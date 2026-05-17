# BaseSignal Class Specification

## 1. Class Overview

The `BaseSignal` class is an **abstract base class defining the interface for all signal types** in the pybtctr2 framework. All signal implementations (atomic signals, combinators, complex patterns, candle signals) must inherit from BaseSignal and implement its core methods.

**Responsibilities:**
- Define the abstract interface (`check()`, `reset()`, `get_data()`, `get_marker_pos()`)
- Provide base attributes (`shift` for historical offset)
- Enable recursive shift propagation for composable signals
- Serve as type anchor for type checking and polymorphism

**Design Pattern:** Abstract base class with pure virtual methods. Enforces contract for all signal subtypes.

**Key Principle:** Signals are **stateless evaluators** that answer "does this condition hold?" They do not maintain execution state; that's SignalChain's responsibility.

---

## 2. Key Attributes

| Attribute | Type | Purpose | Default/Range | Notes |
|-----------|------|---------|----------------|-------|
| `shift` | int | Historical lookback offset | 0 at init | 0 = current candle, 1 = previous, 2 = 2 back, etc. |
| `tf` | int | Timeframe (if used by signal) | Optional | 1, 5, 15, 60, 240, 1440 minutes (varies by subclass) |

### Notes on Attributes

**`shift` (Historical Offset)**
- **0**: Evaluate at current candle (present)
- **1**: Evaluate at previous candle (1 bar ago)
- **2**: Evaluate at 2 candles ago
- **N**: Evaluate at N candles ago
- **Usage**: Enables time-series lookback without duplicating signals
- **Propagation**: Compositors like `History_Signal` and `Continuous_Signal` set shift before evaluating child signals
- **Access**: Signals use `data_point.get(col, tf, self.shift)` to retrieve offset values

**`tf` (Timeframe)**
- **Purpose**: Indicates which timeframe candles the signal evaluates
- **Scope**: Not all signals use `tf` (combinators may not)
- **Common values**: 1, 5, 15, 60, 240, 1440 minutes (loaded from `candles_config.yaml`)
- **Multi-timeframe**: Some signals evaluate across multiple timeframes

---

## 3. Constructor (`__init__`)

### Signature
```python
def __init__(self) -> None
```

### Parameters
- None

### Initialization Steps
1. Initialize `self.shift = 0` (no historical offset by default)

### Postconditions
- Signal is ready to evaluate via `check()`
- `shift` is 0 (current candle only)

### Exceptions
- None; constructor is simple

### Usage in Subclasses
Subclasses typically call `super().__init__()` and add their own parameters:

```python
class Greater_Signal(BaseSignal):
    def __init__(self, tf, indi_1, indi_2):
        super().__init__()
        self.tf = tf
        self.indi_1 = indi_1
        self.indi_2 = indi_2
```

---

## 4. Abstract Methods (Must Override)

### 4.1 `check(data, levels, action)`

#### Signature
```python
def check(self, data, levels, action) -> bool
```

#### Purpose
Evaluate signal condition at current tick. Return True if signal fires (condition holds), False otherwise.

#### Parameters
- **`data_point`** (DataPoint): Path-agnostic data access protocol. Exposes both live (`LiveDataPoint`) and simulation (`WideDataPoint`) data via the same interface
  - Access prices/indicators: `data_point.get(col, tf, shift)`
  - `col`: column name without tf prefix (e.g. `"rsi_14"`, `"close"`, `"ema_25"`)
  - `tf`: timeframe in minutes (from `CANDLES` config)
  - `shift=0`: current value (partial candle if mid-period); `shift=N (N>0)`: Nth last completed candle
  - Example: `data_point.get("rsi_14", 15, 1)` → RSI-14 at last closed 15m candle
  
- **`levels`** (Levels): Support/resistance levels object
  - Access detected levels: `levels.get_level(type, time_type)` or similar
  - Used by level-based signals (Near_Level_Signal, Level_Cross_UP_Signal, etc.)
  
- **`action`** (Action): Action object (for compatibility; rarely used in check)
  - Used for logging/notifications in some signals
  - Typically unused in atomic signals

#### Return Value
- **bool**: True if signal condition is satisfied (signal fires), False otherwise
  - **True** → SignalChain increments `cur_pos` and advances to next signal
  - **False** → SignalChain stays on current signal, evaluates again next tick

#### Implementation Requirements
- **Deterministic**: Same input always produces same output
- **Stateless**: No internal state modifications; pure evaluator
- **Efficient**: Single evaluation per tick (no loops over historical data unless necessary)
- **Safe**: Handle missing data gracefully (NaN values, empty data frames)

#### Default Implementation (Abstract)
```python
def check(self, data_point, levels, action):  # In BaseSignal
    assert False  # Must be overridden
```

#### Subclass Examples

**Atomic Comparison:**
```python
class Greater_Signal(BaseSignal):
    def __init__(self, tf, indi_1, indi_2):
        super().__init__()
        self.tf = tf
        self.indi_1 = indi_1
        self.indi_2 = indi_2
    
    def check(self, data_point, levels, action):
        val_1 = data_point.get(self.indi_1, self.tf, self.shift)
        val_2 = data_point.get(self.indi_2, self.tf, self.shift)
        return val_1 > val_2
```

**Crossover:**
```python
class Cross_Up_Signal(BaseSignal):
    def check(self, data_point, levels, action):
        # Current: indi_1 > indi_2
        cur = data_point.get(self.indi_1, self.tf, self.shift) > \
              data_point.get(self.indi_2, self.tf, self.shift)
        # Previous closed candle: indi_1 < indi_2
        prev = data_point.get(self.indi_1, self.tf, self.shift + 1) < \
               data_point.get(self.indi_2, self.tf, self.shift + 1)
        return cur and prev
```

**Level-Based:**
```python
class Near_Level_Signal(BaseSignal):
    def check(self, data_point, levels, action):
        level = levels.get_level(self.level_type, self.level_time_type)
        price = data_point.get("close", self.tf, self.shift)
        return abs(price - level) <= self.buffer
```

#### Preconditions
- `data` has indicator values for requested timeframe/shift
- `levels` object is valid

#### Postconditions
- No state change; purely evaluative

#### Exceptions
- Should not raise; should gracefully handle missing data (return False or cached value)

---

### 4.2 `reset()`

#### Signature
```python
def reset(self) -> bool
```

#### Purpose
Request chain reset/abort. Return True to reset the parent SignalChain to `cur_pos = 0`, aborting the sequence.

#### Return Value
- **bool**:
  - **True** → Parent chain should reset (abort sequence)
  - **False** → No reset requested; sequence continues

#### Default Implementation
```python
def reset(self):
    return False  # Default: never request reset
```

#### Usage Pattern
In SignalChain.check():
```python
def check(self, data_point, levels, cur_time, action):
    if self.cur_pos < len(self.signals):
        if self.signals[self.cur_pos].check(data_point, levels, action):
            self.cur_pos += 1
    
    # Check for reset request
    if self.cur_pos < len(self.signals):
        if self.signals[self.cur_pos].reset():  # Call reset() on current signal
            self.reset(action)  # Reset chain to cur_pos = 0
```

#### Subclass Examples

**Simple Signal (No Reset):**
```python
class Greater_Signal(BaseSignal):
    def reset(self):
        return False  # Never resets
```

**Stop-Loss Signal (Reset on Violation):**
```python
class Stop_Loss_Signal(BaseSignal):
    def reset(self):
        # If price falls below stop level, abort the sequence
        # Note: reset() has no data_point argument — use stateful check() to cache price
        stop_level = self.entry_price * (1 - self.stop_loss_pct)
        return self._last_price < stop_level
```

**Timeout Signal:**
```python
class Timeout_Signal(BaseSignal):
    def reset(self):
        # Reset if signal took too long to fire
        return self.time_elapsed > 300  # 5 minutes
```

#### Preconditions
- Signal has been in evaluation for at least one tick
- Signal's state (if any) is consistent

#### Postconditions
- No state modification; purely informational

#### Exceptions
- None; should not raise

---

### 4.3 `get_data()`

#### Signature
```python
def get_data(self) -> dict
```

#### Purpose
Return signal-specific metadata that will be included in the action when chain completes.

#### Return Value
**dict**: Key-value pairs to be merged into action metadata.

#### Default Implementation
```python
def get_data(self):
    return {}  # Empty dict; no metadata
```

#### Usage Pattern
SignalChain aggregates metadata when action completes:
```python
def get_action(self, price, action):
    data = {"position_time": self.tf}
    for s in self.signals:
        data.update(s.get_data())  # Merge each signal's metadata
    return [self.result_action, self.tf, price, data]
```

#### Subclass Examples

**Level-Based Signal (Export Level Info):**
```python
class Near_Level_Signal(BaseSignal):
    def get_data(self):
        return {
            "level_name": self.level_type,
            "level_val": self.detected_level,
            "level_time_type": self.level_time_type
        }
```

**SAR Signal (Export SAR Value):**
```python
class SAR_Up_Signal(BaseSignal):
    def get_data(self):
        # Note: get_data() has no data_point arg — cache value during check() if needed
        return {
            "sar_val": self._cached_sar_val,  # set during check()
            "sar_direction": "up"
        }
```

**Complex Pattern (Export Pattern Markers):**
```python
class Diver_Bull_Signal(BaseSignal):
    def get_data(self):
        return {
            "diver_type": "bullish",
            "diver_level": self.level,
            "diver_indicator": self.indicator,
            "peak_idx": self.peak_idx,
            "trough_idx": self.trough_idx
        }
```

**Combinator (Propagate Child Data):**
```python
class And_Signal(BaseSignal):
    def get_data(self):
        result = {}
        for child_signal in self.signals:
            result.update(child_signal.get_data())  # Merge all children
        return result
```

#### Preconditions
- Signal has fired (check() returned True at some point)
- All internal state is consistent

#### Postconditions
- No state change; purely informational

#### Exceptions
- None; should not raise

#### Data Flow to Strategy
Returned metadata is used by Strategy layer to:
- Set stop-loss levels
- Initialize position size
- Log trade reasons
- Validate entry conditions

---

### 4.4 `get_marker_pos(data)`

#### Signature
```python
def get_marker_pos(self, data: Data) -> float
```

#### Purpose
Return a price level for logging/visualization (chart marker). Used to pinpoint where signal fired on the chart.

#### Parameters
- **`data_point`** (DataPoint): DataPoint protocol for accessing current prices

#### Return Value
**float**: Price level (usually close, high, low, or indicator value) used as marker position on chart.

#### Default Implementation
```python
def get_marker_pos(self, data_point):
    return data_point.get("close", 1, 1)  # 1-min tf, last closed candle
```

#### Subclass Examples

**Close Price Signal:**
```python
class Greater_Signal(BaseSignal):
    def get_marker_pos(self, data_point):
        return data_point.get("close", self.tf, 1)
```

**High/Low Levels:**
```python
class Peak_High_Signal(BaseSignal):
    def get_marker_pos(self, data_point):
        return data_point.get("high", self.tf, 1)  # Mark the high

class Peak_Low_Signal(BaseSignal):
    def get_marker_pos(self, data_point):
        return data_point.get("low", self.tf, 1)  # Mark the low
```

**Indicator Value:**
```python
class SAR_Up_Signal(BaseSignal):
    def get_marker_pos(self, data_point):
        return data_point.get("sar", self.tf, 1)  # Mark SAR level
```

**Level Position:**
```python
class Near_Level_Signal(BaseSignal):
    def get_marker_pos(self, data_point):
        return self.detected_level  # Mark the support/resistance level itself
```

**Predictive:**
```python
class Prediction_Normal_Signal(BaseSignal):
    def get_marker_pos(self, data_point):
        return data_point.get("tgt_long", self.tf, 0)  # Mark predicted target level
```

#### Usage
```python
# In SignalChain.check()
if self.notify:
    action.add_multiply_action(
        self.signals[self.cur_pos].get_marker_pos(data_point),
        "SF: C %s S %d" % (self.name, self.cur_pos)
    )
```

#### Preconditions
- Signal has fired (or is about to fire) at data point
- `data` is valid and has necessary prices

#### Postconditions
- No state change; purely informational

#### Exceptions
- None; should not raise

---

## 5. Helper Methods

### 5.1 `set_shift(shift)`

#### Signature
```python
def set_shift(self, shift: int) -> None
```

#### Purpose
Update the historical lookback offset. Used by temporal compositors (History_Signal, Continuous_Signal) to evaluate signals at different points in history.

#### Parameters
- **`shift`** (int): New offset value (0 = current, 1 = previous, etc.)

#### Implementation
```python
def set_shift(self, shift):
    self.shift = shift
```

#### Behavior
- Sets `self.shift` to the specified value
- Affects how `check()` retrieves data: `data_point.get(col, tf, self.shift)`

#### Recursive Propagation
Combinators override `set_shift()` to propagate recursively to child signals:

```python
class And_Signal(BaseSignal):
    def set_shift(self, shift):
        self.shift = shift
        for child_signal in self.signals:
            child_signal.set_shift(shift)  # Propagate to children
```

#### Usage Example
```python
# Evaluate "Greater_Signal" at previous closed candle
signal = Greater_Signal(15, "rsi_14", 50)
signal.set_shift(1)  # Look back 1 closed candle
result = signal.check(data_point, levels, action)  # Evaluates: rsi_14[prev closed] > 50
```

#### Preconditions
- Signal instance is already created

#### Postconditions
- All subsequent `check()` calls use new shift value
- Child signals (if combinator) updated recursively

#### Exceptions
- None

---

## 6. Signal Types & Categories

### 6.1 Atomic Signals (Basic Comparisons)

**Purpose:** Evaluate single conditions

**Examples:**
- `Greater_Signal(tf, indi_1, indi_2)`: `indi_1 > indi_2`
- `Less_Signal(tf, indi_1, indi_2)`: `indi_1 < indi_2`
- `Greater_Val_Signal(tf, indi, val)`: `indi > val`
- `Less_Val_Signal(tf, indi, val)`: `indi < val`

**Subclass Pattern:**
```python
class Greater_Signal(BaseSignal):
    def __init__(self, tf, indi_1, indi_2):
        super().__init__()
        self.tf = tf
        self.indi_1 = indi_1
        self.indi_2 = indi_2
    
    def check(self, data_point, levels, action):
        val_1 = data_point.get(self.indi_1, self.tf, self.shift)
        val_2 = data_point.get(self.indi_2, self.tf, self.shift)
        return val_1 > val_2
    
    def get_data(self):
        return {"greater_indi_1": self.indi_1, "greater_indi_2": self.indi_2}
```

---

### 6.2 Combinators (Logical & Temporal Operations)

**Purpose:** Compose atomic signals into complex conditions

**Boolean Combinators:**
- `And_Signal(signals[])`: All conditions must be true
- `Or_Signal(signals[])`: Any condition true
- `Not_Signal(signal)`: Negation

**Temporal Combinators:**
- `History_Signal(signal, shift)`: Evaluate at historical offset
- `Continuous_Signal(signal, history, multiply)`: Count occurrences

**Subclass Pattern (And_Signal):**
```python
class And_Signal(BaseSignal):
    def __init__(self, signals):
        super().__init__()
        self.signals = signals
    
    def check(self, data_point, levels, action):
        return all(s.check(data_point, levels, action) for s in self.signals)
    
    def reset(self):
        return any(s.reset() for s in self.signals)
    
    def set_shift(self, shift):
        self.shift = shift
        for s in self.signals:
            s.set_shift(shift)  # Recursive propagation
    
    def get_data(self):
        result = {}
        for s in self.signals:
            result.update(s.get_data())  # Merge all children
        return result
```

---

### 6.3 Complex Signals (Multi-Indicator Patterns)

**Purpose:** Detect specific technical patterns

**Examples:**
- `Diver_Bull_signal(tf, level, cancel_level, indicator)`: Bullish divergence
- `Diver_Bear_signal(tf, level, cancel_level, indicator)`: Bearish divergence
- `Bounce_Signal()`: Price bounce off level
- `Peak_High_Signal(tf, level, indicator, hist)`: Local maximum

**Subclass Pattern (Divergence):**
```python
class Diver_Bull_signal(BaseSignal):
    def __init__(self, tf, level, cancel_level, indicator, finished=True):
        super().__init__()
        self.tf = tf
        self.level = level
        self.cancel_level = cancel_level
        self.indicator = indicator
        self.finished = finished
    
    def check(self, data, levels, action):
        # Price makes lower low, indicator makes higher low
        # Returns True if divergence detected
        # Detailed pattern matching logic here
        return <divergence_detected>
```

---

### 6.4 Candle Pattern Signals

**Purpose:** Analyze candle structure (OHLC)

**Examples:**
- `BigCandle_Signal(tf, coef)`: Large candle relative to MA
- `LongTale_Signal(tf, type)`: Long wick in direction
- `CandleUP_Signal(tf)`: Bullish candle
- `CandleDOWN_Signal(tf)`: Bearish candle

**Subclass Pattern:**
```python
class BigCandle_Signal(BaseSignal):
    def __init__(self, tf, coef):
        super().__init__()
        self.tf = tf
        self.coef = coef
    
    def check(self, data_point, levels, action):
        natr = data_point.get("natr_14", self.tf, self.shift)
        natr_ma = data_point.get("atr_ma", self.tf, self.shift)
        return natr > self.coef * natr_ma
```

---

## 7. Existing Approach

### Stateless Signal Evaluation
- Signals are **pure functions** (same input → same output)
- No internal state maintained between ticks
- State managed by parent SignalChain instead
- Enables signal reuse across multiple chains

### Shift-Based Historical Access
- Instead of storing N previous values, signals use `shift` parameter
- `set_shift()` enables temporal composition without duplicating signal code
- Example: Single `Greater_Signal` instance evaluated at shift=0, 1, 2, 3, ... via `History_Signal`

### Recursive Shift Propagation
- Combinators override `set_shift()` to propagate to children
- Enables: `History_Signal(And_Signal([sig1, sig2]), 1)` → evaluate both children at shift=1
- **Decorator pattern**: History_Signal wraps original signal

### Metadata Aggregation
- Each signal exports metadata via `get_data()`
- Parent chain merges all signals' metadata
- Enables signal composition without data loss

### Polymorphic Evaluation
- All signals inherit from BaseSignal
- SignalChain calls `signal.check()` without knowing concrete type
- Enables 50+ signal types in single list

---

## 8. Potential Improvements

### 1. Caching & Memoization
**Current:** Each call to `check()` re-evaluates from scratch.
**Future:** Cache results per data point to avoid redundant calculations.
```python
class Greater_Signal(BaseSignal):
    def __init__(self, tf, indi_1, indi_2):
        super().__init__()
        self.tf = tf
        self.indi_1 = indi_1
        self.indi_2 = indi_2
        self.cache = {}  # {(shift, data_point): result}
    
    def check(self, data_point, levels, action):
        # Note: no cur_point on DataPoint — use id(data_point) as cache key
        cache_key = (self.shift, id(data_point))
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        val_1 = data_point.get(self.indi_1, self.tf, self.shift)
        val_2 = data_point.get(self.indi_2, self.tf, self.shift)
        result = val_1 > val_2
        
        self.cache[cache_key] = result
        return result
```

**Benefit:** 10-50x faster backtesting for repeated signal evaluation.

### 2. Confidence Scores
**Current:** Binary signal (True/False).
**Future:** Return confidence score (0.0 to 1.0).
```python
def check(self, data_point, levels, action) -> tuple:
    val_1 = data_point.get(self.indi_1, self.tf, self.shift)
    val_2 = data_point.get(self.indi_2, self.tf, self.shift)
    diff = abs(val_1 - val_2)
    confidence = min(diff / 10.0, 1.0)  # Scale to [0, 1]
    return (val_1 > val_2, confidence)
```

**Benefit:** Strategy can filter weak signals.

### 3. Async Signal Evaluation
**Current:** Sequential evaluation.
**Future:** Parallel evaluation for 50+ signals via thread pool.
```python
from concurrent.futures import ThreadPoolExecutor

def evaluate_all(self, data_point, levels, action):
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(s.check, data_point, levels, action) 
                   for s in self.signals]
        return [f.result() for f in concurrent.futures.as_completed(futures)]
```

**Benefit:** Faster evaluation on multi-core systems.

### 4. Signal Dependencies & Validation
**Current:** No validation of signal composition.
**Future:** Detect invalid combinations (e.g., two conflicting signals).
```python
class BaseSignal:
    def get_requirements(self):
        # Return set of required indicators
        return set()
    
    def validate(self):
        # Check if signal is valid in current context
        return True
```

**Benefit:** Catch configuration errors early.

### 5. Dynamic Signal Parameters
**Current:** Parameters fixed at initialization.
**Future:** Adjust thresholds based on market conditions.
```python
class Greater_Val_Signal(BaseSignal):
    def __init__(self, tf, indi, val):
        super().__init__()
        self.tf = tf
        self.indi = indi
        self.val = val  # Can be updated
    
    def update_threshold(self, new_val):
        self.val = new_val
```

**Benefit:** Adaptive signal tuning.

### 6. Signal Versioning
**Current:** Single implementation per signal.
**Future:** Support multiple versions with different algorithms.
```python
class Cross_Up_Signal_v2(BaseSignal):
    # Improved version with smoother crossover detection
    def check(self, data, levels, action):
        # Better algorithm
```

**Benefit:** A/B testing of signal variants.

### 7. Streaming/Online Evaluation
**Current:** Batch evaluation (all data loaded at start).
**Future:** Online mode for live trading (incremental updates).
```python
class BaseSignal:
    def on_bar_close(self, ohlc):
        # Called when new bar closes
        self._update_state()
        return self.check(...)
```

**Benefit:** Real-time signal streaming.

---

## 9. Integration Notes

### With SignalChain
- SignalChain calls `check()`, `reset()`, `get_data()`, `get_marker_pos()`, `set_shift()`
- Does not directly manipulate signal internals
- Relies on signal to maintain no state (pure function behavior)

### With Data & Levels
- Signals call `data_point.get(col, tf, shift)` and `levels.get_level()`
- Access is read-only; no modifications
- Shift parameter enables historical lookback via `data_point.get()` shift argument

### With Strategy Layer
- Signals provide metadata via `get_data()` used by strategy
- Strategy examines aggregated action data to make decisions

### With Combinators
- Combinators (And_Signal, Or_Signal, History_Signal) treat child signals as BaseSignal instances
- Rely on polymorphic dispatch for `check()`, `reset()`, `set_shift()`

---

## 10. File Manifest

| File | Location | Content |
|------|----------|---------|
| Source | `signals_lib/base_signal.py` | BaseSignal class (abstract interface) |
| Implementations | `signals_lib/common.py` | Atomic signals (Greater_Signal, Cross_Up_Signal, etc.) |
| Implementations | `signals_lib/operations.py` | Combinators (And_Signal, Or_Signal, History_Signal, etc.) |
| Implementations | `signals_lib/complex.py` | Complex patterns (Diver_Bull_signal, etc.) |
| Implementations | `signals_lib/candle.py` | Candle signals (BigCandle_Signal, LongTale_Signal, etc.) |
| Implementations | `signals_lib/nn_signals.py` | Neural network signals |
| Implementations | `signals_lib/position_signals.py` | Position-dependent signals |
| Spec | `docs/superpowers/specs/critical-path/signals-module/base-signal-class.md` | This document |

---

## 11. Summary

The **BaseSignal** abstract base class provides:
1. **Interface contract** ensuring all signals implement core methods
2. **Stateless evaluation** enabling signal reuse across chains and contexts
3. **Historical lookback** via `shift` parameter without code duplication
4. **Metadata propagation** from signals to strategy via `get_data()`
5. **Polymorphic dispatch** enabling 50+ signal types in unified framework
6. **Extensibility** for new signal types via subclassing
7. **Composability** enabling combinators to build complex patterns from simple ones

It serves as the foundation for the entire signal evaluation system.
