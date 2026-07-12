# Precision@k Promotion Gate (toggleable) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a config-selectable promotion gate so an NN search/lineage run optimises **long-class precision@5%** (rare-positive `direction_binary` target) instead of argmax accuracy, with a single switch to fall back to the legacy accuracy gate.

**Architecture:** The gate scalar is `holdout_score`, produced entirely by `TrainingLoop._score_predictions` (holdout scorer). A new pure `precision_at_k` helper computes the metric; a `gate_metric` config value (default `"accuracy"`) threads from `configs/nn_search.yaml` / `NN_GATE_METRIC` env through `TrainingLoop.search_config` → `evaluate_on_holdout` → `_score_predictions`, which branches the `direction_binary` head between argmax accuracy and precision@5%. No tracker, checkpoint, or spec changes are required for the gate to switch.

**Tech Stack:** Python 3, numpy (metric), PyTorch/Optuna (training image only), pytest. All code and tests run inside the `nn-train` Docker service (`simple_trader_nn` image).

## Global Constraints

- Base branch is `experimental_imp_2`. Create a dedicated branch `nn-precision-at-k-gate` off it; merge back into it.
- **Default `gate_metric = "accuracy"`** — the toggle is opt-in; an unconfigured run keeps legacy behaviour byte-for-byte.
- `gate_metric` ∈ `{"accuracy", "precision_at_k"}` only; any other value fails fast at config load.
- Do **NOT** add `gate_metric` (or any evaluation field) to `NNModelSpec` — it would change `spec_hash` and break tensor-cache reuse, checkpoint dirs, and study naming. It is an evaluation concern; it lives in `nn_search.yaml` / env.
- The gate metric constant `PRECISION_AT_K_FRAC = 0.05` and the metric helpers live in `nn/training_loop.py`, **not** `constants.py` (that file is for cross-module domain constants with zero project imports).
- precision@k applies to `direction_binary` heads only. `direction`, `label`, and `regression` heads keep their existing scoring in both modes.
- All pytest and training runs execute in the `nn-train` image (torch/optuna are not installed on the host). Command: `docker compose run --rm nn-train python3 -m pytest <path> -v`.
- This plan, the spec, and version reports live in the external docs repo — never commit them into the code repo (`main/`).
- The lineage `decide` margin stays `0.01`; no code change (precision ∈ [0,1], 1pp is a meaningful step).

---

## Design discrepancies resolved during scoping (read before starting)

Tracing the live code (branch `experimental_imp_2`) surfaced three deviations from
`2026-07-05-precision-at-k-gate-design.md`. This plan implements the corrected scope;
**update the spec to match after the branch merges.**

1. **Spec site #2 (checkpoint → `val_loss`, mode=min) is a NO-OP for the gate — EXCLUDED.**
   `evaluate_on_holdout` scores the **in-memory, just-trained model** from
   `orchestrator.trained_models` ([training_loop.py:520-537](../../../../main/nn/training_loop.py#L520)),
   before any `_best.pt` write and never reading a checkpoint. In search mode the
   per-trial auto-gate is neutralised (`cm.best_metric = float("inf")`,
   [nn_orchestrator.py:163-170](../../../../main/nn/nn_orchestrator.py#L163)) and `_best.pt`
   is authored only by `_maybe_promote(..., promote=True)`
   ([training_loop.py:346-357](../../../../main/nn/training_loop.py#L346)), gated by
   `tracker.is_improvement` — the holdout scalar, not `val_accuracy`. So changing the
   checkpoint metric changes only *which weights persist for later inference*, not the
   gate. It is out of scope here. (A real "persist the best epoch" change is larger than
   the spec implies and belongs in a separate plan.)

2. **Checkpoint `mode="min"|"max"` + `metric` params already exist**
   ([checkpoint_manager.py:28-72](../../../../main/nn/checkpoint_manager.py#L28)). The
   spec's "add a mode param" implementation note is stale. No checkpoint edit is needed.

3. **`_accuracy_counts` (train-side scorer) need NOT change.** It feeds per-epoch
   train/val *display* accuracy only, not the gate
   ([nn_model.py:620-643](../../../../main/nn/nn_model.py#L620)). The
   [[project_nn_two_scorers]] rule triggers when adding a new *target kind*; precision@k
   is a new *scoring rule* for the existing `direction_binary` kind, so only the holdout
   scorer changes.

**Net blast radius:** one pure helper trio + one constant + one config field + one
branch in `_score_predictions` + its `evaluate_on_holdout` forwarding line + tests.

---

## Docker Entry Points

These commands are the ground truth; the implementation must make them work.

```bash
# Run the nn unit + integration tests (all tasks below)
docker compose run --rm nn-train python3 -m pytest tests/unit/nn/test_training_loop.py -v
docker compose run --rm nn-train python3 -m pytest tests/nn/test_search_config_values.py -v

# Launch a search run with the NEW gate (opt-in via env; no yaml edit needed)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml run --rm \
  -e NN_GATE_METRIC=precision_at_k \
  -e NN_SPEC_PATH=configs/nn_spec.yaml \
  -e NN_STUDY=link_usdt_precision_v1 \
  -e NN_TRAIN_MODE=search \
  nn-train

# Launch with the OLD gate (default — env omitted, or explicitly)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml run --rm \
  -e NN_GATE_METRIC=accuracy \
  -e NN_SPEC_PATH=configs/nn_spec.yaml -e NN_STUDY=link_usdt_baseline -e NN_TRAIN_MODE=search \
  nn-train
```

Verified: [ ] `docker compose run --rm nn-train python3 -c "import torch, optuna"` succeeds.

---

## Layer 2: Training Pipeline (promotion gate)

### Interface (signatures only — no bodies)

```python
# nn/training_loop.py — module level, beside HOLDOUT_EVAL_CHUNK (~line 56)

PRECISION_AT_K_FRAC: float = 0.05
GATE_METRIC_ACCURACY: str = "accuracy"
GATE_METRIC_PRECISION_AT_K: str = "precision_at_k"
VALID_GATE_METRICS: tuple[str, ...] = (GATE_METRIC_ACCURACY, GATE_METRIC_PRECISION_AT_K)

def precision_at_k(
    p_long: np.ndarray, y_long: np.ndarray, k_frac: float = PRECISION_AT_K_FRAC
) -> float: ...

def long_base_rate(y_long: np.ndarray) -> float: ...

def lift(precision: float, base_rate: float) -> float: ...


class TrainingLoop:
    # reads self.search_config["gate_metric"] and forwards it
    def evaluate_on_holdout(self, spec, df, data_attributes) -> dict: ...

    @staticmethod
    def _score_predictions(
        spec, preds: np.ndarray, y: np.ndarray, gate_metric: str = GATE_METRIC_ACCURACY
    ): ...  # returns (overall_mean, per_target)


# training/trainer.py
class Trainer:
    # adds gate_metric env override + fail-fast validation
    def _load_nn_search_config(self) -> dict: ...
```

`direction_binary` head column layout (confirmed by
[test_training_loop.py:563](../../../../main/tests/unit/nn/test_training_loop.py#L563)):
`preds[:, 0]` = long score, `preds[:, 1]` = other. So `p_long = preds[:,0] - preds[:,1]`
and `y_long = y[:, 0]` (1 = truly long).

---

### Task 1: Pure metric helpers + constant

The metric is pure numpy, unit-testable with no torch or model. Build it first.

**Files:**
- Modify: `main/nn/training_loop.py` (add constants ~line 56, helpers after `_chunked_predict` ~line 80)
- Test: `main/tests/unit/nn/test_training_loop.py` (new classes `TestPrecisionAtK`, `TestLongBaseRate`, `TestLift`)

**Interfaces:**
- Produces: `precision_at_k(p_long, y_long, k_frac=0.05) -> float`, `long_base_rate(y_long) -> float`, `lift(precision, base_rate) -> float`, and constants `PRECISION_AT_K_FRAC`, `GATE_METRIC_*`, `VALID_GATE_METRICS`.

- [ ] **Step 1: Write the failing tests**

Append to `main/tests/unit/nn/test_training_loop.py` (imports at top of file already include `numpy as np` and `pytest`; add the symbols to the existing `from nn.training_loop import ...`):

```python
from nn.training_loop import precision_at_k, long_base_rate, lift


class TestPrecisionAtK:
    def test_perfect_ranking_top_all_long(self):
        p = np.array([0.9, 0.8, 0.1, 0.2])
        y = np.array([1.0, 1.0, 0.0, 0.0])
        # k = ceil(0.5*4) = 2; top-2 by score are both long → 1.0
        assert precision_at_k(p, y, k_frac=0.5) == 1.0

    def test_all_negative_zero(self):
        p = np.array([0.9, 0.8, 0.1, 0.2])
        y = np.zeros(4)
        assert precision_at_k(p, y, k_frac=0.5) == 0.0

    def test_k_ceil_rounding(self):
        p = np.arange(10, 0, -1).astype(float)  # 10..1 descending
        y = np.zeros(10); y[0] = 1.0
        # k = ceil(0.05*10) = 1 → top-1 is the single long → 1.0
        assert precision_at_k(p, y, k_frac=0.05) == 1.0

    def test_k_ge_n_uses_all_rows(self):
        p = np.array([1.0, 2.0, 3.0])
        y = np.array([1.0, 0.0, 1.0])
        assert precision_at_k(p, y, k_frac=1.0) == pytest.approx(2 / 3)

    def test_empty_returns_zero(self):
        assert precision_at_k(np.array([]), np.array([])) == 0.0

    def test_ties_stable_sort(self):
        p = np.array([0.5, 0.5, 0.5, 0.5])
        y = np.array([1.0, 0.0, 0.0, 0.0])
        # all tied; k=1; stable sort keeps index 0 first → the long → 1.0
        assert precision_at_k(p, y, k_frac=0.05) == 1.0

    def test_nan_labels_dropped(self):
        p = np.array([0.9, 0.8, 0.1])
        y = np.array([1.0, np.nan, 0.0])
        # valid rows {0:long, 2:other}; k=ceil(0.5*2)=1 → top-1 idx0 long → 1.0
        assert precision_at_k(p, y, k_frac=0.5) == 1.0


class TestLongBaseRate:
    def test_fraction_long_ignoring_nan(self):
        y = np.array([1.0, 0.0, np.nan, 1.0])
        assert long_base_rate(y) == pytest.approx(2 / 3)

    def test_all_nan_returns_zero(self):
        assert long_base_rate(np.array([np.nan, np.nan])) == 0.0


class TestLift:
    def test_normal(self):
        assert lift(0.5, 0.1) == pytest.approx(5.0)

    def test_zero_base_rate_returns_zero(self):
        assert lift(0.5, 0.0) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm nn-train python3 -m pytest tests/unit/nn/test_training_loop.py -k "PrecisionAtK or LongBaseRate or Lift" -v`
Expected: FAIL — `ImportError: cannot import name 'precision_at_k'`.

- [ ] **Step 3: Add the constants**

In `main/nn/training_loop.py`, directly after the `HOLDOUT_EVAL_CHUNK` block (line 56):

```python
#: Top-fraction of bars (ranked by long score) used for the precision@k gate.
#: Single edit point to retune k.
PRECISION_AT_K_FRAC: float = 0.05

#: Promotion/search gate metric selector. "accuracy" preserves the legacy argmax
#: gate; "precision_at_k" optimises long-class precision on rare-positive targets.
GATE_METRIC_ACCURACY: str = "accuracy"
GATE_METRIC_PRECISION_AT_K: str = "precision_at_k"
VALID_GATE_METRICS: tuple[str, ...] = (GATE_METRIC_ACCURACY, GATE_METRIC_PRECISION_AT_K)
```

- [ ] **Step 4: Add the helpers**

In `main/nn/training_loop.py`, after `_chunked_predict` (ends line 79):

```python
def precision_at_k(
    p_long: np.ndarray, y_long: np.ndarray, k_frac: float = PRECISION_AT_K_FRAC
) -> float:
    """Precision within the top ``k_frac`` of rows ranked by long score.

    ``p_long`` = per-row long score (higher = more long, e.g. the logit margin
    ``preds[:,0] - preds[:,1]``). ``y_long`` = 0/1 truth (1 = truly long). Rows
    with NaN in either array are dropped. Returns ``TP / k`` over the top
    ``k = ceil(k_frac * N_valid)`` rows (stable sort for ties). Degenerate input
    (no valid rows) → ``0.0``.
    """
    p = np.asarray(p_long, dtype=np.float64).ravel()
    y = np.asarray(y_long, dtype=np.float64).ravel()
    valid = ~np.isnan(p) & ~np.isnan(y)
    p = p[valid]
    y = y[valid]
    n = p.shape[0]
    if n == 0:
        return 0.0
    k = int(np.ceil(k_frac * n))
    k = max(1, min(k, n))
    order = np.argsort(-p, kind="stable")
    top = order[:k]
    tp = float((y[top] == 1.0).sum())
    return tp / k


def long_base_rate(y_long: np.ndarray) -> float:
    """Fraction of valid (non-NaN) rows that are truly long. Empty → ``0.0``."""
    y = np.asarray(y_long, dtype=np.float64).ravel()
    valid = ~np.isnan(y)
    if not valid.any():
        return 0.0
    return float((y[valid] == 1.0).mean())


def lift(precision: float, base_rate: float) -> float:
    """``precision / base_rate``; ``0.0`` when ``base_rate <= 0`` (no div-by-zero)."""
    if base_rate <= 0.0:
        return 0.0
    return precision / base_rate
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose run --rm nn-train python3 -m pytest tests/unit/nn/test_training_loop.py -k "PrecisionAtK or LongBaseRate or Lift" -v`
Expected: PASS (11 tests).

- [ ] **Step 6: Commit**

```bash
git add main/nn/training_loop.py main/tests/unit/nn/test_training_loop.py
git commit -m "feat(nn): add pure precision_at_k / lift metric helpers"
```

---

### Task 2: `gate_metric` config toggle + validation

Wire the switch into the config surface `TrainingLoop` already reads
(`self.search_config`), sourced from `configs/nn_search.yaml` with a `NN_GATE_METRIC`
env override — matching the existing `_override(...)` pattern.

**Files:**
- Modify: `main/configs/nn_search.yaml` (add one line)
- Modify: `main/training/trainer.py:392-417` (`_load_nn_search_config`)
- Test: `main/tests/nn/test_search_config_values.py` (new tests)

**Interfaces:**
- Consumes: constants `GATE_METRIC_ACCURACY`, `VALID_GATE_METRICS` from Task 1.
- Produces: `_load_nn_search_config()` returns a dict where `gate_metric` is a validated string in `VALID_GATE_METRICS`.

- [ ] **Step 1: Write the failing tests**

Append to `main/tests/nn/test_search_config_values.py`:

```python
import pytest
from training.trainer import Trainer


def _loader(tmp_path, yaml_text):
    (tmp_path / "nn_search.yaml").write_text(yaml_text)
    t = Trainer.__new__(Trainer)  # bypass full init; loader only uses self.config_path
    t.config_path = str(tmp_path)
    return t._load_nn_search_config


def test_gate_metric_defaults_to_accuracy_when_absent(tmp_path):
    cfg = _loader(tmp_path, "margin: 0.01\n")()
    assert cfg.get("gate_metric", "accuracy") == "accuracy"  # no crash, absent is fine


def test_gate_metric_from_yaml(tmp_path):
    cfg = _loader(tmp_path, "gate_metric: precision_at_k\n")()
    assert cfg["gate_metric"] == "precision_at_k"


def test_gate_metric_env_overrides_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("NN_GATE_METRIC", "precision_at_k")
    cfg = _loader(tmp_path, "gate_metric: accuracy\n")()
    assert cfg["gate_metric"] == "precision_at_k"


def test_gate_metric_invalid_raises(tmp_path):
    with pytest.raises(ValueError, match="gate_metric"):
        _loader(tmp_path, "gate_metric: bogus\n")()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm nn-train python3 -m pytest tests/nn/test_search_config_values.py -k gate_metric -v`
Expected: FAIL — env override test fails (no `NN_GATE_METRIC` handling) and invalid test fails (no validation raised).

- [ ] **Step 3: Add the yaml default**

In `main/configs/nn_search.yaml`, add near `margin`:

```yaml
gate_metric: accuracy   # accuracy | precision_at_k  (promotion + search gate)
```

- [ ] **Step 4: Add the override + validation**

In `main/training/trainer.py`, inside `_load_nn_search_config` after the existing
`_override(...)` calls and before `return cfg` (around line 416):

```python
        _override("gate_metric", "NN_GATE_METRIC", str)
        gate_metric = cfg.get("gate_metric", "accuracy")
        if gate_metric not in ("accuracy", "precision_at_k"):
            raise ValueError(
                "gate_metric must be 'accuracy' or 'precision_at_k', "
                f"got {gate_metric!r}"
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose run --rm nn-train python3 -m pytest tests/nn/test_search_config_values.py -k gate_metric -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add main/configs/nn_search.yaml main/training/trainer.py main/tests/nn/test_search_config_values.py
git commit -m "feat(nn): add gate_metric toggle to nn_search config (env NN_GATE_METRIC)"
```

---

### Task 3: Branch `_score_predictions` on `gate_metric` + forward from `evaluate_on_holdout`

This is the load-bearing change: the same synthetic `direction_binary` head scores
argmax accuracy under `"accuracy"` and precision@5% under `"precision_at_k"`.

**Files:**
- Modify: `main/nn/training_loop.py` — `_score_predictions` (552-594) and
  `evaluate_on_holdout` forwarding line (538)
- Test: `main/tests/unit/nn/test_training_loop.py` (new class `TestScorePredictionsPrecisionGate`)

**Interfaces:**
- Consumes: `precision_at_k`, `long_base_rate`, `lift`, `GATE_METRIC_*` (Task 1);
  `self.search_config["gate_metric"]` (Task 2).
- Produces: `_score_predictions(..., gate_metric)` where, for a `direction_binary`
  head under `"precision_at_k"`, `per_target[name]` = precision@5% (the gate scalar) and
  `per_target[f"{name}__p@1|p@5|p@10"]`, `per_target[f"{name}__lift@1|lift@5|lift@10"]`
  carry the report metrics. `overall` is the mean of head scores, as today.

- [ ] **Step 1: Write the failing tests**

Append to `main/tests/unit/nn/test_training_loop.py`:

```python
from nn.nn_model_spec import NNModelSpec, TargetSpec
from nn.training_loop import (
    TrainingLoop,
    GATE_METRIC_PRECISION_AT_K,
)


def _binary_spec():
    return NNModelSpec(
        name="t",
        targets=[
            TargetSpec(name="long15", kind="direction_binary", horizons=[15], side="long")
        ],
    )


class TestScorePredictionsPrecisionGate:
    # 4 rows: cols = [prob_long, prob_other]; y col0 = long truth.
    Y = np.array([[1, 0], [0, 1], [1, 0], [0, 1]], dtype=float)
    PREDS = np.array(
        [[0.9, 0.1], [0.8, 0.2], [0.3, 0.7], [0.1, 0.9]], dtype=float
    )  # long-margin ranking: row0 > row1 > row2 > row3

    def test_precision_gate_scores_top_k(self):
        overall, per_target = TrainingLoop._score_predictions(
            _binary_spec(), self.PREDS, self.Y, GATE_METRIC_PRECISION_AT_K
        )
        # k = ceil(0.05*4) = 1; top-margin row0 has y_long=1 → precision@5% = 1.0
        assert per_target["long15"] == 1.0
        assert per_target["long15__p@5"] == 1.0
        assert per_target["long15__lift@5"] == pytest.approx(1.0 / 0.5)  # base_rate 0.5
        assert "long15__p@1" in per_target and "long15__p@10" in per_target
        assert overall == 1.0

    def test_accuracy_gate_is_default_and_unchanged(self):
        overall, per_target = TrainingLoop._score_predictions(
            _binary_spec(), self.PREDS, self.Y
        )
        # argmax: row0 pred0==y0 ✓, row1 pred1==y1 ✓, row2 pred1 vs y0 ✗, row3 pred1==y1 ✓
        assert per_target["long15"] == 0.75
        assert overall == 0.75
        assert "long15__p@5" not in per_target  # no report extras in accuracy mode
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm nn-train python3 -m pytest tests/unit/nn/test_training_loop.py -k PrecisionGate -v`
Expected: FAIL — `_score_predictions()` takes 3 positional args, not 4 (`gate_metric` unknown).

- [ ] **Step 3: Add the `gate_metric` parameter + branch**

In `main/nn/training_loop.py`, change the signature (line 553) and the
`direction`/`direction_binary` branch (569-575). Replace:

```python
    @staticmethod
    def _score_predictions(spec, preds: np.ndarray, y: np.ndarray):
```

with:

```python
    @staticmethod
    def _score_predictions(
        spec, preds: np.ndarray, y: np.ndarray, gate_metric: str = GATE_METRIC_ACCURACY
    ):
```

and replace the direction branch body (lines 569-575):

```python
                if target.kind in ("direction", "direction_binary"):
                    width = 3 if target.kind == "direction" else 2
                    p = preds[:, offset : offset + width]
                    t = y[:, offset : offset + width]
                    acc = float((p.argmax(axis=1) == t.argmax(axis=1)).mean())
                    per_target[target.name] = acc
                    head_scores.append(acc)
```

with:

```python
                if target.kind in ("direction", "direction_binary"):
                    width = 3 if target.kind == "direction" else 2
                    p = preds[:, offset : offset + width]
                    t = y[:, offset : offset + width]
                    if (
                        gate_metric == GATE_METRIC_PRECISION_AT_K
                        and target.kind == "direction_binary"
                    ):
                        p_long = p[:, 0] - p[:, 1]
                        y_long = t[:, 0]
                        base = long_base_rate(y_long)
                        for frac, tag in ((0.01, "1"), (0.05, "5"), (0.10, "10")):
                            pk = precision_at_k(p_long, y_long, frac)
                            per_target[f"{target.name}__p@{tag}"] = pk
                            per_target[f"{target.name}__lift@{tag}"] = lift(pk, base)
                        score = per_target[f"{target.name}__p@5"]
                        per_target[target.name] = score
                        head_scores.append(score)
                    else:
                        acc = float((p.argmax(axis=1) == t.argmax(axis=1)).mean())
                        per_target[target.name] = acc
                        head_scores.append(acc)
```

Also update the docstring (554-559) to note the `gate_metric` branch (one line:
`"direction_binary under gate_metric='precision_at_k' → long-class precision@5%"`).

- [ ] **Step 4: Forward `gate_metric` from `evaluate_on_holdout`**

In `main/nn/training_loop.py`, add the config read once before the loop (after line 523)
and pass it at the call site (line 538). Replace line 538:

```python
            score, target_scores = self._score_predictions(spec, preds, y)
```

with (and add the `gate_metric = ...` read just before `for group_key, model in trained.items():` at line 525):

```python
        gate_metric = str(self.search_config.get("gate_metric", GATE_METRIC_ACCURACY))
```

```python
            score, target_scores = self._score_predictions(spec, preds, y, gate_metric)
```

- [ ] **Step 5: Run the whole training-loop test file to verify pass + no regression**

Run: `docker compose run --rm nn-train python3 -m pytest tests/unit/nn/test_training_loop.py -v`
Expected: PASS — new `PrecisionGate` tests pass; the existing
`TestScorePredictionsDirectionBinary` and `test_pure_optuna_records_holdout_scores`
(asserts `0.0 <= holdout_score <= 1.0` — precision@5% stays in range) still pass.

- [ ] **Step 6: Commit**

```bash
git add main/nn/training_loop.py main/tests/unit/nn/test_training_loop.py
git commit -m "feat(nn): gate direction_binary holdout score on gate_metric (precision@5%)"
```

---

### Task 4: Integration test — config value flips the gate end-to-end (Docker)

Proves the wire `search_config["gate_metric"]` → `evaluate_on_holdout` →
`_score_predictions` actually changes the returned `holdout_score`, using fakes so no
dataset build or torch model is needed. Written to fail before Task 3's forwarding line
exists.

**Files:**
- Test: `main/tests/unit/nn/test_training_loop.py` (new class `TestEvaluateForwardsGateMetric`)

**Interfaces:**
- Consumes: `evaluate_on_holdout` reading `self.search_config["gate_metric"]` (Task 3),
  and the module-level `NNDataset` symbol / `_chunked_predict` (monkeypatched).

- [ ] **Step 1: Write the failing test**

Append to `main/tests/unit/nn/test_training_loop.py`:

```python
from nn import training_loop as tl_mod


class _FakeGroupView:
    def __init__(self, X, y):
        self._X, self._y = X, y

    def tensors(self):
        return self._X, self._y


class _FakeSplit:
    def __init__(self, X, y):
        self._gv = _FakeGroupView(X, y)

    def group(self, key):
        return self._gv


class _FakeDataset:
    def __init__(self, X, y):
        self._split = _FakeSplit(X, y)

    def split(self, name):
        return self._split


class _FakeModel:
    def __init__(self, preds):
        self._preds = preds

    def run_batch(self, X):
        return self._preds[: len(X)]


class _FakeOrch:
    dataset_dir = "/tmp"

    def __init__(self, preds):
        self.trained_models = {"long": _FakeModel(preds)}


class TestEvaluateForwardsGateMetric:
    X = np.zeros((4, 1, 2), dtype=np.float32)  # (rows, T, F); F must equal head width 2
    Y = np.array([[1, 0], [0, 1], [1, 0], [0, 1]], dtype=np.float64)
    PREDS = np.array([[0.9, 0.1], [0.8, 0.2], [0.3, 0.7], [0.1, 0.9]], dtype=np.float64)

    def _loop(self, gate_metric, monkeypatch):
        monkeypatch.setattr(
            tl_mod.NNDataset, "build",
            staticmethod(lambda *a, **k: _FakeDataset(self.X, self.Y)),
        )
        tl = TrainingLoop.__new__(TrainingLoop)
        tl.orchestrator = _FakeOrch(self.PREDS)
        tl.search_config = {"gate_metric": gate_metric}
        return tl

    def test_precision_gate_flips_holdout_score(self, monkeypatch):
        tl = self._loop(GATE_METRIC_PRECISION_AT_K, monkeypatch)
        out = tl.evaluate_on_holdout(_binary_spec(), df=None, data_attributes=None)
        assert out["holdout_score"] == 1.0            # precision@5% of top-margin row
        assert out["per_target"]["long15__p@5"] == 1.0

    def test_accuracy_gate_holdout_score(self, monkeypatch):
        tl = self._loop("accuracy", monkeypatch)
        out = tl.evaluate_on_holdout(_binary_spec(), df=None, data_attributes=None)
        assert out["holdout_score"] == 0.75           # argmax accuracy
```

- [ ] **Step 2: Run to verify RED (before Task 3 forwarding, this is the layer integration RED)**

Run: `docker compose run --rm nn-train python3 -m pytest tests/unit/nn/test_training_loop.py -k EvaluateForwardsGateMetric -v`
Expected (if run before Task 3): FAIL — `evaluate_on_holdout` calls `_score_predictions`
without `gate_metric`, so the precision test returns 0.75, not 1.0. After Task 3 it is GREEN.

- [ ] **Step 3: Run to verify GREEN (after Task 3 is merged)**

Run: `docker compose run --rm nn-train python3 -m pytest tests/unit/nn/test_training_loop.py -k EvaluateForwardsGateMetric -v`
Expected: PASS (2 tests).

- [ ] **Step 4: Full nn unit suite — no regressions**

Run: `docker compose run --rm nn-train python3 -m pytest tests/unit/nn tests/nn -q`
Expected: PASS (existing suite + all new tests).

- [ ] **Step 5: Commit**

```bash
git add main/tests/unit/nn/test_training_loop.py
git commit -m "test(nn): integration test — gate_metric flips holdout_score end-to-end"
```

---

### Task 5: Docker-verified baseline on the existing v2 checkpoint (record, no code)

Reproduce precision@5% on the existing `nn-features-only` v2 winner so the reports carry
a real starting number, and confirm the toggle switches gates on a live run.

**Files:** none (verification + external report only).

- [ ] **Step 1: Score the existing v2 checkpoint under both gates**

Launch a `NN_TRAIN_MODE=search` run twice (or a single-trial re-score) seeded from the v2
arch — once with `NN_GATE_METRIC=accuracy`, once with `NN_GATE_METRIC=precision_at_k` —
using the Docker Entry Points commands above. Capture from each run's `per_target`:
`long15` (gate scalar), `long15__p@1/p@5/p@10`, `long15__lift@1/5/10`.

- [ ] **Step 2: Cross-check against the ad-hoc recompute**

Confirm the numbers are internally consistent: the prior ad-hoc `long precision 0.138`
was the global top-of-ranking figure; precision@5% is a distinct (higher) number on the
top-5% slice. Record base_rate ≈ 0.0578 and the resulting lift.

- [ ] **Step 3: Write the baseline into the external version report**

Record the precision@{1,5,10%}+lift baseline and the accuracy-gate scalar side by side in
the `nn-features-precision` v1 report (external docs repo). Update
`2026-07-05-precision-at-k-gate-design.md` to reflect the three design discrepancies
resolved above (checkpoint site #2 excluded, mode param pre-existing, `_accuracy_counts`
untouched).

---

## Self-Review

**Spec coverage** (against `2026-07-05-precision-at-k-gate-design.md`):
- Metric `precision_at_k(p_long, y_long, k_frac=0.05) -> float`, `p_long = preds[:,0]-preds[:,1]`, rank/top-k/TP-over-k, lift, all edge cases (N==0, ties, k>=N, base_rate==0, NaN) → **Task 1**. ✓
- `PRECISION_AT_K_FRAC = 0.05` module constant → **Task 1**. ✓
- Wiring site 1 (`_score_predictions` gate scalar = precision@5%, records p@{1,5,10}+lift in `per_target`) → **Task 3**. ✓
- Wiring site 2 (checkpoint `val_loss`/min) → **excluded with justification** (Design discrepancies §1); flagged for spec revision in Task 5. ✓ (deliberate deviation)
- Wiring site 3 (`decide` margin stays 0.01) → no code change (Global Constraints). ✓
- Iterate / new lineage `nn-features-precision` seeded from v2 → out of code scope; baseline recorded in **Task 5**, evolution runs via the existing `nn-evolve` skill under the new gate. ✓
- Testing: unit for `precision_at_k` (all listed cases) → Task 1; regression on existing `_score_predictions` accuracy tests (default path unchanged) → Task 3 Step 5; Docker-verified baseline on v2 checkpoint → Task 5. ✓
- **Added beyond spec:** the `gate_metric` toggle (user requirement) → Tasks 2 & 4, default `accuracy` = legacy behaviour.

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". Every code step shows full code; every run step shows the command and expected result.

**Type consistency:** `precision_at_k`, `long_base_rate`, `lift` signatures identical across Tasks 1/3/4. `_score_predictions(spec, preds, y, gate_metric)` and its call site match (Task 3 Steps 3–4). `gate_metric` string values (`"accuracy"`, `"precision_at_k"`) consistent across config validation (Task 2), constants (Task 1), and branch (Task 3). `per_target` key naming (`long15`, `long15__p@5`, `long15__lift@5`) consistent Task 3 ↔ Task 4.

---

## Execution Handoff

**Plan complete and saved to `external/docs/superpowers/plans/2026-07-12-precision-at-k-gate.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
