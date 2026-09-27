# Live Trade-Operations Test (exchange-agnostic, Binance first) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan layer-by-layer. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status 2026-09-25: implemented and merged.** Layers 1–7 complete, merged into `layer-implementation` as `125a7f3`. Tasks 7.2–7.6 (the live runs and their doc updates) were NOT done; they and every carried-forward defect are specified in [`../specs/2026-09-25-live-trade-ops-remaining-design.md`](../specs/2026-09-25-live-trade-ops-remaining-design.md). Run artefacts and the SDD ledger: [`../references/live-trade-ops-2026-09/`](../references/live-trade-ops-2026-09/).

**Goal:** A live test, written once against the L0 traits and run per exchange via `EXCHANGE`, that places, rests, cancels and fills real orders, funds sells by borrowing, borrows/repays, exercises futures leverage, accounts every fill's fees against real balances, and persists every order in Postgres — green on Binance margin (mainnet), futures (testnet + mainnet), and runnable on MEXC with unimplemented parts reported `SKIPPED`.

**Spec:** [`external/executor/specs/2026-09-22-live-trade-ops-l0-test-design.md`](../specs/2026-09-22-live-trade-ops-l0-test-design.md) (approved 2026-09-22). Section refs (§) below point into it; read it alongside this plan.

**Scope:** executor exchange connector (L0) testing only — no `main/`, no orchestrator/`execution` behaviour change.

**Architecture:** Production crates get only connector capabilities: common types and traits in `exchange_adapter`; host table, error table and new endpoints in `exchange_adapter_binance` / `_mexc`. Everything test-only — registry, `settle`, `LiqCalc`, order journal (in-memory + Postgres), harness, scenarios, fake exchange, runner — lives in the new crate `live_trade_ops`, which nothing depends on. Shared infrastructure change: migration 0008 only.

**Tech stack:** Rust workspace (`tokio`, `reqwest`, `rust_decimal`, `sqlx`/Postgres, `wiremock`), Docker Compose. Workspace: `trade_executor/.worktrees/layer-implementation`.

**Note on layer taxonomy:** `layer-first-planning`'s layer table describes the Python trading pipeline, not the executor; like [2026-09-21-indicator-panel-plan.md](2026-09-21-indicator-panel-plan.md), this plan applies that skill's *principles* (Docker first, interface before code, RED integration test at each boundary, no layer started before the previous is green in Docker) over `trade_executor`'s real layers.

---

## Global Constraints

- **Scope: testing the executor's exchange connector only** (spec header). No `main/` work. No behaviour change in `orchestrator`, `execution`, `market_data`, `mq_gateway`; edits there are compile-only ripples of shared-type changes (`AdapterConfig`, `AdapterError::Rejected`, `OrderInfo`, `MarketInfo`) and must keep their existing tests green unchanged in meaning.
- **Branch:** cut `live-trade-ops` from `layer-implementation` inside the `layer-implementation` worktree before the first change; merge back after Layer 7's human-gated runs. One commit per layer, after that layer is green in Docker. **Standing authorization (user, 2026-09-22): local commits on branch `live-trade-ops` are pre-approved — commit each task without asking. Push and merge still require explicit user confirmation.**
- **No implementation code in this plan** — signatures and test descriptions only.
- **Live runs spend real money.** Every Layer 7 run is a separate human gate: stop, show the env file (keys redacted) and the banner, wait for an explicit "go" for *that* run.
- **`cargo test` with no flags never touches the network.** Live tests are `#[ignore]` + `LIVE_TRADE_OPS=1`.
- **`EXCHANGE_NETWORK` default = `mainnet`** (spec §4.3). Unknown value, or `testnet` for an exchange/kind without one, is a `ConfigError`, never a fallback.
- **Arming flag has no default:** `LIVE_TRADE_OPS=1`.
- **`LIVE_MAX_NOTIONAL` default 15** (quote units); applies to orders **and** loans.
- **Client order id format** `livetest-{run8}-{step}`, only `[a-z0-9-]`, ≤ 32 chars (spec §5.4).
- **Test machinery stays out of production crates.** Everything test-only lives in `crates/live_trade_ops`; no workspace crate depends on it (`cargo tree -i live_trade_ops`). Inside it, only `registry.rs` imports adapter crates; harness/scenarios never compare an exchange name.
- **Callers branch on `RejectReason`, never on exchange codes** (spec §4.6).
- **Journal fails closed:** no order is sent unless `record_intent` committed (spec §4.7).
- **Additive migrations only** — never edit 0001–0007 (sqlx checksums; see 0002's header). `SCHEMA_VERSION` 7 → 8.
- **Wiremock fixtures for new endpoints are captured from real responses** during Layer 7 and replace hand-written ones; until then, hand-written fixtures are marked `// from docs — replace with capture`.
- **Gate command while RED-until-later tests exist:** `cargo test --workspace` stops at the first failing target, so a deliberately-RED integration test hides every later crate's result. Until Layer 3 closes them, the layer gate is `docker compose run --build --rm test cargo test --workspace --no-fail-fast`, and "green" means: no failures other than the known RED cases listed in the ledger.
- **A RED test must still compile.** Never add a RED case that references a function a later task creates — a compile error aborts the entire run with zero tests executed. Defer that case to the task that creates the function.
- **Trait growth uses default methods** where the spec allows (`margin_ops`/`futures_ops` → `None`, `get_order_fills` → `Err(NotSupported)`), so implementors that do not support a capability need no change.

---

## Docker Entry Points

From `trade_executor/.worktrees/layer-implementation`:

```bash
# Every layer's gate. --build is mandatory (stale test image otherwise).
docker compose run --build --rm test

# One crate while iterating
docker compose run --build --rm test cargo test -p exchange_adapter
docker compose run --build --rm test cargo test -p exchange_adapter_binance
docker compose run --build --rm test cargo test -p live_trade_ops

# Migrations (unchanged entry point, now reaches 0008)
docker compose run --rm executor --migrate-only

# Layer 7 live runs (human-gated, one at a time)
docker compose run --build --rm --env-file configs/live-trade-ops/binance.futures.testnet.env test \
  cargo test -p live_trade_ops --test live_trade_ops live_futures -- --ignored --nocapture --test-threads=1
docker compose run --build --rm --env-file configs/live-trade-ops/binance.futures.mainnet.env test \
  cargo test -p live_trade_ops --test live_trade_ops live_futures -- --ignored --nocapture --test-threads=1
docker compose run --build --rm --env-file configs/live-trade-ops/binance.margin.mainnet.env test \
  cargo test -p live_trade_ops --test live_trade_ops live_margin -- --ignored --nocapture --test-threads=1
docker compose run --build --rm --env-file configs/live-trade-ops/mexc.futures.mainnet.env test \
  cargo test -p live_trade_ops --test live_trade_ops live_futures -- --ignored --nocapture --test-threads=1
```

The `test` service must pass through the live vars. Task 4.1 adds to `docker-compose.yml` `test.environment`: `LIVE_TRADE_OPS`, `LIVE_PAIR`, `LIVE_MAX_NOTIONAL`, `LIVE_WAIT_SECS`, `LIVE_RUN_ID`, `LIVE_REQUIRE_ALL`, `EXCHANGE`, `EXCHANGE_NETWORK`, `MARKET_KIND`, `API_KEY`, `API_SECRET`, `FUTURES_API_KEY`, `FUTURES_API_SECRET`, `DATABASE_URL` — each as `${VAR:-}` so an unset var stays unset.

Verified: [ ] `docker compose run --build --rm test` green on the branch before Layer 1 starts (baseline).

---

## Layer 1: `exchange_adapter` — common types and traits (connector capabilities)

Everything later layers compile against. No I/O in this layer except the harness-free decorator logic.

### Task 1.1: Common enums, config network, env loader

**Files:**
- Create: `crates/exchange_adapter/src/config.rs` (re-exported from `lib.rs`); move `AdapterConfig` there
- Test: same files, `#[cfg(test)]`

**Interface:**
```rust
pub enum MarketKind { Spot, Margin, Futures }                 // common; Binance's crate-private enum re-points to it in Layer 2
pub enum Exchange { Binance, Mexc, Local }
pub enum Network { Testnet, Mainnet }
pub enum ResolvedNetwork { Testnet, Mainnet, Custom(Url) }
pub struct AdapterConfig { /* existing fields */ pub network: Network, pub rest_base_url: Option<Url>, pub ws_base_url: Option<Url>, /* … */ }
pub struct Hosts { pub rest: Url, pub ws: Url }
pub enum ConfigError { Missing(String), Invalid { var: String, reason: String }, NoTestnet { exchange: Exchange, kind: MarketKind } }
impl AdapterConfig {
    pub fn from_env(prefix: &str) -> Result<AdapterConfig, ConfigError>;                                   // = from_env_with(prefix, |k| std::env::var(k).ok())
    pub fn from_env_with(prefix: &str, get: impl Fn(&str) -> Option<String>) -> Result<AdapterConfig, ConfigError>;
}
```
`rest_base_url`/`ws_base_url` become `Option` (overrides). `from_env` reads `{prefix}API_KEY`, `{prefix}API_SECRET`, optional `{prefix}REST_BASE_URL`/`{prefix}WS_BASE_URL`, and un-prefixed `EXCHANGE_NETWORK`.

**Unit tests (RED first):**
- `EXCHANGE_NETWORK` unset → `Mainnet`; `testnet` → `Testnet`; `mainnet` → `Mainnet`; `MAINNET`/`prod`/`""` → `ConfigError::Invalid`.
- Missing `API_KEY` → `ConfigError::Missing("API_KEY")`; prefix honoured (`FUTURES_API_KEY`).
- Override URL present → `Some(url)`; malformed URL → `Invalid`.
- `Debug` of `AdapterConfig` still redacts key/secret.
Tests call `from_env_with` with a `HashMap` lookup — never mutate the process environment (tests run in parallel).

**Notes:** `AdapterConfig` field type change ripples to Binance `config.rs`, MEXC config, orchestrator `adapter_config_from_env` (compile-only: it keeps requiring its URL vars and passes them as `Some(url)` overrides, `network: Mainnet` — behaviour identical), `testnet_integration.rs`, `live_credentials.rs` — fix the compile there in the same task (behaviour moves in Layers 2/3/5).

### Task 1.2: Rejection model

**Files:** Modify `crates/exchange_adapter/src/lib.rs` (new `src/error.rs` re-exported); mechanical updates in `crates/orchestrator/src/no_trade.rs`, `crates/execution/src/tests.rs`, `crates/exchange_adapter_binance/src/rest.rs`, `crates/exchange_adapter_mexc/src/{http.rs,dto_futures.rs}`, `crates/exchange_adapter_mexc/tests/futures_wiremock_tests.rs`.

**Interface:**
```rust
pub enum AdapterError { Stale, RateLimited, InvalidRequest(String), Rejected(Rejection), Network(String), NotSupported }
pub struct Rejection { pub reason: RejectReason, pub exchange: Exchange, pub code: Option<String>, pub http_status: Option<u16>, pub message: String }
pub enum RejectReason { InsufficientBalance, InsufficientMargin, InvalidPrice, InvalidQuantity, BelowMinNotional, PriceOutsideBand,
    PostOnlyWouldTake, ReduceOnlyRejected, OrderNotFound, OrderNotCancellable, LeverageNotAllowed, MarginModeChangeBlocked,
    AlreadySet, BorrowLimitExceeded, RepayExceedsDebt, AssetNotBorrowable, AuthFailed, ClockSkew, MarketClosed,
    Disarmed, Unknown }
impl AdapterError { pub fn reason(&self) -> Option<RejectReason>; pub fn is_retryable(&self) -> bool; }
```

**Unit tests (RED):** `reason()` is `Some` only for `Rejected`; `is_retryable` true exactly for `RateLimited`, `Network(_)`, `Rejected{ClockSkew}`; `Display` = `rejected: {message} [{exchange} {code}]` (code part omitted when `None`).

**Mechanical updates (compile-only in this task, real mapping in Layers 2/3):**
- `no_trade.rs`: `Rejection { reason: Disarmed, exchange: Local, code: None, http_status: None, message: "execution disarmed: EXECUTION_MODE=no_trade" }`; its tests assert `reason() == Some(Disarmed)`.
- `execution/src/tests.rs` fake: `Rejection { reason: Unknown, exchange: Local, … "forced test failure" }`.
- Binance `rest.rs` and MEXC `http.rs`/`dto_futures.rs`: temporarily `reason: Unknown` with code/message extracted as today — replaced by `classify` in Layers 2/3. MEXC test `msg.contains("insufficient balance")` → match on `Rejected(r) if r.message.contains(...)` for now; becomes `reason()` in Layer 3.

### Task 1.3: Order info client id, fills

**Files:** Modify `crates/exchange_adapter/src/lib.rs`; mechanical `client_order_id: None` in every `OrderInfo { … }` literal (binance `parsing.rs`, mexc `dto.rs`×2 / `futures.rs` / `account_diff.rs`, `execution/src/{paper.rs,tests.rs}`, `market_data/src/pg/rows.rs`×5, `market_data/tests/common/mod.rs`, `orchestrator/src/{no_trade.rs,tests.rs}`, `state_store/tests/pg_store.rs`×2).

**Interface:**
```rust
pub struct OrderInfo { /* existing */ pub client_order_id: Option<String> }
pub struct Fill { pub trade_id: String, pub order_id: OrderId, pub pair: Pair, pub side: Side, pub price: Decimal, pub qty: Decimal,
                  pub quote_qty: Decimal, pub fee: Decimal, pub fee_asset: String, pub is_maker: bool,
                  pub realized_pnl: Option<Decimal>, pub ts: Ts }
// on MarketAccount, default method:
async fn get_order_fills(&self, id: OrderId) -> Result<Vec<Fill>, AdapterError> { Err(AdapterError::NotSupported) }
```
`MarketInfo` gains `base_asset: String, quote_asset: String` (the harness derives base/quote from it). In this task every constructor sets them to `String::new()` to compile; Layer 2 (Binance `baseAsset`/`quoteAsset`) and Layer 3 (MEXC spot `baseAsset`/`quoteAsset`, futures `baseCoin`/`quoteCoin`) populate them, each with a wiremock test. The harness refuses to run on an empty asset name.

**Unit tests (RED):** a `MarketAccount` that does not override `get_order_fills` returns `Err(NotSupported)`; `Fill` and `OrderInfo` round-trip through `serde` if they derive it (match the existing derive set).

### Task 1.4: Margin/futures ops traits

**Files:** Modify `crates/exchange_adapter/src/lib.rs` (new `src/ops.rs`).

**Interface:**
```rust
pub trait ExchangeAdapter { /* existing */ fn margin_ops(&self) -> Option<&dyn MarginOps> { None } fn futures_ops(&self) -> Option<&dyn FuturesOps> { None } }
#[async_trait] pub trait MarginOps: Send + Sync {
    async fn borrow(&self, asset: &str, amount: Decimal) -> Result<(), AdapterError>;
    async fn repay(&self, asset: &str, amount: Decimal) -> Result<(), AdapterError>;
    async fn max_borrowable(&self, asset: &str) -> Result<Decimal, AdapterError>;
    async fn margin_balances(&self) -> Result<Vec<MarginBalance>, AdapterError>;
}
pub struct MarginBalance { pub asset: String, pub free: Decimal, pub locked: Decimal, pub borrowed: Decimal, pub interest: Decimal, pub net_asset: Decimal }
pub enum MarginType { Cross, Isolated }
#[async_trait] pub trait FuturesOps: Send + Sync {
    async fn set_leverage(&self, pair: &Pair, leverage: u32) -> Result<u32, AdapterError>;
    async fn set_margin_type(&self, pair: &Pair, t: MarginType) -> Result<(), AdapterError>;
    async fn leverage_brackets(&self, pair: &Pair) -> Result<Vec<LeverageBracket>, AdapterError>;
    async fn position_risk(&self, pair: &Pair) -> Result<Option<FuturesPosition>, AdapterError>;
    async fn futures_margin_summary(&self) -> Result<FuturesMarginSummary, AdapterError>;
    async fn is_hedge_mode(&self) -> Result<bool, AdapterError>;
}
pub struct LeverageBracket { pub notional_floor: Decimal, pub notional_cap: Decimal, pub max_leverage: u32, pub maint_margin_ratio: Decimal, pub cum: Decimal }
pub struct FuturesPosition { pub pair: Pair, pub side: Side, pub size: Decimal, pub entry_price: Decimal, pub mark_price: Decimal, pub leverage: u32,
                             pub margin_type: MarginType, pub isolated_margin: Decimal, pub initial_margin: Decimal, pub maint_margin: Decimal, pub liquidation_price: Decimal }
pub struct FuturesMarginSummary { pub wallet_balance: Decimal, pub available_balance: Decimal, pub total_initial_margin: Decimal,
                                  pub total_open_order_initial_margin: Decimal, pub total_position_initial_margin: Decimal }
```
**Unit tests (RED):** default `margin_ops()`/`futures_ops()` return `None` on an adapter that does not override them; `MarginType` / structs construct with the exact field sets above (compile-level).

### Integration test → Layer 2 (RED in Docker)

`crates/exchange_adapter_binance/tests/wiremock_tests.rs`, new cases written now, RED until Layer 2: `get_order_fills` margin/futures parse; `margin_ops().borrow` sends `POST /sapi/v1/margin/borrow-repay type=BORROW`; `futures_ops().set_leverage`; a `-2010 insufficient balance` body classifies to `InsufficientBalance`; `EXCHANGE_NETWORK=testnet` + margin → `ConfigError::NoTestnet`.

**Layer 1 gate:** `docker compose run --build --rm test` — Layer 1 unit tests green, the Layer 2 integration tests above RED (compile, fail), everything else green. Commit (after user confirmation): `feat(exchange_adapter): common kinds, network config, rejections, fills, ops traits`.

---

## Layer 2: `exchange_adapter_binance`

### Task 2.1: Host table, config, `resolved_network`

**Files:** `crates/exchange_adapter_binance/src/config.rs`, `adapter.rs`, `kind.rs`.
**Interface:** `pub fn hosts(network: Network, kind: MarketKind) -> Result<Hosts, ConfigError>`; `impl ExchangeAdapterBinance { pub fn resolved_network(&self, kind: MarketKind) -> ResolvedNetwork; }`. `kind.rs`'s `MarketKind` replaced by `exchange_adapter::MarketKind`.
**Unit tests (RED):** every row of spec §4.3's Binance table (spot testnet/mainnet, margin testnet → `NoTestnet`, futures testnet/mainnet); precedence: override URL > network > default mainnet; `extra["futures_rest_base_url"]` still wins for futures; `resolved_network` = `Custom(url)` when overridden.
**Notes:** remove `DEFAULT_FUTURES_*` testnet constants and update the doc comments that claim "every base URL defaults to testnet" and "futures ws not yet consumed" (spec §4.4). Update existing tests that asserted the testnet default.

### Task 2.2: Error classification

**Files:** new `src/errors.rs`; `rest.rs::classify_http_error` routes through it.
**Interface:** `pub(crate) fn classify(http_status: u16, code: Option<i64>, message: &str) -> RejectReason;`
**Unit tests (RED):** one test per row of spec §4.6 Binance table (incl. `-1013` × 4 filter names, `-1111` price vs qty by message, `-2010` insufficient vs other); unknown code → `Unknown` with code and message preserved in `Rejection`; 429/418 still `RateLimited`; 5xx still `Network`. Each row marked `// from docs` until a Layer 7 capture confirms it.

### Task 2.3: Client order id, fills, market info assets

**Files:** `market.rs`, `parsing.rs`, `kind.rs` (endpoint paths).
**Interface:** `get_order_fills` implemented: spot `GET /api/v3/myTrades`, margin `GET /sapi/v1/margin/myTrades` (`isIsolated=FALSE`), futures `GET /fapi/v1/userTrades`, all with `symbol` + `orderId`. `OrderInfo.client_order_id` parsed from `clientOrderId` (order + open-orders). `MarketInfo.base_asset/quote_asset` from `exchangeInfo` `baseAsset`/`quoteAsset`.
**Wiremock tests (RED):** each fills endpoint: request params, parse incl. `commissionAsset`, `isMaker`/`maker`, futures `realizedPnl`; multi-fill response; `clientOrderId` parsed on all three kinds; margin `place_order` never sends `reduceOnly` (spec §4.4).

### Task 2.4: `MarginOps`

**Files:** new `src/margin_ops.rs`; `adapter.rs` overrides `margin_ops()`.
**Endpoints:** spec §4.2. **Wiremock tests (RED):** `borrow`/`repay` → `POST /sapi/v1/margin/borrow-repay` with `asset`, `amount`, `type=BORROW|REPAY`, `isIsolated=FALSE`, signed; `max_borrowable` parse; `margin_balances` parses `borrowed`/`interest`/`netAsset` (existing fixture in `parsing.rs` already has them); `-3006` → `BorrowLimitExceeded`, `-3015` → `RepayExceedsDebt`.

### Task 2.5: `FuturesOps`

**Files:** new `src/futures_ops.rs`; `adapter.rs` overrides `futures_ops()`.
**Wiremock tests (RED):** `set_leverage` returns applied leverage; `-4028` → `Err` with `LeverageNotAllowed`; `set_margin_type` sends `ISOLATED|CROSSED`, `-4046` → `Ok(())`, `-4048` → `MarginModeChangeBlocked`; `leverage_brackets` parse (bracket list for one symbol); `position_risk` parse (flat → `None`, open → all fields); `futures_margin_summary` parse from `/fapi/v2/account` top-level fields; `is_hedge_mode` from `/fapi/v1/positionSide/dual`.
**Notes:** spec §4.2 leaves `positionRisk` v2 vs v3 open — pick the version whose response carries `leverage`, `marginType`, `isolatedMargin`, `liquidationPrice`; confirm by the Layer 7 capture.

**Layer 2 gate:** Layer 1's Binance integration tests GREEN; all Binance unit/wiremock tests green; workspace green. Commit (after confirmation): `feat(binance): hosts by network, error classification, fills, margin + futures ops`.

---

## Layer 3: `exchange_adapter_mexc` — plumbing only

### Task 3.1: Hosts, classification routing, client id

**Files:** MEXC config (`src/lib.rs`/config), `src/http.rs`, `src/dto_futures.rs`, `src/dto.rs`, new `src/errors.rs`.
**Interface:** `hosts(network, kind)` — `Testnet` → `ConfigError::NoTestnet` for every kind, `Mainnet` → today's hosts; `resolved_network`; `classify(http_status, code, message) -> RejectReason` with the single evidenced row ("insufficient balance" → `InsufficientBalance`) and 401/403 → `AuthFailed`.
**Tests (RED):** `EXCHANGE_NETWORK=testnet` → `NoTestnet`; unset → mainnet hosts; `map_error_status` 4xx → `Rejected` (no longer `InvalidRequest`) with `code` kept; `unwrap_envelope` `success:false` keeps `code` in `Rejection` (today dropped); existing insufficient-balance tests now assert `reason() == Some(InsufficientBalance)`; `clientOrderId` parsed where MEXC returns it (spot `clientOrderId`, futures `externalOid`), else `None`; `MarketInfo.base_asset/quote_asset` populated (spot `baseAsset`/`quoteAsset`, futures `baseCoin`/`quoteCoin`).
**Notes:** `get_order_fills`, `margin_ops`, `futures_ops` stay on their defaults (`NotSupported`/`None`) — out of scope (spec §3). `OrderId` is `u64`; do not change it here.

**Layer 3 gate:** MEXC tests green; workspace green. Commit (after confirmation): `feat(mexc): network hosts, rejection classification, client order id`.

---

## Layer 4: `live_trade_ops` crate — registry and pure functions

New crate `crates/live_trade_ops` (spec §5.0). Nothing in the workspace may depend on it.

### Task 4.1: Crate, registry, `test` service

**Files:** new `crates/live_trade_ops/{Cargo.toml,src/lib.rs,src/registry.rs}`; workspace `Cargo.toml` members; `docker-compose.yml` (`test` service only).
**Interface (`registry`):**
```rust
pub enum BuiltAdapter { Binance(Arc<ExchangeAdapterBinance>), Mexc(Arc<ExchangeAdapterMexc>) }
impl BuiltAdapter {
    pub fn adapter(&self) -> Arc<dyn ExchangeAdapter>;
    pub fn exchange(&self) -> Exchange;
    pub fn resolved_network(&self, kind: MarketKind) -> ResolvedNetwork;
}
pub fn build_adapter_from_env(kind: MarketKind, metrics: Arc<dyn Metrics>, alerts: Arc<dyn Alerts>) -> Result<BuiltAdapter, ConfigError>;
pub fn parse_market_kind(raw: &str) -> Result<MarketKind, ConfigError>;
```
Reads `EXCHANGE` (`binance` | `mexc`, else `ConfigError::Invalid`), builds via `AdapterConfig::from_env("")` (+ `"FUTURES_"` for MEXC futures). Validates `hosts(network, kind)` **at build time**. `registry` is the **only** module in the crate allowed to import `exchange_adapter_binance` / `exchange_adapter_mexc`.
**Unit tests (RED):** `EXCHANGE` unset/unknown → error; `binance` + `EXCHANGE_NETWORK=testnet` + `Margin` → `Err(NoTestnet)`; same with `Futures` → `Ok`, `resolved_network(Futures) == Testnet`; `mexc` + testnet → `NoTestnet`; `binance` defaults → mainnet hosts. Use the `from_env_with` lookup form — no process-env mutation.
**Compose:** `test` service gets the pass-through vars listed under Docker Entry Points (`${VAR:-}`); its command stays `cargo test --workspace` (the crate is a workspace member — no feature flag). The `executor` service is **not** touched.
**Checks:** `cargo tree -i live_trade_ops` lists no workspace crate; a `grep` guard test (`tests/no_adapter_imports.rs`) fails if any file under `src/` other than `registry.rs` mentions `exchange_adapter_binance` or `exchange_adapter_mexc`; `docker compose config` shows the `executor` service unchanged.

### Task 4.2: Fee settlement (`settle`)

**Files:** `crates/live_trade_ops/src/settle.rs`.
**Interface:**
```rust
pub struct PairAssets { pub base: String, pub quote: String }
pub struct Settlement { pub filled_qty: Decimal, pub gross_quote: Decimal, pub avg_price: Option<Decimal>,
                        pub fees: Vec<(String, Decimal)>, pub fee_in_quote: Option<Decimal>, pub effective_fee_rate: Option<Decimal>,
                        pub net_deltas: Vec<(String, Decimal)>, pub net_price: Option<Decimal>, pub realized_pnl: Option<Decimal> }
pub fn settle(kind: MarketKind, assets: &PairAssets, side: Side, fills: &[Fill]) -> Settlement;
```
**Unit tests (RED):** spot/margin BUY (fee in base) → spec §4.5 worked example exact (`net_deltas` LINK +0.79920, USDT −12.0000, `net_price` 15.0150…); SELL (fee in quote); futures BUY open (`net_deltas` = quote −fee only, `realized_pnl` 0); futures SELL close (quote `+realized_pnl − fee`); multi-fill avg price; mixed maker/taker; BNB fee → `fee_in_quote None`, BNB in `net_deltas`; zero fills → all zero, `avg_price None`. Decimal exactness — no float anywhere.

### Task 4.3: Liquidation calculator (`risk`)

**Files:** `crates/live_trade_ops/src/risk.rs`.
**Interface:**
```rust
pub fn initial_margin(qty: Decimal, entry: Decimal, leverage: u32) -> Decimal;
pub fn isolated_liquidation_price(side: Side, qty: Decimal, entry: Decimal, isolated_margin: Decimal, bracket: &LeverageBracket) -> Decimal;
pub fn bracket_for(brackets: &[LeverageBracket], notional: Decimal) -> Option<&LeverageBracket>;
```
Lives here, not in `exchange_adapter` (spec §6.3): test-only today.
**Unit tests (RED):** `initial_margin` exact; liquidation long/short with spec example (lev 10, mmr 1 %, cum 0 → 0.90909… × entry); `cum ≠ 0` case; `bracket_for` at floor/cap boundaries and beyond last cap → `None`. Golden-file test `risk_matches_live_golden_rows` reads `crates/live_trade_ops/tests/fixtures/futures_liq_golden.json` **if present** and asserts within 0.5 % per row (file created in Layer 7; passes vacuously with a printed "no golden rows yet" until then).

**Layer 4 gate:** `docker compose run --build --rm test` green. Commit (after confirmation): `feat(live_trade_ops): crate, registry, settle, risk`.

---

## Layer 5: Order journal (REVIEW GATE — TECH_DEBT §8)

> Do not start this layer until the user confirms the [TECH_DEBT.md §8](../TECH_DEBT.md) review is settled. Layers 6–7 depend on it only through `JournaledAccount`; if the review changes the design, update spec §4.7 and this layer first.

### Task 5.1: `OrderJournal`, `JournaledAccount`, in-memory journal

> **Review required first:** [TECH_DEBT.md §8](../TECH_DEBT.md). Before starting Layer 5, ask the user whether the §8 review is settled; implement as written only if they say so.

**Files:** `crates/live_trade_ops/src/journal/{mod.rs,memory.rs}`.

**Interface:**
```rust
pub struct OrderIntent { pub client_order_id: String, pub exchange: Exchange, pub network: ResolvedNetwork, pub kind: MarketKind,
                         pub request: OrderRequest, pub origin: String, pub run_id: Option<String>, pub created_at: Ts }
pub enum JournalStatus { Intent, SubmittedUnknown, New, PartiallyFilled, Filled, Cancelled, Rejected }
pub struct JournaledOrder { pub intent: OrderIntent, pub exchange_order_id: Option<String>, pub status: JournalStatus,
                            pub filled_qty: Decimal, pub avg_fill_price: Option<Decimal>, pub rejection: Option<Rejection> }
pub enum JournalError { Write(String), BackwardTransition { client_order_id: String, from: JournalStatus, to: JournalStatus } }
#[async_trait] pub trait OrderJournal: Send + Sync {
    async fn record_intent(&self, i: &OrderIntent) -> Result<(), JournalError>;
    async fn record_ack(&self, client_id: &str, ack: &OrderAck) -> Result<(), JournalError>;
    async fn record_submit_unknown(&self, client_id: &str) -> Result<(), JournalError>;
    async fn record_rejection(&self, client_id: &str, r: &Rejection) -> Result<(), JournalError>;
    async fn record_status(&self, client_id: &str, info: &OrderInfo) -> Result<(), JournalError>;
    async fn record_fills(&self, client_id: &str, fills: &[Fill]) -> Result<(), JournalError>;   // idempotent on (exchange, trade_id)
    async fn get(&self, client_id: &str) -> Result<Option<JournaledOrder>, JournalError>;
    async fn fills(&self, client_id: &str) -> Result<Vec<Fill>, JournalError>;
    async fn unfinished(&self, exchange: Exchange, origin: &str) -> Result<Vec<JournaledOrder>, JournalError>;
}
pub struct JournaledAccount { /* inner: Arc<dyn MarketAccount>, journal: Arc<dyn OrderJournal>, exchange, network, kind, origin, run_id, alerts */ }
impl JournaledAccount { pub fn new(inner: Arc<dyn MarketAccount>, journal: Arc<dyn OrderJournal>, ctx: JournalContext) -> Self; }
pub struct JournalContext { pub exchange: Exchange, pub network: ResolvedNetwork, pub kind: MarketKind, pub origin: String, pub run_id: Option<String> }
// impl MarketAccount for JournaledAccount
```
`record_fills` stores fills only; settlement is always recomputed with `settle` (Task 4.2, spec §4.7). `JournaledAccount` needs an `order_id → client_order_id` map for `get_order`/`cancel_order`/`get_order_fills` (their argument is the exchange id): kept in memory and backfilled from the journal on miss.

**Unit tests (RED), against `MemoryJournal` + a recording fake account:**
- `place_order` without `client_order_id` → `InvalidRequest`, inner never called.
- `record_intent` fails → inner `place_order` **never called**, error returned.
- Happy path: intent row, then ack row with exchange id; order of calls intent → send → ack.
- Inner returns `Rejected` → `record_rejection`, status `Rejected`, error passed through unchanged.
- Inner returns `Network` → status `SubmittedUnknown`, error passed through.
- `record_ack` fails after inner succeeded → alert raised (`OrderJournalWriteFailed`), error returned to caller.
- `get_order` / `cancel_order` → `record_status`; status can only move forward (`Filled` then `New` → `BackwardTransition`, alert, caller still gets the exchange's answer).
- `get_order_fills` twice → fills stored once (idempotent).
- `unfinished` returns only non-terminal rows of that exchange+origin.
- Passthrough methods (`get_market_info`, `subscribe_market_data`, …) untouched.

### Task 5.2: Migration 0008


**Files:** new `migrations/0008_order_journal.sql`; `crates/db_schema/src/lib.rs` (`SCHEMA_VERSION = 8`); `crates/db_schema/tests/migrations.rs`.
**Schema:** exactly spec §4.7 (`exchange_order`, `exchange_fill`, indexes `(origin, status)` and `(run_id)`, `UNIQUE (exchange, market_kind, exchange_order_id)`), plus a `CHECK` on `exchange_order.status` listing the 7 values.
**Tests (RED):** migrations test sees version 8; tables/columns/constraints exist; `dashboard` role can `SELECT` both, cannot `INSERT`.

### Task 5.3: `PgOrderJournal`


**Files:** `crates/live_trade_ops/src/journal/pg.rs` (`sqlx` directly — `state_store` is **not** touched). Test: `crates/live_trade_ops/tests/pg_journal.rs` (Docker Postgres via `TEST_DATABASE_URL`, same connection pattern as `state_store/tests/pg_store.rs`).
**Interface:** `pub struct PgOrderJournal; impl PgOrderJournal { pub fn new(pool: PgPool, alerts: Arc<dyn Alerts>) -> Self; } impl OrderJournal for PgOrderJournal`.
**Integration tests (RED):**
- Round trip of every `OrderJournal` method; `record_intent` committed before it returns (read from a second connection).
- Duplicate `client_order_id` intent → `JournalError::Write`.
- Forward-only status: `Filled` → `New` refused with `BackwardTransition`; `New` → `PartiallyFilled` → `Filled` accepted.
- `record_fills` twice with same trade ids → one row each.
- `unfinished(exchange, origin)` filters exchange, origin and terminal statuses.
- **Parity test:** a scripted sequence run against `MemoryJournal` and `PgOrderJournal` yields identical `get`/`fills`/`unfinished` results (keeps the self-test's in-memory journal honest).
- `JournaledAccount(fake account, PgOrderJournal)`: intent row exists when the fake's `place_order` is entered (fake checks the DB inside its call).

**Layer 5 gate:** workspace green in Docker; `docker compose run --rm executor --migrate-only` applies 0008 on a fresh volume. Commit (after confirmation): `feat(live_trade_ops): order journal + migration 0008`.

---

## Layer 6: Live harness (offline, against `ScriptedExchange`)

All code in `crates/live_trade_ops/src/{harness,scenarios,fake}/`. No exchange-specific code (Task 4.1 guard test).

### Task 6.1: Scripted fake exchange (decided 2026-09-22: scripted, not simulated)

**Files:** `crates/live_trade_ops/src/fake/{mod.rs,script.rs,builders.rs}`.
**What it is:** no order book engine, no matching, no fee model, no borrow ledger. Each test gives it a **script**: an ordered list of expected calls, each with an argument matcher and the canned response to return (value, `AdapterError`, delay, or panic). It records every call it receives. Real exchange behaviour is covered by the live runs, not by the fake.
**Interface:**
```rust
pub struct ScriptedExchange;   // implements ExchangeAdapter; margin()/futures() → ScriptedAccount; margin_ops()/futures_ops() → Some or None per script
impl ScriptedExchange {
    pub fn new(script: Script) -> Self;
    pub fn calls(&self) -> Vec<RecordedCall>;          // every call, in order, with arguments
    pub fn assert_script_consumed(&self);              // panics listing unused steps
}
pub struct Script;
impl Script {
    pub fn new() -> Self;
    pub fn expect(self, call: CallMatcher, reply: Reply) -> Self;          // strict order
    pub fn any_time(self, call: CallMatcher, reply: Reply) -> Self;        // unordered, repeatable (e.g. get_market_info, get_fees)
    pub fn without_margin_ops(self) -> Self;
    pub fn without_futures_ops(self) -> Self;
    pub fn book(self, events: Vec<(Duration, MarketDataEvent)>) -> Self;  // what subscribe_market_data streams, with delays
}
pub enum CallMatcher { PlaceOrder(OrderMatcher), CancelOrder, GetOrder, GetOrderFills, GetAccountState, GetMarketInfo, GetFees,
                       GetExtendedMarketData, Borrow { asset: String }, Repay { asset: String }, MaxBorrowable { asset: String },
                       MarginBalances, SetLeverage(u32), SetMarginType(MarginType), LeverageBrackets, PositionRisk,
                       FuturesMarginSummary, IsHedgeMode }
pub struct OrderMatcher { pub side: Option<Side>, pub reduce_only: Option<bool>, pub client_id_step: Option<String> }
pub enum Reply { Ok(ReplyValue), Err(AdapterError), Delay(Duration, Box<Reply>), Panic(String) }
// builders.rs — readable helpers composing common sequences, e.g.
pub fn resting_order_cancelled(side: Side, step: &str, order_id: u64) -> Vec<(CallMatcher, Reply)>;
pub fn marketable_order_filled(side: Side, step: &str, order_id: u64, fills: Vec<Fill>) -> Vec<(CallMatcher, Reply)>;
pub fn margin_balances(pairs: &[(&str, Decimal, Decimal, Decimal)]) -> Reply;   // (asset, free, locked, borrowed)
```
An **unexpected call** (no matching step) panics with the call and the next expected step — tests fail loudly, never silently get a default.
**Unit tests (RED):** strict order enforced; `any_time` repeatable; unexpected call panics with a readable message; `assert_script_consumed` lists leftovers; `Delay` actually delays (tokio paused time); `Panic` reply panics inside the caller; `without_margin_ops` → `margin_ops() == None`; `calls()` records arguments.

### Task 6.2: Harness components

**Files:** `crates/live_trade_ops/src/{book.rs,pricer.rs,countdown.rs,capped.rs,cleanup.rs,poller.rs,settlement_check.rs,report.rs,ids.rs,config.rs}`.
**Interface (one line each):**
```rust
pub struct LiveConfig { pub pair: Pair, pub max_notional: Decimal, pub wait: Duration, pub run_id: String, pub require_all: bool }  // from LIVE_* env
pub struct BookWatcher;   pub async fn start(account: &dyn MarketAccount, pair: &Pair) -> Result<BookWatcher, HarnessError>; fn best_bid/best_ask(&self) -> Result<Decimal, HarnessError> /* fresh ≤ 2 s */;
pub struct Pricer;        pub fn resting_buy/resting_sell/marketable_buy/marketable_sell(&self, book: &BookWatcher, offset: Decimal) -> Decimal; fn qty_for_notional(&self, notional: Decimal, price: Decimal) -> Decimal; fn min_order_qty(&self, ask: Decimal) -> Decimal; fn check(&self, qty: Decimal, price: Decimal) -> Result<(), HarnessError>;
pub async fn countdown(secs: u64, book: &BookWatcher, resting: Option<RestingOrder>) -> Touched;
pub struct CappedAccount; // MarketAccount decorator; place_order over cap → InvalidRequest("notional cap …"), nothing sent
pub fn client_id(run_id: &str, step: &str) -> String;   // livetest-{run8}-{step}, validated [a-z0-9-] ≤ 32
pub async fn await_filled(acct: &dyn MarketAccount, id: OrderId, timeout: Duration) -> Result<(OrderInfo, Vec<Fill>), HarnessError>;
pub async fn check_settlement(before: &Balances, after: &Balances, s: &Settlement, fees: &FeeSchedule, fills: &[Fill]) -> Result<(), HarnessError>;
pub async fn check_journal(journal: &dyn OrderJournal, client_id: &str, info: &OrderInfo, s: &Settlement) -> Result<(), HarnessError>;
pub async fn with_cleanup<F: Future<Output = Result<(), HarnessError>>>(ctx: &RunCtx, body: F) -> RunOutcome;   // catch_unwind + always-cleanup
pub struct RunReport; // steps: Passed | Inconclusive | Skipped(reason) | Failed; fills; UNMAPPED rejections; writes target/live-trade-ops/{run}.jsonl
```
**Unit tests (RED), all against `ScriptedExchange` + `MemoryJournal`:** pricer rounding (bid down / ask up / qty down) and min-notional/cap refusal; countdown duration ≥ secs and `touched` when the fake moves the book onto the resting price; cap blocks before the inner account is called; client id format/length; poller waits for fill lag (fake delays fills); settlement check passes on correct balances and fails naming the asset on a 1-unit discrepancy; journal check fails on mismatched exchange id; report JSONL line shape.

### Task 6.3: Scenarios and self-tests

**Files:** `crates/live_trade_ops/src/margin_scenario.rs`, `crates/live_trade_ops/src/futures_scenario.rs`, `crates/live_trade_ops/src/sell_funding.rs`; self-tests in `crates/live_trade_ops/src/tests.rs` (normal `#[tokio::test]`, not ignored).
**Interface:**
```rust
pub async fn run_margin_scenario(adapter: Arc<dyn ExchangeAdapter>, journal: Arc<dyn OrderJournal>, ctx: RunCtx) -> RunReport;   // Arc, not &dyn: CappedAccount/JournaledAccount need Arc<dyn MarketAccount>, which is +'static
pub async fn run_futures_scenario(adapter: Arc<dyn ExchangeAdapter>, journal: Arc<dyn OrderJournal>, ctx: RunCtx) -> RunReport;
pub async fn ensure_sell_funds(ops: Option<&dyn MarginOps>, pricer: &Pricer, book: &BookWatcher, base: &str, qty: Decimal, cap: Decimal) -> Result<Decimal /* borrowed */, HarnessError>;
pub struct RunCtx { pub cfg: LiveConfig, pub exchange: Exchange, pub network: ResolvedNetwork, pub kind: MarketKind }
```
Steps exactly as spec §6.1 (0, 1–3, 4a, 4–6, 6b, 7, 8, cleanup) and §6.2 (0–6 with futures differences, F1–F7, observation-only F4, funding-time guard via `next_funding_time`, restore leverage/margin type). Journal reconciliation at step 0 (spec §6.1 step 0). Touched rule (§5.3). Capability skips + `LIVE_REQUIRE_ALL` (D8).

**Self-tests (RED), each a full scenario on `ScriptedExchange` + `MemoryJournal`.** Assertions are on the **recorded call sequence** and the report, not on simulated end state:
1. Margin happy path → all steps `Passed`; script fully consumed; recorded calls show 4a `borrow` of `min_order_qty`, 6b buy-back + `repay`; every order has a journal row with terminal status.
2. Futures happy path → recorded calls end with `set_leverage(<step-0 value>)` and `set_margin_type(<step-0 value>)`; golden-row writer produces rows (temp path).
3. `Panic` reply between 4a and 6b → recorded calls after the panic: cancel of open `livetest-` orders, marketable buy tagged `cl-buyback`, `repay`; outcome `Failed` with the original panic message.
4. Book script moves the touch onto the resting buy during the countdown, `get_order` then returns filled → step `Inconclusive`, next `place_order` priced at 4 %, run continues.
5. `get_order` returns filled on a resting order with no touch in the book script → `Failed`.
6. `without_margin_ops` + base balance ≥ qty → sell steps run; + base short → `Skipped(cannot fund sell)`, no `place_order` for sells recorded; + `require_all` → `Failed`.
7. `max_borrowable` below need → `precondition not met`, no `borrow` and no `place_order` recorded.
8. Journal `record_intent` failing → no `place_order` recorded; run `Failed`.
9. Journal holds an unfinished `livetest` row + script's open orders include it → step 0 records `get_order` + `cancel_order` for it; open tagged order with no row → `Failed (order sent without a journal row)`.
10. `get_extended_market_data` returns `next_funding_time` 2 min ahead → `precondition not met`, no orders recorded.
11. `place_order` replies `Rejected { reason: Unknown, code: "-9999" }` → report contains `UNMAPPED`.
12. Unexpected call (harness calls something the script does not expect) → test harness itself fails with the call named (guards against silent harness drift).

**Layer 6 gate:** `docker compose run --build --rm test cargo test -p live_trade_ops` green; workspace green; `cargo tree -i live_trade_ops` still lists no dependents. Commit (after confirmation): `feat(live_trade_ops): exchange-agnostic harness, scenarios, offline self-tests`.

---

## Layer 7: Live runner and human-gated runs

### Task 7.1: Runner, env templates

**Files:** `crates/live_trade_ops/tests/live_trade_ops.rs`; `configs/live-trade-ops/{binance.margin.mainnet,binance.futures.testnet,binance.futures.mainnet,mexc.futures.mainnet}.env.example`; `.gitignore` adds `configs/live-trade-ops/*.env`.
**Interface:** `#[tokio::test] #[ignore] async fn live_margin_trade_ops()`, `async fn live_futures_trade_ops()` — return early with a printed reason unless `LIVE_TRADE_OPS=1`; build via `build_adapter_from_env`; `PgOrderJournal` on `DATABASE_URL`; print banner; run scenario; print report; `assert!(report.passed())`.
**Tests:** `cargo test -p live_trade_ops` (no flags) → both tests reported ignored, zero network (verify with the container's network disabled: `docker compose run --rm --network none …` must still pass).
**Remove:** `exchange_adapter_binance/tests/testnet_integration.rs` and `exchange_adapter_mexc/tests/live_credentials.rs` (superseded, spec header) — only after 7.1 compiles.

### Task 7.2: Binance futures — testnet (HUMAN GATE)

Preconditions the user provides: futures-testnet key, funded testnet wallet. Run the futures command from Docker Entry Points with `binance.futures.testnet.env`.
Record: report JSONL; captured raw responses for every new endpoint (enable request/response capture via an env flag added in 7.1, `LIVE_CAPTURE_DIR`); F4 observations.
Then: replace `// from docs` wiremock fixtures with captures; mark confirmed `classify` rows; turn F4 observations into assertions (spec §6.2 note) — **stop and show the user the observed F4 behaviour before encoding it**; append golden rows; Layer 1's golden test now non-vacuous and green.

### Task 7.3: Binance futures — mainnet (HUMAN GATE)

Same, with `binance.futures.mainnet.env` (sub-account, futures enabled, withdrawals disabled, ≥ 30 USDT). Verify afterwards, independently of the test: position flat, no open orders, leverage/margin type equal pre-run values, journal rows terminal. Append mainnet golden rows (accepts `LiqCalc` for Binance).

### Task 7.4: Binance margin — mainnet (HUMAN GATE)

`binance.margin.mainnet.env`. Verify afterwards: `borrowed == 0`, `interest == 0` on base and quote, no open orders, journal rows terminal, report shows 4a borrow and 6b repay. Record spec §7.1 outcome (borrow-repay endpoint confirmed; captured response becomes the wiremock fixture).

### Task 7.5: MEXC smoke (HUMAN GATE)

`mexc.futures.mainnet.env`, `LIVE_REQUIRE_ALL` unset. Expected: book/pricer/order place/rest/cancel/fill steps run; fills, ops steps `SKIPPED (not supported)`; cleanup clean; every `UNMAPPED` line recorded for the MEXC spec.

### Task 7.6: Docs

- [ ] Tick L0 Stage 1 checkboxes named in the spec header in `external/executor/specs/layers/L0-exchange-adapter.md`, with run dates.
- [ ] Spec status → `implemented 2026-…`; this plan's status line.
- [ ] `TECH_DEBT.md` §7 (`order_event.order_id` bigint) stays open — not fixed here.

**Layer 7 gate:** all spec §9 acceptance boxes checked. Commit (after confirmation) per task; merge `live-trade-ops` → `layer-implementation` only after 7.4, with user confirmation.

---

## Spec coverage check

| Spec | Plan |
|---|---|
| D1 separate crate, no dependents | 4.1 (guard test, `cargo tree -i`), 6 gate |
| §4.1 ops traits | 1.4, 2.4, 2.5 |
| §4.2 Binance endpoints | 2.3–2.5 |
| §4.3 env loader, `EXCHANGE_NETWORK`, mainnet default, `test` service | 1.1, 2.1, 3.1, 4.1 |
| §4.4 small fixes | 2.1, 2.3 |
| §4.5 fills (L0) / `settle` (test crate) | 1.3, 2.3 / 4.2 |
| §4.6 rejections (no test-only variants) | 1.2, 2.2, 3.1 |
| §4.7 order journal (review gate) | 5.1–5.3 |
| §5.0 code locations | 4.1, 6.x, 7.1 |
| §5.1 gating, env files, banner, key/net mismatch | 7.1, 6.3 |
| §5.2 components | 6.2 |
| §5.3 touched rule | 6.3 self-tests 4–5 |
| §5.4 client ids | 1.3, 2.3, 3.1, 6.2 |
| §5.5 fill report | 6.2 |
| §6.1 margin + §6.1.1 sell funding | 6.3, 7.4 |
| §6.2 futures | 6.3, 7.2, 7.3 |
| §6.3 LiqCalc + golden | 4.3, 7.2, 7.3 |
| §7 risks | 7.2–7.4 |
| §9 acceptance | layer gates + 7.6 |
