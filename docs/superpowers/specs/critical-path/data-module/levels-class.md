# Levels Class Specification

**File:** `levels.py`  
**Class:** `Levels`  
**Category:** Data Module — Support/Resistance Level Manager  
**Status:** Production (Partially Functional)

---

## 1. Class Overview

The **Levels** class manages **support and resistance price levels** for trading strategies. It supports:
- **Hand-drawn levels** loaded from a CSV file (`levels.txt`)
- **Auto-detected levels** generated during simulation/trading
- **Slope-based interpolation** for dynamic level values over time
- **Level activation/deactivation** based on time windows
- **Multiple timeframes** (minute, hour, day candles)

### Design Pattern
- **Stateful container**: Stores level data across multiple timeframes
- **Interpolation-based**: Levels have start (time1, val1) and end (time2, val2) points; price interpolated linearly over time
- **Time-windowed**: Levels are only active within specified time ranges
- **File-based persistence**: Loads hand-drawn levels from CSV; saves auto-levels to pickle

### Key Characteristics
- Levels organized by timeframe (15, 60, 240 minutes)
- Support for level types: support, resistance, target, auto-detected
- Contact tracking for level interactions
- Extension mechanism when prices touch existing levels

---

## 2. Key Attributes

| Attribute | Type | Purpose | Initialization |
|-----------|------|---------|-----------------|
| `levels_by_time` | `dict[int, list[dict]]` | Levels indexed by timeframe (15, 60, 240 min); each value is a list of level dictionaries | `{}` in `__init__`, populated via `load()` |
| `levels` | `list[dict]` | Combined list of all active levels across all timeframes (unused in core logic) | `[]` class-level; rarely modified |
| `levels_d` | `list[dict]` | Hand-drawn levels for daily timeframe | `[]` class-level; populated via `load()` |
| `levels_h` | `list[dict]` | Hand-drawn levels for hourly timeframe | `[]` class-level; populated via `load()` |
| `levels_m` | `list[dict]` | Hand-drawn levels for minute timeframe | `[]` class-level; populated via `load()` |
| `cur_level` | `dict` | Current/working level (often initialized to `empty_level`) | `empty_level` |
| `empty_level` | `dict` | Template for inactive levels; used as default | Predefined with `LI_ACTIVE: False`, other keys zeroed |
| `save_on_add` | `bool` | If `True`, persist levels to pickle file after each `add_level()` call | Constructor parameter (default: `False`) |
| `predicted_levels` | `dict` | Reserved for future predictive levels (unused) | `{}` |

### LEVELS_LIST Constant
```python
LEVELS_LIST = {15, 60, 240}  # Supported timeframes in minutes
```

---

## 3. Level Dictionary Schema

Each level is a dictionary with the following keys (using constants from `constants.py`):

| Key | Constant | Type | Description |
|-----|----------|------|-------------|
| `"name"` | `LI_NAME` | `str` | Unique identifier for the level (e.g., "15_1234567_5500.5") |
| `"time1"` | `LI_TIME1` | `int` | Start timestamp (Unix seconds); level becomes active after this time |
| `"val1"` | `LI_VAL1` | `float` | Price value at time1; start point for slope interpolation |
| `"time2"` | `LI_TIME2` | `int` | End timestamp (Unix seconds); level becomes inactive after this time |
| `"val2"` | `LI_VAL2` | `float` | Price value at time2; end point for slope interpolation |
| `"active"` | `LI_ACTIVE` | `bool` | Whether the level is currently active; used to filter valid levels |
| `"type"` | `LI_TYPE` | `int` | Level type; see **Level Types** section below |
| `"had_contact"` | `LI_HAD_CONTACT` | `bool` | Whether price has touched this level (contact tracking) |

**Example Level Dictionary:**
```python
{
    "name": "15_1609459200_5500.25",
    "time1": 1609459200,
    "val1": 5500.25,
    "time2": 1609545600,
    "val2": 5498.50,
    "active": True,
    "type": LEVEL_TYPE_SUPPORT,
    "had_contact": False
}
```

### Notes on Schema
- `time1` < `time2` always holds; defines the level's validity window
- `val1` may equal or differ from `val2` (slope or horizontal level)
- Time values are in Unix epoch seconds
- Extra keys may be present (legacy: `"first_activation"`, `"validity_time"`)

---

## 4. Level Types

Levels are categorized by type using integer constants from `constants.py`:

| Constant | Value | Description | Usage |
|----------|-------|-------------|-------|
| `LEVEL_TYPE_NONE` | 0 | No level type (default/invalid) | Placeholder |
| `LEVEL_TYPE_LONG_SUPPORT` | 1 | Support level for long trades | Manual entry levels |
| `LEVEL_TYPE_LONG_RESISTANCE` | 2 | Resistance level for long trades | Manual exit/target levels |
| `LEVEL_TYPE_SHORT_SUPPORT` | 3 | Support level for short trades | Manual exit/target levels |
| `LEVEL_TYPE_SHORT_RESISTANCE` | 4 | Resistance level for short trades | Manual entry levels |
| `LEVEL_TYPE_TARGET` | 5 | Take-profit target level | Manual target levels |
| `LEVEL_TYPE_AUTO_SUPPORT` | 6 | Auto-detected support from trend reversal | Simulation-generated |
| `LEVEL_TYPE_AUTO_RESISTANCE` | 7 | Auto-detected resistance from trend reversal | Simulation-generated |

**Notes:**
- Auto-levels (types 6, 7) are generated during simulation; hand-levels (types 1-5) are loaded from CSV
- Type determines signal interpretation and strategy behavior
- Type can change dynamically; e.g., a resistance level may flip to support on breakout (see `init_hand_levels()`)

---

## 5. Constructor

### `__init__(save_on_add: bool = False) → None`

Initializes an empty Levels instance.

**Signature:**
```python
def __init__(self, save_on_add=False):
```

**Parameters:**
- `save_on_add` (bool, optional): If `True`, levels are persisted to pickle file after each `add_level()` call. Default: `False`.

**Behavior:**
- Initializes `levels_by_time` dict with empty lists for each timeframe in `LEVELS_LIST` (15, 60, 240)
- Sets `cur_level` to `empty_level`
- Initializes `predicted_levels` to empty dict
- Does NOT load levels from files; use `load()` after construction

**Initialization Example:**
```python
levels = Levels(save_on_add=False)
# levels.levels_by_time = {15: [], 60: [], 240: []}
# levels.cur_level = {LI_ACTIVE: False, ...}
```

---

## 6. Key Methods

### 6.1 Data Loading

#### `load(thread_num: int, load_auto_levels: bool = False) → None`

Loads hand-drawn levels from a CSV file and optionally auto-levels from a pickle file.

**Signature:**
```python
def load(self, thread_num, load_auto_levels=False):
```

**Parameters:**
- `thread_num` (int): Thread number; used to construct pickle filename for auto-levels (e.g., `levels_0.pkl`, `levels_1.pkl`)
- `load_auto_levels` (bool, optional): If `True`, also load auto-levels from pickle file. Default: `False`.

**File Formats:**

**Hand-drawn levels (CSV):** `{shared_folder}/{pair}/levels.txt`
```
level_name, timeframe, time1, val1, time2, val2, type_alias, time_to_live_hours, activation_time
```
Example:
```
support_1, M, 1609459200, 5500.5, 1609545600, 5498.0, S, 24, 1609459200
resistance_1, H, 1609459200, 5550.0, 1609545600, 5552.0, R, 48, 1609459200
```

**Parsing:**
- `timeframe`: "D" (daily), "H" (hourly), "M" (minute)
- `type_alias`: "S" (support) → `LEVEL_TYPE_SUPPORT`, "R" (resistance) → `LEVEL_TYPE_RESISTANCE`
- `time_to_live_hours`: Hours until level expires; converted to seconds and added to `time2` as `time3`
- `activation_time`: When the level becomes valid; start time adjusted by 3-hour offset

**Processing:**
1. Parse each line into components
2. Interpolate `val1` using `get_slope_level_value_by_time(t2, v2, t1, v1, activation_time)`
3. Interpolate `val3` (final value) using `get_slope_level_value_by_time(t1, v1, t2, v2, t3)`
4. Add to appropriate list (`levels_d`, `levels_h`, `levels_m`) with adjusted timestamps
5. Set `LI_ACTIVE: True` for all loaded levels

**Auto-levels (pickle):** `{shared_folder}/{pair}/levels_{thread_num}.pkl`
- Binary pickle file containing the `levels_by_time` dict
- Loaded into `self.levels_by_time` if `load_auto_levels=True`

**Error Handling:**
- If `levels.txt` does not exist, logs error and continues (empty hand-levels)
- If pickle file does not exist with `load_auto_levels=True`, logs error and continues (empty auto-levels)

**Example Usage:**
```python
levels = Levels()
levels.load(thread_num=0, load_auto_levels=False)  # Load hand-drawn levels only
# levels.levels_d, levels.levels_h, levels.levels_m now populated
```

---

#### `save(thread_num: int) → None`

Persists auto-levels to a pickle file.

**Signature:**
```python
def save(self, thread_num):
```

**Parameters:**
- `thread_num` (int): Thread number; used to construct filename (e.g., `levels_0.pkl`)

**Behavior:**
- Serializes `self.levels_by_time` dict to `{shared_folder}/{pair}/levels_{thread_num}.pkl`
- Called automatically by `add_level()` if `self.save_on_add = True`

**Example:**
```python
levels.save(thread_num=0)  # Writes to levels_0.pkl
```

---

### 6.2 Level Management

#### `add_level(lvl_val: float, t: int, cur_timestamp: int, atr: float, level_type: int, add_to_hand: bool) → None`

Adds a new level or extends an existing nearby level.

**Signature:**
```python
def add_level(self, lvl_val, t, cur_timestamp, atr, level_type, add_to_hand):
```

**Parameters:**
- `lvl_val` (float): Price value of the level to add
- `t` (int): Timeframe in minutes (15, 60, or 240)
- `cur_timestamp` (int): Current timestamp (Unix seconds) when level is created
- `atr` (float): Average True Range; used to define "nearness" thresholds
- `level_type` (int): Type constant (e.g., `LEVEL_TYPE_SUPPORT`)
- `add_to_hand` (bool): If `True` and `t == 15`, also add to `levels_m` (hand-drawn list)

**Behavior:**

**Step 1: Check for nearby active levels to extend**
- Iterate through `levels_by_time[t]`
- If `abs(lvl_val - existing_level_val1) < 0.1 * atr` and level is active, extend `time2`:
  - `level[LI_TIME2] = cur_timestamp + 60 * t * minute` (60 candles from now)
  - Mark as processed (`skip = True`)

**Step 2: Check for loosely nearby levels to extend (0.6 * atr threshold)**
- If no exact match found, check for loosely nearby levels:
  - If `abs(lvl_val - existing_level_val1) < 0.6 * atr` and active, extend `time2` similarly
  - Mark as processed

**Step 3: Create new level if no nearby level found**
- Calculate start time: `start = cur_timestamp` (or `cur_timestamp + t * minute` if `t < 60`)
- Set `level_size = 45` (if `t < 15`) or `60` candles
- Append new level dict with:
  - `LI_NAME`: Auto-generated as `"{t}_{start}_{lvl_val}"`
  - `LI_TIME1`: `start`
  - `LI_VAL1`: `lvl_val`
  - `LI_TIME2`: `cur_timestamp + level_size * t * minute`
  - `LI_VAL2`: `lvl_val` (horizontal level)
  - `LI_ACTIVE`: `True`
  - `LI_TYPE`: `level_type`
  - `LI_HAD_CONTACT`: `False`

**Step 4: Add to hand-drawn levels (optional)**
- If `add_to_hand = True` and `t == 15`, also append the new level to `levels_m`

**Step 5: Persist (conditional)**
- If `self.save_on_add = True`, call `save("full")`

**Error Handling:**
- No explicit error handling; invalid timeframes silently fail to add

**Example:**
```python
levels.add_level(
    lvl_val=5500.5,
    t=15,
    cur_timestamp=1609459200,
    atr=2.5,
    level_type=LEVEL_TYPE_SUPPORT,
    add_to_hand=True
)
# If no nearby level exists, new level added to levels_by_time[15]
# If within 0.1 * atr of existing level, that level's time2 is extended
```

---

### 6.3 Level Interpolation

#### `get_level_value(lvl: dict, cur_time: int) → float`

Returns the price value of a level at a given timestamp using linear interpolation.

**Signature:**
```python
def get_level_value(self, lvl, cur_time):
```

**Parameters:**
- `lvl` (dict): Level dictionary with `LI_TIME1`, `LI_VAL1`, `LI_TIME2`, `LI_VAL2`
- `cur_time` (int): Current timestamp (Unix seconds) for interpolation

**Returns:**
- `float`: Interpolated price value at `cur_time`

**Behavior:**

**Flat level (val1 == val2):**
- Returns `lvl[LI_VAL1]` (no interpolation needed)

**Sloped level (val1 != val2):**
- Performs linear interpolation between (time1, val1) and (time2, val2)
- Formula:
  ```
  pos_coef = (time2 - cur_time) / (time2 - time1)
  result = val2 - pos_coef * (val2 - val1)
  ```
- At `cur_time = time1`: result = `val1`
- At `cur_time = time2`: result = `val2`
- At `cur_time < time1` or `cur_time > time2`: extrapolates linearly (may be outside intended range)

**Example:**
```python
level = {
    LI_TIME1: 1000,
    LI_VAL1: 100.0,
    LI_TIME2: 2000,
    LI_VAL2: 110.0,
}
# At time 1500 (midpoint):
value = levels.get_level_value(level, 1500)
# pos_coef = (2000 - 1500) / (2000 - 1000) = 0.5
# result = 110.0 - 0.5 * (110.0 - 100.0) = 105.0
```

---

### 6.4 Level Activation/Contact

#### `is_active(l: dict, cur_point: int) → bool`

Checks if a level is currently active based on the current timestamp.

**Signature:**
```python
def is_active(self, l, cur_point):
```

**Parameters:**
- `l` (dict): Level dictionary with `LI_TIME1` and `LI_TIME2`
- `cur_point` (int): Current timestamp (Unix seconds)

**Returns:**
- `bool`: `True` if `time1 < cur_point < time2`; `False` otherwise

**Behavior:**
- Simple time-window check; does not consider `LI_ACTIVE` flag
- Note: boundary conditions are strict inequalities; endpoint times are NOT included

**Example:**
```python
level = {LI_TIME1: 1000, LI_TIME2: 2000}
levels.is_active(level, 1500)  # True
levels.is_active(level, 1000)  # False (boundary)
levels.is_active(level, 2000)  # False (boundary)
```

---

#### `is_price_near_level(price: float, level: dict, atr: float, cur_time: int) → bool`

Checks if a price is within a proximity threshold of a level.

**Signature:**
```python
def is_price_near_level(self, price, level, atr, cur_time):
```

**Parameters:**
- `price` (float): Current price to check
- `level` (dict): Level dictionary
- `atr` (float): Average True Range; defines the proximity zone (0.2 * atr)
- `cur_time` (int): Current timestamp (used for level interpolation)

**Returns:**
- `bool`: `True` if `abs(level_value - price) < 0.2 * atr`; `False` otherwise

**Behavior:**
- Interpolates level value at `cur_time` using `get_level_value()`
- Compares distance to ATR-based threshold
- Note: Method signature has a bug (extra `cur_time` parameter in call); see **Error Handling** section

**Example:**
```python
atr = 2.5
near = levels.is_price_near_level(5500.5, level, atr, 1500)
# True if abs(interpolated_level - 5500.5) < 0.5  (0.2 * 2.5)
```

---

#### `had_contact(level: dict) → bool`

Checks if a level has been contacted (touched by price).

**Signature:**
```python
def had_contact(self, level):
```

**Parameters:**
- `level` (dict): Level dictionary with `LI_HAD_CONTACT` key

**Returns:**
- `bool`: Value of `level[LI_HAD_CONTACT]`

**Behavior:**
- Simple accessor; does not modify level state
- Contact tracking is managed externally (e.g., in `update()` or strategy code)

---

### 6.5 Level Range Queries

#### `get_min_level_val_limit(limit_val: float, cur_time: int) → dict`

Finds the minimum-valued active level above a specified price limit.

**Signature:**
```python
def get_min_level_val_limit(self, limit_val, cur_time):
```

**Parameters:**
- `limit_val` (float): Lower price boundary; returned level must have value > this
- `cur_time` (int): Current timestamp for level interpolation

**Returns:**
- `dict`: Level dictionary with minimum value >= `limit_val`, or `cur_level` (default) if none found

**Behavior:**
- Iterates through `self.levels`
- Filters for active levels (`LI_ACTIVE = True`) with interpolated value > `limit_val`
- Selects level with minimum interpolated value
- Logs warning if no valid level found and `cur_level` is returned

**Example:**
```python
# Find closest support level above 5500
min_level = levels.get_min_level_val_limit(limit_val=5500.0, cur_time=1500)
# Returns level with smallest interpolated value >= 5500
```

---

#### `get_max_level_val_limit(limit_val: float, cur_time: int) → dict`

Finds the maximum-valued active level below a specified price limit.

**Signature:**
```python
def get_max_level_val_limit(self, limit_val, cur_time):
```

**Parameters:**
- `limit_val` (float): Upper price boundary; returned level must have value < this
- `cur_time` (int): Current timestamp for level interpolation

**Returns:**
- `dict`: Level dictionary with maximum value <= `limit_val`, or `cur_level` if none found

**Behavior:**
- Iterates through `self.levels`
- Filters for active levels with interpolated value < `limit_val`
- Selects level with maximum interpolated value
- Logs warning if no valid level found

**Example:**
```python
# Find closest resistance level below 5550
max_level = levels.get_max_level_val_limit(limit_val=5550.0, cur_time=1500)
# Returns level with largest interpolated value <= 5550
```

---

#### `get_level_by_name(levels_list: list, name: str) → tuple(bool, dict)`

Searches for a level by name across multiple level lists and auto-level storage.

**Signature:**
```python
def get_level_by_name(self, levels_list, name):
```

**Parameters:**
- `levels_list` (list): List of level lists to search (e.g., `[levels_d, levels_h, levels_m]`)
- `name` (str): Level name (e.g., "support_1", "15_1234567_5500.5")

**Returns:**
- `tuple`: `(found: bool, level: dict)`
  - If found: `(True, level_dict)`
  - If not found: `(False, empty_level)`

**Behavior:**
- Iterates through provided `levels_list`
- Then searches `levels_by_time` dict for all timeframes
- Returns first match or `empty_level` if none found

**Example:**
```python
found, level = levels.get_level_by_name([levels_d, levels_h], "support_1")
if found:
    print(f"Found: {level[LI_NAME]}")
```

---

### 6.6 Utility Methods

#### `get_cur_level() → dict`

Returns the current/working level.

**Signature:**
```python
def get_cur_level(self):
```

**Returns:**
- `dict`: The current level stored in `self.cur_level`

**Behavior:**
- Simple accessor; no side effects

---

#### `update(cur_price: float, low_price: float, high_price: float, cur_point: int, atr: float, action: Action) → None`

Updates level state based on current price action (currently non-functional).

**Signature:**
```python
def update(self, cur_price, low_price, high_price, cur_point, atr, action):
```

**Parameters:**
- `cur_price` (float): Current price
- `low_price` (float): Low price in current candle
- `high_price` (float): High price in current candle
- `cur_point` (int): Current timestamp
- `atr` (float): Average True Range
- `action` (Action): Action object to record level interactions

**Behavior:**
- Currently has no active code (all logic is commented out)
- Was intended to track contact events and update action object
- Returns immediately without modifications

**Note:** This method is deprecated/incomplete; level updates are handled in strategy code.

---

### 6.7 Auto-Level Detection (Legacy)

#### `init_auto_levels(t: int) → None`

Detects support/resistance levels from price reversals during backtesting.

**Status:** Partially implemented; typically called from strategy manager.

**Behavior:**
- Iterates through historical candles for timeframe `t`
- Detects 3-candle reversal patterns (price stopped falling/rising)
- Calls `add_level()` for detected support/resistance levels
- Adds to hand-drawn list if CCI indicator confirms trend (CCI > 100 for support, < -100 for resistance)

**Example Detection Logic:**
```python
# Pseudo-code
for i in range(5, data_size):
    if price_stopped_falling():
        add_level(support_level, t, timestamp, atr, LEVEL_TYPE_SUPPORT, add_to_hand)
    if price_stopped_rising():
        add_level(resistance_level, t, timestamp, atr, LEVEL_TYPE_RESISTANCE, add_to_hand)
```

---

#### `init_hand_levels(t: int) → None`

Validates and adapts hand-drawn levels based on recent price action.

**Status:** Partially implemented; typically called from strategy manager.

**Behavior:**
- Iterates through hand-drawn levels (`levels_d`, `levels_h`, `levels_m`)
- Checks 3-candle confirmation:
  - If resistance level is consistently broken (open/close below level), flips to support
  - If support level is consistently broken (open/close above level), flips to resistance
- Modifies level type in-place based on market behavior

**Example:**
```python
# If level is marked as RESISTANCE but price closes below for 3 candles:
l[LI_TYPE] = LEVEL_TYPE_SUPPORT  # Flip type
```

---

## 7. Module-Level Functions

#### `get_slope_level_value_by_time(t1: int, v1: float, t2: int, v2: float, t3: int) → float`

Standalone function that interpolates a level value at time `t3` given two reference points.

**Signature:**
```python
def get_slope_level_value_by_time(t1, v1, t2, v2, t3):
```

**Parameters:**
- `t1` (int): First reference timestamp
- `v1` (float): Price value at time `t1`
- `t2` (int): Second reference timestamp
- `v2` (float): Price value at time `t2`
- `t3` (int): Target timestamp for interpolation

**Returns:**
- `float`: Interpolated price value at `t3`

**Formula:**
```
result = ((t3 - t2) / (t1 - t2)) * (v1 - v2) + v2
```

**Behavior:**
- Performs linear interpolation (or extrapolation) across time
- Used internally during `load()` to adjust level values when loading from CSV
- Works for any time ordering; result depends on relative positions

**Example:**
```python
# Interpolate between two points
result = get_slope_level_value_by_time(
    t1=1000, v1=100.0,
    t2=2000, v2=110.0,
    t3=1500
)
# result = ((1500 - 2000) / (1000 - 2000)) * (100 - 110) + 110 = 105.0
```

---

## 8. Slope Level Interpolation

### Concept

Levels are not always static horizontal lines; they can slope over time. This allows modeling of:
- Gradual support level erosion (price decaying)
- Rising resistance levels (price increasing)
- Time-decaying support/resistance zones

### Implementation

**Linear Interpolation Formula:**
```
pos_coef = (time2 - cur_time) / (time2 - time1)
level_value = val2 - pos_coef * (val2 - val1)
```

**Interpretation:**
- At `time1`: `pos_coef = 1`, result = `val1`
- At midpoint `(time1 + time2) / 2`: `pos_coef = 0.5`, result = `(val1 + val2) / 2`
- At `time2`: `pos_coef = 0`, result = `val2`

### Example Scenarios

**Horizontal Level (val1 == val2 = 5500):**
```
All interpolations return 5500.0 (flat support line)
```

**Rising Resistance (val1 = 5500 at t1, val2 = 5550 at t2):**
```
At mid-time: interpolated value = 5525 (average)
Models gradually rising resistance as time progresses
```

**Time-Decaying Support (val1 = 5500 at t1, val2 = 5490 at t2):**
```
Support level gradually weakens (drops) over time
Models decay in level significance as time passes
```

### Extrapolation Behavior (Edge Case)

If `cur_time < time1` or `cur_time > time2`, the formula still produces values by extrapolating the slope:
- The level extends beyond its intended validity window
- This may be unintended; strategy code should validate `is_active()` before using extrapolated values

---

## 9. Auto-Level Detection

### Pattern Recognition

Auto-levels are detected during backtesting by identifying **3-candle reversal patterns**:

**Support Level (price stopped falling):**
1. Candle 1: High > 0, forms local low
2. Candle 2: High > Candle 1 low, continues declining
3. Candle 3: High > Candle 2 low, reversal signal
4. Low point across all 3 candles marks support level

**Resistance Level (price stopped rising):**
1. Candle 1: Low < previous high, forms local high
2. Candle 2: Low < Candle 1 high, continues rising
3. Candle 3: Low < Candle 2 high, reversal signal
4. High point across all 3 candles marks resistance level

### Validation via CCI

CCI (Commodity Channel Index) filters which detected levels are added to hand-drawn lists:
- **Support**: Added to `levels_m` if `CCI > 100` (strong uptrend)
- **Resistance**: Added to `levels_m` if `CCI < -100` (strong downtrend)

Levels without CCI validation are added to auto-level storage but not hand-drawn lists.

### Level Extension

When a new level is added and a nearby level exists (within ATR-based threshold), the existing level's `time2` (end time) is extended instead of creating a duplicate:
- Nearby threshold: `0.1 * atr` (exact match)
- Loose threshold: `0.6 * atr` (fuzzy match)
- Extension duration: `60 * timeframe * 60 seconds` (60 candles forward)

---

## 10. Error Handling

### File I/O Errors

| Error | Location | Behavior |
|-------|----------|----------|
| `levels.txt` not found | `load()` | Logs error; continues with empty hand-levels |
| `levels_{thread_num}.pkl` not found | `load(load_auto_levels=True)` | Logs error; continues with empty auto-levels |
| Invalid line format in CSV | `load()` | May raise exception during parsing (not caught); consider adding validation |

### Data Validation Issues

| Issue | Current Behavior | Recommendation |
|-------|------------------|-----------------|
| `time1 >= time2` | No validation; interpolation may fail | Should reject levels where `time1 < time2` condition violated |
| `val1 == val2 == 0` | Accepted as flat level | Consider rejecting zero-valued levels |
| `cur_time` outside level window in `get_level_value()` | Extrapolates linearly | Should validate via `is_active()` before use |
| Missing keys in level dict | May raise KeyError | Should use dict.get() with defaults |

### Method-Specific Issues

**`is_price_near_level()` Bug:**
- Method signature includes `cur_time` parameter but call site may not pass it
- Line 222: `abs(self.get_level_value(level)-price , cur_time)` has syntax error (comma instead of second param)
- Should be: `abs(self.get_level_value(level, cur_time) - price) < 0.2*atr`

---

## 11. Data Persistence

### File Structure

```
{shared_folder}/{pair}/
├── levels.txt              # Hand-drawn levels (CSV format)
├── levels_0.pkl            # Auto-levels for thread 0 (pickle)
├── levels_1.pkl            # Auto-levels for thread 1 (pickle)
└── levels_full.pkl         # Auto-levels merged from all threads
```

### Workflow

1. **Initialization**: `load(thread_num=0, load_auto_levels=False)` loads hand-drawn levels only
2. **Simulation**: `add_level()` creates auto-levels in memory; optionally calls `save()` if `save_on_add=True`
3. **Persistence**: `save(thread_num)` serializes `levels_by_time` to pickle
4. **Reload**: Next run can call `load(thread_num=0, load_auto_levels=True)` to resume with previous auto-levels

### Pickle Format

```python
# levels_{thread_num}.pkl contains:
{
    15: [level1_dict, level2_dict, ...],
    60: [level3_dict, level4_dict, ...],
    240: [level5_dict, level6_dict, ...]
}
```

---

## 12. Existing Approach

### Current Implementation Status

**Strengths:**
- Simple CSV-based manual level definition
- Fast pickle-based auto-level persistence
- ATR-based proximity thresholds prevent level clustering
- Slope interpolation enables dynamic level evolution over time
- Contact tracking available for level interaction analysis

**Limitations:**
- Hand-drawn levels must be manually maintained in CSV file
- Auto-level detection limited to 3-candle reversals (limited pattern recognition)
- No clustering of nearby levels (may create redundant levels at similar prices)
- Level type can flip dynamically (may cause strategy confusion)
- No predictive level generation (levels are reactive, not proactive)
- CCI-based filtering is somewhat arbitrary

### Known Issues

1. **Incomplete `update()` method**: Level-price contact tracking is not active
2. **`is_price_near_level()` bug**: Syntax error in method implementation
3. **No validation**: CSV parsing and level data have minimal validation
4. **Timeframe mismatch**: `levels_by_time` used for auto-levels but `levels_d/h/m` used for hand-levels (inconsistent)

---

## 13. Potential Improvements

### Short-Term (Quick Wins)

1. **Fix `is_price_near_level()` method**: Correct the syntax error and enable contact tracking
2. **Activate `update()` method**: Implement level-price contact detection
3. **Add input validation**: Validate CSV format, level time windows, and price ranges
4. **Unify level storage**: Use `levels_by_time` for both hand-drawn and auto-levels instead of separate lists

### Medium-Term (Architectural)

5. **Level Clustering**: Merge nearby levels (within 0.3 * atr) to reduce redundancy
6. **Zone Management**: Replace point levels with price zones (level +/- tolerance)
7. **Dynamic Level Adjustment**: Adjust level bounds based on support/resistance touches
8. **Level Importance Scoring**: Weight levels by touch frequency and recency
9. **Configuration File**: Move CSV hand-levels to YAML/JSON for better maintainability

### Long-Term (ML-Based)

10. **ML Pattern Detection**: Train model on historical data to detect support/resistance patterns beyond 3-candle reversals
11. **Predictive Levels**: Generate expected support/resistance levels for future time periods
12. **Bayesian Level Filtering**: Use Bayes' theorem to estimate level reliability based on touch history
13. **Fractal Analysis**: Detect levels at multiple fractal scales (intraday, daily, weekly)
14. **Order Book Fusion**: Incorporate real-time order book data to refine level detection

---

## 14. Integration with Other Modules

### Data Module
- Receives OHLC candles and ATR from `data.py`
- Uses candle high/low for pattern detection

### Signals Module
- Provides level-based signals (price near level, breakout, etc.)
- Level types inform signal interpretation

### Strategy Module
- Queries levels to determine entry/exit points
- Uses level types to validate trade direction (long vs short)

### Robot/TrainRobot
- Tracks position relative to levels
- Executes stop-loss and take-profit based on levels

---

## 15. Summary Table

| Aspect | Details |
|--------|---------|
| **Primary Purpose** | Manage support/resistance levels (manual + auto) |
| **Data Types** | Level dictionaries with time-value pairs and metadata |
| **Timeframes** | 15, 60, 240 minutes |
| **Loading** | CSV (hand-drawn) + pickle (auto-detected) |
| **Interpolation** | Linear slope-based at query time |
| **Validation** | Time windows, type constants, price proximity |
| **Persistence** | Pickle files per thread |
| **Testing** | Mock levels available in test suite |
| **Refactoring Needed** | Unify storage, fix bugs, add validation |

