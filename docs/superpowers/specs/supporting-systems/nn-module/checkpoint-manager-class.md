# CheckpointManager Class Specification

**File:** `nn/checkpoint_manager.py`
**Purpose:** Save and load **PyTorch** `NNModel` weights with versioning and best-model tracking. Prevents overwriting the best model with a worse one.

---

## 1. Class Overview

`CheckpointManager` persists `NNModel` weights during training and provides clean loading for inference. Each checkpoint stores the `state_dict`, the model's embedded `NNModelSpec`, **and the normalisation manifest** (feature-column list + per-feature training stats), so a model is **fully self-contained for inference on any dataset** — it can be reconstructed and applied without the training dataset or its folder being present. The manager tracks the best model by the promotion metric and exposes `load_best()` for the inference path.

> **Why bundle the manifest.** `run_inference` (see `nn-orchestrator-class.md` §4.3) runs on arbitrary datasets. Features must be normalised with the **training** stats, not stats recomputed from the inference dataset (distribution-shift / leakage). Bundling the manifest in the checkpoint makes those stats travel with the weights, so inference never depends on the training dataset's `NNDataset`/folder.

Used by the `TrainingLoop`/`NNOrchestrator` (saving during search) and indirectly by `NNOrchestrator.run_inference()` (loading best for batch inference).

---

## 2. Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `checkpoint_dir` | `str` | Directory for this group's checkpoints (created if absent). |
| `model_name` | `str` | Prefix for files, e.g. `tf15`. |
| `best_metric` | `float` | Best promotion-metric value seen (`-inf` / `+inf` by `mode`). |
| `mode` | `str` | `"max"` (accuracy) or `"min"` (regression error). |

---

## 3. Constructor

### `__init__(checkpoint_dir, model_name="model", mode="max")`
- Creates `checkpoint_dir` if it does not exist.
- Initialises `best_metric` per `mode`.

---

## 4. Key Methods

### `save(model, metrics, epoch, manifest, promote=False) -> str`
- Saves `{checkpoint_dir}/{model_name}_epoch{epoch}.pt` containing `{"state_dict":…, "spec":…, "manifest":…, "feature_cols":…, "metrics":…}`, where `manifest` holds the per-feature training normalisation stats and `feature_cols` the ordered feature column names.
- If `promote` or `metrics[gate]` improves on `best_metric` (per `mode`): also writes `{model_name}_best.pt` and updates `best_metric`.
- Returns the saved checkpoint path.

### `load_best(model) -> dict | None`
- Loads `{model_name}_best.pt` into `model` via `model.load_model()` (rebuilding from the embedded spec) and restores the normalisation `manifest` + `feature_cols` onto the model / returns them to the caller.
- Returns the `{manifest, feature_cols}` dict if loaded, `None` if no best checkpoint exists (caller treats as "no model" — inference is skipped, consumers stay absence-safe).

### `load_epoch(model, epoch) -> bool`
- Loads a specific epoch checkpoint. Returns `True`/`False`.

### `list_checkpoints() -> list[dict]`
- Returns `[{epoch, path, size_bytes, metrics}]` for all saved checkpoints.

### `cleanup(keep_best=True, keep_last_n=3) -> None`
- Deletes old epoch checkpoints, retaining the best (if `keep_best`) plus the last N. Prevents unbounded disk growth across a long search.

---

## 5. State & Persistence

- Checkpoints are PyTorch `.pt` files written with `torch.save`; `weights_only` loading is used where supported.
- The embedded spec is the authority for rebuilding architecture; the embedded manifest + `feature_cols` are the authority for normalising inference features — a checkpoint is self-contained across datasets.
- `best_metric` is reconstructable from `{model_name}_best.pt`'s stored metrics on construction if the manager restarts mid-search.

---

## 6. Error Handling

- Loading a missing/corrupt checkpoint → returns `False` (best/epoch) or raises with the offending path (explicit load).
- Spec mismatch between stored checkpoint and a caller's expectation → the embedded spec wins; the caller adapts (inference reads output columns from the spec's targets).
- Disk full on save → raises; the loop records the trial as failed and continues.

---

## 7. Notes

- One `CheckpointManager` per group (class/regime; a single group if `grouping=single`) — separate `checkpoint_dir` or `model_name`.
- Promotion is decided by `ExperimentTracker` (holdout + margin); `CheckpointManager.save(promote=True)` is how that decision is persisted to weights. The two stay in sync via the loop.
