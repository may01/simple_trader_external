# Task 11: nn-train-orchestrator skill + CLI + e2e smoke

**Phase:** 17 — NN Training Orchestration
**Depends on:** Tasks 01–10
**Produces:** nn/orchestration/cli.py ; .agents/skills/nn-train-orchestrator/SKILL.md ; runbook ; e2e smoke test

## Goal

Tie Phase 17 together. Three things ship in this task:

1. **A thin CLI** (`nn/orchestration/cli.py`) — `python -m nn.orchestration.cli <cmd>`
   — a deterministic argparse wrapper over the Layer-B helpers
   (`materialize_spec`, `run_version_training`, `decide`). These are the
   "deterministic hands" the orchestrator skill calls so the agent never has to
   re-implement path math, the Docker launch, or the promote/revert arithmetic in
   freehand prose. Pure-python; unit-tested by monkeypatching the wrapped helpers.

2. **The `nn-train-orchestrator` skill** (`.agents/skills/nn-train-orchestrator/SKILL.md`)
   — the Tier-2 conductor. It walks the candidate archetypes one at a time and, for
   each archetype, runs the autonomous per-archetype lineage loop
   (investigate → materialize v1 → run-version → evolve → … until `decide.stop`),
   then **STOPS for a human gate** before the next archetype. Long trainings between
   version steps are driven by **ralph-loop / `/loop`** re-invoking the skill.

3. **An end-to-end Docker smoke** (`tests/nn/orchestration/test_lineage_e2e.py`)
   — marked `@pytest.mark.docker_e2e`, **SKIPPED** when the NN data
   (`NN_DATA_ROOT` / `link_usdt`) is absent. It materializes a tiny
   `NNModelSpec.default()` (epochs=5), runs ONE version via the real `nn-train`
   container on `link_usdt`, drives ONE evolve cycle, and asserts the artifacts.

The CLI and the e2e smoke get real TDD code. The skill + runbook are markdown.

## Context

- **The orchestrator drives the per-archetype lineage loop.** For one archetype:
  `investigate (Tier 0b)` → `materialize v1` → `run-version` → `evolve` (writes the
  version report.md, then `decide`) → if `not decide.stop`, emit the next spec →
  `run-version` → … until `decide.stop`. The skill ends a run after **one
  archetype's** lineage completes (its winner re-validated on 4y — see below). It
  then **STOPS for human review** — the operator inspects the lineage, then resumes
  the skill for the next archetype. The gate is *between* archetypes, never inside a
  lineage.
- **Long trainings are loop-driven.** A single `run-version` is a multi-hour
  `docker compose run` (Task 08). The skill does not block a single agent turn for
  hours: it is meant to be re-invoked between version steps by **ralph-loop**
  (`/ralph-loop`, Stop-hook feeds the same prompt back) or **`/loop`** (interval
  re-invoke). Each re-invocation reads the lineage's own files (last report.md,
  `best.json`) to resume where it left off — the loop is **stateless across turns,
  state lives in files** (the Ralph philosophy: prompt never changes, prior work
  persists in files).
- **Locked values (verbatim):** `trials_per_round 8`, `max_rounds 1`, `K=2`,
  `max_versions 6`, `margin 0.01`, `budget 28800s`. Iterate on **2y link_usdt**;
  **confirm on 4y**. The **4y re-validation of the promoted best is the final step
  of an archetype before the gate** — the lineage hill-climbs on 2y, and the winner
  is re-run once on 4y to confirm it generalises before the human reviews it.
- **The CLI is the deterministic seam.** Three subcommands, each wrapping exactly
  one Layer-B helper and printing a machine-readable line the skill can parse:
  - `materialize-spec` → prints the materialized volume path (one line).
  - `run-version` → prints JSON `{study, holdout_score}`.
  - `decide` → prints JSON of the `LineageDecision`.
- **e2e smoke shape (verbatim).** Materialize `NNModelSpec.default()` (tiny,
  epochs=5), run-version via Docker on `link_usdt` (skip if data absent), then drive
  ONE evolve cycle producing a v1 `report.md` + (if the loop continues) a v2 spec;
  assert: v1 `report.md` exists under the external `{archetype}/v1/` and parses via
  `parse_report`; `tracking/{study}/best.json` exists; the lineage produced ≥1
  version. Marker `@pytest.mark.docker_e2e`; skip when `NN_DATA_ROOT`/`link_usdt`
  data is absent.

Reference skills (read before authoring): **superpowers:writing-skills** (skill is
TDD on process docs — frontmatter `name` + `description`, "Use when …" description,
flat namespace, keep judgment inline) and **ralph-loop** (Bash `while true` /
Stop-hook re-invokes the same prompt; state persists in files between iterations) —
the SKILL.md must cite both for the long-training loop.

### Helpers wrapped (verbatim — do NOT re-read the source)

```python
from nn.orchestration.spec_store import materialize_spec
from nn.orchestration.runner import run_version_training, VersionResult
from nn.orchestration.lineage import decide, LineageDecision
from nn.nn_model_spec import NNModelSpec
from nn.device import nn_artefact_root
```

`materialize-spec` loads `NNModelSpec.from_yaml(spec-yaml)` then
`materialize_spec(spec, nn_artefact_root(pair))`.

This is pure-python at import time (`argparse`, `json`, plus the helper imports —
the helpers themselves are torch-free per Tasks 05/07/08). So the CLI unit tests run
under `main/.venv`. The e2e smoke needs the `nn-train` image + the data volume and
is the only Docker-touching test here.

## Files

### Create
- `main/nn/orchestration/cli.py` — argparse wrapper with `main(argv)` and the three
  subcommands. Pure-python; wraps the five helpers above.
- `main/tests/nn/orchestration/test_cli.py` — pure unit tests (monkeypatch each
  wrapped helper; assert arg parsing, the helper call args, and the printed output).
- `main/tests/nn/orchestration/test_lineage_e2e.py` — the `@pytest.mark.docker_e2e`
  smoke with the skip guard.
- `main/.agents/skills/nn-train-orchestrator/SKILL.md` — the orchestrator skill
  (markdown; frontmatter `name` + `description`).
- `external/docs/superpowers/plans/impl_2/phase-17-nn-training-orchestration/RUNBOOK.md`
  — the operator flow (docker compose + the CLI). **External repo** (docs never go
  in the code repo).

### May need (only if absent)
- `main/nn/orchestration/__init__.py` and `main/tests/nn/orchestration/__init__.py`
  — created in earlier Phase 17 tasks; create empty if missing.

## Interface

```python
# nn/orchestration/cli.py  — `python -m nn.orchestration.cli <cmd>`
# subcommands wrapping Layer-B helpers (deterministic hands for the skill):
#   materialize-spec --spec-yaml <path-in> --pair <pair>            → prints materialized volume path
#   run-version --spec-path <vol path> --study <name> --pair <pair> --timeout <s>  → prints JSON {study,holdout_score}
#   decide --best <f|none> --candidate <f> --margin <f> --strike <i> --k <i> --version-n <i> --max-versions <i> --elapsed <f> --budget <f>  → prints JSON of LineageDecision
def main(argv: list[str] | None = None) -> int: ...
```

Behavioural contract (the implementation MUST match these shapes):

```python
# materialize-spec: load + persist; print the on-volume path
spec = NNModelSpec.from_yaml(args.spec_yaml)
path = materialize_spec(spec, nn_artefact_root(args.pair))
print(path)            # one line: the materialized volume Path
return 0

# run-version: launch nn-train for one version; print {study, holdout_score}
r = run_version_training(args.spec_path, args.study, pair=args.pair, timeout_s=args.timeout)
print(json.dumps({"study": r.study, "holdout_score": r.holdout_score}))
return 0

# decide: pure promote/revert arithmetic; print the LineageDecision as JSON
#   --best accepts the literal "none" (→ best_score=None, first-version promote) or a float
best = None if args.best == "none" else float(args.best)
d = decide(best_score=best, candidate_score=args.candidate, margin=args.margin,
           strike_count=args.strike, K=args.k, version_n=args.version_n,
           max_versions=args.max_versions, elapsed_s=args.elapsed, budget_s=args.budget)
print(json.dumps({"action": d.action, "new_best": d.new_best,
                  "strike_count": d.strike_count, "stop": d.stop, "reason": d.reason}))
return 0
```

Notes for the implementer:

- Argparse with one subparser per command (`dest="cmd"`); `main` dispatches on
  `args.cmd`. Unknown/absent command → print usage and `return 2`.
- `--timeout` is a `float` (seconds); `--strike`/`--k`/`--version-n`/`--max-versions`
  are `int`; `--candidate`/`--margin`/`--elapsed`/`--budget` are `float`; `--best`
  is a **string** so it can carry the literal `"none"`.
- The wrapped helper names are imported at module top so the unit tests can
  monkeypatch them on the `cli` module object (e.g. `monkeypatch.setattr(cli,
  "decide", fake)`), not on their defining modules.
- `print` only the contract line — no banners — so the skill can `json.loads` /
  read the path directly from stdout.

## TDD Steps

- [ ] **Step 0: Branch for the task.**
  ```bash
  cd /home/om/projects/simple_trader/main
  git checkout experimental_imp_2
  git pull --ff-only
  git checkout -b feat/nn-orchestrator-skill-e2e
  ```
  Expected: `Switched to a new branch 'feat/nn-orchestrator-skill-e2e'`.

---

### Deliverable 1 — `nn/orchestration/cli.py` (pure TDD, RED→GREEN per subcommand)

- [ ] **Step 1: RED — `decide` subcommand parses args and prints the LineageDecision JSON.**
  Create `main/tests/nn/orchestration/test_cli.py` with exactly this content:
  ```python
  import json

  import pytest

  from nn.orchestration import cli
  from nn.orchestration.cli import main


  def test_decide_subcommand_calls_helper_and_prints_json(capsys, monkeypatch):
      captured = {}

      class FakeDecision:
          action = "promote"
          new_best = True
          strike_count = 0
          stop = False
          reason = "promote: +0.0200 ≥ margin 0.0100"

      def fake_decide(**kwargs):
          captured.update(kwargs)
          return FakeDecision()

      monkeypatch.setattr(cli, "decide", fake_decide)

      rc = main([
          "decide",
          "--best", "0.40", "--candidate", "0.42", "--margin", "0.01",
          "--strike", "0", "--k", "2", "--version-n", "2",
          "--max-versions", "6", "--elapsed", "100.0", "--budget", "28800.0",
      ])

      assert rc == 0
      # the literal float "0.40" parses to best_score=0.40 (NOT the "none" sentinel)
      assert captured == dict(
          best_score=0.40, candidate_score=0.42, margin=0.01,
          strike_count=0, K=2, version_n=2, max_versions=6,
          elapsed_s=100.0, budget_s=28800.0,
      )
      out = json.loads(capsys.readouterr().out)
      assert out == {
          "action": "promote", "new_best": True, "strike_count": 0,
          "stop": False, "reason": "promote: +0.0200 ≥ margin 0.0100",
      }
  ```
  Run (pure-python, no torch):
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_cli.py -q
  ```
  Expected: FAIL — `ModuleNotFoundError: No module named 'nn.orchestration.cli'`.
  If `nn.orchestration` itself is missing, create empty
  `main/nn/orchestration/__init__.py` + `main/tests/nn/orchestration/__init__.py`,
  re-run; the error must narrow to the missing `cli` module.

- [ ] **Step 2: GREEN — create `cli.py` with the parser scaffold + the `decide` subcommand.**
  Create `main/nn/orchestration/cli.py` with exactly this content:
  ```python
  import argparse
  import json

  from nn.orchestration.spec_store import materialize_spec
  from nn.orchestration.runner import run_version_training, VersionResult
  from nn.orchestration.lineage import decide, LineageDecision
  from nn.nn_model_spec import NNModelSpec
  from nn.device import nn_artefact_root


  def _build_parser() -> argparse.ArgumentParser:
      parser = argparse.ArgumentParser(prog="nn.orchestration.cli")
      sub = parser.add_subparsers(dest="cmd")

      p_mat = sub.add_parser("materialize-spec")
      p_mat.add_argument("--spec-yaml", required=True)
      p_mat.add_argument("--pair", required=True)

      p_run = sub.add_parser("run-version")
      p_run.add_argument("--spec-path", required=True)
      p_run.add_argument("--study", required=True)
      p_run.add_argument("--pair", required=True)
      p_run.add_argument("--timeout", type=float, required=True)

      p_dec = sub.add_parser("decide")
      p_dec.add_argument("--best", required=True)            # "none" or a float
      p_dec.add_argument("--candidate", type=float, required=True)
      p_dec.add_argument("--margin", type=float, required=True)
      p_dec.add_argument("--strike", type=int, required=True)
      p_dec.add_argument("--k", type=int, required=True)
      p_dec.add_argument("--version-n", type=int, required=True)
      p_dec.add_argument("--max-versions", type=int, required=True)
      p_dec.add_argument("--elapsed", type=float, required=True)
      p_dec.add_argument("--budget", type=float, required=True)

      return parser


  def main(argv: list[str] | None = None) -> int:
      parser = _build_parser()
      args = parser.parse_args(argv)

      if args.cmd == "decide":
          best = None if args.best == "none" else float(args.best)
          d = decide(
              best_score=best,
              candidate_score=args.candidate,
              margin=args.margin,
              strike_count=args.strike,
              K=args.k,
              version_n=args.version_n,
              max_versions=args.max_versions,
              elapsed_s=args.elapsed,
              budget_s=args.budget,
          )
          print(json.dumps({
              "action": d.action,
              "new_best": d.new_best,
              "strike_count": d.strike_count,
              "stop": d.stop,
              "reason": d.reason,
          }))
          return 0

      parser.print_usage()
      return 2


  if __name__ == "__main__":
      raise SystemExit(main())
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_cli.py -q
  ```
  Expected: PASS — `1 passed`. (`cli.decide` is monkeypatched, so the real
  `lineage.decide` is not exercised here; the test only proves arg parsing,
  `best="none"` handling via the float branch, the kwargs, and the printed JSON.)

- [ ] **Step 3: RED — `decide --best none` passes `best_score=None` (first-version promote).**
  Append to `main/tests/nn/orchestration/test_cli.py`:
  ```python
  def test_decide_subcommand_best_none_sentinel(capsys, monkeypatch):
      captured = {}

      class FakeDecision:
          action = "promote"; new_best = True; strike_count = 0
          stop = False; reason = "promote: first version"

      monkeypatch.setattr(cli, "decide",
                          lambda **kw: captured.update(kw) or FakeDecision())

      rc = main([
          "decide",
          "--best", "none", "--candidate", "0.33", "--margin", "0.01",
          "--strike", "0", "--k", "2", "--version-n", "1",
          "--max-versions", "6", "--elapsed", "0.0", "--budget", "28800.0",
      ])

      assert rc == 0
      assert captured["best_score"] is None
      out = json.loads(capsys.readouterr().out)
      assert out["action"] == "promote"
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_cli.py -q
  ```
  Expected: PASS — `2 passed`. (The Step 2 implementation already maps the literal
  `"none"` to `best_score=None`; this test pins that branch. If it FAILS with
  `ValueError: could not convert string to float: 'none'`, the `--best` sentinel
  handling was dropped.)

- [ ] **Step 4: RED — `run-version` subcommand launches and prints `{study, holdout_score}`.**
  Append to `main/tests/nn/orchestration/test_cli.py`:
  ```python
  def test_run_version_subcommand_calls_runner_and_prints_json(capsys, monkeypatch):
      captured = {}

      class FakeResult:
          study = "link_attn_v1"
          holdout_score = 0.41
          best = {"all": {"holdout": {"holdout_score": 0.41}}}

      def fake_run(spec_path, study, *, pair, timeout_s):
          captured.update(dict(spec_path=spec_path, study=study,
                               pair=pair, timeout_s=timeout_s))
          return FakeResult()

      monkeypatch.setattr(cli, "run_version_training", fake_run)

      rc = main([
          "run-version",
          "--spec-path", "/trader_data_long/train/link_usdt/nn/specs/abc/spec.yaml",
          "--study", "link_attn_v1", "--pair", "link_usdt", "--timeout", "28800",
      ])

      assert rc == 0
      assert captured == dict(
          spec_path="/trader_data_long/train/link_usdt/nn/specs/abc/spec.yaml",
          study="link_attn_v1", pair="link_usdt", timeout_s=28800.0,
      )
      out = json.loads(capsys.readouterr().out)
      assert out == {"study": "link_attn_v1", "holdout_score": 0.41}
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_cli.py -q
  ```
  Expected: FAIL — the `run-version` branch is not handled yet, so `main` falls
  through to `print_usage()` and `return 2` (assertion `rc == 0` fails; stdout is
  usage text, not JSON).

- [ ] **Step 5: GREEN — add the `run-version` branch.**
  In `main/nn/orchestration/cli.py`, add this branch BEFORE the `if args.cmd ==
  "decide":` branch (order does not matter functionally; group it with the others):
  ```python
      if args.cmd == "run-version":
          r = run_version_training(
              args.spec_path, args.study, pair=args.pair, timeout_s=args.timeout,
          )
          print(json.dumps({"study": r.study, "holdout_score": r.holdout_score}))
          return 0
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_cli.py -q
  ```
  Expected: PASS — `3 passed`.

- [ ] **Step 6: RED — `materialize-spec` loads the YAML, calls `materialize_spec`, prints the path.**
  Append to `main/tests/nn/orchestration/test_cli.py`:
  ```python
  def test_materialize_spec_subcommand_loads_and_prints_path(capsys, monkeypatch):
      calls = {}
      sentinel_spec = object()
      sentinel_root = object()

      monkeypatch.setattr(
          cli.NNModelSpec, "from_yaml",
          classmethod(lambda cls, path: calls.setdefault("from_yaml", path) or sentinel_spec),
      )
      monkeypatch.setattr(cli, "nn_artefact_root",
                          lambda pair: calls.setdefault("root_pair", pair) or sentinel_root)

      def fake_materialize(spec, artefact_root):
          calls["materialize"] = (spec, artefact_root)
          return "/trader_data_long/train/link_usdt/nn/specs/abc/spec.yaml"

      monkeypatch.setattr(cli, "materialize_spec", fake_materialize)

      rc = main(["materialize-spec",
                 "--spec-yaml", "/in/spec.yaml", "--pair", "link_usdt"])

      assert rc == 0
      assert calls["from_yaml"] == "/in/spec.yaml"
      assert calls["root_pair"] == "link_usdt"
      assert calls["materialize"] == (sentinel_spec, sentinel_root)
      assert capsys.readouterr().out.strip() == \
          "/trader_data_long/train/link_usdt/nn/specs/abc/spec.yaml"
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_cli.py -q
  ```
  Expected: FAIL — the `materialize-spec` branch is not handled; `main` returns 2
  and prints usage (assertions fail).

- [ ] **Step 7: GREEN — add the `materialize-spec` branch.**
  In `main/nn/orchestration/cli.py`, add this branch with the others:
  ```python
      if args.cmd == "materialize-spec":
          spec = NNModelSpec.from_yaml(args.spec_yaml)
          path = materialize_spec(spec, nn_artefact_root(args.pair))
          print(path)
          return 0
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_cli.py -q
  ```
  Expected: PASS — `4 passed`.

- [ ] **Step 8: RED — no/unknown command prints usage and returns 2.**
  Append to `main/tests/nn/orchestration/test_cli.py`:
  ```python
  def test_no_command_returns_usage_code():
      assert main([]) == 2
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_cli.py -q
  ```
  Expected: PASS — `5 passed`. (The Step 2 scaffold already returns 2 with
  `args.cmd is None`; this test pins that contract so a later refactor cannot
  silently make a no-arg invocation a success.)

- [ ] **Step 9: GREEN gate — full CLI suite + no orchestration regressions.**
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/ -q
  ```
  Expected: PASS — the new `test_cli.py` (5 passed) plus the existing Phase 17
  orchestration tests (spec_store / report / lineage / runner) all green; only a new
  module + test file were added.

- [ ] **Step 10: Commit (deliverable 1).**
  ```bash
  cd /home/om/projects/simple_trader/main
  git add nn/orchestration/cli.py tests/nn/orchestration/test_cli.py
  git commit -m "feat(nn): orchestration CLI wrapping spec/runner/lineage helpers"
  ```
  Expected: clean commit; `git status` shows nothing pending under
  `nn/orchestration/` or `tests/nn/orchestration/`. **Do not push without the
  user's explicit confirmation.**

---

### Deliverable 2 — `nn-train-orchestrator` SKILL.md (markdown)

- [ ] **Step 11: Author the skill.**
  Create `main/.agents/skills/nn-train-orchestrator/SKILL.md` with this content:
  ```markdown
  ---
  name: nn-train-orchestrator
  description: Use when running the Phase 17 NN training orchestration — walk the candidate archetypes one at a time, drive each archetype's autonomous version lineage to its stop, re-validate the winner on 4y, then STOP for a human gate before the next archetype. Re-invoke under ralph-loop or /loop for the multi-hour trainings.
  ---

  # NN Train Orchestrator (Tier 2 conductor)

  ## Overview

  You conduct the per-archetype training lineages for one pair (iterate on **2y
  link_usdt**, confirm on **4y**). You do NOT design architectures (that is
  `nn-investigate`, Tier 0) or tune numerics (that is the in-container Optuna
  search, Tier 1). Your job is the **walk**: for each candidate archetype, run its
  lineage to a decided stop, re-validate the winner on 4y, then **hand back to a
  human** before the next archetype.

  **You never compute path math, the Docker launch, or promote/revert arithmetic
  by hand.** Those are deterministic and live in the CLI — call it:

  - `python -m nn.orchestration.cli materialize-spec --spec-yaml <in> --pair <pair>`
    → prints the on-volume spec path.
  - `python -m nn.orchestration.cli run-version --spec-path <vol> --study <name> --pair <pair> --timeout 28800`
    → prints JSON `{study, holdout_score}`.
  - `python -m nn.orchestration.cli decide --best <f|none> --candidate <f> --margin 0.01 --strike <i> --k 2 --version-n <i> --max-versions 6 --elapsed <f> --budget 28800`
    → prints JSON of the `LineageDecision` (`action`, `new_best`, `strike_count`,
    `stop`, `reason`).

  ## Locked values (do not change)

  `trials_per_round 8` · `max_rounds 1` · `K=2` · `max_versions 6` ·
  `margin 0.01` · `budget 28800s` (8 h per archetype) · iterate **2y link_usdt** ·
  confirm **4y**.

  ## The walk (archetypes)

  Read the archetype list from the Tier-0a meta plan (`nn-investigate` output).
  Process **one archetype per run**:

  1. Run that archetype's lineage loop (below) to `decide.stop`.
  2. Re-validate the promoted best on **4y** (the final lineage step — see below).
  3. **STOP.** Emit a short summary and end the run for a **human gate**: the
     operator reviews the lineage + 4y result, then resumes you for the NEXT
     archetype. The gate is BETWEEN archetypes — never pause inside a lineage.

  ## The per-archetype lineage loop (autonomous)

  State lives in files, not in your memory — on every (re-)invocation, read the
  lineage's own artifacts to resume.

  1. **Investigate (Tier 0b)** — get/confirm this archetype's v1 spec via
     `nn-investigate`.
  2. **Materialize v1** — `cli materialize-spec` → on-volume spec path.
  3. **Run version** — `cli run-version --timeout 28800` → `{study, holdout_score}`.
  4. **Evolve (Tier 2)** — invoke `nn-evolve`: it writes the version `report.md`
     (under the external `{archetype}/v{n}/`, parseable by `parse_report`) and then
     calls `cli decide` (current best vs this candidate, margin 0.01, K 2,
     max_versions 6, elapsed vs budget 28800). Thread the returned `strike_count`
     into the next `decide`.
  5. **Branch on `decide.stop`:**
     - `stop == false` → take the next spec `nn-evolve` proposed, go to step 2 with
       `version_n += 1`.
     - `stop == true` → the 2y lineage is done. Go to the 4y confirm step.

  ## 4y confirm step (final step before the gate)

  Once the 2y lineage stops, take the **promoted best** spec and run it ONCE on
  **4y** (`--pair` for the 4y dataset, fresh `--study` suffix `_4y`). Record the 4y
  holdout in the winner's report. This re-validation that the 2y winner generalises
  to 4y is the LAST action of the archetype — then STOP for the human gate.

  ## Long trainings — ralph-loop / /loop

  A single `run-version` is a multi-hour `docker compose run`. Do NOT block one
  turn for hours. This skill is built to be **re-invoked between version steps**:

  - **ralph-loop** (`/ralph-loop "<this skill's task>" --completion-promise
    "ARCHETYPE_DONE"`): the Stop hook feeds the same prompt back; each iteration
    reads the lineage's files (last `report.md`, `tracking/{study}/best.json`) and
    advances one step. Emit the completion promise only after the 4y confirm step,
    so the loop stops at the human gate.
  - **/loop** (interval re-invoke) works the same way for unattended polling.

  The contract that makes this safe: **the prompt never changes between iterations
  and all state is in files** — you reconstruct "where am I" from the artifacts, not
  from conversation history.

  ## Stop conditions you must honour

  Stop the lineage exactly when `cli decide` says `stop == true` — that is the OR of
  `strike_count >= 2`, `version_n >= 6`, or `elapsed_s >= 28800`. Never override it.
  After stop + 4y confirm: STOP the run for the human gate.

  ## Done means

  - One archetype's lineage ran to a decided stop (`decide.stop`).
  - The promoted best was re-validated on 4y and recorded.
  - A v{n} `report.md` exists per version under `{archetype}/v{n}/`, each parseable
    by `parse_report`.
  - You ended the run for a human gate (did not auto-start the next archetype).
  ```
  No test to run for the markdown; the skill is exercised by the e2e smoke
  (deliverable 3) and by the contract checks in Tasks 09/10 (every emitted
  `report.md` parses via `parse_report`).

- [ ] **Step 12: Commit (deliverable 2).**
  ```bash
  cd /home/om/projects/simple_trader/main
  git add .agents/skills/nn-train-orchestrator/SKILL.md
  git commit -m "feat(nn): nn-train-orchestrator skill (archetype walk + gate)"
  ```
  Expected: clean commit. **Do not push without the user's explicit confirmation.**

---

### Deliverable 3 — RUNBOOK.md (external docs; operator flow)

- [ ] **Step 13: Write the runbook.**
  Create
  `external/docs/superpowers/plans/impl_2/phase-17-nn-training-orchestration/RUNBOOK.md`
  with this content (docs live in the EXTERNAL repo, never in `main/`):
  ```markdown
  # Phase 17 — NN Training Orchestration: Operator Runbook

  The full flow to drive one archetype's lineage with `docker compose` + the
  orchestration CLI. Iterate on **2y link_usdt**, confirm on **4y**. Locked values:
  `K=2`, `max_versions 6`, `margin 0.01`, `budget 28800s`, `trials_per_round 8`,
  `max_rounds 1`.

  ## 0. One-time setup
  ```bash
  cd /home/om/projects/simple_trader
  docker compose build nn-train                 # torch + optuna image
  # confirm the data volume is mounted and link_usdt data is present:
  docker compose run --rm nn-train ls /trader_data_long/train/link_usdt/nn
  ```

  ## 1. Investigate (Tier 0) — emit the v1 spec
  Use the `nn-investigate` skill to produce `v1.yaml` (a valid `NNModelSpec`).
  The agent writes it under the archetype's external dir.

  ## 2. Materialize the version spec onto the artefact volume
  ```bash
  docker compose run --rm nn-train \
    python -m nn.orchestration.cli materialize-spec \
      --spec-yaml /work/<archetype>/v1.yaml --pair link_usdt
  # → prints the on-volume path, e.g.
  #   /trader_data_long/train/link_usdt/nn/specs/<spec_hash>/spec.yaml
  ```

  ## 3. Run one version (multi-hour; drive under ralph-loop / /loop)
  ```bash
  docker compose run --rm nn-train \
    python -m nn.orchestration.cli run-version \
      --spec-path /trader_data_long/train/link_usdt/nn/specs/<spec_hash>/spec.yaml \
      --study <archetype>_v1 --pair link_usdt --timeout 28800
  # → prints {"study": "<archetype>_v1", "holdout_score": <f>}
  # result also on the volume: tracking/<archetype>_v1/best.json
  ```

  ## 4. Evolve — write the report + decide promote/revert/stop
  The `nn-evolve` skill writes `{archetype}/v1/report.md` and runs:
  ```bash
  docker compose run --rm nn-train \
    python -m nn.orchestration.cli decide \
      --best none --candidate <holdout_score> --margin 0.01 \
      --strike 0 --k 2 --version-n 1 --max-versions 6 \
      --elapsed <s> --budget 28800
  # → {"action": "...", "new_best": ..., "strike_count": ..., "stop": ..., "reason": "..."}
  ```
  If `stop == false`: take the next proposed spec → back to step 2 with
  `--version-n 2` (and `--best <running best score>`, `--strike <returned count>`).
  Repeat until `stop == true`.

  ## 5. Confirm the winner on 4y (final lineage step)
  Re-run the promoted best ONCE on the 4y dataset with a `_4y` study suffix:
  ```bash
  docker compose run --rm nn-train \
    python -m nn.orchestration.cli run-version \
      --spec-path <winner spec path> --study <archetype>_4y \
      --pair link_usdt --timeout 28800
  ```
  Record the 4y holdout in the winner's report.

  ## 6. Human gate
  Review the lineage (per-version reports + 4y result), then resume the
  `nn-train-orchestrator` skill for the NEXT archetype.

  ## Drive the loop unattended
  ```bash
  # ralph-loop: Stop hook re-feeds the prompt; state persists in files
  /ralph-loop "Run nn-train-orchestrator for archetype <name> on link_usdt" \
    --completion-promise "ARCHETYPE_DONE"
  # or interval re-invoke:
  /loop 30m run the nn-train-orchestrator skill for archetype <name>
  ```
  ```

- [ ] **Step 14: Commit (deliverable 3).**
  ```bash
  cd /home/om/projects/simple_trader/external
  git add docs/superpowers/plans/impl_2/phase-17-nn-training-orchestration/RUNBOOK.md
  git commit -m "docs(phase17): operator runbook for nn-train orchestration"
  ```
  Expected: clean commit in the EXTERNAL docs repo. **Do not push without the
  user's explicit confirmation.**

---

### Deliverable 4 — end-to-end Docker smoke (`@pytest.mark.docker_e2e`)

- [ ] **Step 15: RED — write the e2e smoke (skips when data absent).**
  Create `main/tests/nn/orchestration/test_lineage_e2e.py` with exactly this
  content:
  ```python
  import json
  import os
  from pathlib import Path

  import pytest

  from nn.nn_model_spec import NNModelSpec
  from nn.device import nn_artefact_root
  from nn.orchestration.spec_store import materialize_spec
  from nn.orchestration.runner import run_version_training
  from nn.orchestration.lineage import decide
  from nn.orchestration.report import parse_report


  pytestmark = pytest.mark.docker_e2e


  def _data_present() -> bool:
      root = os.environ.get("NN_DATA_ROOT")
      if not root:
          return False
      return os.path.isdir(os.path.join(root, "link_usdt")) or os.path.isdir(root)


  @pytest.mark.skipif(
      not _data_present(),
      reason="NN_DATA_ROOT / link_usdt data absent; e2e needs the populated volume",
  )
  def test_one_tiny_lineage_produces_artifacts(tmp_path):
      pair = "link_usdt"
      archetype = "e2e_smoke"

      # 1. tiny spec: NNModelSpec.default() shrunk to epochs=5
      spec = NNModelSpec.default()
      spec.epochs = 5
      in_yaml = tmp_path / "v1.yaml"
      spec.to_yaml(str(in_yaml))

      # 2. materialize onto the artefact volume
      spec_path = materialize_spec(spec, nn_artefact_root(pair))
      assert Path(spec_path).exists()

      # 3. run ONE version via the real nn-train container (multi-minute, tiny)
      study = f"{archetype}_v1"
      result = run_version_training(
          str(spec_path), study, pair=pair, timeout_s=3600,
      )
      assert result.study == study

      # tracking/{study}/best.json exists on the volume
      best_path = nn_artefact_root(pair) / "tracking" / study / "best.json"
      assert best_path.exists(), f"missing {best_path}"

      # 4. drive ONE evolve cycle: write a v1 report.md, then decide
      version_dir = tmp_path / archetype / "v1"
      version_dir.mkdir(parents=True)
      report_md = version_dir / "report.md"
      report_md.write_text(_render_v1_report(archetype, spec, result))
      assert report_md.exists()

      # v1 report parses via parse_report (contract with Task 06)
      meta = parse_report(report_md.read_text())
      assert meta.archetype == archetype
      assert meta.version == 1

      # decide: first version always promotes -> lineage produced >= 1 version
      d = decide(
          best_score=None, candidate_score=result.holdout_score, margin=0.01,
          strike_count=0, K=2, version_n=1, max_versions=6,
          elapsed_s=0.0, budget_s=28800.0,
      )
      assert d.action == "promote"          # >= 1 version in the lineage
      assert d.new_best is True

      # 5. if the loop continues, a v2 spec would be emitted next; assert the
      #    lineage is in a continuable state (not an immediate forced stop)
      assert d.stop is False


  def _render_v1_report(archetype: str, spec, result) -> str:
      # minimal frontmatter that parse_report (Task 06) accepts
      meta = {
          "archetype": archetype,
          "version": 1,
          "parent": None,
          "spec_hash": spec.spec_hash,
          "hypothesis": "baseline default architecture, epochs=5",
          "holdout_acc": float(result.holdout_score),
          "holdout_loss": 0.0,
          "per_class": {"up": 0.0, "neutral": 0.0, "down": 0.0},
          "decision": "pending",
          "strike": 0,
          "next_hypothesis": None,
      }
      lines = ["---"]
      for k, v in meta.items():
          lines.append(f"{k}: {json.dumps(v)}")
      lines.append("---")
      lines.append("")
      lines.append("# e2e smoke v1")
      return "\n".join(lines)
  ```
  Run WITHOUT the data volume (the common dev case):
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_lineage_e2e.py -q
  ```
  Expected: `1 skipped` (the skip guard fires; `NN_DATA_ROOT` is unset). No
  unregistered-marker warning — `docker_e2e` was registered in Task 08
  (`pytest.ini` / `pyproject.toml`). If you see `PytestUnknownMarkWarning`, add the
  marker line `docker_e2e: end-to-end test that launches the real nn-train Docker
  service` to the markers config.

- [ ] **Step 16: GREEN — run the smoke in Docker WITH the data volume (the real check).**
  Run the e2e inside the image, with the data volume mounted and `NN_DATA_ROOT`
  pointed at it so the skip guard passes:
  ```bash
  cd /home/om/projects/simple_trader
  docker compose run --rm \
    -e NN_DATA_ROOT=/trader_data_long/train \
    nn-train python -m pytest tests/nn/orchestration/test_lineage_e2e.py -q -m docker_e2e
  ```
  Expected: PASS — `1 passed`. The container materializes the tiny spec, runs ONE
  5-epoch version on `link_usdt`, writes `tracking/{study}/best.json`, the test
  writes + parses a v1 `report.md`, and `decide` promotes (≥1 version, continuable).
  If it SKIPS here, `NN_DATA_ROOT` did not resolve to a dir containing the data —
  check the volume mount and the env value. If `run_version_training` raises
  `RuntimeError("no best.json")`, the inner search wrote nothing — inspect the
  container logs (the spec or study env wiring, Task 08).

- [ ] **Step 17: GREEN gate — no regression in the orchestration suite (pure run).**
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/ -q
  ```
  Expected: PASS — CLI + spec_store/report/lineage/runner tests green; the
  `docker_e2e` smoke is collected and **skipped** (no data volume in the pure venv).

- [ ] **Step 18: Commit (deliverable 4).**
  ```bash
  cd /home/om/projects/simple_trader/main
  git add tests/nn/orchestration/test_lineage_e2e.py
  # include pytest.ini / pyproject.toml only if a marker line was added here
  git add pytest.ini 2>/dev/null || true
  git commit -m "test(nn): e2e docker smoke for one tiny orchestration lineage"
  ```
  Expected: clean commit; `git status` clean under `tests/nn/orchestration/`.
  **Do not push without the user's explicit confirmation.**

---

- [ ] **Step 19: Final phase gate — whole nn suite in Docker.**
  ```bash
  cd /home/om/projects/simple_trader
  docker compose run --rm nn-train python -m pytest tests/nn -q
  ```
  Expected: PASS — all Phase 17 orchestration tests green in the image; the
  `docker_e2e` smoke either passes (if the data volume is mounted) or is skipped.
  This closes Layer C: the CLI, the skill, the runbook, and the e2e smoke are in
  place and verified.
