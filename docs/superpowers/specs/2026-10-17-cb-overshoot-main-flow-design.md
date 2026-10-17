# CB marker overshoot filter in the main flow, on the wire, and in the executor view — design

**Date:** 2026-10-17
**Base branch:** `experimental_imp_2` (main/; `cb-markers-main-flow` merged into it as `97fb76d` on 2026-10-17) — the executor side builds on `cb-overlay-visualiser` (trade_executor; uncommitted off `layer-implementation`).
**Work branches:** `cb-overshoot-main-flow` (main/, off `experimental_imp_2`); `cb-overlay-overshoot` (trade_executor, off `cb-overlay-visualiser`).
**Status:** built and merged 2026-10-17 — main/ `4e5d791` → `experimental_imp_2` `aca3ef6`; trade_executor `9acc357` → `layer-implementation` `ecebb1f`; D1–D7 as proposed. Plan: `plans/impl_2/phase-19-cb-overshoot-main-flow/`; gates: `experiment/results/cb_overshoot_main_flow_results.md`. G1b not run; G9 user-gated.
**Extends:** [2026-10-05-cb-markers-main-flow-design.md](2026-10-05-cb-markers-main-flow-design.md) (listed `cbover_*` / `cb_overshoot_*` under its Non-goals: "stay sidecars"); executor side extends `external/executor/specs/2026-10-16-cb-overlay-visualiser-design.md` §8.2.
**Related:** `notebooks/zone_profitability/run_cb_overshoot.py` (the sidecar producer this moves), `data.join_cb_overshoot`, `frontend/data_viewer._MARKER_VETO`, phase-18 plan `plans/impl_2/phase-18-cb-markers-main-flow/`.

## Goal

The fourth marker filter. Today a `cb_inzone` minute is any touch of the zone — a candle that blows straight through the bound still counts. The experiment's answer (`run_cb_overshoot.py`: "deep breaks precede a larger further move") was a sidecar: a notebook writes `df_with_cb_overshoot.pkl` for one dataset, `view_full.py` joins it, the viewer's `_MARKER_VETO` drops markers where `{tf}_cbover_{side}` holds. It exists for oos2m only, never live, never on the wire, and the executor chart draws every touch.

After this spec:

1. `indicators/candle_bounds` computes, with one implementation in prep and live, `{tf}_cb_overshoot_{side}` (the overshoot, float) and `{tf}_cb_f_overshoot_{side}` (the pass flag, bool) against **frozen** thresholds — exactly like `cb_f_extdone` / `cb_f_trend` / `cb_f_mcx`.
2. `cb_f_overshoot_{long,short}` is broadcast over MQ like the other flags.
3. main/'s viewer treats it as the fourth `cb_f_*` toggle (on by default); the sidecar join and `_MARKER_VETO` go.
4. trade_executor's pair chart gets a `filter: overshoot` toggle (on by default) masking the in-zone dots. No Rust change.

Nothing consumes the flag in trading logic (same posture as the other three).

## Decisions proposed (user to confirm)

| # | Decision | Default here |
|---|---|---|
| D1 | Threshold provenance | Freeze the six values the existing sidecar already encodes (derived below), not a refit. A refit script is provided but not run for this spec. |
| D2 | Flag semantics | `cb_f_overshoot_{side}` is a **pass** flag like its siblings: True = keep the marker. NaN overshoot → True. |
| D3 | Wire | Broadcast the two bool flags per tf (`on_change: true`), 6 names → allowlist grows 42 → 48 CB names. The float `cb_overshoot_*` is stored-only (same class as `*_std`). |
| D4 | Viewer default | `cb_f_overshoot` **on** by default (the sidecar veto was unconditional whenever the sidecar existed; this keeps today's look). |
| D5 | Executor default | `filter: overshoot` **on** by default, same reason. |
| D6 | Sidecar | `run_cb_overshoot.py` stops being a producer: its threshold fit moves to `scripts/cb_export_overshoot.py`; `data.join_cb_overshoot` and `view_full.py`'s call are removed; `_MARKER_VETO` is removed. `df_with_cb_overshoot.pkl` on the volume is left in place (not deleted; no longer read). |
| D7 | Branch order | main/: phase 18 is merged (`97fb76d`), so `cb-overshoot-main-flow` branches off `experimental_imp_2` and merges back into it; no stacking on main/. trade_executor: still stacked on the unmerged `cb-overlay-visualiser`; merge after it. |

## Non-goals

- No strategy, signal or executor decision-path change; no use of the flag in `trade_executor`'s Rust side at all (the route and `indicators` table are generic).
- No refit of bounds, ladder or class thresholds; no change to `ZONE_FRAC`, `TGT_SHRINK_PCT`.
- No per-tf/side tuning of the overshoot quantile beyond the frozen 0.75.
- `cbnc_*` / `cbx_*` markers get no overshoot flag (the sidecar never had one; a forming bound's band is not a frozen reference).
- No change to the executor's Indicators panel (lists all names verbatim; it will show 48).

## State before this spec (verified 2026-10-17)

- **Definition** (`run_cb_overshoot.py` docstring, `overshoot()`): per 1-min row,
  `long: z = (cb_low − 1_low) / cb_low_std`, `short: z = (1_high − cb_high) / cb_high_std`
  (z > 0: the 1-min extreme is past the predicted bound, in band-sd units).
  Threshold per `(tf, side)` = quantile 0.75 of z over the 2y **filtered** markers (`cb_inzone` ∧ ¬extdone-veto ∧ finite ATR), frozen, applied to the target dataset: `cbover = z > thr`.
- **Thresholds on disk**: the run's `cb_overshoot_report.json` went to a session scratchpad and is gone (`ev_line_results.md` "Run reports"). They are recoverable exactly from the sidecar `df_with_cb_overshoot.pkl` on the oos2m volume (`z` and `cbover` per row bracket each threshold to 4 decimals):

  | tf | side | thr (band sd) | share of finite rows over |
  |---|---|---|---|
  | 15 | long | 0.3477 | 12.6 % |
  | 15 | short | 0.3808 | 12.4 % |
  | 60 | long | 0.3756 | 10.0 % |
  | 60 | short | 0.3796 | 9.6 % |
  | 240 | long | 0.4693 | 7.6 % |
  | 240 | short | 0.5178 | 6.4 % |

  (bracket width ≤ 5e-4; the midpoint is frozen. Rows: 84 961, finite 81.6–84.8 k.)
- **Caveat on provenance**: the sidecar's "filtered markers" used the **oos2m-picked** extdone ladder (`run_zone_ext.extdone`) for the training-side veto, not the 2y ladder the main flow froze. A refit with the main-flow `cb_f_extdone` would move the thresholds slightly. D1 freezes the sidecar's numbers so that parity with the stored sidecar is exact; the refit script exists for when that is wanted.
- **Inputs available in both paths**: `{tf}_cb_{side}` and `{tf}_cb_{side}_std` (`closed_bounds`, broadcast to the following candle's rows), `1_high` / `1_low` (`required_columns`). Nothing new is needed from the indicator loop.
- **Viewer**: `_MARKER_VETO = {"cb_inzone_long": "cbover_long", ...}` applied in the marker loop after `_cb_marker_mask`, skip-if-absent. `_CB_MARKER_FILTERS` has three stems; `_OVERLAY_GROUPS`, `_MARKER_ONLY_FIELDS`, `_DEFAULT_OVERLAYS_OFF` list the three flags. `tests/test_cb_marker_overshoot_veto.py` pins the sidecar join + veto.
- **Executor**: `cb_overlay.js` `filterPasses` is generic over `toggles.filters` keys → reads `{tf}_cb_f_{filter}_{side}`; `renderCbControls` renders one checkbox per key; the store's name regex `^\d+_(cb_|cbnc_|extdone_)` already admits `cb_f_overshoot_*`. `GET /api/pair_indicators` is name-agnostic.
- **Live reality that motivated this**: on 2026-10-17 LINKUSDT the executor chart showed every 15 m touch (137 long / 128 short in-zone minutes over 12 h with extdone off); main/'s full view on oos2m hides the top ~12 % of them.

## Design

### Where it runs

In `kernel.filters` — the one place the pass flags are made — extended with the overshoot inputs. Same shape in prep (`compute_cb` → `tf_columns`) and live (`LiveCbStage` → `tf_columns` on the current row). No new stage, no new per-row field.

### Kernel

```python
# kernel.py
def overshoot(cb: pd.DataFrame, df: pd.DataFrame, tf: int) -> pd.DataFrame:
    """{tf}_cb_overshoot_{long,short}: how far the 1-min extreme is past the
    closed bound, in band sd. long = (cb_low − 1_low) / cb_low_std,
    short = (1_high − cb_high) / cb_high_std. NaN bound/std/extreme → NaN;
    std == 0 → NaN (never ±inf)."""

def filters(df, ext, over, tf) -> pd.DataFrame:
    # existing three, plus:
    cols[f"{tf}_cb_f_overshoot_long"]  = ~(z_long  > OVERSHOOT_THR[tf]["long"])   # NaN > thr is False → pass
    cols[f"{tf}_cb_f_overshoot_short"] = ~(z_short > OVERSHOOT_THR[tf]["short"])
```

Rules:
- The flag is a per-minute state of the row, not sticky, not applied to any marker (Global Constraint of phase 18 stands: the marker stays the raw `cb_inzone`).
- `z` is defined on every row, not only in-zone rows: a row that is not in zone has `z ≤ 0.05·span/std`-ish and passes; that is fine and matches the sidecar, which also wrote z for all rows.
- Division by a zero or NaN band → NaN z → flag True (D2). The sidecar produced ±inf there; the kernel must not.

### Frozen parameters

`params.py`:

```python
# p75 of overshoot (band sd) over the 2y filtered markers, frozen from the
# oos2m sidecar df_with_cb_overshoot.pkl (run_cb_overshoot.py, OVER_Q=0.75).
OVERSHOOT_Q: float = 0.75
OVERSHOOT_THR: dict[int, dict[str, float]] = {
    15:  {"long": 0.3477, "short": 0.3808},
    60:  {"long": 0.3756, "short": 0.3796},
    240: {"long": 0.4693, "short": 0.5178},
}
```

`scripts/cb_export_overshoot.py` (one-off, runs in the `ohlc_gen` container, mirrors `cb_export_models.py`'s role): recomputes the thresholds from `2y_az_link_usdt` + `2y_link_usdt/df_with_candle_bounds.pkl` using the **main-flow** filtered-marker definition (`cb_inzone ∧ cb_f_extdone`, 2y ladder) and prints both the refit values and the frozen ones side by side. It does not write `params.py`. Running it is G1b, optional for this spec (D1).

### Columns

Added to `_tf_names(tf)` (so prep, backtest, materialize, live and `expected_columns` all see them), per tf:

| Column | Type | Broadcast |
|---|---|---|
| `{tf}_cb_overshoot_long`, `_short` | float (band sd), NaN on warm-up | no |
| `{tf}_cb_f_overshoot_long`, `_short` | bool; `_is_bool_column` → True | yes, `on_change: true` |

Look-ahead: `cb_{side}` / `_std` are the previous closed candle's prediction broadcast to the current candle's rows (`to_rows`), and `1_high`/`1_low` are the row's own — same inputs the zone marker already uses, so the flag is known at the same instant as the marker.

### Data preparation, backtesting, materialize

No wiring change: `compute_cb` writes `_tf_names(tf)`. The materialize script (`scripts/cb_markers_materialize.py`) picks the new columns up through the same list; its parity report (`cb_markers_validate.py`) gains one row group (G4-o below). Backtest exposure is the prepared dataset, as for the other flags.

### Live session

`LiveCbStage` evaluates `tf_columns` on the current row; `overshoot` needs only the current row's `1_high`/`1_low` and the cached closed bound/std → no cache change. Warm-up/NaN rule unchanged: floats NaN, bools False… **except** the pass flags, which are True on NaN input (D2, consistent with `cb_f_trend`'s "NaN → True"). `cb_live_parity.py` adds the four columns to its compared set.

### MQ broadcast

`configs/shared_indicators_config.yaml` gains:

```yaml
  - name: cb_f_overshoot_long
    timeframes: [15, 60, 240]
    on_change: true
  - name: cb_f_overshoot_short
    timeframes: [15, 60, 240]
    on_change: true
```

`tests/test_cb_broadcast.py` `ONCHG` list grows by two; the "not broadcast" assertion adds `cb_overshoot_long`. Wire cost: a flag flips at most once a minute per (tf, side); the executor's run-folding reader (`read_indicator_series`) keeps the overlay cheap regardless.

Executor TECH_DEBT §17 (first value after start waits for the heartbeat) applies unchanged.

### Viewer (main/)

- `_CB_MARKER_FILTERS["cb_f_overshoot"] = "cb_f_overshoot"`; `_CB_MARKER_FILTERS_DEFAULT = ("cb_f_extdone", "cb_f_overshoot")`.
- `_OVERLAY_GROUPS["cb_f_overshoot"] = ["cb_f_overshoot_long", "cb_f_overshoot_short"]`; both names into `_MARKER_ONLY_FIELDS`. Not in `_DEFAULT_OVERLAYS_OFF` (on by default, D4).
- Delete `_MARKER_VETO` and its application in the marker loop. The zone **line** is not blanked by overshoot (only extdone does that; a deep break is a marker property, not a level property).
- `view_full.py`: drop `join_cb_overshoot`; `data.join_cb_overshoot` deleted; `tests/test_cb_marker_overshoot_veto.py` rewritten for the toggle (same assertions as `test_cb_marker_filter_toggles.py` has for `cb_f_trend`, plus "on by default" and "line not blanked").
- Sidecar-only datasets (no main-flow columns): overshoot no longer vetoes anything there (same behaviour change phase 18 accepted for extdone).

### Executor view (trade_executor)

Spec `2026-10-16-cb-overlay-visualiser-design.md` §8.2 gains a third filter; implementation is `static/js/cb_overlay.js` only:

- `defaultToggles().filters = { extdone: true, overshoot: true, trend: false }` — order is the control order.
- `filterPasses` unchanged (generic). Marker for `(tf, side)` at minute m is drawn only when `{tf}_cb_f_overshoot_{side}` does not sample false (absent → passes).
- Zone line untouched (only extdone blanks it).
- `cb_overlay.test.js`: `defaultToggles has overshoot on`, `buildOverlay masks in-zone dots by cb_f_overshoot and leaves the zone line` — two cases.
- `renderCbControls` renders the new checkbox from the key; label `filter: overshoot`. No `chart.js`, `pair.js`, `pair.html`, Rust or route change.
- Docs: executor spec §8.2 + L8 layer spec paragraph updated.

Until main/ broadcasts the flag, the toggle is a no-op (null passes) — same as `filter: trend` on a flat day.

## Acceptance gates

- **G1** `kernel.overshoot` on a hand-checked 6-row frame: z exact to 1e-12 for both sides; NaN std → NaN; zero std → NaN; NaN extreme → NaN.
- **G1b (optional, D1)** `cb_export_overshoot.py` runs in Docker; refit values printed against frozen; difference recorded in the results doc, no param change unless the user says so.
- **G2** `filters`: flag False iff z > thr; NaN z → True; thresholds read from `params.OVERSHOOT_THR`, pinned per cell.
- **G3** `expected_columns()` has 4 new names per tf; `_is_bool_column` True for the flags, False for the floats; existing column values unchanged (materialize diff on oos2m: every pre-existing column equal).
- **G4-o (parity vs sidecar, oos2m)** on rows where both are finite: `|cb_overshoot − sidecar z| < 1e-9` and `cb_f_overshoot == ¬cbover` with **0 mismatches** (frozen thresholds are the sidecar's, bracket ≤ 5e-4, so any mismatch is a definition bug). Rows where the sidecar is ±inf: main-flow NaN, flag True — counted and reported, not gating.
- **G5** live parity (`cb_live_parity.py`): the four columns match `compute_cb` on `build_wide` tick for tick over the parity window.
- **G6** broadcast test: config lists the two flags with `on_change`; the fake publisher receives `{tf}_cb_f_overshoot_{side}` as 1.0/0.0; the float is absent from the allowlist.
- **G7** viewer tests: toggle present only when the column exists; on by default; AND with the other filters; `_MARKER_VETO` gone (grep); line not blanked.
- **G8** executor: `node --test` green with the two new cases; Docker suite unchanged (no Rust change — run anyway, project-isolated).
- **G9 (user-gated)** live: main/ `live` on the work branch → executor `no_trade` stack → pair page: `filter: overshoot` off shows more dots than on; the Indicators panel lists 48 CB names.

## Risks

- **Threshold drift (D1).** Frozen numbers come from a training-side veto that used the oos2m ladder. If G1b shows a material difference (say > 0.02 sd), decide then; the flag's consumer is only a chart today, so the cost of being slightly off is cosmetic.
- **`cb_*_std == 0`.** The Ridge band is `ext · band_pct / 100`; zero only when the extreme is 0 — impossible for a price — but guarded anyway.
- **Wire growth.** +6 names on_change; worst case 6 flips/min. The executor's reader folds heartbeats and the SPA store folds the per-tick boundary repeat (overlay spec §4/§7 revision 2026-10-17), so no visible cost.
- **Viewer behaviour change** for sidecar-only datasets (no veto). Same class of change phase 18 already made for extdone; stated, not mitigated.
- **Branch stacking.** Only on the executor side now (`cb-overlay-visualiser` → `cb-overlay-overshoot`); main/ sits directly on `experimental_imp_2` since `97fb76d`. Review order matters on trade_executor; neither this spec nor its plan merges anything.

## Testing

main/: unit tests under `tests/unit/data_layer/` (kernel overshoot + filters, stage column list), `tests/test_cb_broadcast.py`, `tests/test_cb_marker_filter_toggles.py` (+ the rewritten overshoot test), `scripts/cb_markers_validate.py` G4-o row group, `cb_live_parity.py`. All in Docker under a separate compose project (`docker compose -p cbtest run --rm ohlc_gen python -m pytest <path> -q`).
trade_executor: `node --test crates/visualizer_server/static/js/cb_overlay.test.js`; Docker gate under an isolated project.

## Open questions for the user

1. D1 — freeze the sidecar's thresholds, or run the refit (G1b) first and freeze that?
2. D3 — broadcast only the flags, or also the float overshoot (would let the executor chart size the dot by depth later)?
3. D4/D5 — on by default on both viewers?
4. D6 — delete the sidecar join/veto outright, or keep `join_cb_overshoot` absence-safe for one release?

## Plan

To follow as `plans/impl_2/phase-19-cb-overshoot-main-flow/` (task-01 params + kernel → task-02 stage/columns → task-03 materialize + G4-o → task-04 live parity → task-05 broadcast → task-06 viewer → task-07 executor overlay → task-08 docs), after the questions above are answered.
