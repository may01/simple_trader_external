# Current-Indicator Panel (visualiser) Implementation Plan

> **Status 2026-09-21: done.** All layers green in Docker. Operator reported the panel verified on live `LINKUSDT` data (main/'s real `live` service, `binance_candles`). `indicator-panel` merged into `layer-implementation` (`ff2938d`) and pushed.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan layer-by-layer. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** A new **Indicators** panel on the visualiser's pair page listing every non-expired `indicators` row for that pair, as of now (Live) or as of the loaded window's end (History).

**Spec:** [`external/executor/specs/2026-09-20-indicator-visualisation-design.md`](../specs/2026-09-20-indicator-visualisation-design.md) (revised 2026-09-21, panel-only).

**Architecture:** One vertical slice through layers that already exist, copying the `pair_signals` slice exactly: `PgStateReader` query (L5) → `VisualizerBackend` pass-through (L8) → `visualizer_server` route + DTO → SPA panel. No executor-process change, no wire/table change, no `main/` change.

**Tech stack:** Rust (`sqlx`/Postgres, `axum`, `serde`), vanilla JS SPA (`static/js/{api,pair}.js`, `static/pair.html`). Workspace: `trade_executor/.worktrees/layer-implementation`.

**Note on layer taxonomy:** `layer-first-planning`'s layer table is `main/`'s pipeline; like [2026-09-20-level-broadcast-plan.md](2026-09-20-level-broadcast-plan.md), this plan applies that skill's *principles* (Docker first, interface before code, RED integration test at each boundary, no layer started before the previous is green in Docker) over `trade_executor`'s real layers.

---

## Global Constraints

- **Branch:** cut `indicator-panel` from `layer-implementation` inside the `layer-implementation` worktree before the first change; merge back when Layer 4's manual check passes. One commit per layer, after that layer is green in Docker. Never commit without explicit user confirmation.
- **No implementation code in this plan** — signatures and test descriptions only.
- **Read-only role.** `PgStateReader` connects as `dashboard` (SELECT-only via `docker/initdb.d/00-roles.sql`'s default privileges). The new query must work under that role — the Layer 1 integration test runs as `dashboard`, not `executor`.
- **No migration.** `(pair, name, received_at DESC)` already exists (0007) and serves `DISTINCT ON (name) … ORDER BY name, received_at DESC` for one `pair`. `SCHEMA_VERSION` stays 7.
- **`current_indicator` untouched** — not called, not changed, not deleted (spec §4).
- **Error conventions copied, not invented:** decode failure → `StoreError::Decode` (surfaced, never skipped); not-ready → `200 []`; query failure → `service_unavailable(...)`; empty is `[]`, never `null`; `Decimal` fields serialise as strings like every existing DTO.
- **Seeding in tests uses raw `INSERT INTO indicators …`**, not `record_indicator` — `record_indicator` stamps `received_at = now_ms()`, and the `as_of`/expiry cases need controlled timestamps. `pg_store.rs` already does this (lines ~1630/1646/1789).

---

## Docker Entry Points

From `trade_executor/.worktrees/layer-implementation`:

```bash
# Every layer's gate. --build is mandatory: without it compose reuses a stale
# test image and runs the previous binary (see the level-broadcast plan).
docker compose run --build --rm test

# Layer 4 manual check (stack up, visualiser rebuilt from the branch)
docker compose up -d --build visualizer
curl -s 'http://127.0.0.1:8090/api/current_indicators?pair=BTCUSDT'
# then open http://127.0.0.1:8090/pair.html?pair=BTCUSDT
```

DB-backed tests cannot run on the host (`TEST_DATABASE_URL must be set`); host `cargo test` is an inner loop for pure tests only.

- [x] **Step 0.1** Create branch `indicator-panel` from `layer-implementation`. *(Carries one pre-existing uncommitted change, `docker-compose.yml`'s `trader_mq` network — excluded from this plan's commits.)*
- [x] **Step 0.2** Baseline: `docker compose run --build --rm test` green on the branch before any change. Record the per-crate pass counts (for "no regressions" comparison later).
- [x] **Step 0.3** Confirm the stack's `dashboard` role can read the table: `SELECT has_table_privilege('dashboard','indicators','SELECT');` → `t`. If `f`, stop — the default-privileges assumption is wrong and the plan needs a grant migration.

---

## Layer 1: Read (L5, `state_store::PgStateReader`)

### Interface

```rust
// crates/state_store/src/pg.rs, impl PgStateReader, beside read_signal_log
pub async fn read_current_indicators(&self, pair: Pair, as_of: Ts)
    -> Result<Vec<(Ts, IndicatorReading)>, StoreError>;
```
The `Ts` in each tuple is the row's `received_at`. Order: by `name` ascending.

### Integration test → Layer 2 (RED in Docker)

In `crates/visualizer_backend/src/lib.rs` tests, beside `signals_reads_back_what_the_writer_logged`:
- [x] `current_indicators_reads_back_what_was_stored` — raw-INSERT two names for `BTCUSDT` with future `expires_at`; `backend.current_indicators(pair, as_of)` returns both, names ascending, values/kind intact. RED because neither the backend method nor the reader method exists (compile failure is the expected RED).

### Unit tests (RED) — `crates/state_store/tests/pg_store.rs`, all as `dashboard`

- [x] `read_current_indicators_returns_the_newest_row_per_name` — three rows for one name, different `received_at`; only the newest comes back.
- [x] `read_current_indicators_returns_exactly_one_row_per_name` — nine names × several rows each → nine results.
- [x] `read_current_indicators_excludes_expired_rows_but_leaves_them_in_the_table` — expired row absent from result; `SELECT count(*)` still sees it.
- [x] `read_current_indicators_falls_back_to_an_older_live_row_when_the_newest_has_expired` — only possible if the newer row has a *shorter* TTL; newest-non-expired wins, not newest-overall. (Pins the `WHERE` before `DISTINCT ON` semantics.)
- [x] `read_current_indicators_honours_a_past_as_of` — a row received before `as_of` whose `expires_at` is after `as_of` (but before now) is included.
- [x] `read_current_indicators_excludes_rows_received_after_as_of` — a row received after a past `as_of` is excluded, even though it is live now (see constraint below).
- [x] `read_current_indicators_excludes_other_pairs`.
- [x] `read_current_indicators_decodes_support_with_volume` — `kind='support'`, `volume=3.25`.
- [x] `read_current_indicators_on_an_empty_table_is_an_empty_vec_not_an_error`.
- [x] `read_current_indicators_expires_at_equal_to_as_of_is_excluded` — boundary: `expires_at > as_of`, strictly.

### Constraints / notes

- **`as_of` must also bound `received_at`.** The spec's query (`WHERE pair = $1 AND expires_at > $2`) would, for a past `as_of`, return rows *received after* `as_of` — readings that did not exist yet at the moment being viewed. Add `AND received_at <= $2`. This corrects spec §4; update the spec's SQL in Layer 5.
- Tie-break `ORDER BY name, received_at DESC, seq DESC` — two readings in the same millisecond must resolve deterministically.
- Corrupt row (unknown `kind`) → `Err(StoreError::Decode)`. Can't be produced through the CHECK constraint, so the decode path is covered by reusing the existing kind-mapping helper that `current_indicator` uses rather than a second one — no separate test needed if the helper is shared; if a new mapping is written, it needs its own unit test.

- [x] **Gate:** `docker compose run --build --rm test` — all Layer 1 tests green, baseline counts otherwise unchanged. Commit: `feat(state_store): read_current_indicators for the visualiser panel`. *(Green 2026-09-21; commit pending user confirmation.)*

---

## Layer 2: Backend (L8, `visualizer_backend`)

### Interface

```rust
// crates/visualizer_backend/src/lib.rs, impl VisualizerBackend, beside signals()
pub async fn current_indicators(&self, pair: Pair, as_of: Ts)
    -> Result<Vec<(Ts, IndicatorReading)>, VisualizerError>;
```
Thin pass-through to `self.state.read_current_indicators` — no filtering, reordering or folding.

### Integration test → Layer 3 (RED in Docker)

In `crates/visualizer_server/tests/passive.rs`, using the existing `server_only`/`TestApp::get` helpers:
- [x] `current_indicators_endpoint_serves_what_is_stored` — raw-INSERT rows, `GET /api/current_indicators?pair=BTCUSDT&as_of=…`, deserialise the body, assert names/values/`kind`/`volume`/`received_at`/`expires_at`. RED: route not registered (404).

### Unit tests (RED)

- [x] Layer 1's integration test (`current_indicators_reads_back_what_was_stored`) now goes GREEN.
- [x] `current_indicators_on_a_pair_with_no_rows_is_an_empty_vec_not_an_error`.
- [x] `current_indicators_degrades_to_a_typed_error_not_a_panic` — dead pool, same construction `signals_degrades_to_a_typed_error_not_a_panic` uses.

- [x] **Gate:** Docker green. Commit: `feat(visualizer_backend): current_indicators pass-through`. *(Green 2026-09-21; commit pending user confirmation.)*

---

## Layer 3: HTTP (`visualizer_server`)

### Interface

```rust
// src/routes.rs
#[derive(Deserialize)]
pub struct CurrentIndicatorsParams { pub pair: String, pub as_of: Option<u64> }

pub async fn current_indicators_handler(
    State(state): State<Arc<AppState>>,
    Query(params): Query<CurrentIndicatorsParams>,
) -> Response;

// src/dto.rs
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CurrentIndicatorDto {
    pub name: String,
    pub value: Decimal,
    pub kind: String,            // "support" | "resistance" | "none"
    pub volume: Option<Decimal>,
    pub received_at: u64,
    pub expires_at: u64,
    pub age_ms: u64,
    pub expires_in_ms: u64,
}

// src/lib.rs router, beside /api/pair_signals
.route("/api/current_indicators", get(routes::current_indicators_handler))
```

### Integration test → Layer 4 (RED in Docker)

The SPA has no automated harness, so the Layer 3 → 4 boundary is pinned by the **response contract** instead:
- [x] `current_indicators_response_matches_the_panel_contract` (passive.rs) — asserts the exact JSON key set the panel reads (`name`, `value`, `kind`, `volume`, `age_ms`, `expires_in_ms`), `value` a string, `volume` `null` for `kind: none`. Any rename breaks this test before it breaks the page.

### Unit tests (RED) — passive.rs

- [x] `current_indicators_returns_an_empty_array_while_not_ready` — unmigrated schema (existing `the_server_initializes_without_crashing_when_the_schema_has_not_been_migrated_yet` setup) → `200 []`.
- [x] `current_indicators_defaults_as_of_to_now` — one live row, one expired row, no `as_of` → only the live one.
- [x] `current_indicators_honours_an_explicit_as_of` — past `as_of` returns what was current then.
- [x] `current_indicators_computes_age_and_expiry_against_as_of` — fixed `as_of`, exact `age_ms`/`expires_in_ms`.
- [x] `current_indicators_is_sorted_by_name`.
- [x] `current_indicators_rejects_a_missing_pair` — `400` via axum's `Query` rejection, not a `500`.
- [x] Existing `error_responses_never_leak_driver_error_text` still green — the new handler routes failures through `service_unavailable`.

### Constraints / notes

- `age_ms`/`expires_in_ms` from the **same** `as_of` the query used (resolve the default once, pass it to both). `saturating_sub` — never underflow a `u64`.
- `kind` string mapping belongs in `dto.rs` next to the existing `*_str` helpers.

- [x] **Gate:** Docker green. Commit: `feat(visualizer_server): GET /api/current_indicators`. *(Green 2026-09-21; commit pending user confirmation.)*

---

## Layer 4: SPA panel

### Interface

```js
// static/js/api.js, beside pairSignals
/** GET /api/current_indicators?pair=&as_of= -> Vec<CurrentIndicatorDto> */
async currentIndicators(pair, asOfMs /* undefined in Live */) { ... }

// static/js/pair.js
function renderIndicatorsPanel(rows) { ... }       // pure: rows -> DOM
async function refreshIndicators(asOfMs) { ... }   // fetch + render, keeps last rows on failure
```
```html
<!-- static/pair.html, directly after the chart panel -->
<div class="panel">
  <h2>Indicators</h2>
  <table>… <tbody id="indicators-body">…</tbody></table>
</div>
```

### Integration check (manual, stack running)

- [x] `docker compose up -d --build visualizer`; `curl …/api/current_indicators?pair=BTCUSDT` returns every seeded row. *(2026-09-21: synthetic `check_`-prefixed rows seeded by SQL, not a live `main/` — executor and `main/` `live` are trading processes and were not started.)*
- [x] Panel shows the nine rows: name, value, kind, age, expires in.

### Behaviour checks (manual)

- [x] Empty state reads exactly "No live indicators — `main/` may not be publishing." (test by querying a pair with no rows, or before `main/` starts).
- [x] Row with `expires_in_ms < 30000` renders muted.
- [x] Rows go muted in their last 30 s, then disappear at `expires_at`. *(Verified with short-TTL synthetic rows, not by stopping a live `main/`.)*
- [x] History mode: load a window ending in the past → panel shows what was current at `to`. *(Operator-verified 2026-09-21. Reported as "indicator-panel verified"; the individual steps were not itemised. Headless screenshots can't drive the date pickers; `as_of` semantics are also covered by L5 + route tests.)*
- [x] Kill the visualiser mid-poll → last rows stay, no JS error in console. *(Operator-verified 2026-09-21, same caveat as above. Also: "existing banner appears" was wrong — polled panels degrade silently; spec §7 corrected.)*

### Constraints / notes

- **Refresh on the existing `startStatusPolling` tick**, not a new `setInterval`. `as_of` = `undefined` in Live, `tradeActivityRange.to` in History — the same `mode === "live" ? … : tradeActivityRange.to` switch the tick already uses for `refreshTradeActivity`. Also call `refreshIndicators` once from `loadHistoryRange`. This refreshes History mode on every tick with a fixed `as_of` (idempotent) rather than "once per window load" as spec §7 says; it follows the existing panels' precedent. Update spec §7 to match.
- Render `value` string verbatim; format `age_ms`/`expires_in_ms` via `format.js` if it has a duration helper, else a local `Xm Ys` formatter.
- `kind` `support`/`resistance` → append `(vol N)`; `none` → plain.

- [x] **Gate:** Docker suite still green (no Rust change in this layer, but run it — the SPA ships in the `visualizer` image). Commit: `feat(spa): current indicators panel`. *(Green 2026-09-21; committed `12ab1af`.)*

---

## Layer 5: Docs

- [x] Spec: apply the two corrections found while planning — §4 SQL gains `AND received_at <= as_of`; §7 History refresh cadence follows `startStatusPolling`.
- [x] `specs/layers/L5-state-store.md`: `read_current_indicators` in the interface block + testing paragraph.
- [x] `specs/layers/L8-interfaces.md`: `current_indicators` backend method + `GET /api/current_indicators` route.
- [x] E2E spec §6a: assertion 5 → covered at the row level by this panel; assertion 2 unchanged (cache, unit-test-only).
- [x] Tick this plan's boxes.

Docs live in `external/`, never the code repo.

---

## Self-Review Notes

- **Spec coverage:** §4 → Layer 1; §5 → Layer 2; §6 → Layer 3; §7 → Layer 4; §8 tests → distributed per layer; §9 acceptance → Layer 4 manual checks + Layer 5.
- **Spec corrections found while planning (both flagged in-line and scheduled in Layer 5):** (1) the spec's query leaks future rows for a past `as_of` — missing `received_at <= as_of`; (2) History refresh cadence aligned to the existing poll pattern.
- **Assumptions to verify, not trust:** `dashboard` can SELECT `indicators` (Step 0.3); `PgStateReader`'s kind decode can share `current_indicator`'s helper (Layer 1 note).
