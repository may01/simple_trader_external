# Task 03: PerformanceAnalyzer

**Phase:** 08 — Backtesting  
**Depends on:** Task 02 (SimulationOrchestrator results format)  
**Produces:** `backtesting/performance_analyzer.py` — trade analytics and revenue reporting

---

## Goal

Implement `PerformanceAnalyzer` — consumes aggregated worker results, computes per-trade and aggregate statistics, and produces printable/exportable performance report.

---

## Context

After all workers complete, their result dicts are merged and passed to `PerformanceAnalyzer`. Produces metrics: total trades, win rate, average revenue, Sharpe-like ratio, max drawdown, consecutive losses. Used both by backtesting pipeline and by training pipeline to evaluate strategy quality.

---

## Files

- Create: `backtesting/performance_analyzer.py`

---

## Interface

**`PerformanceAnalyzer(results: list[dict])`**

Attributes:
- `all_trades: list[tuple[float, float]]` — flattened `(revenue_pct, revenue_abs)` across all workers
- `total_trades: int`
- `winning_trades: int`
- `losing_trades: int`

**`analyze() -> dict`**
- Computes and returns metrics dict:
  - `total_trades: int`
  - `win_rate: float` — fraction of trades with `revenue_pct > 0`
  - `avg_revenue_pct: float`
  - `total_revenue_abs: float`
  - `max_drawdown: float` — maximum peak-to-trough cumulative revenue drop
  - `max_consecutive_losses: int`
  - `profit_factor: float` — sum of wins / abs(sum of losses)

**`print_report() -> None`**
- Prints formatted summary to stdout

**`to_dict() -> dict`**
- Returns raw `all_trades` list plus computed metrics — suitable for JSON export or Trainer metadata

---

## Key Constraints

- Handles empty `results` or workers with zero trades without dividing by zero
- `max_drawdown` computed on cumulative `revenue_abs` series — track running peak
- `profit_factor` returns `inf` if no losing trades; returns 0.0 if no winning trades
- No plotting in this class — visualization is Frontend concern (Phase 12)
- All metrics computed lazily in `analyze()`, not in `__init__`

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from backtesting.performance_analyzer import PerformanceAnalyzer

results = [
    {'revenue_history': [(0.01, 10.0), (-0.005, -5.0), (0.02, 20.0)], 'trade_count': 3},
    {'revenue_history': [(0.015, 15.0)], 'trade_count': 1},
]
pa = PerformanceAnalyzer(results)
metrics = pa.analyze()
assert metrics['total_trades'] == 4
assert metrics['win_rate'] == 0.75
print('performance_analyzer ok:', metrics)
"
```

---

## Commit

`feat: implement PerformanceAnalyzer with win rate, drawdown, and profit factor metrics`
