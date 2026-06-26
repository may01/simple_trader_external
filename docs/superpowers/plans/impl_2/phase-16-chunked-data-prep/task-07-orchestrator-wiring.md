# Task 07: `prepare_chunked` orchestrator + manifest + trainer wiring

**Phase:** 16 — Chunked Data Prep
**Depends on:** Tasks 01–06, existing `_load_raw_data`, `training/trainer.py::_run_prepare_data`
**Produces:** `DataPreparer.prepare_chunked`, `_chunk_manifest_path`, `_chunk_config_hash`; updated `_run_prepare_data`

---

## Goal

Wire the helpers into one entry point: decide single-vs-chunked, purge stale
parts on config drift, drive Pass 1 → global stats → Pass 2 → merge with progress
logging, and route the trainer's prepare step through it. This is the layer
integration point.

---

## Files

- Modify: `training/data_preparer.py` — add `prepare_chunked`, `_chunk_manifest_path`, `_chunk_config_hash`
- Modify: `training/trainer.py` — `_run_prepare_data` reads `DATA_END`, calls `prepare_chunked`
- Test: `tests/training/test_prepare_chunked.py`

---

## Interface

```python
def prepare_chunked(self, raw_data_path: str,
                    data_start_ms: int, data_end_ms: int) -> None:
    """Resumable, progress-logged preparation.

    span_days, min_rows = chunk_config()
    If _window_row_count(data_start_ms, data_end_ms) < min_rows:
        self.prepare(raw_data_path, data_start_ms)     # unchanged single-pass
        return
    Else drive the chunked pipeline (steps below).
    """

def _chunk_manifest_path(self) -> str:        # {data_folder()}chunk_manifest.json
def _chunk_config_hash(self, start_ms: int, end_ms: int, span_days: int) -> str: ...
```

Chunked pipeline:
1. `boundaries = _chunk_boundaries(start, end, span_days)`.
2. Manifest guard: if `_chunk_manifest_path()` exists and its stored hash !=
   `_chunk_config_hash(...)`, delete all `df_base.part_*` + `df_with_indicators.part_*`
   (stale config). Write the current hash.
3. `raw_df = self._load_raw_data(raw_data_path)` (once; shared read-only).
4. **Pass 1:** `prog = _ChunkProgress("pass1 base-ind", len(boundaries))`;
   for `i, win in enumerate(boundaries)`: `_pass1_base_portion(raw_df, i, win)`;
   `prog.tick(i+1, rows_so_far)`.
5. `_global_base_stats([_base_part_path(i) for i in range(len(boundaries))])`.
6. **Pass 2:** `prog = _ChunkProgress("pass2 class-ind", len(boundaries))`;
   for `i, win in enumerate(boundaries)`: `prev = _base_part_path(i-1) if i > 0 else None`;
   `_pass2_class_portion(i, win, prev)`; `prog.tick(i+1, rows_so_far)`.
7. `_merge_parts(finals, bases)`.

Trainer wiring (`training/trainer.py::_run_prepare_data`):
```python
preparer.prepare_chunked(
    graber_data_path(),
    data_start_ms=int(os.environ["DATA_START"]),
    data_end_ms=int(os.environ["DATA_END"]),
)
```

---

## Tests (RED first)

```python
# tests/training/test_prepare_chunked.py
import os, glob
import pandas as pd
from training.data_preparer import DataPreparer

def test_below_threshold_calls_prepare(monkeypatch, small_dataset):
    prep = DataPreparer(...)
    called = {}
    monkeypatch.setattr(prep, "prepare", lambda p, s: called.setdefault("hit", True))
    monkeypatch.setenv("CHUNK_MIN_ROWS", "999999999")
    DAY = 86_400_000
    prep.prepare_chunked(RAW, 0, 14*DAY)
    assert called.get("hit")                       # single-pass path
    assert not glob.glob(os.path.join(DATA_FOLDER, "*.part_*.pkl"))

def test_above_threshold_produces_output(forced_chunk_env, small_dataset):
    # CHUNK_MIN_ROWS=0, CHUNK_SPAN_DAYS=3 → multi-chunk
    prep = DataPreparer(...)
    DAY = 86_400_000
    prep.prepare_chunked(RAW, 0, 14*DAY)
    assert os.path.exists(prep.output_path)
    assert not glob.glob(os.path.join(DATA_FOLDER, "*.part_*.pkl"))  # merged + cleaned

def test_stale_manifest_purges_parts(forced_chunk_env, small_dataset):
    prep = DataPreparer(...)
    DAY = 86_400_000
    # seed a part + a manifest with a mismatching hash
    open(os.path.join(DATA_FOLDER, "df_base.part_00.pkl"), "w").close()
    with open(prep._chunk_manifest_path(), "w") as f: f.write('{"config_hash": "STALE"}')
    prep.prepare_chunked(RAW, 0, 14*DAY)
    # stale part was discarded, run completed cleanly
    assert os.path.exists(prep.output_path)

def test_resume_skips_existing(forced_chunk_env, small_dataset, monkeypatch):
    prep = DataPreparer(...)
    DAY = 86_400_000
    prep.prepare_chunked(RAW, 0, 14*DAY)            # full run
    # rerun: pass-1 worker must not recompute (spy it raises if called)
    monkeypatch.setattr(prep, "_pass1_base_portion",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("recomputed")))
    # parts already merged+deleted, so a clean rerun rebuilds; this asserts the
    # skip path on a half-finished run instead — see Docker resume test (Task 08)
```

Run RED: `pytest tests/training/test_prepare_chunked.py -v` → FAIL.

### Integration test → Docker (RED in Docker)

```python
# tests/training/test_prepare_chunked_docker.py  (marker: docker)
def test_ohlc_gen_chunked_path_writes_output():
    """Run the ohlc_gen entry with forced chunking; assert merged output exists.
    RED before prepare_chunked is wired into _run_prepare_data."""
```

---

## Key constraints

- `_load_raw_data` runs once; the same `raw_df` feeds every Pass-1 portion
  (read-only) — this is what "share grabbed data" means.
- Portions run SEQUENTIALLY so `_ChunkProgress` ETA is meaningful and per-portion
  fork-pool memory stays bounded. Do not parallelise across portions.
- Manifest stores only the config hash (`DATA_START`, `DATA_END`, `CHUNK_SPAN_DAYS`).
  Skip logic itself is file-existence based; the manifest only guards against a
  config change between runs silently merging incompatible portions.
- `DATA_END` must be present in env for the chunked path; it already is for every
  dataset env file (`backtesting_flow.md`).
- Below-threshold path is byte-for-byte the current behaviour — only the call site
  changes.

---

## Verification

```bash
TRAIN_ENV=configs/train_dataset.env CHUNK_SPAN_DAYS=3 CHUNK_MIN_ROWS=0 \
    docker compose up ohlc_gen
# expect: pass1/pass2 portion logs with ETA, then a merged df_with_indicators.pkl
docker compose run --rm ohlc_gen python3 -c "
import os; from helpers import wide_df_path; assert os.path.exists(wide_df_path()); print('chunked prepare ok')
"
```

---

## Commit

`feat(data-prep): prepare_chunked orchestrator, manifest guard, trainer wiring`
