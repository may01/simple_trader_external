# Task 01: LiveOrderTracker

**Phase:** 10 — Execution  
**Depends on:** Phase 06 (Position facade), Phase 01 (StockInterface)  
**Produces:** `robots/live_order_tracker.py` — order ID tracking, margin loan management, JSON persistence

---

## Goal

Implement `LiveOrderTracker` — owns all execution-bridge concerns that Position explicitly does NOT: Binance order IDs, margin loan tracking, JSON persistence for crash recovery.

---

## Context

`Position` tracks trade state; `LiveOrderTracker` tracks Binance-side state (buy_id, sell_id, loan amounts). On crash recovery, Robot loads `LiveOrderTracker` from JSON, reconstructs Position state, and resumes from last known point. Separation ensures Position remains testable without exchange connectivity.

---

## Files

- Create: `robots/live_order_tracker.py`

---

## Interface

**`LiveOrderTracker(position: Position, stock: StockInterface, persist_path: str)`**

Attributes:
- `position: Position`
- `stock: StockInterface`
- `buy_id: str` — Binance order ID for current buy order
- `sell_id: str` — Binance order ID for current sell order
- `loan_id: str` — margin loan ID (for short positions)
- `loan_amount: float` — amount borrowed
- `persist_path: str` — JSON file path for state persistence

**`set_buy_order(order_id: str) -> None`**
- Sets `buy_id`, calls `save()`

**`set_sell_order(order_id: str) -> None`**
- Sets `sell_id`, calls `save()`

**`set_loan(loan_id: str, amount: float) -> None`**
- Sets `loan_id`, `loan_amount`, calls `save()`

**`get_loan() -> tuple[str, float]`**
- Returns `(loan_id, loan_amount)`

**`cancel_buy() -> None`**
- Calls `stock.cancel_order(buy_id)`, clears `buy_id`, calls `save()`

**`cancel_sell() -> None`**
- Calls `stock.cancel_order(sell_id)`, clears `sell_id`, calls `save()`

**`check_fill(order_id: str) -> tuple[str, dict]`**
- Calls `stock.order_info(order_id)` — returns `(status, fill_dict)` unchanged
- Callers must check `status == STATUS_SUCCESS` before reading dict; on `STATUS_FAIL` dict is `{}`

**`save() -> None`**
- Serializes `{buy_id, sell_id, loan_id, loan_amount}` + `position.to_dict()` to `persist_path` atomically

**`load() -> bool`**
- Loads JSON from `persist_path` if exists
- Restores own fields, calls `position.from_dict(data)`
- Returns True if loaded successfully, False if file absent

**`clear() -> None`**
- Resets all order IDs (`buy_id = ""`, `sell_id = ""`, `loan_id = ""`, `loan_amount = 0.0`), deletes `persist_path` file if it exists

---

## Key Constraints

- `persist_path` write is always atomic (`.tmp` → rename)
- `buy_id` / `sell_id` initialized to empty string `""` — never None (avoids None checks everywhere)
- `load()` must call `position.from_dict()` — Position reconstructed from same JSON
- After `clear()`, tracker state is reset — `position.posImpl` is `None` because `_do_finalize_action()` already called `position.finalize()` before calling `tracker.clear()`
- Margin loan (`set_loan`) only relevant for SHORT positions — for LONG positions, loan fields remain at defaults

---

## Verification

```bash
docker compose run --rm trader python3 -c "
from robots.live_order_tracker import LiveOrderTracker
from position.position import Position
from stocks_holder import do_stock_init, stock_holder as stock

do_stock_init('mock')
pos = Position(fee=0.001)
tracker = LiveOrderTracker(position=pos, stock=stock.item, persist_path='/tmp/test_tracker.json')
tracker.set_buy_order('order123')
assert tracker.buy_id == 'order123'
print('live_order_tracker ok')
"
```

---

## Commit

`feat: implement LiveOrderTracker with order ID management and JSON crash recovery`
