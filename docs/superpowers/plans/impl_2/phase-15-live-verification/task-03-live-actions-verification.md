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

`Robot.do()` → `StrategyManager.check()` → on `OPEN_LONG` / `OPEN_SHORT` → `Robot._open_position` → `_place_valid_order` → real `stock.trade(...)` and (short) `stock.borrow(...)`. Fills are reconciled in `Robot._process_executed_orders` → `position.record_entry_fill` / `record_exit_fill`.

`Action` is the Phase-14 record type, but it was **simulation-only** (`sim_id` field; assembled only by `TrainRobot`). The live `Robot` did not produce or persist any Action records — it only logged a "Trade finalized" line and updated `live_tracker.json`. **Resolved in this phase (added production wiring):** at the end of every `Robot.do()` tick, `Robot._record_live_actions()` drains `position.drain_changes()` and appends one `Action` (sim_id = `LIVE_SIM_ID` = 0) per lifecycle change to an append-only JSONL store, `LiveActionLog` (`robots/live_action_log.py`), at `shared_folder()/live_actions.jsonl`. This is what `scripts/tail_live_actions.py` tails. The change is backward compatible: `Robot(action_log_path=None)` keeps the old inert behaviour.

The EMA strategies use `5_ema_7` / `5_ema_14` on the live wide DataFrame; `LiveData` must already be producing those columns (Phase 03 / Phase 13 warmup). If the live dataset lacks the EMA columns at startup, the cross can never fire — verify the columns exist before waiting.

---

## Files

- Create: `robots/live_action_log.py` — `LiveActionLog` append-only JSONL store + `tail(n)` (production; the live Action store that did not previously exist).
- Modify: `robots/robot.py` — optional `action_log_path` ctor arg; `_record_live_actions()` drains `position.drain_changes()` into the store each tick.
- Modify: `trader.py` — pass `action_log_path=shared_folder()+"live_actions.jsonl"` so the live path persists Actions.
- Create: `scripts/tail_live_actions.py` — read-only `--preflight` (creds, EMA columns, size, 2 strategies) + tail of recent live `Action` records.
- Create: `tests/test_phase15_live_actions.py` — mock store round-trip + Robot recording wiring (Docker, no creds).

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
docker compose run --rm live python3 scripts/tail_live_actions.py --preflight

# Live run — attended, real funds, EMA strategies, ≤50 USDT
STRATEGY_SET=ema LIVE_POSITION_USDT=40 \
  docker compose run --rm -e STRATEGY_SET -e LIVE_POSITION_USDT \
    live python3 trader.py
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

### Live-path bugs found by pre-flight (fixed)

The first real pre-flight run (read-only, no orders) caught two live-only defects — the live path had never run before this phase:

1. **`KeyError('1_buy_volume')`** — `Stock_Binance.get_candles_history` dropped `taker_base_vol` in both the `tf == base_min` column select and `_resample_to_tf`, so `LiveData.build_candles` could not derive `{tf}_buy_volume` and the volume indicator crashed. Fixed by preserving `taker_base_vol` through both paths (commit `c37b9d0`).
2. **Every order rejected** — `is_invalid_amount` looked up only the `MIN_NOTIONAL` filter, but Binance renamed it to `NOTIONAL`; the lookup returned `None` and flagged all amounts invalid, which would block every live trade. Fixed by accepting `NOTIONAL` or `MIN_NOTIONAL` (commit `c37b9d0`).

Both are covered by mock unit tests in `tests/unit/stock_abstraction/`.

Verified (mainnet, read-only): [x] pre-flight passes — live creds, EMA columns present, size tradeable, 2 strategies registered
Verified (mainnet, manual): [ ] a natural EMA cross fires the strategy and the Robot places a real margin order
Verified (mainnet, manual): [ ] the fill is processed — `Position` reflects the entry, `LiveOrderTracker` cleared/updated
Verified (mainnet, manual): [ ] an `Action` record is written describing the open (and close, if observed)
Verified (mainnet, manual): [ ] at shutdown: no open position, no residual margin loan

---

## Commit

`feat: add live-action pre-flight/tail helper and verification procedure`
