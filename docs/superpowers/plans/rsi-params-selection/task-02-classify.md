# task-02 — cut fitting + class assignment

**Files:**
- Create: `experiments/rsi_params_selection/classify.py`
- Test: `tests/unit/experiments/test_rps_classify.py`

**Interfaces:**
- Consumes: `config.QUANTILE_CUTS`, `config.SYM0_K`, `config.ZSCORE_K`.
- Produces:
  - `classify.fit_cuts(x: np.ndarray, technique: str, n_classes: int) -> np.ndarray` — ascending cut array, len `n_classes - 1`; fit values must be NaN-free.
  - `classify.apply_cuts(x: np.ndarray, cuts: np.ndarray) -> np.ndarray` — centered int class ids: 5-class → −2..2, 7-class → −3..3 (0 = neutral). Raises `ValueError` on NaN input.

- [ ] **Step 1: write failing tests**

`tests/unit/experiments/test_rps_classify.py`:

```python
import numpy as np
import pytest

from experiments.rsi_params_selection.classify import apply_cuts, fit_cuts


def _x():
    return np.random.default_rng(1).normal(0.5, 2.0, 100_000)  # off-center on purpose


def test_quantile_5_balanced_populations():
    x = _x()
    cuts = fit_cuts(x, "quantile", 5)
    assert len(cuts) == 4 and np.all(np.diff(cuts) > 0)
    cls = apply_cuts(x, cuts)
    share = np.bincount(cls + 2, minlength=5) / len(x)
    assert np.allclose(share, [0.10, 0.20, 0.40, 0.20, 0.10], atol=0.01)


def test_quantile_7_extra_tail_share():
    x = _x()
    cls = apply_cuts(x, fit_cuts(x, "quantile", 7))
    share = np.bincount(cls + 3, minlength=7) / len(x)
    assert abs(share[0] - 0.02) < 0.005 and abs(share[6] - 0.02) < 0.005


def test_sym0_centered_on_zero_not_mean():
    x = _x()  # mean 0.5 — sym0 must ignore it
    cuts = fit_cuts(x, "sym0", 5)
    s = x.std()
    assert np.allclose(cuts, [-1.0 * s, -0.3 * s, 0.3 * s, 1.0 * s], rtol=1e-6)


def test_zscore_centered_on_mean():
    x = _x()
    cuts = fit_cuts(x, "zscore", 7)
    mu, s = x.mean(), x.std()
    want = [mu - 2 * s, mu - 1 * s, mu - 0.5 * s,
            mu + 0.5 * s, mu + 1 * s, mu + 2 * s]
    assert np.allclose(cuts, want, rtol=1e-6)


def test_apply_cuts_centered_ids_and_boundaries():
    cuts = np.array([-1.0, -0.3, 0.3, 1.0])
    cls = apply_cuts(np.array([-5.0, -0.5, 0.0, 0.5, 5.0]), cuts)
    assert cls.tolist() == [-2, -1, 0, 1, 2]


def test_apply_cuts_rejects_nan():
    with pytest.raises(ValueError):
        apply_cuts(np.array([0.0, np.nan]), np.array([-1.0, -0.3, 0.3, 1.0]))


def test_fit_cuts_unknown_technique():
    with pytest.raises(ValueError):
        fit_cuts(np.zeros(10), "tree", 5)
```

- [ ] **Step 2: run tests, verify fail**

Run: `python3 -m pytest tests/unit/experiments/test_rps_classify.py -q`
Expected: FAIL — `ModuleNotFoundError` / `ImportError: classify`

- [ ] **Step 3: implement**

`experiments/rsi_params_selection/classify.py`:

```python
"""Cut fitting + class assignment for rsi_maN_diff values.

Techniques (spec §4):
  quantile — percentile cuts of the fit distribution.
  sym0     — symmetric around ZERO: 0 ± k·std (neutral = flat slope).
  zscore   — symmetric around the MEAN: mean ± k·std (legacy _five_tiers family).

Class ids are centered ints: 5-class → −2..2, 7-class → −3..3; 0 = neutral,
negative = falling RSI ma, positive = rising.
"""
import numpy as np

from .config import QUANTILE_CUTS, SYM0_K, ZSCORE_K


def fit_cuts(x: np.ndarray, technique: str, n_classes: int) -> np.ndarray:
    """Ascending cut array (len n_classes−1) fit on NaN-free values."""
    x = np.asarray(x, dtype=float)
    if np.isnan(x).any():
        raise ValueError("fit_cuts: NaN in fit values — drop them first")
    if technique == "quantile":
        return np.percentile(x, QUANTILE_CUTS[n_classes])
    if technique == "sym0":
        k = np.asarray(SYM0_K[n_classes], dtype=float)
        s = float(x.std())
        return np.concatenate([-k[::-1] * s, k * s])
    if technique == "zscore":
        k = np.asarray(ZSCORE_K[n_classes], dtype=float)
        mu, s = float(x.mean()), float(x.std())
        return np.concatenate([mu - k[::-1] * s, mu + k * s])
    raise ValueError(f"unknown technique {technique!r}")


def apply_cuts(x: np.ndarray, cuts: np.ndarray) -> np.ndarray:
    """Centered class ids via np.digitize. NaN input is a caller bug."""
    x = np.asarray(x, dtype=float)
    if np.isnan(x).any():
        raise ValueError("apply_cuts: NaN in values — drop them first")
    n_classes = len(cuts) + 1
    return np.digitize(x, cuts) - n_classes // 2
```

- [ ] **Step 4: run tests, verify pass**

Run: `python3 -m pytest tests/unit/experiments/test_rps_classify.py -q`
Expected: 7 passed.

- [ ] **Step 5: checkpoint — report changed files (NO commit)**
