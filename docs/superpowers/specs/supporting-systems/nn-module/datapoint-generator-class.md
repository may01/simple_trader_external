# DataPointGenerator Class Specification

**Class:** `DataPointGenerator` (Proposed Refactoring)  
**Files:** `trainer.py` (parallel_generate_data_points function, lines 200-350)  
**Purpose:** Generate timestamped data point snapshots containing OHLC candles, technical indicators, signals, and NN targets for training and simulation.

---

## 1. Class Overview

The `DataPointGenerator` class is a proposed refactoring of the current `parallel_generate_data_points()` function in trainer.py. Rather than a standalone function, extracting logic into a dedicated class would improve testability, reusability, and maintainability.

DataPointGenerator's responsibility is to take a time range and produce data point files: one per timestamp containing multi-timeframe OHLC candles, computed indicators, all available signals, and (optionally) NN target classifications. These data points serve as training data for signal evaluation and neural network models.

The class encapsulates the core data generation pipeline: load historical data, iterate timestamps, compute indicators, evaluate signals, optionally run predictor and NN target classification, and persist results to disk.

---

## 2. Key Attributes

### Instance Variables

| Attribute | Type | Description |
|-----------|------|-------------|
| `pair` | `str` | Trading pair (e.g., `link_usdt`) |
| `begin_time` | `int` | Start timestamp (Unix ms) for data generation |
| `end_time` | `int` | End timestamp (Unix ms) for data generation |
| `time_step` | `int` | Minutes between generated data points |
| `data_root` | `str` | Root data folder path from environment |
| `run_predictor` | `bool` | If True, compute price predictions and NN targets; if False, skip |
| `save_candles` | `bool` | If True, persist multi-timeframe candles to disk; if False, skip (optimization for NN-only mode) |
| `progress_bar` | `tqdm` | Progress indicator for user feedback |

---

## 3. Constructor

### `__init__(pair, begin_time, end_time, time_step, run_predictor=False, save_candles=True)`

**Purpose:** Initialize DataPointGenerator with configuration.

**Parameters:**
- `pair` (`str`) — Trading pair (e.g., `link_usdt`)
- `begin_time` (`int`) — Start timestamp (Unix ms)
- `end_time` (`int`) — End timestamp (Unix ms)
- `time_step` (`int`) — Time interval in minutes between points
- `run_predictor` (`bool`) — Enable predictor and NN target computation. Default: False
- `save_candles` (`bool`) — Persist candles to disk. Default: True

**Behavior:**
1. Store all parameters as instance attributes
2. Extract data_root from environment variable `DATA_ROOT`
3. Initialize empty progress bar
4. Load reference OHLC data from `data_root / pair / full / ohlc.pkl`

**Preconditions:**
- Environment variables `DATA_ROOT`, `PAIR` must be set
- Graber data file must exist at `data_root / pair / graber_data.pkl`

**Postconditions:**
- Instance configured and ready to call `generate()`

---

## 4. Key Methods & Interfaces

### `generate(num_threads=1)`

**Purpose:** Generate data points for entire time range.

**Parameters:**
- `num_threads` (`int`) — Number of parallel threads (1 for sequential). Default: 1

**Return Value:** `dict` with keys:
- `"total_points"` — Number of data points generated
- `"start_time"` — Timestamp of first point
- `"end_time"` — Timestamp of last point
- `"errors"` — Count of points that failed processing

**Behavior:**
1. If `num_threads > 1`: Split time range into segments, spawn parallel processes
2. For each segment (or sequentially if single-threaded):
   - Call `generate_segment()`
   - Collect results
3. Merge results from all threads
4. Return summary dict

**Preconditions:**
- Data loaded and valid
- Environment configured

### `generate_segment()`

**Purpose:** Generate data points for a single time segment (sequential).

**Behavior:**

1. **Initialize Data Structures:**
   - Create Data instance for current pair
   - Initialize action storage list
   - Create predictor if `run_predictor=True`

2. **Load Tick Data:**
   - Load raw Binance tick data from `graber_data.pkl`
   - Sort by timestamp

3. **Iterate Time Points:**
   ```
   for timestamp in range(begin_time, end_time, time_step * 60000):
       counter += 1
       if counter % 100 == 0:
           progress_bar.update(100)
   ```

4. **For Each Time Point:**
   - **Load Historical Data:**
     - Subtract 5-day shift for indicator warmup
     - Resample tick data to 1m OHLC
     - For each configured timeframe (1m, 3m, 5m, 15m, 60m, 240m):
       - Extract last 120 candles
       - Resample to timeframe
       - Backfill missing values

   - **Calculate Indicators:**
     - Call `data.calculate_indicators()` for each timeframe
     - Compute RSI, MACD, CCI, Bollinger Bands, ATR, SAR, ADX, etc.

   - **Prepare Candles:**
     - Normalize columns (e.g., compute differences, moving averages)
     - Compute statistical boundaries

   - **Evaluate Signals:**
     - Call signal manager to evaluate all 50+ signals
     - Store signal outputs in action dict

   - **Compute NN Targets (if run_predictor=True):**
     - For each NN target type (0-17):
       - Define future window (e.g., 30-480 minutes ahead)
       - Define expected move threshold (0.8%-varies by target)
       - Call `get_nn_target()` to classify as BUY/SELL/NONE
       - Store target label in `point_target` array

   - **Run Predictor (if run_predictor=True):**
     - Compute next price levels via Gauss modeling
     - Store predictions in action dict

   - **Persist Candles (if save_candles=True):**
     - Save all timeframes to `data_root / pair / data_points / {timestamp} / candles.pkl`

   - **Save Action File:**
     - Serialize signals, targets, predictions to `data_root / pair / data_points / {timestamp} / action.pkl`

5. **Return Results:**
   - Count total points generated
   - Report any errors
   - Return summary dict

---

## 5. State Management

- **Uninitialized:** Just created; no data loaded
- **Configured:** Constructor completed; ready to generate
- **Generating:** `generate()` in progress
- **Complete:** All data points persisted to disk

---

## 6. Error Handling

**Missing Data Files:**
```python
if not os.path.exists(graber_data_path):
    raise FileNotFoundError(f"Graber data not found: {graber_data_path}")
```

**Invalid Timestamps:**
```python
if begin_time >= end_time:
    raise ValueError("begin_time must be < end_time")
```

**Signal Evaluation Error:**
```python
try:
    signals = signal_manager.evaluate_all()
except Exception as e:
    logger.error(f"Signal evaluation failed at {timestamp}: {e}")
    error_count += 1
    continue  # Skip this point
```

---

## 7. Existing Approach (Current Implementation)

Currently, data generation is implemented as:
- `parallel_generate_data_points()` — Worker function for parallel execution
- Direct calls from `Trainer.generate_data_points()`
- Heavy environment variable reading for paths and parameters

The parallel_generate_data_points function:
1. Takes time range, thread ID, flags
2. Processes all points sequentially within segment
3. Saves results to thread-specific pickle files
4. Main thread merges results

### Limitations of Current Approach
- Function-based (harder to reuse, test, extend)
- Environment variable coupling (harder to test with different configs)
- Limited progress reporting (no callback mechanism)
- Tight coupling to Trainer orchestration

---

## 8. Potential Improvements

1. **Add Progress Callbacks**
   - Accept callback function for progress updates
   - Enable real-time monitoring via logging/UI
   - Would improve user feedback

2. **Implement Checkpoint & Resume**
   - Save progress metadata at checkpoints
   - Allow resuming from last checkpoint if interrupted
   - Would save time on long data generation runs

3. **Add Data Validation**
   - Verify candle OHLC invariants (H >= L, close in [L,H])
   - Check for NaN/inf values
   - Would catch data corruption early

4. **Support Streaming Input**
   - Accept tick data via iterator instead of loading all at once
   - Process points as they arrive
   - Would reduce memory footprint

5. **Add Configurable Indicator Selection**
   - Allow selecting subset of indicators to compute
   - Skip expensive computations for rapid prototyping
   - Would improve iteration speed during development

6. **Implement Incremental Caching**
   - Cache computed indicators per candle
   - Reuse when generating overlapping data points
   - Would significantly reduce computation time

7. **Support Multiple Output Formats**
   - CSV export for external analysis
   - Parquet for efficient columnar storage
   - JSON for Web consumption
   - Would improve interoperability

8. **Add Statistical Summaries**
   - Track indicator distributions per timeframe
   - Compute correlation matrices between indicators
   - Would support feature engineering analysis

9. **Implement Data Point Filtering**
   - Skip points that don't meet signal criteria
   - Reduce storage for sparse trading signals
   - Would reduce storage overhead

10. **Add Batch Verification**
    - Verify generated batches match expected distributions
    - Detect anomalies in data generation
    - Would provide quality assurance
