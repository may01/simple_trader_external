# Task 11: Trainer Wiring (RUN_TYPE Dispatch)

**Phase:** 11 — NN Module  
**Depends on:** Task 08 (NNOrchestrator.from_trainer), Task 10 (TrainingLoop)  
**Produces:** reworked `trainer.py` NN dispatch (`nn_train`, `infer_nn`/`simulate_nn`)

---

## Goal

Rewire the NN branches of `Trainer.run()` onto the v3.0 `NNOrchestrator` surface.
The `Trainer` is a thin dispatcher: for an NN `RUN_TYPE` it constructs the orchestrator
through the pair-scoped `NNOrchestrator.from_trainer(pair, self)` factory and calls
`train()` / `run_inference()` — nothing more. All architecture, grouping, timeframe and
target knowledge now lives in `configs/nn_spec.yaml` (`NNModelSpec`), so `Trainer` stops
threading `feature_cols`, `checkpoint_dir`, `tfs`, or any `NN_CLS/NN_TGT/NN_TYPE` env into
the orchestrator. `simulate_nn` is renamed to `infer_nn` (alias retained), and the legacy
`group_nn` RUN_TYPE plus the `NNOrchestrator.group(class_type)` call are deleted.

## Context

<MIGRATION>

**From (current `trainer.py`, lines 60-90 + 230-290):**
- Dispatch table maps `"train_nn" → _run_train_nn` and `"simulate_nn" → _run_simulate_nn`.
- Both handlers build the orchestrator the old way:
  ```python
  nn_cfg = load_nn_config(self.config_path + "indicators_config.yaml")
  orch = NNOrchestrator(checkpoint_dir=nn_cfg["checkpoint_dir"],
                        feature_cols=nn_cfg["feature_cols"])
  ```
- `_run_train_nn` calls `orch.train(df, data_attributes, tfs, epoch_callback=...)` and the
  `epoch_callback(tf_str, epoch, metrics)` writes `{shared_folder()}/training_state.pkl`.
- `_run_simulate_nn` calls `orch.run_inference(df, data_attributes, tfs)` and writes the
  result to `_nn_output_path()` via a `.tmp` + `os.rename` atomic swap.

**To (target — `nn-orchestrator-class.md` §"Training-Module Wiring"):**
- Construct via `NNOrchestrator.from_trainer(pair, self)`, which reads `configs/nn_spec.yaml`
  (`NNModelSpec.from_yaml(nn_spec_path(pair))`), derives artefact roots
  (`nn_artefact_root(pair)` = `{NN_ARTEFACT_ROOT}/{DATA_ROOT}/{pair}/nn`), and injects
  `num_workers = trainer.available_threads()`.
- `nn_train → from_trainer(pair, self).train(df, data_attributes)` — no `tfs`, no per-TF loop.
- `infer_nn` (alias `simulate_nn`) `→ from_trainer(pair, self).run_inference(dataset, checkpoint_id)`
  → writes `{dataset}/df_with_nn.pkl` (additive `nn_res_*` columns only; never mutates
  `df_with_indicators.pkl`; absence-safe — no checkpoint returns `None` and writes nothing).
- `load_nn_config` `feature_cols`/`checkpoint_dir` path is **superseded** and no longer read
  by the NN branches.
- `group_nn` RUN_TYPE and `NNOrchestrator.group(...)` are **removed**.

</MIGRATION>

## Files

- Modify: `training/trainer.py` — dispatch table + NN handlers + env reads.
- Modify: `docker-compose.yml` — NN env vars and service `command` (coordinate with Task 01).

## Interface

### RUN_TYPE → handler dispatch (verbatim from `nn-orchestrator-class.md` §"RUN_TYPE dispatch")

| `RUN_TYPE` | Dispatch |
|------------|----------|
| `nn_train` | `NNOrchestrator.from_trainer(pair, self).train(df, data_attributes)` — `df` + `DataAttributes` loaded by `Trainer`. |
| `infer_nn` (alias `simulate_nn`) | `NNOrchestrator.from_trainer(pair, self).run_inference(dataset=NN_INFER_DATASET, checkpoint_id=NN_INFER_CHECKPOINT)` → writes `{dataset}/df_with_nn.pkl`. |

The dispatch table in `Trainer.run()` maps `"nn_train" → self._run_train_nn` and both
`"infer_nn"` and `"simulate_nn"` (legacy alias) → `self._run_infer_nn`. Unknown `RUN_TYPE`
raises `ValueError`. The `"group_nn"` entry and its handler are removed.

### `_run_train_nn(self) -> None`

Ordered steps:
1. Lazy-import `pandas`, `DataAttributes`, `NNOrchestrator`, and the path helpers
   (`wide_df_path`, `data_attributes_path`, `shared_folder`). Drop the `CANDLES as tfs` and
   `load_nn_config` imports.
2. Load `df = pd.read_pickle(wide_df_path())` and
   `data_attributes = DataAttributes.load(data_attributes_path())`.
3. Build `orch = NNOrchestrator.from_trainer(self.pair, self)`.
4. Define `epoch_callback` and pickle progress to `{shared_folder()}/training_state.pkl`
   (see Key Constraints for the adapted signature).
5. `train_metrics = orch.train(df, data_attributes, epoch_callback=epoch_callback)`.
6. `self.metadata["train_nn"] = train_metrics or {}` (now a `{group_key: metrics}` dict).

### `_run_infer_nn(self) -> None`  (replaces `_run_simulate_nn`)

Ordered steps:
1. Lazy-import `NNOrchestrator` and `root_folder` (default-dataset helper). No `df`,
   `DataAttributes`, `tfs`, or `load_nn_config` reads — `run_inference` loads
   `df_with_indicators.pkl` from the target dataset itself.
2. `dataset = os.getenv("NN_INFER_DATASET", root_folder(self.pair))`.
3. `checkpoint_id = os.getenv("NN_INFER_CHECKPOINT", "best")`.
4. `orch = NNOrchestrator.from_trainer(self.pair, self)`.
5. `result = orch.run_inference(dataset=dataset, checkpoint_id=checkpoint_id)`.
   - The orchestrator writes `{dataset}/df_with_nn.pkl` atomically; absence-safe (`None`).
6. Record a light summary in `self.metadata["infer_nn"]` (guard `result is None`).

### Env var table (`Trainer` supplies / reads for NN)

| Env Var | Use |
|---------|-----|
| `NN_DATA_ROOT` | Input data root — feeds `from_trainer` artefact-path derivation. |
| `NN_ARTEFACT_ROOT` | Artefact root — feeds `from_trainer` (`{NN_ARTEFACT_ROOT}/{DATA_ROOT}/{pair}/nn`). |
| `NN_INFER_DATASET` | `run_inference` target dataset (default `root_folder(pair)`). |
| `NN_INFER_CHECKPOINT` | `run_inference` checkpoint id (default `"best"`). |
| ~~`NN_CLS` / `NN_TGT` / `NN_TYPE`~~ | **Removed** — architecture/grouping/targets live in `configs/nn_spec.yaml`. |
| ~~`SHUFFLE_GROUPED_NN_DATA`~~ | **Removed** (legacy grouping retired). |

## Key Constraints

- `run_inference` output is written atomically to `{dataset}/df_with_nn.pkl`; it must
  **never** mutate `df_with_indicators.pkl`. The atomic-write responsibility moves into the
  orchestrator — `Trainer` no longer does the `.tmp`/`os.rename` itself.
- `from_trainer` reads `configs/nn_spec.yaml` (`NNModelSpec`) + artefact roots;
  `num_workers = trainer.available_threads()`. `Trainer` passes no `feature_cols`,
  `checkpoint_dir`, or `tfs`.
- `epoch_callback` adapts to the new `train()` shape — group-keyed, not per-TF. Use the
  orchestrator's documented callback signature (group/epoch/metrics) and persist
  `{"phase": "nn_train", ...}` to `training_state.pkl`; do **not** assume a `tf_str` arg.
  `train()` returns `{group_key: metrics}`.
- `group_nn` RUN_TYPE removed; no `NNOrchestrator.group(class_type)` reference remains.
- `NN_CLS` / `NN_TGT` / `NN_TYPE` (and `SHUFFLE_GROUPED_NN_DATA`) env reads removed.
- `load_nn_config` `feature_cols`/`checkpoint_dir` usage removed from the NN branches.

> **Spec-doc follow-up (flag, do not fix here):** `trainer-class.md` §4.1 still shows the
> `group_nn → NNOrchestrator(...).group(NN_POINT_CLASS_BIG)` branch, and
> `training-module.md` §2/§4.3/§5.D still reference `group_nn` / `NNOrchestrator.group(...)`.
> These are obsolete under NNOrchestrator v3.0 and must be dropped in a separate spec edit.

## Verification

```bash
docker compose run --rm nn-train       # RUN_TYPE=nn_train end-to-end on a tiny config → checkpoints + tracking written
docker compose run --rm simulate-nn    # RUN_TYPE=infer_nn → {dataset}/df_with_nn.pkl with nn_res_* columns
```

Additional checks:
- `grep -n "group_nn\|NN_CLS\|NN_TGT\|NN_TYPE\|load_nn_config" training/trainer.py` → no matches in NN branches.
- `infer_nn` against a dataset with no checkpoint exits cleanly, writes no `df_with_nn.pkl`.
- `df_with_indicators.pkl` mtime unchanged after `infer_nn`.

## Commit

`refactor(training): wire NNOrchestrator.from_trainer; rename simulate_nn→infer_nn; drop group_nn`
