# Task 02: DataPreparer

**Phase:** 09 — Training Pipeline  
**Depends on:** Task 01 (Graber), Phase 03 Tasks 02-04 (wide DataFrame builder, indicator fields), Phase 03 Task 07 (DataAttributes)  
**Produces:** `training/data_preparer.py` — multi-pass indicator pipeline producing `df_with_indicators.pkl` + `data_attributes.pkl`

---

## Goal

Implement `DataPreparer` — orchestrates data preparation in dependency order: raw OHLCV → resamples → base indicators → base attributes → class indicators → merge NN output → NN attributes → save outputs.

---

## Context

Data preparation has a strict layer dependency that requires two indicator passes:

```
graber_data.pkl
  └─► resampled_df         (wide multi-TF OHLCV via get_stock_data())
        └─► base_indicators (momentum/trend/volatility/oscillators/volume/
        │                    price_derivatives/trend_flags/nn_features groups)
              └─► base_attributes  (rsi_classification.json, diff_stats.pkl)
                    └─► class_indicators  (classification + targets groups;
                    │                      read base_attributes at compute time)
                          └─► [merge df_with_nn.pkl if exists]
                                └─► nn_attributes  (data_attributes.pkl —
                                │                   NN input feature normalization stats)
                                      └─► df_with_indicators.pkl (plain DataFrame)
                                          data_attributes.pkl (separate file)
```

`classification` and `targets` fields require `rsi_classification.json` and `diff_stats.pkl` — these are produced by `_compute_base_attributes()` from base indicator output, so class indicators cannot run in the same pass as base indicators.

`data_attributes.pkl` holds normalization stats for NN input feature columns. Required by `NNOrchestrator.run_inference()` before NN inference can run.

`df_with_indicators.pkl` is a plain DataFrame (no tuple) — preserves `SimulationData` contract from Phase 03.

---

## Files

- Create: `training/data_preparer.py`

---

## Interface

**`DataPreparer(config_path: str, output_path: str, attributes_output_path: str, nn_output_path: str = "df_with_nn.pkl")`**

Attributes:
- `config_path: str` — path to `indicators_config.yaml`
- `output_path: str` — path for `df_with_indicators.pkl` (plain DataFrame; use `wide_df_path()`)
- `attributes_output_path: str` — path for `data_attributes.pkl` (use `data_attributes_path()`)
- `nn_output_path: str` — path to `df_with_nn.pkl`; checked by `_merge_nn_output()`
- `num_workers: int` — read from `NUM_WORKERS` env var, default 4

**`prepare(raw_data_path: str) -> None`**

Executes the full pipeline in dependency order:

1. `_load_raw_data(raw_data_path)` → base 1-min DataFrame
2. `_build_base_dataframe(raw_df)` → wide multi-TF DataFrame with `{tf}_open/high/low/close/is_closed` columns
3. `_compute_base_indicators(wide_df)` → fills all non-stats-dependent indicator columns in-place
4. `_compute_base_attributes(wide_df)` → derives `rsi_classification.json` + `diff_stats.pkl` from step 3 output; saves to stats files
5. `_compute_class_indicators(wide_df)` → fills classification + target columns (reads stats files written in step 4)
6. `_merge_nn_output(wide_df)` → left-joins `df_with_nn.pkl` columns if file exists; no-op if absent
7. `_compute_nn_attributes(wide_df)` → builds `DataAttributes` normalization stats for NN input feature columns
8. Saves `wide_df` to `output_path` atomically
9. Saves `data_attributes` to `attributes_output_path` via `DataAttributes.save()`

**`_load_raw_data(path: str) -> pd.DataFrame`**
- Loads `graber_data.pkl`, validates columns (`open_time, o, h, l, c, v`), sets `open_time` as index

**`_build_base_dataframe(raw_df: pd.DataFrame) -> pd.DataFrame`**
- Calls `get_stock_data()` (Phase 03 Task 02) to produce wide multi-TF DataFrame

**`_compute_base_indicators(df: pd.DataFrame) -> None`**
- Calls `Indicators.compute_group(data_point, tf, groups=BASE_GROUPS)` per TF per row
- `BASE_GROUPS = ["momentum", "trend", "volatility", "oscillators", "volume", "price_derivatives", "trend_flags", "nn_features"]`
- Worker parallelism: TF groups distributed across `num_workers` processes

**`_compute_base_attributes(df: pd.DataFrame) -> None`**
- Instantiates `DataAttributes`, calls `data_attributes.compute(df)`
- Writes `rsi_classification.json` + `diff_stats.pkl` to stats files (idempotent — skips if already current)

**`_compute_class_indicators(df: pd.DataFrame) -> None`**
- Calls `Indicators.compute_group(data_point, tf, groups=CLASS_GROUPS)` per TF per row
- `CLASS_GROUPS = ["classification", "targets"]`
- Applies only to TFs `[15, 60, 240, 1440]` — skipped for `tf=1` and `tf=5`
- Worker parallelism same as base pass

**`_merge_nn_output(df: pd.DataFrame) -> None`**
- If `nn_output_path` exists: loads it, left-joins its columns into `df` on index — NaN for timestamps not covered
- If absent: no-op

**`_compute_nn_attributes(df: pd.DataFrame) -> DataAttributes`**
- Instantiates `DataAttributes`
- Reads `feature_cols` from `indicators_config.yaml` (NN input feature column list)
- Calls `data_attributes.compute_nn_stats(df, feature_cols)` — mean/std over closed-candle rows only
- Returns populated `DataAttributes`

---

## Key Constraints

- **Two-pass indicator requirement**: base indicators MUST complete before `_compute_base_attributes()` runs; class indicators MUST NOT run before base attributes are saved — enforced by sequential steps in `prepare()`
- Raw data must cover at least `max(indicator_lookback)` rows before first valid indicator row
- Indicator columns populated at EVERY 1-min row — each pass calls `build_indicator_input(df, ts, tf)` per row, appending partial candle row; result written back for all timestamps
- Atomic save: `df` pickled to `output_path + ".tmp"` then renamed; `data_attributes` saved via `DataAttributes.save(attributes_output_path)` with same `.tmp` → rename pattern
- `num_workers` applies to both indicator passes — attribute and NN attribute computation runs single-threaded
- `df_with_indicators.pkl` is always a plain DataFrame — never a tuple

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from training.data_preparer import DataPreparer
from helpers import wide_df_path, data_attributes_path, graber_data_path
import os

dp = DataPreparer(
    config_path='config/indicators_config.yaml',
    output_path=wide_df_path(),
    attributes_output_path=data_attributes_path(),
    nn_output_path='/tmp/nn_not_present.pkl',
)
print('data_preparer ok')
"
```

---

## Commit

`feat: implement DataPreparer with two-pass indicator pipeline (base → attributes → class → nn_attributes)`
