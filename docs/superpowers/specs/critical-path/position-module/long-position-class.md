# LongPosition Class Specification

## Class Overview

The `LongPosition` class implements the complete lifecycle of a long trade (buy and then sell) in the pybtctr2 trading bot framework. It extends `BasePosition` with specific logic for opening long positions (buying an asset at one or more ascending price levels), holding the position while monitoring stop-loss conditions, and closing the position (selling at one or more descending price levels).

The class manages all aspects of a long trade including position sizing based on risk-reward ratios, graduated entry/exit execution, stop-loss tracking, and P&L calculation. It serves as the concrete implementation for going "long" (profiting from price increases), contrasting with `ShortPosition` for short selling.

A key role of `LongPosition` is to bridge strategy decisions with execution realities: when a strategy signals a long entry, `LongPosition` calculates position size, tracks the execution state (buy tranches, hold, sell tranches), and computes realized profit or loss based on actual execution prices and fees.

## Key Attributes

| Attribute | Type | Inherited | Description |
|-----------|------|-----------|-------------|
| `position_type` | int | No | Set to `POSITION_TYPE_LONG` (1); identifies this as a long position |
| `price_open` | list[float] | Yes | List of target buy prices (ascending or equal), representing graduated entry levels |
| `price_close` | list[float] | Yes | List of target sell prices (descending or equal), representing graduated exit levels |
| `price_stop_loss` | float | Yes | Hard stop-loss price; position closes immediately if price touches this level |
| `executed_open` | list[float] | Yes | Actual buy prices achieved during execution, tracked in order |
| `executed_open_amount` | list[float] | Yes | Amounts (in base coin USD) used for each buy, corresponding to `executed_open` |
| `executed_close` | list[float] | Yes | Actual sell prices achieved during execution, tracked in order |
| `executed_close_amount` | list[float] | Yes | Amounts (in asset coin) sold at each close price, corresponding to `executed_close` |
| `coinUse` | Coin | Yes | Coin tracker for the base asset (USD); tracks available capital, spent amount, and returned amount |
| `coinGet` | Coin | Yes | Coin tracker for the target asset (e.g., BTC); tracks acquired amount, used amount, and available to sell |
| `state` | int | Yes | Current position state (WAIT, WAIT_SELL, WAIT_SAFETY_SELL, etc.); determines allowed actions |
| `action` | int | Yes | Current position action (OPEN_LONG, CLOSE_LONG, DO_STOP_LOSS, etc.); signals what operation is active |
| `open_time` | int | Yes | Unix timestamp (milliseconds) when position was opened; used for timeout checks |
| `safety_close_time` | int | Yes | Unix timestamp (milliseconds) when safety close window expires; triggers forced exit |
| `fee` | float | Yes | Taker fee from `stock.item.fee` — injected by caller; never hardcoded; applied to all fills |
| `risk_per_trade` | float | Yes | Risk tolerance percentage (0.05 = 5% of capital); used to calculate position size |
| `full_position` | float | Yes | Maximum position size allowed (in USD); limits total capital exposed per trade |

## Constructor

```python
def __init__(self, coin_use: str, coin_get: str, full_position, thread_num, fee, use_safety: bool = True):
    super(LongPosition, self).__init__(coin_use, coin_get, full_position, thread_num, fee, use_safety)
    self.position_type = POSITION_TYPE_LONG
```

**Parameters:**
- `coin_use` (str): Base currency symbol being spent (e.g., "usdt")
- `coin_get` (str): Target currency symbol being acquired (e.g., "btc")
- `full_position` (float): Maximum capital to risk on this trade (USD), typically 10000 or less
- `thread_num` (int): Worker thread identifier for logging and parallelization
- `fee` (float): Taker fee from `stock.item.fee` — passed in by caller; never a default constant
- `use_safety` (bool): If `True` (default), entry fill transitions to `WAIT_SAFETY_SELL` for safety management; if `False`, stays in `WAIT_SELL` and skips safety phase

**Initialization Flow:**
1. Calls parent `BasePosition.__init__()` with coin names, full_position, thread_num, fee, use_safety
2. Sets `position_type = POSITION_TYPE_LONG` to identify this as a long position

## Key Methods & Interfaces

### open(price_open, price_close, price_stop_loss, time_period, action_msg)

Opens a long position and computes position size. Prices are passed in already validated by Strategy (risk/reward checked via `validate_trade_risk()` before `open()` is called).

**Parameters:**
- `price_open` (list[float]): Target buy prices in ascending order (e.g., [10, 11, 12] to buy in 3 tranches)
- `price_close` (list[float]): Target sell prices in descending order (e.g., [15, 14, 13])
- `price_stop_loss` (float): Hard stop-loss price; position exits if price drops to this level
- `time_period` (int): Candle duration; used for state tracking
- `action_msg` (ActionMessage): Message object to communicate actions back to strategy

**Returns:** bool
- `True` if position opened successfully
- `False` if state precondition not met (not in WAIT state)

**Logic:**
1. Calculates `avg_price_open` as the mean of all target buy prices
3. Computes `risk = avg_price_open * (1 + 2 * fee) - price_stop_loss` (distance to stop in USD/coin)
4. Calculates position size: `cur_position_size = min(full_position, full_position * risk_per_trade / (risk / avg_price_open))`
5. Calls `extend()` to allocate capital
6. Stores target prices, stop-loss, and timing
7. Sets `action = STRATEGY_ACTION_OPEN_LONG`
8. Sets `coinUse.action_amount = want_to_use / len(price_open)` (amount per buy tranche)

### close(price_close, price_stop_loss, time_period, action_msg)

Prepares the position for closure. Called when exit conditions are met.

**Parameters:**
- `price_close` (list[float]): Target sell prices
- `price_stop_loss` (float): Updated stop-loss level
- `time_period` (int): Current candle duration
- `action_msg` (ActionMessage): Message object

**Returns:** bool
- `True` if close was prepared successfully
- `False` if position was not in a closeable state

**Logic:**
1. Checks if position is in a wait-close state (WAIT_SELL or WAIT_SAFETY_SELL)
2. Updates the first sell price via `update_price_close(price_close[0])`
3. If in WAIT_SAFETY_SELL:
   - Sets a tighter stop-loss for partial close protection
   - Sets `action = STRATEGY_ACTION_CLOSE_LONG_PART`
   - Sets `coinGet.action_amount = 0.3 * coinGet.size` (close 30% of position)
4. If in normal WAIT_SELL:
   - Updates stop-loss to new level
   - Sets `action = STRATEGY_ACTION_CLOSE_LONG`
   - Sets `coinGet.action_amount = coinGet.size` (close full position)

### record_entry_fill(coin_amount, price)

Records the execution of a long entry (buy) fill. Called by `Position.process_action()` when an entry fill is confirmed.

**Parameters:**
- `coin_amount` (float): Number of coins acquired in this fill
- `price` (float): Actual buy price (USD/coin)

**Logic:**
1. Checks if action is STRATEGY_ACTION_OPEN_LONG
2. Constrains the fill to available capital:
   - `capped = min(coinUse.size / price, coin_amount)` (can't spend more USD than available)
3. Records the execution:
   - Appends `price` to `executed_open`
   - Appends `capped` to `executed_open_amount`
4. Updates coin tracking:
   - Deducts `capped * price` from `coinUse.size` (USD spent)
   - Increments `coinUse.used`
   - Increments `coinGet.size` by `capped * (1 - fee)` (coins acquired net of fee)
5. Transitions state: if `use_safety=True` → `POSITION_STATE_WAIT_SAFETY_SELL`; if `use_safety=False` → remains `POSITION_STATE_WAIT_SELL` (exit-awaiting, safety phase skipped)

### record_exit_fill(coin_amount, price)

Records the execution of a long exit (sell) fill. Called by `Position.process_action()` when an exit fill is confirmed.

**Parameters:**
- `coin_amount` (float): Number of coins sold in this fill
- `price` (float): Actual sell price (USD/coin)

**Logic:**
1. Checks if action is STRATEGY_ACTION_CLOSE_LONG, CLOSE_LONG_PART, or DO_STOP_LOSS
2. Constrains the fill:
   - `capped = min(coinGet.size, coin_amount)`
3. Records the execution:
   - Appends `price` to `executed_close`
   - Appends `capped` to `executed_close_amount`
4. Updates coin tracking:
   - Deducts `capped` from `coinGet.size`
   - Increments `coinUse.size` by `capped * price * (1 - fee)` (USD returned net of fee)
   - Increments `coinUse.returned`
5. If in WAIT_SAFETY_SELL state, transitions to WAIT_SELL

### get_action_amount_in_coins(price)

Returns the order size in coin units for the current pending action.

**Parameters:**
- `price` (float): Current USD/coin price

**Logic:**
- If `is_wait_open_state()`: return `coinUse.action_amount / price` (convert USD allocation to coins)
- Else: return `coinGet.action_amount` (already in coins for sell)

### avg_price_open()

Calculates the volume-weighted average buy price across all executed buys.

**Returns:** float - Average buy price

**Calculation:**
```
total_spent = sum(executed_open_amount)
total_tokens = sum(executed_open_amount[i] / executed_open[i] for i in range(len(executed_open)))
avg_price_open = total_spent / total_tokens
```

**Example:**
- Buy 100 USD at 10 USD/coin → 10 coins
- Buy 100 USD at 11 USD/coin → 9.09 coins
- Total: 200 USD spent, 19.09 coins → avg = 200 / 19.09 = 10.48 USD/coin

### avg_price_close()

Calculates the volume-weighted average sell price across all executed sells.

**Returns:** float - Average sell price

**Calculation:**
```
total_returned = sum(executed_close[i] * executed_close_amount[i] for i in range(len(executed_close)))
total_tokens_sold = sum(executed_close_amount)
avg_price_close = total_returned / total_tokens_sold
```

**Example:**
- Sell 10 coins at 15 USD/coin → 150 USD
- Sell 9 coins at 14 USD/coin → 126 USD
- Total: 19 coins sold, 276 USD returned → avg = 276 / 19 = 14.53 USD/coin

### is_wait_open_state()

Checks if the position is waiting to open (i.e., executing buy orders).

**Returns:** bool - `True` if `action == STRATEGY_ACTION_OPEN_LONG`

### is_wait_close_state()

Checks if the position is waiting to close (i.e., executing sell orders).

**Returns:** bool - `True` if `state == POSITION_STATE_WAIT_SELL or state == POSITION_STATE_WAIT_SAFETY_SELL`

### get_trade_type()

Returns the type of trade operation currently active.

**Returns:** int constant
- `TRADE_BUY` if action is `STRATEGY_ACTION_OPEN_LONG`
- `TRADE_SELL` if action is `STRATEGY_ACTION_CLOSE_LONG`, `CLOSE_LONG_PART`, or `DO_STOP_LOSS`
- `STRATEGY_ACTION_NOTHING` if action is unknown

### check_target(action_msg)

Checks if the safety close target (first sell price) has been hit. Called during WAIT_SAFETY_SELL state.

**Returns:** bool - `True` if target price reached

**Logic:**
1. Returns `False` if in WAIT_SELL state (no target check)
2. If in WAIT_SAFETY_SELL:
   - Creates a default target if `price_close` is empty: `price_close[0] = avg_price_open * (1 + direction_profit(0.008))`
   - Retrieves the current candle's high price
   - Returns `True` if `price_close[0] <= current_high`

### safety_update(strategy_action, action_msg)

Monitors safety conditions and adjusts stop-loss dynamically during WAIT_SAFETY_SELL.

**Returns:** int - Updated strategy action

**Logic:**
1. If in WAIT_SAFETY_SELL:
   - Calls `check_target()` to see if safety target is hit
   - If target hit and no new strategy action: sets action to `STRATEGY_ACTION_CLOSE_LONG_PART`
   - Checks if safety close time has expired (via `safety_close_time` timestamp)
   - If expired and price below `zero_price()`: tightens stop-loss to Bollinger Band lower (BBD)
2. Returns the (possibly updated) strategy_action

### best_executed_open()

Returns the best (lowest) executed buy price achieved so far.

**Returns:** float - `min(executed_open)`

### best_executed_close()

Returns the best (highest) executed sell price achieved so far.

**Returns:** float - `max(executed_close)`

**Note:** There appears to be a bug in the source code; this method returns `max(executed_open)` instead of `max(executed_close)`. This should return the highest sell price for a long position.

### set_close_state()

Transitions the position state to WAIT_SELL.

### set_close_action()

Sets the action to STRATEGY_ACTION_CLOSE_LONG.

### get_safety_state()

Returns the safety state for long positions.

**Returns:** `POSITION_STATE_WAIT_SAFETY_SELL` (5)

### get_close_state()

Returns the close state for long positions.

**Returns:** `POSITION_STATE_WAIT_SELL` (2)

### get_open_action()

Returns the open action for long positions.

**Returns:** `STRATEGY_ACTION_OPEN_LONG` (1)

### get_close_action()

Returns the close action for long positions.

**Returns:** `STRATEGY_ACTION_CLOSE_LONG` (3)

### max_profit_price()

Returns the maximum (highest) price in the current candle.

**Returns:** float - Current candle's high price

### max_loss_price()

Returns the minimum (lowest) price in the current candle.

**Returns:** float - Current candle's low price

### check_new_action(new_action)

Validates that a new action is appropriate for a long position.

**Logic:**
- Asserts that the action is NOT a short action (OPEN_SHORT, CLOSE_SHORT, CLOSE_SHORT_PART)
- Returns `True` if validation passes
- Raises an assertion error if a short action is attempted on a long position

## Trade Lifecycle

### 1. OPENING Phase (state: varies, action: STRATEGY_ACTION_OPEN_LONG)

**Entry Conditions (all checked by Strategy before `open()` is called):**
- Strategy signals a buy with favorable risk/reward (`validate_trade_risk()` passed)
- Minimum capital available

**Process:**
1. Strategy calls `position.open(price_open=[10, 11, 12], price_close=[15, 14], price_stop_loss=9)`
2. LongPosition calculates position size using `risk_per_trade` (risk/reward already validated by Strategy)
3. `state = WAIT_SELL`, `action = STRATEGY_ACTION_OPEN_LONG`
4. Execution system calls `record_entry_fill()` for each tranche:
   - Fill tranche 1: 10 coins at 10 → `coinGet.size += 10 * (1-fee)`
   - Fill tranche 2: ~9.09 coins at 11 → `coinGet.size += 9.09 * (1-fee)`
   - After each fill: if `use_safety=True` → `state = WAIT_SAFETY_SELL`; if `use_safety=False` → stays `WAIT_SELL`
5. Position is now "long": owns coins and is holding them

### 2. HOLDING Phase (state: POSITION_STATE_WAIT_SELL or WAIT_SAFETY_SELL, action: varies)

**During this phase:**
- `coinUse` tracks capital spent and returned
- `coinGet` tracks coins acquired and available to sell
- Stop-loss is monitored continuously; if price touches `price_stop_loss`, immediate sell triggered
- Safety timeout: if position remains open past `safety_close_time`, forced close with tighter margins
- Safety targets: if in WAIT_SAFETY_SELL and first sell price reached, partial close initiated

**Price Monitoring:**
- Current price compared against `price_stop_loss` (hard floor)
- Current price compared against next unexecuted `price_close[i]` target
- Current candle high/low tracked via `max_profit_price()` and `max_loss_price()`

### 3. CLOSING Phase (state: POSITION_STATE_WAIT_SELL, action: STRATEGY_ACTION_CLOSE_LONG or CLOSE_LONG_PART)

**Exit Triggers:**
1. **Target Hit:** Price reaches or exceeds first (best) target sell price
2. **Stop-Loss Hit:** Price falls to `price_stop_loss` level
3. **Safety Timeout:** `safety_close_time` expired; forced close at safety price
4. **Partial Exit:** In WAIT_SAFETY_SELL, close 30% at favorable price first

**Process:**
1. Strategy or safety system calls `position.close(price_close=[15, 14], price_stop_loss=...)`
2. LongPosition updates sell targets and transitions state
3. Execution system calls `record_exit_fill()` for each tranche:
   - Exit tranche 1: 10 coins at 15 → returns 150 USD net of fee
   - Exit tranche 2: 9.09 coins at 14 → returns 127.26 USD net of fee
4. Position is now closed; coins are converted back to capital

### 4. FINALIZE Phase

Inherited from `BasePosition.finalize()`, calculates:
- **Revenue %:** `(avg_price_close / avg_price_open - 1 - 2 * fee) * 100`
- **Revenue Absolute:** `coinUse.returned - coinUse.used`

**Example:**
- Spent 200 USD, got 19.09 coins, avg buy = 10.48
- Returned 277.26 USD, sold 19.09 coins, avg sell = 14.53
- Fee = 0.1% (0.001)
- Revenue % = (14.53 / 10.48 - 1 - 0.002) * 100 = 37.35%
- Revenue Abs = 277.26 - 200 = 77.26 USD

## P&L Calculation

### Formula for Long Positions

```
profit_percent = ((avg_close_price / avg_open_price) - 1 - 2 * fee) * 100
profit_absolute = (avg_close_price * total_coins_sold - total_usd_spent) * (1 - fee)
```

**Components:**
- `avg_open_price`: Volume-weighted average of all buy prices
- `avg_close_price`: Volume-weighted average of all sell prices
- `fee`: Broker fee (applied on both entry and exit, hence 2 * fee deduction)
- `total_coins_sold`: Sum of all `executed_close_amount`
- `total_usd_spent`: Sum of all `executed_open_amount`

**Example Scenarios:**

1. **Profitable Trade:**
   - Buy 1 BTC at $30,000 (spend $30,000)
   - Sell 1 BTC at $33,000 (return $33,000)
   - Fee: 0.1% each direction
   - Profit % = (33,000 / 30,000 - 1 - 0.002) * 100 = 9.8%
   - Profit $ = $33,000 - $30,000 - 0.1% entry - 0.1% exit ≈ $2,940

2. **Loss Trade:**
   - Buy 1 BTC at $30,000
   - Sell 1 BTC at $29,000 (stop-loss hit)
   - Profit % = (29,000 / 30,000 - 1 - 0.002) * 100 = -3.67%
   - Profit $ = $29,000 - $30,000 - $60 fees ≈ -$1,060

### Stop-Loss Effect

A stop-loss at `price_stop_loss = $29,000` means:
- If current price drops to $29,000, position is immediately closed
- All remaining coins are sold at (approximately) $29,000
- This acts as a maximum loss limit

## Error Handling

### Invalid Price Sequences

**Open prices must be ascending or equal:**
- Valid: `[10, 10, 11, 12]`, `[10, 11, 12]`
- Invalid: `[10, 9, 11]` (9 < 10; violates graduation)
- **Consequence:** Position sizes calculated incorrectly; later tranches buy above earlier ones

**Close prices must be descending or equal:**
- Valid: `[15, 14, 14, 13]`, `[15, 14, 13]`
- Invalid: `[15, 16, 13]` (16 > 15; violates graduation)
- **Consequence:** Position sized incorrectly; may hit lower target before higher one

### Insufficient Capital

**Trigger:** `coinUse.want_to_use > coinUse.size`

**Current Handling:** In `validate_position_size()`:
```python
if self.coinUse.want_to_use > self.coinUse.size:
    self.coinUse.want_to_use = self.coinUse.size
    log("Cut LONG position size to available funds")
```

**Consequence:** Position size reduced but trade still proceeds (no hard failure)

### Execution Mismatches

**Scenario:** `record_entry_fill()` called with price that doesn't match any target in `price_open`

**Current Handling:** No validation; price recorded as-is in `executed_open`

**Issue:** Could lead to incorrect state transitions or missed targets if prices drift significantly

## Existing Approach

### Graduated Entry (Dollar-Cost Averaging)

The `LongPosition` class implements DCA-style entry:
- Multiple buy tranches at ascending prices
- Each tranche uses `full_position * risk_per_trade / (risk / avg_open_price) / len(price_open)` capital
- Reduces impact of buying at a single price
- Spreads risk across multiple price levels

**Example:**
```python
price_open = [10, 11, 12]  # 3 tranches
amount_per_buy = cur_position_size / 3
# Buy 1/3 at 10
# Buy 1/3 at 11
# Buy 1/3 at 12
```

### Graduated Exit (Partial Position Taking)

Exit is similarly graduated:
- Sell tranches at descending prices
- First sell at best price (15), then 14, then 13
- Takes profits in multiple batches
- Reduces slippage from selling entire position at once

### Stop-Loss is a Hard Floor

Once set via `set_stop_loss()`, the `price_stop_loss` is a hard minimum:
- Any price touch or break below triggers immediate sell
- Prevents catastrophic losses
- Checked during position lifecycle via price monitoring in execution layer

### P&L is Percentage-Based

Revenue calculated as percentage of entry capital:
- `(close_price - open_price - fees) / open_price * 100`
- Allows comparison across different position sizes
- Independent of absolute capital deployed

### Fee Handling

Fees are applied:
1. **On entry:** Reduces coins acquired: `(amount / price) * (1 - fee)`
2. **On exit:** Reduces capital returned: `(coins * price) * (1 - fee)`
3. **On P&L:** Deducted as `2 * fee` (entry + exit)

`fee` is injected via constructor from `stock.item.fee` (live) or its equivalent config value (simulation). Never hardcoded or defaulted anywhere in this class.

## Potential Improvements

1. **Partial Position Taking at Intermediate Targets**
   - Currently: Full position holds until first close price
   - Enhancement: Close 20% at first target, 30% at second, 50% at third
   - Benefit: Locks in profits incrementally; reduces risk on remaining position

2. **Trailing Stop-Loss**
   - Currently: Fixed stop-loss set at open time
   - Enhancement: Move stop-loss up automatically as price increases (e.g., 5% below high)
   - Benefit: Protects profits while allowing upside; reduces maximum loss

3. **Time-Weighted Position Sizing**
   - Currently: Equal tranches (1/n capital per buy, n=number of levels)
   - Enhancement: Earlier tranches smaller (reduce entry noise), later tranches larger (average down)
   - Benefit: Better capital efficiency; reduces average entry price

4. **Break-Even Stop Management**
   - Currently: Hard stop-loss only
   - Enhancement: Move stop-loss to break-even once 1st target hit
   - Benefit: Zero-loss exit after partial profit; removes downside after committing capital

5. **Volatility-Adjusted Position Sizing**
   - Currently: Fixed `risk_per_trade` percentage
   - Enhancement: Reduce position size in high volatility (ATR > threshold), increase in low volatility
   - Benefit: Adjusts risk dynamically; avoids overleveraging in choppy markets

6. **Explicit Error Handling**
   - Currently: Errors logged but not raised
   - Enhancement: Raise exceptions for invalid prices, insufficient capital, negative risk
   - Benefit: Prevents silent failures; forces explicit handling in calling code

7. **State Machine Validation**
   - Currently: State transitions checked implicitly
   - Enhancement: Add `_validate_state_transition()` to prevent invalid state combos
   - Benefit: Reduces bugs from unexpected state sequences

8. **Dynamic Stop-Loss Based on Bollinger Bands**
   - Currently: Fixed stop-loss or manual adjustment
   - Enhancement: Initialize stop-loss at lower Bollinger Band; adjust as bands move
   - Benefit: Data-driven stops; adapts to volatility changes

9. **Batch Execution Optimization**
   - Currently: Sequential `record_entry_fill()` calls
   - Enhancement: Batch multiple buys and apply slippage model
   - Benefit: More realistic simulation; accounts for market impact

10. **Profit Target Management**
    - Currently: All targets set at open time
    - Enhancement: Dynamically adjust targets based on realized momentum or volatility
    - Benefit: Captures larger moves in trending markets; reduces leaving money on table
