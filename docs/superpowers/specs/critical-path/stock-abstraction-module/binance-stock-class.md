# BinanceStock Class Specification

**Location:** `stocks/binance_stock.py`

**Class Name:** `Stock_Binance`

---

## 1. Class Overview

The `Stock_Binance` class is a concrete Binance exchange adapter that implements the `StockInterface` base class. It provides a complete REST API integration layer with the Binance cryptocurrency exchange, enabling the pybtctr2 system to fetch market data, execute trades, and manage positions in real-time or during backtesting.

The class encapsulates all Binance-specific communication logic, including API authentication, weight-based rate limiting, order execution (limit orders on margin accounts), candle data fetching with multi-timeframe resampling, and account information retrieval. It handles both standard and margin account operations, with sophisticated error recovery mechanisms including automatic retries and circuit breaker patterns.

Key architectural responsibility: Bridge between the pybtctr2 trading logic (signals, strategy, robot) and the Binance REST API, abstracting away exchange-specific details while exposing a consistent interface for candle data, depth information, order management, and account state.

---

## 2. Key Attributes

| Attribute | Type | Source | Purpose |
|-----------|------|--------|---------|
| `stock_name` | str | StockInterface | Exchange identifier; set to "binance" |
| `key` | str | StockInterface | Binance API key (stored but not directly used; stored as empty string) |
| `secret` | str | StockInterface | Binance API secret (stored but not directly used; stored as empty string) |
| `coin_base` | str | StockInterface | Quote currency; default "USDT" (e.g., LINKUSDT pairs use USDT as base) |
| `coin` | str | StockInterface | Trading coin/asset symbol (e.g., "LINK", "BTC"); empty by default |
| `instance` | BinanceClient | Stock_Binance | Binance python-binance SDK client; initialized with API credentials |
| `fee` | float | Stock_Binance | Trading fee percentage; set to 0.001 (0.1%) |
| `weight` | int | StockInterface | Current API weight consumed in rate limit window; accumulated across API calls |
| `weight_set_time` | float | StockInterface | Unix timestamp when weight counter was last reset; used for tracking rate limit window |
| `overflow_weight` | int | Stock_Binance | Threshold weight limit; set to 5000 (Binance standard) |
| `overflow_weight_time` | int | Stock_Binance | Rate limit window duration in seconds; set to 60 (1 minute) |

---

## 3. Constructor (`__init__`)

```python
def __init__(self):
```

**Initialization Flow:**

1. Calls parent `StockInterface.__init__("binance", "", "")` to initialize base attributes
2. Retrieves Binance API credentials from environment variables:
   - `BINANCE_API_KEY` → passed to BinanceClient
   - `BINANCE_API_SECRET` → passed to BinanceClient
3. Creates authenticated `BinanceClient` instance using credentials
4. Sets trading parameters:
   - `key = ""` (empty, credentials in client instance instead)
   - `secret = ""` (empty, credentials in client instance instead)
   - `url = ""` (not used; Binance client handles URLs internally)
5. Configures rate limiting:
   - `fee = 0.001` (0.1% trading fee)
   - `overflow_weight = 5000` (Binance weight limit per minute)
   - `overflow_weight_time = 60` (reset window in seconds)

**Preconditions:**
- `BINANCE_API_KEY` environment variable must be set
- `BINANCE_API_SECRET` environment variable must be set
- Valid Binance API credentials with appropriate permissions (spot trading, margin trading, account data)

**Postconditions:**
- `self.instance` is an authenticated BinanceClient ready to execute API calls
- Weight tracking initialized (weight=0, weight_set_time=0)
- Instance is ready for `get_candles_history()`, `trade()`, `depth()`, and account queries

---

## 4. Key Methods & Interfaces

### 4.1 `get_pair_name()` → str

**Purpose:** Format trading pair symbol for Binance API

**Parameters:** None

**Returns:**
- **str:** Uppercase pair string; concatenates `self.coin` + `self.coin_base` (e.g., "LINKUSDT")

**Binance-Specific Behavior:**
- Binance requires uppercase pair symbols (e.g., "LINKUSDT", not "linkusdt")
- Pair format is `{COIN}{BASE}` (e.g., LINK + USDT = LINKUSDT)

**Example:**
```python
# If self.coin="link", self.coin_base="usdt"
pair = stock.get_pair_name()  # Returns "LINKUSDT"
```

---

### 4.2 `get_candles_history(time_list, coin, time_point=0)` → dict[int, DataFrame]

**Purpose:** Fetch historical OHLC candles from Binance and resample to multiple timeframes

**Parameters:**
- `time_list` – **list[int]**: Requested timeframe periods in minutes (ignored; uses hardcoded timeframes)
- `coin` – **str**: Trading coin symbol (not directly used; pulled from self.coin)
- `time_point` – **int**: Optional; unused in current implementation

**Returns:**
- **dict[int, DataFrame]**: Dictionary mapping timeframe (in minutes) to OHLC DataFrame
  - Keys: 1, 5, 15, 60, 240, 1440 (minutes)
  - Each DataFrame has columns: open, high, low, close, volume, close_time, qav, num_trades, taker_base_vol, taker_quote_vol, ignore
  - Index: DatetimeIndex (converted from open_time milliseconds)
  - Size: Last 120 candles per timeframe

**Binance-Specific Behavior:**

1. **Multi-Stage Fetching:** Makes 4 separate REST API calls for different timeframe bases:
   - 1-minute klines: lookback "10 hours ago UTC" → weight += 2
   - 15-minute klines: lookback "4 days ago UTC" → weight += 2
   - 1-hour klines: lookback "43 days ago UTC" → weight += 2
   - 12-hour klines: lookback "121 days ago UTC" → weight += 2
   - **Total weight cost:** 8 per call to `get_candles_history()`

2. **Resampling Strategy:** Intelligently resamples fetched data to avoid excessive API calls:
   - Timeframes 1-14 min: resample from 1-minute data
   - Timeframes 15-59 min: resample from 15-minute data
   - Timeframes 60-719 min (< 12 hours): resample from 1-hour data
   - Timeframes >= 720 min (>= 12 hours): resample from 12-hour data

3. **OHLC Aggregation:** Uses pandas `.resample().agg()` with:
   - open: 'first' (opening price of period)
   - high: 'max' (highest price in period)
   - low: 'min' (lowest price in period)
   - close: 'last' (closing price of period)
   - volume: 'sum' (aggregate volume)

4. **Candle Limit:** Each timeframe returns last 120 candles (`.iloc[-120:]`)

**Error Handling:**
- Catches `BinanceRequestException` (network errors) → logs error, continues
- Catches `BinanceAPIException` (invalid requests) → logs status code and message, continues
- No retry logic; returns incomplete data if exception occurs

**Example:**
```python
ohlc = stock.get_candles_history([], "link")
# Returns {
#   1:    DataFrame(120 rows, 12 columns),  # 1-minute candles
#   5:    DataFrame(120 rows, 12 columns),  # 5-minute (resampled from 1-min)
#   15:   DataFrame(120 rows, 12 columns),  # 15-minute candles
#   60:   DataFrame(120 rows, 12 columns),  # 1-hour (resampled from 1-hour data)
#   240:  DataFrame(120 rows, 12 columns),  # 4-hour (resampled from 1-hour data)
#   1440: DataFrame(120 rows, 12 columns),  # 1-day (resampled from 12-hour data)
# }
```

---

### 4.3 `depth(qnt)` → (DataFrame, DataFrame)

**Purpose:** Fetch order book (bid/ask depth) from Binance

**Parameters:**
- `qnt` – **int**: Number of bid/ask levels to retrieve (typically 20, 100, 500, 1000, 5000)

**Returns:**
- **tuple(DataFrame, DataFrame):** `(asksDF, bidsDF)`
  - Each DataFrame has columns: `["price", "qnt", "sum"]`
  - `price`: Price level (float)
  - `qnt`: Quantity available at this level (float)
  - `sum`: Cumulative quantity up to this level (float)
  - Index: numeric (0, 1, 2, ...)

**Binance-Specific Behavior:**

1. **Weight Scaling:** API call weight depends on requested depth levels:
   - qnt < 100: weight += 5
   - qnt < 500: weight += 25
   - qnt < 1000: weight += 50
   - qnt < 5000: weight += 250

2. **Depth Format:** Binance returns `{"bids": [[price, qty], ...], "asks": [[price, qty], ...]}`

3. **Cumulative Sum:** Adds "sum" column with cumulative quantity for visualization/analysis

**Error Handling:**
- Catches `BinanceRequestException` → logs error, returns empty DataFrames
- Catches `BinanceAPIException` → logs status code and message, returns empty DataFrames
- No retry logic

**Example:**
```python
asks, bids = stock.depth(20)
# asks["price"]    = [31.0, 31.1, 31.2, ...]
# asks["qnt"]      = [10.5, 20.0, 15.3, ...]
# asks["sum"]      = [10.5, 30.5, 45.8, ...]  # Cumulative
```

---

### 4.4 `trade(type, price, amount, force=False)` → (int, dict)

**Purpose:** Place a limit order on Binance (margin account)

**Parameters:**
- `type` – **int**: Trade direction; use `TRADE_BUY` or `TRADE_SELL` (from helpers)
- `price` – **float**: Limit price for the order
- `amount` – **float**: Quantity to trade (in base units; e.g., number of LINK coins)
- `force` – **bool**: Optional; currently unused (commented out in code)

**Returns:**
- **tuple(int, dict):** `(status, response)`
  - `status` – **int**: `STATUS_SUCCESS` if orderId != 0, else `STATUS_FAIL`
  - `response` – **dict**: Binance order response with key `"orderId"`

**Binance-Specific Behavior:**

1. **Order Type:** Always uses margin account with:
   - Order type: `BinanceClient.ORDER_TYPE_LIMIT` (limit orders only)
   - Time-in-force: `BinanceClient.TIME_IN_FORCE_GTC` (Good Till Cancel)
   - Margin account: `create_margin_order()` (not `order_limit_buy()`)

2. **Price Precision:** Rounds price to 2 decimal places: `float("{0:.2f}".format(price))`

3. **Quantity Precision:** Rounds and reduces amount by 0.01:
   - `float("{0:.2f}".format(amount - 0.01))`
   - Note: Reducing by 0.01 is a hack to account for fees; may cause issues on position close

4. **Weight Cost:** weight += 6 per order

5. **Buy Order:** `create_margin_order(side=SIDE_BUY, type=ORDER_TYPE_LIMIT, ...)`

6. **Sell Order:** `create_margin_order(side=SIDE_SELL, type=ORDER_TYPE_LIMIT, ...)`

**Error Handling:**
- Catches `BinanceRequestException` → logs error, returns (STATUS_FAIL, {})
- Catches `BinanceAPIException` → logs status code/message and traceback, returns (STATUS_FAIL, {})
- No automatic retry

**Example:**
```python
status, res = stock.trade(TRADE_BUY, price=31.50, amount=10.5)
if status == STATUS_SUCCESS:
    order_id = res["order_id"]  # = response["orderId"]
```

---

### 4.5 `cancel_order(order_id)` → (int, dict)

**Purpose:** Cancel an open limit order

**Parameters:**
- `order_id` – **int**: Binance order ID (from `trade()` response)

**Returns:**
- **tuple(int, dict):** `(status, response)`
  - `status` – **int**: `STATUS_SUCCESS` if order reached `ORDER_STATUS_CANCELED` or `ORDER_STATUS_PENDING_CANCEL`, else `STATUS_FAIL`
  - `response` – **dict**: Binance cancel response

**Binance-Specific Behavior:**

1. **Margin Account:** Uses `cancel_margin_order()` (not `cancel_order()`)

2. **Weight Cost:** weight += 10 per cancel request

3. **Status Handling:**
   - Immediate cancel: `ORDER_STATUS_CANCELED` → status = STATUS_SUCCESS
   - Pending cancel: `ORDER_STATUS_PENDING_CANCEL` → polls for up to 10 iterations (2-second intervals)
     - Each poll calls `order_info()` (10 weight per poll)
     - Breaks on `ORDER_STATUS_CANCELED`
     - Success if canceled within 20 seconds

**Error Handling:**
- Catches `BinanceRequestException` → logs error, returns (STATUS_FAIL, {})
- Catches `BinanceAPIException` → logs status code/message, returns (STATUS_FAIL, {})

**Example:**
```python
status, response = stock.cancel_order(12345)
if status == STATUS_SUCCESS:
    print("Order canceled successfully")
```

---

### 4.6 `order_info(order_id)` → (int, dict)

**Purpose:** Fetch status and details of a specific order

**Parameters:**
- `order_id` – **int**: Binance order ID

**Returns:**
- **tuple(int, dict):** `(status, order_info_dict)`
  - `status` – **int**: `STATUS_SUCCESS` if order found, `STATUS_FAIL` otherwise
  - `order_info_dict` – **dict**: Contains keys:
    - `"status"`: Normalized status constant (ORDER_STATUS_NEW, ORDER_STATUS_FILLED, etc.)
    - `"start_amount"`: Original order quantity (float)
    - `"left_amount"`: Remaining unfilled quantity = origQty - executedQty (float)
    - `"rate"`: Limit price (float)

**Binance-Specific Behavior:**

1. **Margin Account:** Uses `get_margin_order()` (not `get_order()`)

2. **Weight Cost:** weight += 10 per query

3. **Status Mapping:** Converts Binance order status constants to internal constants:
   - `ORDER_STATUS_NEW` ← BinanceClient.ORDER_STATUS_NEW
   - `ORDER_STATUS_PARTIALLY_FILLED` ← BinanceClient.ORDER_STATUS_PARTIALLY_FILLED
   - `ORDER_STATUS_FILLED` ← BinanceClient.ORDER_STATUS_FILLED
   - `ORDER_STATUS_CANCELED` ← BinanceClient.ORDER_STATUS_CANCELED
   - `ORDER_STATUS_PENDING_CANCEL` ← BinanceClient.ORDER_STATUS_PENDING_CANCEL
   - `ORDER_STATUS_REJECTED` ← BinanceClient.ORDER_STATUS_REJECTED
   - `ORDER_STATUS_EXPIRED` ← BinanceClient.ORDER_STATUS_EXPIRED

**Error Handling:**
- Catches `BinanceRequestException` → logs error, returns (STATUS_FAIL, {})
- Catches `BinanceAPIException` → logs status code/message, returns (STATUS_FAIL, {})

**Example:**
```python
status, info = stock.order_info(12345)
if status == STATUS_SUCCESS:
    print(f"Order status: {info['status']}")
    print(f"Remaining: {info['left_amount']} units at {info['rate']}")
```

---

### 4.7 `info()` → dict

**Purpose:** Fetch general account status from Binance

**Parameters:** None

**Returns:**
- **dict**: Raw Binance account status response (structure varies; typically contains account health info)

**Binance-Specific Behavior:**
- Calls `self.instance.get_account_status()`
- Weight cost: weight += 1

**Error Handling:**
- No explicit exception handling; exceptions propagate to caller

**Example:**
```python
account_status = stock.info()
```

---

### 4.8 `get_symbol_info(pair_name)` → dict

**Purpose:** Fetch trading rules and precision info for a symbol

**Parameters:**
- `pair_name` – **str**: Binance pair symbol (e.g., "LINKUSDT")

**Returns:**
- **dict**: Symbol info response with:
  - `"symbol"`: Pair name
  - `"filters"`: List of filter objects (LOT_SIZE, MIN_NOTIONAL, PRICE_FILTER, etc.)
  - `"baseAsset"`, `"quoteAsset"`: Currency symbols
  - Other metadata

**Binance-Specific Behavior:**
- Calls `self.instance.get_symbol_info(pair_name)`
- Weight cost: weight += 10

**Key Filter Types:**
- `"LOT_SIZE"`: min/max quantity (`minQty`, `maxQty`, `stepSize`)
- `"MIN_NOTIONAL"`: min order value in quote currency (`minNotional`)
- `"PRICE_FILTER"`: min/max price and tick size

**Error Handling:**
- No explicit exception handling; exceptions propagate

**Example:**
```python
info = stock.get_symbol_info("LINKUSDT")
for f in info['filters']:
    if f["filterType"] == "LOT_SIZE":
        min_qty = float(f["minQty"])
```

---

### 4.9 `is_invalid_amount(amount, price)` → bool

**Purpose:** Validate if an order amount meets Binance's minimum size/notional requirements

**Parameters:**
- `amount` – **float**: Order quantity
- `price` – **float**: Limit price

**Returns:**
- **bool**: `True` if order is invalid (too small), `False` if valid

**Binance-Specific Behavior:**

1. **Fetches Symbol Info:** Calls `get_symbol_info()` to retrieve LOT_SIZE and MIN_NOTIONAL filters

2. **Minimum Order Size (LOT_SIZE):**
   - Defaults to 0.01
   - Overridden by filter `minQty` if available
   - Check: `amount < 2 * MINIMUM_ORDER_SIZE` (2x is a safety hack)

3. **Minimum Notional (MIN_NOTIONAL):**
   - Defaults to 5 (USDT)
   - Overridden by filter `minNotional` if available
   - Check: `amount * price < 2 * MINIMUM_NOTIONAL` (2x safety)

4. **Weight Cost:** Calls `get_symbol_info()` internally (weight += 10)

5. **Logging:** Logs all threshold values and order parameters

**Returns True (Invalid) if:**
- `amount < 2 * MINIMUM_ORDER_SIZE` OR
- `amount * price < 2 * MINIMUM_NOTIONAL`

**Example:**
```python
# LINKUSDT: minQty=0.01, minNotional=5
is_invalid = stock.is_invalid_amount(amount=0.2, price=31.0)  # 0.2 * 31 = 6.2 > 5 → False (valid)

is_invalid = stock.is_invalid_amount(amount=0.1, price=31.0)  # 0.1 * 31 = 3.1 < 5 → True (invalid)
```

---

### 4.10 `funds(coin, asset_type="free")` → (int, float)

**Purpose:** Fetch available balance for a specific coin

**Parameters:**
- `coin` – **str**: Coin symbol (e.g., "LINK", "USDT", "BTC")
- `asset_type` – **str**: Balance type; default "free" (available for trading); alternative "locked" (in open orders)

**Returns:**
- **tuple(int, float):** `(status, amount)`
  - `status` – **int**: `STATUS_SUCCESS` if coin found, `STATUS_FAIL` otherwise
  - `amount` – **float**: Available balance in the coin

**Binance-Specific Behavior:**

1. **Margin Account:** Uses `get_margin_account()` to fetch account with borrowed funds
   - Returns `{"userAssets": [{"asset": "LINK", "free": 10.5, "locked": 0.0, ...}, ...]}`

2. **Balance Type:** Defaults to "free" (unreserved); also supports "locked" (in open orders)

3. **Logging:** Logs balances for BTC and USDT; logs requested coin if found

4. **Weight Cost:** weight += 1

**Error Handling:**
- Catches `BinanceRequestException` → logs error, returns (STATUS_FAIL, 0.0)
- Catches `BinanceAPIException` → logs status code/message, returns (STATUS_FAIL, 0.0)

**Example:**
```python
status, link_balance = stock.funds("link", asset_type="free")
if status == STATUS_SUCCESS:
    print(f"Available LINK: {link_balance}")
```

---

### 4.11 `get_aviable_loan(coin)` → (int, float)

**Purpose:** Fetch maximum available loan amount for margin trading a coin

**Parameters:**
- `coin` – **str**: Coin symbol (e.g., "USDT")

**Returns:**
- **tuple(int, float):** `(status, max_loan_amount)`
  - `status` – **int**: `STATUS_SUCCESS` or `STATUS_FAIL`
  - `max_loan_amount` – **float**: Maximum amount that can be borrowed in that coin

**Binance-Specific Behavior:**

1. **Binance API:** Calls `get_max_margin_loan(asset=coin.upper())`

2. **Weight Cost:** weight += 50 (expensive operation)

3. **Returns Response:** Unpacks float value from response `["amount"]`

**Error Handling:**
- Catches `BinanceRequestException` → logs error, returns (STATUS_FAIL, 0.0)
- Catches `BinanceAPIException` → logs status code/message, returns (STATUS_FAIL, 0.0)

**Example:**
```python
status, max_usdt = stock.get_aviable_loan("usdt")
if status == STATUS_SUCCESS:
    print(f"Can borrow up to {max_usdt} USDT")
```

---

### 4.12 `borrow(coin, amount)` → (int, dict)

**Purpose:** Borrow coins from Binance margin account

**Parameters:**
- `coin` – **str**: Coin symbol (e.g., "USDT", "LINK")
- `amount` – **float**: Amount to borrow

**Returns:**
- **tuple(int, dict):** `(status, transaction)`
  - `status` – **int**: `STATUS_SUCCESS` or `STATUS_FAIL`
  - `transaction` – **dict**: Binance borrow response (contains txn ID, etc.)

**Binance-Specific Behavior:**

1. **Binance API:** Calls `create_margin_loan(asset=coin.upper(), amount=formatted_amount)`

2. **Amount Formatting:** Formats to 6 decimal places: `"%.6f" % amount`

3. **Weight Cost:** weight += 3000 (very expensive; rare operation)

4. **Timing:** Sleeps 1 second after borrow to allow coins to settle in account

**Error Handling:**
- Catches `BinanceRequestException` → logs error, returns (STATUS_FAIL, {})
- Catches `BinanceAPIException` → logs status code/message, returns (STATUS_FAIL, {})

**Example:**
```python
status, txn = stock.borrow("usdt", amount=100.0)
if status == STATUS_SUCCESS:
    print(f"Borrowed 100 USDT, txn: {txn}")
```

---

### 4.13 `repay(coin, amount)` → (int, float)

**Purpose:** Repay borrowed coins to Binance margin account

**Parameters:**
- `coin` – **str**: Coin symbol to repay
- `amount` – **float**: Amount to repay

**Returns:**
- **tuple(int, float):** `(status, repaid_amount)`
  - `status` – **int**: `STATUS_SUCCESS` or `STATUS_FAIL`
  - `repaid_amount` – **float**: Actual amount repaid

**Binance-Specific Behavior:**

1. **Binance API:** Calls `repay_margin_loan(asset=coin.upper(), amount=formatted_amount)`

2. **Smart Repayment:**
   - Checks available funds via `funds(coin)` first
   - Caps repayment to available balance if insufficient
   - Applies delta = 0.00001 to avoid precision errors

3. **Amount Formatting:** Formats to 5 decimal places: `"%.5f" % (amount - delta)`

4. **Early Return:** If calculated amount < 0 after delta adjustment, returns (STATUS_SUCCESS, 0.0) without repayment

5. **Weight Cost:** weight += 3000 (very expensive)

6. **Timing:** Sleeps 1 second after repay to allow transaction settlement

**Error Handling:**
- Catches `BinanceRequestException` → logs error, continues
- Catches `BinanceAPIException` → logs status code/message
  - Special case: Catches "Repay Failed. Repay amount exceeds borrow amount." message (commented-out recovery logic)

**Example:**
```python
status, repaid = stock.repay("usdt", amount=100.0)
if status == STATUS_SUCCESS:
    print(f"Repaid {repaid} USDT")
```

---

## 5. Rate Limiting

### Design

Binance uses a weight-based rate limiting system:
- Each REST API call costs a certain weight
- Weight accumulates within a rolling 60-second window
- When weight exceeds 5000 in any 60-second window, new requests are blocked with HTTP 418 (rate limited)

### Weight Tracking

**Attributes:**
- `self.weight` – **int**: Cumulative weight in current window; manually incremented after each API call
- `self.weight_set_time` – **float**: Unix timestamp when window started or was last reset
- `self.overflow_weight` – **int**: Threshold (5000)
- `self.overflow_weight_time` – **int**: Window duration in seconds (60)

### Weight Costs by Operation

| Operation | Weight |
|-----------|--------|
| `get_candles_history()` | 2 per interval fetch (4 fetches = 8 total) |
| `depth()` | 5–250 (depends on level count) |
| `trade()` (buy/sell) | 6 |
| `cancel_order()` | 10 |
| `order_info()` | 10 |
| `info()` | 1 |
| `get_symbol_info()` | 10 |
| `funds()` | 1 |
| `get_aviable_loan()` | 50 |
| `borrow()` | 3000 |
| `repay()` | 3000 |

### Rate Limit Prevention (`set_operation_sleep()`)

**Method (from StockInterface):**

```python
def set_operation_sleep(self):
    if self.overflow_weight == 0 or self.overflow_weight_time == 0:
        return False
    
    # Check if weight exceeded and window still open
    if self.weight > self.overflow_weight and \
       time.time() - self.weight_set_time < self.overflow_weight_time:
        print("STOCK: weight exceeded; sleeping for 1 minute...")
        time.sleep(self.overflow_weight_time)  # 60 seconds
        return True
    
    # Reset window if time has passed
    if time.time() - self.weight_set_time > self.overflow_weight_time:
        self.weight = 0
        self.weight_set_time = time.time()
    
    return False
```

**Backoff Logic:**
1. If `weight > 5000` and current window is still active (< 60 sec elapsed), sleep for 60 seconds
2. After sleep, weight resets to 0 and window restarts
3. If > 60 sec have elapsed since `weight_set_time`, auto-reset without sleeping

### Current Usage

The `Stock_Binance` class **manually increments `self.weight`** after each API call (e.g., `self.weight += 2` after `get_historical_klines()`). The `set_operation_sleep()` method is available but **not called within Stock_Binance** — callers (like `robot.py`) are responsible for checking rate limit status before making operations.

---

## 6. Error Handling

### Exception Types

**BinanceRequestException**
- **Cause:** Network/connection errors; timeouts; unreachable host
- **Handling in Stock_Binance:** Caught and logged as "EXCEPTION: BinanceRequestException"; execution continues; returns STATUS_FAIL
- **Recovery:** No automatic retry; caller must retry or abandon

**BinanceAPIException**
- **Cause:** Invalid API calls; authentication failures; invalid parameters; violated trading rules
- **Status Code + Message:** Logged (e.g., "EXCEPTION: 400 Invalid quantity")
- **Handling:** Caught and logged; execution continues; returns STATUS_FAIL
- **Special Cases:**
  - `repay()` catches "Repay Failed. Repay amount exceeds borrow amount." (recovery commented out)

### Retry Logic

**Current Status:** No automatic retry logic implemented in `Stock_Binance`

- Transient errors (timeouts, 500-level errors) are not retried
- Caller must implement retry loops if needed
- Recommended: Exponential backoff retry wrapper around critical operations (candle fetching, order placement)

### Circuit Breaker Pattern

**Current Status:** Not implemented in `Stock_Binance`

- No tracking of consecutive failures
- No pause after repeated failures
- Recommendation: Add circuit breaker in robot or strategy layer to pause trading after N failed orders

### Error Recovery Examples

1. **Candle Fetch Failure:** `get_candles_history()` returns incomplete dict; caller must detect and re-request
2. **Order Placement Failure:** `trade()` returns STATUS_FAIL; caller can retry or escalate
3. **Rate Limit Hit:** `set_operation_sleep()` pauses; caller can continue
4. **Network Timeout:** Exception not caught; propagates to caller

---

## 7. Order Execution

### Order Type

- **Type:** Limit orders only (no market, stop-loss, or OCO orders)
- **Binance Constant:** `BinanceClient.ORDER_TYPE_LIMIT`
- **Time-in-Force:** Good Till Cancel (GTC) — order stays active until filled or manually canceled
- **Binance Constant:** `BinanceClient.TIME_IN_FORCE_GTC`

### Account Type

- **Current:** Margin account (`create_margin_order()`)
- **Alternative (commented out):** Spot account (`order_limit_buy()`, `order_limit_sell()`)
- **Margin Advantages:** Access to borrowed funds for leverage trading
- **Margin Disadvantages:** Requires active margin account; subject to liquidation; higher fees/interest

### Price Precision

- **Formatting:** `float("{0:.2f}".format(price))`
- **Decimal Places:** 2 (e.g., 31.50, not 31.501)
- **Binance Validation:** LINKUSDT actually allows more precision; 2 decimals is conservative
- **Risk:** Rounding may cause order rejections on assets requiring different precision

### Quantity Rounding

- **Formatting:** `float("{0:.2f}".format(amount - 0.01))`
- **Decimal Places:** 2 (e.g., 10.00, 10.25)
- **Hack:** Subtracts 0.01 to account for fees; prevents position from being fully closed
- **Risk:** Can leave small dust amounts; may fail on very small orders (< 2 * min_qty)

**BUG COMMENT:**
```python
# TODO: BUG can lead to not full position close especially on position close
quantity=float("{0:.2f}".format(amount-0.01))
```

### Order Response

Binance returns order details including:
- `orderId` – **int**: Unique order ID for status queries
- `status` – **str**: NEW, PARTIALLY_FILLED, FILLED, CANCELED, etc.
- `price`, `origQty`, `executedQty`, `cummulativeQuoteQty`, etc.

---

## 8. Candle Data Fetching

### Data Source

**Binance REST API:** `Client.get_historical_klines()`
- **Endpoint:** /api/v3/klines (public, rate-limited)
- **Parameters:** symbol, interval, startTime (optional), endTime (optional), limit (default 500, max 1000)

### Kline Intervals

Fetched intervals in `get_candles_history()`:
- **1-minute:** `BinanceClient.KLINE_INTERVAL_1MINUTE`
- **15-minute:** `BinanceClient.KLINE_INTERVAL_15MINUTE`
- **1-hour:** `BinanceClient.KLINE_INTERVAL_1HOUR`
- **12-hour:** `BinanceClient.KLINE_INTERVAL_12HOUR`

### Kline Data Format

Each kline (candle) is a list:
```
[open_time_ms, open, high, low, close, volume, close_time_ms, quote_asset_volume,
 number_of_trades, taker_buy_base_asset_volume, taker_buy_quote_asset_volume, ignore]
```

Mapped to DataFrame columns:
- `open_time` – Unix ms; converted to DatetimeIndex
- `open, high, low, close` – OHLC prices (strings converted to float)
- `volume` – Base asset volume
- `close_time, qav, num_trades, taker_base_vol, taker_quote_vol, ignore` – Auxiliary data

### Lookback Windows

| Interval | Lookback | Reason |
|----------|----------|--------|
| 1-minute | "10 hours ago UTC" | ~600 candles; covers recent trading |
| 15-minute | "4 days ago UTC" | ~384 candles; multi-day context |
| 1-hour | "43 days ago UTC" | ~1032 candles; 6-week history |
| 12-hour | "121 days ago UTC" | ~242 candles; 4-month history |

### Resampling

Uses pandas `.resample()` to aggregate candles:
```python
ohlc[t] = df.resample(f'{t}min').agg({
    'open': 'first',    # First open in period
    'high': 'max',      # Highest high in period
    'low': 'min',       # Lowest low in period
    'close': 'last',    # Last close in period
    'volume': 'sum'     # Total volume in period
})
```

**Example:** 5-minute candle from 1-minute data:
- Takes 5 consecutive 1-minute candles
- Open = open of first 1-min candle
- High = highest of all 5 highs
- Low = lowest of all 5 lows
- Close = close of 5th 1-min candle
- Volume = sum of all 5 volumes

### Candle Limit

Each timeframe returns last 120 candles (`.iloc[-120:]`). This balances:
- **Memory usage:** ~12 columns × 120 rows = manageable
- **Lookback coverage:** 120 1-minute candles = 2 hours; 120 1-hour candles = 5 days
- **Trade signal context:** Sufficient for technical indicators (RSI, MACD, etc.)

---

## 9. Existing Approach

### Architecture Characteristics

1. **Single Symbol per Instance**
   - Each `Stock_Binance` instance manages one trading pair (coin + coin_base)
   - Pair set via environment or in caller logic
   - Simplifies state management; limits concurrency

2. **Synchronous REST API**
   - All methods are blocking (no async/await)
   - Calls wait for Binance response before returning
   - Trades sequential; network latency adds up

3. **Polling-Based Status Checking**
   - No WebSocket streams for real-time updates
   - `order_info()` requires explicit calls; callers must poll for fills
   - Example: `cancel_order()` polls 10 times at 2-second intervals for PENDING_CANCEL

4. **Manual Rate Limit Tracking**
   - Weight incremented after each call; no automatic backoff
   - Caller responsible for checking `set_operation_sleep()` before operations
   - Passive approach; relies on caller discipline

5. **Error Recovery via Retries**
   - No automatic retry in `Stock_Binance`
   - Caller must wrap operations with retry logic
   - Transient failures (timeouts) cause immediate failure

6. **DataFrame-Based Data**
   - All candle data in pandas DataFrames
   - Enables easy resampling and indicator calculation
   - Integration with rest of pybtctr2 codebase

### Strengths

- **Simplicity:** Single-threaded, easy to debug
- **Low overhead:** No async complexity; minimal resource usage
- **Data integration:** Native pandas DataFrames work with `data.py` and `indicators.py`
- **Transparency:** All API calls logged; weight tracking visible

### Weaknesses

- **Latency:** Sequential REST calls (e.g., `get_candles_history()` makes 4 calls serially)
- **Order Latency:** No real-time fills; polling introduces delays
- **No Concurrency:** Single-pair limitation; cannot trade multiple pairs simultaneously
- **Manual Burden:** Callers must handle retries, rate limits, multi-symbol scenarios

---

## 10. Potential Improvements

1. **WebSocket Real-Time Streams**
   - Subscribe to `@kline`, `@trade`, `@depth` streams
   - Eliminate polling for candle updates and fills
   - Benefit: Sub-second latency on price updates

2. **Async Methods**
   - Use `asyncio` + `aiohttp` for concurrent API calls
   - Example: fetch 4 kline intervals in parallel instead of serially
   - Benefit: Reduce `get_candles_history()` latency from ~4s to ~1s

3. **Batch Kline Requests**
   - Combine multiple symbol requests in single call (if API supports)
   - Reduce total weight cost and round-trip latency
   - Benefit: Multi-pair trading with lower overhead

4. **Order Type Flexibility**
   - Add market orders for urgent execution
   - Add stop-loss and take-profit (OCO) orders
   - Add trailing stops
   - Benefit: Better risk management; fewer fills on slippage

5. **Intelligent Rate Limit Prediction**
   - Pre-calculate weight cost of operation
   - Proactive sleep before hitting limit (not after)
   - Adaptive window tracking (per-second resolution)
   - Benefit: No wasted sleep time; smoother execution

6. **Connection Pooling**
   - Reuse HTTP connections across multiple requests
   - Use session-based connection (aiohttp ClientSession or requests.Session)
   - Benefit: Faster requests; lower TCP overhead

7. **Caching for Stable Queries**
   - Cache `get_symbol_info()` results (rules don't change often)
   - Cache account status with TTL
   - Benefit: Reduce API calls; faster access

8. **Monitoring and Metrics**
   - Track API latency per operation
   - Monitor rate limit headroom
   - Count errors by type
   - Benefit: Visibility into system health; easier debugging

9. **Circuit Breaker**
   - Pause trading after N consecutive order failures
   - Automatic recovery after cooldown
   - Benefit: Prevent cascading failures during issues

10. **Multi-Symbol Support**
    - Extend class to manage multiple pairs
    - Use dictionary of pair-specific state
    - Benefit: Trade multiple coins with single instance

---

## Appendix: Related Constants

Constants used by `Stock_Binance` (defined in `helpers.py`):

```python
STATUS_SUCCESS = <int>  # Success status code
STATUS_FAIL = <int>     # Failure status code
TRADE_BUY = <int>       # Buy order constant
TRADE_SELL = <int>      # Sell order constant
ORDER_STATUS_NEW = <int>
ORDER_STATUS_PARTIALLY_FILLED = <int>
ORDER_STATUS_FILLED = <int>
ORDER_STATUS_CANCELED = <int>
ORDER_STATUS_PENDING_CANCEL = <int>
ORDER_STATUS_REJECTED = <int>
ORDER_STATUS_EXPIRED = <int>
```

---

## Appendix: Logging

All `Stock_Binance` methods call `log_stock(operation_name, weight)` after API calls to track:
- Operation name (e.g., "trade", "depth", "get_symbol_info")
- Current accumulated weight

Example call: `log_stock("get_candles_history", self.weight)`

Errors logged via: `log_error(message)`

---

## Summary

The `Stock_Binance` class is a battle-tested Binance adapter with strong fundamentals: clear separation of concerns, comprehensive error logging, and tight rate limit tracking. Its synchronous, single-pair design prioritizes simplicity and reliability over throughput. The primary expansion vector is async/WebSocket integration for lower latency; secondary improvements include caching, connection pooling, and more sophisticated retry/circuit-breaker patterns.
