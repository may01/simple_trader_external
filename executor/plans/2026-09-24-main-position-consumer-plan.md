# Position Management 6/9 — main/ position consumer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan layer-by-layer. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let main/ see what the executor holds — enough to record actions for level visualisation and to hold an average entry price that risk and strategy can be recomputed against. Nothing more.

**Spec:** [`2026-09-22-position-management-design.md`](../specs/2026-09-22-position-management-design.md) §6.4, audit rows B4, B9.

**Repository: `main/`.** Branch `main-position-consumer`, cut from `experimental_imp_2` (after plan 5/9 merges), merged back into it.

**Scope:** `main/mq/position_consumer.py`, `main/position/position.py`, `main/robots/robot.py`, `main/trader.py`, `main/tests/`, `main/scripts/`.

**Depends on:** plan 5/9 merged (with main/'s own order path live there would be two fill sources and §6.4's single-`Position` design would not hold), and plan 4/9's **golden fixtures** — `crates/mq_gateway/tests/fixtures/*.json`, copied into `main/tests/fixtures/wire_v2/`. Coding against the fixtures rather than against a reading of the spec is what lets this plan proceed in another repository and another language without guessing.

## Readiness review

Verified against the code on `layer-implementation` @ `ff2938d` and `live-trade-ops` @ `e45dc05` (2026-09-25).

🟢 **green** — exists in the system, small update · 🟡 **yellow** — in the spec, small code change · 🟠 **orange** — in the spec, large code change · 🔴 **red** — in neither code nor spec

### 🟢 Green

| Item | Where it is today | Change |
|---|---|---|
| `Position` facade over `LongPosition`/`ShortPosition` | `main/position/position.py` | one method added |
| `BasePosition` — `_record_change`, `drain_changes`, `set_stop_loss`, `finalize`, `avg_price_open`, `is_stop_loss_triggered`, `is_target_reached`, `check_stop_open`, `direction_profit`/`_loss` | `main/position/base_position.py` | the consumers of the synced average; unchanged |
| The `IndicatorPublisher` shape this module copies — pure builder + socket in `__init__` | `main/mq/indicator_publisher.py` | a template, not a dependency |
| `trader.py`'s degrade-to-`None` path and `Robot`'s no-op handling | `trader.py`, `robots/robot.py` | the same pattern for a second optional component |
| `scripts/e2e_indicator_broadcast.py` | `main/scripts/` | the model for the round-trip script, incl. `--cold` and never-`down -v` |

### 🟡 Yellow

`mq/position_consumer.py` — `parse_position_event` and `PositionConsumer` · `request_snapshot` · fixture copying.

### 🟠 Orange

| Item | Why it is large |
|---|---|
| `sync_from_executor` | lands on the facade **and** both subclasses, must interact correctly with `_record_change`, and must not touch `executed_open`/`executed_open_amount` — the no-drift test is the whole justification for a setter over a synthetic fill |
| `Robot` tick integration + divergence detection | three divergence cases, a heartbeat that must not produce a warning storm, and a no-consumer path that behaves exactly as 5/9 left it |
| `scripts/e2e_position_round_trip.py` | drives two compose projects and asserts across both |

### 🔴 Red

| Item | Status |
|---|---|
| **Where in the tick the sync is applied** | This plan places it after the strategy step and before `drain_changes()`, so an executor action recorded this tick reaches the action log this tick. The spec does not say. It is a **material ordering decision** — the other order delays every executor-driven action by one tick. **Spec amendment: one line in §6.4.** |
| `PositionEvent` dataclass shape, `request_snapshot` naming | implementation detail; no amendment needed |

---

## Global Constraints

- **main/ does not track fills** (§6.4). No `record_entry_fill`/`record_exit_fill` from this path, no per-trade rows, no fee arithmetic. Per-fill data is not on the wire at all — this is "never sent", not "sent and discarded".
- **main/ tracks a position for exactly two reasons**, and every rule follows from them: (1) record actions so position levels can be visualised; (2) hold `avg_price_open` so risk can be recomputed and strategies can run against the price actually paid.
- **Telemetry must never block or crash the trading path** (`16b22c3`). `zmq` imported inside `__init__`, never at module level; a missing pyzmq degrades to no consumer with a warning, exactly as `IndicatorPublisher` already does in `trader.py`.
- **Unknown is skipped, never raised.** An unknown `event` or `schema > 2` logs once per kind and is dropped.
- **Commit only after explicit user confirmation.**

---

## Docker Entry Points

```bash
docker compose run --rm --no-deps live python3 -m pytest tests/ -q
docker compose run --rm --no-deps live python3 -m pytest tests/test_position_consumer.py -q

# End-to-end against a running executor stack (see Layer 4)
python3 scripts/e2e_position_round_trip.py
python3 scripts/e2e_position_round_trip.py --cold
```

Verified: [ ] baseline green on the branch before Layer 1.

---

## Layer 1: Pure decode

### Task 1.1: `parse_position_event`

**Files:** create `mq/position_consumer.py`; `tests/test_position_consumer.py`; fixtures copied to `tests/fixtures/wire_v2/`.

**Interface:**
```python
@dataclass(frozen=True)
class PositionEvent:
    schema: int; pair: str; position_id: str | None; event: str
    decision_id: str | None; reason: str | None
    status: str; side: str | None
    net_size: float; target_size: float
    avg_entry_price: float | None; avg_exit_price: float | None
    stop_loss_price: float | None; take_profit_price: float | None
    realized_pnl: float | None; unrealized_pnl: float | None
    settlement_complete: bool; ts: str

def parse_position_event(raw: dict) -> PositionEvent: ...
```

**Unit tests (RED):** **one test per golden fixture**, asserting a full decode — this is the cross-repo contract and deserves a test per message kind, not one loop with a smoke assertion. Plus: `schema: 3` → skipped with one log line, not raised; an unknown `event` → same; a missing required field → skipped with a log naming the field; a `null` `avg_entry_price` on an `opening` event decodes as `None` rather than `0.0` (a zero average entry price would silently poison every risk calculation downstream); prices decode without float-rounding a value the executor sent exactly.

**Constraints:** mirrors `build_indicator_update`'s shape — a pure function, fully unit-testable with no socket. No `zmq` import in this module's top level.

**Layer 1 gate:** `pytest tests/test_position_consumer.py -q` green in Docker. Commit: `feat(mq): wire v2 position event decoder`.

---

## Layer 2: The socket

### Task 2.1: `PositionConsumer`

**Interface:**
```python
class PositionConsumer:
    def __init__(self, connect_addr: str) -> None: ...          # imports zmq HERE
    def poll(self, timeout_ms: int = 0) -> list[PositionEvent]: ...
    def request_snapshot(self, pair: str | None = None) -> None: ...   # sends position_query
    def close(self) -> None: ...
```

**Unit tests (RED):** `poll` returns immediately with `[]` when nothing is queued (non-blocking — it runs on the 1 s trading tick); it drains everything queued in one call; a malformed frame is skipped and polling continues; a socket error is logged and swallowed, never raised into the tick; constructing without pyzmq raises `ImportError` **only** from `__init__` (the module still imports), which `trader.py` then guards.

### Task 2.2: Wiring in `trader.py`

**Unit tests (RED):** no pyzmq → `position_consumer = None`, a warning naming the address, and trading continues; `Robot` treats `None` as a complete no-op; the address comes from the same env-var convention as `MQ_EXECUTOR_ADDR`.

**Layer 2 gate:** full `pytest tests/ -q` green. Commit: `feat(mq): position consumer socket, degrading without pyzmq`.

---

## Layer 3: Applying it to `Position`

### Task 3.1: `Position.sync_from_executor`

**Files:** `position/position.py`, `position/base_position.py`, `tests/test_position_sync.py`.

**Interface:**
```python
def sync_from_executor(self, status: str, side: str | None, net_size: float,
                       avg_entry_price: float | None, stop_loss_price: float | None,
                       take_profit_price: float | None, realized_pnl: float | None) -> bool: ...
```
Returns whether anything changed.

**Unit tests (RED):**
- `avg_price_open()` returns the executor's `avg_entry_price` after a sync (§6.4 purpose 2).
- **Repeated syncs with the same value do not drift.** Call it five times with `avg_entry_price = 15.015` and assert `avg_price_open()` is still exactly that. This is the test that justifies a replace-in-place setter over `record_entry_fill(net_size, avg)`: the latter appends to `executed_open`/`executed_open_amount` and re-averages against its own previous output.
- `executed_open` / `executed_open_amount` are **not** appended to by this method at all (assert their length is unchanged) — main/ tracks no fills.
- `price_stop_loss` tracks a `sl_moved` sync; `is_stop_loss_triggered`, `is_target_reached`, `check_stop_open`, `direction_profit`/`direction_loss` all compute against the synced average (§6.4 purpose 2, named explicitly because these are the callers that matter).
- A sync that changes status, side, average price or either level **records a change** through `_record_change`, visible in `drain_changes()` (§6.4 purpose 1).
- A sync that changes nothing records nothing (§5.1's rule, applied here).
- A `closed` sync with `settlement_complete: true` takes the executor's `realized_pnl`; with `false` it falls back to `(avg_close/avg_open − 1) − 2×fee` and logs **which it used**.

### Task 3.2: `Robot` integration and divergence

**Files:** `robots/robot.py`, `tests/test_robot_position_sync.py`.

**Unit tests (RED):**
- `Robot` keeps opening and closing `self.position` from its strategy exactly as before; those calls express intent.
- Consumer events are applied on the existing tick, after the strategy step, before `drain_changes()` — so an executor action recorded this tick reaches the action log this tick.
- **Divergence**: the executor reporting a position for a pair main/ thinks is flat (and the reverse, and a side mismatch) logs at `WARNING` with **both** states and increments a counter. Three separate tests, one per case.
- No heartbeat-driven `WARNING` storm: a `state_update` heartbeat matching main/'s view logs nothing.
- No consumer configured → every one of the above is a no-op and the robot behaves exactly as plan 5/9 left it.

**Layer 3 gate:** full `pytest tests/ -q` green. Commit: `feat(robot): mirror executor position state onto main/'s Position`.

---

## Layer 4: End-to-end

### Task 4.1: `scripts/e2e_position_round_trip.py`

**Files:** `main/scripts/e2e_position_round_trip.py`, modelled on the existing `scripts/e2e_indicator_broadcast.py` (same `--cold` restart handling, same compose-path discovery, same never-`down -v` rule).

**Interface:** drives the executor stack through one position (paper or `no_trade` with a wiremock exchange), then asserts, per spec §10: main/ decoded **every** event kind at least once; main/'s `Position` matches the executor's `/api/positions` row on side, net size and average entry price; `request_snapshot` from a freshly constructed consumer returns the live position.

**Constraints:** side effects match the existing probe's — `--cold` restarts the executor stack, never `down -v`; the database survives.

**Layer 4 gate:** the script passes against a locally running stack. Commit: `test(e2e): position round trip from executor to main/`.

---

## Done when

- [ ] Every layer gate green in Docker, in order.
- [ ] Spec acceptance criteria satisfied here: "main/ receives and decodes every event kind … main/'s `Position` — filled from the consumer — matches the executor's `/api/positions` row".
- [ ] `main-position-consumer` merged into `experimental_imp_2` (after user confirmation).
