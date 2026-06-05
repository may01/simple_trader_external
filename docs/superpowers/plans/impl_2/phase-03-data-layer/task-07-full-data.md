# Task 07: FullData + DataAttributes

**Phase:** 03 — Data Layer  
**Depends on:** Task 06 (SimulationData), Task 04 (indicator fields)  
**Produces:** `data.py` — `FullData` class; `indicators.py` — `DataAttributes` class

---

## Goal

Implement `FullData` (read interface over wide DataFrame exposing per-TF closed-candle views) and `DataAttributes` (manages stats files: `rsi_classification.json`, `diff_stats.pkl`).

---

## Context

`FullData` is used by visualization, NN training, and strategy research — NOT by the live or simulation trading loops. It filters `df_with_indicators.pkl` to expose only `{tf}_is_closed=True` rows for each TF. `DataAttributes` generates and caches the stats files needed by `MoveClassField` and target fields.

---

## Files

- Modify: `data.py` (add `FullData`)
- Modify: `indicators.py` (add `DataAttributes`)

---

## Interface — FullData

- `__init__(df: pd.DataFrame)` — wraps `df_with_indicators.pkl` DataFrame
- `get(tf: int) -> pd.DataFrame` — returns all `{tf}_is_closed=True` rows, only `{tf}_*` columns; one row per completed candle, indexed at close minute
- `get_candle(tf: int, open_time: pd.Timestamp) -> pd.Series` — returns single closed-candle row for candle that opened at `open_time`

---

## FullData Column Filtering

`get(tf=5)` returns:
- Rows where `df["5_is_closed"] == True`
- Columns: only those starting with `"5_"` (e.g., `5_open`, `5_high`, `5_rsi_14`, `5_trend_up`, etc.)
- Index: 1-min timestamp at which the candle closed (e.g., `09:04` for the `09:00` 5-min candle)

---

## Interface — DataAttributes

- `compute(df: pd.DataFrame) -> None` — computes and saves all stats files if absent
- `_compute_rsi_classification(df: pd.DataFrame) -> None` — for each TF in `[15, 60, 240, 1440]`, computes mean and std of `{tf}_rsi_ma8` over all closed candles; saves to `stats/rsi_classification.json`
- `_compute_diff_stats(df: pd.DataFrame) -> None` — computes price differential stats per move class; saves to `stats/diff_stats.pkl`
- `load_rsi_classification() -> dict` — loads existing JSON; raises if absent
- `load_diff_stats() -> dict` — loads existing pkl; raises if absent

---

## Stats File Formats

**rsi_classification.json:**
```json
{
  "15": {"mean": 52.3, "std": 14.1},
  "60": {"mean": 50.8, "std": 15.2},
  ...
}
```

**diff_stats.pkl:** `dict[str, dict]` mapping move class names to mean/std price differential statistics. Used by `TgtLongField`, `TgtShortField`, `SLLongField`, `SLShortField`.

---

## Key Constraints

- `FullData` returns only `{tf}_is_closed=True` rows — NO partial-candle rows, ever
- `FullData.get(tf)` returns only `{tf}_*` columns — strips all other TF columns
- `DataAttributes.compute()` skips computation if files already exist (idempotent)
- Stats files are static per pair — changing them invalidates all cached indicator values
- `DataAttributes` is only called by `DataPreparer` during `generate_full_ohlc` — never in live path
- Forward-looking target columns (`tgt_long`, `tgt_short`) must ONLY appear in `FullData` output — never in `LiveDataPoint`

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
import os
os.environ['PAIR'] = 'link_usdt'; os.environ['ROOT_FOLDER'] = 'local'
import pandas as pd
from helpers import wide_df_path
from data import FullData

df = pd.read_pickle(wide_df_path())
full = FullData(df)

df_5m = full.get(tf=5)
assert all(df_5m.index.map(lambda ts: ts.minute % 5 == 4))  # all close at minute 4, 9, 14...
assert all(c.startswith('5_') for c in df_5m.columns)
print('FullData ok, 5m candles:', len(df_5m))
"
```

---

## Commit

`feat: implement FullData read interface and DataAttributes stats computation`
