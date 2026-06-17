# Task 04: TrainRobot emits enriched Action records

**Phase:** 14 — Simulation Wiring
**Depends on:** Task 02 (Action/ActionLog), Task 03 (position.change_history), Phase 08 Task 01 (TrainRobot)
**Produces:** TrainRobot owns an `ActionLog`, maps position changes + strategy decisions into `Action`s

---

## Goal

TrainRobot is the only layer that sees both the strategy decision (action type + the open/close/stop prices the strategy *provided*) and the resulting position transition. This task makes it assemble `Action` records each tick by combining `position.drain_changes()` (raw transitions) with the strategy context it already holds, plus a `SIGNAL_FIRED` action whenever a strategy returns a non-NOTHING action.

---

## Context

`TrainRobot._do()` already unpacks `(strategy_action, open_prices, close_prices, stop_price, tf)` from `strategy_manager.check()` and dispatches to `buy()`/`sell()`/`wait()`. After dispatch, the position has appended its changes; the robot drains them, enriches each with the strategy context captured this tick, and records `Action`s into its `ActionLog`. The orchestrator (Task 05) injects the `sim_id` and a tick counter, then collects the log.

To attribute `strategy_name`/`signal_name`, `StrategyManager.check()` must surface which strategy and chain won — see Constraints.

---

## Files

- Modify: `robots/train_robot.py`
- Modify: `strategies/strategy_manager.py` — surface provenance of the resolved action
- Modify: `strategies/strategy.py` — `check()` returns originating chain name alongside the action

---

## Interface

**StrategyManager / Strategy provenance (minimal extension):**
- `Strategy.check(...)` and `StrategyManager.check(...)` keep their 5-tuple return for callers that ignore provenance, but additionally expose the winning `(strategy_name: str, signal_name: str)` via a new return field OR an out-parameter the robot reads. Recommended: extend the resolved result to a small struct / 7-tuple `(action, open_prices, close_prices, stop_price, tf, strategy_name, signal_name)`. Update Phase 08/07 callers and tests accordingly.
- `signal_name` is the `SignalChain.name` of the chain that produced the winning action (already available in `SignalManager.check` results — thread it through `select_final_action`).

**TrainRobot:**
- New attribute `action_log: ActionLog` — constructed lazily/`set_sim_context(sim_id, tick_offset)`; `sim_id` defaults to `0` for standalone use
- `set_sim_context(self, sim_id: int) -> None` — sets the log's `sim_id`; resets `tick_index` counter
- `step(data_point)` increments an internal `tick_index`
- After dispatch in `_do()`:
  - If `strategy_action != NOTHING`: record a `SIGNAL_FIRED` `Action` (carries `action_type`, `strategy_name`, `signal_name`, `target_price` = first relevant strategy-provided price, `stop_loss_price`)
  - For each dict from `position.drain_changes()`: map `kind → event` and record an `Action`, filling `executed_price` from the position fill (entry uses `open_prices[0]`/`avg_price_open`, exit uses `close_prices[0]`/`avg_price_close`), and `revenue_*` from the settle change
- `get_action_log() -> ActionLog`

---

## Key Constraints

- Mapping `kind → event` is 1:1 (`OPEN→OPEN`, `CLOSE→CLOSE`, `MOVE_STOP_LOSS→MOVE_STOP_LOSS`, `STOP_LOSS→STOP_LOSS`). The separate `SIGNAL_FIRED` action is what records "the strategy fired and what price it provided" even on ticks where the position rejects the action (incompatible state) — so signal firings are visible independent of position outcome.
- `target_price` on a position change comes from the position's recorded target; `target_price` on `SIGNAL_FIRED` comes from the strategy's provided prices — these can differ and both are kept.
- `data_point` still NEVER stored as an attribute — `tick_index` is robot state, `timestamp` read from `data_point` per call.
- Drain AFTER `_finalize()` so the settle change (with realised P&L) is included in the same tick's actions.
- Exceptions in action recording must not crash the simulation — wrap in the existing `step()` try/except, log via `log_error`.
- Standalone `TrainRobot` (no orchestrator) still works: `sim_id` defaults to `0`, log accumulates in memory.

---

## Verification

```bash
docker run --rm -v "$PWD":/code -w /code simple_trader python3 -m pytest tests/test_phase14_train_robot_actions.py -q
```

Test asserts: after stepping a robot through a synthetic OPEN→CLOSE sequence, `get_action_log()` contains a `SIGNAL_FIRED`, an `OPEN`, and a `CLOSE` action; the CLOSE carries non-zero `revenue_pct`; the OPEN carries the strategy-provided `target_price`.

---

## Commit

`feat: TrainRobot assembles enriched Action records from position changes and strategy decisions`
