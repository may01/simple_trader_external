# Postgres market-data store + passive dashboard — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move L1 `market_data` and L5 `state_store` from embedded sled to PostgreSQL with one table per stream kind, and split the visualiser out of the executor process into a passive dashboard that reads only committed database rows.

**Architecture:** The executor is the single writer: one batching writer task for high-volume market data, synchronous durable writes for low-volume state. The dashboard is a separate container running a read-only Postgres role, linking `market_data`/`state_store` as read-only reader types, polling an `ins_seq` tail cursor and fanning results to browsers over WebSocket. No exchange dependency exists in the dashboard's dependency graph.

**Tech Stack:** Rust (workspace `trade_executor`), `sqlx` 0.8 with `postgres`/`rust_decimal`/`macros` features, `async-trait`, `axum` (visualiser server), PostgreSQL 17, Docker Compose.

**Spec:** [2026-09-09-postgres-market-data-store-design.md](../specs/2026-09-09-postgres-market-data-store-design.md)

**Branch:** create `postgres-market-data-store` off `layer-implementation` in `trade_executor`.

## Global Constraints

- One table per stream kind. Tables: `book_snapshot`, `book_update`, `book_gap`, `trade`, `candle`, `order_event`, `balance_event`, `position_event`, plus L5's `position_state`, `decision_log`, `event_log`.
- Every table carries `exchange_ts bigint NULL`, `recv_ts bigint NOT NULL`, `ord_ts bigint GENERATED ALWAYS AS (COALESCE(exchange_ts, recv_ts)) STORED`.
- One global sequence `global_ins_seq` supplies `ins_seq` on market-data tables and `seq` on the three account tables. `ord_ts` orders display/replay; `ins_seq` is the only legal tail cursor.
- **Exactly one writer task commits at a time.** The tail cursor's correctness depends on it. Never add a second concurrent writer without revisiting the cursor design.
- Decimals are Postgres `numeric`, never JSON, never text.
- The executor owns migrations. The visualiser never runs DDL.
- The `dashboard` role has `CONNECT` + `SELECT` only.
- The visualiser must never depend on `exchange_adapter_binance` or `exchange_adapter_mexc`.
- Every task's tests run inside Docker (`docker compose run --rm test`) before the task is considered done. Host-only `cargo test` is not sufficient — the suite needs Postgres.
- No sled data migration. Cutover is clean; `sled` and `tempfile` dependencies are deleted when their last user goes.

**Dependency note:** L5's `event_log` / `last_reconciliation` additions live on the `state-store-expansion` branch and may not be merged into `layer-implementation` when this starts. Task 6 handles both cases explicitly — do not assume `append_event`/`read_event_log` exist.

---

## Docker Entry Points

These commands are ground truth. Implementation must make them work.

```bash
# Full test suite (Postgres comes up as a dependency)
docker compose run --rm test

# Apply migrations only, then exit
docker compose run --rm executor --migrate-only

# Run the executor (migrations then orchestrator)
docker compose up executor

# Run the passive dashboard alone, executor stopped — must work
docker compose up postgres visualizer
# then: http://127.0.0.1:8090/  -> renders, shows "executor offline"
```

Verified: [ ] `docker compose run --rm test` green · [ ] `docker compose up executor` boots · [ ] `docker compose up postgres visualizer` serves with the executor down

---

## File Structure

**Created:**
- `trade_executor/migrations/0001_init.sql` — full schema, one file (this is a greenfield schema, not an evolution)
- `trade_executor/docker/initdb.d/00-roles.sql` — `executor` / `dashboard` roles and default privileges
- `trade_executor/crates/test_support/` — `test_db()` schema-per-test harness (dev-dependency only)
- `trade_executor/crates/market_data/src/pg/mod.rs` — Postgres backend module root
- `trade_executor/crates/market_data/src/pg/writer.rs` — batching writer task
- `trade_executor/crates/market_data/src/pg/rows.rs` — row ⇄ wire-type mapping
- `trade_executor/crates/market_data/src/pg/reader.rs` — `PgMarketDataReader`, queries, tail cursor
- `trade_executor/crates/state_store/src/pg.rs` — Postgres `StateStoreImpl` + `PgStateReader`
- `trade_executor/crates/visualizer_server/` — new binary crate (axum, poll tasks, WS fan-out)

**Modified:**
- `crates/market_data/src/store.rs` — sled internals replaced; live caches and gap detection kept
- `crates/market_data/src/lib.rs` — traits become async; `InsSeq`, `Freshness` added
- `crates/state_store/src/store.rs` — sled internals replaced
- `crates/orchestrator/src/config.rs:100` — `MARKET_DATA_PATH`/`STATE_STORE_PATH` → `DATABASE_URL`
- `crates/orchestrator/src/system.rs:151,190` — connect instead of open; migrations at boot
- `crates/visualizer_backend/src/lib.rs` — reader-only, `LiveModeFlag` deleted, `catch_unwind` deleted
- `docker-compose.yml`, `Dockerfile` — three services, new `visualizer` stage

**Deleted:** `crates/market_data/src/keys.rs`, `crates/state_store/src/keys.rs` (sled byte-key encoding has no Postgres equivalent).

---

## Task 1: Docker + Postgres + test harness

Nothing else can be written test-first until a test can reach a database.

**Files:**
- Create: `trade_executor/docker/initdb.d/00-roles.sql`
- Create: `trade_executor/crates/test_support/Cargo.toml`, `trade_executor/crates/test_support/src/lib.rs`
- Modify: `trade_executor/docker-compose.yml`, `trade_executor/Cargo.toml` (workspace members)

**Interfaces:**
- Consumes: nothing.
- Produces: `test_support::test_db() -> TestDb`, `TestDb { pub url: String, pub schema: String }`, `TestDb::pool(&self) -> sqlx::PgPool`. `TestDb`'s `Drop` drops the schema.

- [ ] **Step 1: Add the postgres service and point the test service at it**

`trade_executor/docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:17-alpine
    environment:
      - POSTGRES_USER=executor
      - POSTGRES_PASSWORD=executor
      - POSTGRES_DB=trader
    volumes:
      - trader_pgdata:/var/lib/postgresql/data
      - ./docker/initdb.d:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U executor -d trader"]
      interval: 2s
      timeout: 3s
      retries: 30

  test:
    build:
      context: .
      target: test
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      - TEST_DATABASE_URL=postgres://executor:executor@postgres:5432/trader
    command: ["cargo", "test", "--workspace"]

volumes:
  trader_pgdata:
```

- [ ] **Step 2: Create the roles init script**

`trade_executor/docker/initdb.d/00-roles.sql`:

```sql
-- `executor` is the POSTGRES_USER (owner) created by the image itself.
-- `dashboard` is read-only: CONNECT + SELECT, nothing else, ever.
CREATE ROLE dashboard LOGIN PASSWORD 'dashboard';
GRANT CONNECT ON DATABASE trader TO dashboard;
GRANT USAGE ON SCHEMA public TO dashboard;
ALTER DEFAULT PRIVILEGES FOR ROLE executor IN SCHEMA public
    GRANT SELECT ON TABLES TO dashboard;
ALTER DEFAULT PRIVILEGES FOR ROLE executor IN SCHEMA public
    GRANT SELECT ON SEQUENCES TO dashboard;
```

- [ ] **Step 3: Write the failing test for the harness**

`trade_executor/crates/test_support/src/lib.rs` (test at the bottom of the file):

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn each_test_db_gets_its_own_isolated_schema() {
        let a = test_db().await;
        let b = test_db().await;
        assert_ne!(a.schema, b.schema);

        sqlx::query("CREATE TABLE t (x int)").execute(&a.pool()).await.unwrap();
        // b's search_path points at b's schema, so a's table is invisible there.
        let visible: Option<String> = sqlx::query_scalar("SELECT to_regclass('t')::text")
            .fetch_one(&b.pool())
            .await
            .unwrap();
        assert_eq!(visible, None);
    }
}
```

- [ ] **Step 4: Run it and watch it fail**

Run: `docker compose run --rm test cargo test -p test_support -- --nocapture`
Expected: FAIL — `test_db` not found (crate has no implementation yet).

- [ ] **Step 5: Implement the harness**

`trade_executor/crates/test_support/src/lib.rs`:

```rust
//! Schema-per-test Postgres harness. Replaces the sled tempdir pattern:
//! every test gets an isolated schema on one shared database, so tests
//! stay parallel without a container each.

use sqlx::postgres::PgPoolOptions;
use sqlx::{Executor, PgPool};

pub struct TestDb {
    pub url: String,
    pub schema: String,
    pool: PgPool,
}

impl TestDb {
    pub fn pool(&self) -> PgPool {
        self.pool.clone()
    }
}

impl Drop for TestDb {
    fn drop(&mut self) {
        let url = self.url.clone();
        let schema = self.schema.clone();
        // Drop on a fresh connection: the pool may already be closing.
        std::thread::spawn(move || {
            let rt = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
            rt.block_on(async move {
                if let Ok(pool) = PgPool::connect(&url).await {
                    let _ = pool.execute(&*format!("DROP SCHEMA IF EXISTS {schema} CASCADE")).await;
                }
            });
        })
        .join()
        .ok();
    }
}

pub async fn test_db() -> TestDb {
    let url = std::env::var("TEST_DATABASE_URL")
        .expect("TEST_DATABASE_URL must be set -- run tests via `docker compose run --rm test`");
    let schema = format!("t_{}", uuid::Uuid::new_v4().simple());

    let admin = PgPool::connect(&url).await.expect("connect to test database");
    admin
        .execute(&*format!("CREATE SCHEMA {schema}"))
        .await
        .expect("create test schema");
    admin.close().await;

    let schema_for_hook = schema.clone();
    let pool = PgPoolOptions::new()
        .max_connections(5)
        .after_connect(move |conn, _| {
            let schema = schema_for_hook.clone();
            Box::pin(async move {
                conn.execute(&*format!("SET search_path = {schema}")).await?;
                Ok(())
            })
        })
        .connect(&url)
        .await
        .expect("connect test pool");

    TestDb { url, schema, pool }
}
```

`trade_executor/crates/test_support/Cargo.toml`:

```toml
[package]
name = "test_support"
version = "0.1.0"
edition.workspace = true

[dependencies]
sqlx = { version = "0.8", default-features = false, features = ["runtime-tokio", "postgres", "macros", "rust_decimal"] }
tokio = { version = "1.53.1", features = ["rt", "macros"] }
uuid = { version = "1", features = ["v4"] }
```

Add `"crates/test_support"` to the workspace `members` list in `trade_executor/Cargo.toml`.

- [ ] **Step 6: Run it and watch it pass**

Run: `docker compose run --rm test cargo test -p test_support`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml docker/initdb.d/00-roles.sql crates/test_support Cargo.toml Cargo.lock
git commit -m "test: schema-per-test Postgres harness and compose service"
```

---

## Task 2: Schema migration

**Files:**
- Create: `trade_executor/migrations/0001_init.sql`
- Create: `trade_executor/crates/market_data/tests/migrations.rs`
- Modify: `trade_executor/crates/market_data/Cargo.toml`

**Interfaces:**
- Consumes: `test_support::test_db()`.
- Produces: the tables named in Global Constraints; `market_data::pg::MIGRATOR: sqlx::migrate::Migrator`; `market_data::SCHEMA_VERSION: i64` (value `1`).

- [ ] **Step 1: Write the failing test**

`trade_executor/crates/market_data/tests/migrations.rs`:

```rust
use test_support::test_db;

#[tokio::test]
async fn migrations_create_every_stream_table_with_ord_ts_and_ins_seq() {
    let db = test_db().await;
    market_data::pg::MIGRATOR.run(&db.pool()).await.unwrap();

    for table in [
        "book_snapshot", "book_update", "book_gap", "trade", "candle",
        "order_event", "balance_event", "position_event",
    ] {
        let cols: Vec<String> = sqlx::query_scalar(
            "SELECT column_name FROM information_schema.columns
             WHERE table_schema = current_schema() AND table_name = $1",
        )
        .bind(table)
        .fetch_all(&db.pool())
        .await
        .unwrap();

        assert!(cols.iter().any(|c| c == "recv_ts"), "{table} missing recv_ts");
        assert!(cols.iter().any(|c| c == "ord_ts"), "{table} missing ord_ts");
        let cursor = if table.ends_with("_event") { "seq" } else { "ins_seq" };
        assert!(cols.iter().any(|c| c == cursor), "{table} missing {cursor}");
    }
}

#[tokio::test]
async fn ord_ts_falls_back_to_recv_ts_when_the_exchange_gave_no_timestamp() {
    let db = test_db().await;
    market_data::pg::MIGRATOR.run(&db.pool()).await.unwrap();

    sqlx::query(
        "INSERT INTO book_gap (pair, expected_seq, observed_seq, exchange_ts, recv_ts, ins_seq)
         VALUES ('BTCUSDT', 7, NULL, NULL, 1234, nextval('global_ins_seq'))",
    )
    .execute(&db.pool())
    .await
    .unwrap();

    let ord_ts: i64 = sqlx::query_scalar("SELECT ord_ts FROM book_gap WHERE expected_seq = 7")
        .fetch_one(&db.pool())
        .await
        .unwrap();
    assert_eq!(ord_ts, 1234);
}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `docker compose run --rm test cargo test -p market_data --test migrations`
Expected: FAIL — `market_data::pg` does not exist.

- [ ] **Step 3: Write the migration**

`trade_executor/migrations/0001_init.sql` (abridged here only in the repetitive middle — write every table listed in Global Constraints, following exactly this pattern):

```sql
CREATE SEQUENCE global_ins_seq;

CREATE TYPE side_enum AS ENUM ('buy', 'sell');

CREATE TABLE book_snapshot (
    pair          text   NOT NULL,
    seq           bigint NOT NULL,
    bid_prices    numeric[] NOT NULL,
    bid_qtys      numeric[] NOT NULL,
    ask_prices    numeric[] NOT NULL,
    ask_qtys      numeric[] NOT NULL,
    exchange_ts   bigint,
    recv_ts       bigint NOT NULL,
    ord_ts        bigint GENERATED ALWAYS AS (COALESCE(exchange_ts, recv_ts)) STORED,
    ins_seq       bigint NOT NULL DEFAULT nextval('global_ins_seq'),
    PRIMARY KEY (pair, seq)
);
CREATE INDEX book_snapshot_scan ON book_snapshot (pair, ord_ts, ins_seq);
CREATE INDEX book_snapshot_tail ON book_snapshot (ins_seq);

CREATE TABLE book_update (
    pair          text   NOT NULL,
    seq           bigint NOT NULL,
    bid_prices    numeric[] NOT NULL,
    bid_qtys      numeric[] NOT NULL,
    ask_prices    numeric[] NOT NULL,
    ask_qtys      numeric[] NOT NULL,
    exchange_ts   bigint,
    recv_ts       bigint NOT NULL,
    ord_ts        bigint GENERATED ALWAYS AS (COALESCE(exchange_ts, recv_ts)) STORED,
    ins_seq       bigint NOT NULL DEFAULT nextval('global_ins_seq'),
    PRIMARY KEY (pair, seq)
);
CREATE INDEX book_update_scan ON book_update (pair, ord_ts, ins_seq);
CREATE INDEX book_update_tail ON book_update (ins_seq);

CREATE TABLE book_gap (
    pair          text   NOT NULL,
    expected_seq  bigint NOT NULL,
    observed_seq  bigint,
    exchange_ts   bigint,
    recv_ts       bigint NOT NULL,
    ord_ts        bigint GENERATED ALWAYS AS (COALESCE(exchange_ts, recv_ts)) STORED,
    ins_seq       bigint NOT NULL DEFAULT nextval('global_ins_seq'),
    PRIMARY KEY (pair, expected_seq)
);
CREATE INDEX book_gap_scan ON book_gap (pair, ord_ts, ins_seq);
CREATE INDEX book_gap_tail ON book_gap (ins_seq);

CREATE TABLE trade (
    pair          text   NOT NULL,
    trade_id      bigint NOT NULL,
    price         numeric NOT NULL,
    qty           numeric NOT NULL,
    side          side_enum NOT NULL,
    exchange_ts   bigint,
    recv_ts       bigint NOT NULL,
    ord_ts        bigint GENERATED ALWAYS AS (COALESCE(exchange_ts, recv_ts)) STORED,
    ins_seq       bigint NOT NULL DEFAULT nextval('global_ins_seq'),
    PRIMARY KEY (pair, trade_id)
);
CREATE INDEX trade_scan ON trade (pair, ord_ts, ins_seq);
CREATE INDEX trade_tail ON trade (ins_seq);

CREATE TABLE candle (
    pair          text   NOT NULL,
    interval      text   NOT NULL,
    open_time     bigint NOT NULL,
    open          numeric NOT NULL,
    high          numeric NOT NULL,
    low           numeric NOT NULL,
    close         numeric NOT NULL,
    volume        numeric NOT NULL,
    close_time    bigint NOT NULL,
    is_closed     boolean NOT NULL,
    exchange_ts   bigint,
    recv_ts       bigint NOT NULL,
    ord_ts        bigint GENERATED ALWAYS AS (COALESCE(exchange_ts, recv_ts)) STORED,
    ins_seq       bigint NOT NULL DEFAULT nextval('global_ins_seq'),
    PRIMARY KEY (pair, interval, open_time)
);
CREATE INDEX candle_scan ON candle (pair, ord_ts, ins_seq);
CREATE INDEX candle_tail ON candle (ins_seq);

-- Account tables: `seq` is drawn from the SAME sequence, so it is both the
-- primary key and the tail cursor. No separate ins_seq column.
CREATE TABLE order_event (
    seq             bigint PRIMARY KEY DEFAULT nextval('global_ins_seq'),
    order_id        bigint NOT NULL,
    pair            text   NOT NULL,
    side            side_enum NOT NULL,
    status          text   NOT NULL,
    filled_qty      numeric NOT NULL,
    avg_fill_price  numeric,
    exchange_ts     bigint,
    recv_ts         bigint NOT NULL,
    ord_ts          bigint GENERATED ALWAYS AS (COALESCE(exchange_ts, recv_ts)) STORED
);

CREATE TABLE balance_event (
    seq          bigint PRIMARY KEY DEFAULT nextval('global_ins_seq'),
    asset        text   NOT NULL,
    free         numeric NOT NULL,
    locked       numeric NOT NULL,
    exchange_ts  bigint,
    recv_ts      bigint NOT NULL,
    ord_ts       bigint GENERATED ALWAYS AS (COALESCE(exchange_ts, recv_ts)) STORED
);

CREATE TABLE position_event (
    seq                bigint PRIMARY KEY DEFAULT nextval('global_ins_seq'),
    pair               text   NOT NULL,
    side               side_enum NOT NULL,
    size               numeric NOT NULL,
    entry_price        numeric NOT NULL,
    leverage           numeric,
    liquidation_price  numeric,
    exchange_ts        bigint,
    recv_ts            bigint NOT NULL,
    ord_ts             bigint GENERATED ALWAYS AS (COALESCE(exchange_ts, recv_ts)) STORED
);

-- L5 tables (see Task 6 for the DTO mapping).
CREATE TABLE position_state (
    pair        text PRIMARY KEY,
    state       jsonb  NOT NULL,
    updated_at  bigint NOT NULL
);

CREATE TABLE decision_log (
    seq          bigint PRIMARY KEY DEFAULT nextval('global_ins_seq'),
    decision_id  text   NOT NULL,
    record       jsonb  NOT NULL,
    received_at  bigint NOT NULL
);

CREATE TABLE event_log (
    seq         bigint PRIMARY KEY DEFAULT nextval('global_ins_seq'),
    pair        text   NOT NULL,
    event       jsonb  NOT NULL,
    recorded_at bigint NOT NULL
);
```

`position_state`/`decision_log`/`event_log` keep `jsonb` payloads deliberately: they carry Rust enums with variant-specific shapes (`PositionStatus`, `DecisionRecord`), not fixed numeric columns, and nothing queries inside them. Market-data tables get real columns because they are queried, ordered and aggregated.

- [ ] **Step 4: Expose the migrator**

`trade_executor/crates/market_data/src/pg/mod.rs`:

```rust
pub mod reader;
pub mod rows;
pub mod writer;

/// Bumped whenever `migrations/` changes. The visualiser refuses to serve
/// against a database whose applied version differs (see Task 8).
pub const SCHEMA_VERSION: i64 = 1;

pub static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("../../migrations");
```

Add to `crates/market_data/Cargo.toml`:

```toml
async-trait = "0.1"
sqlx = { version = "0.8", default-features = false, features = ["runtime-tokio", "postgres", "macros", "rust_decimal", "migrate"] }

[dev-dependencies]
test_support = { path = "../test_support" }
```

- [ ] **Step 5: Run tests and verify they pass**

Run: `docker compose run --rm test cargo test -p market_data --test migrations`
Expected: PASS, both tests.

- [ ] **Step 6: Commit**

```bash
git add migrations crates/market_data/src/pg crates/market_data/Cargo.toml crates/market_data/tests/migrations.rs Cargo.lock
git commit -m "feat(market_data): Postgres schema, one table per stream kind"
```

---

## Task 3: Row mapping (wire types ⇄ tables)

Isolated from writer and reader so both sides share one definition and a mapping bug fails here, not in an integration test.

**Files:**
- Create: `trade_executor/crates/market_data/src/pg/rows.rs`

**Interfaces:**
- Consumes: `exchange_adapter::{MarketDataEvent, AccountEvent, OrderBookSnapshot, OrderBookUpdate, TradeTick, CandleUpdate, GapMarker}`.
- Produces:
  - `pub struct BookRow { pub pair: String, pub seq: i64, pub bid_prices: Vec<Decimal>, pub bid_qtys: Vec<Decimal>, pub ask_prices: Vec<Decimal>, pub ask_qtys: Vec<Decimal>, pub exchange_ts: Option<i64>, pub recv_ts: i64 }`
  - `pub fn snapshot_to_row(s: &OrderBookSnapshot, recv_ts: i64) -> BookRow`
  - `pub fn row_to_snapshot(r: BookRow) -> OrderBookSnapshot`
  - `pub fn update_to_row(u: &OrderBookUpdate, recv_ts: i64) -> BookRow`
  - `pub fn row_to_update(r: BookRow) -> OrderBookUpdate`
  - equivalents for `TradeRow`, `CandleRow`, `GapRow`, and the three account rows.

- [ ] **Step 1: Write the failing round-trip tests**

In `rows.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use exchange_adapter::{Pair, PriceLevel, Ts};
    use rust_decimal::Decimal;

    fn snapshot() -> OrderBookSnapshot {
        OrderBookSnapshot {
            pair: Pair("BTCUSDT".into()),
            bids: vec![PriceLevel { price: Decimal::new(10050, 2), qty: Decimal::new(15, 1) }],
            asks: vec![PriceLevel { price: Decimal::new(10075, 2), qty: Decimal::new(20, 1) }],
            sequence: 42,
            ts: Ts(1700),
        }
    }

    #[test]
    fn snapshot_survives_a_row_round_trip_with_exact_decimals() {
        let original = snapshot();
        let back = row_to_snapshot(snapshot_to_row(&original, 1800));
        assert_eq!(back, original);
    }

    #[test]
    fn a_book_row_keeps_prices_and_quantities_index_aligned() {
        let row = snapshot_to_row(&snapshot(), 1800);
        assert_eq!(row.bid_prices.len(), row.bid_qtys.len());
        assert_eq!(row.bid_prices[0], Decimal::new(10050, 2));
        assert_eq!(row.bid_qtys[0], Decimal::new(15, 1));
    }

    #[test]
    fn an_empty_side_round_trips_as_an_empty_side_not_a_null() {
        let mut s = snapshot();
        s.asks.clear();
        let back = row_to_snapshot(snapshot_to_row(&s, 1800));
        assert!(back.asks.is_empty());
    }

    #[test]
    fn a_zero_quantity_delta_survives_because_it_means_remove_the_level() {
        let update = OrderBookUpdate {
            pair: Pair("BTCUSDT".into()),
            bids: vec![PriceLevelDelta { price: Decimal::new(100, 0), qty: Decimal::ZERO }],
            asks: vec![],
            sequence: 9,
            ts: Ts(50),
        };
        let back = row_to_update(update_to_row(&update, 60));
        assert_eq!(back.bids[0].qty, Decimal::ZERO);
    }
}
```

- [ ] **Step 2: Run and watch fail**

Run: `docker compose run --rm test cargo test -p market_data pg::rows`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Implement the mappings**

Write `BookRow`/`TradeRow`/`CandleRow`/`GapRow` plus `OrderEventRow`/`BalanceEventRow`/`PositionEventRow` as plain structs deriving `sqlx::FromRow`, with the conversion functions listed under Interfaces. `exchange_ts` is `Some(event.ts.0 as i64)` for every event that carries an exchange timestamp; `None` only where the source genuinely had none (REST snapshots — the caller decides and passes it, the mapping never guesses). `recv_ts` is always the caller's value.

- [ ] **Step 4: Run and verify pass**

Run: `docker compose run --rm test cargo test -p market_data pg::rows`
Expected: PASS, four tests.

- [ ] **Step 5: Commit**

```bash
git add crates/market_data/src/pg/rows.rs
git commit -m "feat(market_data): wire-type to row mapping with exact numerics"
```

---

## Task 4: Write path — batching writer, async ingest, backpressure

**Files:**
- Create: `trade_executor/crates/market_data/src/pg/writer.rs`
- Modify: `trade_executor/crates/market_data/src/store.rs`, `crates/market_data/src/lib.rs`
- Delete: `trade_executor/crates/market_data/src/keys.rs`

**Interfaces:**
- Consumes: `pg::rows::*`, `pg::MIGRATOR`, `observability::{Alerts, Metrics}`.
- Produces:
  - `pub struct PgConfig { pub url: String, pub max_conns: u32, pub queue_capacity: usize, pub flush_rows: usize, pub flush_interval: Duration }`, with `PgConfig::from_url(url: &str) -> Self` defaulting to `max_conns: 4, queue_capacity: 50_000, flush_rows: 1_000, flush_interval: Duration::from_millis(50)`
  - `MarketDataService::connect(cfg: PgConfig, alerts: Arc<dyn Alerts>, metrics: Arc<dyn Metrics>) -> Result<Arc<Self>, StoreError>`
  - `async fn MarketDataService::ingest(&self, event: MarketDataEvent) -> Result<(), StoreError>`
  - `async fn MarketDataService::ingest_account_event(&self, event: AccountEvent) -> Result<(), StoreError>`
  - `async fn MarketDataService::flush(&self) -> Result<(), StoreError>` — waits until everything enqueued so far is committed. Tests use this instead of sleeping.
  - `StoreError::Db(sqlx::Error)`, `StoreError::WriterGone`

- [ ] **Step 1: Write the failing tests**

`trade_executor/crates/market_data/tests/write_path.rs`:

```rust
use market_data::{MarketDataEvent, MarketDataService, PgConfig, Pair, Ts};
use test_support::test_db;

#[tokio::test]
async fn ingested_events_are_committed_and_readable_after_flush() {
    let db = test_db().await;
    let svc = service(&db).await;

    svc.ingest(trade_event(&Pair("BTCUSDT".into()), 1, 100)).await.unwrap();
    svc.flush().await.unwrap();

    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM trade")
        .fetch_one(&db.pool())
        .await
        .unwrap();
    assert_eq!(count, 1);
}

#[tokio::test]
async fn re_ingesting_the_same_key_after_a_resync_stores_one_row_not_two() {
    let db = test_db().await;
    let svc = service(&db).await;
    let pair = Pair("BTCUSDT".into());

    svc.ingest(book_update_event(&pair, 7)).await.unwrap();
    svc.ingest(book_update_event(&pair, 7)).await.unwrap();
    svc.flush().await.unwrap();

    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM book_update WHERE seq = 7")
        .fetch_one(&db.pool())
        .await
        .unwrap();
    assert_eq!(count, 1);
}

#[tokio::test]
async fn a_detected_gap_writes_a_book_gap_row_and_fires_an_alert() {
    let db = test_db().await;
    let alerts = Arc::new(RecordingAlerts::default());
    let svc = service_with_alerts(&db, alerts.clone()).await;
    let pair = Pair("BTCUSDT".into());

    svc.ingest(book_update_event(&pair, 1)).await.unwrap();
    svc.ingest(book_update_event(&pair, 3)).await.unwrap(); // 2 missing
    svc.flush().await.unwrap();

    let expected: Vec<i64> = sqlx::query_scalar("SELECT expected_seq FROM book_gap")
        .fetch_all(&db.pool())
        .await
        .unwrap();
    assert_eq!(expected, vec![2]);
    assert_eq!(alerts.kinds(), vec![AlertKind::FeedStale]);
}

#[tokio::test]
async fn a_full_queue_stalls_the_producer_and_still_stores_every_event() {
    let db = test_db().await;
    let mut cfg = PgConfig::from_url(&db.url);
    cfg.queue_capacity = 8;      // tiny, so the producer must block
    cfg.flush_rows = 4;
    let svc = service_with_config(&db, cfg).await;
    let pair = Pair("BTCUSDT".into());

    for seq in 1..=200 {
        svc.ingest(book_update_event(&pair, seq)).await.unwrap();
    }
    svc.flush().await.unwrap();

    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM book_update")
        .fetch_one(&db.pool())
        .await
        .unwrap();
    assert_eq!(count, 200, "backpressure must stall, never drop");
}

#[tokio::test]
async fn book_snapshots_store_a_null_exchange_ts_because_rest_gives_none() {
    let db = test_db().await;
    let svc = service(&db).await;

    svc.ingest(snapshot_event(&Pair("BTCUSDT".into()), 1)).await.unwrap();
    svc.flush().await.unwrap();

    let exchange_ts: Option<i64> = sqlx::query_scalar("SELECT exchange_ts FROM book_snapshot")
        .fetch_one(&db.pool())
        .await
        .unwrap();
    assert_eq!(exchange_ts, None);
}
```

Helpers `service`, `service_with_alerts`, `service_with_config`, `trade_event`, `book_update_event`, `snapshot_event` and `RecordingAlerts` go in `trade_executor/crates/market_data/tests/common/mod.rs`. `RecordingAlerts` implements `observability::Alerts` by pushing each `AlertEvent` into a `Mutex<Vec<_>>` and exposes `kinds() -> Vec<AlertKind>`.

- [ ] **Step 2: Run and watch fail**

Run: `docker compose run --rm test cargo test -p market_data --test write_path`
Expected: FAIL — `MarketDataService::connect` / `PgConfig` not found.

- [ ] **Step 3: Implement the writer task**

In `pg/writer.rs`: a `WriteOp` enum (one variant per table), a bounded `tokio::sync::mpsc` receiver loop that accumulates per-table `Vec`s, and a flush triggered by `flush_rows` or `flush_interval` (`tokio::select!` on the channel and an interval timer). Each flush opens one transaction and issues one multi-row `INSERT … ON CONFLICT DO NOTHING` per non-empty table using `sqlx::QueryBuilder::push_values`, then commits. `WriteOp::Flush(oneshot::Sender<Result<(), StoreError>>)` implements `MarketDataService::flush`: the writer flushes, commits, then answers — which is what makes the tests above deterministic without sleeps.

On flush error: retry with exponential backoff (100ms, doubling, capped 5s), keeping the batch. After 30s of continuous failure, fire `AlertKind::FeedStale` at `Severity::Critical` and set an `Arc<AtomicBool> write_failed` flag that Task 7 wires to shutdown.

- [ ] **Step 4: Convert `ingest` to async and keep the live path intact**

In `store.rs`, `ingest` keeps its existing structure — live caches, `BookTracker::apply_update`, gap detection, `Metrics::record("market_data_gap_detected")`, `Alerts::fire(FeedStale)` — and replaces every `sled::Tree::insert` with an enqueue. Enqueue is `try_send`, and on `TrySendError::Full` fires one alert per episode, then `send().await`.

Delete `crates/market_data/src/keys.rs` and its `mod keys;` declaration; the byte-key encoding has no Postgres counterpart.

- [ ] **Step 5: Run and verify pass**

Run: `docker compose run --rm test cargo test -p market_data --test write_path`
Expected: PASS, five tests.

- [ ] **Step 6: Commit**

```bash
git add crates/market_data/src crates/market_data/tests
git rm crates/market_data/src/keys.rs
git commit -m "feat(market_data): batching Postgres writer with stall-not-drop backpressure"
```

---

## Task 5: Read path — async traits, ordered merge, tail cursor, freshness

**Files:**
- Create: `trade_executor/crates/market_data/src/pg/reader.rs`
- Modify: `trade_executor/crates/market_data/src/lib.rs`, `crates/market_data/src/store.rs`, `crates/market_data/src/replay.rs`

**Interfaces:**
- Consumes: Task 3's row mapping, Task 4's `PgConfig`.
- Produces:
  - `pub struct InsSeq(pub i64);`
  - `#[async_trait] pub trait MarketDataStore: Send + Sync { async fn read_range(&self, pair: Pair, from: Ts, to: Ts) -> Result<MarketDataStream, StoreError>; async fn read_account_events(&self, from: Ts, to: Ts) -> Result<AccountEventStream, StoreError>; async fn replay(&self, pair: Pair, from: Ts, to: Ts, speed: ReplaySpeed) -> Result<Box<dyn MarketDataFeed>, StoreError>; async fn tail(&self, pair: Pair, after: InsSeq, limit: i64) -> Result<Vec<(InsSeq, MarketDataEvent)>, StoreError>; async fn latest_recv_ts(&self, pair: Pair) -> Result<Option<Ts>, StoreError>; }`
  - `pub struct PgMarketDataReader;` with `PgMarketDataReader::connect(cfg: PgConfig) -> Result<Self, StoreError>` — implements `MarketDataStore` and **not** `MarketDataFeed`.
  - `MarketDataService` implements both traits (executor side).

- [ ] **Step 1: Write the failing tests**

`trade_executor/crates/market_data/tests/read_path.rs`:

```rust
#[tokio::test]
async fn read_range_merges_every_stream_kind_in_ord_ts_order() {
    let db = test_db().await;
    let svc = service(&db).await;
    let pair = Pair("BTCUSDT".into());

    svc.ingest(candle_event(&pair, 300)).await.unwrap();
    svc.ingest(trade_event(&pair, 1, 100)).await.unwrap();
    svc.ingest(book_update_at(&pair, 5, 200)).await.unwrap();
    svc.flush().await.unwrap();

    let events: Vec<_> = svc.read_range(pair, Ts(0), Ts(1000)).await.unwrap().collect().await;
    let timestamps: Vec<u64> = events.iter().map(event_ts).collect();
    assert_eq!(timestamps, vec![100, 200, 300]);
}

#[tokio::test]
async fn a_recorded_gap_is_yielded_between_its_real_neighbours() {
    let db = test_db().await;
    let svc = service(&db).await;
    let pair = Pair("BTCUSDT".into());

    svc.ingest(book_update_at(&pair, 1, 100)).await.unwrap();
    svc.ingest(book_update_at(&pair, 3, 300)).await.unwrap(); // gap at 2
    svc.flush().await.unwrap();

    let events: Vec<_> = svc.read_range(pair, Ts(0), Ts(1000)).await.unwrap().collect().await;
    assert!(matches!(events[1], MarketDataEvent::Gap(_)), "gap must sit between the two updates");
}

#[tokio::test]
async fn account_events_read_back_in_exact_write_order_across_all_three_tables() {
    let db = test_db().await;
    let svc = service(&db).await;

    svc.ingest_account_event(order_event(1)).await.unwrap();
    svc.ingest_account_event(balance_event("USDT")).await.unwrap();
    svc.ingest_account_event(position_event(&Pair("BTCUSDT".into()))).await.unwrap();
    svc.ingest_account_event(order_event(2)).await.unwrap();
    svc.flush().await.unwrap();

    let events: Vec<_> = svc.read_account_events(Ts(0), Ts(u64::MAX)).await.unwrap().collect().await;
    assert!(matches!(events[0], AccountEvent::OrderUpdate(ref o) if o.id.0 == 1));
    assert!(matches!(events[1], AccountEvent::BalanceUpdate(_)));
    assert!(matches!(events[2], AccountEvent::PositionUpdate(_)));
    assert!(matches!(events[3], AccountEvent::OrderUpdate(ref o) if o.id.0 == 2));
}

#[tokio::test]
async fn the_tail_cursor_delivers_a_late_row_whose_ord_ts_is_behind_the_cursor() {
    // This is the regression test for the ord_ts-as-cursor hole. A row
    // inserted later with an EARLIER timestamp must still be delivered.
    let db = test_db().await;
    let svc = service(&db).await;
    let pair = Pair("BTCUSDT".into());

    svc.ingest(trade_at(&pair, 1, 5_000)).await.unwrap();
    svc.flush().await.unwrap();
    let first = svc.tail(pair.clone(), InsSeq(0), 100).await.unwrap();
    let cursor = first.last().unwrap().0;

    svc.ingest(trade_at(&pair, 2, 1_000)).await.unwrap(); // ord_ts far behind
    svc.flush().await.unwrap();

    let next = svc.tail(pair, cursor, 100).await.unwrap();
    assert_eq!(next.len(), 1, "late row with an earlier ord_ts must still arrive");
}

#[tokio::test]
async fn latest_recv_ts_reports_none_for_a_pair_with_no_rows() {
    let db = test_db().await;
    let svc = service(&db).await;
    assert_eq!(svc.latest_recv_ts(Pair("ETHUSDT".into())).await.unwrap(), None);
}

#[tokio::test]
async fn the_read_only_reader_returns_the_same_events_the_writer_stored() {
    let db = test_db().await;
    let svc = service(&db).await;
    let pair = Pair("BTCUSDT".into());
    svc.ingest(trade_event(&pair, 1, 100)).await.unwrap();
    svc.flush().await.unwrap();

    let reader = PgMarketDataReader::connect(PgConfig::from_url(&db.url)).await.unwrap();
    let events: Vec<_> = reader.read_range(pair, Ts(0), Ts(1000)).await.unwrap().collect().await;
    assert_eq!(events.len(), 1);
}
```

- [ ] **Step 2: Run and watch fail**

Run: `docker compose run --rm test cargo test -p market_data --test read_path`
Expected: FAIL — trait is not async, `tail`/`latest_recv_ts`/`PgMarketDataReader` missing.

- [ ] **Step 3: Implement the reader**

`read_range` issues one `UNION ALL` over the five market-data tables for the pair, each branch selecting a discriminator column plus its own payload, `WHERE ord_ts BETWEEN $2 AND $3`, `ORDER BY ord_ts, ins_seq`, keyset-paged by `(ord_ts, ins_seq)` with a page size of 5000; the returned `MarketDataStream` fetches pages lazily via `async_stream::stream!`. `read_account_events` is the same shape over the three account tables ordered by `seq`. `tail` is the same union with `WHERE ins_seq > $2 ORDER BY ins_seq LIMIT $3`. `latest_recv_ts` is `SELECT max(recv_ts)` across the market-data tables for the pair.

`read_range` must also emit the seeding snapshot: the latest `book_snapshot` with `ord_ts < from`, prepended, exactly as `collect_range` does today.

`replay` collects the range and hands it to the existing `ReplayFeed`, unchanged apart from being built inside an async fn.

`PgMarketDataReader` holds only a pool and implements `MarketDataStore`. Do not implement `MarketDataFeed` for it — the compile error is the safety mechanism.

- [ ] **Step 4: Update every call site the async traits break**

`replay_harness`, `local_analysis`, `visualizer_backend` and `orchestrator` call these methods; add `.await?` and make enclosing functions async where needed. Do not change their logic in this task.

- [ ] **Step 5: Run and verify pass**

Run: `docker compose run --rm test cargo test --workspace`
Expected: PASS, whole workspace.

- [ ] **Step 6: Commit**

```bash
git add crates/market_data crates/replay_harness crates/local_analysis crates/visualizer_backend
git commit -m "feat(market_data): async Postgres reads, ins_seq tail cursor, ordered union merge"
```

---

## Task 6: L5 state_store on Postgres

**Files:**
- Create: `trade_executor/crates/state_store/src/pg.rs`
- Modify: `crates/state_store/src/store.rs`, `crates/state_store/src/lib.rs`, `crates/cli/src/lib.rs` (its `FakeStore`)
- Delete: `crates/state_store/src/keys.rs`

**Interfaces:**
- Consumes: `market_data::PgConfig`, the `position_state`/`decision_log`/`event_log` tables from Task 2.
- Produces:
  - `#[async_trait] pub trait StateStore: Send + Sync { async fn persist(&self, state: PositionState) -> Result<(), StoreError>; async fn load_all(&self) -> Result<Vec<PositionState>, StoreError>; async fn reconcile(&self, truth: AccountState) -> Result<ReconciliationReport, StoreError>; async fn log_decision(&self, id: execution::DecisionId, record: DecisionRecord, received_at: Ts) -> Result<(), StoreError>; async fn read_decision_log(&self, from: Ts, to: Ts) -> Result<DecisionLogStream, StoreError>; }`
  - `StateStoreImpl::connect(cfg: PgConfig, metrics: Arc<dyn Metrics>) -> Result<Self, StoreError>`
  - `pub struct PgStateReader;` with `connect(cfg)`, exposing `load_all` and `read_decision_log` only.

**If** `append_event`/`read_event_log` already exist on this branch (the `state-store-expansion` work), port them here on the same terms, backed by `event_log`, and add `PgStateReader::read_event_log`. **If not**, leave `event_log` unused — Task 2 creates the table either way, so the later merge needs no migration.

- [ ] **Step 1: Write the failing tests**

`trade_executor/crates/state_store/tests/pg_store.rs`:

```rust
#[tokio::test]
async fn a_persisted_position_is_returned_by_load_all_after_reconnecting() {
    let db = test_db().await;
    let store = store(&db).await;
    store.persist(open_position("BTCUSDT")).await.unwrap();

    let reopened = StateStoreImpl::connect(PgConfig::from_url(&db.url), metrics()).await.unwrap();
    let all = reopened.load_all().await.unwrap();
    assert_eq!(all.len(), 1);
}

#[tokio::test]
async fn persist_is_durable_before_it_returns_not_queued_for_later() {
    let db = test_db().await;
    let store = store(&db).await;
    store.persist(open_position("BTCUSDT")).await.unwrap();

    // No flush() call: a second, independent connection must already see it.
    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM position_state")
        .fetch_one(&db.pool())
        .await
        .unwrap();
    assert_eq!(count, 1);
}

#[tokio::test]
async fn persisting_the_same_pair_twice_updates_it_rather_than_duplicating() {
    let db = test_db().await;
    let store = store(&db).await;
    store.persist(open_position("BTCUSDT")).await.unwrap();
    store.persist(closed_position("BTCUSDT")).await.unwrap();

    let all = store.load_all().await.unwrap();
    assert_eq!(all.len(), 1);
    assert!(matches!(all[0].status, PositionStatus::Closed));
}

#[tokio::test]
async fn the_decision_log_reads_back_in_write_order_within_a_window() {
    let db = test_db().await;
    let store = store(&db).await;
    store.log_decision(DecisionId("a".into()), record(), Ts(10)).await.unwrap();
    store.log_decision(DecisionId("b".into()), record(), Ts(20)).await.unwrap();

    let records: Vec<_> = store.read_decision_log(Ts(0), Ts(100)).await.unwrap().collect().await;
    assert_eq!(records.len(), 2);
}

#[tokio::test]
async fn the_read_only_state_reader_sees_what_the_writer_persisted() {
    let db = test_db().await;
    let store = store(&db).await;
    store.persist(open_position("BTCUSDT")).await.unwrap();

    let reader = PgStateReader::connect(PgConfig::from_url(&db.url)).await.unwrap();
    assert_eq!(reader.load_all().await.unwrap().len(), 1);
}
```

- [ ] **Step 2: Run and watch fail**

Run: `docker compose run --rm test cargo test -p state_store --test pg_store`
Expected: FAIL — `StateStoreImpl::connect` not found.

- [ ] **Step 3: Implement**

`persist` is `INSERT INTO position_state … ON CONFLICT (pair) DO UPDATE`, committed before return — no queue, no writer task. `log_decision` is a plain insert. `load_all` and `read_decision_log` deserialize the `jsonb` payload through the existing `PositionStateDto`. `reconcile` keeps its current logic and awaits `persist` for each correction. `last_reconciliation` stays an in-memory field.

- [ ] **Step 4: Update `cli`'s `FakeStore` to the async trait**

`crates/cli/src/lib.rs:153` implements `StateStore` for a test double; add `#[async_trait]` and `async fn`s. Behaviour unchanged.

- [ ] **Step 5: Run and verify pass**

Run: `docker compose run --rm test cargo test -p state_store -p cli`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add crates/state_store crates/cli
git rm crates/state_store/src/keys.rs
git commit -m "feat(state_store): Postgres backend with synchronous durability"
```

---

## Task 7: Orchestrator wiring — DATABASE_URL, migrations at boot, write-failure shutdown

**Files:**
- Modify: `crates/orchestrator/src/config.rs:30,100,139`, `crates/orchestrator/src/system.rs:151,190`, `crates/orchestrator/src/main.rs`, `crates/orchestrator/src/tests.rs`

**Interfaces:**
- Consumes: `MarketDataService::connect`, `StateStoreImpl::connect`, `market_data::pg::MIGRATOR`.
- Produces: `Config { database_url: String, … }` (with `market_data_path`/`state_store_path` removed); `--migrate-only` CLI flag on the `trade_executor` binary.

- [ ] **Step 1: Write the failing tests**

`crates/orchestrator/src/tests.rs`:

```rust
#[tokio::test]
async fn config_requires_database_url_and_no_longer_requires_store_paths() {
    let _guard = ENV_LOCK.lock().unwrap();
    clear_all_vars();
    set_valid_env(); // helper: every required var EXCEPT DATABASE_URL
    let err = Config::from_env().unwrap_err();
    assert!(err.reason.contains("DATABASE_URL"));
    assert!(!err.reason.contains("MARKET_DATA_PATH"));
}

#[tokio::test]
async fn boot_fails_cleanly_when_the_database_is_unreachable() {
    let mut config = valid_config();
    config.database_url = "postgres://executor:executor@127.0.0.1:1/trader".into();
    let err = build_system(config, mock_account()).await.unwrap_err();
    assert!(matches!(err, BootError::Store(_)));
}

#[tokio::test]
async fn sustained_write_failure_triggers_shutdown_rather_than_trading_blind() {
    let db = test_db().await;
    let system = boot_with(&db).await;
    drop_the_schema(&db).await; // every write now errors

    feed_events(&system, 50).await;
    let fired = tokio::time::timeout(Duration::from_secs(60), system.wait_for_shutdown()).await;
    assert!(fired.is_ok(), "executor must shut down when it cannot record state");
}
```

- [ ] **Step 2: Run and watch fail**

Run: `docker compose run --rm test cargo test -p orchestrator`
Expected: FAIL — `database_url` field missing.

- [ ] **Step 3: Implement config and boot changes**

Replace the two `PathBuf` fields with `database_url: String` in [config.rs:30](../../trade_executor/crates/orchestrator/src/config.rs), swap the two `req(&mut errors, …)` calls for `req(&mut errors, "DATABASE_URL")`, and update `ALL_VARS`. In `system.rs`, run `MIGRATOR.run(&pool)` before constructing either store, then `MarketDataService::connect` / `StateStoreImpl::connect`. Add `--migrate-only` to `main.rs`: run migrations, print the applied version, exit 0.

- [ ] **Step 4: Wire the write-failure flag to shutdown**

Task 4 set an `AtomicBool` on sustained write failure. Spawn a supervisor task that polls it and calls `shutdown_tx.send(true)` with a `Critical` alert.

**Before implementing, verify the claim this rests on:** read `execution`'s stop-loss path and confirm open positions carry an exchange-native stop that survives executor exit. If they do not, stop and report it — the shutdown policy would then be leaving positions unguarded, and the spec's Error handling section needs revisiting rather than implementing as written.

- [ ] **Step 5: Run and verify pass**

Run: `docker compose run --rm test cargo test --workspace`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add crates/orchestrator
git commit -m "feat(orchestrator): DATABASE_URL config, boot migrations, write-failure shutdown"
```

---

## Task 8: visualizer_backend becomes reader-only

**Files:**
- Modify: `crates/visualizer_backend/src/lib.rs` (whole file — `LiveModeFlag`, `catch_unwind` and the `feed` handle all go)

**Interfaces:**
- Consumes: `PgMarketDataReader`, `PgStateReader`, `InsSeq`.
- Produces:
  - `pub enum Freshness { Fresh { lag_ms: u64 }, Stale { lag_ms: u64 }, Offline }`
  - `VisualizerBackend::new(store: Arc<dyn MarketDataStore>, state: Arc<PgStateReader>, thresholds: FreshnessThresholds) -> Self`
  - `FreshnessThresholds { stale_after: Duration, offline_after: Duration }`
  - `async fn historical(&self, pair, from, to) -> Result<MarketDataStream, VisualizerError>`
  - `async fn tail(&self, pair, after: InsSeq, limit: i64) -> Result<Vec<(InsSeq, MarketDataEvent)>, VisualizerError>`
  - `async fn freshness(&self, pair, now: Ts) -> Result<Freshness, VisualizerError>`
  - `async fn order_book_view(&self, pair, from, to) -> Result<Vec<OrderBookSnapshot>, VisualizerError>`

- [ ] **Step 1: Write the failing tests**

```rust
#[tokio::test]
async fn freshness_is_fresh_when_the_newest_row_is_recent() {
    let db = test_db().await;
    let (svc, backend) = writer_and_backend(&db).await;
    svc.ingest(trade_at(&pair(), 1, 10_000)).await.unwrap();
    svc.flush().await.unwrap();

    assert!(matches!(backend.freshness(pair(), Ts(10_500)).await.unwrap(), Freshness::Fresh { .. }));
}

#[tokio::test]
async fn freshness_is_stale_past_the_threshold_and_offline_past_the_longer_one() {
    let db = test_db().await;
    let (svc, backend) = writer_and_backend(&db).await; // stale_after 5s, offline_after 60s
    svc.ingest(trade_at(&pair(), 1, 10_000)).await.unwrap();
    svc.flush().await.unwrap();

    assert!(matches!(backend.freshness(pair(), Ts(20_000)).await.unwrap(), Freshness::Stale { .. }));
    assert!(matches!(backend.freshness(pair(), Ts(100_000)).await.unwrap(), Freshness::Offline));
}

#[tokio::test]
async fn freshness_is_offline_for_a_pair_that_never_produced_a_row() {
    let db = test_db().await;
    let (_svc, backend) = writer_and_backend(&db).await;
    assert!(matches!(backend.freshness(Pair("ETHUSDT".into()), Ts(1)).await.unwrap(), Freshness::Offline));
}

#[tokio::test]
async fn order_book_view_folds_snapshot_plus_updates_into_full_depth() {
    let db = test_db().await;
    let (svc, backend) = writer_and_backend(&db).await;
    svc.ingest(snapshot_with_bid(&pair(), 1, "100", "2")).await.unwrap();
    svc.ingest(update_setting_bid(&pair(), 2, "100", "5")).await.unwrap();
    svc.flush().await.unwrap();

    let books = backend.order_book_view(pair(), Ts(0), Ts(10_000)).await.unwrap();
    assert_eq!(books.last().unwrap().bids[0].qty, Decimal::new(5, 0));
}

#[tokio::test]
async fn a_database_error_degrades_to_a_typed_error_not_a_panic() {
    let db = test_db().await;
    let (_svc, backend) = writer_and_backend(&db).await;
    drop_the_schema(&db).await;
    assert!(backend.historical(pair(), Ts(0), Ts(1)).await.is_err());
}
```

- [ ] **Step 2: Run and watch fail**

Run: `docker compose run --rm test cargo test -p visualizer_backend`
Expected: FAIL — `Freshness` not defined.

- [ ] **Step 3: Implement**

Delete `LiveModeFlag`, the `feed` field, `is_live`, `view` and both `catch_unwind` blocks. `freshness` computes `now - latest_recv_ts` and maps it through the thresholds, returning `Offline` when `latest_recv_ts` is `None`. `order_book_view` folds `read_range` through `BookTracker` (`apply_deltas` stays where it already was, in `market_data::book` — **correction, 2026-09-11**: an earlier version of this step claimed it moved to `exchange_adapter` and was re-exported; that never happened, see `crates/market_data/src/book.rs:10`, and the false claim has been removed from the design doc and from `plans/03-L1-market-data.md`'s note that originated it).

- [ ] **Step 4: Run and verify pass**

Run: `docker compose run --rm test cargo test -p visualizer_backend`
Expected: PASS, five tests.

- [ ] **Step 5: Commit**

```bash
git add crates/visualizer_backend
git commit -m "refactor(visualizer_backend): reader-only backend with freshness in place of LiveModeFlag"
```

---

## Task 9: visualizer_server — separate binary, poll tasks, WS fan-out

**Files:**
- Create: `crates/visualizer_server/Cargo.toml`, `src/main.rs`, `src/config.rs`, `src/poll.rs`, `src/routes.rs`
- Create: `crates/visualizer_server/tests/passive.rs`

**Interfaces:**
- Consumes: `VisualizerBackend`, `PgMarketDataReader`, `PgStateReader`, `market_data::pg::SCHEMA_VERSION`.
- Produces: binary `visualizer`; routes `GET /api/history?pair&from&to`, `GET /api/freshness?pair`, `GET /ws?pair`, `GET /` (static); `VisualizerConfig { database_url, bind_addr, static_dir, poll_interval_ms, pairs }` from env.

- [ ] **Step 1: Write the failing tests**

```rust
#[tokio::test]
async fn the_poller_pushes_newly_committed_rows_to_a_subscriber() {
    let db = test_db().await;
    let (svc, app) = server_with_writer(&db).await;
    let mut rx = app.subscribe(pair());

    svc.ingest(trade_event(&pair(), 1, 100)).await.unwrap();
    svc.flush().await.unwrap();

    let event = tokio::time::timeout(Duration::from_secs(5), rx.recv()).await.unwrap().unwrap();
    assert!(matches!(event, MarketDataEvent::Trade(_)));
}

#[tokio::test]
async fn two_subscribers_share_one_database_poller() {
    let db = test_db().await;
    let (svc, app) = server_with_writer(&db).await;
    let mut a = app.subscribe(pair());
    let mut b = app.subscribe(pair());

    svc.ingest(trade_event(&pair(), 1, 100)).await.unwrap();
    svc.flush().await.unwrap();

    assert!(a.recv().await.is_some());
    assert!(b.recv().await.is_some());
    assert_eq!(app.poller_count(), 1);
}

#[tokio::test]
async fn the_server_serves_while_no_executor_is_running() {
    let db = test_db().await;
    let app = server_only(&db).await; // nothing ingests
    let response = app.get("/api/freshness?pair=BTCUSDT").await;
    assert_eq!(response.status(), 200);
    assert_eq!(response.json::<Freshness>().await, Freshness::Offline);
}

#[tokio::test]
async fn the_server_refuses_to_serve_against_a_mismatched_schema_version() {
    let db = test_db().await;
    apply_migrations_then_bump_recorded_version(&db, 99).await;
    assert!(start_server(&db).await.is_err());
}

#[tokio::test]
async fn the_dashboard_role_cannot_write() {
    let db = test_db().await;
    let pool = connect_as_dashboard(&db).await;
    let err = sqlx::query("INSERT INTO trade (pair, trade_id, price, qty, side, recv_ts)
                           VALUES ('BTCUSDT', 1, 1, 1, 'buy', 1)")
        .execute(&pool)
        .await
        .unwrap_err();
    assert!(err.to_string().contains("permission denied"));
}

#[test]
fn the_visualizer_binary_has_no_exchange_adapter_dependency() {
    // Passivity is a property of the dependency graph, not of good intentions.
    let metadata = std::process::Command::new("cargo")
        .args(["tree", "-p", "visualizer_server", "--prefix", "none", "--no-dedupe"])
        .output()
        .expect("cargo tree");
    let tree = String::from_utf8_lossy(&metadata.stdout);
    assert!(!tree.contains("exchange_adapter_binance"));
    assert!(!tree.contains("exchange_adapter_mexc"));
}
```

- [ ] **Step 2: Run and watch fail**

Run: `docker compose run --rm test cargo test -p visualizer_server`
Expected: FAIL — crate does not exist.

- [ ] **Step 3: Implement**

`AppState` holds the backend, a `HashMap<Pair, broadcast::Sender<MarketDataEvent>>`, and one spawned poll task per configured pair. Each poll task loops: `backend.tail(pair, cursor, 5000)`, advance the cursor to the last `InsSeq`, `send` each event, `sleep(poll_interval)`. `subscribe(pair)` returns a receiver on the existing sender — it never spawns a second poller. `/ws` upgrades and forwards from that receiver. `/api/history` and `/api/freshness` call the backend directly. At startup, compare the applied migration version against `SCHEMA_VERSION` and refuse to serve on mismatch; on a *missing* schema, retry with backoff and serve an "initializing" state instead of exiting.

Dependencies: `axum`, `tokio`, `serde`, `market_data`, `state_store`, `visualizer_backend`, `observability`. **Not** `exchange_adapter_binance`/`_mexc`.

- [ ] **Step 4: Run and verify pass**

Run: `docker compose run --rm test cargo test -p visualizer_server`
Expected: PASS, six tests.

- [ ] **Step 5: Commit**

```bash
git add crates/visualizer_server Cargo.toml Cargo.lock
git commit -m "feat(visualizer_server): passive dashboard server with cursor polling and WS fan-out"
```

---

## Task 10: Split the containers, verify the Docker entry points

**Files:**
- Modify: `trade_executor/Dockerfile`, `trade_executor/docker-compose.yml`

**Interfaces:**
- Consumes: everything above.
- Produces: the four Docker Entry Points at the top of this plan, working.

- [ ] **Step 1: Add the visualizer build stage**

In `Dockerfile`, after the existing `release` stage:

```dockerfile
FROM builder AS visualizer-builder
RUN cargo build --release --locked -p visualizer_server --bin visualizer

FROM debian:trixie-slim AS visualizer
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=visualizer-builder /app/target/release/visualizer /usr/local/bin/visualizer
COPY --from=visualizer-builder /app/crates/visualizer_server/static /usr/local/share/visualizer_server/static
ENTRYPOINT ["/usr/local/bin/visualizer"]
```

- [ ] **Step 2: Split the compose services**

```yaml
  executor:
    build:
      context: .
      target: release
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      - DATABASE_URL=postgres://executor:executor@postgres:5432/trader
      - PAIRS=BTCUSDT
      # ... the rest of the L9 orchestrator vars, unchanged from today's `run` service
      - MARKET_KIND=spot
      - EXCHANGE=mexc
      - API_KEY=${EXCHANGE_API_KEY:-placeholder}
      - API_SECRET=${EXCHANGE_API_SECRET:-placeholder}

  visualizer:
    build:
      context: .
      target: visualizer
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      # Host-only: the dashboard still has no auth of its own.
      - "127.0.0.1:8090:8090"
    environment:
      - DATABASE_URL=postgres://dashboard:dashboard@postgres:5432/trader
      - VISUALIZER_BIND_ADDR=0.0.0.0:8090
      - VISUALIZER_STATIC_DIR=/usr/local/share/visualizer_server/static
      - POLL_INTERVAL_MS=500
      - PAIRS=BTCUSDT
```

Note what is absent from `visualizer`: every exchange variable, and the `executor` role's credentials. Both absences are load-bearing.

Delete the old single `run` service and the `trade_executor_data` volume.

- [ ] **Step 3: Verify each entry point by hand**

```bash
docker compose run --rm test                    # expect: whole workspace green
docker compose run --rm executor --migrate-only # expect: "applied version 1", exit 0
docker compose up -d postgres visualizer        # executor deliberately not started
curl -s localhost:8090/api/freshness?pair=BTCUSDT   # expect: {"Offline":null} or equivalent
docker compose up -d executor                   # expect: boots, ingests
curl -s localhost:8090/api/freshness?pair=BTCUSDT   # expect: Fresh within a few seconds
```

- [ ] **Step 4: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "build: split executor and passive visualizer into separate containers"
```

---

## Task 11: Update the layer specs

Docs live in the external repo (`external/executor/`), never in the code repo.

**Files:**
- Modify: `external/executor/specs/layers/L1-market-data.md`, `L5-state-store.md`, `L8-interfaces.md`
- Modify: `external/executor/plans/03-L1-market-data.md`, `07-L5-state-store.md`, `09-L8-interfaces.md` (status blocks)
- Modify: `external/executor/specs/2026-09-07-executor-visualiser-design.md` (supersession note at the top)

- [ ] **Step 1: L1** — replace the Storage design section (Postgres tables, not sled trees / RocksDB CFs); record that `ingest` and the read methods are async; move `GapMarker` to its own table; mark the k-way-merge deviation **closed**; add the single-writer constraint as a stated requirement; add the `ins_seq`-vs-`ord_ts` cursor rule.
- [ ] **Step 2: L5** — same backend change; write methods async and synchronously durable; `last_reconciliation` still in-memory.
- [ ] **Step 3: L8** — visualiser is a separate process reading committed rows only; `LiveModeFlag` removed, freshness added; no exchange dependency, asserted by test.
- [ ] **Step 4: Supersession note** on the executor-visualiser design: process topology and transport superseded by this spec; panels, `BookTracker` reconstruction and frontend choice still stand.
- [ ] **Step 5: Commit** in the external repo.

---

## Self-review notes

- **Spec coverage:** schema → Task 2; row mapping → Task 3; write path/backpressure → Task 4; read path/tail cursor/freshness → Tasks 5, 8; L5 → Task 6; config/topology → Tasks 7, 10; testing infra → Task 1; passivity enforcement → Task 9; layer specs → Task 11.
- **Unverified claim carried forward:** the write-failure shutdown policy assumes L3 leaves exchange-native stops in place. Task 7 Step 4 verifies before implementing, and stops if false. **Resolved, 2026-09-11: it was false.** MEXC has no exchange-native stop order on either market kind; Task 7 stopped and did not implement the shutdown policy. See the design doc's Error handling section and `task-7-report.md` for the finding, and L1's spec for the wider pre-existing safety gap this exposed.
- **Ordering constraint:** Task 5 breaks every `MarketDataStore` caller at once (async traits). Expect a large mechanical diff in `replay_harness`/`local_analysis`; that is the task's cost, not a sign of scope creep.
