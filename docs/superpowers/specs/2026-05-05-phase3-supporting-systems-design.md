# Phase 3: Supporting Systems Module & Class Specifications Design Document

**Date:** 2026-05-05  
**Project:** pybtctr2 — Cryptocurrency Trading Bot  
**Objective:** Design Phase 3 documentation: specify 4 supporting system modules and key classes using full contract documentation, organized in 2 sequential batches.

---

## 1. Design Overview

Phase 3 documents the supporting systems that enable training, neural network enhancement, backtesting analysis, and live trading visualization. These systems sit alongside the critical path (Phase 2) and consume its outputs.

**Key Constraints:**
- Document existing code as-is; no refactoring
- Light formality: Markdown + ASCII diagrams only
- For each section: **Existing Approach** (current implementation) + **Potential Improvements** (numbered list)
- Class specs include full contracts: methods, attributes, state machines, error handling
- Sequential execution: Batch 1 → Batch 2
- Commit all specs together at the end

---

## 2. Batch Definitions

### Batch 1: Training & NN Systems — FIRST

**Modules:** Training, NN  
**Total Specs:** 10 (2 module + 8 class)  
**Dependencies:** Critical path (Phase 2)  
**Focus:** Data generation, NN training, prediction integration

**Module Specs (2 files):**
- `training-module.md` — Orchestration, data generation modes, training pipeline
- `nn-module.md` — NN architecture, training, prediction, probability integration

**Class Specs (8 files):**
- `trainer-class.md` — Main orchestrator (generate_full_ohlc, simulate, train, etc.)
- `nn-predictor-class.md` — NN prediction interface
- `nn-model-class.md` — Model architecture and forward pass
- `predictor-loader-class.md` — Pre-computed prediction loading
- `data-point-generator-class.md` — Feature vector generation
- `training-coordinator-class.md` — Batch training orchestration
- `result-aggregator-class.md` — Thread result collection
- `checkpoint-manager-class.md` — Model checkpoint persistence

---

### Batch 2: Backtesting & Visualization Systems — SECOND

**Modules:** Backtesting, Frontend Visualization  
**Total Specs:** 9 (2 module + 7 class)  
**Dependencies:** Critical path (Phase 2), Training module (Batch 1)  
**Focus:** Simulation analysis, visualization, charting

**Module Specs (2 files):**
- `backtesting-module.md` — Simulation engine, result analysis, performance metrics
- `frontend-module.md` — Data viewers, dashboards, charting tools

**Class Specs (7 files):**
- `train-robot-class.md` — Simulation robot (parallel to Robot)
- `simulation-result-class.md` — Trade result aggregation and metrics
- `performance-analyzer-class.md` — Return metrics, drawdown, sharpe calculation
- `data-viewer-class.md` — Full historical data viewer
- `training-dashboard-class.md` — Training progress visualization
- `live-dashboard-class.md` — Live trading dashboard
- `chart-renderer-class.md` — OHLC and indicator charting

---

## 3. Specification Content Structure

### Module Specification Template

Each module spec follows this structure:

1. **Overview** (3-4 paragraphs)
   - Purpose and responsibilities
   - Key classes in the module
   - How this module fits in the system

2. **Module Boundaries** (brief)
   - Upstream: what feeds into this module
   - Downstream: what consumes this module's output
   - Key interfaces exposed

3. **Data Flow** (ASCII diagram)
   - Input → Processing → Output
   - Shows movement of data through module components

4. **Execution Flow** (step-by-step)
   - How the module operates
   - Numbered sequence or process description

5. **Key Components** (list)
   - Brief description of each class in the module

6. **Existing Approach** (1-2 sections)
   - Current implementation pattern
   - Design decisions, architecture choices

7. **Potential Improvements** (numbered list)
   - 3-5 improvement ideas

---

### Class Specification Template

Each class spec includes:

1. **Class Overview** (2-3 paragraphs)
   - Purpose and responsibility
   - Key role in the module

2. **Key Attributes** (table or list)
   - Instance variable names, types, descriptions

3. **Constructor** (`__init__`)
   - Parameters and their types
   - Initialization logic

4. **Key Methods & Interfaces** (method signatures with contracts)
   - Method name and signature
   - Parameters, return value, exceptions
   - Preconditions and postconditions

5. **State Management** (if applicable)
   - Valid state transitions
   - Invariants maintained

6. **Error Handling** (if applicable)
   - Exception types raised
   - Recovery strategies

7. **Existing Approach** (1-2 sections)
   - Current implementation style
   - Notable design choices

8. **Potential Improvements** (numbered list)
   - 2-4 improvement ideas

---

## 4. File Organization

All specs organized under `docs/superpowers/specs/supporting-systems/`:

```
supporting-systems/
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

## 5. Success Criteria

✅ All 19 specs written (2 module + class specs per module)  
✅ Each module spec covers: Overview, Boundaries, Data Flow, Execution Flow, Components, Existing Approach, Potential Improvements  
✅ Each class spec covers: Overview, Attributes, Constructor, Methods, State Management, Error Handling, Existing Approach, Potential Improvements  
✅ All specs verified against source code accuracy  
✅ No time estimates in any specs  
✅ All specs committed together in single git commit  

---

## 6. Next Steps (After Phase 3)

1. Review Phase 3 specs
2. All system specifications complete (Phase 1 + Phase 2 + Phase 3)
3. Begin implementation improvements based on documented potential improvements
4. Update CLAUDE.md with spec references

---

**End of Design Document**
