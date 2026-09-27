# Step 8 — L6 replay_harness (plan)

Part of the [layer implementation sequence](2026-09-05-layer-implementation-sequence.md).
Note: only depends on L1 + L2, so it can be pulled earlier (right
after step 4) if replay validation is needed before execution work
starts — this step number is a default, not a hard gate.
Spec: [L6-replay-harness](../specs/layers/L6-replay-harness.md).

## What to implement

- The required gate: any change to local_analysis must replay
  cleanly against captured market conditions before it's enabled in
  live trading — not just a research convenience.
- Orchestration only: pick a dataset window, get a replay-mode feed
  from market_data, wire it into the exact same local_analysis code
  path used live. Replay mechanics themselves live in market_data
  (L1), not here.
- A pass/fail report that gates promotion of a local_analysis change
  to execution.

## Acceptance criteria (high level)

**Status:** implemented and committed on branch `layer-implementation`
(`crates/replay_harness`, commit `bd33890`). 2 tests, workspace total
199, clippy clean, Docker-verified. The spec's illustrative
`ReplayRunner` trait isn't valid Rust as written and doesn't fit
`local_analysis`'s actual trait shapes — documented deviation in the
crate's module doc: the caller wires the analyzer to a `replay_feed()`-
backed `MarketDataFeed` at construction time (analyzers hold their feed
fixed at construction, there's no post-hoc rewiring hook), `run` only
drives `subscribe_signals` to completion and reports, under a timeout
that guards against a live-backed analyzer accidentally being handed to
it (this is the "code path is provably the same one used live" bullet
below — the only difference between live and replay is which feed the
analyzer was built with).

- [ ] A known dataset run against a known local_analysis version
      produces a known, reproducible report — catches regressions in
      the harness itself, not just in local_analysis.
- [ ] A local_analysis change that fails replay is blocked from
      promotion — this is a normal gate outcome, not an error to
      catch and recover from.
- [ ] The code path exercised under replay is provably the same one
      used live (no bespoke replay-only implementation of any
      local_analysis logic).
