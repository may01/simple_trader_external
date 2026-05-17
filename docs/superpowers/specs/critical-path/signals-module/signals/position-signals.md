# Position Signals Specification

**Source file:** `signals_lib/position_signals.py`  
**Category:** Position-state signals — gate strategies based on current trade state

These signals read position state from `data` directly instead of reading indicator columns. They allow signal chains to be gated on whether a position is open, what type it is, or what state it is in.

Both signals inherit from `BaseSignal`.

---

## Signal Overview

| Signal | Logic | Use case |
|--------|-------|----------|
| `PositionState_Signal(state)` | `data.get_position_state() == state` | Gate chain on specific state machine phase |
| `PositionType_Signal(type)` | `data.get_position_type() == type` | Gate chain on long vs short vs no position |

---

## `PositionState_Signal(param)`

**Logic:** Fires when the current position state machine state equals `param`.

```python
data.get_position_state() == self.state
```

**Parameters:**
- `param` — one of the `POSITION_STATE_*` constants from `helpers.py`:
  - `POSITION_STATE_WAIT` — no position open
  - `POSITION_STATE_WAIT_BUY` — waiting for buy fill (short entry)
  - `POSITION_STATE_WAIT_SELL` — waiting for sell fill (long entry)
  - `POSITION_STATE_WAIT_SAFETY_BUY` — partial buy-to-cover (short)
  - `POSITION_STATE_WAIT_SAFETY_SELL` — partial sell (long)

**Note:** Reads position state from `data` (the legacy `data` object passed to `check()`). In the v2 architecture, position state is owned by the Position module and accessed via `position.get_state()`. This signal depends on the `data` object exposing `get_position_state()`, which is a compatibility method.

**Example:**
```python
PositionState_Signal(POSITION_STATE_WAIT)  # Only fire when no position is open
```

---

## `PositionType_Signal(param)`

**Logic:** Fires when the current position type equals `param`.

```python
data.get_position_type() == self.type
```

**Parameters:**
- `param` — one of the `POSITION_TYPE_*` constants:
  - `POSITION_TYPE_UNKNOWN` — no position / neutral
  - `POSITION_TYPE_LONG` — long position open
  - `POSITION_TYPE_SHORT` — short position open

**Example:**
```python
PositionType_Signal(POSITION_TYPE_LONG)  # Currently in a long position
```

---

## Design Notes

- These signals access position state via the `data` argument (not via `data_point.get()`), which couples them to the legacy data object interface rather than the `DataPoint` protocol.
- They are typically used as the first signal in a chain to gate execution — e.g. `PositionState_Signal(POSITION_STATE_WAIT)` as chain step 0 ensures the chain only advances when idle.
- `StrategyManager` already provides position-state gating via `check_conditions()` in each strategy, so these signals are primarily useful inside signal chains that need finer-grained position-state logic.
