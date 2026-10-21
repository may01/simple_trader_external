# candle_reach_gate — Results & Conclusion

**Date:** 2026-10-21 · **Spec:** [candle_reach_gate.md](../candle_reach_gate.md) · **Plan:** [plans/2026-10-21-candle-reach-gate.md](../../plans/2026-10-21-candle-reach-gate.md) · **Branch:** none (read-only replay; docs on external `cross-tf-veto-replay`)
**Data:** 2y `2y_az_link_usdt` + `2y_link_usdt` ATR parts, 2023-01-01 → 2024-12-31, 1 052 560 rows (train / freeze); oos2m `oos2m_link_usdt`, 2025-01-01 → 2025-03-01, 84 961 rows (scored once); paper `cbov-check` DB export (LINKUSDT, 832 623 trades, 207 recorded fires), replay 10-18 11:41Z → 10-21 18:04Z (78.4 h, 15 six-hour blocks) and the candle-stop era from 10-20 02:25Z (5 blocks).
**Pipeline:** `executor/runs/2026-10-21-candle-reach-2y-oos2m.py` (output `…-output-h60.txt`), `executor/runs/2026-10-21-candle-reach-replay.py` (outputs `…-output-full.txt`, `…-output-candle-era.txt`); run report [2026-10-21-candle-reach-replay.md](../../../../executor/runs/2026-10-21-candle-reach-replay.md).
**Final configuration (frozen on 2y, tf-15 cells, retention ≥ 60 %):** reach `rem16t_a0.5_k0.5` (median range of the last 16 closed candles / ATR1 now, remaining = × (1 − progress)^0.5, skip when remaining < 0.5 × target distance); rw `rw_a0.5_k0.5`; thr `thr4t_q0.5`; chop `chop_a1.3_b0.8`; dead `dead_m1`; eff `eff_e0.25`; lad `lad240_r1.5`.

## Headline conclusion

**Negative.** The candle-reach index (tf-candle range in 1-min ATRs, forecast from the last N closed candles) does not
improve the CB zone entries on any tier. On 2y every reach-gate variant loses (frozen −14 709 [−29 067, −568] on
+166 435, P(Δ<0) 0.95; the whole grid −12 743 … −150 179); on oos2m the frozen gate is noise (+761 [−3 013, +4 399]);
on paper it sits inside the random-skip band (+270 [−284, +800] vs rand10 max +176) and its control without any reach
information (`rw`: reach replaced by √tf) does the same or better everywhere (paper +517, oos2m +151, 2y −30 613). The
24-h-shifted placebo matches the real gate on all three tiers. The index itself carries almost no forecastable
information: in ATR1 units the candle range sits at 1.1–1.3 × the random-walk value √tf and barely persists from one
candle to the next (lag-1 autocorrelation +0.12 / +0.19 / +0.07 on 2y for tf 15 / 60 / 240, +0.02 / +0.05 / +0.07 on
oos2m); the median-8 forecast's inter-quartile range on tf 15 is 3.9–4.9 ATR1 around 4.35 — a ±11 % band that no gate
can exploit. Not proven: anything about sizing or stop width from the same index (not tested, by the user's choice of
"gate first"); the fee-floor family (`dead`) had no rows on oos2m and loses on 2y.

## The progression

Paired Δ vs the e25 baseline (2y / oos2m: by candle, CI90, P(Δ<0), months with Δ > 0; paper: 6-h block bootstrap vs
the live rule; positions n / net).

| variant | 2y (base +166 435, 57 383 entries) | oos2m (base +15 827, 4 414) | paper full (live 186 / +2 679) | paper candle era (53 / +411) |
|---|---|---|---|---|
| `rem16t_a0.5_k0.5` (frozen reach) | −14 709 [−29 067, −568] P 0.95, 10/24 | +761 [−3 013, +4 399] P 0.38 | 172 / +2 950, Δ +270 [−284, +800] P 0.20 | 49 / +390, Δ −21 |
| `rw_a0.5_k0.5` (no reach: √tf × progress / D_tgt) | −30 613 [−46 169, −14 993] P 1.00 | +151 [−3 342, +3 677] | 174 / +3 196, Δ +517 [+161, +902] P 0.01 | 50 / +481, Δ +70 |
| `sh_` / `sh24_` placebo of the reach gate | −23 008 [−39 047, −6 923] P 0.99 | +855 [−2 958, +4 720] | 174 / +2 859, Δ +180 [−259, +635] | 50 / +526, Δ +115 |
| `mir_` (skip when the candle CAN reach) | −96 191 (keeps 40 %) | −19 890 | 14 / −358, Δ −3 038 | 3 / −70 |
| `thr4t_q0.5` | −1 911 [−7 226, +2 869] P 0.75 | +805 [−323, +1 870] P 0.11 (placebo +548) | 184 / +2 849, Δ +170 [+1, +372] | 53, Δ 0 |
| `chop_a1.3_b0.8` | +731 [−1 978, +3 315] P 0.32 (placebo +2 719, P 0.03) | +51 | 186, Δ 0 (never fires) | Δ 0 |
| `dead_m1` (ATR1 % < fee round trip) | −6 820 [−12 050, −1 826] P 0.99 | 0 rows | Δ 0 | Δ 0 |
| `eff_e0.25` | −7 821 [−18 950, +3 089] P 0.89 | +376 | 169 / +3 275, Δ +596 [−47, +1 345] P 0.07 (placebo +216) | 46 / +740, Δ +328 (placebo +350) |
| `lad240_r1.5` (tf-15 fire skipped when the 240 reach ratio is 1.5 × the 15) | +6 473 [−3 387, +16 562] P 0.14, 14/24 (placebo −18 081) | +838 [−1 136, +2 965] P 0.24 (placebo −1 178) | 157 / +1 363, Δ −1 316 [−2 542, −305] P 0.98 | Δ 0 |
| random-skip band (paper, 8 seeds) | — | — | rand10 mean −258 [−939, +176]; rand20 −479 | rand10 +31 [−478, +267] |

Full grids: 2y 81 variants + placebos + mirrors (all `rem` and `rw` cells negative with CI90 excluding 0 except
the three smallest-skip ones at P 0.95–0.96); oos2m post hoc grid printed, nothing above its own placebo; paper
split-half: 22 variants with Δ > 0 on the first half, 18 also on the second, but the chosen one is a placebo
(`sh24_thr8t_q1.0`) and the reverse direction agrees only 23 %; candle era 47 % / 41 %.

## Why it fails (the mechanism, with numbers)

1. **Reach is not persistent in ATR1 units.** The forecast and the next candle's reach correlate +0.21 / +0.31 /
   +0.23 (Pearson, 2y) and +0.03 / +0.09 / +0.05 (oos2m). The ATR1 normalisation removes exactly the part of the
   range that persists (the volatility level); what is left — the shape of the candle relative to its own 1-min
   steps — is close to white noise around √tf (median / √tf 1.12 / 1.20 / 1.28 on 2y, 1.03 / 1.11 / 1.13 on oos2m,
   1.15 / 1.27 / 1.37 on paper).
2. **The gate is therefore a progress × target-distance gate.** Replacing the forecast by the constant √tf (`rw`)
   reproduces every tier within noise and the 24-h placebo (same clock → same progress, own target) does too.
3. **And that gate removes the better entries.** On 2y tf 15 the entries where the candle "cannot reach" are the best
   cells (rem/D < 1: +3 … +5 per entry, PF 1.07–1.13, 31 % of entries) and the ones with the most room are the worst
   (rem/D ≥ 3: −4 … −7 per entry, PF 0.71–0.83, 4 %); the stop-out share does run the hypothesised way (71–73 % vs
   23–25 %, AUC(rem/D → stop) 0.38–0.39) but the risk-sized far targets pay for it. On oos2m the bins are flat or
   reversed (rem/D < 0.75 on tf 15 long −20 per entry, short +9…+23), on paper the lowest quintile of rw/D is the
   only negative one (−164, PF 0.90) and the rest are +206 … +1 249.

## Leads (reported, not claimed)

- **ATR1 level, not reach.** At the fire the absolute 1-min ATR relates to the outcome monotonically on 2y
  (Spearman(atr1_pct, pnl) −0.24 / −0.25 tf 15 long / short, −0.33 tf 60 long; the ≥ 0.2 % bins PF 1.00–1.03, the
  0.084–0.126 % bin PF 1.10–1.12) and on paper (atr1_rel −0.147, perm P 0.04; the fires sit in calmer minutes than
  random ticks: atr1_rel median 0.98 vs 1.20). oos2m tf 15 short inverts it (atr1_rel ≥ 1.3: +22 … +38 per entry,
  PF 1.4–1.9). The low-ATR veto (`dead_m1`) loses −6 820 on 2y, i.e. the quiet minutes are the good ones for the
  fade — the opposite of "low volatility = wait". A high-ATR1 veto was not in the grid; with the oos2m inversion
  it is not a strong lead.
- **Target distance.** The rem/D ≥ 3 cells (target within a third of the remaining reach: near target, early in the
  candle) lose −18 k on 2y over 4.6 % of the tf-15 entries, but are flat / positive on oos2m (+86 / +635) → a 2y-only
  pattern.

## Validity gates

| gate | number |
|---|---|
| null floor | paper random-skip band rand10 mean −258, max +176 over 8 seeds; the frozen gate +270 [−284, +800], P 0.20; era −21. 2y: every reach variant's CI90 excludes 0 on the negative side (frozen upper bound −568) |
| base rate | paired Δ vs the own e25 baseline per cell; 2y months with Δ > 0: 10/24 (reach), 6/24 (rw); oos2m 1/2; paper blocks > / < : 8 / 5 |
| degeneracy | the 2y selection lands on the grid boundary k = 0.5 for both reach and rw (the smallest skip) and N = 16 / norm t (the smoothest forecast) — the objective is "skip as little as possible" because every skip loses; the mirror keeps 40 % of entries and loses −96 k |
| truth ladder / ablation | reach forecast → √tf (`rw`): 2y −14 709 → −30 613, oos2m +761 → +151, paper +270 → +517, era −21 → +70; reach → 24-h-shifted: −23 008 / +855 / +180 / +115. The forecast adds nothing beyond progress × target distance |
| look-ahead | ATR1 of the last closed 1-min bar (paper: `ATR1[k_now − 1]`); reach from candles closed before the forming one (frame: candle id − 1 and earlier; paper: wall-clock key < current); progress wall-clock; the target is the fire's own cbnc bound; the rolling ATR median over the trailing 1440 closed rows |
| provenance | frozen names from the 2y `select()` block (`rem16t_a0.5_k0.5`, `rw_a0.5_k0.5`, `thr4t_q0.5`, `chop_a1.3_b0.8`, `dead_m1`, `eff_e0.25`, `lad240_r1.5`); oos2m scored once with them (the post hoc grid printed and labelled); paper variants carry the same names and constants (0.042 % fee round trip, √tf, N, α, k) |
| reproduction | stand-in e25 cells identical to the volume-flow stand-in (57 383 entries, +166 435 on 2y; 4 414, +15 827 on oos2m); paper: 202 simulated vs 207 recorded fires, 200 matched, 54/55 candle stops within half a tick; ATR1 rebuilt from trades median 0.0095 (0.078 % of price) |

## Disposition

Negative; no code-repo branch (read-only replay), scripts and outputs in `executor/runs/`. Register row closed.
