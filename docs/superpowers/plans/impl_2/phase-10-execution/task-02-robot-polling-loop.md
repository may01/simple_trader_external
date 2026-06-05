# Task 02: Robot Polling Loop

**Phase:** 10 — Execution  
**Depends on:** Task 01 (LiveOrderTracker), Phase 07 (StrategyManager), Phase 03 Task 05 (LiveData)  
**Produces:** `robots/robot.py` — live trading robot main loop

---

## Goal

Implement `Robot` — the live trading robot. Drives `LiveData` per-tick, evaluates `StrategyManager`, and dispatches order management actions. Polling loop runs continuously until stopped.

---

## Context

Robot is the live-path counterpart to `TrainRobot`. Unlike `TrainRobot`, Robot places real orders via `StockInterface`, polls for fills, and uses `LiveOrderTracker` for persistence. `run_instantly()` is the main entry point — called from Docker execution path E.

---

## Files

- Create: `robots/robot.py`

---

## Interface

**`Robot(strategy_manager: StrategyManager, live_data: LiveData, stock: StockInterface, fee: float, persist_path: str)`**

Attributes:
- `strategy_manager: StrategyManager`
- `live_data: LiveData` — provides `data_point` per tick
- `stock: StockInterface`
- `position: Position`
- `tracker: LiveOrderTracker`
- `fee: float`
- `running: bool = False`

**`run_instantly() -> None`**
- Entry point: loads tracker state (crash recovery), sets `running = True`
- Main loop: calls `do()`, sleeps polling interval, repeat
- Catches `KeyboardInterrupt` → graceful shutdown

**`do() -> None`**
- Gets current `data_point` from `live_data`
- Gets `position_state`, `position_target`
- Calls `strategy_manager.check(data_point, position_state, position_target, action_msg=None)`
- Dispatches: OPEN → `_open_position()`, CLOSE → `_close_position()`, DO_STOP_LOSS → `_stop_loss()`, NOTHING → `wait()`

**`wait(data_point) -> None`**
- Checks for fills on open orders via `tracker.check_fill()`
- Checks stop-loss trigger, close-by-time trigger
- Updates stop-loss if strategy returns MOVE_STOP_LOSS action

**`stop() -> None`**
- Sets `running = False`

---

## Key Constraints

- `data_point` obtained fresh each tick from `live_data` — not stored between ticks
- Polling interval: 1 second minimum; matches `LiveData` update cadence
- On crash recovery: `tracker.load()` called at start; if Position has open trade, resume `wait()` immediately
- `position.full_position` set from config at Robot init — not per-trade
- `strategy_manager` initialized with `robot_actions_test=False` for live path (NN filter active)

---

## Verification

```bash
docker compose run --rm trader python3 -c "
from robots.robot import Robot
from strategies.strategy_manager import StrategyManager
print('robot module importable')
"
```

---

## Commit

`feat: implement Robot polling loop with crash recovery and live order dispatch`
