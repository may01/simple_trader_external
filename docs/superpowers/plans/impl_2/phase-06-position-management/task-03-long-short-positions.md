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
- `coinUse = Coin("usdt")` — currency spent to enter (base currency)
- `coinGet = Coin("coin")` — currency acquired (quote coin)

**`open(strategy_action, price_open, price_close, price_stop_loss, time_period, action_msg) -> bool`**
- Validates no open position exists; stop-loss safety interval has elapsed
- Computes position size: `size = min(full_position, full_position * (risk_per_trade / (risk / avg_price)))` where `risk = avg_price - price_stop_loss`
- Sets `coinUse.size = full_position` — seeds available USDT balance before any fills
- Sets `coinUse.want_to_use = size`
- Sets `coinUse.action_amount = size` (amount to spend on first buy)
- Sets `safety_close_time = time_period * 60 * 4` — 4 candles of the signal TF
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
- Increments `close_idx`

**`avg_price_open() -> float`**
- `sum(executed_open_amount) / sum(executed_open_amount[i] / executed_open[i])` — total USD spent / total coins bought; pre-fee prices

**`avg_price_close() -> float`**
- `sum(executed_close[i] * executed_close_amount[i]) / sum(executed_close_amount)` — weighted average exit price; pre-fee prices

**Direction helpers:**
- `direction_profit(val) -> float` — for long, profit direction is up: returns `val` (unchanged)
- `direction_loss(val) -> float` — for long, loss direction is down: returns `-val`
- `first_in_profit(a, b) -> bool` — for long: `a > b` (higher price is more profitable)
- `is_stop_loss_triggered(cur_price) -> bool` — `cur_price <= self.price_stop_loss`

---

## ShortPosition Interface

**`__init__(fee, thread_num, full_position)`**
- `position_type = POSITION_TYPE_SHORT`
- `coinUse = Coin("coin")` — currency borrowed and sold to enter
- `coinGet = Coin("usdt")` — USD proceeds from short sale

**`open(strategy_action, price_open, price_close, price_stop_loss, time_period, action_msg) -> bool`**
- Validates no open position exists; stop-loss safety interval has elapsed
- Computes position size: `risk = price_stop_loss - avg_price` where `avg_price = avg(price_open)`; abort with `False` if `risk <= 0`
- `size = min(full_position, full_position * (risk_per_trade / (risk / avg_price)))`
- Sets `coinUse.size = full_position` — seeds available coin balance (borrow amount) before any fills
- Sets `coinUse.want_to_use = size`
- Sets `coinUse.action_amount = size` (coin amount to sell on first entry)
- Sets `safety_close_time = time_period * 60 * 4` — 4 candles of the signal TF
- Sets `state = POSITION_STATE_WAIT_SELL` (short: we SELL first, buy back later)
- Sets `action = STRATEGY_ACTION_OPEN_SHORT`
- Records `open_time`

**`record_entry_fill(coin_amount, price)`**
- Short entry is a SELL
- `coinUse.size -= coin_amount` — coin sold
- `coinGet.size += coin_amount * price * (1 - fee)` — USD proceeds received

**`record_exit_fill(coin_amount, price)`**
- Short exit is a BUY (buy back coin)
- `coinGet.size -= coin_amount * price * (1 + fee)` — USD spent to buy back
- `coinUse.size += coin_amount` — coin returned (to repay borrow)
- Increments `close_idx`

**Direction helpers:**
- `direction_profit(val) -> float` — for short, profit is DOWN: returns `-val`
- `direction_loss(val) -> float` — for short, loss is UP: returns `val`
- `first_in_profit(a, b) -> bool` — for short: `a < b` (lower price is more profitable)
- `is_stop_loss_triggered(cur_price) -> bool` — `cur_price >= self.price_stop_loss`

---

## Key Constraints

- `coinUse` and `coinGet` names are hardcoded strings passed to `Coin(name)` at construction: LongPosition uses `Coin("usdt")` / `Coin("coin")`; ShortPosition uses `Coin("coin")` / `Coin("usdt")` — symbolic names for logging only, not used for exchange routing
- Position sizing formula: `risk = avg(price_open) - price_stop_loss` (long) / `risk = price_stop_loss - avg(price_open)` (short) — must be positive; abort with `False` if `risk <= 0`
- `executed_open_amount` stores USD amounts spent at each fill (not coin amounts)
- `executed_close_amount` stores coin amounts sold at each fill
- `state` transitions are strict: `WAIT_BUY` → fill → `WAIT_SELL`; any other transition is an error

---

## Commit

`feat: implement LongPosition and ShortPosition with fill recording and P&L logic`
