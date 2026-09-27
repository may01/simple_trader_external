# Step 4 — L2 local_analysis (plan)

Part of the [layer implementation sequence](2026-09-05-layer-implementation-sequence.md).
Spec: [L2-local-analysis](../specs/layers/L2-local-analysis.md).

## What to implement

- **Critical levels**: own wall detection from the live order book,
  plus a merge step combining main/'s levels with detected walls
  into one sorted, tolerance-collapsed level set.
- **Simple signals**: a configurable check mechanism (not a fixed
  pair of hardcoded functions) so new signals register via config.
  Two signals in scope now — an extreme opposite-direction volume
  spike, and a volume-projected price move over a parameterized
  horizon (the price-impact model itself is deferred to its own
  spec; only the input/output shape is fixed here).
- **Signal building**: given a decision's context (kind, side,
  timeframe, main/'s levels) plus market data, produce exactly one
  action — no-op, open (with price/timing), or close (with
  price/timing). No separate "nothing to do" path outside this.
- **Pre-trade risk validation / best-price selection**: a staged
  check (reward/risk minimum, then a refinement loop that nudges
  open/stop-loss toward level-supported candidates scored on both
  R:R and probability of reaching entry before stop) — passes,
  refines, or rejects outright; never hands back a partial/
  best-effort signal.
- **Position advisor**: for an already-open position, propose
  adjustments (e.g. trailing the stop-loss) from live conditions —
  proposes only, never places an order or holds state itself.
- Kept as pure functions with no dependency on the exchange adapter,
  execution, or the message queue — decision/position context always
  arrives as plain data, which is what keeps the replay gate
  structural rather than a process rule.

## Acceptance criteria (high level)

Mostly self-contained; only the last block gates on L3.

**Status:** implemented and committed on branch `layer-implementation`
(`crates/local_analysis`, commit `9bd7ef3`). 32 tests green, clippy
clean, Docker-verified as part of the full workspace. Blocks A/B/C/E's
non-gated criteria are covered by real (non-placeholder) control-flow
tests; the underlying models the spec itself defers (volume->price
elasticity, wall-detection statistics, entry-probability estimation)
are implemented as documented placeholder constants/heuristics, not
the eventual real formulas — see doc comments at
`VolumeProjectedMoveCheck`, `WallDetector`, `DefaultRiskValidator::
estimate_probability`, `DefaultSignalBuilder`, `DefaultPositionAdvisor`.
Block D's second checkbox and Block E's second checkbox (execution-side
re-verification) are gated on L3, which doesn't exist yet.

- [ ] Signal factory builds the right check from config; both
      signals fire/don't fire correctly at their thresholds,
      including boundary cases; adding a new signal needs no change
      to the iteration loop.
- [ ] Wall detection is correct against a fixture book (no false
      positives/negatives); level merge behaves per the defined rule
      across no-overlap, full-overlap, and boundary cases.
- [ ] Risk validation: an already-clearing signal passes unchanged;
      a failing one either converges on a level-supported candidate
      or is rejected outright — never a partial signal; main/'s
      levels demonstrably influence the chosen prices, not just
      decorate them.
- [ ] The four boundary types (decision context, signal action,
      open-position view, position adjustment) are treated as the
      complete, frozen contract to execution — nothing else crosses.
- [ ] Position advisor tightens the stop-loss (never loosens it) on
      a favorable fixture move, and proposes nothing when there's no
      favorable move.
- [ ] Once execution exists: a real inbound decision maps correctly
      to this layer's input, every output variant is handled
      correctly on the execution side, and advisor output is applied
      correctly — re-verified against execution's real
      implementation, not the assumed interface.
