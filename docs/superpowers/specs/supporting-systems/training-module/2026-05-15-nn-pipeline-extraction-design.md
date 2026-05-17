# NN Pipeline Extraction Design

**Version:** 1.0  
**Date:** 2026-05-15  
**Module:** Training  
**Purpose:** Decompose the NN pipeline (forward-looking targets, grouping, training, simulation) into a fully independent orchestrator (`NNTrainer`) separate from the main training flow (`Trainer`).

---

## 1. Overview

Currently (Training Module v2.0), the `DataPreparer` class computes NN forward-looking targets as step 5 during `generate_ohlc`. This couples the NN pipeline to the main indicator-preparation flow. This design extracts all NN-related work into a separate `NNTrainer` orchestrator:

- **Main flow** (`Trainer`): `grab_data` → `generate_ohlc` (indicators only) → `simulate`
- **NN flow** (`NNTrainer`): `nn_targets` → `nn_group` → `nn_train` → `nn_simulate`

Both orchestrators inherit from a shared `BaseOrchestrator` to avoid duplicating config/metadata management.

**Key benefit:** Decouple NN workflows from main training. Users can:
- Generate indicators once, then iterate on NN targets separately
- Skip NN pipelines entirely if not using neural networks
- Parallelize NN training independently of main backtesting

---

## 2. Architecture

### 2.1 BaseOrchestrator

Minimal shared base class owning configuration and metadata:

```python
class BaseOrchestrator:
    """
    Shared config/metadata management for Trainer and NNTrainer.
    Reads environment variables and persists metadata.pkl.
    """
    
    metadata = {"begin_point": 0, "end_point": 0, "time_step": 0}
    
    def __init__(self, pair: str):
        self.pair = pair
        self.load_metadata()
    
    def load_metadata(self):
        # Load {data_folder}/{pair}/metadata.pkl
        
    def save_metadata(self):
        # Save {data_folder}/{pair}/metadata.pkl
    
    # Configuration accessors (read from env)
    def train_begin_time(self) -> int:  # Unix seconds
    def train_end_time(self) -> int:    # Unix seconds
    def train_time_step(self) -> int:   # Minutes
    def available_threads(self) -> int:
    def data_folder(self) -> str:
    def pair_data_folder(self) -> str:
```

**Responsibilities:**
- Load/save `metadata.pkl` (begin_point, end_point, time_step)
- Expose environment variables (`DATA_START`, `DATA_END`, `TRAINER_TIME_STEP`, `AVAIABLE_THREADS`)
- Provide file path helpers (data folder, pickle paths)

**No orchestration logic.** Both `Trainer` and `NNTrainer` inherit this; each implements their own pipelines.

---

### 2.2 Trainer (Updated)

Handles offline main training pipeline:

```python
class Trainer(BaseOrchestrator):
    """
    Main training orchestrator.
    Responsible for: grab_data, generate_ohlc, simulate
    Does NOT compute NN targets (delegated to NNTrainer).
    """
    
    def run(self, run_type: str):
        if run_type == "grab_data":
            self.grab_data()
        elif run_type == "generate_ohlc":
            self.generate_ohlc()
        elif run_type == "simulate":
            self.simulate()
        else:
            raise ValueError(f"Unknown RUN_TYPE: {run_type}")
    
    def grab_data(self):
        # Graber(pair).grab_from_env() → graber_data.pkl
        
    def generate_ohlc(self):
        # DataPreparer(pair, self).prepare()
        # Stops after step 4 (indicators). No NN targets, no DataAttributes.
        # Output: df_with_indicators.pkl
        
    def simulate(self):
        # SimulationOrchestrator(pair).run()
        # Reads df_with_indicators.pkl (or df_with_nn_targets.pkl if NN targets added)
```

**Key change:** `DataPreparer.prepare()` stops after step 4. Steps 5–6 (NN targets, DataAttributes) are removed.

---

### 2.3 NNTrainer (New)

Independent NN pipeline orchestrator:

```python
class NNTrainer(BaseOrchestrator):
    """
    Neural network pipeline orchestrator.
    Responsible for: nn_targets, nn_group, nn_train, nn_simulate
    All NN-related workflows.
    """
    
    def run(self, run_type: str):
        if run_type == "nn_targets":
            self.compute_targets()
        elif run_type == "nn_group":
            self.group()
        elif run_type == "nn_train":
            self.train()
        elif run_type == "nn_simulate":
            self.simulate()
        else:
            raise ValueError(f"Unknown NN RUN_TYPE: {run_type}")
    
    def compute_targets(self):
        # Read df_with_indicators.pkl
        # Compute NN forward-looking targets (step 5 from old DataPreparer)
        # Compute DataAttributes (step 6)
        # Write df_with_nn_targets.pkl
        
    def group(self):
        # NNOrchestrator.group(class_type)
        # Reads df_with_nn_targets.pkl
        # Outputs: nn_group_*.pkl
        
    def train(self):
        # NNOrchestrator.train()
        # Reads nn_group_*.pkl
        # Trains NN models
        
    def simulate(self):
        # NNOrchestrator.simulate()
        # Reads df_with_nn_targets.pkl + trained models
        # Outputs: nn_simulation_*.pkl
```

**Owns:** All NN-related methods (target computation, grouping, training, simulation).  
**Reads:** `df_with_indicators.pkl` (main flow output)  
**Writes:** `df_with_nn_targets.pkl`, NN models, `nn_simulation_*.pkl`

---

## 3. Data Flow

### 3.1 Main Training Pipeline (Trainer)

```
┌─────────────────────────────────────┐
│ RUN_TYPE=grab_data                  │
│ Graber(pair).grab_from_env()        │
└────────────┬────────────────────────┘
             ▼
┌─────────────────────────────────────┐
│ graber_data.pkl                     │
│ (raw 1-min OHLCV from Binance)      │
└─────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ RUN_TYPE=generate_ohlc         │
│ DataPreparer(pair).prepare()        │
│ • Load raw data                     │
│ • Build base DataFrame              │
│ • Compute indicators (parallel)     │
│ • STOP (no NN targets, no stats)    │
└────────────┬────────────────────────┘
             ▼
┌─────────────────────────────────────┐
│ df_with_indicators.pkl              │
│ (wide, 1-min indexed, ~200 cols)    │
│ NO NN target columns                │
│ NO DataAttributes stats             │
└─────────────────────────────────────┘
             │
             ├─→ (direct to simulate if no NN)
             │
             └─→ (pass to NNTrainer if NN needed)
             
┌─────────────────────────────────────┐
│ RUN_TYPE=simulate                   │
│ SimulationOrchestrator.run()        │
│ Reads: df_with_indicators.pkl       │
│        (or df_with_nn_targets.pkl)  │
└────────────┬────────────────────────┘
             ▼
┌─────────────────────────────────────┐
│ simulation_results.pkl              │
│ (backtest results)                  │
└─────────────────────────────────────┘
```

---

### 3.2 NN Pipeline (NNTrainer)

```
df_with_indicators.pkl
             │
             ▼
┌─────────────────────────────────────┐
│ RUN_TYPE=nn_targets                 │
│ NNTrainer.compute_targets()         │
│ • Read df_with_indicators.pkl       │
│ • Compute NN forward-looking targets│
│   (look N steps ahead)              │
│ • Compute DataAttributes stats      │
│ • Write df_with_nn_targets.pkl      │
└────────────┬────────────────────────┘
             ▼
┌─────────────────────────────────────┐
│ df_with_nn_targets.pkl              │
│ (df_with_indicators + NN cols)      │
│ (includes tgt_long, tgt_short, etc.)│
└─────────────────────────────────────┘
             │
             ├─→ (to nn_group)
             │
             └─→ (to simulate, if using NN backtest)
             
┌─────────────────────────────────────┐
│ RUN_TYPE=nn_group                   │
│ NNTrainer.group(class_type)         │
└────────────┬────────────────────────┘
             ▼
┌─────────────────────────────────────┐
│ nn_group_*.pkl                      │
│ (training data buckets by class)    │
└─────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ RUN_TYPE=nn_train                   │
│ NNTrainer.train()                   │
└────────────┬────────────────────────┘
             ▼
┌─────────────────────────────────────┐
│ NN models (pickle files)            │
│ (trained weights per class/tf/type) │
└─────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ RUN_TYPE=nn_simulate                │
│ NNTrainer.simulate()                │
│ Reads: df_with_nn_targets.pkl +     │
│        trained models               │
└────────────┬────────────────────────┘
             ▼
┌─────────────────────────────────────┐
│ nn_simulation_*.pkl                 │
│ (NN backtest results)               │
└─────────────────────────────────────┘
```

---

## 4. RUN_TYPE Mapping

| RUN_TYPE | Class | Method | Input | Output |
|----------|-------|--------|-------|--------|
| `grab_data` | Trainer | `grab_data()` | Binance API | `graber_data.pkl` |
| `generate_ohlc` | Trainer | `generate_ohlc()` | `graber_data.pkl` | `df_with_indicators.pkl` |
| `simulate` | Trainer | `simulate()` | `df_with_indicators.pkl` (or `df_with_nn_targets.pkl`) | `simulation_results.pkl` |
| `nn_targets` | NNTrainer | `compute_targets()` | `df_with_indicators.pkl` | `df_with_nn_targets.pkl` |
| `nn_group` | NNTrainer | `group()` | `df_with_nn_targets.pkl` | `nn_group_*.pkl` |
| `nn_train` | NNTrainer | `train()` | `nn_group_*.pkl` | NN models |
| `nn_simulate` | NNTrainer | `simulate()` | `df_with_nn_targets.pkl` + models | `nn_simulation_*.pkl` |

---

## 5. Entry Point / Dispatcher

A thin dispatcher (in `trainer.py` or main entry point) routes RUN_TYPE to the correct orchestrator:

```python
def dispatch(pair: str, run_type: str):
    """
    Route RUN_TYPE to correct orchestrator.
    """
    if run_type.startswith("nn_"):
        nn_trainer = NNTrainer(pair)
        nn_trainer.run(run_type)
    else:
        trainer = Trainer(pair)
        trainer.run(run_type)
```

**Usage:**
```bash
export PAIR=link_usdt RUN_TYPE=generate_ohlc
python trainer.py  # Trainer.generate_ohlc()

export PAIR=link_usdt RUN_TYPE=nn_targets
python trainer.py  # NNTrainer.compute_targets()

export PAIR=link_usdt RUN_TYPE=nn_train
python trainer.py  # NNTrainer.train()
```

---

## 6. Workflow Examples

### 6.1 Main Training Only (No NN)

```bash
export PAIR=link_usdt DATA_START=... DATA_END=... AVAIABLE_THREADS=8

# Step 1: Download Binance data
RUN_TYPE=grab_data python trainer.py

# Step 2: Build indicators
RUN_TYPE=generate_ohlc python trainer.py

# Step 3: Backtest
RUN_TYPE=simulate python trainer.py
```

Output: `simulation_results.pkl` (no NN).

---

### 6.2 Full Pipeline with NN

```bash
export PAIR=link_usdt DATA_START=... DATA_END=... AVAIABLE_THREADS=8

# Main flow
RUN_TYPE=grab_data python trainer.py
RUN_TYPE=generate_ohlc python trainer.py

# NN flow
RUN_TYPE=nn_targets python trainer.py
RUN_TYPE=nn_group python trainer.py
RUN_TYPE=nn_train python trainer.py
RUN_TYPE=nn_simulate python trainer.py
```

Output: `df_with_nn_targets.pkl`, trained models, `nn_simulation_*.pkl`.

---

### 6.3 Iterate on NN Targets (After Indicators Fixed)

```bash
# Once df_with_indicators.pkl is stable:

# Change indicators_config.yaml? Recompute indicators.
RUN_TYPE=generate_ohlc python trainer.py

# Iterate on NN target logic without re-deriving indicators:
RUN_TYPE=nn_targets python trainer.py  # Fast recompute
RUN_TYPE=nn_group python trainer.py    # Regrouped data
RUN_TYPE=nn_train python trainer.py    # Retrain
RUN_TYPE=nn_simulate python trainer.py
```

---

## 7. Constraints and Invariants

1. **Separate files preserve main flow independence:**
   - `df_with_indicators.pkl` is the definitive output of the main flow (Trainer)
   - NN pipeline reads this and creates `df_with_nn_targets.pkl` (not modifying the original)
   - Allows recomputing NN targets without affecting the base indicators

2. **Metadata is shared:**
   - Both Trainer and NNTrainer read/write the same `metadata.pkl`
   - Ensures `begin_point`, `end_point`, `time_step` are consistent across pipelines

3. **NN targets are computed once per pair/timeframe:**
   - `nn_targets` RUN_TYPE is a one-time pass; outputs `df_with_nn_targets.pkl`
   - Subsequent `nn_group` and `nn_train` read from this file

4. **Trainer does not touch NN models or NN-specific columns:**
   - `Trainer.simulate()` can read either `df_with_indicators.pkl` or `df_with_nn_targets.pkl`
   - If NN columns are present, they are ignored by the strategy (backward compatible)

5. **No circular dependencies:**
   - Trainer → writes `df_with_indicators.pkl` → NNTrainer reads it
   - NNTrainer writes `df_with_nn_targets.pkl` (does not feed back to Trainer)

---

## 8. Future Considerations

1. **Checkpointing:** `nn_targets` could checkpoint per batch to resume interrupted runs
2. **Schema versioning:** When NN target definitions change, a migration hook updates `df_with_nn_targets.pkl`
3. **Distributed NN training:** `nn_train` could be swapped to Ray/Dask for multi-machine training
4. **Streaming NN updates:** Incremental model retraining as new data arrives (requires stateful NNTrainer)

---

## 9. Migration from v2.0

Currently, `DataPreparer.prepare()` includes:
1. Load raw data
2. Build base DataFrame
3. Compute indicators (parallel)
4. **[MOVE TO NNTrainer]** Compute NN forward-looking targets
5. **[MOVE TO NNTrainer]** Compute DataAttributes

After this design:
- `DataPreparer.prepare()` stops after step 3
- A new `NNTargetComputer` class (used by `NNTrainer.compute_targets()`) handles steps 4–5

---
