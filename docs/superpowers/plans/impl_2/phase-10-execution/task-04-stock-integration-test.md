# Task 04: Stock Operations Integration Test

**Phase:** 10 — Execution  
**Depends on:** Task 01 (LiveOrderTracker), Task 03 (Robot order management), Phase 01 Task 04 (StockHolder + Stock_MockBinance)  
**Produces:** `tests/integration/test_stock_operations.py` — verifies full order lifecycle via Stock_MockBinance

---

## Goal

Verify that all stock operations used by Robot and LiveOrderTracker work correctly end-to-end: order placement, fill detection, cancellation, margin borrow/repay, and fund queries. Uses `Stock_MockBinance` — no real Binance credentials required.

---

## Context

Unit tests cover Position and signal logic in isolation. This test covers the execution bridge: the path from Robot dispatching an order through LiveOrderTracker to stock interface and back. Catches interface mismatches (wrong arg order, missing params, wrong return parsing) that unit tests miss.

---

## Files

- Create: `tests/integration/test_stock_operations.py`
- Create: `tests/integration/__init__.py` (empty, if not exists)

---

## Test Cases

### 1 — Order placement and fill detection (LONG)

```python
def test_order_place_and_fill_long():
    from stocks_holder import do_stock_init, stock_holder as stock
    from position.position import Position
    from robots.live_order_tracker import LiveOrderTracker
    from constants import STATUS_SUCCESS, TRADE_BUY, TRADE_SELL

    do_stock_init('mock_binance')

    pos = Position(fee=0.001)
    pos.full_position = 1000.0
    tracker = LiveOrderTracker(position=pos, stock=stock.item, persist_path='/tmp/test_integration.json')

    # Place buy order
    status, result = stock.item.trade(TRADE_BUY, 20.0, 50.0)
    assert status == STATUS_SUCCESS
    order_id = result["order_id"]
    assert order_id != ""

    tracker.set_buy_order(order_id)
    assert tracker.buy_id == order_id

    # Check fill
    status, fill = tracker.check_fill(order_id)
    assert status == STATUS_SUCCESS
    assert fill["status"] == "FILLED"
    assert fill["start_amount"] > 0
    assert fill["left_amount"] == 0.0
    assert fill["rate"] > 0.0

    coin_amount = fill["start_amount"] - fill["left_amount"]
    print(f"test_order_place_and_fill_long ok — filled {coin_amount} coins at {fill['rate']}")
```

### 2 — Order cancellation

```python
def test_order_cancel():
    from stocks_holder import do_stock_init, stock_holder as stock
    from position.position import Position
    from robots.live_order_tracker import LiveOrderTracker
    from constants import STATUS_SUCCESS, TRADE_BUY

    do_stock_init('mock_binance')

    pos = Position(fee=0.001)
    tracker = LiveOrderTracker(position=pos, stock=stock.item, persist_path='/tmp/test_cancel.json')

    status, result = stock.item.trade(TRADE_BUY, 20.0, 50.0)
    assert status == STATUS_SUCCESS
    tracker.set_buy_order(result["order_id"])

    tracker.cancel_buy()
    assert tracker.buy_id == ""
    print("test_order_cancel ok")
```

### 3 — Margin borrow and repay (SHORT)

```python
def test_margin_borrow_repay():
    from stocks_holder import do_stock_init, stock_holder as stock
    from constants import STATUS_SUCCESS

    do_stock_init('mock_binance')

    status, amount = stock.item.borrow("LINK", 10.0)
    assert status == STATUS_SUCCESS
    assert amount > 0

    status, repaid = stock.item.repay("LINK", amount)
    assert status == STATUS_SUCCESS
    print(f"test_margin_borrow_repay ok — borrowed {amount}, repaid {repaid}")
```

### 4 — Fund query

```python
def test_funds_query():
    from stocks_holder import do_stock_init, stock_holder as stock
    from constants import STATUS_SUCCESS

    do_stock_init('mock_binance')

    status, free = stock.item.funds("USDT", "free")
    assert status == STATUS_SUCCESS
    assert free >= 0.0

    status, locked = stock.item.funds("USDT", "locked")
    assert status == STATUS_SUCCESS
    print(f"test_funds_query ok — free: {free}, locked: {locked}")
```

### 5 — LiveOrderTracker JSON persist/load roundtrip

```python
def test_tracker_persist_load():
    import os
    from stocks_holder import do_stock_init, stock_holder as stock
    from position.position import Position
    from robots.live_order_tracker import LiveOrderTracker
    from constants import STRATEGY_ACTION_OPEN_LONG

    do_stock_init('mock')
    path = '/tmp/test_tracker_roundtrip.json'

    pos = Position(fee=0.001)
    pos.full_position = 1000.0
    pos.open(STRATEGY_ACTION_OPEN_LONG, [20.0], [21.0], 19.0, 15, None)

    tracker = LiveOrderTracker(position=pos, stock=stock.item, persist_path=path)
    tracker.set_buy_order("order-abc")
    tracker.set_loan("loan-001", 500.0)

    # Reconstruct from JSON
    pos2 = Position(fee=0.001)
    pos2.full_position = 1000.0
    tracker2 = LiveOrderTracker(position=pos2, stock=stock.item, persist_path=path)
    loaded = tracker2.load()

    assert loaded == True
    assert tracker2.buy_id == "order-abc"
    assert tracker2.loan_id == "loan-001"
    assert tracker2.loan_amount == 500.0

    tracker2.clear()
    assert not os.path.exists(path)
    print("test_tracker_persist_load ok")
```

---

## Running All Tests

```bash
docker compose run --rm trader python3 -m pytest tests/integration/test_stock_operations.py -v
```

Or run individually:

```bash
docker compose run --rm trader python3 -c "
import tests.integration.test_stock_operations as t
t.test_order_place_and_fill_long()
t.test_order_cancel()
t.test_margin_borrow_repay()
t.test_funds_query()
t.test_tracker_persist_load()
print('all stock integration tests passed')
"
```

---

## Key Constraints

- All tests use `Stock_MockBinance` or `Stock_Mock` — no real Binance credentials or network
- `Stock_MockBinance` requires `tests/fixtures/mock_candles.pkl` — generate per Phase 01 Task 04 fixture instructions if missing
- `borrow()` / `repay()` on `Stock_MockBinance` return safe defaults — if not implemented, add minimal mock response per Phase 01 Task 04 pattern
- Tests are independent — each calls `do_stock_init()` fresh; no shared state between tests

---

## Commit

`test: add stock operations integration tests for order lifecycle and margin`
