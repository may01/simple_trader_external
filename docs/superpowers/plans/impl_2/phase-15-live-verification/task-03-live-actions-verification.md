# Task 03: Live Actions — EMA Strategy Execution Verification

**Phase:** 15 — Live Operation Verification
**Depends on:** Task 01 (live wiring), Task 02 (ops proven in isolation)
**Produces:** A documented, attended live run proving the Robot — driven by the test EMA strategies — places a **real** margin order on a natural EMA cross and records the resulting `Action`. Plus a small observability assertion so the run is checkable.

> ⚠️ **REAL FUNDS, UNBOUNDED WAIT.** This run trades real money on a live margin account and waits for a *natural* EMA-7/EMA-14 cross on the configured pair — which may take hours. Run it attended, capped at `LIVE_POSITION_USDT ≤ 50`, and stop it once one full open→close (or one open + manual close) is observed.

---

## Goal

Close the loop: the live `trader.py` path, with `STRATEGY_SET=ema`, must

1. run the live polling loop against real Binance data,
2. fire `StrategyTest1Long` / `StrategyTest1Short` on a real EMA crossover,
3. place a real margin order sized to `LIVE_POSITION_USDT`,
4. process the fill via `LiveOrderTracker` and update `Position`,
5. produce an `Action` record describing what happened.

This is the natural-cross path chosen during design — no forced or replayed signals.

---

## Context

`Robot.do()` → `StrategyManager.check()` → on `OPEN_LONG` / `OPEN_SHORT` → `Robot._open_position` → `_place_valid_order` → real `stock.trade(...)` and (short) `stock.borrow(...)`. Fills are reconciled in `Robot._process_executed_orders` → `position.record_entry_fill` / `record_exit_fill`. `Action` records are the Phase-14 record type assembled when a position transitions.

The EMA strategies use `5_ema_7` / `5_ema_14` on the live wide DataFrame; `LiveData` must already be producing those columns (Phase 03 / Phase 13 warmup). If the live dataset lacks the EMA columns at startup, the cross can never fire — verify the columns exist before waiting.

---

## Files

- No new production module required if Task 01 + Phase 14 are in place.
- Optional: a small read-only `scripts/tail_live_actions.py` that prints the most recent `Action` records from the live persistence/action store, so the observer can confirm a record was written without stopping the bot.

---

## Pre-flight checks (before the unbounded wait)

Run these first so a multi-hour wait is not wasted on a misconfiguration:

1. `do_stock_init("binance")` succeeds with live creds.
2. The live wide DataFrame contains `5_ema_7` and `5_ema_14` (non-NaN on closed candles). Print the latest two values of each so the observer can see how close a cross is.
3. `LIVE_POSITION_USDT` resolves to a value in [30, 50]; `is_invalid_amount(usdt/price, price)` is `False` at the current price (the size is tradeable).
4. The EMA strategies are registered: `len(strategy_manager.strategies) == 2`.

---

## Procedure

```bash
# Pre-flight (no trading)
docker compose run --rm trader python3 scripts/tail_live_actions.py --preflight

# Live run — attended, real funds, EMA strategies, ≤50 USDT
STRATEGY_SET=ema LIVE_POSITION_USDT=40 \
  docker compose run --rm -e STRATEGY_SET -e LIVE_POSITION_USDT \
    trader python3 trader.py
```

Watch the logs. When `5_ema_7` crosses `5_ema_14`, the Robot should log an open, place a real order, and (on fill) record an entry. Confirm the `Action` was written (tail the action store). Let it run to the opposite cross for a close, **or** stop after a confirmed open + fill and close the position manually via the Task-02 harness if a natural close is impractical. Either way, ensure no position and no loan are left open at the end.

---

## Key constraints

- Natural cross only — do not lower thresholds or inject synthetic candles for this task.
- Hard cap `LIVE_POSITION_USDT ≤ 50` (enforced in Task 01 code).
- The run is attended; never leave the live bot unsupervised with an open position or outstanding margin loan.
- Short entries take a real `borrow`; confirm the matching `repay` happens on close (Robot short-close path) or repay manually before exit.

---

## Verification

Verified (mainnet, manual): [ ] pre-flight passes — live creds, EMA columns present, size tradeable, 2 strategies registered
Verified (mainnet, manual): [ ] a natural EMA cross fires the strategy and the Robot places a real margin order
Verified (mainnet, manual): [ ] the fill is processed — `Position` reflects the entry, `LiveOrderTracker` cleared/updated
Verified (mainnet, manual): [ ] an `Action` record is written describing the open (and close, if observed)
Verified (mainnet, manual): [ ] at shutdown: no open position, no residual margin loan

---

## Commit

`feat: add live-action pre-flight/tail helper and verification procedure`
