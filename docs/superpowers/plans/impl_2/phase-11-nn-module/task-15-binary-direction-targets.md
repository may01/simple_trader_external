# Task 15: Binary Direction Targets (single action vs. rest)

**Phase:** 11 — NN Module
**Depends on:** Task 02 (NNModelSpec/TargetSpec), Task 04 (NNDataset), Task 05 (NNModel)
**Produces:** new `kind="direction_binary"` target + `side` field — edits to `nn/nn_model_spec.py`, `nn/nn_dataset.py`, `nn/nn_model.py`, `configs/nn_spec.yaml`, and their unit tests

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This task follows the layer order: interface signatures first, RED integration test next, RED unit tests, then implementation — each verified inside Docker before the next layer.

---

## Goal

Add a `direction_binary` target kind: a **2-class softmax** head emitting `(prob_{side}, prob_other)` for ONE action (`long` or `short`) versus everything else, alongside the existing 3-class `direction` head. The positive class is the raw profit-label column for that side (`== 1`); `other` is `== 0`.

## Context

Today `kind="direction"` produces a 3-class one-hot `(prob_up, prob_neutral, prob_down)` by **coupling** the long and short profit labels (`up = long profitable & short not`, `down = short profitable`, else `neutral`) → softmax/cross-entropy, head width 3. `kind="label"` reads a single profit-label column as a binary **sigmoid** scalar (`nn_res_{name}_prob`, width 1). `kind="regression"` is a linear head.

This task adds a third classification family, `direction_binary`, that models one side **independently**: it reads a single profit-label column (`{tf}_plong_*` for `side="long"`, `{tf}_pshort_*` for `side="short"`) and emits a width-2 one-hot `(prob_{side}, prob_other)` trained with softmax/cross-entropy. It differs from `kind="label"` only in shape: a 2-value softmax where `prob_{side} + prob_other = 1`, matching the 3-class head's one-hot shape so downstream consumers (viewer, join, strategies) read it the same way they read direction probabilities.

Authoritative spec for this feature (updated alongside this task):
- `specs/supporting-systems/nn-module/nn-module.md` §7 (Targets and Labelling), family 2.
- `specs/supporting-systems/nn-module/datapoint-generator-class.md` §4, "Binary direction".
- `specs/supporting-systems/nn-module/nnmodel-class.md` §6 (TargetSpec output heads).

Everything routes through the **same code paths** as `kind="direction"` (softmax activation, cross-entropy loss, balanced class weights, argmax accuracy) — only the head width (2 not 3) and the label derivation (single column, raw) differ.

---

## Files

- Modify: `main/nn/nn_model_spec.py` — `TargetSpec.side` field; `__post_init__` validation; `out_columns()` `direction_binary` branch; docstrings.
- Modify: `main/nn/nn_dataset.py` — `_binary_onehot()` helper; `_target_block()` `direction_binary` branch; add `side` to `_dataset_hash` target spec dict.
- Modify: `main/nn/nn_model.py` — `_HEAD_WIDTH["direction_binary"] = 2`; include `direction_binary` in `_combined_loss`, `_apply_head_activation`, `_class_weights`, `_accuracy_counts`.
- Modify: `main/nn/training_loop.py` — `TrainingLoop._score_predictions`: score `direction_binary` heads as width-2 argmax accuracy (NOT the regression `else` branch). This is a SEPARATE holdout scorer from `NNModel._accuracy_counts`; missing it corrupts `holdout_score` and head-offset alignment for any spec mixing kinds. (See Layer 3b.)
- Modify: `main/configs/nn_spec.yaml` — example `long15` / `short15` targets.
- Test: `main/tests/unit/nn/test_nn_model_spec.py` — out_columns, validation, spec_hash.
- Test: `main/tests/unit/nn/test_nn_dataset.py` — `_binary_onehot`, `_target_block` (single + multi-horizon).
- Test: `main/tests/unit/nn/test_nn_model.py` — head width, output size, softmax activation, integration.
- Test: `main/tests/unit/nn/test_training_loop.py` — `_score_predictions` with a mixed direction + direction_binary spec (guards the offset/scoring fix).

---

## Docker Entry Points

All tests run inside the `nn-train` service (CPU is fine for these):

```bash
docker compose run --rm nn-train pytest tests/unit/nn/test_nn_model_spec.py -k direction_binary -v
docker compose run --rm nn-train pytest tests/unit/nn/test_nn_dataset.py   -k direction_binary -v
docker compose run --rm nn-train pytest tests/unit/nn/test_nn_model.py     -k direction_binary -v
docker compose run --rm nn-train python3 -c "from nn.nn_model_spec import NNModelSpec; s=NNModelSpec.from_yaml('configs/nn_spec.yaml'); print([(t.name,t.kind,t.side) for t in s.targets])"
```

Ground truth: the last command must list the `long15`/`short15` `direction_binary` targets after implementation.

---

## Interface (signatures only — implement bodies in the steps below)

`nn/nn_model_spec.py`:

```python
@dataclass
class TargetSpec:
    name: str
    kind: str                       # "direction"|"direction_binary"|"label"|"regression"
    horizons: list[int] = field(default_factory=lambda: [1])
    side: str | None = None         # direction_binary only: "long" | "short"
    label_tf: int | None = None
    label_m: float | None = None
    label_x: float | None = None
    strict: bool = False
    transform: str = "logret"

    def __post_init__(self) -> None: ...
    def out_columns(self) -> list[str]: ...
```

`nn/nn_dataset.py`:

```python
def _binary_onehot(col: np.ndarray) -> np.ndarray: ...   # (rows,) {0,1}/NaN -> (rows, 2)
def _target_block(df: pd.DataFrame, target: "TargetSpec") -> tuple[np.ndarray, dict]: ...
```

`nn/nn_model.py`:

```python
_HEAD_WIDTH = {"direction": 3, "direction_binary": 2, "label": 1, "regression": 1}
```

Consumes (already exist, do not change signatures):
- `_profit_long_col(spec, horizon) -> str`, `_profit_short_col(spec, horizon) -> str` (`nn/nn_dataset.py`)
- `NNModel.build()`, `NNModel.output_size`, `NNModel.model.head_meta` (list of `{"name","kind","horizon","width"}`), `NNModel.model.head_logits(x) -> list[Tensor]`, `NNModel._apply_head_activation(logits, meta)`, `NNModel._compute_output_size(spec)`, `NNModel._n_features`
- `_make_y(spec, n, rng)` test helper in `test_nn_model.py`

Produces (later layers / consumers rely on these exact strings):
- Output columns: `nn_res_{name}_prob_{side}`, `nn_res_{name}_prob_other` (single horizon); `nn_res_{name}_h{hk}_prob_{side}` / `_prob_other` (multi-horizon).
- Manifest entry keys for this kind: `side`, `encoding={<side>:0, "other":1}`, `source={"column":..., "strict":...}` (or `per_horizon`).

---

## Integration test (RED first, in Docker) — spec → model head → softmax

This wires the spec layer (`TargetSpec`) to the model layer (`NNModel` head + activation) and asserts the cross-layer contract: a `direction_binary` target yields one width-2 softmax head whose per-row probabilities sum to 1. Write it RED before any implementation.

- [ ] **Step I1: Add the binary-spec helper + integration test (RED)**

Add to `main/tests/unit/nn/test_nn_model.py` (near the other `_*_spec` helpers):

```python
def _binary_spec(**overrides) -> NNModelSpec:
    """Single-head direction_binary (long) spec: head width 2 (softmax)."""
    kwargs = dict(
        name="tiny_binary",
        timeframes=[15],
        indicators=["rsi", "atr_ma"],
        history_points=1,
        layers=[LayerSpec(kind="dense", units=8)],
        targets=[
            TargetSpec(
                name="long15", kind="direction_binary", side="long",
                label_tf=15, label_m=1.0, label_x=0.3,
            )
        ],
        epochs=2,
        validation_split=0.2,
        val_strategy="time_holdout",
        device="cpu",
        seed=0,
    )
    kwargs.update(overrides)
    return NNModelSpec(**kwargs)


def test_direction_binary_spec_to_softmax_head():
    """Integration: a direction_binary TargetSpec -> one width-2 softmax head."""
    spec = _binary_spec()
    model = NNModel(spec)
    model.build()

    assert model.output_size == 2
    assert [m["width"] for m in model.model.head_meta] == [2]
    assert model.model.head_meta[0]["kind"] == "direction_binary"

    x = torch.zeros(3, spec.history_points, model._n_features)
    logits = model.model.head_logits(x)[0]
    probs = NNModel._apply_head_activation(logits, model.model.head_meta[0])
    assert probs.shape == (3, 2)
    assert torch.allclose(probs.sum(dim=1), torch.ones(3), atol=1e-5)
```

(If `torch` is not already imported at the top of the test module, add `import torch`.)

- [ ] **Step I2: Run it — expect RED**

Run: `docker compose run --rm nn-train pytest tests/unit/nn/test_nn_model.py::test_direction_binary_spec_to_softmax_head -v`
Expected: FAIL — `_HEAD_WIDTH` has no `"direction_binary"` key (KeyError) / `output_size` wrong. This proves the wiring is not yet implemented.

---

## Layer 1 — `TargetSpec` (spec layer)

- [ ] **Step 1.1: Unit tests for the new field, columns, validation, hash (RED)**

Add to `main/tests/unit/nn/test_nn_model_spec.py` (imports `TargetSpec`, `NNModelSpec`, `LayerSpec`, `pytest` already present):

```python
class TestDirectionBinaryTarget:
    def test_out_columns_long_single_horizon(self):
        t = TargetSpec(
            name="long15", kind="direction_binary", side="long",
            horizons=[1], label_tf=15, label_m=1.0, label_x=0.3,
        )
        assert t.out_columns() == [
            "nn_res_long15_prob_long",
            "nn_res_long15_prob_other",
        ]

    def test_out_columns_short_multi_horizon(self):
        t = TargetSpec(
            name="s", kind="direction_binary", side="short",
            horizons=[1, 2], label_tf=15, label_m=1.0, label_x=0.3,
        )
        assert t.out_columns() == [
            "nn_res_s_h1_prob_short", "nn_res_s_h1_prob_other",
            "nn_res_s_h2_prob_short", "nn_res_s_h2_prob_other",
        ]

    def test_missing_side_raises(self):
        with pytest.raises(ValueError, match="side"):
            TargetSpec(
                name="x", kind="direction_binary", side=None,
                label_tf=15, label_m=1.0, label_x=0.3,
            )

    def test_bad_side_raises(self):
        with pytest.raises(ValueError, match="side"):
            TargetSpec(
                name="x", kind="direction_binary", side="up",
                label_tf=15, label_m=1.0, label_x=0.3,
            )

    def test_side_changes_spec_hash(self):
        common = dict(
            name="m", timeframes=[15], indicators=["15_close"],
            layers=[LayerSpec(kind="dense", units=8)],
        )
        long_spec = NNModelSpec(
            targets=[TargetSpec(name="a", kind="direction_binary", side="long",
                                label_tf=15, label_m=1.0, label_x=0.3)],
            **common,
        )
        short_spec = NNModelSpec(
            targets=[TargetSpec(name="a", kind="direction_binary", side="short",
                                label_tf=15, label_m=1.0, label_x=0.3)],
            **common,
        )
        assert long_spec.spec_hash != short_spec.spec_hash
```

- [ ] **Step 1.2: Run — expect RED**

Run: `docker compose run --rm nn-train pytest tests/unit/nn/test_nn_model_spec.py::TestDirectionBinaryTarget -v`
Expected: FAIL — `TargetSpec.__init__() got an unexpected keyword argument 'side'`.

- [ ] **Step 1.3: Add the `side` field + validation + docstring**

In `main/nn/nn_model_spec.py`, in the `TargetSpec` dataclass, update the kind docstring line and add the `side` field right after `horizons`:

```python
    name: str
    kind: str                                   # "direction"|"direction_binary"|"label"|"regression"
    horizons: list[int] = field(default_factory=lambda: [1])

    # direction_binary only:
    side: str | None = None                     # "long" | "short"

    # direction / direction_binary / label
    label_tf: int | None = None
    label_m: float | None = None
    label_x: float | None = None
    strict: bool = False

    # regression
    transform: str = "logret"

    def __post_init__(self) -> None:
        if self.kind == "direction_binary" and self.side not in ("long", "short"):
            raise ValueError(
                f"direction_binary target {self.name!r} needs "
                f"side='long'|'short', got {self.side!r}"
            )
```

- [ ] **Step 1.4: Add the `direction_binary` branch to `out_columns()`**

In `TargetSpec.out_columns()`, inside the `for hk in self.horizons:` loop, add the branch between the `direction` and `label` branches:

```python
            if self.kind == "direction":
                cols += [
                    f"{base}_prob_up",
                    f"{base}_prob_neutral",
                    f"{base}_prob_down",
                ]
            elif self.kind == "direction_binary":
                cols += [
                    f"{base}_prob_{self.side}",
                    f"{base}_prob_other",
                ]
            elif self.kind == "label":
                cols.append(f"{base}_prob")
```

- [ ] **Step 1.5: Run — expect GREEN**

Run: `docker compose run --rm nn-train pytest tests/unit/nn/test_nn_model_spec.py::TestDirectionBinaryTarget -v`
Expected: PASS (5 tests).

- [ ] **Step 1.6: Commit**

```bash
git add main/nn/nn_model_spec.py main/tests/unit/nn/test_nn_model_spec.py
git commit -m "feat(nn): TargetSpec.side + direction_binary out_columns"
```

---

## Layer 2 — `NNDataset` (label materialisation)

- [ ] **Step 2.1: Unit tests for `_binary_onehot` and `_target_block` (RED)**

Add to `main/tests/unit/nn/test_nn_dataset.py` (imports `numpy as np`, `pandas as pd`, `TargetSpec` already present):

```python
def test_binary_onehot_positive_other_nan():
    from nn.nn_dataset import _binary_onehot
    col = np.array([1.0, 0.0, np.nan, 1.0])
    out = _binary_onehot(col)
    assert out.shape == (4, 2)
    np.testing.assert_array_equal(out[0], [1.0, 0.0])   # positive
    np.testing.assert_array_equal(out[1], [0.0, 1.0])   # other
    assert np.isnan(out[2]).all()                        # NaN row dropped at build
    np.testing.assert_array_equal(out[3], [1.0, 0.0])


def test_target_block_direction_binary_long():
    from nn.nn_dataset import _target_block, _profit_long_col
    t = TargetSpec(
        name="long15", kind="direction_binary", side="long",
        horizons=[1], label_tf=15, label_m=1.0, label_x=0.3,
    )
    col = _profit_long_col(t, 1)
    df = pd.DataFrame({col: [1.0, 0.0, 1.0, np.nan]})
    block, entry = _target_block(df, t)
    assert block.shape == (4, 2)
    assert entry["out_columns"] == [
        "nn_res_long15_prob_long", "nn_res_long15_prob_other",
    ]
    assert entry["side"] == "long"
    assert entry["encoding"] == {"long": 0, "other": 1}
    assert entry["source"] == {"column": col, "strict": False}
    np.testing.assert_array_equal(block[0], [1.0, 0.0])
    np.testing.assert_array_equal(block[1], [0.0, 1.0])


def test_target_block_direction_binary_short_reads_short_col():
    from nn.nn_dataset import _target_block, _profit_short_col
    t = TargetSpec(
        name="short15", kind="direction_binary", side="short",
        horizons=[1], label_tf=15, label_m=1.0, label_x=0.3,
    )
    col = _profit_short_col(t, 1)
    df = pd.DataFrame({col: [1.0, 0.0]})
    block, entry = _target_block(df, t)
    assert entry["out_columns"] == [
        "nn_res_short15_prob_short", "nn_res_short15_prob_other",
    ]
    np.testing.assert_array_equal(block[0], [1.0, 0.0])
    np.testing.assert_array_equal(block[1], [0.0, 1.0])


def test_target_block_direction_binary_missing_column_raises():
    from nn.nn_dataset import _target_block
    t = TargetSpec(
        name="long15", kind="direction_binary", side="long",
        horizons=[1], label_tf=15, label_m=1.0, label_x=0.3,
    )
    with pytest.raises(ValueError, match="missing profit-label column"):
        _target_block(pd.DataFrame({"other": [1.0]}), t)
```

- [ ] **Step 2.2: Run — expect RED**

Run: `docker compose run --rm nn-train pytest tests/unit/nn/test_nn_dataset.py -k direction_binary -v`
Expected: FAIL — `cannot import name '_binary_onehot'` / `_target_block` raises `unknown target kind 'direction_binary'`.

- [ ] **Step 2.3: Add the `_binary_onehot` helper**

In `main/nn/nn_dataset.py`, add next to `_onehot3`:

```python
def _binary_onehot(col: np.ndarray) -> np.ndarray:
    """(rows,) profit label {0,1}/NaN -> (rows, 2) one-hot [positive, other].

    positive (col == 1) -> [1, 0]; other (col == 0) -> [0, 1]; NaN row -> all NaN.
    """
    out = np.full((col.shape[0], 2), np.nan, dtype=np.float64)
    valid = ~np.isnan(col)
    out[valid] = 0.0
    pos = np.flatnonzero(valid & (col == 1.0))
    oth = np.flatnonzero(valid & (col == 0.0))
    out[pos, 0] = 1.0
    out[oth, 1] = 1.0
    return out
```

- [ ] **Step 2.4: Add the `direction_binary` branch to `_target_block`**

In `_target_block`, add the branch after the `direction` branch and before the `label` branch:

```python
    elif target.kind == "direction_binary":
        if target.side not in ("long", "short"):
            raise ValueError(
                f"direction_binary target {target.name!r} needs "
                f"side='long'|'short', got {target.side!r}"
            )
        srcs = []
        for h in target.horizons:
            col_name = (
                _profit_long_col(target, h)
                if target.side == "long"
                else _profit_short_col(target, h)
            )
            srcs.append(col_name)
            if col_name not in df.columns:
                raise ValueError(f"missing profit-label column {col_name!r}")
            c = df[col_name].to_numpy(dtype=np.float64)
            cols.append(_binary_onehot(c))
        entry["side"] = target.side
        entry["encoding"] = {target.side: 0, "other": 1}
        entry["source"] = (
            {"column": srcs[0], "strict": target.strict}
            if len(srcs) == 1
            else {"per_horizon": srcs, "strict": target.strict}
        )
```

- [ ] **Step 2.5: Add `side` to the dataset hash**

In `_dataset_hash`, inside the `target_specs` list comprehension dict, add `side` (so `long` vs `short` datasets hash differently and cache separately):

```python
            {
                "name": t.name,
                "kind": t.kind,
                "side": t.side,
                "horizons": list(t.horizons),
                "label_tf": t.label_tf,
                "label_m": t.label_m,
                "label_x": t.label_x,
                "strict": t.strict,
                "transform": t.transform,
            }
```

- [ ] **Step 2.6: Run — expect GREEN**

Run: `docker compose run --rm nn-train pytest tests/unit/nn/test_nn_dataset.py -k direction_binary -v`
Expected: PASS (4 tests).

- [ ] **Step 2.7: Commit**

```bash
git add main/nn/nn_dataset.py main/tests/unit/nn/test_nn_dataset.py
git commit -m "feat(nn): direction_binary label materialisation in NNDataset"
```

---

## Layer 3 — `NNModel` (head width, loss, activation, metrics)

- [ ] **Step 3.1: Unit tests for head width / output size / activation (RED)**

Add to `main/tests/unit/nn/test_nn_model.py`:

```python
def test_head_width_direction_binary():
    from nn.nn_model import _HEAD_WIDTH
    assert _HEAD_WIDTH["direction_binary"] == 2


def test_compute_output_size_direction_binary():
    spec = _binary_spec()
    assert NNModel._compute_output_size(spec) == 2


def test_apply_activation_direction_binary_is_softmax():
    logits = torch.tensor([[2.0, 0.0], [0.0, 0.0]])
    out = NNModel._apply_head_activation(logits, {"kind": "direction_binary"})
    assert torch.allclose(out.sum(dim=1), torch.ones(2), atol=1e-6)
    assert out[0, 0] > out[0, 1]
```

Also extend the existing `_make_y` test helper so model-training tests can build a `direction_binary` head — add this branch inside its per-target loop (after the `direction` branch):

```python
            elif t.kind == "direction_binary":
                codes = rng.randint(0, 2, size=n)
                oh = np.zeros((n, 2), dtype=np.float32)
                oh[np.arange(n), codes] = 1.0
                cols.append(oh)
```

- [ ] **Step 3.2: Run — expect RED**

Run: `docker compose run --rm nn-train pytest tests/unit/nn/test_nn_model.py -k direction_binary -v`
Expected: FAIL — `KeyError: 'direction_binary'` from `_HEAD_WIDTH`; activation returns sigmoid (sum != 1).

- [ ] **Step 3.3: Register head width**

In `main/nn/nn_model.py`:

```python
_HEAD_WIDTH = {"direction": 3, "direction_binary": 2, "label": 1, "regression": 1}
```

- [ ] **Step 3.4: Route `direction_binary` through the softmax/cross-entropy paths**

In `_combined_loss`, change the direction test to include the new kind:

```python
            if meta["kind"] in ("direction", "direction_binary"):
                tgt = target_y.argmax(dim=1)
                loss = nn.functional.cross_entropy(logits, tgt, weight=cw)
```

In `_apply_head_activation`:

```python
        if meta["kind"] in ("direction", "direction_binary"):
            return torch.softmax(logits, dim=1)
```

In `_class_weights` (balanced weights generalise to any width via `counts.sum()/(width*counts)`):

```python
            if meta["kind"] in ("direction", "direction_binary"):
                counts = block.sum(dim=0)  # one-hot -> per-class counts
                counts = torch.clamp(counts, min=1.0)
                w = counts.sum() / (width * counts)
```

In `_accuracy_counts`:

```python
            if meta["kind"] in ("direction", "direction_binary"):
                pred = logits.argmax(dim=1)
                tgt = target_y.argmax(dim=1)
                correct += float((pred == tgt).float().sum().item())
                count += float(target_y.shape[0])
```

- [ ] **Step 3.5: Run unit + integration — expect GREEN**

Run: `docker compose run --rm nn-train pytest tests/unit/nn/test_nn_model.py -k direction_binary -v`
Expected: PASS — includes `test_direction_binary_spec_to_softmax_head` (the integration test from Step I1) now green.

- [ ] **Step 3.6: Commit**

```bash
git add main/nn/nn_model.py main/tests/unit/nn/test_nn_model.py
git commit -m "feat(nn): direction_binary 2-class softmax head + metrics"
```

---

## Layer 3b — holdout scorer (`training_loop.py`)

`NNModel._accuracy_counts` (Layer 3) is the per-batch training metric. The agentic search loop ALSO has a second, independent scorer — `TrainingLoop._score_predictions` in `nn/training_loop.py` — whose result becomes `holdout_score` and drives trial ranking / model promotion. It switches on `kind` with **hard-coded widths** and an `else → regression` fallthrough, so `direction_binary` (width 2) silently lands in the regression branch: it mis-scores the head AND advances `offset` by 1 instead of 2, misaligning every later head. Any spec mixing `direction_binary` with another head (the default `nn_spec.yaml` does, after Layer 4) gets a corrupt holdout score. Update this site too.

- [ ] **Step 3b.1: Holdout-scorer test (RED)**

Add to `main/tests/unit/nn/test_training_loop.py` (module already imports `numpy as np`, `LayerSpec`, `NNModelSpec`, `TargetSpec`, `TrainingLoop`; note the file's top-level `optuna = pytest.importorskip("optuna")` — the test runs only where optuna is installed, which the `nn-train` image is):

```python
class TestScorePredictionsDirectionBinary:
    def test_mixed_direction_and_binary_offset_and_accuracy(self):
        spec = NNModelSpec(
            name="m",
            timeframes=[15],
            indicators=["15_close"],
            layers=[LayerSpec(kind="dense", units=8)],
            targets=[
                TargetSpec(name="dir15", kind="direction",
                           label_tf=15, label_m=1.0, label_x=0.3),
                TargetSpec(name="long15", kind="direction_binary", side="long",
                           label_tf=15, label_m=1.0, label_x=0.3),
            ],
        )
        # columns: [dir up, neutral, down | long prob_long, prob_other]
        y = np.array([
            [1, 0, 0, 1, 0],
            [0, 0, 1, 0, 1],
        ], dtype=float)
        preds = np.array([
            [0.7, 0.2, 0.1, 0.9, 0.1],
            [0.1, 0.2, 0.7, 0.2, 0.8],
        ], dtype=float)
        overall, per_target = TrainingLoop._score_predictions(spec, preds, y)
        assert per_target["dir15"] == 1.0
        assert per_target["long15"] == 1.0   # ~0.976 (MSE on 1 col) before the fix
        assert overall == 1.0
```

- [ ] **Step 3b.2: Run — expect RED**

Run: `docker compose run --rm nn-train pytest tests/unit/nn/test_training_loop.py -k direction_binary -v`
Expected: FAIL — `per_target["long15"]` ≈ 0.976, not 1.0 (the head is MSE-scored on one column in the regression branch). If the test is reported **skipped**, optuna is absent in the image — resolve that before relying on this guard.

- [ ] **Step 3b.3: Add the `direction_binary` branch to `_score_predictions`**

In `main/nn/training_loop.py`, change the first branch of the per-target loop:

```python
                if target.kind in ("direction", "direction_binary"):
                    width = 3 if target.kind == "direction" else 2
                    p = preds[:, offset : offset + width]
                    t = y[:, offset : offset + width]
                    acc = float((p.argmax(axis=1) == t.argmax(axis=1)).mean())
                    per_target[target.name] = acc
                    head_scores.append(acc)
```

Leave the `label` and `else`/regression branches unchanged.

- [ ] **Step 3b.4: Run — expect GREEN**

Run: `docker compose run --rm nn-train pytest tests/unit/nn/test_training_loop.py -k direction_binary -v`
Expected: PASS.

- [ ] **Step 3b.5: Commit**

```bash
git add nn/training_loop.py tests/unit/nn/test_training_loop.py
git commit -m "fix(nn): score direction_binary heads as argmax accuracy in holdout scorer"
```

---

## Layer 4 — config example + full-suite regression

- [ ] **Step 4.1: Add example targets to `configs/nn_spec.yaml`**

In `main/configs/nn_spec.yaml`, under `targets:` (after the existing `dir15` entry), add:

```yaml
  - name: long15
    kind: direction_binary
    side: long
    horizons: [1]
    label_tf: 15
    label_m: 1.0
    label_x: 0.3
    strict: false
  - name: short15
    kind: direction_binary
    side: short
    horizons: [1]
    label_tf: 15
    label_m: 1.0
    label_x: 0.3
    strict: false
```

These reuse the same `(label_tf=15, m=1.0, x=0.3)` profit-label columns the existing `dir15` target reads, so no new label config is required.

- [ ] **Step 4.2: Verify `from_yaml` round-trips the new targets**

Run:
```bash
docker compose run --rm nn-train python3 -c "from nn.nn_model_spec import NNModelSpec; s=NNModelSpec.from_yaml('configs/nn_spec.yaml'); print([(t.name,t.kind,t.side) for t in s.targets])"
```
Expected output includes: `('long15', 'direction_binary', 'long')` and `('short15', 'direction_binary', 'short')`.

- [ ] **Step 4.3: Run the full NN unit suite — expect GREEN (no regressions)**

Run:
```bash
docker compose run --rm nn-train pytest tests/unit/nn/ -v
```
Expected: all pass. (`test_from_yaml_default_path_loads_configs` asserts only `len(targets) >= 1`, so the added targets do not break it.)

- [ ] **Step 4.4: Commit**

```bash
git add main/configs/nn_spec.yaml
git commit -m "feat(nn): example direction_binary long15/short15 targets in nn_spec.yaml"
```

---

## Key Constraints

- **Reuse, don't fork.** `direction_binary` must run through the *same* softmax/cross-entropy/argmax/balanced-weight code as `direction` — the only differences are head width (2) and label derivation (single raw profit column). Do not duplicate the loss/activation logic.
- **Update EVERY `kind`-dispatch site — there are two scorers.** Grep the NN module for `kind == "direction"` / `"direction"` before finishing. The sites that must include `direction_binary`: `nn_model.py` (`_HEAD_WIDTH`, `_combined_loss`, `_apply_head_activation`, `_class_weights`, `_accuracy_counts`) AND `training_loop.py` (`_score_predictions`, the holdout/promotion scorer — Layer 3b). `_accuracy_counts` (train metric) and `_score_predictions` (holdout score) are SEPARATE functions; updating only the first leaves a width-2 head mis-scored and offset-misaligned in promotion. `nn_dataset.py:_target_block` and `nn_model_spec.py:out_columns` keep `direction` and `direction_binary` as distinct adjacent branches (different widths), which is correct — not a fork.
- **Known out-of-scope follow-ups (NOT part of this task; file as separate tasks):** (1) `frontend/data_viewer.py:_NN_RES_COLORS` only maps `prob_up/neutral/down`; `prob_long/short/other` lines fall back to the default colour (graceful, no crash) — add colours for a consistent viewer. (2) `nn/nn_strategist.py` does not emit `side`, so the agentic strategist cannot propose `direction_binary` (config-only) — extend the proposal schema if strategist-reachability is wanted.
- **Positive class = raw profit label.** `prob_{side}` is `column == 1` for the side's own profit column; it does **not** consult the opposite side (that is what `kind="direction"` does). `other = column == 0`. NaN rows stay NaN and are dropped at build, exactly like `direction`/`label`.
- **Column names are part of the public contract.** `nn_res_{name}_prob_{side}` / `nn_res_{name}_prob_other` (and `_h{hk}` for multi-horizon) are read by the viewer, join, and strategies — match them exactly. `block.shape[1]` must equal `len(out_columns)` (the existing assert at the end of `_target_block` enforces this).
- **`side` enters identity.** It is a dataclass field, so `spec_hash` (via `asdict`) and `_dataset_hash` both include it — a `long` model and a `short` model are distinct artefacts. The Step 1.5 and Step 2.5 changes guarantee this; the `test_side_changes_spec_hash` test guards it.
- **Validation fails fast.** A `direction_binary` target without a valid `side` raises in `TargetSpec.__post_init__` (construction time) and again defensively in `_target_block`.
- Global: timeframe-agnostic outputs (no `{tf}_` prefix); CPU is sufficient for all tests in this task.

---

## Verification

```bash
docker compose run --rm nn-train pytest tests/unit/nn/test_nn_model_spec.py tests/unit/nn/test_nn_dataset.py tests/unit/nn/test_nn_model.py -v
docker compose run --rm nn-train python3 -c "from nn.nn_model_spec import NNModelSpec; s=NNModelSpec.from_yaml('configs/nn_spec.yaml'); print([(t.name,t.kind,t.side) for t in s.targets])"
```
All green; the second prints the two `direction_binary` targets.

## Commit

Commits are made per layer (Steps 1.6, 2.7, 3.6, 4.4). Final state: `kind="direction_binary"` is a first-class target producing a 2-value softmax `(prob_{side}, prob_other)` head, wired spec → dataset → model → inference, with example targets in `nn_spec.yaml`.
