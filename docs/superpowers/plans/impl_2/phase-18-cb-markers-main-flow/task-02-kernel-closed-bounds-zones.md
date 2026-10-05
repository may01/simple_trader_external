# Task 02: Kernel — closed bounds, closed zone, marker

**Phase:** 18 — CB Markers Main Flow
**Depends on:** Task 01 (`params`, `BoundModel`)
**Produces:** `indicators.candle_bounds.kernel`: `to_rows`, `closed_frame`, `closed_bounds`, `closed_zones`

---

## Goal

Port the closed-candle part of `notebooks/candle_bounds_nc/cbnc.py` into the package, predicting with `BoundModel`, and add the closed zone and the raw marker, which no code produces today.

## Context

Read `cbnc.py` `closed_frame`, `_to_rows`, `infer_closed` (lines 44–130) — the port must be numerically identical. The only change is the predictor: `model.predict_pct(valid[FEATURES].to_numpy())` instead of the sklearn pipeline.

Wide-frame facts the kernel relies on (`data._build_wide_df`): one row per minute; `{tf}_high` / `{tf}_low` are running extremes of the candle; `{tf}_close` is the minute's close; `{tf}_is_closed` is True only on the candle's last minute; indicator columns on a row are forming-candle values, final on the closed row.

Closed zone and marker were verified against the stored oos2m sidecar on 2026-10-05 (exact):

```
cb_zone_long   = cb_low  + ZONE_FRAC * (cb_high - cb_low)
cb_zone_short  = cb_high - ZONE_FRAC * (cb_high - cb_low)
cb_inzone_long  = 1_low  <= cb_zone_long
cb_inzone_short = 1_high >= cb_zone_short
```

No span-validity guard on the closed zone: the stored artifact has none and G3 requires an exact match.

## Files

- Create: `indicators/candle_bounds/kernel.py`
- Test: `tests/unit/data_layer/test_cb_kernel_closed.py`
- Create: `tests/unit/data_layer/cb_fixtures.py` (shared synthetic wide frame builder, reused by Tasks 03–06, 09)

## Interface

```python
# indicators/candle_bounds/kernel.py
def to_rows(closed_series: pd.Series, index: pd.Index) -> pd.Series: ...
    # per-closed-candle series -> 1-min index: row t carries the last candle closed strictly before t

def closed_frame(df: pd.DataFrame, tf: int, side: str) -> pd.DataFrame: ...
    # index = closing timestamps; columns FEATURES + ["d", "ext"]   (no "target": inference only)

def closed_bounds(df: pd.DataFrame, model: BoundModel) -> pd.DataFrame: ...
    # index = df.index; columns {tf}_cb_{side}, {tf}_cb_{side}_std, {tf}_cb_{side}_up, {tf}_cb_{side}_dn

def closed_zones(cb: pd.DataFrame, df: pd.DataFrame, tf: int) -> pd.DataFrame: ...
    # cb must hold {tf}_cb_high and {tf}_cb_low
    # columns {tf}_cb_zone_long, {tf}_cb_zone_short (float), {tf}_cb_inzone_long, {tf}_cb_inzone_short (bool)
```

```python
# tests/unit/data_layer/cb_fixtures.py
def make_wide(n_minutes: int = 6000, seed: int = 0, start: str = "2025-01-01 00:00") -> pd.DataFrame: ...
    # random-walk 1-min OHLC -> data._build_wide_df -> adds, per tf in (15, 60, 240):
    #   {tf}_rsi_14, {tf}_rsi_ma8, {tf}_macd_12_26_9, {tf}_macd_hist_12_26_9, {tf}_ema_25
    #   (deterministic smooth functions of {tf}_close; real TA-Lib not needed for kernel tests),
    #   {tf}_move_class (ints -3..3), {tf}_ema_25_slope_class (ints -1..1), and 1_atr_14_ma_5 (> 0)
def make_models(seed: int = 0) -> ModelSet: ...
    # six BoundModel with small random coef, scale = 1, mean = 0, band_pct = 0.3
```

## Key Constraints

- Closed-candle selection is `df[f"{tf}_is_closed"] == True` (the column can be object dtype with NaN).
- Bool outputs: comparison with NaN level → False (`.fillna(False)` then `astype(bool)`).
- `kernel.py` must not import from `notebooks/`, `data.py`, or `helpers.py`. Pure functions of their arguments.
- No look-ahead: a bound on row *t* depends only on rows of candles closed strictly before *t*.

## Tests (RED first)

`tests/unit/data_layer/test_cb_kernel_closed.py`:

- `test_to_rows_strictly_before` — closed series at 00:14 and 00:29 with values 1, 2; index 00:00–00:44 → rows 00:00–00:14 NaN, 00:15–00:29 = 1, 00:30–00:44 = 2. (Row 00:14, the closing row itself, must still be NaN.)
- `test_closed_frame_features_by_hand` — a 4-candle hand-built tf-15 frame with known highs; assert `d` equals `pct_change * 100` of the closed highs, `V_range`, `V_body`, `A_position` against hand values.
- `test_closed_bounds_constant_within_candle` — on `make_wide`, for every candle, `{15}_cb_high` has one unique non-NaN value across its rows.
- `test_closed_bounds_no_lookahead` — compute on `make_wide(6000)`; compute again on a copy where all rows from minute 3000 on have OHLC and indicators multiplied by 2; assert outputs on rows `< 3000` are identical.
- `test_closed_bounds_value_formula` — pick one candle k; assert `cb_high` on candle k+1's rows equals `ext[k] * (1 + pred[k] / 100)` and `_std` equals `ext[k] * band_pct / 100`, `_up - _dn == 2 * _std`.
- `test_closed_bounds_warmup_nan` — rows before the first candle with complete features are NaN.
- `test_closed_zone_formulas` — hand `cb` frame with `cb_high = 110`, `cb_low = 100` → `zone_long == 100.5`, `zone_short == 109.5`.
- `test_inzone_boundaries` — `1_low == zone_long` → True; `1_low` one tick above → False; mirrored for short with `1_high`.
- `test_inzone_nan_level_false` — NaN bound → both inzone columns False, dtype bool.
- `test_dtypes` — bound and zone columns float64, inzone columns bool.

## Steps

- [x] Write `cb_fixtures.py` and the test file. Run in Docker: `docker compose -p cbtest run --rm ohlc_gen python -m pytest tests/unit/data_layer/test_cb_kernel_closed.py -q` → FAIL.
- [x] Implement `to_rows`, `closed_frame`, `closed_bounds`, `closed_zones`.
- [x] Re-run → PASS.
- [ ] Stage; describe; wait for confirmation. Suggested message: `feat(cb): kernel closed bounds, zone and marker`. *(As executed: staged by the controller with `git add` after review; no commit — the commit waits for the user's confirmation at handover.)*
