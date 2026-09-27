---
archetype: recurrent-temporal
version: 1
parent: null
spec_hash: ff6e625c6c6371be2d9ecba280b81d06e3f0d5096fb434a20b69d01fe365e6f0
hypothesis: Baseline — an LSTM(64)->dense(32) over 14 stationary/trend features on
  TFs [15,60,240,1440] can predict the strict 15m entry direction (up/neutral/down).
holdout_acc: 0.4499
holdout_loss: null
per_class:
  up: {precision: 0.058, recall: 0.268}
  neutral: {precision: 0.891, recall: 0.473}
  down: {precision: 0.059, recall: 0.274}
decision: promote
strike: 0
next_hypothesis: Rule out undertraining before any structural change — re-run the
  same architecture at epochs=50/patience=8 (v2). If up/down precision still tracks
  the base rate, switch the target to a binary long-only strict label (v3) and/or add
  a conv1d front (conv->lstm) to capture local entry patterns.
---

# recurrent-temporal v1 — report

## Setup
- Dataset: 2y slim `link_usdt` (full 2 years, 62 spec columns; built from the labeled monolith to fit laptop RAM). 1,052,560 rows → train/val/holdout time split.
- Input: TFs [15, 60, 240, 1440] × 14 features (rsi_14, rsi_ma8_diff, cci_14, cci_diff, adx_14, macd_hist_12_26_9, trend_up_50, trend_down_50, sar_002_02, natr_14, move_class, zone_class, over_high, over_low). history_points=32 → X(N, 32, 56).
- Target: strict 15m direction `dir15s` (m1/x0.3/l15/y0.2), 3-class up/neutral/down from pslong/psshort.
- Architecture: LSTM(64) → dense(32). class_weight=balanced.
- Search: 3 Optuna trials over lr/units/dropout (epochs cut to 12 for laptop compute). Best: lr 0.00123, units 36, dropout 0.194 (trial spec d48a09da).

## Result (holdout = 201,581 rows)
| class | true % | pred % | precision | recall |
|---|---|---|---|---|
| up | 5.8% | 26.6% | 0.058 | 0.268 |
| neutral | 88.5% | 47.0% | 0.891 | 0.473 |
| down | 5.7% | 26.4% | 0.059 | 0.274 |

Holdout direction accuracy 0.4499 (best trial); the 3 trials spanned 0.416–0.450.

## What went well
- End-to-end pipeline works on real 2y data: strict-target resolution, multi-TF feature tensors, balanced training, chunked holdout eval, tracker recording, checkpoint promotion.
- The model is NOT degenerate-neutral — balanced weighting makes it actively predict up/down, so the metric is informative (0.45 < the 0.88 always-neutral floor).

## What went badly
- **No predictive signal on the rare entries.** up precision 0.058 ≈ up base rate 0.058; down precision 0.059 ≈ down base rate 0.057. The up/down predictions are right at chance — the model does not discriminate true best-entry points from noise.
- Recall ~0.27 on up/down is just an artefact of predicting those classes ~26% of the time, not real detection.

## What to improve (→ v2)
- **Confound:** epochs were cut 50→12 for the 4 GB laptop. "No signal" may be undertraining. The next version must rule this out FIRST: same architecture at epochs=50, patience=8.
- If signal still absent at 50 epochs, the limitation is structural/representational → switch to a binary long-only strict label (single, cleaner target) and/or add a conv1d front to capture local entry micro-structure before the LSTM models trend.

## Decision
Promote as the archetype baseline (first version; nothing to beat yet). strike 0. Lineage continues to v2.

## Compute notes (laptop reality)
4 GB GPU + 15 GB RAM. Fixes required to run at all: detached container (bash-lifetime kills), slim 62-col df (4.85 GB monolith OOM), chunked holdout inference (full-holdout LSTM forward OOM), reduced epochs (trial wall-time + session teardowns). A deeper search (epochs 50, 8 trials, all archetypes) needs a bigger GPU or unattended overnight runs.
