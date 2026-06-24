# NNOrchestrator, TrainingLoop & NNStrategist Specification

**File:** `nn/nn_orchestrator.py`, `nn/training_loop.py`, `nn/nn_strategist.py`
**Purpose:** Coordinate NN training and inference. `NNOrchestrator` drives per-group training, batch inference, and row routing (a model takes multi-TF input, emits timeframe-agnostic `nn_res_*` output). `TrainingLoop` runs the **hybrid agentic improvement loop** (Optuna search steered by an LLM `NNStrategist`), validating and promoting models.

---

## 1. NNOrchestrator

The execution-level coordinator. Two modes, both called from `Trainer`.

### Constructor

#### `__init__(checkpoint_dir, dataset_dir, base_spec)`
- `checkpoint_dir` — where `CheckpointManager` stores weights per group (class/regime; one group if `grouping=single`).
- `dataset_dir` — where `NNDataset` materialised tensors live.
- `base_spec: NNModelSpec` — the default model definition (loop may override fields).
- `num_workers` — from `NUM_WORKERS` env (default 4).
- `trained_models: dict[str, NNModel]` — keyed by group string.

### `train(df, data_attributes, spec=None, epoch_callback=None) -> dict`
- Resolves the spec (`spec or base_spec`).
- Builds the `NNDataset` once over all rows (multi-TF input per `spec.timeframes`), cached.
- Partitions rows into groups per `spec.grouping` (one group if `mode="single"`; one per class/regime if `mode="by_indicator"`).
- For each group:
  - `NNModel(spec).train(dataset.group(group_key), epoch_callback=…)`.
  - Save via `CheckpointManager`; store in `trained_models`.
- Returns `{group_key: final_metrics}`. Called by `Trainer._run_train_nn()` — for a single-shot train. The full search is driven by `TrainingLoop` (below).

### `run_inference(df, data_attributes, spec=None) -> pd.DataFrame`
- Loads the best checkpoint per group via `CheckpointManager.load_best()` (each checkpoint embeds its own spec).
- Builds the multi-TF feature matrix from the **target** `df` (any dataset); normalises via the **manifest bundled in the checkpoint** (training stats + `feature_cols`), never stats recomputed from the inference dataset (leakage guard). No grouped-pickle dependency.
- **Routes each row to its group's model** by the grouping condition (single group → all rows to the one model), then `model.run_batch(X)` → output sized to the spec's targets.
- Appends only the **timeframe-agnostic** NN output columns (`nn_res_{target}_prob_*`, `nn_res_{target}`, multi-horizon `_h{hk}` variants) to a fresh DataFrame indexed by `df.index`. All groups write the same `nn_res_*` columns; only the producing model differs per row.
- Returns that NN-columns-only DataFrame. Caller (`NNOrchestrator.run_inference` / `Trainer._run_infer_nn`) saves `{dataset}/df_with_nn.pkl`. Input `df` is not modified.

---

## 2. TrainingLoop (item 4 — agentic improvement loop)

`TrainingLoop` turns training from a single run into a **search for a better model**, combining numeric optimisation with LLM-level reasoning.

### Constructor

#### `__init__(orchestrator, tracker, strategist, search_config)`
- `orchestrator: NNOrchestrator`
- `tracker: ExperimentTracker` (records + promotion gate; see `result-aggregator-class.md`)
- `strategist: NNStrategist` (LLM steering)
- `search_config` — round budget, trials-per-round, Optuna sampler/pruner, time/compute caps.

### Study identity (`study_name`)

`study_name` keys the whole `tracking/{study_name}/` namespace (`ExperimentTracker.__init__`, see `result-aggregator-class.md`; layout in `nn-infrastructure.md`). Unlike its sibling namespaces it is **not content-addressed** — `dataset_hash` and `spec_hash` are derived from content, but `study_name` is a caller-chosen label for *one search run*. Ownership and rules:

- **Owner:** `Trainer._run_train_nn()` resolves `study_name` and constructs the `ExperimentTracker` with it, then passes the tracker into `TrainingLoop`. `TrainingLoop` never derives or mutates it — it receives an already-named tracker.
- **Source / default:** taken from training config / CLI (`--study <name>`). When omitted, default to `"{PAIR}_{base_spec.spec_hash[:8]}"` — pair-scoped (matches the `{DATA_ROOT}/{PAIR}/` artefact scope) and stable across restarts of the same base spec, so a re-run resumes rather than forks by accident.
- **Resume semantics:** reusing an existing `study_name` **resumes** that study — the loop reads the existing SQLite index + `best.json` as its starting history/incumbent (`nn-infrastructure.md` §5 "Tracking persistence"). A fresh search requires a new name. This is the only switch between resume and fresh, so it is a deliberate caller decision, never auto-generated per-process (an auto-timestamp would silently fork history every run).
- **Validation:** filesystem-safe slug (no path separators); rejected early by `Trainer` before the tracker touches disk.

### `run(df, data_attributes) -> RunResult`

```
for round in range(max_rounds):
    proposal = strategist.propose(history=tracker.summary())
        # → indicator set, timeframe set, target set, search-space bounds, rationale
    study = optuna.create_study(direction="maximize",
                                sampler=TPESampler, pruner=MedianPruner)
    for trial in range(trials_per_round):
        spec = build_spec(base_spec, proposal, optuna_suggestions(trial))
        metrics = orchestrator.train(df, data_attributes, spec,
                                     epoch_callback=optuna_prune_cb)
        holdout = evaluate_on_holdout(spec, df, data_attributes)
        tracker.record(spec, metrics, holdout, round)
        if tracker.is_improvement(holdout):       # promotion gate
            checkpoint_manager.save(model, holdout, promote=True)
    decision = strategist.review(tracker.round_summary(round))
        # → continue | narrow | broaden | change_targets | stop
    if decision == "stop": break
return tracker.best()
```

**Division of labour:**

| Concern | Owner |
|---------|-------|
| Numeric hyperparameter/architecture sampling, pruning | Optuna |
| Which indicators / timeframes / targets to explore, when to stop, why | `NNStrategist` (LLM) |
| Train one concrete spec | `NNModel` via `NNOrchestrator` |
| Record trials, hold out, decide promotion | `ExperimentTracker` |

Optuna explores *within* a space; the strategist *moves* the space. This keeps the search efficient (Optuna) while letting higher-level structural decisions (drop a noisy indicator, switch to a longer horizon, add a regression head) be reasoned about explicitly and logged.

---

## 3. NNStrategist (LLM steering)

A bounded LLM agent that reasons over experiment history and proposes the next experiment. **It only emits structured proposals — it never trains or touches weights.**

### `propose(history: dict) -> Proposal`
- Input: tracker summary (best metrics so far, per-indicator/target performance deltas, recent trial outcomes).
- Output (validated schema):
  ```python
  @dataclass
  class Proposal:
      indicators: list[str]
      timeframes: list[int]
      targets: list[TargetSpec]
      search_space: dict          # bounds for Optuna: lr range, depth range, units, dropout
      rationale: str              # why this scope — logged with the round
  ```
- **Investigation log (short form):** before returning, `propose` emits one concise, human-readable line via `logs.log()` summarising *what it investigated and what it decided* — for the user to follow the search at a glance, distinct from the verbose reproducibility record (prompt + full proposal, see §3 Guardrails). One line, no JSON dump. Shape:
  ```
  [NNStrategist] round={r}: best={metric}={value:.4f} | signals: <top driver / weakest indicator from history> → propose {n_ind} ind, tf={timeframes}, targets=[…]; space lr={lo}-{hi}, depth={lo}-{hi} | why: {rationale[:120]}
  ```
  - Sourced only from the inputs `propose` already has (the tracker `history` summary + the `Proposal` it is about to return) — no extra computation, no model/weight access.
  - Truncate `rationale` to keep the line readable; the full rationale stays in the `Proposal` and the reproducibility log.
  - On the fallback path (schema-rejected proposal → previous proposal reused, see Guardrails), log `[NNStrategist] round={r}: proposal rejected ({reason}); reusing previous scope` so the user sees the search did not advance.

### `review(round_summary: dict) -> str`
- Returns one of `continue | narrow | broaden | change_targets | stop`, plus a rationale.

### Guardrails
- Proposals are schema-validated; any field outside allowed indicator/timeframe/target vocab is rejected and the round falls back to the previous proposal.
- Search-space bounds are clamped to `search_config` limits (the LLM cannot request unbounded LR/depth).
- Per-run caps: max rounds, max trials, wall-clock and compute budget; the loop stops at the first cap reached regardless of strategist output.
- The strategist call is optional — with it disabled, `TrainingLoop` degrades to a pure Optuna search over `base_spec`.
- Model/provider for the strategist follows project LLM conventions; calls are logged (prompt, proposal, rationale) for reproducibility.

---

## 4. State & Error Handling

- A trial that raises (bad spec, OOM) is recorded as failed in the tracker and pruned; the loop continues.
- GPU OOM → retry once on CPU (per `nn-infrastructure.md` device policy) before marking failed.
- If no trial beats the incumbent across a full round, the incumbent best is retained; the strategist is told so it can broaden.
- All randomness seeded (`spec.seed`, Optuna seed) for reproducible rounds.

---

## 5. Notes

- `NNOrchestrator.train()` remains usable standalone (single-shot, no search) so `Trainer._run_train_nn()` works without the LLM loop.
- The loop's terminal artefact is the promoted best checkpoint per group plus the tracker's full history.
- Each model ingests multi-timeframe features and emits timeframe-agnostic `nn_res_*` outputs. Initial implementation uses `grouping=single` (one model over all rows); class/regime grouping (one model per partition, with inference routing) is the configurable extension via `spec.grouping`.
