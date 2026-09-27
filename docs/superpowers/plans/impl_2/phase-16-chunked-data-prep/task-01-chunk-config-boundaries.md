# Task 01: Chunk config, boundaries, and part-file paths

**Phase:** 16 — Chunked Data Prep
**Depends on:** existing `config_loader`, `helpers.dataset_folder/data_folder`, `config_loader.warmup_start_ms`
**Produces:** `config_loader.chunk_config()`, and module helpers in `training/data_preparer.py`: `_window_row_count`, `_chunk_boundaries`, `_base_part_path`, `_final_part_path`

---

## Goal

The pure, side-effect-free foundation: read chunk config from env, compute
portion boundaries deterministically, and name part files. Everything here is
unit-testable with no I/O.

---

## Files

- Modify: `config_loader.py` — add `chunk_config()`
- Modify: `training/data_preparer.py` — add module-level `_window_row_count`, `_chunk_boundaries`, `_base_part_path`, `_final_part_path`
- Test: `tests/training/test_chunk_boundaries.py`

---

## Interface

```python
# config_loader.py
def chunk_config() -> tuple[int, int]:
    """Return (chunk_span_days, chunk_min_rows) from env.

    CHUNK_SPAN_DAYS  default 30
    CHUNK_MIN_ROWS   default 200000   (≈140 days of 1-min rows)
    """

# training/data_preparer.py  (module-level, private)
def _window_row_count(start_ms: int, end_ms: int) -> int:
    """1-min rows in [start_ms, end_ms): (end_ms - start_ms) // 60_000."""

def _chunk_boundaries(start_ms: int, end_ms: int, span_days: int) -> list[tuple[int, int]]:
    """Contiguous [start, end) portions of span_days each, last clamped to end_ms.
    A window <= one span returns a single (start_ms, end_ms). Returns [] when
    start_ms >= end_ms."""

def _base_part_path(index: int) -> str:
    """{data_folder()}df_base.part_NN.pkl  (NN = zero-padded 2-digit index)."""

def _final_part_path(index: int) -> str:
    """wide_df_path() with .pkl → .part_NN.pkl (df_with_indicators.part_NN.pkl)."""
```

`span_days` is converted to ms as `span_days * 86_400_000`.

---

## Tests (RED first)

```python
# tests/training/test_chunk_boundaries.py
import os
import pytest
from config_loader import chunk_config
from training.data_preparer import (
    _window_row_count, _chunk_boundaries, _base_part_path, _final_part_path,
)

DAY = 86_400_000

def test_chunk_config_defaults(monkeypatch):
    monkeypatch.delenv("CHUNK_SPAN_DAYS", raising=False)
    monkeypatch.delenv("CHUNK_MIN_ROWS", raising=False)
    assert chunk_config() == (30, 200000)

def test_chunk_config_env_override(monkeypatch):
    monkeypatch.setenv("CHUNK_SPAN_DAYS", "3")
    monkeypatch.setenv("CHUNK_MIN_ROWS", "0")
    assert chunk_config() == (3, 0)

def test_window_row_count():
    assert _window_row_count(0, 14 * DAY) == 14 * 1440

def test_boundaries_split_14d_span3():
    b = _chunk_boundaries(0, 14 * DAY, 3)
    assert b == [(0, 3*DAY), (3*DAY, 6*DAY), (6*DAY, 9*DAY),
                 (9*DAY, 12*DAY), (12*DAY, 14*DAY)]   # last clamped

def test_boundaries_single_when_below_span():
    assert _chunk_boundaries(0, 14 * DAY, 30) == [(0, 14 * DAY)]

def test_boundaries_empty_window():
    assert _chunk_boundaries(5 * DAY, 5 * DAY, 3) == []

def test_part_paths_zero_padded():
    assert _base_part_path(7).endswith("df_base.part_07.pkl")
    assert _final_part_path(7).endswith("df_with_indicators.part_07.pkl")
    assert _final_part_path(0).endswith("df_with_indicators.part_00.pkl")
```

Run RED: `pytest tests/training/test_chunk_boundaries.py -v` → FAIL (functions
not defined).

---

## Key constraints

- `_chunk_boundaries` is the single source of truth for portion identity; a part
  file's existence at `index` means "portion `index` done". Boundaries MUST be a
  pure function of `(start_ms, end_ms, span_days)` — no env reads inside it.
- Zero-pad part indices to 2 digits (`part_00`..`part_99`); a dataset never
  exceeds ~49 portions at the default span, but pad uniformly for sort-stable
  globbing. If >99 portions are ever possible, widen here only.
- `_base_part_path` lives beside `graber_data.pkl` in `data_folder()`;
  `_final_part_path` is derived from `wide_df_path()` so it tracks the dataset
  folder automatically.

---

## Verification

```bash
docker compose run --rm ohlc_gen python3 -c "
from training.data_preparer import _chunk_boundaries
DAY=86_400_000
assert _chunk_boundaries(0, 14*DAY, 3)[-1] == (12*DAY, 14*DAY)
assert _chunk_boundaries(0, 14*DAY, 30) == [(0, 14*DAY)]
print('boundaries ok')
"
```

---

## Commit

`feat(data-prep): chunk config, deterministic portion boundaries, part paths`
