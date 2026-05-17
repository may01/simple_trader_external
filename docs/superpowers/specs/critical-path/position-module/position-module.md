# Position Module Specification

**Layer:** Business Logic  
**Related specs:** [Business Logic Layer](../../layers/03-business-logic-layer.md) · [Execution Layer](../../layers/04-execution-layer.md) · [Robot Module](../robot-module/robot-module.md)

## Overview

The Position module manages the complete lifecycle of a trading position, from opening through closing and finalization. It is a **Business Logic** component: it enforces trading rules (state machine invariants, one-directional stop-loss, risk-based position sizing), computes P&L, and acts as the authoritative source of trade state. The Execution Layer (Robot, TrainRobot) reads Position's execution intent and reports fills back — it does not own or manage position state.

The module implements a strict state machine (WAIT → WAIT_BUY/WAIT_SELL → WAIT_SAFETY_BUY/WAIT_SAFETY_SELL → WAIT) enabling both long and short trading strategies with support for partial fills and graduated entry/exit prices.

The Position module fulfills three primary responsibilities: (1) managing position state throughout the trade lifecycle via a strict state machine enforcing business rules, (2) computing P&L across graduated fills with fee accounting, and (3) providing execution intent via `get_action()` that the Execution Layer consumes to place orders. Execution-bridge concerns (Binance order IDs, margin loan tracking, JSON persistence) are managed by `LiveOrderTracker` in the Execution Layer — Position itself contains only business logic.

## Key Classes and Responsibilities

- **Position (Facade)**: Public-facing wrapper that orchestrates BasePosition-derived classes. Manages state transitions between Long/Short implementations. Provides unified interface regardless of position direction. Execution-bridge concerns (order IDs, loans, persistence) live in `LiveOrderTracker` (Execution Layer).

- **BasePosition (Abstract State Machine)**: Base class defining the position state machine and common interface. Manages state transitions (WAIT, WAIT_BUY, WAIT_SELL, WAIT_SAFETY_BUY, WAIT_SAFETY_SELL), price target tracking (price_open[], price_close[], price_stop_loss), and execution history (executed_open[], executed_close[]). Handles JSON serialization for position recovery.

- **LongPosition (Concrete)**: Implements long trade lifecycle where buy is followed by sell. Tracks coinUse (base currency, e.g., USDT) and coinGet (target coin, e.g., LINK). Computes average entry/exit prices and manages graduated sell targets. Implements direction-aware profit/loss calculations.

- **ShortPosition (Concrete)**: Implements short trade lifecycle where sell precedes buy. Tracks coinUse (target coin) and coinGet (base currency). Computes average sell/buy prices. Implements direction-aware profit/loss calculations for short strategies.

- **Coin (Currency Tracker)**: Data structure tracking a single currency's state within a position. Manages: size (available amount), used (amount deployed), returned (amount recovered), loan (amount borrowed for margin), want_to_use (intended allocation), and action_amount (amount pending current trade action). Used for both base and target currencies.

## Module Boundaries

### Upstream (callers into this module)
- **StrategyManager (Business Logic)**: Routes action decisions into position via `position.open()`, `position.close()`, `position.set_stop_loss()` after `strategy_manager.check()` resolves. Position state (via `position.get_state()` / `position.get_target()`) informs StrategyManager on subsequent ticks.
- **Robot (Execution Layer)**: Reports fills via `record_entry_fill()` / `record_exit_fill()`; calls `finalize()` after close. Order ID tracking, margin loans, and persistence are managed by `LiveOrderTracker` (not Position).
- **TrainRobot (Execution Layer)**: Simulates fills via `record_entry_fill()` / `record_exit_fill()`; calls `finalize()` to collect P&L.

### Downstream (what this module calls)
- **Logging System (logs.py)**: `finalize()` calls `log_revenue()` to emit P&L for accounting.
- **Infrastructure (helpers.py / paths.py)**: `save_position()` / `load_position()` write/read JSON at `manual_setup/{PAIR}/position.json`.
- **Visualization (view_*.py)**: Reads position state via `get_position_type()`, `get_verbose_state()`, `get_price_open()`, `get_price_close()` for charting.

### Key Interfaces
```python
# Position Opening
position.open(strategy_action, price_open, price_close, price_stop_loss, time_period, action_msg)

# Position Management
position.close(strategy_action, price_close, price_stop_loss, time_period, action_msg)
position.set_stop_loss(price, action_msg, force=False)
position.check_stop_loss()  # Detects if stop loss should trigger

# Fill Reporting (called by Execution Layer after order fills)
position.record_entry_fill(coin_amount: float, price: float)  # Report buy/short-sell fill
position.record_exit_fill(coin_amount: float, price: float)   # Report sell/buy-to-cover fill

# State Queries
position.is_opened()  # true if position_type != POSITION_TYPE_UNKNOWN
position.is_closed()  # true if coinGet.size == 0
position.get_position_type()  # POSITION_TYPE_LONG or POSITION_TYPE_SHORT
position.get_state()  # Current state machine state

# Finalization
revenue, revenue_abs = position.finalize()  # Compute P&L and reset
```

> **Note:** Order ID tracking (`buy_id`/`sell_id`), margin loan management (`set_loan`/`set_repay`/`get_loan`), and JSON persistence (`save_position`/`load_position`/`restore_position`) are Execution Layer concerns managed by `LiveOrderTracker` — not part of the Position interface.

## Data Flow

```
Strategy Decision
      ↓
Signal Evaluation (Signals → Position.state check)
      ↓
Action Request (StrategyManager → Position.open/close/setup_stop_loss)
      ↓
Position Implementation (LongPosition or ShortPosition)
      ↓
Order Generation (get_action_amount, get_action_price)
      ↓
Robot/TrainRobot Execution
      ↓
Fill Callback (process_action with amount, price)
      ↓
Position State Update (record_entry_fill/record_exit_fill, update coinUse/coinGet)
      ↓
Stop Loss Check (check_stop_loss on each candle)
      ↓
Exit Trigger (Position.close or setup_stop_loss)
      ↓
Final Execution (last record_exit_fill/record_entry_fill)
      ↓
Finalization (compute revenue, log_revenue, reset to BasePosition)
```

## Execution Flow

### 1. Trade Opening
```
1. Strategy signals ENTRY (long or short)
2. StrategyManager calls position.open(STRATEGY_ACTION_OPEN_LONG, 
                                       price_open=[price1, price2, ...],
                                       price_close=[target1, target2, ...],
                                       price_stop_loss=stop_price,
                                       time_period=candle_interval,
                                       action_msg)
3. Position.open() validates:
   - No open position exists
   - Stop loss safety interval has elapsed
4. Creates appropriate implementation:
   - LongPosition if STRATEGY_ACTION_OPEN_LONG
   - ShortPosition if STRATEGY_ACTION_OPEN_SHORT
5. LongPosition.open() calculates:
   - Average open price from price_open[]
   - Risk/profit ratio vs win/lose rate
   - Position size based on risk_per_trade parameter
6. Sets position state to POSITION_STATE_WAIT_BUY (short) or POSITION_STATE_WAIT_SELL (long)
7. Sets position action to STRATEGY_ACTION_OPEN_LONG or STRATEGY_ACTION_OPEN_SHORT
8. Returns action_amount to Robot for order placement
```

### 2. Trade Management (During Position Life)
```
For each candle while position is open:
1. check_stop_loss() examines if price breached stop_loss_price
   - If yes, calls setup_stop_loss() to transition to stop loss mode
2. safety_update() monitors timeout and partial fill opportunities
   - For POSITION_STATE_WAIT_SAFETY_SELL: checks if target hit
   - If safety_close_time exceeded: forces close with break-even target
3. get_target() returns next price target:
   - If executed_close[] is non-empty: next unexecuted target
   - If safety mode: 0.8% above average entry price
4. State transitions:
   - WAIT_BUY ↔ WAIT_SELL for buy/sell completion
   - WAIT_SELL ↔ WAIT_SAFETY_SELL for partial fills
5. set_stop_loss() updates price_stop_loss if new price is more favorable
```

### 3. Trade Closing
```
1. Strategy signals EXIT or STOP_LOSS
2. StrategyManager calls position.close(STRATEGY_ACTION_CLOSE_LONG,
                                        price_close=[target1, target2, ...],
                                        price_stop_loss=new_stop,
                                        time_period,
                                        action_msg)
3. Position.close() validates position is_opened()
4. LongPosition.close():
   - Updates target prices (may be partial close at 30% volume)
   - Sets action to STRATEGY_ACTION_CLOSE_LONG or STRATEGY_ACTION_CLOSE_LONG_PART
   - Sets coinGet.action_amount for order quantity
5. Robot places sell order at calculated price
6. Fill callback: position.record_exit_fill(coin_amount, price)
7. record_exit_fill() updates:
   - coinGet.size -= coin_amount
   - coinUse.size += coin_amount * price * (1 - fee)
   - coinUse.returned += coin_amount * price * (1 - fee)
```

### 4. Finalization
```
1. Position.finalize() called after position closure
2. Computes revenue based on position type:
   - LONG: revenue = (avg_close / avg_open - 1) - 2*fee
   - SHORT: revenue = (1 - avg_close / avg_open) - 2*fee
3. Logs revenue via log_revenue() with P&L details
4. Computes revenue_abs (absolute $ value change)
5. Resets posImpl to BasePosition (neutral state)
6. Returns (revenue%, revenue_abs) tuple to caller
```

## Key Components

### Position (position.py)

The facade class providing public API for position management. Key methods:

```python
__init__(thread_num, fee)
    # Initialize with fee parameter

open(strategy_action, price_open, price_close, price_stop_loss, time_period, action_msg)
    # Initiate long/short trade

close(strategy_action, price_close, price_stop_loss, time_period, action_msg)
    # Close open position

finalize()
    # Compute P&L and reset to neutral state

record_entry_fill(coin_amount: float, price: float)
    # Report buy (long) or short-sell (short) fill; updates coinUse/coinGet

record_exit_fill(coin_amount: float, price: float)
    # Report sell (long) or buy-to-cover (short) fill; updates coinUse/coinGet

check_stop_loss()
    # Monitor for stop loss trigger
```

Static configuration parameters:
- **fee**: 0.001 (0.1% per fill, adjusted for real vs simulation)
- **desired_revenue**: 0.002 (0.2% profit target)
- **risk_per_trade**: 0.01 (1% of full_position risked per trade)
- **full_position**: 10000 (capital allocated to single position)
- **stop_loss_safety_interval**: 1 minute (cooldown after stop loss trigger)

### BasePosition (base_position.py)

Abstract base class implementing core state machine and interface:

```python
# State Machine
state ∈ {POSITION_STATE_WAIT, 
          POSITION_STATE_WAIT_BUY,
          POSITION_STATE_WAIT_SELL,
          POSITION_STATE_WAIT_SAFETY_BUY,
          POSITION_STATE_WAIT_SAFETY_SELL}

# Price Targets (graduated entry/exit)
price_open[]       # Array of entry price targets
price_close[]      # Array of exit price targets
price_stop_loss    # Stop loss level

# Execution History
executed_open[]       # Prices at which buys executed
executed_open_amount[]    # USD amounts at each buy
executed_close[]      # Prices at which sells executed
executed_close_amount[]   # Coin amounts at each sell

# Currencies
coinUse   # Base currency (USD for long, coin for short)
coinGet   # Target currency (coin for long, USD for short)

# Direction-Aware Helpers
direction_profit(val)  # Returns profit multiplier based on type
direction_loss(val)    # Returns loss multiplier based on type
first_in_profit(a, b)  # Returns true if a is more profitable than b
```

Methods (to be overridden in LongPosition/ShortPosition):
```python
open(...)              # Initialize position
close(...)             # Prepare for closure
check_stop_open(...)   # Stop opening if price is unfavorable
close_by_time(...)     # Force close if time limit exceeded
set_stop_loss(...)     # Update stop level
record_entry_fill(coin_amount, price) / record_exit_fill(coin_amount, price)  # Record order fills
avg_price_open() / avg_price_close()  # Compute execution averages
```

### LongPosition (long_position.py)

Concrete implementation of long trades (buy then sell):

```python
position_type = POSITION_TYPE_LONG

coinUse.name = data.coin_base  # e.g., "usdt"
coinGet.name = data.coin        # e.g., "link"

# Opening calculates risk/reward ratio and position size:
# position_size = min(full_position, 
#                     full_position * (risk_per_trade / (risk/avg_price)))

# record_entry_fill(coin_amount, price) executes purchase:
# - Updates coinUse.size, coinUse.used
# - Updates coinGet.size based on fill price
# - Transitions state to POSITION_STATE_WAIT_SELL

# record_exit_fill(coin_amount, price) executes sale:
# - Updates coinGet.size (decreases as coins sell)
# - Updates coinUse.size (increases as USD received)
# - Tracks in executed_close[] and executed_close_amount[]

# avg_price_open() = sum(executed_open_amount[]) / sum(coins_bought)
# avg_price_close() = sum(executed_close_usd[]) / sum(executed_close_amount[])
```

### ShortPosition (short_position.py)

Concrete implementation of short trades (sell then buy):

```python
position_type = POSITION_TYPE_SHORT

coinUse.name = data.coin        # Borrowed coin (e.g., "link")
coinGet.name = data.coin_base   # Proceeds in base (e.g., "usdt")

# Opening calculates margin and position size for shorting

# record_entry_fill(coin_amount, price) executes short sale:
# - Updates coinUse.size (amount sold)
# - Updates coinGet.size (proceeds received)

# record_exit_fill(coin_amount, price) executes buy-to-cover:
# - Repays borrowed amount
# - Reduces coinUse.size
```

### Coin (coin.py)

Lightweight data structure tracking a single currency's lifecycle:

```python
class Coin:
    name: str          # Currency name (e.g., "link", "usdt")
    size: float        # Available amount
    loan: float        # Amount borrowed (margin trading)
    want_to_use: float # Intended allocation
    used: float        # Amount deployed in position
    returned: float    # Amount recovered
    action_amount: float  # Amount pending in current action
```

Methods:
```python
log()                 # Print coin state
to_dict() / from_dict()  # Serialization
```

## Existing Approach

The implementation uses a strict state machine with the following design decisions:

### State Machine Design
- **POSITION_STATE_WAIT**: Neutral, no position open. All variables zeroed.
- **POSITION_STATE_WAIT_BUY** (Short): Awaiting buy-to-cover execution
- **POSITION_STATE_WAIT_SELL** (Long): Awaiting sell execution
- **POSITION_STATE_WAIT_SAFETY_BUY**: Partial buy-to-cover execution (short)
- **POSITION_STATE_WAIT_SAFETY_SELL**: Partial sell execution (long)

Transitions are strictly controlled and logged. Invalid transitions trigger errors.

### Execution-Bridge Concerns (LiveOrderTracker — Execution Layer)
Order ID tracking, margin loan management, and JSON persistence are **not** Position responsibilities. These are handled by `LiveOrderTracker` in the Execution Layer:
- **buy_id / sell_id**: Binance order IDs for crash recovery
- **set_loan / set_repay / get_loan**: Margin borrow lifecycle
- **save_position / load_position / restore_position**: JSON persistence at `manual_setup/{PAIR}/position.json`

Position state serialization (for `LiveOrderTracker` to use) is still exposed via `to_dict()` / `from_dict()`.

### Graduated Price Targets
- **price_open[]**: Array of entry prices enabling multi-tranche buys
- **price_close[]**: Array of exit prices enabling graduated profit-taking
- get_price_open() / get_price_close() track which targets remain unexecuted
- Supports partial position sizing (e.g., 30% at safety level)

## Potential Improvements

1. **Multi-Position Support**: Current implementation manages single position per ticker. Extend to portfolio model supporting N concurrent positions with independent state machines.

2. **Risk Management**: Add hard limits for:
   - Maximum position size as % of account
   - Maximum drawdown before trading halt
   - Correlation-based position limits (avoid correlated pairs)

3. **Dynamic Position Sizing**: Calculate position_size based on realized volatility rather than fixed risk_per_trade. Adapt to market conditions.

4. **Time-Based Position Closure**: Implement configurable timeout to force close if position doesn't reach profit target within N minutes. Prevents capital tie-up.

5. **Advanced Exit Strategies**: 
   - Trailing stop loss that adjusts based on price movement
   - Partial profit-taking at multiple levels (e.g., take 50% at +0.5%, 30% at +1%)
   - Dynamic profit targets based on market regime (quiet vs volatile)

6. **Position Metadata Enhancement**: Extend to_dict() to include:
   - Entry reason (which signals triggered)
   - Strategy identifier (manual_long vs nn_enhanced)
   - Backtesting metrics (win%, average profit, max drawdown)
   - Historical fill prices for post-trade analysis

7. **Concurrent Order Handling**: Current fill API expects sequential fills. Enhance `record_entry_fill`/`record_exit_fill` to handle multiple partial fills per action.

8. **Position Reopening Logic**: Provide mechanism to reopen position at break-even if stopped out, with safety circuit breaker to prevent whipsaw.

9. **Slippage Simulation**: Enhance backtesting by simulating realistic slippage based on order size and volatility instead of assuming perfect fills.

10. **Position Aggregation**: Support merging multiple partial positions (from safety fills) into aggregated P&L view without requiring manual intervention.
