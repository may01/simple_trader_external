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

**`Diver_Hidden_Bull_signal(tf: int, level: float, cancel_level: float, indicator: str, finished: bool = True)`**

Hidden bullish divergence: price makes a **higher low** (bullish continuation) while the indicator makes a **lower low**. Signals trend continuation in an uptrend.

- Price reference: `"low"` (not `"close"`) — current vs. historical low
- Fire if: prior indicator low > current indicator low (indicator made lower low) AND prior price low < current price low (price made higher low)
- Cancel: if a historical indicator value rises above `cancel_level` during the scan, search stops and `reset()` returns True (mirrors `Diver_Bull_signal`'s cancel mechanics — see Key Constraints)

**`Diver_Hidden_Bear_signal(tf: int, level: float, cancel_level: float, indicator: str, finished: bool = True)`**

Hidden bearish divergence: price makes a **lower high** (bearish continuation) while the indicator makes a **higher high**. Signals trend continuation in a downtrend.

- Price reference: `"high"` (not `"close"`) — current vs. historical high
- Fire if: prior indicator high < current indicator high (indicator made higher high) AND prior price high > current price high (price made lower high)
- Cancel: if a historical indicator value falls below `cancel_level` during the scan, search stops and `reset()` returns True

**`Bounce_Long_Signal(tf: int, indi: str, indi_ma: str)`**
- Detects a bullish bounce: `indi` previously ran well above `indi_ma` (gap > 1 for the last two candles), and the gap has now closed to < 1 in either direction — i.e. `indi` touched/crossed back toward `indi_ma` and is potentially recovering. Composed internally (no new primitives — built from tasks 02 and 04):
  ```python
  And_Signal([
      Or_Signal([
          Diff_Less_Signal(tf, indi_ma, indi, 1),   # indi_ma slightly above indi (touched/crossed)
          Diff_Less_Signal(tf, indi, indi_ma, 1),   # indi slightly above indi_ma (tight gap)
      ]),
      History_Signal(Diff_Greater_Signal(tf, indi, indi_ma, 1), 1),  # indi was > indi_ma by > 1, 1 candle ago
      History_Signal(Diff_Greater_Signal(tf, indi, indi_ma, 1), 2),  # ...and 2 candles ago
  ])
  ```
- `set_shift()` propagates to the inner `And_Signal`

**`Bounce_Short_Signal(tf: int, indi: str, indi_ma: str)`**
- Mirror of `Bounce_Long_Signal` — `indi` previously ran well below `indi_ma`, gap has now closed:
  ```python
  And_Signal([
      Or_Signal([
          Diff_Less_Signal(tf, indi_ma, indi, 1),
          Diff_Less_Signal(tf, indi, indi_ma, 1),
      ]),
      History_Signal(Diff_Greater_Signal(tf, indi_ma, indi, 1), 1),  # indi_ma was > indi by > 1, 1 candle ago
      History_Signal(Diff_Greater_Signal(tf, indi_ma, indi, 1), 2),
  ])
  ```
- `set_shift()` propagates to the inner `And_Signal`

---

## Key Constraints

- All divergence signals use `data_point.get(col, tf, shift + self.shift)` for historical lookback
- `peak_history=7` candles scanned — use `range(1, peak_history+1)` with increasing shift values
- `finished=True` requires 3-candle valley pattern: `indicator[i-1] > indicator[i] < indicator[i+1]` (prior to current)
- `finished=False` fires immediately on condition match (less noise filtering, more signals)
- `get_data()` returns metadata including the prior peak/valley values and timestamps for analytics
- `cancel_level` arms `reset()` on all four divergence signals (regular and hidden): for the "bull" variants (`Diver_Bull_signal`, `Diver_Hidden_Bull_signal`), indicator rising above `cancel_level` → `reset()` returns True; for the "bear" variants (`Diver_Bear_signal`, `Diver_Hidden_Bear_signal`), indicator falling below `cancel_level` → `reset()` returns True (either way, the in-progress divergence is invalidated and the parent chain aborts)
- `Diver_Hidden_Bull_signal`/`Diver_Hidden_Bear_signal` use `"low"`/`"high"` as their price reference respectively (not `"close"`) — see signatures above
- **Deliberate departure from `complex-signals.md`:** that spec documents `reset()`/`get_data()` as always returning `False`/`{}` for this file (a legacy-code quirk). This plan intentionally diverges — `reset()` aborts the chain on `cancel_level` breach and `get_data()` exports pattern metadata — because both are more useful for chain control and Strategy logging. Implementers should follow THIS plan, not the spec, for these two methods

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
