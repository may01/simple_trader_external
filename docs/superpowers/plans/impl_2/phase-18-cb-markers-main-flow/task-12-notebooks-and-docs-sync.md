# Task 12: Notebooks use the kernel; docs in sync; finish the branch

**Phase:** 18 — CB Markers Main Flow
**Layer:** docs / cleanup
**Depends on:** Tasks 01–11
**Produces:** one implementation of the CB maths; external specs and results matching the code

---

## Goal

Remove the duplicated maths from the notebook drivers, bring the external docs up to date with what was built, and hand the branch over.

## Part A — notebooks import the kernel

`notebooks/candle_bounds_nc/cbnc.py` and `notebooks/zone_profitability/run_extdone.py` currently carry their own copies of what is now in `indicators/candle_bounds/kernel.py`.

**Files:**

- Modify: `notebooks/candle_bounds_nc/cbnc.py`
- Modify: `notebooks/zone_profitability/run_extdone.py`
- Test: `tests/unit/data_layer/test_cb_notebook_parity.py`

**Changes:**

- `cbnc.py`: `FEATURES`, `TFS`, `SIDES`, `ZONE_FRAC`, `TGT_SHRINK_PCT` re-exported from `indicators.candle_bounds.params`. `closed_frame` keeps its `target` column (fitting needs it) by calling `kernel.closed_frame` and adding `out["target"] = out["d"].shift(-1)`. `_to_rows` → `kernel.to_rows`. `forming_features` → `kernel.forming_features`. `fit_side`, `SideModel`, `infer_closed`, `infer_forming`, `add_zones` stay (they work with the sklearn pipeline and are used by `run_cbnc.py`, `scripts/cb_export_models.py` and other notebook drivers).
- `run_extdone.py`: `d_of_progress` → thin wrapper over `kernel.ladder_threshold`. Its `LADDER` (oos2m-picked) and sticky logic stay: the file documents the experiment as it was run. Add one header line pointing to `indicators/candle_bounds/` as the production implementation and stating that production is per-minute with the 2y ladder.
- Notebooks add the repo root to `sys.path` the way other drivers in those folders already import repo modules; check `run_ema_slope.py` (it imports `indicators.library.classification`) and copy its approach.

**Key constraint:** `grep -rn "from cbnc import\|import cbnc\|from run_extdone import" notebooks scripts` lists every consumer. Each imported name must still exist with the same signature.

**Tests (RED first):**

- `test_cbnc_closed_frame_equals_kernel_plus_target` — on `cb_fixtures.make_wide`: `cbnc.closed_frame(df, 15, "high")` minus `target` equals `kernel.closed_frame(df, 15, "high")`; `target == d.shift(-1)`.
- `test_cbnc_forming_features_is_kernel` — frames equal.
- `test_cbnc_constants_are_params` — `cbnc.FEATURES is params.FEATURES`; `cbnc.ZONE_FRAC == params.ZONE_FRAC`.
- `test_run_extdone_d_of_progress_matches_kernel` — same output as `kernel.ladder_threshold` on a progress grid for each oos ladder.
- `test_notebook_modules_import_without_sklearn` — importing `cbnc` and `run_extdone` in the main image succeeds (sklearn stays lazily imported inside `fit_side`).

The test file inserts `notebooks/candle_bounds_nc` and `notebooks/zone_profitability` into `sys.path`. `run_extdone` must be importable without running `main()` (it already guards with `if __name__ == "__main__"`).

**As executed (2026-10-06).** Done as above, plus: `cbnc._to_rows` / `forming_features` are the kernel objects themselves (identity, not copies); `cbnc.py` adds the repo root to `sys.path` only if absent; `run_extdone.py` moved its `os.makedirs(OUT)` from import time into `main()` (importing it from a test created a root-owned `out/` in the worktree). Extra tests: `test_cbnc_to_rows_is_kernel`, `test_run_extdone_d_of_progress_delegates_to_kernel`, `test_run_extdone_import_has_no_side_effects`; the sklearn-free import test runs a fresh interpreter with `sklearn` imports blocked, cwd = repo root (the `indicators` package reads `configs/` relative to cwd). 8 tests, RED 5 failed → GREEN 8 passed.

## Part B — docs in sync (external repo)

Per the project rule, specs and task files must match the code after every improvement.

- `specs/2026-10-05-cb-markers-main-flow-design.md`: set **Status** to implemented with the merge commit *(as executed: there is no merge commit — status set to "implemented, uncommitted on branch `cb-markers-main-flow`, awaiting user review")*; correct anything that changed during implementation (thresholds agreed in Task 09, any gate that was adjusted, anything deferred). If something was deferred, add it to `external/executor/TECH_DEBT.md` as a new numbered section instead of leaving it only in the spec.
- `experiment/results/cb_markers_main_flow_results.md`: complete — G1 numbers, validate output, marker-count table, live parity numbers and agreed thresholds, G10 result or "not run".
- `experiment/results/extdone_zone_filter_results.md`: add a short dated note under §2 that the production state is per-minute (not sticky) with the 2y ladder, linking the new results doc. Do not rewrite the experiment's numbers.
- `experiment/candle_bounds_algorithm.md` §7 "Frozen parameters": add where they now live (`indicators/candle_bounds/models_link_usdt.json`, exported by `scripts/cb_export_models.py`).
- Supporting-system specs: find those that describe the affected modules and add the CB stage — `grep -rln "DataPreparer\|LiveData\|shared_indicators\|data_viewer" external/docs/superpowers/specs/supporting-systems external/docs/superpowers/specs/layers`. Update each hit that documents prep steps, `LiveData.build_candles`, the broadcast allowlist or viewer overlays. List the files changed in the task report; if a hit needs no change, say why.
- This phase's task files: tick the steps actually done; where execution diverged from a task file, edit the task file to say what was done.
- `plans/impl_2/README.md` Phase Index: add the row `| 18 | phase-18-cb-markers-main-flow/ | Candle-bound markers and filters in prep + live |`.
- Review `external/executor/TECH_DEBT.md` §15 (live vs prep data shapes): add one line with the measured G8 gap for the CB columns.

## Part C — full verification and handover

- [x] Whole suite in Docker: `docker compose -p cbtest run --rm ohlc_gen python -m pytest tests -q`. Report the exact pass/fail counts. Compare failures against the same command on `experimental_imp_2` to separate pre-existing failures from new ones; do not call the suite green if it is not. *(Run with `-e PYTHONDONTWRITEBYTECODE=1 ... -p no:cacheprovider`. Whole `tests`: collection stops on 2 errors in `tests/nn` (`optuna` missing) on both branch and base. With `--ignore=tests/nn`: branch 21 failed / 2,344 passed / 2 skipped; base 21 failed / 2,192 passed / 2 skipped; failing ids identical (9 `test_phase09_task03_trainer.py::TestRunTrainNNSearchMode`, 6 `test_phase12_task01_chart_renderer.py::TestDrawLine`, 6 `test_phase12_task14_label_markers.py`) — no new failures, suite NOT green.)*
- [x] `grep -rn "sklearn" indicators training data.py robots mq frontend` → no hits.
- [x] Confirm no file under `main/` contains docs, specs or plans from this work. *(Checked the worktree's changes and `main/`: none.)*
- [x] Check for root-owned files left in the worktree by containers (`find . -user root | head`); they block merges. If present, remove them through a container (`docker compose -p cbtest run --rm ohlc_gen rm -rf <paths>`), not with sudo. *(Junk created during Task 12 — `notebooks/zone_profitability/out/`, `__pycache__` dirs — removed through the container; final check empty.)*
- [ ] Use `superpowers:requesting-code-review` on the branch diff, then `superpowers:finishing-a-development-branch`. *(Controller's step.)*
- [ ] *(Controller's step.)* Present to the user: what was built, gate table with actual numbers (G1–G10, each marked passed / failed / not run), files changed in `main/` and in `external/`, and the open decisions below. Wait for explicit confirmation before any commit, merge or push in either repo.

## Open decisions to raise at handover

- Materialize 2y and 4y datasets now, or leave them until a consumer needs the columns (2y in particular has a history of OOM on the 15 GB host).
- tf 240 extdone covers only the last quarter of the candle under the 2y ladder (grid stopped at d = 12). Extending the grid is a separate experiment.
- Second OOS window for the ladder is still missing (open item in `extdone_zone_filter_results.md` §4).
