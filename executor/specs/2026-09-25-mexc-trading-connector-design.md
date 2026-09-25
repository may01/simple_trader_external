# MEXC trading connector — every exchange function the executor needs — Design Spec

Date: 2026-09-25
Status: **draft**, decisions D1–D5 taken 2026-09-25 (§4, the recommended option in each case). Revised 2026-09-25: F2 corrected against MEXC's current docs (`mexc.com/api-docs`), see §2. **Reviewed 2026-09-25 (§15)**: every claim re-checked against the code (`layer-implementation` @165afdb plus the uncommitted position-management work in that worktree) and against the current MEXC docs. Findings R1–R29 resolved in place by adopting the recommended option. §15 is the log.
Target project: `trade_executor` (Rust; worktree `.worktrees/layer-implementation`, which currently has branch `position-management` checked out with uncommitted work), crate `exchange_adapter_mexc` plus small common-layer changes in `exchange_adapter`, `execution` and `orchestrator`
Reference implementation: `exchange_adapter_binance` (live-trade-ops §4 and position-management §3 as built against it)
Predecessors: [2026-09-06-mexc-spot-market-data-websocket-design.md](2026-09-06-mexc-spot-market-data-websocket-design.md) (market data, done), [2026-09-22-live-trade-ops-l0-test-design.md](2026-09-22-live-trade-ops-l0-test-design.md) §4.6 (MEXC error plumbing, done; table left to "MEXC's own spec" — this one), [2026-09-22-position-management-design.md](2026-09-22-position-management-design.md) (the consumer)

---

## 1. Why this exists

Binance is the only exchange the executor can trade on. MEXC is wired in `orchestrator/src/main.rs` (`EXCHANGE=mexc`) and has real market data, but its trading surface was built with no credentials and no network, and several documents defer the rest to "MEXC's own spec":

- live-trade-ops §4.6 — MEXC's `RejectReason` table;
- live-trade-ops-remaining §4 — `get_order_fills`, `MarginOps`, `FuturesOps` still on their defaults;
- position-management §3.5, §9 — MEXC positions report `settlement_complete: false` because `get_order_fills` is `NotSupported`;
- TECH_DEBT §7 — `order_event.order_id` is `bigint`, MEXC spot ids are strings.

This spec lists every exchange function the executor uses to open, protect, monitor, close and reconcile a position (§3), says how MEXC provides each one, and specifies the work. It is also where three facts about MEXC's API are written down (§2), because they change what the executor can safely do on MEXC — not just how the adapter is coded.

## 2. Facts about MEXC that change the design

Checked on 2026-09-25 against MEXC's **current** docs, `https://www.mexc.com/api-docs/` (spot-v3 and futures). The first draft of this spec used the legacy GitHub Pages docs (`mexcdevelop.github.io/apidocs/…`), which are stale. F2 in particular was wrong there and is corrected below. The legacy site must not be used as a source for this work. **None of these facts has been checked against a live response.** Gate G0 (§10.1) confirms each one before any code depends on it.

| # | Fact | Consequence |
|---|---|---|
| F1 | **Spot has no stop order type that can be placed.** The Order Type enum (`spot-v3/public-api-definitions`) is `LIMIT`, `MARKET`, `LIMIT_MAKER`, `IMMEDIATE_OR_CANCEL`, `FILL_OR_KILL`, `STOP_MARKET_ORDER` — and the last one is marked **"Query only"**. `POST /api/v3/order` has no `stopPrice`/trigger parameter, and there is no OCO. | The exchange-side stop leg of the dual stop (main_goal.md: "a resting stop-loss … is always placed on the exchange itself") **cannot be placed on MEXC spot through the API**. A sell `LIMIT` below the market fills at once, so it is not a substitute. → D1. |
| F2 | **Futures trading is available, on a new API surface.** Current docs: host `https://api.mexc.com`. Orders go to `POST /api/v1/private/order/create` (4 req / 2 s; `orderId` returned as a **string**). Trigger orders go to `POST /api/v1/private/planorder/place/v2`. Position TP/SL goes to `POST /api/v1/private/stoporder/place`. Trailing orders exist too. The order-placement permission **requires the account to have completed KYC**. Signing: `ApiKey`, `Request-Time`, `Signature` = HMAC-SHA256(`accessKey + timestamp + paramString`). For GET/DELETE the params are sorted and `&`-joined; for POST the raw JSON body is signed. `Recv-Window` max 60 (s); default tolerance 10 s. *(The legacy docs' 2022 "under maintenance" notice on `order/submit` is superseded.)* | Futures is the MEXC path for shorts **and** for an exchange-side stop. The existing adapter targets the **legacy** surface (`contract.mexc.com`, `order/submit`, numeric `orderId`) and must be moved to the current one (§7). D2 is reduced to an account check: KYC done, and futures order permission enabled on the key. |
| F3 | **Margin API closed** (since 2023-04-14; current docs list no `/api/v3/margin/*`). Already recorded in `exchange_adapter_mexc/NOTES.md` §2. | Shorts on MEXC go through futures (F2). Spot is long-only. → D4. (Current docs still show no margin endpoints; G0 re-checks this.) |
| F4 | **Spot `orderId` is a string** (e.g. `"06a480e69e604477bfb48dddd5f0b750"`, or the `C02__…` form). `dto.rs:84-86` parses it as `u64`. | The **first live MEXC spot order fails to parse** after it has already been placed on the exchange. Today that surfaces as `AdapterError::Network("bad order response: …")` (`spot.rs`), which is the right variant, but the caller gets no id to track or cancel. `exchange_adapter::OrderId(u64)` cannot hold it. → D3. |
| F5 | **Spot `exchangeInfo` has no Binance-style `PRICE_FILTER`/`LOT_SIZE`/`MIN_NOTIONAL` filters** (the only filter is `PERCENT_PRICE_BY_SIDE`). Precision comes from `quotePrecision`, `baseAssetPrecision`, `baseSizePrecision` (min qty, a quantity string such as `"0.1"`), `quoteAmountPrecision` / `quoteAmountPrecisionMarket` (min notional, limit / market) and `maxQuoteAmount` / `maxQuoteAmountMarket`. Status is a string: `"1"` online, `"2"` pause, `"3"` offline. `isSpotTradingAllowed` = API trading allowed. `tradeSideType`: 1 all, 2 buy only, 3 sell only, 4 close. API tradability per key: `GET /api/v3/selfSymbols` (per user); `GET /api/v3/defaultSymbols` is the global list. | `get_market_info` needs its own mapping (§6.1). Today it reads Binance filters (`spot.rs:378-395`) and gets nothing. `TradingStatus::Trading` iff `status == "1"` && `isSpotTradingAllowed` && `tradeSideType == 1` && the symbol is in `selfSymbols` (R12). |
| F6 | **No testnet** for any kind. | Every live run is mainnet with real money. Covered by `live_trade_ops`' arming flag and notional cap, as for Binance margin. |
| F7 | **API keys with no bound IP expire after 90 days.** Max 10 IPs per key, 30 keys per account, 500 open orders per account, `recvWindow` ≤ 60 000 ms (spot, ms) / `Recv-Window` ≤ 60 (futures, **seconds**). Spot limits: **300 weight / 10 s per IP**, 500 / 10 s per UID, order place + cancel share a **UID bucket of 12 req/s**. Futures limits are per endpoint (e.g. `order/create` 4 / 2 s, `order/get` 20 / 2 s, `change_leverage` 10 / 10 s). Spot ws: 30 subscriptions per connection, connection valid **24 h** max, dropped after 30 s with no subscription / 60 s with no traffic. | Expiry is a silent production outage 90 days after deployment unless the key is IP-bound. It goes in the operator checklist (§9), and `AuthFailed` at boot fails closed. The limiter (§9) is per surface, not one shared bucket. |
| F8 | **Spot `GET /api/v3/openOrders` takes `symbol` as optional** (up to 5 comma-separated, ≤ 1000 orders returned, weight 3). Futures `GET /api/v1/private/order/list/open_orders` is account-wide and paginated (`page_num`, `page_size` ≤ 100). *(The first draft said spot requires `symbol`: wrong, R1.)* | Account-wide open orders exist on both surfaces. `get_account_state().open_orders` is one call on spot and a paged call on futures. No pair list is needed (§6.1, §7.2). The sub-account (§9) keeps foreign orders out. |

### 2.1 G0 results — live probe, 2026-09-25

The probe ran on the operator's MEXC account against `api.mexc.com` (branch `mexc-trading-connector` @ `1f90e31`): 28 requests, all answered. The redacted fixtures are in `crates/exchange_adapter_mexc/tests/fixtures/captured/`.

| # | Verdict | Evidence |
|---|---|---|
| F1 | **Confirmed** | `exchangeInfo` `orderTypes` for LINKUSDT = `LIMIT, MARKET, LIMIT_MAKER`. No stop type. |
| F2 | **Confirmed. Futures order permission granted** | `order/create` with `vol=0` → `{"success":false,"code":2011,"message":"Order quantity error"}`, a validation refusal. D2's prerequisites hold for this key. |
| F3 | **Confirmed** | `GET /api/v3/margin/isolated/account` → 400 `{"code":700011,"msg":"This interface is not allowed"}`. |
| F4 | Not yet observed | No order was placed. Confirmed when M3/M1 place one. |
| F5 | **Confirmed, with specifics** | `baseSizePrecision` = `"0.01"` is a **quantity step** (not a digit count), so `lot_size = 0.01`. `quoteAmountPrecision` = `"1"` is the **min notional in quote** (1 USDT). `quotePrecision` = 3 (digits), so `tick_size = 0.001`. `status` = `"1"`. `isSpotTradingAllowed` = true. `tradeSideType` = 1. LINKUSDT is in `defaultSymbols`. `filters` = `[PERCENT_PRICE_BY_SIDE bidMultiplierUp 0.2 / askMultiplierDown 0.2]`, the source of `PriceOutsideBand`. `selfSymbols` (R12) was **not** probed. |
| F7 | Partly confirmed | Client-id rule, verbatim from the live error: `^[0-9a-zA-Z_-]{1,32}$` (a 33-character id → 400 code `700008`). Not observed: key expiry, rate limits. |
| F8 / R1 | Consistent, not proven | `GET /api/v3/openOrders` without `symbol` → 200 `[]`. The account had no open orders, so this does not yet show that it lists every symbol. Re-check in M1 with an order resting. |

Answers to the capture-dependent items:

- Spot order by unknown client id → 400 `{"code":-2013,"msg":"Order does not exist."}`. §8's spot `-2011` row is **wrong**: the not-found code is `-2013` (same as Binance). `-2013` → `OrderNotFound` → `Ok(None)` in `get_order_by_client_id`.
- Futures order by unknown `externalOid` → **HTTP 200** `{"code":0,"success":true}` with **no `data`**. This is the "not found" shape, not an error. `get_order_by_client_id` maps an absent `data` to `Ok(None)`.
- Futures `order/create` with `vol=0` → `2011` "Order quantity error". §8's `2011` → `InvalidQuantity` is confirmed.
- `contract/detail` path: `GET /api/v1/contract/detail?symbol=LINK_USDT` answers 200 (R14 resolved; not `/country`).
- `tiered_fee_rate` (v1) answers 200 with data (`takerFee` 0, `makerFee` 0, `level` 9999). R15 still adopts `/v2`; L3 captures it.
- **`position_mode` = `1` = HEDGE.** The account is in hedge mode today. D10 makes that fatal at boot. **Operator action before M3/M5: switch MEXC futures to one-way.**
- `position/leverage` LINK_USDT: 20× on both sides, `openType` 1 (isolated), `mmr` 0.004, `imr` 0.005, `maxVol` 1 550 000, `level` 2.
- `contract/detail` LINK_USDT: **`contractSize` = 0.1** (qty ≠ vol: 1 vol = 0.1 LINK), `volUnit` 1, `minVol` 1, `priceUnit` 0.001, `maxLeverage` 300, `riskLevelLimit` 1 with every `riskIncr*` = 0 (a **single** bracket), `maintenanceMarginRate` 0.0023, `initialMarginRate` 0.00333333.
- Fees: spot LINKUSDT maker 0, taker 0.0005. Futures LINK_USDT maker 0 and taker 0 in both `contract/detail` and `tiered_fee_rate`.
- Clock offset (server − local): spot +437 ms, futures +126 ms. This host runs about 0.4 s behind MEXC, inside any recvWindow, but R8's `ServerClock` still applies.
- **Futures USDT wallet equity = 0.** Fund it (≥ 2 × `LIVE_MAX_NOTIONAL`) before M3.
- **Run 2 (complete §10.1 set, `5956b46`):** see [`runs/2026-09-25-mexc-g0.md`](../runs/2026-09-25-mexc-g0.md). It adds: **R15 confirmed**, API fees differ (`tiered_fee_rate/v2` real taker 0.0008 / maker 0.0006, where `contract/detail` says 0). **R29 confirmed**: `contract/detail/country` carries `riskLimitCustom` with 2 levels (230 000 vol at 300× / mmr 0.0023; 1 550 000 vol at 200× / mmr 0.004), so the derived single bracket is wrong for LINK_USDT. The spot user stream acknowledged all 3 private channels in one comma-separated `msg`. Futures ws login with `subscribe:false` → `rs.login` success. `selfSymbols` contains LINKUSDT. The STOP_MARKET_ORDER `order/test` is refused with `700004` (missing price) before the type is judged, so F1 rests on `orderTypes`.

## 3. Capability matrix — what the system calls, Binance reference, MEXC plan

"Consumer" means who calls it in production today (position-management design, `execution`, `orchestrator`) or in the live test (`live_trade_ops`).

| # | Function | Consumer | Binance (reference) | MEXC spot | MEXC futures (current API, F2) | MEXC today |
|---|---|---|---|---|---|---|
| C1 | `place_order` Limit | execution entry / exit / escalation | ✅ | `POST /api/v3/order type=LIMIT` | `order/create type=1` | spot ✅ but breaks on F4; futures targets the legacy `order/submit` path |
| C2 | `place_order` Market | cleanup, operator force-close | ✅ | `type=MARKET` + `quantity` | `type=5` | same as C1 |
| C3 | `place_order` **Stop** (resting protective leg) | execution, after the entry resolves to `Open` | ✅ `STOP_LOSS(_LIMIT)` / `STOP(_MARKET)` | ❌ **does not exist (F1)** → D1 | `planorder/place/v2` (§7.3) | `NotSupported` on both (no plan-order code exists) |
| C4 | `reduce_only` honoured | execution closes | futures ✅; margin not sent | accepted, not sent; enforced locally (§5.2, R21) | `side` 2/4 = close, plus `reduceOnly` | **spot rejects `reduce_only=true` with `InvalidRequest` (`spot.rs:209-215`), so every spot exit and stop fails today**; futures maps it to side 2/4 (`futures.rs:407-414`) |
| C5 | `cancel_order` | execution: stop replace, exit escalation, entry timeout | ✅ | `DELETE /api/v3/order` | `order/cancel`; plan: `planorder/cancel` | symbol from in-memory cache (NOTES §4) |
| C6 | `get_order` — the fill authority (pos-mgmt §3.5) | `run_fill_sync` every 2 s | ✅ | `GET /api/v3/order` | `order/get/{id}`; plan: `planorder/list/orders` | spot ✅ except F4 |
| C7 | `get_order_fills` — fees, settlement | `run_fill_sync`, `settle`, journal | ✅ `myTrades` / `userTrades` | `GET /api/v3/myTrades?symbol&orderId` | `order/deal_details/{id}` | **`NotSupported`** |
| C8 | Look up order by client id (journal `submitted_unknown`, restart) | order journal recovery | ⚠️ not on the trait | `GET /api/v3/order?origClientOrderId` | `order/external/{symbol}/{externalOid}` | missing (new trait method, §5.3) |
| C9 | `get_account_state` (balances, open orders, positions) | reconcile at boot and every 60 s, sizing | ✅ | `GET /api/v3/account` + `openOrders` account-wide (F8) | `account/assets` + `open_positions` + `order/list/open_orders` paged (F8) | spot ✅ (account-wide call is valid per F8); futures open orders always empty |
| C10 | `get_market_info` (tick, lot, min notional, status, base/quote) | sizing min-notional check, `live_trade_ops` | ✅ | `exchangeInfo` + `selfSymbols` (F5) | `contract/detail` (`priceUnit`, `volUnit`, `contractSize`, `minVol`, `state`, `apiAllowed`) | spot reads Binance filters that MEXC does not send; futures `lot_size = volUnit` (missing `× contractSize`), `min_notional` = 0 |
| C11 | `get_fees` | sizing, paper account | ✅ | `GET /api/v3/tradeFee` (fields inside a `data` envelope) | `GET /api/v1/private/account/tiered_fee_rate/v2` → `realMakerFee` / `realTakerFee` (API fees differ from web fees; R15) | spot ✅ (unverified; envelope not handled) |
| C12 | `get_extended_market_data` | advisor loop (futures) | ✅ futures, `None` spot/margin | `None` | `funding_rate/{s}`, `fair_price/{s}`, `ticker` | futures ✅ (unverified) |
| C13 | `subscribe_market_data` (book, trades, candles) | L1 `market_data`, walls, signals | ✅ ws | ✅ ws protobuf + REST klines | ❌ REST klines only → ws `sub.depth` / `sub.deal` on `wss://contract.mexc.com/edge` (§7.6) | spot done |
| C14 | `subscribe_account_updates` (a hint, pos-mgmt §3.5) | `run_fill_sync` wake-up | poll-and-diff | poll-and-diff → **user-data stream** (§6.4) | poll-and-diff → private ws (§7.6) | poll-and-diff |
| C15 | Short entry | execution for `side: short` decisions | margin borrow + sell, or futures | ❌ (F3) → D4 | ✅ `side=3` | — |
| C16 | `MarginOps` (borrow, repay, max_borrowable, margin_balances) | margin short path, sizing | ✅ | ❌ (F3) | n/a | default `None` — stays |
| C17 | `FuturesOps::set_leverage` | boot, per pair | ✅ | n/a | `position/change_leverage` | missing (fixed `extra["default_leverage"]`) |
| C18 | `FuturesOps::set_margin_type` | boot | ✅ | n/a | no endpoint: `openType` travels on every order and leverage call (§7.4) | missing |
| C19 | `FuturesOps::is_hedge_mode` | boot guard (pos-mgmt D10; not built, this spec's L3 builds it) | ✅ | n/a | `GET position/position_mode` (1 = hedge, 2 = one-way) | missing |
| C20 | `FuturesOps::position_risk` | liquidation proximity every 15 s (pos-mgmt; loop not built yet, no caller today) | ✅ | n/a | `position/open_positions?symbol` + `fair_price` | missing |
| C21 | `FuturesOps::futures_margin_summary` | leverage-aware sizing (pos-mgmt §3.3) | ✅ | n/a | `account/asset/{currency}` | missing |
| C22 | `FuturesOps::leverage_brackets` | `LiqCalc` cross-check (live test) | ✅ | n/a | risk-limit ladder from `contract/detail` (§7.4) | missing |
| C23 | Error → `RejectReason` table | every caller branching on `reason()` | ✅ ~20 rows | §8 | §8 | 1 row + auth |
| C24 | Signed-request clock | every private call | ❌ local `now_ms()` (`rest.rs:97`); the `-1021` fix was never built (R8) | shared `ServerClock` (§6.5) | same | local clock only; futures `Recv-Window` sent in ms, docs say seconds (R9) |
| C25 | `capabilities()` (new, §5.1) | orchestrator boot gate, execution | new | new | new | new |

## 4. Decisions — taken 2026-09-25

Each decision below was taken on 2026-09-25 by adopting the recommended option. The alternatives are kept for the record.

| # | Decision |
|---|---|
| D1 | **(a)** MEXC spot trades with local-only protection behind the explicit `ALLOW_LOCAL_ONLY_STOP=1` waiver and the `LOCAL_ONLY_MAX_NOTIONAL` cap |
| D2 | Operator checklist (KYC, futures order permission, IP-bound key). **Futures is the first MEXC trading kind** |
| D3 | **(a)** `OrderId(String)`, opaque and adapter-defined; MEXC encodes `{surface}:{symbol}:{raw_id}` |
| D4 | Short decisions on MEXC spot are refused before sending: `NotPlaced { reason: "short_unsupported" }` |
| D5 | Futures exchange-side stop = **plan order** (`planorder/place/v2`). Stop moves stay cancel-and-replace through the trait for now; `planorder/change_price` (modify in place) is a recorded follow-up. Position TP/SL is no longer evaluated (R3, §7.3) |

Detail and rationale per decision follow.

**D1 — What protects a MEXC spot position when the exchange cannot hold a stop (F1)?** — **Decided: (a).**

| Option | What it means |
|---|---|
| **(a) Local-only protection, explicit waiver — recommended** | Only the in-process leg (`run_stop_loss_watcher`) protects the position. The orchestrator refuses to start armed on MEXC spot unless `ALLOW_LOCAL_ONLY_STOP=1` is set, and logs a `Severity::Critical` banner once at boot. Per-position notional is capped separately (`LOCAL_ONLY_MAX_NOTIONAL`, quote units; **required** when the waiver is set, boot is fatal without it; sizing clamps entry notional to `min(risk size, cap)`, R22). A feed-loss grace expiry has no exchange-side fallback, so it **closes the position** instead of relying on one. The visualiser shows the stop leg as "local only", not "unprotected". |
| (b) MEXC spot is data-only | `capabilities().native_stop == false` makes the orchestrator refuse `EXECUTION_MODE=live` on MEXC spot. MEXC is used only for market data and `no_trade`. |
| (c) Futures only | Trade MEXC only through futures, which has plan orders and position TP/SL (F2). Spot stays data-only. |

The recommendation is (a), because the requirement only says protection must survive process or feed death, and (a) makes the gap explicit and bounded. Choose (b) if a position with no exchange-side stop is not acceptable at any size. The decision is the operator's, because it trades a hard requirement of main_goal.md for access to the venue. **Taken 2026-09-25: (a).** The waiver defaults to off, so nothing trades on MEXC spot until the operator sets it.

**D2 — Account prerequisites for futures (F2). No longer a design decision. Decided: futures first.** The futures API is open. What remains is an operator checklist: KYC completed, futures order permission enabled on `FUTURES_API_KEY`, and the key bound to an IP. G0 (§10.1) confirms the permission with a deliberately invalid order (`vol=0` → expect a validation refusal, not a permission refusal; KYC refusals are codes 200005/200006/300000/300001, trade-permission refusal 704). The live boot repeats the same probe (§5.2, R17). Innovation-Zone contracts are not API-tradable at all: `contract/detail.apiAllowed` gates `trading_status` (§7.1). Given D1(c)'s reasoning, **the first MEXC trading kind is futures, not spot**: it is the only MEXC kind that satisfies main_goal.md's dual stop without a waiver.

**D3 — How is a string order id represented (F4)?** — **Decided: (a).**

| Option | Blast radius |
|---|---|
| **(a) `OrderId(String)`, opaque and adapter-defined — recommended** | About 300 lines naming `OrderId` across 10 crates (live_trade_ops 89, order_journal 79, mexc 28, binance 27, orchestrator 21, exchange_adapter 17, execution 17, state_store 14, market_data 7, mq_gateway 2), plus the implicit copies that break when `Copy` goes. Binance renders its `u64` as a decimal string. MEXC encodes `"{surface}:{symbol}:{raw_id}"` (surface `s` = spot, `f` = futures order, `p` = futures plan order; `symbol` is the exchange symbol, `LINKUSDT` / `LINK_USDT`; decode with `splitn(3, ':')` so a raw id is never split). That removes the in-memory symbol cache (NOTES §4 — a restart can then cancel an order it did not place in this process) and gives plan-order routing (§7.3) for free. Fixes TECH_DEBT §7 at the same time (`order_event.order_id` → `text`, one additive migration). |
| (b) Adapter-local `u64` surrogate ↔ string map | Needs persistence to survive restart, which a leaf crate cannot do, and the journal would store a meaningless number. Rejected. |

The journal already stores `exchange_order_id text` (migration 0008), so (a) needs no journal **schema** change. Its code does: `order_journal/src/pg.rs:669` parses the text as `u64` and falls back to `OrderId(0)`, which must go. The market-data writer `market_data/src/pg/rows.rs:336` (`o.id.0 as i64`) changes with the migration. `OrderId` stays `Hash + Eq + Serialize`. It stops being `Copy`, which is where most of the mechanical edits come from.

**D4 — What happens to a `side: short` decision on MEXC spot (F3)?** **Decided (the recommendation):** `capabilities().can_short == false` means execution refuses the decision *before* anything is sent. It reports `NotPlaced { reason: "short_unsupported" }` to `main/` (`NotPlaced.reason` is a `String`, `execution/src/types.rs:485`; R20), logs at `WARN` once per decision id, and sends nothing. A spot sell without holdings would either be rejected or, worse, sell base asset the account already held for other reasons. The latter is exactly the over-close class the position spec forbids. **Binance spot has `can_short == false` too, so the same refusal applies there**: a behaviour change for any Binance-spot short decision, called out in the L3 task.

## 5. Common-layer changes (`exchange_adapter`)

Kept small. Each one is also implemented for Binance so that the two stay interchangeable behind the trait.

### 5.1 `MarketAccount::capabilities()`

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Capabilities {
    pub can_place_orders: bool,       // false: MEXC futures key without order permission (D2, probed at boot)
    pub native_stop: bool,            // an exchange-resting stop exists (OrderKind::Stop)
    pub reduce_only_enforced: bool,   // exchange honours reduce_only; false => execution caps close qty itself
    pub can_short: bool,              // an opening sell is a short, not a sale of holdings
    pub order_fills: bool,            // get_order_fills is real
    pub client_id_lookup: bool,       // get_order_by_client_id is real
    pub account_push: bool,           // subscribe_account_updates is a real push, not poll-and-diff
}

trait MarketAccount {
    // …existing…
    fn capabilities(&self) -> Capabilities;   // required, no default: every adapter must answer truthfully
}
```

| | Binance spot | Binance margin | Binance futures | MEXC spot | MEXC futures |
|---|---|---|---|---|---|
| can_place_orders | ✓ | ✓ | ✓ | ✓ | ✓ at boot iff the permission probe passes (§5.2); flips ✗ on a runtime permission refusal |
| native_stop | ✓ | ✓ | ✓ | **✗** | ✓ |
| reduce_only_enforced | ✗ | ✗ | ✓ | ✗ | ✓ |
| can_short | ✗ | ✓ (borrow) | ✓ | ✗ | ✓ |
| order_fills | ✓ | ✓ | ✓ | ✓ (§6) | ✓ (§7) |
| client_id_lookup | ✓ (§5.3) | ✓ | ✓ | ✓ | ✓ |
| account_push | ✗ | ✗ | ✗ | ✓ after §6.4 | ✓ after §7.6 |

There is no MEXC margin column: `margin()` returns `None` (below), so no MEXC margin account exists to answer. `can_place_orders` is the only field that changes at runtime, so `Capabilities` stays `Copy` and the adapter builds it on each call from an `AtomicBool` it owns (R16).

Implementors (17 `impl MarketAccount`): the adapters, `NoTradeAccount`, `PaperMarketAccount`, `JournaledAccount`, `KindAccount`, `CappedAccount` (live_trade_ops harness), `AdapterAccountView`, `ScriptedAccount` and the test fakes. Wrappers pass it through; test fakes set it explicitly.

**MEXC `margin()` changes from `Some(NotSupported-stub)` to `None`.** The trait's own convention is that `None` means "this kind does not exist here". Today's stub lets `MARKET_KIND=margin` boot and then fail on the first order, but the orchestrator's `KindAccount` does **not** turn `None` into a boot error today: `resolve()` panics through `.expect` on first use (`orchestrator/src/main.rs:38-46`). L3 resolves the kind once at boot and fails with a config error instead (R19). The spot-endpoint reuse (NOTES §2) goes away with it.

### 5.2 Orchestrator and execution consume capabilities

The orchestrator today keeps only `Arc<dyn MarketAccount>` and drops the `ExchangeAdapter` (`orchestrator/src/main.rs:256`), so it cannot reach `futures_ops()`. It is changed to keep the adapter (or an `Option<Arc<dyn FuturesOps>>` beside the account) so the boot gate below can call it.

- **Boot gate** (orchestrator, `EXECUTION_MODE=live` only), in this order:
  1. Resolve `MARKET_KIND` once; `None` → config error, exit (replaces the `KindAccount` panic, R19).
  2. Futures only: `is_hedge_mode() == true` → fatal. This is pos-mgmt D10, which is **not built yet** on this branch (R18), so this spec builds it.
  3. MEXC futures only: permission probe (`ExchangeAdapter::permission_probe() -> Option<&dyn PermissionProbe>`, default `None`) = `order/create` with `vol=0` (the G0 step 6 request). A validation refusal → `can_place_orders = true`; a permission or KYC refusal (704, 200005, 200006, 300000, 300001) → `false`. If the probe unexpectedly returns an order id, cancel it at once and treat the result as fatal (R17).
  4. `!can_place_orders` → fatal.
  5. `!native_stop` → fatal unless `ALLOW_LOCAL_ONLY_STOP=1` **and** `LOCAL_ONLY_MAX_NOTIONAL` is set (D1(a)); then log the `Severity::Critical` banner once.
  6. Futures only: for each pair in `PAIRS`, `set_margin_type(FUTURES_MARGIN_TYPE)` then `set_leverage(FUTURES_LEVERAGE)` (new env, defaults `isolated` / `1`). These replace the adapter's `extra["default_leverage"]` and `extra["margin_mode"]` (R24).
- **Runtime permission loss**: a permission refusal on any order sets `can_place_orders = false` in the adapter, fires one `Severity::Critical` alert, and execution stops opening positions. Closes are still attempted.
- **Close sizing when `!reduce_only_enforced`**: the exit and stop quantity is `min(position.net_size, free_base_balance)`, read just before placement. This makes the rule execution already relies on for Binance margin explicit, because MEXC spot has no `reduceOnly` at all. It also absorbs MEXC's base-asset buy fee.
- **`reduce_only` on MEXC spot**: the adapter accepts `reduce_only=true` and does not send it. The capability advertises that it is not enforced, so the reason for today's `InvalidRequest` (`spot.rs:209-215`) is gone. Today that rejection fails every spot exit (R21).
- **Short refusal** per D4, reason string `"short_unsupported"`.
- **Stop placement when `!native_stop`**: skip placement, set the position's new `stop_leg` field to `StopLeg::LocalOnly` (`enum StopLeg { Exchange, LocalOnly, Unprotected }` on `OpenPosition`, persisted with it and rendered by the visualiser), and emit no `OrderPlacementFailed`. The alert is replaced by the boot banner, so a deliberate mode does not look like a failure on every position. `OrderRole` is a role enum (`Entry/Exit/Stop`, whose tags are embedded in client ids), so it is not the place for this state (R23).
- **Feed-loss grace** (D1(a)) does not exist in execution or the orchestrator yet (R18). Building it is a pos-mgmt deliverable. MEXC spot live (M4) is blocked until it exists.

### 5.3 `MarketAccount::get_order_by_client_id`

```rust
async fn get_order_by_client_id(&self, pair: &Pair, client_order_id: &str)
    -> Result<Option<OrderInfo>, AdapterError> { Err(AdapterError::NotSupported) }
```

`Ok(None)` means the exchange confirms it has no such order. For a journal row in `submitted_unknown` that means "never accepted", which is safe to mark `rejected`, **but only once the row is older than `recvWindow + 10 s`**. Before that, a delayed request can still land. After it, the exchange refuses it on timestamp. A younger row is re-checked later, never marked (R26). Binance: `GET …/order?origClientOrderId`. MEXC: §6.1, §7.2. Consumers: order-journal recovery at boot (live-trade-ops §4.7 names this lookup but it does not exist yet), and execution at runtime: a `place_order` that returned `Network` is resolved with this lookup on the next fill-sync tick after the age above, instead of waiting for a restart (R26).

### 5.4 `OrderId(String)` (D3)

Covered in §4. It also needs one additive migration, `order_event.order_id bigint → text` (TECH_DEBT §7, closes audit item C9 of the position-management audit, not to be confused with matrix row C9 here).

### 5.5 Client order id format

Futures `externalOid` is documented as **≤ 32 characters** (error 2030). Spot `newClientOrderId` is undocumented (error 700008 = illegal characters). `exchange_adapter::ids::MAX_CLIENT_ORDER_ID_LEN` is already 32, and minted ids are `{prefix}-{16 hex}-{e|x|s}-{n}` and `livetest-{8}-…`, so both fit if the spot limit is ≥ 32 and allows `-`. G0 step 4 captures the spot limit by sending a 32-character and a 33-character id to `order/test`. The adapter validates locally and returns `InvalidRequest`, never a round trip.

## 6. MEXC spot — full trading surface

### 6.1 Endpoints

All signed calls use spot signing (`signing.rs`: HMAC-SHA256 over the query string, `X-MEXC-APIKEY` header), `timestamp` from the offset clock (§6.5), and `recvWindow` from `extra["recv_window_ms"]` (default 5 000, max 60 000). Any field the docs example spells two ways is parsed with a serde alias until G0 captures the real one (e.g. `cummulativeQuoteQty` / `cumulativeQuoteQty`).

| Trait call | Endpoint | Mapping notes |
|---|---|---|
| `place_order` Limit | `POST /api/v3/order` `symbol, side, type=LIMIT, quantity, price, newClientOrderId` | Price and qty are rounded **by the caller**. The adapter rejects values off precision with `InvalidRequest` (no silent rounding). |
| `place_order` Market | `type=MARKET, quantity` | `quoteOrderQty` is not used: the trait is quantity-denominated. |
| `place_order` Stop | — | `NotSupported` before any network call (unchanged; now also advertised by `native_stop=false`). |
| `reduce_only` | accepted, not sent | §5.2 close sizing. Replaces today's `InvalidRequest` (R21). |
| `cancel_order` | `DELETE /api/v3/order symbol, orderId` | Symbol comes from the `OrderId` encoding (D3). `OrderNotFound` / `OrderNotCancellable` come from §8. |
| `get_order` | `GET /api/v3/order symbol, orderId` | Status map (the docs enum has exactly these five): `NEW`→New, `PARTIALLY_FILLED`→PartiallyFilled, `FILLED`→Filled, `CANCELED`/`PARTIALLY_CANCELED`→Cancelled. Any other string → `Network("unparsed: status …")` plus an `UNMAPPED` log line, never a guess (R13). `avg_fill_price = cumulativeQuoteQty / executedQty` when `executedQty > 0`. |
| `get_order_by_client_id` | `GET /api/v3/order symbol, origClientOrderId` | "Order does not exist" → `Ok(None)`. |
| `get_order_fills` | `GET /api/v3/myTrades symbol, orderId` (weight 10; only the **last month** is queryable, so settlement of an older order returns what exists and stays `settlement_complete: false`) | `id`→trade_id, `price`, `qty`, `quoteQty`, `commission`→fee, `commissionAsset`→fee_asset, `isMaker`, `time`; `realized_pnl=None`. Fill-lag rule unchanged (poll until Σqty = filled_qty, 10 s). A fee of `0` with an empty `commissionAsset` (0-fee pairs) → fee 0, fee_asset = quote asset. |
| `get_account_state` | `GET /api/v3/account` → `balances[]`; `GET /api/v3/openOrders` with no `symbol`, account-wide (F8) | `positions` is always empty (spot). No pair list needed (R1). |
| `get_market_info` | `GET /api/v3/exchangeInfo?symbol` + `GET /api/v3/selfSymbols` (signed, cached 1 h) | `tick_size = 10^-quotePrecision`, `lot_size = baseSizePrecision` (a quantity string, per the docs example), `min_notional = max(quoteAmountPrecision, quoteAmountPrecisionMarket)` (conservative: `MarketInfo` has one field and exits can be market orders), `price_precision = quotePrecision`, `qty_precision = baseAssetPrecision`, `trading_status = Trading` iff `status=="1"` && `isSpotTradingAllowed` && `tradeSideType == 1` && in `selfSymbols` (F5, R12), `base_asset`/`quote_asset` from the payload. `PERCENT_PRICE_BY_SIDE` is not mapped; a breach comes back as a reject. |
| `get_fees` | `GET /api/v3/tradeFee?symbol` (weight 20, cached 1 h) | `data.makerCommission` / `data.takerCommission` (response is wrapped in `{data, code, msg}`). |
| `get_extended_market_data` | — | `Ok(None)`. |
| `subscribe_market_data` | unchanged (done) | — |
| `subscribe_account_updates` | §6.4 | — |

### 6.2 Failure behaviour that must hold

- A `place_order` whose HTTP call fails with `Network` returns `Network`. The journal row stays `submitted_unknown` and recovery runs `get_order_by_client_id`. The adapter never retries a `POST /api/v3/order` itself: a retry after an unknown outcome is a duplicate order.
- A response the adapter cannot parse **after** a 2xx on `place_order` returns `AdapterError::Network("accepted-but-unparsed: …")`, not `InvalidRequest`. The order probably exists, and `InvalidRequest` means "nothing was sent". The code already uses `Network` here (`"bad order response: …"`); only the message prefix changes, so recovery can tell this case from a transport failure. Both go through §5.3's lookup.

### 6.3 Symbol status and API tradability

`get_market_info` returning anything but `Trading` makes execution refuse the entry (`NotPlaced { reason: "market_closed" }`). Exits never check it: a sell-only (`tradeSideType` 3/4) pair still lets a position close. It never places an order to find out.

### 6.4 User-data stream (replaces poll-and-diff)

- `POST /api/v3/userDataStream` → `listenKey`, valid 60 min. `PUT` keepalive every 30 min. `DELETE` on shutdown. A keepalive failure recreates the key and reconnects. A ws connection lives **24 h** at most (F7), so the client reconnects proactively at 23 h, not on error.
- Connect `wss://wbs-api.mexc.com/ws?listenKey=…` and send `{"method":"SUBSCRIPTION","params":["spot@private.orders.v3.api.pb","spot@private.deals.v3.api.pb","spot@private.account.v3.api.pb"]}` (names confirmed in the current docs; G0 confirms the subscribe ack; the protobuf schemas are vendored beside the existing `proto/` files).
- Mapping: orders → `AccountEvent::OrderUpdate` (carries `clientId`, cumulative qty, avg price, status); account → `BalanceUpdate`; deals → no new variant. The deal becomes an `OrderUpdate` wake-up, because `AccountEvent` has no fill variant and pos-mgmt §3.5 treats the stream as a hint anyway.
- Reuses `ws.rs`' `Backoff` and the spot constants `MEXC_PING_INTERVAL` (20 s, `{"method":"PING"}`) and `MEXC_IDLE_TIMEOUT` (45 s) from `spot.rs:41,47`. The same `FeedDisconnected` alert fires after 5 failures.
- **Position-management does not change**: the stream stays a hint and `get_order` stays the authority. The stream only cuts fill latency from about 3 s (poll) to push. Poll-and-diff stays as the fallback while the stream is down, so there is never a period with neither.

### 6.5 Clock offset

A shared `ServerClock` in `exchange_adapter` (offset = server − local, measured at the round-trip midpoint, refreshed every 10 min and after any `ClockSkew` reject). MEXC spot uses `GET /api/v3/time` (`serverTime`), futures `GET /api/v1/contract/ping` (`data` = server ms); every signed timestamp is `now_ms() + offset`. `|offset|` above `recvWindow / 2` fires a new `AlertKind::ClockSkew` (`Severity::Warn`; the host's NTP is wrong even though signing is compensated) (R10). Binance adopts the same `ServerClock` in L0-a: the spec's earlier claim that Binance already has it was wrong (`rest.rs:97` signs with local time), and the 2026-09-24 `-1021` failure is still unfixed there (R8).

## 7. MEXC futures — full trading surface (current API)

All REST paths below are on `https://api.mexc.com` (F2); the futures **websocket stays on `wss://contract.mexc.com/edge`** (§7.6). **Migration from the legacy surface is part of this work**: the futures REST host-table row (`exchange_adapter_mexc/src/config.rs:76`) moves from `contract.mexc.com` to `api.mexc.com`, and so does the operator's `FUTURES_REST_BASE_URL`, which the orchestrator requires and which overrides the table (§9); `order/submit` becomes `order/create`; plan orders are new code on `planorder/place/v2` (none exist today); `orderId` is parsed as a string; POST signing signs the raw JSON body; `Recv-Window` is sent in **seconds** = `ceil(recv_window_ms / 1000)`, capped at 60 (today `http.rs:203` sends 5000, R9); a `success:false` body on HTTP 200 goes through `classify` with its `code`, so 510 becomes `RateLimited` (today it lands in `Unknown`). Every path and field not quoted in F2 was taken from the legacy docs and is marked **"verify against current docs"** until G0 or its per-endpoint page confirms it. The implementer checks each against `mexc.com/api-docs/futures/account-and-trading-endpoints/*` before writing its wiremock fixture.

### 7.1 Units: contracts, not base quantity

MEXC orders are in `vol` = number of contracts. `contract/detail` gives `contractSize` (base per contract), `volUnit` (vol step), `minVol`, `maxVol`, `priceUnit` (tick), `maxLeverage`, `minLeverage`, `state` (0 enabled, 1 delivery, 2 delivered, 3 offline, 4 paused), `apiAllowed`. The docs page shows the path as `GET /api/v1/contract/detail/country` (optional `symbol`); G0 confirms which path answers (R14). All arithmetic is `Decimal`.

- **Outbound:** `vol = qty / contractSize`. It must be an integer multiple of `volUnit` and ≥ `minVol`, else `InvalidRequest` (no silent rounding, same rule as spot). This **fixes NOTES §3's known correctness gap**: today `qty` is passed straight through as `vol`.
- **Inbound:** every `vol` (orders, deals, positions) × `contractSize` → base qty. The rest of the system only ever sees base quantity.
- `get_market_info`: `tick_size = priceUnit`, `lot_size = volUnit × contractSize` (today `futures.rs:307-309` omits `× contractSize`), `min_notional = minVol × contractSize × fair_price` (derived from `fair_price/{symbol}`, documented as derived), `trading_status = Trading` iff `state == 0 && apiAllowed`, else `Halted`, `base_asset = baseCoin`, `quote_asset = quoteCoin`.
- `contract/detail` is cached per symbol for 1 h. A change in `contractSize` between cache refreshes is logged at `WARN`.

### 7.2 Orders

Headers: `ApiKey`, `Request-Time`, `Signature` = HMAC-SHA256(`accessKey + timestamp + paramString`), `Recv-Window`, JSON body (already in `signing.rs`).

| Trait call | Endpoint | Mapping |
|---|---|---|
| `place_order` Limit / Market | `POST /api/v1/private/order/create` (4 / 2 s; `positionMode=2` one-way, since the default is 1 = hedge) | `side`: open long 1, close short 2, open short 3, close long 4. `reduce_only=true` → close codes (Buy→2, Sell→4); `false` → open codes (Buy→1, Sell→3). `type`: Limit 1, Market 5. `openType` and `leverage` come from the per-pair settings held by `FuturesOps` (§7.4), set at boot (§5.2 step 6), not from `extra["default_leverage"]` / `extra["margin_mode"]` (both removed). A pair with no stored settings → `InvalidRequest("leverage not set")` locally. `leverage` is sent on opens only (the docs require it only there). `externalOid` = client id (≤ 32). Also `reduceOnly: true` when closing. The entry-attached `stopLossPrice` is **not** used: the stop is placed as a plan order after the entry resolves, as on Binance. |
| `cancel_order` | `POST /api/v1/private/order/cancel` (surface `f`; docs example body `{"orderIds":[…]}`, the legacy form was a bare array: G0/M3 captures which, R6); `POST /api/v1/private/planorder/cancel` `[{symbol, orderId}]` (surface `p`) | Order cancel returns per-item `{orderId, errorCode, errorMsg}`, classified per item (§8; 2040 not exist, 2041 cannot cancel). Plan cancel's docs show only the envelope; per-item handling applies if the capture shows items. |
| `get_order` | `GET /api/v1/private/order/get/{order_id}` (f); `GET /api/v1/private/planorder/list/orders?symbol&page_num=1&page_size=100&start_time&end_time` (p; all four paging/time params are **required**; window = now − 8 days … now, which covers the 7-day `executeCycle`; filtered by id, next page fetched while `page_size` rows come back) | Order `state`: 1 pending→New, 2 unfilled→New/PartiallyFilled by `dealVol`, 3 filled→Filled, 4 canceled→Cancelled, 5 invalid→Rejected. Plan order `state` (R4): 1 untriggered→New, 2 canceled→Cancelled, 3 executed→status of the spawned order (§7.3), 4 invalidated (incl. `executeCycle` expiry)→Cancelled, 5 execution failed→Rejected (`errorCode` kept in the message). |
| `get_order_by_client_id` | `GET /api/v1/private/order/external/{symbol}/{externalOid}` | Not found → `Ok(None)`. |
| `get_order_fills` | `GET /api/v1/private/order/deal_details/{order_id}` | `id`, `price`, `vol×contractSize`, `fee` (positive = paid), `feeCurrency`, `isTaker` (alias `taker`, the docs example spells it so)→!is_maker, `profit`→realized_pnl, `timestamp`; `quote_qty = price × qty` (the exchange does not report it, so this is **derived**, flagged in the doc comment). |
| `get_account_state` | `account/assets` + `position/open_positions` + `GET order/list/open_orders?page_num&page_size=100` (account-wide, paged, F8) | Fixes NOTES §3's "futures open orders always empty". Open **plan** orders are not in that list; reconcile sees the stop through the position record, not through `open_orders`. |

### 7.3 The exchange-side stop — plan order

`OrderKind::Stop` → `POST /api/v1/private/planorder/place/v2` (response `data` = order id string):

| Field | Value |
|---|---|
| `symbol`, `vol`, `leverage`, `openType` | as in §7.2 |
| `side` | close codes (4 for a long's stop, 2 for a short's) — a stop is always reduce-only in this system |
| `triggerPrice` | `stop_trigger_price` |
| `triggerType` | long stop (sell): 2 (price ≤ trigger); short stop (buy): 1 (price ≥ trigger) |
| `trend` | **2 = fair (mark) price** — same reason Binance futures stops use mark price: a wick on last price must not stop out a position that liquidation logic considers healthy. Configurable, `extra["stop_trigger_trend"]` ∈ {1 last, 2 fair, 3 index}. |
| `orderType` | 5 market when `price` is `None` (stop-market); 1 limit with `price` when `Some` (stop-limit) |
| `executeCycle` | 2 (7 days, the maximum; 1 = 24 h). Execution re-places the stop at 6 days (cancel-and-replace, the same path as a stop move), and treats an unexpected `Cancelled` on a stop it did not cancel (state 4 invalidated) as "stop lost": re-place at once and alert `OrderPlacementFailed` if that fails. Both are L3 tasks (§11, R11). |
| `positionMode`, `reduceOnly` | 2 (one-way), `true` |

The returned id is encoded `p:{symbol}:{id}`. When a plan order executes (state 3), MEXC creates an ordinary order; the plan-order record's `orderId` field carries that order's id ("returned when execution succeeds"). `get_order(p:…)` then reports the spawned order's status, `filled_qty` and `avg_fill_price`, and `get_order_fills(p:…)` returns the spawned order's deals. Confirmed by capture in M3. `run_fill_sync` needs no change: it keeps polling the stop's `OrderId` and sees it go terminal.

**D5 (decided: plan order; revised by R3).** The first draft preferred evaluating position TP/SL (`stoporder/place`, modify via `stoporder/change_plan_price`) because the plan order seemed to lack a modify. The current docs show one: `POST /api/v1/private/planorder/change_price` (`symbol, orderId, triggerPrice, price, orderType, triggerType, trend`; 4 / 2 s). So position TP/SL has no advantage left, and it is bound to a `positionId` that exists only after the entry fills. It is dropped, and so is the `t:` surface. Stop moves stay cancel-and-replace through the existing trait (the same gap as Binance today). Using `change_price` needs a new trait method, `amend_stop(OrderId, trigger) -> Result<(), AdapterError>` behind a `stop_amend` capability. That is recorded in TECH_DEBT as a follow-up, not built here.

### 7.4 `FuturesOps`

| Method | Endpoint | Notes |
|---|---|---|
| `set_leverage(pair, l)` | `POST /api/v1/private/position/change_leverage` (10 / 10 s). With no open position: `{symbol, openType, positionType, leverage}`, sent twice, `positionType` 1 and 2, so either direction opens at `l`. With an open position: `{positionId, leverage}`. Code 2019 (open orders) → `LeverageNotAllowed`. | Returns the leverage read back via `GET /api/v1/private/position/leverage?symbol` (an array per `positionType`; both must equal `l`). The adapter stores `(leverage, openType)` per pair for §7.2. Out of `[minLeverage, maxLeverage]` → `LeverageNotAllowed` locally. |
| `set_margin_type(pair, t)` | no dedicated endpoint | Stores `openType` (1 isolated, 2 cross) for the pair and re-issues `change_leverage` with it. With an open position or open orders of the other type → `MarginModeChangeBlocked` (checked locally from `open_positions`/`open_orders`, since MEXC gives no such refusal). Same type → `Ok(())` (AlreadySet semantics). |
| `is_hedge_mode()` | `GET /api/v1/private/position/position_mode` → `1` hedge / `2` one-way | Hedge → boot `ConfigError` (pos-mgmt D10). The executor never changes the mode itself. |
| `position_risk(pair)` | `GET /api/v1/private/position/open_positions?symbol` + `GET /api/v1/contract/fair_price/{symbol}` | `holdVol×contractSize`→size, `openAvgPrice`, `liquidatePrice`, `leverage`, `openType`, `im`→initial_margin, `oim`→isolated_margin (isolated only), `positionType` 1/2 → Buy/Sell. `maint_margin` is not reported: derived as `size × mark × mmr(tier)` from §7.4's ladder and **flagged derived**. `LiqCalc` cross-checks `liquidatePrice`, never the reverse. No position → `Ok(None)`. |
| `futures_margin_summary()` | `GET /api/v1/private/account/asset/USDT` | `equity`→wallet_balance, `availableBalance`, `positionMargin`→total_position_initial_margin, `frozenBalance`→total_open_order_initial_margin, total_initial_margin = `positionMargin + frozenBalance` (R25). |
| `leverage_brackets(pair)` | `contract/detail`: `riskLimitCustom[]`, `riskLimitType`, `riskBaseVol`, `riskIncrVol`, `riskIncrMmr`, `riskIncrImr`, `riskLevelLimit`, `maintenanceMarginRate`, `initialMarginRate`, `maxLeverage` | **If `riskLimitCustom` is non-empty, it is the ladder** (`level, maxVol, mmr, imr, maxLeverage` per row) (R29). Otherwise derive tier *k* = 0 … `riskLevelLimit − 1` (G0 confirms whether the bound is inclusive): cap = `(riskBaseVol + k×riskIncrVol) × contractSize × price_ref`, mmr = `maintenanceMarginRate + k×riskIncrMmr`, max_leverage = `floor(1 / (initialMarginRate + k×riskIncrImr))`. MEXC has **no `cum`** term: it is set to 0 and `LiqCalc` gets a MEXC formula branch (live-trade-ops §6.3). The notional ladder in vol units is exact. Converting it to quote uses `price_ref` = fair price at call time, which is documented on the method; with `riskLimitType == BY_VALUE` the caps are already quote and no `price_ref` is used. `LiqCalc` here means `live_trade_ops/src/risk.rs::isolated_liquidation_price` and its golden-row dispatcher, which today has only a `"binance"` arm. |

### 7.5 Extended market data

`get_extended_market_data` stays as built (`funding_rate/{symbol}`, ticker; `mark_price` already comes from `ticker.fair_price`, `futures.rs:357`). Only the host changes. Captured and confirmed in G0 step 5.

### 7.6 Websockets (futures)

- **Public:** `wss://contract.mexc.com/edge` (still the current docs' URL: the REST host moved, the ws host did not), `sub.depth` (incremental, `version`-sequenced; the same `DepthSync` resync pattern as spot) and `sub.deal`. Deal and incremental-depth pushes are **compressed by default** since 2025; the client either decompresses or subscribes with `"compress": false` (capture decides, prefer uncompressed). `{"method":"ping"}` every 15 s (docs: 10–20 s, disconnect after 60 s). This closes NOTES §1's "futures websocket for book/trade remains unbuilt", which critical-level analysis (walls) needs on futures.
- **Private:** the same connection, `{"method":"login","param":{"apiKey","reqTime","signature","subscribe":false}}` (without `subscribe:false` every private channel is pushed after login), expect `rs.login` (`rs.error` → `AuthFailed`), then `personal.filter` limited to `order`, `order.deal`, `position`, `asset`, `plan.order`. Mapping follows §6.4: order → `OrderUpdate`, position → `PositionUpdate`, asset → `BalanceUpdate`, deal / plan-order → wake-up `OrderUpdate`. Poll-and-diff stays as the fallback.

## 8. Error table (`errors.rs::classify`)

Built as live-trade-ops §4.6 prescribes: every row starts **"from docs"** and becomes final only when a captured response confirms it (M-runs, §10). The runner's `UNMAPPED Mexc <code>: <message>` lines (`report.rs:179` prints the exchange with `{:?}`) grow the table. The codes below are the docs' candidates, listed so the first captures have something to confirm against. **None is asserted yet.**

Meanings below are quoted from the current docs' error-code pages (R5); the first draft's futures rows were mostly wrong. `classify` today ignores `code` (`errors.rs:35-48`) and must key on it.

| Surface | Code (candidate) | Docs meaning | → `RejectReason` |
|---|---|---|---|
| spot | 700001 / 700002 / 10072 | API-key format invalid / signature not valid / invalid access key | `AuthFailed` |
| spot | 700006 | IP not in whitelist | `AuthFailed` |
| spot | 700007 / 30020 | no permission for endpoint / no permission for symbol | `PermissionDenied` (new) |
| spot | 700003 | timestamp outside recvWindow | `ClockSkew` |
| spot | 700004 / 700005 / 700008 / 730002 | ids both empty / recvWindow > 60000 / illegal characters / invalid param | `Unknown` (adapter bug — surfaced verbatim) |
| spot | 10101 / 30004 / 30005 | insufficient balance / insufficient position / oversold | `InsufficientBalance` |
| spot | 30002 | below minimum transaction volume | `InvalidQuantity` |
| spot | 30029 / 30032 | above maximum order limit / above maximum position | `InvalidQuantity` |
| spot | 30016 | trading disabled | `MarketClosed` |
| spot | 30018 / 30019 | market order disabled / API market order disabled | `MarketClosed` (the pair may still take limits; execution's exit escalation falls back to limit) |
| spot | 30014 / 730001 | invalid symbol / pair not found | `Unknown` (config bug — surfaced verbatim) |
| spot | **-2013** (G0-captured; the docs' `-2011` did not appear) | "Order does not exist." | `OrderNotFound` |
| spot | **700011** (G0-captured, margin endpoint) | "This interface is not allowed" | `PermissionDenied` |
| spot | HTTP 429 | rate limit | `AdapterError::RateLimited` |
| futures | 602 / 401 / 402 / 406 | signature failed / not logged in / key expired / IP not whitelisted | `AuthFailed` |
| futures | 701 / 702 / 704 / 200005 / 200006 / 300000 / 300001 | read / write / trade permission not enabled; KYC refusals | `PermissionDenied` (new): sets `can_place_orders = false` at runtime (alert once) |
| futures | 2005 | balance insufficient | `InsufficientMargin` |
| futures | 2008 / 2009 / 2043 | not enough position to close / position nonexistent or closed / order does not match position | `ReduceOnlyRejected` |
| futures | 2040 / 2041 | order does not exist / cannot cancel | `OrderNotFound` / `OrderNotCancellable` |
| futures | 2006 / 2019 / 2021 | leverage out of range / cannot change with open orders / order leverage ≠ position leverage | `LeverageNotAllowed` |
| futures | 2003 / 2004 | price above max / below min (the band) | `PriceOutsideBand` |
| futures | 2007 | order price error | `InvalidPrice` |
| futures | 2011 / 2015 | order quantity error / price or quantity precision error | `InvalidQuantity` |
| futures | 2016 / 2013 | too many trigger orders / too many cancels in one batch | `Unknown` (should never happen at one position per pair) |
| futures | 1001 / 1002 | contract does not exist / not activated | `MarketClosed` |
| futures | 2030 | `externalOid` too long | `Unknown` (the local 32-char check should have caught it) |
| futures | 2042 | duplicate order id (`externalOid`) | `Unknown` with the message kept; recovery then looks the order up by client id (§5.3). Never retried |
| futures | 3001–3004 | plan-order parameter errors | `Unknown` (adapter bug) |
| futures | 510 / 2037 | requests / trading too frequent | `AdapterError::RateLimited` |

New variants: `PermissionDenied` (replaces the first draft's `EndpointUnavailable`: the cause is the key's permission, not the endpoint, and spot 700007 now lands in the same place) (R7). `order_journal/src/pg.rs` has exhaustive `RejectReason` ↔ string maps in both directions; both get the new rows. `ShortUnsupported` is **not** a `RejectReason`: it is a `NotPlaced` reason string (R20).

The futures batch-cancel per-item `errorCode` goes through the same function.

## 9. Operations and config

| Item | Rule |
|---|---|
| Credentials | Spot: `API_KEY` / `API_SECRET`. Futures: `FUTURES_API_KEY` / `FUTURES_API_SECRET` (already the orchestrator's prefixes). Permissions: spot trade and futures trade only, **never withdraw**. |
| IP binding | **Required** (F7): an unbound key dies after 90 days. The executor host's egress IP is bound on both keys. An `AuthFailed` at boot is fatal. An `AuthFailed` while running → `Severity::Critical` alert, trading stops, open positions keep only whatever native protection they have. **On MEXC spot that is none**: the local stop leg cannot close either, so the alert text says "MEXC spot position UNPROTECTED — close manually". The D1 waiver covers this case. |
| Sub-account | Recommended (lesson from live-trade-ops-remaining §3.1): reconcile then never sees balances or orders it did not create. |
| Hosts | `FUTURES_REST_BASE_URL` must change to `https://api.mexc.com` (the orchestrator requires `{prefix}REST_BASE_URL` / `{prefix}WS_BASE_URL` and they override the adapter's table). `FUTURES_WS_BASE_URL` stays `wss://contract.mexc.com/edge`. |
| Futures boot settings | New env `FUTURES_LEVERAGE` (default 1) and `FUTURES_MARGIN_TYPE` (`isolated` / `cross`, default `isolated`), applied per pair in `PAIRS` at boot (§5.2). They replace `extra["default_leverage"]` / `extra["margin_mode"]`. |
| D1 waiver | `ALLOW_LOCAL_ONLY_STOP=1` + `LOCAL_ONLY_MAX_NOTIONAL` (quote), both required for MEXC spot live. |
| Rate budget | Token buckets in `http.rs` at 70 % of each documented limit (none exists today), `RateLimited` when exhausted: spot IP weight **300 / 10 s** (→ 210) and spot order place+cancel **12 / s** (→ 8); futures one bucket per endpoint group per F7/§7 (`order/create` and `planorder/*` 4 / 2 s, `order/get`, `open_orders`, `cancel` 20 / 2 s, `change_leverage` 10 / 10 s). Consumers: market data (depth snapshot on resync), fill sync (2 s per live order), account poll (3 s), reconcile (60 s). Metric: `mexc_rest_weight_used{surface,bucket}`. |
| Open-order cap | 500 per account. Not a concern at one position per pair. Recorded, not enforced. |
| No testnet | Every MEXC live run is mainnet with `LIVE_TRADE_OPS=1`, `LIVE_MAX_NOTIONAL` and a `run_id`, exactly as Binance margin (R3). |

## 10. Verification

### 10.1 G0 — capability probe (read-mostly; first thing run)

A standalone `live_trade_ops` scenario, `mexc_probe`, built on raw signed HTTP (the existing `signing.rs` / `http.rs`), **not** on the new `OrderId` or adapter mapping: it runs before L0-a, so the facts that shape the refactor are confirmed before it starts (R2). It changes nothing on the account except, at most, one refused futures order:

1. `GET /api/v3/time`, `/api/v1/contract/ping` → clock offsets.
2. `GET /api/v3/account` → key valid and permissions (`canTrade`).
3. `exchangeInfo` + `selfSymbols` + `defaultSymbols` for `LIVE_PAIR` → captures F5's fields (incl. `tradeSideType`, `quoteAmountPrecisionMarket`) and the `lot_size` interpretation.
4. `POST /api/v3/order/test` (not executed) three times: a valid LIMIT with a 32-char client id, the same with a 33-char id (§5.5), and `type=STOP_MARKET_ORDER` (expect refusal: confirms F1).
5. `GET /api/v3/openOrders` with no `symbol` (confirms F8) and `GET /api/v3/margin/…` (expect 404: confirms F3).
6. `contract/detail` (both path forms, R14), `position_mode`, `account/assets`, `open_positions`, `order/list/open_orders`, `planorder/list/orders` (empty window), `tiered_fee_rate/v2`, `funding_rate`, `fair_price` → captures the futures read shapes.
7. `order/create` with `vol=0` and a 32-char `externalOid` → **D2**: a validation refusal means the permission is in place; a permission / KYC refusal is recorded and blocks M3. If an order id comes back, cancel it at once and fail the probe.
8. Opens the spot user-data stream for 60 s → subscribe ack for the three channel names; futures ws login with `subscribe:false` → `rs.login`.

Output: a probe report with one confirmed / refuted line per F-fact, plus fixtures written to `exchange_adapter_mexc/tests/fixtures/captured/`. Every `// from docs` wiremock fixture is replaced by a captured one when one exists.

### 10.2 Offline (every layer, `cargo test` in Docker)

- Wiremock per endpoint in §6–§7: request params sent **and** response parsing, using captured fixtures.
- Unit: `OrderId` encode/decode for all three surfaces; vol ↔ qty conversion including off-step rejection; side-code table (4 combinations × reduce_only); plan-order `triggerType` by side; leverage-bracket derivation from a captured `contract/detail`; the `classify` table one test per row; capability values per surface (§5.1 table as a test).
- Execution: `!native_stop` → no stop order sent and `stop_leg == LocalOnly`; `!can_short` → `NotPlaced { reason: "short_unsupported" }` with zero adapter calls; `!reduce_only_enforced` → close qty capped to free base.
- `live_trade_ops` fake: a `mexc_spot` profile with the capability set from §5.1, so the scenario's capability skips are exercised offline.
- Orchestrator: boot gate steps 1–6 (§5.2), each fatal branch tested; permission probe result → `can_place_orders`.
- `ServerClock` offset and `Recv-Window` seconds conversion; plan-order state table incl. state 3 → spawned order; stop renewal at 6 days and re-place on unexpected `Cancelled`.

### 10.3 Live runs (mainnet, operator-armed)

| # | Run | Proves |
|---|---|---|
| M0 | G0 probe | D2, the F-facts, fixtures |
| M1 | New `run_spot_scenario` (only margin and futures scenarios exist today): MEXC spot round trip at `LIVE_MAX_NOTIONAL`: limit buy → fills via `get_order_fills` → `settle` → limit sell (`reduce_only=true`, sized by §5.2) → flat; the stop step reports `Skipped(native_stop=false)` | C1, C2, C4–C11, settlement with MEXC fee assets, journal with string ids |
| M2 | M1 with the user-data stream up: every fill observed on push before the poll | §6.4 |
| M3 | Futures open → plan-order stop → move stop → close reduce-only → flat; `position_risk` vs `LiqCalc` golden row | §7 whole |
| M4 | Executor itself, `EXCHANGE=mexc MARKET_KIND=spot EXECUTION_MODE=live` with the D1 waiver, one SAR-test-signal position at minimum notional, end to end with `main/` | integration: position-management on MEXC spot. Blocked until feed-loss grace exists (§5.2) |
| M5 | Executor itself, `EXCHANGE=mexc MARKET_KIND=futures EXECUTION_MODE=live`, one SAR-test-signal position at minimum notional: boot gate passes (hedge check, permission probe, leverage/margin set), entry → plan-order stop → exit → flat, end to end with `main/` | integration: position-management on MEXC futures, the first MEXC trading kind (D2). Missing from the first draft (R27) |

This is live-trade-ops-remaining's R4. Futures (M3, M5) comes first (D2). M1–M3 are `live_trade_ops` scenarios and do not go through the orchestrator, so the D1 waiver is not needed for M1; it is needed for M4.

## 11. Implementation layering

Per `layer-first-planning`: Docker-first, interface before code at each boundary, and each layer's Docker-verified tests green before the next starts. Branch `mexc-trading-connector` from `layer-implementation` **after** the position-management work (uncommitted in `.worktrees/layer-implementation`, 56 changed files at review time) is committed and merged there: this spec's consumers (`run_fill_sync`, `settle`, the order journal's recovery) live in it (R28).

| Layer | Content | Depends on |
|---|---|---|
| **G0** | `mexc_probe` scenario on raw signed HTTP; run M0; commit captured fixtures and the F-table verdicts | operator keys (D2 checklist) |
| **L0-a common** | `OrderId(String)` (D3) across the workspace + `order_event` migration (0010) + `order_journal` parse fix; `Capabilities` + `capabilities()` on all 17 implementors; `get_order_by_client_id` (Binance too); `RejectReason::PermissionDenied` (+ journal string maps); `ServerClock` (Binance adopts it); `AlertKind::ClockSkew` | G0 (if G0 refutes F4, D3 is re-opened) |
| **L0-b MEXC spot** | §6.1–6.3, §6.5, `reduce_only` accepted, margin → `None`, `classify` rows confirmed by G0, rate buckets | L0-a |
| **L0-c MEXC spot push** | §6.4 user-data stream | L0-b |
| **L0-d MEXC futures** (migrate to current API) | §7.1–7.5, `Recv-Window` seconds, 510 → `RateLimited`, rate buckets | L0-a, G0 step 7 green |
| **L0-e MEXC futures ws** | §7.6 | L0-d for private; public is independent |
| **L3 orchestrator + execution** | §5.2: orchestrator keeps the adapter, boot gate steps 1–6 (incl. hedge guard and permission probe), `FUTURES_LEVERAGE` / `FUTURES_MARGIN_TYPE`, runtime permission loss, close-qty cap, short refusal (Binance spot too), `StopLeg` field + visualiser label, runtime `submitted_unknown` resolution (§5.3), plan-order renewal and lost-stop re-place (§7.3), `LOCAL_ONLY_MAX_NOTIONAL` clamp | L0-a, D1, D4 |
| **Live M3** | futures scenario | L0-d (L0-e optional) |
| **Live M5** | executor on MEXC futures | L0-d, L0-e, L3 |
| **Live M1, M2** | spot scenarios | L0-b (M2: L0-c) |
| **Live M4** | executor on MEXC spot | L0-b, L0-c, L3, pos-mgmt feed-loss grace |

**Order (D2: futures first):** G0 → L0-a → L0-d → M3 → L0-e → L3 → M5 is the critical path. L0-b / L0-c and M1 / M2 follow; M4 last, once the operator sets the D1 waiver and feed-loss grace exists.

Implementation plans (written 2026-09-25): index [`plans/2026-09-25-mexc-connector-index-plan.md`](../plans/2026-09-25-mexc-connector-index-plan.md) → 1/5 G0, 2/5 L0-a, 3/5 L0-d + L0-e, 4/5 L3, 5/5 L0-b + L0-c. The MEXC-side plumbing both adapter plans share (id codec, rate bucket, code-keyed `classify`) moved into L0-a so the spot and futures plans run in parallel.

`exchange_adapter_mexc/NOTES.md` is rewritten at the end of each layer: every section that this spec closes is deleted, not annotated.

## 12. Out of scope

- MEXC margin (F3), and any borrow-based short on MEXC.
- Hedge mode (pos-mgmt D10).
- Automatic de-risking on liquidation proximity (pos-mgmt §9).
- MEXC spot kline websocket: REST polling stays, as for Binance.
- Batch order placement (`batchOrders`, `submit_batch`): one position per pair never needs it.
- Emulating a spot stop with a server-side service outside the executor (a second process holding the stop): it is still not "on the exchange", and it would duplicate the local leg's failure modes.
- Cancel-on-disconnect / dead-man switch: MEXC offers none that we found. Noted so nobody assumes it exists.
- Modify-in-place stop moves (`planorder/change_price`, trait `amend_stop`): recorded in TECH_DEBT, not built (D5).
- The liquidation-proximity loop and feed-loss grace themselves: position-management deliverables. This spec only depends on them (M4 is blocked on feed-loss grace).
- Entry-attached TP/SL (`stopLossPrice` on `order/create`): the stop is a separate plan order, as on Binance.

## 13. Acceptance criteria

1. D1–D5 recorded in this file with the date taken — **done 2026-09-25** (§4).
2. G0 has run; its report and captured fixtures are committed; §2's F-table has a "confirmed / refuted" column filled in from it.
3. `OrderId` is a string end to end: a MEXC spot order placed, restarted-over (new process), then cancelled via its stored id succeeds (offline test plus M1).
4. Every C-row in §3 marked MEXC spot is implemented or returns its documented refusal, with a wiremock test on a captured fixture.
5. `get_order_fills` is real on MEXC spot: an M1 position ends with `settlement_complete: true` and fees in the fee asset MEXC actually charged.
6. The orchestrator refuses to start live on MEXC spot without the D1 waiver and `LOCAL_ONLY_MAX_NOTIONAL`, and refuses `MARKET_KIND=margin` on MEXC at boot with a config error, not a panic. All tested.
7. A short decision on MEXC spot produces `NotPlaced { reason: "short_unsupported" }` and zero exchange calls.
8. `classify` has no row still marked "from docs" for any code seen in M0–M4, and every `Unknown` seen is listed in the run report.
9. M3 is green on the current futures API (no **REST** request goes to `contract.mexc.com` or a legacy path; the futures ws stays there by design), and `LiqCalc` has a MEXC golden row. A key without order permission gives `can_place_orders == false` from the boot probe, and `MARKET_KIND=futures` refuses to start live — tested.
9a. Every C-row in §3 marked MEXC futures is implemented, with a wiremock test on a captured fixture; M5 is green.
9b. A MEXC spot exit with `reduce_only=true` is placed (not rejected), sized to `min(net_size, free_base)`.
10. `exchange_adapter_mexc/NOTES.md` describes only what is still true.
11. The task files in `external/executor/plans/` exist for each layer in §11, `TECH_DEBT.md` §7 is closed, and the `amend_stop` follow-up (D5) is recorded there.

## 14. Sources

Current MEXC docs (authoritative for this spec):
- Spot new order — https://www.mexc.com/api-docs/spot-v3/spot-account-trade/new-order
- Spot enums (Order Type incl. `STOP_MARKET_ORDER (Query only)`) — https://www.mexc.com/api-docs/spot-v3/public-api-definitions
- Futures integration guide (host, signing, KYC, 90-day key) — https://www.mexc.com/api-docs/futures/integration-guide
- Futures place order — https://www.mexc.com/api-docs/futures/account-and-trading-endpoints/place-order
- Futures place plan order — https://www.mexc.com/api-docs/futures/account-and-trading-endpoints/place-plan-order
- Futures TP/SL by position — https://www.mexc.com/api-docs/futures/account-and-trading-endpoints/place-tpsl-order-by-position

- Spot exchange info, self symbols, open orders, error codes, user-data streams — https://www.mexc.com/api-docs/spot-v3/market-data-endpoints/exchange-information , …/spot-account-trade/user-api-default-symbol , …/spot-account-trade/current-open-orders , …/error-code , …/websocket-user-data-streams/
- Futures modify plan order — https://www.mexc.com/api-docs/futures/account-and-trading-endpoints/modify-plan-order
- Futures plan-order list, current orders, cancel orders, error codes, contract info, websocket — …/futures/account-and-trading-endpoints/get-plan-order-list , …/get-current-orders , …/cancel-orders , https://www.mexc.com/api-docs/futures/error-code , …/futures/market-endpoints/get-contract-info , …/futures/websocket-api/

Legacy docs (`mexcdevelop.github.io/apidocs/…`) are **not** a source (NOTES §2 still cites them and is rewritten with L0-b): their futures "under maintenance" notice misled the first draft of this spec.

## 15. Review log — 2026-09-25

Checked against the code (`.worktrees/layer-implementation`, HEAD 165afdb plus uncommitted position-management work) and the current MEXC docs (read through WebFetch; field spellings marked "capture" still need G0). Each finding lists the options considered; the **recommended option was adopted** and is already applied in the sections named.

### Wrong facts (docs)

| # | Finding | Options | Adopted |
|---|---|---|---|
| R1 | F8 was wrong: spot `openOrders` takes `symbol` optionally; futures `open_orders` is account-wide, paged | (a) account-wide calls, drop `extra["pairs"]`; (b) keep per-pair loop | **(a)**: fewer calls, no new config (F8, §6.1, §7.2, §9) |
| R3 | Plan orders do have a modify (`planorder/change_price`), so D5's reason for looking at position TP/SL is gone | (a) plan order, cancel-and-replace now, `amend_stop` follow-up; (b) add `amend_stop` to the trait now; (c) keep the TP/SL evaluation | **(a)**: no trait change in this spec, same behaviour as Binance; drops `t:` (D5, §7.3) |
| R4 | Plan-order states are numeric 1–5; state 3 carries the spawned `orderId`; the list call needs paging and a time window | — (fact) | Mapping and 8-day window (§7.2, §7.3) |
| R5 | Futures error rows mostly wrong (2011, 2013, 2015, 2016, 2019 meant other things); spot 30018/30029/30032 wrong | — (fact) | §8 rebuilt from the docs' error pages; missing codes added |
| R6 | Futures `order/cancel` body is `{"orderIds":[…]}` in the docs example | capture decides | §7.2 |
| R12 | Spot tradability also needs `tradeSideType`; `selfSymbols` is per key | (a) `selfSymbols` + `tradeSideType == 1`; (b) `defaultSymbols` only | **(a)**: answers for this key, not the whole exchange (F5, §6.1) |
| R13 | Spot has no `REJECTED` status | map unknown → error; or guess `Rejected` | **error + UNMAPPED**, no guessing (§6.1) |
| R14 | `contract/detail` shown as `/contract/detail/country` | capture decides | G0 step 6 (§7.1) |
| R15 | `tiered_fee_rate` is now `/v2`; API fees differ from `contract/detail` fees | (a) `tiered_fee_rate/v2`; (b) `contract/detail` | **(a)**: the real fee (C11) |
| — | Rate limits: spot IP 300 / 10 s, orders 12 / s UID, futures per endpoint; spot ws 24 h; futures ws host unchanged, compressed pushes, `subscribe:false` on login; `externalOid` ≤ 32; `apiAllowed` / Innovation Zone | — (facts) | F7, §6.4, §7.1, §7.6, §9 |

### Wrong or missing against the code

| # | Finding | Options | Adopted |
|---|---|---|---|
| R2 | G0 depended on L0-a (≈300-line `OrderId` refactor) although its job is to confirm the facts that refactor rests on | (a) G0 on raw signed HTTP, first; (b) keep order | **(a)** (§10.1, §11) |
| R7 | Permission refusal mapped to `EndpointUnavailable` while spot 700007 went to `AuthFailed` | (a) one new `PermissionDenied`; (b) reuse `AuthFailed` for both | **(a)**: G0 and the boot probe must tell "wrong key" from "key lacks permission" (§8) |
| R8 | C24 claimed Binance has a server-time offset; it signs with local time (`rest.rs:97`) | (a) shared `ServerClock`, Binance adopts it; (b) MEXC-only clock | **(a)**: fixes the real 2026-09-24 `-1021` failure too (§6.5, L0-a) |
| R9 | Futures `Recv-Window` sent as 5000 (ms); docs say seconds, max 60 | — (bug) | seconds conversion (§7) |
| R10 | Clock alert left as "ClockSkew or FeedStale"; no `AlertKind::ClockSkew` exists | (a) new variant; (b) `FeedStale{component:clock}` | **(a)**: a feed alert would mislead (§6.5) |
| R11 | Plan-order renewal said "part of L3" but L3 did not list it; expiry (state 4) was unhandled | — (gap) | renewal at 6 d + lost-stop re-place in L3 (§7.3, §11) |
| R16 | `Capabilities` is `Copy` yet `can_place_orders` must change at runtime; no boot mechanism found it | (a) adapter-owned `AtomicBool` + boot `vol=0` probe; (b) flip only on first refusal; (c) operator flag | **(a)**: acceptance 9 needs a refusal *at boot* (§5.1, §5.2) |
| R17 | Boot permission probe could, in theory, create an order | — | cancel immediately + fatal (§5.2) |
| R18 | Hedge-mode guard, liquidation loop, feed-loss grace are "already pos-mgmt" in the spec but do not exist | (a) this spec builds the hedge guard, depends on pos-mgmt for the rest, M4 blocked; (b) build all here | **(a)**: keeps scope; spot live needs feed-loss grace anyway (§5.2, §11, §12) |
| R19 | `KindAccount` panics on `None`, it does not boot-error | — (bug) | resolve at boot, config error (§5.1, §5.2) |
| R20 | `NotPlaced.reason` is a `String`; `ShortUnsupported` / `MarketClosed` are not its type | (a) fixed strings `"short_unsupported"` / `"market_closed"`; (b) new enum through state_store / mq_gateway / visualizer dtos | **(a)**: wire-compatible, no DTO change (D4, §6.3) |
| R21 | MEXC spot rejects `reduce_only=true`, so every spot exit and stop fails today | (a) adapter accepts and does not send it (capability says not enforced); (b) execution clears the flag | **(a)**: matches Binance margin; execution stays exchange-agnostic (C4, §5.2, §6.1) |
| R22 | `LOCAL_ONLY_MAX_NOTIONAL` had no unit, default or enforcement point | — (gap) | quote units, required with waiver, sizing clamp (D1, §9) |
| R23 | `LocalOnly` as an `OrderRole` status: `OrderRole` is a role enum whose tag is in client ids | (a) `stop_leg: StopLeg` on `OpenPosition`; (b) new `OrderStatus` on a synthetic tracked order | **(a)**: no fake orders, adapters' status enum untouched (§5.2) |
| R24 | Nothing calls `set_leverage` / `set_margin_type`; spec removed `extra["default_leverage"]` and missed `extra["margin_mode"]` | (a) boot applies `FUTURES_LEVERAGE` / `FUTURES_MARGIN_TYPE`; (b) keep extra keys | **(a)**: one source, exchange-agnostic (§5.2, §7.2, §9) |
| R25 | `futures_margin_summary` "total = sum" undefined | — | `positionMargin + frozenBalance` (§7.4) |
| R26 | `Ok(None)` right after a network timeout can be a race; recovery only ran at boot | — (gap) | age > `recvWindow + 10 s`; runtime resolution (§5.3) |
| R27 | Futures is the first trading kind but no live run tested the executor on it | — (gap) | M5 (§10.3, §11, §13) |
| R28 | Branch base: consumers are uncommitted position-management work | — | branch after it merges (§11) |
| R29 | `contract/detail` has `riskLimitCustom` / `riskLimitType` that override the derived ladder | (a) custom ladder when present; (b) always derive | **(a)** (§7.4) |
| — | Smaller corrections: `OrderId` ≈300 lines / 10 crates (not 176 / 8); journal code parses `u64` (pg.rs:669); F4 already surfaces as `Network`; `margin()` lives on `ExchangeAdapter`; 17 implementors incl. `CappedAccount`, `AdapterAccountView`, `ScriptedAccount`, `PaperMarketAccount`; `FUTURES_REST_BASE_URL` overrides the host table; `UNMAPPED Mexc` spelling; no spot `live_trade_ops` scenario exists (M1 builds one); `LiqCalc` = `risk.rs::isolated_liquidation_price`; futures `lot_size` misses `× contractSize`; `mark_price` already from `fair_price`; wrong §6.2 cross-references → §6.1; stale "Given (c)" / "unless D1(a) is chosen" wording; MEXC margin column dropped from §5.1 | — | applied in place |

### Implementation drift — L0-a as built (2026-09-25)

Built on `mexc-trading-connector` directly, not on a separate `mexc-common` branch: `8ae129f` (first pass, against the pre-review draft), then an alignment commit.

- **`OrderId` still accepts a legacy JSON number** when deserializing, where plan 2/5 Task 1.1 asked for a loud failure. The reason: `position_log.state` (0009) jsonb already holds numeric Binance ids for positions persisted before this change, and a loud failure would stop every such position from loading at boot. New writes are always strings.
- `get_order_by_client_id` takes `Pair` by value, per plan 2/5.
- `ShortUnsupported` is not a `RejectReason` (R20). `PermissionDenied` replaced the first pass's `EndpointUnavailable` (R7).
- A fill whose order row has no `exchange_order_id` is now a journal read **error**. It used to be attributed to a placeholder `OrderId(0)`.
- MEXC `classify(venue, status, code, msg) -> AdapterError` keeps the one pre-existing message-matched row ("insufficient balance" → `InsufficientBalance`) until 3/5 and 5/5 replace it with code rows.
- `JournaledAccount::resolve_submitted_unknown(now, min_age_ms)` is the recovery helper §5.3 names. Callers pass `recvWindow + 10 s` (R26). Wiring it into boot and runtime belongs to plan 4/5.

### Implementation drift — plan 4/5 (L3) as built (2026-09-26)

- **Local-only banner:** it uses a new `AlertKind::ProtectionDegraded` (Critical, once at boot), not `OrderPlacementFailed`. A deliberate, waived mode must not read as a placement failure.
- **Runtime recovery of `submitted_unknown`:** a background task every `ORDER_POLL_INTERVAL_SECS` (minimum 5 s), for rows older than 15 s. An order the exchange accepted after its send timed out is **cancelled, not adopted**: `open_position` already treated the send as failed, so nothing tracks the order. If it filled before the cancel, the periodic reconciliation (D8) brings that position in. It raises a Warn alert.
- **Close sizing:** capped at the free base balance only for a closing **sell** on a venue without enforced `reduce_only`. A closing buy (e.g. Binance margin short cover) is never capped.
- **Exit retry and stop upkeep:** both run on the fill-sync poll. A `Closing` position with size and no working exit gets one. An `Open` position's stop that is no longer live and was not cancelled here is re-placed. A stop older than 6 days is cancelled and re-placed.
- **`StopLeg` / `stop_placed_at`:** persisted in `position_log.state` with serde defaults (old rows read as `Exchange`). The visualiser shows "local only" instead of the unprotected banner.
- **Venue resolution:** `KindAccount` in `main.rs` is replaced by `orchestrator::resolve_account` (a config error, not a panic).
- **Compose:** the `executor` futures defaults now point at `api.mexc.com` and `contract.mexc.com/edge`, and the four gate variables are passed through.
- **Not built:** the orchestrator-level integration test `live_boot_on_mexc_futures_fake_reaches_execution`. The gate is unit-tested against fakes for every refusal and for setup order.

### Still open (need a capture, not a decision)

~~Spot `newClientOrderId` limit~~ (G0: `^[0-9a-zA-Z_-]{1,32}$`); `cumulativeQuoteQty` spelling; `isTaker` vs `taker`; ~~`contract/detail` path~~ (G0: `/api/v1/contract/detail`); order-cancel body shape; plan-cancel per-item errors; `riskLevelLimit` bound inclusivity (G0: this pair has a single bracket, so it cannot show it); futures ws compression default. The ones not struck through are M3 items (they need a real order).
