# Task 07: Action overlay on full_view

**Phase:** 14 — Simulation Wiring
**Depends on:** Task 05 (sim folders + actions.jsonl), Phase 12 (FullData, ChartRenderer, HistoryDashboard, `_draw_label_markers`)
**Produces:** action markers from the latest simulation drawn on the `full_view` price chart

---

## Goal

Requirement 4: actions from the latest simulation shown on the `full_view` graph. The viewer (`view_full.py` → `HistoryDashboard`) loads the newest `sim_<id>` folder's `actions.jsonl` and draws OPEN/CLOSE/STOP_LOSS markers on the price subplot, mirroring the existing `_draw_label_markers` mechanism.

---

## Context

`frontend/data_viewer.py` already has `_draw_label_markers` that places marker traces on the price subplot for each label column. Action markers follow the same pattern but are sourced from disk (the latest simulation) rather than df columns, and positioned by `timestamp` + `executed_price` (or `target_price` fallback).

`full_view` chart = `HistoryDashboard.build_window_figure`. Add a toggleable subplot/overlay so the user can show/hide simulation actions.

---

## Files

- Modify: `frontend/data_viewer.py` — `_load_latest_actions`, `_draw_action_markers`, register an "actions" overlay/subplot toggle
- Modify: `frontend/history_dashboard.py` — add "actions" to the subplot/overlay selection controls
- Add: `tests/test_phase14_action_overlay.py`

---

## Interface

- `latest_simulation_folder() -> str | None` (helpers.py) — newest `sim_<id>` dir by id, or `None`
- `FullData._load_latest_actions(self) -> list[dict]` — reads `latest_simulation_folder()/actions.jsonl`, returns parsed action dicts; `[]` if no simulation or file absent
- `_draw_action_markers(self, fig, df_window, ...) -> None` — for actions whose `timestamp` falls in the visible window, draw on the price subplot:
  - `OPEN` long → triangle-up below low (limegreen); `OPEN` short → triangle-down above high (orange)
  - `CLOSE` → "x" at `executed_price` (blue)
  - `STOP_LOSS` → "x" at `executed_price` (red)
  - `MOVE_STOP_LOSS` → small dot at `stop_loss_price` (grey) — optional, low priority
  - hovertext = `strategy_name` + `action_type` + `revenue_pct` (on closes)
- Marker y-position from `executed_price` (fallback `target_price`); x from `timestamp`

---

## Key Constraints

- Skip-if-absent: no `sim_<id>` folder / no `actions.jsonl` → chart renders unchanged, no error (mirrors label-marker skip-if-absent).
- Markers on the price subplot only — never the navigator/range row (same rule as label markers).
- Only `OPEN`/`CLOSE`/`STOP_LOSS` (and optionally `MOVE_STOP_LOSS`) are drawn — `SIGNAL_FIRED` actions are NOT plotted (too noisy; they fire even when the position rejects them). Filter by `event`.
- Reads the newest simulation by **id**, not by mtime — id ordering is the source of truth (Task 05 allocates monotonically).
- Overlay is toggleable and OFF by default so existing chart behaviour is unchanged until the user opts in.
- Timestamps in `actions.jsonl` are Unix seconds — align to the df index (which the renderer already handles for candles) before plotting.

---

## Verification

```bash
docker run --rm -v "$PWD":/code -w /code simple_trader python3 -m pytest tests/test_phase14_action_overlay.py -q
```

Test writes a fake `sim_1/actions.jsonl` with one OPEN + one CLOSE inside a known window, builds the figure with the actions overlay on, and asserts two extra marker traces appear on the price subplot at the expected x/y.

Manual: `docker compose -f docker-compose-view.yml run --rm viewer python3 view_full.py` → enable "actions" → green/blue markers sit on the candles where the latest backtest opened and closed trades.

---

## Commit

`feat: overlay latest simulation actions on the full_view chart`
