# Trade visualization — decisions, position events, and chart markers — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

Implements
[2026-09-16-trade-visualization-design.md](../specs/2026-09-16-trade-visualization-design.md).
Base: `layer-implementation` worktree, current HEAD `a442027`.

> **Amended after execution.** Layers 1-4 below shipped as written, plus
> one inserted, unplanned task — **Task 3b**, between Layers 3 and 4 —
> found necessary when Layer 4's implementer discovered neither
> `/api/pair_events` nor `/api/pair_decisions` carried a timestamp at
> all (the interfaces below still show the original, pre-3b signatures;
> see the design doc's §3/§4 amendment notes for the corrected shape:
> `EventLogStream`/`DecisionLogStream` now yield `(Ts, T)` tuples, and
> both routes wrap each entry as `{"ts": ..., "<Variant>": {...}}` via
> new `PositionEventEntryDto`/`DecisionEntryDto` wrappers). Layer 5's
> Docker/UI verification also has a caveat the plan didn't anticipate —
> see the design doc's Testing section.

## Global Constraints

- Work happens in the `layer-implementation` worktree
  (`trade_executor/.worktrees/layer-implementation`), branch
  `layer-implementation`. One commit per layer, after its tests are
  green.
- Layer N is not started until layer N-1's tests are green in Docker.
- No existing public function signature changes except the one
  documented addition inside `run_position_sync` (Layer 1) — everything
  else is new, additive surface.
- `PgStateReader` stays `SELECT`-only — no write method is added to it
  at any layer.
- Decimals stay strings on the wire (`rust_decimal` through JSON), same
  as every existing DTO in `visualizer_server::dto`.
- Match existing code conventions exactly: doc comments explain *why*,
  `Ts`/`Pair`/`Side` from `exchange_adapter`, the `CorruptRow::Surface`
  policy for every new `PgStateReader` read (dashboard-side reads
  surface corruption rather than skipping it, per `load_all`'s own
  precedent).

---

## Docker Entry Points

```bash
docker compose run --rm test
docker compose up -d postgres executor visualizer
# http://127.0.0.1:8090/pair.html?pair=BTCUSDT
```

Verified:
- [ ] `docker compose run --rm test` green, including every new test below
- [ ] Decisions panel shows real `decision_log` rows for a pair with a
      fired mock signal
- [ ] Position Events panel shows real `event_log` rows (Opened/Closed/
      StoppedOut/StopLossMoved) for the same pair
- [ ] Chart shows the marker table from the design (§5) at the right
      prices and times, with `Closed` visually distinct from
      `StoppedOut`

---

## Layer 1: `state_store`/orchestrator — close the `event_log` gap

### Interface

```rust
// crates/state_store/src/pg.rs, impl PgStateReader
pub async fn read_event_log(&self, pair: Pair, from: Ts, to: Ts)
    -> Result<EventLogStream, StoreError>;
```

No new public signature in `orchestrator` — `run_position_sync`'s
internal state-change branch changes shape (it currently discards the
`PositionStateEvent` after reading its `pair`; it must keep the event
and pass it to `log_event` too), but its own signature is unchanged.

### Integration test → Layer 2 (RED, Docker)

Extend the existing `PositionSyncStateStoreSpy` (`crates/orchestrator/
src/tests.rs`) with a `logged_events: Mutex<Vec<PositionStateEvent>>`
field and a `logged_event_calls_for(pair_str) -> usize` accessor,
mirroring `persist_calls_for`'s own shape. Override its `log_event` to
record into that field instead of the current no-op `Ok(())` stub.

```rust
// crates/orchestrator/src/tests.rs
#[tokio::test]
async fn position_state_events_are_logged_to_the_event_log_too() {
    let executor_spy = Arc::new(PositionSyncExecutorSpy::new());
    let state_store_spy = Arc::new(PositionSyncStateStoreSpy::default());
    let account_feed = Arc::new(FakeAccountFeed::empty());
    let (_shutdown_tx, shutdown_rx) = tokio::sync::watch::channel(false);

    let handle = tokio::spawn(run_position_sync(
        executor_spy.clone() as Arc<dyn ExecutionEngine>,
        account_feed as Arc<dyn MarketDataFeed>,
        state_store_spy.clone() as Arc<dyn StateStore + Send + Sync>,
        Arc::new(StdoutAlerts::new()),
        shutdown_rx,
    ));

    executor_spy.emit_state_event(opened_event("BTCUSDT"));
    executor_spy.emit_state_event(closed_event("BTCUSDT"));
    tokio::time::sleep(Duration::from_millis(50)).await;

    // The existing persist behaviour must be unchanged...
    assert_eq!(state_store_spy.persist_calls_for("BTCUSDT"), 2);
    // ...and now event_log gets a row for each transition too.
    assert_eq!(state_store_spy.logged_event_calls_for("BTCUSDT"), 2);

    handle.abort();
}

#[tokio::test]
async fn account_order_events_do_not_write_to_the_event_log() {
    // The account-event trigger (order fills) has no PositionStateEvent
    // to log -- it only re-persists the snapshot, unchanged from today.
    // Reuses `account_order_events_for_an_open_position_also_persist`'s
    // fixture; asserts `logged_event_calls_for` stays 0 while
    // `persist_calls_for` is 1.
}
```

### Run to verify it fails

`cargo test -p orchestrator position_state_events_are_logged_to_the_event_log_too`
— expected: FAIL (`logged_event_calls_for` doesn't exist / stays 0).

### Unit tests (RED)

- `read_event_log` on `PgStateReader`: dashboard-role round trip
  against a fixture `StateStoreImpl` (executor role) writes — proves
  the grant, not just the query. Mirrors
  `the_read_only_state_reader_reads_wall_snapshots_too` in
  `crates/state_store/tests/pg_store.rs`.
- `read_event_log` never returns another pair's events (mirrors
  `read_wall_snapshots_excludes_rows_outside_the_window_and_other_pairs`).
- A corrupt/undecodable row surfaces as `Err`, not a silent gap —
  `CorruptRow::Surface`, distinct from `StateStoreImpl`'s own `Skip`
  policy for the exact same table (per `load_all`'s existing reasoning:
  the executor tolerates a gap it can recover from elsewhere; the
  dashboard has no elsewhere, so it must know).

### Implementation notes (no code bodies here — see design §1, §2)

- `run_position_sync`'s `PositionSyncTrigger::State(event)` match arm
  must produce `(pair, Some(event))` instead of just `pair`, threading
  the event past the existing `let Some(pair) = pair else { continue };`
  guard so it's still available after the `persist` call.
- Add `state_store.log_event(pair.clone(), event, Ts(exchange_adapter::now_ms())).await`
  after the existing `persist` call, only when the trigger was a state
  event (never for the account-event branch — there is no event value
  there).
- Failure alert: `AlertKind::PersistFailed` at `Severity::Warn` — same
  tier as `run_wall_snapshot_task`'s own persist-failure alert, and for
  the same reason stated there: this is a disposable audit/visualization
  row, not the crash-recovery source of truth (`position_state`,
  written by the adjacent `persist` call, already carries that weight
  at `Severity::Critical`). Losing one `event_log` row loses history,
  not correctness.
- `PgStateReader::read_event_log` reuses the exact SQL already in
  `StateStoreImpl::read_event_log` (`crates/state_store/src/pg.rs`),
  with `CorruptRow::Surface` in place of that method's `Skip` — same
  relationship `read_decision_log`/`load_all` already have to their own
  `StateStoreImpl` counterparts. Consider factoring both into a shared
  `read_event_log_rows(pool, pair, from, to, on_corrupt)` free function,
  matching `read_decision_log_rows`'s existing pattern, so the two
  copies cannot drift.

### Run full suite, commit

```bash
cargo test -p orchestrator -p state_store
git add crates/orchestrator crates/state_store
git commit -m "feat: log position-state events to event_log, expose it to the dashboard reader"
```

---

## Layer 2: `visualizer_backend` — thin wrappers

### Interface

```rust
// crates/visualizer_backend/src/lib.rs
pub async fn position_events(&self, pair: Pair, from: Ts, to: Ts)
    -> Result<Vec<PositionStateEvent>, VisualizerError>;
pub async fn decisions(&self, pair: Pair, from: Ts, to: Ts)
    -> Result<Vec<DecisionRecord>, VisualizerError>;
```

`decision_log` has **no `pair` column** (`migrations/0001_init.sql`) —
`PgStateReader::read_decision_log(from, to)` returns every pair's
decisions in the window, `pair` living only inside each record's own
payload. `decisions` filters the returned stream to `pair` in Rust
after decode, rather than adding a new jsonb-predicate query — no new
SQL, per this crate's own stated preference for reusing what
`StateStoreImpl` already runs and tests.

### Integration test → Layer 3 (RED, Docker)

```rust
// crates/visualizer_backend/src/lib.rs, #[cfg(test)]
#[tokio::test]
async fn position_events_reads_back_what_the_writer_logged() {
    // Seed via state_store (executor role): log_event(Opened), then
    // log_event(Closed), for BTCUSDT. backend.position_events(...)
    // must return both, in write order.
}
#[tokio::test]
async fn decisions_filters_to_the_requested_pair_only() {
    // Seed log_decision for BTCUSDT and ETHUSDT in the same window.
    // backend.decisions(BTCUSDT, ...) must return only the BTCUSDT one,
    // proving the in-Rust filter, since the query itself cannot.
}
```

### Unit tests (RED)

- A database error degrades to `VisualizerError`, never a panic — same
  property `a_database_error_degrades_to_a_typed_error_not_a_panic`
  already covers for `historical`; add the equivalent for both new
  methods.
- `position_events`/`decisions` on a pair/window with no rows returns
  `Ok(vec![])`, not an error.

### Run full suite, commit

```bash
cargo test -p visualizer_backend
git add crates/visualizer_backend
git commit -m "feat(visualizer_backend): expose position_events and decisions reads"
```

---

## Layer 3: `visualizer_server` — routes + DTOs

### Interface

```rust
// crates/visualizer_server/src/dto.rs

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum PositionStateEventDto {
    NotPlaced { pair: Pair, reason: String },
    Opened { pair: Pair, side: Side, size: Decimal, open_price: Decimal, stop_loss_price: Decimal, close_price: Decimal },
    Closed { pair: Pair, close_price: Decimal },
    StoppedOut { pair: Pair, stop_price: Decimal },
    AlreadyClosed { pair: Pair },
    StopLossMoved { pair: Pair, new_stop_loss_price: Decimal },
}
impl From<&PositionStateEvent> for PositionStateEventDto { ... }

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DecisionLevelDto { pub price: Decimal, pub kind: Option<String> }
// display-only, for the Decisions panel's `main_levels` listing -- NOT
// the current_levels chart overlay (out of scope, design's own note).

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TradeDecisionDto {
    pub id: String, pub pair: Pair, pub kind: String, // "Open"|"Close"|"Modify"
    pub side: Side, pub timeframe: String,            // "M1"|"M5"|"M15"|"M60"|"M240"
    pub main_levels: Vec<DecisionLevelDto>,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ForceActionDto { pub id: String, pub pair: Pair, pub kind: String /* "CloseNow" */, pub comment: String }
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum DecisionRecordDto { Decision(TradeDecisionDto), Force(ForceActionDto) }
impl From<&DecisionRecord> for DecisionRecordDto { ... }

// crates/visualizer_server/src/routes.rs
pub async fn pair_events_handler(
    State(state): State<Arc<AppState>>, Query(params): Query<HistoryParams>,
) -> Response { ... }
pub async fn pair_decisions_handler(
    State(state): State<Arc<AppState>>, Query(params): Query<HistoryParams>,
) -> Response { ... }
```

Routes added in `lib.rs`, alongside the existing `/api/pair_history`:

```
GET /api/pair_events?pair=&from=&to=     -> Vec<PositionStateEventDto>
GET /api/pair_decisions?pair=&from=&to=  -> Vec<DecisionRecordDto>
```

`kind`/`timeframe` are serialized as plain strings (not a nested
externally-tagged enum) — the SPA only ever displays them as text, per
design §5's panel description; no reason to hand it a shape it must
then re-stringify itself.

### Integration test → Layer 4 (RED, Docker)

```rust
// crates/visualizer_server/tests/passive.rs
#[tokio::test]
async fn pair_events_returns_real_outcomes_in_arrival_order() {
    // Seed event_log for a pair (Opened, then StoppedOut) via the
    // executor role. GET /api/pair_events returns both, in that order.
}
#[tokio::test]
async fn pair_decisions_returns_only_the_requested_pairs_decisions() {
    // Seed decision_log for two pairs. GET /api/pair_decisions?pair=X
    // returns only X's rows -- proves visualizer_backend's in-Rust
    // filter reaches the HTTP layer correctly.
}
```

### Unit tests (RED)

- Not-ready (schema unapplied) returns `[]`, HTTP 200, for both routes
  — same posture as every existing handler.
- Cross-pair isolation on both routes (`/api/pair_events` too, not only
  `/api/pair_decisions` — a pair filter bug could hide in either
  layer).
- A `NotPlaced`/`AlreadyClosed` row round-trips with no price fields
  present in its JSON (the enum variant simply has none), proving the
  DTO doesn't fabricate one.

### Constraints / notes

- Neither route touches `AppState::books()` or the poller — plain
  `state_store` reads via `visualizer_backend`, same shape as
  `pairs_handler`'s existing `load_all()` call.
- Update `dto.rs`'s own module doc comment (currently states "What is
  *not* ported is position-state events... `PgStateReader` exposes no
  event log" — no longer true after this layer).

### Run full suite, commit

```bash
cargo test -p visualizer_server
git add crates/visualizer_server
git commit -m "feat(visualizer_server): pair_events and pair_decisions routes"
```

---

## Layer 4: SPA — panels + chart markers

### Interface

```
pair.html    + two new panels: "Decisions", "Position Events"
js/api.js    + positionEvents(pair, fromMs, toMs) -> GET /api/pair_events
             + decisions(pair, fromMs, toMs)      -> GET /api/pair_decisions
js/pair.js   + renders both panels on load and on the same poll cadence
               as the existing position summary (design §6: poll only,
               no /ws change)
             + derives per-marker-kind arrays from position_events and
               calls chart.js's new setter (below) each poll tick
js/chart.js  + one addLineSeries({lineVisible: false, pointMarkersVisible: true, ...})
               per marker kind, exact technique already used by
               createWallSeries -- entry/buy, entry/sell, stop-loss,
               target, closed, stopped-out: 6 series total
             + setTradeMarkers(state, events) -- maps each
               PositionStateEventDto to its series per the design §5
               table (Opened -> 3 points across 3 series at the same
               ts; StopLossMoved -> 1 point on the stop-loss series;
               Closed/StoppedOut -> 1 point each on their own distinct
               series; NotPlaced/AlreadyClosed -> no chart point)
```

### Integration test → Layer 5 (RED, Docker)

```rust
// crates/visualizer_server/tests/passive.rs -- extends the existing
// "every asset the SPA references is actually served" test.
#[tokio::test]
async fn pair_html_has_decision_and_position_event_panel_containers() {
    // Assert both new panel container ids are present in served pair.html.
}
```

### Unit tests (RED)

Rust-side only, per this project's no-JS-runner convention:

- `/pair.html` still 200 with both new panel container ids present.
- `node --check crates/visualizer_server/static/js/{api,pair,chart}.js`
  — no syntax errors (run as a plain shell step in this task, not a
  `#[test]`, matching Task 3's own Step 10 precedent).

### Constraints / notes

- No CDN, vendored only — unchanged rule.
- Six marker series, not one shared series with per-point overrides —
  matches `createWallSeries`'s existing per-kind-series pattern and
  keeps each kind's color/shape declarative instead of computed per
  point.
- `AlreadyClosed`/`NotPlaced` render in the Position Events panel as
  plain text rows (no price to show) — never passed to `chart.js` at
  all, per design §5.

### Run full suite, commit

```bash
cargo test -p visualizer_server
git add crates/visualizer_server
git commit -m "feat(spa): decisions + position-events panels, per-kind chart markers"
```

---

## Layer 5: verification

- [ ] `docker compose run --rm test` green
- [ ] `docker compose up -d postgres executor visualizer`; with the
      mock signal already live (2026-09-15 Task 7) under
      `EXECUTION_MODE=no_trade`, wait for at least one crossing
- [ ] `SELECT count(*) FROM event_log;` and
      `SELECT count(*) FROM decision_log;` both non-zero and growing
- [ ] Open `pair.html?pair=BTCUSDT` — Decisions panel shows real fired
      decisions, Position Events panel shows real `Opened`/`Closed`/
      `StoppedOut`/`StopLossMoved` rows, chart shows the marker table
      from the design at the right prices/times, `Closed` visually
      distinct from `StoppedOut`
- [ ] Stop the executor — both panels and chart markers keep showing
      last-read data rather than erroring; only freshness on the
      Overview page visibly degrades (same posture as every other
      panel in this dashboard)
