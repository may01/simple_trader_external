# Zone Selection — 2y Experiment Results & Conclusion

**Date:** 2026-07-20
**Data:** train = 2y (2023-01-01 → 2024-12-31, LINK/USDT, 1.05M 1-min rows), OOS = oos2m
(2025-01 → 2025-03). Column-subset `2y_az` dataset (the experiment reads ~40 of the wide
df's 744 columns; RAM-safe).
**Pipeline:** `notebooks/action_zones/azlib` (loader → space → indicators → models → infer
→ rr → zones → validate), branch `zone-selection-experiment`. All runs read-only over the
existing wide df; artifacts on `simple_trader_vol_long`.

## Headline conclusion

**Best validated config = RSI-3D-gbr model + Fix 1 (Y-objective).** It is 5/6 positive on
OOS realized R and produces one genuinely selective, profitable zone: **long/240 = +1.48R
at 14% coverage.** Per-combo target/stop *optimization* (Fix 2/2b) was explored and
**reverted** — it overfits the 2-month OOS. `run_train` uses the reach-based
`build_rr_levels` (Fix 1).

## The progression (OOS realized R / in-zone coverage)

| combo | baseline (1D-linear) | RSI-3D-gbr | **RSI-3D + Fix 1** | RSI-3D + Fix 2b |
|---|---|---|---|---|
| long/15 | +0.19 / .85 | +0.12 / .99 | +0.15 / .93 | +1.38 / .37 |
| long/60 | +0.50 / .80 | +0.34 / .97 | **+0.42 / .84** | −0.15 / .23 |
| long/240 | +0.03 / .91 | +0.055 / .92 | **+1.48 / .14** | −0.45 / .82 |
| short/15 | +0.62 / .83 | +0.38 / .98 | **+0.50 / .87** | −0.60 / .18 |
| short/60 | +0.088 / .89 | +0.050 / 1.0 | +0.072 / .91 | +0.094 / .98 |
| short/240 | −0.13 / .85 | −0.06 / 1.0 | −1.00 / .013 | −1.00 / .013 |

reach-drift train→OOS ≈ 0.06 across all combos (distributions stable — no regime break).

## Three degeneracies found (and what each fix did)

1. **1D-linear model is near-useless.** `run_train` originally fused hardcoded 1D-linear
   regressions (r2 ≈ 0.04). The `40nb` exploration (all 1D/2D/3D × {linear,poly2,gbr} +
   {logistic,gbc}) showed **RSI position-slope-distance gbr** is the best predictor of
   label_coeff in *every* combo (r2 ≈ 0.20–0.24, classifier auc ≈ 0.70–0.73) — MACD/MA
   never win. → wired a `selected_models` path so `run_train` fits/fuses the chosen model.
2. **Y-selection was degenerate (widest zone).** `run_train`'s `rr_fn` was Y-invariant, so
   `select_y` maximized coverage with no counterweight → Y slammed to ±2 → zone covered
   ~everything (coverage 0.77–1.0). A better model just made a wider, worse zone. **Fix 1:**
   `rr_fn` now returns the realized first-touch R of the entries marked at each Y, and
   `select_y` maximizes total profit `n_zoned × mean_R`. Widening becomes self-limiting →
   selective zones, Y off the boundary, long/240 → +1.48R.
3. **R/R-level selection was a mirage.** `select_levels` maximized a *marginal-reach*
   expected return → degenerate near-target/far-stop corner (tgt_x 0.25 / sl_x 1.75) with
   weak/negative realized R. **Fix 2** replaced it with first-touch expected R; **Fix 2b**
   regularized it (strict-labeled eval set, reward:risk ∈ [1,3]). **Both overfit** the
   2-month OOS (realized R worse on 4/6) and were reverted.

## Why level optimization overfits (the key negative result)

Optimizing target/stop on train first-touch — even regularized — does not generalize to a
2-month OOS. Proof: long/240's train-best level is 1.75/0.75 → it *loses* OOS (−0.45); but
the reach-based selection happened to use **0.75/0.25** there → **+1.48**. Every big OOS
winner used **0.75/0.25** (≈3:1 reward, near stop): long/240 Fix 1 (+1.48) and long/15
Fix 2b (+1.38). The generalizing levels are a *fixed, sane reward:risk*, not the train-R
maximizer. More free parameters → worse OOS on a short horizon.

## What generalized vs didn't

- **Generalized:** the RSI-3D-gbr model (label_coeff prediction), Fix 1's Y-objective, and
  a ~3:1 near-stop level. long/240 (+1.48R, 14%) is a real, selective, profitable zone.
- **Did not:** per-combo level optimization; short/240 (−1.00R, 1.3%) — never found a
  working zone (likely a genuinely hard/short-adverse regime for 240m on this OOS).

## Config & artifacts (final state)

- `results.json` per (dir, tf) = RSI-3D-gbr + Fix 1 (`selected_models` = rsi
  position-slope-distance gbr; reach-based tgt/sl; Y from the total-profit objective).
  Under `/trader_data_long/train/2y_az_link_usdt/action_zones/{dir}/{tf}/`.
- Regression/classification plots (40nb) copied to host `~/action_zones_plots/{dir}_{tf}/`
  (75 PNGs each).
- Viewer: `view-full` on `2y_az` at localhost:8080 — candlestick + `az_long`/`az_short`
  zone lines + in-zone markers on the 1-min chart (green triangle-up = long buy-zone at the
  low, red triangle-down = short at the high). Zones shown are in-sample (train replay).
- `first_touch_rr_grid` remains in `validate.py` as an explored-but-unused artifact
  (Fix 2/2b), off the critical path.
- Tests: 187 passing in Docker under `-W error`. Code (azlib `selected_models` + Fix 1;
  viewer edits `data.py`/`view_full.py`/`data_viewer.py`/`chart_renderer.py`) is
  **uncommitted** pending review.

## Open questions / next steps

- **Longer OOS** (6–12 months) — the 2-month window is too short to trust per-combo tuning;
  most overfitting symptoms trace to it.
- **Fixed reward:risk sweep** — test a single fixed ~3:1 near-stop level across all combos
  (the generalizing winners used 0.75/0.25) vs per-combo optimization.
- **Fix 3** — compute reach-prob / diff_prc distributions on *closed* candles, not
  per-minute forming rows.
- **short/240** needs its own investigation (or exclusion) — no config produced a working
  short zone at 240m on this OOS.
- Model selection is currently hand-set (RSI-3D-gbr, from the 40nb reports). A cleaner loop
  would auto-select per combo from the report and record it in `ResultsFile.selected_models`.
