# Visualizer × state_store cache integration — implementation plan

> **Deferred 2026-09-13 — do not execute.** Per direct instruction:
> Layers 1-4 below (Event Log panel, entry/SL/TP overlay lines, and the
> analysis overlay added in a later revision) visualize data that is
> not properly implemented on the backend yet — `current_analysis` has
> no producer in main/ at all, and `event_log`/`current_levels` were
> never verified end-to-end. None of it should ship to the dashboard
> before that changes. This plan is not currently being worked; kept as
> the recorded shape of the work for whenever the backend catches up.
> Re-verify every backend precondition below before resuming — this
> document does not update itself when main/ changes.

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development or superpowers:executing-plans
> to implement this plan task-by-task. Steps use checkbox (`- [ ]`)
> syntax for tracking.

Implements
[2026-09-12-visualizer-state-integration-design.md](../specs/2026-09-12-visualizer-state-integration-design.md).
Base: `postgres-live-binance` (currently 12 files uncommitted, nothing
committed yet), rebased onto `layer-implementation` @ `998bb98`.

## Docker Entry Points

Ground truth, unchanged from the SPA-port plan:

```bash
docker compose run --rm test
docker compose up executor visualizer   # http://127.0.0.1:8090/
docker compose up postgres visualizer   # executor down, must still render
```

Verified:
- [ ] `docker compose run --rm test` green, including every new test below
- [ ] Event Log panel shows real `PositionStateEvent`s for a pair with
      trading history
- [ ] Chart shows SL/TP lines for a pair with rows in `current_levels`
- [ ] `reconciliationHealthy`/`reconciliationFlag` no longer exist in
      `format.js`

---

## Layer 0: rebase

- [ ] Rebase (or merge) `postgres-live-binance` onto `layer-implementation`
      @ `998bb98`. Resolve `visualizer_server`/`visualizer_backend`
      conflicts in favor of `postgres-live-binance`'s working tree
      (`dto.rs`, `books.rs`, `routes.rs`, the static SPA); take
      `state_store`/`db_schema` from `layer-implementation` as-is.
- [ ] `docker compose run --rm test` green post-rebase, before touching
      anything else — confirms the merge itself introduced no
      regression before new work starts on top of it.

## Layer 1: `state_store` — `PgStateReader` read surface

### Interface

```rust
// crates/state_store/src/pg.rs, impl PgStateReader
pub async fn read_event_log(&self, pair: Pair, from: Ts, to: Ts)
    -> Result<EventLogStream, StoreError>;
pub async fn current_levels(&self, pair: Pair)
    -> Result<Option<(Vec<Level>, Ts)>, StoreError>;
pub async fn current_analysis(&self, pair: Pair, kind: String)
    -> Result<Option<(Vec<u8>, Ts)>, StoreError>;
```

All three bodies are the same query `StateStoreImpl`'s own `impl
StateStore` already runs — this is exposing existing, tested SQL on a
second type, not writing new SQL. `PgStateReader` connects as the
`dashboard` role (`SELECT`-only); no write method (`persist_analysis`,
`log_event`) is added alongside these — see design §1 for why
`current_analysis` is the one analysis read this dashboard needs,
`read_analysis_log` is not.

### Integration test → Layer 2 (RED, Docker)

```rust
// crates/state_store/tests/pg_reader.rs (new or extend existing)
#[tokio::test]
async fn dashboard_role_reads_event_log_and_current_levels_the_executor_wrote() {
    // StateStoreImpl (executor role) writes a PositionStateEvent and a
    // Decision carrying levels; PgStateReader (dashboard role, separate
    // connection) reads both back. Proves the grant, not just the query.
}
#[tokio::test]
async fn dashboard_role_reads_the_latest_analysis_record_the_executor_persisted() {
    // StateStoreImpl.persist_analysis(pair, kind, bytes, ts) writes;
    // PgStateReader.current_analysis(pair, kind) reads the same bytes
    // back over the dashboard role. A second persist_analysis call for
    // the same (pair, kind) must overwrite what this read returns, not
    // append -- current_analysis is the upsert side, not the log.
}
```

### Unit tests (RED)

- `read_event_log` never returns another pair's events (mirrors the
  existing `StateStoreImpl` test of the same property).
- `current_levels` on a pair with no decisions yet returns `Ok(None)`,
  not an error.
- `current_analysis` on a `(pair, kind)` with no `persist_analysis` call
  yet returns `Ok(None)`, not an error; a second `persist_analysis` for
  the same key overwrites what the next `current_analysis` call returns.
- A corrupt/undecodable row in any of the three reads as absent
  (`Ok(None)`/empty), per the design's existing "cache miss, not a hard
  failure" policy — same convention `StateStoreImpl`'s own readers use.

### Constraints / notes

- No `current_command`, no `read_analysis_log`, no `persist_analysis`/
  `log_event` — see design §1 for why.

## Layer 2: `visualizer_backend` — thin wrappers

### Interface

```rust
// crates/visualizer_backend/src/lib.rs
pub async fn position_events(&self, pair: Pair, from: Ts, to: Ts)
    -> Result<Vec<PositionStateEvent>, VisualizerError>;
pub async fn current_levels(&self, pair: Pair)
    -> Result<Option<(Vec<Level>, Ts)>, VisualizerError>;
pub async fn current_analysis(&self, pair: Pair, kind: String)
    -> Result<Option<(Vec<u8>, Ts)>, VisualizerError>;
```

All three are `?`-propagation over the new `PgStateReader` methods, same
shape as `historical`/`freshness` already in this file — no new
control flow to test beyond the `From<StoreError>` conversion already
in place.

### Integration test → Layer 3 (RED, Docker)

```rust
// crates/visualizer_backend/src/lib.rs, #[cfg(test)]
#[tokio::test]
async fn position_events_reads_back_what_the_writer_logged() { ... }
#[tokio::test]
async fn current_levels_reads_back_what_log_decision_wrote() { ... }
#[tokio::test]
async fn current_analysis_reads_back_the_latest_persisted_value() { ... }
```

### Unit tests (RED)

- A database error degrades to `VisualizerError`, not a panic — same
  property `a_database_error_degrades_to_a_typed_error_not_a_panic`
  already covers for `historical`; add the equivalent for all three new
  methods rather than assuming the shared `?` makes it redundant.

## Layer 3: `visualizer_server` — routes + DTOs

### Interface

```rust
// crates/visualizer_server/src/dto.rs
pub struct PositionStateEventDto { /* mirrors execution::PositionStateEvent,
    one variant per NotPlaced/Opened/Closed/StoppedOut/... */ }
pub struct LevelDto { pub price: Decimal, pub kind: Option<String> }
pub struct AnalysisDto { pub kind: String, pub value_base64: String, pub computed_at: u64 }

// crates/visualizer_server/src/routes.rs
pub async fn pair_events_handler(
    State(state): State<Arc<AppState>>, Query(params): Query<HistoryParams>,
) -> Response { ... }
pub async fn pair_levels_handler(
    State(state): State<Arc<AppState>>, Query(params): Query<PairParam>,
) -> Response { ... }
pub async fn pair_analysis_handler(
    State(state): State<Arc<AppState>>, Query(params): Query<AnalysisParams>,
) -> Response { ... }
```

Routes added in `lib.rs`, alongside the existing `/api/pairs` and
`/api/pair_history`:

```
GET /api/pair_events?pair=&from=&to=   -> Vec<PositionStateEventDto>
GET /api/pair_levels?pair=             -> Vec<LevelDto>
GET /api/pair_analysis?pair=&kind=     -> AnalysisDto | 404 (no record yet)
```

`/api/pair_analysis` is the one route in this layer that returns 404
rather than an empty/default body on a genuine miss: `[]` reads as
"nothing configured" for the other two, but there is no empty `AnalysisDto`
to fall back to for one specific `kind` that has never been persisted —
404 is the honest answer, distinct from the 503
`service_unavailable` already reserved for a real query failure.

### Integration test → Layer 4 (RED, Docker)

```rust
// crates/visualizer_server/tests/passive.rs
#[tokio::test]
async fn pair_events_returns_real_outcomes_in_arrival_order() {
    // Seed event_log for a pair (Opened, then StoppedOut). GET
    // /api/pair_events must return both, in that order, numbered by
    // arrival -- not by a fabricated timestamp (design §3).
}
#[tokio::test]
async fn pair_levels_returns_the_pairs_current_target_and_stop_loss() {
    // Seed current_levels via a Decision carrying Level::main_with_kind
    // rows. GET /api/pair_levels must return both with the right `kind`
    // strings.
}
#[tokio::test]
async fn pair_analysis_returns_the_latest_persisted_record_base64_encoded() {
    // persist_analysis(pair, "zones", bytes, ts) via the executor role;
    // GET /api/pair_analysis?pair=&kind=zones must return that exact
    // byte content, base64-decoded, and `computed_at == ts`. A second
    // persist_analysis call for the same key must change what this
    // route returns on the next request -- proving current_analysis,
    // not a cached first read.
}
```

### Unit tests (RED)

- Not-ready (schema unapplied) returns empty arrays, HTTP 200, for
  `/api/pair_events` and `/api/pair_levels` — same posture as every
  existing handler in this file. `/api/pair_analysis` not-ready returns
  404, same as the not-yet-persisted case: this route has no
  ready/not-ready distinction to make, since either way there is
  nothing to return yet.
- Cross-pair isolation on all three new routes.
- `/api/pair_levels` for a pair with no decisions yet returns `[]`, not
  404 and not `null`.
- `/api/pair_analysis?kind=` for a kind nobody has persisted (but the
  pair has other kinds) returns 404 for that kind specifically, not the
  other kind's record.

### Constraints / notes

- Decimals stay strings on the wire (`rust_decimal` through JSON), same
  as every existing DTO.
- Neither `/api/pair_events` nor `/api/pair_levels` touches
  `AppState::books()` or the poller — these are plain `state_store`
  reads, same shape as `pairs_handler`'s existing `load_all()` call.
  `/api/pair_analysis` likewise: base64-encoding opaque bytes is the
  only transformation this handler does, no decoding.

## Layer 4: SPA — Event Log panel + overlay lines

### Interface

```
pair.html    + one new panel: "Event Log", a scrolling <ul>/<table>
js/api.js    + events(pair, fromMs, toMs)   -> GET /api/pair_events
             + levels(pair)                  -> GET /api/pair_levels
             + analysis(pair, kind)           -> GET /api/pair_analysis
                (404 -> null, not a thrown error: "not persisted yet"
                is an expected state, not a fetch failure)
js/pair.js   + renders the Event Log panel on load and on the same
               poll cadence as position summary (design §3: no live
               push for this panel)
js/chart.js  + one price line per level: Target/StopLoss get the same
               visual treatment the old sled-era chart.js gave entry/
               SL/TP lines (reference: external/executor/references/
               legacy-visualiser-frontend/static/js/pair.js — layout
               and formatting only; its chart calls were Chart.js and
               are not portable, this branch already uses
               lightweight-charts)
             + decodes AnalysisDto.value_base64 into whatever the
               overlay draws -- THE BYTE FORMAT IS NOT SPECIFIED HERE.
               Design §4a: `current_analysis` is opaque bytes by
               contract, all the way up to this handler. Before writing
               this decoder, confirm with whoever calls
               `persist_analysis` from main/ what `kind` and what byte
               layout it actually sends -- do not guess a schema and
               ship a decoder for one that doesn't match production.
js/format.js — DELETE reconciliationHealthy/reconciliationFlag (design §2)
```

### Integration test → Layer 5 (RED, Docker)

```rust
// crates/visualizer_server/tests/passive.rs — extends the existing
// "every asset the SPA references is actually served" test rather than
// adding a parallel one.
#[tokio::test]
async fn pair_html_references_no_dead_reconciliation_helpers() {
    // Grep-equivalent: the served pair.html + its <script src> files
    // must not contain "reconciliationHealthy" after this layer lands.
}
```

### Unit tests (RED)

Rust-side, per this project's no-JS-runner convention (matches the
SPA-port plan's own reasoning):

- `/` and `/pair.html` still 200 with the new panel markup present
  (assert the Event Log panel's container id is in the served HTML).

### Constraints / notes

- No CDN, vendored only — same rule the SPA-port plan already set for
  `lightweight-charts.standalone.production.js`.
- The Event Log panel has no live tail (design §3) — do not wire it to
  `/ws`; poll `/api/pair_events` on the same interval `pair.js` already
  uses for position summary / freshness.
- The analysis overlay's `kind` string and byte layout are a main/
  producer contract, confirmed against real production code before the
  decoder in `chart.js` is written — not invented in this plan (design §4a).

## Layer 5: verification

- [ ] `docker compose run --rm test` green
- [ ] `docker compose up executor visualizer`; open a pair with trading
      history — Event Log panel shows real outcomes, chart shows SL/TP
      lines matching that pair's actual levels
- [ ] The analysis overlay renders against a real `persist_analysis`
      record from main/, not a hand-crafted test fixture — confirms the
      byte-format assumption made when `chart.js`'s decoder was written
      actually matches what gets persisted in production
- [ ] Stop the executor — Event Log, levels and analysis panels keep
      showing last-read data (or empty/absent, if never populated)
      rather than erroring; freshness on the Overview page is the only
      thing that visibly degrades
- [ ] `grep -r reconciliationHealthy crates/visualizer_server/static`
      returns nothing
