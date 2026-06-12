# Task 07: Price-axis indicator overlays — Bollinger, EMAs, SAR

**Phase:** 12 — Frontend  
**Depends on:** Task 06 (timeframe selection)  
**Produces:** indicator overlays on each TF's OHLC chart in `HistoryDashboard`

---

## Goal

On every timeframe's candlestick chart, render the indicators that live on the price axis: all configured Bollinger Band variants, the EMA set, and Parabolic SAR.

---

## Context

These columns are computed per TF by the prepare stage (`configs/indicators_config.yaml`) and already sit in the wide df. The existing `_PRICE_AXIS_PREFIXES` routing in `data_viewer.py` (`ema`, `sma`, `bb`, `vwap`) puts band/MA lines on the price subplot; SAR has no routing yet and must render as markers, not a line.

Configured price-axis fields:

- Bollinger: `bb_upper_20_2`, `bb_middle_20_2`, `bb_lower_20_2`, `bb_upper_10_15`, `bb_lower_10_15`, `bb_upper_20_3`, `bb_lower_20_3`
- EMAs: `ema_7`, `ema_14`, `ema_25`, `ema_50`, `ema_100`
- SAR: `sar_002_02`

---

## Files

- Modify: `frontend/data_viewer.py` — default price-overlay indicator set, SAR routing
- Modify: `frontend/chart_renderer.py` — only if a marker-series primitive is missing (`draw_marker` exists; reuse it)

---

## Interface

**`DataViewer`**

- `_PRICE_OVERLAYS: list[str]` — the field list above; `build_window_figure()` draws every member present in the df for the figure's TF, silently skipping absent columns
- SAR routing: indicator names starting with `sar` draw via `renderer.draw_marker(fig, times, values, marker_symbol="circle", ...)` on the price row — dots above/below price, never connected by a line
- Bollinger variants share one colour per variant (upper/middle/lower of `20_2` visually grouped); EMAs get distinct colours; legend label = field name

---

## Key Constraints

- Skip-if-absent: a dataset prepared with an older `indicators_config.yaml` must still render — missing columns are not an error
- Overlays draw on the price subplot of the existing per-TF figure — no new subplots in this task
- Legend entries toggle visibility per trace (plotly default) — that is the user's on/off control; no extra UI
- NaN warm-up rows render as gaps (plotly default), not dropped

---

## Verification

```bash
LONG_ENV=configs/long_dataset.env docker compose up -d view-full
curl -sf http://localhost:8080 >/dev/null && echo "serving"
docker compose down view-full
```

Manual: on the 15m chart confirm bands envelope price, EMAs track close, SAR renders as dots flipping sides on trend reversal.

---

## Commit

`feat: render Bollinger, EMA, and SAR overlays on per-TF price charts`
