# Task 05: NNModel (Spec-Driven Network)

**Phase:** 11 — NN Module  
**Depends on:** Task 01 (device resolver), Task 02 (NNModelSpec), Task 04 (NNDataset)  
**Produces:** reworked `nn/nn_model.py` (+ rewritten tests)

---

## Goal

Rework `NNModel` so the network is constructed **entirely from an `NNModelSpec`** — nothing about the architecture, inputs, or targets is hardcoded. The model takes multi-timeframe input, emits one or more jointly-trained target heads, and persists self-contained checkpoints (weights + spec + normalisation manifest) so it can be rebuilt and run on any dataset without the training folder present. Two models differ only by their specs.

---

## Context

<MIGRATION: replaces the fixed-MLP `NNModel(input_size, hidden_size, num_classes)` (a single `nn.Sequential` of `Linear → ReLU → Linear → ReLU → Linear`, `train(X, y, epochs, lr)`, and `save_model`/`load_model` that only round-trip a bare `state_dict`).>

The old constructor took raw integer sizes and built one fixed 3-class direction MLP; there are no architecture variants in code (`get_generic_model` / `get_hack_*` are retired). Now the constructor takes an `NNModelSpec` (Task 02) and `build()` materialises the network from `spec.layers` / `spec.activation` / `spec.dropout` plus the per-target output heads from `spec.targets`. Input is multi-timeframe (`indicators × timeframes × history_points`), output is the concatenation of multiple target heads trained jointly.

`train()` consumes an `NNDataset` (Task 04) — not raw `(X, y)` arrays — and splits internally per `spec.val_strategy`. Checkpoints embed the spec and the normalisation manifest so inference is self-contained across datasets (`checkpoint-manager-class.md` §4).

**Normalisation is NOT done inside `NNModel`** (leakage guard). Callers normalise features with the **training** manifest (feature list + per-feature stats) before `run`/`run_batch`; `NNModel` never recomputes stats from inference data. The device comes from `nn/device.py` (`resolve_device`), the single source of device policy.

---

## Files

- Modify: `nn/nn_model.py` — rebuild as the spec-driven implementation
- Modify: `tests/unit/nn/test_nn_model.py` — rewrite to the spec-driven interface (all 13 old tests are obsolete; see "Tests to rewrite")

---

## Interface

### Constructor

**`__init__(self, spec: NNModelSpec) -> None`**
- Stores `spec`, resolves `device` via `nn/device.py` (`resolve_device(spec.device)`).
- Derives `input_size` (= `len(spec.indicators) × len(spec.timeframes) × spec.history_points`) and `output_size` (= sum of per-target head widths).
- Does **not** build the network (lazy — `build()` or `train()` does).

### Architecture

**`build(self) -> None`**
- Constructs `self.model` from `spec.layers`, `spec.activation`, `spec.dropout`, and the target heads derived from `spec.targets`.
- Idempotent — no-op if already built.
- Called automatically by `train()`; explicit call is useful for logging layer shapes.
- Empty `spec.layers` or empty `spec.targets` → `ValueError`.

### Training

**`train(self, dataset: NNDataset, epoch_callback=None) -> dict`**
- Calls `build()` if needed.
- Splits train/validation per `spec.val_strategy` / `spec.validation_split` (time-holdout default, to avoid look-ahead leakage).
- Assembles optimiser/loss from spec; per-target losses combined as a weighted sum. Classification targets use `spec.class_weight`.
- Trains for `spec.epochs` with `spec.early_stopping_patience`; supports Optuna pruning via `epoch_callback(epoch, metrics)` returning a stop signal.
- After each epoch, `epoch_callback` (if set) receives `{loss, accuracy, val_loss, val_accuracy, per_target: {...}}`.
- Returns the final metrics dict; sets `is_trained = True`.

### Inference

**`run(self, features: np.ndarray) -> np.ndarray`**
- Single-sample inference. Returns the concatenated output vector across all heads. Requires `is_trained`.

**`run_batch(self, features: np.ndarray) -> np.ndarray`**
- Batch inference: `(M, input_size)` → `(M, output_size)`. Used by `NNOrchestrator.run_inference()`.

### Persistence

**`save_model(self, path: str) -> None`**
- Saves the `state_dict` **and** the serialised `spec` **and** the normalisation manifest (per-feature training stats + ordered `feature_cols`), so the model is fully self-contained for inference on any dataset.
- Checkpoint payload schema matches `CheckpointManager`: `{"state_dict": …, "spec": …, "manifest": …, "feature_cols": …}` (see `checkpoint-manager-class.md` §4).

**`load_model(self, path: str) -> None`**
- Rebuilds the network from the embedded spec, loads the `state_dict`, restores the normalisation manifest + `feature_cols`, and sets `is_trained = True`.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `spec` | `NNModelSpec` | The defining spec (immutable for the model's life). |
| `model` | `torch.nn.Module` | The built network (`None` until `build()`). |
| `input_size` | `int` | `indicators × timeframes × history_points` (all configured TFs feed every model). |
| `output_size` | `int` | Sum of per-target head widths. |
| `device` | `torch.device` | Resolved from `spec.device` (`auto` → cuda if available). |
| `is_trained` | `bool` | `False` until `train()` / `load_model()` completes. |

### Output column naming (timeframe-agnostic — no `{tf}_` prefix)

| Target `kind` | Head width | Output columns |
|---------------|-----------|----------------|
| `direction` | 3 (softmax) | `nn_res_{name}_prob_up`, `nn_res_{name}_prob_neutral`, `nn_res_{name}_prob_down` |
| `label` | 1 (sigmoid) | `nn_res_{name}_prob` |
| `regression` | 1 (linear) | `nn_res_{name}` |
| multi-horizon (`horizons=[h1,h2,…]`) | per-horizon head | append `_h{hk}` after `{name}`, e.g. `nn_res_{name}_h{hk}_prob_up` |

`output_size` is the sum over all `(target, horizon)` head widths in spec order; `run`/`run_batch` return the heads concatenated in that order.

---

## Key Constraints

- Network built **ENTIRELY** from spec — no hardcoded architecture variants (no `hidden_size`/`num_classes` constructor args; no `get_generic_model` / `get_hack_*`).
- `history_points > 1` with `dense` layers flattens the lookback window; with `lstm`/`gru`/`conv1d` layers the window is the sequence dimension.
- Head width and default loss follow `TargetSpec.kind`: `direction` → softmax / cross-entropy (3-class up/neutral/down from the long+short pair); `label` → sigmoid / BCE; `regression` → linear / Huber. Multiple `TargetSpec`s = multiple heads trained jointly.
- **Normalisation is done by callers** via the bundled manifest (leakage guard) — never inside `NNModel`, and never recomputed from inference data.
- `save`/`load` are path-based and self-contained: embed `spec` + `manifest` + `feature_cols` so a checkpoint rebuilds and runs without the training dataset/folder.
- Device via `nn/device.py` (`resolve_device`); CUDA OOM during training → one CPU retry before failing (`training-coordinator-class.md` §4).
- `run()` / `run_batch()` before training → `RuntimeError("model not trained")`.
- Feature-vector width mismatch vs `input_size` → `ValueError` with expected/actual sizes.

### Tests to rewrite

All 13 tests in `tests/unit/nn/test_nn_model.py` assume the old `NNModel(input_size, hidden_size, num_classes)` + `train(X, y, ...)` + bare-`state_dict` save/load API and must be rewritten against the spec-driven interface:
- `small_model` / `trained_model` fixtures → build from a tiny `NNModelSpec` + `NNDataset`.
- `test_train_returns_correct_metric_keys` / `test_epoch_callback_called` → keep `{loss, accuracy, val_loss, val_accuracy}` plus assert the new `per_target` key.
- `test_run_output_shape` / `test_run_batch_output_shape` → assert `(output_size,)` / `(M, output_size)` derived from spec targets, not a fixed `3`.
- `test_run_output_is_probabilities` / `test_run_batch_output_is_probabilities` → per-head semantics (softmax heads sum to ~1; sigmoid/regression heads are not constrained to sum to 1).
- `test_save_load_round_trip` → assert the checkpoint embeds spec + manifest + feature_cols and that `load_model` rebuilds from the embedded spec (no external sizes passed).
- `test_save_model_raises_when_not_built` / `test_binary_classification` → re-express via a `label`-kind single-head spec; binary is a `label` target, not `num_classes=2`.
- Add: `build()` with empty `layers`/`targets` → `ValueError`; feature-width mismatch → `ValueError`; multi-target head produces the expected concatenated `output_size` and column names.

---

## Verification

```bash
docker compose run --rm nn-train python3 -c "
import numpy as np
from nn.nn_model import NNModel
from nn.nn_model_spec import NNModelSpec, LayerSpec, TargetSpec
from nn.nn_dataset import NNDataset
# tiny spec: 1 tf, a couple indicators, history_points=1, one dense layer, one direction head
spec = NNModelSpec(
    name='tiny', timeframes=[15], indicators=['rsi','atr_ma'], history_points=1,
    layers=[LayerSpec(kind='dense', units=8)],
    targets=[TargetSpec(name='dir15', kind='direction', label_tf=15)],
    epochs=2, validation_split=0.2, val_strategy='time_holdout', device='cpu',
)
m = NNModel(spec)
m.build()
print('input_size', m.input_size, 'output_size', m.output_size)  # 2*1*1=2 ; direction=3
ds = NNDataset.__new__(NNDataset)  # or build a tiny in-memory dataset per Task 04
# ... assemble a minimal NNDataset of ~50 rows ...
metrics = m.train(ds, epoch_callback=lambda e, mm: None)
assert m.is_trained
preds = m.run_batch(np.random.randn(7, m.input_size).astype('float32'))
assert preds.shape == (7, m.output_size), preds.shape
print('nn_model ok', metrics.keys())
"
```

---

## Commit

`refactor(nn): spec-driven NNModel (multi-tf input, multi-target heads, self-contained checkpoints)`
