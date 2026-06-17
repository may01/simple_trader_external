# Task 01: Test strategies (EMA cross + RSI zone) long & short

**Phase:** 14 — Simulation Wiring
**Depends on:** Phase 04 (Cross_Up_Signal, Cross_Down_Signal, Cross_Up_Val_Signal, Cross_Down_Val_Signal), Phase 05 (SignalChain/SignalManager), Phase 07 (Strategy base, StrategyManager)
**Produces:** `strategies/strategy_test_1_long.py`, `strategy_test_1_short.py`, `strategy_test_2_long.py`, `strategy_test_2_short.py`, `strategies/test_factory.py`

---

## Goal

Four concrete test strategies that fire real OPEN/CLOSE signals over the prepared dataset, plus a picklable factory that registers them. These exercise the full pipeline with non-trivial entry/exit logic (unlike `ExampleStrategy*`, which only validates plumbing).

---

## Context

All four strategies operate on `tf=5` (5-minute candles). They reuse existing signal primitives — **no new signal classes**. `zone_class` is the integer RSI tier `0..4` (0 = oversold, 4 = overbought) from `indicators/library/classification.py`, read via `data_point.get("zone_class", 5, 0)`. Half-integer thresholds turn "leaves oversold" / "enters overbought" into existing value-crossover checks.

These are test strategies for pipeline validation and chart inspection — not tuned for profit.

---

## Files

- Create: `strategies/strategy_test_1_long.py`
- Create: `strategies/strategy_test_1_short.py`
- Create: `strategies/strategy_test_2_long.py`
- Create: `strategies/strategy_test_2_short.py`
- Create: `strategies/test_factory.py`

---

## Interface

All strategies subclass `Strategy(fee: float)` and override only `register_signals()` and `check_conditions()`. Price methods delegate to base-class defaults.

**`StrategyTest1Long`** — EMA cross
- `register_signals()`:
  - `SignalChain("t1_long_entry", STRATEGY_ACTION_OPEN_LONG, tf=5)` with `Cross_Up_Signal(5, "ema_7", "ema_14")`
  - `SignalChain("t1_long_exit", STRATEGY_ACTION_CLOSE_LONG, tf=5)` with `Cross_Down_Signal(5, "ema_7", "ema_14")`

**`StrategyTest1Short`** — EMA cross (mirror)
- `SignalChain("t1_short_entry", STRATEGY_ACTION_OPEN_SHORT, tf=5)` with `Cross_Down_Signal(5, "ema_7", "ema_14")`
- `SignalChain("t1_short_exit", STRATEGY_ACTION_CLOSE_SHORT, tf=5)` with `Cross_Up_Signal(5, "ema_7", "ema_14")`

**`StrategyTest2Long`** — RSI zone_class
- `SignalChain("t2_long_entry", STRATEGY_ACTION_OPEN_LONG, tf=5)` with `Cross_Up_Val_Signal(5, "zone_class", 0.5)` — leaves oversold (prev `0` → cur `≥1`)
- `SignalChain("t2_long_exit", STRATEGY_ACTION_CLOSE_LONG, tf=5)` with `Cross_Up_Val_Signal(5, "zone_class", 3.5)` — enters overbought (cur `== 4`)

**`StrategyTest2Short`** — RSI zone_class (mirror)
- `SignalChain("t2_short_entry", STRATEGY_ACTION_OPEN_SHORT, tf=5)` with `Cross_Down_Val_Signal(5, "zone_class", 3.5)` — leaves overbought (prev `4` → cur `≤3`)
- `SignalChain("t2_short_exit", STRATEGY_ACTION_CLOSE_SHORT, tf=5)` with `Cross_Down_Val_Signal(5, "zone_class", 0.5)` — enters oversold (cur `== 0`)

`check_conditions(data_point, position_state, action_msg) -> bool` — all return `True` (position rejects incompatible actions).

**`strategies/test_factory.py`**
- `class TestStrategyFactory:` — picklable (same pattern as `_DefaultStrategyFactory`), `__init__(self, fee: float)`, `__call__(self) -> StrategyManager` registers all four test strategies into a fresh `StrategyManager(fee)` and returns it.

---

## Key Constraints

- `tf=5` everywhere — column names resolve as `5_ema_7`, `5_ema_14`, `5_zone_class`.
- Reuse existing crossover signals only — adding a new signal class for zone transitions is a NO; the half-integer threshold trick is intentional and must be commented.
- `zone_class` is integer-valued; thresholds at `0.5` / `3.5` are robust to the discrete tiers. Do not assume float tiers.
- `TestStrategyFactory` must be a top-level class (picklable across `ProcessPoolExecutor`) — never a closure.
- Long and short strategies coexist in the same `StrategyManager`; `StrategyManager._resolve` already handles competing OPENs (returns NOTHING on conflict) — do not special-case here.
- Not production strategies — do not tune thresholds.

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from strategies.test_factory import TestStrategyFactory
from strategies.strategy_test_1_long import StrategyTest1Long
sm = TestStrategyFactory(0.001)()
assert len(sm.strategies) == 4
s = StrategyTest1Long(fee=0.001)
assert len(s.signals.chains) == 2
print('test strategies ok:', [type(x).__name__ for x in sm.strategies])
"
```

---

## Commit

`feat: add EMA-cross and RSI-zone test strategies (long/short) with picklable factory`
