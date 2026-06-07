# Task 02: SimulationOrchestrator

**Phase:** 08 — Backtesting  
**Depends on:** Task 01 (TrainRobot), Phase 03 Task 06 (SimulationData)  
**Produces:** `backtesting/simulation_orchestrator.py` — parallel simulation runner with result aggregation

---

## Goal

Implement `SimulationOrchestrator` — splits time range into worker segments, runs `TrainRobot` instances in parallel, and aggregates trade results across all workers.

---

## Context

Single simulation run loops through every `data_point` in `SimulationData`, calling `robot.step()` per tick. Parallelism achieved by splitting the DataFrame time range into N segments, running N workers simultaneously. Results collected and merged into unified `PerformanceAnalyzer` input.

---

## Files

- Create: `backtesting/simulation_orchestrator.py`
- Create: `backtesting/__init__.py` (empty)

---

## Interface

**`SimulationOrchestrator(strategy_factory: Callable[[], StrategyManager], fee: float)`**

Attributes:
- `strategy_factory: Callable` — zero-arg factory returning configured `StrategyManager`; called once per worker
- `fee: float`
- `num_workers: int` — read from `NUM_WORKERS` env var, default 4

**`run(simulation_data: SimulationData) -> list[dict]`**
- Calls `simulation_data.split(num_workers)` → list of `SimulationData` segments (shared `_df`, independent timestamp slices)
- Spawns one worker per segment via process pool
- Each worker: creates `TrainRobot(strategy_factory(), fee)`, loops `robot.step(dp)` for each data point in segment
- Collects `robot.get_results()` from each worker
- Returns list of result dicts (one per worker)

**`run_single(simulation_data: SimulationData) -> dict`**
- Single-threaded variant — same logic without parallelism
- Useful for debugging and small datasets

**`_worker(segment_data: SimulationData, strategy_factory: Callable, fee: float) -> dict`**
- Worker function: calls `strategy_factory()` to get independent `StrategyManager`, builds `TrainRobot`, loops all data points, returns results

---

## Key Constraints

- `strategy_factory` called N times (once per worker) — each worker gets independent `StrategyManager` instance; no shared state
- `SimulationData.split()` preserves chronological order within each segment — segments are contiguous non-overlapping timestamp slices
- Workers run in separate processes (not threads) to bypass GIL for CPU-bound indicator computation
- Worker crash: log error, return empty result for that segment — do not abort entire run
- `TrainRobot.step()` takes only `data_point` — no action parameter; strategy decides action internally via `StrategyManager.check()`

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from backtesting.simulation_orchestrator import SimulationOrchestrator
from strategies.strategy_manager import StrategyManager
from strategies.example_strategy_long import ExampleStrategyLong

def factory():
    sm = StrategyManager(fee=0.001)
    sm.register(ExampleStrategyLong(fee=0.001))
    return sm

orch = SimulationOrchestrator(strategy_factory=factory, fee=0.001)
print('orchestrator ok')
"
```

---

## Commit

`feat: implement SimulationOrchestrator with parallel worker pool and result aggregation`
