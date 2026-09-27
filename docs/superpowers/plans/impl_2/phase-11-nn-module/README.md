# Phase 11 — NN Module: Migration Plan

**Status:** planning
**Spec source:** `docs/superpowers/specs/supporting-systems/nn-module/` + `docs/superpowers/specs/supporting-systems/training-module/` (branch `spec-nn-module-revision`)
**Scope:** Full — every class + infra (core batch pipeline, agentic training loop, GPU infra).

---

## 1. Why this phase is being rewritten

The current `nn/` implementation was built to the *original* phase-11 task series (task-01..04). That design is now superseded by the revised NN-module spec. The existing code is **already PyTorch** — this is **not** a framework swap. It is an **architectural expansion**: from a fixed per-timeframe MLP with per-tick live inference to a spec-driven, dataset-cached, grouping-routed, batch-inference-as-indicators subsystem with an agentic (Optuna + LLM) training loop and dedicated GPU infrastructure.

### Current implementation (built to old tasks — all DONE + tested)

| File | Class | Shape |
|------|-------|-------|
| `nn/nn_model.py` | `NNModel(input_size, hidden_size, num_classes)` | fixed 2-hidden-layer MLP; `train(X, y, …)`; `save_model`/`load_model` = state_dict only |
| `nn/nn_predictor.py` | `NNPredictor` | per-tick live inference; called from `LiveData.build_candles()` (`data.py:303`) |
| `nn/nn_orchestrator.py` | `NNOrchestrator(checkpoint_dir, feature_cols)` | per-TF train/infer; output `{tf}_nn_prob_*`; targets from `{tf}_target_direction` |
| `nn/checkpoint_manager.py` | `CheckpointManager(checkpoint_dir, model_name)` | best by `val_accuracy`; `load_best → bool` |
| `indicators/library/nn_features.py` | `NNRSINormField`, `NNCloseDiffATRField` | 2 engineered features |

### Target architecture (new spec)

| File | Class | Role |
|------|-------|------|
| `nn/device.py` | `resolve_device(pref)` | CUDA→CPU fallback, OOM retry |
| `nn/nn_model_spec.py` | `NNModelSpec`, `LayerSpec`, `GroupingSpec`, `TargetSpec` | declarative model definition; `spec_hash`, `from_yaml` |
| `nn/nn_model.py` | `NNModel(spec)` | builds network from spec; multi-TF input; multi-target/multi-horizon heads; checkpoint embeds spec + manifest |
| `nn/nn_dataset.py` | `NNDataset` | content-addressed tensor cache + manifest + time-ordered splits + grouping; reads profit-label targets |
| `nn/checkpoint_manager.py` | `CheckpointManager(checkpoint_dir, model_name, mode)` | bundles manifest + feature_cols; `save(…, promote)`; `load_best → dict\|None` |
| `nn/experiment_tracker.py` | `ExperimentTracker` | trial store (JSON + SQLite); holdout promotion gate |
| `nn/nn_orchestrator.py` | `NNOrchestrator(checkpoint_dir, dataset_dir, base_spec)` | `from_trainer`; dataset-built + grouping-partitioned train; grouping-routed `run_inference` → `df_with_nn.pkl`; timeframe-agnostic `nn_res_*` |
| `nn/nn_strategist.py` | `NNStrategist` | LLM steering: `propose(history)`, `review(round_summary)` |
| `nn/training_loop.py` | `TrainingLoop` | Optuna round loop wiring orchestrator + tracker + strategist |
| `indicators/library/nn_features.py` | engineered fields | expanded: logret, z-scores, range/ATR, body/wick, slopes, vol_regime, cyclical time, cross-TF |

**Removed entirely:** `NNPredictor` class, `nn/nn_predictor.py`, the `predictor.compute(point, tf)` call in `data.py:303`, all live-path NN imports, the `group_nn` RUN_TYPE + `prepare-nn-data` compose service, env vars `NN_CLS`/`NN_TGT`/`NN_TYPE`.

---

## 2. Cross-cutting contract changes

These constraints apply to every task and must hold at the end of the phase:

1. **Spec-driven, not hardcoded.** All architecture/grouping/timeframes/targets live in `configs/nn_spec.yaml` (`NNModelSpec`), never in env or code branches.
2. **Multi-TF input, timeframe-agnostic output.** A model ingests all `spec.timeframes`; output columns are `nn_res_*` with **no** `{tf}_` prefix. (Old `{tf}_nn_prob_*` naming is retired.)
3. **Targets are read, not computed.** Direction/label targets come from the profit-labels pipeline columns (`{tf}_plong_n{n}_m{m}_x{x}`, `{tf}_pshort_*`, strict `{tf}_pslong_*`/`{tf}_psshort_*`) already produced by `DataPreparer._compute_profit_labels()`. NN never re-classifies BUY/SELL/NONE.
4. **Batch inference only.** No per-tick predictor. `run_inference` produces `{dataset}/df_with_nn.pkl` (nn_res_* only) and **never mutates** `df_with_indicators.pkl`. Consumers (`SimulationData`/`FullData`/`LiveData`) **left-join** it at construction; absence is a no-op (missing-indicator semantics via `data_point.get(col, tf, default=…)`).
5. **No leakage.** Normalization stats computed on the train split only, bundled into the checkpoint manifest, and reused verbatim at inference (never recomputed from inference data). Splits are time-ordered.
6. **Self-contained checkpoints.** Each `.pt` carries `state_dict` + serialized `spec` + normalization `manifest` + `feature_cols` + `metrics`.
7. **GPU optional.** Auto-detect CUDA, fall back to CPU; CUDA OOM → one CPU retry before marking the trial failed.

---

## 3. Layer mapping & Docker entry points (Step 0 — authoritative)

The NN module sits primarily in the **Training pipeline** layer, with touch-points in Docker (0), Indicators / test-data-prep (3–4, feature columns), and Backtesting / Business-logic (5–6, consumer join). These compose commands are the ground truth; implementation must make them work.

```bash
# Build the dedicated CUDA NN image (separate from the always-on simple_trader image)
docker compose build nn-train

# Feature columns are produced by the standard data-prep run (DataPreparer adds nn_features)
docker compose run --rm ohlc_gen                 # RUN_TYPE=generate_full_ohlc → df_with_indicators.pkl

# Train: agentic loop (Optuna + NNStrategist) over groups, writes checkpoints + tracking
docker compose run --rm nn-train                 # RUN_TYPE=nn_train  → NNOrchestrator.from_trainer(...).train()

# Inference: batch, writes {dataset}/df_with_nn.pkl (nn_res_* only)
docker compose run --rm simulate-nn              # RUN_TYPE=infer_nn (alias simulate_nn) → run_inference()
```

Volume contract (per `nn-infrastructure.md`):
- `simple_trader_vol` (`/trader_data`) — **read-only** input (`df_with_indicators.pkl`, `DataAttributes`).
- `simple_trader_vol_long` (`/trader_data_long`) — **read-write** artefacts.

Artefact layout under `{NN_ARTEFACT_ROOT}/{DATA_ROOT}/{PAIR}/nn/`:
```
datasets/{dataset_hash}/   manifest.json  X_{tf}.npy  y.npy  index.npy  splits.json
checkpoints/{spec_hash}/   {group_key}_best.pt  {group_key}_epoch{N}.pt
tracking/{study_name}/     index.sqlite  trials/{trial_id}.json  best.json
```

Env (new): `NN_DEVICE`, `NN_DATA_ROOT`, `NN_ARTEFACT_ROOT`, `NN_INFER_DATASET`, `NN_INFER_CHECKPOINT`, `NUM_WORKERS`.
Env (removed): `NN_CLS`, `NN_TGT`, `NN_TYPE`, `SHUFFLE_GROUPED_NN_DATA`.

**Verified:** [ ] `docker compose build nn-train` succeeds · [ ] `docker compose config` valid after service/env edits.

---

## 4. Task series & dependency order

Tasks are ordered by layer then dependency. Each task is interface-first, RED integration test before either side, then unit tests, then implementation — all verified in Docker (`docker compose run --rm <service> …`). See `layer-first-planning`.

| # | Task | Produces | Depends on |
|---|------|----------|-----------|
| 01 | nn-infrastructure | `docker/Dockerfile.nn-train`, compose `nn-train`/`simulate-nn` edits, `nn/device.py`, artefact-root helpers, env | — |
| 02 | nn-model-spec | `nn/nn_model_spec.py` (NNModelSpec/LayerSpec/GroupingSpec/TargetSpec, `spec_hash`, `from_yaml`), `configs/nn_spec.yaml` | 01 |
| 03 | nn-features | expanded `indicators/library/nn_features.py` + `indicators_config.yaml` `nn` section | — (data layer) |
| 04 | nn-dataset | `nn/nn_dataset.py` (build/load/tensors/split/groups/group, manifest, profit-label TargetSpec wiring) | 02, 03 |
| 05 | nn-model | reworked `nn/nn_model.py` (spec-driven build, multi-head train/infer, checkpoint embed) | 02, 04 |
| 06 | checkpoint-manager | reworked `nn/checkpoint_manager.py` (mode, manifest bundle, promote, `load_best→dict`) | 05 |
| 07 | experiment-tracker | `nn/experiment_tracker.py` (record/is_improvement/promote/summary/best/export) | 02 |
| 08 | nn-orchestrator | reworked `nn/nn_orchestrator.py` (`from_trainer`, grouping train, `run_inference→df_with_nn.pkl`) | 04, 05, 06 |
| 09 | nn-strategist | `nn/nn_strategist.py` (LLM `propose`/`review`, `Proposal`, guardrails) | 07 |
| 10 | training-loop | `nn/training_loop.py` (`run`, Optuna round loop, `study_name`, promotion wiring, `RunResult`) | 07, 08, 09 |
| 11 | trainer-wiring | `trainer.py` RUN_TYPE dispatch (`nn_train`, `infer_nn` alias `simulate_nn`), `from_trainer`, env, `group_nn` removal | 08, 10 |
| 12 | inference-consumer-join | delete `NNPredictor` + `data.py:303` call site + tests; `SimulationData`/`FullData`/`LiveData` left-join `df_with_nn.pkl`; absence-safety | 08, 11 |

```
01 ─┬─ 02 ─┬─ 04 ─┬─ 05 ─ 06 ─┐
    │      │      │            ├─ 08 ─┬─ 11 ─ 12
    │      03 ────┘            │      │
    └────── 07 ─┬─ 09 ────────┘      │
                └─ 10 ───────────────┘
```

---

## 5. Verification strategy

- Every layer boundary gets a Docker-run integration test written **RED** before either side is implemented (per `layer-first-planning`).
- Key integration seams:
  - **03→04:** `nn_features` columns present in `df_with_indicators.pkl` → `NNDataset.build()` materializes tensors + manifest.
  - **04/05→08:** `NNOrchestrator.train()` builds dataset once, partitions by `spec.grouping`, trains a model per group, saves promotable checkpoints.
  - **08→12:** `run_inference()` writes `df_with_nn.pkl`; a consumer (`SimulationData`) left-joins it and a strategy reads `nn_res_*` via `data_point.get(...)`; absent file = columns simply missing.
  - **10:** one full `TrainingLoop.run()` round (Optuna sampling + tracker record + holdout promotion gate) on a tiny dataset, strategist stubbed/disabled (pure-Optuna degrade path).
- A migration is "done" only when `train_nn` and `infer_nn` both run green in Docker and produce the artefact layout in §3.

---

## 6. Migration risks / open items

- **`prepare-nn-data` service (`group_nn`)** is obsolete — grouping is internal to `train()`. Task 01 removes or repurposes it.
- **Spec doc inconsistency:** `trainer-class.md` and `training-module.md` still reference the removed `group_nn` / `NNOrchestrator.group(class_type)`; task 11 removes those references in code and flags the spec follow-up.
- **`nn-train` image:** currently reuses the main `simple_trader` image; task 01 introduces a dedicated `docker/Dockerfile.nn-train` so the always-on live/runtime image gains no CUDA/Optuna weight.
- **Old tests:** `tests/unit/nn/test_nn_predictor.py` is deleted with the class; `test_nn_model.py`, `test_nn_orchestrator.py`, `test_checkpoint_manager.py` are rewritten to the new interfaces under their respective tasks.
- **`NNStrategist` LLM provider** follows project LLM conventions; the loop must degrade to pure Optuna when the strategist is disabled.
- Update `impl_2/TESTS.md` and `impl_2/TECH_DEBT.md` as tasks land.
