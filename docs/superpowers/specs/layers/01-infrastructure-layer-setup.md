# Infrastructure Layer — Docker Setup & Container Configuration

**Related specs:**
- [Infrastructure Layer](01-infrastructure-layer.md)
- [Execution Layer](04-execution-layer.md)

---

## 1. Overview

The system runs as a **single Docker image** (`pybtctr2`) used for every execution path. What changes between paths is the `SCRIPT_TYPE` and `RUN_TYPE` environment variables — these tell the container which Python script to run and in which mode.

**Container entry point:**
```
CMD: python3 ${SCRIPT_TYPE}.py ${RUN_TYPE}
```

Examples:
```
python3 trainer.py simulate
python3 pybtctr.py          # (RUN_TYPE unused for live)
python3 grabers/grab_binance.py
python3 view_online_point.py
```

A separate set of docker-compose files exists for each major use case. The operator picks the right compose file, sets the active `PAIR` and `RUN_TYPE`, and runs it. No code change is needed to switch between modes.

---

## 2. Volume Prerequisites

Volumes must be **pre-provisioned externally** before any compose file is started. Docker Compose declares them as `external: true` — it will fail immediately if they do not exist.

| Volume name | Mount point in container | Used by | Contents |
|---|---|---|---|
| `pybtctr_vol` | `/trader_data` | All paths except long | Standard dataset storage |
| `alexandria_pybtctr_vol` | `/trader_data` | Long dataset path | Extended (4-month+) dataset storage on remote server |
| `pybtctr_vol_local` | `/trader_data_local` | NN training (optional) | Local fast storage for grouped NN batches |

**Create volumes (one-time setup):**
```bash
docker volume create pybtctr_vol
docker volume create alexandria_pybtctr_vol
# pybtctr_vol_local — create only if using local NN training
docker volume create pybtctr_vol_local
```

The source code is always **volume-mounted** (`.:/code`), not baked into the image. This means the image only needs to be rebuilt when Python dependencies or ta-lib change — code edits take effect immediately on the next container run.

---

## 3. Execution Paths

### Path A — Data Collection

**Purpose:** Pull raw 1-minute OHLCV klines from Binance and save `graber_data.pkl`. Run once per pair before any other path.

**Compose file:** `docker-compose.yml`

**Key settings:**
```yaml
SCRIPT_TYPE: grabers/grab_binance
RUN_TYPE:    (not used — grab_binance.py ignores it)
env_file:    configs/train_dataset.env   # sets DATA_START, DATA_END, DATA_SET_NAME
```

**Required environment:**
| Variable | Example | Notes |
|---|---|---|
| `PAIR` | `link_usdt` | Trading pair |
| `DATA_ROOT` | `binance` | Exchange subfolder |
| `DATA_SET_NAME` | `2023_09_01_2W` | Names the storage folder |
| `DATA_START` | `1693526400000` | Unix ms — collection start |
| `DATA_END` | `1694736000000` | Unix ms — collection end |
| `BINANCE_API_KEY` | `$BINANCE_API_KEY` | From host env |
| `BINANCE_API_SECRET` | `$BINANCE_API_SECRET` | From host env |

**Output:** `{root_folder}/graber_data.pkl`

**Prerequisites:** None — this is the first step.

---

### Path B — OHLC Generation

**Purpose:** Transform `graber_data.pkl` into the pre-computed wide DataFrame `df_with_indicators.pkl`. Must complete before simulation or data-point generation.

**Compose file:** `docker-compose.yml`

**Key settings:**
```yaml
SCRIPT_TYPE: trainer
RUN_TYPE:    generate_full_ohlc
env_file:    configs/train_dataset.env
```

**Required environment:**
| Variable | Example | Notes |
|---|---|---|
| `PAIR` | `link_usdt` | |
| `DATA_ROOT` | `binance` | |
| `DATA_SET_NAME` | `2023_09_01_2W` | Must match the collection run |
| `DATA_START` / `DATA_END` | ms timestamps | Must match the collection run |
| `AVAIABLE_THREADS` | `15` | Controls parallel indicator computation |
| `TRAINER_TIME_STEP` | `1` | Minutes between generated rows |

**Output:** `{root_folder}/df_with_indicators.pkl`

**Prerequisites:** Path A completed for this pair and date range.

---

### Path C — Simulation / Backtest

**Purpose:** Replay historical data with the current strategy and measure revenue. The primary validation loop.

**Compose file:** `docker-compose.yml` (standard) or `docker-compose-long.yml` (4-month dataset)

**Key settings:**
```yaml
# Standard (2-week dataset):
SCRIPT_TYPE: trainer
RUN_TYPE:    simulate
env_file:    configs/train_dataset.env
volumes:     pybtctr_vol → /trader_data

# Long dataset (4-month):
SCRIPT_TYPE: trainer
RUN_TYPE:    simulate
env_file:    configs/long_dataset.env
volumes:     alexandria_pybtctr_vol → /trader_data
```

**Required environment:**
| Variable | Example | Notes |
|---|---|---|
| `PAIR` | `link_usdt` | |
| `AVAIABLE_THREADS` | `15` | Parallel simulation workers |
| `USE_NN_SIMULATION` | `"True"` | Load pre-computed NN pkl instead of live inference |
| `NN_CLS` / `NN_TGT` / `NN_TYPE` | `$NN_CLS` | NN architecture — passed from host env |

**Prerequisites:** Path B completed. If `USE_NN_SIMULATION=True`, NN pipeline (Path D) must also be complete.

---

### Path D — NN Pipeline

Three sub-steps run sequentially, each as a separate container invocation:

**F1 — Group NN data:**
```yaml
SCRIPT_TYPE: trainer
RUN_TYPE:    group_nn
env_file:    configs/train_dataset.env
```

**F2 — Train NN model:**
```yaml
SCRIPT_TYPE: trainer
RUN_TYPE:    nn_train
NN_CLS:      $NN_CLS    # classification type
NN_TGT:      $NN_TGT    # target type
NN_TYPE:     $NN_TYPE   # model architecture
```
Optional: enable NVIDIA runtime in compose for GPU acceleration.

**D3 — NN-enhanced simulation:**
```yaml
SCRIPT_TYPE: trainer
RUN_TYPE:    simulate_nn
USE_NN_SIMULATION: "True"
```

**Volume note:** D1 writes grouped batches to `nn_folder_local()` (`/trader_data_local/...`) when a local fast volume is available, and to `nn_folder_remote()` otherwise. D2 reads from local, writes trained model weights to `nn_folder_remote()`.

**Prerequisites:** Path B completed before D1. D1 before D2. D2 before D3.

---

### Path E — Live Trading

**Purpose:** Connect to Binance, evaluate strategy in real time, execute orders.

**Compose file:** `docker-compose-live.yml`

**Key settings:**
```yaml
SCRIPT_TYPE: pybtctr
RUN_TYPE:    (not used)
env_file:    configs/live.env
```

**live.env specifics:**
```env
DATA_SET_NAME=live
USE_NN_SIMULATION="False"    # live NN inference, not pre-computed pkl
IS_TRAIDER_TEST="1"          # paper-trade mode — no real orders sent to Binance
```

**Required environment:**
| Variable | Value | Notes |
|---|---|---|
| `PAIR` | `link_usdt` | |
| `DATA_ROOT` | `binance` | |
| `IS_TRAIDER_TEST` | `"1"` | Set to `"0"` only for real-money trading |
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | from host | Required even in paper-trade mode (for market data) |
| `USE_NN_SIMULATION` | `"False"` | Live path runs NN inference per tick |

**Port:** `8050` — exposed for status monitoring.

**Prerequisites:** Path B completed for the reference dataset (used to seed indicator warm-up). Binance credentials in host environment.

---

### Path F — View / Dashboard

Three view variants, each reading from the same volume but presenting different data:

**F1 — Training data viewer** (`view_full`, `view_full_levels`):
```yaml
# docker-compose-view-long.yml
SCRIPT_TYPE: view_full          # or view_full_levels
RUN_TYPE:    none
env_file:    configs/long_dataset.env
ports:       8080, 8090
```
Shows the full backtested OHLC with signals and level overlays. Requires simulation output.

**F2 — Simulation results viewer** (`view_online_point`, `view_onlineB`):
```yaml
# docker-compose-view.yml
SCRIPT_TYPE: view_online_point  # or view_onlineB
RUN_TYPE:    none
env_file:    configs/live.env
ports:       8080, 8090
```
Replays simulation decisions step by step. Requires Path B output.

**F3 — Live trading dashboard** (`view_onlineB` against live data):
```yaml
# docker-compose-view-live.yml
SCRIPT_TYPE: view_onlineB
RUN_TYPE:    none
env_file:    configs/live.env
ports:       8070
```
Shows live position, incoming candles, and strategy decisions in real time.

**All view paths:**
- `AVAIABLE_THREADS=1` — no parallelism needed
- `RUN_TYPE=none` — ignored by view scripts
- Require `BINANCE_API_KEY` / `BINANCE_API_SECRET` for live candle fetching (F2, F3)

---

## 4. Path Dependency Order

```
A (Data Collection)
  └─ B (OHLC Generation)
       ├─ C (Simulation / Backtest)
       ├─ D1 (Group NN)
       │    └─ D2 (Train NN)
       │         └─ D3 (NN Simulation)
       └─ F2 (Simulation Viewer)

E (Live Trading)   ← depends on B for warm-up reference data; otherwise independent
F1, F3             ← independent of training paths; read from live volume
```

---

## 5. Configuration Matrix

| Path | compose file | SCRIPT_TYPE | RUN_TYPE | env_file | Volume |
|---|---|---|---|---|---|
| A — Data collection | docker-compose.yml | `grabers/grab_binance` | — | train_dataset.env | pybtctr_vol |
| B — OHLC generation | docker-compose.yml | `trainer` | `generate_full_ohlc` | train_dataset.env | pybtctr_vol |
| C — Simulation | docker-compose.yml | `trainer` | `simulate` | train_dataset.env | pybtctr_vol |
| C — Long simulation | docker-compose-long.yml | `trainer` | `simulate` | long_dataset.env | alexandria_pybtctr_vol |
| D1 — Group NN | docker-compose.yml | `trainer` | `group_nn` | train_dataset.env | pybtctr_vol |
| D2 — Train NN | docker-compose.yml | `trainer` | `nn_train` | train_dataset.env | pybtctr_vol |
| D3 — NN simulation | docker-compose.yml | `trainer` | `simulate_nn` | train_dataset.env | pybtctr_vol |
| E — Live trading | docker-compose-live.yml | `pybtctr` | — | live.env | pybtctr_vol |
| F1 — Full viewer | docker-compose-view-long.yml | `view_full` | none | long_dataset.env | alexandria_pybtctr_vol |
| F2 — Sim viewer | docker-compose-view.yml | `view_online_point` | none | live.env | pybtctr_vol |
| F3 — Live dashboard | docker-compose-view-live.yml | `view_onlineB` | none | live.env | pybtctr_vol |

---

## 6. Secrets and Host Environment

Binance credentials are **never stored in compose files or env files**. They must be present in the host shell environment before any compose command:

```bash
export BINANCE_API_KEY=<your_key>
export BINANCE_API_SECRET=<your_secret>
```

Compose files reference them as `${BINANCE_API_KEY}` and `${BINANCE_API_SECRET}`, which Docker Compose resolves from the host shell at startup. If either is missing, the container starts but Binance API calls will fail.

NN architecture variables (`NN_CLS`, `NN_TGT`, `NN_TYPE`) follow the same pattern — set in host env before running NN paths.
