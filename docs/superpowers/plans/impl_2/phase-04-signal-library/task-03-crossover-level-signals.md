# Task 03: Crossover and Level Signals

**Phase:** 04 — Signal Library  
**Depends on:** Task 02 (atomic signals), Phase 03 Task 08 (Levels)  
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
- Checks if `indi_1` is within `buffer` distance of any active level of `level_type`
- `check()`: for each active level of `level_type` in `levels`: if `abs(price - level_value) <= buffer` → True
- `get_data()` returns `{"cur_level_name": name, "level_val": value}` for the matched level

**`Near_Price_Level_Signal(tf: int, indi_1: str, level_type: int, buffer: float, buffer_indi: str)`**
- Like `Near_Level_Signal` but buffer scaled by `data_point.get(buffer_indi, tf)` value

**`Over_Level_Signal(tf: int, indi_1: str, level_type: int)`**
- `check()` returns True if `indi_1 > level_value` for any active level of `level_type`

**`Under_Level_Signal(tf: int, indi_1: str, level_type: int)`**
- `check()` returns True if `indi_1 < level_value` for any active level of `level_type`

---

## Key Constraints

- Crossover signals: if either current or previous value is NaN → return False
- Level signals receive `levels` dict from `Strategy.get_level_values()` — this dict may be empty if no levels of that type are active; return False in that case
- `Near_Level_Signal.get_data()` populates `cur_level_name` and `level_val` — strategy uses these for stop-loss positioning
- Level values are linearly interpolated at current time — use `levels.get_level_value(level_dict, cur_time)` where `cur_time` is passed via `action.cur_time` or computed from data_point

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
