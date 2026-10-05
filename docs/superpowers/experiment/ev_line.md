# EV line — entry placement and entry state between the candle-bound bands

> **Status 2026-10-05: DONE — verdict partial (approved), branch kept.** Results:
> [`results/ev_line_results.md`](results/ev_line_results.md) (decision report) and
> [`results/extdone_zone_filter_results.md`](results/extdone_zone_filter_results.md) (detail
> for rounds 4–6). Branch `ev-line-experiment` off `zone-profitability` @ `2788110`,
> worktree `worktrees/ev-line-experiment`, committed as `60def30` (one combined commit, not pushed). Register: `REPORT.md`.
> This spec was written back from an interactive session (2026-10-01 … 10-03); the numbered
> sections below the spec are the working log, in the order the rounds were run.

# Goal
Decide whether the closed-candle bound predictions (`{tf}_cb_low/high` ± frozen band,
candle_bounds_algorithm.md) can be turned into a better **entry** for tf 15/60/240 than the
current 5 %-of-span `cb_zone_*`: (a) by *placing* the entry level from the bands'
probabilities, and, once that failed, (b) by *selecting* when a zone is live and estimating
how far price still runs past it. Measurable outcome per rule: net pnl per candle on a
minute replay, and for the state/quantile deliverables OOS hold probability and coverage.

# Rationale and algorithm
1. **EV line (placement).** Treat each band as N(bound, σ). Long: stop S = L − s·σ_L, target
   T = H − t·σ_H, entry E; p_fill = Φ((E−L)/σ_L), p_win = p_target·(1 − p_stop|fill);
   choose E = argmax p_fill·EV(E). If the bands carry placement information, EV-best beats
   the fixed 5 % zone.
2. **Empirical reach.** Replace the Gaussian-independence p_win with what a minute replay on
   2y actually does for every (a, s, t) in band units; freeze argmax; score oos2m.
3. **ATR-shifted zone.** Entry = bound ± k × 1-min ATR instead of 5 % of span.
4. **Executed bound (extdone).** The candle's running extreme is "in" when the close has
   pulled away by ≥ d(progress) 1-min ATRs; use it to veto zones on the wrong side.
5. **Remaining extension.** From a vetoed zone marker, how far does the candle still go:
   distribution, Ridge on market state, quantiles per (tf, progress) in ATR units.
6. **EMA-25 slope classes.** fall / neutral / rise by z-scored closed-candle slope as a
   conditioner for (5), and as a chart indicator.

# Steps
| # | round | driver |
|---|---|---|
| 1 | Gaussian EV line + replay vs cb_zone / cb level | `run_ev.py`, `evlib.py` |
| 2 | stop/target σ sweep (25 combos) | `sweep_ev.py` |
| 3 | empirical-reach rule, fit 2y → oos2m | `run_evr.py` |
| 4 | ATR-shifted zone, k sweep | `run_cbatr.py` |
| 5 | extdone state + ladder; 2y-fit provenance gate | `run_extdone.py`, `fit_extdone_ladder.py` |
| 6 | zone veto; marker → extreme distribution, Ridge, quantiles | viewer `_ZONE_VETO`, `run_zone_ext.py` |
| 7 | EMA-25 slope classes × quantiles; slope distribution + chart | `run_ema_class.py`, `run_ema_slope.py` |

# Results
Reports under `results/`; sidecars on the oos2m dataset dir (`df_with_ev_line`,
`_ev_reach`, `_cb_zone_atr`, `_ext_done`, `_ema_slope`); viewer overlay groups `ev_*`,
`evr_*`, `cbatr_*`, `extdone_*`, `ema25_cls`, `cb_enter`; zone veto in the viewer.

# Constraints
Read-only over `df_with_indicators.pkl` and the cb sidecars; new data only as sidecars.
Bound models and `band_pct` are NOT refit (frozen from candle_bounds). Fee 0.1 % per side.
Nothing committed before the report is approved. Docs only in the external repo.

# Data
Train: 2y (`2y_az_link_usdt` indicators, bounds from `2y_link_usdt/df_with_candle_bounds.pkl`
— in-sample for the bound models), 2023-01-01 → 2024-12-31. Validation: oos2m, 2025-01-01 →
2025-03-01, 84,961 minutes. LINK/USDT only. Columns `{tf}_<name>_{side}`.

# Open questions
- EMA-25 slope classes as a conditioner: open, see `results/ev_line_results.md` → "Open".
- See `results/ev_line_results.md` → Next arbiter.

---

# Working log

## 1. Question
Given `cb_low`/`cb_high` and their frozen ±1σ bands, where is the entry level whose win
odds cover the risk/reward the trade needs — one level per side, per tf?

## 2. Method
Long (short mirrored), per closed-candle prediction:
```
S = L − 1.0·σ_L               stop, beyond the low band
T = H − 0.5·σ_H               target, inside the high band
p_fill   = Φ((E−L)/σ_L)       p_stop = Φ((S−L)/σ_L)/p_fill     p_target = 1−Φ((T−H)/σ_H)
p_win    = p_target·(1−p_stop)                                   (independence, no ordering)
EV(E)    = p_win·(T−E) − (1−p_win)·(E−S) − 2·fee·E               fee 0.1 % per side
best     = argmax_E p_fill·EV(E)      breakeven = outermost E with EV ≥ 0
```
Realized check: minute replay inside each candle — fill at first minute `1_low ≤ E`; stop
counted from the fill minute inclusive, target from the next minute; open at candle close
exits at `1_close`. Four rules replayed with their own S/T:
`ev` (best), `ev_be` (breakeven), `cb_zone` (E = cb_zone, S = cb_low, T = cb_high — the
current 5 %-of-span rule), `cb_level` (E = cb_low, S = cb_low − 1σ, T = cb_high).

## 3. Results (oos2m, LINK/USDT)
## Model-implied (median per candle)

| tf | side | n | p_fill | p_win | EV/fill % | EV/candle % | best @ span | be @ span | best−cb_zone % | best−cb_level % | span % |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 | long | 5651 | 0.270 | 0.286 | -0.075 | -0.020 | -0.32 | 0.11 | -0.271 | -0.234 | 0.73 |
| 15 | short | 5651 | 0.278 | 0.296 | -0.077 | -0.021 | -0.25 | 0.14 | +0.218 | +0.182 | 0.73 |
| 60 | long | 1403 | 0.335 | 0.364 | +0.071 | +0.024 | -0.22 | 0.05 | -0.402 | -0.327 | 1.50 |
| 60 | short | 1403 | 0.357 | 0.384 | +0.066 | +0.024 | -0.16 | 0.10 | +0.305 | +0.231 | 1.50 |
| 240 | long | 341 | 0.372 | 0.397 | +0.338 | +0.126 | -0.16 | 0.08 | -0.651 | -0.497 | 3.06 |
| 240 | short | 341 | 0.395 | 0.413 | +0.317 | +0.125 | -0.11 | 0.12 | +0.487 | +0.338 | 3.06 |

## Realized (minute replay, net of 2×fee)

| tf | side | rule | n | fill | win | stop | open@close | pnl/fill % | pnl/candle % | Σ pnl % |
|---|---|---|---|---|---|---|---|---|---|---|
| 15 | long | ev | 5651 | 0.246 | 0.054 | 0.559 | 0.387 | -0.1942 | -0.0478 | -270.4 |
| 15 | long | ev_be | 1554 | 0.597 | 0.186 | 0.357 | 0.457 | -0.2027 | -0.1209 | -187.9 |
| 15 | long | cb_zone | 5651 | 0.515 | 0.030 | 0.897 | 0.073 | -0.1936 | -0.0996 | -563.1 |
| 15 | long | cb_level | 5651 | 0.463 | 0.075 | 0.297 | 0.628 | -0.1913 | -0.0885 | -500.3 |
| 15 | short | ev | 5651 | 0.262 | 0.059 | 0.633 | 0.308 | -0.1827 | -0.0479 | -270.6 |
| 15 | short | ev_be | 1574 | 0.553 | 0.200 | 0.383 | 0.417 | -0.1877 | -0.1037 | -163.3 |
| 15 | short | cb_zone | 5651 | 0.473 | 0.025 | 0.910 | 0.066 | -0.2000 | -0.0945 | -534.2 |
| 15 | short | cb_level | 5651 | 0.431 | 0.068 | 0.386 | 0.547 | -0.1908 | -0.0821 | -464.2 |
| 60 | long | ev | 1403 | 0.298 | 0.081 | 0.505 | 0.414 | -0.2340 | -0.0697 | -97.8 |
| 60 | long | ev_be | 991 | 0.517 | 0.180 | 0.338 | 0.482 | -0.2818 | -0.1456 | -144.3 |
| 60 | long | cb_zone | 1403 | 0.505 | 0.024 | 0.906 | 0.071 | -0.2013 | -0.1017 | -142.7 |
| 60 | long | cb_level | 1403 | 0.458 | 0.073 | 0.326 | 0.601 | -0.2292 | -0.1049 | -147.1 |
| 60 | short | ev | 1403 | 0.309 | 0.090 | 0.561 | 0.349 | -0.2090 | -0.0645 | -90.5 |
| 60 | short | ev_be | 967 | 0.524 | 0.229 | 0.377 | 0.394 | -0.2047 | -0.1073 | -103.8 |
| 60 | short | cb_zone | 1403 | 0.470 | 0.032 | 0.912 | 0.056 | -0.1941 | -0.0912 | -127.9 |
| 60 | short | cb_level | 1403 | 0.431 | 0.071 | 0.407 | 0.522 | -0.1948 | -0.0840 | -117.8 |
| 240 | long | ev | 341 | 0.331 | 0.062 | 0.487 | 0.451 | -0.2475 | -0.0820 | -28.0 |
| 240 | long | ev_be | 334 | 0.548 | 0.208 | 0.301 | 0.492 | -0.2057 | -0.1127 | -37.6 |
| 240 | long | cb_zone | 341 | 0.522 | 0.006 | 0.899 | 0.096 | -0.2334 | -0.1218 | -41.5 |
| 240 | long | cb_level | 341 | 0.469 | 0.113 | 0.344 | 0.544 | -0.1596 | -0.0749 | -25.5 |
| 240 | short | ev | 341 | 0.302 | 0.136 | 0.447 | 0.417 | -0.1643 | -0.0496 | -16.9 |
| 240 | short | ev_be | 326 | 0.509 | 0.277 | 0.265 | 0.458 | -0.0282 | -0.0144 | -4.7 |
| 240 | short | cb_zone | 341 | 0.457 | 0.026 | 0.859 | 0.115 | -0.1705 | -0.0780 | -26.6 |
| 240 | short | cb_level | 341 | 0.393 | 0.149 | 0.343 | 0.507 | +0.0055 | +0.0021 | +0.7 |

`best @ span` = (best − cb_low)/(cb_high − cb_low): negative = below cb_low, inside the low
band. `best−cb_zone %` = distance from the current zone line, % of price.

## 4. Reading
1. **Model says:** at 15 m no entry is EV-positive (span 0.73 % vs 0.2 % round-trip fee);
   at 60/240 m the best entry sits 0.16–0.22 spans *below* cb_low with p_win ≈ 0.36–0.41.
2. **Realized says:** every rule, every tf, nets ≈ −fee. Gross pnl per fill is within
   ±0.05 % of zero in 21 of 24 cells (exceptions: ev_be 60 long −0.08, ev_be 240 short +0.17 on
   166 fills, cb_level 240 short +0.21 on 134 fills). *(Corrected 2026-10-05; first written as
   "all 24 cells, one exception".)*
   Confirms candle_bounds_algorithm.md known-limitation 1: placement cannot move EV.
3. **Why the model overshoots:** realized win rate (5–14 %) is ~4× below modelled p_win
   (29–41 %). `p_target` is NOT independent of the fill — a low that already dipped to E
   rarely has the candle go on to reach T; the target was often hit *before* the fill. The
   Gaussian-independence prior is the wrong model for ordering; `p_target` must be
   measured conditional on fill (zplib's `future_extreme_in_candle` route).
4. **vs cb_zone:** ev loses half as much per candle (−0.048 vs −0.100 at 15 m) only because
   it fills half as often; cb_zone with S = cb_low is stopped 86–91 % of fills (stop 5 % of
   span from entry).
5. **vs cb_level:** entry at the raw bound is the least bad at 240 m; comparable elsewhere.

## 5. Next
- Replace `p_target` with the empirical conditional reach from the 2y frame (reach T after
  fill at E, per tf/side, binned by E's σ-offset), keep the EV argmax.
- Horizon: 39–49 % of fills are still open at candle close — the one-candle validity of the
  bounds is the binding constraint, not the level.

## 6. σ sweep (2026-10-02) — `sweep_ev.py`
stop σ ∈ {0.5,1,1.5,2,3} × target σ ∈ {−0.5,0,0.5,1,1.5} (target σ < 0 = beyond the predicted
extreme), EV-best entry re-solved per combo, same minute replay. Mean over tf×side:

| stop σ | tgt σ | fill | win | pnl/fill % | pnl/candle % | Σ pnl % | model p_win | model EV/candle % |
|---|---|---|---|---|---|---|---|---|
| 0.5 | -0.5 | 0.275 | 0.003 | -0.1951 | -0.0538 | -803.1 | 0.005 | -0.0624 |
| 0.5 | 0.0 | 0.304 | 0.024 | -0.1795 | -0.0547 | -836.9 | 0.051 | -0.0557 |
| 0.5 | 0.5 | 0.329 | 0.047 | -0.2019 | -0.0669 | -937.8 | 0.107 | -0.0469 |
| 0.5 | 1.0 | 0.324 | 0.068 | -0.2057 | -0.0667 | -950.1 | 0.102 | -0.0528 |
| 0.5 | 1.5 | 0.303 | 0.064 | -0.2026 | -0.0613 | -892.2 | 0.019 | -0.0613 |
| 1.0 | -0.5 | 0.189 | 0.011 | -0.1778 | -0.0337 | -478.8 | 0.052 | -0.0260 |
| 1.0 | 0.0 | 0.251 | 0.044 | -0.1800 | -0.0452 | -620.0 | 0.207 | +0.0075 |
| 1.0 | 0.5 | 0.291 | 0.080 | -0.2053 | -0.0603 | -774.2 | 0.357 | +0.0427 |
| 1.0 | 1.0 | 0.291 | 0.129 | -0.2102 | -0.0620 | -793.1 | 0.424 | +0.0391 |
| 1.0 | 1.5 | 0.257 | 0.159 | -0.1957 | -0.0502 | -707.2 | 0.354 | +0.0046 |
| 1.5 | -0.5 | 0.143 | 0.010 | -0.2590 | -0.0379 | -373.4 | 0.134 | +0.0021 |
| 1.5 | 0.0 | 0.216 | 0.049 | -0.1928 | -0.0417 | -525.5 | 0.347 | +0.0564 |
| 1.5 | 0.5 | 0.272 | 0.093 | -0.1936 | -0.0528 | -686.8 | 0.534 | +0.1183 |
| 1.5 | 1.0 | 0.278 | 0.146 | -0.2236 | -0.0633 | -755.5 | 0.656 | +0.1292 |
| 1.5 | 1.5 | 0.250 | 0.199 | -0.2147 | -0.0542 | -678.6 | 0.683 | +0.0864 |
| 2.0 | -0.5 | 0.113 | 0.011 | -0.2796 | -0.0319 | -301.6 | 0.210 | +0.0135 |
| 2.0 | 0.0 | 0.181 | 0.041 | -0.2585 | -0.0480 | -465.9 | 0.433 | +0.0729 |
| 2.0 | 0.5 | 0.247 | 0.086 | -0.2307 | -0.0580 | -630.2 | 0.631 | +0.1517 |
| 2.0 | 1.0 | 0.268 | 0.146 | -0.2388 | -0.0659 | -726.3 | 0.774 | +0.1803 |
| 2.0 | 1.5 | 0.245 | 0.212 | -0.2248 | -0.0564 | -663.8 | 0.845 | +0.1421 |
| 3.0 | -0.5 | 0.067 | 0.004 | -0.2784 | -0.0191 | -201.4 | 0.288 | +0.0079 |
| 3.0 | 0.0 | 0.132 | 0.032 | -0.2408 | -0.0318 | -339.1 | 0.492 | +0.0485 |
| 3.0 | 0.5 | 0.208 | 0.068 | -0.2357 | -0.0500 | -537.6 | 0.687 | +0.1313 |
| 3.0 | 1.0 | 0.246 | 0.134 | -0.2465 | -0.0616 | -664.3 | 0.837 | +0.1871 |
| 3.0 | 1.5 | 0.238 | 0.222 | -0.2046 | -0.0489 | -635.5 | 0.928 | +0.1696 |

**No combo is net-positive in any aggregate; 0 of 150 (combo, tf, side) cells net-positive.**
Gross pnl per fill stays in [−0.08, +0.02] % for every combo; the 11 cells with gross/fill
> +0.05 % have 53–260 fills and win rates 1–22 % (open-at-close exits carry them). Realized
win rate caps at 0.22 while modelled p_win climbs to 0.93 — the gap *widens* with wider
stops, which is the independence assumption failing, not a σ-calibration problem. Verdict:
stop/target σ is not the lever; the conditional reach model (§5) is. Sidecar/chart kept at
(stop 1.0, target 0.5).

## 7. Empirical conditional reach (2026-10-02) — `run_evr.py`
Gaussian prior replaced by measurement: entry/stop/target in band units
`E = L + a·σ_L, S = L − s·σ_L, T = H − t·σ_H` (short mirrored), every (a, s, t) on
a ∈ [−3, 1] step 0.25 × s ∈ {0.5..3} × t ∈ {−0.5..1.5} replayed minute-by-minute on the
2y frame (bounds from `2y_link_usdt/df_with_candle_bounds.pkl`, in-sample for the bound
models), then the per-(tf, side) argmax of 2y net pnl/candle (≥ 100 fills) replayed on oos2m.
Sidecar `df_with_ev_reach.pkl` (`{tf}_evr_{side}[,_sl,_tgt]`), viewer groups `evr_*` (off
by default).

**Gaussian vs measured, s = 1, t = 0.5, 2y (all tf/side agree within ±0.03):**

| a (entry offset) | G p_fill | E p_fill | G p_win | E p_win\|fill | E stop\|fill | E open\|fill | E pnl/fill % |
|---|---|---|---|---|---|---|---|
| −0.75 | 0.23 | 0.12–0.15 | 0.21 | 0.02–0.03 | 0.70–0.76 | 0.22–0.28 | −0.15…−0.23 |
| −0.25 | 0.40 | 0.26–0.29 | 0.42 | 0.08–0.10 | 0.32–0.40 | 0.50–0.60 | −0.16…−0.21 |
| 0.0 | 0.50 | 0.37–0.41 | 0.47 | 0.15–0.18 | 0.21–0.28 | 0.55–0.64 | −0.16…−0.21 |
| +0.5 | 0.69 | 0.71–0.75 | 0.53 | 0.46–0.48 | 0.11–0.15 | 0.39–0.42 | −0.16…−0.22 |
| +1.0 | 0.84 | 0.87–0.92 | 0.56 | 0.54–0.58 | 0.11–0.14 | 0.31–0.34 | −0.24…−0.37 |

Measured p_win|fill is ~3× below the Gaussian value for entries at/beyond the bound and
converges only for shallow entries (a ≥ +0.5), where the trade is effectively "buy the
previous close". Net pnl/fill is flat at ≈ −0.20 % = −round-trip fee across every a: gross
≈ 0 regardless of placement.

**2y grid:** 24 of 1545 eligible cells net-positive per fill — all 240 long, a ∈ [−2, −1.75],
s = 3.0, 150–196 fills, win 1–8 % (open-at-close carry). Selected rules per (tf, side) all
collapse to a ≤ −1.75, s = 3.0 (deepest, rarest fills: 2y pnl/candle ≈ −0.003 … +0.007).
**oos2m:** 17–219 fills per cell, **0 wins in all six**, pnl/fill −0.16 … −0.40 %.

**Verdict:** closed-candle bound bands carry no entry-placement edge at any σ-offset, on
either the Gaussian or the measured reach model; the only positive in-sample cells are
small-n carry artefacts that do not survive OOS. This closes the EV-line line of inquiry
(consistent with candle_bounds_algorithm.md limitation 1 and zone_profitability.md's
"no in-candle target beats breakeven"). Any future edge must come from entry *selection*
(state conditioning), not from where the level sits between the bands.

## 8. ATR-shifted entry zone vs cb_zone 5 % (2026-10-02) — `run_cbatr.py`
Entry = closed bound shifted k × `1_atr_14_ma_5` (per-minute, 0.18 % of price at k = 1)
instead of 5 % of the cb span (0.037 / 0.075 / 0.15 % at tf 15 / 60 / 240). Same stop/target
as cb_zone (S = bound, T = opposite bound) and a second variant S = bound − 1σ. Sidecar
`df_with_cb_zone_atr.pkl` (`{tf}_cbatr_zone_{side}`, `{tf}_cbatr_inzone_{side}`, k = 1),
viewer groups `cbatr_long`/`cbatr_short` + dotted-triangle in-zone markers.

### stop S=bound, target = opposite bound

| tf | side | rule | shift % price | shift/span | in-zone rows % | fills | fill | win | stop | open | pnl/fill % | pnl/candle % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 | long | cb_zone_5pct | 0.037 | 0.05 | 24.6 | 2909 | 0.515 | 0.030 | 0.897 | 0.073 | -0.1936 | -0.0996 |
| 15 | long | atr_k0.5 | 0.089 | 0.12 | 30.0 | 3332 | 0.590 | 0.071 | 0.781 | 0.148 | -0.1971 | -0.1162 |
| 15 | long | atr_k1 | 0.178 | 0.25 | 39.8 | 4024 | 0.712 | 0.147 | 0.639 | 0.213 | -0.2107 | -0.1500 |
| 15 | long | atr_k1.5 | 0.267 | 0.37 | 50.8 | 4668 | 0.826 | 0.234 | 0.543 | 0.223 | -0.2307 | -0.1906 |
| 15 | long | atr_k2 | 0.356 | 0.49 | 61.2 | 5200 | 0.920 | 0.312 | 0.481 | 0.207 | -0.2725 | -0.2507 |
| 15 | long | atr_k3 | 0.533 | 0.74 | 78.6 | 5610 | 0.993 | 0.381 | 0.438 | 0.181 | -0.4303 | -0.4272 |
| 15 | short | cb_zone_5pct | 0.036 | 0.05 | 22.0 | 2671 | 0.473 | 0.025 | 0.910 | 0.066 | -0.2000 | -0.0945 |
| 15 | short | atr_k0.5 | 0.089 | 0.12 | 26.6 | 3087 | 0.546 | 0.069 | 0.784 | 0.147 | -0.1958 | -0.1069 |
| 15 | short | atr_k1 | 0.178 | 0.25 | 35.3 | 3747 | 0.663 | 0.147 | 0.638 | 0.215 | -0.2072 | -0.1374 |
| 15 | short | atr_k1.5 | 0.267 | 0.37 | 45.5 | 4447 | 0.787 | 0.239 | 0.526 | 0.234 | -0.2168 | -0.1706 |
| 15 | short | atr_k2 | 0.356 | 0.49 | 56.1 | 5038 | 0.892 | 0.324 | 0.457 | 0.219 | -0.2509 | -0.2237 |
| 15 | short | atr_k3 | 0.535 | 0.74 | 75.2 | 5585 | 0.988 | 0.415 | 0.402 | 0.183 | -0.3945 | -0.3898 |
| 60 | long | cb_zone_5pct | 0.075 | 0.05 | 20.3 | 709 | 0.505 | 0.024 | 0.906 | 0.071 | -0.2013 | -0.1017 |
| 60 | long | atr_k0.5 | 0.090 | 0.06 | 21.0 | 719 | 0.512 | 0.033 | 0.893 | 0.074 | -0.2078 | -0.1065 |
| 60 | long | atr_k1 | 0.180 | 0.12 | 25.0 | 807 | 0.575 | 0.064 | 0.794 | 0.141 | -0.2181 | -0.1254 |
| 60 | long | atr_k1.5 | 0.269 | 0.18 | 29.3 | 896 | 0.639 | 0.096 | 0.714 | 0.190 | -0.2247 | -0.1435 |
| 60 | long | atr_k2 | 0.359 | 0.24 | 34.0 | 997 | 0.711 | 0.140 | 0.637 | 0.223 | -0.2241 | -0.1592 |
| 60 | long | atr_k3 | 0.537 | 0.36 | 44.2 | 1158 | 0.825 | 0.240 | 0.541 | 0.219 | -0.2514 | -0.2075 |
| 60 | short | cb_zone_5pct | 0.074 | 0.05 | 17.5 | 659 | 0.470 | 0.032 | 0.912 | 0.056 | -0.1941 | -0.0912 |
| 60 | short | atr_k0.5 | 0.089 | 0.06 | 18.2 | 672 | 0.479 | 0.042 | 0.894 | 0.064 | -0.1927 | -0.0923 |
| 60 | short | atr_k1 | 0.177 | 0.12 | 21.4 | 763 | 0.544 | 0.071 | 0.782 | 0.147 | -0.1835 | -0.0998 |
| 60 | short | atr_k1.5 | 0.266 | 0.18 | 25.3 | 854 | 0.609 | 0.125 | 0.693 | 0.181 | -0.1621 | -0.0987 |
| 60 | short | atr_k2 | 0.356 | 0.24 | 29.5 | 936 | 0.667 | 0.166 | 0.629 | 0.205 | -0.1822 | -0.1216 |
| 60 | short | atr_k3 | 0.534 | 0.36 | 39.0 | 1100 | 0.784 | 0.252 | 0.525 | 0.223 | -0.2183 | -0.1712 |
| 240 | long | cb_zone_5pct | 0.153 | 0.05 | 16.7 | 178 | 0.522 | 0.006 | 0.899 | 0.096 | -0.2334 | -0.1218 |
| 240 | long | atr_k0.5 | 0.091 | 0.03 | 15.9 | 171 | 0.501 | 0.012 | 0.936 | 0.053 | -0.2188 | -0.1097 |
| 240 | long | atr_k1 | 0.182 | 0.06 | 17.4 | 181 | 0.531 | 0.017 | 0.884 | 0.099 | -0.2487 | -0.1320 |
| 240 | long | atr_k1.5 | 0.272 | 0.09 | 19.1 | 188 | 0.551 | 0.027 | 0.846 | 0.128 | -0.2961 | -0.1633 |
| 240 | long | atr_k2 | 0.363 | 0.12 | 20.9 | 200 | 0.587 | 0.040 | 0.795 | 0.165 | -0.3178 | -0.1864 |
| 240 | long | atr_k3 | 0.543 | 0.18 | 24.7 | 226 | 0.663 | 0.080 | 0.704 | 0.217 | -0.3140 | -0.2081 |
| 240 | short | cb_zone_5pct | 0.148 | 0.05 | 12.6 | 156 | 0.457 | 0.026 | 0.859 | 0.115 | -0.1705 | -0.0780 |
| 240 | short | atr_k0.5 | 0.088 | 0.03 | 11.9 | 149 | 0.437 | 0.020 | 0.899 | 0.081 | -0.1806 | -0.0789 |
| 240 | short | atr_k1 | 0.177 | 0.06 | 13.1 | 159 | 0.466 | 0.038 | 0.843 | 0.119 | -0.1931 | -0.0900 |
| 240 | short | atr_k1.5 | 0.266 | 0.09 | 14.4 | 169 | 0.496 | 0.041 | 0.793 | 0.166 | -0.2156 | -0.1068 |
| 240 | short | atr_k2 | 0.354 | 0.12 | 15.9 | 179 | 0.525 | 0.073 | 0.749 | 0.179 | -0.1994 | -0.1047 |
| 240 | short | atr_k3 | 0.533 | 0.18 | 19.2 | 202 | 0.592 | 0.109 | 0.663 | 0.228 | -0.1861 | -0.1102 |

### stop S=bound-1sd, target = opposite bound

| tf | side | rule | shift % price | shift/span | in-zone rows % | fills | fill | win | stop | open | pnl/fill % | pnl/candle % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 | long | cb_zone_5pct | 0.037 | 0.05 | 24.6 | 2909 | 0.515 | 0.098 | 0.267 | 0.635 | -0.1859 | -0.0957 |
| 15 | long | atr_k0.5 | 0.089 | 0.12 | 30.0 | 3332 | 0.590 | 0.131 | 0.233 | 0.637 | -0.1901 | -0.1121 |
| 15 | long | atr_k1 | 0.178 | 0.25 | 39.8 | 4024 | 0.712 | 0.196 | 0.190 | 0.614 | -0.2044 | -0.1455 |
| 15 | long | atr_k1.5 | 0.267 | 0.37 | 50.8 | 4668 | 0.826 | 0.275 | 0.161 | 0.563 | -0.2247 | -0.1856 |
| 15 | long | atr_k2 | 0.356 | 0.49 | 61.2 | 5200 | 0.920 | 0.349 | 0.143 | 0.508 | -0.2672 | -0.2459 |
| 15 | long | atr_k3 | 0.533 | 0.74 | 78.6 | 5610 | 0.993 | 0.415 | 0.131 | 0.454 | -0.4260 | -0.4229 |
| 15 | short | cb_zone_5pct | 0.036 | 0.05 | 22.0 | 2671 | 0.473 | 0.086 | 0.350 | 0.563 | -0.1914 | -0.0904 |
| 15 | short | atr_k0.5 | 0.089 | 0.12 | 26.6 | 3087 | 0.546 | 0.122 | 0.302 | 0.576 | -0.1881 | -0.1027 |
| 15 | short | atr_k1 | 0.178 | 0.25 | 35.3 | 3747 | 0.663 | 0.191 | 0.246 | 0.563 | -0.2009 | -0.1332 |
| 15 | short | atr_k1.5 | 0.267 | 0.37 | 45.5 | 4447 | 0.787 | 0.275 | 0.204 | 0.521 | -0.2123 | -0.1671 |
| 15 | short | atr_k2 | 0.356 | 0.49 | 56.1 | 5038 | 0.892 | 0.356 | 0.177 | 0.467 | -0.2463 | -0.2196 |
| 15 | short | atr_k3 | 0.535 | 0.74 | 75.2 | 5585 | 0.988 | 0.444 | 0.157 | 0.399 | -0.3904 | -0.3858 |
| 60 | long | cb_zone_5pct | 0.075 | 0.05 | 20.3 | 709 | 0.505 | 0.090 | 0.295 | 0.615 | -0.2277 | -0.1151 |
| 60 | long | atr_k0.5 | 0.090 | 0.06 | 21.0 | 719 | 0.512 | 0.099 | 0.291 | 0.611 | -0.2339 | -0.1199 |
| 60 | long | atr_k1 | 0.180 | 0.12 | 25.0 | 807 | 0.575 | 0.123 | 0.259 | 0.618 | -0.2426 | -0.1395 |
| 60 | long | atr_k1.5 | 0.269 | 0.18 | 29.3 | 896 | 0.639 | 0.148 | 0.233 | 0.618 | -0.2469 | -0.1577 |
| 60 | long | atr_k2 | 0.359 | 0.24 | 34.0 | 997 | 0.711 | 0.188 | 0.210 | 0.603 | -0.2445 | -0.1738 |
| 60 | long | atr_k3 | 0.537 | 0.36 | 44.2 | 1158 | 0.825 | 0.281 | 0.180 | 0.540 | -0.2698 | -0.2227 |
| 60 | short | cb_zone_5pct | 0.074 | 0.05 | 17.5 | 659 | 0.470 | 0.097 | 0.367 | 0.536 | -0.1855 | -0.0871 |
| 60 | short | atr_k0.5 | 0.089 | 0.06 | 18.2 | 672 | 0.479 | 0.106 | 0.360 | 0.534 | -0.1843 | -0.0883 |
| 60 | short | atr_k1 | 0.177 | 0.12 | 21.4 | 763 | 0.544 | 0.126 | 0.317 | 0.557 | -0.1794 | -0.0976 |
| 60 | short | atr_k1.5 | 0.266 | 0.18 | 25.3 | 854 | 0.609 | 0.174 | 0.280 | 0.546 | -0.1560 | -0.0950 |
| 60 | short | atr_k2 | 0.356 | 0.24 | 29.5 | 936 | 0.667 | 0.210 | 0.255 | 0.534 | -0.1772 | -0.1182 |
| 60 | short | atr_k3 | 0.534 | 0.36 | 39.0 | 1100 | 0.784 | 0.290 | 0.214 | 0.496 | -0.2147 | -0.1683 |
| 240 | long | cb_zone_5pct | 0.153 | 0.05 | 16.7 | 178 | 0.522 | 0.107 | 0.309 | 0.584 | -0.1971 | -0.1029 |
| 240 | long | atr_k0.5 | 0.091 | 0.03 | 15.9 | 171 | 0.501 | 0.117 | 0.322 | 0.561 | -0.1810 | -0.0908 |
| 240 | long | atr_k1 | 0.182 | 0.06 | 17.4 | 181 | 0.531 | 0.116 | 0.304 | 0.580 | -0.2130 | -0.1130 |
| 240 | long | atr_k1.5 | 0.272 | 0.09 | 19.1 | 188 | 0.551 | 0.122 | 0.287 | 0.590 | -0.2538 | -0.1399 |
| 240 | long | atr_k2 | 0.363 | 0.12 | 20.9 | 200 | 0.587 | 0.130 | 0.270 | 0.600 | -0.2780 | -0.1630 |
| 240 | long | atr_k3 | 0.543 | 0.18 | 24.7 | 226 | 0.663 | 0.159 | 0.239 | 0.602 | -0.2788 | -0.1848 |
| 240 | short | cb_zone_5pct | 0.148 | 0.05 | 12.6 | 156 | 0.457 | 0.154 | 0.295 | 0.551 | +0.0061 | +0.0028 |
| 240 | short | atr_k0.5 | 0.088 | 0.03 | 11.9 | 149 | 0.437 | 0.154 | 0.309 | 0.537 | +0.0043 | +0.0019 |
| 240 | short | atr_k1 | 0.177 | 0.06 | 13.1 | 159 | 0.466 | 0.164 | 0.289 | 0.547 | -0.0196 | -0.0092 |
| 240 | short | atr_k1.5 | 0.266 | 0.09 | 14.4 | 169 | 0.496 | 0.160 | 0.272 | 0.568 | -0.0522 | -0.0259 |
| 240 | short | atr_k2 | 0.354 | 0.12 | 15.9 | 179 | 0.525 | 0.184 | 0.257 | 0.559 | -0.0451 | -0.0237 |
| 240 | short | atr_k3 | 0.533 | 0.18 | 19.2 | 202 | 0.592 | 0.208 | 0.228 | 0.564 | -0.0490 | -0.0290 |

**Reading.** Wider shift → more fills, more wins, *and* more loss per candle: pnl/candle is
monotone decreasing in k at every tf/side (15 m: −0.10 → −0.15 → −0.43 % for 5 % → k1 → k3).
At tf 15 k = 1 is 5× the 5 % shift and fills 71 % of candles; at tf 240 k = 0.5 is the only
ATR shift tighter than 5 %, and it is marginally less bad (−0.110 vs −0.122 long). The only
non-negative cells are the pre-existing 240 short with S = bound − 1σ (+0.003 %/candle,
156 fills) and its k = 0.5 twin (+0.002 %). No ATR multiple improves on the 5 % rule;
the ordering "closer to the stop = less loss" is just fewer fills × ≈ −fee each.

### 8b. k = 0.3 (chart default since 2026-10-02), fine grid k ∈ {0.1, 0.2, 0.3, 0.5, 1}
Shift 0.054 % of price at k = 0.3 — between the 5 % rule's 0.037 % (tf 15) and 0.075 % (tf 60).
pnl/candle % (S = bound / S = bound − 1σ):

| tf | side | cb_zone 5 % | k 0.1 | k 0.2 | **k 0.3** | k 0.5 | k 1 |
|---|---|---|---|---|---|---|---|
| 15 | long | −0.100 / −0.096 | −0.096 / −0.092 | −0.100 / −0.096 | **−0.104 / −0.100** | −0.116 / −0.112 | −0.150 / −0.146 |
| 15 | short | −0.095 / −0.090 | −0.090 / −0.086 | −0.095 / −0.091 | **−0.099 / −0.095** | −0.107 / −0.103 | −0.137 / −0.133 |
| 60 | long | −0.102 / −0.115 | −0.091 / −0.104 | −0.091 / −0.105 | **−0.095 / −0.109** | −0.107 / −0.120 | −0.125 / −0.140 |
| 60 | short | −0.091 / −0.087 | −0.087 / −0.083 | −0.089 / −0.086 | **−0.092 / −0.088** | −0.092 / −0.088 | −0.100 / −0.098 |
| 240 | long | −0.122 / −0.103 | −0.103 / −0.084 | −0.105 / −0.086 | **−0.109 / −0.090** | −0.110 / −0.091 | −0.132 / −0.113 |
| 240 | short | −0.078 / +0.003 | −0.070 / +0.011 | −0.065 / +0.016 | **−0.072 / +0.009** | −0.079 / +0.002 | −0.090 / −0.009 |

k = 0.3 ≈ the 5 % rule at tf 15 (same shift size), slightly better at 60/240 where 5 % of a
wider span is a bigger shift. Still monotone: the smaller the shift the smaller the loss,
limit = never fill. In-zone rows at k = 0.3: 26.4/23.4, 19.5/17.0, 15.2/11.5 % (long/short,
tf 15/60/240).

## 9. "Extreme done" state (2026-10-02) — `run_extdone.py`
> Consolidated write-up (detection, cb-zone veto, extension quantiles): `results/extdone_zone_filter_results.md`.
Question: which level tells that the candle's high/low is already in? Answer: none —
first touch of any cb / cb±σ / cbnc level is followed by a further extreme or retouch
85–95 % of the time (continuation, not exhaustion). What predicts it is pull-away from the
running extreme in 1-min ATR × candle progress. Rule:
`done = (run_extreme − close)/atr1 ≥ d(progress)`, sticky within the candle; marker at the
first trigger minute. d per bucket = smallest grid value with EVENT-based
P(not touched again | first trigger) ≥ 0.90 (row-based conditionals overstate by 5–20 pts).
Sidecar `df_with_ext_done.pkl` (`{tf}_extdone_{high,low}[,_first,_lvl]`), viewer groups
`extdone_short` (high done) / `extdone_long` (low done), "x" markers on the 1-min chart.

### tf 15 high: ladder [(0.25, 4.0), (0.5, 2.5), (0.75, 1.0)] — triggers in 87.2 % of candles, median progress at trigger 0.80, P(hold | first trigger) 0.897

| progress | d (ATR) | first triggers | P(hold \| first trigger) | P(hold \| any done row) |
|---|---|---|---|---|
| 0.00-0.25 | — | 0 | — | — |
| 0.25-0.50 | 4.0 | 248 | 0.948 | 0.937 |
| 0.50-0.75 | 2.5 | 1875 | 0.935 | 0.933 |
| 0.75-1.00 | 1.0 | 2620 | 0.865 | 0.912 |

### tf 15 low: ladder [(0.25, 4.0), (0.5, 2.5), (0.75, 1.0)] — triggers in 84.6 % of candles, median progress at trigger 0.80, P(hold | first trigger) 0.896

| progress | d (ATR) | first triggers | P(hold \| first trigger) | P(hold \| any done row) |
|---|---|---|---|---|
| 0.00-0.25 | — | 0 | — | — |
| 0.25-0.50 | 4.0 | 318 | 0.921 | 0.904 |
| 0.50-0.75 | 2.5 | 1769 | 0.940 | 0.932 |
| 0.75-1.00 | 1.0 | 2483 | 0.863 | 0.911 |

### tf 60 high: ladder [(0.25, 8.0), (0.5, 5.0), (0.75, 3.0)] — triggers in 83.4 % of candles, median progress at trigger 0.67, P(hold | first trigger) 0.898

| progress | d (ATR) | first triggers | P(hold \| first trigger) | P(hold \| any done row) |
|---|---|---|---|---|
| 0.00-0.25 | — | 0 | — | — |
| 0.25-0.50 | 8.0 | 70 | 0.929 | 0.921 |
| 0.50-0.75 | 5.0 | 592 | 0.904 | 0.902 |
| 0.75-1.00 | 3.0 | 515 | 0.887 | 0.924 |

### tf 60 low: ladder [(0.25, 8.0), (0.5, 5.0), (0.75, 3.0)] — triggers in 78.0 % of candles, median progress at trigger 0.72, P(hold | first trigger) 0.895

| progress | d (ATR) | first triggers | P(hold \| first trigger) | P(hold \| any done row) |
|---|---|---|---|---|
| 0.00-0.25 | — | 0 | — | — |
| 0.25-0.50 | 8.0 | 68 | 0.941 | 0.929 |
| 0.50-0.75 | 5.0 | 504 | 0.905 | 0.908 |
| 0.75-1.00 | 3.0 | 519 | 0.879 | 0.915 |

### tf 240 high: ladder [(0.5, 12.0), (0.75, 8.0)] — triggers in 75.8 % of candles, median progress at trigger 0.75, P(hold | first trigger) 0.907

| progress | d (ATR) | first triggers | P(hold \| first trigger) | P(hold \| any done row) |
|---|---|---|---|---|
| 0.00-0.25 | — | 0 | — | — |
| 0.25-0.50 | — | 0 | — | — |
| 0.50-0.75 | 12.0 | 127 | 0.906 | 0.907 |
| 0.75-1.00 | 8.0 | 141 | 0.908 | 0.926 |

### tf 240 low: ladder [(0.5, 12.0), (0.75, 8.0)] — triggers in 71.0 % of candles, median progress at trigger 0.75, P(hold | first trigger) 0.936

| progress | d (ATR) | first triggers | P(hold \| first trigger) | P(hold \| any done row) |
|---|---|---|---|---|
| 0.00-0.25 | — | 0 | — | — |
| 0.25-0.50 | — | 0 | — | — |
| 0.50-0.75 | 12.0 | 120 | 0.925 | 0.915 |
| 0.75-1.00 | 8.0 | 130 | 0.946 | 0.948 |


## 10. Vetoed cb-zone marker → candle extreme (2026-10-03) — `run_zone_ext.py`
Markers = `cb_inzone_{side}` minus the extdone veto (the chart's current `cbzone_*`).
Per marker minute: remaining extension from the marker's 1-min low/high to the candle's
final low/high, and a Ridge (numpy StandardScaler+Ridge, α=1, same estimator as the bound
models) of that extension on the 15 forming-candle bound features + progress, pull-away,
1_low-below-cb in σ, atr1 % — fit on 2y marker rows (markers rebuilt there), tested on oos2m.

### Distribution per marker minute (oos2m)

| tf | side | markers | candles | at ext % | run=final % | ext % mean | median | sd | p75 | p90 | ext (1m ATR) mean | sd | ext (tf ATR) mean | from zone line % mean | sd |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 | long | 8836 | 2240 | 18.1 | 35.3 | 0.270 | 0.162 | 0.470 | 0.351 | 0.598 | 1.23 | 1.44 | 0.30 | 0.438 | 0.556 |
| 15 | short | 7254 | 1999 | 19.0 | 35.8 | 0.280 | 0.163 | 0.370 | 0.362 | 0.693 | 1.31 | 1.42 | 0.32 | 0.446 | 0.452 |
| 60 | long | 6310 | 512 | 4.7 | 23.2 | 0.772 | 0.548 | 0.844 | 1.003 | 1.629 | 3.36 | 3.24 | 0.43 | 1.132 | 1.038 |
| 60 | short | 5153 | 486 | 6.4 | 29.3 | 0.660 | 0.482 | 0.707 | 0.910 | 1.358 | 2.96 | 3.03 | 0.37 | 1.016 | 0.919 |
| 240 | long | 5866 | 146 | 1.7 | 21.0 | 1.761 | 1.161 | 2.469 | 1.964 | 3.735 | 6.66 | 5.90 | 0.48 | 2.470 | 2.861 |
| 240 | short | 3852 | 118 | 2.1 | 21.4 | 1.547 | 1.011 | 2.142 | 1.788 | 2.811 | 6.60 | 8.63 | 0.45 | 2.305 | 2.375 |

### By candle progress (oos2m, ext % mean / sd / at-ext %)

| tf | side | 0-25 % | 25-50 % | 50-75 % | 75-100 % |
|---|---|---|---|---|---|
| 15 | long | 0.351 / 0.607 / 19% (n2331) | 0.252 / 0.451 / 19% (n4900) | 0.207 / 0.220 / 14% (n1570) | 0.261 / 0.173 / 3% (n35) |
| 15 | short | 0.353 / 0.478 / 21% (n1926) | 0.267 / 0.337 / 19% (n4113) | 0.204 / 0.236 / 14% (n1195) | 0.307 / 0.185 / 0% (n20) |
| 60 | long | 0.934 / 0.997 / 5% (n1807) | 0.720 / 0.800 / 5% (n3599) | 0.651 / 0.609 / 4% (n887) | 0.797 / 0.137 / 0% (n17) |
| 60 | short | 0.769 / 0.884 / 7% (n1444) | 0.625 / 0.636 / 7% (n3081) | 0.572 / 0.534 / 4% (n619) | 0.890 / 0.553 / 0% (n9) |
| 240 | long | 1.980 / 3.002 / 2% (n1280) | 1.797 / 2.572 / 2% (n3271) | 1.457 / 1.355 / 1% (n1244) | 1.501 / 1.236 / 3% (n71) |
| 240 | short | 1.760 / 2.642 / 3% (n942) | 1.627 / 2.120 / 2% (n2230) | 0.991 / 1.106 / 2% (n662) | 1.000 / 0.612 / 0% (n18) |

### Ridge regression of ext % on market state

| tf | side | fit -> test | n train | n test | r² train | r² test | MAE model | MAE baseline | resid sd model | resid sd baseline | top coefficients |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 | long | 2y -> oos2m (15 bound feats + 4 state) | 67891 | 8836 | 0.157 | 0.158 | 0.229 | 0.221 | 0.430 | 0.470 | A_slope=+0.493, M_position=-0.425, R_slope=+0.313, R_distance=-0.285 |
| 15 | long | 2y -> oos2m (4 state feats only) | 67891 | 8836 | 0.118 | 0.139 | 0.224 | 0.221 | 0.435 | 0.470 | atr1_pct=+0.124, progress=-0.041, below_cb_sd=+0.027, pull_atr=-0.001 |
| 15 | long | oos2m first 75 % -> last 25 % | 6774 | 2062 | 0.233 | -0.056 | 0.236 | 0.230 | 0.375 | 0.365 | A_position=-0.594, A_slope=+0.426, M_slope=-0.180, V_std12=-0.163 |
| 15 | short | 2y -> oos2m (15 bound feats + 4 state) | 72851 | 7254 | 0.176 | 0.154 | 0.219 | 0.223 | 0.340 | 0.370 | A_slope=-0.263, M_position=+0.223, R_slope=-0.172, R_distance=+0.162 |
| 15 | short | 2y -> oos2m (4 state feats only) | 72851 | 7254 | 0.136 | 0.130 | 0.220 | 0.223 | 0.344 | 0.370 | atr1_pct=+0.091, progress=-0.032, below_cb_sd=+0.014, pull_atr=-0.007 |
| 15 | short | oos2m first 75 % -> last 25 % | 5442 | 1812 | 0.181 | 0.096 | 0.197 | 0.227 | 0.256 | 0.274 | A_position=+0.133, M_distance=+0.130, A_slope=-0.128, R_slope=-0.117 |
| 60 | long | 2y -> oos2m (15 bound feats + 4 state) | 46936 | 6310 | 0.223 | 0.164 | 0.500 | 0.524 | 0.772 | 0.844 | R_slope=-1.049, R_distance=+1.025, A_slope=+0.568, M_position=-0.522 |
| 60 | long | 2y -> oos2m (4 state feats only) | 46936 | 6310 | 0.187 | 0.159 | 0.499 | 0.524 | 0.774 | 0.844 | atr1_pct=+0.365, progress=-0.068, pull_atr=+0.065, below_cb_sd=+0.002 |
| 60 | long | oos2m first 75 % -> last 25 % | 4843 | 1467 | 0.346 | 0.241 | 0.522 | 0.547 | 0.692 | 0.801 | A_position=+0.803, R_position=-0.668, R_slope=+0.606, R_distance=-0.502 |
| 60 | short | 2y -> oos2m (15 bound feats + 4 state) | 48274 | 5153 | 0.207 | 0.122 | 0.458 | 0.456 | 0.661 | 0.707 | A_slope=+0.368, R_distance=-0.282, R_slope=+0.273, M_position=-0.254 |
| 60 | short | 2y -> oos2m (4 state feats only) | 48274 | 5153 | 0.175 | 0.086 | 0.464 | 0.456 | 0.673 | 0.707 | atr1_pct=+0.247, progress=-0.075, pull_atr=+0.056, below_cb_sd=+0.042 |
| 60 | short | oos2m first 75 % -> last 25 % | 3813 | 1340 | 0.228 | -0.049 | 0.339 | 0.385 | 0.424 | 0.414 | A_position=-0.489, M_slope=+0.470, A_slope=-0.386, R_slope=-0.349 |
| 240 | long | 2y -> oos2m (15 bound feats + 4 state) | 47743 | 5866 | 0.248 | 0.263 | 1.142 | 1.243 | 2.120 | 2.468 | R_slope=-9.818, R_distance=+9.813, A_slope=+5.194, M_position=-4.390 |
| 240 | long | 2y -> oos2m (4 state feats only) | 47743 | 5866 | 0.193 | 0.188 | 1.126 | 1.243 | 2.218 | 2.468 | atr1_pct=+0.668, pull_atr=+0.396, progress=-0.166, below_cb_sd=+0.113 |
| 240 | long | oos2m first 75 % -> last 25 % | 4501 | 1365 | 0.595 | -2.744 | 1.834 | 1.159 | 2.274 | 1.240 | A_position=-4.134, R_distance=+3.613, V_std12=-3.531, R_slope=-3.321 |
| 240 | short | 2y -> oos2m (15 bound feats + 4 state) | 53265 | 3852 | 0.231 | -0.051 | 1.102 | 1.064 | 2.190 | 2.142 | A_slope=-2.442, M_position=+1.831, M_slope=+1.197, atr1_pct=+0.340 |
| 240 | short | 2y -> oos2m (4 state feats only) | 53265 | 3852 | 0.202 | -0.006 | 1.088 | 1.064 | 2.144 | 2.142 | atr1_pct=+0.565, pull_atr=+0.146, below_cb_sd=-0.117, progress=-0.097 |
| 240 | short | oos2m first 75 % -> last 25 % | 2974 | 878 | 0.439 | -2.856 | 1.561 | 1.065 | 1.897 | 0.996 | A_position=+2.832, V_absmean12=+1.771, V_std12=-1.633, M_slope=-1.548 |

**Reading.** The marker is NOT the extreme: only 2–19 % of marker minutes are the candle low;
median remaining extension 0.16 / 0.55 / 1.16 % (tf 15/60/240) ≈ 0.3–0.5 tf-ATR, with sd
≥ mean (right-skewed, fat tail: p90 = 0.6 / 1.6 / 3.7 %). Ridge on market state explains
r² 0.12–0.26 OOS at 15/60 and 240-long; 240-short negative; oos2m-internal split unstable
(n small, 240 r² < −2). Residual sd shrinks 8–14 % vs the unconditional sd — the same
"volatility-scale, not timing" signal as the bound models (atr1_pct dominates the 4-state
fit). Verdict: a linear state model is applicable only as a scale estimator (expected
further extension ≈ k·ATR with k by tf and progress); it does not tell where the low lands.
