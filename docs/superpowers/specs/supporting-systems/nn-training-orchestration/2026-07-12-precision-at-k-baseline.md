# Precision@k gate — strict direction_binary baseline (2y holdout)

**Date:** 2026-07-12
**Scope:** re-score existing trained **strict `direction_binary`** (long15) checkpoints
under both gate metrics, no retraining. Companion to
[2026-07-05-precision-at-k-gate-design.md] and its implementation resolution.
**How:** `_score_precision_baseline.py` harness — loads each `all_best.pt` into an
`NNModel`, stuffs it into `orchestrator.trained_models`, calls
`TrainingLoop.evaluate_on_holdout` twice (`gate_metric=accuracy`, then
`precision_at_k`). Ran in the `nn-train` GPU container, `NN_TRAIN_ENV=…_2y`,
2y df (1,052,560 rows). Long base rate = 0.0578 (5.78%) for all.

## Results

| model (strict long15) | hash | acc gate (old) | p@1% | p@5% | p@10% | lift@1 | lift@5 | lift@10 |
|---|---|---|---|---|---|---|---|---|
| nn-features-only-v1 | 85e3eedb | 0.7076 | 0.3643 | 0.2561 | 0.2111 | 6.31× | 4.43× | 3.65× |
| nn-features-only-v2 | 76f51bd3 | **0.7795** | 0.2737 | 0.1923 | 0.1708 | 4.74× | 3.33× | 2.96× |
| nn-features-only-v3 | 2c2d050f | 0.7160 | 0.4072 | **0.2702** | 0.2209 | 7.05× | **4.68×** | 3.82× |
| nn-features-only-v4 | 5561ade8 | 0.7379 | 0.2756 | 0.2196 | 0.1960 | 4.77× | 3.80× | 3.39× |

## Key finding — the gate flips the winner

- **Old accuracy gate ranks:** v2 (0.7795) > v4 > v3 > v1. It crowns **v2**.
- **New precision@5% ranks:** v3 (0.2702) > v1 > v4 > **v2 (0.1923, last)**.

The accuracy-gate winner (v2) is the **worst** model on actionable long precision;
the precision@5% winner (v3) lifts 4.68× over the 5.78% base rate at the top-5%
slice. Near-inverted ranking — the concrete demonstration that argmax accuracy
gamed the rare-positive target and precision@k corrects it. v2's `0.7795` accuracy
+ 5.78% base rate reproduce the design doc's stated baseline, confirming this is
the design's reference model (and that its ~0.138 global long precision is, as the
design predicted, lower than the top-5% precision@5% of 0.1923).

## Not reproduced

`full-snapshot-dense` v1–v5 (also strict long15 `direction_binary`, checkpoints
present) failed with **feature-width mismatch** (model expects 474 / 1896, the
current 2y df yields 610 / 2440). The 2y `df_with_indicators.pkl` was regenerated
2026-07-12 with more indicator columns than when those models trained; the
`full-snapshot` archetype consumes ALL features so its input width grew and the
saved weights no longer fit. `nn-features-only` uses a fixed per-TF feature subset
([[project_nn_features_stale_tf_coverage]], [[project_nnfo_profit_strict_12]]) so
its width held. To baseline the full-snapshot models, re-score against the df
revision they trained on (not currently on the volume) or retrain.

## Next

Evolve an `nn-features-precision` strict lineage seeded from **v3** (the precision@5%
leader) under `NN_GATE_METRIC=precision_at_k`, hill-climbing precision@5% — multi-hour
GPU orchestration (`nn-train-orchestrator` / `nn-evolve`), not yet run.
