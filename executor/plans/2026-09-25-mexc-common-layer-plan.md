# MEXC trading connector 2/5 — Common layer (L0-a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Index: [2026-09-25-mexc-connector-index-plan.md](2026-09-25-mexc-connector-index-plan.md).

**Goal:** Change the shared adapter layer so that both exchanges fit behind it: string order ids, a truthful capability set, lookup by client id, a permission reject reason, and a server-offset clock. Binance keeps working, and loses its `-1021` failure mode along the way.

**Spec:** D3, §5.1, §5.3, §5.4, §6.5, §8 (new variant), §11 L0-a; review items R7, R8, R10, R16, and the §15 "smaller corrections" row (`OrderId` blast radius, journal parse).

**Scope:** `exchange_adapter`, `exchange_adapter_binance`, `exchange_adapter_mexc` (compile-through plus the shared plumbing in Task 1.7: codec, rate bucket, `classify` skeleton; endpoint mapping is 3/5 and 5/5), `order_journal`, `market_data`, `observability`, `execution`, `orchestrator`, `state_store`, `mq_gateway`, `live_trade_ops`, `migrations/`. **No** MEXC endpoint work, **no** execution behaviour change.

**Depends on:** index precondition (position-management merged). Plan 1/5's **F4 verdict**: if F4 is refuted (MEXC ids numeric), stop and re-open D3 with the user.

**Branch:** `mexc-common`, cut from `mexc-trading-connector`.

---

## Readiness review

Verified against `layer-implementation` @ 165afdb plus the uncommitted position-management work.

| Item | Today | Change | Size |
|---|---|---|---|
| `OrderId(u64)`, `Copy` | `exchange_adapter/src/lib.rs:152-153` | `OrderId(String)`, not `Copy` | 🟠 ~300 lines / 10 crates: live_trade_ops 89, order_journal 79, mexc 28, binance 27, orchestrator 21, exchange_adapter 17, execution 17, state_store 14, market_data 7, mq_gateway 2 |
| `order_event.order_id bigint` | `migrations/0001_init.sql:93`; writer `market_data/src/pg/rows.rs:336` (`o.id.0 as i64`) | migration `0010`: → `text` | 🟡 |
| Journal id parse | `order_journal/src/pg.rs:669` parses `u64`, falls back to `OrderId(0)` | take the text as is | 🟡 |
| `capabilities()` | absent | required trait method, 17 implementors | 🟡 |
| `get_order_by_client_id` | absent everywhere | default `NotSupported`; Binance real | 🟡 |
| `RejectReason` | 21 variants (`exchange_adapter/src/error.rs:31-58`); journal string maps both ways (`order_journal/src/pg.rs:~265-305`) | + `PermissionDenied` | 🟢 |
| Binance clock | local `now_ms()` (`exchange_adapter_binance/src/rest.rs:97`) | `ServerClock` | 🟡 |
| `AlertKind` | 8 variants, no `ClockSkew` (`observability/src/lib.rs:48-92`) | + `ClockSkew` | 🟢 |
| MEXC in-memory `OrderId`→symbol cache | `exchange_adapter_mexc/src/order_cache.rs` | kept in this plan; deleted by 3/5 and 5/5 once ids carry the symbol | — |

---

## Global constraints

- **Mechanical first, behaviour second.** Task 1.1 changes the type and nothing else; every test that was green stays green with the same meaning.
- **Do not add `Copy`-shaped workarounds** (`Arc<str>`, interning) unless a benchmark shows a need. `.clone()` at call sites is fine.
- **Trait methods keep their by-value `OrderId` / `Pair` parameters.** Callers clone. No signature churn beyond the type.
- **Binance encodes its id as the decimal string of its `u64`.** Existing journal rows then read back unchanged.
- One commit per layer, after green in Docker, after user confirmation.

---

## Docker Entry Points

```bash
docker compose run --build --rm test                                  # layer gate
docker compose run --build --rm test cargo test -p exchange_adapter
docker compose run --build --rm test cargo test -p order_journal       # needs postgres (compose starts it)
docker compose run --build --rm test cargo test -p db_schema           # migration tests
docker compose run --rm executor --migrate-only                        # 0010 applies on a real DB
```

Verified: [ ] baseline green on `mexc-common` at its cut point.

---

## Layer 1: `exchange_adapter` types

### Task 1.1: `OrderId(String)`

**Interface:**
```rust
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct OrderId(pub String);
impl OrderId { pub fn as_str(&self) -> &str; }
impl fmt::Display for OrderId { … }
impl From<u64> for OrderId { … }   // Binance only: decimal rendering
```

**Integration test → journal + market_data (RED in Docker):** `string_order_id_round_trips_through_journal_and_order_event` (in `order_journal/tests/`): a fake adapter returns `OrderId("s:LINKUSDT:06a480e69e604477bfb48dddd5f0b750")`. `JournaledAccount::place_order` records it. A **new** `PgOrderJournal` instance (simulating a restart) reads the row back, and `cancel_order` on the fake receives the identical id. `market_data`'s `order_event` writer stores the same string. This is acceptance 3's offline half.

**Unit tests (RED first):**
- `From<u64>` renders decimal with no padding; `OrderId::from(0)` is `"0"`.
- Serde: JSON string round trip; an old JSON number no longer deserialises (fail loud, not silently).
- Binance: every existing place/get/cancel wiremock test passes with the decimal string, and the adapter parses its own id back to `u64` for its REST calls; a non-numeric id → `InvalidRequest` before any request.

**Constraints:** the MEXC adapter keeps its current behaviour (its dto still reads a number) until 3/5 and 5/5; here it only compiles through `From<u64>`.

### Task 1.2: Migration `0010` and the two writers

**Files:** `migrations/0010_order_event_order_id_text.sql`; `market_data/src/pg/rows.rs:336`; `order_journal/src/pg.rs:669`; `db_schema/tests/migrations.rs`.

**Interface (DDL):** `ALTER TABLE order_event ALTER COLUMN order_id TYPE text USING order_id::text;`. Additive for readers: existing numeric rows become their decimal text.

**Unit tests (RED first):**
- Migration test: a row inserted as `bigint` before `0010` reads back as the same digits after.
- `rows.rs` binds `o.id.as_str()`; a MEXC-style id with `:` and `_` inserts and reads back.
- `pg.rs` returns the stored text verbatim; the `OrderId(0)` fallback is gone. A NULL `exchange_order_id` stays `None`.

**Constraints:** check every other `order_id` column reachable from `state_store` / `visualizer_server` queries (`grep -rn "order_id" crates/*/src/**/*.sql crates/*/src/pg*`). Anything `bigint` that stores an exchange id changes in the same migration.

### Task 1.3: `Capabilities`

**Interface:**
```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Capabilities {
    pub can_place_orders: bool, pub native_stop: bool, pub reduce_only_enforced: bool,
    pub can_short: bool, pub order_fills: bool, pub client_id_lookup: bool, pub account_push: bool,
}
// on MarketAccount — required, no default
fn capabilities(&self) -> Capabilities;
```

**Integration test → execution (RED):** `execution` compiles and its test fake answers `capabilities()`; `PaperMarketAccount`, `NoTradeAccount`, `JournaledAccount`, `KindAccount`, `CappedAccount`, `AdapterAccountView`, `ScriptedAccount` pass their inner account's value through. Assert the pass-through for each wrapper.

**Unit tests (RED first):** one test per adapter kind asserting spec §5.1's column: Binance spot, margin, futures. MEXC spot, futures for now return today's truth (`native_stop=false` on both, `order_fills=false`, `client_id_lookup=false`); 3/5 and 5/5 flip them as the features land, and their tests change with them.

Also, for the boot gate (spec §5.2 step 3):
```rust
// exchange_adapter::ops
#[async_trait]
pub trait PermissionProbe: Send + Sync {
    /// Ok(true): the key may place orders. Ok(false): permission / KYC refusal.
    /// Sets the account's can_place_orders flag as a side effect.
    async fn probe_order_permission(&self, pair: &Pair) -> Result<bool, AdapterError>;
}
// on ExchangeAdapter
fn permission_probe(&self) -> Option<&dyn PermissionProbe> { None }
```

**Constraints:** `can_place_orders` must be readable at runtime from an adapter-owned flag. The MEXC futures account holds an `AtomicBool` (initially `true`) and builds `Capabilities` on each call. Only the adapter writes it: from `probe_order_permission` (3/5 Task 2.3) and on a runtime `PermissionDenied`.

### Task 1.4: `get_order_by_client_id`

**Interface:**
```rust
// on MarketAccount
async fn get_order_by_client_id(&self, pair: Pair, client_order_id: &str)
    -> Result<Option<OrderInfo>, AdapterError> { Err(AdapterError::NotSupported) }
```
`Ok(None)` = the exchange confirms no such order.

**Integration test → order_journal (RED):** `JournaledAccount` passes the call through unchanged, and its recovery helper (the one live-trade-ops §4.7 names) calls it for a `submitted_unknown` row.

**Unit tests (RED first), Binance wiremock:** spot/margin/futures `GET …/order?origClientOrderId=` → `Some(info)`; Binance code `-2013` "Order does not exist" → `Ok(None)`; other errors pass through `classify`; `capabilities().client_id_lookup == true` on all three.

### Task 1.5: `RejectReason::PermissionDenied`

**Interface:** add `PermissionDenied` to `RejectReason`; add both directions to `order_journal/src/pg.rs`'s string maps (`"permission_denied"`).

**Unit tests (RED first):** journal map round trip for every variant (exhaustive test over all variants, so the next addition cannot forget a direction); Binance `-2015` (invalid key / IP / permissions) stays `AuthFailed` (unchanged).

### Task 1.6: `ServerClock` and `AlertKind::ClockSkew`

**Interface:**
```rust
// exchange_adapter::clock
pub struct ServerClock { /* AtomicI64 offset */ }
impl ServerClock {
    pub fn new() -> Self;
    pub fn now_ms(&self) -> i64;                        // local + offset
    pub fn offset_ms(&self) -> i64;
    /// Midpoint rule: offset = server − (sent + recv) / 2. Returns the new offset.
    pub fn record(&self, server_ms: i64, sent_local_ms: i64, recv_local_ms: i64) -> i64;
}
// observability
AlertKind::ClockSkew   // raised by each adapter when |offset| > recv_window / 2, Severity::Warn
```

**Integration test → Binance signing (RED):** a wiremock Binance server whose `/api/v3/time` is 3 s ahead: after one refresh, signed requests carry `timestamp` within ±50 ms of server time, and a `ClockSkew` alert fired once (recv window 5 s).

**Unit tests (RED first):** midpoint maths; negative offsets; concurrent `now_ms` during `record`; refresh every 10 min and immediately after a `ClockSkew` reject (`-1021` on Binance); the alert is not repeated while the skew persists, and fires again after it clears and returns.

**Constraints:** Binance spot/margin use `/api/v3/time`, futures `/fapi/v1/time`. MEXC wiring is 3/5 and 5/5. Record the Binance `-1021` fix in the TECH_DEBT / UNFINISHED entry that tracks the 2026-09-24 failure.

### Task 1.7: MEXC shared plumbing (so 3/5 and 5/5 can run in parallel)

Pure, network-free pieces both MEXC plans need. Putting them here avoids two plans creating the same file.

**Files:** `exchange_adapter_mexc/src/order_id.rs` (new), `exchange_adapter_mexc/src/rate.rs` (new), `exchange_adapter_mexc/src/errors.rs`, `exchange_adapter_mexc/src/http.rs`.

**Interface:**
```rust
// order_id.rs — spec D3
pub(crate) enum Surface { Spot, Futures, Plan }                 // "s" | "f" | "p"
pub(crate) fn encode(surface: Surface, symbol: &str, raw_id: &str) -> OrderId;
pub(crate) fn decode(id: &OrderId) -> Result<(Surface, String, String), AdapterError>; // splitn(3, ':')

// rate.rs — spec §9
pub(crate) struct TokenBucket { /* capacity, refill per window */ }
impl TokenBucket {
    pub(crate) fn new(limit: u32, window: Duration, fraction: f64) -> Self; // fraction = 0.7
    pub(crate) fn try_take(&self, weight: u32) -> Result<(), AdapterError>;  // Err(RateLimited)
}

// errors.rs — classify keyed on code (today the code argument is unused)
pub(crate) enum Venue { Spot, Futures }
pub(crate) fn classify(venue: Venue, http_status: u16, code: Option<i64>, msg: &str) -> AdapterError;
```

**Unit tests (RED first):**
- Codec: round trip for all three surfaces; raw ids containing `_` and `:` (`C02__…`, a hypothetical `a:b`) survive; symbols `LINKUSDT` and `LINK_USDT`; empty / unknown surface / missing parts → `InvalidRequest`.
- Bucket: 70 % of limit, refill after window, weight > 1, concurrent takers never exceed capacity.
- `classify`: the skeleton maps HTTP 401/403 → `AuthFailed`, 429 → `RateLimited`, anything else → `Unknown` carrying code and message verbatim. The per-code rows are added by 3/5 (futures) and 5/5 (spot), each with one test per row.
- `http.rs`: a futures `success:false` body on HTTP 200 reaches `classify` **with its `code`** (today it reaches it with 0).

**Constraints:** the in-memory `order_cache.rs` stays until both 3/5 and 5/5 stop using it; the second of them to merge deletes it.

### Task 1.8: Docs

- [ ] `external/executor/TECH_DEBT.md` §7 (`order_event.order_id` bigint) closed, with the migration named.
- [ ] Spec §11 L0-a row ticked; any drift found here amended in the spec and noted in §15.
- [ ] Layer gate: `docker compose run --build --rm test` green. Commit after confirmation.
