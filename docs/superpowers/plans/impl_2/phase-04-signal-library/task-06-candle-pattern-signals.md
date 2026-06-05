# Task 06: Candle Pattern Signals

**Phase:** 04 — Signal Library  
**Depends on:** Task 01 (BaseSignal)  
**Produces:** `signals_lib/candle.py` — candle size, wick proportion, and direction signals

---

## Goal

Implement candle structure signals: big candle detection, long/short wick analysis, and bullish/bearish candle direction.

---

## Files

- Create: `signals_lib/candle.py`

---

## Signals to Implement

**`BigCandle_Signal(tf: int, coef: float)`**
- `check()` returns `data_point.get("natr_14", tf, self.shift) > coef * data_point.get("atr_ma", tf, self.shift)`
- Note: spec says `natr > coef * natr_ma` — use `natr_14` and `atr_ma` as the indicator names

**`LongTale_Signal(tf: int, tale_type: str)`**
- `tale_type = "low"` (lower wick): returns `(min(open, close) - low) > 0.5 * candle_size`
- `tale_type = "high"` (upper wick): returns `(high - max(open, close)) > 0.5 * candle_size`
- `candle_size = high - low`
- Uses `data_point.get("open", tf)`, `get("close", tf)`, `get("high", tf)`, `get("low", tf)` with shift

**`ShortTale_Signal(tf: int, tale_type: str)`**
- `tale_type = "low"`: returns `(min(open, close) - low) < 0.2 * candle_size`
- `tale_type = "high"`: returns `(high - max(open, close)) < 0.2 * candle_size`

**`CandleUP_Signal(tf: int)`**
- `check()` returns `data_point.get("open", tf, self.shift) < data_point.get("close", tf, self.shift)`
- Bullish candle (close > open)

**`CandleDOWN_Signal(tf: int)`**
- `check()` returns `data_point.get("open", tf, self.shift) > data_point.get("close", tf, self.shift)`
- Bearish candle (open > close)

---

## Constants Needed

Add to `signals_lib/candle.py` or import from `constants.py`:
- `CANDLE_LOW = "low"` — refers to lower wick analysis
- `CANDLE_HIGH = "high"` — refers to upper wick analysis

---

## Key Constraints

- `candle_size = high - low` — if zero (doji), wick ratio checks are undefined; return False when `candle_size == 0`
- All candle values read via `data_point.get(col, tf, self.shift)` — not direct DataFrame access
- `LongTale_Signal` and `ShortTale_Signal` constructors accept the `CANDLE_LOW`/`CANDLE_HIGH` constants (not the strings "low"/"high") — use the constants for documentation clarity
- `BigCandle_Signal` coef is a float multiplier — typical range 1.5 to 3.0

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from signals_lib.candle import BigCandle_Signal, CandleUP_Signal, LongTale_Signal
from data import LiveDataPoint
import pandas as pd

# Bullish candle
df = pd.DataFrame({
    '15_open': [20.0], '15_close': [21.5],
    '15_high': [22.0], '15_low': [19.5],
    '15_natr_14': [2.5], '15_atr_ma': [1.0]
})
pt = LiveDataPoint({15: df})

assert CandleUP_Signal(15).check(pt, {}, None) == True   # 20 < 21.5
assert BigCandle_Signal(15, 2.0).check(pt, {}, None) == True  # 2.5 > 2.0*1.0
print('candle signals ok')
"
```

---

## Commit

`feat: implement candle pattern signals — BigCandle, LongTale, ShortTale, CandleUP/DOWN`
