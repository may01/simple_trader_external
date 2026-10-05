# Task 11: Viewer — marker filter toggles

**Phase:** 18 — CB Markers Main Flow
**Layer:** frontend
**Depends on:** Task 07 (oos2m has the columns)
**Produces:** three marker-filter toggles in `frontend/data_viewer.py`

---

## Goal

The full view draws CB markers from the main-flow columns and lets the user restrict them by each stored filter. The hard-coded marker veto goes away.

## Context

`frontend/data_viewer.py`:

- `_OVERLAY_GROUPS` (line ~140): checklist group → list of tf-stripped field names.
- `_DEFAULT_OVERLAYS_OFF` (line ~254): groups unchecked on first load.
- `_ZONE_VETO` (line ~283): maps `cb_zone_short`, `cb_inzone_short` → `extdone_low` and `cb_zone_long`, `cb_inzone_long` → `extdone_high`. Applied to marker columns in `_draw_zone_markers` (line ~1069) and to zone lines (line ~1239). Skip-if-absent.
- `_MARKER_VETO` (line ~292): overshoot veto from a sidecar. Unchanged by this task.
- `_ZONE_MARKER_SOURCES` + `_draw_zone_markers` (line ~1017–1090): one tuple per marker family; `overlays` is the list of checked groups (`None` = all).

`view_full.py` joins sidecars with "never overwrite existing columns", so on a materialized dataset the main-flow `cb_*`, `cbnc_*`, `cbx_*`, `extdone_*` columns win automatically. `view_full.py` needs no change.

Stored `_extdone_*_first` columns from the old sidecar still get joined (they are not in the main frame). Nothing draws them; leave them.

## Behaviour

Three new checklist entries, shown with the other CB overlays:

| Toggle | Default | Effect when checked |
|---|---|---|
| `cb_f_extdone` | **on** | CB markers drawn only where `{tf}_cb_f_extdone_{side}` is True; `cb_zone_{side}` line blanked where it is False |
| `cb_f_trend` | off | CB markers drawn only where `{tf}_cb_f_trend_{side}` is True |
| `cb_f_mcx` | off | CB markers drawn only where `{tf}_cb_f_mcx_{side}` is True |

- "CB markers" = the `cb_inzone_{long,short}` family only. `cbnc_inzone`, `cbx_inzone`, `zp_*`, `cbatr_*`, `cb_enter_*`, `az_*` are not filtered.
- Several toggles checked → AND.
- A dataset without the flag column for a toggle → that toggle has no effect (skip-if-absent). A dataset with neither main-flow columns nor sidecars draws nothing, as today.
- `cb_inzone_*` entries are removed from `_ZONE_VETO`. The `cb_zone_*` entries are replaced by the `cb_f_extdone` toggle logic (line blanked where `cb_f_extdone_{side}` is False, only while the toggle is checked). With the toggle unchecked, zone lines and markers are unfiltered.
- `_MARKER_VETO` still applies after the toggles.
- The toggles are not drawable fields: checking one must not add a trace of its own.

## Files

- Modify: `frontend/data_viewer.py`
- Test: `tests/test_cb_marker_filter_toggles.py`
- Modify if it asserts the old veto: `tests/test_cb_marker_overshoot_veto.py`, `tests/test_phase12_task15_overlay_selection.py`

## Interface

```python
class DataViewer:   # (the class that owns _OVERLAY_GROUPS; keep its real name)
    # toggle name -> flag column stem; side appended at use: f"{tf}_{stem}_{side}"
    _CB_MARKER_FILTERS: dict[str, str] = {
        "cb_f_extdone": "cb_f_extdone",
        "cb_f_trend": "cb_f_trend",
        "cb_f_mcx": "cb_f_mcx",
    }

    def _cb_marker_mask(self, window: pd.DataFrame, tf: int, side: str,
                        overlays: list[str] | None) -> np.ndarray: ...
        # bool array, len(window): AND of the checked filters whose flag column exists; all True if none
        # overlays=None means defaults: cb_f_extdone on, the other two off
```

## Key Constraints

- Follow the file's existing patterns (class-level dict constants with a comment block, skip-if-absent). Do not restructure `_draw_zone_markers` beyond swapping the `_ZONE_VETO` lookup for `_cb_marker_mask` on the CB family.
- Read the existing tests named above before editing; where they assert the removed marker veto, update them to the toggle behaviour rather than deleting them.
- Charts at every tf (1, 5, 15, 60, 240) keep working: markers come from `{src_tf}_cb_inzone_*` columns for src_tf in 15/60/240 regardless of chart tf, as today.

## Tests (RED first)

`tests/test_cb_marker_filter_toggles.py` — build a small window frame by hand (10 rows) with `1_low`, `1_high`, `15_cb_inzone_long` and the three flag columns; call the drawing method the existing marker tests call, and inspect the produced traces.

- `test_default_applies_extdone_only` — `overlays=None`: marker points = rows where `inzone & f_extdone`.
- `test_extdone_unchecked_draws_all_inzone` — overlays list with `cb_long` but without `cb_f_extdone`: all `inzone` rows.
- `test_trend_and_mcx_and_together` — all three checked: rows where `inzone & f_extdone & f_trend & f_mcx`.
- `test_filter_column_absent_is_noop` — frame without `15_cb_f_mcx_long`, `cb_f_mcx` checked → same as unchecked.
- `test_side_specific` — `cb_f_trend` checked: long markers filtered by `cb_f_trend_long`, short by `cb_f_trend_short`.
- `test_other_families_not_filtered` — `15_cbx_inzone_long` and `15_cbnc_inzone_long` markers unchanged by any toggle.
- `test_zone_line_blanked_only_with_extdone_toggle` — `cb_zone_long` line has NaN where `cb_f_extdone_long` is False when the toggle is checked; fully drawn when unchecked.
- `test_toggles_add_no_trace` — checking the three toggles alone (no `cb_long`/`cb_short`) produces no marker trace.
- `test_defaults_off_set` — `cb_f_trend` and `cb_f_mcx` in `_DEFAULT_OVERLAYS_OFF`; `cb_f_extdone` not.
- `test_overshoot_veto_still_applies` — with `15_cbover_long` True on a row, that marker is dropped regardless of toggles.

## Steps

- [x] Read `_draw_zone_markers`, the zone-line veto site, and the three existing test files named above.
- [x] Write the test file. Run in Docker: `docker compose -p cbtest run --rm ohlc_gen python -m pytest tests/test_cb_marker_filter_toggles.py -q` → FAIL.
- [x] Implement. Re-run → PASS.
- [x] Regression: `... python -m pytest tests -q -k "phase12 or overlay or cb_marker or target_sl"` → PASS (after updating assertions that pinned the removed marker veto). *(As executed: 12 failures in `test_phase12_task01_chart_renderer.py` / `test_phase12_task14_label_markers.py`, identical on the base branch — pre-existing. Behaviour change: sidecar-only datasets (no main-flow flag columns) lose the old extdone veto on `cb_inzone` markers and `cb_zone` lines and draw unfiltered, as intended. A stale comment in `_DEFAULT_OVERLAYS_OFF` about the veto was corrected in Task 12.)*
- [ ] *(NOT RUN — user-gated.)* Visual check, user-facing: ask the user to restart `view-full` on oos2m (it mounts `main/`; the work branch is in a worktree, so say which path must be mounted or wait until merge) and look at one day at tf 15: markers with `cb_f_extdone` on vs off, then `cb_f_trend`, `cb_f_mcx`. Do not claim the chart was checked unless it was.
- [ ] Stage; describe; wait for confirmation. Suggested message: `feat(viewer): marker filter toggles for candle-bound markers`. *(As executed: staged by the controller with `git add` after review; no commit — the commit waits for the user's confirmation at handover.)*
