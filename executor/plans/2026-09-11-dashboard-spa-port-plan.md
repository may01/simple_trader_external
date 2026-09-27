# Dashboard SPA port — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the passive Postgres dashboard the real SPA. Today
`visualizer_server/static/` holds a single placeholder `index.html`; the
working SPA lives on the sled-era `executor-visualiser` branch and is
written against a transport that no longer exists.

**Supersedes nothing.** This finishes work
[2026-09-09-postgres-market-data-store-plan.md](2026-09-09-postgres-market-data-store-plan.md)
Task 11 Step 4 explicitly left standing: "panels, `BookTracker`
reconstruction and frontend choice still stand" — that plan replaced the
transport and deferred the frontend, leaving the placeholder behind.

**Branch:** `postgres-live-binance` (already off `layer-implementation`).

## Central decision: shape server-side, not in `api.js`

The obvious port is a JavaScript shim — have `api.js` bucket the flat
tagged event list into `{candles, trades, book, events}` and fold
`BookUpdate`s onto a `BookSnapshot` client-side. Rejected:

- **It would be untestable.** This workspace has no JS test runner, no
  `package.json`, no node toolchain. Every other invariant in this
  project is covered by `cargo test` inside Docker. Book reconstruction
  is exactly the kind of fold that breaks silently — a dropped delta
  renders as a plausible-but-wrong book, with nothing failing.
- **The logic already exists in Rust, tested.**
  `visualizer_backend::order_book_view` folds `BookSnapshot` +
  `BookUpdate` through `market_data::BookTracker`, and explicitly drops
  a tracker it cannot seed rather than guessing at a partial
  reconstruction.

So: one new REST endpoint shapes the response server-side, and `api.js`
stays the thin wrapper it already is. The SPA's own consumption code
(`pair.js`, `chart.js` — 1170 lines) is then reused unmodified.

## Scope reduction — three panels lose their data source

The new transport carries `MarketDataEvent` only. Three panels on the
old pair page have no equivalent source and must be removed rather than
left rendering "Loading…" forever:

| Panel | Old source | On this branch |
|---|---|---|
| Walls overlay | `walls` + `LiveMessage::Walls` | **Gone.** No wall table in the schema. Remove the overlay, its legend entries, and the depth-chart wall lines. |
| Event Log | `event_log` via `HistoryResponseDto.events` | **Repointed.** `PgStateReader` exposes `read_decision_log`, not `read_event_log`. Feed the panel from the decision log and retitle it. |
| Position summary | `LiveMessage::Snapshot` | **Poll-only.** `PgStateReader::load_all` gives position state over REST; there is no live push for it. Refresh on the same cadence as freshness. |

Removing is the point: a panel wired to nothing is worse than an absent
one, because it reads as a bug in the executor rather than an absent
feature.

## Docker Entry Points

These commands are ground truth. Implementation must make them work.

```bash
# Full suite, Postgres comes up as a dependency
docker compose run --rm test

# The stack: executor writes, dashboard reads
docker compose up executor visualizer
# dashboard at http://127.0.0.1:8090/  -> overview table, not a placeholder

# Dashboard alone, executor stopped -- must still render
docker compose up postgres visualizer
```

Verified:
- [ ] `docker compose run --rm test` green, including the new route tests
- [ ] `docker compose up executor visualizer` serves the real SPA at `/`
- [ ] `docker compose up postgres visualizer` renders with the executor down

No compose or Dockerfile change is expected: the `visualizer` target
already `COPY`s `crates/visualizer_server/static` and
`VISUALIZER_STATIC_DIR` already points at it. Adding files to that
directory is sufficient. Confirm, do not assume.

---

## Layer 1: `visualizer_server` — shaped history endpoint (L8b)

### Interface

```rust
// crates/visualizer_server/src/dto.rs

/// The old `HistoryResponseDto`, minus `walls`. Pre-bucketed and
/// book-reconstructed so the browser does no folding of its own.
pub struct PairHistoryDto {
    pub candles: Vec<CandleUpdate>,
    pub trades: Vec<TradeTick>,
    pub book: Option<OrderBookSnapshot>,
    pub decisions: Vec<DecisionRecord>,
}

pub struct PairSummaryDto {
    pub pair: String,
    pub position: PositionState,
    pub freshness: Freshness,
}

// crates/visualizer_server/src/routes.rs
pub async fn pair_history_handler(..., Query<HistoryParams>) -> Response { ... }
pub async fn pairs_handler(...) -> Response { ... }
```

Routes added in `lib.rs`:

```
GET /api/pairs                                  -> Vec<PairSummaryDto>
GET /api/pair_history?pair=&from=&to=           -> PairHistoryDto
```

`/api/history`, `/api/freshness`, `/api/status`, `/ws` are unchanged —
the raw event feed stays, this is additive.

### Integration test → Layer 2 (RED, Docker)

Written before the handler exists:

```rust
// Seed a schema-per-test DB (test_support::test_db) with a BookSnapshot,
// two BookUpdates that move the best bid, some trades and a candle.
// GET /api/pair_history must return: trades and candles bucketed into
// their own arrays, and `book` equal to the snapshot with BOTH updates
// already applied -- proving the fold happened server-side and the
// browser is handed a finished book.
#[tokio::test]
async fn pair_history_returns_a_reconstructed_book_and_bucketed_series() { ... }
```

### Unit tests (RED)

- Empty range returns empty arrays and `book: None`, HTTP 200 — not an
  error, not `null` for the arrays (the SPA indexes them directly).
- A range whose first book event is a `BookUpdate` with no preceding
  `BookSnapshot` returns `book: None` — matching `order_book_view`'s
  documented refusal to partially reconstruct.
- Cross-pair isolation: seeding two pairs, `?pair=A` never returns B's
  trades.
- Not-ready (schema unapplied) returns empty arrays, consistent with
  `history_handler`'s existing readiness behavior.
- `/api/pairs` with the executor down still returns each configured pair
  with its last known position and `Freshness::Stale`/`Offline`.

### Constraints / notes

- Decimals stay strings on the wire, as every existing DTO does —
  `rust_decimal` through JSON, never floats.
- The dashboard role is `SELECT`-only; nothing here may issue DDL or
  writes, including implicit sequence bumps.

---

## Layer 2: SPA — static tree (L8c)

### Interface

Files copied from `executor-visualiser`'s
`crates/visualizer_server/static/`, then edited:

```
index.html          overview table              (unchanged)
pair.html           panels                      (walls panel removed)
css/style.css                                   (unchanged)
js/format.js                                    (unchanged)
js/chart.js         charts                      (wall overlay removed)
js/pair.js          page controller             (wall + live-position paths removed)
js/overview.js      overview controller         (-> /api/pairs)
js/api.js           transport wrapper           (rewritten: 4 endpoints)
vendor/…            lightweight-charts, chart.js (unchanged, vendored)
```

`api.js` is the only file whose contract changes:

```js
const API = {
  async pairs() { ... },                       // GET /api/pairs
  async history(pair, fromMs, toMs) { ... },   // GET /api/pair_history
  async freshness(pair) { ... },               // GET /api/freshness
  wsUrl(pair) { ... },                         // /ws?pair=
};
```

### Integration test → Layer 1 (RED, Docker)

```rust
// Served-asset test, in visualizer_server's existing harness: GET /,
// /pair.html and every asset they reference must return 200 with a
// sane content-type -- a 404 on one <script src> is invisible from the
// Rust side today and fatal in the browser.
#[tokio::test]
async fn every_asset_the_spa_references_is_actually_served() { ... }
```

### Unit tests (RED)

Rust-side, since there is no JS runner:

- `/` serves the overview, not the placeholder — assert the placeholder's
  marker string is absent, so this test fails loudly if the old file
  survives the copy.
- An unmatched path falls back to the SPA rather than 404ing.

### Constraints / notes

- The live WS demux in `pair.js` switches on `msg.type`; the new feed is
  externally tagged (`{"Trade":{…}}`) with no `type` field. `api.js`
  normalizes each frame to the old internally-tagged shape before
  handing it over — that is the one place the two transports are
  reconciled on the client, and it is a pure rename, no folding.
- `Resync`, `Snapshot`, `Walls` and `Position` live messages do not
  exist on the new feed. Their `case` arms go; do not leave them
  unreachable.
- Vendored chart libraries are copied as-is. No CDN: the dashboard must
  render with no outbound network.

---

## Layer 3: verification

- [ ] `docker compose run --rm test` green
- [ ] `docker compose up executor visualizer`, then load `/` — overview
      lists BTCUSDT with a live position and fresh lag
- [ ] Open the pair page: candles, trades and depth all render from real
      Binance data
- [ ] Stop the executor; the page stays up and freshness degrades rather
      than the page erroring
