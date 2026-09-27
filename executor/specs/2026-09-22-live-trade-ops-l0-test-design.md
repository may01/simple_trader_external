# Live Trade-Operations Test at L0 — exchange-agnostic, Binance first (margin + futures) — Design Spec

Date: 2026-09-22
Status: **implemented and merged 2026-09-25** (branch `live-trade-ops` → `layer-implementation`, 35 commits). Two live margin-mainnet runs done; nothing past step 0 has run live yet. Remaining work: [2026-09-25-live-trade-ops-remaining-design.md](2026-09-25-live-trade-ops-remaining-design.md)
Target project: `trade_executor` (Rust, worktree `layer-implementation`)
Scope: **testing the executor's exchange connector (L0) only.** No `main/` work, no orchestrator/`execution` behaviour change; all test machinery lives in the separate crate `live_trade_ops` (D1); outside L0 the only shared change is migration `0008` (+ `SCHEMA_VERSION`); other edits are compile-only ripples of shared-type changes (decided 2026-09-22).
Closes (partly): [layers/L0-exchange-adapter.md](layers/L0-exchange-adapter.md) §Acceptance criteria, Stage 1 — "`place_order` opens a position and a corresponding order closes it … against the exchange", "`cancel_order` succeeds against a resting order", "`get_order` returns correct status, filled qty, and avg fill price after a real fill", "position modify (… leverage change on an open position)", "Verified via integration test against exchange testnet/sandbox"
Related: [layers/L9-deploy.md](layers/L9-deploy.md) (env config), `crates/exchange_adapter_binance/tests/testnet_integration.rs` and `crates/exchange_adapter_mexc/tests/live_credentials.rs` (the existing per-exchange smoke tests this spec supersedes)

## 1. Why this exists

The test is written once, against the L0 traits only, and run against whichever exchange `EXCHANGE` selects (§5). Binance is the first exchange it is run on; MEXC runs the same test once its adapter implements the traits. The rest of this section describes the Binance gap that motivates it; MEXC's is the same.

Every Binance adapter test today stops at a boundary it controls: `tests/wiremock_tests.rs` (≈1300 lines) proves request building and response parsing against a local mock; `testnet_integration.rs` only proves construction plus `get_market_info` and has never been run. Nothing has ever placed, observed, cancelled and filled a real order through `exchange_adapter_binance`, and nothing can borrow or change leverage at all — L0 has no such calls.

The executor will trade real money through exactly this code. The questions only a real exchange answers:

- does a limit order priced away from the touch rest (`New`), and does `cancel_order` actually remove it and release the locked balance;
- does a limit order priced through the touch fill, and does `get_order` report the fill correctly;
- does borrowing and repaying on cross margin work (and does the endpoint we call still exist — see §7);
- on futures, does leverage do what the risk code assumes: initial margin = notional / leverage, and a liquidation price that moves when leverage changes.

## 2. Decisions taken (2026-09-21/22)

| # | Decision | Why |
|---|---|---|
| D1 | The test **lives in its own crate, `crates/live_trade_ops`**, which no production crate depends on. Its harness and scenarios are written only against the L0 traits (`ExchangeAdapter`, `MarketAccount`, the new ops traits, §4) — no exchange-specific type or code in them. Production crates (L0 adapters) get only the **connector capabilities** being tested; everything that exists only to test them (harness, fake, registry, fee settlement, liquidation calculator, order journal) lives in `live_trade_ops`. No MQ, no `execution`, no running executor process. **Amended 2026-09-25:** two of those stop being test-only once position management (spec 2026-09-22-position-management-design.md) uses them in production, so they leave this crate rather than making a production crate depend on it — `settle` to `exchange_adapter` (that spec's D4), the order journal to its own production crate `crates/order_journal` (that spec's D5, §5.0 here). | L0 is the executor's only path to the exchange, so that is what the test drives. Keeping test machinery out of production crates means the live code paths do not change shape to accommodate the test (decided 2026-09-22). |
| D2 | The test **observes the order book itself** (via L0's `subscribe_market_data`) to choose prices, and **times its own waits**. | Prices must be chosen relative to the live touch at the moment of placement; the 20 s waits are part of the scenario, not an implementation detail. |
| D3 | The adapter is built with an **env loader that lives in L0** (`AdapterConfig::from_env`, §4.3), not a hand-built `AdapterConfig`. | The connector's own config path (var names, URL parsing, network selection) is exercised by the test. Switching the orchestrator to this loader is a follow-up outside this spec. |
| D4 | Margin runs on **mainnet**, small notional, on a **dedicated sub-account**. Futures runs on **testnet or mainnet, chosen by one exchange-agnostic flag** (`EXCHANGE_NETWORK`, §4.3, default mainnet); the testnet run is done first, by setting the flag. | Binance's spot testnet (`testnet.binance.vision`) has no `/sapi/v1/margin/*` endpoints; margin cannot be tested anywhere else. The futures testnet is real and free, but its brackets, filters and liquidity are not mainnet's — the numbers `execution` will rely on must also be proven on mainnet. A sub-account bounds the loss if cleanup fails. |
| D5 | One run per (exchange, kind, network), one env file each — e.g. binance/margin/mainnet, binance/futures/testnet, binance/futures/mainnet. | Different hosts and credentials per exchange and per network. |
| D7 | **One test, many exchanges.** The exchange is chosen at run time by `EXCHANGE` through an adapter registry (§5.0); running on another exchange is a different env file, not different code. | Every exchange the executor trades on must pass the same bar. Exchange-specific knowledge lives only in the adapters: endpoints (§4.2), host table (§4.3), error table (§4.6), fee rules (via `Fill`, §4.5). |
| D8 | **Capability-driven, not exchange-driven.** A step needing `margin_ops()` or `futures_ops()` runs if the adapter returns `Some`; on `None`, or on `AdapterError::NotSupported` from a call, the step is reported `SKIPPED (not supported)`, never silently passed. `LIVE_REQUIRE_ALL=1` turns any skip into a failure (used once an exchange is claimed complete). | Lets a partly-implemented adapter (MEXC today) run the parts it has, and makes the gaps visible in the run report. |
| D9 | **Every order is persisted in the executor's Postgres** — client order id, exchange order id, request, status, fills and fees — written **before** the order is sent and updated after (§4.7). The test uses the same persistence path production will use. | An order id that exists only in process memory is lost on a crash; the DB row is what lets the next run (and later `execution`) find, reconcile and account for every order ever sent. |
| D6 | The network (testnet/mainnet) is selected **in L0's common config** by `EXCHANGE_NETWORK`, with a host table per exchange — not in the test and not Binance-specific. | The switch belongs to the connector, so any caller of L0 gets it; the test proves it. Any exchange (MEXC now, others later) plugs in by adding host-table rows. |

Not covered, by design: anything above L0 — the orchestrator (`NoTradeAccount`, `MARKET_KIND` selection, exchange construction in `orchestrator/src/main.rs`), `execution`, MQ, and `main/`. The orchestrator keeps its own construction code; moving it onto `AdapterConfig::from_env`, `exchange_registry` and `JournaledAccount` is a follow-up.

## 3. Scope

In:
- L0 additions: `MarginOps`, `FuturesOps`, extra margin/futures account fields, exchange-agnostic rejection reasons (§4.6), env config loader (§4), `get_order_fills` + the pure `settle` fee/settlement function (§4.5), `client_order_id` on `OrderInfo` (§5.4).
- New crate `crates/live_trade_ops` (§5.0): adapter registry, exchange-agnostic harness and two scenarios (§5, §6), `settle` (§4.5), liquidation calculator (§6.3), order journal (§4.7; moves to `crates/order_journal`, amended 2026-09-25 — §5.0), scripted fake exchange + offline self-tests, and the runner `tests/live_trade_ops.rs`. Not a dependency of any production crate.
- Migration `0008` (order journal tables, §4.7) — the only change to shared infrastructure outside L0.
- Binance: full implementation of everything the test needs; runs green on margin mainnet, futures testnet and futures mainnet.
- MEXC: the exchange-agnostic plumbing only — registry entry, host rows, error-classification routing (§4.6). `EXCHANGE=mexc` must run end-to-end, with unimplemented capabilities reported `SKIPPED`.
- A pure liquidation/initial-margin calculator plus a golden-file unit test fed by the futures run (§6.3).

Out:
- MEXC adapter work beyond the plumbing (ops traits, `get_order_fills`, error-table rows, MEXC's own live runs) — its own spec; **the test itself needs no change** for it.
- Hedge mode (`dualSidePosition`) — one-way mode only.
- Any MQ, `execution` or `state_store` change.
- Persisting borrow/repay and leverage/margin-type changes — same pattern, follow-up once the order journal exists.

## 4. Production code changes (L0, plus the L5 order journal in §4.7)

### 4.1 Extension traits

Borrowing and leverage are not common to every `MarketAccount` (spot has neither; margin has no leverage call; futures has no borrowing), so they are separate traits, exposed through new `ExchangeAdapter` accessors. `None` means "this kind does not have it", same convention as the existing accessors.

```
trait ExchangeAdapter {
    // existing: spot(), margin(), futures()
    fn margin_ops(&self)  -> Option<&dyn MarginOps>;   // Binance: Some
    fn futures_ops(&self) -> Option<&dyn FuturesOps>;  // Binance: Some
}

trait MarginOps {
    fn borrow(&self, asset: &str, amount: Decimal) -> Result<(), AdapterError>;
    fn repay(&self, asset: &str, amount: Decimal)  -> Result<(), AdapterError>;
    fn max_borrowable(&self, asset: &str)          -> Result<Decimal, AdapterError>;
    fn margin_balances(&self)                      -> Result<Vec<MarginBalance>, AdapterError>;
}

struct MarginBalance { asset, free, locked, borrowed, interest, net_asset: Decimal }

trait FuturesOps {
    fn set_leverage(&self, pair: Pair, leverage: u32)          -> Result<u32, AdapterError>;   // returns what the exchange applied
    fn set_margin_type(&self, pair: Pair, t: MarginType)       -> Result<(), AdapterError>;    // Cross | Isolated
    fn leverage_brackets(&self, pair: Pair)                    -> Result<Vec<LeverageBracket>, AdapterError>;
    fn position_risk(&self, pair: Pair)                        -> Result<Option<FuturesPosition>, AdapterError>;
    fn futures_margin_summary(&self)                           -> Result<FuturesMarginSummary, AdapterError>;
    fn is_hedge_mode(&self)                                    -> Result<bool, AdapterError>;  // GET /fapi/v1/positionSide/dual
}

struct LeverageBracket    { notional_floor, notional_cap: Decimal, max_leverage: u32, maint_margin_ratio, cum: Decimal }
struct FuturesPosition    { pair, side, size, entry_price, mark_price, leverage: u32, margin_type: MarginType,
                            isolated_margin, initial_margin, maint_margin, liquidation_price: Decimal }
struct FuturesMarginSummary { wallet_balance, available_balance, total_initial_margin,
                              total_open_order_initial_margin, total_position_initial_margin: Decimal }
```

`margin_balances` is separate from `get_account_state` so `BalanceDelta` (shared with L1) does not grow margin-only fields.

### 4.2 Binance endpoints (first implementation)

The traits in §4.1 are exchange-agnostic; this table is Binance's implementation of them. MEXC's equivalent table belongs to the MEXC spec.


| Call | Endpoint | Notes |
|---|---|---|
| `borrow` / `repay` | `POST /sapi/v1/margin/borrow-repay` (`type=BORROW\|REPAY`, `isIsolated=FALSE`) | The replacement for the retired `/sapi/v1/margin/loan` / `/repay` (see §7). |
| `max_borrowable` | `GET /sapi/v1/margin/maxBorrowable` | |
| `margin_balances` | `GET /sapi/v1/margin/account` → `userAssets[]` | Already fetched by `get_account_state`; `borrowed`/`interest`/`netAsset` are already in the payload (see `parsing.rs` fixtures) but dropped. |
| `set_leverage` | `POST /fapi/v1/leverage` | |
| `set_margin_type` | `POST /fapi/v1/marginType` | "Already set" (`RejectReason::AlreadySet`, §4.6) maps to `Ok(())`. |
| `leverage_brackets` | `GET /fapi/v1/leverageBracket` | |
| `position_risk` | `GET /fapi/v2/positionRisk` (or v3 — pick the version whose payload carries `leverage`, `marginType`, `isolatedMargin`, `liquidationPrice`; confirm with a fixture captured from testnet) | |
| `futures_margin_summary` | `GET /fapi/v2/account` | Top-level fields. |

Every new call gets wiremock tests (request params + response parsing), like the existing ones. Wiremock fixtures for the new endpoints are **captured from the first real testnet/mainnet response**, not written from memory of the docs.

### 4.3 Error codes and config

- **Exchange error codes → common reasons.** See §4.6 (replaces an earlier Binance-only `binance_error_code` helper).
- **Env loader.** Add `AdapterConfig::from_env(prefix) -> Result<AdapterConfig, ConfigError>` to L0 (modelled on `orchestrator/src/main.rs::adapter_config_from_env`, but returning an error instead of `process::exit`). The orchestrator's own function is left in place, touched only as far as the `AdapterConfig` field changes require to compile. Same var names: `{prefix}API_KEY`, `{prefix}API_SECRET`, `{prefix}REST_BASE_URL`, `{prefix}WS_BASE_URL` (now optional overrides), plus `EXCHANGE_NETWORK` below.
- **Network switch — exchange-agnostic.** One env var, `EXCHANGE_NETWORK = testnet | mainnet`, for every exchange and every market kind. It lives in the common layer, not in any one adapter:

  ```
  // exchange_adapter (common)
  enum Network { Testnet, Mainnet }
  struct AdapterConfig { …existing…, network: Network }      // from_env reads EXCHANGE_NETWORK; unset → Mainnet; other → ConfigError

  // each exchange_adapter_X owns its own host table
  fn hosts(network: Network, kind: MarketKind) -> Result<Hosts, ConfigError>;   // Hosts { rest, ws }
  fn resolved_network(&self) -> ResolvedNetwork;   // Testnet | Mainnet | Custom(url) — for banners and startup logs
  ```

  Host tables this spec fills in:

  | Exchange | Kind | `testnet` | `mainnet` |
  |---|---|---|---|
  | binance | spot | `testnet.binance.vision` | `api.binance.com` / `stream.binance.com:9443` |
  | binance | margin | **`ConfigError`** — Binance has no margin testnet | `api.binance.com` / `stream.binance.com:9443` |
  | binance | futures | `testnet.binancefuture.com` / `stream.binancefuture.com` | `fapi.binance.com` / `fstream.binance.com` |
  | mexc | spot, margin, futures | **`ConfigError`** — no public testnet | today's hosts (`api.mexc.com`, `contract.mexc.com`, …) |

  An unsupported combination is a startup error naming the exchange and kind, never a silent fallback to the other network. Adding an exchange means adding its rows; the flag, the loader and the test do not change.

  **Precedence**, highest first: explicit URL override (`{prefix}REST_BASE_URL` / `{prefix}WS_BASE_URL`, and Binance's `extra["futures_rest_base_url"]` / `extra["futures_ws_base_url"]`) > `EXCHANGE_NETWORK` host table > **mainnet default**. The URL vars become **optional** (they are required today); when one is set, `resolved_network()` reports `Custom(url)` so a log never claims "mainnet" for a hand-set host. `trade_executor/docker-compose.yml`'s `executor` service keeps its explicit URL vars for now (they act as overrides, so the running executor is unaffected); only the `test` service gets `EXCHANGE_NETWORK` pass-through. Moving the `executor` service onto `EXCHANGE_NETWORK` is part of the orchestrator follow-up.

  **Default = mainnet (decided 2026-09-22).** Unset means mainnet for every exchange and kind; testnet is the explicit choice. This matches how the executor is deployed (its compose service already points at Binance mainnet hosts) and lets Binance margin and MEXC — which have no testnet — work without setting anything. It **reverses** `exchange_adapter_binance/src/config.rs`'s current rule ("default every base URL to testnet", `DEFAULT_FUTURES_REST_BASE_URL = testnet.binancefuture.com`): those constants, their doc comments and the unit tests asserting a testnet default change with it. What keeps a default-mainnet test from trading by accident is not the network but its arming flag, `LIVE_TRADE_OPS=1`, which has no default.

  Unit tests: every host-table row (incl. both `ConfigError` rows), unset/invalid value, and override precedence including `Custom`.

### 4.4 Also fix while here

- `market.rs::place_order` sends `reduceOnly` only for futures (correct) — keep, and add a wiremock test that margin never sends it.
- `config.rs` doc comment says `futures_ws_base_url` is "not yet consumed"; `adapter.rs` does pass it to the futures account. Correct the comment.

### 4.5 Fills, fees and settlement

Today `OrderInfo` reports `filled_qty` and `avg_fill_price` only. Binance's order endpoints (`GET …/order`) carry **no fee information**; fees exist only per trade (fill). So neither the test nor `execution` can currently say what an order cost or what it left in the account.

**New on `MarketAccount`** (every kind has fills and fees, so this is the common trait, not an extension trait):

```
fn get_order_fills(&self, id: OrderId) -> Result<Vec<Fill>, AdapterError>;

struct Fill {
    trade_id: String, order_id: OrderId, pair: Pair, side: Side,
    price: Decimal, qty: Decimal,          // base qty of this fill
    quote_qty: Decimal,                    // price × qty as reported by the exchange (not recomputed)
    fee: Decimal, fee_asset: String,       // Binance commission, commissionAsset
    is_maker: bool,
    realized_pnl: Option<Decimal>,         // futures only
    ts: Ts,
}
```

| Kind | Endpoint | Notes |
|---|---|---|
| spot | `GET /api/v3/myTrades?symbol&orderId` | |
| margin | `GET /sapi/v1/margin/myTrades?symbol&orderId&isIsolated=FALSE` | |
| futures | `GET /fapi/v1/userTrades?symbol&orderId` | carries `realizedPnl` |

Other implementors (MEXC, paper account, `NoTradeAccount` pass-through, test fakes): MEXC returns `NotSupported` until its own spec; paper account synthesises one fill with fee = `get_fees().taker × quote_qty`; `NoTradeAccount` passes through (reading is allowed).

**Settlement — pure function** (no I/O, exchange-agnostic, unit-tested). Written in `live_trade_ops`; **promoted to `exchange_adapter` by [2026-09-22-position-management-design.md](2026-09-22-position-management-design.md) D4** (amended 2026-09-25), so `execution` and this test share one implementation of fee arithmetic and cannot disagree. `live_trade_ops` calls the promoted copy:

```
fn settle(kind: MarketKind, assets: &PairAssets, side: Side, fills: &[Fill]) -> Settlement;

struct PairAssets { base: String, quote: String }      // LINK, USDT — from get_market_info

struct Settlement {
    filled_qty: Decimal,             // Σ fill.qty
    gross_quote: Decimal,            // Σ fill.quote_qty — what the order was worth before fees
    avg_price: Option<Decimal>,     // gross_quote / filled_qty; None when there are no fills
    fees: Vec<(String, Decimal)>,    // Σ fee per fee_asset — the amount PAID
    fee_in_quote: Option<Decimal>,   // fees converted to quote at avg_price; None if a fee asset is neither base nor quote (e.g. BNB)
    effective_fee_rate: Option<Decimal>, // fee_in_quote / gross_quote
    net_deltas: Vec<(String, Decimal)>,  // signed change per asset in the account, fees included — the RESULTING funds
    net_price: Option<Decimal>,      // quote actually paid (buy) / received (sell) per unit of base actually received / given
    realized_pnl: Option<Decimal>,   // futures: Σ fill.realized_pnl
}
```

Rules `settle` applies:

| Kind / side | base delta | quote delta | fee |
|---|---|---|---|
| spot/margin BUY | `+filled_qty` | `−gross_quote` | subtracted from `fee_asset` (normally base: you receive less LINK) |
| spot/margin SELL | `−filled_qty` | `+gross_quote` | subtracted from `fee_asset` (normally quote: you receive less USDT) |
| futures (either side) | none (a position, not a balance) | wallet `+realized_pnl` | subtracted from `fee_asset` (USDT, or BNB if enabled) |

Worked example (margin BUY 0.80 LINK at 15.000, taker 0.1 %, fee in LINK): `gross_quote` 12.0000 USDT, fee 0.00080 LINK, `fee_in_quote` 0.0120 USDT, `net_deltas` = LINK +0.79920, USDT −12.0000, `net_price` = 12.0000 / 0.79920 = 15.0150 USDT per LINK actually received.

`settle` is the one place fee arithmetic lives for the test; if `execution` needs fee-aware PnL later, `settle` moves to `exchange_adapter` and both call it, so they cannot disagree. Unit tests: each row of the table, multi-fill orders, mixed maker/taker fills, a BNB fee (→ `fee_in_quote == None`, BNB appears in `net_deltas`), zero fills.

**Fill lag.** `myTrades`/`userTrades` can lag the `FILLED` status by a moment. `get_order_fills` returns what exists; the caller (test's fill poller, later `execution`) polls until `Σ fill.qty == OrderInfo.filled_qty`, timeout 10 s.

### 4.6 Exchange-agnostic rejection reasons

**Problem today.** The same exchange condition surfaces differently per adapter, and the exchange's error code is lost or buried in a string:

| Adapter | Exchange refuses a request (4xx / error envelope) | Code kept? |
|---|---|---|
| binance (`rest.rs::classify_http_error`) | `Rejected(<raw JSON body>)` | only inside the raw body |
| mexc spot/margin (`http.rs::map_error_status`) | `InvalidRequest("[code] msg")`; 401/403 → `Rejected("auth error …")` | inside a formatted string |
| mexc futures (`dto_futures.rs::unwrap_envelope`, `success:false` even on HTTP 200) | `Rejected(message)` | **dropped** |

A caller (this test, `execution`) cannot ask "was this insufficient balance?" without string-matching per exchange — e.g. `mexc/tests/futures_wiremock_tests.rs:128` matches `msg.contains("insufficient balance")`.

**Common model** (in `exchange_adapter`, used by every adapter):

```
enum AdapterError {
    Stale, RateLimited, Network(String), NotSupported,     // unchanged
    InvalidRequest(String),   // NARROWED: refused locally, before anything was sent (e.g. limit without price),
                              // or a response we could not parse. Never a exchange refusal.
    Rejected(Rejection),      // CHANGED from Rejected(String): the exchange (or NoTradeAccount) refused.
}

enum Exchange { Binance, Mexc, Local }   // which exchange; Local = refused inside our process (NoTradeAccount), nothing sent

struct Rejection {
    reason: RejectReason,       // what callers branch on
    exchange: Exchange,               // Binance | Mexc | Local (NoTradeAccount)
    code: Option<String>,       // raw exchange code, verbatim ("-4028", "30004"); String because exchanges differ
    http_status: Option<u16>,
    message: String,            // exchange text, verbatim
}

enum RejectReason {
    // funds
    InsufficientBalance, InsufficientMargin,
    // order parameters
    InvalidPrice,            // tick / precision
    InvalidQuantity,         // lot / step / precision
    BelowMinNotional,
    PriceOutsideBand,        // percent-price / price-limit bands
    PostOnlyWouldTake,
    ReduceOnlyRejected,
    // order lifecycle
    OrderNotFound, OrderNotCancellable,     // e.g. already filled/cancelled
    // account settings (futures)
    LeverageNotAllowed,      // above bracket max / invalid value
    MarginModeChangeBlocked, // open position or orders
    AlreadySet,              // "no need to change" — setters map this to Ok(())
    // borrowing (margin)
    BorrowLimitExceeded, RepayExceedsDebt, AssetNotBorrowable,
    // access
    AuthFailed,              // bad key, wrong network's key, missing permission, IP not whitelisted
    ClockSkew,               // timestamp outside recv window
    MarketClosed,
    // local
    Disarmed,                // NoTradeAccount (EXECUTION_MODE=no_trade)

    Unknown,                 // unmapped code — code/message still carried verbatim
}

impl AdapterError {
    fn reason(&self) -> Option<RejectReason>;   // Some only for Rejected
    fn is_retryable(&self) -> bool;             // RateLimited, Network, Rejected(ClockSkew); nothing else
}
```

`Display` stays `rejected: {message}` plus ` [exchange code]`, so existing logs read the same.

**Per-adapter mapping.** Each adapter crate owns one `errors.rs` with a single function `classify(http_status, code, message) -> RejectReason` built from a table, one unit test per row. Every place in the adapter that builds an error goes through it — no more ad-hoc `Rejected(...)`/`InvalidRequest(...)` for exchange refusals. Some exchange codes are overloaded and need the message too (Binance `-1013` carries the filter name; `-2010` covers several order refusals).

Binance starting table — each row is **confirmed against a captured real response** (§4.2 fixture rule) before its test is marked final; a row the live runs never hit stays marked "from docs":

| Binance code | Message hint | → `RejectReason` |
|---|---|---|
| `-2010` | "insufficient balance" | `InsufficientBalance` |
| `-2010` | other | `Unknown` |
| `-2019` | margin is insufficient | `InsufficientMargin` |
| `-1013` | `PRICE_FILTER` | `InvalidPrice` |
| `-1013` | `LOT_SIZE` / `MARKET_LOT_SIZE` | `InvalidQuantity` |
| `-1013` | `MIN_NOTIONAL` / `NOTIONAL` | `BelowMinNotional` |
| `-1013` | `PERCENT_PRICE…` | `PriceOutsideBand` |
| `-1111` | precision | `InvalidQuantity` or `InvalidPrice` by message |
| `-4131` / `-4016` / `-4024` | price above/below limit | `PriceOutsideBand` |
| `-5022` | post-only would take | `PostOnlyWouldTake` |
| `-2022` | reduce-only rejected | `ReduceOnlyRejected` |
| `-2013` | order does not exist | `OrderNotFound` |
| `-2011` | unknown order / cancel rejected | `OrderNotCancellable` |
| `-4028` | leverage not valid | `LeverageNotAllowed` |
| `-4048` / `-4047` | margin type cannot change with position / open orders | `MarginModeChangeBlocked` |
| `-4046` | no need to change margin type | `AlreadySet` |
| `-3006` | exceeds max borrowable | `BorrowLimitExceeded` |
| `-3015` | repay exceeds borrow | `RepayExceedsDebt` |
| `-3045` | system lacks asset to lend | `AssetNotBorrowable` |
| `-2014` / `-2015` / `-1022` | bad key / permissions / signature | `AuthFailed` |
| `-1021` | timestamp outside recvWindow | `ClockSkew` |
| HTTP 429 / 418 | — | `AdapterError::RateLimited` (unchanged) |
| any other | — | `Unknown` (code + message kept) |

**MEXC.** In scope here: only the plumbing — `map_error_status` and `unwrap_envelope` route through MEXC's own `classify`, the envelope `code` is preserved (it is dropped today), exchange 4xx become `Rejected` instead of `InvalidRequest`, 401/403 become `AuthFailed`, and the table starts with the one row already evidenced in MEXC's tests ("insufficient balance" → `InsufficientBalance`); everything else is `Unknown` with its code. Filling MEXC's table is the MEXC live-test spec's job, done the same way (captured responses → rows → tests). Because the test in §5–§6 asserts on `RejectReason`, not on exchange codes, running it against MEXC later needs no test changes — only table rows.

**Unmapped codes are surfaced.** The live test prints every `Unknown` rejection it sees as `UNMAPPED <exchange> <code>: <message>`, so each run grows the table rather than hiding gaps.

**Blast radius** (mechanical, all in this workspace): `no_trade.rs` builds `Rejection { reason: Disarmed, exchange: Local, … }` and its tests match `reason == Disarmed`; `execution/src/tests.rs` fake builds a `Rejection`; MEXC tests replace `msg.contains("insufficient balance")` with `reason() == Some(InsufficientBalance)`. No `execution` behaviour changes — it may start branching on `reason()` later, outside this spec.

### 4.7 Order journal — every order persisted in the DB

> **Review required:** the `JournaledAccount` / `OrderJournal` design below is flagged for review in [../TECH_DEBT.md](../TECH_DEBT.md) §8 (state row vs. action log, cancels not write-before-send, naming).

**Today.** L1 writes `AccountEvent::OrderUpdate`s it happens to observe into `order_event` (`migrations/0001_init.sql`), but nothing records the orders the executor *sends*: no client order id, no request (price/qty/kind), no link between request and exchange id, no fills, no fees. `order_event.order_id` is also `bigint`, which cannot hold MEXC's string order ids.

**Interface (in `crates/order_journal`, a production crate — amended 2026-09-25; built first as test-only `live_trade_ops::journal`, moved when the orchestrator started journalling production orders, position-management §5.5):**

```
trait OrderJournal: Send + Sync {
    fn record_intent(&self, i: &OrderIntent)                          -> Result<(), JournalError>;  // before sending
    fn record_ack(&self, client_id: &str, ack: &OrderAck)             -> Result<(), JournalError>;  // exchange order id + first status
    fn record_rejection(&self, client_id: &str, r: &Rejection)        -> Result<(), JournalError>;
    fn record_status(&self, client_id: &str, info: &OrderInfo)        -> Result<(), JournalError>;  // every get_order / cancel result
    fn record_fills(&self, client_id: &str, fills: &[Fill], s: &Settlement) -> Result<(), JournalError>;  // idempotent on (exchange, trade_id)
    fn unfinished(&self, exchange: Exchange, origin: &str)                  -> Result<Vec<JournaledOrder>, JournalError>;  // not in a terminal status
}

struct OrderIntent { client_order_id, exchange, network, kind: MarketKind, request: OrderRequest, origin: String /* "livetest" | "execution" */, run_id: Option<String>, created_at: Ts }

struct JournaledAccount<A: MarketAccount, J: OrderJournal>   // implements MarketAccount; wraps any account
```

`JournaledAccount` (in `order_journal`) is a `MarketAccount` decorator: `place_order` requires a `client_order_id`, calls `record_intent`, **only then** sends, then `record_ack` / `record_rejection`; `get_order`, `cancel_order` and `get_order_fills` pass through and record what they return. Everything else passes through untouched. Callers never write to the journal directly, so no code path can send an order without persisting it.

**Failure rules (fail closed):**
- `record_intent` fails → the order is **not sent**; `place_order` returns the error.
- Send fails with `Network` (unknown whether the exchange accepted it) → row stays `submitted_unknown`; resolved later by looking the order up by client order id (§5.4 tag).
- `record_ack` fails after the exchange accepted → the order is live but the DB lacks its exchange id: an alert is raised (surfaced as `observability::AlertKind::PersistFailed` with `component=order_journal` and `OrderJournalWriteFailed:` in the message — no new `AlertKind` variant — kept after the move to `order_journal`, since `PersistFailed` is already the production kind for a failed durable write and `component` identifies the journal), the error is returned to the caller; recovery is the same client-id lookup. The live test treats this as a failure; cleanup still runs.

**Postgres implementation** (`order_journal::PgOrderJournal`, `sqlx` directly; `state_store` untouched; synchronous commit — `record_intent` has committed before the order is sent). New migration `0008_order_journal.sql` (additive; `SCHEMA_VERSION` 7 → 8):

```
exchange_order (
  client_order_id   text PRIMARY KEY,
  exchange             text NOT NULL,              -- binance | mexc
  network           text NOT NULL,              -- testnet | mainnet | custom
  market_kind       text NOT NULL,              -- spot | margin | futures
  pair              text NOT NULL,
  side              side_enum NOT NULL,
  order_kind        text NOT NULL,              -- limit | market | stop
  price             numeric, stop_price numeric,
  qty               numeric NOT NULL,
  reduce_only       boolean NOT NULL,
  exchange_order_id text,                       -- text: MEXC ids are strings; NULL until acked
  status            text NOT NULL,              -- intent | submitted_unknown | new | partially_filled | filled | cancelled | rejected
  filled_qty        numeric NOT NULL DEFAULT 0,
  avg_fill_price    numeric,
  reject_reason     text, reject_code text, reject_message text,
  origin            text NOT NULL,              -- livetest | execution
  run_id            text,
  created_at        bigint NOT NULL,
  updated_at        bigint NOT NULL,
  UNIQUE (exchange, market_kind, exchange_order_id)
)
exchange_fill (
  exchange text NOT NULL, trade_id text NOT NULL,
  client_order_id text NOT NULL REFERENCES exchange_order,
  price numeric NOT NULL, qty numeric NOT NULL, quote_qty numeric NOT NULL,
  fee numeric NOT NULL, fee_asset text NOT NULL, is_maker boolean NOT NULL,
  realized_pnl numeric, exchange_ts bigint NOT NULL,
  PRIMARY KEY (exchange, trade_id)
)
-- index: exchange_order (origin, status) for unfinished(); exchange_order (run_id)
```

The settlement summary (`gross_quote`, `fees`, `net_deltas`) is not stored: it is derived from `exchange_fill` by `settle` (§4.5) whenever needed, so it cannot drift from the fills. Status transitions only move forward (`intent → submitted_unknown|new|rejected → partially_filled → filled|cancelled`); a backward update is refused and alerted. `order_event` is left as is (L1's observation log); its `bigint order_id` is recorded as tech debt.

The `dashboard` role gets `SELECT` on both tables through the existing default privileges (`docker/initdb.d/00-roles.sql`), so the visualiser can show them later without a schema change.

**Who uses it.** The live test: every order goes through `JournaledAccount`, `origin = livetest`, `run_id` = `LIVE_RUN_ID`. The offline self-test uses the in-memory `OrderJournal`. **Amended 2026-09-25:** the orchestrator too — wrapping its account was the follow-up this section named, taken up by position-management §5.5 with `origin = execution`. Both callers depend on `crates/order_journal`; neither depends on the other.

## 5. The test harness

### 5.0 Where the code lives

Everything test-only is in one crate, `crates/live_trade_ops`. Dependency direction is one-way: `live_trade_ops` → `exchange_adapter`, `exchange_adapter_binance`, `exchange_adapter_mexc`, `observability`, `order_journal`, `sqlx`; **nothing depends on `live_trade_ops`** (checked: `cargo tree -i live_trade_ops` lists no workspace crate).

**Amended 2026-09-25 — the order journal lives in `crates/order_journal`.** It started here as the `journal` module, but position-management §5.5 wraps the orchestrator's production account in `JournaledAccount`, and the orchestrator may not depend on this crate. So the module moves out whole — `OrderJournal`, `JournaledAccount`, `JournalContext`, `MemoryJournal`, `PgOrderJournal`, their unit tests, and `tests/pg_journal.rs` — the same move `settle` makes to `exchange_adapter` (position-management D4). `order_journal` → `exchange_adapter`, `observability`, `sqlx` (plus `async-trait`, `rust_decimal`, `uuid`); it imports no adapter crate and not `live_trade_ops`. `cargo tree -i order_journal` lists exactly `live_trade_ops` and `orchestrator`. The move changes no behaviour or schema: migration `0008` and the §4.7 rules stay as written.

| Module | Content | May import adapter crates? |
|---|---|---|
| `registry` | `build_adapter_from_env(kind) -> BuiltAdapter` reading `EXCHANGE` (`binance` \| `mexc`) and `AdapterConfig::from_env`; modelled on the orchestrator's construction but does not replace it | yes — the only module that does |
| `settle`, `risk` | fee settlement (§4.5), liquidation calculator (§6.3) | no |
| ~~`journal`~~ | moved to `crates/order_journal` (amended 2026-09-25, above); harness and scenarios import it from there | — |
| `harness` | `BookWatcher`, `Pricer`, `Countdown`, `CappedAccount`, cleanup guard, fill poller, settlement check, report (§5.2–§5.5) | no |
| `scenarios` | `run_margin_scenario`, `run_futures_scenario`, `ensure_sell_funds` (§6) | no |
| `fake` | `ScriptedExchange` for offline self-tests — scripted, not simulated (decided 2026-09-22): each test lists expected calls with canned replies (values, errors, delays, panics) and asserts on the recorded call sequence; no book engine, matching, fee model or borrow ledger | no |
| `tests/live_trade_ops.rs` | runner: `live_margin_trade_ops`, `live_futures_trade_ops` (`#[ignore]`) | via `registry` |
| `tests/fixtures/` | captured responses, `futures_liq_golden.json` | — |

The self-tests (harness + scenarios on `ScriptedExchange`) are ordinary `#[tokio::test]`s in this crate, so `cargo test --workspace` in the `test` service runs them; no feature flag is needed.

The offline self-test is what keeps the harness honest without spending money: cleanup after a mid-scenario panic, the touched rule, settlement arithmetic, capability skips and `LIVE_REQUIRE_ALL` are all exercised against the scripted fake on every build. Real exchange behaviour (matching, fees, borrow interest, leverage rules) is **not** modelled by the fake; the live runs cover it.

### 5.1 Gating and running

- Both tests are `#[ignore]` **and** return early (with a printed reason) unless `LIVE_TRADE_OPS=1`. `cargo test` never touches the network.
- Run in the executor's test image, one test at a time:
  ```bash
  docker compose run --build --rm --env-file configs/live-trade-ops/binance.margin.mainnet.env test \
    cargo test -p live_trade_ops --test live_trade_ops live_margin -- --ignored --nocapture --test-threads=1
  ```
- Env files `configs/live-trade-ops/{exchange}.{kind}.{network}.env` are **gitignored**; a committed `*.env.example` per exchange lists the vars. Switching exchange or network = switching env file (`EXCHANGE`, `EXCHANGE_NETWORK`, keys); the test code is identical. Binance files below; MEXC files take the same vars plus MEXC's `FUTURES_API_KEY`/`FUTURES_API_SECRET` (its futures API has separate credentials, see `orchestrator/src/main.rs`).

| Var (Binance files) | margin.mainnet | futures.testnet | futures.mainnet |
|---|---|---|---|
| `LIVE_TRADE_OPS` | `1` | `1` | `1` |
| `EXCHANGE` | `binance` | `binance` | `binance` |
| `EXCHANGE_NETWORK` | unset (= `mainnet`; margin has no testnet, `testnet` is a config error) | `testnet` | unset (= `mainnet`) |
| `API_KEY` / `API_SECRET` | sub-account mainnet key (margin + spot trading enabled, **withdrawals disabled**); sub-account holds no BNB, so fees stay in base/quote (a fee in a third asset is still settled and checked, §4.5, it just makes the report less readable) | futures-testnet key | sub-account mainnet key with **futures enabled, withdrawals disabled**; futures wallet funded with ≥ 2 × `LIVE_MAX_NOTIONAL` USDT |
| `REST_BASE_URL` / `WS_BASE_URL` | unset (host table) | unset | unset |
| `LIVE_PAIR` | `LINKUSDT` | `LINKUSDT` | `LINKUSDT` (pair spelling is whatever the adapter's `Pair` expects for that exchange) |
| `DATABASE_URL` | executor Postgres (write role) | same | same |
| `LIVE_REQUIRE_ALL` | `1` | `1` | `1` (unset on an exchange still being implemented, D8) |
| `LIVE_MAX_NOTIONAL` | `15` (USDT) | `15` | `15` |
| `LIVE_WAIT_SECS` | `20` | `20` | `20` |
| `LIVE_RUN_ID` | optional; default a fresh uuid | same | same |

- **Network banner.** Both tests print `EXCHANGE = <exchange>  KIND = <margin|futures>  NETWORK = <testnet|mainnet|custom> (<host>)` from `resolved_network()` before step 0, and every log line of the run carries the network. There is no second confirmation flag: mainnet is the default, and `LIVE_TRADE_OPS=1` is the explicit decision to trade; the banner makes the network visible before the first order.
- **Key/net mismatch.** A testnet key on mainnet (or the reverse) fails the first signed call with `RejectReason::AuthFailed` (§4.6); step 0 turns that into `precondition not met: API key does not belong to <net>` instead of a raw error.

### 5.2 Components (harness code in `live_trade_ops`, exchange-agnostic)

| Component | Responsibility |
|---|---|
| **BookWatcher** | Calls `subscribe_market_data(pair)`, applies `BookSnapshot`/`BookUpdate` with the shared `apply_deltas` helper, and exposes `best_bid()`, `best_ask()`, `snapshot_age()`. Before any price decision it requires a book no older than 2 s; a `Gap` it cannot resync from within 10 s fails the test. Ignores `Trade`/`Candle`. |
| **Pricer** | Reads `get_market_info(pair)` once. Rounds prices to `tick_size` (down for bids, up for asks) and quantities down to `lot_size`; refuses (test failure, before any call) any order whose notional is below `min_notional` or above `LIVE_MAX_NOTIONAL`. Offsets: resting = touch ∓ 2 %, marketable = opposite touch ± 0.3 %. |
| **Countdown** | `wait(secs, watch: RestingOrder)` — sleeps in 1 s ticks, logs remaining time every 5 s, and on each tick checks the BookWatcher: if the opposite touch reaches the resting price, marks the step `touched`. Wall-clock duration is asserted ≥ `secs`. |
| **CappedAccount** | Wraps `&dyn MarketAccount`; `place_order` refuses (returns `InvalidRequest("notional cap …")` — refused locally, nothing sent, per §4.6's narrowed meaning — never reaching the exchange) when `qty × price > LIVE_MAX_NOTIONAL`. A second line of defence behind the Pricer. |
| **Order tagging** | Every order the test places carries a client order id `livetest-{run}-{step}`. Why and how: §5.4. |
| **Journal** | The account the scenarios use is `JournaledAccount(CappedAccount(adapter account), PgOrderJournal)` (§4.7), `origin = livetest`, `run_id = LIVE_RUN_ID`. After every order step the harness reads the row back and asserts: `exchange_order_id` == the ack's id; `status`, `filled_qty`, `avg_fill_price` == the last `get_order`; `Σ exchange_fill.qty == filled_qty`; `settle(exchange_fill rows)` == the settlement the step checked against balances. A journal write failure fails the test (cleanup still runs). |
| **Cleanup guard** | The scenario body runs inside `AssertUnwindSafe(body).catch_unwind()`. Afterwards, **always**: cancel every open order on the pair whose client order id starts with `livetest-` (§5.4), then (margin) repay every non-zero `borrowed + interest` for the pair's base and quote assets — buying back base first when free base is short of the debt (§6.1.1) — or (futures) close any open position with a `reduce_only` marketable order and then restore the leverage and margin type recorded at step 0 (margin type can only change once flat, so this runs after the close). Then re-raise the original panic. `Drop` cannot do this — cleanup is async. A cleanup failure is logged as `LIVE CLEANUP FAILED: <what is left>` and fails the test even if the body passed. |
| **Fill poller** | `await_status(id, want, timeout)` — `get_order` every 1 s until `want` or timeout; for `Filled`, then `get_order_fills` until `Σ fill.qty == filled_qty` (§4.5), and returns `(OrderInfo, Vec<Fill>, Settlement)`. |
| **Settlement check** | Around every filling order: snapshot balances (margin: `margin_balances`; futures: `futures_margin_summary`) before placing and after the fill, and assert the observed change per asset **equals** `Settlement.net_deltas` exactly (margin: to the asset's balance precision, no tolerance; futures: `wallet_balance` change == `realized_pnl − fee`). Also asserts `effective_fee_rate` == `get_fees()` rate for the fill's role (`is_maker` false → taker) to within one unit of the fee asset's precision. Prints the fill report (§5.5). |

### 5.3 The "touched" rule

A resting order can fill if the market moves 2 % in 20 s. That is a market event, not an adapter bug. Before cancelling, the test calls `get_order`:

- still `New` → proceed;
- `Filled`/`PartiallyFilled` and the step was `touched` → step **inconclusive**: log it, clean up the fill (sell it back / close it), repeat the step **once** at ∓ 4 %;
- filled without `touched`, or filled again on the retry → **test failure**.

### 5.4 Test order ids (`livetest-…`)

**What.** Exchanges let the caller attach its own id to every order (Binance `newClientOrderId`, MEXC `newClientOrderId`/`externalOid`; L0 already sends `OrderRequest.client_order_id`). The exchange stores it with the order, returns it from every order and open-orders query, and shows it in the order history. The test sets it on every order it places:

```
livetest-{run}-{step}        e.g.  livetest-3f9a1c2e-m1-buy-rest
  run  = first 8 hex chars of LIVE_RUN_ID (a fresh uuid per run)
  step = short step code: m1-buy-rest, m3-buy-fill, m4-sell-rest, m6-sell-fill,
         f2-buy-rest, f3-buy-fill, f7-close, cl-close (cleanup), …
```

To stay portable across exchanges the id uses only `[a-z0-9-]` and at most 32 characters (the longest above is 29; Binance allows 36). An adapter whose exchange cannot carry a client id must say so with `NotSupported` on `place_order` with an id — the harness then cannot run (tagging is a safety requirement, not optional).

**Why.** Three concrete jobs, each of which fails without it:

1. **Cleanup cancels only the test's own orders.** Without a tag, cleanup could only "cancel every open order on the pair". That is safe on an empty sub-account but destructive the day anything else trades on that account (a manual order, the executor itself). With the tag, cleanup and step 0 filter on the `livetest-` prefix and never touch an order they did not place.
2. **Leftovers from a crashed run are recognisable** — first from the DB (`unfinished(exchange, "livetest")`, §4.7: every order ever sent has a row, even one whose ack never came back), then confirmed on the exchange by the tag. If the process dies mid-run (container killed, network loss), the resting order stays on the exchange, and the new process has no memory of its exchange order id. The tag is on the exchange side, so the next run's step 0 finds it, cancels it, and logs which run and step left it. Any open order *without* the tag is someone else's, so the run aborts rather than trade next to it.
3. **A human can see what happened.** In the exchange's order history, `livetest-3f9a1c2e-m3-buy-fill` says at a glance that this was the live test, which run (matching `LIVE_RUN_ID` in the test log) and which step, with no need to correlate timestamps.

It is **not** used for de-duplication: the test never retries a `place_order` call on its own, so there is nothing to deduplicate.

**L0 change this needs.** `OrderInfo` (shared type) has no client-id field today, so open orders cannot be filtered by tag. Add `client_order_id: Option<String>` to `OrderInfo`, parsed by each adapter from its exchange's field (Binance `clientOrderId`) on spot, margin and futures; `None` when absent. Every place that constructs `OrderInfo` (fakes in `execution`, `orchestrator/no_trade.rs`, paper account, MEXC adapter) sets `None` or its own value — a mechanical change, covered by existing tests plus one wiremock parsing test per kind.

### 5.5 Fill report

Printed (`--nocapture`) after every filled order, and appended to `target/live-trade-ops/{run}.jsonl` for later reading:

```
[livetest-3f9a1c2e-m3-buy-fill] margin BUY LINKUSDT  fills=2 (taker)
  ordered   0.80 LINK @ ≤ 15.045
  executed  0.80 LINK @ avg 15.0000        gross 12.0000 USDT
  fee paid  0.00080 LINK  (≈ 0.0120 USDT, rate 0.1000 %, expected taker 0.1000 %)
  resulting LINK +0.79920   USDT −12.0000   net price 15.0150 USDT/LINK
  balances  LINK 0.00000 → 0.79920 (expected 0.79920, diff 0)
            USDT 40.0000 → 28.0000 (expected 28.0000, diff 0)
```

Fields map one-to-one to `Settlement`, so the report is also the record of *paid amount* (gross + fee) and *resulting funds* (net deltas and balances) per order.

## 6. Scenarios

### 6.1 Margin — `adapter.margin()` + `adapter.margin_ops()`, cross margin, `LIVE_PAIR` (base/quote from `get_market_info`; Binance run: LINK/USDT)

Asset names below (LINK, USDT) are the Binance run's; the harness uses the pair's base and quote.

| # | Action | Price source | Assertions |
|---|---|---|---|
| 0 | `margin_balances`, `get_account_state`, BookWatcher warm-up, journal check | — | Unfinished `livetest` rows in the DB from earlier runs are reconciled first: looked up on the exchange by client order id, cancelled if still open, final status and fills written back (logged). Any open `livetest-` order on the exchange with **no** DB row is a failure (`order sent without a journal row`) — that must be impossible (§4.7). Then: USDT free ≥ 2 × `LIVE_MAX_NOTIONAL`; **no other** open orders on the pair; `borrowed == 0` for LINK and USDT. Otherwise **abort without trading** (not a failure: `precondition not met`). |
| 1 | limit BUY, qty = `LIVE_MAX_NOTIONAL × 0.8 / price` | bid × 0.98 | ack `New`; `get_order` → `New`, `filled_qty == 0`; USDT `locked` rose by ≈ qty × price |
| 2 | Countdown `LIVE_WAIT_SECS`, then `get_order` (§5.3), then `cancel_order` | — | `get_order` → `Cancelled`; USDT `locked` back to its step-0 value |
| 3 | limit BUY, same qty | ask × 1.003 | `await_status(Filled, 10 s)`; `filled_qty == qty`; `avg_price ≤ order price`; every fill `is_maker == false`; **Settlement check**: every asset's `free` Δ == `net_deltas` (Binance, no BNB: LINK Δ == `filled_qty − fee`, USDT Δ == `−gross_quote`) |
| 4a | **Sell funding** — `ensure_sell_funds(qty_sell)` (§6.1.1), `qty_sell` = same target qty as the buys (`LIVE_MAX_NOTIONAL × 0.8 / price`, rounded to lot) | — | after it, LINK `free ≥ qty_sell`; if it borrowed: `borrowed[LINK]` rose by exactly `b_sell`, `free[LINK]` rose by `b_sell`. Report line: `sell funding: free <f>, needed <q>, borrowed <b_sell> LINK` or `… no borrow needed` |
| 4 | limit SELL, qty = `qty_sell` | ask × 1.02 | `New`; LINK `locked` rose by qty |
| 5 | Countdown, `get_order` (§5.3), `cancel_order` | — | `Cancelled`; LINK `locked` back to its step-4a value |
| 6 | limit SELL, qty = `qty_sell` | bid × 0.997 | `await_status(Filled, 10 s)`; `avg_price ≥ order price`; **Settlement check**: every asset's Δ == `net_deltas` (Binance: LINK Δ == `−filled_qty`, USDT Δ == `gross_quote − fee`). Round-trip line in the report: USDT spent (step 3) vs USDT received (step 6), total fees in USDT, LINK left |
| 6b | **Close the sell funding** — only if 4a borrowed: marketable BUY (ask × 1.003) of `buyback = ceil_lot(max(b_sell + interest[LINK] − free[LINK], min_order_qty))`, then `repay(LINK, borrowed + interest)` | ask × 1.003 | BUY filled, **Settlement check** as step 3; after repay `borrowed[LINK] == 0`, `interest[LINK] == 0`. Report: LINK dust left after repay |
| 7 | `max_borrowable(LINK)`, `max_borrowable(USDT)`; `borrow(LINK, b_link)`; `borrow(USDT, 10)` where `b_link` = 10 USDT worth of LINK rounded to lot | — | each `max_borrowable` ≥ amount; after each borrow, `borrowed` rose by exactly the amount and `free` rose by the amount; `interest > 0` (Binance charges the first hour on borrow) |
| 8 | `repay(asset, borrowed + interest)` for LINK then USDT | — | `borrowed == 0` and `interest == 0` for both. The LINK dust left after step 6 pays LINK interest; if it is below interest, the test tops up with a tiny marketable BUY first (logged). |
| — | Cleanup guard | — | no `livetest-` open orders on the pair; `borrowed == 0` both assets |

#### 6.1.1 `ensure_sell_funds(qty)` — make sure a sell can be placed

Sell steps must not depend on the buy leg having delivered enough base asset (fees reduce what step 3 delivers; step 3 may be skipped or inconclusive; a later exchange may run the sell leg on its own). Before the first sell, the harness makes the base-asset balance sufficient, borrowing if it is not:

1. `free = margin_balances()[base].free`. If `free ≥ qty` → no borrow, return `0`.
2. `shortfall = qty − free`. Borrowing a tiny shortfall would leave a loan too small to buy back (below the exchange's minimum order), so the loan is sized to be closable: `b_sell = ceil_lot(max(shortfall, min_order_qty))`, where `min_order_qty = ceil_lot(1.1 × min_notional / ask)` (from `get_market_info`).
3. Refuse (test failure, before borrowing) if `b_sell × ask > LIVE_MAX_NOTIONAL` — the notional cap covers loans too.
4. `max_borrowable(base) ≥ b_sell`, else **abort, precondition not met** (`cannot fund sell: max_borrowable <m> < <b_sell>`).
5. `borrow(base, b_sell)`; re-read balances; assert `free ≥ qty`. Record `b_sell` for step 6b and the cleanup guard.

If the adapter has no `margin_ops()` (spot-only exchange), step 2 onwards cannot run: the sell steps are `SKIPPED (not supported: cannot fund sell)` when funds are short, and run normally when they are not (D8).

On the Binance run this normally triggers: step 3 buys `qty` but receives `qty − fee`, so step 4a borrows `min_order_qty` worth of LINK (≈ 5.5 USDT) — which also puts a real **borrow-to-sell (short) path** under test, not only the explicit borrow/repay of steps 7–8. The buy leg's funding stays a precondition (step 0: USDT free ≥ 2 × `LIVE_MAX_NOTIONAL`); the same helper can fund it later if needed.

The same helper is used by the cleanup guard: if a base loan is outstanding and free base is below `borrowed + interest`, cleanup first buys back the difference (tagged `cl-buyback`, marketable, rounded up to `min_order_qty`) and then repays.

### 6.2 Futures — `adapter.futures()` + `adapter.futures_ops()`, testnet or mainnet per `EXCHANGE_NETWORK`, one-way mode, `LIVE_PAIR`

Identical steps and assertions on both networks. Steps 0–6 as in §6.1, with these differences: step 0 also requires no open position, `is_hedge_mode() == false`, and `available_balance ≥ 2 × LIVE_MAX_NOTIONAL` (else abort, precondition not met), and **records the pair's current leverage and margin type** (from `position_risk`) so cleanup can restore them — on mainnet these are the real account's settings for LINKUSDT and must not be left changed; step 6 is `reduce_only`; balance assertions use `futures_margin_summary` instead of free/locked. **Sell funding on futures** (4a): there is nothing to borrow — a sell needs margin, not the base asset. 4a becomes `ensure_sell_margin`: `available_balance ≥ qty × price / leverage + fee` for the resting SELL of step 4 (step 6 is `reduce_only` and needs none); if not, abort, precondition not met. Step 6b does not exist on futures. Borrowing (steps 7–8) does not exist on futures and is replaced by:

| # | Action | Assertions |
|---|---|---|
| F1 | `set_margin_type(Isolated)`, `set_leverage(5)` | `set_leverage` returns 5; `position_risk` (flat) reports `leverage == 5`, `margin_type == Isolated` |
| F2 | resting limit BUY at bid × 0.98 | `total_open_order_initial_margin` ≈ notional / 5 (tolerance: 1 tick × qty + fee); after `cancel_order` it returns to its pre-order value |
| F3 | marketable limit BUY at ask × 1.003 | filled; **Settlement check**: `wallet_balance` Δ == `−fee` (USDT), `realized_pnl == 0`; `position_risk`: `size == qty`, `initial_margin` ≈ notional / 5, `liquidation_price` within 0.5 % of `LiqCalc` (§6.3) using the bracket from `leverage_brackets` |
| F4 | `set_leverage(10)` then `set_leverage(3)` with the position open | each returns the requested value (or a rejection, recorded with its `RejectReason` and exchange code); after each, record `isolated_margin`, `initial_margin`, `liquidation_price`, `available_balance`. **Observation step — no expected value asserted** beyond "call answered and position still open" (see below) |
| F5 | negative: `set_leverage(bracket.max_leverage + 1)` | `Err`, `reason() == Some(LeverageNotAllowed)` (exchange code logged) |
| F6 | negative: `set_margin_type(Cross)` with the position open | `Err`, `reason() == Some(MarginModeChangeBlocked)` |
| F7 | `reduce_only` marketable SELL for the full size | **Settlement check**: `wallet_balance` Δ == `realized_pnl − fee`; `realized_pnl` == `(exit_avg − entry_avg) × qty` within one tick × qty; `position_risk` → `None`; no open orders. Round-trip line: total fees (F3 + F7), realized PnL, net wallet change |

F4 is deliberately an observation, not an assertion: how the exchange treats an **open isolated** position when leverage changes (whether margin is moved in/out of the position, whether a decrease is refused without extra margin, whether the liquidation price moves) is not something this spec states from memory. The first testnet run records it; the plan then turns the observed behaviour into assertions and into `LiqCalc` / L3 risk-code expectations. Until then, L3 must not assume a leverage change re-prices an open position's liquidation.

### 6.3 Liquidation / margin calculator (pure, unit-tested)

In `live_trade_ops::risk` (test-only today; promote to `exchange_adapter` if `execution` needs it). For a single isolated one-way position:

```
initial_margin = qty × entry / leverage
liq_long  = (qty × entry − isolated_margin − cum) / (qty × (1 − mmr))
liq_short = (qty × entry + isolated_margin + cum) / (qty × (1 + mmr))
```

where `mmr` and `cum` come from the bracket whose notional range contains `qty × mark`. Example: long, leverage 10, `mmr` 1 %, `cum` 0 → liq ≈ entry × 0.9 / 0.99 ≈ 0.909 × entry.

The F3/F4 run appends `(exchange, net, run_date, qty, entry, leverage, isolated_margin, mmr, cum, exchange_liq_price)` — `qty` is **signed**: positive for a long, negative for a short, matching the exchange's own `positionAmt` convention, so the row needs no separate side column to `crates/live_trade_ops/tests/fixtures/futures_liq_golden.json`. Rows carry `exchange` and `net` because brackets (Binance leverage brackets, MEXC risk-limit tiers) differ per exchange and between testnet and mainnet. The formula above is Binance's; a exchange whose rows it does not fit gets its own `LiqCalc` variant selected by `exchange` — decided when that exchange's first rows exist. A normal (non-ignored) unit test asserts `LiqCalc` matches every golden row within 0.5 %; the calculator is accepted for production on a exchange only once at least one `mainnet` row for that exchange exists. The live test is the source of truth; the calculator is what `execution` actually uses.

## 7. Known risks the first run is expected to expose

1. **Borrow endpoint.** L0 uses `POST /sapi/v1/margin/borrow-repay` (§4.2); the older `/sapi/v1/margin/loan` / `/repay` pair is believed retired. The first margin run confirms the new endpoint works and records the captured response as the wiremock fixture.
2. **Price filters.** `MarketInfo` carries tick/lot/min-notional but not Binance's `PERCENT_PRICE_BY_SIDE` (spot/margin) or `PERCENT_PRICE` (futures, typically ±5 % of mark). The 2 % / 4 % offsets are inside those; a `PriceOutsideBand` rejection is a test failure with exchange code and message printed, not a silent retry.
3. **`get_order` depends on an in-memory `orderId → symbol` cache** (adapter NOTES.md). Fine here — the same process places every order — but cleanup must use `get_account_state().open_orders` (filtered by the `livetest-` tag, §5.4), not `get_order`, to find leftovers from a crashed earlier run.
4. **Funding payments move the futures wallet.** If a funding time falls between F3 and F7, `wallet_balance` also changes by the funding fee, which is not a fill. Funding schedules differ per exchange, so the harness reads `get_extended_market_data(pair).next_funding_time` (already in the trait) instead of hard-coding hours; step 0 refuses to start a futures run within 5 minutes of it (if the adapter returns `None`, it logs that and proceeds); a run that still straddles one fails the settlement check with `funding interval crossed` rather than a fee mismatch.
5. **Account polling cadence.** `subscribe_account_updates` is a 3 s poll-diff; the test does not use it — assertions poll `get_order`/balances directly.

## 8. Safety summary

- Opt-in twice (`#[ignore]` + `LIVE_TRADE_OPS=1`); never in CI.
- The two live tests share one test binary and are serialized in code by a process-wide guard, so a no-name-filter `--ignored` run cannot interleave margin and futures against one account. That guard is **in-process only**: two operators, or a stray second container, would each hold their own and could still collide on the same sub-account. One run at a time is a procedural rule at the human gate, not a code guarantee.
- Notional capped twice (Pricer, CappedAccount) at `LIVE_MAX_NOTIONAL`, default 15 USDT.
- Dedicated sub-account, API key with withdrawals disabled. Every exchange/kind defaults to **mainnet**; testnet only with `EXCHANGE_NETWORK=testnet`. The network is always announced by the banner. Trading is gated by the arming flag `LIVE_TRADE_OPS=1`, not by the network default. An unknown value, or `testnet` for an exchange/kind that has none, is a config error, never a fallback.
- Futures cleanup restores the pair's leverage and margin type to their pre-run values.
- Precondition check before any order; unconditional cleanup after; a leftover is a failure, loudly.
- Worst case if the process dies mid-run: one resting order ≤ 15 USDT and loans ≤ `LIVE_MAX_NOTIONAL` per asset (sell-funding loan of §6.1.1 or the step-7 loans) on the sub-account, or (futures mainnet) one open position ≤ 15 USDT notional at ≤ 10× leverage plus a changed leverage/margin-type setting on LINKUSDT — the orders identifiable by the `livetest-` client order id tag (§5.4).

## 9. Acceptance criteria

- [ ] §4 L0 additions implemented with wiremock tests; `docker compose run --build --rm test` green.
- [ ] `crates/live_trade_ops` exists; `cargo tree -i live_trade_ops` shows no workspace dependents; the journal lives in `crates/order_journal`, which depends on no adapter crate and not on `live_trade_ops` (amended 2026-09-25); only its `registry` module imports adapter crates; offline self-test against `ScriptedExchange` runs in the normal test suite and covers cleanup-after-panic, touched rule, settlement, capability skips and `LIVE_REQUIRE_ALL`.
- [ ] `live_trade_ops::registry` builds Binance and MEXC from `EXCHANGE`; orchestrator unchanged apart from compile-only ripples.
- [ ] `EXCHANGE=mexc` runs both scenarios end to end on MEXC mainnet with `LIVE_REQUIRE_ALL` unset: implemented steps pass, the rest report `SKIPPED (not supported)`, cleanup leaves nothing behind.
- [ ] `cargo test` (no flags) still never touches the network.
- [ ] `AdapterError::Rejected(Rejection)` + `RejectReason` in `exchange_adapter` (no test-only variants); Binance and MEXC route every exchange refusal through their `classify`; one unit test per table row; MEXC envelope code preserved; `no_trade.rs`, `execution` fake and MEXC tests updated; workspace green.
- [ ] Every live-run assertion on a refusal uses `RejectReason`, never a exchange code; every `UNMAPPED` line from the runs is triaged into a table row.
- [ ] `get_order_fills` implemented for Binance spot/margin/futures with wiremock tests (MEXC returns `NotSupported` until its spec); `settle` unit tests green (every table row, multi-fill, mixed maker/taker, BNB fee, zero fills).
- [ ] Order journal (§4.7, `crates/order_journal`): migration `0008` applied (`SCHEMA_VERSION` 8, migration test updated); `PgOrderJournal` integration tests in Docker (intent-before-send, ack, rejection, forward-only status, idempotent fills, `unfinished`); `JournaledAccount` unit tests prove no order is sent when `record_intent` fails.
- [ ] After every live run: every order the run placed has an `exchange_order` row with its exchange order id and terminal status; every fill has an `exchange_fill` row; fees from the DB rows equal the settlement checked against balances; no `livetest` row left unfinished.
- [ ] Sell funding (§6.1.1): margin run shows the 4a borrow and 6b buy-back + repay in its report, ending with `borrowed == 0`; offline self-test covers free ≥ qty (no borrow), small shortfall (loan sized to `min_order_qty`), `max_borrowable` too low (abort), no `margin_ops()` (skip), and cleanup buy-back after a panic between 4a and 6b.
- [ ] In every live run, every filled order's observed balance change equals `Settlement.net_deltas` (margin exact; futures `realized_pnl − fee`), and every fee rate matches `get_fees()`.
- [ ] `EXCHANGE_NETWORK` implemented in the common `AdapterConfig` with **mainnet as the default** (unset → mainnet; `config.rs` testnet defaults and their tests updated), with host tables for Binance and MEXC and unit tests (every row, unset / invalid, override precedence, `Custom`); `test` service passes `EXCHANGE_NETWORK` through.
- [ ] `live_futures_trade_ops` passes with `EXCHANGE_NETWORK=testnet`; golden rows written; `LiqCalc` unit test green against them.
- [ ] `live_futures_trade_ops` passes with `EXCHANGE_NETWORK=mainnet` — same code, only the env file changed; mainnet golden rows appended; leverage/margin type verified restored after the run.
- [ ] `live_margin_trade_ops` passes on mainnet sub-account; cleanup verified by an independent `margin_balances` + open-orders check after the run.
- [ ] L0 Stage 1 checkboxes listed at the top of this spec ticked in [layers/L0-exchange-adapter.md](layers/L0-exchange-adapter.md), with the run date.
- [ ] §7.1 outcome recorded (borrow-repay endpoint confirmed on mainnet).
