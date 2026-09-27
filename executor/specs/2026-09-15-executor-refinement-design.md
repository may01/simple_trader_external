# Executor refinement — market data, walls, mock signal, position sync — design

Refines the running `trade_executor` system (L1 market_data, L2 local_analysis,
L3 execution, L5 state_store, L8 visualizer, L9 orchestrator) per
[main_goal.md](../specs/main_goal.md) and the per-layer specs under
[specs/layers/](../specs/layers/). This is a **gap-closing** spec: most of the
requested capability already exists (see Audit below); the new work is
scoped to what's actually missing or regressed.

Branch: work happens in the `layer-implementation` worktree
(`trade_executor/.worktrees/layer-implementation`), current HEAD `c0b50a1`.

## Audit — requested capability vs. current code

| # | Requested capability | Status | Evidence |
|---|---|---|---|
| 1 | Retrieve order book from exchange | **DONE** | `crates/market_data/src/book.rs` (`BookTracker`), exchange adapters |
| 2 | Retrieve candles from exchange | **DONE** | `crates/market_data` candle ingestion, `candle` table |
| 3 | Store order book + candles to DB | **DONE** | `migrations/0001_init.sql` (`book_snapshot`/`book_update`/`candle`), `crates/market_data/src/pg` writer |
| 4 | Visualizer draws candles | **DONE** | `static/js/chart.js` candlestick series, `static/js/pair.js` |
| 5 | Visualizer draws order book | **DONE** | `static/js/pair.js` `renderBookRows`/`updateDepthChart`, `static/js/chart.js` depth chart |
| 6 | Local analyzer detects walls | **PARTIAL** | `crates/local_analysis/src/levels.rs` `WallDetector` exists and feeds `combined_levels` internally, but emits nothing observable outside one decision's lifetime |
| 7 | Store detected walls in DB | **GAP (regressed)** | No `wall_*` table in any migration; `state_store`/`visualizer_backend`/`visualizer_server` have zero `Wall` references outside the unrelated `LevelSource::Wall(Side)` enum variant. A prior sled-backed `wall_log`/`WallSink` (see `plans/2026-09-09-wall-visualisation-plan.md`) did not survive the Postgres migration (`plans/2026-09-12-state-store-expansion-postgres-plan.md`) |
| 8 | Visualizer shows walls on candle + order-book charts | **GAP on backend, dead code on frontend** | `static/js/chart.js` already has `WALL_STYLE`, `createWallSeries`, `setWallSnapshots`, `appendWallSnapshot`, `wallLinesPlugin`, `setDepthChartWalls` — but `static/js/pair.js` calls none of them (`grep` for the four names in `pair.js` returns nothing), because no route ever sends `walls` data |
| 9 | Mock buy/sell-volume-crossover signal | **GAP** | `crates/local_analysis/src/signals.rs`'s `SignalConfig` only has `ExtremeVolumeReversal`/`VolumeProjectedMove`; no 10-minute buy-vs-sell volume moving-average cross exists |
| 10 | Persist signals to DB | **GAP** | No generic signal-log table for any `SignalEvent`; separately, `decision_log` exists (L5) but has zero production call sites — `log_decision` is defined and tested, never called |
| 11 | Propagate signal result to exchange (post orders) | **Reusable, needs a decision source** | `execution::Executor::handle_decision(TradeDecision)` already does sizing, dual stop-loss placement, and calls `MarketAccount::place_order` (`crates/execution/src/engine.rs`) — nothing currently calls it except `mq_gateway::drive` (main/'s path). Needs a second, local caller |
| 12 | Send result to position model (open/close values) | **DONE, reusable** | `execution::Executor` already owns `PositionState`/`OpenPosition` in-memory and emits `PositionStateEvent`s through `subscribe_state_changes()` |
| 13 | Stop-loss at 1% for the mock signal | **GAP** | `local_analysis::builder::DefaultSignalBuilder` only computes `stop_loss_price` via `nearest_in_direction(combined_levels, ...)` (level-based) — no percent-based path exists |
| 14 | Position persisted in DB, updated on exchange execution | **GAP (confirmed)** | `state_store::StateStore::persist` exists and is used at **boot only** (`crates/orchestrator/src/system.rs` step 5, via `load_all`/`reconcile`) — `grep -rn "\.persist(" crates/*/src` returns **zero** call sites anywhere else. No task subscribes to `Executor::subscribe_state_changes()` or to `MarketDataFeed::subscribe_account_events()` at runtime |

Rows 1-5 and 12 need **verification only** (Task 1 of the plan) — no new
code. Rows 6-11, 13, 14 are real implementation work (Tasks 2-8).

## Design decisions

### Wall persistence + visualization (rows 6-8)

Restore the shape the removed sled-backed `wall_log` had, on Postgres:

- `local_analysis::levels` gains `WallObservation { pair, side, price, size,
  ts }` and `WallDetector::wall_observations(&self, book: &OrderBookSnapshot,
  pair: Pair, now: Ts) -> Vec<WallObservation>`, built on the existing
  percentile/max_spread_distance detection — no change to the detection
  math itself.
- New `wall_snapshot` table (migration 0005), same shape convention as
  `trade`/`candle`: `(pair, ts, side, price, size, ins_seq)`, PK on
  `(pair, ts, side, price)`, `_scan`/`_tail` indexes.
- `state_store` gets a `WallSink` write path (mirrors `log_decision`'s
  synchronous-commit reasoning: an observation is a point-in-time fact,
  not something to batch).
- `orchestrator` gets a per-pair task, event-driven on
  `MarketDataEvent::BookSnapshot`/`BookUpdate` (not a timer) — detection
  runs on every order-book update, so `wall_observations` always sees the
  current book. `WALL_SNAPSHOT_INTERVAL_SECS` throttles the *write* only:
  the task keeps the latest computed observations and persists them
  through the sink at most once per interval, never more often — same
  write cadence the old timer design had, but detection no longer samples
  a stale book between ticks.
- `visualizer_backend`/`visualizer_server` add a read path
  (`wall_snapshots`) and wire it into the existing `/api/history` response
  and `/ws` live message enum — the **frontend already has every rendering
  function it needs** (`chart.js`); Task 3 only adds the two-to-three call
  sites `pair.js` is missing.

### Percent-based stop-loss (row 13)

Not a threaded parameter — hard-coded directly at the two places that
touch a stop-loss value, each as a local `const` with a comment marking
it a placeholder for the future strategy-preparation plan:

- `local_analysis::mock_signal` (the analyzer that detects the cross).
- `local_analysis::builder::DefaultSignalBuilder` (the decision maker
  that turns a `DecisionKind::Open` into concrete open/close/stop
  prices) — its `stop_loss_price` computation for `Open` becomes
  `open_price * (1 - PCT)` / `open_price * (1 + PCT)` per side, replacing
  today's `nearest_in_direction(combined_levels, ...)` call for
  stop-loss specifically. `close_price`/target stays level-based,
  unchanged.

No `DecisionContext`/`TradeDecision` field, no `Option`, no plumbing
between the two — each file owns its own constant. This is a deliberate
simplification over the field-threading design from the first pass of
this spec: the percent is a temporary, repo-wide placeholder (per the
comment each const carries), not a per-decision-source toggle worth
architecting around yet. Consequence: this also changes stop-loss for
`main/`'s decisions (any `DecisionKind::Open`, not just the mock
signal's) until the strategy-preparation plan replaces it — acceptable
for a placeholder, called out explicitly so nobody mistakes it for a
permanent rule. It also widens *when* `main/`'s `Open` decisions succeed:
`DefaultSignalBuilder` previously required both a target level and a
stop-side level to resolve (a level-less stop meant `NoOp`), so a
decision with levels on only one side now opens a real position where it
used to do nothing — a deliberate, foreseen consequence of hard-coding
the stop unconditionally rather than scoping it to the mock signal, not
an oversight.

### Mock buy/sell-volume-crossover signal (rows 9-11)

`local_analysis` already has a generic signal mechanism —
`SignalCheck`/`SignalConfig`/`SignalFactory`/`SignalPipeline`, firing a
`SignalEvent` enum (`crates/local_analysis/src/signals.rs`, `lib.rs`) —
built and unit-tested, but **never wired to anything outside
`local_analysis`** (`grep` for `SignalPipeline`/`subscribe_signals`
outside that crate returns nothing). This is exactly the "simplified
signal" category `main_goal.md` already describes ("a lightweight signal
layer over its own live feed... e.g. a sharp volume direction-change
likely to reverse price"). The mock crossover is added as a **new check
in that same pipeline**, not a parallel bespoke mechanism.

**Event vs signal:** an *event* is a raw occurrence some subsystem
reports (a trade tick, a book update, a wall observation) — no implied
action. A *signal* is L2's analysis output over events — what a
decision-maker acts on. This codebase's existing name for that output is
`SignalEvent`; this plan keeps that name rather than introducing a
second `VolumeCrossEvent`/`Signal` type. The mock crossover is two new
variants of the *same* enum — `SignalEvent::MockBuyCrossedAboveSell` /
`MockSellCrossedAboveBuy` — flowing through the identical
`SignalCheck`/`SignalPipeline`/persistence path as any real check.
"Mock" marks provenance (synthetic/demo, not main/'s or a validated
production signal), not a different kind of entity.

- `SignalConfig::MockVolumeCross { window: Duration }` (10 minutes) →
  `SignalFactory` builds `MockVolumeCrossCheck`, implementing the
  existing `SignalCheck` trait (`fn check(&self, window:
  &MarketDataWindow) -> Option<SignalEvent>`) — same shape as
  `ExtremeVolumeReversalCheck`/`VolumeProjectedMoveCheck`. Computes
  buy/sell moving averages over trades in `window.recent_trades` falling
  within the trailing `window` duration (same `cutoff` pattern
  `VolumeProjectedMoveCheck` already uses), and fires **edge-triggered**
  — only when dominance (`buy_ma` vs `sell_ma`) flips from what it was
  last call, tracked via an internal `Mutex<Option<Side>>` (the trait's
  `&self` is immutable; a `Mutex` is the minimal way to remember state
  across calls without changing the trait). A first observation
  (`None -> Some`) never fires — nothing to cross from.
- `SignalPipeline::new(feed, checks, window_capacity)`'s
  `window_capacity` is a **count** bound on `recent_trades`, not a time
  bound (per `MarketDataWindow`'s own doc comment) — it must be sized
  generously enough that 10 minutes of trades on an active pair actually
  fit, or the mock check silently sees a truncated window. Documented as
  a fixed constant (`SIGNAL_PIPELINE_WINDOW_CAPACITY`) in Task 7, not a
  new env knob, unless that turns out to be insufficient.
- A new per-pair orchestrator task calls the pipeline's existing
  `subscribe_signals(pair)` (the `SimpleSignalFeed` trait — no new
  subscription mechanism). On a `Mock*` event it (a) persists the signal
  to the new generic `signal_log` table (row 10, any `SignalEvent`, not
  just mock ones — see below), then (b) builds a `TradeDecision` and
  calls `executor.handle_decision(...)` (row 11) — reusing the entire
  existing sizing/dual-stop-loss/order-placement path unchanged, per the
  audit above. `DecisionKind::Open`, `side` from the event
  (`MockBuyCrossedAboveSell` → `Side::Buy`, `MockSellCrossedAboveBuy` →
  `Side::Sell`). Stop-loss: Task 4's hard-coded constant, not a decision
  field.
- Per the confirmed answer to "which execution backend": this task's
  `TradeDecision`s flow through the **same** `market_account` the
  orchestrator already constructed for the whole process — i.e. whatever
  `EXCHANGE`/`EXECUTION_MODE` the deployment is configured with. No new
  safety gate is invented: `crates/orchestrator/src/no_trade.rs`'s
  existing `NoTradeAccount` wrapper already refuses real order placement
  unless `EXECUTION_MODE=live` is set explicitly (no default — "never
  something you get by accident", per that module's own doc comment).
  Verification in the plan runs under `EXECUTION_MODE=no_trade` first;
  flipping to `live` against a funded or testnet account is a deliberate,
  separate, operator-authorized step (Task 7).

**`decision_id` — producer and persistence:** the orchestrator task above
generates one `uuid::Uuid::new_v4()` per fired `Mock*` signal (nothing
upstream carries or needs one — most `SignalEvent`s never become a
decision). It's written to two places, both already shaped for this: (1)
`signal_log.decision_id`, linking the persisted signal to the decision it
produced, and (2) `decision_log` via `state_store.log_decision(...)` —
an existing L5 method with **zero production call sites today** (`grep
-rn "log_decision" crates/*/src` only matches the trait/impl definitions
and a CLI test fake); this task is its first real caller, making
`decision_log` the one audit trail for every decision fed to execution,
regardless of source.

**Persistence table is generic, not mock-specific** (row 10): `signal_log`
stores *any* `SignalEvent` — `signal_id` (text, e.g.
`"mock_volume_cross"`, `"extreme_volume_reversal"`), a `record jsonb`
column holding a serialized `SignalEventDto` mirror (variant-specific
fields like `buy_ma`/`sell_ma`/`magnitude`/`projected_move` live inside
that jsonb blob, not as dedicated columns — same DTO-mirror convention
`state_store::dto` already uses for `WallObservationDto`/`LevelSourceDto`,
per that module's own reasoning: domain types don't derive `serde`,
storage-format concerns stay in `state_store`), and a nullable
`decision_id` (`NULL` for a fired signal that didn't produce a decision
— true of every non-mock signal today, since nothing consumes those into
decisions yet).

### Live position persistence (row 14)

One new orchestrator task, `run_position_sync`, merges two trigger
sources into the same action — `state_store.persist(executor
.position_state(pair)).await`:

1. `Executor::subscribe_state_changes()` — fires on every
   `PositionStateEvent` (`Opened`/`Closed`/`StoppedOut`/`StopLossMoved`/
   `NotPlaced`/`AlreadyClosed`), i.e. every local lifecycle transition.
2. `MarketDataFeed::subscribe_account_events()`, filtered to
   `AccountEvent::Order` updates for a pair currently holding an open
   position — i.e. "position... updated on exchange on receiving exchange
   data regarding order execution", literally: a fill notification from
   the exchange re-persists that pair's current state.

No change to `OpenPosition`'s fields or to how/when a position is
considered open (that would be a bigger re-architecture, out of scope for
a persistence refinement) — this task only makes sure whatever the
in-memory state already is gets written to Postgres promptly, instead of
only at the next process boot.

## Out of scope

- Re-deriving `open_price`/fill quantity from actual exchange fills
  instead of assuming immediate fill at the requested price (a bigger
  execution-engine change; row 14 here only closes the *persistence*
  gap, not the *fill-accuracy* gap).
- Any change to `main/`'s mq_gateway decision path, or to the existing
  `ExtremeVolumeReversal`/`VolumeProjectedMove` `SignalConfig` variants'
  own detection math (only their shared `SignalEvent` enum gains new
  `Mock*` variants; nothing about the real checks changes).
- Take-profit/target selection for the mock signal — reuses the existing
  `nearest_in_direction` level-based `close_price`, unchanged.

## Plan

See [2026-09-15-executor-refinement-plan.md](../plans/2026-09-15-executor-refinement-plan.md).
