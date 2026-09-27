# Task 06: Merge parts → labels → nn → save → cleanup

**Phase:** 16 — Chunked Data Prep
**Depends on:** Task 05 (final part files), existing `_compute_profit_labels`, `_compute_nn_attributes`

> **Implementation note:** On the current branch `prepare()` does **not** left-join
> `df_with_nn.pkl` (that moved to consumers in refactor `969819b`). `_merge_parts`
> mirrors `prepare()` exactly, so it omits the nn-merge step too. The
> `nn_output_path` constructor arg was also removed (`a2a52ad`).
**Produces:** `DataPreparer._merge_parts`

---

## Goal

Concatenate the final parts into the whole-window frame, then run the merge-time
global steps (profit labels, NN merge, NN-normalisation) on the full frame and
write the durable outputs. Delete scratch parts on success.

---

## Files

- Modify: `training/data_preparer.py` — add `_merge_parts`
- Test: `tests/training/test_merge_parts.py`

---

## Interface

```python
def _merge_parts(self, final_part_paths: list[str], base_part_paths: list[str]) -> None:
    """Concat final parts (index order) → full frame, then:
      - _compute_profit_labels(full)        (lookahead, on the whole frame)
      - _merge_nn_output(full)              (left-join df_with_nn.pkl if present)
      - data_attributes = _compute_nn_attributes(full)
      - atomic save full → self.output_path
      - data_attributes.save(self.attributes_output_path)
      - delete every final + base part on success
    """
```

Behaviour mirrors `prepare()` steps 7–11, operating on the concatenated frame.

---

## Tests (RED first)

```python
# tests/training/test_merge_parts.py
import os
import pandas as pd
from training.data_preparer import DataPreparer

def test_concat_monotonic_and_labels_present(final_parts, tmp_dataset):
    prep = DataPreparer(config_path=LABELS_CFG, output_path=OUT, attributes_output_path=ATTR)
    prep._merge_parts(final_parts, base_parts=[])
    out = pd.read_pickle(OUT)
    assert out.index.is_monotonic_increasing
    assert any(c.endswith("_profit_label") or "profit" in c for c in out.columns)

def test_parts_deleted_after_save(final_parts, base_parts, tmp_dataset):
    prep = DataPreparer(...)
    prep._merge_parts(final_parts, base_parts)
    assert all(not os.path.exists(p) for p in final_parts + base_parts)
    assert os.path.exists(prep.output_path)
    assert os.path.exists(prep.attributes_output_path)

def test_nn_merge_noop_when_absent(final_parts, tmp_dataset):
    prep = DataPreparer(..., nn_output_path="/nonexistent/df_with_nn.pkl")
    prep._merge_parts(final_parts, base_parts=[])
    assert os.path.exists(prep.output_path)   # no crash
```

Run RED: `pytest tests/training/test_merge_parts.py -v` → FAIL.

---

## Key constraints

- Labels run AFTER concat on the full frame, so lookahead at portion boundaries is
  correct; at the final tail, lookahead beyond `DATA_END` is NaN — identical to
  single-pass.
- Cleanup deletes parts ONLY after both outputs are saved. If the save raises,
  parts remain so a rerun resumes from merge, not from Pass 1.
- Atomic save reuses the existing temp-file + `os.rename` pattern from `prepare()`.
- `base_part_paths` is passed in so cleanup removes both `df_base.part_*` and
  `df_with_indicators.part_*`. Pass `[]` in unit tests that only exercise final
  parts.

---

## Verification

```bash
docker compose run --rm ohlc_gen python3 -c "
import glob, os, pandas as pd
from helpers import data_folder, wide_df_path
finals=sorted(glob.glob(os.path.join(data_folder(),'df_with_indicators.part_*.pkl')))
bases =sorted(glob.glob(os.path.join(data_folder(),'df_base.part_*.pkl')))
from training.data_preparer import DataPreparer
DataPreparer(...)._merge_parts(finals, bases)
assert os.path.exists(wide_df_path()) and not glob.glob(os.path.join(data_folder(),'*.part_*.pkl'))
print('merge + cleanup ok')
"
```

---

## Commit

`feat(data-prep): merge parts with labels/nn-norm and part cleanup`
