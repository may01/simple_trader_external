# Volume-imbalance / order-book-depletion signal — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

Implements
[2026-09-17-volume-book-depletion-signal-design.md](../specs/2026-09-17-volume-book-depletion-signal-design.md).
Base: `layer-implementation` worktree, current HEAD `2106e44`.

## Global Constraints

- Work happens in the `layer-implementation` worktree
  (`trade_executor/.worktrees/layer-implementation`), branch
  `layer-implementation`. One commit per layer, after its tests are
  green.
- Layer N is not started until layer N-1's tests are green in Docker.
- Observation-only: no new arm in `run_signal_decision_task` maps
  `SignalEvent::VolumeBookDepletion` to a `Side`. It explicitly joins
  the existing `=> None` arm alongside `ExtremeVolumeReversal`/
  `VolumeProjectedMove` — never place a real order from this signal in
  this plan.
- One documented public-signature change, needed by Layer 1:
  `SignalFactory::create` gains a second parameter,
  `feed: Arc<dyn MarketDataFeed>` (`crates/local_analysis/src/
  signals.rs:134`). Every existing match arm ignores it except the new
  one. Single call site today (`crates/orchestrator/src/system.rs:413`),
  already has `market_data` in scope there — low-risk, but it is a
  breaking signature change and the only one in this plan.
- All 3 concrete instances are percentage-based thresholds:
  `Percent(0.4)` / `Percent(0.6)` / `Percent(1.0)` for horizons
  15/60/240 respectively. `ThresholdSpec::Absolute` stays part of the
  type (Layer 1) for future instances, but no concrete instance
  registered in Layer 2 uses it.
- `SignalEvent::VolumeBookDepletion` carries its own `signal_id:
  SignalId` field (set at construction from `SignalConfig`), rather
  than deriving `SignalId` from a match on the event's payload. This is
  what lets three concrete instances (horizons 15/60/240) share one
  `SignalConfig`/`SignalEvent` variant while still resolving to three
  distinct `SignalId`s (`"volume_book_depletion_15"` etc.) — the
  existing `check.id() == event.signal_id()` invariant
  (`crates/local_analysis/src/types.rs:287-297`) still holds because
  both read the same configured value.
- Adding the new `SignalEvent`/`SignalConfig` variants means every
  exhaustive match on them must gain an arm. Full list (grep-verified,
  no others exist):
  - `crates/local_analysis/src/types.rs:213-221` (`signal_id()`)
  - `crates/local_analysis/src/signals.rs:134-148` (`SignalFactory::create`)
  - `crates/orchestrator/src/system.rs:779-788` (`run_signal_decision_task`'s Side mapping — must resolve to `None`)
  - `crates/state_store/src/pg.rs:874-911` (`record_signal`'s `ts` extraction)
  - `crates/state_store/src/dto.rs:531-568` (`SignalEventDto::from(&SignalEvent)`)
- `signal_log.record`'s stored shape is Bitcoin's — i.e. Rust's — default
  externally-tagged serde JSON: `{"<Variant>": {...}}`. Keep that
  convention for the new variant; no custom `Serialize` impl.
- `SignalEventDto` is currently write-only (`#[derive(Debug, Clone,
  Serialize)]`, no `Deserialize`, no `From<SignalEventDto> for
  SignalEvent`, per its own doc comment at `dto.rs:480-498`). Layer 3
  makes it round-trip — that doc comment's claim becomes false and
  must be corrected (same kind of drift the trade-visualization plan's
  Layer 3 hit with `dto.rs`'s module doc comment).
- Match existing code conventions exactly: doc comments explain *why*,
  `Ts`/`Pair`/`Side`/`Decimal` types reused as-is, `CorruptRow::Surface`
  for every new `PgStateReader` read (dashboard-side reads surface
  corruption, per `read_wall_snapshots`'s/`read_decision_log_rows`'s own
  precedent — this table has a jsonb payload like `decision_log`, not
  typed columns like `wall_snapshot`, so `read_decision_log_rows` is the
  closer template).

---

## Docker Entry Points

```bash
docker compose run --rm test
EXECUTION_MODE=no_trade docker compose up -d postgres executor visualizer
# http://127.0.0.1:8090/pair.html?pair=BTCUSDT
```

Verified:
- [ ] `docker compose run --rm test` green, including every new test below
- [ ] Executor running under `EXECUTION_MODE=no_trade` fires at least one
      of the 3 registered `VolumeBookDepletion` instances against live
      market data without placing any order
- [ ] `signal_log` accumulates rows for `volume_book_depletion_15`/`_60`/`_240`
- [ ] `pair.html` shows a marker per firing, at the `target_price` level
      (not the current candle's close), one color per horizon, in the
      legend

---

## Layer 1: `local_analysis` — depletion projector, config/event types, check, factory

### Interface

```rust
// crates/local_analysis/src/depletion.rs (NEW FILE)

/// Walks `book`'s ask side (net_rate_per_min > 0) or bid side (< 0) by
/// cumulative `qty` until it reaches `|net_rate_per_min| * horizon_minutes`.
/// Returns the price at which that happens, and the direction. `None` when
/// `net_rate_per_min` is zero (no direction), or when the book's visible
/// levels are exhausted before reaching that cumulative volume (see design
/// spec §4.1 — deliberately not extrapolated).
pub fn project_target_price(
    net_rate_per_min: Decimal,
    horizon_minutes: Decimal,
    book: &OrderBookSnapshot,
    current_price: Decimal,
) -> Option<(Decimal /* target_price */, Side /* direction */)>;

// crates/local_analysis/src/types.rs (additions)

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ThresholdSpec {
    Absolute(Decimal),
    Percent(Decimal),
}
impl ThresholdSpec {
    /// Resolves to an absolute price delta given the current price.
    pub fn resolve(&self, current_price: Decimal) -> Decimal;
}

// SignalConfig: new variant
VolumeBookDepletion {
    id: SignalId,
    avg_window: Duration,
    horizon: Duration,
    threshold: ThresholdSpec,
},

// SignalEvent: new variant
VolumeBookDepletion {
    pair: Pair,
    signal_id: SignalId,
    direction: Side,
    target_price: Decimal,
    projected_move: Decimal,
    horizon: Duration,
    ts: Ts,
},

// SignalEvent::signal_id(), new arm:
SignalEvent::VolumeBookDepletion { signal_id, .. } => *signal_id,

// crates/local_analysis/src/signals.rs (additions)

pub struct VolumeBookDepletionCheck {
    pub id: SignalId,
    pub avg_window: Duration,
    pub horizon: Duration,
    pub threshold: ThresholdSpec,
    pub feed: Arc<dyn MarketDataFeed>,
}
impl SignalCheck for VolumeBookDepletionCheck {
    fn id(&self) -> SignalId;
    fn check(&self, window: &MarketDataWindow) -> Option<SignalEvent>;
}

// SignalFactory::create — signature change (see Global Constraints)
impl SignalFactory {
    pub fn create(&self, config: SignalConfig, feed: Arc<dyn MarketDataFeed>) -> Box<dyn SignalCheck>;
}
```

### Constraints / notes

- `current_price` for the projector: taken as the most recent trade's
  price in `window.recent_trades` (last element — oldest-first per
  `MarketDataWindow`'s own doc comment), not derived from the order
  book. If `recent_trades` is empty, `check()` returns `None` before
  ever calling the projector (mirrors `VolumeProjectedMoveCheck`'s
  existing `if !any { return None; }` guard).
- **Open point carried from the design spec, to resolve here, not
  assumed:** verify `OrderBookSnapshot.asks`/`.bids` are already
  sorted touch-outward (ascending for asks, descending for bids) by
  `BookTracker`. If not guaranteed, `project_target_price` must sort
  defensively before walking — check `crates/market_data/src/book.rs`
  before writing the unit tests below, and note which case applies in
  the doc comment.
- `net_rate_per_min` computed exactly like `VolumeProjectedMoveCheck`
  today (sum `qty` by `Side` over trades within `avg_window` of
  `window.now`), but expressed per-minute instead of per-second —
  match `avg_window`'s own units, do not silently convert; horizon in
  `project_target_price` is also minutes, so both sides of the
  multiplication agree without a conversion factor to get wrong.
- Firing condition (level check, stateless — design spec §4.2 step 5,
  amended): `projected_move > threshold.resolve(current_price)` when
  `direction == Side::Buy`, `projected_move < -threshold.resolve(current_price)`
  when `direction == Side::Sell`. Evaluated fresh every `check()` call,
  no stored state.

### Integration test → Layer 2 (RED, Docker)

A fake `MarketDataFeed` test double (new, local to `local_analysis`'s
test module — no existing one returns a controllable `OrderBookSnapshot`)
wired through `SignalFactory::create` and one `check()` call:

```rust
// crates/local_analysis/src/signals.rs, #[cfg(test)]
#[test]
fn volume_book_depletion_fires_when_projected_move_exceeds_threshold() {
    // FakeFeed::with_book(asks: [(100.5, 5), (101.0, 10)], bids: [...])
    // window.recent_trades: net buy volume over avg_window such that
    // net_rate_per_min * horizon_minutes lands the walk at price 101.0,
    // i.e. projected_move = 101.0 - current_price, engineered > threshold.
    // Assert Some(SignalEvent::VolumeBookDepletion { direction: Side::Buy,
    // target_price: dec!(101.0), signal_id: SignalId("test_id"), .. }).
}
#[test]
fn volume_book_depletion_skips_when_book_depth_is_insufficient() {
    // Thin book (total ask qty < cumulative_target). Assert None --
    // the skip-fire-and-log policy, not an extrapolated guess.
}
```

### Run to verify it fails

`cargo test -p local_analysis volume_book_depletion` — expected: FAIL
(types/fn don't exist yet).

### Unit tests (RED)

- `project_target_price`: exact-level match (cumulative lands exactly
  on a level boundary), interpolation-free by design (returns that
  level's price, not an interpolated one — confirm this is the
  intended precision per design spec, it doesn't call for
  interpolation), zero net rate → `None`, depth-exhausted → `None`,
  buy direction walks asks / sell direction walks bids (not swapped).
- `ThresholdSpec::resolve`: `Absolute` passes through unchanged;
  `Percent(1.0)` at `current_price = 100` → `1.0`.
- `VolumeBookDepletionCheck::check`: no trades in window → `None`
  (matches `VolumeProjectedMoveCheck`'s existing guard); net rate
  positive but projected move under threshold → `None`; net rate
  positive and projected move over threshold → fires with
  `direction: Side::Buy`; mirrored for `Side::Sell`.
- `id()` returns exactly the configured `self.id`, and a fired
  event's `signal_id()` returns that same value (the invariant this
  design leans on — write the property test the existing
  `types.rs:287-297` test generalizes, or extend that test's table if
  it's table-driven).

### Run full suite, commit

```bash
cargo test -p local_analysis
git add crates/local_analysis
git commit -m "feat(local_analysis): order-book-depletion volume signal"
```

---

## Layer 2: `orchestrator` — register the 3 concrete instances

### Interface

No new public function signature. Extends the `checks` vec literal at
`crates/orchestrator/src/system.rs:413` (see Global Constraints for the
exact 3-entry list: horizons 15/60/240, `avg_window = 5m` for all
three, thresholds `Percent(0.4)` / `Percent(0.6)` / `Percent(1.0)` — all
three percentage-based, none use `ThresholdSpec::Absolute`)
and adds `SignalEvent::VolumeBookDepletion { .. }` to the existing
`=> None` arm at `system.rs:782`.

### Integration test → Layer 3 (RED, Docker)

```rust
// crates/orchestrator/src/tests.rs
#[tokio::test]
async fn volume_book_depletion_signals_are_logged_without_a_decision() {
    // Drive run_signal_decision_task with a pipeline holding a
    // VolumeBookDepletionCheck (constructed the same way system.rs
    // does), a FakeAccountFeed whose order_book/recent_trades are
    // engineered to fire it. Assert: executor_spy never receives a
    // decision (open-position count stays 0), and
    // state_store_spy.signal_log has a VolumeBookDepletion row with the
    // right signal_id.
}
```

### Run to verify it fails

`cargo test -p orchestrator volume_book_depletion_signals_are_logged_without_a_decision`
— expected: FAIL (checks vec doesn't include it yet).

### Unit tests (RED)

- All 3 `SignalId`s (`volume_book_depletion_15`/`_60`/`_240`) are
  distinct and each fires independently (a scenario tuned to cross
  only the 15-minute threshold must not also fire the 60/240 entries).
- `EXTREME_VOLUME_THRESHOLD`/`VOLUME_AVG_WINDOW_SECS`/`VOLUME_HORIZON_SECS`
  env vars (already parsed by `OrchestratorConfig::from_env`, currently
  unused per `system.rs:402-405`) are confirmed still unused by this
  layer — the 3 instances are hardcoded params, not env-driven; note
  this explicitly rather than silently leaving the existing config
  dead code more confusingly dead.

### Constraints / notes

- Follows the exact registration pattern already in `system.rs:402-439`
  (one `SignalPipeline` per pair, this signal's checks added to the
  same `checks` vec as `MockVolumeCross`, not a separate pipeline).
- `SignalFactory.create(config, market_data.clone() as Arc<dyn
  MarketDataFeed>)` for every entry now, including the existing
  `MockVolumeCross` one — the signature change from Layer 1 touches
  this call site regardless of which variant is being constructed.

### Run full suite, commit

```bash
cargo test -p orchestrator
git add crates/orchestrator
git commit -m "feat(orchestrator): register 3 volume-book-depletion signal instances (observation-only)"
```

---

## Layer 3: `state_store` — read `signal_log` back

### Interface

```rust
// crates/state_store/src/dto.rs
// SignalEventDto gains Deserialize, a new VolumeBookDepletion variant,
// and the read direction it currently explicitly lacks:
#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) enum SignalEventDto {
    // ...existing variants unchanged...
    VolumeBookDepletion {
        pair: Pair,
        signal_id: String, // SignalId's &'static str, stored/read as owned String
        direction: Side,
        target_price: Decimal,
        projected_move: Decimal,
        horizon: Duration,
        ts: Ts,
    },
}
impl From<&SignalEvent> for SignalEventDto { /* new arm */ }
impl From<SignalEventDto> for SignalEvent { /* NEW impl, all variants */ }

// crates/state_store/src/pg.rs
pub async fn read_signal_log(&self, pair: Pair, from: Ts, to: Ts)
    -> Result<Vec<(Ts, SignalEvent)>, StoreError>; // on PgStateReader
```

### Constraints / notes

- `SignalId` is `SignalId(pub &'static str)` — not deserializable as
  `&'static str` from a DB round trip. Store/read it as an owned
  `String` inside the DTO (see interface above), and construct a
  `SignalEvent`'s `signal_id: SignalId` field from one of the 3 known
  literal constants by matching the decoded string in `From<SignalEventDto>
  for SignalEvent` (`"volume_book_depletion_15" => SignalId("volume_book_depletion_15")`,
  etc.) — mirrors how `wall_side_from_db` already turns a stored string
  back into a static Rust value (`pg.rs`, `read_wall_snapshots`'s
  neighbor). An unrecognized string is a corrupt row (`CorruptRow`
  policy), not a panic.
- Follows `read_decision_log_rows`'s shape exactly (`pg.rs:231-284`):
  materialize into a `Vec`, decode `record` as JSON with `on_corrupt`,
  `CorruptRow::Surface` for `PgStateReader`'s own new
  `read_signal_log` (dashboard policy — same reasoning as
  `read_wall_snapshots`/`read_decision_log`: an unreadable signal must
  not silently look like "no signal fired"). `StateStoreImpl` gets no
  read counterpart — `signal_log` is write-only for the executor, same
  as `wall_snapshot`.
- Query: `SELECT record::text AS record, ts FROM signal_log WHERE pair
  = $1 AND ts >= $2 AND ts <= $3 ORDER BY ts, seq` (the table's actual
  PK, `seq`, breaks same-`ts` ties — same role `ins_seq`/`seq` play in
  every sibling `read_*` function).
- Correct `dto.rs:480-498`'s doc comment — it currently states
  `SignalEventDto` is write-only with no read direction; that becomes
  false after this layer (same drift the trade-visualization plan hit
  and fixed in its own Layer 3).

### Integration test → Layer 4 (RED, Docker)

```rust
// crates/state_store/tests/pg_store.rs
#[tokio::test]
async fn read_signal_log_reads_back_what_record_signal_wrote() {
    // Executor role: record_signal(pair, SignalId("volume_book_depletion_15"),
    // &VolumeBookDepletion{...}, None). Dashboard role:
    // PgStateReader::read_signal_log(pair, from, to) returns that same
    // event, decoded, with the right signal_id/target_price/direction.
}
#[tokio::test]
async fn read_signal_log_excludes_other_pairs_and_out_of_window_rows() {
    // Mirrors read_wall_snapshots_excludes_rows_outside_the_window_and_other_pairs.
}
```

### Unit tests (RED)

- A corrupt `record` jsonb surfaces as `Err(StoreError::Decode(...))`,
  not a skip and not a panic (`CorruptRow::Surface`).
- An unrecognized `signal_id` string (shouldn't happen, but the decode
  path must not panic on it) also surfaces as `Err`, not a crash.
- Round trip for all 3 concrete `signal_id`s (`_15`/`_60`/`_240`),
  proving the string→`SignalId` match covers every registered instance.

### Run full suite, commit

```bash
cargo test -p state_store
git add crates/state_store
git commit -m "feat(state_store): read signal_log back (VolumeBookDepletion round-trip)"
```

---

## Layer 4: `visualizer_backend` — thin wrapper

### Interface

```rust
// crates/visualizer_backend/src/lib.rs
pub async fn signals(&self, pair: Pair, from: Ts, to: Ts)
    -> Result<Vec<(Ts, SignalEvent)>, VisualizerError>;
```

Exact pass-through pattern as `wall_snapshots`/`position_events`:
`Ok(self.state.read_signal_log(pair, from, to).await?)`.

### Integration test → Layer 5 (RED, Docker)

```rust
// crates/visualizer_backend/src/lib.rs, #[cfg(test)]
#[tokio::test]
async fn signals_reads_back_what_the_writer_logged() {
    // Seed via state_store (executor role): record_signal for two
    // different signal_ids on the same pair. backend.signals(...)
    // returns both.
}
```

### Unit tests (RED)

- A database error degrades to `VisualizerError`, never a panic (same
  property as every other method on this type).
- No rows in window → `Ok(vec![])`.

### Run full suite, commit

```bash
cargo test -p visualizer_backend
git add crates/visualizer_backend
git commit -m "feat(visualizer_backend): expose signals read"
```

---

## Layer 5: `visualizer_server` — DTO + route

### Interface

```rust
// crates/visualizer_server/src/dto.rs
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum SignalEventDto {
    ExtremeVolumeReversal { pair: Pair, direction: Side, magnitude: Decimal },
    VolumeProjectedMove { pair: Pair, projected_move: Decimal, horizon_secs: u64 },
    VolumeBookDepletion {
        pair: Pair,
        signal_id: String,
        direction: Side,
        target_price: Decimal,
        projected_move: Decimal,
        horizon_secs: u64,
    },
    // Mock* variants omitted -- not display-worthy on this dashboard,
    // same reasoning DecisionLevelDto gives for leaving out fields
    // nothing renders.
}
impl From<&local_analysis::SignalEvent> for SignalEventDto { ... }

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SignalLogEntryDto {
    pub ts: Ts,
    #[serde(flatten)]
    pub event: SignalEventDto,
}
impl From<(Ts, &local_analysis::SignalEvent)> for SignalLogEntryDto { ... }

// crates/visualizer_server/src/routes.rs
pub async fn pair_signals_handler(
    State(state): State<Arc<AppState>>, Query(params): Query<HistoryParams>,
) -> Response { ... }
```

Route, alongside the existing ones:
```
GET /api/pair_signals?pair=&from=&to=  -> Vec<SignalLogEntryDto>
```

### Constraints / notes

- Reuses `HistoryParams` exactly (no new query-param struct — same
  `pair`/`from`/`to` shape every sibling route already takes).
- `horizon_secs: u64` (not a serialized `Duration` struct) — matches
  this crate's existing "plain, display-ready fields, not a shape the
  SPA must re-derive" convention (`TradeDecisionDto`'s `kind`/
  `timeframe` as plain strings is the precedent cited in the trade-viz
  plan).
- Not ready (schema unapplied) → `Json(Vec::<SignalLogEntryDto>::new())`,
  HTTP 200 — same posture as every existing handler.

### Integration test → Layer 6 (RED, Docker)

```rust
// crates/visualizer_server/tests/passive.rs
#[tokio::test]
async fn pair_signals_returns_real_firings_in_arrival_order() {
    // Seed signal_log for a pair (two VolumeBookDepletion firings,
    // different horizons) via the executor role. GET /api/pair_signals
    // returns both, in ts order, target_price present on both.
}
#[tokio::test]
async fn pair_signals_excludes_other_pairs() {
    // Cross-pair isolation, same property every other pair-scoped
    // route already has its own test for.
}
```

### Unit tests (RED)

- Not-ready returns `[]`, HTTP 200.
- A `VolumeBookDepletion` entry round-trips with `target_price` present
  and correct (this is the field Layer 6's markers depend on).

### Run full suite, commit

```bash
cargo test -p visualizer_server
git add crates/visualizer_server
git commit -m "feat(visualizer_server): pair_signals route"
```

---

## Layer 6: SPA — chart markers at the projected price level

### Interface

```
js/api.js    + pairSignals(pair, fromMs, toMs) -> GET /api/pair_signals
js/pair.js   + fetches pair signals on the same 5s poll cadence as
               decisions/position-events (design §4.6: poll only, no
               /ws change -- /ws stays MarketDataEvent-only) and calls
               chart.js's new setter each tick
js/chart.js  + SIGNAL_MARKER_STYLE: one entry per horizon
               (volume_book_depletion_15/_60/_240), 3 distinct colors
             + createSignalMarkerSeries(chart) -- same
               addLineSeries({lineVisible:false, pointMarkersVisible:true, ...})
               technique as createTradeMarkerSeries/createWallSeries
             + setSignalMarkers(state, entries) -- maps each
               SignalLogEntryDto with a VolumeBookDepletion payload to
               {time: tsToTime(entry.ts), value: num(entry.VolumeBookDepletion.target_price)}
               on the series matching its signal_id; entries with a
               different payload kind (ExtremeVolumeReversal/
               VolumeProjectedMove) are not drawn -- this layer only
               visualizes VolumeBookDepletion, per design §4.6 scope
```

### Constraints / notes

- **Marker y-value is `target_price`, not the current candle's
  close** — this is the one place this overlay differs from
  `setTradeMarkers`'s pattern, which plots at the event's actual fill
  price. Get this field from the DTO, not derived client-side.
- 3 series, not 1 shared series with per-point color — matches
  `createWallSeries`/`createTradeMarkerSeries`'s existing per-kind-
  series precedent.
- `renderChartLegend` (`chart.js:106-145`) gains 3 entries, one per
  horizon.
- Full-replace on each poll tick (`setData`), not incremental — same
  as `setTradeMarkers`. Given Layer 1's stateless level-check fires
  every qualifying tick (design spec §5 point 7), expect a denser
  marker series during a sustained imbalance than the trade-lifecycle
  markers this is templated on; no dedup/throttle in this layer (design
  spec leaves that an open, deferred call).

### Integration test → Layer 7 (RED, Docker)

```rust
// crates/visualizer_server/tests/passive.rs
#[tokio::test]
async fn pair_html_has_no_new_containers_required() {
    // No new panel/container needed (markers only, no new list panel) --
    // confirm pair.html still serves 200 and existing containers are
    // unaffected. If a legend container needs a new element id, assert
    // its presence instead.
}
```

### Unit tests (RED)

- `node --check crates/visualizer_server/static/js/{api,pair,chart}.js`
  — no syntax errors (this project's established no-JS-runner
  convention, per the trade-viz plan's own Layer 4).

### Run full suite, commit

```bash
cargo test -p visualizer_server
git add crates/visualizer_server
git commit -m "feat(spa): volume-book-depletion signal markers on the chart"
```

---

## Layer 7: verification

- [ ] `docker compose run --rm test` green
- [ ] `EXECUTION_MODE=no_trade docker compose up -d postgres executor visualizer`
- [ ] `SELECT signal_id, count(*) FROM signal_log WHERE signal_id LIKE
      'volume_book_depletion_%' GROUP BY signal_id;` — all 3 present
      and growing (240 expected to grow slowest/skip most, per the
      depth-exhaustion policy — not a bug if it's rare or absent early
      on)
- [ ] Open `pair.html?pair=BTCUSDT` — signal markers appear at
      `target_price` levels (visibly off the candle body, since they're
      projections), one color per horizon, legend shows all 3
- [ ] Confirm no order was ever placed from these signals — position
      state / `event_log` shows nothing attributable to
      `volume_book_depletion_*` (there is no decision path for them to
      have used, but verify empirically, not just by code inspection)
- [ ] Stop the executor — chart keeps showing last-read markers rather
      than erroring, same posture as every other panel
