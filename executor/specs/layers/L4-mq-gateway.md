# L4 — mq_gateway

Part of [architecture index](../2026-09-04-architecture-design.md).

## Purpose

Boundary to `main/` (Python). Transport-abstracted so Redis/NATS/
ZeroMQ can be chosen later without touching `execution`.

## Responsibilities

- Inbound: trade decisions (open/close/modify: side, entry, SL,
  TP) + watch-levels from main/'s Levels module, + force signals
  (force-close, override local risk) — same channel/path as regular
  decisions, not a separate side channel.
- Inbound: **standalone `indicator_update` readings** from main/
  (added 2026-09-20, built — see
  [level-broadcast-design.md](../2026-09-19-level-broadcast-design.md)):
  a named value with its own validity window, published independently
  of any trade decision. Same inbound topic and the same dedup
  id-space as decisions/force, distinguished only by `"type"` — not a
  separate channel, and never a shortcut into `execution`: an
  `indicator_update` produces no `TradeDecision` and reaches no
  execution path at all, it is persisted by L5 and inert until some
  future spec's checking logic reads it back.
- Dedup every inbound message by its decision id — redelivery
  (at-least-once transport) is a no-op.
- Outbound: position/fill state changes back to main/ (opened, closed,
  stopped out, fills, current position state).
- Force actions still go through the exchange-native-order-first
  safety path in `execution` — this layer does not grant a shortcut.

## Message structures (wire format)

This is the actual contract main/ (Python) codes against — defined
now, independent of which transport gets picked later. Two topics,
one schema each, both a thin JSON envelope plus a type-specific
payload:

**Inbound topic** (main/ → executor) — the endpoint main/ publishes
trade decisions and force actions onto:

```json
{
  "id": "<uuid>",
  "type": "open" | "close" | "modify" | "force_close" | "force_override",
  "payload": { ... }
}
```

`open`/`close`/`modify` payload (a `TradeDecision` — per L2's
corrected doc: no size, no firing window):
```json
{
  "pair": "BTCUSDT",
  "side": "long" | "short",
  "timeframe": "m1" | "m5" | "m15" | "m60" | "m240",
  "levels": [
    {"kind": "support" | "resistance" | "target" | "stop_loss", "price": 12345.0}
  ]
}
```

`force_close`/`force_override` payload (a `ForceAction`):
```json
{
  "pair": "BTCUSDT",
  "reason": "string"
}
```

**Outbound topic** (executor → main/) — what main/ subscribes to, to
receive position/fill state changes:

```json
{
  "pair": "BTCUSDT",
  "event": "opened" | "closed" | "stopped_out" | "filled" | "state_update",
  "position_state": { ... },
  "ts": "<iso8601>"
}
```

### `indicator_update` (inbound, added 2026-09-20 — built)

Unlike the four types above, this one is documented **as the code
actually encodes it**: a flat envelope, no nested `payload` object.
(The nested-`payload` shape shown above is pre-existing doc/code drift
for `open`/`close`/`modify`/`force_close`/`force_override`; the
indicator type was deliberately not made to match the stale doc. See
the design spec §2.)

```json
{
  "id": "<uuid>",
  "type": "indicator_update",
  "pair": "BTCUSDT",
  "name": "15_ema_7",
  "value": 12345.0,
  "kind": "support" | "resistance" | "none",
  "volume": 3.25,
  "expires_at": "<rfc3339>"
}
```

- `name` is main/'s stable identifier and the **lookup key on the
  executor side** (L5's `current_indicator`), not `id`. `id` is a
  fresh uuid per publish, for dedup only.
- `value` is generic — a price for `support`/`resistance`, any numeric
  reading for `none`. Deliberately not called `price`.
- `volume` is present **exactly when** `kind` is `support` or
  `resistance`, and absent entirely for `kind: "none"` — not null,
  absent. Either mismatch is a **parse error**, not a validated-then-
  rejected value. The design spec proposed a `#[serde(tag = "kind")]`
  internally-tagged enum; the implementation instead decodes a flat
  `kind` + `Option<volume>` through `parse_indicator_kind`
  (`crates/mq_gateway/src/wire.rs`), which yields the same
  unrepresentable-state guarantee while keeping the envelope flat.
  The decoded type is `IndicatorKind::{Support{volume},
  Resistance{volume}, None}`.
- `expires_at` is an absolute rfc3339 timestamp, not a relative TTL —
  no clock-skew ambiguity about when a duration started. main/
  republishes every tick, so the field doubles as a heartbeat: a dead
  sender ages its own readings out with no retract message.
- v1's main/ sender emits `kind: "none"` only; `support`/`resistance`
  producers are a later increment (design spec §4.1).

`id` is the dedup key on the inbound side (per Error handling below);
outbound carries no `id` — it's a state report, not a request that
needs deduplication on main/'s end. Field shapes here must stay in
sync with `local_analysis::DecisionContext`/`TradeSignal` (L2) and
`execution::PositionState`/`PositionStateEvent` (L3) — this is the
wire encoding of those same types, not a separate format invented here.

## Depends on

A `Transport` trait (concrete impl: ZeroMQ, PUSH/PULL — see
[L4-mq-gateway-transport.md](L4-mq-gateway-transport.md); the message
structures above are not deferred — main/ can code against them
regardless of transport choice).
`execution::ExecutionEngine::subscribe_state_changes` for outbound
content.

## Interface exposed upward

```
trait DecisionInbound {
    fn subscribe_decisions(&self)
        -> Stream<(DecisionId, TradeDecision)>;
    fn subscribe_force(&self)
        -> Stream<(DecisionId, ForceAction)>;
}

// added 2026-09-20 -- built. Separate trait, not a third method on
// DecisionInbound: its consumer (L9's indicator_ingest task) has no
// business subscribing to decisions, and `execution` -- DecisionInbound's
// only consumer -- must not see indicators at all.
trait IndicatorInbound {
    fn subscribe_indicators(&self)
        -> Stream<(DecisionId, IndicatorUpdate)>;
}

trait StateOutbound {
    fn publish_state(&self, event: PositionStateEvent)
        -> Result<(), MqError>;
}

trait Transport {  // deferred concrete impl
    fn send(&self, topic: Topic, payload: Bytes) -> Result<(), MqError>;
    fn recv(&self, topic: Topic) -> Stream<Bytes>;
}
```

Consumers: `execution` (subscribes to DecisionInbound, feeds
StateOutbound from its own state-change stream), `interfaces::cli`
(may publish force actions onto the same inbound path for convenience),
and — for `IndicatorInbound` only — `orchestrator`'s `indicator_ingest`
task (L9), which forwards straight into L5's `IndicatorSink`.
`subscribe_indicators` shares `SharedDedup` with
`subscribe_decisions`/`subscribe_force`, so one id is consumed once
across all three streams, and each stream filter-maps only its own
message type off the shared inbound topic.

## Construction / config

```
struct MqGatewayConfig {
    transport: TransportConfig,   // shape follows whichever Transport impl is chosen
    inbound_topic: String,
    outbound_topic: String,
}

impl MqGateway {
    fn new(config: MqGatewayConfig) -> Result<Self, MqError>;
}
```

Validated at construction, not on first publish/subscribe: empty or
malformed `inbound_topic`/`outbound_topic`, or an internally invalid
`transport` config (e.g. an unparseable connection string), fails
`new` immediately. This is what lets main/'s Python side and the
executor each validate their own config independently before either
side is actually wired to the other — a bad config surfaces at
startup, not as a mysterious silent drop later.

## Error handling

Duplicate decision id → drop silently, log at debug (not warn) — this
is expected, not exceptional. Transport-level failures are
`observability`-visible (feed/command-path staleness matters as much
as market-data staleness).

## Testing

Dedup-logic unit tests with a mocked `Transport`. Transport trait
itself untested here — deferred to its own spec/crate.

## Acceptance criteria (staged)

**Block A — construction/config validated**
- [ ] `MqGatewayConfig` with an empty/invalid topic name, or a
      malformed `transport` config, fails `new` — never constructs
      successfully and fails later on first use.
- [ ] A valid config constructs successfully, and a smoke test against
      a local/test transport instance confirms both the inbound and
      outbound topics are actually reachable (publish + receive round
      trip on each).

**Block B — per-method unit tests**
- [ ] `subscribe_decisions`, `subscribe_force`, and `publish_state`
      each have their own unit test, with `Transport` mocked. Dedup
      logic (already covered above) counts as one of these.
- [ ] Every method that *can* be unit tested without a real transport
      is — only `Transport`'s own concrete implementation is deferred
      (per Testing above), not the logic layered on top of it.

**Block C — integration tests: full round trip through `execution`**
- [ ] Every inbound message kind (`open`, `close`, `modify`,
      `force_close`, `force_override`), posted in the wire format
      defined above, is received by `execution`, handled correctly
      (per L3's own acceptance criteria — `NoOp`/`Open`/`Close`, or the
      force pass-through), and `mq_gateway` reports the correct result
      back — verified end-to-end against a real (or realistic
      in-memory) transport, not just that a Rust function was called.
- [ ] Redelivery of the same decision `id` is a no-op end-to-end: post
      it twice, confirm `execution` only acts once — not just that the
      dedup-logic unit test (Block B) passes in isolation.
- [ ] Outbound state events (`opened`/`closed`/`stopped_out`/`filled`/
      `state_update`) that `execution` generates correctly appear on
      the outbound topic in the wire format defined above — verified
      by a test subscriber actually reading them back, not by
      asserting `publish_state` was called.

**Block D — `indicator_update` (added 2026-09-20 — built and green)**
- [x] Wire round-trip: `kind: support`/`resistance` with `volume`
      decode; `kind: none` without `volume` decodes; `kind: none`
      *with* a stray `volume`, and `kind: support` *without* one, both
      fail to parse.
- [x] `subscribe_indicators` yields `indicator_update` only, ignores
      decision messages on the same topic, and dedups by `id` in the
      space shared with decisions.
- [x] Verified via `docker compose run --build --rm test` in the
      `layer-implementation` worktree (`mq_gateway`: 39 tests green,
      2026-09-20).

**Standing rule**: same as every other layer's staged criteria — once
`execution`'s real implementation and the real `Transport` both exist,
reopen Block C and re-check against what was actually built.
