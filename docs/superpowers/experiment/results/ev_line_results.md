# EV line — Results & Conclusion

**Date:** 2026-10-05 (rounds run 2026-10-01 … 10-03) · **Verdict:** partial (approved 2026-10-05) · **Disposition:** branch kept, not merged
**Spec + working log:** [`../ev_line.md`](../ev_line.md) · **Detail for rounds 5–7:**
[`extdone_zone_filter_results.md`](extdone_zone_filter_results.md) · **Plan:** none (interactive session)
**Branch:** `ev-line-experiment` off `zone-profitability` @ `2788110` (predecessor experiment, itself
uncommitted until now — see "Description of changes"). Worktree `worktrees/ev-line-experiment`. Committed as `60def30` (one combined commit, layers A + B; not pushed).
**Data:** train 2y 2023-01-01 → 2024-12-31 (`2y_az_link_usdt`, 1,052,560 min; bounds from
`2y_link_usdt/df_with_candle_bounds.pkl`); OOS oos2m 2025-01-01 → 2025-03-01 (84,961 min; 5,651 /
1,403 / 341 candles at tf 15 / 60 / 240). LINK/USDT.
**Pipeline:** `notebooks/zone_profitability/` — `evlib.py` + drivers `run_ev`, `sweep_ev`, `run_evr`,
`run_cbatr`, `run_extdone`, `fit_extdone_ladder`, `run_zone_ext`, `run_ema_class`, `run_ema_slope`.
Run inside the `simple_trader` image:
`docker run --rm -v <worktree>:/code -v simple_trader_vol_long:/trader_data_long -v <out>:/out -e EV_OUT=/out -e PYTHONPATH=/code -w /code simple_trader python3 notebooks/zone_profitability/<driver>.py`
**Final configuration:** fee 0.1 %/side; EV line s = 1.0σ, t = 0.5σ; ATR zone k = 0.3 × `1_atr_14_ma_5`;
extdone ladder as drawn (picked on oos2m) 15: 4 / 2.5 / 1, 60: 8 / 5 / 3, 240: — / 12 / 8 at progress
25–50 / 50–75 / 75–100 %; **recommended ladder (fit on 2y)** in "Validity gates → Provenance"; EMA
classes x = 0.5.

## Headline conclusion
**Entry placement between the bound bands has no edge.** Every placement rule — Gaussian EV-best,
EV-breakeven, 25 stop/target σ combos, 1,545 empirically replayed (entry, stop, target) cells, six ATR
shifts, the 5 % zone and the raw bound — nets ≈ −0.20 % per fill on oos2m, i.e. gross ≈ 0 and the
round-trip fee is the whole loss (0 of 150 sweep cells net-positive; the 2y-selected empirical rule
won 0 trades in 6 of 6 oos2m cells).
**Two by-products survive as candidates:** (1) the *executed-bound state* — pull-away from the running
extreme ≥ d(progress) 1-min ATRs — with the ladder fit on 2y holds on oos2m at P = 0.93–0.96 against
a progress-only base rate of 0.62–0.83; (2) an ATR-scaled *remaining-extension quantile table* per
(tf, side, progress) whose 2y q75 / q90 cover 0.72–0.89 / 0.87–0.95 of oos2m.
**Not proven:** that either by-product improves realized P&L. The extdone-vetoed zones were never
replayed; the quantile table sizes a stop, it does not locate the extreme. One pair, one 2-month OOS
window.

## The progression
oos2m, net pnl per candle in % (fill rate × pnl per fill), minute replay, S/T as each rule defines:

| tf | side | cb_zone 5 % | cb level | EV best (s1, t0.5) | EV breakeven | empirical-reach (2y argmax) | ATR k = 0.3 | ATR k = 1 |
|---|---|---|---|---|---|---|---|---|
| 15 | long | −0.100 | −0.089 | −0.048 | −0.121 | −0.004 (116 fills, 0 wins) | −0.104 | −0.150 |
| 15 | short | −0.095 | −0.082 | −0.048 | −0.104 | −0.009 (219, 0) | −0.099 | −0.137 |
| 60 | long | −0.102 | −0.105 | −0.070 | −0.146 | −0.010 (43, 0) | −0.095 | −0.125 |
| 60 | short | −0.091 | −0.084 | −0.065 | −0.107 | −0.006 (46, 0) | −0.092 | −0.100 |
| 240 | long | −0.122 | −0.075 | −0.082 | −0.113 | −0.013 (27, 0) | −0.109 | −0.132 |
| 240 | short | −0.078 | +0.002 | −0.050 | −0.014 | −0.020 (17, 0) | −0.072 | −0.090 |

pnl **per fill** is −0.16 … −0.40 % in every cell except two 240-short ones (EV breakeven −0.03 on
166 fills, cb level +0.006 on 134). A smaller loss per candle is always fewer fills, never a better
fill.

State / quantile deliverables (oos2m):

| deliverable | 15 m | 60 m | 240 m |
|---|---|---|---|
| extdone, ladder **fit on 2y**: P(extreme not touched again \| first trigger), high / low | 0.938 / 0.936 | 0.951 / 0.952 | 0.931 / 0.955 |
| … fires in % of candles | 75 / 72 | 69 / 64 | 74 / 70 |
| extdone, ladder picked on oos2m (as drawn) | 0.897 / 0.896 | 0.898 / 0.895 | 0.907 / 0.936 |
| zone minutes removed by the veto | 60 % | 64 % | 62 % |
| vetoed marker is the candle extreme | 18–19 % | 5–6 % | 2 % |
| remaining extension, median / sd (% of price) | 0.16 / 0.37–0.47 | 0.48–0.55 / 0.71–0.84 | 1.0–1.2 / 2.1–2.5 |
| Ridge on market state, r² test (2y → oos2m), long / short | 0.16 / 0.15 | 0.16 / 0.12 | 0.26 / −0.05 |
| 2y quantile table: oos2m coverage of q75 / q90 (nominal .75 / .90) | .76–.82 / .91–.95 | .72–.80 / .90–.94 | .76–.89 / .87–.94 |
| EMA-25 slope classes as quantile conditioner (open): Δ pinball loss, 2y out-of-time / oos2m | −0.09 % / +0.95 % (all tf pooled, x = 0.5) | | |

## Degeneracies found (and what each fix did)
1. **Gaussian independence.** Modelled p_win 0.29–0.41 vs realized win rate 0.05–0.14 (×4); with wider
   stops the model climbs to 0.93 while realized caps at 0.22. A fill at E conditions against reaching
   T (the target was usually hit before the fill). Fix: measure reach after fill on 2y (round 3) →
   measured p_win|fill is ~3× below Gaussian at/beyond the bound; net per fill still −0.20 %.
2. **Empirical-reach argmax → rarest-fill corner.** Selecting by 2y pnl per candle picked a ≤ −1.75σ,
   s = 3σ in all six cells (139–1,248 fills on 2y, win rate 0.2–2.5 %): the least-bad cell is the one
   that almost never trades. Only 24 of 1,545 eligible 2y cells were net-positive per fill, all
   240-long with 150–196 fills carried by open-at-close exits. OOS: 0 wins.
3. **Row-based vs event-based hold probability.** The first extdone table counted every minute of an
   already-done candle and overstated P(hold) by 5–20 points (15 m: 0.93 row-based vs 0.87 at the
   first trigger). Fix: score only the first trigger; ladder re-tuned.
4. **Ladder selected on oos2m.** The drawn ladder was chosen from oos2m counts. Fix: provenance gate
   `fit_extdone_ladder.py` (below) — the 2y fit is stricter and holds higher OOS.
5. **Ridge on small samples.** oos2m-internal 75/25 split at tf 240 (146 candles): r² train 0.60,
   test −2.7. Only the 2y → oos2m fit is reported as the result.
6. **Late-candle bucket.** After the veto the 75–100 % progress bucket holds 9–71 oos2m markers and
   gives inverted class quantiles; excluded from the quantile table.
7. **In-place mask bug (operational).** `mask &= ~veto` on a read-only `to_numpy()` view raised inside
   the viewer; the dashboard swallows exceptions and returned an empty chart. Fixed; noted because
   the silent blank chart is a recurring trap.

## Validity gates
| gate | result |
|---|---|
| **Null floor** | Placement: gross pnl per fill (net + 0.2 %) within ±0.05 % of zero in 21 / 24 base cells — outside: EV-breakeven 60 long −0.08, EV-breakeven 240 short +0.17 (166 fills), cb level 240 short +0.21 (134 fills) — and within [−0.08, +0.02] % for all 25 sweep combos (mean over tf × side) — indistinguishable from "no information". EMA classes: −0.09 % pinball on 2y out-of-time at the chosen x (negative for all 7 x) → below noise. |
| **Base rate** | extdone vs unconditional P(extreme holds) at the same progress: 0.62 / 0.79 (15 m, 50–75 / 75–100 %), 0.64 / 0.83 (60 m), 0.62 / 0.83 (240 m) → state gives 0.94 / 0.94, 0.95–0.97 / 0.95–0.96, — / 0.93–0.96 (2y ladder). Real lift mid-candle, +0.10–0.15 only in the last quarter. Fixed levels: first touch of cb / cb ± σ → 0.04–0.19, *below* base. |
| **Degeneracy** | Six found, listed above; argmax corner (2) and small-n (5, 6) both hit. |
| **Truth ladder** | Model EV/candle +0.02 … +0.13 % (60 / 240 m) → realized replay −0.05 … −0.08 % → gross of fee ≈ 0. Modelled p_win 0.36 → measured-on-2y 0.08–0.18 → oos2m 0.05–0.14. |
| **Feature ablation** | Ridge with the 4 state features only (atr1 %, progress, pull-away, depth) keeps r² 0.09–0.19 of 0.12–0.26: the 15 bound features add ≤ 0.08; `atr1_pct` dominates → scale, not timing. |
| **Look-ahead** | extdone at minute t uses run extreme, `1_close`, `1_atr_14_ma_5` through t only; zone markers and veto read the same row. `{tf}_ema25_cls` / `_slope_z` are shift(1) (last closed candle); only the `ema_25_{rise,fall,neutral}` drawing columns are unshifted (chart-only). Replay is pessimistic: stop counted from the fill minute, target from the next. **Not clean:** 2y bounds are in-sample for the bound models, so 2y-fit rules see slightly tighter bounds than OOS. |
| **Provenance** | Quantile table, EMA mean/std, empirical-reach params, Ridge: fit on 2y, applied unchanged to oos2m. **extdone ladder as drawn: selected on oos2m (fails).** Re-fit on 2y with the same rule (P(hold) ≥ 0.90, ≥ 100 events): 15 high 5 / 2.5 / 1.5, 15 low 4 / 2.5 / 1.5, 60 high 10 / 8 / 4, 60 low 10 / 6 / 4, 240 — / — / 8 → oos2m P(hold) 0.938 / 0.936 / 0.951 / 0.952 / 0.931 / 0.955 (n 4,025 / 3,845 / 968 / 895 / 262 / 246). Veto counts and the quantile table were computed with the oos2m-picked ladder and have not been re-run with the 2y one. EV-line s, t, ATR k = 0.3 and EMA x were user-chosen on oos2m, all inside a null result. |
| **Reproduction** | Vectorized `evlib.replay` vs the reference loop `realized`: max abs diff 0 (tf 15) and 3.6e-15 (tf 240) on all summary stats. atr1 rebuilt from OHLC vs stored `1_atr_14_ma_5`: median relative diff 6.9e-05. Report recomputation of the candle_bounds table from the stored sidecar: r² / coverage match the doc to ≤ 0.01. |

## What generalized vs what did not
**Generalized (2y → oos2m)**
- extdone with the 2y ladder: 0.93–0.96 hold probability at 64–75 % firing rate.
- ATR-scaled extension quantiles per (tf, side, progress): coverage near nominal despite oos2m being
  1.3–1.4× more volatile than 2y.
- The direction of the EMA-slope effect: against-trend markers extend 10–25 % further at q90.

**Did not**
- Any entry placement rule (Gaussian, empirical, ATR-shifted): net ≈ −fee everywhere.
- Gaussian band probabilities as trade probabilities (×3–4 optimistic).
- Fixed predicted levels as exhaustion signals (first touch is continuation).
- Ridge of remaining extension on market state as a location model (r² ≤ 0.26, 240-short negative).

**Open — left for further investigation (user decision 2026-10-05)**
- EMA-25 slope classes (fall / neutral / rise) as a conditioner. Measured so far: the direction is
  right (against-trend markers extend 10–25 % further at q90) but as a 3-class conditioner of the
  extension quantiles it adds ≤ 1.7 % pinball on oos2m and −0.09 % on 2y out-of-time. Not tested:
  as a filter on entries (with-trend only), as a conditioner of extdone / hold probability, other
  EMA lengths, a 2-class with/against-trend split, x other than the ±0.5σ grid. The class is now an
  in-code indicator (`ema_25_slope_class`) so follow-ups read a column instead of a sidecar.

## Description of changes
Branch `ev-line-experiment`, on top of `2788110`. Three layers are present in the tree; only the
second is this experiment.

**A. Predecessor, zone_profitability (2026-08-07, never committed)** — carried because this
experiment builds on its files: `notebooks/zone_profitability/{zplib,run_zp}.py`;
`data.join_zone_profitability`; viewer groups `zp_long` / `zp_short` + `zpzone` / `zptgt` markers;
its hook in `view_full.py`.

**B. This experiment**

| file | change |
|---|---|
| `notebooks/zone_profitability/evlib.py` (new) | `ev_line` (Gaussian EV-optimal entry), `replay` (vectorized minute replay, per-candle or per-row entry), `summarize`, `realized` (reference loop), `candle_id`, `Phi` |
| `…/run_ev.py`, `sweep_ev.py`, `run_evr.py`, `run_cbatr.py` (new) | rounds 1–4 drivers; sidecars `df_with_ev_line`, `_ev_reach`, `_cb_zone_atr` |
| `…/run_extdone.py`, `fit_extdone_ladder.py` (new) | extdone state + sidecar `df_with_ext_done`; 2y-fit ladder gate |
| `…/run_zone_ext.py` (new) | marker → extreme distribution, numpy Ridge, 2y marker rebuild |
| `…/run_ema_class.py`, `run_ema_slope.py` (new) | EMA-25 slope classes × quantiles; slope distribution + sidecar `df_with_ema_slope` |
| `data.py` | `join_ev_line`, `join_ev_reach`, `join_cb_zone_atr`, `join_ext_done`, `join_ema_slope` (absence-safe sidecar joins) |
| `view_full.py` | calls the joins above |
| `frontend/data_viewer.py` | overlay groups `ev_*`, `evr_*`, `cbatr_*`, `extdone_*`, `ema25_cls`, `cb_enter` (NN-breakdown arrows split out of `cb_long/short`); markers `cbatr`, `extdone`; `_ZONE_VETO` (cb zone line + markers blanked by the opposite extdone state); `_MARKER_ONLY_FIELDS`; `_DEFAULT_SUBPLOTS_OFF` + `default_subplots()`; default-off set extended (first load shows `ema`, `ema25_cls`, `cb_long`, `cb_short` and cci / macd / adx / atr / natr) |
| `frontend/history_dashboard.py` | subplot checklist default = `default_subplots()` |
| `indicators/library/trend.py` | `EmaDiffPrcField` → `{tf}_ema_25_diff_prc` = (ema[k] − ema[k−1]) / ema[k−1] · 100 (repo `*_diff_prc` convention; the existing nn_features `ema_25_slope` is a 5-bar OLS slope — different quantity, untouched) |
| `indicators/library/classification.py` | `EMA_SLOPE_STATS` (frozen 2y closed-candle mean / std per tf), `EMA_SLOPE_X = 0.5`, `ema_slope_class()`, `EmaSlopeClassField` → `{tf}_ema_25_slope_class` ∈ {−1 fall, 0 neutral, 1 rise}, tf 15 / 60 / 240, no stats file |
| `indicators/registry.py`, `configs/indicators_config.yaml` | both fields registered and wired (`ema_25` → `ema_25_diff_prc` → `ema_25_slope_class`) |
| `tests/unit/data_layer/test_ema_slope_class.py` (new) | 11 tests: formula, frozen stats, class boundaries, NaN → neutral, registry / config order, no shadowing of the OLS slope |
| `notebooks/candle_bounds_nc/cbnc.py` | sklearn import made lazy (image has no sklearn; feature builders stay importable) |
| `tests/test_phase12_task15_overlay_selection.py` | two assertions updated for `bb_x_20_2` default-off |

**C. Not included** — `run_sltgt.py`, `run_cb_overshoot.py`, `data.join_cb_overshoot`, viewer
`_MARKER_VETO`: a later experiment (`sl-tgt-quantile-experiment`) that imports `run_zone_ext`; left
in `worktrees/zone-profitability`, stripped from this branch's copy of the three shared files.

## Config & artifacts (final state)
- **Sidecars** (oos2m dataset dir, root-owned, written via docker): `df_with_ev_line.pkl`,
  `df_with_ev_reach.pkl`, `df_with_cb_zone_atr.pkl` (k = 0.3), `df_with_ext_done.pkl` (oos2m-picked
  ladder), `df_with_ema_slope.pkl` (x = 0.5, regenerated 2026-10-05 from the in-code constants).
- **Frozen params:** extdone 2y ladder (above); quantile table in
  `extdone_zone_filter_results.md` §3.3; EMA slope mean / std per tf 15: +0.0018 / 0.0886, 60:
  +0.0073 / 0.1736, 240: +0.0296 / 0.3436; empirical-reach (a, s, t) per cell in `../ev_line.md` §7.
- **Run reports** (`ev_line_report`, `ev_sweep`, `ev_reach_*`, `cbatr_report`, `extdone_report`,
  `zone_ext_report`, `ema_class_*`, `ema_slope_report`) were written to the session scratchpad and
  are gone; every table is transcribed in the two docs and each driver regenerates its report.
  `extdone_ladder_2y.{json,md}` is the only one still on disk.
- **Viewer:** `view-full-oos2m` (port 8080) still mounts `worktrees/zone-profitability` (layer C on
  top). Overlay toggles: `ev_long/short`, `evr_long/short`, `cbatr_long/short`,
  `extdone_short/long`, `ema25_cls`, `cb_enter`. The extdone veto applies whenever the sidecar exists.
- **Tests:** `tests/unit/data_layer/test_ema_slope_class.py` 11 / 11. `tests/test_phase12_task15_overlay_selection.py`
  + `tests/test_phase11_nn_viz.py`: 23 pass, 1 fail (`test_targets_always_drawn` — fails at `2788110`
  too, `_TARGET_OVERLAYS` was emptied there). `tests/unit/data_layer` green on its own; run together
  with `test_parallel_indicator_pass.py` / `test_phase09_task02_data_preparer.py` 5 of those fail by
  test-order pollution — identical at `2788110`. No unit tests for the experiment drivers.
- **EMA class in code:** frozen stats tf 15: 0.0018696074 / 0.0885475477, 60: 0.0075861817 /
  0.1736558145, 240: 0.0308328348 / 0.3443346525 (the /prev formula; the experiment tables used
  /current — class agreement 99.95 / 99.94 / 99.79 % on 2y closed candles). `run_ema_slope.py` now
  imports the constants and asserts them against a fresh 2y recompute (rtol 1e-9, passes); the field
  run on oos2m closed candles reproduces the sidecar classes with 0 mismatches (5,664 / 1,416 / 354
  candles). Existing datasets do not carry the two columns until re-prepared — the viewer keeps
  using `df_with_ema_slope.pkl`.
- **Committed:** `60def30` on `ev-line-experiment` (10 modified files, 12 new under `notebooks/zone_profitability/` — of which `zplib.py` and `run_zp.py` are layer A — and 1 new test file).

## Next arbiter
Replay the cb zones **with the extdone veto (2y ladder)** through `evlib.replay`, stop sized from the
q75 / q90 extension table, against the unvetoed 5 % zone on oos2m: if gross pnl per fill stays within
±0.05 % of zero, entry *selection* by candle state is dead as well and the bound bands are only a
risk-sizing tool; if it moves, the veto + quantile stop is the first candidate rule. Before that,
re-run the veto counts and the quantile table with the 2y ladder.
