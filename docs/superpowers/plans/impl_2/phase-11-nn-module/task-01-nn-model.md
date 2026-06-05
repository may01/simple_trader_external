# Task 01: NNModel

**Phase:** 11 — NN Module  
**Depends on:** Phase 03 Task 07 (DataAttributes for normalization), Phase 09 Task 02 (DataPreparer output format)  
**Produces:** `nn/nn_model.py` — neural network build, train, and inference

---

## Goal

Implement `NNModel` — builds, trains, and runs inference on the price direction prediction neural network. Input: normalized indicator features from `df_with_indicators.pkl`. Output: direction probability per candle.

---

## Context

NN predicts future price direction (up/down/neutral) for a given TF and horizon. Used by `StrategyManager` to filter OPEN signals: if NN confidence below threshold, signal suppressed. Model architecture is fixed (not tunable via config) — tuning is future scope.

---

## Files

- Create: `nn/nn_model.py`
- Create: `nn/__init__.py` (empty)

---

## Interface

**`NNModel(input_size: int, hidden_size: int = 128, num_classes: int = 3)`**

Attributes:
- `model` — underlying neural network (framework: PyTorch or Keras — framework determined by existing project dependencies)
- `input_size: int`
- `hidden_size: int`
- `num_classes: int` — typically 3: up / neutral / down
- `is_trained: bool = False`

**`build() -> None`**
- Constructs network layers: `input → hidden → relu → hidden → softmax`
- Call once before `train()` or `load_model()`

**`train(X: np.ndarray, y: np.ndarray, epochs: int = 100, lr: float = 0.001) -> dict`**
- Trains model on normalized feature matrix `X` and labels `y`
- Returns training metrics dict: `{loss, accuracy, val_loss, val_accuracy}`
- Sets `is_trained = True` on completion

**`run(features: np.ndarray) -> np.ndarray`**
- Single-sample inference: returns probability array of shape `(num_classes,)`
- Requires `is_trained == True`

**`run_batch(features: np.ndarray) -> np.ndarray`**
- Batch inference: `features` shape `(N, input_size)` → returns `(N, num_classes)`

**`load_model(path: str) -> None`**
- Loads saved weights from `path`
- Sets `is_trained = True`

**`save_model(path: str) -> None`**
- Saves model weights to `path`

---

## Key Constraints

- Input features must be normalized (mean=0, std=1) using `DataAttributes` before passing to `run()`
- `run()` raises `RuntimeError` if `is_trained == False`
- Training uses 80/20 train/validation split internally — caller does not split
- Model weights saved in framework-native format (`.pt` for PyTorch, `.h5` for Keras)
- `num_classes=3` is the default; binary classification (`num_classes=2`) also supported

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
import numpy as np
from nn.nn_model import NNModel

model = NNModel(input_size=50)
model.build()
X = np.random.randn(100, 50).astype('float32')
y = np.random.randint(0, 3, size=100)
metrics = model.train(X, y, epochs=2)
assert model.is_trained
pred = model.run(X[0])
assert pred.shape == (3,)
print('nn_model ok, metrics:', metrics)
"
```

---

## Commit

`feat: implement NNModel with build, train, and batch inference API`
