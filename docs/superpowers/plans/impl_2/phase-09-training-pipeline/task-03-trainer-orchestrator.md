# Task 03: Trainer Orchestrator

**Phase:** 09 — Training Pipeline  
**Depends on:** Task 02 (DataPreparer), Phase 08 (SimulationOrchestrator, PerformanceAnalyzer), Phase 11 Tasks 01-04 (NNOrchestrator)  
**Produces:** `training/trainer.py` — thin orchestrator dispatching RUN_TYPE-based pipeline execution

---

## Goal

Implement `Trainer` — top-level orchestrator invoked by Docker entry point. Dispatches to correct pipeline path based on `RUN_TYPE` env var: data prep, simulation, NN training, or full pipeline.

---

## Context

`Trainer` is the entry point for all training-related execution paths (Docker execution path D). It reads `RUN_TYPE` and `SCRIPT_TYPE` env vars, calls the appropriate subsystem, and manages metadata (run timestamps, performance metrics, model paths). Thin by design — no business logic, only orchestration.

---

## Files

- Create: `training/trainer.py`

---

## Interface

**`Trainer(config_path: str = "config/")`**

Attributes:
- `config_path: str`
- `run_type: str` — from `os.environ["RUN_TYPE"]`
- `metadata: dict` — collects run metadata for logging

**`run() -> None`**
- Dispatches on `self.run_type`:
  - `"grab_data"` → `_run_grab_data()`
  - `"prepare_data"` → `_run_prepare_data()`
  - `"simulate"` → `_run_simulate()`
  - `"train_nn"` → `_run_train_nn()`
  - `"simulate_nn"` → `_run_simulate_nn()`
  - `"full"` → `_run_grab_data()` → `_run_prepare_data()` → `_run_simulate()` → `_run_train_nn()` → `_run_simulate_nn()` → `_run_prepare_data()`
  - Unknown → raise `ValueError`

**`_run_grab_data() -> None`**
- Instantiates `Graber`, calls `ensure_data()` for configured symbol and date range

**`_run_prepare_data() -> None`**
- Instantiates `DataPreparer`, calls `prepare(raw_data_path)`
- Writes preparation stats to metadata

**`_run_simulate() -> None`**
- Loads `SimulationData` from `df_with_indicators.pkl`
- Instantiates `SimulationOrchestrator` with configured strategy factory
- Calls `orch.run(simulation_data)`
- Instantiates `PerformanceAnalyzer(results)`, calls `analyze()`
- After each worker completes: atomically writes `shared/training_state.pkl` with `phase="simulate"`, cumulative `revenue_history`, `win_rate`, `total_trades` (for TrainingDashboard)
- Writes final performance metrics to metadata

**`_run_train_nn() -> None`**
- Loads `(df, data_attributes)` tuple from `df_with_indicators.pkl`
- Instantiates `NNOrchestrator(checkpoint_dir, feature_cols)` from config
- Defines `epoch_callback(tf_str, epoch, metrics)` — atomically writes `shared/training_state.pkl` with `phase="nn_train"`, `tf`, cumulative `loss_history`, `val_loss_history` (for TrainingDashboard)
- Calls `orchestrator.train(df, data_attributes, tfs, epoch_callback=epoch_callback)`
- Writes final training metrics to metadata

**`_run_simulate_nn() -> None`**
- Loads `(df, data_attributes)` tuple from `df_with_indicators.pkl`
- Instantiates `NNOrchestrator` from config
- Calls `orchestrator.run_inference(df, data_attributes, tfs)` → NN-columns-only DataFrame
- Saves result to `df_with_nn.pkl` atomically
- Writes inference stats (row count, TFs covered) to metadata

**`_save_metadata(path: str) -> None`**
- Writes `self.metadata` as JSON to `path`

---

## Key Constraints

- `Trainer` has no trading logic — pure orchestration and dispatch
- Each `_run_*` method independent — can be called individually or chained in `"full"` mode
- Metadata written after each stage — partial runs produce partial metadata
- `RUN_TYPE` read from env at construction — not passed as argument
- `config_path` defaults to `"config/"` but can be overridden for test isolation

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
import os
os.environ['RUN_TYPE'] = 'prepare_data'
from training.trainer import Trainer
t = Trainer()
print('trainer ok, run_type:', t.run_type)
"
```

---

## Commit

`feat: implement Trainer orchestrator with RUN_TYPE-based pipeline dispatch`
