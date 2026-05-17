# DataViewer Class Specification

**Class:** `DataViewer` (Refactoring of view_*.py)  
**Files:** `view_full.py`, `view_point.py`, `view_online.py`  
**Purpose:** Load and provide OHLC candles, signals, levels, and other market data for visualization.

---

## 1. Class Overview

The `DataViewer` class encapsulates data loading logic currently scattered across multiple view_*.py files. It abstracts away file system details, pickle loading, and data normalization, providing a clean interface for dashboards to query historical and live data.

---

## 2. Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `pair` | `str` | Trading pair (e.g., `link_usdt`) |
| `data_root` | `str` | Root data folder path |
| `cache` | `dict` | In-memory cache of loaded data (timeframe → dataframe) |
| `cache_ttl` | `int` | Cache time-to-live in seconds |

---

## 3. Constructor

### `__init__(pair, data_root, enable_cache=True)`

**Parameters:**
- `pair` (`str`) — Trading pair
- `data_root` (`str`) — Data folder path
- `enable_cache` (`bool`) — Cache loaded data. Default: True

**Behavior:**
1. Store parameters
2. Initialize empty cache dict
3. Set cache_ttl to 3600 seconds (1 hour)

---

## 4. Key Methods & Interfaces

### `load_candles(timeframe, begin_time, end_time)`

**Purpose:** Load OHLC candles for timeframe and date range.

**Parameters:**
- `timeframe` (`int`) — Candle size in minutes (1, 3, 5, 15, 60, 240)
- `begin_time` (`int`) — Start timestamp (Unix ms)
- `end_time` (`int`) — End timestamp (Unix ms)

**Return Value:** `pandas.DataFrame` with columns: [open, high, low, close, volume, ...]

**Behavior:**
1. Check cache (if enabled)
2. Load from disk: `{data_root}/pair/full/ohlc_{timeframe}.pkl`
3. Filter to time range
4. Cache result
5. Return dataframe

### `load_signals(timeframe, begin_time, end_time)`

**Purpose:** Load all signal values for time range.

**Parameters:**
- `timeframe` (`int`) — Timeframe
- `begin_time` (`int`) — Start timestamp
- `end_time` (`int`) — End timestamp

**Return Value:** `dict` with signal names → DataFrame

### `load_indicators(timeframe, begin_time, end_time)`

**Purpose:** Load technical indicators.

**Return Value:** `dict` with indicator names → Series

### `load_levels(begin_time, end_time)`

**Purpose:** Load support/resistance levels.

**Return Value:** `Levels` instance with detected levels

### `load_trades(begin_time, end_time)`

**Purpose:** Load executed trades.

**Return Value:** `list[dict]` with trade details: [entry_time, entry_price, exit_time, exit_price, pnl]

### `get_data_point(timestamp)`

**Purpose:** Fetch all data at single timestamp.

**Parameters:**
- `timestamp` (`int`) — Unix timestamp

**Return Value:** `dict` with candles, signals, indicators for all timeframes

### `clear_cache()`

**Purpose:** Clear in-memory cache to free memory.

---

## 5. Error Handling

**File Not Found:**
```python
if not os.path.exists(file_path):
    logger.warning(f"Data file not found: {file_path}")
    return empty_dataframe()
```

**Corrupted Pickle:**
```python
try:
    data = pickle.load(f)
except Exception as e:
    logger.error(f"Failed to load data: {e}")
    return empty_dataframe()
```

---

## 6. Potential Improvements

1. **Add Lazy Loading**
   - Load only visible candles
   - Stream additional data as user scrolls

2. **Implement Compression**
   - Store data compressed
   - Decompress on load

3. **Add Data Validation**
   - Check OHLC invariants
   - Detect missing/corrupt data

4. **Support Multiple Sources**
   - Load from local, remote, or live API
   - Abstract source selection

5. **Add Prefetching**
   - Anticipate which data will be needed
   - Load proactively

6. **Implement Compression**
   - Store data in HDF5 or Parquet
   - Faster I/O

7. **Add Data Streaming**
   - Stream historical data with time delays
   - Simulate live data arrival

8. **Support Incremental Updates**
   - Load only new data since last query
   - Reduce I/O

9. **Add Data Quality Metrics**
   - Report completeness, freshness
   - Flag problematic data

10. **Implement Distributed Caching**
    - Cache across processes
    - Shared memory access
