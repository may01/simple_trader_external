# Task 04: NNDataset (Modular Tensor Cache)

**Phase:** 11 — NN Module  
**Depends on:** Task 02 (NNModelSpec / TargetSpec / GroupingSpec), Task 03 (nn_features), profit-labels pipeline (phase 13 task-07)  
**Produces:** `nn/nn_dataset.py`

---

## Goal
Define the **modular, content-addressed data format** that NN training and inference consume. `NNDataset` materialises a prepared wide DataFrame into per-timeframe feature tensors and a multi-target tensor **once** per `(feature-set, target-set, history, split)`, caches them on disk under `datasets/{dataset_hash}/`, and serves them back with zero re-derivation. The agentic search loop reloads data hundreds of times across trials; a format that recomputes features or reparses pickles every trial is too slow, so the cache is keyed by a content hash and reused across every spec that resolves to the same config.

This is the replacement for the legacy per-point pickle generator (`DataPointGenerator`): there is no per-candle "data point" object in the training path; training operates on materialised `.npy` tensors. Targets are **read from profit-label columns**, not classified by the NN.

## Context
The old per-timestamp data-point generation produced one `WideDataPoint` pickle per candle and re-derived features on every load. `NNDataset` collapses that into three persisted concerns:

1. **NN features** — engineered indicators (`{tf}_logret`, `{tf}_{ind}_z`, `{tf}_range_atr`, body/wick, slopes, vol_regime, cyclical time, cross-TF) computed once during `DataPreparer.prepare()` (the `nn_features` step, task-03) and persisted into `df_with_indicators.pkl`. `NNDataset` only **reads** them.
2. **Materialised tensors** — per-TF feature blocks (`X_{tf}.npy`) and a multi-target tensor (`y.npy`), built once and cached by content hash.
3. **Manifest** — a JSON sidecar describing column order, normalisation stats, target encodings, row index, and the source content-hash, so a dataset loads and validates without re-deriving anything.

**Targets come from profit-labels, not the NN.** `DataPreparer._compute_profit_labels()` (`main/training/data_preparer.py:348`, via `indicators/labels.py:add_profit_labels` / `add_profit_strict_labels`) already wrote, per `labels:` config spec, the binary outcome columns into `df_with_indicators.pkl`:
- `{tf}_plong_n{n}_m{m}_x{x}` / `{tf}_pshort_n{n}_m{m}_x{x}` (e.g. `15_plong_n1_m1_x0p4`),
- strict `{tf}_pslong_..._l{l}_y{y}` / `{tf}_psshort_...`.

Each is binary (1 = target `m×atr_ma` reached before stop `x×atr_ma` within `n` tf-candles; long enters at `1_low`, short at `1_high`; NaN while warming up or when the forward window is incomplete). A `direction` target reads the matching long+short columns and derives 3-class; a `label` target reads one column directly; a `regression` target is computed from price (forward `logret`), not from a label column.

The dataset emits **one row per 1-minute timestamp** (matching legacy `WideDataPoint` cadence). The **latest** feature value at each timestamp is the current forming (not-yet-closed) candle (`WideDataPoint shift=0`); historical lookback within `history_points` uses **closed** candles only (`shift≥1`).

## Files
- Create: `nn/nn_dataset.py`

## Interface

```python
class NNDataset:
    @classmethod
    def build(cls, df: pd.DataFrame, data_attributes: "DataAttributes",
              spec: "NNModelSpec") -> "NNDataset": ...
    @classmethod
    def load(cls, dataset_hash: str) -> "NNDataset": ...
    def tensors(self) -> tuple[np.ndarray, np.ndarray]: ...      # (X_multi_tf, y)
    def split(self, name: str) -> "NNDataset": ...               # "train" | "val" | "holdout"
    def groups(self, grouping: "GroupingSpec") -> list[str]: ...
    def group(self, group_key: str) -> "NNDataset": ...
    # attributes / properties
    manifest: dict          # parsed manifest.json (see schema below)
    dataset_hash: str       # content hash; also the cache directory name
    cached: bool            # True if build() reused an existing cache dir
```

- **`build(cls, df, data_attributes, spec)`** — materialise + cache tensors from a prepared wide `df`. Resolves `dataset_hash` from `(source content-hash, feature set, target set, history, split)`; if the cache dir exists and its manifest's `source` content-hash matches, loads it (`cached=True`) instead of rebuilding. Otherwise: validates every `feature_col` exists in `df` (missing → `ValueError` naming it); builds per-TF feature blocks over `history_points` (latest = forming candle, lookback = closed candles); reads target columns per `TargetSpec` (profit-labels for direction/label, price-derived logret for regression); drops rows with any NaN feature or NaN target; computes normalisation stats (`mean`/`std` per feature column) **on the train split only**; writes pre-normalised `X_{tf}.npy`, `y.npy`, `index.npy`, `splits.json`, `manifest.json`. Empty after drops → `ValueError("no usable rows")`.
- **`load(cls, dataset_hash)`** — load a cached dataset by hash; parse and validate `manifest.json`; a missing `.npy`/manifest is a corrupt dir → treated as cache miss (caller rebuilds). Stale source (manifest `source` content-hash no longer matches the live source) → raise / force rebuild rather than silently serving old tensors.
- **`tensors()`** — return `(X, y)`. `X` concatenates the configured timeframes' feature blocks into one multi-TF input `(rows, history_points, sum_tf n_features)`; `y` is `(rows, total_target_width)`. Both load directly into `torch.from_numpy` with no transform (tensors are already z-scored).
- **`split(name)`** — return a time-ordered row-range view (`"train"`/`"val"`/`"holdout"`) from `splits.json`; never shuffles before splitting.
- **`groups(grouping)`** — return the group keys for a `GroupingSpec` (routing indicator column read off the source frame); `grouping.mode="single"` → one group containing all rows.
- **`group(group_key)`** — return a row-subset view for one class/regime.

### Storage layout — `datasets/{dataset_hash}/`
```
datasets/{dataset_hash}/
├── manifest.json          # schema, stats, encodings, provenance
├── X_{tf}.npy             # per-TF feature tensor: (rows, history_points, n_features) — NORMALISED
├── y.npy                  # multi-target tensor: (rows, total_target_width)
├── index.npy              # DataFrame index (timestamps) per row
└── splits.json            # train / val / holdout row ranges (time-ordered)
```
One `X_{tf}.npy` block per timeframe (modular): a different TF subset can be assembled by `tensors()` without recompute. Tensors are written **already z-scored** (`(x - mean) / std` per feature column) so inference loads them ready-to-feed.

### manifest.json schema (verbatim from spec)
```json
{
  "dataset_hash": "…",
  "source": "df_with_indicators.pkl@<content-hash>",
  "timeframes": [15, 60],
  "history_points": 32,
  "feature_cols": { "15": ["15_logret", "15_rsi_z", ...], "60": [...] },
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
The manifest additionally records the **dropped-row count** (NaN feature/target/horizon drops) and the same `normalization` stats are reused verbatim by `NNOrchestrator.run_inference()` so batch inference reproduces the training scale exactly.

### Target sourcing
- `kind="direction"` — `TargetSpec` selects a profit-label spec by `(label_tf, n=horizon, label_m, label_x, strict)`; reads the matching `{tf}_plong_*`/`{tf}_pshort_*` (or strict `pslong`/`psshort`) columns → 3-class: `up` if long profitable and short not, `down` if short profitable, else `neutral` → `{up:0, neutral:1, down:2}`.
- `kind="label"` — references a single profit-label column directly → binary (profitable vs not).
- `kind="regression"` — computed from price: forward `logret` over horizon `N`, continuous.
- `horizons=[h1, h2, …]` — materialised once per horizon; for direction/label, horizon `hk` selects the profit-label spec whose `n = hk` (the matching `labels:` config entry must exist); for regression, `hk` sets the lookahead. Each horizon is its own column block and its own model head.
- **Default:** a single direction target from the primary profit-label spec at the strategy's primary horizon. Multiple targets per model are supported.

## Key Constraints
- **Content-addressed:** `dataset_hash` derives from `(source content-hash, feature set, target set, history, split)`. Identical config reuses the cache dir; a changed config builds a new directory. A cache hit re-verifies the manifest `source` content-hash; a stale source forces a rebuild rather than silently serving old tensors. Corrupt/partial dir (missing `.npy` or manifest) → treated as cache miss and rebuilt.
- **Normalisation stats on the TRAIN split only** — no val/holdout leakage. Tensors are written pre-normalised; the manifest carries the same mean/std so live inference reproduces the exact training scale.
- **Time-ordered splits** — one row per 1-min timestamp; never shuffle before splitting. Lookback within `history_points` uses **closed** candles only; the latest value is the forming candle.
- **NaN feature/target rows dropped at build** (not filled); the dropped count is recorded in the manifest. Rows with incomplete forward windows already carry NaN profit labels (pipeline-produced) and are dropped, as are rows past the dataset end for regression. Empty after drops → `ValueError("no usable rows")`.
- **Read-only consumer:** `NNDataset` reads `df_with_indicators.pkl` (feature + profit-label columns) and `DataAttributes`; it never computes direction labels itself and never writes back to the source frame.

## Verification
```bash
docker compose run --rm nn-train python3 -c "import pandas as pd; from nn.nn_dataset import NNDataset; from nn.nn_model_spec import NNModelSpec; from indicators import DataAttributes; from helpers import wide_df_path, data_attributes_path; spec=NNModelSpec.from_yaml('configs/nn_spec.yaml'); ds=NNDataset.build(pd.read_pickle(wide_df_path()), DataAttributes.load(data_attributes_path()), spec); X,y=ds.tensors(); print(ds.dataset_hash[:8], X.shape, y.shape, ds.manifest['rows'])"
```

## Commit
`feat(nn): NNDataset content-addressed tensor cache with manifest + splits`
