# Position management — fill-driven position, main/ round trip, logging, visualisation — design

Makes `trade_executor`'s position the authoritative, fill-driven record of what
this system actually holds, reports it back to `main/`, persists its whole
lifetime, and shows it in the visualiser. Per
[main_goal.md](main_goal.md) ("Owns position lifecycle and risk logic once a
position is handed off", "backward message passing to main/ should be available
to notify main about current position state, and actions that were executed")
and [specs/layers/L3-execution.md](layers/L3-execution.md).

This is a **correctness** spec before it is a feature spec. The position is
currently written at order-*submission* time; an unfilled entry or unfilled
close makes the executor's belief and the exchange's truth diverge silently
until the next process restart. Everything else here (P&L, main/ round trip,
history, records panels) is unbuildable on that foundation and is specified on top of
the fix, not beside it.

**Branch:** `position-management`, cut from `layer-implementation` in the
`trade_executor/.worktrees/layer-implementation` worktree.

**Hard dependency:** [2026-09-22-live-trade-ops-l0-test-design.md](2026-09-22-live-trade-ops-l0-test-design.md)
must be merged to `layer-implementation` first. This spec is written against the
post-live-trade-ops world and consumes, as production API, what that spec builds
as test-only: `Fill`, `MarketAccount::get_order_fills`, `settle`,
`OrderRequest::client_order_id`, `RejectReason`, `MarginOps`/`FuturesOps`,
`JournaledAccount`/`OrderJournal` (promoted to `crates/order_journal`, D5),
migration `0008_order_journal.sql`. Nothing
here may start before `cargo test` is green on a `layer-implementation` that
contains it.

**Blocked on, additionally:** [../TECH_DEBT.md](../TECH_DEBT.md) §8 (the
`JournaledAccount`/`OrderJournal` review — state-row vs. append-only action log,
cancels not write-before-send). §5.5 below wraps the orchestrator's real account
in that decorator, so the review's outcome changes what gets persisted for every
production order. **Resolved:** design reviewed 2026-09-23 (build as specified);
placement decided 2026-09-25 (own crate `order_journal`, D5).

---

## 1. Audit — required capability vs. current code

Evidence paths are relative to `trade_executor/.worktrees/layer-implementation`
unless stated otherwise.

### A. Position core

| # | Capability | Status | Evidence |
|---|---|---|---|
| A1 | Flat/Open state per pair | **DONE** | `crates/execution/src/types.rs` `PositionState`/`PositionStatus`/`OpenPosition` |
| A2 | In-memory owner + boot seeding | **DONE** | `Executor.positions: Mutex<HashMap<Pair, PositionState>>`; `seed_position` called from `crates/orchestrator/src/system.rs` step 5 |
| A3 | Risk-based sizing + account-limit check | **DONE (placeholder depth)** | `crates/execution/src/sizing.rs` — `risk_per_trade / |open − stop|`, notional ≤ `free_quote × max_notional_fraction`. No margin/leverage/liquidation-distance check; documented as placeholder in the module's own doc comment |
| A4 | Dual stop-loss (in-process watcher + resting native stop) | **DONE** | `engine.rs` `run_stop_loss_watcher`, `open_position`'s `OrderKind::Stop` reduce-only leg, `OpenPosition::stop_order_id` |
| A5 | Trailing stop-loss | **DONE** | `engine.rs` `run_advisor_loop` → `local_analysis::DefaultPositionAdvisor::advise` → `apply_stop_loss_move` (cancel + replace, `StopLossMoved`) |
| A6 | Force close bypassing `local_analysis` | **DONE** | `engine.rs` `handle_force(ForceKind::CloseNow)` |
| A7 | Command for an already-closed position is a no-op | **DONE** | `handle_decision` → `PositionStateEvent::AlreadyClosed` |
| A8 | **Entry order id tracked** | **GAP** | `open_position` calls `place_order(entry)` and discards the `OrderAck`. Only `stop_order_id` is retained. Nothing in the process can look the entry order up again |
| A9 | **Position reflects fills, not submissions** | **GAP (correctness)** | `open_position` inserts `Open` with `size` = computed size and `open_price` = *intended* limit price immediately after `place_order` returns. `do_close` writes `Flat` immediately after placing the reduce-only close limit |
| A10 | **`AccountEvent::OrderUpdate` updates the position** | **GAP** | `system.rs` `run_position_sync` uses an order update only as a trigger to re-`persist` the *unchanged* snapshot, and only when the pair is already `Open` (`system.rs:1084`). No field is ever mutated by an exchange event |
| A11 | Partial fills | **GAP** | No `filled_qty` anywhere on the position; `OrderInfo::filled_qty` is never read by `execution` |
| A12 | Average fill price / slippage | **GAP** | `open_price` is the intended price forever |
| A13 | Fees | **GAP** | Nothing in `execution` reads fees. `MarketAccount::get_fees` has no caller in `execution` |
| A14 | Realized P&L | **GAP** | `PaperMarketAccount::pnl()` exists (`crates/execution/src/paper.rs:59`) and is never read into position state. Real accounts have no equivalent |
| A15 | Unrealized P&L / mark price | **GAP** | `run_advisor_loop` has the trade price in hand every tick and uses it only for the stop comparison |
| A16 | Take-profit acted on at all | **GAP** | `close_price` is a number on `OpenPosition` that nothing ever compares a price against. `run_stop_loss_watcher` checks only the stop side; `run_advisor_loop` reads `current_close_price` only to hand it to the advisor. A position that reaches its target sits there until main/ sends a `close` — see D7 for how it is triggered, and why it stays a *local* trigger |
| A17 | Leverage / margin type / liquidation price | **GAP** | `exchange_adapter::PositionInfo` carries `leverage`/`liquidation_price` and `FuturesOps::position_risk` (post-live-trade-ops) carries the full set; `OpenPosition` has no field for any of them |
| A18 | Liquidation-proximity risk loop | **GAP** | Required by `L3-execution.md` ("Margin/liquidation proximity tracked as a distinct, higher-priority risk"). `observability::AlertKind::LiquidationNear` exists with **zero producers** |
| A19 | Scale-in / partial close | **GAP (hazardous)** | `open_position` overwrites `positions[pair]` unconditionally, orphaning the previous position's live exchange-native stop order. Mitigated today only by a guard in the *orchestrator* (see A20) |
| A20 | Already-open guard | **DONE, in the wrong crate** | `system.rs` `run_signal_decision_task` guards 1 (already open) and 2 (cooldown) exist precisely because of A19, and deliberately not in `Executor` — adding them there would change main/'s path. Documented residual race with `mq_gateway::drive` |
| A21 | Position identity / traceability | **GAP** | No `position_id`. A position cannot be joined to the `decision_id` or `signal_id` that produced it, nor to its orders |
| A22 | Timing (created_at, closed_at, max hold) | **GAP** | No timestamps on `OpenPosition`. main/ has `open_time` + `close_by_time`; the executor has neither |
| A23 | Mid-run drift detection | **GAP** | `reconcile` runs at boot only (`system.rs` step 5). `last_reconciliation()` is in-memory and lost on restart |

### B. Communication with main/

| # | Capability | Status | Evidence |
|---|---|---|---|
| B1 | Outbound transport | **DONE** | `crates/mq_gateway/src/zmq_transport.rs` — executor PUSH binds `outbound_bind_addr`; chosen over PUB/SUB so a message queues for a disconnected peer |
| B2 | Outbound encoder | **PARTIAL** | `wire.rs::encode_outbound`. Only `Opened` carries state; every other event emits `flat_state()` — `status: "flat_or_unchanged"`, all fields `null` (`wire.rs:307`) |
| B3 | Event kinds | **PARTIAL** | `L4-mq-gateway.md` lists `opened|closed|stopped_out|filled|state_update`. Nothing emits `"filled"` — documented in `wire.rs`'s own module doc. `NotPlaced` (with its rejection reason), `AlreadyClosed` and `StopLossMoved` are all flattened into `state_update` with a null body |
| B4 | **main/ consumer** | **GAP** | `main/mq/` contains only `indicator_publisher.py`. Nothing in `main/` opens a PULL socket on the outbound topic. Every position event the executor has ever published has been sent into a void |
| B5 | Per-decision ack/nack | **GAP** | Outbound carries no `id` — by design in `L4-mq-gateway.md` ("it's a state report, not a request"). Consequence: main/ cannot learn that its decision was refused or why |
| B6 | Snapshot / resync | **GAP** | A restarted main/ has no way to ask what the executor holds |
| B7 | main/ supplies real risk levels | **GAP — deferred, not in this scope** | `LevelKind::{Target, StopLoss}` exists on the wire and is decoded into `Level.kind`, but `DefaultSignalBuilder` ignores `kind` entirely: target = `nearest_in_direction(combined_levels)`, stop = hard-coded `PLACEHOLDER_STOP_LOSS_PCT = 0.01` (`crates/local_analysis/src/builder.rs:24`). Recorded with B8 as [../TECH_DEBT.md](../TECH_DEBT.md) §10 — see §9 |
| B8 | `modify` does something | **GAP — deferred, not in this scope** | `DecisionKind::Modify` → `SignalAction::NoOp` (`builder.rs:63`), flagged there as a known gap. main/ cannot amend a live position. Same root cause as B7 (a `modify` carries only levels, so acting on it means reading `Level.kind`) — recorded together as [../TECH_DEBT.md](../TECH_DEBT.md) §10 |
| B9 | main/ has a position model to receive this | **DONE, unconnected** | `main/position/` — `BasePosition`/`LongPosition`/`ShortPosition`/`Position` facade with graduated entry/exit lists, `record_entry_fill`/`record_exit_fill`, `avg_price_open/close`, `finalize()` → `(revenue_pct, revenue_abs)` net of `2 × fee`, and a `change_history` drained per tick. Only the aggregate half of it is used from the executor feed — §6.4 |
| B10 | **Two independent live order paths** | **ARCHITECTURAL CONFLICT — closed by this spec** | `main/robots/robot.py` `_open_position`/`_close_position`/`_stop_loss` place real orders through `self.stock` and track them in `main/robots/live_order_tracker.py` (`LiveOrderTracker`: order ids, `check_fill`, margin loan id/amount, atomic JSON persistence). The executor places its own orders through `exchange_adapter`. Neither knows about the other. main/'s write path is **disabled, not deleted** — D2 / §6.5 |

### C. Logging

| # | Capability | Status | Evidence |
|---|---|---|---|
| C1 | Current position persisted | **DONE, but as a snapshot** | `position_state` (one row per pair, jsonb), overwritten in place; `state_store::StateStore::persist`, written live by `run_position_sync`. A failed `persist` leaves the on-disk row asserting a *previous* state — the failure mode its own call site documents at `system.rs:1110`. Replaced by an append-only log, D12 / §5 |
| C2 | Position lifecycle events persisted | **PARTIAL** | `event_log` via `log_event`. Payloads are thin: `Closed` carries only `close_price`; `StoppedOut` only `stop_price`; `AlreadyClosed` only the pair. No size, fill, fee or P&L on any of them. Absorbed into the same append-only log, D12 / §5 |
| C3 | Decision audit | **DONE** | `decision_log` + `current_command`; `log_decision` called by `run_signal_decision_task`, fails closed |
| C4 | Signal audit | **DONE** | `signal_log` + `record_signal`, with `decision_id` linkage |
| C5 | Orders the executor *sends* | **GAP → arrives test-only** | `order_event` (migration 0001) holds only `AccountEvent::OrderUpdate`s L1 happened to observe. `exchange_order`/`exchange_fill` (migration 0008) will exist but with `origin = 'livetest'` only; the `origin` column exists for `execution`, wrapping the orchestrator's account is explicitly called a follow-up |
| C6 | Closed-position history | **GAP** | `position_state` is a current-snapshot table by design ("not an append-only log" — `state_store`'s own module doc). A closed position leaves no row anywhere describing what it was. Fixed by replacing the snapshot with an append-only log rather than adding a second table beside it, D12 / §5 |
| C7 | Position metrics | **GAP** | Only `mock_signal_crossing` / `mock_signal_crossing_skipped` exist (`system.rs`). No counter, latency, slippage or P&L metric |
| C8 | Position alerts | **PARTIAL** | `OrderPlacementFailed` and `PersistFailed` fire. `LiquidationNear` has no producer. No alert for an entry that never fills, a close that never fills, or mid-run drift |
| C9 | `order_event.order_id` can hold MEXC ids | **GAP** | `bigint`; MEXC spot ids are strings — [../TECH_DEBT.md](../TECH_DEBT.md) §7 |

### D. Visualiser

| # | Capability | Status | Evidence |
|---|---|---|---|
| D1 | Position panel | **PARTIAL** | `crates/visualizer_server/static/js/pair.js` `renderPositionSummary` — status text only |
| D2 | Entry / SL / target price lines | **DONE** | `static/js/chart.js` `setPositionLines` |
| D3 | Position-event markers on the chart | **DONE** | `chart.js` trade-marker line series, one dot per event, per the trade-visualisation design |
| D4 | Position-events panel | **DONE** | `pair.js` `renderPositionEventsPanel` ← `GET /api/pair_events` ← `VisualizerBackend::position_events` |
| D5 | Overview row per pair | **PARTIAL** | `routes.rs` `/api/pairs` → `PairSummaryDto { pair, position, freshness }`, position from `load_all` (status only) |
| D6 | Size / avg entry / P&L / fees / R-multiple / liq price | **GAP** | None of these exist to render. Delivered as fields on the Position panel — §8.2 |
| D7 | Orders and fills | **GAP** | No route, no DTO, no panel. Delivered as two record panels, not chart markers — §8.2 |
| D8 | Closed-position history | **GAP** | Nothing to read (C6). Delivered as a Closed-positions record panel with a totals footer; the equity curve is explicitly dropped — §8.2, §9 |
| D9 | Live push of position state | **GAP** | `/ws` is candle/trade/book only (stated in `pair.js`'s own header comment); the position panel polls |
| D10 | Operator context (disarmed, drift) | **GAP** | `EXECUTION_MODE=no_trade` is visible only in the executor's stdout. A reconciliation discrepancy is visible nowhere |

---

## 2. Decisions taken (2026-09-22)

**D1 — The executor is the single owner of live position state.** Per
`main_goal.md`. main/ decides; the executor executes and reports. main/'s
`Position` becomes a **read model** fed from the outbound stream, not a second
source of truth.

**D2 — the executor becomes the only process that places real orders.**
main/'s direct order path (B10) is **disabled, not deleted**: the code stays,
commented at every site with what replaced it and how to re-arm it, and is
refused at one boundary rather than being cut out of `robot.py` (§6.5). Two
reasons it is disabled rather than removed. Deleting it would take
`LiveOrderTracker`'s loan bookkeeping and crash-recovery JSON with it, and
those describe positions that may exist on the exchange *right now*; and a
disabled path can be re-armed in one env var if the executor turns out not to
be ready, whereas a deleted one cannot. Running both against one account
double-trades — with D2 that is no longer an operational convention nobody can
enforce, but a refusal in code, symmetric with the executor's own
`NoTradeAccount`.

**D3 — Position becomes fill-driven, and `Opening` resolves once.** No state
transition on a submission. The status machine is
`Flat → Opening → {Open | Closing | Flat} → Closing → Flat`, and only an
observed fill (or a reconcile against the exchange) moves it.

`Opening` is **not** left on the first fill. It holds until the entry order
reaches a terminal state — fully filled, or cancelled / rejected / expired,
partial fills included — and only then does the *final* filled quantity decide
where the position goes: nothing filled → `Flat`; something filled → `Open`,
or straight to `Closing` if a close was asked for while the entry was still
working. One decision on settled facts, rather than a status that flips on the
first fill and then has to be re-derived on every subsequent one. A partial
fill during `Opening` is still *reported* (`PartiallyFilled`, growing
`net_size`) — the event stream is continuous, the status is not.

**D4 — `settle()` is promoted from `live_trade_ops` to `exchange_adapter`**, as
[2026-09-22-live-trade-ops-l0-test-design.md](2026-09-22-live-trade-ops-l0-test-design.md)
§4.5 already sanctions ("if `execution` needs fee-aware PnL later, `settle` moves
to `exchange_adapter` and both call it, so they cannot disagree"). Fee arithmetic
exists once in this system, and `live_trade_ops` calls the promoted copy.

**D5 — Every production order carries a `client_order_id` minted by
`execution`**, and the orchestrator's account is wrapped in `JournaledAccount`
with `origin = "execution"`. No order can reach an exchange without a committed
intent row. **The journal is promoted from `live_trade_ops` to a new production
crate, `crates/order_journal`** (decided 2026-09-25): `JournaledAccount`,
`OrderJournal`, `PgOrderJournal` and the in-memory journal lived in
`live_trade_ops::journal`, and live-trade-ops §5.0 forbids any workspace crate
depending on `live_trade_ops` (acceptance: `cargo tree -i live_trade_ops` lists
nothing). Same reasoning as D4 — code production needs leaves the test crate
instead of production depending on it. `order_journal` depends on
`exchange_adapter`, `observability` and `sqlx` only; `orchestrator` and
`live_trade_ops` both depend on it. Chosen over folding it into `state_store`,
which would make `state_store` depend on `exchange_adapter` for `MarketAccount`
and reopen live-trade-ops' "`state_store` untouched" scope line. Format, borrowing live-trade-ops §5.4's constraints (`[a-z0-9-]`,
≤ 32 chars): `x-{pos16}-{role}-{n}` where `pos16` is the **last 16 hex digits**
of the `position_id` with hyphens stripped, `role ∈ {e, x, s}` (entry, exit,
stop — there is no target order, D7) and `n` is a per-position monotonic
counter. The `livetest-` prefix stays reserved for the live test.

**Why 16 and why the last 16** (amended 2026-09-25, after review). An earlier
draft used the *first* 8 hex digits — 32 bits. `exchange_order.client_order_id`
is a global `PRIMARY KEY` (migration `0008`), so two positions colliding on
that prefix and placing the same role at the same counter produce a primary-key
violation inside `record_intent`, which fails closed: the order is never sent
and the position silently fails to open. Birthday arithmetic on 32 bits gives
~1.2 % after 10 000 positions and 50 % after 77 000 — weeks, not years, at this
system's rate. 16 hex digits is 64 bits, and taking the *low* half is
deliberate: uuid v4 fixes 4 version bits in byte 6 (high half) against 2
variant bits in byte 8, so the low 64 bits carry 62 bits of entropy where the
high 64 carry 60. 62 bits puts 50 % collision at ~2.3 × 10⁹ positions.

Character budget: `x-` (2) + 16 + `-` + role (1) + `-` = 21, leaving 11 digits
for `n` inside the 32-char limit. Hex rather than base36 (which would fit the
same 62 bits in 12 characters) because the three saved characters are not
needed and, during a live incident, a `client_order_id` should be eyeballable
against a `position_id` in the database without decoding.

**A collision is still made loud, not merely unlikely.** `JournalError` gains
`DuplicateClientOrderId { client_order_id }`, mapped from Postgres SQLSTATE
`23505` in `record_intent`, alerted at `Severity::Critical`. Behaviour is
unchanged — fail closed, no order sent — but the cause becomes nameable. At 62
bits this cannot fire from a birthday collision, so if it ever fires the cause
is a bug (a replayed intent, a reused position id, a restored database
overlapping a live run), and those are exactly the things that must not arrive
disguised as a generic write failure.

The detection already exists: `PgOrderJournal::record_intent` matches
`is_unique_violation` (SQLSTATE `23505`) today and wraps it in
`JournalError::Write(..)`. The change is the new variant plus that one branch
returning it, not new detection logic. The alert goes out through the journal's
existing path — `AlertKind::PersistFailed`, tag `component=order_journal`,
message prefix `OrderJournalDuplicateClientOrderId:` (§7.3) — not through a new
`AlertKind`.

**Nothing joins by this prefix.** `exchange_order.position_id` (§5.4) is the
join key. The prefix exists for human reading and for looking an order up by
client id after a restart, and `parse_client_order_id`'s doc comment says so.

`livetest-{run8}-{step}` keeps its 32-bit `run8` unchanged: live runs are
manual and number in the tens, and the `x-` / `livetest-` prefixes make
cross-family collision impossible.

**D6 — Two fill sources, one truth.** `AccountEvent::OrderUpdate` (pushed, fast,
carries `filled_qty`/`avg_fill_price`, no fees) updates the position
immediately. `get_order_fills` (pulled, authoritative, carries fees and futures
`realized_pnl`) settles it. A position's P&L is marked `provisional` until
`Σ fill.qty == OrderInfo.filled_qty` for every terminal order, using
live-trade-ops §4.5's own fill-lag rule (poll, 10 s timeout).

**D7 — Take-profit is a local trigger, not a resting order.** Nothing for the
target sits on the exchange. The executor watches the position in-process and,
when an exit trigger fires, places the exit order *then* — an ordinary
`reduce_only` limit, the same `Exit` order a main/ `close` decision produces.
The stop keeps its resting exchange-native leg; the two legs are deliberately
**not** symmetric.

The asymmetry is the whole point, and it follows `main_goal.md`'s own
reasoning for the dual stop-loss ("protection must survive this process or its
feed dying"). What a resting leg buys is survival of this process dying. For a
stop that is the difference between a bounded loss and an unbounded one. For a
target it is the difference between taking profit now and taking it when the
process comes back — a missed opportunity, not a loss. Paying for it with a
resting order costs real things: an order that cannot react to anything
(`local_analysis` sees walls and signals the exchange does not), a second leg
to keep re-sized on every partial entry fill, a cancel-race on every close, and
on venues without OCO a permanently-orphanable order. None of that is worth
buying protection against a risk that is not a loss.

**The trigger.** Evaluated in-process for an open position, whichever comes
first:
- a `SignalEvent` on this pair from `local_analysis::subscribe_signals` that the
  exit policy treats as a close — this is `L3-execution.md`'s "ongoing risk
  logic ... reacting to `local_analysis`'s live `walls`/`subscribe_signals` for
  timing", which is the requirement this decision actually satisfies;
- `take_profit_price` reached on a trade tick, as a backstop for the case where
  no signal fires at all.

Either path emits `TargetHit` and goes through the same `do_close` every other
close uses — no separate placement mechanics, per `main_goal.md`'s "no shortcut
bypasses it".

**Stated consequence:** if this process is down when the target is reached, the
target is not taken. That is accepted, and it is the one thing an operator must
know about the design rather than discover. The stop, which is the leg that
matters, is unaffected.

**D8 — Exchange is truth, continuously.** `reconcile` runs on a timer
(`RECONCILE_INTERVAL_SECS`, default 60) as well as at boot, and its report is
persisted.

**D9 — The wire format gains a `schema` field and is versioned additively.**
`schema: 2` on outbound; a reader that does not understand a field ignores it.
The nested-vs-flat `payload` drift already documented in `L4-mq-gateway.md` is
**not** fixed here (out of scope, §9).

**D10 — One position per `(pair, market_kind)`, one-way mode only.** Hedge mode
(simultaneous long and short on one symbol) is out of scope; `FuturesOps::
is_hedge_mode` returning `true` is a boot-time `ConfigError`, not something the
position model bends around.

**D12 — position persistence is an append-only log, not a snapshot.**
`position_state` — one row per pair, overwritten in place — is retired. Every
state change appends a row carrying the triggering event *and* the full
resulting state; "current" is the newest row per pair. This is one change
answering three audit rows at once: C6 (a closed position left no record),
C2 (`event_log`'s thin payloads, now the same row's `event` column beside a
complete `state`), and C1's failure mode — a failed append leaves the last good
row intact and a gap in the history, where a failed overwrite leaves the on-disk
row *confidently wrong*, which is the hazard `system.rs:1110`'s own comment
describes. It also matches the direction [../TECH_DEBT.md](../TECH_DEBT.md) §8
argues for on the order journal, so the two stores do not disagree about what
persistence means here.

**D11 — Scale-in and partial close are modelled from the start** (entry and exit
execution lists, net size, weighted average prices). This removes the A19 hazard
at its root, which in turn lets the orchestrator's already-open guard (A20) be
deleted. The cooldown guard stays — it is a signal-pacing concern, not a
position-model one. A scale-in does not re-enter `Opening` (§3.1): that state
exists to resolve "is there a position at all", a question an `Open` position
has already answered.

---

## 3. Position model

### 3.1 Status machine

```
                          entry order TERMINAL (filled / cancelled / rejected / expired)
                                     │
Flat ──open decision──▶ Opening ─────┼── filled = 0 ──────────────────────────▶ Flat
 ▲                                   ├── filled > 0, no close pending ────────▶ Open
 │                                   └── filled > 0, close pending ───────────┐
 │                                                                   │        │
 │                                      close decision / force / stop / target │
 │                                                                   ▼        ▼
 └────────────────────────── all exits filled ──────────────────── Closing ◀──┘
```

- `Opening` — the entry order is working. It holds through partial fills: the
  position reports each one and `net_size` grows, but the status does not move
  until the entry order is terminal. Nothing else about the position is decided
  while it is in flight.
- **The `Opening` exit is one decision on the final filled quantity**, taken
  when the entry order reaches a terminal status (`Filled`, `Cancelled`,
  `Rejected`, or cancelled by `ENTRY_FILL_TIMEOUT_SECS`):
  - filled = 0 → `Flat`, event `NotFilled { reason }`. Nothing was bought; there
    is nothing to protect, close or record beyond the attempt.
  - filled > 0, nothing asked to close in the meantime → `Open`.
  - filled > 0 and a close *was* asked for while the entry was working (a main/
    `close`, a `force_close`, a stop trigger, a target trigger) → `Closing`
    directly, for the quantity that actually filled. The request is held as
    `pending_close: Option<CloseReason>` on the position and applied here, not
    dropped and not raced against the entry: placing an exit against a size
    still being filled is exactly how a partial fill becomes an unhedged
    remainder. The working entry *is* cancelled once (I-10, 2026-09-26: left
    working, it filled against the flip that asked for the close), but no exit
    is placed until the cancel has made the entry terminal and this rule has
    run on what actually filled.
- `Open` — net size ≠ 0, no entry order working. A scale-in (D11) places a
  further entry against an `Open` position and **leaves the status `Open`** —
  `Opening` is the initial-entry state only. There is already a position to
  protect and to close; making a scale-in re-enter `Opening` would make an open
  position temporarily un-closable, which is the opposite of what that state is
  for.
- `Closing` — exit order(s) live for the whole remaining size. Partial exit
  fills reduce net size; the position stays `Closing` until net size is 0.
- There is no `Closed` status. A fully closed position appends a terminal
  `closed` row to `position_log` (§5) and the pair returns to `Flat`.

A `Modify` decision reaches `execution` today and resolves to `NoOp` before
any of this (row B8, deferred — §9). The model is nonetheless built to receive
it: `stop_loss_price` and `take_profit_price` are first-class amendable fields,
and amending either changes no status. Amending the stop is a cancel-and-replace
against the resting leg; amending the target is a field write
only, since nothing for the target rests on the exchange (D7). So the fix, when
it lands, is a `local_analysis` change, not a position-model one.

### 3.2 Types

In `crates/execution/src/types.rs`:

```rust
pub struct PositionId(pub uuid::Uuid);

pub enum PositionStatus { Flat, Opening(OpenPosition), Open(OpenPosition), Closing(OpenPosition) }

pub struct OpenPosition {
    pub id: PositionId,
    pub side: Side,
    pub market_kind: MarketKind,

    // intent — what was asked for
    pub target_size: Decimal,          // what sizing computed
    pub intended_open_price: Decimal,  // ex-`open_price`; kept, for slippage
    pub stop_loss_price: Decimal,
    pub take_profit_price: Decimal,    // ex-`close_price`

    // truth — what the exchange did
    pub entries: Vec<Fill>,            // exchange_adapter::Fill, as get_order_fills returns it
    pub exits: Vec<Fill>,
    pub net_size: Decimal,             // Σ entry qty − Σ exit qty
    pub avg_entry_price: Option<Decimal>,
    pub avg_exit_price: Option<Decimal>,
    pub fees: Vec<(String, Decimal)>,  // per fee asset, as `settle` reports
    pub realized_pnl: Option<Decimal>,
    pub settlement_complete: bool,     // D6: every terminal order's fills accounted

    // live orders
    pub orders: Vec<(OrderRole, OrderInfo)>,   // exchange_adapter::OrderInfo + the one thing it lacks

    // leverage / margin (None on spot)
    pub leverage: Option<u32>,
    pub margin_type: Option<MarginType>,
    pub liquidation_price: Option<Decimal>,
    pub maint_margin: Option<Decimal>,

    // a close asked for while the entry was still working (§3.1)
    pub pending_close: Option<CloseReason>,

    // provenance and timing
    pub decision_id: Option<DecisionId>,
    pub signal_id: Option<SignalId>,
    pub created_at: Ts,                // when this position was created (intent), not when it filled
    pub closed_at: Option<Ts>,
}

pub enum OrderRole { Entry, Exit, Stop }   // no TakeProfit -- D7: the target never becomes a resting order
```

**No new order or fill type.** Both already exist in `exchange_adapter` and are
used as they are:

- **A fill is `exchange_adapter::Fill`** (live-trade-ops §4.5) — `trade_id`,
  `order_id`, `pair`, `side`, `price`, `qty`, `quote_qty`, `fee`, `fee_asset`,
  `is_maker`, `realized_pnl`, `ts`. It is exactly what `get_order_fills`
  returns and exactly what `settle` consumes, so `entries`/`exits` hold the
  adapter's own values with nothing copied field-by-field into a parallel
  shape that could drift from it.
- **An order is `exchange_adapter::OrderInfo`** — `id`, `pair`, `side`,
  `status`, `filled_qty`, `avg_fill_price`, `client_order_id`. It is what
  `place_order`'s ack and every `AccountEvent::OrderUpdate` already carry, so
  the position stores what the exchange said rather than a local rewrite of it.
  The *requested* terms (`qty`, `price`, `stop_trigger_price`, `reduce_only`)
  are not re-held in memory: `stop_loss_price` on the position is the only one
  `execution` acts on, and the full `OrderRequest` is already persisted by the
  journal (`OrderIntent { client_order_id, request: OrderRequest, … }`,
  live-trade-ops §4.7) and served to the visualiser from `exchange_order`
  (§8.1) — one record of what was asked for, in the store built for it.

`OrderRole` is the single genuinely new type, and it is an enum, not a struct:
"which leg is this" is a fact about the position's use of an order that no
exchange type carries. It could be parsed back out of `client_order_id` (D5
encodes it), and deliberately is not — recovering a domain fact by string
parsing is how that fact stops being checked by the compiler.

`PositionState { pair, status }` keeps its shape. `OpenPosition::size`,
`open_price` and `close_price` are **renamed, not merely supplemented** —
`net_size`, `intended_open_price`/`avg_entry_price`, `take_profit_price` — so
every existing read site is forced through review by the compiler rather than
silently continuing to read a submission-time number.

`OpenPositionView` (the `local_analysis::PositionAdvisor` input) gains
`avg_entry_price`, `net_size` and `unrealized_pnl`, so a future advisor can
trail on realised risk rather than on intent. `DefaultPositionAdvisor`'s
behaviour is unchanged in this spec.

### 3.3 Sizing

Unchanged formula (`sizing::compute_size`). Two additions:

- `within_account_limits` gains a leverage-aware branch for margin/futures:
  notional ≤ `available_balance × leverage × max_notional_fraction`, read from
  `FuturesOps::futures_margin_summary` / `MarginOps::margin_balances` rather
  than from the spot `free` balance, which does not exist for a futures wallet.
- A `min_notional` / step-size check against `MarketInfo` before placement —
  today a size below the exchange's minimum is discovered as a `RejectReason::
  BelowMinNotional` after the round trip. Rejecting locally is cheaper and
  produces a `NotPlaced` with a usable reason.

Scale-in sizes the *increment*, not the total, and the account-limit check runs
against the position's post-increment notional.

### 3.4 Order choreography

**Open.** Mint `position_id` → `record_intent` (via `JournaledAccount`) → place
entry → status `Opening`. Nothing else is sent while the entry works.

**Entry terminal → resolve (§3.1).** The **stop** — the only resting protective
leg (D7) — is placed here, **once**, sized to the final filled quantity, when
the resolution is `Open`. Resolving to `Closing` places the exit instead and no
stop at all (a stop plus an exit for the same size is a second exit on any
venue where `reduce_only` is not honoured); resolving to `Flat` places nothing.

This is two deliberate changes from today, where the stop goes out immediately
at the full *intended* size. A stop for a quantity that was never filled is
itself an over-close risk. And sizing it once, on a settled number, removes the
cancel-and-replace-per-partial-fill churn the first draft of this spec called
for — each of those replacements was a window with no stop resting at all.

`take_profit_price` is recorded on the position and nothing is sent for it.

**What protects a partially filled position while `Opening`.** The fast
in-process leg (`run_stop_loss_watcher`) arms as soon as `net_size > 0`, before
the resting leg exists — it reads the position map, which is already being
updated per fill. So the local leg covers the `Opening` window and the resting
leg covers everything after. Stated plainly because it is the one gap this
design has: between the first partial fill and the entry going terminal, the
exchange-side leg is absent, so a process death in that window leaves a small
unprotected position. It is bounded by `ENTRY_FILL_TIMEOUT_SECS` (default 120)
and by the entry size, and it is the price of one correctly-sized stop instead
of a sequence of racing ones. If the local leg fires in that window, it sets
`pending_close = Some(Stop)` and the resolution takes it to `Closing`.

A failure to place the stop remains `AlertKind::OrderPlacementFailed` at
`Severity::Critical`, as today — and additionally sets
the `Stop` role's `OrderInfo.status` to `Rejected`, which is what the
visualiser renders as an unprotected position (§8).

**Close.** If the position is `Opening`, the request is recorded as
`pending_close` and applied at resolution (§3.1). The working entry is cancelled
once (`entry_cancel = CloseRequested`), and resolution waits for it to be
terminal (I-10). If it is `Open`: cancel the resting stop →
place exit for `net_size` reduce-only → status `Closing`. `Flat` is written only
when `net_size` reaches 0. One cancel, not two — there is no target order to
race.

**Stop fires (fast local path).** `run_stop_loss_watcher` is unchanged in
mechanism. Its `do_close` now moves the position to `Closing`, not `Flat`.

**Target fires (local trigger, D7).** The exit-trigger evaluation lives with
`run_advisor_loop`, which already subscribes to the same tick stream and already
holds the open position's view — it gains the `subscribe_signals` arm and the
`take_profit_price` comparison. On a trigger it emits `TargetHit` and calls the
same `do_close`, at the current price. No new task: a second loop reading the
same two streams to reach the same `do_close` would be a race with itself.

**Timeouts.** Two, both new:
- `ENTRY_FILL_TIMEOUT_SECS` (default 120): an `Opening` position whose entry is
  still working is cancelled. *As built (I-10, 2026-09-26):* the timeout is
  `SignalAction::Open.max_wait` (`SIGNAL_MAX_WAIT_SECS`, 300 in compose),
  stored as `entry_expires_at` and checked on every order poll. There is no
  separate `ENTRY_FILL_TIMEOUT_SECS` knob. An expired entry that filled nothing
  reports `NotFilled` "entry expired unfilled after max_wait". The cancel is what makes the entry terminal; the
  resolution rule (§3.1) then decides, so a *partially* filled entry becomes
  `Open` at the filled size, not `Flat`. `NotFilled { reason }` is emitted only
  when nothing filled at all.
- `EXIT_FILL_TIMEOUT_SECS` (default 120): a `Closing` position still holding
  size escalates — cancel the resting exit and re-place at the current price,
  and fire `AlertKind::OrderPlacementFailed` at `Severity::Critical` on the
  second escalation. **Never** converts to a market order automatically; that is
  an operator decision, not a timer's.

### 3.5 Fill ingestion

#### The account-event stream is a hint. It is never the authority.

This is forced by what the adapters actually are, not by defensiveness.
**Neither exchange has a user-data-stream push in this codebase**: both
`subscribe_account_updates` implementations REST-poll `get_account_state` and
diff successive snapshots (`exchange_adapter_binance/NOTES.md` §2,
`exchange_adapter_mexc/NOTES.md` §1b; MEXC's poll defaults to 3 s). Three
consequences follow, each documented in those notes:

- **A terminal order is a disappearance, not a status.** `get_account_state`
  returns only *open* orders, so a filled order leaves the set. Binance's diff
  then emits **nothing at all** for it ("telling filled apart from cancelled
  would need an extra `get_order` call per vanished id, which this cheap diff
  loop doesn't make"); MEXC's emits the **last-known** `OrderInfo`, whose status
  is stale by construction. A design that waited for `status == Filled` on this
  stream would leave a position in `Opening` forever on Binance.
- **A fill that opens and closes between two polls is invisible**, and the diff
  can report "this order left the open-orders set" but not the fill price or
  quantity.
- **The stream itself can drop.** `MarketDataFeed::subscribe_account_events`
  wraps a `tokio` broadcast channel; a slow subscriber gets `Lagged(n)` and
  those events are gone (`lagged_aware`, `market_data/src/store.rs`).

`AccountEvent` also has no fill variant at all — `OrderUpdate(OrderInfo)` carries
cumulative `filled_qty`/`avg_fill_price` and nothing else. Every field that makes
a fill a fill (`trade_id`, per-trade price/qty, `fee`, `fee_asset`, `is_maker`,
`realized_pnl`) exists only on `Fill`, reachable only through `get_order_fills`.

So `run_fill_sync` treats an account event as a **wake-up**, and asks:

#### `run_fill_sync` — one task per pair, owned by `execution`

- Subscribes `MarketDataFeed::subscribe_account_events()`. An `OrderUpdate`
  whose `client_order_id` matches a tracked order of a live position schedules
  an **immediate poll of that order**; one that matches nothing (or carries no
  client id) schedules a poll of *all* non-terminal tracked orders, rather than
  being discarded — the stream's own gaps are why it cannot be trusted to have
  named the right order.
- Polls `get_order(id)` for every non-terminal tracked order on
  `ORDER_POLL_INTERVAL_SECS` (default 2) regardless of whether any event
  arrived. This is the authority for `filled_qty`, `avg_fill_price` and
  **status**; a dropped, stale or absent event costs latency, never
  correctness. Rate: a handful of REST calls per second per live position, and
  only while one is live.
- Emits `PartiallyFilled` / `Filled` from the polled deltas. These are
  **events, not status changes** — an `Opening` position emits
  `PartiallyFilled` and stays `Opening` (§3.1).
- **Terminal status comes only from `get_order`.** On the *entry* order reaching
  one (`Filled`, `Cancelled`, `Rejected`), runs §3.1's resolution: the final
  filled quantity moves the position to `Flat`, `Open` or `Closing` in one step,
  placing the stop or the exit as §3.4 describes.
- On any order reaching a terminal status, polls `get_order_fills` until
  `Σ fill.qty == OrderInfo.filled_qty` or 10 s (live-trade-ops §4.5's own
  fill-lag rule), then calls `settle` and writes fees, `net_price` and futures
  `realized_pnl` into the position; sets `settlement_complete`.
- **Applying a fill is idempotent on `(exchange, trade_id)`.** This is a
  requirement, not a precaution: `get_order_fills` returns *every* fill against
  an order on *every* poll, and the fill-lag loop above polls it repeatedly by
  design, so the same `Fill` is re-delivered many times in the ordinary case. A
  position that appended blindly would inflate `net_size` and corrupt
  `avg_entry_price` on its first partially-filled order. `entries`/`exits`
  therefore ignore a `Fill` whose `trade_id` they already hold, and
  `settle` is called over the deduplicated set — matching `exchange_fill`'s own
  `PRIMARY KEY (exchange, trade_id)` (§4.7 of the live-trade-ops design), so
  the in-memory position and the table agree on what "the same fill" means.
  `trade_id` is unique per exchange, not globally, which is why the exchange is
  part of the key.
- A `get_order_fills` returning `NotSupported` (MEXC, until its own spec) leaves
  `settlement_complete = false` and fees empty. This is reported, never
  fabricated: a P&L figure computed without fees is a wrong number, not an
  approximate one.

Real user-data-stream push — Binance's `listenKey` (`executionReport` /
`ORDER_TRADE_UPDATE`), MEXC's protobuf private channels — would make the hint
timely and carry per-fill commission directly. Both are named as the intended
replacement in the adapters' own notes, and both are out of scope here (§9):
this design is correct without them and merely slower.

### 3.6 Unrealized P&L and liquidation proximity

`run_advisor_loop` already has the trade price every tick. It additionally:

- computes `unrealized_pnl = (mark − avg_entry) × net_size × dir` (spot/margin)
  or takes it from `FuturesOps::position_risk` when available;
- for margin/futures, refreshes `liquidation_price`/`maint_margin` from
  `position_risk` on a slower cadence (`POSITION_RISK_POLL_SECS`, default 15);
- fires `AlertKind::LiquidationNear` when
  `|mark − liquidation_price| / mark < LIQUIDATION_WARN_FRACTION` (default 0.15),
  rate-limited to once per position per crossing — giving A18's alert its first
  producer.

This is *monitoring*. Automatic de-risking on liquidation proximity is out of
scope (§9): it is a money-losing action taken without an operator, and the
`L3-execution.md` requirement it satisfies is the tracking one.

---

## 4. `local_analysis` changes

Almost none. Both level-interpretation gaps — B7 (the open path ignores main/'s
`StopLoss`/`Target` kinds) and B8 (`modify` is a `NoOp`) — are one root cause
and are cut from this scope together: [../TECH_DEBT.md](../TECH_DEBT.md) §10,
and §9 below. `DefaultSignalBuilder` is untouched by this spec.

- `OpenPositionView` (the `PositionAdvisor` input) gains `avg_entry_price`,
  `net_size` and `unrealized_pnl`, so an advisor can trail on realised risk
  rather than on intent. `DefaultPositionAdvisor`'s behaviour is unchanged —
  the fields are supplied, not yet used.
- `RiskValidator` gains nothing. Pre-trade validation still runs once, before
  open, per `L2`'s and `L3`'s division of labour.

---

## 5. Persistence

### 5.1 Migration `0009_position.sql` (additive; `SCHEMA_VERSION` 8 → 9)

`0008` belongs to live-trade-ops's order journal. Never edit `0001`–`0008`
(sqlx checksums; see `0002`'s header). Additive means additive: `position_state`
and `event_log` are **not dropped** here (see §5.2).

```sql
-- Append-only. One row per position state change: the event that caused it
-- plus the complete resulting state. Replaces `position_state` (a one-row-per-
-- pair overwrite) and absorbs `event_log`'s position role -- D12. Hot fields
-- are denormalised out of `state` so the common queries are not jsonb digs;
-- `state` remains the whole `OpenPosition`, so a reader never needs a second
-- table to reconstruct one.
CREATE TABLE position_log (
    seq             bigint PRIMARY KEY DEFAULT nextval('global_ins_seq'),
    position_id     uuid,                       -- NULL only for a `not_placed` with no position
    pair            text NOT NULL,
    event           text NOT NULL,              -- opened | partially_filled | filled | closed | stopped_out
                                                -- | target_hit | sl_moved | not_placed | already_closed
                                                -- | not_filled | reconciled
    event_detail    jsonb NOT NULL,             -- the PositionStateEvent itself (reason, prices, ...)
    status          text NOT NULL,              -- flat | opening | open | closing | closed
    market_kind     text,
    side            side_enum,
    target_size     numeric,
    net_size        numeric,
    intended_open_price numeric,
    avg_entry_price numeric,
    avg_exit_price  numeric,
    stop_loss_price numeric,
    take_profit_price numeric,
    realized_pnl    numeric,
    unrealized_pnl  numeric,
    fees            jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [[asset, amount], ...]
    settlement_complete boolean NOT NULL DEFAULT false,
    leverage        integer,
    margin_type     text,
    liquidation_price numeric,
    close_reason    text,                       -- target | stop | main_close | force | reconcile | timeout
    decision_id     text,
    signal_id       text,
    state           jsonb NOT NULL,             -- the full OpenPosition (or a flat marker)
    recorded_at     bigint NOT NULL
);
CREATE INDEX position_log_pair_seq   ON position_log (pair, seq DESC);
CREATE INDEX position_log_position   ON position_log (position_id, seq);
CREATE INDEX position_log_window     ON position_log (pair, recorded_at);

-- "Current position per pair" -- what `load_all` reads at boot, and what
-- `/api/pairs` renders. A view, not a table: a second table would be the
-- snapshot D12 just removed, wearing a different name.
CREATE VIEW position_current AS
SELECT DISTINCT ON (pair) * FROM position_log ORDER BY pair, seq DESC;

-- One row per position LIFETIME, derived. `created_at` is the first row's
-- timestamp, everything else the last row's -- so it cannot drift from the log.
-- There is no separate first-fill timestamp: the log already carries the row
-- that recorded the first fill, so a column duplicating it could only disagree.
CREATE VIEW position_history AS
SELECT DISTINCT ON (position_id) position_id, pair, market_kind, side, status,
       target_size, net_size, intended_open_price, avg_entry_price, avg_exit_price,
       realized_pnl, fees, settlement_complete, leverage, liquidation_price,
       close_reason, decision_id, signal_id, recorded_at AS closed_at,
       (SELECT MIN(recorded_at) FROM position_log l2 WHERE l2.position_id = position_log.position_id) AS created_at
FROM position_log WHERE position_id IS NOT NULL ORDER BY position_id, seq DESC;

-- Append-only reconciliation outcomes (A23). `last_reconciliation` stays in
-- memory as the cheap read; this is the durable record.
CREATE TABLE reconciliation_log (
    seq        bigint PRIMARY KEY DEFAULT nextval('global_ins_seq'),
    pair       text NOT NULL,
    outcome    text NOT NULL,      -- no_discrepancy | missing_locally | extra_locally | quantity_drift | stale_order
    detail     jsonb NOT NULL,
    ran_at     bigint NOT NULL
);
```

Per-order and per-fill rows are **not** duplicated here: `exchange_order` /
`exchange_fill` (migration 0008) already hold them, keyed by `client_order_id`,
and D5's id format embeds the position id. A position's orders would be
findable as `exchange_order WHERE client_order_id LIKE 'x-{pos8}-%'`, and §5.4
adds an explicit column rather than leaning on the prefix.

`global_ins_seq` is the same sequence `trade`/`candle`/`signal_log`/`indicators`
already order by, so `seq` orders `position_log` against them without a clock
comparison. The `dashboard` role picks the tables and views up through the
existing default privileges (`docker/initdb.d/00-roles.sql`), as 0008's do.

**A row means something changed. Nothing else appends.** Two periodic things
run against a live position and neither writes here:

- the **outbound heartbeat** (`POSITION_HEARTBEAT_SECS`, §6.3) publishes an MQ
  message and appends nothing. It exists so main/ can tell a dead PUSH queue
  from a quiet market — a liveness property of the *link*, which a database row
  cannot carry and a database reader never asks about. Writing unchanged state
  on a timer would also destroy the one thing this table is for: in an
  append-only log every row is evidence that something happened, and a log
  where most rows mean "nothing happened" has to be filtered before it can be
  read.
- a **periodic `reconcile`** (`RECONCILE_INTERVAL_SECS`, D8) appends only when
  it actually corrected something. `NoDiscrepancy` — the overwhelmingly common
  outcome, once a minute per pair — goes to `reconciliation_log` and nowhere
  else. That table is the record of *checks*; `position_log` is the record of
  *changes*, and conflating them would put ~1400 no-op rows per pair per day
  into the position history.

Unrealized P&L is the one field that genuinely moves without a state change,
and it is deliberately not a reason to append: it is a function of mark price,
which `trade` already stores tick by tick, so any point in the past can be
recomputed rather than pre-written.

**Write volume**, with that rule: one row per state change — order-of-magnitude
hundreds of rows a day at the pair counts this system runs, against
`book_update`'s millions. No retention policy is specified; if one is ever
needed it is a partition on `recorded_at`, not a prune of history, because
history is the point.

### 5.2 What happens to `position_state` and `event_log`

Both are **retired, not dropped**: no new writes, rows left in place. Dropping
a table that holds the only record of a position this system may still be
holding is not a migration, it is data loss — and `0001`/`0003` cannot be edited
anyway. `state_store`'s module doc, which currently explains why
`position_state` is "not an append-only log", is rewritten to say why it now is
one and where its predecessor went.

Migration `0009` backfills: every `position_state` row becomes one
`position_log` row with `event = 'reconciled'`, `recorded_at` = the row's own
timestamp, so a boot immediately after the migration recovers exactly what a
boot immediately before it would have. The `event_log` rows are **not**
backfilled — they carry no state to put in `state`, and the visualiser's
`/api/pair_events` reads the union of the two for a window that spans the
migration (§8.1), which is the one place the seam is visible.

### 5.3 Write path

`StateStore`'s `persist` + `log_event` pair is replaced by a single append:

```rust
async fn append_position(&self, entry: &PositionLogEntry) -> Result<(), StoreError>;
async fn load_all(&self) -> Result<Vec<PositionState>, StoreError>;                  // now over `position_current`
async fn read_position_log(&self, pair: Pair, from: Ts, to: Ts) -> Result<PositionLogStream, StoreError>;
async fn read_position_history(&self, pair: Pair, from: Ts, to: Ts) -> Result<PositionHistoryStream, StoreError>;
async fn read_position(&self, id: PositionId) -> Result<Option<PositionLogStream>, StoreError>;
async fn record_reconciliation(&self, report: &ReconciliationReport, at: Ts) -> Result<(), StoreError>;
```

`PositionLogEntry { pair, position_id, event: PositionStateEvent, state: PositionState, recorded_at }`
— the event and the state it produced, together, in **one row and one commit**.
That pairing is the point of D12: today `run_position_sync` writes the snapshot
and the event as two independent writes, and its own call site documents what a
partial failure leaves behind. One row cannot half-commit.

Same synchronous-durability contract as `log_decision`: committed before it
returns. An append failure is alerted (`AlertKind::PersistFailed`) and never
aborts the loop — but the alert text changes meaning and must be rewritten: the
on-disk state is no longer *stale*, it is *missing a step*, and the next
successful append restores a correct current state on its own.

`run_position_sync` collapses to one `append_position` call per trigger.
`dto.rs`'s `PositionStateDto`/`OpenPositionDto` mirrors are extended
field-for-field with `OpenPosition`'s new fields, and a round-trip test per new
field is the RED test for that task.

### 5.4 Additive change to 0008 — folded into `0009`

One column, `ALTER TABLE exchange_order ADD COLUMN position_id uuid` (nullable —
`livetest` orders have none), plus an index on it. Joining orders and fills to a
position by string prefix would work and would be the wrong thing to leave in a
schema.

**This rides in `0009`, not a migration of its own** (amended 2026-09-25).
§5.1's "`SCHEMA_VERSION` 8 → 9" is the whole budget for this spec, and §11's
layer table already reads "Migration 0009 (`position_log` + views + backfill)
**and** 0008's `position_id` column". `0009` does not exist on disk yet, so
defining it to contain both is free — the never-edit rule binds `0001`–`0008`
only. The file is therefore named **`0009_position.sql`**, not
`0009_position_log.sql`: it creates `position_log`, `reconciliation_log` and
two views *and* alters `exchange_order`, and a migration filename that
under-describes its contents is how a column gets missed six months later.

### 5.5 Journalled production orders

The orchestrator wraps its `MarketAccount` in `order_journal::JournaledAccount`
with an `order_journal::PgOrderJournal` and `origin = "execution"`, after `NoTradeAccount` (so a
disarmed refusal is still journalled as `rejected: Disarmed` — an operator
asking "did it try?" gets an answer). This is live-trade-ops §4.7's own
"wrapping the orchestrator's account is a follow-up", taken up here, and is
gated on the [../TECH_DEBT.md](../TECH_DEBT.md) §8 review (resolved: design
2026-09-23, placement 2026-09-25). `orchestrator` depends on `order_journal`,
never on `live_trade_ops` (D5).

---

## 6. Communication with main/

### 6.1 Outbound wire v2

Additive to `L4-mq-gateway.md`'s envelope; `schema` distinguishes it.

```json
{
  "schema": 2,
  "pair": "LINKUSDT",
  "position_id": "9f2c…",
  "event": "opened" | "partially_filled" | "filled" | "closed" | "stopped_out"
         | "target_hit" | "sl_moved" | "not_placed" | "already_closed"
         | "not_filled" | "state_update",
  "decision_id": "…",
  "reason": "…",
  "position_state": {
    "status": "flat" | "opening" | "open" | "closing",
    "side": "long" | "short",
    "market_kind": "spot" | "margin" | "futures",
    "target_size": 12.0, "net_size": 7.5,
    "intended_open_price": 15.00, "avg_entry_price": 15.0150, "avg_exit_price": null,
    "stop_loss_price": 14.85, "take_profit_price": 15.60,
    "realized_pnl": null, "unrealized_pnl": 0.41,
    "fees": [["LINK", 0.0008]], "settlement_complete": false,
    "leverage": null, "liquidation_price": null,
    "created_at": 1758500000000
  },
  "ts": "2026-09-22T12:00:00Z"
}
```

Aggregates only — **no per-fill array, ever.** main/ needs an average entry
price and a set of levels (§6.4), not a trade ledger; the executor has already
netted the fills against the authoritative source and holds them in
`exchange_fill` for anything that wants them. Putting fills on this wire would
invite a second, lossier reconstruction of a number that already exists.

Three substantive changes against today:

1. **Every event carries the full current state.** `flat_state()` — the
   all-`null` body every non-`Opened` event sends today — is deleted. A consumer
   must be able to reconstruct the position from the last message it received,
   without having seen the first one.
2. **`not_placed` carries its `reason`.** The rejection reason is already
   computed and already persisted to `event_log`; it was being thrown away at
   the wire boundary. B5's "no `id` on outbound" stays, but `decision_id` is
   carried as a *correlation field* — a state report that says which decision
   caused it is still a state report.
3. **`filled` is emitted.** `L4-mq-gateway.md` has listed it since the layer was
   written and nothing has ever produced it (documented in `wire.rs`'s module
   doc). D3 gives it a meaning: the entry or exit order reached `Filled`.

**A failed publish is counted, not dropped.** `mq_gateway::drive` discards
every `publish_state` result today (`let _ = outbound.publish_state(event)`,
[../TECH_DEBT.md](../TECH_DEBT.md) §3). Under v1 that lost a status word; under
v2 the message *is* main/'s copy of the position, so the loss matters more.
The state-publish loop therefore increments `wire_publish_failed` (§7.2,
tagged `event`) on every error and logs at `WARNING` at most once per 60 s,
and keeps running — a publish error must never stop the loop. The receiver's
own safety net is the heartbeat (§6.3): a missed event is corrected by the next
`state_update` at the latest. Only this leg is in scope here; moving `drive`
into `orchestrator` and the two dropped inbound-handling results stay in
TECH_DEBT §3, which this narrows rather than closes.

### 6.2 Inbound additions

```json
{ "id": "<uuid>", "type": "position_query", "pair": "LINKUSDT" }   // pair optional: omitted = all
```

Answered with one `state_update` per live position (or a single `status: flat`
message for a queried pair holding nothing). This is B6, and it is what lets a
restarted main/ resynchronise without waiting for the next event.

```json
{ "id": "<uuid>", "type": "client_hello", "client": "main",
  "order_placement": "disabled" | "enabled", "wire_schema_max": 2 }
```

**`client_hello` — the deployment-compatibility interlock.** Two deployment
mistakes are invisible from inside either repository: an armed main/ (§6.5,
`MAIN_ORDER_PLACEMENT=enabled`) against an executor placing live orders — two
processes trading one account — and a main/ consumer against an executor that
does not speak wire v2. Neither repo's test suite can see the other's deployed
version, so the processes tell each other at runtime.

main/ sends `client_hello` once at startup and again every
`POSITION_HEARTBEAT_SECS`, so an executor that restarts learns main/'s state
within one period. It is a dedicated message, not fields added to
`indicator_update`, because indicator publishing is optional
(`indicator_publisher = None` without pyzmq or shared indicators) and the
interlock must not depend on it. The executor keeps the last hello received and:

- `order_placement = "enabled"` while `EXECUTION_MODE=live` → one
  `Severity::Critical` alert of kind `MainOrderPlacementArmed` (§7.3) per
  transition into that state, not per message, plus gauge
  `main_order_placement_armed = 1`. The executor keeps trading: it cannot
  disarm main/, and stopping itself would leave its own positions unmanaged.
  The operator's response is to disarm main/.
- no hello for `2 × POSITION_HEARTBEAT_SECS` → `WARNING` log once and
  `main_order_placement` reported as `unknown` (§8.1). An old main/ that
  predates this message lands here, which is the right answer: its state is
  unknown.
- `wire_schema_max < 2` → `WARNING` once; the executor sends v2 regardless
  (there is no v1 fallback), so the operator knows main/ will be skipping it.

An executor from before this spec rejects `client_hello` as an unknown `type`
at `decode_inbound` and drops it; main/ does not depend on a reply.

`modify` keeps its existing payload and its existing behaviour — it resolves
to `NoOp` (row B8, deferred; [../TECH_DEBT.md](../TECH_DEBT.md) §10). It is
listed here only so the v2 reader is not written as though the type did not
exist: an inbound `modify` produces a `not_placed` event carrying that reason,
rather than silence.

### 6.3 Snapshot heartbeat

Every `POSITION_HEARTBEAT_SECS` (default 30) the executor publishes a
`state_update` per live position, unprompted. A PUSH queue that silently stopped
being drained and a genuinely quiet market are otherwise indistinguishable from
main/'s side.

**Publish only — it never touches the database** (§5.1). The heartbeat proves
the link is alive, which is a fact about the link, not about the position; the
position did not change, so there is nothing to append. A consumer that has
seen no heartbeat for `2 × POSITION_HEARTBEAT_SECS` logs and issues a
`position_query` (§6.2) rather than assuming anything.

The heartbeat period also paces main/'s `client_hello` (§6.2) in the other
direction, so one setting governs link liveness both ways.

**The startup version check** rides on the same mechanism. At startup the
consumer sends `position_query`; the executor answers with `schema: 2`
messages. A consumer that has received no `schema: 2` message within
`2 × POSITION_HEARTBEAT_SECS` of startup logs `WARNING` "executor does not
speak wire v2 (or is not running)" once and sets gauge `executor_wire_v2 = 0`
(`1` once one arrives). main/ keeps trading on its own intent — the consumer
only ever adds truth, and its absence is the pre-spec behaviour.

### 6.4 main/ side — `mq/position_consumer.py`

New module, shaped exactly like `mq/indicator_publisher.py` and for the same
reasons:

- `zmq` imported **inside** `__init__`, never at module level, so an image
  without pyzmq still imports and still trades (`trader.py` already degrades to
  `indicator_publisher = None`; the consumer degrades the same way, with the
  same warning).
- Pure decode function `parse_position_event(raw: dict) -> PositionEvent`,
  fully unit-testable with no socket, mirroring `build_indicator_update`.
- `PositionConsumer.poll(timeout_ms)` — non-blocking, called from `Robot`'s
  existing 1 s tick. Telemetry must never block the trading path (see
  `16b22c3`).
- **Where in the tick:** events are polled and applied (`sync_from_executor`,
  below) **before the strategy step** — in `Robot.do()` after
  `live_data.get_data_point()` and before `self.position.get_state()` — so the
  strategy decides against the executor's actual status, average price and
  levels on this tick, not last tick's. The sync's recorded changes still
  reach the action log on the same tick, because `_record_live_actions`
  (`drain_changes()`) runs at the end of `do()`. Applying it *after* the
  strategy instead would let a strategy `CLOSE` act on a position the executor
  has already stopped out, recording two closes; syncing first records the
  executor's close and then any new open, in the order they happened.
- An unknown `event` or `schema > 2` is logged once per kind and skipped, never
  raised.

#### What main/ keeps a position for — and what it therefore does not need

main/ tracks a position for exactly two reasons, and every rule below follows
from them:

1. **Record actions, so position levels can be visualised.** The existing
   `change_history` → `drain_changes()` → Action-record path
   (`robots/robot.py:277`) is the product.
2. **Hold `avg_price_open`**, so risk can be recomputed and strategies can run
   against the price actually paid rather than the price intended.

Neither needs a fill. **main/ does not track fills, and the consumer discards
fill detail rather than replaying it** — no `record_entry_fill` /
`record_exit_fill` from this path, no per-trade rows, no fee arithmetic. The
executor has already done that work against the authoritative source
(`get_order_fills` + `settle`, §3.5), and a second reconstruction in another
language from a lossy stream could only ever disagree with it. Per-fill data
does not appear on the wire at all (§6.1 carries aggregates only), so this is
"never sent" rather than "sent and thrown away".

What the consumer applies is the **aggregate**, wholesale:

- `Robot` keeps opening and closing `self.position` from its strategy exactly as
  it does now — that is what drives `get_action`, `change_history`, the action
  log and every backtest-shaped behaviour main/ has. Those calls express
  *intent*, and they are what purpose 1 records.
- A new facade method `Position.sync_from_executor(status, side, net_size,
  avg_entry_price, stop_loss_price, take_profit_price, realized_pnl)`
  **replaces** the aggregate rather than appending to it. Deliberately not
  `record_entry_fill(net_size, avg_entry_price)` as a synthetic single fill:
  that appends to `executed_open`/`executed_open_amount`, so every repeated
  update would re-average against its own previous output and drift. A
  replace-in-place setter says what this actually is — a projection of someone
  else's state — and cannot accumulate.
- `avg_price_open()` returns the executor's `avg_entry_price` after a sync;
  `price_stop_loss` tracks `sl_moved`. That is purpose 2 satisfied, and it is
  what `is_stop_loss_triggered`, `is_target_reached`, `check_stop_open`,
  `direction_profit`/`direction_loss` and every strategy reading them now
  compute against.
- A sync that changes status, side, average price or either level **records a
  change** through the existing `_record_change` path, so purpose 1 covers the
  executor's actions and not only main/'s own intent. A sync that changes
  nothing records nothing — same rule as §5.1's.
- `finalize()` on a `closed` event takes the executor's `realized_pnl` when
  `settlement_complete` is true, and otherwise falls back to main/'s own
  `(avg_close/avg_open − 1) − 2×fee` (MEXC, §3.5), logging which it used. Two
  revenue numbers disagreeing silently would be worse than either.
- **Divergence check.** The executor reporting a position for a pair main/
  thinks is flat (or the reverse, or a side mismatch) logs at `WARNING` with
  both states and increments a counter. main/'s intent and the executor's truth
  are two different things by design, and the gap between them is the only
  signal that a decision was silently refused — wire v2 carries `not_placed`
  with a reason (§6.1), but a dropped PUSH message carries nothing.

### 6.5 main/ order placement — disabled, not deleted (D2)

Every order main/ can send funnels through exactly three calls on
`stocks.base_stock.StockInterface`:

| Call site | Primitive | Used by |
|---|---|---|
| `Robot._place_valid_order` (`robots/robot.py:317`) | `stock.trade(...)` | `_open_position`, `_close_position`, `_stop_loss` — every entry, exit and stop order |
| `Robot._open_position` (`robots/robot.py:370`) | `stock.borrow(...)` | the margin loan taken before a SHORT entry |
| `LiveOrderTracker.cancel_buy` / `cancel_sell` (`robots/live_order_tracker.py:59,68`) | `stock.cancel_order(...)` | cancelling a resting order |

**The refusal happens at the `StockInterface` boundary, in one decorator**, not
as three `if` statements in `robot.py`. `DisarmedStock` wraps the real stock:
reads (`get_order`, balances, candles, book) pass through untouched;
`trade`/`borrow`/`repay`/`cancel_order` return the interface's own
`STATUS_FAIL` shape without constructing a request. This is deliberately the
same shape as the executor's `NoTradeAccount` (`crates/orchestrator/src/no_trade.rs`)
and for the same stated reason: the refusal must not depend on API-key
permissions, on the exchange, or on anything outside the process being
configured right.

Selected by `MAIN_ORDER_PLACEMENT`, read in `trader.py` beside the existing
`MQ_EXECUTOR_ADDR` handling:

- unset or `disabled` (**the default**) → `DisarmedStock`, and a startup log
  line saying main/ will place no orders and which process will;
- `enabled` → the real stock, and a `WARNING`-level banner naming the
  double-trade hazard against a live executor. An explicit, loud escape hatch,
  because the reason to keep this code is the day the executor is not ready.

Either way the value is reported to the executor in `client_hello` (§6.2), so
an armed main/ against a live executor is alerted on from the executor's side
too, not only announced in main/'s own log.

**The call sites stay, each with a comment** naming what now owns that action
(`execution::Executor::open_position` / `do_close` / `run_stop_loss_watcher` /
`apply_stop_loss_move`), pointing at this section, and saying how to re-arm.
Deleting them would take `LiveOrderTracker`'s loan bookkeeping and its
crash-recovery JSON with it — and those describe positions that may be open on
the exchange right now.

**Behaviour under refusal, stated rather than discovered:**

- `_place_valid_order` already returns `""` on failure and every caller already
  handles it. But `_open_position`/`_close_position` log that at `ERROR`
  ("order placement failed, skipping tracking"), which would now fire on every
  single decision. A refusal is a *normal* outcome here: the refusal is
  distinguished from a genuine failure and logged once at startup plus at
  `DEBUG` per call, never at `ERROR`.
- `stock.borrow` refused means a SHORT never borrows. `self.position` has
  already been opened by then (`position.open()` runs before placement), which
  is correct under §6.4: it is intent. The executor borrows for its own short.
- With no order ever placed, `tracker.buy_id`/`sell_id` stay empty,
  `check_fill` never runs, and no fill is recorded from that path — which is
  exactly the vacancy §6.4's consumer fills.
- An existing `live_order_tracker` JSON file from a previous armed run is
  **loaded and reported, never acted on**: a startup `WARNING` naming the order
  ids and loan it still claims, so an operator can settle them by hand before
  the executor takes over. Silently ignoring a file that says "you owe a
  margin loan" is the one failure mode this whole section exists to avoid.

**Tests** (`main/tests/`): a fake `StockInterface` asserting zero
`trade`/`borrow`/`cancel_order` calls across a full open→close robot tick cycle
under the default config; `MAIN_ORDER_PLACEMENT=enabled` restoring every one of
them; and the existing `test_robot_orders.py` / `test_live_order_tracker.py`
kept green by running against the armed configuration, unchanged in meaning.

---

## 7. Logging, metrics, alerts

### 7.1 Event payloads (C2)

`PositionStateEvent` variants gain the fields the wire now carries:
`Opened`/`PartiallyFilled`/`Filled` carry `net_size`, `avg_entry_price`,
`fees`; `Closed`/`StoppedOut` carry `net_size`, `avg_exit_price`,
`realized_pnl`, `fees`, `close_reason`. `PositionStateEventDto` (state_store)
and `PositionStateEventDto` (visualizer_server) mirror each addition — both are
1:1 mirrors by design and both have round-trip tests to extend.

New variants: `PartiallyFilled`, `Filled`, `NotFilled { reason }`,
`TargetHit`. No `Modified` variant — `modify` does nothing until
[../TECH_DEBT.md](../TECH_DEBT.md) §10 is taken up, and an event kind with no
producer is exactly the trap `"filled"` has been in `L4-mq-gateway.md` since
the layer was written (§6.1).

### 7.2 Metrics (C7)

Via the existing `observability::Metrics`/`MetricEvent` with `pair` + `side`
tags: `position_opened`, `position_closed` (tagged `close_reason`),
`position_realized_pnl` (value), `position_fees_quote`, `position_hold_secs`,
`fill_latency_ms` (submit → first fill), `slippage_bps`
(`avg_entry_price` vs `intended_open_price`), `entry_unfilled`,
`exit_escalated`, `reconcile_discrepancy` (tagged `outcome`),
`wire_publish_failed` (tagged `event`, §6.1), `main_order_placement_armed`
(gauge, §6.2). main/ side: `executor_wire_v2` (gauge, §6.3).

### 7.3 Alerts (C8)

`LiquidationNear` gets its producer (§3.6). No new `AlertKind` variants are
added for the timeouts — `OrderPlacementFailed` at `Severity::Critical` already
means "an order this process needed did not end up where it should be", and
inventing a kind per timer dilutes it. Mid-run drift is `PersistFailed`'s
opposite (the DB is right and memory was wrong) and gets one new kind,
`PositionDrift`, because the operator response is different: stop trading and
look, rather than retry.

One more new kind, `MainOrderPlacementArmed` (§6.2), for the same reason: the
response is neither retry nor stop-and-look but "disarm the *other* process",
and an operator must not have to read a message body to learn that.

**Journal alerts use no new kind.** Anything live-trade-ops §4.7 calls
`OrderJournalWriteFailed` is raised as `AlertKind::PersistFailed` at
`Severity::Critical` with tag `component=order_journal` and the name as a
message prefix (`OrderJournalWriteFailed:`, `OrderJournalBackwardTransition:`,
`OrderJournalDuplicateClientOrderId:`) — as the journal already does today.
`PersistFailed` is the production kind for a failed durable write, and the
`component` tag, not a variant, is what identifies the journal. Anything that
routes or counts journal alerts matches on `kind` + `component`, never on a
variant name that does not exist.

---

## 8. Visualiser

### 8.1 Backend + routes

- `VisualizerBackend::position_log(pair, from, to)` → `read_position_log`
  (the append-only stream, §5.3) — this is what `/api/pair_events` becomes,
  reading `position_log` unioned with legacy `event_log` rows for a window that
  spans migration 0009 (§5.2).
- `VisualizerBackend::position_history(pair, from, to)` → `read_position_history`
  (the `position_history` view — one record per closed position).
- `VisualizerBackend::orders(pair, from, to)` / `fills(position_id)` over
  `exchange_order`/`exchange_fill` (`dashboard` already has `SELECT`).
- `VisualizerBackend::open_orders(pair)` — the **currently resting** orders for
  a pair: `exchange_order` rows with `origin = 'execution'` whose `status` is
  non-terminal (`intent | submitted_unknown | new | partially_filled`). A
  point-in-time query with no window, unlike every route above: "what is on the
  exchange right now" has no `from`/`to`. Served from `exchange_order` rather
  than from the live position's own `orders` field, so an order that outlived
  its position — an orphan, the exact thing worth seeing on a chart — is still
  returned.
- `GET /api/positions`, `GET /api/orders`, `GET /api/fills` — same
  `from`/`to`/empty-window conventions as `/api/pair_events`, same
  `#[serde(flatten)]` entry-wrapper shape.
- `GET /api/open_orders?pair=` → `Vec<OpenOrderDto> { client_order_id, role,
  side, order_kind, price, stop_price, qty, filled_qty, status }`. Price is
  `stop_price` for a `Stop` order (the trigger is where it lives on a price
  axis) and `price` otherwise; a market order has neither and is omitted — it
  has no price to draw.
- `/api/pairs`'s `PairSummaryDto.position` carries the full `PositionStateDto`,
  so the overview can show size and P&L per pair rather than a status word.
- `/api/status` gains `execution_mode` and `main_order_placement`. The executor
  cannot read main/'s environment, so `main_order_placement` is the value from
  the last `client_hello` (§6.2): `disabled` | `enabled` | `unknown` (no hello
  within `2 × POSITION_HEARTBEAT_SECS`), with `main_hello_at` beside it.

### 8.2 Frontend — records panels, not chart layers

**Decision: history goes in panels of records; only *currently resting orders*
are drawn.** The existing position chart overlay stays as it is — entry /
stop-loss / target price lines (D2) and the point-in-time position-event
markers (D3), both already built and both unchanged. Nothing historical is
added to a chart: no qty-scaled fill markers, no per-order markers, no
liquidation line, no equity curve on a canvas.

The reason is that the things this spec produces are *records with many fields*
— a fill has a price, a quantity, a fee, a fee asset, a maker flag and a trade
id — and a chart can show one number per point. Every one of D6/D7/D8's fields
that mattered would have to be recovered from a tooltip. A table shows all of
them at once, sorts, and copies.

**Open orders are the one exception, and the line between them is state, not
taste.** A resting order is a single price that is true *right now*, and its
whole meaning is where it sits relative to the current book and the current
candle — which is a question only a chart answers. A fill is a past event with
six fields; a resting order is one number in the present. §8.3 draws those.

Four panels, all following the existing `renderPositionEventsPanel` /
Decisions / Signals pattern in `pair.js` — a `<table>` in a bordered section,
newest first, refreshed on the same `refreshTradeActivity` tick, with an
explicit empty state:

1. **Position panel** (`renderPositionSummary`, extended — D6). Not a table but
   a labelled field list: status, side, net size / target size, avg entry,
   mark, unrealized P&L (coloured), realized P&L once closing, fees per asset,
   R-multiple (`(mark − avg_entry) / (avg_entry − stop)`), liquidation price
   and leverage when present, time in position, `settlement_complete`. An
   unprotected position (the `Stop` role's `OrderInfo` in `Rejected` — the only
   resting protective leg, D7) renders as a red banner above it — the one thing on the page an operator
   must never have to look for.
2. **Orders panel** (D7, from `/api/orders`): time, role (entry/exit/stop),
   side, kind, price, stop price, qty, filled qty, status, reject reason,
   `client_order_id`. One row per `exchange_order`, so a refused or
   orphaned order is visible as itself rather than inferred from a gap.
3. **Fills panel** (D7, from `/api/fills`): time, side, price, qty, quote qty,
   fee, fee asset, maker/taker, realized P&L, trade id. Expandable under the
   order it belongs to, or filtered by the selected position.
4. **Closed positions panel** (D8, from `/api/positions`): opened, closed,
   duration, side, size, avg entry, avg exit, realized P&L, fees, close reason,
   `decision_id` / `signal_id` linking to the rows the existing Decisions and
   Signals panels already render. A footer row totals realized P&L and fees over
   the window — which is what the equity curve was for, at a hundredth of the
   work and with the numbers legible.

Also:

- **`/ws` carries position updates** (D9), ending the position panel's poll.
  The header comment in `pair.js` declaring `/ws` candle/trade/book-only is
  updated, not worked around.
- **Operator banners**: `EXECUTION_MODE` and `MAIN_ORDER_PLACEMENT` (from
  `/api/status`, §6.5), and an unresolved-`reconciliation_log`-discrepancy
  banner. `main_order_placement = enabled` with `execution_mode = live` renders
  red; `unknown` renders amber.

**Testing the frontend.** `static/js/` has no test harness today, and every
other layer gates on a Docker test run. The new panel code is therefore split
in two:

- a **pure model** module, `static/js/positions_model.js` — route response in,
  row/field data out (formatting, sorting, footer totals, R-multiple, the
  unprotected flag, open-order line specs). No DOM, no `fetch`;
- a **thin render** layer in `pair.js`/`chart.js` that turns those rows into
  elements.

The pure module is tested by a `node --test` suite with no npm dependencies:
the scripts are plain globals-defining files (as `format.js` is), so each test
loads them into a `node:vm` context. It runs as a compose service `test-js`
(`node:22-alpine`, `static/` mounted read-only) against the committed
route-response fixtures of §8.1's routes — so a DTO field renamed in the
backend fails a frontend test, not a live run. DOM layout, colours and the
legend stay on a manual checklist; they are not what drifts.

### 8.3 Open-order lines (candle chart and order book chart)

From `GET /api/open_orders` (§8.1), refreshed on the same tick as the position
summary and on every `/ws` position push.

- **Candle chart** — one horizontal price line per open order, via
  `state.series.createPriceLine`, the same API `setPositionLines`
  (`chart.js:276`) already uses for entry/stop/target. New function
  `setOpenOrderLines(state, orders)`, keeping its own handle map so lines are
  removed when an order fills or cancels, exactly as `setPositionLines` manages
  `state.priceLines`.
- **Order book chart** — one marker at each order's price on the depth chart,
  through the existing `wallLines` chart.js plugin and
  `setDepthChartWalls`(`chart.js:586`)'s mechanism. Walls already prove the
  pattern: a price drawn onto the depth axis, not a chart.js dataset. An open
  order gets the same treatment on a separate styled channel, so "my order" and
  "somebody's wall" are never the same colour.
- **Styling and labels**: title `{role} {side} {qty}` (e.g. `stop sell 12.0`),
  one colour per `OrderRole`, and a dashed line for a non-terminal order that is
  not yet acknowledged (`intent` / `submitted_unknown` — believed sent, not
  confirmed resting). That distinction matters more on a chart than anywhere
  else: a solid line claims something is protecting you.
- **Against the existing intent lines.** `setPositionLines` draws
  `stop_loss_price` and `take_profit_price` — the position's *intent*. These
  draw what is *actually on the exchange*. They normally coincide, and when
  they do not, that gap is the single most useful thing the chart can show: a
  target line with no order under it is expected (D7 — the target never rests);
  a stop line with no order under it is an unprotected position. The legend
  states which is which rather than leaving it to be inferred.

---

## 9. Out of scope

- **Every use main/'s per-level `kind` was meant to have** — honouring
  `StopLoss`/`Target` on the open path (row B7) and making `modify` act (row
  B8). One root cause, deferred together to its own scope and recorded as
  [../TECH_DEBT.md](../TECH_DEBT.md) §10. Two consequences to hold in mind
  while reading the rest of this spec:
  **(a)** every position opened under it is still risked at a flat
  `PLACEHOLDER_STOP_LOSS_PCT` (1 %) of entry, whatever main/ sent — and since
  that same distance is the sizing input (`risk_per_trade / |open − stop|`), it
  fixes the size too, so the P&L, fees and R-multiple this spec makes real are
  measured against a placeholder risk model;
  **(b)** main/ cannot revise a live position's stop or target at all, so the
  only thing that moves a stop after open is this process's own
  `DefaultPositionAdvisor` trail (§3.4, A5). Force-close remains main/'s single
  lever over a live position.
- **Deleting main/'s direct order path.** It is disabled at one boundary and
  left in place, comments and all (D2, §6.5). Removing `LiveOrderTracker`, the
  loan bookkeeping and the `_place_valid_order` call sites is a separate
  cleanup, to be done only once the executor has held live positions through a
  full cycle and nobody needs the escape hatch.
- **Rewriting main/'s strategy loop around the executor.** `Robot` keeps its
  own `Position` and keeps driving it from strategy; this spec changes where
  its *fills* come from (§6.4), not how it decides. A main/ that asks the
  executor for a position instead of modelling one is a later, larger change.
- **Historical chart layers.** D6/D7/D8 are records panels. No qty-scaled fill
  markers, no per-order history markers, no liquidation line, no equity curve
  canvas (§8.2). The one addition is open-order lines on the candle and depth
  charts (§8.3) — present state, not history.
- **Dropping `position_state` / `event_log`.** Retired, backfilled and left in
  place (§5.2).
- **Any resting order for the target** (D7), OCO, and any venue-specific
  bracket-order primitive. The stop is the only protective leg on the exchange;
  a target reached while this process is down is not taken.
- **Hedge mode** (D10).
- **Automatic de-risking / auto-deleverage** on liquidation proximity (§3.6).
  Monitor and alert only.
- **Multi-exchange or cross-pair portfolio aggregation**, net exposure limits,
  correlation risk. One position per `(pair, market_kind)`.
- **Tax-lot / FIFO-LIFO accounting.** `settle`'s net deltas and per-close
  realized P&L, nothing more.
- **Fixing the nested-vs-flat inbound `payload` doc/code drift** already
  recorded in `L4-mq-gateway.md` (D9).
- **MEXC fee-aware P&L.** `get_order_fills` returns `NotSupported` there until
  MEXC's own spec; those positions report `settlement_complete: false` (§3.5).
- **Real user-data-stream push** on either exchange — Binance `listenKey`
  (`executionReport`/`ORDER_TRADE_UPDATE`), MEXC protobuf private channels.
  Both adapters poll-and-diff today and both NOTES.md files already name push
  as the intended replacement. §3.5 is designed to be correct without it; push
  makes it timely, and is its own spec per adapter.
- **`order_event.order_id bigint`** ([../TECH_DEBT.md](../TECH_DEBT.md) §7) —
  `position`/`exchange_order` use `uuid`/`text` and are unaffected.

---

## 10. Acceptance criteria

- [ ] No position state transition anywhere in `execution` is caused by a
      `place_order` return value. Verified structurally: `grep` for
      `place_order` in `engine.rs` shows no call whose result feeds a
      `positions.insert`.
- [ ] An entry order that never fills leaves the pair `Flat` after
      `ENTRY_FILL_TIMEOUT_SECS`, with a `not_filled` event carrying a reason —
      wiremock test, and observed live in Layer 9.
- [ ] A close order that never fills leaves the position `Closing` and never
      `Flat`; the escalation fires and alerts.
- [ ] A partially filled entry stays `Opening` while the order works, emitting
      `partially_filled` per fill, and becomes `Open` with `net_size` = the
      final filled quantity only once the entry is terminal — with exactly
      **one** stop order placed, sized to that final quantity. Verified from the
      wiremock request log: no stop is placed or replaced mid-fill.
- [ ] A close arriving while `Opening` is held as `pending_close` and applied at
      resolution: the position goes `Opening → Closing` with no stop order ever
      placed, and the working entry is not cancelled before it terminates.
- [ ] An entry cancelled by `ENTRY_FILL_TIMEOUT_SECS` after a partial fill
      resolves to `Open` at the filled size, not `Flat`; only a zero-fill
      timeout emits `not_filled`.
- [ ] A scale-in against an `Open` position leaves the status `Open` throughout
      — it never re-enters `Opening`, and the position stays closable while the
      scale-in entry works.
- [ ] **No order is ever placed for the target.** Across a full open →
      target-hit → closed cycle, the orders the account saw are exactly
      entry, stop, exit — verified from `exchange_order` (`role` never `t`,
      no `client_order_id` with a `-t-` segment) and from the wiremock
      request log.
- [ ] A position reaching `take_profit_price` with no signal firing still
      closes, via the backstop arm, emitting `TargetHit`; a close signal
      firing before the price is reached closes it too. Both go through
      `do_close` — same code path as a main/ `close`.
- [ ] A position resolves correctly with the account-event stream **disabled
      entirely** (no `AccountEvent` ever delivered): the `get_order` poll alone
      opens, fills and closes it. Proves the stream is a hint, not the
      authority — and that a Binance vanished-order gap cannot strand a
      position in `Opening`.
- [ ] **Re-delivering the same fills does not change the position.** Applying
      `get_order_fills`' output five times in a row leaves `net_size`,
      `avg_entry_price` and `fees` identical to applying it once — the
      idempotency the fill-lag poll makes mandatory (§3.5).
- [ ] A minted `client_order_id` is ≤ 32 chars and `[a-z0-9-]`-only for `n` up
      to 11 digits, and carries 16 hex digits of position id (D5); a forced
      duplicate insert surfaces as `JournalError::DuplicateClientOrderId` at
      `Severity::Critical`, with no order sent.
- [ ] `settle`'s fee arithmetic exists in exactly one place:
      `cargo tree`/`grep` shows `live_trade_ops` calling
      `exchange_adapter::settle`, with no second implementation.
- [ ] The journal exists in exactly one place, `crates/order_journal` (D5):
      `cargo tree -i live_trade_ops` lists no workspace crate;
      `cargo tree -i order_journal` lists `live_trade_ops` and `orchestrator`;
      `order_journal` depends on no adapter crate; no `journal` module is left
      in `live_trade_ops`.
- [ ] Every order the orchestrator sends has a row in `exchange_order` with
      `origin = 'execution'` and a non-null `position_id`, committed before the
      send. Verified by killing the process between intent and send.
- [ ] A closed position leaves a terminal `position_log` row with
      `realized_pnl`, `fees`, `close_reason` and `settlement_complete = true`
      on Binance, and exactly one row in `position_history` for its
      `position_id`.
- [ ] `position_log` is append-only in practice, not just by intent: no
      `UPDATE` or `DELETE` against it anywhere in `state_store` (`grep`), and
      a pair's full history survives a restart mid-position.
- [ ] `load_all()` after migration 0009 returns exactly what it returned
      before, on a database backfilled from `position_state` — verified by
      running both readers against the same restored dump.
- [ ] A killed process between two appends leaves the last good row intact and
      the next append restores a correct current state, with no overwrite of a
      newer row by an older one.
- [ ] Boot reconcile and the periodic reconcile both write
      `reconciliation_log` rows; a deliberate mismatch (position closed by hand
      on the exchange) is corrected, alerted and visible in the UI.
- [ ] main/ receives and decodes every event kind: a scripted end-to-end check
      in `main/scripts/`, modelled on
      `scripts/e2e_indicator_broadcast.py`, drives the executor and asserts
      main/'s `Position` — filled from the consumer — matches the executor's
      `/api/positions` row.
- [ ] **main/ places no orders.** A full open→close robot tick cycle against a
      fake `StockInterface` records zero `trade`/`borrow`/`cancel_order` calls
      under the default config; `MAIN_ORDER_PLACEMENT=enabled` restores every
      one of them; the existing `test_robot_orders.py` /
      `test_live_order_tracker.py` stay green against the armed configuration.
- [ ] A refused order is not logged as an error: a full cycle under the default
      config produces no `ERROR`-level line from `_open_position` /
      `_close_position` / `_stop_loss`.
- [ ] A leftover `live_order_tracker` JSON from an armed run produces a startup
      `WARNING` naming the order ids and loan it claims, and is not acted on.
- [ ] `position_query` from a freshly started main/ returns the live position.
- [ ] **Executor-driven changes are synced before the strategy step.** A robot
      tick test with a queued `stopped_out` event and a strategy that would
      emit `CLOSE` records exactly one close in the action log, on that tick,
      and the strategy saw `status = flat`.
- [ ] **The deployment interlock fires.** In the e2e script: main/ started with
      `MAIN_ORDER_PLACEMENT=enabled` against an executor with
      `EXECUTION_MODE=live` (wiremock exchange) produces exactly one
      `MainOrderPlacementArmed` alert and `/api/status` reporting `enabled`;
      stopping main/ turns it to `unknown` after `2 × POSITION_HEARTBEAT_SECS`.
- [ ] **A consumer against a v1 executor says so.** main/'s consumer fed only
      schema-1 fixtures logs the "no wire v2" `WARNING` once and reports
      `executor_wire_v2 = 0`, and keeps ticking.
- [ ] A failing `publish_state` increments `wire_publish_failed` and does not
      stop `drive`'s state loop: unit test with an always-failing outbound.
- [ ] Journal alerts are `PersistFailed` + `component=order_journal`: `grep`
      finds no `OrderJournalWriteFailed` `AlertKind` variant, and a forced
      duplicate intent alerts with the `OrderJournalDuplicateClientOrderId:`
      prefix.
- [ ] The visualiser's Position panel shows size, avg entry, unrealized and
      realized P&L, fees, R-multiple, liquidation price and the
      unprotected-position banner; the Orders, Fills and Closed-positions
      panels render over a window containing a real round trip, and the
      Closed-positions footer totals P&L and fees.
- [ ] Open orders are drawn on both charts: a resting stop appears as a price
      line on the candle chart and a marker at the same price on the depth
      chart, disappears within one refresh of being cancelled or filled, and is
      dashed while `intent`/`submitted_unknown`.
- [ ] An orphaned order — open on the exchange with no live position — is still
      drawn, since `/api/open_orders` reads `exchange_order`, not the position.
- [ ] No *historical* chart layer was added: no marker series for fills or past
      orders, no liquidation line, no equity-curve canvas (`grep` over
      `chart.js` for new dataset/series creation beyond `setOpenOrderLines`).
- [ ] `docker compose run --rm test-js` is green: `positions_model.js` tested
      against the committed route-response fixtures (§8.2).
- [ ] `docker compose run --build --rm test` green at every layer boundary.
- [ ] Live acceptance on Binance margin mainnet with `LIVE_MAX_NOTIONAL`-scale
      size, human-gated per run exactly as live-trade-ops Layer 7 is.

---

## 11. Implementation layering

**Implemented as nine plans, not one** — see
[`plans/2026-09-24-position-management-finalisation-plan.md`](../plans/2026-09-24-position-management-finalisation-plan.md),
which indexes the other eight, records the dependency graph and the wave
schedule, and owns §10 end to end. The layer table below is the sequence; the
plans group it into independently-buildable units, each with a committed
contract artefact at its boundaries.

For those plans, applying
`layer-first-planning`'s principles over the executor's real layers as the
indicator-panel and live-trade-ops plans do — Docker entry point first,
interface before code, a RED integration test at each boundary, no layer started
before the previous is green in Docker.

| Layer | Crate(s) | Content |
|---|---|---|
| 0 | — | Verify live-trade-ops merged and green; TECH_DEBT §8 resolved; baseline `docker compose run --build --rm test` |
| 1 | `exchange_adapter`, `order_journal` (new) | Promote `settle`/`Settlement`/`PairAssets`; promote `live_trade_ops::journal` to `crates/order_journal` (D5); `PositionId`; client-order-id minting helper; `live_trade_ops` re-pointed at both promoted copies |
| 2 | `execution` | Status machine, new `OpenPosition` over `exchange_adapter`'s own `Fill`/`OrderInfo`, plus the `OrderRole` enum. Pure state transitions, unit-tested, no I/O |
| 3 | `execution` | `run_fill_sync`, order choreography, timeouts, unrealized P&L, liquidation proximity |
| 4 | `local_analysis` | `OpenPositionView` additions only. **Not** B7/B8's level interpretation — see TECH_DEBT §10 |
| 5 | `state_store` + `db_schema` + `order_journal` | Migration 0009 (`position_log` + views + backfill) and 0008's `position_id` column (written by `order_journal`); `append_position` replacing `persist`/`log_event`; `load_all` over `position_current`; read paths; DTO mirrors |
| 6 | `orchestrator` | `order_journal::JournaledAccount` wrapping, `run_fill_sync` spawn, periodic reconcile, metrics/alerts, delete A20's already-open guard |
| 7a | `mq_gateway` | Wire v2, `position_query`, `client_hello` + `MainOrderPlacementArmed` interlock, heartbeat, counted `publish_state` failures |
| 7b | `main/` | `DisarmedStock` + `MAIN_ORDER_PLACEMENT` (§6.5), `client_hello` sender, `mq/position_consumer.py` with startup v2 check, `Robot` synced before the strategy step, divergence check, e2e script |
| 8 | `visualizer_backend`/`_server` | `position_log`/`position_history`/orders/fills read paths, routes, DTOs, `/ws` position push |
| 9 | frontend | `test-js` harness + `positions_model.js` first (§8.2); Position panel fields, Orders / Fills / Closed-positions panels, banners, open-order lines on the candle and depth charts (§8.3). No historical chart layers |
| 10 | — | Live acceptance, human-gated per run |

Layers 7a/7b and 8/9 are independent of each other and may run in parallel
once Layer 6 is green. 7b is the one layer that touches `main/` — it must land
before any live run with `EXECUTION_MODE=live`, since until it does both
processes can place orders.
