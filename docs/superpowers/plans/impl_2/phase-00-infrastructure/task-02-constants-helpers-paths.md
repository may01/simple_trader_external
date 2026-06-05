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

- `root_folder() -> str` — returns base data path based on `ROOT_FOLDER` env var (`local` → `/trader_data`, `remote` → `/trader_data`)
- `data_folder() -> str` — `{root_folder()}/{DATA_ROOT}/{PAIR}/{DATA_SET_NAME}/`
- `shared_folder() -> str` — `{root_folder()}/{DATA_ROOT}/{PAIR}/shared/`
- `stats_folder() -> str` — path to `stats/` directory for pair
- `nn_folder_remote() -> str` — remote NN model/data path
- `nn_folder_local() -> str` — local fast-storage NN path (optional `pybtctr_vol_local`)
- `graber_data_path() -> str` — full path to `graber_data.pkl`
- `wide_df_path() -> str` — full path to `df_with_indicators.pkl`
- `position_json_path() -> str` — `manual_setup/{PAIR}/position.json`

---

## Interface — logs.py

- `log(message: str) -> None` — standard operation log with timestamp
- `log_error(message: str) -> None` — error log with traceback context
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
docker compose run --rm trainer python3 -c "
from constants import STRATEGY_ACTION_OPEN_LONG, POSITION_STATE_WAIT
from helpers import root_folder, data_folder
import os; os.environ['PAIR'] = 'link_usdt'; os.environ['ROOT_FOLDER'] = 'local'
print(data_folder())
"
```

---

## Commit

`feat: add constants, helpers, paths, logging infrastructure`
