# Task 03: Position change log

**Phase:** 14 — Simulation Wiring
**Depends on:** Phase 06 (BasePosition, LongPosition, ShortPosition), Task 02 (event vocabulary)
**Produces:** `position.action_history` — raw lifecycle change tracking on the position

---

## Goal

Requirement 6: the position must track its own changes and log them. Add a `change_history` to `BasePosition` that records every state transition the position undergoes — open, close, stop-loss set/move, finalize — with the prices involved. This is the raw, strategy-agnostic source the robot (Task 04) enriches into `Action`s.

---

## Context

`BasePosition` already mutates state in `open()`, `close()`, `set_stop_loss()`, `finalize()`. Today those mutations are invisible after the fact. This task makes the position append a small change-event dict on each transition, so any caller can read what the position did without re-deriving it from fill arrays.

This must NOT depend on `backtesting.action` (Position is a lower layer than backtesting) — Position records plain dicts; TrainRobot maps them to `Action`s.

---

## Files

- Modify: `position/base_position.py`

---

## Interface

New on `BasePosition`:
- Attribute `change_history: list[dict]` — initialised `[]` in `__init__`
- `_record_change(self, kind: str, target_price: float, executed_price: float, was_stop_loss: bool = False, revenue_pct: float = 0.0, revenue_abs: float = 0.0) -> None` — appends a dict:
  `{"kind", "position_type", "target_price", "executed_price", "stop_loss_price", "was_stop_loss", "revenue_pct", "revenue_abs", "open_time"}`
  where `kind` ∈ `{"OPEN", "CLOSE", "MOVE_STOP_LOSS", "STOP_LOSS"}`
- `drain_changes(self) -> list[dict]` — returns the accumulated changes and clears the list (so the robot pulls per tick without re-reading old events)

Wiring into existing methods:
- `open(...)` success → `_record_change("OPEN", target_price=price_open[0], executed_price=0.0)` (fill recorded later by `record_entry_fill`; OPEN target captured here)
- `set_stop_loss(...)` when it actually updates → `_record_change("MOVE_STOP_LOSS", target_price=new_stop, executed_price=0.0)`
- `close(...)` → `_record_change("CLOSE", target_price=price_close[close_idx], executed_price=0.0, was_stop_loss=(strategy_action == STRATEGY_ACTION_DO_STOP_LOSS))`
- `finalize()` → after computing P&L, set the matching trailing CLOSE change's `revenue_pct`/`revenue_abs`, OR append a `"STOP_LOSS"`/`"CLOSE"` settle entry carrying the realised P&L (choose the simplest that keeps one settle event per trade)

---

## Key Constraints

- Position records dicts only — **no import of `backtesting.action`** (layer direction: backtesting depends on position, never the reverse).
- `change_history` must survive until `drain_changes()` is called — `finalize()`'s state reset must NOT clear it (the robot drains after finalize to capture the realised P&L). Add `change_history` to the explicit list of attributes `finalize()` does *not* reset.
- `was_stop_loss` is True only when the close was triggered by `STRATEGY_ACTION_DO_STOP_LOSS` or a `is_stop_loss_triggered`-forced close — not for normal target exits.
- `set_stop_loss(force=False)` that is silently ignored (less profitable) records **nothing** — only actual updates produce a MOVE_STOP_LOSS change.
- `to_dict()` / `from_dict()` need not serialise `change_history` (it is per-run, drained continuously) — leave persistence untouched.

---

## Verification

```bash
docker run --rm -v "$PWD":/code -w /code simple_trader python3 -c "
from position.position import Position
from constants import STRATEGY_ACTION_OPEN_LONG, POSITION_STATE_WAIT
p = Position(fee=0.001)
p.full_position = 1000.0
p.open(STRATEGY_ACTION_OPEN_LONG, [20.0], [20.16], 19.5, 3600, None)
ch = p.drain_changes()
assert ch and ch[0]['kind'] == 'OPEN' and ch[0]['target_price'] == 20.0
assert p.drain_changes() == []   # drained
print('position change log ok:', ch[0]['kind'])
"
```

---

## Commit

`feat: track position lifecycle changes in change_history with drain_changes`
