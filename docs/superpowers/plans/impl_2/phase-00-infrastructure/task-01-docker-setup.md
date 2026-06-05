# Task 01: Docker Setup

**Phase:** 00 — Infrastructure  
**Depends on:** Nothing  
**Produces:** Working Docker image + single compose file with named services; each service starts and exits cleanly

---

## Goal

Create single Docker image (`simple_trader`) and single `docker-compose.yml` with one named service per execution path. Each service has its command hardcoded — no `SCRIPT_TYPE`/`RUN_TYPE` env var dispatch. `env_file` paths are configurable via variables with defaults in `.env`. Code is volume-mounted, not baked in — rebuild only when Python deps change.

---

## Context

All execution paths (data collection, training, live trading, visualization) run the same image. Each path maps to a named compose service with an explicit `command:`. Operators run `docker compose run --rm <service>`. Volumes must be pre-created as `external: true` — compose will fail if they don't exist.

`env_file` paths default to standard locations via `.env` file variables. Override any path at runtime: `TRAIN_ENV=configs/custom.env docker compose run --rm simulate`.

---

## Files

**Infrastructure:**
- Create: `Dockerfile`
- Create: `docker-compose.yml` (all paths — single file)
- Create: `.env` (env_file path defaults)
- Create: `configs/functional_dataset.env` (template — 1-day smoke test dataset)
- Create: `configs/train_dataset.env` (template — 2-week standard training)
- Create: `configs/validate_dataset.env` (template — 2-week out-of-sample validation)
- Create: `configs/long_dataset.env` (template — 4-month extended backtest)
- Create: `configs/nn_train_dataset.env` (template — 3-year full NN weight training)
- Create: `configs/live.env` (template — live trading + paper-trade gate)
- Create: `requirements.txt`

**Entry-point stubs** (replaced by real implementations in later phases):
- Create: `trainer.py` (stub — accepts `sys.argv[1]` mode, prints and exits)
- Create: `trader.py` (stub — prints and exits)
- Create: `grabers/__init__.py` (empty package marker)
- Create: `grabers/grab_binance.py` (stub — prints and exits)
- Create: `view_full.py` (stub — prints and exits)
- Create: `view_online_point.py` (stub — prints and exits)
- Create: `view_onlineB.py` (stub — prints and exits)
- Create: `output/.gitkeep` (logs directory, excluded from git via .gitignore)
- Create: `scripts/vol_creation.sh` (volume creation helper — path configurable via env)

---

## Dockerfile Key Requirements

- Base: `python:3.11-slim`
- Install TA-Lib C library from source (required for `ta-lib` Python package)
- Install all Python deps from `requirements.txt`
- CUDA/cuDNN provided via pip (`tensorflow[and-cuda]` in requirements.txt — TF 2.13+ bundles CUDA wheels); no NVIDIA base image needed. GPU access requires `--gpus all` at runtime (Docker NVIDIA Container Toolkit on host).
- `WORKDIR /code`
- No `CMD` — every service defines its own `command:`
- Source code mounted at `/code` via volume — NOT copied into image

---

## `.env` — env_file Path Defaults

```env
FUNCTIONAL_ENV=configs/functional_dataset.env
TRAIN_ENV=configs/train_dataset.env
VALIDATE_ENV=configs/validate_dataset.env
LONG_ENV=configs/long_dataset.env
NN_TRAIN_ENV=configs/nn_train_dataset.env
LIVE_ENV=configs/live.env
```

Docker Compose loads `.env` automatically. Override at invocation time:
```bash
# Run simulation on 4-month dataset
TRAIN_ENV=configs/long_dataset.env docker compose run --rm simulate

# Run simulation on functional (1-day) dataset
TRAIN_ENV=configs/functional_dataset.env docker compose run --rm simulate
```

Each `configs/*.env` file must set `ROOT_FOLDER` to tell `helpers.root_folder()` which mount to use:

| env file | `ROOT_FOLDER` value | `root_folder()` resolves to |
|---|---|---|
| functional/train/validate/live | `short` | `/trader_data/...` |
| long/nn_train | `long` | `/trader_data_long/...` |

---

## `docker-compose.yml` — Service Map

```yaml
services:

  # Path A — Data Collection (any dataset via TRAIN_ENV override)
  graber:
    image: simple_trader
    build: .
    command: python3 grabers/grab_binance.py
    env_file: ${TRAIN_ENV:-configs/train_dataset.env}
    volumes:
      - .:/code
      - simple_trader_vol:/trader_data
      - simple_trader_vol_long:/trader_data_long
    environment:
      - BINANCE_API_KEY=${BINANCE_API_KEY}
      - BINANCE_API_SECRET=${BINANCE_API_SECRET}

  # Path B — OHLC Generation (any dataset via TRAIN_ENV override)
  ohlc_gen:
    image: simple_trader
    command: python3 trainer.py generate_full_ohlc
    env_file: ${TRAIN_ENV:-configs/train_dataset.env}
    volumes:
      - .:/code
      - simple_trader_vol:/trader_data
      - simple_trader_vol_long:/trader_data_long

  # Path C — Simulation (any dataset)
  # Dataset selected by TRAIN_ENV override. ROOT_FOLDER in env file controls which
  # mount path helpers.root_folder() uses: "short" → /trader_data, "long" → /trader_data_long.
  # Both volumes always mounted so any dataset is reachable without changing the service.
  simulate:
    image: simple_trader
    command: python3 trainer.py simulate
    env_file: ${TRAIN_ENV:-configs/train_dataset.env}
    volumes:
      - .:/code
      - simple_trader_vol:/trader_data
      - simple_trader_vol_long:/trader_data_long

  # Path D1 — Prepare NN data (any dataset via NN_TRAIN_ENV override)
  # Batches co-located with source dataset — ROOT_FOLDER in env file selects the mount.
  # Default: 3-year dataset (simple_trader_vol_long). Override to smaller dataset if needed.
  prepare-nn-data:
    image: simple_trader
    command: python3 trainer.py group_nn
    env_file: ${NN_TRAIN_ENV:-configs/nn_train_dataset.env}
    volumes:
      - .:/code
      - simple_trader_vol:/trader_data
      - simple_trader_vol_long:/trader_data_long

  # Path D2 — Train NN model (any dataset via NN_TRAIN_ENV override)
  # Reads batches from /trader_data (ROOT_FOLDER in env selects which vol's data)
  # Writes model weights to /trader_data_long (always simple_trader_vol_long)
  # Weights are reused by simulate-nn, simulate, and live.
  nn-train:
    image: simple_trader
    command: python3 trainer.py nn_train
    env_file: ${NN_TRAIN_ENV:-configs/nn_train_dataset.env}
    volumes:
      - .:/code
      - simple_trader_vol:/trader_data
      - simple_trader_vol_long:/trader_data_long
    environment:
      - NN_CLS=${NN_CLS}
      - NN_TGT=${NN_TGT}
      - NN_TYPE=${NN_TYPE}
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

  # Path D3 — NN-enhanced simulation
  # Reads simulation data from /trader_data (small dataset)
  # Reads model weights from /trader_data_long (always simple_trader_vol_long)
  simulate-nn:
    image: simple_trader
    command: python3 trainer.py simulate_nn
    env_file: ${TRAIN_ENV:-configs/train_dataset.env}
    volumes:
      - .:/code
      - simple_trader_vol:/trader_data
      - simple_trader_vol_long:/trader_data_long

  # Path E — Live Trading
  live:
    image: simple_trader
    command: python3 trader.py
    env_file: ${LIVE_ENV:-configs/live.env}
    ports:
      - "8050:8050"
    volumes:
      - .:/code
      - simple_trader_vol:/trader_data
      - simple_trader_vol_long:/trader_data_long
    environment:
      - BINANCE_API_KEY=${BINANCE_API_KEY}
      - BINANCE_API_SECRET=${BINANCE_API_SECRET}

  # Path F2 — Simulation results viewer (any dataset via LIVE_ENV override)
  view-sim:
    image: simple_trader
    command: python3 view_online_point.py none
    env_file: ${LIVE_ENV:-configs/live.env}
    ports:
      - "8080:8080"
      - "8090:8090"
    volumes:
      - .:/code
      - simple_trader_vol:/trader_data
      - simple_trader_vol_long:/trader_data_long
    environment:
      - BINANCE_API_KEY=${BINANCE_API_KEY}
      - BINANCE_API_SECRET=${BINANCE_API_SECRET}

  # Path F1 — Full data viewer (long dataset)
  view-full:
    image: simple_trader
    command: python3 view_full.py none
    env_file: ${LONG_ENV:-configs/long_dataset.env}
    ports:
      - "8080:8080"
      - "8090:8090"
    volumes:
      - .:/code
      - simple_trader_vol_long:/trader_data_long

  # Path F3 — Live trading dashboard
  view-live:
    image: simple_trader
    command: python3 view_onlineB.py none
    env_file: ${LIVE_ENV:-configs/live.env}
    ports:
      - "8070:8070"
    volumes:
      - .:/code
      - simple_trader_vol:/trader_data
    environment:
      - BINANCE_API_KEY=${BINANCE_API_KEY}
      - BINANCE_API_SECRET=${BINANCE_API_SECRET}

volumes:
  simple_trader_vol:
    external: true
  simple_trader_vol_long:
    external: true
```

---

## Service Reference

| Service | Path | Command | env_file var | Volume |
|---------|------|---------|--------------|--------|
| `graber` | A | `python3 grabers/grab_binance.py` | `TRAIN_ENV` (override for any dataset) | simple_trader_vol:/trader_data + simple_trader_vol_long:/trader_data_long |
| `ohlc_gen` | B | `python3 trainer.py generate_full_ohlc` | `TRAIN_ENV` (override for any dataset) | simple_trader_vol:/trader_data + simple_trader_vol_long:/trader_data_long |
| `simulate` | C | `python3 trainer.py simulate` | `TRAIN_ENV` (override for any dataset) | simple_trader_vol:/trader_data + simple_trader_vol_long:/trader_data_long |
| `prepare-nn-data` | D1 | `python3 trainer.py group_nn` | `NN_TRAIN_ENV` (override for any dataset) | simple_trader_vol:/trader_data + simple_trader_vol_long:/trader_data_long |
| `nn-train` | D2 | `python3 trainer.py nn_train` | `NN_TRAIN_ENV` (override for any dataset) | simple_trader_vol:/trader_data + simple_trader_vol_long:/trader_data_long |
| `simulate-nn` | D3 | `python3 trainer.py simulate_nn` | `TRAIN_ENV` | simple_trader_vol:/trader_data + simple_trader_vol_long:/trader_data_long |
| `live` | E | `python3 trader.py` | `LIVE_ENV` | simple_trader_vol:/trader_data + simple_trader_vol_long:/trader_data_long |
| `view-full` | F1 | `python3 view_full.py none` | `LONG_ENV` | simple_trader_vol_long:/trader_data_long |
| `view-sim` | F2 | `python3 view_online_point.py none` | `LIVE_ENV` (override for any dataset) | simple_trader_vol:/trader_data + simple_trader_vol_long:/trader_data_long |
| `view-live` | F3 | `python3 view_onlineB.py none` | `LIVE_ENV` | simple_trader_vol |

---

## Volumes

Two external volumes must be pre-created before first run using `scripts/vol_creation.sh`:

```bash
# Docker-managed storage (default)
./scripts/vol_creation.sh

# Bind to specific host path (external disk, NFS, etc.)
VOL_PATH=/mnt/data ./scripts/vol_creation.sh
```

### `scripts/vol_creation.sh`

```bash
#!/bin/bash
# Create Docker volumes for simple_trader.
# Usage:
#   ./scripts/vol_creation.sh                         # Docker-managed location
#   VOL_PATH=/mnt/data ./scripts/vol_creation.sh      # Bind to specific host path

set -e

if [ -n "$VOL_PATH" ]; then
    mkdir -p "$VOL_PATH/simple_trader_vol" "$VOL_PATH/simple_trader_vol_long"
    docker volume create --driver local \
        --opt type=none --opt o=bind \
        --opt device="$VOL_PATH/simple_trader_vol" \
        simple_trader_vol
    docker volume create --driver local \
        --opt type=none --opt o=bind \
        --opt device="$VOL_PATH/simple_trader_vol_long" \
        simple_trader_vol_long
else
    docker volume create simple_trader_vol
    docker volume create simple_trader_vol_long
fi

echo "Volumes created:"
docker volume ls --filter name=simple_trader
```

| Volume | Mount | Contents |
|--------|-------|----------|
| `simple_trader_vol` | `/trader_data` | Small datasets: functional (1-day), train (2-week), validate (2-week), live reference |
| `simple_trader_vol_long` | `/trader_data_long` | Large datasets (4-month, 3-year), NN grouped batches, NN model weights |

Both declared `external: true` in compose file.

### NN path contract (constraint on helpers.py)

| Function | Returns | Rule |
|----------|---------|------|
| `nn_folder()` | `/trader_data/{DATA_ROOT}/{DATA_SET_NAME}_{PAIR}/shared/nn_data/` | Grouped batches live on whichever volume is mounted at `/trader_data` — always co-located with the source dataset |
| `nn_weights_folder()` | `/trader_data_long/{DATA_ROOT}/{PAIR}/nn_weights/` | Model weights always read from `simple_trader_vol_long` at `/trader_data_long` — weights trained on 3-year dataset are shared by all consumers |

**Weight reuse rule:** `simulate-nn`, `simulate`, and `live` all read weights from `/trader_data_long` regardless of which small dataset they're running against. Only `nn-train` writes to `/trader_data_long`.

`simulate-nn` is the only service that mounts both volumes simultaneously (small dataset at `/trader_data`, weights at `/trader_data_long`).

---

## Secrets

`BINANCE_API_KEY` and `BINANCE_API_SECRET` are NEVER in compose files or env files. Operator sets in host shell before running. Compose references as `${BINANCE_API_KEY}`. Same for NN vars: `NN_CLS`, `NN_TGT`, `NN_TYPE`.

---

## Key Constraints

- `live.env` must contain `IS_TRAIDER_TEST=1` for paper-trade mode; set to `0` only for real-money trading
- `live.env` sets `USE_NN_SIMULATION=False` — live path runs online NN inference
- `live` service exposes port 8050 for status monitoring
- View services: `AVAIABLE_THREADS=1` set in their env files

---

## Stub Content

All stubs follow the same pattern — print service name + received args, exit 0:

```python
# trainer.py
import sys
mode = sys.argv[1] if len(sys.argv) > 1 else "none"
print(f"[stub] trainer mode={mode}")
```

```python
# trader.py
print("[stub] trader")
```

```python
# grabers/grab_binance.py
print("[stub] grab_binance")
```

```python
# view_full.py / view_online_point.py / view_onlineB.py
import sys
print(f"[stub] {__file__} args={sys.argv[1:]}")
```

---

## Verification

```bash
# One-time setup
./scripts/vol_creation.sh

# Build image
docker compose build

# Verify every service starts and exits cleanly using stubs
docker compose run --rm graber
docker compose run --rm ohlc_gen
docker compose run --rm simulate
docker compose run --rm prepare-nn-data
docker compose run --rm nn-train
docker compose run --rm simulate-nn
docker compose run --rm live
docker compose run --rm view-sim
docker compose run --rm view-full
docker compose run --rm view-live

# Verify ROOT_FOLDER routing — long dataset reads from /trader_data_long
TRAIN_ENV=configs/long_dataset.env docker compose run --rm simulate \
  python3 -c "import os; print(os.environ.get('ROOT_FOLDER', 'NOT SET'))"
# expected output: long

# Verify env_file override works
TRAIN_ENV=configs/functional_dataset.env docker compose run --rm simulate \
  python3 -c "import os; print(os.environ.get('DATA_SET_NAME', 'NOT SET'))"
```

---

## Commit

`feat: add Docker setup — single compose file with named services, configurable env_file paths`
