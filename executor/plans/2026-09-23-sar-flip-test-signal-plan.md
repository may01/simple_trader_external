# SAR-Flip Test Signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan layer-by-layer. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an indicator `main/` computes drive a real order and a real position in the executor: `main/` publishes parabolic SAR at tf 1, the executor reads it through its existing indicator read path, a `SarFlipCheck` fires when SAR crosses price, and the flip closes any opposite position and opens the reverse with nominal exits.

**Spec:** [`external/executor/specs/2026-09-22-sar-flip-test-signal-design.md`](../specs/2026-09-22-sar-flip-test-signal-design.md). Section refs (§) and decision refs (D) below point into it; read it alongside this plan.

**Architecture:** All signal code moves into a new crate `signals`, nested at `crates/local_analysis/signals`, depending on nothing from `local_analysis` and vice versa. Indicators reach checks through a new `IndicatorSource` trait whose only real implementation is a thin orchestrator adapter over the **existing** `StateStoreImpl::current_indicator` — the read path that already owns a write-through, expiry-aware `(pair, name)` cache, always warm here because the executor is the process that ingests the readings. No new cache, no new query, no schema change. `SignalCheck::check` stays synchronous; `SignalPipeline` prefetches each check's `required_indicators()` into the window before dispatching.

**Tech stack:** Rust workspace (`tokio`, `async-trait`, `rust_decimal`, `sqlx`/Postgres), Docker Compose. Executor workspace: `trade_executor/.worktrees/layer-implementation`. Python side: `main/` (one YAML entry + one test).

**Note on layer taxonomy:** `layer-first-planning`'s layer table describes the Python trading pipeline, not the executor; like [2026-09-22-live-trade-ops-plan.md](2026-09-22-live-trade-ops-plan.md), this plan applies that skill's *principles* (Docker first, interface before code, RED test at each boundary, no layer started before the previous is green in Docker) over `trade_executor`'s real layers.

---

## Prerequisite — blocked until `live-trade-ops` is merged

**No task in this plan starts until `live-trade-ops` has been merged into `layer-implementation`** (user decision, 2026-09-24). That work is in flight in the same worktree, touches L0 and migration 0008, and ends with human-gated live runs; branching this off `layer-implementation` before it lands would either fork an outdated base or fight the worktree for a checkout.

Check the gate before Layer 1:

```bash
# in trade_executor/.worktrees/layer-implementation
git merge-base --is-ancestor live-trade-ops layer-implementation && echo "MERGED — clear to start" || echo "BLOCKED"
git status -sb        # expect: ## layer-implementation, clean
```

Two things are re-checked once it is merged, because that branch adds a crate and moves shared types:

- **Layer 1's import-ripple list** (Task 1.1, Step 5) is re-derived rather than trusted: `grep -rln "local_analysis::" crates` after the merge. `live_trade_ops` is written against the L0 traits only and should not appear, but confirm rather than assume.
- **The baseline test count** (Task 1.1, Step 1) is captured *after* the merge, on the merged `layer-implementation` — the pre-merge number is meaningless once `live_trade_ops`'s offline tests are in the workspace.

---

## Global Constraints

- **Branches.** Executor: cut `sar-flip-test-signal` from `layer-implementation` **after the prerequisite above is satisfied**; the worktree is then already on `layer-implementation`, so no checkout conflict remains. `main/`: cut `sar-broadcast-tf1` from `experimental_imp_2`.
- **Commits need confirmation.** There is no standing commit authorization for these branches. Ask for one at kickoff; until it is granted, each task's commit step means *stage, describe, and wait*. Push and merge always need explicit confirmation.
- **Gate command (executor):** `docker compose run --build --rm test cargo test --workspace`. `--build` is mandatory or the test image is stale. While a deliberately-RED test exists, use `--no-fail-fast` and read "green" as "no failures other than the known RED case named in the task".
- **Gate command (`main/`):** `docker compose run --rm live python3 -m pytest tests/test_shared_indicators_config.py -q`.
- **Container-written files are root-owned.** The compose `test` service writes `target/` as root inside the mounted worktree; if a later `git` operation refuses, `sudo chown -R $USER:$USER target` in the worktree.
- **Indicators are read through `current_indicator`** — the existing cached path, warm because this process ingests the readings — reached through the existing indicator trait, renamed `IndicatorSink` → `IndicatorStore` and extended with that method (§6.2). One new trait in the whole feature (`IndicatorSource`, forced by the L2 boundary); no second one describing the same store. The dashboard's `read_current_indicators` is not touched and not reused; it stays the visualiser's uncached, every-name, `as_of`-filtered reader.
- **`now` is `exchange_adapter::now_ms()`**, the wall clock, because `expires_at` was written by `main/`'s wall clock. Flip pacing (`min_flip_interval`) stays on exchange time. The asymmetry is deliberate (§6.4).
- **No schema change, no migration.** `SCHEMA_VERSION` is untouched; the `indicators` table, `current_indicator` and `run_indicator_ingest_task` are all unchanged (§6).
- **`SignalEvent` has two stored mirrors.** `state_store::dto::SignalEventDto` (with `From<&SignalEvent>` *and* `TryFrom<SignalEventDto>`) and `visualizer_server::dto::SignalEventDto` (`From` only). Adding a variant is a compile error in both until both are updated — that is the intended guardrail, not an obstacle to route around.
- **`SignalEvent::signal_id`'s `match` is the single source of truth** for event→`SignalId` (its own doc comment says so). Add the arm there, nowhere else.
- **Decimal literals** follow the codebase's `Decimal::from_parts(...)` / `Decimal::new(mantissa, scale)` style, never `Decimal::from_str` in production code.
- **`min_flip_interval` is a signal parameter, not an env var** (D5a). It is passed on `SignalConfig::SarFlip` where the pipeline is built, and measured against **exchange timestamps** (`window.now`), never `Instant::now`.
- **`MIN_RR=0` is deployment-scoped** (§9) and disables the R:R gate for *every* decision path in that deployment. It belongs in the compose environment, never as a new default in `config.rs`.
- **No implementation code in this plan** — signatures and test descriptions only, except where a test body *is* the deliverable.

## Review Focus

Five input classes the spec implies but that no task's happy path exercises. Each has its test pinned to the task that owns the code.

1. **Configured indicator name never published** (typo in `SAR_TEST_SIGNAL_INDICATOR`, or `main/` publishing `15_sar_002_02` while the executor asks for `1_sar_002_02`). The signal is then silently dead forever. → Task 2.2 asserts an unpublished name is absent from the window rather than defaulted, Task 2.3 that an unknown name is `None` not an error, Task 3.2 that an absent name leaves the relation untouched; Task 5.3 asserts boot logs the configured indicator name once, so the misconfiguration is discoverable from the startup log rather than from silence.
2. **Reading for a different pair.** `main/`'s `PAIR=link_usdt` and the executor's `PAIRS=LINKUSDT` can drift. The cache is keyed by `(pair, name)`, so a wrong pair reads as "no indicator". → Task 2.3 asserts a reading recorded for `LINKUSDT` is not returned for `BTCUSDT`.
3. **Expiry boundary and clock choice.** `current_indicator` treats `now == expires_at` as expired, and `expires_at` is a wall-clock value — so the pipeline must pass `now_ms()`, never a trade's exchange timestamp (§6.4). A trade timestamp would judge a wall-clock expiry against a different clock. → Task 2.3 asserts the boundary; Task 2.2 asserts the pipeline passes wall-clock time.
4. **Flip against a position that closed underneath us.** Between the position read and the `Close` decision, a stop-out can flatten the pair; `handle_decision` then reports `AlreadyClosed`. The `Open` must still proceed — the flip is still valid. → Task 5.2.
5. **`sar` exactly equal to `price`**, and flips with sub-cent differences. Equality names no side and must not fire, and must not corrupt the stored relation. → Task 3.2.

---

## Docker Entry Points

```bash
# Executor — every layer's gate (run from the layer-implementation worktree)
docker compose run --build --rm test cargo test --workspace
docker compose run --build --rm test cargo test --workspace --no-fail-fast   # while a RED case is open

# Executor — one crate while iterating
docker compose run --build --rm test cargo test -p signals
docker compose run --build --rm test cargo test -p orchestrator

# main/ — config test
docker compose run --rm live python3 -m pytest tests/test_shared_indicators_config.py -q

# Layer 7 staging runs (human-gated, one at a time)
EXECUTION_MODE=no_trade docker compose up executor        # from trade_executor
docker compose up live                                    # from main/, publishes indicators
EXECUTION_MODE=live docker compose up executor            # only after the no_trade run is accepted
```

Verified: [ ] `docker compose run --build --rm test cargo test --workspace` is green on the branch point before any change.

---

## Layer 1: `signals` crate — carve-out (pure move, no behaviour change)

### Task 1.1: Create the crate and move every signal module into it

**Files:**
- Create: `crates/local_analysis/signals/Cargo.toml`, `crates/local_analysis/signals/src/{lib,types,indicator,factory,depletion}.rs`, `crates/local_analysis/signals/src/checks/{mod,extreme_volume,volume_projected,volume_book_depletion,mock_volume_cross}.rs`
- Modify: `Cargo.toml` (workspace members), `crates/local_analysis/Cargo.toml`, `crates/local_analysis/src/lib.rs`, `crates/local_analysis/src/types.rs`
- Delete: `crates/local_analysis/src/{signals,mock_signal,depletion}.rs`
- Modify (imports only): `crates/orchestrator/src/{system,tests,main}.rs`, `crates/state_store/src/{lib,dto,pg}.rs`, `crates/state_store/tests/pg_store.rs`, `crates/replay_harness/src/lib.rs`, `crates/visualizer_backend/src/lib.rs`, `crates/visualizer_server/src/dto.rs`, `crates/visualizer_server/tests/passive.rs`
- Modify (doc text only): `crates/db_schema/src/lib.rs`

**Interfaces:**
- Produces, from crate `signals`: `SignalId`, `SignalConfig`, `SignalEvent`, `ThresholdSpec`, `VOLUME_BOOK_DEPLETION_IDS`, `SignalCheck`, `MarketDataWindow`, `SignalPipeline`, `SimpleSignalFeed`, `SignalEventStream`, `SignalFactory`, `project_target_price`, and the check types. Names and types are **unchanged** — only the crate path changes.
- `local_analysis` keeps: `Level`, `LevelKind`, `LevelSource`, `Price`, `DecisionContext`, `DecisionKind`, `Timeframe`, `SignalAction`, `RiskViolation`, `OpenPositionView`, `PositionAdjustment`, `CriticalLevelAnalyzer`, `LiveCriticalLevelAnalyzer`, `WallDetector`, `combined_levels`, `DefaultSignalBuilder`, `DefaultRiskValidator`, `DefaultPositionAdvisor`.

- [ ] **Step 1: Capture the baseline test count** (post-merge — see Prerequisite)

```bash
docker compose run --build --rm test cargo test --workspace 2>&1 | grep "test result" | tee /tmp/baseline-tests.txt
```

Write the total down. The move must end with exactly the same numbers.

- [ ] **Step 2: Create the crate skeleton and register it**

`crates/local_analysis/signals/Cargo.toml`: package `signals`, `edition.workspace = true`; dependencies `market_data`, `rust_decimal`, `futures-core`, `futures-util`, `async-stream`, `async-trait`; dev-dependencies `observability`, `test_support`, `tokio` (same versions as `crates/local_analysis/Cargo.toml` uses today). Add `"crates/local_analysis/signals"` to the workspace `members` list in the root `Cargo.toml`.

- [ ] **Step 3: Move the files with `git mv`, then split**

```bash
git mv crates/local_analysis/src/depletion.rs        crates/local_analysis/signals/src/depletion.rs
git mv crates/local_analysis/src/mock_signal.rs      crates/local_analysis/signals/src/checks/mock_volume_cross.rs
git mv crates/local_analysis/src/signals.rs          crates/local_analysis/signals/src/lib.rs
```

Then split by hand, moving code without editing it:
- `SignalId`, `SignalConfig`, `SignalEvent`, `ThresholdSpec`, `VOLUME_BOOK_DEPLETION_IDS` and `impl SignalEvent` out of `crates/local_analysis/src/types.rs` into `signals/src/types.rs`.
- `ExtremeVolumeReversalCheck`, `VolumeProjectedMoveCheck`, `VolumeBookDepletionCheck` out of the moved `lib.rs` into their own files under `checks/`, each with its own `#[cfg(test)] mod tests` carrying that check's existing tests.
- `SignalFactory` into `factory.rs`.
- `SignalPipeline`, `SimpleSignalFeed`, `SignalEventStream`, `MarketDataWindow`, `SignalCheck` stay in `signals/src/lib.rs`, together with the pipeline test currently in `crates/local_analysis/src/lib.rs`.

- [ ] **Step 4: Delete the dead duplicate const**

`mock_volume_cross.rs`'s `pub const PLACEHOLDER_STOP_LOSS_PCT` is removed entirely (§4.3): nothing imports it, it duplicates `builder.rs`'s private const of the same name, and the only other mention is a comment in `system.rs:910` which stays accurate.

- [ ] **Step 5: Fix every consumer's `use` lines**

Add `signals = { path = "../local_analysis/signals" }` to `orchestrator`, `state_store`, `replay_harness`, `visualizer_backend`, `visualizer_server`. Change `use local_analysis::{SignalEvent, ...}` to `use signals::{SignalEvent, ...}`, splitting mixed imports (e.g. `use local_analysis::{Level, SignalEvent}` becomes two lines). Update the doc comment in `db_schema/src/lib.rs:24` from `local_analysis::SignalEvent` to `signals::SignalEvent`, and the two `SignalEventDto` doc comments in `state_store/src/dto.rs` and `visualizer_server/src/dto.rs` the same way.

- [ ] **Step 6: Run the gate and compare against the baseline**

```bash
docker compose run --build --rm test cargo test --workspace 2>&1 | grep "test result"
```

Expected: identical counts to `/tmp/baseline-tests.txt`. A changed count means a test was lost in the move — find it before continuing. A changed *assertion* means the move was not pure.

- [ ] **Step 7: Verify the dependency direction**

```bash
docker compose run --build --rm test cargo tree -p signals | grep local_analysis   # expect: no output
docker compose run --build --rm test cargo tree -p local_analysis | grep signals   # expect: no output
```

- [ ] **Step 8: Commit** (ask first, per Global Constraints)

```bash
git add -A
git commit -m "refactor(signals): carve signal checks out of local_analysis into their own crate"
```

---

## Layer 2: The indicator read path (L5 → L2 boundary)

### Task 2.1: `IndicatorSource` interface (signatures only)

**Files:**
- Create: `crates/local_analysis/signals/src/indicator.rs`
- Modify: `crates/local_analysis/signals/src/lib.rs` (module + re-export)

**Interfaces:**
- Produces:

```rust
#[derive(Debug, Clone, PartialEq)]
pub struct IndicatorReadingView {
    pub value: Decimal,
    pub expires_at: Ts,
}

#[async_trait]
pub trait IndicatorSource: Send + Sync {
    async fn latest(&self, pair: &Pair, name: &str, now: Ts) -> Option<IndicatorReadingView>;
}

/// Always `None`. For the construction sites that read no indicators.
pub struct NoIndicators;
```

- [ ] **Step 1: Write the interface with no implementation beyond `NoIndicators`**

Doc comments carry §6.1's reasoning: `async` because the only real implementation is a store read; `None` means "no reading valid at `now`" and deliberately does not distinguish "never arrived" from "expired"; `now` is wall-clock time, because `expires_at` was written by `main/`'s wall clock (§6.4).

- [ ] **Step 2: Write the test**

```rust
#[tokio::test]
async fn no_indicators_always_answers_none() {
    let src = NoIndicators;
    assert_eq!(src.latest(&Pair("LINKUSDT".into()), "1_sar_002_02", Ts(1)).await, None);
}
```

- [ ] **Step 3: Run** — `docker compose run --build --rm test cargo test -p signals no_indicators` → PASS.

- [ ] **Step 4: Commit** — `feat(signals): IndicatorSource interface`

### Task 2.2: Pipeline prefetch (RED first)

**Files:**
- Modify: `crates/local_analysis/signals/src/lib.rs` (`SignalCheck`, `MarketDataWindow`, `SignalPipeline`)
- Modify: `crates/orchestrator/src/system.rs`, `crates/orchestrator/src/tests.rs`, `crates/replay_harness/src/lib.rs` (construction sites gain an argument)

**Interfaces:**
- Consumes: `IndicatorSource`, `IndicatorReadingView`, `NoIndicators` (Task 2.1).
- Produces:

```rust
pub trait SignalCheck: Send + Sync {
    fn id(&self) -> SignalId;
    fn check(&self, window: &MarketDataWindow) -> Option<SignalEvent>;
    fn required_indicators(&self) -> &[String] { &[] }
}

pub struct MarketDataWindow {
    pub pair: Pair,
    pub recent_trades: Vec<TradeTick>,
    pub now: Ts,                                            // exchange time, unchanged
    pub indicators: HashMap<String, IndicatorReadingView>,  // new
}

impl SignalPipeline {
    pub fn new(
        feed: Arc<dyn MarketDataFeed>,
        checks: Vec<Box<dyn SignalCheck>>,
        window_capacity: usize,
        indicators: Arc<dyn IndicatorSource>,
    ) -> Self;
}
```

- [ ] **Step 1: Write the failing test**

In `signals/src/lib.rs`'s test module, beside the moved pipeline test (which already builds a real `MarketDataService` against `test_support::test_db`):

```rust
/// Answers one known name, and records the `now` it was asked for.
struct StubIndicators {
    asked: Mutex<Vec<Ts>>,
    value: Decimal,
}

#[async_trait]
impl IndicatorSource for StubIndicators {
    async fn latest(&self, _pair: &Pair, name: &str, now: Ts) -> Option<IndicatorReadingView> {
        self.asked.lock().unwrap().push(now);
        (name == "1_sar_002_02")
            .then(|| IndicatorReadingView { value: self.value, expires_at: Ts(u64::MAX) })
    }
}

/// Records what the pipeline put in each window it dispatched.
struct WindowSpy {
    required: Vec<String>,
    seen: Mutex<Vec<HashMap<String, IndicatorReadingView>>>,
}

impl SignalCheck for WindowSpy {
    fn id(&self) -> SignalId { SignalId("window_spy") }
    fn required_indicators(&self) -> &[String] { &self.required }
    fn check(&self, window: &MarketDataWindow) -> Option<SignalEvent> {
        self.seen.lock().unwrap().push(window.indicators.clone());
        None
    }
}

/// `SignalPipeline` owns its checks as `Box<dyn SignalCheck>` and the test
/// needs to read `seen` afterwards, so the boxed check is this handle over
/// the shared `Arc`.
struct SpyHandle(Arc<WindowSpy>);

impl SignalCheck for SpyHandle {
    fn id(&self) -> SignalId { self.0.id() }
    fn required_indicators(&self) -> &[String] { self.0.required_indicators() }
    fn check(&self, window: &MarketDataWindow) -> Option<SignalEvent> { self.0.check(window) }
}

#[tokio::test]
async fn the_pipeline_prefetches_declared_indicators_into_the_window() {
    // ... same MarketDataService/test_db setup as the pipeline test above ...
    let spy = Arc::new(WindowSpy {
        required: vec!["1_sar_002_02".to_string(), "never_published".to_string()],
        seen: Mutex::new(vec![]),
    });
    let source = Arc::new(StubIndicators { asked: Mutex::new(vec![]), value: Decimal::new(1234, 2) });
    let pipeline = SignalPipeline::new(feed.clone(), vec![Box::new(SpyHandle(spy.clone()))], 50, source.clone());
    // ingest one trade, drive the stream once
    let seen = spy.seen.lock().unwrap();
    let window = seen.first().expect("check must have run once");
    assert_eq!(window["1_sar_002_02"].value, Decimal::new(1234, 2));
    assert!(!window.contains_key("never_published"), "an unpublished name must be absent, not defaulted");
}

#[tokio::test]
async fn a_check_declaring_no_indicators_gets_an_empty_map_and_no_fetch() {
    // register only the moved ExtremeVolumeReversalCheck (required_indicators() == [])
    assert!(source.asked.lock().unwrap().is_empty(), "nothing declared, nothing fetched");
}

#[tokio::test]
async fn the_fetch_is_asked_for_wall_clock_time_not_the_trades_timestamp() {
    // Review Focus 3: `expires_at` is main/'s wall clock (§6.4). The trade
    // below is stamped ts=1, which is 1970 -- a `now` of 1 would treat
    // every real reading as valid forever.
    // ingest a trade with ts = Ts(1)
    let asked = source.asked.lock().unwrap();
    assert!(asked[0].0 > 1_600_000_000_000, "now must be now_ms(), got {}", asked[0].0);
}
```

- [ ] **Step 2: Run to verify it fails**

`docker compose run --build --rm test cargo test -p signals prefetch` → FAIL to compile (`SignalPipeline::new` takes 3 arguments, `MarketDataWindow` has no `indicators`). That compile failure is the RED state, contained to one crate because nothing else names the new argument yet.

- [ ] **Step 3: Implement**

Add the field, the default trait method and the constructor argument. In `subscribe_signals`, collect the union of `check.required_indicators()` once outside the loop (an empty union means no fetch is ever issued); per trade, `await indicators.latest(&pair, name, Ts(exchange_adapter::now_ms()))` for each name, inserting only the `Some` results into `window.indicators`.

- [ ] **Step 4: Update the other construction sites**

`orchestrator/src/system.rs:468`, `orchestrator/src/tests.rs`'s `signal_pipeline` helper, and `replay_harness/src/lib.rs`'s two test pipelines pass `Arc::new(NoIndicators)`. Layer 5 replaces the orchestrator's with the real adapter. `replay_harness` keeps `NoIndicators` permanently — expiry is judged against wall-clock time, so replaying an indicator-driven signal would read today's indicators against historical trades; "no reading, no flip" is the honest behaviour (spec §13).

- [ ] **Step 5: Run the gate** — `docker compose run --build --rm test cargo test --workspace` → green.

- [ ] **Step 6: Commit** — `feat(signals): prefetch declared indicators into the signal window`

### Task 2.3: `IndicatorStore` + the `StateStoreIndicators` adapter

**Files:**
- Modify: `crates/state_store/src/lib.rs` (`IndicatorSink` → `IndicatorStore`, gains `current_indicator`)
- Modify: `crates/state_store/src/pg.rs` (move the inherent `current_indicator` into the trait impl; one doc-comment correction)
- Modify: `crates/orchestrator/src/indicators.rs` (rename-through: the task's parameter type and `FakeIndicatorSink` → `FakeIndicatorStore`), `crates/orchestrator/src/system.rs` (the `Arc<dyn IndicatorSink>` it passes)
- Create: `crates/orchestrator/src/indicator_source.rs`
- Modify: `crates/orchestrator/src/lib.rs` (module + export)

**Interfaces:**
- Consumes: `StateStoreImpl::current_indicator(pair, name, now) -> Result<Option<IndicatorReading>, StoreError>` (exists today; its body and its cache do not change), `signals::{IndicatorSource, IndicatorReadingView}`.
- Produces:

```rust
// state_store/src/lib.rs -- was `IndicatorSink`
#[async_trait]
pub trait IndicatorStore: Send + Sync {
    async fn record_indicator(&self, pair: Pair, reading: &IndicatorReading) -> Result<(), StoreError>;
    async fn current_indicator(&self, pair: Pair, name: &str, now: Ts)
        -> Result<Option<IndicatorReading>, StoreError>;
}

// orchestrator/src/indicator_source.rs
pub struct StateStoreIndicators { /* store: Arc<dyn IndicatorStore>, alerts: Arc<dyn Alerts> */ }
impl StateStoreIndicators {
    pub fn new(store: Arc<dyn IndicatorStore>, alerts: Arc<dyn Alerts>) -> Self;
}

#[async_trait]
impl IndicatorSource for StateStoreIndicators {
    async fn latest(&self, pair: &Pair, name: &str, now: Ts) -> Option<IndicatorReadingView>;
}
```

A local adapter type is required, not stylistic: Rust's orphan rule forbids `impl IndicatorSource for StateStoreImpl` in a crate that owns neither the trait nor the type.

- [ ] **Step 1: Rename the trait and add the read method (mechanical, no behaviour change)**

`IndicatorSink` → `IndicatorStore` in `state_store/src/lib.rs`, with `current_indicator` added to it and the doc comment saying why the name changed: it is both directions of the indicator store now, not only the write side. In `pg.rs`, `StateStoreImpl`'s **inherent** `current_indicator` moves into `impl IndicatorStore for StateStoreImpl` — moved, not copied, or an inherent method would silently shadow the trait one. Rename through `orchestrator/src/indicators.rs` (parameter type, `FakeIndicatorSink` → `FakeIndicatorStore`, which gains a `current_indicator` returning `Ok(None)`) and `system.rs`.

- [ ] **Step 2: Run the gate** — `docker compose run --build --rm test cargo test --workspace` → green, with the same test count as after Task 2.2. A rename that changes a count changed behaviour.

- [ ] **Step 3: Write the failing tests for the adapter**

```rust
#[tokio::test]
async fn serves_a_recorded_reading_until_its_expiry_and_not_at_or_after_it() {
    let db = test_db().await;
    let store = Arc::new(StateStoreImpl::connect(PgConfig::from_url(&db.url), Arc::new(StdoutMetrics)).await.unwrap());
    let pair = Pair("LINKUSDT".into());
    store.record_indicator(pair.clone(), &IndicatorReading {
        name: "1_sar_002_02".into(),
        value: Decimal::new(1234, 2),
        kind: IndicatorKind::None,
        expires_at: Ts(5_000),
    }).await.unwrap();

    let src = StateStoreIndicators::new(store.clone() as Arc<dyn IndicatorStore>, Arc::new(StdoutAlerts::new()));
    assert_eq!(src.latest(&pair, "1_sar_002_02", Ts(4_999)).await.map(|r| r.value), Some(Decimal::new(1234, 2)));
    // Review Focus 3: `now == expires_at` counts as expired -- current_indicator's own boundary rule.
    assert_eq!(src.latest(&pair, "1_sar_002_02", Ts(5_000)).await, None);
    assert_eq!(src.latest(&pair, "1_sar_002_02", Ts(9_999)).await, None);
}

#[tokio::test]
async fn a_reading_for_one_pair_is_not_served_for_another() {
    // Review Focus 2: main/'s PAIR=link_usdt vs the executor's PAIRS=LINKUSDT.
    // record for LINKUSDT exactly as above, then:
    assert_eq!(src.latest(&Pair("BTCUSDT".into()), "1_sar_002_02", Ts(4_999)).await, None);
}

#[tokio::test]
async fn an_unknown_name_is_none_rather_than_an_error() {
    assert_eq!(src.latest(&Pair("LINKUSDT".into()), "15_sar_002_02", Ts(4_999)).await, None);
}

#[tokio::test]
async fn a_store_error_alerts_and_answers_none() {
    // Injected through the ingest task's existing fake, extended with a
    // read-failure switch -- no second fake, no second trait.
    let store = FakeIndicatorStore::new();
    store.fail_reads();
    let alerts = Arc::new(RecordingAlerts::default());
    let src = StateStoreIndicators::new(store.clone() as Arc<dyn IndicatorStore>, alerts.clone());
    assert_eq!(src.latest(&Pair("LINKUSDT".into()), "1_sar_002_02", Ts(1)).await, None);
    let fired = alerts.fired.lock().unwrap();
    assert_eq!(fired.len(), 1);
    assert_eq!(fired[0].kind, AlertKind::PersistFailed);
    assert!(fired[0].message.contains("1_sar_002_02"), "alert must name the indicator: {}", fired[0].message);
}
```

`FakeIndicatorStore` and `RecordingAlerts` both live in `crates/orchestrator/src/indicators.rs`'s test module — lift them to a shared `pub(crate)` test helper module rather than defining second copies, and give the fake a `fail_reads()` switch beside its existing `fail_next_call()`.

- [ ] **Step 4: Run to verify they fail** — `docker compose run --build --rm test cargo test -p orchestrator indicator_source` → FAIL (module does not exist).

- [ ] **Step 5: Implement the adapter**

`latest` maps `Ok(Some(r))` → `Some(IndicatorReadingView { value: r.value, expires_at: r.expires_at })`, `Ok(None)` → `None`, `Err(e)` → `alerts.fire(AlertEvent::new(AlertKind::PersistFailed, Severity::Warn, format!("indicator read for {pair}/{name} failed: {e}")))` then `None`.

- [ ] **Step 6: Correct the stale doc comment**

`crates/state_store/src/pg.rs`'s `current_indicator` says "only `state_store` itself calls this today ... a plain inherent method rather than trait surface a second implementer would need to provide". Both halves are now false: replace with a line naming the orchestrator's `StateStoreIndicators` as its caller and `IndicatorStore` as its home. Keep the paragraph in `read_current_indicators` explaining the split — it is accurate in both directions: the dashboard reads every name uncached from another process, the executor reads one name from the cache it fills itself (§6).

- [ ] **Step 7: Run the gate** → green.

- [ ] **Step 8: Commit** — `feat(orchestrator): read indicators through IndicatorStore`

## Layer 3: `SarFlipCheck` (L2)

### Task 3.1: The `SarFlip` event and its two stored mirrors

**Files:**
- Modify: `crates/local_analysis/signals/src/types.rs` (`SignalEvent`, `SignalEvent::signal_id`)
- Modify: `crates/state_store/src/dto.rs` (`SignalEventDto`, `From`, `TryFrom`)
- Modify: `crates/visualizer_server/src/dto.rs` (`SignalEventDto`, `From`)

**Interfaces:**
- Produces:

```rust
SignalEvent::SarFlip {
    pair: Pair,
    ts: Ts,
    side: Side,      // Buy when SAR moved above -> below price
    sar: Decimal,
    price: Decimal,
}
// SignalEvent::signal_id() -> SignalId("sar_flip")
```

- [ ] **Step 1: Write the failing tests**

In `state_store/src/dto.rs`'s test module:

```rust
#[test]
fn sar_flip_round_trips_through_the_stored_dto() {
    let event = SignalEvent::SarFlip {
        pair: Pair("LINKUSDT".into()),
        ts: Ts(1_700_000_000_000),
        side: Side::Buy,
        sar: Decimal::new(1234, 2),
        price: Decimal::new(1240, 2),
    };
    let dto = SignalEventDto::from(&event);
    let back = SignalEvent::try_from(dto).expect("stored SarFlip must decode");
    assert_eq!(back, event);
}
```

In `signals/src/types.rs`'s test module:

```rust
#[test]
fn sar_flip_reports_its_signal_id() {
    let event = SignalEvent::SarFlip { /* as above */ };
    assert_eq!(event.signal_id(), SignalId("sar_flip"));
}
```

- [ ] **Step 2: Run to verify they fail** — compile error: no such variant.

- [ ] **Step 3: Implement the variant and both mirrors**

Add the variant, the `signal_id` arm, the `state_store` DTO variant with both conversions, and the `visualizer_server` DTO variant with its `From` arm. The compiler's exhaustiveness errors enumerate every site that needs one.

- [ ] **Step 4: Run the gate** → green.

- [ ] **Step 5: Commit** — `feat(signals): SarFlip signal event`

### Task 3.2: `SarFlipCheck`

**Files:**
- Create: `crates/local_analysis/signals/src/checks/sar_flip.rs`
- Modify: `crates/local_analysis/signals/src/{types,factory}.rs`, `checks/mod.rs`

**Interfaces:**
- Consumes: `MarketDataWindow.indicators` (Task 2.2), `SignalEvent::SarFlip` (Task 3.1).
- Produces:

```rust
SignalConfig::SarFlip { indicator_name: String, min_flip_interval: Duration }

pub struct SarFlipCheck { /* indicator_name, required: [String; 1], min_flip_interval, state: Mutex<SarState> */ }
impl SarFlipCheck {
    pub fn new(indicator_name: impl Into<String>, min_flip_interval: Duration) -> Self;
}
// SignalFactory::create handles SignalConfig::SarFlip
```

- [ ] **Step 1: Write the failing tests**

All eight cases, each a hand-built window — no store, no clock, no sleep:

```rust
fn dec(v: i64) -> Decimal { Decimal::new(v, 0) }

/// One trade at `price` stamped `now`, plus whatever the prefetch would
/// have put in the window (§6.3 -- by the time `check` runs, the fetch
/// already happened, which is exactly why this test needs no source).
fn window_with(sar: Option<Decimal>, price: i64, now: u64) -> MarketDataWindow {
    let pair = Pair("LINKUSDT".into());
    let mut indicators = HashMap::new();
    if let Some(value) = sar {
        indicators.insert(
            "1_sar_002_02".to_string(),
            IndicatorReadingView { value, expires_at: Ts(u64::MAX) },
        );
    }
    MarketDataWindow {
        pair: pair.clone(),
        recent_trades: vec![TradeTick {
            pair,
            price: dec(price),
            qty: dec(1),
            side: Side::Buy,
            trade_id: market_data::TradeId(now),
            ts: Ts(now),
        }],
        now: Ts(now),
        indicators,
    }
}

#[test]
fn first_observation_never_fires() {
    let check = SarFlipCheck::new("1_sar_002_02", Duration::from_secs(60));
    // SAR below price is a relation, not a flip -- there is nothing to
    // have flipped from on the first observation since boot.
    assert_eq!(check.check(&window_with(Some(dec(90)), 100, 1_000)), None);
}

#[test]
fn sar_moving_above_price_fires_sell() {
    let check = SarFlipCheck::new("1_sar_002_02", Duration::from_secs(60));
    check.check(&window_with(Some(dec(90)), 100, 1_000));
    let event = check.check(&window_with(Some(dec(110)), 100, 2_000)).expect("below -> above must fire");
    match event {
        SignalEvent::SarFlip { side, sar, price, .. } => {
            assert_eq!(side, Side::Sell);
            assert_eq!(sar, dec(110));
            assert_eq!(price, dec(100));
        }
        other => panic!("expected SarFlip, got {other:?}"),
    }
}

// The remaining cases follow the same shape -- each is a sequence of
// `window_with` calls and an assertion on what the last one returned:
#[test] fn sar_moving_below_price_fires_buy()                     // above -> below => Side::Buy
#[test] fn an_unchanged_relation_does_not_refire()                // three more windows, all None
#[test] fn a_missing_reading_returns_none_and_keeps_the_relation()
#[test] fn sar_exactly_equal_to_price_returns_none_and_keeps_the_relation()
#[test] fn an_empty_trade_window_returns_none()
#[test] fn a_flip_inside_min_flip_interval_does_not_fire_and_is_not_replayed_late()
```

The last two are the ones worth spelling out:

```rust
#[test]
fn a_missing_reading_returns_none_and_keeps_the_relation() {
    let check = SarFlipCheck::new("1_sar_002_02", Duration::from_secs(60));
    assert_eq!(check.check(&window_with(Some(dec(90)), 100, 1_000)), None);   // first obs: SAR below
    assert_eq!(check.check(&window_with(None, 100, 2_000)), None);            // gap: nothing to read
    // The relation survived the gap, so the flip that follows still reads as a flip.
    let event = check.check(&window_with(Some(dec(110)), 100, 3_000)).expect("below -> above must fire");
    assert!(matches!(event, SignalEvent::SarFlip { side: Side::Sell, .. }));
}

#[test]
fn a_flip_inside_min_flip_interval_does_not_fire_and_is_not_replayed_late() {
    let check = SarFlipCheck::new("1_sar_002_02", Duration::from_secs(60));
    check.check(&window_with(Some(dec(90)), 100, 0));                         // first obs: below
    check.check(&window_with(Some(dec(110)), 100, 1_000)).expect("first flip fires");
    // 30s later, flips back -- inside the 60s interval, so suppressed.
    assert_eq!(check.check(&window_with(Some(dec(90)), 100, 31_000)), None);
    // 120s after the last fire, still below: the suppressed edge was CONSUMED, not deferred.
    assert_eq!(check.check(&window_with(Some(dec(90)), 100, 121_000)), None);
    // A genuine new flip after the interval fires.
    let event = check.check(&window_with(Some(dec(110)), 100, 122_000)).expect("new flip must fire");
    assert!(matches!(event, SignalEvent::SarFlip { side: Side::Sell, .. }));
}
```

- [ ] **Step 2: Run to verify they fail** — `cargo test -p signals sar_flip` → FAIL (no such type).

- [ ] **Step 3: Implement the check**

Exactly §7.2's seven steps, reading `window.indicators[&self.indicator_name]`; `required_indicators()` returns the one-element slice and the check owns no `IndicatorSource` (§6.3). `SignalFactory::create` maps `SignalConfig::SarFlip { indicator_name, min_flip_interval }` to `SarFlipCheck::new(indicator_name, min_flip_interval)` — note this arm ignores the `feed` argument, which is fine and worth a one-line comment saying so.

- [ ] **Step 4: Run** — `cargo test -p signals sar_flip` → all PASS; then the workspace gate → green.

- [ ] **Step 5: Commit** — `feat(signals): SAR flip check`

---

## Layer 4: Nominal exits (L2 builder)

### Task 4.1: Nominal target fallback in `DefaultSignalBuilder`

**Files:**
- Modify: `crates/local_analysis/src/builder.rs`

**Interfaces:**
- Produces: no signature change. `build_signal` with `DecisionKind::Open` now always returns `SignalAction::Open`; the `None => SignalAction::NoOp` arm is gone.

- [ ] **Step 1: Write the failing tests**

```rust
#[test]
fn an_open_with_no_level_above_targets_the_nominal_percentage() {
    let action = DefaultSignalBuilder { max_wait: Duration::from_secs(300) }
        .build_signal(&open_ctx(Side::Buy), &[], Decimal::new(100, 0), Ts(1));
    match action {
        SignalAction::Open { open_price, close_price, stop_loss_price, .. } => {
            assert_eq!(open_price, Decimal::new(100, 0));
            assert_eq!(close_price, Decimal::new(103, 0));   // +3%
            assert_eq!(stop_loss_price, Decimal::new(99, 0)); // -1%, unchanged rule
        }
        other => panic!("expected Open, got {other:?}"),
    }
}

#[test]
fn an_open_short_with_no_level_below_targets_the_nominal_percentage() {
    // Side::Sell, current 100 -> close 97, stop 101
}

#[test]
fn a_level_in_the_profitable_direction_still_wins_over_the_nominal_target() {
    // one Level at 101 with Side::Buy, current 100 -> close_price == 101
}
```

- [ ] **Step 2: Run to verify they fail** — the first two produce `NoOp` today.

- [ ] **Step 3: Implement**

Add `const NOMINAL_TARGET_PCT: Decimal = Decimal::from_parts(3, 0, 0, false, 2); // 0.03` beside `PLACEHOLDER_STOP_LOSS_PCT`, with the same "TEMPORARY / tune by editing this one line" framing. Replace the `None => SignalAction::NoOp` arm with the nominal computation. Update the long comment above that arm — it currently explains why `Open` can become `NoOp`, which stops being true.

- [ ] **Step 4: Run the gate** → green. Watch for existing tests that assert `NoOp` for a levelless `Open`; if one exists, it encoded the old rule and is rewritten to the new one in this task, not deleted.

- [ ] **Step 5: Commit** — `feat(local_analysis): nominal target when no level supports one`

---

## Layer 5: The decision path (L9 orchestrator)

### Task 5.1: Signal-agnostic metric names

**Files:**
- Modify: `crates/orchestrator/src/system.rs` (3 `MetricEvent::new` call sites + the doc comment at line 766), `crates/orchestrator/src/tests.rs` (3 assertions)

**Interfaces:**
- Produces: metrics `signal_firing` and `signal_firing_skipped`, each tagged `pair`, `side`, `signal_id`, plus `decision_id` (fired) / `reason` (skipped).

- [ ] **Step 1: Rename in `system.rs`** — `mock_signal_crossing` → `signal_firing`, `mock_signal_crossing_skipped` → `signal_firing_skipped`, adding `.with_tag("signal_id", event.signal_id().0)` to each.

- [ ] **Step 2: Update the three assertions in `tests.rs`** (`tag_values("mock_signal_crossing_skipped", "reason")` at lines ~1218, ~1236, ~1305) and add one asserting the `signal_id` tag is present on a fired signal.

- [ ] **Step 3: Run the gate** → green. Safe to rename outright: only `StdoutMetrics` and test recorders implement `Metrics`, so nothing outside the workspace reads these names.

- [ ] **Step 4: Commit** — `refactor(orchestrator): signal-agnostic firing metric names`

### Task 5.2: Close-then-reverse

**Files:**
- Modify: `crates/orchestrator/src/system.rs` (`run_signal_decision_task`)
- Modify: `crates/orchestrator/src/tests.rs` (`FakeExecutorSpy` gains a side-parametrized seed and a failure mode)

**Interfaces:**
- Consumes: `SignalEvent::SarFlip { side, .. }` (Task 3.1), `ExecutionEngine::{position_state, handle_decision}`.
- Produces: no new public signature. Behaviour per §8.2.

- [ ] **Step 1: Extend the spy**

```rust
impl FakeExecutorSpy {
    /// Like `seed_open_position`, but names the side -- close-then-reverse
    /// branches on whether the flip opposes the open position.
    fn seed_open_position_side(&self, pair: &Pair, side: Side);
    /// Makes the next `handle_decision` return Err, to prove a failed
    /// Close suppresses the Open that would have followed it.
    fn fail_next_decision(&self);
}
```

- [ ] **Step 2: Write the failing tests**

```rust
#[tokio::test]
async fn a_flip_while_flat_opens_once() {
    // expect handled_decisions() == [Open { side: Buy }]
}

#[tokio::test]
async fn a_flip_against_an_opposite_position_closes_then_opens_the_reverse() {
    executor_spy.seed_open_position_side(&pair, Side::Buy);
    // fire SarFlip { side: Sell }
    let decisions = executor_spy.handled_decisions();
    assert_eq!(decisions.len(), 2);
    assert_eq!(decisions[0].kind, DecisionKind::Close);
    assert_eq!(decisions[1].kind, DecisionKind::Open);
    assert_eq!(decisions[1].side, Side::Sell);
    assert_ne!(decisions[0].id, decisions[1].id, "each decision needs its own id and its own audit row");
    assert_eq!(state_store_spy.logged_decisions().len(), 2);
}

#[tokio::test]
async fn a_flip_on_the_same_side_as_the_open_position_decides_nothing() {
    executor_spy.seed_open_position_side(&pair, Side::Buy);
    // fire SarFlip { side: Buy } -> zero decisions, one signal_log row,
    // one signal_firing_skipped{reason="position_already_open"}
}

#[tokio::test]
async fn a_close_that_fails_in_execution_suppresses_the_open() {
    executor_spy.seed_open_position_side(&pair, Side::Buy);
    executor_spy.fail_next_decision();
    // fire SarFlip { side: Sell }
    assert_eq!(executor_spy.handled_decisions().len(), 1, "the Open must not follow a failed Close");
    // and an OrderPlacementFailed alert fired
}

#[tokio::test]
async fn an_already_closed_position_still_lets_the_reverse_open() {
    // Review Focus 4: the pair flattened between the read and the Close.
    // `handle_decision(Close)` returns Ok (execution reports AlreadyClosed
    // internally), so the Open proceeds: 2 decisions, the second an Open.
}
```

- [ ] **Step 3: Run to verify they fail** — `cargo test -p orchestrator flip` → FAIL.

- [ ] **Step 4: Implement**

Map `SarFlip` to its carried side. Replace the flat-only guard with §8.2's table. Both decisions get their own `DecisionId` and their own `log_decision` call before `handle_decision`, keeping the existing fail-closed rule (a decision that cannot be logged is not executed). An `Err` from the `Close`'s `handle_decision` fires `OrderPlacementFailed` and `continue`s — the `Open` is not attempted.

- [ ] **Step 5: Run the gate** → green.

- [ ] **Step 6: Commit** — `feat(orchestrator): SAR flip closes an opposite position and opens the reverse`

### Task 5.3: Wiring and the enable switch

**Files:**
- Modify: `crates/orchestrator/src/config.rs` (optional knob), `crates/orchestrator/src/system.rs` (`boot`)

**Interfaces:**
- Consumes: `StateStoreIndicators` (2.3), `SarFlipCheck`/`SignalConfig::SarFlip` (3.2).
- Produces:

```rust
// OrchestratorConfig
pub sar_test_signal_indicator: Option<String>,   // SAR_TEST_SIGNAL_INDICATOR, absent by default

// system.rs
pub(crate) const SAR_MIN_FLIP_INTERVAL: Duration = Duration::from_secs(60);
```

- [ ] **Step 1: Write the failing tests**

```rust
#[test]
fn sar_test_signal_indicator_defaults_to_absent() {
    // OrchestratorConfig::from_env with the var unset -> None, and no error
}

#[tokio::test]
async fn the_sar_pipeline_is_constructed_only_when_the_indicator_is_configured() {
    // boot() with the var unset: the mock check is registered, no SAR task
    // boot() with it set:        a SAR task exists and MockVolumeCross is NOT registered
}
```

If `boot`'s existing tests make a full-system assertion awkward, assert on the constructed `Vec<SignalConfig>` by extracting the registration into a small pure helper `fn signal_configs(config: &OrchestratorConfig) -> (Vec<SignalConfig>, Option<SignalConfig>)` and testing that instead — the helper is the deliverable either way.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement**

`from_env` reads `SAR_TEST_SIGNAL_INDICATOR` as an **optional** var (absent is not an error — every other knob in that struct is required, so this one needs its own branch, not `parse_*`). In `boot`, when it is `Some(name)`:
- build `Arc::new(StateStoreIndicators::new(state_store.clone() as Arc<dyn IndicatorStore>, alerts.clone()))` and pass it to a second `SignalPipeline` holding only `SignalConfig::SarFlip { indicator_name: name, min_flip_interval: SAR_MIN_FLIP_INTERVAL }`;
- spawn a second `run_signal_decision_task` for it with `cooldown: Duration::ZERO` (D5a — pacing is the check's job);
- do **not** register `SignalConfig::MockVolumeCross` on the first pipeline (D5);
- `println!` once, beside the existing `EXECUTION_MODE` banner, naming the indicator the SAR signal will read — Review Focus 1's discoverability.

The first pipeline keeps `Arc::new(NoIndicators)` — none of its checks read indicators.

- [ ] **Step 4: Run the gate** → green.

- [ ] **Step 5: Commit** — `feat(orchestrator): wire the SAR test signal behind SAR_TEST_SIGNAL_INDICATOR`

---

## Layer 6: Deploy configuration and `main/`

### Task 6.1: Executor compose environment

**Files:**
- Modify: `docker-compose.yml` (the `executor` service's `environment`)

- [ ] **Step 1: Add the two variables**

```yaml
      - MIN_RR=${MIN_RR:-0}
      - SAR_TEST_SIGNAL_INDICATOR=${SAR_TEST_SIGNAL_INDICATOR:-1_sar_002_02}
```

`MIN_RR` moves from the literal `2` to a `${VAR:-0}` default, matching the exchange knobs' existing convention in that file. The comment above it records §9's cost verbatim: this turns the R:R gate off for **every** decision path in this deployment, not only the SAR signal, and is a test-deployment setting.

- [ ] **Step 2: Verify the service still boots** — `docker compose run --rm executor --migrate-only` exits 0.

- [ ] **Step 3: Commit** — `chore(deploy): SAR test signal env for the executor`

### Task 6.2: `main/` publishes SAR at tf 1

**Files:**
- Modify: `main/configs/shared_indicators_config.yaml`
- Modify: `main/tests/test_shared_indicators_config.py`

- [ ] **Step 1: Write the failing test**

```python
def test_shipped_config_publishes_sar_on_the_one_minute_timeframe():
    """trade_executor's SAR flip signal reads `1_sar_002_02` off the wire;
    the wire name is f"{tf}_{name}", so this entry is what makes that name exist."""
    result = load_shared_indicators_config(path="configs/shared_indicators_config.yaml")
    sar = [c for c in result if c.name == "sar_002_02"]
    assert len(sar) == 1, "sar_002_02 must be published exactly once"
    assert sar[0].timeframes == [1]
```

- [ ] **Step 2: Run to verify it fails**

`docker compose run --rm live python3 -m pytest tests/test_shared_indicators_config.py -q` → FAIL (no `sar_002_02` entry).

- [ ] **Step 3: Add the entry**

```yaml
  - name: sar_002_02
    timeframes: [1]
```

- [ ] **Step 4: Run** → PASS, and the rest of `main/`'s suite stays green.

- [ ] **Step 5: Commit** (branch `sar-broadcast-tf1`) — `feat(indicators): publish parabolic SAR at tf 1 to trade_executor`

---

## Layer 7: Staged runs (human-gated, one at a time)

Each run is a gate: stop, show what will happen, wait for an explicit "go" for *that* run.

### Task 7.1: `no_trade` run

- [ ] **Step 1: Bring both sides up**

```bash
# trade_executor
EXECUTION_MODE=no_trade docker compose up executor
# main/
docker compose up live
```

- [ ] **Step 2: Confirm the indicator is arriving**

```sql
SELECT name, value, expires_at, received_at FROM indicators
WHERE pair = 'LINKUSDT' AND name = '1_sar_002_02'
ORDER BY received_at DESC LIMIT 5;
```

Expected: a new row roughly every 30s. No rows means the wire path is broken — check `main/`'s startup log for `IndicatorPublisher: connecting to trade_executor at tcp://executor:5555` and that both stacks are on the `trader_mq` network.

- [ ] **Step 3: Wait for a flip and check what it produced**

Expected, per flip: one `signal_log` row with `signal_id = 'sar_flip'`; one or two `decision_log` rows sharing the flip's moment; a `signal_firing` metric line on stdout; and a `NotPlaced`/refusal alert from `NoTradeAccount`. **No position opens in this mode** — that is expected, not a failure (§11.4).

- [ ] **Step 4: Record the outcome** in the spec's §11.4 or a run note, and hand the decision to the user.

### Task 7.2: `live` run (real money)

- [ ] **Step 1: Present the gate** — the env that will be used (keys redacted), `RISK_PER_TRADE`, `PAIRS`, and the fact that `MIN_RR=0` means the R:R gate is off for every path. Wait for an explicit "go".

- [ ] **Step 2: Run it watched, from the first flip.**

- [ ] **Step 3: Acceptance** — one full `Open → flip → Close → Open(reverse)` cycle, with every step present in `signal_log`, `decision_log`, the position state rows, and the visualiser.

---

## Ledger — as run (2026-09-25)

`live-trade-ops` was merged into `layer-implementation` (`125a7f3`) before any task started; the post-merge baseline was **1007 passed / 0 failed / 2 ignored** across 48 targets, and the ripple list re-derived on the merged tree matched this plan's (`live_trade_ops` references no `local_analysis` type).

Host iteration ran against the compose Postgres (`TEST_DATABASE_URL=postgres://executor:executor@127.0.0.1:5436/trader`), with the Docker gate at layer boundaries rather than per task — a full `--build` run per task was minutes of wall clock for a rebuild of the same tree.



| Layer | Deliverable | Gate |
|---|---|---|
| 1 | `signals` crate, pure move | Workspace test count identical to baseline; `cargo tree` shows no edge either way |
| 2 | `IndicatorSource` + prefetch + `IndicatorStore` + adapter | Workspace green; test count unchanged across the rename; prefetch, wall-clock `now`, expiry-boundary and pair-isolation tests pass |
| 3 | `SarFlip` event + `SarFlipCheck` | Workspace green; eight check tests pass |
| 4 | Nominal target fallback | Workspace green; a levelless `Open` no longer returns `NoOp` |
| 5 | Close-then-reverse, wiring, metric rename | Workspace green; five decision-path tests pass |
| 6 | Compose env + `main/` config | `--migrate-only` exits 0; `main/` pytest green |
| 7 | `no_trade` then `live` runs | Human gate per run |

Results: Layer 1 **1007 passed** (identical to baseline, as required), Layer 2 **1015**, Layers 3-6 **1037** on the host. Disk exhaustion (the worktree's `target/` had reached 32 GB) interrupted the Docker gate after Layer 6; it was re-run after `cargo clean`.
