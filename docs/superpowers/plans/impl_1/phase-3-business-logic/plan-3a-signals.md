# Phase 3a: Signals Module Implementation Plan (PARALLEL — Agent A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Depends on Phase 2b. Runs in parallel with Phase 3b (Position).

**Goal:** Implement `BaseSignal`, atomic signals (Less, Greater, CrossUp, CrossDown), combinator signals (And, Or, Not, Continuous, History), `SignalChain`, and `SignalManager`.

**Architecture:** `BaseSignal` is an ABC. Atomic signals each read one value from a `DataPoint` and compare it to a threshold. `SignalChain` is a sequential state machine — `cur_pos` advances only when `signals[cur_pos].check()` returns True. `SignalManager` owns multiple `SignalChain` instances and collects the ones that complete each tick.

**Tech Stack:** No external dependencies beyond Phase 2b. All tests use fixture `DataPoint` objects.

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
src/simple_trader/signals/
  __init__.py
  base_signal.py
  atomic.py
  combinators.py
  signal_chain.py
  signal_manager.py
tests/signals/
  __init__.py
  test_base_signal.py
  test_atomic.py
  test_combinators.py
  test_signal_chain.py
  test_signal_manager.py
  conftest.py
```

---

## Task 0: Directory Setup

- [ ] **Step 1: Create directories**

```bash
mkdir -p src/simple_trader/signals
mkdir -p tests/signals
touch src/simple_trader/signals/__init__.py
touch tests/signals/__init__.py
```

---

## Task 1: BaseSignal

**Files:**
- Create: `src/simple_trader/signals/base_signal.py`
- Create: `tests/signals/test_base_signal.py`
- Create: `tests/signals/conftest.py`

- [ ] **Step 1: Write `tests/signals/conftest.py`** (shared fixture)

```python
import pytest
import pandas as pd
import numpy as np
from simple_trader.data.data_point import LiveDataPoint


def _make_live_point(values: dict) -> LiveDataPoint:
    """
    Build a LiveDataPoint from a dict of {tf: {col: [values]}}.
    Example: _make_live_point({1: {"rsi_14": [40.0, 50.0]}})
    """
    ohlc = {}
    for tf, cols in values.items():
        data = {f"{tf}_{col}": vals for col, vals in cols.items()}
        ohlc[tf] = pd.DataFrame(data)
    return LiveDataPoint(ohlc)


@pytest.fixture
def point_rsi_50():
    return _make_live_point({1: {"rsi_14": [30.0, 50.0]}, 15: {"rsi_14": [45.0, 55.0]}})


@pytest.fixture
def point_rsi_series():
    """Point with rsi rising: [20, 40, 60, 80]."""
    return _make_live_point({1: {"rsi_14": [20.0, 40.0, 60.0, 80.0]}})
```

- [ ] **Step 2: Write failing test**

`tests/signals/test_base_signal.py`:

```python
import pytest
from simple_trader.signals.base_signal import BaseSignal
from simple_trader.data.data_point import LiveDataPoint
from tests.signals.conftest import _make_live_point


def test_base_signal_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BaseSignal("rsi_14", tf=1)  # type: ignore[abstract]


def test_subclass_without_check_raises():
    class Bad(BaseSignal):
        pass
    with pytest.raises(TypeError):
        Bad("rsi_14", tf=1)


def test_base_signal_get_data_reads_data_point():
    class Probe(BaseSignal):
        def check(self, data_point):
            return self.get_data(data_point) > 0

    probe = Probe("rsi_14", tf=1)
    point = _make_live_point({1: {"rsi_14": [50.0]}})
    assert probe.get_data(point) == 50.0


def test_base_signal_set_shift_updates_shift():
    class Probe(BaseSignal):
        def check(self, data_point):
            return True

    probe = Probe("rsi_14", tf=1, shift=0)
    probe.set_shift(2)
    assert probe.shift == 2


def test_base_signal_reset_is_noop_by_default():
    class Probe(BaseSignal):
        def check(self, data_point):
            return True

    probe = Probe("rsi_14", tf=1)
    probe.reset()  # should not raise
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/signals/test_base_signal.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.signals.base_signal'`

- [ ] **Step 4: Write `src/simple_trader/signals/base_signal.py`**

```python
from abc import ABC, abstractmethod
from ..data.data_point import DataPoint


class BaseSignal(ABC):
    """Abstract base for all trading signals.

    Each signal reads one or more values from a DataPoint and returns
    True (condition met) or False (condition not met).
    """

    def __init__(self, col: str, tf: int, shift: int = 0) -> None:
        self.col = col
        self.tf = tf
        self.shift = shift

    @abstractmethod
    def check(self, data_point: DataPoint) -> bool:
        """Evaluate this signal against the current data point."""

    def get_data(self, data_point: DataPoint) -> float:
        return data_point.get(self.col, self.tf, self.shift)

    def set_shift(self, shift: int) -> None:
        self.shift = shift

    def reset(self) -> None:
        """Reset any internal state. No-op for stateless signals."""
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/signals/test_base_signal.py -v
```

Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add src/simple_trader/signals/base_signal.py tests/signals/test_base_signal.py tests/signals/conftest.py
git commit -m "feat: add BaseSignal abstract class"
```

---

## Task 2: Atomic Signals

**Files:**
- Create: `src/simple_trader/signals/atomic.py`
- Create: `tests/signals/test_atomic.py`

- [ ] **Step 1: Write failing test**

`tests/signals/test_atomic.py`:

```python
import pytest
from simple_trader.signals.atomic import Less, Greater, CrossUp, CrossDown, Equal
from tests.signals.conftest import _make_live_point


def test_less_true_when_value_below_threshold():
    sig = Less("rsi_14", tf=1, threshold=60.0)
    point = _make_live_point({1: {"rsi_14": [50.0]}})
    assert sig.check(point) is True


def test_less_false_when_value_at_threshold():
    sig = Less("rsi_14", tf=1, threshold=50.0)
    point = _make_live_point({1: {"rsi_14": [50.0]}})
    assert sig.check(point) is False


def test_less_false_when_value_above_threshold():
    sig = Less("rsi_14", tf=1, threshold=40.0)
    point = _make_live_point({1: {"rsi_14": [50.0]}})
    assert sig.check(point) is False


def test_greater_true_when_value_above_threshold():
    sig = Greater("rsi_14", tf=1, threshold=40.0)
    point = _make_live_point({1: {"rsi_14": [50.0]}})
    assert sig.check(point) is True


def test_greater_false_at_threshold():
    sig = Greater("rsi_14", tf=1, threshold=50.0)
    point = _make_live_point({1: {"rsi_14": [50.0]}})
    assert sig.check(point) is False


def test_cross_up_true_when_crossing_above():
    # Values: [prev=40, current=60], threshold=50 → cross up
    sig = CrossUp("rsi_14", tf=1, threshold=50.0)
    point = _make_live_point({1: {"rsi_14": [40.0, 60.0]}})
    assert sig.check(point) is True


def test_cross_up_false_when_already_above():
    # Values: [prev=60, current=70] — was already above
    sig = CrossUp("rsi_14", tf=1, threshold=50.0)
    point = _make_live_point({1: {"rsi_14": [60.0, 70.0]}})
    assert sig.check(point) is False


def test_cross_down_true_when_crossing_below():
    # Values: [prev=60, current=40], threshold=50 → cross down
    sig = CrossDown("rsi_14", tf=1, threshold=50.0)
    point = _make_live_point({1: {"rsi_14": [60.0, 40.0]}})
    assert sig.check(point) is True


def test_cross_down_false_when_already_below():
    sig = CrossDown("rsi_14", tf=1, threshold=50.0)
    point = _make_live_point({1: {"rsi_14": [30.0, 40.0]}})
    assert sig.check(point) is False


def test_equal_true_within_tolerance():
    sig = Equal("rsi_14", tf=1, target=50.0, tolerance=1.0)
    point = _make_live_point({1: {"rsi_14": [50.5]}})
    assert sig.check(point) is True


def test_equal_false_outside_tolerance():
    sig = Equal("rsi_14", tf=1, target=50.0, tolerance=0.1)
    point = _make_live_point({1: {"rsi_14": [51.0]}})
    assert sig.check(point) is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/signals/test_atomic.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.signals.atomic'`

- [ ] **Step 3: Write `src/simple_trader/signals/atomic.py`**

```python
from .base_signal import BaseSignal
from ..data.data_point import DataPoint


class Less(BaseSignal):
    """True when col[tf, shift] < threshold."""

    def __init__(self, col: str, tf: int, threshold: float, shift: int = 0) -> None:
        super().__init__(col, tf, shift)
        self.threshold = threshold

    def check(self, data_point: DataPoint) -> bool:
        return self.get_data(data_point) < self.threshold


class Greater(BaseSignal):
    """True when col[tf, shift] > threshold."""

    def __init__(self, col: str, tf: int, threshold: float, shift: int = 0) -> None:
        super().__init__(col, tf, shift)
        self.threshold = threshold

    def check(self, data_point: DataPoint) -> bool:
        return self.get_data(data_point) > self.threshold


class CrossUp(BaseSignal):
    """True on the tick when the value crosses above threshold (prev < thresh <= current)."""

    def __init__(self, col: str, tf: int, threshold: float) -> None:
        super().__init__(col, tf, shift=0)
        self.threshold = threshold

    def check(self, data_point: DataPoint) -> bool:
        current = data_point.get(self.col, self.tf, 0)
        previous = data_point.get(self.col, self.tf, 1)
        return previous < self.threshold <= current


class CrossDown(BaseSignal):
    """True on the tick when the value crosses below threshold (prev > thresh >= current)."""

    def __init__(self, col: str, tf: int, threshold: float) -> None:
        super().__init__(col, tf, shift=0)
        self.threshold = threshold

    def check(self, data_point: DataPoint) -> bool:
        current = data_point.get(self.col, self.tf, 0)
        previous = data_point.get(self.col, self.tf, 1)
        return previous > self.threshold >= current


class Equal(BaseSignal):
    """True when abs(col[tf] - target) <= tolerance."""

    def __init__(
        self, col: str, tf: int, target: float, tolerance: float = 0.0, shift: int = 0
    ) -> None:
        super().__init__(col, tf, shift)
        self.target = target
        self.tolerance = tolerance

    def check(self, data_point: DataPoint) -> bool:
        return abs(self.get_data(data_point) - self.target) <= self.tolerance
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/signals/test_atomic.py -v
```

Expected: `11 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/signals/atomic.py tests/signals/test_atomic.py
git commit -m "feat: add atomic signals (Less, Greater, CrossUp, CrossDown, Equal)"
```

---

## Task 3: Combinator Signals

**Files:**
- Create: `src/simple_trader/signals/combinators.py`
- Create: `tests/signals/test_combinators.py`

- [ ] **Step 1: Write failing test**

`tests/signals/test_combinators.py`:

```python
import pytest
from simple_trader.signals.atomic import Less, Greater
from simple_trader.signals.combinators import And, Or, Not, Continuous, History
from tests.signals.conftest import _make_live_point


def _pt(rsi: float) -> object:
    return _make_live_point({1: {"rsi_14": [rsi]}})


def test_and_true_when_all_true():
    sig = And([Less("rsi_14", 1, 70), Greater("rsi_14", 1, 30)])
    assert sig.check(_pt(50)) is True


def test_and_false_when_any_false():
    sig = And([Less("rsi_14", 1, 70), Greater("rsi_14", 1, 60)])
    assert sig.check(_pt(50)) is False


def test_or_true_when_any_true():
    sig = Or([Less("rsi_14", 1, 30), Greater("rsi_14", 1, 70)])
    assert sig.check(_pt(80)) is True


def test_or_false_when_all_false():
    sig = Or([Less("rsi_14", 1, 30), Greater("rsi_14", 1, 70)])
    assert sig.check(_pt(50)) is False


def test_not_inverts_result():
    sig = Not(Less("rsi_14", 1, 60))
    assert sig.check(_pt(50)) is False   # Less would be True → Not = False
    assert sig.check(_pt(70)) is True    # Less would be False → Not = True


def test_continuous_true_when_n_consecutive_true():
    sig = Continuous(Greater("rsi_14", 1, 30), n=3)
    points = [_pt(50), _pt(50), _pt(50)]
    results = [sig.check(p) for p in points]
    assert results == [False, False, True]


def test_continuous_resets_on_false():
    sig = Continuous(Greater("rsi_14", 1, 30), n=3)
    sig.check(_pt(50))
    sig.check(_pt(50))
    sig.check(_pt(10))  # breaks streak
    sig.check(_pt(50))
    assert sig.check(_pt(50)) is False   # only 2 consecutive again


def test_history_true_if_any_in_window_was_true():
    sig = History(Greater("rsi_14", 1, 60), window=3)
    sig.check(_pt(70))  # tick 1: True
    sig.check(_pt(40))  # tick 2: False
    assert sig.check(_pt(40)) is True   # tick 3: still in 3-tick window


def test_history_false_after_window_expires():
    sig = History(Greater("rsi_14", 1, 60), window=2)
    sig.check(_pt(70))  # tick 1: True
    sig.check(_pt(40))  # tick 2: False
    assert sig.check(_pt(40)) is False  # tick 3: window expired
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/signals/test_combinators.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.signals.combinators'`

- [ ] **Step 3: Write `src/simple_trader/signals/combinators.py`**

```python
from collections import deque
from typing import Deque, List
from .base_signal import BaseSignal
from ..data.data_point import DataPoint


class And(BaseSignal):
    """True when ALL child signals are True on this tick."""

    def __init__(self, signals: List[BaseSignal]) -> None:
        super().__init__(col="", tf=0)
        self.signals = signals

    def check(self, data_point: DataPoint) -> bool:
        return all(s.check(data_point) for s in self.signals)

    def reset(self) -> None:
        for s in self.signals:
            s.reset()


class Or(BaseSignal):
    """True when ANY child signal is True on this tick."""

    def __init__(self, signals: List[BaseSignal]) -> None:
        super().__init__(col="", tf=0)
        self.signals = signals

    def check(self, data_point: DataPoint) -> bool:
        return any(s.check(data_point) for s in self.signals)

    def reset(self) -> None:
        for s in self.signals:
            s.reset()


class Not(BaseSignal):
    """True when the wrapped signal is False."""

    def __init__(self, signal: BaseSignal) -> None:
        super().__init__(col="", tf=0)
        self.signal = signal

    def check(self, data_point: DataPoint) -> bool:
        return not self.signal.check(data_point)

    def reset(self) -> None:
        self.signal.reset()


class Continuous(BaseSignal):
    """True when the wrapped signal has been True for N consecutive ticks."""

    def __init__(self, signal: BaseSignal, n: int) -> None:
        super().__init__(col="", tf=0)
        self.signal = signal
        self.n = n
        self._streak = 0

    def check(self, data_point: DataPoint) -> bool:
        if self.signal.check(data_point):
            self._streak += 1
        else:
            self._streak = 0
        return self._streak >= self.n

    def reset(self) -> None:
        self._streak = 0
        self.signal.reset()


class History(BaseSignal):
    """True if the wrapped signal fired at least once in the last `window` ticks."""

    def __init__(self, signal: BaseSignal, window: int) -> None:
        super().__init__(col="", tf=0)
        self.signal = signal
        self.window = window
        self._history: Deque[bool] = deque(maxlen=window)

    def check(self, data_point: DataPoint) -> bool:
        result = self.signal.check(data_point)
        self._history.append(result)
        return any(self._history)

    def reset(self) -> None:
        self._history.clear()
        self.signal.reset()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/signals/test_combinators.py -v
```

Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/signals/combinators.py tests/signals/test_combinators.py
git commit -m "feat: add combinator signals (And, Or, Not, Continuous, History)"
```

---

## Task 4: SignalChain

**Files:**
- Create: `src/simple_trader/signals/signal_chain.py`
- Create: `tests/signals/test_signal_chain.py`

- [ ] **Step 1: Write failing test**

`tests/signals/test_signal_chain.py`:

```python
import pytest
from simple_trader.signals.signal_chain import SignalChain
from simple_trader.signals.atomic import Greater, Less
from simple_trader.infrastructure.constants import StrategyAction
from tests.signals.conftest import _make_live_point


def _pt(rsi: float) -> object:
    return _make_live_point({1: {"rsi_14": [rsi]}})


def test_chain_starts_at_position_zero():
    chain = SignalChain("test", result_action=StrategyAction.OPEN_LONG, tf=1)
    chain.add(Greater("rsi_14", 1, 30))
    assert chain.cur_pos == 0


def test_chain_advances_when_signal_fires():
    chain = SignalChain("test", result_action=StrategyAction.OPEN_LONG, tf=1)
    chain.add(Greater("rsi_14", 1, 30))
    chain.add(Less("rsi_14", 1, 80))
    chain.check(_pt(50))  # signal[0] fires → cur_pos = 1
    assert chain.cur_pos == 1


def test_chain_does_not_advance_when_signal_false():
    chain = SignalChain("test", result_action=StrategyAction.OPEN_LONG, tf=1)
    chain.add(Greater("rsi_14", 1, 70))  # requires rsi > 70
    chain.check(_pt(50))               # rsi=50, does not fire
    assert chain.cur_pos == 0


def test_chain_complete_returns_true_after_all_signals():
    chain = SignalChain("test", result_action=StrategyAction.OPEN_LONG, tf=1)
    chain.add(Greater("rsi_14", 1, 30))
    chain.add(Less("rsi_14", 1, 80))
    chain.check(_pt(50))
    result = chain.check(_pt(50))
    assert result is True
    assert chain.is_complete


def test_chain_reset_restarts_from_zero():
    chain = SignalChain("test", result_action=StrategyAction.OPEN_LONG, tf=1)
    chain.add(Greater("rsi_14", 1, 30))
    chain.check(_pt(50))
    chain.reset()
    assert chain.cur_pos == 0
    assert not chain.is_complete


def test_chain_check_returns_false_when_not_complete():
    chain = SignalChain("test", result_action=StrategyAction.OPEN_LONG, tf=1)
    chain.add(Greater("rsi_14", 1, 30))
    chain.add(Less("rsi_14", 1, 80))
    result = chain.check(_pt(50))  # only first signal fires
    assert result is False


def test_chain_stores_result_action_and_tf():
    chain = SignalChain("entry", result_action=StrategyAction.OPEN_SHORT, tf=15)
    assert chain.result_action == StrategyAction.OPEN_SHORT
    assert chain.tf == 15
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/signals/test_signal_chain.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.signals.signal_chain'`

- [ ] **Step 3: Write `src/simple_trader/signals/signal_chain.py`**

```python
from typing import List
from .base_signal import BaseSignal
from ..data.data_point import DataPoint
from ..infrastructure.constants import StrategyAction


class SignalChain:
    """
    Sequential state machine: signals must fire in order over successive ticks.

    cur_pos tracks which signal is currently being evaluated. When signals[cur_pos]
    returns True, cur_pos advances. When cur_pos == len(signals), the chain is
    complete and check() returns True.

    State persists across ticks — completion requires all signals to have fired
    in order, not necessarily on the same tick.
    """

    def __init__(
        self,
        name: str,
        result_action: StrategyAction,
        tf: int,
        notify: bool = False,
    ) -> None:
        self.name = name
        self.result_action = result_action
        self.tf = tf
        self.notify = notify
        self.signals: List[BaseSignal] = []
        self.cur_pos = 0

    def add(self, signal: BaseSignal) -> "SignalChain":
        self.signals.append(signal)
        return self

    def check(self, data_point: DataPoint) -> bool:
        if self.cur_pos >= len(self.signals):
            return True
        if self.signals[self.cur_pos].check(data_point):
            self.cur_pos += 1
            if self.notify:
                print(f"[{self.name}] signal {self.cur_pos}/{len(self.signals)} fired")
        return self.cur_pos >= len(self.signals)

    def reset(self) -> None:
        self.cur_pos = 0
        for s in self.signals:
            s.reset()

    @property
    def is_complete(self) -> bool:
        return self.cur_pos >= len(self.signals)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/signals/test_signal_chain.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/signals/signal_chain.py tests/signals/test_signal_chain.py
git commit -m "feat: add SignalChain sequential state machine"
```

---

## Task 5: SignalManager

**Files:**
- Create: `src/simple_trader/signals/signal_manager.py`
- Create: `tests/signals/test_signal_manager.py`

- [ ] **Step 1: Write failing test**

`tests/signals/test_signal_manager.py`:

```python
import pytest
from simple_trader.signals.signal_manager import SignalManager
from simple_trader.signals.signal_chain import SignalChain
from simple_trader.signals.atomic import Greater, Less
from simple_trader.infrastructure.constants import StrategyAction
from tests.signals.conftest import _make_live_point


def _pt(rsi: float) -> object:
    return _make_live_point({1: {"rsi_14": [rsi]}})


def _make_chain(action: StrategyAction, threshold: float) -> SignalChain:
    chain = SignalChain(f"chain_{action.name}", result_action=action, tf=1)
    chain.add(Greater("rsi_14", 1, threshold))
    return chain


def test_manager_starts_empty():
    mgr = SignalManager()
    assert mgr.chains == []


def test_manager_add_chain():
    mgr = SignalManager()
    chain = _make_chain(StrategyAction.OPEN_LONG, 30)
    mgr.add(chain)
    assert len(mgr.chains) == 1


def test_manager_check_returns_completed_chains():
    mgr = SignalManager()
    chain = _make_chain(StrategyAction.OPEN_LONG, 30)  # completes when rsi > 30
    mgr.add(chain)
    completed = mgr.check(_pt(50))  # rsi=50 > 30 → chain completes
    assert len(completed) == 1
    assert completed[0].result_action == StrategyAction.OPEN_LONG


def test_manager_check_returns_empty_when_no_completion():
    mgr = SignalManager()
    chain = _make_chain(StrategyAction.OPEN_LONG, 70)  # requires rsi > 70
    mgr.add(chain)
    completed = mgr.check(_pt(50))
    assert completed == []


def test_manager_resets_completed_chains_after_check():
    mgr = SignalManager()
    chain = _make_chain(StrategyAction.OPEN_LONG, 30)
    mgr.add(chain)
    mgr.check(_pt(50))       # chain completes and is reset
    assert chain.cur_pos == 0


def test_manager_multiple_chains_can_complete_same_tick():
    mgr = SignalManager()
    chain_long  = _make_chain(StrategyAction.OPEN_LONG,  30)
    chain_short = _make_chain(StrategyAction.CLOSE_SHORT, 20)
    mgr.add(chain_long)
    mgr.add(chain_short)
    completed = mgr.check(_pt(50))
    assert len(completed) == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/signals/test_signal_manager.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.signals.signal_manager'`

- [ ] **Step 3: Write `src/simple_trader/signals/signal_manager.py`**

```python
from typing import List
from .signal_chain import SignalChain
from ..data.data_point import DataPoint


class SignalManager:
    """
    Orchestrates multiple SignalChains per tick.

    On each call to check(), evaluates all chains. Chains that complete
    are collected, reset, and returned. Incomplete chains retain their
    cur_pos for the next tick.
    """

    def __init__(self) -> None:
        self.chains: List[SignalChain] = []

    def add(self, chain: SignalChain) -> "SignalManager":
        self.chains.append(chain)
        return self

    def check(self, data_point: DataPoint) -> List[SignalChain]:
        completed: List[SignalChain] = []
        for chain in self.chains:
            if chain.check(data_point):
                completed.append(chain)
                chain.reset()
        return completed

    def reset_all(self) -> None:
        for chain in self.chains:
            chain.reset()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/signals/test_signal_manager.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Run full Phase 3a test suite**

```bash
pytest tests/signals/ -v
```

Expected: `38+ passed, 0 failed`

- [ ] **Step 6: Commit**

```bash
git add src/simple_trader/signals/ tests/signals/
git commit -m "feat: add signals module — BaseSignal, atomic, combinators, SignalChain, SignalManager"
```
