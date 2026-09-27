# Postgres market-data store + passive dashboard — design

Part of [architecture index](2026-09-04-architecture-design.md). Replaces
the storage backend named in [L1 — market_data](layers/L1-market-data.md)
and [L5 — state_store](layers/L5-state-store.md), and supersedes the
process topology in
[executor visualiser design](2026-09-07-executor-visualiser-design.md).

## Purpose

Three changes, one spec because they are the same change seen from three
angles:

1. `market_data` (L1) and `state_store` (L5) move from embedded sled to
   PostgreSQL, one table per stream kind.
2. The visualiser stops being an in-process consumer of the executor's
   `tokio::sync::broadcast` channels and becomes a **separate process**
   that reads only committed database rows.
3. The visualiser holds no exchange connector of any kind — it cannot
   reach an exchange, by dependency graph and by database grant.

The executor remains the only writer. The dashboard is passive: it
observes what the executor recorded, and nothing else.

## What this supersedes

[2026-09-07-executor-visualiser-design.md](2026-09-07-executor-visualiser-design.md)
put `visualizer_server` inside the executor process, subscribing to
`market_data`'s per-pair `broadcast::Sender<MarketDataEvent>` and
`execution`'s `broadcast::Sender<PositionStateEvent>`. That coupling is
removed. Everything that design says about *what* the dashboard renders
(panels, `BookTracker` reconstruction, `lightweight-charts` frontend,
`event_log`/`last_reconciliation` additions to L5) still stands; only the
transport and process boundary change.

`LiveModeFlag` is deleted (see Freshness below).

## Schema

Database `trader`. One table per stream kind.

Every market-data table carries:

- `exchange_ts bigint NULL` — the exchange's own timestamp, `NULL` when
  the source genuinely provides none (REST depth snapshots; MEXC's
  buffered replay path after a resync).
- `recv_ts bigint NOT NULL` — set by the ingester on receipt.
- `ord_ts bigint GENERATED ALWAYS AS (COALESCE(exchange_ts, recv_ts))
  STORED` — the ordering/range-scan column.
- `ins_seq bigint NOT NULL` from one shared sequence — the tail cursor
  column (see Tail cursor below; these are *not* interchangeable).

The three account tables carry `exchange_ts`/`recv_ts`/`ord_ts` on the
same terms, and their `seq` primary key is drawn from that same single
sequence — so `seq` *is* their `ins_seq`, no second column and no second
sequence. One global sequence orders every table in the database.

| Table | PK | Payload |
|---|---|---|
| `book_snapshot` | `(pair, seq)` | `bid_prices numeric[]`, `bid_qtys numeric[]`, `ask_prices numeric[]`, `ask_qtys numeric[]` |
| `book_update` | `(pair, seq)` | same four arrays (deltas; `qty = 0` removes the level) |
| `book_gap` | `(pair, expected_seq)` | `observed_seq bigint NULL` |
| `trade` | `(pair, trade_id)` | `price numeric`, `qty numeric`, `side side_enum` |
| `candle` | `(pair, interval, open_time)` | `open`, `high`, `low`, `close`, `volume numeric`, `close_time bigint`, `is_closed bool` |
| `order_event` | `(seq)` | `order_id`, `pair`, `side`, `status`, `filled_qty`, `avg_fill_price` |
| `balance_event` | `(seq)` | `asset`, `free numeric`, `locked numeric` |
| `position_event` | `(seq)` | `pair`, `side`, `size`, `entry_price`, `leverage`, `liquidation_price` |

L5 tables (`position_state`, `decision_log`, `event_log`) move to the
same database, keeping the shapes L5's own spec defines.
`last_reconciliation` stays in memory — a since-last-boot fact, never
durable, per its L5 addendum.

### Why these shapes

**Gap markers get their own table.** Storing a `GapMarker` inline in
`book_update` was a sled key-space trick: it made the marker appear in
position during a single-tree scan. SQL does not need it — `read_range`
is a `UNION ALL … ORDER BY ord_ts, ins_seq`, so `book_gap` rows merge
back into position for free, and `book_update` stops being a column
family holding two different shapes.

**`numeric`, not JSON.** The sled implementation encodes values as JSON
because `rust_decimal`'s `Deserialize` needs a self-describing format,
which bincode's serde layer could not provide (`store.rs` documents the
`Decode(Serde(AnyNotSupported))` failure). Postgres `numeric` maps to
`rust_decimal` directly via sqlx, so the workaround disappears and
precision is exact on disk rather than exact-after-a-string-round-trip.

**Book sides as four parallel `numeric[]` columns**, not jsonb and not a
row per price level. Row-per-level would multiply `book_update`'s row
count by the depth of every delta; jsonb would put the decimals back
into text.

**Three account tables sharing one sequence.** `AccountEvent` is one
ordered stream in L1's spec, but its three variants share no columns.
Three typed tables drawing `seq` from a single Postgres sequence gives
both: real columns per variant, and an exact global order that
`read_account_events` rebuilds with `UNION ALL … ORDER BY seq`. That
ordering is what L3 Stage 3's "no loss or reordering" criterion checks.

### Indexes

PK on each table, plus `(pair, ord_ts, ins_seq)` on each market-data
table — serves both `read_range`'s time window and the dashboard's
keyset paging. Retention/eviction stays out of scope per L1's spec;
`book_update` is the table that will want partitioning first, noted, not
built.

### Migrations

`sqlx migrate`, files in `trade_executor/migrations`, run by the
**executor** at boot. The visualiser never runs DDL: it checks the
schema version and refuses to serve on a mismatch, so a stale dashboard
image cannot misread newer tables.

## Write path

Two durability regimes, because the two stores have opposite volume
profiles.

### L1 market data — batched, single writer task

`MarketDataService::open(path, …)` becomes `connect(pg_url, …)`: builds a
writer pool and spawns one writer task. `ingest` becomes `async fn` —
every caller (`spawn_ingestion` in `orchestrator::system`, plus tests) is
already async, and `ingest` is an inherent method rather than a trait
method, so no downstream trait re-shaping follows.

Per event:

1. live caches and `BookTracker` gap detection run first, synchronously,
   unchanged — this is what serves `execution`'s hot path;
2. the event is enqueued on a bounded mpsc (~50k);
3. the writer task batches per table until 1000 rows or 50ms, then
   flushes each table with one multi-row `INSERT … ON CONFLICT DO
   NOTHING`, all inside a single transaction per flush.

`ON CONFLICT DO NOTHING` because reconnect and resync legitimately
replay sequence numbers already stored. Idempotency by primary key, not
by hoping duplicates never arrive.

**Backpressure.** `try_send` first; when full, fire one `FeedStale`
alert per episode, then `send().await`. The ingestion task stalls; it
never drops. A stall eventually surfaces as a genuinely recorded gap,
which is visible and honest. A silent drop from the store of record
would contradict L1's standing no-silent-interpolation rule.

**Flush failure** retries with backoff, holding the batch. See Error
handling for what happens when retries are exhausted.

**Exactly one writer task commits at a time.** This is load-bearing, not
incidental — the tail cursor's correctness depends on it (below).

### L5 state store — synchronous durability

`persist`, `log_decision` and `append_event` fire once per decision, not
once per book tick, and exist to survive a crash. Batching them would
trade away the single property they are for. Their trait methods become
`async` and commit before returning.

This is cheap to land now: nothing in `execution` calls them yet.
Current callers are `orchestrator::system` (`reconcile`, `load_all`) and
`interfaces::cli`, plus a `FakeStore` in cli's tests. The sync→async
change lands before the hot-path caller exists.

## Read path

### Traits become async; one documented deviation disappears

`MarketDataStore` and `StateStore` read methods become `async`.
`read_range` is a single `UNION ALL` across `book_snapshot`,
`book_update`, `book_gap`, `trade` and `candle` for one pair, `ORDER BY
ord_ts, ins_seq`, keyset-paged.

That deletes `collect_range`'s sort-after-collect, which L1's spec
flagged as a deviation from its preferred k-way merge over already-
sorted ranges. Postgres performs an ordered merge over indexed ranges —
the thing the spec asked for.

### Two types, not one type in two modes

- **Executor**: `MarketDataService` implements `MarketDataFeed` +
  `MarketDataStore`, owns the writer task and the live caches.
- **Visualiser**: `PgMarketDataReader` implements `MarketDataStore`
  **only**. `PgStateReader` likewise exposes reads only.

The reason is structural, not stylistic. `MarketDataFeed`'s live getters
(`order_book`, `candles`, `latest_trades`) are served from in-memory
caches filled by ingestion. In a process that does not ingest, those
caches are permanently empty, so a shared type would let the dashboard
call them and render silent nonsense. With no `MarketDataFeed` impl on
the reader, that call does not compile.

Both readers connect as a Postgres role granted `CONNECT` and `SELECT`
only, so passivity holds at the database as well as in the type system.

### No exchange connector

The visualiser crates depend on `exchange_adapter` (wire **types** only),
`market_data` and `state_store`. They do not depend on
`exchange_adapter_binance` or `exchange_adapter_mexc` — there is no code
path to a socket, and the container receives no exchange credentials or
URLs. A test asserts those two crates are absent from the visualiser
binary's dependency tree, so a later edit cannot quietly reintroduce one.

### Live view: server-side cursor polling

`visualizer_server` runs one poll task per pair holding an `ins_seq`
cursor, polling on `POLL_INTERVAL_MS` (default 500), and fans each
batch out to every connected browser over WebSocket. One database reader
per pair regardless of how many browser tabs are open.

Each poll task keeps a `BookTracker`, seeded from the latest
`book_snapshot` at or before its starting cursor and fed the polled
updates, and emits reconstructed full depth — no consumer reimplements
delta application. (**Correction, 2026-09-11:** `apply_deltas` still
lives in `market_data::book`, per `crates/market_data/src/book.rs:10` —
it never moved to `exchange_adapter`. The earlier claim here was copied
from a now-corrected note in `plans/03-L1-market-data.md`; see that
file's own correction for what actually happened in the
`book-crossed-safety-check` branch.) History mode serves REST endpoints
over `read_range` with the same fold. `book_gap` rows arrive as rows and
render as gaps.

### Tail cursor: `ins_seq`, never `ord_ts`

A tail cursor on `ord_ts` loses rows. `ord_ts` mixes clocks by
construction — a trade's exchange match time against a snapshot's local
`recv_ts` — so a row inserted later can carry an earlier `ord_ts` than
the reader's cursor, and the reader would skip it permanently.

`ord_ts` therefore orders display and replay; `ins_seq` is the tail
cursor. This is safe **only** because exactly one writer task commits one
transaction at a time: with concurrent writers, sequence values can
commit out of order and the same hole reopens. Any future change that
adds a second writer must revisit this.

### Freshness replaces `LiveModeFlag`

`LiveModeFlag` was an in-process `AtomicBool`, meaningless across a
process boundary. The dashboard instead derives state per pair from
`max(recv_ts)` lag: fresh below a threshold, "feed stale" above it,
"executor offline" when nothing has arrived for a longer one. Strictly
more informative than the flag, which was set once at boot and never
caught an executor that had crashed or wedged.

## Process topology

Three compose services, replacing today's single container plus shared
`/data` volume.

- **`postgres`** — named volume for `PGDATA`; not published to the host.
  An `initdb.d` script creates `executor` (owner: DDL + DML) and
  `dashboard` (`CONNECT` + `SELECT`), with `ALTER DEFAULT PRIVILEGES FOR
  ROLE executor GRANT SELECT ON TABLES TO dashboard` so migration-created
  tables need no manual grant. `pg_isready` healthcheck.
- **`executor`** — today's `release` stage minus the visualiser.
  `depends_on: postgres (healthy)`. Runs migrations, then the
  orchestrator.
- **`visualizer`** — new Dockerfile stage: `visualizer_server` binary
  plus the built static frontend. `depends_on: postgres (healthy)` and
  **not** the executor: a passive dashboard must stay up while the
  executor is down, which is exactly when it is worth looking at. Keeps
  the host-only bind `127.0.0.1:8090:8090` — it still has no auth of its
  own.

### Config

`MARKET_DATA_PATH` and `STATE_STORE_PATH` leave `orchestrator::config`'s
required set, replaced by `DATABASE_URL`.

The visualiser's own config is `DATABASE_URL` (dashboard role),
`VISUALIZER_BIND_ADDR`, `VISUALIZER_STATIC_DIR`, `POLL_INTERVAL_MS`,
`PAIRS`. No exchange variables at all: no `API_KEY`, no `WS_BASE_URL`.
The absence is the point — the dashboard container holds no credentials
to misuse.

### Boot ordering

The executor owns migrations. The visualiser, which will usually start
first, retries with backoff against a missing schema and serves an
"initializing" state rather than crash-looping.

### Cost

Both images rebuild on a shared-crate change, and Postgres now sits in
the path of every executor start — a database that will not come up is a
trading outage, where sled failing was impossible by locality. Accepted
as the price of two processes; the healthcheck and `depends_on` make it
loud at boot rather than subtle at runtime.

## Error handling

- **DB down at executor boot**: retry with backoff, then exit non-zero.
  No store of record, no trading.
- **DB lost mid-run**: the writer retries with backoff, the queue fills,
  ingestion stalls. `MarketDataService::write_failed()` latches to
  `true` after 30 continuous seconds of failed flushes (this part is
  implemented and tested —
  `a_batch_postgres_will_never_accept_raises_the_alarm_at_once_not_after_30s`,
  `crates/market_data/tests/write_path.rs`) and a `Critical` alert
  fires. **The shutdown policy originally specified here — trigger the
  existing `shutdown_tx` path on sustained write failure — was checked
  against `execution`'s real code (per the verification note this
  section used to carry) and found to rest on a false premise, so it was
  deliberately NOT implemented.** `write_failed()` stays exposed;
  nothing polls it or wires it to `shutdown_tx`.
  Verification outcome: on MEXC (both market kinds), there is no
  exchange-native stop order at all —
  `exchange_adapter_mexc/src/spot.rs:203-208` and
  `futures.rs:132-144` both reject `OrderKind::Stop` with
  `AdapterError::NotSupported`. An open position on a MEXC deployment is
  protected solely by `execution`'s in-process stop-loss watcher
  (`run_stop_loss_watcher`), which dies the instant the process exits.
  Shutting the executor down on a sustained write failure would kill
  that watcher and leave the position with **no protection whatsoever**
  — strictly worse than the status quo of continuing to trade while
  unable to persist state, which at least keeps the watcher alive.
  Binance does implement native stops
  (`exchange_adapter_binance/src/parsing.rs:322-326`), so the original
  policy would have been safe there alone — but a policy that is only
  safe for one of the two exchanges this binary can be configured
  against cannot be implemented as a blanket behavior. See
  `task-7-report.md` in the plan's working directory for the full
  finding. This also means the Testing section's "write-failure
  shutdown" test below, as originally worded, was never added — adding
  it would require implementing the policy this finding blocks.
  **This is a narrower instance of a wider, pre-existing gap**: L1's
  spec documents a general feed-staleness fallback to "exchange-native
  stop only" that degrades to no protection at all on MEXC for the same
  reason — see [L1-market-data.md](layers/L1-market-data.md)'s Error
  handling section, which also notes it predates this migration and
  needs its own task.
- **Visualiser DB error**: per-panel error banner, keep serving what is
  already loaded, retry. The `catch_unwind` wrappers in
  `visualizer_backend` are removed: sqlx returns `Result`, so degradation
  becomes a typed error rather than a panic caught across an abstraction
  boundary.
- **Flush atomicity**: one transaction per flush, so a reader never sees
  half a batch.
- **Gap handling is unchanged and stays on the executor**: detection,
  the `market_data_gap_detected` metric, and the `FeedStale` alert. The
  dashboard renders `book_gap` rows and fires nothing. Passive means
  passive.

### Latency budget

Flush interval (≤50ms) + poll interval (~500ms) + WebSocket hop: roughly
0.5–0.6s behind the exchange under normal conditions, against
sub-millisecond for the superseded in-process design. This is the price
of the process split. Postgres `LISTEN`/`NOTIFY` is the documented seam
if that proves too slow to watch a wall form; it is not built now,
because it adds per-insert work to the write path for a latency
complaint nobody has made yet.

## Testing

### Infrastructure

The compose `test` service gains a `postgres` dependency. A new
`test_support` dev-dependency crate exposes `test_db()`: create schema
`t_<uuid>`, set `search_path`, run migrations, drop on teardown. Schema
isolation keeps tests parallel. It replaces the sled-tempdir helpers in
`market_data`, `state_store`, `replay_harness`, `local_analysis` and
`visualizer_backend`.

### Load-bearing tests

- **Round-trip fidelity per stream kind** — ingest, read back identical.
  L1 Stage 1's "byte-for-byte, not just some data comes back", now
  against real `numeric` columns.
- **`ins_seq` cursor regression** — advance the cursor, insert a row with
  an `ord_ts` *below* it, assert the poller still delivers it. Without
  this test the Tail cursor section is a comment.
- **Account-stream ordering** — interleave order/balance/position writes;
  assert the `UNION ALL` read returns exact write order, nothing lost.
  Serves L3 Stage 3.
- **Idempotent replay** — insert the same `(pair, seq)` twice; assert one
  row.
- **Backpressure, not drops** — fill the writer channel; assert the
  ingest task stalls and alerts, and that every event lands once the
  drain resumes.
- **Write-failure alarm** — kill the DB mid-run (or force a
  non-retryable error); assert retries, then `write_failed()` latches
  and a `Critical`/`FeedStale` alert fires within the grace period.
  Implemented as
  `a_batch_postgres_will_never_accept_raises_the_alarm_at_once_not_after_30s`.
  **Not implemented, and not to be added as currently scoped:** a
  "then shutdown trigger" assertion — see Error handling above for why
  the shutdown policy itself was deliberately not built.
- **Passivity, enforced twice** — the `dashboard` role gets `permission
  denied` on `INSERT`; a dependency-tree test asserts
  `exchange_adapter_binance`/`_mexc` are absent from the visualiser
  binary.
- **Gap in position** — an induced gap produces a `book_gap` row that
  `read_range` yields between the correct neighbours.

All run under `docker compose run --rm test`, per this project's
Docker-verified convention. The suite now requires a running Postgres —
`cargo test` on the host alone is no longer sufficient.

## Layer-spec amendments this forces

- **L1** — storage design section replaced (Postgres tables, not sled
  trees / RocksDB column families); `ingest` async; read methods async;
  `GapMarker` moves to its own table; the k-way-merge deviation is
  closed; the single-writer constraint is added as a requirement.
- **L5** — same backend change; write methods async and synchronously
  durable.
- **L8** — the visualiser is a separate process reading committed rows
  only; `LiveModeFlag` removed, freshness added; no exchange dependency,
  asserted by test.

## `exchange_ts` provenance and its limits

`exchange_ts` is the exchange's own timestamp where one genuinely
exists; it is `NULL` when it doesn't, and the row-mapping layer
(`pg::rows`) never guesses — the caller decides provenance explicitly,
per-call. Two concrete gaps in what the caller can actually provide,
both pre-existing data-quality limits rather than migration bugs:

- **REST book snapshots never carry a real exchange timestamp.** Both
  adapters build `OrderBookSnapshot` with a local `Ts(now_ms())`
  stand-in — there is no exchange-provided timestamp on that REST
  response to use instead. `exchange_ts` is correctly `NULL` for every
  snapshot row; `ord_ts` falls back to `recv_ts`, a local-clock value.
- **MEXC's post-resync buffered-replay path also substitutes
  `now_ms()` for book updates**
  (`exchange_adapter_mexc/src/ws.rs:460`, `to_update`): no per-buffered
  event `sendTime` is kept across a resync, so replayed updates get a
  local timestamp with no way for `market_data` to tell the difference
  from a genuine one. `exchange_ts` is populated for these rows, but is
  sometimes a local clock rather than an exchange clock, silently.
- **Candle `exchange_ts` is `open_time`, not `close_time`, and cannot
  be anything finer.** L0's `CandleUpdate` carries only `open_time` and
  `close_time`; event-time at the granularity of "when this candle's
  data actually changed" is discarded before it reaches L1.
  `close_time` on a still-forming candle is in the **future**, so using
  it would invert replay causality (a candle pushed now would sort
  after trades that haven't happened yet); `open_time` is what the
  pre-existing embedded-store implementation ordered candles by, kept
  for continuity across this migration.

Both of the first two need an L0 wire-type change to fix properly (a
field distinguishing "exchange said this" from "we substituted a local
clock because there was nothing else") — out of scope for this plan.

## Verification status — what is and is not proven end-to-end

The full workspace test suite passes (408 tests, 45 suites, Docker-run,
as of Task 10's re-verification) and Task 10 drove three of the four
Docker entry points by hand: the test suite itself, `--migrate-only`,
and the dashboard serving `{"ready":true,...}`/`"Offline"` correctly
while the executor container is stopped.

**The fourth entry point — a real row travelling exchange → writer →
rendered dashboard — is unverified.** Nothing has ever driven that path
end-to-end. Task 10 brought the executor container up against the real
MEXC production REST endpoint with placeholder credentials; MEXC's own
API rejected the account-info call with `[10072] "Api key info
invalid"` and the process exited before writing a single market-data
row, so the dashboard's freshness for that pair correctly stayed
`"Offline"` — it was never exercised into `"Fresh"`. A green test suite
must not be read as end-to-end coverage of this path; it is not.

Verifying it needs either real exchange credentials or a testnet.
Compose's exchange base URLs are now overridable (`REST_BASE_URL`,
`WS_BASE_URL`, and the `FUTURES_*` equivalents, all
`${VAR:-<production default>}`), and this repo already has
`exchange_adapter_binance/tests/testnet_integration.rs`, driven by
`BINANCE_TESTNET_API_KEY` — so `EXCHANGE=binance` against Binance's
testnet, with real testnet credentials, is a viable route to actually
observing the Offline→Fresh transition without a funded MEXC account.
That route is open but has not been driven by anyone as of this
writing.

## Open follow-ups (deliberately not done by this plan)

Work this plan identified but did not do, in no particular priority
order:

- **An execution-layer degraded mode**, instead of either extreme the
  write-failure policy above is stuck between: halt new entries while
  keeping existing stop-loss watchers alive, rather than either
  shutting down (which on MEXC kills the only protection open
  positions have) or trading on unboundedly while unable to persist
  state.
- **`reconcile`'s per-pair corrections are not atomic.** Each pair's
  correction is its own write; a crash mid-pass leaves some pairs
  corrected and others not — unchanged from the old sled
  implementation's own lack of atomicity here, not a regression, but
  not fixed either. Wrapping the whole pass in one transaction closes
  it.
- **`/ws` has no server-side keepalive ping.** Task 10's fix
  (`forward_to_socket` now also selects on `socket.recv()`) closes the
  gap for a peer that sends a TCP-level close or disappears in a way
  the OS notices. It does not cover a genuinely half-open peer — one
  whose TCP connection is still technically live but who will never
  send or acknowledge anything (a dead NAT mapping, a network
  partition with no RST) — which still pins a task, a broadcast
  receiver and a file descriptor indefinitely on an idle pair. A
  periodic ping/pong with a timeout is the standard fix; not built.
- **`book_gap`'s primary key, `(pair, expected_seq)`, collapses a
  second genuinely distinct gap at the same `expected_seq`** if a
  resync resets the sequence counter and a later gap happens to land on
  a previously-used `expected_seq` for that pair. Rare, but the schema
  as written cannot distinguish the two gaps if it happens.
- **Account-event inserts are not idempotent.** `order_event`/
  `balance_event`/`position_event` draw their primary key from a
  sequence default (`seq bigint PRIMARY KEY DEFAULT
  nextval('global_ins_seq')`), not from any exchange-provided identity.
  A replayed account snapshot or a retried ingest of the same logical
  event produces a new row with a new `seq`, not an `ON CONFLICT DO
  NOTHING` no-op the way the five market-data tables' natural-key PKs
  do.
- **The three account tables have no `ord_ts` index.** Unlike every
  market-data table (`book_snapshot`, `book_update`, `book_gap`,
  `trade`, `candle`), which each get a `(pair, ord_ts, ins_seq)` index,
  `order_event`/`balance_event`/`position_event` carry only their PK on
  `seq`. A range query by time against these tables is currently a
  sequential scan.
- **Postgres `max_connections` headroom** is unchecked against the
  connection count one executor process now actually opens: an L1
  reader pool (`cfg.max_conns`), a one-connection L1 writer pool, and
  an L5 pool. Fine at one executor instance; worth checking before
  assuming it scales to more.

## Out of scope

Retention/eviction, `LISTEN`/`NOTIFY` push, dashboard authentication
(still host-bound only), and migrating any existing sled data — there is
no production data to carry over, so the cutover is clean.
