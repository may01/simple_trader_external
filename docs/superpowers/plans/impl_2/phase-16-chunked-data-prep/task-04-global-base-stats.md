# Task 04: Global base-attribute stats from base parts

**Phase:** 16 — Chunked Data Prep
**Depends on:** Task 03 (base part files), existing `indicators.DataAttributes.compute`
**Produces:** `DataPreparer._global_base_stats`

---

## Goal

Compute the base-attribute stats (`rsi_classification.json`, `diff_stats.pkl`)
ONCE over all base parts, so every Pass-2 portion classifies against the same
global thresholds. This is the step that makes class indicators consistent across
portions.

---

## Files

- Modify: `training/data_preparer.py` — add `_global_base_stats`
- Test: `tests/training/test_global_base_stats.py`

---

## Interface

```python
def _global_base_stats(self, base_part_paths: list[str]) -> None:
    """Concatenate base parts in index order and run DataAttributes.compute(df)
    to write rsi_classification.json + diff_stats.pkl.

    Idempotent: DataAttributes.compute already no-ops when the stats files exist
    (current behaviour), so re-running after a resume does not rewrite them.
    """
```

Behaviour:
1. `frames = [pd.read_pickle(p) for p in base_part_paths]` (paths already in
   ascending portion order from the orchestrator).
2. `full = pd.concat(frames)` (indexes are contiguous, non-overlapping).
3. `from indicators import DataAttributes; DataAttributes().compute(full)`.

---

## Tests (RED first)

```python
# tests/training/test_global_base_stats.py
import json, os
import pandas as pd
from training.data_preparer import DataPreparer

def test_stats_match_single_concatenated_frame(base_parts_and_single, tmp_dataset):
    """Stats from parts == stats from the equivalent single base frame."""
    parts, single_frame = base_parts_and_single
    prep = DataPreparer(...)
    prep._global_base_stats(parts)
    from helpers import stats_folder
    chunked = json.load(open(os.path.join(stats_folder(), "rsi_classification.json")))

    # recompute reference from the single frame in a clean stats dir
    # (fixture isolates stats_folder per case)
    os.remove(os.path.join(stats_folder(), "rsi_classification.json"))
    os.remove(os.path.join(stats_folder(), "diff_stats.pkl"))
    from indicators import DataAttributes
    DataAttributes().compute(single_frame)
    ref = json.load(open(os.path.join(stats_folder(), "rsi_classification.json")))

    assert chunked == ref

def test_idempotent_when_stats_exist(base_parts_and_single, tmp_dataset):
    parts, _ = base_parts_and_single
    prep = DataPreparer(...)
    prep._global_base_stats(parts)
    from helpers import stats_folder
    p = os.path.join(stats_folder(), "rsi_classification.json")
    mtime = os.path.getmtime(p)
    prep._global_base_stats(parts)         # second call
    assert os.path.getmtime(p) == mtime    # not rewritten
```

Run RED: `pytest tests/training/test_global_base_stats.py -v` → FAIL.

---

## Key constraints

- Stats parity is the correctness keystone: the concatenated base parts contain
  exactly the owned rows `[DATA_START, DATA_END)` with base indicators filled —
  the same rows the single-pass `_compute_base_attributes` sees after warmup rows
  drop out (they are NaN and excluded from closed-candle reductions).
- Concatenation order matters only for index monotonicity; the reductions are
  order-independent, but keep ascending order for sane debugging.
- Do not hold the concatenated frame longer than needed — it is built only to
  feed `DataAttributes.compute`, then released.

---

## Verification

```bash
docker compose run --rm ohlc_gen python3 -c "
import glob, os
from helpers import data_folder, stats_folder
from training.data_preparer import DataPreparer
parts = sorted(glob.glob(os.path.join(data_folder(), 'df_base.part_*.pkl')))
DataPreparer(...)._global_base_stats(parts)
assert os.path.exists(os.path.join(stats_folder(), 'rsi_classification.json'))
print('global stats ok')
"
```

---

## Commit

`feat(data-prep): global base-attr stats from base parts (consistent thresholds)`
