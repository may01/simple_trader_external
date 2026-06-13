# Task 13: Chart UX — OHLC range navigator, volume bars, RSI class markers

**Phase:** 12 — Frontend
**Depends on:** Task 12 (subplot selection)
**Produces:** rangeslider that always previews OHLC, bar-chart volume, move/zone class markers on the rsi_ma8 line

---

## Goal

Three chart improvements:

1. The range selector always shows OHLC inside it, never an indicator.
2. Volume renders as bars.
3. `move_class` and `zone_class` render as markers on the `rsi_ma8` line they are computed from.

---

## Context

Plotly's rangeslider previews the traces of the axis it is attached to — previously the last subplot row, i.e. whatever indicator sorted last. A dedicated short "range" row holding a second candlestick copy fixes the preview permanently.

Both class fields (`indicators/library/classification.py`) draw at the `rsi_ma8` y-value: `move_class` buckets `rsi_ma8_diff` momentum (−2..2), `zone_class` buckets the `rsi_ma8` level (0..4) — see task-15. The open diamond rings the move-class dot, so both read without occlusion.

---

## Files

- Modify: `frontend/chart_renderer.py` — `create_figure(range_row=...)`, `draw_candles(subplot=...)`, `draw_marker(subplot=..., size=...)`
- Modify: `frontend/data_viewer.py` — range-row candles, `draw_bar` volume, `_draw_rsi_class_markers`
- Add: `tests/test_phase12_task13_chart_ux.py`

---

## Interface

**`ChartRenderer`**

- `create_figure(subplots, range_row=False)` — appends an untitled "range" row (weight 0.15, hidden y-axis); the slim rangeslider attaches to it instead of the last regular row
- `draw_candles(..., subplot="price")` — navigator candles via `subplot="range"`, legend entry suppressed off-price
- `draw_marker(..., subplot="price", size=None)` — markers on any subplot

**`DataViewer`**

- `_build_figure(..., range_row=False)`; `build_window_figure` always passes `range_row=True` and draws a second candlestick copy into the range row; no indicators there
- Volume: `draw_bar` instead of `draw_line`
- `_RSI_CLASS_MARKERS`: `move_class` circles (size 6), `zone_class` open diamonds (size 11); bucket colours red/orange/lightgreen/green low→high; one trace per (field, value), y-values from `{tf}_rsi_ma8`

---

## Key Constraints

- Skip-if-absent everywhere: missing class/rsi_ma8 columns or a hidden rsi subplot draw nothing
- Legacy `view_full*`/`save_chart` paths keep the old layout (no range row)
- Legend toggling remains the per-trace on/off control

---

## Verification

```bash
docker run --rm -v "$PWD":/code -w /code simple_trader \
  python3 -m pytest tests/test_phase12_task13_chart_ux.py -q
```

Manual: rangeslider preview shows candles on every TF regardless of subplot selection; volume is bars; rsi subplot shows colored dots ringed by diamonds on the rsi_ma8 line.

---

## Commit

`feat: OHLC range-row navigator, volume bars, RSI class markers`
