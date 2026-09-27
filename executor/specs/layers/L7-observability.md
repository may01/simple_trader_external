# L7 — observability

Part of [architecture index](../2026-09-04-architecture-design.md).

## Purpose

Cross-cutting sink for every other layer. Structured logs/metrics for
all state transitions and risk events; alerts (not just logs) on
conditions that threaten money safety.

## Responsibilities

- Structured logging/metrics API every layer can call.
- Alert-class events distinct from ordinary logs: feed
  staleness/disconnect, failed order placement, approaching
  liquidation.
- Own dead-man's-switch for the alert channel itself — if alerting
  dies, that has to be independently detectable, not just another log
  line nobody's watching.

## Depends on

Nothing structurally — every other layer depends on this one, not the
reverse. Must stay a leaf so no layer's correctness depends on
observability being up.

## Interface exposed upward (to all other layers)

```
trait Metrics {
    fn record(&self, event: MetricEvent);
}

trait Alerts {
    fn fire(&self, alert: AlertEvent);   // feed-stale, order-fail, liquidation-near, ...
}
```

Consumers: L0–L6, L8 all call `record`/`fire` ambiently. Not drawn on
the main data-flow diagram to avoid clutter — treat as present on every
arrow.

## Error handling

N/A in the usual sense — this crate *is* the error-handling backchannel
for everything else. Its own failure mode (alert channel down) is
covered by the dead-man's-switch above.

## Testing

Unit tests that MetricEvent/AlertEvent are actually emitted at each
call site listed in the other layer docs' "Error handling" sections
(cross-check, not a property of this crate alone).
