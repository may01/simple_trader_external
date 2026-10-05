# Task 04: Kernel — per-minute extdone and the filter flags

**Phase:** 18 — CB Markers Main Flow
**Depends on:** Task 01 (`params.EXTDONE_LADDER`, `ATR_COL`), Task 02 (`kernel.py` exists)
**Produces:** `kernel.candle_progress`, `kernel.ladder_threshold`, `kernel.extdone`, `kernel.filters`
**Gate:** G6

---

## Goal

Compute the extreme-done state per minute (not sticky) and the three pass-flag filters.

## Context

Definition (spec "extdone definition"):

```
run_high[t] = {tf}_high[t]            run_low[t] = {tf}_low[t]
pull_high[t] = ({tf}_high[t] - 1_close[t]) / 1_atr_14_ma_5[t]
pull_low[t]  = (1_close[t] - {tf}_low[t])  / 1_atr_14_ma_5[t]
progress[t]  = (minutes since candle open, counting t) / tf
extdone_side[t] = pull_side[t] >= d(progress[t])  and  atr finite and > 0
```

`d(progress)` steps through the ladder: below the first `progress_from` the threshold is `+inf` (never set); each `(p0, d)` applies for `progress >= p0` until the next step.

This differs from `notebooks/zone_profitability/run_extdone.py` in two deliberate ways: the state is **not** made sticky within the candle, and progress is wall-clock, not row count. `by_rows=True` exists only so Task 07 can reproduce the stored sidecar.

Filters:

```
cb_f_extdone_long  = not extdone_high        cb_f_extdone_short = not extdone_low
cb_f_trend_long    = ema_25_slope_class != -1    cb_f_trend_short = ema_25_slope_class != +1
cb_f_mcx_long      = move_class == -3            cb_f_mcx_short   = move_class == +3
```

## Files

- Modify: `indicators/candle_bounds/kernel.py`
- Test: `tests/unit/data_layer/test_cb_kernel_extdone.py`

## Interface

```python
def candle_progress(df: pd.DataFrame, tf: int, *, by_rows: bool = False) -> np.ndarray: ...
    # by_rows=False: ((index - index.floor(f"{tf}min")) / 1min + 1) / tf        -> in (0, 1]
    # by_rows=True : (row position inside the candle + 1) / tf, candles delimited by {tf}_is_closed
    #                (rows after a close through the next closing row share a candle) — experiment convention

def ladder_threshold(progress: np.ndarray, ladder: tuple[tuple[float, float], ...]) -> np.ndarray: ...
    # +inf below the first step

def extdone(df: pd.DataFrame, tf: int, ladder: dict[str, tuple[tuple[float, float], ...]], *,
            by_rows: bool = False) -> pd.DataFrame: ...
    # columns {tf}_extdone_high, {tf}_extdone_low (bool), {tf}_extdone_high_lvl, {tf}_extdone_low_lvl (float)

def filters(df: pd.DataFrame, ext: pd.DataFrame, tf: int) -> pd.DataFrame: ...
    # ext = extdone output
    # columns {tf}_cb_f_extdone_long/_short, {tf}_cb_f_trend_long/_short, {tf}_cb_f_mcx_long/_short (bool)
```

## Key Constraints

- No `groupby(...).cummax()` on the state: per-minute only.
- `_lvl` = `{tf}_high` (or `{tf}_low`) where the state is True, NaN elsewhere.
- NaN / non-finite / non-positive ATR → extdone False.
- NaN class value: `cb_f_trend` True for both sides (NaN is "neutral", matching `ema_slope_class`, which maps NaN slope to 0); `cb_f_mcx` False for both sides.
- `cb_f_extdone` is True wherever extdone is False, including warm-up rows. It is a pass flag: "nothing blocks".

## Tests (RED first)

`tests/unit/data_layer/test_cb_kernel_extdone.py`:

- `test_progress_wall_clock` — tf 15, rows 10:00…10:14 → `1/15 … 15/15`.
- `test_progress_wall_clock_with_gap` — **Review Focus 1.** Rows 10:00–10:03 and 10:08–10:14 (10:04–10:07 missing) → progress at 10:08 is `9/15`, not `5/15`.
- `test_progress_by_rows_with_gap` — same frame, `by_rows=True` → 10:08 is `5/15`.
- `test_ladder_threshold_steps` — ladder `((0.25, 5.0), (0.50, 2.5), (0.75, 1.5))`: progress `0.2 → inf`, `0.25 → 5.0`, `0.49 → 5.0`, `0.50 → 2.5`, `0.75 → 1.5`, `1.0 → 1.5`.
- `test_ladder_single_step_240` — ladder `((0.75, 8.0),)`: `0.74 → inf`, `0.75 → 8.0`.
- `test_extdone_true_at_threshold` — hand tf-15 candle, ATR = 1, `15_high = 110`; at 10:08 (progress 0.6, d = 2.5) close 107.5 → `extdone_high` True (pull exactly 2.5); close 107.6 → False.
- `test_extdone_not_sticky` — minute 10:08 pull 3.0 (True), minute 10:09 pull 1.0 (False under d = 2.5) → `extdone_high` is `[True, False]`. This is the test that fails if anyone reintroduces stickiness.
- `test_extdone_can_reactivate` — True, False, True across three minutes of one candle.
- `test_extdone_never_before_first_step` — progress < 0.25, pull 100 → False.
- `test_extdone_low_mirrored` — `(close - 15_low) / atr`.
- `test_extdone_per_side_ladder` — tf 60 at progress 0.6: pull 7.0 → `extdone_low` True (d = 6.0), `extdone_high` False (d = 8.0).
- `test_extdone_bad_atr_false` — ATR NaN, 0, inf → False, no warning raised.
- `test_lvl_only_when_true` — `_lvl` equals `15_high` on True rows, NaN on False rows.
- `test_filter_extdone_is_negation` — `cb_f_extdone_long == ~extdone_high`, `cb_f_extdone_short == ~extdone_low`.
- `test_filter_trend_truth_table` — class −1 → long False, short True; 0 → both True; +1 → long True, short False; NaN → both True.
- `test_filter_mcx_truth_table` — class −3 → long True, short False; +3 → long False, short True; each of −2…+2 → both False; NaN → both False.
- `test_filter_dtypes_bool`.

## Steps

- [x] Write the test file. Run in Docker: `docker compose -p cbtest run --rm ohlc_gen python -m pytest tests/unit/data_layer/test_cb_kernel_extdone.py -q` → FAIL.
- [x] Implement the four functions.
- [x] Re-run → PASS (G6). *(23 new tests. extdone requires ATR finite **and > 0**, as this brief says; the spec text "atr finite" was aligned in Task 12.)*
- [ ] Stage; describe; wait for confirmation. Suggested message: `feat(cb): per-minute extdone state and filter flags`. *(As executed: staged by the controller with `git add` after review; no commit — the commit waits for the user's confirmation at handover.)*
