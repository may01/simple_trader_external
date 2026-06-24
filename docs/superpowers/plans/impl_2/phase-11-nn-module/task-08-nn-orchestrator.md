# Task 08: NNOrchestrator (Grouping Train + Batch Inference)

**Phase:** 11 — NN Module  
**Depends on:** Task 04 (NNDataset), Task 05 (NNModel), Task 06 (CheckpointManager)  
**Produces:** reworked `nn/nn_orchestrator.py` (+ rewritten tests)

---

## Goal

Rework `NNOrchestrator` into the execution-level coordinator described in the canonical
NN-module spec ([`training-coordinator-class.md` §1](../../../specs/supporting-systems/nn-module/training-coordinator-class.md)):
the per-TF `NN`/`{tf}_nn_prob_*` design is replaced by a **dataset-built, grouping-partitioned**
coordinator where each model ingests **multi-timeframe** input and emits **timeframe-agnostic**
`nn_res_*` output. Two modes, both called from `Trainer`:

- `train()` — build an `NNDataset` once over all rows, partition rows into groups per `spec.grouping`,
  train one `NNModel` per group, persist each via `CheckpointManager`.
- `run_inference()` — load the best checkpoint per group, build a multi-TF feature matrix from **any**
  target `df`, normalise via the checkpoint's **bundled** training manifest (leakage guard), route each
  row to its group's model, and return a NN-columns-only DataFrame indexed by the input index.

Add the `pair`-scoped `from_trainer()` factory so `Trainer` constructs the orchestrator without knowing
`spec_hash` or artefact roots up front. Initial implementation uses `grouping=single` (one model over
all rows); class/regime grouping (one model per partition + inference routing) is the configurable
extension via `spec.grouping`.

---

## Context

MIGRATION from current implementation:

- **Construction:** `__init__(checkpoint_dir, feature_cols)` → `__init__(checkpoint_dir, dataset_dir, base_spec)`.
  Feature columns are no longer passed in; they come from the `NNModelSpec` / `NNDataset` and from each
  checkpoint's bundled `feature_cols`. New `dataset_dir` (materialised `NNDataset` tensors) and `base_spec`
  (default `NNModelSpec`, the loop may override fields). New `from_trainer()` classmethod builds paths from
  the pair-scoped artefact root.
- **Input:** was per-TF (a separate model and feature slice per `tf`, `tfs: list[int]` arg). Now a single
  `NNDataset` is built **once** over all rows with **multi-TF input** (per `spec.timeframes`); rows are
  partitioned by `spec.grouping`, one `NNModel` per group keyed by group string. The `tfs` argument is gone.
- **Targets:** was `{tf}_target_direction` (3-class direction per TF). Now the dataset/spec define targets;
  output is sized to `spec.targets` (multi-target, multi-horizon possible).
- **Output:** was `{tf}_nn_prob_up/_neutral/_down` (TF-prefixed). Now **timeframe-agnostic**
  `nn_res_{target}_prob_*`, `nn_res_{target}`, and multi-horizon `_h{hk}` variants. All groups write the
  **same** `nn_res_*` columns; only the producing model differs per row.
- **Normalisation:** was recomputed from the inference data via `data_attributes.get_stats()`. Now inference
  normalises via the **manifest bundled in the checkpoint** (training stats + ordered `feature_cols`),
  never stats recomputed from the inference dataset (leakage guard). No grouped-pickle / `data_attributes`
  dependency for inference stats.
- **Output sink:** `run_inference` still returns a NN-columns-only DataFrame indexed by `df.index`; the input
  `df` is never mutated. The caller (`Trainer._run_infer_nn`) saves it as `{dataset}/df_with_nn.pkl`
  (consumed downstream by trainer task 11, left-joined at load by `SimulationData`/`FullData`/`LiveData`).
- **Trainer wiring:** `Trainer._run_train_nn` → `from_trainer(pair, self).train(df, data_attributes)`;
  `Trainer._run_infer_nn` (alias `simulate_nn`) → `from_trainer(pair, self).run_inference(...)`. Absence-safe:
  no checkpoint → inference returns an empty/`None` result and writes nothing.

This task reworks `train()` / `run_inference()` only. `TrainingLoop` + `NNStrategist`
(canonical spec §2–§3, the agentic search around `train()`) are a separate task — `train()` must stay
usable standalone for a single-shot train without the LLM loop.

---

## Files

- Modify: `nn/nn_orchestrator.py`
- Modify: `tests/unit/nn/test_nn_orchestrator.py`

---

## Interface

```python
class NNOrchestrator:
    """Execution-level coordinator for NN training and batch inference.

    Each model ingests multi-timeframe features (per spec.timeframes) and emits
    timeframe-agnostic nn_res_* output. Rows are partitioned into groups per
    spec.grouping; one NNModel per group (a single group if grouping=single),
    with inference routing each row to its group's model.

    Attributes:
        checkpoint_dir: Where CheckpointManager stores weights per group.
        dataset_dir: Where NNDataset materialised tensors live.
        base_spec: Default NNModelSpec (the TrainingLoop may override fields).
        num_workers: From NUM_WORKERS env (default 4).
        trained_models: dict[str, NNModel] keyed by group string.
    """

    def __init__(self, checkpoint_dir: str, dataset_dir: str, base_spec: NNModelSpec) -> None:
        """Init paths + base_spec; read num_workers from NUM_WORKERS env (default 4);
        start trained_models empty."""

    @classmethod
    def from_trainer(cls, pair: str, trainer: "Trainer") -> "NNOrchestrator":
        """Pair-scoped factory. Loads base_spec = NNModelSpec.from_yaml(configs/nn_spec.yaml);
        artefact_root = nn_artefact_root(pair); builds
            checkpoint_dir = f"{artefact_root}/checkpoints/{base_spec.spec_hash}",
            dataset_dir    = f"{artefact_root}/datasets",
        and passes num_workers = trainer.available_threads()."""

    def train(
        self,
        df: pd.DataFrame,
        data_attributes: DataAttributes,
        spec: NNModelSpec | None = None,
        epoch_callback: Callable[[str, int, dict], None] | None = None,
    ) -> dict:
        """Resolve spec (spec or base_spec). Build the NNDataset ONCE over all rows
        (multi-TF input per spec.timeframes), cached under dataset_dir. Partition rows
        into groups per spec.grouping (one group if mode='single'; one per class/regime
        if mode='by_indicator'). For each group:
          - NNModel(spec).train(dataset.group(group_key), epoch_callback=...)
          - CheckpointManager.save(model, metrics, manifest=..., feature_cols=...)
          - store in trained_models[group_key]
        Returns {group_key: final_metrics}. Called by Trainer._run_train_nn() for a
        single-shot train; the full search is driven by TrainingLoop."""

    def run_inference(
        self,
        df: pd.DataFrame,
        data_attributes: DataAttributes,
        spec: NNModelSpec | None = None,
    ) -> pd.DataFrame:
        """Load the best checkpoint per group via CheckpointManager.load_best() (each
        checkpoint embeds its own spec + normalisation manifest + ordered feature_cols).
        Build the multi-TF feature matrix from the target df (any dataset); normalise via
        the manifest bundled in the checkpoint (training stats), NEVER stats recomputed
        from the inference dataset (leakage guard). Route each row to its group's model by
        the grouping condition (single group → all rows to the one model), then
        model.run_batch(X) → output sized to the spec's targets. Append only the
        timeframe-agnostic NN output columns (nn_res_{target}_prob_*, nn_res_{target},
        multi-horizon _h{hk} variants) to a FRESH DataFrame indexed by df.index. All groups
        write the SAME nn_res_* columns; only the producing model differs per row.
        Returns that NN-columns-only DataFrame. Input df is NOT modified. Absence-safe:
        no checkpoint for a group → that group contributes no rows; no checkpoints at all →
        empty result (caller writes nothing)."""
```

Properties / contracts:
- **Multi-TF input:** features span all `spec.timeframes`, built once via `NNDataset` (train) / a feature
  matrix derived from the checkpoint's `feature_cols` (inference). No per-TF model split.
- **TF-agnostic output:** `nn_res_*` column names carry no `{tf}` prefix; identical across groups.
- **Row routing:** each row's group is decided by the grouping condition (`single` → one group;
  `by_indicator` → partition + per-group model), and only that group's model produces its `nn_res_*` values.
- **Group keying:** `trained_models` and `CheckpointManager` instances are keyed by **group string**
  (one group if `grouping=single`).

---

## Key Constraints

- Build `NNDataset` **once** over all rows; partition by `spec.grouping`; one model per group
  (`grouping=single` → exactly one model over all rows).
- Inference normalises via the checkpoint's **bundled manifest** (training stats + `feature_cols`), never
  from the inference data (leakage guard). No `data_attributes`-recomputed stats and no grouped-pickle
  dependency on the inference path.
- `run_inference` returns a **NN-columns-only** DataFrame indexed by the input index; the input `df` is
  **not** modified (fresh DataFrame, `df.index`).
- All groups write the **same** `nn_res_*` columns; only the producing model differs per row.
- Output columns are sized/named from the **spec's targets** (multi-target, multi-horizon `_h{hk}`),
  read from each checkpoint's embedded spec (embedded spec wins on mismatch).
- `train()` stays usable standalone (single-shot, no `TrainingLoop`); group keys are strings so the
  `trained_models` dict serialises safely.
- Absence-safe inference: missing best checkpoint for a group → no contribution; no checkpoints at all →
  empty result, nothing written.

### Tests to change (from existing 12)

- **`__init__` tests:** replace `feature_cols=` construction with `(checkpoint_dir, dataset_dir, base_spec)`;
  keep the `NUM_WORKERS` env default-4 / override cases; assert `trained_models == {}` and `base_spec` stored.
- **Add `from_trainer` test:** mock `Trainer.available_threads()` + `NNModelSpec.from_yaml` + `nn_artefact_root`,
  assert `checkpoint_dir`/`dataset_dir` are built from `spec_hash` and the artefact root, and `num_workers`
  comes from `available_threads()`.
- **`train` tests:** replace per-TF (`tfs=[15, 60]`, `{tf}_target_direction`) expectations with grouping —
  assert `NNDataset` is built **once**, rows partitioned by `spec.grouping`, return keyed by **group string**
  (single group → one key), one `NNModel(spec).train(dataset.group(...))` per group, `CheckpointManager.save`
  called with a `manifest=`; keep an `epoch_callback` wiring assertion.
- **`run_inference` tests:** assert output columns are **only** the TF-agnostic `nn_res_*` set (no `{tf}_nn_prob_*`),
  index equals `df.index`, input `df` unchanged, normalisation uses the **bundled manifest** (not
  `data_attributes`), and `load_best()` returning `None` (no checkpoint) yields an empty/absence-safe result.
- Drop the `{tf}_nn_prob_up/_neutral/_down` column assertions and the per-TF `is_closed`/`get_stats`
  inference-normalisation assertions entirely.

---

## Verification

```bash
docker compose run --rm nn-train python3 -c "
from nn.nn_orchestrator import NNOrchestrator
# build a single-group (grouping=single) orchestrator over a small df,
# train() then run_inference() on the same df, then assert:
#   - run_inference output contains ONLY nn_res_* columns (no {tf}_nn_prob_*),
#   - its index equals the input df.index,
#   - the input df was not mutated.
# ... (construct base_spec via NNModelSpec.from_yaml; df from a tiny fixture) ...
res = orch.run_inference(df, data_attributes)
assert all(c.startswith('nn_res_') for c in res.columns), res.columns.tolist()
assert res.index.equals(df.index)
print('OK')
"
docker compose run --rm nn-train python3 -m pytest tests/unit/nn/test_nn_orchestrator.py -q
```

---

## Commit

`refactor(nn): NNOrchestrator grouping train + tf-agnostic batch inference`
