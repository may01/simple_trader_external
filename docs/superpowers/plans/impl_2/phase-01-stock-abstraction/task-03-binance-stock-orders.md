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
- Creates margin order (LIMIT, GTC)
- Returns `(STATUS_SUCCESS, {"order_id": id})` or `(STATUS_FAIL, {})`
- Weight: +6

**order_info(order_id: str) -> tuple[str, dict]**
- Queries `get_margin_order()`
- Maps Binance status → internal status string: `"new"`, `"partially_filled"`, `"filled"`, `"canceled"`, `"pending_cancel"`, `"rejected"`, `"expired"`
- Returns `(status, {"status": s, "start_amount": float, "left_amount": float, "rate": float})`
- Weight: +10

**cancel_order(order_id: str) -> tuple[str, dict]**
- Calls `cancel_margin_order()`
- If status == PENDING_CANCEL: polls `order_info()` up to 10 times with 2-second sleep until CANCELED
- Returns `(STATUS_SUCCESS/FAIL, response_dict)`
- Weight: +10

**depth(quantity: int) -> tuple[pd.DataFrame, pd.DataFrame]**
- Returns `(asks_df, bids_df)` each with cumulative sum column
- Weight: +5 (<100), +25 (<500), +50 (<1000), +250 (<5000)

**is_invalid_amount(amount: float, price: float) -> bool**
- Queries symbol info for LOT_SIZE and MIN_NOTIONAL filters
- Returns True if invalid: amount < 2×MINIMUM_ORDER_SIZE OR amount×price < 2×MINIMUM_NOTIONAL

**funds(coin: str, asset_type: str = "free") -> tuple[str, float]**
- Queries margin account balance for specific coin
- `asset_type`: `"free"` or `"locked"`

**get_aviable_loan(coin: str) -> tuple[str, float]**  
**borrow(coin: str, amount: float) -> tuple[str, object]**  
**repay(coin: str, amount: float) -> tuple[str, float]**
- Standard margin borrow/repay operations

---

## Key Constraints

- All order methods use margin API — NOT spot API
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
docker compose run --rm trader python3 -c "
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
