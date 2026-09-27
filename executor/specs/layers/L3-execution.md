# L3 — execution

Part of [architecture index](../2026-09-04-architecture-design.md).

## Purpose

Owns position lifecycle and risk once main/ hands off a decision.

## Responsibilities

- On an inbound `TradeDecision` (regular, non-force), build
  `local_analysis`'s `DecisionContext` (kind, side, timeframe, main/'s
  levels — no size, no firing window, per L2's corrected doc) and call
  `combined_levels` → `build_signal` → `validate` (per L2) to get a
  risk-checked `SignalAction` before placing anything. A
  `NoOp`/`RiskViolation` result means the decision is not acted on —
  reported back as not placed, with reason, not an error. `execution`
  is still the sole caller of `local_analysis` and the sole subscriber
  of `mq_gateway` (L2 stays isolated per its own doc) — but
  functionally, a regular decision is always routed through this
  `local_analysis` processing before anything is placed. It never
  reaches the exchange unprocessed.
- **Force actions are the one exception**: `handle_force` does **not**
  go through `local_analysis` at all — it's a direct pass-through,
  acted on immediately (still via the exchange-native-order-first
  safety path, per `main_goal.md` — "no shortcut bypasses it" means the
  placement mechanics stay safe, not that it waits on L2's pipeline).
  This is the only case where a decision-shaped message skips
  `local_analysis`'s processing.
- Position lifecycle: opened/closed/modified, using the returned
  `SignalAction::Open`'s open/close/stop-loss prices and timing to
  open, or `SignalAction::Close`'s close price/timing to close. This
  relies entirely on `exchange_adapter::MarketAccount`
  (place_order/cancel_order/get_order, per L0) for the actual exchange
  interaction — L3's position lifecycle is not considered working
  until L0's own [Stage 3 acceptance
  criteria](L0-exchange-adapter.md#acceptance-criteria-staged) ("glue
  to L3") pass: opening/closing via place_order/cancel_order, fill
  confirmation via the real `AccountEvent` path (not stubbed), full
  round trip with no manual step.
- **Position sizing**: computed entirely here, not by `local_analysis`
  or taken from main/ (main/ supplies no size at all). Size =
  risk-per-trade ÷ the validated open/stop-loss price distance from
  `SignalAction::Open`. Checked against account limits (via
  `get_account_state`) and distance-to-liquidation before
  `place_order` — both checks are L3's alone; L2's pre-trade
  `risk_validate` runs neither (it has no size to check against, per
  L2's doc).
- Ongoing risk logic once open: SL/TP/trailing-stop, reacting to
  `local_analysis`'s live `walls`/`subscribe_signals` for timing,
  without round-tripping to `main/` per tick. This is *ongoing*
  position risk — distinct from L2's pre-trade `risk_validate`, which
  only ever runs once, before open; L3 never re-runs L2's pre-trade
  check once the position exists.
- **Ongoing advisory adjustments**: each iteration while a position is
  open, calls `local_analysis::position_advisor::advise` with an
  `OpenPositionView` L3 maintains (e.g. current stop-loss, open
  price). A returned `MoveStopLoss` is applied here — amend the
  resting exchange-native stop order, update internal position state,
  report the change like any other position update. L2 only computes
  *what* the adjustment should be from market conditions; it never
  places an order or holds position state — L3 remains the sole owner
  of the position's lifecycle in both the pre-trade and ongoing case.
- Margin/liquidation proximity tracked as a distinct, higher-priority
  risk than price-based SL/TP (exchange-forced liquidation happens
  regardless of whether a stop order fills in time).
- Dual stop-loss: local risk logic (fast, in-process) **and** a
  resting exchange-native stop/liquidation-safe order always placed
  too. Local logic is an enhancement, never a replacement — protection
  must survive this process or its feed dying.
- Local safety actions (stop-loss, liquidation avoidance) execute
  immediately, never blocked waiting on `main/`.
- A `main/` command for a position already closed locally is a no-op,
  reported back as "already closed", not an error.
- Paper-trading/dry-run: an alternate backend implementing the same
  L0 `MarketAccount` trait, simulating fills against the live L1 feed
  instead of sending real orders.

## Depends on

`exchange_adapter::MarketAccount` (the sub-model matching the
position's market kind, per L0) for the write path — place_order,
cancel_order, get_order, get_account_state, get_fees, get_market_info.
`market_data::MarketDataFeed::subscribe_account_events` for the push
path — fills/status/balance changes arrive through the shared
ingestion pipeline (L1) rather than a second direct subscription to
L0. `local_analysis::{CriticalLevelAnalyzer, SimpleSignalFeed,
SignalBuilder, RiskValidator, PositionAdvisor}` — pre-trade
(build_signal/validate), ongoing timing (walls/subscribe_signals), and
ongoing advisory adjustment (position_advisor::advise) alike.
`mq_gateway`'s inbound decision stream (see L4), which supplies the
raw `TradeDecision` (kind/side/timeframe/levels) that gets turned into
`local_analysis::DecisionContext`. `state_store::log_decision` (L5) —
every inbound message, `TradeDecision` or `ForceAction`, is forwarded
there for the audit log regardless of what `execution` ends up doing
with it.

## Interface exposed upward

```
trait ExecutionEngine {
    fn handle_decision(&self, d: TradeDecision) -> Result<(), ExecutionError>;
    fn handle_force(&self, f: ForceAction) -> Result<(), ExecutionError>;
    fn position_state(&self, pair: Pair) -> PositionState;
    fn subscribe_state_changes(&self) -> Stream<PositionStateEvent>;
}
```

Consumers: `mq_gateway` (drives handle_decision/handle_force from
inbound queue; consumes subscribe_state_changes for outbound
reporting), `state_store` (consumes subscribe_state_changes to
persist), `interfaces::cli` (position_state for status).

## Error handling

Order placement failure → retry per order-type policy; a failed SL/TP
placement specifically is a money-safety alert (observability),
never silent retry-forever. Command for already-closed position →
no-op + "already closed" report, not an error path.
`local_analysis::build_signal` returning `SignalAction::NoOp`, or
`validate` returning a `RiskViolation`, is likewise a normal outcome —
reported back as decision not placed, with reason, never treated as an
`ExecutionError`.

## Testing

Unit tests with a fake `MarketAccount`, a fake inbound decision stream,
and a fake `local_analysis` (`SignalBuilder`/`RiskValidator`/
`PositionAdvisor`) so pre-trade rejection paths and ongoing-advisory
handling are exercised without needing L2's real logic. Property tests
asserting SL/TP/liquidation-priority ordering holds under randomized
event interleavings, including a `MoveStopLoss` arriving mid-sequence.

## Acceptance criteria (staged)

L3 sits on more dependencies than any other layer (L0, L1, L2, L4,
L5), so most blocks below are gated the same way as L0/L1/L2's own
staged criteria: verified first against fakes, then re-verified once
the real dependency lands. **Standing rule**: whenever a dependent
layer's real implementation is built, reopen the block below that
touches it and re-check against what was *actually* built, not the
interface assumed here — same rule already stated in L0/L1/L2.

**Block A — position sizing**
- [ ] Size computed correctly as risk-per-trade ÷ the validated
      open/stop-loss distance from a fixture `SignalAction::Open`.
- [ ] Computed size checked against account limits (via
      `get_account_state`) before `place_order` — rejected, not
      silently clamped, when it would exceed them.
- [ ] The R:R relationship L2's `risk_validate` already established
      (open/close/stop-loss prices) survives sizing unchanged — sizing
      scales exposure, it never re-opens or second-guesses the R:R
      decision L2 made.

**Block B — glue to L2 (`local_analysis`)**
- [ ] Every inbound `TradeDecision` (non-force) is correctly turned
      into a `DecisionContext` and handed to `local_analysis` — kind,
      side, timeframe, and main/'s levels all mapped, nothing lost or
      invented.
- [ ] `local_analysis` receives the market data it needs during this
      call through execution's own `market_data` dependency (L1) — not
      a stub standing in for live data, once L1 is real.
- [ ] Every `SignalAction` variant `local_analysis` can return is
      handled correctly: `NoOp` → no exchange calls, reported
      not-placed with reason; `Open` → sized, risk-checked, placed;
      `Close` → closed at the returned price/timing.
- [ ] Every iteration, `position_advisor::advise` is called for each
      open position and a returned `MoveStopLoss` is applied correctly
      (Block E covers the exchange-side half of this).

**Block C — no-op validated**
- [ ] A decision that resolves to `NoOp` produces zero exchange calls
      (no `place_order`/`cancel_order`) — verified by asserting on the
      fake `MarketAccount`'s call log, not just the returned value —
      and is reported back as not-placed, with reason.

**Block D — stop-loss handled with no additional dependencies**
- [ ] The local stop-loss/liquidation-avoidance path fires and
      executes correctly using *only* `exchange_adapter` + live
      `market_data` — verified with `mq_gateway` and `local_analysis`
      entirely unavailable/stubbed out in the test, confirming this
      path never actually needs them to fire, matching "never blocked
      waiting on main/" from the Responsibilities section above.

**Block E — glue to L0 (`exchange_adapter`)**: orders round-trip
- [ ] A `SignalAction::Open` correctly becomes a real `place_order`
      call (correct side/price/computed-size) against the exchange (or
      its testnet/sandbox) — the decision `local_analysis` made
      actually reaches the exchange as the order it specified.
- [ ] Orders can be cancelled via `cancel_order`, with the cancelled
      state observed back correctly.
- [ ] After a real fill, the resulting `AccountEvent` (via L1, per L3's
      Depends-on) correctly updates `position_state`/
      `subscribe_state_changes` — verified both directions: decision →
      order on the exchange, and exchange fill → correct internal
      state update, not just one half of the round trip.
- [ ] This block and L0's own [Stage 3 acceptance
      criteria](L0-exchange-adapter.md#acceptance-criteria-staged)
      ("glue to L3") are two views of the same round trip — both must
      pass together, not independently.

**Block F — communication structures defined and aligned**
- [ ] Every type crossing execution's boundary is the frozen contract
      already declared by its *owning* layer's doc, not a parallel
      version invented here: `TradeDecision`/`ForceAction` (L4),
      `DecisionContext`/`SignalAction`/`OpenPositionView`/
      `PositionAdjustment` (L2), `MarketAccount` calls plus
      `MarketDataEvent`/`AccountEvent` (L0, via L1's ingestion),
      `AccountState`/`OrderInfo` (L0), `PositionState`/
      `PositionStateEvent` (this doc's own, consumed by L4/L5/L8).
- [ ] Where a field's meaning could drift between two layers' docs
      (e.g. what "size" means here vs. what main/ used to send, per
      L2's corrected doc), this doc and the other layer's doc agree —
      checked explicitly, not assumed consistent because both compile.
