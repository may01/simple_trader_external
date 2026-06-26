# Task 05: Pass-2 class-indicator portion worker

**Phase:** 16 — Chunked Data Prep
**Depends on:** Task 03 (`_base_part_path`), Task 04 (persisted stats), existing `_compute_class_indicators`, `CANDLES`, `constants.INDICATOR_WINDOW_ROWS`
**Produces:** `DataPreparer._pass2_class_portion`

---

## Goal

Compute the class indicators (`classification`, `targets`) for one portion using
the global stats, and persist the FINAL part (base + class columns) for its owned
window. Class fields need at most one prior row (`targets` uses `.shift(1)`,
`classification` uses none) — so a small lookback margin from the previous base
part makes interior boundaries bit-identical to single-pass.

---

## Files

- Modify: `training/data_preparer.py` — add `_pass2_class_portion`
- Test: `tests/training/test_pass2_class_portion.py`

---

## Interface

```python
def _pass2_class_portion(self, index: int, window: tuple[int, int],
                         prev_base_path: str | None) -> str:
    """Compute class indicators for owned window [w0, w1) and save the final part
    to _final_part_path(index) atomically.

    Loads _base_part_path(index); if prev_base_path is not None, prepends a
    lookback margin of INDICATOR_WINDOW_ROWS * max(CANDLES) rows from the tail of
    the previous base part so per-row slices (build_indicator_input) are full.
    Computes class indicators with start_ts = w0, then drops the prepended rows
    before saving.

    Returns the final part path. Skips (returns path) if the final part exists.
    """
```

Behaviour:
1. If `os.path.exists(_final_part_path(index))` → return it (skip).
2. `base = pd.read_pickle(_base_part_path(index))`.
3. If `prev_base_path`: `margin = INDICATOR_WINDOW_ROWS * max(CANDLES)`;
   `lead = pd.read_pickle(prev_base_path).iloc[-margin:]`;
   `frame = pd.concat([lead, base])`. Else `frame = base`.
4. `w0_ts = Timestamp(window[0])`; `self._compute_class_indicators(frame, start_ts=w0_ts)`.
5. `owned = frame.loc[frame.index >= w0_ts]` (drops the prepended lead).
6. Atomic save `owned` to `_final_part_path(index)`.

---

## Tests (RED first)

```python
# tests/training/test_pass2_class_portion.py
import os
import pandas as pd
import numpy as np
from training.data_preparer import DataPreparer, _base_part_path, _final_part_path

def test_class_columns_present(two_base_parts, tmp_dataset):
    prep = DataPreparer(...)
    DAY = 86_400_000
    path = prep._pass2_class_portion(1, (3*DAY, 4*DAY), prev_base_path=_base_part_path(0))
    part = pd.read_pickle(path)
    assert "15_move_class" in part.columns and "15_zone_class" in part.columns

def test_interior_boundary_matches_single_pass(two_base_parts, single_pass_frame, tmp_dataset):
    """First owned row's targets equal the single-pass value (lookback works)."""
    prep = DataPreparer(...)
    DAY = 86_400_000
    path = prep._pass2_class_portion(1, (3*DAY, 4*DAY), prev_base_path=_base_part_path(0))
    part = pd.read_pickle(path)
    first_ts = part.index[0]
    assert np.isclose(part.loc[first_ts, "15_tgt_long"],
                      single_pass_frame.loc[first_ts, "15_tgt_long"], equal_nan=True)

def test_portion0_first_row_target_nan(two_base_parts, tmp_dataset):
    prep = DataPreparer(...)
    DAY = 86_400_000
    path = prep._pass2_class_portion(0, (0, 3*DAY), prev_base_path=None)
    part = pd.read_pickle(path)
    assert pd.isna(part.iloc[0]["15_tgt_long"])   # matches single-pass first row

def test_skip_if_exists(two_base_parts, tmp_dataset):
    prep = DataPreparer(...)
    DAY = 86_400_000
    p = prep._pass2_class_portion(1, (3*DAY, 4*DAY), prev_base_path=_base_part_path(0))
    m = os.path.getmtime(p)
    assert prep._pass2_class_portion(1, (3*DAY, 4*DAY), prev_base_path=_base_part_path(0)) == p
    assert os.path.getmtime(p) == m
```

Run RED: `pytest tests/training/test_pass2_class_portion.py -v` → FAIL.

---

## Key constraints

- Lookback margin `INDICATOR_WINDOW_ROWS * max(CANDLES)` is deliberately generous:
  class fields need ≤1 prior row, but `build_indicator_input` is the shared
  slicing mechanism (105-row window), so feed it a full window for robustness
  against future class fields. The prepended rows are dropped before save.
- Portion 0 has `prev_base_path=None`: its first row's `targets` resolve to NaN —
  identical to single-pass, where `shift(1)` at `DATA_START` references a warmup
  row whose base indicators are NaN. Do NOT special-case to avoid the NaN.
- `_compute_class_indicators` reads stats via the LRU-cached loaders; Task 04 must
  have written them first. The orchestrator (Task 07) enforces that ordering.
- Final part = owned window only, base + class columns. No labels yet (merge step).

---

## Verification

```bash
docker compose run --rm ohlc_gen python3 -c "
import pandas as pd
from training.data_preparer import DataPreparer, _base_part_path, _final_part_path
DAY=86_400_000
p=DataPreparer(...)._pass2_class_portion(1,(3*DAY,4*DAY),_base_part_path(0))
print('final part cols include class:', '15_move_class' in pd.read_pickle(p).columns)
"
```

---

## Commit

`feat(data-prep): pass-2 class-indicator portion with boundary lookback`
