# Executor refinement — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the confirmed gaps in the running `trade_executor` system —
wall persistence/visualization, a mock 10-minute buy/sell-volume-cross
signal that trades live, and live (not boot-only) position-state
persistence — while verifying the pieces that already work.

**Architecture:** Additive changes on top of the existing L1-L9 crates
(`market_data`, `local_analysis`, `execution`, `state_store`,
`visualizer_backend`, `visualizer_server`, `orchestrator`). No existing
public function signature changes. Stop-loss is a hard-coded placeholder
`const` inside `builder.rs`/`mock_signal.rs` (Task 4), never a
`DecisionContext`/`TradeDecision` field. The mock signal is a new
`SignalCheck` in `local_analysis`'s existing, previously-unwired
`SignalPipeline` (Task 5) — not a parallel bespoke mechanism.

**Tech Stack:** Rust workspace (`trade_executor/.worktrees/layer-implementation`),
PostgreSQL 17 (`sqlx`), Docker Compose, vanilla JS frontend
(`lightweight-charts`, `chart.js`).

**Spec:** [2026-09-15-executor-refinement-design.md](../specs/2026-09-15-executor-refinement-design.md)

## Global Constraints

- Work happens in the `layer-implementation` worktree
  (`trade_executor/.worktrees/layer-implementation`), branch
  `layer-implementation`. One commit per task, after its tests are green.
- Every task is gated: do not start task N+1 until task N's tests pass
  AND its stated DB-query/log/UI verification has actually been observed
  — not just "should work". This is a hard sequencing rule, not a
  suggestion (per this plan's own scope).
- Every new piece of persisted state gets a test that writes it and reads
  it back through the real code path (no mocked DB for `state_store`
  tests — this repo's existing `crates/state_store/tests/pg_store.rs`
  runs against real Postgres via `TEST_DATABASE_URL`, follow that
  pattern).
- New migrations are additive only (`migrations/000N_*.sql`, next free
  number after `0004`) — never edit a previously-applied migration file.
- `EXECUTION_MODE` stays `no_trade` for every verification step in this
  plan except the one explicit sub-step in Task 7 that is called out as
  requiring an operator's deliberate go-ahead. Never set
  `EXECUTION_MODE=live` as a side effect of running the test suite or a
  docker-compose smoke check.
- Match existing code conventions exactly: doc comments explaining *why*
  (not what), `rust_decimal::Decimal` for all prices/sizes, `Ts`/`Pair`/
  `Side` from `exchange_adapter`, synchronous-commit reasoning for any
  new `state_store` write (see `pg.rs`'s module doc for why L5 doesn't
  batch).

---

## Docker Entry Points

```bash
# Bring up Postgres and apply all migrations (existing + this plan's new ones)
docker compose up -d postgres
docker compose run --rm executor --migrate-only

# Full workspace test suite (existing + every test this plan adds)
docker compose run --rm test

# Run the executor (paper-safe default) and the dashboard
docker compose up -d executor visualizer
# dashboard: http://127.0.0.1:8090/pair.html?pair=BTCUSDT
```

Verified: [ ] `docker compose run --rm executor --migrate-only` succeeds
against a clean `trader_pgdata` volume, with this plan's migrations
applied (checked in Task 9).

---

## Task 1: Audit-verify the already-working pipeline (rows 1-5, 12)

No code expected to change. If any check below fails, stop and write a
regression test capturing the failure before touching anything else
(this plan's Tasks 2-8 assume this baseline holds).

**Files:** none (read/run only).

- [ ] **Step 1:** `docker compose up -d postgres executor visualizer` against
  a live-reachable exchange (default `EXCHANGE=binance`, `EXECUTION_MODE=
  no_trade`).
- [ ] **Step 2:** After ~2 minutes, run:
  ```sql
  SELECT pair, count(*) FROM book_snapshot GROUP BY pair;
  SELECT pair, count(*) FROM book_update GROUP BY pair;
  SELECT pair, count(*) FROM candle GROUP BY pair;
  ```
  Expected: non-zero, growing counts for the configured `PAIRS`.
- [ ] **Step 3:** `curl http://127.0.0.1:8090/api/history?pair=BTCUSDT` —
  expected: 200, non-empty `candles` array, non-empty order-book fields.
- [ ] **Step 4:** Open `http://127.0.0.1:8090/pair.html?pair=BTCUSDT` in a
  browser — expected: candlestick chart renders and updates, bid/ask
  tables and depth chart render and update.
- [ ] **Step 5:** `docker compose run --rm test` — expected: full existing
  workspace suite green (this is the pre-change baseline; record the pass
  count for comparison after Task 9).
- [ ] **Step 6:** Commit nothing (verification-only task) unless Step 2-5
  surfaced a regression, in which case follow
  `superpowers:systematic-debugging` before proceeding.

---

## Task 2: Wall observations — detection output + persisted table

**Files:**
- Modify: `crates/local_analysis/src/levels.rs`
- Modify: `crates/local_analysis/src/lib.rs` (re-export)
- Create: `migrations/0005_wall_snapshot.sql`
- Modify: `crates/state_store/src/dto.rs`, `crates/state_store/src/pg.rs`,
  `crates/state_store/src/lib.rs`
- Test: `crates/local_analysis/src/levels.rs` (inline `#[cfg(test)]`),
  `crates/state_store/tests/pg_store.rs`

**Interfaces:**
- Produces (for Task 3):
  ```rust
  // local_analysis
  pub struct WallObservation { pub pair: Pair, pub side: Side, pub price: Price, pub size: Decimal, pub ts: Ts }
  impl WallDetector {
      pub fn wall_observations(&self, book: &OrderBookSnapshot, pair: Pair, now: Ts) -> Vec<WallObservation>;
  }

  // state_store
  #[async_trait]
  pub trait WallSink: Send + Sync {
      async fn record_wall_observations(&self, obs: &[WallObservation]) -> Result<(), StoreError>;
  }
  impl WallSink for StateStoreImpl { /* ... */ }
  ```

- [ ] **Step 1: Write the failing test — detection**
  ```rust
  // crates/local_analysis/src/levels.rs, in the existing #[cfg(test)] mod
  #[test]
  fn wall_observations_reports_each_detected_wall_with_its_side_and_price() {
      let detector = WallDetector::new(dec!(95), dec!(0.1));
      let book = book_with_one_obvious_bid_wall(); // existing test helper pattern in this file
      let now = Ts(1_000);
      let obs = detector.wall_observations(&book, Pair::new("BTCUSDT"), now);
      assert_eq!(obs.len(), 1);
      assert_eq!(obs[0].side, Side::Buy);
      assert_eq!(obs[0].ts, now);
  }
  ```
- [ ] **Step 2: Run to verify it fails** — `cargo test -p local_analysis wall_observations_reports_each_detected_wall_with_its_side_and_price` — expected: FAIL, `wall_observations` not found.
- [ ] **Step 3: Implement** `WallObservation` + `wall_observations` in
  `levels.rs`, reusing the existing percentile/`max_spread_distance`
  detection already in `WallDetector` (do not change its math — only add
  a method that returns what it already computes as a `Vec` instead of
  feeding it straight into `combined_levels`).
- [ ] **Step 4: Run to verify it passes** — same command, expect PASS.
- [ ] **Step 5: Write the failing test — persistence round-trip**
  ```rust
  // crates/state_store/tests/pg_store.rs
  #[tokio::test]
  async fn wall_observations_round_trip() {
      let db = test_db().await; // test_support::test_db, existing pattern in this file
      let store = store(&db).await; // this file's existing `store(&TestDb) -> StateStoreImpl` helper
      let obs = vec![WallObservation { pair: Pair::new("BTCUSDT"), side: Side::Buy, price: dec!(50000), size: dec!(3.5), ts: Ts(1000) }];
      store.record_wall_observations(&obs).await.unwrap();
      let row: (String, i64) = sqlx::query_as("SELECT pair, ts FROM wall_snapshot WHERE pair = $1")
          .bind("BTCUSDT")
          .fetch_one(&db.pool())
          .await
          .unwrap();
      assert_eq!(row.0, "BTCUSDT");
      assert_eq!(row.1, 1000);
  }
  ```
- [ ] **Step 6: Run to verify it fails** — `cargo test -p state_store wall_observations_round_trip` (against `TEST_DATABASE_URL`) — expected: FAIL, no `wall_snapshot` table / no `record_wall_observations`.
- [ ] **Step 7: Write the migration**
  ```sql
  -- migrations/0005_wall_snapshot.sql
  CREATE TABLE wall_snapshot (
      pair        text      NOT NULL,
      ts          bigint    NOT NULL,
      side        side_enum NOT NULL,
      price       numeric   NOT NULL,
      size        numeric   NOT NULL,
      ins_seq     bigint    NOT NULL DEFAULT nextval('global_ins_seq'),
      PRIMARY KEY (pair, ts, side, price)
  );
  CREATE INDEX wall_snapshot_scan ON wall_snapshot (pair, ts, ins_seq);
  CREATE INDEX wall_snapshot_tail ON wall_snapshot (ins_seq);
  ```
- [ ] **Step 8: Implement** `WallSink`/`record_wall_observations` in
  `state_store` (synchronous commit — same reasoning as `persist`/
  `log_decision`, see `pg.rs`'s module doc), plus a `WallObservationDto`
  mirror in `dto.rs` matching the existing `LevelSourceDto` pattern.
- [ ] **Step 9: Run to verify it passes** — same command as Step 6, PASS.
- [ ] **Step 10: Run the full local_analysis + state_store suites** —
  `cargo test -p local_analysis -p state_store` — all green, including
  every pre-existing test (no regressions).
- [ ] **Step 11: Commit**
  ```bash
  git add crates/local_analysis crates/state_store migrations/0005_wall_snapshot.sql
  git commit -m "feat: wall observations + wall_snapshot persistence"
  ```

---

## Task 3: Wire walls into orchestrator + visualizer (read path + frontend)

**Files:**
- Modify: `crates/orchestrator/src/config.rs` (add `WALL_SNAPSHOT_INTERVAL_SECS`)
- Modify: `crates/orchestrator/src/system.rs` (spawn tick task)
- Modify: `crates/visualizer_backend/src/lib.rs`
- Modify: `crates/visualizer_server/src/dto.rs`, `crates/visualizer_server/src/routes.rs`
- Modify: `crates/visualizer_server/static/js/pair.js`
- Test: `crates/visualizer_backend` (inline), `crates/visualizer_server/tests/passive.rs`

**Interfaces:**
- Consumes: `state_store::WallSink`/`wall_snapshot` table (Task 2).
- Produces: `VisualizerBackend::wall_snapshots(&self, pair: Pair, from: Ts, to: Ts) -> Result<Vec<WallSnapshotDto>, VisualizerError>`; `PairHistoryDto.walls: Vec<WallSnapshotDto>`; `LiveMessage::Walls(WallSnapshotDto)`.

- [ ] **Step 1: Write the failing test — backend read**
  ```rust
  // crates/visualizer_backend/src/lib.rs test module
  #[tokio::test]
  async fn wall_snapshots_returns_rows_in_the_requested_window() {
      let backend = test_backend_with_seeded_walls().await; // seed via state_store in test setup, matching existing candle-read test's pattern
      let rows = backend.wall_snapshots(Pair::new("BTCUSDT"), Ts(0), Ts(u64::MAX)).await.unwrap();
      assert!(!rows.is_empty());
  }
  ```
- [ ] **Step 2: Run to verify it fails** — `cargo test -p visualizer_backend wall_snapshots_returns_rows_in_the_requested_window` — FAIL.
- [ ] **Step 3: Implement** `wall_snapshots` (mirrors the existing candle/
  trade read methods' `catch_unwind` + `VisualizerError` pattern already
  documented in `lib.rs`).
- [ ] **Step 4: Run to verify it passes** — PASS.
- [ ] **Step 5: Write the failing test — HTTP surface**
  ```rust
  // crates/visualizer_server/tests/passive.rs
  #[tokio::test]
  async fn history_response_includes_walls() {
      let app = test_app_with_seeded_walls().await;
      let resp = app.get("/api/history?pair=BTCUSDT").await;
      let body: serde_json::Value = resp.json();
      assert!(body["walls"].as_array().is_some_and(|w| !w.is_empty()));
  }
  ```
- [ ] **Step 6: Run to verify it fails** — FAIL (`walls` key absent).
- [ ] **Step 7: Implement** `PairHistoryDto.walls`, wire it in the
  `/api/history` handler, add `LiveMessage::Walls` to the `/ws` enum and
  its poll-task arm (mirror the existing candle/trade poll-and-push
  pattern in `routes.rs`).
- [ ] **Step 8: Run to verify it passes** — PASS.
- [ ] **Step 9: Wire the frontend** — in `pair.js`, after
  `setChartHistory(chartState, data.candles)`, add
  `setWallSnapshots(chartState, data.walls)`; in the `onLiveMessage`
  switch (alongside the existing `case "Candle":`), add
  `case "Walls": appendWallSnapshot(chartState, msg); setDepthChartWalls(depthState, wallLinesFromSnapshot(msg)); break;`.
  No new rendering code — `chart.js` already defines every function
  called here.
- [ ] **Step 10: Verify with `node --check`** — `node --check
  crates/visualizer_server/static/js/pair.js` — no syntax errors.
- [ ] **Step 11: Implement the orchestrator task — event-driven
  detection, interval-throttled persistence.** Detection runs on every
  order-book update, not on a timer: per pair,
  `market_data.subscribe_updates(pair)`, filter to
  `MarketDataEvent::BookSnapshot`/`BookUpdate` (same event stream and
  filter shape as `run_stop_loss_watcher`'s `trade_price` filter, mirrored
  for book events instead of trades), and on each one call
  `WallDetector::wall_observations` against `market_data.order_book(pair)`
  (the freshly-updated book). `WALL_SNAPSHOT_INTERVAL_SECS` (config,
  default `10`) gates the DB write only: keep the last computed
  `Vec<WallObservation>` in the task's own state, and call
  `state_store.record_wall_observations` at most once per interval (e.g.
  track `last_written: Instant`, write only when
  `last_written.elapsed() >= interval`, always writing the *latest*
  observations at that point — never a stale set from earlier in the
  interval). This keeps the write path exactly as cheap as the old timer
  design while making detection itself track the book in real time
  instead of sampling it. Same `spawn_supervised` pattern as the existing
  stop-loss-watcher/advisor-loop tasks in `system.rs`.
- [ ] **Step 12: Run full suite** — `cargo test -p local_analysis -p state_store -p visualizer_backend -p visualizer_server -p orchestrator` — all green.
- [ ] **Step 13: Docker/UI verification** — `docker compose up -d --build
  postgres executor visualizer`; after one interval, `SELECT count(*) FROM
  wall_snapshot;` is non-zero; open `pair.html?pair=BTCUSDT` — dots appear
  on the candlestick chart and lines on the depth chart, matching
  `WALL_STYLE`'s legend.
- [ ] **Step 14: Commit**
  ```bash
  git add crates/orchestrator crates/visualizer_backend crates/visualizer_server
  git commit -m "feat: wire wall observations into the visualizer read + live paths"
  ```

---

## Task 4: Hard-coded percent-based stop-loss (analyzer + decision maker)

Not a function parameter and not a `DecisionContext`/`TradeDecision`
field — a local `const` in each of the two files that touch a stop-loss
value, each carrying a comment marking it a placeholder. No plumbing
between the two files; each owns its own copy.

**Files:**
- Create: `crates/local_analysis/src/mock_signal.rs` (const only — the
  rest of this file is Task 5; if Task 5 hasn't landed yet when this task
  runs, add the file with just the const + comment, doc-only until Task 5
  fills it in)
- Modify: `crates/local_analysis/src/builder.rs`
- Test: `crates/local_analysis/src/builder.rs` (inline)

**Interfaces:**
- No new public signature. `DefaultSignalBuilder::build_signal`'s return
  shape (`SignalAction::Open { stop_loss_price, .. }`) is unchanged —
  only how that price is computed changes.

- [ ] **Step 1: Write the failing tests**
  ```rust
  // crates/local_analysis/src/builder.rs test module
  #[test]
  fn stop_loss_is_one_percent_below_entry_for_a_long() {
      let ctx = open_ctx(Side::Buy); // this file's existing Open-decision fixture
      let action = DefaultSignalBuilder { max_wait: Duration::from_secs(60) }
          .build_signal(&ctx, &[], dec!(100), Ts(0));
      match action {
          SignalAction::Open { stop_loss_price, .. } => assert_eq!(stop_loss_price, dec!(99)),
          other => panic!("expected Open, got {other:?}"),
      }
  }

  #[test]
  fn stop_loss_is_one_percent_above_entry_for_a_short() {
      let ctx = open_ctx(Side::Sell);
      let action = DefaultSignalBuilder { max_wait: Duration::from_secs(60) }
          .build_signal(&ctx, &[], dec!(100), Ts(0));
      match action {
          SignalAction::Open { stop_loss_price, .. } => assert_eq!(stop_loss_price, dec!(101)),
          other => panic!("expected Open, got {other:?}"),
      }
  }

  #[test]
  fn close_price_still_comes_from_the_nearest_level() {
      // Reuses this file's existing level-based Open test fixture,
      // asserting close_price is unchanged by this task -- only
      // stop_loss_price's source changed.
  }
  ```
- [ ] **Step 2: Run to verify failure** — `cargo test -p local_analysis stop_loss_is_one_percent` — FAIL (still level-based, `assert_eq!` mismatch).
- [ ] **Step 3: Implement** — in `builder.rs`:
  ```rust
  // TEMPORARY: fixed 1% stop-loss, unconditional for every Open decision.
  // Replace with real stop-loss selection in the strategy-preparation plan
  // -- this exists only so the mock signal has a working stop, not as a
  // considered risk rule.
  const PLACEHOLDER_STOP_LOSS_PCT: Decimal = dec!(0.01);
  ```
  and in the `DecisionKind::Open` arm, replace the
  `nearest_in_direction(combined_levels, open_price, !is_long)` call used
  for `stop_loss_price` with:
  ```rust
  let stop_loss_price = if is_long {
      open_price * (Decimal::ONE - PLACEHOLDER_STOP_LOSS_PCT)
  } else {
      open_price * (Decimal::ONE + PLACEHOLDER_STOP_LOSS_PCT)
  };
  ```
  `close_price` keeps calling `nearest_in_direction` exactly as before —
  only the stop-loss line changes. `nearest_in_direction`'s call for
  `stop_loss_price` is removed; if that leaves the function only used for
  `close_price` now, that's fine, no signature change needed.
  In `mock_signal.rs`, add the matching const + identical comment (used
  by Task 5's logic once it lands):
  ```rust
  // TEMPORARY: fixed 1% stop-loss, mirrors builder.rs's
  // PLACEHOLDER_STOP_LOSS_PCT. Replace with real stop-loss selection in
  // the strategy-preparation plan.
  const PLACEHOLDER_STOP_LOSS_PCT: Decimal = dec!(0.01);
  ```
- [ ] **Step 4: Run to verify it passes** — PASS, all three new tests plus
  every pre-existing `local_analysis` test still green (the old
  level-based-stop-loss test, if one existed asserting a specific
  level-derived stop price, is expected to now fail and must be updated
  to assert the 1% value instead — that is this task's intended
  behavior change, not a regression to chase).
- [ ] **Step 5: Commit**
  ```bash
  git add crates/local_analysis
  git commit -m "feat: hard-code placeholder 1% stop-loss in analyzer + decision maker"
  ```

---

## Task 5: Mock volume-cross check, as a `SignalCheck` in the existing unified signal pipeline

`local_analysis` already has a generic signal mechanism —
`SignalCheck`/`SignalConfig`/`SignalFactory`/`SignalPipeline`, firing
`SignalEvent`s (`crates/local_analysis/src/signals.rs`, `lib.rs`) — built
and unit-tested, but never wired to anything outside `local_analysis`
(`grep` for `SignalPipeline`/`subscribe_signals` outside that crate
returns nothing). This task adds a **mock** check to that *same*
pipeline rather than building a parallel one. See "Event vs Signal"
below for the naming rule this follows.

**Files:**
- Create: `crates/local_analysis/src/mock_signal.rs`
- Modify: `crates/local_analysis/src/types.rs` (`SignalConfig`, `SignalEvent` new variants)
- Modify: `crates/local_analysis/src/signals.rs` (`SignalFactory::create` new arm)
- Modify: `crates/local_analysis/src/lib.rs` (module + re-export)
- Test: inline `#[cfg(test)]` in `mock_signal.rs`

**Interfaces:**
- Modifies existing enums (additive variants only):
  ```rust
  // types.rs
  pub enum SignalConfig {
      ExtremeVolumeReversal { threshold: Decimal },
      VolumeProjectedMove { avg_window: Duration, horizon: Duration },
      MockVolumeCross { window: Duration }, // new
  }

  pub enum SignalEvent {
      ExtremeVolumeReversal { /* unchanged */ },
      VolumeProjectedMove { /* unchanged */ },
      // new — `Mock` prefix marks these as test/demo-only signals living
      // in the same enum as real ones, never a separate type:
      MockBuyCrossedAboveSell { pair: Pair, ts: Ts, buy_ma: Decimal, sell_ma: Decimal },
      MockSellCrossedAboveBuy { pair: Pair, ts: Ts, buy_ma: Decimal, sell_ma: Decimal },
  }
  ```
- Produces (for Task 7): `SignalFactory.create(SignalConfig::MockVolumeCross { window })` returns a `Box<dyn SignalCheck>` (`MockVolumeCrossCheck`) usable in a `SignalPipeline` exactly like `ExtremeVolumeReversalCheck`.

**Event vs Signal — the naming rule this plan follows:**
An **event** is a raw occurrence some subsystem reports — a trade tick,
an order-book update, a wall observation, an account fill. Plain fact,
no implied action. A **signal** is specifically the *output of L2's
analysis over events* — the thing a decision-maker acts on (open/close/
buy/sell). This codebase already names that output type `SignalEvent`
(a little awkwardly, since the word "event" is in it) — this plan does
**not** rename it; that's out of scope and would touch every existing
`SignalCheck` impl and test for no functional gain. The one entity this
task adds lives as new variants *of that same existing type*, not a new
`VolumeCrossEvent`/`Signal` type. "Mock" describes provenance (a
synthetic/demo check, not main/'s or a validated production one), not a
different category of thing — a `MockBuyCrossedAboveSell` is exactly as
much a `SignalEvent` as `ExtremeVolumeReversal` is, and flows through the
identical `SignalCheck`/`SignalPipeline`/persistence path.

- [ ] **Step 1: Write the failing tests**
  ```rust
  // crates/local_analysis/src/mock_signal.rs
  use crate::signals::MarketDataWindow;
  use crate::types::{Pair, Side, SignalEvent, Ts};

  fn trade(side: Side, qty: i64, ts: u64) -> market_data::TradeTick { /* same helper shape as signals.rs's own test module */ }
  fn window(trades: Vec<market_data::TradeTick>, now: u64) -> MarketDataWindow { /* same as signals.rs's own test module */ }

  #[test]
  fn fires_mock_buy_crossed_above_sell_when_dominance_flips() {
      let check = MockVolumeCrossCheck::new(Duration::from_secs(600));
      // Sell-dominant window: no fire (first observation never fires -- nothing to cross from).
      let sell_heavy = window(vec![trade(Side::Sell, 100, 1_000)], 1_000);
      assert_eq!(check.check(&sell_heavy), None);
      // Buy-dominant window at a later `now`: dominance flipped Sell -> Buy, fires.
      let buy_heavy = window(vec![trade(Side::Buy, 100, 2_000)], 2_000);
      let event = check.check(&buy_heavy).expect("dominance flip should fire");
      assert!(matches!(event, SignalEvent::MockBuyCrossedAboveSell { .. }));
      // Same dominance again (still buy-heavy): must NOT re-fire.
      let still_buy_heavy = window(vec![trade(Side::Buy, 50, 3_000)], 3_000);
      assert_eq!(check.check(&still_buy_heavy), None);
  }

  #[test]
  fn fires_mock_sell_crossed_above_buy_on_the_opposite_flip() {
      let check = MockVolumeCrossCheck::new(Duration::from_secs(600));
      check.check(&window(vec![trade(Side::Buy, 100, 1_000)], 1_000));
      let event = check.check(&window(vec![trade(Side::Sell, 100, 2_000)], 2_000)).expect("flip should fire");
      assert!(matches!(event, SignalEvent::MockSellCrossedAboveBuy { .. }));
  }

  #[test]
  fn ignores_trades_outside_the_trailing_window() {
      // A window's `recent_trades` can carry more history than the check's
      // own `window` duration cares about (the pipeline's `window_capacity`
      // is a count bound, not a time bound) -- assert trades older than
      // `now - window` are excluded from buy_ma/sell_ma, mirroring
      // VolumeProjectedMoveCheck's own `cutoff` pattern in signals.rs.
      let check = MockVolumeCrossCheck::new(Duration::from_secs(600));
      let trades = vec![
          trade(Side::Buy, 1000, 0),       // 600s+ before `now` below -- must be excluded
          trade(Side::Sell, 1, 601_000),
      ];
      assert_eq!(check.check(&window(trades, 601_000)), None); // sell(1) > buy(0) in-window, but no prior dominance to flip from
  }
  ```
- [ ] **Step 2: Run to verify failure** — `cargo test -p local_analysis mock_signal` — FAIL, module/type doesn't exist.
- [ ] **Step 3: Implement.** `MockVolumeCrossCheck` holds `window:
  Duration` plus `last_dominant: Mutex<Option<Side>>` (interior
  mutability — `SignalCheck::check` takes `&self`, matching every other
  check in this file; a `Mutex` is the minimal way to remember "which
  side was dominant last call" without changing the trait). On each
  `check`: filter `window.recent_trades` to `ts >= window.now - self.window`
  (same `cutoff` pattern as `VolumeProjectedMoveCheck`), sum `buy_qty`/
  `sell_qty`, `buy_ma = buy_qty / window_secs`, `sell_ma = sell_qty /
  window_secs`. Dominant side = whichever `_ma` is strictly greater
  (equal → no dominance, `None`). Compare against `last_dominant`: fire
  only when it's `Some` and different from the newly computed dominant
  side (a `None -> Some` first observation never fires — nothing to cross
  from, matches `evicts_volume_older_than_the_window`'s spirit from the
  earlier draft without needing an internal ring buffer, since the
  pipeline's own `recent_trades` window already carries the history).
  Always update `last_dominant` to the newly computed value, fired or
  not.
- [ ] **Step 4: Implement the factory arm** in `signals.rs`:
  ```rust
  SignalConfig::MockVolumeCross { window } => Box::new(mock_signal::MockVolumeCrossCheck::new(window)),
  ```
- [ ] **Step 5: Run to verify it passes** — PASS.
- [ ] **Step 6: Run full local_analysis suite** — `cargo test -p local_analysis` — all green, no regressions (existing `SignalEvent`/`SignalConfig` match arms elsewhere in the crate need the two new variants added — the compiler's exhaustiveness check will point at every one).
- [ ] **Step 7: Commit**
  ```bash
  git add crates/local_analysis
  git commit -m "feat: mock buy/sell volume-cross check in the unified signal pipeline"
  ```

---

## Task 6: Persist fired signals (generic `signal_log`, any `SignalEvent`)

**Files:**
- Create: `migrations/0006_signal_log.sql`
- Modify: `crates/state_store/src/dto.rs` (new `SignalEventDto` mirror, same convention as `WallObservationDto`), `crates/state_store/src/pg.rs`, `crates/state_store/src/lib.rs`
- Test: `crates/state_store/tests/pg_store.rs`

**Interfaces:**
- Produces (for Task 7):
  ```rust
  #[async_trait]
  pub trait SignalSink: Send + Sync {
      /// `decision_id` is `None` when this fired signal didn't produce a
      /// `TradeDecision` (e.g. a real/non-mock signal today -- nothing
      /// consumes those into a decision yet, only Mock variants do, per
      /// Task 7). Whoever turns a signal into a decision passes `Some`.
      async fn record_signal(&self, pair: Pair, event: &local_analysis::SignalEvent, decision_id: Option<&str>) -> Result<(), StoreError>;
  }
  impl SignalSink for StateStoreImpl { /* ... */ }
  ```

- [ ] **Step 1: Write the failing test**
  ```rust
  #[tokio::test]
  async fn signal_round_trip_with_decision_id() {
      let db = test_db().await;
      let store = store(&db).await;
      let event = SignalEvent::MockBuyCrossedAboveSell {
          pair: Pair::new("BTCUSDT"), ts: Ts(1000), buy_ma: dec!(5), sell_ma: dec!(2),
      };
      store.record_signal(Pair::new("BTCUSDT"), &event, Some("decision-abc")).await.unwrap();
      let (signal_id, decision_id, record): (String, Option<String>, serde_json::Value) =
          sqlx::query_as("SELECT signal_id, decision_id, record FROM signal_log WHERE decision_id = $1")
              .bind("decision-abc")
              .fetch_one(&db.pool())
              .await
              .unwrap();
      assert_eq!(signal_id, "mock_volume_cross");
      assert_eq!(decision_id.as_deref(), Some("decision-abc"));
      assert_eq!(record["buy_ma"], "5"); // exact shape depends on SignalEventDto's serde derive -- assert whatever it actually serializes to, not a guessed shape
  }

  #[tokio::test]
  async fn signal_without_a_decision_persists_with_null_decision_id() {
      let db = test_db().await;
      let store = store(&db).await;
      let event = SignalEvent::ExtremeVolumeReversal {
          pair: Pair::new("BTCUSDT"), direction: Side::Buy, magnitude: dec!(10), ts: Ts(1000),
      };
      store.record_signal(Pair::new("BTCUSDT"), &event, None).await.unwrap();
      let decision_id: Option<String> = sqlx::query_scalar("SELECT decision_id FROM signal_log WHERE signal_id = 'extreme_volume_reversal'")
          .fetch_one(&db.pool())
          .await
          .unwrap();
      assert_eq!(decision_id, None);
  }
  ```
- [ ] **Step 2: Run to verify failure** — FAIL, no table/method/DTO.
- [ ] **Step 3: Write the migration**
  ```sql
  -- migrations/0006_signal_log.sql
  CREATE TABLE signal_log (
      seq          bigint PRIMARY KEY DEFAULT nextval('global_ins_seq'),
      pair         text   NOT NULL,
      signal_id    text   NOT NULL,  -- SignalId, e.g. "mock_volume_cross", "extreme_volume_reversal"
      record       jsonb  NOT NULL,  -- serialized SignalEvent (SignalEventDto) -- variant-specific fields (buy_ma/sell_ma, magnitude, projected_move, ...) live here, not as columns
      decision_id  text,             -- NULL when this signal didn't produce a decision
      ts           bigint NOT NULL
  );
  CREATE INDEX signal_log_pair_ts ON signal_log (pair, ts);
  CREATE INDEX signal_log_decision ON signal_log (decision_id) WHERE decision_id IS NOT NULL;
  ```
- [ ] **Step 4: Implement.** `SignalEventDto` in `dto.rs`: a `#[derive(Serialize, Deserialize)]` mirror of `local_analysis::SignalEvent` (same reasoning as every other DTO in this file — the domain enum doesn't derive serde, per `dto.rs`'s own module doc), with `From<&SignalEvent> for SignalEventDto`. `record_signal` serializes the DTO into the `record` jsonb column via `serde_json::to_value`, pulls `signal_id` from `event`'s existing `SignalId` (each `SignalEvent` variant's originating `SignalCheck::id()` — thread it in as a parameter since a bare `SignalEvent` doesn't carry its own `SignalId` today; `record_signal(&self, pair, signal_id: SignalId, event: &SignalEvent, decision_id: Option<&str>)` — **note:** this changes the trait signature from the stub above; use this corrected one). Synchronous commit — same reasoning as `log_decision`: proving a signal fired must survive a crash the instant it happens, not be batched.
- [ ] **Step 5: Run to verify it passes** — PASS.
- [ ] **Step 6: Run full state_store suite** — `cargo test -p state_store` — all green.
- [ ] **Step 7: Commit**
  ```bash
  git add crates/state_store migrations/0006_signal_log.sql
  git commit -m "feat: persist fired signals (any SignalEvent) to signal_log"
  ```

---

## Task 7: Wire the mock signal into a live decision source

**decision_id — who produces it, how it persists:** the orchestrator task
below (the "decision maker" for this path) generates one fresh
`uuid::Uuid::new_v4()` string at the moment a `Mock*` `SignalEvent`
fires — nowhere else invents one, and nothing upstream (the check, the
pipeline) carries or needs one, since most `SignalEvent`s never become a
decision at all (Task 6's `None` case). That id is then written to
*two* places, both already designed for exactly this in the existing
schema:
1. `signal_log.decision_id` (Task 6) — links the persisted signal to the
   decision it produced.
2. `decision_log` via `state_store.log_decision(TradeDecision)` — this
   existing L5 method (`crates/state_store/src/pg.rs`) has **zero**
   production call sites today (`grep -rn "log_decision" crates/*/src`
   only matches the trait/impl definitions and a CLI test fake) — this
   task is its first real caller. Persisting through it, rather than
   inventing a second decision-audit path, keeps `decision_log` the one
   place every decision fed to execution shows up, regardless of source
   (main/'s, eventually, or this mock path today).

Add `uuid = { version = "1", features = ["v4"] }` to
`crates/orchestrator/Cargo.toml` (already a workspace dependency of
`test_support`, per `crates/test_support/Cargo.toml` — same version).

**Files:**
- Modify: `crates/orchestrator/Cargo.toml` (add `uuid`)
- Modify: `crates/orchestrator/src/config.rs` (no new knobs — reuses existing `PAIRS`/`EXECUTION_MODE`)
- Modify: `crates/orchestrator/src/system.rs` (construct a `SignalPipeline`, spawn per-pair consumer task)
- Test: `crates/orchestrator/src/tests.rs`

**Interfaces:**
- Consumes: `local_analysis::{SignalPipeline, SimpleSignalFeed,
  SignalConfig, SignalFactory, SignalEvent}` (existing pipeline + Task
  5's new variants), `state_store::{SignalSink, StateStore::log_decision}`
  (Task 6 + existing), `execution::ExecutionEngine::handle_decision`
  (existing). Stop-loss is Task 4's hard-coded `PLACEHOLDER_STOP_LOSS_PCT`
  inside `builder.rs` — this task passes nothing stop-loss related
  through `TradeDecision`.
- `SignalPipeline::new(feed, checks, window_capacity)`'s `window_capacity`
  must be sized generously enough that `recent_trades` actually covers
  the mock check's 10-minute window on an active pair — it's a count
  bound, not a time bound (see `MarketDataWindow`'s doc comment in
  `signals.rs`). Config: reuse `VOLUME_AVG_WINDOW_SECS`'s neighbor
  pattern — add nothing new here beyond a documented constant
  (`SIGNAL_PIPELINE_WINDOW_CAPACITY`, e.g. `20_000`) unless a config knob
  is later found necessary.

- [ ] **Step 1: Write the failing test**
  ```rust
  // crates/orchestrator/src/tests.rs
  #[tokio::test]
  async fn mock_signal_crossing_reaches_execution_and_is_logged() {
      let (executor_spy, state_store_spy, feed) = fake_system_for_signal_pipeline(); // new test fixture: a fake MarketDataFeed whose subscribe_updates can be scripted, same shape as this file's existing fake-adapter fixtures
      let checks: Vec<Box<dyn SignalCheck>> = vec![SignalFactory.create(SignalConfig::MockVolumeCross { window: Duration::from_secs(600) })];
      let pipeline = SignalPipeline::new(feed.clone(), checks, 20_000);
      spawn_signal_decision_loop(executor_spy.clone(), state_store_spy.clone(), pipeline, Pair::new("BTCUSDT"));
      // Drive a scripted sell-heavy-then-buy-heavy trade sequence that crosses.
      for tick in scripted_crossing_sequence() {
          feed.ingest_for_test(tick); // fixture helper pushing into subscribe_updates' stream
      }
      tokio::time::sleep(Duration::from_millis(50)).await; // let the task drain the channel
      assert_eq!(executor_spy.handle_decision_calls(), 1);
      assert_eq!(state_store_spy.signal_log_rows_with_decision(), 1);
      assert_eq!(state_store_spy.decision_log_rows(), 1); // log_decision's first real caller
  }
  ```
- [ ] **Step 2: Run to verify failure** — FAIL, `spawn_signal_decision_loop` doesn't exist.
- [ ] **Step 3: Implement** the per-pair task: `pipeline.subscribe_signals(pair)`
  (the existing `SimpleSignalFeed` trait method — no new subscription
  mechanism); for each yielded `SignalEvent`, match:
  - `SignalEvent::MockBuyCrossedAboveSell { .. } | SignalEvent::MockSellCrossedAboveBuy { .. }`:
    1. Generate `let decision_id = uuid::Uuid::new_v4().to_string();`.
    2. `state_store.record_signal(pair.clone(), SignalId("mock_volume_cross"), &event, Some(&decision_id)).await`.
    3. Build `let decision = TradeDecision { id: DecisionId(decision_id), pair: pair.clone(), kind: DecisionKind::Open, side: <Buy for MockBuyCrossedAboveSell, Sell for MockSellCrossedAboveBuy>, timeframe: None, main_levels: vec![] };` — stop-loss applied downstream by `DefaultSignalBuilder`'s hard-coded `PLACEHOLDER_STOP_LOSS_PCT` (Task 4), nothing to set here.
    4. `state_store.log_decision(decision.clone()).await` (first real caller, per the note above).
    5. `executor.handle_decision(decision).await`.
  - any other `SignalEvent` (real checks, if registered): `state_store.record_signal(pair.clone(), event.originating_signal_id(), &event, None).await` — logged, no decision. Forward-compat for when real checks get wired to actually decide something; out of scope here.

  Log a structured line on every crossing (`observability::Metrics`/log,
  matching this crate's existing convention) before/after step 5, so
  Task 9's log-based verification has something concrete to grep for.
- [ ] **Step 4: Run to verify it passes** — PASS.
- [ ] **Step 5: Wire into `system.rs`** — construct the `SignalPipeline`
  with `SignalConfig::MockVolumeCross { window: Duration::from_secs(600) }`
  as its only registered check for now, one `spawn_supervised` task per
  pair, same shutdown-aware pattern as `run_stop_loss_watcher`/
  `run_advisor_loop`.
- [ ] **Step 6: Run full orchestrator suite** — `cargo test -p orchestrator` — all green.
- [ ] **Step 7: Docker verification (`EXECUTION_MODE=no_trade`, required)** —
  `docker compose up -d --build postgres executor`; tail logs for the
  crossing log line from Step 3; confirm
  `SELECT count(*) FROM signal_log WHERE decision_id IS NOT NULL;` and
  `SELECT count(*) FROM decision_log;` both increase whenever it appears;
  confirm `NoTradeAccount` is refusing placement (no unexpected
  `order_event` rows) — this proves propagation reaches execution without
  risking capital.
- [ ] **Step 8: Live verification (opt-in, operator-authorized only)** —
  only after Step 7 is clean and the user explicitly authorizes it: set
  `EXECUTION_MODE=live` against a funded or exchange-testnet account,
  restart the `executor` service, and on the next observed crossing
  confirm `SELECT * FROM order_event ORDER BY seq DESC LIMIT 1;` shows a
  real order. Revert to `EXECUTION_MODE=no_trade` afterward unless the
  user asks to keep it live.
- [ ] **Step 9: Commit**
  ```bash
  git add crates/orchestrator
  git commit -m "feat: mock volume-cross signal drives execution live via the unified signal pipeline"
  ```

---

## Task 8: Live position-state persistence

**Files:**
- Modify: `crates/orchestrator/src/system.rs` (spawn `run_position_sync`)
- Test: `crates/orchestrator/src/tests.rs`

**Interfaces:**
- Consumes: `execution::PositionStateEventStream` (existing
  `subscribe_state_changes`), `market_data::AccountEventStream` (existing
  `subscribe_account_events`), `state_store::StateStore::persist` (existing).

- [ ] **Step 1: Write the failing test — state-change trigger**
  ```rust
  #[tokio::test]
  async fn position_state_events_persist_immediately() {
      let (executor_spy, state_store_spy) = fake_system_for_position_sync();
      spawn_position_sync(executor_spy.clone(), state_store_spy.clone(), /* account events */ empty_account_stream());
      executor_spy.emit_state_event(opened_event("BTCUSDT")); // test helper on the fake
      executor_spy.emit_state_event(closed_event("BTCUSDT"));
      tokio::time::sleep(Duration::from_millis(50)).await;
      assert_eq!(state_store_spy.persist_calls_for("BTCUSDT"), 2);
  }
  ```
- [ ] **Step 2: Run to verify failure** — FAIL, `spawn_position_sync` doesn't exist.
- [ ] **Step 3: Write the failing test — account-event trigger**
  ```rust
  #[tokio::test]
  async fn account_order_events_for_an_open_position_also_persist() {
      let (executor_spy, state_store_spy) = fake_system_for_position_sync();
      executor_spy.seed_open_position("BTCUSDT");
      let account_tx = spawn_position_sync_with_account_stream(executor_spy.clone(), state_store_spy.clone());
      account_tx.send(order_fill_event("BTCUSDT")).unwrap();
      tokio::time::sleep(Duration::from_millis(50)).await;
      assert_eq!(state_store_spy.persist_calls_for("BTCUSDT"), 1);
  }
  ```
- [ ] **Step 4: Run to verify it fails** — FAIL.
- [ ] **Step 5: Implement** `run_position_sync`: `tokio::select!` loop
  over both streams (same wait-point-only shutdown race as
  `run_stop_loss_watcher`); on either event, resolve the affected pair
  and call `state_store.persist(executor.position_state(pair)).await`,
  alerting (not panicking) on a persist error — mirrors the
  `AlertKind::OrderPlacementFailed` pattern already used for the resting
  stop-loss failure case in `engine.rs`.
- [ ] **Step 6: Run to verify both tests pass** — PASS.
- [ ] **Step 7: Wire into `system.rs`** — one `spawn_supervised` task,
  after Step 6/7 (mq_gateway + per-pair loops) in the existing
  construction order.
- [ ] **Step 8: Run full orchestrator suite** — `cargo test -p orchestrator` — all green.
- [ ] **Step 9: Docker/DB verification** — with Task 7's mock signal
  running under `EXECUTION_MODE=no_trade`, watch
  ```sql
  SELECT pair, updated_at FROM position_state WHERE pair = 'BTCUSDT';
  ```
  `updated_at` must advance within a couple seconds of each `Opened`/
  `Closed`/`NotPlaced` log line from Task 7 — not only after a container
  restart.
- [ ] **Step 10: Commit**
  ```bash
  git add crates/orchestrator
  git commit -m "feat: persist position state live, not only at boot"
  ```

---

## Task 9: End-to-end acceptance (executor + visualizer, one command each)

No new code expected. This is the plan's acceptance gate.

**Files:** none, unless a check below fails — in that case, write a
regression test first (per `superpowers:systematic-debugging`), then fix.

- [ ] **Step 1:**
  ```bash
  docker compose up -d postgres
  docker compose run --rm executor --migrate-only
  docker compose up -d --build executor visualizer
  ```
- [ ] **Step 2:** `docker compose run --rm test` — full workspace suite
  green, count of passing tests strictly greater than Task 1's recorded
  baseline (every task above added at least one).
- [ ] **Step 3:** DB checks —
  ```sql
  SELECT count(*) FROM book_snapshot;   -- growing (Task 1)
  SELECT count(*) FROM candle;          -- growing (Task 1)
  SELECT count(*) FROM wall_snapshot;   -- growing (Task 2-3)
  SELECT count(*) FROM signal_log WHERE decision_id IS NOT NULL; -- grows on a real cross (Task 5-7)
  SELECT count(*) FROM decision_log; -- grows alongside it (log_decision's first real caller, Task 7)
  SELECT pair, updated_at FROM position_state; -- updated_at advances live (Task 8)
  ```
- [ ] **Step 4:** UI check — `http://127.0.0.1:8090/pair.html?pair=BTCUSDT`
  shows live-updating candles, order book, depth chart, and (once a
  snapshot interval has elapsed) wall dots/lines with a legend.
- [ ] **Step 5:** Log check — orchestrator logs contain at least one mock
  signal crossing log line (Task 7's Step 3 logging) and, if it fired, a
  matching `Opened`/`NotPlaced` `PositionStateEvent` log line immediately
  followed (within the sync interval) by an `updated_at` bump in Step 3's
  last query.
- [ ] **Step 6:** No commit for this task unless a fix was needed, in
  which case commit the regression test + fix together.
