# Strategy Module Specification

**Module:** `strategies/` and `strategy_manager.py`  
**Purpose:** Coordinate multiple trading strategies, evaluate signals, and produce a single trading action per data point  
**Scope:** Central decision-making layer translating signal interpretation into executable actions  

---

## 1. Overview

The Strategy Module is the trading decision engine. It:
- Registers and evaluates multiple concrete strategies (ExampleStrategyLong, ExampleStrategyShort as reference implementations; production strategies in `strategies/new_simulation/`)
- Evaluates signal chains via a centralized SignalManager
- Resolves conflicts when multiple strategies propose actions
- Produces a single, deterministic action (ENTRY, EXIT, MOVE_STOP_LOSS, NOTHING) per tick
- Manages position-aware behavior (different signal paths when waiting vs. holding)
- Integrates with NN predictor for confidence weighting (optional)

**Core Principle:** Each strategy independently evaluates the current market snapshot (data point, levels, position state). The StrategyManager then applies priority-based resolution to output a single action, ensuring consistency and avoiding order conflicts.

---

## 2. Boundaries

### Upstream Dependencies
- **Data Module** (`data.py`): Provides OHLC candles, calculated indicators (RSI, CCI, ATR, EMAs, Bollinger Bands, SAR), and metadata per timeframe
- **Signals Module** (`signals_lib/`): Delivers signal chains, evaluation results, and combined signal logic (AND, OR, NOT)
- **Levels Module** (`levels.py`): Support/resistance level detection for price proximity checks

### Downstream Consumers
- **Robot/TrainRobot**: Execute action via Binance API or simulator
- **Position Manager**: Uses action type to determine open/close/stop-loss behavior
- **Predictor**: Historical context for pattern matching (loaded per-action cycle)

### Data Flow
```
data_point: DataPoint (passed in per-tick — not stored)
    ↓
StrategyManager.check(data_point, position_state, ...) [orchestration]
    ↓
Strategy.check(data_point, ...) [per strategy, per tick]
    ├─ get_level_values(data_point)
    ├─ signals.check(data_point, ...) → SignalManager.check()
    ├─ select_final_action()
    ├─ get_open_price(), get_close_price(), get_stop_loss_price()
    └─ return (action, open_price, close_price, stop_price, timeframe)
    ↓
StrategyManager: Apply priority-based conflict resolution
    └─ Return single action tuple
    ↓
Robot.execute() [action execution]
```

---

## 3. Key Components

### 3.1 Strategy (Base Class)
**File:** `strategies/strategy.py`

Abstract base class defining the template for all strategy implementations.

**Responsibilities:**
- Register signal chains specific to strategy logic
- Evaluate conditions (position state, time, market regime) to gate strategy execution
- Process and prioritize actions when multiple signals fire
- Compute price levels (open, close, stop-loss) for orders

**Key Attributes:**
- `signals` (SignalManager): Holds all signal chains for this strategy
- `fee` (float): Trading fee — injected at construction, sourced from `stock.item.fee`
- `state` (int): Internal state machine (STRATEGY_STATE_WAIT)

**Lifecycle:**
1. `__init__()`: Initialize SignalManager
2. `check()`: Main entry point; evaluates all signal chains and returns action + prices
3. Abstract methods (override in subclasses):
   - `register_signals()`: Build signal chains specific to strategy
   - `check_conditions()`: Gate execution based on position state or market conditions
   - `process_actions()`: Select from candidate actions (reserved for future enhancement)

**Notable Behaviors:**
- Trend filtering: use `BoolValue_Signal("trend_up", tf)` or `BoolValue_Signal("trend_down", tf)` as a gate inside signal chains — trend columns are pre-computed in the Data layer
- Price levels built from dynamic EMAs/Bollinger Bands per timeframe
- Stop-loss computed as SAR ± 0.3×ATR, with level proximity checks

### 3.2 ExampleStrategyLong (Reference Implementation)
**File:** `strategies/example_strategy_long.py`

Minimal long strategy — exists to validate the full strategy execution pipeline and serve as the starting template for new strategies. Not intended for production use.

**Purpose:**
- Exercise every method in the `Strategy` interface with the simplest possible logic
- Confirm that OPEN_LONG → position open → CLOSE_LONG → finalize flows correctly end-to-end
- Provide a copy-and-modify starting point when building a new long strategy

**Implementation:**
- `register_signals()`: One single-step signal chain — fires OPEN_LONG on a simple CCI crossover; fires CLOSE_LONG on the reverse crossover
- `check_conditions()`: Returns False when position state is WAIT_SAFETY_BUY or WAIT_BUY (already entering); True otherwise
- `get_open_price()`, `get_close_price()`, `get_stop_loss_price()`: All delegate to base class defaults (current close, +0.8% target, SAR-based stop)

### 3.3 ExampleStrategyShort (Reference Implementation)
**File:** `strategies/example_strategy_short.py`

Mirror of ExampleStrategyLong for short positions. Same purpose and structure; all signal directions inverted.

**Implementation:**
- `register_signals()`: One single-step signal chain — fires OPEN_SHORT on a simple CCI crossover in the opposite direction; fires CLOSE_SHORT on the reverse
- `check_conditions()`: Returns False when position state is WAIT_SAFETY_SELL or WAIT_SELL; True otherwise
- Price methods: delegate to base class defaults

### 3.4 StrategyManager (Orchestrator)
**File:** `strategy_manager.py`

Singleton-like manager that coordinates multiple strategies and produces final action.

**Key Responsibilities:**
- Register all active strategies
- Evaluate each strategy's `check_conditions()` before execution
- Execute matching strategies and collect proposed actions
- Apply priority-based conflict resolution
- Load and cache NN models (optional, feature flag controlled)

**Key Attributes:**
- `strategies` (dict): Registered strategy instances mapped to state keys
- `predictor` (Predictor): Optional NN-based prediction module
- `nn_classes_*` (dict): Cache for loaded NN models per classification (BIG, SMALL, etc.)

**Constructor Behavior:**
```python
def __init__(self, fee, robot_actions_test):
    # Initialize predictor
    # Load NN models if USE_NN_SIMULATION is False
    # Call register_strategies() or register_test_strategies()
    # No data stored at construction — data_point passed per-tick to check()
```

**Main Entry Point:**
```python
def check(self, data_point: DataPoint, position_state, position_target, action_msg):
    # data_point passed in each tick — not stored between ticks
    # Load NN predictions
    # Evaluate each registered strategy
    # Apply priority-based conflict resolution
    # Return (action, open_price, close_price, stop_price, timeframe)
```

**Action Resolution Logic:**
1. **CLOSE signals** (CLOSE_LONG, CLOSE_SHORT, CLOSE_LONG_PART, CLOSE_SHORT_PART) take absolute priority (break loop)
2. **MOVE_STOP_LOSS signals** (MOVE_STOP_LOSS_LONG, MOVE_STOP_LOSS_SHORT) next priority (unless in safety state)
3. **OPEN signals** (OPEN_LONG, OPEN_SHORT) evaluated for position state mismatch:
   - In POSITION_STATE_WAIT: accept first OPEN signal
   - In holding position: skip OPEN signals
4. **NOTHING signals**: Preserve current resolution, continue evaluating

**Conflict Detection:**
- If multiple OPEN signals trigger simultaneously: Return NOTHING (skip trade, log error)
- If more than one active strategy produces OPEN: Revert to NOTHING with default close price

**NN Integration (Optional):**
- Loads pre-computed NN predictions per class (classification by MACD 60/240)
- Supports three NN types: ALL, SMALL, BIG for risk stratification
- Features feature flag `USE_NN_SIMULATION` (env var) to use precomputed vs. online inference
- Caches NN models by class to avoid reload overhead

---

## 4. Existing Approach

### Signal Chain Architecture
- **SignalChain**: Container with name, expected action, timeframe, and composite signal (AND, OR, NOT)
- **SignalManager.check()**: Evaluates all chains, returns list of [action, timeframe, price, data] tuples
- **Multi-level evaluation**: Each strategy maintains its own SignalManager; signals evaluated against current market data and levels

### Price Computation
- **Open Price**: Current close or next-predicted close (subject to trend)
- **Close Prices**: Graduated targets (+0.8%, +1.6%, +2.4%) or computed from level proximity
- **Stop-Loss**: SAR ± ATR buffer, adjusted for level proximity; separate logic for MOVE_STOP_LOSS

### Conflict Resolution
- DO_STOP_LOSS is highest priority — returned immediately, breaks evaluation loop
- CLOSE signals returned immediately, break evaluation loop
- MOVE_STOP_LOSS lower priority than CLOSE; skipped in safety states
- First OPEN signal in position-state-matching strategies wins; multiple OPENs → NOTHING

### State Machine Integration
- Position state gates strategy execution (WAIT vs. WAIT_SAFETY_BUY/SELL)
- Trend gating via `BoolValue_Signal("trend_up/down", tf)` inside signal chains

---

## 5. Potential Improvements

### 5.1 Confidence Scoring
- Each signal could emit confidence (0.0-1.0) alongside boolean result
- Aggregate confidence across signal chains weighted by relevance
- Use confidence in StrategyManager to:
  - Break ties when multiple strategies propose same action
  - Scale position size inversely with risk

### 5.2 Dynamic Strategy Weighting
- Instead of first-match-wins, assign weights to strategies based on:
  - Historical win rate in current market regime
  - NN prediction agreement
  - Volatility regime
- Weighted voting to select final action

### 5.3 Conflict Reduction
- Pre-check strategies for potential conflicts:
  - Detect LONG/SHORT signal pairs; require explicit confirmation
  - Enforce cooldown periods between opposite signals
  - Require higher confidence thresholds when market regime changes

### 5.4 NN Confidence Integration
- Load NN predictions at strategy evaluation time (not just manager level)
- Pass NN confidence to signal evaluation
- Strategies can adjust signal thresholds based on NN agreement

### 5.5 Position Sizing Integration
- Calculate position size dynamically based on:
  - Risk percentage (% of account)
  - ATR-based stop-loss distance
  - Signal confidence aggregation
- Return (action, qty, open_price, close_price, stop_price, timeframe) tuple

### 5.6 Level-Based Price Adjustments
- Support dynamic level updates during holding:
  - Trailing stop-loss following support levels
  - Dynamic exit targets based on resistance proximity
  - Volatility-adjusted level tolerance (wider in choppy markets)

### 5.7 Multi-Timeframe Confirmation
- Require signals from multiple timeframes before ENTRY
- Enforce trend alignment across 5/15/60/240 min timeframes
- Timeout-based signal expiration (valid only for N candles)

### 5.8 Strategy-Specific Risk Management
- Allow strategies to override position sizing rules
- Custom stop-loss placement per strategy type
- Graduated entry (size in 2-3 tranches over time)

### 5.9 Time-Based Signal Gating
- Disable certain signal types based on time of day (e.g., avoid entry 1h before close)
- Weekend/holiday handling
- Market session awareness (Binance perpetuals trade 24/7, but volatility varies)

### 5.10 Historical Signal Performance Feedback
- Track accuracy of each signal chain over trailing windows (e.g., 30 days)
- Dynamically adjust signal thresholds (CCI -140 vs. -100) based on recent performance
- Deprecate underperforming signal chains

---

## 6. Testing Strategy

### Unit Tests
- Test each strategy's `register_signals()` produces expected SignalChain count
- Test `check_conditions()` with various position states
- Test price computation (open, close, stop-loss) across action types

### Integration Tests
- Test StrategyManager conflict resolution with multiple strategy proposals
- Test NN loading and caching
- Test signal chain evaluation end-to-end

### Backtesting
- Simulate StrategyManager decision-making over historical data
- Measure action frequency, P&L impact, false signal rate
- Compare with baseline (e.g., buy-and-hold or random entries)

---

## 7. Files Affected

- `/home/om/projects/pybtctr2_brainstorm/pybtctr2_brainstorm_ai/strategies/strategy.py`
- `/home/om/projects/pybtctr2_brainstorm/pybtctr2_brainstorm_ai/strategies/example_strategy_long.py` (reference implementation — pipeline validation)
- `/home/om/projects/pybtctr2_brainstorm/pybtctr2_brainstorm_ai/strategies/example_strategy_short.py` (reference implementation — pipeline validation)
- `/home/om/projects/pybtctr2_brainstorm/pybtctr2_brainstorm_ai/strategy_manager.py`

---

## 8. Summary

The Strategy Module is a multi-layered decision system: individual strategies independently evaluate market conditions via signal chains, and StrategyManager orchestrates their outputs into a single, consistent action. The current design emphasizes simplicity and conflict avoidance; potential improvements focus on confidence-based voting, dynamic weighting, and tighter NN integration. All price levels (entry, exits, stops) are computed with market-aware adjustments (fees, ATR buffers, level proximity).
