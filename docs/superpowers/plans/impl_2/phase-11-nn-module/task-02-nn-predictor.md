# Task 02: NNPredictor

**Phase:** 11 — NN Module  
**Depends on:** Task 01 (NNModel), Phase 03 Task 01 (DataPoint protocol), Phase 03 Task 07 (DataAttributes)  
**Produces:** `nn/nn_predictor.py` — per-tick inference wrapper used by StrategyManager

---

## Goal

Implement `NNPredictor` — wraps `NNModel` for per-tick use: extracts features from `data_point`, normalizes via `DataAttributes`, runs inference, returns direction signal.

---

## Context

`StrategyManager` holds a reference to `NNPredictor`. On each tick where an OPEN action is candidate, `predictor.predict(data_point, tf)` is called. If returned confidence < threshold, OPEN suppressed. `NNPredictor` handles feature extraction and normalization so `StrategyManager` stays clean.

---

## Files

- Create: `nn/nn_predictor.py`

---

## Interface

**`NNPredictor(model: NNModel, data_attributes: DataAttributes, feature_cols: list[str], confidence_threshold: float = 0.6)`**

Attributes:
- `model: NNModel`
- `data_attributes: DataAttributes` — normalization stats
- `feature_cols: list[str]` — ordered list of column names to extract from `data_point`
- `confidence_threshold: float`

**`predict(data_point, tf: int) -> tuple[int, float]`**
- Extracts feature vector: `[data_point.get(col, tf, 0) for col in feature_cols]`
- Normalizes: `(value - mean) / std` per column using `data_attributes`
- Calls `model.run(features)` → probability array
- Returns `(predicted_class, confidence)` where `confidence = max(probability_array)`

**`is_confident(data_point, tf: int, expected_class: int) -> bool`**
- Calls `predict()`, returns True if `predicted_class == expected_class` AND `confidence >= confidence_threshold`
- `expected_class`: 0=up (OPEN_LONG filter), 2=down (OPEN_SHORT filter)

**`load(model_path: str, attributes_path: str) -> None`**
- Loads model weights via `model.load_model(model_path)`
- Loads `DataAttributes` from `attributes_path`

---

## Key Constraints

- Feature extraction uses `data_point.get(col, tf, 0)` — shift=0 (current value)
- Missing feature (column not in data_point): use 0.0 — log warning once, do not crash
- `data_attributes` normalization: if `std == 0` for a column, skip normalization (use raw value)
- `NNPredictor` is stateless between ticks — no caching of prior features
- `confidence_threshold` should default 0.6 — adjustable per strategy instance

---

## Verification

```bash
docker compose run --rm trader python3 -c "
from nn.nn_predictor import NNPredictor
from nn.nn_model import NNModel
print('nn_predictor importable')
"
```

---

## Commit

`feat: implement NNPredictor for per-tick feature extraction and direction confidence`
