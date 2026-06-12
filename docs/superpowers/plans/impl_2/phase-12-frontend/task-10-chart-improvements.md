# Task 10: Chart improvements — ADX, diff std bands, rangeslider, subplot sizing

**Phase:** 12 — Frontend  
**Depends on:** Tasks 05–09  
**Produces:** ADX indicator end-to-end; std-band derivative charts; fixed rangeslider; resized subplots  
**Status:** implemented (merged into `experimental_imp_2`)

---

## Goal

Four visual/UX fixes from dashboard review:

1. Visualise ADX.
2. Derivative charts show diff, its rolling mean, and mean ± rolling-std band.
3. RSI and volume subplots were hidden behind the candlestick rangeslider.
4. Rangeslider 3× smaller; non-OHLC subplots 1.5× taller.

---

## Context

The candlestick trace auto-enables a plotly rangeslider on the price x-axis; with stacked subplots it rendered over the volume and RSI rows. ADX did not exist anywhere in the indicator stack. The one-signed mean bands (`*_mean_above/below`) remain computed for signals/NN but are replaced on charts by the more conventional mean ± std envelope.

---

## Files

- Modify: `indicators/library/trend.py` — `ADXField` (talib ADX, `adx_14`)
- Modify: `indicators/library/price_derivatives.py` — `_DiffPrcRMStdSideBase` + 6 fields `{src}_diff_prc_rm_20_std_{above|below}`
- Modify: `indicators/registry.py`, `configs/indicators_config.yaml` — register/declare the 7 new fields
- Modify: `frontend/data_viewer.py` — `adx_14` in oscillator set (own `adx` subplot); derivative groups draw std bands (mean bands stay routable, not drawn); height 264/row
- Modify: `frontend/chart_renderer.py` — rangeslider + row weights (see Interface)

---

## Interface

**`ADXField(period: int = 14)`** — group `trend`, `talib.ADX(high, low, close)`, name `adx_{period}`.

**`_DiffPrcRMStdSideBase(window: int = 20)`** — name `{src}_diff_prc_rm_{w}_std_{side}`; `compute` = `rm ± diff.rolling(w).std()`; depends on `{src}_diff_prc` and `{src}_diff_prc_rm_{w}`.

**`ChartRenderer.create_figure`** changes:
- Row weights: price 0.60, every other row `1.5 * 0.40/(n-1)` (plotly normalizes); paired with 264 px/row figure height the price row keeps its pixel size while other rows grow 1.5×
- Rangeslider disabled on every axis, enabled on the bottom row only with `thickness=0.05` (a third of the plotly 0.15 default) — it can no longer overlap subplot rows

**Derivative chart lines per group:** `{src}_diff_prc`, `{src}_diff_prc_rm_20`, `{src}_diff_prc_rm_20_std_above`, `{src}_diff_prc_rm_20_std_below` (std bands muted colours).

---

## Key Constraints

- New columns require dataset re-preparation (`ohlc_gen`); until then skip-if-absent hides ADX/std traces without error
- `*_mean_above/below` fields stay in config/registry (signal/NN consumers) and stay routable to their diff subplot for explicit indicator lists
- Legacy `view_full()` defaults unchanged

---

## Verification

```bash
docker compose run --rm --no-deps -T live python -m pytest tests/test_phase12_task10_chart_improvements.py -q
```

Live: serve `view_full.py`, confirm rangeslider sits at figure bottom (thickness 0.05), volume/RSI fully visible, non-price rows ~1.5× previous pixel height.

---

## Commit

`feat: ADX indicator, diff std bands, slim bottom rangeslider, 1.5x subplots`
