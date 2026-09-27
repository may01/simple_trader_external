# Task 01: NN_SPEC_PATH spec override

**Phase:** 17 — NN Training Orchestration
**Depends on:** —
**Produces:** nn/device.py::nn_spec_path() ; NNOrchestrator.from_trainer reads nn_spec_path()

## Goal

Let the NN spec file location be overridden via the `NN_SPEC_PATH` environment
variable. Today `NNOrchestrator.from_trainer` hard-codes `"configs/nn_spec.yaml"`,
so the orchestrator cannot be pointed at a spec living on a mounted data volume
(e.g. `/trader_data_long/...`) without editing code. Add a single source of truth
helper `nn_spec_path()` in `nn/device.py` (next to the existing env-reading helpers
`resolve_device` and `nn_artefact_root`) and make `from_trainer` consume it.

## Context

`nn/device.py` already centralises environment-driven configuration for the NN
layer: `resolve_device()` and `nn_artefact_root(pair)` (which reads
`NN_ARTEFACT_ROOT` / `DATA_ROOT`). The spec path is the one remaining hard-coded
configuration string. `nn_spec_path()` is the natural home for it — pure-python,
no torch, so it is unit-testable without the GPU image. `from_trainer` changes by
exactly one line: the argument to `NNModelSpec.from_yaml(...)`.

The default must stay `"configs/nn_spec.yaml"` so existing behaviour is unchanged
when `NN_SPEC_PATH` is unset.

## Files

### Modify
- `main/nn/device.py` — add `nn_spec_path()` after the existing helpers (uses the
  already-present `import os` at top; ~3 new lines).
- `main/nn/nn_orchestrator.py` — `from_trainer` (lines 79-104): change the import
  line `from nn.device import nn_artefact_root` → `from nn.device import nn_artefact_root, nn_spec_path`
  and the spec-load line `base_spec = NNModelSpec.from_yaml("configs/nn_spec.yaml")`
  → `base_spec = NNModelSpec.from_yaml(nn_spec_path())` (2 lines changed, no other
  lines touched).

### Create
- `main/tests/nn/test_nn_spec_path.py` — new test module (3 tests).

## Interface

```python
# main/nn/device.py  (new helper, alongside resolve_device / nn_artefact_root)
def nn_spec_path() -> str: ...   # os.environ.get("NN_SPEC_PATH", "configs/nn_spec.yaml")
```

```python
# main/nn/nn_orchestrator.py  (from_trainer — ONLY the import + spec-load lines change)
@classmethod
def from_trainer(cls, pair: str, trainer: "object") -> "NNOrchestrator": ...
#   from nn.device import nn_artefact_root, nn_spec_path
#   base_spec = NNModelSpec.from_yaml(nn_spec_path())
```

## TDD Steps

- [ ] **Step 0: Branch for the task.**
  ```bash
  cd /home/om/projects/simple_trader/main
  git checkout experimental_imp_2
  git pull --ff-only
  git checkout -b feat/nn-spec-path-override
  ```
  Expected: `Switched to a new branch 'feat/nn-spec-path-override'`.

- [ ] **Step 1: RED — default when NN_SPEC_PATH unset.**
  Create `main/tests/nn/test_nn_spec_path.py` with exactly this content:
  ```python
  import yaml

  from nn.device import nn_spec_path
  from nn.nn_model_spec import NNModelSpec


  def test_nn_spec_path_default_when_unset(monkeypatch):
      monkeypatch.delenv("NN_SPEC_PATH", raising=False)
      assert nn_spec_path() == "configs/nn_spec.yaml"
  ```
  Run (pure-python, no torch):
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/test_nn_spec_path.py -q
  ```
  Expected: FAIL — `ImportError: cannot import name 'nn_spec_path' from 'nn.device'`
  (collection error: the helper does not exist yet).

- [ ] **Step 2: GREEN — add `nn_spec_path()`.**
  In `main/nn/device.py`, after `nn_artefact_root`, add:
  ```python
  def nn_spec_path() -> str:
      return os.environ.get("NN_SPEC_PATH", "configs/nn_spec.yaml")
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/test_nn_spec_path.py -q
  ```
  Expected: PASS — `1 passed`.

- [ ] **Step 3: RED — returns env value when NN_SPEC_PATH set.**
  Append to `main/tests/nn/test_nn_spec_path.py`:
  ```python
  def test_nn_spec_path_uses_env_when_set(monkeypatch):
      monkeypatch.setenv("NN_SPEC_PATH", "/trader_data_long/x/spec.yaml")
      assert nn_spec_path() == "/trader_data_long/x/spec.yaml"
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/test_nn_spec_path.py -q
  ```
  Expected: PASS — `2 passed` (the Step 2 impl already reads the env var; this test
  locks the behaviour in and guards against regressing the default-only form).
  Commit checkpoint after this step (helper + its two unit tests are complete):
  ```bash
  cd /home/om/projects/simple_trader/main
  git add nn/device.py tests/nn/test_nn_spec_path.py
  git commit -m "feat(nn): NN_SPEC_PATH spec override"
  ```

- [ ] **Step 4: RED — integration: loading via nn_spec_path() honours the env file.**
  Append to `main/tests/nn/test_nn_spec_path.py`:
  ```python
  def test_from_yaml_via_nn_spec_path_loads_env_spec(monkeypatch, tmp_path):
      spec = NNModelSpec.default()
      spec.name = "phase17_override_spec"
      spec_file = tmp_path / "spec.yaml"
      spec_file.write_text(yaml.safe_dump(spec.to_dict()))

      monkeypatch.setenv("NN_SPEC_PATH", str(spec_file))
      loaded = NNModelSpec.from_yaml(nn_spec_path())
      assert loaded.name == "phase17_override_spec"
  ```
  This test imports `NNModelSpec`, which pulls in torch, so it runs in Docker:
  ```bash
  cd /home/om/projects/simple_trader && docker compose run --rm nn-train \
    python -m pytest tests/nn/test_nn_spec_path.py -q
  ```
  Expected: PASS for tests 1-2; for test 3 it depends on the `NNModelSpec` API. If
  `NNModelSpec.default()` / `.to_dict()` / `.name` already exist, this is GREEN. If
  the test errors with `AttributeError` on `to_dict`/`default`/`name`, fix the test
  to match the real `NNModelSpec` surface in `nn/nn_model_spec.py` (the contract:
  build a spec object, serialise it to the temp yaml file, set `NN_SPEC_PATH` to it,
  and assert `NNModelSpec.from_yaml(nn_spec_path()).name` round-trips). Do NOT change
  `nn_spec_path()` — only the test serialisation calls. Re-run until PASS — `3 passed`.

- [ ] **Step 5: RED — wire `from_trainer` to `nn_spec_path()`.**
  In `main/nn/nn_orchestrator.py`, inside `from_trainer` (lines 79-104), change the
  two lines only:
  ```python
          from nn.device import nn_artefact_root, nn_spec_path
          base_spec = NNModelSpec.from_yaml(nn_spec_path())
  ```
  (was `from nn.device import nn_artefact_root` and
  `base_spec = NNModelSpec.from_yaml("configs/nn_spec.yaml")`.)
  Verify nothing else regressed — run the full nn suite plus this module in Docker:
  ```bash
  cd /home/om/projects/simple_trader && docker compose run --rm nn-train \
    python -m pytest tests/nn/test_nn_spec_path.py tests/nn/test_nn_orchestrator.py -q
  ```
  Expected: PASS — all tests green (`from_trainer` now resolves the spec path through
  the helper; default path string is unchanged so existing orchestrator tests still
  pass).

- [ ] **Step 6: GREEN gate — full module passes in the image.**
  Confirm the pure-python helper tests also pass inside the image (no `.venv`):
  ```bash
  cd /home/om/projects/simple_trader && docker compose run --rm nn-train \
    python -m pytest tests/nn/test_nn_spec_path.py -q
  ```
  Expected: PASS — `3 passed`.

- [ ] **Step 7: Commit the wiring.**
  ```bash
  cd /home/om/projects/simple_trader/main
  git add nn/nn_orchestrator.py tests/nn/test_nn_spec_path.py
  git commit -m "feat(nn): NN_SPEC_PATH spec override"
  ```
  Expected: clean commit; `git status` shows nothing pending under `nn/` or
  `tests/nn/`.
