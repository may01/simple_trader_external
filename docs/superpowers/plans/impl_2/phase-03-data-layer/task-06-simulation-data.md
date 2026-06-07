# Task 06: SimulationData

**Phase:** 03 — Data Layer  
**Depends on:** Task 02 (wide DataFrame), Task 01 (WideDataPoint)  
**Produces:** `data.py` — `SimulationData` class — O(1) replay from pre-computed wide DataFrame

---

## Goal

Implement `SimulationData` — loads `df_with_indicators.pkl` once at init, then yields `WideDataPoint` at each replay step with O(1) cost. Replaces the old `DataIterator` (per-step pickle loads).

---

## Context

`SimulationData` is the simulation-path data source. `TrainRobot` (via `SimulationOrchestrator`) calls `sim.get()` to get the current `WideDataPoint`, passes it to `StrategyManager.check()`, calls `step()`, then advances with `sim.next()`. No I/O after init — all data pre-loaded into memory.

---

## Files

- Modify: `data.py`

---

## Interface

**SimulationData:**
- `__init__(pair: str, begin_ts: int, end_ts: int, step_min: int)` — loads `df_with_indicators.pkl` once; builds `self._timestamps` range from `begin_ts` to `end_ts` at `step_min` intervals; validates timestamps exist in DataFrame
- `get() -> WideDataPoint` — returns `WideDataPoint(self._df, self._timestamps[self._cur_idx])` — O(1), no I/O
- `next() -> None` — advances `self._cur_idx += 1`
- `is_end() -> bool` — returns `self._cur_idx >= len(self._timestamps)`
- `steps: int` (property) — total replay length = `len(self._timestamps)`
- `current_ts: pd.Timestamp` (property) — timestamp at current position
- `split(n: int) -> list[SimulationData]` — divides `self._timestamps` into `n` equal slices; returns `n` new `SimulationData` instances sharing the same `_df` (no re-load); last slice absorbs remainder rows

---

## Timestamp Range Construction

- `begin_ts` and `end_ts` are Unix seconds (not milliseconds)
- Build `pd.date_range(begin, end, freq=f"{step_min}min")` as `self._timestamps`
- Filter to only timestamps that exist in `self._df.index` — skip missing (holidays, data gaps)
- Log warning if more than 1% of timestamps are missing

---

## Key Constraints

- `df_with_indicators.pkl` loaded ONCE at `__init__` — never reloaded during simulation
- `get()` is O(1) — `df.loc[ts]` row lookup, no computation
- `SimulationData` is NOT a singleton — instantiated per simulation run (one per worker process in parallel backtest)
- `split(n)` returns instances that share the parent's `_df` reference — no copy, no re-load; each instance has its own `_timestamps` slice and `_cur_idx = 0`
- `begin_ts` / `end_ts` are Unix seconds (DATA_START / DATA_END are ms → divide by 1000 when reading from env)
- `step_min` from `TRAINER_TIME_STEP` env var — minimum 1 minute
- `WideDataPoint` from `get()` shares reference to the full DataFrame — do not modify it

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
import os
os.environ['PAIR'] = 'link_usdt'; os.environ['ROOT_FOLDER'] = 'short'
from data import SimulationData

sim = SimulationData('link_usdt', begin_ts=1693526400, end_ts=1693612800, step_min=1)
print('total steps:', sim.steps)
count = 0
while not sim.is_end():
    pt = sim.get()
    val = pt.get('rsi_14', tf=5)
    sim.next()
    count += 1
    if count > 5: break
print('sim loop ok, steps sampled:', count)
"
```

---

## Commit

`feat: implement SimulationData — single-load replay with O(1) per-step access`
