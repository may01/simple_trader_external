# Zone Selection Experiment — Validated Design

**Date:** 2026-07-18
**Source requirements:** `external/docs/superpowers/experiment/zone_selection.md`
**Status:** design approved in brainstorming; pending user spec review → implementation plan.

## Purpose

On 1-minute data, define price **zones** that identify the best 1-min candles to
enter (buy for long / sell for short), where the zone bounds are derived from the
predicted high/low range of the enclosing higher-timeframe candle. For each zoned
entry, also emit a target level, a stop-loss level, and a risk/reward ratio, and
prove the entries are profitable against candle size + fees on out-of-sample data.

## Scope (decisions)

- **Output:** entry zone **and** target + stop-loss + R/R (full action-level system).
- **Price space:** spec-native `diff_prc_ma ± X*std` (percentage-change space). No ATR
  sizing for the action levels.
- **diff_prc reference:** percentage change of the higher-TF candle's high (and low)
  versus the **previous same-TF candle's** high (and low). Matches existing
  `price_derivatives` columns.
- **Target/SL selection:** R/R grid-search over X (§5-native).
- **Validation metric:** maximize strict-label coverage inside the zone **and** require
  profitable realized R/R of zoned entries. The original "minimize non-strict in zone"
  clause is dropped as self-contradictory (non-strict labels are themselves profitable).
- **Cross-TF scope:** matched only — indicator TF = label TF, for {15, 60, 240}.
  Full cross-product deferred.
- **§2 "next value prediction":** cut (YAGNI — the predicted next diff_prc is never
  consumed; levels use current `diff_prc_ma ± X*std` directly).
- **§6 "market-condition X selection":** folded into §9–11 — the indicator→label_coeff
  regression plus the Y sweep *is* the market adaptation; there is no separate X-picker.
- **"Kalman filter" (§11.2):** renamed to inverse-variance fusion (static fusion of
  independent per-group estimates, not a time-sequential Kalman filter).
- **Naming:** the module/artifacts are called **`action_zones`**, never `levels`
  (`levels.py` already means support/resistance).

## Reuse map (existing code — do not rebuild)

| Concept | Existing |
|---|---|
| diff_prc, diff_prc_ma | `indicators/library/price_derivatives.py` — `{src}_diff_prc`, `_diff_prc_rm_{w}` (= ma). **Plain per-series std (`high_std`, `low_std`) is NOT precomputed** — add as rolling std of `high_diff_prc` / `low_diff_prc` (one line; sided `_std_above/below` exist but are not used). |
| strict labels | `profit_strict_long/short` → `{tf}_pslong/psshort_...` |
| non-strict sibling labels | `profit_long/short` → `{tf}_plong/pshort_...` |
| z-score / stat freeze + persist | `indicators/attributes.py` `DataAttributes` |
| RSI / MACD / EMA / trailing slope | `oscillators.py`, `momentum.py`, `trend.py`, `nn_features.py` `_slope` (OLS) |
| zone markers on full charts | `view_full.py` |

## Pipeline

### 1. Action space (per higher-TF candle; TF ∈ {15, 60, 240})

Levels are computed in percentage-change space, then **converted back to price** — the
coeff is computed in price space (X capped at 2.0):

```
# percentage-change levels (diff_prc is ×100 percent, see price_derivatives.py)
high_level(X) = high_diff_prc_ma + X * high_std
low_level(X)  = low_diff_prc_ma  - X * low_std

# back to price, referenced to the PREVIOUS same-TF candle's high/low
# (diff_prc is a pct change vs the previous same-TF candle):
price_high_level = prev_high * (1 + high_level(2.0) / 100)
price_low_level  = prev_low  * (1 + low_level(2.0)  / 100)   # low_level(2.0) < 0 → below prev_low

# coeff lives in PRICE space:
cur_price = 1-min close
coeff = clamp( (cur_price - price_low_level)
               / (price_high_level - price_low_level), 0, 1 )
```

`coeff 0` = `price_low_level`, `coeff 1` = `price_high_level`. `coeff(·)` is a general
price→position map; `cur_price = close` above is the generic marker. The specific price
plugged in depends on use: **label_coeff** uses the entry extreme — 1-min low (long) /
1-min high (short) — per §2 and pessimistic fill; **zone marking** uses the same extreme
per §7.

> Unit note: `high_level` is a percent (diff_prc is scaled ×100 in
> `price_derivatives.py`), so the price conversion uses `prev * (1 + level/100)`.
> If diff_prc is later stored as a raw fraction instead of percent, drop the `/100`.

### 2. label_coeff (§8)

- Strict labels = existing `{tf}_pslong/psshort` (ATR-outcome ground truth: "was this
  a good entry"). Non-strict siblings = `plong/pshort`, used only for extended
  validation (non-strict positives are still profitable).
- Entry price = 1-min **low** for long, 1-min **high** for short (pessimistic fill,
  identical to the label definition).
- `label_coeff = coeff(entry_price)`. Defined for every row; regression consumes it at
  labeled rows.

### 3. Indicator → label_coeff (§9, matched TF)

For each trend indicator, attributes: position, slope, distance (distance optional for
MA). Each z-scored and clamped to [-3, +3] (reuse `DataAttributes` + `_slope`).

**Regression (§9.1) AND classification (§9.2) run for every dimensionality — 1D, 2D,
and 3D.** Attributes are grouped within a single indicator space only (RSI+RSI,
MACD+MACD, MA+MA — no cross-indicator mixing). Dimensionality = number of attributes fed
as inputs:

- **1D:** each single attribute → label_coeff.
- **2D:** each same-space attribute pair → label_coeff.
- **3D:** each same-space attribute triple → label_coeff.

For **every** input group at **every** dimensionality:

- **§9.1 Regression:** linear + non-linear candidates; predict label_coeff mean & std;
  save all params to a reproducible report; propose a labeling rule from the fit and
  estimate its error.
- **§9.2 Classification:** two classes (label=0 / label=1, label=1 the target class);
  report classification error where label=0 is mistaken for label=1; save reproducible
  results for cross-model comparison.
- **Charts:** 1D and 2D save a chart with the fitted function/boundary and label=1 /
  label=0 points overlaid. 3D is not plotted (results saved to report only).

### 4. Human model validation (§10)

Manual checkpoint: iterate §9, select the best regression/classification models per
group for use in inference.

### 5. Inference + fusion + Y (§11)

- **5.1** Run selected regression models over the dataset → per-group (mean, std) of
  label_coeff for each point.
- **5.2** **Inverse-variance fusion** across groups → single (mean, std) per point.
- **5.3/5.4** `inferred_label_coeff = mean + Y*std`; sweep Y ∈ [-2.0, 2.0] step 0.1.
  Choose Y that maximizes strict coverage under the profitable-R/R constraint (§7).
  Save Y-sweep report + charts.

### 6. Exit levels + R/R (§4–5, grid-search)

Separately for long and short:

- Sweep target-X and SL-X over [0, 2.0].
- `R/R = P(target) / P(stop)`; keep combos where `reward * P(target) − fees` is
  profitable against candle size. **Fees are a parameter of the experiment.**

### 6.1 Reach-probability estimator (hybrid empirical + parametric tail)

The reach-probability is a **touch / first-passage** probability, not a terminal
distribution: for a level at `X` std above/below the mean it is the tail of the
**extreme** (high / low) diff_prc distribution.

```
P_reach(level) = fraction of train candles where high_diff_prc >= level   # upper / long target region
              (or low_diff_prc <= level)                                   # lower / short target region
```

**Do not** use a normal-CDF as the production estimator: high/low extremes are
fat-tailed and skewed (the asymmetry §3 describes), so Gaussian underestimates tail
reach — it would overstate P(distant target) and understate P(stop hit), biasing R/R
optimistically and breaking OOS.

Hybrid, frozen on **train only**:

- **Body** — smoothed empirical ECDF of `high_diff_prc` / `low_diff_prc`.
- **Tail** — where a bin's sample count drops below a threshold (default 50), replace the
  raw ECDF with a fitted parametric tail (generalized-Pareto or skew-t), **not** a
  Gaussian, so far-X levels (near ±2.0) get a smooth, non-zero, non-noisy estimate.
- **Baseline** — a normal-CDF estimate is computed and logged in the report **only** as a
  sanity-check reference, never used to select levels.
- **Drift check** — the OOS report compares realized reach-frequency against the
  train-frozen `P_reach` per level to detect regime drift.

### 7. Zones + validation (§11.5)

1. `zone_limit = price(inferred_label_coeff)` (inverse of the coeff map).
2. Mark 1-min candles: **long** if `1-min low < zone_limit`; **short** if
   `1-min high > zone_limit`.
3. Emit per zoned entry: entry, target, SL, R/R.
4. Save the zoned dataset.

**Metric:** maximize fraction of strict labels captured in-zone **and** require
profitable realized R/R of the zoned entries.

## Restrictions

- Initial experiment on the **train** set only; train is used for model selection and
  tuning.
- All computation in **Jupyter notebooks** (minimize simple_trader code churn), stored
  in a new `notebooks/` folder in the worktree.
- **Do not modify existing simple_trader code** until the full flow is validated by a
  human and approved. The experiment consumes the existing data model read-only.
- Training results, charts, reports, and zoned datasets are **artifacts written only to
  the mounted volume** — never into the worktree (container-written root-owned files
  block merges).
- All dataset stats (diff_prc mean/std, z-score params, regression params) are frozen
  from **train only** and applied unchanged to OOS.
- Investigation runs over TFs {15, 60, 240} (matched indicator/label TF), separately for
  **long and short**.
- Each experiment names and persists the columns it computes so results are
  independently reviewable, and produces an **inference-capable results file** so OOS and
  future datasets can be re-marked.

## Data

- **Training:** 2-year dataset.
- **Validation:** 2-month OOS. Validation may use strict labels and their non-strict
  siblings (non-strict positives are still profitable).
- Both train and validation datasets must be attachable to `view_full.py` to draw zone
  markers on charts.

## Goals (restated)

1. Action levels where target is reached most of the time and stop rarely; R/R
   profitable against candle size + fees.
2. 1-min candles satisfying that R/R are the buy(long)/sell(short) zone — entering during
   them is statistically profitable.
3. Adapt action levels to market condition via indicators (achieved through the
   §9–11 regression + Y sweep, not a separate X-picker).

## Artifact / file structure (to finalize in the plan)

```
notebooks/action_zones/        # experiment notebooks (in worktree)
<volume>/action_zones/<direction>/<tf>/<indicator_group>/
    plots/        1D, 2D, regression, classification, Y-sweep charts
    reports/      reproducible params + metrics (regression, classification, R/R grid)
    results/      inference-capable model/param files
    datasets/     zoned datasets (train + OOS)
```

## Open question (carried from source)

- Investigate whether a distinct std/mean for diff_prc can be computed conditioned on
  indicator values (state-dependent volatility).

## Resolved inconsistencies (from source review)

- §4 label typo `stop loss long = sl_short` → **short**.
- §4/§26 `diff_pc_ma` → `diff_prc_ma`.
- §4 uses plain per-series std (`high_std`, `low_std`), not the sided
  `std_above/std_below` decomposition. §3's asymmetry is preserved structurally:
  high and low are separate series (each own ma + std) combined with opposite ± signs,
  so the high bound reaches up and the low bound reaches down without needing sided std.
- §6 no longer a separate step (folded into §9–11).
- §11 duplicate header removed.
- Goal 4 (empty) removed.
- Validation metric contradiction resolved (see Scope).
