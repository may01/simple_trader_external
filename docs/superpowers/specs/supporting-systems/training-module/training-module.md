# Training Module Specification

**Version:** 2.0 — Class-decomposed architecture aligned with Data Module v2.0
**Supersedes:** Version 1.0 (monolithic `Trainer` class)
**Module:** Training
**File:** `trainer.py` (plus supporting class files)
**Purpose:** Orchestrate data retrieval, wide-DataFrame preparation, simulation, and neural network pipelines for the pybtctr2 trading bot.

---

## 1. Overview

The Training Module is the orchestration engine for the entire training and backtesting workflow of pybtctr2. In v2.0, the previously monolithic `Trainer` class is decomposed into a thin orchestrator (`Trainer`) plus five specialized collaborator classes, each owning a single phase of the lifecycle:

| Class | Responsibility |
|-------|----------------|
| `Trainer` | Thin orchestrator; reads `RUN_TYPE`, manages metadata, dispatches to collaborators |
| `Graber` | Data retrieval: fetch 1-min OHLCV from the Binance API for the requested range and write `graber_data.pkl` to disk |
| `DataPreparer` | Read `graber_data.pkl`; build the wide base DataFrame; run per-minute `Indicators.compute()` in time-batched workers; compute NN forward-looking targets; compute stats; save `df_with_indicators.pkl` |
| `SimulationOrchestrator` | Parallel backtest: spawn workers using `SimulationData` + `TrainRobot`, aggregate thread results |
| `NNOrchestrator` | NN pipeline: `group_nn`, `train_nn`, `simulate_nn` |
| `LiveDataCollector` | Continuous live-data ingestion from Binance (60s loop) |

This decomposition aligns the module with the **Data Module v2.0** two-path architecture:
- The legacy per-timestamp snapshot directory (`data/{pair}/{ts}/ohlc.pkl`) is gone. All offline data lives in a single `df_with_indicators.pkl` (wide DataFrame, 1-min indexed).
- The legacy `DataIterator` is replaced by `SimulationData`, which yields `WideDataPoint` objects sharing the same `DataPoint` protocol used by live trading.
- NN forward-looking targets are implemented as `IndicatorField` subclasses computed once at preparation time, not as a separate generation pass.

The module retains parallel-first execution. Both data preparation (per-tf indicator computation) and simulation can be split across `AVAIABLE_THREADS` worker processes. Aggregation happens on the main thread.

---

## 2. Module Boundaries

### Upstream Dependencies
- **Binance API** — Read by `Graber` to produce `graber_data.pkl` (raw 1-min OHLCV). Auth via `BINANCE_API_KEY` / `BINANCE_API_SECRET`.
- **Data Module v2.0** — `Indicators`, `IndicatorField` registry (`indicators_config.yaml`), `DataAttributes`, `SimulationData`, `WideDataPoint`, `FullData`, `LiveData`
- **Strategy / TrainRobot** — Consumed during simulation
- **NN Module** — Consumed by `NNOrchestrator`
- **Environment config** (`configs/*.env`) — `DATA_START`, `DATA_END`, `TRAINER_TIME_STEP`, `AVAIABLE_THREADS`, `NN_CLS`, `NN_TGT`, `NN_TYPE`, `SHUFFLE_GROUPED_NN_DATA`

### Downstream Consumers
- **`SimulationData`** reads `df_with_indicators.pkl` for replay
- **`FullData`** reads `df_with_indicators.pkl` for visualization and NN training views
- **Strategy / TrainRobot** consume `WideDataPoint` instances during simulation
- **Live Robot** consumes `LiveDataCollector` output during live trading

### RUN_TYPE → Class Mapping

| `RUN_TYPE` | Dispatch |
|------------|----------|
| `grab_data` | `Graber(pair).grab_from_env()` — downloads Binance 1-min klines, writes `graber_data.pkl` |
| `generate_full_ohlc` | `DataPreparer(pair, trainer).prepare()` — reads `graber_data.pkl`, builds the wide base DataFrame, enriches with indicators + NN targets, writes `df_with_indicators.pkl` |
| `simulate` | `SimulationOrchestrator.run()` |
| `group_nn` | `NNOrchestrator.group(class_type)` |
| `nn_train` | `NNOrchestrator.train()` |
| `simulate_nn` | `NNOrchestrator.simulate()` |
| `collect_live` | `LiveDataCollector.run()` |

`grab_data` and `generate_full_ohlc` are independent pipelines coupled by `graber_data.pkl` on disk; a user can re-run `generate_full_ohlc` against the same raw file as many times as they want (e.g. to regenerate after changing `indicators_config.yaml`) without redownloading from Binance.

The legacy `generate_data_points`, `generate_data_points_prediction`, `generate_nn_points`, and `train` RUN_TYPEs are removed in v2.0 — all of their work is now performed by `DataPreparer` during a single `generate_full_ohlc` pass.

---

## 3. Class Architecture

```
                    ┌──────────────────────────────────────┐
                    │              Trainer                 │
                    │  (RUN_TYPE dispatch, metadata mgmt)  │
                    └──┬───────┬───────┬──────────┬────────┘
                       │       │       │          │
            ┌──────────┘       │       │          └─────────────────┐
            ▼                  ▼       ▼                            ▼
   ┌────────────────┐   ┌──────────────┐   ┌───────────────────┐    ┌────────────────────┐
   │     Graber     │   │ DataPreparer │   │ SimulationOrchestr│    │   NNOrchestrator   │
   │ (Binance API)  │   └──────────────┘   └───────────────────┘    └────────────────────┘
   └────────────────┘          ▲                     │                        │
            │                  │                     │                        │
            ▼                  │   df_with_indicators.pkl ◀──────────────────┘
   graber_data.pkl ────────────┘   (Data Module v2.0)        reads via SimulationData
        (disk)                                              and FullData

   ┌────────────────────┐
   │ LiveDataCollector  │  (separate process; writes to LiveData singleton)
   └────────────────────┘
```

**Key Properties**
- Two-step offline pipeline: `Graber` writes `graber_data.pkl` to disk → `DataPreparer` reads it and writes `df_with_indicators.pkl`. The two classes do not share in-memory state.
- All downstream consumers (`SimulationOrchestrator`, `NNOrchestrator`, visualization) read from `df_with_indicators.pkl` exclusively. None of them re-derive base OHLCV or indicators.
- `LiveDataCollector` sits on a parallel track — it does not feed the offline pipeline.

---

## 4. Data Flow

### 4.1 Offline Preparation — Two-Step Pipeline

#### Step 1: `RUN_TYPE=grab_data`

```
┌──────────────────────────────────────┐
│  Graber(pair).grab_from_env()        │
│  - read DATA_START / DATA_END        │
│  - paginated Binance klines API call │
│  - incremental merge if file exists  │
│  - validate strictly 1-min spacing   │
└───────────┬──────────────────────────┘
            ▼
┌───────────────────────────────┐
│   graber_data.pkl             │ (raw 1-min OHLCV from Binance,
│   columns: o,h,l,c,v,         │  written atomically via temp+rename)
│            taker_base_vol     │
└───────────────────────────────┘
```

#### Step 2: `RUN_TYPE=generate_full_ohlc`

```
┌──────────────────────────────────────┐
│   graber_data.pkl                    │ (input — produced by Step 1)
└───────────┬──────────────────────────┘
            ▼
   ┌──────────────────────────────────────┐
   │  DataPreparer(pair, trainer).prepare()│
   │                                      │
   │  1. _load_raw_data()                 │
   │       read graber_data.pkl, rename   │
   │       columns, slice to date range,  │
   │       validate 1-min index           │
   │                                      │
   │  2. _build_base_dataframe(raw_df)    │
   │       for tf in CANDLES build        │
   │       {tf}_open/high/low/close/      │
   │       volume/buy_volume/open_index/  │
   │       is_closed (Data Module v2.0    │
   │       §4.1–§4.2)                     │
   │                                      │
   │  3. Load indicators_config.yaml      │
   │                                      │
   │  4. Split base_df.index into N       │
   │     timestamp batches; per worker:   │
   │       for ts in batch:               │
   │         for tf in CANDLES:           │
   │           WideDataPoint(df, ts)      │
   │           Indicators.compute(pt, tf) │
   │     Main thread concatenates slices. │
   │     (per-minute; no ffill — each     │
   │      row is a complete WideDataPoint)│
   │                                      │
   │  5. Compute NN forward-looking       │
   │     targets on main thread           │
   │     (IndicatorField nn_targets group)│
   │                                      │
   │  6. DataAttributes.compute(df)       │
   │       → rsi_classification.json      │
   │       → diff_stats.pkl               │
   │                                      │
   │  7. Save df_with_indicators.pkl      │
   │       via temp-file + atomic rename  │
   └───────────┬──────────────────────────┘
               ▼
   ┌──────────────────────────────────────┐
   │   df_with_indicators.pkl             │
   │   (wide, 1-min indexed, ~300+ cols)  │
   └──────────────────────────────────────┘
```

Step 1 and Step 2 are decoupled by the on-disk `graber_data.pkl`. Re-running Step 2 is cheap when only `indicators_config.yaml` has changed — no Binance traffic is incurred.

### 4.2 Simulation (`RUN_TYPE=simulate`)

```
   ┌──────────────────────────────────────┐
   │  SimulationOrchestrator              │
   │  - split [DATA_START, DATA_END]      │
   │    into AVAIABLE_THREADS segments    │
   │  - spawn N worker processes          │
   └───────────┬──────────────────────────┘
               ▼  (per worker)
   ┌──────────────────────────────────────┐
   │  SimulationData(pair, b, e, step)    │
   │   while not is_end():                │
   │      point = sim.get()  # WideDataPt │
   │      action = strategy(point)        │
   │      robot.step(point, action)       │
   │      sim.next()                      │
   │   → write thread_result_by_id_N.pkl  │
   └───────────┬──────────────────────────┘
               ▼
   ┌──────────────────────────────────────┐
   │  Main thread aggregation             │
   │  - merge revenue_by_id across threads│
   │  - merge levels                      │
   │  - save shared/simulation_results.pkl│
   └──────────────────────────────────────┘
```

### 4.3 NN Pipeline (`RUN_TYPE=group_nn` → `nn_train` → `simulate_nn`)

```
   df_with_indicators.pkl
            │
            ▼ FullData.get(tf=N)[nn_feature_cols]
   ┌──────────────────────────────────────┐
   │  NNOrchestrator.group(class_type)    │
   │  - read NN feature/target columns    │
   │    via FullData                      │
   │  - bucket by classification          │
   │  - shuffle (optional)                │
   │  - save nn_group_{ct}_{cls}_{n}.pkl  │
   └───────────┬──────────────────────────┘
               ▼
   ┌──────────────────────────────────────┐
   │  NNOrchestrator.train()              │
   │  - for cls in permutations:          │
   │      NN(...).train(group)            │
   └───────────┬──────────────────────────┘
               ▼
   ┌──────────────────────────────────────┐
   │  NNOrchestrator.simulate()           │
   │  - load_model + run_batch per class  │
   │  - aggregate long/short probabilities│
   │  - save nn_simulation_*.pkl          │
   └──────────────────────────────────────┘
```

---

## 5. Execution Flow per RUN_TYPE

### A. `grab_data`

1. `Trainer.__init__()` → `load_metadata()` (metadata not mutated by this RUN_TYPE)
2. `graber = Graber(pair)` → `graber.grab_from_env()`
   - Reads `DATA_START` / `DATA_END` env vars (ms → seconds)
   - Paginated calls to Binance klines API
   - If `graber_data.pkl` exists, fetches only the missing range and merges (incremental mode)
   - Validates strictly 1-min spacing
   - Writes `graber_data.pkl` via temp-file + atomic rename

### B. `generate_full_ohlc`

1. `Trainer.__init__()` → `load_metadata()`
2. `preparer = DataPreparer(pair, trainer)` → `preparer.prepare()`
   - `_load_raw_data()` reads `graber_data.pkl` and validates schema
   - `_build_base_dataframe()` builds the wide base DataFrame (Data Module v2.0 §4.1–§4.2)
   - Loads `indicators_config.yaml`
   - Computes indicators in time-batch workers (parallel across `AVAIABLE_THREADS`); per-minute compute, no ffill
   - Computes NN forward-looking targets on the main thread
   - Computes `DataAttributes` stats if absent
   - Saves `{root_folder}/{pair}/df_with_indicators.pkl` via temp-file + atomic rename
3. `Trainer.metadata` updated with `begin_point`, `end_point`, `time_step` from the resulting DataFrame
4. `Trainer.save_metadata()`

### C. `simulate`

1. `Trainer.__init__()` → `load_metadata()`
2. `orchestrator = SimulationOrchestrator(pair)`
3. `orchestrator.run()`:
   - Clean old thread result files
   - Split date range across `AVAIABLE_THREADS`
   - Spawn `mp.Process(target=simulate_range, args=(...))` per segment
   - Each worker constructs `SimulationData` + `TrainRobot`, replays, persists `thread_result_by_id_N.pkl`
   - Main thread joins, aggregates, saves `simulation_results.pkl`
4. Final revenue logged

### D. `group_nn`

1. `Trainer.__init__()`
2. `nn = NNOrchestrator(pair)` → `nn.group(class_type)`:
   - Open `FullData` view over `df_with_indicators.pkl`
   - For each NN-eligible closed candle, extract `(features, target, class)`
   - Accumulate per-class buckets of size 5000, optionally shuffle, persist to `nn_group_*.pkl`

### E. `nn_train`

1. `nn = NNOrchestrator(pair)` → `nn.train()`:
   - For each `(class_type, cls, tf_type, target_type)` permutation in env config:
     - Build `NN(...)` instance, call `train(data_group=1)`

### F. `simulate_nn`

1. `nn = NNOrchestrator(pair)` → `nn.simulate()`:
   - Load `FullData` view
   - For each NN configuration / classification:
     - Load model, run batch, accumulate long/short probabilities
   - Aggregate across configurations, save `nn_simulation_cls_big_tf.pkl`

### G. `collect_live`

1. `collector = LiveDataCollector(pair)` → `collector.run()`:
   - Infinite 60s-aligned loop: fetch latest candles via `LiveData.build_candles()`, persist snapshot

---

## 6. Parallelization Model

Two distinct workloads parallelize across `AVAIABLE_THREADS` processes:

| Phase | Sharded by | Aggregator |
|-------|-----------|------------|
| `DataPreparer.prepare()` | timestamp range (one worker per contiguous time batch; each worker computes all timeframes' indicators for every 1-min row in its batch) | Main thread concatenates row slices into the wide DataFrame, then runs NN forward-looking targets + `DataAttributes` sequentially |
| `SimulationOrchestrator.run()` | timestamp range (one worker per segment) | Main thread merges `thread_result_by_id_N.pkl` files |

Worker processes communicate via:
- **Pickle files on shared disk** (`thread_result_by_id_N.pkl`, per-batch indicator slices)
- **`mp.Value`** for live totals (`total_revenue`, `total_revenue_abs`)
- Each `DataPreparer` worker holds read access to the full `base_df` (copy or `mp.shared_memory`); no overlap or warmup is required because indicator math is a pure function of base OHLCV columns.

NN training is sequential by design (single-process backpropagation); the existing classification-permutation loop is preserved inside `NNOrchestrator.train()`.

---

## 7. Configuration Surface

All collaborators read configuration through the `Trainer` orchestrator rather than `os.environ` directly. `Trainer` exposes:

| Method | Returns | Source |
|--------|---------|--------|
| `train_begin_time()` | `int` (Unix seconds) | `DATA_START` / 1000 |
| `train_end_time()` | `int` (Unix seconds) | `DATA_END` / 1000 |
| `train_time_step()` | `int` (minutes) | `TRAINER_TIME_STEP` |
| `data_graber_date_limits()` | `(datetime, datetime)` | `DATA_START`, `DATA_END` |
| `available_threads()` | `int` | `AVAIABLE_THREADS` |

The class-level metadata dict (`{begin_point, end_point, time_step}`) is owned by `Trainer` and persisted to `{data_folder}/metadata.pkl`. Collaborators read it via `Trainer.metadata` or via constructor injection.

---

## 8. Key Differences from v1.0

| Concern | v1.0 (deprecated) | v2.0 |
|---------|-------------------|------|
| Storage of prepared data | `data/{pair}/{ts}/ohlc.pkl` per timestamp | Single `df_with_indicators.pkl` |
| Replay iterator | `DataIterator` (per-step pickle load) | `SimulationData` (single load at init) |
| Consumer interface | `data.get_cur_price(col, shift, tf)` | `point.get(col, tf, shift)` (`DataPoint` protocol) |
| NN target generation | Separate pass in `parallel_generate_data_points` | `IndicatorField` subclasses run by `DataPreparer` |
| Data retrieval | `grabers/grab_binance.py` script + inline `pd.read_pickle()` in Trainer methods | `Graber` class (network ingestion → `graber_data.pkl`); `DataPreparer` reads it |
| Wide base DataFrame build | Inline in `Trainer.generate_full_ohlc` | `DataPreparer._build_base_dataframe()` |
| Indicator computation | Inline in Trainer | `Indicators.compute()` from data module, driven by `DataPreparer` per-minute |
| Orchestrator size | ~1300 LOC | `Trainer` ≤ ~200 LOC; logic distributed |
| RUN_TYPE: `generate_data_points*` | 3 separate modes | Removed — collapsed into `generate_full_ohlc` |
| RUN_TYPE: `train` | Skeleton method | Removed — strategy training is handled inside `DataPreparer`-produced columns (`tgt_long`, etc.) |

---

## 9. Constraints and Invariants

- **Single source of truth for prepared data:** `df_with_indicators.pkl`. `graber_data.pkl` is the raw input; `DataPreparer` is the only class that reads it as a pipeline consumer. (`Graber` may also read it in incremental mode to merge new data with existing rows.)
- **Network access is isolated to `Graber`:** No other class in the module performs Binance API calls during the offline pipeline. `LiveDataCollector` is the only other network-touching class, and it operates on the live path, not offline preparation.
- **Indicator registry is config-driven:** `DataPreparer` does not hardcode field names; it reads `indicators_config.yaml` and delegates to `Indicators`.
- **Timeframes are config-driven:** `candles_config.yaml` defines `CANDLES = [1, 5, 15, 60, 240, 1440]`.
- **NN forward-looking targets are safe at preparation time:** Each target field reads `df.loc[ts+N]` from the complete historical DataFrame. Live path does not compute these (only consumes them through model inference).
- **`Trainer` owns metadata; collaborators do not persist their own state files** (except their natural outputs: `graber_data.pkl`, `df_with_indicators.pkl`, thread results, NN models).
- **Parallel workers are stateless beyond the timestamp range they process** — no shared mutable state between processes.

---

## 10. Potential Future Improvements

1. **Checkpointing for `DataPreparer.prepare()`** — Persist per-batch indicator slices as they complete so an interrupted run can resume mid-pipeline.
2. **`TrainerConfig` dataclass** — Replace ad-hoc env reads in `Trainer` with a validated config object passed to collaborators at construction.
3. **Distributed `SimulationOrchestrator`** — Swap `multiprocessing` for Ray/Dask to span machines.
4. **Streaming `NNOrchestrator.train()`** — Incremental model updates rather than full-dataset retraining.
5. **Schema versioning on `df_with_indicators.pkl`** — Migration hooks when the indicator set changes.
6. **Move `LiveDataCollector` into the robot module** — It is unrelated to training; the only reason it currently lives here is historical.
