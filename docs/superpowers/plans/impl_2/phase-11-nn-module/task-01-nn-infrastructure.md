# Task 01: NN Infrastructure (Docker, Device, Artefacts)

**Phase:** 11 — NN Module  
**Depends on:** —  
**Produces:** `docker/Dockerfile.nn-train`, `docker-compose.yml` (nn-train/simulate-nn edits), `nn/device.py`, artefact-root path helpers

---

## Goal
Stand up the runtime layer the rest of phase 11 builds on: a dedicated CUDA-capable training image, an on-demand `nn-train` compose service with the correct volume/env contract, a single device resolver with CPU fallback, and the artefact-root path helpers for the three sibling namespaces. GPU is optional; the same image and code run CPU-only on a laptop and GPU-accelerated on a GPU host.

## Context
NN training (the Optuna + many-trial agentic loop) is heavier than the rest of the bot and benefits from GPU, but its dependencies (CUDA-enabled PyTorch, Optuna) must not bloat or destabilise the always-on `simple_trader` live/runtime image. So training gets its **own** image built from a CUDA runtime base, isolated from the trading containers — the live image gains no CUDA/Optuna weight.

This supersedes the obsolete NN wiring in the current compose file:
- `prepare-nn-data` runs `trainer.py group_nn` — retired; the new dataset cache is content-addressed under `datasets/` and built on demand, not pre-grouped.
- `nn-train` currently runs on the main `simple_trader` image with env `NN_CLS` / `NN_TGT` / `NN_TYPE` — retired; replaced by the dedicated image and `NN_DEVICE` / `NN_DATA_ROOT` / `NN_ARTEFACT_ROOT` / `NUM_WORKERS`.
- `simulate-nn` runs `trainer.py simulate_nn` — repointed at `infer_nn` (alias `simulate_nn`), the batch-inference producer that runs on **any** dataset, not only the training one, and writes only `df_with_nn.pkl` beside the target dataset's `df_with_indicators.pkl`.

## Files
- Create: `docker/Dockerfile.nn-train` — CUDA runtime base + CUDA-enabled PyTorch wheel + `optuna` + numpy/pandas + project package; trading-runtime deps excluded. Entry point dispatches the trainer NN commands (`nn_train` / `infer_nn`), CPU-startable on a host with no GPU.
- Create: `nn/device.py` — `resolve_device()` + the artefact-root path helpers below.
- Modify: `docker-compose.yml` — repoint `nn-train` at `docker/Dockerfile.nn-train`; fix the volume mode contract; swap env vars; repoint `simulate-nn` at `infer_nn`.
- Remove: the `prepare-nn-data` service (`trainer.py group_nn`) — obsolete `group_nn` workflow.

## Docker Entry Points
```
docker compose build nn-train
docker compose run --rm nn-train      # RUN_TYPE=nn_train
docker compose run --rm simulate-nn   # RUN_TYPE=infer_nn (alias simulate_nn)
```
`nn-train` is **not** part of the always-on stack — it is started on demand for both training (`nn_train`) and batch inference (`infer_nn`). Compose changes:
- `nn-train`: `build: { dockerfile: docker/Dockerfile.nn-train }`; mount `simple_trader_vol` (`/trader_data`) **read-only** (`:ro`) and `simple_trader_vol_long` (`/trader_data_long`) **read-write**; code/worktree mount read-only where possible; keep the optional NVIDIA GPU reservation (`deploy.resources.reservations.devices`, capability `gpu`) so it starts CPU-only when no GPU is present; env per the table below.
- `simulate-nn`: run `infer_nn` (alias `simulate_nn`); add `NN_INFER_DATASET` and `NN_INFER_CHECKPOINT`; same volume/env contract as `nn-train`.

## Interface
**`resolve_device(pref: str = "auto") -> torch.device`**
- `pref == "cpu"` → `torch.device("cpu")` (explicit CPU honoured, never probes CUDA).
- otherwise, if `torch.cuda.is_available()` → `torch.device("cuda")`.
- `pref == "cuda"` but CUDA unavailable → log a warning (`"cuda requested but unavailable; falling back to cpu"`) and return `torch.device("cpu")`.
- `pref == "auto"` with no CUDA → `torch.device("cpu")` silently.
- Single source of device policy: honoured by `NNModel`, `NNOrchestrator`, `TrainingLoop`, and `run_inference`. `NNModelSpec.device="auto"` resolves through here.

**`nn_artefact_root(pair: str) -> Path`**
- Returns `{NN_ARTEFACT_ROOT}/{DATA_ROOT}/{pair}/nn` — the per-pair root that holds the three sibling artefact namespaces.
- Scoped under `{DATA_ROOT}/{pair}/` because weights are pair-specific and datasets are inherently pair-specific (their source is that pair's `df_with_indicators`); global content-addressing would buy zero cross-pair dedup while breaking the existing `{DATA_ROOT}/{pair}/` convention.

**Env vars** (replace `NN_CLS`/`NN_TGT`/`NN_TYPE`):

| Env var | Meaning | Default |
|---------|---------|---------|
| `NN_DEVICE` | device preference: `auto` \| `cuda` \| `cpu` | `auto` |
| `NN_DATA_ROOT` | read-only input root (source `df_with_indicators.pkl` + `DataAttributes`) | `/trader_data` |
| `NN_ARTEFACT_ROOT` | read-write artefact root (datasets / checkpoints / tracking) | `/trader_data_long` |
| `NUM_WORKERS` | DataLoader / dataset-build parallelism | `4` |
| `NN_INFER_DATASET` | (inference) target dataset: pair / folder / date-scoped path | training folder |
| `NN_INFER_CHECKPOINT` | (inference) checkpoint id or `best` | `best` |

Tracking / checkpoint / dataset dir paths derive from `NN_ARTEFACT_ROOT`; strategist LLM credentials/config also passed via env.

**Artefact layout** (per pair, three sibling namespaces — never nested under each other):
```
{NN_ARTEFACT_ROOT}/{DATA_ROOT}/{PAIR}/nn/
├── datasets/{dataset_hash}/         # shared cache, content-addressed
│   ├── manifest.json  X_{tf}.npy  y.npy  index.npy  splits.json
├── checkpoints/{spec_hash}/         # one dir per model spec
│   └── {group_key}_best.pt  {group_key}_epoch{N}.pt
└── tracking/{study_name}/           # one dir per search run
    ├── index.sqlite  trials/{trial_id}.json  best.json
```
- `datasets/` keyed by `dataset_hash` (source content-hash + feature/target/history/split) and **shared** — the loop trains hundreds of specs against one cached dataset.
- `checkpoints/` keyed by `spec_hash` then `group_key` (maps onto `CheckpointManager`: `checkpoint_dir = checkpoints/{spec_hash}`, `model_name = {group_key}`).
- `tracking/` keyed by `study_name`; `best.json` maps each `group_key` to its incumbent trial/spec.
- Linked by **reference, not nesting**: a checkpoint embeds its full spec (→ recomputes `dataset_hash`), the dataset manifest records `source: …@<content-hash>`, the tracking trial records `spec_hash`. The legacy `nn_weights/model_{TF}_*.pt` (timeframe-keyed) scheme is retired — model identity is `spec_hash` + `group_key`, not TF.

## Key Constraints
- **Volume contract:** `simple_trader_vol` (`/trader_data`) is mounted **read-only** — NN is a *consumer* of the live/backtest source data and never a writer; RO mount prevents training churn from corrupting the live data volume. `simple_trader_vol_long` (`/trader_data_long`) is **read-write** and holds all NN artefacts. No new volume is introduced (a dedicated `datasets/` volume is justified only if the tensor cache later warrants a disposable retention policy distinct from the precious weights).
- **Image isolation:** CUDA/Optuna/PyTorch live only in `Dockerfile.nn-train`; the always-on `simple_trader` image stays lean.
- **GPU optional:** the NVIDIA reservation is requested as optional, not required — the container starts CPU-only when the host/daemon has no GPU, and the CUDA base image does not need a GPU to start.
- **OOM policy:** a CUDA out-of-memory error on a trial triggers **one CPU retry** before the trial is marked failed (per `training-coordinator-class.md` §4). Document this as a device-policy constraint alongside `resolve_device`.
- **`infer_nn` write scope:** writes only `df_with_nn.pkl` beside the target dataset's `df_with_indicators.pkl` (under `NN_ARTEFACT_ROOT` for training data, or the live dataset path); never mutates `df_with_indicators.pkl`.
- **Root-owned files caveat:** training writes into mounted host dirs; per project convention containers can leave root-owned files in mounted worktrees that block merges. Write artefacts (`datasets/`, `checkpoints/`, `tracking/`) into host-owned mount paths (run as host UID/GID, or chown on exit) — not scattered into the source tree.

## Verification
```bash
docker compose build nn-train
docker compose config   # valid after edits
```

## Commit
`feat(nn): dedicated CUDA nn-train image, device resolver, artefact layout`
