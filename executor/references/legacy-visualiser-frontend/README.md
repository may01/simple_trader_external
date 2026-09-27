# Legacy visualiser frontend (salvaged reference)

Source: trade_executor branches `executor-visualiser` /
`visualiser-live-binance-no-trade` (same commit `b201ecc`, worktree
`.worktrees/executor-visualiser`), deleted 2026-09-12. Both branches were
58 commits behind main and superseded by
[2026-09-07-executor-visualiser-design.md](../../specs/2026-09-07-executor-visualiser-design.md)
(Postgres-backed transport). Backend Rust (visualizer_server,
visualizer_backend, in-process broadcast wiring) was dropped entirely —
not portable, whole crates rewritten since. These static files are kept
as layout/wiring reference for whoever implements the real SPA on top of
the new `visualizer_server` scaffold (currently a placeholder
`index.html` on `state-store-expansion-postgres`).

## Reusable as-is (per spec: "what the dashboard renders... unchanged")
- `static/pair.html` — panel layout structure
- `static/css/style.css` — styling
- `static/js/format.js` — number/time formatting helpers

## Reusable with rework
- `static/js/pair.js` — WS subscribe + panel update wiring is a good
  reference, but:
  - DTO shapes will change (old: in-process broadcast payloads; new:
    `PgMarketDataReader`/`PgStateReader` rows over `/api/history`,
    `/api/freshness`, `/ws?pair=`).
  - All Chart.js-specific calls must be replaced. Spec locks
    candlestick rendering to `lightweight-charts` (TradingView), not
    Chart.js.

## Not carried over
- `static/js/chart.js` and vendor `chart.umd.js` — built on Chart.js,
  contradicts the spec's `lightweight-charts` decision. Not copied.
