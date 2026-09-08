# Executor visualiser — design

Part of [architecture index](2026-09-04-architecture-design.md). Extends
[L8 — interfaces](layers/L8-interfaces.md), which named `visualizer_backend`
but explicitly left UI technology and transport out of scope
("a future frontend spec's concern"). This is that spec.

## Purpose

A read-only web dashboard showing the orchestrator's live and historical
state, per pair: price action, position, order book, decision/event
history. Read-only against already-tested lower layers — never a new
call path into the live `ExecutionEngine`, so it adds no pressure to the
hot (decision) path.

## Architecture

Three pieces, all above L8, no changes to L0–L7:

- **`visualizer_backend`** (existing crate, extended) — pure library,
  no transport. Already serves market data historical/live via
  `MarketDataStore`/`MarketDataFeed`. Extended to also read
  position/reconciliation/decision state.
- **`visualizer_server`** (new crate) — axum HTTP+WS server. Wraps
  `VisualizerBackend` + the configured pair list + an
  `observability::Alerts` handle (added during the final review-fix
  round, so a degraded-but-not-crashed read has somewhere to surface —
  this workspace has no `tracing` subscriber installed anywhere). No
  `state_store::StateStore` handle of its own: an earlier draft gave it
  one, but that meant `AppState` could carry two independently-
  constructed store handles (`backend`'s own internal one and this
  crate's separate one) with nothing constraining them to be the same
  underlying store. Resolved by adding mode-independent
  `VisualizerBackend::historical_order_book`/
  `historical_position_events` instead (see Components below) — every
  read this crate does, including order-book reconstruction
  (`BookTracker`), now goes through the one `backend` handle rather
  than this crate owning that logic itself. Serves the static frontend
  build.
- **frontend** (new, not a Rust crate) — static SPA using
  `lightweight-charts` (TradingView) for candlesticks. No backend
  logic of its own beyond rendering what the server sends.

Wired at L9 construction step 9, alongside `interfaces::cli`, same
point `L9-deploy.md` already names for L8.

## Why this doesn't touch the hot path

Both channels the visualiser needs already exist as
`tokio::sync::broadcast` (multi-consumer by design, not added for this):

- `market_data`'s per-pair `broadcast::Sender<MarketDataEvent>`
  (`store.rs`), covering `Trade`, `Candle`, `BookSnapshot`, `BookUpdate`,
  `Gap`.
- `execution`'s `broadcast::Sender<PositionStateEvent>`
  (`engine.rs`), already consumed by `mq_gateway` per L9 step 7.

`visualizer_server` becomes a second/third subscriber on these — one
extra `clone()` of a small event per broadcast send, no lock taken by
the decision loop, no synchronous call into `ExecutionEngine`. Current
state on connect/reconnect comes from `state_store` (persists current
`PositionState` per pair + an append-only decision log, independent of
the live engine) and `market_data`'s persisted store — never from
`ExecutionEngine::position_state()` directly.

Order book replay is not a special case: `BookSnapshot`/`BookUpdate`
are already persisted and returned by `MarketDataStore::read_range`/
`replay` exactly like trades/candles. `market_data` already exports
`BookTracker`/`apply_deltas` (used internally by `replay.rs`) to fold
snapshot+update events into full-depth state — reused here rather than
reimplemented.

## L5 addendum: event_log

Original draft of this spec assumed `state_store`'s existing
`decision_log` could serve History mode's event panel. It can't:
`decision_log` records inbound intent (`TradeDecision`/`ForceAction`),
not outcomes (Opened/Closed/StoppedOut/StopLossMoved) — and
`state_store`'s `PositionState` tree is overwrite-on-persist by
design, not a log. There was no persisted outcome history to read.

Resolved by adding `event_log` to L5 — a second append-only tree,
same shape and keying convention as `decision_log`, populated by a
second independent `subscribe_state_changes` broadcast subscriber
(alongside `mq_gateway`'s existing one; the channel is
multi-consumer by design, so this adds no coupling and no hot-path
contact). Full detail in
[L5-state-store.md](layers/L5-state-store.md)'s `event_log` sections.

## L5 addendum: last_reconciliation

Same category of gap, found during Task 2 (visualizer_backend):
`pair_snapshot`'s `reconciliation: Option<ReconciliationReport>` field
assumed `state_store` retained the last `reconcile()` outcome — it
didn't. `reconcile()` computes and returns a report once at boot
(L9 construction step 5); nothing kept it afterward.

Resolved by adding `StateStore::last_reconciliation() -> Option<
ReconciliationReport>` — an in-memory cache only (never sled-backed,
since it's inherently a since-last-boot fact, not something needing
durability across restarts), set every time `reconcile` runs. Full
detail in [L5-state-store.md](layers/L5-state-store.md)'s
`last_reconciliation` sections.

## Components

### `visualizer_backend` additions

- `pair_snapshot(pair) -> PairSnapshot { position: PositionState,
  reconciliation: Option<ReconciliationReport> }` — reads
  `state_store` only.
- `position_events(pair)` — historical/live split identical in shape
  to the existing `historical()`/`view()`: historical from
  `state_store::read_event_log` (see L5 addendum below), live via
  subscribing to `execution::subscribe_state_changes`, filtered to
  `pair`.
- `order_book_view(pair, from, to)` — runs `BookTracker` over the
  existing `historical()`/`view()` stream, yields reconstructed
  full-depth `OrderBookSnapshot`s (not raw deltas) so no consumer
  reimplements delta application.
- `historical_order_book(pair, from, to)` / `historical_position_events
  (pair, from, to)` — added during the final review-fix round.
  Unconditionally-historical counterparts to `order_book_view`/
  `position_events` (which both switch to the live feed once
  `LiveModeFlag` is live, exactly wrong for a History-tab request that
  must show the same range on repeat calls). Exist so
  `visualizer_server`'s history route never needs its own
  `state_store` handle or its own copy of `order_book_view`'s
  `BookTracker` fold — see the `visualizer_server` Architecture bullet
  above.

New deps: `state_store`, `execution` (for the broadcast event type).

### `visualizer_server` (new crate)

REST:
- `GET /pairs` — overview: `pair_snapshot` for every configured pair.
- `GET /pairs/:pair/history?from&to` — candles+trades+book for a
  historical range. Powers the History tab. No WS involved. The
  requested range is clamped server-side to a fixed maximum span (48h,
  added during the final review-fix round as a Critical-finding fix):
  an unbounded `from=0`/no-`to` request against a live pair's real
  history could otherwise mean hundreds of thousands of persisted book
  deltas alone, an in-process OOM risk against the same executor
  process this server shares memory with. A request outside the window
  isn't rejected — it silently gets the most recent bounded window
  instead. `book` in the response is likewise a single final
  reconstructed snapshot for the range (folded via
  `historical_order_book`), not one entry per book delta.

WS:
- `GET /pairs/:pair/ws` — **live tail only**. On connect: send a
  `Snapshot` message (current `pair_snapshot` — position/reconciliation
  state, not a history backfill), then multiplex candle/trade/book/
  position event messages over one socket as they arrive on the two
  broadcasts.

Live and historical are two distinct modes (REST vs WS), matching the
split `VisualizerBackend::view()` already has — not a third hybrid
mode. Chart/book backfill on initial page load is two sequential
fetches, not something the WS protocol carries: the frontend calls
`GET /pairs/:pair/history` first, then opens the WS for the live tail.
(An earlier draft had the WS `Snapshot` also carry "a short
recent-history window" — dropped during implementation for being
underspecified: no size, format, or content was ever pinned down, and
the REST endpoint already does this job cleanly.)

Serves the static frontend build at `/`.

### Frontend (static SPA)

- **Overview page**: per configured pair — status (flat/open + side),
  reconciliation health flag. No sparkline (YAGNI for now).
- **Pair page**, three panels:
  - Candlestick chart (`lightweight-charts`) with entry/SL/TP lines
    and trade markers overlaid.
  - Order book depth (bids/asks), fed by `order_book_view`'s
    reconstructed snapshots — works identically in Live and History
    modes.
  - Decision/event log — scrolling feed of `PositionStateEvent` +
    `DecisionRecord`, in stored order. Not per-entry timestamped on the
    wire today: `state_store::read_event_log`/`read_decision_log` both
    discard the `received_at` used to key each entry once read back
    (a pre-existing convention `decision_log` established, `event_log`
    correctly mirrored per L5's "match decision_log" guidance) — found
    during Task 4's frontend work, parked rather than fixed (would mean
    reopening `state_store`/`visualizer_backend`/`visualizer_server`
    for a display-only improvement); the frontend numbers entries in
    arrival order instead of fabricating a misleading timestamp. A
    future `received_at` field on the read path is a clean, isolated
    follow-up if wanted.
- **Live / History toggle**: Live tails the WS; History is a
  date-range picker against the REST endpoint only.

Explicitly out of scope for now: equity/PnL curve (needs its own
aggregation step over `PositionStateEvent` history, not a raw read —
deferred, YAGNI until asked for), and any command path (force-close
etc. stays on the existing `cli` → `mq_gateway` path per L8; the
dashboard does not grow a second command path).

## Error handling

- **Broadcast lag**: `tokio::broadcast` drops old messages for a slow
  receiver (`Lagged`) instead of blocking the sender — this is the
  mechanism that keeps the hot path unaffected. `visualizer_server`
  catches `Lagged`, re-reads the snapshot, tells the WS client to
  resync, and continues. Never a crash — consistent with L8's
  "read-only paths degrade to unavailable, never crash the engine."
- **WS disconnect**: client reconnects with backoff; reconnect follows
  the same resync-via-snapshot path as `Lagged`. The server holds no
  per-client state that outlives the socket.
- **Historical reads**: pure `state_store`/`market_data` store reads,
  no broadcast, no lag concept — ordinary REST error handling.
- **Trust boundary**: no authentication anywhere on this server — the
  dashboard is scoped to trusted local/host access only, enforced by
  `docker-compose.yml` binding it to `127.0.0.1` rather than all
  interfaces, plus a same-origin check on the WS upgrade route (added
  during the final review-fix round to close a Cross-Site WebSocket
  Hijacking gap: unlike `fetch`, a browser's `WebSocket` constructor is
  exempt from same-origin policy, so without that check any page open
  in the operator's browser could otherwise open a WS straight to this
  server and read live trading data).

## Testing

Same fixture-based convention as the rest of L8 — no exchange sandbox
needed, since this layer is read-only against already-tested lower
layers.

- `visualizer_backend`: `pair_snapshot` against a fixture
  `state_store`; `position_events` historical-vs-live split (same
  shape as the existing `view_switches_to_the_live_feed_once_live_is_set`
  test); `order_book_view` reconstructs the same sequence
  `BookTracker` produces internally, asserted byte-for-byte against a
  known snapshot+update sequence.
- `visualizer_server`: HTTP test client against `/pairs` and
  `/pairs/:pair/history`; WS test client asserting
  connect → snapshot → live-event ordering; a forced `Lagged` (small
  test channel, flood it) triggers resync, not a dropped connection.

## Acceptance criteria

- [ ] Overview page shows every configured pair's status +
      reconciliation flag, sourced from `state_store` only.
- [ ] Pair page in Live mode shows candles/position-overlay/order-book/
      event-log updating from the two broadcasts, with zero calls into
      `ExecutionEngine`.
- [ ] Pair page in History mode replays an arbitrary past range,
      including full order-book depth reconstructed via `BookTracker`,
      using only REST (no WS).
- [ ] A forced `Lagged` on either broadcast resyncs via snapshot
      instead of crashing the server or silently freezing the display.
- [ ] Killing/restarting `visualizer_server` has no observable effect
      on the orchestrator's decision loop or order placement.
