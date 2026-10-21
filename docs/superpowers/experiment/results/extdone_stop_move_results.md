# extdone_stop_move — results (2026-10-20)

Verdict: **partial** — nothing decision-grade at the system level; a weak tf-15-only candidate. Profit-side lock-in (2026-10-21 follow-up): **negative**.
Detail, tables and mechanics: `external/executor/runs/2026-10-20-extdone-stop-move-replay.md`
(script + raw output beside it). Spec: [extdone_stop_move.md](../extdone_stop_move.md).

## Headline

58 h paper replay (136 positions, live net +2 447), rule = once the entry-side `extdone` (15 / 60 /
own tf) is on, stop → entry ∓ Y·ATR(1 min), tighten only:

| trig \ Y | 0 | 0.5 | 1 | 1.5 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|---|---|
| 15 | +2532 | +2319 | +2288 | +2390 | +2512 | +2480 | +2459 | +2447 |
| 60 | +2275 | +2230 | +2217 | +2556 | +2498 | +2447 | +2447 | +2447 |
| own | +2615 | +2577 | +2678 | +2695 | +2600 | +2480 | +2459 | +2447 |

Every paired Δ with trigger 15 or 60 has a 90 % CI straddling zero (t15 Y0 +0 [−964, +942]; Y1.5 +182
[−250, +550]). The 15-min candle stop already sits 2–2.5 ATR from the entry, so Y ≥ 3 touches 0–4
positions. Y 0 converts 42 stop-outs into breakeven exits but forfeits 10 targets and 9 reversals: net 0.

## Per tf

| position tf | live | effect of the 15-min state, Y 0 … 2 | own-tf state |
|---|---|---|---|
| 15 (101) | +1675 | +67 … +350 (peak Y 1.5, same sign at every Y) | same as 15 |
| 60 (26) | +106 | −71 … −220 (too early for a 60-min zone trade) | no-op: the 60-min state never turns on inside an 8-min hold |
| 240 (9) | +667 | ±30 … 90 on 2–4 moves | no-op |

## Profit-side lock-in (follow-up 2026-10-21)

Stop → `entry + Y·ATR` (long) once the price is beyond it after the entry-side state has been on
(`p*` variants, run report §7): 58 h +1 724 … +2 652 vs +2 447; last 24 h (72 positions, live +1 938)
+1 187 … +2 140. Paired Δ trig 15: Y 1 −551 / −449, Y 1.5 −723 / −751 [−1404, −144], Y 3 −504 / −370,
Y 5 −305 / −216 [−484, −11]; the lone positive cell Y 2 (+47 / +118, own-tf +205 / +141) sits between two
strongly negative ones. Mechanism: the lock-in converts targets into stop-outs (p15 Y 1.5: 40 stopped at the
locked level vs 19 targets; breakeven: 42 / 37) because the path to the `cbnc` target retraces > 1 ATR.
**Negative.** Adverse-side rule on the 24 h window: same weak tf-15-only pattern (own Y 1.5 +116 [+34, +222],
trig 15 −139 … 0), tf 60 −124 … −239 under the 15-min state.

## Gates

- Reproduction: 146/153 recorded fires (misses = restarts), slope 2.7e-8 median rel diff.
- Null floor / noise: paired bootstrap per cell, 8 Y × 3 triggers; the one trig-own cell with a CI
  excluding zero (Y 1.5, +351 [+176, +548]) is one of 24 cells, neighbours +172 / +153; halves split
  +1001 / +1694 vs live +797 / +1650 — second half flat.
- Ablations: `trans` (flip required) worse (−330); `repl` (looser allowed) +150…+390 = "candle stop too
  tight", a different hypothesis.
- Look-ahead: the state is read as the executor would (latest `received_at ≤ t`, not expired); ATR1
  from the last closed 1-min bar; the move takes effect on the next trade.
- Provenance / fit: no fit — all parameters are the live ones; no oos split (4 days of ticks).
- Fee: −10 k at 0.1 %/side for every variant; the fee question still outranks the rule.

## Disposition

No branch (read-only replay). Candidate for a forward toggle only: own-tf state, tf-15 positions only,
Y ≈ 1.5, tighten only. Not recommended as a live change on this evidence.
