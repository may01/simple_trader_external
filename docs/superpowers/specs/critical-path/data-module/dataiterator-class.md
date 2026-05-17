# SimulationData Class Specification

**Class:** `SimulationData`
**Supersedes:** `DataIterator` (v1 — deprecated; see §11)
**Category:** Data Module — Historical Data Replay Iterator
**Status:** Production (v2.0)

---

## 1. Class Overview

`SimulationData` provides **sequential replay over a pre-computed wide DataFrame** for historical backtesting and simulation. It replaces the v1 `DataIterator` pattern of loading per-timestamp pickle files.

**Core design change from v1:**
- v1 `DataIterator`: loaded `data/{pair}/{timestamp}/ohlc.pkl` at each step — per-snapshot disk I/O on every tick
- v2 `SimulationData`: loads `df_with_indicators.pkl` **once** at init, then replays rows in memory — no per-step I/O

**Responsibilities:**
- Load and hold `df_with_indicators.pkl` (wide DataFrame, 1-min indexed, all timeframes and indicators pre-computed)
- Walk a `pd.date_range` over the requested time window at a configurable minute step
- At each step, yield a `WideDataPoint` that exposes the same `DataPoint` protocol as live trading
- Support `next()`, `is_end()`, and `steps` for loop control

**Design patterns:**
- **Stateful iterator**: holds `_idx` (integer) advancing through a `pd.date_range`
- **Single-load**: DataFrame loaded once, no disk I/O at replay time
- **Protocol-compatible**: `WideDataPoint.get(col, tf, shift)` is identical to `LiveDataPoint.get(col, tf, shift)` — signals and strategies are path-agnostic

---

## 2. Key Attributes

| Attribute | Type | Purpose | Initialization |
|-----------|------|---------|-----------------|
| `_df` | `pd.DataFrame` | Wide DataFrame from `df_with_indicators.pkl` — all TFs, all indicators, 1-min indexed | Loaded at init |
| `_ts_range` | `pd.DatetimeIndex` | Sequence of timestamps to replay; built via `pd.date_range` | Built at init |
| `_idx` | `int` | Current position in `_ts_range` | `0` |

### Derived Values
- **Total steps**: `len(_ts_range)` — also exposed as `steps` property
- **Current timestamp**: `_ts_range[_idx]`
- **Progress**: `_idx / len(_ts_range)`

---

## 3. Constructor

### Signature

```python
def __init__(self, pair: str, begin_ts: int, end_ts: int, step_min: int) -> None
```

### Parameters

| Parameter | Type | Notes |
|-----------|------|-------|
| `pair` | `str` | Trading pair in `coin_base` format (e.g. `"link_usdt"`) |
| `begin_ts` | `int` | Start timestamp in Unix **seconds** |
| `end_ts` | `int` | End timestamp in Unix **seconds** — inclusive |
| `step_min` | `int` | Time step in **minutes** between replay points |

### Implementation

```python
def __init__(self, pair: str, begin_ts: int, end_ts: int, step_min: int) -> None:
    path = root_folder() + "/df_with_indicators.pkl"
    self._df = pd.read_pickle(path)
    self._ts_range = pd.date_range(
        start=pd.Timestamp(begin_ts, unit="s"),
        end=pd.Timestamp(end_ts, unit="s"),
        freq=f"{step_min}min"
    )
    self._idx = 0
```

### Postconditions
- `df_with_indicators.pkl` is fully loaded into `_df` — no further disk I/O during replay
- `_ts_range` defines the exact sequence of timestamps to visit
- `_idx = 0` — ready to call `get()` at `begin_ts`

### Exceptions
- **FileNotFoundError**: If `df_with_indicators.pkl` does not exist — must run `trainer.py RUN_TYPE=generate_ohlc` first
- **MemoryError**: If the DataFrame is too large to fit in RAM (mitigate by limiting date range in wide data generation)

### Notes
- `begin_ts` and `end_ts` are Unix **seconds**, unlike the v1 `DATA_START` / `DATA_END` env vars which are milliseconds
- `pd.date_range` with `freq` handles DST, month boundaries, and edge timestamps correctly
- `step_min` does not need to match a candle timeframe; `step_min=1` gives tick-by-tick replay

---

## 4. Key Methods

### 4.1 `get() -> WideDataPoint`

**Purpose:** Return a `WideDataPoint` for the current replay timestamp.

**Signature:**
```python
def get(self) -> WideDataPoint:
    return WideDataPoint(self._df, self._ts_range[self._idx])
```

**Behavior:**
- Creates a `WideDataPoint` wrapping `_df` and the current `pd.Timestamp`
- `WideDataPoint.get(col, tf, shift)` accesses indicator values for that timestamp (see §7)
- O(1) — no I/O, no computation; the DataFrame is pre-loaded

**Preconditions:** `not self.is_end()`

**Exceptions:**
- **IndexError**: If called when `is_end()` is True
- **KeyError**: If `_ts_range[_idx]` is outside `_df.index` (timestamp not in wide DataFrame)

---

### 4.2 `next() -> None`

**Purpose:** Advance iterator to the next replay timestamp.

**Signature:**
```python
def next(self) -> None:
    self._idx += 1
```

**Behavior:**
- Increments `_idx` by 1 — advances by one `step_min` interval
- Does not validate bounds; check `is_end()` before calling `get()`

**Time complexity:** O(1)

---

### 4.3 `is_end() -> bool`

**Purpose:** Check whether all replay steps have been processed.

**Signature:**
```python
def is_end(self) -> bool:
    return self._idx >= len(self._ts_range)
```

**Behavior:**
- Returns `True` when `_idx` has gone past the last timestamp in `_ts_range`
- Returns `False` during all valid replay steps

**Difference from v1:** v1 `DataIterator.is_end()` required exact timestamp equality (`cur_point == end_point`), which could miss the end if steps were non-uniform. v2 uses index comparison — always terminates correctly.

---

### 4.4 `steps` property

**Purpose:** Expose total replay length for progress reporting.

```python
@property
def steps(self) -> int:
    return len(self._ts_range)
```

---

## 5. Usage Patterns

### Basic simulation loop

```python
sim = SimulationData("link_usdt", begin_ts, end_ts, step_min=1)

while not sim.is_end():
    point = sim.get()                              # WideDataPoint
    rsi   = point.get("rsi_14", tf=15)            # current 15-min RSI
    close = point.get("close",  tf=5)             # current 5-min close
    sim.next()
```

### With step counter and progress

```python
sim = SimulationData("link_usdt", begin_ts, end_ts, step_min=5)
total = sim.steps

for i in range(total):
    point = sim.get()
    action = strategy.select_action(point)
    robot.step(action)
    sim.next()
    if i % 100 == 0:
        print(f"Progress: {100 * i / total:.1f}%")
```

### Integration with TrainRobot (matches data-module.md §8.3)

```python
# trainer.py
sim = SimulationData(pair, begin_ts, end_ts, step_minutes)
while not sim.is_end():
    data_point = sim.get()
    signal = signal_manager.check(data_point)
    action = strategy.select_action(data_point)
    train_robot.step(data_point, action)
    sim.next()
results = train_robot.finalize()
```

### Accessing shift history (closed candles)

```python
point = sim.get()
rsi_now  = point.get("rsi_14", tf=15, shift=0)   # current value (may be partial candle)
rsi_prev = point.get("rsi_14", tf=15, shift=1)   # last closed 15-min candle
rsi_2ago = point.get("rsi_14", tf=15, shift=2)   # candle before that
```

---

## 6. Source Data: `df_with_indicators.pkl`

`SimulationData` reads from a single file generated offline by `trainer.py RUN_TYPE=generate_ohlc`.

### File location

```
{root_folder}/{pair}/df_with_indicators.pkl
```

### Structure

- **Index:** 1-min `DatetimeIndex` (UTC)
- **Columns:** grouped by timeframe prefix `{tf}_`

| Column pattern | Example | Description |
|----------------|---------|-------------|
| `{tf}_open` | `5_open` | Candle open price (constant within period) |
| `{tf}_high` | `5_high` | Expanding high within period |
| `{tf}_low` | `5_low` | Expanding low within period |
| `{tf}_close` | `5_close` | Current 1-min close (= current candle state) |
| `{tf}_volume` | `5_volume` | Expanding volume sum within period |
| `{tf}_buy_volume` | `5_buy_volume` | Expanding taker buy volume |
| `{tf}_open_index` | `5_open_index` | Open timestamp of the candle this row belongs to |
| `{tf}_is_closed` | `5_is_closed` | True at the last 1-min row of each tf-period |
| `{tf}_rsi_14` | `5_rsi_14` | RSI-14 for 5-min candles (written at `{tf}_is_closed=True` rows only) |
| `{tf}_ema_25` | `15_ema_25` | EMA-25 for 15-min candles |
| `{tf}_move_class` | `60_move_class` | RSI momentum class (tf ∈ {15,60,240,1440} only) |
| `{tf}_tgt_long` | `60_tgt_long` | Long target price (tf ∈ {15,60,240,1440} only) |
| `{tf}_ZB` | `60_ZB` | Probability-weighted buy zone |
| `{tf}_is_closed` | `1_is_closed` | Always True for tf=1 |

### Active timeframes

Defined in `candles_config.yaml`:
```yaml
candles: [1, 5, 15, 60, 240, 1440]
```

### Memory size

~300+ columns × (full date range × 1440 rows/day). A 1-year dataset ≈ 500k rows × 300 columns ≈ 1–2 GB RAM.

---

## 7. WideDataPoint — Value Access

`SimulationData.get()` returns a `WideDataPoint`. The `DataPoint` protocol is the same interface used by `LiveDataPoint` in live trading.

```python
class WideDataPoint(DataPoint):
    def get(self, col: str, tf: int, shift: int = 0) -> float:
        if shift == 0:
            return self._df.loc[self._ts, f"{tf}_{col}"]
        closed = self._df[:self._ts][self._df[:self._ts][f"{tf}_is_closed"]]
        if len(closed) < shift:
            return float("nan")
        return closed.iloc[-shift][f"{tf}_{col}"]
```

### Shift semantics

| shift | Meaning |
|-------|---------|
| 0 | Current value at `ts` — partial candle if `ts` is mid-period |
| 1 | Last closed tf-period candle (using `{tf}_is_closed=True` filter) |
| N | Nth last closed tf-period candle |

### Shift examples (tf=5, ts=09:02)

| Call | Result |
|------|--------|
| `point.get("rsi_14", tf=5, shift=0)` | `df.loc["09:02", "5_rsi_14"]` — partial candle state |
| `point.get("rsi_14", tf=5, shift=1)` | `df.loc["08:59", "5_rsi_14"]` — last closed 5-min candle |
| `point.get("rsi_14", tf=5, shift=2)` | `df.loc["08:54", "5_rsi_14"]` — candle before that |

### Shift examples (tf=5, ts=09:04 — close boundary)

| Call | Result |
|------|--------|
| `point.get("rsi_14", tf=5, shift=0)` | `df.loc["09:04", "5_rsi_14"]` — complete candle |
| `point.get("rsi_14", tf=5, shift=1)` | `df.loc["09:04", "5_rsi_14"]` — same row (last closed = current) |
| `point.get("rsi_14", tf=5, shift=2)` | `df.loc["08:59", "5_rsi_14"]` — previous closed candle |

---

## 8. Time Stepping

### Common step values

| step_min | Snapshots / day | Use Case |
|----------|-----------------|----------|
| 1 | 1440 | Full-resolution backtesting, data generation |
| 5 | 288 | Standard simulation frequency |
| 15 | 96 | Quick research runs |
| 60 | 24 | Daily aggregation |

### TRAINER_TIME_STEP environment variable

`step_min` is typically provided from the `TRAINER_TIME_STEP` env var:
```python
step_min = int(os.environ.get("TRAINER_TIME_STEP", 1))
```

### `step_min` and candle timeframes

`step_min` does not need to match a candle timeframe. At `step_min=1`, every 1-min row is visited; `shift` semantics on `WideDataPoint` handle the candle boundary logic regardless of step.

---

## 9. Error Handling

### Missing `df_with_indicators.pkl`

**Symptom:** `FileNotFoundError` at `SimulationData.__init__`

**Cause:** `trainer.py RUN_TYPE=generate_full_ohlc` has not been run for this pair.

**Resolution:** Run:
```bash
SCRIPT_TYPE=trainer RUN_TYPE=generate_ohlc docker-compose up --build
```

### Timestamp out of range

**Symptom:** `KeyError` when `WideDataPoint.get()` accesses `df.loc[ts]`

**Cause:** `begin_ts` or `end_ts` is outside the date range of `df_with_indicators.pkl`.

**Resolution:** Check `_df.index.min()` / `_df.index.max()` against the requested range before creating `SimulationData`.

### NaN indicator values

**Symptom:** `float("nan")` returned from `WideDataPoint.get()` with `shift > 0`

**Cause:** Not enough closed candles before `begin_ts` to satisfy the shift depth (typical at start of dataset).

**Handling:** Strategy code should guard against NaN:
```python
val = point.get("rsi_14", tf=15, shift=1)
if math.isnan(val):
    continue
```

### Memory exhaustion

**Symptom:** `MemoryError` at `pd.read_pickle(path)`

**Cause:** Full-year wide DataFrame (~1–2 GB) exceeds available RAM.

**Mitigation:** Narrow the date range covered by `df_with_indicators.pkl`, or partition into yearly files.

---

## 10. Integration with Other Components

| Component | Role | Integration Point |
|-----------|------|-------------------|
| `TrainRobot` (`train_robot.py`) | Simulation engine | Receives `WideDataPoint` from `sim.get()` each step |
| `Trainer` (`trainer.py`) | Orchestrates backtesting | Creates `SimulationData`, calls `sim.get()` → `sim.next()` loop |
| `SignalManager` (`signals.py`) | Signal evaluation | Calls `data_point.get(col, tf, shift)` — path-agnostic |
| `Strategy` (`strategies/`) | Action selection | Same `DataPoint` protocol as live trading |
| `WideDataPoint` | Access protocol | Returned by `sim.get()`; implements `DataPoint` interface |
| `FullData` | Historical views | Read-only interface over same `df_with_indicators.pkl`; used for NN training and visualization, not simulation |

### Trainer integration pattern

```python
# trainer.py — parallel_simulate()
def simulate_range(pair, begin_ts, end_ts, step_min, thread_id):
    sim = SimulationData(pair, begin_ts, end_ts, step_min)
    robot = TrainRobot(pair)
    while not sim.is_end():
        point = sim.get()
        signal = signal_manager.check(point)
        action = strategy.select_action(point)
        robot.step(point, action)
        sim.next()
    return robot.get_results(thread_id)
```

---

## 11. Migration from v1 DataIterator

### What changed

| Aspect | v1 DataIterator | v2 SimulationData |
|--------|-----------------|-------------------|
| **Storage** | Per-timestamp dirs: `data/{pair}/{ts}/ohlc.pkl` | Single file: `df_with_indicators.pkl` |
| **Load pattern** | Per-step `pickle.load` from disk | Once at init via `pd.read_pickle` |
| **Return type** | `Data` object (old monolith) | `WideDataPoint` (DataPoint protocol) |
| **Access method** | `data.get_cur_price(col, shift, tf)` | `point.get(col, tf, shift)` |
| **Column names** | Unprefixed: `"rsi"`, `"close"` | TF-prefixed: `"5_rsi_14"`, `"5_close"` |
| **Timeframes** | Hardcoded `[1,3,5,15,60,240]` | Config-driven from `candles_config.yaml` |
| **Shift semantics** | Row offset in per-tf DataFrame | Nth **closed** candle using `{tf}_is_closed` filter |
| **Progress** | `get_pos(ts) -> float` | `sim._idx / sim.steps` |
| **Reset to start** | `begin()` method | Re-create `SimulationData` or `_idx = 0` |
| **Legacy files** | `auto_levels.pkl`, `metadata.pkl` per timestamp | Not used; levels managed by `Levels` class |

### Migration mapping

```python
# v1
iterator = DataIterator(pair, begin, end, step_minutes)
while not iterator.is_end():
    data = iterator.get()
    price = data.get_cur_price("close", 0, 15)
    rsi   = data.get_cur_price("rsi",   1, 15)
    iterator.next()

# v2
sim = SimulationData(pair, begin, end, step_min=step_minutes)
while not sim.is_end():
    point = sim.get()
    price = point.get("close",  tf=15, shift=0)
    rsi   = point.get("rsi_14", tf=15, shift=1)
    sim.next()
```

### v1 file paths (legacy, no longer written)

```
data/{pair}/{timestamp}/ohlc.pkl        ← deprecated
data/{pair}/{timestamp}/auto_levels.pkl ← deprecated
data/{pair}/{timestamp}/metadata.pkl    ← deprecated
```

These files are no longer created. If present from a v1 run, they are ignored by v2 components.

---

## 12. Summary Table

| Aspect | Value/Details |
|--------|---------------|
| **Class** | `SimulationData` |
| **File Location** | `data.py` |
| **Primary Use** | Historical replay for backtesting and strategy training |
| **Key Methods** | `get()` → `WideDataPoint`, `next()`, `is_end()`, `steps` |
| **Source File** | `{root_folder}/{pair}/df_with_indicators.pkl` |
| **Load Cost** | O(file_size) once at init; O(1) per step thereafter |
| **Time Complexity** | O(1) per step (`get()`, `next()`, `is_end()`) |
| **Thread Safety** | Not thread-safe; use one `SimulationData` per thread |
| **Backward Compat** | Replaces `DataIterator`; not drop-in compatible (API changed) |
| **Config Dependency** | `candles_config.yaml` (active timeframes) |
