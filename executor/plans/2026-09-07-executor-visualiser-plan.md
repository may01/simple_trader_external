# Executor visualiser — implementation plan

Implements [executor-visualiser-design.md](../specs/2026-09-07-executor-visualiser-design.md),
including its [L5 addendum](../specs/2026-09-07-executor-visualiser-design.md#l5-addendum-event_log)
(amends [L5-state-store.md](../specs/layers/L5-state-store.md)).

Layer order for this feature (bottom to top — each layer's integration
test must be RED against the layer below before that layer starts):

0. Docker entry points
1. `state_store` — `event_log` addition (L5)
2. `visualizer_backend` — snapshot/event/book-replay extensions (L8a)
3. `visualizer_server` — new crate, HTTP+WS (L8b)
4. Frontend — static SPA served by `visualizer_server`
5. `orchestrator` — wiring (L9)

Signatures below are plan-only pseudo-Rust (`{ ... }` bodies) — not
compiled code.

## Docker Entry Points

```bash
# unchanged — now also exercises the new crates (workspace members)
docker compose run --rm test

# new — runs the actual binary with the visualiser reachable
docker compose up run
# dashboard at http://localhost:8090/
```

`docker-compose.yml` gains a `run` service:

```yaml
services:
  test:
    build: .
    command: ["cargo", "test", "--workspace"]
  run:
    build:
      context: .
      target: release
    ports:
      - "8090:8090"
    environment:
      - VISUALIZER_BIND_ADDR=0.0.0.0:8090
      # existing required L9 env vars (exchange creds, pairs, etc.)
```

**Superseded during implementation (Task 5):** `test`'s `build: .` had
no explicit `target`, which silently built the *last* Dockerfile stage
instead of the intended `test` stage once `release`/`release-builder`
stages were appended later — needed `target: test` added to fix.
`run`'s environment also needs `VISUALIZER_STATIC_DIR` (the directory
`GET /*` serves the frontend from in the container — see the design
spec's `visualizer_server` config) alongside `VISUALIZER_BIND_ADDR`.
Actual final `docker-compose.yml` is the source of truth for the full
env var list.

Also superseded: the final `docker-compose.yml` binds `run`'s port as
`"127.0.0.1:8090:8090"`, not `"8090:8090"` — a final-review-round fix
so the dashboard isn't reachable from outside the host (see the design
spec's trust-boundary note).

`OrchestratorConfig` (crates/orchestrator/src/config.rs) gains
`visualizer_bind_addr: SocketAddr`, read from `VISUALIZER_BIND_ADDR`,
same env-based convention as every other L9 config field.

Verified:
- [ ] `docker compose run --rm test` passes, including new crates.
- [ ] `docker compose up run` boots and serves `GET /pairs` at
      `localhost:8090`.

## Layer 1: `state_store` — `event_log` (L5)

### Interface

```rust
// crates/state_store/src/lib.rs

pub trait StateStore {
    // existing: persist, load_all, reconcile, log_decision, read_decision_log ...

    fn log_event(&self, pair: Pair, event: PositionStateEvent, received_at: Ts)
        -> Result<(), StoreError> { ... }
    fn read_event_log(&self, pair: Pair, from: Ts, to: Ts) -> PositionEventLogStream { ... }
}

pub type PositionEventLogStream = Pin<Box<dyn Stream<Item = PositionStateEvent> + Send>>;
```

Storage: new sled tree `event_log`, keyed `(pair, received_at, seq)` —
same convention `decision_log` already uses. JSON encoding, matching
`decision_log`'s documented reason (`rust_decimal`'s `Deserialize`
needs a self-describing format).

### Integration test → orchestrator wiring (RED, Docker)

Written before either side exists:

```rust
// A fake ExecutionEngine emits PositionStateEvent on subscribe_state_changes.
// Two independent subscribers drain it concurrently: one persists via
// log_event, one just counts. Both must see every event, in order,
// with neither blocking the other.
#[tokio::test]
async fn event_log_subscriber_and_mq_relay_subscriber_dont_interfere() { ... }
```

### Unit tests (RED)

- `log_event`/`read_event_log` round-trips every `PositionStateEvent`
  variant (Opened/Closed/StoppedOut/StopLossMoved/NotPlaced/
  AlreadyClosed) unchanged.
- Ordering: events for the same pair come back ordered by
  `received_at` then insertion order (ties).
- Cross-pair isolation: `read_event_log("BTCUSDT", ...)` never returns
  another pair's events.
- Empty range returns empty stream, not an error.

### Constraints / notes

- `event_log` is a second, independent `subscribe_state_changes`
  broadcast subscription — never a tap on `mq_gateway`'s existing
  relay subscription. Confirms L5 doc's "multi-consumer by design, no
  interference" claim is actually true, not just asserted.
- Does not participate in `reconcile` — audit trail only, same as
  `decision_log`.

## Layer 2: `visualizer_backend` extensions (L8a)

### Interface

```rust
// crates/visualizer_backend/src/lib.rs

pub struct PairSnapshot {
    pub pair: Pair,
    pub position: execution::PositionState,
    pub reconciliation: Option<state_store::ReconciliationReport>,
}

pub type PositionEventStream = Pin<Box<dyn Stream<Item = execution::PositionStateEvent> + Send>>;
pub type OrderBookStream = Pin<Box<dyn Stream<Item = market_data::OrderBookSnapshot> + Send>>;

impl VisualizerBackend {
    pub fn new(
        store: Arc<dyn MarketDataStore + Send + Sync>,
        feed: Arc<dyn MarketDataFeed + Send + Sync>,
        mode: Arc<LiveModeFlag>,
        state_store: Arc<dyn StateStore + Send + Sync>,
        engine: Arc<dyn ExecutionEngine + Send + Sync>,
    ) -> Self { ... }

    pub fn pair_snapshot(&self, pair: Pair) -> Result<PairSnapshot, VisualizerError> { ... }

    // historical: state_store::read_event_log; live: engine.subscribe_state_changes()
    // filtered to `pair` — same historical/live decision point as `view()`.
    pub fn position_events(&self, pair: Pair, from: Ts, to: Ts)
        -> Result<PositionEventStream, VisualizerError> { ... }

    // runs market_data::BookTracker over historical()/view()'s stream.
    pub fn order_book_view(&self, pair: Pair, from: Ts, to: Ts)
        -> Result<OrderBookStream, VisualizerError> { ... }
}
```

### Integration test → visualizer_server (RED, Docker)

```rust
// Fixture MarketDataStore + fixture StateStore + fake ExecutionEngine.
// Asserts pair_snapshot/position_events/order_book_view all read
// correctly from fixtures, with zero calls into a real engine's
// decision path (the fake engine panics if any method beyond
// subscribe_state_changes is called).
#[tokio::test]
async fn backend_serves_full_pair_view_without_touching_engine_decision_path() { ... }
```

### Unit tests (RED)

- `pair_snapshot`: flat pair, open pair, pair with a recorded
  reconciliation discrepancy, unknown pair (never persisted).
- `position_events`: historical-only range returns `read_event_log`
  contents; live mode (per existing `LiveModeFlag`) switches to the
  engine's broadcast — same shape as
  `view_switches_to_the_live_feed_once_live_is_set`.
- `order_book_view`: reconstructs the identical sequence
  `market_data::BookTracker` produces internally, given a known
  snapshot+update fixture sequence.
- Panic/error degradation: any underlying store/engine panic degrades
  to `VisualizerError`, per existing `historical`/`view` pattern —
  extend the existing `PanickingStore`-style fixture to also cover
  `state_store`/`engine` panics.

### Constraints / notes

- No new dependency on `mq_gateway` — this crate only ever reads
  `market_data`, `state_store`, and `execution`'s
  `ExecutionEngine::subscribe_state_changes` (already public on that
  trait; no new method needed there).

## Layer 3: `visualizer_server` (new crate, L8b)

New workspace member: `crates/visualizer_server`. Depends on
`visualizer_backend`, `state_store` (see note below), `axum`,
`tokio-tungstenite` (via axum's built-in ws support),
`serde`/`serde_json`.

Note (corrected during implementation): the original draft of this
section omitted `state_store` from the dependency list while still
requiring it as a `new()` parameter below — an inconsistency in the
plan itself, not a later addition. It's genuinely needed: see the
`GET /pairs/:pair/history` route note below for why the history route
calls `state_store::read_event_log` directly rather than going through
`visualizer_backend::position_events`.

**This note itself was superseded during Task 3's review-fix round**,
which removed the `state_store` dependency from `visualizer_server`
entirely (added `VisualizerBackend::historical_order_book`/
`historical_position_events` instead, so the history route no longer
needs its own store handle). See the design spec's Architecture
section for the final, correct dependency list.

### Interface

**Superseded during implementation** (Task 3's review-fix round, then
Task 5's orchestrator wiring) — left as-is below for the historical
record; see `crates/visualizer_server/src/lib.rs` for the actual final
signatures. In short: no `state_store` param (removed, see the note
above); `new()` gained `shutdown: watch::Receiver<bool>` and
`alerts: Arc<dyn Alerts>` params instead of taking `shutdown` at
`serve()` time; `VisualizerServerConfig` gained a `static_dir: PathBuf`
field; `serve()` takes no arguments (pulls the shutdown signal it was
given at construction).

```rust
// crates/visualizer_server/src/lib.rs

pub struct VisualizerServerConfig {
    pub bind_addr: SocketAddr,
    pub pairs: Vec<Pair>,
}

pub struct VisualizerServer {
    // Arc<VisualizerBackend>, Arc<dyn StateStore + Send + Sync>, config
}

impl VisualizerServer {
    pub fn new(
        backend: Arc<VisualizerBackend>,
        state_store: Arc<dyn StateStore + Send + Sync>,
        config: VisualizerServerConfig,
    ) -> Self { ... }

    // Binds and serves until `shutdown` fires. Never panics the caller —
    // a bind failure is reported once via the returned Result, not a crash.
    pub async fn serve(self, shutdown: tokio::sync::watch::Receiver<bool>)
        -> Result<(), std::io::Error> { ... }
}

// wire message enum sent over the WS, one variant per broadcast source
#[derive(Serialize)]
#[serde(tag = "type")]
pub enum LiveMessage {
    Snapshot(PairSnapshotDto),
    Candle(CandleUpdateDto),
    Trade(TradeTickDto),
    Book(OrderBookSnapshotDto),
    Position(PositionStateEventDto),
    Resync, // sent after a Lagged — client should refetch snapshot
}
```

Routes:
- `GET /pairs` → `Vec<PairSnapshotDto>` (JSON).
- `GET /pairs/:pair/history?from&to` → candles+trades+book+events for
  the range (JSON). **Correction during implementation:** the original
  plan text said this goes "via `visualizer_backend::historical`/
  `order_book_view` with `LiveModeFlag` forced off for the call" — that
  was never actually implementable safely: `LiveModeFlag` is one
  shared `AtomicBool` per backend, not scoped per-request, so mutating
  it for the duration of one History call would race any concurrently
  open Live WS connection reading the same flag. Actual (correct)
  approach: call `visualizer_backend::historical()` directly (it never
  checks `is_live()`, unlike `order_book_view`/`view`/
  `position_events`), fold order-book state via `market_data::
  BookTracker` locally the same way `order_book_view` does internally,
  and read the event feed via `state_store::read_event_log` directly —
  this is why `state_store` is a real, load-bearing dependency of this
  crate (see the note above), not just a leftover parameter.
- `GET /pairs/:pair/ws` → upgrades to WS, live tail only (see design's
  Data flow section for the snapshot→subscribe→forward sequence and
  `Lagged` → `Resync` handling). Sends a `Snapshot` message (current
  `pair_snapshot` only) on connect, then live events — no history
  backfill over the socket; a frontend needing backfill calls the
  history route first, then opens the WS (see design spec's WS section
  for why the originally-planned "recent-history-window over WS" was
  dropped).
- `GET /*` → static file serve from the crate's bundled `static/` dir
  (frontend build).

### Integration test → frontend (RED, Docker)

```rust
// Spin VisualizerServer against a fixture VisualizerBackend on an
// ephemeral port. A WS test client connects, asserts message order:
// Snapshot first, then live events as they're pushed through the
// fixture's broadcast. A second test floods the fixture's channel
// past capacity and asserts a Resync message arrives instead of a
// dropped connection.
#[tokio::test]
async fn ws_client_sees_snapshot_then_live_events_in_order() { ... }
#[tokio::test]
async fn lagged_broadcast_triggers_resync_not_disconnect() { ... }
```

### Unit tests (RED)

- `GET /pairs` shape and content against a multi-pair fixture.
- `GET /pairs/:pair/history` range boundaries (empty range, range
  outside stored data, partial overlap).
- Unknown pair on any route → 404, not a panic.
- WS reconnect: a second connection after a forced disconnect gets a
  fresh `Snapshot`, not stale state from the first connection.

### Constraints / notes

- Per design: **no command path.** No route accepts writes. Force
  actions stay on `cli` → `mq_gateway`.
- Per-client state (subscription handles, book reconstruction state)
  lives only for the WS connection's lifetime — nothing leaks across
  reconnects.

## Layer 4: Frontend (static SPA)

Lives at `crates/visualizer_server/static/` — plain HTML/CSS/JS,
`lightweight-charts` vendored as a committed file (no CDN dependency
at runtime, no build step). Consumes exactly the REST/WS contract
Layer 3 defines above — that contract *is* this layer's interface,
already fixed by the time this layer starts.

### Pages

- **Overview** (`/`): fetches `GET /pairs`, renders one row per pair —
  status (flat/open+side) and reconciliation flag. Links to each
  pair's page.
- **Pair page** (`/pair.html?pair=BTCUSDT`): Live/History toggle.
  - Live: opens `GET /pairs/:pair/ws`, renders candlestick chart with
    position overlay (entry/SL/TP lines, trade markers), order-book
    depth panel, event log panel — all driven by `LiveMessage`
    variants. On `Resync`, refetch `GET /pairs` for that pair and
    continue.
  - History: date-range picker → `GET /pairs/:pair/history`, renders
    the same three panels from the static response, no WS.

### "Integration test" → running server (manual + scripted)

Per this repo's standing rule (UI changes verified in a real browser,
not just type/unit checks):
- Scripted: a small WS client script (or the same test harness as
  Layer 3's Rust WS tests, reused) asserts the page's expected message
  schema end-to-end against `docker compose up run`.
- Manual: start `docker compose up run`, open `localhost:8090` in a
  browser, confirm both Overview and a Pair page (Live and History)
  render correctly against real (or replayed) data before this layer
  is marked done.

### Constraints / notes

- No JS build tooling introduced — vanilla JS keeps this servable as
  static files with zero new toolchain, consistent with "no UI/rendering
  technology chosen" being this spec's own thing to decide, not
  something requiring a build pipeline this project doesn't otherwise
  have.

## Layer 5: `orchestrator` wiring (L9)

### Interface (changes to `system.rs`)

```rust
// RunningSystem gains:
pub visualizer_server: Arc<visualizer_server::VisualizerServer>,

// Step 9 (extended): interfaces, wired to L3/L4/L1/L5.
let visualizer = Arc::new(VisualizerBackend::new(
    market_data.clone() as Arc<dyn MarketDataStore + Send + Sync>,
    market_data.clone() as Arc<dyn MarketDataFeed + Send + Sync>,
    live_mode.clone(),
    state_store.clone() as Arc<dyn StateStore + Send + Sync>,
    executor.clone() as Arc<dyn ExecutionEngine>,
));
let visualizer_server = Arc::new(VisualizerServer::new(
    visualizer.clone(),
    state_store.clone() as Arc<dyn StateStore + Send + Sync>,
    VisualizerServerConfig { bind_addr: config.visualizer_bind_addr, pairs: config.pairs.clone() },
));
task_handles.push(spawn_supervised(alerts.clone(), "visualizer_server".into(), {
    let server = visualizer_server.clone();
    let shutdown = shutdown_rx.clone();
    async move { let _ = server.serve(shutdown).await; }
}));
// Superseded: `let _ = server.serve(shutdown).await;` silently swallowed
// a bind failure. Task 5's own review-fix round replaced it with a match
// on the Result that fires a Critical alert on Err; this final review
// round additionally threads an `Alerts` handle into `VisualizerServer`
// itself (see the design spec's Architecture section) rather than only
// alerting at this call site.

// New independent event_log persistence task (per pair, or one task
// fanning out over all configured pairs — implementation detail free
// to choose either, as long as it's a second subscriber, never a tap
// on the mq_gateway relay task).
task_handles.push(spawn_supervised(alerts.clone(), "event_log_writer".into(), {
    let engine = executor.clone();
    let state_store = state_store.clone();
    let shutdown = shutdown_rx.clone();
    async move { run_event_log_writer(engine, state_store, shutdown).await }
}));
```

### Integration test (RED, Docker) — full boot

Extends the existing L9 docker-compose boot test:

```rust
// Boot RunningSystem against a fake exchange sandbox. Assert:
// - GET /pairs on the configured visualizer_bind_addr responds once
//   boot reaches "ready".
// - A simulated PositionStateEvent (via the fake exchange triggering
//   an open/close) shows up both in mq_gateway's outbound relay AND
//   in state_store's event_log, proving the two subscribers really
//   are independent.
// - Killing/restarting visualizer_server mid-run has no effect on
//   order placement or the decision loop (per-task isolation, same
//   pattern as a per-pair task panic).
#[tokio::test]
async fn visualizer_serves_and_event_log_persists_without_affecting_execution() { ... }
```

### Unit tests (RED)

- Config: missing/invalid `VISUALIZER_BIND_ADDR` fails boot the same
  way any other missing required L9 config field does (fail fast,
  non-zero exit, clear log) — extends the existing bad-config test.
- `spawn_supervised` isolation: a forced panic inside
  `visualizer_server`'s task is caught and alerted, other tasks
  (including `event_log_writer`) keep running — same pattern already
  proven for per-pair tasks.

### Constraints / notes

- Construction order: visualizer pieces still built at step 9, after
  everything they read (L1/L3/L5) is already up — no change to the
  documented construction order itself, just what step 9 now
  constructs.
- Reuses `spawn_supervised`'s existing panic-isolation wrapper rather
  than introducing a new supervision mechanism.

## Acceptance criteria (rolled up from the design doc + this plan)

- [ ] `docker compose run --rm test` green, all new/changed crates
      included.
- [ ] `docker compose up run` boots, `GET /pairs` reachable, dashboard
      renders in a browser.
- [ ] Live mode: candles/position-overlay/order-book/event-log update
      in real time, zero calls into `ExecutionEngine`'s decision path.
- [ ] History mode: arbitrary past range replays correctly, including
      order-book depth via `BookTracker` and real outcome events via
      `event_log` — no WS involved.
- [ ] Forced `Lagged` on either broadcast resyncs via snapshot, never
      crashes the server or freezes the display.
- [ ] `event_log` and `mq_gateway`'s relay both receive every
      `PositionStateEvent`, independently, proven under concurrent
      load in the Layer 1 integration test.
- [ ] Killing/restarting `visualizer_server` or `event_log_writer` has
      no observable effect on order placement or the decision loop.
