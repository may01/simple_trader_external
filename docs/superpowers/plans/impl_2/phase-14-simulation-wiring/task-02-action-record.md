# Task 02: Action record + ActionLog

**Phase:** 14 — Simulation Wiring
**Depends on:** Phase 00 (constants: STRATEGY_ACTION_*, POSITION_TYPE_*)
**Produces:** `backtesting/action.py` — `Action` dataclass + `ActionLog` writer

---

## Goal

Define the single record type that captures every meaningful event during a simulation: a position opened, closed, stopped out, a stop-loss moved, or a strategy signal fired. One schema, JSONL-serialisable, written one file per simulation.

---

## Context

Requirement 3: "changes of positions and firing of the signals should produce records that store information about the change — if position was opened, closed, was it stop loss, if the strategy fired signal, what price was provided from strategy to position." `Action` is that record. `ActionLog` accumulates them in memory during a run and serialises them; the orchestrator (Task 05) decides where the file lands.

The model lives in `backtesting/` (not `position/`) because it is a backtest artifact, not a business-logic primitive — Position emits raw events (Task 03), the robot enriches them into `Action`s (Task 04).

---

## Files

- Create: `backtesting/action.py`

---

## Interface

**`@dataclass Action`** — concrete typed fields only, no `Any`, no untyped dict:
- `sim_id: int` — owning simulation id
- `timestamp: float` — Unix seconds of the tick
- `tick_index: int` — ordinal of the tick within the worker segment
- `event: str` — one of `"OPEN" | "CLOSE" | "STOP_LOSS" | "MOVE_STOP_LOSS" | "SIGNAL_FIRED"`
- `action_type: str` — originating `STRATEGY_ACTION_*` constant
- `position_type: str` — `POSITION_TYPE_LONG | POSITION_TYPE_SHORT | POSITION_TYPE_UNKNOWN`
- `was_stop_loss: bool` — True when the close was forced by a stop-loss trigger
- `strategy_name: str` — class name of the deciding strategy, or `""`
- `signal_name: str` — originating `SignalChain` name, or `""`
- `target_price: float` — price the strategy provided to the position (entry/exit target); `0.0` if N/A
- `executed_price: float` — simulated fill price; `0.0` if no fill
- `stop_loss_price: float` — stop-loss price in effect; `0.0` if none
- `revenue_pct: float` — set on CLOSE/STOP_LOSS, else `0.0`
- `revenue_abs: float` — set on CLOSE/STOP_LOSS, else `0.0`

Methods:
- `to_dict() -> dict` — flat dict of all fields (JSON-safe primitives only)
- `@classmethod from_dict(data: dict) -> "Action"`

**`class ActionLog`**
- `__init__(self, sim_id: int)` — stores `sim_id`; `actions: list[Action] = []`
- `record(self, action: Action) -> None` — append; asserts `action.sim_id == self.sim_id`
- `to_jsonl(self) -> str` — one `json.dumps(action.to_dict())` per line, newline-separated
- `extend(self, other: "ActionLog") -> None` — merge another log's actions (used to combine worker logs); asserts matching `sim_id`
- `__len__(self) -> int`

---

## Key Constraints

- All `Action` fields are concrete scalars — JSONL round-trip (`from_dict(json.loads(line)).to_dict()`) must be lossless.
- `ActionLog.record` enforces the `sim_id` invariant — a stray action from another run is a bug, fail loudly.
- No file I/O in this module — `ActionLog` only produces a string. Persistence is Task 05's job (keeps the model testable without a filesystem).
- `event` and `action_type` are distinct: `event` is the lifecycle category (what happened to the position); `action_type` is the strategy intent constant.

---

## Verification

```bash
docker run --rm -v "$PWD":/code -w /code simple_trader python3 -c "
import json
from backtesting.action import Action, ActionLog
from constants import STRATEGY_ACTION_OPEN_LONG, POSITION_TYPE_LONG
a = Action(sim_id=7, timestamp=1000.0, tick_index=3, event='OPEN',
           action_type=STRATEGY_ACTION_OPEN_LONG, position_type=POSITION_TYPE_LONG,
           was_stop_loss=False, strategy_name='StrategyTest1Long', signal_name='t1_long_entry',
           target_price=20.0, executed_price=20.0, stop_loss_price=19.0,
           revenue_pct=0.0, revenue_abs=0.0)
log = ActionLog(7); log.record(a)
line = log.to_jsonl()
assert Action.from_dict(json.loads(line)).to_dict() == a.to_dict()
print('action record ok, lines:', len(log))
"
```

---

## Commit

`feat: add Action record and ActionLog for simulation event capture`
