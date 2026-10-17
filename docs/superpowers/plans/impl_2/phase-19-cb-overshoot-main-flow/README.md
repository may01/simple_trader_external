# Phase 19 — CB Marker Overshoot Filter in the Main Flow, on the Wire, and in the Executor View

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The fourth marker filter, `cb_f_overshoot_{long,short}`, computed by the one candle-bounds kernel in prep and live against frozen thresholds, broadcast over MQ, toggled in both viewers; the oos2m-only sidecar (`run_cb_overshoot.py` → `df_with_cb_overshoot.pkl` → `join_cb_overshoot` → `_MARKER_VETO`) retired.

**Architecture:** `kernel.overshoot` (float z per side) feeds `kernel.filters` (bool pass flag). Four new columns per tf join `_tf_names(tf)`, so stage, prep, materialize, backtest, live and parity all see them with no wiring change. Allowlist +2 names. Viewer +1 toggle stem. Executor `cb_overlay.js` +1 default filter key (its logic is already generic).

**Tech Stack:** Python 3.11, pandas, numpy, pytest, Docker Compose (main/); plain JS + `node --test` (trade_executor; no Rust change).

**Spec:** `specs/2026-10-17-cb-overshoot-main-flow-design.md` — approved 2026-10-17, D1–D7 as proposed. Read it first.

**Branches:** main/ `cb-overshoot-main-flow` off `experimental_imp_2` (`97fb76d`), worktree `simple_trader/worktrees/cb-overshoot-main-flow`. trade_executor: `cb-overlay-overshoot` off `cb-overlay-visualiser` (that branch is still **uncommitted, staged** in `trade_executor/.worktrees/layer-implementation`; see Task 07 for how the two are kept apart).

---

## Global Constraints

- TFs `(15, 60, 240)`; sides `long`/`short` for the new columns.
- Definition (spec "Current state"): `z_long = (cb_low − 1_low) / cb_low_std`, `z_short = (1_high − cb_high) / cb_high_std`. Flag `cb_f_overshoot_{side} = not (z > OVERSHOOT_THR[tf][side])`.
- NaN or zero std, NaN bound, NaN extreme → z NaN → flag **True** (pass). Never ±inf.
- Frozen thresholds (D1): 15 L/S `0.3477 / 0.3808`, 60 `0.3756 / 0.3796`, 240 `0.4693 / 0.5178`. `OVERSHOOT_Q = 0.75`.
- The flag is a per-minute state of the row, never applied to the marker (phase-18 rule stands). Zone line is **not** blanked by overshoot.
- `cbnc_*` / `cbx_*` get no overshoot flag.
- Wire (D3): only the two bool flags per tf, `on_change: true`. The float stays stored-only.
- Defaults (D4/D5): on in both viewers.
- Sidecar (D6): `join_cb_overshoot`, its `view_full.py` call, `_MARKER_VETO` deleted. `run_cb_overshoot.py` keeps its analysis role but its threshold fit moves to `scripts/cb_export_overshoot.py`. `df_with_cb_overshoot.pkl` on the volume stays (not deleted, no longer read).
- Existing CB columns, indicator columns and strategies must not change value (materialize diff on oos2m: every pre-existing column equal).
- No strategy, signal, Rust or route change.
- All main/ tests and gates run in Docker under a separate compose project: `docker compose -p cbtest run --rm -e PYTHONDONTWRITEBYTECODE=1 ohlc_gen python -m pytest -p no:cacheprovider <path> -q`. Executor JS tests: `node --test crates/visualizer_server/static/js/cb_overlay.test.js` on the host.
- Do not commit, push or open a PR without the user's explicit confirmation. Stage, describe, wait.
- Docs (this plan, the spec, results) live in the external repo only.
- Volume files are root-owned: write to them only from inside a container.

## Review Focus

1. **Zero or NaN band in live.** `LiveCbStage` passes the cached closed bound/std; for an unusable tf they are NaN. Expected: float NaN, flag True (not False like the other bools). → Tasks 01, 02, 04.
2. **Sidecar ±inf rows.** The sidecar divided by a zero/NaN band and stored ±inf. Expected: main-flow NaN + flag True there; G4-o counts and reports those rows, never gates on them. → Task 03.
3. **Rows not in zone.** z is defined on every row (negative or small when price is away from the bound); the flag passes there. Nothing in the viewer or executor masks a non-marker. → Task 01.
4. **Datasets without the new columns** (prepared before this phase, or sidecar-only). Expected: viewer toggle listed only when the column exists; executor filter a no-op (null passes). → Tasks 06, 07.

---

## Docker Entry Points

No new service. Existing services gain behaviour:

```bash
# Prep — writes df_with_indicators.pkl including the 4 new columns per tf
TRAIN_ENV=configs/oos2m_dataset.env docker compose run --rm ohlc_gen

# Add the new columns to the already-materialized oos2m in place (idempotent for the old ones)
TRAIN_ENV=configs/oos2m_dataset.env docker compose -p cbtest run --rm ohlc_gen \
    python3 scripts/cb_markers_materialize.py

# Parity vs the stored sidecars (G4-o row group added)
TRAIN_ENV=configs/oos2m_dataset.env docker compose -p cbtest run --rm ohlc_gen \
    python3 scripts/cb_markers_validate.py

# Optional refit of the thresholds, prints refit vs frozen, writes nothing (G1b)
docker compose -p cbtest run --rm ohlc_gen python3 scripts/cb_export_overshoot.py

# Live parity replay (G5)
TRAIN_ENV=configs/oos2m_dataset.env docker compose -p cbtest run --rm -e PAIR=link_usdt ohlc_gen \
    python3 scripts/cb_live_parity.py --minutes 600

# Unit tests
docker compose -p cbtest run --rm -e PYTHONDONTWRITEBYTECODE=1 ohlc_gen \
    python -m pytest -p no:cacheprovider tests/unit/data_layer/test_cb_kernel_extdone.py tests/unit/data_layer/test_cb_stage.py tests/test_cb_broadcast.py tests/test_cb_marker_filter_toggles.py -q
```

Verified: [x] `docker compose -p cbtest run --rm ohlc_gen python -c "import indicators.candle_bounds.stage"` succeeds on the work branch (211 CB tests + 215 regression tests green, 2026-10-17).

---

## Layers

### Layer 4 — Indicators (kernel, params, stage columns)

**Interface produced (consumed by stage, materialize, live):**

```python
# indicators/candle_bounds/params.py
OVERSHOOT_Q: float
OVERSHOOT_THR: dict[int, dict[str, float]]          # tf -> {"long": thr, "short": thr}

# indicators/candle_bounds/kernel.py
def overshoot(cb: pd.DataFrame, df: pd.DataFrame, tf: int) -> pd.DataFrame: ...
    # columns {tf}_cb_overshoot_long, {tf}_cb_overshoot_short (float, band sd); index = df.index
def filters(df: pd.DataFrame, ext: pd.DataFrame, over: pd.DataFrame, tf: int) -> pd.DataFrame: ...
    # existing six bools + {tf}_cb_f_overshoot_long, {tf}_cb_f_overshoot_short
```

`_tf_names(tf)` grows by 4 (38 → 42 per tf; `expected_columns()` 114 → 126). `_is_bool_column` already returns True for `_cb_f_` names and False for `cb_overshoot_*`.

**Integration test → Layer 3 (RED first):** `compute_cb` on the phase-18 fixture frame returns the 4 new columns per tf with the right dtypes, and `materialize` on a small prepared frame equals `compute_cb_columns` (Task 02).

Tasks: 01 (params + kernel), 02 (stage columns + script hooks).

### Layer 3 — Test data prep / materialize

No wiring change. **Integration test (RED first):** `cb_markers_validate.py` G4-o row group fails before materialize, passes after (Task 03).

### Live data layer

No cache change. **Integration test:** `cb_live_parity.py` compares the four new columns tick for tick (Task 04).

### MQ broadcast

Allowlist +2 `on_change` entries; `tests/test_cb_broadcast.py` pins them (Task 05).

### Frontend (main/)

Fourth `cb_f_*` toggle, sidecar join + veto removed (Task 06).

### Executor view (trade_executor)

`defaultToggles().filters` gains `overshoot: true`; two `node --test` cases; docs (Task 07).

### Docs

Spec status, results doc, phase-18 non-goals note, TECH_DEBT, memory (Task 08).

---

## Task Index and Execution Order

| Task | File | Layer | Depends on | Gates |
|---|---|---|---|---|
| 01 | `task-01-params-kernel-overshoot.md` | 4 | — | G1, G2 |
| 02 | `task-02-stage-columns-and-scripts.md` | 4 | 01 | G3 |
| 03 | `task-03-materialize-and-g4o.md` | 3 | 02 | G3 (oos2m), G4-o, G1b (optional) |
| 04 | `task-04-live-parity.md` | live | 02 | G5 |
| 05 | `task-05-mq-broadcast.md` | MQ | 02 | G6 |
| 06 | `task-06-viewer-toggle-and-sidecar-removal.md` | frontend | 02 | G7 |
| 07 | `task-07-executor-overlay-filter.md` | executor | — (independent of main/) | G8 |
| 08 | `task-08-docs-and-handover.md` | docs | all | G9 handover |

Tasks 03–06 are independent of each other once 02 is green. Task 07 is independent of main/ entirely.

## Requirements Covered

| Spec section | Task |
|---|---|
| Kernel `overshoot`, `filters` extension, frozen parameters | 01 |
| Columns in `_tf_names`, `cb_export_overshoot.py`, validate/parity hooks | 02 |
| Data preparation / materialize, G4-o | 03 |
| Live session, G5 | 04 |
| MQ broadcast, G6 | 05 |
| Viewer, D4, D6, G7 | 06 |
| Executor view, D5, G8 | 07 |
| Docs, G9 handover | 08 |
