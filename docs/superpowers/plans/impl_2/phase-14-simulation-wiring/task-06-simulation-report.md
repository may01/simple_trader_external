# Task 06: Simulation report

**Phase:** 14 — Simulation Wiring
**Depends on:** Task 05 (sim folder), Phase 08 Task 03 (PerformanceAnalyzer)
**Produces:** `report.json` written into each `sim_<id>/` folder; `trainer.py simulate` wired to test strategies

---

## Goal

Requirement 7: produce a report of the simulation. After a run, write `{simulation_folder(sim_id)}report.json` containing the `PerformanceAnalyzer` metrics plus run metadata (sim_id, strategy set, window, action counts by event). Wire `trainer.py simulate` to use `TestStrategyFactory` when `STRATEGY_SET=test`.

---

## Context

`PerformanceAnalyzer.analyze()` already computes win rate, drawdown, profit factor, etc. from worker revenue results. This task assembles those metrics with run context into a JSON report living beside the actions, so a simulation folder is self-describing: `actions.jsonl` (what happened) + `report.json` (the summary).

`training/trainer.py::_run_simulate` currently builds `_DefaultStrategyFactory` (registers nothing). Switch the factory based on `STRATEGY_SET`.

---

## Files

- Create: `backtesting/simulation_report.py` — `SimulationReport`
- Modify: `backtesting/simulation_orchestrator.py` — call report writer after persisting actions (or expose data for it)
- Modify: `training/trainer.py` — select factory by `STRATEGY_SET`; surface `sim_id` into `metadata["simulate"]`

---

## Interface

**`backtesting/simulation_report.py`:**
- `class SimulationReport:`
  - `__init__(self, sim_id: int, metrics: dict, action_counts: dict[str, int], context: dict)` — `metrics` from `PerformanceAnalyzer.analyze()`; `action_counts` = count of actions per `event`; `context` = `{"strategy_set", "pair", "begin_ts", "end_ts", "step_min", "num_workers", "fee"}`
  - `to_dict(self) -> dict` — `{"sim_id", "metrics", "action_counts", "context"}`
  - `write(self, folder: str) -> str` — writes `folder + "report.json"` (pretty-printed), returns the path
  - `@staticmethod action_counts_from_jsonl(jsonl: str) -> dict[str, int]` — tally events from the merged actions JSONL

**SimulationOrchestrator** (extends Task 05 `run`):
- After `_persist_actions`, build `PerformanceAnalyzer(results).analyze()`, build `SimulationReport(...).write(simulation_folder(sim_id))`
- `run()` return dict gains `report_path`

**trainer.py `_run_simulate`:**
- `strategy_set = os.environ.get("STRATEGY_SET", "default")`
- `factory = TestStrategyFactory(fee) if strategy_set == "test" else _DefaultStrategyFactory(fee)`
- record `sim_id` and `report_path` in `self.metadata["simulate"]`

---

## Key Constraints

- `report.json` is valid JSON with no NaN — `PerformanceAnalyzer` already guards div-by-zero; `inf` profit_factor must be serialised as a JSON-safe sentinel (string `"inf"` or large float — pick one and document), never raw `float('inf')` which breaks strict parsers.
- Report lives in the SAME folder as `actions.jsonl` — one folder fully describes one simulation.
- `total_trades` in metrics must equal the count of `CLOSE` + `STOP_LOSS` events in `action_counts` — assert this consistency in the report writer (catches wiring drift between the two layers).
- Backward compatibility: `_DefaultStrategyFactory` path (no test strategies) still runs and writes a report with zero trades — empty runs are valid, not errors.

---

## Verification

```bash
docker run --rm -v "$PWD":/code -w /code simple_trader python3 -c "
import json, tempfile, os
from backtesting.simulation_report import SimulationReport
jsonl = '\n'.join(['{\"event\":\"OPEN\"}','{\"event\":\"CLOSE\"}','{\"event\":\"SIGNAL_FIRED\"}'])
counts = SimulationReport.action_counts_from_jsonl(jsonl)
assert counts['OPEN']==1 and counts['CLOSE']==1
d = tempfile.mkdtemp()+'/'
p = SimulationReport(5, {'total_trades':1,'win_rate':1.0}, counts, {'strategy_set':'test'}).write(d)
assert json.load(open(p))['sim_id']==5
print('report ok:', p)
"
```

Plus: `docker compose run --rm -e STRATEGY_SET=test trainer python3 trainer.py simulate` writes `report.json` next to `actions.jsonl`.

---

## Commit

`feat: write per-simulation report.json and wire trainer simulate to test strategies`
