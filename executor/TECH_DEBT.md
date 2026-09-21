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
