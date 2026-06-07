# PyBTCTR2 Implementation Plan v2

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Implement the full simple_trader cryptocurrency trading bot — live trading, backtesting, NN pipeline, and visualization — from infrastructure through frontend.

**Architecture:** Bottom-up, layer-first. Docker entry points defined first. Each layer exposes a typed interface before either side is implemented. No layer reaches into internals of another. Integration boundary must be GREEN in Docker before proceeding to next phase.

**Tech Stack:** Python 3.11, Docker Compose, pandas, TA-Lib, pandas-ta, Keras/TensorFlow, python-binance, Dash/Plotly, multiprocessing.

---

## Phase Index

| Phase | Folder | Focus |
|-------|--------|-------|
| 00 | `phase-00-infrastructure/` | Docker, constants, helpers, config YAMLs |
| 01 | `phase-01-stock-abstraction/` | BaseStock interface, BinanceStock, StockHolder |
| 02 | `phase-02-data-acquisition/` | Graber — Binance klines → graber_data.pkl |
| 03 | `phase-03-data-layer/` | DataPoint, wide DataFrame, Indicators, LiveData, SimulationData, FullData, Levels |
| 04 | `phase-04-signal-library/` | BaseSignal + all 50+ signal type implementations |
| 05 | `phase-05-signals-logic/` | SignalChain, SignalManager |
| 06 | `phase-06-position-management/` | Coin, BasePosition, LongPosition, ShortPosition, Position facade |
| 07 | `phase-07-strategy/` | Strategy base, ExampleStrategyLong/Short, StrategyManager |
| 08 | `phase-08-backtesting/` | TrainRobot, SimulationOrchestrator, PerformanceAnalyzer |
| 09 | `phase-09-training-pipeline/` | Graber class, DataPreparer, Trainer, LiveDataCollector |
| 10 | `phase-10-execution/` | LiveOrderTracker, Robot polling loop + order management |
| 11 | `phase-11-nn-module/` | NNModel, NNPredictor, CheckpointManager, NNOrchestrator |
| 12 | `phase-12-frontend/` | ChartRenderer, DataViewer, TrainingDashboard, LiveDashboard |

---

## Docker Entry Points

```bash
# Path A — collect raw klines
docker compose run --rm trader python3 grabers/grab_binance.py

# Path B — build wide DataFrame with indicators
docker compose run --rm trainer python3 trainer.py generate_full_ohlc

# Path C — run backtest simulation
docker compose run --rm trainer python3 trainer.py simulate

# Path D1/D2/D3 — NN pipeline
docker compose run --rm trainer python3 trainer.py group_nn
docker compose run --rm trainer python3 trainer.py nn_train
docker compose run --rm trainer python3 trainer.py simulate_nn

# Path E — live trading (paper mode: IS_TRAIDER_TEST=1)
docker compose -f docker-compose-live.yml run --rm trader python3 pybtctr.py

# Path F — data viewer
docker compose -f docker-compose-view.yml run --rm viewer python3 view_online_point.py
```

---

## Layer Dependency Order

```
Docker / Infrastructure (Phase 00)
  ↓
Stock Abstraction (Phase 01)       ← Binance API adapter
  ↓
Data Acquisition (Phase 02)        ← graber_data.pkl
  ↓
Data Layer (Phase 03)              ← wide DataFrame + DataPoint protocol
  ↓
Signal Library (Phase 04)          ← 50+ atomic + composite signal types
  ↓
Signals Logic (Phase 05)           ← SignalChain + SignalManager
  ↓
Position Management (Phase 06)     ← trade lifecycle state machine
  ↓
Strategy (Phase 07)                ← decision engine
  ↓
Backtesting (Phase 08)             ← TrainRobot + SimulationOrchestrator
  ↓
Training Pipeline (Phase 09)       ← DataPreparer + Trainer + LiveDataCollector
  ↓
Execution (Phase 10)               ← Robot (live trading)
  ↓
NN Module (Phase 11)               ← NNModel + NNOrchestrator
  ↓
Frontend (Phase 12)                ← Dash dashboards
```

---

## Critical Design Decisions

- Column naming: `{tf}_{col}` everywhere — `5_rsi_14`, `60_close` — live and simulation share same convention
- Indicators calculated at EVERY 1-min row — `build_indicator_input()` feeds all prior closed candles + current partial candle row to `Indicators.compute()`; non-closed rows get a real calculated value, never NaN, never forward-filled
- `DataPoint.get(col, tf, shift)` is the ONLY consumer interface — signals/strategies never access `ohlc[tf]` directly
- `fee` always injected via constructor from `stock.item.fee` — never hardcoded anywhere
- `record_entry_fill(coin_amount, price)` / `record_exit_fill(coin_amount, price)` for fill reporting — not `add_buy`/`add_sell`
- `LiveOrderTracker` (Execution layer) owns order IDs, margin loans, JSON persistence — `Position` owns only BL state
- `StrategyManager.__init__(fee, robot_actions_test)` — no data stored at construction; `data_point` passed per-tick
- `TrainRobot.step(data_point, action)` — data passed in per call, not stored as attribute
- Stop-loss check in simulation delegated to `position.is_stop_loss_triggered(cur_price)` — no inline logic in TrainRobot
- Active TFs: `[1, 5, 15, 60, 240, 1440]` from `candles_config.yaml` — not hardcoded
- Indicator registry from `indicators_config.yaml` — no field names hardcoded in `Indicators`
- `do_stock_init()` must be called once at process startup before any `stock.item` access

---

## Unresolved — Resolve After First Implementation

These decisions are deferred until the core pipeline is working end-to-end.

### NN target labeling (`{tf}_target_direction`)

**Problem:** `NNOrchestrator.train()` needs a supervised label per closed candle — what direction did price move over the next N candles? The label column name, class encoding, labeling logic (threshold, horizon), and which component computes it are all undecided.

**Affects:** `DataPreparer._compute_nn_targets()` (removed from first impl), `NNOrchestrator.train()` (marked UNRESOLVED), `indicators_config.yaml` `nn` section (horizon/threshold params not yet added).

**Questions to resolve:**
1. Class encoding: `{0=up, 1=neutral, 2=down}` or different?
2. Horizon: fixed N candles, or derived from existing `tgt_long`/`tgt_short` target fields?
3. Threshold: absolute price delta %, or ATR-relative?
4. Column name: `{tf}_target_direction` or other?
5. Who computes: `DataPreparer` (at prep time) or `NNOrchestrator` (at train time from raw price)?
