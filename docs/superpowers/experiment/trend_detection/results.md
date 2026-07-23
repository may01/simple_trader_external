# Trend Detection Experiment — Results

**Spec:** `../trend_detection.md` · **Plan:** `../../plans/2026-07-22-trend-detection-experiment.md`
**Date:** 2026-07-23 · **Branch:** `trend-detection-experiment` (worktree, nothing committed)
**Data:** LINK/USDT 2y train (slim 70,170 closed-15m rows × 471 cols) · oos2m validation (5,664 × 479)
**Point set:** `move_class_sym0 == ±2` (2y-fit sym0 cuts; oos2m baked-column crosscheck **1.0000** on all tfs)
**Ground truth:** profit_strict n1 — long-class = `pslong==1 & psshort==0`, short-class inverse; both/neither excluded
**Pipeline:** 214 tests GREEN in docker; frozen-stats OOS (zero refit, byte-verified)

---

## Headline

**Strong-RSI-move points are highly machine-separable into long-profit vs short-profit classes** (GBC test AUC 0.94–0.97 at tf15/60; OOS **holds** at tf15 with AUC 0.98–0.99) — **but a large share of that separation recovers the label's own observable precondition structure, not future price information.** cy gate (last l=15 one-minute rows before entry) and pessimistic entry fill are functions of candle-k's interior, so contemporaneous features partially *reconstruct the label definition*. Removing raw candle-k geometry (diagnostic run) only drops AUC to 0.88–0.95: lower-tf indicator state (5m RSI momentum, price-vs-EMA distance) carries the same gate information in smoothed form.

Practical reading: the discovered metrics DO tell you, at decision time, which side's strict entry conditions are being met — that is real, tradeable, contemporaneous information (and it transfers OOS). What they are NOT proven to predict is the tgt-before-SL race *beyond* the entry gate. Isolating that future-only component needs a different truth definition (see Next steps).

## Point counts (2y, per side)

| tf | side | long | short | both | neither | note |
|---|---|---|---|---|---|---|
| 15 | +2 | 135 | 1,097 | 1 | 9,456 | shorts dominate strong-up (mean-reversion) |
| 15 | −2 | 1,094 | 134 | 2 | 9,495 | longs dominate strong-down (mirror) |
| 60 | +2 | 78 | 125 | 0 | 2,389 | |
| 60 | −2 | 135 | 85 | 0 | 2,376 | |
| 240 | ±2 | 17–26 | 21–25 | 0 | ~620 | **skipped** under n1 (<60 marked) |

- ~88% of strong-move points are `neither` under strict n1 labels — the strict gate is the binding constraint, not the move itself.
- Direction asymmetry matches `rsi_side_stats.json` (strong-down→long edge, strong-up→short edge) and the rsi-sym0 design gate.
- tf240 only becomes scoreable at horizon n2 (68/60 marked) with AUC 0.61/0.56 — weakest, most "honest" (least mechanics leverage), low-n.

## Improvement loop (autonomous, 4 iterations)

| iter | transform | horizon | mean test AUC | verdict |
|---|---|---|---|---|
| 01 | baseline (full features) | n1 | 0.9544 | kept |
| 02 | prune_top40 (train-side importance) | n1 | **0.9617** | **kept — best** |
| 03 | interact_time_left | n1 | 0.9387 | rejected |
| 04 | horizon_n2 | n2 | 0.8275 | rejected (but unlocks tf240) |

Stop: 2 consecutive rejections. Per-iteration reports: `iter_01.md … iter_04.md`.

## Best iteration (02) test metrics — and OOS

| combo | gbc test AUC | test lift_long | test lift_short | OOS AUC | OOS verdict |
|---|---|---|---|---|---|
| 15_up | 0.9411 | +0.62 | +0.13 | 0.9785 | **holds** |
| 15_dn | 0.9706 | +0.11 | +0.78 | 0.9896 | **holds** |
| 60_up | 0.9967 | +0.56 | +0.44 | n=9 | skipped |
| 60_dn | 0.9385 | +0.38 | +0.62 | n=15 | skipped |

OOS gates: sym0 crosscheck 1.0000 (15/60/240); frozen stats byte-identical; both-lift-sign verdict rule. Full table: `oos_report.md`. OOS transfer at tf15 is near-perfect — consistent with the mechanics interpretation (the label code is stationary), and equally consistent with a stable microstructure regime; either way the metric is stable out of sample.

## What separates the classes (the metrics — spec deliverable)

Ranked by robustness across combos and by survival in the geometry-excluded diagnostic (`diag_report.md`):

1. **Lower-tf momentum state (H3 — dominant).** `5_rsi_ma8_diff` (screen AUC 0.05–0.08, i.e. long-class = deeply negative 5m RSI momentum; permutation importance #1 in every diag combo), `5_cci_14`, `5_rsi_ma12/24_diff`, `15_rsi_ma8_slope` (0.72–0.76). Long-class points sit at a *decelerating/reversing* micro-state; short-class at accelerating.
2. **Price-vs-short-EMA / band distance, lower tf (H7-adjacent).** `5_ema_7_minus_close` (0.82–0.90), `5_bb_upper/lower_20_2_minus_close` (0.75–0.87). Long-class = price stretched below the 5m EMA/band.
3. **Candle-k geometry (mechanics channel).** `15_logret`/`close_diff_prc` (0.01–0.05), `15_wick_up/dn` (0.85–0.89), `body_ratio`, `range_atr` — top of the full-feature screen; deliberately excluded in the diagnostic. These are the most direct fingerprints of the entry-gate window (charts: `charts/*.png`).
4. **Engineered features that earn a place (H4/H8).** `swing_dist_hi_15_20` (levels proxy; screen 0.69 in 15_up) and `need_speed_up_240` (#2 permutation importance in 60_dn full run) — the only spec-hypothesis engineered features in any top-10.
5. **Higher-tf context (H2 — weak).** `240_wick_up` (0.76–0.84 pre-exclusion), `1440_cci_14_ma_5`/`1440_cci_diff` minor. Higher-tf state adds little once lower-tf state is present.

Hypothesis verdicts: **H3 lower-tf: strong** · **H1 same-tf: moderate** (rsi_ma8_slope, geometry) · **H4 levels-proxy: moderate** (swing_dist_hi) · **H8 time-left/need-speed: promising, narrow** (need_speed_up_240) · **H7 opposite-bound distance: moderate via lower-tf band distance** · H2 higher-tf: weak · H5 htf-move-agreement: no signal in top ranks · H6 out-of-bound flags: no signal in top ranks · **H9 multivariate: strong** (0.88–0.997 test).

## Truth decomposition (follow-up #1 — EXECUTED 2026-07-23)

Same points, same features, three truth definitions (`alt_truth_report.md`): **strict** (gate+race), **plain** (`plong/pshort` — race+entry-fill, no clean-entry gate), **fwd** (1-bar return sign — pure future). GBC test AUC:

| combo | strict | plain full | plain noshape | fwd full | fwd noshape |
|---|---|---|---|---|---|
| 15_up | 0.9412 | 0.5588 | 0.5119 | 0.5067 | 0.5040 |
| 15_dn | 0.9642 | 0.5809 | 0.5075 | **0.5388** | **0.5407** |
| 60_up | 0.9401 | 0.4768 | 0.4842 | 0.4979 | 0.5201 |
| 60_dn | 0.9722 | 0.4774 | 0.4740 | **0.5377** | **0.5359** |

Decomposition (full set): label(gate) share +0.38–0.49 · entry-fill share −0.06–+0.05 · future share ≈ 0 (up) / **+0.04 (dn)**.

**Conclusions:**
1. **The clean-entry gate accounts for essentially the entire strict-label separation** (0.94–0.97 → ~0.5 once removed). The phase-1 metrics classify the gate, not the future. Hypothesis from the diagnostic confirmed quantitatively.
2. **Plain (race) truth ≈ chance** — 15-tier plain AUCs above 0.55 collapse to ~0.51 without shape features (entry-fill mechanics via geometry).
3. **A small genuine forward signal exists ONLY on strong-DOWN points** (fwd AUC 0.536–0.541, stable across full/noshape, n=2.6k–10.4k, SE≈0.01 → real). Strong-up: chance. Asymmetry matches the rsi-sym0 design gate (S.Dn→long is the stable side).
4. **The future-only separators are the engineered bound/level-distance features:** `bb_dist_up_240` (60_dn screen #2, 0.538), `bb_dist_up_15` + `swing_dist_hi_15_50` (15_dn top-3, 0.533–0.534), plus deeper 5m oversold (`5_rsi_14`, `5_cci_14` low) and price-stretch-below-5m-EMA. Story: after a strong down-move, forward long edge concentrates where there is **room to the upper bound / prior swing high** and a deeper local oversold stretch — H7 (opposite-bound distance) and H4 (levels proxy) are the hypotheses that survive contact with pure-future truth; magnitude is modest (~0.54 AUC / ~+4pp over coin-flip).

## Limitations (read before using)

1. **Label-mechanics confound.** profit_strict embeds an observable precondition (clean-entry gate over the last 15 minutes + pessimistic fill). Contemporaneous features — geometry directly, lower-tf indicators in smoothed form — partially encode that gate. The 0.94–0.99 AUCs therefore overstate *future*-predictive power. The near-tautological fwd-agreement robustness (0.87–0.94 at fwd1 for n1) validates label-marking consistency, not prediction.
2. **tf240 unresolved** under the locked n1 truth (starved); n2 numbers (0.56–0.61) are low-n.
3. 60_up's 0.9967 test AUC is on n=61 — treat as upper-bound noise.
4. Single symbol (LINK/USDT), single 2m OOS window.

## Next steps (recommended follow-ups)

1. ~~Isolate the future-only component~~ **DONE — see Truth decomposition section.** Verdict: gate ≈ everything; genuine forward signal only on strong-down points (~0.54 AUC) via bound/level-distance features.
2. **Promote the confirmed engineered winners** (`bb_dist_up_{tf|htf}`, `swing_dist_hi_{tf}_{w}`; `need_speed_up_240` secondary) into the indicator pipeline — these survived the pure-future truth on dn combos.
3. **tf240 with n2-native labels** and a longer OOS window.
4. Cross-check the dominant lower-tf state metrics as viewer-marker classification fields beside `move_class_sym0` (same coexist A/B pattern as the rsi-quantile work).

## Artifacts

- Volume (full dumps, models, csvs, charts): `/trader_data_long/train/2y_link_usdt/trend_detection/{iter_01..04,diag}/`, `.../oos2m_link_usdt/trend_detection/`
- This dir: `loop_summary.md`, `iter_0N.md`, `diag_report.md`, `oos_report.md`, `alt_truth_report.md`, `charts/`
- Volume also: `.../2y_link_usdt/trend_detection/alt_truth/` (decomposition csvs/metrics)
- Code: branch `trend-detection-experiment`, `notebooks/trend_detection/` (tdlib 10 modules + 5 drivers + 223 tests), uncommitted by spec constraint
