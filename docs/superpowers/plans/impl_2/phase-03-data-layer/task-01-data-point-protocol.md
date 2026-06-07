# Task 01: DataPoint Protocol

**Phase:** 03 — Data Layer  
**Depends on:** Phase 00 (config_loader)  
**Produces:** `data.py` — `DataPoint`, `LiveDataPoint`, `WideDataPoint` classes

---

## Goal

Implement the `DataPoint` protocol — the isolation interface between data storage and all consumers (signals, strategies). Both live and simulation paths expose the same `get(col, tf, shift)` API; consumers never access underlying DataFrames directly.

---

## Context

This is the most critical interface in the system. Every signal and strategy calls `data_point.get(col, tf, shift)` to read indicator values. `LiveDataPoint` wraps `Dict[int, pd.DataFrame]` (per-TF DataFrames from live path). `WideDataPoint` wraps a single row of the pre-computed wide DataFrame. Both implement identical `get()` semantics — `shift=0` is current, `shift=N` is N closed candles back.

---

## Files

- Create: `data.py` (first section — DataPoint classes only)

---

## Interface

**DataPoint (abstract base):**
- `get(col: str, tf: int, shift: int = 0) -> float` — primary consumer interface
- `get_df(tf: int) -> pd.DataFrame` — mutable underlying DataFrame (used ONLY by `Indicators.compute()`, not signals)
- `cur_price(price_type: str) -> float` — returns `self.get(price_type, tf=1)`; `price_type` is `'open'`/`'close'`/`'high'`/`'low'`
- `timestamp: pd.Timestamp` (abstract property) — current tick timestamp

**LiveDataPoint(DataPoint):**
- `__init__(ohlc: dict[int, pd.DataFrame])` — wraps per-TF DataFrames
- `get(col, tf, shift=0)` — returns `self._ohlc[tf][f"{tf}_{col}"].iloc[-1 - shift]`
- `get_df(tf)` — returns `self._ohlc[tf]`
- `timestamp` — returns `self._ohlc[1].index[-1]` (most recent 1-min candle timestamp)

**WideDataPoint(DataPoint):**
- `__init__(df: pd.DataFrame, ts: pd.Timestamp)` — wraps wide DataFrame at timestamp `ts`
- `timestamp` — returns `self._ts`
- `get(col, tf, shift=0)`:
  - `shift=0` → `df.loc[ts, f"{tf}_{col}"]`
  - `shift=N` → `closed = df[:ts][df[:ts][f"{tf}_is_closed"]]; closed.iloc[-N][f"{tf}_{col}"]`
  - Returns `float("nan")` if not enough history for requested shift
- `get_df(tf)` — returns reconstructed per-TF slice (for Indicators during wide DataFrame generation)

---

## Shift Semantics

| shift | LiveDataPoint | WideDataPoint |
|-------|--------------|---------------|
| 0 | `ohlc[tf].iloc[-1]` (most recent row) | `df.loc[ts, col]` (current — partial if mid-period) |
| 1 | `ohlc[tf].iloc[-2]` | last `{tf}_is_closed=True` row ≤ ts |
| N | `ohlc[tf].iloc[-1-N]` | Nth last `{tf}_is_closed=True` row ≤ ts |

---

## Key Constraints

- Column naming is always `{tf}_{col}` — e.g., `"5_rsi_14"`, `"60_close"`. `get("rsi_14", tf=5)` looks up `"5_rsi_14"`.
- `cur_price(price_type)` is defined on the base class; subclasses inherit it via `get()`. Valid types: `'open'`, `'close'`, `'high'`, `'low'`. tf=1 always used — callers must not pass tf.
- `timestamp` must be implemented by every `DataPoint` subclass — used by Robot and TrainRobot for `close_by_time()` and `StrategyManager.check()` calls.
- `get_df()` is for `Indicators.compute()` ONLY — signals must NEVER call it
- `WideDataPoint.get()` with `shift>0` performs a filter on `{tf}_is_closed` — O(n) but only done for closed-candle lookups
- `shift=0` on `WideDataPoint` returns the partial-candle value at `ts` — intentional for tick-by-tick simulation
- `float("nan")` returned (not exception) when shift exceeds available history

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
import pandas as pd
from data import LiveDataPoint, WideDataPoint

# LiveDataPoint test
df = pd.DataFrame({'5_rsi_14': [30.0, 40.0, 50.0], '5_is_closed': [True, True, True]})
lp = LiveDataPoint({5: df})
assert lp.get('rsi_14', 5, 0) == 50.0
assert lp.get('rsi_14', 5, 1) == 40.0
print('DataPoint protocol ok')
"
```

---

## Commit

`feat: implement DataPoint protocol — LiveDataPoint and WideDataPoint`
