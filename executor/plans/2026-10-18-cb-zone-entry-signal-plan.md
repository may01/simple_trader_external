# CB Zone Entry Signal Implementation Plan

> **Status 2026-10-18: implemented on branch `cb-zone-entry-signal` (from `layer-implementation` + the uncommitted `decision-markers` work). Layers 1–6 green; Docker gate 1407/3 (3 known flakes, see 6.3); commit awaits user confirmation.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) to implement this plan layer-by-layer. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open positions from main/'s candle-bound zones (tf 15/60/240), gated by a 1-min trade-price MA trend the executor computes itself, instead of the SAR flip test signal.

**Spec:** [`external/executor/specs/2026-10-18-cb-zone-entry-signal-design.md`](../specs/2026-10-18-cb-zone-entry-signal-design.md). § refs below point into it.

**Architecture:** One new `SignalCheck` (`CbZoneEntryCheck`, one instance for all armed tfs) in the `signals` crate plus a pure `trend` module (Rust port of `static/js/trades_ma.js`); a new `SignalEvent::CbZoneEntry` carried through `state_store`'s and `visualizer_server`'s `SignalEventDto`s; orchestrator env knob `CB_ZONE_SIGNAL_TFS`, boot wiring copied from the SAR block, side dispatch, decision timeframe from the event; compose arms CB and disarms SAR. No schema change, no `main/` change.

**Tech stack:** Rust workspace (`tokio`, `rust_decimal`, `sqlx`), Docker Compose. Executor worktree `trade_executor/.worktrees/layer-implementation`.

**Note on layer taxonomy:** as in every executor plan since 2026-09-21, `layer-first-planning`'s principles (Docker first, interface before code, RED test at each boundary, previous layer green before the next) applied over `trade_executor`'s real layers: L2 `signals` → L5 `state_store` → orchestrator → `visualizer_server` → L9 compose.

---

## Global Constraints

- **Branch:** `cb-zone-entry-signal` from the current `decision-markers` head (it carries the JS MA this ports). Never commit without explicit user confirmation.
- **No implementation code in this plan** — signatures and test descriptions only.
- **Test DB isolation:** host inner loop against throw-away postgres `-p cbz-test` on 5437; final gate `docker compose -p cbz-test … run --build --rm test` on a fresh volume. Never the live stack's project.
- **Live executor is not recreated by this work** — operator restarts it.
- **Exits untouched** (§2). `local_analysis::builder` is not opened.

---

## Docker Entry Points

```bash
# host inner loop (no DB needed for signals/orchestrator-unit; DB for state_store/visualizer_server)
cargo test -p signals
cargo test -p orchestrator --lib
docker compose -p cbz-test -f docker-compose.yml -f <scratch>/ports.yml up -d --wait postgres
TEST_DATABASE_URL=postgres://executor:executor@127.0.0.1:5437/trader cargo test -p state_store -p visualizer_server
docker compose -p cbz-test -f docker-compose.yml down -v

# final gate
docker compose -p cbz-test -f docker-compose.yml -f <scratch>/ports.yml run --build --rm test
docker compose -p cbz-test -f docker-compose.yml down -v

# live (operator): CB_ZONE_SIGNAL_TFS=15,60,240 SAR_TEST_SIGNAL_INDICATOR= docker compose up -d executor
```

- [x] **Step 0.1** Branch `cb-zone-entry-signal`.
- [x] **Step 0.2** Baseline: signals 47, orchestrator lib 81 (6 of them DB-backed).

---

## Layer 1: `signals::trend` (L2, pure)

### Interface
```rust
pub struct TrendParams { pub bucket: Duration, pub ma_window: Duration, pub std_mult: f64, pub std_span: Duration, pub min_buckets: usize }
impl Default for TrendParams { /* 10s, 60s, 0.7, 2h, 30 */ }
pub enum TrendClass { Up, Down, Neutral }
pub struct TrendReading { pub class: TrendClass, pub slope: f64, pub sigma: f64 }
pub fn bucket_mean_prices(trades: &[TradeTick], bucket: Duration) -> (Vec<u64> /*sec*/, Vec<f64>);
pub fn trailing_means(values: &[f64], window: usize) -> Vec<f64>;
pub fn slopes(values: &[f64]) -> Vec<Option<f64>>;
pub fn std_dev(values: &[Option<f64>]) -> f64;
pub fn classify(slope: Option<f64>, sigma: f64, std_mult: f64) -> TrendClass;
pub fn trend_class(trades: &[TradeTick], now: Ts, params: &TrendParams) -> Option<TrendReading>;
```
### Unit tests (RED first)
JS fixtures ported 1:1 (§11): bucket means `[10@10s,12@12s,20@30s]` → times `[10,20,30]`, prices `[11,11,20]`; trailing `[2,4,6,8]`,2 → `[2,3,5,7]`; slopes `[1,3,2]` → `[None,2,-1]`; σ of `[2,4,4,4,5,5,7,9]` = 2; classify band at mult 1 on that set; σ=0 → Neutral; `trend_class` on 40 buckets rising-then-flat → last class Neutral and an earlier Up; < 30 buckets → `None`; buckets older than `std_span` excluded from σ.
- [x] 1.1 tests RED · - [x] 1.2 implement · - [x] 1.3 `cargo test -p signals` green (10 trend tests).

## Layer 2: `CbZoneEntryCheck` (L2)

### Interface
```rust
// types.rs
pub const CB_ZONE_ENTRY_IDS: [SignalId; 3]; // cb_zone_15 / cb_zone_60 / cb_zone_240
pub fn cb_zone_entry_id(tf_minutes: u32) -> Option<SignalId>;
pub enum CbZoneRule { InZone, ZoneRejection }
SignalConfig::CbZoneEntry { tfs: Vec<u32>, min_interval: Duration, trend: TrendParams }
SignalEvent::CbZoneEntry { pair, ts, signal_id: SignalId, side: Side, tf_minutes: u32, rule: CbZoneRule, zone: Decimal, price: Decimal, trend_class: TrendClass, ma_slope: Decimal }
// checks/cb_zone_entry.rs
pub struct CbZoneEntryCheck; impl CbZoneEntryCheck { pub fn new(tfs: Vec<u32>, min_interval: Duration, trend: TrendParams) -> Self }
impl SignalCheck for CbZoneEntryCheck { id = "cb_zone_entry"; required_indicators = 10 names per tf }
```
### Integration test → Layer 3 (RED)
`SignalEvent::signal_id()` returns the event's own id; `every_signal_event_variant_maps_to_its_checks_id` extended.
### Unit tests (RED first) — §11 list
rule 1 long/short; rule 1 neutral no-fire; rule 2 long with neutral and up, not down; rule 2 short mirrored; overshoot=0 veto; trend-flag=0 veto; absent flag passes; absent zone → none; same zone never twice, new zone fires; 60 s gap defers; two tfs opposite sides → `None`, nothing recorded; two tfs same side → higher tf, both keys recorded; insufficient trades → `None`; required names; event ids per tf.
- [x] 2.1 tests RED (13) · - [x] 2.2 implement + factory arm + re-exports · - [x] 2.3 green (signals 73). Note: eight names per tf, not ten — spec corrected.

## Layer 3: `state_store` DTO (L5)

### Interface
`SignalEventDto::CbZoneEntry { pair, ts, signal_id: String, side, tf_minutes: u32, rule: String, zone, price, trend_class: String, ma_slope }`; `From<&SignalEvent>`, `TryFrom<SignalEventDto>` (unknown `signal_id`/`rule`/`trend_class` → `Err`); `pg.rs` `ts` arm.
### Tests (RED first)
round-trip; unknown id → `Err`; existing `signal_id_from_str` now also accepts `CB_ZONE_ENTRY_IDS`.
- [x] 3.1 RED · - [x] 3.2 green.

## Layer 4: orchestrator

### Interface
```rust
OrchestratorConfig { pub cb_zone_signal_tfs: Vec<u32>, .. }   // CB_ZONE_SIGNAL_TFS; sorted, deduped; ⊂ {15,60,240}; set with SAR → ConfigError
pub(crate) fn cb_zone_signal_config(config: &OrchestratorConfig) -> Option<SignalConfig>;
pub(crate) const CB_ZONE_MIN_INTERVAL: Duration; // 60 s
fn decision_timeframe(event: &SignalEvent) -> Timeframe; // CbZoneEntry tf → M15/M60/M240, else M15
```
`trade_window_signal_configs`: Mock only when neither CB nor SAR armed. Boot: CB pipeline + decision task next to the SAR block; boot print.
### Tests (RED first)
config: absent → `[]`; `15,240` → `[15,240]`; `240,15,15` → `[15,240]`; `5` → error; blank → `[]`; with SAR → error. `trade_window_signal_configs` has no Mock with CB. Decision task over a scripted-indicator pipeline: CB event (tf 60) opens once with `timeframe M60`; against an opposite position closes then opens reverse (close leg also M60).
- [x] 4.1 RED · - [x] 4.2 green (orchestrator lib 87).

## Layer 5: `visualizer_server` DTO

`SignalEventDto::CbZoneEntry { pair, signal_id, side, tf_minutes, rule, zone, price, trend_class, ma_slope }` (no `ts`); `From` arm. Test: encodes; `pair_signals` passive test with a seeded CB row returns it.
- [x] 5.1 · - [x] 5.2 green (DTO unit test; passive suite 58 unchanged).

## Layer 6: compose (L9) + docs

- `CB_ZONE_SIGNAL_TFS=${CB_ZONE_SIGNAL_TFS:-15,60,240}`; `SAR_TEST_SIGNAL_INDICATOR=${SAR_TEST_SIGNAL_INDICATOR:-}` with comments; `UNFINISHED.md` SAR section notes CB supersedes it as the open signal; spec status updated.
- [x] 6.1 compose · - [x] 6.2 docs · - [x] 6.3 Docker gate on fresh volume (`cbz-test`, `--no-fail-fast`): **1407 passed / 3 failed**, all three pre-existing timing flakes in untouched crates (binance `signed_requests_use_the_server_clock_and_skew_alerts_once` passes on rerun; market_data `write_path` `the_writers_final_batch_is_committed_on_shutdown_not_discarded` / `shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database` flip between runs on host too). Baseline was 1375/0 — +32 new tests. · - [ ] 6.4 stage, describe, wait for commit confirmation.
