# Task 08: Backtest reads the CB columns

**Phase:** 18 — CB Markers Main Flow
**Layer:** 5 — Backtesting
**Depends on:** Task 06
**Produces:** a test pinning that `SimulationData` / `WideDataPoint` expose the columns
**Gate:** G9

---

## Goal

Prove, with no production code change, that a backtest step can read every CB column from a prepared dataset.

## Context

`data.SimulationData` (line ~700) loads `df_with_indicators.pkl` once and yields `WideDataPoint`. `WideDataPoint.get(col, tf, shift=0)` (line ~128) returns `float(row[f"{tf}_{col}"])` for `shift=0`; for `shift=N` it returns the value on the Nth-last row with `{tf}_is_closed == True` and index ≤ ts — the current row counts when it is itself a closing row (so on a closing minute `shift=1` is the current row, not the previous candle). Booleans come back as `1.0` / `0.0`.

No sidecar join is added to `SimulationData`. If this task seems to need a production change, stop: something upstream is wrong.

## Files

- Test: `tests/unit/data_layer/test_simulation_data_cb.py`

## Tests (RED before Task 06 is merged into the branch, GREEN after)

Read `tests/unit/data_layer/test_simulation_data.py` and reuse its way of pointing `SimulationData` at a temp dataset. Build the dataset with `DataPreparer.prepare()` as in Task 06 (models monkeypatched).

- `test_simulation_point_exposes_all_cb_columns` — step to a row past warm-up; for every name in `expected_columns()` split into `(tf, col)`, `point.get(col, tf)` does not raise and returns a float.
- `test_bool_columns_read_as_zero_or_one` — `point.get("cb_inzone_long", 15)` ∈ {0.0, 1.0} on every step of a 200-step walk; same for `extdone_high`, `cb_f_trend_long`, `cb_f_mcx_short`, `cbx_inzone_long`.
- `test_values_match_frame` — at 20 sampled steps, `point.get("cb_zone_long", 60)` equals the frame's `60_cb_zone_long` at `point.timestamp`.
- `test_marker_filter_combination_is_computable` — at each step compute `inzone and f_extdone and f_trend` from three `get` calls; assert the count over the walk equals the same expression evaluated on the frame columns. (Shows a consumer can combine them; no strategy is added.)
- `test_shift_reads_previous_closed_row` — `point.get("cb_high", 15, shift=1)` equals `15_cb_high` on the last closed tf-15 row with index ≤ ts (as implemented: the Nth-last closed row, current row included when closed; the test walks 40 steps, mid-candle and boundary, shift 1 and 2).

## Steps

- [x] Write the test file. Run in Docker: `docker compose -p cbtest run --rm ohlc_gen python -m pytest tests/unit/data_layer/test_simulation_data_cb.py -q` → PASS if Task 06 is in the branch (RED otherwise; this is the Layer 5 integration test).
- [x] If any test fails with Task 06 present, do not edit `data.py`; report what `get` returned. *(No failure; `data.py` not edited by this task. RED was shown with `model=None`.)*
- [ ] Smoke on the real dataset (after Task 07 materialized oos2m): `TRAIN_ENV=configs/oos2m_dataset.env docker compose -p cbtest run --rm simulate`. Expected: completes as before; CB columns are present but unused by the existing strategies, so the report is unchanged against a run on the `.precb_bak` frame. State in the task report whether the two reports were actually compared. *(NOT RUN: `simulate` writes training state / report into the dataset volume. Reports were not compared.)*
- [ ] Stage; describe; wait for confirmation. Suggested message: `test(backtest): candle-bound columns readable through WideDataPoint`. *(As executed: staged by the controller with `git add` after review; no commit — the commit waits for the user's confirmation at handover.)*
