# DataPreparer Class Specification

**Version:** 2.0 — New class introduced as part of Trainer decomposition
**Class:** `DataPreparer`
**File:** `data_preparer.py`
**Purpose:** Transform `graber_data.pkl` into the fully enriched `df_with_indicators.pkl` consumed by `SimulationData`, `FullData`, and `NNOrchestrator`.

---

## 1. Class Overview

`DataPreparer` owns the **entire offline data preparation pipeline** from raw 1-min OHLCV to the enriched wide DataFrame — Steps 1–6 of Data Module v2.0 §8.2 (Wide Data Generation). `Graber` produces `graber_data.pkl` on disk; `DataPreparer` reads it, builds the wide base DataFrame, computes indicators per-minute, runs NN forward-looking targets, computes per-pair stats, and writes `df_with_indicators.pkl`.

The class is a thin orchestrator around the Data Module's `Indicators`, `IndicatorField` registry, and `DataAttributes` classes. It does not implement indicator math itself — every column is computed by an `IndicatorField` subclass loaded from `indicators_config.yaml`.

**Key responsibilities:**
1. **Load** `{root_folder(pair)}/graber_data.pkl` (the raw 1-min OHLCV produced by `Graber`).
2. **Build the wide base DataFrame**: for each `tf` in `CANDLES`, construct `{tf}_open_index`, `{tf}_open`, `{tf}_high`, `{tf}_low`, `{tf}_close`, `{tf}_volume`, `{tf}_buy_volume`, `{tf}_is_closed` per Data Module v2.0 §4.1–§4.2. This is the `get_stock_data()` step.
3. **Load** the indicator registry from `indicators_config.yaml`.
4. **Compute indicators** (parallel across time-batch workers): for each timeframe, at every 1-min row, call `Indicators.compute(WideDataPoint(df, ts), tf)`. Each row of the resulting wide DataFrame is a fully-populated `WideDataPoint` snapshot: closed-candle state at boundaries, partial-candle state mid-period.
6. **Compute stats** via `DataAttributes.compute(df)` → `rsi_classification.json`, `diff_stats.pkl`.
7. **Persist** the result to `{root_folder(pair)}/df_with_indicators.pkl`.

**Per-minute compute model.** Indicators on higher timeframes (e.g. `5_rsi_14`, `60_macd`) are computed **at every 1-min row**, not only at the candle close. At a row mid-candle, the indicator uses the partial-candle state visible through the expanding `{tf}_close/high/low/volume` columns; at a close-boundary row it uses the final closed-candle state. **There is no forward-fill step** — every row independently reflects the state of that minute. This matches Data Module v2.0 §5.3 (RSI example at `ts=09:02` partial candle producing a value distinct from the `ts=09:04` close value) and §7.2 (`WideDataPoint.get(col, tf, shift=0)` returns "current value, partial candle if mid-period").

---

## 2. Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `pair` | `str` | Trading pair. |
| `trainer` | `Trainer` | Injected reference for env/config access (threads, dates). |
| `candles` | `list[int]` | Active timeframes from `candles_config.yaml`. |
| `indicators` | `Indicators` | Indicator registry / dispatcher (Data Module v2.0). |
| `attributes` | `DataAttributes` | Stats file manager (Data Module v2.0). |
| `_raw_path` | `str` | `{root_folder(pair)}/graber_data.pkl` (input). |
| `_output_path` | `str` | `{root_folder(pair)}/df_with_indicators.pkl` (output). |

---

## 3. Constructor

### `__init__(pair: str, trainer: Trainer, candles: list[int] | None = None)`

**Behavior:**
1. Store `pair`, `trainer`.
2. Load `candles` from config if not provided.
3. Instantiate `self.indicators = Indicators(config_path="indicators_config.yaml")`.
4. Instantiate `self.attributes = DataAttributes(pair)`.
5. Compute `_raw_path = {root_folder(pair)}/graber_data.pkl` and `_output_path = {root_folder(pair)}/df_with_indicators.pkl`.

**Postconditions:**
- Indicator registry is loaded; fields are sorted by dependency.
- Instance is ready to call `prepare()`; no disk I/O has happened yet.

---

## 4. Methods

### 4.1 `prepare() -> pd.DataFrame`

**Purpose:** Read `graber_data.pkl`, build the wide base DataFrame, enrich it with indicators and NN targets, compute stats, and persist `df_with_indicators.pkl`.

**Behavior:**

1. **Load raw data.** Call `self._load_raw_data()` (see §4.3):
   - Reads `_raw_path` (`graber_data.pkl`).
   - Validates required columns `[o, h, l, c, v, taker_base_vol]`.
   - Renames to canonical names `[open, high, low, close, volume, taker_base_vol]`.
   - Slices to `[DATA_START, DATA_END]` from `self.trainer`.
   - Validates strictly 1-min spacing (raises `ValueError` on gaps).
2. **Build the wide base DataFrame.** Call `self._build_base_dataframe(raw_df)` (see §4.4):
   - For each `tf` in `self.candles`, derive `{tf}_open_index`, `{tf}_open`, `{tf}_high`, `{tf}_low`, `{tf}_close`, `{tf}_volume`, `{tf}_buy_volume`, `{tf}_is_closed` per Data Module v2.0 §4.1–§4.2.
   - Returns a 1-min indexed wide DataFrame with `~8 × len(candles)` base columns and no indicator columns yet.
3. **Time-batch indicator computation** (parallel across `trainer.available_threads()`):
   ```
   batches = split_timestamps(base_df.index, n=trainer.available_threads())
   for (ts_begin, ts_end) in batches  (parallel workers):
       for ts in base_df.index[(base_df.index >= ts_begin) & (base_df.index <= ts_end)]:
           for tf in candles:
               point = WideDataPoint(base_df, ts)
               Indicators.compute(point, tf)
               # writes every {tf}_<col> value for this row
   # No ffill: each 1-min row already holds its own per-minute computed values.
   ```
   - Each worker is assigned a contiguous timestamp range and computes **all timeframes' indicators** at every 1-min row in that range.
   - Workers receive read access to the full `base_df` (copy or shared memory). Historical context required by `build_indicator_input` (the previous ~105 closed candles) is read directly from `base_df` — no warmup overlap is needed because indicator math depends only on base OHLCV columns, not on previously-computed indicator outputs.
   - At a row where `{tf}_is_closed == True`, the computed value is the final closed-candle state; at any other row it is the partial-candle state visible through expanding aggregations.
   - Each row of the output is itself a complete `WideDataPoint`: signals/strategies reading `df.loc[ts, "{tf}_rsi_14"]` always get a meaningful value with no gaps.
   - Workers return a DataFrame slice covering only their assigned rows and the indicator columns they wrote.
   - Main thread concatenates the per-batch slices along the time axis to produce the enriched wide DataFrame.
4. **Forward-looking target computation** (see §5). The NN target fields read forward in the DataFrame; they run after step 3 so they can reference completed indicator values.
5. **Stats computation.** Call `self.attributes.compute(df)`:
   - Builds `rsi_classification.json` if absent or out of date.
   - Builds `diff_stats.pkl` if absent or out of date.
   - `level_stats.pkl` is loaded if present; built only via manual offline tooling, not here.
6. **Persist.** Save `df` to `_output_path` via temp-file + atomic rename.
7. **Return** the enriched DataFrame.

**Return:** Enriched wide DataFrame (same shape as written to disk).

**Preconditions:**
- `graber_data.pkl` exists at `_raw_path` (produced by `Graber.grab()`).
- `indicators_config.yaml` is well-formed.
- `DATA_START` / `DATA_END` env vars are set.
- Filesystem permits writing to `_output_path`.

**Postconditions:**
- `df_with_indicators.pkl` exists at `_output_path`.
- `rsi_classification.json`, `diff_stats.pkl` exist for `self.pair`.
- Enriched DataFrame contains the full column set described in Data Module v2.0 §5.2.

**Exceptions:**
- `FileNotFoundError` if `graber_data.pkl` is missing (with hint to run `Graber.grab()` or `RUN_TYPE=grab_data`).
- `ValueError` if raw data has gaps in its 1-min index or missing required columns.
- `RuntimeError` if a batch worker process fails (re-raised with the offending time range).
- `KeyError` if `indicators_config.yaml` references an unknown `IndicatorField` class.

---

### 4.2 `_load_raw_data() -> pd.DataFrame`

**Purpose:** Read `graber_data.pkl` and return a validated 1-min OHLCV DataFrame sliced to the configured date range.

**Behavior:**
```python
def _load_raw_data(self) -> pd.DataFrame:
    df = pd.read_pickle(self._raw_path)
    required = {"o", "h", "l", "c", "v", "taker_base_vol"}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"graber_data.pkl missing columns: {missing}")
    df = df.rename(columns={
        "o": "open", "h": "high", "l": "low",
        "c": "close", "v": "volume",
    })
    begin_ts = self.trainer.train_begin_time()
    end_ts   = self.trainer.train_end_time()
    df = df.loc[pd.Timestamp(begin_ts, unit="s"):pd.Timestamp(end_ts, unit="s")]
    expected = pd.date_range(df.index.min(), df.index.max(), freq="1min")
    if not df.index.equals(expected):
        raise ValueError(
            f"graber_data.pkl is not strictly 1-min spaced over "
            f"[{df.index.min()}, {df.index.max()}]"
        )
    return df
```

**Exceptions:**
- `FileNotFoundError` if `_raw_path` does not exist.
- `KeyError` if required source columns are absent.
- `ValueError` if the date-range slice is empty or has gaps.

---

### 4.3 `_build_base_dataframe(raw_df: pd.DataFrame) -> pd.DataFrame`

**Purpose:** Build the wide base DataFrame (Data Module v2.0 §4.1–§4.2) from the 1-min OHLCV raw frame. This is the `get_stock_data()` step.

**Behavior:**

1. Initialize the wide DataFrame indexed identically to `raw_df`.
2. For each `tf` in `self.candles`:
   - Compute `{tf}_open_index = raw_df.index.floor(f"{tf}min")`.
   - Compute per-tf base columns using groupby on `{tf}_open_index`:

     | Column | Computation |
     |--------|-------------|
     | `{tf}_open` | `groupby({tf}_open_index)["open"].transform("first")` |
     | `{tf}_high` | `groupby({tf}_open_index)["high"].expanding().max()` (reset by group) |
     | `{tf}_low` | `groupby({tf}_open_index)["low"].expanding().min()` (reset by group) |
     | `{tf}_close` | `raw_df["close"]` (raw 1-min close) |
     | `{tf}_volume` | `groupby({tf}_open_index)["volume"].expanding().sum()` |
     | `{tf}_buy_volume` | `groupby({tf}_open_index)["taker_base_vol"].expanding().sum()` |
   - Compute `{tf}_is_closed` per Data Module v2.0 §4.2 rules:
     - `tf=1` → always `True`
     - `tf=5` → `index.minute % 5 == 4`
     - `tf=15` → `index.minute % 15 == 14`
     - `tf=60` → `index.minute == 59`
     - `tf=240` → `index.minute == 59 and index.hour % 4 == 3`
     - `tf=1440` → `index.minute == 59 and index.hour == 23`
3. Return the wide base DataFrame (no indicator columns yet).

**Return:** 1-min indexed wide DataFrame with `~8 × len(candles)` base columns.

**Invariant:** The output contains every base column listed in Data Module v2.0 §4.1–§4.2 for every active timeframe, and no `{tf}_*` indicator columns.

---

### 4.4 `_compute_batch(base_df: pd.DataFrame, ts_begin: pd.Timestamp, ts_end: pd.Timestamp) -> pd.DataFrame`

**Purpose:** Time-batch worker entry point. Computes all timeframes' indicators for every 1-min row in `[ts_begin, ts_end]`.

**Behavior:**
```python
def _compute_batch(base_df, ts_begin, ts_end):
    # base_df is the FULL wide base DataFrame (all timestamps);
    # historical context for indicator math is read directly from it.
    mask = (base_df.index >= ts_begin) & (base_df.index <= ts_end)
    batch_rows = base_df.index[mask]

    for ts in batch_rows:
        for tf in self.candles:
            point = WideDataPoint(base_df, tf=tf, ts=ts)
            self.indicators.compute(point, tf)
            # writes {tf}_<col> values into base_df.loc[ts, ...] for every field

    indicator_cols = [c for c in base_df.columns if c not in BASE_COLS]
    return base_df.loc[batch_rows, indicator_cols]
```

Executed inside a worker process spawned by `prepare()`. Returns only its row slice × newly added columns to minimize inter-process payload. No forward-fill — every row already carries the per-minute values computed for its own state.

**Why time-batch instead of per-tf:**
- **Scales beyond `len(CANDLES)`.** Per-tf is capped at 6 workers (one per active timeframe); time-batch scales to `available_threads()`.
- **Uniform per-worker load.** Every worker computes the same set of fields per row, so wall time is balanced.
- **No warmup overlap needed.** `build_indicator_input` reads OHLCV history directly from the shared `base_df`; indicator math depends only on base columns, never on previously-computed indicator outputs, so workers do not need to share or sequence indicator results across batch boundaries.

**Cost note.** Per-minute compute multiplies the work for a high-tf indicator by `tf` (compared to a close-only model). For a 1-year dataset (~525k 1-min rows × 6 timeframes × ~50 fields/tf) the cost is dominant in the pipeline. Time-batch parallelism with `N` workers reduces wall time by ~`N×` (modulo `base_df` copy / shared-memory overhead). The cost is amortized once at preparation time; replay (`SimulationData`) and live (`LiveData`) are O(1) per step.

---

## 5. NN Forward-Looking Targets

NN training labels (e.g., `08_NO_DIP`, `1H_ATR`, `4H_ATR` — BUY/SELL/NONE classifications based on N-minute-ahead price movement) are implemented as `IndicatorField` subclasses in the `nn_targets` group:

```yaml
# indicators_config.yaml (excerpt)
fields:
  - name: nn_tgt_08_no_dip
    group: nn_targets
    applies_to: [1]
    depends_on: [close, atr_14]
    params: {horizon_min: 30, threshold_pct: 0.8, allow_dip: false}
  - name: nn_tgt_1h_atr
    group: nn_targets
    applies_to: [1]
    depends_on: [close, atr_14]
    params: {horizon_min: 60, threshold_atr: 1.0}
  ...
```

**Forward-reference safety:** These fields read `df.loc[ts + horizon]` from the complete historical DataFrame. This is only valid offline; the live path **must not register `nn_targets` fields** in its `Indicators` instance (or the live `Indicators` instance must skip the `nn_targets` group).

**Execution order:** Targets run after all other indicator fields, in a final pass within `prepare()`. They produce columns `{tf}_nn_tgt_*` that join the per-row feature vector.

---

## 6. Output Schema

The output `df_with_indicators.pkl` matches Data Module v2.0 §6.2 exactly:

- **Index:** 1-min `DatetimeIndex` (UTC), `[DATA_START, DATA_END]`.
- **Columns per active `tf`:**
  - Base: `{tf}_open`, `{tf}_high`, `{tf}_low`, `{tf}_close`, `{tf}_volume`, `{tf}_buy_volume`, `{tf}_open_index`, `{tf}_is_closed`
  - Momentum: `{tf}_rsi_14`, `{tf}_rsi_ma8`, …
  - Trend: `{tf}_ema_*`, `{tf}_macd*`
  - Volatility: `{tf}_atr_14`, `{tf}_bb_*`
  - Oscillators: `{tf}_cci_14`, `{tf}_sar`
  - Volume: `{tf}_vol_ma`, `{tf}_vol_buy_ma`
  - Price derivatives: `{tf}_close_diff_prc*`
  - Classification (tf ∈ {15,60,240,1440}): `{tf}_move_class`, `{tf}_zone_class`, etc.
  - Targets (tf ∈ {15,60,240,1440}): `{tf}_tgt_long`, `{tf}_sl_long`, `{tf}_tgt_short`, `{tf}_sl_short`, `{tf}_ZB`, `{tf}_ZS`
  - Trend flags: `{tf}_trend_up`, `{tf}_trend_down`
  - NN features (tf ∈ {1, 5, 15}): `{tf}_nn_*`
  - NN forward-looking targets (tf=1): `1_nn_tgt_*`

Approximate column count: ~300+ depending on the configured registry.

---

## 7. Parallelization

`prepare()` parallelizes **by timestamp range**. The full 1-min index of `base_df` is split into `N = trainer.available_threads()` contiguous, non-overlapping batches. Each worker computes all timeframes' indicators for every 1-min row in its assigned batch.

| Worker | Time Range Assigned | Computes | Output Rows |
|--------|---------------------|----------|-------------|
| 1 | `[ts₀, ts₁)` | every `{tf}_*` indicator for every row in range | rows `[ts₀, ts₁)` × all indicator cols |
| 2 | `[ts₁, ts₂)` | every `{tf}_*` indicator for every row in range | rows `[ts₁, ts₂)` × all indicator cols |
| … | … | … | … |
| N | `[tsₙ₋₁, ts_end]` | every `{tf}_*` indicator for every row in range | rows `[tsₙ₋₁, ts_end]` × all indicator cols |

**Why time-axis sharding scales better than per-tf sharding.**
- Per-tf would cap parallelism at `len(CANDLES) = 6` workers; time-axis scales to whatever `available_threads()` provides.
- Per-row workload is uniform (same field set per row), so wall time across workers is balanced.
- Main thread just concatenates row slices — no per-tf merge step.

**No warmup overlap.** Each worker holds read access to the entire `base_df` (via copy or `mp.shared_memory`). When `build_indicator_input(base_df, ts, tf)` runs for a `ts` at the start of a worker's batch, the historical 105 closed candles are read from `base_df` exactly as they would be in a single-process run. Indicator math is a pure function of `base_df` columns — it never consumes another worker's output — so batches do not need to overlap or share intermediate state.

**Worker memory.** Each worker process holds one full `base_df` (≈500MB–2GB depending on date range). For N=8 workers on a 1-year pair, peak RAM ≈ N × 2GB ≈ 16GB. If this becomes a problem, switch to `mp.shared_memory` for `base_df` (single shared copy) — orthogonal to this spec.

**Per-minute compute cost.** Total work is `O(len(base_df) × len(CANDLES) × fields_per_tf)`. For a 1-year dataset (~525k rows × 6 tfs × ~50 fields/tf ≈ 160M field computations) this dominates the pipeline. Time-axis parallelism with N workers reduces wall time by ~N×.

**Sequential final pass on main thread:**
- NN forward-looking target fields run after all batch workers join — they read `df.loc[ts + horizon]` and therefore need the complete enriched DataFrame to be assembled.
- `DataAttributes.compute(df)` runs after NN targets, on the assembled DataFrame.

---

## 8. Error Handling

| Condition | Behavior |
|-----------|----------|
| `graber_data.pkl` missing | `FileNotFoundError` at `_load_raw_data()` with hint to run `Graber.grab()` or `RUN_TYPE=grab_data`. |
| `graber_data.pkl` schema invalid | `KeyError` / `ValueError` from `_load_raw_data()`. |
| Gap in 1-min index | `ValueError` from `_load_raw_data()`. |
| Worker process crash | `prepare()` raises `RuntimeError(f"batch [{ts_begin}, {ts_end}] preparation failed: …")`. Partial output is discarded. |
| `indicators_config.yaml` missing | `FileNotFoundError` from `Indicators.__init__`. |
| Unknown `IndicatorField` class in config | `KeyError` from the registry loader. |
| `DataAttributes.compute()` failure | Propagated. The wide DataFrame is NOT saved if stats computation fails — partial outputs are not committed. |
| Write to `_output_path` fails | Propagated `IOError`. |

---

## 9. Testing Notes

- **End-to-end:** seed a tiny synthetic `graber_data.pkl` (e.g., 2 days of 1-min OHLCV), call `DataPreparer(pair, trainer).prepare()`, assert that the output contains every column in `indicators_config.yaml` for every `tf` and matches the schema in §6.
- **Base build correctness:** assert `{tf}_open` is constant within a candle period; `{tf}_high/low/volume` expand correctly; `{tf}_is_closed` is `True` only at the correct minute boundaries.
- **Per-minute compute:** assert `5_rsi_14` at a mid-candle row (e.g. 09:02) differs from the value at the next close (09:04).
- **NN target test:** verify that `1_nn_tgt_08_no_dip.iloc[-30]` reflects the price move over the following 30 minutes correctly (and that values within the last `horizon_min` are NaN).
- **Stats files:** assert `rsi_classification.json` and `diff_stats.pkl` are produced if absent and untouched if up-to-date.
- **Missing input:** delete `graber_data.pkl` before calling `prepare()` → assert `FileNotFoundError` with a hint mentioning `Graber.grab()`.

---

## 10. Constraints and Invariants

- **No network access.** `DataPreparer` reads `graber_data.pkl` from disk; downloading from Binance is `Graber`'s job exclusively.
- **No replay logic.** This class only writes the wide DataFrame; it does not iterate at simulation step.
- **Indicator registry is the source of truth.** Adding/removing fields requires no change to `DataPreparer`.
- **Per-minute compute, no forward-fill.** Every 1-min row in the output DataFrame is a fully-populated `WideDataPoint`: `df.loc[ts, f"{tf}_{col}"]` is always the indicator value computed *for that minute's state* (partial when mid-candle, closed at boundaries). No row carries a ffilled stand-in.
- **Atomicity.** `df_with_indicators.pkl` is written via a temp-file + rename pattern so an interrupted run does not leave a corrupt prepared file.
- **Live path safety.** NN forward-looking target fields are tagged `applies_to_live: false` in the registry and are skipped by `LiveData`'s `Indicators` instance.
- **Base DataFrame is internal.** `_build_base_dataframe()` is a private step; the wide base DataFrame is never persisted to disk independently. `graber_data.pkl` is the input artifact; `df_with_indicators.pkl` is the only output artifact.
