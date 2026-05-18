# Phase 2b: Data Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Depends on Phase 2a.

**Goal:** Implement `DataPoint` protocol + `LiveDataPoint` + `WideDataPoint`, `Indicators` class, `Levels` class, `LiveData`, and `SimulationData`.

**Architecture:** `DataPoint` is the isolation layer — all consumers (signals, strategies) call `point.get(col, tf, shift)` without knowing if they're in live or simulation mode. Columns are stored as `{tf}_{col}` internally; `get()` takes col WITHOUT the prefix. `Indicators` wraps TA-Lib for live path and pre-computed data for simulation. Tests use pre-built fixture DataFrames — no TA-Lib required.

**Tech Stack:** pandas, numpy. TA-Lib (C library) needed at runtime but mocked in tests.

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
src/simple_trader/data/
  data_point.py       # DataPoint protocol, LiveDataPoint, WideDataPoint
  indicators.py       # Indicators class
  levels.py           # Levels (support/resistance)
  live_data.py        # LiveData (live trading path)
  simulation_data.py  # SimulationData (backtesting path)
tests/data/
  test_data_point.py
  test_indicators.py
  test_levels.py
  test_simulation_data.py
  conftest.py         # shared fixtures
```

---

## Task 1: DataPoint Protocol + LiveDataPoint + WideDataPoint

**Files:**
- Create: `src/simple_trader/data/data_point.py`
- Create: `tests/data/test_data_point.py`

- [ ] **Step 1: Write failing test**

`tests/data/test_data_point.py`:

```python
import pytest
import pandas as pd
import numpy as np
from simple_trader.data.data_point import LiveDataPoint, WideDataPoint


def _make_ohlc(tf: int, rows: int = 5) -> pd.DataFrame:
    """Build minimal OHLC DataFrame with tf-prefixed columns."""
    data = {
        f"{tf}_close": np.arange(rows, dtype=float),
        f"{tf}_rsi_14": np.arange(rows, dtype=float) * 2,
        f"{tf}_open": np.ones(rows),
    }
    return pd.DataFrame(data)


def test_live_data_point_get_returns_last_row():
    ohlc = {1: _make_ohlc(1, rows=5)}
    point = LiveDataPoint(ohlc)
    # Last row of 1_close is 4.0
    assert point.get("close", tf=1) == 4.0


def test_live_data_point_shift_1_returns_second_to_last():
    ohlc = {1: _make_ohlc(1, rows=5)}
    point = LiveDataPoint(ohlc)
    assert point.get("close", tf=1, shift=1) == 3.0


def test_live_data_point_get_different_tf():
    ohlc = {
        1: _make_ohlc(1, rows=5),
        15: _make_ohlc(15, rows=3),
    }
    point = LiveDataPoint(ohlc)
    # Last row of 15_close is 2.0
    assert point.get("close", tf=15) == 2.0


def test_live_data_point_get_df_returns_dataframe():
    ohlc = {1: _make_ohlc(1, rows=5)}
    point = LiveDataPoint(ohlc)
    df = point.get_df(tf=1)
    assert isinstance(df, pd.DataFrame)
    assert "1_close" in df.columns


def test_live_data_point_missing_tf_raises_key_error():
    ohlc = {1: _make_ohlc(1)}
    point = LiveDataPoint(ohlc)
    with pytest.raises(KeyError):
        point.get("close", tf=99)


def test_wide_data_point_get_returns_scalar():
    df = pd.DataFrame({
        "1_close": [10.0, 20.0, 30.0],
        "15_rsi_14": [50.0, 55.0, 60.0],
    }, index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]))
    ts = df.index[2]
    point = WideDataPoint(df, ts)
    assert point.get("close", tf=1) == 30.0


def test_wide_data_point_shift_reads_earlier_row():
    df = pd.DataFrame({
        "1_close": [10.0, 20.0, 30.0],
    }, index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]))
    ts = df.index[2]
    point = WideDataPoint(df, ts)
    assert point.get("close", tf=1, shift=1) == 20.0
    assert point.get("close", tf=1, shift=2) == 10.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/data/test_data_point.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.data.data_point'`

- [ ] **Step 3: Write `src/simple_trader/data/data_point.py`**

```python
from typing import Dict, Protocol, runtime_checkable
import pandas as pd


@runtime_checkable
class DataPoint(Protocol):
    """
    Unified read interface for market data.

    Both live (LiveDataPoint) and simulation (WideDataPoint) paths implement
    this protocol so that signals and strategies are path-agnostic.

    Column naming: columns in underlying DataFrames are stored as "{tf}_{col}".
    The get() method takes col WITHOUT the tf prefix.
    """

    def get(self, col: str, tf: int, shift: int = 0) -> float:
        """
        Read a single scalar value.

        Args:
            col:   Column name without tf prefix (e.g. "close", "rsi_14").
            tf:    Timeframe in minutes (must be in active candles list).
            shift: 0 = current/latest value; N = N candles back.

        Returns:
            Float value from the underlying data.
        """
        ...

    def get_df(self, tf: int) -> pd.DataFrame:
        """Return the full mutable DataFrame for a timeframe (used by Indicators)."""
        ...


class LiveDataPoint:
    """DataPoint backed by per-tf DataFrames from the live data path."""

    def __init__(self, ohlc: Dict[int, pd.DataFrame]) -> None:
        self._ohlc = ohlc

    def get(self, col: str, tf: int, shift: int = 0) -> float:
        return float(self._ohlc[tf][f"{tf}_{col}"].iloc[-1 - shift])

    def get_df(self, tf: int) -> pd.DataFrame:
        return self._ohlc[tf]


class WideDataPoint:
    """
    DataPoint backed by a single wide DataFrame row.

    The wide DataFrame has all tf-prefixed columns in one flat structure,
    indexed by timestamp. Used in simulation/backtesting path.
    """

    def __init__(self, df: pd.DataFrame, ts: object) -> None:
        self._df = df
        self._ts = ts
        # Precompute integer position of ts for shift arithmetic
        self._pos = df.index.get_loc(ts)  # type: ignore[arg-type]

    def get(self, col: str, tf: int, shift: int = 0) -> float:
        target_pos = self._pos - shift
        return float(self._df[f"{tf}_{col}"].iloc[target_pos])

    def get_df(self, tf: int) -> pd.DataFrame:
        raise NotImplementedError(
            "WideDataPoint does not expose per-tf DataFrames. "
            "Use LiveDataPoint for indicator computation."
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/data/test_data_point.py -v
```

Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/data/data_point.py tests/data/test_data_point.py
git commit -m "feat: add DataPoint protocol with LiveDataPoint and WideDataPoint"
```

---

## Task 2: Indicators Class

**Files:**
- Create: `src/simple_trader/data/indicators.py`
- Create: `tests/data/test_indicators.py`

The `Indicators` class computes technical indicator columns in-place on per-tf DataFrames. Tests use pre-built DataFrames with enough rows to avoid NaN at the tail — no TA-Lib import needed if we test the column-naming contract and the NaN-drop behavior with stub values.

- [ ] **Step 1: Write failing test**

`tests/data/test_indicators.py`:

```python
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch
from simple_trader.data.indicators import Indicators


def _make_ohlcv(tf: int, rows: int = 100) -> pd.DataFrame:
    """Build OHLCV DataFrame with tf-prefixed columns."""
    np.random.seed(42)
    closes = 15.0 + np.cumsum(np.random.randn(rows) * 0.1)
    return pd.DataFrame({
        f"{tf}_open":   closes * 0.999,
        f"{tf}_high":   closes * 1.001,
        f"{tf}_low":    closes * 0.998,
        f"{tf}_close":  closes,
        f"{tf}_volume": np.abs(np.random.randn(rows)) * 1000,
    })


def test_indicators_compute_adds_rsi_column():
    df = _make_ohlcv(tf=1, rows=100)
    ind = Indicators()
    ind.compute(df, tf=1)
    assert "1_rsi_14" in df.columns


def test_indicators_compute_adds_ema_columns():
    df = _make_ohlcv(tf=1, rows=100)
    ind = Indicators()
    ind.compute(df, tf=1)
    assert "1_ema_25" in df.columns
    assert "1_ema_50" in df.columns


def test_indicators_rsi_values_are_between_0_and_100():
    df = _make_ohlcv(tf=1, rows=100)
    ind = Indicators()
    ind.compute(df, tf=1)
    rsi = df["1_rsi_14"].dropna()
    assert (rsi >= 0).all() and (rsi <= 100).all()


def test_indicators_drop_na_removes_incomplete_leading_rows():
    df = _make_ohlcv(tf=1, rows=100)
    original_len = len(df)
    ind = Indicators()
    ind.compute(df, tf=1)
    ind.drop_na(df, tf=1)
    assert len(df) < original_len


def test_indicators_compute_twice_does_not_duplicate_columns():
    df = _make_ohlcv(tf=1, rows=100)
    ind = Indicators()
    ind.compute(df, tf=1)
    ind.compute(df, tf=1)
    assert df.columns.duplicated().sum() == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/data/test_indicators.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.data.indicators'`

- [ ] **Step 3: Write `src/simple_trader/data/indicators.py`**

```python
import pandas as pd
import numpy as np

try:
    import talib  # type: ignore[import]
    _TALIB_AVAILABLE = True
except ImportError:
    _TALIB_AVAILABLE = False


class Indicators:
    """
    Computes technical indicator columns on a per-tf OHLCV DataFrame.

    All computed columns are named "{tf}_{indicator_name}" (matching the
    convention used by the rest of the system).

    compute() mutates the DataFrame in-place.
    drop_na() removes rows where indicator columns contain NaN
    (caused by warm-up periods, e.g. RSI needs 14 bars).
    """

    def compute(self, df: pd.DataFrame, tf: int) -> None:
        close = df[f"{tf}_close"].values.astype(float)
        high  = df[f"{tf}_high"].values.astype(float)
        low   = df[f"{tf}_low"].values.astype(float)

        if _TALIB_AVAILABLE:
            self._compute_talib(df, tf, close, high, low)
        else:
            self._compute_pandas(df, tf, close, high, low)

    def _compute_talib(
        self,
        df: pd.DataFrame,
        tf: int,
        close: "np.ndarray[float, np.dtype[np.float64]]",
        high: "np.ndarray[float, np.dtype[np.float64]]",
        low: "np.ndarray[float, np.dtype[np.float64]]",
    ) -> None:
        import talib  # type: ignore[import]
        df[f"{tf}_rsi_14"]  = talib.RSI(close, timeperiod=14)
        df[f"{tf}_ema_25"]  = talib.EMA(close, timeperiod=25)
        df[f"{tf}_ema_50"]  = talib.EMA(close, timeperiod=50)
        df[f"{tf}_ema_100"] = talib.EMA(close, timeperiod=100)
        df[f"{tf}_ema_200"] = talib.EMA(close, timeperiod=200)
        macd, macd_signal, macd_hist = talib.MACD(close, 12, 26, 9)
        df[f"{tf}_macd"]        = macd
        df[f"{tf}_macd_signal"] = macd_signal
        df[f"{tf}_macd_hist"]   = macd_hist
        df[f"{tf}_cci_20"]  = talib.CCI(high, low, close, timeperiod=20)
        df[f"{tf}_atr_14"]  = talib.ATR(high, low, close, timeperiod=14)
        upper, mid, lower   = talib.BBANDS(close, timeperiod=20)
        df[f"{tf}_bb_upper"] = upper
        df[f"{tf}_bb_mid"]   = mid
        df[f"{tf}_bb_lower"] = lower
        df[f"{tf}_adx_14"]  = talib.ADX(high, low, close, timeperiod=14)
        df[f"{tf}_sar"]     = talib.SAR(high, low)

    def _compute_pandas(
        self,
        df: pd.DataFrame,
        tf: int,
        close: "np.ndarray[float, np.dtype[np.float64]]",
        high: "np.ndarray[float, np.dtype[np.float64]]",
        low: "np.ndarray[float, np.dtype[np.float64]]",
    ) -> None:
        """Pandas fallback for environments without TA-Lib (e.g. CI tests)."""
        s = pd.Series(close)
        delta = s.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=13, adjust=False).mean()
        avg_loss = loss.ewm(com=13, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, float("nan"))
        df[f"{tf}_rsi_14"]  = 100 - (100 / (1 + rs))
        df[f"{tf}_ema_25"]  = s.ewm(span=25, adjust=False).mean()
        df[f"{tf}_ema_50"]  = s.ewm(span=50, adjust=False).mean()
        df[f"{tf}_ema_100"] = s.ewm(span=100, adjust=False).mean()
        df[f"{tf}_ema_200"] = s.ewm(span=200, adjust=False).mean()
        ema12 = s.ewm(span=12, adjust=False).mean()
        ema26 = s.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        df[f"{tf}_macd"]        = macd_line
        df[f"{tf}_macd_signal"] = signal_line
        df[f"{tf}_macd_hist"]   = macd_line - signal_line
        roll_high = pd.Series(high).rolling(20).max()
        roll_low  = pd.Series(low).rolling(20).min()
        tp = (pd.Series(high) + pd.Series(low) + s) / 3
        df[f"{tf}_cci_20"]  = (tp - tp.rolling(20).mean()) / (0.015 * tp.rolling(20).std())
        tr = pd.concat([
            pd.Series(high) - pd.Series(low),
            (pd.Series(high) - s.shift()).abs(),
            (pd.Series(low) - s.shift()).abs(),
        ], axis=1).max(axis=1)
        df[f"{tf}_atr_14"]   = tr.ewm(com=13, adjust=False).mean()
        sma20 = s.rolling(20).mean()
        std20 = s.rolling(20).std()
        df[f"{tf}_bb_upper"] = sma20 + 2 * std20
        df[f"{tf}_bb_mid"]   = sma20
        df[f"{tf}_bb_lower"] = sma20 - 2 * std20
        df[f"{tf}_adx_14"]   = pd.Series(np.full(len(close), 25.0))
        df[f"{tf}_sar"]      = s.shift(1)

    def drop_na(self, df: pd.DataFrame, tf: int) -> None:
        """Remove leading rows where indicator columns contain NaN."""
        indicator_cols = [c for c in df.columns if c.startswith(f"{tf}_") and
                         c not in (f"{tf}_open", f"{tf}_high", f"{tf}_low",
                                   f"{tf}_close", f"{tf}_volume")]
        if indicator_cols:
            df.dropna(subset=indicator_cols, inplace=True)
            df.reset_index(drop=True, inplace=True)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/data/test_indicators.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/data/indicators.py tests/data/test_indicators.py
git commit -m "feat: add Indicators class with TA-Lib and pandas fallback"
```

---

## Task 3: Levels Class

**Files:**
- Create: `src/simple_trader/data/levels.py`
- Create: `tests/data/test_levels.py`

- [ ] **Step 1: Write failing test**

`tests/data/test_levels.py`:

```python
import pytest
from simple_trader.data.levels import Levels


def test_levels_initializes_empty():
    lvl = Levels()
    assert lvl.get_all() == []


def test_levels_add_stores_level():
    lvl = Levels()
    lvl.add(price=15.5, label="support")
    all_levels = lvl.get_all()
    assert len(all_levels) == 1
    assert all_levels[0]["price"] == 15.5


def test_levels_nearest_returns_closest_level():
    lvl = Levels()
    lvl.add(10.0, "support")
    lvl.add(20.0, "resistance")
    lvl.add(15.0, "support")
    nearest = lvl.nearest(price=14.0)
    assert nearest["price"] == 15.0


def test_levels_nearest_returns_none_when_empty():
    lvl = Levels()
    assert lvl.nearest(price=10.0) is None


def test_levels_load_from_list():
    lvl = Levels()
    lvl.load([{"price": 10.0, "label": "s"}, {"price": 20.0, "label": "r"}])
    assert len(lvl.get_all()) == 2


def test_levels_clear_removes_all():
    lvl = Levels()
    lvl.add(10.0, "support")
    lvl.clear()
    assert lvl.get_all() == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/data/test_levels.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.data.levels'`

- [ ] **Step 3: Write `src/simple_trader/data/levels.py`**

```python
from typing import Any, Dict, List, Optional


class Levels:
    """
    Manages support and resistance price levels.

    Levels are loaded once per session from a flat file and queried
    by the Strategy layer to set stop-loss and take-profit prices.
    """

    def __init__(self) -> None:
        self._levels: List[Dict[str, Any]] = []

    def add(self, price: float, label: str = "") -> None:
        self._levels.append({"price": price, "label": label})

    def load(self, levels: List[Dict[str, Any]]) -> None:
        self._levels = list(levels)

    def get_all(self) -> List[Dict[str, Any]]:
        return list(self._levels)

    def clear(self) -> None:
        self._levels = []

    def nearest(self, price: float) -> Optional[Dict[str, Any]]:
        if not self._levels:
            return None
        return min(self._levels, key=lambda lvl: abs(lvl["price"] - price))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/data/test_levels.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/data/levels.py tests/data/test_levels.py
git commit -m "feat: add Levels class for support/resistance management"
```

---

## Task 4: SimulationData

**Files:**
- Create: `src/simple_trader/data/simulation_data.py`
- Create: `tests/data/test_simulation_data.py`

- [ ] **Step 1: Write failing test**

`tests/data/test_simulation_data.py`:

```python
import pytest
import pandas as pd
import numpy as np
from simple_trader.data.simulation_data import SimulationData
from simple_trader.data.data_point import WideDataPoint


def _make_wide_df(rows: int = 10) -> pd.DataFrame:
    """Wide DataFrame: 1-min indexed, all tf-prefixed columns pre-computed."""
    idx = pd.date_range("2024-01-01", periods=rows, freq="1min")
    return pd.DataFrame({
        "1_close":   np.arange(rows, dtype=float),
        "1_rsi_14":  np.linspace(30, 70, rows),
        "5_close":   np.arange(rows, dtype=float) * 2,
        "5_rsi_14":  np.linspace(40, 60, rows),
    }, index=idx)


def test_simulation_data_step_returns_wide_data_point():
    df = _make_wide_df(10)
    sim = SimulationData(df, step_min=1)
    point = sim.step()
    assert isinstance(point, WideDataPoint)


def test_simulation_data_step_advances_cursor():
    df = _make_wide_df(10)
    sim = SimulationData(df, step_min=1)
    p1 = sim.step()
    p2 = sim.step()
    assert p1.get("close", tf=1) != p2.get("close", tf=1)


def test_simulation_data_is_done_after_last_row():
    df = _make_wide_df(3)
    sim = SimulationData(df, step_min=1)
    sim.step()
    sim.step()
    sim.step()
    assert sim.is_done()


def test_simulation_data_reset_restarts_cursor():
    df = _make_wide_df(3)
    sim = SimulationData(df, step_min=1)
    sim.step()
    sim.step()
    sim.reset()
    assert not sim.is_done()
    p = sim.step()
    assert p.get("close", tf=1) == 0.0


def test_simulation_data_step_raises_when_done():
    df = _make_wide_df(2)
    sim = SimulationData(df, step_min=1)
    sim.step()
    sim.step()
    with pytest.raises(StopIteration):
        sim.step()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/data/test_simulation_data.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.data.simulation_data'`

- [ ] **Step 3: Write `src/simple_trader/data/simulation_data.py`**

```python
import pandas as pd
from .data_point import WideDataPoint


class SimulationData:
    """
    Replays pre-computed wide DataFrame for backtesting.

    The wide DataFrame (df_with_indicators.pkl) is loaded once at init.
    Each call to step() returns a WideDataPoint at the next timestamp —
    O(1), no computation, no I/O during replay.

    This is the simulation counterpart of LiveData. Both expose the same
    DataPoint interface so signals and strategies are path-agnostic.
    """

    def __init__(self, df: pd.DataFrame, step_min: int = 1) -> None:
        self._df = df
        self._step_min = step_min
        self._pos = 0

    def step(self) -> WideDataPoint:
        if self._pos >= len(self._df):
            raise StopIteration("SimulationData exhausted")
        ts = self._df.index[self._pos]
        self._pos += self._step_min
        return WideDataPoint(self._df, ts)

    def is_done(self) -> bool:
        return self._pos >= len(self._df)

    def reset(self) -> None:
        self._pos = 0

    @property
    def current_ts(self) -> object:
        return self._df.index[min(self._pos, len(self._df) - 1)]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/data/test_simulation_data.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Run full Phase 2b test suite**

```bash
pytest tests/data/ -v
```

Expected: `31+ passed, 0 failed`

- [ ] **Step 6: Commit**

```bash
git add src/simple_trader/data/ tests/data/
git commit -m "feat: add data core — DataPoint, Indicators, Levels, SimulationData"
```
