# Phase 3b: Position Module Implementation Plan (PARALLEL — Agent B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Depends on Phase 2b. Runs in parallel with Phase 3a (Signals).

**Goal:** Implement `Coin`, `BasePosition` state machine, `LongPosition`, `ShortPosition`, and `Position` facade.

**Architecture:** `Coin` is a plain dataclass tracking one currency leg. `BasePosition` is an abstract state machine (WAIT → WAIT_BUY/WAIT_SELL → WAIT_SAFETY_* → WAIT). `LongPosition`/`ShortPosition` are concrete subclasses implementing direction-specific logic. `Position` is the public facade — used by `Robot` and `StrategyManager`.

**Tech Stack:** Python standard library only. No external dependencies.

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
src/simple_trader/position/
  __init__.py
  coin.py
  base_position.py
  long_position.py
  short_position.py
  position.py
tests/position/
  __init__.py
  test_coin.py
  test_base_position.py
  test_long_position.py
  test_short_position.py
  test_position.py
```

---

## Task 0: Directory Setup

- [ ] **Step 1: Create directories**

```bash
mkdir -p src/simple_trader/position
mkdir -p tests/position
touch src/simple_trader/position/__init__.py
touch tests/position/__init__.py
```

---

## Task 1: Coin

**Files:**
- Create: `src/simple_trader/position/coin.py`
- Create: `tests/position/test_coin.py`

- [ ] **Step 1: Write failing test**

`tests/position/test_coin.py`:

```python
import pytest
from simple_trader.position.coin import Coin


def test_coin_initial_state():
    coin = Coin("USDT")
    assert coin.name == "USDT"
    assert coin.size == 0.0
    assert coin.used == 0.0
    assert coin.loan == 0.0
    assert coin.returned == 0.0
    assert coin.want_to_use == 0.0
    assert coin.action_amount == 0.0


def test_coin_initializes_with_size():
    coin = Coin("USDT", size=1000.0)
    assert coin.size == 1000.0


def test_coin_use_transfers_from_size_to_used():
    coin = Coin("USDT", size=1000.0)
    coin.use(300.0)
    assert coin.size == 700.0
    assert coin.used == 300.0


def test_coin_use_multiple_times_accumulates():
    coin = Coin("USDT", size=1000.0)
    coin.use(200.0)
    coin.use(300.0)
    assert coin.used == 500.0
    assert coin.size == 500.0


def test_coin_free_transfers_from_used_to_size():
    coin = Coin("USDT", size=1000.0)
    coin.use(400.0)
    coin.free(200.0)
    assert coin.used == 200.0
    assert coin.size == 800.0


def test_coin_total_is_size_plus_used():
    coin = Coin("USDT", size=600.0)
    coin.use(400.0)
    assert coin.total == 1000.0


def test_coin_borrow_adds_to_loan_and_size():
    coin = Coin("USDT", size=100.0)
    coin.borrow(500.0)
    assert coin.loan == 500.0
    assert coin.size == 600.0


def test_coin_repay_reduces_loan_and_size():
    coin = Coin("USDT", size=600.0)
    coin.loan = 500.0
    coin.repay(500.0)
    assert coin.loan == 0.0
    assert coin.size == 100.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/position/test_coin.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.position.coin'`

- [ ] **Step 3: Write `src/simple_trader/position/coin.py`**

```python
class Coin:
    """
    Tracks one currency leg within a position.

    Attributes:
        name:          Currency symbol (e.g. "USDT", "LINK").
        size:          Available balance (not deployed).
        used:          Deployed balance (in an open order or position).
        loan:          Amount borrowed for margin trading.
        returned:      Amount recovered after close.
        want_to_use:   Intended allocation set before placing order.
        action_amount: Amount of the pending order (set by position before trade).
    """

    def __init__(self, name: str, size: float = 0.0) -> None:
        self.name = name
        self.size = size
        self.used = 0.0
        self.loan = 0.0
        self.returned = 0.0
        self.want_to_use = 0.0
        self.action_amount = 0.0

    def use(self, amount: float) -> None:
        self.size -= amount
        self.used += amount

    def free(self, amount: float) -> None:
        self.used -= amount
        self.size += amount

    def borrow(self, amount: float) -> None:
        self.loan += amount
        self.size += amount

    def repay(self, amount: float) -> None:
        self.loan -= amount
        self.size -= amount

    @property
    def total(self) -> float:
        return self.size + self.used
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/position/test_coin.py -v
```

Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/position/coin.py tests/position/test_coin.py
git commit -m "feat: add Coin class for currency leg tracking"
```

---

## Task 2: BasePosition State Machine

**Files:**
- Create: `src/simple_trader/position/base_position.py`
- Create: `tests/position/test_base_position.py`

- [ ] **Step 1: Write failing test**

`tests/position/test_base_position.py`:

```python
import pytest
from simple_trader.position.base_position import BasePosition
from simple_trader.infrastructure.constants import PositionState, StrategyAction


class ConcretePosition(BasePosition):
    """Minimal concrete implementation for testing BasePosition directly."""

    def _wait_buy_state(self):
        return PositionState.WAIT_BUY

    def _wait_sell_state(self):
        return PositionState.WAIT_SELL

    def _wait_safety_buy_state(self):
        return PositionState.WAIT_SAFETY_BUY

    def _open_action(self):
        return StrategyAction.OPEN_LONG

    def _close_action(self):
        return StrategyAction.CLOSE_LONG

    def _is_tighter_stop(self, price: float) -> bool:
        # For long: stop tightens by moving up
        return price > self.price_stop_loss

    def finalize(self, entry_price: float, exit_price: float, fee: float):
        revenue_pct = (exit_price - entry_price) / entry_price - 2 * fee
        return revenue_pct, revenue_pct * entry_price


def test_position_starts_in_wait_state():
    pos = ConcretePosition(coin_use="USDT", coin_get="LINK",
                           full_position=1000.0, fee=0.001)
    assert pos.state == PositionState.WAIT


def test_position_action_starts_as_nothing():
    pos = ConcretePosition("USDT", "LINK", 1000.0, 0.001)
    assert pos.action == StrategyAction.NOTHING


def test_open_transitions_to_wait_buy():
    pos = ConcretePosition("USDT", "LINK", 1000.0, 0.001)
    pos.open(price_open=15.0, price_close=16.5, price_stop=14.5)
    assert pos.state == PositionState.WAIT_BUY


def test_open_sets_action_to_open_long():
    pos = ConcretePosition("USDT", "LINK", 1000.0, 0.001)
    pos.open(15.0, 16.5, 14.5)
    assert pos.action == StrategyAction.OPEN_LONG


def test_open_stores_prices():
    pos = ConcretePosition("USDT", "LINK", 1000.0, 0.001)
    pos.open(15.0, 16.5, 14.5)
    assert pos.price_open == [15.0]
    assert pos.price_close == 16.5
    assert pos.price_stop_loss == 14.5


def test_open_from_non_wait_state_raises():
    pos = ConcretePosition("USDT", "LINK", 1000.0, 0.001)
    pos.open(15.0, 16.5, 14.5)
    with pytest.raises(AssertionError):
        pos.open(15.0, 16.5, 14.5)


def test_set_stop_loss_tighter_updates_price():
    pos = ConcretePosition("USDT", "LINK", 1000.0, 0.001)
    pos.open(15.0, 16.5, 14.5)
    pos.set_stop_loss(15.0)   # tighter for long (higher)
    assert pos.price_stop_loss == 15.0


def test_set_stop_loss_looser_ignored():
    pos = ConcretePosition("USDT", "LINK", 1000.0, 0.001)
    pos.open(15.0, 16.5, 14.5)
    pos.set_stop_loss(13.0)   # looser for long (lower) — should be rejected
    assert pos.price_stop_loss == 14.5


def test_set_stop_loss_force_overrides():
    pos = ConcretePosition("USDT", "LINK", 1000.0, 0.001)
    pos.open(15.0, 16.5, 14.5)
    pos.set_stop_loss(13.0, force=True)
    assert pos.price_stop_loss == 13.0


def test_finalize_returns_pnl():
    pos = ConcretePosition("USDT", "LINK", 1000.0, 0.001)
    pct, abs_rev = pos.finalize(entry_price=15.0, exit_price=16.5, fee=0.001)
    expected_pct = (16.5 - 15.0) / 15.0 - 2 * 0.001
    assert abs(pct - expected_pct) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/position/test_base_position.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.position.base_position'`

- [ ] **Step 3: Write `src/simple_trader/position/base_position.py`**

```python
from abc import ABC, abstractmethod
from typing import List, Tuple
from .coin import Coin
from ..infrastructure.constants import PositionState, StrategyAction, PositionType


class BasePosition(ABC):
    """
    Abstract state machine for a single trade position.

    Enforces the lifecycle: WAIT → WAIT_BUY/WAIT_SELL → (WAIT_SAFETY_*) → WAIT.
    Subclasses implement direction-specific helpers (_wait_buy_state, etc.).

    Execution layer (Robot) reads `action` and `price_open/close` to place
    orders, then calls `record_entry_fill()` / `record_exit_fill()` to
    report fills, and finally `finalize()` to compute P&L.
    """

    def __init__(
        self,
        coin_use: str,
        coin_get: str,
        full_position: float,
        fee: float,
        use_safety: bool = True,
    ) -> None:
        self.coin_use = coin_use
        self.coin_get = coin_get
        self.full_position = full_position
        self.fee = fee
        self.use_safety = use_safety
        self.position_type = PositionType.UNKNOWN
        self._do_init()

    def _do_init(self) -> None:
        self.state = PositionState.WAIT
        self.action = StrategyAction.NOTHING
        self.price_open: List[float] = []
        self.price_close: float = 0.0
        self.price_stop_loss: float = 0.0
        self.executed_open: List[float] = []
        self.executed_open_amount: List[float] = []
        self.executed_close: List[float] = []
        self.executed_close_amount: List[float] = []
        self.coinUse = Coin(coin_use)
        self.coinGet = Coin(coin_get)
        self.open_time: int = 0
        self.safety_close_time: int = 0

    # ── Public interface ──────────────────────────────────────────────────

    def open(
        self,
        price_open: float,
        price_close: float,
        price_stop: float,
    ) -> None:
        assert self.state == PositionState.WAIT, (
            f"open() requires WAIT state, got {self.state}"
        )
        self.price_open = [price_open]
        self.price_close = price_close
        self.price_stop_loss = price_stop
        self.state = self._wait_buy_state()
        self.action = self._open_action()

    def close(self, price_close: float, price_stop: float) -> None:
        allowed = {self._wait_buy_state(), self._wait_safety_buy_state()}
        assert self.state in allowed, (
            f"close() cannot be called from state {self.state}"
        )
        self.price_close = price_close
        self.state = self._wait_sell_state()
        self.action = self._close_action()

    def set_stop_loss(self, price: float, force: bool = False) -> None:
        if force or self._is_tighter_stop(price):
            self.price_stop_loss = price

    def record_entry_fill(self, amount: float, price: float) -> None:
        self.executed_open.append(price)
        self.executed_open_amount.append(amount)
        if self.use_safety:
            self.state = self._wait_safety_buy_state()
        else:
            self.state = self._wait_sell_state()

    def record_exit_fill(self, amount: float, price: float) -> None:
        self.executed_close.append(price)
        self.executed_close_amount.append(amount)
        self.state = PositionState.WAIT
        self.action = StrategyAction.NOTHING

    # ── Abstract helpers (direction-specific) ────────────────────────────

    @abstractmethod
    def _wait_buy_state(self) -> PositionState: ...

    @abstractmethod
    def _wait_sell_state(self) -> PositionState: ...

    @abstractmethod
    def _wait_safety_buy_state(self) -> PositionState: ...

    @abstractmethod
    def _open_action(self) -> StrategyAction: ...

    @abstractmethod
    def _close_action(self) -> StrategyAction: ...

    @abstractmethod
    def _is_tighter_stop(self, price: float) -> bool:
        """Return True if `price` is a stricter stop-loss than the current one."""

    @abstractmethod
    def finalize(
        self, entry_price: float, exit_price: float, fee: float
    ) -> Tuple[float, float]:
        """Compute (revenue_pct, revenue_abs). Called after exit fill confirmed."""
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/position/test_base_position.py -v
```

Expected: `10 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/position/base_position.py tests/position/test_base_position.py
git commit -m "feat: add BasePosition abstract state machine"
```

---

## Task 3: LongPosition + ShortPosition

**Files:**
- Create: `src/simple_trader/position/long_position.py`
- Create: `src/simple_trader/position/short_position.py`
- Create: `tests/position/test_long_position.py`
- Create: `tests/position/test_short_position.py`

- [ ] **Step 1: Write failing tests**

`tests/position/test_long_position.py`:

```python
from simple_trader.position.long_position import LongPosition
from simple_trader.infrastructure.constants import PositionState, StrategyAction, PositionType


def test_long_position_type():
    pos = LongPosition("USDT", "LINK", 1000.0, 0.001)
    assert pos.position_type == PositionType.LONG


def test_long_opens_to_wait_buy():
    pos = LongPosition("USDT", "LINK", 1000.0, 0.001)
    pos.open(15.0, 17.0, 14.0)
    assert pos.state == PositionState.WAIT_BUY


def test_long_close_transitions_to_wait_sell():
    pos = LongPosition("USDT", "LINK", 1000.0, 0.001)
    pos.open(15.0, 17.0, 14.0)
    pos.record_entry_fill(10.0, 15.0)  # fill entry
    pos.close(17.0, 14.5)
    assert pos.state == PositionState.WAIT_SELL
    assert pos.action == StrategyAction.CLOSE_LONG


def test_long_stop_loss_tightens_upward():
    pos = LongPosition("USDT", "LINK", 1000.0, 0.001)
    pos.open(15.0, 17.0, 14.0)
    pos.set_stop_loss(14.5)   # higher than 14.0 → tighter for long
    assert pos.price_stop_loss == 14.5


def test_long_stop_loss_cannot_go_lower():
    pos = LongPosition("USDT", "LINK", 1000.0, 0.001)
    pos.open(15.0, 17.0, 14.0)
    pos.set_stop_loss(13.5)   # lower → not tighter for long
    assert pos.price_stop_loss == 14.0


def test_long_finalize_profitable_trade():
    pos = LongPosition("USDT", "LINK", 1000.0, 0.001)
    pct, _ = pos.finalize(entry_price=15.0, exit_price=16.5, fee=0.001)
    assert pct > 0


def test_long_finalize_losing_trade():
    pos = LongPosition("USDT", "LINK", 1000.0, 0.001)
    pct, _ = pos.finalize(entry_price=15.0, exit_price=14.0, fee=0.001)
    assert pct < 0
```

`tests/position/test_short_position.py`:

```python
from simple_trader.position.short_position import ShortPosition
from simple_trader.infrastructure.constants import PositionState, StrategyAction, PositionType


def test_short_position_type():
    pos = ShortPosition("LINK", "USDT", 1000.0, 0.001)
    assert pos.position_type == PositionType.SHORT


def test_short_opens_to_wait_sell():
    pos = ShortPosition("LINK", "USDT", 1000.0, 0.001)
    pos.open(15.0, 13.0, 16.0)
    assert pos.state == PositionState.WAIT_SELL


def test_short_open_action_is_open_short():
    pos = ShortPosition("LINK", "USDT", 1000.0, 0.001)
    pos.open(15.0, 13.0, 16.0)
    assert pos.action == StrategyAction.OPEN_SHORT


def test_short_stop_loss_tightens_downward():
    pos = ShortPosition("LINK", "USDT", 1000.0, 0.001)
    pos.open(15.0, 13.0, 16.0)
    pos.set_stop_loss(15.5)   # lower than 16 → tighter for short
    assert pos.price_stop_loss == 15.5


def test_short_stop_loss_cannot_go_higher():
    pos = ShortPosition("LINK", "USDT", 1000.0, 0.001)
    pos.open(15.0, 13.0, 16.0)
    pos.set_stop_loss(16.5)   # higher → not tighter for short
    assert pos.price_stop_loss == 16.0


def test_short_finalize_profitable_trade():
    pos = ShortPosition("LINK", "USDT", 1000.0, 0.001)
    pct, _ = pos.finalize(entry_price=15.0, exit_price=13.0, fee=0.001)
    assert pct > 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/position/test_long_position.py tests/position/test_short_position.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.position.long_position'`

- [ ] **Step 3: Write `src/simple_trader/position/long_position.py`**

```python
from typing import Tuple
from .base_position import BasePosition
from ..infrastructure.constants import PositionState, StrategyAction, PositionType


class LongPosition(BasePosition):
    """
    Long trade: buy (entry) then sell (exit).
    coinUse = base currency (USDT), coinGet = asset (LINK).
    Stop-loss tightens by moving UP (protecting profit on the way up).
    """

    def __init__(
        self,
        coin_use: str,
        coin_get: str,
        full_position: float,
        fee: float,
        use_safety: bool = True,
    ) -> None:
        super().__init__(coin_use, coin_get, full_position, fee, use_safety)
        self.position_type = PositionType.LONG

    def _wait_buy_state(self) -> PositionState:
        return PositionState.WAIT_BUY

    def _wait_sell_state(self) -> PositionState:
        return PositionState.WAIT_SELL

    def _wait_safety_buy_state(self) -> PositionState:
        return PositionState.WAIT_SAFETY_BUY

    def _open_action(self) -> StrategyAction:
        return StrategyAction.OPEN_LONG

    def _close_action(self) -> StrategyAction:
        return StrategyAction.CLOSE_LONG

    def _is_tighter_stop(self, price: float) -> bool:
        return price > self.price_stop_loss

    def finalize(
        self, entry_price: float, exit_price: float, fee: float
    ) -> Tuple[float, float]:
        revenue_pct = (exit_price - entry_price) / entry_price - 2 * fee
        return revenue_pct, revenue_pct * entry_price
```

- [ ] **Step 4: Write `src/simple_trader/position/short_position.py`**

```python
from typing import Tuple
from .base_position import BasePosition
from ..infrastructure.constants import PositionState, StrategyAction, PositionType


class ShortPosition(BasePosition):
    """
    Short trade: sell (entry) then buy (exit).
    coinUse = asset (LINK), coinGet = base currency (USDT).
    Stop-loss tightens by moving DOWN (protecting profit on the way down).
    """

    def __init__(
        self,
        coin_use: str,
        coin_get: str,
        full_position: float,
        fee: float,
        use_safety: bool = True,
    ) -> None:
        super().__init__(coin_use, coin_get, full_position, fee, use_safety)
        self.position_type = PositionType.SHORT

    def _wait_buy_state(self) -> PositionState:
        return PositionState.WAIT_SELL

    def _wait_sell_state(self) -> PositionState:
        return PositionState.WAIT_BUY

    def _wait_safety_buy_state(self) -> PositionState:
        return PositionState.WAIT_SAFETY_SELL

    def _open_action(self) -> StrategyAction:
        return StrategyAction.OPEN_SHORT

    def _close_action(self) -> StrategyAction:
        return StrategyAction.CLOSE_SHORT

    def _is_tighter_stop(self, price: float) -> bool:
        return price < self.price_stop_loss

    def finalize(
        self, entry_price: float, exit_price: float, fee: float
    ) -> Tuple[float, float]:
        revenue_pct = (entry_price - exit_price) / entry_price - 2 * fee
        return revenue_pct, revenue_pct * entry_price
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/position/test_long_position.py tests/position/test_short_position.py -v
```

Expected: `13 passed`

- [ ] **Step 6: Commit**

```bash
git add src/simple_trader/position/long_position.py src/simple_trader/position/short_position.py \
        tests/position/test_long_position.py tests/position/test_short_position.py
git commit -m "feat: add LongPosition and ShortPosition with direction-specific state machine"
```

---

## Task 4: Position Facade

**Files:**
- Create: `src/simple_trader/position/position.py`
- Create: `tests/position/test_position.py`

- [ ] **Step 1: Write failing test**

`tests/position/test_position.py`:

```python
import pytest
from simple_trader.position.position import Position
from simple_trader.position.long_position import LongPosition
from simple_trader.position.short_position import ShortPosition
from simple_trader.infrastructure.constants import PositionState, StrategyAction, PositionType


def _long_pos() -> Position:
    impl = LongPosition("USDT", "LINK", 1000.0, 0.001)
    return Position(impl)


def _short_pos() -> Position:
    impl = ShortPosition("LINK", "USDT", 1000.0, 0.001)
    return Position(impl)


def test_position_delegates_state():
    pos = _long_pos()
    assert pos.state == PositionState.WAIT


def test_position_delegates_open():
    pos = _long_pos()
    pos.open(15.0, 17.0, 14.0)
    assert pos.state == PositionState.WAIT_BUY


def test_position_delegates_action():
    pos = _long_pos()
    pos.open(15.0, 17.0, 14.0)
    assert pos.action == StrategyAction.OPEN_LONG


def test_position_get_action_returns_current_action():
    pos = _long_pos()
    pos.open(15.0, 17.0, 14.0)
    assert pos.get_action() == StrategyAction.OPEN_LONG


def test_position_set_action_id_stores_buy_id():
    pos = _long_pos()
    pos.set_action_id("12345")
    assert pos.buy_id == "12345"


def test_position_is_action_in_progress_true_when_id_set():
    pos = _long_pos()
    pos.set_action_id("99")
    assert pos.is_action_in_progress() is True


def test_position_is_action_in_progress_false_initially():
    pos = _long_pos()
    assert pos.is_action_in_progress() is False


def test_position_clear_action_id():
    pos = _long_pos()
    pos.set_action_id("99")
    pos.clear_action_id()
    assert pos.is_action_in_progress() is False


def test_position_short_open_action():
    pos = _short_pos()
    pos.open(15.0, 13.0, 16.0)
    assert pos.action == StrategyAction.OPEN_SHORT


def test_position_delegates_set_stop_loss():
    pos = _long_pos()
    pos.open(15.0, 17.0, 14.0)
    pos.set_stop_loss(14.5)
    assert pos.price_stop_loss == 14.5
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/position/test_position.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.position.position'`

- [ ] **Step 3: Write `src/simple_trader/position/position.py`**

```python
from typing import Optional, Tuple
from .base_position import BasePosition
from ..infrastructure.constants import PositionState, StrategyAction


class Position:
    """
    Public facade over BasePosition.

    All business logic (state machine, P&L, risk) lives in posImpl.
    This class adds execution-bridge attributes used by Robot:
    - buy_id / sell_id: active Binance order IDs
    - set_loan / repay_loan: margin borrow lifecycle
    The facade is passed to both StrategyManager (reads state) and
    Robot (reads action, reports fills, calls finalize).
    """

    def __init__(self, pos_impl: BasePosition) -> None:
        self._impl = pos_impl
        self._action_id: Optional[str] = None
        self._loan_amount: float = 0.0

    # ── Delegation to posImpl ─────────────────────────────────────────────

    @property
    def state(self) -> PositionState:
        return self._impl.state

    @property
    def action(self) -> StrategyAction:
        return self._impl.action

    @property
    def price_stop_loss(self) -> float:
        return self._impl.price_stop_loss

    @property
    def price_open(self) -> list:
        return self._impl.price_open

    @property
    def price_close(self) -> float:
        return self._impl.price_close

    def open(self, price_open: float, price_close: float, price_stop: float) -> None:
        self._impl.open(price_open, price_close, price_stop)

    def close(self, price_close: float, price_stop: float) -> None:
        self._impl.close(price_close, price_stop)

    def set_stop_loss(self, price: float, force: bool = False) -> None:
        self._impl.set_stop_loss(price, force=force)

    def record_entry_fill(self, amount: float, price: float) -> None:
        self._impl.record_entry_fill(amount, price)

    def record_exit_fill(self, amount: float, price: float) -> None:
        self._impl.record_exit_fill(amount, price)

    def finalize(
        self, entry_price: float, exit_price: float
    ) -> Tuple[float, float]:
        return self._impl.finalize(entry_price, exit_price, self._impl.fee)

    def get_action(self) -> StrategyAction:
        return self._impl.action

    # ── Execution-bridge attributes ───────────────────────────────────────

    @property
    def buy_id(self) -> Optional[str]:
        return self._action_id

    @buy_id.setter
    def buy_id(self, value: Optional[str]) -> None:
        self._action_id = value

    def set_action_id(self, order_id: str) -> None:
        self._action_id = order_id

    def clear_action_id(self) -> None:
        self._action_id = None

    def is_action_in_progress(self) -> bool:
        return self._action_id is not None

    def set_loan(self, amount: float) -> None:
        self._loan_amount = amount
        self._impl.coinUse.borrow(amount)

    def repay_loan(self) -> float:
        amount = self._loan_amount
        self._loan_amount = 0.0
        return amount
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/position/test_position.py -v
```

Expected: `10 passed`

- [ ] **Step 5: Run full Phase 3b test suite**

```bash
pytest tests/position/ -v
```

Expected: `41+ passed, 0 failed`

- [ ] **Step 6: Commit**

```bash
git add src/simple_trader/position/ tests/position/
git commit -m "feat: add position module — Coin, BasePosition, LongPosition, ShortPosition, Position facade"
```
