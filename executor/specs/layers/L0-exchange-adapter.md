# L0 — exchange_adapter

Part of [architecture index](../2026-09-04-architecture-design.md).

## Purpose

Exchange-agnostic trait for order placement, market-data subscription,
account/balance query. One common trait crate + one crate per exchange.

## Responsibilities

- Define `ExchangeAdapter` trait: exposes three sub-models, one per
  market kind — `spot()`, `margin()`, `futures()` — each an independent
  `MarketAccount` handling its own order placement, market-data
  subscription, and account query. Replaces an earlier draft where
  market kind was a plain enum parameter on flat methods: fees, margin
  rules, liquidation behavior, and available data (funding rate,
  open interest) differ enough per kind that each deserves its own
  model rather than a shared method branching on an enum internally.
- A given exchange may not support all three kinds (e.g. spot-only
  exchange, or one without margin) — the accessor for an unsupported
  kind returns `None`, not an error; calling code must check before
  use, same spirit as `get_extended_market_data`'s `Option`.
- `exchange_adapter_binance` and `exchange_adapter_mexc`: both
  implement `MarketAccount` for spot, margin, **and** futures,
  including position support (open/close/modify, margin/liquidation
  data) — this is L0's actual scope, not a narrowed first pass. Coding
  order within that scope is free to start with whichever
  exchange/kind is most convenient; future exchanges beyond these two
  follow the same pattern — same trait, own crate, added independently
  so an executor binary links only what it needs.
- Transport strategy for any market-data-shaped method
  (`subscribe_market_data`, and `get_extended_market_data` where the
  exchange streams it) is an adapter-internal decision, invisible to
  the trait's callers: default to the exchange's websocket; if the
  exchange has no ws for that data type, the adapter falls back to
  REST polling (or whatever mechanism the exchange offers) and
  presents the same `Stream`/`Result` interface either way. Callers
  never know or care which transport is behind a given data point.

## Depends on

Nothing in this workspace. Talks to the exchange itself (REST + ws).

## Construction / config

Each `exchange_adapter_X` crate defines its own concrete config type
(fields required differ per exchange — e.g. some need a passphrase,
some a subaccount id) but the common shape is:

```
struct AdapterConfig {
    api_key: SecretString,
    api_secret: SecretString,
    rest_base_url: Url,
    ws_base_url: Url,
    extra: HashMap<String, String>,   // exchange-specific: passphrase, subaccount id, ...
}

impl ExchangeAdapterBinance {
    fn new(config: AdapterConfig) -> Result<Self, AdapterError>;
}
```

Construction is inherent per adapter crate, not part of the
`ExchangeAdapter` trait — the trait describes post-construction
behavior only. `AdapterConfig` is sourced from env/config at process
start (L9), never hardcoded, never logged, never sent over
`mq_gateway` — same constraint `main_goal.md` states for credentials
generally. Distinct base URLs for REST vs ws (and for testnet vs
prod, via a different `AdapterConfig` value) mean environment
switching is a config change, not a code change.

## Interface exposed upward

```
trait ExchangeAdapter {
    fn spot(&self)    -> Option<&dyn MarketAccount>;
    fn margin(&self)  -> Option<&dyn MarketAccount>;
    fn futures(&self) -> Option<&dyn MarketAccount>;
}

trait MarketAccount {
    fn subscribe_market_data(&self, pair: Pair)
        -> Stream<MarketDataEvent>;          // BookDelta | Candle
    fn place_order(&self, order: OrderRequest)
        -> Result<OrderAck, AdapterError>;
    fn cancel_order(&self, id: OrderId)
        -> Result<(), AdapterError>;
    fn get_order(&self, id: OrderId)
        -> Result<OrderInfo, AdapterError>;      // status, filled qty, avg fill price
    fn get_account_state(&self)
        -> Result<AccountState, AdapterError>;   // balances, positions, open orders
    fn get_fees(&self, pair: Pair)
        -> Result<FeeSchedule, AdapterError>;    // maker/taker rate, tier if applicable
    fn get_market_info(&self, pair: Pair)
        -> Result<MarketInfo, AdapterError>;     // tick size, lot size, min notional, precision, trading status
    fn get_extended_market_data(&self, pair: Pair)
        -> Result<Option<ExtendedMarketData>, AdapterError>;
        // funding rate, open interest, mark price — None (not an error)
        // when this kind doesn't have such data, e.g. always None on spot
    fn subscribe_account_updates(&self)
        -> Stream<AccountEvent>;   // own order/fill/balance/position changes, pushed
}
```

No `MarketKind` parameter anywhere on `MarketAccount` — the kind is
implicit in which sub-model you got from `spot()`/`margin()`/
`futures()`. Both `exchange_adapter_binance` and `exchange_adapter_mexc`
implement all three accessors returning `Some` — spot, margin, and
futures are all in scope, not a staged rollout of kinds. `None` from
one of these accessors is reserved for a future exchange that
genuinely lacks a kind (e.g. one without margin), not for these two.

Consumers: `market_data` (subscribe_market_data on whichever
`MarketAccount` it's tracking), `execution` and `state_store`
(place_order/cancel_order/get_account_state on the sub-model matching
the position's market kind). `get_order` specifically: `execution`
polls it after place_order when ack alone doesn't confirm fill state;
`state_store` uses it for per-order reconciliation detail beyond the
bulk `get_account_state` snapshot (e.g. confirming whether a
locally-open order actually filled, partially filled, or was cancelled
on the exchange side).

`get_fees`: `execution` needs this for PnL/sizing that accounts for
cost, not just SL/TP price levels. `get_market_info`: `execution` uses
it to round/validate order price and size to the exchange's tick/lot
before calling place_order — a rejected order due to precision
mismatch is a class of failure this method exists to prevent, not to
handle after the fact. `get_extended_market_data`: `execution`'s
margin/liquidation-proximity risk calc (per L3) folds in funding rate
where the `futures`/`margin` sub-model provides it; `spot()`'s
`MarketAccount` always returns `None` here, which is expected, not an
`AdapterError`.

## Shared data types (propagated to market_data)

`exchange_adapter` defines the wire-shape types that cross the L0→L1
boundary — `market_data` doesn't invent its own book/trade
representation, it consumes these directly:

```
enum MarketDataEvent {
    BookSnapshot(OrderBookSnapshot),   // full state, on (re)subscribe
    BookUpdate(OrderBookUpdate),       // incremental delta
    Trade(TradeTick),                  // latest public trade
    Candle(CandleUpdate),
}

struct OrderBookSnapshot { pair: Pair, bids: Vec<PriceLevel>, asks: Vec<PriceLevel>, sequence: u64, ts: Ts }
struct OrderBookUpdate   { pair: Pair, bids: Vec<PriceLevelDelta>, asks: Vec<PriceLevelDelta>, sequence: u64, ts: Ts }
struct TradeTick         { pair: Pair, price: Decimal, qty: Decimal, side: Side, trade_id: TradeId, ts: Ts }
```

`OrderBookSnapshot` + `OrderBookUpdate` are separate variants, not one
"book state" blob — `market_data` needs the snapshot once to seed
local state, then applies updates incrementally; conflating them would
force every consumer to diff full states instead of applying deltas.

`AccountEvent` (from `subscribe_account_updates`) is the *client's own*
real-time information — order status changes, fills, balance/position
changes — pushed, as a companion to the point-query `get_order`/
`get_account_state`. It is not public market data and never appears on
`subscribe_market_data`'s stream:

```
enum AccountEvent {
    OrderUpdate(OrderInfo),        // status transition: new/partially-filled/filled/cancelled/rejected
    BalanceUpdate(BalanceDelta),
    PositionUpdate(PositionInfo),  // margin/futures position change
}
```

Consumers: `market_data` takes `MarketDataEvent` directly (this is the
type `subscribe_market_data`'s `Stream` carries, referenced already in
L1's doc). `execution` takes `AccountEvent` to react to fills/status
changes without polling `get_order` on a timer — `state_store` also
observes it to keep persisted state current between explicit
`persist()` calls.

## Error handling

Ws disconnect / API error → retry w/ backoff internally; surface
staleness up via `AdapterError::Stale` so `market_data` can flag the
feed and `execution` can fall back to exchange-native-stop-only once
past grace period. Never swallow — every adapter error is observable.

### Crossed-book safety check

Each ws book task maintains its own ladder (seeded by the REST resync
snapshot, advanced by every update it forwards) purely so it can check
one invariant after each applied update: the highest bid must never sit
*strictly* above the lowest ask. `bid == ask` is a locked book —
transient but legal — and is not an error.

A cross means the local book has diverged from the exchange's, so:

- the offending update is **withheld**, never forwarded to L1 — a
  known-broken book must not reach any consumer, which would otherwise
  read a phantom (negative) spread;
- an `AlertKind::BookCrossed` alert fires at `Severity::Error`,
  carrying the pair and the crossed best bid/ask, and a
  `book_crossed_detected` metric is recorded. `BookCrossed` is distinct
  from `FeedStale` (gaps, silence) because the money-safety implication
  and the recovery differ;
- the sync is dropped and the task takes the same recovery path as a
  sequence desync: reconnect, refetch the REST depth snapshot, replay
  the events buffered during that round trip on top of it, and emit the
  fresh `BookSnapshot`. The desync retry floor bounds a stream that
  crosses repeatedly, so a pathological feed cannot hot-loop the
  weight-limited depth endpoint.

The check lives in L0, not in `market_data`'s `BookTracker`, because
only L0 holds the REST client and the buffered-replay machinery needed
to act on it; L1 could detect a cross but not repair it. The shared
`apply_deltas` helper therefore lives in `exchange_adapter` (this leaf
crate) and is re-exported by `market_data` — L0 cannot depend on L1.

## Testing

Contract tests against the trait (fakeable), integration tests against
exchange testnet/sandbox where available. No dependency on any other
workspace crate — this crate is a leaf.

## Acceptance criteria (staged)

L0 is signed off in stages, each gated on the layer it glues to next.
Stage 1 is the crate's own definition-of-done: both exchanges, all
three kinds, position support included — matching L0's scope above,
not a narrowed first increment.

**Stage 1 — standalone adapter, no other layer exists yet**
- [ ] `exchange_adapter_binance` and `exchange_adapter_mexc` each
      implement `MarketAccount` for spot, margin, and futures —
      `spot()`/`margin()`/`futures()` all return `Some` for both
      exchanges.
- [ ] `subscribe_market_data` streams real book snapshots, book
      updates, trades, and candles for a live pair; received data is
      posted to the log (observability, per L7) so correctness is
      confirmed by inspection — no `market_data` crate required yet.
- [ ] `place_order` opens a position and a corresponding order closes
      it, both against the exchange (or its testnet/sandbox) — proven
      for spot, and for margin/futures including position modify
      (size/leverage change on an open position, not just open/close).
- [ ] `cancel_order` succeeds against a resting order, each kind.
- [ ] `get_order` returns correct status, filled qty, and avg fill
      price after a real fill.
- [ ] `get_extended_market_data` returns real funding rate/mark
      price/open interest on margin and futures sub-models (not just
      `None`, which is only correct for spot).
- [ ] Verified via integration test against exchange testnet/sandbox
      (per Testing above) — passes with L0 alone in the workspace.

**Stage 2 — glue to L1 (`market_data`)** — gated: cannot start until
`market_data` exists.
- [ ] `MarketDataEvent` (book snapshot/update, trade, candle) from L0
      is consumed end-to-end by `market_data` and produces a correct
      live order book and trade tape — verified against the same live
      pair used in stage 1, comparing L0's raw log output to what L1
      reconstructs.
- [ ] `AccountEvent` reaches `market_data::subscribe_account_events`
      with no data loss (every `OrderUpdate`/`BalanceUpdate`/
      `PositionUpdate` L0 emits is observed on L1's stream).
- [ ] **Process note**: each time a new dependent layer lands, reopen
      that layer's acceptance criteria and re-check it against the
      *real* interface just built, not the interface assumed when this
      doc was written — fix mismatches in both docs before moving to
      the next stage. This applies to every stage below too, not just
      this one.

**Stage 3 — glue to L3 (`execution`)** — gated: cannot start until
`execution` exists.
- [ ] `execution` opens and closes a position purely by calling L0's
      `place_order`/`cancel_order` (via the correct `MarketAccount`
      sub-model for the position's kind).
- [ ] `execution` receives fill confirmation via the `AccountEvent`
      path (L0 → L1 → L3, per L3's Depends-on), matching what L0
      actually sent — not a stubbed/mocked value.
- [ ] Full round trip (execution places an order → L0 confirms status
      → execution observes it) verified with no manual step in
      between.

**Stage 4 — glue to L5 (`state_store`)** — gated: cannot start until
`state_store` exists.
- [ ] `get_account_state`/`get_order` data reaching
      `state_store::reconcile` matches what L0 actually returns from
      the exchange, not a stub.
- [ ] A boot-time reconciliation test recovers correctly from a
      simulated mismatch (e.g. position closed on the exchange while
      the process was down), sourced from real L0 calls against
      testnet/sandbox, not fixture data alone.
