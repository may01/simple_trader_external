# Robot Class Specification

## Class Overview

The `Robot` class is the live trading execution engine of pybtctr2, responsible for executing buy/sell orders on the Binance exchange in real-time. It is the primary interface between the strategy evaluation pipeline (via `StrategyManager`) and the brokerage API (via `stock` module).

The Robot operates as a continuous polling loop (`run_instantly()`) that cycles through strategy evaluation, position state management, and order execution. At each iteration (every 5–30 seconds depending on position state), it fetches fresh market data (OHLC candles and order book depth), evaluates the active trading strategy, and either maintains the current position or executes new trading actions (open long, open short, close, stop-loss).

The Robot is designed for margin trading on Binance Spot and Margin accounts, supporting both long (buy-to-sell) and short (borrow-sell-repay) positions. It maintains persistent state via JSON files to enable crash recovery and position recovery across restarts.

## Key Attributes

| Attribute | Type | Scope | Description |
|-----------|------|-------|-------------|
| `fee` | float | Class | Fixed broker fee (0.002 = 0.2%). Hardcoded; update if Binance fee structure changes. |
| `update_period` | int | Instance | Sleep duration between polling cycles (seconds). Set to 5 when position is open, 30 when waiting. |
| `risk_per_trade` | float | Class | Maximum risk per trade as fraction of capital (0.01 = 1%). Currently unused; placeholder for position sizing logic. |
| `expected_target_top` | float | Class | Expected profit target (unused; reserved for future enhancement). |
| `expected_target_bottom` | float | Class | Expected loss target (unused; reserved for future enhancement). |
| `full_candles_list` | list[int] | Instance | Available OHLC timeframes (e.g., [1, 5, 15, 60, 240, 1440] minutes). Set from `data.candles` at init. |
| `strategy_mngr` | StrategyManager | Instance | Strategy evaluation engine; returns action signals for current position state. |
| `position` | Position | Instance | Current trade position state: open/closed, long/short, entry price, quantity, fees, PnL. |
| `schedule` | list | Instance | Scheduled actions (not currently used; reserved for async action queuing). |
| `cur_action` | list | Instance | Current action state (not currently used; reserved for multi-action coordination). |
| `sleep_on_step` | bool | Instance | If True, sleep between polling cycles. If False, poll without sleep (used for testing). |
| `test` | bool | Instance | Test flag (set to False by default; unused). |

## Constructor

### `__init__(position_size_limit, use_test_strategy)`

**Parameters:**
- `position_size_limit` (float): Maximum USD capital to deploy per trade. Sets the initial `position.full_position`.
- `use_test_strategy` (bool): If True, use test/demo strategy; if False, use production strategy. Passed to `StrategyManager`.

**Initialization Logic:**
1. Extract available OHLC candle timeframes from global `data.candles` and store in `self.full_candles_list`.
2. Create `StrategyManager` instance with broker fee from `stock.item.fee` and strategy selection flag.
3. Initialize a new `Position` object (thread 0, with broker fee) and set its capital limit.
4. Initialize empty `schedule` and `cur_action` lists for future use.
5. Set `sleep_on_step = True` (polling-based execution with sleep between cycles).
6. Log initial capital: "START: usd(%s)".

**Preconditions:**
- Global `data` object must be initialized with valid OHLC candles.
- Global `stock` object must be initialized (Binance API client).
- `position_size_limit` should be > 0.

**Exceptions:**
- May raise exceptions from `StrategyManager` or `Position` initialization if configuration is invalid.

---

## Key Methods & Interfaces

### `run_instantly(test_buy_sell=False)`

**Purpose:** Main polling loop for live trading execution.

**Parameters:**
- `test_buy_sell` (bool, optional): If True, run borrowing/lending tests (`do_test_buy_sell()`) instead of live trading. Default: False.

**Return Type:** None (infinite loop until external interrupt).

**Behavior:**
1. Enter infinite loop.
2. If `test_buy_sell` is True:
   - Call `do_test_buy_sell()` to test borrow/repay and buy/sell order operations.
3. Else (normal trading mode):
   - Call `data_item.update_candles()` to fetch fresh OHLC data for all timeframes.
   - Call `data_item.get_depth_data(1000)` to fetch order book snapshot.
   - Update `data_item.cur_point` to current Unix timestamp.
   - Update manual data (signals, manual indicators).
   - Assign data reference to position, strategy manager.
   - Calculate technical indicators for all candles via `Indicators.calc()`.
   - Call `stock.item.set_operation_sleep()` to enforce API rate limiting.
   - Call `self.do()` to execute one polling iteration.
   - Catch exceptions: log error, set `update_period = 120` (2 min), sleep, reinit stock.

**Preconditions:**
- Robot must be initialized with valid position and strategy.
- Data source must be accessible (Binance API).
- Binance API credentials must be set in environment.

**Postconditions:**
- Market data is fetched and indicators are calculated.
- One `do()` iteration is executed.
- Thread sleeps for `update_period` seconds before next iteration.

**Exceptions:**
- `requests.exceptions.RequestException`: Network/HTTP error. Logs error, sleeps 2 min, reinits stock.
- `requests.exceptions.ReadTimeout`: API timeout. Same recovery as RequestException.
- `socket.timeout`: Socket timeout. Same recovery.
- `urllib3.SocketError`: Low-level socket error. Same recovery.
- Generic `Exception`: Unexpected error during data fetch. Logs error, sleeps, reinits stock.

---

### `do()`

**Purpose:** Execute one polling cycle: strategy evaluation, position management, and order execution.

**Return Type:** None.

**Behavior:**
1. Log current position state (verbose).
2. Create `Action()` message with empty multiply arrays, set time to current timestamp.
3. Call `wait()` to evaluate strategy and set position action; receive `immediate_next_step` flag.
4. Restore position state from persistent storage.
5. If not `immediate_next_step`:
   - Check if position is in open-pending state (`STRATEGY_ACTION_OPEN_LONG/SHORT`).
   - If yes, verify via `position.check_stop_open()` or `position.close_by_time()` whether to abort the open.
   - If abort condition met, call `stop_open()` and set `immediate_next_step = True`.
6. If not `immediate_next_step` and position has a pending action:
   - Call `trade_action()` to execute or monitor the pending order.
7. Save position state to persistent storage.
8. Save action message with timestamp.
9. Update `update_period`: 5 sec if position active, 30 sec if idle.
10. Log completion: "OK (coin): timestamp L:action_long, S:action_short".
11. If `sleep_on_step` and not `immediate_next_step`, sleep for `update_period` seconds.

**Postconditions:**
- Position state is updated and persisted.
- All pending actions are processed (executed, monitored, or aborted).
- Next polling cycle delay is set based on position state.

**Exceptions:**
- Generic `Exception`: Logs error, sleeps, resets position to `full_position`.
- `requests.exceptions.RequestException`: Logs connection error, sleeps 2 min.
- `requests.exceptions.ReadTimeout`: Same as RequestException.
- `socket.timeout`: Same as RequestException.
- `urllib3.SocketError`: Same as RequestException.

---

### `wait(action_msg)`

**Purpose:** Evaluate strategy signals and manage position state transitions. Returns whether to execute next iteration immediately.

**Parameters:**
- `action_msg` (Action): Action message to record strategy decision and trade details.

**Return Type:** bool
- True: Execute next iteration immediately (e.g., after stop-loss setup).
- False: Continue normal flow (sleep, then next iteration).

**Behavior:**

1. **Signal Evaluation:**
   - Set position state and type in strategy manager data.
   - Call `strategy_mngr.check()` to evaluate all signals and return: (strategy_action, open_price, close_price, stop_price, time_frame).

2. **Safety Checks (if position open):**
   - Call `position.safety_update()` to override strategy action if safety level is breached (e.g., hard stop-loss).

3. **Open Long (if position is closed):**
   - If strategy says `STRATEGY_ACTION_OPEN_LONG` and position is not already opening long:
     - Call `position.open()` to initialize long position with prices and timeframe.
     - If successful: log, set action message, call `prepare_funds()` to borrow if needed, return False.

4. **Open Short (if position is closed):**
   - If strategy says `STRATEGY_ACTION_OPEN_SHORT` and position is not already opening short:
     - Call `position.open()` to initialize short position.
     - If successful: log, set action message, call `prepare_funds()`, return False.

5. **Close Long (if position is long):**
   - If strategy says `STRATEGY_ACTION_CLOSE_LONG` or `CLOSE_LONG_PART`:
     - Call `position.close()` to set close prices and timeframe.
     - If successful: log, set action message, return False.

6. **Close Short (if position is short):**
   - If strategy says `STRATEGY_ACTION_CLOSE_SHORT` or `CLOSE_SHORT_PART`:
     - Call `position.close()` to set close prices.
     - If successful: log, set action message, return False.

7. **Move Stop-Loss (if position open):**
   - If strategy says `STRATEGY_ACTION_MOVE_STOP_LOSS_LONG/SHORT`:
     - Call `position.set_stop_loss()` with new stop price.
     - If successful: log, set action message, return False.

8. **Stop-Loss Execution (if position open):**
   - If `position.check_stop_loss()` returns True (stop triggered):
     - If not already executing stop-loss:
       - Call `position.setup_stop_loss()` to initialize stop-loss action.
       - If setup fails: attempt `stop_loss_cancel_actions()` or `process_executed_orders()` to finalize prior action.
       - If prior action finalizes: call `do_finalize_action()`, return True.
       - Else: log error and assert failure.
     - Set action message type, log "STOP_LOSS", save action.

9. **Action Logging:**
   - If strategy action != NOTHING: save action message with candle snapshots and order book depth.

10. **Return:** False (normal next iteration).

**Preconditions:**
- Position must be initialized.
- Strategy manager must have current market data.

**Postconditions:**
- Position state is updated if action triggered (open/close/stop-loss).
- Action message is logged if action is triggered.
- Strategy action is atomically applied (no partial state updates).

**Exceptions:**
- Assertion: "Can't finalize action for stop loss" if prior action cannot be finalized before setting stop-loss.

---

### `trade_action(position)`

**Purpose:** Execute or monitor a pending trading action (order placement, order monitoring, order finalization).

**Parameters:**
- `position` (Position): The position object with current action state.

**Return Type:** bool
- True: Next iteration should execute immediately (e.g., after stop-loss order placed).
- False: Continue normal flow (sleep before next iteration).

**Behavior:**

1. **If Stop-Loss is Active:**
   - If order is in progress:
     - Try `process_executed_orders()` to check if order filled.
     - If not filled: cancel order via `stop_loss_cancel_actions()`, return True (restart iteration).
     - If filled: finalize via `do_finalize_action()`, return False.
   - If no order in progress: proceed to place new order.

2. **Else (Normal action: open/close):**
   - If order is in progress:
     - Try `process_executed_orders()` to check if order filled.
     - If filled: finalize via `do_finalize_action()`, return False.

3. **Place New Order (if no order in progress):**
   - Call `place_valid_order()` to place a new market/limit order.
   - If `place_valid_order()` returns True (order finalized): call `do_finalize_action()`.
   - Return False.

**Postconditions:**
- Order is placed, monitored, or finalized based on current state.

**Exceptions:**
- None explicitly thrown; errors logged within sub-methods.

---

### `place_valid_order()`

**Purpose:** Place a new trading order (buy or sell) at the best available price, handling order validation and immediate execution.

**Return Type:** bool
- True: Order is finalized (fully executed or canceled due to invalid amount).
- False: Order is pending execution or a new order was placed.

**Behavior:**

1. **Determine Order Price:**
   - Use current close price: `data.get_cur_price("close", 0)`.
   - If this is a stop-loss order: adjust price down by 0.5 * ATR(1) to avoid slippage.

2. **Calculate Order Amount:**
   - Call `position.get_action_amount(price)` to compute order size based on available capital and position type.

3. **Validate Order Amount:**
   - If amount is too small (below minimum): log error, finalize action.
   - Return True.

4. **Place Order on Binance:**
   - Call `stock.item.trade()` with trade type (BUY/SELL), price, amount.
   - If successful: store order ID in position, log order details.
   - If fails: log error and return False.

5. **Check for Immediate Execution:**
   - Query order status via `stock.item.order_info()`.
   - If order is already filled: process via `position.process_action()`, return True.

6. **Return:** True if finalized, False if order is pending.

**Preconditions:**
- Position must have a valid action (OPEN_LONG/SHORT, CLOSE_LONG/SHORT, STOP_LOSS).
- Adequate balance must exist (may borrow via `prepare_funds()`).

**Postconditions:**
- Order is placed or finalized.
- Order ID is stored in position (or reset to 0 if finalized).

**Exceptions:**
- None explicitly thrown; HTTP errors logged from `stock.item` calls.

---

### `process_executed_orders(action_id)`

**Purpose:** Check if a pending order has executed (fully or partially), and finalize it if complete.

**Parameters:**
- `action_id` (int): Order ID to check.

**Return Type:** bool
- True: Order is fully executed or canceled (action can proceed to finalization).
- False: Order is still pending (keep monitoring).

**Behavior:**

1. **Fetch Order Status:**
   - Call `stock.item.order_info(action_id)` to get order details.
   - If query fails: log error, return False.

2. **If Order is FILLED:**
   - Process via `position.process_action()` with full amount and fill price.
   - Log "[immediate] Order complete".
   - Return True.

3. **If Order is PARTIALLY_FILLED:**
   - Check if remaining amount is below minimum via `stock.item.is_invalid_amount()`.
   - If yes: cancel remaining amount, log, finalize.
   - Validate the filled amount is not too small; if so, drop position.
   - Log "order complete (low amount was cut)".
   - Return True.

4. **Else (Order is NEW or still partially filled with valid amount):**
   - Return False (keep monitoring).

**Preconditions:**
- `action_id` must be non-zero (enforced via assertion).
- Binance API must be accessible.

**Postconditions:**
- If True: order amount is processed into position state.
- If False: order remains pending, no state change.

**Exceptions:**
- Assertion: "action_id is 0" if called with invalid action_id.
- No exceptions thrown; errors logged.

---

### `stop_loss_cancel_actions(action_id)`

**Purpose:** Cancel a pending order before executing a stop-loss action. Handles partial fills.

**Parameters:**
- `action_id` (int): Order ID to cancel.

**Return Type:** bool
- True: Order was successfully canceled (or was already filled/invalid).
- False: Order could not be canceled.

**Behavior:**

1. **Skip if no order:** If action_id == 0, return False.

2. **Query Order Status:**
   - Call `stock.item.order_info(action_id)`.

3. **If Order is NEW or PARTIALLY_FILLED:**
   - Call `stock.item.cancel_order(action_id)`.
   - If successful:
     - Query final order state via `stock.item.order_info()` to get executed amount.
     - Process executed amount via `position.process_action()`.
     - Set action_id to 0 in position.
     - Log "Order was canceled to execute stop loss".
     - Return True.
   - If cancel fails: log error, return False.

4. **If Order is already FILLED or CANCELED:**
   - Return False (no further action needed; order already final).

**Postconditions:**
- If True: order is canceled, executed amount is recorded, action_id is cleared.
- If False: order state is unchanged.

---

### `do_finalize_action(position)`

**Purpose:** Finalize a trade action after it completes (order filled). Handles position closure, repayment of margin loans, and PnL calculation.

**Parameters:**
- `position` (Position): Position to finalize.

**Return Type:** bool
- True: Action was finalized successfully.
- False: Action could not be finalized (error state).

**Behavior:**

1. **If Action is CLOSE (LONG/SHORT, full or partial):**
   - Reset buy_id and sell_id to 0.
   - Get current price.
   - If remaining coin amount is too small: drop position.
   - If position is fully closed:
     - If loan exists: repay via `stock.item.repay()`, log repay amount.
     - Call `position.finalize()` to compute final PnL.
     - Log and record revenue in log file.
   - Else (partial close):
     - If in safety state: transition to close state.

2. **If Action is OPEN (LONG/SHORT):**
   - Check if any coins were acquired (`position.coin_used() > 0`).
   - If yes: transition to safety state, set action_id to 0 (no new order placed yet).
   - If no coins acquired (order never filled):
     - If loan exists: repay.
     - Call `position.finalize()` (empty finalization).

3. **Else (unknown action):**
   - Log error, return False.

4. **Clear Action:**
   - Set position action to `STRATEGY_ACTION_NOTHING`.

5. **Return:** True.

**Postconditions:**
- Position state is updated (closed or in safety state).
- Any margin loans are repaid.
- PnL is calculated and logged (if position closed).
- Action is cleared.

**Exceptions:**
- Returns False if action type is invalid.

---

### `do_finalize_open(position, force_close=False)`

**Purpose:** Finalize an open action (called when open is aborted before completion).

**Parameters:**
- `position` (Position): Position to finalize.
- `force_close` (bool, optional): Unused parameter. Default: False.

**Return Type:** bool
- True: Open was finalized.
- False: Open action was not valid.

**Behavior:**

1. **If Action is OPEN:**
   - If coins were acquired: set state to safety state, clear action_id.
   - Else: repay loan (if any), finalize position, return False.

2. **Else (invalid action):**
   - Log error.
   - If no coins were acquired: finalize position.
   - Return False.

3. **Set Action to NOTHING and state to WAIT.**

4. **Return:** True if open was valid and finalized.

---

### `is_action_in_progress()`

**Purpose:** Check if a trading order is currently pending.

**Return Type:** bool
- True: Pending order exists (action_id != 0).
- False: No pending order.

**Note:** This method is called but not defined in the source; likely delegates to `position.is_action_in_progress()`.

---

### `prepare_funds(position)`

**Purpose:** Prepare capital for a new position by borrowing margin if needed.

**Parameters:**
- `position` (Position): Position requiring funds.

**Return Type:** int (STATUS_SUCCESS or STATUS_FAIL).

**Behavior:**

1. **Query Available Funds:**
   - Call `stock.item.funds()` to get current balance in the loan coin.

2. **Query Available Loan Limit:**
   - Call `stock.item.get_aviable_loan()` to get maximum borrowable amount.

3. **Calculate Loan Amount:**
   - Determine position size needed (from position object).
   - Loan amount = max(position_size - current_funds, 0), capped at available_loan.
   - If loan amount > 0: borrow via `stock.item.borrow()`, record in position.

4. **Validate Position Size:**
   - Call `position.validate_position_size()` to ensure minimum amounts.

5. **Return:** STATUS_SUCCESS if funds prepared, STATUS_FAIL otherwise.

**Exceptions:**
- Returns STATUS_FAIL if any step fails (logged internally).

---

### `set_data(data)`

**Purpose:** Assign a data source (OHLC, depth, indicators) to the robot and all its sub-components.

**Parameters:**
- `data` (Data): Data object with candles, depth, and indicators.

**Behavior:**
- Set `self.data = data`.
- Set `self.strategy_mngr.data = data`.
- Set `self.position.data = data`.

---

### `reset_position(position_size_limit)`

**Purpose:** Reinitialize position state after an error or crash.

**Parameters:**
- `position_size_limit` (float): Capital limit to restore.

**Behavior:**
- Create new `Position` object with thread 0, broker fee, real stock flag.
- Set capital limit to `position_size_limit`.
- Log reset message.

---

### `do_test_buy_sell(test_buy_sell=False)` [Internal Testing Method]

**Purpose:** Test borrow/repay and buy/sell operations without live risk.

**Behavior:**
1. Fetch depth data (bid/ask prices).
2. Test borrowing and repaying for long and short positions.
3. Test buy orders (waiting and immediate).
4. Test sell orders (waiting and immediate).
5. Test order cancellation and monitoring.

**Used for:** Manual validation of API connectivity and order lifecycle before live trading.

---

## State Management

### Position State Transitions

The Robot enforces a state machine for position transitions:

```
POSITION_CLOSED
  → (strategy says OPEN_LONG) → POSITION_OPENING_LONG
  → (strategy says OPEN_SHORT) → POSITION_OPENING_SHORT

POSITION_OPENING_LONG
  → (order fills, coin acquired) → POSITION_LONG_SAFETY
  → (order never fills, timeout) → POSITION_CLOSED

POSITION_OPENING_SHORT
  → (order fills, coin borrowed) → POSITION_SHORT_SAFETY
  → (order never fills, timeout) → POSITION_CLOSED

POSITION_LONG_SAFETY
  → (strategy says CLOSE_LONG) → POSITION_LONG_CLOSING
  → (stop-loss triggered) → POSITION_LONG_STOP_LOSS

POSITION_SHORT_SAFETY
  → (strategy says CLOSE_SHORT) → POSITION_SHORT_CLOSING
  → (stop-loss triggered) → POSITION_SHORT_STOP_LOSS

POSITION_LONG_CLOSING / POSITION_SHORT_CLOSING
  → (order fills, all coins sold) → POSITION_CLOSED

POSITION_LONG_STOP_LOSS / POSITION_SHORT_STOP_LOSS
  → (order fills, all coins sold) → POSITION_CLOSED
```

### Action Types

- `STRATEGY_ACTION_NOTHING`: No action; wait for signal.
- `STRATEGY_ACTION_OPEN_LONG`: Buy coins at limit price (margin buy).
- `STRATEGY_ACTION_OPEN_SHORT`: Borrow and sell coins (margin sell).
- `STRATEGY_ACTION_CLOSE_LONG`: Sell all or part of long position.
- `STRATEGY_ACTION_CLOSE_SHORT`: Buy back and repay all or part of short position.
- `STRATEGY_ACTION_MOVE_STOP_LOSS_LONG/SHORT`: Adjust stop-loss price.
- `STRATEGY_ACTION_DO_STOP_LOSS`: Execute stop-loss (triggered by price breach).

### Invariants Maintained

1. **Single Position:** Only one open position (long or short) at a time; no portfolio netting.
2. **Order Sequencing:** Orders are placed, monitored, and finalized in strict sequence; no concurrent orders.
3. **Loan Lifecycle:** Loans are tracked and repaid when position closes; state persisted to disk.
4. **Atomic Actions:** Position state and action are updated together, preventing partial-update races.
5. **Price Data Consistency:** All price decisions use the same timestamp (`data_item.cur_point`).

---

## Error Handling

### Exception Types and Recovery

| Exception | Trigger | Recovery |
|-----------|---------|----------|
| `requests.exceptions.RequestException` | Network error during API call | Log, sleep 2 min, reinitialize stock object, retry |
| `requests.exceptions.ReadTimeout` | API read timeout | Sleep 2 min, reinit stock |
| `socket.timeout` | Socket-level timeout | Sleep 2 min, reinit stock |
| `urllib3.SocketError` | Low-level socket error | Sleep 2 min, reinit stock |
| Generic `Exception` in `do()` | Any other error (data corruption, signal eval failure) | Log, sleep `update_period`, reset position to capital limit, retry |
| Order execution fails | `stock.item.trade()` returns error | Log error details, skip order placement, retry in next cycle |
| Order cancellation fails | Cannot cancel pending order | Log error, attempt to proceed with stop-loss; may leave position partially open |
| Insufficient balance | Position size exceeds available funds after borrowing | Reduce position size, retry; if still insufficient, drop position |

### Failure Modes & Recovery

1. **Network Disconnection:**
   - Detection: RequestException, ReadTimeout, SocketError.
   - Impact: Data fetch stalls, orders cannot execute.
   - Recovery: Increase `update_period` to 2 minutes, wait, reinitialize stock connection, resume normal polling.

2. **Order Timeout (No Execution):**
   - Detection: Order remains NEW or PARTIALLY_FILLED after several polling cycles.
   - Current behavior: Order remains active; no automatic timeout.
   - Recommendation: Add timeout threshold (e.g., 5 min) to auto-cancel stale orders.

3. **Insufficient Balance:**
   - Detection: `stock.item.trade()` fails with "insufficient balance" error.
   - Impact: Cannot open or increase position.
   - Recovery: Log error, skip order, reduce position size for next attempt, or wait for prior position to close.

4. **Margin Loan Repayment Failure:**
   - Detection: `stock.item.repay()` fails.
   - Impact: Position cannot finalize; account may be flagged.
   - Recovery: Log error, retry repayment in next cycle. If persistent, manual intervention required.

5. **Crash and Recovery:**
   - Detection: Process restart.
   - Recovery: Robot loads position state from disk (JSON file), resumes from last action, revalidates balance and order status, and continues.

---

## Existing Approach

### Architecture Decisions

1. **Polling-Based Polling Loop:**
   - Robot runs `run_instantly()` as an infinite loop with periodic sleeps.
   - Advantages: Simple, deterministic, easy to debug.
   - Disadvantages: Inefficient (sleeps even when no action needed), latency (action delayed until next poll), not scalable to multiple positions/pairs.
   - Polling frequency: 5 sec (position open), 30 sec (idle).

2. **Hardcoded Fee (0.2%):**
   - Fee is set as class variable `Robot.fee = 0.002`.
   - Applied uniformly to all trades (buy and sell).
   - Assumptions: Binance standard fee structure; no volume discounts, no VIP tiers.

3. **Single Position Model:**
   - Only one open position (long or short) per Robot instance.
   - No portfolio netting; no concurrent trades.
   - Simple state management; complex multi-leg strategies not supported.

4. **Position State Machine:**
   - Position state is the primary driver of action routing.
   - Transitions are explicit and synchronized with Binance order state.
   - Stop-loss is checked at every polling cycle and interrupts any pending action.

5. **Margin Loan Management:**
   - For long positions: `position_size = (capital * leverage) / price`; borrow `max(0, position_size - available_cash)`.
   - For short positions: borrow `position_size / price` coins, sell at current price, repay when closing.
   - Loans are persisted in position state; repayment is triggered on position close.

6. **JSON State Persistence:**
   - Position state is saved to JSON after each action via `position.save_position()`.
   - Enables crash recovery: restart robot, load prior state, resume trading.
   - Trade actions are also logged to JSON via `action_msg.save()`.

---

## Potential Improvements

1. **Event-Driven Architecture**
   - Replace polling loop with WebSocket-based market updates and order notifications.
   - Benefit: Lower latency, higher efficiency, real-time response to price changes.
   - Complexity: Requires async event handling, WebSocket reconnection logic, deduplication of events.

2. **Portfolio Model (Multiple Positions)**
   - Support multiple concurrent positions (e.g., long LINK and short BTC simultaneously).
   - Benefit: Hedge strategies, pair trading, diversification.
   - Complexity: Position coordination, margin calculation across positions, risk management across portfolio.

3. **Dynamic Fee Configuration**
   - Read fee from Binance API at init; support VIP tiers or variable fees.
   - Benefit: Accurate PnL calculation, leverage VIP discounts.
   - Complexity: Fee structure changes, caching strategy.

4. **Order Timeout and Replacement Logic**
   - Set timeout threshold (e.g., 5 minutes) for pending orders.
   - If timeout: cancel and retry with adjusted price or amount.
   - Benefit: Prevents stuck orders, adapts to market movement.
   - Complexity: Price adjustment heuristics, slippage calculation, rollback safety.

5. **Slippage Protection**
   - Track bid-ask spread; reject orders if spread exceeds threshold.
   - Benefit: Prevent bad fills in low-liquidity markets.
   - Complexity: Spread calculation, threshold tuning per pair/timeframe.

6. **Incremental Position Sizing**
   - Break large position into multiple orders (pyramiding/averaging).
   - Benefit: Reduce market impact, better fills, flexibility to scale in/out.
   - Complexity: Partial position tracking, PnL aggregation, risk management per tranche.

7. **Order Type Flexibility**
   - Support market orders (immediate), limit orders (price-sensitive), stop-loss orders (automatic on Binance).
   - Benefit: Better execution, reduced manual monitoring.
   - Complexity: Order type selection logic, fill rate tracking.

8. **Logging and Monitoring Enhancements**
   - Structured logging (JSON) with timestamps, order IDs, PnL deltas.
   - Real-time dashboard showing position, orders, PnL.
   - Alerts for order failures, balance changes, margin calls.
   - Benefit: Transparency, faster issue detection.

9. **API Error Handling**
   - Distinguish between transient (retry) and permanent (abort) errors.
   - Exponential backoff for retries.
   - Benefit: Robust connection handling, reduced log noise.

10. **Position Risk Limits**
    - Enforce maximum position size, maximum loss per trade, maximum daily loss.
    - Benefit: Risk containment, regulatory compliance.
    - Complexity: Limit enforcement at order placement vs. position finalization.

---

## Related Interfaces

- **Position** (`position/position.py`): Manages trade state, PnL, entry/exit prices.
- **StrategyManager** (`strategy_manager.py`): Evaluates signals and returns action recommendations.
- **Stock/Binance API** (`stocks_holder.py`): Low-level trade execution, balance queries, order monitoring.
- **Data** (`data.py`): OHLC candles, depth data, indicator calculations.
- **Action** (`strategies/actions.py`): Trade action messages logged for audit trail.
