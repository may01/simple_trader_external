# Task 08: Levels — Support/Resistance Level Management

**Phase:** 03 — Data Layer  
**Depends on:** Phase 00 (constants: LI_* keys, LEVEL_TYPE_*)  
**Produces:** `levels.py` — level loading, interpolation, and proximity checking

---

## Goal

Implement `Levels` — loads hand-drawn support/resistance levels from `shared/{pair}/levels.txt`, computes linear interpolation at any timestamp, and exposes proximity and cross-level checks used by signals.

---

## Context

Levels are static per pair (loaded once per process). They're slope lines defined by two `(time, price)` anchor points. `levels.get_level_value(level_dict, cur_time)` linearly interpolates the price at any timestamp. Signals use `Near_Level_Signal`, `Over_Level_Signal`, `Under_Level_Signal` etc. to check if price is near these levels.

---

## Files

- Create: `levels.py`

---

## Interface

**Level dict schema** (keys are `LI_*` constants from `constants.py`):

| Key | Type | Description |
|-----|------|-------------|
| `LI_NAME` | str | Level identifier |
| `LI_TIME1` | int | Start timestamp (Unix seconds) |
| `LI_VAL1` | float | Price at TIME1 |
| `LI_TIME2` | int | End timestamp (Unix seconds) |
| `LI_VAL2` | float | Price at TIME2 |
| `LI_ACTIVE` | bool | Whether level is currently active |
| `LI_TYPE` | int | `LEVEL_TYPE_*` constant |
| `LI_HAD_CONTACT` | bool | Whether price has touched this level |

**Levels class:**
- `__init__(thread_num: int = 0)` — loads `shared/{pair}/levels.txt`, parses level definitions
- `load(thread_num: int = 0) -> list[dict]` — static method; returns list of level dicts
- `get_active_levels(level_type: int, cur_time: float) -> list[dict]` — returns active levels of given type (`cur_time` is float, not int — matches phase-05/06 convention)
- `get_level_value(level_dict: dict, cur_time: float) -> float` — linear interpolation between TIME1/VAL1 and TIME2/VAL2
- `is_price_near_level(price: float, level: dict, atr: float, cur_time: float) -> bool` — price within `atr` distance of level
- `is_price_over_level(price: float, level: dict, cur_time: float) -> bool`
- `is_price_under_level(price: float, level: dict, cur_time: float) -> bool`
- `to_signal_levels(data_point) -> dict[int, list[float]]` — **replaces** `get_levels_dict()` (design-decisions.md #28). Calls `get_active_levels()` + `get_level_value()` for every active level of every `LEVEL_TYPE_*` constant, once per tick, and returns `{level_type: [interpolated_price, ...]}`. Called once per tick in `Strategy.check()` and passed down through `SignalManager` → `SignalChain` → `signal.check()` as the `levels: SignalLevels` parameter
- `get_levels_dict(data_point, ema_cols: list[str]) -> dict` — **RETIRED** (replaced by `to_signal_levels()`). Do not implement; kept here for reference only

---

## levels.txt Format

Text file, one level per line:
```
NAME TIME1 VAL1 TIME2 VAL2 TYPE ACTIVE
support_1 1693526400 20.50 1694736000 21.00 1 1
resistance_1 1693526400 25.00 1694736000 25.50 2 1
```

Level activation: `LI_TIME1 <= cur_time <= LI_TIME2` and `LI_ACTIVE == True`.

---

## Key Constraints

- Level activation times are Unix SECONDS — `DATA_START`/`DATA_END` env vars are milliseconds; divide by 1000 when comparing
- `LEVEL_TYPE_SHORT_1_RESISTANCE` and `LEVEL_TYPE_SHORT_2_RESISTANCE` do NOT exist — removed per design-decisions.md #16
- `LEVEL_TYPE_AUTO_SUPPORT` = 6, `LEVEL_TYPE_AUTO_RESISTANCE` = 7 (renamed from `LEVEL_TYPE_AUTO_TARGET_*`)
- `get_level_value()` uses linear interpolation — valid for `TIME1 <= cur_time <= TIME2`; extrapolates beyond if needed
- Levels file may be empty or absent — return empty list, do not raise
- `to_signal_levels()` is called fresh each tick in `Strategy.check()` — not cached (replaces the retired `get_levels_dict()` call)

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
import os; os.environ['PAIR'] = 'link_usdt'
from levels import Levels
from constants import LEVEL_TYPE_LONG_SUPPORT

lvls = Levels()
active = lvls.get_active_levels(LEVEL_TYPE_LONG_SUPPORT, 1693526400)
print('active support levels:', len(active))
if active:
    val = lvls.get_level_value(active[0], 1693526400)
    print('level value at t=start:', val)
print('levels ok')
"
```

---

## Commit

`feat: implement Levels — support/resistance loading, interpolation, proximity checks`
