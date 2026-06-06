# Task 02: Atomic Comparison Signals

**Phase:** 04 — Signal Library  
**Depends on:** Task 01 (BaseSignal)  
**Produces:** `signals_lib/common.py` — value comparison, difference, and direction signals

---

## Goal

Implement all atomic comparison signal types: value comparisons, difference comparisons, and direction-change signals. These are the primitive building blocks composed into chains and combinators.

---

## Files

- Create: `signals_lib/common.py`

---

## Signals to Implement

### Value Comparisons

**`Less_Signal(tf: int, indi_1: str, indi_2: str)`**
- `check()` returns `data_point.get(indi_1, tf, shift) < data_point.get(indi_2, tf, shift)`

**`Greater_Signal(tf: int, indi_1: str, indi_2: str)`**
- `check()` returns `data_point.get(indi_1, tf, shift) > data_point.get(indi_2, tf, shift)`

**`Less_Val_Signal(tf: int, indi_1: str, val: float)`**
- `check()` returns `data_point.get(indi_1, tf, shift) < val`

**`Greater_Val_Signal(tf: int, indi_1: str, val: float)`**
- `check()` returns `data_point.get(indi_1, tf, shift) > val`

### Direction Changes

**`Rising_Signal(tf: int, indi_1: str)`**
- `check()` returns `data_point.get(indi_1, tf, shift) > data_point.get(indi_1, tf, shift+1)`

**`Falling_Signal(tf: int, indi_1: str)`**
- `check()` returns `data_point.get(indi_1, tf, shift) < data_point.get(indi_1, tf, shift+1)`

### Difference Comparisons

**`Diff_Greater_Signal(tf: int, indi_1: str, indi_2: str, val: float)`**
- `check()` returns `(data_point.get(indi_1, tf, shift) - data_point.get(indi_2, tf, shift)) > val`

**`Diff_Less_Signal(tf: int, indi_1: str, indi_2: str, val: float)`**
- `check()` returns `(data_point.get(indi_1, tf, shift) - data_point.get(indi_2, tf, shift)) < val`

**`Diff_LessIndi_Signal(tf: int, indi_1: str, indi_2: str, indi_dist: str)`**
- `check()` returns `(indi_1 - indi_2) > 0 AND (indi_1 - indi_2) < data_point.get(indi_dist, tf, self.shift)`
- i.e. `indi_1 > indi_2` (diff positive) AND the gap is less than the threshold indicator — prevents firing on negative diffs (per `common-signals.md`)

**`Diff_GreaterIndi_Signal(tf_1: int, indi_1: str, tf_2: int, indi_2: str, tf_dist: int, indi_dist: str)`**
- Cross-timeframe: `(get(indi_1, tf_1) - get(indi_2, tf_2)) > 0 AND (get(indi_1, tf_1) - get(indi_2, tf_2)) > get(indi_dist, tf_dist)`
- i.e. diff positive AND greater than the threshold — `shift` (i.e., `self.shift`) applied uniformly to all three lookups

---

## Key Constraints

- All `check()` calls use `data_point.get(col, tf, self.shift + external_shift)` — the `self.shift` offset from `BaseSignal` is applied to EVERY `data_point.get()` call inside the signal
- `Rising_Signal` uses `shift` and `shift+1` — when `self.shift=2`, it compares `get(indi, tf, 2)` vs `get(indi, tf, 3)` (i.e., historical window shifts consistently)
- `NaN` comparisons: if `data_point.get()` returns `float("nan")`, the comparison should return False (not raise)
- `Diff_GreaterIndi_Signal` stores two TFs (`tf_1`, `tf_2`, `tf_dist`) — `set_shift()` applies to all three get() calls

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from signals_lib.common import Less_Signal, Greater_Val_Signal, Rising_Signal
from data import LiveDataPoint
import pandas as pd

df = pd.DataFrame({'5_rsi_14': [30.0, 45.0, 50.0], '5_close': [20.0, 21.0, 22.0]})
pt = LiveDataPoint({5: df})

sig = Less_Signal(5, 'rsi_14', 'close')
assert sig.check(pt, {}, None) == False  # 50 < 22 is False
sig2 = Greater_Val_Signal(5, 'rsi_14', 40.0)
assert sig2.check(pt, {}, None) == True  # 50 > 40

sig3 = Rising_Signal(5, 'rsi_14')
assert sig3.check(pt, {}, None) == True  # 50 > 45
print('atomic signals ok')
"
```

---

## Commit

`feat: implement atomic comparison signals — Less, Greater, Diff, Rising, Falling`
