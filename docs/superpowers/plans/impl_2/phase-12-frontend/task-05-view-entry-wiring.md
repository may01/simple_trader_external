# Task 05: Viewer Entry Wiring

**Phase:** 12 — Frontend
**Depends on:** Task 02 (DataViewer), Task 03 (TrainingDashboard), Task 04 (LiveDashboard)
**Produces:** root `view_online_point.py`, `view_full.py`, `view_onlineB.py`, `view_training.py` — replace phase-00 stubs; Docker execution path F

---

## Goal

Wire the four root viewer stubs to the frontend modules. Tasks 03/04 already named their entries ("Create: view_training.py / view_online_point.py — instantiates X, calls run()") but the stubs were never replaced; `view_full.py` and `view_onlineB.py` had no entry spec at all — this task defines all four.

## Entry map

| Script | Compose service | Port(s) | Wires to |
|---|---|---|---|
| `view_online_point.py` | `view-sim` | 8080, 8090 | `frontend.live_dashboard.LiveDashboard` (per task-04) |
| `view_onlineB.py` | `view-live` | 8070 | `frontend.live_dashboard.LiveDashboard` (rolling live view) |
| `view_full.py` | `view-full` | 8080, 8090 | `frontend.data_viewer.DataViewer.view_full()` over `FullData` |
| `view_training.py` | — (none defined) | 8050? | `frontend.training_dashboard.TrainingDashboard` (per task-03) |

**Open questions for plan owner (resolve before implementing):**
1. `view_training.py` has no compose service — add one (port 8050 is taken by `live`)?
2. `Dash.run()` port per script — `LiveDashboard.run(state_path)` does not take a port today; either add `port=` parameter or set via `DASH_PORT` env. Compose maps 8080/8090/8070 — the apps must bind accordingly.
3. `view_online_point.py` vs `view_onlineB.py` both render live state — confirm intended difference (sim-shared-state vs live-shared-state path?), they currently differ only by env file and port in compose.

## Files

- Modify: `view_online_point.py`, `view_full.py`, `view_onlineB.py`, `view_training.py` (root stubs)
- Modify: `frontend/live_dashboard.py`, `frontend/training_dashboard.py` (`run()` gains `host`/`port` params, default `0.0.0.0`/from `DASH_PORT` env)
- Test: `tests/test_view_entries.py`

## Steps

- [ ] **Step 1: Write the failing test** — for each entry: mock the dashboard class via `sys.modules`, import entry, call `main()`, assert instantiation + `run()` called with the state path from `shared_folder()`:

```python
def test_view_online_point_runs_live_dashboard(monkeypatch):
    # env: PAIR/ROOT_FOLDER/DATA_ROOT/DATA_SET_NAME per live.env
    ...
    import view_online_point
    view_online_point.main()
    mock_live_dashboard_cls.assert_called_once()
    mock_dashboard.run.assert_called_once()
    state_path = mock_dashboard.run.call_args.kwargs["state_path"]
    assert state_path.endswith("live_state.pkl")
```

- [ ] **Step 2: Verify RED.**

- [ ] **Step 3: Implement** — pattern for `view_online_point.py` (others analogous):

```python
"""view_online_point.py — live dashboard viewer (Docker path F)."""

import os


def main() -> None:
    from frontend.live_dashboard import LiveDashboard
    from helpers import shared_folder

    dashboard = LiveDashboard()
    dashboard.run(state_path=shared_folder() + "live_state.pkl")


if __name__ == "__main__":
    main()
```

`view_full.py`:

```python
"""view_full.py — historical data viewer (Docker path F)."""


def main() -> None:
    import pandas as pd

    from frontend.data_viewer import DataViewer, FullData
    from helpers import wide_df_path

    df = pd.read_pickle(wide_df_path())
    viewer = DataViewer(FullData(df))
    viewer.view_full()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Verify GREEN; full suite.**

- [ ] **Step 5: Docker verification:**

```bash
docker compose up view-full   # then curl/screenshot http://localhost:8080
```

Expected: Dash serves; chart renders from `df_with_indicators.pkl`. For `view-sim`: requires `live_state.pkl` from a running Robot (paper mode) — verify the polling page loads even when state file is absent (empty chart, no crash).

- [ ] **Step 6: Commit** — `feat: wire viewer entry points to frontend dashboards`
