# ShortPosition Class Specification

## 1. Class Overview

**ShortPosition** implements the complete lifecycle of a short trade (also called short selling), where the trader borrows an asset at a high price, sells it immediately, and aims to buy it back at a lower price to return the asset and profit from the price difference. This class extends **BasePosition** and reverses the semantic meaning of opening and closing operations compared to LongPosition.

The ShortPosition class manages graduated short entry and exit strategies, where the trader sells in tranches at descending price levels during opening, and buys back in tranches at ascending price levels during closing. It handles margin loan management, stop-loss enforcement (buying back immediately if price rises against the position), and P&L calculation specific to short positions where profit = (sell_price - buy_price - fees) / sell_price.

Unlike long positions that benefit from price increases, short positions profit when the asset price decreases. The position requires careful risk management to prevent losses from unlimited upside price movements, enforced by mandatory stop-loss mechanics.

## 2. Key Attributes

| Attribute | Type | Description | Inherited |
|-----------|------|-------------|-----------|
| `price_open` | List[float] | Array of sell prices for graduated short entry (descending or equal) | Yes |
| `price_close` | List[float] | Array of buy-back prices for graduated exit (ascending or equal) | Yes |
| `price_stop_loss` | float | Maximum price at which position is forcibly closed (hard ceiling on loss) | Yes |
| `action_price` | float | Current action price from strategy | Yes |
| `executed_open` | List[float] | Actual sell prices executed during opening phase | Yes |
| `executed_open_amount` | List[float] | Amount (in base coin, e.g., USD) sold at each price level | Yes |
| `executed_close` | List[float] | Actual buy-back prices executed during closing phase | Yes |
| `executed_close_amount` | List[float] | Amount (in asset coin) bought back at each price level | Yes |
| `coinUse` | Coin | The asset being shorted (coin, e.g., ETH) - loaned and sold first | Yes |
| `coinGet` | Coin | The base currency received from sale (e.g., USD) - used to buy back | Yes |
| `state` | int | Current state: WAIT_BUY (awaiting buy-back orders) or WAIT_SAFETY_BUY | Yes |
| `action` | int | Current action: OPEN_SHORT, CLOSE_SHORT, CLOSE_SHORT_PART, DO_STOP_LOSS | Yes |
| `position_type` | int | Always POSITION_TYPE_SHORT for this class | Yes |
| `open_time` | float | Timestamp when position was opened | Yes |
| `safety_close_time` | float | Timestamp deadline for safety close (buy-back all if reached) | Yes |
| `fee` | float | Taker fee from `stock.item.fee` — injected by caller; never hardcoded; applied on both sale and buy-back | Yes |
| `desired_revenue` | float | Target profit percentage | Yes |
| `risk_per_trade` | float | Maximum risk as fraction of capital per trade (e.g., 0.05 = 5%) | Yes |
| `full_position` | float | Total capital available for trading | Yes |

**ShortPosition has no additional attributes beyond BasePosition; the semantic reversal is handled through method implementation, not data structure changes.**

## 3. Constructor (`__init__`)

### Signature
```python
def __init__(self, coin_use: str, coin_get: str, full_position, thread_num, fee, use_safety: bool = True)
```

### Parameters
- **coin_use** (str): Asset being borrowed and sold (e.g., "eth")
- **coin_get** (str): Base currency received from the sale (e.g., "usdt")
- **full_position** (float): Total capital available for trading
- **thread_num** (int): Thread identifier for logging/concurrency
- **fee** (float): Taker fee from `stock.item.fee` — passed in by caller; never a default constant
- **use_safety** (bool): If `True` (default), entry fill transitions to `WAIT_SAFETY_BUY` for safety management; if `False`, stays in `WAIT_BUY` and skips safety phase

### Initialization Process
1. Calls `super().__init__(coin_use, coin_get, full_position, thread_num, fee, use_safety)` to initialize BasePosition attributes
2. Sets `self.position_type = POSITION_TYPE_SHORT` (identifies this as a short position)

### Notes
- The coinUse/coinGet role is **reversed** from LongPosition: coinUse is the asset being borrowed/sold, coinGet is the base currency received
- Coin names are passed explicitly rather than derived from a Data object

## 4. Key Methods & Interfaces

### open(price_open, price_close, price_stop_loss, time_period, action_msg)
**Purpose:** Initialize graduated short sell orders and compute position size. Prices are passed in already validated by Strategy (risk/reward checked via `validate_trade_risk()` before `open()` is called).

**Parameters:**
- **price_open** (List[float]): Array of sell prices (should be descending for shorts)
- **price_close** (List[float]): Array of buy-back prices (should be ascending)
- **price_stop_loss** (float): Maximum buy-back price to limit loss
- **time_period** (int): Time interval in minutes between candles
- **action_msg** (ActionMessage): Message object for logging/reporting

**Returns:** bool - True if position opened, False if state precondition not met (not in WAIT state)

**Logic Flow:**
1. Calculate average open price: `avg_price_open = sum(price_open) / len(price_open)`
3. Calculate risk: `risk = price_stop_loss - avg_price_open * (1 - 2*fee)` (distance to stop in USD/coin)
4. Calculate position size: `cur_position_size = min(full_position/avg_price_open, full_position/avg_price_open * (risk_per_trade / (risk/avg_price_open)))`
5. Store price_open, price_close, price_stop_loss; set state to WAIT_BUY
6. Set coinUse.action_amount = total_size / len(price_open) (amount to sell at each level)
7. Set action to STRATEGY_ACTION_OPEN_SHORT

**Key Differences from LongPosition:**
- Risk calculation uses subtraction from stop-loss (shorts risk loss if price goes UP)
- Position size is scaled by `1/avg_price_open` (different currency math)

### close(price_close, price_stop_loss, time_period, action_msg)
**Purpose:** Prepare graduated buy-back orders to exit the short position

**Parameters:**
- **price_close** (List[float]): Target buy-back prices
- **price_stop_loss** (float): Updated stop-loss price
- **time_period** (int): Current time interval
- **action_msg** (ActionMessage): Message object

**Returns:** bool - True if close prepared, False if not in buyable state

**Logic Flow:**
1. Check if state is WAIT_BUY or WAIT_SAFETY_BUY (position must be in hold state)
2. Update first close price to current target
3. If in WAIT_SAFETY_BUY state:
   - Set stop-loss to safety level: `zero_price() * (1 + direction_profit(fee))`
   - Set action to STRATEGY_ACTION_CLOSE_SHORT_PART (partial close)
   - Set coinGet.action_amount = 0.3 * coinGet.size (buy back 30% of holdings)
4. Otherwise (WAIT_BUY):
   - Set stop-loss to provided price
   - Set action to STRATEGY_ACTION_CLOSE_SHORT (full close)
   - Set coinGet.action_amount = coinGet.size (buy back everything)

### record_entry_fill(coin_amount, price)
**Purpose:** Execute a short sale entry — borrow coins, sell for base currency.

**Parameters:**
- **coin_amount** (float): Number of coins borrowed and sold in this fill
- **price** (float): Actual execution price (USD/coin)

**Logic Flow:**
1. Check action is STRATEGY_ACTION_OPEN_SHORT
2. Constrain: `capped = min(coinUse.size, coinUse.want_to_use, coin_amount)`
3. Append `price` to `executed_open`, `capped` to `executed_open_amount`
4. `coinUse.size -= capped` (reduce available borrowed coins)
5. `coinUse.used += capped` (track amount sold)
6. `coinGet.size += capped * price * (1 - fee)` (receive base currency net of fee)
7. Transitions state: if `use_safety=True` → `POSITION_STATE_WAIT_SAFETY_BUY`; if `use_safety=False` → `POSITION_STATE_WAIT_BUY` (exit-awaiting, safety phase skipped)

### record_exit_fill(coin_amount, price)
**Purpose:** Execute a short exit — buy back coins to repay the loan.

**Parameters:**
- **coin_amount** (float): Number of coins to repurchase in this fill
- **price** (float): Actual buy-back price (USD/coin)

**Logic Flow:**
1. Check action is STRATEGY_ACTION_CLOSE_SHORT, CLOSE_SHORT_PART, or DO_STOP_LOSS
2. Constrain: `capped = min(coinGet.size / price, coin_amount)` (USD available / price = coins affordable)
3. Append `price` to `executed_close`, `capped` to `executed_close_amount`
4. `coinGet.size -= capped * price` (reduce held USD)
5. `coinUse_change = capped * (1 - fee)` (coins returned to lender net of fee)
6. `coinUse.size += coinUse_change`
7. `coinUse.returned += coinUse_change`

### get_action_amount_in_coins(price)

Returns the order size in coin units for the current pending action.

**Parameters:**
- `price` (float): Current USD/coin price

**Logic:**
- If `is_wait_open_state()`: return `coinUse.action_amount` (already in coins — borrow amount)
- Else: return `coinGet.action_amount / price` (convert USD buy-back budget to coins)

### avg_price_open()
**Purpose:** Calculate average sell price (short entry)

**Returns:** float - Weighted average price paid for the shorted coins

**Formula for Short:**
```
bought_coin = sum(executed_open_amount[i] * executed_open[i])  // total USD value sold
used_tokens = sum(executed_open_amount)  // total USD spent
avg = bought_coin / used_tokens
```

**Note:** This calculates the USD-weighted average price at which coins were sold

### avg_price_close()
**Purpose:** Calculate average buy-back price (short exit)

**Returns:** float - Weighted average price paid to repurchase coins

**Formula for Short:**
```
bought_coin = sum(executed_close_amount[i] / executed_close[i])  // total coins bought back
returned_tokens = sum(executed_close_amount)  // total USD spent
avg = returned_tokens / bought_coin
```

**Note:** This calculates the total cost divided by total coins repurchased

### is_wait_open_state()
**Returns:** bool - True if action == STRATEGY_ACTION_OPEN_SHORT (waiting to sell coins)

### is_wait_close_state()
**Returns:** bool - True if state is WAIT_BUY or WAIT_SAFETY_BUY (waiting to buy back coins)

### get_coinBuy()
**Returns:** Coin - Returns coinGet (the base currency used for buying back)

### get_coinSell()
**Returns:** Coin - Returns coinUse (the asset being shorted/sold)

### get_trade_type()
**Purpose:** Determine the exchange trade operation type

**Returns:** int
- TRADE_SELL if action is STRATEGY_ACTION_OPEN_SHORT (short sale)
- TRADE_BUY if action is STRATEGY_ACTION_CLOSE_SHORT, CLOSE_SHORT_PART, or DO_STOP_LOSS (buy-back)
- STRATEGY_ACTION_NOTHING if action is unrecognized

### best_executed_open()
**Returns:** float - Maximum sell price executed (best price for short seller = highest price)

### best_executed_close()
**Returns:** float - Minimum buy-back price executed (best price for short buyer = lowest price)

### check_target(action_msg)
**Purpose:** Check if close target has been hit during safety phase

**Returns:** bool - True if target hit, False otherwise

**Logic:**
1. If state is WAIT_BUY, return False (target checking only in safety mode)
2. If state is WAIT_SAFETY_BUY:
   - If price_close[0] not set, initialize to: `avg_price_open + direction_loss(0.008 * avg_price_open)`
   - Get current low price from data
   - Return True if price_close[0] ≥ current_low (target has been reached or exceeded)

### safety_update(strategy_action, action_msg)
**Purpose:** Monitor safety conditions and enforce mandatory buy-back on timeout or SAR signal

**Parameters:**
- **strategy_action** (int): Current action from strategy
- **action_msg** (ActionMessage): Message for logging

**Returns:** int - Updated action (may be modified if safety triggered)

**Logic:**
1. If state is WAIT_SAFETY_BUY:
   - Check if `cur_time > safety_close_time` (cur_time passed by caller)
   - If expired, set stop-loss to SAR: `cur_data.get("sar", 15) * 1.001` (cur_data passed by caller)
   - This forces a buy-back at SAR price (safety exit)

### set_close_action()
**Purpose:** Set action to close the short position

**Behavior:** Sets action = STRATEGY_ACTION_CLOSE_SHORT

### set_close_state()
**Purpose:** Set state to waiting for buy-back

**Behavior:** Sets state = POSITION_STATE_WAIT_BUY

### get_safety_state()
**Returns:** int - POSITION_STATE_WAIT_SAFETY_BUY (safety phase for shorts is waiting for safe buy-back)

### get_close_state()
**Returns:** int - POSITION_STATE_WAIT_BUY (shorts wait for buy-back in close state)

### get_open_action()
**Returns:** int - STRATEGY_ACTION_OPEN_SHORT

### get_close_action()
**Returns:** int - STRATEGY_ACTION_CLOSE_SHORT

### check_new_action(new_action)
**Purpose:** Validate that new action is compatible with short position

**Logic:** Asserts False if action is OPEN_LONG, CLOSE_LONG, or CLOSE_LONG_PART (prevents accidental long actions on short)

## 5. Trade Lifecycle

### OPENING Phase
**Goal:** Establish short position by selling borrowed asset at declining prices

1. **Position Sizing:** open() calculates position_size based on full_position, risk_per_trade, and risk distance; risk/reward already validated by Strategy before open() is called
3. **Graduated Selling:**
   - coinUse.action_amount = position_size / len(price_open)
   - Sell tranches at descending price levels (highest to lowest)
   - Each `record_entry_fill()` call executes one tranche
4. **State Transition:** WAIT (initial) → WAIT_BUY (after first sale completes)
5. **Graduated Entry:** Shorter gets USD for each sale; positions herself for buy-back

**Example:** Sell 1 ETH at $2000, then 1 ETH at $1900, receive $3900 USD total (minus fees)

### HOLDING Phase
**Goal:** Monitor price movement and enforce stop-loss/target conditions

1. **Price Monitoring:** Track current price against price_stop_loss (hard ceiling)
2. **Safety Phase:** If in WAIT_SAFETY_BUY state:
   - Check if target price_close[0] has been reached
   - Check if safety_close_time has expired (force buy-back via SAR)
   - These are intermediate risk-reduction mechanics
3. **Stop-Loss Enforcement:** If current_price ≥ price_stop_loss, trigger immediate buy-back
4. **State:** Position remains in WAIT_BUY or WAIT_SAFETY_BUY

### CLOSING Phase
**Goal:** Exit short position by buying back asset at rising prices

1. **Preparation:** close() sets up buy-back orders
2. **Graduated Buy-Back:**
   - coinGet.action_amount = coinGet.size or 0.3 * coinGet.size (depending on safety)
   - Buy tranches at ascending prices (lowest to highest)
   - Each `record_exit_fill()` call executes one buy-back tranche
3. **Partial Closes:** In WAIT_SAFETY_BUY state, close only 30% of position; rest remains open
4. **Full Close:** In WAIT_BUY state, close entire position

**Example:** Use $1500 USD to buy back 0.75 ETH at $2000, then use $1500 to buy back 0.73 ETH at $2055

### FINALIZED Phase
**Goal:** Calculate final P&L and close position

1. **P&L Calculation:** (See section 6)
2. **State:** State becomes WAIT (neutral, ready for new trades)
3. **Return:** P&L percentage and absolute amount

## 6. P&L Calculation

### Revenue Formula for Shorts
```
Revenue (%) = (1 - (avg_price_close / avg_price_open) - 2 * fee) * 100
```

### Components
- **avg_price_open:** Weighted average price at which coins were sold (higher is better for shorts)
- **avg_price_close:** Weighted average price at which coins were repurchased (lower is better for shorts)
- **fee:** Trading fee (2x because charged on both sell and buy)

### Profit Condition
- Profit occurs when: `avg_price_close < avg_price_open` (buy back cheaper than sold)
- Loss occurs when: `avg_price_close > avg_price_open` (forced to buy back more expensive)

### Absolute Revenue
```
Revenue (USD) = avg_price_open * (coinUse.returned - coinUse.used)
```

This represents the net USD gain from the short trade.

### Example Calculation
```
- Sold 2 ETH at avg $2000 = $4000 received
- Bought back 2 ETH at avg $1900 = $3800 spent
- Fee = 0.2% (0.002)
- Revenue = (1 - (1900/2000) - 2*0.002) * 100
         = (1 - 0.95 - 0.004) * 100
         = 4.6%
- Absolute = $4000 - $3800 - (2*0.002*4000) = $120 profit
```

## 7. Risk Management

### Stop-Loss Mechanism
- **Hard Ceiling:** price_stop_loss is the maximum price the trader will accept before forced buy-back
- **Enforcement:** During holding phase, if current_price ≥ price_stop_loss, action becomes DO_STOP_LOSS
- **Execution:** Next `record_exit_fill()` call with DO_STOP_LOSS action executes emergency buy-back at market price
- **Protection:** Limits maximum loss; prevents unlimited liability of short positions

### Margin Loan Management
- **Borrowing:** During `record_entry_fill()`, coins are borrowed from exchange (simulated via coinUse.size decrease)
- **Tracking:** executed_open and executed_open_amount record all borrowed and sold amounts
- **Repayment:** During `record_exit_fill()`, bought coins are returned (tracked via coinUse.returned)
- **Loan Rate:** Fee subtracted from USD received during sale: `coinGet.size += action_size * price * (1 - fee)`

### Safety Phase Mechanics
- **Initial Close:** After position opened, enters WAIT_SAFETY_BUY state to close 30% at first target
- **Partial Exit:** close(CLOSE_SHORT_PART) only buys back 30% of position, reduces exposure
- **Safety Timeout:** If safety_close_time expires without hitting target, force buy-back via SAR signal
- **Fallback Price:** Uses Parabolic SAR to determine safety exit price

### Risk Constraints
- **Position Sizing:** `cur_position_size = min(full_position/avg_price_open, full_position/avg_price_open * (risk_per_trade / (risk/avg_price_open)))`
- **Risk Ratio:** `risk_per_trade` limits maximum capital at risk per trade (e.g., 5%)
- **Risk/Reward Gate:** Handled by `Strategy.validate_trade_risk()` before `open()` is called; Position does not re-check

## 8. Error Handling

### Invalid Open Prices
- **Condition:** price_open array should be descending or equal for shorts (highest first, lowest last)
- **Current Behavior:** Code does not explicitly validate order; relies on strategy logic to provide correct order
- **Risk:** If prices not descending, position sizing calculations may be incorrect
- **Recommendation:** Add validation: `assert all(price_open[i] >= price_open[i+1])`

### Invalid Close Prices
- **Condition:** price_close array should be ascending or equal for shorts (lowest first, highest last)
- **Current Behavior:** Code does not validate; strategy must provide correct order
- **Risk:** If prices not ascending, graduated exit will execute at suboptimal levels
- **Recommendation:** Add validation: `assert all(price_close[i] <= price_close[i+1])`

### Invalid State on open()
- **Condition:** `open()` called when position is not in `POSITION_STATE_WAIT`
- **Handling:** Returns False; position unchanged

### Loan Repayment Failures
- **Current State:** Code does not explicitly handle cases where coinUse.size goes negative
- **Simulated Behavior:** Commented code shows `self.coinUse.loan = -self.coinUse.size` (tracks negative balance)
- **Risk:** Real trading would require margin account; insufficient coins would cause exchange error
- **Recommendation:** Add assertion: `assert self.coinUse.size >= 0 after record_exit_fill()`

### Margin Requirement Violations
- **Current State:** Code does not check margin ratio (loan balance vs. account equity)
- **Risk:** Real short positions can trigger margin calls if account equity falls below exchange threshold
- **Recommendation:** Robot (live only) should verify margin availability before calling `position.open()`

## 9. Existing Approach & Implementation Details

### Graduated Entry & Exit Strategy
The ShortPosition implements a multi-tranche execution strategy:
- **Selling (Opening):** Divides position into len(price_open) tranches
  - Each tranche: `coinUse.action_amount = position_size / len(price_open)`
  - Executes at prices: price_open[0], price_open[1], ..., price_open[n]
  - Expects prices to be descending (sells at highest prices first)

- **Buying Back (Closing):** Divides buy-back into len(price_close) tranches or partial closes
  - Each tranche: `coinGet.action_amount = coinGet.size or 0.3 * coinGet.size`
  - Executes at prices: price_close[0], price_close[1], ..., price_close[n]
  - Expects prices to be ascending (buys at lowest prices first)

### Position State Machine
```
WAIT (initial)
  ↓ [open() called]
WAIT_SAFETY_BUY or WAIT_BUY (after record_entry_fill; depends on use_safety)
  ↓ [close() called with initial profit target]
WAIT_BUY / WAIT_SAFETY_BUY (holding)
  ├─ [safety target hit or timeout]
  └─ [close() called with final target]
WAIT (finalize() calculates P&L)
```

### Fee Application
- **Sale:** Charged when borrowing and selling: `coinGet.size += action_size * price * (1 - fee)`
- **Buy-back:** Charged when repurchasing: `coinUse_change = (action_size / price) * (1 - fee)`
- **Total Cost:** Two fees applied (one on sale, one on buy-back), increasing break-even price

### Direction Helper Functions
- **direction_profit(val):** For shorts, returns -val (profit direction is negative, downward price movement)
- **direction_loss(val):** For shorts, returns val (loss direction is positive, upward price movement)
- **first_in_profit(first, second):** For shorts, returns first ≤ second (lower price is more profitable)

### Safety Exit Mechanism
- **Trigger:** If position remains open after safety_close_time
- **Action:** `safety_update(cur_data, cur_time, ...)` reads `cur_data.get("sar", 15)` for Parabolic SAR value
- **Effect:** Overrides normal close price with SAR, forcing exit at technical support/resistance level
- **Fallback:** Ensures position doesn't hold indefinitely in unprofitable state

## 10. Potential Improvements

1. **Validate Price Array Order**
   - Add assertions in open() to verify price_open is descending and price_close is ascending
   - Prevents silent errors from incorrect strategy signal generation
   - Example: `assert all(price_open[i] >= price_open[i+1] for i in range(len(price_open)-1))`

2. **Trailing Stop-Loss with Safety Buffer**
   - Implement stop-loss that follows price downward as position becomes more profitable
   - Preserve safety margin (e.g., 0.5%) to avoid premature closure from price noise
   - Example: As avg_price_close drops, lower price_stop_loss incrementally

3. **Dynamic Position Sizing Based on Margin Available**
   - Query exchange for available margin before opening position
   - Scale position_size down if margin is tight
   - Prevents margin calls mid-position

4. **Forced Closure on Margin Requirement Breach**
   - Monitor margin ratio during holding phase: `margin_ratio = account_equity / loan_balance`
   - If margin_ratio falls below threshold (e.g., 1.5x), trigger emergency buy-back
   - Example: `if current_margin_ratio < MARGIN_CALL_THRESHOLD: set_action(DO_STOP_LOSS)`

5. **Loan Interest/Borrow Rate Deduction**
   - Incorporate exchange borrow rates into P&L calculation
   - Adjust profitability for cost of holding borrowed asset
   - Example: `adjusted_fee = fee + (borrow_rate * time_held_hours / 24)`

6. **Partial Profit-Taking at Intermediate Targets**
   - Allow multiple partial closes at multiple price targets beyond safety phase
   - Example: Buy back 20% at first target, 20% at second target, 60% at final target
   - Reduces exposure as price moves favorably

7. **Entry Price Momentum Verification**
   - Before opening, verify that price momentum is downward (not just current level)
   - Prevents entry at local lows where downtrend may be exhausted
   - Example: Check that RSI < 30 or price below BB lower band

8. **Sentiment-Based Position Sizing Adjustment**
   - Increase size when market sentiment strongly bearish
   - Decrease size when sentiment weakly bearish or uncertain
   - Example: `cur_position_size *= sentiment_confidence_factor`

9. **Graduated Buy-Back Intensity**
   - Adjust intensity of buy-back (speed of tranche execution) based on price movement
   - Buy faster if price rising (reduce risk) or slower if price falling favorably (maximize profit)

10. **Correlation-Based Risk Hedging**
    - Identify correlated assets; reduce position size if correlated assets strengthening
    - Example: If shorting altcoin, reduce size if Bitcoin trending up (usually drives altcoin up)
    - Adds defensive positioning for systemic risk scenarios
