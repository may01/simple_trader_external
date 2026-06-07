# Task 02: NNPredictor

**Phase:** 11 — NN Module  
**Depends on:** Task 01 (NNModel), Task 03 (CheckpointManager), Phase 03 Task 01 (DataPoint protocol), Phase 03 Task 07 (DataAttributes)  
**Produces:** `nn/nn_predictor.py` — indicator-style per-tick NN inference, plugs into LiveData pipeline

---

## Goal

Implement `NNPredictor` — computes `{tf}_nn_prob_up`, `{tf}_nn_prob_neutral`, `{tf}_nn_prob_down` columns per tick. Behaves like an indicator: called after `Indicators.compute()` in `LiveData.build_candles()`, writes results directly into `data_point.get_df(tf)`. Strategies access NN output via `data_point.get('nn_prob_up', tf, 0)` — no direct coupling to `NNPredictor`.

---

## Context

In the live path, `LiveData.build_candles()` calls `Indicators.compute(point, tf)` per TF then calls `predictor.compute(point, tf)` to append NN probability columns to the same in-memory DataFrame. In the simulation/data-prep path, `NNOrchestrator.run_inference()` does the equivalent batch computation — `NNPredictor` is NOT used during simulation. `NNPredictor` is optional at runtime: if no checkpoint exists, `LiveData` skips NN computation and `nn_prob_*` columns are absent.

---

## Files

- Create: `nn/nn_predictor.py`

---

## Interface

**`NNPredictor(models: dict[str, NNModel], data_attributes: DataAttributes, feature_cols: list[str])`**

Attributes:
- `models: dict[str, NNModel]` — keyed by TF string (`"15"`, `"60"`); one trained model per TF
- `data_attributes: DataAttributes` — normalization stats
- `feature_cols: list[str]` — ordered list of `{tf}_{col}` column names used as NN input

**`compute(data_point: DataPoint, tf: int) -> None`**
- Extracts feature vector: `[data_point.get(col, tf, 0) for col in feature_cols if col.startswith(f"{tf}_")]`
- Normalizes: `(value - mean) / std` per column via `data_attributes.get_stats(col)`; if `std == 0` use raw value
- Calls `models[str(tf)].run(features)` → probability array `(3,)`
- Writes into last row of `data_point.get_df(tf)`:
  - `{tf}_nn_prob_up` = `probs[0]`
  - `{tf}_nn_prob_neutral` = `probs[1]`
  - `{tf}_nn_prob_down` = `probs[2]`
- If `str(tf)` not in `models`: writes `NaN` for all three columns — no crash

**`classmethod load(checkpoint_dir: str, feature_cols: list[str], data_attributes: DataAttributes, tfs: list[int]) -> NNPredictor`**
- For each TF: instantiates `NNModel(input_size=len(feature_cols_for_tf))`, calls `CheckpointManager(checkpoint_dir).load_best(model)`
- Skips TFs with no checkpoint (logs warning)
- Returns `NNPredictor(models, data_attributes, feature_cols)`

---

## Key Constraints

- `NNPredictor` is NOT used during simulation — `NNOrchestrator.run_inference()` handles batch inference
- `NNPredictor` does NOT gate strategy signals — strategies read `nn_prob_*` as regular indicator columns
- Feature extraction: only `feature_cols` starting with `"{tf}_"` used for that TF's model
- Missing feature column in `data_point`: use `0.0`, log warning once per column per session
- Stateless between ticks — no caching of prior features

---

## Verification

```bash
docker compose -f docker-compose-live.yml run --rm trader python3 -c "
from nn.nn_predictor import NNPredictor
from nn.nn_model import NNModel
print('nn_predictor importable')
"
```

---

## Commit

`feat: implement NNPredictor as indicator-style per-tick NN inference for live path`
