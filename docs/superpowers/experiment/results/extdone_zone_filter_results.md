# Executed bound (extdone) — detection, cb-zone filtering, remaining-extension quantiles

**Date:** 2026-10-03
**Data:** LINK/USDT. Thresholds and quantiles fit on 2y (`2y_az_link_usdt`, bounds from
`2y_link_usdt/df_with_candle_bounds.pkl`); validated on oos2m (2025-01-01 → 2025-03-01).
**Branch:** `ev-line-experiment` (worktree `worktrees/ev-line-experiment`, commit `60def30`). Decision report: `ev_line_results.md`.
**Code:** `notebooks/zone_profitability/run_extdone.py` (state + sidecar),
`frontend/data_viewer.py` `_ZONE_VETO` (filter), `notebooks/zone_profitability/run_zone_ext.py`
(extension analysis), scratch `quant.py` (quantile table). Working log: `../ev_line.md` §9–10.
**Sidecars (oos2m):** `df_with_ext_done.pkl` — `{tf}_extdone_{high,low}`, `_first`, `_lvl`.

---

## 1. Executed bound: when is the candle's high/low already in?

### 1.1 What does NOT work — levels
First touch of any predicted level is a *continuation* signal, not exhaustion. Measured on
oos2m, P(the running extreme is not touched or exceeded again before the candle closes | the
level was just crossed):

| level crossed | 15 m | 60 m | 240 m |
|---|---|---|---|
| cb −1σ / cb / cb +1σ (closed bound) | 0.15 / 0.15 / 0.19 | 0.08 / 0.09 / 0.10 | 0.06 / 0.07 / 0.04 |
| cbnc (forming-candle bound) | 0.55 | 0.66 | 0.66 |
| unconditional, any minute, by progress 0–25/25–50/50–75/75–100 % | .25/.44/.62/.79 | .25/.47/.64/.83 | .26/.44/.62/.83 |

A fixed level is crossed mid-move; the next minute usually extends it. cbnc only tracks the
progress baseline (+0.06). Where the running extreme sits relative to cb (−1σ … +1σ) barely
changes the odds (0.79 → 0.84 at 15 m).

### 1.2 What works — pull-away × progress
The extreme is "in" when the close has moved away from it by enough 1-min ATRs, and enough of
the candle has elapsed:

```
run_high[t]  = max(1_high) over the candle so far          (run_low: min(1_low))
pull[t]      = (run_high[t] − 1_close[t]) / 1_atr_14_ma_5[t]    (low: (close − run_low)/atr)
progress[t]  = (minute index in candle + 1) / tf
extdone_high[t] = pull[t] >= d(progress[t]),   sticky until the candle closes
```

`d(progress)` is a per-tf ladder: for each progress bucket the smallest grid value whose
**event-based** P(hold | first trigger in that bucket) ≥ 0.90 on oos2m (grid d ∈ {1, 1.5, 2,
2.5, 3, 4, 5, 6, 8, 10, 12}). Row-based conditionals overstate by 5–20 points because they
count every later minute of an already-done candle; the first-trigger event is the honest
number.

| tf | progress < | 25–50 % | 50–75 % | 75–100 % |
|---|---|---|---|---|
| 15 | never (< 25 %) | d = 4.0 | d = 2.5 | d = 1.0 |
| 60 | never (< 25 %) | d = 8.0 | d = 5.0 | d = 3.0 |
| 240 | never (< 50 %) | — | d = 12.0 | d = 8.0 |

Same ladder for high and low.

### 1.3 Results (oos2m, at the first trigger)

| tf | side | fires in % of candles | median progress at trigger | P(hold) 25–50 % | 50–75 % | 75–100 % | overall |
|---|---|---|---|---|---|---|---|
| 15 | high | 87 | 0.80 | 0.95 (n 248) | 0.94 (n 1875) | 0.87 (n 2620) | 0.90 |
| 15 | low | 85 | 0.80 | 0.92 (n 318) | 0.94 (n 1769) | 0.86 (n 2483) | 0.90 |
| 60 | high | 83 | 0.67 | 0.93 (n 70) | 0.90 (n 592) | 0.89 (n 515) | 0.90 |
| 60 | low | 78 | 0.72 | 0.94 (n 68) | 0.91 (n 504) | 0.88 (n 519) | 0.90 |
| 240 | high | 76 | 0.75 | — | 0.91 (n 127) | 0.91 (n 141) | 0.91 |
| 240 | low | 71 | 0.75 | — | 0.93 (n 120) | 0.95 (n 130) | 0.94 |

Trade-off knob: the next grid step (e.g. 15 m 75–100 % d = 1.5) gives 0.96 but fires in ~15 %
fewer candles. "Hold" counts an exact retouch of the extreme as a failure; the strict
">" version is a few points higher.

**Provenance fix (2026-10-05, `fit_extdone_ladder.py`).** Same selection rule applied to 2y
only (P(hold) ≥ 0.90, ≥ 100 events), then scored on oos2m:

| tf | side | ladder fit on 2y (25–50 / 50–75 / 75–100 %) | 2y P(hold) | oos2m P(hold) | n | fires % |
|---|---|---|---|---|---|---|
| 15 | high | 5.0 / 2.5 / 1.5 | 0.912 | 0.938 | 4025 | 75 |
| 15 | low | 4.0 / 2.5 / 1.5 | 0.911 | 0.936 | 3845 | 72 |
| 60 | high | 10.0 / 8.0 / 4.0 | 0.937 | 0.951 | 968 | 69 |
| 60 | low | 10.0 / 6.0 / 4.0 | 0.912 | 0.952 | 895 | 64 |
| 240 | high | — / — / 8.0 | 0.926 | 0.931 | 262 | 74 |
| 240 | low | — / — / 8.0 | 0.924 | 0.955 | 246 | 70 |

The 2y ladder is stricter, fires in ~10–15 points fewer candles and holds 3–5 points
higher on oos2m; it is the one to use. The sidecar, the veto counts (§2) and the quantile
table (§3) below still use the oos2m-picked ladder of §1.2.

Caveats: thresholds chosen on oos2m itself (counts, not a fit — low overfit risk, but regime
risk remains); 240 m has 120–140 events per cell; the 75–100 % buckets are partly mechanical
(few minutes left).

Viewer: groups `extdone_short` (high done) / `extdone_long` (low done), "x" marker on every
1-min candle while the state holds, line = frozen running extreme (`_lvl`). Off by default.

---

## 2. Filtering the cb zones with the executed bound

Rule (viewer `_ZONE_VETO`, applied to the zone line and its markers, per tf, same tf):

```
cb_zone_short / cb_inzone_short   drawn only while {tf}_extdone_low  is False
cb_zone_long  / cb_inzone_long    drawn only while {tf}_extdone_high is False
```

Rationale: a short entry zone is meaningless once the candle's low is in (price has turned
up and the short's target, cb_low, is behind it); a long zone once the high is in. The veto
reads the sidecar columns, so it applies regardless of whether the extdone overlay is
checked; datasets without `df_with_ext_done.pkl` draw the zones unfiltered.

Effect on oos2m (zone minutes before → after the veto):

| tf | short | long | removed |
|---|---|---|---|
| 15 | 18,670 → 7,254 | 20,937 → 8,836 | ~60 % |
| 60 | 14,894 → 5,153 | 17,287 → 6,310 | ~64 % |
| 240 | 10,663 → 3,852 | 14,218 → 5,866 | ~62 % |

Roughly 60 % of zone minutes go: the 5 %-of-span zone sits next to the stop-side bound,
which is where the opposite extreme tends to be "in" by mid-candle. Profitability of the
filtered zones has NOT been replayed yet (open item, see §4).

---

## 3. Filtered cb markers → where does the low/high land?

Marker set = the filtered zones of §2 (`cb_inzone_{side}` ∧ ¬veto). Per marker minute t,
remaining extension to the candle's final extreme (long shown; short mirrored on highs):

```
ext_pct = (1_low[t] − candle_low) / 1_low[t] · 100
ext_atr = (1_low[t] − candle_low) / 1_atr_14_ma_5[t]
```

### 3.1 Distribution (oos2m)

| tf | side | markers | candles | marker IS the extreme | ext % median | mean | sd | p90 | ext (1-min ATR) mean | ext (tf ATR) mean |
|---|---|---|---|---|---|---|---|---|---|---|
| 15 | long | 8,836 | 2,240 | 18 % | 0.16 | 0.27 | 0.47 | 0.60 | 1.2 | 0.30 |
| 15 | short | 7,254 | 1,999 | 19 % | 0.16 | 0.28 | 0.37 | 0.69 | 1.3 | 0.32 |
| 60 | long | 6,310 | 512 | 5 % | 0.55 | 0.77 | 0.84 | 1.63 | 3.4 | 0.43 |
| 60 | short | 5,153 | 486 | 6 % | 0.48 | 0.66 | 0.71 | 1.36 | 3.0 | 0.37 |
| 240 | long | 5,866 | 146 | 2 % | 1.16 | 1.76 | 2.47 | 3.74 | 6.7 | 0.48 |
| 240 | short | 3,852 | 118 | 2 % | 1.01 | 1.55 | 2.14 | 2.81 | 6.6 | 0.45 |

Measured from the zone *line* instead of the 1-min low, add ≈ 0.17 / 0.35 / 0.7 %.
The marker is an early signal: in 80–98 % of marker minutes the candle goes further. The
distribution is right-skewed with sd ≥ mean; even at 50–75 % progress sd is 0.22 / 0.6 /
1.4 %. Point estimate of the extreme: `marker_low − k · ATR_tf`, k ≈ 0.30 (15 m), 0.40
(60 m), 0.45 (240 m) — but a ±1 sd band around it is as wide as the estimate.

### 3.2 Linear regression on market state (candle_bounds recipe)
StandardScaler + Ridge(α = 1) of `ext_pct` on the 15 forming-candle bound features
(`cbnc.forming_features`) + progress, pull-away, depth of 1_low below cb_low in σ, atr1 %.
Fit on 2y marker rows, tested on oos2m; baseline = train mean.

| tf | side | r² test | MAE model / baseline (%) | resid sd model / unconditional | state-only (4 feats) r² |
|---|---|---|---|---|---|
| 15 | long | 0.16 | 0.229 / 0.221 | 0.43 / 0.47 | 0.14 |
| 15 | short | 0.15 | 0.219 / 0.223 | 0.34 / 0.37 | 0.13 |
| 60 | long | 0.16 | 0.500 / 0.524 | 0.77 / 0.84 | 0.16 |
| 60 | short | 0.12 | 0.458 / 0.456 | 0.66 / 0.71 | 0.09 |
| 240 | long | 0.26 | 1.14 / 1.24 | 2.12 / 2.47 | 0.19 |
| 240 | short | −0.05 | 1.10 / 1.06 | 2.19 / 2.14 | −0.01 |

An oos2m-internal 75/25 time split is unstable (r² −0.06 … +0.24 at 15/60; < −2 at 240 with
146 candles). `atr1_pct` dominates: the model is a volatility-scale estimator, as the bound
models are (candle_bounds_algorithm.md limitation 2). Residual sd shrinks only 8–14 %.
**Applicable only for scale, not for location.** The skewed target also mismatches a
squared-error linear fit (over-predicts the typical case, under-predicts the tail).

### 3.3 What the data supports — empirical quantiles per (tf, progress), scaled by ATR
Express the extension in 1-min ATR, bucket by (tf, progress), take quantiles on 2y, apply as
`expected_low_q = marker_low − q[tf, bucket] · atr1_now`. No fit, no coefficients; the ATR
scaling absorbs the volatility regime (oos2m was more volatile than 2y and still covers).

`ext_atr` q50 / q75 / q90 fit on 2y; "cov" = share of oos2m markers within the 2y q75 / q90
(nominal 0.75 / 0.90):

| tf | side | progress | q50 / q75 / q90 (2y) | oos2m q50 / q75 / q90 | cov q75 | cov q90 | n oos |
|---|---|---|---|---|---|---|---|
| 15 | long | 0–25 % | 1.2 / 2.6 / 4.4 | 1.1 / 2.3 / 3.8 | 0.79 | 0.93 | 2331 |
| 15 | long | 25–50 % | 0.9 / 2.0 / 3.3 | 0.8 / 1.6 / 2.7 | 0.82 | 0.95 | 4900 |
| 15 | long | 50–75 % | 0.8 / 1.4 / 2.1 | 0.8 / 1.3 / 1.9 | 0.78 | 0.93 | 1570 |
| 15 | short | 0–25 % | 1.1 / 2.5 / 4.3 | 1.1 / 2.4 / 3.9 | 0.76 | 0.92 | 1926 |
| 15 | short | 25–50 % | 0.9 / 1.9 / 3.3 | 0.9 / 1.8 / 3.0 | 0.76 | 0.92 | 4113 |
| 15 | short | 50–75 % | 0.8 / 1.4 / 2.1 | 0.8 / 1.3 / 2.1 | 0.77 | 0.91 | 1195 |
| 60 | long | 0–25 % | 2.6 / 5.3 / 8.8 | 3.1 / 5.7 / 8.9 | 0.72 | 0.90 | 1807 |
| 60 | long | 25–50 % | 2.4 / 4.4 / 7.4 | 2.5 / 4.3 / 6.7 | 0.77 | 0.92 | 3599 |
| 60 | long | 50–75 % | 2.3 / 3.6 / 5.6 | 2.2 / 3.4 / 4.7 | 0.79 | 0.94 | 887 |
| 60 | short | 0–25 % | 2.7 / 5.3 / 8.8 | 2.3 / 4.7 / 7.6 | 0.80 | 0.93 | 1444 |
| 60 | short | 25–50 % | 2.3 / 4.4 / 7.2 | 2.1 / 4.2 / 6.3 | 0.77 | 0.93 | 3081 |
| 60 | short | 50–75 % | 2.0 / 3.5 / 5.2 | 2.1 / 3.1 / 4.9 | 0.80 | 0.91 | 619 |
| 240 | long | 0–25 % | 4.7 / 9.4 / 15.9 | 5.2 / 8.3 / 19.1 | 0.80 | 0.87 | 1280 |
| 240 | long | 25–50 % | 5.5 / 9.7 / 16.8 | 5.2 / 8.9 / 14.1 | 0.78 | 0.93 | 3271 |
| 240 | long | 50–75 % | 5.1 / 7.9 / 11.9 | 4.8 / 7.6 / 10.5 | 0.77 | 0.92 | 1244 |
| 240 | short | 0–25 % | 4.7 / 9.1 / 15.2 | 4.1 / 8.8 / 17.3 | 0.76 | 0.88 | 942 |
| 240 | short | 25–50 % | 4.8 / 8.5 / 14.4 | 5.0 / 8.2 / 11.7 | 0.78 | 0.93 | 2230 |
| 240 | short | 50–75 % | 4.6 / 7.4 / 10.8 | 3.2 / 5.2 / 7.7 | 0.89 | 0.94 | 662 |

75–100 % buckets omitted (20–70 markers). Structure: extension shrinks as the candle matures
(15 m q75: 2.6 → 2.0 → 1.4), grows ≈ √tf, long ≈ short. Worked example — 15 m long marker at
40 % progress, atr1 = 0.037, price 20: median further drop 0.9 × 0.037 ≈ 0.033 (0.17 %); 90 %
of the time the low is within 3.3 × 0.037 ≈ 0.12 (0.6 %). Limits: q50→q90 spans 3–4×, so this
sizes a stop below the zone, it does not locate the low; 240 m 0–25 % q90 under-covers (0.87).

---

## 4. Open items
- Replay the §2-filtered zones (`evlib.replay`, same stop/target as cb_zone) — first test of
  whether entry *selection* moves gross pnl off zero (all placement-only rules net ≈ −fee,
  see ../ev_line.md §4–8).
- Write `{tf}_zone_ext_q{50,75,90}_{long,short}` as a sidecar (level = marker low − q · atr1)
  and draw the expected-extreme band under the zone markers.
- Re-check the extdone ladder on a second OOS window before using it live; consider the
  strict ">" retouch definition.

---

## 5. EMA-25 slope market classes as a quantile conditioner (2026-10-03) — `run_ema_class.py`

**Setup.** `ema_dif_pct[t] = (ema_25[t] − ema_25[last closed candle]) / ema_25[t] · 100` per
1-min row (tf-prefixed `ema_25`, forming value; % of price so 2y's 5× price range does not
dominate); `z = (ema_dif_pct − mean)/std`, mean/std over all 2y rows per tf; classes
fall `z < −x`, neutral `|z| ≤ x`, rise `z > x`. For each x the quantile table of §3.3 is
re-fit per (tf, side, progress, class) and scored with pinball loss (q75 + q90) against the
unconditional table; thin class cells (< 30 rows) fall back to the unconditional cell.

| tf | 2y mean | 2y std | oos2m mean | oos2m std |
|---|---|---|---|---|
| 15 | +0.0016 | 0.085 | −0.006 | 0.120 |
| 60 | +0.0068 | 0.168 | −0.023 | 0.224 |
| 240 | +0.0279 | 0.331 | −0.096 | 0.416 |

**x selection (2y out-of-time: fit first 75 %, score last 25 %):** every x makes the
pinball loss *worse* (−0.1 … −0.65 %). x* = 0.5 taken as the least bad (shares
fall/neutral/rise 0.31/0.43/0.27).

| x | 2y-oot Δ pinball | oos2m Δ pinball | oos2m cov q90 u → c |
|---|---|---|---|
| 0.25 | −0.12 % | +0.79 % | 0.924 → 0.925 |
| 0.50 | −0.08 % | +0.73 % | 0.924 → 0.925 |
| 0.75 | −0.18 % | +0.67 % | 0.924 → 0.924 |
| 1.00 | −0.40 % | +1.03 % | 0.924 → 0.925 |
| 1.25 | −0.65 % | +1.46 % | 0.924 → 0.926 |
| 1.50 | −0.42 % | +1.24 % | 0.924 → 0.926 |
| 2.00 | −0.52 % | +0.88 % | 0.924 → 0.924 |

**Direction of the effect is right but tiny.** At x = 0.5, 2y q50/q75/q90 (ext in 1-min ATR):

| cell | fall | neutral | rise | unconditional |
|---|---|---|---|---|
| 15 long 0–25 % | 1.3 / 3.0 / 5.2 | 1.2 / 2.6 / 4.3 | 0.9 / 2.1 / 3.3 | 1.2 / 2.6 / 4.4 |
| 15 short 0–25 % | 0.9 / 2.0 / 3.3 | 1.1 / 2.6 / 4.4 | 1.3 / 2.8 / 4.9 | 1.1 / 2.5 / 4.3 |
| 60 long 25–50 % | 2.5 / 4.6 / 7.7 | 2.5 / 4.6 / 7.7 | 2.2 / 3.8 / 6.5 | 2.4 / 4.4 / 7.4 |
| 60 short 25–50 % | 2.1 / 4.0 / 6.4 | 2.4 / 4.7 / 7.5 | 2.2 / 4.2 / 7.2 | 2.3 / 4.4 / 7.2 |
| 240 long 0–25 % | 5.1 / 10.3 / 19.8 | 4.7 / 9.0 / 14.4 | 4.1 / 8.4 / 14.0 | 4.7 / 9.4 / 15.9 |

A long marker in a falling market extends ~20 % further at q90 than in a rising one (the
dip keeps going); shorts mirror. But the class moves the quantile by ±15–20 % while the
within-cell spread (q50→q90) is 3–4×, so the information gain is ≤ 1.5 % of pinball loss on
oos2m and negative on 2y out-of-time; per-cell oos2m changes are −1.2 … +2.5 % except one
small cell (240 long 0–25 %, +7 %, 1280 rows, the one that under-covered unconditionally).
oos2m is net-falling (mean z < 0 at every tf), so the +0.7–1.5 % there is partly the fall
class absorbing a regime shift the unconditional table can't see.

**Closed-candle variant (re-run, same day).** `ema_dif` recomputed on the closed sequence
only — `d[k] = (ema[k] − ema[k−1]) / ema[k] · 100` at candle k's close, held constant over the
next candle's rows (shift(1)+ffill), mean/std over 2y closed candles (one value per candle):

| tf | 2y mean | 2y std | oos2m mean | oos2m std |
|---|---|---|---|---|
| 15 | +0.0018 | 0.089 | −0.006 | 0.124 |
| 60 | +0.0073 | 0.174 | −0.024 | 0.233 |
| 240 | +0.0296 | 0.344 | −0.094 | 0.425 |

Normalisation almost identical to the forming version (std +3–4 %). x selection on 2y
out-of-time again negative for every x (−0.09 … −1.58 %), x* = 0.5 (shares .31/.43/.26);
oos2m +0.9 … +1.7 % (cov q90 0.924 → 0.926). Per-cell oos2m: −2.7 … +4.7 %, same single
outlier (240 long 0–25 %, +8 %). Class quantiles at x* = 0.5 (2y, q50/q75/q90, 1-min ATR):

| cell | fall (n 2y) | neutral | rise | unconditional |
|---|---|---|---|---|
| 15 long 0–25 % | 1.2 / 2.9 / 5.1 (4317) | 1.2 / 2.7 / 4.5 (8424) | 1.0 / 2.2 / 3.6 (4865) | 1.2 / 2.6 / 4.4 |
| 15 short 0–25 % | 1.0 / 2.2 / 3.6 (4914) | 1.1 / 2.6 / 4.6 (9627) | 1.2 / 2.8 / 4.8 (4198) | 1.1 / 2.5 / 4.3 |
| 60 long 25–50 % | 2.6 / 4.6 / 7.6 (7666) | 2.4 / 4.7 / 8.0 (12151) | 2.2 / 4.0 / 6.6 (7804) | 2.4 / 4.4 / 7.4 |
| 60 short 25–50 % | 2.1 / 4.0 / 6.5 (8549) | 2.5 / 4.8 / 7.7 (12746) | 2.2 / 4.1 / 6.9 (7144) | 2.3 / 4.4 / 7.2 |
| 240 long 0–25 % | 5.2 / 10.2 / 20.4 (3280) | 5.0 / 9.6 / 16.2 (3820) | 4.0 / 8.5 / 13.3 (3275) | 4.7 / 9.4 / 15.9 |

Class membership shifts vs the forming variant (the closed slope lags by one candle, so
~20 % of rows change class) but the class quantiles land within ±0.1–0.3 ATR of the forming
ones and the fall/rise ordering is identical. Same conclusion.

**Status (2026-10-05): open, left for further investigation** — the measurement below is only
"3-class conditioner of the extension quantiles"; entry filtering, hold-probability
conditioning, other EMA lengths and a 2-class split are untested. The class is now computed
in code (`indicators.library.classification.EmaSlopeClassField`, column
`{tf}_ema_25_slope_class`, on `{tf}_ema_25_diff_prc`).

**Reading so far:** EMA-25 slope classes do not improve the extension quantiles beyond noise. Keep
the unconditional (tf, side, progress) table. If conditioning is wanted, a two-class split
(with-trend vs against-trend relative to the entry side) at x ≈ 0.5 captures the whole
directional effect with twice the cell counts — but the expected gain is ≤ 2 %.

## 6. EMA-25 slope distribution + chart classes (2026-10-03) — `run_ema_slope.py`

Closed-candle slope, classes at x = 0.5 (2y mean/std). Sidecar `df_with_ema_slope.pkl`: `{tf}_ema25_slope_z`, `{tf}_ema25_cls` (shifted, feature-safe) and `{tf}_ema_25_{rise,fall,neutral}` (drawing, unshifted). Viewer overlay group `ema25_cls` (green / red / gray), tf 15/60/240 charts.

| tf | n 2y | mean | std | skew | kurtosis | p1 | p5 | p25 | p50 | p75 | p95 | p99 | fall cut | rise cut |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 | 70169 | +0.0018 | 0.0886 | -0.20 | 16.8 | -0.234 | -0.124 | -0.038 | +0.000 | +0.040 | +0.135 | +0.255 | -0.0425 | +0.0461 |
| 60 | 17541 | +0.0073 | 0.1736 | +0.22 | 10.9 | -0.419 | -0.240 | -0.081 | +0.002 | +0.088 | +0.273 | +0.516 | -0.0795 | +0.0941 |
| 240 | 4385 | +0.0296 | 0.3436 | +0.41 | 6.7 | -0.788 | -0.468 | -0.167 | +0.012 | +0.203 | +0.584 | +1.060 | -0.1422 | +0.2014 |

| tf | share 2y fall / neutral / rise | share oos2m | mean run (candles) 2y f / n / r | oos2m mean / std |
|---|---|---|---|---|
| 15 | 0.23 / 0.55 / 0.22 | 0.33 / 0.38 / 0.29 | 4.7 / 6.0 / 5.0 | -0.0056 / 0.1242 |
| 60 | 0.26 / 0.51 / 0.24 | 0.35 / 0.36 / 0.29 | 5.2 / 5.4 / 5.2 | -0.0242 / 0.2333 |
| 240 | 0.28 / 0.47 / 0.25 | 0.44 / 0.32 / 0.24 | 5.9 / 5.2 / 5.7 | -0.0938 / 0.4257 |

Fat-tailed (kurtosis 7–17), so ±0.5σ puts ~half of 2y candles in neutral (Gaussian: 38 %). oos2m is more volatile and net-falling: neutral shrinks to 0.32–0.38, fall grows to 0.33–0.44. Mean run ≈ 5–6 candles per class at every tf.
