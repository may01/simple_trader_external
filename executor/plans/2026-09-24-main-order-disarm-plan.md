# Position Management 5/9 — main/ order placement disarmed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan layer-by-layer. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the executor the only process that can place a real order, by refusing `main/`'s write path at one boundary — code left in place, commented, and re-armable by one environment variable.

**Spec:** [`2026-09-22-position-management-design.md`](../specs/2026-09-22-position-management-design.md) §6.5, decision D2, audit row B10.

**Repository: `main/`, not `trade_executor`.** Branch `main-order-disarm`, cut from `experimental_imp_2`, merged back into it.

**Scope:** `main/stocks/`, `main/robots/`, `main/trader.py`, `main/tests/`. Python only.

**Depends on: nothing.** This is the one plan in the set with no dependency on any other — no Rust, no live-trade-ops, no schema. It can start immediately and should, because until it lands both processes can place orders against the same account.

**Blocks:** nothing strictly, but plan 6/9 assumes it (with main/'s order path live there would be two fill sources, and §6.4's single-`Position` design would not hold).

## Readiness review

Verified against the code on `layer-implementation` @ `ff2938d` and `live-trade-ops` @ `e45dc05` (2026-09-25).

🟢 **green** — exists in the system, small update · 🟡 **yellow** — in the spec, small code change · 🟠 **orange** — in the spec, large code change · 🔴 **red** — in neither code nor spec

### 🟢 Green

| Item | Where it is today | Change |
|---|---|---|
| `StockInterface` ABC with `trade`, `borrow`, `repay`, `cancel_order`, `order_info`, `funds`, `depth`, `info`, `get_aviable_loan`, … | `main/stocks/base_stock.py` | subclassed, not modified |
| The five order call sites | `robots/robot.py:317,370,405,409,430` + `live_order_tracker.py:59,68` | comments and log levels only |
| `LiveOrderTracker` — ids, `check_fill`, loan state, atomic JSON persistence | `robots/live_order_tracker.py` | untouched; only its leftover file is now reported at startup |
| Env-var wiring and the degrade-don't-crash pattern | `trader.py` (`MQ_EXECUTOR_ADDR`, the pyzmq guard) | the same shape, reused |
| `tests/test_robot_orders.py`, `tests/test_live_order_tracker.py` | `main/tests/` | kept green against the **armed** configuration, unchanged in meaning |

### 🟡 Yellow

`DisarmedStock` · `MAIN_ORDER_PLACEMENT` selection and its banners · the refusal-vs-failure distinction and the log-level change at the call sites · the leftover-tracker-JSON startup warning.

### 🟠 Orange

Nothing. This is the smallest plan in the set and the only one with no dependencies — which is exactly why it goes first.

### 🔴 Red

| Item | Status |
|---|---|
| **Signature drift in this plan — now fixed** | `StockInterface`'s real methods return tuples, not `None`: `trade(self, trade_type, price, amount, force=False) -> tuple`, `borrow(coin, amount) -> tuple`, `repay(coin, amount) -> tuple`, `cancel_order(order_id) -> tuple`. This plan's Task 1.1 had them as `-> None` and omitted `force`. **Corrected below.** `DisarmedStock` must return the interface's real failure tuple, and `force=True` must not bypass the refusal — a `force` flag that arms a disarmed stock would be the worst possible bug here. |
| `select_stock` helper name | implementation detail; no amendment needed |

---

## Global Constraints

- **Disabled, not deleted** (D2). No call site is removed. `LiveOrderTracker` keeps its loan bookkeeping and its crash-recovery JSON — those describe positions that may be open on the exchange right now.
- **Refusal at the `StockInterface` boundary, in one decorator** — not three `if` statements in `robot.py`. Same shape as the executor's own `NoTradeAccount` (`crates/orchestrator/src/no_trade.rs`) and for the same stated reason: the refusal must not depend on API-key permissions, on the exchange, or on anything outside the process being configured right.
- **Default is disarmed.** `MAIN_ORDER_PLACEMENT` unset means no orders.
- **Reads always pass through.** Disarming a write path must not blind the process.
- **Telemetry must never block or crash the trading path** — the standing rule in this repo (`16b22c3`, and `trader.py`'s pyzmq guard). A missing env var, a malformed value, anything: degrade loudly, never raise at import.
- **Commit only after explicit user confirmation.**

---

## Docker Entry Points

```bash
# Tests (the live image mounts the repo at /code)
docker compose run --rm --no-deps live python3 -m pytest tests/ -q
docker compose run --rm --no-deps live python3 -m pytest tests/test_disarmed_stock.py -q

# The process itself, disarmed (the default) and armed
docker compose run --rm live python3 trader.py
MAIN_ORDER_PLACEMENT=enabled docker compose run --rm live python3 trader.py
```

Verified: [ ] `docker compose run --rm --no-deps live python3 -m pytest tests/ -q` green on the branch before Layer 1 (baseline). If the `live` service's `env_file` blocks a bare test run, fix the invocation in this task and record the working command here — the entry point is the contract.

---

## Layer 1: The boundary

### Task 1.1: `DisarmedStock`

**Files:** create `stocks/disarmed_stock.py`; `tests/test_disarmed_stock.py`.

**Interface** (signatures only):
```python
class DisarmedStock(StockInterface):
    def __init__(self, inner: StockInterface) -> None: ...
    # refused — return the interface's own failure tuple, construct no request.
    # Signatures match stocks/base_stock.py exactly, including `force`.
    def trade(self, trade_type: str, price: float, amount: float, force: bool = False) -> tuple: ...
    def borrow(self, coin: str, amount: float) -> tuple: ...
    def repay(self, coin: str, amount: float) -> tuple: ...
    def cancel_order(self, order_id: str) -> tuple: ...
    # everything else delegates to inner, unchanged
```

**`force=True` must not bypass the refusal.** `StockInterface.trade` takes a
`force` flag; a disarmed stock that honoured it would arm itself on the one call
path most likely to be used in an emergency. This gets its own test.

**Unit tests (RED):**
- `trade` returns `STATUS_FAIL` and the wrapped stock's `trade` is never called (a spy, asserting zero calls — "did not reach the exchange" is the property, not "returned a failure").
- `borrow`, `repay`, `cancel_order` likewise.
- Every read method on `StockInterface` delegates and returns the inner value unchanged — enumerate them from the interface so a method added later is caught by a test that iterates the ABC, not by memory.
- A refusal is distinguishable from a genuine exchange failure by the caller (a sentinel in the returned dict, or a typed exception the call sites catch) — §6.5 requires refusals not be logged at `ERROR`, and that requires telling them apart.

**Constraints:** the class docstring states what replaced this path in the executor (`execution::Executor::open_position` / `do_close` / `run_stop_loss_watcher` / `apply_stop_loss_move`), points at spec §6.5, and says how to re-arm.

### Task 1.2: Selection in `trader.py`

**Files:** `trader.py`, `tests/test_trader_order_placement_config.py`.

**Interface:** `def select_stock(inner: StockInterface, mode: str | None) -> StockInterface: ...`

**Unit tests (RED):** unset → `DisarmedStock`; `"disabled"` → `DisarmedStock`; `"enabled"` → the inner stock; any other value → `DisarmedStock` **and** a `WARNING` (a typo must not arm anything); the armed path logs a `WARNING` banner naming the double-trade hazard; the disarmed path logs once at startup saying which process places orders instead.

**Layer 1 gate:** `docker compose run --rm --no-deps live python3 -m pytest tests/test_disarmed_stock.py tests/test_trader_order_placement_config.py -q` green. Commit: `feat(stocks): DisarmedStock — refuse order placement at the exchange boundary`.

---

## Layer 2: Call sites

### Task 2.1: Comments and refusal handling in `robot.py`

**Files:** `robots/robot.py` (`_place_valid_order`, `_open_position`, `_close_position`, `_stop_loss`), `robots/live_order_tracker.py` (`cancel_buy`, `cancel_sell`).

**Interface:** unchanged. Behaviour changes only in logging.

**Unit tests (RED):**
- A full open → close robot tick cycle against a `DisarmedStock` over a spy produces **zero** `trade`/`borrow`/`cancel_order` calls on the inner stock (the spec's acceptance criterion).
- The same cycle produces **no `ERROR`-level line** from `_open_position`/`_close_position`/`_stop_loss` (`caplog`). Today those log `ERROR` on a `""` order id, which would now fire on every decision; a refusal is a normal outcome and logs at `DEBUG` after one startup line.
- `self.position` is still opened and closed by the strategy exactly as before — the state machine, `change_history` and the action log are unaffected (§6.4 purpose 1). Assert the recorded actions are identical to the armed run's.
- A SHORT decision still opens `self.position` although `borrow` was refused (§6.5: `position.open()` runs before placement, and under the new design that call is intent).

**Constraints:** each of the five call sites gets a comment naming what now owns that action and pointing at spec §6.5. Do not remove the `ERROR` logging for the *armed* path — a real placement failure is still an error there.

### Task 2.2: Leftover tracker state

**Files:** `robots/live_order_tracker.py`, `trader.py`.

**Unit tests (RED):** a `live_order_tracker` JSON file left by a previous armed run is **loaded and reported, never acted on** — a startup `WARNING` naming the order ids and the loan amount it still claims; no cancel, no repay, no order query is issued as a result; the file is not deleted (an operator settles it by hand). Absent file → no warning, no error.

**Constraints:** §6.5 is explicit that silently ignoring a file that says "you owe a margin loan" is the failure mode this section exists to avoid.

### Task 2.3: Keep the armed tests honest

**Files:** `tests/test_robot_orders.py`, `tests/test_live_order_tracker.py`.

**Constraints:** these must stay green, **unchanged in meaning**, by running against the armed configuration. They are the regression net for the day someone re-arms; rewriting them to expect refusal would delete that net.

**Layer 2 gate:** `docker compose run --rm --no-deps live python3 -m pytest tests/ -q` fully green. Commit: `feat(robot): route order placement through the disarm boundary`.

---

## Done when

- [ ] Both layer gates green in Docker.
- [ ] Spec acceptance criteria satisfied here: "main/ places no orders … zero `trade`/`borrow`/`cancel_order` calls under the default config; `MAIN_ORDER_PLACEMENT=enabled` restores every one of them"; "a refused order is not logged as an error"; "a leftover `live_order_tracker` JSON produces a startup `WARNING` … and is not acted on".
- [ ] `main-order-disarm` merged into `experimental_imp_2` (after user confirmation).
