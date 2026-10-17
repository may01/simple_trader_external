# Task 01: Params and kernel — overshoot z and the fourth pass flag

**Phase:** 19 — CB Overshoot Main Flow
**Depends on:** — (phase 18 merged, `97fb76d`)
**Produces:** `params.OVERSHOOT_Q`, `params.OVERSHOOT_THR`, `kernel.overshoot`, `kernel.filters` (new signature)
**Gates:** G1, G2

---

## Goal

Compute per 1-min row how far the minute's extreme is past the closed bound, in band-sd units, and turn it into a pass flag against the frozen thresholds.

## Context

Definition (spec "Current state", `run_cb_overshoot.overshoot`):

```
z_long[t]  = ({tf}_cb_low[t]  − 1_low[t])  / {tf}_cb_low_std[t]
z_short[t] = (1_high[t] − {tf}_cb_high[t]) / {tf}_cb_high_std[t]
cb_f_overshoot_side[t] = not (z_side[t] > OVERSHOOT_THR[tf][side])
```

`cb_*` / `cb_*_std` are the previous closed candle's prediction broadcast to the current candle's rows (`to_rows`), so z is known at the same instant as the marker. Unlike the sidecar, a zero or NaN band gives NaN, never ±inf.

## Files

- Modify: `indicators/candle_bounds/params.py`
- Modify: `indicators/candle_bounds/kernel.py`
- Modify: `indicators/candle_bounds/stage.py` (`tf_columns` passes `over` into `filters`; column list is Task 02)
- Test: `tests/unit/data_layer/test_cb_kernel_extdone.py` (new class `TestOvershoot`)

## Interface

```python
# params.py
OVERSHOOT_Q: float = 0.75
OVERSHOOT_THR: dict[int, dict[str, float]] = {
    15:  {"long": 0.3477, "short": 0.3808},
    60:  {"long": 0.3756, "short": 0.3796},
    240: {"long": 0.4693, "short": 0.5178},
}

# kernel.py
def overshoot(cb: pd.DataFrame, df: pd.DataFrame, tf: int) -> pd.DataFrame: ...
    # cb: closed_bounds output (needs {tf}_cb_{high,low}, {tf}_cb_{high,low}_std), df: needs 1_high, 1_low
    # -> {tf}_cb_overshoot_long, {tf}_cb_overshoot_short (float64; index = df.index)

def filters(df: pd.DataFrame, ext: pd.DataFrame, over: pd.DataFrame, tf: int) -> pd.DataFrame: ...
    # over = overshoot output; adds {tf}_cb_f_overshoot_long, {tf}_cb_f_overshoot_short (bool)
```

## Key Constraints

- `std <= 0`, NaN std, NaN bound or NaN extreme → z NaN (mask before dividing; `np.errstate` is not enough because 0/0 and x/0 produce inf/nan, and a negative std must not pass as a sign flip).
- `NaN > thr` is False → flag True. Pin it.
- Thresholds are read from `params.OVERSHOOT_THR` at call time (no copy in the kernel).
- z is computed on every row, in zone or not.
- No change to the six existing flags.

## Tests (RED first)

`tests/unit/data_layer/test_cb_kernel_extdone.py::TestOvershoot`:

- `test_z_long_exact` — hand frame, tf 15: `cb_low = [100, 100, 100]`, `std = [2, 2, 2]`, `1_low = [99, 100, 101]` → `[0.5, 0.0, -0.5]` to 1e-12.
- `test_z_short_exact` — mirror with `cb_high`, `1_high`.
- `test_nan_std_is_nan`, `test_zero_std_is_nan`, `test_negative_std_is_nan`, `test_nan_bound_is_nan`, `test_nan_extreme_is_nan` — each → NaN, and `np.isinf` never True.
- `test_columns_and_dtype` — exactly the two names, float64, index preserved.
- `test_flag_false_iff_above_threshold` — per tf and side: z = thr − 1e-6 → True, z = thr → True (not strictly above), z = thr + 1e-6 → False. Read thr from `OVERSHOOT_THR`.
- `test_flag_nan_passes` — z NaN → both True.
- `test_flag_dtype_bool` — the two new columns are bool; the six old names are still present and unchanged on the extdone fixture.
- `test_thresholds_frozen` — `OVERSHOOT_THR` equals the six spec values exactly (pins the freeze; a refit must change the test deliberately). `OVERSHOOT_Q == 0.75`.

## Steps

- [x] Add the two constants to `params.py`.
- [x] Write `TestOvershoot`. Run in Docker: `docker compose -p cbtest run --rm -e PYTHONDONTWRITEBYTECODE=1 ohlc_gen python -m pytest -p no:cacheprovider tests/unit/data_layer/test_cb_kernel_extdone.py -q` → FAIL (missing `overshoot`, wrong `filters` arity).
- [x] Implement `kernel.overshoot`; extend `kernel.filters(df, ext, over, tf)`; update `stage.tf_columns` to compute `over = kernel.overshoot(cb, df, tf)` and pass it (Task 02 adds the names to `_tf_names`; until then `tf_columns`'s `[_tf_names(tf)]` selection drops them — fine for this task's unit tests).
- [x] Re-run → PASS (G1, G2). Run the whole phase-18 CB suite too → still green.
- [ ] Stage; describe; wait for confirmation. Suggested message: `feat(cb): overshoot z and cb_f_overshoot pass flag`.
