# Task 03: StrategyManager

**Phase:** 07 — Strategy  
**Depends on:** Task 01 (Strategy base), Phase 05 (SignalManager), Phase 06 (Position)  
**Produces:** `strategies/strategy_manager.py` — orchestrator resolving conflicts across multiple registered strategies

---

## Goal

Implement `StrategyManager` — aggregates per-tick actions from all registered strategies, applies conflict resolution priority, and returns a single resolved `(action, open_price, close_price, stop_price, tf)` tuple to Robot.

---

## Context

Robot calls `strategy_manager.check(data_point, position_state, position_target, action_msg)` once per tick. Each registered strategy's `check()` fires; results are collected and conflict-resolved. Priority order: `DO_STOP_LOSS > CLOSE > MOVE_STOP_LOSS > OPEN`. Multiple competing OPEN signals from different strategies → NOTHING. NN predictor output optionally filters OPEN actions.

---

## Files

- Create: `strategies/strategy_manager.py`

---

## Interface

**`StrategyManager(fee: float, robot_actions_test: bool = False)`**

Attributes:
- `strategies: list[Strategy]` — registered strategy instances
- `fee: float`
- `robot_actions_test: bool` — when True, skip NN filter (used in simulation/testing)

**`register(strategy: Strategy) -> None`**
- Appends strategy to `self.strategies`

**`check(data_point, position_state: int, position_target: float, action_msg) -> tuple[int, float, float, float, int]`**
- Calls `strategy.check(data_point, position_state, position_target, action_msg)` for each registered strategy
- Collects all returned `(action, open_price, close_price, stop_price, tf)` tuples where `action != STRATEGY_ACTION_NOTHING`
- Applies conflict resolution (see below)
- Returns resolved tuple or `(STRATEGY_ACTION_NOTHING, 0, 0, 0, 0)` if no action

**`_resolve(results: list[tuple]) -> tuple[int, float, float, float, int]`**
- Priority: DO_STOP_LOSS (highest) → CLOSE_LONG / CLOSE_SHORT → MOVE_STOP_LOSS_* → OPEN_LONG / OPEN_SHORT
- Multiple CLOSE from different strategies: take first (or any — they share same position)
- Multiple OPEN from different strategies: return NOTHING (conflict — no consensus)
- Single OPEN: allowed

---

## Conflict Resolution Rules

| Scenario | Resolution |
|----------|-----------|
| Any DO_STOP_LOSS present | Return DO_STOP_LOSS immediately |
| CLOSE + OPEN both present | Return CLOSE (close takes priority) |
| Multiple CLOSE signals | Return first CLOSE |
| Multiple OPEN signals (different strategies) | Return NOTHING |
| Single OPEN signal | Return it |
| Only MOVE_STOP_LOSS | Return it |
| Empty list | Return NOTHING |

---

## Key Constraints

- Strategies evaluated in registration order — order matters for tie-breaking
- `robot_actions_test=True` disables NN predictor filter entirely; used by `TrainRobot`
- NN integration: if predictor available and `robot_actions_test=False`, OPEN actions filtered by predictor confidence threshold before returning
- `check()` must NOT store state between ticks — stateless aggregation only
- If `strategies` is empty, returns NOTHING immediately

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from strategies.strategy_manager import StrategyManager
from strategies.example_strategy_long import ExampleStrategyLong
from constants import POSITION_STATE_WAIT

sm = StrategyManager(fee=0.001, robot_actions_test=True)
sm.register(ExampleStrategyLong(fee=0.001))
print('strategy_manager ok, strategies:', len(sm.strategies))
"
```

---

## Commit

`feat: implement StrategyManager with priority-based conflict resolution`
