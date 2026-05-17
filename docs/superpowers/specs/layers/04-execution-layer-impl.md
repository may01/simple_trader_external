# Execution Layer — Implementation Resolution Map

**Companion to:** [04-execution-layer.md](04-execution-layer.md)

This document tracks implementation details extracted from the execution layer design spec. Each entry identifies the detail, the class-level spec that owns its resolution, and the open question that must be answered there. Once a topic is resolved in the owning spec, it can be archived here.

---

## §1. Order Lifecycle (Live Trading)

**Owning spec:** [robot-module.md](../critical-path/robot-module/robot-module.md)

| Detail | Open Question |
|---|---|
| Step-by-step flow: place → monitor fills → cancel → finalize | Fully documented in robot-module.md §Order Management. No gap. |
| Stop-loss order priority: cancel existing order before placing stop | Is there a race condition if the original order partially fills between cancel and stop placement? Resolution needed in robot-module.md. |
| ATR adjustment for stop-loss price: 0.5× ATR applied at placement | Why 0.5x specifically? Is this empirically validated or a placeholder? Document rationale or make configurable. |
| `check_stop_open()`: triggers if max open-wait time exceeded | What is the max wait threshold? Currently implicit. Make explicit in robot-module.md. |
| `close_by_time()`: triggers if action timeout exceeded | Same — timeout value not specified at design level. |

---

## §2. Simulation Fill Logic (Backtest Execution)

**Owning spec:** [backtesting-module.md](../supporting-systems/backtesting-module/backtesting-module.md)

| Detail | Open Question |
|---|---|
| Buy fill condition (exit short / enter long): `low <= price_close` or `low <= price_open` | What happens when both stop-loss and target price fall within the same candle? Which takes priority? Needs explicit rule in backtesting-module.md. |
| Stop-loss fill (short position): execute if `low > price_stop_loss` | Asymmetric naming: "low > stop" triggers a buy — document this non-obvious direction explicitly. |
| Sell fill condition (exit long / enter short): mirrors buy conditions against `high` | Same priority question as buy. |
| Fill price is exact candle extreme (no slippage) | Design-level assumption confirmed. Implementation must not add implicit slippage. |
| `set_data(cur_data)` must be called before each `do()` | Enforce this precondition — currently by convention only. Consider assertion. |

---

## §3. Position State Machine

**Owning spec:** Position module spec (not yet written — candidate for critical-path specs)

| Detail | Open Question |
|---|---|
| State names: `WAIT`, `WAIT_SELL`, `WAIT_BUY`, `WAIT_SAFETY_SELL`, `WAIT_SAFETY_BUY` | These are code constants surfaced in the layer spec. They belong in a position module spec, not the execution layer. |
| State transitions (e.g. `OPEN_LONG` signal → `posImpl = LongPosition; action = OPEN_LONG`) | Full transition table should live in position module spec. |
| `WAIT_SAFETY_SELL` / `WAIT_SAFETY_BUY`: partial fill states | Conditions for entering and exiting partial fill states are not fully documented at any spec level. |

---

## §4. Hardcoded Values (Live Trading)

**Owning spec:** [robot-module.md](../critical-path/robot-module/robot-module.md)

| Detail | Open Question |
|---|---|
| `fee = 0.002` (class variable) | Should this be environment-configurable? Currently hardcoded. If Binance fee structure changes, this requires a code change. |
| `update_period`: 5s when action pending, 30s when idle | Should these be configurable? Adaptive intervals (e.g. based on volatility) considered as improvement. |
| `risk_per_trade = 0.01` | Is this a fixed design constraint or a user-configurable parameter? |
| `sleet_on_step` attribute | Typo for `sleep_on_step`. Rename before implementation. Track in robot-module.md. |

---

## §5. Parallelization (Orchestration / Backtest Execution)

**Owning spec:** [backtesting-module.md](../supporting-systems/backtesting-module/backtesting-module.md)

| Detail | Open Question |
|---|---|
| `mp.Value` shared memory for cross-process revenue totals | Fragile for aggregation — race conditions possible. Consider accumulating in per-process files and summing on main thread instead. |
| Thread result files: `shared/thread_result_by_id_{N}.pkl` | File naming convention is implicit. Should be explicit in backtesting-module.md. |
| `TRAINER_TIME_STEP` is in minutes; DataIterator steps in seconds — conversion applied in Trainer | Leaky abstraction: unit conversion scattered at call site. Consider normalizing at DataIterator boundary. |
| Time range split across N workers: no shared mutable state | Confirm: are there any implicit shared resources (e.g. file writes to same path) that could conflict between workers? |

---

## §6. Persistence & Recovery (Live Trading)

**Owning spec:** [robot-module.md](../critical-path/robot-module/robot-module.md) for behavior; Infrastructure layer spec for path conventions

| Detail | Open Question |
|---|---|
| Position JSON path: `manual_setup/{PAIR}/position.json` | Path is hardcoded. Should be config-driven. Belongs in Infrastructure layer spec. |
| Action pkl path: `shared/actions/{timestamp}.pkl` | Same — path convention should be explicit in Infrastructure layer spec. |
| Crash recovery flow: `restore_position()` called on Robot restart | What is the behavior if the JSON is corrupt or stale? Failure mode not specified. |
| `save_position(suffix="")` suffix parameter | Used for backup snapshots? Purpose and naming convention not documented. |

---

## §7. Live/Simulation Symmetry

**Owning specs:** [robot-module.md](../critical-path/robot-module/robot-module.md) and [backtesting-module.md](../supporting-systems/backtesting-module/backtesting-module.md)

| Detail | Open Question |
|---|---|
| `wait()` must be identical in Robot and TrainRobot | Currently enforced by convention only — no shared base class, no test covering parity. How is drift detected? |
| `IS_TRAIDER_TEST=1` paper-trade mode in Robot | Does paper-trade mode affect strategy evaluation or only order submission? If it affects strategy, it breaks symmetry. Clarify in robot-module.md. |
| Loan management (live only) | Must not leak into strategy or `wait()` logic — currently by convention. Should be enforced structurally. |
| StrategyManager instance: same class in both paths | Confirm no live-only state is injected into StrategyManager that would alter simulation results. |

---

## §8. Position Execution Bridge (Live Trading only)

**Owning spec:** [robot-module.md](../critical-path/robot-module/robot-module.md) and Position module spec

**Status: RESOLVED** — See [2026-05-10-position-cross-layer-alignment-design.md §2](../2026-05-10-position-cross-layer-alignment-design.md).

| Detail | Resolution |
|---|---|
| `buy_id`, `sell_id`: Binance order IDs stored on Position facade | Extracted to `LiveOrderTracker` class in execution layer. Position no longer owns order IDs. |
| `set_action_id(id)`, `is_action_in_progress()` | Moved to `LiveOrderTracker`. |
| `set_loan(amount)`, `set_repay(amount)`, `get_loan()` | Moved to `LiveOrderTracker`. |
| `save_position()`, `load_position()`, `restore_position()` | Moved to `Robot`. Position still serializes via `to_dict`/`from_dict`; I/O lifecycle owned by Robot. |
| `is_real_stock` flag on Position | Removed. Paper-trade mode controlled in Robot via `IS_TRADER_TEST` env var. |
