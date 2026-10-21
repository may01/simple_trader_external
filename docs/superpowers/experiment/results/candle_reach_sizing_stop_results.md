# candle_reach_sizing_stop — Results & Conclusion

**Date:** 2026-10-21 · **Spec:** [candle_reach_sizing_stop.md](../candle_reach_sizing_stop.md) · **Branch:** none (read-only replay; docs on external `cross-tf-veto-replay`) · chains off [candle_reach_gate](candle_reach_gate_results.md)
**Data:** as candle_reach_gate (2y freeze 57 383 e25 entries / oos2m 4 414 / paper 186 positions over 78.4 h + candle era 53).
**Pipeline:** `executor/runs/2026-10-21-candle-reach-sizing-2y-oos2m.py` (output `…-output-h60.txt`, 173 s), `executor/runs/2026-10-21-candle-reach-sizing-replay.py` (outputs `…-output-full.txt`, `…-output-candle-era.txt`); run report [2026-10-21-candle-reach-sizing-replay.md](../../../../executor/runs/2026-10-21-candle-reach-sizing-replay.md).
**Frozen on 2y (best paired Δ vs live, all cells):** stop `st_reg_2.0_1.0` (offset × 2 when atr1_rel > 1.3, × 1 below 0.8; mean multiplier 1.206838); size `sz_apct_g0.5` (size ∝ √ATR1 %, normalised by 0.343212 = the 2y mean of √atr1_pct).

## Headline conclusion

**Negative.** Neither the stop-offset rules nor the risk-matched size rules built on the index survive the three tiers.
The frozen stop rule is noise on 2y (+7 910 [−7 214, +23 798], P 0.21), negative on oos2m (−2 858) and zero on paper
(+1 [−298, +368]). The frozen size rule is noise on 2y (+2 284 [−9 278, +13 650], P 0.38; net per $ risked 3.70 vs
4.05 live), the only tier where it scores is oos2m (+7 545 [+1 787, +13 006], P 0.01) and on paper it sits inside the
shuffled-multiplier band (+36 [−171, +253] vs −77 / −264 / −307; era +92 vs +3 / +23 / +76). No stop variant on 2y has a
CI90 excluding zero on the positive side; the 14-variant grid spans −40 568 … +7 910. What the stop-rule sweep does
confirm is the earlier stop-reentry finding: any *constant* widening of the candle-stop offset helps on paper
(`const` × 1.206838: +849 [−106, +2 067], P 0.08; `st_fc_g0.4` ≈ 1.7 ATR1: +733 on paper) and is noise on 2y / oos2m —
not an index effect.

## The progression

| variant | 2y Δ vs live (CI90, P, months+) | oos2m Δ | paper full Δ (6-h blocks) | paper era Δ |
|---|---|---|---|---|
| **stop** `st_reg_2.0_1.0` (frozen) | +7 910 [−7 214, +23 798] 0.21, 12/24 | −2 858 [−6 846, +1 358] 0.87 | +1 [−298, +368] 0.53 | −26 |
| ↳ shifted features (1440 rows / 24 h) | −15 196 | +267 | +52 | −197 |
| ↳ constant = its mean multiplier 1.206838 | −8 449 | −450 | **+849 [−106, +2 067] 0.08** | +99 |
| ↳ shuffled multipliers (3 seeds) | +2 407 / −20 372 / −9 564 | −745 / +2 210 / −1 363 | −177 / +194 / −156 | −87 / −131 / −88 |
| `st_arel_b-0.5` (stop in 24-h-median-ATR units; post hoc best on oos2m + paper) | −8 936 [−23 337, +6 321] 0.82, 9/24 | +5 694 [+1 027, +10 611] 0.03 | +913 [+410, +1 452] 0.00 | +346 [−73, +783] 0.07 |
| `st_rel_b{0.5,1,2}` (× reach ratio) | −6 075 / −20 039 / −38 274 | +253 / −2 444 / −1 869 | +526 / +82 / +167 | +174 / +127 / +106 |
| `st_fc_g{0.15,0.25,0.4}` (offset = g × fc8c_15 × ATR1) | −16 151 / −9 523 / −40 568 | +36 / −1 022 / −5 295 | +111 / +421 / +733 | +191 / +145 / +207 |
| **size** `sz_apct_g0.5` (frozen, ∝ √ATR1 %) | +2 284 [−9 278, +13 650] 0.38, 9/24; R 3.70 vs 4.05 | +7 545 [+1 787, +13 006] 0.01; R 4.64 vs 3.88 | +36 [−171, +253] 0.41 | +92 [−1, +207] 0.07 |
| ↳ shifted 24 h | −5 027 | +5 080 [+765, +9 223] 0.03 | −210 | +95 |
| ↳ shuffled (3 seeds) | −13 625 / −6 864 / −10 602 | +1 052 / +2 449 / +997 | −77 / −264 / −307 | +3 / +23 / +76 |
| `sz_apct_g1.0` | −1 134 | +14 189 [+3 801, +23 843] | −387 | +102 |
| `sz_arel_g{−1,−0.5}` (smaller in high vol, the gate experiment's lead) | −9 419 / −3 763 | −3 515 / −1 980 | −336 / −202 | −119 / −74 |
| `sz_ratio_g{−0.5,0.5}` | +452 / −11 514 | −2 981 / +671 | −461 / +254 | −192 / +143 |
| `sz_reg_{1.5,0.5}` / `{0.5,1.5}` | −9 577 / −9 971 | −3 882 / +3 196 | −328 / +119 | −89 / +82 |

Split-half on paper: 43 variants positive on the first half, 19 also on the second (44 %), the chosen one is the
constant control; era 39 %.

## Mechanism (why the size rule looks good on oos2m only)

At the entries the $-pnl falls with the ATR1 level (Spearman(atr1_pct, pnl) −0.24 / −0.25 tf 15, −0.33 / −0.35 tf 60,
−0.26 / −0.40 tf 240 on 2y) while the return per $ risked rises with it (+0.21 / +0.23, +0.26 / +0.32, +0.21 / +0.26):
the live sizing (100 / stop distance) already shrinks the position in high volatility, and in 2023–24 the high-vol
entries were the ones with the better R. Sizing ∝ √ATR1 % moves risk back to them. On oos2m the R correlation is
≈ 0 (+0.01 … +0.08) yet the rule gains +7 545 — through a few large high-vol winners in Jan–Feb 2025 (both months
positive, but the shuffled controls reach +2 449 and the day-shifted copy +5 080: the ATR level persists for days, so
the placebo is weak and the shuffle is the real null). On paper (78 h, ATR1 % 0.05–0.23) the rule is flat. With 2y
noise, oos2m signal and paper noise the rule fails the pass criterion (three tiers same sign above controls).

## Validity gates

| gate | number |
|---|---|
| null floor | shuffled-multiplier controls: 2y stop −20 372 … +2 407, size −13 625 … −6 864; oos2m stop −1 363 … +2 210, size +997 … +2 449; paper stop −177 … +194, size −307 … −77 (era −131 … −87 / +3 … +76). Frozen stop inside the band on every tier; frozen size above it on oos2m only |
| base rate / risk matching | size multipliers normalised to mean 1 over the 2y entries (constants frozen, applied unchanged to oos2m / paper); net per $ risked reported: size rule 3.70 vs 4.05 on 2y (worse), 4.64 vs 3.88 on oos2m; stop rule 4.13 vs 4.05 on 2y, 3.17 vs 3.88 on oos2m |
| degeneracy | the frozen stop multiplier is 1 on 67 % of the entries (atr1_rel between 0.8 and 1.3) — the rule acts on a third; the frozen size rule's 2y Δ is within the shuffle band's width (±10 k) |
| truth ladder / ablation | stop: real +7 910 vs its constant −8 449 vs shuffled −20 372 … +2 407 on 2y → the dispersion of the multipliers, not their alignment, drives the spread; paper: constant +849 ≥ real +1 → any widening helps, the index does not. Size: shifted-feature copy reproduces oos2m (+5 080 vs +7 545) → the ATR level, not the index timing |
| look-ahead | features of the last closed 1-min bar / closed candles as in candle_reach_gate; the stop multiplier is fixed at the fire; the size multiplier uses the live stop distance (no future) |
| provenance | frozen names from the 2y `select()` (all-cells paired Δ); normalisation constants printed by the 2y run and passed verbatim (`--norm`) to the paper harness; oos2m scored once (post hoc grid printed, labelled) |
| reproduction | stand-in live cells identical to candle_reach_gate's e25 (57 383, +166 203 ≈ +166 435 — the 2y live net differs by 232 because the entry simulation here runs on the entry set only and the trailing-range offset is read at the entry row, as in the gate stand-in; oos2m identical +15 827); paper 200/207 fires, 54/55 stops; era 56/58 |

## Disposition

Negative; no code-repo branch (read-only replay). Leads for a later experiment, none decision-grade: (a) a stop
offset in 24-h-median-ATR units (`st_arel_b-0.5`: tighter in high vol, wider in low vol) +5 694 oos2m / +913 paper,
−8 936 2y; (b) a constant ×1.1–2 widening of the candle stop on paper (already in the stop-reentry replay).
Hold-time / time-stop rules from the index were not tested.
