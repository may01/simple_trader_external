# Task 08: runner.run_version_training (launch + poll)

**Phase:** 17 — NN Training Orchestration
**Depends on:** Task 01 (NN_SPEC_PATH), Task 05 (spec_store)
**Produces:** nn/orchestration/runner.py::VersionResult, run_version_training(...)

## Goal

Provide `run_version_training` — the single seam between the Phase 17 loop driver
and the in-container Tier-1 search. Given a spec written to the artefact volume
(Task 05 spec_store) and a study name, it launches the existing `nn-train` Docker
service for exactly ONE version: the spec is selected via `NN_SPEC_PATH` (Task 01)
and the run is scoped to a study via `NN_STUDY`, in `NN_TRAIN_MODE=search`. It then
reads that study's `tracking/{study}/best.json`, extracts the holdout score, and
returns a `VersionResult`. The driver calls this once per candidate version and
compares `holdout_score` to pick a winner.

The unit of work is one `docker compose run` invocation per version. `docker
compose run` runs the container in the FOREGROUND to completion, so "launch" and
"poll" collapse into: run the subprocess (with a timeout), then read the best.json
the container wrote. The poll loop only exists to absorb the brief window between
container exit and the file being flushed/visible on the shared volume.

## Context

`run_version_training` is split into three pieces so the logic is testable without
Docker:

- `_read_best_json(tracking_dir, study)` — pure file read. Returns the parsed dict
  from `{tracking_dir}/{study}/best.json`, or `None` if the file does not exist.
- `_extract_holdout_score(best)` — pure reducer. `best` maps each `group_key` to a
  trial record; return the MAX holdout score across groups (`0.0` if there are
  none).
- `run_version_training(...)` — orchestration: build the docker command, run it,
  poll for best.json, reduce to a score, wrap in `VersionResult`.

Facts that pin the implementation:

- **Docker entry (verbatim):**
  `docker compose run --rm -e NN_SPEC_PATH=<spec_path> -e NN_STUDY=<study> -e NN_TRAIN_MODE=search nn-train`.
  Build this as a list for `subprocess.run` — never a shell string. `extra_env`
  contributes additional `-e KEY=VALUE` pairs (one `-e` flag per entry), appended
  after the three fixed env flags and before `nn-train`.

- **Tracking dir:** `tracking_dir = nn_artefact_root(pair) / "tracking"`, where
  `nn_artefact_root` lives in `nn/device.py` and reads `NN_ARTEFACT_ROOT` and
  `DATA_ROOT` from the environment at call time (returns
  `{NN_ARTEFACT_ROOT}/{DATA_ROOT}/{pair}/nn`). So `run_version_training` needs both
  env vars set (the real container sets them; tests either monkeypatch
  `nn_artefact_root` or set the two env vars to point inside `tmp_path`).

- **best.json shape:** a dict keyed by `group_key`; each value is a trial record.
  The record contains a nested `"holdout": {"holdout_score": float, ...}` (plus
  `"metrics"`, `"spec_hash"`, `"promoted"`). `_extract_holdout_score` reads
  `record["holdout"]["holdout_score"]` when the nested `holdout` mapping is present,
  else falls back to `record.get("holdout_score", 0.0)`, and takes the MAX across
  all `group_key`s.

- **Polling / failure modes:** run `subprocess.run(cmd, timeout=timeout_s,
  check=False)`. If the subprocess times out, `subprocess.run` raises
  `subprocess.TimeoutExpired` — let it surface as a `TimeoutError` (re-raise as
  `TimeoutError`). After the subprocess returns, poll `_read_best_json` for a few
  seconds (short sleeps) to let the file appear on the volume; if it never appears,
  raise `RuntimeError`. The container's exit code is intentionally NOT treated as
  fatal here (`check=False`): the source of truth for success is whether a usable
  best.json exists — a search that exits non-zero but wrote a best.json is still a
  usable result, and a clean exit with no best.json is still a failure.

- This module is pure-python at import time (`json`, `os`, `subprocess`, `time`,
  `dataclasses`, `pathlib`) plus `nn.device.nn_artefact_root`. No torch. So the
  unit tests run under `main/.venv` without the GPU image.

### Manual Docker end-to-end (NOT part of the pure suite)

A real `nn-train` launch is expensive and needs the NN data volume populated. The
genuine end-to-end test lives in **Task 11**. For local sanity, the same command
this function builds can be run by hand:

```bash
cd /home/om/projects/simple_trader
docker compose run --rm \
  -e NN_SPEC_PATH=/trader_data_long/<pair>/nn/specs/<version>.yaml \
  -e NN_STUDY=phase17_v0 \
  -e NN_TRAIN_MODE=search \
  nn-train
# then inspect the score the container wrote:
cat <NN_ARTEFACT_ROOT>/<DATA_ROOT>/<pair>/nn/tracking/phase17_v0/best.json
```

In this task that path is exercised only behind a `@pytest.mark.docker_e2e` marker
that SKIPS when `NN_DATA_ROOT` data is absent — it documents the seam without
running a multi-hour search in the pure suite.

## Files

### Create
- `main/nn/orchestration/runner.py` — `VersionResult` dataclass,
  `run_version_training`, and the two pure helpers `_read_best_json` /
  `_extract_holdout_score`.
- `main/tests/nn/orchestration/test_runner.py` — new test module (6 pure tests +
  1 skipped docker-e2e marker).

### May need (only if absent)
- `main/nn/orchestration/__init__.py` and `main/tests/nn/orchestration/__init__.py`
  — created in earlier Phase 17 tasks (05/06/07). Create empty if missing so the
  package imports resolve.

## Interface

```python
# nn/orchestration/runner.py
import json, os, subprocess, time
from dataclasses import dataclass
from pathlib import Path

from nn.device import nn_artefact_root


@dataclass
class VersionResult:
    study: str
    holdout_score: float
    best: dict


def run_version_training(spec_path: str, study: str, *, pair: str,
                         timeout_s: float, extra_env: dict | None = None) -> VersionResult: ...


def _read_best_json(tracking_dir: Path, study: str) -> dict | None: ...
#   parse {tracking_dir}/{study}/best.json, or None if absent


def _extract_holdout_score(best: dict) -> float: ...
#   best = {group_key: {"holdout":{"holdout_score":float}|..., "metrics":...}}
#   -> max holdout_score across groups; 0.0 if none
```

Behavioural contract:

```python
# docker cmd (list form) built by run_version_training:
["docker", "compose", "run", "--rm",
 "-e", f"NN_SPEC_PATH={spec_path}",
 "-e", f"NN_STUDY={study}",
 "-e", "NN_TRAIN_MODE=search",
 # then one ["-e", f"{k}={v}"] pair per extra_env item, if any
 "nn-train"]

# success: container wrote tracking/{study}/best.json
result = run_version_training(spec, study, pair=pair, timeout_s=T)
assert result.study == study
assert result.holdout_score == _extract_holdout_score(result.best)

# subprocess timeout -> TimeoutError
# subprocess finished but no best.json ever appears -> RuntimeError
```

## TDD Steps

- [ ] **Step 0: Branch for the task.**
  ```bash
  cd /home/om/projects/simple_trader/main
  git checkout experimental_imp_2
  git pull --ff-only
  git checkout -b feat/nn-version-runner
  ```
  Expected: `Switched to a new branch 'feat/nn-version-runner'`.

- [ ] **Step 1: RED — `_read_best_json` returns None when the file is absent.**
  Create `main/tests/nn/orchestration/test_runner.py` with exactly this content:
  ```python
  import json
  import os
  import subprocess

  import pytest

  from nn.orchestration import runner
  from nn.orchestration.runner import (
      VersionResult,
      _extract_holdout_score,
      _read_best_json,
      run_version_training,
  )


  def test_read_best_json_returns_none_when_absent(tmp_path):
      # tracking dir exists but the {study}/best.json was never written
      assert _read_best_json(tmp_path, "phase17_v0") is None
  ```
  Run (pure-python, no torch):
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_runner.py -q
  ```
  Expected: FAIL — `ModuleNotFoundError: No module named 'nn.orchestration.runner'`
  (the module does not exist yet). If `nn.orchestration` itself is missing, create
  an empty `main/nn/orchestration/__init__.py` and
  `main/tests/nn/orchestration/__init__.py`, then re-run; the error must narrow to
  the missing `runner` module.

- [ ] **Step 2: GREEN — create the module with `_read_best_json`.**
  Create `main/nn/orchestration/runner.py` with exactly this content:
  ```python
  import json
  import os
  import subprocess
  import time
  from dataclasses import dataclass
  from pathlib import Path

  from nn.device import nn_artefact_root


  @dataclass
  class VersionResult:
      study: str
      holdout_score: float
      best: dict


  def _read_best_json(tracking_dir: Path, study: str) -> dict | None:
      """Parse {tracking_dir}/{study}/best.json, or return None if absent."""
      path = Path(tracking_dir) / study / "best.json"
      if not path.exists():
          return None
      with open(path) as f:
          return json.load(f)
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_runner.py -q
  ```
  Expected: FAIL — `ImportError: cannot import name '_extract_holdout_score'`
  (the test module imports four names; only `VersionResult` and `_read_best_json`
  exist so the import line still errors). This is the expected RED for Step 1's
  behaviour: the named test cannot run until the imports resolve. Continue to
  Step 4 to add the remaining symbols; the assertion inside
  `test_read_best_json_returns_none_when_absent` is already satisfied by the code
  above and will go green as soon as the import line resolves.

- [ ] **Step 3: RED — `_read_best_json` parses a written best.json.**
  Append to `main/tests/nn/orchestration/test_runner.py`:
  ```python
  def test_read_best_json_parses_written_file(tmp_path):
      study = "phase17_v0"
      study_dir = tmp_path / study
      study_dir.mkdir()
      payload = {"all": {"holdout": {"holdout_score": 0.41}}}
      (study_dir / "best.json").write_text(json.dumps(payload))

      assert _read_best_json(tmp_path, study) == payload
  ```
  (Still RED at the collection level — the import line for
  `_extract_holdout_score` / `run_version_training` fails, so the whole module
  cannot be collected. Run it to confirm the same ImportError as Step 2.)
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_runner.py -q
  ```
  Expected: FAIL — `ImportError: cannot import name '_extract_holdout_score'`.

- [ ] **Step 4: GREEN — add `_extract_holdout_score` (max across groups, 0.0 default).**
  In `main/nn/orchestration/runner.py`, add directly after `_read_best_json`:
  ```python
  def _extract_holdout_score(best: dict) -> float:
      """Max holdout_score across all group_keys in best.json; 0.0 if none.

      Each value is a trial record that either nests the score under
      "holdout" -> "holdout_score", or carries a flat "holdout_score".
      """
      if not best:
          return 0.0
      scores: list[float] = []
      for record in best.values():
          if not isinstance(record, dict):
              continue
          holdout = record.get("holdout")
          if isinstance(holdout, dict) and "holdout_score" in holdout:
              scores.append(float(holdout["holdout_score"]))
          else:
              scores.append(float(record.get("holdout_score", 0.0)))
      return max(scores) if scores else 0.0
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_runner.py -q
  ```
  Expected: FAIL — `ImportError: cannot import name 'run_version_training'`
  (the import line still references the not-yet-defined function). The two
  `_read_best_json` tests are correct and will pass once the import resolves.

- [ ] **Step 5: RED — `_extract_holdout_score` picks the max across multiple groups.**
  Append to `main/tests/nn/orchestration/test_runner.py`:
  ```python
  def test_extract_holdout_score_max_across_groups():
      best = {
          "all": {"holdout": {"holdout_score": 0.41}},
          "g2": {"holdout": {"holdout_score": 0.45}},
      }
      assert _extract_holdout_score(best) == 0.45
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_runner.py -q
  ```
  Expected: FAIL — `ImportError: cannot import name 'run_version_training'`
  (collection still blocked by the missing function).

- [ ] **Step 6: RED — `_extract_holdout_score` returns 0.0 for empty/missing.**
  Append to `main/tests/nn/orchestration/test_runner.py`:
  ```python
  def test_extract_holdout_score_empty_is_zero():
      assert _extract_holdout_score({}) == 0.0
      # record present but no holdout info anywhere -> 0.0 fallback
      assert _extract_holdout_score({"all": {"metrics": {"loss": 1.0}}}) == 0.0
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_runner.py -q
  ```
  Expected: FAIL — `ImportError: cannot import name 'run_version_training'`.

- [ ] **Step 7: GREEN — add `run_version_training` (launch + poll).**
  In `main/nn/orchestration/runner.py`, add at the end of the file:
  ```python
  def run_version_training(spec_path: str, study: str, *, pair: str,
                           timeout_s: float, extra_env: dict | None = None) -> VersionResult:
      """Launch the nn-train service for one version, poll best.json, return score.

      Runs `docker compose run --rm` in the foreground to completion with
      NN_SPEC_PATH / NN_STUDY / NN_TRAIN_MODE=search set, then reads the study's
      best.json off the shared artefact volume.

      Raises:
          TimeoutError: the container did not finish within timeout_s.
          RuntimeError: the container finished but no best.json was produced.
      """
      cmd = [
          "docker", "compose", "run", "--rm",
          "-e", f"NN_SPEC_PATH={spec_path}",
          "-e", f"NN_STUDY={study}",
          "-e", "NN_TRAIN_MODE=search",
      ]
      for key, value in (extra_env or {}).items():
          cmd += ["-e", f"{key}={value}"]
      cmd.append("nn-train")

      try:
          subprocess.run(cmd, timeout=timeout_s, check=False)
      except subprocess.TimeoutExpired as exc:
          raise TimeoutError(
              f"nn-train timed out after {timeout_s}s for study {study!r}"
          ) from exc

      tracking_dir = nn_artefact_root(pair) / "tracking"

      best = None
      # absorb the flush/visibility window between container exit and file landing
      for _ in range(10):
          best = _read_best_json(tracking_dir, study)
          if best is not None:
              break
          time.sleep(0.5)

      if best is None:
          raise RuntimeError(
              f"nn-train produced no best.json for study {study!r} "
              f"under {tracking_dir / study}"
          )

      return VersionResult(
          study=study,
          holdout_score=_extract_holdout_score(best),
          best=best,
      )
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_runner.py -q
  ```
  Expected: PASS — `5 passed` (imports now resolve; the four pure-helper tests
  plus collection succeed). No docker test exists yet.

- [ ] **Step 8: RED — `run_version_training` builds the right cmd and returns the score
  (monkeypatched subprocess + pre-written best.json).**
  Append to `main/tests/nn/orchestration/test_runner.py`:
  ```python
  def test_run_version_training_launches_and_returns_score(tmp_path, monkeypatch):
      study = "phase17_v0"
      spec_path = "/trader_data_long/link_usdt/nn/specs/v0.yaml"
      pair = "link_usdt"

      # tracking dir -> tmp_path/tracking ; pre-write best.json the "container" left
      tracking_dir = tmp_path / "tracking"
      study_dir = tracking_dir / study
      study_dir.mkdir(parents=True)
      payload = {"all": {"holdout": {"holdout_score": 0.41}}}
      (study_dir / "best.json").write_text(json.dumps(payload))

      monkeypatch.setattr(runner, "nn_artefact_root", lambda p: tmp_path)

      captured = {}

      def fake_run(cmd, *args, **kwargs):
          captured["cmd"] = cmd
          captured["timeout"] = kwargs.get("timeout")
          captured["check"] = kwargs.get("check")
          return subprocess.CompletedProcess(cmd, 0)

      monkeypatch.setattr(runner.subprocess, "run", fake_run)

      result = run_version_training(
          spec_path, study, pair=pair, timeout_s=123.0,
          extra_env={"NN_EXTRA": "x"},
      )

      cmd = captured["cmd"]
      assert "nn-train" in cmd
      assert "-e" in cmd and f"NN_SPEC_PATH={spec_path}" in cmd
      assert f"NN_STUDY={study}" in cmd
      assert "NN_TRAIN_MODE=search" in cmd
      assert "NN_EXTRA=x" in cmd
      assert cmd[-1] == "nn-train"  # service name is the trailing positional
      assert captured["timeout"] == 123.0
      assert captured["check"] is False

      assert isinstance(result, VersionResult)
      assert result.study == study
      assert result.holdout_score == 0.41
      assert result.best == payload
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_runner.py -q
  ```
  Expected: PASS — `6 passed`. The Step 7 implementation already builds the cmd in
  this exact shape and reads the pre-written best.json (the loop finds it on the
  first iteration, so no real sleep elapses). If `nn_artefact_root` is NOT
  monkeypatched on the `runner` module object (e.g. patched on `nn.device`
  instead), the call would hit the real env and KeyError — patch
  `runner.nn_artefact_root`, the name as imported into the module under test.

- [ ] **Step 9: RED — `run_version_training` raises RuntimeError when best.json never appears.**
  Append to `main/tests/nn/orchestration/test_runner.py`:
  ```python
  def test_run_version_training_raises_when_no_best_json(tmp_path, monkeypatch):
      study = "phase17_v0"
      monkeypatch.setattr(runner, "nn_artefact_root", lambda p: tmp_path)

      # subprocess is a no-op: container "ran" but wrote nothing
      monkeypatch.setattr(
          runner.subprocess, "run",
          lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 0),
      )
      # keep the poll loop instant — no real waiting for a file that never comes
      monkeypatch.setattr(runner.time, "sleep", lambda s: None)

      with pytest.raises(RuntimeError, match="no best.json"):
          run_version_training(
              "/specs/v0.yaml", study, pair="link_usdt", timeout_s=5.0,
          )
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_runner.py -q
  ```
  Expected: PASS — `7 passed`. The poll loop exhausts its 10 iterations (each
  `time.sleep` is a no-op), `best` stays `None`, and the `RuntimeError` fires with
  the "no best.json" message. If this HANGS, the `time.sleep` monkeypatch did not
  take — confirm the module calls `time.sleep` (not `from time import sleep`), so
  `runner.time.sleep` is the patch target.

- [ ] **Step 10: Document the manual Docker e2e behind a skip marker.**
  Append to `main/tests/nn/orchestration/test_runner.py`:
  ```python
  @pytest.mark.docker_e2e
  @pytest.mark.skipif(
      not os.environ.get("NN_DATA_ROOT")
      or not os.path.isdir(os.environ.get("NN_DATA_ROOT", "")),
      reason="NN_DATA_ROOT data absent; real nn-train e2e lives in Task 11",
  )
  def test_run_version_training_real_docker():
      # Genuine end-to-end (build a spec via spec_store, launch nn-train, assert a
      # real holdout_score lands) is implemented in Task 11. This placeholder only
      # documents the seam and stays skipped unless NN_DATA_ROOT data is present.
      pytest.skip("real nn-train e2e covered by Task 11")
  ```
  Register the marker so `-q` does not warn: append to `main/pytest.ini` (or the
  `[tool.pytest.ini_options]` markers list in `pyproject.toml`, whichever the repo
  uses) the line:
  ```
  docker_e2e: end-to-end test that launches the real nn-train Docker service
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_runner.py -q
  ```
  Expected: PASS — `7 passed, 1 skipped` (the docker_e2e test is collected and
  skipped; no unregistered-marker warning). If you see
  `PytestUnknownMarkWarning`, the marker registration in Step 10 was missed.

- [ ] **Step 11: GREEN gate — full pure suite for the module.**
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_runner.py -q
  ```
  Expected: PASS — `7 passed, 1 skipped`.

- [ ] **Step 12: GREEN gate — no regression in the orchestration suite.**
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/ -q
  ```
  Expected: PASS — the Phase 17 orchestration tests (spec_store etc.) stay green;
  only a new module and test file were added.

- [ ] **Step 13: Commit.**
  ```bash
  cd /home/om/projects/simple_trader/main
  git add nn/orchestration/runner.py tests/nn/orchestration/test_runner.py
  # include pytest.ini / pyproject.toml only if the marker line was added there
  git add pytest.ini 2>/dev/null || true
  git commit -m "feat(nn): version training runner (launch+poll)"
  ```
  Expected: clean commit; `git status` shows nothing pending under
  `nn/orchestration/` or `tests/nn/orchestration/`.
