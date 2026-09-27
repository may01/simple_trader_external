# L2 — local_analysis

Part of [architecture index](../2026-09-04-architecture-design.md).

## Purpose

Turns market data plus main/'s levels into a fully-specified trade
signal, and pre-trade risk-validates it — **not** timing-only anymore
(superseded 2026-09-04; see note below). Still pure functions over
data handed to it, no exchange/execution dependency, so the replay
gate stays structural.

> **Scope note**: `main_goal.md` and this doc's earlier drafts assumed
> main/ supplies levels, an authorized firing window, and a position
> size alongside a decision, with local_analysis only refining timing.
> Corrected 2026-09-04, in two passes: main/ supplies **kind**
> (open/close/modify), **side**, the **timeframe** its own analysis was
> based on (5/15/60/240 min, the set configurable by main/, not fixed
> here), and its own **levels** (support/resistance/target/SL reference,
> from main/'s Levels module) — but **no size** (execution computes it,
> L3) and **no explicit firing window** (open question, see
> `DecisionContext` below — an intermediate draft removed main/'s
> levels too; that removal is itself reverted here). `main_goal.md`
> itself is not amended by this doc — flagging the divergence here so
> it's visible, not silently overridden.

## Responsibilities

- **critical_levels**: two independently-testable parts, combined:
  1. **`walls`**: detect resting-order "walls" from the live order
     book — prices where big orders are collected (own detection,
     local only). Bid and ask sides are judged independently. Sizing
     statistic is a high percentile of level size on that side
     (`percentile`, 0-100, e.g. `95`) — not a multiple of the mean:
     on a real full-depth book (thousands of tiny levels) the mean is
     easily dragged upward by the very walls it's supposed to find,
     which a live run confirmed (`WALL_MULTIPLIER=3` flagged 112
     "walls" in one BTCUSDT snapshot). A level counts as a wall only
     if its size strictly exceeds the percentile cutoff — ties at the
     cutoff are ordinary, not walls. `max_spread_distance` (a 0-1
     fraction of that side's best price, e.g. `0.1` for 10%) clamps
     how far into the book detection looks at all, inclusive of the
     boundary — resting orders far from the market (e.g. round-number
     orders thousands away from spot) are excluded from consideration
     entirely, however large. Both are constructor parameters on
     `WallDetector`, not hardcoded.
  2. **`combined_levels`**: the glue between main/ and local data —
     merges main/'s levels (support/resistance/target/SL reference)
     with `walls`' big-order-book prices into one level set. Merge
     rule: union of both, sorted by price — nothing collapses. Each
     `Level` carries exactly one `LevelSource` (never a list), so a
     main/ level and a wall at the same or nearby price stay two
     separate entries rather than merging into one multi-tagged point.
     This merge is itself a defined, tested unit — not an implicit
     detail of `signal_builder`/`risk_validate`. (Spread around a
     level's price — e.g. for overlap detection — is deferred to a
     follow-up; not modeled yet.)
- **simple_signals**: a `SignalCheck` mechanism + `SignalFactory` that
  builds the set of active checks from config, not a fixed hardcoded
  pair of functions — adding signal 3 later means registering another
  config entry, not touching the iteration loop. Each iteration (on
  new market data), every registered `SignalCheck` runs against the
  current window; any that fire emit onto `subscribe_signals`.
  Signals in scope now:
  1. **Extreme volume change, opposite direction** — a sharp
     volume spike against the position's current direction, likely to
     reverse price (the existing "wall"-adjacent signal, formalized as
     a `SignalCheck`).
  2. **Volume-projected price move** — moving average of volume over
     a parameterized period (default 10s), then an estimate of how far
     price could move over the next N minutes (parameterized) if that
     volume rate held steady. The volume→price-impact model itself
     (the actual elasticity/estimation function) is deferred to its
     own follow-up spec — this doc fixes the *shape* (inputs: avg
     volume over window, horizon; output: a projected price delta),
     not the formula.
- **signal_builder**: given a decision's context (kind, side,
  timeframe, main/'s levels) plus current market data and
  `combined_levels`, produce exactly one `SignalAction` for `execution`
  to act on: **no-op** (nothing worth doing right now), **open** (open
  price, close price, stop-loss price, fire timing, max wait before
  treating the position as stuck with neither stop-loss nor
  close-price resolving — open/close price plus the size `execution`
  computes gives it everything needed to derive expected profit, no
  separate field for it), or **close** (close price and timing for
  exiting an existing position). There is no separate "no signal"
  out-of-band case — no-op is a variant of the same return type, not
  an `Option`/exception path around it.
- **risk_validate**: pre-trade risk check on a produced `SignalAction`
  before it ever reaches `execution` for placement — staged, not a
  single pass/fail, and only meaningful for the **open** variant (a
  close or no-op passes through unchanged: closing reduces exposure,
  it doesn't need an R:R gate):
  1. **R:R check**: compute reward/risk from the proposed open,
     close, and stop-loss prices. Meets the minimum → `Ok`, done.
     Doesn't → go to stage 2.
  2. **Refinement loop**: nudge open price and/or stop-loss price
     (close price stays — it's the target the signal was built
     around, not local's to move) to candidate values drawn from
     `combined_levels` (own walls + main/'s levels) near the original
     proposal — not an arbitrary continuous search, only prices the
     level data actually supports. Each candidate is scored on both
     R:R *and* estimated probability of reaching the open price before
     hitting the candidate stop-loss (using the same level/volatility
     data `critical_levels` already has). Loop until one candidate
     clears both the R:R minimum and the probability minimum (`Ok`),
     or the candidate set is exhausted (`RiskViolation` — no partial/
     best-effort signal handed to `execution`).

  This is, in effect, **best-price selection**: choosing the best
  available open, close, and stop-loss price from `combined_levels`
  and current market data, not just validating a single proposal.

  Nothing size- or liquidation-dependent runs here — `local_analysis`
  has no size at all (main/ doesn't supply one; see `DecisionContext`
  below): both size-vs-limits and distance-to-liquidation are checked
  entirely by `execution` (L3), since size doesn't exist until L3
  computes it, after this validation returns.

  `risk_validate` itself is a pre-trade gate only, run once before
  open — L3 never re-runs it once the position exists.
- **position_advisor** (ongoing, once open): live market conditions
  can call for adjusting an already-open position — e.g. price moved
  favorably enough that securing profit means trailing the stop-loss
  up, based on current order book / market conditions. L2 computes
  *what* the adjustment should be from `walls`/live market data plus
  the position's current state (passed in as plain data, same pattern
  as `DecisionContext` — no subscription to `execution`); `execution`
  (L3) is the one that actually applies it (moves the resting
  exchange-native order, updates internal position state) and remains
  the sole owner of the position's lifecycle. L2 advises, it never
  manages — no state, no order placement, ever, in either the
  pre-trade or the ongoing case.
- Pure functions over `market_data` output **and** whatever decision
  context is passed in as plain data. **Must not** depend on
  `exchange_adapter`, `execution`, or `mq_gateway` directly — the
  decision's kind/side/timeframe/levels arrive as a plain argument
  (`execution` receives them from `mq_gateway` and passes them in),
  not by this crate subscribing to the queue itself. This is what
  keeps the `replay_harness` gate structural (compile-time), not a
  process rule someone can forget: replaying a decision is just
  calling the same functions with recorded arguments.

## Depends on

`market_data::MarketDataFeed` (live) — and, under replay,
`market_data::MarketDataStore::replay` feeding the identical code path
(per L1). Decision context (kind, side, timeframe, main/'s levels) and
an open position's current state (`OpenPositionView`, for
`position_advisor`) are *not* crate dependencies — both are plain data
arguments `execution` supplies, sourced from `mq_gateway`/its own
position state on the live path or from a recorded fixture on the
replay path.

## Interface exposed upward

```
trait CriticalLevelAnalyzer {
    fn walls(&self, pair: Pair) -> Vec<Level>;                 // own detection
    fn combined_levels(&self, pair: Pair, main_levels: &[Level])
        -> Vec<Level>;                                         // own + main/'s, merged
}

// added 2026-09-09, see wall-visualisation-design.md.
// Visualisation-only: the decision path keeps using Level. Carries the
// two facts Level drops — book side and resting size.
struct WallObservation { price: Price, side: Side, qty: Decimal }

impl WallDetector {
    fn wall_observations(&self, book: &OrderBookSnapshot) -> Vec<WallObservation>;
    // `walls` is defined in terms of this — one threshold, not two.
}

// Where detected walls go to be persisted. Declared here, not in
// state_store, because state_store already depends on this crate: the
// reverse edge would be a dependency cycle. Infallible to the caller —
// it fires on execution's decision path, so a store failure must never
// become a failed trade; implementations meter their own errors.
trait WallSink {
    fn record(&self, pair: &Pair, ts: Ts, walls: &[WallObservation]);
}

// LiveCriticalLevelAnalyzer optionally holds a WallSink and records at
// most one snapshot per interval bucket per pair, bucketed on book.ts
// (not a wall clock, so replay reproduces live).

trait SimpleSignalFeed {
    fn subscribe_signals(&self, pair: Pair) -> Stream<SignalEvent>;
}

trait SignalCheck {
    fn id(&self) -> SignalId;
    fn check(&self, pair: Pair, window: &MarketDataWindow) -> Option<SignalEvent>;
    // called once per iteration per registered check; None = didn't fire
}

trait SignalFactory {
    fn create(&self, config: SignalConfig) -> Box<dyn SignalCheck>;
    // builds the active check set from config at startup — adding a
    // signal later means one more SignalConfig variant + a factory
    // arm, not a change to the iteration loop below
}

enum SignalConfig {
    ExtremeVolumeReversal { threshold: Decimal },
    VolumeProjectedMove { avg_window: Duration, horizon: Duration },
    // avg_window default 10s, horizon ("next N minutes") both
    // parameterized per the request, not hardcoded
}

enum SignalEvent {
    ExtremeVolumeReversal { pair: Pair, direction: Side, magnitude: Decimal, ts: Ts },
    VolumeProjectedMove { pair: Pair, projected_move: Decimal, horizon: Duration, ts: Ts },
}

enum DecisionKind { Open, Close, Modify }

enum Timeframe { M1, M5, M15, M60, M240 }
// the candle interval main/'s own analysis was based on for this
// decision. The set of valid values is main/'s to configure, not
// fixed by this crate — treat this list as the current set, not a
// hardcoded ceiling.

struct DecisionContext {
    pair: Pair,
    kind: DecisionKind,
    side: Side,
    timeframe: Timeframe,
    main_levels: Vec<Level>,     // main/'s support/resistance/target/SL reference
}
// Open question (not yet resolved): main/ does not supply an explicit
// firing window, so what bounds how long a decision stays actionable
// before it lapses is undefined here. Until resolved, treat any
// decision as actionable immediately on receipt with no stated expiry
// — flag this gap rather than inventing a rule not given.

enum SignalAction {
    NoOp,                         // nothing worth doing right now
    Open {
        open_price: Price,
        close_price: Price,       // intended take-profit / exit level
        stop_loss_price: Price,
        fire_at: Ts,              // exact moment chosen by build_signal
        max_wait: Duration,       // how long to wait before treating as stuck
                                   // (neither stop-loss nor close_price resolving)
    },
    Close {
        close_price: Price,       // intended exit price for an existing position
        fire_at: Ts,
        max_wait: Duration,
    },
}

trait SignalBuilder {
    fn build_signal(&self, ctx: &DecisionContext) -> SignalAction;
    // insufficient data or nothing worth acting on both collapse to
    // NoOp — no separate Option/error path for "nothing to do"
}

trait RiskValidator {
    fn validate(&self, signal: SignalAction, ctx: &DecisionContext)
        -> Result<SignalAction, RiskViolation>;
    // meaningful only for the Open variant (see risk_validate above);
    // NoOp/Close pass through unchanged. Ok may carry an adjusted
    // open/stop-loss price (stage 2's refinement loop) — not
    // necessarily what `build_signal` originally proposed.
    // `execution` places the *returned* SignalAction, never the
    // pre-validate one.
}

struct OpenPositionView {
    pair: Pair,
    side: Side,
    open_price: Price,
    current_stop_loss_price: Price,
    current_close_price: Price,
}

enum PositionAdjustment {
    MoveStopLoss { new_stop_loss_price: Price },
    // future adjustment kinds go here — kept to just this one for now
}

trait PositionAdvisor {
    fn advise(&self, pair: Pair, position: &OpenPositionView)
        -> Option<PositionAdjustment>;
    // None = no adjustment warranted right now, the safe default,
    // same as every other "nothing to do" case in this crate
}
```

Consumers: `execution` calls `combined_levels`/`build_signal`/
`validate` in sequence when handling a decision from `mq_gateway`
(translating the inbound `TradeDecision`'s kind/side/timeframe/levels
into a `DecisionContext` first). Once a position is open, `execution`
also calls `position_advisor::advise` on each iteration with an
`OpenPositionView` it maintains, and applies any returned
`PositionAdjustment` itself (moves the resting exchange-native order,
updates internal state) — same "L2 proposes, L3 applies" pattern as
the pre-trade path, just continuous instead of one-shot. `execution`
separately subscribes to `walls`/`subscribe_signals` live for ongoing
timing awareness while a position is open. `replay_harness` drives the
pre-trade traits from recorded `DecisionContext` fixtures plus a
replay-mode `MarketDataFeed` (L1) — no separate replay implementation
of any of this.

## Error handling

Insufficient/bad input data → `SignalAction::NoOp` from `build_signal`,
and `None`/empty from `walls`/`subscribe_signals` — never a guess.
Absence of signal is not the same as a false signal; `execution` must
treat `NoOp` / "no wall detected" / "no signal" as the safe default,
not as an error. A `RiskViolation` from `validate` is likewise a
normal rejection outcome (`execution` reports the decision as not
placed, with a reason), not an exception path. `position_advisor::
advise` returning `None` is the same pattern again — no adjustment is
the safe default, not an omission to flag.

## Testing

Pure-function unit tests, deterministic fixtures — for `walls`,
`combined_levels`, `subscribe_signals`, `build_signal`, `validate`, and
`position_advisor::advise` alike, plus each `SignalCheck` individually.
No live or mocked exchange needed, enforced by the no-exchange_adapter/
execution/mq_gateway-dependency rule above (decision context and
`OpenPositionView` both come in as plain structs, so a test just
constructs them). See Acceptance criteria below for the full breakdown
by sub-component.

## Acceptance criteria (staged)

Split by sub-component, not by dependent-layer readiness (L2 is
mostly self-contained; only the last block genuinely gates on L3).

**Block A — signal creation, management, checking**
- [ ] `SignalFactory::create` builds the correct concrete `SignalCheck`
      for each `SignalConfig` variant.
- [ ] Extreme-volume-reversal: fires above `threshold`, doesn't fire
      at/below it, correct `direction`/`magnitude` in the emitted
      event — tested at the boundary, not just comfortably inside it.
- [ ] Volume-projected-move: produces the expected `projected_move`
      for a fixed avg-volume fixture and `horizon`; changing
      `avg_window`/`horizon` changes the result as expected.
- [ ] Adding a new `SignalConfig` variant requires no change to the
      per-iteration check loop — verified by adding a throwaway test
      signal and confirming only factory + config change.

**Block B — critical level selection**, its two parts each with their
own tests:
- [ ] `walls`: given a fixture order book (known resting-order sizes
      at known prices), returns exactly the expected wall levels — no
      false positives on a uniform-sized book (percentile lands on an
      ordinary value; strict `>` excludes ties), no false negatives on
      an injected outlier at high percentile. Bid and ask sides are
      judged against their own side's size distribution independently
      (not one combined-book statistic), and each returned `Level`'s
      `LevelSource::Wall` carries the side (`Buy`/`Sell`) it was found
      on. `max_spread_distance` excludes out-of-range levels from
      consideration entirely (boundary case: exactly at the clamp
      still counts, just past it is dropped regardless of size).
- [ ] `combined_levels` (the main/↔local glue): given a fixed
      `main_levels` input and a fixed `walls` output, the merge
      behaves per the defined rule — union of both, sorted by price,
      nothing collapsed (a main/ level and a wall at the same price
      stay two separate single-sourced `Level`s).

**Block C — risk validation / best-price selection**
- [ ] Stage 1 (R:R check) accepts a signal that already clears the
      minimum, unchanged.
- [ ] Stage 2 (refinement loop) converges on a candidate drawn from
      `combined_levels` when the original proposal doesn't clear R:R,
      and the chosen open/stop-loss actually comes from the level set
      (not an arbitrary nudge).
- [ ] Stage 2 exhausted → `RiskViolation`, never a best-effort partial
      signal.
- [ ] Best-price selection is exercised against both `walls`-only
      levels and `combined_levels` (with main/'s levels mixed in), to
      confirm main/'s levels actually influence the chosen open/
      close/stop-loss price, not just decorate the level list.

**Block D — communication with `execution` (L3)** — data
structure/format defined now; full round-trip verification gated on
L3 existing (mirrors L0/L1's staged pattern):
- [ ] `DecisionContext`, `SignalAction`, `OpenPositionView`, and
      `PositionAdjustment` (all defined above) are the complete,
      frozen contract for this boundary — `execution` never needs
      anything from `local_analysis` outside these four types.
- [ ] Once `execution` exists: a `TradeDecision` from `mq_gateway`
      correctly becomes a `DecisionContext` (kind/side/timeframe/
      levels mapped, nothing lost or invented), and `execution` acts
      correctly on every `SignalAction` variant (`NoOp`/`Open`/
      `Close`) it can receive — verified against `execution`'s real
      implementation, not an assumed one, same standing rule as L0/L1
      (re-check this block once the next layer lands).

**Block E — ongoing position advisor**
- [ ] Given a fixture `OpenPositionView` and market data showing price
      moved favorably, `advise` returns `MoveStopLoss` with a new price
      that actually improves the position (tighter than the current
      stop-loss, in the profit-securing direction — never loosens it).
- [ ] Given market data with no favorable move, `advise` returns
      `None` — never an adjustment invented to have something to say.
- [ ] Once `execution` exists: it calls `advise` each iteration for
      every open position, and correctly applies a returned
      `MoveStopLoss` (resting exchange-native order amended, internal
      state updated) — verified against `execution`'s real
      implementation, same standing re-check rule as Block D.
