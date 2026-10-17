# CB marker overshoot filter in the main flow — gate report (phase 19)

**Run date:** 2026-10-17
**Code:** main/ `cb-overshoot-main-flow` commit `4e5d791`, merged into `experimental_imp_2` as `aca3ef6` (2026-10-17). trade_executor: `cb-overlay-visualiser` `7d0b06f` and `cb-overlay-overshoot` `9acc357`, merged into `layer-implementation` as `57d8561` / `ecebb1f`. Nothing pushed.
**Spec:** `specs/2026-10-17-cb-overshoot-main-flow-design.md` (D1–D7 as proposed). **Plan:** `plans/impl_2/phase-19-cb-overshoot-main-flow/`.

## Gate summary

| Gate | Status | Numbers / note |
|---|---|---|
| G1 `kernel.overshoot` | passed | hand frames: z exact to 1e-12 both sides; NaN std / 0 std / negative std / NaN bound / NaN extreme → NaN, never ±inf, no warning (`test_cb_kernel_extdone.py`, 11 new tests) |
| G1b refit vs frozen | **not run** | `scripts/cb_export_overshoot.py` written (main-flow veto, 2y ladder); not executed — 2y frame (382 MB pickle) on a host with ~3 GB free; D1 freezes the sidecar's numbers regardless |
| G2 `filters` flag | passed | False iff z > thr, z == thr passes, NaN passes; thresholds read from `params.OVERSHOOT_THR` at call time; frozen values pinned by test |
| G3 columns | passed | `expected_columns()` 114 → 126 (42 per tf); `_is_bool_column` float for `cb_overshoot_*`, bool for `cb_f_overshoot_*`; oos2m materialize: all 872 pre-existing columns hash-identical before/after (per-column md5 of `hash_pandas_object`), 12 added, 872 → 884, 551,721,206 bytes, backup `.precb_bak` kept |
| G4-o parity vs sidecar (oos2m) | passed | per tf/side on finite rows minus the final row: max \|Δz\| 3.14e-13 / 2.56e-13 / 5.26e-14 / 6.28e-14 / 4.00e-14 / 4.62e-14; flag ≠ ¬cbover with \|z−thr\| > 5e-4: **0**; in-bracket flips 2 / 1 / 0 / 0 / 1 / 0 (z within 2e-5 of thr); sidecar ±inf rows 0; ours-finite/sidecar-NaN exactly one warm-up candle per tf (15 / 60 / 240 rows) |
| G5 live parity | passed (flags) / inherited drift (z) | `cb_live_parity.py --minutes 600`: 126 rows; `cb_f_overshoot_*` bool mismatch 0.0000 at every tf; z float max_rel 6.3e+1 / 5.3e-1 / 1.8e-2 / 6.6e-2 / 8.5e-4 / 1.3e-2 — z ≈ 0 makes the relative metric meaningless and the absolute difference inherits the known live-vs-prep `cb_low` drift (max rel 5.8e-5, TECH_DEBT §15). Exact equality live == `compute_cb(build_wide)` pinned by `test_update_equals_compute_cb_on_build_wide` + `test_overshoot_matches_prep`. `update` mean 121.3 / p95 192.9 / max 378.1 ms (phase 18: 81 / 135 / 249; same machine under the live stack + validate run) |
| G6 broadcast | passed | allowlist 16 CB names (6 plain + 10 on_change) → 48 wire names; `cb_overshoot_*` absent; flip 1.0 → 0.0 published inside the 30 s interval (`test_cb_broadcast.py`, 2 new tests) |
| G7 viewer | passed | `cb_f_overshoot` toggle listed only when the column exists, on by default, ANDs with the other three, marker-only (zone line blanked by extdone only), `_MARKER_VETO` / `join_cb_overshoot` gone (`test_cb_marker_overshoot_veto.py` rewritten, 10 tests; `test_cb_marker_filter_toggles.py` updated) |
| G8 executor JS | passed | `node --test cb_overlay.test.js`: 19/19 (2 new). Docker suite not re-run (no Rust change) |
| G9 live dry run | wire part **passed** 2026-10-17 22:00 UTC; pair-page visual check pending (user) | live restarted from the work branch: 48 distinct CB names in `indicators`, 6 overshoot flags arriving, `15_cb_f_overshoot_short` flipped 1→0→1 live; visualizer serves the new `cb_overlay.js` (file copied + container restart, no rebuild) |

**Test runs (Docker, `-p cbtest`):** CB suite 211 passed; regression (robot, 4 viewer/dashboard suites, data_preparer, chunked, materialize) 215 passed.

## Thresholds (frozen, D1)

| tf | long | short |
|---|---|---|
| 15 | 0.3477 | 0.3808 |
| 60 | 0.3756 | 0.3796 |
| 240 | 0.4693 | 0.5178 |

In-bracket flips on oos2m (sidecar dropped, ours kept): 15 long z = 0.34768 (×2), 15 short z = 0.38078, 240 long z = 0.46926. The sidecar's true thresholds therefore lie just below the frozen midpoints; cosmetic, left as frozen.

## G4-o verbatim

```
G4-o PASS 15_cb_overshoot_long max_abs vs sidecar z: 3.14e-13 (n=84750)
G4-o PASS 15_cb_f_overshoot_long == ~15_cbover_long on finite rows (|z-thr| > 0.0005): 0; in-bracket flips 2 z=[0.34768, 0.34768] thr=0.3477 (dropped ours/sidecar=10703/10705)
G4-o PASS 15_cb_overshoot_short max_abs vs sidecar z: 2.56e-13 (n=84750)
G4-o PASS 15_cb_f_overshoot_short == ~15_cbover_short on finite rows (|z-thr| > 0.0005): 0; in-bracket flips 1 z=[0.38078] thr=0.3808 (dropped ours/sidecar=10467/10468)
G4-o PASS 60_cb_overshoot_long max_abs vs sidecar z: 5.26e-14 (n=84120)
G4-o PASS 60_cb_f_overshoot_long == ~60_cbover_long on finite rows (|z-thr| > 0.0005): 0; in-bracket flips 0 z=[] thr=0.3756 (dropped ours/sidecar=8448/8448)
G4-o PASS 60_cb_overshoot_short max_abs vs sidecar z: 6.28e-14 (n=84120)
G4-o PASS 60_cb_f_overshoot_short == ~60_cbover_short on finite rows (|z-thr| > 0.0005): 0; in-bracket flips 0 z=[] thr=0.3796 (dropped ours/sidecar=8096/8096)
G4-o PASS 240_cb_overshoot_long max_abs vs sidecar z: 4.00e-14 (n=81600)
G4-o PASS 240_cb_f_overshoot_long == ~240_cbover_long on finite rows (|z-thr| > 0.0005): 0; in-bracket flips 1 z=[0.46926] thr=0.4693 (dropped ours/sidecar=6182/6183)
G4-o PASS 240_cb_overshoot_short max_abs vs sidecar z: 4.62e-14 (n=81600)
G4-o PASS 240_cb_f_overshoot_short == ~240_cbover_short on finite rows (|z-thr| > 0.0005): 0; in-bracket flips 0 z=[] thr=0.5178 (dropped ours/sidecar=5186/5186)
[validate] all gates PASS
```

Before materialize the same group reported `column absent` ×6 (RED on the real dataset); G2–G5c lines unchanged from phase 18 (`cb_markers_validate.py` 261 PASS, 0 FAIL, 1 pre-existing WARN on the hybrid-shrink sidecar).

## Marker counts (minutes, oos2m, after materialize)

| tf | dir | cb_inzone | ∧ cb_f_extdone | ∧ cb_f_trend | ∧ cb_f_mcx | ∧ cb_f_overshoot | cbx_inzone | extdone share |
|---|---|---|---|---|---|---|---|---|
| 15 | long | 20936 | 10056 (48 %) | 11347 (54 %) | 834 (4 %) | 10233 (49 %) | 14258 | extdone_high 22.3 % |
| 15 | short | 18673 | 8134 (44 %) | 11004 (59 %) | 1173 (6 %) | 8205 (44 %) | 11708 | extdone_low 21.7 % |
| 60 | long | 17291 | 10587 (61 %) | 8520 (49 %) | 739 (4 %) | 8843 (51 %) | 12314 | extdone_high 14.2 % |
| 60 | short | 14894 | 7178 (48 %) | 8741 (59 %) | 939 (6 %) | 6798 (46 %) | 10139 | extdone_low 15.0 % |
| 240 | long | 14352 | 9474 (66 %) | 5778 (40 %) | 793 (6 %) | 8140 (57 %) | 10374 | extdone_high 11.7 % |
| 240 | short | 10663 | 6553 (61 %) | 6791 (64 %) | 62 (1 %) | 5477 (51 %) | 7024 | extdone_low 11.3 % |

`cb_f_overshoot` alone keeps ~44–57 % of in-zone minutes: the frozen p75 was fitted on *filtered* markers (in zone ∧ not extdone), and overshoot is strongly correlated with the extdone state, so on the raw marker set it cuts about half rather than the spec table's 6–13 % "share of finite rows".

## Deviations from the plan

- Task 02: `test_materialize_adds_only_missing_overshoot` not written — `cb_markers_materialize.materialize` drops every `expected_columns()` column and recomputes the whole stage; the existing `test_materialize_equals_prep` / `_idempotent` / `_keeps_existing_columns` cover that contract with 126 columns.
- Task 04: `test_update_overshoot_nan_band_passes` not written at stage level — the NaN/zero band → flag True rule is pinned in the kernel tests; live adds `test_overshoot_matches_prep` and `test_overshoot_unusable_tf_is_nan`.
- G4-o: the final row is excluded (phase-18 edge rule; the stored sidecar's last row carries a bound ours does not reproduce — max |Δz| there 0.19–1.03), and flag flips with |z−thr| ≤ 5e-4 are reported rather than gating (`OVERSHOOT_BRACKET`).

## Handover (G9, user-gated)

1. Restart the live main/ container from the `cb-overshoot-main-flow` worktree (`cb-markers-main-flow-live-1` mounts the old one) → executor stack receives `{tf}_cb_f_overshoot_{side}`; Indicators panel lists 48 CB names.
2. Pair page: `filter: overshoot` off shows more dots than on.
3. Commit sequence — main/: review the branch diff, commit, merge into `experimental_imp_2`. trade_executor: commit the staged index as `cb-overlay-visualiser`, then `git checkout -b cb-overlay-overshoot` and commit the unstaged JS edits; merge visualiser → overshoot.
