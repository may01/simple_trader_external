# Backtesting Flow — Runbook

End-to-end guide: create a dataset, prepare it, run the backtest, verify results in the visualiser.

All commands run from the repo root (worktree `experimental_imp_2`):

```bash
cd /home/om/projects/simple_trader/worktrees/experimental_imp_2
```

## Pipeline overview

```
grab (Binance 1-min klines)          graber service
        │  graber_data.pkl
        ▼
prepare (OHLC resample + indicators) ohlc_gen service
        │  df_with_indicators.pkl + data_attributes
        ▼
simulate (backtest run)              simulate service
        │  training_state.pkl + metrics, stats/
        ▼
view (chart verification)            view-full / view-sim services
```

Every stage is a Docker Compose service. The dataset a stage operates on is selected by the env file passed via `TRAIN_ENV` / `LONG_ENV` / `NN_TRAIN_ENV` (defaults are wired in `.env`).

## 0. One-time setup

### 0.1 Create Docker volumes

Volumes are external bind mounts; data lives outside Docker's default storage.

```bash
# Default location: /media/om/Alexandria/simple_trader
./scripts/vol_creation.sh

# Or override the host path:
VOL_PATH=/some/other/disk/simple_trader ./scripts/vol_creation.sh
```

This creates two volumes:

| Volume | Mounted at | Used for |
|---|---|---|
| `simple_trader_vol` | `/trader_data` | short datasets (`ROOT_FOLDER=short`) |
| `simple_trader_vol_long` | `/trader_data_long` | long datasets (`ROOT_FOLDER=long`) + NN weights |

### 0.2 Build the image

```bash
docker compose build
```

(Any `docker compose up` also builds on first run — `build: .` is set on every service.)

### 0.3 Binance API keys

The graber needs credentials in the host environment:

```bash
export BINANCE_API_KEY=...
export BINANCE_API_SECRET=...
```

## 1. Create a new dataset

A dataset is fully defined by an env file in `configs/`. Existing examples:

| File | Dataset | Range |
|---|---|---|
| `functional_dataset.env` | `1d` smoke test | 1 day |
| `train_dataset.env` | `2w` training | 2 weeks |
| `validate_dataset.env` | `2w_val` out-of-sample | 2 weeks |
| `long_dataset.env` | `4m` extended backtest | 4 months |
| `nn_train_dataset.env` | `3y` NN training | 3 years |

### 1.1 Write the env file

Copy the closest existing one and edit:

```bash
cp configs/train_dataset.env configs/my_dataset.env
```

```bash
# configs/my_dataset.env
ROOT_FOLDER=short          # short → simple_trader_vol, long → simple_trader_vol_long
DATA_ROOT=train            # top-level folder on the volume
DATA_SET_NAME=my_set       # dataset folder name component
PAIR=link_usdt             # lowercase underscore form → LINKUSDT
DATA_START=1704067200000   # epoch ms, inclusive
DATA_END=1705276800000     # epoch ms, exclusive
EXCHANGE_FEE=0.001
AVAIABLE_THREADS=4
```

Get epoch-ms timestamps:

```bash
date -u -d '2024-01-01 00:00:00' +%s000
```

Resulting on-volume layout (`helpers.py`):

```
/trader_data[_long]/{DATA_ROOT}/{DATA_SET_NAME}_{PAIR}/   # dataset_folder
    data/        # graber_data.pkl, df_with_indicators.pkl, data_attributes
    shared/      # training_state.pkl
    nn/          # df_with_nn.pkl
    action/
/trader_data_long/{DATA_ROOT}/{PAIR}/nn_weights/          # always on long volume
stats/{DATA_ROOT}/{PAIR}/                                  # in-repo, not on volume
```

### 1.2 Grab raw data

```bash
TRAIN_ENV=configs/my_dataset.env docker compose up graber
```

Runs `grabers/grab_binance.py`: downloads 1-min OHLCV klines from Binance for `DATA_START → DATA_END`, writes `graber_data.pkl`. **Incremental**: if the file already exists, only the missing range is downloaded and merged — safe to re-run after extending `DATA_END`.

## 2. Prepare the dataset

```bash
TRAIN_ENV=configs/my_dataset.env docker compose up ohlc_gen
```

Runs `trainer.py generate_full_ohlc` (→ `RUN_TYPE=prepare_data`): resamples 1-min data to all configured timeframes, computes indicators per `configs/indicators_config.yaml`, writes the wide dataframe (`df_with_indicators.pkl`) and data attributes.

Re-run this step whenever `indicators_config.yaml` changes.

## 3. Run the backtest

```bash
TRAIN_ENV=configs/my_dataset.env docker compose up simulate
```

Runs `trainer.py simulate`: `SimulationOrchestrator` walks the window `DATA_START → DATA_END` with the default `StrategyManager`, then `PerformanceAnalyzer` computes metrics. Output: `shared/training_state.pkl` (phase + metrics) on the volume.

Optional env overrides (set in the env file or inline):

| Var | Default | Meaning |
|---|---|---|
| `STEP_MIN` | `1` | simulation step in minutes |
| `FEE` | `EXCHANGE_FEE` (0.001) | exchange fee override |
| `AVAIABLE_THREADS` | — | worker processes (note spelling) |

## 4. Visualise / verify

### 4.1 Full historical view (charts + indicators)

```bash
LONG_ENV=configs/my_dataset.env docker compose up view-full
```

Runs `view_full.py`: loads `df_with_indicators.pkl` for the dataset and renders OHLCV + RSI-14 + CCI-14 (plotly). Ports 8080/8090 are mapped. Note: `view-full` defaults to `LONG_ENV` (`configs/long_dataset.env`) — pass your env file explicitly as above, and remember it only mounts the **long** volume, so for a `ROOT_FOLDER=short` dataset use `view-sim` instead or temporarily add the short volume to the service.

### 4.2 Simulation point view

```bash
LIVE_ENV=configs/my_dataset.env docker compose up view-sim
```

Runs `view_online_point.py` on ports 8080/8090; mounts both volumes.

### What to verify

- Candles continuous over the whole `DATA_START → DATA_END` range (no gaps → graber complete).
- Indicator columns present and non-NaN after warm-up period.
- Timeframe resampling aligned (TF candles match 1-min source).

## 5. Optional: NN stages

Uses `NN_TRAIN_ENV` (default `configs/nn_train_dataset.env`, 3-year dataset, `ROOT_FOLDER=long`).

```bash
# group/prepare NN data (currently maps to prepare_data — see trainer.py UNRESOLVED note)
docker compose up prepare-nn-data

# train (GPU; reads NN_CLS / NN_TGT / NN_TYPE from .env or inline)
NN_CLS=... NN_TGT=... NN_TYPE=... docker compose up nn-train

# inference → nn/df_with_nn.pkl
TRAIN_ENV=configs/my_dataset.env docker compose up simulate-nn
```

## 6. Full pipeline in one shot

`trainer.py full` chains grab → prepare → simulate → nn_train → simulate_nn → prepare. No dedicated compose service; run ad hoc:

```bash
TRAIN_ENV=configs/my_dataset.env docker compose run --rm simulate python3 trainer.py full
```

## Quick reference

```bash
# new dataset end-to-end (short, no NN)
export BINANCE_API_KEY=... BINANCE_API_SECRET=...
cp configs/train_dataset.env configs/my_dataset.env   # edit dates/name
E=configs/my_dataset.env
TRAIN_ENV=$E docker compose up graber
TRAIN_ENV=$E docker compose up ohlc_gen
TRAIN_ENV=$E docker compose up simulate
LIVE_ENV=$E docker compose up view-sim                # verify at :8080
```
