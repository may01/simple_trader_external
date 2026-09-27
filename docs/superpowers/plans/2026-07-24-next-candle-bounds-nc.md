# Next-Candle Bounds on Non-Closed Candles — Plan

**Date:** 2026-07-24
**Spec:** `experiment/next_candle_bounds_validation.md`
**Branch:** `next-candle-bounds-nc` (from `zone-selection-experiment` HEAD, in its worktree — the cb viewer wiring it builds on is uncommitted there)
**Data:** train `2y_az_link_usdt` (closed candles only), validate `oos2m_link_usdt` (per-minute).

## Semantics decision

The closed-candle algorithm (`experiment/candle_bounds_algorithm.md`) takes the latest
*closed* candle k−1 and predicts candle k's high/low. The non-closed (nc) variant feeds the
**forming candle k at minute t** through the same frozen models: at every 1-min row the
forming candle plays the "latest candle" role, so the prediction is the extreme of the next
~tf-minute window starting at t (a rolling-horizon bound). At candle k's closing minute the
forming features equal the closed features, so the nc prediction converges exactly to the
closed prediction for k+1 — a built-in parity check.

No re-training: models are fit once on 2y_az closed candles exactly per the algorithm doc
(Ridge α=1 on standardized 15 features, band = frozen train residual sd). The original
producer scripts were scratchpad-only and are lost; this branch re-implements them as
committed code and **gates on reproducing the stored closed-candle artifact**
(`df_with_candle_bounds.pkl` cb_high/cb_low on oos2m) before computing anything new.

## Steps

1. `notebooks/candle_bounds_nc/cbnc.py` — closed-candle feature builder (identical to
   algorithm doc), forming-row feature builder (running extreme, rolling stats via
   11-closed+1-forming decomposition), fit + inference.
2. Parity gate: refit on 2y_az → predict oos2m closed rows → must reproduce stored
   `{tf}_cb_high/low` (allclose). Abort otherwise.
3. NC inference per 1-min oos2m row, shift(1) (prediction from data through t−1 usable at t,
   same convention as the closed broadcast). Columns `{tf}_cbnc_{side}[,_std,_up,_dn]`.
4. Zones, recovered rule (frac = 0.05, same as current closed zones):
   `zone_long = lo + 0.05·span`, `zone_short = hi − 0.05·span`,
   `inzone_long = 1_low ≤ zone_long`, `inzone_short = 1_high ≥ zone_short`.
   Intersection: `{tf}_cbx_inzone_{dir} = cb_inzone ∧ cbnc_inzone`.
5. Artifact: `df_with_candle_bounds_nc.pkl` + `candle_bounds_nc_meta.json` next to the
   dataset (additive sidecar, same pattern as the closed one).
6. Metrics: per (tf, side) — MAE%, ±band coverage, r² vs realized candle-(k+1) extreme,
   bucketed by progress through the forming candle (converges to closed-model quality at
   1.0); forward-tf-window variant; zone counts + intersection counts + target-reach rates
   vs closed baseline. → results doc.
7. Viewer: `join_candle_bounds_nc()` in data.py (absence-safe), nc bound/band lines +
   `cbzone_nc` markers + intersection markers in data_viewer.py alongside existing.

## Out of scope

- `cb_hi_adj`/`cb_lo_adj` overlay (its ±1-band shift rule is from a lost scratch script,
  not required by the spec deliverables).
- `cb_enter_*` nc variant — enter = inzone ∧ a hidden NN-breakdown signal not independently
  recomputable; intersection markers use inzone. Noted in results.
- 2y nc computation (validation runs on oos2m; train uses closed candles only).
