# Task 04: NN Orchestrator

**Phase:** 11 — NN Module  
**Depends on:** Tasks 01-03 (NNModel, NNPredictor, CheckpointManager), Phase 08 (SimulationOrchestrator), Phase 09 Task 02 (DataPreparer output)  
**Produces:** `nn/nn_orchestrator.py` — group/train/simulate NN pipeline coordinator

---

## Goal

Implement `NNOrchestrator` — coordinates the full NN pipeline: group training data by pattern, train models per group, run post-training simulation to evaluate signal quality, select best models.

---

## Context

NN training has three phases: (1) group candle patterns by similarity, (2) train one model per group, (3) simulate using trained models to measure real trade impact. `NNOrchestrator` wires these together. Called from `Trainer._run_train_nn()`. Multiple models can be trained (one per TF or per pattern group).

---

## Files

- Create: `nn/nn_orchestrator.py`

---

## Interface

**`NNOrchestrator(checkpoint_dir: str, feature_cols: list[str], confidence_threshold: float = 0.6)`**

Attributes:
- `checkpoint_dir: str`
- `feature_cols: list[str]`
- `confidence_threshold: float`
- `trained_models: dict[str, NNModel]` — keyed by group/TF identifier

**`train(df: pd.DataFrame, data_attributes: DataAttributes, tfs: list[int]) -> dict`**
- For each TF in `tfs`:
  - Extracts feature matrix from `df` using `feature_cols`
  - Extracts target labels from `df` (`{tf}_target_direction` column)
  - Drops rows with NaN targets
  - Builds `NNModel(input_size=len(feature_cols))`
  - Calls `model.train(X, y)`
  - Saves via `CheckpointManager`
  - Stores in `trained_models[str(tf)]`
- Returns dict of training metrics per TF

**`simulate(simulation_data: SimulationData, strategy_factory: Callable, fee: float) -> dict`**
- Loads best models from checkpoints into `NNPredictor` instances
- Runs `SimulationOrchestrator` with NN-filtered strategy
- Returns `PerformanceAnalyzer` metrics

**`load_predictors(data_attributes: DataAttributes) -> dict[str, NNPredictor]`**
- Loads best checkpoint per TF, wraps each in `NNPredictor`
- Returns `{tf_str: predictor}` dict for injection into `StrategyManager`

---

## Key Constraints

- One model per TF — not per pattern group in initial implementation (grouping is future scope)
- Rows with NaN features or NaN targets excluded from training — not filled
- `confidence_threshold` propagated to all `NNPredictor` instances created by `load_predictors()`
- `simulate()` is optional — `Trainer` may call `train()` without `simulate()` for fast cycles
- `trained_models` keyed by string (`"15"`, `"60"`) not int — dict serialization safe

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from nn.nn_orchestrator import NNOrchestrator
orch = NNOrchestrator(
    checkpoint_dir='/tmp/nn_test',
    feature_cols=['15_rsi_14', '15_cci_14', '60_rsi_14']
)
print('nn_orchestrator ok')
"
```

---

## Commit

`feat: implement NNOrchestrator coordinating train-simulate-select NN pipeline`
