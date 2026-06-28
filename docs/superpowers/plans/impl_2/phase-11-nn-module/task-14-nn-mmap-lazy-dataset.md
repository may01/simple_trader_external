# Task 14: mmap + Lazy Per-Batch Dataset (host-RAM O(batch))

**Phase:** 11 — NN Module
**Depends on:** Task 04 (NNDataset), Task 05 (NNModel), Task 13 (minibatch training loop)
**Produces:** lazy mmap-backed dataset in `nn/nn_dataset.py`; rewired `nn/nn_model.py` training load path; expanded tests
**Branch:** `nn-mmap-dataset` (off `nn-minibatch-training`, or off `experimental_imp_2` after Task 13 merges)
**Layer:** 2 — Training pipeline (internal load path; public contracts unchanged)

---

## Goal

Task 13 made **GPU** memory scale with `batch_size`. **Host RAM** still scales with
dataset size: a 3-year heavy spec materialises a ~24–48 GB `X` array several times over in
RAM during the training load. Make host RAM **O(batch + OS page cache)**, independent of row
count, by memory-mapping the on-disk tensors and assembling each batch's windows lazily.

---

## Context — where host RAM blows up (training path)

1. `NNDataset.tensors()` (`nn/nn_dataset.py`):
   - `np.load(d/f"X_{tf}.npy")` — **no `mmap_mode`** → every per-TF block fully resident.
   - `np.concatenate(blocks, axis=2)` → a **second** full array (~2× peak) while blocks still referenced.
   - then row-slice (view).
2. `NNModel._split_dataset()` calls `dataset.split("train").tensors()` **and** `dataset.split("val").tensors()`. `split()` only sets a row range; `tensors()` still loads the **full** `X_{tf}.npy` each time → **full X loaded twice**.
3. `NNModel._run_training` / `_make_loader` wrap the result in `torch.tensor(np.asarray(X, float32))` → **another** full copy into a torch tensor.

Net training peak ≈ **~4–5× full X** in host RAM. For a 3-year heavy spec that is >100 GB — infeasible. Tensors are written **already-normalised float32** at build (Task 04 / Task 13 finding), so loading needs **no transform** — mmap is straightforward.

Secondary (out of scope here): `build_inference_matrix()` concatenates a full per-df matrix in
RAM for batch inference; the orchestrator should chunk the df. Track separately if it bites.

---

## Files

- Modify: `nn/nn_dataset.py` — add `torch_dataset()`, `labels()`, the lazy `_MmapWindowDataset`; mmap inside `tensors()`
- Modify: `nn/nn_model.py` — `_split_dataset` / `_run_training` consume the lazy dataset + cheap labels; drop the full-numpy `tensors()` → `_flatten` → `TensorDataset` path for training
- Modify: `tests/unit/nn/test_nn_dataset.py`, `tests/unit/nn/test_nn_model.py`
- Update spec doc: `external/.../nn-module/datapoint-generator-class.md` (lazy mmap load, host-RAM O(batch))

---

## Docker Entry Points (ground truth)

```bash
docker compose run --rm nn-train python -m pytest tests/unit/nn/test_nn_dataset.py tests/unit/nn/test_nn_model.py -q
# Optional host-RAM proof on a GPU/large host: RSS stays batch-scaled, not row-scaled
docker compose run --rm nn-train /usr/bin/time -v python -m pytest tests/unit/nn/test_nn_model.py -k lazy_memory -q
```
Verified: [ ] tests green in Docker · [ ] RSS on a ~100k-row synthetic is batch-scaled

---

## Interface (additive; public training contract unchanged)

```python
# nn/nn_dataset.py
def torch_dataset(self, split: "str | None" = None) -> "torch.utils.data.Dataset": ...
    # Lazy, mmap-backed. Opens each X_{tf}.npy with np.load(mmap_mode='r') and y.npy mmap;
    # __getitem__(i) gathers ONE row's window from each TF mmap and concatenates along the
    # feature axis in manifest['timeframes'] order → (history_points, sum_tf n_features) float32,
    # plus that row's y. Only batch-sized data is ever resident.

def labels(self, split: "str | None" = None) -> "np.ndarray": ...
    # The y rows for a split (small: rows × target_width). Cheap to fully load — used for
    # global balanced class weights without materialising X.

def tensors(self) -> "tuple[np.ndarray, np.ndarray]": ...   # unchanged signature
    # Now loads X_{tf}.npy with mmap_mode='r' (no second pre-concat full copy). Kept for
    # inference parity / small datasets / tests; training no longer routes through it.
```

`NNModel._run_training` (Task 13 loop) stays minibatched; only its **data source** changes:
build the `DataLoader` over `dataset.torch_dataset("train"/"val")`; compute class weights from
`dataset.labels("train")` (cheap). Behavioural contract unchanged (steps/epoch, metrics keys,
row-weighted means, seeded shuffle, single-step parity).

---

## Integration test → training path (RED in Docker)

```text
test_training_runs_over_lazy_mmap_dataset:
  write on-disk NNDataset (existing _write_dataset helper saves real .npy)
  spy np.load → assert X_{tf}.npy opened with mmap_mode='r' during train()
  m.train(ds) completes, metrics finite, is_trained True
```

---

## Unit tests (RED before implementation)

- `test_lazy_dataset_byte_parity_with_tensors` — `torch_dataset()` stacked over all rows equals `tensors()[0]` element-for-element (concat order incl. non-ascending timeframes e.g. [60,15]).
- `test_lazy_getitem_returns_single_row_window` — `__getitem__(i)` shape `(history_points, sum_tf n_features)`; y shape `(target_width,)`.
- `test_train_metrics_match_full_and_lazy` — tiny set: metrics from lazy path == metrics from the Task-13 full path (regression guard, same seed).
- `test_X_opened_with_mmap` — spy `np.load`: every `X_{tf}.npy` opened with `mmap_mode='r'` (no full-resident load) in both `tensors()` and `torch_dataset()`.
- `test_labels_loads_y_only_not_X` — `labels("train")` returns correct y rows without opening any `X_{tf}.npy` (spy asserts X files untouched).
- `test_split_does_not_double_load` — training a model opens each `X_{tf}.npy` via mmap, never fully reads it twice (spy on np.load count / mmap usage).
- `test_lazy_memory_proxy` (marker `lazy_memory`) — on a larger synthetic (e.g. 5000 rows), training completes; resident-array proxy (no `np.concatenate` over full row axis) holds.
- `test_splits_json_absent_lazy_fallback` — no `splits.json` → lazy time-holdout ranges still train (keep Task-13 fallback semantics).

---

## Key Constraints

- **Concat order = `manifest['timeframes']` declaration order**, never sorted (a `[60,15]` spec must not swap feature channels — same guard as `build_inference_matrix`).
- Tensors are **already normalised float32 on disk** → lazy gather does **no** transform/cast; per-row cost is one small `np.concatenate` over the feature axis + `.copy()` out of the mmap.
- **Class weights** still global/once: from `dataset.labels("train")` (cheap full-y), not per batch, moved `.to(device)`.
- **Shuffle** (Task 13): `shuffle_train` random-accesses mmap rows → random disk seeks. Fine on SSD/NVMe; note for HDD. `num_workers=0` default (memmap pickles by path, so `NUM_WORKERS>0` is a valid later opt-in to overlap I/O).
- NaN rows already dropped at build → lazy rows are clean; no per-row NaN handling.
- `tensors()` retains its signature and byte-output (now mmap-loaded) so inference-parity and existing callers are unaffected.
- Public `train()` / `run` / `run_batch` / checkpoints unchanged. No `dataset_hash` / `spec_hash` change (pure load-path refactor).

---

## Verification

```bash
docker compose run --rm nn-train python -m pytest tests/unit/nn/test_nn_dataset.py tests/unit/nn/test_nn_model.py -q
# expect: all green incl. new lazy/mmap tests
```
Host-RAM sanity (large host): train a ~200k-row synthetic; `/usr/bin/time -v` peak RSS should
track `batch_size`, not row count (contrast against a pre-Task-14 run).

---

## Commit

`perf(nn): mmap + lazy per-batch dataset — host RAM O(batch) not O(rows)`
```
