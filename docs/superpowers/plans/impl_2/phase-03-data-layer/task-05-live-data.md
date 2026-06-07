# Task 05: LiveData

**Phase:** 03 — Data Layer  
**Depends on:** Task 04 (indicator fields), Phase 01 (StockHolder)  
**Produces:** `data.py` — `LiveData` class, module-level `data.item` singleton

---

## Goal

Implement `LiveData` — the live-path data orchestrator. Called every tick by Robot: fetches fresh candles from Binance, computes all indicators, and returns a `LiveDataPoint` ready for signal evaluation.

---

## Context

`data.item` is the only module-level singleton in the system. `LiveData.build_candles(time_point)` calls `stock.item.get_candles_history()`, runs `Indicators.compute()` per TF, and exposes `get_data_point()`. Robot calls `build_candles()` once per tick, then passes the resulting `LiveDataPoint` to `StrategyManager.check()`.

---

## Files

- Modify: `data.py`

---

## Interface

**LiveData class:**
- `__init__(nn_predictor=None)` — loads `CANDLES` from config; reads `PAIR` from env; stores optional `NNPredictor` instance
- `build_candles(time_point: int = 0) -> None` — fetches from `stock.item.get_candles_history(CANDLES, coin, time_point)`, which returns plain-named columns (`open`, `high`, `low`, `close`, `volume`, ...; see phase-01 task-02). For each TF: rename columns to `{tf}_{col}` (`open`→`{tf}_open`, etc.) and add `{tf}_is_closed = True` for every row (candles from `get_candles_history` are always fully-closed historical candles — unlike the wide DataFrame's partial-candle rows). Then wrap `{tf: ohlc[tf]}` in a `LiveDataPoint` and call `Indicators.compute(point, tf)` (per task-03's `compute(data_point: DataPoint, tf: int)` signature — writes results back via `point.get_df(tf)`, which is the same `ohlc[tf]` DataFrame, mutated in place). After all TFs: if `self.nn_predictor` is set, calls `nn_predictor.compute(point, tf)` for each TF to append `{tf}_nn_prob_*` columns; stores in `self.ohlc`
- `get_data_point() -> LiveDataPoint` — wraps current `self.ohlc` in `LiveDataPoint`
- `get_depth_data(quantity: int) -> tuple[pd.DataFrame, pd.DataFrame]` — calls `stock.item.depth(quantity)`
- `ohlc: dict[int, pd.DataFrame]` — current per-TF enriched DataFrames

**Module-level:**
- `item: LiveData` — singleton instance created at module load

---

## Key Constraints

- `data.item` is a TRUE module-level singleton — only one instance exists per process
- `build_candles()` has NO return value — callers use `get_data_point()` separately
- After `build_candles()`, `self.ohlc[tf]` contains enriched DataFrame with all `{tf}_*` indicator columns
- `get_candles_history()` returns plain-named OHLCV columns (phase-01 task-02) — `build_candles()` is the ONLY place that renames them to `{tf}_{col}` and synthesizes `{tf}_is_closed`; no other module does this for the live path
- `Indicators.compute()` is called per TF, in order of `CANDLES` list — no parallelism in live path
- `data.item` uses `stock.item` — `do_stock_init()` must be called before first `build_candles()` call
- No `FullData` singleton: `FullData` instantiated per run, not at module level
- Live path does NOT compute forward-looking `future_target` columns — those are offline only
- `nn_predictor` is optional — if absent (no checkpoint), `nn_prob_*` columns simply absent from `LiveDataPoint`; signals using them must handle NaN
- `NNPredictor.compute()` called AFTER all `Indicators.compute()` calls — NN features must already be populated

---

## Verification

```bash
docker compose -f docker-compose-live.yml run --rm trader python3 -c "
from stocks_holder import do_stock_init
do_stock_init('binance')
import data
data.item.build_candles()
pt = data.item.get_data_point()
rsi = pt.get('rsi_14', tf=15)
print('live data ok, 15m RSI:', rsi)
assert isinstance(rsi, float)
"
```

---

## Commit

`feat: implement LiveData — per-tick candle fetch + indicator compute`
