# Binance Market-Data WebSocket Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `exchange_adapter_binance`'s `subscribe_market_data` real websocket-backed `BookSnapshot`/`BookUpdate`/`Trade` events (currently only `Candle`, via REST polling), closing the gap flagged in `external/executor/plans/02-L0-exchange-adapter.md`'s "Known gaps".

**Architecture:** New `ws.rs` module in `exchange_adapter_binance`: a pure `DepthSync` state machine implements Binance's snapshot-buffer-resync procedure and assigns L1-compatible synthetic sequence numbers; a `Backoff` struct drives reconnect timing; two independent `tokio-tungstenite`-backed tasks (book-diff, trade) run per pair, fanned into the existing `MarketDataStream` alongside the untouched REST candle-poll task via `futures_util::stream::select`.

**Tech Stack:** Rust, `tokio-tungstenite` (new dep, rustls), `async-stream` (new dep, matches `exchange_adapter_mexc`'s existing pattern), `futures_util::stream::select`, existing `wiremock`/`tokio::test` test harness.

**Spec:** `external/executor/specs/2026-09-05-binance-market-data-websocket-design.md`

## Global Constraints

- `tokio-tungstenite`, rustls-tls feature (`rustls-tls-webpki-roots`) — no OpenSSL, matching `reqwest`'s existing choice (spec "Architecture").
- Account-update push and `Candle`-over-ws are explicitly out of scope (spec "Out of scope") — do not touch `subscribe_account_updates` or the existing candle-poll code path's behavior.
- A real `Gap`/`GapMarker` must never be produced by the live ws path — any Binance-side desync is resolved internally via resync, never surfaced as `MarketDataEvent::Gap` (spec "Sequence numbering").
- `BookUpdate.sequence` numbering: first `BookUpdate` after any `BookSnapshot` is `1`, then `2, 3, ...` — matches `market_data/src/book.rs`'s `BookTracker::seed` (`expected_sequence = snapshot.sequence + 1`). `BookSnapshot.sequence` is always `0`.
- Reconnect backoff: `1s → 2s → 4s → ... capped at 30s`, reset to `1s` after a stable connection (spec "Reconnect policy"). Backoff must be an injectable value (not hardcoded inside the task functions) so tests can use a fast schedule instead of waiting on real timers.
- MEXC, protobuf decoding, and anything under the spec's "Portability to MEXC" section are out of scope for this plan — do not add MEXC code here.

---

## Task 1: Wire-format types and pure JSON→L0 conversions

**Files:**
- Create: `crates/exchange_adapter_binance/src/ws.rs`
- Modify: `crates/exchange_adapter_binance/src/lib.rs:12-18` (add `mod ws;`)
- Modify: `crates/exchange_adapter_binance/Cargo.toml` (add `tokio-tungstenite`, `async-stream`)
- Test: inline `#[cfg(test)] mod tests` at the bottom of `ws.rs`

**Interfaces:**
- Consumes: `exchange_adapter::{parse_decimal, OrderBookSnapshot, OrderBookUpdate, PriceLevel, PriceLevelDelta, Ts, Pair, TradeTick, TradeId, Side, AdapterError}` (all already public per `exchange_adapter/src/lib.rs`).
- Produces (used by Tasks 2-8):
  - `pub(crate) struct RawDepthEvent { first_update_id: u64, final_update_id: u64, prev_final_update_id: Option<u64>, event_time: u64, bids: Vec<(String,String)>, asks: Vec<(String,String)> }` (fields `pub(crate)`)
  - `pub(crate) struct RawTradeEvent { trade_id: u64, price: String, qty: String, buyer_is_maker: bool, trade_time: u64 }` (fields `pub(crate)`)
  - `pub(crate) struct DepthSnapshotResponse { last_update_id: u64, bids: Vec<(String,String)>, asks: Vec<(String,String)> }` (fields `pub(crate)`)
  - `pub(crate) fn to_levels(raw: &[(String, String)]) -> Result<Vec<PriceLevel>, AdapterError>`
  - `pub(crate) fn to_deltas(raw: &[(String, String)]) -> Result<Vec<PriceLevelDelta>, AdapterError>`
  - `pub(crate) fn trade_tick_from_raw(pair: &Pair, raw: RawTradeEvent) -> Result<TradeTick, AdapterError>`

- [ ] **Step 1: Add dependencies**

Edit `crates/exchange_adapter_binance/Cargo.toml`, in `[dependencies]` (alphabetical, matching the file's existing order):

```toml
async-stream = "0.3.6"
tokio-tungstenite = { version = "0.24", default-features = false, features = ["connect", "handshake", "rustls-tls-webpki-roots"] }
```

And in `[dev-dependencies]`, add `"net"` to tokio's feature list so the test fixture (Task 5) can bind a `TcpListener`:

```toml
[dev-dependencies]
tokio = { version = "1.53.1", features = ["rt-multi-thread", "macros", "time", "net"] }
wiremock = "0.6.5"
```

- [ ] **Step 2: Run `cargo check -p exchange_adapter_binance` to confirm the new deps resolve**

Run: `cd trade_executor && cargo check -p exchange_adapter_binance`
Expected: succeeds (no code uses the new crates yet, this only proves they resolve/build).

- [ ] **Step 3: Write the failing tests**

Create `crates/exchange_adapter_binance/src/ws.rs` with just the doc comment and test module first:

```rust
//! Real websocket market data for Binance: book-diff and trade streams,
//! merged into `subscribe_market_data`'s `MarketDataStream` alongside the
//! existing REST candle poll. See
//! `external/executor/specs/2026-09-05-binance-market-data-websocket-design.md`.

use serde::Deserialize;

use exchange_adapter::{
    parse_decimal, AdapterError, Pair, PriceLevel, PriceLevelDelta, Side, TradeId, TradeTick, Ts,
};

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct RawDepthEvent {
    #[serde(rename = "U")]
    pub(crate) first_update_id: u64,
    #[serde(rename = "u")]
    pub(crate) final_update_id: u64,
    #[serde(rename = "pu")]
    pub(crate) prev_final_update_id: Option<u64>,
    #[serde(rename = "E")]
    pub(crate) event_time: u64,
    #[serde(rename = "b")]
    pub(crate) bids: Vec<(String, String)>,
    #[serde(rename = "a")]
    pub(crate) asks: Vec<(String, String)>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct RawTradeEvent {
    #[serde(rename = "t")]
    pub(crate) trade_id: u64,
    #[serde(rename = "p")]
    pub(crate) price: String,
    #[serde(rename = "q")]
    pub(crate) qty: String,
    #[serde(rename = "m")]
    pub(crate) buyer_is_maker: bool,
    #[serde(rename = "T")]
    pub(crate) trade_time: u64,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct DepthSnapshotResponse {
    #[serde(rename = "lastUpdateId")]
    pub(crate) last_update_id: u64,
    pub(crate) bids: Vec<(String, String)>,
    pub(crate) asks: Vec<(String, String)>,
}

pub(crate) fn to_levels(raw: &[(String, String)]) -> Result<Vec<PriceLevel>, AdapterError> {
    raw.iter()
        .map(|(price, qty)| {
            Ok(PriceLevel { price: parse_decimal(price)?, qty: parse_decimal(qty)? })
        })
        .collect()
}

pub(crate) fn to_deltas(raw: &[(String, String)]) -> Result<Vec<PriceLevelDelta>, AdapterError> {
    raw.iter()
        .map(|(price, qty)| {
            Ok(PriceLevelDelta { price: parse_decimal(price)?, qty: parse_decimal(qty)? })
        })
        .collect()
}

/// `m` ("is the buyer the market maker") is Binance's proxy for trade
/// side: when true, the resting order was a bid and the aggressor sold
/// into it, so the trade is a sell from the taker's perspective, and vice
/// versa. `TradeTick.side` is the taker's side, matching how L0's other
/// wire types (`OrderRequest.side`, etc.) always mean the acting party.
pub(crate) fn trade_tick_from_raw(pair: &Pair, raw: RawTradeEvent) -> Result<TradeTick, AdapterError> {
    Ok(TradeTick {
        pair: pair.clone(),
        price: parse_decimal(&raw.price)?,
        qty: parse_decimal(&raw.qty)?,
        side: if raw.buyer_is_maker { Side::Sell } else { Side::Buy },
        trade_id: TradeId(raw.trade_id),
        ts: Ts(raw.trade_time),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_depth_json() -> &'static str {
        r#"{"e":"depthUpdate","E":123456789,"s":"BTCUSDT","U":157,"u":160,"b":[["0.0024","10"]],"a":[["0.0026","100"]]}"#
    }

    fn sample_futures_depth_json() -> &'static str {
        r#"{"e":"depthUpdate","E":123456789,"T":123456788,"s":"BTCUSDT","U":157,"u":160,"pu":149,"b":[["0.0024","10"]],"a":[]}"#
    }

    fn sample_trade_json() -> &'static str {
        r#"{"e":"trade","E":123456789,"s":"BNBBTC","t":12345,"p":"0.001","q":"100","b":88,"a":50,"T":123456785,"m":true,"M":true}"#
    }

    fn sample_snapshot_json() -> &'static str {
        r#"{"lastUpdateId":160,"bids":[["0.0024","10"]],"asks":[["0.0026","100"]]}"#
    }

    #[test]
    fn parses_spot_depth_event_with_no_prev_final_update_id() {
        let raw: RawDepthEvent = serde_json::from_str(sample_depth_json()).unwrap();
        assert_eq!(raw.first_update_id, 157);
        assert_eq!(raw.final_update_id, 160);
        assert_eq!(raw.prev_final_update_id, None);
        assert_eq!(raw.event_time, 123456789);
    }

    #[test]
    fn parses_futures_depth_event_with_prev_final_update_id() {
        let raw: RawDepthEvent = serde_json::from_str(sample_futures_depth_json()).unwrap();
        assert_eq!(raw.prev_final_update_id, Some(149));
    }

    #[test]
    fn parses_trade_event() {
        let raw: RawTradeEvent = serde_json::from_str(sample_trade_json()).unwrap();
        assert_eq!(raw.trade_id, 12345);
        assert_eq!(raw.price, "0.001");
        assert!(raw.buyer_is_maker);
        assert_eq!(raw.trade_time, 123456785);
    }

    #[test]
    fn parses_snapshot_response() {
        let raw: DepthSnapshotResponse = serde_json::from_str(sample_snapshot_json()).unwrap();
        assert_eq!(raw.last_update_id, 160);
        assert_eq!(raw.bids, vec![("0.0024".to_string(), "10".to_string())]);
    }

    #[test]
    fn to_levels_parses_decimals() {
        let levels = to_levels(&[("0.0024".to_string(), "10".to_string())]).unwrap();
        assert_eq!(levels[0].price.to_string(), "0.0024");
        assert_eq!(levels[0].qty.to_string(), "10");
    }

    #[test]
    fn to_levels_rejects_non_numeric_input() {
        assert!(to_levels(&[("not-a-number".to_string(), "10".to_string())]).is_err());
    }

    #[test]
    fn buyer_is_maker_true_means_taker_sold() {
        let raw: RawTradeEvent = serde_json::from_str(sample_trade_json()).unwrap();
        let pair = Pair("BNBBTC".to_string());
        let tick = trade_tick_from_raw(&pair, raw).unwrap();
        assert_eq!(tick.side, Side::Sell);
        assert_eq!(tick.trade_id, TradeId(12345));
    }

    #[test]
    fn buyer_is_maker_false_means_taker_bought() {
        let mut raw: RawTradeEvent = serde_json::from_str(sample_trade_json()).unwrap();
        raw.buyer_is_maker = false;
        let pair = Pair("BNBBTC".to_string());
        let tick = trade_tick_from_raw(&pair, raw).unwrap();
        assert_eq!(tick.side, Side::Buy);
    }
}
```

- [ ] **Step 4: Register the module**

Edit `crates/exchange_adapter_binance/src/lib.rs`, add `mod ws;` alongside the other `mod` declarations (after `mod signing;`).

- [ ] **Step 5: Run the tests, confirm they pass**

Run: `cargo test -p exchange_adapter_binance ws::tests`
Expected: 9 tests pass. (This task has no separate RED step — the types and the tests that exercise them are written together since there's no meaningful intermediate "fails to compile" milestone worth checkpointing; every subsequent task in this plan *does* follow strict red-then-green.)

- [ ] **Step 6: Commit**

```bash
git add crates/exchange_adapter_binance/Cargo.toml crates/exchange_adapter_binance/src/lib.rs crates/exchange_adapter_binance/src/ws.rs
git commit -m "feat(exchange_adapter_binance): add ws wire-format types for depth/trade streams"
```

---

## Task 2: Depth REST endpoint paths

**Files:**
- Modify: `crates/exchange_adapter_binance/src/kind.rs`
- Test: `crates/exchange_adapter_binance/src/kind.rs` (extend the existing inline test, or add one alongside it — check the file for a `#[cfg(test)]` block first; if none exists yet, add one)

**Interfaces:**
- Consumes: nothing new.
- Produces: `Endpoints.depth: &'static str`, used by Task 7's book-stream REST snapshot fetch as `self.kind.endpoints().depth`.

- [ ] **Step 1: Write the failing test**

Add to `kind.rs` (create the `#[cfg(test)] mod tests` block if the file doesn't have one — check first with `grep -n "mod tests" crates/exchange_adapter_binance/src/kind.rs`):

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn each_kind_has_a_depth_endpoint() {
        assert_eq!(MarketKind::Spot.endpoints().depth, "/api/v3/depth");
        assert_eq!(MarketKind::Margin.endpoints().depth, "/api/v3/depth");
        assert_eq!(MarketKind::Futures.endpoints().depth, "/fapi/v1/depth");
    }
}
```

- [ ] **Step 2: Run it, confirm it fails to compile**

Run: `cargo test -p exchange_adapter_binance kind::tests`
Expected: FAIL — `Endpoints` has no field `depth`.

- [ ] **Step 3: Add the field**

In `kind.rs`, add `pub depth: &'static str,` to the `Endpoints` struct (after `exchange_info`), and add the value to each of the three `MarketKind::endpoints()` match arms:
- `MarketKind::Spot` and `MarketKind::Margin`: `depth: "/api/v3/depth",` (margin's book is spot's book, same as `klines`/`exchange_info` already are for margin)
- `MarketKind::Futures`: `depth: "/fapi/v1/depth",`

- [ ] **Step 4: Run it, confirm it passes**

Run: `cargo test -p exchange_adapter_binance kind::tests`
Expected: PASS.

- [ ] **Step 5: Run the full existing test suite to confirm nothing else broke**

Run: `cargo test -p exchange_adapter_binance`
Expected: all existing tests still pass — `Endpoints` gained a field but every existing construction site uses struct-literal syntax with all fields named, so this is additive only. If any construction site uses `..Default::default()` or positional construction, this step will show a compile error there — fix by adding the missing field.

- [ ] **Step 6: Commit**

```bash
git add crates/exchange_adapter_binance/src/kind.rs
git commit -m "feat(exchange_adapter_binance): add per-kind depth REST endpoint"
```

---

## Task 3: `DepthSync` — pure snapshot-buffer-resync state machine

**Files:**
- Modify: `crates/exchange_adapter_binance/src/ws.rs` (add below the wire types from Task 1, above the `#[cfg(test)]` block)

**Interfaces:**
- Consumes: `RawDepthEvent`, `DepthSnapshotResponse`, `to_levels`, `to_deltas` (Task 1); `exchange_adapter::{MarketDataEvent, OrderBookSnapshot, OrderBookUpdate, Pair, Ts}`.
- Produces (used by Task 7):
  - `pub(crate) enum DepthSyncOutcome { Buffering, Update(OrderBookUpdate), Desynced }`
  - `pub(crate) struct DepthSync` with:
    - `pub(crate) fn new(pair: Pair) -> Self`
    - `pub(crate) fn on_event(&mut self, raw: RawDepthEvent) -> DepthSyncOutcome`
    - `pub(crate) fn resync(&mut self, snapshot: DepthSnapshotResponse, ts: Ts) -> Result<Vec<MarketDataEvent>, AdapterError>`
    - `pub(crate) fn mark_disconnected(&mut self)`

- [ ] **Step 1: Write the failing tests**

Add to the `#[cfg(test)] mod tests` block in `ws.rs`:

```rust
fn depth_event(first: u64, final_: u64, prev: Option<u64>) -> RawDepthEvent {
    RawDepthEvent {
        first_update_id: first,
        final_update_id: final_,
        prev_final_update_id: prev,
        event_time: 1000,
        bids: vec![("100".to_string(), "1".to_string())],
        asks: vec![],
    }
}

fn snapshot(last_update_id: u64) -> DepthSnapshotResponse {
    DepthSnapshotResponse {
        last_update_id,
        bids: vec![("99".to_string(), "2".to_string())],
        asks: vec![],
    }
}

#[test]
fn events_before_any_snapshot_are_buffered() {
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    let outcome = sync.on_event(depth_event(150, 155, None));
    assert!(matches!(outcome, DepthSyncOutcome::Buffering));
}

#[test]
fn resync_emits_a_snapshot_with_sequence_zero() {
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    let events = sync.resync(snapshot(160), Ts(2000)).unwrap();
    assert_eq!(events.len(), 1);
    match &events[0] {
        MarketDataEvent::BookSnapshot(snap) => {
            assert_eq!(snap.sequence, 0);
            assert_eq!(snap.ts, Ts(2000));
            assert_eq!(snap.bids[0].price.to_string(), "99");
        }
        other => panic!("expected BookSnapshot, got {other:?}"),
    }
}

#[test]
fn resync_replays_the_bridging_buffered_event_as_update_sequence_one() {
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    // Stale (u <= 160): dropped. Bridging (U <= 161 <= u): replayed as
    // sequence 1. This models Binance's own worked example.
    sync.on_event(depth_event(150, 160, None)); // stale, buffered pre-sync
    sync.on_event(depth_event(161, 165, None)); // bridges lastUpdateId=160
    let events = sync.resync(snapshot(160), Ts(2000)).unwrap();
    assert_eq!(events.len(), 2);
    match &events[1] {
        MarketDataEvent::BookUpdate(update) => assert_eq!(update.sequence, 1),
        other => panic!("expected BookUpdate, got {other:?}"),
    }
}

#[test]
fn contiguous_spot_event_after_resync_is_sequence_two() {
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    sync.resync(snapshot(160), Ts(2000)).unwrap();
    let outcome = sync.on_event(depth_event(161, 165, None));
    match outcome {
        DepthSyncOutcome::Update(update) => assert_eq!(update.sequence, 1),
        other => panic!("expected Update, got {other:?}"),
    }
    let outcome = sync.on_event(depth_event(166, 170, None));
    match outcome {
        DepthSyncOutcome::Update(update) => assert_eq!(update.sequence, 2),
        other => panic!("expected Update, got {other:?}"),
    }
}

#[test]
fn spot_gap_is_detected_via_first_update_id() {
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    sync.resync(snapshot(160), Ts(2000)).unwrap();
    sync.on_event(depth_event(161, 165, None)); // establishes last_seen_final_id = 165
    let outcome = sync.on_event(depth_event(170, 175, None)); // gap: 170 != 166
    assert!(matches!(outcome, DepthSyncOutcome::Desynced));
}

#[test]
fn futures_contiguity_uses_prev_final_update_id_not_first_update_id() {
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    sync.resync(snapshot(160), Ts(2000)).unwrap();
    // Futures events can have gappy U/u ranges but a correct `pu` chain.
    let outcome = sync.on_event(depth_event(200, 210, Some(160)));
    assert!(matches!(outcome, DepthSyncOutcome::Update(_)));
}

#[test]
fn futures_gap_is_detected_via_prev_final_update_id_mismatch() {
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    sync.resync(snapshot(160), Ts(2000)).unwrap();
    let outcome = sync.on_event(depth_event(200, 210, Some(999)));
    assert!(matches!(outcome, DepthSyncOutcome::Desynced));
}

#[test]
fn after_desync_events_are_buffered_again_until_the_next_resync() {
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    sync.resync(snapshot(160), Ts(2000)).unwrap();
    let outcome = sync.on_event(depth_event(999, 999, None)); // gap
    assert!(matches!(outcome, DepthSyncOutcome::Desynced));
    let outcome = sync.on_event(depth_event(1000, 1001, None));
    assert!(matches!(outcome, DepthSyncOutcome::Buffering));
}

#[test]
fn resync_after_desync_starts_the_update_counter_at_one_again() {
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    sync.resync(snapshot(160), Ts(2000)).unwrap();
    sync.on_event(depth_event(161, 165, None));
    sync.on_event(depth_event(999, 999, None)); // forces desync
    let events = sync.resync(snapshot(500), Ts(3000)).unwrap();
    assert_eq!(events.len(), 1); // no buffered events bridge 500
    let outcome = sync.on_event(depth_event(501, 505, None));
    match outcome {
        DepthSyncOutcome::Update(update) => assert_eq!(update.sequence, 1),
        other => panic!("expected Update, got {other:?}"),
    }
}

#[test]
fn mark_disconnected_forces_buffering_even_without_a_failed_contiguity_check() {
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    sync.resync(snapshot(160), Ts(2000)).unwrap();
    sync.mark_disconnected();
    let outcome = sync.on_event(depth_event(161, 165, None));
    assert!(matches!(outcome, DepthSyncOutcome::Buffering));
}
```

- [ ] **Step 2: Run the tests, confirm they fail to compile**

Run: `cargo test -p exchange_adapter_binance ws::tests`
Expected: FAIL — `DepthSync`/`DepthSyncOutcome` don't exist yet.

- [ ] **Step 3: Implement `DepthSync`**

Add to `ws.rs`, above the test module:

```rust
use exchange_adapter::{MarketDataEvent, OrderBookSnapshot, OrderBookUpdate};

#[derive(Debug)]
pub(crate) enum DepthSyncOutcome {
    /// No REST snapshot has been applied yet (or a desync just happened)
    /// -- the event is buffered internally, nothing to emit.
    Buffering,
    /// Contiguous with what came before; safe to forward.
    Update(OrderBookUpdate),
    /// Contiguity broke: spot/margin (`prev_final_update_id.is_none()`)
    /// checks `first_update_id == last_seen_final_id + 1`; futures checks
    /// `prev_final_update_id == Some(last_seen_final_id)`. The caller must
    /// fetch a fresh REST snapshot and call `resync`.
    Desynced,
}

/// Implements Binance's documented diff-depth-stream sync procedure
/// (buffer until a REST snapshot arrives, drop stale buffered events,
/// find the bridging event, then require strict contiguity) and
/// translates it into the synthetic, always-contiguous sequence numbers
/// `market_data`'s `BookTracker` expects. See the design spec's
/// "Binance's snapshot-sync procedure" and "Sequence numbering" sections.
pub(crate) struct DepthSync {
    pair: Pair,
    synced: bool,
    last_seen_final_id: u64,
    counter: u64,
    buffer: Vec<RawDepthEvent>,
}

impl DepthSync {
    pub(crate) fn new(pair: Pair) -> Self {
        Self { pair, synced: false, last_seen_final_id: 0, counter: 1, buffer: Vec::new() }
    }

    pub(crate) fn on_event(&mut self, raw: RawDepthEvent) -> DepthSyncOutcome {
        if !self.synced {
            self.buffer.push(raw);
            return DepthSyncOutcome::Buffering;
        }
        if !self.is_contiguous(&raw) {
            self.synced = false;
            return DepthSyncOutcome::Desynced;
        }
        self.last_seen_final_id = raw.final_update_id;
        match self.to_update(raw) {
            Ok(update) => DepthSyncOutcome::Update(update),
            Err(_) => {
                // A malformed price/qty string mid-stream is exchange
                // misbehavior, not a sequencing problem -- treat it the
                // same as a desync so the caller resyncs from a clean
                // snapshot rather than forwarding a partially-broken
                // update.
                self.synced = false;
                DepthSyncOutcome::Desynced
            }
        }
    }

    pub(crate) fn mark_disconnected(&mut self) {
        self.synced = false;
    }

    fn is_contiguous(&self, raw: &RawDepthEvent) -> bool {
        match raw.prev_final_update_id {
            Some(pu) => pu == self.last_seen_final_id,
            None => raw.first_update_id == self.last_seen_final_id + 1,
        }
    }

    fn to_update(&mut self, raw: RawDepthEvent) -> Result<OrderBookUpdate, AdapterError> {
        let sequence = self.counter;
        self.counter += 1;
        Ok(OrderBookUpdate {
            pair: self.pair.clone(),
            bids: to_deltas(&raw.bids)?,
            asks: to_deltas(&raw.asks)?,
            sequence,
            ts: Ts(raw.event_time),
        })
    }

    /// Call once a REST snapshot has been fetched -- on the very first
    /// sync, or any time `on_event` returned `Desynced`, or right after a
    /// reconnect (paired with `mark_disconnected`). Replays any events
    /// buffered while the snapshot was in flight: stale ones (`u <=
    /// lastUpdateId`) are dropped, the first bridging event (`U <=
    /// lastUpdateId+1`) is applied as sequence `1`, and further buffered
    /// events apply normally as long as they stay contiguous. A
    /// discontinuity found *within* the replayed buffer stops the replay
    /// early (rare in practice -- the buffer only covers the brief REST
    /// round-trip); the next live event will fail its own contiguity
    /// check against the last successfully-replayed one and trigger
    /// another resync, so nothing is silently lost long-term.
    pub(crate) fn resync(
        &mut self,
        snapshot: DepthSnapshotResponse,
        ts: Ts,
    ) -> Result<Vec<MarketDataEvent>, AdapterError> {
        let mut events = vec![MarketDataEvent::BookSnapshot(OrderBookSnapshot {
            pair: self.pair.clone(),
            bids: to_levels(&snapshot.bids)?,
            asks: to_levels(&snapshot.asks)?,
            sequence: 0,
            ts,
        })];

        let last_update_id = snapshot.last_update_id;
        self.counter = 1;
        self.synced = true;
        self.last_seen_final_id = last_update_id;

        let buffered = std::mem::take(&mut self.buffer);
        let mut bridged = false;
        for raw in buffered {
            if raw.final_update_id <= last_update_id {
                continue;
            }
            if !bridged {
                if raw.first_update_id <= last_update_id + 1 {
                    bridged = true;
                    self.last_seen_final_id = raw.final_update_id;
                    events.push(MarketDataEvent::BookUpdate(self.to_update(raw)?));
                }
                continue;
            }
            if self.is_contiguous(&raw) {
                self.last_seen_final_id = raw.final_update_id;
                events.push(MarketDataEvent::BookUpdate(self.to_update(raw)?));
            } else {
                break;
            }
        }

        Ok(events)
    }
}
```

Note: `to_update` increments `self.counter` and reads `raw.event_time`, but no longer needs to separately track `last_seen_final_id` internally since callers (`on_event`, `resync`) set it explicitly before/after calling `to_update` — this keeps `to_update` a pure "turn this raw event into the next `OrderBookUpdate`" step without hidden double-bookkeeping.

- [ ] **Step 4: Run the tests, confirm they pass**

Run: `cargo test -p exchange_adapter_binance ws::tests`
Expected: all `DepthSync` tests (10 new + 9 from Task 1) pass.

- [ ] **Step 5: Commit**

```bash
git add crates/exchange_adapter_binance/src/ws.rs
git commit -m "feat(exchange_adapter_binance): add DepthSync snapshot-resync state machine"
```

---

## Task 4: `Backoff` — reconnect delay schedule

**Files:**
- Modify: `crates/exchange_adapter_binance/src/ws.rs`

**Interfaces:**
- Consumes: `std::time::Duration`.
- Produces (used by Tasks 6-7):
  - `pub(crate) struct Backoff` with:
    - `pub(crate) fn new(initial: Duration, max: Duration) -> Self`
    - `pub(crate) fn production() -> Self` (returns `Backoff::new(Duration::from_secs(1), Duration::from_secs(30))`)
    - `pub(crate) fn next_delay(&mut self) -> Duration`
    - `pub(crate) fn reset(&mut self)`

- [ ] **Step 1: Write the failing tests**

Add to `ws.rs`'s test module:

```rust
use std::time::Duration;

#[test]
fn backoff_doubles_each_call_up_to_the_cap() {
    let mut backoff = Backoff::new(Duration::from_secs(1), Duration::from_secs(30));
    assert_eq!(backoff.next_delay(), Duration::from_secs(1));
    assert_eq!(backoff.next_delay(), Duration::from_secs(2));
    assert_eq!(backoff.next_delay(), Duration::from_secs(4));
    assert_eq!(backoff.next_delay(), Duration::from_secs(8));
    assert_eq!(backoff.next_delay(), Duration::from_secs(16));
    assert_eq!(backoff.next_delay(), Duration::from_secs(30)); // capped, not 32
    assert_eq!(backoff.next_delay(), Duration::from_secs(30)); // stays capped
}

#[test]
fn reset_returns_to_the_initial_delay() {
    let mut backoff = Backoff::new(Duration::from_secs(1), Duration::from_secs(30));
    backoff.next_delay();
    backoff.next_delay();
    backoff.reset();
    assert_eq!(backoff.next_delay(), Duration::from_secs(1));
}

#[test]
fn production_uses_one_second_initial_and_thirty_second_cap() {
    let mut backoff = Backoff::production();
    assert_eq!(backoff.next_delay(), Duration::from_secs(1));
}
```

- [ ] **Step 2: Run the tests, confirm they fail to compile**

Run: `cargo test -p exchange_adapter_binance ws::tests`
Expected: FAIL — `Backoff` doesn't exist.

- [ ] **Step 3: Implement `Backoff`**

Add to `ws.rs`:

```rust
/// Exponential reconnect backoff, 1s -> 2s -> 4s ... capped at 30s,
/// reset to 1s once a connection has proven stable. Takes `initial`/`max`
/// as constructor arguments (rather than hardcoding them) specifically so
/// tests can inject a millisecond-scale schedule instead of waiting on
/// real reconnect timers -- see the design spec's "Reconnect policy".
#[derive(Debug, Clone, Copy)]
pub(crate) struct Backoff {
    initial: Duration,
    max: Duration,
    current: Duration,
}

impl Backoff {
    pub(crate) fn new(initial: Duration, max: Duration) -> Self {
        Self { initial, max, current: initial }
    }

    pub(crate) fn production() -> Self {
        Self::new(Duration::from_secs(1), Duration::from_secs(30))
    }

    pub(crate) fn next_delay(&mut self) -> Duration {
        let delay = self.current;
        self.current = (self.current * 2).min(self.max);
        delay
    }

    pub(crate) fn reset(&mut self) {
        self.current = self.initial;
    }
}
```

- [ ] **Step 4: Run the tests, confirm they pass**

Run: `cargo test -p exchange_adapter_binance ws::tests`
Expected: all pass (3 new + 19 previous = 22).

- [ ] **Step 5: Commit**

```bash
git add crates/exchange_adapter_binance/src/ws.rs
git commit -m "feat(exchange_adapter_binance): add Backoff reconnect delay schedule"
```

---

## Task 5: Fake local ws server test fixture

**Files:**
- Modify: `crates/exchange_adapter_binance/tests/wiremock_tests.rs`

**Interfaces:**
- Consumes: `tokio::net::TcpListener`, `tokio_tungstenite::{accept_async, tungstenite::Message}`.
- Produces (used by Tasks 6-8): `async fn spawn_fake_ws_server(connections: Vec<Vec<String>>) -> url::Url` — `connections[i]` is the list of JSON text frames sent to the i-th accepted connection, in order, before that connection is closed by the server. If more connections are attempted than `connections` has entries, the server closes them immediately with no frames (simulates "still down").

- [ ] **Step 1: Write the failing test**

Add near the top of `wiremock_tests.rs` (after the existing `build_adapter` helper), first the test, then the helper it calls:

```rust
#[tokio::test]
async fn fake_ws_server_sends_scripted_frames_in_order() {
    use futures_util::{SinkExt, StreamExt};

    let url = spawn_fake_ws_server(vec![vec![
        "first".to_string(),
        "second".to_string(),
    ]])
    .await;

    let (mut ws, _response) = tokio_tungstenite::connect_async(url.as_str()).await.unwrap();
    let first = ws.next().await.unwrap().unwrap();
    let second = ws.next().await.unwrap().unwrap();
    assert_eq!(first.into_text().unwrap(), "first");
    assert_eq!(second.into_text().unwrap(), "second");
    let _ = ws.close(None).await;
}
```

- [ ] **Step 2: Run it, confirm it fails to compile**

Run: `cargo test -p exchange_adapter_binance --test wiremock_tests fake_ws_server_sends_scripted_frames_in_order`
Expected: FAIL — `spawn_fake_ws_server` doesn't exist.

- [ ] **Step 3: Implement the fixture**

Add to `wiremock_tests.rs`:

```rust
/// A hand-rolled local websocket server for tests -- there's no
/// wiremock-for-ws in this workspace. Accepts connections one at a time
/// on an OS-assigned port; the i-th connection gets `connections[i]`'s
/// frames (as `Message::Text`) sent in order, then the server closes that
/// connection. Connections past the end of `connections` are closed
/// immediately with nothing sent, modeling "the exchange is still down"
/// for reconnect tests.
async fn spawn_fake_ws_server(connections: Vec<Vec<String>>) -> url::Url {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    tokio::spawn(async move {
        for frames in connections {
            let Ok((stream, _)) = listener.accept().await else { break };
            let Ok(mut ws) = tokio_tungstenite::accept_async(stream).await else { continue };
            for frame in frames {
                use futures_util::SinkExt;
                if ws.send(tokio_tungstenite::tungstenite::Message::text(frame)).await.is_err() {
                    break;
                }
            }
            let _ = ws.close(None).await;
        }
        // Once every scripted connection has been handled, this task
        // ends and `listener` drops -- any further connection attempt
        // gets an immediate refused-connection error, not a hang. No
        // test in this plan relies on that case; it's called out here so
        // it isn't a surprise if a future test adds one more reconnect
        // than it scripted for.
    });

    url::Url::parse(&format!("ws://{addr}")).unwrap()
}
```

- [ ] **Step 4: Run it, confirm it passes**

Run: `cargo test -p exchange_adapter_binance --test wiremock_tests fake_ws_server_sends_scripted_frames_in_order`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add crates/exchange_adapter_binance/tests/wiremock_tests.rs
git commit -m "test(exchange_adapter_binance): add fake local ws server fixture"
```

---

## Task 6: Trade ws task

**Files:**
- Modify: `crates/exchange_adapter_binance/src/ws.rs`
- Modify: `crates/exchange_adapter_binance/tests/wiremock_tests.rs`

**Interfaces:**
- Consumes: `RawTradeEvent`, `trade_tick_from_raw` (Task 1); `Backoff` (Task 4); `exchange_adapter::{MarketDataEvent, MarketDataStream, Pair}`; `observability::{Alerts, Metrics, AlertKind, AlertEvent, MetricEvent, Severity}`.
- Produces (used by Task 8): `pub fn trade_stream(ws_base_url: url::Url, pair: Pair, backoff: Backoff, metrics: Arc<dyn Metrics>, alerts: Arc<dyn Alerts>) -> MarketDataStream` (visibility corrected from the original `pub(crate)` -- see the `__test_support` note in Step 2 below)

- [ ] **Step 1: Write the failing test**

Add to `wiremock_tests.rs`:

```rust
#[tokio::test]
async fn trade_stream_emits_a_trade_event_from_a_ws_frame() {
    use futures_util::StreamExt;

    let ws_url = spawn_fake_ws_server(vec![vec![
        r#"{"e":"trade","E":1,"s":"BTCUSDT","t":42,"p":"100.5","q":"0.01","b":1,"a":2,"T":999,"m":false,"M":true}"#.to_string(),
    ]])
    .await;

    let metrics = Arc::new(RecordingMetrics::default());
    let alerts = Arc::new(RecordingAlerts::default());
    let mut stream = exchange_adapter_binance::__test_support::trade_stream(
        ws_url,
        Pair("BTCUSDT".to_string()),
        exchange_adapter_binance::__test_support::Backoff::new(
            std::time::Duration::from_millis(1),
            std::time::Duration::from_millis(5),
        ),
        metrics,
        alerts,
    );

    let event = tokio::time::timeout(std::time::Duration::from_secs(5), stream.next())
        .await
        .expect("trade should arrive before the timeout")
        .expect("stream should not end");
    match event {
        exchange_adapter::MarketDataEvent::Trade(trade) => {
            assert_eq!(trade.trade_id, exchange_adapter::TradeId(42));
            assert_eq!(trade.side, exchange_adapter::Side::Buy);
        }
        other => panic!("expected Trade, got {other:?}"),
    }
}

#[tokio::test]
async fn trade_stream_reconnects_after_a_dropped_connection() {
    use futures_util::StreamExt;

    // First connection sends nothing and is closed immediately (simulates
    // a drop); second connection sends a real trade.
    let ws_url = spawn_fake_ws_server(vec![
        vec![],
        vec![r#"{"e":"trade","E":1,"s":"BTCUSDT","t":7,"p":"1","q":"1","b":1,"a":2,"T":1,"m":true,"M":true}"#.to_string()],
    ])
    .await;

    let metrics = Arc::new(RecordingMetrics::default());
    let alerts = Arc::new(RecordingAlerts::default());
    let mut stream = exchange_adapter_binance::__test_support::trade_stream(
        ws_url,
        Pair("BTCUSDT".to_string()),
        exchange_adapter_binance::__test_support::Backoff::new(
            std::time::Duration::from_millis(1),
            std::time::Duration::from_millis(5),
        ),
        metrics,
        alerts,
    );

    let event = tokio::time::timeout(std::time::Duration::from_secs(5), stream.next())
        .await
        .expect("trade should arrive after reconnect")
        .expect("stream should not end");
    match event {
        exchange_adapter::MarketDataEvent::Trade(trade) => {
            assert_eq!(trade.trade_id, exchange_adapter::TradeId(7));
        }
        other => panic!("expected Trade, got {other:?}"),
    }
}
```

This introduces a need: `ws::trade_stream` and `ws::Backoff` are `pub(crate)` inside `exchange_adapter_binance`, but `tests/wiremock_tests.rs` is an external integration-test crate and can only see the crate's `pub` surface. Rather than making internal plumbing fully `pub` (which would leak it to every downstream consumer of this crate, not just tests), add a `#[doc(hidden)] pub mod __test_support` re-export, gated so it's clearly not part of the real API:

- [ ] **Step 2: Add the test-support re-export**

In `crates/exchange_adapter_binance/src/lib.rs`, after the existing `pub use` lines:

```rust
/// Re-exports internal ws plumbing for integration tests in `tests/`
/// only -- not part of this crate's real API. `#[doc(hidden)]` keeps it
/// out of generated docs; nothing outside this crate's own test suite
/// should ever import it.
#[doc(hidden)]
pub mod __test_support {
    pub use crate::ws::{trade_stream, Backoff};
}
```

**Correction made after Task 6 was implemented:** this needs `Backoff` (the struct and its `new` constructor) and `trade_stream` to be plain `pub`, not `pub(crate)` as Step 4 below originally specified. Rust's E0365 forbids re-exporting a `pub(crate)` item as `pub`, even via a `pub use` inside the same crate that defines it -- an item's own visibility must be at least as permissive as any re-export of it. `Backoff::production`/`next_delay`/`reset` stay `pub(crate)` (nothing outside the crate needs them). Keep `mod ws;` itself private (not `pub mod ws;`) in `lib.rs` -- that's what actually keeps `trade_stream`/`Backoff` off this crate's real public API surface; the only path to them from outside the crate is this explicit, `#[doc(hidden)]` `__test_support` re-export. Apply the same `pub` promotion to Step 4's `trade_stream` below.

- [ ] **Step 3: Run the tests, confirm they fail to compile**

Run: `cargo test -p exchange_adapter_binance --test wiremock_tests trade_stream`
Expected: FAIL — `ws::trade_stream` doesn't exist yet.

- [ ] **Step 4: Implement `trade_stream`**

Add to `ws.rs`:

```rust
use std::sync::Arc;

use exchange_adapter::{MarketDataStream, Pair};
use observability::{AlertEvent, AlertKind, Alerts, MetricEvent, Metrics, Severity};

/// After this many consecutive failed reconnect attempts, fire
/// `AlertKind::FeedDisconnected` -- a single dropped connection that
/// immediately reconnects is normal and not alert-worthy on its own.
const CONSECUTIVE_FAILURES_BEFORE_ALERT: u32 = 5;

fn trade_stream_url(ws_base_url: &url::Url, pair: &Pair) -> url::Url {
    ws_base_url
        .join(&format!("/ws/{}@trade", pair.0.to_lowercase()))
        .expect("pair symbol never contains URL-breaking characters")
}

pub fn trade_stream(
    ws_base_url: url::Url,
    pair: Pair,
    mut backoff: Backoff,
    metrics: Arc<dyn Metrics>,
    alerts: Arc<dyn Alerts>,
) -> MarketDataStream {
    Box::pin(async_stream::stream! {
        let mut consecutive_failures: u32 = 0;
        loop {
            let url = trade_stream_url(&ws_base_url, &pair);
            let mut ws = match tokio_tungstenite::connect_async(url.as_str()).await {
                Ok((ws, _response)) => ws,
                Err(e) => {
                    consecutive_failures += 1;
                    record_ws_failure(&metrics, &alerts, "trade", consecutive_failures, &e.to_string());
                    tokio::time::sleep(backoff.next_delay()).await;
                    continue;
                }
            };

            let connected_at = tokio::time::Instant::now();
            loop {
                use futures_util::StreamExt;
                match ws.next().await {
                    Some(Ok(message)) => {
                        let Ok(text) = message.into_text() else { continue };
                        let Ok(raw) = serde_json::from_str::<RawTradeEvent>(&text) else { continue };
                        if let Ok(tick) = trade_tick_from_raw(&pair, raw) {
                            yield MarketDataEvent::Trade(tick);
                        }
                    }
                    Some(Err(_)) | None => break,
                }
            }

            if connected_at.elapsed() >= STABLE_CONNECTION_THRESHOLD {
                consecutive_failures = 0;
                backoff.reset();
            } else {
                consecutive_failures += 1;
                record_ws_failure(&metrics, &alerts, "trade", consecutive_failures, "connection dropped shortly after connecting");
            }
            tokio::time::sleep(backoff.next_delay()).await;
        }
    })
}
```

**Corrected after task review found a bug (see the plan's execution ledger, Task 6):** the original draft above reset `consecutive_failures`/`backoff` unconditionally on every successful `connect_async`, before the connection had proven it would stay up. That let a "connects fine, then drops immediately" flapping pattern evade both the alert threshold and the exponential backoff, since each cycle reset the counters right back to zero before the drop was even noticed. The version above only resets after `elapsed() >= STABLE_CONNECTION_THRESHOLD`; a quick drop counts as a failure exactly like a failed connect does. `trade_stream` and `Backoff` (struct + `new`) are `pub`, not `pub(crate)`, per the `__test_support` visibility correction above (Step 2) -- Rust forbids re-exporting a `pub(crate)` item as `pub` even from within the same crate.

```rust

/// How long a connection must stay up before a subsequent drop resets
/// backoff to its initial delay, per the design spec's "Reconnect
/// policy" ("reset to 1s after a stretch of stable connection").
const STABLE_CONNECTION_THRESHOLD: Duration = Duration::from_secs(60);

fn record_ws_failure(
    metrics: &Arc<dyn Metrics>,
    alerts: &Arc<dyn Alerts>,
    stream_tag: &'static str,
    consecutive_failures: u32,
    message: &str,
) {
    metrics.record(
        MetricEvent::new("binance_ws_reconnect_error_count", 1.0).with_tag("stream", stream_tag),
    );
    if consecutive_failures >= CONSECUTIVE_FAILURES_BEFORE_ALERT {
        alerts.fire(
            AlertEvent::new(
                AlertKind::FeedDisconnected,
                Severity::Warn,
                format!("{stream_tag} ws reconnect failing repeatedly: {message}"),
            )
            .with_tag("stream", stream_tag),
        );
    }
}
```

Add `use exchange_adapter::MarketDataEvent;` if not already imported at the top of `ws.rs` from Task 3 (it already is).

- [ ] **Step 5: Run the tests, confirm they pass**

Run: `cargo test -p exchange_adapter_binance --test wiremock_tests trade_stream`
Expected: both tests pass. The reconnect test's first (empty) connection closes instantly, backoff's 1ms initial delay fires, second connection delivers the trade -- should complete in well under a second.

- [ ] **Step 6: Run the whole crate's tests to confirm nothing regressed**

Run: `cargo test -p exchange_adapter_binance`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add crates/exchange_adapter_binance/src/ws.rs crates/exchange_adapter_binance/src/lib.rs crates/exchange_adapter_binance/tests/wiremock_tests.rs
git commit -m "feat(exchange_adapter_binance): add trade_stream ws task with reconnect backoff"
```

---

## Task 7: Book-diff ws task

**Files:**
- Modify: `crates/exchange_adapter_binance/src/ws.rs`
- Modify: `crates/exchange_adapter_binance/src/lib.rs` (extend `__test_support`)
- Modify: `crates/exchange_adapter_binance/tests/wiremock_tests.rs`

**Interfaces:**
- Consumes: `DepthSync`, `DepthSyncOutcome`, `RawDepthEvent`, `DepthSnapshotResponse`, `Backoff` (Tasks 1/3/4); `crate::rest::BinanceRestClient`; `crate::kind::MarketKind`.
- Produces (used by Task 8): `pub fn book_stream(ws_base_url: url::Url, rest: BinanceRestClient, kind: MarketKind, pair: Pair, backoff: Backoff, metrics: Arc<dyn Metrics>, alerts: Arc<dyn Alerts>) -> MarketDataStream` (visibility corrected from the original `pub(crate)` -- see the `__test_support` visibility note in Step 2 below)

- [ ] **Step 1: Write the failing tests**

Add to `wiremock_tests.rs`. These need both a REST mock (for the snapshot fetch) and the fake ws server:

```rust
#[tokio::test]
async fn book_stream_happy_path_emits_snapshot_then_sequential_updates() {
    use futures_util::StreamExt;

    let rest_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/api/v3/depth"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "lastUpdateId": 160,
            "bids": [["99", "1"]],
            "asks": [["101", "1"]]
        })))
        .mount(&rest_server)
        .await;

    let ws_url = spawn_fake_ws_server(vec![vec![
        r#"{"e":"depthUpdate","E":1,"s":"BTCUSDT","U":161,"u":165,"b":[["99","2"]],"a":[]}"#.to_string(),
        r#"{"e":"depthUpdate","E":2,"s":"BTCUSDT","U":166,"u":170,"b":[["99","3"]],"a":[]}"#.to_string(),
    ]])
    .await;

    let (rest, _alerts, _metrics) = test_rest_client(&rest_server.uri());
    let metrics = Arc::new(RecordingMetrics::default());
    let alerts = Arc::new(RecordingAlerts::default());
    let mut stream = exchange_adapter_binance::__test_support::book_stream(
        ws_url,
        rest,
        exchange_adapter_binance::__test_support::MarketKindForTests::Spot,
        Pair("BTCUSDT".to_string()),
        exchange_adapter_binance::__test_support::Backoff::new(
            std::time::Duration::from_millis(1),
            std::time::Duration::from_millis(5),
        ),
        metrics,
        alerts,
    );

    let first = tokio::time::timeout(std::time::Duration::from_secs(5), stream.next())
        .await.unwrap().unwrap();
    let second = tokio::time::timeout(std::time::Duration::from_secs(5), stream.next())
        .await.unwrap().unwrap();
    let third = tokio::time::timeout(std::time::Duration::from_secs(5), stream.next())
        .await.unwrap().unwrap();

    match first {
        exchange_adapter::MarketDataEvent::BookSnapshot(s) => assert_eq!(s.sequence, 0),
        other => panic!("expected BookSnapshot, got {other:?}"),
    }
    match second {
        exchange_adapter::MarketDataEvent::BookUpdate(u) => assert_eq!(u.sequence, 1),
        other => panic!("expected BookUpdate, got {other:?}"),
    }
    match third {
        exchange_adapter::MarketDataEvent::BookUpdate(u) => assert_eq!(u.sequence, 2),
        other => panic!("expected BookUpdate, got {other:?}"),
    }
}

#[tokio::test]
async fn book_stream_resyncs_with_a_fresh_snapshot_on_desync() {
    use futures_util::StreamExt;

    let rest_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/api/v3/depth"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "lastUpdateId": 160, "bids": [["99", "1"]], "asks": []
        })))
        .mount(&rest_server)
        .await;

    let ws_url = spawn_fake_ws_server(vec![vec![
        r#"{"e":"depthUpdate","E":1,"s":"BTCUSDT","U":161,"u":165,"b":[["99","2"]],"a":[]}"#.to_string(),
        // Gap: next U should be 166, this is 500 -- triggers a resync.
        r#"{"e":"depthUpdate","E":2,"s":"BTCUSDT","U":500,"u":505,"b":[["99","4"]],"a":[]}"#.to_string(),
    ]])
    .await;

    let (rest, _alerts, _metrics) = test_rest_client(&rest_server.uri());
    let metrics = Arc::new(RecordingMetrics::default());
    let alerts = Arc::new(RecordingAlerts::default());
    let mut stream = exchange_adapter_binance::__test_support::book_stream(
        ws_url,
        rest,
        exchange_adapter_binance::__test_support::MarketKindForTests::Spot,
        Pair("BTCUSDT".to_string()),
        exchange_adapter_binance::__test_support::Backoff::new(
            std::time::Duration::from_millis(1),
            std::time::Duration::from_millis(5),
        ),
        metrics,
        alerts,
    );

    // snapshot(seq=0), update(seq=1) from the first depth event.
    let _snapshot = tokio::time::timeout(std::time::Duration::from_secs(5), stream.next()).await.unwrap().unwrap();
    let _update = tokio::time::timeout(std::time::Duration::from_secs(5), stream.next()).await.unwrap().unwrap();
    // The gap event triggers a resync: REST snapshot is refetched (same
    // mock, still lastUpdateId=160) and a fresh BookSnapshot re-emitted.
    let after_gap = tokio::time::timeout(std::time::Duration::from_secs(5), stream.next())
        .await.unwrap().unwrap();
    match after_gap {
        exchange_adapter::MarketDataEvent::BookSnapshot(s) => assert_eq!(s.sequence, 0),
        other => panic!("expected a fresh BookSnapshot after the gap, got {other:?}"),
    }
}

#[tokio::test]
async fn book_stream_resyncs_after_a_ws_disconnect() {
    use futures_util::StreamExt;

    let rest_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/api/v3/depth"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "lastUpdateId": 160, "bids": [["99", "1"]], "asks": []
        })))
        .mount(&rest_server)
        .await;

    // First connection: one update, then closed (a drop). Second
    // connection: another update -- proves the stream survives the drop
    // and resyncs (fresh BookSnapshot) rather than stalling.
    let ws_url = spawn_fake_ws_server(vec![
        vec![r#"{"e":"depthUpdate","E":1,"s":"BTCUSDT","U":161,"u":165,"b":[["99","2"]],"a":[]}"#.to_string()],
        vec![r#"{"e":"depthUpdate","E":2,"s":"BTCUSDT","U":161,"u":165,"b":[["99","5"]],"a":[]}"#.to_string()],
    ])
    .await;

    let (rest, _alerts, _metrics) = test_rest_client(&rest_server.uri());
    let metrics = Arc::new(RecordingMetrics::default());
    let alerts = Arc::new(RecordingAlerts::default());
    let mut stream = exchange_adapter_binance::__test_support::book_stream(
        ws_url,
        rest,
        exchange_adapter_binance::__test_support::MarketKindForTests::Spot,
        Pair("BTCUSDT".to_string()),
        exchange_adapter_binance::__test_support::Backoff::new(
            std::time::Duration::from_millis(1),
            std::time::Duration::from_millis(5),
        ),
        metrics,
        alerts,
    );

    let mut snapshot_count = 0;
    for _ in 0..4 {
        let event = tokio::time::timeout(std::time::Duration::from_secs(5), stream.next())
            .await.unwrap().unwrap();
        if matches!(event, exchange_adapter::MarketDataEvent::BookSnapshot(_)) {
            snapshot_count += 1;
        }
    }
    assert_eq!(snapshot_count, 2, "expected one snapshot for the initial sync and one for the post-disconnect resync");
}

#[tokio::test]
async fn book_stream_records_a_failure_metric_for_quick_drops_despite_each_connection_delivering_data() {
    use futures_util::StreamExt;

    let rest_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/api/v3/depth"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "lastUpdateId": 160, "bids": [["99", "1"]], "asks": []
        })))
        .mount(&rest_server)
        .await;

    // Three connections, each delivers one update then closes immediately
    // -- every connection technically "succeeds" but none is stable.
    // Proves the reconnect loop still records a failure per cycle instead
    // of resetting on bare connect success (the bug found and fixed in
    // Task 6's trade_stream, applied here before book_stream is built).
    let ws_url = spawn_fake_ws_server(vec![
        vec![r#"{"e":"depthUpdate","E":1,"s":"BTCUSDT","U":161,"u":165,"b":[["99","2"]],"a":[]}"#.to_string()],
        vec![r#"{"e":"depthUpdate","E":2,"s":"BTCUSDT","U":161,"u":165,"b":[["99","3"]],"a":[]}"#.to_string()],
        vec![r#"{"e":"depthUpdate","E":3,"s":"BTCUSDT","U":161,"u":165,"b":[["99","4"]],"a":[]}"#.to_string()],
    ])
    .await;

    let (rest, _alerts, _metrics) = test_rest_client(&rest_server.uri());
    let metrics = Arc::new(RecordingMetrics::default());
    let alerts = Arc::new(RecordingAlerts::default());
    let mut stream = exchange_adapter_binance::__test_support::book_stream(
        ws_url,
        rest,
        exchange_adapter_binance::__test_support::MarketKindForTests::Spot,
        Pair("BTCUSDT".to_string()),
        exchange_adapter_binance::__test_support::Backoff::new(
            std::time::Duration::from_millis(1),
            std::time::Duration::from_millis(5),
        ),
        metrics.clone(),
        alerts,
    );

    // Each of the 3 connection cycles yields a BookSnapshot + one
    // BookUpdate -- drain all 6 events across all three cycles.
    for _ in 0..6 {
        let _ = tokio::time::timeout(std::time::Duration::from_secs(5), stream.next())
            .await
            .expect("event should arrive before the timeout")
            .expect("stream should not end");
    }

    let recorded = metrics.events.lock().unwrap();
    let failure_count = recorded
        .iter()
        .filter(|e| e.name == "binance_ws_reconnect_error_count")
        .count();
    assert!(
        failure_count >= 2,
        "expected at least 2 recorded failures for the quick-drop cycles after the first, got {failure_count}"
    );
}
```

This test file needs a `test_rest_client` helper that builds a bare `BinanceRestClient` pointed at the mock REST server (the existing `build_adapter` helper builds a whole `ExchangeAdapterBinance`, which is more than needed here and doesn't expose the inner `BinanceRestClient`). Add:

```rust
fn test_rest_client(mock_uri: &str) -> (exchange_adapter_binance::__test_support::BinanceRestClient, Arc<RecordingAlerts>, Arc<RecordingMetrics>) {
    let alerts = Arc::new(RecordingAlerts::default());
    let metrics = Arc::new(RecordingMetrics::default());
    let rest = exchange_adapter_binance::__test_support::BinanceRestClient::new(
        Url::parse(mock_uri).unwrap(),
        "test-api-key".to_string(),
        Arc::new(SecretString::from("test-api-secret".to_string())),
        5000,
        metrics.clone(),
        alerts.clone(),
        "spot",
    )
    .unwrap();
    (rest, alerts, metrics)
}
```

This also needs `BinanceRestClient` and `MarketKind` reachable through `__test_support` — `MarketKind` specifically needs a stable name tests can reference without the test crate needing to import `crate::kind::MarketKind` directly (it can't; that's private). Re-export both.

**Visibility, corrected per the same rule that applied to Task 6's `trade_stream`/`Backoff`:** Rust forbids re-exporting a `pub(crate)` item as `pub`, even from within the defining crate (E0365). So promote to plain `pub`, in `src/kind.rs`: the `MarketKind` enum itself (its `Spot`/`Margin`/`Futures` variants automatically follow, no separate change needed) and its `endpoints()`/`tag()` methods stay `pub(crate)` unless a test needs to call them directly (it doesn't — tests only need to *construct* a `MarketKind` value, per the `MarketKindForTests::Spot` usage in this task's tests); in `src/rest.rs`: the `BinanceRestClient` struct and its `new` constructor. Its other methods (`public`, `signed`) stay `pub(crate)` — nothing outside the crate calls them directly, `book_stream`/`trade_stream` do that internally. Keep `mod kind;` and `mod rest;` themselves private in `lib.rs`, same reasoning as `mod ws;` — the promoted items are still unreachable except through the explicit `__test_support` re-export.

- [ ] **Step 2: Extend `__test_support`**

In `crates/exchange_adapter_binance/src/lib.rs`:

```rust
#[doc(hidden)]
pub mod __test_support {
    pub use crate::kind::MarketKind as MarketKindForTests;
    pub use crate::rest::BinanceRestClient;
    pub use crate::ws::{book_stream, trade_stream, Backoff};
}
```

(Replaces the narrower `__test_support` module added in Task 6, Step 2 -- same module, now re-exporting more.)

- [ ] **Step 3: Run the new tests, confirm they fail to compile**

Run: `cargo test -p exchange_adapter_binance --test wiremock_tests book_stream`
Expected: FAIL — `ws::book_stream` doesn't exist yet, `BinanceRestClient`/`MarketKind` not yet re-exported for tests.

- [ ] **Step 4: Implement `book_stream`**

Add to `ws.rs`:

```rust
use reqwest::Method;

use crate::kind::MarketKind;
use crate::rest::BinanceRestClient;

async fn fetch_depth_snapshot(
    rest: &BinanceRestClient,
    kind: MarketKind,
    pair: &Pair,
) -> Result<DepthSnapshotResponse, AdapterError> {
    let path = kind.endpoints().depth;
    let params = vec![("symbol".to_string(), pair.0.clone()), ("limit".to_string(), "1000".to_string())];
    let value = rest.public(Method::GET, path, params, Some(AlertKind::FeedStale)).await?;
    serde_json::from_value(value)
        .map_err(|e| AdapterError::InvalidRequest(format!("bad depth snapshot response: {e}")))
}

fn book_stream_url(ws_base_url: &url::Url, pair: &Pair) -> url::Url {
    ws_base_url
        .join(&format!("/ws/{}@depth", pair.0.to_lowercase()))
        .expect("pair symbol never contains URL-breaking characters")
}

pub fn book_stream(
    ws_base_url: url::Url,
    rest: BinanceRestClient,
    kind: MarketKind,
    pair: Pair,
    mut backoff: Backoff,
    metrics: Arc<dyn Metrics>,
    alerts: Arc<dyn Alerts>,
) -> MarketDataStream {
    Box::pin(async_stream::stream! {
        let mut sync = DepthSync::new(pair.clone());
        let mut consecutive_failures: u32 = 0;

        loop {
            let url = book_stream_url(&ws_base_url, &pair);
            let mut ws = match tokio_tungstenite::connect_async(url.as_str()).await {
                Ok((ws, _response)) => ws,
                Err(e) => {
                    consecutive_failures += 1;
                    record_ws_failure(&metrics, &alerts, "book", consecutive_failures, &e.to_string());
                    tokio::time::sleep(backoff.next_delay()).await;
                    continue;
                }
            };
            sync.mark_disconnected();

            // Fetch the sync snapshot only after the ws connection is
            // open, per Binance's documented procedure (buffer ws events
            // while the REST call is in flight, then resync against
            // whatever arrived).
            match fetch_depth_snapshot(&rest, kind, &pair).await {
                Ok(snapshot) => match sync.resync(snapshot, Ts(exchange_adapter::now_ms())) {
                    Ok(events) => for event in events {
                        yield event;
                    },
                    Err(_) => {
                        consecutive_failures += 1;
                        record_ws_failure(&metrics, &alerts, "book", consecutive_failures, "snapshot conversion failed");
                        tokio::time::sleep(backoff.next_delay()).await;
                        continue;
                    }
                },
                Err(_) => {
                    consecutive_failures += 1;
                    record_ws_failure(&metrics, &alerts, "book", consecutive_failures, "snapshot fetch failed");
                    tokio::time::sleep(backoff.next_delay()).await;
                    continue;
                }
            }

            let connected_at = tokio::time::Instant::now();
            let mut desynced = false;
            loop {
                use futures_util::StreamExt;
                match ws.next().await {
                    Some(Ok(message)) => {
                        let Ok(text) = message.into_text() else { continue };
                        let Ok(raw) = serde_json::from_str::<RawDepthEvent>(&text) else { continue };
                        match sync.on_event(raw) {
                            DepthSyncOutcome::Update(update) => yield MarketDataEvent::BookUpdate(update),
                            DepthSyncOutcome::Buffering => {}
                            DepthSyncOutcome::Desynced => {
                                desynced = true;
                                break;
                            }
                        }
                    }
                    Some(Err(_)) | None => break,
                }
            }

            if desynced {
                // Fast in-band resync, not a reconnect failure -- doesn't
                // touch consecutive_failures/backoff at all, and loops
                // back immediately with no sleep. The ws connection
                // itself is still alive/valid at the point of desync;
                // Binance's real desync case is rare enough that paying
                // for a fresh connection on the next loop iteration is an
                // acceptable cost for keeping this one control-flow path
                // simple rather than plumbing a separate
                // resync-without-reconnecting branch.
                continue;
            }

            // The connection delivered zero or more updates, then ended
            // (dropped by the peer, or a read error) without ever
            // desyncing. Only count this as *not* a failure if it stayed
            // up long enough to call genuinely stable -- a connection
            // that connects, fetches its snapshot, delivers one update,
            // and immediately dies is still a failure worth backing off
            // and alerting on, even though every step up to the drop
            // technically "succeeded". Resetting consecutive_failures/
            // backoff on bare connect success (instead of on proven
            // stability) would let exactly this flapping pattern evade
            // both the alert threshold and the backoff schedule, since
            // each cycle would reset the counters right before the next
            // drop.
            if connected_at.elapsed() >= STABLE_CONNECTION_THRESHOLD {
                consecutive_failures = 0;
                backoff.reset();
            } else {
                consecutive_failures += 1;
                record_ws_failure(&metrics, &alerts, "book", consecutive_failures, "connection dropped shortly after connecting");
            }
            tokio::time::sleep(backoff.next_delay()).await;
        }
    })
}
```

Note the desync path re-enters the outer `loop` which reconnects the ws too (not just refetches the snapshot) -- simpler than plumbing a separate "resync without reconnecting" inner loop, and Binance's real desync case is rare enough that paying for a fresh connection is an acceptable cost for the simplicity. Update the doc comment on `DepthSync::resync` if this changes its "no sleep on desync" framing -- it doesn't; leave as-is.

**Why this shape (fixed during planning, not left for review to catch):** an earlier draft of this function reset `consecutive_failures`/`backoff` unconditionally on every successful `connect_async`, regardless of how long the connection then lived. That has the same defect `trade_stream` (Task 6) was found to have and had fixed by review: a "connects fine, then drops immediately" flapping pattern would silently evade both the alert threshold and the exponential backoff, since each cycle resets the counters right back to zero before the drop is even noticed. This version only resets after a connection proves stable (`elapsed() >= STABLE_CONNECTION_THRESHOLD`); every other exit path (failed connect, failed snapshot fetch/conversion, or a quick drop) increments `consecutive_failures` and calls `record_ws_failure` uniformly. The desync path stays exempt from this bookkeeping entirely, per its own comment above -- it's not a connection failure, it's routine protocol behavior handled in-band.

- [ ] **Step 5: Implement the `test_rest_client` helper and run the tests**

Add `test_rest_client` (shown above) to `wiremock_tests.rs`.

Run: `cargo test -p exchange_adapter_binance --test wiremock_tests book_stream`
Expected: all 4 tests pass.

- [ ] **Step 6: Run the whole crate's tests**

Run: `cargo test -p exchange_adapter_binance`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add crates/exchange_adapter_binance/src/ws.rs crates/exchange_adapter_binance/src/lib.rs crates/exchange_adapter_binance/tests/wiremock_tests.rs
git commit -m "feat(exchange_adapter_binance): add book_stream ws task with snapshot resync"
```

---

## Task 8: Wire ws streams into `subscribe_market_data`

**Files:**
- Modify: `crates/exchange_adapter_binance/src/adapter.rs`
- Modify: `crates/exchange_adapter_binance/src/market.rs`
- Modify: `crates/exchange_adapter_binance/tests/wiremock_tests.rs`

**Interfaces:**
- Consumes: `ws::book_stream`, `ws::trade_stream`, `ws::Backoff` (Tasks 6-7); `futures_util::stream::select`.
- Produces: `BinanceMarketAccount::new` gains two parameters (`ws_base_url: Url`, `metrics: Arc<dyn Metrics>`, `alerts: Arc<dyn Alerts>` — three, not two; see Step 1) — this is a breaking change to a `pub(crate)` constructor, so every call site in this crate must be updated in the same task.

- [ ] **Step 1: Update `BinanceMarketAccount`'s fields and constructor**

In `market.rs`, add three fields to `BinanceMarketAccount`:

```rust
pub struct BinanceMarketAccount {
    kind: MarketKind,
    rest: BinanceRestClient,
    ws_base_url: Url,
    metrics: Arc<dyn Metrics>,
    alerts: Arc<dyn Alerts>,
    market_data_poll_interval: Duration,
    account_poll_interval: Duration,
    order_symbols: Arc<Mutex<HashMap<u64, String>>>,
}
```

Update `BinanceMarketAccount::new`:

```rust
pub(crate) fn new(
    kind: MarketKind,
    rest: BinanceRestClient,
    ws_base_url: Url,
    metrics: Arc<dyn Metrics>,
    alerts: Arc<dyn Alerts>,
    market_data_poll_interval: Duration,
    account_poll_interval: Duration,
) -> Self {
    Self {
        kind,
        rest,
        ws_base_url,
        metrics,
        alerts,
        market_data_poll_interval,
        account_poll_interval,
        order_symbols: Arc::new(Mutex::new(HashMap::new())),
    }
}
```

Add imports at the top of `market.rs`: `use url::Url;` and `use observability::{Alerts, Metrics};` (the latter may already be imported for `AlertKind` — check; if so, extend that `use` line rather than duplicating it) and `use crate::ws;`.

- [ ] **Step 2: Rewrite `subscribe_market_data`**

Replace the current body in `market.rs`:

```rust
async fn subscribe_market_data(&self, pair: Pair) -> Result<MarketDataStream, AdapterError> {
    let rest = self.rest.clone();
    let path = self.kind.endpoints().klines;
    let interval = tokio::time::interval(self.market_data_poll_interval);
    let candles = IntervalStream::new(interval).filter_map(move |_tick| {
        let rest = rest.clone();
        let pair = pair.clone();
        async move { fetch_latest_candle(&rest, path, &pair).await.ok().map(MarketDataEvent::Candle) }
    });

    let book = ws::book_stream(
        self.ws_base_url.clone(),
        self.rest.clone(),
        self.kind,
        pair.clone(),
        ws::Backoff::production(),
        self.metrics.clone(),
        self.alerts.clone(),
    );
    let trade = ws::trade_stream(
        self.ws_base_url.clone(),
        pair.clone(),
        ws::Backoff::production(),
        self.metrics.clone(),
        self.alerts.clone(),
    );

    Ok(Box::pin(stream::select(stream::select(book, trade), Box::pin(candles))))
}
```

Update the doc comment above it (currently says "Real websocket order-book/trade streaming ... is a known gap, not built in this crate yet -- see `NOTES.md`") to reflect that this is now built:

```rust
/// Merges three independent sources into one stream: a book-diff ws task
/// and a trade ws task (both new -- see
/// `external/executor/specs/2026-09-05-binance-market-data-websocket-design.md`),
/// plus the pre-existing REST kline-poll task for `Candle`. Each source
/// manages its own reconnect independently.
```

`stream::select` requires both operands to have the same `Item` type (`MarketDataEvent`) and be `Unpin` -- `book`/`trade` are already `MarketDataStream = Pin<Box<dyn Stream<...>>>`, which is `Unpin`; `candles` is a bare `impl Stream` from `filter_map`, not boxed/pinned, so it needs `Box::pin(candles)` before it can be passed to `stream::select` alongside the other two (shown above).

- [ ] **Step 3: Update `adapter.rs`'s three construction sites**

In `adapter.rs`, the config destructure currently discards `futures_ws_base_url`/`ws_base_url`:

```rust
let BinanceAdapterConfig {
    base,
    futures_rest_base_url,
    futures_ws_base_url: _futures_ws_base_url,
    recv_window_ms,
    market_data_poll_interval,
    account_poll_interval,
} = config;
let AdapterConfig {
    api_key,
    api_secret,
    rest_base_url,
    ws_base_url: _ws_base_url,
    extra: _extra,
} = base;
```

Change both to stop discarding them:

```rust
let BinanceAdapterConfig {
    base,
    futures_rest_base_url,
    futures_ws_base_url,
    recv_window_ms,
    market_data_poll_interval,
    account_poll_interval,
} = config;
let AdapterConfig {
    api_key,
    api_secret,
    rest_base_url,
    ws_base_url,
    extra: _extra,
} = base;
```

Update each of the three `BinanceMarketAccount::new` call sites to pass the right ws url (spot/margin share `ws_base_url`, futures uses `futures_ws_base_url`) and `metrics`/`alerts`. `metrics`/`alerts` are already `Arc`-cloned per kind for the REST clients right above each call site -- clone them once more for the ws url pass-through:

```rust
Ok(Self {
    spot: BinanceMarketAccount::new(
        MarketKind::Spot,
        spot_rest,
        ws_base_url.clone(),
        metrics.clone(),
        alerts.clone(),
        market_data_poll_interval,
        account_poll_interval,
    ),
    margin: BinanceMarketAccount::new(
        MarketKind::Margin,
        margin_rest,
        ws_base_url,
        metrics.clone(),
        alerts.clone(),
        market_data_poll_interval,
        account_poll_interval,
    ),
    futures: BinanceMarketAccount::new(
        MarketKind::Futures,
        futures_rest,
        futures_ws_base_url,
        metrics,
        alerts,
        market_data_poll_interval,
        account_poll_interval,
    ),
})
```

This requires `metrics`/`alerts` (the `Arc<dyn Metrics>`/`Arc<dyn Alerts>` parameters of `ExchangeAdapterBinance::new`) to still be in scope with at least one more clone available at this point in the function -- check the existing REST-client construction block just above: `spot_rest`/`margin_rest` each `.clone()` metrics/alerts already, and `futures_rest` takes them by value (last use) currently. Since `futures_rest`'s construction now is no longer the last use of `metrics`/`alerts` (the `futures: BinanceMarketAccount::new(...)` call below also needs them), change the `futures_rest` construction call to `.clone()` them too, moving the final by-value use to the last `BinanceMarketAccount::new(..., metrics, alerts, ...)` call for futures shown above.

- [ ] **Step 4: Fix the compile errors this ripples out to**

Run: `cargo build -p exchange_adapter_binance 2>&1 | head -100`

Expected failures and fixes:
- Any other `BinanceMarketAccount::new(...)` call site missing the new params (there should be exactly the three in `adapter.rs`, already fixed in Step 3) -- if `cargo build` finds more (e.g. in a test file constructing `BinanceMarketAccount` directly, unlikely given `pub(crate)` visibility keeps it out of `tests/`), fix them the same way.
- `metrics`/`alerts` move-after-use errors in `adapter.rs` if Step 3's clone placement was missed anywhere -- add the missing `.clone()`.

Keep iterating `cargo build -p exchange_adapter_binance` until clean.

- [ ] **Step 5: Write the end-to-end integration test**

Add to `wiremock_tests.rs` -- this is the one place all three market-data sources (book ws, trade ws, candle REST poll) are proven to arrive on a single `subscribe_market_data` stream through the real `ExchangeAdapterBinance` construction path, not the `__test_support` internals used in Tasks 6-7:

```rust
#[tokio::test]
async fn subscribe_market_data_merges_book_trade_and_candle_events() {
    use futures_util::StreamExt;

    let rest_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/api/v3/depth"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "lastUpdateId": 1, "bids": [], "asks": []
        })))
        .mount(&rest_server)
        .await;
    Mock::given(method("GET"))
        .and(path("/api/v3/klines"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!([[
            1_499_040_000_000_u64, "0.0163", "0.80", "0.0157", "0.0158",
            "148976.11", 1_499_644_799_999_u64, "2434.19", 308, "1756.87",
            "28.46", "17928899.62"
        ]])))
        .mount(&rest_server)
        .await;

    let ws_url = spawn_fake_ws_server(vec![vec![
        r#"{"e":"trade","E":1,"s":"BTCUSDT","t":1,"p":"1","q":"1","b":1,"a":2,"T":1,"m":false,"M":true}"#.to_string(),
    ]])
    .await;

    let mut extra = HashMap::new();
    extra.insert("market_data_poll_interval_ms".to_string(), "10".to_string());
    let mut config = base_config(&rest_server.uri(), extra);
    config.ws_base_url = ws_url;
    let adapter_config = BinanceAdapterConfig::new(config).unwrap();
    let alerts = Arc::new(RecordingAlerts::default());
    let metrics = Arc::new(RecordingMetrics::default());
    let adapter = ExchangeAdapterBinance::new(adapter_config, metrics, alerts).unwrap();

    let mut stream = adapter
        .spot()
        .unwrap()
        .subscribe_market_data(Pair("BTCUSDT".to_string()))
        .await
        .unwrap();

    let mut seen = std::collections::HashSet::new();
    for _ in 0..3 {
        let event = tokio::time::timeout(std::time::Duration::from_secs(5), stream.next())
            .await
            .expect("an event should arrive before the timeout")
            .expect("stream should not end");
        match event {
            exchange_adapter::MarketDataEvent::BookSnapshot(_) => { seen.insert("snapshot"); }
            exchange_adapter::MarketDataEvent::Trade(_) => { seen.insert("trade"); }
            exchange_adapter::MarketDataEvent::Candle(_) => { seen.insert("candle"); }
            other => panic!("unexpected event: {other:?}"),
        }
    }
    assert_eq!(seen.len(), 3, "expected one each of snapshot/trade/candle, got {seen:?}");
}
```

Note this test constructs `BinanceAdapterConfig` directly via `base_config(...)` + a `ws_base_url` override, rather than going through `extra` (unlike `futures_rest_base_url`, `ws_base_url` is a direct `AdapterConfig` field, not sourced from `extra` -- see `config.rs`).

- [ ] **Step 6: Run it, confirm it fails first (sanity-check the test is real), then passes**

Run: `cargo test -p exchange_adapter_binance --test wiremock_tests subscribe_market_data_merges_book_trade_and_candle_events`

If this is written after Steps 1-4 are already done (which it is, per this task's ordering), it should pass immediately -- there's no separate RED checkpoint for it since the code it exercises was already built in earlier steps. Confirm it passes:
Expected: PASS.

- [ ] **Step 7: Run the full existing test suite (this crate + workspace) to confirm nothing regressed**

Run: `cargo test -p exchange_adapter_binance && cd .. && cargo test --workspace`
Expected: all green, including the other adapters/layers untouched by this plan.

- [ ] **Step 8: Commit**

```bash
git add crates/exchange_adapter_binance/src/adapter.rs crates/exchange_adapter_binance/src/market.rs crates/exchange_adapter_binance/tests/wiremock_tests.rs
git commit -m "feat(exchange_adapter_binance): merge ws book/trade streams into subscribe_market_data"
```

---

## Task 9: Update `NOTES.md`

**Files:**
- Modify: `crates/exchange_adapter_binance/NOTES.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Update §1**

Read the current §1 ("No real websocket — REST polling everywhere") in `NOTES.md` and rewrite it to reflect the new state: book/trade are now real ws (with the sync/resync/backoff behavior summarized), `Candle` is still REST-polled (deliberately, per the design spec's "Out of scope"), and account updates are still REST poll-and-diff (also deliberately out of scope). Link to `external/executor/specs/2026-09-05-binance-market-data-websocket-design.md` for the full design rather than duplicating it. Keep §2 (account updates) as-is except for cross-referencing the new §1 wording if it previously implied book/trade were also unbuilt.

- [ ] **Step 2: Update `external/executor/plans/02-L0-exchange-adapter.md`'s "Known gaps" list**

Remove or amend the "No websocket anywhere in either adapter" bullet's Binance half (MEXC's half of that gap is unchanged and stays) to reflect that Binance now has real book/trade ws; keep the note that MEXC is still REST-only and is the tracked follow-up (per this spec's "Out of scope" section naming MEXC as a second project).

- [ ] **Step 3: Commit**

```bash
git add crates/exchange_adapter_binance/NOTES.md external/executor/plans/02-L0-exchange-adapter.md
git commit -m "docs(exchange_adapter_binance): update NOTES.md and L0 plan for ws book/trade support"
```

Note: `external/executor/` is a separate git repository from `trade_executor/` -- this will be two separate commits in two separate repos, not one. Confirm which repo you're in (`git rev-parse --show-toplevel`) before committing each file.

---

## Self-Review Notes (for whoever executes this plan)

- **Spec coverage:** every section of the design spec maps to a task — Architecture → Tasks 6-8, snapshot-sync procedure → Task 3, sequence numbering → Task 3 (fixed a bug in the spec's own wording during planning, see the spec's current "Sequence numbering" section), reconnect policy → Task 4 + Tasks 6-7's loops, trade stream → Task 6, testing approach → Task 5, out-of-scope items are simply untouched (no task references `subscribe_account_updates` or moves `Candle` off REST).
- **`__test_support` module:** introduced in Task 6, extended in Task 7, because `tests/wiremock_tests.rs` is a separate crate from `exchange_adapter_binance`'s `src/` and can't see `pub(crate)` items directly. This is new to this crate (existing tests only ever exercised the fully-`pub` `ExchangeAdapterBinance`/`BinanceAdapterConfig` surface) — flagged explicitly rather than silently introduced, since it's a testability pattern worth the executor noticing rather than stepping over.
- **Type consistency check:** `BinanceMarketAccount::new`'s parameter list is defined once in Task 8 Step 1 and every call site (Task 8 Step 3, the only caller) is updated in the same task — no earlier task calls the old 4-arg form after Task 8 lands.
