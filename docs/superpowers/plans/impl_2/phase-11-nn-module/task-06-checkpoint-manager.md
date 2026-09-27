# Task 06: CheckpointManager (Self-Contained PyTorch Checkpoints)

**Phase:** 11 — NN Module  
**Depends on:** Task 05 (NNModel save/load)  
**Produces:** reworked `nn/checkpoint_manager.py` (+ updated tests)

---

## Goal
Rework `CheckpointManager` so each saved checkpoint is a **self-contained PyTorch bundle** — `state_dict` + embedded `NNModelSpec` + normalisation `manifest` + ordered `feature_cols` + `metrics` — that can be reconstructed and applied to **any** dataset at inference without the training dataset or its folder being present. Add `mode` (`max`/`min`) to govern promotion comparison, add `manifest`/`feature_cols`/`promote` to `save()`, and change `load_best()` to return `dict | None` so consumers stay absence-safe ("no model" → inference skipped).

One `CheckpointManager` per group (class/regime; a single group if `grouping=single`). Promotion is ultimately decided by `ExperimentTracker` (Task 07, holdout + margin); `save(promote=True)` is how that decision is persisted to the `_best.pt` weights.

## Context
MIGRATION from current implementation:
- `__init__` gains `mode: str = "max"`; `best_metric` is initialised to `-inf` (max) or `+inf` (min) accordingly (was hard-coded `-inf`).
- `save()` gains required `manifest: dict` and `promote: bool = False`; the stored `.pt` is now a bundle `{state_dict, spec, manifest, feature_cols, metrics}` instead of a bare `model.save_model()` artifact. Promotion fires when `promote` is set **or** the gate metric improves on `best_metric` per `mode` (was: `val_accuracy` strictly greater than `best_metric`).
- `load_best()` now returns `{manifest, feature_cols} | None` (was `bool`). `None` means no `_best.pt` exists; callers treat as "no model" and skip inference.
- `load_epoch()` keeps its `bool` return.
- `list_checkpoints()` now also reports each checkpoint's stored `metrics`.
- Checkpoints are self-contained for cross-dataset inference (leakage guard): inference features are normalised with the **training** stats carried in the bundle, never stats recomputed from the inference dataset.

Why bundle the manifest: `run_inference` runs on arbitrary datasets; features must be normalised with the training stats, not the inference dataset's, to avoid distribution-shift / leakage. Bundling the manifest in the checkpoint makes those stats travel with the weights.

## Files
- Modify: `nn/checkpoint_manager.py`
- Modify: `tests/unit/nn/test_checkpoint_manager.py`

## Interface

```python
class CheckpointManager:
    """Save/load self-contained PyTorch NNModel checkpoints with best-model tracking."""

    def __init__(self, checkpoint_dir: str, model_name: str = "model", mode: str = "max") -> None:
        """Create checkpoint_dir if absent; init best_metric per mode (-inf for 'max', +inf for 'min')."""

    def save(self, model: NNModel, metrics: dict, epoch: int, manifest: dict, promote: bool = False) -> str:
        """Save {model_name}_epoch{epoch}.pt as a self-contained bundle; if promote or the gate
        metric improves on best_metric (per mode), also write {model_name}_best.pt and update
        best_metric. Atomic (temp + rename). Returns the saved epoch checkpoint path."""

    def load_best(self, model: NNModel) -> dict | None:
        """Load {model_name}_best.pt into model via model.load_model() (rebuilding from the embedded
        spec) and restore the normalisation manifest + feature_cols. Returns {manifest, feature_cols}
        or None if no best checkpoint exists (caller treats as 'no model')."""

    def load_epoch(self, model: NNModel, epoch: int) -> bool:
        """Load a specific epoch checkpoint into model. Returns True/False."""

    def list_checkpoints(self) -> list[dict]:
        """Return [{epoch, path, size_bytes, metrics}, ...] for all epoch checkpoints,
        sorted by epoch ascending. Excludes _best.pt."""

    def cleanup(self, keep_best: bool = True, keep_last_n: int = 3) -> None:
        """Delete old epoch checkpoints, retaining the best (if keep_best) plus the last N."""
```

Stored `.pt` bundle shape:

```python
{
    "state_dict": ...,    # model weights
    "spec": ...,          # serialized NNModelSpec — authority for rebuilding architecture
    "manifest": ...,      # per-feature training normalisation stats (leakage guard at inference)
    "feature_cols": ...,  # ordered feature column names
    "metrics": ...,       # the metrics dict passed to save()
}
```

Attributes: `checkpoint_dir` (str), `model_name` (str), `best_metric` (float), `mode` (str).

## Key Constraints
- Checkpoint bundles the normalisation manifest + `feature_cols` so the model is **self-contained at inference** (leakage guard): inference normalises with training stats, never inference-dataset stats.
- The embedded spec is the authority for rebuilding architecture; inference reads output columns from the spec's targets (spec mismatch → embedded spec wins, caller adapts).
- `mode` (`max`/`min`) governs the promotion comparison; the promotion **gate** (holdout + margin) is owned by `ExperimentTracker` and surfaced here via `promote=True`.
- Atomic writes (temp `.tmp` + `os.rename`); on failure remove the temp file and raise. Never overwrite `_best.pt` with a worse model unless `promote=True`.
- `best_metric` is reconstructable from `{model_name}_best.pt`'s stored metrics if the manager restarts mid-search.
- Loading a missing/corrupt best/epoch checkpoint → returns `None`/`False`; disk full on save → raises (loop records the trial as failed and continues).
- Use `torch.save`; prefer `weights_only` loading where supported.

### Tests to change (from existing 25)
- `__init__` tests: add a `mode="min"` case asserting `best_metric == +inf`; keep the `mode="max"` → `-inf` case.
- All `save(...)` call sites must pass a `manifest=` argument (and `promote=` where exercising forced promotion).
- `load_best` tests #11/#12: assert the returned value is a `{manifest, feature_cols}` dict on success and `None` when no best exists (was `True`/`False`).
- `list_checkpoints` structure test #18: assert each entry now also has a `metrics` key carrying the saved metrics.
- Add a test that a saved bundle round-trips `manifest` + `feature_cols` through `load_best`, and that `promote=True` writes `_best.pt` even when the gate metric did not improve.
- `load_epoch`, `cleanup`, sorting, size, atomicity, custom-name tests are unchanged in intent (only the added `manifest=` arg on `save`).

## Verification
```bash
docker compose run --rm nn-train python3 -c "
import tempfile, numpy as np
from nn.checkpoint_manager import CheckpointManager
from nn.nn_model import NNModel
d = tempfile.mkdtemp()
m = NNModel(input_size=4, hidden_size=8, num_classes=3)
m.train(np.random.randn(40,4).astype('float32'), np.random.randint(0,3,40), epochs=1)
cm = CheckpointManager(d, model_name='tf15', mode='max')
manifest = {'f0': {'mean': 0.0, 'std': 1.0}}
fc = ['f0','f1','f2','f3']
p = cm.save(m, {'val_accuracy': 0.5}, epoch=1, manifest=manifest, promote=True)
assert p.endswith('tf15_epoch1.pt')
m2 = NNModel(input_size=4, hidden_size=8, num_classes=3)
res = cm.load_best(m2)
assert res is not None and res['manifest'] == manifest and res['feature_cols'] == fc, res
lst = cm.list_checkpoints()
assert lst and 'metrics' in lst[0] and 'size_bytes' in lst[0], lst
empty = CheckpointManager(tempfile.mkdtemp())
assert empty.load_best(NNModel(input_size=4, hidden_size=8, num_classes=3)) is None
for e in range(2,6): cm.save(m, {'val_accuracy':0.4}, epoch=e, manifest=manifest)
cm.cleanup(keep_best=True, keep_last_n=2)
assert len(cm.list_checkpoints()) == 2
print('OK')
"
docker compose run --rm nn-train python3 -m pytest tests/unit/nn/test_checkpoint_manager.py -q
```

## Commit
`refactor(nn): self-contained CheckpointManager (manifest bundle, promote gate, mode)`
