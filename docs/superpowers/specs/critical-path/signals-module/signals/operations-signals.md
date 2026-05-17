# Operations Signals Specification

**Source file:** `signals_lib/operations.py`  
**Category:** Combinators — boolean logic, temporal composition, utility constants, metadata wrappers

All signals inherit from `BaseSignal` unless noted. Combinators compose child signals without owning timeframe logic themselves.

---

## Signal Overview

| Signal | Category | Logic |
|--------|----------|-------|
| `And_Signal` | Boolean combinator | All children must fire |
| `Or_Signal` | Boolean combinator | Any child must fire |
| `Not_Signal` | Boolean combinator | Child must NOT fire |
| `History_Signal` | Temporal | Evaluate child at historical offset |
| `Continuous_Signal` | Temporal | Child fires ≥ N times in last M candles |
| `True_Signal` | Constant | Always fires |
| `False_Signal` | Constant | Never fires |
| `BoolValue_Signal` | Indicator boolean | Read a boolean indicator column |
| `PersistentCounter_Signal` | Periodic | Fire every N ticks (global counter) |
| `DataValue_Signal` | Metadata | Conditional metadata injection |

---

## Boolean Combinators

### `And_Signal(signals)`

**Logic:** `s1.check() AND s2.check() AND ... AND sN.check()`

Evaluates all children regardless of short-circuit — Python's `and` via accumulated `res = True`. Every child is always called.

**Parameters:**
- `signals` — list of `BaseSignal` instances

**`set_shift` propagation:** Propagates to all children.

**Usage:**
```python
And_Signal([
    Greater_Val_Signal(15, "rsi_14", 50),
    Greater_Signal(15, "close", "ema_25"),
])
```

**Note:** Widely used inside crossover signals (`Cross_Up_Signal`, `Cross_Down_Signal`, etc.) as their internal composition primitive.

---

### `Or_Signal(signals)`

**Logic:** `s1.check() OR s2.check() OR ... OR sN.check()`

Evaluates all children regardless — no early exit.

**Parameters:**
- `signals` — list of `BaseSignal` instances

**`set_shift` propagation:** Propagates to all children.

**Usage:**
```python
Or_Signal([
    Less_Val_Signal(15, "rsi_14", 30),
    Less_Val_Signal(60, "rsi_14", 35),
])
```

---

### `Not_Signal(signal)`

**Logic:** `NOT signal.check()`

**Parameters:**
- `signal` — single `BaseSignal` instance

**`set_shift` propagation:** Propagates to the wrapped signal.

**Usage:**
```python
Not_Signal(Greater_Val_Signal(15, "rsi_14", 70))  # RSI not overbought
```

---

## Temporal Combinators

### `History_Signal(signal, history)`

**Logic:** Evaluates `signal` at `shift = history + self.shift` (i.e. `history` candles back from the current shift context).

Calls `self.signal.set_shift(self.history + self.shift)` before `signal.check()`.

**Parameters:**
- `signal` — `BaseSignal` instance to evaluate historically
- `history` — how many candles back (added to any existing shift)

**Note:** Does not propagate its own `set_shift` to the child — it overrides the child's shift directly with `history + self.shift`. This means the child signal's shift is always `history` relative to the caller's shift context.

**Usage:**
```python
History_Signal(Greater_Signal(15, "rsi_14", 50), 1)  # RSI was above 50 last candle
```

**Composition with crossovers:** All `Cross_*_Signal` implementations build on `History_Signal` internally.

---

### `Continuous_Signal(signal, history, multiply=1)`

**Logic:** Fires if `signal` fires **at least `multiply` times** when evaluated across `history` consecutive candles (shifts 0 through `history-1`).

```python
count = sum(1 for h in range(history) if signal.check(at shift=h+self.shift))
return count >= multiply
```

**Parameters:**
- `signal` — signal to count
- `history` — window size (number of candles to check)
- `multiply` — minimum required count (default: 1)

**Usage:**
```python
Continuous_Signal(Rising_Signal(60, "rsi_ma8"), 3, 2)
# RSI MA rising in at least 2 of the last 3 1h candles
```

**Performance note:** Makes `history` calls to `signal.check()` per tick. Keep `history` small for frequently-used chains.

---

## Constant Signals

### `True_Signal()`

Always returns `True`. No parameters.

**Usage:** Placeholder in chains during development, or as a pass-through in AND/OR compositions.

---

### `False_Signal()`

Always returns `False`. No parameters.

**Usage:** Disable a chain without removing it, or as a no-op placeholder.

---

## Indicator Boolean

### `BoolValue_Signal(value, tf)`

**Logic:** `data_point.get(value, tf, self.shift)` — reads a boolean indicator column and casts it to bool.

**Parameters:**
- `value` — column name of a pre-computed boolean indicator (e.g. `"trend_up"`, `"trend_down"`)
- `tf` — timeframe in minutes

**Note:** The column must be pre-computed by the Data/Indicators layer. Typical use is reading the `trend_up` / `trend_down` flag fields from the indicator registry.

**Usage:**
```python
BoolValue_Signal("trend_up", 60)   # 1h trend is up (pre-computed column)
BoolValue_Signal("trend_down", 15) # 15m trend is down
```

---

## Periodic

### `PersistentCounter_Signal(fire_each)`

**Logic:** Increments a **module-level global counter** `PERSISTENT_COUNTER_SIGNAL_VAL` on every `check()` call. Fires when `counter % fire_each == 0`.

**Parameters:**
- `fire_each` — fires every N ticks globally

**Critical note:** The counter is a module-level global (`PERSISTENT_COUNTER_SIGNAL_VAL`). All instances of this signal share the same counter. Multiple instances with different `fire_each` values will interfere with each other.

**Usage:**
```python
PersistentCounter_Signal(5)  # Fires on every 5th tick globally
```

**Typical use:** Throttle expensive checks (e.g. re-compute levels every 5 ticks). Not suitable for multiple concurrent instances.

---

## Metadata Wrapper

### `DataValue_Signal(data_name, value, value_set)`

**Logic:** Always returns `self.value_set` (a boolean flag). When fired, injects `{data_name: value}` into the chain's metadata via `get_data()`.

**Parameters:**
- `data_name` — key name to inject into chain metadata
- `value` — value to inject (any type)
- `value_set` — initial boolean fire state

**Methods:**
- `set_value(val)` — set `value = val` and `value_set = True` (arms the signal)
- `unset_value()` — set `value_set = False` (disarms the signal)
- `get_data()` — returns `{data_name: value}` if `value_set` is True, else `{}`

**Warning (from code comment):** `DataValue_Signal` will not work correctly when wrapped by combinator signals (`And_Signal`, `Or_Signal`, etc.) because those combinators do not implement `get_data()` with propagation to children.

**Usage pattern:**
```python
level_signal = DataValue_Signal("cur_level_name", None, False)
# Before chain evaluation, arm the signal:
level_signal.set_value("Support_1")
# When chain completes, metadata includes {"cur_level_name": "Support_1"}
```
