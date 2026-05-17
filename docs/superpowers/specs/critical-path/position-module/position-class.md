# Position Class Specification

## Class Overview

The `Position` class serves as a **facade and state manager** for trade position management in the pybtctr2 trading framework. It wraps a `BasePosition` implementation object (either `LongPosition` or `ShortPosition`) and provides:

1. **Position Lifecycle Coordination** — Delegates core logic to position implementation while managing transitions, validation, and safety intervals
2. **Phase-Aware Fill Routing** — `process_action(coin_amount, price)` routes fills to `record_entry_fill` or `record_exit_fill` based on position phase, not direction

**Live-only concerns have been extracted to `LiveOrderTracker` (execution layer):**
- Order ID tracking (`buy_id`, `sell_id`), `is_action_in_progress()`
- Margin loan lifecycle (`set_loan`, `set_repay`, `get_loan`)
- Crash-recovery persistence (`save_position`, `load_position`, `restore_position`)

`Robot` owns both `Position` and `LiveOrderTracker`. `TrainRobot` owns only `Position`. The `Position` class contains zero live-only state, enabling structural enforcement of the live/simulation symmetry contract.

The class is designed to be **instantiation-safe** (can be created multiple times per session). It acts as the primary interface for both `Robot` and `TrainRobot` to manage position state through entry, management, and exit phases.

---

## Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `posImpl` | `BasePosition` / `LongPosition` / `ShortPosition` | Current position implementation. Delegates state machine, price tracking, and entry/exit logic. Initialized as `BasePosition` (idle), transitions to type-specific on position open. |
| `fee` | `float` | Taker fee ratio — injected from `stock.item.fee` via Robot/TrainRobot constructor; never hardcoded. Used in profit calculations and position sizing. |
| `thread_num` | `int` | Thread identifier for parallel position tracking. Used in logging and diagnostics. |
| `stop_loss_trigger_time` | `int` | Unix timestamp (ms) of last stop-loss trigger. Used to enforce `stop_loss_safety_interval` before reopening. |
| `full_position` | `float` | Total USD value available for the position (default 10000). Determines position sizing. |
| `desired_revenue` | `float` | Target profit % per trade (default 0.002 = 0.2%). Used in profit target calculation. |

**Removed (moved to `LiveOrderTracker` in execution layer):** `buy_id`, `sell_id`, `is_real_stock`, `recovery_path`

### Constants

These values are loaded from `configs/position_config.yaml` at construction — never hardcoded in the class. Robot and TrainRobot pass the loaded config into Position at instantiation.

| Constant | Config Key | Default | Purpose |
|----------|------------|---------|---------|
| `BUY_START_TIME_LIMIT` | `buy_start_time_limit_sec` | 60 | Time window (seconds) to start buy order after signal |
| `SELL_START_TIME_LIMIT` | `sell_start_time_limit_sec` | 180 | Time window (seconds) to start sell order after signal |
| `STOP_LOSS_PERCENT` | `stop_loss_percent` | 0.006 | Risk threshold (fraction) used in emergency close price |
| `stop_loss_safety_interval` | `stop_loss_safety_interval_min` | 1 | Minimum wait (minutes) after stop-loss before reopening |

`configs/position_config.yaml` is the single source of truth for these values. No module reads them as class-level constants.

---

## Constructor

### `__init__(thread_num, fee, coin_use, coin_get)`

**Parameters:**
- `thread_num` (int): Parallel worker identifier for multi-threaded backtesting.
- `fee` (float): Taker fee ratio from `stock.item.fee`. Applied to fills and profit calculations. Never use a hardcoded default.
- `coin_use` (str): Currency spent in trade (e.g. "USDT" for Long, "BTC" for Short).
- `coin_get` (str): Currency received in trade (e.g. "BTC" for Long, "USDT" for Short).

**Initialization:**
1. Stores parameters as instance attributes
2. Creates a new `BasePosition` as `posImpl` (neutral/idle state)

**Postconditions:**
- Position is idle (`POSITION_STATE_WAIT`), no open trades
- Order IDs cleared and ready for new trades
- Ready to accept `open()` or `restore_position()` calls

**Example:**
```python
position = Position(thread_num=1, fee=0.001)
```

---

## Key Methods & Interfaces

> **⚠ TO REFINE — `action_msg` parameter:** Multiple methods accept an `action_msg` object used for logging and action annotation. This couples Position (a BL state machine) to the Action/logging infrastructure. The intended direction is to isolate logging from position logic — Position should emit structured events or return data, and the caller (Robot/TrainRobot) handles logging. Exact boundary not yet defined; marked on each affected method signature.

### Position Lifecycle Methods

#### `open(strategy_action, price_open, price_close, price_stop_loss, time_period, action_msg)`

**Purpose:** Initiate a new trade position (long or short).

**Parameters:**
- `strategy_action` (int): `STRATEGY_ACTION_OPEN_LONG` or `STRATEGY_ACTION_OPEN_SHORT`
- `price_open` (float): Entry price for the position
- `price_close` (list[float]): Target exit price(s). First element used immediately; subsequent elements for partial closes
- `price_stop_loss` (float): Stop-loss price. Position exits if price crosses this level
- `time_period` (int): Candle timeframe (1, 3, 5, 15, 60, 240 minutes)
- `action_msg` (str): Descriptive message for logging (e.g., "RSI oversold entry") — **⚠ TO REFINE:** see note below

**Returns:** `bool` — True if open succeeded, False if rejected

**Preconditions:**
1. `is_opened()` must be False (no existing position)
2. If `stop_loss_trigger_time` is set, must not be within `stop_loss_safety_interval` (1 minute)
3. `posImpl.position_type` must be `POSITION_TYPE_UNKNOWN`

**Postconditions (on success):**
1. `posImpl` is replaced with type-specific implementation (`LongPosition` or `ShortPosition`)
2. `posImpl.state` transitioned to `POSITION_STATE_WAIT_BUY` or `POSITION_STATE_WAIT_SELL`
3. `posImpl.action` set to the passed `strategy_action`
4. Position metadata (open time, prices) initialized

**Error Handling:**
- Returns False if position already open → logs "Position is already opened"
- Returns False during safety interval → logs "Position was not opened during stop loss safety interval"
- Returns False if `posImpl.open()` fails → calls `finalize()` to reset state
- Internally: calls `finalize()` if opening fails to ensure clean state

**Implementation Detail:** Actual open logic delegated to `posImpl.open()` (LongPosition/ShortPosition). Facade only handles type selection and safety checks.

**Example:**
```python
success = position.open(
    STRATEGY_ACTION_OPEN_LONG,
    price_open=50000.0,
    price_close=[51000.0, 52000.0],  # exit targets
    price_stop_loss=49500.0,
    time_period=15,
    action_msg="RSI oversold at support"
)
```

---

#### `close(strategy_action, price_close, price_stop_loss, time_period, action_msg)`

**Purpose:** Exit an open position (full or partial close).

**Parameters:**
- `strategy_action` (int): `STRATEGY_ACTION_CLOSE_LONG`, `STRATEGY_ACTION_CLOSE_SHORT`, or partial close variants
- `price_close` (float): Exit price
- `price_stop_loss` (float): Updated stop-loss level
- `time_period` (int): Candle timeframe
- `action_msg` (str): Logging description (e.g., "Take profit at resistance") — **⚠ TO REFINE:** see note below

**Returns:** `bool` — Result from `posImpl.close()`

**Preconditions:**
- `is_opened()` must be True (position must be active)

**Postconditions (on success):**
- `posImpl.state` transitions to `POSITION_STATE_WAIT_CLOSE` or equivalent
- Position begins liquidation sequence
- Fills recorded in `posImpl.executed_close` list

**Error Handling:**
- If not opened: logs "Position is not opened", sets action to `STRATEGY_ACTION_NOTHING`, returns False
- Delegates error handling to `posImpl.close()`

**Example:**
```python
success = position.close(
    STRATEGY_ACTION_CLOSE_LONG,
    price_close=51500.0,
    price_stop_loss=49500.0,
    time_period=15,
    action_msg="MACD sell signal"
)
```

---

#### `finalize()`

**Purpose:** Reset position to idle state and calculate final P&L.

**Returns:** `tuple(revenue, revenue_abs)` where:
- `revenue` (float): Profit/loss as a fraction (e.g., 0.05 = +5%)
- `revenue_abs` (float): Absolute profit/loss in USD

**Preconditions:**
- Position should be closed (all fills complete)

**Postconditions:**
1. `posImpl.finalize()` called to calculate P&L
2. `posImpl` reset to new `BasePosition` (idle state)
3. `buy_id` and `sell_id` forced to 0
4. Position state returned to `POSITION_STATE_WAIT`

**Error Handling:**
- If `buy_id` or `sell_id` non-zero at finalize: logs error but resets them anyway (crash recovery safeguard)
- Raises no exceptions; errors logged instead

**Side Effects:**
- Calls `log_position_amounts()` to record final state
- Persists position to JSON via `save_position()` (caller responsibility)

**Example:**
```python
revenue_pct, revenue_usd = position.finalize()
print(f"P&L: {revenue_pct*100:.2f}% / ${revenue_usd:.2f}")
```

---

#### `set_stop_loss(price, action_msg, force=False)`

**Purpose:** Update stop-loss level during an open position.

**Parameters:**
- `price` (float): New stop-loss price level
- `action_msg` (str): Reason for adjustment (e.g., "Breakeven stop") — **⚠ TO REFINE:** action logging should be isolated from position logic; this parameter couples Position to the Action/logging infrastructure. Candidate for removal once a dedicated event/logging boundary is defined.
- `force` (bool, optional): If True, override safety checks. Default=False.

**Returns:** Result from `posImpl.set_stop_loss()` (typically bool)

**Preconditions:**
- Position should be open (though facade doesn't enforce)

**Behavior:**
- Delegates directly to `posImpl.set_stop_loss(price, action_msg, force)`
- Implementation-specific logic (e.g., LongPosition may validate price > entry)

**Example:**
```python
position.set_stop_loss(price=49800.0, action_msg="Trailing stop", force=False)
```

---

### Order Tracking & Execution Methods

> **Note:** Order ID tracking (`get_action_id`, `set_action_id`, `is_action_in_progress`) has been moved to `LiveOrderTracker` in the execution layer. Position no longer owns any Binance order state.



#### `process_action(coin_amount, price)`

**Purpose:** Record a fill execution for the current pending action. Routes by position phase, not by direction — no knowledge of Long vs. Short required at call site.

**Parameters:**
- `coin_amount` (float): Coins that changed hands in this fill (always coin units)
- `price` (float): Execution price (USD/coin)

**Behavior:**
```python
if posImpl.is_wait_open_state():
    posImpl.record_entry_fill(coin_amount, price)
else:
    posImpl.record_exit_fill(coin_amount, price)
```

**Precondition:** Caller must compute `coin_amount` via `position.get_action_amount_in_coins(fill_price)` before calling.

**Postconditions:**
- Fill recorded in `posImpl.executed_open` or `posImpl.executed_close`
- Position state updated

**Example:**
```python
coin_amount = position.get_action_amount_in_coins(current_price)
# ... place order ...
position.process_action(filled_coin_amount, fill_price)
```

---

#### `get_action_amount_in_coins(price)`

**Purpose:** Return the pending order size in coin units. Delegates to `posImpl.get_action_amount_in_coins(price)`.

**Parameters:**
- `price` (float): Current market price (USD/coin)

**Returns:** `float` — Coin units to order

**Example:**
```python
coin_amount = position.get_action_amount_in_coins(price=50000)
```

---

### Position State Query Methods

#### `is_opened()`

**Purpose:** Check if a position is currently active.

**Returns:** `bool` — True if `posImpl.state != POSITION_STATE_WAIT`

**Behavior:**
- Simple state check; doesn't verify actual holdings
- Returns True even during partial closes

#### `is_closed()`

**Purpose:** Check if position has zero active holdings.

**Returns:** `bool` — True if `float_eq(posImpl.coinGet.size, 0)` (using tolerance)

**Note:** Uses floating-point equality check to handle precision issues.

#### `get_position_type()`

**Returns:** `int` — Position type constant:
- `POSITION_TYPE_UNKNOWN` (0) — No open position
- `POSITION_TYPE_LONG` (1) — Buy/long position
- `POSITION_TYPE_SHORT` (2) — Sell/short position

#### `get_state()`

**Returns:** `int` — Current position state constant (e.g., `POSITION_STATE_WAIT_BUY`)

#### `get_action()`

**Returns:** `int` — Current position action (e.g., `STRATEGY_ACTION_OPEN_LONG`)

#### `get_verbose_state()`

**Returns:** `str` — Human-readable state description (delegated to `posImpl`)

#### `get_open_amount()`

**Returns:** `float` — Total USD used to open current position

#### `coin_used()`

**Returns:** `float` — Coin quantity held in open position

#### `get_price_open()`

**Returns:** `float` — Average entry price for opened position

#### `get_price_close()`

**Returns:** `float` — Average exit price (if position being closed)

---

### Stop-Loss & Risk Management

#### `check_stop_loss()`

**Purpose:** Determine if stop-loss condition has been triggered.

**Returns:** `bool` — True if current price crosses stop-loss level

**Logic:**
1. Only checks if position in wait-close state and stop-loss price set
2. Calls `posImpl.first_in_profit()` to verify directional correctness
3. Used by robot to trigger automatic liquidation

**Example:**
```python
if position.check_stop_loss():
    position.setup_stop_loss()  # Initiate stop-loss exit
```

---

#### `setup_stop_loss()`

**Purpose:** Initiate an emergency stop-loss exit.

**Returns:** `bool` — True if setup successful

**Postconditions (on success):**
1. Sets action to `STRATEGY_ACTION_DO_STOP_LOSS`
2. Records `stop_loss_trigger_time = self.data.cur_point`
3. Sets `posImpl.coinGet.action_amount` to full position size (exit all)
4. Logs: "position: {state} STOP LOSS!!!"

**Error Handling:**
- Returns False if buy_id or sell_id already set (crash recovery safeguard)

---

#### `check_stop_open(price)`

**Purpose:** Detect a stale entry — check if the current price has moved so far from the expected entry point that the original signal is no longer relevant and the position should be finalized without executing a trade.

Called while position is in the entry-pending phase (waiting for an open fill). If price has already moved past `entry_price × (1 + 4×fee)` (long) or below `entry_price × (1 - 4×fee)` (short), the entry conditions from the original signal no longer hold. Returning True signals the caller to call `finalize()` and discard the pending open.

**Parameters:**
- `price` (float): Current market price

**Returns:** `bool` — True if entry is stale and position should be finalized; False if entry is still valid

**Behavior:**
- Delegates to `posImpl.check_stop_open(price)` for direction-specific boundary check

---

#### `is_stop_loss()`

**Returns:** `bool` — True if position was just stopped-out (from `posImpl`)

---

### Persistence Methods

> **Note:** `save_position`, `load_position`, and `restore_position` have been moved to `Robot` in the execution layer. Position serialization (`to_dict` / `from_dict`) remains on `posImpl` for data extraction, but the file I/O lifecycle is Robot's responsibility.



### Serialization Methods

#### `to_dict()` / `from_dict(data)`

**Purpose:** Explicit serialization interface (delegated to `posImpl`).

**Behavior:**
- `to_dict()`: Returns dict representation of `posImpl` state
- `from_dict(data)`: Populates `posImpl` from dict (used by `load_position()`)

---

### Utility & Diagnostic Methods

#### `get_target()`

**Purpose:** Calculate the next exit target price.

**Returns:** `float` — Target price

**Logic:**
1. If `price_close` list has untouched targets: return next target
2. If no executed closes yet: calculate dynamic target based on `desired_revenue` (0.8% default)
3. Otherwise: return stop-loss price

**Example:**
```python
target = position.get_target()  # Next take-profit level
```

---

#### `check_target(action_msg)`

**Purpose:** Check if current price has hit any exit target.

**Parameters:**
- `action_msg` (str): Logging description

**Returns:** Result from `posImpl.check_target()`

**Note:** Marked TODO in source; currently not used in main flow.

---

#### `close_by_time(action_msg)`

**Purpose:** Force position close after time limit exceeded.

**Parameters:**
- `action_msg` (str): Reason for timeout close

**Returns:** Result from `posImpl.close_by_time()`

**Behavior:**
- Used to prevent positions from running indefinitely
- Closes at current market price

---

#### `validate_position_size()`

**Purpose:** Verify position sizing constraints are met.

**Behavior:**
- Delegates to `posImpl.validate_position_size()`
- Checks coinGet amount >= minimum position size

---

#### `get_safety_state()` / `get_close_state()` / `get_open_action()`

**Purpose:** Query state machine sub-states (delegated to `posImpl`).

**Returns:** Implementation-specific results

---

#### `do_drop()`

**Purpose:** Force-zero position size (emergency only).

**Behavior:**
- Sets `posImpl.coinGet.size = 0`
- Used only in exceptional circumstances
- Logs: "position:do_drop(): drop position small amount"

---

#### `log_position_amounts()`

**Purpose:** Record final position statistics to log.

**Behavior:**
- Delegates to `posImpl.log_position_amounts()`
- Called during `finalize()`

---

#### `log_position(msg)` / `get_buy_report()` / `get_sell_report()`

**Purpose:** Diagnostic logging and reporting.

**Behavior:**
- `log_position()`: Conditional logging based on `do_log` flag
- Reports: avg price, quantity, USD used, timing, best prices (deprecated methods)

---

### State Modification Methods

#### `set_state(new_state)`

**Purpose:** Directly set position state (internal use).

**Parameters:**
- `new_state` (int): Position state constant

**Behavior:**
- Delegates to `posImpl.set_state(new_state)`
- Used during debugging or exceptional recovery

---

#### `set_action(new_action)`

**Purpose:** Set pending action (buy, sell, stop-loss, etc.).

**Parameters:**
- `new_action` (int): Action constant (e.g., `STRATEGY_ACTION_OPEN_LONG`)

**Returns:** `bool` — True on success, False if preconditions violated

**Preconditions:**
- If `new_action == STRATEGY_ACTION_DO_STOP_LOSS`: both `buy_id` and `sell_id` must be 0

**Error Handling:**
- Returns False if stop-loss action attempted with pending orders → logs error
- Prevents race condition where stop-loss could trigger while order still settling

**Example:**
```python
success = position.set_action(STRATEGY_ACTION_OPEN_LONG)
```

---

#### `safety_update(strategy_action, action_msg)`

**Purpose:** Safely update action with validation checks.

**Parameters:**
- `strategy_action` (int): New action
- `action_msg` (str): Reason for update

**Returns:** Result from `posImpl.safety_update()`

**Behavior:**
- Delegates to `posImpl.safety_update()` for implementation-specific validation
- Used by strategy manager to coordinate multi-source signals

---

---

## State Management

### Valid Position Types

1. **POSITION_TYPE_UNKNOWN** (0) — No position open. Implemented by `BasePosition`. Accepts entry actions only.
2. **POSITION_TYPE_LONG** (1) — Long/buy position. Implemented by `LongPosition`. Entry via `STRATEGY_ACTION_OPEN_LONG`, exit via `STRATEGY_ACTION_CLOSE_LONG`.
3. **POSITION_TYPE_SHORT** (2) — Short/sell position. Implemented by `ShortPosition`. Entry via `STRATEGY_ACTION_OPEN_SHORT`, exit via `STRATEGY_ACTION_CLOSE_SHORT`.

### Position State Machine

```
POSITION_STATE_WAIT (0)
  ├─ [OPEN_LONG/SHORT] → POSITION_STATE_WAIT_BUY (1) / WAIT_SELL (2)
  │   └─ [fills arrive] → POSITION_STATE_WAIT_CLOSE (various)
  │       └─ [CLOSE_LONG/SHORT] → [exit sequence] → WAIT
  │
  └─ [Stop Loss Triggered]
      └─ [DO_STOP_LOSS] → [liquidate all] → WAIT
```

### posImpl Lifecycle

1. **Initial:** `Position.__init__()` creates `BasePosition()`
2. **Open:** `Position.open()` replaces `posImpl` with type-specific instance
3. **Trade:** All operations delegate to active `posImpl`
4. **Close:** `posImpl` manages exit sequence internally
5. **Finalize:** `Position.finalize()` resets `posImpl` to new `BasePosition()`
6. **Restore:** `Position.restore_position()` can replace `posImpl` from JSON

---

## Error Handling

### Exception Types

The Position class is **exception-minimal** — it logs errors instead of raising exceptions:

| Error Scenario | Handling | Impact |
|----------------|----------|--------|
| Position already open | Log "Position is already opened", return False | Entry blocked, action rejected |
| During safety interval | Log message, return False | Position open delayed until interval passes |
| Order ID mismatch | Log error | Order tracking becomes unreliable |
| JSON decode failure | Log error, return empty BasePosition | Crash recovery skipped |
| File not found | Log warning, return empty BasePosition | Normal if first run |
| Opposite order ID set | Raises AssertionError (internal safeguard) | Catches logic errors during development |

### Crash Recovery Protocol

1. **Save on every change:** `robot.py` calls `position.save_position()` after fills
2. **Load on startup:** Robot calls `position.restore_position()` during initialization
3. **Manual override:** If restored position invalid, delete `position.json` and restart
4. **Backup copies:** `save_position("_last_restored")` and `save_position("_checkpoint_N")` for audit trail

### Validation & Preconditions

**Order ID Validation:**
```python
# set_action() enforces:
if new_action == STRATEGY_ACTION_DO_STOP_LOSS:
    assert buy_id == 0 and sell_id == 0
```

**Loan Amount Validation:**
```python
# set_loan() / set_repay() trust caller but log amounts:
log("loan is set for {coin} in amount of {amount}")
```

**Position Size Validation:**
```python
# validate_position_size() delegates to posImpl
# Ensures coinGet.size >= COIN_MIN_AMOUNT[coin] (e.g., 0.01 ETH minimum)
```

---

## Implementation Approach

### Facade Pattern

Position wraps BasePosition to:
1. **Isolate external concerns** (Binance IDs, margin loans) from core trading logic
2. **Manage implementation selection** (LongPosition vs. ShortPosition creation)
3. **Enforce global invariants** (safety intervals, order ID validation)

### Delegation

All core trading logic delegated to `posImpl`:
- Entry logic (averaging up/down)
- Exit sequencing
- Stop-loss triggering
- Profit/loss calculation

### Recovery Philosophy

Position persists to JSON as a **last-resort safeguard**, not a primary data store:
- Primary source of truth: in-memory `posImpl`
- JSON updated after every material change
- On crash, load from JSON and validate against user's records
- If mismatch, provide manual reconciliation tools

---

## Key Design Patterns

### Pattern: Defensive Initialization
```python
# Constructor creates BasePosition immediately
# Only transitions type on explicit open() call
self.posImpl = BasePosition(...)  # safe, idle state
```

### Pattern: ID Routing
```python
# get_action_id() maps action type to correct ID
if action == STRATEGY_ACTION_OPEN_LONG:
    return self.buy_id  # which Binance order filled this?
elif action == STRATEGY_ACTION_CLOSE_LONG:
    return self.sell_id
```

### Pattern: Safety Intervals
```python
# Prevent position churn after stop-loss
if stop_loss_trigger_time + safety_interval > cur_time:
    return False  # Too soon to reopen
```

### Pattern: Loan Tracking
```python
# Margin trades need explicit loan management
set_loan(1000)      # Borrow $1000
process_action(...)  # Use it in trade
set_repay(1000)     # Repay after closing
```

---

## Potential Improvements

### 1. Enhanced Error Handling
**Current:** Errors logged, positions may become inconsistent  
**Proposed:** Custom exception hierarchy for recoverable vs. critical failures
```python
class PositionError(Exception): pass
class PositionAlreadyOpenError(PositionError): pass
class OrderIDConflictError(PositionError): pass
```

### 2. Position Risk Monitoring
**Current:** Risk tracking delegated to posImpl  
**Proposed:** Add facade-level risk aggregation
```python
def get_risk_metrics(self):
    """Return (max_loss_usd, max_loss_pct, unrealized_pnl)"""
    return self.posImpl.calculate_risk()
```

### 3. Loan Repayment Automation
**Current:** Manual loan tracking via set_loan/set_repay  
**Proposed:** Automatic repayment scheduling
```python
def auto_repay_loan(self, repay_percent=0.5):
    """Automatically repay X% of loan from position P&L"""
```

### 4. Advanced State Tracking
**Current:** State encoded as integers (POSITION_STATE_*)  
**Proposed:** Enum-based state machine with transition validation
```python
from enum import Enum
class PositionState(Enum):
    IDLE = 0
    WAIT_BUY = 1
    WAIT_CLOSE = 2
```

### 5. Atomic State Transitions
**Current:** Multiple attributes modified across open/close/finalize  
**Proposed:** Transaction-like pattern to ensure all-or-nothing updates
```python
def _atomic_transition(self, old_type, new_type):
    """Atomically swap posImpl implementation"""
```

### 6. Comprehensive Audit Trail
**Current:** Saves position.json on request  
**Proposed:** Built-in audit log with every action timestamp
```python
self.audit_log = [
    {"action": "OPEN_LONG", "time": 1234567890, "price": 50000},
    {"action": "ADD_BUY", "time": 1234567900, "amount": 0.01},
    ...
]
```

### 7. Position Snapshot Testing
**Current:** No mechanism to verify restored state correctness  
**Proposed:** Compare position before/after JSON roundtrip
```python
def verify_persistence(self):
    """Assert current state matches (load then save)"""
    loaded = self.load_position()
    assert loaded.to_dict() == self.posImpl.to_dict()
```

### 8. Dynamic Position Sizing
**Current:** `full_position` fixed at initialization  
**Proposed:** Adjust position size based on volatility or account growth
```python
def adjust_position_size(self, new_size):
    """Update available capital for next position"""
```

---

## Related Classes

- **`BasePosition`** (`position/base_position.py`) — Abstract base implementing core trading state machine
- **`LongPosition`** (`position/long_position.py`) — Long/buy position logic (inherits BasePosition)
- **`ShortPosition`** (`position/short_position.py`) — Short/sell position logic (inherits BasePosition)
- **`Coin`** (`position/coin.py`) — Tracks a single currency (size, price, loan, fees)
- **`Robot`** (`robot.py`) — Live trading orchestrator; calls `Position.open()`, `close()`, `finalize()`
- **`TrainRobot`** (`train_robot.py`) — Backtest simulator; same Position interface
- **`Data`** (`data.py`) — OHLC data and indicator provider

---

## Testing Considerations

### Unit Test Scenarios

1. **Initialization:** New Position has correct defaults
2. **Open/Close Lifecycle:** Position transitions through states correctly
3. **Order ID Tracking:** buy_id and sell_id set/retrieved correctly
4. **Loan Management:** Loan amounts tracked through position lifecycle
5. **Persistence:** Position saves/loads from JSON without data loss
6. **Crash Recovery:** restore_position() correctly rehydrates state
7. **Safety Intervals:** Position blocked from reopening too soon after stop-loss
8. **Precondition Validation:** open() correctly rejects when already opened

### Integration Test Scenarios

1. **Live Trade Simulation:** Open → fills → close → finalize → P&L matches expected
2. **Partial Closes:** Multiple record_exit_fill() calls correctly tracked
3. **Stop-Loss Triggering:** check_stop_loss() triggers at correct price level
4. **Margin Trading:** Loans tracked through position lifecycle and cleared at finalize()

### Mock Objects Available

- `test/mock_data.py` — Mocked Data object with static OHLC
- `test/mock_stock_holder.py` — Mocked stock holder for balance queries

---

## Summary

The `Position` class is the **primary facade** for position lifecycle management in pybtctr2. It bridges strategic decisions (buy/sell signals) with execution details (Binance order IDs), provides crash recovery via JSON persistence, and enforces safety invariants (stop-loss intervals, loan tracking). Its delegation to type-specific BasePosition implementations keeps it lightweight while supporting both long and short positions, live and simulated trading, and margin and spot trading modes. Error handling is defensive (log-based) rather than exception-driven, prioritizing robustness over fail-fast semantics.
