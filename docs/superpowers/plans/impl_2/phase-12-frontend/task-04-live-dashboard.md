# Task 04: LiveDashboard

**Phase:** 12 — Frontend  
**Depends on:** Task 01 (ChartRenderer), Phase 03 Task 05 (LiveData), Phase 06 (Position facade)  
**Produces:** `frontend/live_dashboard.py` — real-time live trading visualization

---

## Goal

Implement `LiveDashboard` — renders live trading state: streaming price candles, current position, stop-loss level, signal markers, and running P&L. `view_onlineB()` called per tick from Robot.

---

## Context

Execution path F (viewer). Robot calls `view_onlineB(data_point, position)` on each tick to keep dashboard current. Dashboard maintains rolling window of N candles. Displays entry/exit markers when trades execute. Runs in separate process from Robot to avoid blocking polling loop.

---

## Files

- Create: `frontend/live_dashboard.py`

---

## Interface

**`LiveDashboard(window_size: int = 200, tf: int = 15)`**

Attributes:
- `renderer: ChartRenderer`
- `window_size: int` — max candles to display
- `tf: int`
- `candle_buffer: deque` — rolling buffer of OHLCV dicts
- `trade_markers: list[dict]` — entry/exit events to draw

**`view_onlineB(data_point, position: Position) -> None`**
- Extracts OHLCV from `data_point.get(col, tf, 0)` for price/open/high/low/close/volume
- Appends to `candle_buffer` (pops oldest if over `window_size`)
- Re-renders: candles + indicators + current stop-loss level + position state overlay
- Calls `plt.pause(0.01)` for non-blocking update

**`add_trade_marker(event_type: str, time, price: float) -> None`**
- `event_type`: `"buy"`, `"sell"`, `"stop_loss"`
- Appends to `trade_markers`; drawn on next `view_onlineB()` call

**`clear_markers() -> None`**
- Clears `trade_markers` list

**`show_pnl_summary(revenue_history: list[tuple]) -> None`**
- Renders running P&L subplot using `revenue_history` from Robot

---

## Key Constraints

- `candle_buffer` is `collections.deque(maxlen=window_size)` — O(1) append/pop
- `view_onlineB()` must complete in < 100ms — no heavy computation inside
- Stop-loss level drawn as horizontal line from `position.posImpl.price_stop_loss` — only when position open
- `plt.ion()` called at construction
- `LiveDashboard` runs in same process as Robot — non-blocking updates mandatory
- Position state overlay: color-coded background (green=long open, red=short open, gray=flat)

---

## Verification

```bash
docker compose run --rm viewer python3 -c "
from frontend.live_dashboard import LiveDashboard
ld = LiveDashboard(window_size=100, tf=15)
print('live_dashboard ok, buffer maxlen:', ld.candle_buffer.maxlen)
"
```

---

## Commit

`feat: implement LiveDashboard with rolling candle window and real-time position overlay`
