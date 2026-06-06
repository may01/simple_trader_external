# Task 01: Graber — Raw Kline Collection

**Phase:** 02 — Data Acquisition  
**Depends on:** Phase 01 — convention-only (mirrors `Stock_Binance`'s credential-loading and kline-parsing conventions; no runtime import of `StockHolder`/`BinanceStock`, see Key Constraints)  
**Produces:** `grabers/grab_binance.py` — downloads Binance 1-min OHLCV and writes `graber_data.pkl`

---

## Goal

Implement `grabers/grab_binance.py` (Path A). Fetches raw 1-minute OHLCV klines from Binance for `DATA_START` → `DATA_END` range and saves `graber_data.pkl`. Must support incremental mode: if file exists, only download missing date range and merge.

---

## Context

`graber_data.pkl` is the raw input to the entire offline pipeline. Every other offline component (`DataPreparer`, `SimulationData`, `FullData`) ultimately depends on this file. The download uses `BinanceClient.get_historical_klines()` in 30-day chunks to bound per-call memory use and allow incremental progress/resume on failure (the helper already auto-paginates within each chunk to respect Binance's per-request candle cap). This is the ONLY component that performs Binance API calls in the offline pipeline.

---

## Files

- Modify: `grabers/grab_binance.py` (replaces Phase 00 stub with full implementation)
- Modify: `grabers/__init__.py` (already an empty package marker from Phase 00 — no change needed, listed for completeness)

---

## Interface

Script entry point: `python3 grabers/grab_binance.py`

**Key functions:**
- `grab_data(pair: str, start_ms: int, end_ms: int) -> pd.DataFrame` — fetches klines in 30-day chunks, returns 1-min indexed DataFrame; `pair` is in `coin_coinbase` format (e.g. `"link_usdt"`, matching the `PAIR` env var convention) — split on `"_"`, uppercase, and concatenate to build the Binance symbol (e.g. `"LINKUSDT"`), mirroring `Stock_Binance.get_pair_name()`
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
4. Validate 1-min spacing on each freshly-fetched chunk — raise immediately with the offending range if a gap or duplicate is found (pinpoints API-side gaps before they mix into existing data)
5. Merge new data with existing, sort by index, drop duplicates
6. Validate 1-min spacing on merged result (catches merge-boundary gaps)
7. Save atomically

---

## Key Constraints

- Uses `BinanceClient.get_historical_klines()` directly (not `stock.item` — this script runs before `do_stock_init`); builds its own `BinanceClient` from `BINANCE_API_KEY` / `BINANCE_API_SECRET` env vars (exception if either absent), same credential-loading pattern as `Stock_Binance.__init__`
- Fetches in 30-day chunks to bound per-call memory use and allow resumable progress (not an API-limit workaround — `get_historical_klines()` auto-paginates internally)
- `graber_data.pkl` must use 1-min DatetimeIndex (no gaps)
- Save is atomic: write to `graber_data.pkl.tmp` then `os.rename()` — prevents corrupt files on interrupt
- Column names use short aliases (`o`, `h`, `l`, `c`, `v`) to match downstream expectations in `DataPreparer`
- `DATA_START` / `DATA_END` env vars (`os.environ`, set per dataset `.env` file) are milliseconds — divide by 1000 for Binance API call

---

## Verification

```bash
docker compose run --rm graber python3 -c "
import pandas as pd
from helpers import graber_data_path
df = pd.read_pickle(graber_data_path())
assert (df.index[1] - df.index[0]).seconds == 60
assert set(['o','h','l','c','v','taker_base_vol']).issubset(df.columns)
print('graber ok, rows:', len(df), 'range:', df.index[0], '->', df.index[-1])
"
```

---

## Commit

`feat: implement Graber — Binance 1-min kline collection with incremental mode`
