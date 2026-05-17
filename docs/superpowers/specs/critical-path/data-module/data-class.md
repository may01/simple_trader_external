# Data Class Specification

**Version:** 2.0 — LiveData / SimulationData / FullData split; DataAttributes; config-driven timeframes and indicator registry

---

## 1. Class Overview

### `LiveData`
Manages the **live trading path**. Fetches per-tf DataFrames from `stock.item.get_candles_history()`, delegates all enrichment to `Indicators.compute()`, and exposes a `LiveDataPoint` for downstream consumption.

### `SimulationData`
Manages the **simulation path**. Loads `df_with_indicators.pkl` once at init and yields a `WideDataPoint` at each replay step. No indicator computation at replay time — all values are pre-computed.

### `FullData`
Read interface over the wide DataFrame. Exposes per-tf views of completed candles for visualization, NN training, and strategy research. See §8.

Both `LiveData` and `SimulationData` expose the same `DataPoint` protocol — consumers (signals, strategies) do not know which path they are on.

**Responsibilities of `LiveData`:**
- Call `stock.item.get_candles_history()` and hold the resulting per-tf DataFrames
- Delegate all enrichment to `Indicators.compute(data_point, tf)`
- Produce `LiveDataPoint` for downstream consumption
- Cache NN predictions

**Responsibilities of `Indicators`:**
- All field computation: indicators, price derivatives, classifications, targets, trend flags, NN features
- Each field is a separate `IndicatorField` implementation loaded from `indicators_config.yaml`
- `Indicators.compute(data_point, tf)` runs all active fields in dependency order
- Live path uses TA-Lib; simulation path uses `pandas_ta`

**Responsibilities of `DataAttributes`:**
- Load, save, and compute all pair-level stat files
- Each attribute (rsi_classification, diff_stats, targets_stats) is a separate `DataAttribute` implementation

---

## 2. DataPoint Protocol

The isolation layer between storage format and all consumers.

```python
class DataPoint:
    def get(self, col: str, tf: int, shift: int = 0) -> float:
        """
        col:   column name WITHOUT tf prefix (e.g. "rsi_14", "close", "ema_25")
        tf:    timeframe in minutes (from CANDLES config)
        shift: 0 = current value; N>0 = Nth last completed candle
        """

    def get_df(self, tf: int) -> pd.DataFrame:
        """
        Exposes the mutable underlying DataFrame for tf.
        Used by Indicators.compute() to read input columns and write results.
        """
```

### LiveDataPoint

```python
class LiveDataPoint(DataPoint):
    def __init__(self, ohlc: dict[int, pd.DataFrame]):
        self._ohlc = ohlc

    def get(self, col: str, tf: int, shift: int = 0) -> float:
        return self._ohlc[tf][f"{tf}_{col}"].iloc[-1 - shift]

    def get_df(self, tf: int) -> pd.DataFrame:
        return self._ohlc[tf]
```

- `shift=0` → most recent (current/last complete) candle from `ohlc[tf]`
- `shift=N` → N candles back by row offset in `ohlc[tf]`

### WideDataPoint

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

    def get_df(self, tf: int) -> pd.DataFrame:
        return build_indicator_input(self._df, self._ts, tf)
```

- `shift=0` → current value at `ts` (partial candle if mid-period)
- `shift=N` → Nth last `{tf}_is_closed=True` row up to `ts`

**Shift examples at `ts=09:02`, tf=5:**
- `shift=0` → `df.loc["09:02", "5_rsi_14"]` (partial candle)
- `shift=1` → row at 08:59 (last closed 5-min candle)
- `shift=2` → row at 08:54

**Shift examples at `ts=09:04`, tf=5 (closed boundary):**
- `shift=0` → `df.loc["09:04", "5_rsi_14"]` (complete candle)
- `shift=1` → row at 09:04 (itself in the closed list)
- `shift=2` → row at 08:59

---

## 3. DataAttributes Class

Manages all pair-level stat artifacts. Each attribute is a separate `DataAttribute` implementation responsible for its own load, save, and compute logic.

```python
class DataAttribute:
    name: str        # e.g. "rsi_classification"
    file_path: str   # e.g. "stats/{pair}/rsi_classification.json"

    def load(self) -> Any:
        """Load from file. Returns the data structure."""

    def save(self, data: Any) -> None:
        """Persist to file."""

    def compute(self, full_df: pd.DataFrame) -> Any:
        """Derive from the wide DataFrame when file is absent."""
```

**Concrete implementations:**

| Class | File | Computes from | Consumed by |
|-------|------|---------------|-------------|
| `RsiClassificationAttribute` | `stats/{pair}/rsi_classification.json` | RSI/rsi_ma8 distributions in full_df | `ClassificationField`, `ZoneClassField` |
| `DiffStatsAttribute` | `stats/{pair}/diff_stats.pkl` | price diff distributions per class | `TargetsField`, `SLField` |
| `TargetsStatsAttribute` | `stats/{pair}/level_stats.pkl` | level efficacy metrics | `TargetsField` |

```python
class DataAttributes:
    rsi_classification: RsiClassificationAttribute
    diff_stats: DiffStatsAttribute
    targets_stats: TargetsStatsAttribute

    def load_all(self, pair: str) -> None:
        """Load all attributes from files. Non-fatal if any file is missing."""

    def compute_missing(self, full_df: pd.DataFrame) -> None:
        """Compute and save any attribute whose file is absent."""
```

`DataAttributes` is instantiated once per pair and injected into `Indicators` and `FullData`.

---

## 4. LiveData Class — Attributes

| Attribute | Type | Purpose | Initial Value |
|-----------|------|---------|---------------|
| `pair` | str | Trading pair in `coin_base` format (e.g. `link_usdt`) | Set at init |
| `coin` | str | Asset symbol | `pair.split("_")[0]` |
| `coin_base` | str | Quote currency | `pair.split("_")[1]` |
| `ohlc` | `dict[int, pd.DataFrame]` | Enriched OHLCV per timeframe (live path) | Empty DataFrames per tf |
| `cur_point` | int | Current Unix timestamp (seconds) | 0 |
| `attributes` | `DataAttributes` | Loaded stat artifacts (rsi_classification, diff_stats, targets_stats) | Loaded at init |
| `nn_cache_all` | list[float] | NN predictions: all-TF model `[buy_prob, sell_prob, none_prob]` | `[0, 0, 0]` |
| `nn_cache_small` | list[float] | NN predictions: small-TF model | `[0, 0, 0]` |
| `nn_cache_big` | list[float] | NN predictions: big-TF model | `[0, 0, 0]` |
| `nn_history_cache` | pd.DataFrame | Rolling 60-row NN prediction history (`long`, `short` columns) | Empty DataFrame |
| `atr_limit` | `dict[int, float]` | ATR threshold per tf | 0.0 per tf |

---

## 5. LiveData Class — Constructor

```python
def __init__(self, pair: str) -> None
```

**Initialization order:**
1. `self.reset(pair)` — initialize all per-tf structures
2. Load `CANDLES` from `candles_config.yaml`
3. `self.attributes = DataAttributes()` → `attributes.load_all(pair)` (non-fatal if files missing)
4. Initialize `nn_history_cache` as empty DataFrame with columns `["long", "short"]`

**Postconditions:** `ohlc[tf]` are empty DataFrames; ready for `build_candles()`.

---

## 6. LiveData Class — Key Methods

### 6.1 `reset(pair)`

```python
def reset(self, pair: str) -> None:
    self.pair = pair
    self.coin = pair.split("_")[0]
    self.coin_base = pair.split("_")[1]
    for tf in CANDLES:
        self.ohlc[tf] = pd.DataFrame()
        self.atr_limit[tf] = 0.0
    self.nn_cache_all = self.nn_cache_small = self.nn_cache_big = [0, 0, 0]
```

### 6.2 `build_candles(time_point=0)`

Fetches live data and enriches all timeframes. Called each tick in live trading.

```python
def build_candles(self, time_point: int = 0) -> None:
    raw = stock.item.get_candles_history(CANDLES, self.coin, time_point)
    for tf in CANDLES:
        self.ohlc[tf] = raw[tf]
        Indicators.compute(self.get_data_point(), tf)
```

**Postconditions:** `ohlc[tf]` populated with all indicator columns. Ready for `get_data_point()`.

### 6.3 `get_data_point() -> LiveDataPoint`

```python
def get_data_point(self) -> LiveDataPoint:
    return LiveDataPoint(self.ohlc)
```

All signals and strategies receive this object and call `data_point.get(col, tf, shift)`.

### 6.4 `get_cur_price(col, shift=0, tf=0) -> float`

Legacy accessor — delegates to `LiveDataPoint.get()` for backward compatibility.

```python
def get_cur_price(self, col: str, shift: int = 0, tf: int = 0) -> float:
    if tf == 0:
        tf = CANDLES[0]
    return self.ohlc[tf][col].iloc[-1 - shift]
```

### 6.5 `get_ma_price(col, shift=0, window=5, tf=0) -> float`

```python
def get_ma_price(self, col: str, shift: int = 0, window: int = 5, tf: int = 0) -> float:
    if tf == 0:
        tf = CANDLES[0]
    return self.ohlc[tf][col].rolling(window=window, center=False).mean() \
               .iloc[-1 - shift]
```

---

## 7. Indicators Class — Architecture

### 7.1 IndicatorField base

```python
class IndicatorField:
    name: str                # output column suffix (e.g. "rsi_14")
    dependencies: list[str]  # other field names computed first
    applies_to: list[int]    # timeframes this field applies to ([] = all CANDLES)

    def compute(self, data_point: DataPoint, tf: int) -> pd.Series:
        df = data_point.get_df(tf)   # read input columns from underlying DataFrame
        ...                          # return Series to be written as f"{tf}_{self.name}"
```

### 7.2 `Indicators.compute(data_point, tf)`

```python
class Indicators:
    _registry: list[IndicatorField] = []  # loaded from indicators_config.yaml at startup

    @classmethod
    def load_registry(cls, config_path: str) -> None:
        """Load field definitions from indicators_config.yaml."""
        ...

    @staticmethod
    def compute(data_point: DataPoint, tf: int) -> None:
        for field in Indicators._sorted_fields(tf):
            series = field.compute(data_point, tf)
            data_point.get_df(tf)[f"{tf}_{field.name}"] = series
```

**Live path** uses `talib.abstract` for vectorized computation.
**Simulation path** (`WideDataPoint.get_df(tf)` returns `build_indicator_input` slice) uses `pandas_ta`.

### 7.3 Registered fields

Declared in `indicators_config.yaml`. No field list is hardcoded in Python. See [data-module.md §5.2](data-module.md#52-indicatorfield-groups) for the default group summary.

---

## 8. FullData Class

```python
class FullData:
    def __init__(self, df: pd.DataFrame):
        self._df = df

    def get(self, tf: int) -> pd.DataFrame:
        """One row per closed tf-period candle. Columns: {tf}_* only."""
        mask = self._df[f"{tf}_is_closed"]
        tf_cols = [c for c in self._df.columns if c.startswith(f"{tf}_")]
        return self._df.loc[mask, tf_cols]

    def get_candle(self, tf: int, open_time: pd.Timestamp) -> pd.Series:
        """Single closed-candle row for the candle that opened at open_time."""
        mask = (self._df[f"{tf}_open_index"] == open_time) & self._df[f"{tf}_is_closed"]
        return self._df.loc[mask].iloc[0]
```

---

## 9. SimulationData Class

```python
class SimulationData:
    def __init__(self, pair: str, begin_ts: int, end_ts: int, step_min: int):
        path = root_folder() + "/df_with_indicators.pkl"
        self._df = pd.read_pickle(path)
        self._ts_range = pd.date_range(
            start=pd.Timestamp(begin_ts, unit="s"),
            end=pd.Timestamp(end_ts, unit="s"),
            freq=f"{step_min}min"
        )
        self._idx = 0

    def get(self) -> WideDataPoint:
        return WideDataPoint(self._df, self._ts_range[self._idx])

    def next(self) -> None:
        self._idx += 1

    def is_end(self) -> bool:
        return self._idx >= len(self._ts_range)

    @property
    def steps(self) -> int:
        return len(self._ts_range)
```

**Usage:**
```python
sim = SimulationData("link_usdt", begin_ts, end_ts, step_min=1)
while not sim.is_end():
    point = sim.get()                          # WideDataPoint
    rsi = point.get("rsi_14", tf=15)          # partial or complete candle
    rsi_prev = point.get("rsi_14", tf=15, shift=1)  # last closed candle
    sim.next()
```

---

## 10. Singletons

```python
# data.py module scope
item = LiveData(default_pair)   # Live trading singleton
```

`SimulationData` and `FullData` are instantiated per run (not singletons).

---

## 11. Active Timeframes — Config-Driven

```yaml
# candles_config.yaml
candles: [1, 5, 15, 60, 240, 1440]  # minutes
```

Loaded at startup by both `LiveData` and `SimulationData`:

```python
CANDLES = load_candles_config("candles_config.yaml")
```

No timeframe list is hardcoded in Python. To add or remove a timeframe, update `candles_config.yaml` only.

---

## 12. Column Naming Convention

| Example | Meaning |
|---------|---------|
| `5_rsi_14` | RSI-14 on 5-min timeframe |
| `15_move_class` | RSI momentum classification on 15-min |
| `60_tgt_long` | Long target price on 60-min |
| `5_open_index` | 5-min candle open timestamp |
| `5_open` | 5-min candle open price |
| `5_is_closed` | True at the last 1-min row of each 5-min candle |

Live path `ohlc[tf]` DataFrames use **prefixed** column names (e.g. `"5_rsi_14"`, `"5_close"`) consistent with the wide DataFrame format. `LiveDataPoint.get("rsi_14", tf=5)` looks up `ohlc[5]["5_rsi_14"]`.

---

## 13. Error Handling

| Scenario | Handling |
|----------|---------|
| Binance API unavailable | Propagates from `stock.item`; `build_candles` raises |
| Missing stats file | `DataAttributes.load_all` logs and continues; affected fields produce NaN |
| NaN in indicator output | `bfill()` applied by `Indicators.compute` after each field |
| `shift` exceeds data length | Returns `float("nan")` |
| `indicators_config.yaml` missing | Fatal at startup — no fallback; config is required |
| `candles_config.yaml` missing | Fatal at startup — no fallback |
