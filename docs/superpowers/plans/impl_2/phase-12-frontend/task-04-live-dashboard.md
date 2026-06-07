# Task 04: LiveDashboard

**Phase:** 12 — Frontend  
**Depends on:** Task 01 (ChartRenderer)  
**Produces:** `frontend/live_dashboard.py` — real-time live trading visualization

---

## Goal

Implement `LiveDashboard` — renders live trading state: streaming price candles, current position, stop-loss level, trade markers, and running P&L. Reads shared pickle written by Robot; runs as a separate Dash process.

---

## Context

Execution path F (viewer). Robot writes a state snapshot dict to a shared pickle file (`shared/live_state.pkl`) on each tick. `LiveDashboard` runs in a **separate process** from Robot — it polls the shared file via `dcc.Interval` to update charts. Dashboard maintains rolling window of N candles. Displays entry/exit markers when trades execute.

---

## Files

- Create: `frontend/live_dashboard.py`
- Create: `view_online_point.py` — entry point: instantiates `LiveDashboard`, calls `run()`

---

## Interface

**`LiveDashboard(window_size: int = 200, tf: int = 15)`**

Attributes:
- `renderer: ChartRenderer`
- `window_size: int` — max candles to display
- `tf: int`
- `candle_buffer: deque` — rolling buffer of OHLCV dicts
- `trade_markers: list[dict]` — entry/exit events to draw

**`run(state_path: str = "shared/live_state.pkl") -> None`**
- Starts Dash app with `dcc.Interval` polling `state_path` every 1000ms
- On each interval: reads pickle, calls `_update_charts(state)`
- Blocking — call from dedicated process

**`_update_charts(state: dict) -> list[go.Figure]`**
- `state` keys: `candles: list[dict]` (OHLCV dicts), `position: dict`, `trade_markers: list[dict]`, `revenue_history: list[tuple]`
- Returns updated Plotly figures for all chart components

**State dict schema** (written by Robot):
```python
{
    "candles": [{"time": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}, ...],
    "position": {"is_open": bool, "direction": str, "stop_loss": float | None},
    "trade_markers": [{"type": "buy"|"sell"|"stop_loss", "time": ..., "price": float}],
    "revenue_history": [(revenue_pct, revenue_abs), ...]
}
```

---

## Key Constraints

- `LiveDashboard` runs in **separate process** from Robot — Robot never imports `frontend.*`
- Robot writes `shared/live_state.pkl` atomically (write to `.tmp` then rename) each tick
- Dash app polls file via `dcc.Interval(interval=1000)` — 1s refresh
- Stop-loss drawn from `state["position"]["stop_loss"]` — only when `is_open=True`
- Position overlay: background shape color (green=long, red=short, gray=flat) via Plotly `fig.add_vrect()`
- Candle window capped at `window_size` — LiveDashboard trims `state["candles"]` list on read

---

## Verification

```bash
docker compose -f docker-compose-view.yml run --rm viewer python3 -c "
from frontend.live_dashboard import LiveDashboard
ld = LiveDashboard(window_size=100, tf=15)
print('live_dashboard ok')
"
```

---

## Commit

`feat: implement LiveDashboard with rolling candle window and real-time position overlay`
