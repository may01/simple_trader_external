# Task 02: build_spec respects declared layers (ADR-0001)

**Phase:** 17 — NN Training Orchestration
**Depends on:** —
**Produces:** TrainingLoop.build_spec keeps declared layer kinds/count/params; Optuna tunes units(width)+lr+dropout only; no depth suggestion

## Goal

Make `TrainingLoop.build_spec` honour the architecture declared in `base_spec`. The Optuna trial must tune **width (`units`), `learning_rate`, and `dropout` only** — never the layer **kind** and never the layer **count** (`depth`). Each declared layer keeps its `kind` and `params`; only its `units` is replaced with the single suggested width. This is the concrete code change that delivers ADR-0001 ("architecture is reasoned, not searched"): architecture comes from the spec (authored by Tier 0/2 agents), numerics come from Optuna.

## Context

ADR-0001 says the engine must train **any declared architecture**, while Optuna does numeric tuning only. The engine already complies: `_SpecNet`/`_add_layer` in `nn/nn_model.py` already builds `dense`/`lstm`/`gru`/`conv1d` and mixed stacks (verified — see DECISIONS-LOG "Things already wired"). The **only** place that forces dense-only is the current `TrainingLoop.build_spec`, which (a) suggests a `depth` int and (b) overwrites `spec.layers` with a freshly-built list of `LayerSpec(kind="dense", units=units)` — discarding the declared kinds, params, and count entirely.

Current code (`nn/training_loop.py`, ~lines 350–402), the lines this task changes:

```python
        lr_lo, lr_hi = self._bounds(space, "lr", (1e-5, 1e-2))
        depth_lo, depth_hi = self._bounds(space, "depth", (1, 3))
        units_lo, units_hi = self._bounds(space, "units", (16, 128))
        drop_lo, drop_hi = self._bounds(space, "dropout", (0.0, 0.5))
        lr = trial.suggest_float("lr", lr_lo, lr_hi, log=True)
        depth = trial.suggest_int("depth", int(round(depth_lo)), int(round(depth_hi)))
        units = trial.suggest_int("units", int(round(units_lo)), int(round(units_hi)))
        dropout = trial.suggest_float("dropout", drop_lo, drop_hi)
        spec.learning_rate = lr
        spec.dropout = dropout
        spec.layers = [LayerSpec(kind="dense", units=int(units)) for _ in range(int(depth))]
        spec.seed = int(seed) if seed is not None else 0
        return spec
```

The fix: drop the `depth` bound + `depth` suggestion entirely, and replace the `spec.layers` rebuild with a per-layer width override that **preserves kind/params/count**:

```python
        spec.layers = [dataclasses.replace(layer, units=int(units)) for layer in spec.layers]
```

`import copy`, `import dataclasses`, and `from nn.nn_model_spec import LayerSpec, NNModelSpec` are already imported in `training_loop.py`. `LayerSpec(kind: str, units: int, params: dict)` is a dataclass; `NNModelSpec.default()` returns a one-dense-layer spec. An lstm base can be built with
`dataclasses.replace(NNModelSpec.default(), layers=[LayerSpec(kind="lstm", units=32, params={"num_layers": 2})])`.

**Knock-on (do NOT do it here):** with `depth` no longer suggested, the `search_space.depth` key in `main/configs/nn_search.yaml` becomes unused/dead. **Leave it for now** — it is removed as part of the config migration in **Task 03**. This task changes code only, no config.

These tests construct real Optuna `Trial` objects (so `suggest_*` actually run), so they import `optuna` and MUST run in the `nn-train` Docker image. Build a study with `optuna.create_study()` and call `study.ask()` to get a live `Trial`; after `build_spec` returns, call `study.tell(trial, 0.0)` to close it cleanly.

## Files

- `main/nn/training_loop.py` — modify `TrainingLoop.build_spec` (and its `_bounds` call sites for `depth`).
- `main/tests/nn/test_build_spec_layers.py` — **new** test module (create dir/`__init__.py` if absent).

## Interface

```python
# nn/training_loop.py  — TrainingLoop.build_spec (unchanged signature)
def build_spec(self, base_spec, proposal, trial, seed) -> NNModelSpec: ...
# Behaviour contract (ADR-0001):
#   - returns deepcopy of base_spec with:
#       spec.learning_rate = trial.suggest_float("lr", lr_lo, lr_hi, log=True)
#       spec.dropout       = trial.suggest_float("dropout", drop_lo, drop_hi)
#       units              = trial.suggest_int("units", units_lo, units_hi)
#       spec.layers        = [dataclasses.replace(layer, units=int(units)) for layer in spec.layers]
#       spec.seed          = int(seed) if seed is not None else 0
#   - NO trial.suggest_int("depth", ...) is called  ->  "depth" not in trial.params
#   - layer .kind and .params are preserved verbatim; len(spec.layers) == len(base_spec.layers)
```

A minimal `TrainingLoop` for tests is constructed with an empty `search_config` so `build_spec` falls back to default bounds:

```python
from nn.training_loop import TrainingLoop
loop = TrainingLoop(search_config={})
```

(If `TrainingLoop.__init__` requires more args, pass `search_config={}` and any other required args as `None`/empty per its signature — check the constructor before writing the test fixture.)

---

## TDD Steps

> Run everything in Docker (these tests build real Optuna trials):
> `docker compose run --rm nn-train python -m pytest tests/nn/test_build_spec_layers.py -q`
> One cycle = write one failing test → run (RED, see the stated reason) → minimal impl → run (GREEN) → commit.

### Setup

- [ ] **Branch first.**
  ```bash
  cd /home/om/projects/simple_trader/main
  git checkout experimental_imp_2
  git checkout -b phase17-t02-build-spec-layers
  ```

- [ ] Ensure the test package exists.
  ```bash
  ls tests/nn/__init__.py 2>/dev/null || { mkdir -p tests/nn && touch tests/nn/__init__.py; }
  ```

- [ ] Confirm the `TrainingLoop` constructor signature so the test fixture is correct.
  ```bash
  sed -n '108,130p' nn/training_loop.py
  ```
  Expected: `__init__(self, search_config: dict, ...)`. Construct test loops as `TrainingLoop(search_config={})`, filling any other required positional args with `None`/`[]` as the signature dictates. Record the exact call you will use in the test file.

---

### Cycle 1 — lstm base: kind + params preserved, units suggested

- [ ] **Write the failing test.** Create `tests/nn/test_build_spec_layers.py`:
  ```python
  """Tests for TrainingLoop.build_spec — ADR-0001: architecture declared, not searched.

  build_spec must keep the layer KIND, PARAMS, and COUNT declared in base_spec,
  and let Optuna tune width (units), learning_rate and dropout only — no depth.

  These build real Optuna Trial objects (suggest_* must actually run), so this
  module runs in the nn-train image:
      docker compose run --rm nn-train python -m pytest tests/nn/test_build_spec_layers.py -q
  """

  import dataclasses

  import optuna

  from nn.nn_model_spec import LayerSpec, NNModelSpec
  from nn.training_loop import TrainingLoop


  def _loop():
      # Empty search_config → build_spec uses its default bounds.
      return TrainingLoop(search_config={})


  def _ask():
      study = optuna.create_study()
      return study, study.ask()


  def test_lstm_base_preserves_kind_and_params():
      base = dataclasses.replace(
          NNModelSpec.default(),
          layers=[LayerSpec(kind="lstm", units=32, params={"num_layers": 2})],
      )
      study, trial = _ask()
      spec = _loop().build_spec(base, proposal=None, trial=trial, seed=7)
      study.tell(trial, 0.0)

      assert len(spec.layers) == 1
      layer = spec.layers[0]
      assert layer.kind == "lstm"
      assert layer.params == {"num_layers": 2}
      # width is whatever Optuna suggested, and it must equal trial's "units"
      assert layer.units == trial.params["units"]
      # architecture untouched in the base object (deepcopy, not mutation)
      assert base.layers[0].units == 32
  ```

- [ ] **Run — expect RED.**
  ```bash
  docker compose run --rm nn-train python -m pytest tests/nn/test_build_spec_layers.py -q
  ```
  Expected FAIL: current `build_spec` rebuilds `spec.layers` as `[LayerSpec(kind="dense", units=units) for _ in range(depth)]`, so `layer.kind == "lstm"` fails with `AssertionError: 'dense' != 'lstm'` (and `layer.params` is `{}`). It may also create 1–3 layers from the `depth` suggestion.

- [ ] **Minimal impl.** Edit `TrainingLoop.build_spec` in `nn/training_loop.py`. Remove the `depth` bound + suggestion, and replace the layer rebuild with a per-layer width override. The full updated method body (suggestion block onward):
  ```python
          lr_lo, lr_hi = self._bounds(space, "lr", (1e-5, 1e-2))
          units_lo, units_hi = self._bounds(space, "units", (16, 128))
          drop_lo, drop_hi = self._bounds(space, "dropout", (0.0, 0.5))
          lr = trial.suggest_float("lr", lr_lo, lr_hi, log=True)
          units = trial.suggest_int("units", int(round(units_lo)), int(round(units_hi)))
          dropout = trial.suggest_float("dropout", drop_lo, drop_hi)
          spec.learning_rate = lr
          spec.dropout = dropout
          # ADR-0001: keep declared architecture (kind/params/count); tune width only.
          spec.layers = [dataclasses.replace(layer, units=int(units)) for layer in spec.layers]
          spec.seed = int(seed) if seed is not None else 0
          return spec
  ```
  Delete the now-removed lines: `depth_lo, depth_hi = self._bounds(space, "depth", (1, 3))` and `depth = trial.suggest_int("depth", int(round(depth_lo)), int(round(depth_hi)))`.

- [ ] **Run — expect GREEN.**
  ```bash
  docker compose run --rm nn-train python -m pytest tests/nn/test_build_spec_layers.py -q
  ```
  Expected PASS: `1 passed`.

- [ ] **Commit.**
  ```bash
  git add nn/training_loop.py tests/nn/test_build_spec_layers.py tests/nn/__init__.py
  git commit -m "fix(nn): build_spec respects declared layer architecture (ADR-0001)"
  ```

---

### Cycle 2 — mixed 2-layer base: both kinds + count preserved

- [ ] **Add the failing test** to `tests/nn/test_build_spec_layers.py`:
  ```python
  def test_mixed_base_preserves_both_kinds_and_count():
      base = dataclasses.replace(
          NNModelSpec.default(),
          layers=[
              LayerSpec(kind="conv1d", units=24, params={"kernel_size": 3}),
              LayerSpec(kind="dense", units=48),
          ],
      )
      study, trial = _ask()
      spec = _loop().build_spec(base, proposal=None, trial=trial, seed=1)
      study.tell(trial, 0.0)

      assert len(spec.layers) == 2  # not collapsed to dense-only
      assert [layer.kind for layer in spec.layers] == ["conv1d", "dense"]
      assert spec.layers[0].params == {"kernel_size": 3}
      # both layers get the single suggested width
      suggested = trial.params["units"]
      assert spec.layers[0].units == suggested
      assert spec.layers[1].units == suggested
  ```

- [ ] **Run — expect RED** (before re-running the fix this proves the count/kind guard):
  ```bash
  docker compose run --rm nn-train python -m pytest tests/nn/test_build_spec_layers.py::test_mixed_base_preserves_both_kinds_and_count -q
  ```
  If Cycle 1's impl is already in place this will **PASS immediately** (the impl already preserves count/kind). That is acceptable — this test is a regression guard for the mixed case. If you are running tests against the pre-fix code it FAILs with `AssertionError` on the kinds list (`['dense', ...]`) / count.

- [ ] **Run full file — expect GREEN.**
  ```bash
  docker compose run --rm nn-train python -m pytest tests/nn/test_build_spec_layers.py -q
  ```
  Expected PASS: `2 passed`.

- [ ] **Commit.**
  ```bash
  git add tests/nn/test_build_spec_layers.py
  git commit -m "test(nn): build_spec preserves mixed conv1d+dense architecture (ADR-0001)"
  ```

---

### Cycle 3 — lr/dropout/seed set; no depth parameter

- [ ] **Add the failing test:**
  ```python
  def test_sets_lr_dropout_seed_and_no_depth_param():
      base = dataclasses.replace(
          NNModelSpec.default(),
          layers=[LayerSpec(kind="gru", units=16, params={"num_layers": 1})],
      )
      study, trial = _ask()
      spec = _loop().build_spec(base, proposal=None, trial=trial, seed=42)
      study.tell(trial, 0.0)

      # numerics come from the trial / seed
      assert spec.learning_rate == trial.params["lr"]
      assert spec.dropout == trial.params["dropout"]
      assert spec.seed == 42
      # ADR-0001: depth is NOT a tuned parameter
      assert "depth" not in trial.params
      # the only tuned knobs are width/lr/dropout
      assert set(trial.params) == {"units", "lr", "dropout"}
  ```

- [ ] **Run — expect RED on pre-fix code / GREEN on fixed code.**
  ```bash
  docker compose run --rm nn-train python -m pytest tests/nn/test_build_spec_layers.py::test_sets_lr_dropout_seed_and_no_depth_param -q
  ```
  On unfixed code: FAIL — `"depth" in trial.params` (the old `suggest_int("depth", ...)` ran), so both `"depth" not in trial.params` and the `set(...) == {"units","lr","dropout"}` assertions fail. On fixed code: PASS.

- [ ] **Run full file — expect GREEN.**
  ```bash
  docker compose run --rm nn-train python -m pytest tests/nn/test_build_spec_layers.py -q
  ```
  Expected PASS: `3 passed`.

- [ ] **Commit.**
  ```bash
  git add tests/nn/test_build_spec_layers.py
  git commit -m "test(nn): build_spec tunes lr/dropout/units only, no depth (ADR-0001)"
  ```

---

### Cycle 4 — dense base regression guard

- [ ] **Add the failing test:**
  ```python
  def test_dense_base_still_works():
      # NNModelSpec.default() already has one dense layer (units=64).
      base = NNModelSpec.default()
      assert [layer.kind for layer in base.layers] == ["dense"]

      study, trial = _ask()
      spec = _loop().build_spec(base, proposal=None, trial=trial, seed=0)
      study.tell(trial, 0.0)

      assert len(spec.layers) == 1
      assert spec.layers[0].kind == "dense"
      assert spec.layers[0].units == trial.params["units"]
      assert spec.seed == 0
  ```

- [ ] **Run — expect GREEN** (the fix already covers dense; this locks the regression):
  ```bash
  docker compose run --rm nn-train python -m pytest tests/nn/test_build_spec_layers.py::test_dense_base_still_works -q
  ```
  Expected PASS. (On pre-fix code it would FAIL only if `depth` happened to suggest >1 layer; the guard is here so future edits can't re-break the dense path.)

- [ ] **Run full file — expect GREEN.**
  ```bash
  docker compose run --rm nn-train python -m pytest tests/nn/test_build_spec_layers.py -q
  ```
  Expected PASS: `4 passed`.

- [ ] **Commit.**
  ```bash
  git add tests/nn/test_build_spec_layers.py
  git commit -m "test(nn): dense base regression guard for build_spec (ADR-0001)"
  ```

---

### Final verification

- [ ] Full nn suite still green in Docker (no other test relied on the `depth` param):
  ```bash
  docker compose run --rm nn-train python -m pytest tests/nn -q
  ```
  Expected: all pass. If any other test asserts on a `"depth"` trial param, update that test to match ADR-0001 (depth is no longer tuned) and note it in the commit.

- [ ] Confirm `depth` is gone from `build_spec`:
  ```bash
  grep -n "depth" nn/training_loop.py
  ```
  Expected: no match inside `build_spec` (a leftover `search_space.depth` may still exist in `configs/nn_search.yaml` — that dead key is removed in **Task 03**, not here).
