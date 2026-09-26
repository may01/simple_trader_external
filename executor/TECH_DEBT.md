# Tech Debt — `trade_executor`

Known unresolved issues, to be picked up as future tasks. One section per item:
what's wrong, why it was deferred, what resolving it looks like.

## 1. `analysis_current` / `analysis_log` — two tables where one plus a cache may do

**Status:** open (flagged 2026-09-20)
**Where:** `migrations/0003_state_store_caches.sql`, `crates/state_store/src/pg.rs:648-700`
(`persist_analysis`, `current_analysis`, `read_analysis_log`)

`persist_analysis` writes every analysis payload twice in one transaction: an
append to `analysis_log`, plus an upsert into `analysis_current` keyed
`(pair, kind)`. `current_analysis` then reads the current-value row by primary
key. `current_levels` and `current_command`
(same migration, `pg.rs:531-646`) are the same family of derived read-cache
tables.

The indicator-broadcast work
([2026-09-19-level-broadcast-design.md](specs/2026-09-19-level-broadcast-design.md) §3)
deliberately did **not** follow this pattern: `indicators` is a single
append-only table, fronted by a write-through/read-through in-process cache on
`StateStoreImpl`. That raised the question this entry records — whether the
analysis pair should converge on the same shape, collapsing to
`analysis_log` alone and deleting `analysis_current` (table, upsert, and the
migration's half of it) in favour of an in-process cache.

Not resolved during that work because it is out of its scope: `analysis_current`
has live callers, its own tests, and a dashboard reading it, and the indicators
case differed in one material respect — **an indicator row carries its own
`expires_at`, so its cache has a natural, self-describing invalidation point.
An analysis row carries only `computed_at`; `state_store`'s own module doc says
freshness policy belongs to the caller.** A cache in front of `analysis_log`
would therefore need a different invalidation rule (write-through only, no
natural expiry), which is viable — the writing process is also the reading one —
but is a design decision, not a mechanical refactor.

**Resolution:** decide whether "append-only log + in-process cache" is the
house pattern for derived current-value state, or whether the current-value
table earns its keep (crash recovery across restarts, cross-process reads by
the visualizer, query-ability from SQL). If the former: fold `analysis_current`
into a cache over `analysis_log`, drop the table in a new migration, and apply
the same review to `current_levels`/`current_command`. If the latter: document
why, and revisit whether `indicators` should gain an `indicators_current` after
all — the two designs should not stay split by accident.

## 2. Indicator cache `Mutex` — one global lock in front of a read-mostly map

**Status:** open (flagged 2026-09-20)
**Where:** [2026-09-19-level-broadcast-design.md](specs/2026-09-19-level-broadcast-design.md) §3
(the cache field itself: `Mutex<HashMap<(String, String), IndicatorReading>>` on
`StateStoreImpl`), following the `last_reconciliation` precedent at
`crates/state_store/src/pg.rs:344-352`

The indicator read-through cache is guarded by a single plain `Mutex` covering
the whole map. That choice was made for the write path and for parity with
`last_reconciliation`, where the lock is held across a synchronous
clone/insert and contention is a non-issue because there is exactly one value
and few touches.

The indicator cache is not that shape. It is read-mostly, keyed by
`(pair, kind)`, and the expected access pattern is *many* indicators pulled
per decision — a strategy reading several kinds for a pair, several pairs in
flight, potentially from concurrent tasks. Every one of those reads takes an
exclusive lock on the entire map, so readers that touch disjoint keys serialize
against each other and against every write. The more indicators the system
broadcasts, the tighter the constraint gets: cost grows with the number of
lookups, not with the amount of contended data.

Not resolved now because the cache does not exist yet in `main` (the design is
written, the implementation is pending) and because the contention is
predicted, not measured — building the simple version first is the right call.

**Resolution:** once the cache is in and the multi-indicator read path is real,
measure lock hold time and wait time under a realistic number of pairs × kinds
before changing anything. If contention is confirmed, the options in rough
order of intrusiveness: (a) a batch read API that takes the lock once and
returns every requested reading, cutting acquisitions rather than widening
concurrency; (b) `RwLock`, letting the many readers overlap and keeping writers
exclusive; (c) sharding by key (`dashmap` or a fixed array of locked buckets),
which removes cross-key contention entirely; (d) an immutable snapshot
(`ArcSwap<HashMap<...>>`) swapped on write, so readers never lock at all — a
good fit for read-mostly data, at the cost of a map clone per write. Whichever
is chosen, keep the "no lock held across `.await`" invariant the original note
calls out.

## 3. `mq_gateway::drive` — misplaced glue that also drops every error

**Status:** open (flagged 2026-09-20)
**Where:** `crates/mq_gateway/src/drive.rs` (whole module; the dropped results at
`:51`, `:70`, `:88`, `:93`), called from `crates/orchestrator/src/system.rs:357`

`drive` spawns three loops — decisions → `engine.handle_decision`, force actions →
`engine.handle_force`, and `engine.subscribe_state_changes()` →
`outbound.publish_state` — and joins them. Three separate things are owed here.

**It is in the wrong crate, by its own admission.** The module doc opens with "this
is orchestration glue that will likely move into L9 (orchestrator) once that exists;
kept here because L4's own Block C acceptance criteria requires proving this round
trip end-to-end". L9 now exists and is the only caller
(`system.rs:357`), so the stated condition for moving it has been met and the
deferral note has outlived its reason. As it stands, `mq_gateway` — a transport
crate — depends on `execution` purely to own wiring that nothing in `mq_gateway`
needs.

**Every fallible call discards its result.** `let _ = engine.handle_decision(..)`,
`let _ = engine.handle_force(..)` and `let _ = outbound.publish_state(event)` mean a
rejected decision, a failed force-close, or a state event that never reached the
outbound topic all vanish with no log, no metric, and no effect on control flow. The
`publish_state` case is the sharpest: it returns `Result<(), MqError>`
(`gateway.rs:26`), and a dropped error there is a position-state event the rest of
the system never sees while the executor believes it published. The final
`let _ = tokio::join!(..)` swallows task panics the same way — a panicked loop leaves
`drive` returning normally, i.e. looking like clean shutdown.

**Each loop is strictly sequential, and stream end is indistinguishable from
shutdown.** The next decision is only picked up after the previous
`handle_decision` has fully completed, so one slow order placement stalls every
decision behind it (force actions ride a separate task, so cancels at least are not
blocked by that queue). And `let Some(..) = next else { break }` exits a loop
silently when its stream ends; because `drive` joins all three, one dead input can
leave the process running with a quietly missing half.

Not resolved during L4 because moving the glue was explicitly out of that layer's
scope, and the error handling was left as-is while `ExecutionEngine`'s error contract
was still settling.

**Resolution:** move `drive` into `orchestrator` (it is the sole caller; check
whether `mq_gateway`'s dependency on `execution` can then be dropped entirely), and
on the way decide the error policy rather than re-implementing `let _ =`: at minimum
log-and-count each failure through `observability`, and state explicitly which
failures are fatal (stop the loop, signal shutdown) versus merely recorded.
Sequential processing is likely correct for decisions — ordering matters — but say so
in a comment instead of leaving it implicit, and consider whether a stream ending
early should tear the whole `drive` down rather than silently shrinking it.

## 4. `current_indicator` coerces an undecodable `kind`/`volume` to `None`

**Status:** open (flagged 2026-09-21)
**Where:** `crates/state_store/src/pg.rs`, `StateStoreImpl::current_indicator`'s inline
`match (kind.as_str(), volume) { … _ => IndicatorKind::None }`

Any stored pair other than `support`+volume / `resistance`+volume maps to
`IndicatorKind::None` — including an unknown `kind` string, and a `support` row whose
`volume` is somehow NULL. The `volume_matches_kind` CHECK makes those rows impossible to
*write* today, so this is latent, not live; but it is the opposite of the
`CorruptRow::Surface` policy every other reader in the crate follows, and it would turn
a future schema/kind addition into silently wrong readings rather than an error.

`PgStateReader::read_current_indicators` (2026-09-21) did **not** reuse this mapping:
it uses a new strict `decode_indicator_kind` helper that returns `StoreError::Decode`.
Fix: have `current_indicator` call `decode_indicator_kind` too, and decide whether a
decode error there should evict the cache entry. Left alone in the indicator-panel work
because that plan's scope said `current_indicator` stays untouched.

## 5. `write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database` is flaky

**Status:** open (flagged 2026-09-21)
**Where:** `crates/market_data/tests/write_path.rs:572`

Failed once in a full `docker compose run --build --rm test` on 2026-09-21 with
`an un-committable final batch must be reported as a timeout, got Ok(())`, then passed
23/23 on an immediate re-run with no code change — and the branch under test did not
touch `market_data` at all. The test races a shutdown deadline against a database made
to fail; when the final batch happens to commit (or be empty) before the failure is in
place, shutdown returns `Ok(())`. Because cargo stops at the first failing test binary,
one flake also hides every later crate's results unless `--no-fail-fast` is passed.
Fix: make the failure injection deterministic (fail the database *before* the batch is
enqueued, or gate the commit on a barrier) rather than relying on timing.


## 6. `indicator_update` accepts an empty `pair`

**Status:** open (flagged 2026-09-21)
**Where:** `crates/mq_gateway/src/wire.rs` (`decode_inbound`, `InboundPayload::IndicatorUpdate` arm)

The wire decoder rejects a `kind`/`volume` mismatch at parse time. It lets `"pair": ""`
straight through, and the row lands in `indicators` under an empty pair. No per-pair
reader (`/api/current_indicators?pair=…`, the SPA panel) will ever surface it. Seen live
on 2026-09-21: main/'s paper stock (`Stock_MockBinance`) had no `get_pair_name()`, so
every reading it published arrived as `pair: ""`, about 135 rows before anyone noticed.
Nothing alerted on either side. The sender is fixed (main/ branch
`stock-pair-and-readonly-candles`), but the executor still trusts whatever it is sent.
Fix: reject an empty or whitespace-only `pair` (and `name`) in the decode arm, as a
`WireError`, with a wire test next to the existing stray-`volume` one. The existing
`pair = ''` rows are append-only history and can be left to age out of "current".


## 7. `order_event.order_id` is `bigint` — cannot hold MEXC order ids

**Status:** **closed 2026-09-25** on branch `mexc-trading-connector` (MEXC trading-connector plan, Layer 1). Migration `0010_order_event_order_id_text.sql` converts the column in place (`ALTER … TYPE text USING order_id::text`) — not the add-a-column route suggested below, because `exchange_adapter::OrderId` itself became `String` (spec D3), so no reader needs the old column; `OrderId`'s deserializer accepts legacy numbers for jsonb written earlier. The reader's `UNION ALL` projections were retyped to `NULL::text AS order_id` with it.
(flagged 2026-09-22)
**Where:** `migrations/0001_init.sql` (`order_event`), `crates/market_data/src/pg/writer.rs` (`insert_order_event_batch`), `crates/market_data/src/pg/rows.rs`

L1 persists observed `AccountEvent::OrderUpdate`s into `order_event` with `order_id bigint NOT NULL`.
Binance order ids are integers, so this works today; MEXC spot order ids are strings, so the first
MEXC order update L1 tries to persist cannot be stored as-is. Found while designing the order journal
([specs/2026-09-22-live-trade-ops-l0-test-design.md](specs/2026-09-22-live-trade-ops-l0-test-design.md) §4.7),
whose new `exchange_order.exchange_order_id` is `text` for this reason; `order_event` was deliberately
left alone there. Fix: additive migration adding `order_id_text text`, backfilled from `order_id`, with
the writer/reader switched to it (never edit 0001 — sqlx checksums, see 0002's header).


## 8. `JournaledAccount` / `OrderJournal` design — review required

**Status:** reviewed 2026-09-23 — user decided to **build as specified** (state row + append-only fills). The
`exchange_order_event` action-log option below was considered and **not adopted**. Item stays open as debt: revisit if
Layer 7's live runs show a cancel or a crash is hard to reconstruct from the state row alone.
**Placement decided 2026-09-25:** the journal leaves `live_trade_ops` for a new production crate
`crates/order_journal` (position-management spec D5/§5.5; live-trade-ops spec §5.0 amended). Production (the orchestrator,
`origin = execution`) needs it, and nothing may depend on `live_trade_ops`. `order_journal` → `exchange_adapter`,
`observability`, `sqlx`; depended on by `live_trade_ops` and `orchestrator`. The move is position-core plan (1/9) Task 1.3.
Rejected: folding it into `state_store` (would pull `exchange_adapter` into `state_store`).
**Where:** [specs/2026-09-22-live-trade-ops-l0-test-design.md](specs/2026-09-22-live-trade-ops-l0-test-design.md) §4.7; plan [plans/2026-09-22-live-trade-ops-plan.md](plans/2026-09-22-live-trade-ops-plan.md) Layer 5, Tasks 5.1–5.3 (`live_trade_ops::journal` — `OrderJournal`, `JournaledAccount`, `PgOrderJournal` — and migration 0008)

The "journal" as specified is not a journal of actions. It is a current-state record:
`exchange_order` is one row per order, **updated in place** (latest status, filled qty,
avg price, exchange order id, rejection); only `exchange_fill` is append-only. The
decorator never changes an order on the exchange; it only records, and it gates sending
on `client_order_id` presence and on a committed intent row.

Points to review:
- **No action history.** A row that says `cancelled` does not show when the cancel was
  requested, which status polls preceded it, or what the exchange returned at each step.
- **Cancels are not write-before-send.** Only `place_order` records intent before sending.
  A crash between sending a cancel and recording its result leaves no trace that a cancel
  was sent.
- **Backward-transition refusals** (§4.7 forward-only status rule) are visible only as
  alerts, not in the DB.
- **Naming.** "Journal" suggests an append-only log; the design is a state table plus fills.

Option raised and **not** adopted in the spec (2026-09-22): an append-only
`exchange_order_event` table (intent, sent, ack, send_unknown, rejected, status_seen,
cancel_requested, cancel_result, fills_seen, backward_refused — timestamp + raw payload),
with `exchange_order` kept as a projection updated in the same transaction, and
`cancel_requested` written before a cancel is sent. Decide on review: keep as specified,
adopt this, or rename to reflect the state-record design.


## 9. `KindAccount::resolve()` panics instead of failing at startup

**Status:** open — must be fixed BEFORE the orchestrator follow-up wires up `EXCHANGE_NETWORK` (flagged 2026-09-23)
**Where:** `crates/orchestrator/src/main.rs:38-45` (`KindAccount::resolve`), against `adapter_config_from_env` (same file, ~line 183-194)

`KindAccount::resolve()` ends in an `.expect()` on the configured kind's accessor, and it runs on **every** `MarketAccount`
call, not once at boot. Since 2026-09-23 the adapters resolve hosts per kind and return `None` for a kind that has no host
on the configured network (Binance margin on testnet; every MEXC kind on testnet) — see
[specs/2026-09-22-live-trade-ops-l0-test-design.md](specs/2026-09-22-live-trade-ops-l0-test-design.md) §4.3 and the
`live-trade-ops` branch.

Dead code today: `adapter_config_from_env` hardcodes `network: Network::Mainnet` and `env_required`s both
`{prefix}REST_BASE_URL`/`WS_BASE_URL`, so every kind resolves through the override branch and never consults the host
table. The moment the orchestrator follow-up (spec §2, "Not covered") starts reading `EXCHANGE_NETWORK` and drops the
forced override, a misconfigured `MARKET_KIND` (e.g. Binance margin + testnet) stops being today's fail-fast typed
boot-time exit (`unwrap_or_else` + `process::exit(1)`) and becomes a panic on the first live call of an already-running
process. Fix: a typed startup check that the configured `MARKET_KIND` is present on the built adapter, before the
process starts trading.


## 10. main/'s per-level `kind` is decoded and then ignored — no real stop/target, and `modify` does nothing

**Status:** open — deferred out of the position-management scope, to be solved in its own scope (flagged 2026-09-23)
**Where:** `crates/local_analysis/src/builder.rs` (`DefaultSignalBuilder::build_signal`, `PLACEHOLDER_STOP_LOSS_PCT` at line 24, `nearest_in_direction` target selection, the `DecisionKind::Modify => SignalAction::NoOp` arm at line ~63), against `crates/local_analysis/src/types.rs` (`LevelKind`, `SignalAction`) and `crates/mq_gateway/src/wire.rs` (`LevelKindDto` → `Level::main_with_kind`)

One root cause, two symptoms. The wire format carries a per-level `kind` (`support | resistance | target | stop_loss`),
`mq_gateway` decodes it, and `Level.kind` holds it — that end of the chain works and has tests. `DefaultSignalBuilder`
is the only consumer, and it never reads the field.

**Symptom 1 — the open path trades its own numbers.**

- the **target** is `nearest_in_direction(combined_levels, open_price, is_long)` — the nearest level on the profit side,
  whatever it is labelled, including one of this process's own detected walls;
- the **stop** is `open_price × (1 ∓ PLACEHOLDER_STOP_LOSS_PCT)`, an unconditional hard-coded 1 %, whatever main/ sent.

So main/ can express its intended stop-loss and target on the wire, the executor stores them, and then trades neither.
Every live `Open` — main/'s and the mock signal's alike — is risked at a flat 1 % of entry.

**Symptom 2 — `modify` is a no-op.** `DecisionKind::Modify => SignalAction::NoOp`, flagged in `builder.rs`'s own comment
as a known gap ("position parameter changes for an already-open position are `position_advisor`'s job"). main/ cannot
amend a live position's stop or target at all. `SignalAction` has no `Modify` variant to map onto.

**Why the two are one item, not two.** A `Modify` carries levels and nothing else. Acting on it means deciding which of
them is the new stop and which is the new target — i.e. reading `kind`, the exact thing symptom 1 is about. Fixing
`modify` without fixing the open path would put two different level-interpretation rules in one builder; fixing the
open path without `modify` leaves main/ able to set risk levels once and never revise them. Whoever takes this scope
needs a single stated contract for what a `kind` means, applied to both paths.

Further couplings to hold in mind:

- The hard-coded stop is what made `builder.rs`'s own documented widening safe ("an `Open` with levels on one side only
  now opens a real position", `builder.rs` ~line 95): a decision can no longer fail to resolve a stop. Honouring
  main/'s `StopLoss` level re-opens that question — an `Open` whose stop level is missing, or on the wrong side of
  entry, needs a defined outcome (fall back to the percentage, or `NoOp`).
- `PLACEHOLDER_STOP_LOSS_PCT` is also the sizing input (`risk_per_trade / |open − stop|`, `crates/execution/src/sizing.rs`),
  so a real stop level changes position size, not just the stop order. The two land together or not at all.
- A `Modify` must not be re-validated through L2's pre-trade `RiskValidator` (`L3-execution.md`: "L3 never re-runs L2's
  pre-trade check once the position exists"), and a new stop on the wrong side of the position's average entry is a
  position fact for `execution` to refuse, not a market fact for `local_analysis` to judge.

Raised as rows B7 and B8 of [specs/2026-09-22-position-management-design.md](specs/2026-09-22-position-management-design.md)
§1.B and deliberately cut from that spec's scope (see its §9). That spec's position model is built to receive the fix —
`OpenPosition` carries `stop_loss_price` and `take_profit_price` as first-class amendable fields, both backed by real
resting orders — so this scope is a `local_analysis` + wire-contract change, not a position-model one.

## 11. `write_path::the_writers_final_batch_is_committed_on_shutdown_not_discarded` is flaky

**Status:** open (flagged 2026-09-25)
**Where:** `crates/market_data/tests/write_path.rs:535`

The sibling of §5, in the same file, with the same shape. Failed once in a full
`docker compose run --build --rm test --no-fail-fast` on 2026-09-25 with
`the row must still be sitting in the writer's batch, or this test is vacuous: left: 1,
right: 0`, then passed 1/1 on an immediate isolated re-run with no code change — and the
branch under test (`position-management`) does not touch `market_data` at all.

What fails is the test's own **vacuity guard**, not its assertion: the test sets
`flush_rows = 10_000` and `flush_interval = 3600s` so that nothing can flush on its own,
ingests one trade, and asserts `SELECT count(*) FROM trade` is still 0 before calling
`shutdown_writer`. The row was already committed. So some path flushes the batch that is
neither the row count nor the interval, and under load it wins the race. Worth knowing
which: if a writer can commit a partial batch at an unintended moment, that is a
production behaviour nobody has described, not just a test nuisance.

Fix: find the third flush trigger (idle/empty-channel drain is the first suspect in
`crates/market_data/src/pg/writer.rs`) and either gate the test on it explicitly or, if
it turns out to be unintended, fix the writer. Do not simply relax the guard — it is the
only thing keeping the real assertion from passing vacuously.

## 12. MEXC spot trading — built, never run live (M1 / M2 / M4 open)

**Status:** open (flagged 2026-09-26)
**Where:** `crates/exchange_adapter_mexc/src/{spot.rs,spot_user_ws.rs,ws.rs}`, `crates/live_trade_ops/src/spot_scenario.rs`
(trade_executor `layer-implementation` @ 2f55ba7, merged from `mexc-trading-connector`; plan
[plans/2026-09-25-mexc-spot-trading-plan.md](plans/2026-09-25-mexc-spot-trading-plan.md), drift in
[specs/2026-09-25-mexc-trading-connector-design.md](specs/2026-09-25-mexc-trading-connector-design.md) §15 "plan 5/5 as built")

**Current state.** Plan 5/5 is fully built and green offline (wiremock on G0 captures, local ws server):

- Orders: `s:SYMBOL:ID` string ids (cancel after restart by stored id), `reduce_only` accepted and not sent,
  `Stop` → `NotSupported`, off-tick / off-step refused (no rounding), unreadable 2xx →
  `Network("accepted-but-unparsed")`, strict status map (unknown → error, never a guess).
- Fills from `myTrades`, client-id lookup (`-2013` → `None`), account-wide `openOrders`, market info per F5 +
  `selfSymbols` tradability, `tradeFee` `data` envelope, spot `classify` code rows, spot token buckets.
- `margin()` → `None`. Capabilities: `native_stop=false`, `reduce_only_enforced=false`, `can_short=false`,
  `order_fills`, `client_id_lookup`, `account_push=true`.
- User-data stream: `listenKey` create / 30 min keepalive / delete, renewal at 23 h, protobuf private
  orders / deals / account → `OrderUpdate` / re-read / `BalanceUpdate`; poll-and-diff stays as fallback.
- `live_spot_trade_ops` scenario (s0–s6) and `configs/live-trade-ops/mexc.spot.mainnet.env.example`.

**What is not proven** — nothing on spot has touched a real order:

1. **M1 not run.** Blocked 2026-09-26: the assistant's permission mode refused to create the live env file
   (real-money action). The operator runs it, or grants a permission rule for live trade-ops runs.
   Unconfirmed until then: the `POST /api/v3/order` response shape, `cummulativeQuoteQty` vs
   `cumulativeQuoteQty`, `myTrades` field names (`isBuyer`, `commissionAsset` on a fee-bearing pair),
   `openOrders` without `symbol` listing a resting order (F8), balance lag after a fill (the scenario
   retries 5 × 1 s), and every spot `classify` row still marked "from docs".
2. **M2 not run.** The private protobuf field numbers (`proto/Private*V3Api.proto`) come from MEXC's
   websocket-proto repo, not a capture. A wrong number degrades silently to the 3 s poll (events decode to
   nothing), so M2 must check push-before-poll explicitly, not just a green run.
3. **M4 not run** (executor live on MEXC spot, `ALLOW_LOCAL_ONLY_STOP=1`); also needs the pos-mgmt
   feed-loss grace.
4. **Plan's `run_fill_sync` integration test not built** (Task 3.1); covered only by unit tests of the
   stream and by `execution`'s own wake-up tests.
5. **Compose defaults:** the `executor` service's spot `REST_BASE_URL` / `WS_BASE_URL` default to Binance.
   A MEXC spot deployment must set `EXCHANGE_REST_BASE_URL=https://api.mexc.com` and
   `EXCHANGE_WS_BASE_URL=wss://wbs-api.mexc.com/ws`.
6. ~~Not pushed~~ — pushed and merged into `layer-implementation` (2f55ba7) on 2026-09-26.

**Fix / close:** run M1 then M2 (reports `runs/<date>-mexc-m1.md`, `-m2.md`), commit captures, replace
"from docs" rows and fixtures with captured ones, then M4. Close when index-plan acceptance rows 3, 5, 8
are green.

## 13. Stop moves are cancel-and-replace — no `amend_stop` (MEXC `planorder/change_price`)

**Status:** open (recorded 2026-09-26; MEXC trading-connector spec D5 / R3)
**Where:** `crates/exchange_adapter/src/lib.rs` (`MarketAccount`), `crates/execution/src/engine.rs` (stop moves,
`upkeep_stop`), `crates/exchange_adapter_mexc/src/futures.rs` (`place_plan_order`, `Surface::Plan`)

Every stop move — trailing, breakeven, the 6-day renewal in `upkeep_stop` — cancels the resting stop and
places a new one. Between the two calls the position has no exchange-side stop, and if the place fails
after the cancel succeeded, it stays without one until the next fill-sync pass re-places it (4/5's
"lost stop" upkeep). Same gap on Binance today. M3 (2026-09-25) exercised it on MEXC futures (F8→F9)
without incident, but the window is real.

MEXC has a modify in place: `POST /api/v1/private/planorder/change_price`
(`symbol, orderId, triggerPrice, price, orderType, triggerType, trend`; 4 / 2 s, the order-place bucket).
The plan order keeps its id, so the `p:SYMBOL:ID` tracked by execution stays valid.

Fix: new trait method `amend_stop(&self, id: OrderId, trigger: Decimal) -> Result<(), AdapterError>`
(default `NotSupported`) behind a `stop_amend` capability; MEXC futures implements it for `p:` ids;
execution prefers it when the capability is set and falls back to cancel-and-replace otherwise. Needs a
captured `change_price` answer (success and a refusal) before any `classify` row is trusted. Binance
has no equivalent (its stops are plain orders), so it keeps cancel-and-replace.

## 14. Continuous reconciliation corrects the store, not the running executor

**Status:** open (flagged 2026-09-26, live MEXC futures M5 prep)
**Where:** `crates/orchestrator/src/system.rs` (`run_reconcile_loop`), `crates/execution/src/engine.rs` (in-memory `positions`)

`run_reconcile_loop` compares `get_account_state` with `state_store` every interval and applies the
exchange's truth to the **store** (`PositionDrift` "extra_locally … the correction is applied"). The
executor's in-memory position map is only seeded from the store at boot, so a running executor never
sees the correction: on 2026-09-26 it kept a position MEXC had closed for 20 minutes while the drift
alert fired every minute. Commit `5163899` (branch `mexc-live-m5`) closes the two paths that caused it
(the lost-update race, and no flat check when the venue refuses a close or drops a stop), but
reconciliation itself still cannot correct a live executor.

Fix: have the reconcile loop hand each correction to the executor (a `Executor::apply_reconciliation`
behind the per-pair lock) instead of only writing the store, or run reconciliation inside the executor.
