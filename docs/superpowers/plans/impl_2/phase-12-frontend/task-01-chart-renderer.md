# Task 01: ChartRenderer

**Phase:** 12 — Frontend  
**Depends on:** Phase 03 (DataPoint, FullData), Phase 03 Task 08 (Levels)  
**Produces:** `frontend/chart_renderer.py` — base chart rendering primitives

---

## Goal

Implement `ChartRenderer` — base class providing shared chart layout, OHLCV candlestick rendering, indicator overlay helpers, and marker placement API used by all viewer subclasses.

---

## Context

All visualization classes (`DataViewer`, `TrainingDashboard`, `LiveDashboard`) compose `ChartRenderer` to build Plotly figures. `ChartRenderer` is a pure figure factory — it builds and returns `go.Figure` objects. It has no Dash app; dashboards own the app and pass figures to `dcc.Graph`. `DataViewer` calls `fig.show()` directly (opens browser).

---

## Files

- Create: `frontend/chart_renderer.py`
- Create: `frontend/__init__.py` (empty)

---

## Interface

**`ChartRenderer(title: str = "")`**

Attributes:
- `title: str`

**`create_figure(subplots: list[str]) -> go.Figure`**
- Calls `make_subplots(rows=len(subplots), ...)` — `"price"` row gets 60% of vertical space, others share remainder
- Returns configured `go.Figure`; caller stores it
- `subplots` order maps to row numbers: `subplot_rows: dict[str, int]` stored on the returned figure via `fig._subplot_rows` attribute

**`draw_candles(fig: go.Figure, times: list, opens: list, highs: list, lows: list, closes: list) -> None`**
- Adds `go.Candlestick` trace to row `fig._subplot_rows["price"]`
- Green/red candle colors via `increasing_line_color` / `decreasing_line_color`

**`draw_line(fig: go.Figure, subplot: str, times: list, values: list, label: str, color: str = "blue") -> None`**
- Adds `go.Scatter(mode="lines")` to row `fig._subplot_rows[subplot]`

**`draw_marker(fig: go.Figure, times: list, prices: list, marker_symbol: str, color: str, label: str = "") -> None`**
- Adds `go.Scatter(mode="markers")` to price row

**`draw_level(fig: go.Figure, price: float, label: str, color: str = "gray") -> None`**
- Calls `fig.add_hline(y=price, ...)` on price row

**`save(fig: go.Figure, path: str) -> None`**
- Calls `fig.write_image(path)` — saves as PNG (requires `kaleido`)

---

## Key Constraints

- All draw methods are additive and stateless — pass `fig` in, add traces, return nothing
- `fig._subplot_rows` is a plain `dict[str, int]` set by `create_figure()` — callers must not mutate it
- `create_figure()` called once per render cycle; pass resulting `fig` to all draw methods
- `save()` requires `kaleido` package — add to viewer image requirements
- No matplotlib imports anywhere in `frontend/` — Plotly only

---

## Verification

```bash
docker compose -f docker-compose-view.yml run --rm viewer python3 -c "
from frontend.chart_renderer import ChartRenderer
cr = ChartRenderer(title='Test')
fig = cr.create_figure(['price', 'volume'])
print('chart_renderer ok, subplot rows:', fig._subplot_rows)
"
```

---

## Commit

`feat: implement ChartRenderer base with candlestick, line, marker, and level primitives`
