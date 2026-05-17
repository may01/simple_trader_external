# Complex Signals Specification

**Source file:** `signals_lib/complex.py`  
**Category:** Multi-candle pattern detection — divergences and bounces

These signals scan history to detect higher-order price/indicator relationships. They do **not** inherit from `BaseSignal` formally (class body has no `super().__init__()`) but implement the full `BaseSignal` interface (`check`, `reset`, `get_data`, `get_marker_pos`). `reset()` always returns `False` and `get_data()` always returns `{}` for all signals in this file.

---

## Signal Overview

| Signal | Pattern | Price Reference | Indicator Direction |
|--------|---------|-----------------|---------------------|
| `Diver_Bull_signal` | Regular bullish divergence | Lower low in price | Higher low in indicator |
| `Diver_Bear_signal` | Regular bearish divergence | Higher high in price | Lower high in indicator |
| `Diver_Hidden_Bull_signal` | Hidden bullish divergence | Higher low in price (`low`) | Lower low in indicator |
| `Diver_Hidden_Bear_signal` | Hidden bearish divergence | Lower high in price (`high`) | Higher high in indicator |
| `Bounce_Long_Signal` | Bullish bounce off MA | — | indi crosses back above indi_ma |
| `Bounce_Short_Signal` | Bearish bounce off MA | — | indi crosses back below indi_ma |

---

## Divergence Signals

All four divergence signals share the same structural algorithm, varying only in the comparison direction and which price series is used.

### Common Divergence Algorithm

Each divergence signal scans backwards `peak_history = 7` candles from the current position to find a prior peak/trough in the indicator. If found:
- Compares the current indicator value vs the historical peak value
- Compares the current price vs the historical price
- Fires if the relationship diverges (price and indicator move in opposite directions)

Two modes controlled by `finished`:
- **`finished=True` (default):** Requires a completed peak — looks for a valley/peak at shift+1 (surrounded by higher/lower values on both sides). More reliable, less sensitive.
- **`finished=False`:** Immediate mode — detects divergence at the current candle without waiting for the peak to complete. More sensitive, more false positives.

---

### `Diver_Bull_signal(timeframe, level, cancel_level, indicator, finished=True)`

**Detects:** Regular bullish divergence — price makes a lower low while the indicator makes a higher low.

**Logic:**
1. Check current state: indicator `< level` (oversold zone)
2. If `finished=True`: verify current candle is a completed valley (`indi[2] > indi[1] < indi[0]` at current shift)  
   If `finished=False`: verify indicator is falling (`indi[0] < indi[1]`) and `< level`
3. Scan history (shifts 2..8): find a prior valley in the indicator `< level` with no intervening value `> cancel_level`
4. Fire if: `h_val < current_val` (prior indicator valley is lower) AND `h_price > cur_price` (prior price was higher = price made lower low)

**Parameters:**
- `timeframe` — candle timeframe for all lookups
- `level` — indicator must be below this to detect bullish divergence (e.g. RSI `30`)
- `cancel_level` — if any historical indicator value exceeds this, search stops (e.g. RSI `70`)
- `indicator` — indicator column name (e.g. `"rsi_14"`, `"cci_14"`)
- `finished` — `True` requires completed valley pattern; `False` fires immediately

**Price reference:** `"close"` at current and historical shifts.

**Example:**
```python
Diver_Bull_signal(15, level=30, cancel_level=70, indicator="rsi_14")
# RSI bullish divergence on 15m: price lower low, RSI higher low, both below 30
```

---

### `Diver_Bear_signal(timeframe, level, cancel_level, indicator, finished=True)`

**Detects:** Regular bearish divergence — price makes a higher high while the indicator makes a lower high.

**Logic:** Mirror of `Diver_Bull_signal` with all comparisons inverted:
1. Indicator `> level` (overbought zone)
2. If `finished=True`: completed peak (`indi[2] < indi[1] > indi[0]`)
3. Search history: prior peak `> level`, no value `< cancel_level` intervening
4. Fire if: `h_val > current_val` (prior indicator peak is higher) AND `h_price < cur_price` (price made higher high)

**Parameters:** same as `Diver_Bull_signal`.

**Example:**
```python
Diver_Bear_signal(60, level=70, cancel_level=30, indicator="rsi_14")
# RSI bearish divergence on 1h
```

---

### `Diver_Hidden_Bull_signal(timeframe, level, cancel_level, indicator, finished=True)`

**Detects:** Hidden bullish divergence — price makes a higher low (bullish continuation) while indicator makes a lower low.

**Logic:** Similar algorithm with these differences:
- Price reference uses `"low"` (not `"close"`)
- In search: prior valley condition `h_val < h_val_prev AND h_val < h_val_next` (same valley shape)
- Fire condition: `h_val > current_val` (prior indicator low is HIGHER — indicator made lower low) AND `h_price < cur_price` (prior price low was lower — price made higher low)
- Cancel: if historical indicator value `> cancel_level`, break

**Typical use:** Confirmation that the uptrend is resuming from a pullback.

---

### `Diver_Hidden_Bear_signal(timeframe, level, cancel_level, indicator, finished=True)`

**Detects:** Hidden bearish divergence — price makes a lower high (bearish continuation) while indicator makes a higher high.

**Logic:** Mirror of `Diver_Hidden_Bull_signal`:
- Price reference uses `"high"`
- Cancel: if historical indicator value `< cancel_level`, break
- Prior peak: `h_val > h_val_prev AND h_val > h_val_next`
- Fire: `h_val < current_val` (indicator made higher high) AND `h_price > cur_price` (price made lower high)

---

## Bounce Signals

These detect when an indicator (`indi`) bounces off its moving average (`indi_ma`), using `Diff_Greater_Signal` and `Diff_Less_Signal` internally to check the spread history.

### `Bounce_Long_Signal(timeframe, indi, indi_ma)`

**Detects:** Bullish bounce — indicator was above its MA, dipped close to it, and is now recovering.

**Logic (composed internally):**
```
And_Signal([
    Or_Signal([
        Diff_Less_Signal(tf, indi_ma, indi, 1),    # indi_ma is slightly above indi (touched/crossed)
        Diff_Less_Signal(tf, indi, indi_ma, 1),    # indi is slightly above indi_ma (tight gap)
    ]),
    History_Signal(Diff_Greater_Signal(tf, indi, indi_ma, 1), 1),  # indi was above indi_ma 1 candle ago by > 1
    History_Signal(Diff_Greater_Signal(tf, indi, indi_ma, 1), 2),  # indi was above indi_ma 2 candles ago by > 1
])
```

Fires when: indicator previously had a gap > 1 above its MA (shifts 1 and 2), and now the gap is < 1 in either direction — the indicator touched/crossed the MA and is potentially bouncing up.

**Parameters:**
- `timeframe` — candle timeframe
- `indi` — indicator (e.g. `"rsi_ma8"`)
- `indi_ma` — moving average of that indicator (e.g. `"rsi_ma12"`)

**`set_shift` propagation:** Propagates to inner `And_Signal`.

**Example:**
```python
Bounce_Long_Signal(15, "rsi_ma8", "rsi_ma12")  # RSI MA bouncing up off slower MA
```

---

### `Bounce_Short_Signal(timeframe, indi, indi_ma)`

**Detects:** Bearish bounce — indicator was below its MA, rose close to it, and is now falling back.

**Logic:** Mirror of `Bounce_Long_Signal`:
```
And_Signal([
    Or_Signal([
        Diff_Less_Signal(tf, indi_ma, indi, 1),
        Diff_Less_Signal(tf, indi, indi_ma, 1),
    ]),
    History_Signal(Diff_Greater_Signal(tf, indi_ma, indi, 1), 1),  # indi_ma was above indi by > 1
    History_Signal(Diff_Greater_Signal(tf, indi_ma, indi, 1), 2),
])
```

**Example:**
```python
Bounce_Short_Signal(15, "rsi_ma8", "rsi_ma12")  # RSI MA bouncing down off slower MA
```

---

## Implementation Notes

- All divergence signals use `peak_history = 7` as the lookback depth — scans at most 7 candles back for a prior peak/trough.
- The divergence search returns `False` (not `True`) when it finds a prior peak but the relationship does **not** diverge. This means once a non-diverging prior peak is found, the signal immediately returns False without checking further history.
- The `finished` parameter defaults to `True` in all divergence signals. This is the safer production default; `finished=False` is useful for early detection in active strategies.
- `get_marker_pos()` returns `data.get_cur_price("close", 1)` for all signals in this file (1-min close, shift=1).
