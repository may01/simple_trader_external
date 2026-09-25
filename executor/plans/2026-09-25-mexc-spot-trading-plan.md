# MEXC trading connector 5/5 — MEXC spot trading (L0-b, L0-c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Index: [2026-09-25-mexc-connector-index-plan.md](2026-09-25-mexc-connector-index-plan.md).

**Goal:** MEXC spot trades correctly: string ids, exits that are not rejected, real fills and fees, correct market info and tradability, account-wide open orders, a server-offset clock, a spot error table, and push fills over the user-data stream. The venue has no exchange-side stop, so it advertises `native_stop = false` and leaves the rest to 4/5.

**Spec:** F1, F4, F5, F7, F8, §3 (spot column), §5.1 (margin → `None`), §6 whole, §8 spot rows, §9; review items R1, R12, R13, R21, and the spot parts of R5.

**Scope:** `crates/exchange_adapter_mexc` (spot files: `spot.rs`, `dto.rs`, `endpoints.rs`, `lib.rs`, `ws.rs` user stream, `errors.rs` spot rows, `proto/`), `crates/live_trade_ops` (new spot scenario). **No** futures (3/5), **no** execution / orchestrator (4/5).

**Depends on:** 2/5 merged. 1/5's captures (exchangeInfo, selfSymbols, order/test, openOrders, client-id limit, user-stream subscribe ack).

**Branch:** `mexc-spot`, cut from `mexc-trading-connector`.

---

## Readiness review

Verified against `layer-implementation` @ 165afdb.

| Item | Today | Target | Size |
|---|---|---|---|
| `orderId` | parsed as `u64` (`dto.rs:84-86`) | string, encoded `s:{symbol}:{id}` | 🟢 |
| `reduce_only=true` | `InvalidRequest` (`spot.rs:209-215`): **every exit fails** | accepted, not sent | 🟢 |
| Market info | reads Binance filters MEXC does not send (`spot.rs:378-395`); status accepts `"1"`/`"ENABLED"`/`"TRADING"` | F5 mapping + `selfSymbols` + `tradeSideType` | 🟡 |
| Open orders | called without `symbol` (`spot.rs:306-309`) | correct per F8; keep, add paging guard | 🟢 |
| `get_order_fills` | not overridden (`NotSupported`) | `myTrades` | 🟡 |
| `get_order_by_client_id` | absent | `origClientOrderId` | 🟢 |
| `get_fees` | reads flat fields | `data` envelope | 🟢 |
| Clock | local `now_ms()` (`http.rs:121,171`) | `ServerClock` from `/api/v3/time` | 🟢 |
| `margin()` | `Some(SpotStyleAccount{kind: Margin})` stub (`lib.rs:317-319`) | `None` | 🟢 |
| `classify` | 401/403 + "insufficient balance" text | spot rows of spec §8 | 🟡 |
| Account updates | poll-and-diff 3 s | user-data stream + poll fallback | 🟠 |
| Spot live scenario | none | `run_spot_scenario` | 🟡 |

---

## Global constraints

- **No silent rounding.** Off-tick price / off-step qty → `InvalidRequest`.
- **Two spellings, one field:** parse `cumulativeQuoteQty` and `cummulativeQuoteQty` with a serde alias until the captured fixture settles it; then keep only the captured one.
- **Unknown status strings are errors**, never guessed (`Network("unparsed: status …")` + `UNMAPPED`).
- **Never retry** `POST /api/v3/order` or `DELETE /api/v3/order`.
- One commit per layer, green in Docker, after user confirmation.

---

## Docker Entry Points

```bash
docker compose run --build --rm test cargo test -p exchange_adapter_mexc
docker compose run --build --rm test cargo test -p live_trade_ops
docker compose run --build --rm test                          # layer gate

# M1 / M2 (human-gated)
docker compose run --build --rm --env-file configs/live-trade-ops/mexc.spot.mainnet.env test \
  cargo test -p live_trade_ops --test live_trade_ops live_spot_trade_ops -- --ignored --nocapture --test-threads=1
```

Verified: [ ] baseline green on `mexc-spot` at its cut point.

---

## Layer 1 (L0-b): orders

### Task 1.1: String ids, clock, buckets, `classify` spot rows

**Files:** `dto.rs`, `http.rs`, `spot.rs`, `errors.rs`.

**Integration test → order journal (RED):** `mexc_spot_order_survives_restart`: wiremock MEXC spot; place through `JournaledAccount` → id `s:LINKUSDT:06a4…`; a fresh adapter **and** a fresh journal (no in-memory cache) cancel it by the stored id, and the `DELETE /api/v3/order` carries `symbol=LINKUSDT&orderId=06a4…`. (Acceptance 3, offline half.)

**Unit tests (RED first):**
- `orderId` as string and as the `C02__…` form; a numeric JSON `orderId` still parses (the docs' query example shows one) and is stored as its string.
- Signed requests use `ServerClock::now_ms()`; offset from `/api/v3/time` (`serverTime`), refreshed every 10 min and after 700003.
- IP bucket 300 / 10 s at 70 %, per-endpoint weight (`myTrades` 10, `tradeFee` 20, `openOrders` 3, `order/test` 1, others per docs); order bucket 12 / s at 70 % for place + cancel.
- One test per spot `classify` row (spec §8): 700001/700002/10072/700006 → `AuthFailed`; 700007/30020 → `PermissionDenied`; 700003 → `ClockSkew`; 10101/30004/30005 → `InsufficientBalance`; 30002/30029/30032 → `InvalidQuantity`; 30016/30018/30019 → `MarketClosed`; 30014/730001/700004/700005/700008/730002 → `Unknown`; -2011 → `OrderNotFound`; HTTP 429 → `RateLimited`.

### Task 1.2: `place_order`, `cancel_order`, `get_order`

**Unit tests (RED first), wiremock:**
- Limit: `symbol, side, type=LIMIT, quantity, price, newClientOrderId`; off-tick / off-step → `InvalidRequest`, no request sent. Market: `type=MARKET, quantity`, no `quoteOrderQty`.
- **`reduce_only=true` is accepted and absent from the request** (regression test for today's `InvalidRequest`).
- `OrderKind::Stop` → `NotSupported` before any request.
- Client id > the limit 1/5 captured (32 unless refuted) or outside `[A-Za-z0-9_-]` → `InvalidRequest`.
- 2xx with an unparseable body → `Network("accepted-but-unparsed: …")`.
- Cancel decodes symbol and raw id from the `OrderId`; a `f:`/`p:` id → `InvalidRequest`.
- `get_order`: the five statuses; `PARTIALLY_CANCELED` → Cancelled; unknown status → error + `UNMAPPED`; `avg_fill_price = cumulativeQuoteQty / executedQty`, `None` at zero.

### Task 1.3: `get_order_fills`, `get_order_by_client_id`

**Integration test → `settle` (RED):** `mexc_spot_fills_settle_with_base_asset_fee`: a buy whose `myTrades` rows charge `commission` in the **base** asset, plus a sell charging quote. `exchange_adapter::settle` produces the net base delta and `fee_in_quote` as the live-trade-ops rules say, and position-management's `settlement_complete` goes true.

**Unit tests (RED first):** `myTrades symbol&orderId` field mapping (`id`, `price`, `qty`, `quoteQty`, `commission`, `commissionAsset`, `isMaker`, `time`); `realized_pnl = None`; fee `0` with empty `commissionAsset` → fee 0 in the quote asset; order older than one month → the rows that exist, no error; `get_order_by_client_id` → `GET /api/v3/order?symbol&origClientOrderId`; -2011 / "order does not exist" → `Ok(None)`.

### Task 1.4: `get_account_state`, `get_market_info`, `get_fees`

**Unit tests (RED first), captured fixtures:**
- Account: `balances[]` → balances; `openOrders` with **no** `symbol` → all open orders, ids encoded with each order's own symbol; `positions` empty.
- Market info: `tick_size = 10^-quotePrecision`; `lot_size = baseSizePrecision` (quantity string); `min_notional = max(quoteAmountPrecision, quoteAmountPrecisionMarket)`; `trading_status` Trading iff `status=="1"` && `isSpotTradingAllowed` && `tradeSideType==1` && symbol in `selfSymbols`: one test per failing condition → `Halted`; `selfSymbols` cached 1 h.
- Fees: `data.makerCommission` / `data.takerCommission`.

### Task 1.5: Margin → `None`, capabilities, NOTES

- [ ] `ExchangeAdapter::margin()` returns `None` on MEXC; delete the spot-endpoint reuse. Test: `margin().is_none()`.
- [ ] `capabilities()` spot: `can_place_orders` true, `native_stop` false, `reduce_only_enforced` false, `can_short` false, `order_fills` true, `client_id_lookup` true, `account_push` false (true after Layer 2).
- [ ] Stop using `order_cache.rs` for spot; delete the file if 3/5 has merged.
- [ ] `NOTES.md`: delete §2 (margin; it also cites the legacy docs), the spot parts of §4, and anything else this layer closes.

---

## Layer 2 (L0-b): live spot scenario (M1)

### Task 2.1: `run_spot_scenario`

**Files:** `live_trade_ops/src/spot_scenario.rs` (new), `registry.rs`, `tests/live_trade_ops.rs` (`live_spot_trade_ops`, `#[ignore]` + `LIVE_TRADE_OPS=1`).

**Interface:**
```rust
// same shape as run_futures_scenario / run_margin_scenario
pub async fn run_spot_scenario(adapter: Arc<dyn ExchangeAdapter>, journal: Arc<dyn OrderJournal>,
                               ctx: RunCtx) -> RunReport;
```
Steps: `s0` preconditions (market info Trading, quote balance ≥ `LIVE_MAX_NOTIONAL`); `s1` limit buy at the touch, wait for the fill; `s2` `get_order_fills` + `settle`; `s3` stop step → `Skipped("native_stop=false")` when the capability is false; `s4` limit sell `reduce_only=true`, sized `min(filled net of fee, free base)`; `s5` flat and settled; `s6` cleanup (cancel anything left, journal touched rule).

**Unit tests (RED first):** offline run against the fake with the `mexc_spot` capability profile: all steps pass; `s3` is `Skipped`; a fee charged in base makes `s4` sell less than `s1` bought; `LIVE_REQUIRE_ALL=1` turns the skip into a failure (existing D8 rule).

### Task 2.2: Run M1 (human-gated)

- [ ] Operator go; run; report `external/executor/runs/<date>-mexc-m1.md`; commit captures; mark confirmed `classify` rows; acceptance 5 (`settlement_complete: true`).

---

## Layer 3 (L0-c): user-data stream

### Task 3.1: `subscribe_account_updates` on spot

**Interface:** unchanged trait method; internally a `SpotUserStream`: `POST /api/v3/userDataStream` → `listenKey`; `PUT` every 30 min; `DELETE` on shutdown; ws `wss://wbs-api.mexc.com/ws?listenKey=…`; `{"method":"SUBSCRIPTION","params":["spot@private.orders.v3.api.pb","spot@private.deals.v3.api.pb","spot@private.account.v3.api.pb"]}`; protobuf schemas vendored beside the existing `proto/` files.

**Integration test → `run_fill_sync` (RED):** a local ws fake pushes an order update for a tracked order; position-management's fill sync wakes and calls `get_order` before its 2 s poll would have (the stream is a hint; `get_order` stays the authority).

**Unit tests (RED first):** orders → `OrderUpdate` (`s:` id, client id, cumulative qty, avg price, status); deals → `OrderUpdate` wake-up; account → `BalanceUpdate`; keepalive failure → new key + reconnect; proactive reconnect at 23 h; ping `{"method":"PING"}` every 20 s, idle 45 s → reconnect (`MEXC_PING_INTERVAL`, `MEXC_IDLE_TIMEOUT`); 5 failures → `FeedDisconnected`; poll-and-diff runs while the stream is down and never leaves a gap; `capabilities().account_push` true.

### Task 3.2: Run M2 (human-gated)

- [ ] M1 again with the stream up; the report shows every fill seen on push before the poll. Report `external/executor/runs/<date>-mexc-m2.md`.
- [ ] `NOTES.md` §1b (poll-and-diff) rewritten as "fallback only". Layer gate green; commit after confirmation.
