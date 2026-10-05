# Task 03: Kernel — forming bounds, hybrid zone, intersection

**Phase:** 18 — CB Markers Main Flow
**Depends on:** Task 02 (`to_rows`, `closed_frame`, `closed_bounds`, `closed_zones`)
**Produces:** `kernel.forming_features`, `kernel.forming_prediction`, `kernel.forming_bounds`, `kernel.forming_zones`

---

## Goal

Port the forming-candle (non-closed) inference and the hybrid zone from `cbnc.py`, split so that live can take the **unshifted** prediction of the last row.

## Context

Read `cbnc.py` `forming_features`, `infer_forming`, `add_zones` (lines 133–242). Port numerically identical.

`infer_forming` computes a prediction per 1-min row from that row's forming-candle state, then shifts it one row: the value on row *t* is the prediction from row *t − 1*. Prep keeps that shift. Live cannot reproduce the previous row (it only has forming indicator values for now), so it holds the previous minute's prediction itself (Task 09) and needs the unshifted value — hence two functions.

Hybrid zone (from `add_zones`):

```
tgt_long   = cbnc_high * (1 - TGT_SHRINK_PCT / 100)
tgt_short  = cbnc_low  * (1 + TGT_SHRINK_PCT / 100)
zone_long  = cb_low  + ZONE_FRAC * (tgt_long - cb_low)
zone_short = cb_high - ZONE_FRAC * (cb_high - tgt_short)
cbnc_inzone_long  = (1_low  <= zone_long)  and (tgt_long  - cb_low  > 0)
cbnc_inzone_short = (1_high >= zone_short) and (cb_high - tgt_short > 0)
cbx_inzone_side   = cbnc_inzone_side and cb_inzone_side
```

## Files

- Modify: `indicators/candle_bounds/kernel.py`
- Test: `tests/unit/data_layer/test_cb_kernel_forming.py`

## Interface

```python
def forming_features(df: pd.DataFrame, tf: int, side: str) -> pd.DataFrame: ...
    # index = df.index; columns FEATURES + ["ext_f"]

def forming_prediction(df: pd.DataFrame, model: BoundModel) -> pd.DataFrame: ...
    # UNSHIFTED. index = df.index; columns "bound", "band" (price units); NaN where features incomplete

def forming_bounds(pred: pd.DataFrame, tf: int, side: str) -> pd.DataFrame: ...
    # pred = forming_prediction output; applies shift(1)
    # columns {tf}_cbnc_{side}, {tf}_cbnc_{side}_std, {tf}_cbnc_{side}_up, {tf}_cbnc_{side}_dn

def forming_zones(cbnc: pd.DataFrame, cb: pd.DataFrame, df: pd.DataFrame, tf: int) -> pd.DataFrame: ...
    # cbnc holds {tf}_cbnc_high/_low; cb holds {tf}_cb_high/_low and {tf}_cb_inzone_long/_short
    # columns {tf}_cbnc_tgt_long/_short, {tf}_cbnc_zone_long/_short (float),
    #         {tf}_cbnc_inzone_long/_short, {tf}_cbx_inzone_long/_short (bool)
```

## Key Constraints

- `forming_bounds` shift is by **row**, exactly as the experiment. Gap handling in prep is unchanged from the experiment (G4 requires equality with the stored sidecar).
- Inverted hybrid span → `cbnc_inzone` False, hence `cbx_inzone` False.
- NaN anywhere in a comparison → False.

## Tests (RED first)

`tests/unit/data_layer/test_cb_kernel_forming.py` (uses `cb_fixtures.make_wide`, `make_models`):

- `test_forming_features_equal_closed_on_closing_row` — on every row where `15_is_closed` is True, `forming_features(df, 15, "high")[FEATURES]` equals `closed_frame(df, 15, "high")[FEATURES]` on that timestamp (rtol 1e-9), for rows where both are non-NaN. This is the experiment's convergence property.
- `test_forming_prediction_converges_to_closed_bound` — experiment gate G3: `forming_bounds` on the first row of each candle equals `closed_bounds` `{tf}_cb_{side}` on that row (rtol 1e-6), all three tfs, both sides.
- `test_forming_bounds_is_prediction_shifted_one_row` — `forming_bounds(pred, 15, "high")["15_cbnc_high"].iloc[1:]` equals `pred["bound"].iloc[:-1]` values; first row NaN.
- `test_forming_no_lookahead` — same perturbation test as Task 02 (`rows >= 3000` scaled ×2): `cbnc` on rows `<= 3000` unchanged.
- `test_hybrid_zone_formulas` — hand frames: `cbnc_high = 200`, `cb_low = 100`, `cb_high = 150`, `cbnc_low = 90` → `tgt_long == 199.7`, `zone_long == 100 + 0.05 * 99.7`, `tgt_short == 90.135`, `zone_short == 150 - 0.05 * (150 - 90.135)`.
- `test_inverted_span_no_zone` — `cbnc_high` below `cb_low` → `cbnc_inzone_long` False even when `1_low` is far below the zone level.
- `test_cbx_is_intersection` — truth table over the four combinations of `cb_inzone` and `cbnc_inzone`.
- `test_bool_dtypes_and_nan_false` — NaN `cbnc_high` → `cbnc_inzone_long`, `cbx_inzone_long` False; dtype bool.

## Steps

- [x] Write the test file. Run in Docker: `docker compose -p cbtest run --rm ohlc_gen python -m pytest tests/unit/data_layer/test_cb_kernel_forming.py -q` → FAIL.
- [x] Implement the four functions. *(As executed: `forming_prediction`'s `band` follows the reference — NaN only where `ext_f` is NaN — so `{tf}_cbnc_{side}_std` (and closed `_std`) stay finite during feature warm-up while the bound is NaN; ruling: parity with the stored artifacts (G2/G4) wins over the "warm-up floats NaN" constraint for the `_std` family. In Task 09 `forming_features` was further split into `forming_history` + `forming_row_features` for the live cache, behaviour unchanged.)*
- [x] Re-run → PASS. Re-run `test_cb_kernel_closed.py` → still PASS.
- [ ] Stage; describe; wait for confirmation. Suggested message: `feat(cb): kernel forming bounds, hybrid zone, intersection`. *(As executed: staged by the controller with `git add` after review; no commit — the commit waits for the user's confirmation at handover.)*
