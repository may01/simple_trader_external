# NN Infrastructure Specification

**Files:** `docker/Dockerfile.nn-train`, `docker-compose.yml` (`nn-train` service), `nn/device.py`
**Purpose:** Define the runtime infrastructure for NN training and batch inference, including a dedicated training image, a compose service, and **GPU acceleration with CPU fallback** (item 8).

---

## 1. Overview

NN training (the agentic loop with Optuna + many trials) is heavier than the rest of the bot and benefits from GPU. It runs in its **own container** built from a CUDA-capable image, isolated from the trading/runtime containers so the heavyweight ML dependencies (PyTorch + CUDA, Optuna) do not bloat or destabilise the live image.

GPU is **optional**. The same image and code auto-detect CUDA and fall back to CPU, so training runs on a developer laptop without a GPU and on a GPU host without changes.

---

## 2. Dedicated Training Image

`docker/Dockerfile.nn-train`:

- **Base:** an NVIDIA CUDA runtime image (e.g. `nvidia/cuda:<ver>-runtime-ubuntu<ver>`) with a matching CUDA-enabled PyTorch wheel installed. The image runs on CPU when no GPU is present — the CUDA base does not require a GPU to start.
- Installs NN-only dependencies: `torch`, `optuna`, numpy/pandas (shared), and the project package. Trading-runtime deps are not included.
- Entry point runs the trainer's NN commands (`train_nn`, `infer_nn`). `infer_nn` (formerly `simulate_nn`) is the batch-inference producer; it runs on **any dataset**, not only the training one (see `nn-orchestrator-class.md` §4.3).
- Build is separate from the main app image; the live/runtime image gains no CUDA/Optuna weight.

---

## 3. Compose Service

`docker-compose.yml` adds an `nn-train` service:

- Built from `Dockerfile.nn-train`.
- **GPU access (optional):** declared via Compose `deploy.resources.reservations.devices` (NVIDIA capability `gpu`). When the host/daemon has no GPU, the reservation is unsatisfiable only if marked required — so GPU is requested as **optional** and the container starts CPU-only when absent.
- **Mounts:**
  - **`simple_trader_vol` (`/trader_data`) — read-only.** The source training data produced by the live/backtest path: `df_with_indicators.pkl` + `DataAttributes`. NN training is a *consumer* of this volume, never a writer; mounting it read-only prevents training churn from corrupting the live/backtest data volume.
  - **`simple_trader_vol_long` (`/trader_data_long`) — read-write.** Holds all NN-produced artefacts (datasets cache, checkpoints, tracking) under the per-pair subtree below. This is the existing long-term/training-data volume; weights already live here.
  - the worktree source (read-only where possible) — code only, not data.
- **Env:** `NUM_WORKERS`, `NN_DEVICE` (`auto|cuda|cpu`), `NN_DATA_ROOT` (read-only input root, default `/trader_data`), `NN_ARTEFACT_ROOT` (read-write artefact root, default `/trader_data_long`), tracking/checkpoint/dataset dir paths derived from `NN_ARTEFACT_ROOT`, strategist LLM config. For inference: `NN_INFER_DATASET` (target dataset — pair / folder / date-scoped path; default = training folder) and `NN_INFER_CHECKPOINT` (checkpoint id / `best`).
- Not part of the always-on stack; started on demand for training **and inference** runs (`docker compose run --rm nn-train train_nn …` / `… infer_nn …`).
- **`infer_nn` writes only `df_with_nn.pkl`** beside the target dataset's `df_with_indicators.pkl` (under `NN_ARTEFACT_ROOT` for training data, or the live dataset path); it never mutates `df_with_indicators.pkl`.

### Volume rationale (input vs artefacts)

Two existing volumes, split by **producer and lifecycle** — no new volume is introduced:

| Data | Volume | Mode | Why |
|------|--------|------|-----|
| Input: klines, indicators, profit labels (`df_with_indicators.pkl`, `DataAttributes`) | `simple_trader_vol` (`/trader_data`) | **read-only** | Source of truth produced by `graber`/`ohlc_gen`, shared with live + backtest. NN only reads it. RO mount isolates the live data volume from training writes. |
| NN artefacts: `datasets/`, `checkpoints/`, `tracking/` | `simple_trader_vol_long` (`/trader_data_long`) | read-write | Same lifecycle as the weights that already live here ("long" = training/weights). Keeps heavy training churn off the hot live/backtest volume. |

A **separate** dedicated volume is justified only if the `datasets/` tensor cache grows large enough to warrant a disposable retention policy distinct from the precious weights — it is fully rebuildable. Until then, reuse `simple_trader_vol_long`; a third external volume is provisioning overhead with no isolation gain.

### Artefact layout (per pair, three sibling namespaces)

The three artefact kinds have **different keys and different cardinality**, so they live as **sibling namespaces — never nested under each other**:

```
/trader_data_long/{DATA_ROOT}/{PAIR}/nn/
├── datasets/{dataset_hash}/         # shared cache, content-addressed
│   ├── manifest.json  X_{tf}.npy  y.npy  index.npy  splits.json
├── checkpoints/{spec_hash}/         # one dir per model spec
│   └── {group_key}_best.pt  {group_key}_epoch{N}.pt
└── tracking/{study_name}/           # one dir per search run
    ├── index.sqlite  trials/{trial_id}.json  best.json
```

- **`datasets/` is keyed by `dataset_hash`** (source content-hash + feature/target/history/split) and is **shared**: the agentic loop trains hundreds of specs against one cached dataset. Nesting checkpoints under a dataset would either duplicate the heavy `.npy` cache per model or falsely imply a 1:1 relationship — wrong. They are linked by **reference**, not directory nesting: a checkpoint embeds its full spec (→ recomputes `dataset_hash`), the dataset manifest records `source: …@<content-hash>`, the tracking trial records `spec_hash`.
- **`checkpoints/` is keyed by `spec_hash` then `group_key`** — maps directly onto `CheckpointManager` (`checkpoint_dir = checkpoints/{spec_hash}`, `model_name = {group_key}`).
- **`tracking/` is keyed by `study_name`**; `best.json` maps each `group_key` to its incumbent trial/spec.
- The whole `nn/` subtree is scoped under **`{DATA_ROOT}/{PAIR}/`** because weights are pair-specific (same spec on a different pair = different weights) and datasets are inherently pair-specific anyway (their source is that pair's `df_with_indicators`) — so global content-addressing would buy zero cross-pair dedup while breaking the existing `{DATA_ROOT}/{PAIR}/` convention.

**Obsolete naming:** the legacy `nn_weights/model_{TF}_*.pt` scheme keys weights by timeframe. The current design is timeframe-agnostic (a model ingests multi-TF input and emits `nn_res_*` with no `{tf}` prefix); model identity is `spec_hash` + `group_key`, not TF. Timeframe lives only in `spec.timeframes` (input). The `model_{TF}` naming is retired.

### Root-owned files caveat

Training writes into mounted host directories. Per project convention, containers can leave **root-owned files** in mounted worktrees that block merges. The service should write artefacts (`datasets/`, `checkpoints/`, `tracking/`) into dedicated mount paths owned appropriately (run as host UID/GID, or chown on exit) — not scattered into the source tree — so merges are not blocked.

---

## 4. Device Selection

`nn/device.py` centralises device policy, honoured by `NNModel`, `NNOrchestrator`, and `TrainingLoop`:

```python
def resolve_device(pref: str = "auto") -> torch.device:
    if pref == "cpu":
        return torch.device("cpu")
    if torch.cuda.is_available():
        return torch.device("cuda")
    if pref == "cuda":
        log.warning("cuda requested but unavailable; falling back to cpu")
    return torch.device("cpu")
```

- `NNModelSpec.device="auto"` resolves via this function.
- **OOM policy:** a CUDA out-of-memory error on a trial triggers one CPU retry (per `training-coordinator-class.md` §4) before the trial is marked failed.
- Inference (`run_inference`) uses the same resolver; batch inference runs on GPU when present, CPU otherwise.

---

## 5. Resource & Operational Notes

- **Workers:** `NUM_WORKERS` controls DataLoader / dataset-build parallelism; default 4.
- **Reproducibility:** seeds (`spec.seed`, Optuna seed) set; CUDA determinism flags optional via env for exact reproduction at a speed cost.
- **Caching:** the `datasets/` mount persists materialised tensors across runs so repeated trials skip rebuild (see `datapoint-generator-class.md`).
- **Tracking persistence:** the `tracking/` mount holds the SQLite index + trial JSON so a restarted loop resumes its history and incumbent best.
- **Strategist calls:** the LLM `NNStrategist` makes outbound API calls from the training container; its credentials/config are passed via env and its calls are logged for reproducibility.

---

## 6. Summary

| Concern | Decision |
|---------|----------|
| Image | Dedicated `Dockerfile.nn-train`, CUDA base + CUDA PyTorch wheel |
| Service | On-demand `nn-train` compose service, optional GPU reservation |
| Device | `auto` → CUDA if available, else CPU; explicit `cuda`/`cpu` honoured |
| GPU required? | No — CPU fallback everywhere |
| Input data | `simple_trader_vol` (`/trader_data`) mounted **read-only** — live/backtest source |
| Artefacts | `datasets/`, `checkpoints/`, `tracking/` on `simple_trader_vol_long` (`/trader_data_long`), host-owned, under `{DATA_ROOT}/{PAIR}/nn/` |
| Layout | Three sibling namespaces keyed by `dataset_hash` / `spec_hash`+`group_key` / `study_name`; linked by reference, not nested |
| Isolation | NN/ML deps kept out of the live runtime image |
