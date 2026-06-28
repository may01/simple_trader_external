# Task 05: spec_store.materialize_spec

**Phase:** 17 — NN Training Orchestration
**Depends on:** Task 04 (NNModelSpec.to_yaml)
**Produces:** nn/orchestration/spec_store.py::materialize_spec(spec: NNModelSpec, artefact_root: Path) -> Path

## Goal

Add a `materialize_spec(spec, artefact_root)` helper that persists a version's
`spec.yaml` onto the artefact volume under `specs/{spec_hash}/`, returning the
written path. This is the write-side that lets the loop driver hand the trainer a
single env var — `NN_SPEC_PATH` (Task 01) — pointing at the materialised file.

The path is **content-addressed**: it is keyed by `spec.spec_hash`, so the same
spec always lands at the same place (idempotent re-write, never an error) and two
different specs are isolated into different `specs/{hash}/` directories. The helper
is a thin composition over Task 04's `NNModelSpec.to_yaml`, which already creates
the parent directories — so `materialize_spec` does no `os.makedirs` of its own.

## Context

After Task 04, `NNModelSpec` has the full write side:

- `spec.spec_hash` — property, sha256 hex digest over the canonically-normalised
  spec (device/seed excluded). Stable across processes for the same spec content.
- `spec.to_yaml(path: str) -> None` — dumps `self.to_dict()` to `path` with
  `yaml.safe_dump(..., sort_keys=False)`, and **creates the parent directory**
  (`os.makedirs(dirname(path), exist_ok=True)`) before writing.
- `NNModelSpec.from_yaml(path: str)` — read side; reconstructs an equal-hashed
  spec from the YAML. `NNModelSpec.default()` — minimal valid spec for tests.

So `materialize_spec` is pure composition: compute the hash-keyed path, call
`to_yaml`, return the path. Because `to_yaml` makes the parent dir and overwrites
in place, calling `materialize_spec` twice on the same spec just rewrites the same
bytes to the same path — idempotent by construction, no guard needed.

The artefact layout this establishes (consumed downstream by the loop driver and
the trainer via `NN_SPEC_PATH`):

```
{artefact_root}/
  specs/
    {spec_hash}/
      spec.yaml          ← written here
```

This task is the FIRST file in the new `nn/orchestration/` package. It creates the
package (`nn/orchestration/__init__.py`) and the matching test package
(`tests/nn/orchestration/__init__.py`).

Pure-python: `spec_store.py` imports only `pathlib` and `NNModelSpec`; the helper
touches only `to_yaml`/`spec_hash` (no torch). The test imports `NNModelSpec` and
`materialize_spec`, both torch-free. So the suite runs both under `main/.venv` and
inside the `nn-train` image.

## Files

### Create

- `main/nn/orchestration/__init__.py` — empty (marks the package).
- `main/nn/orchestration/spec_store.py` — the `materialize_spec` helper (one
  function; see Interface).
- `main/tests/nn/orchestration/__init__.py` — empty (the test dir is a package;
  matches the `tests/unit/nn/__init__.py` precedent and avoids pytest basename
  import clashes — there is no pytest config / rootdir override in `main/`, so
  test modules are imported by basename).
- `main/tests/nn/orchestration/test_spec_store.py` — new test module (4 tests,
  one per behaviour below), using the `tmp_path` fixture.

> Note: `main/nn/__init__.py` already exists, so the new sub-package imports as
> `nn.orchestration.spec_store`. `main/tests/__init__.py` already exists; this
> task adds `tests/nn/__init__.py` only if it is missing (Task 04 created
> `tests/nn/test_spec_roundtrip.py` without one — see Step 1 for the guard).

## Interface

```python
# nn/orchestration/spec_store.py
from pathlib import Path

from nn.nn_model_spec import NNModelSpec


def materialize_spec(spec: NNModelSpec, artefact_root: Path) -> Path:
    """Persist spec to {artefact_root}/specs/{spec.spec_hash}/spec.yaml.

    Content-addressed by spec_hash: the same spec always maps to the same path,
    so re-materialising is idempotent (overwrites in place, never raises) and
    distinct specs are isolated under distinct specs/{hash}/ directories.

    NNModelSpec.to_yaml creates the parent directory, so no makedirs here.

    Returns the written path.
    """
    path = artefact_root / "specs" / spec.spec_hash / "spec.yaml"
    spec.to_yaml(str(path))
    return path
```

Contract the tests pin:

```python
returned = materialize_spec(spec, artefact_root)
assert returned == artefact_root / "specs" / spec.spec_hash / "spec.yaml"
assert returned.exists()
assert NNModelSpec.from_yaml(str(returned)).spec_hash == spec.spec_hash
```

## TDD Steps

- [ ] **Step 0: Branch for the task.**
  ```bash
  cd /home/om/projects/simple_trader/main
  git checkout experimental_imp_2
  git pull --ff-only
  git checkout -b feat/nn-spec-store-materialize
  ```
  Expected: `Switched to a new branch 'feat/nn-spec-store-materialize'`.

- [ ] **Step 1: Create the test + source packages (no logic yet).**
  Create the new package markers and the test package. `nn/__init__.py` and
  `tests/__init__.py` already exist; create the missing ones only.
  ```bash
  cd /home/om/projects/simple_trader/main
  mkdir -p nn/orchestration tests/nn/orchestration
  touch nn/orchestration/__init__.py
  [ -f tests/nn/__init__.py ] || touch tests/nn/__init__.py
  touch tests/nn/orchestration/__init__.py
  ```
  Create `main/nn/orchestration/spec_store.py` with a stub so the test module can
  import the symbol and fail on behaviour, not on `ImportError`:
  ```python
  # nn/orchestration/spec_store.py
  """spec_store — persist NNModelSpec to the artefact volume (content-addressed).

  Phase 17 Task 05. The loop driver materialises each version's spec under
  specs/{spec_hash}/spec.yaml and hands the path to the trainer via NN_SPEC_PATH.
  """

  from pathlib import Path

  from nn.nn_model_spec import NNModelSpec


  def materialize_spec(spec: NNModelSpec, artefact_root: Path) -> Path:
      raise NotImplementedError
  ```
  Run (confirms the package imports cleanly under the venv):
  ```bash
  cd /home/om/projects/simple_trader/main && \
    .venv/bin/python -c "from nn.orchestration.spec_store import materialize_spec; print('import ok')"
  ```
  Expected: `import ok`.

- [ ] **Step 2: RED — returns the hash-keyed path and writes the file.**
  Create `main/tests/nn/orchestration/test_spec_store.py` with exactly this
  content:
  ```python
  from pathlib import Path

  from nn.nn_model_spec import LayerSpec, NNModelSpec
  from nn.orchestration.spec_store import materialize_spec


  def test_materialize_returns_hash_keyed_path_and_writes_file(tmp_path):
      spec = NNModelSpec.default()

      returned = materialize_spec(spec, tmp_path)

      expected = tmp_path / "specs" / spec.spec_hash / "spec.yaml"
      assert returned == expected
      assert returned.exists()
      assert returned.is_file()
  ```
  Run (pure-python, no torch):
  ```bash
  cd /home/om/projects/simple_trader/main && \
    .venv/bin/pytest tests/nn/orchestration/test_spec_store.py -q
  ```
  Expected: FAIL — `NotImplementedError` raised from `materialize_spec`.

- [ ] **Step 3: GREEN — implement `materialize_spec`.**
  Replace the body of `materialize_spec` in `main/nn/orchestration/spec_store.py`
  so the file reads exactly:
  ```python
  # nn/orchestration/spec_store.py
  """spec_store — persist NNModelSpec to the artefact volume (content-addressed).

  Phase 17 Task 05. The loop driver materialises each version's spec under
  specs/{spec_hash}/spec.yaml and hands the path to the trainer via NN_SPEC_PATH.
  """

  from pathlib import Path

  from nn.nn_model_spec import NNModelSpec


  def materialize_spec(spec: NNModelSpec, artefact_root: Path) -> Path:
      """Persist spec to {artefact_root}/specs/{spec.spec_hash}/spec.yaml.

      Content-addressed by spec_hash: the same spec always maps to the same path,
      so re-materialising is idempotent (overwrites in place, never raises) and
      distinct specs are isolated under distinct specs/{hash}/ directories.

      NNModelSpec.to_yaml creates the parent directory, so no makedirs here.

      Returns the written path.
      """
      path = artefact_root / "specs" / spec.spec_hash / "spec.yaml"
      spec.to_yaml(str(path))
      return path
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && \
    .venv/bin/pytest tests/nn/orchestration/test_spec_store.py -q
  ```
  Expected: PASS — `1 passed`. (`to_yaml` creates `specs/{hash}/` via its own
  `os.makedirs`, then writes `spec.yaml`.)

- [ ] **Step 4: RED — written file reloads with the same spec_hash.**
  Append to `main/tests/nn/orchestration/test_spec_store.py`:
  ```python
  def test_materialized_file_reloads_with_same_hash(tmp_path):
      spec = NNModelSpec.default()

      returned = materialize_spec(spec, tmp_path)

      reloaded = NNModelSpec.from_yaml(str(returned))
      assert reloaded.spec_hash == spec.spec_hash
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && \
    .venv/bin/pytest tests/nn/orchestration/test_spec_store.py -q
  ```
  Expected: PASS — `2 passed`. Task 04 guarantees the YAML round-trips, so this
  goes green immediately. If it FAILS on the hash, the bug is in Task 04's
  `to_yaml`/`from_yaml`, NOT here — do not weaken the assertion.

- [ ] **Step 5: RED — idempotent: calling twice returns the same path, no error.**
  Append to `main/tests/nn/orchestration/test_spec_store.py`:
  ```python
  def test_materialize_is_idempotent(tmp_path):
      spec = NNModelSpec.default()

      first = materialize_spec(spec, tmp_path)
      second = materialize_spec(spec, tmp_path)  # must not raise

      assert first == second
      assert second.exists()
      # second write reproduces identical bytes (content-addressed, deterministic dump)
      assert first.read_text() == second.read_text()
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && \
    .venv/bin/pytest tests/nn/orchestration/test_spec_store.py -q
  ```
  Expected: PASS — `3 passed`. The path is derived purely from `spec_hash`, and
  `to_yaml` opens the file in `"w"` mode (truncate-and-overwrite), so the second
  call rewrites the same path with the same content. If this FAILS with a
  `FileExistsError`, the implementation wrongly added an existence guard or
  `makedirs(..., exist_ok=False)` — remove it; idempotency comes from plain
  overwrite, not from skipping.

- [ ] **Step 6: RED — distinct specs land in distinct specs/{hash}/ dirs.**
  Append to `main/tests/nn/orchestration/test_spec_store.py`:
  ```python
  def test_distinct_specs_are_isolated_by_hash(tmp_path):
      import dataclasses

      spec_a = NNModelSpec.default()
      spec_b = dataclasses.replace(
          spec_a,
          layers=[LayerSpec("lstm", 128, {"num_layers": 2})],  # different architecture
      )
      assert spec_a.spec_hash != spec_b.spec_hash  # precondition: genuinely different

      path_a = materialize_spec(spec_a, tmp_path)
      path_b = materialize_spec(spec_b, tmp_path)

      assert path_a != path_b
      assert path_a.parent != path_b.parent  # different specs/{hash}/ dirs
      assert path_a.exists() and path_b.exists()

      # each file reloads to its own spec, no cross-contamination
      assert NNModelSpec.from_yaml(str(path_a)).spec_hash == spec_a.spec_hash
      assert NNModelSpec.from_yaml(str(path_b)).spec_hash == spec_b.spec_hash
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && \
    .venv/bin/pytest tests/nn/orchestration/test_spec_store.py -q
  ```
  Expected: PASS — `4 passed`. Hash-keyed paths give each spec its own directory.
  If the precondition `spec_a.spec_hash != spec_b.spec_hash` FAILS, the spec hash
  is ignoring `layers` — a Task 04 / `spec_hash` regression, not a fault here.

- [ ] **Step 7: GREEN gate — full module passes inside the image.**
  The module is pure-python, but importing it pulls in the `nn` package; confirm
  it also passes in the GPU image (no `.venv`):
  ```bash
  cd /home/om/projects/simple_trader && docker compose run --rm nn-train \
    python -m pytest tests/nn/orchestration/test_spec_store.py -q
  ```
  Expected: PASS — `4 passed`.

- [ ] **Step 8: GREEN gate — no regression in the nn suite.**
  ```bash
  cd /home/om/projects/simple_trader && docker compose run --rm nn-train \
    python -m pytest tests/nn/ -q
  ```
  Expected: PASS — the existing nn tests (including Task 04's
  `test_spec_roundtrip.py`) stay green; this task only adds a new package and a
  new test module.

- [ ] **Step 9: Commit.**
  ```bash
  cd /home/om/projects/simple_trader/main
  git add nn/orchestration/__init__.py nn/orchestration/spec_store.py \
          tests/nn/__init__.py tests/nn/orchestration/__init__.py \
          tests/nn/orchestration/test_spec_store.py
  git commit -m "feat(nn): spec_store.materialize_spec"
  ```
  Expected: clean commit; `git status` shows nothing pending under
  `nn/orchestration/` or `tests/nn/orchestration/`.
  (`tests/nn/__init__.py` only appears in the commit if Step 1 created it — drop
  it from `git add` if it already existed.)
