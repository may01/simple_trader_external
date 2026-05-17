# Trainer Class Specification

**Version:** 2.0 — Thin orchestrator after class decomposition
**Class:** `Trainer`
**File:** `trainer.py`
**Purpose:** Dispatch `RUN_TYPE` to the appropriate collaborator class and manage cross-pipeline metadata.

---

## 1. Class Overview

In v2.0 the `Trainer` class is reduced to a thin orchestrator. It no longer contains data-loading, indicator-computation, simulation-loop, or NN-training logic. All of that work has been moved into specialized collaborators (`Graber`, `DataPreparer`, `SimulationOrchestrator`, `NNOrchestrator`, `LiveDataCollector`). `Trainer`'s only responsibilities are:

1. **RUN_TYPE dispatch** — read the env variable, construct the right collaborator, call it.
2. **Cross-pipeline metadata** — own and persist the `{begin_point, end_point, time_step}` dict that multiple pipelines read.
3. **Configuration surface** — expose `DATA_START`, `DATA_END`, `TRAINER_TIME_STEP`, `AVAIABLE_THREADS` as typed accessors so collaborators do not touch `os.environ`.

Trainer is expected to be under ~200 lines.

---

## 2. Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `pair` | `str` | Trading pair in `coin_base` format (instance-level). |
| `metadata` | `dict` | `{begin_point: int, end_point: int, time_step: int}`. Loaded from disk at init. |
| `aviable_threads` | `int` (class-level) | `int(os.environ["AVAIABLE_THREADS"])`. Cached at import time. |

Instance state beyond `pair` and `metadata` is intentionally minimal — collaborators hold their own state.

---

## 3. Constructor

### `__init__(pair: str)`

**Behavior:**
1. Store `pair`.
2. Call `load_metadata()` to populate `self.metadata` from disk (graceful default if file absent).
3. Log loaded metadata.

**Postconditions:** Instance is ready to dispatch any `RUN_TYPE`.

---

## 4. Methods

### 4.1 `run(run_type: str) -> None`

**Purpose:** Dispatch a `RUN_TYPE` to its collaborator.

**Behavior:**
```python
def run(self, run_type: str) -> None:
    if run_type == "grab_data":
        Graber(self.pair).grab_from_env()

    elif run_type == "generate_full_ohlc":
        df = DataPreparer(self.pair, trainer=self).prepare()
        self._update_metadata_from_df(df)
        self.save_metadata()

    elif run_type == "simulate":
        SimulationOrchestrator(self.pair, trainer=self).run()

    elif run_type == "group_nn":
        NNOrchestrator(self.pair, trainer=self).group(NN_POINT_CLASS_BIG)

    elif run_type == "nn_train":
        NNOrchestrator(self.pair, trainer=self).train()

    elif run_type == "simulate_nn":
        NNOrchestrator(self.pair, trainer=self).simulate()

    elif run_type == "collect_live":
        LiveDataCollector(self.pair).run()

    else:
        raise ValueError(f"Unknown RUN_TYPE: {run_type}")
```

**Notes:**
- A `RUN_TYPE` value not in the table above is an error in v2.0 — silent fall-through (the v1.0 pattern of independent `if` blocks) is replaced by explicit dispatch.
- `grab_data` and `generate_full_ohlc` are independent: `grab_data` writes `graber_data.pkl` to disk; `generate_full_ohlc` reads it as input. A user runs `grab_data` once per dataset, then can re-run `generate_full_ohlc` repeatedly (e.g. after changing `indicators_config.yaml`) without redownloading.
- Legacy RUN_TYPEs (`generate_data_points`, `generate_data_points_prediction`, `generate_nn_points`, `train`) are not accepted; their work is now done by `generate_full_ohlc`.

---

### 4.2 Metadata Methods

#### `save_metadata() -> None`
Pickle `self.metadata` to `{data_folder(pair)}/metadata.pkl`.

#### `load_metadata() -> None`
Read `{data_folder(pair)}/metadata.pkl` into `self.metadata`. If the file is absent or corrupt, retain default `{"begin_point": 0, "end_point": 0, "time_step": 0}` and log the condition.

#### `_update_metadata_from_df(df: pd.DataFrame) -> None`
After `DataPreparer.prepare()` completes, compute:
```python
self.metadata["begin_point"] = int(df.index.min().timestamp())
self.metadata["end_point"]   = int(df.index.max().timestamp())
self.metadata["time_step"]   = self.train_time_step()
```

---

### 4.3 Configuration Accessors

| Method | Returns | Source |
|--------|---------|--------|
| `train_begin_time()` | `int` (Unix seconds) | `int(os.environ["DATA_START"]) / 1000` |
| `train_end_time()` | `int` (Unix seconds) | `int(os.environ["DATA_END"]) / 1000` |
| `train_time_step()` | `int` (minutes) | `int(os.environ["TRAINER_TIME_STEP"])` |
| `data_graber_date_limits()` | `(datetime, datetime)` | derived from `DATA_START`, `DATA_END` |
| `available_threads()` | `int` | `int(os.environ["AVAIABLE_THREADS"])` |

These are the only places `os.environ` is read for training-period configuration. Collaborators must receive these values via `trainer=self` injection rather than reading env directly.

---

### 4.4 Query Methods

#### `time_points_qnt() -> int`
Estimate of total replay steps:
```python
return (self.metadata["end_point"] - self.metadata["begin_point"]) // (self.metadata["time_step"] * 60)
```

(The v1.0 `get_points_list()` is removed — it required a `DataIterator` walk to produce a list of timestamps from per-snapshot pickle files, which no longer exist. Consumers needing the full timestamp sequence should construct it from metadata and `pd.date_range`.)

---

## 5. State Management

```
__init__()              metadata = load_metadata()  (or defaults)
run("grab_data")
  └─ Graber             writes graber_data.pkl (no metadata change)
run("generate_full_ohlc")
  └─ DataPreparer       reads graber_data.pkl → writes df_with_indicators.pkl
  └─ Trainer            updates metadata.begin/end/step from df
  └─ Trainer            save_metadata()
run("simulate")
  └─ SimulationOrchestrator reads metadata via trainer accessors
                       (does not mutate metadata)
```

**Invariants:**
- `metadata` is only mutated inside `Trainer`.
- `metadata["end_point"] >= metadata["begin_point"]`.
- `metadata` is persisted after any RUN_TYPE that produced new prepared data.

---

## 6. Error Handling

| Condition | Behavior |
|-----------|----------|
| Unknown `run_type` | Raise `ValueError` (no silent skip). |
| Missing `graber_data.pkl` | `Graber` raises `FileNotFoundError`; `Trainer` propagates. |
| Missing `df_with_indicators.pkl` during `simulate` | `SimulationData` raises `FileNotFoundError`; `Trainer` propagates with a hint to run `generate_full_ohlc` first. |
| Corrupt `metadata.pkl` | `load_metadata` logs and retains defaults. |
| Env var unset | Raise `KeyError` on first access — fail fast at startup, not mid-run. |

---

## 7. Example main() Flow

```python
# trainer.py — entry point
if __name__ == "__main__":
    pair = os.environ["PAIR"]
    run_type = os.environ["RUN_TYPE"]
    trainer = Trainer(pair)
    trainer.run(run_type)
```

That is the entire public surface — one constructor call, one `run()` call.

---

## 8. Migration Notes from v1.0

| v1.0 method | v2.0 location |
|-------------|---------------|
| `generate_full_ohlc(graber)` | `Graber.build_base_dataframe()` + `DataPreparer.prepare()` |
| `generate_data_points(...)` (all 3 variants) | Removed. Indicator + NN-target enrichment is part of `DataPreparer.prepare()`. |
| `train()` | Removed. The skeleton had no real logic. |
| `simulate()` | `SimulationOrchestrator.run()` |
| `group_nn(class_type)` | `NNOrchestrator.group(class_type)` |
| `train_nn()` | `NNOrchestrator.train()` |
| `simulate_nn()` | `NNOrchestrator.simulate()` |
| `collect_live_data()` | `LiveDataCollector.run()` |
| `parallel_generate_data_points`, `parallel_simulate`, `parallel_batch_train`, `parallel_train_nn` | Encapsulated inside the relevant collaborator (no longer module-level helpers). |
| `get_nn_target`, `get_nn_target_near_level`, `get_regression_target` | Become `IndicatorField` subclasses owned by the data module. |
| `save_metadata`, `load_metadata`, `train_begin_time`, `train_end_time`, `train_time_step`, `data_graber_date_limits` | Remain on `Trainer`. |
| `get_points_list(max=0)` | Removed (see §4.4). |
