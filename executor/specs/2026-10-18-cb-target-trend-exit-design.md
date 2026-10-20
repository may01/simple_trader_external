# CB target + trend-flip exit (replaces the placeholder take-profit) — Design Spec

Date: 2026-10-18
Status: **implemented 2026-10-18 on branch `cb-target-trend-exit` (squashed into `close-marker-pnl` `4f5ede3`, in `layer-implementation` = `release_001` @ `1689dc5` since 2026-10-20) — host loop green (signals 83, local_analysis 33, execution 110, orchestrator 89, state_store 20+96, visualizer_server 17+58); Docker gate 1444/0 on a fresh volume; operator live check pending**
Target project: `trade_executor` (worktree `layer-implementation`, on top of branch `cb-zone-entry-signal`) — L2 `signals` crate (`CbZoneEntryCheck` reads two more names, event carries the target), L2 `local_analysis` (`DecisionContext`/`SignalBuilder` take an explicit target), L4 `execution` (position stores the extreme price, `run_advisor_loop` evaluates the new close rule, computes the trend class), L5 `state_store` (decision DTO field), orchestrator (passes the target through). No `main/` change: `{tf}_cbnc_high/low` are already broadcast (`main/tests/test_cb_broadcast.py` PLAIN list). No schema change.
Supersedes: the placeholder target (`nearest_in_direction` / `NOMINAL_TARGET_PCT`) as the *close* rule for every position; the stop stays the 1 % placeholder.
Related: [2026-10-18-cb-zone-entry-signal-design.md](2026-10-18-cb-zone-entry-signal-design.md) (the open signal, the trend class §5), [2026-09-22-position-management-design.md](2026-09-22-position-management-design.md) D7 (take-profit is a local trigger evaluated in `run_advisor_loop`), main/ `external/docs/superpowers/specs/2026-10-05-cb-markers-main-flow-design.md` (what `cbnc_*` is: the candle-bound model served on the *forming* candle).

## 1. Why

The CB zone entry opens positions; the close is still the placeholder take-profit at the nearest level (or +3 %). The forming-candle bound (`cbnc`) on the zone's own tf is the model's estimate of how far the current candle reaches; the entry's trend class says whether the move is still running. This spec makes the position remember the far bound at open and close on the first trend reversal *after* price has traded through it — ride the move past the model's bound, exit when it turns.

## 2. Decisions taken by the user (2026-10-18)

| Question | Answer |
|---|---|
| Target stored at open | The **opposite** forming-candle (not-closed) bound of the firing tf: long → `{tf}_cbnc_high`, short → `{tf}_cbnc_low`. |
| Close long | While long and **max traded price since open > target** and the 1-min trade-MA trend class is **down** → close. |
| Close short | While short and **min traded price since open < target** and the trend class is **up** → close. |
| "Since open" | The extreme (high-water / low-water mark) of every trade seen since the position opened; once armed it stays armed. |
| Trend flip before the extreme reaches the target | Nothing. The position rides to its stop or to a reversal signal. |
| Reaching the target alone | Nothing. The old "close at target price" backstop goes away. |

Calls made by the author (not asked of the user; flagged for review in §12):

| Question | Call |
|---|---|
| Target missing at fire time (`{tf}_cbnc_*` absent/expired) | The zone entry **does not fire** for that tf — same as an absent zone. A position without a target has no close rule. |
| Which positions the new close rule governs | **Every** position the executor holds: there is one close flow (D7), and a position opened from any other path keeps getting its `take_profit_price` from the existing builder fallback, now read as an arming level rather than a close. |
| Where the trend class is computed for the close | **Nowhere new — the user's decision (2026-10-18): the class already computed for the open is reused.** The computation moves from `CbZoneEntryCheck` up into `SignalPipeline`, which computes it once per trade, hands it to the checks on `MarketDataWindow::trend` and publishes the latest reading per pair into a shared slot (`TrendSlot`) the executor reads. `execution` reads it through a `TrendSource` trait (injected like `position_advisor`), implemented by the slot. Not a new `SignalEvent`: the close needs the position's side, target and extreme, which only the executor holds, and D7 already places the target trigger in `run_advisor_loop`. |
| When the extreme is tracked and the rule evaluated | While the position's status is `Open` (the loop's existing scope). An `Opening` position with partial fills is protected by the stop watcher only, as today. |
| Persistence of the extreme | In memory only. After a restart the extreme restarts from the first trade seen; the position's `take_profit_price` is persisted already. |
| Close reason / event | Unchanged: `CloseReason::Target`, `PositionStateEvent::TargetHit { price }`. The log line adds extreme, target, class and slope. |
| Stored `signal_log` rows from the entry build without `target` | Tolerated: `target` is `Option` on the event and `serde(default)` on both DTOs, so the entry build may go live before this one. |
| Wrong-side target (long whose `cbnc_high` is already below the price at fire time) | Passed through. The extreme exceeds it from the first trade, so the position closes on the first down class — ride while it runs, exit on the first turn. The R:R gate (`reward = |close − open|`, `MIN_RR=0`) does not reject it. |

## 3. Scope

In: two more indicator names per tf in `CbZoneEntryCheck`; `target` on `SignalEvent::CbZoneEntry`, `TradeDecision`, `DecisionContext`, the decision DTO; `DefaultSignalBuilder` uses a given target; the trend class moves from the check to `SignalPipeline` (`MarketDataWindow::trend`, `TrendSlot`); `OpenPosition.extreme_price`; `TrendSource` on the executor and the new close rule in `run_advisor_loop`; tests; UNFINISHED/plan updates.

Out: a second trend computation anywhere; the stop (1 % placeholder stays; `cb_low`/`cb_high` stops are a later spec), sizing, the trailing-stop advisor (unchanged, still runs after the close check), persistence of the extreme, a chart marker for the target line (the position panel already shows `take_profit_price`), the SAR/Mock signals' own targets (they get the builder fallback, as today).

## 4. The data this reads

Per armed tf, two more names from `MarketDataWindow::indicators`: `{tf}_cbnc_high`, `{tf}_cbnc_low` (price; the forming-candle bound of the candle now open on that tf; re-published every 30 s and changes within the candle). `names_for(tf)` returns ten names; `required_indicators` lists thirty for three tfs.

## 5. Open: the target travels with the signal

1. `CbZoneEntryCheck` §6 step 3 gains, per side: `target = {tf}_cbnc_high` (long) / `{tf}_cbnc_low` (short) must be present, else the side is skipped (same handling as an absent zone). The value is read on the tick that fires — the forming-candle bound as of that moment, frozen from here on.
2. `SignalEvent::CbZoneEntry` gains `target: Option<Decimal>` — always `Some` from the check; `Option` only so rows stored before this field decode (§8). The `state_store` and `visualizer_server` `SignalEventDto::CbZoneEntry` mirror it (`signal_log` rows record what the position was given).
3. `run_signal_decision_task` builds the **open** `TradeDecision` with `target: event.target` for `CbZoneEntry`, `None` for every other event. The close leg of a reversal carries `None`.
4. `execution::TradeDecision` and `local_analysis::DecisionContext` gain `target: Option<Price>`; `handle_decision` copies it into the context. `TradeDecisionDto` gains `#[serde(default)] target: Option<Decimal>` so stored rows without it still decode.
5. `DefaultSignalBuilder::build_signal`, `DecisionKind::Open`: `close_price = ctx.target` when `Some`, else the existing nearest-level / nominal fallback. Stop unchanged.
6. Risk validation, sizing, `open_position`, `OpenPosition::new(.., take_profit_price, ..)` unchanged: the target lands in `take_profit_price`, which `position_state`/`position_log` already persist and the visualiser already shows.

## 6. One trend class, computed once per trade (moves out of the check)

The entry spec §5 put `trend_class(...)` inside `CbZoneEntryCheck::check`. It moves one level up so the open and the close read the same number from the same tick:

- `SignalPipeline::new(.., trend: Option<TrendParams>, trend_slot: Option<Arc<TrendSlot>>)` — when `trend` is `Some`, the pipeline calls `signals::trend::trend_class(&recent, trade.ts, &params)` once per trade, **before** dispatching to the checks, and stores the result in `MarketDataWindow::trend: Option<TrendReading>` (`None` = too few buckets, or trend not configured for this pipeline). The `recent` deque and its 6 000 bound are the ones the pipeline already keeps.
- `TrendSlot`: `signals::trend::TrendSlot` = `Mutex<HashMap<Pair, (Ts, TrendReading)>>` with `publish(pair, ts, reading)` and `latest(&pair) -> Option<(Ts, TrendReading)>`. The pipeline publishes every reading it computes (and clears the pair's entry when the result is `None`, so a stale class never outlives the trades that produced it).
- `CbZoneEntryCheck` loses its `trend: TrendParams` field and the call; §6 step 1 of the entry spec becomes "`window.trend` is `None` → return `None`". `SignalConfig::CbZoneEntry { tfs, min_interval }`; the params move to the pipeline's constructor (`TrendParams::default()`). Its unit tests build the window with `trend: Some(..)` by hand instead of feeding 5 min of trades; the trend fixtures themselves stay in `trend.rs`.
- Boot: the CB pipeline for a pair gets `trend: Some(TrendParams::default())` and the pair's slot. The SAR and Mock pipelines get `None` (nothing reads the class there); a deployment without the CB pipeline therefore never arms the trend-flip close — its positions ride to the stop or a reversal — stated in boot's log line.
- `execution` gains `pub trait TrendSource: Send + Sync { fn latest(&self, pair: &Pair, now: Ts) -> Option<TrendReading> }` and `Executor` holds a `Box<dyn TrendSource>` next to `position_advisor` (`Executor::with_trend_source`, default `NoTrend`). `TrendReading`/`TrendClass` come from the `signals` crate (a types-only dependency; `signals` depends on `market_data` only, no cycle). The orchestrator implements `TrendSource` as `SlotTrend(Arc<TrendSlot>)`; tests implement it with a `Mutex<Option<TrendReading>>`.
- Lag and staleness: the pipeline and `run_advisor_loop` subscribe to the same feed independently, so the advisor may read the reading from the previous trade — accepted, both see the same trades and the class is a 10 s-bucket quantity. But the stream that feeds the slot is pulled by the decision task, which can stall (DB write, exchange call, flat wait) or die, so `SlotTrend` bounds the reading's age against the trade being judged: older than **`TREND_READING_MAX_AGE` = 30 s** (three buckets, exchange time) → `None`, no close. (Review finding, 2026-10-18.)

## 7. Close: extreme past target, then the trend turns

`OpenPosition` gains `extreme_price: Option<Decimal>` — the highest trade seen while `Open` for a long, the lowest for a short; `None` until the first trade after the position is `Open`. `OpenPositionView` gains the same field (for the advisor's view; `DefaultPositionAdvisor` does not read it). Every other writer of the position works on a clone taken under the lock and written back after an exchange call (`take_if` → `store`); `store`/`store_and_report` therefore **merge** the stored extreme into the write-back (same position id; the more favourable wins) so an armed position never silently disarms. (Review finding, 2026-10-18.)

`run_advisor_loop` per trade `(price, ts)`:

1. `reading = self.trend_source.latest(&pair)` — the class the signal pipeline computed for this pair's latest trade (§6); `None` until the pipeline has 30 buckets, or forever in a deployment without the CB pipeline.
2. Snapshot the `Open` position as today. If none → continue.
3. Update `extreme_price` under the positions lock: long `max(extreme, price)`, short `min(extreme, price)`.
4. **Armed** = long: `extreme > take_profit_price`; short: `extreme < take_profit_price` (strict, as the user wrote it).
5. **Close** = armed ∧ `reading.class` = `Down` (long) / `Up` (short). No reading → no close. Neutral → no close.
6. Close → `do_close(&pair, price, CloseReason::Target)`; on `Ok(true)` report `TargetHit { pair, id, price }` and print `target exit {pair}: side, target, extreme, price, class, slope, sigma`. `Ok(false)` (already closing) → nothing. `Err` → the existing Critical alert. Then `continue` (no stop move on the same tick), as today.
7. Not closed → the trailing-stop advisor runs as today.

## 8. Orchestrator and config

- Boot builds one `Arc<TrendSlot>` shared by every pair's CB pipeline and the `Executor` (`Executor::new(.., trend_source: Box<dyn TrendSource>)`). No new env; `TrendParams::default()` as today.
- `run_signal_decision_task`: the open decision's `target` from the event (§5.3). The `signal_log` persist already records the whole event.
- Boot's CB armed line names `cbnc_high/low` among the names read.

## 9. Persistence and DTOs

- `state_store::dto::TradeDecisionDto.target: Option<Decimal>` (`serde(default)`), round-tripped.
- `state_store::dto::SignalEventDto::CbZoneEntry.target: Option<Decimal>` with `serde(default)`, and the `visualizer_server` mirror likewise. The domain event `SignalEvent::CbZoneEntry.target` is also `Option<Decimal>`: the check never emits `None` (an absent bound skips the side, §5.1), but a `signal_log` row written by the `cb-zone-entry-signal` build *before* this change — the entry spec's live check may run first — must still decode, and a decode fallback that invents a price would be worse than `None`. `run_signal_decision_task` passes the `Option` straight through to `TradeDecision.target`; a `None` there (old rows replayed, never a live fire) falls back to the builder's existing target, exactly as a non-CB decision does.
- `position_state`/`position_log`: unchanged (`take_profit_price` already there; `extreme_price` is not persisted).

## 10. Compose (L9)

Unchanged. The live executor is not recreated by this work; the operator restarts it.

## 11. Error handling

A missing target skips the side at the check (never a decision without a target from this signal). No reading in the slot means no close this tick, never a guessed class. `do_close` errors alert at Critical as the target backstop does today. A decode of an old decision row without `target` yields `None`.

## 12. Testing

**`signals` unit** (host): `names_for` lists ten names, `required_indicators` thirty for three tfs; rule 1/rule 2 events carry `target == Some({tf}_cbnc_high)` (long) / `Some({tf}_cbnc_low)` (short); absent `cbnc_*` → that side does not fire while the other side with a target still can; the check's existing tests set `window.trend` by hand (up/down/neutral/`None`) and keep their assertions; pipeline: with `trend: Some(..)` the window handed to a check carries the reading `trend_class` gives on the same deque, and the slot holds `(trade.ts, reading)` after the tick and is cleared when the reading is `None`; with `trend: None` the window's `trend` is `None` and the slot untouched; `TrendSlot::latest` per pair.

**`local_analysis` unit**: `build_signal` Open with `ctx.target = Some(t)` → `close_price == t` regardless of levels; `None` → existing behaviour (nearest level, nominal fallback) unchanged.

**`execution` unit** (`tests.rs`, fake feed + spy account + a scripted `TrendSource`, the existing `run_advisor_loop` tests' shape):
- long, trades rising through the target with an up class → no close; extreme recorded above target;
- long, armed, source turns down → one `TargetHit` close at the trade's price, reason `target`, `do_close` once;
- long, never above target, class down → no close;
- long, extreme above target then price falls back below target, class down → closes (armed stays armed);
- short mirrored (min below target, class up);
- source `None` → no close even when armed;
- neutral class → no close;
- a position seeded `Open` with no `extreme_price` arms from the first trade;
- the old price-only target close is gone: price ≥ target with an up/neutral class does not close.
- `OpenPosition::new` starts `extreme_price = None`.

**Orchestrator unit** (`tests.rs`): a `CbZoneEntry` event with `target` opens with `TradeDecision.target == Some(target)`; a reversal's close leg has `target: None`; the SAR/Mock paths pass `None`.

**DTO round-trips** (`state_store`, `visualizer_server`): `TradeDecisionDto` with and without `target` (a JSON blob lacking the key decodes to `None`); `SignalEventDto::CbZoneEntry` with `target`.

**Docker gate**: `docker compose -p cbx-test … run --build --rm test` on a fresh volume, isolated project ([project-executor-test-isolation]).

**Live check (operator, human-gated)**: after a restart on the new build, a `cb_zone_*` open shows `take_profit_price` equal to that tf's `cbnc` bound at fire time in the position panel; a position whose price traded through the target closes with `close_reason = target` on the first down (long) / up (short) class, and the log line names the extreme and the class.

## 13. Acceptance criteria

1. Every position opened from `cb_zone_{tf}` has `take_profit_price == {tf}_cbnc_high` (long) / `{tf}_cbnc_low` (short) as of the firing tick; a tf whose bound is absent does not fire.
2. No position closes on price alone: reaching or passing the target without the opposite trend class leaves it open.
3. A position closes with reason `target` exactly when its extreme has passed the target and the trend class is opposite to its side, at the first such trade.
4. The trend class the close uses **is** the one the pipeline computed for the open: one `trend_class` call per trade per pair, read by the check from the window and by the executor from the slot.
5. Stop watcher, trailing stop, reversal-on-opposite-signal, force close, main/ close: unchanged behaviour and tests.
6. Docker gate green; test count ≥ baseline + new tests.

## 14. Open questions / follow-ups (not blocking)

- `MIN_RR` in the live env: the §2 "wrong-side target passes" claim holds for the compose default `0`. With `MIN_RR > 0` a near/behind target fails stage 1 of `DefaultRiskValidator` and stage 2 looks for a level-supported stop; `DefaultRiskValidator` now takes the side from the **stop** (`stop < open` = long), not from the target, so a wrong-side target can no longer nudge a long's stop above its entry (review finding, 2026-10-18; `risk.rs` test). If no candidate clears the bar the open is refused `NotPlaced` after the check consumed the zone key — a check-side guard (skip a side whose target is not beyond the price) is the follow-up if that bites. Awaiting the user's answer on the live value; the plan assumes `0`.

- Stops from `cb_low`/`cb_high` (UNFINISHED "CB-bound exits") — next spec.
- Whether the extreme should be persisted / rebuilt from stored trades after a restart.
- Whether a position should remember its tf and re-read the *current* `cbnc` bound instead of freezing the value at open (user chose frozen).
