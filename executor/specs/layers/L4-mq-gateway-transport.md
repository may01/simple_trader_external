# L4 transport — ZeroMQ

Part of [architecture index](../2026-09-04-architecture-design.md). Resolves
the `Transport` trait's concrete implementation, deferred by
[L4-mq-gateway.md](L4-mq-gateway.md#depends-on) ("Redis/NATS/ZeroMQ ...
picked in its own later spec").

## Decision

**ZeroMQ**, no broker process, PUSH/PULL sockets, executor binds.

## Context that drove it

- **Deployment**: main/ (Python) and the executor (Rust) run on the same
  host, in separate Docker containers, talking over the bridge network —
  not the same process, not different hosts.
- **Durability**: not needed at this layer. `state_store` (L5) already owns
  crash recovery via boot-time reconcile against exchange truth. The MQ
  layer's dedup-by-id (per L4's Error handling) only has to make
  *transport-level redelivery* a no-op — it does not imply the transport
  must itself persist or replay messages.
- **Fanout**: both topics are point-to-point, not fanout. Inbound: main/
  and `interfaces::cli` both *publish* onto the same inbound topic (per
  L4's Responsibilities and L8's Depends on) — `interfaces::cli` is a
  second producer, not a second consumer. Outbound: only main/ subscribes.
  `interfaces::visualizer_backend` reads `market_data`/`state_store`
  directly (per L8), not through `mq_gateway`. Confirmed against L9:
  multi-pair is one orchestrator process handling several pairs
  internally, not one executor instance per pair — so this stays
  1-producer/1-consumer per topic even under multi-pair.
- **Conclusion**: with no durability requirement and no fanout, a broker
  (Kafka, Redis, NATS, RabbitMQ) buys nothing here — its value in every
  case is either a durable/replayable log or multi-consumer distribution,
  neither of which applies. Running one would add a third container that
  can fail independently of the two real endpoints, and another thing
  `observability` (L7) has to watch, for no payoff. ZeroMQ is a library,
  not a service — it runs inside the two existing containers.

## Socket pattern: PUSH/PULL, not PUB/SUB

Two one-directional pipes, matching the point-to-point topology:

- main/ PUSH → executor PULL (inbound: decisions + force actions)
- executor PUSH → main/ PULL (outbound: state events)

Considered PUB/SUB first (better fit for the "executor consumes
concurrently without knowing when main/ produces" requirement, and for
force-action delivery) and rejected it:

- Async/event-driven consumption is a ZeroMQ-wide property, not a PUB/SUB
  one — PULL sockets block/poll and wake on message arrival exactly like
  SUB sockets. No polling or lockstep either way.
- Force actions ride the same topic/path as regular decisions (per L4
  Responsibilities — "not a separate side channel"), so socket pattern
  cannot give them priority delivery under either option.
- Reliability differs, and favors PUSH/PULL: a PUB socket does not buffer
  for a currently-disconnected SUB — a message published while the
  executor container is mid-restart is dropped silently, no queue. A PUSH
  socket queues locally (up to HWM) while its peer is unreachable and
  flushes on reconnect. For a `force_close` sent around an executor
  restart, PUSH/PULL is the safer choice.

## Bind/connect ownership

**Executor binds both sockets** (its PULL for inbound, its PUSH for
outbound). **main/ connects both** (PUSH out, PULL in).

Rationale: the executor is the live-trading process and should stay up
continuously, at a fixed known address, indifferent to when main/ comes
and goes (dev iteration, redeploys, tuning runs). main/ reconnects to that
fixed endpoint automatically on restart; the executor never needs to track
wherever a currently-running main/ instance is.

## Library

- **Executor (Rust)**: `zeromq-rs` — pure-Rust reimplementation, no
  `libzmq` C dependency. Chosen over the `zmq` crate (libzmq bindings,
  more battle-tested) to keep the executor's Docker build dependency-free
  (no `libzmq3-dev` apt layer, simpler static binary). PUSH/PULL is one of
  `zeromq-rs`'s more complete-supported patterns, which lowers the risk of
  picking the less-mature option.
- **main/ (Python)**: `pyzmq` — wheels bundle `libzmq` already, so there's
  no equivalent build-dependency concern on that side; no reason to avoid
  the more mature binding there.

## Wire format

Unchanged from [L4-mq-gateway.md](L4-mq-gateway.md#message-structures-wire-format).
`Transport::send(topic, payload: Bytes)`/`recv(topic)` carries the JSON
envelope as-is — ZeroMQ is payload-agnostic, no protobuf/schema step is
introduced by this choice.

## Open items for L4's `TransportConfig`

Not resolved here, left to implementation: HWM (high-water-mark) sizing
for both PUSH sockets' local queues, and how a queue-full condition
surfaces through `MqError`/`observability` (L7) — feed/command-path
staleness matters per L4's Error handling, so a PUSH socket silently
dropping past HWM would need to be observable, not silent.
