# Plan: same_side_zone_gap (2026-10-21)

Spec: `../experiment/same_side_zone_gap.md`. Read-only replay, no code-repo branch (precedent:
higher_tf_bounds_geometry). External docs branch `cross-tf-veto-replay`. Nothing committed until the user approves.

## Known facts (recon 2026-10-21)

- Register: higher_tf_bounds_geometry (negative) measured range position f, ATR room, OPPOSITE-bound coincidence
  (nest) and executed opposite zone (exz); the signed same-side zone gap was not measured. Its f ≥ 0.9 bin (long entry
  near the 60 low) is mildly worse on 2y (long PF 1.00 mean +0.3 vs +2; short 1.08 / +3.2 vs +3.7) — the only hint.
- Paper exports copied from the bounds-geometry session into this session's scratchpad `…/a4a6a35b-…/scratchpad/data`
  (trades.csv 748 276 rows, indicators.csv with `{tf}_cb_zone_long/short`, `cb_low/high`, `cb_inzone_*`, `cb_f_*`,
  `cbnc_*`; events.jsonl 188 rows; trend_cache.npz) and `…/scratchpad/klines`; stats
  `executor/runs/2026-10-21-trend-ma-length-ema-stats-2y.json`.
- Harness: `executor/runs/2026-10-21-higher-tf-trend-replay.py` imported as a module (I_START, ZONE, INZONE, TARGET,
  GEO_OK, C07, candle_stop, mean_range, simulate, stats, row). The delay variants need a pending-limit extension of
  `simulate` → copied into the new script.
- Tier B: `2026-10-21-bounds-geometry-2y-oos2m.py` load / classes / simulate_all reused; stored zone lines on oos2m,
  derived with ZONE_FRAC 0.05 on 2y. RSS ~850 MB; host 15 GB with ~1 GB free + swap — run tiers sequentially.
- Live stack `cbov-check` untouched (replay reads exports only).

## Tasks

1. Tier B `executor/runs/2026-10-21-same-side-gap-2y-oos2m.py`: gap quantities at the candidates, e25 splits by gap
   bin, veto grid + delay grid, 2y freeze → oos2m score. Gate: e25 baselines equal the bounds run (2y +166 435 /
   57 383; oos2m +15 827 / 4 414).
2. Paper `…-same-side-gap-replay.py`: gap per trade from the stored zone lines, vectorised 15-min extreme for the
   stop distance, veto variants + delay variants with a pending limit. Gates: harness fires 177/188; zone lines present
   ≥ 97 % of trades; `gz`-veto with k = 0 reproduces e25 exactly.
3. Run both; raw outputs beside the scripts.
4. Results `experiment/results/same_side_zone_gap_results.md`, run report `executor/runs/…-same-side-gap-replay.md`,
   REPORT.md row closed. User approves before any commit.
