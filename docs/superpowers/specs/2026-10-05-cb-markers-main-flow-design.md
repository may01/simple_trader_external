# CB markers and marker filters in the main flow — design

**Date:** 2026-10-05
**Base branch:** `experimental_imp_2`
**Work branch:** `cb-markers-main-flow` (off base; merge back)
**Status:** approved 2026-10-05; **implemented 2026-10-06, uncommitted on branch `cb-markers-main-flow`
(base `757fc1d`), awaiting user review.** No commit or merge exists yet; all work is staged in the
worktree `worktrees/cb-markers-main-flow`.
**Plan:** `plans/impl_2/phase-18-cb-markers-main-flow/README.md`
**Results:** `experiment/results/cb_markers_main_flow_results.md` (gate numbers G1–G10)

## Implementation outcome (2026-10-06)

Built as designed (tasks 01–12). Where execution refined or departed from the text below, the
section concerned is corrected in place; the list here is the summary.

| Gate | Result |
|---|---|
| G1 model export | **passed** — 6/6, `band_pct` rel ≤ 2.9e-16, numpy vs sklearn max diff 0.0 (n_train 70,157 / 17,529 / 4,373 for 15 / 60 / 240) |
| G2 closed bounds | **passed** on oos2m — max rel ≤ 1.21e-15 |
| G3 closed zone / marker | **passed** — 0 mismatches inside the comparison mask |
| G4 forming bounds / hybrid | **passed** — bounds max rel ≤ 9.99e-16; hybrid columns validated as kernel parity at the sidecar's own shrink 0.35, plus a non-gating WARN (see "Frozen parameters") |
| G5 extdone | **passed** — G5a sticky reduction 0 mismatches; G5b P(hold) 0.938 / 0.936 / 0.951 / 0.952 / 0.931 / 0.955; G5c materialized == kernel |
| G6 filter unit tests | **passed** |
| G7 chunked == single-pass | **passed on synthetic inputs only** (114 cols × 5,760 rows, max diff 0.0); not run on a real dataset |
| G8 live parity | **measured, thresholds proposed not agreed** — `cb_inzone_*` bool mismatch 0; worst bool 1/600 (`15_cbnc_inzone_long`, boundary); float max rel ≤ 5.9e-5; per-tick cost mean 81 / p95 135 / max 249 ms vs the 50 ms target (**not met**, open decision) |
| G9 `WideDataPoint.get` | **passed** (unit tests); real-dataset `simulate` smoke **not run** |
| G10 broadcast dry run | **not run** (user-gated live run) |

Rulings taken during implementation (each recorded where it applies below):

- `*_std` band columns stay finite during feature warm-up (parity with the stored artifacts).
- The held forming prediction (`nc_pred_prev`) is applied per component.
- `TGT_SHRINK_PCT` stays 0.15; the stored nc sidecar was built with 0.35.
- The EMA-slope backfill reproduces the field's 104-candle window; first 103 closed candles of a
  trimmed dataset are approximate.
- extdone requires ATR finite **and > 0**.
- Live: the held prediction is reset at every minute change and merged only from finite entries;
  a tf with fewer than `MIN_CLOSED_CANDLES = 13` closed candles is not warm.
- Live per-tick cost accepted at mean 81 / p95 135 ms after caching; no second (numpy one-row)
  implementation of the kernel maths. Open decision for the user.

Follow-ups recorded in `executor/TECH_DEBT.md` §15 (G8 gap numbers) and §16–§19.

## Goal

Candle-bound (CB) entry markers and their filters exist today only as offline
sidecar pickles written by notebook drivers and as veto logic inside the
viewer. This change moves them into the main flow, so the same columns are
produced by one implementation in:

- **data preparation** — written into `df_with_indicators.pkl`;
- **the live session** — available on the live data point every tick;
- **backtesting** — read from the prepared dataset (backtest computes nothing
  itself, so it inherits the columns from data preparation).

**No filter is applied to the marker.** The marker column is the raw
`cb_inzone`. Four filters are **computed and stored as separate columns**:
the extdone veto, EMA-25 slope with-trend, move_class extremes, and the
forming-candle intersection `cbx_inzone`. Combining a filter with the marker
is left to the consumer.

## Decisions taken (user, 2026-10-05)

| Topic | Decision |
|---|---|
| With-trend rule | "Not against trend", on the EMA-25 slope class `{tf}_ema_25_slope_class` (−1 fall / 0 neutral / +1 rise): long passes when the class ≠ −1, short when ≠ +1. Neutral passes. |
| extdone ladder | The 2y-fit ladder, per side (not the oos2m-picked one in today's sidecar). |
| extdone veto | Computed and stored, **not applied** to the marker (same treatment as the other three filters). |
| Scope | Columns in prep + live; MQ broadcast of the columns; viewer reads the main-flow columns. **No** strategy or signal wiring. |

## Non-goals

- No strategy, signal class or entry logic that consumes the markers.
- No change in `trade_executor`. This spec only puts values on the wire.
- No refit of the bound models, the ladder, or the class thresholds.
- The other experiment sidecars stay sidecars: `cb_close*`, `cb_hi_adj` /
  `cb_lo_adj`, `cb_enter_*`, `cbover_*` / `cb_overshoot_*`, `cbatr_*`,
  `ev_*`, `evr_*`, `zp_*`, and the `ema25_*` drawing columns. *(2026-10-17: `cbover_*` / `cb_overshoot_*` moved into the main flow by phase 19 — `2026-10-17-cb-overshoot-main-flow-design.md`, columns `{tf}_cb_overshoot_{side}` / `{tf}_cb_f_overshoot_{side}`; the sidecar join and viewer veto are gone.)*
- No fix for the unrelated findings listed under "Observed, out of scope".

## Current state (verified)

- **Closed bounds** `{tf}_cb_{high,low}[_std,_up,_dn]`: the original producer
  is lost. `notebooks/candle_bounds_nc/cbnc.py` re-implements it
  (`closed_frame`, `infer_closed`) and reproduces the stored
  `df_with_candle_bounds.pkl` to 1e-9 in the interior. It **refits**
  `StandardScaler + Ridge(alpha=1)` on 2y_az at every run; only `band_pct` is
  persisted. scikit-learn is not in the main image.
- **Closed zone and raw marker**: no code produces them today. Checked against
  the stored oos2m sidecar on 2026-10-05, exact match on tf 15:
  `cb_zone_long = cb_low + 0.05·(cb_high − cb_low)`,
  `cb_zone_short = cb_high − 0.05·(cb_high − cb_low)`,
  `cb_inzone_long = 1_low ≤ cb_zone_long`, `cb_inzone_short = 1_high ≥ cb_zone_short`.
- **Forming bounds, zones, intersection** (`cbnc_*`, `cbx_inzone_*`):
  `cbnc.forming_features`, `infer_forming`, `add_zones`.
- **extdone**: `notebooks/zone_profitability/run_extdone.py`, ladder
  hard-coded and picked on oos2m. The 2y ladder comes from
  `fit_extdone_ladder.py`; nothing loads it.
- **Veto**: only in `frontend/data_viewer.py` (`_ZONE_VETO`), at draw time.
- **`move_class`, `ema_25_slope_class`**: already main-flow indicator fields
  (`indicators/library/classification.py`), enabled in
  `configs/indicators_config.yaml`, computed on the forming candle per row.
  Existing prepared datasets predate `ema_25_slope_class` and
  `ema_25_diff_prc` and do not contain them.
- **Flows**: prep computes indicators per 1-min row on a slice of closed
  candles plus the forming row, in a wide frame with `{tf}_` columns. Live
  recomputes per-TF frames (120 candles each, no wide frame, no cross-TF
  access) every second. Backtest loads `df_with_indicators.pkl`.

## Design

### Where it runs: on the wide frame, outside the per-row field loop

The computation **does use the wide frame** (1-min rows with `{tf}_`
columns). What it does not use is the `IndicatorField` per-row loop, for
three reasons:

- **The field's input slice has no minutes inside the candle.** In prep a
  field sees, per 1-min row, the last 105 *closed-candle* rows of its tf
  plus the current row. The forming bound needs the previous minute's row,
  which is not in the slice.
- **Cost.** The per-row loop is the known prep bottleneck (about 16 rows/s).
  All CB columns are plain column arithmetic over the whole wide frame and
  take seconds when vectorized.
- **Live has no wide frame.** It holds one frame per tf, so a field there
  cannot read the 1-min low next to a 15-min level.

So the CB computation is one function over a wide frame,
`compute_cb_columns(wide_df)`, called after the indicator passes:

- **Prep** calls it on the full wide frame.
- **Live** builds a small wide frame each tick from what it already has —
  the closed-candle rows of each tf frame plus one current-minute row with
  the forming values — and calls the **same function**, taking the last row
  of the result.

Alternatives considered and rejected:

- *Fields with cross-TF reads in the class pass.* Works in prep only; live
  per-TF frames cannot see other TFs, and the forming bound's
  previous-minute value does not fit a per-row slice.
- *Keep sidecars, add a live-only implementation.* Two implementations with
  no shared code; backtest would need sidecar joins in `SimulationData`.

### Module layout

New package `indicators/candle_bounds/`:

| File | Responsibility |
|---|---|
| `params.py` | Frozen constants: TFs `(15, 60, 240)`, `ZONE_FRAC = 0.05`, `TGT_SHRINK_PCT = 0.15`, the 2y extdone ladder, feature list. |
| `models.py` | Load frozen model coefficients from JSON; `predict_pct(X)` in numpy. No scikit-learn at runtime. |
| `kernel.py` | Pure functions: features (closed and forming), bound inference, zones, markers, extdone, filters. Port of `cbnc.py` and `run_extdone.py`. Input: a wide 1-min frame. Output: a frame of new columns. As built, `forming_features` is split into `forming_history` (closed-history aggregates, constant through a candle) and `forming_row_features`; `forming_prediction` (unshifted) and `forming_bounds` (one-row shift) split `infer_forming`. |
| `stage.py` | `compute_cb_columns(wide_df) -> DataFrame` (vectorized; the single entry point for prep and the materialize script; `compute_cb` = loop over `tf_columns(closed_cb(...))` per tf) and `LiveCbStage` (builds the live wide frame each tick, holds the previous minute's forming prediction). As built, live does not call `compute_cb_columns` on the whole sparse frame each tick: it caches `closed_cb` and `forming_history` per (tf, closed block) and evaluates only the current row through the same `tf_columns` (see "Live session"). |
| `models_link_usdt.json` | Frozen models for LINK/USDT. |

The notebooks keep working; `cbnc.py` and `run_extdone.py` import the kernel
instead of carrying their own copies, so there is one implementation. As built:
`cbnc.py` re-exports the constants from `params`, `closed_frame` = `kernel.closed_frame` +
`target`, `forming_features` / `_to_rows` are the kernel's; `fit_side`, `SideModel`,
`infer_closed`, `infer_forming`, `add_zones` stay (sklearn pipeline, experiment drivers).
`run_extdone.d_of_progress` wraps `kernel.ladder_threshold`; its oos2m `LADDER` and sticky logic
stay as the experiment was run. Pinned by `tests/unit/data_layer/test_cb_notebook_parity.py`.

### Frozen parameters

**Bound models.** Per `(tf, side)` for tf ∈ {15, 60, 240}, side ∈ {high, low}:
scaler mean and scale (15 values each), Ridge coefficients (15), intercept,
`band_pct`, `n_train`, train dataset name. Stored in
`models_link_usdt.json`, selected by `PAIR`. Runtime prediction is
`((x − mean) / scale) · coef + intercept`.

A one-off script `scripts/cb_export_models.py` (run in the venv that has
scikit-learn) fits on `2y_az_link_usdt` with `cbnc.fit_side` and writes the
JSON. It aborts unless refit `band_pct` matches `candle_bounds_meta.json`
(relative difference < 1e-3) and the numpy prediction matches the sklearn
pipeline (< 1e-12) on the training rows. As run (G1, 2026-10-05): inside the
`ohlc_gen` container with scikit-learn pip-installed into a throwaway target
directory (no host venv); 6/6 models, `band_pct` rel ≤ 2.9e-16, max prediction
difference 0.0.

If no model file exists for the configured pair, the stage is skipped with a
warning and no CB columns are written. A missing input column with a model
file present is an error, not a skip.

**extdone ladder (2y fit, per side).** `(progress_from, d)` in 1-min ATR;
below the first step the state is never set.

| tf | high | low |
|---|---|---|
| 15 | (0.25, 5.0), (0.50, 2.5), (0.75, 1.5) | (0.25, 4.0), (0.50, 2.5), (0.75, 1.5) |
| 60 | (0.25, 10.0), (0.50, 8.0), (0.75, 4.0) | (0.25, 10.0), (0.50, 6.0), (0.75, 4.0) |
| 240 | (0.75, 8.0) | (0.75, 8.0) |

Values are taken from `results/extdone_zone_filter_results.md` §1.3
(provenance fix). They were re-checked against the `fit_extdone_ladder.py`
output on 2026-10-05 (not refit) and frozen in `params.EXTDONE_LADDER`; G5b
reproduces the fit's P(hold | first trigger) on oos2m to 3 decimals.

**Target haircut.** `TGT_SHRINK_PCT = 0.15` (Global Constraints, committed
`cbnc.py`, viewer comment). The stored oos2m nc sidecar
(`df_with_candle_bounds_nc.pkl`) was built with 0.35 (its
`candle_bounds_nc_meta.json`), so it is a stale reference for the hybrid
columns `cbnc_tgt_*`, `cbnc_zone_*`, `cbnc_inzone_*`, `cbx_inzone_*`. G4 for
those columns is validated as kernel parity at the sidecar's own shrink (read
from its meta: 0.35 reproduces the sidecar exactly) plus a check that the
materialized 0.15 columns equal the kernel at 0.15; the parameter difference
is printed as a non-gating WARN. At 0.15 the 15 m hybrid markers are about
twice as many as at 0.35 (`cbnc_inzone_long` 14,261 vs 6,433 on oos2m). If
0.35 was intended: change one constant and re-materialize.

**Classes.** Two existing class indicators are read, both on the forming
candle of the marker's tf:

- `{tf}_ema_25_slope_class` (EMA class, used by `cb_f_trend`): the
  candle-to-candle change of EMA-25 in % (`{tf}_ema_25_diff_prc`) against
  the frozen 2y mean ± 0.5·std. −1 fall, 0 neutral (also NaN), +1 rise.
  Cuts in % per candle: tf 15 −0.0425 / +0.0461, tf 60 −0.0795 / +0.0941,
  tf 240 −0.1422 / +0.2014.
- `{tf}_move_class` (RSI class, used by `cb_f_mcx`): `rsi_ma8_diff` against
  frozen 2y cuts, −3..3.

`EMA_SLOPE_STATS`, `EMA_SLOPE_X` and `MOVE_CLASS_CUTS` stay where they are
(`indicators/library/classification.py`); the stage only reads the class
columns.

### Columns

For each tf ∈ {15, 60, 240}. `side` is `high`/`low` for bounds and extdone,
`long`/`short` for zones, markers and filters. All values are per 1-min row.

| Column | Type | Definition |
|---|---|---|
| `{tf}_cb_{high,low}` | float | Closed bound: prediction made at the previous candle's close, held through the current candle. |
| `{tf}_cb_{high,low}_std`, `_up`, `_dn` | float | Band half-width in price; bound ± band. |
| `{tf}_cb_zone_{long,short}` | float | Entry zone level, 5 % of the bound span from the stop-side bound (formulas above). |
| `{tf}_cb_inzone_{long,short}` | bool | **CB marker** (unfiltered): the row's 1-min low (long) / high (short) reaches the zone. |
| `{tf}_extdone_{high,low}` | bool | Extreme-done state of this minute. Evaluated independently per minute; **not sticky** — it turns false again if price returns toward the extreme. |
| `{tf}_extdone_{high,low}_lvl` | float | The candle's running extreme on minutes where the state is true, NaN otherwise. |
| `{tf}_cb_f_extdone_{long,short}` | bool | Filter, not applied. Long: `¬extdone_high`. Short: `¬extdone_low`. |
| `{tf}_cb_f_trend_{long,short}` | bool | Filter, not applied. EMA-25 slope class of the same tf. Long: `{tf}_ema_25_slope_class ≠ −1` (EMA-25 not falling). Short: `≠ +1` (not rising). |
| `{tf}_cb_f_mcx_{long,short}` | bool | Filter, not applied. RSI momentum class of the same tf. Long: `{tf}_move_class == −3`. Short: `{tf}_move_class == +3`. |
| `{tf}_cbnc_{high,low}[_std,_up,_dn]` | float | Forming-candle bound, prediction from the previous minute. |
| `{tf}_cbnc_tgt_{long,short}`, `{tf}_cbnc_zone_{long,short}` | float | Hybrid target and zone level (`cbnc.add_zones`). |
| `{tf}_cbnc_inzone_{long,short}` | bool | Row reaches the forming zone and the hybrid span is valid. |
| `{tf}_cbx_inzone_{long,short}` | bool | Filter, not applied. `cbnc_inzone ∧ cb_inzone` (as in the experiment). |

Closed bounds are placed on the 1-min rows by `kernel.to_rows` (reindex,
shift one candle, forward-fill): over a closed candle whose features are NaN
the previous closed bound is carried forward instead of turning NaN — this
matches the stored experiment artifacts (final review).

Semantics of the filters: `cb_f_extdone`, `cb_f_trend` and `cb_f_mcx` are
**pass flags of the row's state**, true or false on every row regardless of
whether a marker fired. A consumer combines them itself, for example
`cb_inzone_long ∧ cb_f_extdone_long ∧ cb_f_trend_long`. `cbx_inzone` keeps its experiment
definition and is itself marker-shaped. Class columns are read on the same
row and tf as the marker (forming-candle value).

Rows where an input is NaN (warm-up): float columns are NaN, bool columns
are False. **Exception (ruling, task 03):** the band columns
`{tf}_cb_{side}_std` and `{tf}_cbnc_{side}_std` (= extreme × `band_pct`) stay
finite during feature warm-up wherever the extreme is known, while the bound
and `_up` / `_dn` are NaN — parity with the stored experiment artifacts (G2/G4
demand the match). A consumer reading `_std` alone in warm-up gets a number
without a bound; the fix, if wanted, is to mask `_std` by `bound.notna()` and
relax G2/G4 for `_std`.

### Look-ahead rules

- Closed bounds for a candle use only data closed before the candle opened.
- The forming bound at minute *t* is the prediction from minute *t − 1*.
- The marker compares minute *t*'s low/high with levels known before *t*.
- extdone at minute *t* uses minute *t*'s close, so `cb_f_extdone` at *t* is
  known at the end of minute *t*. This matches the viewer rule and the
  experiment's measurement. A marker combined with this filter is therefore
  final when its minute closes, not earlier.

### extdone definition

```
run_high[t] = {tf}_high[t]   (the forming candle's high so far; run_low: {tf}_low[t])
pull[t]     = (run_high[t] − 1_close[t]) / 1_atr_14_ma_5[t]   (low: (1_close − run_low) / atr)
progress[t] = (minutes since candle open, counting t) / tf
extdone[t]  = pull[t] ≥ d(progress[t])    and atr finite and atr > 0
```

The state is **calculated per minute from that minute's values only**. It
is not carried forward: a minute where the pull-away falls back under the
threshold is false even if an earlier minute of the same candle was true.
There is no `_first` column.

This departs from the experiment, where the state was sticky to the
candle's close. What carries over and what does not:

- The first true minute of a candle is the same under both definitions, so
  the measured P(hold | first trigger) of 0.93–0.96 and the ladder fit
  still describe that first minute.
- Later minutes differ: the sticky state stayed on, this one can switch off
  and on. Share of true minutes and the effect of `cb_f_extdone` on marker
  counts will be lower than the experiment's figures (about 60 % of zone
  minutes removed) and are re-measured, not assumed.

`progress` is defined by wall-clock minutes from the candle's open, not by
row count, so prep and live agree when minutes are missing. The experiment
used row count; the two differ only on candles with gaps.

### Data preparation

A third pass in `DataPreparer` (step 6b, `DataPreparer._compute_cb_stage`), on the final frame after warm-up rows are
trimmed (single-pass) or after parts are merged (chunked, `_merge_parts`), before the profit
labels: `compute_cb_columns(df)` runs vectorized over the whole wide frame and its output is assigned into the
frame before `df_with_indicators.pkl` is written. It is not part of the
per-row fork pool.

Required input columns: `1_high`, `1_low`, `1_close`, `1_atr_14_ma_5`; per
tf `{tf}_open/high/low/close`, `{tf}_is_closed`, `{tf}_rsi_14`,
`{tf}_rsi_ma8`, `{tf}_macd_12_26_9`, `{tf}_macd_hist_12_26_9`,
`{tf}_ema_25`, `{tf}_move_class`, `{tf}_ema_25_slope_class`.

The stage reads only these columns, to keep memory bounded on the 2y and 4y
frames. Because it runs on the trimmed frame in both paths, the first ~20
closed candles of each tf at the start of a dataset have NaN bounds
(feature warm-up), identically in single-pass and chunked output. Stale CB
columns already on the frame are dropped before the stage (rerun safety). G7
(chunked == single-pass) was run on synthetic inputs only (114 columns × 5,760
rows, max diff 0.0), not on a real dataset; no real dataset has been re-prepped
with the stage yet (oos2m was materialized, 2y / 4y not touched).

**Existing datasets.** A full re-prep of 4y takes about a day, so
`scripts/cb_markers_materialize.py` adds the columns to an existing
`df_with_indicators.pkl` in place (backup first, run in the container
because the volume is root-owned). Where `ema_25_diff_prc` and
`ema_25_slope_class` are absent it backfills them with a vectorized
equivalent of the fields: forming `{tf}_ema_25` against the previous candle's
EMA **as the field sees it** — a talib EMA over the 104 closed candles of the
field's input slice, recomputed per closed candle (ruling, task 07). The
stored closed `{tf}_ema_25` (105-candle window, talib seeds each window on its
first 25 values) is not the same number; using it would be off by up to
2.3e-3 %-pt with 45 / 63 / 58 slope-class flips on oos2m (15 / 60 / 240). The
backfill matches the field to rtol 1e-9 on a freshly prepared small frame.

**Limitation.** In the first 103 closed candles of each tf inside a trimmed
dataset the field's window reached into warm-up rows prep dropped, so the
field value cannot be recovered; the stored closed `ema_25` is used there. On
oos2m that is 1.82 % / 7.27 % / 29.10 % of rows (15 / 60 / 240), estimated
error up to ~2.3e-3 %-pt, about 1 / 5 / 24 slope-class flips (estimate). It
affects only `ema_25_slope_class` → `cb_f_trend`; a full re-prep removes it
(`executor/TECH_DEBT.md` §19).

oos2m was materialized in place on 2026-10-05: 752 → 872 columns (114 CB + 6
backfill), backup `df_with_indicators.pkl.precb_bak`. 2y and 4y are not
materialized (open decision).

### Backtesting

No compute. `SimulationData` loads `df_with_indicators.pkl`, so the columns
are reachable through `WideDataPoint.get(name, tf)` once the dataset is
prepared or materialized. No sidecar joins are added to `SimulationData`.
`get(name, tf, shift=N)` returns the value on the Nth-last `{tf}_is_closed`
row with index ≤ ts — the current row counts when it is itself a closing row
(data-layer spec §7). G9 passed on unit tests; the real-dataset `simulate`
smoke was not run (simulate writes training state / report into the dataset
volume), so reports against the `.precb_bak` frame were not compared.

In-sample warning for whoever backtests on these columns: the bound models,
the ladder and the class thresholds are fit on 2023-01-01 → 2024-12-31. Any
backtest window inside that range is in-sample for all of them.

### Live session

Live already fetches the klines and recomputes every indicator on every tick
(about once per second), and the last row of each tf frame is the forming
candle with its current indicator values. `LiveCbStage` therefore runs on
**every tick**, inside `LiveData.build_candles()` right after the indicator
compute. It triggers **no additional indicator computation**.

Conceptually, each tick is equivalent to assembling a small wide frame and
running `compute_cb` on it: rows are the closing minutes of the closed
candles of each tf (values from the tf frames) plus one row for the current
minute, which carries the forming values of every tf and the current 1-min
candle. Rows are sparse in time, which the kernel tolerates because it
locates candles by `is_closed` and measures progress by wall-clock. As built
(Task 09), the stage does not run `compute_cb` per tick: it caches the closed
bounds and the forming-feature history per (tf, closed block) and evaluates
only the current row through the same kernel `tf_columns`; `build_wide` +
`compute_cb` remain the test and parity oracle, and
`test_update_equals_compute_cb_on_build_wide` pins the equality over all 114
columns. What the last row of the result contains, per tf:

1. **Closed bounds, zones.** Closed-candle rows give the feature history;
   the bound for the current candle is the prediction at the last closed
   candle. Constant through the candle.
2. **Forming bound.** Features come from the forming values on the last row
   plus the closed history. Live has forming indicator values only for
   *now*, not for earlier minutes, so to keep the prep rule "the bound at
   minute *t* is the prediction from minute *t − 1*" the stage holds one
   value per `(tf, side)`: the prediction of the latest tick of the previous
   minute whose bound was finite. As implemented (ruling, task 09): the
   fresh set is reset at every minute change; within a minute it is updated
   only for `(tf, side)` whose prediction is finite on that tick, so a tf
   that is unusable on the last tick (fetch-order skew around a candle
   close) keeps the earlier same-minute prediction. At rollover to the next
   minute the fresh set becomes the held set; after a gap > 1 minute or the
   clock going back the held set is empty. The held value is applied **per
   component** (`nc_pred_prev`, ruling task 05), but live stores only
   finite-bound predictions, so a held entry never has a NaN bound: wherever
   the live bound is NaN, `cbnc_*_std` is NaN too. Prep's row shift can give a
   finite `_std` beside a NaN bound in feature warm-up (see "Columns") —
   a known live/prep asymmetry, limited to warm-up (final review). After a restart `cbnc_*` is NaN until the first
   rollover (under one minute).
3. **extdone.** From the current row alone: the forming candle's high/low
   in the tf frame, the 1-min close and 1-min ATR. No history, no state.
4. **Markers and filters.** On the current minute.

Values on the data point describe the **current, forming minute** and
update every tick, like every other live indicator. Within a minute
`cb_inzone` can only turn true (the 1-min low only falls, the high only
rises); `extdone` and the class-based flags can change until the minute
closes. The value at the last tick of a minute is the one that corresponds
to the prep row of that minute.

Changes this requires:

- The last kline of each frame is the forming candle; the stage treats it as
  such regardless of the `is_closed` flag live sets on it.
- Outputs are written to the last row of the matching tf frame as
  `{tf}_<name>`, so `LiveDataPoint.get(name, tf)` returns them. History rows
  of the frame are not filled.

Two degraded states exist. Inside a usable tf, kernel warm-up (NaN features)
gives float NaN and bool False (0.0), as in prep. A tf that is unusable as a
whole gives NaN in every column, bools included. As implemented, a
tf whose frame is missing, empty, lacks an input column, is stale (last
index ≠ the current minute's candle open) or has fewer than
`MIN_CLOSED_CANDLES = 13` closed candles (what `V_std12` needs) is unusable
for the tick: all its columns are NaN (bools included — `0.0` would be a
value and was published as a change on every candle-boundary fetch skew;
final review I2), with one warning per (tf, cause); other tfs still compute. Live frames
normally hold 119 closed candles, so the 13-candle rule only fires after an
outage; in that state live shows no extdone / filter flags where prep would.

Performance as built: the closed bounds and forming-history aggregates of a
tf depend only on its closed candles and are cached per (tf, closed block);
each tick evaluates only the current row through the same kernel functions.
Measured on the G8 replay: mean 81 / p95 135 / max 249 ms per `update`
(before caching 221 / 363 / 452). **The 50 ms target is not met**; getting
under it needs a numpy one-row evaluation, i.e. a second implementation of
the kernel maths, which was not done (open decision, `executor/TECH_DEBT.md`
§16).

Failure handling: `LiveData` logs a stage exception once per exception type
and continues the tick; the CB columns are then **absent** from the frames
for that tick (also when the stage is disabled for lack of a model), so
`LiveDataPoint.get` raises `KeyError` for them — future consumers need a
default (`executor/TECH_DEBT.md` §18).

### MQ broadcast

Added to `configs/shared_indicators_config.yaml`, timeframes `[15, 60, 240]`:

| Group | Names |
|---|---|
| Closed bounds and zones | `cb_high`, `cb_low`, `cb_zone_long`, `cb_zone_short` |
| Marker | `cb_inzone_long`, `cb_inzone_short` |
| Forming bounds | `cbnc_high`, `cbnc_low` |
| extdone | `extdone_high`, `extdone_low`, `cb_f_extdone_long`, `cb_f_extdone_short` |
| EMA trend filter | `cb_f_trend_long`, `cb_f_trend_short` |

Computed and stored but **not broadcast**: `cb_f_mcx_*`, `cbx_inzone_*`,
the bands (`*_std`, `*_up`, `*_dn`), `cbnc_tgt_*`, `cbnc_zone_*`,
`cbnc_inzone_*`, `extdone_*_lvl`.

Wire names are `{tf}_{name}` as today. Booleans go as `1.0` / `0.0`. The
publisher already skips non-finite values.

Values on the wire are the current tick's values. A marker is a one-minute
event and the publisher runs on a 30-second interval, which can miss it, so
a change of any broadcast CB boolean also triggers an immediate publish. As
built: an `on_change: true` key per allowlist entry (`config_loader`), set on
the eight bool names. The 30 s heartbeat publishes the whole allowlist
(including the `on_change` entries) on its own cadence, exactly as before. On
any tick in between, an `on_change` reading whose value differs from its last
**published** value is published immediately — only the changed readings, not
the whole allowlist — and the heartbeat clock is not reset (final review I1:
the interval exists because of the executor's append-only readings table; a
flapping flag must not republish every reading per tick). NaN / unreadable is
never a change; the last published value survives a NaN run, so a different
finite value afterwards is a change. Known gap: a value never published before
(after start) is not a "change", so the first finite value waits up to the
30 s heartbeat (`executor/TECH_DEBT.md` §17). G10 (live dry run) not run.

### Viewer

- `view_full.py` keeps its sidecar joins. Joins never overwrite existing
  columns, so on a dataset with main-flow columns the main-flow values win
  and the remaining sidecars still add their own columns.
- Markers are drawn from `{tf}_cb_inzone_{side}` as today.
- Three overlay toggles restrict the drawn CB markers to rows where the
  flag holds: `cb_f_extdone` (**on** by default, so the chart keeps today's
  vetoed look), `cb_f_trend` and `cb_f_mcx` (off by default). The
  `cb_inzone` entries leave `_ZONE_VETO`; the toggle replaces that
  hard-coded marker veto. Datasets without the flag columns draw unfiltered.
- The zone **line** veto (`cb_zone_*` blanked while extdone holds) follows
  the `cb_f_extdone` toggle and reads the main-flow extdone columns.
- `_MARKER_VETO` (overshoot, sidecar-based) is unchanged.
- `cbx` markers are drawn as today.
- As built: the toggles are offered only when a flag column exists at some
  available tf. **Behaviour change for sidecar-only datasets** (no main-flow
  flag columns): the old hard-coded extdone veto on `cb_inzone` markers and on
  the `cb_zone` lines is gone, so they draw unfiltered (intended by the plan).
  The visual check on oos2m was not run (user-gated).

Markers on screen will change against today's full view for two reasons: the
2y ladder replaces the oos2m-picked one, and extdone is no longer sticky, so
fewer markers are hidden.

## Acceptance gates

All run in Docker. Numbers are reported, not assumed.

| Gate | Check |
|---|---|
| G1 | Model export: refit `band_pct` equals `candle_bounds_meta.json` (rel < 1e-3); numpy prediction equals sklearn (< 1e-12). |
| G2 | Stage closed bounds on oos2m equal stored `df_with_candle_bounds.pkl`, interior rel < 1e-9. Known edge deltas (one warm-up candle, final row) as in `run_cbnc.py`. |
| G3 | `cb_zone_*`, `cb_inzone_*` equal the stored sidecar on all three TFs. |
| G4 | `cbnc_*`, `cbx_inzone_*` equal stored `df_with_candle_bounds_nc.pkl`. |
| G5 | extdone kernel run with the oos2m ladder and row-count progress, then made sticky within the candle in the test (running OR), reproduces stored `df_with_ext_done.pkl` exactly. Then with the 2y ladder on oos2m: P(hold) at the first true minute per candle matches the results doc table; share of true minutes is reported. |
| G6 | Unit tests for `cb_f_extdone`, `cb_f_trend`, `cb_f_mcx` on hand-built rows, including NaN and warm-up. |
| G7 | Chunked prep equals single-pass prep for all new columns. Materialize script output equals prep output on a small dataset. |
| G8 | Live parity: replay a prepared fixture through `LiveCbStage`, one tick at the end of each minute (frames built the way `LiveData` builds them), and compare with the prep row of that minute. Bool columns: mismatch rate reported and explained; float columns: relative difference reported. The tolerance is set from this measurement and recorded in the test. As run: 600 ticks on oos2m; proposed `MAX_BOOL_MISMATCH_RATE = 0.005`, `MAX_FLOAT_REL_DIFF = 2e-4` — **proposed, not agreed**; both constants are still `None` in `scripts/cb_live_parity.py` (report-only). |
| G9 | `SimulationData` exposes the columns through `WideDataPoint.get`. |
| G10 | Broadcast: a live dry run publishes the listed names with finite values. |

Also reported for oos2m: marker minutes per tf and side, unfiltered and
under each of the four filters (extdone with the 2y ladder).

## Risks

- **Live and prep indicator inputs are not identical today.** Different
  window lengths (120 candles against 105) and exchange-built against
  resampled candles shift `rsi`, `macd` and `ema` slightly, and those feed
  the bound. G8 measures the effect; if a marker flips more than rarely, the
  fix belongs in the live frame construction, and that would be raised
  before widening this change. Measured: `cb_inzone_*` 0 flips in 600 ticks;
  input differences up to 6e-4 (rsi), 2e-5 (ema), 8e-3 (macd) relative, most
  likely from the 120- vs 105-candle TA-Lib seed (`executor/TECH_DEBT.md` §15).
- **Per-tick cost in live.** The stage builds a frame of a few hundred rows
  and runs the vectorized kernel on it every tick. Measured in G8: mean 81 /
  p95 135 / max 249 ms after caching, above the 50 ms target (open decision).
- **Forming bound in live is taken at the last tick of a minute**, not at
  the exchange's final 1-min kline; the two can differ by the last second
  of trading. Covered by the G8 measurement.
- **One pair.** Models exist only for LINK/USDT; other pairs get no CB
  columns until models are exported for them.
- **Second OOS window still missing** for the extdone ladder (open item in
  the results doc). This change makes the ladder live-visible but no trading
  decision depends on it yet.

## Observed, out of scope

Found while mapping the flows; not addressed here:

- `align_*` cross-TF fields are all NaN in both prep and live.
- yaml `applies_to` is ignored for every group except `nn_features`.
- No general prep-to-live parity test exists for indicators.

## Testing

Unit tests under `tests/unit/data_layer/` for the kernel (features, bounds
against a tiny hand-checked frame, zones, extdone ladder steps and
per-minute behaviour, filters), for `models.py`, and for both stage adapters.
Integration tests for G7–G9 run in Docker under a separate compose project.
Viewer tests cover the three filter toggles.
