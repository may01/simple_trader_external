# Strategy Module Specifications

This directory contains detailed specifications for the Strategy Module.

---

## Files Overview

### 1. [strategy-module.md](strategy-module.md)
**Module-level architecture and design**

- Overview: Coordination layer translating signals into trading actions
- Boundaries: Clear upstream (Data, Signals) and downstream (Robot, Position) dependencies
- Key Components: Strategy base class, ExampleStrategyLong/Short, StrategyManager
- Data Flow: Signal evaluation → action selection → conflict resolution → execution
- Existing Approach: Signal chains, level-based prices, priority-based selection
- Potential Improvements: Confidence scoring, dynamic weighting, NN integration

**Best for:** Understanding module boundaries, data flow, and high-level architecture.

---

### 2. [strategy-class.md](strategy-class.md)
**Abstract Strategy base class specification**

- Template Method pattern; base for all strategy implementations
- Key Attributes: SignalManager, fee injection, level management
- Abstract Methods: `register_signals()`, `check_conditions()`, `process_actions()`
- Key Methods: `check()`, `check_chains()`, `select_final_action()`, price computation
- Price Defaults: Entry (current close), Exit (`tgt_long/short` or +0.8% fallback), Stop (data-layer `sl_long/short` or SAR ± 0.3×ATR fallback)
- Trend gating via `BoolValue_Signal("trend_up/down", tf)` — no trend infrastructure in Strategy
- §9 Magic Numbers: all hardcoded ATR multipliers, SAR timeframes, and exit % values listed with refactor path

**Best for:** Understanding strategy contract, method signatures, price computation algorithms, and which values need future parameterisation.

---

### 3. [example-strategy-long-class.md](example-strategy-long-class.md)
**ExampleStrategyLong reference implementation**

- Purpose: Pipeline validation reference — NOT a production strategy
- Two signal chains: CCI -140 crossover up (entry), CCI 100 crossover down (exit)
- All price methods delegate to base class defaults
- Position gate: skip when WAIT_SAFETY_BUY / WAIT_BUY
- Magic Numbers: CCI thresholds and signal timeframe listed for future config extraction
- Copy-and-modify starting point for new long strategies

**Best for:** Understanding the minimum viable Strategy implementation and the long-side execution path.

---

### 4. [example-strategy-short-class.md](example-strategy-short-class.md)
**ExampleStrategyShort reference implementation**

- Purpose: Pipeline validation reference — NOT a production strategy
- Two signal chains: CCI 140 crossover down (entry), CCI -100 crossover up (exit)
- All price methods delegate to base class defaults
- Position gate: skip when WAIT_SAFETY_SELL / WAIT_SELL
- Comparison table vs ExampleStrategyLong (directions, gates, defaults)
- Copy-and-modify starting point for new short strategies

**Best for:** Understanding the short-side execution path and how to invert long signals.

---

### 5. [strategy-manager-class.md](strategy-manager-class.md)
**StrategyManager orchestration layer**

- Constructor: `StrategyManager(fee, robot_actions_test)` — no data stored; timeframes from `candles_config.yaml`
- Main Entry: `check(data, position_state, position_target, action_msg)` — data passed per tick
- Action Priority: DO_STOP_LOSS > CLOSE > MOVE_STOP_LOSS > OPEN > NOTHING
- Conflict Detection: Multiple OPEN signals → return NOTHING
- Predictor and NN outputs: Data layer IndicatorField subclasses, consumed via `DataPoint.get()`
- Levels: accessed via `data.get_levels()` — no Levels import in StrategyManager
- Depth methods: live-only, pending removal to dedicated live module
- §13 Fee Injection Rules: full propagation chain from `EXCHANGE_FEE` env var to Strategy/Position

**Best for:** Understanding strategy orchestration, conflict resolution, action priority logic, and fee propagation.

---

## Quick Reference: Key Concepts

### Action Types
- `STRATEGY_ACTION_OPEN_LONG/SHORT` — enter position
- `STRATEGY_ACTION_CLOSE_LONG/SHORT` — exit position (high priority)
- `STRATEGY_ACTION_MOVE_STOP_LOSS_*` — trail stop-loss (lower priority)
- `STRATEGY_ACTION_DO_STOP_LOSS` — immediate stop-loss (highest priority)
- `STRATEGY_ACTION_NOTHING` — no action (default)

### Priority Resolution
1. DO_STOP_LOSS → SET + IMMEDIATE BREAK
2. CLOSE signals → SET + IMMEDIATE BREAK
3. MOVE_STOP_LOSS → SET, continue
4. OPEN signals → SET, continue (count conflicts)
5. NOTHING → continue

**Conflict Rule:** Multiple OPEN signals → return NOTHING

### Position State Gates
- `POSITION_STATE_WAIT` — idle, no position
- `POSITION_STATE_WAIT_SAFETY_BUY` / `WAIT_BUY` — pending/entering long
- `POSITION_STATE_WAIT_SAFETY_SELL` / `WAIT_SELL` — pending/entering short

### Data Access Pattern
- All indicators, predictor outputs, and NN columns accessed via `DataPoint.get(col, tf, shift)`
- `data` passed as parameter to `check()` — never stored between ticks in StrategyManager
- Levels accessed via `data.get_levels()` — no direct Levels import in strategy layer
- Trend columns (`trend_up`, `trend_down`) pre-computed by Data layer; consumed via `BoolValue_Signal`

---

## Architecture Diagram

```
StrategyManager.check(data, position_state, ...)
    ├─ ExampleStrategyLong.check(data, ...)   ← reference / pipeline test
    ├─ ExampleStrategyShort.check(data, ...)  ← reference / pipeline test
    └─ StratLong1_v1 / StratShort1_v1        ← production strategies
         ↓
    Strategy base class
         ├─ SignalManager → SignalChain → BaseSignal
         └─ Price computation (open/close/stop)
              ↓
    DataPoint.get(col, tf, shift)   ← indicators, targets, NN cols, trend flags
              ↓
    Robot.execute()
```

## Data Flow Per Tick

1. `StrategyManager.check(data_point, position_state, position_target, action_msg)`
   - data_point carries all pre-computed indicator, predictor, and NN columns
   - For each strategy: `check_conditions()` gate → `strategy.check(data_point, ...)` → collect action
   - Apply priority resolution
   - Detect conflicts
2. Return `(action, open_price, close_price, stop_price, timeframe)`
3. `Robot.execute()` — execute final action
