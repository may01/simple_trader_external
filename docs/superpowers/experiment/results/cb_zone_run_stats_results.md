# CB zone run-length statistics — results (phase 20)

**Run date:** 2026-10-19
**Code:** main/ branch `cb-zone-run-stats` (worktree `worktrees/cb-zone-run-stats`, off `experimental_imp_2` @ `aca3ef6`), commit `8c5f422` (2026-10-20): `notebooks/zone_profitability/zone_runs.py`, `scripts/cb_zone_run_stats.py`, `tests/unit/data_layer/test_cb_zone_runs.py`, `tests/unit/data_layer/test_cb_zone_run_stats_script.py`.
**Spec:** `specs/2026-10-19-cb-zone-run-stats-design.md`. **Plan:** `plans/impl_2/phase-20-cb-zone-run-stats/`.
**Consumer:** `trade_executor` `CB_STOP_EXPECTED_POINTS` (executor spec `2026-10-19-cb-book-stop-design.md` §10).

## Frozen values

```
CB_STOP_EXPECTED_POINTS=15:2.0/2.0;60:3.0/3.0;240:4.0/4.0
```

Set C = `{tf}_cb_inzone_{side} ∧ {tf}_cb_f_overshoot_{side}`, 2y, **median block length** (minutes in a row inside the zone, blocks bounded by the tf candle). User decisions 2026-10-19: this set (no `cb_f_trend`), the median, 2y only.

Set C is the entry check's *overshoot veto* only, not its firing set: `CbZoneEntryCheck` also vetoes on `cb_f_trend`, needs its own 1-min trade-price MA class (no main/ column), and rule 2 fires on a minute that is not in zone. Set D (`C ∧ cb_f_trend`) gives the same p50 in every cell (table below), so the trend veto does not move the frozen number.

## Run

```
docker compose -p cbrun run --rm ohlc_gen python3 scripts/cb_zone_run_stats.py \
    --train-ind /trader_data_long/train/2y_az_link_usdt/df_with_indicators.pkl \
    --train-cb  /trader_data_long/train/2y_link_usdt/df_with_candle_bounds.pkl \
    --oos-dir   /trader_data_long/train/oos2m_link_usdt \
    --out       /trader_data_long/train/cb_zone_run_stats/full
```

- Host before the run: 15 GB RAM, 4 GB available, 19 GB free disk.
- 2y frame: `(1 052 560, 21)` after the column trim, loaded in 1 s; **peak RSS 727 MB, wall 6 s** (G3). No subset re-pickle was needed; the memory worry in the spec was unfounded for this frame (21 columns after trim).
- `{tf}_ema_25_slope_class` absent on 2y → backfilled (`cb_markers_materialize._ema_slope_columns`); `{tf}_move_class` absent → NaN (unused); **ATR**: `1_atr_14_ma_5` absent on 2y → rebuilt (Wilder ATR14 → MA5, `run_zone_ext.atr1_ma5`'s formula, the series the frozen `EXTDONE_LADDER` was fit against). Only set B reads the ATR; the frozen set C does not.
- oos2m: the materialized `df_with_indicators.pkl` (884 columns); flags read directly.
- Outputs on the volume: `/trader_data_long/train/cb_zone_run_stats/full/cb_zone_run_stats.{json,md}` (and `…/oos_only/` from the G2 run). The md is reproduced below.

## Gates

| Gate | Status | Numbers |
|---|---|---|
| G1 unit | passed | `test_cb_zone_runs.py` 10/10 (`blocks` split by candle boundary and by index gap, `per_candle`, `remaining_given_streak` empty cell `{"n": 0}`, `summarize`) |
| G2 oos2m parity | passed | exact `minutes_total` (Σ block lengths, integer) vs `cb_markers_main_flow_results.md`: raw **20936/18673/17291/14894/14352/10663**, ∧extdone **10056/8134/10587/7178/9474/6553** — equal in every cell (the edge rule drops 0 marker rows on oos2m). **Kernel-path parity** (review finding, 2026-10-20): `scripts/cb_zone_run_stats.py --parity-kernel` runs the 2y path (`masks_from_kernel` on the stored bounds) against the oos2m path (`masks_from_columns` on the stored flags) on oos2m — **24 masks, 0 mismatches**; so the masks behind every 2y number reproduce main/'s own flags. The reviewer also reproduced the frozen numbers independently on the host (block counts identical, e.g. 2y 15 long C 47224 blocks). |
| G3 2y run | passed | peak RSS 727 MB, wall 6 s, no retry |
| G4 2y vs oos2m | passed | set C p50 per cell identical except 60 short (2y 3 vs oos2m 2); no cell differs by more than 50 %. **A vs C at p50 differs by > 1 minute at 15 short (4 vs 2)** and by 1 at 15 long / 60 both sides: the executor's raw streak counter runs longer than a C block when an overshoot veto splits a run — `minutes_left = max(E − streak, 0) + 1` then collapses to the buffer sooner. Accepted (the buffer minute is the floor). |
| G5 results doc | this file | |

Fresh review (2026-10-20): no Critical; Important — the G2 record did not cover the kernel path → `--parity-kernel` added and run (above); minors deferred: `--skip-train` still prints an `n/a` freeze line, duplicate-free json only, commit hash to be filled in after the commit.

Bug found by G2 and fixed before the 2y run: `minutes_of` divided `asi8` by 60·10⁹, but the stored frames carry a `datetime64[ms, UTC]` index (`asi8` in ms), so every block had length 1. Now unit-independent (`test_minutes_of_is_unit_independent`).

## Freeze table

| tf | side | 2y C p50 | oos2m C p50 | 2y A p50 | 2y C mean | 2y D p50 | 2y C first-block p50 | 2y C blocks/candle mean |
|---|---|---|---|---|---|---|---|---|
| 15 | long | 2.0 | 2.0 | 3.0 | 2.5 | 2.0 | 2.0 | 1.6 |
| 15 | short | 2.0 | 2.0 | 4.0 | 2.5 | 2.0 | 2.0 | 1.6 |
| 60 | long | 3.0 | 3.0 | 4.0 | 4.6 | 3.0 | 3.0 | 2.8 |
| 60 | short | 3.0 | 2.0 | 4.0 | 4.6 | 3.0 | 3.0 | 2.8 |
| 240 | long | 4.0 | 4.0 | 4.0 | 9.6 | 4.0 | 3.0 | 4.7 |
| 240 | short | 4.0 | 4.0 | 5.0 | 10.5 | 4.0 | 4.0 | 4.6 |

Reading: a zone block is short — median 2–4 minutes at every tf, while a touched candle holds 1.6–4.7 blocks and 4–48 minutes in zone in all. The mean is pulled far above the median at 240 (9.6 / 10.5 vs 4) by the long tail (p90 25–26, max > 200). The `remaining_given_streak` table (set C, 2y) shows the one-number rule's bias: at tf 15 the median remaining is 1 minute at every streak; at 240 it *grows* with the streak (3 → 10 over s = 1…12) — a block that has lasted longer tends to last longer still. The frozen rule (`E − streak`) is the user's; the table is here for a later switch to a lookup.

## Full report (verbatim, `cb_zone_run_stats.md`)

### 2y — set raw

| tf | side | blocks | candles | run mean | p50 | p75 | p90 | max | blocks/candle mean | p50 | min/candle mean | p50 | first blk mean | p50 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 | long | 41541 | 30829 | 5.0 | 3.0 | 8.0 | 12.0 | 15.0 | 1.3 | 1.0 | 6.7 | 6.0 | 5.4 | 4.0 |
| 15 | short | 42830 | 31986 | 5.1 | 4.0 | 8.0 | 12.0 | 15.0 | 1.3 | 1.0 | 6.8 | 6.0 | 5.5 | 4.0 |
| 60 | long | 15671 | 7476 | 9.9 | 4.0 | 12.0 | 30.0 | 60.0 | 2.1 | 2.0 | 20.8 | 17.0 | 10.9 | 4.0 |
| 60 | short | 16296 | 7739 | 10.4 | 4.0 | 13.0 | 31.0 | 60.0 | 2.1 | 2.0 | 21.9 | 19.0 | 11.7 | 4.0 |
| 240 | long | 6518 | 1833 | 19.5 | 4.0 | 15.0 | 57.0 | 240.0 | 3.6 | 3.0 | 69.2 | 49.0 | 21.0 | 4.0 |
| 240 | short | 6722 | 1935 | 21.8 | 5.0 | 18.0 | 71.0 | 238.0 | 3.5 | 3.0 | 75.8 | 58.0 | 26.4 | 5.0 |

### 2y — set extdone

| tf | side | blocks | candles | run mean | p50 | p75 | p90 | max | blocks/candle mean | p50 | min/candle mean | p50 | first blk mean | p50 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 | long | 30884 | 22136 | 2.7 | 2.0 | 4.0 | 6.0 | 15.0 | 1.4 | 1.0 | 3.7 | 3.0 | 3.0 | 2.0 |
| 15 | short | 31538 | 22146 | 2.6 | 2.0 | 3.0 | 6.0 | 15.0 | 1.4 | 1.0 | 3.7 | 3.0 | 3.0 | 2.0 |
| 60 | long | 14176 | 6129 | 6.0 | 3.0 | 7.0 | 16.0 | 57.0 | 2.3 | 2.0 | 13.9 | 11.0 | 7.1 | 3.0 |
| 60 | short | 13859 | 5802 | 5.2 | 3.0 | 6.0 | 13.0 | 59.0 | 2.4 | 2.0 | 12.4 | 9.0 | 6.6 | 3.0 |
| 240 | long | 5493 | 1630 | 14.6 | 4.0 | 12.0 | 41.0 | 183.0 | 3.4 | 3.0 | 49.1 | 33.0 | 16.8 | 3.0 |
| 240 | short | 5624 | 1708 | 16.5 | 4.0 | 14.0 | 49.0 | 201.0 | 3.3 | 3.0 | 54.2 | 39.0 | 21.0 | 4.5 |

### 2y — set overshoot (C, frozen)

| tf | side | blocks | candles | run mean | p50 | p75 | p90 | max | blocks/candle mean | p50 | min/candle mean | p50 | first blk mean | p50 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 | long | 47224 | 29529 | 2.5 | 2.0 | 3.0 | 5.0 | 15.0 | 1.6 | 1.0 | 4.0 | 3.0 | 2.7 | 2.0 |
| 15 | short | 48392 | 30493 | 2.5 | 2.0 | 3.0 | 5.0 | 15.0 | 1.6 | 1.0 | 4.0 | 3.0 | 2.7 | 2.0 |
| 60 | long | 20512 | 7417 | 4.6 | 3.0 | 6.0 | 11.0 | 51.0 | 2.8 | 2.0 | 12.7 | 10.0 | 4.6 | 3.0 |
| 60 | short | 21253 | 7673 | 4.6 | 3.0 | 6.0 | 10.0 | 57.0 | 2.8 | 2.0 | 12.8 | 10.0 | 4.7 | 3.0 |
| 240 | long | 8541 | 1830 | 9.6 | 4.0 | 11.0 | 25.0 | 218.0 | 4.7 | 4.0 | 44.9 | 31.0 | 7.9 | 3.0 |
| 240 | short | 8905 | 1928 | 10.5 | 4.0 | 12.0 | 26.0 | 213.0 | 4.6 | 4.0 | 48.4 | 35.0 | 10.4 | 4.0 |

(More blocks than set raw: a vetoed minute inside a raw run splits it.)

### 2y — set entry (D, reported only)

| tf | side | blocks | candles | run mean | p50 | p75 | p90 | max | blocks/candle mean | p50 | min/candle mean | p50 | first blk mean | p50 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 | long | 34529 | 21626 | 2.6 | 2.0 | 3.0 | 5.0 | 15.0 | 1.6 | 1.0 | 4.1 | 3.0 | 2.7 | 2.0 |
| 15 | short | 35919 | 22698 | 2.6 | 2.0 | 3.0 | 5.0 | 15.0 | 1.6 | 1.0 | 4.1 | 3.0 | 2.7 | 2.0 |
| 60 | long | 13962 | 5083 | 4.6 | 3.0 | 6.0 | 11.0 | 50.0 | 2.7 | 2.0 | 12.7 | 10.0 | 4.7 | 3.0 |
| 60 | short | 14802 | 5446 | 4.8 | 3.0 | 6.0 | 11.0 | 57.0 | 2.7 | 2.0 | 13.0 | 10.0 | 4.9 | 3.0 |
| 240 | long | 5661 | 1189 | 9.3 | 4.0 | 10.0 | 24.0 | 218.0 | 4.8 | 4.0 | 44.2 | 31.0 | 8.0 | 3.0 |
| 240 | short | 6079 | 1338 | 11.0 | 4.0 | 12.0 | 28.0 | 213.0 | 4.5 | 4.0 | 49.8 | 34.5 | 11.1 | 4.0 |

### 2y — remaining given streak, set overshoot (p50 / n)

| tf | side | s=1 | s=2 | s=3 | s=4 | s=5 | s=6 | s=7 | s=8 | s=9 | s=10 | s=11 | s=12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 | long | 1.0 / 47224 | 1.0 / 27505 | 1.0 / 16412 | 1.0 / 10205 | 1.0 / 6483 | 1.0 / 4112 | 1.0 / 2719 | 1.0 / 1769 | 1.0 / 1164 | 1.0 / 701 | 1.0 / 444 | 1.0 / 270 |
| 15 | short | 1.0 / 48392 | 1.0 / 28760 | 1.0 / 17015 | 1.0 / 10556 | 1.0 / 6602 | 1.0 / 4212 | 1.0 / 2689 | 1.0 / 1756 | 1.0 / 1132 | 1.0 / 693 | 1.0 / 421 | 1.0 / 271 |
| 60 | long | 2.0 / 20512 | 2.0 / 14763 | 2.0 / 10868 | 3.0 / 8426 | 3.0 / 6647 | 3.0 / 5374 | 3.0 / 4369 | 3.0 / 3629 | 3.0 / 3000 | 3.0 / 2483 | 4.0 / 2068 | 4.0 / 1761 |
| 60 | short | 2.0 / 21253 | 2.0 / 15400 | 2.0 / 11491 | 3.0 / 8908 | 3.0 / 7086 | 3.0 / 5729 | 3.0 / 4599 | 3.0 / 3786 | 3.0 / 3105 | 4.0 / 2567 | 4.0 / 2103 | 4.0 / 1793 |
| 240 | long | 3.0 / 8541 | 4.0 / 6566 | 5.0 / 5291 | 6.0 / 4494 | 7.0 / 3923 | 7.0 / 3504 | 8.0 / 3155 | 8.0 / 2840 | 9.0 / 2566 | 9.0 / 2347 | 10.0 / 2160 | 10.0 / 1985 |
| 240 | short | 3.0 / 8905 | 4.0 / 6871 | 6.0 / 5615 | 7.0 / 4812 | 7.0 / 4283 | 8.0 / 3811 | 8.0 / 3424 | 9.0 / 3089 | 10.0 / 2816 | 10.0 / 2614 | 10.0 / 2443 | 10.0 / 2266 |

### oos2m — set raw

| tf | side | blocks | candles | run mean | p50 | p75 | p90 | max | blocks/candle mean | p50 | min/candle mean | p50 | first blk mean | p50 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 | long | 4003 | 2908 | 5.2 | 4.0 | 8.0 | 13.0 | 15.0 | 1.4 | 1.0 | 7.2 | 7.0 | 5.8 | 4.0 |
| 15 | short | 3644 | 2672 | 5.1 | 3.0 | 8.0 | 12.0 | 15.0 | 1.4 | 1.0 | 7.0 | 7.0 | 5.6 | 4.0 |
| 60 | long | 1612 | 710 | 10.7 | 4.0 | 14.0 | 32.0 | 60.0 | 2.3 | 2.0 | 24.4 | 22.0 | 12.3 | 4.0 |
| 60 | short | 1383 | 659 | 10.8 | 4.0 | 14.0 | 31.8 | 59.0 | 2.1 | 2.0 | 22.6 | 19.0 | 12.6 | 5.0 |
| 240 | long | 691 | 179 | 20.8 | 5.0 | 17.0 | 63.0 | 235.0 | 3.9 | 3.0 | 80.2 | 62.0 | 22.7 | 4.0 |
| 240 | short | 521 | 156 | 20.5 | 4.0 | 16.0 | 57.0 | 228.0 | 3.3 | 3.0 | 68.4 | 49.5 | 21.9 | 3.0 |

### oos2m — set extdone

| tf | side | blocks | candles | run mean | p50 | p75 | p90 | max | blocks/candle mean | p50 | min/candle mean | p50 | first blk mean | p50 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 | long | 3344 | 2335 | 3.0 | 2.0 | 4.0 | 6.0 | 15.0 | 1.4 | 1.0 | 4.3 | 4.0 | 3.5 | 3.0 |
| 15 | short | 3019 | 2065 | 2.7 | 2.0 | 4.0 | 6.0 | 15.0 | 1.5 | 1.0 | 3.9 | 3.0 | 3.1 | 2.0 |
| 60 | long | 1520 | 629 | 7.0 | 3.0 | 9.0 | 19.0 | 52.0 | 2.4 | 2.0 | 16.8 | 13.0 | 8.6 | 4.0 |
| 60 | short | 1298 | 553 | 5.5 | 3.0 | 6.0 | 15.0 | 43.0 | 2.3 | 2.0 | 13.0 | 10.0 | 7.3 | 3.0 |
| 240 | long | 629 | 161 | 15.1 | 4.0 | 13.0 | 48.2 | 174.0 | 3.9 | 3.0 | 58.8 | 46.0 | 18.6 | 4.0 |
| 240 | short | 414 | 130 | 15.8 | 4.0 | 14.0 | 49.4 | 167.0 | 3.2 | 3.0 | 50.4 | 38.5 | 17.8 | 3.5 |

### oos2m — set overshoot (C)

| tf | side | blocks | candles | run mean | p50 | p75 | p90 | max | blocks/candle mean | p50 | min/candle mean | p50 | first blk mean | p50 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 | long | 4614 | 2759 | 2.2 | 2.0 | 3.0 | 4.0 | 14.0 | 1.7 | 1.0 | 3.7 | 3.0 | 2.3 | 2.0 |
| 15 | short | 4167 | 2489 | 2.0 | 2.0 | 2.0 | 4.0 | 15.0 | 1.7 | 1.0 | 3.3 | 3.0 | 2.0 | 2.0 |
| 60 | long | 2197 | 708 | 4.0 | 3.0 | 5.0 | 9.0 | 49.0 | 3.1 | 3.0 | 12.5 | 11.0 | 4.1 | 3.0 |
| 60 | short | 1908 | 653 | 3.6 | 2.0 | 5.0 | 8.0 | 27.0 | 2.9 | 2.0 | 10.4 | 9.0 | 3.5 | 2.0 |
| 240 | long | 930 | 178 | 8.8 | 4.0 | 10.0 | 22.0 | 142.0 | 5.2 | 4.5 | 45.7 | 35.5 | 8.1 | 3.0 |
| 240 | short | 747 | 155 | 7.3 | 4.0 | 9.0 | 19.0 | 99.0 | 4.8 | 4.0 | 35.3 | 28.0 | 5.5 | 3.0 |

### oos2m — set entry (D)

| tf | side | blocks | candles | run mean | p50 | p75 | p90 | max | blocks/candle mean | p50 | min/candle mean | p50 | first blk mean | p50 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 | long | 2830 | 1710 | 2.2 | 2.0 | 3.0 | 4.0 | 14.0 | 1.7 | 1.0 | 3.7 | 3.0 | 2.3 | 2.0 |
| 15 | short | 2800 | 1655 | 2.0 | 1.0 | 2.0 | 4.0 | 15.0 | 1.7 | 1.0 | 3.3 | 3.0 | 2.0 | 1.0 |
| 60 | long | 1260 | 417 | 4.2 | 3.0 | 5.0 | 10.0 | 31.0 | 3.0 | 3.0 | 12.7 | 11.0 | 4.3 | 2.0 |
| 60 | short | 1265 | 428 | 3.5 | 2.0 | 5.0 | 8.0 | 27.0 | 3.0 | 3.0 | 10.4 | 9.0 | 3.3 | 2.0 |
| 240 | long | 456 | 84 | 9.1 | 4.0 | 10.0 | 22.0 | 142.0 | 5.4 | 5.0 | 49.5 | 41.5 | 8.1 | 3.0 |
| 240 | short | 514 | 108 | 7.4 | 4.0 | 10.0 | 19.0 | 99.0 | 4.8 | 4.0 | 35.4 | 28.0 | 5.6 | 2.5 |

### oos2m — remaining given streak, set overshoot (p50 / n)

| tf | side | s=1 | s=2 | s=3 | s=4 | s=5 | s=6 | s=7 | s=8 | s=9 | s=10 | s=11 | s=12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 | long | 1.0 / 4614 | 1.0 / 2512 | 1.0 / 1348 | 1.0 / 735 | 1.0 / 432 | 1.0 / 232 | 1.0 / 132 | 1.0 / 89 | 1.0 / 60 | 1.0 / 34 | 1.0 / 20 | 1.0 / 14 |
| 15 | short | 1.0 / 4167 | 0.0 / 2092 | 0.0 / 984 | 1.0 / 482 | 0.0 / 244 | 1.0 / 120 | 0.0 / 61 | 0.0 / 30 | 0.0 / 12 | 2.0 / 4 | 3.5 / 2 | 2.5 / 2 |
| 60 | long | 2.0 / 2197 | 2.0 / 1597 | 2.0 / 1151 | 2.0 / 829 | 2.0 / 614 | 3.0 / 488 | 3.0 / 382 | 3.0 / 298 | 2.0 / 251 | 3.0 / 195 | 3.0 / 152 | 3.0 / 120 |
| 60 | short | 1.0 / 1908 | 1.0 / 1381 | 2.0 / 950 | 2.0 / 662 | 2.0 / 492 | 2.0 / 348 | 2.0 / 260 | 2.0 / 198 | 2.0 / 149 | 2.0 / 103 | 2.0 / 78 | 2.0 / 57 |
| 240 | long | 3.0 / 930 | 4.0 / 715 | 5.0 / 575 | 6.0 / 501 | 6.0 / 432 | 7.0 / 379 | 7.0 / 338 | 7.0 / 304 | 7.0 / 276 | 8.0 / 254 | 9.0 / 225 | 8.0 / 212 |
| 240 | short | 3.0 / 747 | 3.0 / 599 | 4.0 / 480 | 4.0 / 404 | 5.5 / 330 | 6.0 / 286 | 6.0 / 254 | 7.0 / 217 | 7.0 / 199 | 7.0 / 180 | 7.0 / 165 | 7.0 / 150 |

## Hand-over

- Executor plan `2026-10-19-cb-book-stop-plan.md` Task 6 / Task 7 step 4: copy `CB_STOP_EXPECTED_POINTS=15:2.0/2.0;60:3.0/3.0;240:4.0/4.0` into `docker-compose.yml`'s default.
- main/ commit `8c5f422` on `cb-zone-run-stats`; not merged into `experimental_imp_2` yet.
