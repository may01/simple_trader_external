# Task 01: BaseStock Interface

**Phase:** 01 — Stock Abstraction  
**Depends on:** Phase 00 (constants)  
**Produces:** `stocks/base_stock.py` — abstract contract all exchange implementations must satisfy

---

## Goal

Define the abstract `StockInterface` base class with all method signatures, default attributes, and rate-limit tracking infrastructure. Concrete implementations (`Stock_Binance`) will override all abstract methods.

---

## Context

`StockInterface` is the exchange-neutral contract. Robot, LiveData, and TrainRobot call `stock.item.method()` — they never know if they're talking to Binance, a mock, or any other exchange. The base class provides default no-op implementations that print "INIT STOCK" so uninitialized access fails loudly rather than silently.

---

## Files

- Create: `stocks/base_stock.py`
- Create: `stocks/__init__.py` (empty)

---

## Interface

**Constructor:**
- `__init__(key: str = "", secret: str = "", coin: str = "", coin_base: str = "")` — stores all four as instance attributes; sets `was_init = False`, `weight = 0`, `weight_set_time = 0.0`, `overflow_weight = 5000`, `overflow_weight_time = 60`; does NOT set `fee` — accessing `fee` before `do_stock_init()` raises `AttributeError` (intentional); concrete `__init__` calls `super().__init__()` then overrides with env-sourced values

**Class attributes:**
- `stock_name: str` — exchange identifier; defined as a class-level constant on each concrete class (e.g., `Stock_Binance.stock_name = "binance"`, `Stock_Mock.stock_name = "mock"`); not set in `StockInterface.__init__`
- `key: str`, `secret: str` — API credentials (empty in base)
- `coin: str`, `coin_base: str` — current pair parts (e.g., `"link"`, `"usdt"`)
- `fee: float` — trading fee (must be set by concrete `__init__`, never has a default value)
- `weight: int`, `weight_set_time: float` — API rate-limit tracking
- `overflow_weight: int`, `overflow_weight_time: int` — rate-limit thresholds
- `was_init: bool` — initialization guard flag

**Abstract methods (all print "INIT STOCK" and return empty/default):**
- `get_candles_history(time_list: list[int], coin: str, time_point: int = 0) -> dict[int, pd.DataFrame]`
- `trade(trade_type: str, price: float, amount: float, force: bool = False) -> tuple[str, dict]`
- `order_info(order_id: str) -> tuple[str, dict]`
- `cancel_order(order_id: str) -> tuple[str, dict]`
- `depth(quantity: int) -> tuple[pd.DataFrame, pd.DataFrame]`
- `info() -> dict` — exchange metadata for current pair (symbol filters, precision, min/max order sizes); `Stock_Binance` calls `get_symbol_info(get_pair_name())`; base returns `{}`
- `is_invalid_amount(amount: float, price: float) -> bool`
- `funds(coin: str, asset_type: str = "free") -> tuple[str, float]`
- `get_aviable_loan(coin: str) -> tuple[str, float]`
- `borrow(coin: str, amount: float) -> tuple[str, float]`
- `repay(coin: str, amount: float) -> tuple[str, float]`
- `get_pair_name() -> str`
- `set_operation_sleep() -> None` — rate-limit backoff

**Protected helpers (implemented in base, not overridden by concrete classes):**
- `_resample_to_tf(base_df: pd.DataFrame, source_interval_min: int, target_interval_min: int) -> pd.DataFrame` — OHLCV resampling using `{'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}`; shared by all exchange implementations

---

## Key Constraints

- `fee` has NO default value in the base class — concrete `__init__` must set it from env; missing fee must fail loudly
- `was_init = False` in base constructor; set to `True` only by concrete `__init__` after successful setup
- All abstract methods must return typed defaults matching the concrete return signature (empty DataFrames, empty dicts, STATUS_FAIL, etc.) — not None
- `set_operation_sleep()` in base is a no-op; `Stock_Binance` overrides with actual weight check + sleep

---

## Verification

```bash
docker compose run --rm simulate python3 -c "
from stocks.base_stock import StockInterface
s = StockInterface('', '', '', '')
result = s.get_candles_history([1, 5], 'link')
assert isinstance(result, dict)
assert s.was_init == False
print('base stock ok')
"
```

---

## Commit

`feat: add StockInterface abstract base class`
