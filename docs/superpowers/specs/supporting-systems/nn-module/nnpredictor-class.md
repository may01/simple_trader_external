# NN Inference Path Specification (NNPredictor Removed)

**Status:** `NNPredictor` is **removed from the prediction stage** (item 2). This document records the removal and the batch-inference path that replaces it.
**Replaced by:** `NNOrchestrator.run_inference()` (see `training-coordinator-class.md`).

---

## 1. What Changed

Earlier designs ran a per-tick `NNPredictor` inside the live prediction stage. On every candle, `LiveData.build_candles()` called `predictor.compute(point, tf)` to append per-tf NN columns one row at a time, normalising features per tick and invoking `NNModel.run()` for a single sample.

**That class and that call site are removed.** The prediction/strategy stage no longer imports or depends on any NN class.

---

## 2. Why

1. **Live/backtest parity.** Per-tick inference risked subtle differences from the batch path used in simulation (normalisation timing, warmup, feature availability). Computing NN outputs once, in batch, and consuming identical precomputed columns in both live and backtest eliminates that skew.
2. **Decoupling.** Strategies read `nn_res_*` as ordinary indicator columns via `data_point.get(...)`. They have no knowledge of models, checkpoints, or PyTorch. Removing the live predictor removes a runtime dependency and a class of live-only failures.
3. **Cost and latency.** Single-sample inference per tick per TF is wasteful. Batch inference over the prepared DataFrame is far cheaper and runs off the hot path.

---

## 3. Replacement Path

NN outputs reach strategies as indicator columns, produced offline and joined at load time:

```
NNOrchestrator.run_inference(dataset, checkpoint_id)
    → {dataset}/df_with_nn.pkl   (NN-only columns: nn_res_{target}_prob_*, nn_res_{target}, …)
        → SimulationData / FullData / LiveData LEFT-JOIN df_with_nn.pkl at construction
            → strategies read nn_res_* via data_point.get(...)
```

- **Producer.** `run_inference` reads the NN feature columns from the *target* dataset's own `df_with_indicators.pkl` (any dataset, not only the training one), runs batch inference (`NNModel.run_batch`) over closed candles, and writes `{dataset}/df_with_nn.pkl` beside it. It returns/writes only the NN columns and **never mutates** `df_with_indicators.pkl`.
- **Normalisation.** Features are normalised via the **training manifest stats bundled in the checkpoint** (feature list + per-feature `{q01,q99,mean,std}`), identical to training: clip raw to `[q01,q99]` → `(x-mean)/std` → clamp `[-4,+4]`. They are **never recomputed from the inference dataset** — recomputing would introduce distribution shift / leakage.
- **Merge is a consumer-side join, not a prepare() step.** `df_with_indicators.pkl` stays single-writer (DataPreparer); `df_with_nn.pkl` is an additive, disposable artifact. Consumers left-join it on the 1-min index at construction. Re-running `prepare()` never clobbers NN columns; re-running inference overwrites only `df_with_nn.pkl`.

---

## 4. Consumer Contract

- If no trained checkpoint exists (or inference was not run for this dataset), `df_with_nn.pkl` is absent, the load-time join is a no-op, and the `nn_res_*` columns simply do not appear. Strategies must treat their absence like any other missing indicator (e.g. `data_point.get('nn_res_dir15n1_prob_up', tf, default)`), not crash. Absence-safety is enforced at the access layer: `DataPoint.get(col, tf, default=…)` returns `default` when the column is missing (see `data-class.md` §2).
- Column names are timeframe-agnostic and determined by the model's `TargetSpec` list (see `nnmodel-class.md` §6), so adding a profit-label direction, regression, or multi-horizon target adds columns without touching strategy code that ignores them.

---

## 5. Removed Surface

The following are deleted and should not be reintroduced into the prediction stage:
- `NNPredictor` class and `nn/nn_predictor.py` per-tick path.
- The `predictor.compute(point, tf)` call in `LiveData.build_candles()`.
- Any live-path import of `NNModel`/checkpoints.

The legacy Gaussian price-level `Predictor` (high/low/close extrapolation) is also retired; price-level prediction, if revived, would be modelled as a regression `TargetSpec` and delivered through the same batch indicator path.

---

## 6. Notes

- This keeps the NN module strictly a **data-preparation producer** of indicator columns, with a single inference path shared by live and backtest.
- **Live/backtest parity is structural.** Both paths consume `nn_res_*` via the same load-time left-join of a `df_with_nn.pkl` produced by the same `run_inference` batch. The live path treats its accumulating window as just another dataset and runs the identical batch inference (cadence is a LiveData concern; it MUST reuse `run_inference`, never a per-tick predictor).
- Any future need for online/incremental inference must preserve this parity (e.g. by replaying the same batch computation), not by reintroducing a divergent per-tick predictor.
