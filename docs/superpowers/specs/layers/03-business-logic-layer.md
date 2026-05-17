# Business Logic Layer Specification

**Layer position:** Third layer — sits between Data and Execution, transforms market data into trading decisions.

**Related specs:**
- [Main Architecture](../2026-05-05-pybtctr2-architecture.md)
- [Data Layer](02-data-layer.md)
- [Execution Layer](04-execution-layer.md)

---

## 1. Overview

**Purpose:** Transform enriched OHLC data into concrete trading decisions (OPEN_LONG, CLOSE_SHORT, MOVE_STOP_LOSS, etc.) by evaluating signal chains and coordinating multiple trading strategies. Apply those decisions to the Position state machine, which enforces trade lifecycle rules and computes P&L.

**Responsibilities:**
- Define and evaluate atomic market signals (comparisons, crossovers, divergences, candle patterns, level proximity)
- Compose signals into sequential chains (all signals must fire in order for a chain to complete)
- Register and execute trading strategies (long, short, NN-based)
- Coordinate multiple strategies, resolve conflicts, and produce a single winning action per tick
- Compute entry price, target price, and stop-loss price for each action
- Pass NN probability context to strategies (live inference or pre-computed simulation)
- Manage trade lifecycle (open, close, finalize) through the Position state machine
- Enforce risk management rules: one-directional stop-loss tightening, position sizing by risk_per_trade, safety timeout close
- Track P&L and execution history across graduated entry/exit fills

**Key modules:** `signals.py`, `signals_lib/` (7 files), `strategies/strategy.py`, `strategies/example_strategy_long.py`, `strategies/example_strategy_short.py`, `strategy_manager.py`, `position/position.py`, `position/base_position.py`, `position/long_position.py`, `position/short_position.py`, `position/coin.py`

---

## 2. Layer Boundaries

**Upstream (feeds into this layer):**
- Data layer: `data_point.get(col, tf, shift)` — the `DataPoint` protocol (see Data Layer spec v2); NN and predictor outputs are pre-computed columns accessible via the same interface
- Levels: accessed via `data.get_levels(tf, level_type, ema_cols)` — `Levels` is a Data module concern; Business Logic layer never imports it directly
- NN layer (optional): pre-computed simulation pkl (`shared/nn_data/nn_simulation_cls_big_tf.pkl`) or live NN inference

**Downstream (layers that consume this layer):**
- Execution layer: receives `(action, open_price, close_price, stop_price, time_frame)` 5-tuple from `strategy_manager.check()`; then reads `position.get_action()` to know what order to place; calls `position.record_entry_fill()` / `position.record_exit_fill()` to record fills; calls `position.finalize()` after close

**Key interfaces this layer exposes:**
- `strategy_manager.check(data, position_state, position_target, action_msg) -> (action, open_price, close_price, stop_price, tf)` — strategy evaluation entry point; called once per tick; `data` is passed in, not stored
- `position.open(strategy_action, price_open, price_close, price_stop_loss, time_period, action_msg) -> bool` — initiates trade; transitions state machine; sets execution intent
- `position.close(strategy_action, price_close, price_stop_loss, time_period, action_msg)` — prepares exit; updates price targets
- `position.set_stop_loss(price, action_msg, force=False) -> bool` — tightens stop toward profit side
- `position.get_action() -> STRATEGY_ACTION_*` — execution layer reads this to know what order to place next
- `position.record_entry_fill(coin_amount, price)` / `position.record_exit_fill(coin_amount, price)` — execution layer reports fills; updates coin balances
- `position.finalize() -> (revenue_pct, revenue_abs)` — computes P&L; resets position to WAIT

---

## 3. Data Flow

```
data.ohlc[tf]  (multi-timeframe enriched OHLC DataFrames)
   ↓ [data.get_cur_price(col, shift, tf)]
Scalar indicator values (rsi, cci, ema_25, close, atr, ...)
   ↓ [BaseSignal.check(data, levels, action)]
bool (signal fired or not)
   ↓ [SignalChain.check() — advances chain if current signal fired]
SignalChain.completed() == True
   ↓ [SignalChain.get_action(price, action_msg)]
[result_action_int, tf_int, price_float, data_dict]
   ↓ [SignalManager.check() — collects all completed chains this tick]
actions_list: list of [action, tf, price, data_dict]
   ↓ [Strategy.select_final_action(actions_list, position_state)]
(final_action, open_tf, close_tf, stop_tf)
   ↓ [Strategy.get_open/close/stop_loss_price()]
(action, open_price, close_price, stop_price, tf)
   ↓ [StrategyManager.check() — resolves across multiple strategies]
Single winning (action, open_price, close_price, stop_price, tf)
   ↓ [Robot.wait() routes to Position]
Position.open() / close() / set_stop_loss()
   → state machine transitions; posImpl = LongPosition / ShortPosition
   → position.action set to OPEN_LONG / CLOSE_LONG / etc.
   ↓ [Execution layer reads position.get_action() and executes]
Robot / TrainRobot → order placement / simulated fill
   ↓ [fill reported back]
position.record_entry_fill() / record_exit_fill() → coin balances updated
position.finalize() → (revenue_pct, revenue_abs)
```

---

## 4. Execution Flow

### Per-tick signal evaluation
1. `strategy_manager.check(data, position_state, position_target, action_msg)` called by Robot/TrainRobot; `data` carries all indicators, predictor outputs, and NN probability columns pre-computed by the Data layer
2. For each registered strategy:
   a. `strategy.check_conditions(data, position_state, action_msg)` — strategy gate (e.g., ExampleStrategyLong skips if `WAIT_SAFETY_BUY` state)
   b. `strategy.check(data, position_state, position_target, action_msg)` — full signal evaluation
3. Strategy.check() flow:
   a. `get_level_values()` — builds dict of price levels by type (EMA_50, EMA_100, BBU, BBM across timeframes)
   b. `signals.check(data, levels, action_msg)` — evaluates all SignalChains
   c. `select_final_action(actions_list, position_state)` — picks single action by priority
   d. `get_open/close/stop_loss_price()` — resolves numeric prices
4. StrategyManager merges results across all strategies (priority order):
   - DO_STOP_LOSS: returned immediately on first match (highest priority)
   - CLOSE_*: returned immediately on first match
   - MOVE_STOP_LOSS_*: accumulated; skipped in safety states
   - OPEN_LONG/SHORT: accumulated; multiple simultaneous OPENs → conflict → returns NOTHING

### Signal chain evaluation (per chain, per tick)
1. `SignalChain.check(data, levels, cur_time, action_msg)`:
   - Evaluates `signals[cur_pos].check(data, levels, action_msg)`
   - If True: increments `cur_pos`
   - If signal returns `reset()=True`: resets `cur_pos` to 0
2. Multiple chains advance independently each tick — chain state persists across ticks
3. When `cur_pos == len(signals)`: chain is complete; `get_action()` packages the result; chain immediately resets
4. Chain result: `[result_action_int, tf_int, price_float, {position_time, ...signal_data_dicts}]`

### Action priority (select_final_action)
- Single action in list: use it directly
- Multiple actions, `position_state == WAIT`: prefer OPEN_LONG or OPEN_SHORT
- Multiple actions, position open: prefer CLOSE_* actions, then MOVE_STOP_LOSS_*

---

## 5. Key Classes

### BaseSignal (signals_lib/base_signal.py)
Abstract base for all signal types. All signals must implement:
- `check(data, levels, action) -> bool` — primary evaluation
- `reset() -> bool` — returns True to cancel the chain
- `get_data() -> dict` — signal-specific payload for action packaging
- `get_marker_pos(data) -> float` — chart marker price
- `set_shift(shift: int)` — shifts historical window; propagated recursively by combinator signals

`self.shift` (default 0): offset passed to `data_point.get(col, tf, shift + self.shift)`.

### SignalChain (signals_lib/signal_manager.py)
Sequential signal sequence — all must fire in order for the chain to complete.

Constructor: `SignalChain(name: str, result_action: int, tf: int, notify: bool=True)`
- `add(signal)` — appends signal to chain
- `check(data, levels, cur_time, action)` — advances cur_pos if current signal fires
- `completed(data, action) -> bool` — True when cur_pos == len(signals)
- `get_action(price, action) -> [result_action, tf, price, data_dict]` — packages completed action
- `reset(action)` — resets cur_pos to 0

### SignalManager (signals_lib/signal_manager.py)
Container for multiple SignalChain objects.

- `add_chain(chain)` — registers a chain
- `check(data, levels, action) -> list` — runs all chains; returns completed action tuples; resets each completed chain

### Atomic Signal types (signals_lib/common.py)
Single-step comparisons. All extend BaseSignal. Examples:
- `Less_Signal(tf, indi1, indi2)` / `Greater_Signal(tf, indi1, indi2)` — compare two indicators
- `Cross_Up_Signal(tf, indi1, indi2)` / `Cross_Down_Signal(tf, indi1, indi2)` — crossovers
- `Rising_Signal(tf, indi1)` / `Falling_Signal(tf, indi1)` — direction of change
- `Near_Level_Signal(tf, indi, level_type, buffer)` — proximity to a price level
- `Over_Level_Signal` / `Under_Level_Signal` — above/below any active level

### Combinator Signals (signals_lib/operations.py)
Logical composition of signals:
- `And_Signal(signals)` / `Or_Signal(signals)` / `Not_Signal(signal)` — boolean logic
- `Continuous_Signal(signal, history, multiply)` — fires if signal true ≥ multiply times in history candles
- `History_Signal(signal, history)` — evaluates signal at shift + history (candles in the past)
- `BoolValue_Signal(value, tf)` — reads a boolean column from data.get_cur_price()

All combinators propagate `set_shift()` recursively to nested signals.

### Complex Signals (signals_lib/complex.py)
Multi-candle pattern detection:
- `Diver_Bull_signal(tf, level, cancel_level, indicator)` — bullish divergence: price higher low, indicator lower low below threshold
- `Diver_Bear_signal(...)` — bearish divergence: price lower high, indicator higher high above threshold
- `Diver_Hidden_Bull/Bear_signal(...)` — hidden divergence variants
- `Bounce_Long/Short_Signal(tf, indi, indi_ma)` — MA bounce detection
Divergence signals scan back `peak_history=7` candles for the prior peak.

### Candle Pattern Signals (signals_lib/candle.py)
- `BigCandle_Signal(tf, coef)` — `natr > coef × natr_ma`
- `LongTale_Signal(tf, type)` / `ShortTale_Signal(tf, type)` — wick proportions
- `CandleUP_Signal(tf)` / `CandleDOWN_Signal(tf)` — bullish/bearish candle

### Strategy (strategies/strategy.py)
Base class for all strategies. Constructor creates `self.signals = SignalManager()`.

Key method: `check(data, position_state, position_target, action_msg) -> (action, open_price, close_price, stop_price, tf)`

Flow: `get_level_values()` → `signals.check()` → `select_final_action()` → `get_open/close/stop_loss_price()`

Price defaults: open = current close; close = +0.8% (long) / -0.8% (short); stop = SAR ± 0.3×ATR.

Abstract interface (must override): `register_signals()`, `check_conditions()`, `process_actions()`

### ExampleStrategyLong / ExampleStrategyShort (strategies/example_strategy_long.py, strategies/example_strategy_short.py)
Minimal reference implementations — not production strategies. Purpose: validate the full strategy execution pipeline end-to-end and serve as the starting template for new strategy development.

Each example strategy implements only what is required by the `Strategy` interface:
- `register_signals()` — one simple signal chain (e.g. CCI crossover) sufficient to fire OPEN and CLOSE actions
- `check_conditions()` — gates on position state (long: skip if already in a sell state; short: skip if already in a buy state)
- `get_open_price()`, `get_close_price()`, `get_stop_loss_price()` — delegate to base class defaults

Signal logic is intentionally trivial; these strategies are not tuned for profitability.

### StrategyManager (strategy_manager.py)
Coordinates multiple strategies and manages NN context.

Constructor: `StrategyManager(fee, robot_actions_test)` — registers strategies; no data stored at construction.

Primary method: `check(data, position_state, position_target, action_msg) -> (action, open_price, close_price, stop_price, tf)`
- `data` passed in each tick; predictor and NN outputs are pre-computed columns on the data object; calls each strategy, merges results

---

### Position (position/position.py)
Facade wrapping `posImpl: BasePosition`. Primary BL interface for trade lifecycle management. Delegates `open()`, `close()`, `finalize()`, `set_stop_loss()` to posImpl (LongPosition or ShortPosition). Also carries execution-bridge attributes used by Robot: `buy_id`/`sell_id` (Binance order IDs), `set_loan()`/`set_repay()` (margin lifecycle), `save_position()`/`load_position()` (crash recovery). These bridge attributes are execution concerns living in the BL-owned facade.

Key BL methods: `open()`, `close()`, `finalize()`, `set_stop_loss()`, `check_stop_open()`, `close_by_time()`, `get_target() -> float`.

### BasePosition (position/base_position.py)
Abstract state machine for a single open trade. Enforces strict WAIT → WAIT_BUY/WAIT_SELL → WAIT_SAFETY_* → WAIT transitions. Manages `price_open[]`, `price_close[]`, `price_stop_loss`, `coinUse`/`coinGet` objects, and execution history arrays.

Key business rules enforced here:
- `set_stop_loss()` only tightens toward profit (unless `force=True`) — prevents accidental stop-widening
- `check_stop_open(cur_price)` — early close if price moved 4×fee against entry (unlikely to fill)
- `close_by_time()` — forces safety close if safety_close_time exceeded
- `finalize()` — computes revenue_pct and revenue_abs from execution history; logs P&L

### LongPosition / ShortPosition (position/long_position.py, short_position.py)
Concrete BasePosition subclasses. LongPosition: buy→sell; `coinUse=USDT`, `coinGet=coin`. ShortPosition: sell→buy; `coinUse=coin`, `coinGet=USDT`. Implement direction-aware helpers: `direction_profit(val)`, `direction_loss(val)`, `first_in_profit(a, b)`. Compute graduated position sizing: `size = min(full_position, full_position × risk_per_trade / (risk / avg_price))`.

### Coin (position/coin.py)
Lightweight data structure tracking one currency leg within a position. Attributes: `name` (e.g., "usdt"), `size` (available), `used` (deployed), `returned` (recovered), `loan` (margin borrow), `want_to_use` (intended allocation), `action_amount` (pending fill quantity). Serialized via `to_dict()` / `from_dict()` as part of full position persistence.

---

## 6. Assumptions & Constraints

- SignalChain state persists across ticks — chains accumulate toward completion over multiple candles; this is intentional (sequential pattern detection)
- All signal classes access data exclusively via `data_point.get(col, tf, shift + self.shift)` — they never access underlying DataFrames directly
- `data` is passed as a parameter to `strategy_manager.check()` each tick — StrategyManager stores no data reference between ticks
- Multiple active strategies can conflict on OPEN signals; StrategyManager returns NOTHING when two strategies both want to open — prevents conflicting entries
- Level values passed into strategies are built fresh each tick in `get_level_values()`; the current implementation only populates SHORT_1_RESISTANCE and SHORT_2_RESISTANCE (long support/resistance are commented out)
- Trend filtering is a Data layer concern — use `BoolValue_Signal("trend_up/down", tf)` in signal chains; no trend detection infrastructure lives in Strategy
- Action resolution priority: DO_STOP_LOSS > CLOSE_* > MOVE_STOP_LOSS_* > OPEN_*
- Position state machine is the source of truth for trade state; Robot/TrainRobot (Execution layer) are consumers — they must never bypass `position.open()`/`close()`/`finalize()` to modify state directly
- Stop-loss movement is one-directional (enforced by BasePosition.set_stop_loss): new stop must be closer to profit than current stop, unless `force=True` — this is a business rule, not an execution constraint
- Position sizing uses `risk_per_trade` (1% of `full_position`) as a BL constraint; the amount returned by `position.get_action_amount()` is authoritative — the Execution layer executes this amount without modification
- **Fee is injected, never hardcoded.** `StrategyManager`, `Strategy`, and `Position` all receive `fee` as a constructor parameter sourced from `stock.item.fee`. No class-level fee default is permitted — a missing fee must fail loudly at construction, not silently fall back. `2×fee` (round-trip cost) is computed inline as `2 * self.fee` wherever needed.
