# Task 04: LiveDataCollector

**Phase:** 09 — Training Pipeline  
**Depends on:** Phase 01 (StockHolder, BinanceStock), Phase 03 Task 05 (LiveData)  
**Produces:** `training/live_data_collector.py` — 60-second polling loop for live OHLCV collection

---

## Goal

Implement `LiveDataCollector` — runs continuously, polls Binance every 60 seconds for new 1-minute candles, appends to `graber_data.pkl` incrementally.

---

## Context

Execution path A (data collection) runs this as a long-lived process. Distinct from batch grab: `LiveDataCollector` is continuous, `Graber` is one-shot. Used to keep training data current without re-fetching history. Appends only; never rewrites existing rows.

---

## Files

- Create: `training/live_data_collector.py`

---

## Interface

**`LiveDataCollector(stock: StockInterface, output_path: str, symbol: str, interval_seconds: int = 60)`**

Attributes:
- `stock: StockInterface`
- `output_path: str`
- `symbol: str`
- `interval_seconds: int`
- `running: bool = False`

**`start() -> None`**
- Sets `running = True`
- Enters poll loop: sleep `interval_seconds`, call `_poll()`, repeat
- Catches `KeyboardInterrupt` → sets `running = False`, exits cleanly

**`stop() -> None`**
- Sets `running = False`; loop exits on next iteration

**`_poll() -> None`**
- Loads existing `output_path` (or empty DataFrame if not present)
- Determines `last_timestamp` from loaded data
- Fetches candles from `last_timestamp` to now via `stock.get_candles_history()`
- If new candles: appends to DataFrame, saves atomically
- Logs count of new rows appended

**`_append_save(existing: pd.DataFrame, new_rows: pd.DataFrame) -> None`**
- Concatenates `existing` + `new_rows`, drops duplicate `open_time` rows (keep last)
- Atomic save to `output_path`

---

## Key Constraints

- Append-only: never truncate or rewrite existing rows
- Duplicate guard: `open_time` dedup prevents double-appending if poll overlaps previous fetch range
- Atomic save on every poll cycle — crash-safe
- `interval_seconds=60` matches 1-minute candle close cadence; shorter intervals waste API weight
- Graceful shutdown: `stop()` and `KeyboardInterrupt` both land the same exit path

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from training.live_data_collector import LiveDataCollector
from stocks.stock_holder import StockHolder
from constants import STOCK_MOCK

StockHolder.do_stock_init(STOCK_MOCK)
stock = StockHolder.get_stock()
collector = LiveDataCollector(stock=stock, output_path='/tmp/live_test.pkl', symbol='LINKUSDT')
print('live_data_collector ok')
"
```

---

## Commit

`feat: implement LiveDataCollector 60-second polling loop for continuous data collection`
