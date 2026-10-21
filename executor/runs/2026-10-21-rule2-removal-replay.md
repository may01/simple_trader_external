# Replay: the CB zone entry without rule 2 (wick / zone-rejection signal)

Date: 2026-10-21. Question (user): the position opens on two conditions — rule 1 = price in the zone and the 1-min
trade-price MA moving in the direction; rule 2 = the previous 1-min candle's wick crossed the zone and the candle
closed back outside it, open on the next candle. How does the profit change if rule 2 is removed?

Data: `cbov-check` paper stack (Binance LINKUSDT, paper balance 100 000, `RISK_PER_TRADE=100`,
`MAX_NOTIONAL_FRACTION=0.5`, `CB_STOP_MODE=candle`), read straight from its tables: `trade` (748 157 rows,
10-16 22:29Z → 10-21 10:05Z), `indicators` (42 CB names, 465 582 readings with their expiry), `signal_log`
CbZoneEntry rows (188) and `position_log` (the last two for the reproduction gate only). Window = the whole CB-armed
history, **2026-10-18 11:41Z → 2026-10-21 10:05Z (70.4 h, 527 892 trades)**, plus three slices (§5).
Script: [`2026-10-21-rule2-removal-replay.py`](2026-10-21-rule2-removal-replay.py) (numpy only; the export SQL is in
its header; a copy of the `2026-10-20-ma-window-by-tf-replay.py` harness with the MA-window variants replaced by rule
sets). Outputs incl. every per-trade table and the live → r1 transition table: [`…-output.txt`](2026-10-21-rule2-removal-replay-output.txt)
(full window), [`…-output-candle-era.txt`](2026-10-21-rule2-removal-replay-output-candle-era.txt),
[`…-output-24h.txt`](2026-10-21-rule2-removal-replay-output-24h.txt), [`…-output-prev24h.txt`](2026-10-21-rule2-removal-replay-output-prev24h.txt).
Status: **answered — removing rule 2 does not change the profit measurably; the sign of the difference flips by window (§8).**

## 1. What was replayed

Nothing recorded is reused: every fire is recomputed from the stored indicators and trades with a port of
`CbZoneEntryCheck` + `signals::trend` + `cb_stop::compute_candle_stop` + the orchestrator's open / skip / reversal and
the executor's stop watcher and trend-flip exit (cb-candle-stop @ `a6a5bc6`, the stack that is live). Per trade `t`:

- indicators = the latest stored reading with `received_at ≤ t < expires_at`;
- trend class = 10 s bucket means over the last 6 000 trades, trailing mean over 6 buckets (1 min), slope = first
  difference, σ = population std of the slopes in the last 2 h, up/down if |slope| > 0.7 σ, ≥ 30 buckets;
- rule 1 = `{tf}_cb_inzone_{side} == 1` ∧ class = direction; rule 2 = previous 1-min candle (from the trades) wick
  ≤ zone ∧ close > zone (short mirrored) ∧ class ∈ {neutral, direction}; filters overshoot + trend (0 vetoes, absent
  passes); once per (tf, side, zone) with the latest zone per (tf, side) remembered; both sides → nothing; 60 s gap
  deferred; highest tf fires; target = `{tf}_cbnc_{far}` at fire;
- stop = forming-15m extreme ∓ mean range of the last 60 closed 1-min bars, 0.2 % placeholder when not adverse —
  today's live rule, held fixed for every variant; size `min(100 / dist, free × 0.5 / entry)`; entry at the fire
  trade's price; stop fills at the crossing trade; paper = no fees (fee column as sensitivity).

| variant | rules that may produce a candidate | what it answers |
|---|---|---|
| **live** | rule 1 + rule 2 | reproduction |
| **r1** | rule 1 only | **the question: rule 2 removed** |
| r2 | rule 2 only | ablation: what rule 2 is worth on its own |

Second-order effect, handled by construction: a rule-2 fire marks its (tf, side, zone) as fired, so in `live` rule 1
can no longer fire on that zone; in `r1` the same zone may fire later by rule 1 (§4).

Author's calls (user not available during the run; flag if you disagree): the whole CB-armed history as the primary
window (the live run's earlier stop rules are *not* reproduced — fires are, P&L is not, one stop rule throughout);
the candle-stop era (10-20 20:25Z →, the only slice where the recorded P&L and the sim share a stop rule), the last
24 h and the 24 h before it as robustness slices; a 6-h-block paired bootstrap of the variant difference as the
significance test (positions binned by the opening fire's time, blocks resampled); no parameter fitted anywhere.

## 2. Gates

| Gate | Result |
|---|---|
| Reproduction: fires | `live` re-fires **181 of the 188** recorded CbZoneEntry rows (same side + tf within 60 s; median \|dt\| 0.0 s, max 2.7 s); same rule 180/181, same class 180/181, same zone value 181/181; at the 177 exact-timestamp matches the logged `ma_slope` is reproduced to a median relative difference of 3.1 × 10⁻⁸ (one row at 4.7 × 10⁻², all others < 1 %). The 7 misses sit at the executor (re)starts — 10-18 11:41Z (boot), 10-19 22:43Z (release_001), 10-20 20:25Z (candle stop) — where the live check had a short trade window (σ over an almost empty window → class) and the sim has the full window; 2 extra sim fires are the same zones fired a few minutes later. |
| Reproduction: stop port | **36 of 37** recorded candle-stop fires reproduced within half a tick (the one miss is the first fire 1.7 min after the candle-stop restart: live `MinuteBars` had ~35 closed bars, the sim uses the full 60 → offset 0.0093 vs 0.0086, anchor exact). |
| Reproduction: P&L in the candle-stop era | recorded 36 positions +356 vs sim-live 34 positions +151 over the same 13.7 h — same trades, the difference is the two restart-only fires (the first recorded one is the +94 `main_close`) and fill-price differences of the paper engine; the variant comparison is sim vs sim. |
| Look-ahead | by construction: indicators by `received_at ≤ t`, trades ≤ t, bars closed before the current minute, the forming bar only up to the current trade; rule 2 reads the *previous* minute's candle only. |
| Provenance | no parameter fitted: 0.7 σ, 2 h, 6 000 trades, 60 s gap, 15-min anchor, 60 bars, 0.2 % and the sizing are the live values; the variants differ only in the rule set. |
| Null floor | 168 / 141 / 150 positions; bootstrap 90 % CI of the net: live [+457, +4 946], r1 [+1 083, +5 128], r2 [+134, +4 174]. **Paired 6-h-block difference r1 − live = +378, 90 % CI [−788, +1 542], P(Δ < 0) 0.29** (7 blocks r1 ahead, 5 behind, 1 equal); r2 − live = −600, CI [−1 405, +254], P 0.88. |
| Concentration | top-2 trades +733 (live), +715 (r1), +691 (r2) — the same two 240-zone trades in every variant. |
| Split halves | live +504 / +2 190; r1 +1 077 / +1 996; r2 +311 / +1 783 — r1 ahead of live in the first half (+573), behind in the second (−194). |
| Slices (§5) | candle-stop era r1 − live −167 (P 0.73); last 24 h −258 (P 0.69); previous 24 h +50 (P 0.47). The sign flips. |
| Feed gaps | 4 gaps > 60 s in the window: 5 564 s (10-19 13:01Z), 9 432 s (10-19 20:01Z), 305 s (10-20 16:13Z), 66 s (10-21 02:55Z). |

## 3. Headline — full window (70.4 h)

| variant | trades | net | net at 0.1 %/side fee | PF | win rate | stop-outs n / mean | targets | reversals | median hold min | sum R | 90 % CI | top-2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| live | 168 | +2 694 | −13 023 | 1.42 | 51 % | 79 / −80 | 61 | 27 | 7.2 | +38.7 | [+457, +4 946] | +733 |
| **r1** | **141** | **+3 073** | **−9 808** | **1.62** | **59 %** | 56 / −88 | 65 | 19 | 7.8 | +42.6 | [+1 083, +5 128] | +715 |
| r2 | 150 | +2 094 | −11 160 | 1.41 | 52 % | 62 / −79 | 68 | 19 | 6.6 | +28.6 | [+134, +4 174] | +691 |

Fires: live 183 (rule 1: 103, rule 2: 80; 15/60/240 = 137/36/10), r1 153 (113/30/10), r2 161 (119/33/9).
Deferred ticks (60 s gap): live 285, r1 140, r2 84. Contradiction ticks 0 everywhere.

Per tf (positions by the tf of their opening fire):

| variant | tf 15 n / net / PF | tf 60 n / net / PF | tf 240 n / net / PF | tf 60+240 n / net / CI |
|---|---|---|---|---|
| live | 127 / +1 710 / 1.36 | 32 / +318 / 1.23 | 9 / +667 / 2.98 | 41 / +984 / [−270, +2 283] |
| r1 | 104 / +2 360 / 1.70 | 28 / +429 / 1.36 | 9 / +283 / 1.72 | 37 / +712 / [−425, +1 856] |
| r2 | 114 / +1 702 / 1.47 | 28 / +162 / 1.15 | 8 / +230 / 1.70 | 36 / +392 / [−672, +1 547] |

Per UTC day of the opening fire (n / net): 10-18 live 26 / +542, r1 25 / +771, r2 24 / +345; 10-19 40 / +330,
34 / +651, 35 / +146; 10-20 74 / +1 684, 62 / +1 361, 66 / +1 171; 10-21 (10 h) 28 / +138, 20 / +291, 25 / +432.
r1 wins two of the four days, loses the biggest one.

## 4. What rule 2 actually does in the live run

Positions of the live variant by the rule of their opening fire:

| opening rule | n | net | PF | win rate | stop-outs | targets | reversals | median risk |
|---|---|---|---|---|---|---|---|---|
| in_zone (rule 1) | 96 | +1 495 | 1.40 | 55 % | 42 / −88 | 40 | 14 | 90 |
| zone_rejection (rule 2) | 72 | +1 199 | 1.45 | 46 % | 37 / −71 | 21 | 13 | 71 |
| rule 2 with class neutral / down / up | 63 / 8 / 1 | +1 037 / +115 / +47 | 1.43 / 1.44 / ∞ | 44 / 50 / 100 % | | | | |
| rule 2 long / short | 33 / 39 | +397 / +803 | 1.31 / 1.58 | 39 / 51 % | | | | |

So rule-2 positions are **not** losers on their own (+1 199 over 72, PF 1.45 — the same PF as rule 1's). Removing
them still *raises* the full-window net because of what they displace:

- **Fire keys.** live fires 183 (side, tf, zone) keys; r1 fires 153 — every one of them also a live key; 30 keys fire
  only in live. On the 153 common keys 117 fire in the same minute, 36 fire later in r1 (median +0.0, max +12.6 min):
  rule 2 mostly fires the **same zone earlier** (class still neutral), rule 1 catches it once the MA class confirms.
- **The 30 rule-2-only zones** (zones that never get a direction-class minute while in-zone): 30 live positions,
  net +289, PF 1.29, win rate 43 %, 14 stop-outs — worth little; 11 of them were the live rule-2 positions that map to
  no r1 position at all (−256 in live, i.e. removing them is +256).
- **Transitions** of the 72 live rule-2 positions into r1 (same side, r1 position opened within −5…+60 min):
  38 tf-15 → tf-15 +923 → +1 094; 7 tf-15 → tf-60 +58 → +739 (the later fire is taken by the 60 zone with the farther
  target); 4 tf-60 → tf-15 +473 → +384; 7 tf-60 → tf-60 −61 → −116; 2 tf-60 → tf-240 −88 → −123; 1 tf-240 → tf-15
  +296 → +96; 2 tf-240 → tf-240 −145 → −169; 11 → none (−256 → 0). Net of the matched set +1 199 → +1 905; the rest
  of r1's book is worse than live's by about the same amount (the 60-s gap and the fired-state chain shift every
  later fire), so the system total moves only +378.
- Rule 2 delays nothing and adds no *new* zones that pay; its value is "the same zone, one or a few minutes earlier,
  before the MA agrees" — which on these 70 h is worth +0 … +400 either way.

## 5. Slices

| window | h | live n / net | r1 n / net | r2 n / net | r1 − live paired Δ, 90 % CI, P(Δ<0) | r2 − live |
|---|---|---|---|---|---|---|
| full CB-armed history 10-18 11:41Z → 10-21 10:05Z | 70.4 | 168 / +2 694 | 141 / +3 073 | 150 / +2 094 | +378, [−788, +1 542], 0.29 | −600, [−1 405, +254], 0.88 |
| candle-stop era 10-20 20:25Z → | 13.7 | 35 / +425 | 25 / +258 | 31 / +817 | −167, [−797, +463], 0.73 | +392, [+184, +601], 0.00 (3 blocks) |
| last 24 h 10-20 10:05Z → | 24 | 67 / +1 193 | 52 / +936 | 62 / +1 227 | −258, [−1 040, +618], 0.69 | +34, [−456, +552], 0.47 |
| previous 24 h 10-19 10:05Z → 10-20 10:05Z | 24 | 52 / +885 | 47 / +935 | 43 / +698 | +50, [−415, +617], 0.47 | −188, [−735, +385], 0.69 |

In the candle-stop era the live rule-1 tf-15 positions are the losing leg (13, −230, PF 0.60) and the rule-2
positions the winning one (21, +528, PF 1.80) — the opposite of the full window's ordering. Nothing is stable.

## 6. Fees

At 0.1 %/side every variant loses (live −13.0 k, r1 −9.8 k, r2 −11.2 k). Gross-edge breakeven fee per side ≈
0.017 % (live), 0.024 % (r1), 0.019 % (r2): r1 is the cheapest variant to run because it trades 16 % fewer times for
the same gross, but all three sit far below any real taker fee (see trend_x_sweep: 0.021 %/side on the earlier window).

## 7. Caveats

- One window of 70 h, one pair, paper fills, no fees; every variant's CI is ±2 k wide and the differences are ±0.4 k.
- The sim holds today's candle stop throughout, so the first 57 h of fires are scored with a stop the live run did not
  have then; this is the same for every variant and only the differences are read.
- Rule 2 fires with a neutral class 63 of 72 times — removing it is almost the same experiment as "require the MA
  class at every fire"; a "rule 2 but only with class = direction" variant would be a third option, not run here
  (it would be 9 positions on this window).

## 8. Conclusion

**Removing the wick / zone-rejection signal (rule 2) does not change the profit measurably.** Full window +2 694 →
+3 073 (+378, P(Δ<0) 0.29) with 16 % fewer trades and a higher PF (1.42 → 1.62); last 24 h −258, candle-stop era −167,
previous 24 h +50 — the sign flips with the window and every paired CI straddles zero. Mechanism: rule 2 rarely opens
a zone rule 1 would not (30 of 183 keys, worth +289 together); it opens the same zone a few minutes earlier, before
the MA class confirms, and those earlier fills are neither systematically better nor worse. No rule change
recommended on this evidence; the only consistent effect of removal is fewer trades (lower fee exposure for the same
gross), which is a reason to revisit once fees are real and ≥ 2 weeks of trades exist (`--t0=` re-run).
