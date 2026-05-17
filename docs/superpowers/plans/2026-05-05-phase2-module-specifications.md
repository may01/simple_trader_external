# Phase 2: Critical Path Module & Class Specifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write 26 specification files documenting 6 core modules (Robot, Position, Stock Abstraction, Data, Signals, Strategy) in 3 sequential batches.

**Architecture:** Batch 1 (Execution Layer: Robot) → Batch 2 (Foundation Layer: Stock + Data) → Batch 3 (Decision Layer: Signals + Strategy + Position). Position has been reclassified from Execution to Business Logic Layer — it owns trade state machine, risk management, and P&L, while Robot is a thin executor. Each spec includes "Existing Approach" + "Potential Improvements". Class specs document full contracts (attributes, methods, state machines, error handling). All batches commit together at end.

**Tech Stack:** Markdown files only. No code changes. Verification against source code using grep and file inspection.

---

## File Structure

**Directory tree to create:**
```
docs/superpowers/specs/critical-path/
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

**Total files:** 26 specs (2 module + 3-5 class specs per module)

---

## BATCH 1: Execution Layer (Robot)

> **Note:** Position module was originally in this batch but has been reclassified to Business Logic Layer and moved to Batch 3 (Decision Layer). Position enforces trading rules, risk management, and P&L rather than execution mechanics.

### Task 1: Create Directory Structure

**Files:**
- Create: `docs/superpowers/specs/critical-path/` (directory)
- Create: All subdirectories for 6 modules (listed above)

- [ ] **Step 1: Create critical-path directory**

```bash
mkdir -p docs/superpowers/specs/critical-path
```

- [ ] **Step 2: Create all module subdirectories**

```bash
mkdir -p docs/superpowers/specs/critical-path/{robot-module,position-module,stock-abstraction-module,data-module,signals-module,strategy-module}
```

- [ ] **Step 3: Verify directory structure**

```bash
find docs/superpowers/specs/critical-path -type d | sort
```

Expected: All 6 module directories created.

---

### Task 2: Write Robot Module Specification

**Files:**
- Create: `docs/superpowers/specs/critical-path/robot-module/robot-module.md`
- Read: `robot.py` (to verify current implementation)

- [ ] **Step 1: Read robot.py to understand structure**

```bash
head -50 robot.py
grep -n "class Robot\|def run_instantly\|def do\|def wait\|def trade_action" robot.py | head -20
```

- [ ] **Step 2: Write robot-module.md**

Create file with following content (document as-is, then list improvements):

```markdown
# Robot Module Specification

**Module position:** Execution layer — live trading robot that polls market data, evaluates strategies, and executes orders.

**Related specs:**
- [Main Architecture](../../2026-05-05-pybtctr2-architecture.md)
- [Execution Layer](../../layers/04-execution-layer.md)
- [Position Module](../position-module/position-module.md)

---

## 1. Overview

**Purpose:** Implement the live trading loop that continuously polls Binance for market updates, evaluates trading strategies, and executes buy/sell orders.

**Responsibilities:**
- Maintain infinite polling loop (5-30 second intervals)
- Fetch current market data (candles, depth) from Binance
- Calculate technical indicators on all timeframes
- Evaluate strategies and obtain trading decisions
- Place, monitor, and manage Binance orders
- Track position lifecycle and handle stop-loss triggers
- Persist position state to disk for crash recovery
- Log trading actions and revenue

**Key classes:** Robot, integrated with StrategyManager and Position

---

## 2. Module Boundaries

**Upstream (feeds into this module):**
- Binance exchange: live market data, order execution, order status queries
- StrategyManager: trading decisions (action, prices, timeframe)
- Data layer: candle building, indicator calculation
- Infrastructure: logging, file paths, configuration

**Downstream (layers that consume this module):**
- Visualization tools: read saved position JSON and action pkl files
- Monitoring/alerting: subscribe to logs or action outcomes
- Manual intervention: read/modify position state from JSON

**Key interfaces this module exposes:**
- `robot.run_instantly(test_buy_sell=False)` — start infinite live trading loop
- Position state persisted to `manual_setup/{PAIR}/position.json`
- Actions persisted to `shared/actions/{timestamp}.pkl`
- Revenue logged to `output/REVENUE_{PAIR}_0.txt`

---

## 3. Data Flow

```
Binance Exchange
   ↓ [stock.item.update_candles() + get_depth_data()]
Live market data (OHLCV + depth)
   ↓ [Data.build_candles() + Indicators.calc()]
Enriched OHLCV with all indicators on all timeframes
   ↓ [StrategyManager.check()]
Trading decision: (action, open_price, close_price, stop_price, tf)
   ↓ [Robot.wait() routes by action type]
Position state transitions: WAIT → OPEN → CLOSE → finalize()
   ↓ [Robot.trade_action() → stock.item.trade()]
Binance order placed → fills monitored → finalized
   ↓ [position.save_position() + action.save()]
State persisted to JSON + pkl
```

---

## 4. Execution Flow

### Polling Loop (run_instantly)

1. Infinite loop:
   - Call `data_item.update_candles()` and `data_item.get_depth_data(1000)`
   - Set `data_item.cur_point = int(time.time())`
   - Call `Indicators.calc()` for each timeframe (1, 3, 5, 15, 60, 240)
   - Call `self.do()` — single trading step
   - Sleep: 5 seconds if action pending, 30 seconds if idle
2. On exception: sleep 2 minutes, reinitialize stock connection, retry

### Single Step (do)

1. Create `Action()` marker object
2. Call `self.wait(action_msg)` → returns `immediate_next_step` bool
3. If not immediate: check `position.check_stop_open()` and `position.close_by_time()`
4. If action pending: call `self.trade_action(position)`
5. Call `position.save_position()` — persist state to JSON
6. Call `action_msg.save()` — persist action to pkl

### Order Management (trade_action)

1. Check `is_action_in_progress()` — is an order ID tracked?
2. If in progress: call `process_executed_orders()` → check Binance fills
3. If filled: call `do_finalize_action()` → repay loan, finalize position
4. If not in progress: call `place_valid_order()` → compute amount, submit trade
5. Stop-loss path: cancel via `stop_loss_cancel_actions()` before placing new order

---

## 5. Key Components

### Robot Class

Core attributes:
- `fee = 0.002` (class-level)
- `update_period = 10` (polling interval in seconds, adjusted by action state)
- `risk_per_trade = 0.01` (risk per trade as % of capital)
- `data_item` (singleton Data reference)
- `stock` (stock module for Binance API)
- `strategy_mngr` (StrategyManager for decision making)
- `position` (current Position object)
- `schedule` (list of pending actions)
- `cur_action` (current action being executed)

Key methods:
- `run_instantly(test_buy_sell=False)` — infinite polling loop
- `do()` — single step: evaluate strategy, route to position, persist state
- `wait(action_msg)` — evaluate strategy, route by action type
- `trade_action(position)` — order placement and fill monitoring
- `place_valid_order()` → compute amount → stock.item.trade()
- `process_executed_orders()` → query Binance order status
- `do_finalize_action()` → repay loan, call position.finalize()

---

## 6. Existing Approach

Current Robot implementation:
- Hardcoded fee = 0.002 (0.2% Binance fee)
- Polling sleep 5-30 seconds based on action state
- Exception handling: 2-minute sleep + reinit on error
- Position state saved to JSON after every do() step
- Actions saved to pkl for visualization/logging
- Order IDs tracked in position.buy_id / position.sell_id
- Margin loans: borrow on open (if needed), repay on close

Design patterns:
- Infinite loop with sleep-based polling (not event-driven)
- State machine via position.state (WAIT, WAIT_BUY, WAIT_SELL, etc.)
- Action routing: one place where (action_type, position_state) → position method call
- Single position open at a time (no portfolio management)

---

## 7. Potential Improvements

1. **Event-driven architecture** — Replace polling loop with WebSocket market data stream from Binance (lower latency, less CPU)
2. **Portfolio support** — Track multiple open positions simultaneously instead of max 1 per pair
3. **Dynamic fee configuration** — Make fee adjustable per-trade instead of class-level constant
4. **Configurable polling intervals** — Move 5s/30s sleep times to config instead of hardcoded
5. **Order timeout logic** — Add configurable order timeout; auto-cancel orders stuck for > N minutes
6. **Partial position sizing** — Support multiple price levels with graduated position sizes (e.g., buy in 3 tranches)
```

- [ ] **Step 3: Verify against source**

```bash
grep -c "def run_instantly\|def do\|def wait\|def trade_action" robot.py
```

Expected: At least 4 key methods found.

- [ ] **Step 4: Check module is complete**

Verify file exists and contains all sections (Overview, Boundaries, Data Flow, Execution Flow, Components, Existing Approach, Potential Improvements).

---

### Task 3: Write Robot Class Specification

**Files:**
- Create: `docs/superpowers/specs/critical-path/robot-module/robot-class.md`
- Read: `robot.py` (full file for Robot class methods and attributes)

- [ ] **Step 1: Scan Robot class in robot.py**

```bash
grep -n "class Robot\|def __init__\|def run_instantly\|def do\|def wait\|self\." robot.py | head -40
```

- [ ] **Step 2: Write robot-class.md with full contract**

[Due to length, this task contains extensive spec content documenting Robot class attributes, constructor, methods, state management, error handling, existing approach, and potential improvements. In actual execution, write the complete class spec with all sections filled in with exact implementation details from robot.py]

- [ ] **Step 3: Verify method names match source**

```bash
grep "def " robot.py | grep -E "run_instantly|do|wait|trade_action|place_valid_order|process_executed_orders"
```

Expected: All key methods present.

---

### Task 4: Write Position Module Specification

**Files:**
- Create: `docs/superpowers/specs/critical-path/position-module/position-module.md`
- Read: `position/position.py`, `position/base_position.py`

- [ ] **Step 1: Read position module structure**

```bash
head -30 position/position.py
head -30 position/base_position.py
grep -n "class Position\|class BasePosition\|class LongPosition\|class ShortPosition" position/*.py
```

- [ ] **Step 2: Write position-module.md**

[Position module spec documenting state machine, position lifecycle, margin loan management, with Existing Approach + Potential Improvements]

---

### Task 5-8: Write Remaining Position Classes

- [ ] **Task 5: Write position-class.md** (Position facade class)
- [ ] **Task 6: Write base-position-class.md** (Abstract state machine)
- [ ] **Task 7: Write long-position-class.md** (LongPosition implementation)
- [ ] **Task 8: Write short-position-class.md** (ShortPosition implementation)
- [ ] **Task 9: Write coin-class.md** (Currency tracking class)

*(Each task follows same pattern: read source, write spec with full contract, verify)*

---

## BATCH 2: Foundation Layer (Stock Abstraction + Data)

### Task 9: Write Stock Abstraction Module Specification

**Files:**
- Create: `docs/superpowers/specs/critical-path/stock-abstraction-module/stock-abstraction-module.md`
- Read: `stocks/base_stock.py`, `stocks/binance_stock.py`

*(Follow same pattern as Robot module)*

---

### Tasks 10-17: Write Stock Classes + Data Module + Data Classes

- [ ] **Task 10:** Write base-stock-interface-class.md
- [ ] **Task 11:** Write binance-stock-class.md
- [ ] **Task 12:** Write stock-item-class.md
- [ ] **Task 13:** Write data-module.md
- [ ] **Task 14:** Write data-class.md
- [ ] **Task 15:** Write indicators-class.md
- [ ] **Task 16:** Write levels-class.md
- [ ] **Task 17:** Write dataiterator-class.md

---

## BATCH 3: Decision Layer (Signals + Strategy + Position)

### Tasks 18-26: Write Signals + Strategy Modules and Classes

- [ ] **Task 18:** Write signals-module.md
- [ ] **Task 19:** Write signal-manager-class.md
- [ ] **Task 20:** Write signal-chain-class.md
- [ ] **Task 21:** Write base-signal-class.md
- [ ] **Task 22:** Write strategy-module.md
- [ ] **Task 23:** Write strategy-class.md
- [ ] **Task 24:** Write manual-strategy-long-class.md
- [ ] **Task 25:** Write manual-strategy-short-class.md
- [ ] **Task 26:** Write strategy-manager-class.md

---

## Task 27: Final Verification & Commit All Batches

**Files:**
- Verify: All 26 spec files created and contain required sections
- Commit: Single git commit for all 3 batches

- [ ] **Step 1: Verify all 26 specs exist**

```bash
find docs/superpowers/specs/critical-path -name "*.md" -type f | wc -l
```

Expected: 26 files.

- [ ] **Step 2: Quick content check (sample)**

```bash
grep -l "Existing Approach\|Potential Improvements" docs/superpowers/specs/critical-path/*/*.md | wc -l
```

Expected: All 26 files contain both sections.

- [ ] **Step 3: Verify no placeholder text**

```bash
grep -r "TBD\|TODO\|placeholder" docs/superpowers/specs/critical-path/ || echo "No placeholders found"
```

Expected: No matches.

- [ ] **Step 4: Commit all specs together**

```bash
git add docs/superpowers/specs/critical-path/
git commit -m "Add Phase 2: Critical path module and class specifications

Adds 26 specifications across 3 batches:
- Batch 1 (Execution): Robot (2 specs) = 2 specs
- Batch 2 (Foundation): Stock Abstraction (4 specs) + Data (5 specs) = 9 specs
- Batch 3 (Decision): Signals (4 specs) + Strategy (5 specs) + Position (7 specs) = 16 specs

Each spec documents existing approach + potential improvements.
Class specs include full contracts (methods, attributes, state machines, error handling).

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Verify commit**

```bash
git log --oneline -1
```

Expected: Single commit with all 26 specs.

---

## Summary

**Deliverables:**
- 26 specification files (2 module + 3-5 class specs per module)
- Organized in `docs/superpowers/specs/critical-path/` with 6 module subdirectories
- Each spec includes: Overview, Boundaries, Data Flow, Execution Flow, Components, Existing Approach, Potential Improvements (for modules) + full class contracts
- All specs committed in single git commit
- Total: ~150-200KB of documentation

**Next:** Phase 3 planning (Training, NN, Backtesting, Frontend modules)
