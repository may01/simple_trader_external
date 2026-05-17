# Phase 2: Critical Path Module & Class Specifications Design Document

**Date:** 2026-05-05  
**Project:** pybtctr2 — Cryptocurrency Trading Bot  
**Objective:** Design Phase 2 documentation: specify 6 core modules and 24+ key classes using full contract documentation, organized in 3 sequential batches.

---

## 1. Design Overview

Phase 2 documents the critical path modules from Phase 1 architecture: Robot → Position (Batch 1), Stock Abstraction → Data (Batch 2), Signals → Strategy (Batch 3). Each batch pairs 2 modules and includes module-level + class-level specifications.

**Key Constraints:**
- Document existing code as-is; no refactoring
- Light formality: Markdown + ASCII diagrams only
- For each section: **Existing Approach** (current implementation) + **Potential Improvements** (numbered list)
- Class specs include full contracts: methods, attributes, state machines, error handling
- Sequential execution: Batch 1 → Batch 2 → Batch 3 (reverse dependency order)
- Commit all 3 batches together at the end

---

## 2. Batch Definitions

### Batch 1: Execution Layer (Robot) — FIRST

**Modules:** Robot  
**Total Specs:** 2 (1 module + 1 class)  
**Dependencies:** Strategy layer (Batch 3), Position module (Batch 3)  
**Focus:** Order placement, fill processing, live trading vs. simulation

**Module Specs (1 file):**
- `robot-module.md` — Polling loop, order management, Binance integration, state persistence

**Class Specs (1 file):**
- `robot-class.md` — Live trading robot (full contract)

> **Note:** Position module was originally in this batch but has been reclassified to Business Logic Layer (see Batch 3 below). Position enforces trading rules (state machine, risk management, P&L) rather than execution mechanics.

---

### Batch 2: Foundation Layer (Stock Abstraction + Data) — SECOND

**Modules:** Stock Abstraction, Data  
**Total Specs:** 8 (2 module + 6 class)  
**Dependencies:** Infrastructure layer (Phase 1)  
**Focus:** Data collection from Binance, OHLC multi-timeframe management, indicator calculation

**Module Specs (2 files):**
- `stock-abstraction-module.md` — Binance API adapter, interface pattern, singleton access
- `data-module.md` — OHLC management, indicator pipeline, level detection, data persistence

**Class Specs (6 files):**
- `base-stock-interface-class.md` — Abstract interface (fetch_candles, trade, get_order_status)
- `binance-stock-class.md` — Live Binance implementation with API credentials, rate limiting
- `stock-item-class.md` — Singleton wrapper providing module-level access
- `data-class.md` — Main Data class (OHLC dict, indicators, classification, targets)
- `indicators-class.md` — Technical indicator calculation via TA-Lib (RSI, MACD, CCI, EMA, etc.)
- `levels-class.md` — Support/resistance level management (slope levels, activation times)
- `dataiterator-class.md` — Historical data replay for backtesting (time stepping)

---

### Batch 3: Decision Layer (Signals + Strategy + Position) — THIRD

**Modules:** Signals, Strategy, Position  
**Total Specs:** 16 (3 module + 13 class)  
**Dependencies:** Data layer (Batch 2)  
**Focus:** Signal evaluation, signal composition, strategy coordination, action resolution, trade lifecycle management

**Module Specs (3 files):**
- `signals-module.md` — 50+ signal types, signal chains, signal composition (AND, OR, NOT, History)
- `strategy-module.md` — Strategy registration, level building, action selection, price resolution
- `position-module.md` — State machine, risk management, P&L, trade lifecycle (Business Logic)

**Class Specs (13 files):**
- `signal-manager-class.md` — Orchestrates multiple SignalChains, collects completed chains
- `signal-chain-class.md` — Sequential signal evaluation (state machine: cur_pos advances)
- `base-signal-class.md` — Abstract signal interface (check, reset, get_data, set_shift)
- `atomic-signal-classes.md` — Single comparisons (Less, Greater, Cross_Up, Cross_Down, etc.)
- `combinator-signal-classes.md` — Logical composition (And, Or, Not, Continuous, History)
- `strategy-class.md` — Base strategy class (abstract interface, level building, action selection)
- `manual-strategy-long-class.md` — Concrete long strategy (CCI-based entry/exit)
- `manual-strategy-short-class.md` — Concrete short strategy (CCI-based entry/exit)
- `strategy-manager-class.md` — Multi-strategy coordination, NN integration, action merging
- `position-class.md` — Facade: delegates BL methods to posImpl; carries execution-bridge attributes
- `base-position-class.md` — Abstract state machine (WAIT → OPEN → CLOSE), risk rules, P&L
- `long-position-class.md` — Long trade lifecycle (buy → sell → finalize), direction helpers
- `short-position-class.md` — Short trade lifecycle (sell → buy → finalize), direction helpers
- `coin-class.md` — Currency tracking (size, used, loan, returned) — single currency leg

---

## 3. Specification Content Structure

### Module Specification Template

Each module spec follows this structure:

1. **Overview** (3-4 paragraphs)
   - Purpose and responsibilities
   - Key classes in the module
   - How this module fits in the critical path

2. **Module Boundaries** (brief)
   - Upstream: what feeds into this module
   - Downstream: what consumes this module's output
   - Key interfaces exposed

3. **Data Flow** (ASCII diagram)
   - Input → Processing → Output
   - Shows movement of data through module components

4. **Execution Flow** (step-by-step)
   - How the module operates during live trading or backtesting
   - Numbered sequence or process description

5. **Key Components** (list)
   - Brief description of each class in the module
   - What it does, what it depends on

6. **Existing Approach** (1-2 sections)
   - Current implementation pattern
   - Design decisions, architecture choices
   - Any notable patterns or conventions

7. **Potential Improvements** (numbered list)
   - 3-5 improvement ideas (not required)
   - Each item is a separate point
   - Examples: refactoring ideas, missing features, architectural improvements

---

### Class Specification Template

Each class spec includes:

1. **Class Overview** (2-3 paragraphs)
   - Purpose and responsibility
   - Who uses it, what does it do
   - Key role in the module

2. **Key Attributes** (table or list)
   - Instance variable names
   - Types and descriptions
   - Default values if applicable

3. **Constructor** (`__init__`)
   - Parameters and their types
   - Initialization logic
   - Preconditions

4. **Key Methods & Interfaces** (method signatures with contracts)
   - Method name and signature
   - Parameters (types, descriptions)
   - Return value (type, description)
   - Preconditions and postconditions
   - Exceptions raised
   - Usage example if complex

5. **State Management** (if applicable)
   - State machine diagram (if complex)
   - Valid state transitions
   - How state changes
   - Invariants maintained

6. **Error Handling** (if applicable)
   - Exception types raised
   - Recovery strategies
   - Failure modes

7. **Existing Approach** (1-2 sections)
   - Current implementation style
   - Notable design choices
   - Patterns used

8. **Potential Improvements** (numbered list)
   - 2-4 improvement ideas
   - Examples: performance, clarity, error handling, extensibility

---

## 4. Documentation Principles

### Existing Code, Existing Patterns

- Document the code as it currently exists; don't prescribe refactoring
- Follow the patterns already in the codebase (don't suggest new patterns unless listed as improvement)
- Note architectural decisions without judgment

### Light Formality

- Markdown text with embedded ASCII diagrams
- No external diagram tools
- Simple, readable notation for flows and state machines
- Code examples only when illustrating an interface

### Cross-References

- Module specs link to their class specs
- Class specs reference related classes in other modules
- Use Markdown links: `[Class Name](../other-module/class-spec.md)`
- Phase 1 layer specs available as context: `../../layers/`

### Depth per Layer

- **Execution Layer (Batch 1):** Detailed state machines, order management, persistence
- **Foundation Layer (Batch 2):** Data structures, indicator pipelines, configuration options
- **Decision Layer (Batch 3):** Signal evaluation patterns, strategy composition, action prioritization

---

## 5. Batch Execution Workflow

### Per-Batch Process

1. **Write module specs** — Boundaries, data flow, execution flow, components
2. **Write class specs** — Full contracts for each key class
3. **Verify against source code** — Cross-check specs match actual implementation
4. **Move to next batch**

### Across All Batches

1. Batch 1 specs write (Robot, Position)
2. Batch 2 specs write (Stock, Data)
3. Batch 3 specs write (Signals, Strategy)
4. **Single git commit** for all 3 batches together
5. Phase 3 planning begins

---

## 6. File Organization

All specs organized under `docs/superpowers/specs/critical-path/`:

```
critical-path/
├── robot-module/
│   ├── robot-module.md
│   └── robot-class.md
├── position-module/
│   ├── position-module.md
│   ├── position-class.md
│   ├── base-position-class.md
│   ├── long-position-class.md
│   ├── short-position-class.md
│   └── coin-class.md
├── stock-abstraction-module/
│   ├── stock-abstraction-module.md
│   ├── base-stock-interface-class.md
│   ├── binance-stock-class.md
│   └── stock-item-class.md
├── data-module/
│   ├── data-module.md
│   ├── data-class.md
│   ├── indicators-class.md
│   ├── levels-class.md
│   └── dataiterator-class.md
├── signals-module/
│   ├── signals-module.md
│   ├── signal-manager-class.md
│   ├── signal-chain-class.md
│   └── base-signal-class.md
└── strategy-module/
    ├── strategy-module.md
    ├── strategy-class.md
    ├── manual-strategy-long-class.md
    ├── manual-strategy-short-class.md
    └── strategy-manager-class.md
```

---

## 7. Success Criteria

✅ All 26 specs written (2 module + class specs per module across 6 modules + signal/strategy combinator classes)  
✅ Each module spec covers: Overview, Boundaries, Data Flow, Execution Flow, Components, Existing Approach, Potential Improvements  
✅ Each class spec covers: Overview, Attributes, Constructor, Methods, State Management, Error Handling, Existing Approach, Potential Improvements  
✅ All specs verified against source code accuracy  
✅ Cross-references working between related specs  
✅ No time estimates in any specs  
✅ All 3 batches committed together in single git commit  

---

## 8. Next Steps (After Phase 2)

1. Review Phase 2 specs
2. Create implementation plan for Phase 3 (Training, NN, Backtesting, Frontend)
3. Execute Phase 3 with same three-batch sequential approach

---

**End of Design Document**
