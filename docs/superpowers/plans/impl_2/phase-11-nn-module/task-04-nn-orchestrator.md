# Task 04: NN Orchestrator

**Phase:** 11 — NN Module  
**Depends on:** Tasks 01, 03 (NNModel, CheckpointManager), Phase 03 Task 07 (DataAttributes), Phase 09 Task 02 (DataPreparer output)  
**Produces:** `nn/nn_orchestrator.py` — group/train/simulate NN pipeline coordinator

---

## Goal

Implement `NNOrchestrator` — coordinates the NN pipeline: train one model per TF, save checkpoints, and run batch inference over the full dataset appending NN probability columns.

---

## Context

`NNOrchestrator` has two modes: (1) `train()` — called by `Trainer._run_train_nn()`, trains one `NNModel` per TF, saves via `CheckpointManager`; (2) `run_inference()` — called by `Trainer._run_simulate_nn()`, loads best checkpoints and runs batch inference over the full `df_with_indicators` DataFrame, returning a NN-columns-only DataFrame saved as `df_with_nn.pkl`. On next `DataPreparer.prepare()` run, those columns are merged into `df_with_indicators.pkl` making them available as regular indicators.

---

## Files

- Create: `nn/nn_orchestrator.py`

---

## Interface

**`NNOrchestrator(checkpoint_dir: str, feature_cols: list[str])`**

Attributes:
- `checkpoint_dir: str`
- `feature_cols: list[str]`
- `num_workers: int` — read from `NUM_WORKERS` env var, default 4
- `trained_models: dict[str, NNModel]` — keyed by TF string (`"15"`, `"60"`)

**`train(df: pd.DataFrame, data_attributes: DataAttributes, tfs: list[int], epoch_callback: Callable[[str, int, dict], None] = None) -> dict`**
- For each TF in `tfs`:
  - Extracts feature matrix from `df` using `feature_cols` (closed-candle rows only)
  - **Target label column name and labeling logic: UNRESOLVED — see README § Unresolved**
  - Drops rows with NaN features or NaN targets
  - Builds `NNModel(input_size=len(feature_cols_for_tf))`
  - Calls `model.train(X, y, epoch_callback=lambda ep, m: epoch_callback(str(tf), ep, m) if epoch_callback else None)`
  - Saves via `CheckpointManager`
  - Stores in `trained_models[str(tf)]`
- Returns dict of training metrics per TF: `{tf_str: {loss, accuracy, val_loss, val_accuracy}}`

**`run_inference(df: pd.DataFrame, data_attributes: DataAttributes, tfs: list[int]) -> pd.DataFrame`**
- Loads best checkpoint per TF via `CheckpointManager.load_best()`
- For each TF: normalizes feature matrix using `data_attributes.get_stats()`, runs `model.run_batch(X)` → `(N, 3)` probability array
- Appends columns `{tf}_nn_prob_up`, `{tf}_nn_prob_neutral`, `{tf}_nn_prob_down` to a new DataFrame indexed by `df.index`
- Returns DataFrame containing ONLY the appended NN columns (not a copy of `df`)

---

## Key Constraints

- One model per TF — not per pattern group in initial implementation (grouping is future scope)
- Rows with NaN features or NaN targets excluded from training — not filled
- `run_inference()` returns ONLY NN columns — caller saves to `df_with_nn.pkl`; does not modify input `df`
- Rows with NaN features: NN output columns set to `NaN` for those rows — not skipped
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
print('nn_orchestrator ok, trained_models:', orch.trained_models)
"
```

---

## Commit

`feat: implement NNOrchestrator coordinating train-simulate-select NN pipeline`
