# L9 — orchestrator & deploy

Part of [architecture index](../2026-09-04-architecture-design.md).

> **Gap fixed 2026-09-04**: earlier drafts described L9 as "Docker +
> config, not a crate" and left every other layer's doc to describe
> only its own interface — nobody was ever named as the thing that
> constructs each layer's concrete implementation, wires them
> together, runs the boot sequence, or drives the runtime loop. That
> is this layer: **L9 is a binary crate** (the actual `main()`
> entrypoint) plus the Docker/deploy wrapping around running it. It
> was wrong to call it "not a crate."

## Purpose

The orchestrator: constructs every other layer's concrete
implementation from config, wires them together in the correct order,
drives the runtime loop, and owns the top-level error boundary —
wrapped in a Docker container for deployment. This is the only place
in the workspace that depends on every other layer at once; every
other layer's doc describes what it does in isolation, this doc
describes how they actually get run together as one process.

## Responsibilities

- **Config loading**: env-based config (per `main_goal.md`'s
  convention) parsed into each layer's own config type —
  `AdapterConfig` per configured exchange (L0), storage path for
  `market_data` (L1), `SignalConfig` list for `local_analysis` (L2),
  `MqGatewayConfig` (L4), and this layer's own: which pairs this
  instance handles, risk-per-trade, R:R/probability minimums (L2's
  thresholds), account risk limits (L3's sizing). Exchange API
  credentials injected via env/config at process start, never logged,
  never sent over the message queue.
  Indicator ingestion (step 7b) adds **no new executor env var**: it
  rides the already-configured inbound socket
  (`MQ_ZMQ_INBOUND_BIND_ADDR`, `tcp://0.0.0.0:5555`). It does add a
  **deployment requirement**: `main/` runs in its own compose project,
  and the two are joined by `trader_mq`, an external docker network
  both attach to (`docker network create trader_mq`, owned by
  neither), with `main/` addressing this service by name —
  `MQ_EXECUTOR_ADDR=tcp://executor:5555` in `main/configs/live.env`.
  The `127.0.0.1:5555/5556` publishes remain for host-side tooling
  only. Routing main/ through the host instead does **not** work: a
  port published on the host's loopback is unreachable from another
  container via host-gateway, and the sender fails silently when it
  is (decided/measured 2026-09-20 — see
  [indicator-broadcast-e2e-check-design.md](../2026-09-20-indicator-broadcast-e2e-check-design.md) §3-§4).
- **Construction order** (matters — later steps depend on earlier ones
  being ready):
  1. `observability` (L7) first — every later step can log/alert
     through it.
  2. `exchange_adapter_<exchange>` (L0) — one instance per configured
     exchange/kind combo this deployment actually uses.
  3. `market_data` (L1), wired to the L0 adapters — start ingestion
     (`subscribe_market_data`/`subscribe_account_events`) for each
     configured pair.
  4. `local_analysis` (L2) — `SignalFactory` builds the active
     `SignalCheck` set from config. No wiring needed beyond config: L2
     stays a pure library, called by L3 (per L2/L3's own docs).
  5. `state_store` (L5) — `load_all()` then `reconcile()` against
     L0's `get_account_state`. This **must complete** before the next
     step starts accepting decisions — reconciliation failure that
     can't resolve automatically stops the boot here, per L5's own
     Error handling.
  6. `execution` (L3), wired to L0/L1/L2/L5.
  7. `mq_gateway` (L4), wired to the configured `Transport` +
     `execution`. Start the inbound loop
     (`subscribe_decisions`/`subscribe_force` → `execution`'s
     `handle_decision`/`handle_force`) and the outbound relay
     (`execution::subscribe_state_changes` → `mq_gateway::
     publish_state`).
  7b. **`indicator_ingest`** (added 2026-09-20, **built** — see
     [level-broadcast-design.md](../2026-09-19-level-broadcast-design.md)):
     spawn one supervised task wiring L4's
     `IndicatorInbound::subscribe_indicators` straight into L5's
     `IndicatorSink::record_indicator`, translating `mq_gateway`'s
     wire-level `IndicatorKind` into `state_store`'s own and nothing
     else. **Spawned once per process, not per pair** — every
     `indicator_update` carries its own `pair`, same reasoning as
     `mq_gateway::drive`'s single spawn just above it — and it lives in
     `orchestrator` (`crates/orchestrator/src/indicators.rs`), not
     inside `drive()`, matching the precedent of
     `run_wall_snapshot_task`/`record_signal_without_decision`.
     A persist failure fires a `PersistFailed` alert at `Warn` and the
     loop keeps running; it is never swallowed. The task holds no
     indicator state of its own — the only cache is L5's private one.
  8. Start `execution`'s per-iteration loop: for every open position,
     call `local_analysis::position_advisor::advise`
     (per L2/L3's ongoing-advisory docs); `local_analysis`'s own
     `SignalCheck` iteration for `subscribe_signals` runs on its own
     schedule feeding the same ongoing path.
  9. `interfaces::cli`/`visualizer_backend` (L8), wired to
     L3/L4/L1/L5 — start serving.
  10. Signal readiness (log "started"); install SIGTERM/SIGINT
      handling for graceful shutdown.
- **Multi-pair**: one orchestrator process handles several pairs
  concurrently — one ingestion+iteration task per configured pair
  (steps 3 and 8 above, per-pair), sharing L0 adapter connections
  where the exchange's own transport multiplexes multiple pairs over
  one connection. A panic or unhandled error in one pair's task is
  isolated — logged as an alert (`observability`), the process and
  other pairs' tasks keep running; per-pair failure is not
  process-wide failure.
- **Graceful shutdown**: on SIGTERM, stop accepting new inbound
  decisions, let in-flight order placements resolve (or fail cleanly,
  reported the normal way), flush `state_store`, close exchange
  connections — never a hard kill that could leave an order placed
  with no local record of it.

## Depends on

Everything (L0–L8) — this is the wiring root; no crate depends on it.

## Interface exposed upward

None in the crate sense — this is the top of the dependency graph, a
binary, not a library. What it exposes is operational: process exit
code (0 on clean shutdown, non-zero on boot failure), structured logs
via `observability`, and the running process itself (inspected via
`interfaces::cli`).

## Error handling

Boot failure (bad config, or a reconciliation mismatch step 5 can't
resolve automatically) → process exits non-zero, logs the specific
reason, **never** starts accepting decisions in an unreconciled state
— fail fast, not degrade silently. A per-pair task panic is caught and
isolated (per Multi-pair above) — it is not a process-level failure.
Shutdown mid-flight (SIGTERM while an order is in transit) waits for
that operation to resolve before tearing down further, per Graceful
shutdown above.

## Testing

**Indicator broadcast, cross-repo (added 2026-09-21)**: the main/ →
executor hop has a scripted end-to-end check. It lives in the **`main/`
repo**, because it drives main/'s real `IndicatorPublisher` from main/'s
image:

```bash
# from main/; needs `docker network create trader_mq` once per machine
python3 scripts/e2e_indicator_broadcast.py --cold
```

It brings this stack up (`--cold`: `down` without `-v`, then `up -d
--build postgres executor visualizer`), waits for `/api/status` ready
at schema 7, then waits for a warm-up reading to land in `indicators`,
since a ready API does not prove `indicator_ingest` is running. It then
asserts arrival, dedup, append-only / newest-wins, expiry, support-kind
round trip and a dead-address negative control, through `psql` and
`GET /api/current_indicators`, and exits non-zero on any failure.
Green from cold start on 2026-09-21. It is not part of `cargo test
--workspace`: it needs both repos, a real network hop and a running
stack. Design and results:
[2026-09-20-indicator-broadcast-e2e-check-design.md](../2026-09-20-indicator-broadcast-e2e-check-design.md).

docker-compose integration test spinning the full binary against an
exchange sandbox + fake main/ publisher (see L3/L4 testing notes for
what this exercises) — this **is** the construction-order/wiring
described above, exercised end-to-end, not a separate thing. Also:
boot with a deliberately bad config fails fast with a clear log,
never partially starts; boot with a deliberate exchange/local state
mismatch (per L5) blocks before decisions are accepted; a forced panic
in one pair's task doesn't take down a second configured pair's task
in the same test run; SIGTERM mid-order-placement is handled per
Graceful shutdown, not a hard kill.

## Acceptance criteria (staged)

- [ ] Valid config boots successfully through every construction-order
      step above, in order, reaching "ready" only after step 5's
      reconciliation completes — not before.
- [ ] Invalid config (missing required env var, malformed
      `AdapterConfig`/`MqGatewayConfig`) fails fast at boot, non-zero
      exit, clear log — never a partial start.
- [ ] Two or more configured pairs run concurrently with no
      cross-pair interference; killing one pair's task (simulated
      panic) leaves the others running.
- [ ] SIGTERM during an in-flight order placement is handled per
      Graceful shutdown — the order resolves (or fails cleanly and is
      reported) before the process exits, never silently abandoned.
- [ ] **Standing rule** (same as every other layer): once each
      dependency's real implementation exists, re-verify this layer's
      wiring against what was actually built, not the interface
      assumed here — this layer is uniquely exposed to every other
      layer's changes, so it's the one most likely to need frequent
      re-checks.
