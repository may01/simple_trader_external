# Task 02: ExampleStrategyLong and ExampleStrategyShort

**Phase:** 07 — Strategy  
**Depends on:** Task 01 (Strategy base), Phase 04-05 (signals)  
**Produces:** `strategies/example_strategy_long.py`, `strategies/example_strategy_short.py` — minimal reference implementations for pipeline validation

---

## Goal

Implement `ExampleStrategyLong` and `ExampleStrategyShort` — minimal strategies that exercise the full Strategy interface without any sophisticated trading logic. Purpose: validate the OPEN → fill → CLOSE → finalize pipeline end-to-end. Not for production use.

---

## Context

These strategies exist solely to confirm the plumbing works: that signal chains fire, that position opens, that close signals fire, and that finalize produces a P&L number. Signal logic is intentionally trivial (CCI crossover). Not tuned for profitability.

---

## Files

- Create: `strategies/example_strategy_long.py`
- Create: `strategies/example_strategy_short.py`

---

## ExampleStrategyLong

**`register_signals()`:**
- Create one `SignalChain("long_entry", STRATEGY_ACTION_OPEN_LONG, tf=15)` with single signal: `Cross_Up_Val_Signal(15, "cci_14", -100)` — fires OPEN_LONG when CCI crosses above -100
- Create one `SignalChain("long_exit", STRATEGY_ACTION_CLOSE_LONG, tf=15)` with single signal: `Cross_Down_Val_Signal(15, "cci_14", 100)` — fires CLOSE_LONG when CCI crosses below 100
- Add both chains to `self.signals`

**`check_conditions(data_point, position_state, action_msg) -> bool`:**
- Always returns True — position rejects incompatible actions

**`get_open_price()`, `get_close_price()`, `get_stop_loss_price()`:**
- All delegate to base class defaults

---

## ExampleStrategyShort

**`register_signals()`:**
- `SignalChain("short_entry", STRATEGY_ACTION_OPEN_SHORT, tf=15)` with `Cross_Down_Val_Signal(15, "cci_14", 100)` — OPEN_SHORT when CCI crosses below 100
- `SignalChain("short_exit", STRATEGY_ACTION_CLOSE_SHORT, tf=15)` with `Cross_Up_Val_Signal(15, "cci_14", -100)` — CLOSE_SHORT when CCI crosses above -100

**`check_conditions(data_point, position_state, action_msg) -> bool`:**
- Always returns True — position rejects incompatible actions

**Price methods:** Delegate to base class defaults.

---

## Key Constraints

- These are NOT production strategies — do not optimize signal thresholds
- Both strategies operate on `tf=15` — 15-minute candle signals
- Signal chains are single-step (one signal per chain) — intentionally minimal for pipeline validation
- `check_conditions()` always returns True — incompatible action rejection is the position's responsibility
- Base class default prices are sufficient — no override needed

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from strategies.example_strategy_long import ExampleStrategyLong
from strategies.example_strategy_short import ExampleStrategyShort
from constants import POSITION_STATE_WAIT

s_long = ExampleStrategyLong(fee=0.001)
s_short = ExampleStrategyShort(fee=0.001)

# check_conditions passes when WAIT
assert s_long.check_conditions(None, POSITION_STATE_WAIT, None) == True
assert s_short.check_conditions(None, POSITION_STATE_WAIT, None) == True

print('example strategies ok, chains:', len(s_long.signals.chains), len(s_short.signals.chains))
"
```

---

## Commit

`feat: implement ExampleStrategyLong and ExampleStrategyShort pipeline validators`
