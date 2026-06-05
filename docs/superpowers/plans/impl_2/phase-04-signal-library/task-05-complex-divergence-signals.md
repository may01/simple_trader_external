# Task 05: Complex Divergence and Bounce Signals

**Phase:** 04 — Signal Library  
**Depends on:** Task 01 (BaseSignal)  
**Produces:** `signals_lib/complex.py` — divergence and bounce pattern detection

---

## Goal

Implement multi-candle complex signals: bullish/bearish divergence (regular and hidden) and MA bounce detection. These require scanning back `peak_history` candles to find prior peaks/troughs.

---

## Files

- Create: `signals_lib/complex.py`

---

## Signals to Implement

**`Diver_Bull_signal(tf: int, level: float, cancel_level: float, indicator: str, finished: bool = True)`**

Detects bullish divergence: price makes a lower low while the indicator makes a higher low below `level`.

Logic:
1. Current indicator value < `level` (indicator oversold)
2. If indicator > `cancel_level` → `reset()` returns True (sequence aborted)
3. Scan back `peak_history=7` candles for a prior valley (local minimum in indicator below `level`)
4. Compare: current indicator > prior indicator valley (higher low in indicator)
5. Compare: current price < prior price at valley (lower low in price)
6. If `finished=True`: require prior valley to be confirmed (i.e., indicator went up after the valley — 3-candle pattern)

**`Diver_Bear_signal(tf: int, level: float, cancel_level: float, indicator: str, finished: bool = True)`**

Mirrors bullish: bearish divergence — price makes a higher high, indicator makes a lower high above `level`.

Logic:
1. Current indicator value > `level` (indicator overbought)
2. If indicator < `cancel_level` → `reset()` returns True
3. Scan back `peak_history=7` candles for prior peak above `level`
4. Current indicator < prior peak (lower high in indicator)
5. Current price > prior price at peak (higher high in price)

**`Diver_Hidden_Bull_signal(tf: int, level: float, indicator: str)`**

Hidden bullish divergence: price lower high, indicator higher high. Signals trend continuation in uptrend.

**`Diver_Hidden_Bear_signal(tf: int, level: float, indicator: str)`**

Hidden bearish divergence: price higher low, indicator lower low.

**`Bounce_Long_Signal(tf: int, indi: str, indi_ma: str)`**
- Detects price bounce off a moving average in uptrend context
- Current price touched `indi_ma` then bounced up: `indi > indi_ma` and prior `indi <= indi_ma`

**`Bounce_Short_Signal(tf: int, indi: str, indi_ma: str)`**
- Mirror: bounce down off MA in downtrend

---

## Key Constraints

- All divergence signals use `data_point.get(col, tf, shift + self.shift)` for historical lookback
- `peak_history=7` candles scanned — use `range(1, peak_history+1)` with increasing shift values
- `finished=True` requires 3-candle valley pattern: `indicator[i-1] > indicator[i] < indicator[i+1]` (prior to current)
- `finished=False` fires immediately on condition match (less noise filtering, more signals)
- `get_data()` returns metadata including the prior peak/valley values and timestamps for analytics
- `cancel_level` in bearish signals: if indicator drops below cancel_level while chain is in progress, `reset()` must return True (bear divergence invalidated)

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from signals_lib.complex import Diver_Bull_signal
# With synthetic data showing bullish divergence:
# price: 100, 95, 98 (lower low then recovery)
# rsi: 35, 28, 32 (lower than prev valley but price lower low)
# Not easy to unit-test without a full DataPoint — integration test preferred
print('complex signals module importable ok')
from signals_lib.complex import Diver_Bear_signal, Bounce_Long_Signal
print('all complex signals importable')
"
```

---

## Commit

`feat: implement divergence and bounce complex signals`
