# Candle Bounds Prediction — Algorithm

**Date:** 2026-07-21
**Status:** validated on 2y_az → oos2m. See `candle_bounds_estimation_results.md` for numbers.
**Purpose:** predict, at the close of candle *k−1*, where candle *k*'s high and low will land,
plus an uncertainty band around each.

Two independent models per timeframe — one for the high bound, one for the low bound.
Six models total across tf ∈ {15, 60, 240}.

---

## 1. Closed-candle reduction

Everything operates on **completed candles**, never on the per-minute forming series.

```
closed = wide_df[f"{tf}_is_closed"] == True
ext[k] = wide_df.loc[closed, f"{tf}_{side}"]        # side ∈ {high, low}
```

At an `is_closed` row the forming cummax/cummin equals that candle's final value, so `ext`
is the true per-candle extreme sequence, indexed by each candle's closing timestamp.

This matters: the wide df's `{tf}_high_diff_prc` column is a *forming* quantity (65% of its
values are negative because a partial candle has not yet caught up to the previous full
one). It is **not used anywhere** in this algorithm.

## 2. Target

```
d[k] = (ext[k] − ext[k−1]) / ext[k−1] × 100        # percent, candle-to-candle
```

`d[k]` is predicted **directly**. Earlier versions predicted a z-score of the residual from
a rolling mean and reconstructed `d` afterwards; that detour cost most of the signal
(MAE gain −1.3% vs −13..−17% for identical features). Do not reintroduce it.

## 3. Features

All evaluated on the **closed-candle sequence** at index *k−1*, so every value is known at
the moment candle *k* begins. Let `rm = d.rolling(6).mean()`.

| block | feature | definition (at k−1) |
|---|---|---|
| R | `R_position` | `{tf}_rsi_ma8` |
| R | `R_slope` | Δ`{tf}_rsi_ma8` (candle-to-candle) |
| R | `R_distance` | `{tf}_rsi_14 − {tf}_rsi_ma8` |
| M | `M_position` | `{tf}_macd_12_26_9` |
| M | `M_slope` | Δ`{tf}_macd_12_26_9` |
| M | `M_distance` | `{tf}_macd_hist_12_26_9` |
| A | `A_position` | `({tf}_close − {tf}_ema_25) / {tf}_close × 100` |
| A | `A_slope` | Δ`{tf}_ema_25` |
| **V** | `V_std12` | `d.rolling(12).std()` |
| **V** | `V_absmean12` | `d.abs().rolling(12).mean()` |
| **V** | `V_range` | `({tf}_high − {tf}_low) / {tf}_low × 100` |
| **V** | `V_body` | `({tf}_close − {tf}_open) / {tf}_open × 100` |
| P | `P_z1` | `(d − rm.shift(1))` at k−1 |
| P | `P_z2` | `(d − rm.shift(1))` at k−2 |
| P | `P_rm` | `rm[k−1]` |

**V is the dominant block** — alone it reaches r² 0.26–0.38 versus 0.08–0.11 for R.
Ablation confirms it: removing V costs more than removing everything else combined.

Two blocks were tested and **dropped** for zero contribution (r² ≈ 0.000, within noise of a
shuffled-target control): time-of-day (sin/cos hour, sin/cos day-of-week) and
cross-timeframe RSI position.

## 4. Model

```python
model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
model.fit(X_train, d_train)
```

Linear, deliberately. GradientBoosting was tested on the RSI block: it helps slightly at
tf15, is neutral at tf60, and scores **−0.042** at tf240, where only 4,379 closed candles
exist in two years. The data volume does not support a nonlinear model at coarse
timeframes.

## 5. Band

The uncertainty band is the **in-sample residual standard deviation, frozen on train**:

```python
band_pct = std(d_train − model.predict(X_train), ddof=1)
```

One scalar per (tf, side). Never recomputed on OOS or live data — that is what keeps
application look-ahead free.

## 6. Inference

At the close of candle *k−1*:

```python
pred_pct   = model.predict(features[k−1])          # percent move
bound_px   = ext[k−1] × (1 + pred_pct / 100)       # predicted extreme, price
band_px    = ext[k−1] × band_pct / 100             # band half-width, price
upper      = bound_px + band_px
lower      = bound_px − band_px
```

`ext[k−1]` is the previous candle's own high (for the high model) or low (for the low
model) — the same reference the percentage change was measured against.

The four values are then **held constant across every 1-minute row of candle k**, matching
`azlib.space.price_levels`' broadcast convention: computed at candle *k−1*'s closing minute,
shifted forward one row, forward-filled through candle *k*. A forming candle's own data
never influences its own bounds.

## 7. Frozen parameters

Per (tf, side), persisted for inference: the fitted `StandardScaler` mean/scale, the Ridge
coefficients and intercept, and `band_pct`. Nothing else is needed.

---

## Validated performance (2y_az train → oos2m)

| combo | r² OOS | MAE vs `diff_prc_rm` baseline | band vs baseline | coverage |
|---|---|---|---|---|
| 15_high | 0.354 | −26.9% | −27.7% | 0.659 |
| 15_low | 0.380 | −30.8% | −24.6% | 0.776 |
| 60_high | 0.363 | −24.7% | −27.5% | 0.659 |
| 60_low | 0.340 | −28.9% | −24.7% | 0.773 |
| 240_high | 0.306 | −27.4% | −27.3% | 0.698 |
| 240_low | 0.403 | −37.5% | −25.7% | 0.765 |

Controls: shuffled-target fit scores −0.037 to +0.002; time-of-day scores −0.012 to +0.003.

## Known limitations

1. **This is a sizing tool, not an alpha source.** Round 3 tested it as a target/stop
   placement rule with unconditional entry: gross R across 146 configurations averaged
   +0.007 with a 0.498 win rate. Level placement cannot move expected value — only entry
   selection can. The bound's value is accurate R:R accounting and a tighter band, not
   return.
2. **`V_range` shares a term with the target.** `ext[k−1]` appears in both `V_range` and the
   denominator of `d[k]`, so part of V's power is reversion of an extreme toward its own
   reference. Look-ahead free and usable at k−1's close, but a scale effect rather than a
   market-timing edge.
3. **Validated on one pair (LINK/USDT), one 2-month OOS window.** Coverage of a ±1-band is
   0.66–0.78 — below the 0.68 a Gaussian would give on several combos, i.e. the residual is
   fat-tailed. Any use needing a specific confidence level should set the multiplier from
   the empirical quantile, not from 1σ.
4. **`diff_prc_rm(6)` scored r² −0.155 to −0.245** as a predictor — worse than a constant.
   The existing action space centres its band on exactly this quantity.
