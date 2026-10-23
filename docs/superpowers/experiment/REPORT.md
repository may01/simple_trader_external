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
| 2026-10-21 | [trend_ma_length](trend_ma_length.md) → [results](results/trend_ma_length_results.md), [run report](../../../executor/runs/2026-10-21-trend-ma-length-replay.md) | CB zone trend filter from the EMA-7 / EMA-14 slope class instead of the EMA-25 (forming class, 2y-frozen thresholds); paper-run replay + 2y / oos2m entry stand-in | negative (EMA-14 Δ +168 / −3.8 k / −1.9 k inside noise; EMA-7 −383 / −22.8 k (P 0.95) / −10.5 k (P 0.97); side: no flag +968 / +71.6 k / +10.6 k, closed-candle class ≥ forming) | no branch (read-only replay over the executor DB + host run over the frames); scripts + outputs in `executor/runs/` |
| 2026-10-21 | [rule2_removal](rule2_removal.md) → [results](results/rule2_removal_results.md), [run report](../../../executor/runs/2026-10-21-rule2-removal-replay.md) | Remove the CB zone entry's rule 2 (previous 1-min candle wick crossed the zone and closed back, MA neutral-or-direction) and keep rule 1 only; fire-re-deriving replay of the paper run 10-18 → 10-21 (70.4 h), plus rule-2-only ablation | negative (no measurable change: +2 694 → +3 073, paired Δ +378 CI [−788, +1 542] P 0.29, 16 % fewer trades, PF 1.42 → 1.62; last 24 h −258, candle-stop era −167, previous 24 h +50 — sign flips by window; rule 2 fires the same zones a few minutes earlier, only 30/183 keys are rule-2-only, worth +289) | no branch (read-only replay; script + outputs in executor/runs) — keep rule 2 |
| 2026-10-21 | [stop_reentry_pairs](stop_reentry_pairs.md) → [results](results/stop_reentry_pairs_results.md), [run report](../../../executor/runs/2026-10-21-stop-reentry-replay.md) | Stop-out at the zone's start followed by a same-side re-entry minutes later from a better price: how often, what it costs, which rule change fixes it (cooldown, wider stop, anchor, deeper entry, candle-minute skip, half size, zone-bound stop) | partial (43 % of simulated stop-outs start such a pair, first legs = 43 % of all stop money −2 795 / −6 560 in 71.6 h, second legs +226 with 17/35 stopped again; stop offset × 2 / 2.5 +605 / +636 full (P 0.21 / 0.11), +363 era, stop-outs 82 → 54 / 43, plateau 1.5–2.5; cooldown −348 … −473 era (P 0.96–0.97), deeper entry, half size, candle-skip dead; anchor variants no-op) | no branch (read-only replay; scripts + outputs in executor/runs) — candidate `CB_STOP_RANGE_MULT` ≈ 2 |
| 2026-10-21 | [cci_entry_quality](cci_entry_quality.md) → [results](results/cci_entry_quality_results.md), [run report](../../../executor/runs/2026-10-21-cci-entry-quality.md), [2y plan](../plans/2026-10-21-cci-entry-quality-2y-test.md) | Map main/'s CCI-14 (5- / 15-min candles) onto the executor's CB zone fires; does the signed CCI at the fire predict the stop-out / pair-P1 and would 'adv ≥ 140 → wait for a better price (limit δ·range)' or 'skip' help; 2y / oos2m test designed | partial (paper run inconclusive: U-shaped, AUC 0.49 / 0.51, permutation P 0.18 / 0.11; skip ≥ 140 +133 / +359 full P 0.41 / 0.32, era +436 / +113; wait −483 … +67, every-fire control −2 448 P 0.99; 2y test not run) | no branch (read-only replay; `cci_lib.py` + map script + replay variants in executor/runs); 2y plan in plans/ |
| 2026-10-21 | [higher_tf_trend_filter](higher_tf_trend_filter.md) | Veto / align a lower-tf CB zone entry (15 / 60) by the higher tf's trend flag (60 / 240, forming EMA-25 slope class): 15←60, 15←240, 60←240, ladder, replace / aligned / closed variants; paper-run replay + 2y / oos2m stand-in | running | — |
| 2026-10-21 | [higher_tf_pullback_veto](higher_tf_pullback_veto.md) → [results](results/higher_tf_pullback_veto_results.md), [run report](../../../executor/runs/2026-10-21-higher-tf-pullback-replay.md) | Veto a lower-tf CB zone entry in the higher tf's trend direction while the higher tf is PULLING BACK (extreme done / EMA-25 class left +1 / overshoot retreat), 15←60, 15←240, 60←240, ladder; mirror + shifted-state controls; paper-run replay + 2y / oos2m stand-in | negative (paper best real +178 vs placebo +912; 2y every 15-min pair −8.7 k … −79.6 k P 0.94–1.00, placebo −24.8 k ≈ xd −28.6 k; oos2m −1 k … −11.5 k; removed entries average or better; 60←240 only consistent-sign cell, thin and oos2m-contradicted) | archived 2026-10-21 — no branch (read-only replay; scripts + outputs in executor/runs), committed on `cross-tf-veto-replay` |
| 2026-10-21 | [cci_zone_excursion](cci_zone_excursion.md) → [results](results/cci_zone_excursion_results.md) | 2y / oos2m: CCI-14 (5 / 15 min) at CB zone entry and at the strict-marker minutes; in-zone excursion beyond the current extreme in 1-min ATR by CCI level → delayed entry / stop placement | partial (zone entered at adv5 ≈ +66 / +120 / +110 for tf 15 / 60 / 240; strict marker P rises with adv: tf 15 0.12 → 0.18–0.21 at ≥ 200, entry minute 0.24–0.33, oos2m same; excursion to candle close q50 0.7 / 1.7 / 3.6 ATR1 by tf, CCI adds 0.1–1.3 at the top bins, 100 ≈ 140 ≈ p90; memoryless in δ: P(+1 ATR1 | filled) 55 / 75 / 85 %) | no branch (read-only; script + 2 outputs in executor/runs); use: tf 15 entry +0.5–1 ATR1, stop +2–3 ATR1 |
| 2026-10-21 | [higher_tf_bounds_geometry](higher_tf_bounds_geometry.md) → [results](results/higher_tf_bounds_geometry_results.md), [run report](../../../executor/runs/2026-10-21-bounds-geometry-replay.md) | How the CB bounds of 15 / 60 / 240 connect (spans, nesting, bound coincidence) and the higher tf's range position / executed opposite bound as a veto on the lower-tf CB zone entry (the user's "15 low bound ≈ 60 low bound, 60 keeps rising, 15 short from the high bound fails" case); paper-run replay + 2y fit / oos2m score | negative (entries at the wrong end of the higher range are the BEST cells — 2y tf 15 short f < 0.2 of the 60 range PF 1.20–1.29 vs 1.09; pos0.15 15←60 −32 488 2y P 1.00 / −4 416 oos2m / paper +80 inside the placebo +355; ladder −51 400; user-case cell PF 1.00 / 1.07 2y, flips oos2m; only exz 60←240 consistent +4 000 / +2 258 P 0.25 / 0.10, thin) | no branch (read-only replay; scripts + outputs in executor/runs) — no toggle |
| 2026-10-21 | [half_atr_stop](half_atr_stop.md) → [results](results/half_atr_stop_results.md), [run report](../../../executor/runs/2026-10-21-half-atr-stop-replay.md) | CB zone stop = forming 15-min high/low ∓ 0.5 × ATR(1 min) instead of ∓ 1.0 × trailing-60 mean 1-min range; paper-run replay 10-18 → 10-21 (77.6 h) + candle-stop era, offset sweep 0.25–2.5 × ATR1, 1-min / fire anchors, live-sizing ablation | negative (Δ +348 full P 0.25 / +266 era P 0.14; placement alone +20 / +186 — the rest is risk sizing (cap 67 → 81 %); null floor atr10 vs live +292; sweep non-monotone 0.25 +593 / 0.75 +875 / 2.0 +590 → live is a local minimum = noise on 186 positions; 1-min-bar anchor +853 P 0.06 / +829 era carried by 10-21, in-sample lead only; every 15-min-anchored variant negative at 0.02 %/side) | no branch (read-only replay; script + 2 outputs in executor/runs) — keep the live offset |
| 2026-10-21 | [same_side_zone_gap](same_side_zone_gap.md) | A close higher-tf zone on the SAME side as a lower-tf CB zone fire (signed gap entry → 60 / 240 zone line, in stop units and stop-distance units): veto the lower fire, or delay it to a limit at the higher zone; placebo + opposite-zone control; paper-run replay + 2y fit / oos2m score | running | — |
| 2026-10-21 | [volume_flow_entry_filter](volume_flow_entry_filter.md) → [results](results/volume_flow_entry_filter_results.md) | 1-/5-/15-min volume, 5-min buy−sell flow and the book-depletion markers at the CB zone fire vs the position outcome; entry filters replayed through the paper executor (paired blocks, placebos, split-half) and the flow part on 2y / oos2m | partial (paper: climax-volume / 60-min-marker skips +700…+900 on +2 679, P 0.00–0.07, both halves; flow direction dead; nothing holds on 2y / oos2m) | no branch (read-only replay over the executor DB + stored frames; scripts in `executor/runs/`) |
| 2026-10-21 | fired_state_removal → [run report](../../../executor/runs/2026-10-21-fired-state-removal-replay.md) | Remove the CB zone entry's once-per-(tf, side, zone) fired-state (cb_zone_entry.rs:284-311): is a second open in the same tf candle blocked after a stop-out (yes, outcome-blind), and what does lifting it do — variants nofired / clear-on-exit / clear-on-stop; paper-run replay 10-18 → 10-21 (78.5 h) + candle-stop era + 24-h slices, re-entries scored by the earlier leg's close reason | running | no branch (read-only replay over the executor DB; script + outputs in `executor/runs/`) |
| 2026-10-21 | [candle_reach_gate](candle_reach_gate.md) → [results](results/candle_reach_gate_results.md) | Per-tf candle reach (tf range in 1-min ATRs, median of last N closed candles) as an entry gate: skip the CB fire when the forecast remaining reach cannot cover the target distance; 2y freeze → oos2m → paper replay | negative (reach in ATR1 units ≈ white noise around √tf, lag-1 ≤ 0.2; gate = progress × target distance, √tf control reproduces it; 2y −14 709 P 0.95, oos2m +761 noise, paper +270 inside the rand10 band, placebo +180) | no branch (read-only replay; scripts + outputs in `executor/runs/`) |
| 2026-10-21 | [candle_reach_sizing_stop](candle_reach_sizing_stop.md) → [results](results/candle_reach_sizing_stop_results.md) | Volatility index (ATR1 level, candle reach) as a stop-offset multiplier and a risk-matched size multiplier on the CB entries; 2y freeze → oos2m → paper replay | negative (stop: 2y +7 910 P 0.21, oos2m −2 858, paper +1, inside shuffled band; size ∝ √ATR1 %: 2y +2 284 P 0.38, oos2m +7 545 but placebo +5 080, paper +36 inside band; only constant stop widening moves paper) | no branch (read-only replay; scripts + outputs in `executor/runs/`) |
| — | [color_prediction](color_prediction.md) | Predict next candle colour | not started | n/a |
| — | [nn_signal_validation](nn_signal_validation.md) | Validate NN signals end to end | not started | n/a (spec empty) |
| 2026-10-21 | release_001 stop vs live candle stop (post-pivot replay) → `executor/runs/2026-10-21-rel001-vs-candle-stop-replay.md` | Replay the 23 h since the 2026-10-20 20:21Z restart under the release_001 rule (order-book stop + 1 % placeholder) vs the running candle stop + 0.2 % placeholder; profit difference from the pivot | partial | no branch (read-only, external runs/) — release rule ≈ +440 USDT more over 23.4 h sim-vs-sim (CI [−442, +1 267]), opposite sign of the 2026-10-20 replay; not decidable |

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

### 2026-10-21 · rule2_removal — negative (70.4 h replay, executor paper data)

The CB zone entry without rule 2 (previous 1-min candle wick crossed the zone and closed back, MA neutral-or-direction):
fire-re-deriving replay of the paper run 10-18 11:41Z → 10-21 10:05Z, 181/188 recorded fires reproduced. Rule 1 only:
168 → 141 positions, net +2 694 → +3 073 (paired 6-h-block Δ +378, 90 % CI [−788, +1 542], P(Δ<0) 0.29), PF 1.42 → 1.62;
candle-stop era −167, last 24 h −258, previous 24 h +50 — the sign flips by window. Rule 2 alone +2 094 (full) but the best
variant in the candle-stop era. Mechanism: 153 of the 183 live fire keys also fire by rule 1 (117 same minute, 36 up to
12.6 min later); the 30 rule-2-only zones are worth +289; rule 2 = "the same zone a few minutes earlier, before the MA
confirms". Keep rule 2; the only consistent effect of removal is 16 % fewer trades (fee exposure). Report
`results/rule2_removal_results.md`, run report `executor/runs/2026-10-21-rule2-removal-replay.md`.

### 2026-10-21 · trend_ma_length — negative (84 h paper replay + 2y / oos2m entry stand-in)

The CB zone trend filter (`cb_f_trend`, forming EMA-25 slope class) rebuilt from the EMA-14 / EMA-7 with the same
2y-frozen ±0.5σ recipe. EMA-14: +168 USDT on the paper run (CI90 [−825, +1 201]), −3.8 k / −1.9 k over 2y / oos2m —
noise everywhere. EMA-7: −383 on the paper run, −22.8 k (P 0.95) / −10.5 k (P 0.97) over 2y / oos2m, worst on the
15-min zones (the fast class vetoes the bounce while its slope still points against). Gates: 177/188 recorded fires
reproduced, flag reconstruction 99.1–99.9 % per cell, live `EMA_SLOPE_STATS` reproduced to 1e-16 (mean) from the
stored 2y EMA. Side findings: every weakening of the veto beats live (no flag +968 / +71.6 k CI90 [+39.7 k, +105.6 k] /
+10.6 k; X 1.0 +0.9…+1.1 k), sign-only loses 1.9–2.6 k; the closed-candle EMA-25 class beats the forming one (+22.4 k
P 0.01 / +5.3 k P 0.06 / ±0). Report `results/trend_ma_length_results.md`.

### 2026-10-21 · stop_reentry_pairs — partial (71.6 h paper replay + recorded positions)

User observation confirmed: under the running candle stop, 35 of 82 simulated stop-outs (43 %; recorded 13/71 and
4/22 at 18 %) are the first leg of "stop → same side re-entry ≤ 15 min later from a better price"; those first legs
are −2 795 of −6 560 stop money, the second legs +226 (17/35 stopped again, gap median 1.9 min, 23/35 beyond P1's
stop). Mechanism: the fire is the extreme, the stop anchors on it (41/42 era fires rolling-15 = forming extreme),
1.8–2.1 mean ranges from entry inside a zone 2–4 stops deep; the zone value moves every minute so once-per-zone
never blocks the second fire. Fixes: stop offset × 2 / 2.5 +605 / +636 full (P(Δ<0) 0.21 / 0.11), +363 era, stop-outs
82 → 54 / 43, PF 1.38 → 1.58 / 1.71, plateau 1.5–2.5 (× 3 −163) — the only one with the right sign on both windows;
entry-side `cbnc`-bound stop neutral (+151 / −54); cooldown 5 / 15 / 30 min dead (removes the positive P2 legs;
era −348 / −473, P 0.97 / 0.96); deeper entry −334 / −1 819 full; half-size first leg −936 (P 0.99); candle-minute
skip and anchor variants no-op. Gates: 184/191 fires, 39/40 stops reproduced. Report
`results/stop_reentry_pairs_results.md`, run report `executor/runs/2026-10-21-stop-reentry-replay.md`.

### 2026-10-21 · cci_entry_quality — partial (paper-run mapping; 2y test designed, not run)

main/'s `cci_14` (last 104 closed tf candles + forming, talib) recomputed from the executor trade feed (gate 5e-11 vs
the 2y frame) and signed into the trade's direction (`adv`). On the 171 simulated live positions the relation is
U-shaped: adv15 ∈ [0, 100) stops 40 % (net +1 908, n 55), ≥ 140 stops 60–67 % (−33, n 18), < −100 stops 64 % (−208,
n 22); AUC(adv → stop) 0.49 / 0.51, permutation P 0.18 / 0.11; recorded positions show the same shape. Actions: skip at
adv ≥ 140 +133 (cci15) / +359 (cci5) full (P(Δ<0) 0.41 / 0.32), +436 / +113 era; "wait for a better price" (limit at
price ∓ δ·mean range, 15 min) −483 / −348 / +67 at δ 0.5 / 1 / 2, and the every-fire control −2 448 (P 0.99, win rate
26 %) — the limit fills on the trades that keep going. No action on 71.6 h. 2y / oos2m test: tier-B stand-in over the
2y part files + candle-bounds frames, CCI deciles with month-matched permutation nulls, truth ladder (candle stop →
stop × 2 → forward return), skip / wait grid fit on 2y with random-skip and wait-all controls, frozen params scored
once on oos2m, interaction with stop × 2 — plan `plans/2026-10-21-cci-entry-quality-2y-test.md`.

### 2026-10-21 · higher_tf_pullback_veto — negative (84 h paper replay + 2y / oos2m stand-in)

User question: when the higher tf signals a reversal (or goes too deep) and moves back into range, discard the lower
tf's in-trend zones. Three pull-back states of the higher tf (extreme done `extdone`, EMA-25 class leaving +1,
overshoot retreat) and their union, ANDed as a veto into the 15- / 60-min entry, with mirror and ±24 h shifted-state
controls. Paper: best real variant +178 vs e25 +3 783 (P 0.30), the shifted placebo +912 (P 0.01). 2y: every 15-min
pair negative, −8 702 (cf0) … −79 598 (any ladder), P 0.94–1.00, placebo −24 759 ≈ xd −28 562 (removal of average
entries, not a quality effect); oos2m −961 … −11 455. Mechanism: the vetoed cells are of average quality (2y mean
+2.05 vs +2.16) or better (against the 240 pull-back PF 2.80 paper / 1.11 vs 1.04 2y; oos2m 15←60 long 1.27 vs 1.04).
60-min longs during a 240 pull-back are the only consistent-sign cell (2y PF 0.94 vs 1.09; xd60<240 +990 / +2 097,
cf060<240 +3 860 / −2 068) — thin, not actionable. Lead: the mirror cell (entry against the higher tf's done extreme)
is the best cell on 2y (PF 1.17–1.45), mixed oos2m. Report `results/higher_tf_pullback_veto_results.md`.

### 2026-10-21 · higher_tf_bounds_geometry — negative (84 h paper replay + 2y / oos2m stand-in)

User question: how are the tfs' candle bounds connected, and can the lower-tf entries that lose because of the bigger
tf's move be filtered by the higher tf's bounds (15 low ≈ 60 low, 60 keeps rising, 15 short from its high bound
fails)? Geometry: spans double per step (ATR1 q50 4.75 / 10.1 / 21.4), the 15 range nests in the 60 range 60 % of
minutes, 15 low within 1 ATR1 of the 60 low 14 %. Filter: favourable room share f of the entry inside the higher range
(veto f < 0.15), ATR room, bound coincidence (nest ≤ 1 ATR1), executed opposite zone (exz), pairs 15←60 / 15←240 /
60←240 / ladder, mirror + 24-h-shifted placebo. Negative everywhere: the entries at the wrong end of the higher range
are the best cells (2y tf 15 short f < 0.2 of the 60: PF 1.20–1.29, mean +9…+13 vs +3.7; beyond the bound 1.27), so
pos0.15 15←60 −32 488 (P 1.00, 2/24 months), room2 −29 400, ladder −51 400, placebo −15 859; oos2m −4 416 … −8 435;
paper +80 / +477 on 14–16 fires inside the placebo +355, exz −2 032 (P 0.98). The user-case cell (exz ∧ nest) is
average on 2y (PF 1.00 / 1.07) and flips on oos2m. Lead only: exz 60←240 +4 000 / +2 258 (P 0.25 / 0.10). Report
`results/higher_tf_bounds_geometry_results.md`, run report `executor/runs/2026-10-21-bounds-geometry-replay.md`.

### 2026-10-21 · cci_zone_excursion — partial (2y + oos2m, read-only)

CB zones are entered at adv5 (CCI-14 on the 5-min candle, signed into the zone) ≈ +66 (tf 15), +120 (tf 60), +110
(tf 240) median; 55–62 % of the 60 / 240 blocks start at adv5 ≥ 100. The strict marker (profit_strict, oos2m
parameters, labels reproduced 100 % against the stored oos2m columns) fires *more* often the higher adv is: tf 15
P 0.122 base → 0.178–0.210 at adv ≥ 200 (0.24–0.33 at the zone-entry minute), tf 60 0.07 → 0.11–0.12, tf 240
0.04 → 0.08; below −100 it halves; oos2m reproduces every direction. The excursion beyond the current 1-min extreme
to the candle close is set by the tf (q50 / q90: 0.7 / 3.3, 1.7 / 6.9, 3.6 / 13.5 ATR1); adv ≥ 140 adds 0.1 / 0.5 /
1.2 ATR1 to the median and 100 vs 140 vs p90 are indistinguishable; the next-60-min excursion is 3.0–3.4 / 9–11.5
ATR1 in every cell. P(a further +1 ATR1 | a limit at +δ filled) is 55 / 75 / 85 % (tf 15 / 60 / 240) independent of
δ, so a deeper delayed entry only lowers the fill rate (tf 15: 59 → 44 → 24 % at δ 0.5 / 1 / 2). Numbers to use at
tf 15: entry +0.5–1 ATR1, stop +2–3 ATR1 beyond the fill (31–33 % / 18–20 % stopped). Script
`executor/runs/2026-10-21-cci-zone-excursion-2y.py`, outputs beside it; report `results/cci_zone_excursion_results.md`.

### 2026-10-21 · volume_flow_entry_filter — partial (78 h paper replay + 2y / oos2m stand-in)

User question: align the volume, the 5-min buy/sell volume difference and the volume-depletion markers with the
position entries, find the correlation, propose filters that stop the losing trades, measure the profit impact.
Paper (186 simulated positions, +2 679; 200/207 fires reproduced): the relative 5-min volume at the fire is the
strongest relation (Spearman −0.21, P 0.00, AUC → stop-out 0.60; top quintile rv5 ≥ 2.3 stops 62 %, −705; bottom
36 %, +1 764), the 60-min depletion marker next (on: 42 fires, 60 %, −539; off 43 %, +3 218), the 5-min buy−sell
flow direction weak (|ρ| ≤ 0.1, AUC 0.43; only tf 15 short +0.26). Filters: skip rv5 > 3 +763 (P 0.06), rv15 > 3
+699 (0.00), dep60_on +881 (0.07) — positive on both halves, 4/4 (3/4) days, era +411 / +201 / +509, above the
random-skip band (20 %: −479) and the 24-h-shifted controls (−142 / −131); every flow-direction filter noise or
negative (adv5 > 0.1 −1 505, adv5 < −0.2 −431), skipping low-volume fires −2 365. 2y / oos2m (flow only, klines
taker volume): correlation ≈ 0 (|ρ| ≤ 0.06), the climax veto frozen on 2y (rv1 > 3 +9 150, P 0.25) scores −3 417
on oos2m, every rv > k on oos2m −3 417 … −7 970, against-flow vetoes −16 k … −80 k on 2y (the fires against the
strongest inflow are the best cells). Lead only; next arbiter = two more paper weeks with the three features logged.
Report `results/volume_flow_entry_filter_results.md`, run report `executor/runs/2026-10-21-volume-flow-replay.md`.

### 2026-10-21 · release_001 stop vs live candle stop — partial (23.4 h paper replay since the 2026-10-20 20:21Z restart)

User question: how much would profit differ from the pivot (the restart onto the candle stop) had release_001 kept
running. Harness = the 2026-10-20 sl-15m replay reversed, with the order-book stop rebuilt from `book_snapshot` +
`book_update` (BookTracker port) and the recorded in-zone streak. Live reproduced 58/58 (stops exact, sizes within
1 %, 57/58 close reasons; actual +240 vs sim −19 = the paper mid-fill, 2 ticks per stop). release_001 (book stop +
1 % placeholder) +422 vs live −19: **Δ +440** (paired 90 % CI [−442, +1 267], P 0.20; +387 at stop-level fills; +269 /
+133 with the book 170 / 1 000 ms stale). Stop rule alone +385, placeholder alone 0 (candle never fell back).
Mechanism: 22 stop→stop fires lose −526 instead of −1 611, but 6 of 11 live reversals and 2 targets stop first (−947).
Risk per trade 22 vs 75 USDT — a sizing statement. Previous day's replay said +791 the other way. Not decidable;
no code change. Report `executor/runs/2026-10-21-rel001-vs-candle-stop-replay.md`.
