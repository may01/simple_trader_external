# Phase 18 — CB Markers and Marker Filters in the Main Flow

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute candle-bound (CB) markers and four stored-only marker filters with one implementation in data preparation and the live session, so backtesting reads them from the prepared dataset.

**Architecture:** A new package `indicators/candle_bounds/` holds a vectorized kernel over a wide 1-min frame. Data prep calls it on the final frame; live assembles a small wide frame each tick and calls the same function. Bound models are frozen to JSON and predicted with numpy.

**Tech Stack:** Python 3.11, pandas, numpy, TA-Lib (existing indicators), pytest, Docker Compose. scikit-learn only in the one-off export script, never at runtime.

**Spec:** `specs/2026-10-05-cb-markers-main-flow-design.md` — read it first; this plan argues from it.

**Branch:** `cb-markers-main-flow` off `experimental_imp_2`, in a worktree under `simple_trader/worktrees/`.

---

## Global Constraints

- TFs are exactly `(15, 60, 240)`. Sides: `high`/`low` for bounds and extdone, `long`/`short` for zones, markers, filters.
- `ZONE_FRAC = 0.05`, `TGT_SHRINK_PCT = 0.15`.
- **No filter is applied to the marker.** The marker is the raw `{tf}_cb_inzone_{long,short}`. There is no `cb_marker` column.
- extdone is a **per-minute state, not sticky**. There is no `_first` column.
- extdone ladder (2y fit, per side), `(progress_from, d)`:
  - 15 high `(0.25, 5.0), (0.50, 2.5), (0.75, 1.5)`; 15 low `(0.25, 4.0), (0.50, 2.5), (0.75, 1.5)`
  - 60 high `(0.25, 10.0), (0.50, 8.0), (0.75, 4.0)`; 60 low `(0.25, 10.0), (0.50, 6.0), (0.75, 4.0)`
  - 240 high `(0.75, 8.0)`; 240 low `(0.75, 8.0)`
- `cb_f_trend`: long `ema_25_slope_class != -1`, short `!= +1`. `cb_f_mcx`: long `move_class == -3`, short `== +3`. `cb_f_extdone`: long `not extdone_high`, short `not extdone_low`.
- Warm-up / NaN input: float outputs NaN, bool outputs False.
- No scikit-learn import anywhere under `indicators/`, `training/`, `data.py`, `robots/`.
- No model file for the configured pair → stage skipped with one warning, no CB columns. Model file present but an input column missing → `ValueError` naming the columns.
- Existing indicator columns and existing strategies must not change value.
- No strategy, signal, or `trade_executor` change.
- All tests and gates run in Docker. Use a separate compose project so the live stack is untouched: `docker compose -p cbtest run --rm ohlc_gen python -m pytest <path> -q`.
- Do not commit, push or open a PR without the user's explicit confirmation. Stage, describe, wait.
- Docs (this plan, the spec, results) live in the external repo only, never in `main/`.
- Volume files are root-owned: write to them only from inside a container.

## Review Focus

Inputs the spec implies but no gate names. Each has a pinning test in the task shown.

1. **Minutes missing inside a candle** (exchange gap in prepared data). Expected: extdone progress follows wall-clock, not row count, so a candle with a hole reaches the same ladder step at the same clock minute. → Task 04.
2. **Live tick gap longer than one minute** (network stall, restart). Expected: `cbnc_*` is NaN for the first minute after the gap, never a stale prediction from minutes ago. → Task 09.
3. **Pair without a model file** (any pair other than LINK/USDT). Expected: prep completes and writes the dataset without CB columns; live does not raise; one warning. → Tasks 05, 06, 09.
4. **Old dataset without `ema_25_slope_class`.** Expected: prep stage fails with an error naming the missing columns; the materialize script backfills instead of failing. → Tasks 05, 07.
5. **Live frames with too little history** (fewer than ~20 closed candles for a tf after an exchange outage). Expected: that tf's outputs are NaN / False, other tfs unaffected, no exception. → Task 09.

---

## Docker Entry Points

No new service. Existing services gain behaviour:

```bash
# Prep — writes df_with_indicators.pkl including the CB columns
TRAIN_ENV=configs/oos2m_dataset.env docker compose run --rm ohlc_gen

# Add CB columns to an existing dataset in place (no re-prep)
TRAIN_ENV=configs/oos2m_dataset.env docker compose -p cbtest run --rm ohlc_gen \
    python3 scripts/cb_markers_materialize.py

# Gate report against the stored experiment sidecars (G2–G5 + marker counts)
TRAIN_ENV=configs/oos2m_dataset.env docker compose -p cbtest run --rm ohlc_gen \
    python3 scripts/cb_markers_validate.py

# Backtest — reads the columns from the prepared dataset, unchanged command
TRAIN_ENV=configs/oos2m_dataset.env docker compose run --rm simulate

# Live — computes the columns each tick and broadcasts them (user runs this; see Task 10)
docker compose up live

# Tests
docker compose -p cbtest run --rm ohlc_gen python -m pytest tests/unit/data_layer -q
```

One-off, outside the image (needs scikit-learn; run by the user or in a scratch venv with read access to the volume):

```bash
python scripts/cb_export_models.py \
    --train /media/om/Alexandria/simple_trader/simple_trader_vol_long/train/2y_az_link_usdt/df_with_indicators.pkl \
    --meta  /media/om/Alexandria/simple_trader/simple_trader_vol_long/train/oos2m_link_usdt/candle_bounds_meta.json \
    --out   indicators/candle_bounds/models_link_usdt.json
```

Verified: [ ] `docker compose -p cbtest run --rm ohlc_gen python -c "import indicators"` succeeds on the work branch.

---

## Layers

Order follows the pipeline. Within a layer: interface, then the integration test RED in Docker, then unit tests RED, then implementation.

### Layer 3 — Test data prep

**Interface consumed from Layer 4:**

```python
# indicators/candle_bounds/stage.py
def compute_cb_columns(wide_df: pd.DataFrame, pair: str | None = None) -> pd.DataFrame | None: ...
```

**Integration test → Layer 4 (RED first):** `tests/unit/data_layer/test_data_preparer_cb.py` — run `DataPreparer.prepare()` on the small mock dataset with a model file present; assert every column of `expected_columns()` exists in the saved frame; assert chunked output equals single-pass output for those columns (G7).

Tasks: 06 (prep wiring), 07 (materialize + validation scripts).

### Layer 4 — Indicators

**Interface produced:**

```python
# indicators/candle_bounds/models.py
@dataclass(frozen=True)
class BoundModel:
    tf: int
    side: str                 # "high" | "low"
    mean: np.ndarray          # shape (15,)
    scale: np.ndarray         # shape (15,)
    coef: np.ndarray          # shape (15,)
    intercept: float
    band_pct: float
    n_train: int
    def predict_pct(self, X: np.ndarray) -> np.ndarray: ...

ModelSet = dict[tuple[int, str], BoundModel]

def models_path(pair: str) -> str: ...
def load_models(pair: str) -> ModelSet | None: ...        # None when the file does not exist

# indicators/candle_bounds/stage.py
@dataclass(frozen=True)
class CbResult:
    columns: pd.DataFrame                                  # index = wide_df.index
    nc_pred_last: dict[tuple[int, str], tuple[float, float]]   # (bound, band) from the LAST row, unshifted

def required_columns() -> list[str]: ...
def expected_columns() -> list[str]: ...
def compute_cb(wide_df: pd.DataFrame, models: ModelSet, *,
               nc_pred_prev: dict[tuple[int, str], tuple[float, float]] | None = None) -> CbResult: ...
def compute_cb_columns(wide_df: pd.DataFrame, pair: str | None = None) -> pd.DataFrame | None: ...
```

Tasks: 01 (models), 02 (closed bounds, zones, marker), 03 (forming bounds, hybrid zones, cbx), 04 (extdone, filters), 05 (stage).

### Layer 5 — Backtesting

No code. **Integration test (RED first):** `SimulationData` over a prepared fixture returns finite/boolean values from `WideDataPoint.get("cb_inzone_long", 15)` and the other names (G9). Task 08.

### Live data layer (execution side of Layer 3/4)

**Interface produced:**

```python
# indicators/candle_bounds/stage.py
class LiveCbStage:
    def __init__(self, pair: str) -> None: ...
    @staticmethod
    def build_wide(ohlc: dict[int, pd.DataFrame]) -> pd.DataFrame: ...
    def update(self, ohlc: dict[int, pd.DataFrame]) -> None: ...   # writes {tf}_<name> into the last row of ohlc[tf]
```

**Integration test (RED first):** live parity replay (G8). Task 09.

### MQ broadcast

```python
# config_loader.py
@dataclass
class SharedIndicatorConfig:
    name: str
    timeframes: list[int]
    on_change: bool = False        # new: a value change publishes immediately, bypassing the interval
```

Task 10.

### Frontend

Three marker-filter toggles in `frontend/data_viewer.py`. Task 11.

---

## Task Index and Execution Order

| Task | File | Layer | Depends on | Gates |
|---|---|---|---|---|
| 01 | `task-01-frozen-bound-models.md` | 4 | — | G1 |
| 02 | `task-02-kernel-closed-bounds-zones.md` | 4 | 01 | — |
| 03 | `task-03-kernel-forming-bounds.md` | 4 | 02 | — |
| 04 | `task-04-kernel-extdone-filters.md` | 4 | 02 | G6 |
| 05 | `task-05-stage-entry-point.md` | 4 | 02, 03, 04 | — |
| 06 | `task-06-prep-wiring.md` | 3 | 05 | G7 (chunked) |
| 07 | `task-07-materialize-and-validate.md` | 3 | 05 | G2, G3, G4, G5, G7 (materialize) |
| 08 | `task-08-backtest-exposure.md` | 5 | 06 | G9 |
| 09 | `task-09-live-stage.md` | live | 05 | G8 |
| 10 | `task-10-mq-broadcast.md` | MQ | 09 | G10 |
| 11 | `task-11-viewer-filter-toggles.md` | frontend | 07 | — |
| 12 | `task-12-notebooks-and-docs-sync.md` | docs | all | — |

A layer's tasks start only when the previous layer's integration test is RED in Docker, and finish only when unit and integration tests are GREEN in Docker.

## Requirements Covered

| Spec section | Task |
|---|---|
| Frozen bound models, export script | 01 |
| Columns: closed bounds, zone, marker | 02 |
| Columns: forming bounds, hybrid zone, cbx | 03 |
| extdone definition (per minute), ladder, filters | 04 |
| Skip without model / error on missing input | 05 |
| Data preparation, chunked equality | 06 |
| Existing datasets, backfill, gates G2–G5, marker counts | 07 |
| Backtesting | 08 |
| Live session, held forming prediction | 09 |
| MQ broadcast, publish on change | 10 |
| Viewer | 11 |
| Notebooks import the kernel; spec and results kept in sync | 12 |
