# Task 03: TrainingDashboard

**Phase:** 12 — Frontend  
**Depends on:** Task 01 (ChartRenderer), Phase 08 (PerformanceAnalyzer output format)  
**Produces:** `frontend/training_dashboard.py` — real-time training progress visualization

---

## Goal

Implement `TrainingDashboard` — renders training pipeline progress: loss curves, trade P&L distribution, win rate over time. `view_online_point()` updates chart incrementally as training progresses.

---

## Context

Runs as a **separate process** alongside `Trainer`. `Trainer._run_train_nn()` writes epoch metrics to `shared/training_state.pkl` after each epoch; `Trainer._run_simulate()` writes simulation results after each worker completes. `TrainingDashboard` polls the shared file via `dcc.Interval` and re-renders charts as data arrives.

---

## Files

- Create: `frontend/training_dashboard.py`
- Create: `view_training.py` — entry point: instantiates `TrainingDashboard`, calls `run()`

---

## Interface

**`TrainingDashboard()`**

**`run(state_path: str = "shared/training_state.pkl") -> None`**
- Starts Dash app with `dcc.Interval` polling `state_path` every 2000ms
- Blocking — call from dedicated process

**`_update_charts(state: dict) -> list[go.Figure]`**
- `state` keys: `phase: "nn_train"|"simulate"`, `loss_history: list[float]`, `val_loss_history: list[float]`, `revenue_history: list[tuple]`, `win_rate: float|None`, `total_trades: int`
- Returns updated Plotly figures

**State dict schema** (written by Trainer):
```python
# During _run_train_nn() — appended after each epoch:
{
    "phase": "nn_train",
    "loss_history": [...],
    "val_loss_history": [...]
}
# During _run_simulate() — updated after each worker:
{
    "phase": "simulate",
    "revenue_history": [(pct, abs), ...],
    "win_rate": float,
    "total_trades": int
}
```

---

## Key Constraints

- `TrainingDashboard` runs in **separate process** from Trainer — Trainer never imports `frontend.*`
- Trainer writes `shared/training_state.pkl` atomically (write to `.tmp` then rename) after each epoch/worker
- Dash app polls file via `dcc.Interval(interval=2000)` — 2s refresh (training slower than live trading)
- Missing or unreadable state file → show empty charts, no crash
- Histograms use `plotly.graph_objects.Histogram` — no matplotlib/seaborn dependency

---

## Verification

```bash
docker compose -f docker-compose-view.yml run --rm viewer python3 -c "
from frontend.training_dashboard import TrainingDashboard
td = TrainingDashboard()
print('training_dashboard ok')
"
```

---

## Commit

`feat: implement TrainingDashboard with incremental loss curve and P&L visualization`
