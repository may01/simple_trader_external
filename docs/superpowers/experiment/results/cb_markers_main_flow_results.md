# CB markers in the main flow — gate report (phase 18)

**Run date:** 2026-10-05 (task 07 materialization + fix round 1 re-run; task 09 G8 replay), summary added 2026-10-06 (task 12)
**Code:** branch `cb-markers-main-flow` (worktree `worktrees/cb-markers-main-flow`), base `757fc1d` plus the phase-18 working tree (tasks 01–12), **uncommitted, awaiting user review** — there is no commit hash for these numbers yet.
**Spec:** `specs/2026-10-05-cb-markers-main-flow-design.md`

## Gate summary (G1–G10)

| Gate | Status | Numbers / note |
|---|---|---|
| G1 model export | passed | 6/6; `band_pct` rel ≤ 2.9e-16 (< 1e-3); numpy vs sklearn max diff 0.0 (< 1e-12). Run in the `ohlc_gen` container with scikit-learn in a throwaway target dir. Table below. |
| G2 closed bounds | passed | max rel ≤ 1.21e-15 on oos2m |
| G3 closed zone / marker | passed | 0 inzone mismatches in the mask; off-mask rows all warm-up candle / final row |
| G4 forming bounds | passed | max rel ≤ 9.99e-16 |
| G4 hybrid | passed (kernel parity at the sidecar's shrink 0.35) + WARN | sidecar built with `tgt_shrink_pct = 0.35`, production `TGT_SHRINK_PCT = 0.15` (ruling R1) |
| G5 extdone | passed | G5a 0 mismatches; G5b P(hold) 0.938 / 0.936 / 0.951 / 0.952 / 0.931 / 0.955; G5c 0 mismatches |
| G6 filter flags | passed | unit tests (`test_cb_kernel_extdone.py`, 23 new tests in task 04) |
| G7 chunked == single-pass | passed on synthetic inputs only | 114 cols × 5,760 rows, max diff 0.0; materialize == prep on a small prepared frame (unit test). Not run on a real dataset |
| G8 live parity | measured; thresholds **proposed, not agreed** | `cb_inzone_*` mismatch 0; worst bool 0.0017 (1/600, `15_cbnc_inzone_long` / `15_cbx_inzone_long`); float max rel ≤ 5.9e-5; `update` mean 81 / p95 135 / max 249 ms vs 50 ms target — **not met** |
| G9 `WideDataPoint.get` | passed (unit tests) | real-dataset `simulate` smoke **not run**; reports vs `.precb_bak` not compared |
| G10 broadcast dry run | **not run** | user-gated live run; see last section |

**Final review fixes (2026-10-06).** (1) Live: an unusable tf writes NaN in all its columns (bools included; was `0.0`, which was published as a change on every candle-boundary fetch skew). (2) Broadcast: the 30 s heartbeat publishes the whole allowlist as before; an `on_change` flip publishes only the changed readings immediately and does not reset the heartbeat. (3) Live stores only finite-bound forming predictions, so live `cbnc_*_std` is NaN wherever the live bound is NaN; prep's `_std` can be finite there in feature warm-up (known asymmetry, outside the G8 window). G8 replay re-run after the fixes (`cb_live_parity.py --minutes 600`, oos2m): per-column table identical to the one below (114/114 rows), worst bool 0.0017, worst float max rel 5.899e-5; `update` mean 80.1 / p95 129.8 / max 218.1 ms (timing noise vs 81 / 135 / 249).

### G1 — model export (task 01, verbatim)

```
15_high  n_train=  70157 band_pct=0.308983004374 stored=0.308983004374 band_rel=0.000e+00 max_pred_diff=0.000e+00 OK
15_low   n_train=  70157 band_pct=0.382271504310 stored=0.382271504310 band_rel=2.904e-16 max_pred_diff=0.000e+00 OK
60_high  n_train=  17529 band_pct=0.630716503040 stored=0.630716503040 band_rel=0.000e+00 max_pred_diff=0.000e+00 OK
60_low   n_train=  17529 band_pct=0.765995452440 stored=0.765995452440 band_rel=0.000e+00 max_pred_diff=0.000e+00 OK
240_high n_train=   4373 band_pct=1.268180937382 stored=1.268180937382 band_rel=1.751e-16 max_pred_diff=0.000e+00 OK
240_low  n_train=   4373 band_pct=1.515168346362 stored=1.515168346362 band_rel=1.465e-16 max_pred_diff=0.000e+00 OK
```

max_pred_diff is exactly 0: the numpy formula reproduces sklearn's operation order (subtract, divide, dot, add).

## oos2m materialization and G2–G5 (task 07)

**Dataset:** `/trader_data_long/train/oos2m_link_usdt/df_with_indicators.pkl` (LINK/USDT, 2025-01-01 → 2025-03-01, 84,961 rows, no gaps in the index).
**Materialized in place:** 752 → 872 columns (114 CB columns + 6 EMA backfill columns).
- One-time hard-link backup `df_with_indicators.pkl.precb_bak`: 490,543,881 bytes, equal to the original.
- The 752 existing columns are identical to the backup (`assert_frame_equal`).
- A second `materialize` on the result gives an identical frame.

**Sidecars compared (not modified):** `df_with_candle_bounds.pkl`, `df_with_candle_bounds_nc.pkl`, `df_with_ext_done.pkl`.

### Verdict

`cb_markers_validate.py` **exit code 0**: 249 checks PASS, 0 FAIL, plus 1 WARN, which is not gating.

**Edge-delta rule (enforced by the script).** Two kinds of rows are checked against it:
- rows where exactly one side is NaN, and
- bool mismatches outside the comparison mask.

Each such row must lie in the leading warm-up candle of its tf, or be the final row. Otherwise the check fails. On oos2m every such row satisfies the rule. The ours-only-valid totals are exactly one candle: 15 / 60 / 240 rows. Rows where the stored value is valid and ours is NaN: 0 everywhere.

| Gate | Result | Numbers |
|---|---|---|
| G2 closed bounds `cb_{side}`, `_up`, `_dn` | PASS | max rel ≤ 1.21e-15 |
| G3 `cb_zone_*` (G2 row mask), `cb_inzone_*` | PASS | max rel ≤ 1.20e-15; 0 inzone mismatches in the mask. Off-mask mismatches (1 / 3 / 4 / 0 / 134 / 0) are all in the warm-up candle or the final row |
| G4 `cbnc_{side}`, `_up`, `_dn` vs sidecar | PASS | max rel ≤ 9.99e-16 |
| G4 hybrid (`cbnc_tgt`, `cbnc_zone`, `cbnc_inzone`, `cbx_inzone`) | PASS (kernel parity) + **WARN** | Details below the table |
| G5a sticky reduction of `kernel.extdone(…, LADDER_OOS, by_rows=True)` vs stored | PASS | 0 mismatches on all 6 cells |
| G5b P(hold \| first True minute), 2y ladder, per-minute state | PASS | 0.938 / 0.936 / 0.951 / 0.952 / 0.931 / 0.955, equal to the reference to 3 decimals |
| G5c materialized `extdone_*`, `_lvl` == `kernel.extdone(EXTDONE_LADDER)` | PASS | 0 mismatches on all 12 columns |

G4 hybrid details:
- The sidecar meta records `tgt_shrink_pct = 0.35`; production uses `TGT_SHRINK_PCT = 0.15`.
- Under ruling R1 the sidecar is a stale reference for these columns. The materialized hybrid columns are **not comparable** to it, and the script prints that as a WARN.
- What is gated instead:
  - The materialized columns equal the kernel recomputed at 0.15 (identical).
  - The kernel recomputed at 0.35 reproduces the sidecar: max rel ≤ 1.2e-15, 0 mismatches.
- Measured directly against the sidecar, the materialized 0.15 columns differ: tgt rel 2.0e-3, zone ~1.1e-4, 618–7,828 inzone mismatches per cell. That is first-run output, kept below for the record.
- At 0.15 there are roughly twice as many 15 m hybrid markers: cbnc_inzone_long 14,261 vs 6,433 at 0.35.

### Notes

- **`cb_f_extdone` is measured for the non-sticky per-minute state.** Its effect is therefore not the ~60 % of zone minutes removed in `extdone_zone_filter_results.md` §2, which was measured with the sticky state and the oos2m-picked ladder.

  | tf | cb_inzone minutes kept by `cb_f_extdone` (long / short) | removed | minutes with `extdone` True (high / low) |
  |---|---|---|---|
  | 15 m | 48 % / 44 % | 52 % / 56 % | 22.3 % / 21.7 % |
  | 60 m | 61 % / 48 % | 39 % / 52 % | 14.2 % / 15.0 % |
  | 240 m | 66 % / 61 % | 34 % / 39 % | 11.7 % / 11.3 % |
- **EMA backfill (ruling R2).**
  - `ema_25_diff_prc` and `ema_25_slope_class` were absent and were backfilled.
  - The plan's formula `to_rows(closed ema_25)` does not equal the field output once a tf has more than `INDICATOR_WINDOW_ROWS` (105) closed candles:
    - The field's previous-candle EMA is a talib EMA over the 104 closed candles of its slice.
    - The stored closed `ema_25` uses 105 candles.
    - talib seeds each window on its first 25 values, so the two windows give different values.
  - The script therefore recomputes the 104-candle window EMA per closed candle wherever the frame holds it. That matches the field to rtol 1e-9 on a freshly prepared frame.
  - On oos2m, the plan formula vs the implemented one differ by up to 8.7e-4 / 1.4e-3 / 2.3e-3 %-pt, with 45 / 63 / 58 class flips (15 / 60 / 240).
- **Limitation: backfill approximation window (oos2m).** In the first 103 closed candles of each tf inside the dataset, the true field window reached into the warm-up rows that prep trimmed. The field value cannot be recovered there, and the stored closed `ema_25` (105-candle window) is used instead. Rows before the frame's first close have NaN diff and class 0 (neutral).

  | tf | approximation rows | share | through | NaN rows | exact rows |
  |---|---|---|---|---|---|
  | 15 | 1,545 | 1.82 % | 2025-01-02 01:59 | 15 | 98.16 % |
  | 60 | 6,180 | 7.27 % | 2025-01-05 07:59 | 60 | 92.66 % |
  | 240 | 24,720 | 29.10 % | 2025-01-18 07:59 | 240 | 70.62 % |

  - The error in this window cannot be measured: the field value is not available.
  - Its size is of the order of the one-candle seed difference, measured where both values are known: up to 0.9e-3 / 1.4e-3 / 2.3e-3 %-pt.
  - The flip rate in the exact region (45 / 83,401, 63 / 78,721, 58 / 60,001) suggests about 1 / 5 / 24 slope-class flips inside the window. This is an estimate, not a measurement.
  - It affects only `ema_25_slope_class` → `cb_f_trend`. The 240 m figure (29 % of oos2m) is the material one; a full re-prep of oos2m removes it.
- G5b matches exactly because oos2m has no gaps, so wall-clock progress equals row-count progress.

### Validate output (verbatim, fix round 1, exit code 0)

```
[validate] /trader_data_long/train/oos2m_link_usdt/df_with_indicators.pkl shape=(84961, 872) 2025-01-01 00:00:00+00:00 -> 2025-03-01 00:00:00+00:00
IDX PASS df_with_candle_bounds index == dataset index: 84961 rows
IDX PASS df_with_candle_bounds_nc index == dataset index: 84961 rows
IDX PASS df_with_ext_done index == dataset index: 84961 rows
[validate] non-1-min steps in index: 0
G2 PASS 15_cb_high max_rel: 7.90e-16 (n=84750)
G2 PASS 15_cb_high stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 15_cb_high ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 15)
G2 PASS 15_cb_high_up max_rel: 7.88e-16 (n=84750)
G2 PASS 15_cb_high_up stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 15_cb_high_up ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 15)
G2 PASS 15_cb_high_dn max_rel: 7.93e-16 (n=84750)
G2 PASS 15_cb_high_dn stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 15_cb_high_dn ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 15)
G2 PASS 15_cb_low max_rel: 1.20e-15 (n=84750)
G2 PASS 15_cb_low stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 15_cb_low ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 15)
G2 PASS 15_cb_low_up max_rel: 1.20e-15 (n=84750)
G2 PASS 15_cb_low_up stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 15_cb_low_up ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 15)
G2 PASS 15_cb_low_dn max_rel: 1.21e-15 (n=84750)
G2 PASS 15_cb_low_dn stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 15_cb_low_dn ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 15)
G3 PASS 15_cb_zone_long max_rel: 1.20e-15 (n=84750)
G3 PASS 15_cb_zone_long stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G3 PASS 15_cb_zone_long ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 15)
G3 PASS 15_cb_zone_short max_rel: 7.91e-16 (n=84750)
G3 PASS 15_cb_zone_short stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G3 PASS 15_cb_zone_short ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 15)
G3 PASS 15_cb_inzone_long mismatches: 0 (n=84750, true ours/stored=20936/20936)
G3 PASS 15_cb_inzone_long off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 1)
G3 PASS 15_cb_inzone_short mismatches: 0 (n=84750, true ours/stored=18670/18670)
G3 PASS 15_cb_inzone_short off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 3)
G2 PASS 60_cb_high max_rel: 3.93e-16 (n=84120)
G2 PASS 60_cb_high stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 60_cb_high ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 60)
G2 PASS 60_cb_high_up max_rel: 3.91e-16 (n=84120)
G2 PASS 60_cb_high_up stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 60_cb_high_up ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 60)
G2 PASS 60_cb_high_dn max_rel: 3.96e-16 (n=84120)
G2 PASS 60_cb_high_dn stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 60_cb_high_dn ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 60)
G2 PASS 60_cb_low max_rel: 4.01e-16 (n=84120)
G2 PASS 60_cb_low stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 60_cb_low ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 60)
G2 PASS 60_cb_low_up max_rel: 3.98e-16 (n=84120)
G2 PASS 60_cb_low_up stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 60_cb_low_up ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 60)
G2 PASS 60_cb_low_dn max_rel: 4.04e-16 (n=84120)
G2 PASS 60_cb_low_dn stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 60_cb_low_dn ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 60)
G3 PASS 60_cb_zone_long max_rel: 4.01e-16 (n=84120)
G3 PASS 60_cb_zone_long stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G3 PASS 60_cb_zone_long ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 60)
G3 PASS 60_cb_zone_short max_rel: 3.93e-16 (n=84120)
G3 PASS 60_cb_zone_short stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G3 PASS 60_cb_zone_short ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 60)
G3 PASS 60_cb_inzone_long mismatches: 0 (n=84120, true ours/stored=17287/17287)
G3 PASS 60_cb_inzone_long off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 4)
G3 PASS 60_cb_inzone_short mismatches: 0 (n=84120, true ours/stored=14894/14894)
G3 PASS 60_cb_inzone_short off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 0)
G2 PASS 240_cb_high max_rel: 5.83e-16 (n=81600)
G2 PASS 240_cb_high stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 240_cb_high ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 240)
G2 PASS 240_cb_high_up max_rel: 5.75e-16 (n=81600)
G2 PASS 240_cb_high_up stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 240_cb_high_up ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 240)
G2 PASS 240_cb_high_dn max_rel: 5.90e-16 (n=81600)
G2 PASS 240_cb_high_dn stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 240_cb_high_dn ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 240)
G2 PASS 240_cb_low max_rel: 5.95e-16 (n=81600)
G2 PASS 240_cb_low stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 240_cb_low ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 240)
G2 PASS 240_cb_low_up max_rel: 5.86e-16 (n=81600)
G2 PASS 240_cb_low_up stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 240_cb_low_up ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 240)
G2 PASS 240_cb_low_dn max_rel: 6.04e-16 (n=81600)
G2 PASS 240_cb_low_dn stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G2 PASS 240_cb_low_dn ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 240)
G3 PASS 240_cb_zone_long max_rel: 5.94e-16 (n=81600)
G3 PASS 240_cb_zone_long stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G3 PASS 240_cb_zone_long ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 240)
G3 PASS 240_cb_zone_short max_rel: 5.83e-16 (n=81600)
G3 PASS 240_cb_zone_short stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G3 PASS 240_cb_zone_short ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 240)
G3 PASS 240_cb_inzone_long mismatches: 0 (n=81600, true ours/stored=14218/14218)
G3 PASS 240_cb_inzone_long off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 134)
G3 PASS 240_cb_inzone_short mismatches: 0 (n=81600, true ours/stored=10663/10663)
G3 PASS 240_cb_inzone_short off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 0)
G4 WARN sidecar tgt_shrink_pct=0.35 != main flow TGT_SHRINK_PCT=0.15: the materialized hybrid columns (cbnc_tgt/cbnc_zone/cbnc_inzone/cbx_inzone) are NOT comparable to the sidecar; gating kernel parity recomputed at 0.35
G4 PASS 15_cbnc_high max_rel: 5.05e-16 (n=84779)
G4 PASS 15_cbnc_high stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_high ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_high_up max_rel: 5.16e-16 (n=84779)
G4 PASS 15_cbnc_high_up stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_high_up ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_high_dn max_rel: 5.20e-16 (n=84779)
G4 PASS 15_cbnc_high_dn stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_high_dn ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_low max_rel: 9.95e-16 (n=84779)
G4 PASS 15_cbnc_low stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_low ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_low_up max_rel: 9.91e-16 (n=84779)
G4 PASS 15_cbnc_low_up stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_low_up ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_low_dn max_rel: 9.99e-16 (n=84779)
G4 PASS 15_cbnc_low_dn stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_low_dn ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_tgt_long == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 15_cbnc_tgt_short == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 15_cbnc_zone_long == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 15_cbnc_zone_short == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 15_cbnc_inzone_long == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 15_cbnc_inzone_short == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 15_cbx_inzone_long == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 15_cbx_inzone_short == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 15_cbnc_tgt_long @shrink 0.35 max_rel: 5.07e-16 (n=84779)
G4 PASS 15_cbnc_tgt_long @shrink 0.35 stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_tgt_long @shrink 0.35 ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_tgt_short @shrink 0.35 max_rel: 1.19e-15 (n=84779)
G4 PASS 15_cbnc_tgt_short @shrink 0.35 stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_tgt_short @shrink 0.35 ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_zone_long @shrink 0.35 max_rel: 1.20e-15 (n=84750)
G4 PASS 15_cbnc_zone_long @shrink 0.35 stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_zone_long @shrink 0.35 ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 15)
G4 PASS 15_cbnc_zone_short @shrink 0.35 max_rel: 7.91e-16 (n=84750)
G4 PASS 15_cbnc_zone_short @shrink 0.35 stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 15_cbnc_zone_short @shrink 0.35 ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 15)
G4 PASS 15_cbnc_inzone_long @shrink 0.35 mismatches: 0 (n=84750, true ours/stored=6433/6433)
G4 PASS 15_cbnc_inzone_long @shrink 0.35 off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 0)
G4 PASS 15_cbnc_inzone_short @shrink 0.35 mismatches: 0 (n=84750, true ours/stored=5407/5407)
G4 PASS 15_cbnc_inzone_short @shrink 0.35 off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 1)
G4 PASS 15_cbx_inzone_long @shrink 0.35 mismatches: 0 (n=84750, true ours/stored=6433/6433)
G4 PASS 15_cbx_inzone_long @shrink 0.35 off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 0)
G4 PASS 15_cbx_inzone_short @shrink 0.35 mismatches: 0 (n=84750, true ours/stored=5407/5407)
G4 PASS 15_cbx_inzone_short @shrink 0.35 off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 1)
G4 PASS 60_cbnc_high max_rel: 4.36e-16 (n=84239)
G4 PASS 60_cbnc_high stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_high ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_high_up max_rel: 4.33e-16 (n=84239)
G4 PASS 60_cbnc_high_up stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_high_up ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_high_dn max_rel: 4.38e-16 (n=84239)
G4 PASS 60_cbnc_high_dn stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_high_dn ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_low max_rel: 7.35e-16 (n=84239)
G4 PASS 60_cbnc_low stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_low ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_low_up max_rel: 7.29e-16 (n=84239)
G4 PASS 60_cbnc_low_up stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_low_up ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_low_dn max_rel: 7.40e-16 (n=84239)
G4 PASS 60_cbnc_low_dn stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_low_dn ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_tgt_long == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 60_cbnc_tgt_short == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 60_cbnc_zone_long == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 60_cbnc_zone_short == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 60_cbnc_inzone_long == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 60_cbnc_inzone_short == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 60_cbx_inzone_long == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 60_cbx_inzone_short == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 60_cbnc_tgt_long @shrink 0.35 max_rel: 4.37e-16 (n=84239)
G4 PASS 60_cbnc_tgt_long @shrink 0.35 stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_tgt_long @shrink 0.35 ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_tgt_short @shrink 0.35 max_rel: 8.94e-16 (n=84239)
G4 PASS 60_cbnc_tgt_short @shrink 0.35 stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_tgt_short @shrink 0.35 ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_zone_long @shrink 0.35 max_rel: 4.14e-16 (n=84120)
G4 PASS 60_cbnc_zone_long @shrink 0.35 stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_zone_long @shrink 0.35 ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 60)
G4 PASS 60_cbnc_zone_short @shrink 0.35 max_rel: 4.25e-16 (n=84120)
G4 PASS 60_cbnc_zone_short @shrink 0.35 stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 60_cbnc_zone_short @shrink 0.35 ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 60)
G4 PASS 60_cbnc_inzone_long @shrink 0.35 mismatches: 0 (n=84120, true ours/stored=9573/9573)
G4 PASS 60_cbnc_inzone_long @shrink 0.35 off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 4)
G4 PASS 60_cbnc_inzone_short @shrink 0.35 mismatches: 0 (n=84120, true ours/stored=7685/7685)
G4 PASS 60_cbnc_inzone_short @shrink 0.35 off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 0)
G4 PASS 60_cbx_inzone_long @shrink 0.35 mismatches: 0 (n=84120, true ours/stored=9572/9572)
G4 PASS 60_cbx_inzone_long @shrink 0.35 off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 4)
G4 PASS 60_cbx_inzone_short @shrink 0.35 mismatches: 0 (n=84120, true ours/stored=7685/7685)
G4 PASS 60_cbx_inzone_short @shrink 0.35 off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 0)
G4 PASS 240_cbnc_high max_rel: 0.00e+00 (n=82079)
G4 PASS 240_cbnc_high stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_high ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_high_up max_rel: 0.00e+00 (n=82079)
G4 PASS 240_cbnc_high_up stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_high_up ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_high_dn max_rel: 0.00e+00 (n=82079)
G4 PASS 240_cbnc_high_dn stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_high_dn ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_low max_rel: 0.00e+00 (n=82079)
G4 PASS 240_cbnc_low stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_low ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_low_up max_rel: 0.00e+00 (n=82079)
G4 PASS 240_cbnc_low_up stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_low_up ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_low_dn max_rel: 0.00e+00 (n=82079)
G4 PASS 240_cbnc_low_dn stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_low_dn ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_tgt_long == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 240_cbnc_tgt_short == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 240_cbnc_zone_long == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 240_cbnc_zone_short == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 240_cbnc_inzone_long == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 240_cbnc_inzone_short == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 240_cbx_inzone_long == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 240_cbx_inzone_short == kernel at TGT_SHRINK_PCT=0.15: identical
G4 PASS 240_cbnc_tgt_long @shrink 0.35 max_rel: 0.00e+00 (n=82079)
G4 PASS 240_cbnc_tgt_long @shrink 0.35 stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_tgt_long @shrink 0.35 ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_tgt_short @shrink 0.35 max_rel: 0.00e+00 (n=82079)
G4 PASS 240_cbnc_tgt_short @shrink 0.35 stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_tgt_short @shrink 0.35 ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_zone_long @shrink 0.35 max_rel: 5.95e-16 (n=81600)
G4 PASS 240_cbnc_zone_long @shrink 0.35 stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_zone_long @shrink 0.35 ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 240)
G4 PASS 240_cbnc_zone_short @shrink 0.35 max_rel: 5.83e-16 (n=81600)
G4 PASS 240_cbnc_zone_short @shrink 0.35 stored-valid/ours-NaN outside warm-up candle+final row: 0 (total 0)
G4 PASS 240_cbnc_zone_short @shrink 0.35 ours-valid/stored-NaN outside warm-up candle+final row: 0 (total 240)
G4 PASS 240_cbnc_inzone_long @shrink 0.35 mismatches: 0 (n=81600, true ours/stored=9254/9254)
G4 PASS 240_cbnc_inzone_long @shrink 0.35 off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 73)
G4 PASS 240_cbnc_inzone_short @shrink 0.35 mismatches: 0 (n=81600, true ours/stored=6406/6406)
G4 PASS 240_cbnc_inzone_short @shrink 0.35 off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 0)
G4 PASS 240_cbx_inzone_long @shrink 0.35 mismatches: 0 (n=81600, true ours/stored=9254/9254)
G4 PASS 240_cbx_inzone_long @shrink 0.35 off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 73)
G4 PASS 240_cbx_inzone_short @shrink 0.35 mismatches: 0 (n=81600, true ours/stored=6406/6406)
G4 PASS 240_cbx_inzone_short @shrink 0.35 off-mask mismatches outside warm-up candle+final row: 0 (off-mask total 0)
G5a PASS 15_extdone_high sticky(oos ladder, by_rows) mismatches: 0 (n=84961, true ours/stored=25697/25697)
G5a PASS 15_extdone_low sticky(oos ladder, by_rows) mismatches: 0 (n=84961, true ours/stored=24963/24963)
G5a PASS 60_extdone_high sticky(oos ladder, by_rows) mismatches: 0 (n=84961, true ours/stored=25455/25455)
G5a PASS 60_extdone_low sticky(oos ladder, by_rows) mismatches: 0 (n=84961, true ours/stored=22874/22874)
G5a PASS 240_extdone_high sticky(oos ladder, by_rows) mismatches: 0 (n=84961, true ours/stored=19963/19963)
G5a PASS 240_extdone_low sticky(oos ladder, by_rows) mismatches: 0 (n=84961, true ours/stored=18262/18262)
G5c PASS 15_extdone_high == kernel.extdone(EXTDONE_LADDER): 0 mismatches (n=84961)
G5c PASS 15_extdone_high_lvl == kernel: 0 mismatches
G5c PASS 15_extdone_low == kernel.extdone(EXTDONE_LADDER): 0 mismatches (n=84961)
G5c PASS 15_extdone_low_lvl == kernel: 0 mismatches
G5c PASS 60_extdone_high == kernel.extdone(EXTDONE_LADDER): 0 mismatches (n=84961)
G5c PASS 60_extdone_high_lvl == kernel: 0 mismatches
G5c PASS 60_extdone_low == kernel.extdone(EXTDONE_LADDER): 0 mismatches (n=84961)
G5c PASS 60_extdone_low_lvl == kernel: 0 mismatches
G5c PASS 240_extdone_high == kernel.extdone(EXTDONE_LADDER): 0 mismatches (n=84961)
G5c PASS 240_extdone_high_lvl == kernel: 0 mismatches
G5c PASS 240_extdone_low == kernel.extdone(EXTDONE_LADDER): 0 mismatches (n=84961)
G5c PASS 240_extdone_low_lvl == kernel: 0 mismatches
G5b PASS 15_extdone_high P(hold|first) 2y ladder: 0.938 vs ref 0.938 ±0.01 (n=4025, fires 75% of candles, true minutes 22.3%)
G5b PASS 15_extdone_low P(hold|first) 2y ladder: 0.936 vs ref 0.936 ±0.01 (n=3845, fires 72% of candles, true minutes 21.7%)
G5b PASS 60_extdone_high P(hold|first) 2y ladder: 0.951 vs ref 0.951 ±0.01 (n=968, fires 69% of candles, true minutes 14.2%)
G5b PASS 60_extdone_low P(hold|first) 2y ladder: 0.952 vs ref 0.952 ±0.01 (n=895, fires 64% of candles, true minutes 15.0%)
G5b PASS 240_extdone_high P(hold|first) 2y ladder: 0.931 vs ref 0.931 ±0.01 (n=262, fires 74% of candles, true minutes 11.7%)
G5b PASS 240_extdone_low P(hold|first) 2y ladder: 0.955 vs ref 0.955 ±0.01 (n=246, fires 70% of candles, true minutes 11.3%)

Marker counts (minutes, oos2m):
| tf | dir | cb_inzone | ∧ cb_f_extdone | ∧ cb_f_trend | ∧ cb_f_mcx | cbx_inzone | extdone share |
|---|---|---|---|---|---|---|---|
| 15 | long | 20936 | 10056 (48 %) | 11347 (54 %) | 834 (4 %) | 14258 | extdone_high 22.3 % |
| 15 | short | 18673 | 8134 (44 %) | 11004 (59 %) | 1173 (6 %) | 11708 | extdone_low 21.7 % |
| 60 | long | 17291 | 10587 (61 %) | 8520 (49 %) | 739 (4 %) | 12314 | extdone_high 14.2 % |
| 60 | short | 14894 | 7178 (48 %) | 8741 (59 %) | 939 (6 %) | 10139 | extdone_low 15.0 % |
| 240 | long | 14352 | 9474 (66 %) | 5778 (40 %) | 793 (6 %) | 10374 | extdone_high 11.7 % |
| 240 | short | 10663 | 6553 (61 %) | 6791 (64 %) | 62 (1 %) | 7024 | extdone_low 11.3 % |

[validate] all gates PASS
```

### First-run G4 lines (before ruling R1: hybrid columns compared directly to the 0.35 sidecar)

```
G4 FAIL 15_cbnc_tgt_long max_rel: 2.01e-03 (n=84779, ours-only valid rows=0)
G4 FAIL 15_cbnc_tgt_short max_rel: 1.99e-03 (n=84779, ours-only valid rows=0)
G4 FAIL 15_cbnc_zone_long max_rel: 1.10e-04 (n=84750, ours-only valid rows=15)
G4 FAIL 15_cbnc_zone_short max_rel: 1.04e-04 (n=84750, ours-only valid rows=15)
G4 FAIL 15_cbnc_inzone_long mismatches: 7828 (n=84750, true ours/stored=14261/6433, outside mask=0)
G4 FAIL 15_cbnc_inzone_short mismatches: 6299 (n=84750, true ours/stored=11706/5407, outside mask=3)
G4 FAIL 15_cbx_inzone_long mismatches: 7825 (n=84750, true ours/stored=14258/6433, outside mask=0)
G4 FAIL 15_cbx_inzone_short mismatches: 6298 (n=84750, true ours/stored=11705/5407, outside mask=3)
G4 FAIL 60_cbnc_tgt_long max_rel: 2.01e-03 (n=84239, ours-only valid rows=0)
G4 FAIL 60_cbnc_tgt_short max_rel: 1.99e-03 (n=84239, ours-only valid rows=0)
G4 FAIL 60_cbnc_zone_long max_rel: 1.15e-04 (n=84120, ours-only valid rows=60)
G4 FAIL 60_cbnc_zone_short max_rel: 1.05e-04 (n=84120, ours-only valid rows=60)
G4 FAIL 60_cbnc_inzone_long mismatches: 2738 (n=84120, true ours/stored=12311/9573, outside mask=4)
G4 FAIL 60_cbnc_inzone_short mismatches: 2454 (n=84120, true ours/stored=10139/7685, outside mask=0)
G4 FAIL 60_cbx_inzone_long mismatches: 2738 (n=84120, true ours/stored=12310/9572, outside mask=4)
G4 FAIL 60_cbx_inzone_short mismatches: 2454 (n=84120, true ours/stored=10139/7685, outside mask=0)
G4 FAIL 240_cbnc_tgt_long max_rel: 2.01e-03 (n=82079, ours-only valid rows=0)
G4 FAIL 240_cbnc_tgt_short max_rel: 1.99e-03 (n=82079, ours-only valid rows=0)
G4 FAIL 240_cbnc_zone_long max_rel: 1.24e-04 (n=81600, ours-only valid rows=240)
G4 FAIL 240_cbnc_zone_short max_rel: 1.10e-04 (n=81600, ours-only valid rows=240)
G4 FAIL 240_cbnc_inzone_long mismatches: 1028 (n=81600, true ours/stored=10282/9254, outside mask=92)
G4 FAIL 240_cbnc_inzone_short mismatches: 618 (n=81600, true ours/stored=7024/6406, outside mask=0)
G4 FAIL 240_cbx_inzone_long mismatches: 1028 (n=81600, true ours/stored=10282/9254, outside mask=92)
G4 FAIL 240_cbx_inzone_short mismatches: 618 (n=81600, true ours/stored=7024/6406, outside mask=0)
G4-DIAG sidecar tgt_shrink_pct=0.35 vs main flow TGT_SHRINK_PCT=0.15
G4-DIAG tf15 with shrink 0.35: cbnc_tgt_long max_rel=5.1e-16, cbnc_tgt_short max_rel=1.2e-15, cbnc_zone_long max_rel=1.2e-15, cbnc_zone_short max_rel=7.9e-16, cbnc_inzone_long mism=0, cbnc_inzone_short mism=0, cbx_inzone_long mism=0, cbx_inzone_short mism=0
G4-DIAG tf60 with shrink 0.35: cbnc_tgt_long max_rel=4.4e-16, cbnc_tgt_short max_rel=8.9e-16, cbnc_zone_long max_rel=4.1e-16, cbnc_zone_short max_rel=4.3e-16, cbnc_inzone_long mism=0, cbnc_inzone_short mism=0, cbx_inzone_long mism=0, cbx_inzone_short mism=0
G4-DIAG tf240 with shrink 0.35: cbnc_tgt_long max_rel=0.0e+00, cbnc_tgt_short max_rel=0.0e+00, cbnc_zone_long max_rel=5.9e-16, cbnc_zone_short max_rel=5.8e-16, cbnc_inzone_long mism=0, cbnc_inzone_short mism=0, cbx_inzone_long mism=0, cbx_inzone_short mism=0
```

## Live parity (G8) — task 09

`scripts/cb_live_parity.py --minutes 600` on oos2m (2025-02-28 14:01 .. 2025-03-01 00:00 UTC, 600 ticks, one per minute at the minute's end, plus one warm tick before the window so the held forming bound is set on the first measured minute). Per tick: per-tf frames rebuilt the way live builds them (stored 1-min OHLCV up to the minute → `_resample_to_tf` rule → `tail(120)` → `{tf}_*`, `is_closed = True` → `Indicators.compute`), then `LiveCbStage.update`, then every CB value compared to the prep row. Exit code 0 (report only).

**Thresholds: `MAX_BOOL_MISMATCH_RATE` / `MAX_FLOAT_REL_DIFF` are proposed, not agreed** — both still `None` in the script.

| Measure | Value |
|---|---|
| Bool mismatch, `cb_inzone_*` (all tfs) | 0.0000 |
| Bool mismatch, worst column | 0.0017 (1/600) — `15_cbnc_inzone_long` and, through it, `15_cbx_inzone_long`; every other bool column 0.0000 |
| Float max rel diff, worst column | 5.90e-5 (`15_cbnc_low_dn`); 15: ≤ 5.9e-5, 60: ≤ 9.0e-6, 240: ≤ 1.9e-5; all `_std` columns 0 |
| Float rows finite on one side only | 0 for every column |
| `update` time | fix round 1: mean 81.2 ms, p95 135.3 ms, max 248.9 ms (round 0: mean 220.6, p95 363.3, max 451.5). Target < 50 ms — **not met**, see below |

**Proposed thresholds (not agreed):** `MAX_BOOL_MISMATCH_RATE = 0.005` per column (allows boundary flips of the size seen here, ~3 per 600 minutes); `MAX_FLOAT_REL_DIFF = 2e-4` (≈3.4× the worst measured 5.9e-5).

**Cause of the float differences / the one bool flip.** OHLC inputs are identical (rel diff 0 on every tf, forming and closed). Indicator inputs differ slightly (max rel, forming row): `rsi_14` / `rsi_ma8` ≤ 6e-4, `ema_25` ≤ 2e-5, `macd_12_26_9` ≤ 8e-3, `macd_hist_12_26_9` ≤ 2e-2 (0.54 once at 240 on a near-zero value; median ≤ 2.5e-3). Most likely cause (not isolated further): live runs TA-Lib on a 120-candle tail, prep on its `INDICATOR_WINDOW_ROWS = 105` window, so the recursive indicators are seeded differently. Class inputs (`move_class`, `ema_25_slope_class`) match on every tick (mismatch 0). The single `15_cbnc_inzone_long` flip is a boundary case: a mismatch needs `|1_low − zone| / zone` below the zone's live-vs-prep difference (≤ 5.7e-5), and only 5 rows of the window are that close (closest: 21:26, `1_low` 14.73 vs prep zone 14.72980, rel 1.4e-5 — 0.0002 in price, a fifth of the 0.001 tick).

**Update time.** Round 0 ran `compute_cb` on the ~300-row sparse frame every tick (≈220 ms mean). Fix round 1 (task 09 review F2): the closed bounds and the forming-history aggregates of a tf depend only on its closed candles, so the stage caches them per (tf, closed block) and each tick evaluates only the current row through the same kernel functions (`stage.tf_columns`, `kernel.forming_history` / `forming_row_features` split out of `forming_features`; kernel output frames now built from dicts instead of per-column inserts). The CB and input tables above are byte-identical to round 0. Measured on this machine under shared load (load average 2–4): replay mean 81 ms, p95 135 ms; synthetic full frames: cache-hit ticks mean 82 / p95 119 ms, cache-miss ticks (new candle) mean 122 / p95 193 ms. What remains is fixed pandas overhead: ~300 Series operations on one-row frames per tick (6 forming predictions + zones, extdone, filters for 3 tfs). Getting under 50 ms needs a numpy evaluation of the row path, i.e. a second implementation of the kernel maths; per the review ruling this was stopped and reported instead.

**What the replay does not cover:** (a) live candles come from exchange klines at four base intervals (1m / 15m / 1h / 12h), each gap-filled with `resample().ffill()` before resampling to the tf; the replay resamples stored 1-min data; (b) fetch-timing skew between the tf frames of one tick (1m is fetched before 15m and 1h, so around a candle close a tf frame can be one candle ahead of the 1-min frame — the stage then blanks that tf for the tick (all its columns NaN, bools included — final review) and keeps the earlier same-minute forming prediction as the held value, unit-tested only); (c) live's last tick of a minute can precede the minute's final trade. The first ~103 closed candles per tf of oos2m carry a backfilled `ema_25_slope_class` (task 07); the 600-minute window lies outside that range.

### Output (verbatim, warnings stripped; fix round 1 run, exit 0)

```
dataset: /trader_data_long/train/oos2m_link_usdt/df_with_indicators.pkl
window: 2025-02-28 14:01:00+00:00 .. 2025-03-01 00:00:00+00:00 (600 ticks)

== CB columns: live stage vs prep ==
  tf family                 kind      n  mismatch    max_rel    med_rel  one_side
  15 cb_high                float   600            3.858e-05  8.041e-06    0.0000
  15 cb_high_std            float   600            0.000e+00  0.000e+00    0.0000
  15 cb_high_up             float   600            3.847e-05  8.017e-06    0.0000
  15 cb_high_dn             float   600            3.870e-05  8.066e-06    0.0000
  15 cb_low                 float   600            5.847e-05  1.231e-05    0.0000
  15 cb_low_std             float   600            0.000e+00  0.000e+00    0.0000
  15 cb_low_up              float   600            5.824e-05  1.226e-05    0.0000
  15 cb_low_dn              float   600            5.869e-05  1.236e-05    0.0000
  15 cb_zone_long           float   600            5.728e-05  1.209e-05    0.0000
  15 cb_zone_short          float   600            3.955e-05  8.253e-06    0.0000
  15 cb_inzone_long         bool    600    0.0000
  15 cb_inzone_short        bool    600    0.0000
  15 cbnc_high              float   600            3.875e-05  8.034e-06    0.0000
  15 cbnc_high_std          float   600            0.000e+00  0.000e+00    0.0000
  15 cbnc_high_up           float   600            3.863e-05  8.009e-06    0.0000
  15 cbnc_high_dn           float   600            3.887e-05  8.059e-06    0.0000
  15 cbnc_low               float   600            5.876e-05  1.244e-05    0.0000
  15 cbnc_low_std           float   600            0.000e+00  0.000e+00    0.0000
  15 cbnc_low_up            float   600            5.854e-05  1.240e-05    0.0000
  15 cbnc_low_dn            float   600            5.899e-05  1.249e-05    0.0000
  15 cbnc_tgt_long          float   600            3.875e-05  8.034e-06    0.0000
  15 cbnc_tgt_short         float   600            5.876e-05  1.244e-05    0.0000
  15 cbnc_zone_long         float   600            5.729e-05  1.218e-05    0.0000
  15 cbnc_zone_short        float   600            3.955e-05  7.383e-06    0.0000
  15 cbnc_inzone_long       bool    600    0.0017
  15 cbnc_inzone_short      bool    600    0.0000
  15 cbx_inzone_long        bool    600    0.0017
  15 cbx_inzone_short       bool    600    0.0000
  15 extdone_high           bool    600    0.0000
  15 extdone_low            bool    600    0.0000
  15 extdone_high_lvl       float   130            0.000e+00  0.000e+00    0.0000
  15 extdone_low_lvl        float   127            0.000e+00  0.000e+00    0.0000
  15 cb_f_extdone_long      bool    600    0.0000
  15 cb_f_extdone_short     bool    600    0.0000
  15 cb_f_trend_long        bool    600    0.0000
  15 cb_f_trend_short       bool    600    0.0000
  15 cb_f_mcx_long          bool    600    0.0000
  15 cb_f_mcx_short         bool    600    0.0000
  60 cb_high                float   600            8.737e-06  2.513e-06    0.0000
  60 cb_high_std            float   600            0.000e+00  0.000e+00    0.0000
  60 cb_high_up             float   600            8.682e-06  2.497e-06    0.0000
  60 cb_high_dn             float   600            8.792e-06  2.529e-06    0.0000
  60 cb_low                 float   600            8.934e-06  5.611e-06    0.0000
  60 cb_low_std             float   600            0.000e+00  0.000e+00    0.0000
  60 cb_low_up              float   600            8.866e-06  5.568e-06    0.0000
  60 cb_low_dn              float   600            9.003e-06  5.654e-06    0.0000
  60 cb_zone_long           float   600            8.833e-06  5.501e-06    0.0000
  60 cb_zone_short          float   600            8.702e-06  2.060e-06    0.0000
  60 cb_inzone_long         bool    600    0.0000
  60 cb_inzone_short        bool    600    0.0000
  60 cbnc_high              float   600            6.979e-06  2.438e-06    0.0000
  60 cbnc_high_std          float   600            0.000e+00  0.000e+00    0.0000
  60 cbnc_high_up           float   600            6.935e-06  2.422e-06    0.0000
  60 cbnc_high_dn           float   600            7.023e-06  2.453e-06    0.0000
  60 cbnc_low               float   600            8.964e-06  5.585e-06    0.0000
  60 cbnc_low_std           float   600            0.000e+00  0.000e+00    0.0000
  60 cbnc_low_up            float   600            8.895e-06  5.543e-06    0.0000
  60 cbnc_low_dn            float   600            9.033e-06  5.628e-06    0.0000
  60 cbnc_tgt_long          float   600            6.979e-06  2.438e-06    0.0000
  60 cbnc_tgt_short         float   600            8.964e-06  5.585e-06    0.0000
  60 cbnc_zone_long         float   600            8.834e-06  5.424e-06    0.0000
  60 cbnc_zone_short        float   600            8.592e-06  2.063e-06    0.0000
  60 cbnc_inzone_long       bool    600    0.0000
  60 cbnc_inzone_short      bool    600    0.0000
  60 cbx_inzone_long        bool    600    0.0000
  60 cbx_inzone_short       bool    600    0.0000
  60 extdone_high           bool    600    0.0000
  60 extdone_low            bool    600    0.0000
  60 extdone_high_lvl       float    42            0.000e+00  0.000e+00    0.0000
  60 extdone_low_lvl        float   126            0.000e+00  0.000e+00    0.0000
  60 cb_f_extdone_long      bool    600    0.0000
  60 cb_f_extdone_short     bool    600    0.0000
  60 cb_f_trend_long        bool    600    0.0000
  60 cb_f_trend_short       bool    600    0.0000
  60 cb_f_mcx_long          bool    600    0.0000
  60 cb_f_mcx_short         bool    600    0.0000
 240 cb_high                float   600            1.866e-05  1.563e-05    0.0000
 240 cb_high_std            float   600            0.000e+00  0.000e+00    0.0000
 240 cb_high_up             float   600            1.842e-05  1.544e-05    0.0000
 240 cb_high_dn             float   600            1.889e-05  1.583e-05    0.0000
 240 cb_low                 float   600            1.231e-05  9.129e-06    0.0000
 240 cb_low_std             float   600            0.000e+00  0.000e+00    0.0000
 240 cb_low_up              float   600            1.213e-05  8.999e-06    0.0000
 240 cb_low_dn              float   600            1.250e-05  9.263e-06    0.0000
 240 cb_zone_long           float   600            1.264e-05  9.468e-06    0.0000
 240 cb_zone_short          float   600            1.835e-05  1.532e-05    0.0000
 240 cb_inzone_long         bool    600    0.0000
 240 cb_inzone_short        bool    600    0.0000
 240 cbnc_high              float   600            1.562e-05  5.763e-06    0.0000
 240 cbnc_high_std          float   600            0.000e+00  0.000e+00    0.0000
 240 cbnc_high_up           float   600            1.543e-05  5.691e-06    0.0000
 240 cbnc_high_dn           float   600            1.582e-05  5.837e-06    0.0000
 240 cbnc_low               float   600            9.200e-06  5.218e-06    0.0000
 240 cbnc_low_std           float   600            0.000e+00  0.000e+00    0.0000
 240 cbnc_low_up            float   600            9.065e-06  5.139e-06    0.0000
 240 cbnc_low_dn            float   600            9.338e-06  5.298e-06    0.0000
 240 cbnc_tgt_long          float   600            1.562e-05  5.763e-06    0.0000
 240 cbnc_tgt_short         float   600            9.200e-06  5.218e-06    0.0000
 240 cbnc_zone_long         float   600            1.249e-05  8.955e-06    0.0000
 240 cbnc_zone_short        float   600            1.819e-05  1.494e-05    0.0000
 240 cbnc_inzone_long       bool    600    0.0000
 240 cbnc_inzone_short      bool    600    0.0000
 240 cbx_inzone_long        bool    600    0.0000
 240 cbx_inzone_short       bool    600    0.0000
 240 extdone_high           bool    600    0.0000
 240 extdone_low            bool    600    0.0000
 240 extdone_high_lvl       float     0                  nan        nan    0.0000
 240 extdone_low_lvl        float   130            0.000e+00  0.000e+00    0.0000
 240 cb_f_extdone_long      bool    600    0.0000
 240 cb_f_extdone_short     bool    600    0.0000
 240 cb_f_trend_long        bool    600    0.0000
 240 cb_f_trend_short       bool    600    0.0000
 240 cb_f_mcx_long          bool    600    0.0000
 240 cb_f_mcx_short         bool    600    0.0000

== stage inputs: live frames vs prep ==
  tf input                  row      mismatch    max_rel    med_rel
  15 open                   forming            0.000e+00  0.000e+00
  15 open                   closed             0.000e+00  0.000e+00
  15 high                   forming            0.000e+00  0.000e+00
  15 high                   closed             0.000e+00  0.000e+00
  15 low                    forming            0.000e+00  0.000e+00
  15 low                    closed             0.000e+00  0.000e+00
  15 close                  forming            0.000e+00  0.000e+00
  15 close                  closed             0.000e+00  0.000e+00
  15 rsi_14                 forming            4.168e-04  9.952e-05
  15 rsi_14                 closed             3.890e-04  1.045e-04
  15 rsi_ma8                forming            4.777e-04  1.292e-04
  15 rsi_ma8                closed             4.468e-04  1.391e-04
  15 macd_12_26_9           forming            5.404e-03  3.114e-04
  15 macd_12_26_9           closed             5.207e-03  3.102e-04
  15 macd_hist_12_26_9      forming            2.119e-02  9.779e-04
  15 macd_hist_12_26_9      closed             1.658e-02  8.808e-04
  15 ema_25                 forming            1.854e-05  1.979e-06
  15 ema_25                 closed             1.780e-05  1.866e-06
  15 move_class             forming    0.0000
  15 move_class             closed     0.0000
  15 ema_25_slope_class     forming    0.0000
  15 ema_25_slope_class     closed     0.0000
  60 open                   forming            0.000e+00  0.000e+00
  60 open                   closed             0.000e+00  0.000e+00
  60 high                   forming            0.000e+00  0.000e+00
  60 high                   closed             0.000e+00  0.000e+00
  60 low                    forming            0.000e+00  0.000e+00
  60 low                    closed             0.000e+00  0.000e+00
  60 close                  forming            0.000e+00  0.000e+00
  60 close                  closed             0.000e+00  0.000e+00
  60 rsi_14                 forming            1.508e-04  5.841e-05
  60 rsi_14                 closed             1.315e-04  5.922e-05
  60 rsi_ma8                forming            1.838e-04  9.021e-05
  60 rsi_ma8                closed             1.779e-04  8.772e-05
  60 macd_12_26_9           forming            8.063e-03  1.328e-03
  60 macd_12_26_9           closed             6.572e-03  1.230e-03
  60 macd_hist_12_26_9      forming            2.662e-03  5.090e-04
  60 macd_hist_12_26_9      closed             8.746e-03  4.875e-04
  60 ema_25                 forming            9.783e-06  6.834e-06
  60 ema_25                 closed             9.650e-06  7.985e-06
  60 move_class             forming    0.0000
  60 move_class             closed     0.0000
  60 ema_25_slope_class     forming    0.0000
  60 ema_25_slope_class     closed     0.0000
 240 open                   forming            0.000e+00  0.000e+00
 240 open                   closed             0.000e+00  0.000e+00
 240 high                   forming            0.000e+00  0.000e+00
 240 high                   closed             0.000e+00  0.000e+00
 240 low                    forming            0.000e+00  0.000e+00
 240 low                    closed             0.000e+00  0.000e+00
 240 close                  forming            0.000e+00  0.000e+00
 240 close                  closed             0.000e+00  0.000e+00
 240 rsi_14                 forming            3.961e-04  2.794e-04
 240 rsi_14                 closed             3.059e-04  2.814e-04
 240 rsi_ma8                forming            5.998e-04  4.581e-04
 240 rsi_ma8                closed             5.653e-04  3.849e-04
 240 macd_12_26_9           forming            4.472e-04  2.527e-04
 240 macd_12_26_9           closed             3.790e-04  1.358e-04
 240 macd_hist_12_26_9      forming            5.373e-01  2.450e-03
 240 macd_hist_12_26_9      closed             1.158e-02  9.015e-04
 240 ema_25                 forming            1.042e-05  8.235e-06
 240 ema_25                 closed             1.014e-05  4.767e-06
 240 move_class             forming    0.0000
 240 move_class             closed     0.0000
 240 ema_25_slope_class     forming    0.0000
 240 ema_25_slope_class     closed     0.0000

update time ms: mean=81.2 p95=135.3 max=248.9
worst bool mismatch rate=0.0017  worst float max rel diff=5.899e-05
thresholds not agreed yet: report only
```

## MQ broadcast (G10)

Not run (user-gated live dry run). Task 10 code and unit tests are done; the live check on the wire is pending. G10 is NOT passed.

Checklist handed over (task 10): start live as normal on the work branch; run `python3 scripts/e2e_indicator_broadcast_probe.py` or tail the executor's indicator log; confirm the 14 names × 3 tfs arrive with finite values, `cbnc_*` from the second minute on, and a `cb_inzone` flip within ~1 s of the tick. Known gap: a value never published before is not a "change", so the first finite on_change value after start / after NaN waits for the 30 s heartbeat (`executor/TECH_DEBT.md` §17).
