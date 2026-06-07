# Task 04: Position Facade

**Phase:** 06 — Position Management  
**Depends on:** Task 03 (LongPosition, ShortPosition)  
**Produces:** `position/position.py` — public-facing facade wrapping concrete position implementations

---

## Goal

Implement `Position` — the facade that orchestrates `BasePosition`-derived classes. Provides the unified public API consumed by Robot, TrainRobot, and StrategyManager. Creates `LongPosition` or `ShortPosition` based on the action type received from Strategy.

---

## Context

`Position` is the single entry point for all position lifecycle operations. Robot and TrainRobot call `position.open()`, `position.close()`, `position.record_entry_fill()` etc. — they never interact with `LongPosition`/`ShortPosition` directly. Execution-bridge concerns (order IDs, margin loans, JSON persistence) live in `LiveOrderTracker` (Phase 10), NOT in Position.

---

## Files

- Create: `position/position.py`

---

## Interface

**`Position(thread_num: int = 0, fee: float = 0.0)`**

Attributes:
- `posImpl: BasePosition | None` — current concrete implementation; `None` when no position is open
- `fee: float` — injected, used when creating LongPosition/ShortPosition
- `thread_num: int`
- `full_position: float = 10000.0`

**Methods:**

`open(strategy_action: int, price_open: list[float], price_close: list[float], price_stop_loss: float, time_period: int, action_msg) -> bool`
- If `strategy_action == STRATEGY_ACTION_OPEN_LONG`: creates `LongPosition(fee, thread_num, full_position)`, calls `posImpl.open(...)`
- If `strategy_action == STRATEGY_ACTION_OPEN_SHORT`: creates `ShortPosition(fee, thread_num, full_position)`, calls `posImpl.open(...)`
- Returns False if already have open position

`close(strategy_action: int, price_close: list[float], price_stop_loss: float, time_period: int, action_msg) -> None`
- Delegates to `posImpl.close(...)`

`set_stop_loss(price: float, action_msg, force: bool = False) -> bool`
- Delegates to `posImpl.set_stop_loss(price, action_msg, force)`

`record_entry_fill(coin_amount: float, price: float) -> None`
- Delegates to `posImpl.record_entry_fill(coin_amount, price)`

`record_exit_fill(coin_amount: float, price: float) -> None`
- Delegates to `posImpl.record_exit_fill(coin_amount, price)`

`finalize() -> tuple[float, float]`
- Delegates to `posImpl.finalize()`; sets `posImpl = None` after

`get_action() -> int`
- Returns `posImpl.get_action()`

`get_state() -> int`
- Returns `posImpl.state`

`get_target() -> float`
- Returns `posImpl.get_target()`

`is_opened() -> bool`
- Returns `self.posImpl is not None`

`is_stop_loss_triggered(cur_price: float) -> bool`
- Delegates to `posImpl.is_stop_loss_triggered(cur_price)`

`check_stop_open(cur_price: float) -> bool`
- Delegates to `posImpl.check_stop_open(cur_price)`

`close_by_time(cur_time: float) -> bool`
- Delegates to `posImpl.close_by_time(cur_time)`

`to_dict() -> dict`
- Returns `posImpl.to_dict()` with position type info added

`from_dict(data: dict) -> None`
- Reconstructs correct `posImpl` type from serialized dict (LongPosition or ShortPosition based on `position_type` field)

---

## Key Constraints

- `Position` does NOT own order IDs (`buy_id`, `sell_id`), margin loans (`set_loan`, `get_loan`), or JSON persistence (`save_position`, `load_position`) — those belong to `LiveOrderTracker` in Phase 10
- `fee` passed to `Position` must come from `stock.item.fee` after `do_stock_init()` — never default to 0.0 silently in production
- `full_position` set via `position.full_position = X` before first `open()` call — Robot sets this at init
- After `finalize()`, `posImpl = None` — next `open()` call creates a new `LongPosition`/`ShortPosition`
- All delegation methods (`close`, `record_entry_fill`, etc.) are no-ops when `posImpl is None`; `get_action()` returns `STRATEGY_ACTION_NOTHING`, `get_state()` returns `POSITION_STATE_WAIT`, `get_target()` returns `0.0`
- `from_dict()` must determine position type (Long vs Short) from the serialized data and reconstruct correctly for crash recovery

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from position.position import Position
from constants import STRATEGY_ACTION_OPEN_LONG, POSITION_STATE_WAIT_BUY, POSITION_TYPE_LONG

pos = Position(fee=0.001)
pos.full_position = 1000.0

result = pos.open(STRATEGY_ACTION_OPEN_LONG,
    price_open=[20.0], price_close=[21.0, 22.0],
    price_stop_loss=19.0, time_period=15, action_msg=None)
assert result == True
assert pos.get_state() == POSITION_STATE_WAIT_BUY
assert pos.posImpl.position_type == POSITION_TYPE_LONG
print('position facade ok')
"
```

---

## Commit

`feat: implement Position facade wrapping LongPosition/ShortPosition`
