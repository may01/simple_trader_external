# Task 02: Constants, Helpers, Paths, and Logging

**Phase:** 00 — Infrastructure  
**Depends on:** Task 01 (Docker)  
**Produces:** `constants.py`, `helpers.py`, `paths.py`, `logs.py` — shared foundation used by every module

---

## Goal

Implement all shared infrastructure: domain constants, path utilities (reading env vars to build file paths), and structured logging. All other modules depend on these.

---

## Context

`constants.py` holds all domain constants (`STRATEGY_ACTION_*`, `POSITION_TYPE_*`, `POSITION_STATE_*`, `LEVEL_TYPE_*`, `LI_*`, `TRADE_BUY`/`TRADE_SELL`, etc.). `helpers.py` provides path helpers — functions that read `PAIR` from `os.environ` to build storage paths. `logs.py` provides logging utilities. No domain logic anywhere in these files.

---

## Files

- Create: `constants.py`
- Create: `helpers.py`
- Create: `paths.py` (or merge into helpers.py)
- Create: `logs.py`

---

## Interface — constants.py

Key constant groups to define:

**Strategy actions:**
- `STRATEGY_ACTION_NOTHING`
- `STRATEGY_ACTION_OPEN_LONG`, `STRATEGY_ACTION_CLOSE_LONG`, `STRATEGY_ACTION_CLOSE_LONG_PART`
- `STRATEGY_ACTION_OPEN_SHORT`, `STRATEGY_ACTION_CLOSE_SHORT`, `STRATEGY_ACTION_CLOSE_SHORT_PART`
- `STRATEGY_ACTION_MOVE_STOP_LOSS_LONG`, `STRATEGY_ACTION_MOVE_STOP_LOSS_SHORT`
- `STRATEGY_ACTION_DO_STOP_LOSS`

**Position types:**
- `POSITION_TYPE_UNKNOWN`
- `POSITION_TYPE_LONG`
- `POSITION_TYPE_SHORT`

**Position states:**
- `POSITION_STATE_WAIT`
- `POSITION_STATE_WAIT_BUY`
- `POSITION_STATE_WAIT_SELL`
- `POSITION_STATE_WAIT_SAFETY_BUY`
- `POSITION_STATE_WAIT_SAFETY_SELL`

**Level types:**
- `LEVEL_TYPE_LONG_SUPPORT` = 1
- `LEVEL_TYPE_LONG_RESISTANCE` = 2
- `LEVEL_TYPE_SHORT_SUPPORT` = 3
- `LEVEL_TYPE_SHORT_RESISTANCE` = 4
- `LEVEL_TYPE_TARGET` = 5
- `LEVEL_TYPE_AUTO_SUPPORT` = 6
- `LEVEL_TYPE_AUTO_RESISTANCE` = 7
- (SHORT_1 and SHORT_2 variants removed — see design-decisions.md #16)

**Level dict keys:**
- `LI_NAME`, `LI_TIME1`, `LI_VAL1`, `LI_TIME2`, `LI_VAL2`
- `LI_ACTIVE`, `LI_TYPE`, `LI_HAD_CONTACT`

**Trade types:**
- `TRADE_BUY`
- `TRADE_SELL`

**Status codes:**
- `STATUS_SUCCESS`
- `STATUS_FAIL`

---

## Interface — helpers.py / paths.py

Path functions all read `os.environ['PAIR']` internally — no `pair` parameter:

- `root_folder() -> str` — mount point only: `ROOT_FOLDER` env var `short` → `/trader_data`, `long` → `/trader_data_long`
- `dataset_folder() -> str` — `{root_folder()}/{DATA_ROOT}/{DATA_SET_NAME}_{PAIR}/` — full path to this dataset's directory
- `data_folder() -> str` — `{dataset_folder()}/data/`
- `shared_folder() -> str` — `{dataset_folder()}/shared/`
- `stats_folder() -> str` — `stats/{DATA_ROOT}/{PAIR}/` — in-repo, version-controlled; NOT on Docker volume
- `nn_folder() -> str` — `{shared_folder()}/nn_data/` — grouped batches co-located with source dataset
- `nn_weights_folder() -> str` — `/trader_data_long/{DATA_ROOT}/{PAIR}/nn_weights/` — ALWAYS on `simple_trader_vol_long`; hardcoded, not affected by ROOT_FOLDER
- `action_folder() -> str` — `{shared_folder()}/actions/` — per-timestamp action pkl files
- `graber_data_path() -> str` — `{dataset_folder()}/graber_data.pkl`
- `wide_df_path() -> str` — `{dataset_folder()}/df_with_indicators.pkl`
- `position_json_path() -> str` — `manual_setup/{PAIR}/position.json`

---

## Interface — logs.py

- `log(message: str) -> None` — standard operation log with timestamp
- `log_error(message: str) -> None` — error log with traceback context
- `log_warning(message: str) -> None` — warning log with traceback context
- `log_revenue(revenue_pct: float, revenue_abs: float, details: dict) -> None` — P&L accounting log
- `log_stock(operation: str, weight: int) -> None` — API weight tracking log

---

## Key Constraints

- Path functions read `os.environ['PAIR']` at call time, not at import time — no module-level env reads
- `constants.py` has ZERO imports from other project modules
- `helpers.py` has ZERO business logic — pure path construction
- `LEVEL_TYPE_SHORT_1_RESISTANCE` and `LEVEL_TYPE_SHORT_2_RESISTANCE` do NOT exist — removed per design-decisions.md #16
- `AUTO_TARGET_SUPPORT` / `AUTO_TARGET_RESISTANCE` renamed to `AUTO_SUPPORT` / `AUTO_RESISTANCE`

---

## Verification

```bash
# Verify constants import cleanly
docker compose run --rm simulate python3 -c "
from constants import STRATEGY_ACTION_OPEN_LONG, STRATEGY_ACTION_CLOSE_LONG, POSITION_STATE_WAIT
from constants import LEVEL_TYPE_LONG_SUPPORT, LEVEL_TYPE_AUTO_SUPPORT, LI_NAME, TRADE_BUY
print('constants ok')
"

# Verify path helpers resolve correctly for short dataset
TRAIN_ENV=configs/train_dataset.env docker compose run --rm simulate python3 -c "
from helpers import root_folder, dataset_folder, data_folder, shared_folder, nn_weights_folder
print('root_folder:', root_folder())
print('dataset_folder:', dataset_folder())
print('data_folder:', data_folder())
print('nn_weights_folder:', nn_weights_folder())
"
# expected: root_folder=/trader_data, dataset_folder=/trader_data/{DATA_ROOT}/{DATA_SET_NAME}_{PAIR}

# Verify ROOT_FOLDER routing — long dataset reads from /trader_data_long
TRAIN_ENV=configs/long_dataset.env docker compose run --rm simulate python3 -c "
from helpers import root_folder
print('root_folder:', root_folder())
"
# expected: root_folder=/trader_data_long
```

---

## Commit

`feat: add constants, helpers, paths, logging infrastructure`
