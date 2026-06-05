# Task 02: DataViewer

**Phase:** 12 — Frontend  
**Depends on:** Task 01 (ChartRenderer), Phase 03 Task 07 (FullData), Phase 03 Task 08 (Levels)  
**Produces:** `frontend/data_viewer.py` — static historical data visualization

---

## Goal

Implement `DataViewer` — renders historical OHLCV + indicators + levels for analysis. Two modes: `view_full` (full dataset) and `view_full_levels` (with drawn level overlays).

---

## Context

Used by researchers reviewing training data and indicator quality. Not real-time — operates on `FullData` (loaded from `df_with_indicators.pkl`). Renders candles plus all configured indicator subplots plus level lines.

---

## Files

- Create: `frontend/data_viewer.py`

---

## Interface

**`DataViewer(full_data: FullData, tf: int = 15)`**

Attributes:
- `full_data: FullData`
- `tf: int` — primary timeframe for display
- `renderer: ChartRenderer`

**`view_full(start_idx: int = 0, end_idx: int = None, indicators: list[str] = None) -> None`**
- Builds subset of `full_data` from `start_idx` to `end_idx`
- Calls `renderer.setup_layout(["price", "volume"] + indicator_subplots)`
- Draws candles from `{tf}_open/high/low/close` columns
- Draws each indicator in `indicators` list as line on appropriate subplot
- Calls `renderer.show()`

**`view_full_levels(start_idx: int = 0, end_idx: int = None, levels: Levels = None) -> None`**
- Same as `view_full()` plus: calls `renderer.draw_level()` for each level in `levels.get_all()`

**`save_chart(path: str, start_idx: int = 0, end_idx: int = None) -> None`**
- Renders and saves to `path` without `show()`

---

## Key Constraints

- Indicator subplot mapping: RSI/CCI on separate axis, EMAs on price axis, volume on volume axis
- `indicators=None` defaults to `["rsi_14", "cci_14"]` for primary TF
- Column access uses TF prefix: `f"{tf}_rsi_14"` — not raw column name
- Slice `start_idx:end_idx` on the wide DataFrame index — integer row slicing, not timestamp
- `DataViewer` is read-only — never modifies `full_data`

---

## Verification

```bash
docker compose run --rm viewer python3 -c "
from frontend.data_viewer import DataViewer
print('data_viewer importable')
"
```

---

## Commit

`feat: implement DataViewer for static historical chart rendering with level overlays`
