# SimulationOrchestrator Class Specification

**Version:** 2.0 — New class introduced as part of Trainer decomposition
**Class:** `SimulationOrchestrator`
**File:** `simulation_orchestrator.py`
**Purpose:** Run a parallel backtest across the training period using `SimulationData` + `TrainRobot`, then aggregate per-thread results.

---

## 1. Class Overview

`SimulationOrchestrator` encapsulates the `RUN_TYPE=simulate` pipeline that previously lived inside `Trainer.simulate()` and `parallel_simulate()`. In v2.0 it depends on the Data Module v2.0 replay primitives:

- **`SimulationData`** replaces `DataIterator`. Each worker constructs its own instance for its time segment.
- **`WideDataPoint`** replaces the v1 monolithic `Data` object passed to the robot.
- **`DataPoint` protocol** isolates strategies and signals from the simulation/live path distinction.

The class is responsible for:
1. Dividing `[DATA_START, DATA_END]` into `AVAIABLE_THREADS` equal time segments.
2. Spawning one worker process per segment.
3. Each worker: walk `SimulationData`, call strategy + robot at every step, persist per-thread results.
4. Main thread: join workers, merge `thread_result_by_id_N.pkl` files, persist aggregated outputs.

No simulation business logic lives here — that belongs to `TrainRobot` and strategy classes. `SimulationOrchestrator` is pure parallel-execution scaffolding plus result aggregation.

---

## 2. Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `pair` | `str` | Trading pair. |
| `trainer` | `Trainer` | Injected reference for env/config access. |
| `shared_folder` | `str` | Output folder for thread results and aggregates. |
| `_total_revenue` | `mp.Value("d", 0.0)` | Shared running total (relative). |
| `_total_revenue_abs` | `mp.Value("d", 0.0)` | Shared running total (absolute). |

---

## 3. Constructor

### `__init__(pair: str, trainer: Trainer)`

**Behavior:**
1. Store `pair`, `trainer`.
2. Compute `shared_folder = shared_folder(pair)`.
3. Initialize shared `mp.Value` counters.

---

## 4. Methods

### 4.1 `run() -> SimulationResults`

**Purpose:** Execute the full parallel backtest pipeline.

**Behavior:**
1. **Cleanup.** Delete any pre-existing `thread_result_by_id_*.pkl` files in `shared_folder` to avoid mixing runs.
2. **Segment division.**
   ```python
   begin_ts = trainer.train_begin_time()
   end_ts   = trainer.train_end_time()
   step_min = trainer.train_time_step()
   nthreads = trainer.available_threads()
   segments = self._split_range(begin_ts, end_ts, nthreads)
   ```
3. **Spawn workers.**
   ```python
   procs = []
   for i, (b, e) in enumerate(segments):
       p = mp.Process(
           target=_simulate_range,
           args=(self.pair, i, b, e, step_min,
                 self._total_revenue, self._total_revenue_abs)
       )
       p.start()
       procs.append(p)
   for p in procs:
       p.join()
   ```
4. **Aggregate.**
   - Load each `thread_result_by_id_N.pkl` and merge revenue-by-strategy-id dicts:
     ```python
     for key in thread_result:
         agg[key] = agg.get(key, 0) + thread_result[key]
     ```
   - Load and merge `levels_partial_N.pkl` files into `levels_full.pkl`.
   - Save `simulation_results.pkl` with: `{total_rel, total_abs, by_strategy_id, threads, segments}`.
5. **Log final totals.**
6. **Return** a `SimulationResults` value object (typed dataclass).

**Return:** `SimulationResults` with:
- `total_revenue: float` (relative, sum across threads)
- `total_revenue_abs: float` (absolute)
- `by_strategy_id: dict[str, float]`
- `thread_count: int`
- `segments: list[tuple[int, int]]`

**Preconditions:**
- `df_with_indicators.pkl` exists (raise `FileNotFoundError` with hint to run `generate_full_ohlc` if absent).
- `TrainRobot` and strategy classes are importable.
- `shared_folder(pair)` exists or is creatable.

**Postconditions:**
- `shared_folder/simulation_results.pkl` written.
- `shared_folder/levels_full.pkl` written.
- Per-thread intermediate files retained for debugging.

---

### 4.2 `_simulate_range(pair, thread_id, begin_ts, end_ts, step_min, total_rel, total_abs) -> None`

**Purpose:** Worker process body. Module-level function (not a method) so it pickles cleanly for `multiprocessing`.

**Behavior:**
```python
def _simulate_range(pair, thread_id, begin_ts, end_ts, step_min,
                    total_rel, total_abs):
    sim   = SimulationData(pair, begin_ts, end_ts, step_min)
    robot = TrainRobot(pair, thread_id)

    progress = tqdm(total=sim.steps, position=thread_id)
    while not sim.is_end():
        point = sim.get()
        signal = signal_manager.check(point)
        action = strategy.select_action(point)
        robot.step(point, action)
        sim.next()
        progress.update(1)

    results = robot.get_results()
    with total_rel.get_lock():
        total_rel.value += results.revenue_rel
    with total_abs.get_lock():
        total_abs.value += results.revenue_abs

    save_thread_results(pair, thread_id, results)
    save_thread_levels(pair, thread_id, robot.levels_collected)
```

**Exception handling:** Per-step exceptions inside the strategy or robot are caught, logged with `(thread_id, timestamp, error)`, and the loop continues to the next step (preserving the v1 behavior where partial simulation results are useful).

---

### 4.3 `_split_range(begin_ts, end_ts, nthreads) -> list[tuple[int, int]]`

**Purpose:** Compute `nthreads` contiguous, non-overlapping segments.

**Behavior:**
```python
delta = (end_ts - begin_ts) // nthreads
return [(begin_ts + i*delta,
         begin_ts + (i+1)*delta if i < nthreads-1 else end_ts)
        for i in range(nthreads)]
```

Last segment absorbs any modulo remainder so the full range is covered.

---

## 5. Output Files

| File | Format | Contents |
|------|--------|----------|
| `shared/thread_result_by_id_{N}.pkl` | dict pkl | `{strategy_id: revenue}` for thread N |
| `shared/levels_partial_{N}.pkl` | dict pkl | Levels observed by thread N |
| `shared/levels_full.pkl` | dict pkl | Merged levels across all threads |
| `shared/simulation_results.pkl` | dataclass pkl | Aggregated `SimulationResults` |

---

## 6. Parallelization Notes

- **Sharded by time range** (not by timeframe — that's `DataPreparer`'s axis).
- **Stateless across processes.** Each worker loads its own copy of `df_with_indicators.pkl` via `SimulationData(...)`. Memory cost: ~`nthreads × df_size`. For a 1–2 GB DataFrame with 8 threads, that is 8–16 GB peak — acceptable on the typical training host.
- **Optimization opportunity:** `df_with_indicators.pkl` could be memory-mapped or held in `mp.shared_memory` to halve RAM use; not in scope for v2.0.
- **Determinism:** Strategies and the robot are expected to be deterministic given the same `WideDataPoint` inputs. Thread-id only influences output filenames.

---

## 7. Error Handling

| Condition | Behavior |
|-----------|----------|
| `df_with_indicators.pkl` missing | `FileNotFoundError` raised at worker init; the worker exits; main thread surfaces an aggregated error after join. |
| Worker process dies (non-zero exit code) | Main thread raises `RuntimeError(f"thread {N} failed")` after join; partial results are NOT aggregated. |
| Per-step exception inside loop | Caught, logged, loop continues. |
| Missing `shared_folder` | Created with `os.makedirs(..., exist_ok=True)`. |

---

## 8. Testing Notes

- **Unit:** test `_split_range` with edge cases (nthreads=1, large remainder, single-second range).
- **Integration:** small fixture `df_with_indicators.pkl` covering a few hours, `nthreads=2`, deterministic strategy that always returns `WAIT` → assert zero revenue, no exceptions, both thread files written.
- **Aggregation:** create two fake `thread_result_by_id_*.pkl` files with overlapping strategy IDs → assert the merged dict sums correctly.

---

## 9. Constraints and Invariants

- **No data computation.** All indicator values come from the pre-built wide DataFrame.
- **No mutation of `df_with_indicators.pkl`.** Workers read-only.
- **Thread-local outputs.** Each worker writes only files named with its thread id; the main thread is the only writer of aggregated outputs.
- **Reproducibility.** Re-running `run()` with the same inputs produces identical aggregated results (assuming deterministic strategy).
- **`SimulationData` is constructed per-worker** — never shared across processes (it is not thread-safe per Data Module v2.0 §12).
