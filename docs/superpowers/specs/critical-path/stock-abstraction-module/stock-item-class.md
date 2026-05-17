# StockItem Class Specification

## Class Overview

The **StockItem** class (implemented as `StockHolder`) serves as a singleton wrapper providing module-level access to the stock abstraction layer. It acts as the bridge between the Robot, Data, and Position classes and the underlying exchange implementation (BinanceStock or mock implementations). Rather than injecting the stock instance as a dependency throughout the codebase, StockItem maintains a single, globally-accessible instance that can be initialized once and reused everywhere.

The key design philosophy is simplicity and convenience: all trading logic accesses the current exchange via `stock_holder.item` without needing constructor parameters or dependency injection frameworks. This pattern allows the system to switch between live Binance trading, testnet, and mock implementations by calling a single initialization function (`do_stock_init(stock_type)`) at startup.

StockItem is a **stateless delegation wrapper**—it does not add logic, caching, or additional state management. It purely forwards method calls to the underlying stock implementation, making it invisible to callers. All error handling, rate limiting, and API logic remain in the concrete implementation (Stock_Binance or mock).

## Key Attributes

| Attribute | Type | Purpose |
|-----------|------|---------|
| `item` | StockInterface | The current exchange instance (BinanceStock, MockBinance, or Mock). Class attribute initialized to default StockInterface; replaced by `do_stock_init()`. |
| `was_init` | bool | Initialization flag inherited from StockInterface. Checked during `__init__()` to detect if wrapper has been properly set up. |

## Constructor

### `__init__(self)`

**Purpose**: Initialize the StockHolder singleton wrapper.

**Behavior**:
- Check if the `item` class attribute has been initialized (`item.was_init == True`)
- If not initialized, create a new default `StockInterface()` with empty credentials
- This ensures the singleton pattern: only one instance exists throughout the application lifecycle

**Parameters**: None

**Returns**: None

**Exceptions**: None (graceful fallback to default interface)

**Example**:
```python
from stocks_holder import stock_holder

# At startup, item is a default StockInterface
stock_holder = StockHolder()  # Wrapped in module-level instance

# Later, initialize the actual implementation
do_stock_init("binance")  # Replaces stock_holder.item with Stock_Binance()
```

## Key Methods & Interfaces

All methods in StockItem are **delegation methods**—they forward calls to `self.item` without adding logic. The actual implementation resides in the underlying stock instance (BinanceStock, MockBinance, or Mock).

### Candle Data Methods

#### `get_candles_history(time_list, coin, time_point=0)`

**Delegates to**: `stock.item.get_candles_history()`

**Parameters**:
- `time_list` (list[int]) — timeframes in minutes to fetch (e.g., [1, 5, 15, 60, 240, 1440])
- `coin` (str) — coin name in lowercase (e.g., "link")
- `time_point` (int, optional) — Unix timestamp for "before" filter (0 = fetch latest)

**Returns**: Dict[int, DataFrame]
- Keys: timeframe in minutes (1, 5, 15, 60, 240, 1440, etc.)
- Values: Pandas DataFrame with columns [open, high, low, close, volume, ...]

**Purpose**: Fetch OHLCV candles from Binance for analysis, signal generation, and backtesting.

**Example**:
```python
from stocks_holder import stock_holder as stock

ohlc = stock.item.get_candles_history([1, 5, 15, 60, 240, 1440], "link")
# ohlc[1]    = DataFrame with 1-minute candles
# ohlc[5]    = DataFrame with 5-minute candles
# ohlc[15]   = DataFrame with 15-minute candles
# ohlc[60]   = DataFrame with 1-hour candles
# ohlc[240]  = DataFrame with 4-hour candles
# ohlc[1440] = DataFrame with 1-day candles
```

---

### Order Placement Methods

#### `trade(type, price, amount, force=False)`

**Delegates to**: `stock.item.trade()`

**Parameters**:
- `type` (str or enum) — BUY or SELL
- `price` (float) — limit price for order
- `amount` (float) — quantity to buy or sell
- `force` (bool, optional) — force order even if validation fails (default: False)

**Returns**: (status, response_dict)
- `status` (str) — "success" or "failure"
- `response_dict` (dict) — contains `order_id`, order metadata, error messages if applicable

**Purpose**: Place a new buy or sell limit order on Binance margin account.

**Example**:
```python
status, response = stock.item.trade("BUY", 50.0, 1.5)
if status == "success":
    order_id = response["order_id"]
    print(f"Order {order_id} placed at 50.0 for 1.5 LINK")
else:
    print(f"Order failed: {response}")
```

---

### Order Status & Cancellation Methods

#### `get_order_status(order_id)` / `order_info(order_id)`

**Delegates to**: `stock.item.order_info()` (note: API may use either name)

**Parameters**:
- `order_id` (str or int) — Binance order ID to query

**Returns**: (status, order_info_dict)
- `status` (str) — "success" or "failure"
- `order_info_dict` (dict) — contains:
  - `status` — Binance status (NEW, PARTIALLY_FILLED, FILLED, CANCELED, REJECTED, EXPIRED)
  - `start_amount` — original quantity ordered
  - `left_amount` — quantity still open (not filled)
  - `rate` — execution price
  - Additional metadata from Binance response

**Purpose**: Poll order status during lifecycle (filled, partially filled, pending, cancelled).

**Example**:
```python
status, info = stock.item.order_info("12345678")
if info["status"] == "FILLED":
    filled_amount = info["start_amount"] - info["left_amount"]
    print(f"Order filled: {filled_amount} LINK at {info['rate']}")
elif info["status"] == "PARTIALLY_FILLED":
    print(f"Partial fill, {info['left_amount']} remaining")
```

---

#### `cancel_order(order_id)`

**Delegates to**: `stock.item.cancel_order()`

**Parameters**:
- `order_id` (str or int) — order ID to cancel

**Returns**: (status, response_dict)
- `status` (str) — "success" or "failure"
- `response_dict` (dict) — cancellation result or error details

**Purpose**: Cancel an open order (e.g., during stop-loss or exit signal).

**Implementation Detail**: If Binance returns PENDING_CANCEL status, the underlying implementation polls `order_info()` up to 10 times with 2-second delays to confirm final cancellation.

**Example**:
```python
status, response = stock.item.cancel_order("12345678")
if status == "success":
    print("Order cancelled successfully")
else:
    print(f"Cancellation failed: {response}")
```

---

### Market Data Methods

#### `depth(quantity)` / `get_depth_data(limit)`

**Delegates to**: `stock.item.depth()`

**Parameters**:
- `quantity` (int) — order book depth (e.g., 100, 500, 1000, 5000)

**Returns**: (asks_df, bids_df)
- `asks_df` (DataFrame) — ask orders with columns [price, qnt, sum (cumulative)]
- `bids_df` (DataFrame) — bid orders with columns [price, qnt, sum (cumulative)]

**Purpose**: Fetch current order book snapshot for liquidity analysis or VWAP calculations.

**API Weight Cost**: Varies by depth:
- <100: +5 weight
- <500: +25 weight
- <1000: +50 weight
- <5000: +250 weight

**Example**:
```python
asks, bids = stock.item.depth(100)
# asks[0] = (price, quantity, cumulative_sum)
# bids[0] = (highest_bid_price, quantity, cumulative_sum)
best_ask = asks.iloc[0]["price"]
best_bid = bids.iloc[0]["price"]
spread = best_ask - best_bid
```

---

### Account Methods

#### `get_account_info()` / `info()`

**Delegates to**: `stock.item.info()`

**Parameters**: None

**Returns**: dict or account_status_object
- Contains margin status, available balances, locked balances, borrowing details

**Purpose**: Query account metadata (not used frequently in current implementation).

**API Weight Cost**: +1 per call

**Example**:
```python
account_info = stock.item.info()
margin_status = account_info.get("marginLevel")  # current margin ratio
```

---

#### `get_trading_rules()` / `is_invalid_amount(amount, price)`

**Delegates to**: `stock.item.is_invalid_amount()` or `get_symbol_info()`

**Parameters**:
- `amount` (float) — quantity to trade
- `price` (float) — order price

**Returns**: bool
- True if amount is invalid (fails LOT_SIZE or MIN_NOTIONAL filter)
- False if valid

**Purpose**: Validate order size before placement (prevents rejection from Binance).

**Validation Rules**:
- Amount must be >= 2 × MINIMUM_ORDER_SIZE
- Amount × price must be >= 2 × MINIMUM_NOTIONAL

**Example**:
```python
valid = not stock.item.is_invalid_amount(1.5, 50.0)
if not valid:
    print("Order size too small for LINK_USDT")
```

---

## Singleton Pattern

### Module-Level Instance

The singleton is created at module level in `stocks_holder.py`:

```python
class StockHolder:
    item = StockInterface("", "", "")  # Class attribute
    
    def __init__(self):
        if not self.item.was_init:
            self.item = StockInterface()

stock_holder = StockHolder()  # Global singleton
```

### Access Pattern

Throughout the system, all classes import and use the singleton:

```python
# In robot.py, data.py, position/position.py, etc.
from stocks_holder import stock_holder as stock

# Use anywhere without dependency injection
stock.item.trade("BUY", 50.0, 1.5)
stock.item.get_candles_history([1, 15, 60], "link")
```

### Initialization & Switching

The `do_stock_init(stock_name)` function replaces the singleton instance:

```python
def do_stock_init(stock):
    if stock == "binance":
        stock_holder.item = Stock_Binance()  # Live Binance
    elif stock == "mock_binance":
        stock_holder.item = Stock_MockBinance()  # Testnet mock
    elif stock == "mock":
        stock_holder.item = Stock_Mock()  # Full mock with in-memory funds
        setup_mock_funds(stock_holder.item)
    else:
        log("Unknown stock")
        exit()
    print(stock_holder.item.stock_name)
```

### Thread Safety

**Current Status**: Not thread-safe. Single-threaded execution is assumed (Robot runs in one event loop, Trainer in one main thread).

**Limitations**:
- No locks around `stock_holder.item` access
- No atomic swap during `do_stock_init()`
- If multiple threads access simultaneously, race conditions possible

**If Multi-Threading Required**: Use `threading.Lock()` around reads and writes to `stock_holder.item`.

## Error Handling

### Delegation Approach

StockItem does **not** add error handling. All exceptions are passed through directly from the underlying implementation:

```python
# Example: BinanceStock raises BinanceAPIException
try:
    stock.item.trade("BUY", 50.0, 1.5)
except BinanceAPIException as e:
    print(f"Binance API error: {e.status_code} - {e.message}")
```

### Exception Types

Callers must handle exceptions from the underlying implementation:
- `BinanceRequestException` — network or connection errors
- `BinanceAPIException` — API response errors (invalid amount, insufficient balance, etc.)
- `ValueError` — invalid parameters (e.g., invalid pair format)
- `KeyError` — missing environment variable (BINANCE_API_KEY, BINANCE_API_SECRET)

### Logging

The underlying Stock_Binance logs all operations via `log_stock(operation_name, weight)` to track API weight usage.

## Testability & Mocking

### Replacing the Singleton in Tests

To use a mock in tests, simply replace `stock_holder.item` before running test code:

```python
# In conftest.py or test setUp
import stocks_holder
from stocks.mock_binance_stock import Stock_MockBinance

# Replace the global singleton
stocks_holder.stock_holder.item = Stock_MockBinance()

# Or use a fully custom mock
class MockStock(StockInterface):
    def trade(self, type, price, amount, force=False):
        return ("success", {"order_id": "mock_123"})
    
    def get_candles_history(self, time_list, coin, time_point=0):
        # Return fixture data
        return {1: pd.DataFrame(...), 15: pd.DataFrame(...)}

stocks_holder.stock_holder.item = MockStock()
```

### Mock Interface

Any mock must implement the same public methods as StockInterface:
- `get_candles_history(time_list, coin, time_point=0)`
- `trade(type, price, amount, force=False)`
- `order_info(order_id)`
- `cancel_order(order_id)`
- `depth(quantity)`
- `info()`
- `is_invalid_amount(amount, price)`
- And margin-specific methods: `funds()`, `borrow()`, `repay()`

## Integration Points

### Robot Class

The Robot trading engine uses StockItem for all exchange operations:

```python
# In robot.py
from stocks_holder import stock_holder as stock

class Robot:
    def trade_action(self):
        status, response = stock.item.trade("BUY", self.entry_price, self.amount)
        if status == "success":
            self.position.action_id = response["order_id"]
    
    def update_position(self):
        status, info = stock.item.order_info(self.position.action_id)
        if info["status"] == "FILLED":
            self.position.filled = True
    
    def cancel_position(self):
        stock.item.cancel_order(self.position.action_id)
```

### LiveData Class

`LiveData` fetches candles via StockItem each tick:

```python
# In data.py
from stocks_holder import stock_holder as stock

class LiveData:
    def build_candles(self, time_point: int = 0):
        ohlc = stock.item.get_candles_history(
            self.candles,  # [1, 5, 15, 60, 240, 1440] from candles_config.yaml
            self.coin,
            time_point
        )
```

### Position Class

Position classes read fee and exchange info from StockItem:

```python
# In position/position.py
from stocks_holder import stock_holder as stock

class Position:
    def __init__(self):
        self.fee = stock.item.fee  # 0.001 = 0.1%
    
    def calculate_pnl(self):
        entry_cost = self.entry_price * self.quantity * (1 + self.fee)
        exit_value = self.exit_price * self.quantity * (1 - self.fee)
        return exit_value - entry_cost
```

### Trainer & TrainRobot

Backtesting uses StockItem (typically replaced with Mock):

```python
# In trainer.py
from stocks_holder import stock_holder as stock

# Use do_stock_init("mock") to switch to mock for backtesting
do_stock_init("mock")

robot = TrainRobot()
robot.run()  # Uses stock.item (now mocked)
```

## Existing Implementation Details

### Code Location

**File**: `stocks_holder.py` (root directory)

**Class Definition**:
```python
class StockHolder:
    item = StockInterface("", "", "")
    
    def __init__(self):
        if not self.item.was_init:
            self.item = StockInterface()

stock_holder = StockHolder()

def do_stock_init(stock):
    if stock == "binance":
        stock_holder.item = Stock_Binance()
    if stock == "mock_binance":
        stock_holder.item = Stock_MockBinance()
    if stock == "mock":
        stock_holder.item = Stock_Mock()
        setup_mock_funds(stock_holder.item)
    else:
        log("Unknown stock")
        exit()
    print(stock_holder.item.stock_name)
```

### Imports Across Codebase

**Robot** (`robot.py`):
```python
from stocks_holder import stock_holder as stock
```

**Data** (`data.py`):
```python
from stocks_holder import stock_holder as stock
```

**Position** (`position/base_position.py`, etc.):
```python
from stocks_holder import stock_holder as stock
```

**Trainer** (`trainer.py`):
```python
from stocks_holder import stock_holder as stock, do_stock_init
```

### Configuration

No configuration required beyond environment variables for credentials:
- `BINANCE_API_KEY` — Binance API key (loaded by Stock_Binance)
- `BINANCE_API_SECRET` — Binance API secret (loaded by Stock_Binance)

These are read from the environment during `do_stock_init("binance")`, not from a config file.

## Potential Improvements

1. **Thread-Safe Initialization**
   - Wrap `do_stock_init()` with a lock to prevent race conditions during singleton replacement
   - Use `threading.Lock()` or `contextlib.contextmanager` for safe concurrent access

2. **Lazy Initialization**
   - Defer creation of Stock_Binance and BinanceClient until first use
   - Reduce startup time if StockItem is imported but not used

3. **Multi-Symbol Support**
   - Allow StockItem to manage multiple coin pairs simultaneously
   - Return market data for all pairs in one call
   - Currently: one symbol per instance (`stock.item.coin` set globally)

4. **Dependency Injection Interface**
   - Add optional `inject_stock(instance)` method for cleaner testing
   - Allow explicit dependency passing instead of relying on global singleton
   - Maintains backward compatibility with existing singleton pattern

5. **Caching Layer at Wrapper Level**
   - Cache `get_candles_history()` results to avoid redundant API calls
   - Invalidate cache on time boundaries (e.g., new minute = refresh)
   - Cache trading rules and symbol info (changes rarely)

6. **Rate Limiting Aggregation**
   - Track all weight usage across all API calls
   - Implement request queuing if approaching weight limit
   - Proactive backoff before hitting rate limit threshold

7. **Retry Logic at Wrapper Level**
   - Implement exponential backoff for transient failures
   - Automatically retry failed trades, candle fetches, order status queries
   - Configurable retry count and backoff strategy

8. **Metrics & Observability Hooks**
   - Add hooks for logging API latency, success rates, error rates
   - Track weight consumption per operation type
   - Export metrics for monitoring dashboards

9. **Circuit Breaker Pattern**
   - Detect Binance API outages
   - Fail fast if circuit is open (too many recent failures)
   - Automatic recovery with exponential backoff

10. **Migration to Structured Instance**
    - Replace singleton with dependency injection framework
    - Use constructor injection instead of global imports
    - Better testability and decoupling

11. **Factory Pattern for Multiple Implementations**
    - Create `StockFactory` class to manage instance creation
    - Decouple initialization logic from global state
    - Support version-specific implementations

12. **Async/Await Support**
    - Add async variants of all methods: `async def get_candles_history_async()`
    - Enable parallel API calls for multiple symbols or timeframes
    - Use `asyncio` for non-blocking I/O
