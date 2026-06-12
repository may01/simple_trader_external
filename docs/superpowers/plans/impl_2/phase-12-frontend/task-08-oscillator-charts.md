# Task 08: Oscillator charts — RSI, CCI, MACD with their moving averages

**Phase:** 12 — Frontend  
**Depends on:** Task 06 (timeframe selection)  
**Produces:** RSI / CCI / MACD subplots with MA overlays in each TF chart group

---

## Goal

Under every timeframe's candlestick chart, render three oscillator subplots: RSI with its moving averages, CCI with its moving average, and MACD. Each oscillator's MA lines draw on the same subplot as the oscillator itself.

---

## Context

The `_INDICATOR_SUBPLOT` routing in `data_viewer.py` already sends `rsi*`/`cci*`/`macd*` to named subplots, but the default indicator set is only `["rsi_14", "cci_14"]` and MACD needs bar rendering for the histogram, which `ChartRenderer` lacks.

Configured oscillator fields:

- RSI subplot: `rsi_14`, `rsi_ma8`, `rsi_ma12`, `rsi_ma24`
- CCI subplot: `cci_14`, `cci_14_ma_20`
- MACD subplot(s): `macd_12_26_9` + `macd_signal_12_26_9` + `macd_hist_12_26_9`; second variant `macd_5_13_9` + `macd_signal_5_13_9` on its own subplot

---

## Files

- Modify: `frontend/data_viewer.py` — oscillator default set, MACD histogram routing
- Modify: `frontend/chart_renderer.py` — add `draw_bar`

---

## Interface

**`ChartRenderer.draw_bar(fig: go.Figure, subplot: str, times: list, values: list, label: str, color: str = "gray") -> None`**
- Adds `go.Bar` trace to row `fig._subplot_rows[subplot]` — same additive/stateless contract as `draw_line`

**`DataViewer`**

- `_OSCILLATORS: list[str]` — the field list above; drawn for every TF figure, skip-if-absent
- Routing additions to `_INDICATOR_SUBPLOT`: `rsi_ma*` → `rsi` subplot (current base-name split would route them to subplot `rsi` already — verify, don't assume), `cci_14_ma_20` → `cci`, `macd_signal_12_26_9`/`macd_hist_12_26_9` → `macd_12_26_9`, `macd_5_13_9`/`macd_signal_5_13_9` → `macd_5_13_9`
- `macd_hist_*` draws via `draw_bar`; all other oscillator fields via `draw_line`
- Subplot order under price/volume: `rsi`, `cci`, `macd_12_26_9`, `macd_5_13_9`

---

## Key Constraints

- MA lines share the subplot of their oscillator — RSI MAs never land on a separate subplot
- `rsi_ma8_diff` / `rsi_ma12_diff` / `rsi_ma24_diff` are NOT part of this task — they are derivative fields (Task 09)
- Skip-if-absent per column, same rule as Task 07
- Subplot heights: price keeps its 60% share (`create_figure` contract from Task 01); oscillators share the remainder equally

---

## Verification

```bash
LONG_ENV=configs/long_dataset.env docker compose up -d view-full
curl -sf http://localhost:8080 >/dev/null && echo "serving"
docker compose down view-full
```

Manual: 15m group shows four oscillator subplots; RSI panel has 4 lines (rsi_14 + 3 MAs), CCI panel 2 lines, MACD panels show line + signal + histogram bars.

---

## Commit

`feat: add RSI/CCI/MACD oscillator subplots with moving averages per timeframe`
