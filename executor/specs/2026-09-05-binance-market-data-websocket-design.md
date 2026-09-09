# Binance market-data WebSocket support — design

## Problem

`exchange_adapter_binance`'s `subscribe_market_data` never emits
`MarketDataEvent::BookSnapshot`, `BookUpdate`, or `Trade` — only `Candle`,
via REST kline polling. Real order-book/trade data is a documented gap
(`NOTES.md` §1). `ws_base_url`/`futures_ws_base_url` already exist in
`BinanceAdapterConfig` but are dead — nothing dials them.

This spec covers closing that gap for Binance only. MEXC gets the same
treatment as a second, smaller follow-up once this implementation is
validated — its wire format differs enough (different stream naming,
protobuf on at least one channel — see "Portability to MEXC" below) that
porting the pattern is safer than designing both at once.

## Out of scope

- Account-update push (`AccountEvent` via `listenKey` user-data-stream).
  `subscribe_account_updates` keeps its current REST poll-and-diff
  behavior. Different auth/keepalive machinery, separate project.
- `Candle` stays on REST kline polling — Binance does have a `@kline_*`
  ws stream, but nothing here requires moving off the working poll path.
- MEXC (see above — follow-up project).

## Architecture

New module `exchange_adapter_binance/src/ws.rs`: connection management,
Binance's snapshot-sync procedure, and reconnect/backoff. One book+trade
ws connection per host (spot and margin share one — margin trades the
same pairs on the same host, per `kind.rs`'s existing comment; futures
gets its own via `futures_ws_base_url`).

`BinanceMarketAccount::subscribe_market_data(pair)` merges three
independent sources into the one `MarketDataStream` it already returns:

- book-diff ws task (new)
- trade ws task (new)
- REST candle-poll task (existing, unchanged)

Each task manages its own reconnect independently — a trade-stream drop
doesn't interrupt book updates or candles, and vice versa.

**Actual connection topology (reconciled with the implementation).** The
"one book+trade ws connection per host" wording above describes an
ambition the built code deliberately does not meet: `subscribe_market_data`
opens **two** ws connections **per pair, per call** — one `@depth`, one
`@trade` — because the independent-reconnect property in the paragraph
above is what actually buys the resilience this design wanted, and sharing
one socket across streams would couple their failure modes back together.
Spot and margin still share the same `ws_base_url` host, and futures still
uses `futures_ws_base_url`, but connection *count* scales as
`2 × pairs subscribed`, not as a constant per host. Worth knowing before
subscribing many pairs from one process: Binance enforces per-IP websocket
connection limits (and a connection-attempt rate limit) on the same IP this
adapter also places orders from. If pair counts grow, the fix is Binance's
combined-stream endpoint (`/stream?streams=a@depth/b@depth/...`), which
would multiplex many symbols onto one socket at the cost of reintroducing
shared-failure coupling — not attempted here.

New dependency: `tokio-tungstenite`, rustls-tls feature (matching
`reqwest`'s existing rustls choice — no reason to also pull in
OpenSSL). First ws consumer in this workspace.

## Binance's snapshot-sync procedure (book stream)

Per Binance's documented diff-depth-stream procedure:

1. Open the `@depth` ws stream for the symbol, buffer incoming diff
   events without applying them yet.
2. Fetch a REST snapshot (`/api/v3/depth` spot/margin, `/fapi/v1/depth`
   futures) → gives `lastUpdateId`.
3. Drop any buffered event where `u <= lastUpdateId`.
4. Find the first buffered event where `U <= lastUpdateId+1 <= u` — the
   sync point.
5. From there, each next event must satisfy `event.U == prev.u + 1`
   (spot/margin) or `event.pu == prev.u` (futures); if not, the stream has
   desynced — go back to step 1 (refetch snapshot, resync).

Note that step 4's looser range check applies to the first event after
*any* snapshot, whether it came out of the buffer or arrived live
afterwards — the implementation reads the socket only after its REST fetch
returns, so in practice the buffer is empty and the bridge is found live.
Applying step 5's strict rule to that first event instead would desync on
nearly every sync, since a snapshot taken at an arbitrary instant lands
inside some event's `U..u` window rather than on a boundary.

This is exchange-specific wire behavior with no equivalent in L0's wire
types — `OrderBookUpdate.sequence` is a single `u64`, not a `U..u` range.
The whole procedure stays internal to the adapter.

### Sequence numbering

L1's `BookTracker` (`market_data/src/book.rs`) expects
`update.sequence == prev_sequence + 1` on every update — anything else is
flagged as a `GapMarker` and fires a `FeedStale` alert (`store.rs`). But
Binance gaps/resyncs are routine protocol behavior, not something-is-wrong
signals. Passing Binance's raw update id through would mean L1 reports a
gap on nearly every message.

Instead, the adapter synthesizes its own contiguous sequence:

- On every successful sync (initial, or after a resync triggered by
  desync or reconnect): emit a fresh `BookSnapshot` (`sequence = 0`,
  `ts` = snapshot fetch time), reset the update counter to `1` — matching
  `BookTracker::seed`'s `expected_sequence = snapshot.sequence + 1`.
- Each subsequent verified-contiguous Binance event becomes one
  `BookUpdate` with `sequence = counter`, then `counter += 1` (so updates
  are numbered 1, 2, 3, ... after each snapshot).

A real `Gap` reaching L1 from the live ws path would now mean something
is actually wrong (adapter bug, dropped internal channel) — never routine
Binance-side behavior. This matches `GapMarker`'s existing doc comment:
"`subscribe_market_data` (the live path from an adapter) never produces
this variant — only L1's stored/replayed stream does."

## Reconnect policy

On any ws disconnect (network blip, exchange-side close, ping/pong
timeout): reconnect with exponential backoff, 1s → 2s → 4s ... capped at
30s, reset to 1s after a stretch of stable connection. A fresh connection
is treated exactly like a resync — refetch REST snapshot, emit new
`BookSnapshot`, reset counter.

Same alerting/metrics hooks the REST-poll path already uses
(`observability::Alerts`/`Metrics`): an error-count metric
(`binance_ws_reconnect_error_count`, tagged `stream=book|trade`) per failed
attempt, plus an alert once failures accumulate. Keeps this consistent with
the polling fallback that still exists for MEXC and for account updates.

**Which alert kind fires for which failure (reconciled with the
implementation).** An earlier draft of this section said `FeedStale` fires
after N consecutive failed reconnects. The built code splits the two
failure modes, which really are different, and this spec now follows the
code:

- `AlertKind::FeedDisconnected` — the *transport* is failing: 5+
  consecutive reconnect cycles that either failed to connect or dropped
  before proving stable (`STABLE_CONNECTION_THRESHOLD`, 60s). Fired by both
  `book_stream` and `trade_stream`.
- `AlertKind::FeedStale` — the *REST depth snapshot fetch* failed (raised
  from inside `BinanceRestClient` for that request), i.e. the ws side may be
  fine but the book can't be seeded/resynced.

- `AlertKind::BookCrossed` — an applied update left the adapter's own
  ladder with its highest bid strictly above its lowest ask (`bid == ask`,
  a locked book, is not an error). Fired at `Severity::Error` with the
  pair and the crossed prices, alongside a `book_crossed_detected` metric.
  The offending update is withheld from L1 and the stream recovers exactly
  as it does from a desync: reconnect, refetch the REST snapshot, replay
  the buffered events on top, emit the fresh `BookSnapshot`. Rate-limited
  by the same `DESYNC_RETRY_DELAY` floor. See L0's spec, "Crossed-book
  safety check", for why detection lives in the adapter rather than in
  L1's `BookTracker`.

A book-stream desync deliberately fires **neither**: it is routine Binance
protocol behavior, resolved in-band by refetching the snapshot, and never
counts toward `consecutive_failures`. It is rate-limited by its own fixed
floor (`DESYNC_RETRY_DELAY`, 500ms) rather than by the reconnect backoff,
so a pathologically desyncing stream cannot hot-loop TLS handshakes and
weight-50 REST depth calls.

Both read loops additionally treat `WS_IDLE_TIMEOUT` (5 minutes) of total
silence as a dead connection and reconnect through the normal failure
path — a half-open socket blackholed by a middlebox never returns an error
or a close frame, so without this it would stall the feed silently and
forever. Binance's ~3-minute server pings are what keep a healthy idle
market well inside that window.

Binance's ws-level ping/pong (server pings every ~3 min, client must pong
within 10 min or gets disconnected) is handled automatically by
`tokio-tungstenite` at the protocol level — no application code needed.

## Trade stream

Separate ws subscription, `@trade` (spot/margin and futures both have a
plain `@trade` stream). No sequence/continuity contract in L0 —
`TradeTick` only carries `trade_id`, and L1's store keys trades by
`trade_id` with no gap logic. Trades pass straight through: one
`MarketDataEvent::Trade` per ws message, Binance's `t` field becomes
`TradeId`. Same reconnect/backoff as the book stream, but nothing to
resync — just resubscribe and resume.

## Testing

No ws-mocking crate exists in this workspace (`wiremock` only covers
HTTP). New test-only helper: a hand-rolled fake ws server
(`tokio_tungstenite::accept_async` over a `TcpListener` bound to
`127.0.0.1:0`), fed a scripted sequence of JSON frames. `ws_base_url` /
`futures_ws_base_url` — currently-dead config fields — finally get
pointed at this fake server in tests, the same way `wiremock` already
stands in for the REST side.

Scenarios:

- Happy path: snapshot (existing `wiremock` REST mock) + contiguous ws
  diff events → `BookSnapshot` then `BookUpdate`s with counter 0,1,2...
- Desync (a scripted `U` that doesn't chain off the previous `u`) →
  adapter refetches snapshot, re-emits a fresh `BookSnapshot`, counter
  resets to 0.
- Ws disconnect mid-stream → reconnect, same resync path.
- Trade messages pass straight through, no continuity logic exercised.

## Portability to MEXC (informs the follow-up, not this project)

Checked this design against MEXC's actual ws API to make sure the
architecture isn't accidentally Binance-specific:

- **Spot** diff depth carries `fromVersion`/`toVersion` — same shape as
  Binance's `U`/`u`; "`fromVersion` must equal prev `toVersion`+1, else
  reinit" is exactly Binance's resync trigger. The synthetic-contiguous-
  sequence design (this spec's "Sequence numbering" section) applies
  unchanged.
- **Futures** carries a single `version` field (long) rather than a
  range — likely just `version == prev + 1`, a simpler case of the same
  resync pattern.
- Level quantities are absolute-per-level, `0` = remove — identical to
  what L1's `apply_deltas` already assumes for Binance. No adapter-side
  conversion needed.
- Margin reuses spot's ws, matching the MEXC crate's existing NOTES.md
  ("margin reuses spot's base URL and spot-style signing").
- Module layout, the 3-stream fan-in per pair, backoff-reconnect-as-
  resync, and the fake-local-ws-server test harness are all
  exchange-agnostic and should port as-is.

**One real gotcha for the follow-up**: MEXC's current spot depth channel
(`spot@public.aggre.depth.v3.api.pb@...`) is protobuf-encoded, not plain
JSON like Binance's ws — the MEXC implementation will need a decode step
(new dependency, e.g. `prost`) that this Binance work doesn't. MEXC
futures depth appears to be JSON (its REST API is JSON throughout) but
wasn't confirmed against live docs — verify when that phase starts
rather than assuming.

## Files touched

- `exchange_adapter_binance/src/ws.rs` (new) — connection management,
  sync procedure, reconnect/backoff
- `exchange_adapter_binance/src/market.rs` — `subscribe_market_data`
  merges the ws stream with the existing candle poll
- `exchange_adapter_binance/Cargo.toml` — add `tokio-tungstenite`
- `exchange_adapter_binance/tests/` — new fake-ws-server test helper +
  additions to `wiremock_tests.rs`
- `exchange_adapter_binance/NOTES.md` — update §1 (book/update/trade are
  no longer an unbuilt gap; note MEXC as the remaining follow-up)
