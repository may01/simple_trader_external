# Wall visualisation — implementation plan

Implements [wall-visualisation-design.md](../specs/2026-09-09-wall-visualisation-design.md).

Branch: work done in the `executor-visualiser` worktree (the frontend
exists only there). The `wall-side-typed` branch turned out **not** to be
a prerequisite: `WallObservation` carries its own `side`, so
`LevelSource::Wall(Side)` is not on this path.

Layer order (bottom to top):

1. `local_analysis` — `WallObservation`, `WallSink`, sink-aware analyzer (L2)
2. `state_store` — `wall_log` tree + `read_wall_log` (L5)
3. `visualizer_backend` — `wall_snapshots` (L8a)
4. `visualizer_server` — history field, `LiveMessage::Walls`, WS poll (L8b)
5. Frontend — remove trade markers, add wall scatter overlay
6. `orchestrator` — sink injection + snapshot tick task (L9)

## Status: implemented

| Layer | Change | Tests |
| --- | --- | --- |
| L2 | `WallObservation`, `WallSink`, `WallDetector::wall_observations`, `LiveCriticalLevelAnalyzer::{new,with_wall_sink}` + per-pair bucket rate limit | 38 pass |
| L5 | `wall_log` tree, `WallSnapshotDto`/`WallObservationDto`, `impl WallSink for StateStoreImpl`, `read_wall_log` | 33 pass |
| L8a | `VisualizerBackend::wall_snapshots` (always historical, `catch_unwind`) | 24 pass |
| L8b | `HistoryResponseDto.walls`, `LiveMessage::Walls`, WS seed-then-poll task, `with_ws_tuning` test hook | 20 pass |
| Frontend | trade-marker path deleted; `createWallSeries`/`setWallSnapshots`/`appendWallSnapshot` | `node --check` |
| L9 | `WALL_SNAPSHOT_INTERVAL_SECS` config, sink injection, `spawn_wall_snapshots` tick task | workspace green |

Verified end-to-end with `cargo run --release -p orchestrator --example smoke`:
`state_store_wall_snapshot_written` fires once on boot and the rate limit
holds on later ticks; `GET /pairs/:pair/history` carries the `walls`
field.

## Live run against real market data

`crates/orchestrator/examples/live_walls.rs` boots the real system
against **public** Binance market data — the `@depth` diff stream, the
`@trade` stream and the klines REST endpoint, none of which are signed.
The account side is faked; `place_order`/`cancel_order` panic rather than
no-op, so a wiring mistake fails loudly instead of looking like a fill.
No API key is used and no signed request is ever made.

```
cargo run --release -p orchestrator --example live_walls
# http://127.0.0.1:18100/pair.html?pair=BTCUSDT
# env: LIVE_PAIR, LIVE_WALL_MULTIPLIER, LIVE_SNAPSHOT_INTERVAL_SECS, LIVE_BIND_ADDR
```

Confirmed on a live BTCUSDT book: 112 walls in the first snapshot, rows
served by `GET /history`, dots drawn at their prices, legend rendered.

### Two findings from that run

1. **`WALL_MULTIPLIER=3` is far too permissive on a full-depth book.**
   Binance's `@depth` stream carries thousands of levels whose mean size
   is tiny, so 3x mean flagged 112 "walls" in one snapshot (72 bid / 40
   ask). The detector is behaving as specified; the threshold is the
   problem. Needs re-tuning against a real book — a much larger
   multiplier, or a different statistic (a high percentile of level
   size, rather than a multiple of the mean, which the mean's own
   sensitivity to the walls being detected keeps dragging upward).

2. **Walls must not drive the price scale.** The largest resting orders
   cluster at round numbers thousands away from spot (76000 / 80000 /
   81000 while BTC traded at 79400). With those in autoscale the axis
   spanned 74k-86k and the candles flattened into a line. The wall
   series now sets `autoscaleInfoProvider: () => null`: candles own the
   scale, walls are drawn onto it, and a wall outside the visible range
   is off-screen until the user zooms out.

## Chart legend

`#chart-legend` above the chart, filled by `renderChartLegend` from the
`WALL_STYLE` constants themselves — a hand-written colour in the HTML
would silently drift from the one the series actually draws.

## Visualiser fixes found by running it live

1. **Order book never updated (real bug, not cosmetic).** `fold_order_book`
   started with `tracker = None` and only seeded on a `BookSnapshot`. A
   real adapter emits its REST depth snapshot **once**, at subscribe
   time, and everything after is deltas — so every viewer that connects
   later saw `BookUpdate`s only, all silently dropped by the
   `if let Some(t)` guard. Measured over a live WS: 0 `Book` messages in
   25s against 1257 trades; the panel rendered once from `GET /history`
   and froze.

   `order_book_view` now seeds the fold from `feed.order_book(pair)` on
   the **live path only** — `historical_order_book` stays unseeded,
   since seeding a past range from the current book would open that
   range with prices that were never in it. An empty stored book is not
   used as a seed: folding deltas onto nothing yields only the levels
   that changed, which looks like a book but is not one. After the fix:
   27 `Book` messages in 25s, sequence advancing, ~1000 levels a side.
   Three regression tests cover the deltas-only, empty-seed and
   historical cases.

2. **Text contrast.** `--muted` was `#6b7280` (4.8:1 on white) and used
   at 12–13px for panel headings, the chart key and log lines. Now
   `#4b5563` (7.5:1), with a separate `--heading` `#374151` for panel
   titles. Chart.js also defaults its ticks and axis titles to `#666`;
   those are now pinned to the same value rather than inherited.

3. **Buy/sell volume bars overlapped.** Both histogram series plotted at
   the same bucket timestamp, so the second painted over the first and
   only one bar per bucket was ever visible (the doc comment claiming
   sell sat below the zero line was simply wrong). The sell series is
   now offset half a bucket (`TRADES_VOLUME_SLOT_SEC`), giving each side
   its own slot — lightweight-charts derives histogram width from bar
   spacing and has no grouped-bar mode, so the time axis is the only
   place that separation can come from. Empty sides are dropped rather
   than sent as zeros, since a zero-height bar still reads as "a bar was
   drawn here".

## Follow-up visualiser changes

4. **Volume bars now pair per 10s bucket.** The half-bucket offset from
   fix 3 separated the bars but spread them evenly, because
   lightweight-charts' time scale is **ordinal**: it lays out one slot
   per distinct timestamp across all series and spaces those slots
   evenly, so a 7s offset placed a bucket's two bars as far apart as two
   bars from different buckets. Bucket is now 10s and the sell bar sits
   one second after the buy bar, so the pair occupies neighbouring slots
   and the rest of the bucket becomes the gap before the next pair.

5. **Second depth chart, +-0.5% around the touch.** Same chart, same
   colours, one constant apart (`DEPTH_CHART_ZOOM_WINDOW_FRACTION`),
   rendered under the wide one inside the Order Book panel.
   `updateDepthChart` now takes the window fraction as a parameter and
   **filters the levels** to it rather than only clamping the X axis:
   Chart.js autoscales Y over the whole dataset, so leaving far-away
   levels in means the Y axis is set by depth nobody is looking at and
   the curve inside the window flattens against the bottom of the pane
   -- the tighter the window, the flatter. Cumulative volume is still
   summed outward from the touch, so surviving points keep their Y
   values. The wide chart gets the same treatment, which also fixes its
   own (milder) version of the problem.

6. **Position summary rendered permanently grey (real bug).** Sampling
   the rendered pixels rather than eyeballing them found "BTCUSDT" drawn
   at `#4b5563`, i.e. `--muted`, not `--text`: `pair.html` ships
   `<div id="position-summary" class="muted">Loading...</div>` and
   `renderPositionSummary` replaced the element's *content* without ever
   dropping the placeholder's class, so the pair name, status and flag
   stayed secondary-grey for the life of the page.
   `el.classList.remove("muted")` on render. (The book/overview
   placeholders use the same idiom safely -- there the whole `<td>`/row
   is replaced, class included.)

   Two contributing causes alongside it: buttons inherit neither `color`
   nor `font-family`, so `.mode-toggle`/`.history-controls` buttons were
   drawing in the UA's own button colour and font (measured `#000` in
   headless Chrome, platform-grey elsewhere) -- both now pinned; and the
   "never reconciled" state rendered as bare `muted` text `n/a` beside
   the coloured OK/DISCREPANCY badges, which read as a rendering
   failure rather than a status. It is now a neutral `flag-unknown`
   pill reading NOT RECONCILED, used by the overview table too.

7. **Recent Trades moved and widened.** Panel order is now Position ->
   Chart -> Recent Trades -> Order Book -> Event Log, and
   `RECENT_TRADES_WINDOW_MS` is 20 minutes.

   Widening the window alone did not widen the view: the pane still
   showed ~4 minutes. The time scale is ordinal (one slot per distinct
   trade second), so 20 minutes is over a thousand slots and the default
   bar spacing puts only the last few hundred on screen -- the data was
   there, the viewport was not. `setTradesChartData` now calls
   `timeScale().fitContent()`, which is right for a panel that is
   explicitly "the last N minutes". The candle chart deliberately does
   not do this: panning back through history there is the point.

   Density note: 20 minutes of 10s buckets is ~120 buckets, ~240 bars
   once split buy/sell. Still legible, but if the bars want more weight
   the bucket is the knob (`TRADES_VOLUME_BUCKET_MS`), not the window.

8. **Auto-fit became a default, not a policy.** `fitContent()` on every
   redraw meant a viewer could never zoom the trades panel: the next
   live trade snapped the view back. `createTradesChart` now carries an
   `autoFit` flag, true at open and cleared on the first
   `wheel`/`mousedown`/`touchstart` on the container; `fitContent` runs
   only while it is set, and double-clicking the pane re-arms it.

   The flag is driven from raw pointer events rather than
   `subscribeVisibleLogicalRangeChange`, because that callback cannot
   distinguish a viewer's zoom from the `fitContent` the code itself
   calls -- it would disarm auto-fit on our own change.

   Verified over CDP with real dispatched input, not by inspection:
   autoFit true / span 61 slots at open; after a wheel event, false /
   55; after three redraws, still 55; after a double-click, true / 61.

9. **History payload is the real page-load cost (partly fixed).**
   Measured on a store holding ~2h of live BTCUSDT: `GET /history` over
   24h returned **97 MB in 105s**, leaving the page stuck on
   "Loading...". Attribution:

   | field | count | size |
   | --- | --- | --- |
   | trades | 687,787 | 89.1 MB |
   | walls | 641 snapshots, avg 177 walls each | 7.6 MB |
   | book | 1 | 0.6 MB |
   | candles | 132 | 0.03 MB |

   The wall half is fixed: `WallSnapshotDto::from` now keeps only the
   largest `MAX_WALLS_PER_SIDE` (8) per side, which is what the client's
   own qty ranking would have kept anyway (the chart draws four). 177
   walls a snapshot -> 16; the walls field measured 0.01 MB after.

   **The trades half is untouched and still the dominant cost.**
   `DEFAULT_BACKFILL_MS` is 24h while the trades panel only ever keeps
   `RECENT_TRADES_WINDOW_MS` (20 min) of them -- the other ~23h40m is
   fetched, parsed and thrown away. Shrinking the backfill outright
   would also shorten the candle chart's history, which is a product
   decision, so the options are: a separate, shorter range for trades
   (a `trades_from` query param, or a second request), or a server-side
   cap on returned trades. Left open deliberately.

10. **Buy/sell volume moving averages on the trades chart.** Trailing
    five-minute means (`TRADES_VOLUME_MA_WINDOW_MS`), one per side,
    ending at and including the bar being plotted -- never a centred
    window that would peek right. Each mean is drawn on its own side's
    slot so it tracks the bars it summarises.

    Two details that decide whether the number means anything:

    - The means are computed over a **dense** bucket grid, quiet buckets
      included as zeros. Averaging only the buckets that saw trades
      would report the mean of *active* buckets, which rises exactly
      when activity thins out -- the opposite of what the line is for.
    - Buckets before the window is full average what exists rather than
      dividing by 30 buckets that have not happened yet, which would
      drag the first five minutes toward zero.

    `trailingMeans` is unit-tested directly (ramp-up divisor, sliding
    window, zero buckets pulling the mean down, current bar inside the
    window).

    **Scale.** Sharing the bars' price scale is the textbook choice and
    was tried first: it is unreadable here, because one outsized trade
    sets the bars' maximum and a five-minute mean is a fraction of a
    single spike -- both lines collapsed onto the baseline. The means
    now share their own scale (`volma`) overlaying the same band, so
    buy-versus-sell (the comparison the lines exist to make) stays
    exact, while a line's height is no longer comparable to a bar's.
    The legend says so rather than leaving it to be misread.

    Confirmed on live data: the sell mean steps up at 19:05 and falls
    back at 19:10 -- one large sell entering, then leaving, a
    five-minute trailing window.

## Config

`WALL_SNAPSHOT_INTERVAL_SECS` — new required env var, added to
`docker-compose.yml` as `60` (one snapshot per 1-minute candle). `0`
disables wall recording entirely.

## Deliberate design points worth not regressing

- `walls()` is implemented in terms of `wall_observations()` — one
  threshold, not two.
- `WallSink::record` is infallible to its caller; it sits on
  `execution`'s decision path.
- The snapshot bucket is computed from `book.ts`, not a wall clock, so
  replay reproduces live.
- The WS poll seeds its high-water mark **before** the loop; treating
  the first row-finding poll as the seed swallows the first snapshot
  ever written on an empty store (caught in review, has a regression
  test).
- Empty `walls` rows are stored, not skipped — "none here" differs from
  "not recorded".

## Follow-ups

- **Collapse into `analysis_log`.** `state-store-expansion` adds a
  generic `persist_analysis`/`read_analysis_log`. Once merged, `wall_log`
  should become `kind = "walls"` on that log, with `WallSink` kept as the
  typed façade.
- **System-trade arrows.** `arrowUp`/`arrowDown` are now unused. The
  intended next use is the executor's own fills, sourced from the
  position event log rather than the exchange trade feed.
- **Docker verification.** `docker compose run --rm test` not run here —
  containers write root-owned files into the mounted worktree.
