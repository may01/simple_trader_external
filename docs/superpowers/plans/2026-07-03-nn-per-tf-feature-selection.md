# NN per-TF feature selection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make NN feature selection per-TF-aware (ragged) so TF-restricted `nn_features` (cross-TF align ladder, cyclical `sin_tod`/`cos_tod` omitting 1440) train without the `feature columns missing` crash, with the network's input width derived from the resolved selection.

**Architecture:** Two-file change inside the Layer-2 NN module. `NNDataset.build` emits `{tf}_{ind}` only where the column exists in `df` (with typo + empty-TF guards, logged drops). `NNModel` computes feature width from the resolved `feature_cols` (dataset at train, bundled manifest at load), falling back to the spec's uniform product only when no selection is resolved yet. Everything downstream (`_materialise`, per-column normalization, manifest, checkpoint bundle, inference `build_matrix`) is already keyed per-TF and needs no change.

**Tech Stack:** Python 3, PyTorch, pandas/numpy, pytest 9.0.3; Docker Compose (`simple_trader_nn` image, `nn-train` service).

## Global Constraints

- No spec schema change; no strategist/LLM change; no revived `nn:` config block; no `_z` columns.
- Feature-column order MUST preserve `spec.indicators` order → deterministic dataset hash (`_dataset_hash` already folds `feature_cols_by_tf`).
- Width source of truth = resolved `feature_cols`; spec arithmetic `len(indicators)×len(timeframes)` is the **fallback only** (when `feature_cols` is None). This keeps `test_input_size_from_spec` green.
- All RED/GREEN test runs execute in Docker: `docker compose run --rm nn-train python3 -m pytest <path> -v` (service `nn-train`, image `simple_trader_nn`, mounts `.:/code`, WORKDIR `/code`; if the entrypoint interferes add `--entrypoint python3` and drop the leading `python3`).
- Branch off `experimental_imp_2` before Task 1; one branch for the whole feature. Commit per task. Push/PR only on explicit user confirmation (do not auto-push).

---

## Docker Entry Points

Ground-truth commands the implementation must satisfy:

```bash
# Run the NN unit suite (used for every RED/GREEN step below)
docker compose run --rm nn-train python3 -m pytest tests/unit/nn -v

# Run one test file / one test
docker compose run --rm nn-train python3 -m pytest tests/unit/nn/test_nn_dataset.py -v
docker compose run --rm nn-train python3 -m pytest tests/unit/nn/test_ragged_feature_selection.py -v

# (config follow-on, optional Task 5) full NN training smoke — needs df_with_indicators.pkl in the data volume
docker compose run --rm nn-train python3 trainer.py nn_train
```

Verified: [ ] `docker compose run --rm nn-train python3 -m pytest tests/unit/nn -q` collects & runs.

---

## Layer boundary: NNDataset → NNModel

### Interface (resolved shapes; no new signatures)

```python
# Produced by NNDataset.build → stored in dataset.manifest and each checkpoint bundle:
#   feature_cols_by_tf: dict[str, list[str]]   # RAGGED: per-TF lists may differ in length
#                                              # order within each list == spec.indicators order

# Consumed by NNModel (width derives from the resolved dict, spec product is fallback):
#   NNModel.feature_cols: dict[str, list[str]] | None
#   NNModel._n_features -> int    # sum(len(c) for c in feature_cols.values()) if feature_cols
#                                 #   else len(spec.indicators) * len(spec.timeframes)
#   NNModel.input_size  -> int    # _n_features * spec.history_points
```

### Boundary integration test — write FIRST, RED in Docker (Task 4 turns it GREEN)

New file `tests/unit/nn/test_ragged_feature_selection.py`. `make_wide_df` has `15_rsi_14` but no `60_rsi_14`, so `timeframes=[15,60], indicators=["logret","rsi_14"]` is a natural ragged case (crashes today at the missing-column check).

```python
import numpy as np
from indicators import DataAttributes
from nn.nn_dataset import NNDataset
from nn.nn_model import NNModel
from nn.nn_model_spec import LayerSpec
from tests.unit.nn.test_nn_dataset import make_wide_df, small_spec


def test_ragged_dataset_sizes_model_and_trains(tmp_path):
    # rsi_14 exists at 15 but NOT at 60 → ragged:
    #   tf15 → [15_logret, 15_rsi_14], tf60 → [60_logret]  (3 features total)
    df = make_wide_df(rows=120)
    spec = small_spec(
        timeframes=[15, 60],
        indicators=["logret", "rsi_14"],
        layers=[LayerSpec(kind="dense", units=8)],
        epochs=1,
        device="cpu",
    )
    ds = NNDataset.build(df, DataAttributes(), spec, dataset_dir=str(tmp_path))
    assert ds.manifest["feature_cols"]["15"] == ["15_logret", "15_rsi_14"]
    assert ds.manifest["feature_cols"]["60"] == ["60_logret"]

    model = NNModel(spec)
    model.train(ds)
    assert model._n_features == 3                       # 2 + 1, NOT 2*2
    assert model.input_size == 3 * spec.history_points

    x = np.random.randn(model.input_size).astype("float32")
    out = model.run(x)
    assert out.shape[0] == model.output_size
```

Run RED now (documents the starting failure):

```bash
docker compose run --rm nn-train python3 -m pytest tests/unit/nn/test_ragged_feature_selection.py -v
# Expected: FAIL — ValueError "feature columns missing from source frame: ['60_rsi_14']"
```

---

## Task 1: Ragged feature selection in `NNDataset.build`

**Files:**
- Modify: `nn/nn_dataset.py` (imports: add module logger; `NNDataset.build` ~433-450)
- Test: `tests/unit/nn/test_nn_dataset.py`

**Interfaces:**
- Consumes: `spec.indicators: list[str]`, `spec.timeframes: list[int]`, `df.columns`
- Produces: `feature_cols_by_tf: dict[str, list[str]]` (ragged, order = `spec.indicators`); raises `ValueError` on (a) an indicator absent at every TF, (b) a TF with zero features.

- [ ] **Step 1: Write failing unit tests**

Add to `tests/unit/nn/test_nn_dataset.py` (inside the existing dataset test class, or module-level — match the file's style):

```python
def test_ragged_selection_drops_nonapplicable_tf(self, tmp_path):
    # 60_rsi_14 does not exist in make_wide_df → dropped at tf=60 only.
    df = make_wide_df(rows=90)
    spec = small_spec(timeframes=[15, 60], indicators=["logret", "rsi_14"])
    ds = NNDataset.build(df, DataAttributes(), spec, dataset_dir=str(tmp_path))
    assert ds.manifest["feature_cols"]["15"] == ["15_logret", "15_rsi_14"]
    assert ds.manifest["feature_cols"]["60"] == ["60_logret"]

def test_indicator_absent_at_all_tfs_raises(self, tmp_path):
    df = make_wide_df(rows=90)
    spec = small_spec(timeframes=[15, 60], indicators=["logret", "does_not_exist"])
    with pytest.raises(ValueError, match="does_not_exist"):
        NNDataset.build(df, DataAttributes(), spec, dataset_dir=str(tmp_path))

def test_timeframe_with_zero_features_raises(self, tmp_path):
    # rsi_14 resolves at 15 (typo guard passes) but tf=60 has no features.
    df = make_wide_df(rows=90)
    spec = small_spec(timeframes=[15, 60], indicators=["rsi_14"])
    with pytest.raises(ValueError, match="zero features"):
        NNDataset.build(df, DataAttributes(), spec, dataset_dir=str(tmp_path))
```

Note: existing `test_missing_feature_col_raises` (single-TF, wholly-missing indicator) stays green — the typo guard message contains the name.

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose run --rm nn-train python3 -m pytest \
  tests/unit/nn/test_nn_dataset.py -k "ragged_selection or absent_at_all or zero_features" -v
# Expected: FAIL — current build raises "feature columns missing" for the ragged case
```

- [ ] **Step 3: Add a module logger to `nn/nn_dataset.py`**

Near the top imports (after `import os`):

```python
import logging

logger = logging.getLogger(__name__)
```

- [ ] **Step 4: Replace the uniform product + hard error in `NNDataset.build`**

Replace the block (currently ~433-450):

```python
        # Feature columns per TF (bare indicator names → {tf}_{indicator}).
        feature_cols_by_tf: dict[str, list[str]] = {}
        for tf in spec.timeframes:
            feature_cols_by_tf[str(tf)] = [
                f"{tf}_{ind}" for ind in spec.indicators
            ]

        # Validate every feature column exists.
        missing = [
            c
            for cols in feature_cols_by_tf.values()
            for c in cols
            if c not in df.columns
        ]
        if missing:
            raise ValueError(
                f"feature columns missing from source frame: {missing}"
            )
```

with:

```python
        # Feature columns per TF (bare indicator names → {tf}_{indicator}).
        # Ragged / applies_to-aware: emit {tf}_{ind} only where the column
        # exists, so TF-restricted features (align ladder, cyclical-omit-1440)
        # select cleanly instead of crashing. Order preserves spec.indicators
        # for a deterministic dataset hash.
        feature_cols_by_tf: dict[str, list[str]] = {}
        dropped: list[tuple[int, str]] = []
        for tf in spec.timeframes:
            cols: list[str] = []
            for ind in spec.indicators:
                col = f"{tf}_{ind}"
                if col in df.columns:
                    cols.append(col)
                else:
                    dropped.append((tf, ind))
            feature_cols_by_tf[str(tf)] = cols

        # Typo guard: an indicator absent at EVERY timeframe is a spec error,
        # distinct from a legitimate per-TF restriction.
        unresolved = [
            ind
            for ind in spec.indicators
            if not any(f"{tf}_{ind}" in df.columns for tf in spec.timeframes)
        ]
        if unresolved:
            raise ValueError(
                f"indicators not found at any timeframe: {unresolved}"
            )

        # A timeframe that resolves to zero features is a spec error.
        empty_tfs = [tf for tf, cols in feature_cols_by_tf.items() if not cols]
        if empty_tfs:
            raise ValueError(f"timeframes with zero features: {empty_tfs}")

        # Visibility: intentional per-TF drops are logged, never silent.
        if dropped:
            logger.info(
                "NN feature selection dropped %d per-TF pair(s) via applies_to: %s",
                len(dropped),
                dropped,
            )
```

- [ ] **Step 5: Run tests to verify GREEN (and no regressions in the file)**

```bash
docker compose run --rm nn-train python3 -m pytest tests/unit/nn/test_nn_dataset.py -v
# Expected: PASS — new ragged tests + existing dataset tests (incl. test_missing_feature_col_raises)
```

- [ ] **Step 6: Commit**

```bash
git add nn/nn_dataset.py tests/unit/nn/test_nn_dataset.py
git commit -m "feat(nn): ragged per-TF feature selection in NNDataset.build"
```

---

## Task 2: Feature width from resolved `feature_cols` in `NNModel`

**Files:**
- Modify: `nn/nn_model.py` (`__init__` ~286-296; `_n_features` ~305-308; add `input_size` property; `train` ~344-360)
- Test: `tests/unit/nn/test_nn_model.py`

**Interfaces:**
- Consumes: `NNModel.feature_cols: dict[str, list[str]] | None`, `spec.history_points`
- Produces: `_n_features` and `input_size` as properties (resolved sum with spec-product fallback); `train(dataset)` sets `feature_cols` before `build()`.

- [ ] **Step 1: Write failing unit tests**

Add to `tests/unit/nn/test_nn_model.py`:

```python
def test_n_features_uses_resolved_feature_cols():
    m = NNModel(_direction_spec(timeframes=[15, 60], indicators=["a", "b"], history_points=4))
    # Simulate a ragged resolved selection: 2 cols @15, 1 col @60 → 3 (NOT 2*2)
    m.feature_cols = {"15": ["15_a", "15_b"], "60": ["60_a"]}
    assert m._n_features == 3
    assert m.input_size == 3 * 4

def test_n_features_falls_back_to_spec_product_when_unresolved():
    m = NNModel(_direction_spec(timeframes=[15, 60], indicators=["a", "b", "c"], history_points=4))
    assert m.feature_cols is None
    assert m._n_features == 3 * 2          # spec product fallback
    assert m.input_size == 3 * 2 * 4       # keeps test_input_size_from_spec semantics
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose run --rm nn-train python3 -m pytest \
  tests/unit/nn/test_nn_model.py -k "resolved_feature_cols or falls_back_to_spec" -v
# Expected: FAIL — _n_features currently ignores feature_cols; input_size is a plain attr
```

- [ ] **Step 3: Make `_n_features` / `input_size` resolved-aware**

In `NNModel.__init__`, DELETE the stored `input_size` assignment (currently ~286-288):

```python
        self.input_size = (
            len(spec.indicators) * len(spec.timeframes) * spec.history_points
        )
```

Replace the existing `_n_features` property (currently ~305-308) and add an `input_size` property immediately after it:

```python
    @property
    def _n_features(self) -> int:
        """Per-timestep feature width.

        Uses the RESOLVED feature_cols (from the dataset at train time or the
        bundled manifest at load time) when available; before either is known,
        falls back to the spec's uniform indicators×timeframes product.
        """
        if self.feature_cols:
            return sum(len(cols) for cols in self.feature_cols.values())
        return len(self.spec.indicators) * len(self.spec.timeframes)

    @property
    def input_size(self) -> int:
        return self._n_features * self.spec.history_points
```

(`self.feature_cols` is already initialised to `None` in `__init__`; keep that line, and keep it AFTER any early attribute setup so the properties never read a missing attribute.)

- [ ] **Step 4: Size the net from the dataset in `train()`**

In `NNModel.train`, hoist manifest capture ABOVE `build()` and remove the later duplicate call. Change:

```python
        if self.spec.seed is not None:
            torch.manual_seed(self.spec.seed)

        self.build()

        train_view, val_view = self._split_dataset(dataset)
        # Capture the normalisation manifest + feature_cols for self-contained
        # checkpoints (leakage guard: stats are the TRAIN stats from the dataset).
        self._capture_manifest(dataset)
```

to:

```python
        if self.spec.seed is not None:
            torch.manual_seed(self.spec.seed)

        # Capture the manifest + resolved feature_cols BEFORE build so the net
        # is sized to the dataset's (possibly ragged) feature width, not the
        # spec's uniform product. Stats are the TRAIN stats (leakage guard).
        self._capture_manifest(dataset)
        self.build()

        train_view, val_view = self._split_dataset(dataset)
```

- [ ] **Step 5: Run model tests GREEN (incl. existing width/forward tests)**

```bash
docker compose run --rm nn-train python3 -m pytest tests/unit/nn/test_nn_model.py -v
# Expected: PASS — new tests + existing (test_input_size_from_spec, forward-pass, train tests)
```

- [ ] **Step 6: Commit**

```bash
git add nn/nn_model.py tests/unit/nn/test_nn_model.py
git commit -m "feat(nn): size NNModel input width from resolved feature_cols"
```

---

## Task 3: Load path sizes from bundled `feature_cols` (checkpoint round-trip)

**Files:**
- Modify: `nn/nn_model.py` (`load_model` ~695-714)
- Test: `tests/unit/nn/test_nn_model.py`

**Interfaces:**
- Consumes: checkpoint bundle `{"feature_cols": dict[str, list[str]], "manifest": ..., "spec": ..., "state_dict": ...}`
- Produces: a reloaded `NNModel` whose `input_size` equals the trained (possibly ragged) width.

- [ ] **Step 1: Write failing round-trip test**

Add to `tests/unit/nn/test_nn_model.py` (reuses the ragged dataset builder):

```python
def test_checkpoint_roundtrip_preserves_ragged_width(tmp_path):
    from indicators import DataAttributes
    from nn.nn_dataset import NNDataset
    from tests.unit.nn.test_nn_dataset import make_wide_df, small_spec

    df = make_wide_df(rows=120)
    spec = small_spec(
        timeframes=[15, 60], indicators=["logret", "rsi_14"],
        layers=[LayerSpec(kind="dense", units=8)], epochs=1, device="cpu",
    )
    ds = NNDataset.build(df, DataAttributes(), spec, dataset_dir=str(tmp_path))
    trained = NNModel(spec)
    trained.train(ds)
    assert trained.input_size == 3 * spec.history_points

    path = str(tmp_path / "ckpt.pt")
    trained.save_model(path)

    loaded = NNModel(spec)
    loaded.load_model(path)
    assert loaded.feature_cols == trained.feature_cols
    assert loaded.input_size == trained.input_size          # ragged width, NOT 2*2*hp
    x = np.random.randn(loaded.input_size).astype("float32")
    assert loaded.run(x).shape[0] == loaded.output_size
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose run --rm nn-train python3 -m pytest \
  tests/unit/nn/test_nn_model.py::test_checkpoint_roundtrip_preserves_ragged_width -v
# Expected: FAIL — load_model rebuilds width from spec arithmetic (sets feature_cols AFTER build)
```

- [ ] **Step 3: Reorder `load_model` — set feature_cols before build, drop spec arithmetic**

Replace (currently ~698-713):

```python
        self.spec = _spec_from_dict(bundle["spec"])
        self.input_size = (
            len(self.spec.indicators)
            * len(self.spec.timeframes)
            * self.spec.history_points
        )
        self.output_size = self._compute_output_size(self.spec)
        self.device = resolve_device(self.spec.device)

        self.model = None
        self.build()
        self.model.load_state_dict(bundle["state_dict"])
        self.model.to(self.device)

        self.manifest = bundle.get("manifest")
        self.feature_cols = bundle.get("feature_cols")
        self.is_trained = True
```

with:

```python
        self.spec = _spec_from_dict(bundle["spec"])
        self.output_size = self._compute_output_size(self.spec)
        self.device = resolve_device(self.spec.device)

        # Restore the resolved feature_cols BEFORE build so the rebuilt net is
        # sized to the trained (possibly ragged) width — input_size/_n_features
        # read from feature_cols, not spec arithmetic.
        self.manifest = bundle.get("manifest")
        self.feature_cols = bundle.get("feature_cols")

        self.model = None
        self.build()
        self.model.load_state_dict(bundle["state_dict"])
        self.model.to(self.device)
        self.is_trained = True
```

- [ ] **Step 4: Run test GREEN**

```bash
docker compose run --rm nn-train python3 -m pytest \
  tests/unit/nn/test_nn_model.py::test_checkpoint_roundtrip_preserves_ragged_width -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add nn/nn_model.py tests/unit/nn/test_nn_model.py
git commit -m "feat(nn): rebuild checkpoint width from bundled feature_cols"
```

---

## Task 4: Turn the boundary integration test GREEN + full NN suite in Docker

**Files:**
- Create: `tests/unit/nn/test_ragged_feature_selection.py` (from the "Layer boundary" section above, if not already added)

**Interfaces:**
- Consumes: Task 1 (ragged build), Task 2 (train sizing), Task 3 (load sizing).
- Produces: end-to-end proof the NNDataset→NNModel seam handles ragged widths in the real image.

- [ ] **Step 1: Ensure the boundary test file exists** (content from the "Layer boundary" section).

- [ ] **Step 2: Run the boundary integration test GREEN in Docker**

```bash
docker compose run --rm nn-train python3 -m pytest tests/unit/nn/test_ragged_feature_selection.py -v
# Expected: PASS
```

- [ ] **Step 3: Run the FULL NN unit suite in Docker (regression gate)**

```bash
docker compose run --rm nn-train python3 -m pytest tests/unit/nn -v
# Expected: PASS — no regressions across dataset/model/orchestrator/checkpoint tests
```

- [ ] **Step 4: Commit**

```bash
git add tests/unit/nn/test_ragged_feature_selection.py
git commit -m "test(nn): boundary integration for ragged per-TF feature selection"
```

---

## Task 5 (optional, separate concern): enable the TF-restricted features in `nn_spec.yaml`

Mechanism-only work is done above. This task makes the current experiment path actually *select* the previously-unusable families.

**Files:**
- Modify: `configs/nn_spec.yaml` (`indicators:` list)

**Interfaces:**
- Consumes: the ragged selector (Tasks 1–3).
- Produces: a spec that trains on an align rung + cyclical time across multiple TFs without crashing.

- [ ] **Step 1: Add TF-restricted names to `nn_spec.yaml indicators:`**

Example additions (align rung selects only where it exists; cyclical drops at 1440):

```yaml
indicators:
  - rsi_14
  - logret
  - range_atr
  - ema_50_minus_close
  - macd_12_26_9_slope
  - align_60      # resolves at tf=15 only; dropped elsewhere (logged)
  - sin_tod       # dropped at tf=1440 (logged)
  - cos_tod
```

- [ ] **Step 2: Docker training smoke** (requires `df_with_indicators.pkl` in the data volume)

```bash
docker compose run --rm nn-train python3 trainer.py nn_train
# Expected: dataset builds, training runs; logs show dropped per-TF pairs, no "feature columns missing"
```

- [ ] **Step 3: Commit**

```bash
git add configs/nn_spec.yaml
git commit -m "chore(nn): select align/cyclical features via ragged selector"
```

> If the full impl-A feature set is wanted, extend `indicators:` with the Group-1/2/3 bare names catalogued in `plans/impl_2/phase-11-nn-module/task-03-nn-features.md`; the ragged selector drops non-applicable `(tf, ind)` pairs instead of crashing.

---

## Self-Review

**Spec coverage:**
- Ragged selection honoring `applies_to` → Task 1. ✅
- Width from resolved selection (train) → Task 2. ✅
- Width from bundled feature_cols (load/inference) → Task 3. ✅
- align ladder + cyclical-1440 trainable end-to-end → Task 4 boundary test + Task 5 config. ✅
- Guards (zero-TF typo error, empty-TF error, logged drops) → Task 1. ✅
- Non-goals (no schema/strategist/`nn:`/`_z` change) → respected; no task touches them. ✅

**Placeholder scan:** none — every code/test/command step is concrete.

**Type consistency:** `feature_cols_by_tf: dict[str, list[str]]` (string TF keys) consistent across dataset build, manifest, `NNModel.feature_cols`, and `_n_features` sum. `_n_features`/`input_size` are properties in Tasks 2–3; `run()` and `build()` read them unchanged. Fallback (`feature_cols is None`) preserves `test_input_size_from_spec`.

**Risk note:** `input_size` changes from a stored attribute to a property — any code assigning `model.input_size = ...` breaks. Only `load_model` did (removed in Task 3). Verified no other assignment via `grep -n "\.input_size\s*=" nn/*.py`.
