# Task 04: NNModelSpec to_dict/to_yaml round-trip

**Phase:** 17 — NN Training Orchestration
**Depends on:** —
**Produces:** NNModelSpec.to_dict() -> dict ; NNModelSpec.to_yaml(path: str) -> None ; from_yaml(to_yaml(x)) preserves spec_hash

## Goal

Add `to_dict()` and `to_yaml(path)` to `NNModelSpec` so the Phase 17 loop driver
can persist a version's spec to the artefact volume and re-load it identically.
The acceptance bar is a true round-trip: `from_yaml(to_yaml(x))` must reconstruct a
spec whose `spec_hash` equals the original's. `NNModelSpec` already has the read
side (`from_yaml`) and a private `_canonical`/`asdict`-based hash; this task adds
the write side and proves the two are inverses.

## Context

`nn/nn_model_spec.py` defines the spec model as nested dataclasses: `LayerSpec`,
`GroupingSpec`, `TargetSpec`, and the top-level `NNModelSpec`. The file already
imports everything we need — `from dataclasses import asdict, dataclass, field`,
`import yaml`, `import json`, `import hashlib`.

Key facts that make the round-trip work:

- `spec_hash` is a property computed over `_canonical(self)`, which calls
  `asdict(spec)`, pops `device` and `seed`, then sorts dict keys recursively while
  keeping list order. So `device`/`seed` do NOT affect the hash, but everything
  else does (layer kinds, units, params; target horizons; timeframes; etc.).
- `from_yaml(path)` reads `yaml.safe_load`, pops `grouping`/`timeframes`/`layers`/
  `targets` to build the nested objects, coerces `timeframes`→`list[int]` and each
  target's `horizons`→`list[int]`, then calls
  `cls(grouping=..., timeframes=..., layers=..., targets=..., **raw)` with the
  remaining keys.
- `asdict(self)` produces plain nested dicts that already contain ALL of those keys
  (grouping/timeframes/layers/targets plus every scalar field), so dumping
  `to_dict()` and re-reading through `from_yaml` reconstructs the same object.

Pure-python: `to_dict`/`to_yaml` touch only `asdict`, `yaml`, and `os` — no torch.
So the new tests run both under `main/.venv` and inside the `nn-train` image.

The serialisation order should be stable and human-readable, so `to_yaml` dumps
with `sort_keys=False` (preserve dataclass field order in the file). Correctness
does not depend on file key order — `from_yaml` reads by key, and `_canonical`
re-sorts before hashing — so `sort_keys=False` is purely for readability.

## Files

### Modify
- `main/nn/nn_model_spec.py` — add two methods on `NNModelSpec`: `to_dict(self)`
  and `to_yaml(self, path)`. Uses the already-present `asdict` and `yaml` imports;
  `to_yaml` adds a local `import os` for the parent-dir creation. No other code in
  the file changes (the hash, `from_yaml`, and the dataclasses are untouched).

### Create
- `main/tests/nn/test_spec_roundtrip.py` — new test module (4 tests, one per
  behaviour below).

## Interface

```python
# main/nn/nn_model_spec.py  (two new methods on NNModelSpec)

def to_dict(self) -> dict: ...
#   return asdict(self)  — nested dataclasses become plain dicts, INCLUDING device+seed

def to_yaml(self, path: str) -> None: ...
#   makedirs(dirname(path)) if a dir component exists, then yaml.safe_dump(self.to_dict(), f, sort_keys=False)
```

Round-trip contract:

```python
reloaded = NNModelSpec.from_yaml(path_written_by(spec.to_yaml))
assert reloaded.spec_hash == spec.spec_hash
```

## TDD Steps

- [ ] **Step 0: Branch for the task.**
  ```bash
  cd /home/om/projects/simple_trader/main
  git checkout experimental_imp_2
  git pull --ff-only
  git checkout -b feat/nn-spec-yaml-roundtrip
  ```
  Expected: `Switched to a new branch 'feat/nn-spec-yaml-roundtrip'`.

- [ ] **Step 1: RED — `to_dict()` is a plain nested dict including device+seed.**
  Create `main/tests/nn/test_spec_roundtrip.py` with exactly this content:
  ```python
  import dataclasses

  from nn.nn_model_spec import LayerSpec, NNModelSpec


  def test_to_dict_is_plain_nested_dict():
      spec = NNModelSpec.default()
      d = spec.to_dict()

      assert isinstance(d, dict)
      # no dataclass instances survive — everything is plain dict/list/scalar
      assert not dataclasses.is_dataclass(d)
      assert "device" in d and "seed" in d  # asdict keeps these (hash drops them, dict does not)

      assert isinstance(d["layers"], list) and len(d["layers"]) >= 1
      for layer in d["layers"]:
          assert isinstance(layer, dict)
          assert set(("kind", "units", "params")) <= set(layer)
          assert isinstance(layer["kind"], str)
          assert isinstance(layer["params"], dict)

      assert isinstance(d["targets"], list) and len(d["targets"]) >= 1
      for tgt in d["targets"]:
          assert isinstance(tgt, dict)
          assert "name" in tgt and "horizons" in tgt
          assert isinstance(tgt["horizons"], list)

      assert isinstance(d["grouping"], dict)
  ```
  Run (pure-python, no torch):
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/test_spec_roundtrip.py -q
  ```
  Expected: FAIL — `AttributeError: 'NNModelSpec' object has no attribute 'to_dict'`.

- [ ] **Step 2: GREEN — add `to_dict()`.**
  In `main/nn/nn_model_spec.py`, add this method to `NNModelSpec` (alongside the
  `spec_hash` property / `from_yaml`):
  ```python
      def to_dict(self) -> dict:
          return asdict(self)
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/test_spec_roundtrip.py -q
  ```
  Expected: PASS — `1 passed`.

- [ ] **Step 3: RED — round-trip of `default()` preserves `spec_hash`.**
  Append to `main/tests/nn/test_spec_roundtrip.py`:
  ```python
  def test_to_yaml_from_yaml_roundtrip_preserves_hash(tmp_path):
      original = NNModelSpec.default()
      path = tmp_path / "spec.yaml"

      original.to_yaml(str(path))
      assert path.exists()

      reloaded = NNModelSpec.from_yaml(str(path))
      assert reloaded.spec_hash == original.spec_hash
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/test_spec_roundtrip.py -q
  ```
  Expected: FAIL — `AttributeError: 'NNModelSpec' object has no attribute 'to_yaml'`
  (test 1 still passes; this new test errors on the missing method).

- [ ] **Step 4: GREEN — add `to_yaml()`.**
  In `main/nn/nn_model_spec.py`, add this method to `NNModelSpec` (directly after
  `to_dict`):
  ```python
      def to_yaml(self, path: str) -> None:
          import os

          parent = os.path.dirname(path)
          if parent:
              os.makedirs(parent, exist_ok=True)
          with open(path, "w") as f:
              yaml.safe_dump(self.to_dict(), f, sort_keys=False)
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/test_spec_roundtrip.py -q
  ```
  Expected: PASS — `2 passed`. (The round-trip is exact: `from_yaml` pops
  `grouping`/`timeframes`/`layers`/`targets`, `asdict` emitted all of them, and
  `_canonical` ignores `device`/`seed`, so the rebuilt spec hashes identically.)

- [ ] **Step 5: RED — round-trip preserves a non-trivial mixed architecture.**
  Append to `main/tests/nn/test_spec_roundtrip.py`:
  ```python
  def test_roundtrip_preserves_mixed_layers_and_timeframes(tmp_path):
      original = dataclasses.replace(
          NNModelSpec.default(),
          timeframes=[15, 60],
          layers=[
              LayerSpec("conv1d", 16, {"kernel_size": 5}),
              LayerSpec("lstm", 32, {"num_layers": 2}),
          ],
      )
      path = tmp_path / "spec.yaml"
      original.to_yaml(str(path))

      reloaded = NNModelSpec.from_yaml(str(path))

      assert [l.kind for l in reloaded.layers] == ["conv1d", "lstm"]
      assert [l.units for l in reloaded.layers] == [16, 32]
      assert reloaded.layers[0].params == {"kernel_size": 5}
      assert reloaded.layers[1].params == {"num_layers": 2}
      assert reloaded.timeframes == [15, 60]
      assert reloaded.spec_hash == original.spec_hash
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/test_spec_roundtrip.py -q
  ```
  Expected: PASS — `3 passed`. The `to_dict`/`to_yaml` from Steps 2/4 already
  preserve layer kinds, units, the `params` dict, and `timeframes` order, so this
  test goes green immediately. If it FAILS on `params` or `timeframes`, the bug is
  in serialisation, NOT the test: confirm `to_yaml` writes `self.to_dict()`
  unchanged and that `from_yaml` coerces `timeframes` to `list[int]`; do not edit
  the assertions to match a broken dump.

- [ ] **Step 6: RED — `to_yaml` creates missing parent directories.**
  Append to `main/tests/nn/test_spec_roundtrip.py`:
  ```python
  def test_to_yaml_creates_parent_dirs(tmp_path):
      original = NNModelSpec.default()
      path = tmp_path / "a" / "b" / "spec.yaml"  # parents a/, a/b/ do not exist yet

      original.to_yaml(str(path))

      assert path.exists()
      reloaded = NNModelSpec.from_yaml(str(path))
      assert reloaded.spec_hash == original.spec_hash
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/test_spec_roundtrip.py -q
  ```
  Expected: PASS — `4 passed`. The `os.makedirs(parent, exist_ok=True)` added in
  Step 4 creates `a/b/` before the open, so the write succeeds. If this test FAILS
  with `FileNotFoundError`, the makedirs guard is missing or guarding on the wrong
  variable — fix `to_yaml`, not the test.

- [ ] **Step 7: GREEN gate — full module passes inside the image.**
  The whole module is pure-python, but importing `NNModelSpec` pulls in the nn
  package, so confirm it also passes in the GPU image (no `.venv`):
  ```bash
  cd /home/om/projects/simple_trader && docker compose run --rm nn-train \
    python -m pytest tests/nn/test_spec_roundtrip.py -q
  ```
  Expected: PASS — `4 passed`.

- [ ] **Step 8: GREEN gate — no regression in the spec/orchestrator suites.**
  ```bash
  cd /home/om/projects/simple_trader && docker compose run --rm nn-train \
    python -m pytest tests/nn/ -q
  ```
  Expected: PASS — the existing nn tests stay green (only two methods were added to
  `NNModelSpec`; `spec_hash`, `from_yaml`, and the dataclasses are unchanged).

- [ ] **Step 9: Commit.**
  ```bash
  cd /home/om/projects/simple_trader/main
  git add nn/nn_model_spec.py tests/nn/test_spec_roundtrip.py
  git commit -m "feat(nn): NNModelSpec to_dict/to_yaml round-trip"
  ```
  Expected: clean commit; `git status` shows nothing pending under `nn/` or
  `tests/nn/`.
