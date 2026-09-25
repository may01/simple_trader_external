# MEXC trading connector 3/5 — MEXC futures trading (L0-d, L0-e) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Index: [2026-09-25-mexc-connector-index-plan.md](2026-09-25-mexc-connector-index-plan.md).

**Goal:** Move the MEXC futures adapter from the legacy surface to the current API and make it trade correctly. That means orders in contracts, not base quantity; a resting plan-order stop; real fills, open orders, `FuturesOps` and error mapping; and, last, websockets for the book, trades and private push.

**Spec:** F2, F7, F8, §3 (futures column), §7 whole, §8 futures rows, §9 (hosts, rate budget), D5; review items R3, R4, R5, R6, R9, R11 (adapter side), R14, R15, R25, R29.

**Scope:** `crates/exchange_adapter_mexc` (futures files: `futures.rs`, `dto_futures.rs`, `endpoints.rs`, `config.rs`, `http.rs`, `ws.rs`, `errors.rs` futures rows), `crates/live_trade_ops` (futures scenario stop steps, `risk.rs` MEXC branch). **No** execution / orchestrator changes (4/5), **no** spot (5/5).

**Depends on:** 2/5 merged (string `OrderId`, `Capabilities`, `get_order_by_client_id`, `PermissionDenied`, `ServerClock`, MEXC codec / bucket / `classify` skeleton). 1/5's **D2 verdict = Confirmed** (futures order permission works); fixtures from 1/5 in `tests/fixtures/captured/`.

**Branch:** `mexc-futures`, cut from `mexc-trading-connector`.

---

## Readiness review

Verified against `layer-implementation` @ 165afdb.

| Item | Today | Target | Size |
|---|---|---|---|
| Host | `contract.mexc.com` (`config.rs:76`) | `api.mexc.com` REST; ws stays `contract.mexc.com/edge` | 🟢 |
| Place | `order/submit`, numeric id (`endpoints.rs:40`, `futures.rs:173-177`) | `order/create`, string id | 🟡 |
| `Recv-Window` | 5000 (ms) (`http.rs:203`) | seconds, ≤ 60 | 🟢 |
| `qty` → `vol` | passed through (NOTES §3) | `qty / contractSize`, step-checked | 🟡 |
| `lot_size` | `volUnit` (`futures.rs:307-309`) | `volUnit × contractSize` | 🟢 |
| Stop | `NotSupported` (`futures.rs:132-139`); no plan-order code | `planorder/place/v2` | 🟠 |
| Open orders | always empty | paged account-wide | 🟡 |
| `get_order_fills` | not overridden | `order/deal_details` | 🟡 |
| `FuturesOps` | absent for MEXC | six methods | 🟠 |
| Leverage / margin mode | `extra["default_leverage"]`, `extra["margin_mode"]` | per-pair settings set through `FuturesOps` | 🟡 |
| 510 rate limit | lands in `Unknown` | `RateLimited` | 🟢 (2/5 feeds the code) |
| Futures ws | none (NOTES §1) | public depth/deal + private login | 🟠 |
| `LiqCalc` golden dispatcher | `"binance"` arm only (`risk.rs:~369`) | + `"mexc"` arm | 🟡 |
| Futures scenario | steps 0–6 + F1–F7, **no stop step** | + plan-order stop steps | 🟡 |

---

## Global constraints

- **Every path, field and code is from `mexc.com/api-docs` or a capture.** A wiremock fixture is a captured file when one exists, otherwise marked `// from docs`.
- **All arithmetic is `Decimal`.** `vol` must be an exact multiple of `volUnit` and ≥ `minVol`; otherwise `InvalidRequest`, never rounding.
- **The rest of the system sees base quantity only.** Every inbound `vol` is multiplied by `contractSize` at the dto boundary.
- **`positionMode=2` (one-way) on every order and plan order.** The adapter never changes the account's mode.
- **Never retry a POST** that places or cancels.
- One commit per layer, green in Docker, after user confirmation.

---

## Docker Entry Points

```bash
docker compose run --build --rm test cargo test -p exchange_adapter_mexc
docker compose run --build --rm test cargo test -p live_trade_ops
docker compose run --build --rm test                         # layer gate

# M3 (human-gated)
docker compose run --build --rm --env-file configs/live-trade-ops/mexc.futures.mainnet.env test \
  cargo test -p live_trade_ops --test live_trade_ops live_futures_trade_ops -- --ignored --nocapture --test-threads=1
```

Verified: [ ] baseline green on `mexc-futures` at its cut point.

---

## Layer 1 (L0-d): transport migration

### Task 1.1: Host, signing, `Recv-Window`, clock, buckets

**Files:** `config.rs`, `endpoints.rs`, `http.rs`, `lib.rs`.

**Interface:** no public change. Internal: `endpoints::FUTURES_*` constants for every §7 path; `FuturesHttp` holds a `ServerClock` (refreshed from `GET /api/v1/contract/ping` every 10 min) and one `TokenBucket` per endpoint group: `order/create` + `planorder/*` 4 / 2 s; `order/get`, `order/list/open_orders`, `order/cancel`, `planorder/cancel`, `order/external` 20 / 2 s; `change_leverage` 10 / 10 s; others 20 / 2 s.

**Integration test → REST (RED):** `futures_signed_post_hits_current_api` (wiremock): a place request goes to `/api/v1/private/order/create` on the configured base URL, with `Recv-Window: 5` for `recv_window_ms = 5000`, `Request-Time` = clock time, and `Signature` = HMAC over `accessKey + timestamp + raw JSON body`.

**Unit tests (RED first):** `recv_window_ms` 5000 → `"5"`, 1 → `"1"` (ceil), 70 000 → `"60"` (cap); GET signs sorted `&`-joined params; null params excluded from the signature; clock offset applied; bucket exhaustion → `RateLimited` with no request sent; `success:false, code:510` → `RateLimited`; `ClockSkew` alert when `|offset| > recv_window / 2`.

### Task 1.2: `classify` futures rows

**Files:** `errors.rs`.

**Unit tests (RED first):** one test per futures row in spec §8 (602, 401, 402, 406 → `AuthFailed`; 701/702/704/200005/200006/300000/300001 → `PermissionDenied`; 2005; 2008/2009/2043; 2040; 2041; 2006/2019/2021; 2003/2004; 2007; 2011/2015; 1001/1002; 510/2037 → `RateLimited`; 2016/2013/2030/2042/3001–3004 → `Unknown` with code and message kept). An unknown code → `Unknown`, and the live runner logs `UNMAPPED Mexc <code>`.

**Constraints:** every row stays marked "from docs" in a comment until a capture confirms it (spec §8); 1/5's captures confirm some at once.

---

## Layer 2 (L0-d): contract metadata, market info, fees, `FuturesOps`

### Task 2.1: Contract cache and unit conversion

**Interface (crate-internal):**
```rust
pub(crate) struct ContractSpec { pub contract_size: Decimal, pub vol_unit: Decimal, pub min_vol: Decimal,
    pub max_vol: Decimal, pub price_unit: Decimal, pub min_leverage: u32, pub max_leverage: u32,
    pub state: u8, pub api_allowed: bool, pub base: String, pub quote: String, pub risk: RiskLadderSpec }
pub(crate) async fn contract(&self, symbol: &str) -> Result<ContractSpec, AdapterError>; // cached 1 h
pub(crate) fn qty_to_vol(spec: &ContractSpec, qty: Decimal) -> Result<Decimal, AdapterError>;
pub(crate) fn vol_to_qty(spec: &ContractSpec, vol: Decimal) -> Decimal;
```

**Unit tests (RED first):** `qty_to_vol` exact multiple → Ok; off-step → `InvalidRequest`; below `minVol` → `InvalidRequest`; above `maxVol` → `InvalidRequest`; `contractSize` 0.1 / 1 / 10; cache hit within 1 h, refresh after; `contractSize` change on refresh → `WARN` logged; the path is the one 1/5 confirmed (`/contract/detail` or `/contract/detail/country`); `state` 0 with `apiAllowed` false → treated as not tradable.

### Task 2.2: `get_market_info`, `get_fees`, `get_extended_market_data`

**Unit tests (RED first), wiremock on captured fixtures:** `tick_size = priceUnit`; `lot_size = volUnit × contractSize`; `min_notional = minVol × contractSize × fairPrice` (fair price from `fair_price/{symbol}`); `trading_status` `Trading` iff `state == 0 && apiAllowed`, `Halted` for states 1–4; `get_fees` from `account/tiered_fee_rate/v2` (`realMakerFee`, `realTakerFee`); extended data unchanged except the host.

### Task 2.3: `FuturesOps` for MEXC

**Interface:** `impl FuturesOps for MexcFutures` (the six existing trait methods, `exchange_adapter/src/ops.rs:108+`), exposed by `ExchangeAdapter::futures_ops()`. Plus `impl PermissionProbe for MexcFutures` (trait defined by 2/5 Task 1.3), exposed by `ExchangeAdapter::permission_probe()`: `order/create` with `vol=0`, result stored in the `can_place_orders` flag (spec §5.2 step 3).

**Integration test → live_trade_ops futures scenario (RED):** the offline futures scenario (fake transport replaying MEXC fixtures) runs F1 `set_leverage(5)`, F5 over-max leverage → `LeverageNotAllowed`, and F6 margin-type change with an open position → `MarginModeChangeBlocked`, all through `futures_ops()`.

**Unit tests (RED first):**
- `set_leverage`: no position → two `change_leverage` calls (`positionType` 1 and 2) with the stored `openType`; open position → one call with `positionId`; read back through `position/leverage`, both entries must equal `l`, else `Unknown`; outside `[minLeverage, maxLeverage]` → `LeverageNotAllowed` with no request; code 2019 → `LeverageNotAllowed`.
- `set_margin_type`: same type → `Ok(())`; other type with an open position or open orders (from `open_positions` / `open_orders`) → `MarginModeChangeBlocked` with no request; otherwise the stored `openType` changes and `change_leverage` is re-issued.
- `is_hedge_mode`: 1 → true, 2 → false.
- `position_risk`: field mapping (`holdVol × contractSize`, `openAvgPrice`, `liquidatePrice`, `im`, `oim`, `positionType` 1/2 → Buy/Sell); `maint_margin` derived from the ladder; none → `Ok(None)`.
- `futures_margin_summary`: `total_initial_margin = positionMargin + frozenBalance`.
- `leverage_brackets`: `riskLimitCustom` present → used verbatim; absent → derived tiers (bound per 1/5's capture); `BY_VALUE` → no `price_ref`; `cum = 0`.
- `probe_order_permission`: validation refusal → `true`; 704 / 200005 / 200006 / 300000 / 300001 → `false`; **returned order id → cancel sent at once, `Err`**.
- A permission refusal on any later order sets the flag false and fires one `Severity::Critical` alert.

**Constraints:** remove `extra["default_leverage"]` and `extra["margin_mode"]` (`lib.rs:140-148`). A pair with no stored settings → `place_order` returns `InvalidRequest("leverage not set")`.

---

## Layer 3 (L0-d): orders

### Task 3.1: `place_order` Limit / Market

**Unit tests (RED first), wiremock:** side-code table, all four combinations (Buy/Sell × `reduce_only`): 1 / 3 open, 2 / 4 close; `type` 1 limit, 5 market; `positionMode=2`; `reduceOnly: true` only on closes; `leverage` only on opens; `openType` from stored settings; `externalOid` = client id, > 32 chars → `InvalidRequest` with no request; `vol` converted; returned id encoded `f:{symbol}:{id}` from a **string** `orderId`; 2xx with an unparseable body → `Network("accepted-but-unparsed: …")`.

### Task 3.2: `place_order` Stop → plan order

**Unit tests (RED first):** `OrderKind::Stop` → `POST planorder/place/v2` with: close side code (long stop 4, short stop 2); `triggerType` 2 for a long stop (≤), 1 for a short stop (≥); `trend` from `extra["stop_trigger_trend"]` (default 2 = fair); `orderType` 5 when `price` is `None`, 1 with `price` when `Some`; `executeCycle` 2; `positionMode` 2; `reduceOnly` true; returned id `p:{symbol}:{id}`; a Stop with `reduce_only == false` → `InvalidRequest` (a stop is always a close here).

### Task 3.3: `cancel_order`, `get_order`, `get_order_fills`, `get_order_by_client_id`

**Unit tests (RED first):**
- Cancel `f:` → `order/cancel`, body shape as captured by 1/5 / M3 (`{"orderIds":[…]}` or a bare array); per-item `errorCode` 2040 → `OrderNotFound`, 2041 → `OrderNotCancellable`. Cancel `p:` → `planorder/cancel [{symbol, orderId}]`.
- `get_order(f:)`: state 1/2 → New (2 with `dealVol > 0` → PartiallyFilled), 3 → Filled, 4 → Cancelled, 5 → Rejected; `dealVol × contractSize`; `dealAvgPrice`.
- `get_order(p:)`: `planorder/list/orders` with `page_num`, `page_size=100`, `start_time = now − 8 d`, `end_time = now`, filtered by id, paging on while full pages return. State 1 → New, 2 → Cancelled, 3 → the spawned order's status via `order/get/{orderId}`, 4 → Cancelled, 5 → Rejected (message carries `errorCode`). Not found in the window → `OrderNotFound`.
- `get_order_fills(f:)`: `deal_details` mapping; `isTaker` or `taker`; `quote_qty = price × qty` (derived); `profit` → `realized_pnl`. `get_order_fills(p:)` → the spawned order's deals; untriggered → empty.
- `get_order_by_client_id` → `order/external/{symbol}/{externalOid}`; not found → `Ok(None)`.
- Decoding a `s:` id on the futures account → `InvalidRequest`.

### Task 3.4: `get_account_state`

**Unit tests (RED first):** `account/assets` → balances; `open_positions` → positions (base qty); `order/list/open_orders?page_num&page_size=100` → paged, all pages read; plan orders not included (documented).

### Task 3.5: Capabilities, NOTES, cache removal

- [ ] MEXC futures `capabilities()`: `native_stop`, `reduce_only_enforced`, `can_short`, `order_fills`, `client_id_lookup` → true; `account_push` false until Layer 6. Test updated.
- [ ] Stop using `order_cache.rs` for futures (the symbol is in the id). If 5/5 has already merged, delete the file.
- [ ] `NOTES.md`: delete §3 and §3b, and the futures parts of §1 and §4 closed here.

---

## Layer 4 (L0-d): live wiring for M3

### Task 4.1: Futures scenario stop steps and MEXC `LiqCalc`

**Files:** `live_trade_ops/src/futures_scenario.rs`, `live_trade_ops/src/risk.rs`, `tests/fixtures/futures_liq_golden.json`.

**Interface:** new scenario steps after the position opens: `F8` place stop (`OrderKind::Stop`, trigger ~3 % away) → `get_order` New; `F9` move stop (cancel + re-place) → old Cancelled, new New; `F10` close reduce-only → flat, then cancel the stop → Cancelled. Steps skip with `Skipped(native_stop=false)` when the capability is false (so Binance margin reports them honestly). `risk.rs`: a `"mexc"` arm in the golden-row dispatcher, using MEXC's formula branch (no `cum`).

**Unit tests (RED first):** offline scenario with the MEXC fake: F8–F10 pass; with `native_stop=false` they report `Skipped`; the golden-row test fails loudly naming the missing MEXC row until M3 writes it, then passes within 0.5 %.

### Task 4.2: Run M3 (human-gated)

- [ ] Operator go. Run M3. Report to `external/executor/runs/<date>-mexc-m3.md`.
- [ ] Commit captures (order/create, planorder place/list/cancel, order/cancel, deal_details, open_orders) and replace the `// from docs` fixtures.
- [ ] Add the MEXC golden row. Mark the confirmed `classify` rows.

---

## Layer 5 (L0-e): public futures websocket

### Task 5.1: `subscribe_market_data` on futures

**Interface:** unchanged trait method; internally a `FuturesWs` client on `wss://contract.mexc.com/edge` with `sub.depth` (incremental, `version`-sequenced) and `sub.deal`, `{"method":"ping"}` every 15 s, `Backoff` and `FeedDisconnected` after 5 failures (reused from `ws.rs`). Klines stay REST.

**Integration test → `market_data` (RED):** a local ws fake serves a depth snapshot + increments + deals; `market_data`'s book builder consumes the stream and ends with the expected top of book.

**Unit tests (RED first):** version gap → resync through the existing `DepthSync` pattern; compressed pushes decoded (or `compress:false` sent, whichever 1/5 found to work); ping cadence; idle timeout 60 s → reconnect; `vol × contractSize` on every level and trade.

## Layer 6 (L0-e): private futures websocket

### Task 6.1: `subscribe_account_updates` on futures

**Interface:** same connection: `login` with `apiKey`, `reqTime`, `signature`, **`subscribe: false`**; on `rs.login` send `personal.filter` for `order`, `order.deal`, `position`, `asset`, `plan.order`; `rs.error` → `AuthFailed`.

**Unit tests (RED first):** order → `AccountEvent::OrderUpdate` with a `f:` id; plan.order → `OrderUpdate` with a `p:` id (wake-up only); order.deal → `OrderUpdate` wake-up; position → `PositionUpdate` (base qty); asset → `BalanceUpdate`; poll-and-diff still runs while the ws is down and stops duplicating once it is up; `capabilities().account_push` true.

- [ ] `NOTES.md` §1 futures ws paragraph deleted. Layer gate green; commit after confirmation.
