# Indicator Visualisation (current-state panel) — Design Spec

Date: 2026-09-20, revised 2026-09-21
Status: **implemented 2026-09-21** on branch `indicator-panel` (plan [2026-09-21-indicator-panel-plan.md](../plans/2026-09-21-indicator-panel-plan.md)); three corrections below were found while planning/implementing and are applied in place
Target project: `trade_executor` (worktree `layer-implementation`) — L5 read path, L8 `visualizer_backend`, `visualizer_server` route + SPA. No `main/` change.
Extends: [2026-09-19-level-broadcast-design.md](2026-09-19-level-broadcast-design.md) (which delivered the `indicators` table and left it unread)
Related: [2026-09-20-indicator-broadcast-e2e-check-design.md](2026-09-20-indicator-broadcast-e2e-check-design.md) §6a, [layers/L5-state-store.md](layers/L5-state-store.md), [layers/L8-interfaces.md](layers/L8-interfaces.md)

> **Revision 2026-09-21 — scope cut.** The first draft also drew EMA readings as lines on the price chart, backed by a history read (`read_indicator_series`) and a `GET /api/pair_indicators` route. Dropped: this spec now covers **only** a separate panel showing current indicator state. No chart change, no history read, no series route. If lines are wanted later, they are a separate spec.

## 1. Why

`indicator_update` readings have been landing in the `indicators` table since 2026-09-20 (proven end to end), and **nothing reads them**. `state_store::current_indicator` exists, is unit-tested, and has zero callers anywhere in the workspace; no `visualizer_server` route touches the table. Two consequences:

- an operator cannot tell whether `main/` is publishing, what it last said, or whether a reading has gone stale — the failure mode from the e2e spec §3 (silent non-delivery) is invisible from the UI;
- the e2e check's assertion 5 (expiry stops a reading being served) cannot be observed from outside the executor process.

This spec adds the first real consumer: a panel listing every indicator that is non-expired at the moment being viewed.

## 2. Scope

**In:** one new panel on the pair page listing every non-expired indicator for that pair — all kinds, not only EMA — with its value and how long it has left; plus the read, backend method and route that feed it.

**Out:** drawing indicators on any chart; any history/series read of `indicators`; any use of indicators in trading logic (`combined_levels`, signal checks — still a later spec); any `main/` change; any change to the wire format, the table, or the ingest task.

## 3. The data this draws on

`indicators` (migration 0007): `seq, pair, name, value, kind, volume, expires_at, received_at`, append-only, indexed `(pair, name, received_at DESC)`.

What `main/` publishes today: `ema_7`, `ema_14`, `ema_25` at timeframes 15/60/240, wire `name` = `{tf}_{name}` — nine names, all `kind: "none"`, `volume` NULL. Cadence `MQ_INDICATOR_PUBLISH_INTERVAL_SEC` = 30 s, TTL 300 s. So a healthy sender keeps all nine names current continuously, each refreshed every ~30 s; a stopped sender's names drain out of the panel over the following 5 minutes.

`name` is opaque to the executor — the panel displays it verbatim and never parses it.

## 4. Read layer (L5, `PgStateReader`)

One new method on `PgStateReader`, the read-only reader the visualiser already uses (sibling of `read_signal_log`/`read_wall_snapshots`/`read_event_log`, same shape):

```rust
/// Newest non-expired reading per `name` for `pair`, as of `as_of`.
/// Each element's Ts is that row's `received_at`. Empty vec when none.
pub async fn read_current_indicators(&self, pair: Pair, as_of: Ts)
    -> Result<Vec<(Ts, IndicatorReading)>, StoreError>;
```
```sql
SELECT DISTINCT ON (name) name, value, kind, volume, expires_at, received_at
FROM indicators
WHERE pair = $1 AND received_at <= $2 AND expires_at > $2
ORDER BY name, received_at DESC, seq DESC
```

> **Correction (2026-09-21):** the first draft omitted `received_at <= $2`. For a past `as_of` (History mode) that returned readings which arrived *after* the moment being viewed — ones that did not exist yet. Pinned by `read_current_indicators_excludes_rows_received_after_as_of`.

A stored row that fails to decode (unknown `kind`, or a `kind`/`volume` mismatch the CHECK should have made impossible) surfaces as `StoreError::Decode`, same `CorruptRow::Surface` policy as the sibling readers — never skipped silently. Implemented as a strict `decode_indicator_kind` helper in `pg.rs`, deliberately **not** shared with `current_indicator`, whose older inline mapping coerces any unrecognised pair to `None` (recorded in TECH_DEBT.md §4).

**Why not reuse `StateStoreImpl::current_indicator`.** That method's value is its write-through cache, which is warm **only in the process that ingested the reading** — the executor. `visualizer_server` is a separate process with a permanently cold cache, and it needs "every current indicator for this pair", not "this one name I already know" — reusing it would mean listing names first and then N always-missing cache lookups. `current_indicator` stays where it is, for the future in-process analyser that motivated it; this spec neither makes it live nor deletes it.

Consequence, stated plainly: the panel proves the **stored** expiry semantics (a reading stops being listed once `expires_at` passes) — that satisfies the e2e spec's assertion 5 at the row level. The cache is still covered by `state_store`'s unit tests only, and the e2e spec's assertion 2 (cache read-back) remains out of reach from outside the process, by choice.

## 5. Backend (L8, `visualizer_backend`)

One thin pass-through, mirroring `signals()` exactly — no folding, no reordering, errors as `VisualizerError`:

```rust
pub async fn current_indicators(&self, pair: Pair, as_of: Ts)
    -> Result<Vec<(Ts, IndicatorReading)>, VisualizerError>;
```

## 6. HTTP (`visualizer_server`)

**`GET /api/current_indicators?pair=&as_of=`**, following the existing handler conventions: `is_ready()` false → `200` with an empty array (schema not applied yet is not an error); query failure → `service_unavailable(...)`; `Vec<Dto>` JSON, empty array never null.

- `as_of` is optional, defaulting to the server's `now_ms()`. Live mode omits it; History mode passes the loaded window's `to`, so the panel answers "what was current at the moment being viewed", not "what is current now".
- Response, sorted by `name`:
  ```json
  [{"name": "15_ema_7", "value": "12345.75", "kind": "none", "volume": null,
    "received_at": 1789934214085, "expires_at": 1789934514085,
    "age_ms": 30000, "expires_in_ms": 270000}]
  ```
- `age_ms` = `as_of − received_at`, `expires_in_ms` = `expires_at − as_of`, both computed server-side against the same `as_of` the query used, so the client never compares timestamps against a clock it doesn't share with the DB.
- `value`/`volume` serialise as strings, matching the existing `Decimal` DTO fields (confirmed on the running stack: `/api/walls` returns `"price":"80458.95000000"`).

## 7. The panel

New `<div class="panel">` on `pair.html`, placed directly after the chart panel, titled **Indicators**:

| Name | Value | Kind | Age | Expires in |
|---|---|---|---|---|
| `15_ema_7` | 12345.75 | none | 30s | 4m 30s |

- Rows in server order (by name). `kind` shows `support`/`resistance` with their `volume` appended when those ever arrive; today every row is `none`.
- A row whose `expires_in_ms` is below one publish interval (30 s) renders in the existing muted style — the visible symptom of a sender that has stopped refreshing it.
- **Empty state is deliberate copy**, not a blank table: "No live indicators — `main/` may not be publishing." That is exactly what the e2e spec §3 misconfiguration looks like from here, and the reason this panel exists.
- A failed fetch keeps the last rendered rows and degrades **silently**, same as the other polled panels (`refreshTradeActivity`). *(Correction 2026-09-21: the first draft said "shows the existing banner", but none of the polled panels do — the banner is reserved for load/mode errors.)*
- **Live**: refreshed on the existing status-polling interval (`startStatusPolling`, which already drives position summary and freshness) — no second timer, per the repo's stated preference.
- **History**: fetched on window load with `as_of` = the window's `to`, then re-fetched on the same status tick with that fixed `as_of` (idempotent) — the pattern `refreshTradeActivity` already uses. Entering History mode clears the live rows ("Load a range to see the indicators current at its end.") until a range is loaded. *(Correction 2026-09-21: the first draft said "once per window load".)*

## 8. Testing

- **L5** (`pg_store`, DB-backed): newest reading wins per name; expired rows excluded while still present in the table; exactly one row per name; other pairs excluded; `as_of` in the past returns what was current then (a row expired *now* but live at `as_of` is included); `kind: support` with `volume` decodes; empty table → empty vec, not an error.
- **L8**: reads back what a writer wrote; empty vec on no rows; typed error, not a panic, on a dead pool — the same three cases `signals_*` covers.
- **Route**: not-ready → `200 []`; populated → expected JSON shape, sorted by name, with correct `age_ms`/`expires_in_ms`; `as_of` honoured when passed, defaulted when not.
- **SPA**: manual check against the running stack — nine rows with `main/` publishing; after stopping it, rows go muted in their last 30 s and then disappear; empty-state copy shown once all have expired.
- All Rust tests pass under `docker compose run --build --rm test` (DB-backed tests cannot run on the host — `TEST_DATABASE_URL`).

## 9. Acceptance criteria

Verified 2026-09-21 against the running `visualizer` (rebuilt from `indicator-panel`) with synthetic `check_`-prefixed rows seeded into `indicators` by SQL — neither the executor nor `main/`'s `live` service was started, since both are trading processes. Headless-Chrome screenshots taken of each state.

- [x] `GET /api/current_indicators?pair=BTCUSDT` returns every current name, sorted, with correct `age_ms`/`expires_in_ms`, `support (vol 3.25)` for the support row. *(Nine synthetic `{tf}_ema_{n}`-shaped names, not a live `main/` — the real sender path was already proven by the e2e spec §6a.)*
- [x] Panel renders them; a row with < 30 s left renders muted; a row past `expires_at` drops out; empty state reads "No live indicators — `main/` may not be publishing." (checked on a pair with no rows).
- [ ] History mode in the browser — **not exercised interactively** (headless screenshots cannot drive the date pickers). The `as_of` semantics it relies on are covered by the L5 and route tests.
- [ ] "Visualiser killed mid-poll keeps last rows" — **not exercised**; the code path is the same silent-catch as `refreshTradeActivity`.
- [x] Docker test suite green, including the new L5/L8/route tests (`pg_store` 76, `state_store` 9, `visualizer_backend` 25, `passive` 52).
- [x] L5 and L8 layer specs updated; e2e spec §6a updated.
