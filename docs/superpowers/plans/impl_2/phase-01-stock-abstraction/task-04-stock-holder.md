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
- Create: `tests/fixtures/mock_candles.pkl` — sample fixture (see Fixture Requirements below)

---

## Interface — stocks_holder.py

**StockHolder class:**
- `__init__()` — sets `self.item = StockInterface("", "", "", "")` as instance attribute

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
- `__init__()` — loads `tests/fixtures/mock_candles.pkl` (raises `FileNotFoundError` if missing); sets `fee = 0.001`, `was_init = True`
- `get_candles_history(time_list, coin, time_point=0)` → filters loaded fixture dict to requested `time_list` keys; returns `dict[int, pd.DataFrame]`
- `trade(...)` → records call, returns `(STATUS_SUCCESS, {"order_id": "mock-001"})`
- `order_info(...)` → returns `(STATUS_SUCCESS, {"status": "FILLED", "start_amount": amount, "left_amount": 0.0, "rate": price})`
- `cancel_order(...)` → returns `(STATUS_SUCCESS, {"status": "CANCELED", "start_amount": 0.0, "left_amount": 0.0, "rate": 0.0})`
- `funds(coin, asset_type)` → returns `(STATUS_SUCCESS, 10000.0)` for base, `(STATUS_SUCCESS, 0.0)` for coin
- All other methods → return safe defaults

**Purpose:** Integration tests and local development without Binance credentials.

---

## Fixture Requirements

**Path:** `tests/fixtures/mock_candles.pkl`

**Format:** `dict[int, pd.DataFrame]` — same schema as real `get_candles_history()` output:
- Keys: all supported TFs in integer minutes — `{1, 5, 15, 60, 240, 1440}`
- Each DataFrame: 120 rows, datetime index, columns `open_time`, `open`, `high`, `low`, `close`, `volume`, `close_time`, `qav`, `num_trades`, `taker_base_vol`, `taker_quote_vol`, `ignore`, all numeric columns `float64`

**Generating the sample fixture:**
```bash
# Run once with real Binance credentials to capture a snapshot
docker compose run --rm live python3 -c "
import pickle
from stocks_holder import do_stock_init, stock_holder as stock
do_stock_init('binance')
result = stock.item.get_candles_history([1, 5, 15, 60, 240, 1440], 'link')
with open('tests/fixtures/mock_candles.pkl', 'wb') as f:
    pickle.dump(result, f)
print('fixture saved, keys:', list(result.keys()))
"
```

Commit `tests/fixtures/mock_candles.pkl` to the repository. Update when the candle schema changes.

---

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
- `Stock_MockBinance` loads fixture from `tests/fixtures/mock_candles.pkl` at construction — `FileNotFoundError` if missing; generate with the script in Fixture Requirements
- Fixture schema must match real `get_candles_history()` output exactly — regenerate when candle schema changes
- Do NOT create multiple `StockHolder` instances — it is a true module-level singleton

---

## Verification

```bash
docker compose run --rm simulate python3 -c "
from stocks_holder import do_stock_init, stock_holder as stock
# Before init: no-op
result = stock.item.get_candles_history([1], 'link')
assert result == {}

# After mock init
do_stock_init('mock')
assert stock.item.was_init == True
assert stock.item.fee == 0.001
status, info = stock.item.trade('TRADE_BUY', 20.0, 5.0)
assert status == 'STATUS_SUCCESS'
print('stock holder ok')
"
```

---

## Commit

`feat: add StockHolder singleton and mock implementations`
