# Task 06: Data-prep wiring

**Phase:** 18 — CB Markers Main Flow
**Layer:** 3 — Test data prep
**Depends on:** Task 05 (`compute_cb_columns`, `expected_columns`)
**Produces:** `df_with_indicators.pkl` containing the CB columns; `DataPreparer._compute_cb_stage`
**Gate:** G7 (chunked == single-pass)

---

## Goal

`ohlc_gen` writes the CB columns into the prepared dataset, in both the single-pass and the chunked path, with identical values.

## Context

`training/data_preparer.py`:

- `prepare()` (line ~295): steps 1–10. Step 6 trims warm-up rows, step 7 computes profit labels, step 9 saves.
- `prepare_chunked()` → `_merge_parts()` (line ~578): concatenates the final parts into `full`, computes labels, saves.

The CB stage goes **after the trim / after the concat, before the labels** in both paths. Running it on the same (trimmed, full) frame in both paths is what makes the outputs equal. Consequence, accepted in the spec: the first ~20 closed candles of each tf at the start of a dataset have NaN bounds.

The stage is one vectorized call over the whole frame. It is not part of `_run_indicator_pass` and not in the fork pool.

## Files

- Modify: `training/data_preparer.py` — add `_compute_cb_stage`, call it in `prepare()` and `_merge_parts()`
- Test: `tests/unit/data_layer/test_data_preparer_cb.py`

## Interface

```python
class DataPreparer:
    def _compute_cb_stage(self, wide_df: pd.DataFrame) -> pd.DataFrame: ...
        # Returns wide_df with the CB columns appended (one pd.concat(axis=1); do not insert column by column).
        # compute_cb_columns(wide_df) is None  -> returns wide_df unchanged (no model for the pair).
        # Existing columns named like expected_columns() are dropped first (rerun safety).
```

Call sites:

```python
# prepare(): between step 6 (trim) and step 7 (labels)
wide_df = self._compute_cb_stage(wide_df)

# _merge_parts(): right after  full = pd.concat(frames)
full = self._compute_cb_stage(full)
```

## Key Constraints

- A `ValueError` from the stage (missing input column) propagates and fails the prep. Do not catch it.
- No change to `BASE_GROUPS`, `CLASS_GROUPS`, `CLASS_TFS`, part-file contents, or resume behaviour. Part files never contain CB columns.
- Every pre-existing column of the output must be bit-identical to the output before this task.
- Peak memory: the stage reads ~40 columns and adds 114. Use a single concat; do not copy `wide_df` beyond that.

## Integration test → Layer 4 (RED first, in Docker)

`tests/unit/data_layer/test_data_preparer_cb.py`. Read `tests/unit/data_layer/test_data_preparer.py` and `test_data_preparer_chunked.py` first and reuse their fixtures for a small raw dataset and env. Model availability: monkeypatch `indicators.candle_bounds.stage.load_models` to return `cb_fixtures.make_models()` so the test does not depend on `PAIR`.

- `test_prepare_writes_cb_columns` — after `prepare()`, the saved frame has every name in `expected_columns()`.
- `test_prepare_cb_dtypes` — `15_cb_inzone_long`, `15_extdone_high`, `15_cb_f_trend_long` are bool; `15_cb_high` float64.
- `test_prepare_existing_columns_unchanged` — run `prepare()` once with `load_models` patched to return `None` and once with models; all columns of the first frame equal the same columns of the second (`assert_frame_equal`).
- `test_prepare_no_model_no_cb_columns` — **Review Focus 3.** `load_models` → `None`: prep succeeds, no column from `expected_columns()` present.
- `test_prepare_missing_input_fails` — monkeypatch `required_columns` to include `"15_does_not_exist"` → `prepare()` raises `ValueError` mentioning it.
- `test_chunked_equals_single_pass_cb` — G7. Same raw data through `prepare()` and `prepare_chunked()` (force chunking the way `test_data_preparer_chunked.py` does); `assert_frame_equal(single[expected_columns()], chunked[expected_columns()])`, `check_exact=False, rtol=1e-12`.
- `test_rerun_idempotent` — call `_compute_cb_stage` twice on the same frame → no duplicate column names, second result equals the first.

## Steps

- [x] Write the test file. Run in Docker: `docker compose -p cbtest run --rm ohlc_gen python -m pytest tests/unit/data_layer/test_data_preparer_cb.py -q` → FAIL (`_compute_cb_stage` missing / columns absent).
- [x] Implement `_compute_cb_stage` and the two call sites. *(As executed: existing prep tests on mock frames without CB inputs hit the new `ValueError` path, so `test_data_preparer.py` and `test_data_preparer_chunked.py` got an autouse `_no_cb_models` fixture (monkeypatches `load_models` → None); no assertion changed.)*
- [x] Re-run → PASS.
- [x] Regression: `... python -m pytest tests/unit/data_layer tests/test_phase09_task02_data_preparer.py tests/test_parallel_indicator_pass.py -q` → PASS. *(As executed: PASS except 5 order-dependent failures (`PicklingError` on `_pool_compute_chunk`), identical on the base branch — pre-existing. G7 chunked == single-pass passed on synthetic inputs only: 114 cols × 5,760 rows, max diff 0.0.)*
- [ ] Stage; describe; wait for confirmation. Suggested message: `feat(prep): compute candle-bound columns in data preparation`. *(As executed: staged by the controller with `git add` after review; no commit — the commit waits for the user's confirmation at handover.)*
