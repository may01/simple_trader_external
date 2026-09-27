# NNOrchestrator — Training-Module Pointer

**Version:** 3.0 — pointer only
**Class:** `NNOrchestrator` · **File:** `nn/nn_orchestrator.py`
**Canonical spec:** [`../nn-module/training-coordinator-class.md`](../nn-module/training-coordinator-class.md)

`NNOrchestrator` is **defined and owned by the NN Module**, not here. Its constructor, `train()`, `run_inference()`, grouping, and row routing live in the canonical spec above; supporting contracts in [`nnmodel-class.md`](../nn-module/nnmodel-class.md), [`datapoint-generator-class.md`](../nn-module/datapoint-generator-class.md) (`NNDataset`), [`checkpoint-manager-class.md`](../nn-module/checkpoint-manager-class.md), and [`nnpredictor-class.md`](../nn-module/nnpredictor-class.md) (batch-inference path). This file records **only** how the Training Module wires into it. It defines no behavior — where it appears to, the canonical spec wins.

> v3.0 removed the legacy `group()` + `nn_group_*.pkl` pipeline and the per-tf `NN` class. Grouping is now internal to `train()` via `spec.grouping` + `NNDataset`. The old standalone version of this doc is superseded.

---

## Training-Module Wiring

`Trainer` constructs `NNOrchestrator` through a `pair`-scoped factory (it doesn't know `spec_hash` or artefact roots a priori):

```python
@classmethod
def from_trainer(cls, pair: str, trainer: "Trainer") -> "NNOrchestrator":
    base_spec     = NNModelSpec.from_yaml(nn_spec_path(pair))   # configs/nn_spec.yaml
    artefact_root = nn_artefact_root(pair)                      # {NN_ARTEFACT_ROOT}/{DATA_ROOT}/{pair}/nn
    return cls(
        checkpoint_dir = f"{artefact_root}/checkpoints/{base_spec.spec_hash}",
        dataset_dir    = f"{artefact_root}/datasets",
        base_spec      = base_spec,
        num_workers    = trainer.available_threads(),
    )
```

Artefact layout: [`../nn-module/nn-infrastructure.md`](../nn-module/nn-infrastructure.md) §"Artefact layout".

### RUN_TYPE dispatch

| `RUN_TYPE` | Dispatch |
|------------|----------|
| `nn_train` | `NNOrchestrator.from_trainer(pair, self).train(df, data_attributes)` — `df` + `DataAttributes` loaded by `Trainer`. |
| `infer_nn` (alias `simulate_nn`) | `NNOrchestrator.from_trainer(pair, self).run_inference_dataset(dataset_dir=NN_INFER_DATASET, checkpoint_id=NN_INFER_CHECKPOINT)` → writes `{dataset_dir}/df_with_nn.pkl`. |

`infer_nn` reads `df_with_indicators.pkl` from any target dataset and writes an additive `df_with_nn.pkl` (`nn_res_*` only); it never mutates `df_with_indicators.pkl`. Absence-safe: no checkpoint → returns `None`, writes nothing. Consumers (`SimulationData`/`FullData`/`LiveData`) left-join `df_with_nn.pkl` at load.

### Config the Training Module supplies

| Env Var | Use |
|---------|-----|
| `NN_DATA_ROOT` / `NN_ARTEFACT_ROOT` | Input root / artefact root (paths in factory). |
| `NUM_WORKERS` | Injected as `trainer.available_threads()`. |
| `NN_INFER_DATASET` / `NN_INFER_CHECKPOINT` | `run_inference` target + checkpoint. |

Architecture/grouping/timeframes/targets live in `configs/nn_spec.yaml` (`NNModelSpec`), not env. Legacy `NN_CLS` / `NN_TGT` / `NN_TYPE` / `SHUFFLE_GROUPED_NN_DATA` retired.

---

## Open Follow-Up (other files)

`trainer-class.md` and `training-module.md` have been updated to match v3.0 (Phase-11 rewrite). Other spec files outside the training-module directory may still carry stale `group_nn`/`NN_CLS`/`run_inference(dataset=` references — flagged as a follow-up cleanup.
