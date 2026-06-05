# Task 03: TrainingDashboard

**Phase:** 12 — Frontend  
**Depends on:** Task 01 (ChartRenderer), Phase 08 (PerformanceAnalyzer output format)  
**Produces:** `frontend/training_dashboard.py` — real-time training progress visualization

---

## Goal

Implement `TrainingDashboard` — renders training pipeline progress: loss curves, trade P&L distribution, win rate over time. `view_online_point()` updates chart incrementally as training progresses.

---

## Context

Called by `Trainer._run_train_nn()` and `Trainer._run_simulate()` to provide visual feedback during long training runs. Uses matplotlib's interactive mode for incremental updates — not a web dashboard. Separate process or subprocess may render while training runs in main process.

---

## Files

- Create: `frontend/training_dashboard.py`

---

## Interface

**`TrainingDashboard()`**

Attributes:
- `renderer: ChartRenderer`
- `loss_history: list[float]`
- `val_loss_history: list[float]`
- `trade_pnl_history: list[float]`
- `win_rate_history: list[float]`

**`view_online_point(metrics: dict) -> None`**
- Appends `metrics['loss']`, `metrics['val_loss']` to histories
- Re-renders loss subplot with updated histories
- Calls `plt.pause(0.01)` for interactive update

**`view_simulation_result(result: dict) -> None`**
- Renders `PerformanceAnalyzer` output:
  - P&L distribution histogram
  - Cumulative revenue curve
  - Win rate trend

**`show_final(performance: dict) -> None`**
- Renders final training summary: all metrics at once, no live updates
- Calls `renderer.show()` (blocking)

---

## Key Constraints

- `plt.ion()` called at construction for interactive mode
- `view_online_point()` non-blocking — never hangs training loop
- Histograms use `matplotlib.pyplot.hist()` — no seaborn dependency
- `TrainingDashboard` created in main process — not spawned as subprocess
- Thread safety: `view_online_point()` must be called from main thread only (matplotlib GUI constraint)

---

## Verification

```bash
docker compose run --rm viewer python3 -c "
from frontend.training_dashboard import TrainingDashboard
td = TrainingDashboard()
td.view_online_point({'loss': 0.5, 'val_loss': 0.6})
print('training_dashboard ok')
"
```

---

## Commit

`feat: implement TrainingDashboard with incremental loss curve and P&L visualization`
