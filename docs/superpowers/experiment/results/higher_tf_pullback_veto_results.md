# higher_tf_pullback_veto — Results & Conclusion

**Date:** 2026-10-21 · **Spec:** [higher_tf_pullback_veto.md](../higher_tf_pullback_veto.md) · **Plan:**
[plans/2026-10-21-higher-tf-pullback-veto.md](../../plans/2026-10-21-higher-tf-pullback-veto.md) · **Branch:** none
(read-only replay; scripts + outputs in `executor/runs/`) · **Run report:**
[executor/runs/2026-10-21-higher-tf-pullback-replay.md](../../../../executor/runs/2026-10-21-higher-tf-pullback-replay.md)
**Data:** paper exports of the `cbov-check` executor (10-16 22:29Z → 10-21 10:07Z, window 10-17 22:00Z → 10-21 10:07Z,
84 h, 188 recorded CbZoneEntry fires); 2y (2023-01 → 2024-12, 1 052 560 rows) and oos2m (2025-01 → 2025-03, 84 961 rows)
1-min frames with the candle-bounds / cbnc sidecars and `1_atr_14_ma_5`.
**Pipeline:** `2026-10-21-higher-tf-pullback-replay.py` (imports the higher_tf_trend_filter harness) and
`…-pullback-2y-oos2m.py` (its tier-B stand-in + kernel-ported extdone); hold 60.
**Final configuration:** veto per (tf, side) = own forming EMA-25 flag ∧ ¬PB_side(H); PB ∈ {xd, cf0, cf−, ovc, ov30, any,
xdcf}; pairs 15←60, 15←240, 60←240, ladder; controls mirror and ±24 h shifted state. Frozen 2y params
(`EXTDONE_LADDER`, `OVERSHOOT_THR`, `EMA_SLOPE_STATS`); nothing fitted on the window or on oos2m.

## Headline conclusion

The hypothesis died. Discarding a lower-tf CB zone entry in the higher tf's trend direction while that higher tf
pulls back does not help: on 84 h of paper the best real variant is +178 vs e25 +3 783 (P(Δ<0) 0.30) while the
shifted-state placebo scores +912 (P 0.01); on 2y every 15-min variant loses −8 702 … −79 598 (P 0.94–1.00) and the
placebo loses as much as the extdone veto (−24 759 vs −28 562); on oos2m every 15-min variant loses −961 … −11 455.
The entries the rule removes are of average quality (2y, mean +2.05 vs +2.16 per trade) or better (against the
240-min pull-back PF 2.80 on paper, 1.11 vs 1.04 on 2y; oos2m 15←60 long PF 1.27 vs 1.04). Not proven: nothing — the
flow has no edge to protect here. Fees: breakeven 0.019–0.025 %/side on every variant, unchanged.

## The progression (paired Δ vs e25; paper 84 h / 2y 24 months / oos2m 2 months)

| variant | paper Δ (P) | 2y Δ (P, months +) | oos2m Δ (P) |
|---|---|---|---|
| hx15<60 (static veto, sibling) | −1 051 (0.93) | −3 998 (0.69, 13/24) | +2 695 (0.15) |
| xd15<60 | −276 (0.69) | −28 562 (1.00, 6/24) | −4 639 (0.96) |
| cf015<60 | +178 (0.30) | −8 702 (0.94, 11/24) | −961 (0.69) |
| ovc15<60 | −310 (0.69) | −18 407 (0.99, 8/24) | −3 563 (0.92) |
| any15<60 | −297 (0.62) | −49 832 (1.00, 5/24) | −7 806 (0.98) |
| xd60<240 | −71 (0.56) | +990 (0.43, 11/24) | +2 097 (0.08) |
| cf060<240 | 0 | +3 860 (0.12, 16/24) | −2 068 (0.96) |
| anyladder | −1 755 (0.94) | −79 598 (1.00, 3/24) | −11 455 (0.99) |
| mir15<60 (control) | −336 (0.76) | −28 887 (1.00, 4/24) | +84 (0.47) |
| sh+15<60 (placebo) | −563 (0.87) | −24 759 (1.00, 8/24) | −483 (0.60) |
| sh−15<60 (placebo) | +912 (0.01) | — | — |

## Degeneracies found

1. **cf− never fires** — at X 0.5 a closed +1 class cannot become a forming −1 within one candle; the variant equals
   e25 on every tier. Dropped from the conclusions.
2. **Placebo ≥ real** — on paper the shifted state is the best variant; on 2y it loses as much as the real one. The
   paper tier cannot resolve ±900 USDT on 84 h, and on 2y the loss of any veto is the removed entries' mean value,
   not a quality effect.
3. **Sign flips by side and tier** — the 15←60 cf0 cell is the worst for longs on 2y (PF 1.00) and the best for shorts
   (PF 1.14); on oos2m the xd long cell flips from equal to PF 1.27. No state is stable.

## Validity gates

| gate | number |
|---|---|
| Null floor / placebo | sh+15<60 −24 759 (2y) vs xd15<60 −28 562; paper sh−15<60 +912 vs best real +178 |
| Base rate | e25 2y PF 1.05–1.09, mean +2…+4 per entry; every removed cell has mean ≥ 0 except cf0 long (−0.01) and 60←240 (−3.55) |
| Degeneracy | cf− = 0 rows; cf0 on H 240 Buy = 0 (240 class never +1 in the window) |
| Truth ladder | paper (live flow) → 2y stand-in → oos2m: the sign of the 15-min variants is negative on all three |
| Feature ablation | three independent state families (extdone, slope transition, overshoot retreat) + their union: same sign |
| Look-ahead | stored indicators by received_at ≤ t with expiry; kernel extdone from the forming running extreme and the row's close; shifted placebo sh− is the one future-looking control and is labelled as such |
| Provenance | `EXTDONE_LADDER` / `OVERSHOOT_THR` / `EMA_SLOPE_STATS` = frozen 2y values; stored `cb_f_extdone == !extdone` 1.0000 |
| Reproduction | 177 / 188 fires exact (live flags); kernel extdone means within ±0.03 of the stored stream per tf |

## What survives (not the question)

The **mirror** cell — a lower-tf entry *against* the higher tf's done extreme — is the best cell on 2y (tf 15 by 60:
PF 1.17 / 1.34 long / short; tf 60 by 240 long 1.45) and mixed on oos2m (1.12 / 0.87 / 1.21 / 1.31). Together with
the sibling's finding (counter-trend 15-min entries PF 2.43) it points at a *positive* filter ("fade the higher-tf
extreme"), to be posed as its own experiment with a null and an oos2m score. Recorded as a lead only.

## Disposition

Negative; no code change, no branch; register row closed. Locked decisions were the author's assumptions (user not
available) and are listed in the spec.
