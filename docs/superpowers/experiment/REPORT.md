# Experiment register

One row per experiment. Append a row when an experiment starts, fill the verdict and
disposition when its results report is approved. This file is the answer to "what have we
already tried, and how did it end" — never delete a row.

**Verdict values:** `success` (hypothesis held, promoted) · `partial` (real effect, not
decision-grade) · `negative` (hypothesis died) · `running` · `not started`
**Disposition values:** `merged → <branch>` · `pushed, worktree removed` · `branch kept` ·
`no branch (read-only)` · `n/a`

## Register

| date | experiment | idea in one line | verdict | disposition |
|---|---|---|---|---|
| 2026-07-20 | [zone_selection](zone_selection.md) → [results](results/zone_selection_2y_results.md) | Predict a candle's high/low bounds, place buy/sell zones inside them by RSI/MACD/MA regression on label position | partial | branch `zone-selection-experiment` kept, worktree alive |
| 2026-07-21 | [candle_bounds_estimation](candle_bounds_estimation.md) → [results](results/candle_bounds_estimation_results.md) | Predict next-candle extension from RSI-group features (Ridge) | partial | no branch (read-only, scratchpad scripts — later recommitted by the NC round) |
| 2026-07-22 | [asymmetry model](results/asymmetry_model_results.md) | Predict which side of the candle extends further, instead of direction | partial | no branch (read-only) |
| 2026-07-22 | [event bars](event_bars_results.md) | Resample by event rather than clock time to sharpen direction prediction | negative | no branch (read-only) |
| 2026-07-22 | rsi quantile/sym0 classification ([spec](../specs/2026-07-22-rsi-classification-quantile-sym0-design.md)) | Classify RSI-slope into 5 symmetric-around-zero market-state classes | success | merged → `experimental_imp_2` (branch `rsi-quantile-sym0`, worktree still present) |
| 2026-07-23 | [trend_detection](trend_detection.md) → [results](trend_detection/results.md) | Split strong-move RSI points into long-favourable and short-favourable classes | negative | branch `trend-detection-experiment` kept, uncommitted, worktree alive |
| 2026-07-24 | [next_candle_bounds_validation](next_candle_bounds_validation.md) → [results](results/next_candle_bounds_nc_results.md) | Recompute bounds every minute on the forming candle instead of once per closed candle | partial | branch `next-candle-bounds-nc` kept, not merged |
| 2026-07-24 | [nn_zone_filtered_training](../plans/2026-07-24-nn-zone-filtered-training.md) → [results](results/nn_zone_filtered_training_results.md) | Train the NN only on rows inside the nc entry zones | success | branch `nn-zone-filtered-training` kept, not merged |
| 2026-08-06 | [rsi_parameters_selection](rsi_parameters_selection.md) → [results](results/rsi_parameters_selection_results.md) | Pick the RSI ma window, class count and cut technique that best separate profit labels | success | merged → `experimental_imp_2` @ `d2aeece`, branch removed |
| 2026-08-07 | [zone_profitability](zone_profitability.md) | Shift the bound per move class to a zone holding the most profitable points | partial | branch `zone-profitability` kept, uncommitted, worktree alive |
| — | [color_prediction](color_prediction.md) | Predict next candle colour | not started | n/a |
| — | [nn_signal_validation](nn_signal_validation.md) | Validate NN signals end to end | not started | n/a (spec empty) |

## Entries

### 2026-07-20 · zone_selection — partial

Bounds plus regression of label position give one genuinely selective zone: long/240 at
+1.48R on 14% coverage, 5/6 combos positive OOS. Per-combo target/stop optimization was
explored and reverted — it overfits a 2-month OOS. What generalized: the RSI-3D-gbr model,
the total-profit Y objective, and a fixed ~3:1 near-stop level. What did not: any per-combo
level tuning, and short/240 in every variant.

### 2026-07-21 · candle_bounds_estimation — partial

Real, stable, weak: r² ≈ 0.02 OOS, identical to train, correlation 0.16–0.18 on all six
combos. Shifts the band centre ±0.3σ against a 0.88σ residual. Kept as a band producer,
never as a standalone level sizer.

### 2026-07-22 · asymmetry model — partial

Asymmetry is more predictable than direction (AUC 0.57–0.75 vs null 0.50–0.56) but does not
convert to net-positive R on this OOS under a fixed config. Retired as a standalone edge;
worth revisiting on a longer OOS.

### 2026-07-22 · event bars — negative, and the valuable kind

Event bars sharpen range prediction but leave direction AUC at ~0.50. Pre-registered
criterion said range gain alone does not justify the pipeline rebuild. Established that the
range/direction split is structural, not a sampling artifact.

### 2026-07-22 · rsi quantile/sym0 classification — success

Produced the `{tf}_zone_class_q` / `{tf}_move_class_sym0` columns used by every later
experiment. Merged.

### 2026-07-23 · trend_detection — negative

Headline AUC 0.94–0.99 decomposed to label mechanics: strict 0.94 → plain 0.56 → pure
forward return 0.51. The clean-entry gate accounted for essentially the whole score. Salvage:
`bb_dist_up`, `swing_dist_hi` are future-only separator candidates. Left uncommitted by spec.

### 2026-07-24 · next_candle_bounds (non-closed) — partial

Per-minute forming-candle bounds raise reach-of-target to 0.57–0.73 versus 0.11–0.15 for
closed zones, and three reproduction gates matched the old pipeline to ~1e-15. Not
P&L-validated: the gain is target proximity, not entry selection. Realized R with fees is
the required next arbiter.

### 2026-07-24 · nn_zone_filtered_training — success

Zone-filtered models beat unfiltered ones on zone rows, 6 of 6 combos on precision@5.
Introduced the `filter_column` dataset path and a two-pass build to survive 2y memory limits.

### 2026-08-06 · rsi_parameters_selection — success

Chose the 7-class sym0 scheme; cuts frozen in `indicators/library/classification.py`. The
direction edge is inverted: steep RSI fall is the long edge. Also produced the MI null-floor
lesson — the top of both mechanical rankings was small-sample bias at TF240. Merged.

### 2026-08-07 · zone_profitability — partial

Extreme move classes hold OOS (15/−3 long 29.3% winrate vs 6.8% base, 25.5% OOS); middle
classes lift only 1.3–1.4×. No open/target pair beats breakeven inside the candle horizon.
Scoring rule had to be fixed twice mid-run: EV degenerated to the fewest-points cell, and
the target margin argmax picked zero-reach corners. Left uncommitted.
