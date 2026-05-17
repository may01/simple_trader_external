# BaseStock Interface Class Specification

## Class Overview

The `StockInterface` class (located in `stocks/base_stock.py`) serves as an abstract base class that defines the interface for cryptocurrency exchange adapters. It provides a standardized abstraction layer enabling multiple exchange implementations (Binance, Kraken, Coinbase, etc.) to be used interchangeably within the trading bot system.

The class encapsulates all exchange-specific API interactions including candle data retrieval, order management, account information, and trading rules validation. By defining a common interface, the system maintains loose coupling between the trading logic and exchange implementations, allowing seamless switching between providers without modifying core strategy code.

This implements the **Strategy design pattern** where each exchange implementation is a concrete strategy providing a specific execution mechanism. The base interface ensures type safety and contract consistency across all implementations while allowing exchange-specific optimizations.

## Key Attributes

| Attribute | Type | Purpose | Notes |
|-----------|------|---------|-------|
| `stock_name` | str | Exchange identifier (e.g., "binance", "kraken") | Set in constructor, used for logging |
| `key` | str | API public key for authentication | May be empty string for mock implementations |
| `secret` | str | API secret key for authentication | May be empty string for mock implementations |
| `coin_base` | str | Base currency (e.g., "USDT", "USD") | Default: "USDT" |
| `coin` | str | Trading coin/asset being traded | Empty by default; set per-session |
| `fee` | float | Commission fee as decimal (e.g., 0.001 for 0.1%) | Default: 0.001 (0.1%) |
| `was_init` | bool | Initialization flag indicating if object is ready | Always True after constructor |
| `instance` | object | Exchange API client instance (e.g., BinanceClient) | May be empty list initially; set by subclasses |
| `weight` | int | Current request weight for rate limiting | Used to track API call quota |
| `weight_set_time` | float | Timestamp when weight was last set | Unix epoch time in seconds |
| `overflow_weight` | int | Threshold above which rate limiting applies (e.g., 5000) | Exchange-specific; 0 = disabled |
| `overflow_weight_time` | int | Time window for weight reset in seconds (e.g., 60) | E.g., weight resets every 60 seconds |

## Constructor

### `__init__(name, key, key_secret, base="USDT", coin="")`

**Purpose:** Initialize the exchange adapter with authentication credentials and configuration.

**Parameters:**
- `name` (str): Exchange name identifier (e.g., "binance", "kraken", "mock")
- `key` (str): API public key for exchange authentication
- `key_secret` (str): API secret key for exchange authentication
- `base` (str, optional): Base currency for trading pairs. Default: "USDT"
- `coin` (str, optional): Trading asset symbol. Default: "" (empty, set later per session)

**Initialization:**
- Stores all parameters as instance attributes
- Initializes `instance` to empty list (subclasses populate with exchange client)
- Sets `was_init = True` to mark object as ready
- Sets default `fee = 0.001` (0.1% commission)
- Initializes weight tracking: `weight = 0`, `weight_set_time = 0`
- Initializes rate limit thresholds: `overflow_weight = 0`, `overflow_weight_time = 0`

**Preconditions:**
- `name` must be non-empty string identifying the exchange
- `base` should be valid currency code (e.g., "USDT", "USD", "EUR")
- For live trading: `key` and `key_secret` must be valid exchange API credentials

**Postconditions:**
- Object is initialized with `was_init = True`
- All attributes are set and available for subclass initialization
- No external connections made (subclasses handle API client setup)

**Exception Handling:**
- No exceptions raised by base class constructor
- Subclasses may raise authentication errors during client initialization

## Key Methods & Interfaces

### `depth(qnt: int) → list`

**Purpose:** Retrieve order book depth data (bid/ask levels) for the current symbol.

**Parameters:**
- `qnt` (int): Number of price levels to retrieve from each side (bid/ask)

**Return Type:**
- list: Empty list in base class (placeholder for subclass implementation)

**Preconditions:**
- Valid symbol set (pair format: lowercase `coin_base`, e.g., "link_usdt")
- Exchange client initialized and authenticated

**Postconditions:**
- Returns bid and ask price levels up to `qnt` depth
- Data is current (latest snapshot from exchange)

**Exceptions:**
- `APIException`: Connection failure, rate limit exceeded, or invalid symbol
- `SymbolException`: Symbol not supported by exchange

**Notes:**
- Base class returns empty list; implemented by subclasses
- Typically called for price level analysis before order placement

---

### `get_candles_history(time_list: list, coin: str, time_point: int = 0) → dict`

**Purpose:** Retrieve OHLC (Open-High-Low-Close) candle data across multiple timeframes.

**Parameters:**
- `time_list` (list): List of timeframe periods in minutes (e.g., [1, 5, 15, 60, 240, 1440])
- `coin` (str): Trading asset symbol (e.g., "LINK", "ETH")
- `time_point` (int, optional): Unix timestamp in seconds for historical cutoff. Default: 0 (current time)

**Return Type:**
- dict: Dictionary with timeframe as key (int: minutes) and DataFrame as value
  - Each DataFrame has columns: open, high, low, close, volume, volume2 (or similar)
  - Index: datetime objects representing candle open time

**Preconditions:**
- `coin` must be valid trading asset
- `self.coin_base` must be set (e.g., "USDT")
- Exchange client initialized and authenticated
- `time_list` values must be supported by exchange (typically [1, 3, 5, 15, 30, 60, 120, 240, 1440])

**Postconditions:**
- Returns OHLC data for all requested timeframes
- Data is sorted chronologically (oldest to newest)
- Missing data points filled via forward-fill strategy (previous value propagated)
- DataFrames include only recent history (typically last 100-120 candles per timeframe)

**Exceptions:**
- `APIException`: Connection failure, rate limit exceeded
- `SymbolException`: Invalid trading pair
- Returns False (boolean) on network error after retry attempts

**Algorithm Notes:**
- Base class delegates to `get_cryptowatch_history()` by default
- May also support `get_cryptocompare_history()` as alternative data source
- Implements automatic retry with 60-second sleep on transient failures
- Fills zero-volume candles with forward-fill to handle missing data

---

### `get_cryptocompare_history(time_list: list, coin: str) → dict or False`

**Purpose:** Retrieve candle data from CryptoCompare API as alternative data source.

**Parameters:**
- `time_list` (list): Timeframe periods in minutes
- `coin` (str): Trading asset symbol

**Return Type:**
- dict: OHLC data by timeframe (same structure as `get_candles_history`)
- False: Boolean False on retrieval failure

**Preconditions:**
- CryptoCompare API accessible and not rate-limited
- Valid `coin` symbol known to CryptoCompare

**Postconditions:**
- Returns aggregated candle data suitable for indicator calculations

**Exceptions:**
- `HTTPError`, `URLError`, `RemoteDisconnected`: Network exceptions caught and retried
- On exception: sleeps 60 seconds and recursively retries

---

### `get_cryptowatch_history(time_list: list, coin: str, time_point: int = 0) → dict`

**Purpose:** Retrieve candle data from CryptoWatch API as primary data source.

**Parameters:**
- `time_list` (list): Timeframe periods in minutes
- `coin` (str): Trading asset symbol
- `time_point` (int, optional): Unix timestamp in seconds for historical boundary. Default: 0

**Return Type:**
- dict: OHLC data by timeframe
  - Keys: timeframe in minutes (int)
  - Values: pandas DataFrame with columns [time, open, high, low, close, volume, volume2]

**Preconditions:**
- CryptoWatch API accessible and not rate-limited
- Exchange name set in `self.stock_name`
- `self.coin_base` set to valid currency (e.g., "USDT")
- Timeframes in `time_list` must be in allowed_periods: [1, 3, 5, 15, 30, 60, 120, 240, 1440, 4320, 10080]

**Postconditions:**
- Returns OHLC data for all valid timeframes from `time_list`
- Resamples base timeframes into additional derived timeframes
- Zero-volume candles have OHLC values filled with forward-fill
- DataFrames include last 100 candles per timeframe

**Data Transformation:**
- Base 1-min data resampled to: 7min
- Base 3-min data resampled to: 9min, 12min, 18min, 21min, 24min, 27min
- Base 5-min data resampled to: 35min, 40min, 50min, 55min
- Base 15-min data resampled to: 45min, 75min, 90min, 105min, 135min, 165min
- Base 30-min data resampled to: 150min, 210min, 6h, 10h, 14h, 18h, 22h
- Base 60-min data resampled to: 120min, 180min
- Base 240-min (4h) data resampled to: 8h, 12h, 16h, 20h, 1.25d, 1.5d, 1.75d, 2.5d, 3.5d
- Base 1440-min (1d) data resampled to: 2d through 30d (15 derived periods)

**Exceptions:**
- `HTTPError`, `URLError`, `RemoteDisconnected`: Caught and retried with 60-second sleep

**Notes:**
- Primary implementation used by `get_candles_history()`
- CryptoWatch URL format: `https://api.cryptowat.ch/markets/{exchange}/{pair}/ohlc?periods=...`
- Pair format: lowercase (e.g., "linkusdt")
- Supports `before` parameter for historical time boundaries

---

### `trade(pair: str, trade_type: str, price: float, amount: float) → dict`

**Purpose:** Place a market or limit order (buy/sell) on the exchange.

**Parameters:**
- `pair` (str): Trading pair in exchange format (e.g., "LINKUSDT")
- `trade_type` (str): Order type - "BUY" or "SELL"
- `price` (float): Limit price per unit (use current price for market orders)
- `amount` (float): Order quantity in base currency

**Return Type:**
- dict: Order response with keys:
  - `"success"`: boolean indicating if order was placed
  - `"error"`: error message if failed
  - `"return"`: nested dict with `"order_id"`: unique order identifier string

**Preconditions:**
- Exchange client initialized and authenticated with trading permissions
- Valid trading pair for the exchange
- `price > 0` and `amount > 0`
- Account has sufficient balance for the order (checked by exchange)
- Order amount meets exchange minimum notional (checked by `is_amount_valid()`)

**Postconditions:**
- If successful: Order placed on exchange; order_id returned for tracking
- If failed: No order placed; error details in response

**Exceptions:**
- `OrderException`: Insufficient balance, invalid pair, or order validation failure
- `APIException`: Connection error, rate limit exceeded
- `BalanceException`: Insufficient available balance (caught before placement)

**Notes:**
- Base class prints placeholder message; implemented by subclasses
- Returns empty list in base implementation (placeholder)
- Binance implementation uses `BinanceClient.create_test_order()` for validation, then `create_order()`

---

### `buy(pair: str, order_type: str, price: float, amount: float) → None`

**Purpose:** Convenience method to place a BUY order.

**Parameters:**
- `pair` (str): Trading pair
- `order_type` (str): Order type specification
- `price` (float): Limit price
- `amount` (float): Order quantity

**Return Type:**
- None (returns without value in base class)

**Notes:**
- Base class is placeholder; typically delegates to `trade()` with side="BUY"

---

### `sell(pair: str, order_type: str, price: float, amount: float) → dict`

**Purpose:** Convenience method to place a SELL order.

**Parameters:**
- `pair` (str): Trading pair
- `order_type` (str): Order type specification
- `price` (float): Limit price
- `amount` (float): Order quantity

**Return Type:**
- dict: Order response (same structure as `trade()`)

**Notes:**
- Base class is placeholder; typically delegates to `trade()` with side="SELL"

---

### `cancel_order(order_id: str) → dict`

**Purpose:** Cancel an open order by its order ID.

**Parameters:**
- `order_id` (str): Unique order identifier returned from order placement

**Return Type:**
- dict: Cancellation response with keys:
  - `"success"`: boolean indicating if cancellation succeeded
  - `"error"`: error message if failed

**Preconditions:**
- Order ID must be valid and correspond to an open order on the exchange
- Order must not already be filled or expired
- Exchange client must be authenticated

**Postconditions:**
- If successful: Order removed from exchange; no further fills possible
- If failed: Order remains active on exchange

**Exceptions:**
- `OrderException`: Order not found, already filled, or exchange rejects cancellation
- `APIException`: Connection error, rate limit exceeded

**Notes:**
- Base class returns empty list (placeholder)
- Subclasses provide actual implementation
- Critical for risk management (stop-loss exits, position unwinding)

---

### `order_info(order_id: str) → dict`

**Purpose:** Retrieve current status and details of an order.

**Parameters:**
- `order_id` (str): Unique order identifier

**Return Type:**
- dict: Order details with keys:
  - `"success"`: boolean (1 = success, 0 = failure)
  - `"error"`: error message
  - `"return"`: nested dict with:
    - `"status"`: order state string (e.g., "FILLED", "PARTIALLY_FILLED", "NEW", "CANCELED")
    - `"start_amount"`: original order quantity
    - `"left_amount"`: remaining unfilled quantity
    - `"rate"`: filled price (may be average if partial fill)

**Preconditions:**
- Order ID must be valid and correspond to an order on the exchange
- Exchange client must be authenticated

**Postconditions:**
- Returns current order state and fill status
- Repeated calls show updated amounts as order fills

**Exceptions:**
- `OrderException`: Order not found on exchange
- `APIException`: Connection error, rate limit exceeded

**Notes:**
- Base class returns empty list (placeholder)
- Used by `train_robot.py` to track position lifecycle
- Essential for partial fill handling and position closure verification

---

### `info() → dict`

**Purpose:** Retrieve account information including balances, margin status, and trading limits.

**Return Type:**
- dict: Account details (structure varies by exchange)
- Base class returns empty list

**Preconditions:**
- Exchange client initialized and authenticated

**Postconditions:**
- Returns current account state including balances and restrictions

**Exceptions:**
- `APIException`: Connection error, rate limit exceeded
- `AuthException`: Invalid API credentials

**Notes:**
- Base class is placeholder
- Used by Robot class to verify sufficient balance before trading
- May include margin account info, open orders count, etc.

---

### `is_amount_valid(amount: float, price: float) → bool`

**Purpose:** Validate that an order amount meets exchange minimum requirements.

**Parameters:**
- `amount` (float): Order quantity
- `price` (float): Order price per unit

**Return Type:**
- bool: True if amount is valid (meets min_notional and min_qty), False otherwise

**Preconditions:**
- `amount > 0` and `price > 0`
- Exchange trading rules loaded (via `get_trading_rules()`)

**Postconditions:**
- Returns validation result
- No side effects

**Exceptions:**
- None (returns boolean)

**Notes:**
- Base class always returns False (conservative placeholder)
- Subclasses implement actual validation logic
- Checks: `amount * price >= min_notional` and `amount >= min_qty`
- Prevents order rejection due to insufficient size

---

### `set_operation_sleep() → bool`

**Purpose:** Manage rate limiting by implementing automatic sleep when API weight exceeds threshold.

**Return Type:**
- bool: True if sleep was applied, False otherwise

**Preconditions:**
- `overflow_weight` and `overflow_weight_time` configured (non-zero)
- `weight` and `weight_set_time` tracked after each API call

**Postconditions:**
- If weight exceeded: sleeps for `overflow_weight_time` seconds, resets weight, returns True
- If timeout passed: resets weight counter, returns False
- Allows code to continue without sleep if threshold not exceeded

**Logic:**
```
IF weight > overflow_weight AND (current_time - weight_set_time) < overflow_weight_time:
    sleep(overflow_weight_time)
    RETURN True
ELSE IF (current_time - weight_set_time) > overflow_weight_time:
    weight = 0
    weight_set_time = current_time
    RETURN False
```

**Notes:**
- Example: Binance sets overflow_weight=5000, overflow_weight_time=60 (sleep 60s if weight exceeds 5000 within 60s window)
- Weight resets every `overflow_weight_time` seconds
- Helps stay within exchange API rate limits

## Exchange-Specific Methods

### `get_commission_info() → dict`

**Purpose:** Retrieve fee tier information for the account (VIP status, maker/taker rates).

**Return Type:**
- dict: Fee structure with keys like:
  - `"maker_commission"`: maker order rate
  - `"taker_commission"`: taker order rate
  - `"vip_tier"`: account tier level
  - `"discount"`: any applicable discounts

**Notes:**
- Not implemented in base class
- Used for accurate PnL calculations in backtesting
- May vary by symbol or account status

---

### `get_server_time() → int`

**Purpose:** Get exchange server time to check for clock skew between local system and exchange.

**Return Type:**
- int: Unix timestamp in milliseconds from exchange server

**Notes:**
- Critical for authenticated requests; prevents nonce errors
- Helps identify timezone issues in backtesting
- Used to align local time with exchange time

---

### `get_trading_rules() → dict`

**Purpose:** Retrieve symbol-specific trading rules and constraints.

**Return Type:**
- dict: Trading restrictions with keys:
  - `"min_notional"`: minimum order value in base currency (e.g., 10 USDT)
  - `"min_qty"`: minimum order quantity in coin
  - `"price_precision"`: decimal places for price (e.g., 2 for price like 1.23)
  - `"quantity_precision"`: decimal places for quantity
  - `"status"`: symbol trading status (TRADING, HALT, BREAK)

**Notes:**
- Must be called before order placement to validate amounts
- Used by `is_amount_valid()` for validation
- May be cached and updated periodically

## Error Handling

The system defines exchange-specific exception types:

### `APIException`
**When:** Network issues, connection failures, timeouts, invalid endpoints
- Connection refused or timeout to exchange
- Invalid HTTP response (non-JSON, corrupted)
- Exchange returns 500+ status code

**Handling:**
- Caught and logged in data retrieval functions
- Triggers automatic retry with 60-second backoff sleep
- After N retries, propagates to caller

---

### `OrderException`
**When:** Order submission or management failures
- Invalid trading pair for the exchange
- Order validation failure (e.g., minimum notional not met)
- Order modification rejected by exchange
- Order exceeds position limits

**Handling:**
- Caught before order placement (via `is_amount_valid()`)
- Logged as warning; order not submitted
- Does not crash trading bot; falls back to WAIT action

---

### `BalanceException`
**When:** Insufficient available balance
- Attempt to buy without sufficient base currency balance
- Attempt to sell without sufficient coin balance
- Account frozen or restricted

**Handling:**
- Checked before order placement
- Prevents order submission
- Logged as warning; strategy pauses trading

---

### `SymbolException`
**When:** Invalid or unsupported trading pair
- Symbol not found on exchange (e.g., "INVALIDUSDT")
- Symbol trading halted (status != TRADING)
- Symbol pair format invalid

**Handling:**
- Raised during candle fetch or order placement
- Logged as error
- Halts trading for that pair until resolved

---

### `AuthException`
**When:** Authentication failures
- Invalid or expired API key
- Secret key incorrect or revoked
- IP whitelist restriction violated

**Handling:**
- Raised during client initialization
- Prevents any further API calls
- Requires manual API credential update and restart

## Existing Approach

The current implementation follows these architectural patterns:

1. **Abstract Base Class Pattern:**
   - `StockInterface` defines method signatures and common behavior
   - Subclasses (`Stock_Binance`, `Stock_Mock`) override methods with exchange-specific logic
   - Python doesn't use `@abstractmethod` decorators; reliance on duck typing

2. **Concrete Implementations:**
   - `Stock_Binance` in `stocks/binance_stock.py` — Production implementation using Binance API
   - `Stock_Mock` in `stocks/mock_stock.py` — Test mock returning pre-configured responses
   - `Stock_Kraken` (commented) — Placeholder for future Kraken integration

3. **API Paradigm:**
   - Synchronous (blocking) REST API calls only
   - No WebSocket streams for real-time data
   - Single trading pair per instance (symbol set via `coin` and `coin_base`)
   - All methods blocking; no async/await support

4. **Data Sources:**
   - Primary: CryptoWatch API (`get_cryptowatch_history`)
   - Fallback: CryptoCompare API (`get_cryptocompare_history`)
   - Live: Exchange API via client (e.g., `BinanceClient.get_historical_klines()`)

5. **Rate Limiting:**
   - Manual weight tracking per instance (`weight`, `weight_set_time`)
   - Threshold-based sleep (`overflow_weight`, `overflow_weight_time`)
   - No automatic backoff; relies on application-level management

6. **Error Recovery:**
   - Transient errors (network, temporary disconnects) trigger automatic retry
   - Retry includes 60-second sleep to allow recovery
   - Persistent errors (invalid credentials, bad symbols) fail immediately

## Potential Improvements

1. **Async/Await Support**
   - Refactor core methods (`fetch_candles()`, `get_candles_history()`) to async
   - Use `asyncio` with concurrent request fetching across multiple timeframes
   - Reduces total time for multi-timeframe data retrieval
   - Unblocks main event loop in live trading

2. **Batch Operations**
   - Add `fetch_candles_batch(symbols_list, intervals, time_range)` for multi-symbol fetches
   - Add `place_orders_batch(order_list)` for simultaneous order submission
   - Reduces total API calls when trading multiple pairs
   - Improves throughput for grid trading strategies

3. **WebSocket Data Streams**
   - Add optional `start_price_stream(symbols)` for real-time updates
   - Implement tick-by-tick price updates instead of polling candles
   - Reduces latency for high-frequency entries/exits
   - Lower bandwidth than polling; respects rate limits better
   - Example: Binance WebSocket endpoint `wss://stream.binance.com:9443/ws/`

4. **Order Type Flexibility**
   - Extend `trade()` to support market, limit, stop-loss, trailing-stop orders
   - Add `time_in_force` options (GTC, IOC, FOK, POST_ONLY)
   - Add conditional orders (trigger price, bracket orders)
   - Enable more sophisticated exit strategies (e.g., stop-loss + take-profit simultaneously)

5. **Caching Layer**
   - Cache `get_trading_rules()` output with TTL (e.g., 1 hour)
   - Cache symbol precision/constraints to reduce API calls
   - Implement local order book snapshot cache updated via WebSocket
   - Reduces calls to `get_symbol_info()`, `info()` during strategy execution

6. **Rate Limit Management Helpers**
   - Expose `get_weight()` to query remaining API capacity
   - Add `wait_for_capacity(required_weight)` blocking until weight available
   - Implement exponential backoff with jitter instead of fixed 60-second sleep
   - Track per-endpoint limits separately (Binance has different weights per endpoint)

7. **Exchange Abstraction Improvements**
   - Define interface in formal Python ABC (Abstract Base Class) with `@abstractmethod`
   - Separate data models from API responses (e.g., `Order`, `Candle` dataclasses)
   - Support both REST and WebSocket in same interface
   - Add dry-run mode for order validation without submission

8. **Error Handling Enhancement**
   - Define custom exception hierarchy (base `ExchangeException`)
   - Distinguish retriable errors (network) from permanent errors (bad credentials)
   - Add context to exceptions (symbol, order_id, timestamp)
   - Log full request/response for debugging exchange integration issues

9. **Monitoring & Metrics**
   - Track request latency per endpoint
   - Monitor rate limit headroom and historical consumption
   - Log all order placements and fills with timestamps
   - Expose metrics for alerting (e.g., alert if API latency > 5 seconds)

10. **Position Margin Support**
    - Add methods for margin trading: `borrow()`, `repay()`, `get_margin_info()`
    - Support short selling via `sell_short()`, `close_short()`
    - Implement margin call detection and liquidation prevention
    - Separate spot and margin account methods

