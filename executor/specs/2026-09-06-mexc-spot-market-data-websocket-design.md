# MEXC spot/margin market-data WebSocket support — design

## Problem

`exchange_adapter_mexc`'s `subscribe_market_data` (spot/margin, via
`SpotStyleAccount`) never emits `MarketDataEvent::BookSnapshot`,
`BookUpdate`, or `Trade` — only `Candle`, via REST kline polling. This is
the documented gap in this crate's `NOTES.md` §1 and in
`external/executor/plans/02-L0-exchange-adapter.md`'s "Known gaps" list,
tracked as the follow-up once Binance's equivalent (already shipped —
`2026-09-05-binance-market-data-websocket-design.md`) validated.

This spec covers MEXC spot/margin only. MEXC futures ("contract") market
data is a separate, later project — its wire protocol (plain JSON, a
single `version` counter instead of a `fromVersion`/`toVersion` range,
client-initiated ping keepalive, base URL `wss://contract.mexc.com/edge`)
differs enough from both Binance's and MEXC spot's that designing it
alongside this one would mean guessing at two protocols instead of
nailing one.

## Out of scope

- MEXC futures market data (see above — follow-up project).
- Account-update push (`AccountEvent`, MEXC's `listenKey` user-data
  stream). `subscribe_account_updates` keeps its current REST
  poll-and-diff behavior — same exemption Binance's spec carried.
- Retrofitting Binance's `DepthSync` into a shared, generic L0
  abstraction. The sync algorithm is structurally identical between the
  two exchanges (see "Sync procedure" below), but Binance's
  implementation just stabilized through a real fix-wave — generalizing
  it now, from one shipped example, risks a premature abstraction shaped
  around one case. MEXC gets its own mirrored implementation; extracting
  a shared abstraction is a natural third project once both concrete
  cases exist to design against.
- `Candle` stays on REST kline polling (unchanged, same as Binance).

## Architecture

New module `exchange_adapter_mexc/src/ws.rs`. `SpotStyleAccount`
(already shared by spot and margin — see `spot.rs`, `SpotStyleKind`)
gains `ws_base_url: Url` (threaded from `AdapterConfig.ws_base_url`,
currently unused by this crate — same as Binance's `ws_base_url` was
before its own ws project). `subscribe_market_data` merges three
independent sources into the one `MarketDataStream` it already returns:

- book-diff ws task (new)
- trade ws task (new)
- REST candle-poll task (existing, unchanged — `polling::market_data_poll_stream`)

Book and trade get **separate** ws connections per pair, mirroring
Binance's shipped, reviewed pattern — even though MEXC's subscribe-frame
protocol (`{"method":"SUBSCRIPTION","params":[...]}` over one socket)
could technically multiplex both channels onto one connection (MEXC
allows up to 30 subscriptions per connection). Consistency with Binance's
already-validated "independent reconnect per stream" property wins over
exploiting a protocol quirk; Binance's final review specifically
confirmed decoupled connections are worth the extra socket.

New dependency: none beyond what Binance's project already proved
(`tokio-tungstenite`, already in the workspace). No `prost`/protobuf
codegen dependency — see "Protobuf decoding" below.

## Wire format

MEXC spot/margin market-data streams are **protobuf**, not JSON (this is
the one structural difference from Binance beyond field names). Schemas
come from MEXC's own `mexcdevelop/websocket-proto` repo (vendor the
`.proto` files into this crate's source tree as reference documentation,
even though nothing compiles them — see "Protobuf decoding"):

```protobuf
// PushDataV3ApiWrapper.proto (relevant excerpt)
message PushDataV3ApiWrapper {
  string channel = 1;
  oneof body {
    // ...
    PublicAggreDepthsV3Api publicAggreDepths = 313;
    PublicAggreDealsV3Api publicAggreDeals = 314;
    // ...
  }
  optional string symbol = 3;
  optional string symbolId = 4;
  optional int64 createTime = 5;
  optional int64 sendTime = 6;
}

// PublicAggreDepthsV3Api.proto
message PublicAggreDepthsV3Api {
  repeated PublicAggreDepthV3ApiItem asks = 1;
  repeated PublicAggreDepthV3ApiItem bids = 2;
  string eventType = 3;
  string fromVersion = 4;
  string toVersion = 5;
  int64 lastOrderCreateTime = 6;
}
message PublicAggreDepthV3ApiItem {
  string price = 1;
  string quantity = 2;
}

// PublicAggreDealsV3Api.proto
message PublicAggreDealsV3Api {
  repeated PublicAggreDealsV3ApiItem deals = 1;
  string eventType = 2;
}
message PublicAggreDealsV3ApiItem {
  string price = 1;
  string quantity = 2;
  int32 tradeType = 3;
  int64 time = 4;
  string tradeId = 5;
}
```

Channels: `spot@public.aggre.depth.v3.api.pb@(100ms|10ms)@<symbol>` and
`spot@public.aggre.deals.v3.api.pb@(100ms|10ms)@<symbol>` — default to
the `100ms` window for both (lower message rate; same reasoning as
Binance's default `@depth` cadence choice). `tradeType`: `1` = buy, `2` =
sell — this maps directly to `Side` (no inversion needed, unlike
Binance's `buyer_is_maker` proxy). `quantity == "0"` removes a price
level (same convention as Binance).

## Protobuf decoding

Hand-rolled minimal decoder, not a codegen dependency (`prost`+`protoc`,
or a pure-Rust generator) — confirmed with the user. Rationale: the
three messages above are small (scalar strings/int64/one level of
repeated nested messages, no maps, no enums beyond the `oneof`), and a
hand-written wire-format walker avoids any new build-time toolchain
dependency (`protoc` in particular is a real Docker-build-image risk this
project has hit before with unrelated tooling). The vendored `.proto`
files stay in the repo purely as documentation for whoever next touches
this decoder — they are not built or referenced by any build script.

Decoder scope, precisely: a generic-enough protobuf wire-format reader
(varint decode, length-delimited field framing, tag = `(field_number <<
3) | wire_type`) applied to exactly the three message shapes above. Two
things worth calling out as decoder edge cases to test explicitly:

- `oneof body`'s field numbers are large (301–315), meaning **multi-byte
  varint tags** — the decoder must not assume a single-byte tag the way
  a naive implementation tempted by Binance's small JSON field names
  might.
- `PushDataV3ApiWrapper`'s `symbol`/`sendTime`/etc. are proto3
  `optional` — decode only what's actually needed (the `channel` string,
  to route to the depth-vs-trade decoder, and the `sendTime` for `Ts` —
  see below); don't build out fields nothing consumes.

## Sync procedure (book stream)

Confirmed directly against MEXC's own docs (`spot_v3_en` branch,
"How to Properly Maintain a Local Copy of the Order Book") — structurally
identical to Binance's, just different field names:

1. Open the `spot@public.aggre.depth.v3.api.pb@100ms@<symbol>` ws
   stream, buffer incoming diff events without applying them yet.
2. Fetch a REST snapshot: `GET /api/v3/depth?symbol=<symbol>&limit=1000`
   → `lastUpdateId` (same shape, same field name, as Binance's spot
   snapshot — MEXC's spot v3 REST surface mirrors Binance's here).
3. Drop any buffered event where `toVersion <= lastUpdateId`.
4. Find the first buffered event where `fromVersion <= lastUpdateId+1 <=
   toVersion` — the sync point.
5. From there, each next event must satisfy `event.fromVersion ==
   prev.toVersion + 1`; if not, the stream has desynced — resync (refetch
   snapshot).

This is the *exact* shape of Binance's procedure — the same
buffer/stale-drop/bridge-find/strict-contiguity structure, MEXC's
`fromVersion`/`toVersion` playing the role of Binance's `U`/`u`. Build
MEXC's own `DepthSync`-equivalent mirroring Binance's post-fix design
(the `bridged: bool` state machine from Binance's final review — see that
project's ledger): `book_stream` must read the socket *while* the REST
snapshot fetch is in flight or, more simply, apply the same "handle the
loose range-check for the first event after any resync, strict equality
thereafter" logic as `on_event`'s `synced && !bridged` branch, learned
the hard way on Binance. This is the single most important carry-over
lesson from that project — repeating Binance's original bug (connect,
fetch snapshot without reading the socket, then apply the strict rule to
the first live event) would reproduce the exact same near-certain
false-desync failure mode on MEXC.

### Crossed-book safety check

`DepthSync` also maintains its own ladder (seeded from the resync
snapshot, advanced by each forwarded update) and checks after every
applied update that the highest bid does not sit strictly above the
lowest ask; `bid == ask` (a locked book) is legal and ignored. On a
cross the update is withheld from L1, an `AlertKind::BookCrossed` alert
fires at `Severity::Error` with the crossed prices plus a
`book_crossed_detected` metric, and the stream recovers through the
existing desync path (reconnect, refetch snapshot, replay buffer),
rate-limited by the same fixed desync floor. Structurally identical to
Binance's — see L0's spec, "Crossed-book safety check".

### Sequence numbering

Same synthesis as Binance: `BookSnapshot.sequence = 0`, first
`BookUpdate.sequence = 1`, incrementing from there — matches L1's
`BookTracker::seed` (`expected_sequence = snapshot.sequence + 1`), which
is exchange-agnostic (it's an L0→L1 contract, not something MEXC-specific
needs to relearn).

## Trade stream

`spot@public.aggre.deals.v3.api.pb@100ms@<symbol>`. No sequence
contract (same as Binance) — pass through directly. `tradeType` maps
straight to `Side` (`1` → `Buy`, `2` → `Sell`, no inversion — simpler
than Binance's `buyer_is_maker` proxy since MEXC gives the taker's side
directly). `tradeId` (present on the aggregated channel, absent on the
legacy plain `spot@public.deals.v3.api.pb`) becomes `TradeId` directly —
parse as `u64` (confirm at implementation time whether MEXC's `tradeId`
is numeric or an opaque string; if the latter, `TradeId`'s `u64` shape
needs a hashing/parsing fallback, called out here as an open
implementation question rather than assumed).

## Reconnect policy

Same as Binance: exponential backoff (`1s → 2s → 4s ... capped at 30s`,
reset only after a connection proves stable — the exact bug Binance's
final review found and fixed must not be reintroduced here), desync
exempt from the failure counter but rate-limited by its own fixed floor,
an idle/read timeout on both tasks (a blackholed connection must not
stall silently forever — Binance's final review added this after
initially missing it; build it in from the start here rather than
rediscovering the same gap).

MEXC's own ws-level requirements, confirmed from its docs: max 24-hour
connection validity (expect a server-initiated close at that mark —
treat like any other drop, reconnect normally), 30 subscriptions per
connection (irrelevant at 1 subscription per connection under this
spec's "separate connections" decision), disconnected after 30s with no
valid subscription or 60s with a subscription but no data.

**Client-initiated keepalive is required — this is the one place MEXC's
ws behavior genuinely differs from Binance's, not just in field names.**
MEXC's ping/pong (`{"method":"PING"}` request, `{"msg":"PONG"}` response)
is an **application-level JSON control message**, not the WebSocket
protocol-level ping/pong frame `tokio-tungstenite` answers automatically.
Binance never needed a client-side keepalive loop because its server
pings the client (handled transparently at the protocol level); MEXC
needs the adapter to actively send `{"method":"PING"}` as a text frame on
its own schedule, or a quiet subscription (a real possibility during low
market activity, even with a live, healthy connection) hits the 60s
no-data-flow disconnect for no real reason.

Both `book_stream` and `trade_stream` need a ping timer running
concurrently with the read loop on the same connection (`tokio::select!`
between "next ws frame" and "ping timer ticked") — send `{"method":
"PING"}` every ~20s, comfortably under the 60s/30s disconnect thresholds
regardless of actual data volume. The idle-timeout constant (the
Binance-style "no frame received in N seconds, treat as a drop" safety
net) still applies on top of this and should stay under 60s for MEXC
(unlike Binance's ~300s, chosen against Binance's ~180s *server* ping
cadence) — propose ~45s, which gives two missed ping-cycles of margin
before declaring the connection dead; confirmed at implementation time
against real behavior if credentials/sandbox access allows, otherwise
documented as a best-effort estimate, same caveat as everything else in
this crate's `NOTES.md`.

## Testing

Same fake-local-ws-server fixture pattern Binance already built
(`spawn_fake_ws_server`, hand-rolled `tokio_tungstenite::accept_async`
over a `TcpListener` bound to `127.0.0.1:0`) — reusable as-is, just
scripted with protobuf-encoded byte frames instead of JSON text frames
for MEXC's tests. `wiremock` continues to stand in for the REST snapshot
fetch, unchanged from Binance's approach.

Decoder unit tests: hand-encode protobuf byte fixtures matching the
message shapes above (tag/wire-type/varint-length framing built by hand,
annotated inline so a future reader can verify each byte group against
the schema without re-deriving the encoding). Scenarios to cover, mirror
of Binance's plus the two MEXC-specific decoder risks:

- Happy path: snapshot + contiguous ws diff events → `BookSnapshot` then
  `BookUpdate`s with counter 0,1,2...
- Desync (a `fromVersion` that doesn't chain off the previous
  `toVersion`) → resync, fresh `BookSnapshot`, counter resets.
- Ws disconnect mid-stream → reconnect, same resync path.
- Trade messages pass straight through, `tradeType`/`tradeId` mapped
  correctly.
- Decoder-specific: a multi-byte `oneof` field-number tag (313/314)
  decodes correctly; a message with only the fields this decoder actually
  reads present (proto3's implicit-default-on-absence semantics) doesn't
  panic or misparse.
- Keepalive: the ping timer actually fires and sends a `{"method":
  "PING"}` text frame on its own schedule, independent of whether any
  data frame ever arrives — provable with an injectable ping interval
  (same dependency-injection pattern as `Backoff`, so the test doesn't
  wait on a real ~20s timer) and a fake server that records every text
  frame it receives.

## Files touched

- `exchange_adapter_mexc/src/ws.rs` (new) — protobuf decoder, `DepthSync`
  equivalent, reconnect/backoff, `book_stream`/`trade_stream` tasks
- `exchange_adapter_mexc/src/spot.rs` — `SpotStyleAccount` gains
  `ws_base_url`, `subscribe_market_data` merges the ws streams
- `exchange_adapter_mexc/src/lib.rs` — thread `ws_base_url` through
  `ExchangeAdapterMexc::new`'s spot/margin construction (currently
  discarded, same as Binance's `ws_base_url` was pre-project)
- `exchange_adapter_mexc/src/endpoints.rs` — add `SPOT_DEPTH =
  "/api/v3/depth"` alongside the existing `SPOT_KLINES`/etc. constants
- `exchange_adapter_mexc/Cargo.toml` — add `tokio-tungstenite`
  (dev-dependency `tokio` gains the `net` feature, same as Binance's
  Task 5 fixture needed)
- `exchange_adapter_mexc/tests/` — new fake-ws-server test helper +
  protobuf byte-fixture tests
- `exchange_adapter_mexc/NOTES.md` — update §1 (book/trade no longer an
  unbuilt gap for spot/margin; MEXC futures remains the tracked
  follow-up)
- `external/executor/plans/02-L0-exchange-adapter.md` — update "Known
  gaps" to reflect MEXC spot/margin now has real ws, futures still open

## Open questions carried into planning

- Exact `tradeId` type on the wire (numeric vs. opaque string) —
  confirm at implementation time by reading MEXC's real example
  payloads more carefully or, if genuinely ambiguous, defensively
  support both.
- MEXC's idle-timeout constant (~45s proposed) is an estimate against
  documented behavior, not verified against a live connection — no
  MEXC credentials/network access were available while writing this
  spec, same limitation this crate's `NOTES.md` already documents for
  everything else in it.
