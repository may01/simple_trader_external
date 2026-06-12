# Task 06: Timeframe selection — one chart group per selected TF

**Phase:** 12 — Frontend  
**Depends on:** Task 05 (HistoryDashboard)  
**Produces:** timeframe multi-select in `HistoryDashboard`; per-TF chart groups

---

## Goal

Add a timeframe multi-select to `HistoryDashboard`. For every selected timeframe the page shows a separate chart group (its own `dcc.Graph`) built from that timeframe's columns of the wide DataFrame. Deselecting a timeframe removes its group.

---

## Context

The wide df carries all configured timeframes as `{tf}_{col}` columns (e.g. `15_close`, `240_rsi_14`). Task 05 renders only the primary `tf`. Researchers compare behaviour across timeframes — this task turns the single-TF skeleton into the multi-TF page that Tasks 07–09 attach indicator charts to.

---

## Files

- Modify: `frontend/history_dashboard.py`
- Modify: `frontend/data_viewer.py` — per-TF figure building

---

## Interface

**`HistoryDashboard`**

Layout additions:
- `dcc.Checklist(id="timeframes")` — options discovered from the wide df: every `tf` for which a `{tf}_close` column exists, sorted ascending; labels human-readable (`1m, 5m, 15m, 1h, 4h, 1d` for 1/5/15/60/240/1440); initial value `[self.tf]`
- `html.Div(id="chart-groups")` — container; callback returns one `dcc.Graph` child per selected TF, id `{"type": "tf-chart", "tf": tf}`

Callback: `(start-date.date, days.value, timeframes.value) → chart-groups.children`
- For each selected TF builds a figure via `DataViewer.build_window_figure(start, days, tf=tf)`
- TF order in output follows ascending TF, not click order

**`DataViewer.build_window_figure(start, days, indicators=None, tf: int | None = None) -> go.Figure`**
- Gains a `tf` parameter overriding `self.tf` for this figure; `None` keeps current behaviour
- All column lookups inside the figure path use the passed TF prefix

---

## Key Constraints

- Available timeframes are discovered from the wide df columns — never hardcode the TF list (datasets may differ)
- Higher TFs have sparser rows in the wide df: forward-filled or NaN between candle closes — drop consecutive duplicate timestamps (or NaN rows) per TF before drawing so candles render one per TF period
- Each TF group is an independent figure — no shared axes across groups (plotly zoom stays per-chart)
- Empty selection renders an empty container, not an error

---

## Verification

```bash
LONG_ENV=configs/long_dataset.env docker compose up -d view-full
curl -sf http://localhost:8080 >/dev/null && echo "serving"
docker compose down view-full
```

Manual: select 15m + 1h + 4h — three chart groups appear, candle widths match each TF period; deselect 1h — its group disappears.

---

## Commit

`feat: add timeframe multi-select with per-TF chart groups to HistoryDashboard`
