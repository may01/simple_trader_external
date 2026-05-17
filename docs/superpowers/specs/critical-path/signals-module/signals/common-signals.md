# Common Signals Specification

**Source file:** `signals_lib/common.py`  
**Category:** Atomic signals — value comparisons, crossovers, direction, differences, level proximity

All signals in this file inherit from `BaseSignal`. They read data via `data_point.get(col, tf, shift)` and return `bool`.

---

## Signal Overview

| Signal | Logic | Key Parameters |
|--------|-------|----------------|
| `Less_Signal` | `indi_1 < indi_2` | tf, indi_1, indi_2 |
| `Greater_Signal` | `indi_1 > indi_2` | tf, indi_1, indi_2 |
| `Less_Val_Signal` | `indi_1 < val` | tf, indi_1, val |
| `Greater_Val_Signal` | `indi_1 > val` | tf, indi_1, val |
| `Cross_Up_Signal` | `indi_1 > indi_2` AND `indi_1_prev < indi_2_prev` | tf, indi_1, indi_2 |
| `Cross_Down_Signal` | `indi_1 < indi_2` AND `indi_1_prev > indi_2_prev` | tf, indi_1, indi_2 |
| `Cross_Up_Val_Signal` | `indi_1 > val` AND `indi_1_prev < val` | tf, indi_1, val |
| `Cross_Down_Val_Signal` | `indi_1 < val` AND `indi_1_prev > val` | tf, indi_1, val |
| `Rising_Signal` | `indi[shift] > indi[shift+1]` | tf, indi_1 |
| `Falling_Signal` | `indi[shift] < indi[shift+1]` | tf, indi_1 |
| `Diff_Greater_Signal` | `(indi_1 - indi_2) > 0 AND > val` | tf, indi_1, indi_2, val |
| `Diff_Less_Signal` | `(indi_1 - indi_2) > 0 AND < val` | tf, indi_1, indi_2, val |
| `Diff_LessIndi_Signal` | `(indi_1 - indi_2) > 0 AND < indi_dist` | tf, indi_1, indi_2, indi_dist |
| `Diff_GreaterIndi_Signal` | `(indi_1 - indi_2) > 0 AND > indi_dist` (cross-tf) | tf_1, indi_1, tf_2, indi_2, tf_dist, indi_dist |
| `Near_Level_Signal` | `level - buffer ≤ indi ≤ level + buffer` (any level in list) | tf, indi_1, level_type, buffer |
| `Near_Price_Level_Signal` | Same as Near_Level_Signal but `buffer = buffer_coef × indi_atr` | tf, indi_1, level_type, buffer, buffer_indi |
| `Over_Level_Signal` | `indi > any level` in level_type list | tf, indi_1, level_type |
| `Under_Level_Signal` | `indi < any level` in level_type list | tf, indi_1, level_type |

---

## Value Comparison Signals

### `Less_Signal(timeframe, indi_1, indi_2)`

**Logic:** `data_point.get(indi_1, tf, shift) < data_point.get(indi_2, tf, shift)`

**Parameters:**
- `timeframe` — timeframe in minutes
- `indi_1` — first indicator column name (e.g. `"rsi_14"`, `"close"`)
- `indi_2` — second indicator column name

**Example:**
```python
Less_Signal(15, "rsi_14", "rsi_ma8")  # RSI below its MA on 15m
```

---

### `Greater_Signal(timeframe, indi_1, indi_2)`

**Logic:** `data_point.get(indi_1, tf, shift) > data_point.get(indi_2, tf, shift)`

**Parameters:** same as `Less_Signal`.

**Example:**
```python
Greater_Signal(60, "close", "ema_50")  # Price above EMA-50 on 1h
```

---

### `Less_Val_Signal(timeframe, indi_1, val)`

**Logic:** `data_point.get(indi_1, tf, shift) < val`

**Parameters:**
- `val` — numeric threshold constant

**Example:**
```python
Less_Val_Signal(15, "rsi_14", 30)  # RSI oversold
```

---

### `Greater_Val_Signal(timeframe, indi_1, val)`

**Logic:** `data_point.get(indi_1, tf, shift) > val`

**Example:**
```python
Greater_Val_Signal(15, "rsi_14", 70)  # RSI overbought
```

---

## Crossover Signals

### `Cross_Up_Signal(timeframe, indi1, indi2)`

**Logic:** `indi1[shift] > indi2[shift]` AND `indi1[shift+1] < indi2[shift+1]`

Implemented as `And_Signal([Greater_Signal(...), History_Signal(Less_Signal(...), 1)])`.

**Parameters:**
- `indi1`, `indi2` — indicator column names

**`set_shift` propagation:** Delegates to inner `And_Signal`.

**Example:**
```python
Cross_Up_Signal(15, "macd", "macd_signal")  # MACD bullish crossover on 15m
```

---

### `Cross_Down_Signal(timeframe, indi1, indi2)`

**Logic:** `indi1[shift] < indi2[shift]` AND `indi1[shift+1] > indi2[shift+1]`

Mirror of `Cross_Up_Signal`.

**Example:**
```python
Cross_Down_Signal(15, "macd", "macd_signal")  # MACD bearish crossover
```

---

### `Cross_Up_Val_Signal(timeframe, indi1, val)`

**Logic:** `indi1[shift] > val` AND `indi1[shift+1] < val`

Crossover of a single indicator against a fixed numeric threshold.

**Example:**
```python
Cross_Up_Val_Signal(15, "rsi_14", 50)  # RSI crosses above 50
```

---

### `Cross_Down_Val_Signal(timeframe, indi1, val)`

**Logic:** `indi1[shift] < val` AND `indi1[shift+1] > val`

**Example:**
```python
Cross_Down_Val_Signal(15, "cci_14", -100)  # CCI crosses below -100
```

---

## Direction Signals

### `Rising_Signal(timeframe, indi_1)`

**Logic:** `indi_1[shift] > indi_1[shift+1]` — indicator is higher now than one candle ago.

**Note:** Indexes `shift` and `shift+1`, so shift offsets propagate correctly.

**Example:**
```python
Rising_Signal(60, "rsi_ma8")  # RSI MA is rising on 1h
```

---

### `Falling_Signal(timeframe, indi_1)`

**Logic:** `indi_1[shift] < indi_1[shift+1]`

**Example:**
```python
Falling_Signal(60, "rsi_ma8")  # RSI MA is falling
```

---

## Difference Signals

### `Diff_Greater_Signal(timeframe, indi_1, indi_2, val)`

**Logic:** `(indi_1 - indi_2) > 0 AND (indi_1 - indi_2) > val`

**Note:** Requires the difference to be positive (indi_1 above indi_2) AND larger than `val`. Both conditions must hold.

**Parameters:**
- `val` — minimum positive spread threshold

**Example:**
```python
Diff_Greater_Signal(15, "ema_7", "ema_25", 0.5)  # EMA-7 is above EMA-25 by > 0.5
```

---

### `Diff_Less_Signal(timeframe, indi_1, indi_2, val)`

**Logic:** `(indi_1 - indi_2) > 0 AND (indi_1 - indi_2) < val`

**Note:** Fires when indi_1 is above indi_2 but the gap is smaller than `val`. Used to detect convergence or near-crossing.

**Example:**
```python
Diff_Less_Signal(15, "ema_7", "ema_25", 0.2)  # EMA-7 above EMA-25 but gap < 0.2
```

---

### `Diff_LessIndi_Signal(timeframe, indi_1, indi_2, indi_dist)`

**Logic:** `(indi_1 - indi_2) > 0 AND (indi_1 - indi_2) < indi_dist`

Same as `Diff_Less_Signal` but the threshold is another indicator value (e.g. ATR) rather than a fixed constant. Useful for ATR-scaled proximity checks.

**Parameters:**
- `indi_dist` — indicator column name providing dynamic threshold

**Example:**
```python
Diff_LessIndi_Signal(15, "close", "ema_25", "atr_14")  # Price above EMA but within 1 ATR
```

---

### `Diff_GreaterIndi_Signal(tf_1, indi_1, tf_2, indi_2, tf_dist, indi_dist)`

**Logic:** `(indi_1[tf_1] - indi_2[tf_2]) > 0 AND > indi_dist[tf_dist]`

Cross-timeframe version. Each operand can come from a different timeframe.

**Parameters:**
- `tf_1`, `indi_1` — first indicator and its timeframe
- `tf_2`, `indi_2` — second indicator and its timeframe
- `tf_dist`, `indi_dist` — distance threshold indicator and its timeframe

**Note:** `shift` is applied uniformly to all three lookups.

**Example:**
```python
Diff_GreaterIndi_Signal(15, "rsi_14", 60, "rsi_14", 15, "atr_14")
# 15m RSI is above 1h RSI by more than 15m ATR
```

---

## Level-Based Signals

### `Near_Level_Signal(timeframe, indi_1, level_type, buffer)`

**Logic:** For each level in `levels[level_type]`: fires if `level - buffer ≤ indi_1 ≤ level + buffer`.

Returns True at the **first** matching level; stops searching once a match is found.

**Parameters:**
- `level_type` — key into the `levels` dict (e.g. `"support"`, `"resistance"`)
- `buffer` — fixed absolute distance (in price units)

**Logs:** Fires `log("Near_Level_Signal fired at level %s")` on match.

**Example:**
```python
Near_Level_Signal(15, "close", "support", 0.3)
```

---

### `Near_Price_Level_Signal(timeframe, indi_1, level_type, buffer, buffer_indi)`

**Logic:** Same as `Near_Level_Signal` but computes the buffer dynamically:  
`effective_buffer = buffer × data_point.get(buffer_indi, tf, shift)`

Delegates to an internal `Near_Level_Signal` instance with the updated buffer on each tick.

**Parameters:**
- `buffer` — multiplier coefficient
- `buffer_indi` — indicator column providing the scale (typically ATR)

**`set_shift` propagation:** Propagates to the inner `Near_Level_Signal`.

**Example:**
```python
Near_Price_Level_Signal(15, "close", "support", 0.5, "atr_14")
# Within 0.5 × ATR of any support level
```

---

### `Over_Level_Signal(timeframe, indi_1, level_type)`

**Logic:** Fires if `indi_1 > any level` in `levels[level_type]`.

Returns True at the **first** level exceeded; no buffer/proximity check.

**Example:**
```python
Over_Level_Signal(60, "close", "resistance")  # Price above any resistance level
```

---

### `Under_Level_Signal(timeframe, indi_1, level_type)`

**Logic:** Fires if `indi_1 < any level` in `levels[level_type]`.

**Example:**
```python
Under_Level_Signal(60, "close", "support")  # Price below any support level
```
