# Design: Split DataPointGenerator & SimulationOrchestrator from Trainer

**Date:** 2026-05-12  
**Status:** Design approved  
**Goal:** Improve testability by extracting `generate_data_points` and `simulate` into focused, independently-importable classes. Dissolve the `Trainer` class.

---

## 1. Motivation

The `Trainer` class in `trainer.py` (1,415 lines) owns two distinct responsibilities alongside many others:

- `generate_data_points()` — snapshots OHLC+signals at each time step
- `simulate()` — splits time range, spawns `TrainRobot` processes, aggregates results

These responsibilities are hard to test independently because they are tangled with Trainer's global state and environment-variable reads. Extracting them into separate classes enables unit testing without constructing Trainer or relying on Docker environment variables.

Additionally, `fee` is currently hardcoded as `0.002` in `TrainRobot.__init__`, violating the position-module contract (position-class.md: "fee injected from constructor; never hardcoded").

---

## 2. Decisions & Trade-offs

### 2.1 File structure
**Decision: Two new files.**
- `data_point_generator.py` and `simulation_orchestrator.py`
- Alternatives considered: both classes in one file (trainer.py stays large, tests still import everything together), or a `trainer/` package (cleaner long-term but adds filesystem restructuring and import path changes). Two new files gives maximum test isolation with minimal disruption.

### 2.2 Parallel orchestration logic
**Decision: Each class owns its own time-splitting and process-spawning logic.**
- Not extracted into a shared base class or utility.
- Alternatives considered: shared `ParallelOrchestrator` base class (abstraction without a third consumer, premature). The two loops are similar but not identical in aggregation behavior.

### 2.3 Remaining Trainer methods
**Decision: Promote to module-level functions in `trainer.py`; Trainer class body removed.**
- `generate_full_ohlc`, `train`, `group_nn`, `train_nn`, `simulate_nn`, `collect_live_data`, and metadata helpers become top-level functions.
- Alternative: Keep a slimmed Trainer coordinator class. Rejected — these methods share no meaningful state; free functions are simpler and honest about the lack of shared lifecycle.
- Note: Deeper refactoring of these remaining functions (e.g., dedicated `NNTrainer` class) is out of scope for this spec.

### 2.4 Fee configuration source
**Decision: Read from `configs/position_config.yaml` (new `fee` key).**
- position-class.md designates `configs/position_config.yaml` as the single source of truth for Position-related constants. Fee is consumed by Position, so it belongs there.
- Alternative: Environment variable `BACKTEST_FEE`. Rejected — fee is not a per-run tunable (unlike DATA_START, AVAIABLE_THREADS); it belongs in the structured config file alongside other Position constants.

### 2.5 Return type of SimulationOrchestrator.run()
**Decision: Return raw `dict`, not `SimulationResult`.**
- `SimulationResult` class is specced but not yet implemented. Introducing it here would exceed scope and create a dependency on unimplemented code.
- Upgrade to `SimulationResult` is the natural next step once that class is built.

---

## 3. Architecture

### Files Changed

| File | Change |
|------|--------|
| `data_point_generator.py` | **New.** `DataPointGenerator` class + `parallel_generate_data_points` function (moved from `trainer.py`) |
| `simulation_orchestrator.py` | **New.** `SimulationOrchestrator` class + `parallel_simulate` function (moved from `trainer.py`, gains `fee` param) |
| `trainer.py` | `Trainer` class removed. Remaining methods become module-level functions. `main()` instantiates new classes directly. |
| `train_robot.py` | `TrainRobot.__init__` gains `fee` parameter (injected, no hardcode). `Position` constructed with new signature per position-class.md. |
| `configs/position_config.yaml` | Add `fee: 0.001` key. |

### Unchanged
- `train_robot.py` buy/sell/wait/do logic — behavior untouched
- Docker, robot.py, all consumers of trainer.py other than main()

---

## 4. Class Designs

### 4.1 DataPointGenerator

**File:** `data_point_generator.py`

```python
class DataPointGenerator:
    def __init__(self, available_threads: int, time_step_min: int):
        self.available_threads = available_threads  # from env AVAIABLE_THREADS
        self.time_step_min = time_step_min           # from env TRAINER_TIME_STEP

    def generate(
        self,
        full_data,
        grouped_data: pd.DataFrame,
        start_date: datetime,
        end_date: datetime,
        run_predictor: bool = False,
        save_candles: bool = True,
    ) -> None:
        """Split time range, spawn parallel_generate_data_points processes, join."""

    def _split_time_range(
        self, start: datetime, end: datetime, step_min: int, n: int
    ) -> list[datetime]:
        """Return list of n+1 boundary datetimes."""
```

**Module-level function (moved from trainer.py):**
```python
def parallel_generate_data_points(
    full_data_, grouped_data, begin_date, end_date, min_step,
    run_predictor, save_candles
):
    ...  # logic unchanged from current trainer.py
```

**Key attributes:**
- `available_threads` — controls process count
- `time_step_min` — minutes between generated data points

**Preconditions for `generate()`:**
- `full_data` loaded from disk
- `grouped_data` is the raw 1-min Binance OHLC DataFrame
- `start_date < end_date`

**Postconditions:**
- Data point directories created: `data_folder(pair)/[timestamp]/`
- Metadata updated and saved after completion

---

### 4.2 SimulationOrchestrator

**File:** `simulation_orchestrator.py`

```python
class SimulationOrchestrator:
    def __init__(self, available_threads: int, time_step_min: int, fee: float):
        self.available_threads = available_threads
        self.time_step_min = time_step_min
        self.fee = fee   # from configs/position_config.yaml — never hardcoded

    def run(self, start_date: datetime, end_date: datetime) -> dict:
        """
        Returns:
            {
                "total_revenue": float,
                "total_revenue_abs": float,
                "revenue_by_id": dict,
            }
        """

    def _split_time_range(
        self, start: datetime, end: datetime, step_min: int, n: int
    ) -> list[datetime]:
        """Return list of n+1 boundary datetimes."""

    def _clean_actions_folder(self) -> None:
        """Delete old action pkl files before simulation run."""

    def _aggregate_results(self, time_limits: list[datetime]) -> dict:
        """Load per-thread result pickles and merge revenue_by_id dicts."""
```

**Module-level function (moved from trainer.py, gains `fee` param):**
```python
def parallel_simulate(
    thread_num, begin_date, end_date, min_step, total, total_abs, fee: float
):
    robot = TrainRobot(thread_num=thread_num, fee=fee)  # fee injected
    ...  # rest of logic unchanged
```

**Key attributes:**
- `fee` — injected from `position_config.yaml`, passed through to `TrainRobot`
- `available_threads` — controls process count

**Preconditions for `run()`:**
- Data points have been generated (`generate_data_points` phase complete)
- `start_date < end_date`

**Postconditions:**
- Actions folder cleaned
- Thread result pickles written to `shared_folder(pair)/thread_result_by_id_N.pkl`
- `levels_full.pkl` written to `shared_folder(pair)/`
- Returns aggregated revenue metrics

---

### 4.3 TrainRobot Constructor (train_robot.py — updated)

```python
class TrainRobot:
    def __init__(self, thread_num: int = 0, fee: float = 0.001):
        self.data = data.Data(default_pair)
        self.thread_num = thread_num
        # fee is always injected — the default 0.001 is a fallback for
        # direct test instantiation only; SimulationOrchestrator always
        # provides the config value explicitly
        self.strategy_mngr = StrategyManager(self.data, fee, False)
        self.position = Position(
            thread_num=thread_num,
            fee=fee,
            coin_use=self.data.coin_base,  # e.g. "usdt"
            coin_get=self.data.coin,        # e.g. "link"
        )
        # No LiveOrderTracker — simulation path owns Position only
```

**Changes from current:**
- `fee = 0.002` hardcode removed
- `fee` parameter added to constructor
- `Position(thread_num, stock.item.fee, self.data)` → `Position(thread_num, fee, coin_use, coin_get)` per position-class.md spec
- No `LiveOrderTracker` (simulation path does not need crash recovery or Binance order IDs)

---

### 4.4 configs/position_config.yaml (new key)

```yaml
fee: 0.001                        # Taker fee per fill (0.1%)
buy_start_time_limit_sec: 60
sell_start_time_limit_sec: 180
stop_loss_percent: 0.006
stop_loss_safety_interval_min: 1
```

If `configs/position_config.yaml` does not yet exist, it is created as part of this work.

---

### 4.5 Updated trainer.py main()

```python
import yaml
from data_point_generator import DataPointGenerator
from simulation_orchestrator import SimulationOrchestrator

def _load_position_config() -> dict:
    with open("configs/position_config.yaml") as f:
        return yaml.safe_load(f)

def main():
    run_type = os.environ.get("RUN_TYPE", "")
    config = _load_position_config()
    available_threads = int(os.environ["AVAIABLE_THREADS"])
    time_step = int(os.environ["TRAINER_TIME_STEP"])

    load_metadata()  # module-level function; metadata stored in module-level dict

    if run_type == "generate_data_points":
        start, end = data_graber_date_limits()
        gen = DataPointGenerator(available_threads, time_step)
        gen.generate(full_data, grouped_data, start, end,
                     run_predictor=False, save_candles=True)
        save_metadata()  # module-level function

    elif run_type == "simulate":
        start, end = data_graber_date_limits()
        orch = SimulationOrchestrator(available_threads, time_step,
                                      fee=config["fee"])
        orch.run(start, end)

    elif run_type == "generate_full_ohlc":
        generate_full_ohlc("binance")

    # ... other run_types call module-level functions directly
```

`TrainerMeta` is a minimal struct (or plain dataclass) holding `metadata` dict + `save_metadata()`/`load_metadata()` — extracted from the dissolved Trainer class.

---

## 5. Data Flow

```
main()
  ├─ generate_data_points run_type
  │    └─ DataPointGenerator.generate(full_data, grouped_data, start, end)
  │         ├─ _split_time_range() → N time segments
  │         └─ mp.Process(parallel_generate_data_points, segment) × N
  │              └─ Writes data_folder(pair)/[timestamp]/ dirs
  │
  └─ simulate run_type
       └─ SimulationOrchestrator.run(start, end)
            ├─ _clean_actions_folder()
            ├─ _split_time_range() → N time segments
            ├─ mp.Process(parallel_simulate, segment, fee) × N
            │    └─ TrainRobot(thread_num, fee=config_fee)
            │         └─ Position(thread_num, fee, coin_use, coin_get)
            └─ _aggregate_results() → {"total_revenue": ..., ...}
```

---

## 6. Testing

Each class is instantiable without the Trainer class or Docker environment:

```python
# DataPointGenerator — unit test example
def test_split_time_range():
    gen = DataPointGenerator(available_threads=2, time_step_min=1)
    limits = gen._split_time_range(start, end, step_min=1, n=2)
    assert len(limits) == 3

# SimulationOrchestrator — unit test example
def test_sim_orch_constructs():
    orch = SimulationOrchestrator(available_threads=1, time_step_min=60, fee=0.001)
    assert orch.fee == 0.001

# TrainRobot — fee injection test
def test_train_robot_fee_injected():
    robot = TrainRobot(thread_num=0, fee=0.002)
    # Verify fee flows into StrategyManager and Position
    assert robot.strategy_mngr.fee == 0.002
```

Integration tests (spawning actual subprocesses) continue to be covered by existing Docker-based test setup.

---

## 7. Out of Scope

- `SimulationResult` class (specced separately in `simulation-result-class.md`)
- Refactoring `generate_full_ohlc`, `group_nn`, `train_nn`, `simulate_nn` (separate future specs)
- `LiveOrderTracker` extraction in `robot.py` (robot-module concern)
- Changing buy/sell/wait/do logic in `TrainRobot` (behavior unchanged)
