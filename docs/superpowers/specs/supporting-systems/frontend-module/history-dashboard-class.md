# HistoryDashboard Class Specification

**Class:** `HistoryDashboard` (interactive evolution of view_full.py)  
**Files:** `frontend/history_dashboard.py`, `view_full.py` (entry point)  
**Purpose:** Interactive Dash viewer for the backtesting dataset: date-windowed, multi-timeframe charts with full indicator panels.

---

## 1. Class Overview

The `HistoryDashboard` class serves the prepared backtesting dataset (`df_with_indicators.pkl`, loaded as `FullData`) as an interactive web app. The user selects a start date, a number of days, and a set of timeframes; the dashboard renders one chart group per selected timeframe. Each group contains the OHLC candlestick chart with price-axis indicator overlays, oscillator subplots, and price-derivative subplots.

It replaces the static `DataViewer.view_full()` → `fig.show()` flow for dataset review. `DataViewer` remains the figure factory; `HistoryDashboard` owns the Dash app and callbacks — the same split `LiveDashboard` uses.

---

## 2. Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `full_data` | `FullData` | Wide multi-TF DataFrame container (read-only) |
| `tf` | `int` | Primary timeframe, initial selection (default: 15) |
| `viewer` | `DataViewer` | Figure construction delegate |
| `_app` | `dash.Dash` | Dash application, built in constructor |

---

## 3. Constructor

### `__init__(full_data, tf=15)`

**Parameters:**
- `full_data` (`FullData`) — Wide DataFrame container
- `tf` (`int`) — Initial timeframe selection. Default: 15

**Behavior:**
1. Store `full_data`, `tf`
2. Create `DataViewer(full_data, tf)`
3. Build Dash app: layout + callbacks

---

## 4. Layout & Controls

| Control | Component | Behavior |
|---------|-----------|----------|
| Start date | `dcc.DatePickerSingle(id="start-date")` | From which day data is shown; bounded by df index range |
| Days shown | `dcc.Input(id="days", type="number", min=1)` | Window length in days from start date |
| Timeframes | `dcc.Checklist(id="timeframes")` | Multi-select; options discovered from `{tf}_close` columns, labels `1m/5m/15m/1h/4h/1d` |
| Chart groups | `html.Div(id="chart-groups")` | One `dcc.Graph` per selected TF, ascending TF order |

### Chart group contents (per selected timeframe)

| Subplot | Series |
|---------|--------|
| price | candles; Bollinger variants (`bb_*`), EMAs (`ema_7/14/25/50/100`), SAR (`sar_002_02`, markers) |
| volume | volume line |
| rsi | `rsi_14`, `rsi_ma8`, `rsi_ma12`, `rsi_ma24` |
| cci | `cci_14`, `cci_14_ma_20` |
| macd_12_26_9 | line + signal + histogram (bars) |
| macd_5_13_9 | line + signal |
| adx | `adx_14` |
| close_diff | `close_diff_prc` + `rm_20` + `rm_20_std_above`/`rm_20_std_below`, zero line |
| high_diff | same pattern for high |
| low_diff | same pattern for low |
| rsi_diff | `rsi_ma8/12/24_diff`, zero line |

Each oscillator's / derivative's moving-average lines draw on the same subplot as the source series. Derivative bands are mean ± rolling std (the one-signed `*_mean_above/below` fields stay computed but are not drawn by default). Trace visibility is toggled via the plotly legend.

### Figure layout

- Row weights: price 0.60, every other row `1.5 × 0.40/(n−1)`; figure height 264 px/row — price row keeps constant pixel size, other rows 1.5× their pre-task-10 size
- Rangeslider: disabled on all axes, slim one (`thickness=0.05`) on the bottom row only — never overlaps volume/RSI rows
- Each candle plots at its period open timestamp and spans the full TF width

---

## 5. Key Methods & Interfaces

### `run()`

**Purpose:** Start the Dash app. Blocking.

**Behavior:** Binds `0.0.0.0:$DASH_PORT` (default 8080) — compose port mapping cannot reach the Dash default 127.0.0.1:8050 inside the container. Served via the `view-full` compose service.

### Callback: `(start-date, days, timeframes) → chart-groups`

**Behavior:**
1. For each selected TF: slice `full_data.df.loc[start : start + days]` (DatetimeIndex slicing; naive picker dates are localized to the tz-aware UTC index)
2. Drop per-TF duplicate/NaN rows so higher-TF candles render one per period; re-index each kept row to its period **open** timestamp (values from the period's last row) so candles plot at open time and span the full TF width
3. Build figure via `DataViewer.build_window_figure(start, days, tf=tf)`
4. Return one `dcc.Graph` per TF

### `DataViewer.build_window_figure(start, days, indicators=None, tf=None)`

**Purpose:** Date-window figure factory used by the dashboard (returns `go.Figure`, never shows). `tf` overrides the viewer's primary timeframe per figure.

---

## 6. Error Handling

**Empty slice:**
- Empty date window → empty `go.Figure` with "no data in range" annotation; never an exception

**Missing indicator columns:**
- Datasets prepared with older `indicators_config.yaml` render fine — every indicator series is skip-if-absent

---

## 7. Potential Improvements

1. **Indicator on/off controls** — checklist per chart group instead of legend-only toggling
2. **Shared x-axis sync across TF groups** — zoom on one TF re-windows the others
3. **Trade/level overlays** — merge `view_full_levels` and simulation trade marks into the same app
4. **Lazy slicing** — load only the visible window for multi-year datasets
5. **Deep linking** — encode date/days/TF selection in query string
