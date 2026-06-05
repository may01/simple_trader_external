# Task 03: Robot Order Management

**Phase:** 10 — Execution  
**Depends on:** Task 02 (Robot polling loop), Task 01 (LiveOrderTracker), Phase 06 (Position)  
**Produces:** additions to `robots/robot.py` — order placement, fill processing, stop-loss management

---

## Goal

Implement Robot's order management methods: `_open_position()`, `_close_position()`, `_stop_loss()`, and fill-check logic. These complete the Robot implementation started in Task 02.

---

## Context

Order management is the most complex Robot concern: place order → track ID → poll for fill → record fill → advance position state. Each step is guarded against stale orders, partial fills, and race conditions. All exchange calls go through `StockInterface` — no direct Binance API calls in Robot.

---

## Files

- Modify: `robots/robot.py` (add methods to Robot class)

---

## Interface

**`_open_position(data_point, strategy_action: int, open_prices: list, close_prices: list, stop_price: float, tf: int) -> None`**
- Calls `position.open(...)` — if returns False (already open), skip
- Places entry order via `stock.trade(action, symbol, amount, price)`
- Calls `tracker.set_buy_order(order_id)` (long) or `tracker.set_sell_order(order_id)` (short)

**`_close_position(data_point, strategy_action: int, close_prices: list, stop_price: float, tf: int) -> None`**
- Calls `position.close(...)`
- Cancels existing open order if present (`tracker.cancel_buy()` or `tracker.cancel_sell()`)
- Places exit order via `stock.trade()`
- Calls `tracker.set_sell_order()` (long exit) or `tracker.set_buy_order()` (short exit)

**`_stop_loss(data_point) -> None`**
- Cancels all open orders
- Places market close order at current price
- Calls `position.record_exit_fill()` when fill confirmed
- Calls `_do_finalize_action()`

**`_process_executed_orders(data_point) -> None`**
- Called from `wait()` each tick
- Checks `tracker.buy_id` and `tracker.sell_id` for fills via `tracker.check_fill()`
- On entry fill: calls `position.record_entry_fill(coin_amount, price)`
- On exit fill: calls `position.record_exit_fill(coin_amount, price)`, then `_do_finalize_action()`

**`_place_valid_order(action: int, symbol: str, amount: float, price: float) -> str`**
- Validates price is reasonable (within 4×fee of current price — uses `position.check_stop_open()` logic)
- Calls `stock.trade(action, symbol, amount, price)`
- Returns order ID

**`_do_finalize_action() -> None`**
- Calls `position.finalize()` → `(revenue_pct, revenue_abs)`
- Calls `tracker.clear()`
- Logs trade result

**`_stop_loss_cancel_actions() -> None`**
- If `position.is_stop_loss_triggered(cur_price)`: calls `_stop_loss()`
- If `position.close_by_time(cur_time)`: calls `_close_position()` at current price

---

## Key Constraints

- All `stock.trade()` calls wrapped in try/except — failed order placement logs error, does NOT crash Robot
- Partial fills: `record_entry_fill()` may be called multiple times — `Position` accumulates partial fills
- `_place_valid_order()` checks `check_stop_open()` before placing — stale price cancels order attempt
- Entry order placed as LIMIT, stop-loss as MARKET
- Margin loan: for SHORT, `stock.margin_borrow()` called before sell; `stock.margin_repay()` called after buy-back fill

---

## Verification

```bash
docker compose run --rm trader python3 -c "
from robots.robot import Robot
import inspect
methods = [m for m in dir(Robot) if not m.startswith('__')]
assert '_open_position' in methods
assert '_close_position' in methods
assert '_stop_loss' in methods
assert '_do_finalize_action' in methods
print('robot order management methods ok:', methods)
"
```

---

## Commit

`feat: implement Robot order management with fill polling and stop-loss enforcement`
