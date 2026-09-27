# Step 5 — L3 execution (plan)

Part of the [layer implementation sequence](2026-09-05-layer-implementation-sequence.md).
Spec: [L3-execution](../specs/layers/L3-execution.md).

## What to implement

- On a regular inbound decision: build local_analysis's decision
  context and run it through level-merge → signal-build → risk
  validation before anything is placed. A no-op or risk rejection is
  reported back as not-placed, with reason — never an error.
- Force actions as the one exception: skip local_analysis entirely,
  act immediately, still via the exchange-native-order-first safety
  path — no shortcut on placement mechanics.
- Full position lifecycle (open/close/modify) driven by the prices
  and timing local_analysis returns, executed through the exchange
  adapter.
- Position sizing, computed entirely here (risk-per-trade over the
  validated entry/stop distance), checked against account limits and
  liquidation distance before placing — neither check happens
  upstream.
- Ongoing risk once a position is open: SL/TP/trailing-stop reacting
  to local_analysis's live wall/signal feed, margin/liquidation
  proximity tracked as higher-priority than price-based stops, and
  per-iteration advisory adjustments (e.g. trailing stop-loss)
  applied from local_analysis's proposals.
- Dual stop-loss: fast local logic plus an always-placed resting
  exchange-native order, so protection survives this process or its
  feed dying.
- Local safety actions never wait on main/; a command for an
  already-closed position is a no-op, reported as such.
- A paper-trading backend implementing the same exchange-adapter
  interface, simulating fills against the live feed.

## Acceptance criteria (high level)

Sits on the most dependencies of any layer (L0, L1, L2, L4, L5) —
verify first against fakes, then re-verify against each real
dependency as it lands.

**Status:** implemented and committed on branch `layer-implementation`
(`crates/execution`, commit `d6f67a7`). 19 tests (sizing, engine,
paper), workspace total 156, clippy clean, Docker-verified. Sizing,
glue-to-L2, no-op-zero-calls, and the fast-stop-loss-independent-of-
local_analysis criteria are all covered by real tests against fakes
(the last one specifically via panicking local_analysis fakes, proving
the path never touches them, not just that this test didn't exercise
it). `TradeDecision`/`ForceAction`/`PositionState`/`PositionStateEvent`
are defined in `execution::types` as provisional stand-ins for L4's not-
yet-built real contract — reopen and reconcile once `mq_gateway` lands.

Not covered: Block E's real exchange round-trip (needs L0 testnet
credentials, same open item as L0/L1's own docs); `fire_at`/`max_wait`
timing from `SignalAction` isn't honored (orders place immediately);
liquidation-distance is a single simplistic balance-fraction check, not
a real margin/leverage model — see `sizing::within_account_limits`'s
doc comment.

- [ ] Position size computed correctly from a fixture signal, checked
      against account limits before placing, and never alters the
      R:R relationship local_analysis already established.
- [ ] Every inbound decision maps correctly to local_analysis's
      input, using this layer's own live market-data dependency (not
      a stub, once L1 is real); every output variant (no-op/open/
      close) is handled correctly; per-iteration advisor calls are
      made for every open position and applied correctly.
- [ ] A no-op decision produces zero exchange calls, verified by
      call-log inspection, not just the returned value.
- [ ] The stop-loss/liquidation-avoidance path fires correctly using
      only the exchange adapter and live market data — proven with
      the message queue and local_analysis unavailable, confirming
      it never actually needs them.
- [ ] A real signal becomes a real exchange order (correct side/
      price/size); it can be cancelled; a real fill correctly
      updates position state — verified both directions, not just
      one half of the round trip. Considered done only together with
      L0's own "glue to L3" stage.
- [ ] Every type crossing this layer's boundary is the frozen
      contract already declared by its owning layer's doc, not a
      parallel version invented here — checked explicitly wherever
      a field's meaning could drift between two docs.
