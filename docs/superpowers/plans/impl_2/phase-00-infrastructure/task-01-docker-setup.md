# Task 01: Docker Setup

**Phase:** 00 — Infrastructure  
**Depends on:** Nothing  
**Produces:** Working Docker image + single compose file with named services; each service starts and exits cleanly

---

## Goal

Create single Docker image (`pybtctr2`) and single `docker-compose.yml` with one named service per execution path. Each service has its command hardcoded — no `SCRIPT_TYPE`/`RUN_TYPE` env var dispatch. `env_file` paths are configurable via variables with defaults in `.env`. Code is volume-mounted, not baked in — rebuild only when Python deps change.

---

## Context

All execution paths (data collection, training, live trading, visualization) run the same image. Each path maps to a named compose service with an explicit `command:`. Operators run `docker compose run --rm <service>`. Volumes must be pre-created as `external: true` — compose will fail if they don't exist.

`env_file` paths default to standard locations via `.env` file variables. Override any path at runtime: `TRAIN_ENV=configs/custom.env docker compose run --rm simulate`.

---

## Files

- Create: `Dockerfile`
- Create: `docker-compose.yml` (all paths — single file)
- Create: `.env` (env_file path defaults)
- Create: `configs/train_dataset.env` (template)
- Create: `configs/long_dataset.env` (template)
- Create: `configs/live.env` (template)
- Create: `requirements.txt`

---

## Dockerfile Key Requirements

- Base: `python:3.11-slim`
- Install TA-Lib C library from source (required for `ta-lib` Python package)
- Install all Python deps from `requirements.txt`
- `WORKDIR /code`
- No `CMD` — every service defines its own `command:`
- Source code mounted at `/code` via volume — NOT copied into image

---

## `.env` — env_file Path Defaults

```env
TRAIN_ENV=configs/train_dataset.env
LONG_ENV=configs/long_dataset.env
LIVE_ENV=configs/live.env
```

Docker Compose loads `.env` automatically. Override at invocation time:
```bash
TRAIN_ENV=configs/my_custom.env docker compose run --rm simulate
```

---

## `docker-compose.yml` — Service Map

```yaml
services:

  # Path A — Data Collection
  graber:
    image: pybtctr2
    build: .
    command: python3 grabers/grab_binance.py
    env_file: ${TRAIN_ENV:-configs/train_dataset.env}
    volumes:
      - .:/code
      - pybtctr_vol:/trader_data
    environment:
      - BINANCE_API_KEY=${BINANCE_API_KEY}
      - BINANCE_API_SECRET=${BINANCE_API_SECRET}

  # Path B — OHLC Generation
  ohlc:
    image: pybtctr2
    command: python3 trainer.py generate_full_ohlc
    env_file: ${TRAIN_ENV:-configs/train_dataset.env}
    volumes:
      - .:/code
      - pybtctr_vol:/trader_data

  # Path C — Simulation (standard 2-week dataset)
  simulate:
    image: pybtctr2
    command: python3 trainer.py simulate
    env_file: ${TRAIN_ENV:-configs/train_dataset.env}
    volumes:
      - .:/code
      - pybtctr_vol:/trader_data

  # Path C-long — Simulation (4-month dataset)
  simulate-long:
    image: pybtctr2
    command: python3 trainer.py simulate
    env_file: ${LONG_ENV:-configs/long_dataset.env}
    volumes:
      - .:/code
      - alexandria_pybtctr_vol:/trader_data

  # Path D1 — Group NN data
  group-nn:
    image: pybtctr2
    command: python3 trainer.py group_nn
    env_file: ${TRAIN_ENV:-configs/train_dataset.env}
    volumes:
      - .:/code
      - pybtctr_vol:/trader_data
      - pybtctr_vol_local:/trader_data_local

  # Path D2 — Train NN model
  nn-train:
    image: pybtctr2
    command: python3 trainer.py nn_train
    env_file: ${TRAIN_ENV:-configs/train_dataset.env}
    volumes:
      - .:/code
      - pybtctr_vol:/trader_data
      - pybtctr_vol_local:/trader_data_local
    environment:
      - NN_CLS=${NN_CLS}
      - NN_TGT=${NN_TGT}
      - NN_TYPE=${NN_TYPE}

  # Path D3 — NN-enhanced simulation
  simulate-nn:
    image: pybtctr2
    command: python3 trainer.py simulate_nn
    env_file: ${TRAIN_ENV:-configs/train_dataset.env}
    volumes:
      - .:/code
      - pybtctr_vol:/trader_data

  # Path E — Live Trading
  live:
    image: pybtctr2
    command: python3 pybtctr.py
    env_file: ${LIVE_ENV:-configs/live.env}
    ports:
      - "8050:8050"
    volumes:
      - .:/code
      - pybtctr_vol:/trader_data
    environment:
      - BINANCE_API_KEY=${BINANCE_API_KEY}
      - BINANCE_API_SECRET=${BINANCE_API_SECRET}

  # Path F1 — Full data viewer (long dataset)
  view-full:
    image: pybtctr2
    command: python3 view_full.py none
    env_file: ${LONG_ENV:-configs/long_dataset.env}
    ports:
      - "8080:8080"
      - "8090:8090"
    volumes:
      - .:/code
      - alexandria_pybtctr_vol:/trader_data

  # Path F2 — Simulation results viewer
  view-sim:
    image: pybtctr2
    command: python3 view_online_point.py none
    env_file: ${LIVE_ENV:-configs/live.env}
    ports:
      - "8080:8080"
      - "8090:8090"
    volumes:
      - .:/code
      - pybtctr_vol:/trader_data
    environment:
      - BINANCE_API_KEY=${BINANCE_API_KEY}
      - BINANCE_API_SECRET=${BINANCE_API_SECRET}

  # Path F3 — Live trading dashboard
  view-live:
    image: pybtctr2
    command: python3 view_onlineB.py none
    env_file: ${LIVE_ENV:-configs/live.env}
    ports:
      - "8070:8070"
    volumes:
      - .:/code
      - pybtctr_vol:/trader_data
    environment:
      - BINANCE_API_KEY=${BINANCE_API_KEY}
      - BINANCE_API_SECRET=${BINANCE_API_SECRET}

volumes:
  pybtctr_vol:
    external: true
  alexandria_pybtctr_vol:
    external: true
  pybtctr_vol_local:
    external: true
```

---

## Service Reference

| Service | Path | Command | env_file var | Volume |
|---------|------|---------|--------------|--------|
| `graber` | A | `python3 grabers/grab_binance.py` | `TRAIN_ENV` | pybtctr_vol |
| `ohlc` | B | `python3 trainer.py generate_full_ohlc` | `TRAIN_ENV` | pybtctr_vol |
| `simulate` | C | `python3 trainer.py simulate` | `TRAIN_ENV` | pybtctr_vol |
| `simulate-long` | C-long | `python3 trainer.py simulate` | `LONG_ENV` | alexandria_pybtctr_vol |
| `group-nn` | D1 | `python3 trainer.py group_nn` | `TRAIN_ENV` | pybtctr_vol + pybtctr_vol_local |
| `nn-train` | D2 | `python3 trainer.py nn_train` | `TRAIN_ENV` | pybtctr_vol + pybtctr_vol_local |
| `simulate-nn` | D3 | `python3 trainer.py simulate_nn` | `TRAIN_ENV` | pybtctr_vol |
| `live` | E | `python3 pybtctr.py` | `LIVE_ENV` | pybtctr_vol |
| `view-full` | F1 | `python3 view_full.py none` | `LONG_ENV` | alexandria_pybtctr_vol |
| `view-sim` | F2 | `python3 view_online_point.py none` | `LIVE_ENV` | pybtctr_vol |
| `view-live` | F3 | `python3 view_onlineB.py none` | `LIVE_ENV` | pybtctr_vol |

---

## Volumes

Three external volumes must be pre-created by operator before first run:

| Volume | Mount | Used by |
|--------|-------|---------|
| `pybtctr_vol` | `/trader_data` | All standard paths |
| `alexandria_pybtctr_vol` | `/trader_data` | Long dataset path (simulate-long, view-full) |
| `pybtctr_vol_local` | `/trader_data_local` | NN local training (group-nn, nn-train) |

All declared `external: true` in compose file.

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

## Verification

```bash
# Create volumes
docker volume create pybtctr_vol
docker volume create alexandria_pybtctr_vol

# Build image
docker compose build

# Verify container starts without error
docker compose run --rm graber python3 -c "print('container ok')"

# Verify env_file override works
TRAIN_ENV=configs/custom.env docker compose run --rm simulate python3 -c "import os; print(os.environ.get('DATA_SET_NAME', 'NOT SET'))"
```

---

## Commit

`feat: add Docker setup — single compose file with named services, configurable env_file paths`
