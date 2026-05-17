# NNPredictor Class Specification

**Class:** `Predictor`  
**File:** `predictor.py` (lines 17-530+)  
**Purpose:** Predict future price levels (high/low/close) for multiple timeframes using Gaussian distribution fitting and caching to reduce redundant computation.

---

## 1. Class Overview

The `Predictor` class complements the NNModel neural network by estimating next-period price levels using statistical methods. Rather than learning from neural network weights, Predictor fits Gaussian distributions to historical price movements and extrapolates to future time windows. This statistical approach provides interpretable confidence scores and captures distributional properties that may be missed by deep learning.

Predictor is designed for efficiency and caching. Predictions are expensive (fitting distributions, computing statistics), so the class caches results per candle index. If the same index is encountered multiple times within a short period, the cached prediction is reused. Additionally, Predictor maintains time-based rate limits per timeframe to prevent redundant fitting when the underlying data hasn't changed substantially.

The class operates in two modes:
1. **Training Mode:** Computes both predicted and actual future prices for model validation
2. **Inference Mode:** Returns predictions only

---

## 2. Key Attributes

### Class Variables

| Attribute | Type | Description |
|-----------|------|-------------|
| `data` | `data.Data` | Current OHLC data for the active time point. Updated via `set_data()`. |
| `full_data` | `data.Data` | Complete historical data. In training mode, reloaded per point; in inference, set once. |

### Instance Variables

| Attribute | Type | Description |
|-----------|------|-------------|
| `train` | `bool` | Training mode flag. If True, compute actual future prices for backtesting. |
| `type_list` | `list[str]` | Price types to predict: `["high", "low", "close"]` |
| `cur_point` | `dict` | Current point data structure (not actively used; legacy). Dict per timeframe. |
| `next_point` | `dict` | Predicted next-period price deltas. Keys: timeframes; values: dicts with "high", "low", "close", score fields. |
| `cur_levels` | `dict` | Cached next-period price levels (absolute prices). Keys: timeframes; values: level dicts with h, l, c, buy_price, sell_price. |
| `future_fact` | `dict` | Actual future price deltas (training only). Keys: timeframes; values: realized price changes. |
| `next_fact_point` | `dict` | Actual next-period prices (legacy; not actively used). |
| `point_sample` | `dict` | Template for point data. Keys: "high", "low", "close", "score", "buy_price", "sell_price", "type", "valid". |
| `level_point_sample` | `dict` | Template for level data. Keys: "high", "low", "close", "buy_price", "sell_price". |
| `tmp_points` | `dict` | Temporary storage for predictions before caching. Used for deduplication. |
| `tmp_limit` | `dict` | Call limits per timeframe to prevent redundant computation: {15: 5, 60: 10, 240: 30}. |
| `tmp_counter` | `dict` | Call counter per timeframe. Increments each call; resets when limit reached. |
| `last_update` | `dict` | Last update index per timeframe. Used for rate limiting. Keys: [15, 60, 240] (configured timeframes). |
| `prediction_cache` | `dict` (implicit) | Passed as parameter; stores {timeframe: {"index": candle_index, "val": level_dict}}. External cache. |

---

## 3. Constructor

### `__init__(train)`

**Purpose:** Initialize a Predictor instance with training mode configuration.

**Parameters:**
- `train` (`bool`) — If True, operate in training mode (compute actual prices); if False, inference mode only

**Behavior:**
1. Initialize `point_sample` dict with template fields: "high", "low", "close", "score" (dict), "buy_price", "sell_price", "type", "valid"
2. Initialize `level_point_sample` dict with template: "high", "low", "close", "buy_price", "sell_price"
3. Initialize `tmp_points` dict (empty)
4. Set time limits per timeframe: {15: 5, 60: 10, 240: 30}
5. Initialize counter per timeframe: {15: 0, 60: 0, 240: 0}
6. Set monitoring timeframes: {15: 0, 60: 0, 240: 0} (last_update)
7. Store `train` flag
8. For each monitored timeframe:
   - Initialize `cur_levels[t]` with `level_point_sample.copy()`
   - Initialize `next_point[t]`, `cur_point[t]`, `future_fact[t]`, `next_fact_point[t]` with `point_sample.copy()`
9. Set `type_list = ["high", "low", "close"]`

**Preconditions:**
- None (constructor has no external dependencies)

**Postconditions:**
- Instance is initialized with empty data
- Ready to accept data via `set_data()` and then compute predictions

**Example:**
```python
predictor_train = Predictor(train=True)   # Training mode
predictor_inference = Predictor(train=False)  # Inference mode
```

---

## 4. Key Methods & Interfaces

### 4.1 Data Configuration

#### `set_data(data, full_data)`

**Purpose:** Configure predictor with current and historical data references.

**Parameters:**
- `data` (`data.Data`) — Current OHLC data (at active time point)
- `full_data` (`data.Data`) — Complete historical OHLC data

**Behavior:**
1. Store `data` as `self.data`
2. If in training mode:
   - Reset `self.full_data` to fresh Data instance for configured pair
   - Load full candles from disk ("full" folder)
3. Else (inference mode):
   - Store `full_data` reference as-is (pre-loaded by caller)

**Returns:** `None`

**Preconditions:**
- `data` and `full_data` must be initialized Data instances
- In training mode, full data must be available on disk

**Postconditions:**
- Predictor has references to both current and historical data
- Ready to call `calc()`

### 4.2 Prediction Computation

#### `calc(save_data, action, prediction_cache)`

**Purpose:** Compute next-period price predictions via Gaussian modeling; cache results; optionally save to disk.

**Parameters:**
- `save_data` (`bool`) — If True, persist predictions to disk
- `action` (Action) — Action object for recording prediction events (legacy; not heavily used)
- `prediction_cache` (`dict`) — Cache dict: {timeframe: {"index": last_index, "val": level_dict}}. Updated in-place.

**Behavior:**

1. **Check Cache:**
   - Call `load(action)` to attempt loading cached predictions
   - If cached and valid: return early (predictions already available)
   - Cache key: current index in data
   - If index matches cached index: log "Use cache prediction" and continue to load predictions

2. **Compute Predictions (if not cached):**
   - For each monitored timeframe (15m, 60m, 240m):
     - Check prediction_cache[t] for index match
     - If match: use cached level, continue to next timeframe
     - Else: compute fresh prediction:

3. **Per-Timeframe Gaussian Prediction:**
   - For each price type (high, low, close):
     - Try loading Gauss predictor model from disk via `gauss_predictor.load_model()`
     - If not found: train new Gauss on historical data via `gauss_predictor.train()`
     - Save trained model via `gauss_predictor.save_model()`
     - Predict next delta: `gauss_predictor.predict()` → (price_delta, confidence_score)
     - Store in `next_point[t][type]` and `next_point[t]["score_" + type]`
     - Store current price delta in `cur_point[t][type]`

4. **Convert to Absolute Levels:**
   - Get previous close, high, low prices from 1-candle lookback
   - Compute absolute prices:
     ```
     h = h_prev * (1 + predicted_delta_high)
     l = l_prev * (1 + predicted_delta_low)
     c = c_prev * (1 + predicted_delta_close)
     ```
   - Compute buy/sell prices: `buy_price = get_buy_price(t, c, l)`, `sell_price = get_sell_price(t, c, h)`

5. **Validate Prediction:**
   - Check if current price is within predicted range: `l < cur_price < h`
   - Set `valid` flag accordingly

6. **Store Prediction:**
   - Update `cur_levels[t]` with computed h, l, c, buy_price (with validity), sell_price (with validity)
   - Update cache: `prediction_cache[t]["index"] = current_index`, `prediction_cache[t]["val"] = cur_levels[t].copy()`

7. **Training Mode (if train=True):**
   - Call `get_fact_data(t)` to load actual future prices and compute realized deltas
   - Store in `future_fact[t]`

8. **Persistence:**
   - If `save_data=True`: call `save()` to persist predictions to disk

**Returns:** `None`

**Preconditions:**
- Data must be set via `set_data()`
- Gauss models must be trainable or loadable from disk
- `prediction_cache` dict must be pre-initialized by caller

**Postconditions:**
- `cur_levels` populated with next-period predictions
- `next_point` populated with price deltas and scores
- `prediction_cache` updated with current predictions
- Predictions available for strategy use

### 4.3 Fact Data (Training Only)

#### `get_fact_data(t)`

**Purpose:** Load actual future price from full data for training validation.

**Parameters:**
- `t` (`int`) — Timeframe (15, 60, 240)

**Behavior:**
1. For each price type (high, low, close):
   - Get current price from `self.data.get_cur_price(type, 0)` (1m close)
   - Get future price from `self.full_data.get_cur_price(type, 0)` (at future timestamp)
   - Compute realized delta: `(future_price / cur_price) - 1`
   - Store in `future_fact[t][type]`

**Returns:** `None`

**Preconditions:**
- In training mode (`self.train = True`)
- `full_data` must be loaded with complete future data

**Postconditions:**
- `future_fact[t]` updated with actual price changes

### 4.4 Price Level Derivation

#### `get_derived_data(t)`

**Purpose:** Compute buy/sell prices and period type from predictions (legacy; partially used).

**Parameters:**
- `t` (`int`) — Timeframe

**Behavior:**
1. Convert predictions to current-price-relative format via `recalc_prediction_to_cur_price()`
2. Classify period type based on position within predicted range:
   - position = (c - l) / (h - l)
   - If position < 0.30: PERIOD_TYPE_LOW
   - If position > 0.70: PERIOD_TYPE_HIGH
   - Else: PERIOD_TYPE_NEUTRAL
3. Store type in `next_point[t]["type"]`

#### `get_buy_price(t, c, l)`

**Purpose:** Compute recommended buy price (long entry).

**Parameters:**
- `t` (`int`) — Timeframe
- `c` (float) — Predicted close price
- `l` (float) — Predicted low price

**Return Value:** `float` — Buy price (slightly below predicted low for safety)

#### `get_sell_price(t, c, h)`

**Purpose:** Compute recommended sell price (short entry).

**Parameters:**
- `t` (`int`) — Timeframe
- `c` (float) — Predicted close price
- `h` (float) — Predicted high price

**Return Value:** `float` — Sell price (slightly above predicted high for safety)

### 4.5 Persistence

#### `save()`

**Purpose:** Persist predictions to disk (legacy; rarely used in current implementation).

**Behavior:**
1. Serialize `next_point`, `future_fact`, etc. to pickle
2. Save to data folder with timestamp key

#### `load(action)`

**Purpose:** Load cached predictions from disk.

**Parameters:**
- `action` (Action) — Action object (legacy)

**Return Value:** `bool` — True if successfully loaded from cache; False if not cached

**Behavior:**
1. Check if predictions already cached in memory
2. Attempt to load from disk if available
3. Return True if loaded, False if fresh computation needed

---

## 5. State Management

### Prediction State
- **Uninitialized:** No data set; all dicts empty
- **Data Configured:** `set_data()` called; ready to compute
- **Computed:** `calc()` called; `cur_levels`, `next_point` populated
- **Cached:** Predictions stored in `prediction_cache` for reuse

### Cache Behavior
- **Hit:** Same candle index; return cached level immediately
- **Miss:** New index; recompute Gaussian, update cache
- **Rate Limiting:** Timeframe-based counter prevents fitting on every call

---

## 6. Error Handling

**Missing Gauss Model:**
If Gauss model doesn't exist, predictor trains on the fly:
```python
if not gauss_predictor.load_model(...):
    gauss_predictor.train(...)
    gauss_predictor.save_model(...)
```

**Prediction Outside Valid Range:**
If current price not within [l, h], `valid` flag is False. Strategy can use this to reject prediction.

**Missing Full Data (Training):**
In training mode, if full_data not loaded, `get_fact_data()` fails. Should fail early with meaningful error.

---

## 7. Existing Approach

### Gaussian-Based Price Prediction

Rather than time-series forecasting (ARIMA, etc.), Predictor uses:
1. Fit normal distribution to historical price deltas (e.g., last 100 candles)
2. Estimate next delta from distribution parameters
3. Confidence score from distribution's PDF at predicted value

This approach:
- Captures trend-agnostic volatility patterns
- Provides natural confidence intervals
- Is fast to compute (no iterative fitting)
- Complements NN-based learning (different model family)

### Caching with Index-Based Keys

Predictions are cached by candle index:
```python
cache_val["index"] = cur_index
cache_val["val"] = cur_levels[t].copy()
```

Allows efficient reuse when multiple strategies query same timeframe within same candle.

### Time-Based Rate Limiting

Per-timeframe counters prevent redundant fitting:
```python
if self.tmp_counter[t] < self.tmp_limit[t]:
    # Increment counter, reuse last fit
else:
    # Reset counter, fit new model
```

Balances accuracy (refitting on new data) vs. efficiency (amortizing fit cost).

### Dual-Mode Operation

Same class supports both training and inference:
- **Training:** Computes both predicted and actual prices for model validation and backtesting
- **Inference:** Computes predictions only (faster path)

Flag-based branching minimizes code duplication.

---

## 8. Potential Improvements

1. **Add Multiple Distribution Fitting**
   - Fit multiple distributions (normal, lognormal, student-t)
   - Select best fit via information criteria
   - Would improve prediction accuracy on non-normal data

2. **Implement EWMA (Exponential Weighted Moving Average)**
   - Weight recent candles more heavily than distant ones
   - Adapt to trend changes faster
   - Would reduce lag in trending markets

3. **Add Seasonality Detection**
   - Detect time-of-day or day-of-week patterns
   - Adjust predictions based on discovered seasonality
   - Would capture periodic market behaviors

4. **Support Multiple Lookback Windows**
   - Train separate models on 20, 50, 100-candle windows
   - Ensemble predictions across windows
   - Would improve robustness to time-scale changes

5. **Implement Volatility Clustering**
   - Use GARCH-style models to predict volatility
   - Combine with price prediction for confidence intervals
   - Would provide dynamic uncertainty estimates

6. **Add Online Learning**
   - Incrementally update Gaussian parameters as new data arrives
   - Avoid expensive full retraining
   - Would support continuous model refinement

7. **Implement Mean Reversion Detection**
   - Identify when price deviates beyond 2σ from predicted level
   - Issue alerts for potential reversion trades
   - Would enable swing trading signals

8. **Support Multivariate Prediction**
   - Jointly model (high, low, close) instead of independently
   - Capture correlations between price levels
   - Would reduce prediction inconsistencies (e.g., close > high)

9. **Add Prediction Confidence Metrics**
   - Track historical prediction accuracy per timeframe
   - Compute dynamic confidence scores
   - Would enable strategy to adjust position sizing by prediction quality

10. **Implement Portfolio-Level Caching**
    - Cache predictions across multiple pairs
    - Shared cache backend (Redis) for multi-process access
    - Would reduce computational overhead in multi-pair systems
