# Infrastructure Layer Specification

**Layer position:** Foundation — provides runtime environment, configuration, logging, data persistence, and path management for all other layers.

**Related specs:**
- [Main Architecture](../2026-05-05-pybtctr2-architecture.md)
- [Data Layer](02-data-layer.md)
- [Docker Setup & Container Configuration](01-infrastructure-layer-setup.md)

---

## 1. Overview

**Purpose:** Provides the deployment environment, configuration management, structured logging, file-system path utilities, and shared domain constants that all other layers depend on.

**Responsibilities:**
- Docker image build and container lifecycle (Dockerfile, docker-compose files)
- Environment variable injection and dataset configuration (configs/*.env, candles_config.yaml, indicators_config.yaml)
- Custom file-based logging (logs.py)
- File-system path construction for data storage (helpers.py)
- Shared domain constants and utilities (constants.py)
- Docker volume management for persistent OHLC data and trained models

**Key modules:** Dockerfile, docker-compose variants, configs/*.env, candles_config.yaml, indicators_config.yaml, logs.py, helpers.py, constants.py

---

## 2. Layer Boundaries

**Upstream (feeds into this layer):** None — this is the bottom layer. External dependencies: Binance API credentials (BINANCE_API_KEY, BINANCE_API_SECRET set in environment), Docker volumes provisioned externally.

**Downstream (layers that depend on this layer):** All other layers. Every module reads environment variables and uses helpers.py path functions. Logging via logs.py is used throughout.

**Key interfaces this layer exposes:**
- `helpers.root_folder()` → absolute path to `/trader_data/{DATA_ROOT}/{DATA_SET_NAME}_{PAIR}/`
- `helpers.data_folder()` → `{root_folder}/data/`
- `helpers.shared_folder()` → `{root_folder}/shared/`
- `helpers.nn_folder()` → `{root_folder}/shared/nn_data/`
- `helpers.action_folder()` → `{root_folder}/shared/actions/`
- `helpers.stats_folder()` → `stats/{DATA_ROOT}/{PAIR}/` (in-repo, version-controlled)
- `logs.log(msg, do_print=False)` → appends to `output/LOG_{PAIR}.txt`
- `logs.log_revenue(msg, time_point, thread)` → prints to stdout + appends per-thread revenue file
- `logs.log_error(msg)` / `logs.log_warn(msg)` → log with forced stdout print
- `constants.*` → all shared domain constants (see §5 — constants.py)

---

## 3. Data Flow

```
Environment Variables (PAIR, DATA_SET_NAME, ROOT_FOLDER, DATA_ROOT, ...)
   ↓ [os.environ reads in helpers.py]
Path strings (root_folder, data_folder, shared_folder, ...)
   ↓ [passed to all modules that read/write data]
Docker Volume: /trader_data/{DATA_ROOT}/{DATA_SET_NAME}_{PAIR}/
   ├── data/                    ← OHLC candle snapshots (.pkl per timestamp)
   ├── shared/                  ← Levels, NN data, thread results, action logs
   │   ├── nn_data/             ← NN training points, grouped batches, simulation results
   │   └── actions/             ← Action pkl files (one per timestamp)
   ├── graber_data.pkl          ← Raw 1-minute OHLCV from Binance (written once by grab_binance.py)
   └── df_with_indicators.pkl   ← Pre-computed wide DataFrame: all timeframes + all indicators,
                                   1-min indexed. Written by trainer (generate_full_ohlc),
                                   consumed by SimulationData for O(1) replay. Not present
                                   in live mode — live path computes indicators on the fly.

stats/{DATA_ROOT}/{PAIR}/  (in-repo directory, version-controlled)
   ├── level_stats.pkl         ← Level statistics loaded by Data class
   ├── diff_stats.pkl          ← Diff statistics for target/SL calculation
   └── rsi_classification.json ← RSI zone/move classification parameters
```

---

## 4. Execution Flow

### Container startup
1. Docker loads env file (e.g., `configs/train_dataset.env`) and injects all variables
2. Container CMD runs `python3 ${SCRIPT_TYPE}.py ${RUN_TYPE}`
3. Script imports modules; each module reads env vars at import time or at first function call
4. `helpers.py` constructs paths from `ROOT_FOLDER` (selects `/trader_data` or `/trader_data_local`)

### Logging flow (per log call)
1. Caller invokes `logs.log(msg)` / `logs.log_error(msg)` / `logs.log_revenue(msg, tp, thread)`
2. `log()` prepends current timestamp from `data.item.cur_point`
3. Appends formatted line to `output/LOG_{PAIR}.txt` (file opened in append mode each call)
4. `do_print=True` additionally writes to stdout and calls `sys.stdout.flush()`
5. `log_revenue()` always prints to stdout and writes to `output/REVENUE_{PAIR}_{thread}.txt`

### Dataset configuration (how configs/*.env are used)
1. docker-compose mounts env_file into container environment
2. `trainer.py` reads `DATA_START`, `DATA_END`, `TRAINER_TIME_STEP`, `AVAIABLE_THREADS` directly from `os.environ`
3. `helpers.py` reads `PAIR`, `DATA_ROOT`, `DATA_SET_NAME`, `ROOT_FOLDER` to build paths
4. `strategy_manager.py` reads `USE_NN_SIMULATION` to decide live vs pre-computed NN

---

## 5. Key Components

### Dockerfile
- Base: `python:3.9`
- Installs `requirements.txt`, then compiles `ta-lib 0.4.0` from source (C library for technical indicators)
- Installs `debugpy` for remote debugging
- CMD: `python3 ${SCRIPT_TYPE}.py ${RUN_TYPE}` — both parameters are docker-compose environment variables
- Source code mounted at runtime (`.:/code`), not baked into image — container always runs the live working tree

### docker-compose variants (7 files)

| File | Purpose | Key env_file |
|------|---------|--------------|
| `docker-compose.yml` | Standard training/simulation | `train_dataset.env` |
| `docker-compose-live.yml` | Live trading bot | `live.env` |
| `docker-compose-long.yml` | Long-dataset training | `long_dataset.env` |
| `docker-compose-test.yml` | Test run with simulate_nn | `train_dataset.env` |
| `docker-compose-view.yml` | Data visualization (view_online_point) | `live.env` |
| `docker-compose-view-live.yml` | Live trading dashboard | `live.env` |
| `docker-compose-view-long.yml` | Full data viewer | `long_dataset.env` |

### configs/*.env files

Six datasets, each defining the same four keys:

| File | Dataset span | Notes |
|------|-------------|-------|
| `functional_dataset.env` | 1 day (2023-01-29) | For smoke tests |
| `train_dataset.env` | 2 weeks (2023-09-01) | Standard training |
| `validate_dataset.env` | 2 weeks (different range from train) | Covers a different time range from `train_dataset.env` to provide out-of-sample validation; time range and expected revenue range documented in testing strategy |
| `nn_train_dataset.env` | 3 years (2020-09-01) | Full NN training dataset |
| `live.env` | Live + 2-week reference | Sets IS_TRAIDER_TEST=1, USE_NN_SIMULATION=False |
| `long_dataset.env` | 4 months (2025-03-01) | Extended backtesting |

All files set: `DATA_SET_NAME`, `DATA_START` (Unix ms), `DATA_END` (Unix ms), `SHUFFLE_GROUPED_NN_DATA`, `ROOT_FOLDER`, `EXCHANGE_FEE`.

`EXCHANGE_FEE` must be present in every env file. Typical values: `0.001` (standard Binance taker), `0.00075` (BNB discount tier). Simulation env files should match the fee that was active during the data collection period for accurate P&L replay.

### YAML config files (in-repo, version-controlled)

| File | Purpose |
|------|---------|
| `candles_config.yaml` | Defines active timeframe list (e.g. `candles: [1, 5, 15, 60, 240, 1440]`). Read at startup by both live and simulation paths. No timeframes are hardcoded in `data.py`. |
| `indicators_config.yaml` | Declares the active `IndicatorField` registry — which fields are enabled and their parameters. Read by `Indicators` at startup. |

These files are operator-configurable: changing the timeframe list or enabling/disabling indicators requires no code change, only a config update and container restart.

### Environment Variables

| Variable | Used by | Purpose |
|----------|---------|---------|
| `PAIR` | helpers, data, logs, trainer, views | Trading pair in lowercase `coin_base` format (e.g., `link_usdt`) |
| `DATA_ROOT` | helpers | Exchange subfolder name (`binance`) |
| `DATA_SET_NAME` | helpers | Dataset identifier; forms storage path |
| `ROOT_FOLDER` | helpers | `"local"` or `"remote"` — selects volume mount (`/trader_data_local` or `/trader_data`) |
| `DATA_START` / `DATA_END` | trainer | Dataset time bounds in Unix milliseconds |
| `TRAINER_TIME_STEP` | trainer | Minutes between generated data points |
| `AVAIABLE_THREADS` | trainer | Parallel process count for data generation |
| `USE_NN_SIMULATION` | strategy_manager | `"True"`: load pre-computed NN pkl; `"False"`: live NN inference |
| `SHUFFLE_GROUPED_NN_DATA` | trainer | Whether to shuffle NN training batches |
| `NN_CLS` / `NN_TGT` / `NN_TYPE` | trainer | NN architecture and target configuration |
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | stocks/binance_stock.py | Exchange API credentials |
| `EXCHANGE_FEE` | stocks/base_stock.py | Taker fee rate as a decimal (e.g. `"0.001"` = 0.1%). Read once at Stock init; propagated as `stock.item.fee` to all consumers. No fee value is hardcoded anywhere else. Update when Binance fee tier changes. |
| `IS_TRAIDER_TEST` | position/position.py | `"1"` = paper-trade mode; orders not submitted to exchange |
| `ACTIONS_INTEGRATION_TESTS` / `STRATEGY_INTEGRATION_TESTS` | pybtctr.py | Integration test gates |

### logs.py — Custom Logging

Not stdlib `logging`. All output written to files under `output/` (relative to container working dir `/code`).

| Function | Output file | Stdout? |
|----------|------------|---------|
| `log(msg, do_print=False)` | `output/LOG_{PAIR}.txt` | Only if `do_print=True` |
| `log_revenue(msg, time_point, thread)` | `output/REVENUE_{PAIR}_{thread}.txt` | Always |
| `log_error(msg)` | `output/LOG_{PAIR}.txt` | Always (prefixes `ERROR!!!:`) |
| `log_warn(msg)` | `output/LOG_{PAIR}.txt` | Always (prefixes `WARNING!!!:`) |
| `log_test(msg, type)` | `output/LOG_{PAIR}.txt` | Gated by type flag dict |
| `log_signals(msg)` | `output/LOG_{PAIR}.txt` | Always (hardcoded enabled) |

Timestamp prefix comes from `data.item.cur_point` (current simulation or live Unix timestamp).

> **Known violation — to be fixed:** `logs.py` currently imports `data` to read `data.item.cur_point`, creating an upward dependency from the Infrastructure layer into the Data layer. This violates the layer boundary. The fix is to remove the `data` import and have callers pass the timestamp explicitly: `log(msg, ts=None, do_print=False)` — when `ts` is `None`, the log line omits the timestamp prefix. No other layer should need to change.

### helpers.py — Path Utilities

Sole responsibility: construct absolute file-system paths from environment variables. No domain logic, no constants, no utilities.

**Target interface (no `pair` argument — all functions read `os.environ['PAIR']` internally):**

```python
root_folder()   → /trader_data/{DATA_ROOT}/{DATA_SET_NAME}_{PAIR}/
data_folder()   → {root_folder()}/data/
shared_folder() → {root_folder()}/shared/
nn_folder()     → {root_folder()}/shared/nn_data/
action_folder() → {root_folder()}/shared/actions/
stats_folder()  → stats/{DATA_ROOT}/{PAIR}/              # in-repo, not in volume

# Remote/local variants (used by nn module which must cross the local/remote boundary):
remote_root_folder() → /trader_data/{DATA_ROOT}/{DATA_SET_NAME}_{PAIR}/
local_root_folder()  → /trader_data_local/{DATA_ROOT}/{DATA_SET_NAME}_{PAIR}/
nn_folder_remote()   → {remote_root_folder()}/shared/nn_data/
nn_folder_local()    → {local_root_folder()}/shared/nn_data/
```

`ROOT_FOLDER="remote"` → `/trader_data`; `ROOT_FOLDER="local"` → `/trader_data_local`

**Correct usage (after cleanup):**
```python
# All callers — no pair argument passed:
dir = data_folder() + '/' + str(time_point)
path = shared_folder() + '/thread_result_by_id_' + str(thread_num) + '.pkl'
path = stats_folder() + '/rsi_classification.json'
path = nn_folder() + '/nn_simulation_cls_big_tf.pkl'
```

**Current state and cleanup required:**

The current `helpers.py` has three problems that must be fixed:

**1. Dead `pair` parameter on every path function.**
Every function takes `pair` but ignores it — all functions read `os.environ['PAIR']` directly. The parameter is dead everywhere.

```python
# Current (wrong):
def data_folder(pair):
    return root_folder(pair) + '/data'      # pair is unused

# Target:
def data_folder():
    return root_folder() + '/data'
```

All call sites pass `data_item.pair` or `self.pair` — these arguments must be removed from every call:
```python
# Current call sites (wrong):
data_folder(data_item.pair)
shared_folder(self.pair)
stats_folder(os.environ["PAIR"])
nn_folder(data_item.pair)

# Target call sites:
data_folder()
shared_folder()
stats_folder()
nn_folder()
```

**2. Dead `root_folder_prefix` global.**
`helpers.py` defines `root_folder_prefix = "history_"` but the path functions never read it — they read `os.environ['DATA_SET_NAME']` directly. Several files set `helpers.root_folder_prefix = os.environ['DATA_SET_NAME']` believing this configures the path builder. It does nothing. Both the global and all assignments to it must be removed:
```python
# Remove from helpers.py:
root_folder_prefix = "history_"   # dead — path functions ignore it

# Remove from all callers (pybtctr.py, trainer.py, view_full.py, view_full_levels.py,
#                           view_onlineB.py, view_online_point.py):
helpers.root_folder_prefix = os.environ['DATA_SET_NAME']   # no-op — delete
```

**3. Non-path content (domain constants, utilities, `BtcException`).**
These are being extracted to `constants.py` (see below). During migration, `helpers.py` re-exports them via `from constants import *` to preserve backward compatibility until all callers are updated to import from `constants` directly.

### constants.py — Shared Domain Constants

Single source of truth for all integer codes, type identifiers, and string keys used across layers. Every consumer imports from `constants` directly; no layer re-exports these.

**Curated constant groups (confirmed needed):**

| Group | Constants | Used by |
|-------|-----------|---------|
| Position type | `POSITION_TYPE_LONG/SHORT/UNKNOWN` | position, strategy, signals |
| Position state | `POSITION_STATE_WAIT`, `WAIT_BUY`, `WAIT_SELL`, `WAIT_SAFETY_*` | position, robot |
| Strategy action | `STRATEGY_ACTION_NOTHING/OPEN_LONG/OPEN_SHORT/CLOSE_LONG/CLOSE_SHORT/DO_STOP_LOSS/MOVE_STOP_LOSS_*/CLOSE_*_PART/SET_MOVING_*` | strategy_manager, robot, train_robot |
| Level type | `LEVEL_TYPE_LONG_SUPPORT/RESISTANCE`, `SHORT_SUPPORT/RESISTANCE`, `TARGET`, `AUTO_SUPPORT/RESISTANCE` | levels, signals, strategy |
| Level dict keys | `LI_NAME/TIME1/VAL1/TIME2/VAL2/ACTIVE/TYPE/HAD_CONTACT` | levels, strategy |
| Level action | `LEVEL_ACTION_NOTHING/BREAK/FALSE_BREAK/BOUNCE` | levels, signals |
| Order status | `ORDER_STATUS_NEW/PARTIALLY_FILLED/FILLED/CANCELED/REJECTED/EXPIRED` | robot, position |
| Trade direction | `TRADE_NONE/BUY/SELL` | robot, train_robot |
| NN type/target | `NN_TYPE_*`, `NN_TARGET_TYPE_*` | nn, trainer |
| RSI/zone class | `CLASS_RSI_*/CLASS_ZONE_*`, `CLASS_OVER_HIGH/LOW` | data, signals |

**Placeholder for new constants:**

```python
# ── ADD NEW CONSTANTS HERE ──────────────────────────────────────────────────
# Group: <domain name>
# <CONSTANT_NAME> = <value>   # brief note on usage
# ───────────────────────────────────────────────────────────────────────────
```

New constants MUST be added in this block with their group label. This prevents constants from accumulating in module files across the codebase.

**What does NOT belong in constants.py:**
- Path strings (→ `helpers.py`)
- Config values loaded from env/yaml (→ read at call site via `os.environ`)
- Computed thresholds or model parameters (→ `indicators_config.yaml` or stats files)

---

## 6. Assumptions & Constraints

- Docker volumes (`pybtctr_vol`, `pybtctr_vol_local`, `alexandria_pybtctr_vol`) are pre-provisioned externally; compose does not create them
- Source code is always volume-mounted (`.:/code`), not baked into image — rebuild is only needed when Python dependencies or ta-lib change
- All timestamps are UTC Unix epoch in milliseconds for DATA_START/DATA_END, but seconds for internal data processing
- `output/` directory is excluded from git (via .gitignore); log files do not persist between deployments
- `stats/` directory IS version-controlled; changes to rsi_classification.json or diff_stats.pkl affect all training runs
- **Fee is a deployment variable, not a code constant.** `EXCHANGE_FEE` is the single source of truth, declared in each `*.env` file. `base_stock.py` reads it once at init and exposes it as `stock.item.fee`. No other module may hardcode a fee value — all consumers receive fee via constructor parameter from `stock.item.fee`.
- Logging is append-only, file-based; no log rotation; output/ fills up during long training runs
