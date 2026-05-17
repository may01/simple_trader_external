# TrainingDashboard Class Specification

**Class:** `TrainingDashboard` (Refactoring of view_simulation.py)  
**Files:** `view_simulation.py`  
**Purpose:** Visualize backtest/training results: equity curves, trade analysis, performance statistics.

---

## 1. Class Overview

The `TrainingDashboard` class displays comprehensive backtest analysis. It loads SimulationResult objects and renders interactive Dash dashboards showing equity evolution, drawdowns, trade statistics, and strategy comparison.

---

## 2. Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `result` | `SimulationResult` | Backtest result to display |
| `app` | `dash.Dash` | Dash application instance |
| `analyzer` | `PerformanceAnalyzer` | Statistics calculator |
| `data_viewer` | `DataViewer` | Market data loader |

---

## 3. Constructor

### `__init__(result, pair=None, enable_comparison=False)`

**Parameters:**
- `result` (`SimulationResult`) — Result to display
- `pair` (`str`) — Trading pair (optional)
- `enable_comparison` (`bool`) — Show comparison mode. Default: False

**Behavior:**
1. Store result
2. Initialize Dash app
3. Create PerformanceAnalyzer
4. Calculate statistics
5. Build layout

---

## 4. Key Methods & Interfaces

### `display()`

**Purpose:** Show interactive dashboard (start Dash server).

**Behavior:**
1. Configure callbacks for interactivity
2. Start Dash server on default port (8050)
3. Open browser
4. Run until shutdown

### `display_results()`

**Purpose:** Get dashboard layout (for embedding).

**Return Value:** `dash.html.Div` with dashboard

**Behavior:**
1. Create multi-panel layout:
   - Equity curve chart (top)
   - Drawdown chart
   - Trade statistics table
   - Performance metrics summary
   - Trade-by-trade list
2. Configure dropdowns for filtering
3. Add interactive callbacks
4. Return layout div

### `display_equity_curve()`

**Purpose:** Render equity evolution chart.

**Return Value:** `plotly.Figure` with equity over time

**Behavior:**
1. Extract cumulative equity from trades
2. Create line chart
3. Shade drawdown regions in red
4. Add milestone markers (max equity, max drawdown)
5. Include statistics annotations

### `display_trade_analysis()`

**Purpose:** Show trade-level statistics table.

**Return Value:** `dash.html.Table` with trade details

**Columns:**
- Entry Date/Time
- Entry Price
- Exit Date/Time
- Exit Price
- P&L (Absolute and Percent)
- Duration
- Position Type (LONG/SHORT)

### `display_comparison(results_list)`

**Purpose:** Compare multiple backtest results.

**Parameters:**
- `results_list` (`list[SimulationResult]`) — Results to compare

**Return Value:** `plotly.Figure` with comparison chart

**Behavior:**
1. Normalize equity curves to 100% starting capital
2. Plot all curves together
3. Highlight best/worst performers
4. Include statistics table

### `get_summary_stats()`

**Purpose:** Get performance metrics dict.

**Return Value:** `dict` with:
- `"total_return"` — Percent return
- `"sharpe_ratio"` — Risk-adjusted return
- `"max_drawdown"` — Peak decline
- `"win_rate"` — Profitable trade percentage
- `"num_trades"` — Count
- `"avg_trade_duration"` — Minutes
- `"profit_factor"` — Gross profit / gross loss

---

## 5. Callbacks (Interactivity)

### Timeframe Selector

User adjusts date range; chart updates to show selected period.

### Indicator Selector

User toggles indicators on/off; chart redraws.

### Trade Filter

User filters trades by type (LONG/SHORT), profitability (profit/loss), duration range.

### Comparison Mode

User adds results to compare; generates overlay chart.

---

## 6. Potential Improvements

1. **Add Risk Metrics Visualization**
   - VaR, CVaR, Calmar ratio charts

2. **Implement Monte Carlo Simulation**
   - Generate confidence bands
   - Show possible outcome ranges

3. **Add Factor Analysis**
   - Decompose returns by market factors
   - Attribution reports

4. **Support Walk-Forward Analysis**
   - Show performance across rolling windows
   - Identify regime changes

5. **Add Scenario Analysis**
   - Test against synthetic market conditions
   - Stress test results

6. **Implement Heat Maps**
   - Trade performance by hour/day of week
   - Identify time-based patterns

7. **Add Correlation Analysis**
   - Correlate trades with market conditions
   - Regime identification

8. **Support Waterfall Charts**
   - Show contribution of each trade to total return
   - Identify key trades

9. **Add Distribution Analysis**
   - P&L distribution histograms
   - Identify skewness/kurtosis

10. **Implement Report Generation**
    - Export PDF reports
    - Generate presentation slides
