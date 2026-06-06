# Task 03: IndicatorField Framework + Indicators Orchestrator

**Phase:** 03 — Data Layer  
**Depends on:** Task 02 (wide DataFrame), Task 03 Phase 00 (indicators_config.yaml)  
**Produces:** `indicators.py` — `IndicatorField` base class, `Indicators` orchestrator, `build_indicator_input()`

---

## Goal

Implement the `IndicatorField` plugin pattern and `Indicators.compute()` orchestrator. The framework loads the field registry from `indicators_config.yaml` at startup and runs all fields in dependency order against any DataPoint.

---

## Context

All enrichment logic lives in `IndicatorField` subclasses — never in `LiveData` or `DataPreparer`. `Indicators.compute(data_point, tf)` iterates the sorted field registry, calls each field's `compute()`, and writes results back via `data_point.get_df(tf)`. This runs both in the live path (per-tick, per-TF) and the simulation path (per-minute, all TFs).

---

## Files

- Create: `indicators.py`

---

## Interface

**IndicatorField (abstract base):**
- `name: str` — output column suffix (e.g., `"rsi_14"`) — output column becomes `{tf}_{name}`
- `dependencies: list[str]` — names of other fields that must be computed first
- `applies_to: list[int]` — TFs this field is valid for (`[]` = all CANDLES)
- `params: dict` — field-specific parameters from config
- `compute(data_point: DataPoint, tf: int) -> pd.Series` — reads from `data_point.get_df(tf)`, returns Series to be written as `{tf}_{name}`

**Indicators (static orchestrator):**
- `_registry: list[IndicatorField]` — class variable, loaded from config at first use
- `_sorted_fields(tf: int) -> list[IndicatorField]` — returns fields applicable to `tf` in dependency order
- `compute(data_point: DataPoint, tf: int) -> None` — runs all applicable fields in order, writes each result back via `data_point.get_df(tf)[f"{tf}_{field.name}"] = series`

**build_indicator_input(df: pd.DataFrame, ts: pd.Timestamp, tf: int) -> pd.DataFrame:**
- Returns the indicator input series at timestamp `ts` for timeframe `tf`
- Logic:
  - `subset = df[:ts]`
  - `closed = subset[subset[f"{tf}_is_closed"]]` — one row per completed candle
  - If current row is NOT a close: append `subset.iloc[[-1]]` as partial candle row
  - Return `tail(105)` of the result
- Used by simulation path in `DataPreparer` and by `WideDataPoint.get_df(tf)`

---

## Key Constraints

- `Indicators.compute()` writes ONLY to `data_point.get_df(tf)` — never modifies the wide DataFrame directly
- `IndicatorField.compute()` reads ONLY from `data_point.get_df(tf)` — never calls `data_point.get()` (that's for signals)
- Dependency order enforced: field `rsi_ma8` (depends on `rsi_14`) must come after `rsi_14` in sorted order
- Circular dependencies in config must be detected at load time and raise `ValueError`
- `applies_to: all` in config expands to full `CANDLES` list
- `classification` and `targets` group fields apply to `[15, 60, 240, 1440]` only — must not be computed for `tf=1` or `tf=5`
- `NN feature` fields use `{tf}_close_diff_atr_ma` etc. from already-computed base columns
- `build_indicator_input` — the partial candle row uses the CURRENT 1-min close, not the TF-period close

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from indicators import Indicators, build_indicator_input
from data import WideDataPoint, get_stock_data
import pandas as pd, os

os.environ['PAIR'] = 'link_usdt'
os.environ['ROOT_FOLDER'] = 'short'
df = get_stock_data('link_usdt')

# Test build_indicator_input at a boundary
ts = df[df['5_is_closed']].index[20]
inp = build_indicator_input(df, ts, 5)
assert inp.iloc[-1]['5_is_closed'] == True
assert len(inp) <= 105
print('indicator framework ok, input rows:', len(inp))
"
```

---

## Commit

`feat: implement IndicatorField framework + Indicators.compute() orchestrator`
