# Candle Bounds Estimation — Results

**Date:** 2026-07-21
**Spec:** `candle_bounds_estimation.md`
**Data:** train = `2y_az` (2023-01-01 → 2024-12-31, LINK/USDT), OOS = `oos2m` (2025-01-01 → 2025-03-01)
**Scope:** 3 tf × 2 sides = 6 combos. Read-only over the wide df; scripts in scratchpad, no repo change.

## Headline

RSI-group → next-candle extension carries a **real, stable, but weak** linear signal.
r² ≈ 0.020–0.026 on OOS, essentially identical to train (0.020–0.028) — **no overfit**,
correlation 0.16–0.18 on every combo. It shifts the band centre by ≈ ±0.3σ against a
residual spread of ≈ 0.88σ. **Not strong enough on its own to size target levels.**

## Setup

Action space updated per spec:

- `diff_prc` — candle-to-candle % change of the closed-candle high (or low)
- `diff_prc_rm` — `rolling(6).mean()` (unchanged)
- **`full_std`** — std of `(diff_prc − diff_prc_rm)` over the **whole train range**, frozen.
  Replaces the rolling(6) std. This is now the single σ in the system.
- `z = clamp((diff_prc − diff_prc_rm) / full_std, −3, +3)`
- Predictor: **previous** closed candle's RSI group (position = `rsi_ma8`,
  slope = candle-to-candle Δ`rsi_ma8`, distance = `rsi_14 − rsi_ma8`)
- Target: **current** candle's `z`. OLS plane. `z_std` = residual std, frozen on train.

Two spec ambiguities resolved (see Open items):
sign of `z`, and RSI slope computed at candle granularity rather than 1-minute.

### Frozen parameters

| combo | n_train | full_std % | z_std | intercept | position | slope | distance |
|---|---|---|---|---|---|---|---|
| 15_high | 70163 | 0.3602 | 0.878 | 0.7581 | −0.01512 | +0.0831 | −0.0150 |
| 15_low | 70163 | 0.4273 | 0.816 | 0.6610 | −0.01314 | −0.3257 | +0.0977 |
| 60_high | 17535 | 0.7347 | 0.889 | 0.6939 | −0.01379 | −0.2204 | +0.0704 |
| 60_low | 17535 | 0.8624 | 0.840 | 0.5889 | −0.01163 | −0.1946 | +0.0563 |
| 240_high | 4379 | 1.4737 | 0.912 | 0.7035 | −0.01391 | −0.4149 | +0.1242 |
| 240_low | 4379 | 1.7266 | 0.859 | 0.5912 | −0.01159 | −0.0670 | +0.0180 |

## Fit quality

| combo | r²_train | r²_OOS | corr_OOS |
|---|---|---|---|
| 15_high | 0.0275 | 0.0243 | 0.161 |
| 15_low | 0.0233 | 0.0248 | 0.163 |
| 60_high | 0.0254 | 0.0256 | 0.169 |
| 60_low | 0.0197 | 0.0223 | 0.160 |
| 240_high | 0.0257 | 0.0233 | 0.178 |
| 240_low | 0.0201 | 0.0200 | 0.167 |

r²_OOS ≈ r²_train on all six. The plane generalizes; it is simply small.

## What the coefficients say

The pattern is consistent across every timeframe and side:

- **`position` dominates and is negative** (−0.012 to −0.015 per RSI point). Low RSI → the
  next candle's extreme extends **more** than its recent average; high RSI → **less**.
  Mean reversion, expressed in extension rather than direction.
- **`slope` mostly negative** (−0.07 to −0.41; 15_high is the lone positive outlier).
- **`distance` mostly positive** (+0.02 to +0.12).

Magnitude: across RSI 30 → 70, `position` alone swings the prediction ≈ **±0.28 z**.
Residual `z_std` ≈ 0.86–0.91. Signal-to-noise ≈ **0.3**.

## Band coverage (spec Result item 2)

Band = `diff_prc_rm + (z_infered ± z_std) · full_std`. Fraction of realized OOS `diff_prc`
landing inside:

| combo | model | baseline (z_inf=0) | gain | Gaussian ref |
|---|---|---|---|---|
| 15_high | 0.5381 | 0.5310 | +0.7 pp | 0.6827 |
| 15_low | 0.5876 | 0.5807 | +0.7 pp | 0.6827 |
| 60_high | 0.5756 | 0.5664 | +0.9 pp | 0.6827 |
| 60_low | 0.5962 | 0.5919 | +0.4 pp | 0.6827 |
| 240_high | 0.5937 | 0.5850 | +0.9 pp | 0.6827 |
| 240_low | 0.5620 | 0.5562 | +0.6 pp | 0.6827 |

Two readings:

1. **Coverage is well below Gaussian.** A ±1σ band should hold 68.3% of a normal
   distribution; it holds 54–60% here. The residual is fat-tailed — a ±1·z_std band is
   materially thinner in practice than its label suggests.
2. **The model barely beats the baseline.** Knowing the RSI group adds 0.4–0.9 pp of
   coverage over just centring on `diff_prc_rm`. MAE improves 1.0–1.4% (e.g. 60_high
   0.7748 vs 0.7850).

## Is the plane the limitation?

No. GradientBoostingRegressor (200×depth-3, 80/20 chronological holdout) on the same three
features:

| combo | r² linear OOS | r² GBR holdout |
|---|---|---|
| 15_high | 0.0243 | 0.0355 |
| 15_low | 0.0248 | 0.0346 |
| 60_high | 0.0256 | 0.0263 |
| 60_low | 0.0223 | 0.0159 |
| 240_high | 0.0233 | **−0.0421** |
| 240_low | 0.0200 | −0.0039 |

Nonlinearity buys a little at tf15 (most candles), nothing at tf60, and is actively harmful
at tf240 where only 4,379 closed candles exist. **The ceiling is in the features, not the
model class.** Linear is the correct choice at 60/240.

## Artifacts

- `~/action_zones_plots/candle_bounds/rsi_vs_z.html` — spec Result item 1. Interactive 3D
  scatter, axes = RSI position/slope/distance, colour = `z` (RdBu, ±3), 10k-point subsample
  per combo, dropdown across all six. Plotly inlined, opens offline.
- `~/action_zones_plots/candle_bounds/oos_bounds.html` — spec Result item 3 (standalone
  form). Predicted bound + ±z_std band vs realized extreme across the OOS window.

## Open items

1. **Spec sign ambiguity.** Line 6 says "std of diff_prc *from* diff_prc_rm"; line 7 writes
   "diff_prc_rm − diff_prc". Implemented as `(diff_prc − diff_prc_rm)/full_std` so positive
   `z` = moved more than recent average, matching the action-space `ma + x·σ` shape. Flipping
   it negates every coefficient and changes nothing else.
2. **RSI slope granularity.** Computed candle-to-candle on the closed sequence, not the
   1-minute `.diff()` that `azlib.indicators.raw_attribute` uses. "For each closed candle
   calculate RSI-group" reads as candle granularity; the 1-minute version is a different
   (much smaller) quantity and untested here.
3. **Train vs OOS coverage are not directly comparable.** Train coverage (0.760–0.777) is
   measured on *clamped* `z`, which compresses the tails; OOS coverage is measured on raw
   realized `diff_prc`. The OOS figures are the meaningful ones.
4. **Spec Result item 3 wanted the bounds on "the full view"** (the viewer at
   localhost:8080). Delivered as a standalone plotly chart instead — wiring the viewer
   touches existing tracked files and needs its own branch. Not done.

## Conclusion

The experiment answers its question cleanly, and the answer is mostly negative:
**an RSI group alone does not carry enough information to set candle bounds.** It is a real
effect — stable across 6 combos and across a train/OOS split, directionally sensible
(mean reversion) — but it moves the band centre ~0.3σ against ~0.88σ of noise, and buys
under 1 pp of coverage.

`full_std` is a clear improvement regardless of the regression outcome: one frozen,
closed-candle σ replaces the rolling(6) σ, which removes the varying-scale problem that
made a fixed `x` grid mean different things at different timeframes.

Useful next steps, in order of expected value:

- **Add features before adding model complexity.** GBR shows the three RSI attributes are
  exhausted. → **Done, see Round 2 below. Outcome overturns the conclusion above.**
- **Widen the band.** A ±1·z_std band holds 54–60%. If the band is meant to bound a target,
  pick the multiplier from the empirical quantile, not from 1σ.
- **Predict spread, not just centre.** The residual is fat-tailed and probably
  heteroskedastic; a model for `z_std` conditional on state may be worth more than a better
  point estimate of `z`.

---

# Round 2 — Feature Expansion

**Date:** 2026-07-21. Same split, same closed-candle frame.

## Metric correction (why Round 1 understated everything)

Round 1 measured r² against `z = (diff_prc − diff_prc_rm)`. That target is contaminated by
its own construction: `diff_prc_rm[k]` contains `diff_prc[k−1..k−5]`, which are known at
k−1. Under iid returns a model gets r² = (5/36)/(30/36) = **0.167 for free**. Measured
`only_P` was 0.152–0.205 — the artifact, not signal.

Switching to `resid = d[k] − rm[k−1]` (no overlap) did not fix it: that target still
contains the *known* term `−rm[k−1]`, worth another `1/7 ≈ 0.143`.

**Final framing: predict `diff_prc[k]` directly, standard r² against the train mean.**
Floor is 0. Two controls confirm it: a shuffled-target fit scores −0.037 to +0.002, and
time-of-day scores −0.012 to +0.003.

## Feature blocks

| block | features |
|---|---|
| R | RSI position, slope, distance |
| M | MACD position, slope, distance (hist) |
| A | MA position, slope |
| V | rolling(12) std of diff_prc, rolling(12) mean abs, prev candle range %, prev candle body % |
| P | prev residual ×2, `diff_prc_rm[k−1]` |
| T | sin/cos hour, sin/cos day-of-week |
| X | higher-timeframe RSI position |

All evaluated at candle k−1. Ridge(α=1) on standardized features.

## OOS r² (vs train mean, floor 0)

| combo | **rm itself** | only_R | only_M | only_A | **only_V** | only_P | only_T | only_X | ALL |
|---|---|---|---|---|---|---|---|---|---|
| 15_high | **−0.155** | 0.097 | 0.120 | 0.038 | **0.318** | 0.028 | −0.001 | 0.000 | 0.354 |
| 15_low | **−0.162** | 0.094 | 0.150 | 0.035 | **0.363** | 0.016 | −0.001 | 0.000 | 0.380 |
| 60_high | **−0.173** | 0.114 | 0.154 | 0.039 | **0.324** | 0.027 | −0.002 | 0.001 | 0.363 |
| 60_low | **−0.184** | 0.093 | 0.140 | 0.025 | **0.320** | 0.013 | −0.004 | 0.000 | 0.340 |
| 240_high | **−0.192** | 0.103 | 0.075 | 0.037 | **0.258** | 0.026 | 0.003 | — | 0.306 |
| 240_low | **−0.245** | 0.080 | 0.107 | 0.013 | **0.375** | 0.009 | −0.012 | — | 0.403 |

## Three findings that change the design

**1. `diff_prc_rm(6)` is worse than a constant.** r² = −0.155 to −0.245. The 6-candle
rolling mean is a *negative-value* predictor of the next candle's move — it adds noise
without signal. **The action space currently centres its band on this.** That is a defect
in the part of the system we assumed was correct.

**2. Volatility dominates; RSI is a minor player.** `only_V` (0.258–0.375) is **3–4×**
`only_R` (0.080–0.114). Ablation agrees — removing V costs the most on every combo
(e.g. 240_low 0.403 → 0.324), removing R costs almost nothing (0.354 → 0.350). And
`R+V ≈ only_V`: RSI adds essentially nothing on top of volatility.

**3. MACD beats RSI** on 4 of 6 combos. This contradicts the earlier 40nb result that
RSI-3D-gbr was the best predictor — but that was predicting `label_coeff`, a different
target. For *candle extension*, MACD > RSI.

Time-of-day and cross-timeframe RSI are worthless (r² ≈ 0). Drop them.

## Decision metrics (band = train-frozen residual sd)

| combo | band_rm | band_R | **band_ALL** | narrower | cov_rm | cov_R | **cov_ALL** | mae_rm | mae_R | **mae_ALL** |
|---|---|---|---|---|---|---|---|---|---|---|
| 15_high | 0.427 | 0.372 | **0.309** | −27.7% | 0.660 | 0.662 | 0.659 | 0.4062 | 0.3532 | **0.2971** |
| 15_low | 0.507 | 0.448 | **0.382** | −24.6% | 0.732 | 0.750 | **0.776** | 0.4123 | 0.3542 | **0.2850** |
| 60_high | 0.870 | 0.757 | **0.631** | −27.5% | 0.691 | 0.701 | 0.659 | 0.7865 | 0.6723 | **0.5912** |
| 60_low | 1.018 | 0.904 | **0.766** | −24.7% | 0.721 | 0.747 | **0.773** | 0.8556 | 0.7273 | **0.6078** |
| 240_high | 1.744 | 1.518 | **1.268** | −27.3% | 0.686 | 0.704 | 0.698 | 1.5651 | 1.3261 | **1.1359** |
| 240_low | 2.040 | 1.819 | **1.515** | −25.7% | 0.669 | 0.701 | **0.765** | 1.9452 | 1.6019 | **1.2093** |

The full model's band is **~25–28% narrower** than the `rm`-centred band while holding
coverage flat or better. MAE improves **27–38%** over `rm`, and **16–25%** over RSI-only.
A narrower band at equal coverage is exactly what a target-level estimator needs.

## Revised conclusion

Round 1's negative verdict was a measurement artifact plus the wrong feature set. With a
clean metric and volatility features, next-candle extension **is** predictable to
r² ≈ 0.31–0.40 out of sample, and the resulting bound is materially tighter than the
current action space's.

Consequences for the rework:

- **Re-centre the action space.** `diff_prc_rm(6)` is a negative-skill predictor. Replace
  it with the model's own prediction; keep `full_std` for scaling.
- **Volatility features are the core**, not the indicator groups. RSI/MACD are secondary
  refinements worth ~0.03–0.05 r² on top of V.
- **Caveat before building on this.** Much of V's power is reversion of the running extreme
  relative to its own reference (`high[k−1]` appears in both the feature and the target's
  denominator). This is look-ahead free and usable at k−1's close, but it is a scale effect,
  not a market-timing edge. Verify it survives translation into realized R before trusting
  it to size targets — the Fix 2 lesson from `zone_selection_2y_results.md` applies.
  → **Done, see Round 3. It does not — and neither can anything else.**

---

# Round 3 — Does the bound edge translate into realized R?

**Date:** 2026-07-21.

## Test design

Deliberately isolates target/stop quality by holding entry constant:

- Entry: close of candle k−1, **every candle**, no selectivity.
- Long: target = predicted `high[k]`, stop = predicted `low[k]`. Short mirrored.
- Level shift swept over `m ∈ {−1, −0.5, 0, +0.5, +1}` × that variant's own band sd.
- First-touch walk over candle k's `tf` 1-minute rows, stop wins same-minute ties.
- `R = reward_dist/risk_dist` on a win, `−1` on a stop. Fee charged as
  `2·fee·entry/risk_dist` (fees in R units).
- Models frozen on 2y_az, evaluated on oos2m. 146 (tf × direction × shift × variant) cells.

## Result

| | median | mean |
|---|---|---|
| **Gross R** | −0.125 | **+0.007** |
| **Net R** | −1.293 | −2.302 |
| win rate | 0.498 | — |

By variant (median):

| variant | gross R | net R |
|---|---|---|
| const | −0.116 | −1.358 |
| R | −0.116 | −1.032 |
| M | −0.157 | −1.317 |
| **V** | −0.134 | −1.630 |
| ALL | −0.079 | −1.351 |

## Interpretation — the test is null by construction, and that is the finding

Gross R averages **+0.007** across 146 cells, with a **0.498** win rate. Every variant is
indistinguishable from every other and from zero. This is not a failure of the V model; it
is arithmetic:

> **Target/stop placement cannot create edge.** On an unconditionally-entered position,
> expected value is zero before costs no matter where the levels sit. Moving levels
> reshapes the R *distribution* — win rate up, R-multiple down, or the reverse — but cannot
> move its *mean*. Only deciding **when to enter** can do that.

Fees then convert "zero" into "badly negative": net median −1.29R. The mechanism is
`fee_R = 2·fee·entry/risk_dist` — a tight stop makes fees enormous in R terms. The −17.05R
outlier is a near-zero `risk_dist`, not a modelling error.

## What this means for the rework

1. **The Round 2 result stands, but its value is not alpha.** The V-driven bound really is
   25–28% narrower at equal coverage. That is worth having — accurate bounds mean accurate
   R:R accounting and better capital efficiency — but it is a *sizing* improvement, not a
   source of profit.
2. **User point 2 is necessary but not sufficient.** Making target/SL depend on market
   conditions fixes a genuine defect (the current selection is unconditional and
   unit-inconsistent), but no target/SL scheme, however good, generates return on its own.
3. **User point 3 is the load-bearing one.** The entry zone currently marks 84–100% of rows,
   i.e. it is very nearly unconditional — which puts the existing system in exactly the
   regime this test just showed has zero expectation. **All available edge must come from
   entry selectivity.** That is where the rework's effort belongs.
4. **Fee-aware stop sizing is not optional.** Any design that can select a `risk_dist` small
   relative to `2·fee·entry` will be destroyed by costs regardless of its hit rate. The stop
   distance needs a floor expressed in fee multiples.

## Caveats

- One pair (LINK/USDT), one 2-month OOS window.
- Entry is deliberately unconditional; this test cannot and does not rule out that better
  bounds outperform worse bounds *once a selective entry rule exists*. It shows only that
  bounds alone are not a source of edge.
- Gross R mean (+0.007) and median (−0.125) disagree in sign because the distribution is
  right-skewed — consistent with noise around zero, not with a small positive edge.
