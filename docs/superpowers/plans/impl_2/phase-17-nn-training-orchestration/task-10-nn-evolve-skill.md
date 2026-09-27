# Task 10: nn-evolve skill (Tier 2)

**Phase:** 17 — NN Training Orchestration
**Depends on:** Task 06 (report), Task 07 (decide), Task 05 (materialize_spec), Task 09 (investigate)
**Produces:** .agents/skills/nn-evolve/SKILL.md ; emits {archetype}/v{n}/report.md, next-version spec on volume

## Goal

Author the `nn-evolve` skill — the **Tier 2** evolution step of the improve-loop.
The orchestrator (Task 11) trains ONE version (Tier 1 / Optuna inside the `nn-train`
image, scoped to a study), then hands `nn-evolve` that version's `VersionResult` plus
the prior version's `report.md`. The skill is the agent-authored reasoning seam: it

1. **records the version report** — writes `{archetype}/v{n}/report.md` with a
   machine-readable frontmatter block (via `render_report`) followed by a prose body
   (hypothesis, result table incl. per-class + confusion, what went good, what went
   bad, what to improve);
2. **decides the lineage move** — calls `lineage.decide(...)` with the holdout score
   to get promote / revert and whether the lineage stops (strikes exhausted, version
   cap, or budget gone);
3. **if continuing, reasons ONE structural change** — it reads the report's
   per-class/confusion failure mode and picks a SINGLE structural edit that targets
   that failure, writes it as `next_hypothesis`, builds the next `NNModelSpec`, and
   materialises it to the volume (which preserves the prior version automatically:
   new spec → new `spec_hash` → new `specs/{hash}/` dir, old untouched).

The skill **NEVER samples architecture randomly — it reasons it (ADR-0001).** Width,
learning-rate, and dropout are Tier-1's job (Optuna, within a version) and are
explicitly OFF the structural menu. Tier 2 only ever changes the *shape*: layer
count, layer kind, history window, targets, indicator groups, grouping.

This is **Layer C** (the skill-set). It produces no Python module of its own; its
contract with Layer B is proven by a pytest **contract test** that drives a report
through `render_report` → `parse_report` → `decide` and asserts the documented
decision.

## Context

The orchestration loop (Task 11) per archetype: declare v1 (from `nn-investigate`,
Task 09) → train it (Tier 1) → `nn-evolve` → if continuing, train the next version →
`nn-evolve` → … until `decide(...).stop`. `nn-evolve` is the body of that loop.

**Inputs the skill is handed (by the orchestrator):**

- a `VersionResult` (Task 08): `study`, `holdout_score: float`, `best: dict` (the
  raw `best.json`; per-class accuracy + confusion come from the trial record's
  `metrics`).
- the prior version's `report.md` text (None for v1), parseable via `parse_report`
  → `ReportMeta` (its `holdout_acc` is the running best to compare against; its
  `strike` is the strike count to thread in; its `next_hypothesis` is the hypothesis
  this version was built to test).
- the current best score + strike count + version number + elapsed time threaded by
  the orchestrator.

**Helpers the skill calls (Layer B — verbatim signatures, do not redeclare):**

```python
from nn.orchestration.report import ReportMeta, parse_report, render_report
from nn.orchestration.lineage import decide, LineageDecision
from nn.orchestration.spec_store import materialize_spec
```

- `render_report(meta: ReportMeta, body: str) -> str` — frontmatter + `\n\n` + prose.
- `parse_report(md: str) -> ReportMeta` — reads the prior report's frontmatter.
- `decide(*, best_score, candidate_score, margin, strike_count, K, version_n,
  max_versions, elapsed_s, budget_s) -> LineageDecision(action, new_best,
  strike_count, stop, reason)`.
- `materialize_spec(spec: NNModelSpec, artefact_root: Path) -> Path` — writes
  `{artefact_root}/specs/{spec_hash}/spec.yaml`; idempotent; content-addressed.

**`ReportMeta` fields** (Task 06): `archetype`, `version:int`, `parent:str|None`,
`spec_hash`, `hypothesis`, `holdout_acc:float`, `holdout_loss:float`,
`per_class:dict{up,neutral,down}`, `decision:str("promote"|"revert"|"pending")`,
`strike:int`, `next_hypothesis:str|None`.

**Locked operating values (do NOT pass anything else):** `margin = 0.01`, `K = 2`,
`max_versions = 6`, `budget_s = 28800` (8 h). These come from the phase decisions and
ADR-0002; the skill passes them as named arguments to every `decide(...)` call.

**Paths:**

- Version report (external docs repo, NOT the code repo):
  `external/docs/superpowers/specs/supporting-systems/nn-training-orchestration/{archetype}/v{n}/report.md`.
- Next version's spec → the artefact volume via `materialize_spec(next_spec,
  nn_artefact_root(pair))`, landing at `specs/{next_spec.spec_hash}/spec.yaml`
  (read-write root `/trader_data_long`). The trainer reads it next round via
  `NN_SPEC_PATH` (Task 01).

**Structural change menu (the skill REASONS over this — examples, not a sampler):**

| Structural edit | What it changes | When to reach for it |
|---|---|---|
| add / remove a layer | layer **count** → new version | underfitting (all classes weak) / overfitting (train ≫ holdout) |
| swap a layer **kind** (e.g. `dense`→`lstm`/`gru`/`conv1d`) | layer kind | no temporal structure being captured; flat per-class |
| widen `history_points` | input window length | model can't see far enough back to separate up/down |
| change / add a `target` (TargetSpec) | output head(s) | the head's labelling is the bottleneck (e.g. neutral band too wide) |
| add / drop an indicator group | input features | a class lacks the signal that distinguishes it |
| change `grouping` | row partitioning (e.g. by vol regime) | one regime dominates and drowns minority-class recall |

**NOT structural (Tier-1 / Optuna only — the skill must NOT pick these as a
`next_hypothesis`):** layer **width** (`units`), `learning_rate`, `dropout`. If the
only thing wrong is "needs a wider layer / lower lr", that is already inside the
version's own Optuna search — there is nothing for Tier 2 to do but re-train; Tier 2
exists to change the SHAPE.

**The reasoning must tie the change to the failure seen in the report's
per-class/confusion.** Example: an "always-neutral" model (`per_class` shows high
neutral, near-zero up/down recall; confusion rows for up/down collapse into the
neutral column) is gaming the accuracy metric (ADR-0002's known risk). The correct
structural move targets **recall on up/down** — e.g. narrow the direction target's
neutral band (`label_m`/`label_x` on the `TargetSpec`), or add an indicator group
that separates direction, or switch to `by_indicator` grouping — and must NOT be
"widen the dense layer," which is (a) Optuna's job and (b) does not address recall.

**"Preserve previous" is automatic.** A new spec → new `spec_hash` → a fresh
`specs/{hash}/` and `checkpoints/{hash}/` directory; the prior version's spec and
checkpoints are never touched. The skill does not copy, delete, or version-bump any
prior artefact — it just materialises the new spec.

This task creates the skill directory and `SKILL.md`, plus ONE pytest **contract
test** (Layer B helpers, pure-python — runs under `main/.venv`) that proves a report
authored to the skill's contract round-trips through the codec and yields the
documented `decide(...)` verdict.

## Files

### Create

- `/home/om/projects/simple_trader/.agents/skills/nn-evolve/SKILL.md` — the skill:
  YAML frontmatter (`name`, `description`) + the evolution procedure (see Interface).
- `/home/om/projects/simple_trader/main/tests/nn/orchestration/test_evolve_contract.py`
  — the contract test (see the contract-test step). Pure-python: imports only the
  Layer B helpers; no torch.

### May need (only if absent)

- `main/tests/nn/orchestration/__init__.py` — created by earlier Phase 17 tasks
  (05–08). Create empty only if missing.

### Modify

- None. (The skill is markdown; it calls existing Layer B helpers and emits files at
  runtime. No existing module changes.)

## Interface

### SKILL.md frontmatter

```markdown
---
name: nn-evolve
description: >-
  Use after a single NN version has been trained (Tier 1 / Optuna) to evolve the
  lineage: record the version's report.md (frontmatter + prose), call lineage.decide
  to promote/revert/strike/stop, and — if continuing — reason ONE structural change
  (never random — ADR-0001) and emit the next version's spec.yaml to the volume.
---
```

### SKILL.md body — the procedure (this is what the skill instructs the agent to do)

```markdown
# nn-evolve — evolve one NN version (Tier 2)

You are handed: a trained version's `VersionResult` (study, holdout_score, best),
the prior version's `report.md` text (or None for v1), and the lineage counters
(version_n, current best_score, strike_count, elapsed_s). Locked values:
margin=0.01, K=2, max_versions=6, budget_s=28800.

## 1. Read the inputs
- If a prior report exists: `prior = parse_report(prior_md)`. Its `holdout_acc` is
  the running best; its `strike` is the strike count; its `next_hypothesis` is the
  hypothesis THIS version was built to test (becomes this report's `hypothesis`).
- For v1: no prior; `best_score=None`, `strike_count=0`, parent=None, and the
  hypothesis is the archetype declaration from `nn-investigate` (Task 09).
- From `result.best`, pull this version's holdout accuracy, holdout loss, the
  per-class accuracy {up, neutral, down}, and the confusion matrix (3×3 over
  up/neutral/down). These live in each trial record's `metrics`.

## 2. Write the version report
- Decide first (step 3), then render — so the frontmatter `decision`/`strike`/
  `next_hypothesis` reflect the verdict. (You may draft prose before deciding, but
  the rendered frontmatter is post-decision.)
- Build `meta = ReportMeta(archetype=..., version=version_n, parent=prior_label,
  spec_hash=this_spec_hash, hypothesis=this_hypothesis,
  holdout_acc=..., holdout_loss=..., per_class={...}, decision=..., strike=...,
  next_hypothesis=...)`.
- `body` = the PROSE TEMPLATE below, filled in.
- `text = render_report(meta, body)`; write to
  `external/docs/superpowers/specs/supporting-systems/nn-training-orchestration/{archetype}/v{version_n}/report.md`.
- The report MUST parse back: `parse_report(text)` returns an equal `ReportMeta`.

## 3. Decide the lineage move
Call exactly:
    d = decide(
        best_score=prior.holdout_acc if prior else None,
        candidate_score=result.holdout_score,
        margin=0.01, strike_count=(prior.strike if prior else 0),
        K=2, version_n=version_n, max_versions=6,
        elapsed_s=elapsed_s, budget_s=28800,
    )
Branch on `d`:
- `d.action == "promote"`: this version is the new incumbent. Set the report's
  `decision="promote"`, `strike=0` (decide reset it). The next version's parent is
  THIS version; the next best_score is THIS holdout_acc.
- `d.action == "revert"`: keep the prior incumbent. Set `decision="revert"`,
  `strike=d.strike_count` (incremented). The next version's parent is still the
  incumbent (the prior promoted version), and best_score stays the incumbent's.
Record `d.reason` verbatim in the report's "what bad / what to improve" prose.

## 4. Stop or continue
- If `d.stop` is True: FINALIZE. Set `next_hypothesis=None`. Write the report.
  Return to the orchestrator: lineage done, winner = the current incumbent, with
  `d.reason` as the stop cause (strikes / max_versions / budget). Do NOT build a
  new spec.
- If `d.stop` is False: CONTINUE. Reason ONE structural change (step 5), set it as
  `next_hypothesis`, build + materialise the next spec (step 6), then return it to
  the orchestrator to train as the next version.

## 5. Reason ONE structural change (NOT random — ADR-0001)
Read the failure in the per-class/confusion table you recorded:
- Diagnose the dominant failure mode (e.g. always-neutral; up/down confused with
  each other; underfit-all; overfit gap; one regime drowning a minority class).
- Pick a SINGLE edit from the structural menu (add/remove layer, swap kind, widen
  history_points, change/add target, add/drop indicator group, change grouping)
  that DIRECTLY targets that failure. State the causal link in one sentence:
  "<failure> → <structural edit> because <why it addresses recall/separation/etc>".
- FORBIDDEN as a structural change: changing layer width/units, learning_rate, or
  dropout — those are Tier-1 (Optuna) and happen inside the version, not here.
- Exactly ONE structural edit per version, so the next report can attribute the
  holdout delta to that one change (clean lineage hill-climb).

## 6. Build + materialise the next spec
- Start from the INCUMBENT spec (the promoted version's spec, or v1's for a revert),
  apply the one structural edit with `dataclasses.replace` / list edits on `layers`,
  `targets`, `history_points`, `indicators`, or `grouping`.
- `path = materialize_spec(next_spec, nn_artefact_root(pair))`. The new spec_hash
  gives it its own `specs/{hash}/` dir; the prior version is untouched (preserved
  automatically). Hand `path` (the next NN_SPEC_PATH) and the next study label
  (`{archetype}_v{version_n+1}`) back to the orchestrator.

## Invariants
- Any emitted spec MUST load via `NNModelSpec.from_yaml`.
- Any emitted report MUST parse via `parse_report`.
- decide(...) is ALWAYS called with the locked values above — never override them.
- Exactly ONE structural change per continuing version. Never sample architecture.
```

### Report.md prose body template (verbatim — the skill fills the `{...}` slots)

```markdown
## v{version_n} — {short title of this version's change}

**Hypothesis.** {what structural change this version tested, and the failure in the
prior version it was meant to fix.}

**Result.**

| metric | value | vs incumbent |
|---|---|---|
| holdout accuracy | {holdout_acc:.4f} | {delta vs best, e.g. +0.0261} |
| holdout loss | {holdout_loss:.4f} | {delta} |
| up recall | {per_class.up:.2f} |  |
| neutral recall | {per_class.neutral:.2f} |  |
| down recall | {per_class.down:.2f} |  |

Confusion (rows = actual, cols = predicted):

|        | pred up | pred neutral | pred down |
|--------|---------|--------------|-----------|
| up     | {c_uu}  | {c_un}       | {c_ud}    |
| neutral| {c_nu}  | {c_nn}       | {c_nd}    |
| down   | {c_du}  | {c_dn}       | {c_dd}    |

**What went good.** {what improved — e.g. the change lifted the targeted class's
recall; loss fell; the lineage promoted.}

**What went bad.** {what regressed or stayed broken — e.g. still gaming neutral;
up/down still confused; overfit gap widened. Quote decide(...).reason here.}

**What to improve.** {the diagnosed dominant failure mode that the NEXT structural
change must target — names the class/confusion cell, not "make it bigger".}

**Decision.** {promote | revert} — {decide(...).reason}. {if continuing:}
Next hypothesis: {next_hypothesis} (one structural change). {if stopped:}
Lineage stops: {stop cause}; winner = {incumbent label}.
```

### Contract the test pins

A report authored to this contract round-trips and yields the documented verdict:

```python
meta = ReportMeta(..., holdout_acc=<below-margin candidate>, ...)
text = render_report(meta, body)
back = parse_report(text)                      # round-trips
d = decide(best_score=<incumbent>, candidate_score=back.holdout_acc,
           margin=0.01, strike_count=1, K=2, version_n=3, max_versions=6,
           elapsed_s=1000.0, budget_s=28800)
assert d.action == "revert" and d.strike_count == 2 and d.stop is True
```

## TDD Steps

- [ ] **Step 0: Branch for the task.**
  ```bash
  cd /home/om/projects/simple_trader/main
  git checkout experimental_imp_2
  git pull --ff-only
  git checkout -b feat/nn-evolve-skill
  ```
  Expected: `Switched to a new branch 'feat/nn-evolve-skill'`.

- [ ] **Step 1: Write the skill.**
  Create the skill directory and `SKILL.md`:
  ```bash
  mkdir -p /home/om/projects/simple_trader/.agents/skills/nn-evolve
  ```
  Write `/home/om/projects/simple_trader/.agents/skills/nn-evolve/SKILL.md` with the
  frontmatter (`name: nn-evolve`, the `description` from the Interface) and the full
  procedure body from the Interface — including the structural-change menu, the "NOT
  structural" exclusion (width/lr/dropout = Optuna), the report.md PROSE TEMPLATE
  verbatim, and the Invariants block. Keep the locked values (margin 0.01, K 2,
  max_versions 6, budget 28800) inline in the `decide(...)` call so the procedure is
  self-contained.
  Sanity-check the frontmatter parses:
  ```bash
  cd /home/om/projects/simple_trader && .venv/bin/python - <<'PY'
  import yaml, pathlib
  p = pathlib.Path(".agents/skills/nn-evolve/SKILL.md")
  txt = p.read_text()
  assert txt.startswith("---\n")
  fm = yaml.safe_load(txt.split("---", 2)[1])
  assert fm["name"] == "nn-evolve" and "description" in fm
  print("frontmatter ok:", fm["name"])
  PY
  ```
  Expected: `frontmatter ok: nn-evolve`.

- [ ] **Step 2: RED — contract test (skill output integrates with the helpers).**
  Ensure the test package marker exists, then create the contract test:
  ```bash
  cd /home/om/projects/simple_trader/main
  [ -f tests/nn/orchestration/__init__.py ] || : > tests/nn/orchestration/__init__.py
  ```
  Create `main/tests/nn/orchestration/test_evolve_contract.py` with exactly this
  content:
  ```python
  """Contract: an nn-evolve report.md round-trips through the Layer B codec and the
  decision threaded through lineage.decide matches the documented verdict.

  This pins the nn-evolve SKILL's promise: it renders a ReportMeta via render_report,
  it parses back via parse_report, and feeding the parsed holdout_acc into decide
  yields the recorded decision. A below-margin second strike must revert + strike +
  stop the lineage.
  """
  from dataclasses import asdict

  from nn.orchestration.report import ReportMeta, parse_report, render_report
  from nn.orchestration.lineage import decide


  PROSE = """## v3 — second strike, below margin

  **Hypothesis.** Swap the trailing dense block for a gru to capture temporal
  structure the dense-only v2 missed (up/down were confused with each other).

  **Result.** holdout accuracy 0.4040 (+0.0040 vs incumbent 0.4000) — below the
  0.01 margin; up/down recall barely moved.

  **What went bad.** decide: revert: +0.0040 < margin (strike 2/2).

  **What to improve.** up/down still collapse into neutral; the NEXT change must
  target up/down recall, not layer width.

  **Decision.** revert — second consecutive strike; lineage stops.
  """


  def _meta(**over):
      base = dict(
          archetype="cnn_lstm",
          version=3,
          parent="v2",
          spec_hash="abc123def456",
          hypothesis="swap trailing dense for gru to capture temporal structure",
          holdout_acc=0.4040,          # incumbent 0.40 + 0.004 < margin 0.01
          holdout_loss=0.9300,
          per_class={"up": 0.31, "neutral": 0.78, "down": 0.29},
          decision="revert",
          strike=2,
          next_hypothesis=None,        # lineage stops, so no next hypothesis
      )
      base.update(over)
      return ReportMeta(**base)


  def test_report_roundtrips_through_codec():
      meta = _meta()
      text = render_report(meta, PROSE)

      assert text.startswith("---\n")
      assert text.endswith(PROSE)

      back = parse_report(text)
      assert asdict(back) == asdict(meta)
      assert back == meta


  def test_below_margin_version_reverts_strikes_and_stops():
      # The skill records the candidate's holdout in the report; the orchestrator
      # threads it through decide with the locked values + the prior strike (1).
      meta = _meta()
      back = parse_report(render_report(meta, PROSE))

      d = decide(
          best_score=0.4000,                 # the incumbent (prior promoted version)
          candidate_score=back.holdout_acc,  # 0.4040 -> +0.0040 < margin 0.01
          margin=0.01,
          strike_count=1,                    # one strike already on the board
          K=2,
          version_n=3,
          max_versions=6,
          elapsed_s=1000.0,
          budget_s=28800,
      )

      assert d.action == "revert"
      assert d.new_best is False
      assert d.strike_count == 2            # 1 -> 2 == K
      assert d.stop is True                 # second consecutive strike stops
      assert "strike" in d.reason and "2/2" in d.reason

      # the recorded report decision matches the verdict the skill must write
      assert back.decision == d.action      # "revert"
      assert back.strike == d.strike_count  # 2
      assert back.next_hypothesis is None   # stopped lineage carries no next step
  ```
  Run (pure-python, no torch):
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_evolve_contract.py -q
  ```
  Expected: RED first if Tasks 06/07 are not yet merged into this branch — the
  imports fail with `ModuleNotFoundError: No module named 'nn.orchestration.report'`
  (or `...lineage`). Rebase onto / merge the branches that delivered Task 06
  (`report.py`) and Task 07 (`lineage.py`) so the helpers exist, then re-run.

- [ ] **Step 3: GREEN — confirm the contract passes against the real helpers.**
  With `report.py` (Task 06) and `lineage.py` (Task 07) present, the test exercises
  only existing code — there is no new module to write; the skill IS the artefact.
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_evolve_contract.py -q
  ```
  Expected: PASS — `2 passed`. The round-trip is exact (`render_report` dumps every
  field, `parse_report` reads them back), and `decide(best=0.40, cand=0.4040, …,
  strike_count=1)` yields `revert`, `strike_count=2`, `stop=True`, reason
  `"stop: 2/2 strikes"` — exactly the verdict the skill records. If the round-trip
  FAILS, the bug is in Task 06's codec, NOT here; if the decision FAILS, the bug is
  in Task 07's `decide`, NOT here — do not weaken the assertions to match a broken
  helper.

- [ ] **Step 4: GREEN gate — full orchestration suite stays green.**
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/ -q
  ```
  Expected: PASS — the Phase 17 orchestration tests (spec_store, report, lineage,
  runner) plus this new contract test all pass; this task only adds a skill (markdown)
  and one pure-python test module.

- [ ] **Step 5: GREEN gate — no regression in the nn suite (image).**
  The contract test is pure-python, but importing `nn.orchestration` pulls in the
  `nn` package; confirm it also passes in the GPU image (no `.venv`):
  ```bash
  cd /home/om/projects/simple_trader && docker compose run --rm nn-train \
    python -m pytest tests/nn/orchestration/test_evolve_contract.py -q
  ```
  Expected: PASS — `2 passed`.

- [ ] **Step 6: Commit.**
  The skill lives in the CODE repo (`.agents/skills/`); the test lives in `main/`.
  The report.md files the skill emits at runtime go to the EXTERNAL docs repo — do
  NOT commit any generated `report.md` or `spec.yaml` here.
  ```bash
  cd /home/om/projects/simple_trader
  git add .agents/skills/nn-evolve/SKILL.md \
          main/tests/nn/orchestration/test_evolve_contract.py
  # include the test __init__.py only if Step 2 created it:
  git add main/tests/nn/orchestration/__init__.py 2>/dev/null || true
  git commit -m "feat(skill): nn-evolve Tier-2"
  ```
  Expected: clean commit; `git status` shows nothing pending under
  `.agents/skills/nn-evolve/` or `main/tests/nn/orchestration/`.
