# Zone Selection Experiment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This plan follows **layer-first-planning**: Docker first, then each layer is interface → integration-test-RED → unit-tests-RED → implementation-GREEN, all verified inside Docker.

**Goal:** Build a read-only, notebook-driven experiment that learns per-higher-TF-candle price zones (entry + target + stop + R/R) from diff_prc-std action levels and trend indicators, validated on OOS.

**Architecture:** All reusable logic lives in a new importable package `notebooks/action_zones/azlib/` (pure, TDD-tested functions). Thin Jupyter notebooks orchestrate + plot by importing `azlib`. The experiment consumes the existing simple_trader wide DataFrame (`df_with_indicators.pkl`) **read-only** and writes every artifact to the mounted volume. No existing simple_trader code is modified until the final human-gated viewer-integration layer.

**Tech Stack:** Python 3.12, pandas, numpy, scikit-learn (regression/classification), scipy (parametric tail fit), matplotlib/plotly (charts), jupyterlab + papermill (notebook run/repro), pytest (TDD), Docker Compose.

**Source spec:** `external/docs/superpowers/specs/2026-07-18-zone-selection-design.md`

## Global Constraints

- **Read-only on existing code.** No edits to any existing simple_trader module until Layer 10, which is human-gated (spec §Restrictions line 173). Layers 0–9 create new files only.
- **Artifacts to volume only.** Charts, reports, results files, zoned datasets go under `/trader_data_long/train/<dataset>_<pair>/action_zones/…` — NEVER into the worktree (container writes root-owned files that block merges).
- **Notebooks in worktree.** `notebooks/action_zones/` (code); artifacts to volume (above).
- **Stats frozen on train.** All means/stds/ECDFs/regression params fit on the 2y train set, serialized, and applied unchanged to OOS.
- **TFs = {15, 60, 240}**, matched indicator TF = label TF. Long and short handled separately.
- **diff_prc is percent (×100)** — price conversion uses `prev * (1 + level/100)`.
- **Fee is a parameter**, default `EXCHANGE_FEE=0.001` (from the dataset env).
- **Datasets:** train = `configs/nn_train_dataset_2y.env` (DATA_SET_NAME=2y); OOS = `configs/oos2m_dataset.env` (DATA_SET_NAME=oos2m). Both ROOT_FOLDER=long, PAIR=link_usdt, on `simple_trader_vol_long`.
- **Label params** (n, m, x, l, y per TF) are experiment config set once in Layer 1 (see Task 1.2). Strict labels via `indicators.labels.add_profit_strict_labels`; non-strict via `add_profit_labels` (imported, not modified).
- **Branch:** work on a dedicated branch cut from `experimental_imp_2`; merge back into it. Never commit/push without explicit user confirmation.

---

## Docker Entry Points (Layer 0 — first, before any layer)

New files only: `docker/Dockerfile.experiment`, `docker-compose.experiment.yml`. The `experiment` service is `FROM simple_trader` + `pip install jupyterlab papermill scikit-learn scipy` (talib/pandas/numpy already in base). Mounts the code dir and `simple_trader_vol_long` (RO for the wide df; artifacts written under a subdir the service owns).

Ground-truth commands (implementation must make these work):

```bash
# 0. Build the experiment image
docker compose -f docker-compose.yml -f docker-compose.experiment.yml build experiment

# 1. Interactive authoring — JupyterLab on http://localhost:8899
docker compose -f docker-compose.yml -f docker-compose.experiment.yml up experiment

# 2. Run the azlib test suite inside Docker (TDD gate for every layer)
docker compose -f docker-compose.yml -f docker-compose.experiment.yml run --rm experiment \
    pytest notebooks/action_zones/tests -v

# 3. Headless notebook run (papermill), train set, one (tf, direction)
docker compose -f docker-compose.yml -f docker-compose.experiment.yml run --rm \
    --env-file configs/nn_train_dataset_2y.env experiment \
    papermill notebooks/action_zones/nb/40_regression_classification.ipynb \
    /trader_data_long/train/2y_link_usdt/action_zones/out/40_tf15_long.ipynb \
    -p tf 15 -p direction long

# 4. Full pipeline train→freeze→OOS→validate (one driver notebook)
docker compose -f docker-compose.yml -f docker-compose.experiment.yml run --rm \
    --env-file configs/nn_train_dataset_2y.env experiment \
    papermill notebooks/action_zones/nb/90_validate.ipynb \
    /trader_data_long/train/2y_link_usdt/action_zones/out/90_validate.ipynb \
    -p oos_env configs/oos2m_dataset.env
```

- [ ] **Step 0.1:** Create `docker/Dockerfile.experiment` (FROM simple_trader image; `pip install jupyterlab papermill scikit-learn scipy`; workdir `/code`).
- [ ] **Step 0.2:** Create `docker-compose.experiment.yml` with the `experiment` service (image build from Dockerfile.experiment; volumes `.:/code` + `simple_trader_vol_long:/trader_data_long`; ports `8899:8899`; default command `jupyter lab --ip=0.0.0.0 --port=8899 --no-browser --allow-root --NotebookApp.token=''`).
- [ ] **Step 0.3:** Create `notebooks/action_zones/{azlib/__init__.py, tests/__init__.py, nb/.gitkeep}` and `notebooks/action_zones/tests/conftest.py` (adds `notebooks/action_zones` to `sys.path`; provides a tiny synthetic wide-df fixture — see Appendix A).
- [ ] **Step 0.4:** Build the image (command 0). Expected: build succeeds.
- [ ] **Step 0.5:** Run the empty suite (command 2). Expected: `collected 0 items`, exit 0.
- [ ] **Step 0.6:** Commit. `docker/Dockerfile.experiment docker-compose.experiment.yml notebooks/action_zones/` — message `chore(action_zones): docker + package scaffold`.

**Verified:** [ ] `up experiment` serves JupyterLab · [ ] `pytest` collects & runs in Docker

---

## Layer 1: Data access & labels (`azlib/loader.py`)

Loads the wide df read-only and attaches strict + non-strict profit labels via existing functions.

### Interface (signatures only)

```python
import pandas as pd

def load_wide_df() -> pd.DataFrame: ...
# reads helpers.wide_df_path() (env-driven); returns the wide df unchanged. RO.

class LabelParams:  # dataclass
    tf: int; n: int; m: float; x: float; l: int; y: float
    atr_period: int = 14; ma_length: int = 5

def add_labels(wide_df: pd.DataFrame, p: LabelParams) -> None: ...
# in place: adds {tf}_pslong/psshort (strict) + {tf}_plong/pshort (non-strict).

def label_col(p: LabelParams, direction: str, strict: bool) -> str: ...
# returns the exact column name for (direction, strict) under params p.
```

### Integration test → Layer 2 (RED in Docker)

`tests/test_layer1_loader.py`:
```python
def test_labels_feed_action_space(synthetic_wide_df):
    from azlib.loader import add_labels, label_col, LabelParams
    from azlib.space import label_coeff
    p = LabelParams(tf=15, n=1, m=2.0, x=2.0, l=15, y=1.0)
    add_labels(synthetic_wide_df, p)
    assert label_col(p, "long", strict=True) in synthetic_wide_df.columns
    lc = label_coeff(synthetic_wide_df, tf=15, direction="long")   # Layer 2
    labeled = synthetic_wide_df[label_col(p, "long", strict=True)] == 1.0
    assert lc[labeled].between(0, 1).all()
```
Run: command 2, `-k layer1`. Expected: FAIL (`azlib.space` / functions absent).

### Unit tests (RED)

- `load_wide_df` returns a DataFrame with `1_high/1_low/1_close` and `{tf}_high/{tf}_low` columns present (use the fixture path via monkeypatched `wide_df_path`).
- `add_labels` adds all four columns; strict positives ⊆ non-strict positives (strict is a subset — every strict row is also non-strict).
- `label_col` round-trips the suffix convention (`n{n}_m{m}_x{x}_l{l}_y{y}` with `.`→`p`).
- Failure: `add_labels` raises `KeyError` with a clear message when `{tf}_atr_14_ma_5` is missing.

### Constraints / notes

- `add_labels` calls `indicators.labels.add_profit_strict_labels` and `add_profit_labels` (imported; not modified).
- Do not persist the labeled df back to the volume path — labels stay in memory (they are look-ahead; never overwrite `df_with_indicators.pkl`).
- Default label params per TF go in `azlib/config.py` (Task 1.2); document each knob's meaning. Defaults: `m=2.0, x=2.0`; `n=1` (one higher-TF candle look-ahead); `l=tf, y=1.0`. These are experiment knobs, tunable before the run.

---

## Layer 2: Action space & label_coeff (`azlib/space.py`)

Percentage-change levels → price levels → price-space coeff, per spec §1–2.

### Interface

```python
import numpy as np, pandas as pd

def diff_prc(series: pd.Series) -> pd.Series: ...            # (s - s.shift1)/s.shift1 * 100
def diff_prc_ma(diff: pd.Series, window: int = 6) -> pd.Series: ...
def diff_prc_std(diff: pd.Series, window: int = 6) -> pd.Series: ...   # plain rolling std

def price_levels(wide_df: pd.DataFrame, tf: int, window: int = 6, x: float = 2.0
                 ) -> tuple[pd.Series, pd.Series]: ...
# returns (price_high_level, price_low_level), each aligned to wide_df rows.
# price_high_level = prev_high * (1 + (high_diff_prc_ma + x*high_std)/100)
# price_low_level  = prev_low  * (1 + (low_diff_prc_ma  - x*low_std )/100)

def coeff(price: np.ndarray, low_level: np.ndarray, high_level: np.ndarray) -> np.ndarray: ...
# clamp((price - low_level)/(high_level - low_level), 0, 1)

def label_coeff(wide_df: pd.DataFrame, tf: int, direction: str,
                window: int = 6, x: float = 2.0) -> pd.Series: ...
# entry extreme: 1_low (long) / 1_high (short) mapped through coeff() at each row.
```

### Integration test → Layer 3 (RED in Docker)

`tests/test_layer2_space.py`:
```python
def test_label_coeff_feeds_indicator_join(synthetic_wide_df):
    from azlib.space import label_coeff
    from azlib.indicators import attribute_frame          # Layer 3
    lc = label_coeff(synthetic_wide_df, tf=15, direction="long")
    attrs = attribute_frame(synthetic_wide_df, tf=15, indicator="rsi")
    joined = attrs.join(lc.rename("label_coeff")).dropna()
    assert not joined.empty
    assert joined["label_coeff"].between(0, 1).all()
```
Run: command 2, `-k layer2`. Expected: FAIL (`attribute_frame` absent).

### Unit tests (RED)

- `diff_prc`: known series → exact percentages; first row NaN.
- `price_levels`: hand-computed on a 3-row frame with known high/low + ma/std → exact `price_high_level`/`price_low_level`; verify `high_level > prev_high` and `low_level < prev_low` for positive x.
- `coeff`: price at `low_level`→0, at `high_level`→1, midpoint→0.5, below→clamped 0, above→clamped 1.
- `label_coeff`: long uses `1_low`, short uses `1_high` (feed a row where low≠high and assert which one drives the coeff).
- Edge: `high_level == low_level` (degenerate) → coeff returns 0 (or documented sentinel), no divide-by-zero warning.

### Constraints / notes

- Prefer existing wide-df columns when present (`{tf}_high_diff_prc_rm_6` = diff_prc_ma window 6); recompute only the plain std (`diff_prc_std`) since only sided std is precomputed. Recompute diff_prc/ma from raw `{tf}_high`/`{tf}_low` if the columns are absent, using the same formulas.
- `prev_high`/`prev_low` = previous **same-TF** candle high/low (diff_prc reference).

---

## Layer 3: Indicator attributes (`azlib/indicators.py`)

position / slope / distance per indicator, z-scored & clamped [-3,3], train-frozen.

### Interface

```python
import pandas as pd

INDICATORS = ("rsi", "macd", "ma")
ATTRS = {"rsi": ("position","slope","distance"),
         "macd": ("position","slope","distance"),
         "ma": ("position","slope")}

def raw_attribute(wide_df: pd.DataFrame, tf: int, indicator: str, attr: str) -> pd.Series: ...

class FreezeStats:  # dataclass: {(tf,indicator,attr): (mean, std)}
    def to_json(self, path: str) -> None: ...
    @classmethod
    def from_json(cls, path: str) -> "FreezeStats": ...

def fit_stats(train_df: pd.DataFrame, tf: int) -> FreezeStats: ...
def zscore_clamp(series: pd.Series, mean: float, std: float, lo=-3.0, hi=3.0) -> pd.Series: ...

def attribute_frame(wide_df: pd.DataFrame, tf: int, indicator: str,
                    stats: FreezeStats | None = None) -> pd.DataFrame: ...
# columns = the indicator's attrs, z-scored+clamped when stats given (raw otherwise).
```

### Integration test → Layer 4 (RED in Docker)

`tests/test_layer3_indicators.py`:
```python
def test_attributes_feed_regression(synthetic_wide_df):
    from azlib.indicators import fit_stats, attribute_frame
    from azlib.space import label_coeff
    from azlib.models import fit_regression                 # Layer 4
    stats = fit_stats(synthetic_wide_df, tf=15)
    X = attribute_frame(synthetic_wide_df, 15, "rsi", stats)[["position"]]
    y = label_coeff(synthetic_wide_df, 15, "long")
    df = X.join(y.rename("y")).dropna()
    res = fit_regression(df[["position"]].to_numpy(), df["y"].to_numpy(), kind="linear")
    assert res.metrics["r2"] is not None
```
Run: command 2, `-k layer3`. Expected: FAIL (`fit_regression` absent).

### Unit tests (RED)

- RSI: `position` = `{tf}_rsi_ma8` (from config), `slope` = diff of `rsi_ma8`, `distance` = `rsi_14 - rsi_ma8`. Assert against known columns.
- MACD: `position` = `{tf}_macd_12_26_9`, `slope` = its diff, `distance` = `{tf}_macd_hist_12_26_9`.
- MA: `position` = `(close - ema_25)/close*100`, `slope` = diff of `ema_25`. (`distance` absent for MA.)
- `zscore_clamp`: value at mean→0; mean+3std→3; mean+5std→clamped 3; std=0 → returns 0 (no div-by-zero).
- `fit_stats`/`from_json` round-trips to identical means/stds.

### Constraints / notes

- Exact column names (from `configs/indicators_config.yaml`): `rsi_14`, `rsi_ma8`, `macd_12_26_9`, `macd_hist_12_26_9`, `ema_25`. Confirm the chosen `ma`/`rsi_ma` periods in Task 3.1; keep them in `azlib/config.py`.
- `fit_stats` computes mean/std on **train only**; OOS calls `attribute_frame(..., stats)` with the frozen stats.

---

## Layer 4: Regression + classification (`azlib/models.py`)

Runs for every 1D/2D/3D same-space attribute group (spec §9, all dimensionalities).

### Interface

```python
import numpy as np

class RegResult:   # dataclass
    kind: str; params: dict; metrics: dict     # metrics: {"r2","rmse","resid_std"}
class ClfResult:   # dataclass
    kind: str; params: dict; metrics: dict     # metrics: {"false_pos_rate","accuracy","auc"}

def fit_regression(X: np.ndarray, y: np.ndarray, kind: str) -> RegResult: ...   # linear|poly2|gbr
def predict_reg(res: RegResult, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]: ...  # (mean, std)
def fit_classification(X: np.ndarray, label: np.ndarray, kind: str) -> ClfResult: ... # logistic|gbc
def predict_clf(res: ClfResult, X: np.ndarray) -> np.ndarray: ...              # P(label=1)

def save_result(res, path: str) -> None: ...        # JSON+joblib; reproducible
def load_result(path: str): ...

def groups(indicator: str, dim: int) -> list[tuple[str, ...]]: ...  # attr combos for a dim
def plot_1d(x, y, res, out_path: str) -> None: ...  # fit curve + label 0/1 points
def plot_2d(x1, x2, y, res, out_path: str) -> None: ...
```

### Integration test → Layer 5 (RED in Docker)

`tests/test_layer4_models.py`:
```python
def test_regression_feeds_fusion(rng_matrix):
    from azlib.models import fit_regression, predict_reg
    from azlib.infer import fuse_inverse_variance          # Layer 5
    X, y = rng_matrix
    r1 = fit_regression(X[:, :1], y, "linear")
    r2 = fit_regression(X[:, 1:2], y, "poly2")
    m1, s1 = predict_reg(r1, X[:, :1]); m2, s2 = predict_reg(r2, X[:, 1:2])
    mean, std = fuse_inverse_variance(np.vstack([m1, m2]), np.vstack([s1, s2]))
    assert mean.shape == y.shape and (std >= 0).all()
```
Run: command 2, `-k layer4`. Expected: FAIL (`fuse_inverse_variance` absent).

### Unit tests (RED)

- `fit_regression` on a perfect line → r2≈1, resid_std≈0; `predict_reg` returns that resid_std as std.
- `poly2`/`gbr` kinds fit and predict without error on the synthetic matrix.
- `fit_classification` on separable data → false_pos_rate≈0; `predict_clf` in [0,1].
- `groups("rsi", 1)`→3 singletons; `("rsi",2)`→3 pairs; `("rsi",3)`→1 triple; `("ma",3)`→[] (only 2 attrs).
- `save_result`/`load_result` round-trip → identical predictions.
- `plot_1d`/`plot_2d` write a non-empty PNG to the given volume path.

### Constraints / notes

- Regression std = residual std of the fit (used as the per-point uncertainty for fusion). For `gbr`, use quantile regressors or residual std by binned prediction — document choice.
- Classification error of interest = **false-positive rate** (label=0 predicted as 1), per spec §9.2.1.
- All charts write to the volume artifact dir, never the worktree.

---

## Layer 5: Inference, fusion & Y-sweep (`azlib/infer.py`)

### Interface

```python
import numpy as np, pandas as pd

def fuse_inverse_variance(means: np.ndarray, stds: np.ndarray) -> tuple[np.ndarray, np.ndarray]: ...
# means/stds shape [n_groups, n_points]; returns fused (mean, std) [n_points].

def inferred_coeff(mean: np.ndarray, std: np.ndarray, y: float) -> np.ndarray: ...  # mean + y*std

def sweep_y(fused_mean, fused_std, wide_df, tf, direction,
            price_levels_fn, strict_label, y_grid) -> pd.DataFrame: ...
# per Y: strict_coverage, realized_rr (placeholder until Layer 6), n_zoned. Returns table.

def select_y(sweep: pd.DataFrame) -> float: ...   # max strict_coverage s.t. rr profitable
```

### Integration test → Layer 6/7 (RED in Docker)

`tests/test_layer5_infer.py`:
```python
def test_y_sweep_produces_selectable_y(synthetic_pipeline):
    from azlib.infer import sweep_y, select_y
    sweep = sweep_y(**synthetic_pipeline, y_grid=np.round(np.arange(-2,2.01,0.1),1))
    assert {"y","strict_coverage","n_zoned"} <= set(sweep.columns)
    y = select_y(sweep)
    assert -2.0 <= y <= 2.0
```
Run: command 2, `-k layer5`. Expected: FAIL.

### Unit tests (RED)

- `fuse_inverse_variance`: two groups equal mean/std → fused std = std/√2; a group with huge std is down-weighted (fused mean ≈ the confident group).
- `inferred_coeff`: y=0→mean; y=1→mean+std.
- `sweep_y`: monotonic — larger Y (long) widens/narrows zone in the documented direction; strict_coverage in [0,1].
- `select_y`: picks the profitable-RR max-coverage row; returns NaN-safe default if none profitable (documented).

### Constraints / notes

- fusion weight = 1/std² per point; guard std→0 with a floor.
- `realized_rr` column is wired in Layer 6; until then sweep_y accepts an injected rr callback (dependency inversion keeps layers testable).

---

## Layer 6: Reach-probability & R/R grid (`azlib/rr.py`)

Hybrid empirical + parametric-tail reach-prob (spec §6.1) + R/R grid (§6).

### Interface

```python
import numpy as np, pandas as pd
from typing import Callable

def reach_prob_estimator(train_extreme_diff: np.ndarray, min_bin: int = 50) -> Callable[[np.ndarray], np.ndarray]: ...
# ECDF body + generalized-Pareto/skew-t tail where sample count < min_bin. Frozen on train.

def rr_grid(reach_up: Callable, reach_down: Callable, x_grid: np.ndarray,
            fee: float, candle_size: float, direction: str) -> pd.DataFrame: ...
# per (tgt_x, sl_x): p_target, p_stop, rr, expected_return_after_fees.

def select_levels(grid: pd.DataFrame) -> dict: ...   # {"tgt_x","sl_x","rr","exp_ret"}

def reach_freq_drift(train_est: Callable, oos_extreme_diff: np.ndarray,
                     x_grid: np.ndarray) -> pd.DataFrame: ...   # train P vs OOS realized freq
```

### Integration test → Layer 7 (RED in Docker)

`tests/test_layer6_rr.py`:
```python
def test_rr_levels_feed_zone_calc(synthetic_wide_df):
    from azlib.rr import reach_prob_estimator, rr_grid, select_levels
    hi = synthetic_wide_df["15_high_diff_prc"].dropna().to_numpy()
    est = reach_prob_estimator(hi)
    grid = rr_grid(est, est, np.round(np.arange(0,2.01,0.25),2),
                   fee=0.001, candle_size=1.0, direction="long")
    lv = select_levels(grid)
    assert 0 <= lv["tgt_x"] <= 2.0 and lv["rr"] > 0
```
Run: command 2, `-k layer6`. Expected: FAIL.

### Unit tests (RED)

- `reach_prob_estimator`: monotone non-increasing in level; P(level=min)≈1; far tail returns smooth non-zero (parametric), not raw-zero.
- Tail kicks in only where bin count < min_bin (assert the crossover uses parametric on a sparse synthetic tail).
- `rr_grid`: rr = p_target/p_stop; expected_return subtracts `2*fee` (entry+exit); larger tgt_x → lower p_target.
- `select_levels`: returns the max expected-return-after-fees row; excludes rows with exp_ret ≤ 0.
- `reach_freq_drift`: identical train/OOS input → ~zero drift.

### Constraints / notes

- Reach prob is a **touch/first-passage** on the extreme series (high_diff_prc for up, low_diff_prc for down) — not a terminal Gaussian. Normal-CDF only logged as a baseline column, never selected on.
- `candle_size` = median |high-low| in price (or ATR) on train — document the exact definition in Task 6.1.

---

## Layer 7: Zones & results file (`azlib/zones.py`)

### Interface

```python
import numpy as np, pandas as pd

def zone_limit_price(inferred_coeff: np.ndarray, low_level: np.ndarray, high_level: np.ndarray) -> np.ndarray: ...
# inverse of coeff: low_level + inferred_coeff*(high_level - low_level)

def mark_zones(wide_df: pd.DataFrame, tf: int, direction: str, zone_limit: np.ndarray) -> pd.Series: ...
# long: 1_low < zone_limit ; short: 1_high > zone_limit → bool per row.

def build_zoned_dataset(wide_df, tf, direction, zone_limit, levels: dict) -> pd.DataFrame: ...
# columns: az_zone_{dir}_{tf} (bool), az_entry, az_tgt, az_sl, az_rr — indexed like wide_df.

class ResultsFile:  # dataclass — everything needed to re-infer on a new dataset
    tf: int; direction: str; label_params: dict; freeze_stats_path: str
    reg_models: list[str]; y: float; tgt_x: float; sl_x: float; fee: float
    def save(self, path: str) -> None: ...
    @classmethod
    def load(cls, path: str) -> "ResultsFile": ...
```

### Integration test → Layer 8 (RED in Docker)

`tests/test_layer7_zones.py`:
```python
def test_zoned_dataset_and_results_roundtrip(synthetic_pipeline_full, tmp_path):
    from azlib.zones import build_zoned_dataset, ResultsFile
    zdf = build_zoned_dataset(**synthetic_pipeline_full)
    assert {"az_zone_long_15","az_entry","az_tgt","az_sl","az_rr"} <= set(zdf.columns)
    rf = ResultsFile(tf=15, direction="long", label_params={}, freeze_stats_path="s.json",
                     reg_models=["rsi:linear"], y=0.3, tgt_x=1.5, sl_x=1.0, fee=0.001)
    rf.save(str(tmp_path/"rf.json")); assert ResultsFile.load(str(tmp_path/"rf.json")).y == 0.3
```
Run: command 2, `-k layer7`. Expected: FAIL.

### Unit tests (RED)

- `zone_limit_price`: inverse of `coeff` (round-trip a known price).
- `mark_zones`: long marks rows where `1_low < zone_limit`; short where `1_high > zone_limit`.
- `build_zoned_dataset`: tgt/sl prices derived from `levels` in the same space; `az_rr` matches `levels["rr"]`.
- `ResultsFile.save/load` round-trips all fields.

### Constraints / notes

- Zoned dataset + results file write to `…/action_zones/<direction>/<tf>/{datasets,results}/` on the volume.
- Column prefix `az_` chosen so a later `join_action_zones` (Layer 10) can surface them without name clashes.

---

## Layer 8: Validation harness (`azlib/validate.py`)

Train→fit/freeze, OOS→apply-frozen, compute metrics.

### Interface

```python
import pandas as pd

def run_train(train_env: str, tf: int, direction: str) -> str: ...
# runs Layers 1-7 on train; freezes stats + writes ResultsFile; returns results path.

def run_oos(results_path: str, oos_env: str) -> pd.DataFrame: ...
# loads frozen ResultsFile, applies to OOS wide df, returns zoned OOS df.

def metrics(zoned_df: pd.DataFrame, tf: int, direction: str, label_params: dict) -> dict: ...
# {"strict_coverage","non_strict_coverage","realized_rr","reach_drift_max"}
```

### Integration test (RED in Docker)

`tests/test_layer8_validate.py`:
```python
def test_train_then_oos_metrics(monkeypatch, two_synthetic_datasets):
    from azlib.validate import run_train, run_oos, metrics
    rp = run_train("train.env", tf=15, direction="long")
    zoos = run_oos(rp, "oos.env")
    m = metrics(zoos, 15, "long", label_params={})
    assert 0 <= m["strict_coverage"] <= 1 and "realized_rr" in m
```
Run: command 2, `-k layer8`. Expected: FAIL.

### Unit tests (RED)

- `run_oos` uses only frozen stats (monkeypatch `fit_stats` to raise → still succeeds, proving no refit on OOS).
- `metrics.strict_coverage` = fraction of strict-label rows inside the zone; hand-check on a tiny frame.
- `realized_rr` computed from actual forward touches of tgt vs sl for zoned entries.
- `reach_drift_max` = max |train P − OOS freq| across the x-grid.

### Constraints / notes

- This is where the spec's success metric lives: **maximize strict_coverage AND require profitable realized_rr**. `metrics` reports both; selection happened in Layers 5–6.
- `run_train`/`run_oos` set env via the passed env-file path so a single Docker invocation covers both datasets.

---

## Layer 9: Notebooks (the mandated Jupyter deliverables)

Thin, papermill-parametrized notebooks in `notebooks/action_zones/nb/` that import `azlib` and emit charts/reports/datasets to the volume. One integration test per notebook via `papermill` execution (no exceptions) — nbval-style.

- [ ] **9.1** `10_action_space.ipynb` — build + sanity-plot the price space and label_coeff distribution (params: `tf`, `direction`).
- [ ] **9.2** `40_regression_classification.ipynb` — run §9.1/§9.2 for all 1D/2D/3D groups; save charts + reproducible reports (params: `tf`, `direction`).
- [ ] **9.3** `60_rr_grid.ipynb` — reach-prob + R/R grid + selected levels report (params: `tf`, `direction`, `fee`).
- [ ] **9.4** `80_zones.ipynb` — infer, fuse, Y-sweep, mark zones, write zoned dataset + ResultsFile (params: `tf`, `direction`).
- [ ] **9.5** `90_validate.ipynb` — full train→OOS run + metrics report (params: `oos_env`).

Integration test (RED in Docker) per notebook, e.g.:
```bash
docker compose -f docker-compose.yml -f docker-compose.experiment.yml run --rm \
  --env-file configs/nn_train_dataset_2y.env experiment \
  papermill notebooks/action_zones/nb/10_action_space.ipynb \
  /trader_data_long/train/2y_link_usdt/action_zones/out/10_smoke.ipynb -p tf 15 -p direction long
```
Expected: exit 0; artifact files present on the volume.

### Constraints / notes

- Notebooks contain orchestration + plotting only; all logic is imported from `azlib` (keeps them thin and the logic tested).
- Human validation checkpoint (spec §10) happens after 9.2/9.4 review — select the best models before locking ResultsFile.

---

## Layer 10 (GATED — do NOT start until human approval): Viewer integration

**Blocked by the spec restriction (line 173): existing code stays untouched until the full flow is human-validated and approved.** Only after that gate:

### Interface (extends existing `data.py`, mirrors `join_nn_results`)

```python
def join_action_zones(df: pd.DataFrame, dataset_dir: str) -> pd.DataFrame: ...
# absence-safe left-join of the az_* zoned sidecar so view_full surfaces zone markers.
```

- [ ] **10.1** Add `join_action_zones` to `data.py` (new function; do not alter `join_nn_results`).
- [ ] **10.2** Call it in `view_full.py` after `join_nn_results` (one line).
- [ ] **10.3** Integration test (RED in Docker): `view_full` on a dataset with an `az_*` sidecar renders the markers.
- [ ] **10.4** Verify in the running `view-full` service on train + OOS (spec Data line 195).

---

## Self-Review

**Spec coverage:** §1 space→L2 · §2 label_coeff→L2 · §3 asymmetry→L2 (structural) · §4 levels/X→L2+L6 · §5 R/R→L6 · §6 folded (indicators→adaptation) →L3-L5 · §7 indicators→L3 · §8 labels→L1 · §9.1/9.2 all dims→L4+L9 · §10 human validation→L9 checkpoint · §11 fusion/Y/zones→L5+L7 · §6.1 hybrid reach-prob→L6 · Restrictions (read-only, notebooks, volume, train-freeze, TF matched, long/short, results file)→Global Constraints+L7/L8 · Data markers-in-viewer→L10 (gated) · Train 2y / OOS 2m→L8.

**Placeholder scan:** label params (n,m,x,l,y) are concrete defaults tagged as tunable config, not TBD. `candle_size` + `ma`/`rsi` period choices deferred to their layer's Task .1 with explicit definitions — flagged, not vague.

**Type consistency:** `label_coeff`, `attribute_frame`, `fit_regression`/`predict_reg`, `fuse_inverse_variance`, `reach_prob_estimator`, `zone_limit_price`, `ResultsFile` signatures are referenced identically across the integration tests that consume them.

## Appendix A — synthetic wide-df fixture

`tests/conftest.py` builds a small deterministic wide df (a few hundred rows) with columns: `1_high/1_low/1_close`, `{tf}_high/{tf}_low/{tf}_close`, `{tf}_high_diff_prc(_rm_6)`, `{tf}_low_diff_prc(_rm_6)`, `{tf}_atr_14_ma_5`, `{tf}_rsi_14`, `{tf}_rsi_ma8`, `{tf}_macd_12_26_9`, `{tf}_macd_hist_12_26_9`, `{tf}_ema_25`, for tf∈{15,60,240}. Values from a seeded RNG (fixed seed constant, not Date/random-at-import) so tests are reproducible.
