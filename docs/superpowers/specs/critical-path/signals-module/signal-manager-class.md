# SignalManager Class Specification

## 1. Class Overview

The `SignalManager` class is a **container and orchestrator for multiple `SignalChain` objects**. It coordinates the evaluation of all registered signal chains per tick, collects completed actions, and returns them as a list for the Strategy layer to process.

**Responsibilities:**
- Register and maintain a list of `SignalChain` instances
- Evaluate all chains sequentially per data tick
- Detect when chains complete and extract their resulting actions
- Reset completed chains for next cycle
- Accumulate and return a list of all completed actions per tick

**Design Pattern:** Simple container with stateless orchestration. SignalManager delegates all state management to individual SignalChain instances.

**Key Principle:** Chains are evaluated independently and concurrently (in sequence but without mutual interference); multiple chains can complete on the same tick.

---

## 2. Key Attributes

| Attribute | Type | Purpose | Default/Range |
|-----------|------|---------|----------------|
| `chains` | list[SignalChain] | List of registered SignalChain instances | Empty list at init |

### Notes on `chains`
- **Mutability**: Chains list is populated via `add_chain()` during initialization
- **Order**: Chains are evaluated in the order they appear in the list (no implicit ordering)
- **Lifecycle**: Chains persist across multiple ticks; state managed by individual chain instances

---

## 3. Constructor (`__init__`)

### Signature
```python
def __init__(self) -> None
```

### Initialization Steps
1. Initialize `self.chains` as an empty list

### Postconditions
- SignalManager is ready to register chains via `add_chain()`
- No chains are pre-registered; caller must add them before `check()` is called

### Exceptions
- None; constructor is simple and always succeeds

---

## 4. Key Methods

### 4.1 `add_chain(chain)`

#### Signature
```python
def add_chain(self, chain: SignalChain) -> None
```

#### Purpose
Register a new SignalChain for evaluation on each tick.

#### Parameters
- **`chain`** (SignalChain): A fully configured SignalChain instance with signals already added via `chain.add(signal)`

#### Implementation
```python
def add_chain(self, chain):
    self.chains.append(chain)
    return
```

#### Behavior
- Appends the chain to the internal `chains` list
- Chain will be evaluated starting on the next `check()` call
- No validation of chain state; assumes chain is properly configured

#### Preconditions
- `chain` is a valid SignalChain instance

#### Postconditions
- `chain` is registered and will be evaluated in `check()`

#### Exceptions
- None; appending to list always succeeds

---

### 4.2 `check(data_point, levels, cur_time, action)`

#### Signature
```python
def check(self, data_point, levels, cur_time, action) -> list
```

#### Purpose
Evaluate all registered chains, return actions from completed chains.

#### Parameters
- **`data_point`** (DataPoint): Path-agnostic data access protocol (`LiveDataPoint` or `WideDataPoint`)
  - Used by chains to access prices and indicators via `data_point.get(col, tf, shift)`
- **`levels`** (Levels): Levels object containing detected support/resistance levels
  - Passed to each chain for level-based signal evaluation
- **`cur_time`** (int): Unix timestamp (seconds) of current tick
  - Passed by caller (Robot, TrainRobot, or Strategy); used by chains to update `timer`
  - **Note:** `cur_time` is NOT read from `data_point` — it is a separate caller-supplied parameter
- **`action`** (Action): Action object for logging/notifications
  - Passed to chains; used to log signal fires and chain completions

#### Return Value
**list**: List of completed actions. Each element is a list with structure:
```python
[action_type, timeframe, price, metadata_dict]
```

Where:
- **`action_type`** (int): Action constant (`OPEN_LONG`, `OPEN_SHORT`, `CLOSE_LONG`, `CLOSE_SHORT`, `MOVE_STOP_LOSS_LONG`, `MOVE_STOP_LOSS_SHORT`)
- **`timeframe`** (int): Minutes (1, 5, 15, 60, 240, 1440) - from `chain.tf`
- **`price`** (float): Current close price when chain completed
- **`metadata_dict`** (dict): Aggregated signal metadata from all signals in the chain

#### Implementation Logic
```python
def check(self, data_point, levels, cur_time, action):
    actions = []
    for ch in self.chains:
        # Step 1: Evaluate chain (advance cur_pos if signals fire)
        ch.check(data_point, levels, cur_time, action)
        
        # Step 2: Check if chain completed
        if ch.completed(data_point, action):
            # Extract action and add to list
            actions.append(ch.get_action(data_point.get("close", 1, 0), action))
            # Reset chain for next cycle
            ch.reset(True)
    
    return actions
```

#### Behavior
1. **Iterate through all chains**: For each chain in `self.chains`
2. **Evaluate chain state**: Call `ch.check()` to advance chain position if current signal fires
3. **Check completion**: Call `ch.completed()` to test if all signals have fired
4. **Extract action**: If completed, call `ch.get_action()` to package the action with metadata
5. **Reset chain**: Call `ch.reset()` to reset position to 0 for next cycle
6. **Accumulate**: Add completed action to `actions` list
7. **Return**: Return accumulated list of all completed actions

#### Timing
- Called once per data tick (per candle)
- All chains evaluated sequentially in single call
- Execution order matches order of chains in `self.chains`

#### Edge Cases
- **No chains**: Returns empty list (no actions)
- **No completions**: Returns empty list (nothing triggered)
- **Multiple completions**: Returns list with multiple actions (all chains can fire simultaneously)

#### Preconditions
- All chains in `self.chains` are properly initialized with signals
- `data_point`, `levels`, `action` objects are valid; `cur_time` is a valid Unix timestamp

#### Postconditions
- Completed chains have been reset to `cur_pos = 0`
- All other chains retain their state for next tick
- All completed actions returned in list

#### Exceptions
- None; method assumes valid input from caller

---

## 5. Existing Approach

### Stateless Orchestration
- SignalManager itself maintains **no state**; all state lives in individual SignalChain instances
- Enables simple composition: add more chains without increasing complexity
- Scales to 100+ chains with minimal overhead

### Concurrent Chain Evaluation
- Chains are evaluated **independently** (no crosstalk)
- A chain can complete while others are in progress without interference
- Multiple chains can return actions on the same tick

### Action Accumulation
- All completed actions returned as a flat list
- Strategy layer decides which action to execute (typically: latest, highest priority, or weighted)
- No prioritization at SignalManager level

---

## 6. Potential Improvements (Do not implement util specific approval for each subsection)

### 1. Priority-Based Action Selection
**Current:** All actions returned as-is; strategy picks latest or highest priority.
**Future:** SignalManager could filter/prioritize actions by confidence, chain name, or timeframe.
```python
def check(self, data_point, levels, cur_time, action):
    actions = []
    for ch in self.chains:
        ch.check(data_point, levels, cur_time, action)
        if ch.completed(data_point, action):
            actions.append(ch.get_action(data_point.get("close", 1, 0), action))
            ch.reset(True)
    
    # Sort by priority before returning
    return sorted(actions, key=lambda a: a[1], reverse=True)  # Sort by timeframe (1440 > 240 > 60 > 15 > 5 > 1)
```

**Benefit:** Ensures longer timeframes prioritized (1d > 4H > 1H > 15m).

### 2. Signal Weighting & Confidence Scores
**Current:** Binary signals (fire or don't fire).
**Future:** Extend BaseSignal to return confidence scores; aggregate at chain level.
```python
def get_confidence(self) -> float:
    # Average confidence of all signals in chain
    return sum(s.get_confidence() for s in self.signals) / len(self.signals)

def check(self, data_point, levels, cur_time, action):
    actions = []
    for ch in self.chains:
        ch.check(data_point, levels, cur_time, action)
        if ch.completed(data_point, action):
            action_data = ch.get_action(data_point.get("close", 1, 0), action)
            action_data.append(ch.get_confidence())  # Append confidence score
            actions.append(action_data)
            ch.reset(True)
    
    return actions
```

**Benefit:** Strategy can filter weak signals (confidence < threshold).

### 3. Conflict Resolution
**Current:** Multiple chains can return conflicting actions (buy + sell on same tick).
**Future:** Detect and resolve conflicts before returning.
```python
def check(self, data_point, levels, cur_time, action):
    actions = []
    for ch in self.chains:
        ch.check(data_point, levels, cur_time, action)
        if ch.completed(data_point, action):
            actions.append(ch.get_action(data_point.get("close", 1, 0), action))
            ch.reset(True)
    
    # Detect conflicts: remove close if open triggered
    action_types = [a[0] for a in actions]
    if OPEN_LONG in action_types and CLOSE_LONG in action_types:
        # Keep only open, discard close
        actions = [a for a in actions if a[0] != CLOSE_LONG]
    
    return actions
```

**Benefit:** Prevents invalid state (simultaneous entry/exit).

### 4. Chain Dependencies
**Current:** Chains are independent; no concept of prerequisites.
**Future:** Support chain dependencies (e.g., "only execute ExitChain if EntryChain previously fired").
```python
class SignalManager:
    def __init__(self):
        self.chains = []
        self.chain_state = {}  # Track if chains have fired
    
    def check(self, data_point, levels, cur_time, action):
        actions = []
        for ch in self.chains:
            # Check if prerequisites met
            if ch.requires and not self.chain_state.get(ch.requires):
                continue  # Skip this chain
            
            ch.check(data_point, levels, cur_time, action)
            if ch.completed(data_point, action):
                self.chain_state[ch.name] = True
                actions.append(ch.get_action(data_point.get("close", 1, 0), action))
                ch.reset(True)
        
        return actions
```

**Benefit:** Ensures logical sequences (entry must fire before exit).

### 5. Chain Statistics & Metrics
**Current:** No tracking of chain performance.
**Future:** Accumulate stats per chain (fires/hour, win rate, avg duration).
```python
class SignalManager:
    def __init__(self):
        self.chains = []
        self.chain_stats = {}  # {chain_name: {fires: 0, wins: 0, avg_duration: 0}}
    
    def log_completion(self, chain_name, duration, win):
        if chain_name not in self.chain_stats:
            self.chain_stats[chain_name] = {"fires": 0, "wins": 0, "duration": 0}
        self.chain_stats[chain_name]["fires"] += 1
        self.chain_stats[chain_name]["wins"] += (1 if win else 0)
```

**Benefit:** Identify underperforming chains for optimization.

### 6. Async Chain Evaluation
**Current:** Sequential evaluation (single-threaded).
**Future:** Parallel evaluation for 100+ chains via thread pool.
```python
from concurrent.futures import ThreadPoolExecutor

def check(self, data_point, levels, cur_time, action):
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(self._eval_chain, ch, data_point, levels, cur_time, action) 
                   for ch in self.chains]
        actions = []
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                actions.append(result)
    
    return actions
```

**Benefit:** Faster evaluation for large numbers of chains; better CPU utilization.

### 7. Dynamic Chain Registration
**Current:** Chains registered at initialization.
**Future:** Enable dynamic registration/deregistration per market conditions.
```python
def enable_chain(self, chain_name):
    # Activate chain by name (e.g., switch from "Bull_Mode" to "Bear_Mode")
    for ch in self.all_chains:
        if ch.name == chain_name:
            self.chains.append(ch)

def disable_chain(self, chain_name):
    # Deactivate chain by name
    self.chains = [ch for ch in self.chains if ch.name != chain_name]
```

**Benefit:** Market-regime switching without restarting.

---

## 7. Integration Notes

### With SignalChain
- SignalManager calls `chain.check()`, `chain.completed()`, `chain.reset()`, and `chain.get_action()`
- Does not access internal chain state (`cur_pos`, `timer`, `signals[]`)
- Relies on chain to maintain state between ticks

### With BaseSignal
- Does not directly interact with signals; delegation via SignalChain
- Signals are evaluated by individual chains during `chain.check()`

### With Strategy Layer
- Returns `actions` list to strategy
- Strategy examines action types and metadata to make execution decisions
- Strategy may log actions, filter by confidence, or execute multiple actions

### With Data & Levels
- Passes `data_point` (DataPoint protocol) and `levels` to chains without modification
- `cur_time` comes from caller, not from `data_point` — DataPoint does not expose a timestamp property
- Chains use `data_point.get(col, tf, shift)` for all indicator/price access

---

## 8. File Manifest

| File | Location | Content |
|------|----------|---------|
| Source | `signals_lib/signal_manager.py` (lines 61-85) | SignalManager class implementation |
| Spec | `docs/superpowers/specs/critical-path/signals-module/signal-manager-class.md` | This document |

---

## 9. Summary

The **SignalManager** class provides:
1. **Chain registration** via `add_chain()` for flexible composition
2. **Concurrent orchestration** of multiple independent chains per tick
3. **Action accumulation** from all completed chains into a single list
4. **Simple interface** with no internal state complexity
5. **Scalability** to 100+ chains without performance impact
6. **Extensibility** for future enhancements (weighting, priorities, conflict resolution)

It bridges the gap between low-level signal evaluation (SignalChain) and high-level strategy decision-making (Strategy layer).
