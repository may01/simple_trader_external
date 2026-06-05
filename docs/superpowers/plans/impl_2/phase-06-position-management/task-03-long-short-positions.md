# Task 03: LongPosition and ShortPosition

**Phase:** 06 — Position Management  
**Depends on:** Task 02 (BasePosition)  
**Produces:** `position/long_position.py`, `position/short_position.py` — concrete direction-specific implementations

---

## Goal

Implement `LongPosition` and `ShortPosition` — concrete subclasses of `BasePosition` that implement direction-specific fill logic, position sizing, and P&L calculation.

---

## Files

- Create: `position/long_position.py`
- Create: `position/short_position.py`

---

## LongPosition Interface

**`__init__(fee, thread_num, full_position)`**
- `position_type = POSITION_TYPE_LONG`
- `coinUse.name = data.coin_base` (e.g., `"usdt"`) — what we spend to enter
- `coinGet.name = data.coin` (e.g., `"link"`) — what we acquire

**`open(strategy_action, price_open, price_close, price_stop_loss, time_period, action_msg) -> bool`**
- Validates no open position exists; stop-loss safety interval has elapsed
- Computes position size: `size = min(full_position, full_position * (risk_per_trade / (risk / avg_price)))` where `risk = avg_price - price_stop_loss`
- Sets `coinUse.want_to_use = size`
- Sets `coinUse.action_amount = size` (amount to spend on first buy)
- Sets `state = POSITION_STATE_WAIT_BUY` (long: we BUY first, sell later)
- Sets `action = STRATEGY_ACTION_OPEN_LONG`
- Records `open_time`

**`record_entry_fill(coin_amount: float, price: float) -> None`**
- Called when buy order fills
- `coinUse.size -= coin_amount * price * (1 + fee)` — deduct USD spent
- `coinUse.used += coin_amount * price * (1 + fee)`
- `coinGet.size += coin_amount` — credit coins received
- Records fill in `executed_open[]` and `executed_open_amount[]`
- Transitions `state = POSITION_STATE_WAIT_SELL`

**`record_exit_fill(coin_amount: float, price: float) -> None`**
- Called when sell order fills
- `coinGet.size -= coin_amount` — deduct coins sold
- `coinUse.size += coin_amount * price * (1 - fee)` — credit USD received
- `coinUse.returned += coin_amount * price * (1 - fee)`
- Records fill in `executed_close[]` and `executed_close_amount[]`

**`avg_price_open() -> float`**
- `sum(executed_open_amount) / total_coins_bought`

**`avg_price_close() -> float`**
- `sum(usd_received_per_fill) / sum(executed_close_amount)`

**Direction helpers:**
- `direction_profit(val) -> float` — for long, profit direction is up: returns `val` (unchanged)
- `direction_loss(val) -> float` — for long, loss direction is down: returns `-val`
- `first_in_profit(a, b) -> bool` — for long: `a > b` (higher price is more profitable)
- `is_stop_loss_triggered(cur_price) -> bool` — `cur_price <= self.price_stop_loss`

---

## ShortPosition Interface

**`__init__(fee, thread_num, full_position)`**
- `position_type = POSITION_TYPE_SHORT`
- `coinUse.name = data.coin` — what we borrow and sell to enter
- `coinGet.name = data.coin_base` — USD proceeds from short sale

**`open(...)`**
- Short opens with a SELL (borrow and sell coin first)
- `state = POSITION_STATE_WAIT_SELL` (short: we SELL first, buy back later)
- `action = STRATEGY_ACTION_OPEN_SHORT`

**`record_entry_fill(coin_amount, price)`**
- Short entry is a SELL
- `coinUse.size -= coin_amount` — coin sold
- `coinGet.size += coin_amount * price * (1 - fee)` — USD proceeds received

**`record_exit_fill(coin_amount, price)`**
- Short exit is a BUY (buy back coin)
- `coinGet.size -= coin_amount * price * (1 + fee)` — USD spent to buy back
- `coinUse.size += coin_amount` — coin returned (to repay borrow)

**Direction helpers:**
- `direction_profit(val) -> float` — for short, profit is DOWN: returns `-val`
- `direction_loss(val) -> float` — for short, loss is UP: returns `val`
- `first_in_profit(a, b) -> bool` — for short: `a < b` (lower price is more profitable)
- `is_stop_loss_triggered(cur_price) -> bool` — `cur_price >= self.price_stop_loss`

---

## Key Constraints

- `coinUse` and `coinGet` names are set from `data.coin_base` / `data.coin` — these come from `data.item.coin_base` and `data.item.coin` (live path) or equivalent configuration
- Position sizing formula: `risk = avg(price_open) - price_stop_loss` (long) — must be positive; if risk <= 0, abort open with False
- `executed_open_amount` stores USD amounts spent at each fill (not coin amounts)
- `executed_close_amount` stores coin amounts sold at each fill
- `state` transitions are strict: `WAIT_BUY` → fill → `WAIT_SELL`; any other transition is an error

---

## Commit

`feat: implement LongPosition and ShortPosition with fill recording and P&L logic`
