# Data Layer Specification

**Version:** 2.0 — Two-path architecture with DataPoint isolation protocol
**Layer position:** Second from bottom — sits above Infrastructure, provides enriched OHLC data to the Business Logic layer.

**Related specs:**
- [Main Architecture](../2026-05-05-pybtctr2-architecture.md)
- [Infrastructure Layer](01-infrastructure-layer.md)
- [Business Logic Layer](03-business-logic-layer.md)
- [Data Module](../critical-path/data-module/data-module.md)
- [Data Class](../critical-path/data-module/data-class.md)

---

## 1. Overview

**Purpose:** Collect raw market data from Binance, enrich it with technical indicators and derived features, and expose a uniform `DataPoint` accessor interface to all upstream consumers — regardless of whether the system is running live or replaying a simulation.

**Responsibilities:**
- Fetch 1-minute OHLCV klines from Binance API (live) or raw pickle (training)
- Build multi-timeframe OHLC candle structures for `[1, 5, 15, 60, 240, 1440]` minutes
- Compute all indicators, price derivatives, classifications, targets, trend flags, and NN features via the `Indicators` class
- Expose the `DataPoint` protocol as the single access interface for all consumers
- Pre-compute and persist the wide DataFrame (`df_with_indicators.pkl`) for simulation
- Detect and manage support/resistance levels

**Key modules:** `grabers/grab_binance.py`, `data.py`, `indicators.py`, `levels.py`

---

## 2. Active Timeframes

Timeframes are not hardcoded — they are loaded at startup from `candles_config.yaml` (owned by the Infrastructure layer). Both the live path and simulation path read the same config. The data model makes no assumption about which specific timeframes are active; any set of minute-period values is valid.

Example config entry:
```yaml
candles: [1, 5, 15, 60, 240, 1440]   # or [1, 5, 15, 60, 240, 1440] — operator choice
```

The active list is exposed as a module-level constant (e.g. `data.candles`) after loading, so all consumers reference a single source of truth.

---

## 3. Layer Boundaries

**Upstream (feeds into this layer):**
- Binance API: raw 1-minute OHLCV klines
  - Live path: `stock.item.get_candles_history(CANDLES, coin, time_point)`
  - Training path: `graber_data.pkl` collected by `grab_binance.py`
- Infrastructure layer: path helpers, env vars (`PAIR`, `DATA_SET_NAME`, `DATA_START`, `DATA_END`)
- Stats files (version-controlled, static per pair):
  - `stats/rsi_classification.json` — RSI mean/std thresholds per tf
  - `stats/diff_stats.pkl` — price differential stats per class for targets/SL
  - `stats/level_stats.pkl` — level efficacy metrics
- `shared/{pair}/levels.txt` — hand-drawn support/resistance levels

**Downstream (layers that consume this layer):**
- Business Logic layer (signals, strategies): reads enriched data via `DataPoint.get(col, tf, shift)`
- Training/NN systems: reads `df_with_indicators.pkl` via `SimulationData`
- Visualization tools: reads `data.ohlc[tf]` DataFrames directly

**Key interface this layer exposes:**

```python
# Unified accessor — path-agnostic, consumed by all signals and strategies
DataPoint.get(col: str, tf: int, shift: int = 0) -> float

# Live path: DataPoint is a LiveDataPoint
data_point = data.get_data_point()              # wraps ohlc dict
val = data_point.get("rsi_14", tf=15)           # current 15-min RSI
val_prev = data_point.get("rsi_14", tf=15, shift=1)  # 1 bar ago

# Simulation path: DataPoint is a WideDataPoint
data_point = SimulationData(...).get()          # wraps df row at ts
val = data_point.get("rsi_14", tf=15)           # same call signature
val_closed = data_point.get("rsi_14", tf=15, shift=1)  # last closed candle
```

---

## 4. Two-Path Data Flow

### Path 1 — Live Trading

```
Binance API (1-min klines)
  ↓ stock.item.get_candles_history(CANDLES=[1,5,15,60,240,1440], coin, time_point)
Dict[tf → DataFrame]  — completed candles per tf, indexed by candle open time
  ↓ for tf in CANDLES:
      Indicators.compute(ohlc[tf], tf)
      → writes all IndicatorField results in-place:
        momentum (rsi_14, rsi_ma8, …)
        trend (ema_7/14/25/50/100, macd, sar)
        volatility (atr_14, atr_ma, bb_upper/middle/lower)
        oscillators (cci_14, cci_ma)
        volume (vol_ma, vol_buy_ma, vol_sell_ma)
        price derivatives (close_diff_prc, close_diff_prc_rm, …)
        classification (move_class, zone_class, {tf}_class, over_low, over_high)
        targets (tgt_long, sl_long, tgt_short, sl_short, ZB, ZS)
        trend flags (trend_up, trend_down)
        nn features (nn_rsi_ma8_norm_mean, nn_close_diff_atr_ma, …)
  ↓ LiveDataPoint(ohlc)
  ↓ SignalManager + Strategy consume via DataPoint.get(col, tf, shift)
```

**Live path column names**: prefixed within `ohlc[tf]` — e.g. `"5_rsi_14"`, `"5_close"`, `"5_tgt_long"`. Column naming is consistent with the wide DataFrame format. `LiveDataPoint.get("rsi_14", tf=5)` looks up `ohlc[5]["5_rsi_14"]`.

### Path 2 — Simulation / Training

```
graber_data.pkl  (raw 1-min OHLCV)
  ↓ get_stock_data(pair)
  → Wide base DataFrame  (1-min indexed, all tf groups):
      {tf}_open_index, {tf}_open, {tf}_high, {tf}_low, {tf}_close,
      {tf}_volume, {tf}_buy_volume, {tf}_is_closed
  ↓ Offline, for each tf in CANDLES:
      for ts where {tf}_is_closed=True:
          inp = build_indicator_input(df, ts, tf)  ← closed rows + no partial
          Indicators.compute(inp, tf)              ← writes to df.loc[ts, {tf}_*]
  ↓ compute future_target fields (tf ∈ {15,60,240,1440})
  ↓ save df_with_indicators.pkl

At simulation time:
  df = pd.read_pickle("df_with_indicators.pkl")
  for ts in replay_range:
      WideDataPoint(df, ts) → DataPoint.get(col, tf, shift)
```

**Simulation path column names**: prefixed — e.g. `"5_rsi_14"`, `"15_move_class"`, `"60_tgt_long"`. `WideDataPoint.get("rsi_14", tf=5)` looks up `df.loc[ts, "5_rsi_14"]`.

---

## 5. Wide DataFrame Column Specification

### Base OHLCV columns (per tf, computed at generation)

| Column | Computation | Candle boundary behaviour |
|--------|------------|--------------------------|
| `{tf}_open_index` | `index.floor(f"{tf}min")` | Constant within candle — identifies which candle this row belongs to |
| `{tf}_open` | `groupby({tf}_open_index)["open"].transform("first")` | Constant — candle open price |
| `{tf}_high` | `groupby({tf}_open_index)["high"].expanding().max()` | Expanding max — resets at candle boundary |
| `{tf}_low` | `groupby({tf}_open_index)["low"].expanding().min()` | Expanding min — resets at candle boundary |
| `{tf}_close` | `df["close"]` (1-min close) | Always the 1-min close at that exact row — no forward reference |
| `{tf}_volume` | `groupby({tf}_open_index)["volume"].expanding().sum()` | Expanding sum — resets at candle boundary |
| `{tf}_buy_volume` | `groupby({tf}_open_index)["taker_base_vol"].expanding().sum()` | Expanding sum |

### Candle state columns

| Column | Type | True when |
|--------|------|-----------|
| `{tf}_is_closed` | bool | Current row is the last 1-min row of the tf-period candle |
| `{tf}_open_index` | Timestamp | (Also serves as candle identity key) |

**`{tf}_is_closed` conditions:**

| tf | Condition |
|----|-----------|
| 1 | always True |
| 5 | `index.minute % 5 == 4` |
| 15 | `index.minute % 15 == 14` |
| 60 | `index.minute == 59` |
| 240 | `index.minute == 59 and index.hour % 4 == 3` |
| 1440 | `index.minute == 59 and index.hour == 23` |

### Indicator columns (per tf, computed at closed-candle rows)

Computed at `{tf}_is_closed=True` rows. Consumers can filter `df[df[f"{tf}_is_closed"]]` to get one definitive row per closed candle.

---

## 6. `build_indicator_input` — Indicator Input Construction

Used to build the closed-candle input series for indicator computation at timestamp `ts`, timeframe `tf`:

```python
def build_indicator_input(df: pd.DataFrame, ts: pd.Timestamp, tf: int) -> pd.DataFrame:
    subset = df[:ts]
    closed = subset[subset[f"{tf}_is_closed"]]
    if not subset.iloc[-1][f"{tf}_is_closed"]:
        partial = subset.iloc[[-1]]
        return pd.concat([closed, partial]).tail(105)
    return closed.tail(105)
```

Each row in the result:
- Indexed at its actual 1-min timestamp (the close minute of that candle)
- `{tf}_open_index` identifies which candle it represents
- No resampled-index aliasing — `08:59` row represents the 08:55 candle's final close state

---

## 7. `DataPoint` Shift Semantics

Shift applies uniformly across both implementations:

| shift | LiveDataPoint | WideDataPoint |
|-------|--------------|---------------|
| 0 | `ohlc[tf].iloc[-1]` (current row) | `df.loc[ts, f"{tf}_{col}"]` (current ts, partial if mid-period) |
| 1 | `ohlc[tf].iloc[-2]` | last `{tf}_is_closed=True` row ≤ ts |
| N | `ohlc[tf].iloc[-1-N]` | Nth last `{tf}_is_closed=True` row ≤ ts |

---

## 8. Full Data Interface

`FullData` is the read interface over the pre-computed wide DataFrame. It exposes per-timeframe views of completed candles only — consumers never touch the raw 1-min wide DataFrame directly.

```python
class FullData:
    def __init__(self, df: pd.DataFrame):
        self._df = df  # df_with_indicators.pkl, 1-min indexed

    def get(self, tf: int) -> pd.DataFrame:
        """
        Returns all closed-candle rows for timeframe tf.
        Each row corresponds to one completed tf-period candle.
        Row index = close minute of that candle.
        Columns = {tf}_* only (open_index, open, high, low, close, volume,
                   all indicator fields, is_closed, open_index).
        """
        mask = self._df[f"{tf}_is_closed"]
        tf_cols = [c for c in self._df.columns if c.startswith(f"{tf}_")]
        return self._df.loc[mask, tf_cols]

    def get_candle(self, tf: int, open_time: pd.Timestamp) -> pd.Series:
        """Returns the single closed-candle row for the candle that opened at open_time."""
        mask = (self._df[f"{tf}_open_index"] == open_time) & self._df[f"{tf}_is_closed"]
        return self._df.loc[mask].iloc[0]
```

**Usage by consumers:**
```python
full = FullData(df)

# One row per closed 5-min candle — for NN training, strategy research
df_5m = full.get(tf=5)      # columns: 5_open, 5_high, 5_rsi_14, 5_move_class, …

# One row per closed 15-min candle
df_15m = full.get(tf=15)

# Specific candle lookup
row = full.get_candle(tf=5, open_time=pd.Timestamp("2024-01-15 09:00"))
```

**Source:** `{root_folder}/{pair}/df_with_indicators.pkl` — single `pd.DataFrame`, 1-min indexed, generated offline by the wide data generation pipeline (see §9).

---

## 9. Execution Flows

### Historical data collection (`grab_binance.py`, run once)
1. Read `PAIR`, `DATA_START`, `DATA_END`, `BINANCE_API_KEY`, `BINANCE_API_SECRET`
2. Call `cl.get_historical_klines()` in 30-day chunks
3. Build DataFrame with columns: `open_time, o, h, l, c, v, close_time, taker_base_vol, …`
4. Save to `{root_folder}/graber_data.pkl`

### Candle building — live (`Data.build_candles`, called each tick)
1. `stock.item.get_candles_history(CANDLES, coin, time_point)` → `Dict[tf → DataFrame]`
2. For each tf: `Indicators.compute(ohlc[tf], tf)` — all fields in dependency order

### Wide data generation — simulation path (`trainer.py RUN_TYPE=generate_full_ohlc`)
Transforms `graber_data.pkl` into `df_with_indicators.pkl`:
1. Load `graber_data.pkl` → 1-min OHLCV DataFrame
2. `get_stock_data(pair)` → build base wide DataFrame: expanding `{tf}_open`, `{tf}_high`, `{tf}_low`, `{tf}_close`, `{tf}_volume`, `{tf}_buy_volume`, `{tf}_is_closed`, `{tf}_open_index` per tf
3. For each tf in `CANDLES`:
   - At each row where `{tf}_is_closed=True`: run `build_indicator_input(df, ts, tf)` → `Indicators.compute(data_point, tf)` → write results to `df.loc[ts, {tf}_*]`
   - Indicator values are written only at `{tf}_is_closed=True` rows; non-closed rows remain NaN — consumers filter using `{tf}_is_closed`
4. Compute `DataAttributes` artifacts: `rsi_classification.json`, `diff_stats.pkl` (if absent)
5. Save `df_with_indicators.pkl`

### Simulation replay (`SimulationData`)
1. Load `df_with_indicators.pkl` once at init
2. At each step ts: `WideDataPoint(df, ts)` — O(1) row lookup, no computation

### Level management (unchanged from v1)
1. `levels.load(thread_num)` — parses `shared/{pair}/levels.txt`
2. Each level: slope line from `(TIME1, VAL1)` to `(TIME2, VAL2)`, active between timestamps
3. `levels.get_level_value(level_dict, cur_time)` — linear interpolation

---

## 10. Key Classes

### `Data` (data.py)
Live path orchestrator. Holds `ohlc[tf]`, calls `Indicators.compute`, exposes `LiveDataPoint`.
Module-level singleton: `data.item`.

### `Indicators` (indicators.py)
All enrichment logic. Each field is a separate `IndicatorField` implementation. `Indicators.compute(ohlc_df, tf)` runs all fields in dependency order, in-place. No enrichment logic lives in `Data`.

### `SimulationData` (data.py)
Simulation path. Loads `df_with_indicators.pkl` once; yields `WideDataPoint` at each replay step.

### `FullData` (data.py)
Read interface over the wide DataFrame. Exposes `get(tf) -> pd.DataFrame` returning only `{tf}_is_closed=True` rows with `{tf}_*` columns. Used by visualization, NN training, and strategy research. See §8.

### `IndicatorField` (indicators.py)
Base class for every computed column. Each field declares `name`, `dependencies`, `applies_to` (timeframes), and implements `compute(data_point: DataPoint, tf: int) -> pd.Series`. The full registry is loaded from `indicators_config.yaml` at startup — no fields are hardcoded in `Indicators`. `Indicators.compute(data_point, tf)` runs all active fields for `tf` in dependency order, writing results back via the DataPoint's underlying DataFrame.

### `Levels` (levels.py)
Support/resistance level management (manual + auto-detected). Unchanged from v1.

### `PredictorField` (indicators.py — pending implementation)
`IndicatorField` subclass wrapping the pattern-based price predictor. Computes expected-next-high and expected-next-low columns (`predictor_high`, `predictor_low`) for each active timeframe. Output stored as `{tf}_predictor_high` / `{tf}_predictor_low` in the wide DataFrame; consumed via `DataPoint.get("predictor_high", tf)`. No predictor logic lives in StrategyManager.

### `NNProbabilityField` (indicators.py — pending implementation)
`IndicatorField` subclass running NN inference (or loading pre-computed outputs for the simulation path). Produces classification probability columns per timeframe (e.g. `{tf}_nn_prob_long`, `{tf}_nn_prob_short`). Simulation path reads pre-computed `.pkl`; live path runs online inference. Either way the output is a plain `{tf}_*` column accessed via `DataPoint.get()`. No NN loading or caching lives in StrategyManager.

### `PriceRejectionField` (indicators.py — pending implementation)
`IndicatorField` wrapping `check_price_stoped_rising` / `check_price_stoped_falling` logic. Produces `{tf}_price_stopped_rising` and `{tf}_price_stopped_falling` boolean columns. Strategies consume via `BoolValue_Signal("price_stopped_rising", tf)` inside signal chains.

Level dict schema (`LI_*` constant keys):
```python
{LI_NAME, LI_TIME1, LI_VAL1, LI_TIME2, LI_VAL2,
 LI_ACTIVE, LI_TYPE, LI_HAD_CONTACT}
```

Level types: `LEVEL_TYPE_LONG_SUPPORT/RESISTANCE (1/2)`, `LEVEL_TYPE_SHORT_SUPPORT/RESISTANCE (3/4)`, `LEVEL_TYPE_TARGET (5)`, `LEVEL_TYPE_AUTO_SUPPORT/RESISTANCE (6/7)`

---

## 11. Assumptions and Constraints

- **Active timeframes are config-driven**: loaded from `candles_config.yaml` at startup; the data model is timeframe-agnostic — see §2
- **All enrichment in `Indicators`**: `Data` has no column-computation logic; all field logic is in `IndicatorField` subclasses
- **`{tf}_close` is always the 1-min close at that row** — never a forward reference
- **`future_target` columns are full_data-only** — must never be present in live `ohlc[tf]` or accessible via `LiveDataPoint`
- **Singleton access**: `data.item` (`LiveData`, live path) is a module-level singleton; no dependency injection
- **Stats files are static per pair**: `rsi_classification.json` and `diff_stats.pkl` invalidate all cached data when changed; managed by `DataAttributes`
- **Level activation times in Unix seconds**: `DATA_START`/`DATA_END` are Unix milliseconds (÷1000 for internal use)
- **Timeframe list loaded from config**: `candles_config.yaml` — not hardcoded; both paths read the same file
- **Indicator registry loaded from config**: `indicators_config.yaml` — active fields and parameters declared externally
