# Position Module → Business Logic Layer Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reclassify the Position module from the Execution Layer to the Business Logic Layer across all spec documentation.

**Architecture:** Position (BasePosition, LongPosition, ShortPosition, Coin, Position facade) manages trade lifecycle through a strict state machine — this is business logic (risk rules, P&L, stop-loss enforcement, position sizing) not execution mechanics. The Execution Layer (Robot, TrainRobot) becomes a thin adapter that reads position decisions and executes them via Binance. The Position facade retains execution-bridge attributes (order IDs, margin loan management, JSON persistence) but the module itself lives in Business Logic.

**Tech Stack:** Markdown spec files only. No code changes.

---

## Architectural Rationale

**Why Position belongs in Business Logic:**
- Position state machine enforces trading rules: "only tighten stop-loss", "safety close after timeout", "position size = f(risk_per_trade, stop_distance)"
- P&L calculation and risk management are business concerns
- Position tells Execution what to do — it is the decision record, not the executor
- StrategyManager already reads `position_state`/`position_target` as BL inputs

**What moves to Business Logic:**
- `BasePosition`, `LongPosition`, `ShortPosition`, `Coin` (pure state machine + P&L)
- `Position` facade: `open()`, `close()`, `finalize()`, `set_stop_loss()`, `check_stop_open()`, `close_by_time()`

**Execution-bridge concerns (remain in Position facade, but in BL layer):**
- `buy_id`, `sell_id` — Binance order ID tracking
- `set_loan()`, `set_repay()`, `get_loan()` — margin loan lifecycle
- `save_position()`, `load_position()` — JSON crash recovery

**Updated flow:**
```
StrategyManager.check() → (action, prices)
  ↓ [Business Logic Layer]
Position.open() / close() / set_stop_loss()
  → Position state machine transitions; stores execution intent in action/state
  ↓ [Execution Layer]
Robot / TrainRobot reads Position.get_action()
  → Executes via Binance API (live) or OHLC simulation (backtest)
  → Reports fills: Position.add_buy() / add_sell()
  → Calls Position.finalize() after close
```

---

## File Structure

Files to modify (no new files):

```
docs/superpowers/specs/
├── layers/
│   ├── 03-business-logic-layer.md         ← Add Position module + classes
│   └── 04-execution-layer.md              ← Remove position lifecycle; keep bridge references
├── 2026-05-05-pybtctr2-architecture.md    ← Move Position in diagram + tables
├── 2026-05-05-phase2-module-specifications-design.md  ← Re-assign Batch 1/3
└── critical-path/
    ├── position-module/
    │   └── position-module.md             ← Update layer ownership + boundaries
    └── robot-module/
        └── robot-module.md               ← Position is now BL dependency

docs/superpowers/plans/
└── 2026-05-05-phase2-module-specifications.md  ← Update BATCH 1 heading
```

---

## Task 1: Update Business Logic Layer spec

**Files:**
- Modify: `docs/superpowers/specs/layers/03-business-logic-layer.md`

- [ ] **Step 1: Update Purpose/Responsibilities section**

  Add to Responsibilities:
  ```
  - Manage trade lifecycle (open, close, finalize) through the Position state machine
  - Enforce risk management rules (stop-loss tightening, position sizing, safety timeouts)
  - Track P&L across graduated entry/exit fills
  ```

  Update Key modules line to include:
  ```
  `position/position.py`, `position/base_position.py`, `position/long_position.py`, `position/short_position.py`, `position/coin.py`
  ```

- [ ] **Step 2: Update Layer Boundaries section**

  Change downstream description — Execution Layer now receives position state/action, not just the 5-tuple from strategy_manager. Add:
  ```
  - Execution layer: reads position.get_action() + position.get_price_open/close() to determine what order to place; calls position.add_buy/add_sell() to record fills; calls position.finalize() to compute P&L
  ```

  Update Key interfaces to include:
  ```
  - `position.open(strategy_action, price_open, price_close, price_stop_loss, time_period, action_msg)` — initiates trade; sets state machine
  - `position.get_action() -> STRATEGY_ACTION_*` — execution layer reads this to know what order to place
  - `position.add_buy(amount, price)` / `position.add_sell(amount, price)` — execution layer reports fills
  - `position.finalize() -> (revenue_pct, revenue_abs)` — computes P&L; resets state
  ```

- [ ] **Step 3: Update Data Flow section**

  Extend the flow to include position after action selection:
  ```
  Single winning (action, open_price, close_price, stop_price, tf)
    ↓ [Robot.wait() routes to Position]
  Position.open() / close() / set_stop_loss()
    → state machine transitions; posImpl = LongPosition / ShortPosition
    → position.action set to OPEN_LONG / CLOSE_LONG / etc.
    → Execution layer reads position.get_action() to place order
  ```

- [ ] **Step 4: Add Position classes to Key Classes section**

  Append after StrategyManager:

  ```markdown
  ### Position (position/position.py)
  Facade wrapping posImpl (BasePosition subclass). Primary BL interface for trade lifecycle. Delegates open/close/finalize/set_stop_loss to posImpl. Also carries execution-bridge attributes used by Robot: buy_id/sell_id (Binance order IDs), set_loan()/set_repay() (margin), save_position()/load_position() (crash recovery).

  Key BL methods: `open()`, `close()`, `finalize()`, `set_stop_loss()`, `check_stop_open()`, `close_by_time()`, `get_target()`.

  ### BasePosition (position/base_position.py)
  Abstract state machine for a single trade. Enforces WAIT → WAIT_BUY/WAIT_SELL → WAIT_SAFETY_* → WAIT transitions. Manages price_open[], price_close[], price_stop_loss, Coin objects, execution history. Contains risk management logic: `check_stop_open()` (early close if price moved against), `close_by_time()` (safety timeout), `set_stop_loss()` (one-directional tightening only). P&L via `finalize()`.

  ### LongPosition / ShortPosition (position/long_position.py, short_position.py)
  Concrete BasePosition subclasses. LongPosition: buy then sell; coinUse=USDT, coinGet=coin. ShortPosition: sell then buy; coinUse=coin, coinGet=USDT. Implement direction-aware helpers (direction_profit, direction_loss, first_in_profit).

  ### Coin (position/coin.py)
  Data structure tracking one currency leg within a position. Attributes: name, size (available), used (deployed), returned (recovered), loan (borrowed for margin), want_to_use (intended allocation), action_amount (pending fill amount).
  ```

- [ ] **Step 5: Update Assumptions & Constraints section**

  Add:
  ```
  - Position state machine is the source of truth for trade state; Robot/TrainRobot are consumers, not owners — they must never bypass position.open/close/finalize
  - stop-loss movement is one-directional: set_stop_loss() only moves toward profit unless force=True; this is a business rule enforced by BasePosition
  - Position sizing uses risk_per_trade (1% of full_position) as a business rule constraint; execution layer must respect the amount returned by position.get_action_amount()
  ```

---

## Task 2: Update Execution Layer spec

**Files:**
- Modify: `docs/superpowers/specs/layers/04-execution-layer.md`

- [ ] **Step 1: Update Purpose/Responsibilities section**

  Remove from Responsibilities:
  - "Track position lifecycle state machine (WAIT → OPEN → CLOSE → finalize)"

  Replace with:
  - "Call position.open/close/set_stop_loss (Business Logic layer) to initiate state transitions"
  - "Read position.get_action() and execute the resulting order via Binance API or OHLC simulation"
  - "Report order fills to position via add_buy() / add_sell(); call finalize() after close"

  Update Key modules — remove position module files; they now live in BL.

- [ ] **Step 2: Update Layer Boundaries section**

  Change upstream feeds:
  ```
  - Business Logic layer: strategy_manager.check() returns (action, open_price, close_price, stop_price, tf); position.get_action() returns pending execution action
  ```

  Add note: "Position module lives in Business Logic layer; Execution layer calls into it but does not own it."

- [ ] **Step 3: Update Data Flow section**

  Change the position step to show it as a BL call, not an internal execution step:
  ```
  Robot.wait() / TrainRobot.wait()
    ↓ [routes action to Business Logic]
    ├── OPEN_LONG/SHORT → position.open(action, price_open, price_close, price_stop, tf)  [BL]
    ├── CLOSE_LONG/SHORT → position.close(price_close, price_stop, tf)                    [BL]
    ├── MOVE_STOP_LOSS_* → position.set_stop_loss(price, action_msg)                      [BL]
    └── DO_STOP_LOSS → position.setup_stop_loss() + immediate buy/sell
    ↓ [Execution Layer executes position's decision]
  ```

- [ ] **Step 4: Update Key Classes — Position section**

  Replace the full Position/BasePosition/LongPosition/ShortPosition/Coin descriptions with a brief reference:

  ```markdown
  ### Position facade — execution-bridge attributes
  Position module lives in Business Logic layer. The facade also carries execution-specific state consumed by Robot:
  - `buy_id`, `sell_id` — active Binance order IDs (set via `set_action_id()`)
  - `set_loan(amount)` / `set_repay(amount)` / `get_loan()` — margin borrow/repay lifecycle (live mode only)
  - `save_position()` / `load_position()` — JSON persistence to `manual_setup/{PAIR}/position.json` for crash recovery
  - `is_action_in_progress()` — True if a Binance order ID is recorded
  ```

  Remove BasePosition, LongPosition, ShortPosition, Coin class descriptions from Execution Layer (they are documented in BL layer).

- [ ] **Step 5: Update Assumptions & Constraints section**

  Remove: "Stop-loss movement is one-directional..." (it's documented in BL layer now)

  Add: "Position state machine (BL) is the authority on what orders should exist; Execution Layer never modifies position state directly — it only reports fills via add_buy/add_sell"

---

## Task 3: Update main architecture spec

**Files:**
- Modify: `docs/superpowers/specs/2026-05-05-pybtctr2-architecture.md`

- [ ] **Step 1: Update architecture ASCII diagram (Section 2)**

  Move "Position state machine" line from EXECUTION to BUSINESS LOGIC:

  ```
  ┌─────────────────────────────────────────────────────────┐
  │                    EXECUTION LAYER                       │
  │  Robot (live) / TrainRobot (sim) / Trainer (orchestrate)│
  │  Order placement / Fill processing / Crash recovery     │
  └──────────────────────┬──────────────────────────────────┘
                         │ calls check() + reads position.get_action()
                         ▼
  ┌─────────────────────────────────────────────────────────┐
  │                BUSINESS LOGIC LAYER                      │
  │  StrategyManager → Strategy → SignalManager             │
  │  SignalChains (50+ signal types) → Action decisions     │
  │  Position state machine / Trade lifecycle / P&L / Risk  │
  └──────────────────────┬──────────────────────────────────┘
  ```

- [ ] **Step 2: Update Critical Path (Section 3)**

  In the critical path flow, move Position before Robot/TrainRobot:

  ```
  StrategyManager (strategy_manager.py)
    ↓ coordinate multiple strategies; resolve conflicts; return single decision
  Position (position/)
    ↓ apply decision to state machine; set action, prices, posImpl
  Robot / TrainRobot
    ↓ read position.get_action(); execute via Binance API or OHLC simulation
  ```

- [ ] **Step 3: Update Layer Specifications table (Section 4)**

  Update Business Logic row to include Position module reference.

- [ ] **Step 4: Update Key Subsystems table (Section 7)**

  Update the Position row to note it is in Business Logic layer.

---

## Task 4: Update Phase 2 design doc

**Files:**
- Modify: `docs/superpowers/specs/2026-05-05-phase2-module-specifications-design.md`

- [ ] **Step 1: Update Batch 1 definition**

  Change Batch 1 from "Execution Layer (Robot + Position)" to "Execution Layer (Robot)":
  ```
  ### Batch 1: Execution Layer (Robot) — FIRST
  **Modules:** Robot
  **Focus:** Order execution, live trading vs. simulation, Binance API integration
  ```

- [ ] **Step 2: Update Batch 3 to include Position**

  Change Batch 3 from "Decision Layer (Signals + Strategy)" to "Decision Layer (Signals + Strategy + Position)":
  ```
  ### Batch 3: Decision Layer (Signals + Strategy + Position) — THIRD
  **Modules:** Signals, Strategy, Position
  **Focus:** Signal evaluation, strategy coordination, action resolution, trade lifecycle management
  ```

  Add Position specs to Batch 3 module/class list.

---

## Task 5: Update position-module.md

**Files:**
- Modify: `docs/superpowers/specs/critical-path/position-module/position-module.md`

- [ ] **Step 1: Update layer header and overview**

  Change the layer reference from "Execution Layer" to "Business Logic Layer". Update overview to clarify position is BL, not execution.

- [ ] **Step 2: Update Module Boundaries — Upstream/Downstream**

  Change upstream from "Robot (Live Trading): Requests position.open()..." to:
  ```
  - **StrategyManager (Business Logic)**: Calls position.open() / close() / set_stop_loss() when action decisions are made
  - **Robot (Execution Layer)**: Reports fills via add_buy/add_sell(); calls finalize(); reads buy_id/sell_id for order management; calls save_position() for persistence
  - **TrainRobot (Execution Layer)**: Simulates fills via add_buy/add_sell(); reads position state for strategy evaluation
  ```

---

## Task 6: Update robot-module.md

**Files:**
- Modify: `docs/superpowers/specs/critical-path/robot-module/robot-module.md`

- [ ] **Step 1: Update Upstream Dependencies**

  Add Position as a BL dependency:
  ```
  - **Position Module (Business Logic)**: Maintains trade state machine; Robot reads position.get_action() to determine what order to place; Robot reports fills via position.add_buy/add_sell(); Robot calls position.finalize() after trade closes
  ```

- [ ] **Step 2: Update data flow diagram**

  Change "Position State Transitions" box to show it as a BL component called by Robot, not part of Robot.

---

## Task 7: Update Phase 2 plan

**Files:**
- Modify: `docs/superpowers/plans/2026-05-05-phase2-module-specifications.md`

- [ ] **Step 1: Update BATCH 1 heading and description**

  Change from "BATCH 1: Execution Layer (Robot + Position)" to "BATCH 1: Execution Layer (Robot)".
  Update description to note Position was moved to Business Logic Layer.

---

## Self-Review

After all tasks, verify:
1. Every file that mentions "Position" in context of layer ownership is updated
2. Architecture diagram places Position in BL consistently
3. No contradictions between layer specs (BL says it owns Position, Execution says it calls Position)
4. Execution-bridge methods (buy_id, save_position, loan) are documented in BL spec as the interface point with Execution

---
