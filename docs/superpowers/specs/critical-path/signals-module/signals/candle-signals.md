# Candle Signals Specification

**Source file:** `signals_lib/candle.py`  
**Category:** Candle-structure pattern detection — size, wick shape, direction

These signals inspect individual candle geometry (open, close, high, low) to detect specific formations. `BigCandle_Signal`, `LongTale_Signal`, `ShortTale_Signal` inherit from `BaseSignal`. `CandleUP_Signal` and `CandleDOWN_Signal` do not inherit from `BaseSignal` (marked `#TODO:` in source) but implement the full interface manually.

Constants defined in this file:
- `CANDLE_HIGH = 1`
- `CANDLE_LOW = 2`

---

## Signal Overview

| Signal | What it detects | Key threshold |
|--------|-----------------|---------------|
| `BigCandle_Signal(tf, coef)` | Candle size unusually large | `natr > coef × natr_ma` |
| `LongTale_Signal(tf, type)` | Long wick in given direction | wick > 50% of candle range |
| `ShortTale_Signal(tf, type)` | Short/absent wick | wick < 20% of candle range |
| `CandleUP_Signal(tf)` | Bullish candle (green) | `open < close` |
| `CandleDOWN_Signal(tf)` | Bearish candle (red) | `open > close` |

---

## `BigCandle_Signal(tf, coef)`

**Logic:** `natr[shift] > coef × natr_ma[shift]`

Reads the normalized ATR (`natr`) and its moving average (`natr_ma`) from the data layer. Fires when the current candle's ATR exceeds a multiple of its average, indicating an unusually large price range.

**Parameters:**
- `tf` — timeframe in minutes
- `coef` — multiplier coefficient (e.g. `1.5` = 50% above average ATR)

**Indicator columns used:**
- `"natr"` — normalized ATR of the candle
- `"natr_ma"` — moving average of normalized ATR

**Example:**
```python
BigCandle_Signal(15, 1.5)  # 15m candle ATR > 1.5× its average
```

---

## `LongTale_Signal(tf, type)`

**Logic:** Fires when the wick in the specified direction exceeds 50% of the total candle range.

```
candle_size = high - low

if type == CANDLE_LOW:
    tale_size = min(open, close) - low   # lower shadow
if type == CANDLE_HIGH:
    tale_size = high - max(open, close)  # upper shadow

fires if: tale_size > 0.5 × candle_size
```

**Parameters:**
- `tf` — timeframe in minutes
- `type` — `CANDLE_LOW` (lower wick) or `CANDLE_HIGH` (upper wick)

**Internal attribute:** `self.coef = 1.8` is defined but **not used** in the current implementation (threshold is hardcoded at 0.5).

**Example:**
```python
LongTale_Signal(15, CANDLE_LOW)   # Long lower wick (hammer-like) on 15m
LongTale_Signal(15, CANDLE_HIGH)  # Long upper wick (shooting star-like) on 15m
```

**Typical use:** `CANDLE_LOW` in long entry setups (rejection of lower prices), `CANDLE_HIGH` in short setups.

---

## `ShortTale_Signal(tf, type)`

**Logic:** Fires when the wick in the specified direction is less than 20% of the total candle range.

```
if type == CANDLE_LOW:
    tale_size = min(open, close) - low
if type == CANDLE_HIGH:
    tale_size = high - max(open, close)

fires if: tale_size < 0.2 × candle_size
```

**Parameters:** same as `LongTale_Signal`.

**Note:** Also has `self.coef = 1.8` which is unused. Threshold hardcoded at 0.2.

**Example:**
```python
ShortTale_Signal(15, CANDLE_LOW)  # Very little lower wick — body dominates (momentum candle)
```

---

## `CandleUP_Signal(tf)`

**Logic:** `open < close` at `shift=1` (hardcoded, **not** using `self.shift`).

**Important:** Unlike other candle signals, `CandleUP_Signal` always evaluates at shift=1 regardless of any `set_shift()` call. This is a known inconsistency marked `#TODO` in source.

**Returns:** True for bullish (green) candles.

**Note:** Does not inherit from `BaseSignal`; implements `reset()`, `get_data()`, `get_marker_pos()` manually. `set_shift()` is **not implemented** — shift cannot be changed.

**Example:**
```python
CandleUP_Signal(15)  # Previous 15m candle was bullish
```

---

## `CandleDOWN_Signal(tf)`

**Logic:** `open > close` at `shift=1` (hardcoded, same issue as `CandleUP_Signal`).

**Returns:** True for bearish (red) candles.

**Note:** Same limitations as `CandleUP_Signal` — no `BaseSignal` inheritance, shift fixed at 1.

**Example:**
```python
CandleDOWN_Signal(15)  # Previous 15m candle was bearish
```

---

## Known Issues

- `LongTale_Signal` and `ShortTale_Signal` define `self.coef = 1.8` but use hardcoded `0.5` and `0.2` thresholds respectively — `coef` is dead code.
- `CandleUP_Signal` and `CandleDOWN_Signal` are marked `#TODO:` — they do not inherit `BaseSignal` and hard-code shift=1, making them incompatible with `History_Signal` and `Continuous_Signal`.
