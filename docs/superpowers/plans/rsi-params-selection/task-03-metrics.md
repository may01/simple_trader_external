# task-03 — per-cell metrics

**Files:**
- Create: `experiments/rsi_params_selection/metrics.py`
- Test: `tests/unit/experiments/test_rps_metrics.py`

**Interfaces:**
- Consumes: centered class ids from `classify.apply_cuts`; closed-row frames from `data_loading.extract_closed` (columns `diff{W}` + 8 label keys); `config.LABEL_PAIRS`.
- Produces:
  - `metrics.evaluate(classes: np.ndarray, labels: pd.DataFrame, n_classes: int) -> dict` — full metric block for one (dataset, cell). `classes` aligned row-for-row with `labels` (the 8 label-key columns).
  - Helpers (unit-tested): `mutual_information(cls, y) -> float` (bits), `eta_squared(cls, y) -> float`, `spearman(a, b) -> float`.

`evaluate` return shape (all plain python types, JSON-ready):

```python
{
  "n_rows": int,
  "population": {"-2": int, ..., "2": int},          # class id -> row count
  "labels": {                                          # per label key
    "strict_n1_long": {
      "n": int, "base_rate": float,
      "rate": {"-2": float|None, ...},                 # P(label=1 | class); None = empty class
      "lift": {"-2": float|None, ...},                 # rate / base_rate
      "mi": float, "eta2": float,
    }, ...
  },
  "pairs": {                                           # per (kind, n) long-vs-short
    "strict_n1": {
      "spread": {"-2": float|None, ...},               # rate_long - rate_short per class
      "monotonicity_rho": float,                       # spearman(class_id, spread)
      "flip": {                                        # 7-class only, else None
        "neg": {"strong": float|None, "extra": float|None,
                 "sign_flip": bool|None, "shrink": bool|None},
        "pos": {...same...},
      },
    }, ...
  },
}
```

- [ ] **Step 1: write failing tests**

`tests/unit/experiments/test_rps_metrics.py`:

```python
import numpy as np
import pandas as pd
import pytest

from experiments.rsi_params_selection.metrics import (
    evaluate, eta_squared, mutual_information, spearman,
)


def test_mi_zero_when_independent_and_positive_when_dependent():
    rng = np.random.default_rng(2)
    cls = rng.integers(-2, 3, 20_000)
    y_ind = rng.integers(0, 2, 20_000).astype(float)
    y_dep = (cls > 0).astype(float)
    assert mutual_information(cls, y_ind) == pytest.approx(0.0, abs=0.001)
    assert mutual_information(cls, y_dep) > 0.5


def test_eta_squared_bounds():
    cls = np.array([-1, -1, 0, 0, 1, 1])
    assert eta_squared(cls, np.array([0, 0, 0, 1, 1, 1.0])) > 0.5
    assert eta_squared(cls, np.array([1, 1, 1, 1, 1, 1.0])) == 0.0


def test_spearman_perfect_and_inverse():
    a = np.array([1.0, 2, 3, 4, 5])
    assert spearman(a, a * 10) == pytest.approx(1.0)
    assert spearman(a, -a) == pytest.approx(-1.0)


def _labels_frame(cls):
    """Long fires on positive classes, short on negative — clean separation."""
    rng = np.random.default_rng(3)
    n = len(cls)
    frame = {}
    for kind in ("plain", "strict"):
        for hn in (1, 2):
            p_long = np.where(cls > 0, 0.6, 0.1)
            p_short = np.where(cls < 0, 0.6, 0.1)
            frame[f"{kind}_n{hn}_long"] = (rng.random(n) < p_long).astype(float)
            frame[f"{kind}_n{hn}_short"] = (rng.random(n) < p_short).astype(float)
    return pd.DataFrame(frame)


def test_evaluate_shape_and_separation():
    rng = np.random.default_rng(4)
    cls = rng.integers(-2, 3, 50_000)
    res = evaluate(cls, _labels_frame(cls), 5)
    assert res["n_rows"] == 50_000
    assert sum(res["population"].values()) == 50_000
    lab = res["labels"]["strict_n1_long"]
    assert lab["rate"]["2"] > lab["rate"]["-2"]
    assert lab["lift"]["2"] > 1.0 > lab["lift"]["-2"]
    assert lab["mi"] > 0.05
    pair = res["pairs"]["strict_n1"]
    assert pair["spread"]["2"] > 0 > pair["spread"]["-2"]
    assert pair["monotonicity_rho"] > 0.8
    assert pair["flip"] is None  # 5-class


def test_evaluate_flip_detection_7class():
    rng = np.random.default_rng(5)
    cls = rng.integers(-3, 4, 80_000)
    n = len(cls)
    # continuation up to |2|, reversal in |3| (extra) classes
    p_long = np.select([cls == 3, cls > 0, cls == -3], [0.1, 0.6, 0.6], 0.1)
    p_short = np.select([cls == -3, cls < 0, cls == 3], [0.1, 0.6, 0.6], 0.1)
    frame = {}
    for kind in ("plain", "strict"):
        for hn in (1, 2):
            frame[f"{kind}_n{hn}_long"] = (rng.random(n) < p_long).astype(float)
            frame[f"{kind}_n{hn}_short"] = (rng.random(n) < p_short).astype(float)
    res = evaluate(cls, pd.DataFrame(frame), 7)
    flip = res["pairs"]["strict_n1"]["flip"]
    assert flip["pos"]["sign_flip"] is True   # +2 long-dominant, +3 short-dominant
    assert flip["neg"]["sign_flip"] is True
    assert flip["pos"]["strong"] > 0 > flip["pos"]["extra"]


def test_evaluate_handles_nan_labels_and_empty_class():
    cls = np.zeros(100, dtype=int)  # only neutral class populated
    frame = _labels_frame(cls)
    frame.iloc[:50, frame.columns.get_loc("strict_n1_long")] = np.nan
    res = evaluate(cls, frame, 5)
    assert res["labels"]["strict_n1_long"]["n"] == 50
    assert res["labels"]["strict_n1_long"]["rate"]["2"] is None  # empty class
    assert res["population"]["2"] == 0
```

- [ ] **Step 2: run tests, verify fail**

Run: `python3 -m pytest tests/unit/experiments/test_rps_metrics.py -q`
Expected: FAIL — `ImportError: metrics`

- [ ] **Step 3: implement**

`experiments/rsi_params_selection/metrics.py`:

```python
"""Separation metrics for one (dataset, grid-cell): how profit labels
distribute over slope classes. numpy/pandas only — no scipy/sklearn.

Flip test is direction-agnostic (spec §6.4): dominance = rate_long − rate_short
per class; "flip" = dominance sign change between the strong (|id| = center−1)
and extra (|id| = center) class of the same sign; "shrink" = |dominance| falls.
"""
import numpy as np
import pandas as pd

from .config import LABEL_PAIRS


def mutual_information(cls: np.ndarray, y: np.ndarray) -> float:
    """MI(class; binary label) in bits, from the contingency table."""
    ct = pd.crosstab(pd.Series(cls), pd.Series(y)).to_numpy(dtype=float)
    p = ct / ct.sum()
    px = p.sum(axis=1, keepdims=True)
    py = p.sum(axis=0, keepdims=True)
    nz = p > 0
    return float((p[nz] * np.log2(p[nz] / (px @ py)[nz])).sum())


def eta_squared(cls: np.ndarray, y: np.ndarray) -> float:
    """Between-class variance share of a numeric target (0..1)."""
    y = np.asarray(y, dtype=float)
    total = y.var()
    if total == 0:
        return 0.0
    s = pd.Series(y)
    g = s.groupby(pd.Series(cls))
    between = (g.size() * (g.mean() - y.mean()) ** 2).sum() / len(y)
    return float(between / total)


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Rank correlation, numpy-only."""
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    ra -= ra.mean()
    rb -= rb.mean()
    denom = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / denom) if denom else float("nan")


def _class_ids(n_classes: int) -> list[int]:
    c = n_classes // 2
    return list(range(-c, c + 1))


def _rates(cls, y, ids) -> tuple[dict, float, int]:
    """Per-class positive rate over non-NaN label rows + base rate + n."""
    ok = ~np.isnan(y)
    cls, y = cls[ok], y[ok]
    rate = {}
    for i in ids:
        sel = cls == i
        rate[str(i)] = float(y[sel].mean()) if sel.any() else None
    base = float(y.mean()) if len(y) else float("nan")
    return rate, base, int(ok.sum())


def evaluate(classes: np.ndarray, labels: pd.DataFrame, n_classes: int) -> dict:
    ids = _class_ids(n_classes)
    center = n_classes // 2
    population = {str(i): int((classes == i).sum()) for i in ids}

    out_labels = {}
    for key in labels.columns:
        y = labels[key].to_numpy(dtype=float)
        rate, base, n = _rates(classes, y, ids)
        ok = ~np.isnan(y)
        out_labels[key] = {
            "n": n,
            "base_rate": base,
            "rate": rate,
            "lift": {k: (None if r is None or base == 0 else r / base)
                     for k, r in rate.items()},
            "mi": mutual_information(classes[ok], y[ok]),
            "eta2": eta_squared(classes[ok], y[ok]),
        }

    out_pairs = {}
    for kind, hn in LABEL_PAIRS:
        rl = out_labels[f"{kind}_n{hn}_long"]["rate"]
        rs = out_labels[f"{kind}_n{hn}_short"]["rate"]
        spread = {str(i): (None if rl[str(i)] is None or rs[str(i)] is None
                           else rl[str(i)] - rs[str(i)]) for i in ids}
        known = [(i, spread[str(i)]) for i in ids if spread[str(i)] is not None]
        rho = spearman(np.array([i for i, _ in known], dtype=float),
                       np.array([s for _, s in known], dtype=float)) \
            if len(known) >= 3 else float("nan")

        flip = None
        if n_classes == 7:
            flip = {}
            for name, sign in (("neg", -1), ("pos", 1)):
                strong = spread[str(sign * (center - 1))]
                extra = spread[str(sign * center)]
                have = strong is not None and extra is not None
                flip[name] = {
                    "strong": strong,
                    "extra": extra,
                    "sign_flip": bool(np.sign(strong) != np.sign(extra)) if have else None,
                    "shrink": (abs(extra) < abs(strong)) if have else None,
                }
        out_pairs[f"{kind}_n{hn}"] = {
            "spread": spread, "monotonicity_rho": rho, "flip": flip,
        }

    return {
        "n_rows": int(len(classes)),
        "population": population,
        "labels": out_labels,
        "pairs": out_pairs,
    }
```

- [ ] **Step 4: run tests, verify pass**

Run: `python3 -m pytest tests/unit/experiments/test_rps_metrics.py -q`
Expected: 6 passed.

- [ ] **Step 5: checkpoint — report changed files (NO commit)**
