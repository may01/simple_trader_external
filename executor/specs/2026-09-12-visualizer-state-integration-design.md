# Visualizer × state_store cache integration — design

> **Deferred 2026-09-13.** §2 (`last_reconciliation`), §3 (Event Log
> panel, `event_log`), §4 (entry/SL/TP overlay lines, `current_levels`)
> and §4a (analysis overlay, `current_analysis`) are all cut from this
> pass, per direct instruction: none of that data is properly
> implemented on the backend yet and none of it should be visualized
> before it is. Concretely: `current_analysis`/`persist_analysis` have
> no producer anywhere in main/ (the 2026-09-12 state-store design's own
> "Out of scope" section says so — "no call sites exist yet on any
> branch"), and `event_log`/`current_levels` were only reasoned about,
> never verified end-to-end against a real running executor. §1 (the
> `PgStateReader` read methods) and §5 (rebase) are consequently also
> moot — §1 had nothing left to add once 2/3/4/4a are gone, and §5 was
> only motivated by needing those methods. **Nothing in this document
> is planned work right now.** Kept below as the record of what was
> considered and why it was rejected, for whenever the backend
> producers above actually exist. Do not resurrect piecemeal without
> re-checking that precondition.

Part of [architecture index](2026-09-04-architecture-design.md). Extends
[executor visualiser design](2026-09-07-executor-visualiser-design.md) and
[postgres market-data store + passive dashboard](2026-09-09-postgres-market-data-store-design.md).
Follows on from
[2026-09-12-state-store-expansion-postgres-design.md](2026-09-12-state-store-expansion-postgres-design.md),
whose caches (`event_log`, `current_levels`, `current_command`,
`analysis_current`/`analysis_log`) landed on `layer-implementation` at
commit `998bb98` — after the dashboard SPA port
([2026-09-11-dashboard-spa-port-plan.md](../plans/2026-09-11-dashboard-spa-port-plan.md))
had already branched and could not use them yet.

## Purpose

Two branches carry the passive dashboard forward independently and now
need to converge:

- **`postgres-live-binance`** (base `6ec8ead`) — the actual SPA port.
  Real `pair.html`/`pair.js`/`chart.js`/`overview.js`, a vendored
  `lightweight-charts.standalone.production.js`, `/api/pairs` and
  `/api/pair_history`, and a continuously-folded live order book
  (`books.rs`) that fixes a drift bug the naive per-request
  `order_book_view` fold had. Working tree only — 12 files uncommitted,
  nothing committed to the branch yet.
- **`layer-implementation`** (commit `998bb98`) — the state_store cache
  rebuild. `StateStoreImpl` (the executor's writer) now implements
  `read_event_log`, `current_levels`, `current_command`,
  `persist_analysis`/`current_analysis`/`read_analysis_log`. None of
  this reached `PgStateReader` (the dashboard's read-only type) or
  `postgres-live-binance`, which still only has `load_all` and
  `read_decision_log` to work with.

This document is the design for closing that gap: what `PgStateReader`
needs, which of the four new caches actually get a panel, and which
don't.

## What this replaces

[2026-09-11-dashboard-spa-port-plan.md](../plans/2026-09-11-dashboard-spa-port-plan.md)'s
scope-reduction table dropped the Event Log panel to "repoint to
`read_decision_log`, retitle it" because `event_log` didn't exist on
Postgres yet at the time it was written. The current working tree shows
that repointing was never actually done either — `pair.html` has no
Event Log panel at all, `PairHistoryDto` has no `decisions` field, and
none of `pair.js`/`api.js`/`overview.js` reference decisions or events.
That compromise is now moot: `read_event_log` exists and returns the
real thing (`PositionStateEvent` outcomes — Opened/Closed/StoppedOut/
etc.), not `decision_log`'s inbound-intent record. Build the panel
against `event_log` directly; do not resurrect the decision_log
workaround first.

## Decisions

### 1. `PgStateReader` gains three read methods, not eight

`StateStore`'s full trait has 8 new async methods as of `998bb98`
(`log_event`/`read_event_log`, `last_reconciliation`, `current_levels`/
`current_command`, `persist_analysis`/`current_analysis`/
`read_analysis_log`). `PgStateReader` is a bare struct, not a
`StateStore` impl — it exposes only the reads a dashboard can actually
use, per the same reasoning
[2026-09-09's design](2026-09-09-postgres-market-data-store-design.md#two-types-not-one-type-in-two-modes)
already gave for keeping `MarketDataFeed` off the reader type: a method
with no real consumer here would compile against empty/misleading data
and prove nothing was actually wired.

Add:
- `read_event_log(pair, from, to) -> Result<EventLogStream, StoreError>`
  — feeds the new Event Log panel (§3).
- `current_levels(pair) -> Result<Option<(Vec<Level>, Ts)>, StoreError>`
  — feeds the chart's entry/SL/TP overlay lines (§4).
- `current_analysis(pair, kind) -> Result<Option<(Vec<u8>, Ts)>, StoreError>`
  — feeds a chart analysis overlay (§4a). `current_analysis` is the
  row `persist_analysis`'s own transaction upserts on every call — it
  is by construction the latest `analysis_log` entry, just without a
  second query. A chart overlay wants "what does main/ currently think",
  not a history of what it used to think, so this is the one analysis
  read this dashboard needs.

Do **not** add:
- `current_command` — no panel wants "the last command sent" yet. Adding
  the read method with no route and no consumer repeats exactly the
  mistake `postgres-live-binance`'s own dto.rs doc comment already
  warns against for the walls panel: a field nothing renders is worse
  than an absent one. Revisit if an operator asks for it.
- `read_analysis_log` — the chart's overlay need is fully answered by
  `current_analysis` (see above); a history-of-analysis panel is a
  different, not-yet-requested feature, not a prerequisite for this one.
- `persist_analysis`/`log_event` — write methods. `PgStateReader`
  connects as the `dashboard` Postgres role, `SELECT`-only by grant;
  this crate has no business ever calling a write method, and not
  exposing it means a future mistake can't compile. `persist_analysis`
  never becomes a reader-side concern regardless of which reads get
  added around it.

### 2. `last_reconciliation` cannot reach this process — drop it, not defer it

The 2026-09-07 design's Overview page bullet ("reconciliation health
flag") assumed the dashboard ran inside the executor process, reading
`StateStore::last_reconciliation()`'s in-memory `Mutex` directly. The
2026-09-09 postgres design kept that same in-memory decision
deliberately — "never sled/DB-backed, since it's inherently a
since-last-boot fact" — while also moving the dashboard to a *separate
process*. Those two decisions together mean `last_reconciliation` is
now unreachable from any dashboard code, structurally: `PgStateReader`
has no handle to the executor's `Mutex`, and nothing persists the value
for it to read instead. `postgres-live-binance`'s own working tree
already independently reached this conclusion — `overview.js` has a
comment ("Freshness, not reconciliation health...") explaining the
omission — but left dead code behind: `format.js` still defines
`reconciliationHealthy`/`reconciliationFlag`, ported unchanged from the
sled-era branch, called from nowhere. Delete both functions as part of
this work — an unreachable helper on the wire-data path is the same
"reads as a bug, not an absent feature" problem the SPA-port plan named
for the walls panel, just one layer further from the user.

If reconciliation health is wanted on the dashboard later, it needs its
own persisted signal (e.g. the executor writes a small
`last_reconciliation` row on every `reconcile()` call) — a real change
to L5's design, not something this integration can retrofit.

### 3. Event Log panel: `current_levels`/`current_command` do not answer this, `event_log` does

`GET /api/pair_events?pair=&from=&to=` → `Vec<PositionStateEventDto>`,
each entry one `PositionStateEvent` (`NotPlaced`, `Opened`, `Closed`,
`StoppedOut`, and the two remaining variants) plus its arrival order.
Per the 2026-09-07 spec's own note (never contradicted since):
`read_event_log` discards `received_at` on the read path, matching
`decision_log`'s existing convention — so the panel numbers entries in
arrival order, it does not fabricate a timestamp.

`visualizer_backend` gets a thin wrapper, matching `historical`'s own
shape:

```rust
pub async fn position_events(&self, pair: Pair, from: Ts, to: Ts)
    -> Result<Vec<PositionStateEvent>, VisualizerError>;
```

No live push for this panel — same posture the SPA-port plan already
chose for the position summary: poll on the same cadence as history
reload. There is no broadcast in this process to subscribe to; polling
Postgres is the only transport that exists here.

### 4. Entry/SL/TP overlay lines: `current_levels`, filtered by `LevelKind`

`local_analysis::types::Level { price, source, kind: Option<LevelKind> }`
does not derive `Serialize` (no domain type in this codebase does,
matching `dto.rs`'s own stated convention). Add `LevelDto` to
`visualizer_server::dto`, same `From<&Level>` pattern as
`PositionStateDto`:

```rust
pub struct LevelDto { pub price: Decimal, pub kind: Option<String> }
// kind: "support" | "resistance" | "target" | "stop_loss" | null
```

New route `GET /api/pair_levels?pair=` → `Vec<LevelDto>`, backed by

```rust
pub async fn current_levels(&self, pair: Pair)
    -> Result<Option<(Vec<Level>, Ts)>, VisualizerError>;
```

on `visualizer_backend`. The chart draws one price line per level whose
`kind` is `Target` or `StopLoss`; `Support`/`Resistance` render too
(same overlay, different color) since main/ can send either on any
level and the frontend has no basis to hide one kind the domain model
treats identically. The position's own `entry_price` (already served by
`/api/pairs`' `PairSummaryDto.position`) draws the entry line — `Level`
carries no `Entry` kind, so this is not a `current_levels` row and must
not be modeled as one.

### 4a. Analysis overlay: `current_analysis`, one row, no history

New route `GET /api/pair_analysis?pair=&kind=` → the raw stored value for
`(pair, kind)`, backed by

```rust
pub async fn current_analysis(&self, pair: Pair, kind: String)
    -> Result<Option<(Vec<u8>, Ts)>, VisualizerError>;
```

`state_store`'s own design is explicit that analysis values are
**opaque bytes it does not parse** — "freshness policy belongs to the
caller" — and that holds all the way to this dashboard: neither
`visualizer_backend` nor `visualizer_server` decodes `value` either.
The route returns it as-is (base64 in the JSON body, since raw bytes
don't fit a JSON string), `computed_at`, and `kind` echoed back.

This pushes a real constraint onto whatever in main/ calls
`persist_analysis`: **the bytes it writes must already be everything
the chart overlay needs to render**, because this dashboard reads
`current_analysis` alone — no `read_analysis_log` call to backfill a
missing field from an earlier record, no second endpoint. What "enough"
means (a price series, a set of zones, a classification label) is a
contract between main/'s analysis producer and the frontend's overlay
renderer; this spec does not fix a schema for it, the same way
`state_store` itself refuses to. That contract needs to be nailed down
wherever the analysis overlay's JS is written (Layer 4 of the
implementation plan), not guessed at here.

`kind` is a free-form `String` (per `current_analysis`'s own signature)
— the route needs it as a query param precisely because the store
supports more than one analysis kind per pair and does not privilege
any one of them.

Only the latest record is fetched — no analysis-history panel, no
timeline scrub. If a past-analysis view is wanted later, that is a new
feature request against `read_analysis_log`, not a gap in this one.

### 5. Rebase before extending

`postgres-live-binance` branched at `6ec8ead`, before `wall-side-typed`
and `book-crossed-safety-check` merged into `layer-implementation`, and
long before `998bb98`. It must rebase (or merge `layer-implementation`
in) before any of the above lands — `current_levels`/`read_event_log`
do not exist on its current base at all. Resolve conflicts in
`visualizer_server`/`visualizer_backend` in favor of keeping
`postgres-live-binance`'s SPA and live-book work; take
`state_store`/`db_schema` changes from `layer-implementation` as-is,
they have no competing edit on this branch.

## Out of scope (this pass)

- `current_command` — no consumer, per §1.
- `read_analysis_log` / any analysis-history view — `current_analysis`
  alone covers the chart's stated need, per §4a.
- Fixing the analysis payload's byte format if it turns out incomplete
  for the chart — that is main/'s producer code, outside this crate's
  boundary, and outside what this integration pass controls.
- Reconstructing the order book *as of* a past instant in History mode
  — `pair_history_handler`'s own comment already documents that the
  live continuously-folded book is served for every window, historical
  or not, and that fixing this needs a seed-replay change to
  `read_range_all` separate from this work.
- Any write path from the dashboard — this remains a `SELECT`-only
  process, unchanged from 2026-09-09's design.

## Testing

DB-backed, `docker compose run --rm test`, schema-per-test via
`test_support::test_db` — same convention as every other Postgres-era
test in this codebase.

- `PgStateReader::read_event_log`/`current_levels`: round-trip against a
  fixture the executor's `StateStoreImpl` writes, read back through the
  `dashboard` role — proves the grant, not just the query.
- `visualizer_backend::position_events`/`current_levels`: same shape as
  the existing `order_book_view` tests — a database error degrades to
  `VisualizerError`, never a panic.
- `visualizer_server`: `/api/pair_events` and `/api/pair_levels` route
  tests, both "not ready yet" (empty, HTTP 200) and cross-pair
  isolation, matching `pair_history_returns_a_reconstructed_book_and_
  bucketed_series`'s existing pattern.
- A grep-style test (or a code-review check) that `reconciliationHealthy`/
  `reconciliationFlag` are gone from `format.js`, not merely uncalled.
