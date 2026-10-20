# Candle-bound overlay on the visualiser chart — Design Spec

Date: 2026-10-16
Status: **implemented 2026-10-17 on branch `cb-overlay-visualiser` (`7d0b06f`, merged into `layer-implementation` `57d8561`; in `release_001`) — rendering verified headless (Chrome DevTools, seeded data, Live + History, every toggle); the user-gated check in the real Docker stack is still open**
Target project: `trade_executor` (worktree `layer-implementation`) — L5 read path, L8 `visualizer_backend`, `visualizer_server` route + SPA. No `main/` change.
Extends: [2026-09-20-indicator-visualisation-design.md](2026-09-20-indicator-visualisation-design.md), whose 2026-09-21 revision cut "lines on the chart" and said: "If lines are wanted later, they are a separate spec." This is that spec.
Related: [2026-09-19-level-broadcast-design.md](2026-09-19-level-broadcast-design.md) (wire format and `indicators` table), [2026-09-16-trade-visualization-design.md](2026-09-16-trade-visualization-design.md) (chart marker conventions), main/ phase 18 `external/docs/superpowers/specs/2026-10-05-cb-markers-main-flow-design.md` (what is broadcast and what the markers mean), [layers/L5-state-store.md](layers/L5-state-store.md), [layers/L8-interfaces.md](layers/L8-interfaces.md).

## 1. Why

main/'s phase 18 (`cb-markers-main-flow`, Task 10) broadcasts the candle-bound (CB) levels, in-zone markers and marker filters over MQ as ordinary `indicator_update` messages. The executor already stores every one of them in `indicators` and lists their current values in the Indicators panel. Nothing draws them. An operator watching the executor's pair page cannot see where the zones sit against price, when a minute was in zone, or which filters would have vetoed it — the same picture main/'s full view (`frontend/data_viewer.py`, Task 11) gives over a prepared dataset, but live, from the wire.

This spec adds that picture to the executor's chart: zone lines stepping over time, one dot per in-zone minute, and the stored-only filters as toggles that mask the dots.

## 2. Scope

**In:**
- a history read of `indicators` over a time window (seeded with the state in force at the window start, heartbeat duplicates dropped);
- a backend pass-through and a `GET /api/pair_indicators` route;
- SPA: a value store with hold-until-next-row-or-expiry semantics, per-minute sampling, a filter mask, and chart series for zone lines, in-zone markers and the optional bound/forming-bound/extdone families;
- toggle controls above the chart: families, filters, timeframes;
- Live mode (incremental fetch on the existing poll tick) and History mode (one fetch per loaded range).

**Out:** any WebSocket change; any change to the Indicators panel (it keeps listing all 51 names verbatim — decided 2026-10-16); any `main/`, wire, table or migration change; use of CB values in trading logic; toggle persistence; `cb_f_mcx_*` (not broadcast); `cbx_*`, bands, `cbnc_tgt_*`, `cbnc_zone_*`, `cbnc_inzone_*`, `extdone_*_lvl` (not broadcast).

## 3. The data this draws on

`indicators` (migration 0007): `seq, pair, name, value, kind, volume, expires_at, received_at`, append-only, indexed `(pair, name, received_at DESC)`. `seq` is the global insert sequence.

What main/ publishes on `cb-markers-main-flow` (`configs/shared_indicators_config.yaml`), wire `name` = `{tf}_{name}`, tf ∈ {15, 60, 240}, all `kind: "none"`, `volume` NULL, TTL 300 s:

| Names | Cadence | Type |
|---|---|---|
| `cb_high`, `cb_low`, `cb_zone_long`, `cb_zone_short`, `cbnc_high`, `cbnc_low` | 30 s heartbeat | price level (float) |
| `cb_inzone_long`, `cb_inzone_short`, `extdone_high`, `extdone_low`, `cb_f_extdone_long`, `cb_f_extdone_short`, `cb_f_trend_long`, `cb_f_trend_short` | 30 s heartbeat **plus** immediate publish of only the changed reading on a flip (`on_change: true`) | bool as `1.0` / `0.0` |

So 14 names × 3 tfs = 42 names, alongside the existing nine `ema_*` and `1_sar_002_02`. `cbnc_*` are NaN for the first minute after main/ starts and are not published then. A level changes value at most once per minute (`cbnc_*`, every minute; `cb_*`, when its tf candle closes). `name` stays opaque to the executor's Rust side; only the SPA interprets it.

Meaning, from the main/ spec: `cb_zone_{side}` is the entry-zone level derived from the predicted bound of the current closed candle; `cb_inzone_{side}` is true for a minute whose price touched that zone; `cb_f_extdone_{side}` is false when the candle's extension is already "done" for that side (`not extdone_high` for long, `not extdone_low` for short); `cb_f_trend_{side}` is false when the EMA-25 slope class points against the side. The filters are stored-only: main/ does not apply them to the marker, and neither does this spec by default beyond `cb_f_extdone`.

## 4. Read layer (L5, `PgStateReader`)

One new method, sibling of `read_signal_log` / `read_current_indicators`:

```rust
/// Every reading needed to reconstruct, minute by minute, what each
/// indicator name said for `pair` over `[from, to]`: the state in force at
/// `from` (seed) plus every value change inside the window. Ordered by
/// `received_at, seq`; each tuple's Ts is the row's `received_at`.
pub async fn read_indicator_series(&self, pair: Pair, from: Ts, to: Ts)
    -> Result<Vec<(Ts, IndicatorReading)>, StoreError>;
```

One SQL statement, two parts joined by `UNION ALL`, ordered as a whole:

**Seed** — per name, the newest row that had arrived before the window and was still live at its start. This is exactly `read_current_indicators`'s body with `as_of = from` and a strict `received_at < from`:

```sql
SELECT DISTINCT ON (name) name, value, kind, volume, expires_at, received_at, seq
FROM indicators
WHERE pair = $1 AND received_at < $2 AND expires_at > $2
ORDER BY name, received_at DESC, seq DESC
```

Without the seed, a window opened at a random instant would show nothing for a name until its next *change*, which for `cb_zone_*` at tf 240 can be hours away.

**Changes** — rows inside the window, with heartbeat repeats removed:

```sql
SELECT name, value, kind, volume, expires_at, received_at, seq FROM (
  SELECT name, value, kind, volume, expires_at, received_at, seq,
         LAG(value)      OVER w AS prev_value,
         LAG(expires_at) OVER w AS prev_expires_at
  FROM indicators
  WHERE pair = $1 AND received_at >= $2 AND received_at <= $3
  WINDOW w AS (PARTITION BY name ORDER BY received_at, seq)
) t
WHERE prev_value IS NULL
   OR value IS DISTINCT FROM prev_value
   OR received_at >= prev_expires_at
```

A row *starts a run* when it is the first of its name in the window, when its value differs from the previous row's, or when the previous row had already expired before this one arrived. The third condition pins a sender gap: if main/ stops and later resumes with the same value, the resumption row survives, so the SPA's hold logic shows the gap instead of bridging it.

**Revision 2026-10-17 (implementation):** each run comes back as its *first* row carrying the run's *latest* `expires_at` (a `MAX(expires_at) OVER (PARTITION BY name, run_id)` on top of the `LAG` query above, `run_id` a running `SUM` of the start flags). The spec's original filter returned the first row with its own `expires_at`, which under §7's hold-until-expiry rule would have shown a level that merely kept heartbeating as *gone* five minutes after its first row — the dropped heartbeats were exactly what kept it alive. The SPA store mirrors the same fold for the one repeat per name that crosses a Live incremental-fetch boundary (§7, `append`).

The `LAG` runs over the uncompressed window rows, so the first in-window row of a name is always kept even when its value equals the seed's — the SPA's store dedupes nothing on value, only on `(name, received_at)`, and a repeated value costs one point.

Order of the union: `ORDER BY received_at, seq`. Seeds therefore come first (their `received_at < from`).

Decoding uses the existing strict `decode_indicator_kind`; a row that fails surfaces as `StoreError::Decode`, never skipped (`CorruptRow::Surface`, as the siblings). Runs under the `dashboard` role (SELECT only). No name filtering server-side: `ema_*` and `sar` rows come back too; after compression they are a few points per change and the route stays generic.

No migration: `(pair, name, received_at DESC)` serves the seed's `DISTINCT ON` and the pair prefix of the changes query. `SCHEMA_VERSION` stays 11.

Size: a 24-hour Live backfill is bounded by the names that change every minute — six `cbnc_*` × 3 tfs × 1440 ≈ 26k rows worst case; everything else changes by the tf candle or on a flip. Fetched once per backfill; the incremental tick (§7) asks for seconds, not hours.

## 5. Backend (L8, `visualizer_backend`)

One thin pass-through, mirroring `signals()`:

```rust
pub async fn indicator_series(&self, pair: Pair, from: Ts, to: Ts)
    -> Result<Vec<(Ts, IndicatorReading)>, VisualizerError>;
```

No folding, no reordering, errors as `VisualizerError`.

## 6. HTTP (`visualizer_server`)

**`GET /api/pair_indicators?pair=&from=&to=`** — `HistoryParams`, same as `pair_signals`. Not-ready → `200 []`; query failure → `service_unavailable(...)`; `Vec<IndicatorPointDto>` as JSON, empty array never null.

```json
[{"name": "15_cb_zone_long", "value": "13.2871", "kind": "none", "volume": null,
  "received_at": 1789934214085, "expires_at": 1789934514085}]
```

Fields as `CurrentIndicatorDto` minus the derived `age_ms` / `expires_in_ms` (there is no single `as_of` here). `value` / `volume` are strings (`Decimal` convention). Seed rows appear with `received_at < from`; that is deliberate and documented on the DTO.

## 7. SPA — data

New file `static/js/cb_overlay.js`: pure logic, no DOM, no chart library. Exposed as `globalThis.CbOverlay` so the same file loads as a plain script in `pair.html` and as a module-less file under `node --test` (§10).

**`IndicatorSeriesStore`** — `Map<name, Point[]>` with `Point = {t: received_at, v: Number(value), exp: expires_at}`, each array sorted by `t`.

- `append(rows)` — merges one route response. Dedupe on `(name, t)` (expiry widened to the later one). Keeps only names matching `^\d+_(cb_|cbnc_|extdone_)`; `ema_*` / `sar_*` are dropped. Non-finite `value` is skipped. A row that repeats the newest point's value while that point is still live extends the point's expiry instead of adding one (the route folds such repeats inside a window; the first repeat of every Live tick crosses the window boundary unfolded).
- `valueAt(name, tMs)` — binary search for the last point with `t <= tMs`; returns its `v` when `tMs < exp`, otherwise `null`. This is the one place that defines "what the sender was saying at instant t": held from arrival until the next row of the same name or its own expiry, whichever first.
- `lastReceivedAt()` — newest `received_at` seen by `append` (folded repeats included); the incremental fetch's lower bound. An empty store falls back to the backfill window's `from`.
- `clear()`.

**Sampling grid** is the chart's 1-minute candles. For a minute starting at `m`, the sample instant is `min(m + 59 999 ms, windowEnd)` where `windowEnd` is `now` in Live and the loaded range's `to` in History — the latest value known inside that minute. A bool name samples true iff `v === 1`; a level name samples a finite number or `null` (gap).

**Fetch cadence** — no new timer:

| Event | Fetch |
|---|---|
| Live initial backfill, History range load | `store.clear()`, then full `[from, to]` of the trade-activity window (Live: `DEFAULT_BACKFILL_MS` lookback; History: the loaded range) |
| Live poll tick (existing 5 s `startStatusPolling`) | `[store.lastReceivedAt() + 1, now]`, appended |
| History poll tick | nothing — the window is fixed and its rows immutable |
| Mode switch | `store.clear()`, overlay series emptied |

A fetch failure keeps the store and degrades silently (`.catch(() => [])`, as `pairSignals`). A flip becomes visible within one poll tick plus main/'s own tick.

**Redraw** `setCbOverlay(state, store, toggles, windowEnd)` runs after every append and after every toggle change; it rebuilds every overlay series with `setData` (replace, never append — the posture every marker overlay in `chart.js` already takes). The forming minute's dot can lag the live candle by up to one poll tick; accepted.

## 8. SPA — chart rendering and controls

All on the main candlestick chart. Series are created once in `createPairChart` (30 in total) and only their data changes.

### 8.1 Families

| Family | Default | Names | Drawn as |
|---|---|---|---|
| Zones | on | `{tf}_cb_zone_{long,short}` | step line (`lineType: WithSteps`), one point per minute; a `null` sample becomes a whitespace point so the line breaks over a gap |
| Markers | on | `{tf}_cb_inzone_{long,short}` | dot series (`lineVisible: false, pointMarkersVisible: true`, radius 3), one dot per minute that samples true. Long: below the minute's candle low; short: above its high |
| Bounds | off | `{tf}_cb_{high,low}` | step line, slate shades |
| Forming | off | `{tf}_cbnc_{high,low}` | step line, amber shades, dashed |
| Extdone | off | `{tf}_extdone_{high,low}` | dots, grey; `high` above the candle high, `low` below the low |

Colours: zone/marker long = lime, short = rose; shade darkens with tf (15 light → 240 dark), the same "one hue, three horizons" convention `SIGNAL_MARKER_STYLE` uses. Every overlay series has `autoscaleInfoProvider: () => null`, `lastValueVisible: false`, `priceLineVisible: false`, `crosshairMarkerVisible: false`.

Marker offset from the candle: `max(0.3 × (high − low), 0.0002 × close)`, multiplied by 1 / 2 / 3 for tf 15 / 60 / 240, so the three tfs stack outward and never overlap. A minute with no candle in the chart's data draws no dot.

### 8.2 Filters

Three toggles: `filter: extdone` (default **on**), `filter: overshoot` (default **on**, added by phase 19 — `specs/2026-10-17-cb-overshoot-main-flow-design.md`; a no-op until main/ broadcasts `{tf}_cb_f_overshoot_{side}`), `filter: trend` (default off). A marker for `(tf, side)` at minute `m` is drawn only when, for every checked filter, `{tf}_cb_f_{filter}_{side}` samples true at `m`. A `null` sample (name never received, or expired) means "filter not applicable" and the marker passes — the same skip-if-absent rule main/'s viewer applies when a flag column is missing. `filter: extdone` additionally blanks the `{tf}_cb_zone_{side}` line where its flag samples false, matching main/ Task 11. Filters never touch Bounds, Forming or Extdone families.

### 8.3 Timeframes

Three toggles `15 / 60 / 240`, all on. An unchecked tf empties every series of that tf.

### 8.4 Controls

A new `<div id="cb-controls">` directly above `#chart-legend` in the Chart panel, plain checkboxes in three groups:

```
Zones · Markers · Bounds · Forming · Extdone  |  filter: extdone · overshoot · trend  |  15 · 60 · 240
```

Legend swatches for the families are rendered from the same style constants that draw the series (the `renderChartLegend` rule: a hand-written colour would drift). Toggle state lives in memory only; a reload restores defaults. A toggle change redraws from the store and never fetches.

## 9. Error handling

- Route: not-ready → `200 []`; query or decode failure → `503` via `service_unavailable`, same as every sibling.
- SPA: fetch failure → silent, last data kept; unknown names ignored; non-finite values skipped; a name that expires mid-window simply stops being sampled (gap), nothing is extrapolated.
- A name present in the store but absent from the style tables (future broadcasts) is ignored, not an error.

## 10. Testing

**L5** (`crates/state_store/tests/pg_store.rs`, DB-backed, as `dashboard`): seed row returned per name when live at `from`; no seed when expired at `from`; heartbeat duplicates dropped; a value change kept; the same value after an expiry gap kept; rows after `to` excluded; other pairs excluded; order `received_at, seq`; empty table → empty vec; unknown `kind` → `StoreError::Decode`.

**L8** (`crates/visualizer_backend/src/lib.rs`): reads back what was stored; empty vec on no rows; typed error, not a panic, on a dead pool.

**Route** (`crates/visualizer_server/tests/passive.rs`): not-ready → `200 []`; populated → DTO shape with string decimals, seeds included with `received_at < from`; other pairs excluded.

**SPA pure logic** (`static/js/cb_overlay.test.js`, `node --test`, host-run, no npm, no dependencies — the first JS test in the repo): `valueAt` holds until the next row; expiry → `null`; dedupe on append; incremental merge keeps order; sampling instant; filter mask ANDs checked filters and lets `null` pass; zone line blanked by `cb_f_extdone`; marker offset stacking by tf; tf toggle empties series; `ema_*` dropped on append.

**Rendering**: manual and user-gated, as in the previous visualiser plans. Rebuild `visualizer` from the branch, seed `indicators` by SQL with rows shaped like `15_cb_zone_long` / `15_cb_inzone_long` / `15_cb_f_extdone_long` over a recent range, open the pair page, check lines, dots and each toggle; then load a History window over the seeded range and repeat. A live check against real main/ happens only when the operator runs `live` on `cb-markers-main-flow`. Not claimed done unless run.

All Rust tests under `docker compose run --build --rm test` (DB-backed tests cannot run on the host).

## 11. Acceptance criteria

- [x] `GET /api/pair_indicators` returns seeds plus compressed changes for a seeded window, correct shape, other pairs excluded. *(passive.rs, 5 tests; 15 120 seeded rows over 3 h came back as 1 522 points)*
- [x] Docker test suite green including the new L5 / L8 / route tests; `node --test static/js/cb_overlay.test.js` green (17). *(see the plan's final gate)*
- [x] Pair page: zone lines and in-zone dots for the seeded data at all three tfs; `filter: extdone` off shows the vetoed dots and unblanks the line; `filter: trend` masks; each tf toggle hides its series; Bounds / Forming / Extdone toggle on and draw. *(2026-10-17, headless Chrome over CDP against the host-built visualiser + seeded throw-away DB; no console errors. The in-stack check by the operator is still to run.)*
- [x] History mode over the seeded range shows the same picture; the Indicators panel is unchanged. *(same run: store emptied on the mode switch, refilled on Load)*
- [x] L5 and L8 layer specs updated with the new reader and pass-through.
