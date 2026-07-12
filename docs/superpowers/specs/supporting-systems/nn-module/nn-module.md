# NN Module Specification

**Module:** Neural Network (NN)
**Files:** `nn/nn_model.py`, `nn/nn_dataset.py`, `nn/checkpoint_manager.py`, `nn/nn_orchestrator.py`, `nn/training_loop.py`, `nn/nn_strategist.py`, `nn/experiment_tracker.py`
**Purpose:** Build, train, and deploy parametrised PyTorch neural networks that predict future price behaviour for the simple-trader bot. NN outputs are merged into the indicator DataFrame as ordinary columns and consumed by strategies — the NN module does not gate signals directly.

---

## 1. Overview

The NN Module provides deep-learning capabilities for the simple-trader bot using **PyTorch**. It builds, trains, and runs inference on neural networks that learn from normalised multi-timeframe indicator features and emit per-candle predictions (direction class, regression deltas, or multi-horizon variants).

The module is organised around three ideas:

1. **Fully parametrised models.** A model is defined entirely by a declarative `NNModelSpec` — data grouping, network depth, history window, indicators, timeframes, targets, and learning parameters. No architecture is hardcoded. Changing a model means changing its spec.

2. **A hybrid agentic training loop.** Optuna runs the numeric hyperparameter/architecture search; an LLM strategist steers the search space, selects indicator/timeframe/target sets, reads each trial's metrics, and proposes the next experiment with a written rationale. Every candidate is validated against a holdout set and only promoted if it beats the current best by a margin.

3. **Batch-only inference as indicators.** Trained models run batch inference over `df_with_indicators` during data preparation, producing `df_with_nn.pkl`. Those columns are merged back into `df_with_indicators` on the next prepare run and become available to strategies as regular indicator columns. There is **no per-tick NN predictor in the live prediction stage** (see §6).

A model takes **multi-timeframe features as input** but its outputs are **timeframe-agnostic**: NN result columns are named `nn_res_*` (no `{tf}_` prefix). One model produces one set of `nn_res_*` columns regardless of how many timeframes feed it.

---

## 2. Module Boundaries

### Upstream Dependencies
- **Data layer:** `DataPreparer` produces `df_with_indicators.pkl` (normalised indicator features) and `DataAttributes` (per-column normalisation stats). NN inputs are derived from these.
- **NN feature step:** `nn_features` computes NN-specific engineered indicators (see §5 and the dataset spec) appended during preparation.
- **Training entry point:** `Trainer._run_train_nn()` invokes the training loop; `Trainer._run_infer_nn()` (alias `_run_simulate_nn`) invokes batch inference via `NNOrchestrator.run_inference(dataset, checkpoint_id)`, runnable on any dataset.
- **Environment configuration:** `NUM_WORKERS`, checkpoint/dataset/tracking directories, and GPU device selection via env vars; model definitions via `NNModelSpec` YAML.

### Downstream Consumers
- **DataPreparer:** merges `df_with_nn.pkl` columns into `df_with_indicators.pkl`.
- **Strategies / StrategyManager:** read `nn_res_*` columns (probabilities, regression deltas) as ordinary indicators via `data_point.get(...)`. No direct coupling to NN classes.
- **Backtest / Simulation:** consume the same merged columns; no separate NN call path.

### Key Interfaces Exposed
- **`NNModelSpec`** — declarative model definition (see `nnmodel-class.md`).
- **`NNModel(spec)`** — `build()`, `train()`, `run()`, `run_batch()`, `save_model()`, `load_model()`.
- **`NNDataset`** — modular tensor dataset + manifest (see `datapoint-generator-class.md`).
- **`CheckpointManager`** — versioned PyTorch weight persistence (see `checkpoint-manager-class.md`).
- **`NNOrchestrator`** — train one model per group (class/regime), route rows, run batch inference (see `training-coordinator-class.md`).
- **`TrainingLoop` + `NNStrategist`** — hybrid Optuna + LLM improvement loop (see `training-coordinator-class.md`).
- **`ExperimentTracker`** — trial records + promotion gate (see `result-aggregator-class.md`).

---

## 3. Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│   df_with_indicators.pkl  +  DataAttributes (norm stats)    │
│         (multi-timeframe candles, indicators)               │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  nn_features step                    │
        │  ├─ log-returns, z-scores            │
        │  ├─ ATR-normalised range, body/wick │
        │  ├─ indicator slopes, vol regime    │
        │  └─ session / cross-TF features     │
        └──────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  Build NNDataset (modular format)    │
        │  ├─ per-TF feature tensors           │
        │  ├─ multi-target tensor              │
        │  ├─ manifest.json (cols, stats,     │
        │  │  target encoding, spec hash)     │
        │  └─ cached for reuse across trials  │
        └──────────────────────────────────────┘
                           │
            ┌──────────────┴───────────────┐
            ▼                               ▼
┌──────────────────────────┐   ┌──────────────────────────────┐
│  Hybrid Training Loop    │   │  Batch Inference             │
│  (TrainingLoop)          │   │  (NNOrchestrator             │
│  ├─ Optuna search        │   │   .run_inference)            │
│  ├─ NNStrategist (LLM)  │   │  ├─ route rows to group model│
│  │  steers space + targets│  │  ├─ run_batch over df        │
│  ├─ train NNModel(spec) │   │  ├─ append nn_res_* cols     │
│  ├─ ExperimentTracker   │   │  └─ save df_with_nn.pkl      │
│  │  records + holdout    │   └──────────────┬───────────────┘
│  └─ promotion gate →     │                  │
│     best checkpoint      │                  ▼
└──────────────────────────┘   ┌──────────────────────────────┐
                               │  DataPreparer merges NN cols  │
                               │  into df_with_indicators.pkl  │
                               └──────────────┬───────────────┘
                                              ▼
                               ┌──────────────────────────────┐
                               │  Strategies read nn_res_*     │
                               │  as ordinary indicators       │
                               └──────────────────────────────┘
```

---

## 4. Execution Flow

### A. Training (`TrainingLoop.run`)

1. Build or load the `NNDataset` for the configured TFs/targets (cached by spec hash).
2. Initialise an Optuna study and the `NNStrategist`.
3. For each round:
   - `NNStrategist` proposes the experiment scope: indicator set, timeframe set, target set, and search-space bounds — with a written rationale.
   - Optuna samples concrete hyperparameters/architecture within that space, building an `NNModelSpec` per trial.
   - `NNModel(spec).train()` runs on train/validation split; intermediate epochs may be pruned by Optuna.
   - `ExperimentTracker` records the trial (spec hash, train/val/holdout metrics, delta vs best).
   - **Promotion gate:** if the trial beats the current best on the holdout set by the configured margin, save via `CheckpointManager` and update best.
   - `NNStrategist` reads the round's metrics and decides the next round (continue, narrow, broaden, change targets, or stop).
4. Return the best `NNModelSpec` + metrics per group.

### B. Batch Inference (`NNOrchestrator.run_inference`)

1. Load the best checkpoint per group via `CheckpointManager.load_best()` (one model if `grouping=single`; one per class/regime otherwise).
2. Build the multi-timeframe feature matrix from `df_with_indicators` using the spec's feature columns (closed-candle rows), normalised via the checkpoint's **bundled manifest stats** (train-split winsorised `{q01,q99,mean,std}`) — never recomputed from inference data (leakage guard). The legacy `DataAttributes.get_stats()` apply path was removed (DECISIONS-LOG D13).
3. Route each row to its group's model (by the grouping indicator condition), then `model.run_batch(X)` → output array sized to the spec's declared targets.
4. Append timeframe-agnostic output columns (`nn_res_{target}_prob_up/neutral/down`, `nn_res_{target}`, horizon variants) to a NN-columns-only DataFrame indexed by `df.index`. All groups write the same `nn_res_*` columns; only the producing model differs per row.
5. Return that DataFrame; the caller saves it as `df_with_nn.pkl`. Input `df` is not modified.

### C. Merge into Indicators (`DataPreparer.prepare`)

On the next prepare run, `df_with_nn.pkl` columns are merged into `df_with_indicators.pkl`, making NN outputs first-class indicator columns for strategies and backtests.

---

## 5. Key Components

| Component | Responsibility | Spec file |
|-----------|----------------|-----------|
| `NNModelSpec` + `NNModel` | Declarative model definition; build/train/infer in PyTorch | `nnmodel-class.md` |
| `NNDataset` | Modular tensor data format + manifest + NN feature engineering | `datapoint-generator-class.md` |
| `CheckpointManager` | Versioned PyTorch weight persistence + best tracking | `checkpoint-manager-class.md` |
| `NNOrchestrator` | Per-group training driver + batch inference + row routing | `training-coordinator-class.md` |
| `TrainingLoop` + `NNStrategist` | Hybrid Optuna + LLM improvement loop | `training-coordinator-class.md` |
| `ExperimentTracker` | Trial records, holdout validation, promotion gate | `result-aggregator-class.md` |
| Inference path notes | Removal of per-tick predictor; batch path | `nnpredictor-class.md` |
| NN training infrastructure | Dockerfile, compose service, GPU/CPU device | `nn-infrastructure.md` |

---

## 6. Inference Stage: No Per-Tick Predictor

Earlier designs ran a per-tick `NNPredictor` inside the live prediction stage, computing NN columns one candle at a time inside `LiveData.build_candles()`. **That coupling is removed.** Rationale:

- NN inference is computed in batch during data preparation/simulation and merged as indicator columns. Live and backtest paths then read identical, precomputed values — eliminating live/backtest skew.
- The prediction stage no longer imports or depends on any NN class. Removing the NN checkpoint removes the `nn_res_*` columns; strategies that reference them must tolerate their absence (treated as a normal missing indicator).
- The former `NNPredictor` per-tick responsibilities are retired; `nnpredictor-class.md` documents the removal and the batch-inference replacement.

---

## 7. Targets and Labelling

Targets are configurable per `NNModelSpec` (`targets: [...]`). **A model may declare multiple targets** — the output layer and combined loss are assembled from the declared list (multi-label / multi-head). Supported target families:

1. **Direction class (from profit labels)** — labels are **not** computed inside the NN module. They are read from the profit-label columns produced by the phase-13 profit-labels pipeline (`task-07-profit-labels-pipeline.md`): `{tf}_plong_n{n}_m{m}_x{x}` / `{tf}_pshort_…` and strict `{tf}_pslong_*` / `{tf}_psshort_*`. Each profit label is a binary outcome for a candidate entry (target `m×atr_ma` hit before stop `x×atr_ma` within `n` tf-candles; long enters at `1_low`, short at `1_high`). A direction `TargetSpec` references one profit-label spec by its `(tf, n, m, x, strict)` and derives the class:
   - `up` if the **long** label is profitable and the short is not,
   - `down` if the **short** label is profitable,
   - `neutral` if neither — encoded `{0=up, 1=neutral, 2=down}`, 3-class softmax head.

   Alternatively a TargetSpec may reference a **single** profit-label column directly as a binary head (`profitable` vs not, `kind="label"`, sigmoid). Because the source columns are `{tf}`-keyed but multiple specs/sides/strictness variants exist, **multiple direction targets can be declared per model** — each becomes its own head and its own `nn_res_{target}_*` output columns.

2. **Binary direction — single action vs. rest (`kind="direction_binary"`)** — a **2-class softmax** head emitting the probability of ONE action versus everything else: `(prob_long, prob_other)` or `(prob_short, prob_other)`. The `TargetSpec` carries `side: "long" | "short"` and reads **one** profit-label column — the long column for `side="long"`, the short column for `side="short"` — selected by `(label_tf, n, label_m, label_x, strict)`. The positive class is that column `== 1` (the action was profitable), `other` is `== 0`; encoded `{0=<side>, 1=other}`, width-2 softmax / cross-entropy. Output columns: `nn_res_{name}_prob_{side}` and `nn_res_{name}_prob_other`. Unlike the 3-class direction head (which couples long vs short into one decision), each binary head models one side independently — so a model may declare a `long` head and a `short` head side-by-side, or either alone. (It differs from `kind="label"` only in shape: a 2-value softmax where `prob_{side} + prob_other = 1`, matching the 3-class head's one-hot shape for downstream consumers, instead of a single sigmoid scalar.)

3. **Regression** — next-delta (e.g. close log-return over horizon `N`). Linear head, MSE/Huber loss. Computed by `NNDataset` from price (not a profit label).

4. **Multi-horizon** — the same target evaluated at several horizons in one model. A direction / direction_binary / regression target carries a `horizons: [h1, h2, …]` list; the dataset materialises one label per horizon (for direction/direction_binary, by selecting the matching profit-label spec with `n = hk`) and the model grows **one head per horizon**. Each horizon emits suffixed columns: `nn_res_{target}_h{hk}_prob_up/neutral/down` (direction), `nn_res_{target}_h{hk}_prob_{side}` / `_prob_other` (direction_binary), or `nn_res_{target}_h{hk}` (regression). This lets a single model predict, e.g., 1-candle and 2-candle direction jointly, sharing the trunk and learning cross-horizon structure, while strategies read each horizon independently.

This resolves the previously-unresolved labelling question (column naming, encoding, horizon, threshold) by sourcing direction labels from the profit-labels pipeline and making the rest spec-driven. **Default labelling:** a direction target from the primary profit-label spec at the strategy's primary horizon. Output columns are timeframe-agnostic (`nn_res_*`).

---

## 8. Architecture Decisions

- **Framework:** PyTorch. (Legacy Keras/TensorFlow references are obsolete.)
- **Search:** Optuna (Bayesian sampling + pruning).
- **Tracking:** dependency-free local store (JSON manifest + SQLite index). No MLflow.
- **GPU:** optional. Training auto-detects CUDA and falls back to CPU (see `nn-infrastructure.md`).
- **Timeframe-agnostic output:** a model ingests multi-timeframe features and emits one set of `nn_res_*` columns. Timeframe selection lives in the input (`spec.timeframes`/`feature_cols`), never in the output names.
- **Grouping ≠ per-timeframe.** Grouping partitions the *training rows* into classes/regimes by a condition on a timeframe-indicator column (e.g. a volatility or trend regime), training one model per class; an inference router assigns each row to its class's model. Initial implementation uses `grouping=single` (one model over all rows); regime/class grouping is the configurable extension. See `nnmodel-class.md` §2 and `training-coordinator-class.md`.

---

## 9. Potential Improvements

1. Richer regime/class grouping conditions (multi-indicator, learned partitions) beyond a single indicator threshold.
2. Ensembling across promoted checkpoints, weighted by holdout performance.
3. Feature-importance attribution feeding the `NNStrategist`'s indicator selection.
4. Online/incremental refinement between full loop runs.
5. Multi-objective Optuna (accuracy vs latency vs stability).
