# Task 03: Pass-1 base-indicator portion worker

**Phase:** 16 — Chunked Data Prep
**Depends on:** Task 01 (`_base_part_path`, `_chunk_boundaries`), existing `_build_base_dataframe`, `_compute_base_indicators`, `config_loader.warmup_start_ms`, `CANDLES`
**Produces:** `DataPreparer._pass1_base_portion`

---

## Goal

Compute base indicators for ONE time portion and persist only its owned rows to a
base part file. This is the expensive, resumable unit. Lookback comes from the
shared raw frame (earlier rows of `graber_data.pkl`), so portions share grabbed
data without re-grabbing.

---

## Files

- Modify: `training/data_preparer.py` — add `_pass1_base_portion`
- Test: `tests/training/test_pass1_base_portion.py`

---

## Interface

```python
def _pass1_base_portion(self, raw_df: pd.DataFrame, index: int,
                        window: tuple[int, int]) -> str:
    """Compute base indicators for owned window [w0, w1) and save owned rows to
    _base_part_path(index) atomically.

    Returns the part path. If the part already exists, returns immediately
    WITHOUT recomputing (resume).

    raw_df:  the full shared raw frame (loaded once by the orchestrator from
             graber_data.pkl, already renamed to standard column names).
    window:  (w0_ms, w1_ms) owned range; lookback is taken from raw_df rows
             >= warmup_start_ms(w0) so per-row slices are full.
    """
```

Behaviour:
1. If `os.path.exists(_base_part_path(index))` → return it (skip).
2. `lookback_start = warmup_start_ms(w0)`. Slice raw_df to
   `[lookback_start, w1)` (ms → Timestamp comparison on the index).
3. `wide_df = self._build_base_dataframe(raw_slice)`.
4. `self._compute_base_indicators(wide_df, start_ts=Timestamp(w0))`.
5. `owned = wide_df.loc[(wide_df.index >= w0) & (wide_df.index < w1)]`.
6. Atomic save `owned` to `_base_part_path(index)` (temp + `os.rename`).

---

## Tests (RED first)

```python
# tests/training/test_pass1_base_portion.py
import os
import pandas as pd
from training.data_preparer import DataPreparer, _base_part_path

# fixture: small synthetic 1-min OHLCV raw_df spanning ~6 days (helper in conftest)

def test_base_part_has_owned_window_only(synthetic_raw_df, tmp_dataset):
    prep = DataPreparer(config_path=..., output_path=..., attributes_output_path=...)
    DAY = 86_400_000
    path = prep._pass1_base_portion(synthetic_raw_df, index=1, window=(3*DAY, 4*DAY))
    part = pd.read_pickle(path)
    assert part.index.min() >= pd.Timestamp(3*DAY, unit="ms", tz="UTC")
    assert part.index.max() <  pd.Timestamp(4*DAY, unit="ms", tz="UTC")

def test_base_columns_nonnan_using_lookback(synthetic_raw_df, tmp_dataset):
    # a non-first portion's first owned row must be NaN-free because lookback feeds it
    prep = DataPreparer(...)
    DAY = 86_400_000
    path = prep._pass1_base_portion(synthetic_raw_df, index=2, window=(4*DAY, 5*DAY))
    part = pd.read_pickle(path)
    assert not part.iloc[0]["15_rsi_14"] != part.iloc[0]["15_rsi_14"]  # not NaN

def test_skip_if_exists(synthetic_raw_df, tmp_dataset):
    prep = DataPreparer(...)
    DAY = 86_400_000
    path = prep._pass1_base_portion(synthetic_raw_df, 1, (3*DAY, 4*DAY))
    mtime = os.path.getmtime(path)
    again = prep._pass1_base_portion(synthetic_raw_df, 1, (3*DAY, 4*DAY))
    assert again == path and os.path.getmtime(path) == mtime  # not rewritten
```

Run RED: `pytest tests/training/test_pass1_base_portion.py -v` → FAIL.

> Note: tests reuse the existing data-prep test fixtures (synthetic raw frame +
> tmp dataset folder). Mirror the setup already used by the current
> `DataPreparer` tests rather than inventing new scaffolding.

---

## Key constraints

- Read-only on `raw_df` — never mutate the shared frame (the orchestrator reuses
  it across all portions).
- `start_ts = w0` ensures only owned rows get indicator values; lookback rows are
  computed-as-NaN and excluded by the `.loc` owned slice anyway — matches the
  single-pass `start_ts` semantics exactly.
- Atomic save: write `_base_part_path(index) + ".tmp"`, then `os.rename`. A crash
  mid-write leaves the `.tmp`, never a half-written part.
- Do NOT compute attributes/class indicators here — base groups only
  (`_compute_base_indicators` uses `BASE_GROUPS`).

---

## Verification

```bash
docker compose run --rm ohlc_gen python3 -c "
# smoke: one portion over the already-grabbed 2-week dataset
import os, pandas as pd
from training.data_preparer import DataPreparer
from training.trainer import _nn_output_path  # path helpers per existing wiring
# (use the same construction _run_prepare_data uses; assert a base part appears)
print('pass1 portion smoke ok')
"
```

---

## Commit

`feat(data-prep): pass-1 base-indicator portion worker with skip-if-exists`
