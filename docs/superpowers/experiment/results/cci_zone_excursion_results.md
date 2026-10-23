# cci_zone_excursion — results (2026-10-21)

Spec: [`../cci_zone_excursion.md`](../cci_zone_excursion.md). Script + full outputs (every bin, both horizons, n1 and
n2, all six cells, oos2m): `executor/runs/2026-10-21-cci-zone-excursion-*`. Verdict: **partial** — both questions
answered with numbers; no CCI threshold separates the excursion distributions, and the strict marker goes the other
way from the paper-run intuition.

Gates: strict labels recomputed = stored oos2m columns on 100.000 % of 84 467–84 932 rows per cell (12 cells, 0 NaN
mismatches); 2y index has one gap (1 h 21 min), rows treated positionally like the stored labels; every reported
bin has ≥ 800 in-zone minutes on 2y except the two extreme negative bins of tf 60 / 240 (n 37–808, marked);
oos2m reproduces every direction below. `adv` = CCI signed into the zone's side (+ = momentum pushing into the zone).

## 1. CCI at zone entry and at the strict marker (2y; oos2m in brackets)

adv at the zone-entry minute (first in-zone minute of a block):

| cell | blocks | adv5 median | adv5 ≥ 100 | adv5 < 0 | adv15 median | adv15 ≥ 100 | adv15 < 0 |
|---|---|---|---|---|---|---|---|
| tf 15 long | 41 541 [4 003] | +66 [+64] | 38 % | 33 % | +21 [+29] | 26 % | 44 % |
| tf 15 short | 42 831 [3 644] | +67 [+51] | 37 % | 32 % | +26 [+13] | 26 % | 43 % |
| tf 60 long | 15 671 [1 612] | +120 [+108] | 62 % | 5 % | +84 [+75] | 43 % | 26 % |
| tf 60 short | 16 300 [1 383] | +117 [+113] | 62 % | 4 % | +81 [+74] | 41 % | 26 % |
| tf 240 long | 6 519 [691] | +110 [+101] | 55 % | 13 % | +121 [+106] | 62 % | 4 % |
| tf 240 short | 6 722 [521] | +107 [+113] | 54 % | 15 % | +117 [+121] | 60 % | 5 % |

P(strict n1 marker = 1 | adv bin) over in-zone minutes (base rate = all in-zone minutes; zone-entry-minute value in
parentheses for the top bin):

| cell | base | adv5 −140..−100 | −100..0 | 0..100 | 100..140 | 140..200 | ≥ 200 | adv15 ≥ 200 |
|---|---|---|---|---|---|---|---|---|
| tf 15 long | 0.122 [0.121] | 0.059 | 0.110 | 0.110 | 0.115 | 0.135 | 0.193 (entry 0.24) [0.170] | 0.204 [0.218] |
| tf 15 short | 0.122 [0.124] | 0.065 | 0.127 | 0.107 | 0.112 | 0.135 | 0.178 (entry 0.24) [0.173] | 0.210 (entry 0.28) [0.197] |
| tf 60 long | 0.066 [0.071] | 0.064 (n 47) | 0.074 | 0.040 | 0.063 | 0.086 | 0.122 [0.098] | 0.091 [0.091] |
| tf 60 short | 0.071 [0.067] | 0.027 (n 37) | 0.077 | 0.043 | 0.074 | 0.090 | 0.110 [0.096] | 0.102 [0.105] |
| tf 240 long | 0.039 [0.053] | 0.006 | 0.024 | 0.032 | 0.048 | 0.059 | 0.076 [0.084] | 0.060 [0.072] |
| tf 240 short | 0.047 [0.045] | 0.023 | 0.033 | 0.039 | 0.060 | 0.063 | 0.078 [0.073] | 0.073 [0.051] |

n2 (two-candle horizon) has the same shape at a higher base (tf 15: 0.20 → 0.25 / 0.26 at ≥ 200, entry 0.31 / 0.34).
The marker's first positive minute sits at the zone entry (median 0 min after it, q75 2–3 min) and carries adv5 ≈
+100–107 (tf 15). Reading: the strict label (target 1·atr_ma before stop x·atr_ma, clean last 15 min) is *more* often
true the stronger the momentum into the zone — on 2y the "CCI > 140 = bad entry" intuition is reversed for this
marker. The paper-run stop-outs at high CCI are a stop-anchor effect (stop 1–2 ATR1 from a running price), not a
target-reach effect.

## 2. Excursion beyond the current extreme, 1-min ATR, by CCI (2y, one sample per block)

To the tf candle close, q50 / q75 / q90 (P > 2 ATR1) — adv5 rows; adv15 rows in the output are within ±0.1:

| cell | all in-zone | adv < 0 | 0..100 | ≥ 100 | ≥ 140 | ≥ 200 | ≥ p90 (value) |
|---|---|---|---|---|---|---|---|
| tf 15 long | 0.72 / 1.83 / 3.34 (22 %) | 0.69 / 1.69 / 2.94 | 0.66 / 1.70 / 3.11 | 0.73 / 1.91 / 3.57 | 0.77 / 2.00 / 3.71 (25 %) | 0.77 / 2.13 / 4.19 | 0.79 / 2.08 / 4.08 (186) |
| tf 15 short | 0.73 / 1.78 / 3.22 (22 %) | 0.66 / 1.62 / 2.89 | 0.66 / 1.65 / 3.04 | 0.76 / 1.87 / 3.40 | 0.80 / 1.95 / 3.56 (24 %) | 0.85 / 2.20 / 3.97 | 0.82 / 2.10 / 3.88 (186) |
| tf 60 long | 1.70 / 3.88 / 6.95 (45 %) | 1.34 / 3.04 / 5.42 | 1.28 / 3.09 / 5.68 | 1.77 / 4.09 / 7.24 | 1.82 / 4.18 / 7.42 (47 %) | 1.81 / 4.23 / 8.00 | 1.85 / 4.22 / 7.95 |
| tf 60 short | 1.71 / 3.90 / 6.81 (45 %) | 1.18 / 2.94 / 5.08 | 1.29 / 3.07 / 5.63 | 1.83 / 4.13 / 7.26 | 1.93 / 4.28 / 7.66 (49 %) | 2.01 / 4.48 / 7.75 | 1.98 / 4.41 / 7.73 |
| tf 240 long | 3.65 / 7.95 / 13.6 (66 %) | 2.51 / 5.71 / 10.2 | 3.48 / 7.43 / 13.1 | 3.74 / 8.26 / 14.1 | 3.68 / 8.06 / 14.1 | 3.36 / 7.42 / 14.5 | 3.60 / 7.69 / 14.2 |
| tf 240 short | 3.61 / 7.47 / 13.4 (67 %) | 2.63 / 5.37 / 8.9 | 3.12 / 6.67 / 12.1 | 3.85 / 8.16 / 14.3 | 3.86 / 8.47 / 14.3 | 3.83 / 7.91 / 13.8 | 3.84 / 7.96 / 14.2 |

Next 60 min (any cell, any CCI): q50 ≈ 3.0–3.4 ATR1, q90 ≈ 9–11.5 — time, not CCI. oos2m: tf 15 q50 0.61–0.80,
q90 2.6–3.3; tf 60 q50 1.2–2.0, q90 5–7; tf 240 q50 2.6–3.9, q90 9–13 — same ordering, slightly tighter tails.

Delayed entry = limit at the current extreme + δ·ATR1 (horizon candle close), condition adv5 ≥ 140 (≥ 100 is the
same within 1 point):

| cell | δ 0.5: P(fill) / P(stop +1 / +2 / +3 ATR1) | δ 1.0 | δ 2.0 |
|---|---|---|---|
| tf 15 long | 58 % / 57 / 32 / 19 % | 44 % / 57 / 33 / 20 % | 25 % / 58 / 35 / 23 % |
| tf 15 short | 59 % / 55 / 31 / 17 % | 44 % / 55 / 31 / 18 % | 24 % / 56 / 32 / 20 % |
| tf 60 long | 74 % / 74 / 55 / 41 % | 64 % / 75 / 55 / 41 % | 47 % / 74 / 56 / 41 % |
| tf 60 short | 76 % / 74 / 55 / 41 % | 65 % / 76 / 56 / 42 % | 49 % / 74 / 55 / 41 % |
| tf 240 long | 83 % / 86 / 73 / 62 % | 77 % / 85 / 72 / 62 % | 65 % / 85 / 73 / 62 % |
| tf 240 short | 85 % / 85 / 73 / 63 % | 79 % / 86 / 74 / 62 % | 68 % / 86 / 72 / 62 % |

oos2m: tf 15 stops 43–50 / 21–27 / 11–13 %, tf 60 67–74 / 47–51 / 33–38 %, tf 240 82–87 / 66–74 / 53–64 %.

## What it means for the delayed entry and the stop

- **CCI level does not move the excursion enough to act on.** From adv < 0 to adv ≥ 200 the median rises by
  0.1–0.2 ATR1 (tf 15), 0.5–0.8 (tf 60), 1.0–1.3 (tf 240); 100 vs 140 vs p90 (158–186) are identical within noise. The
  "stats-based value" question has no answer because the distribution hardly conditions on CCI; the tf does.
- **The excursion is memoryless in δ**: P(a further +1 ATR1 | filled) is 55 % (tf 15), 75 % (tf 60), 85 % (tf 240)
  whatever δ is. A deeper delayed entry buys nothing in stop safety, it only cuts the fill rate (59 → 44 → 24 % at
  tf 15).
- **Numbers to use (tf 15 zones, horizon = candle close):** delayed entry at the extreme + 0.5–1.0 ATR1 (fill 59 / 44
  %, ≈ the median excursion), stop at the fill + 2 ATR1 (stopped 31–33 %) or + 3 ATR1 (18–20 %). tf 60: entry + 1 ATR1
  fills 65 %, stop needs + 3 ATR1 for a 41 % stop rate within the candle. tf 240: inside the candle even + 3 ATR1 is
  stopped 62 % of the time — a 240 zone needs the 60-min horizon (q50 3 ATR1) or a target-sized stop, not an ATR1 one.
- **The strict marker favours high adv.** If anything, high CCI at the zone argues for taking the entry, with the
  stop sized by the tables above, not for skipping it.
