# MEXC Spot/Margin Market-Data WebSocket Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `exchange_adapter_mexc`'s `subscribe_market_data` (spot/margin, via `SpotStyleAccount`) real websocket-backed `BookSnapshot`/`BookUpdate`/`Trade` events (currently only `Candle`, via REST polling), mirroring the already-shipped Binance implementation.

**Architecture:** New `ws.rs` module: a hand-rolled protobuf wire-format reader (MEXC's ws payloads are protobuf, not JSON) decodes the three message shapes we need; a pure `DepthSync` state machine (a direct mirror of Binance's — including the `bridged`-state fix Binance's final review found) implements MEXC's snapshot-buffer-resync procedure; a `Backoff` reconnect schedule; two `tokio-tungstenite`-backed tasks (`book_stream`, `trade_stream`) each running a client-initiated JSON ping loop alongside their read loop (MEXC's keepalive is application-level, unlike Binance's protocol-level auto-pong) — merged into the existing `MarketDataStream` alongside the untouched REST candle-poll task.

**Tech Stack:** Rust, `tokio-tungstenite` (already proven in this workspace via the Binance project), hand-rolled protobuf decode/encode (no `prost`/codegen dependency), existing `wiremock`/`tokio::test` harness.

**Spec:** `external/executor/specs/2026-09-06-mexc-spot-market-data-websocket-design.md`

Reference (do not re-read in full, but the pattern this plan mirrors): `external/executor/specs/2026-09-05-binance-market-data-websocket-design.md` and `external/executor/plans/2026-09-05-binance-market-data-websocket-plan.md`.

## Global Constraints

- No `prost`/`protoc`/any protobuf codegen dependency — hand-rolled wire-format reader only, per the spec's "Protobuf decoding" section.
- MEXC futures market data, MEXC account-update push, and moving `Candle` off REST polling are explicitly out of scope — do not touch `subscribe_account_updates`, `FuturesAccount`, or the candle-poll code path's behavior.
- A real `Gap`/`GapMarker` must never be produced by the live ws path — any MEXC-side desync is resolved internally via resync, never surfaced as `MarketDataEvent::Gap` (same rule as Binance's spec).
- `BookUpdate.sequence` numbering: first `BookUpdate` after any `BookSnapshot` is `1`, then `2, 3, ...`. `BookSnapshot.sequence` is always `0`.
- Reconnect backoff: `1s → 2s → 4s → ... capped at 30s`, reset only after a connection has proven **stable** (`STABLE_CONNECTION_THRESHOLD`, propose 60s to match Binance) — never on bare connect success. This is a lesson learned the hard way on Binance (a real bug found in that project's final review); build it correctly from the start here, do not repeat the mistake.
- `DepthSync`'s post-resync bridging state (`bridged: bool`, gating the loose "first event after snapshot" rule vs. the strict ongoing-contiguity rule) must be present from the first implementation of `DepthSync` — this is Binance's Critical fix, known in advance this time.
- Both `book_stream` and `trade_stream` need an idle/read timeout (propose 45s, under MEXC's 60s no-data-flow disconnect) treating a timeout exactly like a dropped connection — Binance's final review added this after initially missing it; do not repeat that gap either.
- Both `book_stream` and `trade_stream` need a client-initiated JSON ping loop (`{"method":"PING"}` text frame, propose every 20s) running concurrently with the read loop — MEXC's keepalive is application-level, not the WebSocket protocol-level ping/pong `tokio-tungstenite` answers automatically. This has no Binance equivalent; it is new.
- Backoff, ping interval, and idle-timeout must all be injectable values (not hardcoded inside the task functions) so tests can use fast schedules instead of waiting on real timers — same requirement as Binance's `Backoff`.

---

## Task 1: Protobuf wire-format primitives

**Files:**
- Create: `crates/exchange_adapter_mexc/src/ws.rs`
- Create: `crates/exchange_adapter_mexc/proto/PushDataV3ApiWrapper.proto` (reference copy, not built)
- Create: `crates/exchange_adapter_mexc/proto/PublicAggreDepthsV3Api.proto` (reference copy, not built)
- Create: `crates/exchange_adapter_mexc/proto/PublicAggreDealsV3Api.proto` (reference copy, not built)
- Modify: `crates/exchange_adapter_mexc/src/lib.rs:12-24` (add `mod ws;`)
- Test: inline `#[cfg(test)] mod tests` at the bottom of `ws.rs`

**Interfaces:**
- Consumes: nothing yet (pure byte-level primitives).
- Produces (used by Task 2):
  - `pub(crate) struct WireReader<'a>` with:
    - `pub(crate) fn new(buf: &'a [u8]) -> Self`
    - `pub(crate) fn is_empty(&self) -> bool`
    - `pub(crate) fn read_varint(&mut self) -> Option<u64>`
    - `pub(crate) fn read_tag(&mut self) -> Option<(u32, u8)>` (returns `(field_number, wire_type)`)
    - `pub(crate) fn read_length_delimited(&mut self) -> Option<&'a [u8]>`
    - `pub(crate) fn read_string(&mut self) -> Option<String>`
    - `pub(crate) fn skip_field(&mut self, wire_type: u8) -> Option<()>`
  - Test-only encode helpers (module-private, used only by `#[cfg(test)]` code in Tasks 1-2): `encode_varint`, `encode_tag`, `encode_string_field`, `encode_int64_field`, `encode_message_field`.

- [ ] **Step 1: Vendor the reference `.proto` files**

Create the three files below verbatim (documentation only — nothing in the build references them; they exist purely so a future maintainer can check the decoder against the real schema without searching GitHub again):

`crates/exchange_adapter_mexc/proto/PushDataV3ApiWrapper.proto`:
```protobuf
// Reference copy from https://github.com/mexcdevelop/websocket-proto —
// NOT built by this crate. Only the fields this adapter actually
// decodes are relevant: channel (1), sendTime (6), and the two `oneof
// body` variants this crate cares about (313, 314). The real file
// defines many more oneof variants (orders, account, other tickers)
// that this adapter never subscribes to and therefore never needs to
// decode.
syntax = "proto3";

message PushDataV3ApiWrapper {
  string channel = 1;
  oneof body {
    // ... (13 other variants omitted, not relevant to this adapter)
    PublicAggreDepthsV3Api publicAggreDepths = 313;
    PublicAggreDealsV3Api publicAggreDeals = 314;
  }
  optional string symbol = 3;
  optional string symbolId = 4;
  optional int64 createTime = 5;
  optional int64 sendTime = 6;
}
```

`crates/exchange_adapter_mexc/proto/PublicAggreDepthsV3Api.proto`:
```protobuf
// Reference copy from https://github.com/mexcdevelop/websocket-proto —
// NOT built by this crate.
syntax = "proto3";

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
```

`crates/exchange_adapter_mexc/proto/PublicAggreDealsV3Api.proto`:
```protobuf
// Reference copy from https://github.com/mexcdevelop/websocket-proto —
// NOT built by this crate.
syntax = "proto3";

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

- [ ] **Step 2: Write the failing tests**

Create `crates/exchange_adapter_mexc/src/ws.rs`:

```rust
//! Real websocket market data for MEXC spot/margin: a hand-rolled
//! protobuf wire-format decoder (see `../proto/*.proto` for the
//! reference schemas — not built, documentation only), a `DepthSync`
//! snapshot-resync state machine mirroring Binance's (including the
//! post-resync bridging-state fix Binance's final review found), and
//! book-diff/trade ws tasks merged into `subscribe_market_data`'s
//! `MarketDataStream` alongside the existing REST candle poll. See
//! `external/executor/specs/2026-09-06-mexc-spot-market-data-websocket-design.md`.

/// Minimal protobuf wire-format reader over a byte slice — decodes
/// exactly the field/wire-type shapes this adapter needs (varints,
/// length-delimited strings and nested messages) and can skip fields it
/// doesn't recognize (wire-type-aware, so decoding survives MEXC adding
/// fields this adapter never reads).
pub(crate) struct WireReader<'a> {
    buf: &'a [u8],
    pos: usize,
}

impl<'a> WireReader<'a> {
    pub(crate) fn new(buf: &'a [u8]) -> Self {
        Self { buf, pos: 0 }
    }

    pub(crate) fn is_empty(&self) -> bool {
        self.pos >= self.buf.len()
    }

    /// Protobuf's base-128 varint: 7 payload bits per byte, MSB set
    /// means "more bytes follow". Supports up to 10 bytes (enough for a
    /// full u64) before giving up as malformed.
    pub(crate) fn read_varint(&mut self) -> Option<u64> {
        let mut result: u64 = 0;
        let mut shift = 0u32;
        for _ in 0..10 {
            let byte = *self.buf.get(self.pos)?;
            self.pos += 1;
            result |= ((byte & 0x7F) as u64) << shift;
            if byte & 0x80 == 0 {
                return Some(result);
            }
            shift += 7;
        }
        None
    }

    /// A field tag is `(field_number << 3) | wire_type`, itself varint-encoded.
    pub(crate) fn read_tag(&mut self) -> Option<(u32, u8)> {
        let v = self.read_varint()?;
        Some(((v >> 3) as u32, (v & 0x7) as u8))
    }

    pub(crate) fn read_length_delimited(&mut self) -> Option<&'a [u8]> {
        let len = self.read_varint()? as usize;
        let end = self.pos.checked_add(len)?;
        let slice = self.buf.get(self.pos..end)?;
        self.pos = end;
        Some(slice)
    }

    pub(crate) fn read_string(&mut self) -> Option<String> {
        let bytes = self.read_length_delimited()?;
        String::from_utf8(bytes.to_vec()).ok()
    }

    /// Skips a field's value given its wire type, without knowing or
    /// caring what it means — how an unrecognized field number gets
    /// safely ignored. Wire type 3/4 (deprecated start/end group) are
    /// not supported by proto3 and are treated as malformed.
    pub(crate) fn skip_field(&mut self, wire_type: u8) -> Option<()> {
        match wire_type {
            0 => {
                self.read_varint()?;
            }
            1 => {
                self.pos = self.pos.checked_add(8)?;
                if self.pos > self.buf.len() {
                    return None;
                }
            }
            2 => {
                self.read_length_delimited()?;
            }
            5 => {
                self.pos = self.pos.checked_add(4)?;
                if self.pos > self.buf.len() {
                    return None;
                }
            }
            _ => return None,
        }
        Some(())
    }
}

#[cfg(test)]
fn encode_varint(mut v: u64, out: &mut Vec<u8>) {
    loop {
        let mut byte = (v & 0x7F) as u8;
        v >>= 7;
        if v != 0 {
            byte |= 0x80;
        }
        out.push(byte);
        if v == 0 {
            break;
        }
    }
}

#[cfg(test)]
fn encode_tag(field_number: u32, wire_type: u8, out: &mut Vec<u8>) {
    encode_varint(((field_number as u64) << 3) | wire_type as u64, out);
}

#[cfg(test)]
fn encode_string_field(field_number: u32, s: &str, out: &mut Vec<u8>) {
    encode_tag(field_number, 2, out);
    encode_varint(s.len() as u64, out);
    out.extend_from_slice(s.as_bytes());
}

#[cfg(test)]
fn encode_int64_field(field_number: u32, v: i64, out: &mut Vec<u8>) {
    encode_tag(field_number, 0, out);
    encode_varint(v as u64, out);
}

#[cfg(test)]
fn encode_message_field(field_number: u32, msg_bytes: &[u8], out: &mut Vec<u8>) {
    encode_tag(field_number, 2, out);
    encode_varint(msg_bytes.len() as u64, out);
    out.extend_from_slice(msg_bytes);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn varint_round_trips_single_byte_value() {
        let mut buf = Vec::new();
        encode_varint(3, &mut buf);
        assert_eq!(buf, vec![0x03]);
        let mut r = WireReader::new(&buf);
        assert_eq!(r.read_varint(), Some(3));
    }

    #[test]
    fn varint_round_trips_multi_byte_value() {
        // 300 = 0b1_0010_1100 -> needs 2 bytes: 0xAC, 0x02
        let mut buf = Vec::new();
        encode_varint(300, &mut buf);
        assert_eq!(buf, vec![0xAC, 0x02]);
        let mut r = WireReader::new(&buf);
        assert_eq!(r.read_varint(), Some(300));
    }

    #[test]
    fn tag_round_trips_a_high_field_number_needing_a_multi_byte_tag() {
        // field 313, wire type 2 (length-delimited) -- this is exactly
        // the `oneof body` shape (field numbers 301-315), the decoder
        // edge case the design spec calls out explicitly: a naive
        // single-byte-tag assumption would break here.
        let mut buf = Vec::new();
        encode_tag(313, 2, &mut buf);
        let mut r = WireReader::new(&buf);
        assert_eq!(r.read_tag(), Some((313, 2)));
    }

    #[test]
    fn string_field_round_trips() {
        let mut buf = Vec::new();
        encode_string_field(4, "10589632359", &mut buf);
        let mut r = WireReader::new(&buf);
        let (field, wt) = r.read_tag().unwrap();
        assert_eq!(field, 4);
        assert_eq!(wt, 2);
        assert_eq!(r.read_string(), Some("10589632359".to_string()));
    }

    #[test]
    fn int64_field_round_trips() {
        let mut buf = Vec::new();
        encode_int64_field(6, 1736411507002, &mut buf);
        let mut r = WireReader::new(&buf);
        let (field, wt) = r.read_tag().unwrap();
        assert_eq!(field, 6);
        assert_eq!(wt, 0);
        assert_eq!(r.read_varint(), Some(1736411507002u64));
    }

    #[test]
    fn message_field_wraps_nested_bytes_that_can_be_re_parsed() {
        let mut inner = Vec::new();
        encode_string_field(1, "92877.58", &mut inner);
        let mut outer = Vec::new();
        encode_message_field(313, &inner, &mut outer);
        let mut r = WireReader::new(&outer);
        let (field, wt) = r.read_tag().unwrap();
        assert_eq!(field, 313);
        assert_eq!(wt, 2);
        let nested_bytes = r.read_length_delimited().unwrap();
        let mut nested_reader = WireReader::new(nested_bytes);
        let (inner_field, inner_wt) = nested_reader.read_tag().unwrap();
        assert_eq!(inner_field, 1);
        assert_eq!(inner_wt, 2);
        assert_eq!(nested_reader.read_string(), Some("92877.58".to_string()));
    }

    #[test]
    fn skip_field_advances_past_an_unrecognized_varint_field() {
        let mut buf = Vec::new();
        encode_int64_field(99, 42, &mut buf); // a field number this decoder doesn't care about
        encode_string_field(4, "after".into(), &mut buf); // something real follows
        let mut r = WireReader::new(&buf);
        let (field, wt) = r.read_tag().unwrap();
        assert_eq!(field, 99);
        r.skip_field(wt).unwrap();
        let (field2, wt2) = r.read_tag().unwrap();
        assert_eq!(field2, 4);
        assert_eq!(wt2, 2);
        assert_eq!(r.read_string(), Some("after".to_string()));
    }

    #[test]
    fn skip_field_advances_past_an_unrecognized_length_delimited_field() {
        let mut buf = Vec::new();
        encode_string_field(99, "ignored", &mut buf);
        encode_string_field(4, "after", &mut buf);
        let mut r = WireReader::new(&buf);
        let (_, wt) = r.read_tag().unwrap();
        r.skip_field(wt).unwrap();
        let (field2, _) = r.read_tag().unwrap();
        assert_eq!(field2, 4);
        assert_eq!(r.read_string(), Some("after".to_string()));
    }

    #[test]
    fn read_varint_on_empty_input_returns_none() {
        let mut r = WireReader::new(&[]);
        assert_eq!(r.read_varint(), None);
    }

    #[test]
    fn read_length_delimited_past_the_end_of_the_buffer_returns_none() {
        let mut buf = Vec::new();
        encode_varint(100, &mut buf); // claims 100 bytes follow, but none do
        let mut r = WireReader::new(&buf);
        assert_eq!(r.read_length_delimited(), None);
    }
}
```

- [ ] **Step 3: Register the module**

Edit `crates/exchange_adapter_mexc/src/lib.rs`, add `mod ws;` alongside the other `mod` declarations.

- [ ] **Step 4: Run the tests, confirm they pass**

Run: `cargo test -p exchange_adapter_mexc ws::tests`
Expected: 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add crates/exchange_adapter_mexc/proto crates/exchange_adapter_mexc/src/ws.rs crates/exchange_adapter_mexc/src/lib.rs
git commit -m "feat(exchange_adapter_mexc): add protobuf wire-format primitives"
```

---

## Task 2: MEXC message decoders and L0 conversions

**Files:**
- Modify: `crates/exchange_adapter_mexc/src/ws.rs` (add below Task 1's primitives, above its `#[cfg(test)]` block)

**Interfaces:**
- Consumes: `WireReader` and the test-only `encode_*` helpers (Task 1); `exchange_adapter::{parse_decimal, OrderId, Pair, PriceLevel, PriceLevelDelta, Side, TradeId, TradeTick, Ts, AdapterError}`.
- Produces (used by Tasks 4, 7, 8):
  - `pub(crate) struct RawDepthItem { pub(crate) price: String, pub(crate) quantity: String }`
  - `pub(crate) struct RawAggreDepths { pub(crate) asks: Vec<RawDepthItem>, pub(crate) bids: Vec<RawDepthItem>, pub(crate) from_version: String, pub(crate) to_version: String }`
  - `pub(crate) struct RawAggreDealItem { pub(crate) price: String, pub(crate) quantity: String, pub(crate) trade_type: i32, pub(crate) time: i64, pub(crate) trade_id: String }`
  - `pub(crate) struct RawAggreDeals { pub(crate) deals: Vec<RawAggreDealItem> }`
  - `pub(crate) enum MexcPushBody { Depth(RawAggreDepths), Trade(RawAggreDeals), Other }`
  - `pub(crate) struct MexcPush { pub(crate) send_time: i64, pub(crate) body: MexcPushBody }`
  - `pub(crate) fn decode_push(bytes: &[u8]) -> Option<MexcPush>`
  - `pub(crate) fn to_levels(items: &[RawDepthItem]) -> Result<Vec<PriceLevel>, AdapterError>`
  - `pub(crate) fn to_deltas(items: &[RawDepthItem]) -> Result<Vec<PriceLevelDelta>, AdapterError>`
  - `pub(crate) fn trade_tick_from_raw(pair: &Pair, raw: &RawAggreDealItem) -> Result<TradeTick, AdapterError>`

- [ ] **Step 1: Write the failing tests**

Add to `ws.rs`'s test module (the byte fixtures are built with Task 1's `encode_*` helpers — never hand-typed raw arrays, so there's no separate arithmetic to get wrong):

```rust
fn encode_depth_item(price: &str, quantity: &str) -> Vec<u8> {
    let mut buf = Vec::new();
    encode_string_field(1, price, &mut buf);
    encode_string_field(2, quantity, &mut buf);
    buf
}

fn encode_aggre_depths(
    asks: &[(&str, &str)],
    bids: &[(&str, &str)],
    from_version: &str,
    to_version: &str,
) -> Vec<u8> {
    let mut buf = Vec::new();
    for (price, qty) in asks {
        let item = encode_depth_item(price, qty);
        encode_message_field(1, &item, &mut buf);
    }
    for (price, qty) in bids {
        let item = encode_depth_item(price, qty);
        encode_message_field(2, &item, &mut buf);
    }
    encode_string_field(4, from_version, &mut buf);
    encode_string_field(5, to_version, &mut buf);
    buf
}

fn encode_deal_item(price: &str, quantity: &str, trade_type: i32, time: i64, trade_id: &str) -> Vec<u8> {
    let mut buf = Vec::new();
    encode_string_field(1, price, &mut buf);
    encode_string_field(2, quantity, &mut buf);
    encode_tag(3, 0, &mut buf);
    encode_varint(trade_type as u64, &mut buf);
    encode_int64_field(4, time, &mut buf);
    encode_string_field(5, trade_id, &mut buf);
    buf
}

fn encode_aggre_deals(deals: &[Vec<u8>]) -> Vec<u8> {
    let mut buf = Vec::new();
    for deal in deals {
        encode_message_field(1, deal, &mut buf);
    }
    buf
}

fn encode_push_wrapper(channel: &str, send_time: i64, body_field: u32, body_bytes: &[u8]) -> Vec<u8> {
    let mut buf = Vec::new();
    encode_string_field(1, channel, &mut buf);
    encode_message_field(body_field, body_bytes, &mut buf);
    encode_int64_field(6, send_time, &mut buf);
    buf
}

#[test]
fn decodes_a_depth_item() {
    let bytes = encode_depth_item("92877.58", "0.00000000");
    let mut r = WireReader::new(&bytes);
    let item = decode_depth_item(&mut r).unwrap();
    assert_eq!(item.price, "92877.58");
    assert_eq!(item.quantity, "0.00000000");
}

#[test]
fn decodes_aggre_depths_with_multiple_levels() {
    let bytes = encode_aggre_depths(
        &[("92880", "1")],
        &[("92877.58", "0.00000000"), ("92870", "2")],
        "10589632359",
        "10589632359",
    );
    let depths = decode_aggre_depths(&bytes).unwrap();
    assert_eq!(depths.asks.len(), 1);
    assert_eq!(depths.bids.len(), 2);
    assert_eq!(depths.bids[0].price, "92877.58");
    assert_eq!(depths.from_version, "10589632359");
    assert_eq!(depths.to_version, "10589632359");
}

#[test]
fn decodes_aggre_deals() {
    let deal = encode_deal_item("93220.00", "0.04438243", 2, 1736409765051, "12345");
    let bytes = encode_aggre_deals(&[deal]);
    let deals = decode_aggre_deals(&bytes).unwrap();
    assert_eq!(deals.deals.len(), 1);
    assert_eq!(deals.deals[0].price, "93220.00");
    assert_eq!(deals.deals[0].trade_type, 2);
    assert_eq!(deals.deals[0].trade_id, "12345");
}

#[test]
fn decode_push_routes_a_depth_body_via_the_high_field_number() {
    let depths_bytes = encode_aggre_depths(&[], &[("100", "1")], "160", "165");
    let wrapper_bytes = encode_push_wrapper(
        "spot@public.aggre.depth.v3.api.pb@100ms@BTCUSDT",
        1736411507002,
        313,
        &depths_bytes,
    );
    let push = decode_push(&wrapper_bytes).unwrap();
    assert_eq!(push.send_time, 1736411507002);
    match push.body {
        MexcPushBody::Depth(depths) => {
            assert_eq!(depths.from_version, "160");
            assert_eq!(depths.to_version, "165");
        }
        other => panic!("expected Depth body, got {other:?}"),
    }
}

#[test]
fn decode_push_routes_a_trade_body_via_the_high_field_number() {
    let deal = encode_deal_item("1", "1", 1, 1, "7");
    let deals_bytes = encode_aggre_deals(&[deal]);
    let wrapper_bytes = encode_push_wrapper(
        "spot@public.aggre.deals.v3.api.pb@100ms@BTCUSDT",
        1,
        314,
        &deals_bytes,
    );
    let push = decode_push(&wrapper_bytes).unwrap();
    match push.body {
        MexcPushBody::Trade(deals) => assert_eq!(deals.deals[0].trade_id, "7"),
        other => panic!("expected Trade body, got {other:?}"),
    }
}

#[test]
fn decode_push_treats_an_unrecognized_body_field_as_other_without_failing() {
    // Field 305 (publicBookTicker) is a real oneof variant this adapter
    // never subscribes to -- must not crash the whole decode.
    let mut buf = Vec::new();
    encode_string_field(1, "spot@public.bookTicker.v3.api.pb@BTCUSDT", &mut buf);
    encode_message_field(305, b"irrelevant", &mut buf);
    let push = decode_push(&buf).unwrap();
    assert!(matches!(push.body, MexcPushBody::Other));
}

#[test]
fn to_levels_parses_decimals() {
    let items = vec![RawDepthItem { price: "92877.58".to_string(), quantity: "1".to_string() }];
    let levels = to_levels(&items).unwrap();
    assert_eq!(levels[0].price.to_string(), "92877.58");
}

#[test]
fn to_levels_rejects_non_numeric_input() {
    let items = vec![RawDepthItem { price: "not-a-number".to_string(), quantity: "1".to_string() }];
    assert!(to_levels(&items).is_err());
}

#[test]
fn to_deltas_parses_decimals() {
    let items = vec![RawDepthItem { price: "1".to_string(), quantity: "0.5".to_string() }];
    let deltas = to_deltas(&items).unwrap();
    assert_eq!(deltas[0].quantity.to_string(), "0.5");
}

#[test]
fn to_deltas_rejects_non_numeric_input() {
    let items = vec![RawDepthItem { price: "1".to_string(), quantity: "not-a-number".to_string() }];
    assert!(to_deltas(&items).is_err());
}

#[test]
fn trade_type_one_maps_to_buy() {
    let raw = RawAggreDealItem {
        price: "1".to_string(), quantity: "1".to_string(),
        trade_type: 1, time: 1000, trade_id: "42".to_string(),
    };
    let pair = Pair("BTCUSDT".to_string());
    let tick = trade_tick_from_raw(&pair, &raw).unwrap();
    assert_eq!(tick.side, Side::Buy);
    assert_eq!(tick.trade_id, TradeId(42));
}

#[test]
fn trade_type_two_maps_to_sell() {
    let raw = RawAggreDealItem {
        price: "1".to_string(), quantity: "1".to_string(),
        trade_type: 2, time: 1000, trade_id: "42".to_string(),
    };
    let pair = Pair("BTCUSDT".to_string());
    let tick = trade_tick_from_raw(&pair, &raw).unwrap();
    assert_eq!(tick.side, Side::Sell);
}

#[test]
fn a_non_numeric_trade_id_falls_back_to_a_stable_hash_instead_of_failing() {
    let raw = RawAggreDealItem {
        price: "1".to_string(), quantity: "1".to_string(),
        trade_type: 1, time: 1000, trade_id: "not-numeric-abc".to_string(),
    };
    let pair = Pair("BTCUSDT".to_string());
    let tick1 = trade_tick_from_raw(&pair, &raw).unwrap();
    let tick2 = trade_tick_from_raw(&pair, &raw).unwrap();
    // Deterministic: the same opaque id always maps to the same TradeId.
    assert_eq!(tick1.trade_id, tick2.trade_id);
}
```

- [ ] **Step 2: Run the tests, confirm they fail to compile**

Run: `cargo test -p exchange_adapter_mexc ws::tests`
Expected: FAIL — none of `decode_depth_item`, `decode_aggre_depths`, etc. exist yet.

- [ ] **Step 3: Implement the decoders and conversions**

Add to `ws.rs`, above the test module:

```rust
use exchange_adapter::{parse_decimal, AdapterError, Pair, PriceLevel, PriceLevelDelta, Side, TradeId, TradeTick, Ts};

#[derive(Debug, Clone)]
pub(crate) struct RawDepthItem {
    pub(crate) price: String,
    pub(crate) quantity: String,
}

fn decode_depth_item(r: &mut WireReader) -> Option<RawDepthItem> {
    let mut price = None;
    let mut quantity = None;
    while !r.is_empty() {
        let (field, wire_type) = r.read_tag()?;
        match (field, wire_type) {
            (1, 2) => price = r.read_string(),
            (2, 2) => quantity = r.read_string(),
            (_, wt) => r.skip_field(wt)?,
        }
    }
    Some(RawDepthItem { price: price?, quantity: quantity? })
}

#[derive(Debug, Clone)]
pub(crate) struct RawAggreDepths {
    pub(crate) asks: Vec<RawDepthItem>,
    pub(crate) bids: Vec<RawDepthItem>,
    pub(crate) from_version: String,
    pub(crate) to_version: String,
}

fn decode_aggre_depths(bytes: &[u8]) -> Option<RawAggreDepths> {
    let mut r = WireReader::new(bytes);
    let mut asks = Vec::new();
    let mut bids = Vec::new();
    let mut from_version = None;
    let mut to_version = None;
    while !r.is_empty() {
        let (field, wire_type) = r.read_tag()?;
        match (field, wire_type) {
            (1, 2) => {
                let item_bytes = r.read_length_delimited()?;
                asks.push(decode_depth_item(&mut WireReader::new(item_bytes))?);
            }
            (2, 2) => {
                let item_bytes = r.read_length_delimited()?;
                bids.push(decode_depth_item(&mut WireReader::new(item_bytes))?);
            }
            (4, 2) => from_version = r.read_string(),
            (5, 2) => to_version = r.read_string(),
            (_, wt) => r.skip_field(wt)?,
        }
    }
    Some(RawAggreDepths {
        asks,
        bids,
        from_version: from_version?,
        to_version: to_version?,
    })
}

#[derive(Debug, Clone)]
pub(crate) struct RawAggreDealItem {
    pub(crate) price: String,
    pub(crate) quantity: String,
    pub(crate) trade_type: i32,
    pub(crate) time: i64,
    pub(crate) trade_id: String,
}

fn decode_deal_item(r: &mut WireReader) -> Option<RawAggreDealItem> {
    let mut price = None;
    let mut quantity = None;
    let mut trade_type = None;
    let mut time = None;
    let mut trade_id = None;
    while !r.is_empty() {
        let (field, wire_type) = r.read_tag()?;
        match (field, wire_type) {
            (1, 2) => price = r.read_string(),
            (2, 2) => quantity = r.read_string(),
            (3, 0) => trade_type = r.read_varint().map(|v| v as i32),
            (4, 0) => time = r.read_varint().map(|v| v as i64),
            (5, 2) => trade_id = r.read_string(),
            (_, wt) => r.skip_field(wt)?,
        }
    }
    Some(RawAggreDealItem {
        price: price?,
        quantity: quantity?,
        trade_type: trade_type?,
        time: time?,
        trade_id: trade_id?,
    })
}

#[derive(Debug, Clone)]
pub(crate) struct RawAggreDeals {
    pub(crate) deals: Vec<RawAggreDealItem>,
}

fn decode_aggre_deals(bytes: &[u8]) -> Option<RawAggreDeals> {
    let mut r = WireReader::new(bytes);
    let mut deals = Vec::new();
    while !r.is_empty() {
        let (field, wire_type) = r.read_tag()?;
        match (field, wire_type) {
            (1, 2) => {
                let item_bytes = r.read_length_delimited()?;
                deals.push(decode_deal_item(&mut WireReader::new(item_bytes))?);
            }
            (_, wt) => r.skip_field(wt)?,
        }
    }
    Some(RawAggreDeals { deals })
}

#[derive(Debug)]
pub(crate) enum MexcPushBody {
    Depth(RawAggreDepths),
    Trade(RawAggreDeals),
    /// Any other `oneof body` variant (order updates, other ticker
    /// types, ...) this adapter never subscribes to and therefore
    /// doesn't need to decode -- routing sees the field number, skips
    /// the bytes, and moves on rather than failing the whole message.
    Other,
}

pub(crate) struct MexcPush {
    pub(crate) send_time: i64,
    pub(crate) body: MexcPushBody,
}

pub(crate) fn decode_push(bytes: &[u8]) -> Option<MexcPush> {
    let mut r = WireReader::new(bytes);
    let mut send_time = 0i64;
    let mut body = MexcPushBody::Other;
    while !r.is_empty() {
        let (field, wire_type) = r.read_tag()?;
        match (field, wire_type) {
            (1, 2) => {
                r.read_string()?; // channel -- not currently consumed, but must still be parsed off the wire
            }
            (6, 0) => send_time = r.read_varint()? as i64,
            (313, 2) => {
                let body_bytes = r.read_length_delimited()?;
                body = MexcPushBody::Depth(decode_aggre_depths(body_bytes)?);
            }
            (314, 2) => {
                let body_bytes = r.read_length_delimited()?;
                body = MexcPushBody::Trade(decode_aggre_deals(body_bytes)?);
            }
            (_, wt) => r.skip_field(wt)?,
        }
    }
    Some(MexcPush { send_time, body })
}

pub(crate) fn to_levels(items: &[RawDepthItem]) -> Result<Vec<PriceLevel>, AdapterError> {
    items
        .iter()
        .map(|item| {
            Ok(PriceLevel {
                price: parse_decimal(&item.price)?,
                qty: parse_decimal(&item.quantity)?,
            })
        })
        .collect()
}

pub(crate) fn to_deltas(items: &[RawDepthItem]) -> Result<Vec<PriceLevelDelta>, AdapterError> {
    items
        .iter()
        .map(|item| {
            Ok(PriceLevelDelta {
                price: parse_decimal(&item.price)?,
                qty: parse_decimal(&item.quantity)?,
            })
        })
        .collect()
}

/// MEXC's aggregated trade `tradeId` is documented as a string; whether
/// it's always numeric in practice is unconfirmed (no live MEXC access
/// while writing this). Parse as `u64` when possible; when it isn't
/// (an opaque/alphanumeric id), fall back to a stable FNV-1a hash of the
/// string so the same id always maps to the same `TradeId` rather than
/// failing the whole trade tick over an id format this adapter doesn't
/// understand.
fn trade_id_from_str(raw: &str) -> TradeId {
    if let Ok(n) = raw.parse::<u64>() {
        return TradeId(n);
    }
    let mut hash: u64 = 0xcbf29ce484222325; // FNV-1a offset basis
    for byte in raw.as_bytes() {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(0x100000001b3); // FNV-1a prime
    }
    TradeId(hash)
}

/// `tradeType` maps directly to `Side` -- MEXC gives the taker's side
/// as-is (unlike Binance's `buyer_is_maker` proxy, which needs
/// inverting): `1` = Buy, `2` = Sell.
pub(crate) fn trade_tick_from_raw(pair: &Pair, raw: &RawAggreDealItem) -> Result<TradeTick, AdapterError> {
    let side = match raw.trade_type {
        1 => Side::Buy,
        2 => Side::Sell,
        other => {
            return Err(AdapterError::InvalidRequest(format!("unknown MEXC tradeType `{other}`")))
        }
    };
    Ok(TradeTick {
        pair: pair.clone(),
        price: parse_decimal(&raw.price)?,
        qty: parse_decimal(&raw.quantity)?,
        side,
        trade_id: trade_id_from_str(&raw.trade_id),
        ts: Ts(raw.time as u64),
    })
}
```

Update `decode_depth_item`'s call sites in `decode_aggre_depths` to pass `&mut WireReader::new(item_bytes)` as shown (the earlier test-writing step called it as `decode_depth_item(&mut r)` directly on a pre-built reader in the unit test for the item decoder alone — both call shapes work since the function takes `&mut WireReader`).

- [ ] **Step 4: Run the tests, confirm they pass**

Run: `cargo test -p exchange_adapter_mexc ws::tests`
Expected: all pass (16 new + 10 from Task 1 = 26).

- [ ] **Step 5: Commit**

```bash
git add crates/exchange_adapter_mexc/src/ws.rs
git commit -m "feat(exchange_adapter_mexc): add MEXC push-message decoders and L0 conversions"
```

---

## Task 3: Spot depth REST endpoint

**Files:**
- Modify: `crates/exchange_adapter_mexc/src/endpoints.rs`

**Interfaces:**
- Consumes: nothing new.
- Produces (used by Task 8): `pub(crate) const SPOT_DEPTH: &str`, used as `SPOT_DEPTH` (this file's existing constants like `SPOT_KLINES` are flat, not per-kind, since spot and margin already share all read-only market-data endpoints per this file's existing doc comment).

- [ ] **Step 1: Write the failing test**

Check `endpoints.rs` for an existing `#[cfg(test)] mod tests` block (there should be one already, from the earlier endpoint-consolidation refactor this crate went through). Add to it:

```rust
#[test]
fn spot_depth_endpoint_is_the_v3_depth_path() {
    assert_eq!(SPOT_DEPTH, "/api/v3/depth");
}
```

- [ ] **Step 2: Run it, confirm it fails to compile**

Run: `cargo test -p exchange_adapter_mexc endpoints::tests`
Expected: FAIL — `SPOT_DEPTH` doesn't exist.

- [ ] **Step 3: Add the constant**

In `endpoints.rs`, alongside `SPOT_KLINES`/`SPOT_ACCOUNT`/`SPOT_TRADE_FEE`/`SPOT_EXCHANGE_INFO`:

```rust
pub(crate) const SPOT_DEPTH: &str = "/api/v3/depth";
```

- [ ] **Step 4: Run it, confirm it passes, then run the full crate suite**

Run: `cargo test -p exchange_adapter_mexc endpoints::tests` then `cargo test -p exchange_adapter_mexc`
Expected: both green.

- [ ] **Step 5: Commit**

```bash
git add crates/exchange_adapter_mexc/src/endpoints.rs
git commit -m "feat(exchange_adapter_mexc): add spot depth REST endpoint"
```

---

## Task 4: `DepthSync` — pure snapshot-buffer-resync state machine

**Files:**
- Modify: `crates/exchange_adapter_mexc/src/ws.rs`

**Interfaces:**
- Consumes: `RawAggreDepths`, `to_levels`, `to_deltas` (Task 2); `exchange_adapter::{MarketDataEvent, OrderBookSnapshot, OrderBookUpdate, Pair, Ts, AdapterError}`.
- Produces (used by Task 8):
  - `pub(crate) enum DepthSyncOutcome { Buffering, Update(OrderBookUpdate), Desynced }`
  - `pub(crate) struct DepthSync` with:
    - `pub(crate) fn new(pair: Pair) -> Self`
    - `pub(crate) fn on_event(&mut self, raw: RawAggreDepths) -> DepthSyncOutcome`
    - `pub(crate) fn resync(&mut self, snapshot: DepthSnapshot, ts: Ts) -> Result<Vec<MarketDataEvent>, AdapterError>`
    - `pub(crate) fn mark_disconnected(&mut self)`
  - `pub(crate) struct DepthSnapshot { pub(crate) last_update_id: u64, pub(crate) bids: Vec<RawDepthItem>, pub(crate) asks: Vec<RawDepthItem> }` (the REST snapshot shape, built by Task 8 from the `/api/v3/depth` JSON response)

This mirrors Binance's `DepthSync` **as it exists today, post-fix** — the `bridged: bool` state and the size-capped buffer are both present from the start, not discovered via a review cycle this time. The one real simplification versus Binance: MEXC spot has no futures-style secondary chain field on this scope (spot/margin only, no MEXC futures ws in this project), so there is only ONE contiguity rule, not two — `event.from_version == prev.to_version + 1`. No `is_contiguous` branching on an `Option<u64>` secondary field is needed.

- [ ] **Step 1: Write the failing tests**

Add to `ws.rs`'s test module:

```rust
use std::time::Duration;

fn depth_event(from_version: &str, to_version: &str) -> RawAggreDepths {
    RawAggreDepths {
        asks: vec![],
        bids: vec![RawDepthItem { price: "100".to_string(), quantity: "1".to_string() }],
        from_version: from_version.to_string(),
        to_version: to_version.to_string(),
    }
}

fn snapshot(last_update_id: u64) -> DepthSnapshot {
    DepthSnapshot {
        last_update_id,
        bids: vec![RawDepthItem { price: "99".to_string(), quantity: "2".to_string() }],
        asks: vec![],
    }
}

#[test]
fn events_before_any_snapshot_are_buffered() {
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    let outcome = sync.on_event(depth_event("150", "155"));
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
    sync.on_event(depth_event("150", "160")); // stale (to_version <= 160), buffered pre-sync
    sync.on_event(depth_event("161", "165")); // bridges lastUpdateId=160
    let events = sync.resync(snapshot(160), Ts(2000)).unwrap();
    assert_eq!(events.len(), 2);
    match &events[1] {
        MarketDataEvent::BookUpdate(update) => assert_eq!(update.sequence, 1),
        other => panic!("expected BookUpdate, got {other:?}"),
    }
}

#[test]
fn contiguous_event_after_resync_with_a_non_boundary_aligned_snapshot_bridges_correctly() {
    // Deliberately not boundary-aligned (Binance's Critical bug was
    // hidden by every test using the boundary-aligned worked example --
    // this test's snapshot lands strictly inside the first live event's
    // range, proving the bridging state actually gets exercised on the
    // live (not just buffered-replay) path).
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    sync.resync(snapshot(160), Ts(2000)).unwrap();
    let outcome = sync.on_event(depth_event("155", "165")); // straddles 160
    match outcome {
        DepthSyncOutcome::Update(update) => assert_eq!(update.sequence, 1),
        other => panic!("expected Update, got {other:?}"),
    }
    let outcome = sync.on_event(depth_event("166", "170"));
    match outcome {
        DepthSyncOutcome::Update(update) => assert_eq!(update.sequence, 2),
        other => panic!("expected Update, got {other:?}"),
    }
}

#[test]
fn gap_is_detected_via_from_version_mismatch_after_bridging() {
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    sync.resync(snapshot(160), Ts(2000)).unwrap();
    sync.on_event(depth_event("161", "165")); // bridges, last_seen becomes 165
    let outcome = sync.on_event(depth_event("170", "175")); // gap: 170 != 166
    assert!(matches!(outcome, DepthSyncOutcome::Desynced));
}

#[test]
fn a_from_version_greater_than_last_seen_plus_one_before_bridging_is_a_gap_not_a_bridge() {
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    sync.resync(snapshot(160), Ts(2000)).unwrap();
    // from_version=200 is neither stale (to_version > 160) nor a valid
    // bridge (200 > 160+1) -- must be a gap, not silently accepted.
    let outcome = sync.on_event(depth_event("200", "210"));
    assert!(matches!(outcome, DepthSyncOutcome::Desynced));
}

#[test]
fn after_desync_events_are_buffered_again_until_the_next_resync() {
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    sync.resync(snapshot(160), Ts(2000)).unwrap();
    let outcome = sync.on_event(depth_event("999", "1000")); // gap
    assert!(matches!(outcome, DepthSyncOutcome::Desynced));
    let outcome = sync.on_event(depth_event("1001", "1002"));
    assert!(matches!(outcome, DepthSyncOutcome::Buffering));
}

#[test]
fn resync_after_desync_starts_the_update_counter_at_one_again() {
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    sync.resync(snapshot(160), Ts(2000)).unwrap();
    sync.on_event(depth_event("161", "165"));
    sync.on_event(depth_event("999", "1000")); // forces desync
    let events = sync.resync(snapshot(500), Ts(3000)).unwrap();
    assert_eq!(events.len(), 1); // no buffered events bridge 500
    let outcome = sync.on_event(depth_event("501", "505"));
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
    let outcome = sync.on_event(depth_event("161", "165"));
    assert!(matches!(outcome, DepthSyncOutcome::Buffering));
}

#[test]
fn a_malformed_buffered_event_during_resync_replay_returns_ok_with_valid_events_and_resets_synced() {
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    sync.on_event(depth_event("161", "165")); // bridges snapshot(160)
    let mut malformed = depth_event("166", "170");
    malformed.bids = vec![RawDepthItem { price: "not-a-number".to_string(), quantity: "1".to_string() }];
    sync.on_event(malformed); // buffered too (still pre-sync)
    let events = sync.resync(snapshot(160), Ts(2000)).unwrap();
    assert_eq!(events.len(), 2); // snapshot + the one good bridging update, replay stops at the bad one
    let outcome = sync.on_event(depth_event("161", "165"));
    assert!(matches!(outcome, DepthSyncOutcome::Buffering)); // synced was reset, not left true
}

#[test]
fn the_pre_sync_buffer_is_capped_and_drops_its_oldest_entries() {
    let mut sync = DepthSync::new(Pair("BTCUSDT".to_string()));
    for i in 0..1500u64 {
        sync.on_event(depth_event(&i.to_string(), &(i + 1).to_string()));
    }
    // Internal cap is MAX_BUFFERED_EVENTS (1000) -- verified indirectly:
    // resync against a snapshot only the newest entries could bridge
    // proves the oldest ones were evicted, not silently retained forever.
    let events = sync.resync(snapshot(1498), Ts(1)).unwrap();
    // event `from=1499,to=1500` bridges lastUpdateId=1498; earlier ones
    // were either stale or evicted -- either way exactly one update follows.
    assert_eq!(events.len(), 2);
}
```

- [ ] **Step 2: Run the tests, confirm they fail to compile**

Run: `cargo test -p exchange_adapter_mexc ws::tests`
Expected: FAIL — `DepthSync`/`DepthSyncOutcome`/`DepthSnapshot` don't exist.

- [ ] **Step 3: Implement `DepthSync`**

Add to `ws.rs`, above the test module:

```rust
use exchange_adapter::{MarketDataEvent, OrderBookSnapshot, OrderBookUpdate};

pub(crate) struct DepthSnapshot {
    pub(crate) last_update_id: u64,
    pub(crate) bids: Vec<RawDepthItem>,
    pub(crate) asks: Vec<RawDepthItem>,
}

#[derive(Debug)]
pub(crate) enum DepthSyncOutcome {
    Buffering,
    Update(OrderBookUpdate),
    Desynced,
}

/// A resync-buffered event that couldn't be parsed as a `u64` version
/// is treated as malformed input, same handling as a bad price/qty
/// string -- see `to_update`'s `Result` propagation.
fn parse_version(s: &str) -> Result<u64, AdapterError> {
    s.parse::<u64>()
        .map_err(|e| AdapterError::InvalidRequest(format!("bad MEXC depth version `{s}`: {e}")))
}

/// Bounds the pre-sync buffer so a `DepthSync` left unsynced indefinitely
/// (e.g. a malformed event aborted a resync replay, or a caller drives
/// this type outside `book_stream`'s normal connect-then-resync-then-read
/// order) can't grow its memory footprint without limit.
const MAX_BUFFERED_EVENTS: usize = 1000;

/// Implements MEXC's documented snapshot-buffer-resync procedure --
/// structurally identical to Binance's, just `fromVersion`/`toVersion`
/// (strings on the wire, parsed to `u64` here) instead of `U`/`u`, and
/// no secondary `pu`-style chain field since this project's scope is
/// spot/margin only (MEXC futures market data, with its own single-
/// `version`-counter protocol, is a separate later project). Translates
/// MEXC's real update ids into the synthetic, always-contiguous sequence
/// numbers `market_data`'s `BookTracker` expects, the same way Binance's
/// `DepthSync` does.
pub(crate) struct DepthSync {
    pair: Pair,
    synced: bool,
    /// Whether the post-resync bridging event has been found yet. While
    /// `synced && !bridged`, `on_event` applies the loose "first event
    /// after snapshot" rule (drop stale, find the bridge) instead of the
    /// strict ongoing-contiguity rule -- this is the fix Binance's final
    /// review found necessary (a snapshot lands inside an arbitrary
    /// event's version range, not on a boundary), built in from the
    /// start here rather than discovered the same way twice.
    bridged: bool,
    last_seen_to_version: u64,
    counter: u64,
    buffer: Vec<RawAggreDepths>,
}

impl DepthSync {
    pub(crate) fn new(pair: Pair) -> Self {
        Self {
            pair,
            synced: false,
            bridged: false,
            last_seen_to_version: 0,
            counter: 1,
            buffer: Vec::new(),
        }
    }

    pub(crate) fn on_event(&mut self, raw: RawAggreDepths) -> DepthSyncOutcome {
        if !self.synced {
            self.push_buffered(raw);
            return DepthSyncOutcome::Buffering;
        }
        if !self.bridged {
            return self.on_pre_bridge_event(raw);
        }
        match self.check_contiguous(&raw) {
            Ok(true) => match self.to_update(raw) {
                Ok(update) => DepthSyncOutcome::Update(update),
                Err(_) => {
                    self.synced = false;
                    DepthSyncOutcome::Desynced
                }
            },
            Ok(false) => {
                self.synced = false;
                DepthSyncOutcome::Desynced
            }
            Err(_) => {
                self.synced = false;
                DepthSyncOutcome::Desynced
            }
        }
    }

    fn on_pre_bridge_event(&mut self, raw: RawAggreDepths) -> DepthSyncOutcome {
        let (from_version, to_version) = match (parse_version(&raw.from_version), parse_version(&raw.to_version)) {
            (Ok(f), Ok(t)) => (f, t),
            _ => {
                self.synced = false;
                return DepthSyncOutcome::Desynced;
            }
        };
        if to_version <= self.last_seen_to_version {
            return DepthSyncOutcome::Buffering; // stale, drop silently
        }
        if from_version > self.last_seen_to_version + 1 {
            self.synced = false;
            return DepthSyncOutcome::Desynced; // gap even before any bridge found
        }
        self.bridged = true;
        self.last_seen_to_version = to_version;
        match self.to_update(raw) {
            Ok(update) => DepthSyncOutcome::Update(update),
            Err(_) => {
                self.synced = false;
                DepthSyncOutcome::Desynced
            }
        }
    }

    fn check_contiguous(&self, raw: &RawAggreDepths) -> Result<bool, AdapterError> {
        let from_version = parse_version(&raw.from_version)?;
        Ok(from_version == self.last_seen_to_version + 1)
    }

    pub(crate) fn mark_disconnected(&mut self) {
        self.synced = false;
    }

    fn push_buffered(&mut self, raw: RawAggreDepths) {
        if self.buffer.len() >= MAX_BUFFERED_EVENTS {
            self.buffer.remove(0);
        }
        self.buffer.push(raw);
    }

    fn to_update(&mut self, raw: RawAggreDepths) -> Result<OrderBookUpdate, AdapterError> {
        let to_version = parse_version(&raw.to_version)?;
        self.last_seen_to_version = to_version;
        let sequence = self.counter;
        self.counter += 1;
        Ok(OrderBookUpdate {
            pair: self.pair.clone(),
            bids: to_deltas(&raw.bids)?,
            asks: to_deltas(&raw.asks)?,
            sequence,
            ts: Ts(to_version), // MEXC's aggre-depth events carry no per-event timestamp of their own; the wrapper's sendTime is applied by the caller (book_stream), not here -- see Task 8.
        })
    }

    pub(crate) fn resync(
        &mut self,
        snapshot: DepthSnapshot,
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
        self.bridged = false;
        self.last_seen_to_version = last_update_id;

        let buffered = std::mem::take(&mut self.buffer);
        for raw in buffered {
            let (from_version, to_version) = match (parse_version(&raw.from_version), parse_version(&raw.to_version)) {
                (Ok(f), Ok(t)) => (f, t),
                _ => continue, // unparseable buffered entry -- skip, not fatal to the resync
            };
            if to_version <= last_update_id {
                continue;
            }
            if !self.bridged {
                if from_version <= last_update_id + 1 {
                    self.bridged = true;
                    self.last_seen_to_version = to_version;
                    match self.to_update(raw) {
                        Ok(update) => events.push(MarketDataEvent::BookUpdate(update)),
                        Err(_) => {
                            self.synced = false;
                            break;
                        }
                    }
                }
                continue;
            }
            if from_version == self.last_seen_to_version + 1 {
                self.last_seen_to_version = to_version;
                match self.to_update(raw) {
                    Ok(update) => events.push(MarketDataEvent::BookUpdate(update)),
                    Err(_) => {
                        self.synced = false;
                        break;
                    }
                }
            } else {
                break;
            }
        }

        Ok(events)
    }
}
```

- [ ] **Step 4: Run the tests, confirm they pass**

Run: `cargo test -p exchange_adapter_mexc ws::tests`
Expected: all pass (12 new + 26 previous = 38).

- [ ] **Step 5: Commit**

```bash
git add crates/exchange_adapter_mexc/src/ws.rs
git commit -m "feat(exchange_adapter_mexc): add DepthSync snapshot-resync state machine"
```

---

## Task 5: `Backoff` — reconnect delay schedule

**Files:**
- Modify: `crates/exchange_adapter_mexc/src/ws.rs`

**Interfaces:**
- Consumes: `std::time::Duration`.
- Produces (used by Tasks 7-8):
  - `pub(crate) struct Backoff` with:
    - `pub(crate) fn new(initial: Duration, max: Duration) -> Self`
    - `pub(crate) fn production() -> Self` (returns `Backoff::new(Duration::from_secs(1), Duration::from_secs(30))`)
    - `pub(crate) fn next_delay(&mut self) -> Duration`
    - `pub(crate) fn reset(&mut self)`

This is a direct duplicate of Binance's `Backoff` (identical behavior, no MEXC-specific difference) — adapters are peer crates with no shared-code path for this yet, per this plan's Global Constraints / the design spec's explicit "mirror, don't share" decision.

- [ ] **Step 1: Write the failing tests**

Add to `ws.rs`'s test module:

```rust
#[test]
fn backoff_doubles_each_call_up_to_the_cap() {
    let mut backoff = Backoff::new(Duration::from_secs(1), Duration::from_secs(30));
    assert_eq!(backoff.next_delay(), Duration::from_secs(1));
    assert_eq!(backoff.next_delay(), Duration::from_secs(2));
    assert_eq!(backoff.next_delay(), Duration::from_secs(4));
    assert_eq!(backoff.next_delay(), Duration::from_secs(8));
    assert_eq!(backoff.next_delay(), Duration::from_secs(16));
    assert_eq!(backoff.next_delay(), Duration::from_secs(30));
    assert_eq!(backoff.next_delay(), Duration::from_secs(30));
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

- [ ] **Step 2: Run them, confirm they fail to compile**

Run: `cargo test -p exchange_adapter_mexc ws::tests`
Expected: FAIL — `Backoff` doesn't exist.

- [ ] **Step 3: Implement `Backoff`**

```rust
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

Run: `cargo test -p exchange_adapter_mexc ws::tests`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add crates/exchange_adapter_mexc/src/ws.rs
git commit -m "feat(exchange_adapter_mexc): add Backoff reconnect delay schedule"
```

---

## Task 6: Fake local ws server test fixture

**Files:**
- Modify: `crates/exchange_adapter_mexc/Cargo.toml`
- Create: `crates/exchange_adapter_mexc/tests/wiremock_tests.rs`

**Interfaces:**
- Consumes: `tokio::net::TcpListener`, `tokio_tungstenite::{accept_async, tungstenite::Message}`.
- Produces (used by Tasks 7-8): `async fn spawn_fake_ws_server(connections: Vec<Vec<Message>>) -> url::Url` — a small variant of Binance's fixture that scripts full `Message` values (not just text frames), since MEXC's connections carry a mix of binary (protobuf data) and text (ping/pong, subscribe acks) frames and tests need to script both kinds.

This crate has no existing `tests/wiremock_tests.rs` file yet (unlike `exchange_adapter_binance`, which already had one from earlier REST-only work) — check first with `ls crates/exchange_adapter_mexc/tests/` to confirm, and create the file fresh if it's missing.

- [ ] **Step 1: Add dependencies**

Edit `crates/exchange_adapter_mexc/Cargo.toml`, `[dependencies]` (alphabetical order, matching the file's existing style):

```toml
tokio-tungstenite = { version = "0.24", default-features = false, features = ["connect", "handshake", "rustls-tls-webpki-roots"] }
```

And `[dev-dependencies]`, add `"net"` to tokio's features:

```toml
[dev-dependencies]
tokio = { version = "1.53.1", features = ["rt-multi-thread", "macros", "time", "net"] }
wiremock = "0.6.5"
```

- [ ] **Step 2: Write the failing test**

Create `crates/exchange_adapter_mexc/tests/wiremock_tests.rs`:

```rust
//! Request-building/response-parsing tests against `wiremock` for REST,
//! and a hand-rolled fake local websocket server (no ws-mocking crate
//! exists in this workspace) for the ws tasks added in this plan. See
//! the sibling `exchange_adapter_binance` crate's `tests/wiremock_tests.rs`
//! for the pattern this mirrors.

use std::sync::Arc;

use secrecy::SecretString;
use serde_json::json;
use url::Url;

use exchange_adapter::{AdapterConfig, Pair};
use exchange_adapter_mexc::{ExchangeAdapterMexc, MexcConfig};
use observability::{AlertEvent, Alerts, MetricEvent, Metrics};

use wiremock::matchers::{method, path, query_param};
use wiremock::{Mock, MockServer, ResponseTemplate};

#[derive(Default)]
struct RecordingAlerts {
    events: std::sync::Mutex<Vec<AlertEvent>>,
}

impl Alerts for RecordingAlerts {
    fn fire(&self, alert: AlertEvent) {
        self.events.lock().unwrap().push(alert);
    }
}

#[derive(Default)]
struct RecordingMetrics {
    events: std::sync::Mutex<Vec<MetricEvent>>,
}

impl Metrics for RecordingMetrics {
    fn record(&self, event: MetricEvent) {
        self.events.lock().unwrap().push(event);
    }
}

/// A hand-rolled local websocket server for tests -- there's no
/// ws-mocking crate in this workspace. Accepts connections one at a time
/// on an OS-assigned port; the i-th connection gets `connections[i]`'s
/// messages sent in order, then the server closes that connection.
/// Connections past the end of `connections` find the listener already
/// dropped and get refused immediately.
async fn spawn_fake_ws_server(connections: Vec<Vec<tokio_tungstenite::tungstenite::Message>>) -> Url {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    tokio::spawn(async move {
        for messages in connections {
            let Ok((stream, _)) = listener.accept().await else { break };
            let Ok(mut ws) = tokio_tungstenite::accept_async(stream).await else { continue };
            for message in messages {
                use futures_util::SinkExt;
                if ws.send(message).await.is_err() {
                    break;
                }
            }
            let _ = ws.close(None).await;
        }
    });

    Url::parse(&format!("ws://{addr}")).unwrap()
}

#[tokio::test]
async fn fake_ws_server_sends_scripted_frames_in_order() {
    use futures_util::StreamExt;
    use tokio_tungstenite::tungstenite::Message;

    let url = spawn_fake_ws_server(vec![vec![
        Message::text("first"),
        Message::Binary(vec![1, 2, 3].into()),
    ]])
    .await;

    let (mut ws, _response) = tokio_tungstenite::connect_async(url.as_str()).await.unwrap();
    let first = ws.next().await.unwrap().unwrap();
    let second = ws.next().await.unwrap().unwrap();
    assert_eq!(first.into_text().unwrap(), "first");
    assert_eq!(second.into_data(), vec![1, 2, 3]);
    let _ = ws.close(None).await;
}
```

- [ ] **Step 3: Run it, confirm it fails to compile**

Run: `cargo test -p exchange_adapter_mexc --test wiremock_tests fake_ws_server_sends_scripted_frames_in_order`
Expected: FAIL initially on missing dependencies/imports until Step 1's `Cargo.toml` edit lands, then should compile and pass — if it still fails after the dependency edit, iterate on the exact `tokio-tungstenite` feature flags the same way Binance's Task 1 did (this exact version already proved to resolve cleanly on this workspace during the Binance project, so friction here would be surprising, not expected).

- [ ] **Step 4: Confirm it passes**

Run: `cargo test -p exchange_adapter_mexc --test wiremock_tests fake_ws_server_sends_scripted_frames_in_order`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add crates/exchange_adapter_mexc/Cargo.toml crates/exchange_adapter_mexc/tests/wiremock_tests.rs
git commit -m "test(exchange_adapter_mexc): add fake local ws server fixture"
```

---

## Task 7: Trade ws task

**Files:**
- Modify: `crates/exchange_adapter_mexc/src/ws.rs`
- Modify: `crates/exchange_adapter_mexc/src/lib.rs`
- Modify: `crates/exchange_adapter_mexc/tests/wiremock_tests.rs`

**Interfaces:**
- Consumes: `decode_push`, `MexcPushBody`, `trade_tick_from_raw` (Task 2); `Backoff` (Task 5).
- Produces (used by Task 9): `pub fn trade_stream(ws_base_url: url::Url, pair: Pair, backoff: Backoff, ping_interval: Duration, idle_timeout: Duration, metrics: Arc<dyn Metrics>, alerts: Arc<dyn Alerts>) -> MarketDataStream`

Note the two extra parameters versus Binance's `trade_stream` (`ping_interval`, `idle_timeout`) — both injectable for the same reason `backoff` is: tests need fast schedules, not real multi-second/minute timers. `pub`, not `pub(crate)` — same E0365 constraint Binance's project hit (a `pub(crate)` item can't be re-exported from a `pub mod __test_support` even within the same crate); this plan builds it `pub` from the start rather than discovering the compile error the way Binance's Task 6 did.

- [ ] **Step 1: Write the failing tests**

Add to `wiremock_tests.rs`:

```rust
#[tokio::test]
async fn trade_stream_emits_a_trade_event_from_a_ws_frame() {
    use futures_util::StreamExt;
    use tokio_tungstenite::tungstenite::Message;

    // Byte fixture built the same way ws.rs's own unit tests build one --
    // duplicated here (integration tests can't call ws.rs's private
    // #[cfg(test)] encode helpers) using raw protobuf bytes assembled by
    // hand from the same tag/varint rules, verified against the schema
    // in crates/exchange_adapter_mexc/proto/PublicAggreDealsV3Api.proto
    // and PushDataV3ApiWrapper.proto.
    fn encode_varint(mut v: u64, out: &mut Vec<u8>) {
        loop {
            let mut byte = (v & 0x7F) as u8;
            v >>= 7;
            if v != 0 { byte |= 0x80; }
            out.push(byte);
            if v == 0 { break; }
        }
    }
    fn tag(field: u32, wt: u8, out: &mut Vec<u8>) {
        encode_varint(((field as u64) << 3) | wt as u64, out);
    }
    fn string_field(field: u32, s: &str, out: &mut Vec<u8>) {
        tag(field, 2, out);
        encode_varint(s.len() as u64, out);
        out.extend_from_slice(s.as_bytes());
    }
    fn int64_field(field: u32, v: i64, out: &mut Vec<u8>) {
        tag(field, 0, out);
        encode_varint(v as u64, out);
    }
    fn message_field(field: u32, bytes: &[u8], out: &mut Vec<u8>) {
        tag(field, 2, out);
        encode_varint(bytes.len() as u64, out);
        out.extend_from_slice(bytes);
    }

    let mut deal_item = Vec::new();
    string_field(1, "100.5", &mut deal_item);
    string_field(2, "0.01", &mut deal_item);
    tag(3, 0, &mut deal_item);
    encode_varint(1, &mut deal_item); // tradeType 1 = Buy
    int64_field(4, 999, &mut deal_item);
    string_field(5, "42", &mut deal_item);

    let mut deals_msg = Vec::new();
    message_field(1, &deal_item, &mut deals_msg);

    let mut wrapper = Vec::new();
    string_field(1, "spot@public.aggre.deals.v3.api.pb@100ms@BTCUSDT", &mut wrapper);
    message_field(314, &deals_msg, &mut wrapper);
    int64_field(6, 1000, &mut wrapper);

    let ws_url = spawn_fake_ws_server(vec![vec![Message::Binary(wrapper.into())]]).await;

    let metrics = Arc::new(RecordingMetrics::default());
    let alerts = Arc::new(RecordingAlerts::default());
    let mut stream = exchange_adapter_mexc::__test_support::trade_stream(
        ws_url,
        Pair("BTCUSDT".to_string()),
        exchange_adapter_mexc::__test_support::Backoff::new(
            std::time::Duration::from_millis(1),
            std::time::Duration::from_millis(5),
        ),
        std::time::Duration::from_millis(50),
        std::time::Duration::from_secs(5),
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
async fn trade_stream_sends_a_ping_frame_on_its_own_schedule() {
    use futures_util::StreamExt;
    use tokio_tungstenite::tungstenite::Message;

    // No data ever arrives on this connection -- if the ping loop isn't
    // running independently of the read loop, nothing would ever be
    // sent back to the server, and this test's manual read below would
    // hang until its own timeout.
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let ws_url = Url::parse(&format!("ws://{addr}")).unwrap();

    let server_task = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        use futures_util::StreamExt as _;
        ws.next().await.unwrap().unwrap()
    });

    let metrics = Arc::new(RecordingMetrics::default());
    let alerts = Arc::new(RecordingAlerts::default());
    let _stream = exchange_adapter_mexc::__test_support::trade_stream(
        ws_url,
        Pair("BTCUSDT".to_string()),
        exchange_adapter_mexc::__test_support::Backoff::new(
            std::time::Duration::from_millis(1),
            std::time::Duration::from_millis(5),
        ),
        std::time::Duration::from_millis(20), // fast ping interval for the test
        std::time::Duration::from_secs(5),
        metrics,
        alerts,
    );

    let received = tokio::time::timeout(std::time::Duration::from_secs(2), server_task)
        .await
        .expect("a ping should arrive before the timeout")
        .unwrap();
    let Message::Text(text) = received else { panic!("expected a text ping frame, got {received:?}") };
    assert!(text.contains("PING"), "expected a PING message, got: {text}");
}
```

- [ ] **Step 2: Add the test-support re-export**

In `crates/exchange_adapter_mexc/src/lib.rs`, after the existing `pub use config::MexcConfig;` line:

```rust
/// Re-exports internal ws plumbing for integration tests in `tests/`
/// only -- not part of this crate's real API. `#[doc(hidden)]` keeps it
/// out of generated docs; nothing outside this crate's own test suite
/// should ever import it. Items here are `pub` (not `pub(crate)`) only
/// because Rust forbids re-exporting a `pub(crate)` item as `pub` even
/// from within the defining crate (E0365) -- `mod ws;` itself stays
/// private below, so nothing here is reachable except through this
/// explicit path.
#[doc(hidden)]
pub mod __test_support {
    pub use crate::ws::{trade_stream, Backoff};
}
```

- [ ] **Step 3: Run the tests, confirm they fail to compile**

Run: `cargo test -p exchange_adapter_mexc --test wiremock_tests trade_stream`
Expected: FAIL — `ws::trade_stream` doesn't exist yet.

- [ ] **Step 4: Implement `trade_stream`**

Add to `ws.rs`:

```rust
use std::sync::Arc;

use exchange_adapter::{MarketDataStream, Pair};
use observability::{AlertEvent, AlertKind, Alerts, MetricEvent, Metrics, Severity};

const CONSECUTIVE_FAILURES_BEFORE_ALERT: u32 = 5;
const STABLE_CONNECTION_THRESHOLD: Duration = Duration::from_secs(60);

fn record_ws_failure(
    metrics: &Arc<dyn Metrics>,
    alerts: &Arc<dyn Alerts>,
    stream_tag: &'static str,
    consecutive_failures: u32,
    message: &str,
) {
    metrics.record(
        MetricEvent::new("mexc_ws_reconnect_error_count", 1.0).with_tag("stream", stream_tag),
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

/// MEXC's ping/pong is an application-level JSON control message
/// (`{"method":"PING"}` / `{"msg":"PONG"}`), not the WebSocket
/// protocol-level ping/pong frame `tokio-tungstenite` answers
/// automatically -- Binance never needed this because its server pings
/// the client, handled transparently underneath. Without an explicit
/// client-side ping, a quiet subscription (even on a perfectly healthy
/// connection) hits MEXC's 60-second no-data-flow disconnect for no
/// real reason.
fn mexc_ping_message() -> tokio_tungstenite::tungstenite::Message {
    tokio_tungstenite::tungstenite::Message::text(r#"{"method":"PING"}"#)
}

pub fn trade_stream(
    ws_base_url: url::Url,
    pair: Pair,
    mut backoff: Backoff,
    ping_interval: Duration,
    idle_timeout: Duration,
    metrics: Arc<dyn Metrics>,
    alerts: Arc<dyn Alerts>,
) -> MarketDataStream {
    Box::pin(async_stream::stream! {
        let mut consecutive_failures: u32 = 0;
        loop {
            let mut ws = match tokio_tungstenite::connect_async(ws_base_url.as_str()).await {
                Ok((ws, _response)) => ws,
                Err(e) => {
                    consecutive_failures += 1;
                    record_ws_failure(&metrics, &alerts, "trade", consecutive_failures, &e.to_string());
                    tokio::time::sleep(backoff.next_delay()).await;
                    continue;
                }
            };

            let subscribe = tokio_tungstenite::tungstenite::Message::text(format!(
                r#"{{"method":"SUBSCRIPTION","params":["spot@public.aggre.deals.v3.api.pb@100ms@{}"]}}"#,
                pair.0
            ));
            {
                use futures_util::SinkExt;
                if ws.send(subscribe).await.is_err() {
                    consecutive_failures += 1;
                    record_ws_failure(&metrics, &alerts, "trade", consecutive_failures, "subscribe send failed");
                    tokio::time::sleep(backoff.next_delay()).await;
                    continue;
                }
            }

            let connected_at = tokio::time::Instant::now();
            let mut ping_ticker = tokio::time::interval(ping_interval);
            ping_ticker.tick().await; // first tick fires immediately; consume it before the loop

            loop {
                use futures_util::{SinkExt, StreamExt};
                tokio::select! {
                    _ = ping_ticker.tick() => {
                        if ws.send(mexc_ping_message()).await.is_err() {
                            break;
                        }
                    }
                    frame = tokio::time::timeout(idle_timeout, ws.next()) => {
                        match frame {
                            Ok(Some(Ok(message))) => {
                                let bytes = message.into_data();
                                let Some(push) = decode_push(&bytes) else { continue };
                                if let MexcPushBody::Trade(deals) = push.body {
                                    for deal in &deals.deals {
                                        if let Ok(tick) = trade_tick_from_raw(&pair, deal) {
                                            yield MarketDataEvent::Trade(tick);
                                        }
                                    }
                                }
                            }
                            Ok(Some(Err(_))) | Ok(None) | Err(_) => break,
                        }
                    }
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

Note on `message.into_data()`: this returns a plain `Vec<u8>` (verified against `tungstenite` 0.24's source — `Message::Text(s) => s.into_bytes()`, `Binary(data) => data`, no `Result`, no fallibility). A JSON control frame (a subscribe ack, or MEXC's `{"msg":"PONG"}`) arriving as `Message::Text` still produces bytes here, and `decode_push` handles that safely without any special-casing: its very first `read_tag()` call interprets the JSON's leading `{` (`0x7B`) as a one-byte varint (`123`, no continuation bit), splitting into field number `15` and wire type `3` — wire type `3` ("start group") isn't one of the four `WireReader::skip_field` handles, so `skip_field` returns `None`, and the `?` inside `decode_push`'s field-matching loop propagates that `None` straight out of `decode_push` itself. So a JSON control frame reliably decodes to `None` (never a panic, never a garbage-decoded struct) and gets skipped by the `let Some(push) = decode_push(&bytes) else { continue };` line exactly as intended — no extra `Message::Text` special case needed.

- [ ] **Step 5: Run the tests, confirm they pass**

Run: `cargo test -p exchange_adapter_mexc --test wiremock_tests trade_stream`
Expected: both tests pass, quickly (fast injected `Backoff`/ping interval).

- [ ] **Step 6: Run the whole crate's tests**

Run: `cargo test -p exchange_adapter_mexc`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add crates/exchange_adapter_mexc/src/ws.rs crates/exchange_adapter_mexc/src/lib.rs crates/exchange_adapter_mexc/tests/wiremock_tests.rs
git commit -m "feat(exchange_adapter_mexc): add trade_stream ws task with ping keepalive"
```

---

## Task 8: Book-diff ws task

**Files:**
- Modify: `crates/exchange_adapter_mexc/src/ws.rs`
- Modify: `crates/exchange_adapter_mexc/src/lib.rs`
- Modify: `crates/exchange_adapter_mexc/tests/wiremock_tests.rs`

**Interfaces:**
- Consumes: `DepthSync`, `DepthSyncOutcome`, `DepthSnapshot`, `decode_push`, `MexcPushBody`, `Backoff` (Tasks 2/4/5); `crate::http::RestClient`; `crate::endpoints::SPOT_DEPTH`.
- Produces (used by Task 9): `pub fn book_stream(ws_base_url: url::Url, rest: Arc<RestClient>, pair: Pair, backoff: Backoff, ping_interval: Duration, idle_timeout: Duration, metrics: Arc<dyn Metrics>, alerts: Arc<dyn Alerts>) -> MarketDataStream`

`rest: Arc<RestClient>` (not a bare `RestClient`) since `SpotStyleAccount` already stores it that way (see `spot.rs`) — cheaper to clone than Binance's approach needed.

- [ ] **Step 1: Write the failing tests**

Add to `wiremock_tests.rs`. Needs a byte-fixture builder for depth messages (same hand-rolled encode approach as Task 7's trade test) and a REST mock for the snapshot fetch:

```rust
fn encode_varint(mut v: u64, out: &mut Vec<u8>) {
    loop {
        let mut byte = (v & 0x7F) as u8;
        v >>= 7;
        if v != 0 { byte |= 0x80; }
        out.push(byte);
        if v == 0 { break; }
    }
}
fn tag(field: u32, wt: u8, out: &mut Vec<u8>) {
    encode_varint(((field as u64) << 3) | wt as u64, out);
}
fn string_field(field: u32, s: &str, out: &mut Vec<u8>) {
    tag(field, 2, out);
    encode_varint(s.len() as u64, out);
    out.extend_from_slice(s.as_bytes());
}
fn message_field(field: u32, bytes: &[u8], out: &mut Vec<u8>) {
    tag(field, 2, out);
    encode_varint(bytes.len() as u64, out);
    out.extend_from_slice(bytes);
}

fn encode_depth_push(from_version: &str, to_version: &str, bid_price: &str, bid_qty: &str) -> Vec<u8> {
    let mut item = Vec::new();
    string_field(1, bid_price, &mut item);
    string_field(2, bid_qty, &mut item);

    let mut depths = Vec::new();
    message_field(2, &item, &mut depths); // field 2 = bids
    string_field(4, from_version, &mut depths);
    string_field(5, to_version, &mut depths);

    let mut wrapper = Vec::new();
    string_field(1, "spot@public.aggre.depth.v3.api.pb@100ms@BTCUSDT", &mut wrapper);
    message_field(313, &depths, &mut wrapper);
    wrapper
}

fn test_rest_client(mock_uri: &str) -> Arc<exchange_adapter_mexc::__test_support::RestClient> {
    let metrics = Arc::new(RecordingMetrics::default());
    let alerts = Arc::new(RecordingAlerts::default());
    Arc::new(
        exchange_adapter_mexc::__test_support::RestClient::new(
            Url::parse(mock_uri).unwrap(),
            SecretString::from("test-key".to_string()),
            SecretString::from("test-secret".to_string()),
            5000,
            metrics,
            alerts,
            exchange_adapter_mexc::__test_support::Surface::Spot,
        )
        .unwrap(),
    )
}

#[tokio::test]
async fn book_stream_happy_path_emits_snapshot_then_sequential_updates() {
    use futures_util::StreamExt;
    use tokio_tungstenite::tungstenite::Message;

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
        Message::Binary(encode_depth_push("155", "165", "99", "2").into()),
        Message::Binary(encode_depth_push("166", "170", "99", "3").into()),
    ]])
    .await;

    let rest = test_rest_client(&rest_server.uri());
    let metrics = Arc::new(RecordingMetrics::default());
    let alerts = Arc::new(RecordingAlerts::default());
    let mut stream = exchange_adapter_mexc::__test_support::book_stream(
        ws_url,
        rest,
        Pair("BTCUSDT".to_string()),
        exchange_adapter_mexc::__test_support::Backoff::new(
            std::time::Duration::from_millis(1),
            std::time::Duration::from_millis(5),
        ),
        std::time::Duration::from_millis(50),
        std::time::Duration::from_secs(5),
        metrics,
        alerts,
    );

    let first = tokio::time::timeout(std::time::Duration::from_secs(5), stream.next()).await.unwrap().unwrap();
    let second = tokio::time::timeout(std::time::Duration::from_secs(5), stream.next()).await.unwrap().unwrap();
    let third = tokio::time::timeout(std::time::Duration::from_secs(5), stream.next()).await.unwrap().unwrap();

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
async fn book_stream_resyncs_after_a_ws_disconnect() {
    use futures_util::StreamExt;
    use tokio_tungstenite::tungstenite::Message;

    let rest_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/api/v3/depth"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "lastUpdateId": 160, "bids": [["99", "1"]], "asks": []
        })))
        .mount(&rest_server)
        .await;

    let ws_url = spawn_fake_ws_server(vec![
        vec![Message::Binary(encode_depth_push("155", "165", "99", "2").into())],
        vec![Message::Binary(encode_depth_push("155", "165", "99", "5").into())],
    ])
    .await;

    let rest = test_rest_client(&rest_server.uri());
    let metrics = Arc::new(RecordingMetrics::default());
    let alerts = Arc::new(RecordingAlerts::default());
    let mut stream = exchange_adapter_mexc::__test_support::book_stream(
        ws_url,
        rest,
        Pair("BTCUSDT".to_string()),
        exchange_adapter_mexc::__test_support::Backoff::new(
            std::time::Duration::from_millis(1),
            std::time::Duration::from_millis(5),
        ),
        std::time::Duration::from_millis(50),
        std::time::Duration::from_secs(5),
        metrics,
        alerts,
    );

    let mut snapshot_count = 0;
    for _ in 0..4 {
        let event = tokio::time::timeout(std::time::Duration::from_secs(5), stream.next()).await.unwrap().unwrap();
        if matches!(event, exchange_adapter::MarketDataEvent::BookSnapshot(_)) {
            snapshot_count += 1;
        }
    }
    assert_eq!(snapshot_count, 2, "expected one snapshot for the initial sync and one for the post-disconnect resync");
}
```

- [ ] **Step 2: Extend `__test_support`**

In `crates/exchange_adapter_mexc/src/lib.rs`, replace Task 7's narrower `__test_support` with:

```rust
#[doc(hidden)]
pub mod __test_support {
    pub use crate::http::{RestClient, Surface};
    pub use crate::ws::{book_stream, trade_stream, Backoff};
}
```

`RestClient` and `Surface` are currently `pub(crate)` in `http.rs` — promote both (the struct and its `new` constructor) to `pub`, same E0365 reasoning as `Backoff`/`trade_stream`. Keep `RestClient`'s other methods (`signed_spot_style`, `signed_futures_style`, `public_get`) `pub(crate)` — nothing outside the crate calls them directly.

- [ ] **Step 3: Run the tests, confirm they fail to compile**

Run: `cargo test -p exchange_adapter_mexc --test wiremock_tests book_stream`
Expected: FAIL — `ws::book_stream` doesn't exist, `RestClient`/`Surface` not yet `pub`.

- [ ] **Step 4: Implement `book_stream`**

Add to `ws.rs`:

```rust
use crate::endpoints::SPOT_DEPTH;
use crate::http::RestClient;

async fn fetch_depth_snapshot(rest: &RestClient, pair: &Pair) -> Result<DepthSnapshot, AdapterError> {
    let value = rest
        .public_get(
            SPOT_DEPTH,
            &[("symbol".to_string(), pair.0.clone()), ("limit".to_string(), "1000".to_string())],
        )
        .await?;
    let last_update_id = value
        .get("lastUpdateId")
        .and_then(serde_json::Value::as_u64)
        .ok_or_else(|| AdapterError::InvalidRequest("depth snapshot missing lastUpdateId".to_string()))?;
    let bids = parse_level_rows(value.get("bids"))?;
    let asks = parse_level_rows(value.get("asks"))?;
    Ok(DepthSnapshot { last_update_id, bids, asks })
}

fn parse_level_rows(value: Option<&serde_json::Value>) -> Result<Vec<RawDepthItem>, AdapterError> {
    value
        .and_then(serde_json::Value::as_array)
        .ok_or_else(|| AdapterError::InvalidRequest("depth snapshot: expected an array".to_string()))?
        .iter()
        .map(|row| {
            let row = row
                .as_array()
                .ok_or_else(|| AdapterError::InvalidRequest("depth snapshot: expected [price, qty]".to_string()))?;
            let price = row.first().and_then(serde_json::Value::as_str)
                .ok_or_else(|| AdapterError::InvalidRequest("depth snapshot: missing price".to_string()))?;
            let qty = row.get(1).and_then(serde_json::Value::as_str)
                .ok_or_else(|| AdapterError::InvalidRequest("depth snapshot: missing qty".to_string()))?;
            Ok(RawDepthItem { price: price.to_string(), quantity: qty.to_string() })
        })
        .collect()
}

pub fn book_stream(
    ws_base_url: url::Url,
    rest: Arc<RestClient>,
    pair: Pair,
    mut backoff: Backoff,
    ping_interval: Duration,
    idle_timeout: Duration,
    metrics: Arc<dyn Metrics>,
    alerts: Arc<dyn Alerts>,
) -> MarketDataStream {
    Box::pin(async_stream::stream! {
        let mut sync = DepthSync::new(pair.clone());
        let mut consecutive_failures: u32 = 0;

        loop {
            let mut ws = match tokio_tungstenite::connect_async(ws_base_url.as_str()).await {
                Ok((ws, _response)) => ws,
                Err(e) => {
                    consecutive_failures += 1;
                    record_ws_failure(&metrics, &alerts, "book", consecutive_failures, &e.to_string());
                    tokio::time::sleep(backoff.next_delay()).await;
                    continue;
                }
            };
            sync.mark_disconnected();

            let subscribe = tokio_tungstenite::tungstenite::Message::text(format!(
                r#"{{"method":"SUBSCRIPTION","params":["spot@public.aggre.depth.v3.api.pb@100ms@{}"]}}"#,
                pair.0
            ));
            {
                use futures_util::SinkExt;
                if ws.send(subscribe).await.is_err() {
                    consecutive_failures += 1;
                    record_ws_failure(&metrics, &alerts, "book", consecutive_failures, "subscribe send failed");
                    tokio::time::sleep(backoff.next_delay()).await;
                    continue;
                }
            }

            match fetch_depth_snapshot(&rest, &pair).await {
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
            let mut ping_ticker = tokio::time::interval(ping_interval);
            ping_ticker.tick().await;

            loop {
                use futures_util::{SinkExt, StreamExt};
                tokio::select! {
                    _ = ping_ticker.tick() => {
                        if ws.send(mexc_ping_message()).await.is_err() {
                            break;
                        }
                    }
                    frame = tokio::time::timeout(idle_timeout, ws.next()) => {
                        match frame {
                            Ok(Some(Ok(message))) => {
                                let bytes = message.into_data();
                                let Some(push) = decode_push(&bytes) else { continue };
                                if let MexcPushBody::Depth(depths) = push.body {
                                    match sync.on_event(depths) {
                                        DepthSyncOutcome::Update(update) => yield MarketDataEvent::BookUpdate(update),
                                        DepthSyncOutcome::Buffering => {}
                                        DepthSyncOutcome::Desynced => {
                                            desynced = true;
                                            break;
                                        }
                                    }
                                }
                            }
                            Ok(Some(Err(_))) | Ok(None) | Err(_) => break,
                        }
                    }
                }
            }

            if desynced {
                tokio::time::sleep(DESYNC_RETRY_DELAY).await;
                continue;
            }

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

/// A desync is routine protocol behavior, not a connection failure -- it
/// stays exempt from `consecutive_failures`/backoff, but still needs a
/// floor so a pathologically desyncing stream can't hot-loop TLS
/// handshakes and REST depth calls. Same reasoning and same value as
/// Binance's equivalent constant.
const DESYNC_RETRY_DELAY: Duration = Duration::from_millis(500);
```

`message.into_data()` returns a plain `Vec<u8>` (see Task 7's note for the verified detail) — no `Result`, no extra conversion needed here either.

- [ ] **Step 5: Run the tests, confirm they pass**

Run: `cargo test -p exchange_adapter_mexc --test wiremock_tests book_stream`
Expected: both tests pass.

- [ ] **Step 6: Run the whole crate's tests**

Run: `cargo test -p exchange_adapter_mexc`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add crates/exchange_adapter_mexc/src/ws.rs crates/exchange_adapter_mexc/src/lib.rs crates/exchange_adapter_mexc/tests/wiremock_tests.rs
git commit -m "feat(exchange_adapter_mexc): add book_stream ws task with snapshot resync"
```

---

## Task 9: Wire ws streams into `subscribe_market_data`

**Files:**
- Modify: `crates/exchange_adapter_mexc/src/spot.rs`
- Modify: `crates/exchange_adapter_mexc/src/lib.rs`
- Modify: `crates/exchange_adapter_mexc/tests/wiremock_tests.rs`

**Interfaces:**
- Consumes: `ws::book_stream`, `ws::trade_stream`, `ws::Backoff` (Tasks 7-8); `futures_util::stream::select`.
- Produces: `SpotStyleAccount::new` gains one parameter, `ws_base_url: Url` (metrics/alerts are already fields on `SpotStyleAccount` — no new params needed for those, unlike Binance's equivalent task).

- [ ] **Step 1: Add `ws_base_url` to `SpotStyleAccount`**

In `spot.rs`, add the field:

```rust
#[derive(Clone)]
pub(crate) struct SpotStyleAccount {
    kind: SpotStyleKind,
    rest: Arc<RestClient>,
    ws_base_url: url::Url,
    order_cache: OrderIdCache,
    metrics: Arc<dyn Metrics>,
    alerts: Arc<dyn Alerts>,
    market_data_poll_interval_ms: u64,
    account_poll_interval_ms: u64,
    stale_after_ms: u64,
}
```

Update `new`:

```rust
pub(crate) fn new(
    kind: SpotStyleKind,
    rest: Arc<RestClient>,
    ws_base_url: url::Url,
    metrics: Arc<dyn Metrics>,
    alerts: Arc<dyn Alerts>,
    market_data_poll_interval_ms: u64,
    account_poll_interval_ms: u64,
    stale_after_ms: u64,
) -> Self {
    Self {
        kind,
        rest,
        ws_base_url,
        order_cache: OrderIdCache::new(),
        metrics,
        alerts,
        market_data_poll_interval_ms,
        account_poll_interval_ms,
        stale_after_ms,
    }
}
```

Add `use crate::ws;` at the top of `spot.rs`.

- [ ] **Step 2: Rewrite `subscribe_market_data`**

Replace the current body:

```rust
async fn subscribe_market_data(&self, pair: Pair) -> Result<MarketDataStream, AdapterError> {
    let rest = self.rest.clone();
    let metrics = self.metrics.clone();
    let alerts = self.alerts.clone();
    let interval_ms = self.market_data_poll_interval_ms;
    let stale_after_ms = self.stale_after_ms;

    let candles = polling::market_data_poll_stream(
        interval_ms,
        stale_after_ms,
        metrics.clone(),
        alerts.clone(),
        move || {
            let rest = rest.clone();
            let pair = pair.clone();
            async move {
                let value = rest
                    .public_get(
                        SPOT_KLINES,
                        &[
                            ("symbol".to_string(), pair.0.clone()),
                            ("interval".to_string(), "1m".to_string()),
                            ("limit".to_string(), "1".to_string()),
                        ],
                    )
                    .await?;
                let row = value
                    .as_array()
                    .and_then(|rows| rows.last())
                    .ok_or_else(|| AdapterError::Network("empty klines response".into()))?;
                let candle = parse_spot_kline_row(&pair, "1m", row).ok_or_else(|| {
                    AdapterError::Network("failed to parse kline row".into())
                })?;
                Ok(MarketDataEvent::Candle(candle))
            }
        },
    );

    let book = ws::book_stream(
        self.ws_base_url.clone(),
        self.rest.clone(),
        pair.clone(),
        ws::Backoff::production(),
        std::time::Duration::from_secs(20),
        std::time::Duration::from_secs(45),
        self.metrics.clone(),
        self.alerts.clone(),
    );
    let trade = ws::trade_stream(
        self.ws_base_url.clone(),
        pair.clone(),
        ws::Backoff::production(),
        std::time::Duration::from_secs(20),
        std::time::Duration::from_secs(45),
        self.metrics.clone(),
        self.alerts.clone(),
    );

    Ok(Box::pin(futures_util::stream::select(
        futures_util::stream::select(book, trade),
        Box::pin(candles),
    )))
}
```

(`candles` was already a `Pin<Box<dyn Stream<...>>>` returned by `polling::market_data_poll_stream` per that function's existing signature — confirm this against `polling.rs` at implementation time; if it's already boxed/pinned, the `Box::pin(candles)` wrap in the final `stream::select` call may be redundant — check whether the compiler accepts `candles` directly in `stream::select` without an extra wrap, and drop the wrap if so. Binance's equivalent candle stream was NOT pre-boxed (a bare `filter_map` combinator) and needed the wrap; MEXC's `polling::market_data_poll_stream` already returns `Pin<Box<dyn Stream<Item = MarketDataEvent> + Send>>` per its existing signature in `polling.rs`, so this crate's case may already be fine without the extra `Box::pin`.)

Update the doc comment on `subscribe_market_data` to describe the merged three-source behavior instead of the old single-poll description.

- [ ] **Step 3: Update `lib.rs`'s two `SpotStyleAccount::new` call sites**

In `ExchangeAdapterMexc::new`, the `spot`/`margin` construction currently doesn't pass `ws_base_url` (the field doesn't exist yet before Step 1). Add it — both share `spot_cfg.ws_base_url`:

```rust
let spot = SpotStyleAccount::new(
    SpotStyleKind::Spot,
    spot_rest,
    spot_cfg.ws_base_url.clone(),
    metrics.clone(),
    alerts.clone(),
    spot_market_poll_ms,
    spot_account_poll_ms,
    spot_stale_after_ms,
);
let margin = SpotStyleAccount::new(
    SpotStyleKind::Margin,
    margin_rest,
    spot_cfg.ws_base_url.clone(),
    metrics.clone(),
    alerts.clone(),
    spot_market_poll_ms,
    spot_account_poll_ms,
    spot_stale_after_ms,
);
```

Note `spot_cfg.ws_base_url` must still be readable at this point in `new` — check whether `spot_cfg` was already destructured/moved earlier in the function (per the existing code, `let MexcConfig { spot: spot_cfg, futures: futures_cfg } = config;` at the top, followed by several `extra_u64(&spot_cfg, ...)` calls that borrow, not move) — `spot_cfg.rest_base_url.clone()` was already being read for `spot_rest`'s construction earlier in the function, so `spot_cfg` is still alive and `.ws_base_url` is readable the same way; if the compiler disagrees (e.g. an intervening move), adjust by cloning `ws_base_url` out earlier alongside the other `spot_cfg` field reads, mirroring how `rest_base_url` is already handled.

- [ ] **Step 4: Fix the compile ripple**

Run: `cargo build -p exchange_adapter_mexc 2>&1 | head -100`

Iterate on whatever the compiler reports (likely just the `Box::pin(candles)` question from Step 2 and the `spot_cfg.ws_base_url` borrow-timing question from Step 3) until clean.

- [ ] **Step 5: Write the end-to-end integration test**

Add to `wiremock_tests.rs`:

```rust
#[tokio::test]
async fn subscribe_market_data_merges_book_trade_and_candle_events() {
    use futures_util::StreamExt;
    use tokio_tungstenite::tungstenite::Message;

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

    let mut deal_item = Vec::new();
    string_field(1, "1", &mut deal_item);
    string_field(2, "1", &mut deal_item);
    tag(3, 0, &mut deal_item);
    encode_varint(1, &mut deal_item);
    let mut int64_buf = Vec::new();
    tag(4, 0, &mut int64_buf);
    encode_varint(1, &mut int64_buf);
    deal_item.extend_from_slice(&int64_buf);
    string_field(5, "1", &mut deal_item);
    let mut deals_msg = Vec::new();
    message_field(1, &deal_item, &mut deals_msg);
    let mut trade_wrapper = Vec::new();
    string_field(1, "spot@public.aggre.deals.v3.api.pb@100ms@BTCUSDT", &mut trade_wrapper);
    message_field(314, &deals_msg, &mut trade_wrapper);

    // Two connections: book_stream dials first deterministically (left
    // operand of the inner stream::select, same ordering property
    // Binance's equivalent test relies on -- see that project's Task 8
    // for the full explanation), so the first scripted connection can be
    // empty (book_stream still gets its BookSnapshot from the REST
    // resync regardless of ws content) and the second carries the trade.
    let ws_url = spawn_fake_ws_server(vec![
        vec![],
        vec![Message::Binary(trade_wrapper.into())],
    ])
    .await;

    let mut config = MexcConfig {
        spot: AdapterConfig {
            api_key: SecretString::from("test-key".to_string()),
            api_secret: SecretString::from("test-secret".to_string()),
            rest_base_url: Url::parse(&rest_server.uri()).unwrap(),
            ws_base_url: ws_url,
            extra: std::collections::HashMap::from([
                ("market_data_poll_interval_ms".to_string(), "10".to_string()),
            ]),
        },
        futures: AdapterConfig {
            api_key: SecretString::from("test-key".to_string()),
            api_secret: SecretString::from("test-secret".to_string()),
            rest_base_url: Url::parse("https://contract.mexc.com").unwrap(),
            ws_base_url: Url::parse("wss://contract.mexc.com/edge").unwrap(),
            extra: std::collections::HashMap::new(),
        },
    };
    let metrics = Arc::new(RecordingMetrics::default());
    let alerts = Arc::new(RecordingAlerts::default());
    let adapter = ExchangeAdapterMexc::new(config, metrics, alerts).unwrap();

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

This test reuses the `string_field`/`tag`/`message_field`/`encode_varint` helpers defined earlier in this same file (Task 8's additions) — no new helpers needed. `MexcConfig`/`AdapterConfig`/`ExchangeAdapterMexc` are already imported at the top of `wiremock_tests.rs` from Task 6; if this is the first test needing `std::collections::HashMap` directly, add the import.

- [ ] **Step 6: Run it, then the full crate and workspace suites**

Run: `cargo test -p exchange_adapter_mexc --test wiremock_tests subscribe_market_data_merges_book_trade_and_candle_events`
Expected: PASS.

Run: `cargo test -p exchange_adapter_mexc && cd .. && cargo test --workspace` (adjust the `cd` to actually reach the `trade_executor` repo root from wherever the shell currently is).
Expected: all green, including crates untouched by this plan.

- [ ] **Step 7: Commit**

```bash
git add crates/exchange_adapter_mexc/src/spot.rs crates/exchange_adapter_mexc/src/lib.rs crates/exchange_adapter_mexc/tests/wiremock_tests.rs
git commit -m "feat(exchange_adapter_mexc): merge ws book/trade streams into subscribe_market_data"
```

---

## Task 10: Update `NOTES.md` and the L0 plan

**Files:**
- Modify: `crates/exchange_adapter_mexc/NOTES.md`
- Modify: `external/executor/plans/02-L0-exchange-adapter.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Update `NOTES.md` §1**

Read the current §1 ("Not real websocket streaming — REST polling instead") and rewrite it to reflect the new state for spot/margin: book/trade are now real protobuf-decoded ws (summarize the sync/resync/backoff/ping-keepalive behavior at the level of detail a future reader needs), `Candle` is still REST-polled (deliberately, out of scope per the spec), account updates are still REST poll-and-diff (also deliberately out of scope), and MEXC futures market data remains entirely unbuilt (tracked as the next follow-up). Link to `external/executor/specs/2026-09-06-mexc-spot-market-data-websocket-design.md` rather than duplicating it.

- [ ] **Step 2: Update `external/executor/plans/02-L0-exchange-adapter.md`'s "Known gaps" list**

Amend the bullet that currently reads something like "MEXC still has no websocket for book/trade" to reflect that MEXC spot/margin now has real ws, while MEXC futures market data remains the open, tracked gap.

- [ ] **Step 3: Commit**

```bash
git add crates/exchange_adapter_mexc/NOTES.md external/executor/plans/02-L0-exchange-adapter.md
git commit -m "docs(exchange_adapter_mexc): update NOTES.md and L0 plan for ws book/trade support"
```

Note: `external/executor/` is a separate git repository from `trade_executor/` — confirm which repo you're in (`git rev-parse --show-toplevel`) before each commit, same as Binance's project required.

---

## Self-Review Notes (for whoever executes this plan)

- **Spec coverage:** every section of the design spec maps to a task — protobuf decoding → Tasks 1-2, sync procedure → Task 4 (with the `bridged` fix present from the start, not discovered via a fix round), reconnect policy → Task 5 + Tasks 7-8's loops, ping keepalive → Tasks 7-8 explicitly, testing approach → Task 6, out-of-scope items (futures, account push, shared L0 abstraction) are simply untouched.
- **Known-in-advance fixes applied proactively:** this plan bakes in three things Binance's project only found via its final review — the `bridged` post-resync state, the stable-connection-gated backoff reset (never reset on bare connect success), and an idle/read timeout on both tasks. If review still finds something wrong with any of these, that's a genuine new finding, not a repeat of an already-known lesson.
- **New-to-this-project risk surface, given extra scrutiny in this plan:** the hand-rolled protobuf decoder (Tasks 1-2, tested via round-tripped byte fixtures rather than hand-typed literals) and the client-initiated ping loop (Tasks 7-8, tested via an injectable fast interval and a fake server that asserts a real `PING` frame arrives).
- **Type consistency check:** `book_stream`/`trade_stream`'s signatures are defined once each (Tasks 7 and 8) and consumed once (Task 9) — no earlier task calls a signature Task 9 changes.
