# Phase 2a: Stock Abstraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Depends on Phase 1 completing first.

**Goal:** Implement `BaseStock` abstract interface, `BinanceStock` concrete implementation, and `StockItem` module-level singleton.

**Architecture:** `BaseStock` is an ABC defining the exchange contract. `BinanceStock` wraps `python-binance`. `stock_item` is a module-level singleton so any module can call `stock_item.get()` without dependency injection. Tests mock Binance client — no live API calls.

**Tech Stack:** python-binance>=1.0.19, pytest-mock

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
  __init__.py
  stocks/
    __init__.py
    base_stock.py
    binance_stock.py
    stock_item.py
tests/data/
  __init__.py
  test_base_stock.py
  test_binance_stock.py
  test_stock_item.py
```

---

## Task 1: Directory Setup

- [ ] **Step 1: Create directories**

```bash
mkdir -p src/simple_trader/data/stocks
mkdir -p tests/data
touch src/simple_trader/data/__init__.py
touch src/simple_trader/data/stocks/__init__.py
touch tests/data/__init__.py
```

- [ ] **Step 2: Verify**

```bash
find src/simple_trader/data -type f | sort
```

Expected:
```
src/simple_trader/data/__init__.py
src/simple_trader/data/stocks/__init__.py
```

---

## Task 2: BaseStock Interface

**Files:**
- Create: `src/simple_trader/data/stocks/base_stock.py`
- Create: `tests/data/test_base_stock.py`

- [ ] **Step 1: Write failing test**

`tests/data/test_base_stock.py`:

```python
import pytest
from simple_trader.data.stocks.base_stock import BaseStock


def test_base_stock_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BaseStock()  # type: ignore[abstract]


def test_subclass_missing_trade_raises_type_error():
    class Partial(BaseStock):
        @property
        def fee(self) -> float:
            return 0.001

        def get_candles_history(self, count, symbol, time_point, tf_minutes=1):
            return []

        def get_order_status(self, symbol, order_id):
            return {}

    with pytest.raises(TypeError):
        Partial()


def test_fully_implemented_subclass_instantiates():
    class FakeStock(BaseStock):
        @property
        def fee(self) -> float:
            return 0.001

        def get_candles_history(self, count, symbol, time_point, tf_minutes=1):
            return []

        def trade(self, symbol, side, order_type, quantity, price=None):
            return {"orderId": "1"}

        def get_order_status(self, symbol, order_id):
            return {"status": "FILLED", "executedQty": "1.0"}

    stock = FakeStock()
    assert stock.fee == 0.001


def test_get_candles_history_returns_list():
    class FakeStock(BaseStock):
        @property
        def fee(self) -> float:
            return 0.001

        def get_candles_history(self, count, symbol, time_point, tf_minutes=1):
            return [["t", "o", "h", "l", "c", "v"]]

        def trade(self, symbol, side, order_type, quantity, price=None):
            return {"orderId": "1"}

        def get_order_status(self, symbol, order_id):
            return {"status": "FILLED", "executedQty": "1.0"}

    stock = FakeStock()
    result = stock.get_candles_history(1, "LINKUSDT", 0)
    assert isinstance(result, list)
    assert len(result) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/data/test_base_stock.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.data.stocks.base_stock'`

- [ ] **Step 3: Write `src/simple_trader/data/stocks/base_stock.py`**

```python
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseStock(ABC):
    """Abstract contract for market data fetching and order execution.

    All exchange adapters must implement this interface so that the rest
    of the system is exchange-agnostic.
    """

    @property
    @abstractmethod
    def fee(self) -> float:
        """Taker fee as a decimal fraction (e.g. 0.001 = 0.1%)."""

    @abstractmethod
    def get_candles_history(
        self,
        count: int,
        symbol: str,
        time_point: int,
        tf_minutes: int = 1,
    ) -> List[Any]:
        """
        Fetch OHLCV candles from the exchange.

        Args:
            count: Number of candles to fetch.
            symbol: Trading pair symbol (e.g. "LINKUSDT").
            time_point: Reference Unix timestamp (seconds).
            tf_minutes: Candle timeframe in minutes (1, 5, 15, 60, 240, 1440).

        Returns:
            Raw candle list; each entry is [open_time, open, high, low, close, volume, ...].
            Conversion to DataFrame happens in the Data layer.
        """

    @abstractmethod
    def trade(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Place an order on the exchange.

        Args:
            symbol: Trading pair (e.g. "LINKUSDT").
            side: "BUY" or "SELL".
            order_type: "LIMIT" or "MARKET".
            quantity: Asset quantity.
            price: Limit price; None for market orders.

        Returns:
            Order dict containing at least "orderId".
        """

    @abstractmethod
    def get_order_status(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """
        Query the fill status of an existing order.

        Returns:
            Dict with at least "status" ("FILLED", "PARTIALLY_FILLED", etc.)
            and "executedQty" (string float).
        """
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/data/test_base_stock.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/data/stocks/base_stock.py tests/data/test_base_stock.py
git commit -m "feat: add BaseStock abstract interface for exchange adapters"
```

---

## Task 3: StockItem Singleton

**Files:**
- Create: `src/simple_trader/data/stocks/stock_item.py`
- Create: `tests/data/test_stock_item.py`

- [ ] **Step 1: Write failing test**

`tests/data/test_stock_item.py`:

```python
import pytest
import simple_trader.data.stocks.stock_item as stock_item
from simple_trader.data.stocks.base_stock import BaseStock


class FakeStock(BaseStock):
    @property
    def fee(self) -> float:
        return 0.002

    def get_candles_history(self, count, symbol, time_point, tf_minutes=1):
        return []

    def trade(self, symbol, side, order_type, quantity, price=None):
        return {"orderId": "99"}

    def get_order_status(self, symbol, order_id):
        return {"status": "FILLED", "executedQty": "1.0"}


@pytest.fixture(autouse=True)
def reset():
    """Ensure singleton is cleared before and after each test."""
    stock_item.set(None)
    yield
    stock_item.set(None)


def test_get_raises_before_set():
    with pytest.raises(RuntimeError, match="not initialized"):
        stock_item.get()


def test_get_returns_instance_after_set():
    fake = FakeStock()
    stock_item.set(fake)
    assert stock_item.get() is fake


def test_set_overwrites_previous():
    fake1 = FakeStock()
    fake2 = FakeStock()
    stock_item.set(fake1)
    stock_item.set(fake2)
    assert stock_item.get() is fake2


def test_set_none_clears_instance():
    stock_item.set(FakeStock())
    stock_item.set(None)
    with pytest.raises(RuntimeError):
        stock_item.get()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/data/test_stock_item.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.data.stocks.stock_item'`

- [ ] **Step 3: Write `src/simple_trader/data/stocks/stock_item.py`**

```python
from typing import Optional
from .base_stock import BaseStock

_instance: Optional[BaseStock] = None


def set(stock: Optional[BaseStock]) -> None:
    global _instance
    _instance = stock


def get() -> BaseStock:
    if _instance is None:
        raise RuntimeError(
            "StockItem not initialized. Call stock_item.set(instance) before use."
        )
    return _instance
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/data/test_stock_item.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/data/stocks/stock_item.py tests/data/test_stock_item.py
git commit -m "feat: add StockItem module-level singleton"
```

---

## Task 4: BinanceStock Implementation

**Files:**
- Create: `src/simple_trader/data/stocks/binance_stock.py`
- Create: `tests/data/test_binance_stock.py`

- [ ] **Step 1: Write failing test**

`tests/data/test_binance_stock.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from simple_trader.data.stocks.binance_stock import BinanceStock


@pytest.fixture
def mock_client():
    with patch("simple_trader.data.stocks.binance_stock.Client") as MockClient:
        client = MagicMock()
        MockClient.return_value = client
        yield client


def test_fee_returns_constructor_value(mock_client):
    stock = BinanceStock("key", "secret", taker_fee=0.001)
    assert stock.fee == 0.001


def test_get_candles_history_calls_get_klines(mock_client):
    mock_client.get_klines.return_value = [["ts", "o", "h", "l", "c", "v"]]
    stock = BinanceStock("key", "secret")
    result = stock.get_candles_history(count=100, symbol="LINKUSDT", time_point=0)
    mock_client.get_klines.assert_called_once()
    assert result == [["ts", "o", "h", "l", "c", "v"]]


def test_get_candles_history_uses_tf_minutes_map(mock_client):
    mock_client.get_klines.return_value = []
    stock = BinanceStock("key", "secret")
    stock.get_candles_history(count=10, symbol="LINKUSDT", time_point=0, tf_minutes=60)
    call_kwargs = mock_client.get_klines.call_args[1]
    assert "1h" in call_kwargs["interval"] or call_kwargs["interval"].endswith("h")


def test_trade_calls_create_order(mock_client):
    mock_client.create_order.return_value = {"orderId": "42"}
    stock = BinanceStock("key", "secret")
    result = stock.trade("LINKUSDT", "BUY", "LIMIT", 10.0, price=15.5)
    assert result["orderId"] == "42"
    mock_client.create_order.assert_called_once()


def test_get_order_status_calls_get_order(mock_client):
    mock_client.get_order.return_value = {"status": "FILLED", "executedQty": "10.0"}
    stock = BinanceStock("key", "secret")
    result = stock.get_order_status("LINKUSDT", "42")
    assert result["status"] == "FILLED"
    mock_client.get_order.assert_called_once_with(symbol="LINKUSDT", orderId="42")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/data/test_binance_stock.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.data.stocks.binance_stock'`

- [ ] **Step 3: Write `src/simple_trader/data/stocks/binance_stock.py`**

```python
from typing import Any, Dict, List, Optional
from binance.client import Client
from .base_stock import BaseStock

_INTERVAL_MAP = {
    1: Client.KLINE_INTERVAL_1MINUTE,
    3: Client.KLINE_INTERVAL_3MINUTE,
    5: Client.KLINE_INTERVAL_5MINUTE,
    15: Client.KLINE_INTERVAL_15MINUTE,
    60: Client.KLINE_INTERVAL_1HOUR,
    240: Client.KLINE_INTERVAL_4HOUR,
    1440: Client.KLINE_INTERVAL_1DAY,
}


class BinanceStock(BaseStock):
    def __init__(
        self, api_key: str, api_secret: str, taker_fee: float = 0.001
    ) -> None:
        self._client = Client(api_key, api_secret)
        self._fee = taker_fee

    @property
    def fee(self) -> float:
        return self._fee

    def get_candles_history(
        self,
        count: int,
        symbol: str,
        time_point: int,
        tf_minutes: int = 1,
    ) -> List[Any]:
        interval = _INTERVAL_MAP.get(tf_minutes, Client.KLINE_INTERVAL_1MINUTE)
        return self._client.get_klines(
            symbol=symbol.upper(),
            interval=interval,
            limit=count,
        )

    def trade(
        self,
        symbol: str,
        side: str,
        order_type: str = "LIMIT",
        quantity: float = 0.0,
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": order_type,
            "quantity": quantity,
        }
        if price is not None:
            kwargs["price"] = str(price)
            kwargs["timeInForce"] = "GTC"
        return self._client.create_order(**kwargs)

    def get_order_status(self, symbol: str, order_id: str) -> Dict[str, Any]:
        return self._client.get_order(symbol=symbol.upper(), orderId=order_id)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/data/test_binance_stock.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Run full Phase 2a suite**

```bash
pytest tests/data/ -v
```

Expected: `13 passed, 0 failed`

- [ ] **Step 6: Commit**

```bash
git add src/simple_trader/data/stocks/binance_stock.py tests/data/test_binance_stock.py
git commit -m "feat: add BinanceStock exchange adapter wrapping python-binance"
```
