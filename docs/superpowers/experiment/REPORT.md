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
| 2026-10-01 | [ev_line](ev_line.md) → [results](results/ev_line_results.md), [detail](results/extdone_zone_filter_results.md) | Place the entry between the candle-bound bands by probability (EV line), then by candle state (executed bound, extension quantiles) | partial | branch `ev-line-experiment` kept (off `zone-profitability` @ `2788110`, commit `60def30`, not pushed, not merged), worktree `worktrees/ev-line-experiment` alive |
| 2026-10-19 | cb_zone_run_stats ([spec](../specs/2026-10-19-cb-zone-run-stats-design.md)) → [results](results/cb_zone_run_stats_results.md) | Measure consecutive in-zone minutes per CB zone block to freeze the executor's expected-points stop parameter | success | branch `cb-zone-run-stats` @ `8c5f422` (worktree alive, not merged); frozen `15:2.0/2.0;60:3.0/3.0;240:4.0/4.0` |
| 2026-10-20 | sl_15m_anchor_replay ([run report](../../../executor/runs/2026-10-20-sl-15m-anchor-replay.md)) | Replay 21 h of the paper run with the CB stop anchored at the forming 15-min extreme instead of the entry; sweep the offset (today's distance, 0, 0.05–0.2 %, mean 1-min range/body, global and trailing) | partial (one day, in-sample; anchored stops lift win rate 29 → 41–69 %, all CIs overlap) | selected: forming-15m extreme ± trailing-60 mean 1-min range → executor spec `2026-10-20-cb-candle-stop-design.md`, branch `cb-candle-stop`; replay script + outputs beside the report |
| 2026-10-20 | [trend_x_sweep](trend_x_sweep.md) → [results](results/trend_x_sweep_results.md) | Sweep X in "1-min trade-MA slope outside ±X·σ is a trend" (today 0.7) through the paper executor's open gate and trend-flip exit on the recorded 4 days | partial (0.7 on the 0.6–0.85 plateau, nothing beats it; only X ≥ 1.5 / ∞ clearly worse; fee breakeven 0.021 %/side dominates) | no branch (read-only replay; script + output in executor/runs) |
| 2026-10-20 | [overshoot_ma_signal](overshoot_ma_signal.md) → [run report](../../../executor/runs/2026-10-20-overshoot-ma-replay.md) | In overshoot-vetoed zone minutes, take the side from a 3-/5-min trade-price MA class instead of skipping; replay the paper run's 58 h → [results](results/overshoot_ma_signal_results.md) | negative (ma3 +11 trades −74, ma5 +6 trades −127, no veto +19 trades −613; system net unchanged) | no branch (read-only replay over the executor DB); script + outputs in `executor/runs/` |
| 2026-10-20 | ma_window_by_tf_replay ([run report](../../../executor/runs/2026-10-20-ma-window-by-tf-replay.md)) | Replay the CB-era paper run (10-18 → 10-20) with the entry's trend MA lengthened to 3 / 5 min for the 60- and 240-min zones (15-min zone keeps 1 min); entry-only and entry+exit variants | negative (57.7 h, 135 positions: net +2 489 → +2 482 (3 min) → +2 128 (5 min); tf 60+240 subset +772 → +572 → +242, all inside the bootstrap noise; the slower MA fires the same zones 0.6–1.8 min later at a worse price and hands 6–8 trades to the 15-min target; follow-up 10 / 15 min on the 240 zone alone: +2 226 / +1 861, tf 240 +667 → +541 → +310, same keys up to 43 min later) | no branch (read-only replay; script + output beside the run report) — keep the 1-min class |
| 2026-10-20 | [extdone_stop_move](extdone_stop_move.md) → [results](results/extdone_stop_move_results.md), [run report](../../../executor/runs/2026-10-20-extdone-stop-move-replay.md) | While a CB zone position is open, the 15/60-min `extdone` of the entry bound (opposite to the target) moves the stop to entry ∓ Y·ATR(1 min), Y ∈ [0, 5]; replay the paper run, per position tf | partial (58 h, 136 positions: no trig-15/60 cell distinguishable from live +2 447 — t15 Y0 +0, Y1.5 +182, CIs ±900; Y ≥ 3 no-op vs the 2–2.5-ATR candle stop; tf-15 positions +67…+350 at every Y 0–3, tf-60 positions −71…−220 with the 15-min state, 60/240 states never on inside a position; profit-side lock-in negative on 58 h and 24 h) | no branch (read-only replay; script + outputs in executor/runs); candidate toggle = own-tf state, tf 15 only, Y ≈ 1.5 adverse side |
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

### 2026-10-01 · ev_line — partial

Placement is dead: Gaussian EV-best, 25 σ combos, 1,545 empirically replayed (entry, stop,
target) cells and six ATR shifts all net ≈ −0.20 % per fill on oos2m (gross ≈ 0; 0 of 150 sweep
cells net-positive; the 2y-selected empirical rule won 0 trades in 6 of 6 cells). Gaussian band
probabilities overstate win rate ×3–4 because a fill conditions against reaching the target.
Survivors: the executed-bound state (pull-away ≥ d(progress) 1-min ATRs) holds 0.93–0.96 on
oos2m with the ladder fit on 2y, against a 0.62–0.83 progress base rate; ATR-scaled
remaining-extension quantiles cover oos2m near nominal. Dead by-product: Ridge of extension on
market state (r² ≤ 0.26, scale only). Open for further investigation: EMA-25 slope classes
(fall / neutral / rise) — only +0.95 % / −0.09 % pinball as a quantile conditioner so far, but
now an in-code indicator (`ema_25_diff_prc`, `ema_25_slope_class`, frozen 2y stats). Trap hit: the first extdone ladder was picked on oos2m and scored row-based —
both corrected. Not P&L-validated: the vetoed zones were never replayed.

### 2026-10-20 · cross_tf_veto_replay — dead (one-day replay, executor paper data)

Higher-tf CB zone on the opposite side discarding a lower-tf fire: +101 USDT on 2026-10-20 (8 of 82 fires, all instant stop-outs), −143 on 2026-10-19 (3 of 3 were target exits), −158 over the 2.5-day history; every bootstrap CI straddles zero. Forbidding lower-tf reversals of higher-tf positions is clearly worse (−270 over the span). `any_zone` veto flat-to-positive on every window, kept as the toggle candidate. Report `external/executor/runs/2026-10-20-cross-tf-veto-replay.md`.

### 2026-10-20 · overshoot_ma_signal — negative (57.7 h replay, executor paper data)

In overshoot-vetoed CB zone minutes, taking the side from a 3-min / 5-min trade-price MA class instead of skipping adds 11 / 6 positions netting −74 / −127 USDT; the system's net is unchanged within noise (+2 451 / +2 488 vs +2 489). Lifting the veto adds 19 positions netting −613 (P(net<0) 0.94). Mechanisms: the veto removes minutes, not zones — with the once-per-(tf, side, zone) rule the check fires on the next passing minute, so only 19 fires in 2.4 days are actually lost; and the slower MA agreed with the 1-min class at 11 of 12 vetoed fires (`ma3_and ≡ ma3`). The slower class used everywhere is worse (+1 628 / +1 053). Run report `external/executor/runs/2026-10-20-overshoot-ma-replay.md`.

### 2026-10-20 · trend_x_sweep — partial (4-day replay, executor paper data, fires re-derived per X)

X = `TrendParams::std_mult` swept 0.01…∞ with the CB zone check re-run on every recorded trade against the
stored indicator snapshots (reproduction 141/152 recorded fires exact, class 140/141). Joint sweep: plateau
0.6–0.85 (+3 259…+3 513 USDT, 178 trades, PF 1.5, win rate 52 %), falling monotonically to +2 224 at sign-only
(X = 0.01) and +749 with no trend gate at all (X = ∞). Paired against 0.7, every X in 0.3–1.2 has a CI straddling
zero; only X ≥ 2 and ∞ are near-significantly worse (P(Δ<0) 0.92–0.95). The exit gate is indifferent in 0.01–1.0;
the entry gate carries the shape (narrow band → +15 stop-outs, wide band → rule 1 starves). Day-to-day best X
wanders 0.6–1.0. Keep 0.7. Gross edge ≈ 3.9 bp of notional per trade: breakeven fee 0.021 %/side — at 0.1 %/side
every X loses ~13 k over the window. Report `results/trend_x_sweep_results.md`.

### 2026-10-20 · ma_window_by_tf_replay — negative (57.7 h replay, executor paper data)

A slower trade-price MA as the entry class for the higher-tf CB zones: 3 / 5 min on tf 60 + 240 → net +2 489 → +2 482 / +2 128, the tf 60+240 positions +772 → +572 / +242; 10 / 15 min on tf 240 alone → +2 226 / +1 861 (tf 240 +667 → +541 / +310). All inside the bootstrap noise, mechanism uniform: the same (side, tf, zone) keys fire 0.6–1.8 min later (up to +43 min) at a worse price, the 15-min-anchored stop does not move, 6–8 tf-60 trades are taken first by the 15 zone and inherit its nearer target; slower MA on every tf is clearly worse (+1 723 / +1 042). Keep the 1-min class. Report `external/executor/runs/2026-10-20-ma-window-by-tf-replay.md`, summary `experiment/results/ma_window_by_tf_results.md`.

### 2026-10-20 · extdone_stop_move — partial (58 h replay, executor paper data)

Once the entry-side `extdone` (15 / 60 / own tf) is on, move the stop to entry ∓ Y·ATR(1 min), tighten only. The live
15-min candle stop already sits 2–2.5 ATR from the entry, so Y ≥ 3 is a no-op and the sweep is Y ∈ [0, 2]. Whole system:
+2 275 … +2 695 vs live +2 447, every trig-15/60 paired CI straddling zero (Y 0 turns 42 stop-outs into breakeven exits
but forfeits 10 targets + 9 reversals → net 0; Y 0.5–1 worst; Y 1.5–2 ±100). Per tf: tf-15 positions +67…+350 with the
15-min state at every Y (peak Y 1.5, one cell of 24 with a CI excluding zero, halves +1001/+1694 vs +797/+1650);
tf-60 positions −71…−220 (15-min state too early), and the 60-/240-min states never turn on inside a position (median
hold 8 min vs a 4–10 ATR ladder). `trans` (flip required) −330; `repl` (looser allowed) +150…+390 = the candle stop is
~0.5–1 ATR too tight, a separate hypothesis. Candidate forward toggle only: own-tf state, tf 15, Y ≈ 1.5. Follow-up 2026-10-21: moving the stop *into profit*
(`entry + Y·ATR` once reached) is negative on 58 h and on the last 24 h at every Y ≤ 1.5 and ≥ 3 (−216 … −751, the
Y 2 cell +47 / +118 is a spike between −723 and −504): the lock-in turns targets into stop-outs. Report
`results/extdone_stop_move_results.md`.
