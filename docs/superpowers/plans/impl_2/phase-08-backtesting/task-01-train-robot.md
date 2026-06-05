# Task 01: TrainRobot

**Phase:** 08 — Backtesting  
**Depends on:** Phase 06 (Position), Phase 07 (StrategyManager), Phase 03 Task 06 (SimulationData)  
**Produces:** `robots/train_robot.py` — step-driven simulation execution agent

---

## Goal

Implement `TrainRobot` — drives one simulation step at a time. Receives `data_point` and `action` per step (data passed in, never stored as attribute), manages position lifecycle via buy/sell/wait, and records trade outcomes.

---

## Context

`TrainRobot.step(data_point, action)` is the simulation API surface — SimulationOrchestrator calls it per tick. Robot never pulls data itself; data always arrives via `step()`. Position state transitions mirror live robot but without order placement — fills are simulated immediately at target price.

---

## Files

- Create: `robots/train_robot.py`
- Create: `robots/__init__.py` (empty)

---

## Interface

**`TrainRobot(strategy_manager: StrategyManager, fee: float)`**

Attributes:
- `strategy_manager: StrategyManager`
- `position: Position`
- `fee: float`
- `revenue_history: list[tuple[float, float]]` — `(revenue_pct, revenue_abs)` per closed trade
- `trade_count: int`

**`step(data_point, action: int) -> None`**
- Main tick: calls `_do(data_point, action)`
- Catches and logs exceptions without crashing simulation

**`_do(data_point, action: int) -> None`**
- Gets `position_state = position.get_state()`
- Gets `position_target = position.get_target()`
- Calls `strategy_manager.check(data_point, position_state, position_target, action_msg=None)`
- Dispatches on returned action: OPEN → `buy()`, CLOSE → `sell()`, DO_STOP_LOSS → `sell()`, NOTHING → `wait()`

**`buy(data_point, strategy_action: int, open_prices: list, close_prices: list, stop_price: float, tf: int) -> None`**
- Calls `position.open(strategy_action, open_prices, close_prices, stop_price, tf, action_msg=None)`
- If open succeeds: immediately simulates fill at `open_prices[0]`
- Calls `position.record_entry_fill(coin_amount, open_prices[0])`

**`sell(data_point, strategy_action: int, close_prices: list, stop_price: float, tf: int) -> None`**
- Calls `position.close(strategy_action, close_prices, stop_price, tf, action_msg=None)`
- Immediately simulates fill at `close_prices[0]`
- Calls `position.record_exit_fill(coin_amount, close_prices[0])`
- Calls `_finalize()`

**`wait(data_point) -> None`**
- Checks `position.is_stop_loss_triggered(cur_price)` — if True, force close
- Checks `position.close_by_time(cur_time)` — if True, force close

**`_finalize() -> None`**
- Calls `position.finalize()` → `(revenue_pct, revenue_abs)`
- Appends to `revenue_history`
- Increments `trade_count`

**`get_results() -> dict`**
- Returns summary: `total_trades`, `revenue_history`, `total_revenue_abs`, `avg_revenue_pct`

---

## Key Constraints

- `data_point` is passed into every method — NEVER stored as instance attribute
- Fills simulated immediately (no async order placement) — coin_amount computed from `position.full_position / open_prices[0]`
- `fee` flows into Position on construction — TrainRobot does not re-inject per fill
- `strategy_manager` initialized with `robot_actions_test=True` for simulation path
- Stop-loss triggered: call `sell()` with `STRATEGY_ACTION_DO_STOP_LOSS`
- `close_by_time` triggered: call `sell()` at current price, not target price

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from robots.train_robot import TrainRobot
from strategies.strategy_manager import StrategyManager
from strategies.example_strategy_long import ExampleStrategyLong

sm = StrategyManager(fee=0.001, robot_actions_test=True)
sm.register(ExampleStrategyLong(fee=0.001))
robot = TrainRobot(strategy_manager=sm, fee=0.001)
robot.position.full_position = 1000.0
print('train_robot ok, trades:', robot.trade_count)
"
```

---

## Commit

`feat: implement TrainRobot step-driven simulation with immediate fill simulation`
