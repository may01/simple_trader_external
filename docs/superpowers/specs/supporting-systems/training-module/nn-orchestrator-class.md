# NNOrchestrator Class Specification

**Version:** 2.0 — New class introduced as part of Trainer decomposition
**Class:** `NNOrchestrator`
**File:** `nn_orchestrator.py`
**Purpose:** Drive the neural-network pipeline (`group_nn`, `train_nn`, `simulate_nn`) using NN feature/target columns produced by `DataPreparer`.

---
IMPORTANT: IMPLEMENT ONLY THE INTERFACE OF THIS CLASS WITH STUBS!!!!
---

## 1. Class Overview

`NNOrchestrator` consolidates the three NN-pipeline methods previously hung off `Trainer` into a single class. It depends on:

- **`FullData`** from Data Module v2.0 — read-only per-tf views over `df_with_indicators.pkl`. NN features (`nn_*`) and forward-looking targets (`nn_tgt_*`) are columns in the wide DataFrame.
- **`NN` class** (existing) — owns the model architecture, training loop, weight persistence, and batch inference.

The orchestrator does not implement neural-network math. It (a) extracts feature/target pairs from `FullData`, (b) buckets them by classification, (c) feeds each bucket to an `NN` instance for training, and (d) runs trained models in batch mode for simulation.

---

## 2. Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `pair` | `str` | Trading pair. |
| `trainer` | `Trainer` | Injected reference (env/config). |
| `nn_folder` | `str` | Output folder for NN models and grouped data. |
| `full` | `FullData` | Lazy-initialized read view over `df_with_indicators.pkl`. |
| `group_size` | `int` | Points per grouped pickle file (default 5000). |

---

## 3. Constructor

### `__init__(pair: str, trainer: Trainer, group_size: int = 5000)`

**Behavior:**
1. Store inputs.
2. Compute `nn_folder = nn_folder_local(pair)`; create if absent.
3. Defer `FullData` instantiation to first use (`_full()`).

---

## 4. Methods

### 4.1 `group(class_type: int) -> None`

**Purpose:** Group NN feature/target rows by classification value and persist as `nn_group_*.pkl`.

**Behavior:**
1. `df = self._full().get(tf=1)` — one row per closed 1-min candle with NN feature/target columns.
   - For multi-tf NN inputs, also fetch `self._full().get(tf=tf_n)` views and align by timestamp.
2. Iterate rows in chronological order.
3. For each row:
   - Read the classification value at the `class_type` column (e.g., `1_class_big`).
   - Initialize `clsfd_points[cls] = [[], [], [], [], [], []]` on first sight of `cls`. Slots: `[inputs_per_tf, targets, timestamp, classification, atr_at_ts, metadata]`.
   - Append row values to the appropriate buckets.
4. When a bucket reaches `self.group_size` (or iteration finishes):
   - Optionally shuffle (env `SHUFFLE_GROUPED_NN_DATA=1`).
   - Pickle to `{nn_folder}/nn_group_{class_type}_{cls}_{num_group}.pkl`.
   - Reset the bucket.
5. Log totals per class.

**Preconditions:**
- `df_with_indicators.pkl` exists and contains the required `nn_*` columns.

**Postconditions:**
- One or more `nn_group_*.pkl` files exist per classification.

---

### 4.2 `train() -> None`

**Purpose:** Train one `NN` per `(class_type, cls, tf_type, target_type)` permutation.

**Behavior:**
1. Read configuration:
   - `class_type` from `NN_CLS` env (default `NN_POINT_CLASS_BIG`).
   - `target_type` from `NN_TGT`.
   - `tf_type` from `NN_TYPE`.
2. Enumerate `cls` values via `data_item.get_classification_permutation()`.
3. For each `cls`:
   ```python
   nn = NN(self.pair, class_type, cls, tf_type, target_type, nn_history=8)
   start = time.time()
   nn.train(data_group=1)
   log(f"trained cls={cls} in {time.time() - start:.1f}s")
   ```
4. `NN.train()` is expected to load its grouped pickle, build the model, fit, and persist weights — owned entirely by the `NN` class.

**Preconditions:**
- `group()` has been run for the configured `class_type`.
- `NN_CLS`, `NN_TGT`, `NN_TYPE` env vars are set.

**Postconditions:**
- Trained model weights exist on disk per `(class_type, cls, tf_type, target_type)`.

---

### 4.3 `simulate() -> None`

**Purpose:** Run trained NN models in batch over the test set and aggregate probability predictions.

**Behavior:**
1. `df_long = []`
2. For each NN configuration `(target_type, atr_tf, nn_type)` defined in env / config:
   - For each `cls`:
     - `nn = NN(self.pair, class_type, cls, tf_type=nn_type, target_type=target_type)`
     - `nn.load_model()`
     - `data = nn.get_group(1)` — loads grouped test pickle.
     - If `data` is empty, skip.
     - `outputs = nn.run_batch(data)` — shape `(n_samples, n_classes)`.
     - For each output row:
       - Append long/short probabilities.
       - Compute `argmax` prediction.
       - Look up timestamp-specific ATR from `FullData`.
     - Save `nn_simulation_cls_{class_type}_{cls}_{target_type}_{nn_type}.pkl`.
3. `pd.concat(df_long, axis=0)` and group by timestamp:
   - Sum long/short probabilities.
   - Average across configurations.
4. Save `{nn_folder}/nn_simulation_cls_big_tf.pkl`.

**Postconditions:**
- Per-class probability dataframes persisted.
- Combined aggregate dataframe persisted for downstream strategy integration.

---

### 4.4 `_full() -> FullData`

**Purpose:** Lazy-init the `FullData` view.

```python
def _full(self) -> FullData:
    if self.full is None:
        df = pd.read_pickle(f"{root_folder(self.pair)}/df_with_indicators.pkl")
        self.full = FullData(df)
    return self.full
```

---

## 5. Data Flow

```
df_with_indicators.pkl
   │ (NN feature columns + nn_tgt_* targets + classification columns)
   ▼
FullData.get(tf=N)[nn_feature_cols + nn_tgt_cols + class_cols]
   │
   ▼ NNOrchestrator.group(class_type)
nn_group_{class_type}_{cls}_{n}.pkl  (one per (class, group_index))
   │
   ▼ NNOrchestrator.train()
NN model weight files (one per (class_type, cls, tf_type, target_type))
   │
   ▼ NNOrchestrator.simulate()
nn_simulation_*.pkl  (probability dataframes per config)
   │
   ▼ aggregate
nn_simulation_cls_big_tf.pkl  (combined for strategy consumption)
```

---

## 6. Configuration Surface

| Env Var | Purpose |
|---------|---------|
| `NN_CLS` | Classification dimension (default `NN_POINT_CLASS_BIG`). |
| `NN_TGT` | Target type to train (e.g., `08_NO_DIP`). |
| `NN_TYPE` | Timeframe type for NN inputs (e.g., `1H`, `4H`). |
| `SHUFFLE_GROUPED_NN_DATA` | If `1`, shuffle each group bucket before save. |

Future improvement: replace these scattered env reads with an `NNConfig` dataclass passed to the constructor — out of scope for v2.0 first cut.

---

## 7. Error Handling

| Condition | Behavior |
|-----------|----------|
| `df_with_indicators.pkl` missing | `FileNotFoundError` with hint to run `generate_full_ohlc`. |
| `nn_group_*.pkl` missing during `train()` | `FileNotFoundError` with hint to run `group_nn`. |
| Trained weights missing during `simulate()` | `FileNotFoundError` with hint to run `nn_train`. |
| `NN.train()` exception | Logged with `(cls, target_type, tf_type)`; remaining `cls` values still attempt training. |
| Required NN columns missing in `df_with_indicators.pkl` | `KeyError` listing missing columns; suggests `indicators_config.yaml` audit. |

---

## 8. Testing Notes

- **Group correctness:** synthetic `FullData` with 10k rows split across 3 class values, `group_size=1000`, `SHUFFLE_GROUPED_NN_DATA=0` → assert deterministic chunking and chronological order within chunks.
- **Train smoke test:** mock `NN.train` to record `(cls, target_type, tf_type)` arguments → assert the permutation loop covers the expected combinations exactly once.
- **Simulate aggregation:** two configurations producing known probability outputs → assert `nn_simulation_cls_big_tf.pkl` has correctly averaged values per timestamp.

---

## 9. Constraints and Invariants

- **Read-only on the wide DataFrame.** All access flows through `FullData`.
- **Models are the `NN` class's responsibility.** Orchestrator never reaches into model internals.
- **Grouped files are append-safe and idempotent.** Re-running `group()` with the same inputs overwrites the same files deterministically (modulo shuffle).
- **NN target columns must exist** in `df_with_indicators.pkl` — produced by `DataPreparer`'s `nn_targets` field group.
- **Live path never invokes `NNOrchestrator`** — it is purely an offline pipeline. Live NN inference happens inside `LiveData`/`Strategy` using already-trained models.
