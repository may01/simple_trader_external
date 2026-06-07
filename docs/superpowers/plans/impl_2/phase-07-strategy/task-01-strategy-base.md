# Task 01: Strategy Base Class

**Phase:** 07 — Strategy  
**Depends on:** Phase 05 (SignalManager), Phase 06 (Position), Phase 03 Task 08 (Levels)  
**Produces:** `strategies/strategy.py` — abstract base class for all trading strategies

---

## Goal

Implement `Strategy` — abstract base class that all concrete strategies inherit from. Defines the `check()` template method, level building, action selection, and default price computation.

---

## Context

Each strategy registers its own `SignalManager` with signal chains tuned for its trading logic. `Strategy.check()` is the template: build levels → evaluate signals → select action → compute prices → return 5-tuple. `StrategyManager` calls `check()` on each registered strategy per tick and resolves conflicts.

---

## Files

- Create: `strategies/strategy.py`
- Create: `strategies/__init__.py` (empty)

---

## Interface

**`Strategy(fee: float)`**

Attributes:
- `signals: SignalManager` — holds all signal chains for this strategy; initialized in `register_signals()`
- `fee: float` — injected; used for price buffer calculations

**Abstract methods (must override):**
- `register_signals() -> None` — build and register signal chains into `self.signals`
- `check_conditions(data_point, position_state: int, action_msg) -> bool` — returns True if strategy should run this tick; gates on position state or market conditions

**Template method (final — do not override):**
- `check(data_point, position_state: int, cur_time: float, action_msg) -> tuple[int, float, float, float, int]` — calls: `get_level_values()` → `signals.check(data_point, levels, cur_time, action_msg)` → `select_final_action()` → `get_open/close/stop_loss_price()` → returns `(action, open_price, close_price, stop_price, tf)`

**Overridable price methods (with defaults):**
- `get_open_price(data_point, tf: int) -> float` — default: current 1-min close `data_point.get("close", 1, 0)`
- `get_close_price(data_point, tf: int, action: int) -> float` — default: `open_price * (1 + 0.008)` for long, `open_price * (1 - 0.008)` for short (+0.8% target)
- `get_stop_loss_price(data_point, tf: int, action: int) -> float` — default: `data_point.get("sar", tf, 0) - 0.3 * data_point.get("atr_14", tf, 0)` for long; `data_point.get("sar", tf, 0) + 0.3 * data_point.get("atr_14", tf, 0)` for short

**Internal helpers:**
- `get_level_values(data_point) -> dict` — builds levels dict from hand-drawn and auto-detected support/resistance level objects (phase-03 task-08 format); passed to `signals.check()`; signals needing EMA/BB values read them directly from `data_point`
- `select_final_action(actions_list: list, position_state: int) -> tuple[int, int]` — picks single action from list; returns `(final_action, tf)` where `tf` is the timeframe of the winning action

---

## Action Selection Logic (select_final_action)

Priority rules:
- Single action in list → use it directly
- Multiple actions, `position_state == POSITION_STATE_WAIT`: prefer OPEN_LONG or OPEN_SHORT
- Multiple actions, position open: prefer CLOSE_* actions first, then MOVE_STOP_LOSS_*
- NOTHING returned when list is empty

---

## Default Price Logic

| Price | Default Formula |
|-------|----------------|
| open_price | current 1-min `close` |
| close_price (long) | `open_price * 1.008` (+0.8%) |
| close_price (short) | `open_price * 0.992` (-0.8%) |
| stop_loss (long) | `data_point.get("sar", tf, 0) - 0.3 * data_point.get("atr_14", tf, 0)` |
| stop_loss (short) | `data_point.get("sar", tf, 0) + 0.3 * data_point.get("atr_14", tf, 0)` |

---

## Key Constraints

- `fee` injected — NO default value in constructor
- `register_signals()` called in `__init__()` after `self.signals = SignalManager()`
- `get_level_values()` called fresh every tick — levels not cached between ticks
- Current implementation: `get_level_values()` only populates `LEVEL_TYPE_AUTO_RESISTANCE` and `LEVEL_TYPE_SHORT_RESISTANCE` levels (long support/resistance entries commented out)
- Trend filtering is a SIGNAL concern: use `BoolValue_Signal("trend_up", tf)` in chains — no `trend_tf` attribute on Strategy
- `check_conditions()` returning False skips signal evaluation for this tick (strategy-level gate)

---

## Commit

`feat: implement Strategy abstract base class with template method and default price logic`
