# Task 02: BasePosition — Abstract State Machine

**Phase:** 06 — Position Management  
**Depends on:** Task 01 (Coin), Phase 00 (constants: POSITION_STATE_*, STRATEGY_ACTION_*)  
**Produces:** `position/base_position.py` — abstract trade lifecycle state machine

---

## Goal

Implement `BasePosition` — abstract base class defining the position state machine, price target tracking, execution history arrays, and all business rule enforcement (stop-loss direction, safety timeout, P&L calculation).

---

## Context

`BasePosition` enforces the core trading rules. Stop-loss can only move toward profit (one-directional). `close_by_time()` forces close if position hasn't closed within safety window. `finalize()` computes P&L from fill history. `LongPosition` and `ShortPosition` inherit from this and implement direction-specific logic.

---

## Files

- Create: `position/base_position.py`

---

## Interface

**Constructor: `__init__(fee: float, thread_num: int = 0, full_position: float = 10000.0)`**

Attributes:
- `state: int` — current state machine state (`POSITION_STATE_WAIT` initially)
- `position_type: int = POSITION_TYPE_UNKNOWN` — overridden by subclasses to `POSITION_TYPE_LONG` or `POSITION_TYPE_SHORT`
- `price_open: list[float]` — array of entry price targets (graduated entry)
- `price_close: list[float]` — array of exit price targets (graduated exit)
- `price_stop_loss: float` — current stop-loss price
- `executed_open: list[float]` — prices at which entry fills executed
- `executed_open_amount: list[float]` — USD amounts at each entry fill
- `executed_close: list[float]` — prices at which exit fills executed
- `executed_close_amount: list[float]` — coin amounts at each exit fill
- `coinUse: Coin` — base currency leg (USDT for long, coin for short)
- `coinGet: Coin` — target currency leg (coin for long, USDT for short)
- `fee: float` — trading fee (injected, never hardcoded)
- `full_position: float` — total capital allocated
- `risk_per_trade: float = 0.01` — 1% of `full_position` risked per trade
- `safety_close_time: int = 0` — timeout for forcing position close (seconds); set in `open()` from `time_period`
- `close_idx: int = 0` — index of next unexecuted exit target in `price_close`
- `action: int` — current execution intent (`STRATEGY_ACTION_*`)
- `open_time: float` — Unix timestamp when position opened

**Abstract methods (must override in LongPosition/ShortPosition):**
- `open(strategy_action, price_open, price_close, price_stop_loss, time_period, action_msg) -> bool`
- `close(strategy_action, price_close, price_stop_loss, time_period, action_msg) -> None`
- `record_entry_fill(coin_amount: float, price: float) -> None`
- `record_exit_fill(coin_amount: float, price: float) -> None`
- `avg_price_open() -> float`
- `avg_price_close() -> float`
- `direction_profit(val: float) -> float`
- `direction_loss(val: float) -> float`
- `first_in_profit(a: float, b: float) -> bool`
- `is_stop_loss_triggered(cur_price: float) -> bool` — Long: `cur_price <= price_stop_loss`; Short: `cur_price >= price_stop_loss`

**Concrete methods (shared implementation):**
- `set_stop_loss(price: float, action_msg, force: bool = False) -> bool` — sets `price_stop_loss` only if `first_in_profit(price, current_stop)` is True OR `force=True`; returns True if updated
- `check_stop_open(cur_price: float) -> bool` — returns True if price moved 4×fee against entry (unlikely to fill — cancel order)
- `close_by_time(cur_time: float) -> bool` — returns True if `cur_time - open_time > safety_close_time`
- `get_action() -> int` — returns current `self.action`
- `get_action_amount(price: float) -> float` — returns coin quantity for the next order:
  - Long `WAIT_BUY`: `coinUse.action_amount / price` (USD → coins)
  - Long `WAIT_SELL`: `coinGet.action_amount` (already coins)
  - Short `WAIT_SELL`: `coinUse.action_amount` (already coins)
  - Short `WAIT_BUY` (exit): `coinGet.action_amount / price` (USD → coins)
- `get_target() -> float` — returns `price_close[close_idx]` if `close_idx < len(price_close)`; if `close_idx >= len(price_close)` (all targets exhausted but position still open), transitions `state` to `POSITION_STATE_WAIT_SAFETY_SELL` (long) or `POSITION_STATE_WAIT_SAFETY_BUY` (short) and returns `price_close[-1]` — signals Robot to force-close the remainder
- `finalize() -> tuple[float, float]` — computes `revenue_pct` and `revenue_abs` from fill history; calls `log_revenue()`; resets all state; returns `(revenue_pct, revenue_abs)`
- `to_dict() -> dict` — serializes full position state
- `from_dict(data: dict) -> None` — restores position state from dict

---

## Key Business Rules

- **Stop-loss is one-directional**: `set_stop_loss(price)` only accepts prices that are MORE profitable than current stop (closer to profit). To override, caller must pass `force=True`. This prevents accidental stop widening.
- **check_stop_open**: If price moved more than `4 × fee` against the entry target, the fill is unlikely — signal to cancel
- **close_by_time**: Safety timeout prevents capital lockup. If position hasn't closed within `safety_close_time`, forces close.
- **finalize**: Computes `revenue_pct = (avg_close / avg_open - 1) - 2*fee` for long; `(1 - avg_close / avg_open) - 2*fee` for short. `2*fee` is round-trip cost.

---

## Key Constraints

- `fee` has NO default — must be injected at construction; no silent fallback
- `set_stop_loss()` with `force=False` SILENTLY ignores if new price is less profitable — returns False, no exception
- `finalize()` MUST reset all state — `price_open`, `price_close`, `executed_open`, `executed_close`, `coinUse.reset()`, `coinGet.reset()`, `state = POSITION_STATE_WAIT`, `action = STRATEGY_ACTION_NOTHING`, `close_idx = 0`
- `to_dict()` / `from_dict()` roundtrip must preserve ALL state including `Coin` objects

---

## Commit

`feat: implement BasePosition abstract state machine with stop-loss and P&L logic`
