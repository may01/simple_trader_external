# CB zone stop from the 15-min candle: forming extreme ± trailing mean 1-min range — Design Spec

Date: 2026-10-20
Status: **implemented 2026-10-20 on branch `cb-candle-stop` (worktree `trade_executor/.worktrees/cb-candle-stop`, off `layer-implementation` = `release_001` @ `1689dc5`), commit `a6a5bc6` — host loop green (signals 131, local_analysis 40, execution 136, orchestrator 113, state_store 23+96, visualizer_server 17+58); Docker gate 1549/0 (pre-placeholder tree; final-tree rerun hit only the known flaky write_path test); live paper executor restarted on the image 2026-10-20 ~20:25Z**
Target project: `trade_executor` — L2 `signals` (`cb_stop` gains the candle rule and a 1-min bar aggregator; `CbZoneEntryCheck` computes it at fire time), orchestrator (env, config, boot), L5 DTO mirrors (two audit fields), L9 compose. No `main/` change, no schema change, no change to `local_analysis`, `execution`, sizing, the stop watcher or the exits.
Supersedes: the order-book stop ([2026-10-19-cb-book-stop-design.md](2026-10-19-cb-book-stop-design.md)) as the **default** stop for CB zone opens. The book stop stays in the code behind `CB_STOP_MODE=book`; the 1 % placeholder stays as the fallback for every skip and for every non-CB open.
Related: [run report 2026-10-20](../runs/2026-10-20-sl-15m-anchor-replay.md) (the replay this rule comes from), [2026-10-18-cb-zone-entry-signal-design.md](2026-10-18-cb-zone-entry-signal-design.md), [2026-10-18-cb-target-trend-exit-design.md](2026-10-18-cb-target-trend-exit-design.md).

## 1. Why — what the first paper day showed

The book stop went live 2026-10-20 01:44 (paper, LINKUSDT, `E = 15:2/2; 60:3/3; 240:4/4`). Over the next 21 h
(68 positions) it put the stop a **median 3 ticks** from the entry: the in-zone streak had usually already
consumed `E`, leaving `minutes_left = 1` buffer minute of adverse flow, which the book absorbs within 2–4
levels. Result: 46 of 68 positions stopped out, median hold 1.9 min, most inside the first 30 s — the stop
was measuring order-book noise, not the zone episode. The 16 opens whose book stop was *not* adverse fell
back to the 1 % placeholder and were the day's best trades (10 target exits, 6 reversal closes, 0 stops),
but at one-fifth size (`100 / 0.12`).

## 2. The investigation (replay, 2026-10-20)

Event-driven replay of the recorded trades and every recorded `CbZoneEntry` fire (skipped ones too), same
reversal/skip logic, stop watcher on trade price, trend-flip target exit (port of `signals::trend`), the
executor's sizing, paper = no fees. The "current" run reproduces the live positions (68/68 opens, stops
exact, same close reasons); exits differ only by the paper mid-fill (the live paper account fills the stop
market order at the mid, ~1 tick better than the crossing trade the replay uses). Numbers below are
sim-vs-sim under the same fill model. Full tables, gates and caveats: run report §3–§9.

| stop rule | trades | net | PF | win rate | stop-outs n / mean | median hold | median risk/trade | 90 % CI | P(net<0) |
|---|---|---|---|---|---|---|---|---|---|
| book stop (live), placeholder 1 % | 68 | +145 | 1.22 | 29 % | 46 / −13 | 1.9 min | 15 | [−267, +591] | 0.31 |
| book stop, placeholder 0.2 % | 71 | +1 087 | 2.04 | 28 % | 51 / −21 | 2.2 min | 15 | [+118, +2 155] | 0.03 |
| forming-15m extreme ± today's stop distance | 65 | +411 | 1.23 | 49 % | 31 / −58 | 6.5 min | 67 | [−641, +1 544] | 0.28 |
| forming-15m extreme ± 0 | 69 | +1 154 | 1.63 | 41 % | 41 / −45 | 4.0 min | 42 | [−49, +2 432] | 0.06 |
| forming-15m extreme ± 0.1 % | 67 | +2 048 | 1.90 | 61 % | 26 / −88 | 6.3 min | 92 | [+524, +3 607] | 0.01 |
| forming-15m extreme ± mean 1-min range, global | 67 | +1 964 | 1.85 | 61 % | 26 / −89 | 6.6 min | 96 | [+441, +3 515] | 0.02 |
| **forming-15m extreme ± mean 1-min range, trailing 60** | **67** | **+1 878** | **1.83** | **60 %** | **27 / −84** | **6.6 min** | **90** | **[+394, +3 376]** | **0.02** |
| forming-15m extreme ± mean 1-min body, trailing 60 | 67 | +1 824 | 1.82 | 55 % | 30 / −74 | 5.9 min | 74 | [+368, +3 333] | 0.02 |

1-min candle statistics over the window (1 237 closed candles): mean range 0.0130 (13 ticks, 0.107 % of
price), mean body 0.0084 (8 ticks); the trailing-60 mean range varied 7–30 ticks across the day.

### Rationale for the selected rule (user decision 2026-10-20)

- **Anchor on the forming 15-min candle's extreme, not the entry.** A zone entry is a bet that the current
  15-min candle holds its low (long) / high (short); the stop belongs beyond that level, not a few ticks
  under the fill. Every anchored variant lifted the win rate from 29 % to 41–69 % by letting 9–13 of the
  book-stop's stop-outs run to the trend-flip exit or the reversal.
- **Offset = trailing mean 1-min range, not a fixed fraction.** 0.1 % was the in-sample optimum of a sweep
  on the same 21 h (a hump 0 → 0.05 → 0.1 → 0.2 %) — it carries that day in its pocket. The mean 1-min range
  is the same number on this day (0.107 %) *by measurement*, and it re-scales itself when volatility
  changes. Trailing 60 closed candles = one hour, long enough to be a stable mean (60 samples), short enough
  to follow a regime change within the hour. It costs ~170 USDT vs the global mean on this sample (1–4 extra
  stop-outs in the quiet hours); accepted for the forward run as the rule that was not tuned on the day.
- **Range, not body.** Range includes the wicks that actually trip stops; body is ~⅔ of it and sat between
  the 0.05 % and 0.1 % rows.
- **What this is not.** Not a validated edge: one pair, 21 h, two 2–3 % moves, top-2 trades ≈ a third of
  every row's net, all CIs overlap the book-stop + 0.2 % row. It is a stop that measures the right thing
  (the candle, the current volatility) instead of order-book noise; the forward paper run is the test.

## 3. The rule

At fire time, for the firing side, with `now` = the trade's exchange time:

1. **anchor** = the low (long) / high (short) of every trade since the start of the current 15-min
   candle (`floor(now / 15 min) × 15 min`), the firing trade included.
2. **offset** = mean of `(high − low)` over the last **60 closed 1-min bars** before `now`'s minute
   (fewer when the executor has been up for less than an hour — see §5).
3. **stop** = `anchor − offset` (long) / `anchor + offset` (short).
4. The stop must be strictly adverse to the firing trade's price; otherwise no stop on the event (placeholder
   in the builder, one log line). With a positive offset this can only happen when every bar in the window
   has zero range.

Everything downstream is unchanged: the event carries `stop`; the decision carries it; the builder re-checks
it against the real `open_price` and falls back to the placeholder when it is not adverse; sizing is
`min(RISK_PER_TRADE / |entry − stop|, notional cap)`; the stop watcher closes on the first trade through it.

Calls made by the author (flagged for review):

| Question | Call |
|---|---|
| Where the 1-min bars come from | **The check aggregates them from the trades it sees** (`cb_stop::MinuteBars`, owned by the check's `State` like `Streaks`): per trade, update the forming minute's high/low; on a new minute, push the closed bar into a bounded deque (capacity = `range_candles` + 16). Not `MarketDataFeed::candles`: the in-memory candle cache (`CACHE_CAPACITY = 500`) holds every kline *update* (the forming candle is re-sent every ~2 s), i.e. ~15 min of history — not 60 closed candles. Not the `candle` table: `DefaultSignalBuilder`/the check stay I/O-free. Bars from trades equal the exchange's kline high/low; a minute with no trade has no bar (the exchange would publish a zero-range candle — negligible on LINKUSDT, and it biases the mean *up*, the wide direction). |
| Anchor from trades, not the 15-min kline | Same source as the bars (the forming bar + the closed bars since the 15-min boundary + the current trade); the 6 000-trade window is not needed for this — the bars accumulate. |
| Warm-up after a restart | Fewer than 60 closed bars → the mean over what exists (≥ 1 bar); the event's audit field says how many. Zero closed bars (a fire inside the first minute after boot) → skip → placeholder, logged. |
| Both modes configured | `CB_STOP_MODE` selects one: `candle` (default), `book`, `off`. In `candle` mode `CB_STOP_EXPECTED_POINTS` is parsed and ignored with a boot line; in `book` mode the candle env is ignored likewise. |
| Anchor tf | `CB_STOP_ANCHOR_MINUTES`, default 15, must divide 1 440 and be ≥ 1 (the replay only tested 15; the knob exists for the follow-up, not for tuning). |
| Lookback | `CB_STOP_RANGE_CANDLES`, default 60, ≥ 1. |
| Placeholder | **0.2 % (user decision 2026-10-20, was 1 %)** — `PLACEHOLDER_STOP_LOSS_PCT` in `local_analysis::builder`. The replay (run report §7) showed the 1 % fallback sized `100 / 0.12 ≈ 830` while every signal stop sat at the ~4 170 notional cap; at 0.2 % (`100 / 0.024`) the fallback lands on the same cap. A sizing change, not a stop change: on the replay day the fallback opens were the best trades (10 targets, 6 reversals, 0 stops) and 4 of them would now stop at 24 ticks before the reversal came (−446), against +1 008 from the 12 that run at full size. Applies to every fallback open (CB skip, non-adverse stop, SAR/Mock). |
| Streak | Still counted and stored (`inzone_streak`), unused by this rule. |

## 4. Scope

In: `signals::cb_stop` (`CbCandleStopParams`, `MinuteBars`, `compute_candle_stop`, `CandleStopReading`,
`CandleStopSkip`); `CbZoneEntryCheck::with_candle_stop`, bar observation in step 0, candle path in
`stop_for`; `SignalConfig::CbZoneEntry.candle_stop`; `SignalEvent::CbZoneEntry` gains `stop_anchor`,
`stop_offset` (both `Option`, `serde(default)` on the two DTO mirrors); orchestrator env/config/boot;
compose defaults; tests; UNFINISHED; this spec; the plan.

Out: `execution`, sizing (`local_analysis` changes one constant), the stop watcher, the target/trend-flip exit, the replay harness,
persistence of the bars across restarts, a chart line for the anchor, the placeholder value, any cap or
floor on the stop distance, `main/`.

## 5. The bars (`cb_stop::MinuteBars`)

```
struct Bar { minute: u64, high: Decimal, low: Decimal }
pub struct MinuteBars { closed: VecDeque<Bar>, forming: Option<Bar>, capacity: usize }

observe(price, ts)          // minute = ts / 60 000; same minute → extend forming; new minute → close forming, start new
mean_range(n, now)          // mean (high − low) over the last n closed bars with minute < now's minute; None when there are none
extreme_since(start_ms, side, price) // long: min low, short: max high, over closed bars with minute ≥ start_ms / 60 000, the forming bar, and `price`
```

A trade older than the forming minute (out-of-order tick) extends the forming bar when it belongs to that
minute and is otherwise ignored — bars never reopen. `observe` runs once per trade in `check()` step 0 while
the candle stop is armed (not when unarmed: nothing reads them).

## 6. The stop (`cb_stop::compute_candle_stop`, pure)

```
compute_candle_stop(side, now, price, bars, params) -> Result<CandleStopReading, CandleStopSkip>

anchor_start = now / (anchor_minutes × 60 000) × (anchor_minutes × 60 000)
anchor       = bars.extreme_since(anchor_start, side, price)
offset       = bars.mean_range(range_candles, now)?        // None → CandleStopSkip::NoClosedBars
stop         = long: anchor − offset | short: anchor + offset
adverse      = long: stop < price | short: stop > price     // else CandleStopSkip::NotAdverse { stop, price }
CandleStopReading { stop, anchor, offset, bars_used }
```

## 7. The check

- `CbZoneEntryCheck::with_candle_stop(params: CbCandleStopParams) -> Self` (no feed needed). `with_stop`
  (book) unchanged. Both armed → the candle rule wins (the orchestrator never arms both; belt and braces).
- Step 0 gains `state.bars.observe(price, now)` when the candle stop is armed.
- Step 7: `stop_for` tries the candle rule first; `Ok` → event `stop: Some`, `stop_anchor: Some`,
  `stop_offset: Some`, `stop_minutes: None`, `stop_vol_rate: None`; `Err(skip)` → `stop: None` and one
  `eprintln!` line `cb stop skipped {pair} cb_zone_{tf} {side}: {skip}` (same line as the book skips).
- The fire is never blocked by the stop (unchanged).

## 8. Event, DTOs

`SignalEvent::CbZoneEntry` gains `stop_anchor: Option<Decimal>`, `stop_offset: Option<Decimal>`;
`state_store::dto::SignalEventDto::CbZoneEntry` and the `visualizer_server` mirror gain the same with
`#[serde(default, skip_serializing_if = "Option::is_none")]`. Rows stored before this build decode to `None`.
`TradeDecisionDto` is unchanged (`stop` already travels).

## 9. Orchestrator, config, compose

| Var | Meaning | Default |
|---|---|---|
| `CB_STOP_MODE` | `candle` / `book` / `off` | `candle` |
| `CB_STOP_ANCHOR_MINUTES` | the anchor candle's tf | `15` |
| `CB_STOP_RANGE_CANDLES` | closed 1-min bars in the trailing mean | `60` |
| `CB_STOP_EXPECTED_POINTS`, `CB_STOP_VOL_WINDOW_SECS`, `CB_STOP_BUFFER_MINUTES` | book mode only | compose defaults unchanged |

`OrchestratorConfig` gains `cb_candle_stop: Option<CbCandleStopParams>` (`Some` iff mode = `candle` and the
CB zone signal is armed); `cb_stop` is `Some` iff mode = `book` and `CB_STOP_EXPECTED_POINTS` parses as
today. Errors: unknown mode; anchor minutes 0 or not dividing 1 440; range candles 0. Boot prints one of
`cb stop armed: candle mode, anchor {n} min, offset = mean range of the last {k} closed 1-min bars
(CB_STOP_MODE=candle)`, the existing book line, or `cb stop off (CB_STOP_MODE=off): the 1 % placeholder
stop applies`; and `cb stop ignored: …` when a mode's env is set while the CB zone signal is not armed.

The live executor is not recreated by this work; the operator restarts it with the rebuilt image.

## 10. Testing

**`cb_stop` unit** (host): `MinuteBars`: one minute of trades → one forming bar with the right high/low; a
trade in the next minute closes it; `mean_range(60, now)` over 3 closed bars with ranges 1/2/3 → 2; a
forming bar never counts; an out-of-order trade for the forming minute extends it, one for a closed minute
is ignored; the deque is bounded. `compute_candle_stop`: long with bars `[low 99.0 … ]` since the 15-min
boundary and mean range 0.5 → stop = 98.5; short mirrored on the high; the firing trade below every bar's
low becomes the anchor; bars before the 15-min boundary do not move the anchor; fewer than `range_candles`
closed bars → mean over what exists, `bars_used` says how many; no closed bars → `NoClosedBars`; all ranges
zero and price on the anchor → `NotAdverse`.

**`CbZoneEntryCheck` unit**: `with_candle_stop` armed → the event carries `stop == anchor ∓ offset`,
`stop_anchor`, `stop_offset`, `stop_minutes == None`; unarmed → all `None`, streak still counted; a fire in
the first minute (no closed bar) → fires with `stop: None`; the book arm alone still produces the book stop.

**Orchestrator unit**: `CB_STOP_MODE` blank → candle params with the defaults; `book` → `cb_stop` parsed as
before, `cb_candle_stop: None`; `off` → both `None`; `banana` → error; `CB_STOP_ANCHOR_MINUTES=7` → error;
`CB_STOP_RANGE_CANDLES=0` → error; `cb_zone_signal_config` carries the candle params; the decision task opens
with `TradeDecision.stop == event.stop` (existing test shape, candle-armed).

**DTO round-trips** (`state_store`, `visualizer_server`): with and without the two new keys.

**Docker gate**: `docker compose -p ccs-test … run --build --rm test` on a fresh volume, isolated project.

**Live check (operator, human-gated, paper):** after a restart, the boot line names candle mode; a
`cb_zone_*` open shows `current_stop_loss_price` = anchor ∓ offset in the position panel and the
`signal_log` row carries `stop_anchor`/`stop_offset`; over a day: count of `cb stop skipped` lines, stop
distance distribution, stop-out share vs the 68 % of the book-stop day.

## 11. Acceptance criteria

1. With `CB_STOP_MODE=candle`, every position opened from `cb_zone_{tf}` whose event carries `stop` has
   `stop_loss_price == stop == anchor ∓ offset` as of the firing trade; one whose event carries `None` has
   the placeholder and the log says why.
2. `compute_candle_stop` on hand-built bars gives §6's numbers exactly; no skip ever becomes a stop.
3. `CB_STOP_MODE=book` reproduces today's behaviour (with the 0.2 % fallback); `off` = the 0.2 % placeholder for every open.
4. Rows stored before this build decode.
5. Host loops green; Docker gate green; test count ≥ baseline + new tests.

## 12. Follow-ups (not blocking)

- Replay the forward paper day with the same script (`external/executor/runs/2026-10-20-sl-15m-anchor-replay.py`,
  mode `proposed_anchor_c1_range_trail`) against the live numbers: the reproduction gate for this rule.
  **Done 2026-10-21** the other way round ([run report](../runs/2026-10-21-rel001-vs-candle-stop-replay.md)): the
  live run reproduces 58/58 (stops exact); the release_001 book stop rebuilt from the stored book would have made
  ≈ +440 USDT *more* over the 23.4 h since the restart (+422 vs −19 sim-vs-sim, 90 % CI [−442, +1 267], +133 … +440
  by book staleness) — the opposite sign of the 2026-10-20 replay (+791 for the candle stop). Both inside noise;
  nothing to revert, nothing confirmed; the side-by-side paper stack remains the arbiter.
- Persist / rebuild the bars from the `candle` table after a restart (today: warm-up ≤ 60 min).
- Whether the anchor should widen to the zone's own tf (60/240) when that tf fires.
