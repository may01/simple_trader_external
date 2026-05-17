# SignalChain Class Specification

## 1. Class Overview

The `SignalChain` class is a **sequential state machine** that represents a multi-step trading pattern. Signals in the chain must fire **in order**, with state persisting across ticks. When all signals have fired sequentially, the chain is considered "completed" and returns an action to the Strategy layer.

**Responsibilities:**
- Maintain ordered list of BaseSignal instances
- Track current position in sequence (`cur_pos`)
- Evaluate only the current signal at each tick
- Advance position when current signal fires
- Detect chain completion (all signals fired in order)
- Package and return action with aggregated metadata
- Support reset to restart sequence

**Design Pattern:** Sequential state machine with persistent state across ticks.

**Key Principle:** Only `signals[cur_pos]` is evaluated per tick. Completion requires ALL signals to fire in strict order.

---

## 2. Key Attributes

| Attribute | Type | Purpose | Default/Range | Notes |
|-----------|------|---------|----------------|-------|
| `name` | str | Chain identifier (e.g., "Long_Entry_Pattern_1") | Set at init | Used for logging and debugging |
| `signals` | list[BaseSignal] | Ordered list of signal instances | Empty at init | Populated via `add()` method |
| `cur_pos` | int | Current position in signal sequence | 0 at init | Range: 0 to len(signals); completion when == len(signals) |
| `timer` | int | Unix timestamp when last signal fired | 0 at init | Updated on signal advance; used for timeout logic (future) |
| `result_action` | int | Action to return on completion | Set at init | Action constant (`OPEN_LONG`, `OPEN_SHORT`, `CLOSE_LONG`, `CLOSE_SHORT`, `MOVE_STOP_LOSS_LONG`, `MOVE_STOP_LOSS_SHORT`) |
| `tf` | int | Timeframe in minutes | Set at init | 1, 5, 15, 60, 240, 1440 (from `candles_config.yaml`) |
| `notify` | bool | Enable logging/notification on fires | True at init | When True, logs signal advances and completion |

### Notes on Attributes

**`signals[]` lifecycle:**
- Initially empty; populated by caller via `add(signal)`
- Read-only after initialization starts (no removal/reordering during execution)
- Each signal is a BaseSignal instance with `check()`, `reset()`, `get_data()` methods

**`cur_pos` state machine:**
- Starts at 0 (evaluating `signals[0]`)
- Increments when `signals[cur_pos].check()` returns True
- Resets to 0 when any signal's `reset()` returns True
- Completion: `cur_pos == len(signals)`

**`timer` usage:**
- Records timestamp of last signal fire (future: timeout detection)
- Currently logged but not actively used for timeouts
- Could enable: "reset chain if no signal fires for 60 seconds"

**`notify` flag:**
- When True: logs signal advances and chain completion
- Used for debugging and trade analytics
- Reduces noise when notifications not needed

---

## 3. Constructor (`__init__`)

### Signature
```python
def __init__(self, name: str, res_action: int, tf: int, notify: bool = True) -> None
```

### Parameters
- **`name`** (str): Human-readable identifier for the chain (e.g., "MACD_RSI_SMA_Long")
  - Used in logging and debugging
  - Recommended: descriptive pattern name or trade setup identifier
  
- **`res_action`** (int): Action type to return when chain completes
  - Must be an action constant from `strategies/actions.py`
  - Common values: `OPEN_LONG`, `OPEN_SHORT`, `CLOSE_LONG`, `CLOSE_SHORT`, `MOVE_STOP_LOSS_LONG`, `MOVE_STOP_LOSS_SHORT`
  
- **`tf`** (int): Timeframe in minutes for this chain
  - Common values: 1, 5, 15, 60, 240, 1440 (from `candles_config.yaml`)
  - Determines which candle data signals receive
  - Individual signals can use different timeframes, but chain.tf specifies primary
  
- **`notify`** (bool, optional): Enable logging when signals fire and chain completes
  - Default: True
  - Set to False for silent chains (reduces output in verbose backtests)

### Initialization Steps
1. Set `self.name = name`
2. Set `self.result_action = res_action`
3. Set `self.tf = tf`
4. Set `self.notify = notify`
5. Initialize `self.signals = []` (empty list)
6. Initialize `self.cur_pos = 0`
7. Initialize `self.timer = 0`

### Postconditions
- Chain is ready to add signals via `add(signal)`
- Chain is not yet ready to be evaluated (no signals added)

### Exceptions
- None; constructor always succeeds

---

## 4. Key Methods

### 4.1 `add(signal)`

#### Signature
```python
def add(self, signal: BaseSignal) -> None
```

#### Purpose
Register a signal to the end of the chain sequence.

#### Parameters
- **`signal`** (BaseSignal): A fully configured signal instance
  - Must inherit from BaseSignal
  - Must implement `check()`, `reset()`, `get_data()`, `get_marker_pos()`

#### Implementation
```python
def add(self, signal):
    self.signals.append(signal)
```

#### Behavior
- Appends signal to end of sequence
- Signals are evaluated in the order they are added
- No validation; assumes signal is valid BaseSignal instance

#### Preconditions
- `signal` is a valid BaseSignal instance

#### Postconditions
- Signal is registered and will be evaluated when `cur_pos` reaches it

#### Usage Example
```python
chain = SignalChain("Long_Setup", OPEN_LONG, 15)
chain.add(Cross_Up_Signal(15, "macd", "macd_signal"))  # Signal 0
chain.add(Greater_Signal(15, "rsi_14", 50))            # Signal 1
chain.add(Greater_Signal(15, "close", "ema_25"))       # Signal 2
# Chain ready; will evaluate signals in order
```

#### Exceptions
- None

---

### 4.2 `check(data, levels, cur_time, action)`

#### Signature
```python
def check(self, data, levels, cur_time: int, action) -> None
```

#### Purpose
Evaluate current signal and advance position if it fires. Also check for reset condition.

#### Parameters
- **`data_point`** (DataPoint): Path-agnostic data access protocol (`LiveDataPoint` or `WideDataPoint`)
  - Used by current signal to access price/indicator values via `data_point.get(col, tf, shift)`
- **`levels`** (Levels): Support/resistance levels object
  - Passed to current signal for level-based evaluation
- **`cur_time`** (int): Unix timestamp (seconds) of current tick — passed by caller (Robot/Strategy)
  - Used to update `timer` when signal fires; not read from `DataPoint` directly
- **`action`** (Action): Action object for logging/notifications
  - Passed to signal and used to log marker positions

#### Return Value
- **None** (returns nothing; updates internal state)

#### Implementation Logic
```python
def check(self, data_point, levels, cur_time, action):
    # Step 1: Evaluate current signal and advance if it fires
    if self.cur_pos < len(self.signals):
        if self.signals[self.cur_pos].check(data_point, levels, action):
            # Signal fired; advance and log
            if self.notify:
                action.add_multiply_action(
                    self.signals[self.cur_pos].get_marker_pos(data_point),
                    "SF: C %s S %d" % (self.name, self.cur_pos)
                )
            self.cur_pos += 1
            self.timer = cur_time
    
    # Step 2: Check if current signal wants to reset chain
    if self.cur_pos < len(self.signals):
        if self.signals[self.cur_pos].reset():
            self.reset(action)
```

#### Behavior
1. **Check bounds**: Ensure `cur_pos < len(signals)` (not completed yet)
2. **Evaluate current signal**: Call `signals[cur_pos].check(data, levels, action)`
3. **If fires**:
   - Log marker position if `notify=True`
   - Increment `cur_pos` to next signal
   - Update `timer` to current timestamp
4. **Check reset**: If current signal (now at new position) requests reset, reset chain

#### Timing
- Called once per data tick (per candle)
- Evaluation is O(1) for current signal only

#### State Transitions
```
Before check():     cur_pos = 0 (evaluating signals[0])
After check():      cur_pos = 1 (if signals[0] fired, now evaluating signals[1])
                    cur_pos = 0 (if signals[0] requested reset)
                    cur_pos = 0 (if signals[0] didn't fire; no change)
```

#### Edge Cases
- **Chain already complete**: `cur_pos == len(signals)`, nothing happens (signals list can't be accessed)
- **Signal fires and immediately resets**: Position advances, then resets back to 0
- **No signals added**: `cur_pos` stays at 0; nothing fires (len(signals) = 0)

#### Preconditions
- At least one signal must be added via `add()`
- `data`, `levels`, `action` are valid objects

#### Postconditions
- `cur_pos` advanced if current signal fired
- `timer` updated if signal advanced
- All other state unchanged if signal didn't fire

#### Exceptions
- None; method is defensive and handles edge cases

---

### 4.3 `completed(data, action)`

#### Signature
```python
def completed(self, data: Data, action: Action) -> bool
```

#### Purpose
Test whether chain has completed (all signals have fired in sequence).

#### Parameters
- **`data_point`** (DataPoint): DataPoint protocol (used for logging marker position on completion)
- **`action`** (Action): Action object (used for logging completion notification)

#### Return Value
- **bool**: True if `cur_pos == len(signals)` (all signals have fired), False otherwise

#### Implementation Logic
```python
def completed(self, data_point, action):
    if self.cur_pos == len(self.signals):
        if self.notify:
            action.add_multiply_action(
                self.signals[len(self.signals)-1].get_marker_pos(data_point),
                "CPLTD: %s" % self.name
            )
        return True
    return False
```

#### Behavior
1. **Test completion**: Check if `cur_pos == len(signals)`
2. **If completed**:
   - Log completion message with final signal's marker position (if `notify=True`)
   - Return True
3. **If not completed**:
   - Return False (no logging)

#### State
- **Stateless**: Does not modify internal state; purely a test

#### Preconditions
- At least one signal must be added (otherwise len(signals) = 0, cur_pos = 0, completion on init)

#### Postconditions
- No state change; purely informational

#### Exceptions
- None

#### Usage Pattern
```python
for ch in signal_manager.chains:
    ch.check(data_point, levels, cur_time, action)
    
    if ch.completed(data_point, action):  # Check if complete
        action_list.append(ch.get_action(data_point.get("close", 1, 0), action))
        ch.reset(action)
```

---

### 4.4 `get_action(price, action)`

#### Signature
```python
def get_action(self, price: float, action: Action) -> list
```

#### Purpose
Package the completed chain into an action structure for the Strategy layer.

#### Parameters
- **`price`** (float): Current close price at completion time
  - Typically: `data_point.get("close", 1, 0)` (1-min tf, current)
- **`action`** (Action): Action object (currently unused; for consistency)

#### Return Value
**list with 4 elements:**
```python
[result_action, timeframe, price, metadata_dict]
```

Where:
- **`result_action`** (int): `self.result_action` (`OPEN_LONG`, `OPEN_SHORT`, `CLOSE_LONG`, `CLOSE_SHORT`, etc.)
- **`timeframe`** (int): `self.tf` (chain's timeframe)
- **`price`** (float): Close price at completion
- **`metadata_dict`** (dict): Aggregated metadata from all signals

#### Implementation Logic
```python
def get_action(self, price, action):
    # Aggregate metadata from all signals
    data = {}
    data["position_time"] = self.tf
    for s in self.signals:
        data.update(s.get_data())
    
    # Return action package
    return [self.result_action, self.tf, price, data]
```

#### Behavior
1. **Create metadata dict**: Start with `position_time` = chain's timeframe
2. **Aggregate signal data**: Iterate all signals, merge each signal's `get_data()` into dict
3. **Package action**: Return list with action type, timeframe, price, metadata

#### Metadata Aggregation
- Each signal contributes via `get_data()`
- Later signals can override earlier signal's keys
- Enables signals to share or override metadata fields

#### Example
```python
# Chain with 2 signals
chain.add(Near_Level_Signal(...))      # Returns {"level_name": "Support_1", "level_val": 29450}
chain.add(Rising_Signal(...))          # Returns {"direction": "up"}

# get_action() aggregates to:
{
    "position_time": 15,
    "level_name": "Support_1",
    "level_val": 29450,
    "direction": "up"
}

# Returns:
[OPEN_LONG, 15, 29475.50, {above metadata}]
```

#### Preconditions
- Chain must be completed (should only be called after `completed()` returns True)
- `price` is the current close price

#### Postconditions
- No state change; purely informational

#### Exceptions
- None; method is defensive

---

### 4.5 `reset(action)`

#### Signature
```python
def reset(self, action: Action) -> None
```

#### Purpose
Reset chain to initial state for next cycle.

#### Parameters
- **`action`** (Action): Action object (currently unused; for consistency)

#### Implementation Logic
```python
def reset(self, action):
    self.cur_pos = 0
    self.timer = 0
```

#### Behavior
1. **Reset position**: Set `cur_pos = 0` (back to evaluating first signal)
2. **Reset timer**: Set `timer = 0`

#### State Transition
```
Before reset:  cur_pos = len(signals), timer = <timestamp>
After reset:   cur_pos = 0, timer = 0
Chain restarts fresh on next check() call
```

#### Triggering Conditions
- Called by SignalManager after `completed()` returns True
- Called by chain's own `check()` if a signal requests reset via `reset() == True`

#### Preconditions
- Chain is in a state to reset (typically completed or mid-sequence abort)

#### Postconditions
- Chain is ready to start new sequence
- All signals available for re-evaluation

#### Exceptions
- None

#### Usage Example
```python
# SignalManager calls reset after completion
if ch.completed(data, action):
    ch.get_action(price, action)
    ch.reset(action)  # Ready for next cycle
```

---

## 5. State Machine

### Sequential Evaluation Model

```
        │
        ▼
┌─────────────────────────────┐
│ Chain Initialized           │
│ cur_pos = 0, signals = []   │
└──────────────┬──────────────┘
               │
        add(signal 0)
        add(signal 1)
        add(signal 2)
               │
               ▼
┌─────────────────────────────┐
│ Ready for Evaluation        │
│ cur_pos = 0                 │
│ signals = [S0, S1, S2]      │
└──────────────┬──────────────┘
               │
        check() [Tick 1]
               │
        ┌──────┴───────┐
        │              │
   S0.check()    [S0 fires]
   returns True       │
        │             ▼
        │     ┌──────────────────┐
        │     │ S0 Advanced       │
        │     │ cur_pos = 1       │
        │     │ Evaluating S1     │
        │     │ timer = <time>    │
        │     └──────────┬────────┘
        │                │
        │        check() [Tick 2]
        │                │
        │          S1.check()
        │          returns False
        │                │
        │                ▼
        │        ┌──────────────────┐
        │        │ No Change        │
        │        │ cur_pos = 1      │
        │        │ Still on S1      │
        │        └──────────┬───────┘
        │                   │
        │          check() [Tick 3]
        │                   │
        │            S1.check()
        │            returns True
        │                   │
        │                   ▼
        │           ┌──────────────────┐
        │           │ S1 Advanced       │
        │           │ cur_pos = 2       │
        │           │ Evaluating S2     │
        │           │ timer = <time>    │
        │           └──────────┬────────┘
        │                      │
        └──────────────────────┤
                               │
                      check() [Tick 4]
                               │
                        S2.check()
                        returns True
                               │
                               ▼
                       ┌─────────────────┐
                       │ COMPLETED!      │
                       │ cur_pos = 3     │
                       │ All S fired     │
                       │ Return action   │
                       └────────┬────────┘
                                │
                        reset(action)
                                │
                                ▼
                       ┌──────────────────┐
                       │ Reset for Cycle  │
                       │ cur_pos = 0      │
                       │ timer = 0        │
                       │ Ready for S0     │
                       └────────┬─────────┘
                                │
                                ▼
                         (Next cycle)
```

### Reset on Signal Abort

A signal can request chain abort via `reset() == True`:

```
check() evaluates signals[cur_pos]
        │
        ├─ signals[cur_pos].check() returns False
        │  (signal didn't fire; nothing happens)
        │
        └─ signals[cur_pos].reset() returns True
           (signal requests abort)
           │
           ▼
       chain.reset(action)
       cur_pos = 0
       (sequence aborted; restart from beginning)
```

---

## 6. Existing Approach

### Sequential Evaluation
- Only `signals[cur_pos]` is evaluated per tick
- Prevents race conditions and ensures deterministic progression
- Signals before and after cur_pos are completely ignored

### Persistent State Across Ticks
- Chain state (`cur_pos`, `timer`) survives between ticks
- Enables multi-candle patterns (e.g., "3 rising candles then breakout")
- Must be managed carefully to avoid stale state
 - Should be fix by reseting state on failure, multi candle should be handeled with history_signal

### Shift-Based Historical Lookback
- Individual signals can evaluate at historical offset via `shift` parameter
- Example: `History_Signal(Greater_Signal(...), 1)` checks previous candle
- SignalChain itself is not aware of shift; delegated to individual signals

### Single Active Chain per Name
- Each chain is independent; multiple chains with same name allowed (but not recommended)
- No built-in uniqueness check

---

## 7. Potential Improvements

### 1. Timeout-Based Reset
**Current:** Chain persists until completion or manual reset.
**Future:** Auto-reset if no signal fires for N seconds.
```python
def check(self, data, levels, cur_time, action):
    # Check for timeout
    if self.timer > 0 and (cur_time - self.timer) > 300:  # 5 minute timeout
        self.reset(action)
    
    # ... rest of check logic
```

**Benefit:** Prevents chains from getting stuck waiting for a signal that will never fire.

### 2. Alternative Signal Paths (do not implement util specific approval)
**Current:** Linear sequence; all signals must fire in order.
**Future:** Support branching paths (e.g., "Signal_A then (Signal_B OR Signal_C)").
```python
class SignalChain:
    def __init__(self, name, res_action, tf, notify=True):
        self.branches = []  # Alternative paths
    
    def add_branch(self, signals_list):
        self.branches.append(signals_list)
    
    def check(self, data, levels, cur_time, action):
        # Try main path first
        # If stuck, evaluate alternative branches
```

**Benefit:** More flexible pattern matching.

### 3. Priority Weighting (do not implement util specific approval)
**Current:** All signals treated equally; completion triggers immediately.
**Future:** Weight signals by importance; only complete if high-confidence.
```python
class SignalChain:
    def __init__(self, name, res_action, tf, notify=True, min_weight=0.7):
        self.weights = {}  # signal_idx -> weight
        self.min_weight = min_weight
    
    def get_completion_confidence(self):
        weights = [self.weights.get(i, 1.0) for i in range(self.cur_pos)]
        return sum(weights) / len(weights) if weights else 0
```

**Benefit:** Signal strength controls trade confidence.

### 4. Dynamic Signal Addition (do net implement util specific approval)
**Current:** Signals fixed at initialization.
**Future:** Add/remove signals during execution based on market conditions.
```python
def adapt_signals(self, market_volatility):
    if market_volatility > 0.05:  # High volatility
        self.signals.append(Diver_Bull_signal(...))  # Add divergence confirmation
    else:
        self.signals = [s for s in self.signals if not isinstance(s, Diver_Bull_signal)]
```

**Benefit:** Market-adaptive signal selection.

### 5. Performance Metrics
**Current:** No tracking of chain performance.
**Future:** Accumulate win rate, avg profit per completion, fire frequency.
```python
class SignalChain:
    def __init__(self, name, res_action, tf, notify=True):
        self.stats = {
            "fires": 0,
            "wins": 0,
            "total_profit": 0.0,
            "avg_duration": 0
        }
    
    def log_result(self, result_type, profit, duration):
        self.stats["fires"] += 1
        if result_type == "win":
            self.stats["wins"] += 1
            self.stats["total_profit"] += profit
```

**Benefit:** Identify underperforming chains for removal.

### 6. Visualization Support
**Current:** Logs via `action.add_multiply_action()`.
**Future:** Return chart markers with signal progression.
```python
def get_markers(self):
    return {
        "signals_fired": self.cur_pos,
        "completion_pct": (self.cur_pos / len(self.signals)) * 100,
        "positions": [s.get_marker_pos(data) for s in self.signals]
    }
```

**Benefit:** Visual progress tracking on charts.

---

## 8. Integration Notes

### With SignalManager
- SignalManager calls `check()`, `completed()`, `reset()`, `get_action()`
- Does not directly manipulate `cur_pos`, `signals[]`, or `timer`
- SignalManager is responsible for orchestrating chain lifecycle

### With BaseSignal
- Calls signal's `check()`, `reset()`, `get_data()`, `get_marker_pos()`
- Does not inspect or modify signal internals

### With Data & Levels
- Passes through to signals without modification
- Signals use to evaluate conditions

### With Strategy Layer
- Returns action packages via `get_action()`
- Strategy examines and executes returned actions

---

## 9. File Manifest

| File | Location | Content |
|------|----------|---------|
| Source | `signals_lib/signal_manager.py` (lines 6-59) | SignalChain class implementation |
| Spec | `docs/superpowers/specs/critical-path/signals-module/signal-chain-class.md` | This document |

---

## 10. Summary

The **SignalChain** class provides:
1. **Sequential state machine** with persistent state across ticks
2. **Order-dependent signal evaluation** (first signal must fire before second, etc.)
3. **Flexible composition** via `add()` method
4. **Metadata aggregation** from all signals into single action package
5. **Reset support** for cycle restart and abort conditions
6. **Logging & notifications** for debugging and analytics
7. **Simple interface** suitable for 100+ concurrent chains

It transforms a list of individual signal conditions into a multi-step trading pattern detector.
