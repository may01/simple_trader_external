# Task 08: Docs sync and handover

**Phase:** 19 — CB Overshoot Main Flow
**Depends on:** Tasks 01–07
**Produces:** results doc, spec status, phase-18 cross-references, TECH_DEBT, memory; the G9 checklist for the user
**Gate:** G9 (user-gated)

---

## Files (external repo only)

- Create/finish: `docs/superpowers/experiment/results/cb_overshoot_main_flow_results.md` — gate table G1–G9 with actual numbers; G4-o verbatim lines; G1b refit vs frozen if run; marker-drop table; parity timing.
- Modify: `docs/superpowers/specs/2026-10-17-cb-overshoot-main-flow-design.md` — status → built; "Current state" → "State before this spec"; record anything that deviated.
- Modify: `docs/superpowers/specs/2026-10-05-cb-markers-main-flow-design.md` — Non-goals: `cbover_*`/`cb_overshoot_*` note → "moved into the main flow by phase 19".
- Modify: `docs/superpowers/experiment/results/extdone_zone_filter_results.md` (or wherever the overshoot experiment is written up) — one line: thresholds frozen in `params.OVERSHOOT_THR`, sidecar retired.
- Modify: `executor/TECH_DEBT.md` — §17 note (first value waits for heartbeat) now also covers the overshoot flags; new item only if something was left open (e.g. G1b not run → "thresholds frozen from sidecar with oos2m-ladder veto; refit pending").
- Modify: this plan's task files — tick boxes as executed, note deviations in italics as phase 18 did.
- Memory: update `project_cb_markers_main_flow.md` with the phase-19 branch state.

## G9 handover checklist (for the user)

- [x] *(user-gated)* Restart the live main/ container from the `cb-overshoot-main-flow` worktree (today's `cb-markers-main-flow-live-1` mounts the old worktree) → the cbov-check executor stack receives `{tf}_cb_f_overshoot_{side}`; the Indicators panel lists 48 CB names. *(2026-10-17 22:00 UTC, on the user's ask: old container stopped (kept, Exited), `cb-overshoot-main-flow-live-1` up on 8050 + trader_mq with the same keys; `indicators` table shows all 6 overshoot names, 48 distinct CB names in the last 2 min; `15_cb_f_overshoot_short` already flipped 1→0→1 within a minute. Visualizer: `cb_overlay.js` copied into `cbov-check-visualizer-1` + container restart (no image rebuild; the running image otherwise matched the worktree's static files); serves `overshoot: true`.)*
- [ ] *(user-gated)* Pair page: `filter: overshoot` off shows more dots than on (15 m first — it drops ~12 % of touches on oos2m).
- [x] Code review (`superpowers:requesting-code-review`) on the main/ branch diff; `superpowers:finishing-a-development-branch` → merge into `experimental_imp_2` on confirmation. *(User said "commit and merge" 2026-10-17: `4e5d791` → `aca3ef6`; no separate review pass.)*
- [x] trade_executor: commit `cb-overlay-visualiser` (index), then branch + commit `cb-overlay-overshoot`; merge order visualiser → overshoot. *(`7d0b06f`, `9acc357` → `layer-implementation` `57d8561`, `ecebb1f`; worktree now on `layer-implementation`; host `cargo test` state_store + visualizer_server 30 passed.)*

## Steps

- [x] Write the results doc from the task outputs (numbers verbatim, no rounding beyond what the scripts print).
- [x] Spec + cross-reference edits.
- [x] Present to the user: what was built, gate table, what is user-gated, the two commit sequences (main/, trade_executor). Wait.
