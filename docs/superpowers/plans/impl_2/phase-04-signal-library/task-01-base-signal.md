# Task 01: BaseSignal Abstract Interface

**Phase:** 04 — Signal Library  
**Depends on:** Phase 03 (DataPoint protocol)  
**Produces:** `signals_lib/base_signal.py` — abstract contract for all signal implementations

---

## Goal

Implement `BaseSignal` — the abstract base class all signal types inherit from. Defines `check()`, `reset()`, `get_data()`, `get_marker_pos()`, and `set_shift()`.

---

## Context

Every signal in the system inherits from `BaseSignal`. Signals are evaluated by `SignalChain.check()` — it calls `signal.check(data_point, levels, action)` and advances `cur_pos` if True. The `shift` attribute is the historical offset: `shift=0` is current, `shift=N` is N closed candles back. Combinator signals propagate `set_shift()` recursively to nested signals.

---

## Files

- Create: `signals_lib/base_signal.py`
- Create: `signals_lib/__init__.py` (empty)

---

## Interface

**BaseSignal:**
- `shift: int = 0` — historical offset applied when calling `data_point.get(col, tf, shift + self.shift)`
- `check(data_point: DataPoint, levels: dict, action) -> bool` — abstract; raises `AssertionError` if not overridden (use `assert False`)
- `reset() -> bool` — returns True to abort parent `SignalChain`; default returns False
- `get_data() -> dict` — returns signal-specific metadata when chain completes; default returns `{}`
- `get_marker_pos(data_point: DataPoint) -> float` — returns price for chart marker; default returns `data_point.get("close", 1, 1)`
- `set_shift(shift: int) -> None` — sets `self.shift = shift`; combinator signals override to propagate recursively

---

## Key Constraints

- `check()` is called with `shift + self.shift` added to any `data_point.get()` calls inside the signal — implementers must respect this convention
- `reset()` returning True causes the entire `SignalChain` to reset to `cur_pos=0` — use sparingly, for explicit cancellation conditions only
- `get_data()` metadata is merged across all signals in chain when `get_action()` is called — keys must not collide between signals in the same chain
- `set_shift()` in `BaseSignal` sets `self.shift` only; combinator signals (`And_Signal`, `Or_Signal`) must override to propagate to nested signals
- BaseSignal itself is never instantiated directly — it is an abstract base

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from signals_lib.base_signal import BaseSignal
# Cannot instantiate abstract
try:
    s = BaseSignal()
    s.check(None, {}, None)
    assert False, 'should have raised'
except AssertionError:
    pass
print('BaseSignal contract ok')
"
```

---

## Commit

`feat: add BaseSignal abstract interface`
