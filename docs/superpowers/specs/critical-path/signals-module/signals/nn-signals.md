# NN Signals Specification

**Source file:** `signals_lib/nn_signals.py`  
**Category:** Neural network output signals — gate entries on NN prediction confidence

These signals read NN prediction cache from the `data` object rather than indicator columns. They check whether the NN model's output for a given prediction type meets a threshold or ratio condition.

All signals inherit from `BaseSignal`.

---

## Signal Overview

| Signal | Logic | Key Use |
|--------|-------|---------|
| `NN_Signal(nn_tf, nn_target)` | NN prediction equals target class | Exact class match |
| `NN_Xbigger_Signal(nn_tf, bigger_target, coeff)` | `buy_prob / sell_prob > coeff` (or inverse) | Ratio-based confidence |
| `NN_ValBigger_Signal(nn_tf, target_type, val)` | `nn_cache[target_type] > val` | Absolute probability threshold |
| `NN_ZScore_Signal(target_type, val)` | NN value exceeds `mean + val × std` | Z-score confidence filter |

---

## NN Type Constants (from `helpers.py`)

| Constant | Description |
|----------|-------------|
| `NN_TYPE_BIG` | Large-move NN model |
| `NN_TYPE_SMALL` | Small-move NN model |
| `NN_TYPE_ALL` | Combined NN model (used by `NN_ZScore_Signal`) |
| `NN_TARGET_BUY` | Buy/long direction output index |
| `NN_TARGET_SELL` | Sell/short direction output index |

---

## `NN_Signal(nn_tf, nn_target)`

**Logic:**
```python
if nn_tf == NN_TYPE_BIG:
    return data.nn_cache_big == nn_target
elif nn_tf == NN_TYPE_SMALL:
    return data.nn_cache_small == nn_target
return False
```

Fires when the cached NN prediction for the specified model type exactly equals `nn_target`.

**Parameters:**
- `nn_tf` — NN model type (`NN_TYPE_BIG` or `NN_TYPE_SMALL`)
- `nn_target` — expected prediction class to match

**Data source:** `data.nn_cache_big` / `data.nn_cache_small` — cached per-tick by `LiveData` / `StrategyManager`.

**Example:**
```python
NN_Signal(NN_TYPE_BIG, NN_TARGET_BUY)  # Big-move NN predicts buy
```

---

## `NN_Xbigger_Signal(nn_tf, bigger_target, coeff)`

**Logic:**
```python
nn_cache = data.get_nn_cache(nn_tf)
if bigger_target == NN_TARGET_BUY:
    bigger = nn_cache[NN_TARGET_BUY]
    smaller = nn_cache[NN_TARGET_SELL]
elif bigger_target == NN_TARGET_SELL:
    bigger = nn_cache[NN_TARGET_SELL]
    smaller = nn_cache[NN_TARGET_BUY]

if smaller == 0: return False
return bigger / smaller > coeff
```

Fires when the ratio of one direction's probability to the other exceeds a coefficient. Guards against zero-division by returning False when `smaller == 0`.

**Parameters:**
- `nn_tf` — NN model type (any `NN_TYPE_*`)
- `bigger_target` — which direction should be dominant (`NN_TARGET_BUY` or `NN_TARGET_SELL`)
- `coeff` — required ratio (e.g. `2.0` means buy probability must be > 2× sell probability)

**Example:**
```python
NN_Xbigger_Signal(NN_TYPE_ALL, NN_TARGET_BUY, 2.0)
# Buy probability is at least 2× sell probability
```

---

## `NN_ValBigger_Signal(nn_tf, target_type, val)`

**Logic:**
```python
nn_cache = data.get_nn_cache(nn_tf)
return nn_cache[target_type] > val
```

Simple absolute threshold check on one direction's NN output.

**Parameters:**
- `nn_tf` — NN model type
- `target_type` — `NN_TARGET_BUY` or `NN_TARGET_SELL`
- `val` — probability threshold (e.g. `0.6` for 60% confidence)

**Example:**
```python
NN_ValBigger_Signal(NN_TYPE_SMALL, NN_TARGET_SELL, 0.65)
# Small-move NN sell confidence > 65%
```

---

## `NN_ZScore_Signal(target_type, val)`

**Logic:**
```python
nn_cache = data.get_nn_cache(NN_TYPE_ALL)
column_name = "long" if target_type == NN_TARGET_BUY else "short"
mean = data.nn_history_cache[column_name].mean()
std = data.nn_history_cache[column_name].std()
nn_val = nn_cache[target_type]
return mean > 0.1 and (nn_val > (mean + val * std))
```

Fires when the current NN output exceeds the historical mean by `val` standard deviations — a Z-score based filter that adapts to the distribution of recent NN outputs.

**Parameters:**
- `target_type` — `NN_TARGET_BUY` or `NN_TARGET_SELL`
- `val` — Z-score threshold (e.g. `1.5` = 1.5 standard deviations above mean)

**Data sources:**
- `data.get_nn_cache(NN_TYPE_ALL)` — current NN output
- `data.nn_history_cache["long"/"short"]` — rolling historical NN output cache

**Guard:** Only fires if `mean > 0.1` — prevents false signals when the historical mean is near zero (insufficient data or no signal).

**Logs:** `log("NN_ZScore_Signal mean: %f, std: %f, nn_val: %f")`

**Fixed model type:** Always uses `NN_TYPE_ALL` regardless of parameters — the `nn_tf` attribute is initialized to `NN_TYPE_ALL` in the constructor.

**Example:**
```python
NN_ZScore_Signal(NN_TARGET_BUY, 1.5)
# NN buy output > 1.5 std deviations above recent mean
```

---

## Design Notes

- All NN signals read from cached values (`data.nn_cache_*`, `data.get_nn_cache()`) updated each tick by `StrategyManager` or `LiveData`. They do not trigger inference themselves.
- `shift` parameter is inherited from `BaseSignal` but has no effect — NN cache is a single scalar per tick, not a time-series accessible by shift.
- These signals are only meaningful in live trading and NN-enhanced simulation modes. In standard backtesting (`simulate` mode without NN), the cache is not populated and signals return `False`.
