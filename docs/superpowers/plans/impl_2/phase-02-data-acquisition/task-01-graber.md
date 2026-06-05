# Task 01: Graber — Raw Kline Collection

**Phase:** 02 — Data Acquisition  
**Depends on:** Phase 01 (StockHolder, BinanceStock)  
**Produces:** `grabers/grab_binance.py` — downloads Binance 1-min OHLCV and writes `graber_data.pkl`

---

## Goal

Implement `grabers/grab_binance.py` (Path A). Fetches raw 1-minute OHLCV klines from Binance for `DATA_START` → `DATA_END` range and saves `graber_data.pkl`. Must support incremental mode: if file exists, only download missing date range and merge.

---

## Context

`graber_data.pkl` is the raw input to the entire offline pipeline. Every other offline component (`DataPreparer`, `SimulationData`, `FullData`) ultimately depends on this file. The download uses `BinanceClient.get_historical_klines()` in 30-day chunks to stay within API limits. This is the ONLY component that performs Binance API calls in the offline pipeline.

---

## Files

- Create: `grabers/grab_binance.py`
- Create: `grabers/__init__.py` (empty)

---

## Interface

Script entry point: `python3 grabers/grab_binance.py`

**Key functions:**
- `grab_data(pair: str, start_ms: int, end_ms: int) -> pd.DataFrame` — fetches klines in 30-day chunks, returns 1-min indexed DataFrame
- `load_existing(path: str) -> pd.DataFrame | None` — loads existing pickle if present
- `merge_incremental(existing: pd.DataFrame, new_data: pd.DataFrame) -> pd.DataFrame` — merges without duplicates, re-indexes
- `save_atomic(df: pd.DataFrame, path: str) -> None` — writes to temp file, then renames (atomic)
- `validate_1min_spacing(df: pd.DataFrame) -> None` — raises if any gap > 1 min in index

---

## Output DataFrame Schema

Columns after download and parsing:

| Column | Type | Description |
|--------|------|-------------|
| `open_time` | Timestamp | Candle open time (also the index) |
| `o` | float64 | Open price |
| `h` | float64 | High price |
| `l` | float64 | Low price |
| `c` | float64 | Close price |
| `v` | float64 | Volume |
| `close_time` | Timestamp | Candle close time |
| `taker_base_vol` | float64 | Taker buy base asset volume |

Index: `pd.DatetimeIndex`, 1-minute frequency, UTC.

---

## Incremental Mode Logic

1. Load `graber_data.pkl` if it exists
2. Compare existing date range to requested `DATA_START` → `DATA_END`
3. Fetch only the missing range (before existing start, or after existing end)
4. Merge new data with existing, sort by index, drop duplicates
5. Validate 1-min spacing on merged result
6. Save atomically

---

## Key Constraints

- Uses `BinanceClient.get_historical_klines()` directly (not `stock.item` — this script runs before `do_stock_init`)
- Fetches in 30-day chunks to avoid Binance API limits
- `graber_data.pkl` must use 1-min DatetimeIndex (no gaps)
- Save is atomic: write to `graber_data.pkl.tmp` then `os.rename()` — prevents corrupt files on interrupt
- Column names use short aliases (`o`, `h`, `l`, `c`, `v`) to match downstream expectations in `DataPreparer`
- `DATA_START` / `DATA_END` are milliseconds — divide by 1000 for Binance API call

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
import pandas as pd
from helpers import graber_data_path
df = pd.read_pickle(graber_data_path())
assert df.index.freq == '1T' or (df.index[1] - df.index[0]).seconds == 60
assert set(['o','h','l','c','v','taker_base_vol']).issubset(df.columns)
print('graber ok, rows:', len(df), 'range:', df.index[0], '->', df.index[-1])
"
```

---

## Commit

`feat: implement Graber — Binance 1-min kline collection with incremental mode`
