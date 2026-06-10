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
- `group: str` — config group name (e.g., `"momentum"`, `"classification"`, `"targets"`); used by `Indicators.compute_group()` to select pass
- `dependencies: list[str]` — field names (not column names) that must be computed before this field; topological sort enforces order
- `resource_dependencies: list[str]` — file paths relative to `STATS_DIR` that must exist on disk before `compute()` can run (e.g., `["rsi_classification.json"]`, `["diff_stats.pkl"]`); empty for base indicator fields
- `applies_to: list[int]` — TFs this field is valid for (`[]` = all CANDLES)
- `params: dict` — field-specific parameters from config
- `compute(data_point: DataPoint, tf: int) -> pd.Series` — reads from `data_point.get_df(tf)`, returns Series to be written as `{tf}_{name}`
- `is_available() -> bool` — returns True if all `resource_dependencies` exist on disk; called by orchestrator before scheduling; default implementation checks `os.path.exists` for each entry

**Dependency resolution semantics:**

| Dep type | Missing means | Resolution |
|---|---|---|
| `dependencies` (field) | Wrong computation order — code bug | `ValueError` at registry load (topological sort fails) |
| `resource_dependencies` (file) | Stats not yet computed — expected at cold start | Field skipped; output column filled with `NaN`; warning logged once per missing path per session |

Resource dep check is done once per `compute_group()` call (not per row). Fields where `is_available()` returns False are excluded from the sorted field list for that call. This means the live path gracefully degrades: classification/target columns are NaN until `DataPreparer` has run and written the stats files.

**Indicators (static orchestrator):**
- `_registry: list[IndicatorField]` — class variable, loaded from config at first use
- `_sorted_fields(tf: int, groups: list[str] = None, check_resources: bool = True) -> list[IndicatorField]` — returns fields applicable to `tf` in dependency order; filters by group if provided; when `check_resources=True` (default) excludes any field where `is_available()` is False
- `compute(data_point: DataPoint, tf: int) -> None` — runs ALL applicable fields; shorthand for `compute_group(..., groups=None)`
- `compute_group(data_point: DataPoint, tf: int, groups: list[str]) -> None` — runs only fields belonging to specified config groups, in dependency order; used by `DataPreparer` to separate base-indicator pass from class-indicator pass

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
- Resource dep check happens once per `compute_group()` — not per row; unavailable fields are silently excluded for that call
- Missing resource dep logs a warning at WARNING level, once per unique path per process lifetime (use a module-level `_warned_resources: set` to suppress repeats)
- `DataPreparer` never relies on graceful-NaN behavior — it controls ordering explicitly and calls `compute_group()` only after required stats are written
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
