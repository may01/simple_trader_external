# PerformanceAnalyzer Class Specification

**Class:** `PerformanceAnalyzer` (Proposed New)  
**Files:** New utility for analysis  
**Purpose:** Analyze backtest results: compute statistics, generate reports, compare configurations.

---

## 1. Class Overview

The `PerformanceAnalyzer` class provides statistical and comparative analysis of backtest results. It computes performance metrics, generates reports, and enables comparison across multiple strategies or time periods.

---

## 2. Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `results` | `list[SimulationResult]` | Backtest results to analyze |
| `benchmark_result` | `SimulationResult` | Reference result for comparison |
| `statistics` | `dict` | Computed statistics cache |

---

## 3. Constructor

### `__init__(results, benchmark=None)`

**Parameters:**
- `results` (`list[SimulationResult]`) — Results to analyze
- `benchmark` (`SimulationResult`) — Optional reference result

---

## 4. Key Methods & Interfaces

### `compute_statistics(result)`

**Purpose:** Compute comprehensive statistics from result.

**Parameters:**
- `result` (`SimulationResult`) — Single result

**Return Value:** `dict` with:
- `"total_return"` — Percent return
- `"annual_return"` — Annualized return
- `"sharpe_ratio"` — Risk-adjusted return
- `"max_drawdown"` — Peak-to-trough decline
- `"win_rate"` — Profitable trade percentage
- `"profit_factor"` — Gross profit / gross loss
- `"sortino_ratio"` — Downside-adjusted return
- `"calmar_ratio"` — Return / max drawdown
- `"ulcer_index"` — Extent and duration of drawdown
- `"recovery_factor"` — Net profit / max drawdown

**Behavior:**
1. Extract trades from result
2. Compute daily/monthly equity curves
3. Calculate metrics via standard formulas
4. Return results dict

### `compare_results()`

**Purpose:** Compare multiple results.

**Return Value:** `dict` with comparison:
- `"best_result"` — Highest return
- `"worst_result"` — Lowest return
- `"average_metrics"` — Mean across results
- `"ranking"` — Results sorted by Sharpe ratio
- `"statistical_significance"` — p-values from t-tests

### `generate_report(format='dict')`

**Purpose:** Generate comprehensive analysis report.

**Parameters:**
- `format` (`str`) — 'dict', 'html', 'pdf'

**Return Value:** Formatted report with:
- Summary statistics
- Trade analysis
- Risk metrics
- Comparison table (if multiple results)
- Visualizations (if HTML/PDF)

### `identify_edge(min_trades=20)`

**Purpose:** Identify statistically significant trading edge.

**Parameters:**
- `min_trades` (`int`) — Minimum trades required

**Return Value:** `dict` with:
- `"has_edge"` — Bool, is performance significant?
- `"confidence_level"` — Statistical confidence
- `"min_sample_size"` — Trades needed for robustness
- `"recommendations"` — Suggestions for improvement

**Behavior:**
1. Check if win_rate significantly > 50%
2. Check if Sharpe > 1.0 (good; > 2.0 excellent)
3. Check if max_drawdown < annual_return / 2
4. Compute confidence intervals
5. Return assessment

### `rank_by_metric(metric='sharpe_ratio')`

**Purpose:** Rank results by specified metric.

**Parameters:**
- `metric` (`str`) — Metric name (sharpe_ratio, total_return, win_rate, etc.)

**Return Value:** `list[tuple]` — [(rank, result, value), ...]

### `export_comparison_table()`

**Purpose:** Export comparison table.

**Return Value:** `str` (CSV) or `DataFrame`

---

## 5. State Management

- **Initialized:** Results loaded
- **Analyzed:** Statistics computed
- **Compared:** Multiple results ranked

---

## 6. Potential Improvements

1. **Add Monte Carlo Simulation**
   - Resample trades randomly
   - Compute confidence intervals

2. **Implement Walk-Forward Analysis**
   - Test robustness across time windows
   - Detect overfitting

3. **Add Parameter Sensitivity**
   - Vary strategy parameters
   - Measure performance impact

4. **Support Regime Analysis**
   - Identify market regimes
   - Compute per-regime statistics

5. **Add Correlation Analysis**
   - Correlate performance with market factors
   - Identify drivers

6. **Implement Visualization**
   - Equity curves, drawdown charts
   - Distribution plots, heatmaps

7. **Support Report Generation**
   - Professional PDF reports
   - Interactive HTML dashboards

8. **Add Hypothesis Testing**
   - Test if strategy outperforms benchmark
   - Statistical significance

9. **Implement Factor Analysis**
   - Decompose returns by factor
   - Attribution analysis

10. **Support Custom Metrics**
    - User-defined performance metrics
    - Domain-specific analysis
