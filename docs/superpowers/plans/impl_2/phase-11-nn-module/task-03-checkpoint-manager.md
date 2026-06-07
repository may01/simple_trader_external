# Task 03: CheckpointManager

**Phase:** 11 — NN Module  
**Depends on:** Task 01 (NNModel)  
**Produces:** `nn/checkpoint_manager.py` — model weight versioning and persistence

---

## Goal

Implement `CheckpointManager` — saves and loads `NNModel` weights with versioning. Prevents overwriting best model with worse one.

---

## Context

Training runs produce multiple model versions. `CheckpointManager` tracks best model by validation accuracy, saves intermediate checkpoints, and provides `load_best()` for inference loading. Used by `Trainer._run_train_nn()` (via `NNOrchestrator`) and by `NNPredictor.load()` (live path startup).

---

## Files

- Create: `nn/checkpoint_manager.py`

---

## Interface

**`CheckpointManager(checkpoint_dir: str, model_name: str = "model")`**

Attributes:
- `checkpoint_dir: str`
- `model_name: str`
- `best_metric: float = -inf` — tracks best validation accuracy seen

**`save(model: NNModel, metrics: dict, epoch: int) -> str`**
- Saves model weights to `{checkpoint_dir}/{model_name}_epoch{epoch}.pt`
- If `metrics['val_accuracy'] > best_metric`: saves copy as `{model_name}_best.pt`, updates `best_metric`
- Returns path of saved checkpoint

**`load_best(model: NNModel) -> bool`**
- Loads `{model_name}_best.pt` into `model` via `model.load_model()`
- Returns True if loaded, False if no best checkpoint exists

**`load_epoch(model: NNModel, epoch: int) -> bool`**
- Loads specific epoch checkpoint
- Returns True if found, False if missing

**`list_checkpoints() -> list[dict]`**
- Returns list of `{epoch, path, size_bytes}` for all saved checkpoints

**`cleanup(keep_best: bool = True, keep_last_n: int = 3) -> None`**
- Deletes old checkpoints keeping: best model (if `keep_best`) + last N epoch files
- Prevents unbounded disk growth

---

## Key Constraints

- `checkpoint_dir` created if not exists at construction
- `best_metric` initialized to `-inf` — first save always becomes best
- `cleanup()` never deletes `_best.pt` when `keep_best=True`
- All saves atomic: write to `.tmp`, rename
- Thread-safe: single process writes; concurrent reads safe

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
import numpy as np
from nn.checkpoint_manager import CheckpointManager
from nn.nn_model import NNModel

model = NNModel(input_size=10)
model.build()
X = np.random.randn(50, 10).astype('float32')
y = np.random.randint(0, 3, 50)
model.train(X, y, epochs=2)

cm = CheckpointManager('/tmp/test_checkpoints')
path = cm.save(model, {'val_accuracy': 0.75}, epoch=1)
print('checkpoint_manager ok, saved to:', path)
assert cm.load_best(model) == True
"
```

---

## Commit

`feat: implement CheckpointManager with best-model tracking and cleanup`
