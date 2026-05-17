# PyBTCTR2 Specification Design Document

**Date:** 2026-05-04  
**Project:** pybtctr2 — Cryptocurrency Trading Bot and Backtesting Framework  
**Objective:** Create a machine-readable, hierarchical specification of existing features across application, module, class, and infrastructure layers using light formality (Markdown + ASCII diagrams).

---

## 1. Project Overview

PyBTCTR2 is a complex cryptocurrency trading system with multiple interconnected subsystems: data collection, signal generation, strategy coordination, live trading execution, backtesting, neural network training, and visualization. The goal of this specification project is to:

1. **Document existing features** as they currently exist (no refactoring)
2. **Make the system machine-readable** for better agent understanding and automation
3. **Establish clear interfaces and responsibilities** at each layer
4. **Trace data and execution flows** end-to-end through the critical path

This design document describes the approach for creating these specifications.

---

## 2. Design Goals

- **Clarity**: Specifications can be understood independently of code
- **Completeness**: All major components and their interactions documented
- **Machine Readability**: Clear structure enables parsing by tools and agents
- **Maintainability**: Specs remain current as code evolves
- **Scalability**: Pattern established for expanding to new systems
- **Simplicity**: Light formality keeps specs concise and readable (no formal notation)

---

## 3. Approach: Layered Parallel Specification

### 3.1 Core Strategy

Use **Approach 3: Layered Parallel with Critical Path Focus**:

1. **Phase 1**: Define layer boundaries and responsibilities first, then create a main system architecture specification that shows how layers interact.
2. **Phase 2**: Develop specifications for the critical trading path in parallel (modules and classes), using layers as guides.
3. **Phase 3**: Expand to supporting systems (training, NN, backtesting, visualization) using the established pattern.

**Rationale**: Balances high-level clarity (layers) with pragmatic depth (critical path first). Layers guide module design and prevent scope creep. Pattern established in Phase 1-2 can be replicated for Phase 3.

### 3.2 Specification Approach: Documentation-First, Light Formality

- **Scope**: Document existing code as-is; do not refactor during documentation phase
- **Formality**: Light — Markdown descriptions with simple ASCII/text diagrams embedded (no formal notation, no external diagram tools)
- **Content Focus**: Data flows, execution flows, behavior, responsibilities, and interfaces
- **Layer Dependency**: Application layer specs are high-level; module and class specs include more detail

---

## 4. Specification Structure

### 4.1 File Hierarchy

All specifications organized in `docs/superpowers/specs/`:

```
docs/superpowers/specs/
├── 2026-05-04-pybtctr2-specification-design.md  [This document]
├── 2026-05-05-pybtctr2-architecture.md          [Main system spec]
├── 2026-05-05-phase2-module-specifications-design.md
├── 2026-05-05-phase3-supporting-systems-design.md
├── layers/
│   ├── 01-infrastructure-layer.md
│   ├── 01-infrastructure-layer-setup.md
│   ├── 02-data-layer.md
│   ├── 03-business-logic-layer.md
│   ├── 04-execution-layer.md
│   └── 04-execution-layer-impl.md
├── critical-path/
│   ├── stock-abstraction-module/
│   │   ├── stock-abstraction-module.md
│   │   ├── base-stock-interface-class.md
│   │   ├── binance-stock-class.md
│   │   └── stock-item-class.md
│   ├── data-module/
│   │   ├── data-module.md
│   │   ├── data-class.md
│   │   ├── dataiterator-class.md     (SimulationData spec)
│   │   ├── indicators-class.md
│   │   └── levels-class.md
│   ├── signals-module/
│   │   ├── signals-module.md
│   │   ├── base-signal-class.md
│   │   ├── signal-chain-class.md
│   │   ├── signal-manager-class.md
│   │   └── signals/
│   │       ├── candle-signals.md
│   │       ├── common-signals.md
│   │       ├── complex-signals.md
│   │       ├── nn-signals.md
│   │       ├── operations-signals.md
│   │       └── position-signals.md
│   ├── strategy-module/
│   │   ├── strategy-module.md
│   │   ├── strategy-class.md
│   │   ├── strategy-manager-class.md
│   │   ├── example-strategy-long-class.md
│   │   └── example-strategy-short-class.md
│   ├── robot-module/
│   │   ├── robot-module.md
│   │   └── robot-class.md
│   └── position-module/
│       ├── position-module.md
│       ├── position-class.md
│       ├── base-position-class.md
│       ├── long-position-class.md
│       ├── short-position-class.md
│       ├── coin-class.md
│       └── 2026-05-10-position-cross-layer-alignment-design.md
└── supporting-systems/
    ├── training-module/
    │   ├── training-module.md
    │   ├── trainer-class.md
    │   ├── datapreparer-class.md
    │   ├── graber-class.md
    │   ├── livedatacollector-class.md
    │   ├── nn-orchestrator-class.md
    │   └── simulation-orchestrator-class.md
    ├── nn-module/
    │   ├── nn-module.md
    │   ├── nnmodel-class.md
    │   ├── nnpredictor-class.md
    │   ├── checkpoint-manager-class.md
    │   ├── datapoint-generator-class.md
    │   ├── result-aggregator-class.md
    │   └── training-coordinator-class.md
    ├── backtesting-module/
    │   ├── backtesting-module.md
    │   ├── trainrobot-class.md
    │   ├── performance-analyzer-class.md
    │   └── simulation-result-class.md
    └── frontend-module/
        ├── frontend-module.md
        ├── chartrenderer-class.md
        ├── dataviewer-class.md
        ├── live-dashboard-class.md
        └── training-dashboard-class.md
```

### 4.2 Content Structure by Spec Type

#### **Layer Specification Template** (4-6 pages)

Example: `02-data-layer.md`

**Sections:**
1. **Overview** — Purpose, responsibilities, key modules in this layer
2. **Layer Boundaries** — What feeds into this layer (upstream), what consumes its output (downstream), key interfaces
3. **Data Flow** — How data moves through this layer (ASCII diagram showing input → processing → output)
4. **Execution Flow** — How the layer operates step-by-step (numbered sequence or flow diagram)
5. **Key Classes** — Name, purpose, and role of major classes in this layer
6. **Assumptions & Constraints** — Preconditions, rate limits, format assumptions

**Purpose**: Provide a 30,000-foot view of the layer's role in the system and how it interacts with other layers.

---

#### **Module Specification Template** (6-8 pages)

Example: `signals-module/signals-module.md`

**Sections:**
1. **Module Overview** — Purpose, responsibility, input, output; what it does
2. **Module Components** — List of classes in this module and their roles
3. **Data Flow** — How data flows through module (ASCII diagram showing input sources → class operations → output)
4. **Execution Flow** — How the module executes (step-by-step process or diagram)
5. **Key Interfaces** — Method signatures, contracts, and usage expectations
6. **Assumptions** — Preconditions, data format assumptions, performance expectations

**Purpose**: Detailed design of a module's architecture, responsibilities, and how it transforms input to output.

---

#### **Class Specification Template** (3-5 pages)

Example: `position-module/position-class.md`

**Sections:**
1. **Class Overview** — Purpose, responsibility, who uses it
2. **Key Attributes** — Major instance variables with types and descriptions
3. **Data Flow** — Lifecycle of data through the class (creation → updates → closure, as ASCII diagram)
4. **Key Methods & Interfaces** — Method signatures, parameters, return values, contracts
5. **Execution Flow** — How the class executes over its lifecycle (step-by-step)
6. **Assumptions** — Preconditions, invariants, failure modes

**Purpose**: Class contract and usage guide; how instances are created, modified, and used in the system.

---

### 4.3 Content Guidelines

**Light Formality Means:**
- Markdown text descriptions (clear, concise English)
- ASCII/text diagrams embedded in Markdown (no external tool dependencies)
- Simple flow notation: `Input → Process → Output` or step-by-step lists
- No formal pseudo-code, mathematical notation, or state machines (unless essential for clarity)

**Data Flow Diagrams** (ASCII example):
```
Binance API
   ↓ [Stock.fetch_candles()]
Raw Candles
   ↓ [Data.generate_ohlc()]
OHLC DataFrame (open, high, low, close, volume)
   ↓ [Indicators.calculate_*()]
Enhanced OHLC + Indicators
   ↓ [Levels.detect_levels()]
OHLC + Indicators + Levels
```

**Execution Flow** (step-by-step example):
1. Module receives input (data, parameters)
2. Validates input meets preconditions
3. Processes through component A, then B, then C
4. Aggregates results
5. Returns output to caller

---

## 5. Critical Path Definition

The **critical path** is the sequence of modules and classes involved in the core trading loop:

```
Stock Abstraction
   ↓ [Fetch raw market data from Binance]
Data Module
   ↓ [Generate OHLC candles and calculate indicators]
Signals Module
   ↓ [Evaluate buy/sell signals]
Strategy Module
   ↓ [Make trading decision (ENTRY, EXIT, WAIT)]
Robot Module
   ↓ [Execute order and manage position]
Position Module
   ↓ [Track open trade, calculate PnL]
```

**Phase 2 Specifications** will document each of these modules and their key classes in detail.

**Supporting Systems** (Phase 3) — Training, NN, Backtesting, Frontend — are separate paths that feed into or consume from the critical path but are not part of the core real-time loop.

---

## 6. Execution Plan

### 6.1 Phase 1: Layer Specifications & System Architecture

**Deliverables:**
- `2026-05-04-pybtctr2-architecture.md` — Main system spec showing all layers and high-level data/execution flows
- `01-infrastructure-layer.md` — Docker, configuration, logging, environment setup
- `02-data-layer.md` — Stock abstraction, OHLC generation, indicators, levels
- `03-business-logic-layer.md` — Signals, strategies, decision-making
- `04-execution-layer.md` — Robot, position management, order execution

**Focus**: Define layer boundaries, responsibilities, and interactions. Establish the architectural skeleton.

**Outcome**: Clear picture of how the system is layered and how layers communicate. Anyone can read the main spec and understand the system architecture.

---

### 6.2 Phase 2: Critical Path Module & Class Specifications

**Modules** (in dependency order):
1. `stock-abstraction-module/` — Data collection and order execution interface
2. `data-module/` — OHLC candle management and technical indicators
3. `signals-module/` — Signal generation and aggregation
4. `strategy-module/` — Strategy coordination and decision-making
5. `robot-module/` — Live trading robot and execution
6. `position-module/` — Trade position tracking and lifecycle

**Per Module**:
- 1 module-level spec (components, data flow, execution flow, interfaces)
- 2-5 class-level specs for key classes (Data, SignalManager, StrategyManager, Robot, Position, Stock, BinanceAdapter, etc.)

**Focus**: Comprehensive specifications for the core trading loop. Detail flows, interfaces, and responsibilities.

**Outcome**: Specifications enable understanding of how data and control flow through the trading system. Can serve as reference for code review, refactoring, or agent automation.

---

### 6.3 Phase 3: Supporting Systems Specifications

**Systems**:
1. `training-module/` — Data generation and training orchestration
2. `nn-module/` — Neural network integration and prediction
3. `backtesting-module/` — Historical simulation and backtesting
4. `frontend-visualization-system/` — Data visualization, training metrics, live trading dashboard

**Per System**:
- 1 system-level spec (architecture, components, data flow)
- 2-3 key class specs (Trainer, NN, TrainRobot, FrontendAPI, etc.)

**Focus**: Extend the specification pattern to supporting systems. Show how they integrate with the critical path.

**Outcome**: Complete specification of the entire pybtctr2 system. All 40-45 specs linked hierarchically for navigation.

---

## 7. Cross-Linking and Navigation

**Linking Strategy**:
- Main spec links to all layer specs
- Layer specs link to their constituent modules
- Module specs link to their constituent classes
- Class specs reference classes they depend on

**Reference Format** (Markdown):
```markdown
See also: [Data Layer](../layers/02-data-layer.md), [Data Module](./data-module.md)
```

**Goal**: Any spec can be read independently, but links enable traversal from overview to detail and across related components.

---

## 8. Version Control & Commits

**Commit Strategy**:
- Each spec file committed individually as completed
- Commit message format: `[Spec] <spec-type>: <name>` (e.g., `[Spec] Layer: Data Layer`, `[Spec] Module: Signals`)
- Main spec committed last after all linking is verified

**Branches**: All specs created on current branch; merged to master when complete.

---

## 9. Quality Checks

Each spec will be reviewed for:
- **Completeness**: All required sections present
- **Internal Consistency**: No contradictions within the spec
- **Cross-Consistency**: No contradictions with related specs
- **Clarity**: Can someone new to the project understand it?
- **Accuracy**: Does spec match current code behavior?
- **Linkage**: References to related specs are valid and useful

---

## 10. Constraints & Assumptions

### 10.1 Constraints
- **No time estimates** in any specifications
- **No refactoring** during Phase 1-2 (specifications document existing code)
- **Light formality only**: Markdown + ASCII diagrams (no external tools, no formal notation)
- **Critical path first**: Prioritize core trading loop before supporting systems

### 10.2 Assumptions
- All current code is in a workable state (no major architectural bugs preventing documentation)
- Existing code structure is coherent enough to specify (if not, note architectural debt in the spec)
- Code will remain stable during Phase 1-2 (active refactoring can invalidate specs mid-documentation)

---

## 11. Success Metrics

✅ Phase 1 complete: All 5 layer specs + main architecture spec written and linked  
✅ Phase 2 complete: All 6 critical-path modules + ~15 key class specs written and linked  
✅ Phase 3 complete: All 4 supporting systems + ~10 class specs written and linked  
✅ Consistency: No contradictions between related specs  
✅ Completeness: All data/execution flows traced end-to-end  
✅ Usability: New team member can read main spec → layer spec → module spec → class spec and understand the system  

---

## 12. Next Steps

Upon approval of this design:
1. **Invoke writing-plans skill** to create a detailed implementation plan for Phase 1 (layer specs and main architecture spec)
2. Execute Phase 1 according to the plan
3. Upon Phase 1 completion, create implementation plan for Phase 2
4. Upon Phase 2 completion, create implementation plan for Phase 3

---

## Appendix: Example Spec Outlines

### Example: Layer Spec Outline

```markdown
# Data Layer Specification

## 1. Overview
- **Purpose**: ...
- **Responsibilities**: ...
- **Key Modules**: ...

## 2. Layer Boundaries
- **Upstream**: ...
- **Downstream**: ...
- **Interfaces**: ...

## 3. Data Flow
[ASCII diagram]

## 4. Execution Flow
1. Step 1
2. Step 2
...

## 5. Key Classes
- Class A: ...
- Class B: ...

## 6. Assumptions & Constraints
- ...
```

### Example: Module Spec Outline

```markdown
# Signals Module Specification

## 1. Module Overview
- **Purpose**: ...
- **Responsibility**: ...
- **Input**: ...
- **Output**: ...

## 2. Module Components
- Class A: ...
- Class B: ...

## 3. Data Flow
[ASCII diagram]

## 4. Execution Flow
1. Step 1
2. Step 2
...

## 5. Key Interfaces
- Method 1: ...
- Method 2: ...

## 6. Assumptions
- ...
```

### Example: Class Spec Outline

```markdown
# Position Class Specification

## 1. Class Overview
- **Purpose**: ...
- **Responsibility**: ...
- **Used by**: ...

## 2. Key Attributes
- `attr1: Type` — Description
- `attr2: Type` — Description

## 3. Data Flow
[Lifecycle diagram]

## 4. Key Methods & Interfaces
- `method1(param: Type) → Type`: Description
- `method2(param: Type) → Type`: Description

## 5. Execution Flow
1. Step 1
2. Step 2
...

## 6. Assumptions
- ...
```

---

**End of Design Document**
