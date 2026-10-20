# Replay: stop anchored at the current 15-min extreme (last 21 h of the paper run)

Date: 2026-10-20. Data: `cbov-check` paper stack (release_001 @ `1689dc5`, Binance LINKUSDT,
`CB_STOP_EXPECTED_POINTS=15:2/2;60:3/3;240:4/4`, `RISK_PER_TRADE=100`, `MAX_NOTIONAL_FRACTION=0.5`,
paper balance 100 000). Window 2026-10-19 22:43Z → 2026-10-20 19:18Z (first CB fire → last stored trade).
Script: [`2026-10-20-sl-15m-anchor-replay.py`](2026-10-20-sl-15m-anchor-replay.py) (numpy only, reads the
exports of `trade`, `signal_log` CbZoneEntry rows, `position_log`); full output incl. the per-trade table:
[`…-output.txt`](2026-10-20-sl-15m-anchor-replay-output.txt). Status: **decision taken 2026-10-20 — "forming-15m extreme ± mean 1-min range, trailing 60" (§9) is being
implemented as the default CB stop: spec [`2026-10-20-cb-candle-stop-design.md`](../specs/2026-10-20-cb-candle-stop-design.md),
branch `cb-candle-stop` @ `a6a5bc6`, live since 2026-10-20 ~20:25Z; the 0.2 % placeholder (§7) was also adopted the same day.**

## 1. Proposed rule (user, 2026-10-20)

> Stop loss should be: current 15 min High (for short) / low (for long) + existing sl value.

Read as: `d = |entry − stop_today|` (book stop when adverse to the entry, else the 1 % placeholder — exactly
what the builder places today); **long stop = low of the forming 15-min candle at open time − d; short stop =
high of the forming 15-min candle + d.** Two readings of the sentence are also reported: the last *closed*
15-min candle's extreme ± d, and the forming extreme alone (d = 0).

## 2. What the replay does

Event-driven re-run over the recorded trades with the recorded `CbZoneEntry` fires (74 events; the skipped
ones too, since a wider stop keeps positions open longer and changes which fires are skipped or reversed):

- flat → open at the recorded entry price (book mid at the time) when the event actually opened, else at the
  event's trade price; same-side event while open → skip; opposite side → close at the event price and reopen
  (the executor's reversal);
- stop watcher trips on `trade ≤ stop` (long) / `≥ stop` (short); stop fill = the crossing trade's price
  (paper fills a market order at the mid, see §5);
- target exit = extreme beyond `take_profit_price` and then the opposite 10-s-bucket trend class, trend class
  ported from `signals::trend` over the same 6 000-trade window;
- size = `min(100 / dist, free_quote × 0.5 / entry)`, free quote tracks cumulative P&L; no fees (paper).

Both rules run through the same simulator; the "current" run is the reproduction gate.

## 3. Gates

| Gate | Result |
|---|---|
| Reproduction: opens | sim-current opens the same 68 positions as the live run, same stops (all 68 exact), sizes within 0.2 % (balance drift) |
| Reproduction: exits | same close reason for 68/68; exit prices differ by the fill model only (§5): actual net **+331.70**, sim-current **+144.96** (stop-outs −407.88 actual vs −615.11 sim) |
| Trend-class port | at the 14 recorded target exits the port gives the same class 13/14 (the 14th is trade-selection ambiguity), σ within 1 % of the logged values |
| Null floor | 65–69 trades; bootstrap 90 % CI of the net: current [−267, +591], proposed [−641, +1 544]. **The difference is inside the noise.** |
| Concentration | top-2 trades: current +264 of +145 net; proposed +615 of +411 net — both rules are net negative without their two best trades |
| Feed gaps | 2 gaps > 60 s in the trade feed (one of 9 432 s on 10-19 20:01Z, before the first fire; one of 305 s on 10-20 16:13Z) |

## 4. Results (same fill model for all rows: stop fills at the crossing trade)

| Rule | trades | net USDT | gross win (n) | gross loss (n) | win rate | PF | stop-outs: n, mean | target exits | reversals | median hold | median risk/trade |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **current** (book stop / 1 % placeholder) | 68 | **+145** | +797 (20) | −652 (48) | 29 % | 1.22 | 46, −13.4 | 14 | 8 | 1.9 min | 14.6 USDT |
| **proposed** forming-15m extreme ± d | 65 | **+411** | +2 230 (32) | −1 819 (33) | 49 % | 1.23 | 31, −57.6 | 23 | 11 | 6.5 min | 66.9 USDT |
| variant: last *closed* 15m extreme ± d | 66 | +49 | +1 179 (27) | −1 130 (39) | 41 % | 1.04 | 37 | 20 | 9 | 3.4 min | 54.2 USDT |
| variant: forming-15m extreme only (d = 0) | 69 | +1 154 | +2 994 (28) | −1 840 (41) | 41 % | 1.63 | 41 | 20 | 8 | 4.0 min | 41.6 USDT |

With stop fills *at the stop level* instead of the crossing trade: current +145 (unchanged, every stop sat on
the grid), proposed +465, closed-15m +116, anchor-only +1 154.

Actual recorded P&L of the live paper run over the same window: **+331.70** (46 stops −407.88, 14 targets,
8 reversal closes) — higher than sim-current only because of the paper mid-fill (§5).

### Where the difference comes from (current → proposed, same opening event)

| transition | n | P&L current | P&L proposed | Δ |
|---|---|---|---|---|
| stop → stop (stop still hit, now further away, ~5× larger loss) | 31 | −414 | −1 786 | **−1 372** |
| stop → target (survived the shake-out, rode to the trend-flip exit) | 9 | −114 | +1 108 | **+1 222** |
| stop → reversal | 3 | −40 | +348 | +388 |
| stop → not opened (position still held, fire skipped) | 3 | −48 | 0 | +48 |
| target → target | 14 | +434 | +420 | −14 |
| reversal → reversal | 8 | +326 | +321 | −6 |

Stop distance: current median 3 ticks (0.029 %), proposed median 13 ticks (0.134 %); 16 of 65 proposed
stops inherit the 1 % placeholder as `d` (≈120 ticks beyond the 15-min extreme — those are effectively
"never stopped, wait for the flip or the reversal").

## 5. Caveats

1. **Paper fill bias.** The live paper account fills the stop's market order at the book mid, which over
   46 stops was 1–1.5 ticks *better* than the crossing trade (several recorded stop-outs show P&L 0 or
   positive). The simulator fills at the crossing trade, so every sim row is ≈ 4–6 USDT per stop more
   pessimistic than the paper run. Relative comparison is unaffected (same model both sides); the actual
   +331.70 is not comparable with the sim rows one-to-one.
2. **Risk per trade is not held constant.** Today's 3-tick stops hit the notional cap, so the live risk per
   trade is ~15 USDT, not 100. The wider stop pushes it to ~67 USDT median and the stop-outs grow 4–5×.
   Net USDT therefore mostly reflects *more risk*, not better entries: in R-multiples the two are
   indistinguishable (current −6.7 R over 68, proposed +3.7 R over 65).
3. **21 h, one pair, one regime** (LINK 11.9–12.4, two 2–3 % moves). The 90 % CIs overlap almost entirely.
   This replay cannot distinguish the rules; it can only say the proposed stop is not obviously worse and
   changes the trade shape (fewer, larger stops; 9 of 46 stop-outs become target exits).
4. Entry price for events the live run skipped is the event's trade price, not the mid; reversal closes fill
   at the event price (paper limit-at-trade behaviour).
5. The anchor-only variant (d = 0) is the best row and the one that violates the user's wording; its edge
   is also concentrated in two trades (+599 of +1 154).

## 6. Verdict

Not decidable on 21 h. Proposed stop: +266 USDT vs current in the same simulator (+411 vs +145), P(net<0)
0.28 vs 0.31, same profit factor (1.23 vs 1.22), roughly 4.5× the risk per trade. If it goes live as a
toggle, the fair comparison is a second paper stack side by side, or a longer replay once the 1-min-trade
store covers a week.

## 7. Sensitivity: placeholder fallback 1 % → 0.2 % (user question, 2026-10-20)

Same replay, `--placeholder=0.002` (output: [`…-output-placeholder02.txt`](2026-10-20-sl-15m-anchor-replay-output-placeholder02.txt)).
The placeholder is the stop for the 16 opens whose book stop was not adverse to the entry (16/68 = 24 % of fires).

| Rule | placeholder | trades | net | PF | win rate | stop-outs n / mean | median risk/trade | bootstrap 90 % CI | P(net<0) |
|---|---|---|---|---|---|---|---|---|---|
| current | 1 % | 68 | +145 | 1.22 | 29 % | 46 / −13 | 15 | [−267, +591] | 0.31 |
| current | **0.2 %** | 71 | **+1 087** | 2.04 | 28 % | 51 / −21 | 15 | [+118, +2 155] | 0.03 |
| proposed (forming 15m ± d) | 1 % | 65 | +411 | 1.23 | 49 % | 31 / −58 | 67 | [−641, +1 544] | 0.28 |
| proposed (forming 15m ± d) | **0.2 %** | 68 | +1 117 | 1.51 | 49 % | 35 / −63 | 71 | [−265, +2 488] | 0.09 |
| closed-15m ± d | 0.2 % | 69 | +874 | 1.68 | 38 % | 43 | 38 | [−105, +1 925] | 0.07 |
| forming-15m only (d = 0) | — | 69 | +1 154 | 1.63 | 41 % | 41 | 42 | [−49, +2 432] | 0.06 |

**Mechanism — it is a sizing change, not a stop change.** With a 1 % stop (≈ 120 ticks on LINK) the size
is `100 / 0.12 ≈ 830`; with 0.2 % (≈ 24 ticks) it is `100 / 0.024 ≈ 4 170`, i.e. exactly the notional cap
that every book-stop position already sits at. The 16 placeholder positions were the run's best trades (10
target exits, 6 reversal closes, none stopped) and were carrying one fifth of the size. Per opening event,
current rule, 1 % → 0.2 %:

| placeholder positions | n | P&L 1 % | P&L 0.2 % | Δ |
|---|---|---|---|---|
| target → target (5× size) | 10 | +183 | +914 | +731 |
| reversal → reversal (5× size) | 2 | +69 | +346 | +277 |
| reversal → **stop** (24-tick stop now hit before the reversal) | 4 | +36 | −411 | −446 |
| book-stop positions (unchanged) | 52 | −143 | −143 | ≈ 0 |

Same shape under the proposed rule (+484 / +192 / −439). The 0.2 % stop still never fires on a position that
would otherwise reach the target: the 4 new stop-outs are reversal closes that were small (+36 total) and
turn into full −100 USDT losses.

**Caveats, in addition to §5:** (a) the whole gain is 16 trades at 5× size — the risk per trade for those
positions goes from 100 USDT nominal / ~20 effective to 100 effective, so the variance scales with it; (b)
a 24-tick stop is still ~8× today's median book stop, so the 0.2 % placeholder and the book stop remain two
different regimes inside one strategy; (c) current + 0.2 % (PF 2.04, CI excludes zero) beats proposed + 0.2 %
on every measure except win rate — on this day the book stop plus a tighter fallback did the work, the 15-min
anchor added only risk.

## 8. Variants without `d`: 15-min extreme alone, and ± a fixed fraction (user questions, 2026-10-20)

`--anchor-pct=` runs `stop = extreme ∓ extreme × pct` (long: low − pct·low; short: high + pct·high). The
placeholder never enters these rules: in 69/69 opens the forming 15-min extreme was strictly adverse to the entry
(entry never sat on the candle's own low/high), so no fallback fired. Output for 0.1 %:
[`…-output-anchor01.txt`](2026-10-20-sl-15m-anchor-replay-output-anchor01.txt).

| Rule | trades | net | PF | win rate | stop-outs n / mean | targets | reversals | median hold | median risk/trade | 90 % CI | P(net<0) | top-2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| current, placeholder 0.2 % (reference) | 71 | +1 087 | 2.04 | 28 % | 51 / −21 | 15 | 5 | 2.2 min | 15 | [+118, +2 155] | 0.03 | +592 |
| 15m ± 0 (stop on the extreme) | 69 | +1 154 | 1.63 | 41 % | 41 / −45 | 20 | 8 | 4.0 min | 42 | [−49, +2 432] | 0.06 | +599 |
| 15m ± 0.05 % | 68 | +1 543 | 1.67 | 51 % | 33 / −69 | 24 | 11 | 5.7 min | 67 | [+64, +3 021] | 0.04 | +722 |
| **15m ± 0.1 %** | 67 | **+2 048** | 1.90 | 61 % | 26 / −88 | 27 | 14 | 6.3 min | 92 | [+524, +3 607] | 0.01 | +725 |
| 15m ± 0.2 % | 62 | +1 335 | 1.70 | 69 % | 19 / −101 | 27 | 16 | 8.7 min | 100 | [+114, +2 594] | 0.04 | +532 |

15m ± 0.1 %: stop distance 12–46 ticks (median 22, 0.18 % of entry); 39/65 opens still at the notional cap;
stop fills at the stop level instead of the crossing trade: +2 084. Current (0.2 %) → 15m ± 0.1 %, same opening
event: 13 stop-outs become target exits (−165 → +1 702), 9 become reversals (−113 → +690), 26 stay stop-outs at
~4× the loss (−725 → −2 275), the 13 targets and 4 reversals are unchanged.

Reading: the curve over the fraction is a hump (0 → 0.05 → **0.1** → 0.2 %), the kind of shape a single day
produces when one parameter is swept against it — 0.1 % is the in-sample optimum, selected on the same 21 h it
is scored on. Its CI is the only one that clears zero by a margin, but the top-2 trades are a third of the net
and every row shares the same 2–3 % LINK moves. Treat 0.1 % as the candidate to run forward, not as a result.

## 9. 15-min extreme ± the mean 1-min candle size / body (user question, 2026-10-20)

1-min candles from the executor's `candle` table over the replay window (1 237 closed candles):

| statistic | mean | median | mean in ticks | mean as % of price |
|---|---|---|---|---|
| range (high − low) | 0.0130 | 0.0100 | 13 | 0.107 % |
| body (\|close − open\|) | 0.0084 | 0.0060 | 8 | 0.069 % |

Replayed as `stop = forming-15m extreme ∓ offset`, offset = the mean over the whole window (global, one number)
and the trailing mean of the 60 closed 1-min candles before the open (`--trail=60`). Placeholder 0.2 % in the
reference row only; it never enters the anchor rules. Output: [`…-output-c1.txt`](2026-10-20-sl-15m-anchor-replay-output-c1.txt).

| Rule | offset (median) | trades | net | PF | win rate | stop-outs n / mean | targets | reversals | median hold | risk/trade | 90 % CI | P(net<0) | top-2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| current, placeholder 0.2 % | — | 71 | +1 087 | 2.04 | 28 % | 51 / −21 | 15 | 5 | 2.2 min | 15 | [+118, +2 155] | 0.03 | +592 |
| 15m ± 0.1 % (§8) | 0.0120 | 67 | +2 048 | 1.90 | 61 % | 26 / −88 | 27 | 14 | 6.3 min | 92 | [+524, +3 607] | 0.01 | +725 |
| 15m ± mean 1-min range, global | 0.0130 | 67 | +1 964 | 1.85 | 61 % | 26 / −89 | 27 | 14 | 6.6 min | 96 | [+441, +3 515] | 0.02 | +723 |
| 15m ± mean 1-min body, global | 0.0084 | 68 | +1 930 | 1.81 | 56 % | 30 / −80 | 27 | 11 | 6.1 min | 77 | [+324, +3 521] | 0.02 | +724 |
| 15m ± mean 1-min range, trailing 60 | 0.0104 (0.0069–0.0296) | 67 | +1 878 | 1.83 | 60 % | 27 / −84 | 27 | 13 | 6.6 min | 90 | [+394, +3 376] | 0.02 | +657 |
| 15m ± mean 1-min body, trailing 60 | 0.0074 (0.0046–0.0173) | 67 | +1 824 | 1.82 | 55 % | 30 / −74 | 26 | 11 | 5.9 min | 74 | [+368, +3 333] | 0.02 | +723 |

Reading: all four land within ±120 USDT of the 0.1 % row, because the mean 1-min range on this day *is*
0.107 % of price — the same offset by another name. The body (8 ticks) sits between the 0.05 % and 0.1 %
rows of §8 and scores accordingly. The trailing versions adapt the offset to the hour (7–30 ticks) and lose
~100–170 USDT to the global mean here, mostly through 1–4 extra stop-outs in the quiet hours. A volatility-
scaled offset is the more defensible rule for the forward run (it does not carry this day's 0.1 % in its
pocket); on this sample it does not beat the fixed fraction. Same caveats as §8: one day, in-sample.
