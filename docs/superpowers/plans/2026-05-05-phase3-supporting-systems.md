# Phase 3: Supporting Systems Module & Class Specifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write 19 specification files documenting 4 supporting system modules (Training, NN, Backtesting, Frontend) in 2 sequential batches.

**Architecture:** Batch 1 (Training & NN Systems: Trainer + NN classes) → Batch 2 (Backtesting & Frontend: Simulation + Visualization). Each spec includes "Existing Approach" + "Potential Improvements". All batches commit together at end.

**Tech Stack:** Markdown files only. No code changes. Verification against source code using grep and file inspection.

---

## File Structure

**Directory tree to create:**
```
docs/superpowers/specs/supporting-systems/
├── training-module/
│   ├── training-module.md
│   ├── trainer-class.md
│   ├── data-point-generator-class.md
│   ├── training-coordinator-class.md
│   └── result-aggregator-class.md
├── nn-module/
│   ├── nn-module.md
│   ├── nn-predictor-class.md
│   ├── nn-model-class.md
│   ├── predictor-loader-class.md
│   └── checkpoint-manager-class.md
├── backtesting-module/
│   ├── backtesting-module.md
│   ├── train-robot-class.md
│   ├── simulation-result-class.md
│   └── performance-analyzer-class.md
└── frontend-module/
    ├── frontend-module.md
    ├── data-viewer-class.md
    ├── training-dashboard-class.md
    ├── live-dashboard-class.md
    └── chart-renderer-class.md
```

**Total files:** 19 specs (2 module + class specs per module)

---

## BATCH 1: Training & NN Systems

### Task 1: Create Directory Structure

- [ ] **Step 1: Create supporting-systems directory**

```bash
mkdir -p docs/superpowers/specs/supporting-systems
```

- [ ] **Step 2: Create all 4 module subdirectories**

```bash
mkdir -p docs/superpowers/specs/supporting-systems/{training-module,nn-module,backtesting-module,frontend-module}
```

- [ ] **Step 3: Verify directory structure**

```bash
find docs/superpowers/specs/supporting-systems -type d | sort
```

Expected: All 5 directories (supporting-systems + 4 modules) created.

---

### Task 2: Write Training Module Specification

- [ ] **Step 1: Read trainer.py to understand structure**

```bash
head -50 trainer.py
grep -n "class Trainer\|def main\|def generate_full_ohlc\|def simulate\|def train" trainer.py | head -20
```

- [ ] **Step 2: Write training-module.md**

Create file with comprehensive spec documenting:
- Purpose: Orchestrate data generation, training, simulation, NN training
- Responsibilities: coordinate all training modes (generate_full_ohlc, generate_data_points, train, simulate, nn_train, etc.)
- Key classes: Trainer (main orchestrator)
- Existing approach: RUN_TYPE-based mode selection, parallel processing, multi-threaded simulation
- Potential improvements: progress tracking, checkpointing, distributed training

- [ ] **Step 3: Verify against source**

```bash
grep -c "def main\|def generate_full_ohlc\|def simulate\|RUN_TYPE" trainer.py
```

Expected: All key methods found.

---

### Tasks 3-6: Write Trainer and NN-related Class Specs

- [ ] **Task 3: Write trainer-class.md** (Trainer orchestrator class)
- [ ] **Task 4: Write nn-predictor-class.md** (NN prediction interface)
- [ ] **Task 5: Write nn-model-class.md** (NN model architecture)
- [ ] **Task 6: Write checkpoint-manager-class.md** (Model persistence)

---

### Task 7: Write NN Module Specification

- [ ] **Step 1: Read NN-related files** (predictors/*, nn_*.py)

- [ ] **Step 2: Write nn-module.md**

Create file documenting:
- Purpose: Train and integrate neural networks for signal enhancement
- Key classes: NNPredictor, NNModel, CheckpointManager, PredictorLoader
- Existing approach: pre-computed simulation mode, optional live inference
- Potential improvements: real-time training, model ensemble, probability calibration

---

### Tasks 8-10: Write Training Supporting Class Specs

- [ ] **Task 8: Write data-point-generator-class.md**
- [ ] **Task 9: Write training-coordinator-class.md**
- [ ] **Task 10: Write result-aggregator-class.md**

---

## BATCH 2: Backtesting & Frontend Visualization

### Task 11: Write Backtesting Module Specification

- [ ] **Step 1: Read train_robot.py**

```bash
grep -n "class TrainRobot\|def do\|def buy\|def sell" train_robot.py | head -15
```

- [ ] **Step 2: Write backtesting-module.md**

Create file documenting:
- Purpose: Simulate trading strategy execution on historical data
- Key classes: TrainRobot (simulation robot), SimulationResult, PerformanceAnalyzer
- Existing approach: DataIterator stepping, fill simulation at OHLC prices, multi-threaded runs
- Potential improvements: slippage modeling, order book simulation, walk-forward analysis

---

### Tasks 12-14: Write Backtesting Class Specs

- [ ] **Task 12: Write train-robot-class.md** (Simulation robot)
- [ ] **Task 13: Write simulation-result-class.md** (Result aggregation)
- [ ] **Task 14: Write performance-analyzer-class.md** (Metrics calculation)

---

### Task 15: Write Frontend Module Specification

- [ ] **Step 1: Read view_*.py files**

```bash
ls view_*.py
head -30 view_online_point.py
```

- [ ] **Step 2: Write frontend-module.md**

Create file documenting:
- Purpose: Visualize data, training progress, live trading activity
- Key components: Data Viewer, Training Dashboard, Live Dashboard, Chart Renderer
- Existing approach: matplotlib-based rendering, multi-process viewers, file-based data loading
- Potential improvements: real-time streaming, interactive dashboards, web-based interface

---

### Tasks 16-19: Write Frontend Class Specs

- [ ] **Task 16: Write data-viewer-class.md** (Historical data visualization)
- [ ] **Task 17: Write training-dashboard-class.md** (Training progress monitoring)
- [ ] **Task 18: Write live-dashboard-class.md** (Live trading dashboard)
- [ ] **Task 19: Write chart-renderer-class.md** (OHLC and indicator charting)

---

## Task 20: Final Verification & Commit All Batches

- [ ] **Step 1: Verify all 19 specs exist**

```bash
find docs/superpowers/specs/supporting-systems -name "*.md" -type f | wc -l
```

Expected: 19 files (2 module + 17 class specs).

- [ ] **Step 2: Quick content check (sample)**

```bash
grep -l "Existing Approach\|Potential Improvements" docs/superpowers/specs/supporting-systems/*/*.md | wc -l
```

Expected: All 19 files contain both sections.

- [ ] **Step 3: Verify no placeholder text**

```bash
grep -r "TBD\|TODO\|placeholder" docs/superpowers/specs/supporting-systems/ || echo "No placeholders found"
```

Expected: No matches.

- [ ] **Step 4: Commit all specs together**

```bash
git add docs/superpowers/specs/supporting-systems/
git commit -m "Add Phase 3: Supporting systems module and class specifications

Adds 19 specifications across 2 batches:
- Batch 1 (Training & NN): Training (5 specs) + NN (5 specs) = 10 specs
- Batch 2 (Backtesting & Frontend): Backtesting (4 specs) + Frontend (5 specs) = 9 specs

Each spec documents existing approach + potential improvements.
Class specs include full contracts (methods, attributes, state machines, error handling).

All 4 system layers (Phase 1: Infrastructure, Phase 2: Critical Path, Phase 3: Supporting)
are now fully specified and committed.

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Verify commit**

```bash
git log --oneline -1
```

Expected: Single commit with all 19 specs.

---

## Summary

**Deliverables:**
- 19 specification files (2 module + class specs per module)
- Organized in `docs/superpowers/specs/supporting-systems/` with 4 module subdirectories
- Each spec includes: Overview, Boundaries, Data Flow, Execution Flow, Components, Existing Approach, Potential Improvements
- All specs committed in single git commit
- Total: ~100-150KB of documentation

**Completion:**
- All 4 system layers specified (Infrastructure, Critical Path, Supporting Systems)
- Total: 45 specifications across 3 phases
- System fully documented and ready for improvement initiatives

**Next:** Implementation improvements based on documented potential improvements

