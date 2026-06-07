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

**`LiveDataCollector(stock: StockInterface, output_path: str, coin: str, interval_seconds: int = 60)`**

Attributes:
- `stock: StockInterface`
- `output_path: str`
- `coin: str` — lowercase coin name (e.g. `"link"`), passed directly to `get_candles_history()`
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
- Determines `last_timestamp` from last `open_time` in loaded data (or None if empty)
- Calls `stock.get_candles_history([1], self.coin)` → takes `result[1]` (1-min DataFrame)
- Filters rows where `open_time > last_timestamp` (or all rows if empty)
- Renames columns `open→o, high→h, low→l, close→c, volume→v` to match `graber_data.pkl` schema
- If new rows present: calls `_append_save(existing, new_rows)`, logs count appended
- If no new rows: no-op (candle not yet closed)

**`_append_save(existing: pd.DataFrame, new_rows: pd.DataFrame) -> None`**
- Concatenates `existing` + `new_rows`, drops duplicate `open_time` rows (keep last)
- Atomic save to `output_path`

---

## Key Constraints

- Append-only: never truncate or rewrite existing rows
- Duplicate guard: `open_time` dedup prevents double-appending if poll overlaps previous fetch range
- Atomic save on every poll cycle — crash-safe
- `get_candles_history([1], coin)` returns plain-named columns (`open`, `high`, etc.) — column rename to short aliases (`o`, `h`, etc.) is `_poll()`'s responsibility, NOT `get_candles_history()`'s
- `close_time` and `taker_base_vol` columns preserved as-is from `get_candles_history` result (already present in the response per Phase 01 Task 02 schema)
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
collector = LiveDataCollector(stock=stock, output_path='/tmp/live_test.pkl', coin='link')
print('live_data_collector ok')
"
```

---

## Commit

`feat: implement LiveDataCollector 60-second polling loop for continuous data collection`
