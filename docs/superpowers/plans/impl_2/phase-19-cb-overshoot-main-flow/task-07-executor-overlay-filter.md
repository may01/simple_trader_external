# Task 07: Executor view — `filter: overshoot` toggle

**Phase:** 19 — CB Overshoot Main Flow
**Depends on:** — (independent of main/; the toggle is a no-op until the wire carries the flag)
**Produces:** `defaultToggles().filters.overshoot = true`; two `node --test` cases; spec §8.2 / L8 docs
**Gate:** G8

---

## Goal

The executor pair chart masks in-zone dots by `{tf}_cb_f_overshoot_{side}`, on by default (D5). JS only.

## Context

`cb_overlay.js`: `filterPasses(store, tf, side, tMs, filters)` iterates `Object.keys(filters)` → reads `${tf}_cb_f_${filter}_${side}`; `null` passes. `pair.js` `renderCbControls` renders one checkbox per key of `cbToggles.filters`, label `filter: ${f}`. Adding the key to `defaultToggles()` is the whole feature. The store's name regex `^\d+_(cb_|cbnc_|extdone_)` admits `cb_f_overshoot_*`.

**Branch handling.** `cb-overlay-visualiser` is uncommitted (staged) in `trade_executor/.worktrees/layer-implementation`. Do **not** create `cb-overlay-overshoot` yet (it would carry the visualiser work with it). Make this task's edits **unstaged** in the same worktree, on top of the staged visualiser files, so `git diff --cached` = visualiser, `git diff` = overshoot. At handover the user commits the index as `cb-overlay-visualiser`, then `git checkout -b cb-overlay-overshoot` and commits the rest. If the visualiser work is committed before this task starts, branch normally.

## Files

- Modify: `crates/visualizer_server/static/js/cb_overlay.js` (`defaultToggles`, its doc comment, the header comment's filter list)
- Modify: `crates/visualizer_server/static/js/cb_overlay.test.js`
- Docs (external): `executor/specs/2026-10-16-cb-overlay-visualiser-design.md` §8.2 + §8.4 control row; `executor/specs/layers/L8-interfaces.md` filter list (that file has an uncommitted hunk from the visualiser work — edit on top of it, do not revert)

## Interface

```js
// cb_overlay.js
function defaultToggles() -> { families, filters: { extdone: true, overshoot: true, trend: false }, tfs }
// filterPasses, buildOverlay, renderCbControls: unchanged
```

## Tests (RED first)

`cb_overlay.test.js`:

- `defaultToggles has overshoot on, between extdone and trend` — `deepEqual(Object.entries(defaultToggles().filters), [["extdone", true], ["overshoot", true], ["trend", false]])`.
- `buildOverlay masks in-zone dots by cb_f_overshoot by default and leaves the zone line` — store: `15_cb_inzone_long = 1`, `15_cb_zone_long = 100`, `15_cb_f_overshoot_long = 0`; defaults → `inzone_15_long` empty, `zone_15_long` has a valued point; `filters.overshoot = false` → one dot.

## Steps

- [x] Add the two tests. `node --test crates/visualizer_server/static/js/cb_overlay.test.js` → 2 FAIL. *(19 node tests pass. Edits left unstaged on top of the staged `cb-overlay-visualiser` index, per Branch handling.)*
- [x] Edit `defaultToggles` + comments. → all PASS (G8). Existing 17 tests unchanged.
- [x] Docs: §8.2 "Three toggles: `filter: extdone` (on), `filter: overshoot` (on), `filter: trend` (off) …"; §8.4 control row string; L8 filter list `(cb_f_extdone, cb_f_overshoot, cb_f_trend)`.
- [ ] Docker suite: no Rust change — not re-run in this task (run at handover if the user wants the gate: `docker compose -p cbovtest …` per the executor test-isolation note).
- [ ] Do not stage (see Branch handling). Describe; wait.
