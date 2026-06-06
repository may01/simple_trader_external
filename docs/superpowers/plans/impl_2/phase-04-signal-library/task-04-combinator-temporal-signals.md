# Task 04: Combinator and Temporal Signals

**Phase:** 04 — Signal Library  
**Depends on:** Task 01 (BaseSignal)  
**Produces:** `signals_lib/operations.py` — AND/OR/NOT, History, Continuous, BoolValue, and utility signals

---

## Goal

Implement combinator signals (logical composition) and temporal signals (history lookback, persistence counting). These allow complex multi-condition and multi-candle patterns to be expressed declaratively.

---

## Files

- Create: `signals_lib/operations.py`

---

## Boolean Combinators

**`And_Signal(signals: list[BaseSignal])`**
- `check()` returns `all(s.check(data_point, levels, action) for s in signals)`
- `set_shift(shift)` propagates to ALL nested signals

**`Or_Signal(signals: list[BaseSignal])`**
- `check()` returns `any(s.check(data_point, levels, action) for s in signals)`
- `set_shift(shift)` propagates to ALL nested signals

**`Not_Signal(signal: BaseSignal)`**
- `check()` returns `not signal.check(data_point, levels, action)`
- `set_shift(shift)` propagates to nested signal

---

## Temporal Signals

**`History_Signal(signal: BaseSignal, history: int)`**
- Evaluates `signal` at a historical offset relative to the wrapper's own shift: calls `signal.set_shift(self.history + self.shift)` then `signal.check(...)`
- Does **not** restore the child's shift afterward, and does **not** use the normal recursive `set_shift()` propagation path — it overrides the child's shift directly each time it checks (per `operations-signals.md`: "overrides the child's shift directly... the child signal's shift is always `history` relative to the caller's shift context"). No TBD: restoration is moot since `set_shift` is always called again before the next `check()`
- All `Cross_*_Signal` implementations build on `History_Signal` internally (per spec)
- Example: `History_Signal(Greater_Signal(15, "rsi_14", 50), 1)` checks if RSI was above 50 one candle ago

**`Continuous_Signal(signal: BaseSignal, history: int, multiply: int = 1)`**
- Fires if signal is True at least `multiply` times across last `history` candles
- Evaluates `signal.set_shift(i)` for `i` in `range(history)`, counts True results
- Returns True if count >= multiply

---

## Boolean Utility Signals

**`True_Signal()`**
- `check()` always returns True
- Useful as placeholder or for testing

**`False_Signal()`**
- `check()` always returns False

**`BoolValue_Signal(value: str, tf: int)`**
- Reads a boolean indicator column: `data_point.get(value, tf, self.shift) == True` (or truthy)
- Example: `BoolValue_Signal("trend_up", 60)` fires when 60m trend_up column is True
- Used for trend gating inside signal chains

**`PersistentCounter_Signal(fire_each: int)`**
- Global counter incremented each time `check()` is called
- Returns True every `fire_each` calls
- Useful for periodic evaluation

**`DataValue_Signal(data_name: str, value, value_set: bool)`**
- Metadata-injection wrapper, not a comparison: `check()` simply returns `self.value_set` (the armed/fired flag — note the constraint, fixing the plan's `value_set: str` typo to `bool`)
- `set_value(val)` — arms the signal: sets `self.value = val`, `self.value_set = True`
- `get_data()` returns `{self.data_name: self.value}` once armed/fired
- Usage pattern: construct disarmed (`DataValue_Signal("cur_level_name", None, False)`), call `set_value("Support_1")` elsewhere when the bound value is known, then add to chain — `check()` then fires and `get_data()` exports the bound value
- **Footgun (per spec, carry into implementation):** breaks when wrapped inside `And_Signal`/`Or_Signal` — those combinators don't propagate child `get_data()` to the chain (only `SignalChain.get_action()` aggregates `s.get_data()` across its top-level `signals` list). Only place `DataValue_Signal` directly in a chain, not nested inside a combinator, if its metadata must reach `get_action()`

---

## Key Constraints

- `set_shift()` in ALL combinator signals MUST propagate recursively to nested signals — failure to do so breaks History_Signal semantics
- `Continuous_Signal` applies shift sequentially: `shift=0` is current, `shift=1` is prev, etc. It modifies `signal.shift` during evaluation — must restore to original after
- `And_Signal` evaluates ALL nested signals (no short-circuit) to allow `get_data()` collection from all; OR short-circuits after first True match
- `BoolValue_Signal` — `data_point.get()` returns float; treat any nonzero value as True

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from signals_lib.common import Greater_Val_Signal
from signals_lib.operations import And_Signal, Not_Signal, BoolValue_Signal, History_Signal
from data import LiveDataPoint
import pandas as pd

df = pd.DataFrame({'5_rsi_14': [30.0, 55.0, 60.0], '5_trend_up': [1.0, 1.0, 1.0]})
pt = LiveDataPoint({5: df})

sig_and = And_Signal([
    Greater_Val_Signal(5, 'rsi_14', 50),
    BoolValue_Signal('trend_up', 5)
])
assert sig_and.check(pt, {}, None) == True

sig_not = Not_Signal(Greater_Val_Signal(5, 'rsi_14', 70))
assert sig_not.check(pt, {}, None) == True  # 60 < 70, so NOT fires

print('combinator signals ok')
"
```

---

## Commit

`feat: implement And/Or/Not combinators, History, Continuous, BoolValue signals`
