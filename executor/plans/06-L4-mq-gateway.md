# Step 6 — L4 mq_gateway (plan)

Part of the [layer implementation sequence](2026-09-05-layer-implementation-sequence.md)
(parallel with [07-L5-state-store](07-L5-state-store.md) — both depend
only on L3).
Spec: [L4-mq-gateway](../specs/layers/L4-mq-gateway.md).

## What to implement

- The main/ boundary, transport-abstracted so the concrete transport
  (Redis/NATS/ZeroMQ/etc.) can be picked later without touching
  execution.
- Inbound: trade decisions (open/close/modify) and force signals
  (force-close, override), same channel/path — not a side channel.
- Dedup every inbound message by its decision id, so at-least-once
  redelivery is a no-op.
- Outbound: position/fill state changes back to main/.
- The wire message formats themselves (inbound and outbound topic
  schemas) — this is the actual contract main/ codes against,
  defined independent of transport choice.
- Config validated at construction (bad topic name or transport
  config fails immediately, not on first publish/subscribe) so both
  sides can validate independently before being wired together.

## Acceptance criteria (high level)

**Status:** implemented and committed on branch `layer-implementation`
(`crates/mq_gateway`, commit `c9f2dc5`; a background agent originally
dispatched for this hit a session rate limit before producing any
files, rebuilt from scratch directly). 23 tests, workspace total 197,
clippy clean, Docker-verified. Block A (construction validation), B
(per-method unit tests against `InMemoryTransport`), and C (round trip
through a fake `ExecutionEngine` via `drive()`, including redelivery-
is-a-no-op end-to-end) are all covered by real tests, not placeholders.

Real gaps, documented in `crates/mq_gateway/NOTES.md`: `local_analysis::
Level` has no field for the wire format's per-level `kind`
(support/resistance/target/stop_loss); `execution::ForceKind` has only
`CloseNow` so `force_override` is rejected rather than guessed at;
`PositionStateEvent` has six variants against the wire format's five
events (plus a `"filled"` kind nothing currently produces). Concrete
`Transport` (Redis/NATS/ZeroMQ) remains deferred per spec — not
attempted here.

- [ ] Invalid config (empty/malformed topic, bad transport config)
      fails construction outright; valid config constructs and a
      smoke test confirms both topics are reachable end to end.
- [ ] Every method (decision subscribe, force subscribe, state
      publish, dedup) has its own unit test against a mocked
      transport — only the transport's own concrete implementation
      is deferred, not the logic on top of it.
- [ ] Every inbound message kind reaches execution, is handled
      correctly per L3's own criteria, and the result is reported
      back — verified end-to-end against a real or realistic
      transport, not just that a function was called.
- [ ] Redelivering the same decision id is a no-op end-to-end
      (execution only acts once), not just in the isolated dedup
      unit test.
- [ ] Every outbound state event execution generates actually appears
      on the outbound topic in the defined wire format, confirmed by
      a real test subscriber reading it back.
