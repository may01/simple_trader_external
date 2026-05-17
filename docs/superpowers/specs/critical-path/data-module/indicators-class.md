# Indicators Class Specification

**Version:** 2.0 — Registry-based IndicatorField architecture; config-driven; dual-library
**Supersedes:** Version 1.0 (single `calc(df)` monolith)
**File:** `indicators.py`
**Category:** Data Module — Technical Indicator Computation

---

## 1. Class Overview

`Indicators` is a **registry-based computation engine** for all enrichment applied to OHLC DataFrames. Every computed column — technical indicators, price derivatives, RSI classifications, trade targets, trend flags, and NN features — is a separate `IndicatorField` implementation registered in `indicators_config.yaml`.

**Core design change from v1:**
- v1: monolithic `calc(df)` method with 30+ hardcoded TA-Lib calls
- v2: each field is an `IndicatorField` subclass loaded from config; `Indicators.compute(data_point, tf)` runs them in dependency order

**Key properties:**
- **Config-driven:** No field names or parameters hardcoded in Python — all declared in `indicators_config.yaml`
- **Dependency-ordered:** Fields specify `dependencies`; `Indicators` topologically sorts before running
- **Path-aware:** Live path uses TA-Lib; simulation path uses `pandas_ta` via `WideDataPoint.get_df(tf)`
- **DataPoint-coupled:** Reads input and writes results through `DataPoint.get_df(tf)`, not raw DataFrames
- **Per-timeframe:** `compute()` is called once per `tf`; fields declare which timeframes they apply to

**Responsibilities (moved out of v1):**
- `calc_strategy()`, `calc_strategy_margin()` — removed; belong in Strategy module
- `get_markers()` — removed; belongs in Visualization module
- `select()` — removed (was a stub)

---

## 2. IndicatorField Base Class

Every computed column is one `IndicatorField` subclass.

```python
class IndicatorField:
    name: str                 # output column suffix; written as f"{tf}_{name}"
    dependencies: list[str]   # field names that must be computed before this one
    applies_to: list[int]     # timeframes this field is valid for; [] means all CANDLES

    def compute(self, data_point: DataPoint, tf: int) -> pd.Series:
        """
        Reads input columns from data_point.get_df(tf).
        Returns a Series written back as f"{tf}_{self.name}".
        """
        df = data_point.get_df(tf)
        ...
```

### Column writing convention

`Indicators.compute()` writes each result as:
```python
data_point.get_df(tf)[f"{tf}_{field.name}"] = series
```

| `field.name` | Written column | Example |
|---|---|---|
| `rsi_14` | `{tf}_rsi_14` | `5_rsi_14` |
| `ema_25` | `{tf}_ema_25` | `15_ema_25` |
| `move_class` | `{tf}_move_class` | `60_move_class` |
| `tgt_long` | `{tf}_tgt_long` | `60_tgt_long` |

The live-path `ohlc[tf]` DataFrames use **unprefixed** names (`"rsi_14"`, `"close"`) because the timeframe is implicit; `LiveDataPoint.get("rsi_14", tf=5)` looks up `ohlc[5]["rsi_14"]`. The wide DataFrame and all simulation-path code use the prefixed form.

---

## 3. Indicators Class

### 3.1 Class structure

```python
class Indicators:
    _registry: list[IndicatorField] = []  # loaded from indicators_config.yaml at startup

    @classmethod
    def load_registry(cls, config_path: str) -> None:
        """Load field definitions from indicators_config.yaml. Fatal if missing."""
        ...

    @staticmethod
    def _sorted_fields(tf: int) -> list[IndicatorField]:
        """Return fields applicable to tf, in topological dependency order."""
        ...

    @staticmethod
    def compute(data_point: DataPoint, tf: int) -> None:
        """
        Run all active IndicatorFields for tf, in dependency order.
        Results written into data_point.get_df(tf) via DataPoint protocol.
        """
        for field in Indicators._sorted_fields(tf):
            series = field.compute(data_point, tf)
            data_point.get_df(tf)[f"{tf}_{field.name}"] = series
```

### 3.2 `compute(data_point, tf)` — primary entry point

**Signature:**
```python
@staticmethod
def compute(data_point: DataPoint, tf: int) -> None
```

**Parameters:**
- `data_point` — `LiveDataPoint` (live path) or `WideDataPoint` (simulation path)
- `tf` — timeframe in minutes (must be in `CANDLES`)

**Behavior:**
1. Calls `_sorted_fields(tf)` to get the applicable field list in dependency order
2. For each field: calls `field.compute(data_point, tf)`, writes result to `data_point.get_df(tf)[f"{tf}_{field.name}"]`
3. After each field write, applies `bfill()` on the new column to handle leading NaN from indicator warm-up

**Called from:**
- `LiveData.build_candles(time_point)` — once per `tf` after fetching from Binance
- Wide data generation (`trainer.py RUN_TYPE=generate_full_ohlc`) — once per `(ts, tf)` where `{tf}_is_closed=True`

**Preconditions:**
- `indicators_config.yaml` loaded via `load_registry()` at startup (fatal if absent)
- `data_point.get_df(tf)` returns a DataFrame with at least `open`, `high`, `low`, `close`, `volume` columns

**Error handling:**
- Field-level exception → logs and marks column as NaN; does not halt other fields
- Missing `indicators_config.yaml` → fatal at startup; no fallback

### 3.3 `load_registry(config_path)` — startup initialization

```python
@classmethod
def load_registry(cls, config_path: str) -> None
```

- Parses `indicators_config.yaml`
- Instantiates one `IndicatorField` subclass per entry
- Validates that all `dependencies` reference known field names
- Raises `ConfigError` on parse failure (fatal — no partial loading)
- Called once at process startup before any `compute()` calls

---

## 4. Configuration — `indicators_config.yaml`

All field definitions live in this file. No field names or parameters are hardcoded in Python.

```yaml
# indicators_config.yaml (excerpt)
fields:
  - name: rsi_14
    group: momentum
    class: TalibField        # implementation class; uses talib.abstract on live path
    applies_to: []           # [] = all CANDLES
    params: {function: RSI, timeperiod: 14}

  - name: rsi_ma8
    group: momentum
    class: EmaOfField
    applies_to: []
    depends_on: [rsi_14]
    params: {source: rsi_14, length: 8}

  - name: rsi_ma8_diff
    group: momentum
    class: DiffField
    applies_to: []
    depends_on: [rsi_ma8]
    params: {source: rsi_ma8}

  - name: move_class
    group: classification
    class: MoveClassField
    applies_to: [15, 60, 240, 1440]
    depends_on: [rsi_ma8, rsi_ma8_diff]
    params: {stats_source: rsi_classification}

  - name: tgt_long
    group: targets
    class: TargetField
    applies_to: [15, 60, 240, 1440]
    depends_on: [move_class, zone_class, close_diff_prc_rm_mean_below]
    params: {stats_source: diff_stats, direction: long, side: target}
```

**To add a new indicator:** create an `IndicatorField` subclass and add one entry to `indicators_config.yaml`. No changes to `Indicators` itself.

---

## 5. IndicatorField Groups

The table below describes the field groups registered by the default config. Full parameter details are in `indicators_config.yaml`.

### 5.1 Momentum

| Field name | Output column | Applies to | Depends on | Notes |
|---|---|---|---|---|
| `rsi_14` | `{tf}_rsi_14` | all | — | RSI-14 via TA-Lib / pandas_ta |
| `rsi_ma6` | `{tf}_rsi_ma6` | all | `rsi_14` | EMA-6 of RSI |
| `rsi_ma8` | `{tf}_rsi_ma8` | all | `rsi_14` | EMA-8 of RSI |
| `rsi_ma12` | `{tf}_rsi_ma12` | all | `rsi_14` | EMA-12 of RSI |
| `rsi_ma24` | `{tf}_rsi_ma24` | all | `rsi_14` | EMA-24 of RSI |
| `rsi_ma6_diff` | `{tf}_rsi_ma6_diff` | all | `rsi_ma6` | diff() of rsi_ma6 |
| `rsi_ma8_diff` | `{tf}_rsi_ma8_diff` | all | `rsi_ma8` | diff() of rsi_ma8; input to move_class |
| `rsi_ma12_diff` | `{tf}_rsi_ma12_diff` | all | `rsi_ma12` | diff() of rsi_ma12 |

### 5.2 Trend

| Field name | Output column | Applies to | Notes |
|---|---|---|---|
| `ema_7` | `{tf}_ema_7` | all | |
| `ema_14` | `{tf}_ema_14` | all | |
| `ema_25` | `{tf}_ema_25` | all | Used in trend_up / trend_down |
| `ema_50` | `{tf}_ema_50` | all | Used in trend_up / trend_down |
| `ema_100` | `{tf}_ema_100` | all | Used in trend_up / trend_down |
| `macd` | `{tf}_macd` | all | MACD line; fast=12, slow=26 |
| `macd_signal` | `{tf}_macd_signal` | all | Signal line; signal=9 |
| `macd_hist` | `{tf}_macd_hist` | all | MACD − signal |
| `macd_fast` | `{tf}_macd_fast` | all | Fast MACD variant |
| `macd_fast_signal` | `{tf}_macd_fast_signal` | all | Fast MACD signal |
| `trend_up` | `{tf}_trend_up` | all | `ema_25 > ema_50 > ema_100` |
| `trend_down` | `{tf}_trend_down` | all | `ema_25 < ema_50 < ema_100` |

### 5.3 Volatility

| Field name | Output column | Applies to | Notes |
|---|---|---|---|
| `atr_14` | `{tf}_atr_14` | all | ATR-14 |
| `natr_14` | `{tf}_natr_14` | all | Normalized ATR |
| `atr_ma` | `{tf}_atr_ma` | all | EMA-5 of ATR |
| `natr_ma` | `{tf}_natr_ma` | all | EMA-5 of NATR |
| `bb_upper` | `{tf}_bb_upper` | all | BB upper; period=20, 2σ |
| `bb_middle` | `{tf}_bb_middle` | all | BB middle (SMA-20) |
| `bb_lower` | `{tf}_bb_lower` | all | BB lower; period=20, 2σ |
| `bb_fast_upper` | `{tf}_bb_fast_upper` | all | Faster BB variant |
| `bb_fast_lower` | `{tf}_bb_fast_lower` | all | Faster BB variant |
| `bb_wide_upper` | `{tf}_bb_wide_upper` | all | Wider BB variant |
| `bb_wide_lower` | `{tf}_bb_wide_lower` | all | Wider BB variant |

### 5.4 Oscillators

| Field name | Output column | Applies to | Notes |
|---|---|---|---|
| `cci_14` | `{tf}_cci_14` | all | CCI-14 |
| `cci_ma` | `{tf}_cci_ma` | all | EMA of CCI |
| `sar` | `{tf}_sar` | all | Parabolic SAR; acc=0.09, max=0.21 |

### 5.5 Volume

| Field name | Output column | Applies to | Notes |
|---|---|---|---|
| `vol_ma` | `{tf}_vol_ma` | all | EMA-12 of volume |
| `vol_buy_ma` | `{tf}_vol_buy_ma` | all | EMA of taker buy volume |
| `vol_sell_ma` | `{tf}_vol_sell_ma` | all | EMA of taker sell volume (= volume − buy_volume) |

### 5.6 Price Derivatives

Computed for each price type: `close`, `high`, `low` (9 fields total, shown for `close`):

| Field name | Output column | Applies to | Computation |
|---|---|---|---|
| `close_diff_prc` | `{tf}_close_diff_prc` | all | `close.diff() / close.shift(1)` — % candle-to-candle change |
| `close_diff_prc_rm` | `{tf}_close_diff_prc_rm` | all | `close_diff_prc.rolling(6).mean()` |
| `close_diff_prc_rm_mean_above` | `{tf}_close_diff_prc_rm_mean_above` | all | mean of `(diff − rm)` where positive; per-class from diff_stats |
| `close_diff_prc_rm_mean_below` | `{tf}_close_diff_prc_rm_mean_below` | all | mean of `(diff − rm)` where negative; per-class from diff_stats |

Equivalent fields exist for `high_*` and `low_*` prefixes.

### 5.7 Classification

| Field name | Output column | Applies to | Depends on |
|---|---|---|---|
| `over_low` | `{tf}_over_low` | {15, 60, 240, 1440} | `low_diff_prc`, `low_diff_prc_rm`, `low_diff_prc_rm_mean` |
| `over_high` | `{tf}_over_high` | {15, 60, 240, 1440} | `high_diff_prc`, `high_diff_prc_rm`, `high_diff_prc_rm_mean` |
| `move_class` | `{tf}_move_class` | {15, 60, 240, 1440} | `rsi_ma8_diff`; thresholds from `rsi_classification` |
| `zone_class` | `{tf}_zone_class` | {15, 60, 240, 1440} | `rsi_ma8`; thresholds from `rsi_classification` |
| `{tf}_class` | `{tf}_{tf}_class` | {15, 60, 240, 1440} | `move_class + zone_class`; overridden by over_low/over_high |

**Classification tiers** (5 levels each):

| move_class | Condition |
|---|---|
| `CLASS_RSI_D` | `rsi_ma8_diff < mean − std` |
| `CLASS_RSI_MD` | `mean − std ≤ x < mean − 0.5·std` |
| `CLASS_RSI_M` | `−0.5·std ≤ x ≤ 0.5·std` |
| `CLASS_RSI_MU` | `mean + 0.5·std < x ≤ mean + std` |
| `CLASS_RSI_U` | `x > mean + std` |

Thresholds sourced from `DataAttributes.rsi_classification` (loaded from `stats/{pair}/rsi_classification.json`).

### 5.8 Targets

Only for timeframes in `{15, 60, 240, 1440}`.

| Field name | Output column | Computation |
|---|---|---|
| `tgt_long` | `{tf}_tgt_long` | `high.shift(1) × (1 + diff_prc_rm_high − tgt_shift × high_diff_prc_rm_mean_below)` |
| `sl_long` | `{tf}_sl_long` | `low.shift(1) × (1 + diff_prc_rm_low − sl_shift × low_diff_prc_rm_mean_below)` |
| `tgt_short` | `{tf}_tgt_short` | `low.shift(1) × (1 + diff_prc_rm_low + tgt_shift × low_diff_prc_rm_mean_above)` |
| `sl_short` | `{tf}_sl_short` | `high.shift(1) × (1 + diff_prc_rm_high + sl_shift × high_diff_prc_rm_mean_above)` |
| `ZB` | `{tf}_ZB` | `(0.3/1.0) × tgt_long + (0.7/1.0) × sl_long` — probability-weighted buy zone |
| `ZS` | `{tf}_ZS` | `(0.3/1.0) × tgt_short + (0.7/1.0) × sl_short` — probability-weighted sell zone |

`tgt_shift` / `sl_shift` values per class are sourced from `DataAttributes.diff_stats`.

### 5.9 NN Features

Pre-normalized features for direct NN consumption, computed only for `tf ∈ {1, 5, 15}`.

| Representative fields | Normalization |
|---|---|
| `nn_rsi_ma8_norm_mean` | `(rsi_ma8 − rsi_ma8_mean) / rsi_ma8_std` |
| `nn_close_diff_atr_ma` | `close_diff_prc / atr_ma` (ATR-relative return) |
| `nn_macd_hist_norm` | `macd_hist / atr_ma` |
| `nn_vol_norm` | `volume / vol_ma − 1` |

Full list declared in `indicators_config.yaml` under `group: nn_features`.

---

## 6. Dual-Library Support

The same `IndicatorField.compute()` method is called in both paths; the difference is what `data_point.get_df(tf)` returns.

| Path | `get_df(tf)` returns | Library used |
|---|---|---|
| Live (`LiveDataPoint`) | `ohlc[tf]` — full per-tf DataFrame | TA-Lib (`talib.abstract`) |
| Simulation (`WideDataPoint`) | slice from `build_indicator_input(df, ts, tf)` | `pandas_ta` |

### Why two libraries

TA-Lib is a compiled C extension — fast, industry-standard, but requires a compiled binary. `pandas_ta` is pure Python — no build dependency, compatible with the simulation environment where TA-Lib may not be available and correctness (not speed) is primary.

### `TalibField` implementation example

```python
class TalibField(IndicatorField):
    def compute(self, data_point: DataPoint, tf: int) -> pd.Series:
        df = data_point.get_df(tf)
        if isinstance(data_point, LiveDataPoint):
            return talib.abstract.__dict__[self.params["function"]](
                df, **{k: v for k, v in self.params.items() if k != "function"}
            )
        else:  # WideDataPoint (simulation)
            return getattr(pandas_ta, self.params["function"].lower())(
                df[f"{tf}_close"], **self.params
            )
```

---

## 7. DataAttributes Dependency

Classification and target fields require pair-level statistics from `DataAttributes`. These are not passed as arguments — each field implementation accesses them via the injected `DataAttributes` instance.

```python
class MoveClassField(IndicatorField):
    def __init__(self, attributes: DataAttributes, **kwargs):
        self._attrs = attributes

    def compute(self, data_point: DataPoint, tf: int) -> pd.Series:
        df = data_point.get_df(tf)
        stats = self._attrs.rsi_classification[str(tf)]
        mean = stats["mean"]
        std = stats["std"]
        return df[f"{tf}_rsi_ma8_diff"].apply(
            lambda x: CLASS_RSI_D  if x < mean - std       else
                      CLASS_RSI_MD if x < mean - 0.5 * std else
                      CLASS_RSI_M  if x <= mean + 0.5 * std else
                      CLASS_RSI_MU if x <= mean + std       else
                      CLASS_RSI_U
        )
```

If `rsi_classification` is absent (stats file not generated yet), the field returns NaN for that column; downstream classification-dependent fields also produce NaN. Non-fatal — strategies guard against NaN.

---

## 8. Dependency Resolution

`Indicators._sorted_fields(tf)` performs a topological sort on the field graph for `tf`:

```
rsi_14 → rsi_ma8 → rsi_ma8_diff → move_class → {tf}_class → tgt_long
                                 ↗
                    zone_class ──
close_diff_prc → close_diff_prc_rm → close_diff_prc_rm_mean_below → tgt_long
```

**Rules:**
- A field is excluded from the sorted list if `tf not in field.applies_to` (when `applies_to` is non-empty)
- Circular dependencies raise `ConfigError` at `load_registry()` time
- Fields with no dependencies run first in registration order

---

## 9. Error Handling

| Scenario | Handling |
|---|---|
| `indicators_config.yaml` missing | Fatal at startup — `load_registry()` raises `ConfigError`; no fallback |
| Circular dependency in config | Fatal at `load_registry()` |
| Field compute raises exception | Column set to NaN; error logged; remaining fields continue |
| `DataAttributes` stats file absent | Classification/target fields produce NaN; logged; non-fatal |
| NaN in indicator output (warm-up) | `bfill()` applied per column after each field write |
| `shift` exceeds data length in `WideDataPoint` | `float("nan")` returned by `WideDataPoint.get()` |

---

## 10. Integration Points

### 10.1 Called by

| Caller | When |
|---|---|
| `LiveData.build_candles(time_point)` | Each tick in live trading — once per tf after fetching from Binance |
| `trainer.py generate_full_ohlc` | Offline, once per `(ts, tf)` where `{tf}_is_closed=True` in wide DataFrame generation |

### 10.2 Depends on

| Component | Purpose |
|---|---|
| `DataPoint` protocol | Reads input via `get_df(tf)`; writes results back to same DataFrame |
| `DataAttributes` | Supplies `rsi_classification` and `diff_stats` to classification and target fields |
| `talib` | Live path computation (compiled C extension) |
| `pandas_ta` | Simulation path computation (pure Python) |
| `indicators_config.yaml` | Field registry — fatal if absent at startup |
| `candles_config.yaml` | Active timeframe list (determines which fields are excluded) |

### 10.3 Data flow

```
DataPoint.get_df(tf)  ←  ohlc[tf] (live) or build_indicator_input slice (simulation)
        ↓
Indicators._sorted_fields(tf)
        ↓ for each IndicatorField (dependency order)
field.compute(data_point, tf) → pd.Series
        ↓
data_point.get_df(tf)[f"{tf}_{field.name}"] = series
        ↓
bfill() on new column
        ↓
All {tf}_* columns written → consumed by SignalManager, Strategy, FullData
```

---

## 11. Migration from v1

### API changes

| v1 | v2 |
|---|---|
| `Indicators()` — instantiated per Data object | `Indicators` — class-level registry; no per-instance state |
| `indicators.calc(df)` — raw DataFrame in, modified in-place | `Indicators.compute(data_point, tf)` — DataPoint in, writes to `get_df(tf)` |
| Column names unprefixed: `"rsi"`, `"ema_25"` | Column names TF-prefixed: `"5_rsi_14"`, `"5_ema_25"` |
| Parameters hardcoded in `calc()` | Parameters declared in `indicators_config.yaml` |
| TA-Lib only | TA-Lib (live) + pandas_ta (simulation) |
| `calc_strategy()` — mixed indicator + decision logic | Removed; logic moved to Strategy module |
| `calc_strategy_margin()` | Removed |
| `get_markers()` — visualization markers | Removed; belongs in Visualization module |
| `select()` — stub | Removed |

### v1 → v2 call-site migration

```python
# v1
indicators = Indicators()
indicators.calc(ohlc_df)
rsi = ohlc_df["rsi"]

# v2
# (load_registry called once at startup)
Indicators.compute(data_point, tf=5)
rsi = data_point.get("rsi_14", tf=5)         # via DataPoint protocol
# or directly:
rsi = data_point.get_df(5)["5_rsi_14"]
```

---

## 12. Summary Table

| Aspect | v2 Details |
|---|---|
| **Architecture** | Registry of `IndicatorField` subclasses; topological dependency sort |
| **Entry point** | `Indicators.compute(data_point: DataPoint, tf: int) -> None` |
| **Configuration** | `indicators_config.yaml` — fatal if missing at startup |
| **Timeframe filtering** | `field.applies_to` — classification/target fields restricted to `{15, 60, 240, 1440}` |
| **Library (live)** | TA-Lib (`talib.abstract`) |
| **Library (simulation)** | `pandas_ta` |
| **Column convention** | `{tf}_{field.name}` (e.g. `5_rsi_14`, `60_move_class`) |
| **Stats dependency** | `DataAttributes` injected into classification and target fields |
| **NaN handling** | `bfill()` after each field write; missing stats → NaN (non-fatal) |
| **Error on bad config** | Fatal at `load_registry()` — `ConfigError` raised |
| **Removed methods** | `calc_strategy`, `calc_strategy_margin`, `get_markers`, `select`, `set_data` |
