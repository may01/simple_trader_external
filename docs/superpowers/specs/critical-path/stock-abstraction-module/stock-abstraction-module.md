# Stock Abstraction Module Specification

## Overview

The **Stock Abstraction Module** provides a pluggable adapter layer that abstracts cryptocurrency exchange APIs, allowing the trading system to work with multiple exchanges without coupling to any specific implementation. The module serves as the interface between the Robot trading logic and the Binance REST API (and other potential exchanges).

The core responsibility is to handle all exchange-level operations: fetching market data (OHLC candles and order book depth), executing trades (buy/sell orders), monitoring order status, and querying account information. By decoupling the Robot from Binance-specific API details, the module enables future support for Kraken, Bitstamp, Coincheck, and other exchanges.

The module is organized around three key abstractions:

1. **StockInterface** (abstract base) — defines the contract all implementations must fulfill
2. **Stock_Binance** (concrete implementation) — provides Binance-specific REST API integration
3. **StockHolder** (singleton wrapper) — exposes module-level access via `stock_holder.item` for use throughout the system

## Module Boundaries

### Upstream Dependencies

- **Robot class** — calls `stock.item.trade()` to place orders, `stock.item.order_info()` to check fills, `stock.item.get_candles_history()` for market data
- **LiveData class** — calls `stock.item.get_candles_history()` each tick (live path); `stock.item.depth()` is called from StrategyManager (live-only, pending removal to a dedicated live module)
- **Position class** — reads `stock.item.fee` to calculate PnL
- **Trainer and TrainRobot** — use `stock.item` to fetch historical candles during backtesting

### Downstream Dependencies

- **Binance REST API** — public endpoints (klines, depth) and private endpoints (order placement, order queries, account info)
- **binance-python-api** (python-binance) — SDK for all Binance communications

### Key Interfaces Exposed

| Method | Input | Output | Purpose |
|--------|-------|--------|---------|
| `get_candles_history(time_list, coin, time_point)` | timeframes (min), coin name, optional epoch | Dict[int, DataFrame] | Fetch OHLCV candles, return keyed by minute interval |
| `trade(type, price, amount, force)` | BUY/SELL, price, quantity, force flag | (status, response_dict) | Place buy or sell order, return order ID |
| `order_info(order_id)` | order ID | (status, order_info_dict) | Query order status (filled, partially filled, pending, cancelled, etc.) |
| `cancel_order(order_id)` | order ID | (status, response_dict) | Cancel an open order, poll until confirmed |
| `depth(quantity)` | order book depth (e.g., 100, 500) | (asks_df, bids_df) | Fetch bid/ask order book, return as DataFrames with cumulative sums |
| `info()` | — | account_status | Query account info (margin status, balances) |
| `is_invalid_amount(amount, price)` | token quantity, price | boolean | Validate order size against Binance minimums |
| `funds(coin, asset_type)` | coin name, "free" or "locked" | (status, float) | Query available/locked balance for a specific coin |
| `get_aviable_loan(coin)` | coin name | (status, float) | Check max margin loan available |
| `borrow(coin, amount)` | coin name, quantity | (status, transaction) | Borrow funds on margin |
| `repay(coin, amount)` | coin name, quantity | (status, amount_repaid) | Repay margin loan |

## Data Flow

### Candle Fetching Flow

```
Robot / Trainer
    ↓
LiveData.build_candles()
    ↓
stock.item.get_candles_history()
    ↓
BinanceClient.get_historical_klines()
    ↓
Binance API (GET /api/v3/klines)
    ↓
Raw OHLCV array
    ↓
Pandas DataFrame (one per timeframe)
    ↓
Resample to derived timeframes (7m from 1m, 9m from 3m, etc.)
    ↓
Return: Dict[timeframe_minutes → DataFrame]
```

### Order Placement Flow

```
Robot.trade_action()
    ↓
stock.item.trade(BUY/SELL, price, amount)
    ↓
Validate amount against symbol limits
    ↓
BinanceClient.create_margin_order()
    ↓
Binance API (POST /sapi/v1/margin/order)
    ↓
Return orderId, status
    ↓
LiveOrderTracker.set_order_id(side, order_id)
```

### Order Status Monitoring Flow

```
Robot.update_position() (polling loop)
    ↓
stock.item.order_info(order_id)
    ↓
BinanceClient.get_margin_order()
    ↓
Binance API (GET /sapi/v1/margin/order)
    ↓
Parse status (NEW, PARTIALLY_FILLED, FILLED, CANCELED, etc.)
    ↓
Update Position fill state
    ↓
Repeat until FILLED or CANCELED
```

### Order Cancellation Flow

```
Robot.cancel_position()
    ↓
stock.item.cancel_order(order_id)
    ↓
BinanceClient.cancel_margin_order()
    ↓
Binance API (DELETE /sapi/v1/margin/order)
    ↓
If status == PENDING_CANCEL, poll order_info() until CANCELED
    ↓
Return success/failure
```

## Execution Flow

### Candle Fetching: Step-by-Step

1. **Request**: Robot or LiveData calls `stock.item.get_candles_history(time_list=[1,5,15,60,240,1440], coin="link", time_point=0)`
2. **Binance API Calls**: For each required base interval (1-min, 15-min, 1-hour, 12-hour):
   - Fetch historical klines via `BinanceClient.get_historical_klines(symbol="LINKUSDT", interval, lookback_period)`
   - Weight counter incremented by 2 per call
3. **DataFrame Construction**: Parse raw kline data into Pandas DataFrame with columns:
   - `open_time`, `open`, `high`, `low`, `close`, `volume`, `close_time`, `qav` (quote asset volume), `num_trades`, `taker_base_vol`, `taker_quote_vol`, `ignore`
4. **Index & Fill**: Convert Unix timestamps to datetime index, forward-fill missing data (zero-volume candles)
5. **Resampling**: Aggregate base timeframes to derived intervals:
   - From 1-min: create 7-min, 9-min, 12-min, 18-min, 21-min, 24-min, 27-min
   - From 15-min: create 45-min, 75-min, 90-min, 105-min, 135-min, 165-min
   - From 1-hour: create 2-hour, 3-hour, 4-hour, 5-hour, 6-hour, etc.
   - From 12-hour: create 1-day, 2-day, up to 30-day intervals
   - Aggregation: `{'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}`
6. **Trim & Return**: Keep last 120 candles per interval, return as dict keyed by minutes

### Order Placement: Step-by-Step

1. **Validation**: Check amount against symbol LOT_SIZE and MIN_NOTIONAL filters via `is_invalid_amount()`
2. **Formatting**: Round amount and price to Binance precision (e.g., 0.2f for amount, 0.2f for price)
3. **Request**: Call `BinanceClient.create_margin_order()`
   - Symbol: pair in uppercase (e.g., "LINKUSDT")
   - Side: BUY or SELL
   - Type: LIMIT order with GTC (Good-Till-Cancelled)
   - Quantity: formatted amount
   - Price: formatted price
   - Weight: +6 per call
4. **Response**: Receive orderId, status (NEW), and metadata
5. **Return**: Status flag and dict with `order_id` key

### Order Monitoring: Step-by-Step

1. **Poll Loop**: Robot calls `stock.item.order_info(order_id)` every 1-2 seconds
2. **Binance Query**: Fetch order via `BinanceClient.get_margin_order()`
   - Weight: +10 per call
3. **Status Parsing**: Map Binance status constants to internal enums:
   - `ORDER_STATUS_NEW` → "new"
   - `ORDER_STATUS_PARTIALLY_FILLED` → "partially_filled"
   - `ORDER_STATUS_FILLED` → "filled"
   - `ORDER_STATUS_CANCELED` → "canceled"
   - `ORDER_STATUS_PENDING_CANCEL` → "pending_cancel"
   - `ORDER_STATUS_REJECTED` → "rejected"
   - `ORDER_STATUS_EXPIRED` → "expired"
4. **Fill Calculation**: Extract `origQty` and `executedQty` to compute remaining amount
5. **Decision**: Robot checks status and either:
   - Continues waiting if NEW or PARTIALLY_FILLED
   - Processes filled quantity if FILLED
   - Retries cancellation if PENDING_CANCEL
   - Fails and logs if REJECTED or EXPIRED

### Order Cancellation: Step-by-Step

1. **Request**: Robot calls `stock.item.cancel_order(order_id)` when stop-loss or exit signal triggers
2. **Binance Call**: `BinanceClient.cancel_margin_order()`
   - Weight: +10 per call
3. **Response Check**: Examine returned status field
4. **Poll if Pending**: If status == PENDING_CANCEL:
   - Sleep 2 seconds, then poll `order_info()` up to 10 times
   - Continue until status becomes CANCELED
5. **Return**: Status flag; Robot proceeds with position closure

## Key Components

### StockInterface (Abstract Base)

**File**: `stocks/base_stock.py`

**Purpose**: Defines the contract that all exchange implementations must satisfy.

**Key Attributes**:
- `stock_name` (str) — exchange identifier (e.g., "binance", "kraken")
- `key`, `secret` (str) — API credentials (empty in base)
- `coin`, `coin_base` (str) — current pair (e.g., "link", "usdt")
- `fee` (float) — trading fee (0.001 = 0.1%)
- `weight`, `weight_set_time` (int, float) — API rate-limit tracking for Binance
- `overflow_weight`, `overflow_weight_time` (int, float) — thresholds for rate-limit backoff
- `was_init` (bool) — initialization flag

**Key Methods** (abstract, print "INIT STOCK" and return empty/default):
- `depth(qnt)` — fetch order book
- `get_candles_history(time_list, coin, time_point)` — fetch OHLCV
- `trade(pair, type, price, amount)` — place order
- `buy()`, `sell()`, `cancel_order()`, `order_info()` — legacy aliases
- `info()` — account status
- `is_amount_valid()` — validate order size
- `set_operation_sleep()` — rate-limit backoff helper

**Legacy Methods** (deprecated, present for backward compatibility):
- `get_cryptocompare_history()` — fetch from CryptoCompare API (not used)
- `get_cryptowatch_history()` — fetch from Cryptowatch API (not used)

### Stock_Binance (Concrete Implementation)

**File**: `stocks/binance_stock.py`

**Purpose**: Implements StockInterface for Binance, handling all API interactions.

**Key Attributes** (from environment):
- `stock_name` = "binance"
- `instance` (BinanceClient) — initialized with `BINANCE_API_KEY` and `BINANCE_API_SECRET` env vars
- `fee`: Read from `EXCHANGE_FEE` environment variable at init — never hardcoded. If `EXCHANGE_FEE` is absent the constructor must fail loudly (no silent fallback)
- `overflow_weight` = 5000 (Binance rate-limit weight threshold)
- `overflow_weight_time` = 60 (seconds to wait when weight exceeded)

**Key Methods**:

1. **get_candles_history(time_list, coin, time_point=0)**
   - Calls Binance API for 1-min, 15-min, 1-hour, 12-hour klines
   - Builds DataFrames from raw data
   - Resamples to all required timeframes
   - Returns dict keyed by minutes

2. **depth(qnt)**
   - Calls `BinanceClient.get_order_book(symbol, limit=qnt)`
   - Filters by qnt: <100 (weight +5), <500 (+25), <1000 (+50), <5000 (+250)
   - Returns (asks_df, bids_df) with cumulative sums

3. **trade(type, price, amount, force=False)**
   - Validates order size via symbol info
   - Creates margin order via `create_margin_order()`
   - Returns (STATUS_SUCCESS/FAIL, dict with order_id)

4. **cancel_order(order_id)**
   - Calls `cancel_margin_order()`
   - If PENDING_CANCEL, polls `order_info()` up to 10 times
   - Returns (status, response_dict)

5. **order_info(order_id)**
   - Calls `get_margin_order()`
   - Maps Binance status to internal enum
   - Extracts origQty and executedQty
   - Returns (status, dict with `status`, `start_amount`, `left_amount`, `rate`)

6. **info()**
   - Calls `get_account_status()`
   - Returns account status object

7. **is_invalid_amount(amount, price)**
   - Queries symbol info for LOT_SIZE and MIN_NOTIONAL filters
   - Checks: amount >= 2*MINIMUM_ORDER_SIZE AND amount*price >= 2*MINIMUM_NOTIONAL
   - Returns boolean (True if invalid)

8. **Margin-Specific Methods**:
   - `funds(coin, asset_type="free")` — query balance for coin (from margin account)
   - `get_aviable_loan(coin)` — max margin loan available
   - `borrow(coin, amount)` — borrow coins on margin
   - `repay(coin, amount)` — repay margin loan with safety checks

9. **Utility Methods**:
   - `get_pair_name()` — returns symbol in uppercase (e.g., "LINKUSDT")
   - `get_symbol_info(pair_name)` — fetch Binance symbol metadata
   - `set_operation_sleep()` — implement backoff if weight threshold exceeded

### StockHolder (Singleton Wrapper)

**File**: `stocks_holder.py`

**Purpose**: Provides a module-level singleton instance of the currently active stock implementation, allowing global access via `stock_holder.item`.

**Class**: `StockHolder`
- **Class Attribute**: `item` (StockInterface) — initialized to a default StockInterface("","","")
- **Constructor**: If `item.was_init` is False, reinitializes with new StockInterface()
- **Access Pattern**: Global `stock_holder` instance created at module level

**Global Instance**:
```python
stock_holder = StockHolder()
```

**Initialization Function**: `do_stock_init(stock_name)`
- Accepts: "binance", "mock_binance", "mock"
- Replaces `stock_holder.item` with the appropriate implementation
- For "binance": creates Stock_Binance() and initializes from env vars
- For "mock_binance": creates Stock_MockBinance() for testing
- For "mock": creates Stock_Mock() with mock funds setup

**Initialization Contract (critical):**
- `do_stock_init()` **must be called once at process startup** before any other component accesses `stock.item`
- Accessing `stock.item` before `do_stock_init()` leaves `item` as an uninitialized `StockInterface()` — calls will silently no-op rather than raise
- Guard: components that depend on `stock.item.fee` (Robot, Position, StrategyManager) must receive `fee` as a constructor parameter from the caller that invokes `do_stock_init()` — never import and read `stock.item.fee` at module load time

**Usage Throughout System**:
```python
# In robot.py, data.py, position/base_position.py, etc.
from stocks_holder import stock_holder as stock

# Access current exchange
stock.item.get_candles_history([1, 15, 60], "link")
stock.item.trade(TRADE_BUY, 50.0, 1.5)
stock.item.order_info(order_id)
```

## Existing Approach

### API Credentials & Authentication

- Credentials loaded from environment variables: `BINANCE_API_KEY` and `BINANCE_API_SECRET`
- Passed directly to `BinanceClient()` constructor during `Stock_Binance.__init__()`
- No credential storage in code; fully external

### API Protocol & Data Fetching

- **REST API Only**: No WebSocket connections (legacy limitation)
- **Polling-Based**: Candle fetching requests historical data in batches
- **Lookback Periods**: Hardcoded in get_candles_history():
  - 1-min klines: 10 hours ago
  - 15-min klines: 4 days ago
  - 1-hour klines: 43 days ago
  - 12-hour klines: 121 days ago
- **Caching**: No caching layer; every call hits Binance

### Order Execution

- **Order Type**: Limit orders only (no market orders in current implementation)
- **Time-in-Force**: GTC (Good-Till-Cancelled) — orders remain active until filled or cancelled
- **Account Type**: Margin account (not standard spot account)
  - Uses `create_margin_order()`, `get_margin_order()`, `cancel_margin_order()`
  - Supports borrow/repay for short selling
  - Requires position and collateral checks
- **Order Precision**: Formatted to 2 decimal places (hardcoded for USDT base)

### Rate Limit Management

- **Weight System**: Each API call has a "weight" cost; 1200-weight limit per minute
- **Tracking**: `self.weight` increments per call:
  - Candle fetch: +2 per interval
  - Depth query: +5 to +250 depending on depth
  - Trade: +6
  - Cancel: +10
  - Order info: +10
  - Account info: +1
- **Backoff**: If weight > 5000, sleep 60 seconds and reset counter
- **Logging**: Weight logged after each operation via `log_stock(operation_name, weight)`

### Single Symbol Operation

- One symbol per `Stock_Binance` instance
- Coin and base selected at runtime: `stock.item.coin = "link"`, `stock.item.coin_base = "usdt"`
- Pair name derived in `get_pair_name()` as uppercase concatenation: "LINKUSDT"

### Error Handling

- **BinanceRequestException**: Network/connection errors (logged, retry with 60-second sleep)
- **BinanceAPIException**: API errors (status code + message logged)
- **Traceback**: Full stack trace printed for debugging

## Potential Improvements

1. **WebSocket Integration**
   - Replace polling for market data with WebSocket streams
   - Implement depth update stream (`@depth@100ms`) for order book
   - Implement kline stream for real-time candles
   - Reduce API weight consumption

2. **Order Type Flexibility**
   - Support market orders (execute immediately at best price)
   - Implement stop-loss orders on exchange (reduce fill risk)
   - Support post-only orders (maker-only, avoid taker fees)
   - Support conditional orders (stop-market, stop-limit)

3. **Batch Order Operations** (do not implement until specifically approved)
   - Place multiple orders in single API call
   - Implement OCO (One-Cancels-Other) for stop/take-profit pairs
   - Cancel multiple orders in parallel

4. **Rate Limit Management**
   - Implement token bucket algorithm for smooth rate limiting
   - Cache symbol info instead of querying every trade
   - Batch order info queries (request multiple order statuses in one call)
   - Monitor rate limit via exchange headers (X-MBX-USED-WEIGHT)

5. **Retry Logic & Circuit Breaker**
   - Exponential backoff on transient failures
   - Circuit breaker pattern for API endpoints
   - Jitter to prevent thundering herd on recovery

6. **Multi-Symbol Support**
   - Track multiple symbols in single instance
   - Aggregate candles from multiple symbols
   - Support portfolio-level operations

7. **Data Persistence & Caching**
   - Cache OHLCV data locally to avoid redundant API calls
   - Persist candle history to disk for faster startup
   - Implement incremental updates (fetch only new candles)

8. **Extended Account Features**
   - Streaming account updates (balances, fills) via WebSocket
   - Portfolio value calculations
   - Unrealized PnL per position
   - Borrow/repay optimization

9. **Logging & Observability**
   - Structured logging with timestamps and severity
   - Metrics collection (API latency, weight usage, error rates)
   - Distributed tracing for order lifecycle
   - Alert on rate limit approaches

10. **Testing & Mocking**
    - Expand mock implementations (Stock_MockBinance, Stock_Mock)
    - Record/replay API responses for deterministic tests
    - Chaos testing (simulate API failures, delays, partial fills)
    - Property-based testing of rate limit logic

11. **Multi-Exchange Support**
    - Implement Kraken, Bitstamp, Coincheck, Bitmex, OKX, KuCoin adapters
    - Unified pair naming across exchanges
    - Cross-exchange order routing
    - Price aggregation and arbitrage detection

12. **Performance Optimization**
    - Lazy load client libraries (defer binance-python-api import)
    - Connection pooling for HTTP requests
    - Async/await for parallel API calls
    - Memory-efficient candle storage (use numpy arrays instead of DataFrames for large histories)
