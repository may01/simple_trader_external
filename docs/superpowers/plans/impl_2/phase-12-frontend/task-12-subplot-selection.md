# Task 12: Oscillator-subplot selection checkboxes — shared across all TFs

**Phase:** 12 — Frontend
**Depends on:** Task 06 (timeframe selection), Task 08 (oscillator charts)
**Produces:** subplot on/off checkboxes in `HistoryDashboard`; one selection drives every timeframe's figure

---

## Goal

Let the user choose which additional plots (rsi, cci, adx, macd variants, derivative groups) render under price/volume. The selection is a single control applied to all selected timeframes.

---

## Context

Every oscillator/derivative indicator routes to a named subplot via `_indicator_subplot` in `data_viewer.py`. Default window figures draw the full `_OSCILLATORS` + derivative-group set. Hiding a subplot means dropping all indicators routed to it before figure construction — the subplot row is then never created and vertical space redistributes automatically.

---

## Files

- Modify: `frontend/data_viewer.py` — `available_subplots()`, `build_window_figure(subplots=...)`
- Modify: `frontend/history_dashboard.py` — `subplots` Checklist + callback wiring
- Add: `tests/test_phase12_task12_subplot_selection.py`

---

## Interface

**`DataViewer`**

- `available_subplots() -> list[str]` — ordered, deduped subplot names from the default indicator set, kept only when the backing column exists for at least one available TF; TF-independent so one control serves all TFs
- `build_window_figure(..., subplots: list[str] | None = None)` — `None` keeps everything (back-compat); a list keeps only indicators routed to those subplots; `[]` leaves price + volume only. Price-axis indicators and overlays are never filtered.

**`HistoryDashboard`**

- `dcc.Checklist(id="subplots")` — options/labels = `available_subplots()`, all checked by default
- `_render_groups(start_date, days, tfs, subplots)` — passes the same selection to every TF's `build_window_figure`

---

## Key Constraints

- Selection applies to all timeframes — no per-TF subplot state
- Price, its overlays (EMA/BB/SAR/tgt/sl), and volume always render
- Unchecking everything still renders the price/volume figure per TF
- Subplot order stays the default indicator order regardless of click order

---

## Verification

```bash
docker run --rm -v "$PWD":/code -w /code simple_trader \
  python3 -m pytest tests/test_phase12_task12_subplot_selection.py -q
```

Manual: uncheck `cci` — the CCI row disappears from every TF's chart; recheck — it returns in its default position.

---

## Commit

`feat: checkbox selection of oscillator subplots, shared across all TFs`
