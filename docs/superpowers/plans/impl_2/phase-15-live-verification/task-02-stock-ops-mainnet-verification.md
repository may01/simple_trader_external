# Task 02: Stock Operations — Mainnet Margin Verification

**Phase:** 15 — Live Operation Verification
**Depends on:** Task 01 (live wiring), Phase 01 (`Stock_Binance` order methods)
**Produces:** `scripts/verify_stock_ops.py` — a manual, attended harness that exercises all six required operations against the **real Binance mainnet margin account** with a hard ≤50 USDT cap, plus a verification checklist.

> ⚠️ **REAL FUNDS.** This harness places real LIMIT orders, takes a real margin loan, and repays it. Run it attended. It must never exceed `LIVE_POSITION_USDT` (≤50). It cancels every order it places and repays every coin it borrows.

---

## Goal

Prove each spec operation works against the live exchange, individually and attributably:

| Spec op | Method exercised |
|---------|------------------|
| `buy` | `stock.item.trade(TRADE_BUY, price, amount)` |
| `sell` | `stock.item.trade(TRADE_SELL, price, amount)` |
| `get_order` | `stock.item.order_info(order_id)` |
| `get_info` | `stock.item.info()` |
| `borrow` | `stock.item.borrow(coin, amount)` |
| `repay` | `stock.item.repay(coin, amount)` |

---

## Context

All order methods use the Binance **margin** API (`create_margin_order`, `get_margin_order`, `cancel_margin_order`, margin `borrow`/`repay`). On mainnet these are fully available — which is why mainnet, not testnet, is the verification target.

Order amount is derived from notional and price: `amount = usdt_notional / price`, with `usdt_notional` capped at 50. `is_invalid_amount(amount, price)` already enforces Binance LOT_SIZE / MIN_NOTIONAL (it checks `2×` minimums); a 30–50 USDT notional clears these on the configured pair.

To exercise `buy`/`sell` **without risking a fill**, place LIMIT orders far from the market (buy well below best bid; sell well above best ask), confirm via `order_info`, then `cancel_order`. To exercise `borrow`/`repay`, take a tiny coin loan and immediately repay the same amount, asserting the loan returns to zero.

---

## Files

- Create: `scripts/verify_stock_ops.py`

---

## Harness behaviour (`scripts/verify_stock_ops.py`)

Reads `LIVE_POSITION_USDT` (default 40, clamp ≤50). Resolves coin/base/pair from the same env `Stock_Binance` already uses (`PAIR`). Calls `do_stock_init("binance")`. Runs the operations in this order, printing one `PASS:` / `FAIL:` line per op, and exits non-zero on any failure:

1. **get_info** — `status, _ = stock.item.info()` returns symbol/exchange info. PASS if it returns without exception and contains the configured symbol.
2. **get depth / reference price** — `asks, bids = stock.item.depth(100)`; derive `best_ask`, `best_bid`. Used to price the non-filling orders.
3. **buy (non-filling)** — price = `best_bid * 0.80` (well below market), `amount = usdt / price`. `status, res = stock.item.trade(TRADE_BUY, price, amount)`. PASS if `status == STATUS_SUCCESS` and `res["order_id"]` non-empty. Keep `order_id`.
4. **get_order** — `status, info = stock.item.order_info(order_id)`. PASS if `status == STATUS_SUCCESS`, `info["status"]` in `{"NEW","PARTIALLY_FILLED"}`, and `start_amount` > 0.
5. **cancel buy** — `stock.item.cancel_order(order_id)`; PASS if final status is `"CANCELED"`. (Cleanup — not one of the 6 spec ops, but required so the resting buy never fills.)
6. **sell (non-filling)** — price = `best_ask * 1.20` (well above market), `amount = usdt / price`. `status, res = stock.item.trade(TRADE_SELL, price, amount)`. PASS on success; record `order_id`; then **cancel** it the same way as step 5.
7. **borrow** — pick a tiny coin amount worth ~`usdt` at market (`amount = usdt / best_ask`, but no more than `get_aviable_loan` allows). `status, got = stock.item.borrow(coin, amount)`. PASS if `status == STATUS_SUCCESS` and `got > 0`.
8. **repay** — `status, repaid = stock.item.repay(coin, amount)`. PASS if `status == STATUS_SUCCESS`. Then re-query the loan (`get_aviable_loan` / margin account) and assert the outstanding loan for `coin` is back to its pre-test level (≈ 0 added).

End with a summary table (op → PASS/FAIL). Any unhandled exception or any resting order left open is a FAIL.

Hard guards:
- Refuse to run if `usdt > 50`.
- Refuse to run if `STOCK_TYPE`/init is not `binance` (no point verifying mainnet ops against a mock — but allow a `--dry-run` that prints intended calls without sending them).
- Every placed order is cancelled before exit, even on failure (wrap in try/finally).
- Every borrow is repaid before exit, even on failure.

---

## Key constraints

- This script is **manual / attended only**. Do not import it into any pytest collection or CI path.
- Use only the public `Stock_Binance` interface (`trade`, `order_info`, `cancel_order`, `info`, `depth`, `borrow`, `repay`, `get_aviable_loan`, `funds`) — no raw `client` calls. The point is to verify the abstraction, not bypass it.
- Non-filling prices (0.80× / 1.20×) must still satisfy `is_invalid_amount` and exchange price filters; if a placement is rejected for being too far from market on the configured pair, narrow the offset but never to a level that risks an immediate fill.
- `borrow` amount must not exceed `get_aviable_loan(coin)`.

---

## Verification

```bash
# Dry run first — prints intended calls, sends nothing.
docker compose run --rm live python3 scripts/verify_stock_ops.py --dry-run

# Real run — attended, real funds, ≤50 USDT.
LIVE_POSITION_USDT=40 docker compose run --rm -e LIVE_POSITION_USDT \
  live python3 scripts/verify_stock_ops.py
```

**Live result (mainnet LINKUSDT, 10 USDT, attended) — 5/6 PASS.** Harness reordered to borrow-before-sell (commit `37cad3b`) so the loaned coin funds the sell test (no pre-held inventory needed). Two live-only bugs were fixed first (commit `c37b9d0`): `taker_base_vol`/`buy_volume` drop and the `MIN_NOTIONAL`→`NOTIONAL` filter rename.

Verified (mainnet, manual): [x] `get_info` returns exchange/symbol info
Verified (mainnet, manual): [ ] `buy` places a real margin LIMIT order — **BLOCKED on this account**: Binance `-3087` caps LINK pledged collateral (max transfer 1.266 LINK), while min-notional needs ≥1.58 LINK; no non-filling size satisfies both. Account/collateral issue, not code. Needs a pair without a maxed collateral cap, or freed LINK collateral.
Verified (mainnet, manual): [x] `get_order` reports the order as NEW/PARTIALLY_FILLED with correct amounts (on the sell order)
Verified (mainnet, manual): [x] `sell` places a real margin LIMIT order (funded by the borrowed coin)
Verified (mainnet, manual): [x] `borrow` takes a real margin loan
Verified (mainnet, manual): [x] `repay` returns the loan to its pre-test level
Verified (mainnet, manual): [x] all placed orders cancelled, no residual loan (buy never placed; sell cancelled; loan repaid)

---

## Commit

`feat: add mainnet margin stock-operation verification harness`
