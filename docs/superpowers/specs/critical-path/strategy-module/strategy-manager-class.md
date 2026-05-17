# StrategyManager Class Specification

**Class:** `StrategyManager` (Orchestrator/Singleton Pattern)  
**File:** `strategy_manager.py`  
**Purpose:** Orchestrate multiple trading strategies, resolve conflicts, and produce single deterministic action  
**Scope:** Central coordinator translating strategy proposals into final trading decisions  

---

## 1. Class Overview

`StrategyManager` is the top-level decision engine that:
- Registers and manages multiple strategy instances (ExampleStrategyLong/Short as reference implementations; production strategies in `strategies/new_simulation/`)
- Evaluates each strategy's `check_conditions()` before execution
- Executes all eligible strategies and collects their proposed actions
- Applies priority-based conflict resolution (CLOSE > MOVE_STOP_LOSS > OPEN)
- Detects and prevents conflicting multi-strategy executions

**Design Pattern:** Coordinator/Facade  
- Hides complexity of multiple strategy evaluation
- Exposes single `check()` entry point
- Delegates details to individual strategy instances

**Singleton Behavior:** Typically instantiated once per trading session; data reference updated per-tick via `set_data()`.

---

## 2. Key Attributes

### Class Attributes (Shared)
```python
robot_actions_test = True  # Test mode flag
```

`Levels` is a Data module concern. Level data is accessed via `data.get_levels()` inside `check()` — no `Levels` instance is owned or imported by StrategyManager.

No class-level `fee` default — see fee injection rules below.

### Instance Attributes
| Attribute | Type | Initialized | Purpose |
|-----------|------|-------------|---------|
| `fee` | float | `__init__` | Taker fee rate — received from caller (`stock.item.fee`); passed to every Strategy and Position constructor |
| `robot_actions_test` | bool | `__init__` | Test mode: use test strategies if True |
| `state` | int | `__init__` | Internal state (STRATEGY_STATE_WAIT) |
| `strategies` | dict[int, Strategy] | `__init__` → register_strategies() | Active strategies mapped to state keys |

**Predictor and NN outputs are not owned by StrategyManager.** They are `IndicatorField` subclasses computed by the Data layer and exposed via `DataPoint.get(col, tf, shift)`. Strategies access them the same way as RSI or EMA — no separate loading or caching in StrategyManager.

---

## 3. Constructor

```python
def __init__(self, fee, robot_actions_test):
    """
    Initialize StrategyManager with configuration.
    
    Parameters:
        fee (float): Trading fee (e.g., 0.001) — received from stock.item.fee
        robot_actions_test (bool): True = use test strategies; False = use production strategies
    
    Behavior:
        1. Store fee, robot_actions_test, and state
        2. Initialize empty strategies dict
        3. Call register_test_strategies() if robot_actions_test=True
           OR register_strategies() if robot_actions_test=False
    
    Note: data is NOT stored — it is passed as a parameter to check() each tick.
    """
    self.fee = fee
    self.robot_actions_test = robot_actions_test
    self.state = STRATEGY_STATE_WAIT
    
    # Initialize and register strategies
    self.strategies = {}
    if robot_actions_test:
        self.register_test_strategies()
    else:
        self.register_strategies()
```

**Key Constructor Behaviors:**
- No predictor or NN caching — both delegated to the Data layer as IndicatorField subclasses
- Strategy registration deferred to helper methods
- No strategy validation (assumes valid implementations)

---

## 4. Strategy Registration

### 4.1 register_test_strategies()
```python
def register_test_strategies(self):
    """
    Register strategies for testing/debug mode.
    
    Behavior:
        Called when robot_actions_test=True
        Currently registers single test strategy:
        - ForTestLiveAction (simulates live trading for validation)
    
    Log Output:
        "strategy_manager:register_test_strategies()"
    """
    log("strategy_manager:register_test_strategies()")
    self.strategies[STRATEGY_STATE_WAIT_LONG_ACTION] = ForTestLiveAction(self.fee)
```

**Test Strategy Types (Commented Out, Available):**
- `ForTestLongAction`: Basic long-only action
- Other variants for specific validation

### 4.2 register_strategies()
```python
def register_strategies(self):
    """
    Register production strategies for live/backtest trading.
    
    Behavior:
        Called when robot_actions_test=False
        Currently registers new simulation strategies:
        - StratLong1_v1: Long strategy v1
        - StratShort1_v1: Short strategy v1 (commented, can be enabled)
        - StratShort2_v1: Short strategy v2 (commented, can be enabled)
    
    Log Output:
        "strategy_manager:register_strategies()"
    
    Commented Strategy Types (Available for Activation):
        - ExampleStrategyLong / ExampleStrategyShort: minimal reference implementations (pipeline validation)
        - Outliers1_Long_v1_1Strategy / Outliers1_Short_v1_1Strategy: Outlier detection
        - Various NN-enhanced strategies (NNLongV2, NNManualLongV3, etc.)
    
    Future Enhancement:
        - Should load strategies from config file (DB, JSON, YAML)
        - Enable/disable strategies per environment
        - Support strategy groups for different market regimes
    """
    log("strategy_manager:register_strategies()")
    
    self.strategies[0] = StratLong1_v1(self.data, self.fee)
    # self.strategies[1] = StratShort1_v1(self.data, self.fee)
    # self.strategies[2] = StratShort2_v1(self.data, self.fee)
    
    return
```

**Strategy Mapping:**
- Key: Integer state/ID (0, 1, 2, ...)
- Value: Strategy instance

**Current Active Strategies (Production):**
- Only StratLong1_v1 enabled
- Short strategies available but commented (allows quick activation)

---

## 5. Main Entry Point

### 5.1 check(position_state, position_target, action_msg)
**Called Once Per Tick - Returns Single Action**

```python
def check(self, data, position_state, position_target, action_msg):
    """
    Evaluate all registered strategies and return single trading action.
    
    Parameters:
        data (DataPoint): Current market data snapshot — passed in, not stored on self
        position_state (int): Current position state (POSITION_STATE_WAIT, WAIT_SELL, etc.)
        position_target (float): Position target price (if any)
        action_msg (ActionMessage): Message container for logging/debugging
    
    Returns:
        Tuple (action, open_price, close_price, stop_price, timeframe):
            - action (int): STRATEGY_ACTION_* constant
            - open_price (list[float]): Entry prices
            - close_price (list[float]): Exit targets
            - stop_price (float): Stop-loss price
            - timeframe (int): Recommended timeframe (minutes)
    
    Flow:
        1. Initialize result variables (all default NOTHING/empty)
        2. Build level lists (support/resistance) from multiple timeframes
        3. Evaluate each registered strategy:
            a. Call strategy.check_conditions()
            b. If conditions met: call strategy.check() to get action + prices
            c. Apply priority-based resolution
            d. Count active strategies
        4. Detect conflicts (multiple OPEN signals)
        5. Return final action tuple
    
    Key Behaviors:
        - Predictor and NN outputs pre-computed by Data layer; strategies consume via DataPoint.get()
        - Levels aggregated across 5, 15, 60, 240 min timeframes
        - First CLOSE signal breaks evaluation (absolute priority)
        - Multiple OPEN signals trigger NOTHING (conflict avoidance)
    """
    
    # Initialize result container
    res_action = STRATEGY_ACTION_NOTHING
    res_open_price = []
    res_close_price = []
    res_stop_price = 0.0
    res_time_frame = 15
    
    # Build level lists from multiple timeframes
    levels_support = []
    levels_resistance = []
    
    LEVELS_tf = [5, 15, 60, 240]
    for ltf in LEVELS_tf:
        pred_support, _ = data.get_levels(ltf, LEVEL_TYPE_AUTO_SUPPORT, ["ema_25", "ema_50", "ema_100"])
        pred_resistance, _ = data.get_levels(ltf, LEVEL_TYPE_AUTO_RESISTANCE, ["ema_25", "ema_50", "ema_100"])
        levels_support += pred_support
        levels_resistance += pred_resistance
    
    # Sort levels by proximity to current price
    levels_support.sort(key=lambda x: x[0])
    levels_resistance.sort(key=lambda x: x[0])
    
    cur_price = data.get_cur_price("close", 0, 1)
    
    # Evaluate all registered strategies
    count_active_strategies = 0
    for strategy_state, strategy in self.strategies.items():
        # Check conditions gate
        if strategy.check_conditions(data, position_state, action_msg):
            # Execute strategy
            action, open_price, close_price, stop_price, time_frame = strategy.check(
                data, position_state, position_target, action_msg
            )
            
            # Apply priority-based resolution
            if action == STRATEGY_ACTION_NOTHING:
                if res_action == action:
                    res_open_price = open_price
                    res_close_price = close_price
                    res_stop_price = stop_price
                    res_time_frame = time_frame
                continue
            
            elif action == STRATEGY_ACTION_CLOSE_LONG:
                res_action = action
                res_open_price = open_price
                res_close_price = close_price
                res_stop_price = stop_price
                res_time_frame = time_frame
                break  # CLOSE is absolute priority
            
            elif action == STRATEGY_ACTION_CLOSE_SHORT:
                res_action = action
                res_open_price = open_price
                res_close_price = close_price
                res_stop_price = stop_price
                res_time_frame = time_frame
                break  # CLOSE is absolute priority
            
            elif action in [STRATEGY_ACTION_MOVE_STOP_LOSS_LONG, STRATEGY_ACTION_MOVE_STOP_LOSS_SHORT]:
                res_action = action
                res_open_price = open_price
                res_close_price = close_price
                res_stop_price = stop_price
                res_time_frame = time_frame
                count_active_strategies += 1
            
            elif action in [STRATEGY_ACTION_OPEN_LONG, STRATEGY_ACTION_OPEN_SHORT]:
                res_action = action
                res_open_price = open_price
                res_close_price = close_price
                res_stop_price = stop_price
                res_time_frame = time_frame
                count_active_strategies += 1
            
            # ... Other action types handled similarly ...
            
            # Conflict detection: multiple OPEN signals
            if count_active_strategies > 1:
                cur_price = data.get_cur_price("close", 0, 1)
                res_action = STRATEGY_ACTION_NOTHING
                res_open_price = []
                res_close_price = [cur_price]
                res_stop_price = cur_price * (1 - 0.01)  # 1% SL
                res_time_frame = 15
                log_error("ERROR: more than one active strategy")
                break
    
    # Log results and return
    log("strategy_manager:check(): %d, %s, %s, %.4f, %d" % (
        res_action, str(res_open_price), str(res_close_price), res_stop_price, res_time_frame
    ))
    return res_action, res_open_price, res_close_price, res_stop_price, res_time_frame
```

---

## 6. Helper Methods

### 6.1 Per-tick call pattern

`set_data()` is removed. `data` is passed directly as the first argument to `check()` each tick:

```python
# Robot / TrainRobot call site — per tick:
action, *prices = manager.check(data_point, position_state, position_target, action_msg)
```

There is no per-tick setup call and no cached data reference inside StrategyManager.

### 6.2 Supporting Methods

**`check_price_stoped_rising(t, atr_abs)`** and **`check_price_stoped_falling(t, atr_abs)`** — price rejection/bounce detection logic. These are market analysis and belong in the Data layer as `IndicatorField` subclasses. StrategyManager will consume the resulting boolean columns via `DataPoint.get()`.

**Depth methods (`set_profit_by_depth`, `set_lowest_buy_by_depth`, `set_stop_loss_by_depth`)** — order book depth adjustment for profit/SL targets. **Live-only** (require live order book data unavailable in simulation). Pending removal from StrategyManager; will move to a dedicated live-trading module.

```python
def get_best_pair(self, grid_profit, grid_sl, step, sufix, action_msg):
    """
    Select best risk-reward pair from NN probability grids.
    
    Parameters:
        grid_profit: Profit probability distribution
        grid_sl: Stop-loss probability distribution
        step: Grid resolution
        sufix: "L" for long, "S" for short
        action_msg: Logging
    
    Returns:
        Tuple (profit_prc, sl_prc): Selected target and stop-loss percentages
    
    Logic:
        - Filter for high-probability success (1 - failure_prob > threshold)
        - Select pair with minimum expected profit (risk-aware selection)
        - Avoid low-probability or very tight stops
    """
    # ... Pair selection logic ...
    return res_prof, res_sl
```

---

## 7. Predictor and NN Output Access

StrategyManager does **not** own, load, or cache predictors or NN models. All such outputs are computed by the Data layer as `IndicatorField` subclasses and pre-written into the wide DataFrame (simulation) or live OHLC DataFrame. Strategies and StrategyManager access them identically to any other indicator:

```python
# Example: consume NN probability column via DataPoint
nn_long_prob = data.get("nn_prob_long", tf=60)
rejection_stopped = data.get("price_stopped_rising", tf=15)
```

Predictor outputs (expected next high/low) and NN classification probabilities are `{tf}_*` columns in the Data layer. No separate loading or `USE_NN_SIMULATION` branching lives in StrategyManager.

---

## 8. Action Resolution Priority

### Priority Order (Enforced in check() loop)
```
1. STRATEGY_ACTION_DO_STOP_LOSS          → SET + IMMEDIATE BREAK (highest priority)
2. STRATEGY_ACTION_CLOSE_LONG/SHORT      → SET + IMMEDIATE BREAK
3. STRATEGY_ACTION_CLOSE_LONG_PART/SHORT_PART → SET + IMMEDIATE BREAK
4. STRATEGY_ACTION_MOVE_STOP_LOSS_*      → SET, continue (unless conflict detected)
5. STRATEGY_ACTION_OPEN_LONG/SHORT       → SET, continue (count conflicts)
6. STRATEGY_ACTION_NOTHING               → Continue
```

All priority-1 through 3 actions are returned to the Execution layer — the loop breaks immediately and the action is propagated via `res_action`.

### Conflict Handling
- **No Conflict:** Single strategy fires → Accept action
- **Multiple OPEN:** count_active_strategies > 1 → Return NOTHING (skip trade)
- **DO_STOP_LOSS / CLOSE Detected:** Set res_action + break immediately

---

## 9. Existing Approach Strengths

### Modularity
- Strategies registered as pluggable components
- Each strategy independent; no cross-strategy dependencies
- Easy to enable/disable strategies via register methods

### Simplicity
- First-match-wins for CLOSE actions (deterministic)
- Conflict detection prevents contradictory trades
- Clear priority hierarchy

### Flexibility
- Test mode vs. production mode
- Environment variable controls (NN simulation)
- Extensible NN caching per classification

---

## 10. Potential Improvements

### 10.1 Config-Based Strategy Loading
```python
def register_strategies(self):
    config = load_config('strategies.json')  # {"long": true, "short": false, ...}
    if config['long']:
        self.strategies[0] = StratLong1_v1(...)
    if config['short']:
        self.strategies[1] = StratShort1_v1(...)
```

### 10.2 Weighted Voting
Replace first-match with confidence-weighted selection:
```python
strategy_scores = []
for strategy, action in strategy_results:
    confidence = strategy.get_confidence()
    strategy_scores.append((action, confidence))

final_action = max(strategy_scores, key=lambda x: x[1])[0]
```

### 10.3 NN-Aware Strategy Selection
```python
# Load NN prediction for this point
nn_prediction = self.nn.predict(cur_data)

# Only execute strategies aligned with NN prediction
if nn_prediction == NN_TARGET_BUY and action == STRATEGY_ACTION_OPEN_SHORT:
    continue  # Skip conflicting short when NN says buy
```

### 10.4 Strategy Performance Tracking
```python
self.strategy_stats = {
    strategy_id: {
        'win_rate': 0.0,
        'avg_pnl': 0.0,
        'trades': 0
    }
}

# Update after position close
self.strategy_stats[winning_strategy]['trades'] += 1
self.strategy_stats[winning_strategy]['avg_pnl'] += pnl
```

### 10.5 Dynamic Strategy Enable/Disable
```python
# Disable strategy if win rate drops below threshold
if self.strategy_stats[sid]['win_rate'] < 0.40:
    self.disabled_strategies.add(sid)

# In check():
if strategy_id not in self.disabled_strategies:
    evaluate_strategy(strategy)
```

### 10.6 Multi-Timeframe Confirmation
```python
# Require trend alignment across timeframes before OPEN
uptrend_5m = self.trend_signals[5].check(...)
uptrend_15m = self.trend_signals[15].check(...)
uptrend_60m = self.trend_signals[60].check(...)

if action == STRATEGY_ACTION_OPEN_LONG:
    if not (uptrend_5m and uptrend_15m and uptrend_60m):
        continue  # Skip if trends misaligned
```

### 10.7 NN Probability Grids for Stops
```python
# Use NN failure grids to place more intelligent stops
long_fail_grid = nn.get_failure_grid(NN_TARGET_BUY, 240)
optimal_sl = long_fail_grid[0.05]  # 5% failure probability
strategy_result.stop_price = optimal_sl
```

### 10.8 Timeout for Strategies
```python
# Track how long each strategy has been evaluating
if time.time() - strategy_start_time > timeout_seconds:
    log_error(f"Strategy {sid} timeout")
    # Fallback to NOTHING or previous action
```

### 10.9 Cooldown Between Opposite Signals
```python
# Prevent alternating LONG/SHORT too frequently
if last_action == STRATEGY_ACTION_OPEN_LONG and current_action == STRATEGY_ACTION_OPEN_SHORT:
    if elapsed_time < MIN_COOLDOWN:
        skip_action()  # Cooldown period
```

### 10.10 Strategy Compositing (Ensemble)
```python
# Combine multiple strategies for final decision
ensemble_vote = {}
for strategy, action in strategy_results:
    ensemble_vote[action] = ensemble_vote.get(action, 0) + 1

# Action with most votes wins
final_action = max(ensemble_vote, key=ensemble_vote.get)
```

---

## 11. Testing Strategy

### Unit Tests
- Test strategy registration (both test and production modes)
- Test action priority resolution with mock strategies
- Test conflict detection (multiple OPEN signals)
- Test NN loading and caching

### Integration Tests
- Simulate manager with multiple strategies
- Verify CLOSE signals break evaluation
- Confirm position_state gating works
- Test level aggregation across timeframes

### End-to-End Tests
- Full trading session with mock data
- Verify deterministic output (same input → same output)
- Test NN integration with precomputed data

---

## 12. Files & Dependencies

**Primary File:**
- `/home/om/projects/pybtctr2_brainstorm/pybtctr2_brainstorm_ai/strategy_manager.py`

**Imports:**
- Strategy classes: `ExampleStrategyLong`, `ExampleStrategyShort` (reference); `StratLong1_v1`, `StratShort1_v1` (production, `strategies/`)
- Constants: All `STRATEGY_ACTION_*`, `POSITION_STATE_*`

**Data Flow:**
```
[Per Tick]
check(data_point, position_state, position_target, action_msg)
    ├─ data_point carries all indicators, predictor outputs, NN columns
    ├─ Evaluate StratLong1_v1(data_point, ...)
    │   └─ Return (action_long, prices_long)
    ├─ Evaluate StratShort1_v1(data_point, ...) (if enabled)
    │   └─ Return (action_short, prices_short)
    ├─ Apply priority: DO_STOP_LOSS > CLOSE > MOVE_SL > OPEN
    ├─ Detect conflicts
    └─ Return final (action, open_price, close_price, stop_price, tf)
        |
        ↓ Robot.execute()
```

---

## 13. Fee Injection Rules

Fee originates from `EXCHANGE_FEE` environment variable (Infrastructure layer), read once at startup by `base_stock.py` and exposed as `stock.item.fee`. The propagation chain is:

```
EXCHANGE_FEE (*.env)
    ↓ os.environ read at startup
stock.item.fee
    ↓ constructor parameter
StrategyManager(data, fee, ...)   ← self.fee
    ↓ constructor parameter
Strategy(data, fee)               ← self.fee
    ↓ constructor parameter (via Robot/TrainRobot)
Position(thread_num, fee, data)   ← self.fee
```

**Rules enforced throughout:**
- No class-level `fee` default on Strategy, StrategyManager, or Position — missing fee must fail at construction
- No hardcoded fee literals inside methods — always reference `self.fee`
- `2 * self.fee` is the round-trip cost (open fill + close fill) — computed inline, not stored as a separate constant
- `get_best_pair()` and all depth-adjustment helpers use `self.fee`, never a local literal

---

## 14. Summary

`StrategyManager` is the orchestration layer that coordinates multiple independent strategies into a single, deterministic action. Its core responsibility is conflict resolution: prioritizing CLOSE actions, preventing multiple conflicting OPENs, and ensuring consistent decision-making. The current implementation emphasizes simplicity (first-match-wins) and clarity (explicit priority order). Key enhancements focus on confidence-based voting, NN integration for filtering, performance tracking for dynamic strategy selection, and multi-timeframe confirmation. NN support is partially implemented (caching, simulation loading) but not fully active; activating it would require enabling the commented strategy loading and ensuring full inference pipelines are available.
