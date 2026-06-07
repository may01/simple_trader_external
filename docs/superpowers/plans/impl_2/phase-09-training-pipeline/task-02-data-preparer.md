# Task 02: DataPreparer

**Phase:** 09 — Training Pipeline  
**Depends on:** Task 01 (Graber), Phase 03 Tasks 02-04 (wide DataFrame builder, indicator fields), Phase 03 Task 07 (FullData/DataAttributes)  
**Produces:** `training/data_preparer.py` — indicator computation pipeline producing `df_with_indicators.pkl`

---

## Goal

Implement `DataPreparer` — orchestrates the full data preparation pipeline: load raw OHLCV → build wide DataFrame → compute all indicators → save `df_with_indicators.pkl`.

---

## Context

`df_with_indicators.pkl` is the input to simulation (`SimulationData`) and NN training. `DataPreparer` runs once per training cycle. Heavy computation (indicator fields) is parallelized across TF groups. Output is a single wide DataFrame with all `{tf}_{col}` columns populated. `DataAttributes` stats (mean/std per NN feature column) also computed here.

---

## Files

- Create: `training/data_preparer.py`

---

## Interface

**`DataPreparer(config_path: str, output_path: str, nn_output_path: str = "df_with_nn.pkl")`**

Attributes:
- `config_path: str` — path to `indicators_config.yaml`
- `output_path: str` — path for output `df_with_indicators.pkl`
- `nn_output_path: str` — path to `df_with_nn.pkl`; checked by `_merge_nn_output()`
- `num_workers: int` — read from `NUM_WORKERS` env var, default 4

**`prepare(raw_data_path: str) -> None`**
- Calls `_load_raw_data(raw_data_path)` → base 1-min DataFrame
- Calls `_build_base_dataframe(raw_df)` → wide DataFrame with TF structure
- Calls `_compute_indicators(wide_df)` → fills all `{tf}_{col}` indicator columns
- Calls `_merge_nn_output(wide_df)` → left-joins `df_with_nn.pkl` columns if file exists
- Calls `_compute_attributes(wide_df)` → builds `DataAttributes` normalization stats
- Saves `(wide_df, data_attributes)` to `output_path` atomically

**`_load_raw_data(path: str) -> pd.DataFrame`**
- Loads `graber_data.pkl`, validates columns, sets `open_time` as index

**`_build_base_dataframe(raw_df: pd.DataFrame) -> pd.DataFrame`**
- Calls `get_stock_data()` (Phase 03 Task 02) to produce wide multi-TF DataFrame

**`_compute_indicators(df: pd.DataFrame) -> pd.DataFrame`**
- Instantiates `Indicators` (Phase 03 Task 03) from config
- Runs `indicators.compute(df)` — fills all indicator columns in-place
- Worker parallelism: TF groups distributed across `num_workers` processes

**`_merge_nn_output(df: pd.DataFrame) -> None`**
- Checks if `df_with_nn.pkl` exists at configured path
- If present: loads it, left-joins its columns into `df` on index — NaN for timestamps not covered
- If absent: no-op — `df` unchanged

**`_compute_attributes(df: pd.DataFrame) -> DataAttributes`**
- Instantiates `DataAttributes`
- Reads `feature_cols` from `indicators_config.yaml` (NN feature column list)
- Calls `data_attributes.compute_nn_stats(df, feature_cols)` — stats computed only for those columns
- Returns populated `DataAttributes`

---

## Key Constraints

- Raw data must cover at least `max(indicator_lookback)` rows before first valid indicator row
- Indicator columns populated at EVERY 1-min row — `_compute_indicators()` calls `build_indicator_input(df, ts, tf)` per row, which includes the partial candle row appended after closed-candle history; result written back for all timestamps, no NaN at non-closed rows
- Atomic save: pickle `(df, data_attributes)` tuple to `.tmp`, then rename
- `num_workers` applies to indicator computation only — target and attribute computation runs single-threaded

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from training.data_preparer import DataPreparer
import os

dp = DataPreparer(
    config_path='config/indicators_config.yaml',
    output_path='/tmp/test_indicators.pkl',
    num_workers=1
)
print('data_preparer ok')
"
```

---

## Commit

`feat: implement DataPreparer orchestrating indicator computation and DataFrame preparation`
