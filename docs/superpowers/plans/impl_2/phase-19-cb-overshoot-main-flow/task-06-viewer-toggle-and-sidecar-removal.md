# Task 06: Viewer — fourth `cb_f_*` toggle, sidecar join and veto removed

**Phase:** 19 — CB Overshoot Main Flow
**Depends on:** Task 02
**Produces:** `cb_f_overshoot` toggle (on by default); `data.join_cb_overshoot`, its `view_full.py` call and `DataViewer._MARKER_VETO` deleted
**Gate:** G7

---

## Goal

The full view masks `cb_inzone` markers by the main-flow flag through the same mechanism as the other three filters, on by default (D4), and stops reading the sidecar (D6).

## Files

- Modify: `frontend/data_viewer.py` — `_OVERLAY_GROUPS["cb_f_overshoot"]`, `_MARKER_ONLY_FIELDS` += 2, `_CB_MARKER_FILTERS["cb_f_overshoot"]`, `_CB_MARKER_FILTERS_DEFAULT = ("cb_f_extdone", "cb_f_overshoot")`, delete `_MARKER_VETO` and its two-line application in `_draw_zone_markers`. Not added to `_DEFAULT_OVERLAYS_OFF`.
- Modify: `data.py` — delete `join_cb_overshoot`.
- Modify: `view_full.py` — drop the import and the call (+ its comment).
- Modify: `tests/test_cb_marker_filter_toggles.py` — `_make_df` gains `15_cb_f_overshoot_{long,short}`; `test_overshoot_veto_still_applies` deleted; defaults tests updated for two defaults.
- Rewrite: `tests/test_cb_marker_overshoot_veto.py` → toggle semantics (keep the filename so the phase-18 docs' reference stays valid, update its docstring).

## Key Constraints

- Zone line: only `cb_f_extdone` blanks it (the `_draw_price_overlays` branch is unchanged). Pin.
- Skip-if-absent: a dataset without `{tf}_cb_f_overshoot_{side}` lists no toggle and masks nothing.
- `grep -n "_MARKER_VETO\|cbover\|join_cb_overshoot" frontend/ data.py view_full.py tests/` → only `run_cb_overshoot.py`'s own column names remain (notebooks are out of scope).

## Tests (RED first)

`tests/test_cb_marker_overshoot_veto.py` (rewritten):

- `test_default_masks_overshoot_and_extdone` — `overlays=None` → markers = `INZONE & EXTDONE & OVERSHOOT`.
- `test_overshoot_unchecked_draws_overshoot_rows` — explicit overlays without `cb_f_overshoot` → `INZONE & EXTDONE`.
- `test_overshoot_ands_with_trend_and_mcx`.
- `test_overshoot_column_absent_is_noop` — toggle checked, column missing → unchanged.
- `test_side_specific` — long flag does not touch short markers.
- `test_zone_line_not_blanked_by_overshoot` — `_draw_price_overlays` with `cb_f_overshoot` checked and the flag False on some rows → `cb_zone_long` series has no NaN introduced there (compare to the extdone case, which does blank).
- `test_toggle_listed_only_when_column_exists` and `test_on_by_default` — `available_overlays()` / `default_overlays()`.
- `test_sidecar_veto_removed` — `not hasattr(DataViewer, "_MARKER_VETO")`; `not hasattr(data, "join_cb_overshoot")`; a `15_cbover_long` column in the frame has no effect on markers.

`tests/test_cb_marker_filter_toggles.py`:

- `test_default_applies_extdone_only` → renamed `test_default_applies_extdone_and_overshoot`.
- `test_defaults_off_set` — `cb_f_overshoot` **not** in `_DEFAULT_OVERLAYS_OFF`.
- `test_toggles_listed_when_flag_columns_exist` — set includes `cb_f_overshoot`; `default_overlays()` includes it.

## Steps

- [x] Rewrite / update the two test files. Run → FAIL.
- [x] Viewer edits; delete `join_cb_overshoot` + `view_full.py` call.
- [x] Run both test files + `tests/test_data_viewer*.py` (whatever exists under `tests/` touching the viewer) → PASS (G7). Grep check.
- [ ] Stage; describe; wait for confirmation. Suggested message: `feat(viewer): cb_f_overshoot toggle, sidecar veto removed`.
