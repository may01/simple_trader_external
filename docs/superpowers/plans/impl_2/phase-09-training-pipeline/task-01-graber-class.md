# Task 01: Graber Class

**Phase:** 09 — Training Pipeline  
**Depends on:** Phase 01 (StockHolder, BinanceStock), Phase 02 (grab_binance script)  
**Produces:** `training/graber.py` — class wrapper around raw data acquisition for DataPreparer integration

---

## Goal

Implement `Graber` class — thin wrapper that DataPreparer calls to ensure raw OHLCV data is present and up-to-date before indicator computation begins.

---

## Context

`grab_binance.py` (Phase 02) is a standalone script. `DataPreparer` needs programmatic access to the same logic. `Graber` class wraps the fetch-and-save cycle: check if `graber_data.pkl` exists and is current, fetch missing candles if not, save atomically. Distinct from the CLI script — this is the Python API used inside the training pipeline.

---

## Files

- Create: `training/graber.py`
- Create: `training/__init__.py` (empty)

---

## Interface

**`Graber(stock: StockInterface, output_path: str)`**

Attributes:
- `stock: StockInterface` — BinanceStock or mock; provides `get_candles_history()`
- `output_path: str` — path to `graber_data.pkl`

**`ensure_data(symbol: str, start_ms: int, end_ms: int) -> None`**
- `symbol`: Binance format (e.g. `"LINKUSDT"`)
- `start_ms` / `end_ms`: Unix milliseconds — matches `DATA_START` / `DATA_END` env vars
- If `output_path` exists: loads existing data, checks first/last `open_time` timestamp
- If data covers `start_ms` to `end_ms`: return (no-op)
- If data is partial or missing: fetches missing range via `stock.get_candles_range(symbol, start_ms, end_ms)`
- Saves result atomically (write to `.tmp`, then rename)

**`load() -> pd.DataFrame`**
- Loads and returns DataFrame from `output_path`
- Raises `FileNotFoundError` if not present

**`is_current(end_ms: int) -> bool`**
- Returns True if last row `open_time` timestamp (as Unix ms) >= `end_ms`

---

## Key Constraints

- Incremental fetch: only request candles after last saved timestamp — avoid re-fetching existing data
- Atomic save: write to `output_path + ".tmp"` then `os.rename()` — prevent partial writes
- Column schema matches Phase 02 grab_binance output: `open_time, o, h, l, c, v, close_time, taker_base_vol` (short aliases — see Phase 02 task-01-graber.md and design-decisions.md; NOT `open/high/low/close/volume`)
- All timestamps compared as Unix milliseconds — no timezone ambiguity
- `start_ms` / `end_ms` from `DATA_START` / `DATA_END` env vars (already ms — no conversion needed at this level)
- Raises clear exception if `stock.get_candles_history()` returns empty result for non-empty date range

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from training.graber import Graber
from stocks.stock_holder import StockHolder
from constants import STOCK_MOCK

StockHolder.do_stock_init(STOCK_MOCK)
stock = StockHolder.get_stock()
g = Graber(stock=stock, output_path='/tmp/test_graber.pkl')
print('graber ok')
"
```

---

## Commit

`feat: implement Graber class for programmatic OHLCV data acquisition in training pipeline`
