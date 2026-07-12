# NNDataset & NN Feature Specification

**File:** `nn/nn_dataset.py`, `data_layer/nn_features.py`
**Purpose:** Define the **modular data format** that NN training and inference consume, the **NN-specific engineered indicators** that feed it, and the **target labelling** that supervises it. Designed for fast reuse across the many trials of the agentic training loop.

---

## 1. Overview

NN training in a search loop reloads data hundreds of times. A format that recomputes features or reparses pickles on every trial is too slow. `NNDataset` solves this by separating three concerns:

1. **NN features** — engineered indicators computed once during data preparation (`nn_features` step) and persisted into the indicator DataFrame.
2. **Materialised tensors** — per-timeframe feature tensors and a multi-target tensor, built once per `(feature-set, target-set)` and cached on disk keyed by a content hash.
3. **Manifest** — a JSON sidecar describing column order, normalisation stats, target encodings, row index, and the producing spec hash, so a dataset can be loaded and validated without re-deriving anything.

---

## 2. Modular Data Format (item 5)

A materialised dataset lives under `datasets/{dataset_hash}/`:

```
datasets/{dataset_hash}/
├── manifest.json          # schema, stats, encodings, provenance
├── X_{tf}.npy             # per-TF feature tensor: (rows, history_points, n_features) — stores NORMALISED values
├── y.npy                  # multi-target tensor: (rows, total_target_width)
├── index.npy              # DataFrame index (timestamps) per row
└── splits.json            # train / val / holdout row ranges (time-ordered)
```

### manifest.json

```json
{
  "dataset_hash": "…",
  "source": "df_with_indicators.pkl@<content-hash>",
  "timeframes": [15, 60],
  "history_points": 32,
  "feature_cols": { "15": ["15_logret", "15_rsi_14", "15_ema_7_minus_close", "15_macd_12_26_9_slope", ...], "60": [...] },
  "normalization": { "15_logret": {"mean": 0.0, "std": 0.0123}, ... },
  "targets": [
    {"name": "dir15n1", "kind": "direction", "horizons": [1],
     "source": {"long": "15_plong_n1_m1_x0.4", "short": "15_pshort_n1_m1_x0.4", "strict": false},
     "out_columns": ["nn_res_dir15n1_prob_up", "nn_res_dir15n1_prob_neutral", "nn_res_dir15n1_prob_down"],
     "encoding": {"up":0,"neutral":1,"down":2}},
    {"name": "ret60", "kind": "regression", "horizons": [1], "transform": "logret",
     "out_columns": ["nn_res_ret60"]}
  ],
  "rows": 41234,
  "split": {"strategy": "time_holdout", "train": 0.6, "val": 0.2, "holdout": 0.2}
}
```

**Key properties:**
- **Tensor-native:** `.npy` arrays load directly into `torch.from_numpy` with zero parsing.
- **Pre-normalised tensors:** `X_{tf}.npy` is written already z-scored (`(x - mean) / std` per feature column), so training/eval load it ready-to-feed with no transform step.
- **Self-describing:** the manifest carries the same normalisation stats (mean/std per column), so `run_inference()` applies them to raw live features and reproduces the training scale exactly. Stats are computed on the **train split only** (no val/holdout leakage).
- **Content-addressed:** `dataset_hash` derives from `(source content-hash, feature set, history, target set, split)`. Identical configs reuse the cache; changed configs build a new directory.
- **Modular by TF:** each timeframe is stored as a separate block (`X_{tf}.npy`); `tensors()` concatenates the configured timeframes into one multi-TF input. Storing blocks separately lets a different timeframe subset be assembled without recompute.

### `NNDataset` class

```python
class NNDataset:
    @classmethod
    def build(cls, df, data_attributes, spec) -> "NNDataset": ...   # materialise + cache
    @classmethod
    def load(cls, dataset_hash) -> "NNDataset": ...                 # load cached
    def tensors(self) -> tuple[np.ndarray, np.ndarray]: ...         # X (multi-TF), y — materialised (mmap-loaded)
    def torch_dataset(self) -> "Dataset": ...                       # LAZY mmap-backed map-style dataset (training)
    def labels(self) -> np.ndarray: ...                             # y rows only (cheap; for class weights)
    def split(self, name: str) -> "NNDataset": ...                  # train/val/holdout view
    def groups(self, grouping) -> list[str]: ...                    # group keys per GroupingSpec
    def group(self, group_key: str) -> "NNDataset": ...             # row-subset view for one class/regime
    @property
    def manifest(self) -> dict: ...
```

`X` concatenates all configured timeframes' feature blocks (model input is multi-TF). `groups()`/`group()` partition rows by the spec's `GroupingSpec` (the routing indicator column is read off the source frame); `grouping.mode="single"` yields one group containing all rows.

Rows with NaN features or NaN targets are dropped at build time (not filled), and the dropped count is recorded in the manifest.

#### Lazy loading — host RAM O(batch), not O(rows)

`tensors()` materialises the full `(rows, history, sum_tf features)` array, so the training load path does **not** use it (a 3-year set is tens of GB, copied several times: load → concat → torch-tensor). Training instead consumes `torch_dataset()` — a **map-style, mmap-backed** dataset:

- Each `X_{tf}.npy` / `y.npy` is opened with `np.load(mmap_mode='r')`.
- `__getitem__(i)` reads **one** row's `(history, n_features_tf)` block from each TF mmap and concatenates them along the feature axis in **`manifest['timeframes']` declaration order** (never sorted — a `[60, 15]` spec must not swap feature channels), yielding `(history, sum_tf features)` plus that row's `y`. Tensors are already normalised float32 on disk, so no transform happens on access.
- A `DataLoader` over this keeps host RAM at **O(batch + OS page cache)**, independent of row count — the complement to the minibatching that bounds GPU memory (see `nnmodel-class.md` §5.2).
- `labels()` opens only `y.npy` (small: `rows × target_width`) so global balanced class weights are computed without materialising any `X_{tf}.npy`.
- `tensors()` retains its signature/output (now mmap-loaded) for inference parity, small datasets, and tests.

Shuffle (`spec.shuffle_train`) random-accesses mmap rows — fine on SSD/NVMe; `num_workers=0` by default (memmaps pickle by path, so `NUM_WORKERS>0` is a valid later opt-in to overlap I/O).

---

## 3. NN-Specific Indicators (item 9)

The `nn_features` step runs during `DataPreparer.prepare()` after base indicators, writing `{tf}_`-prefixed columns. Two families: (a) explicit indicator **groups** — Group 1 raw indicators, Group 2 indicator differences, Group 3 indicator slopes — and (b) orthogonal engineered features (returns, candle ratios, regime, cyclical, cross-TF). **Normalisation is global + outlier-robust:** these columns are written raw; the single z-score is the dataset-level train-split standardisation computed by `NNDataset` — per-column `{q01,q99,mean,std}` estimated on **winsorised** values, applied as clip-to-`[q01,q99]` → `(x-mean)/std` → clamp `[-4,+4]` (written into `X_{tf}.npy` and the manifest stats). No rolling `_z` columns are produced. (The legacy `DataAttributes.compute_nn_stats` path that previously owned these stats was removed — see DECISIONS-LOG D13.)

| Feature | Column | Definition |
|---------|--------|------------|
| Group 1 — raw indicators | existing `{tf}_<ind>` | selected straight into `feature_cols`; globally z-scored (RSI/CCI bases, `rsi_ma*_diff`, `cci_diff`, `atr_14_ma_5`, `natr_14_ma_5`, `*_diff_prc_rm_6*`, MACD/MACD-signal lines) |
| Group 2 — indicator difference | `{tf}_{a}_minus_{b}` | `a - b` for `bb_*_20_2 − close`, `ema_{7..100} − close`, `vol_ma_20 − volume`, all `ema` pairs (shorter − longer), `atr_14_ma_5 − atr_14`, `natr_14_ma_5 − natr_14` |
| Group 3 — indicator slope | `{tf}_{ind}_slope` | linear slope over short window for MACD/MACD-signal (12_26_9 & 5_13_9), `ema_{7..100}`, `adx_14`, `rsi_ma8/12/24`, `cci_14_ma_5` |
| Log return | `{tf}_logret` | `log(close_t / close_{t-1})` |
| ATR-normalised range | `{tf}_range_atr` | `(high - low) / ATR` |
| Body ratio | `{tf}_body_ratio` | `(close - open) / (high - low)` |
| Upper/lower wick | `{tf}_wick_up`, `{tf}_wick_dn` | wick length / candle range |
| Volatility regime | `{tf}_vol_regime` | bucketed rolling ATR percentile |
| Session encoding | `{tf}_sin_tod`, `{tf}_cos_tod` | cyclical time-of-day (and day-of-week) |
| Cross-TF alignment | `{tf}_align_{other}` | sign agreement of trend between this TF and a higher TF |

`nn_features` is configured via the `indicators_config.yaml` `nn` section (windows, which features on). The dataset emits **one row per 1-minute timestamp** (`index.npy` carries every 1-min stamp), matching the legacy `WideDataPoint` cadence. The **latest** feature values at each timestamp represent the **current forming (not-yet-closed) candle** of each timeframe — equivalent to `WideDataPoint` `shift=0`. Historical lookback values within `history_points` use **closed** candles (`WideDataPoint` `shift≥1`). Warmup rows yield NaN and are dropped at dataset build.

---

## 4. Target Labelling (item 6, resolves README "Unresolved")

Targets are declared in the `NNModelSpec` (`TargetSpec` list) and materialised into `y.npy` at dataset build. **The NN module does not compute direction labels itself** — it reads the profit-label columns produced by the phase-13 profit-labels pipeline (`task-07-profit-labels-pipeline.md`).

### Source: profit-labels pipeline

`DataPreparer._compute_profit_labels()` writes, per `labels:` config spec, the columns:
- `{tf}_plong_n{n}_m{m}_x{x}` / `{tf}_pshort_n{n}_m{m}_x{x}` — long/short profit outcome,
- strict `{tf}_pslong_*` / `{tf}_psshort_*`.

Each is a **binary** outcome for a candidate entry at that row: target `m×atr_ma` reached before stop `x×atr_ma` within `n` tf-candles (long enters at `1_low`, short at `1_high`). These columns already live in `df_with_indicators.pkl` before NN dataset build.

### Direction class (`kind="direction"`)
- A `TargetSpec` selects a profit-label spec by `(label_tf, n=horizon, label_m, label_x, strict)`.
- Reads the matching long + short columns and derives 3-class:
  - `up` if long profitable and short not, `down` if short profitable, else `neutral` → `{up:0, neutral:1, down:2}`.

### Binary label (`kind="label"`)
- References a single profit-label column directly → binary target (profitable vs not), single sigmoid output.

### Binary direction — single action vs. rest (`kind="direction_binary"`)
- One-vs-rest head emitting `(prob_{side}, prob_other)` for a single `side: "long" | "short"`.
- Reads **one** profit-label column — `{tf}_plong_*` for `side="long"`, `{tf}_pshort_*` for `side="short"` (strict → `pslong`/`psshort`) — selected by `(label_tf, n=horizon, label_m, label_x, strict)`.
- Positive class = column `== 1` (action profitable), `other` = column `== 0` → width-2 one-hot `{<side>:0, other:1}`, softmax / cross-entropy. NaN source → NaN row, dropped at build.
- Differs from `kind="label"`: `direction_binary` is a 2-value softmax so `prob_{side} + prob_other = 1`, matching the 3-class direction head's one-hot shape for downstream consumers; `kind="label"` is a single sigmoid scalar.

### Regression (`kind="regression"`)
- Computed from price (not a profit label): transformed future move (`logret` over horizon `N`), continuous.

### Multi-horizon (`horizons=[h1, h2, …]`)
- The target is materialised once per horizon. For direction/label, horizon `hk` selects the profit-label spec whose `n = hk` (the matching `labels:` config entry must exist); for regression, `hk` sets the lookahead. Each horizon becomes its own column block (`…_h{hk}_…`) and its own model head.

The manifest records, per target, the exact source columns, horizon(s), strictness, and class encoding so labels are reproducible and inference output columns map back unambiguously. **Multiple targets per model are supported** — e.g. several `(tf, n, m, x)` profit-label specs as separate direction heads. **Default:** a single direction target from the primary profit-label spec at the strategy's primary horizon.

Rows whose forward window is incomplete already carry NaN profit labels (pipeline-produced) and are dropped at build, as are rows past the dataset end for regression targets.

---

## 5. State & Error Handling

- `build()` validates that every `feature_col` exists in the source DataFrame; missing column → `ValueError` naming it.
- A cache hit verifies `source content-hash` in the manifest; a stale source (hash mismatch) forces a rebuild rather than silently serving old tensors.
- Corrupt/partial dataset directory (missing `.npy` or manifest) → treated as cache miss and rebuilt.
- Empty dataset after NaN/horizon drops → `ValueError("no usable rows")`.

---

## 6. Notes

- `NNDataset` replaces the legacy per-point pickle generator. There is no per-candle "data point" object in the training path; training operates on materialised tensors.
- Time-ordered splits prevent look-ahead leakage; never shuffle before splitting.
- The same manifest normalisation stats are reused by `NNOrchestrator.run_inference()` so batch inference matches training exactly.
