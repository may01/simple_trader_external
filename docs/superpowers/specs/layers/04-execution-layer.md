# Execution Layer Specification

**Layer position:** Top layer — consumes trading decisions from Business Logic, executes them against Binance (live) or OHLC prices (simulation).

**Related specs:**
- [Main Architecture](../2026-05-05-pybtctr2-architecture.md)
- [Business Logic Layer](03-business-logic-layer.md)
- [Infrastructure Layer](01-infrastructure-layer.md)
- [Implementation Details](04-execution-layer-impl.md)

---

## 1. Overview

**Purpose:** Execute trading decisions produced by the Business Logic layer — placing orders on Binance in live mode, or replaying decisions against historical OHLC data in backtest mode. The Execution Layer bridges Business Logic intent and actual (or simulated) market outcomes.

**Four sub-concerns:**

| Sub-Concern | Responsibility | Key Module |
|---|---|---|
| Live Trading | Continuous polling loop; real order placement on Binance | `robot.py` |
| Backtest Execution | Step-by-step replay of historical data; simulated fills | `train_robot.py` |
| Data Preparation | Transform raw Binance data into data point artifacts for backtesting | `trainer.py` |
| Orchestration | Dispatch simulation and training runs; aggregate results | `trainer.py` |

**Key modules:** `robot.py`, `train_robot.py`, `trainer.py`, `strategies/actions.py`

---

## 2. Layer Boundaries

**Common upstream (feeds into all sub-concerns):**
- Business Logic layer: `StrategyManager.check()` returns action decisions; Position module owns trade state machine
- Data layer: OHLC candles, computed indicators, `SimulationData` (backtest) / `LiveData` (live)
- Infrastructure layer: logging, file I/O, path conventions

**Common downstream (consumed from all sub-concerns):**
- Visualization tools: read Action snapshots and Position state

**Sub-concern divergences:**

| Sub-Concern | Unique Upstream | Unique Downstream |
|---|---|---|
| Live Trading | Binance exchange (live market data, order fills) | Binance exchange (order placement) |
| Backtest Execution | SimulationData (wide DataFrame loaded once from Data Preparation output) | Orchestration (per-thread revenue results) |
| Data Preparation | Raw Binance OHLC from grabber output | `df_with_indicators.pkl` consumed by SimulationData |
| Orchestration | Data Preparation output; Backtest Execution workers | Aggregated revenue results; model artifacts |

---

## 3. Sub-Concern A — Live Trading

**Behavioral contract:**
- Maintain a continuous polling loop consuming current market state from Binance
- Evaluate strategy via StrategyManager at each cycle
- Route strategy decisions into the Position state machine (Business Logic)
- Execute resulting orders against Binance and report fills back to Position
- Persist position state after every cycle for crash recovery
- On restart, restore position state and re-query open orders from Binance

**Upstream:**
- Business Logic: Position (state machine + execution bridge), StrategyManager
- Data layer: live OHLC candles, depth data, computed indicators
- Infrastructure: Binance exchange via stock abstraction layer

**Downstream:**
- Binance: order placement, status queries, cancellations
- Visualization: position JSON, action snapshots
- Monitoring: log output

**Key interface exposed:**
- `robot.run_instantly(test_buy_sell=False)` — starts infinite polling loop; runs until external termination

**Key abstractions:**
- **Polling loop:** fetch market state → evaluate strategy → execute → persist → sleep
- **Order lifecycle:** place → monitor fills → cancel if needed → finalize and report to Position
- **Crash recovery:** position state persisted to disk after every cycle; restored on Robot restart with open order re-query

---

## 4. Sub-Concern B — Backtest Execution

**Behavioral contract:**
- Replay historical data point-by-point using the same strategy and position logic as Live Trading
- Simulate order fills against historical candle price extrema (no Binance API, no loan management, no persistence)
- Accumulate revenue results per independent worker thread
- Must produce identical strategy decisions as Live Trading given the same data (symmetry contract — see §7)

**Upstream:**
- SimulationData: `WideDataPoint` at each replay step, loaded once from `df_with_indicators.pkl`
- Business Logic: Position, StrategyManager (same logic as live — symmetry enforced)

**Downstream:**
- Orchestration: per-thread revenue totals and per-strategy breakdowns
- Visualization: action snapshots (same format as live)

**Key interfaces exposed:**
- `train_robot.step(data_point: WideDataPoint, action)` — executes one simulation step; `data_point` and resolved `action` are passed in per-call from the `trainer.py` loop; data is not stored between steps

**Key abstractions:**
- **Simulation step:** check position action queue → evaluate strategy → simulate fill against candle extrema
- **Price matching:** fills simulated at candle high/low rather than live market price — see [04-execution-layer-impl.md §2](04-execution-layer-impl.md) for fill conditions
- **Revenue accumulation:** per-thread totals aggregated by Orchestration on completion

---

## 5. Sub-Concern C — Data Preparation

**Behavioral contract:**
- Transform raw Binance OHLC data into time-ordered, versioned data point artifacts consumable by Backtest Execution
- Produce deterministic output for a given pair, time range, and configuration
- Must run to completion before Backtest Execution begins for the same time range

**Upstream:**
- Raw Binance OHLC data (from grabber output)
- Data layer: candle generation, multi-timeframe resampling, indicator computation

**Downstream:**
- `df_with_indicators.pkl` — wide DataFrame consumed by SimulationData → Backtest Execution

**Key interfaces exposed:**
- `trainer.main("generate_ohlc")` — triggers OHLC artifact generation; data is exposed via interface getters (see Data layer spec — `SimulationData` / `WideDataPoint`); no calculations performed at this layer
- `trainer.main("generate_data_points")` — iterate target time range; persist data point artifacts via data model interface; no indicator computation here

**Pre/post conditions:**
- **Pre:** raw Binance grabber data available for target pair and time range
- **Post:** `df_with_indicators.pkl` present for target pair and time range; SimulationData can iterate it without gaps

---

## 6. Sub-Concern D — Orchestration

**Behavioral contract:**
- Dispatch simulation and model training runs across parallel workers
- Coordinate Data Preparation output with Backtest Execution input
- Aggregate per-worker results into combined output
- Manage the full NN pipeline (data grouping, model training, NN-enhanced simulation)

**Upstream:**
- Data Preparation output (data point pkls)
- Backtest Execution workers (TrainRobot instances)

**Downstream:**
- Aggregated revenue results
- Trained model artifacts (NN weights, metadata)

**Key interface exposed:**
- `trainer.main(run_type)` — single dispatch entry point for all modes:
  - `simulate` — parallel backtest over full time range
  - `train` — parallel data generation for strategy training
  - `group_nn` / `nn_train` / `simulate_nn` — NN pipeline stages

**Parallelization contract:**
- Time range divided across N independent worker processes
- Each worker operates a full TrainRobot instance with no shared mutable state between workers
- Results aggregated on main process after all workers complete
- See [04-execution-layer-impl.md §5](04-execution-layer-impl.md) for parallelization implementation details

---

## 7. Shared Abstractions

### Action
Trading decision snapshot produced by both Live Trading and Backtest Execution in an identical format. Records decision type, price targets, timestamp, and chart markers. Consumed by Visualization.

### LiveOrderTracker
Live-only execution state extracted from the Position facade into a dedicated class owned by Robot. Tracks Binance order IDs, margin loan lifecycle, and provides the `reset()` call required before each new order placement:

```
LiveOrderTracker:
    buy_id: str | None
    sell_id: str | None
    loan_amount: float
    repay_amount: float

    set_order_id(side, order_id)
    reset()
    is_action_in_progress() -> bool
    set_loan(amount) / set_repay(amount) / get_loan()
```

Crash-recovery persistence (`save_position`, `load_position`, `restore_position`) lives in Robot, not in Position.

### Position Execution Bridge
The Position module lives in the Business Logic layer and owns all trade state. The Execution layer calls into Position to route decisions (`open`, `close`, `set_stop_loss`), report fills via the phase-semantic interface (`record_entry_fill`, `record_exit_fill` through `process_action`), and finalize trades (`finalize`).

`Robot` owns both `Position` and `LiveOrderTracker`. `TrainRobot` owns only `Position`. The Position class contains zero live-only state — symmetry is structurally enforced rather than enforced by convention.

### Execution/Simulation Symmetry Contract
The `wait()` logic and StrategyManager evaluation in Robot and TrainRobot must be identical. Any divergence between live and simulation behavior at this level invalidates backtest results as a predictor of live performance.

See [04-execution-layer-impl.md §7](04-execution-layer-impl.md) for open questions on how this symmetry is currently enforced and what gaps exist.

---

## 8. Constraints & Assumptions

- **Polling architecture:** Live Trading uses sleep-based polling; it is not event-driven — there is inherent latency between candle close and action execution
- **No slippage model:** Backtest Execution fills at exact candle price extrema; this overestimates real live performance
- **Ownership boundary:** Execution layer never owns or directly modifies Position state — it only calls BL-owned methods and reads their results
- **Data Preparation prerequisite:** Backtest Execution requires Data Preparation to have completed for the target time range and pair before simulation begins
- **Paper-trade mode:** Live Trading supports a test mode that tracks orders without submitting them to Binance exchange

→ Implementation details extracted from earlier versions of this spec are tracked in [04-execution-layer-impl.md](04-execution-layer-impl.md)
