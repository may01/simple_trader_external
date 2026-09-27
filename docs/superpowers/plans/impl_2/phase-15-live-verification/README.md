# Phase 15 — Live Operation Verification

**Goal:** Prove the live trading path works end-to-end against the **real Binance mainnet margin account**, driven by the Phase-14 test EMA strategies, using small real trades (**30–50 USDT notional**). Verify every stock operation required by the specification — `buy`, `sell`, `get_order`, `get_info`, `borrow`, `repay` — and verify that the live Robot, given the test EMA strategies, places real margin orders and records the resulting actions.

**Why this phase exists:** Phases 01–14 built and unit/integration-tested every layer against **mock** stocks. Nothing has been run against the real exchange, and the live entry point (`trader.py`) registers **zero strategies** — so the live Robot currently does nothing. This phase closes the two wiring gaps and then verifies the real path with hands-on, money-on-the-line runs.

This phase **extends existing layers** — it adds no new bottom layer. It is the last verification gate before the live path can be trusted.

> ⚠️ **REAL FUNDS.** Tasks 02 and 03 place real orders and take real margin loans on a live Binance account. Every step is bounded to a hard cap of **`LIVE_POSITION_USDT ≤ 50`**, executed manually op-by-op, with resting orders cancelled and every borrow repaid. Do not automate these into CI. Do not raise the cap.

---

## Requirements covered

| # | Requirement | Task |
|---|-------------|------|
| 1 | `buy` operation implemented and working on mainnet (`trade(TRADE_BUY, …)`) | 02 |
| 2 | `sell` operation implemented and working on mainnet (`trade(TRADE_SELL, …)`) | 02 |
| 3 | `get_order` implemented and working (`order_info(order_id)`) | 02 |
| 4 | `get_info` implemented and working (`info()`) | 02 |
| 5 | `borrow` implemented and working on real margin | 02 |
| 6 | `repay` implemented and working on real margin | 02 |
| 7 | Live Robot runs the test EMA strategies and places real orders | 01, 03 |
| 8 | Live actions recorded (`Action` records: open / close / fill) | 03 |

**Operation name → method mapping** (spec name on the left, code method on the right):

| Spec name | Method | Notes |
|-----------|--------|-------|
| `buy` | `Stock_Binance.trade(TRADE_BUY, price, amount)` | LIMIT GTC, margin |
| `sell` | `Stock_Binance.trade(TRADE_SELL, price, amount)` | LIMIT GTC, margin |
| `get_order` | `Stock_Binance.order_info(order_id)` | returns status + amounts + rate |
| `get_info` | `Stock_Binance.info()` | symbol / exchange info |
| `borrow` | `Stock_Binance.borrow(coin, amount)` | margin loan |
| `repay` | `Stock_Binance.repay(coin, amount)` | margin repay |

---

## Dependencies

- **Phase 14 must be merged into `experimental_imp_2` first.** The EMA strategies and factory live in `strategies/test_factory.py` (`EmaStrategyFactory`), `strategies/strategy_test_1_long.py`, `strategies/strategy_test_1_short.py` — produced by Phase 14, not yet in the base branch.
- A funded Binance **margin** account with API key/secret that permit margin trading + borrowing.

---

## Docker Entry Points (ground truth — defined before any layer)

```bash
# Live trading with the EMA test strategies, small real position.
# STRATEGY_SET selects the live factory; LIVE_POSITION_USDT caps notional.
STRATEGY_SET=ema LIVE_POSITION_USDT=40 \
  docker compose run --rm \
    -e STRATEGY_SET -e LIVE_POSITION_USDT \
    live python3 trader.py

# Manual stock-operation verification harness (real margin, ≤50 USDT).
docker compose run --rm live python3 scripts/verify_stock_ops.py
```

These commands are the contract. Implementation must make them work. `trader.py` must register the EMA strategies when `STRATEGY_SET=ema` and size every order to `LIVE_POSITION_USDT`.

Verified (mainnet, manual): [ ] `verify_stock_ops.py` runs all 6 ops (`buy`, `sell`, `get_order`, `get_info`, `borrow`, `repay`) and prints a PASS line for each
Verified (mainnet, manual): [ ] `trader.py` with `STRATEGY_SET=ema` places a real margin order on a natural EMA cross and writes a matching `Action` record

---

## Layer order for this phase

```
Strategy / factory (Phase 14)     ← REUSED: EmaStrategyFactory — no new strategies
  ↓
Execution / trader entry (Ph 10)  ← Task 01: wire STRATEGY_SET + LIVE_POSITION_USDT into trader.py
  ↓
Stock abstraction (Phase 01)      ← Task 02: verify all 6 ops on real mainnet margin
  ↓
Execution / Robot (Phase 10)      ← Task 03: live run, natural EMA cross, real order + Action
```

---

## Phase integration boundary

**Automated (CI, mock, no creds):** the existing mock integration test stays GREEN — it is the regression gate for the wiring change in Task 01.

```bash
docker run --rm -v "$PWD":/code -w /code simple_trader \
  python3 -m pytest tests/integration/test_stock_operations.py -q
```

**Manual (mainnet, real money):** Tasks 02 and 03 are verified by hand via the `Verified:` checkboxes above and in each task. They are **not** added to CI — they need live credentials, real funds, and (Task 03) an unbounded wait for a natural EMA cross.

---

## Key design decisions

- **No testnet.** Binance spot testnet has no margin/`borrow`/`repay` endpoints, so it cannot verify the spec's margin operations. Verification runs on **mainnet** with a hard small-notional cap instead.
- **Hard notional cap.** All real trading is bounded by `LIVE_POSITION_USDT` (≤ 50). Task 01 makes this the single sizing knob for the live path; there is no other place that sets `full_position` for live.
- **No new strategies or signals.** The live path reuses `EmaStrategyFactory` exactly as Phase 14 built it. Phase 15 only wires it into `trader.py`.
- **Mock stays the CI gate.** Real-exchange runs are inherently manual and non-deterministic; the mock integration test remains the automated regression boundary.
- **Manual op-by-op for Task 02.** Each of the 6 operations is exercised and asserted individually so a failure is attributable to one method, not a tangled sequence.
- **Repay every borrow.** Any `borrow` in verification is immediately followed by `repay` of the same amount; the harness asserts the loan returns to zero.

---

## Tasks

| Task | File | Produces |
|------|------|----------|
| 01 | `task-01-live-strategy-wiring.md` | `trader.py` reads `STRATEGY_SET` + `LIVE_POSITION_USDT`; README drift fix |
| 02 | `task-02-stock-ops-mainnet-verification.md` | `scripts/verify_stock_ops.py` + manual checklist for all 6 ops |
| 03 | `task-03-live-actions-verification.md` | Live mainnet run, natural EMA cross, real order + `Action` record |
