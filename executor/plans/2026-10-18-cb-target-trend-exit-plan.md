# CB Target + Trend-Flip Exit Implementation Plan

> **Status 2026-10-18: implemented on branch `cb-target-trend-exit` (stacked on `cb-zone-entry-signal`, both uncommitted). Tasks 1–6 green on the host (signals 83, local_analysis 34, execution 111, orchestrator 90, state_store 20+96, visualizer_server 17+58). Final review (fresh reviewer) → 3 Important fixes applied with RED→GREEN tests: extreme merged on clone write-back, slot reading age-bounded (30 s), risk validator side from stop. Docker gate `cargo test --workspace --no-fail-fast` on a fresh volume: 1444 passed / 0 failed. Commit awaits user confirmation.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) to implement this plan layer-by-layer. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A position opened from a CB zone stores the firing tf's forming-candle far bound as its target, and closes on the first opposite 1-min-MA trend class after its extreme traded through that target — replacing the "close at target price" backstop.

**Architecture:** The trend class moves from `CbZoneEntryCheck` into `SignalPipeline` (once per trade, onto `MarketDataWindow::trend` and a shared per-pair `TrendSlot`). `CbZoneEntryCheck` reads two more names and puts `target` on its event; the orchestrator passes it onto `TradeDecision.target`; `DefaultSignalBuilder` uses it as `close_price`. `Executor` reads the class through a `TrendSource` (the slot), tracks `extreme_price` per open position, and `run_advisor_loop` closes with `CloseReason::Target` on armed ∧ opposite class. No schema, compose or `main/` change.

**Tech stack:** Rust workspace (`tokio`, `rust_decimal`, `serde`, `sqlx`), Docker Compose. Executor worktree `trade_executor/.worktrees/layer-implementation`.

**Spec:** [`external/executor/specs/2026-10-18-cb-target-trend-exit-design.md`](../specs/2026-10-18-cb-target-trend-exit-design.md). § refs point into it.

**Note on layer taxonomy:** `layer-first-planning`'s principles over `trade_executor`'s real layers: L2 `signals` → L2 `local_analysis` → L4 `execution` → L5 `state_store` / `visualizer_server` DTOs → orchestrator → docs. Each layer's host tests green before the next; Docker gate at the end.

---

## Global Constraints

- **Branch:** `cb-target-trend-exit` from the current `cb-zone-entry-signal` head (uncommitted, staged); the staged work rides along. Never commit without explicit user confirmation.
- **No implementation code in this plan** — signatures and test descriptions only.
- **One trend computation per trade per pair** (spec §6, acceptance 4). Nothing else may call `trend_class` at run time.
- **No new env var, no schema change, compose unchanged** (§8, §10).
- **`SignalPipeline::new` and `Executor::new` keep their signatures** — the new inputs come through builder methods (`with_trend`, `with_trend_source`) so the ~25 existing call sites do not churn.
- **Stored rows tolerate the new fields** (§9): `TradeDecisionDto.target` and both `SignalEventDto::CbZoneEntry.target` are `Option` + `serde(default)`.
- **Live executor is not recreated by this work** — operator restarts it.
- **Test DB isolation:** host loop against throw-away postgres `-p cbx-test` on 5437; final gate `docker compose -p cbx-test … run --build --rm test` on a fresh volume ([project-executor-test-isolation]).

## Review Focus

1. A long whose target is already **below** price at fire time (wrong-side `cbnc_high`): must open, arm on the first trade, and close on the first down class — never refuse, never ride past a reversal. Test in Task 4.
2. Price trades through the target then falls back below it with the class still up/neutral: must **stay open** and stay armed; the next down class closes it. Test in Task 4.
3. A deployment with no CB pipeline (SAR/Mock) publishes no class: a position must never close on price alone and never panic on an empty slot. Test in Task 4 (`NoTrend` source) and Task 6 (boot log line).
4. A `signal_log` row written by the entry build without `target`, and a `decision_log` row without it, must decode (`None`), not surface `StoreError::Decode`. Tests in Task 5.
5. The check's own tests after the move: a window with `trend: None` must not fire, and the entry rules must still see exactly the class the pipeline computed on the same trades. Tests in Task 1.

---

## Docker Entry Points

```bash
# host inner loop
cargo test -p signals
cargo test -p local_analysis
cargo test -p execution
cargo test -p orchestrator --lib
docker compose -p cbx-test -f docker-compose.yml -f <scratch>/ports.yml up -d --wait postgres   # ports.yml: postgres 5437, no other ports
TEST_DATABASE_URL=postgres://executor:executor@127.0.0.1:5437/trader cargo test -p state_store -p visualizer_server
docker compose -p cbx-test -f docker-compose.yml down -v

# final gate
docker compose -p cbx-test -f docker-compose.yml -f <scratch>/ports.yml run --build --rm test
```

Verified: [x] final gate green — 1444 passed / 0 failed (2026-10-18).

---

## Task 1 — L2 `signals`: trend computed once per trade; target on the event

**Files:**
- Modify: `crates/local_analysis/signals/src/trend.rs` (add `TrendSlot`)
- Modify: `crates/local_analysis/signals/src/lib.rs` (`MarketDataWindow::trend`, `SignalPipeline::with_trend`, per-trade computation + publish)
- Modify: `crates/local_analysis/signals/src/types.rs` (`SignalConfig::CbZoneEntry` loses `trend`; `SignalEvent::CbZoneEntry.target: Option<Decimal>`)
- Modify: `crates/local_analysis/signals/src/factory.rs`
- Modify: `crates/local_analysis/signals/src/checks/cb_zone_entry.rs` (ten names, read `window.trend`, target on the event)
- Test: same files' `#[cfg(test)]` modules; every existing test that builds a `MarketDataWindow` by struct literal gains `trend: None` (or `Some(..)` where the check needs a class).

**Interfaces:**
- Produces:
  - `pub struct TrendSlot` (in `trend.rs`): `pub fn new() -> Self` (+ `Default`), `pub fn publish(&self, pair: &Pair, ts: Ts, reading: Option<TrendReading>)` (`None` clears the pair's entry), `pub fn latest(&self, pair: &Pair) -> Option<(Ts, TrendReading)>`. Interior `Mutex<HashMap<Pair, (Ts, TrendReading)>>`. `TrendReading` gains `#[derive(Clone, Copy)]` if it lacks it.
  - `MarketDataWindow.trend: Option<TrendReading>`.
  - `impl SignalPipeline { pub fn with_trend(self, params: TrendParams, slot: Arc<TrendSlot>) -> Self }` — stores `Option<(TrendParams, Arc<TrendSlot>)>`; `None` by default.
  - `SignalConfig::CbZoneEntry { tfs: Vec<u32>, min_interval: Duration }` (no `trend`).
  - `CbZoneEntryCheck::new(tfs: Vec<u32>, min_interval: Duration) -> Self`.
  - `SignalEvent::CbZoneEntry { .., target: Option<Decimal> }` (after `zone`); re-export `TrendSlot` from `lib.rs` next to `TrendParams`.

- [ ] **Step 1: RED — `trend.rs` slot tests**

```rust
#[test] fn slot_latest_is_none_until_published()
#[test] fn slot_publish_some_then_latest_returns_ts_and_reading()
#[test] fn slot_publish_none_clears_the_pair_only()   // two pairs, clear one
```

- [ ] **Step 2: RED — pipeline tests in `lib.rs` (host, no DB: use the existing `FakeFeed`-style fixtures in that module; `WindowSpy` records `window.trend`)**

```rust
#[tokio::test] async fn pipeline_without_trend_hands_checks_trend_none_and_leaves_slot_empty()
#[tokio::test] async fn pipeline_with_trend_hands_checks_the_reading_trend_class_gives_on_the_same_trades()
    // feed ≥ 30 buckets of rising trades (10 s apart); assert `window.trend == trend_class(&window.recent_trades, window.now, &params)` and `slot.latest(&pair) == Some((last.ts, reading))`
#[tokio::test] async fn pipeline_with_trend_publishes_none_while_too_few_buckets()
    // 3 trades → window.trend None and slot.latest None
```

- [ ] **Step 3: RED — check tests in `cb_zone_entry.rs`**

Update the fixture builder (`window(..)` helper) to take `trend: Option<TrendReading>` and stop feeding 5 min of trades; a reading is built as `TrendReading { class, slope: 0.0, sigma: 1.0 }`. Then:

```rust
#[test] fn required_indicators_list_ten_names_per_armed_tf_sorted_and_deduped()   // rename of the eight-name test; asserts `{tf}_cbnc_high`/`_low` present, 30 names for three tfs
#[test] fn window_without_trend_never_fires()                                        // inzone=1, class None
#[test] fn rule_1_long_event_carries_target_cbnc_high()                              // `target == Some(cbnc_high value)`
#[test] fn rule_2_short_event_carries_target_cbnc_low()
#[test] fn absent_cbnc_bound_skips_that_side_but_not_the_other()                     // long lacks cbnc_high (would fire), short has cbnc_low and fires with neutral + rule 2
```

Existing rule/filter/re-fire/gap tests keep their assertions, now driven by `trend: Some(..)`.

- [ ] **Step 4: Run `cargo test -p signals` — expect compile failures / RED on the new names**

- [ ] **Step 5: Implement**
  - `TrendSlot` in `trend.rs`; `TrendReading: Clone + Copy`.
  - `MarketDataWindow.trend`; `SignalPipeline { trend: Option<(TrendParams, Arc<TrendSlot>)> }` + `with_trend`; in `subscribe_signals`, after the deque push: `let reading = trend.as_ref().and_then(|(p, _)| trend_class(&recent_vec, trade.ts, p))`, publish to the slot when configured, set `window.trend`.
  - `SignalConfig`/factory/`CbZoneEntryCheck::new` drop `trend`; `check` starts with `let trend = window.trend?;`.
  - `names_for` adds `{tf}_cbnc_high`, `{tf}_cbnc_low` (capacity 10); the per-side block reads `target = indicator("{tf}_cbnc_{high|low}")?` right after `zone`, carries it on `Candidate`, and the fired event sets `target: Some(..)`.
  - `types.rs` tests constructing `CbZoneEntry` gain `target`.

- [ ] **Step 6: `cargo test -p signals` — GREEN; `cargo clippy -p signals` clean**

---

## Task 2 — L2 `local_analysis`: an explicit target on the decision context

**Files:**
- Modify: `crates/local_analysis/src/types.rs` (`DecisionContext.target: Option<Price>`)
- Modify: `crates/local_analysis/src/builder.rs`
- Test: `builder.rs` tests (`ctx(..)` helper gains `target: None`)

**Interfaces:**
- Produces: `DecisionContext { .., target: Option<Price> }`; `build_signal` Open → `close_price = ctx.target.unwrap_or(<existing nearest/nominal>)`.

- [ ] **Step 1: RED**

```rust
#[test] fn open_uses_the_given_target_over_any_level()        // levels [105, 120], target 130 → close_price 130; stop unchanged (99)
#[test] fn open_without_a_target_keeps_the_nearest_level_rule() // existing behaviour pinned: levels [105,120] → 105
#[test] fn short_open_uses_the_given_target_below_entry()       // target 80 for Sell → close_price 80
```

- [ ] **Step 2: `cargo test -p local_analysis` — RED (missing field)**
- [ ] **Step 3: Implement the field and the one-line selection; update the doc comment on the placeholders (they are now the fallback)**
- [ ] **Step 4: `cargo test -p local_analysis` — GREEN** (also `cargo build -p execution` will now fail on `DecisionContext` — fixed in Task 3)

---

## Task 3 — L4 `execution`: `target` on the decision, `extreme_price`, `TrendSource`

**Files:**
- Modify: `crates/execution/Cargo.toml` (`signals = { path = "../local_analysis/signals" }`)
- Modify: `crates/execution/src/types.rs` (`TradeDecision.target: Option<Decimal>`; `OpenPosition.extreme_price: Option<Decimal>`; `new` sets `None`)
- Modify: `crates/execution/src/lib.rs` (re-export `TrendSource`, `NoTrend`)
- Modify: `crates/execution/src/engine.rs` (`TrendSource` trait, `NoTrend`, `Executor.trend_source`, `with_trend_source`, `handle_decision` copies `target` into the context)
- Modify: `crates/local_analysis/src/types.rs::OpenPositionView` (`extreme_price: Option<Price>`) and `engine.rs` where the view is built
- Test: `crates/execution/src/tests.rs` (every `TradeDecision { .. }` literal gains `target: None`; `seeded(..)` sets `extreme_price: None`)

**Interfaces:**
- Produces:
  - `pub trait TrendSource: Send + Sync { fn latest(&self, pair: &Pair) -> Option<signals::TrendReading>; }`
  - `pub struct NoTrend;` (always `None`) — the default.
  - `impl Executor { pub fn with_trend_source(self, source: Box<dyn TrendSource>) -> Self }`
  - `TradeDecision.target: Option<Decimal>`, `OpenPosition.extreme_price: Option<Decimal>`, `OpenPositionView.extreme_price: Option<Price>`.

- [ ] **Step 1: RED — `tests.rs`**

```rust
#[tokio::test] async fn an_open_decision_with_a_target_hands_it_to_the_signal_builder()
    // a RecordingSignalBuilder captures `ctx.target`; decision target Some(123) → captured Some(123)
#[test] fn a_new_position_has_no_extreme_price()
#[test] fn no_trend_source_reports_none()
```

- [ ] **Step 2: `cargo test -p execution` — RED**
- [ ] **Step 3: Implement** (trait + `NoTrend` + field + builder method + context copy; view field populated from the position)
- [ ] **Step 4: `cargo test -p execution` — GREEN** (orchestrator still fails to build until Task 6; that is expected)

---

## Task 4 — L4 `execution`: the close rule in `run_advisor_loop`

**Files:**
- Modify: `crates/execution/src/engine.rs:1529-1600` (`run_advisor_loop`)
- Test: `crates/execution/src/tests.rs` (new `ScriptedTrend(Mutex<Option<TrendReading>>)` implementing `TrendSource`; helper `trend(class) -> TrendReading`)

**Interfaces:**
- Consumes: Task 3's `TrendSource`, `extreme_price`.
- Behaviour (spec §7): per trade — `reading = trend_source.latest(&pair)`; snapshot `Open` position; update `extreme_price` (max for Buy, min for Sell) under the lock; armed = Buy: `extreme > take_profit_price`, Sell: `extreme < take_profit_price`; close = armed ∧ class opposite (Buy→`Down`, Sell→`Up`); on close `do_close(.., CloseReason::Target)` + `TargetHit`, `continue`; else the advisor as today. Remove the price-only `target_reached` block. The log line on close: `target exit {pair}: {side:?} target={} extreme={} price={} class={:?} slope={} sigma={}`.

- [ ] **Step 1: RED — tests (seeded long: entry 100, stop 90, target 110; `setup_with_feed`-style executor built with `.with_trend_source(Box::new(scripted))`)**

```rust
#[tokio::test] async fn long_rising_through_target_with_up_class_stays_open_and_records_the_extreme()
    // trades 105, 112 with Up → no close; extreme_price == Some(112)
#[tokio::test] async fn long_armed_then_down_class_closes_once_with_target_reason()
    // 112 (Up) → set Down → 111: exactly one TargetHit{price:111}, close_reason Some(Target), do_close once (spy order count)
#[tokio::test] async fn long_never_above_target_with_down_class_does_not_close()
    // trades 105, 108 with Down → open, extreme 108
#[tokio::test] async fn long_stays_armed_after_price_falls_back_below_target()
    // 112 (Up), 108 (Up) → open; set Down → 107 → TargetHit{107}
#[tokio::test] async fn short_armed_then_up_class_closes()
    // seeded short entry 100 stop 110 target 90: 88 (Down) → open; set Up → 89 → TargetHit{89}
#[tokio::test] async fn no_trend_reading_never_closes_even_when_armed()
    // NoTrend source, trades 112, 115 → open
#[tokio::test] async fn neutral_class_does_not_close_an_armed_long()
#[tokio::test] async fn reaching_the_target_alone_no_longer_closes()
    // 110, 115 with Up → open (the old backstop is gone)
#[tokio::test] async fn a_wrong_side_target_arms_on_the_first_trade()
    // seeded long target 95 (below entry): trade 101 with Down → TargetHit{101}
```

- [ ] **Step 2: `cargo test -p execution` — RED** (the existing `a_target_hit_on_a_position_already_gone_reports_nothing_after_closed` must be re-driven: give it a `ScriptedTrend(Down)` and a trade above the target — keep its I-17 assertion)
- [ ] **Step 3: Implement the loop body per spec §7**
- [ ] **Step 4: `cargo test -p execution` — GREEN; `cargo clippy -p execution` clean**

---

## Task 5 — L5 `state_store` + `visualizer_server` DTOs

**Files:**
- Modify: `crates/state_store/src/dto.rs` (`TradeDecisionDto.target`, `SignalEventDto::CbZoneEntry.target`)
- Modify: `crates/visualizer_server/src/dto.rs` (`SignalEventDto::CbZoneEntry.target`; the decision DTO there if one mirrors `TradeDecision` — check `grep -n main_levels crates/visualizer_server/src/dto.rs`)
- Test: both files' round-trip tests (DB-free unit tests; the DB-backed suites just need `TEST_DATABASE_URL` as in the entry points)

**Interfaces:**
- Produces: `#[serde(default, skip_serializing_if = "Option::is_none")] target: Option<Decimal>` on `TradeDecisionDto` and on both `CbZoneEntry` DTO variants; `From`/`TryFrom` carry it.

- [ ] **Step 1: RED**

```rust
// state_store
#[test] fn trade_decision_dto_round_trips_target()                 // Some(123.4) survives JSON → back
#[test] fn trade_decision_json_without_target_decodes_to_none()     // hand-written JSON string lacking the key
#[test] fn cb_zone_entry_dto_round_trips_target_and_decodes_without_it()
// visualizer_server
#[test] fn cb_zone_entry_dto_carries_target_and_omits_it_when_none()
```

- [ ] **Step 2: `cargo test -p state_store -p visualizer_server` (DB on 5437) — RED**
- [ ] **Step 3: Implement**
- [ ] **Step 4: GREEN**

---

## Task 6 — Orchestrator: wire the slot, pass the target, log the arming

**Files:**
- Modify: `crates/orchestrator/src/system.rs` (`cb_zone_signal_config` without `trend`; one `Arc<TrendSlot>` per boot; `cb_pipeline.with_trend(TrendParams::default(), slot.clone())`; `Executor::new(..).with_trend_source(Box::new(SlotTrend(slot)))`; `run_signal_decision_task` open decision `target`; boot log lines)
- Modify: `crates/orchestrator/src/tests.rs` (`cb_zone_pipeline` helper: config without `trend`, `.with_trend(..)` on the pipeline; every `TradeDecision` literal/`FakeExecutorSpy` assertion gains `target`)

**Interfaces:**
- Produces: `struct SlotTrend(Arc<TrendSlot>)` implementing `execution::TrendSource` by `slot.latest(pair).map(|(_, r)| r)`.
- Decision task: `target: match &event { SignalEvent::CbZoneEntry { target, .. } => *target, _ => None }` on the open; `None` on the reversal's close leg.

- [ ] **Step 1: RED — `tests.rs`**

```rust
#[tokio::test] async fn a_cb_zone_entry_opens_with_the_events_target()         // FakeExecutorSpy sees TradeDecision.target == Some(t)
#[tokio::test] async fn a_reversal_close_leg_carries_no_target()
#[tokio::test] async fn a_sar_flip_opens_with_no_target()
#[test] fn cb_zone_signal_config_has_no_trend_params()                           // update the existing config test
#[tokio::test] async fn the_cb_pipeline_feeds_the_slot_the_executor_reads()      // build pipeline + slot as boot does, feed 30 buckets, assert `SlotTrend(slot).latest(&pair).is_some()`
```

- [ ] **Step 2: `cargo test -p orchestrator --lib` — RED**
- [ ] **Step 3: Implement**; boot prints `trend-flip exit armed for {pair}: class from the CB pipeline` when CB is armed, and `trend-flip exit NOT armed (no CB pipeline): positions close on stop/reversal only` otherwise.
- [ ] **Step 4: `cargo test -p orchestrator --lib` — GREEN; `cargo clippy --workspace` clean**

---

## Task 7 — Docker gate, docs

- [ ] **Step 1: `docker compose -p cbx-test -f docker-compose.yml -f <scratch>/ports.yml run --build --rm test` on a fresh volume — green, count ≥ 1407 + new**
- [ ] **Step 2: `git status` — no root-owned files in the worktree ([project-container-root-files])**
- [ ] **Step 3: External docs:** spec status → `implemented 2026-10-18 on branch cb-target-trend-exit (uncommitted)`; entry spec §5/§6 note "trend now computed by the pipeline (see target+trend exit spec §6)"; `UNFINISHED.md`: tick "Exits are still the placeholders" → new section for this plan (commit gate, live check, stop still placeholder, `MIN_RR` question); plan status line.
- [ ] **Step 4: Stage everything, describe, wait for the user's commit confirmation** ([feedback-confirm-before-commit]).
