# Task 04: Live stage — no cache change, parity on the four new columns

**Phase:** 19 — CB Overshoot Main Flow
**Depends on:** Task 02
**Produces:** `LiveCbStage.update` writes the four new columns per tf; `cb_live_parity.py` compares them
**Gate:** G5

---

## Goal

Confirm the live path produces the same overshoot values and flags as `compute_cb` on `build_wide`, tick for tick, with no change to the stage's caches.

## Context

`LiveCbStage.update` calls `tf_columns` on the current row with the cached closed bounds (`closed.cb`) — `overshoot` needs only `{tf}_cb_{side}`/`_std` from that cache and the current row's `1_high`/`1_low`. The NaN rule for an unusable tf: the stage writes `np.full(len(_tf_names(tf)), np.nan)` → the flag arrives as NaN, and `_is_bool_column` consumers treat NaN as… **check**: phase 18's final-review fix (1) made unusable tfs NaN in all columns, bools included, and the publisher skips NaN. So the flag is simply *not published* for an unusable tf (D2's "NaN → True" applies to NaN *inputs* on a usable tf, which `kernel.filters` handles). Pin both.

## Files

- Modify: `tests/unit/data_layer/test_cb_live_stage.py` (new tests)
- Modify: `scripts/cb_live_parity.py` only if its compared set is not already `expected_columns()` (it is — verify, no change expected)

## Tests (RED first)

`tests/unit/data_layer/test_cb_live_stage.py`:

- `test_update_writes_overshoot_columns` — after `update`, `ohlc[tf]` last row has the four names; z finite when the cached bound/std are finite; flag bool-valued (1.0/0.0 as float in the frame, like the siblings).
- `test_update_overshoot_nan_band_passes` — a usable tf whose cached `cb_low_std` is forced to NaN/0 → z NaN, flag True (1.0).
- `test_update_unusable_tf_overshoot_nan` — unusable tf → all four NaN (not False, not True).
- `test_update_matches_compute_cb_on_overshoot` — the existing "update == compute_cb(build_wide)" parity test re-run covers the new columns automatically through `expected_columns()`; add an explicit assertion on the four names so a future column-list regression is caught by name.

## Steps

*Deviation: `test_update_writes_overshoot_columns` / `test_update_overshoot_nan_band_passes` folded into `test_overshoot_matches_prep` (per-tf/side z + flag vs prep on the sampled minutes) and `test_overshoot_unusable_tf_is_nan`; the NaN/zero-band → True rule is pinned at kernel level.*

- [x] Write the tests. Run → FAIL (before Task 02's names land) / PASS after — if they pass immediately, that is the expected outcome of Task 02; keep them as pins.
- [x] `TRAIN_ENV=configs/oos2m_dataset.env docker compose -p cbtest run --rm -e PAIR=link_usdt ohlc_gen python3 scripts/cb_live_parity.py --minutes 600` → the per-column table has 126 rows; the four new ones per tf: bool mismatch 0, float max rel ≤ 1e-9. Record `update` timing (expect no measurable change over the 81/135 ms of TECH_DEBT §16). *(As executed: 126 rows; flags 0 mismatches; z max_rel up to 6.3e+1 — z ≈ 0 makes the relative metric meaningless; it inherits the known live-vs-prep `cb_low` drift (max rel 5.8e-5, TECH_DEBT §15); exact equality vs `compute_cb(build_wide)` is pinned by `test_update_equals_compute_cb_on_build_wide`. update mean 121 / p95 193 / max 378 ms.)*
- [ ] Stage; describe; wait for confirmation. Suggested message: `test(live): overshoot columns through LiveCbStage`.
