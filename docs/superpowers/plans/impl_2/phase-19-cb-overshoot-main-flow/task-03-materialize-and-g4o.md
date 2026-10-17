# Task 03: Materialize oos2m and run G4-o (+ optional G1b)

**Phase:** 19 — CB Overshoot Main Flow
**Depends on:** Task 02
**Produces:** oos2m `df_with_indicators.pkl` with 126 CB columns; validate report with the G4-o group; optional refit numbers
**Gates:** G3 (oos2m), G4-o, G1b (optional, D1)

---

## Goal

Put the four new columns per tf on the materialized oos2m dataset and prove, against the stored sidecar, that the kernel reproduces the experiment's z and veto exactly.

## Context

Phase 18 materialized oos2m in place (`df_with_indicators.pkl`, backup `.precb_bak`, 872 columns). `scripts/cb_markers_materialize.py` recomputes `compute_cb_columns` and appends the stage's columns; read the script before running to confirm how it treats columns that already exist (replace vs skip) — the pre-existing 872 must be byte-equal afterwards (G3).

The sidecar `df_with_cb_overshoot.pkl` (Oct 3) has `{tf}_cb_overshoot_{side}` (z, may be ±inf) and `{tf}_cbover_{side}` (bool). Frozen thresholds are the sidecar's own to ≤ 5e-4, so on finite rows `cb_f_overshoot == ~cbover` must hold with **0** mismatches.

## Files

- Run: `scripts/cb_markers_materialize.py`, `scripts/cb_markers_validate.py` (Docker, `TRAIN_ENV=configs/oos2m_dataset.env`)
- Optional run: `scripts/cb_export_overshoot.py`
- Write: results doc `experiment/results/cb_overshoot_main_flow_results.md` (external) — gate table + verbatim G4-o lines

## Steps

- [x] Before: in Docker, snapshot the column list and a hash of the existing 872 columns (small python one-liner inside the container; keep the output in the results doc).
- [x] Run the validate script **before** materialize → G4-o group reports the new columns missing (RED on the real dataset).
- [x] `TRAIN_ENV=configs/oos2m_dataset.env docker compose -p cbtest run --rm ohlc_gen python3 scripts/cb_markers_materialize.py` → 872 → 884 columns. *(872 → 884 columns, 551,721,206 bytes; backup `.precb_bak` kept.)*
- [x] After: the 872 old columns equal the before snapshot (G3 on oos2m). A second materialize is idempotent.
- [x] Run validate → exit 0; G4-o lines: per tf/side, finite-both rows, max |Δz|, flag mismatches 0, count of sidecar ±inf rows (ours NaN, flag True). Existing G2–G5c unchanged. *(As executed: 249 → 261 PASS, 0 FAIL, 1 WARN (G4 shrink, pre-existing); max |Δz| ≤ 3.1e-13; 0 flag mismatches outside the bracket, 4 inside (z within 2e-5 of thr); sidecar ±inf rows: 0.)*
- [ ] Optional G1b: `docker compose -p cbtest run --rm ohlc_gen python3 scripts/cb_export_overshoot.py` → record refit vs frozen in the results doc. No param change.
- [x] Marker table: share of `cb_inzone` minutes dropped by `cb_f_overshoot` per tf/side on oos2m (expect ~6–13 %, cf. spec table).
- [ ] Stage nothing in main/ (volume write only); results doc in external. Describe; wait.
