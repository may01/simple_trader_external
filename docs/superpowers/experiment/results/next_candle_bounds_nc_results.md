# Next-Candle Bounds on Non-Closed Candles — Results

**Date:** 2026-07-24
**Spec:** `experiment/next_candle_bounds_validation.md`; plan `plans/2026-07-24-next-candle-bounds-nc.md`
**Branch:** `next-candle-bounds-nc` (worktree `zone-selection-experiment`)
**Data:** models frozen on `2y_az` closed candles, validated per-minute on `oos2m` (LINK/USDT).
**Producer:** `notebooks/candle_bounds_nc/{cbnc.py,run_cbnc.py}` (committed code — replaces the
lost scratchpad scripts of the closed-candle round).
**Final configuration (current artifact):** HYBRID zone space — SL = closed bound,
target = nc bound hair-cut 0.35 % of price toward the loss side, zone frac = 0.05.
Headline: reach-of-target 0.57–0.73 on nc-flagged minutes vs 0.11–0.15 for the closed
zones; nc zone ≈ strict subset of the closed zone; bound accuracy converges from r² ≈ 0
(candle start) to the closed model's 0.31–0.40 (candle close). Not P&L-validated — the
reach gain is target-proximity, not entry selection; realized-R with fees is the required
next arbiter.

## What was built

At every 1-minute row the *forming* candle is fed through the same frozen Ridge models
(`candle_bounds_algorithm.md`) that normally take the latest closed candle: running
cummax/cummin as the extreme, forming indicator values, rolling blocks decomposed into
11-closed + 1-forming. The prediction is therefore the extreme of the next ~tf-minute window
starting at that row, refreshed every minute — vs the closed bound, which is computed once
per candle and goes stale. Stored one row later (shift(1)), the same
no-same-row-look-ahead convention as the closed broadcast.

Artifacts (sidecar next to the dataset, additive):

- `df_with_candle_bounds_nc.pkl` — 84 961 × 42: `{tf}_cbnc_{high,low}[,_std,_up,_dn]`,
  `{tf}_cbnc_zone/inzone_{long,short}` (HYBRID space: closed bound as SL side, nc bound as
  target side, frac = 10 % — see Entry-zone section), and
  `{tf}_cbx_inzone_{long,short}` = closed ∧ non-closed zone intersection.
- `candle_bounds_nc_meta.json`, `candle_bounds_nc_metrics.json`.

Viewer (`view_full.py` → `data.join_candle_bounds_nc` → `frontend/data_viewer.py`):
overlay groups `cbnc_bounds`/`cbnc_band`/`cbnc_long`/`cbnc_short` (teal/chocolate lines
next to the blue/orange closed pair), open star-triangle `cbzone_nc_*` markers at 1.5×
offset, and star `cbx_*` intersection markers at 3× offset.

## Reproduction gates (all passed)

- **G1** — refit `band_pct` vs stored `candle_bounds_meta.json`: relative diff ≤ 3e-16 on
  all 6 (tf, side). The lost pipeline is reproduced to machine precision.
- **G2** — closed inference vs stored `df_with_candle_bounds.pkl` on oos2m: interior
  max relative diff ≤ 1.6e-15. Two accepted edge deltas of the *stored* artifact: it has
  one extra warmup candle at the series start, and it ffills a stale bound into the final
  partial-candle row where a fresh prediction was available.
- **G3** — nc prediction at each candle's first row == closed prediction (they use
  identical information there): max relative diff ≤ 1.6e-15.

## Bound accuracy vs progress through the forming candle

r² / MAE% / ±1-band coverage of the nc prediction against the realized next-candle
extreme, bucketed by how far through the forming candle the prediction was made.
`closed` = the per-candle closed-bound baseline against its own target.

| combo | 0–25 % | 25–50 % | 50–75 % | 75–100 % | closed |
|---|---|---|---|---|---|
| 15_high | 0.02 / 0.50 / 0.44 | 0.08 / 0.44 / 0.49 | 0.17 / 0.38 / 0.55 | 0.30 / 0.32 / 0.63 | — / 0.30 / 0.66 |
| 15_low | 0.04 / 0.49 / 0.54 | 0.10 / 0.43 / 0.60 | 0.21 / 0.37 / 0.67 | 0.33 / 0.31 / 0.75 | — / 0.29 / 0.78 |
| 60_high | 0.00 / 0.98 / 0.46 | 0.04 / 0.89 / 0.51 | 0.16 / 0.76 / 0.56 | 0.29 / 0.64 / 0.63 | — / 0.59 / 0.66 |
| 60_low | 0.02 / 1.01 / 0.54 | 0.09 / 0.91 / 0.59 | 0.19 / 0.79 / 0.65 | 0.30 / 0.65 / 0.73 | — / 0.61 / 0.77 |
| 240_high | −0.01 / 2.02 / 0.46 | 0.07 / 1.77 / 0.50 | 0.13 / 1.58 / 0.55 | 0.23 / 1.26 / 0.64 | — / 1.13 / 0.70 |
| 240_low | −0.01 / 2.19 / 0.52 | 0.09 / 1.93 / 0.56 | 0.21 / 1.68 / 0.62 | 0.35 / 1.34 / 0.71 | — / 1.24 / 0.76 |

Reading: quality rises monotonically with candle progress and converges to the
closed-model level at the close (the last bucket sits just under it because it averages
progress 0.75–1.0, and G3 shows exact equality *at* 1.0). Early-candle predictions
(first quarter) carry essentially no extension signal — r² ≈ 0, coverage ~10 pp below
the closed band. The nc bound is **not a better bound**; it is the same bound made
available continuously, at a freshness-for-accuracy trade the buckets quantify.

## Entry-zone validation (first-touch of the target bound within the next tf minutes)

Three zone definitions were run in sequence; the artifact currently carries the third.

**Current: HYBRID space, frac = 0.05, target hair-cut 0.35 %.** The nc zone keeps the
closed bound as the stop-loss side; the operative target is the per-minute forming
prediction pulled 0.35 % of price toward the loss side
(`cbnc_tgt_long = cbnc_high·(1−0.0035)`, `cbnc_tgt_short = cbnc_low·(1+0.0035)` —
stored as columns, drawable via the `cbnc_tgt` overlay). Zone level =
SL + frac·(target − SL); inverted span → never in-zone. Closed zones unchanged (own bound
pair, frac 0.05). `reach nc` counts first-touch of the *hair-cut nc* target; `reach cb` of
the closed bound — not level-for-level comparable:

| tf | dir | inzone nc | ∩ | reach nc | reach cb |
|---|---|---|---|---|---|
| 15 | long | 6 433 | 6 433 | **0.728** | 0.116 |
| 15 | short | 5 407 | 5 407 | **0.733** | 0.121 |
| 60 | long | 9 573 | 9 572 | **0.672** | 0.119 |
| 60 | short | 7 685 | 7 685 | **0.710** | 0.106 |
| 240 | long | 9 254 | 9 254 | **0.645** | 0.153 |
| 240 | short | 6 406 | 6 406 | **0.567** | 0.112 |

Each deeper hair-cut trades zone size for reach: 0 → 0.15 → 0.35 % moves reach
0.43–0.54 → 0.49–0.62 → **0.57–0.73** while shrinking the flagged set ~55 % from the
no-hair-cut zone (nearer target pulls the zone level toward the SL). The nc set is now an
exact subset of the closed zone on every combo. Per-hit profit is 0.35 % lower and the
SL/fee side unchanged — realized-R still owed before treating rising reach as improvement.

**HYBRID, frac = 0.05, hair-cut 0.15 % (previous run):**

| tf | dir | inzone nc | ∩ | reach nc |
|---|---|---|---|---|
| 15 | long | 14 262 | 14 259 | 0.603 |
| 15 | short | 11 706 | 11 705 | 0.616 |
| 60 | long | 12 311 | 12 310 | 0.549 |
| 60 | short | 10 139 | 10 139 | 0.600 |
| 240 | long | 10 282 | 10 282 | 0.583 |
| 240 | short | 7 024 | 7 024 | 0.492 |

**HYBRID, frac = 0.05, no hair-cut (previous run):**

| tf | dir | inzone nc | inzone cb | ∩ | reach nc | reach cb | reach ∩ |
|---|---|---|---|---|---|---|---|
| 15 | long | 17 942 | 20 937 | 17 931 | **0.429** | 0.116 | 0.429 |
| 15 | short | 15 033 | 18 670 | 15 026 | **0.449** | 0.121 | 0.449 |
| 60 | long | 13 742 | 17 287 | 13 741 | **0.467** | 0.119 | 0.467 |
| 60 | short | 11 486 | 14 894 | 11 486 | **0.513** | 0.106 | 0.513 |
| 240 | long | 10 872 | 14 218 | 10 871 | **0.538** | 0.153 | 0.538 |
| 240 | short | 7 397 | 10 663 | 7 396 | **0.440** | 0.112 | 0.440 |

Hybrid frac 0.10 numbers below for comparison:

**HYBRID, frac = 0.10 (previous run):**

| tf | dir | inzone nc | inzone cb | ∩ | reach nc | reach cb | reach ∩ |
|---|---|---|---|---|---|---|---|
| 15 | long | 19 835 | 20 937 | 18 812 | **0.426** | 0.116 | 0.432 |
| 15 | short | 16 743 | 18 670 | 15 854 | **0.448** | 0.121 | 0.454 |
| 60 | long | 15 256 | 17 287 | 14 741 | **0.463** | 0.119 | 0.468 |
| 60 | short | 12 580 | 14 894 | 12 200 | **0.511** | 0.106 | 0.515 |
| 240 | long | 11 997 | 14 218 | 11 753 | **0.534** | 0.153 | 0.537 |
| 240 | short | 8 236 | 10 663 | 7 966 | **0.440** | 0.112 | 0.443 |

Reading: anchoring the zone to the closed SL pulls the nc zone back to closed-zone
geometry — ~90 % of nc-flagged minutes are also cb-flagged (the intersection ≈ the nc set),
and counts return to the closed zone's near-unconditional regime. Reach roughly 4×'s the
closed baseline, but mostly because the target moved nearer (nc bound tracks the running
extreme), not because entry selection improved. Selectivity — the property the pure-nc
zones below had — is gone; what remains is a tighter, fresher target on essentially the
same entries. Realized-R with fees, not reach, has to arbitrate between these variants.

Earlier variants — pure nc space (both sides from the forming prediction),
`zone = cbnc_low + frac·span` (long):

**frac = 0.10 (pure nc):**

| tf | dir | inzone nc | inzone cb | ∩ | reach nc | reach cb | reach ∩ |
|---|---|---|---|---|---|---|---|
| 15 | long | 6 797 | 20 937 | 2 685 | **0.269** | 0.116 | 0.264 |
| 15 | short | 7 517 | 18 670 | 2 861 | **0.274** | 0.121 | 0.267 |
| 60 | long | 1 592 | 17 287 | 413 | **0.294** | 0.119 | 0.293 |
| 60 | short | 1 089 | 14 894 | 297 | **0.310** | 0.106 | 0.249 |
| 240 | long | 465 | 14 218 | 219 | 0.187 | 0.153 | **0.297** |
| 240 | short | 189 | 10 663 | 26 | **0.407** | 0.112 | 0.346 (n=26) |

**frac = 0.05 (first run):**

| tf | dir | inzone nc | inzone cb | ∩ | reach nc | reach cb | reach ∩ |
|---|---|---|---|---|---|---|---|
| 15 | long | 4 470 | 20 937 | 2 054 | **0.258** | 0.116 | 0.255 |
| 15 | short | 4 939 | 18 670 | 2 197 | **0.262** | 0.121 | 0.255 |
| 60 | long | 825 | 17 287 | 268 | **0.273** | 0.119 | 0.272 |
| 60 | short | 541 | 14 894 | 177 | **0.299** | 0.106 | 0.237 |
| 240 | long | 266 | 14 218 | 130 | 0.150 | 0.153 | **0.277** |
| 240 | short | 58 | 10 663 | 12 | 0.362 | 0.112 | 0.250 (n=12) |

Three observations:

1. **The nc zone is far more selective** — 4–20× fewer flagged minutes than the closed
   zone (which the Round-3 work already showed marks 84–100 % of rows at some settings).
   Because the nc bound tracks the running extreme, its zone only fires when price is
   near the bottom (long) / top (short) of a *currently updating* forward range.
2. **Target-reach roughly doubles**: ~25–30 % of nc-flagged minutes touch the predicted
   opposite bound within the next tf minutes, vs ~11–12 % for the closed zone. tf240 long
   is the exception (n small, and the 240-min horizon dilutes the freshness advantage).
3. **The intersection keeps the nc-level reach rate** at 15/60 while ANDing in the closed
   zone's context; counts get thin at 240 (12–130 rows / 2 months) — read those cells as
   anecdotes, not statistics.

Caveat carried over from Round 3 (`candle_bounds_estimation_results.md`): reach-of-bound is
a *fill/sizing* statistic, not P&L. Level placement cannot create expected value — these
zones select *when*, and whether the selectivity survives fees needs the realized-R harness
(asymmetry-model style) before any trading conclusion.

## Deviations from the stored closed artifact (accepted)

- One fewer warmup candle at the oos2m start (our first valid prediction is one candle
  earlier); the stored extra-warmup rows stay NaN-mismatched by 14–15 rows per tf/side.
- Final row: we emit the fresh prediction; the stored artifact ffilled the stale one.
- `cb_hi_adj`/`cb_lo_adj` (±1-band shift overlay) and `cb_enter_*` (needs the hidden
  NN-breakdown signal) have no nc counterpart — out of scope per plan.

## Follow-ups

- Realized-R validation of the nc zones (entry at flagged minute, fee-aware), the missing
  step between reach-rate and edge.
- Finish the nc zone-fraction sweep — 5 %→10 % already paid (counts up, reach flat/up);
  the curve past 10 % is unmeasured.
- 6–12 month OOS re-test, same reason as every other 2-month-window result in this line.
