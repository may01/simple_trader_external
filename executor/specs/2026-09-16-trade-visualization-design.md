# Trade visualization — decisions, position events, and chart markers — design

Part of [architecture index](2026-09-04-architecture-design.md). Extends
[main_goal.md](main_goal.md)'s Interfaces bullet on the Visualizer, and
follows on from
[2026-09-15-executor-refinement-design.md](2026-09-15-executor-refinement-design.md)
(Task 7 gave `decision_log` its first production writer; Task 8 gave
live position persistence, but only to `position_state`, not
`event_log`).

## Purpose

Show, on the pair dashboard: where trades actually occurred on the
candle chart at their real price, the concrete prices a decision
carried (open, stop-loss, expected close) as markers at the moment
they were set, and two panels printing position updates and decision
updates as they happen — all without adding anything to the
executor's critical trading path beyond one more synchronous DB write
of the same class it already performs for crash recovery.

## Relationship to the deferred 2026-09-12 design

[2026-09-12-visualizer-state-integration-design.md](2026-09-12-visualizer-state-integration-design.md)
was deferred because none of its data sources were verified against a
real running executor. This design:

- **Replaces §3** (Event Log panel) with a chart-markers-plus-panel
  design instead of a list-only panel.
- **Narrows and replaces §4** (entry/SL/TP overlay). This design does
  **not** use `current_levels`/`Level`/`LevelKind` (`main/`'s advisory
  support/resistance/target/stop-loss reference levels) at all. What
  the user asked for — "open price, stop loss price, expected close
  price" — are the concrete, already-computed prices carried on
  `PositionStateEvent::Opened`/`StopLossMoved`, a different and
  simpler data source than `current_levels`.
- **Leaves §2** (`last_reconciliation`) and **§4a** (analysis overlay)
  out of scope, unchanged from the original deferral reasoning: `
  last_reconciliation` is structurally unreachable from this process,
  and `current_analysis` still has no producer in `main/`.

## The precondition that was blocking this — now partly resolved

- `decision_log` has a real production producer since
  2026-09-15's Task 7 (the orchestrator's mock-signal decision loop,
  `crates/orchestrator/src/system.rs:860`).
- `event_log` still has **zero** production call sites — `grep -rn
  "log_event(" crates/*/src` matches only the trait/impl definitions
  and a CLI test fake. `run_position_sync` (Task 8,
  `crates/orchestrator/src/system.rs`) receives the real
  `PositionStateEvent` on every state-change trigger but only forwards
  it into `state_store.persist(...)` (the current-snapshot upsert) —
  the event value itself is discarded right after. Layer 1 below
  closes this gap with one additional call at that same call site,
  using the event already in hand — no new subscription, no new
  trigger.

## Decisions

### 1. `state_store`/orchestrator: wire `log_event` at the existing trigger

In `run_position_sync`'s state-change branch (triggered by
`Executor::subscribe_state_changes()`), add
`state_store.log_event(pair.clone(), event.clone(), Ts(exchange_adapter::now_ms())).await`
alongside the existing `persist(...)` call, alerting (not panicking)
on failure — same `AlertKind` pattern the persist-failure path already
uses. The account-event trigger (order fills) has no
`PositionStateEvent` to log — it only re-persists the snapshot, as
today; `log_event` is called only where a real lifecycle event exists.

### 2. `PgStateReader` gains `read_event_log`

Same pattern as its existing `read_decision_log`/`read_wall_snapshots`
— exposes SQL `StateStoreImpl` already runs and tests, on the
dashboard's `SELECT`-only role. No write method is added to this
reader type (unchanged rule from the 2026-09-12 design §1).

### 3. `visualizer_backend`: two thin wrappers

```rust
pub async fn position_events(&self, pair: Pair, from: Ts, to: Ts)
    -> Result<Vec<(Ts, PositionStateEvent)>, VisualizerError>;
pub async fn decisions(&self, pair: Pair, from: Ts, to: Ts)
    -> Result<Vec<(Ts, DecisionRecord)>, VisualizerError>;
```

Same `?`-propagation shape as `historical`/`wall_snapshots` — a
database error degrades to `VisualizerError`, never a panic.

> **Amended during implementation (Task 3b, inserted between Layers 3
> and 4):** the original pass of this design (and the plan built from
> it) specified these as bare `Vec<PositionStateEvent>`/
> `Vec<DecisionRecord>`, following `event_log`/`decision_log`'s
> existing read convention of discarding `recorded_at`/`received_at`
> after using it only for `ORDER BY`. That convention was correct for
> a list-only panel (arrival order is enough) but not for this design's
> chart markers, which need a real `(time, price)` point — a gap the
> pre-flight scan and every layer's own review missed until Layer 4's
> implementer traced the wire shape and found no timestamp anywhere in
> it. The fix threads a real `Ts` through `state_store`'s
> `EventLogStream`/`DecisionLogStream` item types (now
> `(Ts, PositionStateEvent)`/`(Ts, DecisionRecord)`, sourced from the
> same `recorded_at`/`received_at` column the `ORDER BY` already uses)
> and through these two wrapper methods, as shown above. See §4's own
> amendment note for the resulting wire shape.

### 4. `visualizer_server`: two routes + DTOs

```
GET /api/pair_events?pair=&from=&to=     -> Vec<PositionEventEntryDto>
GET /api/pair_decisions?pair=&from=&to=  -> Vec<DecisionEntryDto>
```

`PositionStateEventDto` mirrors all 6 `PositionStateEvent` variants
(`NotPlaced`, `Opened`, `Closed`, `StoppedOut`, `AlreadyClosed`,
`StopLossMoved`) — same externally-tagged shape convention as every
other DTO in this crate. `DecisionRecordDto` mirrors `DecisionRecord`'s
two variants (`Decision`/`Force`). Not-ready (schema unapplied) or no
rows yet → `[]`, HTTP 200 — same posture as every existing handler in
`routes.rs`. Read-only, no `AppState::books()`/poller involvement,
same as `pairs_handler`'s plain `state_store` reads.

> **Amended during implementation (Task 3b):** each response entry is
> now wrapped — `PositionEventEntryDto { ts: Ts, #[serde(flatten)]
> event: PositionStateEventDto }` and the equivalent `DecisionEntryDto`
> for records — so the wire shape is `{"ts": <epoch-ms number>,
> "Opened": {...}}` (or whichever variant), `ts` a sibling key to the
> externally-tagged variant, not nested under it. This keeps every
> field access this design originally specified
> (`entry["Opened"]["open_price"]`, `entry["Decision"]["kind"]`)
> unchanged while adding the timestamp the chart markers require. See
> §3's amendment note for why.

### 5. Frontend — two panels, chart markers, no line geometry

**Panels** (`pair.html`, rendered/polled by `pair.js` on the same
cadence as the existing position summary):

- **Decisions** — one row per `decision_log` entry: id, side, kind
  (Open/Close/Modify or Force's CloseNow), timeframe, `main_levels`,
  in arrival order.
- **Position Events** — one row per `event_log` entry, kind-specific
  text (see marker table below for which kinds carry a price).

**Chart markers** — every event draws at its own `(ts, price)` point,
no line connecting one event to another across time. One series per
marker kind, mirroring `createWallSeries`'s per-side-series pattern
(`chart.addLineSeries({lineVisible: false, pointMarkersVisible: true,
pointMarkersRadius: ...})` — the exact technique this file already
uses for wall dots):

| Event | Marker(s) | Style |
|---|---|---|
| `Opened` | 3 dots at `open_ts`: `open_price`, `stop_loss_price`, `close_price` | entry = side-colored arrow (buy=green up, sell=red down); stop-loss = orange dot; target = blue dot |
| `StopLossMoved` | 1 dot at `(ts, new_stop_loss_price)` | same orange stop-loss style as `Opened`'s — a trailing stop reads as a staircase of dots |
| `Closed` | 1 dot at `(ts, close_price)` | green checkmark-style — distinct from `StoppedOut` |
| `StoppedOut` | 1 dot at `(ts, stop_price)` | red X-style — distinct from `Closed` |
| `NotPlaced` | none | panel-only — no price exists to plot |
| `AlreadyClosed` | none | panel-only |

`AlreadyClosed` fires when a `main/` command arrives for a position
already closed locally — per `main_goal.md`, "reported back as
'already closed,' not an error." It is a no-op audit fact (no new
state, no price), so it belongs in the Position Events panel as a log
line only, never on the chart. `NotPlaced` is the same shape of
decision: reasoned-about but nothing opened, carries a `reason`
string, panel-only.

### 6. Update mechanism: poll only

Both panels and the chart markers refresh on `pair.js`'s existing poll
interval (same one driving position summary / freshness) via
`/api/pair_events` and `/api/pair_decisions`. No new `/ws` message
type, no change to `poll.rs` or the broadcast enum — confirmed choice,
matching the deferred design's original reasoning ("no live push...
polling Postgres is the only transport that exists here").

## Out of scope

- `current_levels`/`LevelDto` — `main/`'s advisory reference levels.
  Not what was asked here; a future request that specifically wants
  those shown is a separate, additive feature.
- `current_analysis`/analysis overlay — no producer in `main/` yet,
  unchanged from the 2026-09-12 deferral.
- `last_reconciliation` — structurally unreachable from this process,
  unchanged from the 2026-09-12 deferral §2.
- Live push over `/ws` for either panel — poll only, per confirmed
  decision.
- Any write path from the dashboard beyond the one orchestrator-side
  `log_event` call in Layer 1 — the dashboard itself remains
  `SELECT`-only, unchanged from every prior visualizer design.
- Continuous or bounded line segments connecting a trade's levels
  across time — considered and explicitly rejected in favor of
  point-in-time markers.

## Testing

DB-backed, `docker compose run --rm test`, schema-per-test via
`test_support::test_db` — same convention as every other Postgres-era
test in this codebase.

- `orchestrator`: extend the existing `run_position_sync` test fixture
  to assert a state-change trigger also produces an `event_log` row
  (via the fake `StateStoreImpl`'s spy), not only a `persist` call.
- `PgStateReader::read_event_log`: dashboard-role round trip against a
  fixture the executor's `StateStoreImpl` writes; cross-pair isolation.
- `visualizer_backend::position_events`/`decisions`: a database error
  degrades to `VisualizerError`, never a panic — same property already
  covered for `historical`.
- `visualizer_server`: `/api/pair_events`/`/api/pair_decisions` route
  tests — not-ready (empty, HTTP 200), cross-pair isolation, arrival
  order, and `NotPlaced`/`AlreadyClosed` present in the JSON but
  carrying no price fields.
- Frontend: `node --check` syntax only (no JS runner in this project),
  plus a served-HTML assertion that both new panel container ids are
  present — same pattern as every existing markup-presence test.
- Docker/UI verification: with the mock signal already live
  (2026-09-15 Task 7) under `EXECUTION_MODE=no_trade`, open
  `pair.html?pair=BTCUSDT` — Decisions panel shows real fired
  decisions, Position Events panel shows real `Opened`/`Closed`/
  `StoppedOut` rows, and the chart shows the corresponding dots at the
  right prices and times.

> **Caveat found during the final whole-branch review:** `no_trade`
> cannot actually produce this. `NoTradeAccount::place_order` rejects
> every order, and `Executor::open_position` propagates that error
> before ever reporting `PositionStateEvent::Opened` — so under
> `no_trade` the Decisions panel populates (decision_log's producer
> doesn't depend on order placement succeeding) but Position Events
> and the chart markers see at most `NotPlaced` rows, never `Opened`/
> `StopLossMoved`/`Closed`/`StoppedOut`. There is no paper-trading mode
> to fall back to (`main.rs` accepts only `no_trade`/`live`). Until a
> paper-fill mode exists, verifying the chart-marker path against real
> data means seeding `event_log` directly (raw SQL or a one-off
> `StateStoreImpl` writer, the same technique `passive.rs`'s own tests
> already use) for one pair with an `Opened` → `StopLossMoved` →
> `StoppedOut`/`Closed` sequence, then opening `pair.html` and
> confirming the six marker kinds render at the right prices/times with
> `Closed` visually distinct from `StoppedOut` — a manual step, not
> something `docker compose run --rm test` covers.
