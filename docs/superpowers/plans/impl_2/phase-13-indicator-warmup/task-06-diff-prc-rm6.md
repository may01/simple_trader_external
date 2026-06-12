# Task 06: diff_prc Rolling Window 20 → 6

**Phase:** 13 — Indicator Warmup (continuation: indicator/attribute additions)
**Depends on:** Task 03 (sided semantics)
**Produces:** `{src}_diff_prc_rm_6*` family (window 6) replacing `{src}_diff_prc_rm_20*`
**Branch:** `diff-prc-rm6` (off `experimental_imp_2`), worktree `worktrees/diff-prc-rm6`.

## Goal

The diff_prc rolling family must use period 6. Column names derive from the
window, so all `*_diff_prc_rm_20*` columns become `*_diff_prc_rm_6*`
(rm, mean_above/below, std_above/below × close/high/low).

## Files

- `indicators/library/price_derivatives.py` — default window 20 → 6
- `indicators/registry.py` — key rename
- `configs/indicators_config.yaml` — field name / depends_on rename
- `indicators/library/targets.py` — dependency + column-ref rename
- `indicators/attributes.py` — `diff_prc_std_*` source column rename
- `frontend/data_viewer.py` — chart column lists rename
- tests referencing the old names

## Follow-up (same task)

- Recalculate the 1-day dataset (`functional_dataset.env`): delete stale
  `indicator_stats.json` (its `diff_prc_std_*` values were computed against the
  rm_20 columns), re-run prepare, verify no NaN at DATA_START and rm_6 columns
  present.

## Verification

- Unit: rm window 6 exact values; sided fields window 6; names rm_6; targets
  still compute; full suite green in Docker; recalculated dataset clean.

## Commit

`feat: diff_prc rolling family window 20 -> 6 (rm_6 columns)`
