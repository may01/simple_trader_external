# Task 05: Stage entry point — `compute_cb` / `compute_cb_columns`

**Phase:** 18 — CB Markers Main Flow
**Depends on:** Tasks 01–04
**Produces:** `indicators.candle_bounds.stage`: `CbResult`, `required_columns`, `expected_columns`, `compute_cb`, `compute_cb_columns`

---

## Goal

One function that turns a wide frame into all CB columns, used unchanged by prep, the materialize script and live.

## Files

- Create: `indicators/candle_bounds/stage.py`
- Test: `tests/unit/data_layer/test_cb_stage.py`

## Interface

```python
@dataclass(frozen=True)
class CbResult:
    columns: pd.DataFrame
    nc_pred_last: dict[tuple[int, str], tuple[float, float]]   # (tf, side) -> (bound, band) of the last row, unshifted

def required_columns() -> list[str]: ...
    # ["1_high", "1_low", "1_close", "1_atr_14_ma_5"] + per tf in TFS:
    # {tf}_open, _high, _low, _close, _is_closed, _rsi_14, _rsi_ma8, _macd_12_26_9, _macd_hist_12_26_9,
    # _ema_25, _move_class, _ema_25_slope_class

def expected_columns() -> list[str]: ...
    # per tf, in this order:
    #   cb_{high,low} + _std/_up/_dn, cb_zone_{long,short}, cb_inzone_{long,short},
    #   cbnc_{high,low} + _std/_up/_dn, cbnc_tgt_{long,short}, cbnc_zone_{long,short},
    #   cbnc_inzone_{long,short}, cbx_inzone_{long,short},
    #   extdone_{high,low}, extdone_{high,low}_lvl,
    #   cb_f_extdone_{long,short}, cb_f_trend_{long,short}, cb_f_mcx_{long,short}
    # = 38 columns per tf, 114 total

def compute_cb(wide_df: pd.DataFrame, models: ModelSet, *,
               nc_pred_prev: dict[tuple[int, str], tuple[float, float]] | None = None) -> CbResult: ...

def compute_cb_columns(wide_df: pd.DataFrame, pair: str | None = None) -> pd.DataFrame | None: ...
    # pair defaults to os.environ["PAIR"]; returns None (after one logged warning) when load_models(pair) is None
```

`nc_pred_prev` semantics (live only): when not `None`, the `cbnc_*` values **of the last row** are taken from it instead of from the row shift — `bound`, `band`, `bound + band`, `bound - band` — and `cbnc_tgt/zone/inzone/cbx` of the last row are computed from those. A key absent from the dict, or a NaN value, gives NaN for that `(tf, side)` on the last row. *(As implemented — ruling: the held pair is applied **per component**: a held `(NaN bound, finite band)` gives NaN `cbnc` / `_up` / `_dn` but a finite `_std`, which is exactly what prep's row shift gives for that row (live parity, consistent with the Task 03 `_std` ruling); a missing key gives all four NaN.)* An empty dict therefore means "no held prediction": last-row `cbnc_*` all NaN. Rows other than the last are unaffected. When `None` (prep), the plain row shift applies everywhere.

## Key Constraints

- `compute_cb` raises `ValueError("candle_bounds: missing input columns: [...]")` listing every absent `required_columns()` entry. It never silently skips a tf.
- It reads only `required_columns()` from `wide_df` and never mutates `wide_df`.
- `columns` has exactly `expected_columns()`, in that order, index identical to `wide_df.index`.
- An empty frame (0 rows) returns an empty `columns` frame with the expected columns and `nc_pred_last == {}`.
- `nc_pred_last` always has all six keys for a non-empty frame; values are NaN when the last row's features are incomplete.
- `compute_cb_columns` logs the "no model for pair" warning through `logs` once per pair per process, not once per call (live calls it every tick through the same loader).

## Tests (RED first)

`tests/unit/data_layer/test_cb_stage.py` (uses `cb_fixtures`):

- `test_expected_columns_count_and_unique` — 114, no duplicates, every name starts with `15_`, `60_` or `240_`.
- `test_compute_cb_columns_match_expected` — `list(result.columns.columns) == expected_columns()`; index equals input index.
- `test_compute_cb_equals_kernel_pieces` — for tf 15: `result.columns["15_cb_high"]` equals `kernel.closed_bounds(...)`; `15_extdone_low` equals `kernel.extdone(df, 15, EXTDONE_LADDER[15])`. Guards against the stage wiring the wrong ladder or side.
- `test_uses_production_ladder_per_side` — tf 60 hand row at progress 0.6, pull 7.0 → `60_extdone_low` True, `60_extdone_high` False.
- `test_input_not_mutated` — columns and values of `wide_df` unchanged after the call (`pd.testing.assert_frame_equal` against a deep copy).
- `test_missing_input_raises_naming_columns` — **Review Focus 4.** Drop `15_ema_25_slope_class` and `60_move_class` → `ValueError` whose message contains both names.
- `test_empty_frame` — 0-row frame with the required columns → 0 rows, expected columns, `nc_pred_last == {}`.
- `test_nc_pred_last_is_unshifted_last_row` — `result.nc_pred_last[(15, "high")][0]` equals `kernel.forming_prediction(df, model)["bound"].iloc[-1]`.
- `test_nc_pred_prev_overrides_last_row_only` — pass `{(15, "high"): (123.0, 1.0), ...all six}`: last row `15_cbnc_high == 123.0`, `_up == 124.0`, `_dn == 122.0`; `15_cbnc_tgt_long == 123.0 * (1 - 0.0015)`; second-to-last row equals the result without the override.
- `test_nc_pred_prev_empty_gives_nan_last_row` — `nc_pred_prev={}` → last row `cbnc_*` NaN, `cbnc_inzone_*` and `cbx_inzone_*` False.
- `test_compute_cb_columns_no_model_returns_none` — **Review Focus 3.** `compute_cb_columns(df, pair="btc_usdt") is None`; warning logged exactly once across two calls.
- `test_compute_cb_columns_default_pair_from_env` — monkeypatch `PAIR=link_usdt` → returns a frame.
- `test_no_sklearn_imported` — after `import indicators.candle_bounds.stage`, `"sklearn" not in sys.modules`.

## Steps

- [x] Write the test file. Run in Docker: `docker compose -p cbtest run --rm ohlc_gen python -m pytest tests/unit/data_layer/test_cb_stage.py -q` → FAIL.
- [x] Implement `stage.py` (without `LiveCbStage`; that is Task 09).
- [x] Re-run → PASS. Run the whole CB set: `... python -m pytest tests/unit/data_layer -q -k cb` → PASS.
- [ ] Stage; describe; wait for confirmation. Suggested message: `feat(cb): stage entry point compute_cb_columns`. *(As executed: staged by the controller with `git add` after review; no commit — the commit waits for the user's confirmation at handover.)*
