# Data Module Specification

**Version:** 2.0 — Revised data model with two-path architecture
**Supersedes:** Version 1.0 (single-path, Dict-of-DataFrames only)

---

## 1. Overview

The Data module collects, normalizes, and enriches market OHLC data for two distinct operational paths that share the same consumer interface but differ in their internal data structure and computation strategy.

**Key Responsibilities:**
- Fetch 1-minute klines from Binance and build enriched multi-timeframe OHLC data
- Compute all technical indicators, price derivatives, classifications, targets, trend flags, and NN features via the `Indicators` class
- Expose a unified `DataPoint` protocol that isolates consumers from the underlying storage format
- Persist `full_data` (the pre-computed wide DataFrame) for simulation and NN training

**Core Classes:**
- `LiveData`: Orchestrates the live path; holds `ohlc[tf]` and wraps it in `LiveDataPoint`
- `SimulationData`: Orchestrates the simulation path; loads wide DataFrame, yields `WideDataPoint`
- `FullData`: Read interface over the wide DataFrame; exposes per-tf closed-candle views for visualization, NN training, and strategy research
- `Indicators`: Runs all `IndicatorField` instances; registry loaded from `indicators_config.yaml`
- `DataPoint` / `LiveDataPoint` / `WideDataPoint`: Isolation protocol consumed by signals and strategies
- `DataAttributes`: Manages all pair-level stat files (`rsi_classification.json`, `diff_stats.pkl`, `level_stats.pkl`) — loading, saving, and computation
- `Levels`: Support/resistance level management

---

## 2. Active Timeframes

Unified for both paths:

```python
CANDLES = [1, 5, 15, 60, 240, 1440]  # minutes
```

| TF | Duration | Role |
|----|----------|------|
| 1 min | 1 minute | Entry precision, base kline |
| 5 min | 5 minutes | Short-term momentum |
| 15 min | 15 minutes | Tactical bias |
| 60 min | 1 hour | Medium-term trend |
| 240 min | 4 hours | Strategic trend |
| 1440 min | 1 day | Daily context |

---

## 3. Two-Path Architecture

### 3.1 Path 1 — Live Trading

**Source:** `stock.item.get_candles_history(candles, coin, time_point)`

Returns `Dict[int, pd.DataFrame]` — one DataFrame per timeframe, indexed by TF-period open times.

**Enrichment:** `Indicators.compute(ohlc_df, tf)` applied per timeframe on the returned DataFrame.

**Access layer:** `LiveDataPoint` wraps `Dict[tf → DataFrame]`.

```
Binance API (1-min klines)
  ↓ stock.item.get_candles_history(CANDLES, coin, time_point)
Dict[tf → DataFrame]  (one completed-candle DataFrame per tf)
  ↓ for tf in CANDLES: Indicators.compute(ohlc[tf], tf)
Dict[tf → enriched DataFrame]
  ↓ LiveDataPoint(ohlc)
DataPoint  ←  consumed by SignalManager, Strategy
```

**shift semantics on LiveDataPoint:**
- `shift=0` → `ohlc[tf].iloc[-1]` (current/most recent candle)
- `shift=N` → `ohlc[tf].iloc[-1-N]` (N candles back)

### 3.2 Path 2 — Simulation / Training

**Source:** Pre-computed `df_with_indicators.pkl` (wide DataFrame, 1-min indexed).

Each row of the wide DataFrame IS a complete data point. The simulation replays it row by row (or at any time-step interval).

**Access layer:** `WideDataPoint` wraps a single `pd.Series` — `df.loc[ts]`.

```
graber_data.pkl  (raw 1-min klines)
  ↓ get_stock_data() — build expanding OHLCV columns per tf
Wide base DataFrame  (1_open, 1_close, 5_open, 5_high, ... {tf}_is_closed, {tf}_open_index)
  ↓ for ts in df.index (every 1-min row):
      for tf in CANDLES: Indicators.compute(build_indicator_input(df, ts, tf))
  ↓ (no ffill — every row is computed independently)
df_with_indicators.pkl  (1-min indexed, ~300+ columns, each row a complete WideDataPoint)
  ↓ at simulation time ts: WideDataPoint(df.loc[ts])
DataPoint  ←  consumed by SignalManager, Strategy (same interface)
```

**shift semantics on WideDataPoint:**
- `shift=0` → `df.loc[ts, f"{tf}_{col}"]` (current value, partial candle if mid-period)
- `shift=N` → `closed = df[:ts][df[:ts][f"{tf}_is_closed"]]; closed.iloc[-N][col]` (Nth last closed candle)

---

## 4. Wide DataFrame — Column Structure

The wide DataFrame stores all timeframes as column groups in a single 1-min indexed DataFrame.

### 4.1 Base OHLCV columns (per tf)

Computed by `get_stock_data()` using expanding groupby within each candle period:

| Column | Computation | Behaviour within candle period |
|--------|------------|-------------------------------|
| `{tf}_open_index` | `index.floor(f"{tf}min")` | Constant — candle open **timestamp** |
| `{tf}_open` | `groupby({tf}_open_index)["open"].transform("first")` | Constant — candle open **price** |
| `{tf}_high` | `groupby({tf}_open_index)["high"].expanding().max()` | Expanding max, resets at candle boundary |
| `{tf}_low` | `groupby({tf}_open_index)["low"].expanding().min()` | Expanding min, resets at candle boundary |
| `{tf}_close` | `df["close"]` (1-min close) | Current 1-min close = current candle close state |
| `{tf}_volume` | `groupby({tf}_open_index)["volume"].expanding().sum()` | Expanding sum, resets at candle boundary |
| `{tf}_buy_volume` | `groupby({tf}_open_index)["taker_base_vol"].expanding().sum()` | Expanding sum of taker buy volume |

### 4.2 Candle state columns (per tf)

| Column | Type | Definition |
|--------|------|-----------|
| `{tf}_is_closed` | bool | True when current row is the last 1-min row of the tf-period candle |
| `{tf}_open_index` | Timestamp | Open time of the candle this row belongs to (also the group key) |

**`{tf}_is_closed` rules:**

| tf | True when |
|----|-----------|
| 1 | always (every 1-min row is a complete kline) |
| 5 | `index.minute % 5 == 4` |
| 15 | `index.minute % 15 == 14` |
| 60 | `index.minute == 59` |
| 240 | `index.minute == 59 and index.hour % 4 == 3` |
| 1440 | `index.minute == 59 and index.hour == 23` |

### 4.3 Closed candle lookup

```python
# Row where the 09:00 5-min candle was finally closed:
df[(df["5_open_index"] == pd.Timestamp("09:00")) & df["5_is_closed"]]
# → single row at index 09:04, containing the final OHLCV and indicator values

# All closed 5-min candles (for NN training, chart rendering):
df[df["5_is_closed"]]  # one row per completed 5-min candle, indexed at close minute
```

### 4.4 Example rows (tf=5, around 08:55–09:05)

```
index(1min)  5_open_index  5_open   5_high      5_low       5_close  5_volume   5_is_closed
08:55        08:55         p₀       p₀          p₀          c₀       v₀         False
08:56        08:55         p₀       max(h₀,h₁)  min(l₀,l₁)  c₁       v₀+v₁      False
08:57        08:55         p₀       …           …           c₂       …          False
08:58        08:55         p₀       …           …           c₃       …          False
08:59        08:55         p₀       H_final     L_final     c₄       V_final     True   ← 08:55 closed
09:00        09:00         p₅       p₅          p₅          c₅       v₅         False
09:01        09:00         p₅       max(h₅,h₆)  …           c₆       …          False
09:02        09:00         p₅       …           …           c₇       …          False
09:03        09:00         p₅       …           …           c₈       …          False
09:04        09:00         p₅       H_final     L_final     c₉       V_final     True   ← 09:00 closed
09:05        09:05         p₁₀      p₁₀         p₁₀         c₁₀      v₁₀        False
```

Key: at every row, `{tf}_close` = 1-min close at **that row** (no forward reference). `{tf}_high` = expanding max within the current candle only.

---

## 5. Indicator Computation

### 5.1 IndicatorField pattern

Every computed column is a separate `IndicatorField` implementation owned by the `Indicators` class. No enrichment logic lives in `LiveData`. The full field registry is declared in `indicators_config.yaml` and loaded at startup — no fields are hardcoded in Python.

```python
class IndicatorField:
    name: str                    # output column name suffix (e.g. "rsi_14")
    dependencies: list[str]      # other field names that must be computed first
    applies_to: list[int]        # timeframes this field is valid for ([] = all CANDLES)

    def compute(self, data_point: DataPoint, tf: int) -> pd.Series:
        """
        Reads prior columns from data_point via data_point.get_df(tf)
        (which exposes the underlying DataFrame for the given tf).
        Returns a Series to be written back as f"{tf}_{self.name}".
        """
        df = data_point.get_df(tf)
        ...
```

`Indicators.compute(data_point: DataPoint, tf: int)` runs all active fields for `tf` in dependency order, reading input via `data_point.get_df(tf)` and writing results back:

```python
class Indicators:
    @staticmethod
    def compute(data_point: DataPoint, tf: int) -> None:
        for field in Indicators._sorted_fields(tf):
            series = field.compute(data_point, tf)
            data_point.get_df(tf)[f"{tf}_{field.name}"] = series
```

`DataPoint.get_df(tf)` exposes the mutable underlying DataFrame for indicator computation:
- `LiveDataPoint.get_df(tf)` → `self._ohlc[tf]`
- `WideDataPoint.get_df(tf)` → slice of wide df reconstructed by `build_indicator_input`

### 5.2 IndicatorField groups

The active field list and parameters are declared in `indicators_config.yaml`. The table below describes the field groups that the default config registers. New fields are added by creating an `IndicatorField` subclass and adding an entry to the config — no changes to `Indicators` itself.

```yaml
# indicators_config.yaml (excerpt)
fields:
  - name: rsi_14
    group: momentum
    applies_to: all
    params: {length: 14}
    library: talib   # live path
  - name: rsi_ma8
    group: momentum
    depends_on: [rsi_14]
    applies_to: all
    params: {source: rsi_14, length: 8}
  - name: move_class
    group: classification
    applies_to: [15, 60, 240, 1440]
    depends_on: [rsi_ma8, rsi_ma8_diff]
    params: {stats_source: rsi_classification}
  ...
```

| Group | Representative Fields | tf scope |
|-------|----------------------|----------|
| Momentum | `rsi_14`, `rsi_ma8`, `rsi_ma12`, `rsi_ma24`, `rsi_ma8_diff`, `rsi_ma12_diff`, `rsi_ma24_diff` | all |
| Trend | `ema_7`, `ema_14`, `ema_25`, `ema_50`, `ema_100`, `macd`, `macd_signal`, `macd_hist`, `macd_fast`, `macd_fast_signal` | all |
| Volatility | `atr_14`, `natr_14`, `atr_ma`, `bb_upper`, `bb_middle`, `bb_lower`, `bb_fast_upper`, `bb_fast_lower`, `bb_wide_upper`, `bb_wide_lower` | all |
| Oscillators | `cci_14`, `cci_ma`, `sar` | all |
| Volume | `vol_ma`, `vol_buy_ma`, `vol_sell_ma` | all |
| Price Derivatives | `close_diff_prc`, `close_diff_prc_rm`, `close_diff_prc_rm_mean_above`, `close_diff_prc_rm_mean_below` *(×3 for close/high/low)* | all |
| Classification | `move_class`, `zone_class`, `{tf}_class`, `over_low`, `over_high` | {15, 60, 240, 1440} |
| Targets | `tgt_long`, `sl_long`, `tgt_short`, `sl_short`, `ZB`, `ZS` | {15, 60, 240, 1440} |
| Trend Flags | `trend_up`, `trend_down` | all |
| NN Features | `nn_rsi_ma8_norm_mean`, `nn_close_diff_atr_ma`, … | {1, 5, 15} |

### 5.3 build_indicator_input

Used by the simulation path to construct the indicator input series at a given timestamp:

```python
def build_indicator_input(df: pd.DataFrame, ts: pd.Timestamp, tf: int) -> pd.DataFrame:
    subset = df[:ts]
    closed = subset[subset[f"{tf}_is_closed"]]      # one row per completed candle (at close minute)
    if not subset.iloc[-1][f"{tf}_is_closed"]:      # current candle still open
        partial = subset.iloc[[-1]]                 # append current partial state
        return pd.concat([closed, partial]).tail(105)
    return closed.tail(105)                          # ts itself is a close minute
```

Each row in the result:
- Index = actual 1-min timestamp (the close minute of that candle)
- `{tf}_open_index` = which candle it belongs to
- `{tf}_close` = final close of completed candles, or partial close for the current row

This eliminates the `resample().last()` approach and makes it explicit that no forward-reference occurs.

**RSI-14 example at `ts=09:04`, tf=5:**

```python
inp = build_indicator_input(df, "09:04", 5)
# inp tail:
#   index    5_open_index  5_close
#   ...
#   08:54    08:50         c_08:54   ← close of 08:50 candle
#   08:59    08:55         c_08:59   ← close of 08:55 candle
#   09:04    09:00         c_09:04   ← close of 09:00 candle (complete, 5_is_closed=True)

rsi = pandas_ta.rsi(inp["5_close"], length=14)
# rsi.iloc[-1]  →  stored as df.loc["09:04", "5_rsi_14"]
```

**RSI-14 example at `ts=09:02`, tf=5 (partial candle):**

```python
inp = build_indicator_input(df, "09:02", 5)
# inp tail:
#   index    5_open_index  5_close
#   ...
#   08:59    08:55         c_08:59   ← close of 08:55 candle
#   09:02    09:00         c_09:02   ← partial: only 3 of 5 minutes accumulated

rsi = pandas_ta.rsi(inp["5_close"], length=14)
# rsi.iloc[-1]  →  stored as df.loc["09:02", "5_rsi_14"]
# Differs from 09:04 value because c_09:02 ≠ c_09:04
```

---

## 6. Full Data

### 6.1 Purpose

Full data is the pre-computed enriched wide DataFrame covering a full historical range. It is generated once offline and serves as:

1. **Simulation replay source** — `SimulationData` reads rows at each time step via `WideDataPoint`
2. **NN training data** — `FullData.get(tf)` exposes one row per closed candle for feature extraction
3. **Stats computation** — generate `rsi_classification.json`, `diff_stats.pkl` via `DataAttributes`
4. **Strategy research and visualization** — `FullData.get(tf)` provides clean per-tf DataFrames

### 6.2 Storage

```
{root_folder}/{pair}/df_with_indicators.pkl   ← wide DataFrame, 1-min indexed
```

### 6.3 FullData interface — per-tf closed-candle views

Full data is consumed exclusively through the `FullData` interface, which filters the wide DataFrame to expose only completed candles for each timeframe:

```python
full = FullData(df)

# One row per closed 5-min candle
df_5m  = full.get(tf=5)    # columns: 5_open, 5_high, 5_low, 5_close, 5_rsi_14, …

# One row per closed 15-min candle
df_15m = full.get(tf=15)

# Specific closed candle by its open time
row = full.get_candle(tf=5, open_time=pd.Timestamp("2024-01-15 09:00"))
# → row at index 09:04, columns 5_*

# NN training samples at 15-min granularity
samples = full.get(tf=15)[nn_feature_cols]
```

No consumer accesses `df_with_indicators.pkl` directly. No partial-candle values — each row from `FullData.get(tf)` represents a completed, stable candle state.

### 6.4 Wide DataFrame row semantics

The underlying wide DataFrame stores 1-min rows. For each `tf`, indicator values are **computed at every 1-min row** using that row's state — closed-candle state where `{tf}_is_closed=True`, partial-candle state at all other rows (via the expanding `{tf}_close/high/low/volume` columns). Every row is itself a complete `WideDataPoint`: there is **no forward-fill** and no row carries a stale stand-in value.

```
index    5_is_closed  5_close      5_rsi_14         15_is_closed  15_rsi_14
09:00    False        c_09:00      computed @09:00  False         computed @09:00
09:01    False        c_09:01      computed @09:01  False         computed @09:01
09:02    False        c_09:02      computed @09:02  False         computed @09:02
09:03    False        c_09:03      computed @09:03  False         computed @09:03
09:04    True         c_09:04      computed @09:04  False         computed @09:04   ← 5-min closes
09:05    False        c_09:05      computed @09:05  False         computed @09:05
…
09:14    True         c_09:14      computed @09:14  True          computed @09:14   ← 5-min AND 15-min close
```

Each `{tf}_rsi_14` value at row `ts` uses the partial-candle close visible at `ts` (the expanding `{tf}_close`), so `5_rsi_14` at 09:02 ≠ `5_rsi_14` at 09:04 — the former is the RSI of the partial 09:00–09:02 segment, the latter is the RSI of the fully-closed 09:00–09:04 candle.

`FullData.get(tf)` filters to `{tf}_is_closed=True` rows — one row per *completed* candle, useful for NN training and chart rendering. `SimulationData` (replay) and `LiveData` (live) both consume every row.

### 6.5 Generation — see Wide Data Generation (§8.2)

---

## 7. DataPoint Protocol

The `DataPoint` protocol is the **isolation layer** between the data storage format and all consumers (signals, strategies, robot).

```python
class DataPoint:
    def get(self, col: str, tf: int, shift: int = 0) -> float:
        """
        Returns the value of column `col` for timeframe `tf`.
        shift=0: current value (partial candle if mid-period)
        shift=N (N>0): Nth most recently completed candle
        """
        ...
```

### 7.1 LiveDataPoint

Wraps `Dict[int, pd.DataFrame]` — the live path's per-tf DataFrames.

```python
class LiveDataPoint(DataPoint):
    def __init__(self, ohlc: dict[int, pd.DataFrame]):
        self._ohlc = ohlc

    def get(self, col: str, tf: int, shift: int = 0) -> float:
        return self._ohlc[tf][col].iloc[-1 - shift]
```

- `shift=0` → most recent (current/last complete) candle
- `shift=N` → N candles back by row offset

### 7.2 WideDataPoint

Wraps the wide DataFrame and a processing timestamp `ts`.

```python
class WideDataPoint(DataPoint):
    def __init__(self, df: pd.DataFrame, ts: pd.Timestamp):
        self._df = df
        self._ts = ts

    def get(self, col: str, tf: int, shift: int = 0) -> float:
        if shift == 0:
            return self._df.loc[self._ts, f"{tf}_{col}"]
        closed = self._df[:self._ts][self._df[:self._ts][f"{tf}_is_closed"]]
        if len(closed) < shift:
            return float("nan")
        return closed.iloc[-shift][f"{tf}_{col}"]
```

- `shift=0` → current value at `ts` (partial candle if mid-period)
- `shift=N` → Nth last closed-candle row up to `ts`, using `{tf}_is_closed` filter

**At `ts=09:04`, tf=5:**
- `shift=0` → `df.loc["09:04", "5_rsi_14"]` (complete candle, is_closed=True)
- `shift=1` → closed.iloc[-1] = row 09:04 (last closed = current)
- `shift=2` → closed.iloc[-2] = row 08:59 (previous closed candle)

**At `ts=09:02`, tf=5:**
- `shift=0` → `df.loc["09:02", "5_rsi_14"]` (partial candle state)
- `shift=1` → closed.iloc[-1] = row 08:59 (last closed candle)
- `shift=2` → closed.iloc[-2] = row 08:54

---

## 8. Execution Flows

### 8.1 Live Trading (called each tick)

```
Robot.run_tick()
  ↓
Data.build_candles(time_point=0)
  ↓ stock.item.get_candles_history(CANDLES, coin, time_point=0)
  → ohlc: Dict[tf → DataFrame]  (completed candles per tf)
  ↓ for tf in CANDLES:
      Indicators.compute(ohlc[tf], tf)  — all IndicatorFields in dependency order
  ↓ LiveDataPoint(ohlc)
  ↓ SignalManager.check(data_point) + Strategy.select_action(data_point)
  ↓ Robot.execute_order(action)
```

### 8.2 Wide Data Generation (offline, run once)

Transforms `graber_data.pkl` into `df_with_indicators.pkl`:

```
trainer.py  RUN_TYPE=generate_full_ohlc
  ↓
Step 1: Load graber_data.pkl → 1-min OHLCV DataFrame

Step 2: get_stock_data(pair)
  → for each tf in CANDLES:
      build {tf}_open_index, {tf}_open, {tf}_high, {tf}_low,
            {tf}_close, {tf}_volume, {tf}_buy_volume, {tf}_is_closed

Step 3: Load indicator registry from indicators_config.yaml

Step 4: for tf in CANDLES:
    for ts in df.index:                              ← every 1-min row, NOT just closes
        data_point = WideDataPoint(df, ts)           ← wraps wide df at ts
        Indicators.compute(data_point, tf)           ← runs all IndicatorFields for tf
        results written to df.loc[ts, {tf}_*]        ← via data_point.get_df(tf)
    # No ffill: each row independently holds the indicator value for its
    # own state (closed-candle at boundaries, partial-candle mid-period).

Step 5: DataAttributes.compute(df)
  → rsi_classification.json  (if absent)
  → diff_stats.pkl            (if absent)

Step 6: Save df_with_indicators.pkl
```

### 8.3 Simulation (backtest replay)

```
TrainRobot.simulate(begin_ts, end_ts, step_minutes)
  ↓
SimulationData(pair, begin_ts, end_ts, step_minutes)
  ↓ loads df_with_indicators.pkl once
  ↓ for ts in range(begin_ts, end_ts, step_minutes):
      data_point = WideDataPoint(df, ts)
      ↓ SignalManager.check(data_point) + Strategy.select_action(data_point)
      ↓ TrainRobot.buy() / sell() — match against {tf}_high / {tf}_low at ts
      ↓ position.finalize() → revenue_pct, revenue_abs
  ↓ aggregate results across threads
```

---

## 9. Module Boundaries

### Upstream (feeds into this module)
- **Binance API** via `stock.item.get_candles_history()` — live path
- **graber_data.pkl** — simulation/training path raw source
- **stats/ files** (version-controlled, static per pair):
  - `rsi_classification.json` — RSI thresholds for classification
  - `diff_stats.pkl` — price differential stats per class for targets/SL
  - `level_stats.pkl` — level efficacy metrics

### Downstream (consumes this module)
- **Signals module** (`signals_lib/`) — reads via `DataPoint.get(col, tf, shift)`
- **Strategy module** (`strategies/`) — reads via `DataPoint.get(col, tf, shift)`
- **Robot** (`robot.py`) — live: calls `Data.build_candles()` each tick
- **TrainRobot** (`train_robot.py`) — simulation: uses `SimulationData` → `WideDataPoint`
- **Trainer** (`trainer.py`) — generates full_data, runs simulation, aggregates results

### Key interfaces exposed
```python
# Primary consumer interface (path-agnostic)
DataPoint.get(col: str, tf: int, shift: int = 0) -> float
DataPoint.get_df(tf: int) -> pd.DataFrame          # mutable underlying df (for Indicators)

# Live path: rebuild from Binance each tick
LiveData.build_candles(time_point: int = 0) -> None
LiveData.get_data_point() -> LiveDataPoint

# Simulation: iterate over wide DataFrame
SimulationData(pair, begin_ts, end_ts, step_min) → yields WideDataPoint

# Full data: per-tf closed-candle views (visualization, NN training, strategy research)
FullData.get(tf: int) -> pd.DataFrame              # one row per closed candle
FullData.get_candle(tf: int, open_time: Timestamp) -> pd.Series

# Level access (unchanged)
levels.get_level_value(level_dict, cur_time) -> float
levels.is_price_near_level(price, level, atr, cur_time) -> bool
```

---

## 10. Data Persistence

| File | Format | Written by | Read by | Contents |
|------|--------|-----------|---------|----------|
| `graber_data.pkl` | DataFrame pkl | `grab_binance.py` | `get_stock_data()` | Raw 1-min OHLCV from Binance |
| `df_with_indicators.pkl` | DataFrame pkl | `trainer.py` generate_full_ohlc | `SimulationData` | Wide DataFrame, all TFs, all indicators |
| `rsi_classification.json` | JSON | `trainer.py` stats step | `Indicators` | RSI mean/std per tf for classification |
| `diff_stats.pkl` | dict pkl | `trainer.py` stats step | `Indicators` | Price diff stats per class for targets |
| `level_stats.pkl` | dict pkl | manual / offline | `Indicators` | Level efficacy metrics |
| `shared/thread_result_by_id_{N}.pkl` | dict pkl | `TrainRobot` threads | `Trainer` | Per-thread simulation results |
| Legacy: `data/{ts}/ohlc.pkl` | dict pkl | (deprecated) | (deprecated) | Old per-timestamp snapshots |

---

## 11. Constraints and Invariants

- **Timeframe list from config**: `candles_config.yaml` — unified for both paths; not hardcoded
- **Indicator registry from config**: `indicators_config.yaml` — active fields and parameters declared externally; no hardcoded field list in `Indicators`
- **Singleton access**: `data.item` (`LiveData`, live path) is a module-level singleton; `SimulationData` and `FullData` are instantiated per run
- **All enrichment in Indicators**: `LiveData` has no column-computation logic; all field logic is in `IndicatorField` subclasses loaded from config
- **No partial-candle values via FullData**: `FullData.get(tf)` returns only `{tf}_is_closed=True` rows — stable completed states
- **Simulation sees partial candles**: `WideDataPoint` at non-closed rows returns current partial state (shift=0), enabling realistic tick-by-tick replay
- **`{tf}_close` is always the 1-min close at that row**: Never a forward reference
- **Stats files managed by DataAttributes**: `rsi_classification.json`, `diff_stats.pkl` — each attribute has its own load/save/compute implementation
- **Level activation times in Unix seconds**: `DATA_START` / `DATA_END` env vars are Unix milliseconds (÷1000 for internal use)
