# L1 — market_data

Part of [architecture index](../2026-09-04-architecture-design.md).

## Purpose

Live order book + candles per pair, local persistence of both, and
**replaying** that history back through the same feed interface —
`market_data` owns the replay mechanism itself, not just the storage
`replay_harness` (L6) happens to read from.

## Responsibilities

- Ingest `exchange_adapter`'s shared wire types (defined in L0, not
  reinvented here): `OrderBookSnapshot`/`OrderBookUpdate` and
  `TradeTick` (both riding `MarketDataEvent`), plus `AccountEvent`
  (own order/fill/balance/position updates) — this crate is the single
  ingestion point for everything the adapter streams, public and
  client-specific alike.
- Maintain live order book per pair by applying `OrderBookUpdate` on
  top of the last `OrderBookSnapshot`.
- Retrieve candlesticks from the exchange; keep the latest public
  trade tape per pair.
- Persist captured order-book updates, trades, candles, **and**
  `AccountEvent`s locally, scoped to replaying local-signal conditions
  and the executor's own historical fills (separate from main/'s full
  backtesting system).
- Flag gaps in any of these streams explicitly in the persisted store
  — never silently interpolate; a replay must see real gaps too.
- Own replay: turn a stored time range back into something that looks
  exactly like a live `MarketDataFeed` to whatever consumes it — an
  analysis task (`local_analysis` under `replay_harness`'s gate, or any
  future analysis/backtest task) writes one code path and runs it
  against either live or historical data unmodified. `replay_harness`
  and any future replay-driven task are *consumers* of this
  capability, not separate owners of replay mechanics.

## Depends on

`exchange_adapter::MarketAccount::{subscribe_market_data,
subscribe_account_updates}` (per market-kind sub-model, per L0).

## Storage design

**Superseded 2026-09-11** — the backend below is what is actually
built, per
[postgres-market-data-store-design.md](../2026-09-09-postgres-market-data-store-design.md).
The embedded-KV design this section originally described (sled or
RocksDB, one column family per stream kind) was replaced wholesale,
not incrementally; nothing from the old design survives except the
per-stream-kind separation principle itself.

`market_data` is the only layer that persists historical order-book,
trade, candle, and account-event data — and the only layer that
touches the store directly. Everything else (`replay_harness`,
`interfaces::visualizer_backend`/`visualizer_server`, `execution`,
`state_store`) reads through `MarketDataFeed`/`MarketDataStore` only;
nothing else opens the database directly.

Backend: **PostgreSQL**, one table per stream kind — not sled trees,
not RocksDB column families. Each table still has its own key scheme
and its own index, so a `read_range` scan never has to filter out
unrelated kinds; that property survives the backend change unchanged,
it is just expressed as tables instead of column families:

| Table | Key | Payload | Notes |
|---|---|---|---|
| `book_snapshot` | `(pair, seq)` | four `numeric[]` arrays (bid/ask price+qty) | periodic checkpoint, not every update — bounds replay-from-scratch cost |
| `book_update` | `(pair, seq)` | same four arrays, as deltas | `seq` monotonic per pair |
| `book_gap` | `(pair, expected_seq)` | `observed_seq` (nullable) | its own table now — see below |
| `trade` | `(pair, trade_id)` | price/qty/side | exchange-assigned id, already unique+ordered |
| `candle` | `(pair, interval, open_time)` | OHLCV, `close_time`, `is_closed` | |
| `order_event` | `(seq)` | order_id/pair/side/status/filled_qty/avg_fill_price | |
| `balance_event` | `(seq)` | asset/free/locked | |
| `position_event` | `(seq)` | pair/side/size/entry_price/leverage/liquidation_price | |

`order_event`/`balance_event`/`position_event` replace the single
`account_event` CF the original design used: still one ordered
`AccountEvent` stream conceptually, but three tables because the
variants share no columns. `seq` on all three (and `ins_seq` on the
five market-data tables above) is drawn from one shared Postgres
sequence, so `read_account_events`'s `UNION ALL … ORDER BY seq`
reconstructs the single global order without a second merge step.

**`GapMarker` moved to its own table (`book_gap`), out of
`book_update`.** Storing it inline in `book_update` was a sled
key-space device: writing the marker under the same key scheme made it
surface in position during a single-tree scan, for free. SQL does not
need that trick — `read_range` is a `UNION ALL … ORDER BY ord_ts,
ins_seq` across all five market-data tables, so `book_gap` rows merge
back into position on their own, and `book_update` no longer has to
hold two different value shapes under one key scheme.

**The k-way-merge deviation flagged below is now CLOSED.** The
embedded-store implementation's `read_range` did a sort-after-collect
instead of the k-way merge over already-sorted per-CF ranges this spec
originally asked for — a documented simplification (`store.rs`).
Postgres's query planner performs exactly that ordered merge over
indexed ranges itself; there is no longer a gap between what this spec
asks for and what the implementation does.

**`ingest` and every `MarketDataStore` read method are `async`.**
`MarketDataFeed`'s getters (`order_book`, `candles`, `latest_trades`,
`subscribe_updates`, `subscribe_account_events`) stay synchronous —
they are served from in-memory caches kept current by `ingest`, not
from the database on the hot path. But `ingest` itself, and the whole
of `MarketDataStore` (`read_range`, `read_account_events`, `replay`,
plus `tail` and `latest_recv_ts`, added for the dashboard's tail-read
and freshness needs — see L8), are `async fn`: each one is a Postgres
query.

**Stated requirements** (not just implementation detail — both are
load-bearing for the cursor rule that follows):

- **Exactly one writer task commits at a time.** The writer's
  connection pool is `max_connections(1)`, structurally, not by
  convention — a second concurrent writer transaction must be
  impossible by construction, because the tail-cursor rule below
  depends on commit order matching insertion-sequence order.
- **`ins_seq` is the only legal tail cursor; `ord_ts` orders display
  and replay, and must never be used to tail.** `ord_ts` is
  `COALESCE(exchange_ts, recv_ts)` — it mixes exchange and local
  clocks by construction, so a row committed later can carry an
  *earlier* `ord_ts` than one already returned; a cursor held on
  `ord_ts` would skip that row permanently. `ins_seq` is assigned by
  one global sequence at insert time, and is guaranteed to match commit
  order only because of the single-writer requirement directly above —
  the two rules are one mechanism, not two independent ones.

`order_book(pair)` (live read) is unaffected by the backend change —
still served from the in-memory structure kept current by applying
`book_update` as it arrives, seeded from the latest `book_snapshot`;
it does not hit the database on the hot path. `read_range`
(replay/historical) is now a `UNION ALL … ORDER BY ord_ts, ins_seq`
query rather than a compound iterator over CF ranges — same contract,
different mechanism.

Retention/eviction (how far back the store keeps data) is still out
of scope — unchanged from the original spec; `book_update` is the
table that will want partitioning first if that ever becomes a
requirement.

## Storage responsibility (answers the recurring question directly)

**market_data (L1) is the layer responsible for historical storage of
both order-book updates and account/"client" events.** L0
(`exchange_adapter`) only streams; it holds nothing on disk. Every
other layer above L1 reads historical data exclusively through
`MarketDataStore`, never by touching L1's store files.

## Interface exposed upward

**Superseded 2026-09-11** — signatures below are async now (per
`postgres-market-data-store-design.md`'s Read path), and `replay`/
`read_range`/`read_account_events` return `Result<_, StoreError>` since
every one of them is now a fallible database call. The synchronous
version below is kept struck through rather than deleted, since the
shape (what each method does) is unchanged — only syncness and
fallibility are new.

```
trait MarketDataFeed {
    fn order_book(&self, pair: Pair) -> OrderBookSnapshot;
    fn candles(&self, pair: Pair, tf: Timeframe) -> CandleSeries;
    fn latest_trades(&self, pair: Pair) -> TradeSeries;
    fn subscribe_updates(&self, pair: Pair) -> Stream<MarketDataEvent>;
    fn subscribe_account_events(&self) -> Stream<AccountEvent>;
}
// Unchanged, still synchronous: every getter above is served from an
// in-memory cache, never the database, on execution's hot path.

#[async_trait]
trait MarketDataStore {
    async fn read_range(&self, pair: Pair, from: Ts, to: Ts)
        -> Result<Stream<MarketDataEvent>, StoreError>;   // includes gap markers
    async fn read_account_events(&self, from: Ts, to: Ts)
        -> Result<Stream<AccountEvent>, StoreError>;
    async fn replay(&self, pair: Pair, from: Ts, to: Ts, speed: ReplaySpeed)
        -> Result<Box<dyn MarketDataFeed>, StoreError>;
        // wraps read_range as a MarketDataFeed: order_book()/candles()/
        // latest_trades()/subscribe_updates() behave exactly as they
        // would live, just driven from stored history instead of the
        // exchange. ReplaySpeed::AsFast (no pacing, for CI) or
        // ::Realtime (paced to original timestamps, for manual review).
    async fn tail(&self, pair: Pair, after: InsSeq, limit: i64)
        -> Result<Vec<(InsSeq, MarketDataEvent)>, StoreError>;
        // added for the dashboard's live poll: everything after an
        // ins_seq cursor, oldest first. InsSeq, never Ts -- see the
        // cursor rule in Storage design above.
    async fn latest_recv_ts(&self, pair: Pair) -> Result<Option<Ts>, StoreError>;
        // added for the dashboard's freshness signal -- see L8.
}
```

**Two implementations, not one type in two modes.** The executor's
`MarketDataService` implements both `MarketDataFeed` and
`MarketDataStore` — it ingests, so its live caches are real.
`PgMarketDataReader` (used by the separate visualiser process, see L8)
implements `MarketDataStore` **only**, deliberately with no
`MarketDataFeed` impl: a process that never ingests has permanently
empty live caches, so giving it `MarketDataFeed` would let a caller
call `order_book()`/`candles()`/etc. and render silent nonsense instead
of a compile error.

Consumers: `local_analysis` (MarketDataFeed's book/trade/candle side —
live *or* the `replay()`-returned feed, identical trait either way),
`execution` and `state_store` (subscribe_account_events, so
fills/status/balance changes reach them through the same ingestion
pipeline rather than each re-subscribing to `exchange_adapter`
directly), `replay_harness` (calls `MarketDataStore::replay` to get a
feed, then wires it to `local_analysis` under test — L6 no longer
implements replay mechanics itself, just orchestrates the gate),
`interfaces::visualizer_backend`/`visualizer_server` (MarketDataStore
only, via `PgMarketDataReader` — read-only, committed rows, no live
in-process feed; see L8 for why).

## Error handling

Feed marked stale after grace period on adapter disconnect →
propagated to `execution` (fall back to exchange-native stop only) and
to `observability` as an alert-class event, not just a log line.

**Open safety issue (pre-existing, not introduced by this migration —
needs its own task).** The fallback above assumes every exchange the
executor can be configured against actually has an exchange-native
stop order available to fall back to. That is false for MEXC: neither
MEXC market kind the executor can trade supports exchange-native stop
orders — `exchange_adapter_mexc/src/spot.rs:203-208` and
`futures.rs:132-144` both reject `OrderKind::Stop` with
`AdapterError::NotSupported` ("not confident enough in MEXC's
stop-order param shape to guess at it"). Only
`exchange_adapter_binance` actually implements it
(`exchange_adapter_binance/src/parsing.rs:322-326`). So on a
MEXC-configured deployment, "fall back to exchange-native stop only"
degrades to **no protection at all**: the position is guarded solely
by `execution`'s in-process stop-loss watcher, which a feed-stale
condition does nothing to stop on its own but which dies outright the
moment the process does. This is a property of `execution` and the
MEXC adapter, not of storage, so it predates and is independent of the
Postgres migration — it is recorded here because this is where the
fallback claim is documented, and it affects L3's own copy of the same
claim in exactly the same way. Do not read the "not introduced by this
migration" framing as "therefore low priority" — on a live MEXC
deployment this is a live-trading safety gap today.

## Testing

Unit tests on book-update application logic (apply delta to snapshot,
detect out-of-order/gap). Replay recorded ws sessions through the same
apply logic to catch regressions.

## Acceptance criteria (staged)

Same staged-signoff pattern as L0: each stage gated on the layer it
glues to next, verified against what that layer actually built, not
the assumed interface.

**Stage 1 — glue to L0 (`exchange_adapter`)**
- [ ] Every `MarketDataEvent` L0 emits for a live pair (book snapshot,
      book update, trade, candle) is captured and written to the
      matching CF (`book_snapshot`/`book_update`/`trade`/`candle`, per
      Storage design above).
- [ ] Every `AccountEvent` L0 emits is captured and written to
      `account_event`.
- [ ] Everything written is retrievable: `read_range` and
      `read_account_events` return data matching what was ingested,
      byte-for-byte, for a recorded window — not just "some data
      comes back."
- [ ] A deliberately induced gap (drop a message in a test harness)
      produces a `GapMarker` in `book_update`, not a silent skip or a
      crash.
- [ ] `order_book(pair)` / `candles(pair, tf)` / `latest_trades(pair)`
      reflect the ingested data correctly (live path, not just the
      stored copy).

**Stage 2 — glue to L2 (`local_analysis`)** — gated: cannot start
until `local_analysis` exists.
- [ ] Every input `local_analysis` actually reads (order book state for
      wall detection, trade/volume data for simple-signal timing) is
      served correctly by `MarketDataFeed` — confirmed against
      `local_analysis`'s real implementation, not the trait shape
      alone; if it needs something `MarketDataFeed` doesn't expose,
      that's a gap to fix in L1's interface, not a workaround in L2.

**Stage 3 — glue to L3 (`execution`)** — gated: cannot start until
`execution` exists.
- [ ] Every `AccountEvent` reaches `execution` via
      `subscribe_account_events` with no loss or reordering versus
      what L0 sent (cross-check against L0's own stage-2 criteria).
- [ ] Feed-staleness propagation (Error handling above) actually
      triggers `execution`'s fall-back-to-exchange-native-stop path in
      an integration test, not just in the doc — **on Binance only**;
      on MEXC there is no native-stop path to trigger (see the open
      safety issue above), so this criterion cannot be satisfied for a
      MEXC-configured run and should not be marked done on the strength
      of a Binance-only test.

**Stage 4 — glue to L7 (`observability`)** — gated: cannot start until
`observability` exists.
- [ ] Feed staleness/disconnect and any `GapMarker` write generate a
      real alert-class event (not a plain log line) once `observability`
      exists to receive it.

**Stage 5 — glue to L6 (`replay_harness`)** — gated: cannot start
until `replay_harness` exists.
- [ ] `MarketDataStore::replay(...)`'s returned feed, driven into
      `local_analysis` by `replay_harness`, reproduces the exact
      sequence (including any `GapMarker`s) that was live-ingested for
      that window — replay must see what actually happened, not a
      cleaned-up version.
- [ ] `local_analysis` code run through `replay()` is *the same code
      path*, unmodified, as the one run live — confirmed by using one
      `local_analysis` build for both a live smoke-test and a
      `replay_harness` run over the same recorded window, comparing
      output.

**Standing rule** (applies beyond the stages listed above): whenever a
new layer is built, check that layer's own "Depends on" section — if
it names `market_data`, add a stage here validating that specific
consumption before considering L1 done with respect to it. This is how
`L5 (state_store)`'s account-event dependency and `L8
(visualizer_backend)`'s historical/live feed dependency get covered
once those layers exist, without having to guess their exact needs
now.
