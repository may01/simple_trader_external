# Phase 6a: Backtesting Implementation Plan (PARALLEL — Agent A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Depends on Phase 5. Runs in parallel with Phase 6b.

**Goal:** Implement `TrainRobot` (simulation executor), `SimulationResult` (trade metrics), `PerformanceAnalyzer` (return/drawdown stats).

**Architecture:** `TrainRobot` mirrors `Robot` but uses `SimulationData` instead of Binance. Fills simulated against candle OHLC: long buy fills at candle high, sell fills at candle low (conservative). `SimulationResult` accumulates per-trade P&L. `PerformanceAnalyzer` computes total return, max drawdown, Sharpe.

**Tech Stack:** numpy, pandas. No TA-Lib. No Binance.

---

## Working Directory

```
⚠️ All relative paths and bash commands below resolve from this directory.
```

| Branch type | Working directory |
|-------------|-------------------|
| `main` branch | `/home/om/projects/simple_trader/main` |
| Worktree branch | `/home/om/projects/simple_trader/worktrees/<branch-name>/` |

For parallel phases (3a+3b, 6a+6b): each agent creates its own worktree under `/home/om/projects/simple_trader/worktrees/` using the `superpowers:using-git-worktrees` skill, then works entirely within that directory.

---

## File Structure

```
src/simple_trader/backtesting/
  __init__.py
  train_robot.py
  simulation_result.py
  performance_analyzer.py
tests/backtesting/
  __init__.py
  test_train_robot.py
  test_simulation_result.py
  test_performance_analyzer.py
```

---

## Task 0: Directory Setup

- [ ] **Step 1: Create directories**

```bash
mkdir -p src/simple_trader/backtesting
mkdir -p tests/backtesting
touch src/simple_trader/backtesting/__init__.py
touch tests/backtesting/__init__.py
```

---

## Task 1: SimulationResult

**Files:**
- Create: `src/simple_trader/backtesting/simulation_result.py`
- Create: `tests/backtesting/test_simulation_result.py`

- [ ] **Step 1: Write failing test**

`tests/backtesting/test_simulation_result.py`:

```python
import pytest
from simple_trader.backtesting.simulation_result import SimulationResult


def test_result_starts_empty():
    r = SimulationResult()
    assert r.trade_count == 0
    assert r.total_revenue_pct == pytest.approx(0.0)


def test_result_add_trade_increments_count():
    r = SimulationResult()
    r.add_trade(revenue_pct=0.02, revenue_abs=20.0)
    assert r.trade_count == 1


def test_result_total_revenue_accumulates():
    r = SimulationResult()
    r.add_trade(0.02, 20.0)
    r.add_trade(0.03, 30.0)
    assert r.total_revenue_pct == pytest.approx(0.05)
    assert r.total_revenue_abs == pytest.approx(50.0)


def test_result_winning_trades_count():
    r = SimulationResult()
    r.add_trade(0.02, 20.0)
    r.add_trade(-0.01, -10.0)
    r.add_trade(0.03, 30.0)
    assert r.winning_trades == 2
    assert r.losing_trades == 1


def test_result_win_rate():
    r = SimulationResult()
    r.add_trade(0.02, 20.0)
    r.add_trade(-0.01, -10.0)
    assert r.win_rate == pytest.approx(0.5)


def test_result_win_rate_zero_when_no_trades():
    r = SimulationResult()
    assert r.win_rate == 0.0


def test_result_trades_list_accessible():
    r = SimulationResult()
    r.add_trade(0.05, 50.0)
    assert len(r.trades) == 1
    assert r.trades[0]["revenue_pct"] == pytest.approx(0.05)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/backtesting/test_simulation_result.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.backtesting.simulation_result'`

- [ ] **Step 3: Write `src/simple_trader/backtesting/simulation_result.py`**

```python
from typing import Any, Dict, List


class SimulationResult:
    """Accumulates per-trade P&L across a backtest run."""

    def __init__(self) -> None:
        self.trades: List[Dict[str, Any]] = []

    def add_trade(self, revenue_pct: float, revenue_abs: float) -> None:
        self.trades.append({"revenue_pct": revenue_pct, "revenue_abs": revenue_abs})

    @property
    def trade_count(self) -> int:
        return len(self.trades)

    @property
    def total_revenue_pct(self) -> float:
        return sum(t["revenue_pct"] for t in self.trades)

    @property
    def total_revenue_abs(self) -> float:
        return sum(t["revenue_abs"] for t in self.trades)

    @property
    def winning_trades(self) -> int:
        return sum(1 for t in self.trades if t["revenue_pct"] > 0)

    @property
    def losing_trades(self) -> int:
        return sum(1 for t in self.trades if t["revenue_pct"] <= 0)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return self.winning_trades / self.trade_count
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/backtesting/test_simulation_result.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/backtesting/simulation_result.py tests/backtesting/test_simulation_result.py
git commit -m "feat: add SimulationResult for trade P&L accumulation"
```

---

## Task 2: PerformanceAnalyzer

**Files:**
- Create: `src/simple_trader/backtesting/performance_analyzer.py`
- Create: `tests/backtesting/test_performance_analyzer.py`

- [ ] **Step 1: Write failing test**

`tests/backtesting/test_performance_analyzer.py`:

```python
import pytest
import numpy as np
from simple_trader.backtesting.simulation_result import SimulationResult
from simple_trader.backtesting.performance_analyzer import PerformanceAnalyzer


def _result_from_pcts(pcts: list) -> SimulationResult:
    r = SimulationResult()
    for p in pcts:
        r.add_trade(p, p * 1000)
    return r


def test_analyzer_total_return():
    result = _result_from_pcts([0.02, 0.03, -0.01])
    pa = PerformanceAnalyzer(result)
    assert pa.total_return_pct == pytest.approx(0.04)


def test_analyzer_max_drawdown_zero_when_always_positive():
    result = _result_from_pcts([0.01, 0.02, 0.03])
    pa = PerformanceAnalyzer(result)
    assert pa.max_drawdown_pct == pytest.approx(0.0)


def test_analyzer_max_drawdown_detects_peak_to_trough():
    # Equity: 0, +0.05, +0.02, +0.04 → drawdown from 0.05 to 0.02 = 0.03
    result = _result_from_pcts([0.05, -0.03, 0.02])
    pa = PerformanceAnalyzer(result)
    assert pa.max_drawdown_pct == pytest.approx(0.03)


def test_analyzer_sharpe_positive_for_consistent_gains():
    result = _result_from_pcts([0.01] * 20)
    pa = PerformanceAnalyzer(result)
    assert pa.sharpe_ratio > 0


def test_analyzer_sharpe_zero_when_no_trades():
    pa = PerformanceAnalyzer(SimulationResult())
    assert pa.sharpe_ratio == 0.0


def test_analyzer_summary_dict_has_required_keys():
    result = _result_from_pcts([0.02, -0.01, 0.03])
    pa = PerformanceAnalyzer(result)
    summary = pa.summary()
    assert "total_return_pct" in summary
    assert "max_drawdown_pct" in summary
    assert "sharpe_ratio" in summary
    assert "win_rate" in summary
    assert "trade_count" in summary
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/backtesting/test_performance_analyzer.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.backtesting.performance_analyzer'`

- [ ] **Step 3: Write `src/simple_trader/backtesting/performance_analyzer.py`**

```python
from typing import Any, Dict
import numpy as np
from .simulation_result import SimulationResult


class PerformanceAnalyzer:
    """Computes return metrics from a SimulationResult."""

    def __init__(self, result: SimulationResult) -> None:
        self._result = result

    @property
    def total_return_pct(self) -> float:
        return self._result.total_revenue_pct

    @property
    def max_drawdown_pct(self) -> float:
        if not self._result.trades:
            return 0.0
        pcts = [t["revenue_pct"] for t in self._result.trades]
        equity = np.cumsum(pcts)
        running_max = np.maximum.accumulate(equity)
        drawdowns = running_max - equity
        return float(np.max(drawdowns))

    @property
    def sharpe_ratio(self) -> float:
        if not self._result.trades:
            return 0.0
        pcts = np.array([t["revenue_pct"] for t in self._result.trades])
        std = pcts.std()
        if std == 0:
            return 0.0
        return float(pcts.mean() / std * np.sqrt(len(pcts)))

    def summary(self) -> Dict[str, Any]:
        return {
            "total_return_pct": self.total_return_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sharpe_ratio":     self.sharpe_ratio,
            "win_rate":         self._result.win_rate,
            "trade_count":      self._result.trade_count,
        }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/backtesting/test_performance_analyzer.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/backtesting/performance_analyzer.py tests/backtesting/test_performance_analyzer.py
git commit -m "feat: add PerformanceAnalyzer with drawdown and Sharpe calculation"
```

---

## Task 3: TrainRobot

**Files:**
- Create: `src/simple_trader/backtesting/train_robot.py`
- Create: `tests/backtesting/test_train_robot.py`

- [ ] **Step 1: Write failing test**

`tests/backtesting/test_train_robot.py`:

```python
import pytest
import pandas as pd
import numpy as np
from simple_trader.backtesting.train_robot import TrainRobot
from simple_trader.backtesting.simulation_result import SimulationResult
from simple_trader.data.data_point import WideDataPoint
from simple_trader.data.simulation_data import SimulationData
from simple_trader.position.position import Position
from simple_trader.position.long_position import LongPosition
from simple_trader.strategy.strategy_manager import StrategyManager
from simple_trader.infrastructure.constants import StrategyAction, PositionState
from unittest.mock import MagicMock


def _make_wide_df(rows: int = 20) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=rows, freq="1min")
    closes = 15.0 + np.sin(np.linspace(0, 4 * np.pi, rows))
    return pd.DataFrame({
        "1_close": closes,
        "1_high":  closes * 1.001,
        "1_low":   closes * 0.999,
        "1_rsi_14": np.linspace(30, 70, rows),
        "1_cci_20": np.linspace(-150, 150, rows),
    }, index=idx)


def _make_idle_position() -> Position:
    return Position(LongPosition("USDT", "LINK", 1000.0, 0.001))


def test_train_robot_step_does_not_raise():
    df = _make_wide_df()
    sim = SimulationData(df, step_min=1)
    mgr = MagicMock(spec=StrategyManager)
    mgr.check.return_value = (StrategyAction.NOTHING, 0.0, 0.0, 0.0, 1)
    robot = TrainRobot(strategy_mgr=mgr, position=_make_idle_position(), fee=0.001)
    point = sim.step()
    robot.step(point)


def test_train_robot_records_completed_trade():
    df = _make_wide_df()
    sim = SimulationData(df, step_min=1)
    result = SimulationResult()
    mgr = MagicMock(spec=StrategyManager)

    pos = _make_idle_position()
    robot = TrainRobot(strategy_mgr=mgr, position=pos, fee=0.001, result=result)

    # Open long
    mgr.check.return_value = (StrategyAction.OPEN_LONG, 15.0, 16.0, 14.5, 1)
    robot.step(sim.step())
    assert pos.state == PositionState.WAIT_BUY

    # Simulate fill (entry)
    pos.record_entry_fill(10.0, 15.0)

    # Close long
    mgr.check.return_value = (StrategyAction.CLOSE_LONG, 0.0, 16.0, 0.0, 1)
    robot.step(sim.step())

    # Simulate fill (exit)
    pos.record_exit_fill(10.0, 16.0)
    robot.finalize_trade(entry_price=15.0, exit_price=16.0)

    assert result.trade_count == 1
    assert result.total_revenue_pct > 0


def test_train_robot_simulated_fill_uses_candle_prices():
    """Entry fills at candle high (pessimistic), exit fills at candle low."""
    df = _make_wide_df()
    sim = SimulationData(df, step_min=1)
    pos = _make_idle_position()
    mgr = MagicMock(spec=StrategyManager)
    mgr.check.return_value = (StrategyAction.OPEN_LONG, 15.0, 16.0, 14.5, 1)
    robot = TrainRobot(strategy_mgr=mgr, position=pos, fee=0.001)

    point = sim.step()
    robot.step(point)

    # Entry fill price should be candle high (conservative for long buy)
    assert len(pos._impl.executed_open) == 1
    fill_price = pos._impl.executed_open[0]
    candle_high = point.get("high", tf=1)
    assert fill_price == pytest.approx(candle_high)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/backtesting/test_train_robot.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.backtesting.train_robot'`

- [ ] **Step 3: Write `src/simple_trader/backtesting/train_robot.py`**

```python
from typing import Optional
from ..data.data_point import DataPoint
from ..position.position import Position
from ..strategy.strategy_manager import StrategyManager
from ..infrastructure.constants import StrategyAction, PositionState
from .simulation_result import SimulationResult


class TrainRobot:
    """
    Simulation robot for backtesting.

    Mirrors Robot but replaces Binance API calls with simulated fills
    against candle OHLC data. Conservative fill model:
    - Long BUY fills at candle HIGH (worst-case entry)
    - Long SELL fills at candle LOW  (worst-case exit)
    - Short SELL fills at candle LOW
    - Short BUY fills at candle HIGH
    """

    def __init__(
        self,
        strategy_mgr: StrategyManager,
        position: Position,
        fee: float = 0.001,
        result: Optional[SimulationResult] = None,
    ) -> None:
        self.strategy_mgr = strategy_mgr
        self.position = position
        self.fee = fee
        self.result = result or SimulationResult()
        self._pending_entry_price: float = 0.0

    def step(self, data_point: DataPoint) -> None:
        action, open_p, close_p, stop_p, tf = self.strategy_mgr.check(
            data_point, self.position
        )
        self._route_action(action, data_point, open_p, close_p, stop_p, tf)

    def _route_action(
        self,
        action: StrategyAction,
        data_point: DataPoint,
        open_p: float,
        close_p: float,
        stop_p: float,
        tf: int,
    ) -> None:
        if action == StrategyAction.OPEN_LONG:
            if self.position.state == PositionState.WAIT:
                self.position.open(open_p, close_p, stop_p)
                fill_price = data_point.get("high", tf)
                self.position.record_entry_fill(1.0, fill_price)
                self._pending_entry_price = fill_price

        elif action == StrategyAction.OPEN_SHORT:
            if self.position.state == PositionState.WAIT:
                self.position.open(open_p, close_p, stop_p)
                fill_price = data_point.get("low", tf)
                self.position.record_entry_fill(1.0, fill_price)
                self._pending_entry_price = fill_price

        elif action == StrategyAction.CLOSE_LONG:
            if self.position.state in (
                PositionState.WAIT_BUY, PositionState.WAIT_SAFETY_BUY
            ):
                self.position.close(close_p, stop_p)
                fill_price = data_point.get("low", tf)
                self.position.record_exit_fill(1.0, fill_price)
                self.finalize_trade(self._pending_entry_price, fill_price)

        elif action == StrategyAction.CLOSE_SHORT:
            if self.position.state in (
                PositionState.WAIT_SELL, PositionState.WAIT_SAFETY_SELL
            ):
                self.position.close(close_p, stop_p)
                fill_price = data_point.get("high", tf)
                self.position.record_exit_fill(1.0, fill_price)
                self.finalize_trade(self._pending_entry_price, fill_price)

        elif action == StrategyAction.MOVE_STOP_LOSS_LONG:
            self.position.set_stop_loss(stop_p)

        elif action == StrategyAction.DO_STOP_LOSS:
            fill_price = stop_p
            self.position.close(stop_p, stop_p)
            self.position.record_exit_fill(1.0, fill_price)
            self.finalize_trade(self._pending_entry_price, fill_price)

    def finalize_trade(self, entry_price: float, exit_price: float) -> None:
        pct, abs_rev = self.position.finalize(entry_price, exit_price)
        self.result.add_trade(pct, abs_rev)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/backtesting/test_train_robot.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Run full Phase 6a suite**

```bash
pytest tests/backtesting/ -v
```

Expected: `16+ passed, 0 failed`

- [ ] **Step 6: Commit**

```bash
git add src/simple_trader/backtesting/ tests/backtesting/
git commit -m "feat: add backtesting module — TrainRobot, SimulationResult, PerformanceAnalyzer"
```
