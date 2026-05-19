# Phase 7: Frontend Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Depends on Phase 6a + 6b both completing.

**Goal:** Implement `ChartRenderer` (OHLC + indicator charting), `DataViewer` (full historical view), `TrainingDashboard` (training metrics), `LiveDashboard` (live trading status).

**Architecture:** Terminal-first output (stdout/ASCII). No external UI framework required. `ChartRenderer` uses matplotlib if available, falls back to ASCII sparklines. Dashboards print structured summaries. Tests verify data formatting, not visual output.

**Tech Stack:** matplotlib (optional), rich (optional for tables). Falls back to plain print if absent.

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
src/simple_trader/frontend/
  __init__.py
  chart_renderer.py
  data_viewer.py
  training_dashboard.py
  live_dashboard.py
tests/frontend/
  __init__.py
  test_chart_renderer.py
  test_data_viewer.py
  test_training_dashboard.py
  test_live_dashboard.py
```

---

## Task 0: Directory Setup

- [ ] **Step 1: Create directories**

```bash
mkdir -p src/simple_trader/frontend
mkdir -p tests/frontend
touch src/simple_trader/frontend/__init__.py
touch tests/frontend/__init__.py
```

---

## Task 1: ChartRenderer

Renders OHLC data + indicators. Tests verify the data extraction logic, not pixel output.

**Files:**
- Create: `src/simple_trader/frontend/chart_renderer.py`
- Create: `tests/frontend/test_chart_renderer.py`

- [ ] **Step 1: Write failing test**

`tests/frontend/test_chart_renderer.py`:

```python
import pytest
import pandas as pd
import numpy as np
from simple_trader.frontend.chart_renderer import ChartRenderer


def _make_df(rows: int = 20) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=rows, freq="1min")
    closes = 15.0 + np.sin(np.linspace(0, 2 * np.pi, rows))
    return pd.DataFrame({
        "1_open":   closes * 0.999,
        "1_high":   closes * 1.002,
        "1_low":    closes * 0.998,
        "1_close":  closes,
        "1_volume": np.abs(np.random.randn(rows)) * 1000,
        "1_rsi_14": np.linspace(30, 70, rows),
    }, index=idx)


def test_renderer_extract_ohlc_returns_dict():
    df = _make_df()
    renderer = ChartRenderer(tf=1)
    ohlc = renderer.extract_ohlc(df)
    assert "open" in ohlc
    assert "high" in ohlc
    assert "low" in ohlc
    assert "close" in ohlc
    assert len(ohlc["close"]) == 20


def test_renderer_extract_indicator_returns_series():
    df = _make_df()
    renderer = ChartRenderer(tf=1)
    rsi = renderer.extract_indicator(df, "rsi_14")
    assert len(rsi) == 20
    assert rsi[0] == pytest.approx(30.0)


def test_renderer_ascii_sparkline_returns_string():
    renderer = ChartRenderer(tf=1)
    values = [10.0, 12.0, 8.0, 15.0, 11.0]
    line = renderer.ascii_sparkline(values)
    assert isinstance(line, str)
    assert len(line) == len(values)


def test_renderer_ascii_sparkline_uses_block_chars():
    renderer = ChartRenderer(tf=1)
    values = [0.0, 50.0, 100.0]
    line = renderer.ascii_sparkline(values)
    # Lowest value → lowest block, highest → highest block
    assert line[0] < line[2]   # char code comparison (lower block < higher block)


def test_renderer_summary_returns_dict():
    df = _make_df()
    renderer = ChartRenderer(tf=1)
    summary = renderer.summary(df, last_n=5)
    assert "last_close" in summary
    assert "high_5" in summary
    assert "low_5" in summary
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/frontend/test_chart_renderer.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.frontend.chart_renderer'`

- [ ] **Step 3: Write `src/simple_trader/frontend/chart_renderer.py`**

```python
from typing import Any, Dict, List
import pandas as pd

_SPARK_CHARS = " ▁▂▃▄▅▆▇█"


class ChartRenderer:
    """
    Renders OHLC data and indicators.

    Primary output is ASCII sparklines for terminal use.
    If matplotlib is available, plot() renders a visual chart.
    """

    def __init__(self, tf: int = 1) -> None:
        self.tf = tf

    def extract_ohlc(self, df: pd.DataFrame) -> Dict[str, List[float]]:
        prefix = f"{self.tf}_"
        return {
            "open":   df[f"{prefix}open"].tolist(),
            "high":   df[f"{prefix}high"].tolist(),
            "low":    df[f"{prefix}low"].tolist(),
            "close":  df[f"{prefix}close"].tolist(),
            "volume": df[f"{prefix}volume"].tolist() if f"{prefix}volume" in df else [],
        }

    def extract_indicator(self, df: pd.DataFrame, col: str) -> List[float]:
        return df[f"{self.tf}_{col}"].tolist()

    def ascii_sparkline(self, values: List[float]) -> str:
        if not values:
            return ""
        lo, hi = min(values), max(values)
        span = hi - lo or 1.0
        chars = _SPARK_CHARS
        result = ""
        for v in values:
            idx = int((v - lo) / span * (len(chars) - 1))
            result += chars[idx]
        return result

    def summary(self, df: pd.DataFrame, last_n: int = 5) -> Dict[str, Any]:
        closes = df[f"{self.tf}_close"].tail(last_n)
        highs  = df[f"{self.tf}_high"].tail(last_n)
        lows   = df[f"{self.tf}_low"].tail(last_n)
        return {
            "last_close": float(closes.iloc[-1]),
            f"high_{last_n}": float(highs.max()),
            f"low_{last_n}":  float(lows.min()),
            "sparkline": self.ascii_sparkline(closes.tolist()),
        }

    def plot(self, df: pd.DataFrame, indicators: List[str] = None) -> None:  # type: ignore[assignment]
        try:
            import matplotlib.pyplot as plt  # type: ignore[import]
            ohlc = self.extract_ohlc(df)
            fig, axes = plt.subplots(2, 1, figsize=(14, 8))
            axes[0].plot(ohlc["close"], label="close")
            axes[0].set_title(f"TF={self.tf}min")
            if indicators:
                for col in indicators:
                    if f"{self.tf}_{col}" in df.columns:
                        axes[1].plot(self.extract_indicator(df, col), label=col)
                axes[1].legend()
            plt.tight_layout()
            plt.show()
        except ImportError:
            print(self.ascii_sparkline(self.extract_ohlc(df)["close"]))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/frontend/test_chart_renderer.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/frontend/chart_renderer.py tests/frontend/test_chart_renderer.py
git commit -m "feat: add ChartRenderer with ASCII sparklines and matplotlib fallback"
```

---

## Task 2: TrainingDashboard

**Files:**
- Create: `src/simple_trader/frontend/training_dashboard.py`
- Create: `tests/frontend/test_training_dashboard.py`

- [ ] **Step 1: Write failing test**

`tests/frontend/test_training_dashboard.py`:

```python
from simple_trader.frontend.training_dashboard import TrainingDashboard
from simple_trader.backtesting.simulation_result import SimulationResult
from simple_trader.backtesting.performance_analyzer import PerformanceAnalyzer


def _result(pcts: list) -> SimulationResult:
    r = SimulationResult()
    for p in pcts:
        r.add_trade(p, p * 1000)
    return r


def test_dashboard_format_epoch_line():
    dash = TrainingDashboard()
    line = dash.format_epoch(epoch=5, loss=0.234, accuracy=0.72)
    assert "5" in line
    assert "0.234" in line or "0.23" in line


def test_dashboard_format_simulation_result():
    r = _result([0.02, 0.03, -0.01])
    pa = PerformanceAnalyzer(r)
    dash = TrainingDashboard()
    text = dash.format_simulation(pa)
    assert "trades" in text.lower() or "3" in text
    assert "return" in text.lower() or "0.04" in text


def test_dashboard_print_does_not_raise(capsys):
    dash = TrainingDashboard()
    dash.print_epoch(epoch=1, loss=0.5, accuracy=0.6)
    captured = capsys.readouterr()
    assert "1" in captured.out
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/frontend/test_training_dashboard.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Write `src/simple_trader/frontend/training_dashboard.py`**

```python
from ..backtesting.performance_analyzer import PerformanceAnalyzer


class TrainingDashboard:
    """Prints training progress and simulation metrics to stdout."""

    def format_epoch(self, epoch: int, loss: float, accuracy: float) -> str:
        return f"Epoch {epoch:4d} | loss={loss:.4f} | acc={accuracy:.4f}"

    def format_simulation(self, analyzer: PerformanceAnalyzer) -> str:
        s = analyzer.summary()
        return (
            f"Trades: {s['trade_count']:4d} | "
            f"Return: {s['total_return_pct']:+.4f} | "
            f"WinRate: {s['win_rate']:.2%} | "
            f"MaxDD: {s['max_drawdown_pct']:.4f} | "
            f"Sharpe: {s['sharpe_ratio']:.3f}"
        )

    def print_epoch(self, epoch: int, loss: float, accuracy: float) -> None:
        print(self.format_epoch(epoch, loss, accuracy))

    def print_simulation(self, analyzer: PerformanceAnalyzer) -> None:
        print(self.format_simulation(analyzer))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/frontend/test_training_dashboard.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/frontend/training_dashboard.py tests/frontend/test_training_dashboard.py
git commit -m "feat: add TrainingDashboard for training progress output"
```

---

## Task 3: LiveDashboard

**Files:**
- Create: `src/simple_trader/frontend/live_dashboard.py`
- Create: `tests/frontend/test_live_dashboard.py`

- [ ] **Step 1: Write failing test**

`tests/frontend/test_live_dashboard.py`:

```python
from simple_trader.frontend.live_dashboard import LiveDashboard
from simple_trader.position.position import Position
from simple_trader.position.long_position import LongPosition
from simple_trader.infrastructure.constants import PositionState


def _idle_pos() -> Position:
    return Position(LongPosition("USDT", "LINK", 1000.0, 0.001))


def test_dashboard_format_position_idle():
    pos = _idle_pos()
    dash = LiveDashboard(pair="LINKUSDT")
    text = dash.format_position(pos)
    assert "WAIT" in text or "idle" in text.lower()


def test_dashboard_format_position_open():
    pos = _idle_pos()
    pos.open(15.0, 17.0, 14.0)
    dash = LiveDashboard(pair="LINKUSDT")
    text = dash.format_position(pos)
    assert "15" in text or "WAIT_BUY" in text


def test_dashboard_format_price():
    dash = LiveDashboard(pair="LINKUSDT")
    text = dash.format_price(15.123)
    assert "15.12" in text


def test_dashboard_print_status_does_not_raise(capsys):
    pos = _idle_pos()
    dash = LiveDashboard(pair="LINKUSDT")
    dash.print_status(pos, current_price=15.0)
    out = capsys.readouterr().out
    assert "LINKUSDT" in out or "15" in out
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/frontend/test_live_dashboard.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Write `src/simple_trader/frontend/live_dashboard.py`**

```python
import time
from ..position.position import Position
from ..infrastructure.constants import PositionState


class LiveDashboard:
    """Prints live trading status to stdout."""

    def __init__(self, pair: str) -> None:
        self.pair = pair

    def format_price(self, price: float) -> str:
        return f"{price:.4f}"

    def format_position(self, position: Position) -> str:
        state = position.state.value
        if position.state == PositionState.WAIT:
            return f"[{state}] idle"
        return (
            f"[{state}] "
            f"entry={position.price_open[0] if position.price_open else 0:.4f} "
            f"stop={position.price_stop_loss:.4f} "
            f"target={position.price_close:.4f}"
        )

    def print_status(self, position: Position, current_price: float) -> None:
        ts = time.strftime("%H:%M:%S")
        print(
            f"{ts} | {self.pair} | price={self.format_price(current_price)} | "
            f"{self.format_position(position)}"
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/frontend/test_live_dashboard.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Run full Phase 7 suite**

```bash
pytest tests/frontend/ -v
```

Expected: `12+ passed, 0 failed`

- [ ] **Step 6: Run complete test suite (all phases)**

```bash
pytest tests/ -v --tb=short
```

Expected: All tests from Phases 1-7 pass.

- [ ] **Step 7: Commit**

```bash
git add src/simple_trader/frontend/ tests/frontend/
git commit -m "feat: add frontend module — ChartRenderer, TrainingDashboard, LiveDashboard"
```

---

## Task 4: DataViewer

**Files:**
- Create: `src/simple_trader/frontend/data_viewer.py`
- Create: `tests/frontend/test_data_viewer.py`

- [ ] **Step 1: Write failing test**

`tests/frontend/test_data_viewer.py`:

```python
import pandas as pd
import numpy as np
from simple_trader.frontend.data_viewer import DataViewer


def _make_wide_df(rows: int = 50) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=rows, freq="1min")
    closes = 15.0 + np.sin(np.linspace(0, 4 * np.pi, rows))
    return pd.DataFrame({
        "1_close":   closes,
        "1_rsi_14":  np.linspace(30, 70, rows),
        "15_close":  closes * 1.001,
        "15_rsi_14": np.linspace(35, 65, rows),
    }, index=idx)


def test_viewer_slice_returns_subset():
    df = _make_wide_df(50)
    viewer = DataViewer(df)
    sliced = viewer.slice(start=10, end=20)
    assert len(sliced) == 10


def test_viewer_get_tf_view_returns_tf_columns_only():
    df = _make_wide_df()
    viewer = DataViewer(df)
    view = viewer.get_tf_view(tf=1)
    assert all(c.startswith("1_") for c in view.columns)
    assert not any(c.startswith("15_") for c in view.columns)


def test_viewer_summary_stats():
    df = _make_wide_df(50)
    viewer = DataViewer(df)
    stats = viewer.summary_stats(tf=1, col="close")
    assert "mean" in stats
    assert "std" in stats
    assert "min" in stats
    assert "max" in stats


def test_viewer_print_summary_does_not_raise(capsys):
    df = _make_wide_df(20)
    viewer = DataViewer(df)
    viewer.print_summary(tf=1)
    out = capsys.readouterr().out
    assert len(out) > 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/frontend/test_data_viewer.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Write `src/simple_trader/frontend/data_viewer.py`**

```python
from typing import Any, Dict
import pandas as pd


class DataViewer:
    """Read interface over the wide DataFrame for analysis and debugging."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def slice(self, start: int, end: int) -> pd.DataFrame:
        return self._df.iloc[start:end]

    def get_tf_view(self, tf: int) -> pd.DataFrame:
        cols = [c for c in self._df.columns if c.startswith(f"{tf}_")]
        return self._df[cols]

    def summary_stats(self, tf: int, col: str) -> Dict[str, Any]:
        series = self._df[f"{tf}_{col}"]
        return {
            "mean": float(series.mean()),
            "std":  float(series.std()),
            "min":  float(series.min()),
            "max":  float(series.max()),
            "count": int(series.count()),
        }

    def print_summary(self, tf: int) -> None:
        tf_cols = [c for c in self._df.columns if c.startswith(f"{tf}_")]
        print(f"TF={tf}min | rows={len(self._df)} | cols={len(tf_cols)}")
        for col in tf_cols[:5]:   # show first 5
            s = self._df[col]
            print(f"  {col}: mean={s.mean():.3f} min={s.min():.3f} max={s.max():.3f}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/frontend/test_data_viewer.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Final full-suite run**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All phases green. Zero failures.

- [ ] **Step 6: Final commit**

```bash
git add src/simple_trader/frontend/data_viewer.py tests/frontend/test_data_viewer.py
git commit -m "feat: add DataViewer for wide DataFrame inspection"
```
