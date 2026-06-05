# Task 03: BinanceStock — Order Management

**Phase:** 01 — Stock Abstraction  
**Depends on:** Task 02 (BinanceStock candles)  
**Produces:** `stocks/binance_stock.py` — full order lifecycle: place, monitor, cancel, margin operations

---

## Goal

Implement all order management methods on `Stock_Binance`: `trade()`, `order_info()`, `cancel_order()`, `depth()`, `info()`, `funds()`, `get_aviable_loan()`, `borrow()`, `repay()`, `is_invalid_amount()`.

---

## Context

All orders use Binance margin account (`create_margin_order`, `get_margin_order`, `cancel_margin_order`). Orders are LIMIT GTC only. `cancel_order()` polls until status leaves PENDING_CANCEL. Rate weights are tracked per call.

---

## Files

- Modify: `stocks/binance_stock.py`

---

## Interface

**trade(trade_type: str, price: float, amount: float, force: bool = False) -> tuple[str, dict]**
- Validates amount via `is_invalid_amount()`
- Rounds amount and price to 2 decimal places
- Resolves symbol internally via `self.get_pair_name()`
- Creates margin order (LIMIT, GTC)
- Returns `(STATUS_SUCCESS, {"order_id": id})` or `(STATUS_FAIL, {})`
- Weight: +6

**order_info(order_id: str) -> tuple[str, dict]**
- Resolves symbol internally via `self.get_pair_name()`
- Queries `get_margin_order(symbol, order_id)`
- Returns Binance status string directly (no mapping) — values are `Client.ORDER_STATUS_*` constants: `"NEW"`, `"PARTIALLY_FILLED"`, `"FILLED"`, `"CANCELED"`, `"PENDING_CANCEL"`, `"REJECTED"`, `"EXPIRED"`
- Returns `(STATUS_SUCCESS, {"status": s, "start_amount": float, "left_amount": float, "rate": float})` on success, `(STATUS_FAIL, {})` on exception
- Weight: +10

**cancel_order(order_id: str) -> tuple[str, dict]**
- Resolves symbol internally via `self.get_pair_name()`
- Calls `cancel_margin_order(symbol, order_id)`
- If status == `"PENDING_CANCEL"`: polls `order_info()` up to 10 times with 2-second sleep until `"CANCELED"`
- Returns `(STATUS_SUCCESS, {"status": s, "start_amount": float, "left_amount": float, "rate": float})` mirroring `order_info` — final state after cancellation confirmed
- Returns `(STATUS_FAIL, {})` on exception
- Weight: +10

**depth(quantity: int) -> tuple[pd.DataFrame, pd.DataFrame]**
- Resolves symbol internally via `self.get_pair_name()`
- Returns `(asks_df, bids_df)`, each with columns `["price", "quantity", "cumulative"]`, sorted by price, all `float64`
- Weight: +5 (<100), +25 (<500), +50 (<1000), +250 (<5000)

**is_invalid_amount(amount: float, price: float) -> bool**
- Resolves symbol internally via `self.get_pair_name()`
- Queries symbol info for LOT_SIZE and MIN_NOTIONAL filters
- Returns True if invalid: amount < 2×MINIMUM_ORDER_SIZE OR amount×price < 2×MINIMUM_NOTIONAL

**funds(coin: str, asset_type: str = "free") -> tuple[str, float]**
- Queries margin account balance for specific coin
- `asset_type`: `"free"` or `"locked"`
- Coin not found in margin account → `(STATUS_SUCCESS, 0.0)`
- API exception → `(STATUS_FAIL, 0.0)`

**get_aviable_loan(coin: str) -> tuple[str, float]**
- Returns `(STATUS_SUCCESS, available_amount)` or `(STATUS_FAIL, 0.0)`

**borrow(coin: str, amount: float) -> tuple[str, float]**
- Returns `(STATUS_SUCCESS, borrowed_amount)` or `(STATUS_FAIL, 0.0)`

**repay(coin: str, amount: float) -> tuple[str, float]**
- Returns `(STATUS_SUCCESS, repaid_amount)` or `(STATUS_FAIL, 0.0)`

---

## Key Constraints

- All order methods use margin API — NOT spot API
- `trade_type` values are `TRADE_BUY = "TRADE_BUY"` / `TRADE_SELL = "TRADE_SELL"` — `Stock_Binance` maps these to Binance API's `"BUY"` / `"SELL"` internally
- Price formatted to 2 decimal places (hardcoded for USDT base pairs)
- `is_invalid_amount()` checks `2×minimum` to ensure both entry and exit can meet minimums
- `cancel_order()` must handle PENDING_CANCEL with retry loop — Binance cancellation is not instant
- All API exceptions (`BinanceRequestException`, `BinanceAPIException`) caught: log full traceback, return `STATUS_FAIL`
- Network timeouts: sleep 60 seconds, then retry
- Mock classes `Stock_MockBinance` and `Stock_Mock` must implement the same interface (Task 04 handles StockHolder + mocks)

---

## Verification

```bash
# Test order validation only (no real order placed)
docker compose run --rm live python3 -c "
from stocks_holder import do_stock_init, stock_holder as stock
do_stock_init('binance')
# is_invalid_amount with tiny amount should return True
result = stock.item.is_invalid_amount(0.0001, 20.0)
print('tiny amount invalid:', result)
# depth query
asks, bids = stock.item.depth(100)
print('depth rows:', len(asks), len(bids))
"
```

---

## Commit

`feat: implement Stock_Binance order management methods`
