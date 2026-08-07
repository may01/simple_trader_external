# task-01 — config + data loading (closed-row per-TF frames)

**Files:**
- Create: `experiments/__init__.py`, `experiments/rsi_params_selection/__init__.py`
- Create: `experiments/rsi_params_selection/config.py`
- Create: `experiments/rsi_params_selection/data_loading.py`
- Test: `tests/unit/experiments/__init__.py`, `tests/unit/experiments/test_rps_data_loading.py`

**Interfaces:**
- Consumes: repo `config_loader.load_labels_config(path)`; `indicators.labels.add_profit_labels(df, tf, n, m, x, atr_period, ma_length)` / `add_profit_strict_labels(df, tf, n, m, x, l, y, atr_period, ma_length)`; volume pickles.
- Produces (later tasks rely on these exact names):
  - `config.TFS = [15, 60, 240]`, `config.WINDOWS = [8, 12, 24]`, `config.TECHNIQUES = ["quantile", "sym0", "zscore"]`, `config.CLASS_COUNTS = [5, 7]`
  - `config.QUANTILE_CUTS: dict[int, list[float]]`, `config.SYM0_K: dict[int, list[float]]`, `config.ZSCORE_K: dict[int, list[float]]`
  - `config.label_cols(tf: int) -> dict[str, str]` — key like `"strict_n1_long"` → wide column name
  - `data_loading.add_labels_for_tfs(df: pd.DataFrame, tfs: list[int], config_path: str) -> None` (in place)
  - `data_loading.extract_closed(df: pd.DataFrame, tf: int) -> pd.DataFrame` — columns `diff8, diff12, diff24` + the 8 label keys, only closed rows
  - `data_loading.load_2y(tfs, limit: int | None = None) -> dict[int, pd.DataFrame]`
  - `data_loading.load_oos(tfs) -> dict[int, pd.DataFrame]`

- [ ] **Step 1: write failing tests**

`tests/unit/experiments/test_rps_data_loading.py`:

```python
import numpy as np
import pandas as pd
import pytest

from experiments.rsi_params_selection import config
from experiments.rsi_params_selection.data_loading import (
    add_labels_for_tfs, extract_closed,
)


def test_label_cols_names_match_baked_columns():
    cols = config.label_cols(60)
    assert cols["plain_n1_long"] == "60_plong_n1_m1_x0p2"
    assert cols["strict_n2_short"] == "60_psshort_n2_m1_x0p2_l15_y0p1"
    cols15 = config.label_cols(15)
    assert cols15["strict_n1_long"] == "15_pslong_n1_m1_x0p3_l15_y0p2"
    cols240 = config.label_cols(240)
    assert cols240["plain_n2_short"] == "240_pshort_n2_m1_x0p1"
    assert len(cols) == 8


def _tiny_wide(n=2000, tf=15):
    """Minimal wide frame labels.py + extract_closed can run on."""
    idx = pd.date_range("2024-01-01", periods=n, freq="min")
    rng = np.random.default_rng(0)
    close = 100 + np.cumsum(rng.normal(0, 0.1, n))
    df = pd.DataFrame(index=idx)
    df["1_high"] = close + 0.05
    df["1_low"] = close - 0.05
    df[f"{tf}_atr_14_ma_5"] = 1.0
    df[f"{tf}_is_closed"] = (np.arange(n) % tf) == (tf - 1)
    for w in config.WINDOWS:
        df[f"{tf}_rsi_ma{w}_diff"] = rng.normal(0, 1, n)
    return df


def test_add_labels_for_tfs_appends_all_8_columns():
    df = _tiny_wide(tf=15)
    add_labels_for_tfs(df, [15], config_path="configs/indicators_config.yaml")
    for col in config.label_cols(15).values():
        assert col in df.columns, col
    lab = df["15_plong_n1_m1_x0p3"]
    vals = lab.dropna().unique()
    assert set(vals).issubset({0.0, 1.0})
    assert lab.tail(5).isna().all()  # future window incomplete at frame end


def test_add_labels_for_tfs_skips_other_tfs():
    df = _tiny_wide(tf=15)
    add_labels_for_tfs(df, [15], config_path="configs/indicators_config.yaml")
    assert not any(c.startswith("60_p") for c in df.columns)


def test_extract_closed_filters_and_renames():
    df = _tiny_wide(n=600, tf=15)
    add_labels_for_tfs(df, [15], config_path="configs/indicators_config.yaml")
    out = extract_closed(df, 15)
    assert len(out) == int(df["15_is_closed"].sum())
    assert set(out.columns) == {"diff8", "diff12", "diff24",
                                *config.label_cols(15).keys()}
    closed_ts = df.index[df["15_is_closed"].astype(bool)]
    assert out.index.equals(closed_ts)
    got = out["diff12"].to_numpy()
    want = df.loc[closed_ts, "15_rsi_ma12_diff"].to_numpy()
    assert np.array_equal(got, want)
```

- [ ] **Step 2: run tests, verify they fail**

Run: `python3 -m pytest tests/unit/experiments/test_rps_data_loading.py -q`
Expected: FAIL — `ModuleNotFoundError: experiments`

- [ ] **Step 3: implement**

`experiments/__init__.py`, `experiments/rsi_params_selection/__init__.py`, `tests/unit/experiments/__init__.py` — empty files.

`experiments/rsi_params_selection/config.py`:

```python
"""Grid constants + dataset paths for the RSI parameters selection experiment.

Spec: external/docs/superpowers/specs/2026-08-06-rsi-parameters-selection-design.md
Measurement-only harness — never imported by production code.
"""

VOL = "/media/om/Alexandria/simple_trader/simple_trader_vol_long/train"
TWOY_DIR = f"{VOL}/2y_link_usdt"
OOS_PATH = f"{VOL}/oos2m_link_usdt/df_with_indicators.pkl"
CONFIG_PATH = "configs/indicators_config.yaml"

TFS = [15, 60, 240]
WINDOWS = [8, 12, 24]
TECHNIQUES = ["quantile", "sym0", "zscore"]
CLASS_COUNTS = [5, 7]

QUANTILE_CUTS = {5: [10, 30, 70, 90], 7: [2, 10, 30, 70, 90, 98]}
SYM0_K = {5: [0.3, 1.0], 7: [0.3, 1.0, 2.0]}
ZSCORE_K = {5: [0.5, 1.0], 7: [0.5, 1.0, 2.0]}

# Per-TF label params baked into column names (configs/indicators_config.yaml labels:)
_X = {15: "0p3", 60: "0p2", 240: "0p1"}
_Y = {15: "0p2", 60: "0p1", 240: "0p1"}


def label_cols(tf: int) -> dict[str, str]:
    """Map short label key -> wide-frame column name for one TF."""
    out = {}
    for n in (1, 2):
        out[f"plain_n{n}_long"] = f"{tf}_plong_n{n}_m1_x{_X[tf]}"
        out[f"plain_n{n}_short"] = f"{tf}_pshort_n{n}_m1_x{_X[tf]}"
        out[f"strict_n{n}_long"] = f"{tf}_pslong_n{n}_m1_x{_X[tf]}_l15_y{_Y[tf]}"
        out[f"strict_n{n}_short"] = f"{tf}_psshort_n{n}_m1_x{_X[tf]}_l15_y{_Y[tf]}"
    return out


# (kind, n) pairs used by metrics for long-vs-short separation
LABEL_PAIRS = [("plain", 1), ("plain", 2), ("strict", 1), ("strict", 2)]
```

`experiments/rsi_params_selection/data_loading.py`:

```python
"""Load per-TF closed-row frames (diffs + labels) from 2y parts and oos2m.

2y parts carry NO label columns — labels are computed per part in memory via
indicators.labels (vectorized). Per-part boundary tails yield NaN labels and
are dropped downstream (spec §5.2 accepted loss). oos2m has labels baked.
"""
import glob
import os

import pandas as pd

from . import config


def add_labels_for_tfs(df: pd.DataFrame, tfs, config_path: str = config.CONFIG_PATH) -> None:
    """Append profit-label columns for the given tfs, in place.

    Same loop as training/data_preparer._compute_profit_labels, restricted
    to tfs we score — parts are 43200x716, full label pass is wasted work.
    """
    from config_loader import load_labels_config
    from indicators.labels import add_profit_labels, add_profit_strict_labels

    for spec in load_labels_config(config_path):
        for tf in spec.tfs:
            if tf not in tfs:
                continue
            if spec.type == "profit":
                add_profit_labels(
                    df, tf, spec.n, spec.m, spec.x,
                    atr_period=spec.atr_period, ma_length=spec.ma_length,
                )
            else:  # profit_strict — validated by load_labels_config
                add_profit_strict_labels(
                    df, tf, spec.n, spec.m, spec.x, spec.l, spec.y,
                    atr_period=spec.atr_period, ma_length=spec.ma_length,
                )


def extract_closed(df: pd.DataFrame, tf: int) -> pd.DataFrame:
    """Closed-candle rows for one TF, renamed to short keys.

    Columns: diff8/diff12/diff24 + the 8 label keys of config.label_cols(tf).
    """
    cols = {f"diff{w}": f"{tf}_rsi_ma{w}_diff" for w in config.WINDOWS}
    cols.update(config.label_cols(tf))
    mask = df[f"{tf}_is_closed"].astype(bool).to_numpy()
    out = pd.DataFrame(
        {short: df[wide].to_numpy()[mask] for short, wide in cols.items()},
        index=df.index[mask],
    )
    return out


def _part_paths(limit: int | None = None) -> list[str]:
    paths = sorted(glob.glob(
        os.path.join(config.TWOY_DIR, "df_with_indicators.part_*.pkl")))
    if not paths:
        raise FileNotFoundError(f"no 2y parts under {config.TWOY_DIR}")
    return paths[:limit] if limit else paths


def load_2y(tfs=tuple(config.TFS), limit: int | None = None) -> dict[int, pd.DataFrame]:
    """One concat'd closed-row frame per TF across 2y parts (labels computed)."""
    frames: dict[int, list] = {tf: [] for tf in tfs}
    for path in _part_paths(limit):
        df = pd.read_pickle(path)
        add_labels_for_tfs(df, list(tfs))
        for tf in tfs:
            frames[tf].append(extract_closed(df, tf))
        del df
    return {tf: pd.concat(parts) for tf, parts in frames.items()}


def load_oos(tfs=tuple(config.TFS)) -> dict[int, pd.DataFrame]:
    """Per-TF closed-row frames from oos2m (labels already baked)."""
    df = pd.read_pickle(config.OOS_PATH)
    return {tf: extract_closed(df, tf) for tf in tfs}
```

- [ ] **Step 4: run tests, verify pass**

Run: `python3 -m pytest tests/unit/experiments/test_rps_data_loading.py -q`
Expected: 4 passed. (Runs from worktree root so `config_loader` / `indicators` import.)

- [ ] **Step 5: real-data spot check (no test file — one-off command)**

```bash
python3 -c "
from experiments.rsi_params_selection.data_loading import load_2y, load_oos
tr = load_2y(limit=1); oo = load_oos()
for tf, f in tr.items(): print('2y', tf, f.shape, f['strict_n1_long'].notna().mean().round(3))
for tf, f in oo.items(): print('oos', tf, f.shape, f['strict_n1_long'].notna().mean().round(3))
"
```
Expected: 2y part_00 → TF15 ≈ 2880 rows, TF60 ≈ 720, TF240 ≈ 180; oos → TF15 ≈ 5664, TF60 ≈ 1416, TF240 ≈ 354; notna fraction > 0.9 everywhere.

- [ ] **Step 6: checkpoint — report changed files (NO commit; user confirms commits)**
