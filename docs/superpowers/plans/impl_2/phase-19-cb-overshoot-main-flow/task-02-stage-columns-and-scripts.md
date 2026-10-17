# Task 02: Stage columns, export script, validate/parity hooks

**Phase:** 19 — CB Overshoot Main Flow
**Depends on:** Task 01
**Produces:** 4 new names per tf in `_tf_names`; `scripts/cb_export_overshoot.py`; G4-o row group in `cb_markers_validate.py`
**Gate:** G3

---

## Goal

Make every consumer of `expected_columns()` (prep, materialize, backtest, live, parity, `_empty_columns`) see the four new columns without wiring changes, and provide the optional refit script.

## Files

- Modify: `indicators/candle_bounds/stage.py` (`_tf_names`)
- Create: `scripts/cb_export_overshoot.py`
- Modify: `scripts/cb_markers_validate.py` (`gate_g4o`, called from `main`, loads `df_with_cb_overshoot.pkl` when present)
- Modify: `tests/unit/data_layer/test_cb_stage.py` (114 → 126; new names; bool/float split)
- Test: `tests/unit/data_layer/test_cb_materialize.py` (materialize == compute_cb_columns still holds with 126 columns — existing test, just re-run)

## Interface

```python
# stage.py — _tf_names(tf) order, appended after the cb_f_mcx pair:
#   {tf}_cb_overshoot_long, {tf}_cb_overshoot_short, {tf}_cb_f_overshoot_long, {tf}_cb_f_overshoot_short

# scripts/cb_export_overshoot.py
def filtered_markers(df: pd.DataFrame, cb: pd.DataFrame, tf: int, side: str) -> np.ndarray: ...
    # main-flow definition: {tf}_cb_inzone_{side} & {tf}_cb_f_extdone_{side} (2y ladder) & finite ATR
def refit_thresholds(train_ind: str, train_cb: str, q: float) -> dict[int, dict[str, float]]: ...
def main(argv=None) -> int: ...   # prints refit vs frozen per cell, exits 0; never writes params.py

# scripts/cb_markers_validate.py
def gate_g4o(rep: Report, df: pd.DataFrame, ov: pd.DataFrame | None) -> None: ...
    # per tf/side: finite-both rows |z − sidecar z| < 1e-9 (gating); flag == ~cbover on finite rows, 0 mismatches (gating);
    # sidecar ±inf rows: ours NaN & flag True — counted, printed, not gating. ov None → one "G4-o SKIP" line.
```

## Key Constraints

- `_is_bool_column` needs no change: `"_cb_f_" in name` → True for the flags; `cb_overshoot_*` has neither `inzone`, `_cb_f_`, nor `extdone_` → float.
- `cb_export_overshoot.py` runs in the `simple_trader` image (no sklearn). It computes the 2y closed bounds with `stage.compute_cb_columns` on `2y_az_link_usdt/df_with_indicators.pkl` **or** reads the stored `2y_link_usdt/df_with_candle_bounds.pkl` (`--train-cb`), whichever the user points it at; default is the stored sidecar (fast, no model run over 1M rows). The marker set uses the **main-flow** veto (`cb_f_extdone` from `compute_cb_columns` would need the whole stage; to keep the script light, recompute `kernel.extdone` with `EXTDONE_LADDER` on the 2y frame, which is exactly what `cb_f_extdone` negates).
- Validate: the G4-o group goes after G5c in `main`; the sidecar path is `{ddir}/df_with_cb_overshoot.pkl`, optional.

## Tests (RED first)

`tests/unit/data_layer/test_cb_stage.py`:

- `test_expected_columns_count` — 126 total, 42 per tf, unique.
- `test_overshoot_names_present_per_tf` — the four names per tf, in `_tf_names` order after `cb_f_mcx_short`.
- `test_bool_float_split_for_overshoot` — `_is_bool_column` False for `15_cb_overshoot_long`, True for `15_cb_f_overshoot_long`.
- `test_empty_columns_dtypes` — `_empty_columns` gives float for the z, bool for the flag.
- `test_compute_cb_writes_overshoot` — on the phase-18 fixture (`cb_fixtures`), `compute_cb` output has the four columns per tf; flag True wherever z is NaN; `flag == ~(z > thr)` elsewhere.

`tests/unit/data_layer/test_cb_materialize.py` — existing `materialize == compute_cb_columns` test re-run (now 126 columns). Add `test_materialize_adds_only_missing_overshoot` — a frame that already has the 114 phase-18 columns gets exactly the 12 new ones appended and the 114 are untouched (`assert_frame_equal` on the old block). *(If the current materialize overwrites CB columns wholesale, this test documents whichever contract holds; check `scripts/cb_markers_materialize.py` first and pin the real behaviour — do not change it in this task.)*

## Steps

*Deviation: `test_materialize_adds_only_missing_overshoot` not written — `materialize` recomputes the whole stage (drops `expected_columns()` first); the existing equals-prep / idempotent / keeps-existing tests cover it with 126 columns.*

- [x] Update `test_cb_stage.py` counts/names; add the tests above. Run → FAIL.
- [x] Add the four names to `_tf_names`. Run `test_cb_stage.py`, `test_cb_materialize.py`, `test_cb_live_stage.py`, `test_data_preparer_cb.py`, `test_simulation_data_cb.py` → PASS (G3 on fixtures).
- [x] Write `scripts/cb_export_overshoot.py` (argparse: `--train-ind`, `--train-cb`, `--q`, `--pair`; prints a table `tf side refit frozen diff`).
- [x] Add `gate_g4o` to `cb_markers_validate.py`; wire into `main` (sidecar optional). *(As executed: final row excluded like the other gates; flag flips with |z−thr| ≤ 5e-4 (`OVERSHOOT_BRACKET`) reported, not gating — 4 such rows on oos2m.)*
- [ ] Stage; describe; wait for confirmation. Suggested message: `feat(cb): overshoot columns in the stage, refit script, G4-o validation`.
