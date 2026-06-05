# Task 01: ChartRenderer

**Phase:** 12 — Frontend  
**Depends on:** Phase 03 (DataPoint, FullData), Phase 03 Task 08 (Levels)  
**Produces:** `frontend/chart_renderer.py` — base chart rendering primitives

---

## Goal

Implement `ChartRenderer` — base class providing shared chart layout, OHLCV candlestick rendering, indicator overlay helpers, and marker placement API used by all viewer subclasses.

---

## Context

All visualization classes (`DataViewer`, `TrainingDashboard`, `LiveDashboard`) inherit from `ChartRenderer` or compose it. Uses matplotlib (or plotly if project standard) for rendering. `ChartRenderer` draws OHLCV and indicator subplots; subclasses add domain-specific overlays (levels, signals, trades).

---

## Files

- Create: `frontend/chart_renderer.py`
- Create: `frontend/__init__.py` (empty)

---

## Interface

**`ChartRenderer(title: str = "", figsize: tuple = (20, 12))`**

Attributes:
- `fig` — matplotlib Figure
- `axes: dict[str, Axes]` — named subplot axes: `"price"`, `"volume"`, `"rsi"`, etc.
- `title: str`

**`setup_layout(subplots: list[str]) -> None`**
- Creates Figure with named subplots stacked vertically
- Price subplot takes majority of vertical space

**`draw_candles(times: list, opens: list, highs: list, lows: list, closes: list) -> None`**
- Renders OHLCV candlestick chart on `axes["price"]`
- Green candles for up, red for down

**`draw_line(ax_name: str, times: list, values: list, label: str, color: str = "blue", linewidth: float = 1.0) -> None`**
- Draws line series on named subplot axis

**`draw_marker(time, price: float, marker: str, color: str, label: str = "") -> None`**
- Places marker on price axis (used for signal/trade entry/exit markers)

**`draw_level(price: float, label: str, color: str = "gray", linestyle: str = "--") -> None`**
- Draws horizontal level line across price axis

**`show() -> None`**
- Calls `plt.tight_layout()`, `plt.show()`

**`save(path: str) -> None`**
- Saves figure to `path` as PNG

---

## Key Constraints

- `axes` dict keyed by string name — subclasses use `self.axes["price"]` not index
- All draw methods are additive — call in any order, render on `show()`/`save()`
- Thread safety: `ChartRenderer` not thread-safe; create one instance per render thread
- `draw_candles()` does not clear existing canvas — call `setup_layout()` first on each new render
- Matplotlib is primary rendering library; do not mix with plotly in same class

---

## Verification

```bash
docker compose run --rm viewer python3 -c "
from frontend.chart_renderer import ChartRenderer
cr = ChartRenderer(title='Test')
cr.setup_layout(['price', 'volume'])
print('chart_renderer ok, axes:', list(cr.axes.keys()))
"
```

---

## Commit

`feat: implement ChartRenderer base with candlestick, line, marker, and level primitives`
