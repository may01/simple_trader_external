# Task 01: SignalChain — Sequential State Machine

**Phase:** 05 — Signals Logic  
**Depends on:** Phase 04 (all signal types)  
**Produces:** `signals_lib/signal_manager.py` — `SignalChain` class

---

## Goal

Implement `SignalChain` — the sequential state machine that advances through a list of signals, firing when each one activates in order. When all signals have fired, the chain is complete and returns an action tuple.

---

## Context

`SignalChain` is the core compositional unit of the signal system. A chain with 3 signals only completes after signal 0 fires, THEN signal 1 fires, THEN signal 2 fires — in separate ticks. State persists across ticks. This enables multi-candle pattern detection (e.g., "CCI cross, then RSI confirm, then price confirms").

---

## Files

- Create: `signals_lib/signal_manager.py`

---

## Interface

**`SignalChain(name: str, res_action: int, tf: int, notify: bool = True)`**

Attributes:
- `name: str` — chain identifier for logging
- `signals: list[BaseSignal]` — ordered signal sequence
- `cur_pos: int` — current position in sequence (0 = waiting for first signal)
- `timer: float` — Unix timestamp when last signal fired
- `result_action: int` — `STRATEGY_ACTION_*` constant returned when chain completes
- `tf: int` — timeframe this chain operates on
- `notify: bool` — whether to log chain progress via `action.add_multiply_action()`

Methods:
- `add(signal: BaseSignal) -> None` — appends signal to `self.signals`
- `check(data_point, levels, cur_time: float, action) -> None` — if `cur_pos < len(signals)`: call `signals[cur_pos].check()`; if True: log fired signal via action (see #30), then increment `cur_pos` and set `timer = cur_time`; then check if new `signals[cur_pos]`'s `reset()` returns True → if so, call `self.reset(action)`
- `completed(data_point, action) -> bool` — if `cur_pos == len(signals)`: log completion via action when `notify=True` (see #31), return `True`; else return `False`
- `get_action(price: float, action) -> list` — returns `[result_action, tf, price, data_dict]` where `data_dict` merges `{"position_time": tf}` with `s.get_data()` from all signals
- `reset(action) -> None` — resets `cur_pos = 0`, `timer = 0`

---

## State Machine Behavior

```
cur_pos=0 → signals[0].check() fires → cur_pos=1
cur_pos=1 → signals[1].check() fires → cur_pos=2
...
cur_pos=N → all fired → completed() = True → get_action() → reset to 0

At any point: signals[cur_pos].reset() = True → reset to 0
```

Only `signals[cur_pos]` is evaluated each tick — signals before `cur_pos` are ignored (already passed).

---

## Key Constraints

- `check()` only evaluates ONE signal per call (`signals[cur_pos]`) — NOT all signals
- After incrementing `cur_pos`, immediately check if new `signals[cur_pos].reset()` is True — chain may need to abort before next tick
- `timer` is set to `cur_time` (Unix seconds) whenever `cur_pos` advances — available for timeout logic
- `get_action()` merges `get_data()` from ALL signals (not just the last) — this collects level names, prices, etc. from any signal in the chain
- `notify=True` logs progress via `action.add_multiply_action(signals[cur_pos].get_marker_pos(data_point), "SF: C {name} S {cur_pos}")` BEFORE incrementing `cur_pos` (#30), and logs completion via `action.add_multiply_action(signals[-1].get_marker_pos(data_point), "CPLTD: {name}")` from `completed()` (#31) — `notify=False` suppresses both
- `get_marker_pos(data_point) -> float` is a `BaseSignal` method `SignalChain` calls for both of the above logs (default: `data_point.get("close", 1, 1)`)
- `result_action` must be a valid `STRATEGY_ACTION_*` constant

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from signals_lib.signal_manager import SignalChain
from signals_lib.common import Greater_Val_Signal, Less_Val_Signal
from constants import STRATEGY_ACTION_OPEN_LONG
from data import LiveDataPoint
import pandas as pd

chain = SignalChain('test_chain', STRATEGY_ACTION_OPEN_LONG, tf=15, notify=False)
chain.add(Greater_Val_Signal(15, 'rsi_14', 40))  # must fire first
chain.add(Greater_Val_Signal(15, 'rsi_14', 50))  # then this

df1 = pd.DataFrame({'15_rsi_14': [45.0]})  # first signal fires
pt1 = LiveDataPoint({15: df1})
chain.check(pt1, {}, 1000.0, None)
assert chain.cur_pos == 1

df2 = pd.DataFrame({'15_rsi_14': [55.0]})  # second signal fires
pt2 = LiveDataPoint({15: df2})
chain.check(pt2, {}, 1001.0, None)
assert chain.completed(pt2, None) == True
action = chain.get_action(55.0, None)
assert action[0] == STRATEGY_ACTION_OPEN_LONG
print('signal chain ok')
"
```

---

## Commit

`feat: implement SignalChain sequential state machine`
