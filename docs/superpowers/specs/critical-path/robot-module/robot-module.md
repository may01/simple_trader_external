# Robot Module Specification

## Overview

The Robot module is the live trading execution engine of pybtctr2. It continuously polls market data from Binance, evaluates trading strategies, and executes buy/sell orders while maintaining position state and tracking profitability. Operating as an infinite polling loop, the Robot bridges the gap between signal generation (StrategyManager) and order execution (stock/Binance API), managing the complete lifecycle of a trade from entry signal through stop-loss management and final closure.

The Robot is responsible for orchestrating the complete trading workflow: fetching and updating OHLC candles, computing technical indicators, invoking the StrategyManager to determine trading decisions, executing orders on the exchange, managing position state transitions, and persisting all state changes for monitoring and audit purposes. It operates a single position per trading pair at any given time and implements a state machine pattern where position state drives the available actions.

The core Robot class serves as the entry point, with the `run_instantly()` method starting an infinite polling loop that continues until external termination. Each loop iteration performs candle updates, indicator calculations, and delegates to the `do()` method for decision-making and execution.

## Module Boundaries

**Upstream Dependencies (Business Logic):**
- **StrategyManager**: Evaluates all available trading signals and returns action decisions (entry, exit, stop-loss, move stop-loss) via `strategy_manager.check()`
- **Position Module (Business Logic)**: Maintains trade state machine. Robot routes strategy actions into Position (`position.open/close/set_stop_loss`), reads execution intent via `position.get_action()`, reports fills via `position.record_entry_fill() / position.record_exit_fill()`, and calls `position.finalize()` after close. Execution-bridge concerns (order ID tracking, margin loans, persistence) are managed by `LiveOrderTracker` in the Execution Layer.
- **Data Layer** (`data.py`, `indicators.py`): Provides OHLC candles and calculated technical indicators (RSI, MACD, CCI, Bollinger Bands, SAR, ATR, etc.)

**Upstream Dependencies (Infrastructure):**
- **Binance Exchange**: Provides market data (OHLC candles, depth data, order fills) and executes orders via the stock abstraction layer
- **Infrastructure**: Logging (`logs.py`), file I/O, paths, and helpers

**Downstream Consumers:**
- **Visualization**: Reads position state from `manual_setup/{PAIR}/position.json` and action history from `shared/actions/{timestamp}.pkl`
- **Monitoring/Alerting**: Subscribes to log output for trade signals, executions, and revenue tracking
- **Manual Override**: Can read/modify position state via the JSON file during runtime

**Key External Interfaces:**
- `robot.run_instantly()`: Starts live trading loop
- Position state persisted to: `manual_setup/{PAIR}/position.json`
- Actions persisted to: `shared/actions/{timestamp}.pkl`
- Logging output via `log()` and `log_error()` functions

## Data Flow

```
                    ┌──────────────┐
                    │   Binance    │ (market data, order execution)
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────────┐
                    │ update_candles   │ (fetch new OHLC data)
                    │ get_depth_data   │
                    └──────┬───────────┘
                           │
                           ▼
                    ┌──────────────────┐
                    │ Indicators.calc  │ (RSI, MACD, CCI, ATR, etc.)
                    └──────┬───────────┘
                           │
                           ▼
                    ┌──────────────────┐
                    │ StrategyManager  │ (evaluate signals → action decision)
                    │ .check()         │
                    └──────┬───────────┘
                           │
                    ┌──────▼──────────┐
                    │ Robot.wait()    │ (action creation, signal routing)
                    │ Robot.do()      │
                    └──────┬──────────┘
                           │
                           ▼
                    ┌──────────────────┐
                    │ Position (BL)    │ (state machine; sets action intent)
                    │ open/close/SL    │ ← Business Logic Layer
                    └──────┬───────────┘
                           │
                           ▼
                    ┌──────────────────┐
                    │ trade_action()   │ (place order, cancel, process fills)
                    │ place_valid_ord  │
                    │ process_executed │
                    └──────┬───────────┘
                           │
                           ▼
                    ┌──────────────────┐
                    │ stock.trade()    │ (order placement via Binance API)
                    │ stock.order_info │
                    │ stock.cancel_ord │
                    └──────┬───────────┘
                           │
                           ▼
                    ┌──────────────────┐
                    │ Binance Orders   │ (placed, filled, canceled)
                    └──────┬───────────┘
                           │
                           ▼
                    ┌──────────────────┐
                    │ do_finalize_act  │ (cleanup, position.finalize())
                    │ save_position()  │
                    │ action.save()    │
                    └──────────────────┘
```

## Execution Flow

### Polling Loop (run_instantly)

The Robot implements a continuous polling loop that starts on `run_instantly(test_buy_sell=False)`:

1. **Infinite loop** begins with `while(True)`:
2. **Timestamp**: Set `self.cur_point = int(time.time())` to record current Unix timestamp in seconds
3. **Candle Update + Indicators**: Call `data_item.build_candles(self.cur_point)` — fetches OHLC data from Binance via `stock.item.get_candles_history()` and computes all indicators via `Indicators.compute()` for each configured timeframe (`[1, 5, 15, 60, 240, 1440]` minutes from `candles_config.yaml`)
4. **Depth Data**: Retrieve order book depth via `data_item.get_depth_data(1000)` for price level analysis
8. **Sleep Management**: Call `stock.item.set_operation_sleep()` to pace API requests
9. **Single Step**: Invoke `self.do()` to process decision logic and execute trades
10. **Exception Handling**: On any exception, log error, set `update_period = 2*60` (2 minutes), sleep, then reinitialize stock connection
11. **Sleep Duration**: Between iterations, sleep for `self.update_period` seconds (5 if action in progress, 30 if waiting)

### Single Step (do)

The `do()` method processes one complete trading iteration:

1. **Log State**: Output current position state via `position.get_verbose_state()`
2. **Create Action Message**: Instantiate `Action()` object to collect signals and metadata
3. **Wait Phase**: Call `immediate_next_step = self.wait(action_msg)` to evaluate strategies and route to the appropriate action handler
4. **Restore Position**: Call `position.restore_position()` to refresh cached state from persisted JSON
5. **Check Stop Conditions**: If not immediate next step:
   - If position opening: check `position.check_stop_open()` (triggers if max open wait exceeded)
   - If opening: check `position.close_by_time()` (triggers if action timeout exceeded)
   - If either triggers: call `self.stop_open()` to cancel/finalize pending open orders
6. **Trade Action**: If position state is not NOTHING, invoke `self.trade_action(position)` to:
   - Check if order is in progress (pending on exchange)
   - Process fills/cancellations if in progress
   - Place new order if not in progress
7. **Save State**: Call `position.save_position()` to persist JSON file
8. **Save Action**: Call `action_msg.save()` to persist action as pickle file for visualization
9. **Adjust Sleep Period**: Set `update_period = 5` seconds if action pending, `30` seconds if waiting
10. **Output**: Log completion with timestamp and coin name
11. **Sleep**: If `sleep_on_step=True` and not immediate next step, sleep for `update_period` seconds
12. **Exception Handling**: On exception, sleep 2 minutes and reset position

### Order Management (trade_action)

The `trade_action(position)` method manages the order lifecycle:

1. **Stop-Loss Priority**: If `position.is_stop_loss()` is true:
   - Check if order is in progress via `position.is_action_in_progress()`
   - If in progress: call `process_executed_orders()` to check if filled
     - If not filled: call `stop_loss_cancel_actions()` to cancel the pending order and return `True` (immediate next step)
     - If filled: call `do_finalize_action()` and return `False`
   - If not in progress: proceed to place order (below)

2. **Normal Order Processing**: If not in stop-loss:
   - If order in progress: call `process_executed_orders(action_id)` to check fills
     - If filled: call `do_finalize_action()` and return `False` (no immediate step needed)
     - If not filled: continue (keep waiting)

3. **Place New Order**: If no action in progress:
   - Call `place_valid_order()` which:
     - Fetches current close price via `data.get_cur_price("close", 0)`
     - For stop-loss orders: adjusts price down (long) or up (short) by 0.5x ATR for market impact safety
     - Computes amount via `position.get_action_amount(price)`
     - Validates amount against minimum thresholds
     - If invalid: calls `position.do_drop()` to reset position
     - If valid: calls `stock.item.trade(trade_type, price, amount)` to submit order
     - On success: stores order ID in `position.set_action_id(response["order_id"])`
     - Checks immediate fill via `stock.item.order_info()` and processes if filled
   - If finalize needed: calls `do_finalize_action()`

4. **Return Value**: Returns `False` (no immediate next step required)

## Key Components

### Robot Class

**Attributes:**
- `fee`: Read from `stock.item.fee` at init — never hardcoded; sourced from `EXCHANGE_FEE` env var via `Stock_Binance`
- `update_period`: Polling interval in seconds; 5 seconds when action in progress, 30 seconds when idle
- `risk_per_trade`: Risk capital per trade = 0.01 (1% of account); configurable via environment
- `expected_target_top`, `expected_target_bottom`: Target price levels (currently unused)
- `full_candles_list`: Loaded from `candles_config.yaml` at init — `[1, 5, 15, 60, 240, 1440]` minutes; not hardcoded
- `strategy_mngr`: StrategyManager instance for signal evaluation
- `position`: Position instance tracking open trade state, PnL, and order IDs
- `schedule`: List for scheduled actions (future use)
- `cur_action`: List of current action details (future use)
- `sleep_on_step`: Boolean flag controlling sleep between loop iterations

**Initialization:**
- Constructor `__init__(position_size_limit, use_test_strategy)`:
  - Initializes StrategyManager with data_item and stock fee
  - Resets position with `position_size_limit` (USD allocation)
  - Logs initial position in USD

### Key Methods

**run_instantly(test_buy_sell=False):**
- Starts infinite polling loop
- Updates candles, indicators, and calls `do()` each iteration
- Parameter `test_buy_sell`: If True, runs `do_test_buy_sell()` for testing borrow/repay and order flows instead

**do():**
- Main decision and execution handler
- Calls `wait()` to evaluate strategy, then `trade_action()` to execute
- Saves position and action state after each step
- Adjusts polling interval based on action state

**wait(action_msg):**
- Evaluates StrategyManager for trading signals
- Routes to position.open() for entry signals (long/short)
- Routes to position.close() for exit signals
- Routes to position.set_stop_loss() for stop-loss adjustments
- Checks safety conditions and applies automatic stop-loss triggers
- Handles state transitions and saves action messages

**trade_action(position):**
- Manages order lifecycle: place, monitor fills, cancel, finalize
- Implements priority: stop-loss orders override normal orders
- Calls process_executed_orders() to check fills
- Calls place_valid_order() to submit new orders

**place_valid_order():**
- Validates order amount against exchange minimums
- Calculates price with ATR adjustment for stop-loss orders
- Submits order via stock.item.trade()
- Checks immediate fills and processes if filled

**process_executed_orders(action_id):**
- Queries exchange for order status via stock.item.order_info()
- Processes fully filled orders: updates position, returns True
- Processes partially filled orders with small remainder: cancels remainder, returns True
- Returns False if order still pending or validation fails

**stop_loss_cancel_actions(action_id):**
- Cancels pending (NEW or PARTIALLY_FILLED) orders before stop-loss execution
- Processes executed portion of partially filled orders
- Returns True if canceled successfully, False otherwise

**do_finalize_action(position):**
- Finalizes close actions: clears order IDs, drops invalid amounts, repays loans
- Finalizes open actions: sets state to SAFETY_CLOSE if coin acquired, repays loans if failed
- Calls position.finalize() to calculate revenue and reset for next trade

**do_finalize_open(position, force_close=False):**
- Similar to do_finalize_action() but called specifically during stop_open()
- Handles partial fills during opening phase

**prepare_funds(position):**
- Checks available funds and borrows additional if needed
- Queries stock.item.funds() for current balance
- Queries stock.item.get_aviable_loan() for available margin
- Calls stock.item.borrow() to borrow shortfall amount
- Updates position.set_loan() with borrowed amount

**stop_open():**
- Called when opening takes too long or price moves unfavorably
- Cancels pending open order or processes partial fill
- Calls do_finalize_open() to transition state

**reset_position(position_size_limit):**
- Creates new Position instance
- Sets full_position budget to position_size_limit
- Resets all trade state

**set_data(data):**
- Assigns data reference to robot, strategy_mngr, and position for consistency

**do_test_buy_sell():**
- Test harness for borrow/repay and order placement operations
- Places limit buy/sell, cancels, then places market orders
- Used for validating exchange connectivity and order flows

## Existing Approach

**Polling Architecture:**
- Implements sleep-based polling (not event-driven)
- Update period: 5 seconds if action in progress, 30 seconds if idle
- Full loop cycle: fetch data → calculate indicators → evaluate strategy → execute → sleep

**Fee Model:**
- Fee read from `stock.item.fee` at Robot init; sourced from `EXCHANGE_FEE` environment variable via `Stock_Binance.__init__`
- Never hardcoded; injected as constructor parameter into `StrategyManager` and `Position`
- Applied during position open amount calculations

**Exception Handling:**
- All exceptions in run_instantly loop trigger 2-minute sleep before reinit
- Catches specific exceptions: general Exception, RequestException, ReadTimeout, socket.timeout, urllib3.SocketError
- On error: reinitializes stock connection via do_stock_init()

**Position State Machine:**
- Position state drives available actions: UNKNOWN (wait), LONG, SHORT, SAFETY_CLOSE
- Order tracking: position.buy_id and position.sell_id store active order IDs
- State transitions: UNKNOWN → (OPEN_LONG/OPEN_SHORT) → SAFETY_CLOSE → (CLOSE_LONG/CLOSE_SHORT) → UNKNOWN
- State persistence: saved to `manual_setup/{PAIR}/position.json` after every do() step

**Margin Support:**
- Supports margin trading (isolated margin on Binance)
- On open: borrows required amount via stock.item.borrow(loan_coin, amount)
- On close: repays loan via stock.item.repay(loan_coin, amount)
- Loan tracking: position.loan field stores current obligation

**Action Routing:**
- Single position per pair: no concurrent open positions
- Action priority: stop-loss actions override normal entry/exit
- Actions routed by position state and strategy signal type
- Action state saved to `shared/actions/{timestamp}.pkl` for visualization

**Logging & Monitoring:**
- All operations logged via log() and log_error() functions
- Revenue tracked via log_revenue() to separate file
- Order operations logged with details: type, price, amount, USD value, order ID

## Potential Improvements

1. **Event-Driven Architecture**: Replace sleep-based polling with WebSocket subscriptions to Binance (userDataStream for fills, mark price for real-time prices) to reduce latency and API consumption

2. **Portfolio Support**: Extend to manage multiple concurrent open positions per pair and multiple pairs simultaneously, with position sizing across portfolio

3. **Dynamic Fee Configuration**: Read fee from exchange or config file instead of hardcoding 0.002; support different fees for different trading pairs or order types

4. **Configurable Polling Intervals**: Move update_period values to config file; support adaptive intervals based on market volatility or action state

5. **Order Timeout Logic**: Implement timeout mechanism for pending orders (e.g., cancel if not filled within 5 minutes) to prevent capital lockup

6. **Partial Position Sizing**: Support configurable position size as fraction of available capital rather than fixed USD amount

7. **Price Slippage Protection**: Implement slippage checks comparing expected fill price to actual fill price, with automatic cancellation if slippage exceeds threshold

8. **Candle Validation**: Add checks for missing or out-of-order candles from Binance before processing

9. **Graceful Shutdown**: Add signal handlers (SIGINT, SIGTERM) to cleanly close positions and exit loop

10. **Performance Metrics**: Track iteration timing, API latency, and execution statistics for monitoring system health

11. **Multi-Strategy Coordination**: Support multiple strategy instances running in parallel with conflict resolution (e.g., latest decision wins, voting mechanism)

12. **Incremental Indicator Updates**: Cache and update indicators incrementally for new candles instead of recalculating on all historical data
