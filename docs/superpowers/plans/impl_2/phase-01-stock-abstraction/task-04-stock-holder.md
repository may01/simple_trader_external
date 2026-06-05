# Task 04: StockHolder Singleton + Mock Implementations

**Phase:** 01 — Stock Abstraction  
**Depends on:** Task 03 (BinanceStock orders)  
**Produces:** `stocks_holder.py`, `stocks/mock_stock.py` — module-level singleton access + test mocks

---

## Goal

Implement `StockHolder`, the module-level singleton wrapper, plus `Stock_MockBinance` and `Stock_Mock` test implementations. After this task, any module can `from stocks_holder import stock_holder as stock` and call `stock.item.*`.

---

## Context

`do_stock_init(stock_name)` is called once at process startup. It replaces the default uninitialized `StockInterface` with the real implementation. All consuming modules import `stock_holder` and access `stock_holder.item` — they never instantiate `Stock_Binance` directly. Mock implementations enable testing without a real Binance connection.

---

## Files

- Create: `stocks_holder.py`
- Create: `stocks/mock_stock.py`

---

## Interface — stocks_holder.py

**StockHolder class:**
- `item: StockInterface` — class attribute, initialized to `StockInterface("", "", "")`
- `__init__()` — if `item.was_init` is False, reinitialize with new default `StockInterface()`

**Module-level singleton:**
- `stock_holder = StockHolder()` — created at module load

**`do_stock_init(stock_name: str) -> None`:**
- Accepts: `"binance"`, `"mock_binance"`, `"mock"`
- `"binance"` → creates `Stock_Binance()`, sets `stock_holder.item`
- `"mock_binance"` → creates `Stock_MockBinance()` for integration tests with fake candle data
- `"mock"` → creates `Stock_Mock()` with pre-seeded funds for unit tests
- Must be called BEFORE any other module accesses `stock_holder.item`

---

## Interface — Stock_MockBinance

Extends `StockInterface`. Overrides:
- `get_candles_history(...)` → returns pre-loaded DataFrame fixtures (not real Binance calls)
- `trade(...)` → records call, returns `(STATUS_SUCCESS, {"order_id": "mock-001"})`
- `order_info(...)` → returns `(STATUS_SUCCESS, {"status": "filled", "start_amount": amount, "left_amount": 0.0, "rate": price})`
- `cancel_order(...)` → returns `(STATUS_SUCCESS, {})`
- `funds(coin, asset_type)` → returns `(STATUS_SUCCESS, 10000.0)` for base, `(STATUS_SUCCESS, 0.0)` for coin
- All other methods → return safe defaults

**Purpose:** Integration tests and local development without Binance credentials.

---

## Interface — Stock_Mock

Extends `StockInterface`. Minimal mock for unit testing Position, Strategy, Robot in isolation:
- All methods return minimal valid responses
- `fee` set to `0.001`
- `was_init = True`

---

## Key Constraints

- `stock_holder.item` before `do_stock_init()` is an uninitialized `StockInterface()` — calls will no-op (print "INIT STOCK"), not raise — this is intentional behavior
- Components that depend on `stock.item.fee` (Robot, StrategyManager, Position) must receive `fee` as a constructor parameter from the caller that ran `do_stock_init()` — never import `stock.item.fee` at module load time
- `Stock_MockBinance` candle fixtures must have same schema as real `get_candles_history()` output
- Do NOT create multiple `StockHolder` instances — it is a true module-level singleton

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from stocks_holder import do_stock_init, stock_holder as stock
# Before init: no-op
result = stock.item.get_candles_history([1], 'link')
assert result == {}

# After mock init
do_stock_init('mock')
assert stock.item.was_init == True
assert stock.item.fee == 0.001
status, info = stock.item.trade('BUY', 20.0, 5.0)
assert status == 'success'
print('stock holder ok')
"
```

---

## Commit

`feat: add StockHolder singleton and mock implementations`
