# Task 03: Crossover and Level Signals

**Phase:** 04 — Signal Library  
**Depends on:** Task 02 (atomic signals), Phase 03 Task 08 (Levels), design-decisions.md #28 (`SignalLevels` shape + `to_signal_levels()`)  
**Produces:** `signals_lib/common.py` — crossover signals and level proximity signals

---

## Goal

Implement crossover signals (indicator crosses value or another indicator) and level-based signals (price near/over/under support-resistance levels).

---

## Files

- Modify: `signals_lib/common.py`

---

## Crossover Signals to Implement

**`Cross_Up_Signal(tf: int, indi_1: str, indi_2: str)`**
- `check()` returns: current `indi_1 > indi_2` AND previous `indi_1 < indi_2`
- Uses `data_point.get(indi_1, tf, self.shift)` for current and `data_point.get(indi_1, tf, self.shift+1)` for previous

**`Cross_Down_Signal(tf: int, indi_1: str, indi_2: str)`**
- `check()` returns: current `indi_1 < indi_2` AND previous `indi_1 > indi_2`

**`Cross_Up_Val_Signal(tf: int, indi_1: str, val: float)`**
- `check()` returns: current `indi_1 > val` AND previous `indi_1 < val`

**`Cross_Down_Val_Signal(tf: int, indi_1: str, val: float)`**
- `check()` returns: current `indi_1 < val` AND previous `indi_1 > val`

---

## Level-Based Signals to Implement

**`Near_Level_Signal(tf: int, indi_1: str, level_type: int, buffer: float)`**
- Checks if `indi_1` is within `buffer` distance of any pre-interpolated price for `level_type`
- `check()`: for each `level_val` in `levels.get(level_type, [])`: if `abs(price - level_val) <= buffer` → True
- `get_data()` returns `{"level_val": level_val}` for the matched price — no level name available (see Key Constraints)

**`Near_Price_Level_Signal(tf: int, indi_1: str, level_type: int, buffer: float, buffer_indi: str)`**
- Same as `Near_Level_Signal` but buffer is dynamic: `effective_buffer = buffer × data_point.get(buffer_indi, tf, self.shift)` (here `buffer` is a coefficient/multiplier, typically a fraction; `buffer_indi` is usually `"atr_14"`)
- Delegates to an internal `Near_Level_Signal` instance on each tick; `set_shift()` propagates to the inner instance

**`Over_Level_Signal(tf: int, indi_1: str, level_type: int)`**
- `check()` returns True if `indi_1 > level_val` for any `level_val` in `levels.get(level_type, [])`

**`Under_Level_Signal(tf: int, indi_1: str, level_type: int)`**
- `check()` returns True if `indi_1 < level_val` for any `level_val` in `levels.get(level_type, [])`

---

## Key Constraints

- Crossover signals: if either current or previous value is NaN → return False
- Level signals receive `levels: SignalLevels` — a plain `Dict[int, List[float]]` mapping `level_type` → pre-interpolated prices, built fresh each tick by `Levels.to_signal_levels(data_point)` (design-decisions.md #28). This **replaces** the retired `get_levels_dict()` (phase-03 task-08) / `get_level_values()` / `levels.get_level_value(level_dict, cur_time)` path — signals never call `get_level_value` or pass `cur_time`, they only do plain float comparisons against `levels.get(level_type, [])`
- `levels.get(level_type, [])` may be `[]` if no levels of that type are active — return False in that case
- `Near_Level_Signal.get_data()` populates `level_val` only — `SignalLevels` carries interpolated floats, not level identities, so `cur_level_name` cannot be reported (strategy must locate the matching level by value if it needs the name)

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from signals_lib.common import Cross_Up_Val_Signal, Cross_Down_Val_Signal
from data import LiveDataPoint
import pandas as pd

# RSI crosses above 50
df = pd.DataFrame({'15_rsi_14': [48.0, 51.0]})
pt = LiveDataPoint({15: df})
sig = Cross_Up_Val_Signal(15, 'rsi_14', 50.0)
assert sig.check(pt, {}, None) == True  # 51 > 50 and prev 48 < 50

# Second tick: still above but no longer crossing
df2 = pd.DataFrame({'15_rsi_14': [51.0, 53.0]})
pt2 = LiveDataPoint({15: df2})
assert sig.check(pt2, {}, None) == False  # 53 > 50 but prev 51 also > 50
print('crossover signals ok')
"
```

---

## Commit

`feat: implement crossover and level proximity signals`
