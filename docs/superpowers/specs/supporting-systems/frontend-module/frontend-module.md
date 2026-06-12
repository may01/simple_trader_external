# Frontend Module Specification

**Module:** Frontend  
**Files:** `view_*.py` files (view_full.py, view_simulation.py, view_online.py, view_predict.py, etc.)  
**Purpose:** Visualize trading data, signals, strategy performance, and live trading via interactive Dash dashboards.

---

## 1. Overview

The Frontend Module provides interactive web-based dashboards for analyzing trading data and strategy performance. Built on Plotly and Dash, it enables:

- **Historical Data Viewer:** Display OHLC candles with technical indicators and trading signals — interactive via `HistoryDashboard` (start-date + days window, multi-timeframe chart groups, full indicator panels; see `history-dashboard-class.md`)
- **Simulation Viewer:** Replay backtests with trade marks and performance metrics
- **Live Dashboard:** Real-time market data and open positions
- **Prediction Viewer:** Display price predictions and forecast confidence

The module is designed for exploratory analysis—users can drill down into data, toggle indicators on/off, adjust timeframes, and identify trading patterns visually.

Key design: Viewers are independent Dash apps that can run standalone or be combined into a unified dashboard. Each viewer accepts parameters via query strings, allowing deep linking to specific analyses.

---

## 2. Module Boundaries

### Upstream Dependencies
- **Data Module:** Loads OHLC candles and indicators
- **Backtest Results:** SimulationResult for trade replay
- **Position Data:** Current positions and trades
- **Levels Module:** Support/resistance levels
- **Signals Module:** Signal evaluation for overlay
- **NN Module:** Neural network predictions for visualization

### Downstream Consumers
- Web browsers (traders viewing dashboards)
- Embedded analysis (notebooks using viewer code)
- Integration with monitoring systems

### Key Interfaces
- **ChartRenderer.render_candlestick()** — Draw OHLC with indicators
- **DataViewer.display_candles()** — Show candle data with controls
- **HistoryDashboard.run()** — Interactive dataset review: date window, timeframe multi-select, per-TF indicator chart groups
- **TrainingDashboard.display_results()** — Show backtest statistics
- **LiveDashboard.display_positions()** — Real-time position monitoring

---

## 3. Data Flow

```
┌─────────────────────────────────────────────────┐
│      User Requests Analysis                     │
│  (Selects timeframe, indicators, date range)    │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
        ┌─────────────────────────┐
        │  DataViewer             │
        │  ├─ Load candle data    │
        │  ├─ Load signals        │
        │  └─ Load indicators     │
        └────────────┬────────────┘
                     │
                     ▼
        ┌─────────────────────────┐
        │  ChartRenderer          │
        │  ├─ Draw candlesticks   │
        │  ├─ Add indicator lines │
        │  └─ Mark signals        │
        └────────────┬────────────┘
                     │
                     ▼
        ┌─────────────────────────┐
        │  Plotly Figure          │
        └────────────┬────────────┘
                     │
                     ▼
        ┌─────────────────────────┐
        │  Dash Interactive UI    │
        │  ├─ Dropdown selectors  │
        │  ├─ Zoom/pan controls   │
        │  └─ Info popups         │
        └────────────┬────────────┘
                     │
                     ▼
        ┌─────────────────────────┐
        │  Browser Rendering      │
        │  (Trader Views Charts)  │
        └─────────────────────────┘
```

---

## 4. Execution Flow

### A. DataViewer.display_candles()

1. Parse parameters from URL/callback (timeframe, date range, pair)
2. Load OHLC candles from disk
3. Load technical indicators for selected timeframe
4. Load signals for this time window
5. Optional: Load levels (support/resistance)
6. Format data for rendering
7. Call ChartRenderer.render_candlestick()
8. Add interactive controls (dropdowns, sliders)
9. Return Dash layout

### B. ChartRenderer.render_candlestick()

1. Create Plotly figure with candlestick trace
2. For each selected indicator:
   - Extract values for timeframe
   - Add line/scatter trace
   - Color-code by signal state
3. Mark trade entries/exits with annotations
4. Add volume bar chart as subplot
5. Add horizontal lines for levels
6. Set axes labels, title, range
7. Configure hover templates
8. Return figure

### C. TrainingDashboard.display_results()

1. Load backtest results from pickle
2. Compute statistics (Sharpe, drawdown, win rate)
3. Extract trade-by-trade details
4. Create subplot figure:
   - Equity curve (top)
   - Drawdown chart (middle)
   - Trade distribution histogram (bottom)
5. Overlay trade marks on equity curve
6. Create summary statistics table
7. Return dashboard layout

---

## 5. Key Components

### DataViewer Class
Loads and provides data for visualization.

**Methods:**
- `load_candles(pair, timeframe, date_range)` — Load OHLC data
- `load_signals(pair, timeframe, date_range)` — Load signal values
- `load_levels(pair, date_range)` — Load support/resistance
- `get_data_point(pair, timestamp)` — Fetch single data point

### ChartRenderer Class
Renders data as interactive Plotly figures.

**Methods:**
- `render_candlestick(ohlc_data, indicators, signals, levels)` — Main chart
- `render_indicators(ohlc_data, indicator_list)` — Indicator panel
- `render_trade_marks(trades, start, end)` — Entry/exit annotations
- `add_hover_template(figure)` — Interactive tooltips

### TrainingDashboard Class
Displays backtest analysis dashboard.

**Methods:**
- `display_results(result)` — Full result visualization
- `display_equity_curve(result)` — Equity curve chart
- `display_trade_analysis(result)` — Trade statistics
- `display_comparison(results_list)` — Compare multiple backtests

### HistoryDashboard Class
Interactive Dash viewer for the prepared backtesting dataset (see `history-dashboard-class.md`).

**Controls:**
- Start-date picker — from which day data is shown
- Days input — how many days are shown
- Timeframe multi-select — one chart group per selected TF

**Per-TF chart group:** OHLC candles with Bollinger/EMA/SAR overlays; RSI, CCI, MACD subplots each with their moving averages; close/high/low diff and rsi_diff derivative subplots each with rolling means.

### LiveDashboard Class
Real-time monitoring dashboard.

**Methods:**
- `display_positions(robot)` — Current open positions
- `display_execution_log(robot)` — Recent trades
- `display_market_overview(robot)` — Multi-pair snapshot

---

## 6. Existing Approach

### Dash-Based Web Framework

Viewers use Dash (Flask + Plotly) for interactive dashboards:
- Server-side data loading
- Client-side interactivity (dropdowns, sliders trigger callbacks)
- No page reloads (AJAX updates)

### Independent Viewer Apps

Each view_*.py is a standalone Dash app:
- `view_full.py` — Full candle viewer
- `view_simulation.py` — Backtest replay
- `view_online.py` — Live trading monitor
- `view_predict.py` — Price predictions

Allows modular development and independent deployment.

### Plotly for Charting

Plotly provides:
- Responsive candlestick charts
- Zoom/pan/hover interactivity
- Subplots for multi-panel layouts
- Annotation support for trade marks

### Parameter-Driven Rendering

UI components accept callbacks that recompute charts:
```python
@app.callback(
    Output('graphs', 'children'),
    [Input('stock-ticker-input', 'value'),
     Input('time-input', 'value'),
     Input('shift-input', 'value'),
     Input('markers-input', 'value')]
)
def update_graph(tickers, time, time_shift, markers_to_show):
    # Recompute and redraw chart
```

Users adjust parameters; chart updates in real-time.

---

## 7. Potential Improvements

1. **Add Real-Time WebSocket Updates**
   - Stream live price data to dashboard
   - Push position updates automatically
   - Would enable true live monitoring

2. **Implement Chart Export**
   - Save charts as PNG/PDF
   - Generate reports with multiple charts

3. **Add Annotation Tools**
   - Manually mark support/resistance
   - Add notes to trades
   - Would improve analysis collaboration

4. **Support Strategy Playback**
   - Step through strategy logic
   - Explain decisions at each step
   - Would aid strategy learning

5. **Implement Alert System**
   - Notify on signal generation
   - Alert on drawdown thresholds
   - Would support active monitoring

6. **Add Comparison Slider**
   - Side-by-side comparison of time periods
   - Overlay multiple strategies
   - Would improve relative analysis

7. **Support Custom Indicators**
   - Allow user-defined indicator formulas
   - Real-time computation
   - Would enable advanced analysis

8. **Implement Portfolio Dashboard**
   - Multi-pair overview
   - Correlation heatmap
   - Aggregated risk metrics

9. **Add Machine Learning Insights**
   - Feature importance visualization
   - Prediction confidence intervals
   - Would show NN decision drivers

10. **Support Mobile Responsiveness**
    - Optimize for phone/tablet
    - Touch-friendly controls
    - Would enable monitoring on-the-go
