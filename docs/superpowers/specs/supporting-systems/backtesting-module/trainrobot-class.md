# TrainRobot Class Specification

**Class:** `TrainRobot`  
**File:** `train_robot.py` (lines 43-450+)  
**Purpose:** Simulate trading strategy execution on historical data, managing positions, executing trades, and accumulating performance metrics for backtesting.

---

## 1. Class Overview

The `TrainRobot` class is the core backtesting engine in pybtctr2. It simulates how trading strategies would perform on historical data by replaying market conditions point-by-point and executing the same logic as the live Robot. Rather than connecting to Binance, TrainRobot consumes pre-generated OHLC candles and signals, evaluates strategy conditions, and simulates buy/sell execution.

TrainRobot maintains position state throughout a backtest period, transitioning between open, closing, and closed states. It accumulates revenue (fees-inclusive) and tracks trades at the individual and aggregate levels. The class is designed for parallel execution—multiple instances can process independent time segments, then results are aggregated by the Trainer orchestrator.

Key design principle: TrainRobot uses the same StrategyManager as live Robot, ensuring backtest behavior matches production behavior.

---

## 2. Key Attributes

### Class Variables

| Attribute | Type | Description |
|-----------|------|-------------|
| `total_revenue` | `float` | Cumulative revenue across all trades (relative: PnL / initial capital). Shared across instances but typically thread-local. |
| `total_revenue_by_id` | `dict` | Revenue breakdown by strategy ID. Maps `{"revenue": float, "revenue_abs": float}`. |
| `total_revenue_abs` | `float` | Absolute revenue in USD equivalent (accounting for fees). |

### Instance Variables

| Attribute | Type | Description |
|-----------|------|-------------|
| `data` | `data.Data` | Current OHLC data point being processed. Updated each iteration via implicit data reference. |
| `thread_num` | `int` | Thread identifier for parallel execution (0 for single-threaded). Used in logging and result file naming. |
| `strategy_mngr` | `StrategyManager` | Strategy evaluator. Checks signals, generates actions (OPEN_LONG, CLOSE_SHORT, etc.). |
| `position` | `Position` | Position tracker. Maintains entry/exit prices, quantity, fees, PnL, state machine. |
| `position_tf` | `int` | Position timeframe (minutes). Copied from strategy action's timeframe; used for logging. Default: 15. |

---

## 3. Constructor

### `__init__(thread_num=0)`

**Purpose:** Initialize a TrainRobot instance for backtesting a time segment.

**Parameters:**
- `thread_num` (`int`) — Thread/process identifier for parallel execution tracking. Default: 0

**Behavior:**
1. Initialize `data` as new Data instance with default pair
2. Store `thread_num` parameter
3. Set trading fee: `fee = 0.002` (0.2%)
4. Create StrategyManager instance:
   - Pass `data`, `fee`, and False (not live mode)
5. Create Position tracker:
   - Pass `thread_num`, fee, and data reference
6. Set `position_tf = 15` (default position timeframe for logging)
7. Initialize empty `total_revenue` (0.0)
8. Initialize empty `total_revenue_by_id` dict
9. Initialize empty `total_revenue_abs` (0.0)
10. Log initialization: "START: usd({position.full_position})"
11. Log position_tf and "TEST COMMENT" markers

**Preconditions:**
- Data module must be importable
- StrategyManager and Position classes must be available
- Default pair must be configured via environment

**Postconditions:**
- Instance ready to process data points via `do()`
- Position state initialized to closed
- Ready to accumulate revenue

**Example:**
```python
robot = TrainRobot(thread_num=0)  # Initialize first thread
# Later: iterate through data, calling robot.do() for each point
```

---

## 4. Key Methods & Interfaces

### 4.1 Simulation Loop

#### `do()`

**Purpose:** Execute one iteration of backtesting (process one data point).

**Return Value:** `None`

**Behavior:**

1. **Initialize Action Message:**
   ```python
   action_msg = Action()
   action_msg.multiply_pos = []
   action_msg.multiply_msg = []
   action_msg.time = self.data.cur_point
   ```

2. **Log Position State:**
   - `log(self.position.get_verbose_state())`
   - Outputs current position: open price, quantity, PnL, state

3. **Check Position Action Queue:**
   ```python
   pos_action = self.position.get_action()
   if pos_action == STRATEGY_ACTION_OPEN_LONG or STRATEGY_ACTION_CLOSE_SHORT:
       self.buy(action_msg)
   elif pos_action == STRATEGY_ACTION_OPEN_SHORT or STRATEGY_ACTION_CLOSE_LONG:
       self.sell(action_msg)
   ```
   - If position has queued action: execute it
   - Otherwise: proceed to strategy evaluation

4. **Evaluate Strategy (if No Position Action):**
   ```python
   self.strategy_mngr.data.set_position_state(self.position.get_state())
   self.strategy_mngr.data.set_position_type(self.position.get_position_type())
   strategy_action, open_p, close_p, stop_p, tf = self.strategy_mngr.check(
       self.position.get_state(),
       self.position.get_target(),
       action_msg
   )
   self.wait(strategy_action, open_p, close_p, stop_p, tf, action_msg)
   ```
   - Set position context on strategy manager
   - Check signals and generate action
   - Handle action via `wait()`

5. **Save Action Message:**
   ```python
   action_msg.time = self.strategy_mngr.data.cur_point
   action_msg.save(self.strategy_mngr.data.cur_point)
   ```
   - Persist to disk for later analysis

6. **Exception Handling:**
   ```python
   try:
       # ... main logic
   except Exception as exc:
       date_time_string = datetime.fromtimestamp(self.data.cur_point).strftime(...)
       log("EXCEPTION: " + str(date_time_string) + ": " + str(exc))
       print(traceback.format_exc())
   ```
   - Catch any exception, log with timestamp
   - Continue to next iteration (no crash)

**Preconditions:**
- Data must be set via implicit reference (Trainer sets on all active robots)
- StrategyManager and Position must be initialized
- Position state must be valid (OPEN, CLOSED, or transitioning)

**Postconditions:**
- Position state may have changed (OPEN → CLOSING → CLOSED, or NEW → OPEN)
- Revenue accumulated if trade closed
- Action message saved to disk

---

### 4.2 Trade Execution

#### `buy(action_msg)`

**Purpose:** Execute buy action (entry long or exit short).

**Parameters:**
- `action_msg` (Action) — Action message for recording events

**Behavior:**

1. **Get Current Low Price:**
   ```python
   price = self.data.get_cur_price("low", 0)
   ```

2. **Check Safety Buy (Closing Short):**
   ```python
   if self.position.get_state() == POSITION_STATE_WAIT_BUY:
       if price <= self.position.posImpl.get_price_close():
           price = self.position.posImpl.get_price_close()
           do_buy = True  # Execute at target close price
   ```
   - If waiting to close short and price hits target: execute

3. **Check Stop Loss (Short Position):**
   ```python
   if self.position.get_state() == POSITION_STATE_WAIT_BUY:
       if price > self.position.posImpl.price_stop_loss:
           price = max(price, self.position.posImpl.price_stop_loss)
           log("robot:buy(): STOP LOSS!!!")
           do_buy = True
   ```
   - If short position exceeding stop loss: execute at stop loss price

4. **Check Entry (Open Long):**
   ```python
   if self.position.get_action() == STRATEGY_ACTION_OPEN_LONG:
       if self.position.posImpl.check_stop_open(price):
           if self.position.is_closed():
               self.position.finalize()
           return  # Entry failed validation
       if self.position.close_by_time(action_msg):
           # Time-based exit triggered
           return
       if price <= self.position.posImpl.get_price_open():
           price = self.position.posImpl.get_price_open()
           do_buy = True  # Execute at target open price
   ```
   - If action is OPEN_LONG: check entry conditions
   - If stop_open validation fails: finalize and return
   - If time-based close triggered: handle and return
   - If price hits target: execute

5. **Process Buy (if do_buy=True):**
   ```python
   amount = self.position.posImpl.get_coinBuy().action_amount
   self.position.process_action(amount/price, price)
   log("robot:simulste_buy(): BUY COMPLIT")
   ```
   - Calculate buy quantity: `amount / price` (coins)
   - Update position with quantity and price

6. **Update Position State (after buy):**
   ```python
   if self.position.get_state() == POSITION_STATE_WAIT_BUY:
       if self.position.is_closed():  # Short trade now closed
           action_msg.add_multiply_action(price, "CLOSE SHORT DONE")
           revenue, revenue_abs = self.position.finalize()
           self.total_revenue += revenue
           self.total_revenue_abs += revenue_abs
           log_revenue("TOTAL revenue: %f" % self.total_revenue, ...)
           return
       else:
           # Still partially open; transition
           self.position.set_state(POSITION_STATE_WAIT_BUY)
           self.position.set_action(STRATEGY_ACTION_NOTHING)
   ```
   - If position fully closed: finalize and accumulate revenue
   - Else: transition to next state

**Preconditions:**
- Position must be valid
- Price data must be available in current candle

**Postconditions:**
- Position quantity updated
- If position closed: revenue accumulated, state reset
- Action message updated with buy event

#### `sell(action_msg)`

**Purpose:** Execute sell action (exit long or entry short).

**Parameters:**
- `action_msg` (Action) — Action message for recording events

**Behavior:** (Mirror of `buy()` but for sell side)

1. Get current high price
2. Check safety sell (long closing)
3. Check stop loss (long position)
4. Check entry (open short)
5. Process sell if triggered
6. Update position state; finalize if closed

---

### 4.3 Action Deferral & State Management

#### `wait(strategy_action, action_open_price, action_close_price, action_stop_price, action_time_frame, action_msg)`

**Purpose:** Handle deferred actions and position state transitions.

**Parameters:**
- `strategy_action` (`int`) — Action code (OPEN_LONG, CLOSE_LONG, WAIT, etc.)
- `action_open_price` (`float`) — Entry price for opening trades
- `action_close_price` (`float`) — Exit price for closing trades
- `action_stop_price` (`float`) — Stop-loss price
- `action_time_frame` (`int`) — Timeframe of signal (minutes)
- `action_msg` (Action) — Message object

**Behavior:**

1. **Check Stop Loss Setup:**
   ```python
   if self.position.check_stop_loss():
       if not self.position.setup_stop_loss():
           assert False, "Couldn't setup stop loss"
       log("STOP_LOSS %s %d" % (action, position_tf))
       
       if self.position.get_position_type() == POSITION_TYPE_LONG:
           self.sell(action_msg)  # Exit long
       if self.position.get_position_type() == POSITION_TYPE_SHORT:
           self.buy(action_msg)   # Exit short
   ```
   - If position needs stop loss: set it up and exit

2. **Safety Update:**
   ```python
   new_strategy_action = self.position.safety_update(strategy_action, action_msg)
   if new_strategy_action != strategy_action:
       log("safety_update: strategy_action = %d" % new_strategy_action)
       strategy_action = new_strategy_action
       action_time_frame = self.position.posImpl.time_period
   ```
   - Position may override action for safety reasons

3. **Handle Entry (OPEN_LONG or OPEN_SHORT):**
   ```python
   if strategy_action == STRATEGY_ACTION_OPEN_LONG or STRATEGY_ACTION_OPEN_SHORT:
       do_open = self.position.open(
           strategy_action, action_open_price, action_close_price,
           action_stop_price, action_time_frame, action_msg
       )
       if do_open:
           self.position_tf = action_time_frame
           log("OPEN LONG/SHORT")
           
           if strategy_action == STRATEGY_ACTION_OPEN_LONG:
               self.buy(action_msg)
           else:
               self.sell(action_msg)
   ```
   - Call position.open() to validate and set up entry
   - If successful: execute fill (buy/sell)

4. **Handle Exit (CLOSE_LONG or CLOSE_SHORT):**
   ```python
   if (strategy_action == STRATEGY_ACTION_CLOSE_LONG and
       self.position.get_position_type() == POSITION_TYPE_LONG) or ...:
       
       self.position.set_action(strategy_action)
       do_close = self.position.close(
           strategy_action, action_close_price, action_stop_price,
           action_time_frame, action_msg
       )
       if do_close:
           log("CLOSE LONG/SHORT")
           if strategy_action in [CLOSE_LONG, CLOSE_LONG_PART]:
               self.sell(action_msg)
           else:
               self.buy(action_msg)
   ```
   - Call position.close() to initiate exit
   - If successful: execute fill

**Preconditions:**
- Position must be in valid state
- Action parameters must be valid

**Postconditions:**
- Position state may have changed (OPEN → CLOSING, CLOSING → CLOSED, CLOSED → OPENING)
- Trades may have been executed
- Stop loss may have been set up

---

## 5. State Management

### Position State Machine

```
CLOSED
  ↓
OPENING (position.open() called, not yet filled)
  ↓
OPEN (entry filled, holding position)
  ↓
CLOSING (exit initiated, waiting for fill)
  ↓
CLOSED (position finalized, revenue accumulated)
```

TrainRobot transitions position through states based on:
- Strategy signals (OPEN_LONG, CLOSE_LONG)
- Price action (entry/exit prices hit)
- Time-based rules (position duration exceeded)
- Safety rules (stop loss, risk limits)

---

## 6. Error Handling

**Exception in do():**
```python
except Exception as exc:
    log("EXCEPTION: " + str(date_time_string) + ": " + str(exc))
    print(traceback.format_exc())
    # Continues to next iteration; no crash
```

Exceptions logged but not fatal. Allows backtest to continue despite errors in signal evaluation or position logic.

**Failed Stop Loss Setup:**
```python
if not self.position.setup_stop_loss():
    assert False, "Couldn't setup stop loss"
```

Should not happen in backtest (data complete). Assertion for development; would fail the backtest if triggered.

**Invalid Position State:**
If position state machine enters unexpected state (e.g., CLOSED → SELLING), logic should gracefully ignore or handle via position's internal checks.

---

## 7. Existing Approach

### Direct Data Reference

Robot instances don't fetch data themselves. Data is implicitly available via class variable or passed by Trainer. This design allows all robots to operate on same data at same timestamp, enabling synchronized backtests.

### Position-Centric Execution

Rather than centralizing buy/sell logic, TrainRobot delegates to Position class:
- Position.open() — Validates entry conditions
- Position.close() — Validates exit conditions
- Position.process_action() — Executes fill, updates PnL

This separation keeps TrainRobot focused on simulation loop, delegating position logic to Position.

### Signal & Strategy Reuse

TrainRobot uses same StrategyManager as live Robot:
```python
self.strategy_mngr = StrategyManager(self.data, fee, False)
```

The `False` flag indicates backtest mode. This ensures backtest logic matches live trading logic—same signals, same thresholds.

### Fee-Inclusive Revenue Tracking

Two revenue metrics:
- **relative** (`total_revenue`): PnL as percentage of capital
- **absolute** (`total_revenue_abs`): USD-equivalent with fees deducted

Enables evaluation of strategy profitability under different capital levels.

---

## 8. Potential Improvements

1. **Add Equity Curve Tracking**
   - Record cumulative equity at each time point
   - Enable drawdown analysis and equity curve visualization

2. **Implement Partial Position Management**
   - Support scaling into position (multiple entries)
   - Scaling out (partial exits with trailing stops)
   - Would improve realism on complex strategies

3. **Add Trade Annotation**
   - Store entry/exit reason per trade
   - Track which signal triggered the action
   - Would improve post-backtest analysis

4. **Support Multiple Positions**
   - Allow multiple concurrent trades (long + short simultaneously)
   - Track per-pair position independently
   - Would enable more complex strategies

5. **Implement Order Time-in-Force**
   - Limit orders expire after N candles
   - Market orders execute immediately
   - Would prevent phantom fills on stale signals

6. **Add Realistic Slippage**
   - Apply random price deviation to fills
   - Model market impact based on volume
   - Would improve accuracy on real trading

7. **Support Bracket Orders**
   - Link entry to take-profit and stop-loss automatically
   - Ensure position closed within expected range
   - Would improve risk management

8. **Add Performance Attribution**
   - Track revenue contribution by signal type
   - Identify which signals drive profits
   - Would guide strategy optimization

9. **Implement Lazy Data Loading**
   - Load only required candles into memory
   - Reduce memory footprint on long backtests
   - Would enable backtests on resource-limited systems

10. **Add Statistical Validation**
    - Calculate Sharpe ratio, sortino ratio, win rate
    - Detect regime changes in performance
    - Would provide statistical confidence in results
