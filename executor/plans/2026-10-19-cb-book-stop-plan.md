# CB Zone Stop From the Order Book — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan layer-by-layer. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A position opened from a CB zone gets its stop from the live order book — the price the book would be pushed to if the current |buy − sell| flow kept going for the minutes the zone episode has left (frozen expected minutes − in-zone streak + 1) — instead of the 1 % placeholder; opens are sized under a notional cap so a tight stop is never refused.

**Architecture:** `CbZoneEntryCheck` keeps a per-`(tf, side)` in-zone streak (bounded by the zone value), and at fire time computes the stop with a pure `cb_stop` module (vol rate from the trade window, `depletion::project_target_price` walked on the adverse side of `feed.order_book`) and puts it on the event. The orchestrator passes it to `TradeDecision.stop` → `DecisionContext.stop`; `DefaultSignalBuilder` uses it when strictly adverse to the real `open_price`, else the placeholder. `execution::sizing` gains the notional cap. DTOs mirror the new fields with `serde(default)`. Env `CB_STOP_EXPECTED_POINTS` gates the feature; blank = off.

**Tech stack:** Rust workspace (`tokio`, `rust_decimal`, `serde`, `sqlx`), Docker Compose. Executor worktree `trade_executor/.worktrees/layer-implementation`, branch `cb-book-stop` off `close-marker-pnl` (`4f5ede3`).

**Spec:** [`external/executor/specs/2026-10-19-cb-book-stop-design.md`](../specs/2026-10-19-cb-book-stop-design.md). § refs point into it. User decisions in §14.

**Layer taxonomy:** `layer-first-planning`'s principles over `trade_executor`'s real layers: L2 `signals` (pure `cb_stop` → check) → L2 `local_analysis` → L4 `execution` → L5 `state_store` / `visualizer_server` DTOs → orchestrator (config, boot, dispatch, compose) → docs. Each layer's host tests green before the next; Docker gate at the end.

---

## Global Constraints

- **Branch:** `cb-book-stop` from `close-marker-pnl` (`4f5ede3`, committed). Never commit without explicit user confirmation: stage, describe, wait.
- **No implementation code in this plan** — signatures and test descriptions only.
- **The stop never blocks a fire** (§7, §11): every skip collapses to `stop: None` + one `eprintln!` line; the builder falls back to `PLACEHOLDER_STOP_LOSS_PCT`.
- **Rule values (§2, §6):** `minutes_left = max(E − streak, 0) + buffer`, buffer default `1`; vol window default `300 s`; rate = adverse-side qty (sells for a long, buys for a short) per covered minute — user decision 2026-10-20, was `|Σbuy − Σsell| / window_minutes`; long walks **bids** downward (signed rate negative), short walks **asks** upward; stop = the reached level's own price; stop must be strictly adverse to the last trade at the check and to `open_price` at the builder.
- **Streak (§5):** per `(tf, side)` run `{zone, start_minute, last_minute}` in exchange-time minutes; a new zone value, or a gap > 1 minute, starts a new run; `streak_at(m) = last − start + 1` if `last ≥ m − 1` else 0.
- **Sizing (§10, user decision a):** `size = min(RISK_PER_TRADE / dist, free_quote × MAX_NOTIONAL_FRACTION / open_price)` before lot rounding; `within_account_limits` stays as a belt. Applies to every open.
- **Env (§10):** `CB_STOP_EXPECTED_POINTS=15:L/S;60:L/S;240:L/S` (blank = off), `CB_STOP_VOL_WINDOW_SECS` (default 300, < 60 is an error), `CB_STOP_BUFFER_MINUTES` (default 1). Armed tf without a value → config error; a tf outside 15/60/240 → error; set with `CB_ZONE_SIGNAL_TFS` blank → accepted, boot line says ignored.
- **Compose default** for `CB_STOP_EXPECTED_POINTS` stays blank until `external/docs/superpowers/experiment/results/cb_zone_run_stats_results.md` exists; Task 6 copies its line.
- **Stored rows decode (§9):** every new DTO field is `Option` + `serde(default)` (`inzone_streak: u32` defaults to 0).
- **`SignalPipeline::new`, `Executor::new`, `CbZoneEntryCheck::new` keep their signatures** — new inputs via builder methods (`with_stop`), as `with_trend` did.
- **Live executor is not recreated by this work** — operator restarts it.
- **Test DB isolation:** host loop against throw-away postgres `-p cbs-test` on 5437 (`ports.yml` override); final gate `docker compose -p cbs-test … run --build --rm test` on a fresh volume ([project-executor-test-isolation]).

## Review Focus

1. **Stop crosses the entry between fire and open.** Long fired with last trade 12.000, bids walked to 11.998, entry priced at mid 11.997 after a reversal's flat wait → stop ≥ open. Expected: placeholder, log line; never a long with a stop above its entry (`DefaultRiskValidator` would read it as a short). → Task 3 builder test.
2. **Decision task stalls, queued trades.** `check()` runs on a stale window against the live book. Expected: the stop is still strictly adverse to the *window's* last trade and the builder re-check catches the rest; no panic on an empty book. → Task 1 (`NotAdverse`, `DepthExhausted`), Task 2 (empty `ChannelFeed` book → `stop: None`).
3. **Fractional `E` and `streak ≥ E`.** `E = 3.5, streak = 7` → `minutes_left = 1` (buffer only), still walks the book. Expected: a stop one buffer-minute of flow away, never zero minutes. → Task 1.
4. **Cap bites at exactly the limit and at zero free balance.** Expected: equal-to-limit places; free 0 → size 0 → refused `below min notional after lot rounding`, not a panic or a negative size. → Task 4.
5. **Zone value changes while in zone across a tf close.** Expected: streak restarts at 1 on the new zone, so `minutes_left ≈ E`. → Task 1 `Streaks` test.

---

## Docker Entry Points

```bash
# host inner loop
cargo test -p signals --lib
cargo test -p local_analysis
cargo test -p execution
cargo test -p orchestrator --lib
docker compose -p cbs-test -f docker-compose.yml -f <scratch>/ports.yml up -d --wait postgres   # ports.yml: postgres 5437, no other ports
TEST_DATABASE_URL=postgres://executor:executor@127.0.0.1:5437/trader cargo test -p signals -p state_store -p visualizer_server -p orchestrator
docker compose -p cbs-test -f docker-compose.yml -f <scratch>/ports.yml down -v

# final gate
docker compose -p cbs-test -f docker-compose.yml -f <scratch>/ports.yml run --build --rm test

# paper run with the stop armed (operator shell, after the results doc exists)
CB_STOP_EXPECTED_POINTS="15:L/S;60:L/S;240:L/S" EXECUTION_MODE=paper docker compose -p cbov-check up -d --no-build executor
```

Verified: [ ] baseline `cargo test --workspace` count on `4f5ede3` recorded before Task 1 (host, with the test DB up).

---

## File Structure

- `crates/local_analysis/signals/src/cb_stop.rs` — **new**, pure: `Streaks`, `CbStopParams`, `vol_rate_abs`, `compute_stop`, `StopReading`, `StopSkip`.
- `crates/local_analysis/signals/src/checks/cb_zone_entry.rs` — streak update step, `with_stop`, stop at fire time, event fields.
- `crates/local_analysis/signals/src/types.rs` — `SignalConfig::CbZoneEntry.stop: Option<CbStopParams>`, `SignalEvent::CbZoneEntry` new fields; `factory.rs` passes `feed`; `lib.rs` re-exports.
- `crates/local_analysis/src/types.rs`, `builder.rs` — `DecisionContext.stop`, adverse re-check.
- `crates/execution/src/types.rs`, `engine.rs`, `sizing.rs` — `TradeDecision.stop`, context copy, notional cap.
- `crates/state_store/src/dto.rs`, `crates/visualizer_server/src/dto.rs` — mirrors.
- `crates/orchestrator/src/config.rs`, `system.rs`, `tests.rs`, `docker-compose.yml` — env, boot, dispatch.
- `external/executor/UNFINISHED.md`, spec status — docs.

---

## Task 1 — L2 `signals`: pure `cb_stop` module

**Files:**
- Create: `crates/local_analysis/signals/src/cb_stop.rs`
- Modify: `crates/local_analysis/signals/src/lib.rs` (`mod cb_stop; pub use cb_stop::{CbStopParams, StopReading, StopSkip};`)
- Test: `cb_stop.rs` `#[cfg(test)]`

**Interfaces:**
- Consumes: `crate::depletion::project_target_price(net_rate_per_min: Decimal, horizon_minutes: Decimal, book: &OrderBookSnapshot, current_price: Decimal) -> Option<(Decimal, Side)>`; `market_data::{OrderBookSnapshot, TradeTick, Side, Ts}`.
- Produces:

```rust
#[derive(Debug, Clone, PartialEq)]
pub struct CbStopParams {
    /// (tf_minutes, side) -> E
    pub expected_points: HashMap<(u32, Side), Decimal>,
    pub vol_window: Duration,
    pub buffer_minutes: Decimal,
}
impl CbStopParams { pub fn expected(&self, tf: u32, side: Side) -> Option<Decimal>; }

#[derive(Debug, Default)]
pub struct Streaks { /* HashMap<(u32, Side), Run { zone: Decimal, start_minute: u64, last_minute: u64 }> */ }
impl Streaks {
    pub fn observe(&mut self, tf: u32, side: Side, zone: Option<Decimal>, in_zone: bool, now: Ts);
    pub fn streak_at(&self, tf: u32, side: Side, now: Ts) -> u32;
}
pub fn minute_of(ts: Ts) -> u64;                                   // ts.0 / 60_000

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct StopReading { pub stop: Decimal, pub streak: u32, pub minutes_left: Decimal, pub vol_rate: Decimal, pub book_ts: Ts, pub levels_walked: usize }

#[derive(Debug, Clone, PartialEq)]
pub enum StopSkip { NoTrades, ZeroRate, DepthExhausted { cumulative_target: Decimal, levels: usize }, NotAdverse { level: Decimal, price: Decimal } }
impl std::fmt::Display for StopSkip { /* one line per variant, for the log */ }

pub fn vol_rate_abs(trades: &[TradeTick], now: Ts, window: Duration) -> Result<Decimal, StopSkip>;
pub fn compute_stop(side: Side, streak: u32, expected: Decimal, buffer: Decimal, vol_rate: Decimal, book: &OrderBookSnapshot, price: Decimal) -> Result<StopReading, StopSkip>;
```

`levels_walked` = count of levels beyond `price` on the walked side up to and including the reached one (recomputed from the sorted, filtered side — `project_target_price` does not expose it; a small private helper mirrors its filter+sort, or `compute_stop` re-walks to count. Builder's choice; the test pins the number).

- [ ] **Step 1: RED — `Streaks` tests**
  - `three_adjacent_in_zone_minutes_give_streak_3` (observe at minutes m, m+1, m+2 with the same zone → `streak_at(m+2) == 3`).
  - `several_trades_in_one_minute_count_once`.
  - `a_gap_of_one_minute_restarts` (m, m+2 → streak 1).
  - `a_zone_value_change_restarts_even_when_adjacent` (m zone 12.00, m+1 zone 12.05 → streak 1).
  - `not_in_zone_leaves_the_run_and_it_still_counts_one_minute_later` (in at m, out at m+1 → `streak_at(m+1) == 1`, `streak_at(m+2) == 0`).
  - `absent_zone_counts_as_not_in_zone`.
  - `tf_and_side_are_independent`.
- [ ] **Step 2: RED — `vol_rate_abs` tests**: buys 6, sells 2 over 5 min → `0.8`/min; only trades inside `[now − window, now]` count; no trade in window → `Err(NoTrades)`; equal buy/sell → `Err(ZeroRate)`.
- [ ] **Step 3: RED — `compute_stop` tests** (spec §12 numbers): long, bids `[99.9×5, 99.8×5, 99.7×10]`, rate 2, E 4, streak 1, buffer 1 → `minutes_left 4`, target 8 → `stop 99.8`, `levels_walked 2`; short mirrored on asks `[100.1×5, 100.2×5]` → `100.2`; streak 7 ≥ E 3.5 → `minutes_left == buffer`; fractional E 3.5 streak 1 → `3.5`; depth exhausted → `Err(DepthExhausted { cumulative_target: 8, levels: 3 })`; rate 0 → `Err(ZeroRate)`; bid at the trade price holding everything → `Err(NotAdverse)`; unsorted book gives the same stop.
- [ ] **Step 4: Run RED** — `cargo test -p signals --lib cb_stop` → compile errors.
- [ ] **Step 5: Implement `cb_stop.rs`** per the interface.
- [ ] **Step 6: Run GREEN** — the ~19 tests pass; `cargo test -p signals --lib` unchanged elsewhere.
- [ ] **Step 7: Stage and describe** — `feat(signals): cb_stop — in-zone streaks and the order-book stop`. Wait for the user.

## Task 2 — L2 `signals`: the check computes the stop at fire time; event carries it

**Files:**
- Modify: `crates/local_analysis/signals/src/types.rs` (`SignalConfig::CbZoneEntry { tfs, min_interval, stop: Option<CbStopParams> }`; `SignalEvent::CbZoneEntry` gains `stop: Option<Decimal>`, `inzone_streak: u32`, `stop_minutes: Option<Decimal>`, `stop_vol_rate: Option<Decimal>` after `target`)
- Modify: `crates/local_analysis/signals/src/checks/cb_zone_entry.rs` (`State.streaks: Streaks`; `with_stop`; step 0 + step 7)
- Modify: `crates/local_analysis/signals/src/factory.rs` (`CbZoneEntry { tfs, min_interval, stop }` → `CbZoneEntryCheck::new(tfs, min_interval)` then `.with_stop(params, feed)` when `Some`)
- Test: `cb_zone_entry.rs` tests; `types.rs` test that builds the event literal gains the fields; every struct-literal `SignalEvent::CbZoneEntry` in the workspace gains `stop: None, inzone_streak: 0, stop_minutes: None, stop_vol_rate: None` (orchestrator tests, DTO tests — grep).

**Interfaces:**
- Consumes: Task 1.
- Produces: `impl CbZoneEntryCheck { pub fn with_stop(self, params: CbStopParams, feed: Arc<dyn MarketDataFeed>) -> Self }`; the four event fields above. `required_indicators` unchanged (zone + inzone are already read).

- [ ] **Step 1: RED — check tests** (existing window-by-hand helpers + a `BookFeed` stub implementing `MarketDataFeed` with a scripted `OrderBookSnapshot` and an `order_book` call counter):
  - `armed_stop_rides_on_the_event` (rule 1 long, book from Task 1's long case, E 4 for (15, Buy), streak observed 1 → `stop == Some(99.8)`, `inzone_streak == 1`, `stop_minutes == Some(4)`, `stop_vol_rate == Some(rate)`).
  - `unarmed_check_counts_the_streak_but_sets_no_stop`.
  - `empty_book_fires_with_stop_none` (skip → `DepthExhausted`, event still fires).
  - `the_streak_of_the_firing_tf_and_side_is_used` (two tfs in zone with different streaks; highest tf fires; its own streak on the event).
  - `rule_2_fire_uses_the_run_that_ended_last_minute`.
  - `the_book_is_read_once_per_fire_not_per_trade` (counter == number of fires).
  - `streak_update_runs_before_refire_suppression` (a trade blocked by the 60 s gap still advances the streak).
- [ ] **Step 2: Run RED.**
- [ ] **Step 3: Implement** — step 0 in `check()`: for every armed `(tf, side)` call `streaks.observe(tf, side, zone_reading, in_zone_reading, window.now)` under the state lock (move the lock acquisition up; the entry rules read indicators, not state). Step 7 after `best` is chosen and before `state.fired` is written: if armed, `vol_rate_abs(..)` → `feed.order_book(pair)` → `compute_stop(..)`; `Err(skip)` → `eprintln!("cb stop skipped {pair} {signal_id} {side:?}: {skip}")`.
- [ ] **Step 4: Run GREEN** — `cargo test -p signals --lib`; fix every struct literal the compiler flags.
- [ ] **Step 5: Stage and describe** — `feat(signals): CB zone entry computes the order-book stop at fire time`. Wait.

## Task 3 — L2 `local_analysis`: `DecisionContext.stop`, builder re-check

**Files:**
- Modify: `crates/local_analysis/src/types.rs` (`DecisionContext.stop: Option<Price>` after `target`)
- Modify: `crates/local_analysis/src/builder.rs` (`DecisionKind::Open`: stop selection + log line)
- Test: `builder.rs` tests; every `DecisionContext { .. }` literal in `local_analysis`, `execution`, `orchestrator` tests gains `stop: None`.

**Interfaces:**
- Produces: `DecisionContext.stop`; builder rule `stop_loss_price = ctx.stop.filter(|s| is_long && *s < open_price || !is_long && *s > open_price).unwrap_or(placeholder)`.

- [ ] **Step 1: RED** — `an_adverse_decision_stop_is_used_for_a_long` (`ctx.stop = Some(99.5)`, price 100 → 99.5); `_for_a_short` (100.5); `a_stop_on_or_beyond_the_entry_falls_back_to_the_placeholder` (long `Some(100)` and `Some(100.2)` → 99; short `Some(100)` → 101); `no_stop_keeps_the_placeholder`; existing stop tests unchanged.
- [ ] **Step 2: Run RED.** - [ ] **Step 3: Implement** (one `eprintln!` on fallback naming pair, side, stop, open price). - [ ] **Step 4: Run GREEN** — `cargo test -p local_analysis`. - [ ] **Step 5: Stage and describe** — `feat(local_analysis): builder takes the decision's stop when it is adverse to the entry`. Wait.

## Task 4 — L4 `execution`: `TradeDecision.stop`, notional-capped sizing

**Files:**
- Modify: `crates/execution/src/types.rs` (`TradeDecision.stop: Option<Decimal>` after `target`)
- Modify: `crates/execution/src/engine.rs` (`handle_decision` copies `stop` into the context; sizing block: fetch `account` **before** lot rounding, cap, then round, then the local-only cap and `within_account_limits` as today)
- Modify: `crates/execution/src/sizing.rs` (new fn + tests)
- Test: `sizing.rs` tests; `execution/src/tests.rs` (every `TradeDecision { .. }` literal gains `stop: None`; one new open test)

**Interfaces:**
- Produces: `pub fn cap_to_account_limits(size: Decimal, open_price: Decimal, account: &AccountState, quote_asset: &str, max_notional_fraction: Decimal) -> Option<Decimal>` — `None` when the quote balance is missing (refuse, as `within_account_limits` does), else `min(size, free × fraction / open_price)`.

- [ ] **Step 1: RED — `sizing` tests**: `a_size_over_the_cap_is_cut_to_it` (free 100 000, frac 0.5, price 12, size 10 000 → 4 166.666…); `a_size_under_the_cap_is_unchanged`; `exactly_at_the_cap_is_unchanged`; `missing_quote_balance_is_none`; `zero_free_balance_caps_to_zero`.
- [ ] **Step 2: RED — engine test** (`execution/src/tests.rs`, paper-style spy account with free 100 000): a decision whose builder stop is 2 ticks from the entry opens with `size == floor_to_step(cap / open_price)` and the log line prints `size capped` with both numbers; a decision with a 1 % stop opens with the uncapped size; free 0 → `NotPlaced` with the existing "below min notional" reason.
- [ ] **Step 3: Run RED.** - [ ] **Step 4: Implement.** - [ ] **Step 5: Run GREEN** — `cargo test -p execution` (128 + new). - [ ] **Step 6: Stage and describe** — `feat(execution): decision stop on the context; notional-capped sizing`. Wait.

## Task 5 — L5 DTOs: `state_store` and `visualizer_server`

**Files:**
- Modify: `crates/state_store/src/dto.rs` (`SignalEventDto::CbZoneEntry` + `TradeDecisionDto` new fields, `#[serde(default, skip_serializing_if = "Option::is_none")]` for the `Option`s, `#[serde(default)]` for `inzone_streak`; `From`/`TryFrom` arms)
- Modify: `crates/visualizer_server/src/dto.rs` (mirror, minus `ts`)
- Test: both files' round-trip tests (`with` and `without` the new keys — the existing "old row without target" tests are the pattern).

- [ ] **Step 1: RED** — `cb_zone_entry_round_trips_with_stop_fields`; `a_row_without_stop_fields_decodes_to_none_and_zero` (both crates); `trade_decision_round_trips_stop` and `_without_stop` (state_store).
- [ ] **Step 2: Run RED** (test DB up for `state_store`'s integration tests; the DTO tests are host-only). - [ ] **Step 3: Implement.** - [ ] **Step 4: Run GREEN** — `TEST_DATABASE_URL=… cargo test -p state_store -p visualizer_server`. - [ ] **Step 5: Stage and describe** — `feat(dto): stop fields on the CB zone event and the decision`. Wait.

## Task 6 — Orchestrator: env, boot, dispatch, compose

**Files:**
- Modify: `crates/orchestrator/src/config.rs` (`OrchestratorConfig.cb_stop: Option<CbStopParams>`; `parse_cb_stop(errors, cb_zone_tfs: &[u32]) -> Option<CbStopParams>`; the env-name list in the test helper)
- Modify: `crates/orchestrator/src/system.rs` (`SignalConfig::CbZoneEntry { .., stop: config.cb_stop.clone() }`; boot line; `run_signal_decision_task` open decision `stop: match &event { SignalEvent::CbZoneEntry { stop, .. } => *stop, _ => None }`, close leg `None`)
- Modify: `docker-compose.yml` (three env lines with comments; `CB_STOP_EXPECTED_POINTS=${CB_STOP_EXPECTED_POINTS:-}` until the results doc exists, then the frozen line)
- Test: `config.rs` tests, `orchestrator/src/tests.rs`

- [ ] **Step 1: RED — config tests**: `15:4/3.5;60:12/10;240:40/32` → map of six; `15:4/3.5` with `CB_ZONE_SIGNAL_TFS=15` → ok; with `15,60` → error "60 has no CB_STOP_EXPECTED_POINTS entry"; `5:1/1` → error; `15:0/3` → error; blank → `None`; `CB_STOP_VOL_WINDOW_SECS=30` → error; set with `CB_ZONE_SIGNAL_TFS` blank → `None` and no error (boot prints ignored).
- [ ] **Step 2: RED — decision task tests** (existing `FakeExecutorSpy` shape): a `CbZoneEntry` event with `stop: Some(s)` opens with `TradeDecision.stop == Some(s)`; the reversal's close leg has `stop: None`; SAR/Mock paths `None`; boot prints `cb stop armed: …` when set, `cb stop off` when not.
- [ ] **Step 3: Run RED.** - [ ] **Step 4: Implement** (parse: split `;` → `tf:L/S`; `Side::Buy` ← L, `Side::Sell` ← S). - [ ] **Step 5: Run GREEN** — `cargo test -p orchestrator --lib`; with the test DB, the full crate. - [ ] **Step 6: Compose** — add the three lines; **record the live book depth** here (MEXC spot: `spot@public.aggre.depth.v3.api.pb@100ms` + REST `/api/v3/depth` snapshot — read `ws.rs:887-965` for the `limit` used; write the number into spec §14). - [ ] **Step 7: Stage and describe** — `feat(orchestrator): CB_STOP_EXPECTED_POINTS env, boot wiring, decision stop`. Wait.

## Task 7 — Docker gate, docs, hand-over

- [ ] **Step 1: Final gate** — `docker compose -p cbs-test … run --build --rm test` on a fresh volume; record passed/failed against the baseline recorded under Docker Entry Points. Expected: 0 failed, count ≥ baseline + new tests.
- [ ] **Step 2: Fresh reviewer** on the branch diff (`caveman:cavecrew-reviewer` or `superpowers:requesting-code-review`), spec in hand; fix Important findings RED→GREEN.
- [ ] **Step 3: Docs** — spec status line (implemented, counts); `UNFINISHED.md` section "CB book stop" (commit pending, operator restart, results-doc dependency for the compose default, live-check counts to gather: `cb stop skipped` by reason, `size capped` count, book depth); memory `project_cb_book_stop` updated.
- [ ] **Step 4: When the run-stats results doc lands** — copy its `CB_STOP_EXPECTED_POINTS=…` line into the compose default; one config test pins that the compose default parses.
- [ ] **Step 5: Stage and describe the branch for commit.** Wait for the user. Operator restart (paper) is the user's.
