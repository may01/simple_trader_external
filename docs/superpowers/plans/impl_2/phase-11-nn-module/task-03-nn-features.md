# Task 03: NN Feature Engineering

**Phase:** 11 — NN Module  
**Depends on:** Phase 09 DataPreparer, Phase 04 indicator library  
**Produces:** expanded `indicators/library/nn_features.py`, `indicators_config.yaml` nn_features + nn sections

---

## Goal
Expand the engineered NN feature set into concrete `IndicatorField` subclasses so the full feature family is produced as ordinary `{tf}_`-prefixed indicator columns, then selected into `nn.feature_cols`. Today `nn_features.py` ships only `NNRSINormField` and `NNCloseDiffATRField`; this task adds (a) three **grouped feature families** drawn from an explicit indicator catalogue — Group 1 raw indicators, Group 2 indicator differences, Group 3 indicator slopes — plus (b) a set of **orthogonal** engineered features (log-returns, ATR-normalised range, candle body/wick ratios, a volatility regime bucket, cyclical time-of-day/day-of-week encodings, and cross-TF trend-alignment). Each is registered in `indicators/registry.py` and declared in `indicators_config.yaml` (the `nn_features` group plus the `nn` section `feature_cols` list), so `DataPreparer.prepare()` materialises them once into `df_with_indicators.pkl` for `NNDataset` to consume.

## Normalisation model — **global robust (winsorised) z-score**

> **Superseded by DECISIONS-LOG D13 (historical record below).** The winsorised z-score *formula*
> is unchanged, but it is now owned by `NNDataset` (train-split stats bundled into the checkpoint
> manifest), NOT by `DataAttributes.compute_nn_stats` / `nn.feature_cols`. That "Pipeline A" path
> and its apply site `nn_predictor` were removed (the latter in `969819b`). Read the rest of this
> section as the original design; substitute `NNDataset` for `compute_nn_stats`/`column_stats`.

There is **one** normalisation layer for these features, applied by `DataAttributes.compute_nn_stats(df, feature_cols)` and the apply sites (`nn_orchestrator` / `nn_predictor`). It is an **outlier-robust** global z-score: per-column stats are estimated on **winsorised** train-split values, and the standardised output is hard-clamped. This task does **not** create rolling on-frame `_z` columns.

**Per-column stats** (train-split closed-candle rows only; stored in `column_stats` and the dataset manifest):
1. `q01 = x.quantile(0.01)`, `q99 = x.quantile(0.99)` on the raw column.
2. `xw = x.clip(q01, q99)` — winsorise to the 1st–99th percentile band.
3. `mean = xw.mean()`, `std = max(xw.std(), 1e-8)`.

Store `{q01, q99, mean, std}` per feature column.

**Apply** (train, val, holdout, and live inference — all using the stored *train* stats, never recomputed → no leakage):
```text
xc = clip(x_raw, q01, q99)
z  = (xc - mean) / std
z  = clip(z, -4.0, +4.0)
```

Rationale: raw `mean`/`std` are non-robust — fat-tail spikes inflate `std` and squash the bulk near 0. Winsorising to `[q01, q99]` before estimating `mean`/`std` ties the scale to the central mass (option 3); the `[-4, +4]` clamp bounds any residual extreme (e.g. a live value beyond the train `q99`) so one spike can't dominate a batch. `compute_nn_stats` therefore stores four numbers per column (`q01, q99, mean, std`) instead of two, and `get_stats(col)` returns all four.

Consequences for the groups:

- **"Z-score on indicator X" (Group 1) ⇒ list X's existing column in `feature_cols`.** The global layer z-scores it. No new field, no `_z` column.
- **"Z-score on a difference" (Group 2) ⇒ materialise the raw difference `{tf}_{left}_minus_{right}` via `NNDiffField`, then list it in `feature_cols`.** The global layer z-scores the difference.
- **"Slope and z-score of the slope" (Group 3) ⇒ materialise the raw slope `{tf}_{src}_slope` via `NNSlopeField`, then list it in `feature_cols`.** The global layer supplies the z-score; there is no separate `_slope_z` column.

The previously-specced rolling `NNZScoreField` (`rsi_14_z`, `cci_14_z`, `vol_ma_20_z`, `macd_12_26_9_z`) is **removed** — superseded by this global-only decision. Its intent is now served by Group 1 (`rsi_14`, `cci_14`, `macd_12_26_9` raw → global z) and Group 2 (`vol_ma_20 - vol`).

## Context
These become `{tf}_*` feature columns in `df_with_indicators.pkl`, computed by `DataPreparer` during the `nn_features` step (after base indicators) and consumed read-only by `NNDataset.build()`. The NN module is a pure consumer: it never writes indicator columns, and `DataPreparer` is the single writer of `df_with_indicators.pkl`. Warmup rows (insufficient rolling window for a slope) emit NaN and are dropped at `NNDataset` build, not filled. The `nn` section's `feature_cols` list selects which `{tf}_<col>` columns enter the materialised tensors; window sizes live on the field params and are surfaced through the config `params:` blocks.

## Files
- Modify: indicators/library/nn_features.py
- Modify: indicators/registry.py
- Modify: configs/indicators_config.yaml
- Modify: indicators/attributes.py — `DataAttributes.compute_nn_stats` / `get_stats` (winsorised stats `{q01,q99,mean,std}`)
- Modify: nn/nn_orchestrator.py, nn/nn_predictor.py — apply winsorise → z → clamp `[-4,+4]`

> The robust-normalisation change (winsorise + clamp) is the canonical policy here; the materialisation/manifest schema and apply sites are also tracked by task-04 (NNDataset), phase-09 task-02 (DataPreparer), and the NNPredictor spec, which carry the matching `{q01,q99,mean,std}` stats.

## Interface

New/changed `IndicatorField` subclasses in `indicators/library/nn_features.py` (`group = "nn_features"`, `resource_dependencies = []`, `applies_to = []`; each sets `self.name`, `self.params`, `self.dependencies`; registry key == `self.name`, produced column == `{tf}_{name}`). Compute bodies are descriptions only.

### Group 1 — z-score on indicators (no new fields)
All Group 1 inputs already exist as base-indicator columns, so Group 1 adds **zero** field classes — it is purely a `feature_cols` selection (the global layer z-scores each). Columns selected (21):

```
rsi_ma8_diff, rsi_ma12_diff, rsi_ma24_diff,
cci_diff,
atr_14_ma_5, natr_14_ma_5,
close_diff_prc, close_diff_prc_rm_6, close_diff_prc_rm_6_mean_above, close_diff_prc_rm_6_mean_below,
high_diff_prc, high_diff_prc_rm_6,  high_diff_prc_rm_6_mean_above,  high_diff_prc_rm_6_mean_below,
low_diff_prc, low_diff_prc_rm_6,   low_diff_prc_rm_6_mean_above,   low_diff_prc_rm_6_mean_below,
macd_12_26_9, macd_signal_12_26_9, macd_5_13_9, macd_signal_5_13_9,
rsi_14, cci_14
```

### Group 2 — z-score on indicator differences (new `NNDiffField`)
- **`NNDiffField(IndicatorField)`** — `__init__(self, left: str, right: str)`; `name = f"{left}_minus_{right}"`. compute → `{tf}_{left}_minus_{right}` = `df[f"{tf}_{left}"] - df[f"{tf}_{right}"]`. Depends on `[left, right]`. Raw difference only; the global layer z-scores it.

Instantiated 21× (column == `{tf}_{name}`):

| left | right | column (`{tf}_…`) |
|---|---|---|
| bb_upper_20_2 | close | bb_upper_20_2_minus_close |
| bb_middle_20_2 | close | bb_middle_20_2_minus_close |
| bb_lower_20_2 | close | bb_lower_20_2_minus_close |
| ema_7 | close | ema_7_minus_close |
| ema_14 | close | ema_14_minus_close |
| ema_25 | close | ema_25_minus_close |
| ema_50 | close | ema_50_minus_close |
| ema_100 | close | ema_100_minus_close |
| vol_ma_20 | volume | vol_ma_20_minus_volume |
| ema_7 | ema_14 | ema_7_minus_ema_14 |
| ema_7 | ema_25 | ema_7_minus_ema_25 |
| ema_7 | ema_50 | ema_7_minus_ema_50 |
| ema_7 | ema_100 | ema_7_minus_ema_100 |
| ema_14 | ema_25 | ema_14_minus_ema_25 |
| ema_14 | ema_50 | ema_14_minus_ema_50 |
| ema_14 | ema_100 | ema_14_minus_ema_100 |
| ema_25 | ema_50 | ema_25_minus_ema_50 |
| ema_25 | ema_100 | ema_25_minus_ema_100 |
| ema_50 | ema_100 | ema_50_minus_ema_100 |
| atr_14_ma_5 | atr_14 | atr_14_ma_5_minus_atr_14 |
| natr_14_ma_5 | natr_14 | natr_14_ma_5_minus_natr_14 |

`ema_x - ema_y` pairs are the 10 unordered combinations of `[7,14,25,50,100]`, always computed **shorter − longer** (positive ⇒ faster EMA above slower ⇒ up-momentum). `atr`/`natr` in the source catalogue resolve to `atr_14`/`natr_14` (the bare `atr`/`natr` columns do not exist).

### Group 3 — slope + z-score-of-slope (reuse `NNSlopeField`)
- **`NNSlopeField(IndicatorField)`** — `__init__(self, source: str, window: int = 5)`; `name = f"{source}_slope"`. compute → `{tf}_{source}_slope` = linear (OLS) slope of `source` over the trailing `window` bars (per-bar change). Depends on `source`. Raw slope only; the global layer supplies the z-score.

Instantiated for 14 sources → `{tf}_{source}_slope`:

```
macd_12_26_9, macd_signal_12_26_9, macd_5_13_9, macd_signal_5_13_9,
ema_7, ema_14, ema_25, ema_50, ema_100,
adx_14,
rsi_ma8, rsi_ma12, rsi_ma24,
cci_14_ma_5
```

(Replaces the earlier ad-hoc `rsi_14_slope` pick; `macd_12_26_9_slope` is retained as it is in this list.)

### Orthogonal engineered fields (kept, unchanged)
Not covered by any group; retained because they add independent signal.

- **`NNLogRetField`** — `name = "logret"`. compute → `{tf}_logret` = `log(close_t / close_{t-1})`. Depends on `close`.
- **`NNRangeATRField`** — `__init__(self, atr_col="atr_14")`; `name = "range_atr"`. compute → `(high - low) / atr.clip(lower=1e-8)`. Depends on `high`, `low`, `atr_col`.
- **`NNBodyRatioField`** — `name = "body_ratio"`. compute → `(close - open) / (high - low).clip(lower=1e-8)`. Depends on `open`, `close`, `high`, `low`.
- **`NNWickUpField`** — `name = "wick_up"`. compute → `(high - max(open, close)) / (high - low).clip(lower=1e-8)`. Depends on `open`, `close`, `high`, `low`.
- **`NNWickDnField`** — `name = "wick_dn"`. compute → `(min(open, close) - low) / (high - low).clip(lower=1e-8)`. Depends on `open`, `close`, `high`, `low`.
- **`NNVolRegimeField`** — `__init__(self, atr_col="atr_14", window=200, buckets=3)`; `name = "vol_regime"`. compute → bucketed rolling percentile of `atr_col` (`0..buckets-1`, float). Depends on `atr_col`.
- **`NNSinTodField` / `NNCosTodField`** — `name = "sin_tod"` / `"cos_tod"`. compute → `sin`/`cos(2π · seconds_since_midnight / 86400)` from the index. No data dependencies.
- **`NNSinDowField` / `NNCosDowField`** — `name = "sin_dow"` / `"cos_dow"`. compute → `sin`/`cos(2π · day_of_week / 7)` from the index. No data dependencies.
- **`NNCrossTFAlignField`** — `__init__(self, other_tf: int, trend_col="ema_50")`; `name = f"align_{other_tf}"`. compute → sign-agreement of this TF's trend slope vs the higher TF's same trend column, reindexed/forward-filled onto this TF's index (`+1`/`-1`/`0`). Depends on `trend_col` this TF; reads `{other_tf}_{trend_col}`. Instantiated as a **ladder** over the full CANDLE set, each TF aligning to the next-higher one: 1 vs 5 → `1_align_5`, 5 vs 15 → `5_align_15`, 15 vs 60 → `15_align_60`, 60 vs 240 → `60_align_240`, 240 vs 1440 → `240_align_1440`. tf=1440 is the top of the ladder and has no align column.

### Already-built fields (kept)
`NNRSINormField` (`nn_rsi_ma8_norm_mean_20`) and `NNCloseDiffATRField` (`nn_close_diff_atr_14_ma_5`) remain as-is; existing `feature_cols` entries reference them.

### Removed
`NNZScoreField` and its instances (`rsi_14_z`, `cci_14_z`, `vol_ma_20_z`, `macd_12_26_9_z`) — superseded by the global-z decision (see Normalisation model). The classification group (`move_class`, `zone_class`) is **out of scope** for this task.

## `indicators_config.yaml` — `nn_features` group (append after the existing two entries)

Group 2 differences (one entry each; identity `left`/`right` is baked in the registry factory, so `params: {}` — `depends_on` lists the operands for config ordering):
```yaml
  - name: bb_upper_20_2_minus_close
    group: nn_features
    applies_to: all
    depends_on: [bb_upper_20_2, close]
    params: {}
  - name: bb_middle_20_2_minus_close
    group: nn_features
    applies_to: all
    depends_on: [bb_middle_20_2, close]
    params: {}
  - name: bb_lower_20_2_minus_close
    group: nn_features
    applies_to: all
    depends_on: [bb_lower_20_2, close]
    params: {}
  - name: ema_7_minus_close
    group: nn_features
    applies_to: all
    depends_on: [ema_7, close]
    params: {}
  - name: ema_14_minus_close
    group: nn_features
    applies_to: all
    depends_on: [ema_14, close]
    params: {}
  - name: ema_25_minus_close
    group: nn_features
    applies_to: all
    depends_on: [ema_25, close]
    params: {}
  - name: ema_50_minus_close
    group: nn_features
    applies_to: all
    depends_on: [ema_50, close]
    params: {}
  - name: ema_100_minus_close
    group: nn_features
    applies_to: all
    depends_on: [ema_100, close]
    params: {}
  - name: vol_ma_20_minus_volume
    group: nn_features
    applies_to: all
    depends_on: [vol_ma_20, volume]
    params: {}
  - name: ema_7_minus_ema_14
    group: nn_features
    applies_to: all
    depends_on: [ema_7, ema_14]
    params: {}
  - name: ema_7_minus_ema_25
    group: nn_features
    applies_to: all
    depends_on: [ema_7, ema_25]
    params: {}
  - name: ema_7_minus_ema_50
    group: nn_features
    applies_to: all
    depends_on: [ema_7, ema_50]
    params: {}
  - name: ema_7_minus_ema_100
    group: nn_features
    applies_to: all
    depends_on: [ema_7, ema_100]
    params: {}
  - name: ema_14_minus_ema_25
    group: nn_features
    applies_to: all
    depends_on: [ema_14, ema_25]
    params: {}
  - name: ema_14_minus_ema_50
    group: nn_features
    applies_to: all
    depends_on: [ema_14, ema_50]
    params: {}
  - name: ema_14_minus_ema_100
    group: nn_features
    applies_to: all
    depends_on: [ema_14, ema_100]
    params: {}
  - name: ema_25_minus_ema_50
    group: nn_features
    applies_to: all
    depends_on: [ema_25, ema_50]
    params: {}
  - name: ema_25_minus_ema_100
    group: nn_features
    applies_to: all
    depends_on: [ema_25, ema_100]
    params: {}
  - name: ema_50_minus_ema_100
    group: nn_features
    applies_to: all
    depends_on: [ema_50, ema_100]
    params: {}
  - name: atr_14_ma_5_minus_atr_14
    group: nn_features
    applies_to: all
    depends_on: [atr_14_ma_5, atr_14]
    params: {}
  - name: natr_14_ma_5_minus_natr_14
    group: nn_features
    applies_to: all
    depends_on: [natr_14_ma_5, natr_14]
    params: {}
```

Group 3 slopes (identity `source` is baked in the registry factory; `window: 5` default kept in config as the tunable; one entry each):
```yaml
  - name: macd_12_26_9_slope
    group: nn_features
    applies_to: all
    depends_on: [macd_12_26_9]
    params: {window: 5}
  - name: macd_signal_12_26_9_slope
    group: nn_features
    applies_to: all
    depends_on: [macd_signal_12_26_9]
    params: {window: 5}
  - name: macd_5_13_9_slope
    group: nn_features
    applies_to: all
    depends_on: [macd_5_13_9]
    params: {window: 5}
  - name: macd_signal_5_13_9_slope
    group: nn_features
    applies_to: all
    depends_on: [macd_signal_5_13_9]
    params: {window: 5}
  - name: ema_7_slope
    group: nn_features
    applies_to: all
    depends_on: [ema_7]
    params: {window: 5}
  - name: ema_14_slope
    group: nn_features
    applies_to: all
    depends_on: [ema_14]
    params: {window: 5}
  - name: ema_25_slope
    group: nn_features
    applies_to: all
    depends_on: [ema_25]
    params: {window: 5}
  - name: ema_50_slope
    group: nn_features
    applies_to: all
    depends_on: [ema_50]
    params: {window: 5}
  - name: ema_100_slope
    group: nn_features
    applies_to: all
    depends_on: [ema_100]
    params: {window: 5}
  - name: adx_14_slope
    group: nn_features
    applies_to: all
    depends_on: [adx_14]
    params: {window: 5}
  - name: rsi_ma8_slope
    group: nn_features
    applies_to: all
    depends_on: [rsi_ma8]
    params: {window: 5}
  - name: rsi_ma12_slope
    group: nn_features
    applies_to: all
    depends_on: [rsi_ma12]
    params: {window: 5}
  - name: rsi_ma24_slope
    group: nn_features
    applies_to: all
    depends_on: [rsi_ma24]
    params: {window: 5}
  - name: cci_14_ma_5_slope
    group: nn_features
    applies_to: all
    depends_on: [cci_14_ma_5]
    params: {window: 5}
```

Orthogonal entries (`logret`, `range_atr`, `body_ratio`, `wick_up`, `wick_dn`, `vol_regime`, `sin_tod`, `cos_tod`, `sin_dow`, `cos_dow`) plus the cross-TF align ladder (`align_5` [`applies_to: [1]`], `align_15` [`applies_to: [5]`], `align_60` [`applies_to: [15]`], `align_240` [`applies_to: [60]`], `align_1440` [`applies_to: [240]`]) are declared as before. The `rsi_14_z` / `cci_14_z` / `vol_ma_20_z` / `macd_12_26_9_z` entries are **deleted**.

**TF coverage (D12).** Every non-align nn_features entry applies to the full CANDLE set `[1, 5, 15, 60, 240, 1440]` (equivalently `applies_to: all`). Two carve-outs: `sin_tod`/`cos_tod` use `[1, 5, 15, 60, 240]` (omit 1440 — daily bars share one wall-clock open, so intraday time is a constant), and each `align_{other_tf}` applies only to its single lower TF as listed above. See DECISIONS-LOG D12 (supersedes D9's `[15, 60, 240]` perf restriction).

## `indicators_config.yaml` — `nn` section `feature_cols`

`feature_cols` is the per-timeframe selection. Show the full Group-1/2/3 block for `tf=15` below; **replicate the identical block for every CANDLE** (`1`, `5`, `15`, `60`, `240`, `1440`), substituting the prefix. The orthogonal columns and the two already-built `nn_*` columns are appended per the prior list, with two per-TF differences: the align column is the ladder entry for that TF (`1_align_5`, `5_align_15`, `15_align_60`, `60_align_240`, `240_align_1440`; tf=1440 has none), and `tf=1440` omits `sin_tod`/`cos_tod`. This yields 69 columns per TF for 1/5/15/60/240 and 66 for 1440 (411 total).

```yaml
nn:
  feature_cols:
    # ---- tf=15 — Group 1 (raw, globally z-scored) ----
    - "15_rsi_ma8_diff"
    - "15_rsi_ma12_diff"
    - "15_rsi_ma24_diff"
    - "15_cci_diff"
    - "15_atr_14_ma_5"
    - "15_natr_14_ma_5"
    - "15_close_diff_prc_rm_6"
    - "15_close_diff_prc_rm_6_mean_above"
    - "15_close_diff_prc_rm_6_mean_below"
    - "15_high_diff_prc_rm_6"
    - "15_high_diff_prc_rm_6_mean_above"
    - "15_high_diff_prc_rm_6_mean_below"
    - "15_low_diff_prc_rm_6"
    - "15_low_diff_prc_rm_6_mean_above"
    - "15_low_diff_prc_rm_6_mean_below"
    - "15_macd_12_26_9"
    - "15_macd_signal_12_26_9"
    - "15_macd_5_13_9"
    - "15_macd_signal_5_13_9"
    - "15_rsi_14"
    - "15_cci_14"
    # ---- tf=15 — Group 2 (differences, globally z-scored) ----
    - "15_bb_upper_20_2_minus_close"
    - "15_bb_middle_20_2_minus_close"
    - "15_bb_lower_20_2_minus_close"
    - "15_ema_7_minus_close"
    - "15_ema_14_minus_close"
    - "15_ema_25_minus_close"
    - "15_ema_50_minus_close"
    - "15_ema_100_minus_close"
    - "15_vol_ma_20_minus_volume"
    - "15_ema_7_minus_ema_14"
    - "15_ema_7_minus_ema_25"
    - "15_ema_7_minus_ema_50"
    - "15_ema_7_minus_ema_100"
    - "15_ema_14_minus_ema_25"
    - "15_ema_14_minus_ema_50"
    - "15_ema_14_minus_ema_100"
    - "15_ema_25_minus_ema_50"
    - "15_ema_25_minus_ema_100"
    - "15_ema_50_minus_ema_100"
    - "15_atr_14_ma_5_minus_atr_14"
    - "15_natr_14_ma_5_minus_natr_14"
    # ---- tf=15 — Group 3 (slopes, globally z-scored) ----
    - "15_macd_12_26_9_slope"
    - "15_macd_signal_12_26_9_slope"
    - "15_macd_5_13_9_slope"
    - "15_macd_signal_5_13_9_slope"
    - "15_ema_7_slope"
    - "15_ema_14_slope"
    - "15_ema_25_slope"
    - "15_ema_50_slope"
    - "15_ema_100_slope"
    - "15_adx_14_slope"
    - "15_rsi_ma8_slope"
    - "15_rsi_ma12_slope"
    - "15_rsi_ma24_slope"
    - "15_cci_14_ma_5_slope"
    # ---- tf=15 — orthogonal + already-built ----
    - "15_logret"
    - "15_range_atr"
    - "15_body_ratio"
    - "15_wick_up"
    - "15_wick_dn"
    - "15_vol_regime"
    - "15_sin_tod"
    - "15_cos_tod"
    - "15_sin_dow"
    - "15_cos_dow"
    - "15_align_60"
    - "15_nn_rsi_ma8_norm_mean_20"
    - "15_nn_close_diff_atr_14_ma_5"
    # ---- repeat the same 56 group columns + orthogonal for tf in {1, 5, 60, 240, 1440} ----
    #      align per ladder: 1→align_5, 5→align_15, 60→align_240, 240→align_1440; 1440 has none.
    #      tf=1440 also omits sin_tod/cos_tod (daily bars → constant intraday time).
  checkpoint_dir: "checkpoints/"
```

## `indicators/registry.py` — `_FIELD_REGISTRY` (append under `# NN features`, delete the `*_z` lines)

```python
    # Group 2 — differences (identity baked: left, right)
    "bb_upper_20_2_minus_close":   lambda cfg: NNDiffField(**{"left": "bb_upper_20_2",  "right": "close",  **cfg.params}),
    "bb_middle_20_2_minus_close":  lambda cfg: NNDiffField(**{"left": "bb_middle_20_2", "right": "close",  **cfg.params}),
    "bb_lower_20_2_minus_close":   lambda cfg: NNDiffField(**{"left": "bb_lower_20_2",  "right": "close",  **cfg.params}),
    "ema_7_minus_close":           lambda cfg: NNDiffField(**{"left": "ema_7",   "right": "close",  **cfg.params}),
    "ema_14_minus_close":          lambda cfg: NNDiffField(**{"left": "ema_14",  "right": "close",  **cfg.params}),
    "ema_25_minus_close":          lambda cfg: NNDiffField(**{"left": "ema_25",  "right": "close",  **cfg.params}),
    "ema_50_minus_close":          lambda cfg: NNDiffField(**{"left": "ema_50",  "right": "close",  **cfg.params}),
    "ema_100_minus_close":         lambda cfg: NNDiffField(**{"left": "ema_100", "right": "close",  **cfg.params}),
    "vol_ma_20_minus_volume":      lambda cfg: NNDiffField(**{"left": "vol_ma_20", "right": "volume", **cfg.params}),
    "ema_7_minus_ema_14":          lambda cfg: NNDiffField(**{"left": "ema_7",  "right": "ema_14",  **cfg.params}),
    "ema_7_minus_ema_25":          lambda cfg: NNDiffField(**{"left": "ema_7",  "right": "ema_25",  **cfg.params}),
    "ema_7_minus_ema_50":          lambda cfg: NNDiffField(**{"left": "ema_7",  "right": "ema_50",  **cfg.params}),
    "ema_7_minus_ema_100":         lambda cfg: NNDiffField(**{"left": "ema_7",  "right": "ema_100", **cfg.params}),
    "ema_14_minus_ema_25":         lambda cfg: NNDiffField(**{"left": "ema_14", "right": "ema_25",  **cfg.params}),
    "ema_14_minus_ema_50":         lambda cfg: NNDiffField(**{"left": "ema_14", "right": "ema_50",  **cfg.params}),
    "ema_14_minus_ema_100":        lambda cfg: NNDiffField(**{"left": "ema_14", "right": "ema_100", **cfg.params}),
    "ema_25_minus_ema_50":         lambda cfg: NNDiffField(**{"left": "ema_25", "right": "ema_50",  **cfg.params}),
    "ema_25_minus_ema_100":        lambda cfg: NNDiffField(**{"left": "ema_25", "right": "ema_100", **cfg.params}),
    "ema_50_minus_ema_100":        lambda cfg: NNDiffField(**{"left": "ema_50", "right": "ema_100", **cfg.params}),
    "atr_14_ma_5_minus_atr_14":    lambda cfg: NNDiffField(**{"left": "atr_14_ma_5",  "right": "atr_14",  **cfg.params}),
    "natr_14_ma_5_minus_natr_14":  lambda cfg: NNDiffField(**{"left": "natr_14_ma_5", "right": "natr_14", **cfg.params}),
    # Group 3 — slopes (identity baked: source; window from params, default 5)
    "macd_12_26_9_slope":          lambda cfg: NNSlopeField(**{"source": "macd_12_26_9",        **cfg.params}),
    "macd_signal_12_26_9_slope":   lambda cfg: NNSlopeField(**{"source": "macd_signal_12_26_9", **cfg.params}),
    "macd_5_13_9_slope":           lambda cfg: NNSlopeField(**{"source": "macd_5_13_9",         **cfg.params}),
    "macd_signal_5_13_9_slope":    lambda cfg: NNSlopeField(**{"source": "macd_signal_5_13_9",  **cfg.params}),
    "ema_7_slope":                 lambda cfg: NNSlopeField(**{"source": "ema_7",   **cfg.params}),
    "ema_14_slope":                lambda cfg: NNSlopeField(**{"source": "ema_14",  **cfg.params}),
    "ema_25_slope":                lambda cfg: NNSlopeField(**{"source": "ema_25",  **cfg.params}),
    "ema_50_slope":                lambda cfg: NNSlopeField(**{"source": "ema_50",  **cfg.params}),
    "ema_100_slope":               lambda cfg: NNSlopeField(**{"source": "ema_100", **cfg.params}),
    "adx_14_slope":                lambda cfg: NNSlopeField(**{"source": "adx_14",  **cfg.params}),
    "rsi_ma8_slope":               lambda cfg: NNSlopeField(**{"source": "rsi_ma8",  **cfg.params}),
    "rsi_ma12_slope":              lambda cfg: NNSlopeField(**{"source": "rsi_ma12", **cfg.params}),
    "rsi_ma24_slope":              lambda cfg: NNSlopeField(**{"source": "rsi_ma24", **cfg.params}),
    "cci_14_ma_5_slope":           lambda cfg: NNSlopeField(**{"source": "cci_14_ma_5", **cfg.params}),
    # Orthogonal
    "logret":              lambda cfg: NNLogRetField(**cfg.params),
    "range_atr":           lambda cfg: NNRangeATRField(**cfg.params),
    "body_ratio":          lambda cfg: NNBodyRatioField(**cfg.params),
    "wick_up":             lambda cfg: NNWickUpField(**cfg.params),
    "wick_dn":             lambda cfg: NNWickDnField(**cfg.params),
    "vol_regime":          lambda cfg: NNVolRegimeField(**cfg.params),
    "sin_tod":             lambda cfg: NNSinTodField(**cfg.params),
    "cos_tod":             lambda cfg: NNCosTodField(**cfg.params),
    "sin_dow":             lambda cfg: NNSinDowField(**cfg.params),
    "cos_dow":             lambda cfg: NNCosDowField(**cfg.params),
    "align_5":             lambda cfg: NNCrossTFAlignField(**{"other_tf": 5,    "applies_to": cfg.applies_to, **cfg.params}),
    "align_15":            lambda cfg: NNCrossTFAlignField(**{"other_tf": 15,   "applies_to": cfg.applies_to, **cfg.params}),
    "align_60":            lambda cfg: NNCrossTFAlignField(**{"other_tf": 60,   "applies_to": cfg.applies_to, **cfg.params}),
    "align_240":           lambda cfg: NNCrossTFAlignField(**{"other_tf": 240,  "applies_to": cfg.applies_to, **cfg.params}),
    "align_1440":          lambda cfg: NNCrossTFAlignField(**{"other_tf": 1440, "applies_to": cfg.applies_to, **cfg.params}),
```

(Identity args — `left`/`right` for diffs, `source` for slopes, `other_tf` for cross-TF align — are baked into each factory, matching the `rsi_ma8` idiom and the registry docstring ("an empty params dict yields the defaults"). Config `params` stays `{}` except the slope `window` override; `range_atr`/`vol_regime` rely on their class defaults.)

## Key Constraints
- **Single normalisation layer (robust).** No rolling `_z` columns. Group features are raw `{tf}_*` columns; the only standardisation is the global **winsorised** z-score (clip raw to train `[q01,q99]` → `(x-mean)/std` on winsorised stats → clamp `[-4,+4]`), computed on the train split only and reused verbatim at val/holdout/live. Confirm `feature_cols` matches the materialised column names exactly so `compute_nn_stats` finds them.
- All features are plain indicator columns: `DataPreparer` is the single writer of `df_with_indicators.pkl` during the `nn_features` step (after base indicators); the NN module never writes them and only reads `feature_cols`. Each field follows the derived-name convention (registry key == `self.name`, column == `{tf}_{name}`) and lists its base-indicator suffixes in `self.dependencies` so prep ordering resolves prerequisites first (e.g. each `*_slope` depends on its source MA; each `*_minus_*` depends on both operands).
- **No look-ahead.** Slope uses only trailing data (`.rolling(window)`); differences are point-in-time; cross-TF alignment forward-fills the *last closed* higher-TF value, never a future one; cyclical time encodings are point-in-time from the index. Warmup rows emit NaN and are dropped at `NNDataset` build, never forward/back-filled.
- **`atr`/`natr` ⇒ `atr_14`/`natr_14`** in Group 2 (the bare-period columns do not exist).
- **EMA-pair direction:** all 10 unordered pairs of `[7,14,25,50,100]`, computed shorter − longer.
- **The classification group (`move_class`, `zone_class`) is out of scope** for this task (excluded by decision).
- Cross-TF fields require the higher TF present; each `align_{other_tf}` applies only to its lower member (the ladder `align_5`→`[1]`, `align_15`→`[5]`, `align_60`→`[15]`, `align_240`→`[60]`, `align_1440`→`[240]`), so a missing higher TF is a config error, not a silent NaN.

## Verification
```bash
docker compose run --rm ohlc_gen   # then assert the new {tf}_* nn feature columns exist in df_with_indicators.pkl
docker compose run --rm trainer python3 -c "import pandas as pd; from helpers import wide_df_path; df=pd.read_pickle(wide_df_path()); cols=set(df.columns); import sys; need=[f'15_{c}' for c in ['ema_7_minus_close','ema_50_minus_ema_100','macd_12_26_9_slope','rsi_ma8_slope','cci_14_ma_5_slope','natr_14_ma_5_minus_natr_14']]; missing=[c for c in need if c not in cols]; print('MISSING', missing) or sys.exit(1 if missing else 0)"
# assert compute_nn_stats has stats for every feature_cols entry (no KeyError at train/inference)
```

## Commit
`feat(indicators): nn_features grouped families — diffs, slopes, group-1 selection (global-z)`
