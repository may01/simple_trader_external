# Position Module — Cross-Layer Alignment Design

**Date:** 2026-05-10
**Status:** Approved
**Scope:** Align Position module with v2.0 Data layer, Execution layer separation, and Business Logic contracts. No feature additions — consistency and isolation only.

**Related specs:**
- [Data Layer](/layers/02-data-layer.md)
- [Business Logic Layer](/layers/03-business-logic-layer.md)
- [Execution Layer](/layers/04-execution-layer.md)
- [Position Module Overview](/critical-path/position-module/position-module.md)
- [BasePosition](/critical-path/position-module/base-position-class.md)
- [LongPosition](/critical-path/position-module/long-position-class.md)
- [ShortPosition](/critical-path/position-module/short-position-class.md)
- [Position Facade](/critical-path/position-module/position-class.md)

---

## Inconsistencies Addressed

| ID | Description | Section |
|---|---|---|
| IC-1 | Position holds `self.data` (raw Data object) — stale after tick boundary | §1 |
| IC-2 | Live-only order tracking attributes mixed into Position BL facade | §2 |
| IC-3 | `get_close_price()` / `get_stop_loss_price()` ignore data-layer-computed targets | §3 |
| IC-4 | `data.get_cur_price()` old API used in Strategy; `cur_time` sourced from `data.cur_point` | §1 |
| IC-5 | Invalid timeframe constants in StrategyManager (`trend_tf`, `price_check_tf`) | §3 |
| IC-6 | `add_buy()` / `add_sell()` semantics reversed between Long and Short; amounts in mixed units | §4 |

---

## Section 1 — Data Interface Decoupling (IC-1, IC-4)

### Problem

`BasePosition` holds a reference to the raw `Data` object (`self.data`). This reference goes stale after each tick because the Data layer updates in-place. Any method that reads `self.data` between ticks sees inconsistent state. Additionally, `data.get_cur_price()` is the old pre-v2.0 API; v2.0 exposes `DataPoint.get(col, tf, shift)` instead. The current timestamp is sourced from `data.cur_point`, which is also an internal Data-layer artifact.

### Fix

**Remove `self.data` from `BasePosition` entirely.** All methods that previously read from `self.data` now accept a `DataPoint` parameter per-call. Coin names (previously derived from pair string on Data) become constructor parameters.

```
BasePosition.__init__(coin_use: str, coin_get: str, fee: float):
    self.coin_use = coin_use    # e.g. "USDT" for Long, "BTC" for Short
    self.coin_get = coin_get    # e.g. "BTC" for Long, "USDT" for Short
    # no self.data

safety_update(cur_data: DataPoint, cur_time: int) -> None
set_stop_loss(cur_data: DataPoint) -> None
is_stop_loss_triggered(cur_data: DataPoint, cur_time: int) -> bool
```

`cur_time` is passed explicitly by the caller (Robot or TrainRobot) — both already have it from the tick clock. This eliminates the `data.cur_point` dependency and makes each method call self-contained.

**Strategy layer:** `get_open_price()`, `get_close_price()`, `get_stop_loss_price()` on `Strategy` already receive `cur_data: DataPoint` from `StrategyManager.check()`. No change needed at the call site — the fix is removing the `self.data` read inside BasePosition methods and relying on the passed-in `cur_data`.

### Invariant

After this change: no `BasePosition` method reads from a stored data reference. Every data access goes through the `DataPoint` argument. Staleness is impossible by construction.

---

## Section 2 — Execution Bridge Extraction (IC-2)

### Problem

The Position facade (`position.py`) carries live-only attributes that have no meaning in backtesting:

- `buy_id`, `sell_id` — Binance order IDs
- `set_action_id()`, `is_action_in_progress()` — order tracking state
- `set_loan()`, `set_repay()`, `get_loan()` — margin loan lifecycle
- `save_position()`, `load_position()`, `restore_position()` — crash-recovery persistence
- `is_real_stock` flag — controls whether orders actually reach Binance

These force TrainRobot to instantiate a Position object with live-only infrastructure it never uses. They also make the symmetry contract fragile — any bug in this mixed interface can silently affect simulation paths.

### Fix — Extract `LiveOrderTracker`

New class in the execution layer (not BL):

```
LiveOrderTracker:
    buy_id: str | None
    sell_id: str | None
    loan_amount: float
    repay_amount: float

    set_order_id(side: str, order_id: str) -> None  # side = "buy" | "sell"
    reset() -> None                                  # clear IDs before each new operation
    is_action_in_progress() -> bool
    set_loan(amount: float) -> None
    set_repay(amount: float) -> None
    get_loan() -> float
```

Crash-recovery persistence (`save_position()`, `load_position()`, `restore_position()`) moves to Robot itself — it already owns the file paths and recovery flow.

**Robot owns both:**
```
Robot:
    position: Position          # BL state machine only
    order_tracker: LiveOrderTracker
```

**TrainRobot owns only:**
```
TrainRobot:
    position: Position          # same class, no live scaffolding
```

**Remove `is_real_stock`** from Position entirely. Paper-trade mode is controlled in Robot: if `IS_TRADER_TEST=1`, Robot skips the Binance API call but still calls `order_tracker.set_order_id()` with a synthetic ID, maintaining the same code path.

### Symmetry invariant

After this change: `Position` class contains zero live-only state. Robot and TrainRobot both instantiate the same `Position` class with the same interface. Structural enforcement replaces convention.

---

## Section 3 — Target and Stop-Loss Wiring (IC-3, IC-5)

### Problem

**IC-3:** `get_close_price()` in Strategy computes exit target as a fixed percentage above/below entry (`+0.8%`). `get_stop_loss_price()` uses SAR ± 0.3×ATR. The v2.0 data layer computes `tgt_long`, `sl_long`, `tgt_short`, `sl_short` from `diff_stats.pkl` — statistically calibrated per-timeframe targets. These are available via `DataPoint.get("tgt_long", tf)` for tf ∈ {15, 60, 240, 1440}. They are currently unused.

**IC-5:** `StrategyManager.trend_tf` and `price_check_tf` contain invalid timeframes (3, 30, 45, 120) not present in `CANDLES = [1, 5, 15, 60, 240, 1440]`. Any signal evaluation against these timeframes silently returns no data or stale data.

### Fix — IC-3: Data-layer targets as primary source

```
Strategy.get_close_price(cur_data: DataPoint, tf: int) -> float:
    # primary: use data-layer computed target
    tgt = cur_data.get("tgt_long" if is_long else "tgt_short", tf)
    if tgt is not None:
        return tgt
    # fallback: fixed % from entry (existing behavior)
    return entry_price * (1 + target_pct if is_long else 1 - target_pct)

Strategy.get_stop_loss_price(cur_data: DataPoint, tf: int) -> float:
    # primary: use data-layer computed stop
    sl = cur_data.get("sl_long" if is_long else "sl_short", tf)
    if sl is not None:
        return sl
    # fallback: SAR ± 0.3*ATR + level search (existing behavior)
    ...
```

Data-layer targets are available for tf ∈ {15, 60, 240, 1440}. For tf=1 or tf=5, fallback is used automatically. No special casing needed — `cur_data.get()` returns `None` for unavailable fields.

### Fix — IC-5: Scrub invalid timeframes

`StrategyManager.trend_tf` and `price_check_tf` are loaded from `candles_config.yaml` (same source as `CANDLES`). Any timeframe not in `CANDLES` is rejected at startup with a clear error. Hardcoded lists removed from `StrategyManager`.

```
candles_config.yaml:
  candles: [1, 5, 15, 60, 240, 1440]
  trend_tf: [5, 15, 60, 240, 1440]
  price_check_tf: [5, 15, 60, 240, 1440]

StrategyManager.__init__:
    config = load candles_config.yaml
    self.candles = config.candles
    self.trend_tf = config.trend_tf
    self.price_check_tf = config.price_check_tf
    assert all(tf in self.candles for tf in self.trend_tf + self.price_check_tf)
```

---

## Section 4 — Symmetric Fill Interface (IC-6)

### Problem

`add_buy()` and `add_sell()` mean opposite things depending on position direction:

| Method | LongPosition | ShortPosition |
|---|---|---|
| `add_buy(usd, price)` | Entry — spend USD, receive coins | Exit — buy-to-cover |
| `add_sell(coins, price)` | Exit — sell coins, receive USD | Entry — short sale |

Robot must know position direction to pass the right amount in the right units. There is no direction-agnostic fill interface. TrainRobot's `process_action()` re-implements the same routing logic, duplicating a potential source of drift.

### Fix — Phase-semantic rename

Replace direction-named methods with phase-named methods. Both always take `coin_amount` (coins that changed hands) and `price` (USD per coin):

```
BasePosition:
  record_entry_fill(coin_amount: float, price: float) -> None  # abstract
  record_exit_fill(coin_amount: float, price: float) -> None   # abstract
  get_action_amount_in_coins(price: float) -> float            # direction-aware size helper
  get_trade_type() -> str                                      # TRADE_BUY | TRADE_SELL — unchanged
```

**LongPosition:**
```
record_entry_fill(coin_amount, price):
    coinGet.size += coin_amount * (1 - fee)
    coinUse.size -= coin_amount * price
    executed_open.append(price)

record_exit_fill(coin_amount, price):
    coinGet.size -= coin_amount
    coinUse.size += coin_amount * price * (1 - fee)
    executed_close.append(price)

get_action_amount_in_coins(price) -> float:
    if is_wait_open_state(): return coinUse.action_amount / price  # USD → coins
    else: return coinGet.action_amount                             # already coins
```

**ShortPosition:**
```
record_entry_fill(coin_amount, price):
    coinUse.size -= coin_amount                       # coins borrowed and sold
    coinGet.size += coin_amount * price * (1 - fee)  # USD received
    executed_open.append(price)

record_exit_fill(coin_amount, price):
    coinUse.size += coin_amount                       # coins returned
    coinGet.size -= coin_amount * price               # USD spent to repurchase
    executed_close.append(price)

get_action_amount_in_coins(price) -> float:
    if is_wait_open_state(): return coinUse.action_amount          # already coins (borrow amount)
    else: return coinGet.action_amount / price                     # USD → coins
```

**Position facade — `process_action()` simplified:**
```
Position.process_action(coin_amount: float, price: float):
    if posImpl.is_wait_open_state():
        posImpl.record_entry_fill(coin_amount, price)
    else:
        posImpl.record_exit_fill(coin_amount, price)
```

**Robot and TrainRobot — identical call sequence:**
```
# Before placing order:
coin_amount = position.get_action_amount_in_coins(current_price)

# On fill confirmation:
position.process_action(filled_coin_amount, fill_price)
```

Neither caller needs to know if the position is Long or Short. `get_trade_type()` remains — it tells the exchange BUY or SELL and is direction-dependent by design.

### Loan sizing (applies to both Long and Short)

Margin leverage is available for both directions. Long borrows USD to buy more coins; Short borrows coins to sell. The loan amount is determined by Position before the order is placed:

```
BasePosition.compute_loan(want_to_use: float, available_funds: float, available_borrow: float) -> float:
    expected_loan = max(0.0, want_to_use - available_funds)
    return min(expected_loan, available_borrow)
```

`want_to_use` comes from the risk model (e.g., `risk_per_trade × portfolio_value`). `available_funds` and `available_borrow` come from exchange balance queries (live only — in simulation, available_borrow is treated as unlimited). The computed loan is passed to `LiveOrderTracker.set_loan()` before order submission; it is never stored on Position itself.

---

## Position Config Contract

Position timing and risk constants (`BUY_START_TIME_LIMIT`, `SELL_START_TIME_LIMIT`, `STOP_LOSS_PERCENT`, `stop_loss_safety_interval`) are loaded from `configs/position_config.yaml` — never hardcoded as class-level constants. Robot and TrainRobot pass the loaded config into Position at instantiation.

```yaml
# configs/position_config.yaml
buy_start_time_limit_sec: 60
sell_start_time_limit_sec: 180
stop_loss_percent: 0.006
stop_loss_safety_interval_min: 1
```

---

## Fee Injection Contract

`fee` is never hardcoded or defaulted anywhere in the position or strategy stack. The single authoritative source is `stock.item.fee` (live) or its equivalent config value (simulation). It flows:

```
stock.item.fee → Robot/TrainRobot → StrategyManager(fee) → Strategy(fee) → Position(fee) → BasePosition(fee)
```

Any module that needs `fee` receives it as a constructor parameter. No module reads a fallback constant.

---

## Constraints & Non-Goals

- **No feature additions.** This design does not add new strategy logic, new signal types, or new position states.
- **No new file structure.** `LiveOrderTracker` is a new class but lives within the existing execution layer.
- **Backward-compatible simulation output.** Action snapshots, revenue accumulation, and DataIterator interfaces are unchanged.
- **`best_executed_close()` bug** (returns `max(executed_open)` instead of `max(executed_close)`) is a separate defect — tracked in `base-position-class.md` and not in scope here.
