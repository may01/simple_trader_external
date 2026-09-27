# Step 1 — L7 observability (plan)

Part of the [layer implementation sequence](2026-09-05-layer-implementation-sequence.md).
Spec: [L7-observability](../specs/layers/L7-observability.md).

## What to implement

- A structured logging/metrics API every other layer can call —
  build the minimal version first, ahead of L0, so no later layer
  bolts logging on afterward.
- A distinct alert channel, separate from ordinary logs, for
  money-safety conditions: feed staleness/disconnect, failed order
  placement, approaching liquidation. Alert callers don't yet exist
  (L0+), but the channel and its call shape must be ready for them.
- A dead-man's-switch on the alert channel itself — its own failure
  (alerting silently dying) must be independently detectable, not
  just another unread log line.
- No dependency on any other crate — this stays a leaf so nothing
  else's correctness depends on it being up.

## Acceptance criteria (high level)

- [x] Any layer can emit a metric event and an alert event through a
      single shared API, with no circular dependency back onto any
      other layer. — `crates/observability`: `Metrics`/`Alerts` traits,
      zero path dependencies (leaf crate).
- [x] Alert-class events are visibly distinct from ordinary logs
      (different channel/severity, not just a log line grep would
      miss). — `AlertEvent`/`MetricEvent` are distinct types dispatched
      through distinct traits (`Alerts::fire` vs `Metrics::record`);
      `StdoutAlerts` writes to stderr, `StdoutMetrics` to stdout.
- [x] The alert channel's own failure is detectable on its own —
      proven by deliberately breaking it in a test and confirming
      something surfaces. — `DeadMansSwitch::check` in
      `crates/observability/src/lib.rs`, reports via `Metrics` (a
      structurally separate path from `Alerts`) when `AlertHealth` goes
      stale; covered by
      `dead_mans_switch_detects_stale_alert_channel` and
      `dead_mans_switch_stays_quiet_after_a_heartbeat`.
- [ ] Later layers (L0 onward) can each be verified, per their own
      spec's "Error handling" section, to actually call `record`/
      `fire` at the sites they claim to — treat this as an ongoing
      cross-check as each layer lands, not a one-time L7 task.
      **Ongoing tally:** `exchange_adapter_binance`/`_mexc` (L0) call
      `Metrics::record` on every REST request and `Alerts::fire` on
      failure/staleness, injected via constructor (not hardcoded to
      `StdoutAlerts`/`StdoutMetrics`). `market_data` (L1) calls both on
      a detected book-sequence gap. Still open: nothing calls `fire`
      for `OrderPlacementFailed`/`LiquidationNear` in a real order-
      placement path yet (no `execution` layer exists to place orders
      against L0 for real) — recheck once L3 lands.

**Status:** implemented on branch `layer-implementation` (trade_executor
repo), commit landing 2026-09-05. Docker entry point:
`docker build -t trade_executor_test . && docker run --rm --network host
trade_executor_test` runs `cargo test --workspace` (the `docker compose
run test` form hits a pre-existing host issue: all predefined Docker
address pools are fully subnetted on this machine, unrelated to this
repo's config — revisit once that's freed up, or once a later layer adds
real network requirements to the compose file anyway).
