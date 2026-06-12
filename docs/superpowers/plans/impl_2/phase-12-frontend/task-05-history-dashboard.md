# Task 05: HistoryDashboard — interactive viewer with date controls

**Phase:** 12 — Frontend  
**Depends on:** Task 01 (ChartRenderer), Task 02 (DataViewer)  
**Produces:** `frontend/history_dashboard.py` — interactive Dash viewer for the backtesting dataset; `view_full.py` updated to launch it

---

## Goal

Replace the static one-shot chart (`DataViewer.view_full()` → `fig.show()`) with an interactive Dash app for reviewing backtesting data. Two controls: a start-date picker selecting from which day data is shown, and a numeric input selecting how many days are shown. Changing either control re-slices the wide DataFrame and redraws the chart.

---

## Context

`view_full.py` currently renders once and exits. Researchers verifying a backtest dataset need to move through the date range without editing code. `LiveDashboard` already establishes the Dash app pattern (app owned by the dashboard class, `ChartRenderer` builds figures, served on `0.0.0.0:$DASH_PORT` default 8080, reachable through the `view-full` compose service). This task establishes the input → date slice → chart loop end-to-end; later tasks (06–09) add timeframes and indicator charts on top of this skeleton.

---

## Files

- Create: `frontend/history_dashboard.py`
- Modify: `view_full.py` — construct `HistoryDashboard` and call `run()` instead of `DataViewer.view_full()`
- Modify: `frontend/data_viewer.py` — add date-window figure building (see Interface)

---

## Interface

**`HistoryDashboard(full_data: FullData, tf: int = 15)`**

Attributes:
- `full_data: FullData`
- `tf: int` — primary timeframe for display (multi-TF comes in Task 06)
- `viewer: DataViewer` — figure construction delegate
- `_app: dash.Dash` — built in `__init__` via `_build_app()`

**`run() -> None`**
- Starts the Dash app, blocking. Binds `0.0.0.0:$DASH_PORT` (default 8080) — same contract as `LiveDashboard.run()`

Layout (ids are the callback contract):
- `dcc.DatePickerSingle(id="start-date")` — initial value = first index date of the wide df; min/max bounded by df index range
- `dcc.Input(id="days", type="number", min=1)` — initial value 7
- `dcc.Graph(id="history-chart")`

Callback: `(start-date.date, days.value) → history-chart.figure`
- Slices `full_data.df.loc[start : start + days]` (DatetimeIndex slicing, not iloc)
- Builds figure via `DataViewer.build_window_figure(...)`
- Empty slice → empty `go.Figure` with annotation "no data in range", never an exception

**`DataViewer.build_window_figure(start: pd.Timestamp, days: int, indicators: list[str] | None = None) -> go.Figure`**
- New public method: date-window variant of the existing `_build_figure()` path — slices by timestamp, draws candles + volume + default indicators for `self.tf`, returns the figure without showing it
- Existing `view_full()` / `view_full_levels()` / `save_chart()` keep their iloc-based signatures unchanged

---

## Key Constraints

- Date slicing uses the wide df `DatetimeIndex` (`df.loc[start:end]`) — the iloc convention stays only in the legacy `view_full()` API
- `HistoryDashboard` owns the Dash app; `DataViewer`/`ChartRenderer` stay Dash-free (figure factories only) — same split as `LiveDashboard`
- All data is read at startup from `FullData`; callbacks never touch the filesystem
- Wide df column access keeps the `{tf}_{col}` prefix convention
- No new dependencies — `dash`, `plotly` already pinned in `requirements.txt`

---

## Verification

```bash
LONG_ENV=configs/long_dataset.env docker compose up -d view-full
# wait for startup, then:
curl -sf http://localhost:8080 | grep -q "dash" && echo "dashboard serving"
docker compose down view-full
```

Manual: open `http://localhost:8080`, change start date and days — chart re-renders with the selected window.

---

## Commit

`feat: implement HistoryDashboard with start-date and days-count controls`
