# BasePosition Class Specification

**File:** `position/base_position.py`  
**Inheritance:** Base class (abstract); subclassed by `LongPosition` and `ShortPosition`  
**Status:** Active (core trading position abstraction)

---

## 1. Class Overview

### Purpose

`BasePosition` is an abstract state machine that manages the complete lifecycle of a single trade position from initialization through finalization. It enforces strict state transitions, manages asset tracking through Coin objects, calculates position-specific P&L, and enforces risk management constraints independent of trade direction (long or short).

The class serves as the foundational abstraction layer for position management, defining the contract that all position types must fulfill. It prevents invalid state transitions, tracks execution history at multiple price levels, manages graduated entry/exit strategies, and provides serialization for position persistence.

### Key Responsibilities

1. **State Machine Enforcement**: Validates and manages position state transitions (WAIT → OPEN_pending → OPEN_active → CLOSE_pending → WAIT)
2. **Asset Lifecycle Management**: Tracks buy/sell currencies (coinUse, coinGet) through their complete lifecycle with balances and action amounts
3. **P&L Calculation**: Computes revenue percentage and absolute revenue based on executed prices, fees, and position-specific logic
4. **Risk Management**: Enforces stop-loss limits, validates position sizing against available funds, checks profit thresholds
5. **Graduated Trading**: Supports multiple price levels for both entry and exit, with execution history tracking
6. **Position Metadata**: Manages timing, counters, and execution details for post-trade analysis

### Design Pattern

The class implements a **state machine pattern** with **Template Method** for subclass specialization. Abstract methods (`open()`, `close()`, `avg_price_open()`, `avg_price_close()`, etc.) define the position-specific logic that subclasses must implement, while concrete methods handle common concerns like state validation and serialization.

---

## 2. Key Attributes

| Attribute | Type | Purpose | Notes |
|-----------|------|---------|-------|
| **state** | int (POSITION_STATE_*) | Current position state | One of WAIT, WAIT_BUY, WAIT_SELL, WAIT_SAFETY_BUY, WAIT_SAFETY_SELL, WAIT_BUY_SIGNAL, WAIT_SELL_SIGNAL |
| **action** | int (STRATEGY_ACTION_*) | Current action type | NOTHING, OPEN_LONG, OPEN_SHORT, CLOSE_LONG, CLOSE_SHORT, DO_STOP_LOSS, MOVE_STOP_LOSS_*, CLOSE_*_PART, SET_MOVING_STOP_LOSS_* |
| **position_type** | int (POSITION_TYPE_*) | Long or short indicator | POSITION_TYPE_LONG, POSITION_TYPE_SHORT, POSITION_TYPE_UNKNOWN |
| **coinUse** | Coin object | Currency spent in trade | For long: coin_base (USDT); for short: coin (e.g., LINK). Tracks size, used, returned amounts |
| **coinGet** | Coin object | Currency received in trade | For long: coin (e.g., LINK); for short: coin_base (USDT). Tracks action_amount for graduated exit |
| **price_open** | list of float | Target entry prices (graduated) | Multiple levels support scaled/averaged entry; updated by `open()` |
| **price_close** | list of float | Target exit prices (graduated) | Multiple levels support scaled exit; updated by `close()` |
| **price_stop_loss** | float | Stop-loss trigger price | Single value; adjusted dynamically via `set_stop_loss()` |
| **action_price** | float | Associated action price | Reference price for current action; used in action messaging |
| **executed_open** | list of float | Recorded entry execution prices | Appended when entry executed; used to find next unexecuted level |
| **executed_open_amount** | list of float | Amounts executed at each open level | Parallel to executed_open; tracks quantity per price level |
| **executed_close** | list of float | Recorded exit execution prices | Appended when exit executed; determines position remaining |
| **executed_close_amount** | list of float | Amounts executed at each close level | Parallel to executed_close; tracks quantity per price level |
| **open_time** | int (unix ms) | Position entry timestamp | Set when `open()` succeeds |
| **safety_close_time** | int (unix ms) | Deadline for reaching target before forced close | Calculated from `safety_time_intervals`; triggers `close_by_time()` |
| **time_period** | int (minutes) | Timeframe/candle period of entry | e.g., 5, 15, 60; stored for context |
| **count_open** | int | Entry execution counter | Tracks number of partial fills |
| **expected_target** | float | Expected profit target | Target revenue or price level |
| **fee** | float | Taker fee percentage — injected from `stock.item.fee` via Robot/TrainRobot; never hardcoded | Affects risk/profit calculations |
| **desired_revenue** | float | Target revenue percentage | Used in strategy signal evaluation |
| **risk_per_trade** | float | Risk allocation as % of capital | e.g., 0.05 (5%); constrains position sizing |
| **full_position** | float | Maximum position size (absolute) | Cap on position value; used in sizing calculations |
| **safety_time_intervals** | int | Multiplier for safety deadline | Interval count; safety_close_time = now + (value * 15 min) |
| **use_safety** | bool | Whether the WAIT_SAFETY_* phase is active | If False, `record_entry_fill()` transitions directly to exit-awaiting state, skipping safety management |
| **thread_num** | int | Thread/process identifier | For logging and parallel execution tracking |
| **coin_use** | str | Name of currency spent in trade | e.g. "USDT" for Long, "BTC" for Short; constructor param, replaces data.coin_base/data.coin |
| **coin_get** | str | Name of currency received in trade | e.g. "BTC" for Long, "USDT" for Short; constructor param |

---

## 3. Constructor

### Signature
```python
def __init__(self, coin_use: str, coin_get: str, full_position, thread_num, fee, use_safety: bool = True)
```

### Parameters

| Parameter | Type | Default | Purpose |
|-----------|------|---------|---------|
| **coin_use** | str | — | Currency symbol spent in trade (e.g. "USDT" for Long, "BTC" for Short) |
| **coin_get** | str | — | Currency symbol received in trade (e.g. "BTC" for Long, "USDT" for Short) |
| **full_position** | float | — | Maximum position size in base currency (e.g., USD amount) |
| **thread_num** | int | — | Identifier for logging/tracking in parallel execution |
| **fee** | float | — | Taker fee from `stock.item.fee` — passed in by caller; never a default constant |
| **use_safety** | bool | `True` | Whether to use the WAIT_SAFETY_* holding phase. If `False`, `record_entry_fill()` skips directly to exit-awaiting state and `safety_update()` is a no-op |

### Initialization Steps

1. Store instance parameters: `coin_use`, `coin_get`, `thread_num`, `fee`
2. Set `position_type = POSITION_TYPE_UNKNOWN` (overridden by subclass)
3. Call `do_init()` to initialize all trading state:
   - Clear price lists: `price_open = []`, `price_close = []`, `price_stop_loss = 0`
   - Clear execution history: `executed_open = []`, `executed_close = []`, etc.
   - Create coin objects: `coinUse = Coin()`, `coinGet = Coin()`
   - Set initial state: `state = POSITION_STATE_WAIT`
   - Set initial action: `action = STRATEGY_ACTION_NOTHING`
   - Initialize timing: `open_time = 0`, `safety_close_time = 0`

### Postconditions

- Position is ready to accept `open()` call
- All price lists are empty (no trade active)
- State is WAIT (neutral/idle)
- All coin balances are zero

### Exceptions

- None (constructor always succeeds if data object is valid)

---

## 4. Key Methods & Interfaces

### 4.1 State Transition Methods

#### `open(strategy_action, price_open, price_close, price_stop_loss, time_period, action_msg)`

**Purpose:** Transition position from WAIT to OPEN states and initialize trading parameters.

**Preconditions:**
- State must be POSITION_STATE_WAIT
- `price_open`, `price_close`, `price_stop_loss` must be valid prices (> 0); risk/reward already validated by Strategy before `open()` is called
- `price_stop_loss` must be on the loss side of `price_open[0]` (enforced by subclass)
- Strategy action must be OPEN_LONG or OPEN_SHORT
- Enough available funds in coinUse

**Parameters:**
- **strategy_action** (int): STRATEGY_ACTION_OPEN_LONG or OPEN_SHORT
- **price_open** (list of float): Graduated entry prices; position will attempt all levels
- **price_close** (list of float): Target exit prices matching entry levels
- **price_stop_loss** (float): Loss-side boundary price
- **time_period** (int): Candle period in minutes (5, 15, 60, etc.)
- **action_msg** (Action object): Message object for logging/multiplying actions

**Implementation (Subclass):**
- Calculate average entry price from price_open list
- Calculate position size using risk_per_trade (risk/reward ratio was validated by Strategy)
- Set `price_open`, `price_close`, `price_stop_loss` lists
- Set `action = STRATEGY_ACTION_OPEN_LONG/SHORT`
- Set `open_time = cur_time` (passed by caller)
- Set `safety_close_time = make_future_timestamp(safety_time_intervals * 15, cur_time)`
- Initialize `coinUse.action_amount = coinUse.want_to_use / len(price_open)`
- Return True on success

**Postconditions:**
- State transitions to WAIT_BUY (short) or WAIT_SELL (long)
- action is set to OPEN_LONG or OPEN_SHORT
- Price lists populated with graduated levels
- Execution history cleared (ready for first fill)

**Return:** bool (True if position opened, False if validation failed)

**Exceptions:**
- None (failures return False; logged via action_msg)

---

#### `close(strategy_action, price_close, price_stop_loss, time_period, action_msg)`

**Purpose:** Transition position from OPEN states to CLOSE states and update exit parameters.

**Preconditions:**
- State must be a "wait close" state (WAIT_SELL for long, WAIT_BUY for short)
- `price_close` must be valid (> 0)
- `is_wait_close_state()` must return True

**Parameters:**
- **strategy_action** (int): STRATEGY_ACTION_CLOSE_LONG, CLOSE_SHORT, or partial variant
- **price_close** (list of float): Target exit price(s)
- **price_stop_loss** (float): Updated stop-loss boundary
- **time_period** (int): Candle period
- **action_msg** (Action object): Message object for logging

**Implementation (Subclass):**
- Verify `is_wait_close_state()` returns True
- Update close prices via `update_price_close()`
- Set stop-loss via `set_stop_loss()`
- Set action to CLOSE_LONG, CLOSE_SHORT, or partial variant
- If partial close: set action to CLOSE_*_PART and reduce action_amount

**Postconditions:**
- Price close updated
- Stop-loss adjusted
- Action set to close variant
- State may transition to CLOSE_pending (implementation-dependent)

**Return:** None (void method)

**Exceptions:**
- None (guards via is_wait_close_state() precondition)

---

### 4.2 Price & Execution Tracking Methods

#### `record_entry_fill(coin_amount, price)` [ABSTRACT]

**Purpose:** Record the execution of an entry fill. Direction-agnostic — phase-semantic name replaces `add_buy`/`add_sell`.

**Preconditions:**
- `is_wait_open_state()` must be True
- `coin_amount > 0` and `price > 0`

**Parameters:**
- **coin_amount** (float): Number of coins that changed hands in this fill
- **price** (float): USD per coin at execution

**Implementation (Subclass):**
- Append `price` to `executed_open` and `coin_amount` to `executed_open_amount`
- Update `coinUse` and `coinGet` according to direction (see LongPosition/ShortPosition)
- Update `count_open += 1`
- Transition state to the appropriate holding state

**Postconditions:**
- Fill recorded in execution history
- Coin balances updated

**Return:** None (void)

---

#### `record_exit_fill(coin_amount, price)` [ABSTRACT]

**Purpose:** Record the execution of an exit fill. Direction-agnostic — phase-semantic name replaces `add_buy`/`add_sell`.

**Preconditions:**
- `is_wait_close_state()` must be True (or DO_STOP_LOSS action active)
- `coin_amount > 0` and `price > 0`

**Parameters:**
- **coin_amount** (float): Number of coins that changed hands in this fill
- **price** (float): USD per coin at execution

**Implementation (Subclass):**
- Append `price` to `executed_close` and `coin_amount` to `executed_close_amount`
- Update `coinUse` and `coinGet` according to direction (see LongPosition/ShortPosition)

**Postconditions:**
- Fill recorded in execution history
- Coin proceeds accumulated

**Return:** None (void)

---

#### `get_action_amount_in_coins(price)` [ABSTRACT]

**Purpose:** Convert the pending action amount from its native units into coin units. Enables Robot and TrainRobot to call a uniform interface without knowing position direction.

**Parameters:**
- **price** (float): Current USD/coin price (used for USD→coin conversion)

**Implementation (Subclass):**
- LongPosition entry: `coinUse.action_amount / price` (USD → coins)
- LongPosition exit: `coinGet.action_amount` (already coins)
- ShortPosition entry: `coinUse.action_amount` (already coins — borrow amount)
- ShortPosition exit: `coinGet.action_amount / price` (USD → coins)

**Return:** float (coin units to order)

---

#### `compute_loan(want_to_use, available_funds, available_borrow)` [CONCRETE]

**Purpose:** Calculate the margin loan amount needed to reach the desired position size. Applies to both Long (borrow USD) and Short (borrow coins).

**Parameters:**
- **want_to_use** (float): Desired position size from risk model
- **available_funds** (float): Funds already available on exchange
- **available_borrow** (float): Maximum borrow available from exchange (live only; pass `float("inf")` in simulation)

**Logic:**
```
expected_loan = max(0.0, want_to_use - available_funds)
return min(expected_loan, available_borrow)
```

**Return:** float (amount to borrow; 0.0 if no loan needed)

---

#### `get_price_open()`

**Purpose:** Return the next unexecuted entry price level.

**Preconditions:**
- `price_open` list populated

**Logic:**
- Start with `price_open[0]` (first/primary level)
- If executions exist: iterate through price_open
- Return first price that hasn't been executed yet (check against `executed_open` via `first_in_profit_strict()`)
- If all executed: return last price in list

**Return:** float (next target entry price)

---

#### `get_price_close()`

**Purpose:** Return the next unexecuted exit price level.

**Preconditions:**
- `price_close` list populated

**Logic:**
- Start with `price_close[0]`
- If executions exist: check against `best_executed_close()`
- Return first price that would profit relative to best close execution
- If all executed: return last price

**Return:** float (next target exit price)

---

#### `update_price_close(action_price)`

**Purpose:** Update a close price to match a newly calculated action price.

**Parameters:**
- **action_price** (float): New price to use for next close level

**Logic:**
- Find the close price corresponding to the next unexecuted open level
- Replace that close price with `action_price`
- If no unexecuted opens: update `price_close[0]`

**Return:** None (void)

---

#### `best_executed_open()` [ABSTRACT]

**Purpose:** Return the best (profit-side) entry price executed so far.

**Implementation (Subclass):**
- For long: return minimum executed_open price (cheapest buy)
- For short: return maximum executed_open price (most expensive sell)

**Return:** float (best entry price)

---

#### `best_executed_close()` [ABSTRACT]

**Purpose:** Return the best (profit-side) exit price executed so far.

**Implementation (Subclass):**
- For long: return maximum executed_close price (highest sell)
- For short: return minimum executed_close price (lowest buy)

**Return:** float (best exit price)

---

### 4.3 Stop-Loss & Risk Management

#### `safety_update(cur_data, cur_time, strategy_action, action_msg)`

**Parameters:**
- **cur_data** (DataPoint): Current tick data snapshot — replaces `self.data` reads
- **cur_time** (int): Current unix timestamp in ms — passed explicitly by caller
- **strategy_action** (int): Current strategy action
- **action_msg** (Action): Message object

**Return:** int (updated strategy_action)

---

#### `is_stop_loss_triggered(cur_data, cur_time)` → bool

**Parameters:**
- **cur_data** (DataPoint): Current tick data snapshot
- **cur_time** (int): Current unix timestamp in ms

**Return:** bool

---

#### `set_stop_loss(cur_data, price, action_msg, force=False)`

**Purpose:** Update stop-loss level; enforces that new stop-loss is closer to target (better risk management).

**Preconditions:**
- `price > 0` and `price != 0.0`
- State must be WAIT_CLOSE state OR `force=True`
- New price must be closer to profit side than current stop-loss (unless forced)

**Parameters:**
- **cur_data** (DataPoint): Current tick data snapshot (used for indicator lookups if needed)
- **price** (float): New stop-loss price

**Parameters:**
- **price** (float): New stop-loss price
- **action_msg** (Action): Message object for action logging
- **force** (bool): If True, bypass profit comparison and accept new price

**Logic:**
1. Validate `price != 0.0` (assert fails if zero)
2. Log test message with old/new prices
3. Check if in appropriate state: `is_wait_close_state() or force`
4. Compare profitability: `first_in_profit(price, current_stop_loss) or force`
5. If valid: update `price_stop_loss = price`, log, call `action_msg.add_multiply_action(price, "RESET_STOP")`
6. Return True if updated, False otherwise

**Postconditions:**
- Stop-loss updated only if conditions met
- Action message records the change
- Price always moves toward profit side (unless forced)

**Return:** bool (True if updated, False if rejected)

**Exceptions:**
- AssertionError if price == 0.0

---

#### `check_stop_open(cur_price)`

**Purpose:** Detect a stale entry — verify if the current price has moved so far from the expected entry point that the original signal is no longer relevant and the position should be finalized without executing a trade.

Called while in the entry-pending phase. If price has already moved past the staleness boundary (`entry_price × (1 + 4×fee)` for Long; below `entry_price × (1 - 4×fee)` for Short), the entry conditions no longer hold. The caller should respond by calling `finalize()` and discarding the pending open.

**Parameters:**
- **cur_price** (float): Current market price

**Logic:**
1. Calculate staleness threshold: `stop_open_limit = 4 * fee`
2. Get reference entry price: `limit_price = avg_price_open()` if executions exist, else `price_open[0]`
3. Calculate staleness boundary: `limit_price * (1 + direction_profit(stop_open_limit))`
4. Check if current price has crossed the boundary: `first_in_profit(cur_price, boundary)`
5. If true: log "stop open" and return True (entry stale); else return False (entry still valid)

**Preconditions:**
- Position in entry-pending state (`is_wait_open_state()` True)
- `cur_price > 0`

**Return:** bool (True if entry is stale and position should be finalized; False if entry still valid)

---

#### `close_by_time(cur_time, action_msg)`

**Purpose:** Check if safety deadline has passed; if so, force position closure.

**Parameters:**
- **cur_time** (int): Current unix timestamp in ms — compared against `safety_close_time`

**Logic:**
1. Check if action matches open action AND safety_close_time exceeded: `action == get_open_action() and cur_time > safety_close_time`
2. If true: call `setup_stop_open(action_msg)` and return True
3. Else: return False

**Postconditions:**
- If triggered: position closed with `setup_stop_open()`, which sets close prices and state

**Return:** bool (True if closed by timeout, False otherwise)

---

#### `setup_stop_open(action_msg)`

**Purpose:** Emergency close: set minimal profit target and transition to close state.

**Logic:**
1. Get average or first open price
2. Set stop-loss to zero price: `set_stop_loss(zero_price(), action_msg)`
3. Calculate minimal profit close price: `price_close = [limit_price * (1 + direction_profit(0.006))]`
4. Set `coinGet.action_amount = coinGet.size` (prepare all coins for exit)
5. Transition state via `set_close_state()`
6. Set action via `set_action(get_close_action())`

**Return:** None (void)

---

### 4.4 Position Sizing & Validation

#### `extend(amount, price)`

**Purpose:** Increase desired position size.

**Parameters:**
- **amount** (float): Total desired position amount
- **price** (float): Associated price (unused in base implementation)

**Logic:**
1. Update `coinUse.size = amount - coinUse.used`
2. If `coinUse.want_to_use < amount`: set `coinUse.want_to_use = amount`

**Postconditions:**
- Position desire increased

**Return:** None (void)

---

#### `validate_position_size()`

**Purpose:** Verify requested position doesn't exceed available funds.

**Logic:**
1. If in wait-open state: check `coinUse.want_to_use > coinUse.size`
2. If true: cap to available: `coinUse.want_to_use = coinUse.size` and log message

**Postconditions:**
- Position size validated against available funds

**Return:** None (void)

---

#### `get_open_amount()`

**Purpose:** Return the amount to deploy in next open fill.

**Logic:**
1. If in wait-open state: return `coinUse.want_to_use`
2. Else: log error and return 0.0

**Return:** float (amount to open)

---

### 4.5 Coin Management

#### `coin_used()`

**Purpose:** Return the amount of input currency used (spent).

**Return:** float (`coinUse.used`)

---

> **Note:** `update_coin_size()` has been removed. Robot queries funds from the exchange and passes the amount into `extend()` — Position never calls `stock.item.funds()` directly (that would violate the layer boundary).

### 4.6 P&L Calculation

#### `finalize()`

**Purpose:** Calculate final P&L for a closed position; prepare for next position.

**Return:** tuple(revenue_pct, revenue_abs)
- **revenue_pct** (float): Percentage return, net of fees
- **revenue_abs** (float): Absolute return in base currency

**Logic (Position-Specific):**

**For Long Position (POSITION_STATE_WAIT_SELL):**
1. Calculate: `revenue_abs = coinUse.returned - coinUse.used`
2. Calculate: `revenue_pct = ((avg_price_close / avg_price_open - 1) - 2*fee) * 100`
3. Log revenue with timestamps

**For Short Position (POSITION_STATE_WAIT_BUY):**
1. Calculate: `revenue_abs = avg_price_open * (coinUse.returned - coinUse.used)`
2. Calculate: `revenue_pct = (1 - (avg_price_close / avg_price_open) - 2*fee) * 100`
3. Log revenue with timestamps

**For WAIT State:**
- No position active; return 0, 0

**Postconditions:**
- Revenue logged
- Position data available for analysis

**Return:** (revenue_pct, revenue_abs)

---

#### `avg_price_open()` [ABSTRACT]

**Purpose:** Calculate average entry price across all open executions.

**Implementation (Subclass):**
- Sum all executed quantities weighted by price
- Divide by total quantity executed
- Return unweighted average if no executions yet

**Return:** float (average entry price)

---

#### `avg_price_close()` [ABSTRACT]

**Purpose:** Calculate average exit price across all close executions.

**Implementation (Subclass):**
- Sum all executed quantities weighted by price
- Divide by total quantity executed

**Return:** float (average exit price)

---

### 4.7 State Query Methods

#### `is_wait_open_state()` [ABSTRACT]

**Purpose:** Check if position is waiting for entry fill.

**Implementation (Subclass):**
- Return True if state is WAIT_BUY (short) or WAIT_SELL (long)

**Return:** bool

---

#### `is_wait_close_state()` [ABSTRACT]

**Purpose:** Check if position is open and waiting for exit fill.

**Implementation (Subclass):**
- Return True if state is WAIT_SELL (long) or WAIT_BUY (short)

**Return:** bool

---

#### `get_verbose_state()`

**Purpose:** Return human-readable state description.

**Return:** string (e.g., "state=wait buy action: OPEN_LONG")

**Logic:**
- Map state constant to string name
- Append action string via `get_verbose_action(action)`

---

### 4.8 Action & State Management

#### `get_action()`

**Purpose:** Return current action type.

**Return:** int (STRATEGY_ACTION_*)

---

#### `set_state(new_state)`

**Purpose:** Transition to new state.

**Parameters:**
- **new_state** (int): Target state

**Postconditions:**
- State updated
- Test log entry created

**Return:** None (void)

---

#### `set_action(new_action)`

**Purpose:** Set current action; validates via `check_new_action()`.

**Parameters:**
- **new_action** (int): Target action

**Logic:**
1. Call `check_new_action(new_action)` (hook for subclass validation)
2. Update `action = new_action`
3. Log test message

**Return:** None (void)

---

#### `check_new_action(new_action)`

**Purpose:** Hook for subclass to validate action transitions.

**Default:** Always returns True (no validation)

**Preconditions:**
- None

**Return:** bool (True to allow, False to reject)

---

#### `set_close_state()` [ABSTRACT]

**Purpose:** Transition to appropriate close state based on position type.

**Implementation (Subclass):**
- For long: state = POSITION_STATE_WAIT_SELL
- For short: state = POSITION_STATE_WAIT_BUY

**Postconditions:**
- State updated to wait-close variant

**Return:** None (void)

---

#### `get_open_action()` [ABSTRACT]

**Purpose:** Return the action constant for this position's open phase.

**Implementation (Subclass):**
- For long: return STRATEGY_ACTION_OPEN_LONG
- For short: return STRATEGY_ACTION_OPEN_SHORT

**Return:** int (STRATEGY_ACTION_*)

---

#### `get_close_action()` [ABSTRACT]

**Purpose:** Return the action constant for this position's close phase.

**Implementation (Subclass):**
- For long: return STRATEGY_ACTION_CLOSE_LONG
- For short: return STRATEGY_ACTION_CLOSE_SHORT

**Return:** int (STRATEGY_ACTION_*)

---

### 4.9 Direction Helpers

These methods delegate to module-level functions based on position_type:

#### `direction_profit(val)`
**Return:** Profit-direction multiplier (+val for long, -val for short)

#### `direction_loss(val)`
**Return:** Loss-direction multiplier (-val for long, +val for short)

#### `first_in_profit(first, second)`
**Return:** True if first is more profitable than second in this position's direction

#### `first_in_profit_strict(first, second)`
**Return:** True if first is strictly more profitable (with strict comparison)

#### `zero_price()`
**Return:** float calculated as `avg_price_open * (1 + direction_profit(fee*2))`

---

### 4.10 State Retrieval Methods

#### `get_close_state()`
**Return:** int (POSITION_STATE_WAIT by default; may be overridden)

#### `get_safety_state()`
**Return:** int (POSITION_STATE_WAIT by default; safety fallback state)

---

### 4.11 Serialization

#### `to_dict()`

**Purpose:** Serialize position to dictionary for storage/messaging.

**Return:** dict with keys:
```
{
  "price_open": list,
  "price_close": list,
  "price_stop_loss": float,
  "action_price": float,
  "executed_open": list,
  "executed_open_amount": list,
  "executed_close": list,
  "executed_close_amount": list,
  "coinUse": dict (via coinUse.to_dict()),
  "coinGet": dict (via coinGet.to_dict()),
  "state": int,
  "action": int,
  "position_type": int,
  "expected_target": float,
  "count_open": int,
  "open_time": int,
  "safety_close_time": int,
  "fee": float,
  "desired_revenue": float,
  "risk_per_trade": float,
  "full_position": float,
  "safety_time_intervals": int,
  "use_safety": bool,
  "thread_num": int
}
```

---

#### `from_dict(dict)`

**Purpose:** Deserialize position from dictionary.

**Parameters:**
- **dict** (dict): Dictionary with keys matching `to_dict()` output

**Postconditions:**
- All instance attributes restored from dict
- Position state reconstructed

**Return:** self (for chaining)

---

### 4.12 Logging

#### `log_position(msg)`

**Purpose:** Log position-specific message if `do_log` is True.

**Parameters:**
- **msg** (str): Message to log

**Return:** None (void)

---

#### `log_position_amounts()`

**Purpose:** Log detailed coin balances via `coinUse.log()` and `coinGet.log()`.

**Return:** None (void)

---

---

## 5. State Management

### State Machine Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        POSITION LIFECYCLE                        │
└─────────────────────────────────────────────────────────────────┘

  ┌──────────────┐
  │   WAIT       │  (Idle; no position)
  │ state = 0    │
  └──────┬───────┘
         │ open(OPEN_LONG)
         ▼
  ┌──────────────────────┐
  │ WAIT_SELL (Long)     │  (Awaiting entry fill)
  │ or WAIT_BUY (Short)  │
  │ state = 1 or 2       │
  │ action = OPEN_*      │
  └──────┬───────────────┘
         │ entry executed (record_entry_fill)
         │ [may iterate multiple times for graduated entry]
         ▼
  ┌──────────────────────┐
  │ WAIT_SAFETY_SELL     │  (Entry complete; managing position)
  │ or WAIT_SAFETY_BUY   │
  │ state = 5 or 6       │
  └──────┬───────────────┘
         │ close() called
         │ [state might become WAIT_SELL again for long]
         ▼
  ┌──────────────────────┐
  │ WAIT_SELL (Long)     │  (Awaiting exit fill)
  │ or WAIT_BUY (Short)  │
  │ state = 2 or 1       │
  │ action = CLOSE_*     │
  └──────┬───────────────┘
         │ exit executed (record_exit_fill)
         │ [may iterate multiple times for graduated exit]
         ▼
  ┌──────────────┐
  │   WAIT       │  (Position closed; ready for next)
  │ state = 0    │
  │ finalize()   │
  │ (calculate P&L)
  └──────────────┘
```

### State Constants

| Constant | Value | Meaning | Used For |
|----------|-------|---------|----------|
| POSITION_STATE_WAIT | 0 | No active position | Idle state; awaiting open() |
| POSITION_STATE_WAIT_BUY | 1 | Awaiting buy fill (short entry) | Short entry phase |
| POSITION_STATE_WAIT_SELL | 2 | Awaiting sell fill (long entry/exit) | Long entry/exit phase |
| POSITION_STATE_WAIT_BUY_SIGNAL | 3 | [Reserved] Awaiting buy signal | (TODO state) |
| POSITION_STATE_WAIT_SELL_SIGNAL | 4 | [Reserved] Awaiting sell signal | (TODO state) |
| POSITION_STATE_WAIT_SAFETY_SELL | 5 | Position open, safety management (long) | Long position active |
| POSITION_STATE_WAIT_SAFETY_BUY | 6 | Position open, safety management (short) | Short position active |

### Valid Transitions

| From | To | Trigger | Method |
|------|----|---------|----|
| WAIT | WAIT_SELL (long) | `open(OPEN_LONG)` | `open()` |
| WAIT | WAIT_BUY (short) | `open(OPEN_SHORT)` | `open()` |
| WAIT_SELL | WAIT_SAFETY_SELL | Entry fill (`use_safety=True`) | `record_entry_fill()` |
| WAIT_SELL | WAIT_SELL | Entry fill (`use_safety=False`) | `record_entry_fill()` — stays in exit-awaiting state |
| WAIT_BUY | WAIT_SAFETY_BUY | Entry fill (`use_safety=True`) | `record_entry_fill()` |
| WAIT_BUY | WAIT_BUY | Entry fill (`use_safety=False`) | `record_entry_fill()` — stays in exit-awaiting state |
| WAIT_SAFETY_SELL | WAIT_SELL | `close()` called | `close()` |
| WAIT_SAFETY_BUY | WAIT_BUY | `close()` called | `close()` |
| WAIT_SELL | WAIT | Exit fill complete | `record_exit_fill()` or `finalize()` |
| WAIT_BUY | WAIT | Exit fill complete | `record_exit_fill()` or `finalize()` |
| WAIT_* → WAIT | `finalize()` + reset | Position closed | `finalize()` |

### Invariants

1. **Price List Consistency**: `len(price_open) == len(price_close)` (each open has a close)
2. **Execution Tracking**: `len(executed_open) <= len(price_open)` (can't execute more levels than defined)
3. **Single Stop-Loss**: Only one `price_stop_loss` active at any time
4. **State-Action Pairing**: Certain actions only valid in certain states (enforced by subclass)
5. **Coin Conservation**: `coinUse.used + coinUse.size = total` (no creation/destruction)
6. **Non-Negative Amounts**: All `used`, `returned`, `size` >= 0
7. **Timing Consistency**: `open_time <= safety_close_time <= now` (during open position)

---

## 6. Error Handling

### Exceptions Raised

| Exception | Trigger | Handling |
|-----------|---------|----------|
| **AssertionError** | `price == 0.0` in `set_stop_loss()` | Logs error; position must be closed manually |
| **AssertionError** | Abstract methods called on BasePosition directly | Indicates subclass not overridden (development error) |
| **ValueError** (implicit) | Invalid state transition | Returns False or logs; state remains unchanged |

### Validation Guards

1. **Price Validation**: `check_stop_open()`, `set_stop_loss()` validate profitability before updating
2. **State Guards**: `is_wait_open_state()`, `is_wait_close_state()` prevent methods from operating in wrong states
3. **Fund Validation**: `validate_position_size()` ensures requested size ≤ available
4. **Execution Ordering**: `record_entry_fill()` / `record_exit_fill()` append to history but don't validate state (caller's responsibility)

### Recovery Strategies

1. **Invalid State**: Log error; state remains unchanged; next action must restore consistency
2. **Price Zero**: AssertionError forces manual intervention (design choice: fail-fast)
3. **Insufficient Funds**: Position capped to available via `validate_position_size()`
4. **Timeout Close**: `close_by_time()` forces position closure at minimal profit target

---

## 7. Existing Approach

### Core Patterns

1. **State Machine**: Position enforces strict state transitions; no invalid jumps possible
2. **Graduated Entry/Exit**: Multiple price levels allow scaled entry/exit reducing slippage impact
3. **Coin Tracking**: Separate objects for input/output currencies enable complex multi-leg trades
4. **Fee Integration**: Fee applied at point of coin transfer (`record_entry_fill`/`record_exit_fill`), not at calculation
5. **Time-Period Based Management**: Safety deadlines trigger forced close if profit target not hit
6. **Execution History**: Each fill recorded for P&L and auditing; supports partial fills

### Strengths

- **Strict Safety**: Invalid transitions prevented; positions can't get into inconsistent states
- **Flexibility**: Graduated pricing allows sophisticated multi-level strategies
- **Transparency**: All fills recorded; P&L fully traceable to individual trades
- **Risk Management**: Automatic stop-loss enforcement, position sizing against risk limits
- **Persistence**: Full serialization enables position recovery after crashes

---

## 8. Potential Improvements

### 8.1 Richer State Machine
- **Add pending states**: OPEN_PENDING (awaiting confirmation), CLOSE_PENDING (exit in progress)
- **Add intermediate states**: PARTIAL_CLOSE (some exited, some still open)
- **State transitions table**: Make valid transitions explicit/configurable
- **State callbacks**: Hooks for entering/exiting each state (logging, notifications)

### 8.2 Dynamic Position Sizing
- **Adaptive risk**: Adjust risk_per_trade based on recent volatility
- **Kelly Criterion**: Optimize position size using historical win rate
- **Dynamic safety**: Shorten safety deadline based on momentum
- **Incremental sizing**: Add small amounts as profit accumulates (pyramiding)

### 8.3 Advanced Risk Management
- **Trailing stop-loss**: Automatically follow profit with dynamic distance
- **Profit targets**: Multiple take-profit levels with partial exits
- **Volatility-adjusted SL**: Stop-loss distance scales with market ATR
- **Max loss per position**: Hard cap independent of position size
- **Correlation limits**: Don't open positions if correlated pairs are open

### 8.4 Partial Position Closing
- **Close by percentage**: Exit 50% at first target, 30% at second, etc.
- **Close by time**: Close portion if time expired (even if not at target)
- **Close by signal**: Exit portion on opposite signal (doesn't require profit)
- **Scale-out management**: Track partial closes and adjust remaining stop-loss

### 8.5 Reporting & Analysis
- **Trade metrics**: Win rate, Sharpe ratio, max drawdown per position
- **Attribution**: Which signal triggered open? Which price level executed?
- **Tax reporting**: Track cost basis, FIFO/LIFO for accounting
- **Monte Carlo**: Simulate outcomes with historical price distributions

### 8.6 Order Management
- **Limit order tracking**: Bid/ask levels and fill probability
- **Orphaned order recovery**: Reconnect to broker's open orders on restart
- **Order linking**: Associate entries with exits; maintain 1:1 matching
- **Slippage tracking**: Measure actual vs. expected fill price

---

## 9. Related Classes

- **Coin** (`position/coin.py`): Currency tracking for buy/sell pair
- **LongPosition** (`position/long_position.py`): Subclass for long (buy) positions
- **ShortPosition** (`position/short_position.py`): Subclass for short (sell) positions
- **Data** (`data.py`): Market data provider (prices, timestamps, indicators)
- **Action** (`strategies/actions.py`): Action message object for communication

---

## 10. Example Usage Flow

```python
# Initialize position
pos = LongPosition(coin_use="USDT", coin_get="BTC", full_position=1000, thread_num=1, fee=0.001)

# Attempt entry at graduated prices
success = pos.open(
    strategy_action=STRATEGY_ACTION_OPEN_LONG,
    price_open=[100.0, 99.5, 99.0],      # Try at 3 price levels
    price_close=[102.0, 102.0, 102.0],   # Target profit at each level
    price_stop_loss=98.0,                # Loss limit
    time_period=15,                       # 15-min candles
    cur_time=cur_time_ms,
    action_msg=action_object
)

if success:
    # Determine order size before placing
    coin_amount = pos.get_action_amount_in_coins(price=100.0)  # USD→coins for Long entry
    
    # Record fills phase-semantically
    pos.record_entry_fill(coin_amount=5.0, price=100.0)  # Bought 5 coins at 100
    pos.record_entry_fill(coin_amount=5.0, price=99.5)   # Bought 5 more at 99.5
    
    # Record exit fill
    pos.record_exit_fill(coin_amount=10.0, price=102.0)
    
    # Finalize and get P&L
    rev_pct, rev_abs = pos.finalize()
    print(f"Return: {rev_pct:.2f}%, Profit: ${rev_abs:.2f}")
```

---

## 11. Testing Considerations

### Unit Test Areas

1. **State Transitions**: Valid/invalid transitions from each state
2. **Price Logic**: Graduated entry/exit, stop-loss enforcement
3. **Coin Tracking**: Balances correct after each trade
4. **P&L Calculation**: Matches manual calculation for simple trades
5. **Serialization**: Round-trip to/from dict preserves state
6. **Safety Timeouts**: Position closes correctly on safety deadline

### Integration Test Areas

1. **Full Trade Lifecycle**: WAIT → OPEN → CLOSE → WAIT
2. **Partial Fills**: Multiple adds before full exit
3. **Stop-Loss Trigger**: Position closes at stop price
4. **Fee Impact**: Final revenue accounts for all fees
5. **Risk Sizing**: Position size respects risk_per_trade limit

---

**End of BasePosition Class Specification**
