# Volume-Imbalance / Order-Book-Depletion Signal — Design Spec

Date: 2026-09-17
Status: approved for planning
Target project: `trade_executor` (Rust workspace), worktree `layer-implementation`
Scope: signal computation + observation/visualization only. Execution wiring (fired signal → real order) is explicitly deferred to a later spec.

## 1. Origin / template

A reusable signal template, parametrized by three values:

- `X` — minutes, moving-average window for buy/sell volume (default 5)
- `N` — minutes, projection horizon
- `P` — threshold the projected price move must cross to fire (absolute price delta, or % of current price)

Template steps:
1. Compute X-min buy volume MA and X-min sell volume MA.
2. Net rate = (buy MA − sell MA) → average 1-min net volume over the last X minutes.
3. Direction = sign(net rate). Zero → no signal.
4. Project how far price moves in N minutes if that net rate holds, via **order-book depletion**: the cumulative volume `|net rate| * N` that would need to be absorbed is walked against the live ask side (net rate > 0, buying pressure eating asks) or live bid side (net rate < 0), price level by price level, until cumulative book volume reaches that amount. That price level is the projection target.
5. Fire when the projected move is beyond P — `projected_move > P` when direction is up, `projected_move < -P` when direction is down. Stateless level check, evaluated fresh each tick (fires every tick the condition holds, not just once per crossing).

## 2. Why this repo, not `main/` (Python)

`main/` (simple_trader, Python) has a parallel `BaseSignal`/`SignalChain` framework and buy-volume data, but:
- No order-book data at all in the historical/backtest pipeline, and only an unused live REST `depth()` snapshot method with zero callers.
- The projection step is inherently live-only (order-book depletion needs a live book; no historical order-book data exists anywhere in the org, so no backtest/chart-over-history is possible for this signal).

`trade_executor` (Rust) already has:
- A live-maintained L2 order book per pair (`crates/market_data`, `BookTracker`, fed by Binance diff-depth WS + REST resync).
- A `SignalCheck` trait / `SignalConfig` / `SignalFactory` framework (`crates/local_analysis`).
- An **existing placeholder** for exactly this feature: `VolumeProjectedMoveCheck` (`crates/local_analysis/src/signals.rs:87-132`) already computes net buy/sell volume rate from the trailing trade window and projects it over a horizon, but multiplies by a hardcoded `PLACEHOLDER_ELASTICITY` constant, with a doc comment explicitly deferring "the actual volume->price elasticity model" to its own spec. This spec is that follow-up: replace the placeholder elasticity with the real order-book-depletion walk.
- A live dashboard (`visualizer_server`) with a real candlestick chart and an established marker-overlay pattern (trade-lifecycle markers, wall overlays) to extend for "signal fired" markers.

Decision: **implement in `trade_executor`**, live-only, observation/visualization only — no execution wiring yet.

## 3. Data already available (reuse, no new ingestion)

- **Buy/sell volume**: `TradeTick { pair, price, qty, side: Side, trade_id, ts }` (`exchange_adapter/src/lib.rs:203-211`) — every existing volume check derives buy/sell MAs by summing `qty` by `side` over a trailing window of `MarketDataWindow.recent_trades`. This is already equivalent to "X-min MA of buy/sell volume" (sum over last X minutes ÷ X = avg 1-min volume) — no gap here, reuse the exact pattern from `VolumeProjectedMoveCheck::check` (`signals.rs:102-114`).
- **Live order book**: `MarketDataFeed::order_book(pair) -> OrderBookSnapshot { bids: Vec<PriceLevel>, asks: Vec<PriceLevel>, sequence, ts }` (`crates/market_data/src/lib.rs:66`), `PriceLevel { price, qty }` (`exchange_adapter/src/lib.rs:147-201`). Live-maintained by `BookTracker` applying WS deltas onto REST snapshots with gap detection (`crates/market_data/src/book.rs:10-52`). Already consumed the same way (holding `Arc<dyn MarketDataFeed>`, calling `.order_book(pair)` synchronously) by `WallDetector`/`LiveCriticalLevelAnalyzer` (`crates/local_analysis/src/levels.rs`) — this new check follows that exact precedent rather than changing the `SignalCheck::check(&self, window)` signature.

## 4. New components

### 4.1 Order-book depletion projector
Pure function (new module in `local_analysis`), given `net_rate: Decimal`, `horizon_minutes: u32`, `book: &OrderBookSnapshot`, `current_price: Decimal`:

- `cumulative_target = net_rate.abs() * horizon_minutes`
- side = asks if `net_rate > 0`, bids if `net_rate < 0`; `net_rate == 0` → `None` (no direction, no signal)
- walk that side's `PriceLevel`s in touch-outward order, accumulating `qty`, until cumulative ≥ `cumulative_target` → that level's `price` is `target_price`
- **if the book's visible levels don't hold `cumulative_target` before running out (depth exhausted) → return `None` (skip-fire-and-log), do not extrapolate.** This is a deliberate, agreed policy: an order-book-depletion projection with no book to back it is not a valid signal. Expected to trigger more often for longer horizons (N=240 needs to absorb 4h of the current net rate, likely exceeding visible near-touch depth) — log/metric this skip path so it's visible how often it happens per signal instance.
- `projected_move = target_price - current_price` (signed, sign matches `net_rate`'s direction)

### 4.2 Signal check
New/replacing `VolumeProjectedMoveCheck` (`local_analysis/src/signals.rs:87-132`), constructed with an `Arc<dyn MarketDataFeed>` (for `order_book`) plus its own params (see 4.4). On each `check(&self, window)`:
1. Compute `net_rate` from `window.recent_trades` over `avg_window` (X), as today.
2. If zero → no event.
3. Call the depletion projector (4.1) with the feed's current `order_book(window.pair)`. `None` → no event (skip-fire-and-log per 4.1's policy).
4. Resolve `P` to an absolute price delta (`Absolute(v) => v`, `Percent(p) => current_price * p / 100`).
5. **Level check, stateless**: fire when `projected_move > P` (direction up) or `projected_move < -P` (direction down). No memory of previous calls needed — `check(&self, window)` stays pure, no interior mutability required. Fires every tick the condition holds (repeat fires while the projected move stays beyond threshold), matching the codebase's existing `Over_Level`/`Under_Level`-style level checks rather than a crossing/edge check.

### 4.3 Config / identity
- New `SignalConfig` variant (or the existing `VolumeProjectedMove` variant repurposed — its own comment already anticipates this): `{ avg_window: Duration, horizon: Duration, threshold: ThresholdSpec }` where `ThresholdSpec = Absolute(Decimal) | Percent(Decimal)`.
- `SignalId`: **single parametrized variant** carrying the horizon (e.g. `SignalId::VolumeBookDepletion { horizon_minutes: u32 }`), rather than one enum variant per concrete instance — since the 3 concrete signals differ only in horizon/threshold and share the same check logic. Exact field set (whether `avg_window`/`threshold` also need to be part of the identity for `HashMap<SignalId, _>` uniqueness in the replay harness) to be finalized at plan time; must stay `Eq + Hash`.
- Registered per pair in `system.rs` (today only `MockVolumeCross` is registered there, `system.rs:412-414`) — add the 3 concrete instances (4.5) alongside it.

### 4.4 Execution wiring — explicitly deferred
No new arm in `run_signal_decision_task` (`orchestrator/src/system.rs:739-855`). The signal fires, gets persisted via `SignalSink::record_signal` (existing, `state_store/src/pg.rs:899`, table `signal_log`), and is visualized (4.6) — but does **not** map to a `Side`/`TradeDecision`, so no order is ever placed from it in this iteration. Wiring to `executor.handle_decision` is a separate, later spec once the projection model has been observed live.

### 4.5 Three concrete instances

| id (horizon) | X (avg_window) | N (horizon) | P (threshold) |
|---|---|---|---|
| 15 | 5m | 15m | 0.4% of current price |
| 60 | 5m | 60m | 0.6% of current price |
| 240 | 5m | 240m | 1% of current price |

All three now percentage-based, not absolute — `ThresholdSpec::Absolute` stays part of the type (still valid for future instances) but none of the 3 concrete instances use it.

### 4.6 Visualization
- `signal_log` currently has zero read-side plumbing (write-only via `SignalSink`). Add:
  - `state_store`: a read method (new trait or addition to the existing `PgStateReader`-equivalent) for `signal_log`, mirroring `read_wall_snapshots`/`read_event_log`/`read_decision_log`.
  - `visualizer_backend`: a method calling that read.
  - `visualizer_server`: new `GET /api/pair_signals` route + DTO, `{ts, signal_id, horizon_minutes, target_price, projected_move, threshold, ...}` shaped like the existing `{ts, <Kind>: {...}}` flatten convention (`PositionEventEntryDto`/`DecisionEntryDto`). Polled every 5s from the frontend (like walls/decisions), **not** pushed over `/ws` — `/ws` is reserved for raw `MarketDataEvent`s per the existing house rule (`routes.rs:180-189`).
- Frontend (`crates/visualizer_server/static/js/chart.js`): new marker series following the existing `TRADE_MARKER_STYLE` / `createTradeMarkerSeries` / `setTradeMarkers` pattern (`chart.js:324-405`) — one dot style per signal instance (3 colors, one per horizon), full-replace on each poll tick, plus a legend entry (`renderChartLegend`, `chart.js:106-145`). Reuses the existing per-pair candle chart page (`pair.html`); no new page needed.
- **Marker placement**: `{time: <fire tick's ts>, value: target_price}` — the marker sits at the *projected* price level (`target_price` from 4.1, i.e. `current_price + projected_move`), not at the current candle's close. This differs from the trade-lifecycle markers it's templated on, which plot at the event's actual fill price; here the y-value is a forward-looking projection, so the dot will typically sit above/below the current candle. `/api/pair_signals` (4.6 route) must include `target_price` in its payload for this, not just `projected_move`.

## 5. Unclear / open points carried forward

1. ~~Depth-insufficiency policy~~ — **resolved**: skip-fire-and-log (4.1).
2. ~~Firing semantics~~ — **resolved**: stateless level check (`projected_move` beyond ±P, fires every qualifying tick), not edge-triggered crossing. No interior mutability needed in the check (4.2 step 5).
3. ~~Execution wiring~~ — **resolved**: deferred, out of scope for this spec (4.4).
4. ~~`SignalId` shape~~ — **resolved direction**: single parametrized variant; exact field set for `Eq + Hash` uniqueness to finalize at plan time (4.3).
5. **Not yet resolved**: exact `SignalConfig`/`SignalId` field set and whether `VolumeProjectedMove` is replaced in place or a new variant is added alongside it (to be decided during implementation planning, not a design-level fork).
6. **Not yet resolved**: `OrderBookSnapshot` depth (number of levels) currently held by `BookTracker` — whether the default REST/WS-maintained depth is sufficient for the 15/60-minute horizons even though 240 is expected to skip frequently. Should be checked empirically during implementation/testing, not assumed.
7. **Not yet resolved**: since firing is now a stateless level check (repeat-fires every tick the condition holds, per point 2), `signal_log` will accumulate one row per qualifying tick, not one per crossing — could be dense during a sustained imbalance. Whether to dedupe/throttle at the write or visualization layer (vs. logging every fire as-is) is a plan-time call, not a design blocker.
