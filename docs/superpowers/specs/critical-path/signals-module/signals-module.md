# Signals Module Specification

## Overview

The **Signals Module** is the decision engine of pybtctr2, responsible for evaluating 50+ signal types to detect market conditions and generate trading recommendations. Signals are hierarchically composed using combinators (AND, OR, NOT) into `SignalChain` sequences that represent multi-step trading patterns. The module evaluates all chains concurrently per tick, advancing each chain's position when its current signal fires. Once a chain completes, the SignalManager returns the corresponding action to the Strategy layer.

**Key principle:** Signals operate as a state machine where each chain tracks position in a sequence; completion triggers an action for strategy execution.

---

## Module Boundaries

### Upstream Dependencies
- **Data Layer** (`data.py`, `indicators.py`): Provides OHLC candles and technical indicators (RSI, MACD, CCI, Bollinger Bands, SAR, ATR, etc.) via the `DataPoint` protocol — signals read values via `data_point.get(col, tf, shift)` (path-agnostic; works for both live `LiveDataPoint` and simulation `WideDataPoint`)
- **Levels Module** (`levels.py`): Provides support/resistance levels and predicted price targets
- **Helpers Module** (`helpers.py`): Provides action constants (`OPEN_LONG`, `OPEN_SHORT`, `CLOSE_LONG`, `CLOSE_SHORT`, `MOVE_STOP_LOSS_LONG`, `MOVE_STOP_LOSS_SHORT`, `NOTHING`)

### Downstream Dependencies
- **Strategy Layer** (`strategy.py`, `strategy_manager.py`): Consumes signal-generated actions (entry, exit, stop-loss) to make final trading decisions
- **Position Management**: Strategy uses signal-generated data (level names, prices) to initialize/adjust positions

---

## Data Flow

```
Data Layer (OHLC, Indicators)
        ↓
BaseSignal.check(data, levels, action)
        ↓
    [Atomic Signal]  [Combinator Signal]  [Complex Signal]  [Candle Signal]
        ↓                   ↓                    ↓                  ↓
    SignalChain.cur_pos advances when current signal fires
        ↓
    SignalChain.completed() → generate action
        ↓
SignalManager.check() accumulates actions_list[]
        ↓
Strategy Layer (processes actions_list[])
```

**Evaluation sequence per tick:**
1. For each `SignalChain` in `SignalManager.chains[]`:
   - Call `chain.check(data_point, levels, cur_time, action)` — `data_point` is `DataPoint` protocol; `cur_time` (Unix seconds) is passed by caller
   - If `signals[cur_pos].check()` fires:
     - Increment `cur_pos`
     - Log marker position
   - If `cur_pos == len(signals)`: chain completed, generate action
2. Return accumulated `actions_list[]` to strategy

---

## Execution Flow

### Per-Tick Signal Evaluation

```python
# SignalManager.check(data_point, levels, cur_time, action)
# cur_time: Unix timestamp passed by caller (Robot/TrainRobot/Strategy)
actions = []
for ch in self.chains:
    ch.check(data_point, levels, cur_time, action)
    
    if ch.completed(data_point, action):
        # All signals in chain have fired sequentially
        actions.append(ch.get_action(data_point.get("close", 1, 0), action))
        ch.reset()
        
return actions
```

### Signal Chain State Machine

Each `SignalChain` maintains:
- `cur_pos`: Current position in signal sequence (0 to len(signals)-1)
- `signals[]`: List of BaseSignal instances
- `timer`: Timestamp when last signal fired (for timeout logic)
- `name`: Chain identifier (e.g., "Long_Entry_Pattern_1")
- `result_action`: Action to return when chain completes (`OPEN_LONG`, `OPEN_SHORT`, `CLOSE_LONG`, `CLOSE_SHORT`, `MOVE_STOP_LOSS_LONG`, `MOVE_STOP_LOSS_SHORT`)

**State transitions:**
```
cur_pos = 0
    ↓ [signals[0].check() fires]
cur_pos = 1
    ↓ [signals[1].check() fires]
cur_pos = 2
    ↓ ...
cur_pos = len(signals) → COMPLETED → return action & reset to 0
    
OR [signals[cur_pos].reset() fires] → reset to 0 (abort sequence)
```

---

## Key Components

### 1. BaseSignal (Abstract Interface)

**File:** `signals_lib/base_signal.py`

```python
class BaseSignal:
    def __init__(self):    
        self.shift = 0  # Historical offset (0=current, N>0=Nth last closed candle)
    
    def check(self, data_point, levels, action) -> bool:
        # Evaluate signal condition; return True if fired
        # data_point: DataPoint protocol — call data_point.get(col, tf, shift)
        assert False
    
    def reset(self) -> bool:
        # Return True to abort parent chain
        return False
    
    def get_data(self) -> dict:
        # Return metadata when chain completes (level names, prices, etc.)
        return {}
    
    def get_marker_pos(self, data_point) -> float:
        # Return price for logging/visualization
        return data_point.get("close", 1, 1)  # 1-min tf, last closed candle
    
    def set_shift(self, shift):
        # Set historical lookback offset
        self.shift = shift
```

All signal types inherit from `BaseSignal` and implement `check()` to evaluate a single condition.

### 2. SignalChain (Sequential State Machine)

**File:** `signals_lib/signal_manager.py`

```python
class SignalChain:
    def __init__(self, name, res_action, tf, notify=True):
        self.name = name
        self.signals = []
        self.cur_pos = 0  # Position in sequence
        self.timer = 0
        self.result_action = res_action  # Action when complete (e.g. OPEN_LONG, CLOSE_SHORT)
        self.tf = tf  # Timeframe
        self.notify = notify  # Log notifications
    
    def check(self, data_point, levels, cur_time, action):
        # Advance if current signal fires
        if self.cur_pos < len(self.signals):
            if self.signals[self.cur_pos].check(data_point, levels, action):
                if self.notify:
                    action.add_multiply_action(
                        self.signals[self.cur_pos].get_marker_pos(data_point),
                        "SF: C %s S %d" % (self.name, self.cur_pos)
                    )
                self.cur_pos += 1
                self.timer = cur_time
    
    def completed(self, data_point, action) -> bool:
        # True when all signals have fired
        if self.cur_pos == len(self.signals):
            if self.notify:
                action.add_multiply_action(
                    self.signals[len(self.signals)-1].get_marker_pos(data_point),
                    "CPLTD: %s" % self.name
                )
            return True
        return False
    
    def reset(self, action):
        # Reset to initial state
        self.cur_pos = 0
        self.timer = 0
    
    def get_action(self, price, action) -> list:
        # [result_action, tf, price, metadata_dict]
        data = {"position_time": self.tf}
        for s in self.signals:
            data.update(s.get_data())
        return [self.result_action, self.tf, price, data]
```

**Key invariants:**
- Only `signals[cur_pos]` is evaluated each tick (sequential evaluation)
- `cur_pos` only advances when current signal fires
- Chain completion requires ALL signals to fire in order

### 3. SignalManager (Chain Container)

**File:** `signals_lib/signal_manager.py`

```python
class SignalManager:
    def __init__(self):
        self.chains = []
    
    def add_chain(self, chain):
        self.chains.append(chain)
    
    def check(self, data_point, levels, cur_time, action) -> list:
        # data_point: DataPoint protocol (LiveDataPoint or WideDataPoint)
        # cur_time: Unix timestamp (seconds), passed by caller (Robot/TrainRobot/Strategy)
        # Evaluate all chains, return actions from completed ones
        actions = []
        for ch in self.chains:
            ch.check(data_point, levels, cur_time, action)
            
            if ch.completed(data_point, action):
                actions.append(ch.get_action(data_point.get("close", 1, 0), action))
                ch.reset()
        
        return actions  # Each element: [action_type, tf, price, metadata]
```

---

## Signal Types (50+ Implementations)

### Atomic Signals (Basic Comparisons)

These evaluate single conditions and form building blocks for complex patterns.

#### Value Comparisons
- **Less_Signal(tf, indi_1, indi_2)**: Returns `indi_1 < indi_2`
- **Greater_Signal(tf, indi_1, indi_2)**: Returns `indi_1 > indi_2`
- **Less_Val_Signal(tf, indi_1, val)**: Returns `indi_1 < val`
- **Greater_Val_Signal(tf, indi_1, val)**: Returns `indi_1 > val`

#### Crossovers (Composed from atomic + History)
- **Cross_Up_Signal(tf, indi1, indi2)**: `indi1 > indi2 AND indi1_prev < indi2_prev`
- **Cross_Down_Signal(tf, indi1, indi2)**: `indi1 < indi2 AND indi1_prev > indi2_prev`
- **Cross_Up_Val_Signal(tf, indi1, val)**: `indi1 > val AND indi1_prev < val`
- **Cross_Down_Val_Signal(tf, indi1, val)**: `indi1 < val AND indi1_prev > val`

#### Direction Changes
- **Rising_Signal(tf, indi_1)**: Returns `indi[0] > indi[1]` (indi rising)
- **Falling_Signal(tf, indi_1)**: Returns `indi[0] < indi[1]` (indi falling)

#### Difference Comparisons
- **Diff_Greater_Signal(tf, indi_1, indi_2, val)**: Returns `(indi_1 - indi_2) > val`
- **Diff_Less_Signal(tf, indi_1, indi_2, val)**: Returns `(indi_1 - indi_2) < val`
- **Diff_LessIndi_Signal(tf, indi_1, indi_2, indi_dist)**: Returns `(indi_1 - indi_2) < indi_dist`
- **Diff_GreaterIndi_Signal(tf_1, indi_1, tf_2, indi_2, tf_dist, indi_dist)**: Cross-timeframe difference

#### Level-Based Signals
- **Near_Level_Signal(tf, indi_1, level_type, buffer)**: `level - buffer <= indi <= level + buffer`
- **Near_Price_Level_Signal(tf, indi_1, level_type, buffer, buffer_indi)**: `buffer` scaled by indicator
- **Over_Level_Signal(tf, indi_1, level_type)**: `indi > any_level`
- **Under_Level_Signal(tf, indi_1, level_type)**: `indi < any_level`

### Combinators (Logical & Temporal Operations)

These compose atomic signals into complex conditions.

#### Boolean Logic
- **And_Signal(signals[])**: Returns `s1 AND s2 AND ... AND sN`
- **Or_Signal(signals[])**: Returns `s1 OR s2 OR ... OR sN`
- **Not_Signal(signal)**: Returns `NOT signal`

#### Temporal Composition
- **History_Signal(signal, history)**: Evaluate signal at historical offset
  - `signal.set_shift(history)` then `signal.check()`
  - Example: `History_Signal(Greater_Signal(...), 1)` checks if greater at shift=1

- **Continuous_Signal(signal, history, multiply=1)**: Count occurrences in history
  - Fires if signal fires `>= multiply` times in last `history` candles
  - Example: `Continuous_Signal(Rising_Signal(...), 3, 2)` fires if rising at least 2 of last 3 candles

#### Boolean Wrappers
- **True_Signal()**: Always fires
- **False_Signal()**: Never fires
- **BoolValue_Signal(value, tf)**: Evaluates boolean indicator value
- **PersistentCounter_Signal(fire_each)**: Fires every N ticks (global counter)
- **DataValue_Signal(name, value, value_set)**: Wraps metadata with boolean logic

### Complex Signals (Multi-Indicator Patterns)

These detect specific technical patterns requiring sequence analysis.

#### Divergences
- **Diver_Bull_signal(tf, level, cancel_level, indicator, finished=True)**
  - Detects bullish divergence: price makes lower low, indicator makes higher low below level
  - Searches history for peak in indicator below `level` with opposite price direction
  - Cancels if indicator exceeds `cancel_level`
  - `finished=True`: requires completed peak (3 candle valley); `False`: immediate
  - Returns: True if divergence detected

- **Diver_Bear_signal(tf, level, cancel_level, indicator, finished=True)**
  - Detects bearish divergence: price makes higher high, indicator makes lower high above level
  - Mirrors bullish logic with inverted comparisons

- **Diver_Hidden_signal** (referenced in spec, implementation similar)
  - Hidden bullish: price lower high, indicator higher high
  - Hidden bearish: price higher low, indicator lower low

#### Bounce Signals
- **Bounce_Signal** (referenced in spec, detects price bounce off level)

### Candle Pattern Signals

These analyze candle structure (open, close, high, low) to detect specific formations.

#### Candle Size
- **BigCandle_Signal(tf, coef)**: Returns `natr > coef * natr_ma` (large candle relative to average)

#### Wick Analysis
- **LongTale_Signal(tf, type)**: Long wick in specified direction
  - `type=CANDLE_LOW`: Long lower wick: `(min(open,close) - low) > 0.5 * candle_size`
  - `type=CANDLE_HIGH`: Long upper wick: `(high - max(open,close)) > 0.5 * candle_size`

- **ShortTale_Signal(tf, type)**: Short wick in specified direction
  - `type=CANDLE_LOW`: `(min(open,close) - low) < 0.2 * candle_size`
  - `type=CANDLE_HIGH`: `(high - max(open,close)) < 0.2 * candle_size`

#### Direction
- **CandleUP_Signal(tf)**: Returns `open < close` (bullish candle)
- **CandleDOWN_Signal(tf)**: Returns `open > close` (bearish candle)

### Legacy Signals (signals.py - Original Implementation)

The `signals.py` file contains legacy signal classes still used alongside new modular system:

#### Volume & Price Action
- **High_Volume_Signal**: Detects high volume candles
- **OHLC_Diff_UP_Signal**: Detects bullish OHLC divergences in price ranges
- **OHLC_Diff_DOWN_Signal**: Detects bearish OHLC divergences

#### Level Interactions
- **Level_Cross_UP_Signal(tf, lvl_type, lvl_time_type)**: Price crosses support level upward
- **Level_Cross_DOWN_Signal(tf, lvl_type, lvl_time_type)**: Price crosses resistance level downward
- **Price_Near_Level_UP_Signal(tf, lvl_type, lvl_time_type, max_limit, min_limit)**: Price near support
- **Price_Near_Level_DOWN_Signal(tf, lvl_type, lvl_time_type, max_limit, min_limit)**: Price near resistance
- **Support_Break_Confirmation_Signal(tf, lvl_type, lvl_time_type)**: Support level breaks with confirmation
- **Resistance_Break_Confirmation_Signal(tf, lvl_type, lvl_time_type)**: Resistance level breaks with confirmation

#### Bollinger Bands
- **Near_BB_Signal(tf, bb_type, price_type, min_val, max_val)**: Price near Bollinger Band
  - Checks if price within range of BB (upper, middle, lower)
- **Near_BBD_Signal(tf, window)**: Price near upper BB with small distance

#### SAR (Parabolic SAR)
- **SAR_Up_Signal(tf, hist)**: SAR below price (uptrend reversal indicator)
- **SAR_Down_Signal(tf, hist)**: SAR above price (downtrend reversal indicator)

#### Peak/Trough Detection
- **Peak_High_Signal(tf, level, indicator, hist)**: Local maximum in indicator above threshold
  - Checks if indicator forms peak: `indicator[t-1] < indicator[t] > indicator[t+1]`
- **Peak_Low_Signal(tf, level, indicator, hist)**: Local minimum in indicator below threshold
  - Checks if indicator forms trough: `indicator[t-1] > indicator[t] < indicator[t+1]`

#### Prediction-Based
- **Prediction_Normal_Signal(tf)**: Price within predicted buy/sell range
- **Near_Prediction_Buy_Signal(tf, window)**: Price approaching predicted buy level
- **Near_Prediction_Sell_Signal(tf, window)**: Price approaching predicted sell level

---

## Signal State Machine Detailed

### Chain Execution Model

**Example chain:** `[Signal_A, Signal_B, Signal_C]` with result_action=`OPEN_LONG`

**Tick-by-tick execution:**

| Tick | signals[cur_pos].check() | cur_pos | State | Event |
|------|--------------------------|---------|-------|-------|
| 1 | A fires | 0→1 | Advancing | Log "Signal A fired" |
| 2 | A fires | 1 | Waiting for B | Nothing happens (cur_pos already past A) |
| 3 | B fires | 1→2 | Advancing | Log "Signal B fired" |
| 4 | B fires | 2 | Waiting for C | Nothing happens |
| 5 | A fires | 2 | Waiting for C | Nothing happens (we're past A) |
| 6 | C fires | 2→3 | COMPLETED | Log "Chain completed"; return [OPEN_LONG, tf, price, metadata]; reset |
| 7 | A fires | 0→1 | Restarted | New cycle begins |

**Key observation:** Only the current signal is evaluated; signals before cur_pos are ignored.

### Reset Behavior

```python
def check(self, data_point, levels, cur_time, action):
    if self.cur_pos < len(self.signals):
        if self.signals[self.cur_pos].check(data_point, levels, action):
            self.cur_pos += 1
            
    # Check for reset (abort sequence)
    if self.cur_pos < len(self.signals):
        if self.signals[self.cur_pos].reset():
            self.reset(action)  # Reset to cur_pos = 0
```

If any signal's `reset()` returns True, the entire chain resets. This allows aborting a sequence if a condition is violated (e.g., stop-loss hit).

---

## Existing Approach & Design Patterns

### Sequential Evaluation
- Each chain evaluates only one signal per tick (`signals[cur_pos]`)
- Prevents race conditions and ensures deterministic state progression
- Scales to 100s of chains with minimal overhead

### Persistent State Across Ticks
- Chain state (`cur_pos`, `timer`) persists across ticks until completion/reset
- Enables multi-candle patterns (e.g., "3 rising candles then breakout")
- Historical lookback via `shift` parameter in BaseSignal

### Shift-Based Historical Lookback
- Each signal reads values via `data_point.get(col, tf, shift)`:
  - shift=0: current value (partial candle if mid-period in simulation)
  - shift=1: last completed candle
  - shift=N: Nth last completed candle
- Compositors like `History_Signal` call `signal.set_shift(N)` before evaluating
- Example: `History_Signal(Greater_Signal(...), 1)` checks previous closed candle

### Cross-Timeframe Support
- Signals can mix timeframes: `Diff_GreaterIndi_Signal(tf1=15, indi1, tf2=60, indi2, ...)`
- Enables multi-timeframe trend confirmation

### Logging & Markers
- Each signal provides `get_marker_pos(data_point)` for chart visualization
- Signals log firing via `action.add_multiply_action()` for trade analytics
- Chain completion logged with name and position

---

## Signal Composition Examples

### Example 1: Simple Crossover Entry

```python
# RSI crosses above 50 — long entry
chain = SignalChain("RSI_Cross_50_Up", OPEN_LONG, tf=15)
chain.add(Cross_Up_Val_Signal(15, "rsi_14", 50))
signal_manager.add_chain(chain)
```

Completion fires `OPEN_LONG` when RSI-14 crosses 50 upward on 15m candle.

### Example 2: Multi-Step Pattern

```python
# Long entry: (1) MACD bullish crossover, (2) RSI confirms above 50, (3) Price above EMA-25
chain = SignalChain("MACD_RSI_EMA_Long", OPEN_LONG, tf=5)
chain.add(Cross_Up_Signal(5, "macd", "macd_signal"))  # Signal 0
chain.add(Greater_Signal(5, "rsi_14", 50))            # Signal 1
chain.add(Greater_Signal(5, "close", "ema_25"))       # Signal 2
signal_manager.add_chain(chain)
```

Entry only triggers after MACD crosses up, then RSI confirms above 50, then price confirms above EMA. Sequential on same timeframe.

### Example 3: Complex Multi-Timeframe

```python
# 1H uptrend confirmed, 15m entry setup
chain = SignalChain("1H_15m_Entry", OPEN_LONG, tf=15)
# 1H: price above EMA-50
chain.add(Greater_Signal(60, "close", "ema_50"))
# 15m: RSI oversold + divergence setup
chain.add(Less_Signal(15, "rsi_14", 40))
chain.add(Diver_Bull_signal(15, level=40, cancel_level=70, indicator="rsi_14"))
signal_manager.add_chain(chain)
```

---

## Signal Metadata & Data Flow

When a chain completes, `get_action()` accumulates metadata from all signals:

```python
def get_action(self, price, action):
    data = {"position_time": self.tf}
    for s in self.signals:
        data.update(s.get_data())  # Merge signal-specific data
    return [self.result_action, self.tf, price, data]
```

**Example metadata returned:**

```python
{
    "position_time": 15,
    "cur_level_name": "Support_1",
    "level_val": 29450.50,
    "sar_val": 29445.20,
    ...
}
```

Strategy layer uses this metadata to:
- Set stop-loss at level_val
- Initialize position size based on distance to level
- Log trade reason for analytics

---

## Potential Improvements

### 1. ML-Based Signal Optimization
- **Current:** Signals hardcoded with fixed thresholds (RSI > 50, etc.)
- **Future:** Train NN to adjust thresholds and timeframes per pair based on backtested win rate
- **Implementation:** Wrap signals in optimization layer; auto-tune hyperparameters

### 2. Signal Weighting & Confidence Scoring
- **Current:** All signals binary (fire or don't fire)
- **Future:** Return confidence scores; combine with weighted OR instead of AND
  - Example: RSI=55 scores higher confidence than RSI=50.1
  - Example: Multiple timeframes vote; highest consensus triggers
- **Implementation:** Extend BaseSignal to return `(bool, confidence_0_1)`

### 3. Predictive Signals
- **Current:** Signals detect historical patterns (divergence, crossover)
- **Future:** Add NN-based prediction signals (e.g., "NN predicts 2% move in 5 min")
- **Implementation:** `NNPredictor_Signal` inherits BaseSignal; outputs probability

### 4. Batch Evaluation & Vectorization
- **Current:** Sequential evaluation; one signal per chain per tick
- **Future:** Vectorize across multiple chains; evaluate all signals in parallel for same data point
- **Benefit:** 10-50x faster backtesting; better hardware utilization
- **Implementation:** Refactor to NumPy-based bulk evaluation

### 5. Signal Dependency Management
- **Current:** Manual ordering in chains; no validation
- **Future:** Graph-based system; detect circular dependencies; auto-order signals
- **Example:** Detect that Signal_B depends on Signal_A output; auto-insert in correct order

### 6. Adaptive Timeframe Scaling
- **Current:** Timeframes fixed (1, 5, 15, 60, 240 min)
- **Future:** Dynamic timeframe selection per pair based on volatility
- **Example:** High-volatility pairs switch to shorter timeframes; low-volatility to longer

### 7. Real-Time Signal Strength Aggregation
- **Current:** Actions_list returned as-is; strategy picks latest action
- **Future:** Score all active signals; return weighted aggregate action strength
- **Example:** 3 entry signals firing simultaneously boost confidence; 0.3 individual → 0.8 aggregate

---

## Implementation Notes

### Threading & Performance
- Signal evaluation is single-threaded per tick (no race conditions)
- Compatible with parallel data generation (separate ticks don't interfere)
- Chains can number in 100s without measurable slowdown

### Indicator Precalculation
- All indicators precalculated in Data layer before signal evaluation
- Signals never recalculate; only read via `data_point.get(col, tf, shift)`
- Cache coherency guaranteed by data versioning (`df_with_indicators.pkl`)

### Debugging Signals
- Enable logging: `from logs import log_signals`
- Each signal fires logs via `signal.get_marker_pos(data_point)` and chain notifications
- Use `chain.name`, `chain.cur_pos`, `signal.shift` to trace state

### Testing
- Mock `DataPoint` with `get()` returning predictable values
- Test signals in isolation with unit tests
- Test chains with end-to-end backtest comparison

---

## File Manifest

| File | Classes | Purpose |
|------|---------|---------|
| `signals_lib/base_signal.py` | BaseSignal | Abstract signal interface |
| `signals_lib/signal_manager.py` | SignalChain, SignalManager | Chain state machine & container |
| `signals_lib/common.py` | Less_Signal, Greater_Signal, Cross_Up_Signal, Rising_Signal, etc. | Atomic signals & basic comparisons |
| `signals_lib/operations.py` | And_Signal, Or_Signal, Not_Signal, History_Signal, Continuous_Signal, etc. | Combinators & temporal composition |
| `signals_lib/complex.py` | Diver_Bull_signal, Diver_Bear_signal | Complex patterns (divergences) |
| `signals_lib/candle.py` | BigCandle_Signal, LongTale_Signal, CandleUP_Signal, etc. | Candle-based patterns |
| `signals_lib/nn_signals.py` | (TBD) | Neural network signal integration |
| `signals_lib/position_signals.py` | (TBD) | Signals dependent on open positions |
| `signals.py` | High_Volume_Signal, Level_Cross_UP_Signal, etc. | Legacy signals (to migrate) |

---

## Summary

The **Signals Module** provides:
1. **50+ signal types** covering atomic conditions, combinators, complex patterns, and candle formations
2. **Sequential composition** via SignalChain state machine ensuring deterministic multi-step pattern detection
3. **Historical lookback** via shift-based offset in BaseSignal enabling multi-candle analysis
4. **Cross-timeframe support** allowing signals to mix 1m, 5m, 15m, 1h, 4h, 1d candles
5. **Metadata propagation** from signals to strategy via `get_data()` enabling level-based position sizing
6. **High performance** with parallel chain evaluation and minimal overhead per tick

The module bridges data indicators to trading strategies, translating raw price/volume patterns into actionable entry/exit signals.
