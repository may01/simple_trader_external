# PyBTCTR2 System Architecture Specification

**Version:** 1.0 — Phase 1 (Layer Specifications)
**Design document:** [Specification Design](2026-05-04-pybtctr2-specification-design.md)

---

## 1. System Overview

PyBTCTR2 is a cryptocurrency trading bot and backtesting framework for the Binance exchange. It operates on a single trading pair (e.g., `link_usdt`) and makes automated buy/sell decisions using technical indicators, signal chains, and configurable strategies.

**Two operational modes:**
- **Live trading** (`robot.py`): Connects to Binance API, polls market data every 5-30 seconds, places real orders
- **Backtesting / Simulation** (`train_robot.py` + `trainer.py`): Replays historical OHLC data, simulates fills at candle prices, measures strategy performance

**Four layers** (bottom to top):
1. **Infrastructure** — Docker, config, logging, file paths
2. **Data** — Binance data collection, OHLC generation, indicator calculation, level management
3. **Business Logic** — Signal evaluation, strategy coordination, action decision
4. **Execution** — Order placement, position lifecycle, revenue tracking

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    EXECUTION LAYER                       │
│  Robot (live) / TrainRobot (sim) / Trainer (orchestrate)│
│  Order placement / Fill processing / Crash recovery     │
└──────────────────────┬──────────────────────────────────┘
                       │ calls check(); reads position.get_action()
                       │ reports fills via record_entry_fill/record_exit_fill
                       ▼
┌─────────────────────────────────────────────────────────┐
│                BUSINESS LOGIC LAYER                      │
│  StrategyManager → Strategy → SignalManager             │
│  SignalChains (50+ signal types) → Action decisions     │
│  Position state machine / Trade lifecycle / P&L / Risk  │
└──────────────────────┬──────────────────────────────────┘
                       │ reads via get_cur_price()
                       ▼
┌─────────────────────────────────────────────────────────┐
│                    DATA LAYER                            │
│  Data (OHLC multi-TF) / Indicators / Levels             │
│  grab_binance.py (collection) / SimulationData (replay) │
└──────────────────────┬──────────────────────────────────┘
                       │ uses paths, env vars, logging
                       ▼
┌─────────────────────────────────────────────────────────┐
│               INFRASTRUCTURE LAYER                       │
│  Docker / configs/*.env / logs.py / helpers.py          │
│  Docker volumes (/trader_data) / stats/ files           │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Critical Path

The real-time trading loop flows through these components in sequence:

```
Stock Abstraction (stocks/)
   ↓ fetch 1-min klines from Binance API
Data (data.py)
   ↓ build_candles() — fetch 1-min klines; compute indicators for [1,5,15,60,240,1440] min
Signals (signals_lib/)
   ↓ evaluate 50+ signal chains against enriched OHLC
Strategy (strategies/)
   ↓ select action (OPEN_LONG, CLOSE_SHORT, MOVE_STOP_LOSS, ...) + prices
StrategyManager (strategy_manager.py)
   ↓ coordinate multiple strategies; resolve conflicts; return single decision
Position (position/)
   ↓ apply decision to state machine; enforce risk rules; set execution intent
Robot / TrainRobot
   ↓ read position.get_action(); execute via Binance API (live) or OHLC simulation (backtest)
   ↓ report fills → position.record_entry_fill/record_exit_fill → position.finalize → (revenue_pct, revenue_abs)
```

---

## 4. Layer Specifications

| Layer | Spec file | Purpose |
|-------|-----------|---------|
| Infrastructure | [01-infrastructure-layer.md](layers/01-infrastructure-layer.md) | Runtime environment, config, logging, paths |
| Data | [02-data-layer.md](layers/02-data-layer.md) | Market data, OHLC, indicators, levels |
| Business Logic | [03-business-logic-layer.md](layers/03-business-logic-layer.md) | Signals, strategies, trading decisions, position state machine, P&L, risk management |
| Execution | [04-execution-layer.md](layers/04-execution-layer.md) | Order placement, fill processing, crash recovery, training orchestration |

---

## 5. End-to-End Data Flow (Live Trading)

```
[1] Binance Exchange
      1-min OHLCV klines
      ↓ stock.item.update_candles()
[2] data.ohlc[1] (raw 1-min DataFrame)
      ↓ Data.build_candles() — resample to all TFs + Indicators.calc() + prepare_candles() + update_candles_indicators()
[3] data.ohlc[tf] for tf in [1,3,5,15,60,240]
      enriched with: RSI, MACD, CCI, EMA, ATR, Bollinger, SAR, ADX + diff%/rolling/class columns
      ↓ data.get_cur_price(col, shift, tf)
[4] Scalar indicator values
      ↓ SignalChain.check() — each signal reads via get_cur_price()
[5] Completed signal chains → actions_list
      ↓ Strategy.select_final_action() + get_open/close/stop_loss_price()
[6] (action, open_price, close_price, stop_price, tf)
      ↓ StrategyManager resolves across all strategies
[7] Single winning decision
      ↓ Robot.wait() routes to Position (Business Logic)
[8] Position.open() / close() / set_stop_loss()  [Business Logic — state machine transitions]
      ↓ position.get_action() → Robot reads execution intent
      ↓ Robot.trade_action() → stock.item.trade()
[9] Binance order placed → fill confirmed → position.record_entry_fill/record_exit_fill() → position.finalize()
      ↓ LiveOrderTracker.save_position() + action.save()
[10] JSON + pkl persisted to /trader_data volume
```

---

## 6. End-to-End Data Flow (Backtesting)

```
[1] graber_data.pkl (raw 1-min OHLCV, collected once by grab_binance.py)
      ↓ trainer.py RUN_TYPE=generate_full_ohlc — compute indicators at is_closed rows; save wide DataFrame
[2] df_with_indicators.pkl  (1-min indexed wide DataFrame, all TFs and indicators pre-computed)
      ↓ SimulationData(pair, begin_ts, end_ts, step_min) — load once at init
[3] WideDataPoint(df, ts) — at each replay timestamp (O(1), no I/O)
      ↓ same DataPoint protocol as live; signals/strategies call point.get(col, tf, shift)
[4] StrategyManager.check(data_point, ...) → (action, prices)
      ↓ train_robot.step(data_point, action)
[5] Position.open() / close()  [Business Logic — state machine transitions]
      ↓ TrainRobot.buy() / sell() — match against candle low/high
[6] Simulated fill → position.record_entry_fill/record_exit_fill() → position.finalize() → (revenue_pct, revenue_abs)
      ↓ accumulated to total_revenue per thread
[7] Trainer aggregates across all threads
[8] Final simulation result: total % return over time period
```

---

## 7. Key Subsystems (Phase 2 Critical Path)

Full module and class specifications for these subsystems are in `docs/superpowers/specs/critical-path/`:

| Subsystem | Key classes | Layer | Description |
|-----------|------------|-------|-------------|
| Stock Abstraction | `BinanceStock`, `StockItem` | Data | Binance API adapter for data fetch and order execution |
| Data Module | `Data`, `SimulationData`, `Indicators`, `Levels` | Data | OHLC management and enrichment |
| Signals Module | `SignalManager`, `SignalChain`, `BaseSignal` + 50+ signal types | Business Logic | Market signal evaluation |
| Strategy Module | `Strategy`, `ManualStrategyLong`, `ManualStrategyShort`, `StrategyManager` | Business Logic | Trading decision logic |
| Position Module | `Position`, `BasePosition`, `LongPosition`, `ShortPosition`, `Coin` | Business Logic | Trade lifecycle, state machine, P&L, risk management |
| Robot Module | `Robot` | Execution | Live trading — order placement and fill management |

*(Critical-path specs to be written in Phase 2)*

---

## 8. Supporting Systems (Phase 3)

Full specifications for these systems are in `docs/superpowers/specs/supporting-systems/`:

| System | Description |
|--------|-------------|
| Training Module | `Trainer` orchestration; generate_full_ohlc, generate_data_points, train, simulate modes |
| NN Module | Neural network training, prediction, and probability integration |
| Backtesting Module | `TrainRobot` simulation and `SimulationData` replay |
| Frontend Visualization | Data viewer, training dashboard, live trading dashboard |

*(Supporting system specs to be written in Phase 3)*

---

## 9. Configuration Summary

All runtime behavior is controlled by environment variables injected via docker-compose env files:

| Variable | Effect |
|----------|--------|
| `PAIR` | Trading pair (`link_usdt`) — affects all data paths and Binance API calls |
| `DATA_SET_NAME` | Dataset name — forms the storage path under `/trader_data/{DATA_ROOT}/` |
| `DATA_START` / `DATA_END` | Time bounds for training/simulation (Unix ms) |
| `ROOT_FOLDER` | `"local"` or `"remote"` — selects Docker volume mount |
| `USE_NN_SIMULATION` | `"True"`: load pre-computed NN pkl; `"False"`: live inference |
| `TRAINER_TIME_STEP` | Simulation step size in minutes |
| `AVAIABLE_THREADS` | Parallel process count |
| `IS_TRAIDER_TEST` | `"1"`: paper-trade mode (live env only) |

---

## 10. Constraints and Invariants

- **Single pair per process**: each container runs one `PAIR`; to trade multiple pairs, run multiple containers
- **UTC timestamps throughout**: all internal times are Unix epoch seconds; DATA_START/DATA_END are milliseconds
- **Indicator dependency**: TA-Lib C library must be compiled at build time; changing indicator logic requires Docker rebuild
- **Singleton data access**: `data.item` (`LiveData`) is the only module-level singleton; `SimulationData` and `FullData` are instantiated per run — no dependency injection for live path
- **Stateful signal chains**: SignalChain state persists across ticks — chains advance toward completion over multiple candles
- **Classification statics**: `rsi_classification.json` and `diff_stats.pkl` in stats/ are version-controlled and static per pair; changing them requires reprocessing all historical data
