# Task 13: Minibatched NN Training (DataLoader)

**Phase:** 11 — NN Module
**Depends on:** Task 02 (NNModelSpec), Task 05 (NNModel)
**Produces:** reworked `nn/nn_model.py::_run_training`, new `NNModelSpec.shuffle_train`, expanded `tests/unit/nn/test_nn_model.py`
**Branch:** `nn-minibatch-training` (off `experimental_imp_2`)
**Layer:** 2 — Training pipeline (internal; `train()` contract unchanged)

---

## Goal

Stop loading the **entire** train+val split onto the GPU. `_run_training` currently moves
`X_train/y_train/X_val/y_val` to `device` in full and runs one full-batch
`forward/backward` per epoch — `spec.batch_size` is ignored. GPU memory therefore scales
with **dataset size**, so a 3-year set (~1.58M rows) busts a 4 GB GPU at any realistic
`history_points`/feature count.

Replace the full-batch loop with `DataLoader` minibatching so **GPU-resident memory scales
with `batch_size`, not row count**. Metrics, early-stopping, class weights, per-target
losses, and the public `train()` signature stay identical.

---

## Context

Root cause — `nn/nn_model.py::_run_training`:
- L384–387: `torch.tensor(X_*, device=device)` for the whole split (train **and** val resident at once).
- L397–403: `for epoch` → single `head_logits(Xtr)` over all rows, one `backward()`. No inner batch loop.

`batch_size: 32` exists in `nn_spec.yaml` but is never read. Holdout (0.2) is excluded by
`split()`; train+val (~0.8 of rows) sit on GPU simultaneously.

The model is **stateless per forward** (`_SpecNet`, `batch_first`, no hidden-state carry across
batches), so sample-axis shuffling is safe for dense **and** sequence (lstm/gru/conv1d) layers —
`history_points` is the per-sample sequence dim, untouched by shuffle. Only a future *stateful*
RNN (BPTT across batch boundaries) would need shuffle off; that is the reason `shuffle_train`
is a spec flag, not hardcoded `True`.

Out of scope (separate follow-up task): host-RAM blowup in `NNDataset.tensors()`
(`np.load` no-mmap + `np.concatenate` 2× peak + `_flatten` copy). Fixing GPU does not cure
host RAM for very large specs; track as Task 14 (`mmap_mode='r'` + lazy per-batch TF assembly).

---

## Files

- Modify: `nn/nn_model.py` — `_run_training` (minibatch loop), `_overall_accuracy` (return counts), `_class_weights` (global, once, `.to(device)`), per-target loss accumulation
- Modify: `nn/nn_model_spec.py` — add `shuffle_train: bool = True`
- Modify: `configs/nn_spec.yaml` — document `shuffle_train` (optional key; default True)
- Modify: `tests/unit/nn/test_nn_model.py` — add minibatch tests; keep all existing green
- Update spec doc: `external/.../nn-module/nnmodel-class.md` (training section: minibatched, batch_size honoured, shuffle policy)

---

## Docker Entry Points (ground truth)

```bash
# Unit + integration tests for this task (must be GREEN in Docker before done)
docker compose run --rm nn-train python -m pytest tests/unit/nn/test_nn_model.py -q

# Real training path unchanged — now minibatched, GPU holds one batch
docker compose run --rm nn-train train_nn   # RUN_TYPE=nn_train, NN_TRAIN_MODE=single
```
Verified: [ ] tests green in Docker · [ ] `train_nn` smoke run completes on CPU

---

## Interface (unchanged public contract + one spec field)

```python
# nn/nn_model_spec.py — additive, backward compatible
class NNModelSpec:
    shuffle_train: bool = True   # shuffle TRAIN batches per epoch; val/inference never shuffle

# nn/nn_model.py — signatures UNCHANGED
def train(self, dataset: "NNDataset", epoch_callback: "Optional[Callable[[int, dict], object]]" = None) -> dict: ...
def _run_training(self, X_train, y_train, X_val, y_val, epoch_callback, device) -> dict: ...
```

Behavioural contract (the thing tests pin):
- Optimizer steps per epoch == `ceil(n_train / spec.batch_size)`.
- `batch_size >= n_train` → exactly 1 step/epoch (parity with old full-batch).
- Returned metrics dict keys identical: `{loss, accuracy, val_loss, val_accuracy, per_target}`.
- `train_loss`/`val_loss` are row-weighted means over batches (equal to full-batch mean when 1 step).
- GPU-resident tensors per step are `O(batch_size)`, independent of `n_train`.

---

## Integration test → training path (RED in Docker)

```text
test_train_path_minibatched_end_to_end:
  build tiny NNModelSpec (history=2, 2 indicators, 2 tf, batch_size=8, epochs=2)
  assemble in-memory NNDataset ~50 rows
  m.train(ds)  → is_trained True, metric keys present, loss finite
  (proves DataLoader wiring runs through real train() → _run_training in Docker)
```

---

## Unit tests (RED before implementation)

Keep existing green: metric keys, per_target keyed by name, callback called N times,
stop-signal prunes, is_trained flag.

Add:
- `test_steps_per_epoch_equals_ceil_rows_over_batch` — monkeypatch `optimizer.step`, count == `ceil(n/batch)`.
- `test_batch_ge_rows_single_step` — `batch_size >= n_train` → 1 step/epoch.
- `test_loss_decreases_minibatched` — multi-epoch on separable synthetic → final loss < first.
- `test_metrics_are_row_weighted_means` — train_loss finite, `0 <= accuracy <= 1`.
- `test_seeded_shuffle_deterministic` — same `seed` + `shuffle_train=True` → identical epoch-0 metrics across two runs.
- `test_shuffle_off_is_order_preserving` — `shuffle_train=False` → deterministic, matches single-step path when batch≥rows.
- `test_val_never_shuffled` — val metrics identical regardless of `shuffle_train`.
- `test_class_weights_computed_once_global` — balanced weights derived from full train labels, not per-batch (assert weights stable across batch sizes).

---

## Key Constraints

- Public `train()` / `run` / `run_batch` signatures unchanged; checkpoints unaffected.
- **Class weights global**: compute once from full `y_train` before the epoch loop, move weight tensors `.to(device)`. Never per-batch.
- **Loss/accuracy accumulation**: weight per-batch loss by batch row count; accumulate `correct/count` for accuracy; `per_target` accumulated × rows then normalized. Single-step path must reproduce old numbers (regression guard).
- **Shuffle policy**: train shuffles iff `spec.shuffle_train` (default True), seeded by `spec.seed` via DataLoader `generator`; **val always `shuffle=False`; inference never uses a shuffling loader**.
- `num_workers=0` (tensors already materialized in RAM; worker fork is pure overhead).
- `drop_last=False` (keep every row).
- **OOM→CPU retry preserved** (`train()` L322–332); now rarely triggers but stays as the device-policy fallback.
- Move batches with `.to(device, non_blocking=True)`; keep `TensorDataset` on CPU.

---

## Verification

```bash
docker compose run --rm nn-train python -m pytest tests/unit/nn/test_nn_model.py -q
# expect: all green, including the 8 new minibatch tests
```
Manual GPU-memory sanity (optional, GPU host): train a ~100k-row synthetic with small
`batch_size` and confirm `nvidia-smi` peak is batch-scaled, not dataset-scaled.

---

## Commit

`fix(nn): minibatch training via DataLoader — GPU memory scales with batch, not dataset`
