# Phase 4: Strategy Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Depends on Phase 3a (Signals) AND Phase 3b (Position) both completing.

**Goal:** Implement `BaseStrategy` abstract class, `ManualStrategyLong`, `ManualStrategyShort`, and `StrategyManager`.

**Architecture:** Each `Strategy` owns a `SignalManager` with configured signal chains. Its `check()` method evaluates chains and returns a `(StrategyAction, open_price, close_price, stop_price, tf)` tuple. `StrategyManager` collects results from all registered strategies and resolves conflicts by priority.

**Tech Stack:** No new dependencies. Builds on signals (Phase 3a) and position (Phase 3b).

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
src/simple_trader/strategy/
  __init__.py
  base_strategy.py
  manual_long.py
  manual_short.py
  strategy_manager.py
tests/strategy/
  __init__.py
  conftest.py
  test_base_strategy.py
  test_manual_long.py
  test_manual_short.py
  test_strategy_manager.py
```

---

## Task 0: Directory Setup

- [ ] **Step 1: Create directories**

```bash
mkdir -p src/simple_trader/strategy
mkdir -p tests/strategy
touch src/simple_trader/strategy/__init__.py
touch tests/strategy/__init__.py
```

---

## Task 1: BaseStrategy

**Files:**
- Create: `src/simple_trader/strategy/base_strategy.py`
- Create: `tests/strategy/conftest.py`
- Create: `tests/strategy/test_base_strategy.py`

- [ ] **Step 1: Write `tests/strategy/conftest.py`**

```python
import pytest
import pandas as pd
import numpy as np
from simple_trader.data.data_point import LiveDataPoint
from simple_trader.position.position import Position
from simple_trader.position.long_position import LongPosition


def _make_point(tf_values: dict) -> LiveDataPoint:
    """Build LiveDataPoint. tf_values: {tf: {col: [val, ...]}}"""
    ohlc = {}
    for tf, cols in tf_values.items():
        ohlc[tf] = pd.DataFrame({f"{tf}_{c}": v for c, v in cols.items()})
    return LiveDataPoint(ohlc)


def make_idle_position() -> Position:
    return Position(LongPosition("USDT", "LINK", 1000.0, 0.001))


@pytest.fixture
def idle_position():
    return make_idle_position()


@pytest.fixture
def flat_point():
    """Point with rsi=50, close=15.0 on tf=1."""
    return _make_point({1: {"rsi_14": [50.0], "close": [15.0]},
                        15: {"rsi_14": [50.0], "close": [15.0]}})
```

- [ ] **Step 2: Write failing test**

`tests/strategy/test_base_strategy.py`:

```python
import pytest
from simple_trader.strategy.base_strategy import BaseStrategy
from simple_trader.infrastructure.constants import StrategyAction
from tests.strategy.conftest import _make_point, make_idle_position


def test_base_strategy_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BaseStrategy()  # type: ignore[abstract]


def test_subclass_without_check_raises():
    class Bad(BaseStrategy):
        pass
    with pytest.raises(TypeError):
        Bad()


def test_check_returns_tuple_of_5():
    class NoOpStrategy(BaseStrategy):
        def check(self, data_point, position):
            return (StrategyAction.NOTHING, 0.0, 0.0, 0.0, 1)

    s = NoOpStrategy()
    point = _make_point({1: {"close": [15.0]}})
    result = s.check(point, make_idle_position())
    assert len(result) == 5


def test_check_returns_nothing_action_when_no_signal():
    class NoOpStrategy(BaseStrategy):
        def check(self, data_point, position):
            return (StrategyAction.NOTHING, 0.0, 0.0, 0.0, 1)

    s = NoOpStrategy()
    point = _make_point({1: {"close": [15.0]}})
    action, *_ = s.check(point, make_idle_position())
    assert action == StrategyAction.NOTHING
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/strategy/test_base_strategy.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.strategy.base_strategy'`

- [ ] **Step 4: Write `src/simple_trader/strategy/base_strategy.py`**

```python
from abc import ABC, abstractmethod
from typing import Tuple
from ..data.data_point import DataPoint
from ..position.position import Position
from ..infrastructure.constants import StrategyAction

DecisionTuple = Tuple[StrategyAction, float, float, float, int]
"""(action, open_price, close_price, stop_price, tf_minutes)"""


class BaseStrategy(ABC):
    """
    Abstract base for all trading strategies.

    Each strategy owns its own SignalManager with configured chains.
    check() is called every tick and returns a 5-tuple. Returning
    StrategyAction.NOTHING means no trade decision this tick.
    """

    @abstractmethod
    def check(self, data_point: DataPoint, position: Position) -> DecisionTuple:
        """
        Evaluate signals and return a trading decision.

        Returns:
            (action, open_price, close_price, stop_price, tf_minutes)
            Return (StrategyAction.NOTHING, 0, 0, 0, 0) when no action.
        """
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/strategy/test_base_strategy.py -v
```

Expected: `4 passed`

- [ ] **Step 6: Commit**

```bash
git add src/simple_trader/strategy/base_strategy.py tests/strategy/conftest.py tests/strategy/test_base_strategy.py
git commit -m "feat: add BaseStrategy abstract class"
```

---

## Task 2: ManualStrategyLong

**Files:**
- Create: `src/simple_trader/strategy/manual_long.py`
- Create: `tests/strategy/test_manual_long.py`

`ManualStrategyLong` enters long when CCI crosses below -100 (oversold) and closes when CCI crosses above +100. Stop-loss is set at a fixed percentage below entry.

- [ ] **Step 1: Write failing test**

`tests/strategy/test_manual_long.py`:

```python
import pytest
from simple_trader.strategy.manual_long import ManualStrategyLong
from simple_trader.infrastructure.constants import StrategyAction, PositionState
from tests.strategy.conftest import _make_point, make_idle_position


def _pt(cci: float, close: float = 15.0, tf: int = 15) -> object:
    return _make_point({tf: {"cci_20": [90.0, cci], "close": [close, close]}})


def test_manual_long_returns_nothing_when_cci_neutral():
    strat = ManualStrategyLong(tf=15, stop_pct=0.02)
    point = _pt(cci=0.0)
    action, *_ = strat.check(point, make_idle_position())
    assert action == StrategyAction.NOTHING


def test_manual_long_opens_when_cci_crosses_below_minus100():
    strat = ManualStrategyLong(tf=15, stop_pct=0.02)
    # First tick: cci=90 (above -100) to set previous value
    strat.check(_pt(cci=90.0), make_idle_position())
    # Second tick: cci crosses below -100
    action, open_p, close_p, stop_p, tf = strat.check(
        _pt(cci=-110.0, close=15.0), make_idle_position()
    )
    assert action == StrategyAction.OPEN_LONG
    assert open_p == pytest.approx(15.0)
    assert stop_p < open_p   # stop is below entry for long


def test_manual_long_closes_when_cci_crosses_above_100():
    from simple_trader.position.position import Position
    from simple_trader.position.long_position import LongPosition
    strat = ManualStrategyLong(tf=15, stop_pct=0.02)
    pos = Position(LongPosition("USDT", "LINK", 1000.0, 0.001))
    pos.open(15.0, 17.0, 14.5)
    pos.record_entry_fill(10.0, 15.0)
    # CCI crosses above 100 (prev=50, current=110)
    point = _make_point({15: {"cci_20": [50.0, 110.0], "close": [15.0, 15.5]}})
    action, *_ = strat.check(point, pos)
    assert action == StrategyAction.CLOSE_LONG


def test_manual_long_uses_configured_tf():
    strat = ManualStrategyLong(tf=60, stop_pct=0.02)
    assert strat.tf == 60
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/strategy/test_manual_long.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.strategy.manual_long'`

- [ ] **Step 3: Write `src/simple_trader/strategy/manual_long.py`**

```python
from typing import Tuple
from .base_strategy import BaseStrategy, DecisionTuple
from ..signals.signal_chain import SignalChain
from ..signals.signal_manager import SignalManager
from ..signals.atomic import CrossDown, CrossUp
from ..data.data_point import DataPoint
from ..position.position import Position
from ..infrastructure.constants import StrategyAction, PositionState


class ManualStrategyLong(BaseStrategy):
    """
    CCI-based manual long strategy.

    Entry:  CCI[tf] crosses below -100 (oversold)
    Exit:   CCI[tf] crosses above +100 (overbought)
    Stop:   `stop_pct` below entry price
    """

    def __init__(self, tf: int = 15, stop_pct: float = 0.02) -> None:
        self.tf = tf
        self.stop_pct = stop_pct
        self._signal_mgr = SignalManager()

        entry_chain = SignalChain(
            "long_cci_entry",
            result_action=StrategyAction.OPEN_LONG,
            tf=tf,
        )
        entry_chain.add(CrossDown("cci_20", tf, threshold=-100.0))
        self._signal_mgr.add(entry_chain)

        exit_chain = SignalChain(
            "long_cci_exit",
            result_action=StrategyAction.CLOSE_LONG,
            tf=tf,
        )
        exit_chain.add(CrossUp("cci_20", tf, threshold=100.0))
        self._signal_mgr.add(exit_chain)

    def check(self, data_point: DataPoint, position: Position) -> DecisionTuple:
        completed = self._signal_mgr.check(data_point)

        for chain in completed:
            action = chain.result_action

            if action == StrategyAction.OPEN_LONG:
                if position.state == PositionState.WAIT:
                    open_price = data_point.get("close", self.tf)
                    stop_price = open_price * (1 - self.stop_pct)
                    close_price = open_price * (1 + self.stop_pct * 3)
                    return (StrategyAction.OPEN_LONG, open_price, close_price, stop_price, self.tf)

            if action == StrategyAction.CLOSE_LONG:
                if position.state in (PositionState.WAIT_SAFETY_BUY, PositionState.WAIT_BUY):
                    close_price = data_point.get("close", self.tf)
                    return (StrategyAction.CLOSE_LONG, 0.0, close_price, 0.0, self.tf)

        return (StrategyAction.NOTHING, 0.0, 0.0, 0.0, 0)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/strategy/test_manual_long.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/strategy/manual_long.py tests/strategy/test_manual_long.py
git commit -m "feat: add ManualStrategyLong CCI-based entry/exit strategy"
```

---

## Task 3: ManualStrategyShort

**Files:**
- Create: `src/simple_trader/strategy/manual_short.py`
- Create: `tests/strategy/test_manual_short.py`

Mirror of `ManualStrategyLong` but inverted: entry when CCI crosses above +100, exit when CCI crosses below -100.

- [ ] **Step 1: Write failing test**

`tests/strategy/test_manual_short.py`:

```python
from simple_trader.strategy.manual_short import ManualStrategyShort
from simple_trader.infrastructure.constants import StrategyAction
from tests.strategy.conftest import _make_point, make_idle_position


def _pt(cci: float, close: float = 15.0, tf: int = 15) -> object:
    return _make_point({tf: {"cci_20": [0.0, cci], "close": [close, close]}})


def test_short_returns_nothing_when_cci_neutral():
    strat = ManualStrategyShort(tf=15, stop_pct=0.02)
    action, *_ = strat.check(_pt(50.0), make_idle_position())
    assert action == StrategyAction.NOTHING


def test_short_opens_when_cci_crosses_above_100():
    strat = ManualStrategyShort(tf=15, stop_pct=0.02)
    strat.check(_pt(0.0), make_idle_position())   # set prev
    action, open_p, _, stop_p, _ = strat.check(_pt(110.0, close=15.0), make_idle_position())
    assert action == StrategyAction.OPEN_SHORT
    assert stop_p > open_p   # stop above entry for short


def test_short_uses_configured_tf():
    strat = ManualStrategyShort(tf=60)
    assert strat.tf == 60
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/strategy/test_manual_short.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.strategy.manual_short'`

- [ ] **Step 3: Write `src/simple_trader/strategy/manual_short.py`**

```python
from .base_strategy import BaseStrategy, DecisionTuple
from ..signals.signal_chain import SignalChain
from ..signals.signal_manager import SignalManager
from ..signals.atomic import CrossUp, CrossDown
from ..data.data_point import DataPoint
from ..position.position import Position
from ..infrastructure.constants import StrategyAction, PositionState


class ManualStrategyShort(BaseStrategy):
    """
    CCI-based manual short strategy.

    Entry:  CCI[tf] crosses above +100 (overbought)
    Exit:   CCI[tf] crosses below -100 (oversold)
    Stop:   `stop_pct` above entry price
    """

    def __init__(self, tf: int = 15, stop_pct: float = 0.02) -> None:
        self.tf = tf
        self.stop_pct = stop_pct
        self._signal_mgr = SignalManager()

        entry_chain = SignalChain("short_cci_entry", StrategyAction.OPEN_SHORT, tf)
        entry_chain.add(CrossUp("cci_20", tf, threshold=100.0))
        self._signal_mgr.add(entry_chain)

        exit_chain = SignalChain("short_cci_exit", StrategyAction.CLOSE_SHORT, tf)
        exit_chain.add(CrossDown("cci_20", tf, threshold=-100.0))
        self._signal_mgr.add(exit_chain)

    def check(self, data_point: DataPoint, position: Position) -> DecisionTuple:
        completed = self._signal_mgr.check(data_point)

        for chain in completed:
            action = chain.result_action

            if action == StrategyAction.OPEN_SHORT:
                if position.state == PositionState.WAIT:
                    open_price = data_point.get("close", self.tf)
                    stop_price = open_price * (1 + self.stop_pct)
                    close_price = open_price * (1 - self.stop_pct * 3)
                    return (StrategyAction.OPEN_SHORT, open_price, close_price, stop_price, self.tf)

            if action == StrategyAction.CLOSE_SHORT:
                if position.state in (PositionState.WAIT_SAFETY_SELL, PositionState.WAIT_SELL):
                    close_price = data_point.get("close", self.tf)
                    return (StrategyAction.CLOSE_SHORT, 0.0, close_price, 0.0, self.tf)

        return (StrategyAction.NOTHING, 0.0, 0.0, 0.0, 0)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/strategy/test_manual_short.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/strategy/manual_short.py tests/strategy/test_manual_short.py
git commit -m "feat: add ManualStrategyShort CCI-based short strategy"
```

---

## Task 4: StrategyManager

**Files:**
- Create: `src/simple_trader/strategy/strategy_manager.py`
- Create: `tests/strategy/test_strategy_manager.py`

- [ ] **Step 1: Write failing test**

`tests/strategy/test_strategy_manager.py`:

```python
import pytest
from unittest.mock import MagicMock
from simple_trader.strategy.strategy_manager import StrategyManager
from simple_trader.strategy.base_strategy import BaseStrategy
from simple_trader.infrastructure.constants import StrategyAction
from tests.strategy.conftest import make_idle_position, _make_point


def _noop_strategy(action=StrategyAction.NOTHING) -> BaseStrategy:
    s = MagicMock(spec=BaseStrategy)
    s.check.return_value = (action, 15.0, 17.0, 14.0, 15)
    return s


def _pt():
    return _make_point({15: {"close": [15.0], "cci_20": [0.0]}})


def test_manager_starts_empty():
    mgr = StrategyManager()
    assert mgr.strategies == []


def test_manager_check_returns_nothing_when_all_nothing():
    mgr = StrategyManager()
    mgr.add(_noop_strategy(StrategyAction.NOTHING))
    action, *_ = mgr.check(_pt(), make_idle_position())
    assert action == StrategyAction.NOTHING


def test_manager_returns_first_non_nothing_action():
    mgr = StrategyManager()
    mgr.add(_noop_strategy(StrategyAction.NOTHING))
    mgr.add(_noop_strategy(StrategyAction.OPEN_LONG))
    action, open_p, close_p, stop_p, tf = mgr.check(_pt(), make_idle_position())
    assert action == StrategyAction.OPEN_LONG


def test_manager_passes_position_to_each_strategy():
    mgr = StrategyManager()
    s = _noop_strategy()
    mgr.add(s)
    pos = make_idle_position()
    mgr.check(_pt(), pos)
    s.check.assert_called_once()
    assert s.check.call_args[0][1] is pos


def test_manager_with_no_strategies_returns_nothing():
    mgr = StrategyManager()
    action, *_ = mgr.check(_pt(), make_idle_position())
    assert action == StrategyAction.NOTHING
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/strategy/test_strategy_manager.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.strategy.strategy_manager'`

- [ ] **Step 3: Write `src/simple_trader/strategy/strategy_manager.py`**

```python
from typing import List
from .base_strategy import BaseStrategy, DecisionTuple
from ..data.data_point import DataPoint
from ..position.position import Position
from ..infrastructure.constants import StrategyAction


class StrategyManager:
    """
    Coordinates multiple strategies and resolves their decisions.

    Evaluation order: strategies are checked in registration order.
    The first strategy that returns a non-NOTHING action wins.
    This simple priority model works for the 1-position-at-a-time system.
    """

    def __init__(self) -> None:
        self.strategies: List[BaseStrategy] = []

    def add(self, strategy: BaseStrategy) -> "StrategyManager":
        self.strategies.append(strategy)
        return self

    def check(
        self, data_point: DataPoint, position: Position
    ) -> DecisionTuple:
        for strategy in self.strategies:
            action, open_p, close_p, stop_p, tf = strategy.check(data_point, position)
            if action != StrategyAction.NOTHING:
                return (action, open_p, close_p, stop_p, tf)
        return (StrategyAction.NOTHING, 0.0, 0.0, 0.0, 0)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/strategy/test_strategy_manager.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Run full Phase 4 test suite**

```bash
pytest tests/strategy/ -v
```

Expected: `16+ passed, 0 failed`

- [ ] **Step 6: Commit**

```bash
git add src/simple_trader/strategy/ tests/strategy/
git commit -m "feat: add strategy module — BaseStrategy, ManualStrategyLong/Short, StrategyManager"
```
