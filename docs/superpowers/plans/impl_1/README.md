# Trading System Implementation — Master Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute. Each phase folder contains self-contained plan files. Phases with "(PARALLEL)" may run as simultaneous agents.

**Goal:** Implement `simple_trader` — a Python cryptocurrency trading system — from scratch, following the pybtctr2 architecture specs in `external/docs/superpowers/specs/`.

---

## Development Directories

| Purpose | Path |
|---------|------|
| Main branch | `/home/om/projects/simple_trader/main` |
| Worktrees root | `/home/om/projects/simple_trader/worktrees/` |
| Example worktree | `/home/om/projects/simple_trader/worktrees/<branch-name>/` |

**All relative paths in plan files resolve from the active working directory** — either `main` or the relevant worktree branch directory.

**Git worktrees:** When executing parallel phases (3a+3b, 6a+6b), each agent works in its own worktree under `/home/om/projects/simple_trader/worktrees/`. Use the `superpowers:using-git-worktrees` skill to create the worktree before starting.

**Repo:** `/home/om/projects/simple_trader/main` (git initialized, currently empty except README + CLAUDE.md)

---

## Dependency Graph

```
Phase 1: Infrastructure
    ↓
Phase 2a: Stock Abstraction ──┐
Phase 2b: Data Core           ├── sequential (2b depends on 2a)
    ↓                         ┘
Phase 3a: Signals ─────── PARALLEL ──┐
Phase 3b: Position ────── PARALLEL ──┤
    ↓                                ┘ (Phase 4 waits for BOTH)
Phase 4: Strategy
    ↓
Phase 5: Execution (Robot)
    ↓
Phase 6a: Backtesting ─── PARALLEL ──┐
Phase 6b: Training + NN ─ PARALLEL ──┤
    ↓                                ┘ (Phase 7 waits for BOTH)
Phase 7: Frontend
```

---

## Phase Files

| Phase | File | Agent | Depends on |
|-------|------|-------|------------|
| 1 | [phase-1-infrastructure/plan.md](phase-1-infrastructure/plan.md) | 1 | — |
| 2a | [phase-2-data-layer/plan-2a-stock-abstraction.md](phase-2-data-layer/plan-2a-stock-abstraction.md) | 1 | Phase 1 |
| 2b | [phase-2-data-layer/plan-2b-data-core.md](phase-2-data-layer/plan-2b-data-core.md) | 1 | Phase 2a |
| 3a | [phase-3-business-logic/plan-3a-signals.md](phase-3-business-logic/plan-3a-signals.md) | A | Phase 2b |
| 3b | [phase-3-business-logic/plan-3b-position.md](phase-3-business-logic/plan-3b-position.md) | B | Phase 2b |
| 4 | [phase-4-strategy/plan.md](phase-4-strategy/plan.md) | 1 | Phase 3a + 3b |
| 5 | [phase-5-execution/plan.md](phase-5-execution/plan.md) | 1 | Phase 4 |
| 6a | [phase-6-supporting/plan-6a-backtesting.md](phase-6-supporting/plan-6a-backtesting.md) | A | Phase 5 |
| 6b | [phase-6-supporting/plan-6b-training-nn.md](phase-6-supporting/plan-6b-training-nn.md) | B | Phase 5 |
| 7 | [phase-7-frontend/plan.md](phase-7-frontend/plan.md) | 1 | Phase 6a + 6b |

---

## Source Layout

```
src/simple_trader/
  infrastructure/    config, logging, paths, constants
  data/
    stocks/          base_stock, binance_stock, stock_item
    data_point.py    DataPoint protocol, LiveDataPoint, WideDataPoint
    data.py          LiveData, SimulationData, FullData
    indicators.py    Indicators (TA-Lib wrappers)
    levels.py        Levels (support/resistance)
  signals/           base_signal, atomic, combinators, signal_chain, signal_manager
  position/          coin, base_position, long_position, short_position, position
  strategy/          base_strategy, manual_long, manual_short, strategy_manager
  execution/         robot
  backtesting/       train_robot, simulation_result, performance_analyzer
  training/          trainer, data_point_generator, training_coordinator, result_aggregator
  nn/                nn_model, nn_predictor, checkpoint_manager
  frontend/          chart_renderer, data_viewer, training_dashboard, live_dashboard
tests/               mirrors src/ layout
```

---

## Tech Stack

- Python 3.11+, pytest, mypy, black
- pandas, numpy, python-binance, ta-lib (C), torch (Phase 6b+)
- No TA-Lib in unit tests — use pre-computed fixture DataFrames
