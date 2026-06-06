# Task 02: Wide DataFrame Builder

**Phase:** 03 — Data Layer  
**Depends on:** Task 01 (DataPoint), Phase 02 (graber_data.pkl)  
**Produces:** `data.py` — `get_stock_data()` that builds the wide base DataFrame from `graber_data.pkl`

---

## Goal

Implement `get_stock_data(pair)` — transforms raw 1-min OHLCV (`graber_data.pkl`) into the wide base DataFrame with expanding per-TF OHLCV columns, candle-boundary columns, and `{tf}_is_closed` flags.

---

## Context

The wide DataFrame is the foundation of the entire offline pipeline. Every row is a 1-min timestamp. For each TF in `[1, 5, 15, 60, 240, 1440]`, it contains expanding OHLCV columns (open, high, low, close, volume, buy_volume, open_index, is_closed). Indicators are written into this DataFrame later by `DataPreparer`. `SimulationData` and `FullData` consume it at runtime.

---

## Files

- Modify: `data.py`

---

## Interface

- `get_stock_data(pair: str) -> pd.DataFrame` — loads `graber_data.pkl` for the pair, builds and returns the wide base DataFrame

---

## Wide DataFrame Column Spec

For each `tf` in `CANDLES = [1, 5, 15, 60, 240, 1440]`:

| Column | Computation | Behavior within candle |
|--------|------------|----------------------|
| `{tf}_open_index` | `index.floor(f"{tf}min")` | Constant — candle open timestamp |
| `{tf}_open` | `groupby({tf}_open_index)["open"].transform("first")` | Constant — candle open price |
| `{tf}_high` | `groupby({tf}_open_index)["high"].expanding().max()` | Expanding max, resets at boundary |
| `{tf}_low` | `groupby({tf}_open_index)["low"].expanding().min()` | Expanding min, resets at boundary |
| `{tf}_close` | `df["close"]` (1-min close) | Current 1-min close = no forward reference |
| `{tf}_volume` | `groupby({tf}_open_index)["volume"].expanding().sum()` | Expanding sum, resets at boundary |
| `{tf}_buy_volume` | `groupby({tf}_open_index)["taker_base_vol"].expanding().sum()` | Expanding sum |
| `{tf}_is_closed` | Boolean flag | True when current row is last 1-min row of tf-period candle |

**`{tf}_is_closed` rules:**

| tf | True when |
|----|-----------|
| 1 | Always (every 1-min row is complete) |
| 5 | `index.minute % 5 == 4` |
| 15 | `index.minute % 15 == 14` |
| 60 | `index.minute == 59` |
| 240 | `index.minute == 59 and index.hour % 4 == 3` |
| 1440 | `index.minute == 59 and index.hour == 23` |

---

## Key Constraints

- `{tf}_close` is ALWAYS the 1-min close at that row — never a forward reference, never the TF-period close
- `{tf}_high` / `{tf}_low` use expanding max/min WITHIN candle period — they reset at each new candle open
- For `tf=1`: all `1_*` columns equal the raw 1-min values (trivial case)
- Index remains 1-minute DatetimeIndex throughout — no resampling of the index
- `graber_data.pkl` columns renamed from `o/h/l/c/v` to `open/high/low/close/volume` inside `get_stock_data()` before building wide columns

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
import os; os.environ['PAIR']='link_usdt'; os.environ['ROOT_FOLDER']='short'
from data import get_stock_data
df = get_stock_data('link_usdt')
# Check 5-min candle at a boundary
row_09_04 = df.loc['2023-09-01 09:04']
assert row_09_04['5_is_closed'] == True
row_09_02 = df.loc['2023-09-01 09:02']
assert row_09_02['5_is_closed'] == False
# open_index same for rows in same candle
assert row_09_02['5_open_index'] == row_09_04['5_open_index']
print('wide df builder ok, shape:', df.shape)
"
```

---

## Commit

`feat: implement wide DataFrame builder — get_stock_data()`
