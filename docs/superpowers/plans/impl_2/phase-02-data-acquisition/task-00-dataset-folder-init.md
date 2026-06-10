# Task 00: Dataset Folder Initialization

**Phase:** 02 — Data Acquisition  
**Depends on:** Phase 00 Task 02 (helpers.py — path functions)  
**Produces:** `grabers/init_folders.py` — creates all required dataset directories on Docker volumes before any data is written

---

## Goal

Implement `grabers/init_folders.py`. Creates the full folder structure required by the dataset pipeline if it does not already exist. Must be called once before any service writes data (graber, DataPreparer, etc.). Safe to call multiple times (`exist_ok=True`).

---

## Context

Every data-writing service (`graber`, `DataPreparer`, `Trainer`, `LiveDataCollector`) writes into a fixed directory tree rooted at `dataset_folder()`. If any of those directories is missing, the write fails with `FileNotFoundError`. This task centralises folder creation so no individual service needs to handle it, and so the structure is guaranteed before the first write.

---

## Files

- Create: `grabers/init_folders.py`

---

## Interface

```python
def init_dataset_folders() -> None:
    """Create all dataset directories. Safe to call multiple times."""
```

Entry point (called by the graber service at startup and any other service that writes data):

```python
# grabers/init_folders.py
if __name__ == "__main__":
    init_dataset_folders()
```

---

## Folder Structure Created

All paths derived from `helpers.py` functions (read env vars at call time):

| Helper | Resolved path | Notes |
|--------|---------------|-------|
| `dataset_folder()` | `{root_folder()}/{DATA_ROOT}/{DATA_SET_NAME}_{PAIR}/` | Root of this dataset |
| `data_folder()` | `{dataset_folder()}/data/` | Per-thread simulation results |
| `shared_folder()` | `{dataset_folder()}/shared/` | Shared artifacts |
| `nn_folder()` | `{shared_folder()}/nn_data/` | NN batch files |
| `action_folder()` | `{shared_folder()}/actions/` | Per-timestamp action pkl files |
| `nn_weights_folder()` | `/trader_data_long/{DATA_ROOT}/{PAIR}/nn_weights/` | Always on `simple_trader_vol_long` |
| `stats_folder()` | `stats/{DATA_ROOT}/{PAIR}/` | In-repo; version-controlled |

---

## Key Constraints

- All `os.makedirs` calls use `exist_ok=True` — no error if dir already exists
- No logic beyond path resolution and `makedirs`; this module has zero business logic
- `helpers.py` path functions read env vars at call time — do not cache or read at import
- `stats_folder()` is an in-repo relative path (not on Docker volume); still created by this function since it must exist before any service writes stats

---

## Verification

```bash
docker compose run --rm graber python3 -c "
from grabers.init_folders import init_dataset_folders
init_dataset_folders()
from helpers import data_folder, shared_folder, nn_folder, action_folder, nn_weights_folder
import os
for path in [data_folder(), shared_folder(), nn_folder(), action_folder(), nn_weights_folder()]:
    assert os.path.isdir(path), f'missing: {path}'
print('all folders ok')
"
```

---

## Commit

`feat: implement dataset folder initialization`
