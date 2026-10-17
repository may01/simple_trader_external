# Candle-Bound Overlay (visualiser chart) Implementation Plan

> **Status 2026-10-17: implemented, uncommitted.** Branch `cb-overlay-visualiser` from `layer-implementation` (`6e0ffe2`). Host loop green (state_store 15+96, visualizer_backend 28, visualizer_server 15+58; baseline 15+83 / 25 / 15+52), `node --test` 17/17, headless rendering check passed (Live + History, every toggle). Docker gate 1375/0. Commit (awaiting user confirmation) and the operator's in-stack rendering check pending.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) or superpowers:subagent-driven-development to implement this plan layer-by-layer. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Draw main/'s candle-bound (CB) levels and in-zone markers on the executor visualiser's pair chart, live from stored `indicators` rows, with family / filter / timeframe toggles — in both Live and History mode.

**Spec:** [`external/executor/specs/2026-10-16-cb-overlay-visualiser-design.md`](../specs/2026-10-16-cb-overlay-visualiser-design.md).

**Architecture:** One vertical slice copying the `pair_signals` / `current_indicators` slices: `PgStateReader::read_indicator_series` (L5) → `VisualizerBackend::indicator_series` (L8) → `GET /api/pair_indicators` route + `IndicatorPointDto` → SPA (`static/js/cb_overlay.js` pure logic + `chart.js` series + `pair.js` wiring + `pair.html` controls). No executor-process, wire, table, migration or `main/` change.

**Tech stack:** Rust (`sqlx`/Postgres window functions, `axum`, `serde`), vanilla JS SPA, `node --test` for the pure-JS logic (first JS test in the repo; host node v22, no npm).

**Note on layer taxonomy:** as in [2026-09-21-indicator-panel-plan.md](2026-09-21-indicator-panel-plan.md), `layer-first-planning`'s principles (Docker first, interface before code, RED integration test at each boundary, previous layer green before the next starts) applied over `trade_executor`'s real layers.

---

## Global Constraints

- **Branch:** `cb-overlay-visualiser` from `layer-implementation`. One commit per layer after that layer is green. Never commit without explicit user confirmation.
- **No implementation code in this plan** — signatures and test descriptions only.
- **Read-only role:** the new query runs as `dashboard`; Layer 1 tests connect as `dashboard` via `migrated_reader`.
- **No migration.** `SCHEMA_VERSION` stays 11. `(pair, name, received_at DESC)` serves both halves of the query.
- **Error conventions copied:** decode failure → `StoreError::Decode` (surfaced); not-ready → `200 []`; query failure → `service_unavailable(...)`; empty is `[]`, never `null`; `Decimal` → string.
- **Seeding in tests:** raw `INSERT INTO indicators …` (controlled `received_at`/`expires_at`), the existing `insert_indicator` helpers in `pg_store.rs` / `passive.rs`.
- **Indicators panel untouched** (spec §2). `current_indicators` untouched.
- **Test DB isolation:** never run `test` under the default compose project (live stack's volume `layer-implementation_trader_pgdata`). Inner loop: host `cargo test` against a throw-away postgres from compose project `cbov-test` on host port 5437; final gate: `docker compose -p cbov-test … run --build --rm test`.

---

## Docker Entry Points

From `trade_executor/.worktrees/layer-implementation`:

```bash
# Throw-away postgres for the host inner loop (port override keeps 5436 free)
docker compose -p cbov-test -f docker-compose.yml -f /tmp/…/cbov-ports.yml up -d postgres
TEST_DATABASE_URL=postgres://executor:executor@127.0.0.1:5437/trader \
  cargo test -p state_store -p visualizer_backend -p visualizer_server

# Pure JS logic (host, no npm)
node --test crates/visualizer_server/static/js/cb_overlay.test.js

# Final gate — full workspace in Docker, isolated project
docker compose -p cbov-test -f docker-compose.yml -f /tmp/…/cbov-ports.yml run --build --rm test
docker compose -p cbov-test down -v

# Layer 4 manual check (user-gated): stack up, visualiser rebuilt from the branch
docker compose up -d --build visualizer
curl -s 'http://127.0.0.1:8090/api/pair_indicators?pair=LINKUSDT&from=…&to=…'
# open http://127.0.0.1:8090/pair.html?pair=LINKUSDT
```

- [x] **Step 0.1** Branch `cb-overlay-visualiser` from `layer-implementation`.
- [x] **Step 0.2** Baseline: host `cargo test` for the three crates green before any change; record counts.

---

## Layer 1: Read (L5, `state_store::PgStateReader`)

### Interface

```rust
// crates/state_store/src/pg.rs, impl PgStateReader, beside read_current_indicators
pub async fn read_indicator_series(&self, pair: Pair, from: Ts, to: Ts)
    -> Result<Vec<(Ts, IndicatorReading)>, StoreError>;
```
Seed (newest live row per name, `received_at < from AND expires_at > from`) `UNION ALL` compressed in-window changes (`LAG` over `(name) ORDER BY received_at, seq`: keep when first-in-window, value differs, or `received_at >= prev_expires_at`). Ordered `received_at, seq` as a whole. Tuple `Ts` = `received_at`.

### Integration test → Layer 2 (RED in Docker)

`crates/visualizer_backend/src/lib.rs` tests, beside `current_indicators_reads_back_what_was_stored`:
- [x] `indicator_series_reads_back_seed_and_changes` — one name with a pre-window live row and two in-window rows (one a heartbeat repeat): `backend.indicator_series(pair, from, to)` returns seed + first in-window row only, ordered. RED: compile failure.

### Unit tests (RED) — `crates/state_store/tests/pg_store.rs`, as `dashboard`

- [x] `read_indicator_series_returns_the_seed_row_for_a_name_live_at_from`
- [x] `read_indicator_series_has_no_seed_for_a_name_expired_at_from`
- [x] `read_indicator_series_seed_is_the_newest_pre_window_row`
- [x] `read_indicator_series_folds_heartbeat_repeats_into_one_row_with_the_runs_latest_expiry` *(renamed; see Constraints)*
- [x] `read_indicator_series_does_not_extend_a_run_past_a_value_change` *(added)*
- [x] `read_indicator_series_keeps_a_value_change`
- [x] `read_indicator_series_keeps_the_same_value_after_an_expiry_gap`
- [x] `read_indicator_series_keeps_the_first_in_window_row_even_when_equal_to_the_seed`
- [x] `read_indicator_series_honours_both_window_bounds` *(renamed)*
- [x] `read_indicator_series_excludes_other_pairs`
- [x] `read_indicator_series_orders_by_received_at_then_seq_across_names`
- [x] `read_indicator_series_on_an_empty_table_is_an_empty_vec_not_an_error`
- [x] `read_indicator_series_decodes_support_with_volume`

### Constraints / notes

- `received_at = from` belongs to the window (`>=`), not the seed (`<`): a row can be in exactly one half.
- Unknown `kind` cannot be inserted (CHECK constraint); decode path covered by reusing `decode_indicator_kind`.
- **Spec correction (found at Layer 1):** the spec's filter returned each run's first row with its *own* `expires_at`; under the SPA's hold-until-expiry rule a level that only kept heartbeating would vanish 5 minutes after its first row. The query now folds a run into its first row carrying the run's latest `expires_at` (`SUM` of start flags → `run_id`, `MAX(expires_at) OVER (PARTITION BY name, run_id)`). Spec §4 revised; the SPA store applies the same fold to the one repeat per name that crosses a Live incremental-fetch boundary.

- [x] **Gate:** Layer 1 tests green on host, Docker later. Commit: `feat(state_store): read_indicator_series for the CB overlay`.

---

## Layer 2: Backend (L8, `visualizer_backend`)

### Interface

```rust
pub async fn indicator_series(&self, pair: Pair, from: Ts, to: Ts)
    -> Result<Vec<(Ts, IndicatorReading)>, VisualizerError>;
```

### Integration test → Layer 3 (RED)

`passive.rs`:
- [x] `pair_indicators_endpoint_serves_seed_and_changes` — raw-INSERT, `GET /api/pair_indicators?pair=&from=&to=`, assert exact JSON (string decimals, seed with `received_at < from`). RED: 404.

### Unit tests (RED)

- [x] Layer 1's integration test goes GREEN.
- [x] `indicator_series_on_a_pair_with_no_rows_is_an_empty_vec_not_an_error`
- [x] `indicator_series_degrades_to_a_typed_error_not_a_panic`

- [x] **Gate.** Commit: `feat(visualizer_backend): indicator_series pass-through`.

---

## Layer 3: HTTP (`visualizer_server`)

### Interface

```rust
// src/dto.rs
pub struct IndicatorPointDto { name: String, value: Decimal, kind: String, volume: Option<Decimal>, received_at: u64, expires_at: u64 }
impl From<(Ts, &IndicatorReading)> for IndicatorPointDto;

// src/routes.rs — HistoryParams reused
pub async fn pair_indicators_handler(State<Arc<AppState>>, Query<HistoryParams>) -> Response;
// src/lib.rs: .route("/api/pair_indicators", get(routes::pair_indicators_handler))
```

### Integration test → Layer 4 (RED)

- [x] `pair_indicators_response_matches_the_overlay_contract` — exact key set `expires_at, kind, name, received_at, value, volume`; `value` is a string.
- [x] `every_asset_the_spa_references_is_actually_served` gains `/js/cb_overlay.js` (RED until Layer 4 adds the file).
- [x] `pair_html_has_cb_controls_container` — `id="cb-controls"` present (RED until Layer 4).

### Unit tests (RED) — passive.rs

- [x] Layer 2's integration test goes GREEN.
- [x] `pair_indicators_excludes_other_pairs`
- [x] `pair_indicators_answers_empty_before_the_schema_is_ready`
- [x] `pair_indicators_rejects_a_missing_window` → 400.

- [x] **Gate.** Commit: `feat(visualizer_server): GET /api/pair_indicators`.

---

## Layer 4: SPA

### Interface

```js
// static/js/cb_overlay.js  (globalThis.CbOverlay, no DOM, no chart lib)
class IndicatorSeriesStore { append(rows); valueAt(name, tMs); lastReceivedAt(); clear(); names(); }
const CB_NAME_RE;                                   // ^\d+_(cb_|cbnc_|extdone_)
function sampleInstant(minuteStartMs, windowEndMs); // min(m+59_999, windowEnd)
function markerOffset(bar, tf);                     // max(0.3*(h-l), 0.0002*close) * {15:1,60:2,240:3}
function filterPasses(store, tf, side, tMs, filters);  // AND over checked filters, null passes
function buildOverlay(store, bars, windowEndMs, toggles) -> { [seriesKey]: points[] }
const CB_SERIES_STYLE;                              // seriesKey -> {family, tf, side?, color, kind:"step"|"dots", dashed?, title}
const DEFAULT_TOGGLES;

// static/js/chart.js
function createCbOverlaySeries(chart);              // one series per CB_SERIES_STYLE key, added in createPairChart
function setCbOverlay(state, store, toggles);       // buildOverlay → setData per series
// renderChartLegend: CB family swatches from CB_SERIES_STYLE

// static/js/api.js
async pairIndicators(pair, fromMs, toMs)           // GET /api/pair_indicators

// static/js/pair.js
let cbStore, cbToggles;  // store cleared on backfill / mode switch; incremental fetch on the 5 s tick in Live
function renderCbControls(container)                // checkboxes → cbToggles → setCbOverlay
```

### Unit tests (RED) — `static/js/cb_overlay.test.js`, `node --test`

- [x] `valueAt holds until the next row of the same name`
- [x] `valueAt is null after expiry and before the first row`
- [x] `append dedupes on (name, received_at) and keeps arrays sorted on incremental merge`
- [x] `append drops ema_ and sar names and non-finite values`
- [x] `lastReceivedAt is the max over all names, 0 when empty`
- [x] `sampleInstant is min(m+59999, windowEnd)`
- [x] `filterPasses ANDs checked filters and lets null pass`
- [x] `buildOverlay blanks the zone line where cb_f_extdone samples false`
- [x] `buildOverlay stacks marker offsets by tf and skips minutes without a bar`
- [x] `buildOverlay empties every series of an unchecked tf`
- [x] `buildOverlay emits whitespace points for level gaps`

### Integration check (manual, user-gated — spec §10 "Rendering")

- [x] *(headless, 2026-10-17)* host-built `visualizer` against a throw-away postgres (3 h of 1-minute candles + 15 120 CB rows seeded by SQL), driven over the Chrome DevTools Protocol: 42 names in the store; defaults draw zones (151/181 minutes valued — the seeded `cb_f_extdone_long=0` stretch blanked) and dots at all three tfs; `filter: extdone` off → 181 valued, more long dots; `filter: trend` on → fewer; Bounds / Forming / Extdone draw when on; `15` off empties every 15m series; Markers off empties the dots; History: store emptied on the mode switch, refilled on Load (177 bars). No console errors. Screenshot inspected.
- [ ] **User-gated:** the same check inside the real Docker stack (`docker compose up -d --build visualizer`), and against live `main/` on `cb-markers-main-flow`.

### Constraints / notes

- All overlay series: `autoscaleInfoProvider: () => null`, `lastValueVisible: false`, `priceLineVisible: false`, `crosshairMarkerVisible: false`; levels `lineType: LightweightCharts.LineType.WithSteps`; forming dashed (`LineStyle.Dashed`); dots `lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 3`.
- Redraw is full `setData` per series (replace, never append).
- Toggle state in memory only.

- [x] **Gate:** `node --test` green, Rust suite green (asset + container tests now pass). Commit: `feat(visualizer): candle-bound overlay on the pair chart`.

---

## Layer 5: Docs + final gate

- [x] L5 spec (`specs/layers/L5-state-store.md`): `read_indicator_series` signature + test summary.
- [x] L8 spec (`specs/layers/L8-interfaces.md`): `indicator_series` / `GET /api/pair_indicators` / overlay paragraph.
- [x] Design spec status → `implemented 2026-10-16 (rendering check pending)`; acceptance boxes.
- [x] Full Docker gate green under project `cbov-test` (2026-10-17: **1375 passed / 0 failed**, 54 test binaries, fresh volume, `down -v` after). Two earlier runs were invalid: Postgres hit `No space left on device` (root fs at 98%; the smoke test's host builds had eaten the margin) and the first also shared its `public` schema with the smoke test's `--migrate-only`/seed.
- [x] This plan's status line.
