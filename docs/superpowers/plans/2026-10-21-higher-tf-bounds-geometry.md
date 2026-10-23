# Plan: higher_tf_bounds_geometry (2026-10-21)

Spec: `../experiment/higher_tf_bounds_geometry.md`. Read-only replay, no code-repo branch (precedent:
higher_tf_pullback_veto). External docs branch `cross-tf-veto-replay`. Nothing committed until the user approves.

## Known facts (recon 2026-10-21)

- Register: cross_tf_veto_replay (dead), higher_tf_trend_filter (negative on paper, run report written, results md
  pending in another session — not touched here), higher_tf_pullback_veto (negative, archived). None measured range
  position or bound coincidence.
- Paper exports (trend_ma_length session, reused): `/tmp/claude-1000/-home-om-projects-simple-trader/1b027314-…/scratchpad/data`
  (trades.csv 748 276 rows 10-16 22:29Z → 10-21 10:07Z; indicators.csv with `{tf}_cb_high/low`, `cb_zone_*`,
  `cb_inzone_*`, `cb_f_*`, `extdone_*`, `cbnc_*`, `ema_*`; events.jsonl 188 CbZoneEntry rows; trend_cache.npz) and
  `…/scratchpad/klines/klines_{1m,15m,1h,4h}.csv`; stats `executor/runs/2026-10-21-trend-ma-length-ema-stats-2y.json`.
  Copied into this session's scratchpad before use.
- 2y frames: `2y_az_link_usdt/df_with_indicators.pkl` (`1_high/low/close`, `{tf}_close/is_closed/high/low`),
  `2y_link_usdt/df_with_candle_bounds.pkl` (`{tf}_cb_low/high(_std)`, `cb_inzone_*`), `…_nc.pkl` (`{tf}_cbnc_high/low`),
  ATR from `2y_link_usdt/df_with_indicators.part_NN.pkl` (`1_atr_14_ma_5`); oos2m all in `oos2m_link_usdt/df_with_indicators.pkl`
  (884 cols; also `{tf}_cb_zone_*`, `{tf}_extdone_*`). Tier-B RSS ~700 MB–1 GB; host 15 GB with ~1 GB free (Chrome / VS Code / live stack).
- Zone lines: `zone_long = cb_low + ZONE_FRAC·span`, `zone_short = cb_high − ZONE_FRAC·span` (kernel.py:97).
- Live stack `cbov-check` untouched (replay reads exports only).

## Tasks

1. Tier B `executor/runs/2026-10-21-bounds-geometry-2y-oos2m.py` (pullback stand-in flow + the geometry quantities):
   descriptive block, variant grids, 2y fit → frozen q/k/δ printed, oos2m scored with the frozen values.
   Gate: e25 baselines equal the pullback run (2y e25 +166 435 / 57 383 entries at hold 60; oos2m +15 827 / 4 414).
2. Paper replay `…-bounds-geometry-replay.py` importing the trend-filter harness: stored cb_high/low per trade,
   frozen variants + grid for display + mirror + placebo. Gates: 177/188 fires (harness), cb_high/low present ≥ 97 %.
3. Run both; raw outputs beside the scripts.
4. Results `experiment/results/higher_tf_bounds_geometry_results.md`, run report `executor/runs/…-replay.md`,
   REPORT.md row closed. User approves before any commit.
