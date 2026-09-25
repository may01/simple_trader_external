# SAR-Flip Test Signal — indicator to execution, end to end — Design Spec

Date: 2026-09-22
Status: draft — awaiting user review
Target projects: `trade_executor` (Rust, worktree `layer-implementation`) and `main/` (one config line)
Scope: the first indicator-driven signal. Carves a `signals` crate out of `local_analysis`, gives L2 a read path onto the indicator readings `main/` already broadcasts, adds a SAR-flip check, and lets a flip close an open position and open the reverse. Deliberately minimal strategy content: the point is the wiring, not the edge.
Related: [2026-09-19-level-broadcast-design.md](2026-09-19-level-broadcast-design.md) (the indicator wire path this consumes), [2026-09-20-indicator-broadcast-e2e-check-design.md](2026-09-20-indicator-broadcast-e2e-check-design.md), [layers/L2-local-analysis.md](layers/L2-local-analysis.md), [layers/L9-deploy.md](layers/L9-deploy.md)

## 1. Why this exists

`main/` has been broadcasting indicator readings to the executor since the level-broadcast work, and the executor stores every one of them in Postgres. Nothing reads them back. Every signal the executor can fire today is computed from its own trade feed (`MockVolumeCrossCheck`, `ExtremeVolumeReversalCheck`, `VolumeProjectedMoveCheck`, `VolumeBookDepletionCheck`), so the path from *an indicator `main/` computed* to *an order on the exchange* has never run once, in any environment.

This spec closes that path with the smallest signal that still touches every piece of it: parabolic SAR flipping from one side of price to the other. One indicator, one comparison, no parameters to tune, a flip that is unambiguous and that names a side. Entry, target and stop are nominal — they exist so the pipeline has values to carry, not because they express a view.

What the test proves when it runs green: `main/` computes SAR → publishes it → `mq_gateway` receives it → it becomes readable inside L2 → a `SignalCheck` fires on it → a `TradeDecision` is logged → `execution` builds, sizes and places the order → the position is tracked, and the next flip closes it and opens the reverse.

Secondary, and the reason the crate split is in this spec rather than a later one: this is the *first* of several signals. Grouping them now, before there are five of them scattered through `local_analysis`, is cheap; doing it later is a rename across every consumer.

## 2. Decisions taken (2026-09-22)

| # | Decision | Why |
|---|---|---|
| D1 | All signal code moves into a **new crate `signals`, nested at `crates/local_analysis/signals`**. It depends on nothing from `local_analysis`, and `local_analysis` depends on nothing from it. | Signals are about to multiply. A crate boundary (rather than a module) means no future check can quietly reach into `builder`/`risk`/`advisor`. Nesting keeps the kinship with L2 visible on disk. Verified: a nested workspace member builds with no `exclude` and no warning — that is only a `cargo package` concern, and this workspace never publishes. |
| D2 | The flip is detected by a **real `SignalCheck` inside `SignalPipeline`**, not by a side task in the orchestrator and not by `main/` sending a ready-made decision. | The point of the exercise is the indicator→execution path *through the layers as designed*. A side task would skip `signal_log` and the check abstraction; deciding in `main/` would not test the executor's indicator wiring at all. |
| D3 | Indicators reach L2 through a new **`IndicatorSource` trait** (in `signals`) whose only real implementation is a thin orchestrator adapter over the **existing `StateStoreImpl::current_indicator`** — the read path that already owns a write-through, expiry-aware `(pair, name)` cache. No new cache, no new query, no change to the ingest task or the schema. | The executor ingests these readings, so that cache is always warm here and a read costs no query at all. The dashboard's `read_current_indicators` was considered and rejected (§6): it is uncached, lives on a handle the executor does not hold, and its `received_at <= as_of` filter serves the visualiser's History mode, not a live signal. |
| D3b | The orchestrator side reads through the **existing indicator trait, extended**: `IndicatorSink` gains `current_indicator` and is renamed **`IndicatorStore`**. No new trait in `state_store`, and no second one in the orchestrator. | The read side is currently an inherent method on a concrete type, so it is not trait surface anything can fake or depend on. Rather than declare a second trait describing the same store, the one that already describes it gains the method — two implementors (`StateStoreImpl`, the ingest task's test fake), and `run_indicator_ingest_task`'s existing handle serves both directions. The rename is because "Sink" stops being true once it also reads. |
| D3a | `SignalCheck::check` **stays synchronous**; `SignalPipeline` prefetches each check's `required_indicators()` before dispatching. | `current_indicator` is `async`. Making the whole trait `async` would push I/O into every check for one check's sake; prefetching keeps checks pure functions over a window, which is what makes them testable without a store. |
| D4 | A flip against an **opposite-side open position closes it and then opens the reverse** — two separate, separately-audited decisions in that order. | Exercises both `DecisionKind::Close` and `DecisionKind::Open` on every flip, which is the fullest position-lifecycle test a single signal can produce. |
| D5 | The SAR check runs in **its own `SignalPipeline` and its own decision task**, and the task's own cooldown is **disabled** for it (`Duration::ZERO`). While the SAR test signal is enabled, `MockVolumeCross` is **not registered**. | `MOCK_SIGNAL_COOLDOWN` is 1800s because that is 3x `MockVolumeCrossCheck`'s own 600s dominance window — a number derived from *that* check, which SAR has no equivalent of; inheriting it would throttle SAR to ~2 flips an hour. And two decision paths opening positions on one pair would fight: the mock check would open positions the SAR check then closes, each attributing the other's position to itself. |
| D5a | SAR's pacing is **a parameter of the signal** (`SignalConfig::SarFlip { min_flip_interval }`), enforced inside `SarFlipCheck` against **exchange timestamps**, not an env var enforced by the orchestrator against the wall clock. | Pacing derives from the check's own mechanism, so it belongs with the check, where it is also visible to anyone reading the signal and settable per instance. Measuring it on `window.now` rather than `Instant::now` additionally makes it replay-correct: `replay_harness` feeds historical timestamps, and a wall-clock throttle would fire differently there than it did live. The trade-off is in §7.4. |
| D6 | Nominal exits are reached by **a target fallback in `DefaultSignalBuilder` plus `MIN_RR=0` in the test deployment** (option B of the two considered) — no new type on `TradeDecision`. | ~5 lines against ~40, and no change to a contract `execution` depends on. Cost, accepted: `MIN_RR=0` disables the R:R gate for *every* decision path in that deployment, not just this signal (§9). |
| D7 | `main/` publishes **`sar_002_02` at timeframe 1** (wire name `1_sar_002_02`). | Flips on a 1-minute SAR are minutes apart, so a full open→flip→close→reverse cycle is observable in one sitting. On 15m it would be hours. |
| D8 | Validated in **`EXECUTION_MODE=no_trade` first, then live** on small notional. **No paper step** (§11.4). | `no_trade` proves everything up to the exchange call with no money at risk, but refuses both orders — so position *tracking* (`Opened`/`Closed`, position rows, visualiser) is only observable once fills are real. A paper step was considered and dropped: `EXECUTION_MODE` accepts only `no_trade|live`, and `execution::PaperMarketAccount` is used by nothing but its own unit tests. Wiring it is not one enum arm — it needs the market-data feed, which `boot` constructs *internally*, after the account is passed in, so paper mode requires `boot` to take two accounts (a real one for ingestion, a simulated one for execution). That is its own change; see §13. |

Not covered, by design: any claim that this signal is profitable; R:R, position sizing or stop placement as strategy questions; other indicators; `main/`'s own trading logic; the L0 work in [2026-09-22-live-trade-ops-l0-test-design.md](2026-09-22-live-trade-ops-l0-test-design.md).

## 3. Scope

In:
- New crate `crates/local_analysis/signals` (§4) — a pure move of existing code plus the two new pieces below; workspace green before any behaviour change.
- `main/configs/shared_indicators_config.yaml`: one entry (§5).
- `IndicatorSource`/`IndicatorReadingView` + `NoIndicators` in `signals`; `SignalCheck::required_indicators()` and the pipeline prefetch; `IndicatorSink` → `IndicatorStore` with `current_indicator` on it; `StateStoreIndicators` adapter in the orchestrator (§6).
- `SarFlipCheck` + `SignalConfig::SarFlip` + `SignalEvent::SarFlip` + `SignalId("sar_flip")` (§7).
- Close-then-reverse handling, its own pipeline and task, the enable switch in `system.rs`, and the `signal_firing*` metric rename (§8).
- Nominal target fallback in `DefaultSignalBuilder`; `MIN_RR=0` in `docker-compose.yml` (§9).
- Tests at every layer (§11).

Out:
- Any change to `execution`'s types, to `mq_gateway`, or to the `state_store` schema. `SignalEvent` gains a variant, which serialises through the existing `signal_log` JSON path with no migration.
- Any change to `run_indicator_ingest_task`'s behaviour (it is renamed-through only), to `current_indicator`'s caching or query, to `read_current_indicators` (the dashboard keeps its own reader), or to the `indicators` table.
- Removing `MockVolumeCrossCheck`. It stays in the tree and stays registered when the SAR signal is disabled.
- Tuning: the 1% stop, the 3% nominal target and the 60s `min_flip_interval` are placeholders, each one line.

## 4. The `signals` crate

### 4.1 Layout

```
crates/local_analysis/
  Cargo.toml                 unchanged deps (market_data, rust_decimal, futures-*, async-stream)
  src/
    lib.rs                   CriticalLevelAnalyzer, LiveCriticalLevelAnalyzer   (SignalPipeline leaves)
    types.rs                 Level, LevelKind, LevelSource, Price, DecisionContext, DecisionKind,
                             Timeframe, SignalAction, RiskViolation, OpenPositionView, PositionAdjustment
    levels.rs  builder.rs  risk.rs  advisor.rs                                   (unchanged)
  signals/
    Cargo.toml               name = "signals"; deps: market_data, rust_decimal, futures-core,
                             futures-util, async-stream
    src/
      lib.rs                 SignalCheck, MarketDataWindow, SignalPipeline, SimpleSignalFeed,
                             SignalEventStream
      types.rs               SignalId, SignalConfig, SignalEvent, ThresholdSpec,
                             VOLUME_BOOK_DEPLETION_IDS
      indicator.rs           IndicatorSource, IndicatorReadingView                (new, §6.1)
      factory.rs             SignalFactory
      depletion.rs           project_target_price                                 (moved verbatim)
      checks/
        extreme_volume.rs    ExtremeVolumeReversalCheck
        volume_projected.rs  VolumeProjectedMoveCheck
        volume_book_depletion.rs
        mock_volume_cross.rs MockVolumeCrossCheck
        sar_flip.rs          SarFlipCheck                                          (new, §7)
```

Workspace `members` gains `"crates/local_analysis/signals"`. Dependents declare `signals = { path = "../local_analysis/signals" }`.

### 4.2 Why the split is clean

Checked before committing to it: `builder.rs`, `risk.rs`, `advisor.rs` and `levels.rs` mention no signal type at all, and `depletion.rs` imports only `market_data`. No check uses `Level`. `Pair`/`Side`/`Ts` are `exchange_adapter`'s types re-exported through `market_data`, so both crates name the same types without either depending on the other. The result is two independent workspace members that merely live in the same directory — not a parent/child pair.

### 4.3 Ripples

- `use` lines only, in: `orchestrator/src/{system,tests,main}.rs`, `state_store/src/{lib,dto,pg}.rs` and `tests/pg_store.rs`, `replay_harness/src/lib.rs`, `visualizer_backend/src/lib.rs`, `visualizer_server/src/dto.rs` and `tests/passive.rs`. Type names do not change, so the edit is mechanical.
- Doc text naming `local_analysis::SignalEvent` (`db_schema/src/lib.rs`) updated to `signals::SignalEvent`.
- `mock_signal.rs`'s `pub const PLACEHOLDER_STOP_LOSS_PCT` is **deleted rather than moved**: it duplicates `builder.rs`'s private const of the same name, nothing imports it, and the only other mention is a comment in `system.rs`.

### 4.4 Sequencing

The move is task 1 and lands on its own: no behaviour change, no new variant, `cargo test --workspace` green before `sar_flip.rs` exists. A move and a feature in one commit would make any bisect through this work useless.

## 5. `main/` — publish SAR at tf 1

`sar_002_02` is already computed on every timeframe (`configs/indicators_config.yaml`, `applies_to: all`) and tf 1 is in `configs/candles_config.yaml`. The whole change is one allowlist entry in `configs/shared_indicators_config.yaml`:

```yaml
indicators:
  - name: ema_7
    timeframes: [15, 60, 240]
  - name: ema_14
    timeframes: [15, 60, 240]
  - name: ema_25
    timeframes: [15, 60, 240]
  - name: sar_002_02
    timeframes: [1]
```

No Python code change. `Robot._publish_shared_indicators` already reads the field per (name, tf), skips non-finite warm-up values with a once-only warning, and publishes on the `MQ_INDICATOR_PUBLISH_INTERVAL_SEC=30` heartbeat with a 300s TTL — comfortable for a 1-minute indicator.

## 6. The indicator read path

No new store, no new cache and no new query: `StateStoreImpl::current_indicator(pair, name, now)` (`crates/state_store/src/pg.rs`) already is the read path this signal needs, and the executor is the process its cache was built for.

That cache is keyed by `(pair, name)`, process-lifetime, **write-through** (`record_indicator` refreshes the entry once its INSERT commits) and **read-through** (a miss, or an entry past its own `expires_at`, falls back to the newest non-expired row and re-caches it; nothing valid ⇒ the stale entry is evicted). Expiry is enforced there, at the boundary the reading itself declared. Because the executor is also the process that *ingests* the readings, the entry is written on every message `main/` sends — so in steady state a read is a `HashMap` hit and issues no query at all.

Consequently `run_indicator_ingest_task` (`crates/orchestrator/src/indicators.rs`) is **not touched by this spec**: it already writes through that cache on every message it persists, and `main/`'s 30s heartbeat keeps the entry warm.

One doc correction rides along: `current_indicator`'s comment says "only `state_store` itself calls this today". After this spec it has a caller.

**Why not the dashboard's `read_current_indicators`** — the query behind the EMA indicator panel — was considered and rejected (user decision, 2026-09-24): it has no cache, so it is a Postgres round trip per call and would need a refresh interval on the trade path; it lives on `PgStateReader`, which the executor does not hold, so it would need the query extracted into a shared free function plus a new `StateStoreImpl` method; and it filters `received_at <= as_of`, which forces a wall-clock `as_of` and would intermittently exclude the newest row. Its own doc comment already says why it is not `current_indicator`: the cache "is only ever warm in the process that ingested the readings (the executor)" and the visualiser "needs every name for the pair rather than one it already knows". Both of those conditions are the other way round here — this *is* the ingesting process, and it wants one name.

### 6.1 `IndicatorSource` (in `signals`)

```rust
/// One indicator reading as a check sees it. `kind` is not carried:
/// checks read numbers, and support/resistance classification belongs to
/// the level path.
pub struct IndicatorReadingView {
    pub value: Decimal,
    pub expires_at: Ts,
}

/// Async, because the only implementation is a store read -- see the
/// orchestrator's adapter below and the prefetch in §6.3 that keeps this
/// out of `SignalCheck::check`.
///
/// `None` means "no reading valid at `now`" and covers both "never
/// arrived" and "expired" -- a check cannot distinguish them and should
/// not try.
#[async_trait]
pub trait IndicatorSource: Send + Sync {
    async fn latest(&self, pair: &Pair, name: &str, now: Ts) -> Option<IndicatorReadingView>;
}
```

`signals` ships only `NoIndicators` (always `None`) for the construction sites that register no indicator-driven check — the four existing pipeline tests and `replay_harness`. L2 stays free of stores, exactly as `CriticalLevelAnalyzer` keeps it free of the market-data service.

### 6.2 `IndicatorStore` (in `state_store`) and the adapter (in the orchestrator)

The read side is an inherent method on `StateStoreImpl` today, so nothing can depend on it or fake it. Instead of declaring a second trait for the same store, the one that already describes it gains the method and a name that stays true:

```rust
/// Was `IndicatorSink`. Both directions of the indicator store: the
/// ingest task writes, the SAR signal's adapter reads.
#[async_trait]
pub trait IndicatorStore: Send + Sync {
    async fn record_indicator(&self, pair: Pair, reading: &IndicatorReading) -> Result<(), StoreError>;
    async fn current_indicator(&self, pair: Pair, name: &str, now: Ts)
        -> Result<Option<IndicatorReading>, StoreError>;
}
```

`StateStoreImpl`'s inherent `current_indicator` **moves into** this trait impl rather than being duplicated beside it. Two implementors exist (`StateStoreImpl` and the ingest task's own test fake), and `run_indicator_ingest_task` already holds an `Arc<dyn IndicatorSink>` that becomes an `Arc<dyn IndicatorStore>` serving both directions.

The orchestrator's adapter is then the smallest thing that can exist — a local type, because Rust's orphan rule forbids `impl IndicatorSource for StateStoreImpl` in a crate owning neither:

```rust
pub struct StateStoreIndicators {
    store: Arc<dyn IndicatorStore>,
    alerts: Arc<dyn Alerts>,
}
```

`latest` calls `current_indicator` and maps `Ok(Some(r))` → `Some(view)`, `Ok(None)` → `None`, `Err(e)` → an alert plus `None`. The `Result`-to-`Option` narrowing happens here, in the one place that has an `Alerts` handle: a store that cannot answer must not be silently indistinguishable from an indicator that never arrived, but it also must not be a reason for a check to carry error plumbing.

### 6.3 Prefetch, so checks stay synchronous

`SignalCheck::check` is synchronous and stays that way — making it `async` would put I/O inside every check for the sake of one of them. Instead the pipeline, which is already async, fetches before it dispatches:

```rust
pub trait SignalCheck: Send + Sync {
    fn id(&self) -> SignalId;
    fn check(&self, window: &MarketDataWindow) -> Option<SignalEvent>;
    /// Indicator names this check reads. Default: none.
    fn required_indicators(&self) -> &[String] { &[] }
}

pub struct MarketDataWindow {
    pub pair: Pair,
    pub recent_trades: Vec<TradeTick>,
    pub now: Ts,
    pub indicators: HashMap<String, IndicatorReadingView>,   // new
}
```

`SignalPipeline::new` gains an `Arc<dyn IndicatorSource>`. Per incoming trade it awaits `latest(pair, name, now)` for the union of its checks' `required_indicators()` — for this spec, exactly one name — and puts whatever came back into `window.indicators`. Names with no valid reading are simply absent from the map.

### 6.4 Which clock `now` is

`expires_at` is produced by `main/`'s wall clock (`now + ttl_seconds`) and compared against whatever the caller passes. The pipeline therefore passes `exchange_adapter::now_ms()`, **not** the trade's timestamp: a trade timestamp is exchange event time, a different clock, and comparing it against a wall-clock expiry is only ever accidentally right.

Keep the resulting asymmetry deliberate: **expiry is wall-clock time, flip pacing (`min_flip_interval`, §7.2) is exchange time** — the first because that is the clock the column was written with, the second because it must behave identically in replay.

Cost in the normal case: one `Mutex` lock and a clone per trade, because the entry is warm. Cost when `main/` is not publishing at all: `current_indicator` evicts on a `None` result, so every trade issues one small indexed query. Named as a risk in §12, with a per-name prefetch throttle as the one-line fix if it ever matters.

## 7. `SarFlipCheck`

### 7.1 Semantics

Parabolic SAR sits on one side of price and jumps to the other when the trend it is tracking ends. The signal is that jump, seen as a change in the sign of `price − sar`:

- SAR was **above** price, now **below** ⇒ `Side::Buy`
- SAR was **below** price, now **above** ⇒ `Side::Sell`

### 7.2 Shape

```rust
pub struct SarFlipCheck {
    /// Both the name read out of `window.indicators` and, returned as a
    /// one-element slice from `required_indicators()`, what tells the
    /// pipeline to prefetch it (§6.3). The check holds no
    /// `IndicatorSource` of its own.
    indicator_name: String,                   // "1_sar_002_02"
    required: [String; 1],                    // = [indicator_name.clone()]
    /// Minimum gap between two fired flips, measured on exchange
    /// timestamps. A parameter of the signal, carried on
    /// `SignalConfig::SarFlip` -- see D5a.
    min_flip_interval: Duration,
    state: Mutex<SarState>,
}

struct SarState {
    last_relation: Option<Relation>,          // Above | Below
    last_fired: Option<Ts>,
}
```

and the config it is built from:

```rust
SignalConfig::SarFlip { indicator_name: String, min_flip_interval: Duration }
```

`Mutex` for the same reason `MockVolumeCrossCheck` has one: `check` takes `&self`, and remembering the previous observation is the whole mechanism. One `Mutex<SarState>` rather than two fields under two locks, so the relation and the throttle can never be read half-updated.

`check(window)`:

1. `price` = the newest trade in `window.recent_trades` (the pipeline pushes it there immediately before calling); no trades ⇒ `None`.
2. `sar` = `window.indicators.get(&self.indicator_name)`; absent ⇒ `None`, **state untouched**. Absent covers "never arrived" and "expired" alike — expiry was applied by `current_indicator` against the `now` the pipeline passed (§6.4), so a dead `main/` makes the signal go quiet within one TTL rather than trade on a frozen number.
3. `relation` = `Below` if `sar < price`, `Above` if `sar > price`; exactly equal ⇒ `None`, state untouched (no side to name).
4. Swap `relation` into `state.last_relation`. Previous `None` (first observation since boot) ⇒ `None`: there is nothing to have flipped from.
5. Unchanged relation ⇒ `None`.
6. Changed, but `window.now - state.last_fired < min_flip_interval` ⇒ `None`. The relation update from step 4 **stands**: the edge is consumed, not deferred, so the check does not fire it late once the interval passes.
7. Otherwise set `state.last_fired = window.now` and fire.

```rust
SignalEvent::SarFlip { pair, ts, side, sar, price }
```

with `SignalId("sar_flip")`, added to `SignalEvent::signal_id`'s single `match` — the one place that mapping lives.

### 7.3 Two consequences worth naming

- The check is evaluated **per trade**, while the SAR value refreshes every 30s. A flip therefore fires the moment *price* crosses the last published SAR, which can be well before `main/` itself would notice on its own candle close. That is the intended reading of "SAR changed position relative to price" and it is what makes the signal observable, but it is not identical to a flip computed on closed candles in `main/`.
- Price oscillating around SAR produces repeated flips. `min_flip_interval` (default 60s) is the only guard, and it is a blunt one: in chop the signal will open and reverse repeatedly. Acceptable for a wiring test on small notional; it is the first thing to fix if this signal is ever taken seriously.

### 7.4 What moving the throttle into the check changes

`run_signal_decision_task`'s existing cooldown counts *accepted* crossings — it starts only once a crossing has passed the flat/position guards and is committed to becoming a decision. `min_flip_interval` counts *fired* flips instead, one step earlier, so a flip that the decision task then discards (same-side position already open, or a decision that fails to log) still consumes the interval.

The practical difference is small and one-directional: it can only make the signal quieter, never noisier, and the case where they differ — a flip discarded because a same-side position is already open — is immediately followed by an opposite-direction flip anyway, which is the one that matters. Stated here because it is a real behavioural difference from the mock path, not an accident of implementation.

## 8. From flip to orders

### 8.1 Its own pipeline and task

`boot()` registers a second `SignalPipeline` for each pair containing only `SarFlipCheck`, and spawns a second `run_signal_decision_task` for it with `cooldown: Duration::ZERO` — pacing is the check's job now (D5a), and a second throttle on top of it would be a number nobody could derive from anything. When `SAR_TEST_SIGNAL_INDICATOR` is set, `SignalConfig::MockVolumeCross` is not registered on the first pipeline (D5). When it is unset, none of this is constructed and the system behaves exactly as it does today.

### 8.2 Close, then reverse

`run_signal_decision_task` (`crates/orchestrator/src/system.rs`, currently at line 793) maps `SignalEvent` to an optional side and hard-skips whenever the pair is not flat. `SarFlip` maps to its carried `side`, and the not-flat branch gains a case:

| Position state | Action |
|---|---|
| Flat | `Open` (today's path) |
| Open, **opposite** side | `Close` decision → `await handle_decision` → then the `Open` decision |
| Open, **same** side | Recorded via `record_signal_without_decision`, no decision, `signal_firing_skipped{reason="position_already_open"}` (§8.3) |

Each of the two decisions gets its own `DecisionId` and its own `decision_log` row, written **before** `handle_decision` is called, and keeps today's fail-closed rule: a decision that cannot be logged is not executed. If the `Close` fails in execution, the `Open` is **not** attempted — reversing into a position that was supposed to have been closed is the one outcome worse than doing nothing, and the existing `OrderPlacementFailed` alert carries the reason.

The cooldown clock starts at the flip, not per decision, so one flip costs one cooldown regardless of whether it produced one decision or two.

### 8.3 Metric names

The task is now shared by two kinds of signal, so its two metrics are renamed `mock_signal_crossing` → `signal_firing` and `mock_signal_crossing_skipped` → `signal_firing_skipped`, each gaining a `signal_id` tag alongside the existing `pair`/`side`/`reason`/`decision_id` ones. Safe to rename outright: the only implementations of `Metrics` are `StdoutMetrics` and test recorders, so nothing outside the workspace reads these names. Three assertions in `orchestrator/src/tests.rs` move with them.

## 9. Nominal exits (option B)

Two things stop a nominal trade from reaching the exchange today:

1. `DefaultSignalBuilder` resolves the target from `combined_levels` and returns `NoOp` when nothing sits in the profitable direction.
2. `DefaultRiskValidator` vetoes anything below `MIN_RR` (2 in `docker-compose.yml`).

The fix is the smaller of the two considered:

```rust
// builder.rs, alongside PLACEHOLDER_STOP_LOSS_PCT
/// TEMPORARY: target used when no level supports one. Same status as the
/// placeholder stop beside it -- a number that lets a decision reach
/// execution, not a considered exit. Tune by editing this one line.
const NOMINAL_TARGET_PCT: Decimal = Decimal::from_parts(3, 0, 0, false, 2); // 0.03
```

`nearest_in_direction(...)` returning `None` now yields `open_price * (1 ± NOMINAL_TARGET_PCT)` instead of `SignalAction::NoOp`, so an `Open` always produces an `Open`. The stop stays the existing unconditional ±1%.

`MIN_RR=0` in the executor service's environment then makes the R:R gate pass everything (`risk = 1%` of entry is non-zero, so the ratio always resolves and `rr >= 0` always holds; stage 2 and the probability estimate are never reached).

**The cost, stated plainly:** `MIN_RR` is a deployment-wide knob. Setting it to 0 disables the R:R gate for *every* decision path in that deployment — the mock signals and any decision `main/` sends over MQ, not only this one. That is acceptable for a wiring test on small notional and unacceptable for a deployment doing anything else at the same time. A deployment that needs both a live R:R gate and this signal needs option A (an explicit per-decision exit policy), which this spec deliberately does not build.

A second, smaller consequence: when levels *do* exist near the entry, the target is still the nearest level, which may be a few basis points away — the position will often close on target rather than on the next flip. The flow is still exercised end to end; the exit reason just varies.

## 10. Configuration

| Var | Where | Value | Meaning |
|---|---|---|---|
| `SAR_TEST_SIGNAL_INDICATOR` | executor | `1_sar_002_02` | Enables the whole SAR path and names the indicator. Unset **or blank** ⇒ nothing in this spec is constructed, and `MockVolumeCross` is registered in its place. Blank counts as unset because that is how an operator turns it off in a compose file. |
| — | `system.rs` const | `min_flip_interval = 60s` | Signal parameter, not an env var (D5a). Passed on `SignalConfig::SarFlip` where the pipeline is constructed; tune by editing that line. |
| `MIN_RR` | executor | `${MIN_RR:-0}` | R:R gate off (§9). Was a literal 2; now a defaulted override, matching the exchange knobs' convention in that file. |
| `EXECUTION_MODE` | executor | `no_trade`, then `live` | Staging (§11.4). `paper` is not a valid value today (D8). |
| `PAIRS` | executor | `LINKUSDT` | Unchanged; must match `main/`'s `PAIR=link_usdt`. |
| `MQ_INDICATOR_PUBLISH_INTERVAL_SEC` | `main/` | `30` | Unchanged. |
| — | `main/` | `sar_002_02: [1]` | The allowlist entry (§5). |

## 11. Testing

### 11.1 The move (task 1)
`cargo test --workspace` green, unchanged test count, before any new behaviour exists.

### 11.2 Unit — `signals`
`SarFlipCheck`: first observation never fires; `Above→Below` fires `Buy` and `Below→Above` fires `Sell`; an unchanged relation does not re-fire across many calls; a missing reading, an expired reading and `sar == price` each return `None` **and leave the stored relation untouched** (asserted by firing correctly on the next valid observation); an empty trade window returns `None`. Throttle: a second flip inside `min_flip_interval` does not fire, the one after it does, and the suppressed edge is not replayed late (step 6) — all driven by the timestamps in the window, so the test needs no clock and no sleep. Every case is a hand-built `MarketDataWindow` — no `IndicatorSource`, no orchestrator, no store, because the prefetch already happened by the time `check` runs.

### 11.3 Unit/integration — orchestrator
- `StateStoreIndicators` against a test database: a recorded reading is returned before its `expires_at` and not at or after it; a reading for another pair is not served; a store error produces an alert and `None`, injected through the ingest task's existing fake rather than a second one. The ingest task's own tests change by rename only.
- `SignalPipeline` prefetch: a check declaring an indicator name receives it in `window.indicators`; a name nothing published is absent rather than defaulted; the fetch is asked for wall-clock time, not the trade's timestamp.
- Decision task, with an executor spy: a flip while flat produces exactly one `Open`; a flip against an opposite position produces `Close` **then** `Open`, in that order, with two distinct `decision_log` rows; a flip on the same side produces no decision; a `Close` that fails in execution suppresses the `Open`. No cooldown assertion here — the task runs with `Duration::ZERO` and the throttle is tested in §11.2.
- Builder: an `Open` with no level in the profitable direction yields the nominal target rather than `NoOp`, on both sides; with a level present, behaviour is unchanged.

### 11.4 Environment staging

1. **`no_trade`** — `docker compose up`, `main/` publishing. Observable: `indicators` rows for `1_sar_002_02`, a `signal_log` row per flip, one or two `decision_log` rows per flip, and `NotPlaced`/refusal alerts from `NoTradeAccount`. This proves everything **up to** the exchange call; positions never open, so nothing after it. In particular this step cannot show `Opened`/`Closed` events, position state rows, the close-then-reverse sequence as a real lifecycle, or the visualiser rendering any of it.
2. **`live`** — small `RISK_PER_TRADE`, `LINKUSDT`, one pair, watched from the first flip. This is the only step in scope that exercises the second half: real fills, real position tracking, real fees.

There is no simulated middle step (D8). If one is wanted before risking money, wire paper mode first (§13) — it is a separate change to `boot`, not a flag.

Acceptance: one full `Open → flip → Close → Open(reverse)` cycle observed in step 2 or 3, with every step present in `signal_log`, `decision_log`, the position state rows and the visualiser.

## 12. Risks

| Risk | Handling |
|---|---|
| `MIN_RR=0` disables the R:R gate deployment-wide (§9) | Stated in §9 and §10; test deployment only; option A exists if it ever needs to coexist with a live gate. |
| Chop produces repeated flips and repeated reversals | 60s `min_flip_interval` on the check; small notional; named in §7.3 as the first thing to fix. |
| `main/` stops publishing | Readings expire (300s TTL) inside `current_indicator`, the name goes absent from `window.indicators`, and the check goes quiet rather than trading on a frozen SAR (§7.2 step 2). |
| A never-published or long-dead indicator makes the prefetch query Postgres once per trade (`current_indicator` evicts on a `None` result) | Small indexed query, a few per second at this pair's trade rate; the normal case is a warm cache refreshed every 30s by the ingest task. One-line fix available if needed: throttle the prefetch per `(pair, name)` in the pipeline. |
| Executor's flip fires earlier than `main/`'s own candle-close flip | Intended (§7.3), documented so the two are never expected to agree tick for tick. |
| Two decision paths racing on one pair | `MockVolumeCross` unregistered while the SAR signal is enabled (D5). |
| `no_trade` looks green while proving only half the path | §11.4 says exactly what each mode does and does not show. |

## 13. As built (2026-09-25)

Implemented on branch `sar-flip-test-signal` (executor) and `sar-broadcast-tf1` (`main/`), six commits plus one. Deviations from this spec, all deliberate:

- **The moved test module stayed whole.** §4.1 put a `#[cfg(test)] mod tests` in each check file; the 359-line module that came out of `signals.rs` shares one set of fixtures (`trade`, `window`, the `FakeFeed` order-book double) and several of its tests drive a check through `SignalFactory`, so it lives in `checks/mod.rs` with a comment saying why. The per-check code split is as specified.
- **`SignalConfig` lost `Copy`.** `SarFlip` carries the indicator name, which is operator config read at boot rather than a `&'static str`.
- **The registration decision was extracted.** `trade_window_signal_configs` and `sar_signal_config` in `system.rs` are pure functions, so "the mock check and the SAR check are never registered together" is testable without a database, an exchange or a socket.
- **Both legs of a reversal emit `signal_firing`**, tagged `kind=close|open`, rather than one metric per firing. A close leg is a real order and deserves its own line.
- **Boot says which indicator the signal will read**, once, on both branches (armed and disabled) — §12's "silently dead signal" risk, made visible in the startup log.
- **Test fixtures were lifted**, not duplicated: `FakeIndicatorStore` and `RecordingAlerts` moved to `orchestrator::test_fixtures` so the adapter's failure path is injected through the same fake the ingest task is tested against.

Verification at the last commit: workspace **1037 passed, 0 failed** (baseline 1007), Docker gate green through Layer 2; `main/`'s config tests 7/7 on the host.

## 14. Open items

- **Replaying an indicator-driven signal is not supported.** Expiry is judged against wall-clock time (§6.4), so a replay would read today's indicators against historical trades. `replay_harness` passes `NoIndicators`, which makes that honest — no reading, no flip — rather than quietly wrong. A replayable source (`as_of` driven by the replayed event's own time, against `received_at`) is its own change.
- **Paper mode is not wired** (D8, §11.4). `EXECUTION_MODE` parses `no_trade|live` only, and `PaperMarketAccount` needs `Arc<dyn MarketDataFeed>` — which `boot` creates after receiving the account, so paper needs `boot` to take a real account for ingestion *and* a simulated one for execution. Worth doing (it is the only way to watch a full position lifecycle without money) but it is its own task, outside this spec. Note also that `PaperMarketAccount` leaves `Stop` orders resting without trigger simulation and fills a `Limit` only when already marketable, so a paper run would exercise flip-driven closes but not stop-outs.
- None blocking. The 1% stop, 3% nominal target, 60s `min_flip_interval` and tf-1 choice are all single-line placeholders, chosen to make the flow observable rather than profitable.
