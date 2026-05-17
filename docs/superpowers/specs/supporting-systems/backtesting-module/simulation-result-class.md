# SimulationResult Class Specification

**Class:** `SimulationResult` (Proposed Refactoring)  
**Files:** `trainer.py`, `train_robot.py` (result structures, lines 165-170)  
**Purpose:** Encapsulate backtest results: revenue metrics, trade-level details, statistics for analysis and reporting.

---

## 1. Class Overview

The `SimulationResult` class is a proposed refactoring to formalize result structures. Currently, backtest results are scattered dictionaries and direct class variables. A dedicated result class would:

- Provide typed attributes for all result metrics
- Enable result comparison and statistical analysis
- Support serialization/deserialization
- Calculate derived metrics (Sharpe ratio, max drawdown, etc.)
- Enable result filtering and aggregation

---

## 2. Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `pair` | `str` | Trading pair |
| `begin_time` | `int` | Backtest start timestamp |
| `end_time` | `int` | Backtest end timestamp |
| `total_revenue` | `float` | Cumulative revenue (relative: PnL / capital) |
| `total_revenue_abs` | `float` | Absolute revenue (USD) |
| `revenue_by_strategy_id` | `dict` | Revenue breakdown by strategy: {strategy_id: revenue} |
| `trades` | `list[dict]` | Trade-level details: [{entry_time, entry_price, exit_time, exit_price, pnl, ...}, ...] |
| `max_drawdown` | `float` | Peak-to-trough decline |
| `sharpe_ratio` | `float` | Risk-adjusted return metric |
| `win_rate` | `float` | Percentage of profitable trades |
| `average_trade_duration` | `int` | Mean trade duration in minutes |
| `num_trades` | `int` | Total number of trades executed |
| `strategy_configs` | `dict` | Strategy configuration used in backtest |

---

## 3. Constructor

### `__init__(pair, begin_time, end_time, strategy_configs=None)`

**Purpose:** Initialize result container.

**Parameters:**
- `pair` (`str`) — Trading pair
- `begin_time` (`int`) — Start timestamp
- `end_time` (`int`) — End timestamp
- `strategy_configs` (`dict`) — Strategy configuration (optional)

**Behavior:**
1. Store parameters
2. Initialize empty collections: trades[], revenue_by_strategy_id{}
3. Initialize metrics to 0: total_revenue, total_revenue_abs, win_rate, etc.

---

## 4. Key Methods & Interfaces

### `add_trade(entry_time, entry_price, exit_time, exit_price, quantity, fees, position_type)`

**Purpose:** Record a closed trade.

**Parameters:**
- `entry_time` (`int`) — Entry timestamp
- `entry_price` (`float`) — Entry execution price
- `exit_time` (`int`) — Exit timestamp
- `exit_price` (`float`) — Exit execution price
- `quantity` (`float`) — Position size
- `fees` (`float`) — Total fees paid
- `position_type` (`str`) — 'LONG' or 'SHORT'

**Behavior:**
1. Calculate PnL: (exit_price - entry_price) * quantity for long; reversed for short
2. Create trade dict: {entry_time, entry_price, exit_time, exit_price, pnl, ...}
3. Append to trades list
4. Update win_rate: count profitable trades / total trades

### `set_revenue(total_revenue, revenue_abs, revenue_by_id)`

**Purpose:** Set cumulative revenue metrics.

**Parameters:**
- `total_revenue` (`float`) — Relative revenue
- `revenue_abs` (`float`) — Absolute revenue
- `revenue_by_id` (`dict`) — By-strategy breakdown

**Behavior:**
1. Store metrics
2. Trigger recalculation of derived statistics if needed

### `calculate_statistics()`

**Purpose:** Compute derived metrics from raw results.

**Behavior:**
1. Calculate max_drawdown:
   - Track cumulative equity at each trade
   - Find peak and trough
   - Compute (peak - trough) / peak
2. Calculate sharpe_ratio:
   - Collect daily/monthly returns
   - Compute (mean return) / (std return)
3. Calculate win_rate: count_profitable / total_trades
4. Calculate average_trade_duration: sum(exit_time - entry_time) / num_trades

**Returns:** `dict` with all calculated metrics

### `filter_trades(filter_fn)`

**Purpose:** Filter trades by criteria.

**Parameters:**
- `filter_fn` (callable) — Function taking trade dict, returning bool

**Behavior:**
1. Filter trades list
2. Recalculate statistics on filtered set
3. Return new SimulationResult with filtered trades

**Example:**
```python
profitable_only = result.filter_trades(lambda t: t['pnl'] > 0)
long_trades = result.filter_trades(lambda t: t['position_type'] == 'LONG')
```

### `to_dict()`

**Purpose:** Export to dictionary for serialization.

**Return Value:** `dict` with all attributes

### `from_dict(data)`

**Purpose:** Load from dictionary.

**Parameters:**
- `data` (`dict`) — Serialized result

**Return Value:** `SimulationResult` instance

### `export_csv(filepath)`

**Purpose:** Export trades to CSV for analysis.

**Parameters:**
- `filepath` (`str`) — Output CSV path

**Behavior:**
1. Create DataFrame from trades list
2. Add computed columns: duration, pnl_pct, etc.
3. Write to CSV

### `get_summary()`

**Purpose:** Get human-readable summary.

**Return Value:** `str` with formatted results:
```
Backtest Results: link_usdt [2024-01-01 to 2024-01-31]
Total Revenue: 5.25% (USD 1050)
Win Rate: 60% (12/20 trades)
Max Drawdown: -8.5%
Sharpe Ratio: 1.2
Average Trade Duration: 4.5 hours
```

---

## 5. Error Handling

**Invalid Price Data:**
```python
if exit_price <= 0 or entry_price <= 0:
    raise ValueError("Prices must be positive")
```

**Negative Quantity:**
```python
if quantity <= 0:
    raise ValueError("Quantity must be positive")
```

---

## 6. Existing Approach

Current implementation:
- TrainRobot stores results as class variables
- Results scattered across multiple dicts
- Manual calculation of statistics
- No formal structure

Limitations:
- Hard to compare multiple backtest results
- Statistics require manual computation
- No serialization support

---

## 7. Potential Improvements

1. **Add Equity Curve**
   - Track cumulative equity at each time point
   - Enable drawdown visualization

2. **Implement Scenario Analysis**
   - Test against different market conditions
   - Compute regime-specific statistics

3. **Add Sensitivity Analysis**
   - Vary strategy parameters
   - Measure impact on results

4. **Support Stress Testing**
   - Apply worst-case price movements
   - Compute robustness metrics

5. **Add Trade Clustering**
   - Group similar trades
   - Identify common win/loss patterns

6. **Implement Correlation Analysis**
   - Correlate trades with market conditions
   - Identify regime-dependent performance

7. **Add Visualization Export**
   - Generate equity curve charts
   - Export trade marks on candlestick charts

8. **Support Batch Comparison**
   - Compare multiple backtest results
   - Statistical significance testing

9. **Add Risk Metrics**
   - Calmar ratio, Sortino ratio
   - Value at Risk (VaR)

10. **Implement Report Generation**
    - PDF reports with charts and statistics
    - HTML dashboards for Web viewing
