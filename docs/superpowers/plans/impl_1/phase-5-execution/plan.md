# Phase 5: Execution Layer — Robot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Depends on Phase 4.

**Goal:** Implement `Robot` — the live trading loop that polls Binance, evaluates strategies, places orders, and manages position lifecycle.

**Architecture:** `Robot.run_instantly()` is an infinite polling loop. `do()` is a single step: call StrategyManager, route the action to Position, then execute via stock_item. All Binance calls are mocked in tests. Position state persists to JSON after each step for crash recovery.

**Tech Stack:** Depends on all previous phases. No new packages.

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
src/simple_trader/execution/
  __init__.py
  robot.py
tests/execution/
  __init__.py
  test_robot.py
  conftest.py
```

---

## Task 0: Directory Setup

- [ ] **Step 1: Create directories**

```bash
mkdir -p src/simple_trader/execution
mkdir -p tests/execution
touch src/simple_trader/execution/__init__.py
touch tests/execution/__init__.py
```

---

## Task 1: Robot Core

**Files:**
- Create: `src/simple_trader/execution/robot.py`
- Create: `tests/execution/conftest.py`
- Create: `tests/execution/test_robot.py`

- [ ] **Step 1: Write `tests/execution/conftest.py`**

```python
import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from simple_trader.data.data_point import LiveDataPoint
from simple_trader.data.stocks.base_stock import BaseStock
from simple_trader.position.position import Position
from simple_trader.position.long_position import LongPosition
from simple_trader.strategy.strategy_manager import StrategyManager
from simple_trader.infrastructure.constants import StrategyAction
import simple_trader.data.stocks.stock_item as stock_item


def make_fake_stock(fee: float = 0.001) -> BaseStock:
    stock = MagicMock(spec=BaseStock)
    stock.fee = fee
    stock.get_candles_history.return_value = []
    stock.trade.return_value = {"orderId": "TEST-1"}
    stock.get_order_status.return_value = {
        "status": "FILLED",
        "executedQty": "10.0",
        "price": "15.0",
    }
    return stock


def make_data_point() -> LiveDataPoint:
    ohlc = {1: pd.DataFrame({
        "1_close":   [14.0, 15.0],
        "1_rsi_14":  [45.0, 50.0],
        "1_cci_20":  [-50.0, 0.0],
    })}
    return LiveDataPoint(ohlc)


def make_idle_position() -> Position:
    return Position(LongPosition("USDT", "LINK", 1000.0, 0.001))


def make_strategy_manager(action=StrategyAction.NOTHING) -> StrategyManager:
    mgr = MagicMock(spec=StrategyManager)
    mgr.check.return_value = (action, 15.0, 17.0, 14.0, 1)
    return mgr


@pytest.fixture(autouse=True)
def reset_stock_item():
    stock_item.set(None)
    yield
    stock_item.set(None)
```

- [ ] **Step 2: Write failing test**

`tests/execution/test_robot.py`:

```python
import pytest
from unittest.mock import MagicMock, patch, call
from simple_trader.execution.robot import Robot
from simple_trader.infrastructure.constants import StrategyAction, PositionState
import simple_trader.data.stocks.stock_item as stock_item
from tests.execution.conftest import (
    make_fake_stock, make_data_point, make_idle_position, make_strategy_manager
)


def make_robot(action=StrategyAction.NOTHING) -> Robot:
    fake_stock = make_fake_stock()
    stock_item.set(fake_stock)
    strategy_mgr = make_strategy_manager(action)
    position = make_idle_position()
    return Robot(strategy_mgr=strategy_mgr, position=position)


def test_robot_initializes():
    robot = make_robot()
    assert robot is not None


def test_robot_do_does_not_raise_when_action_nothing():
    robot = make_robot(action=StrategyAction.NOTHING)
    point = make_data_point()
    robot.do(point)  # should not raise


def test_robot_do_calls_strategy_manager():
    robot = make_robot(action=StrategyAction.NOTHING)
    point = make_data_point()
    robot.do(point)
    robot.strategy_mgr.check.assert_called_once_with(point, robot.position)


def test_robot_do_open_long_calls_position_open():
    robot = make_robot(action=StrategyAction.OPEN_LONG)
    point = make_data_point()
    robot.do(point)
    assert robot.position.state == PositionState.WAIT_BUY


def test_robot_do_open_long_places_order():
    robot = make_robot(action=StrategyAction.OPEN_LONG)
    point = make_data_point()
    robot.do(point)
    stock = stock_item.get()
    stock.trade.assert_called_once()


def test_robot_do_sets_action_id_after_order():
    robot = make_robot(action=StrategyAction.OPEN_LONG)
    robot.do(make_data_point())
    assert robot.position.is_action_in_progress()


def test_robot_process_fill_records_entry():
    robot = make_robot(action=StrategyAction.OPEN_LONG)
    robot.do(make_data_point())   # places order, sets action_id
    # Now process the fill
    robot.process_fill()
    assert len(robot.position._impl.executed_open) == 1


def test_robot_process_fill_clears_action_id_after_fill():
    robot = make_robot(action=StrategyAction.OPEN_LONG)
    robot.do(make_data_point())
    robot.process_fill()
    # After recording fill, action_id cleared for next order
    # (position transitions to WAIT_SAFETY_BUY, action_id still set until exit)
    # Action ID is cleared only after exit fill
    assert robot.position.state == PositionState.WAIT_SAFETY_BUY
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/execution/test_robot.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.execution.robot'`

- [ ] **Step 4: Write `src/simple_trader/execution/robot.py`**

```python
import time
import json
from pathlib import Path
from typing import Optional
from ..data.data_point import DataPoint
from ..position.position import Position
from ..strategy.strategy_manager import StrategyManager
from ..infrastructure.constants import StrategyAction, PositionState
import simple_trader.data.stocks.stock_item as stock_item


class Robot:
    """
    Live trading robot.

    Polling loop:
    1. Fetch candles + compute indicators (done before do() is called)
    2. do(data_point) — evaluate strategy, route action to position, execute
    3. process_fill() — check Binance order status; record fills; finalize

    Position state is persisted to JSON after each step for crash recovery.
    """

    POLL_INTERVAL_IDLE   = 30   # seconds when no action pending
    POLL_INTERVAL_ACTIVE = 5    # seconds when order in flight
    ERROR_SLEEP          = 120  # seconds after exception

    def __init__(
        self,
        strategy_mgr: StrategyManager,
        position: Position,
        pair: str = "LINKUSDT",
        persist_path: Optional[Path] = None,
    ) -> None:
        self.strategy_mgr = strategy_mgr
        self.position = position
        self.pair = pair
        self.persist_path = persist_path

    # ── Single step ───────────────────────────────────────────────────────

    def do(self, data_point: DataPoint) -> None:
        action, open_p, close_p, stop_p, tf = self.strategy_mgr.check(
            data_point, self.position
        )
        self._route_action(action, open_p, close_p, stop_p, tf)
        if self.persist_path:
            self._save_state()

    def _route_action(
        self,
        action: StrategyAction,
        open_p: float,
        close_p: float,
        stop_p: float,
        tf: int,
    ) -> None:
        if action == StrategyAction.OPEN_LONG:
            if self.position.state == PositionState.WAIT:
                self.position.open(open_p, close_p, stop_p)
                self._place_order("BUY", open_p)

        elif action == StrategyAction.OPEN_SHORT:
            if self.position.state == PositionState.WAIT:
                self.position.open(open_p, close_p, stop_p)
                self._place_order("SELL", open_p)

        elif action == StrategyAction.CLOSE_LONG:
            if self.position.state in (
                PositionState.WAIT_BUY, PositionState.WAIT_SAFETY_BUY
            ):
                self.position.close(close_p, stop_p)
                self._place_order("SELL", close_p)

        elif action == StrategyAction.CLOSE_SHORT:
            if self.position.state in (
                PositionState.WAIT_SELL, PositionState.WAIT_SAFETY_SELL
            ):
                self.position.close(close_p, stop_p)
                self._place_order("BUY", close_p)

        elif action == StrategyAction.MOVE_STOP_LOSS_LONG:
            self.position.set_stop_loss(stop_p)

        elif action == StrategyAction.DO_STOP_LOSS:
            self.position.close(stop_p, stop_p)
            side = "SELL" if self.position._impl.position_type.value == "LONG" else "BUY"
            self._place_order(side, stop_p)

    def _place_order(self, side: str, price: float) -> None:
        qty = self._compute_quantity(price)
        result = stock_item.get().trade(
            symbol=self.pair,
            side=side,
            order_type="LIMIT",
            quantity=qty,
            price=price,
        )
        self.position.set_action_id(str(result["orderId"]))

    def _compute_quantity(self, price: float) -> float:
        full = self.position._impl.full_position
        fee = self.position._impl.fee
        risk = self.position._impl.risk_per_trade if hasattr(
            self.position._impl, "risk_per_trade"
        ) else 0.01
        amount = full * risk
        return round(amount / price, 6)

    # ── Fill processing ───────────────────────────────────────────────────

    def process_fill(self) -> bool:
        """
        Query Binance for current order status.
        If filled, record the fill on position.
        Returns True if fill was processed.
        """
        if not self.position.is_action_in_progress():
            return False

        order_id = self.position.buy_id
        status = stock_item.get().get_order_status(self.pair, order_id)  # type: ignore[arg-type]

        if status["status"] == "FILLED":
            qty   = float(status["executedQty"])
            price = float(status.get("price", 0.0))
            state = self.position.state

            if state == PositionState.WAIT_BUY:
                self.position.record_entry_fill(qty, price)
            elif state == PositionState.WAIT_SELL:
                self.position.record_exit_fill(qty, price)
                self.position.clear_action_id()

            return True
        return False

    # ── Persistence ───────────────────────────────────────────────────────

    def _save_state(self) -> None:
        if self.persist_path is None:
            return
        state = {
            "state":           self.position.state.value,
            "action":          self.position.action.value,
            "price_stop_loss": self.position.price_stop_loss,
            "price_close":     self.position.price_close,
        }
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        self.persist_path.write_text(json.dumps(state, indent=2))

    # ── Main loop (not unit-tested — integration/manual only) ────────────

    def run_instantly(self) -> None:
        """Infinite live trading loop. Not called from tests."""
        while True:
            try:
                # Caller is responsible for providing data_point each iteration
                # In live mode: fetch candles, compute indicators, then call do()
                interval = (
                    self.POLL_INTERVAL_ACTIVE
                    if self.position.is_action_in_progress()
                    else self.POLL_INTERVAL_IDLE
                )
                time.sleep(interval)
                if self.position.is_action_in_progress():
                    self.process_fill()
            except Exception as e:
                print(f"Robot error: {e}")
                time.sleep(self.ERROR_SLEEP)
```

- [ ] **Step 5: Add `risk_per_trade` to `BasePosition`**

Open `src/simple_trader/position/base_position.py` and add `risk_per_trade` to `__init__`:

```python
def __init__(
    self,
    coin_use: str,
    coin_get: str,
    full_position: float,
    fee: float,
    use_safety: bool = True,
    risk_per_trade: float = 0.01,
) -> None:
    self.coin_use = coin_use
    self.coin_get = coin_get
    self.full_position = full_position
    self.fee = fee
    self.use_safety = use_safety
    self.risk_per_trade = risk_per_trade
    self.position_type = PositionType.UNKNOWN
    self._do_init()
```

Also update `LongPosition.__init__` and `ShortPosition.__init__` to pass `risk_per_trade` through to `super().__init__()`.

- [ ] **Step 6: Run test to verify it passes**

```bash
pytest tests/execution/test_robot.py -v
```

Expected: `8 passed`

- [ ] **Step 7: Run full integration smoke test**

```bash
pytest tests/ -v --tb=short
```

Expected: All tests from Phases 1-5 pass.

- [ ] **Step 8: Commit**

```bash
git add src/simple_trader/execution/ tests/execution/ src/simple_trader/position/
git commit -m "feat: add Robot execution layer — live trading loop with order management"
```
