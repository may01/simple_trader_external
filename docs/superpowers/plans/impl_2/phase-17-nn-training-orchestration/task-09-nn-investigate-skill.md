# Task 09: nn-investigate skill (Tier 0a + 0b)

**Phase:** 17 — NN Training Orchestration
**Depends on:** Task 04 (to_yaml), Task 05 (materialize_spec)
**Produces:** .agents/skills/nn-investigate/SKILL.md ; emits meta-investigation.md, {archetype}/description.md, v1 spec materialized on volume

## Goal

Author the `nn-investigate` skill: the Tier-0 reasoning entry point of the
orchestration loop. It runs in two stages.

- **Tier 0a (meta-investigation).** Read the project's allowed vocabulary
  (indicators, timeframes, targets, buildable layer kinds) from existing config,
  then propose a ranked **archetype list** — each archetype is a distinct NN
  design hypothesis (e.g. `dense_snapshot`, `cnn_lstm`, `gru_multi_tf`) with a
  one-line thesis and a **buildable-now flag**. Write this to
  `meta-investigation.md`.
- **Tier 0b (per-archetype deep investigation).** For one chosen archetype,
  reason which indicators / targets / layers it should use and **WHY each layer
  represents a real-data dependency**, write a `description.md`, build a v1
  `NNModelSpec` from that reasoning, and materialize the spec to the artefact
  volume so the trainer can read it via `NN_SPEC_PATH`.

This is the skill that turns "what should we try?" into a concrete, buildable,
trainable v1 spec — using exactly the same allowed vocabulary the in-loop
`NNStrategist` already uses, and refusing to declare a layer kind the engine
cannot build yet.

## Context

`nn-investigate` is the first skill in **Layer C** (Task Index T09; see phase
[README](./README.md)). Skills are markdown procedures the agent follows; they
contain no executable logic. The contract the README fixes for this skill
(README "Layer C — skills"):

> any emitted `spec.yaml` MUST load via `NNModelSpec.from_yaml`.

That contract is what this task pins with a pytest **contract test** (this task
is not pure-TDD-code, but the documented output must be proven to validate).

**Allowed vocabulary — the skill reads these as its only allowed sets** (verbatim
from the spec; the same vocab `NNStrategist` uses):

- **Indicators** = field names in `main/configs/indicators_config.yaml` (140+
  fields, bare names like `rsi_14`, `logret`, `macd_12_26_9_slope`). The skill
  may select feature columns ONLY from these names.
- **Timeframes** = `main/configs/candles_config.yaml` `candles: [1,5,15,60,240,1440]`.
  A multi-timeframe archetype may use only these candle resolutions.
- **Targets** = profit-label specs in `indicators_config.yaml` `labels:` **plus**
  the `NNModelSpec` `TargetSpec` kinds (`direction` / `label` / `regression`).
  A target the skill declares must name a `kind` from this set.

**Buildable layer kinds today** = `dense`, `lstm`, `gru`, `conv1d` (and mixed
stacks of these). `_SpecNet` already builds these ([nn_model.py:164](../../../../../main/nn/nn_model.py),
DECISIONS-LOG.md "Things already wired"). **New kinds (e.g. `attention`)
require the engine extension recipe** in [DECISIONS-LOG.md](./DECISIONS-LOG.md)
(added on demand via TDD) **BEFORE an archetype may declare them** — the skill
flags such archetypes as not-buildable-now and links the recipe.

**Output layout** (docs external, spec on the volume — Global Constraints):

- `meta-investigation.md` →
  `external/docs/superpowers/specs/supporting-systems/nn-training-orchestration/meta-investigation.md`
- per-archetype `description.md` →
  `.../nn-training-orchestration/{archetype}/description.md`
- the v1 spec → materialized to the **artefact VOLUME**, not the code repo, via
  `materialize_spec(spec, nn_artefact_root(pair))` (Task 05) →
  `specs/{spec_hash}/spec.yaml`. Never write the spec into `main/`.

**Locked starting values** the v1 spec MUST set (Global Constraints / [starting-values.md](../../specs/supporting-systems/nn-training-orchestration/starting-values.md)):
batch_size **128** (**64** for recurrent archetypes), epochs **50**, patience
**8**, learning_rate seed `1e-3`, dropout `0.2`. Iterate on **2y `link_usdt`**;
re-validate winners on 4y. The 4 GB GPU is the VRAM ceiling — every
`description.md` carries a VRAM note, and recurrent/attention widths stay small.

**Skill dir.** Main-repo path
`/home/om/projects/simple_trader/.agents/skills/nn-investigate/`, symlinked from
`.claude/skills/` (the runtime reads `.claude/skills/`; the canonical copy lives
in `.agents/skills/` and is the only path committed). Per
**superpowers:writing-skills**: `SKILL.md` frontmatter has exactly two required
fields — `name:` (kebab-case) and `description:` (one line, third person, "Use
when…", triggers only, NO workflow summary). The body is the procedure.

This task delivers the SKILL.md + a contract test + a sample fixture. It does NOT
run the skill (no training launched here) — Task 11's runbook does that
end-to-end.

## Files

### Create

- `main/.agents/skills/nn-investigate/SKILL.md` — the skill procedure (Step 1).
- `main/tests/nn/orchestration/fixtures/sample_v1_spec.yaml` — a representative
  v1 `spec.yaml` of the kind Tier-0b emits (Step 2).
- `main/tests/nn/orchestration/test_investigate_contract.py` — the contract test
  (Step 3) proving the fixture loads via `NNModelSpec.from_yaml` and is
  well-formed.

> `main/tests/nn/orchestration/__init__.py` already exists (Task 05 created the
> test package). `main/nn/orchestration/` (the import target for `from_yaml`)
> also exists from Task 05. This task adds only the `fixtures/` dir + two files;
> `fixtures/` needs no `__init__.py` (it holds data, not importable modules).

### Reference (read-only, do not modify)

- `main/configs/indicators_config.yaml` — indicator field names + `labels:`.
- `main/configs/candles_config.yaml` — `candles:` timeframes.
- `main/nn/nn_model_spec.py` — `NNModelSpec`, `LayerSpec`, `TargetSpec`,
  `from_yaml`, `default`.
- `main/nn/orchestration/spec_store.py` — `materialize_spec` (Task 05).
- [DECISIONS-LOG.md](./DECISIONS-LOG.md) — engine extension recipe for new kinds.

## Interface

This is a **skill** — its interface is an input/output contract the agent
follows, not a python signature.

**Inputs (what the skill is invoked with):**

- `pair` — the trading pair to investigate (e.g. `link_usdt`); selects the
  artefact root via `nn_artefact_root(pair)`.
- optional `archetype` — when present, run Tier 0b for that one archetype; when
  absent, run Tier 0a (produce / refresh the archetype list).

**Reads (allowed vocabulary, read-only):**

- `main/configs/indicators_config.yaml` (indicator names + `labels:`)
- `main/configs/candles_config.yaml` (`candles:` timeframes)
- buildable layer kinds: `dense`, `lstm`, `gru`, `conv1d` — plus the
  DECISIONS-LOG recipe gate for any other kind.

**Outputs (side effects):**

- **Tier 0a →** writes
  `external/docs/.../nn-training-orchestration/meta-investigation.md` — a ranked
  archetype list, each row: `archetype` name, one-line thesis, declared layer
  kinds, **buildable-now: yes/no** (no ⇒ links the engine extension recipe).
- **Tier 0b →** writes
  `external/docs/.../nn-training-orchestration/{archetype}/description.md`
  (template below), constructs an in-memory `NNModelSpec`, and calls
  `materialize_spec(spec, nn_artefact_root(pair))` → returns the volume path
  `…/specs/{spec_hash}/spec.yaml`.

**Output contract (pinned by the contract test):** any emitted `spec.yaml` loads
via `NNModelSpec.from_yaml` without error; its `layers` are non-empty and each
`LayerSpec.kind` is in `{dense, lstm, gru, conv1d}`; its `targets` are non-empty
and each `TargetSpec.kind` is in `{direction, label, regression}`; the locked
starting values are set.

### The archetype `description.md` template (use verbatim)

Tier 0b MUST produce a `description.md` with exactly these sections, in this
order:

```markdown
# Archetype: {archetype}

## Design thesis
One paragraph: the single real-data hypothesis this architecture tests
(e.g. "local candlestick shapes over the last N bars predict the next-bar
direction better than a flat snapshot"). What would make it win; what would
make it lose.

## Indicators (features) — rationale
For EACH selected indicator (each name MUST exist in indicators_config.yaml):
- `{indicator_name}` — what real-data signal it carries and why this archetype
  needs it (not "it's commonly used" — the concrete dependency).
Timeframes used (subset of [1,5,15,60,240,1440]) and why these resolutions.

## Layers — real-data dependency rationale
For EACH layer (in stack order), state the real-data dependency it captures:
- `conv1d` → local candle/pattern structure over a short window (shape, not value).
- `lstm` / `gru` → temporal dependency across the bar history (order matters).
- `dense` → snapshot feature interaction at a single instant (cross-feature, no time).
Every layer must map to a stated dependency; a layer with no dependency rationale
is removed. If any kind is NOT in {dense,lstm,gru,conv1d}, this archetype is
not-buildable-now — STOP and link the engine extension recipe in DECISIONS-LOG.md.

## Target — rationale
The TargetSpec kind ({direction|label|regression}) and, for a label target, which
labels_config entry; why this target matches the thesis (horizon, class balance).

## Initial hyperparameters — and why
batch_size, epochs, patience, learning_rate, dropout, units per layer — each with
one clause of justification. Use the locked starting values (batch_size 128, or 64
for recurrent archetypes; epochs 50; patience 8; lr 1e-3; dropout 0.2). State the
Optuna-tuned dims (units/lr/dropout) vs the fixed ones (kinds/count — ADR-0001).

## VRAM note (4 GB GPU)
Estimated footprint at the chosen width/sequence length; why it fits the 4 GB
ceiling; the fallback (OOM→CPU retry is the safety net). Recurrent/attention
widths kept small.
```

## Steps

- [ ] **Step 0: Branch for the task.**
  ```bash
  cd /home/om/projects/simple_trader/main
  git checkout experimental_imp_2
  git pull --ff-only
  git checkout -b feat/nn-investigate-skill
  ```
  Expected: `Switched to a new branch 'feat/nn-investigate-skill'`.

- [ ] **Step 1: Write `SKILL.md` (the Tier 0a + 0b procedure).**
  Create the skill dir and write the file:
  ```bash
  cd /home/om/projects/simple_trader/main
  mkdir -p .agents/skills/nn-investigate
  ```
  Write `main/.agents/skills/nn-investigate/SKILL.md` with exactly this content:
  ````markdown
  ---
  name: nn-investigate
  description: Use when starting a new NN archetype investigation for a trading pair, or when asked to propose candidate NN designs or emit a v1 model spec for stock-price prediction — Tier 0 of the NN training orchestration loop.
  ---

  # nn-investigate (Tier 0a + 0b)

  ## Overview

  Tier-0 reasoning for the NN training orchestration loop. Two stages:
  **0a** proposes the archetype list; **0b** turns one archetype into a written
  `description.md` and a buildable v1 `NNModelSpec` materialized on the artefact
  volume. You reason which indicators / targets / layers to use and WHY each layer
  is a real-data dependency — you do NOT search numerics (Optuna does that) and you
  do NOT launch training (the orchestrator does that).

  **Inputs:** `pair` (e.g. `link_usdt`); optional `archetype` (present ⇒ run 0b for
  it; absent ⇒ run 0a).

  ## Allowed vocabulary — read these FIRST, every run

  You may use ONLY these sets. This is the same vocabulary the in-loop NNStrategist
  uses. Read them fresh each run; do not invent names from memory.

  | Set | Source | Use |
  |---|---|---|
  | Indicators (features) | `main/configs/indicators_config.yaml` field names (140+, e.g. `rsi_14`, `logret`, `macd_12_26_9_slope`) | feature columns |
  | Timeframes | `main/configs/candles_config.yaml` `candles: [1,5,15,60,240,1440]` | candle resolutions |
  | Targets | `indicators_config.yaml` `labels:` entries + TargetSpec kinds `direction`/`label`/`regression` | the prediction target |
  | Buildable layer kinds | `dense`, `lstm`, `gru`, `conv1d` (+ mixed stacks) | layer `kind` |

  A name not in its set is not allowed. A layer kind not in the buildable set is
  **not-buildable-now**: do not declare it until the engine extension recipe in
  `phase-17.../DECISIONS-LOG.md` has added it via TDD — flag the archetype and link
  the recipe instead.

  ## Tier 0a — meta-investigation (when no `archetype` given)

  1. Read the four vocabulary sources above.
  2. Brainstorm 4–8 distinct archetypes — each a single real-data hypothesis with a
     distinct architecture shape. Examples of the *shape* (not a fixed list):
     - snapshot dense (cross-feature interaction at one instant),
     - conv1d→dense (local candle pattern over a short window),
     - lstm/gru sequence (temporal dependency across bar history),
     - cnn_lstm (local pattern then temporal),
     - multi-timeframe (parallel branches over several `candles`).
  3. For each, decide its declared layer kinds and set **buildable-now = yes** iff
     every kind is in `{dense,lstm,gru,conv1d}`; otherwise **no** + link the recipe.
  4. Rank by expected signal-to-effort.
  5. Write `external/docs/superpowers/specs/supporting-systems/nn-training-orchestration/meta-investigation.md`:
     a short intro + a table with columns `archetype | thesis (1 line) | layer kinds | buildable-now`.
     STOP. (Choosing which archetype to pursue is the orchestrator's call.)

  ## Tier 0b — per-archetype deep investigation (when `archetype` given)

  1. Re-read the vocabulary sources. Confirm the archetype is **buildable-now**;
     if not, STOP and report the recipe link — do not emit a spec.
  2. Reason the design and write
     `.../nn-training-orchestration/{archetype}/description.md` using the template
     in the task file VERBATIM (Design thesis; Indicators rationale; Layers
     real-data-dependency rationale; Target rationale; Initial hyperparameters +
     why; VRAM note). Every indicator name must exist in `indicators_config.yaml`;
     every layer must map to a stated real-data dependency; every layer kind must be
     buildable-now.
  3. Build the v1 `NNModelSpec` from that reasoning (in a short python snippet run
     under `main/.venv`): construct `LayerSpec(...)` per the description's layer
     stack, `TargetSpec(...)` per the target section, and set the **locked starting
     values** — `batch_size=128` (or `64` if the stack contains `lstm`/`gru`),
     `epochs=50`, `patience=8`, `learning_rate=1e-3`, `dropout=0.2`. Optuna will
     tune only `units`/`learning_rate`/`dropout` later (ADR-0001) — kinds and count
     are fixed here.
  4. Materialize to the volume, NOT the repo:
     ```python
     from nn.device import nn_artefact_root
     from nn.orchestration.spec_store import materialize_spec
     path = materialize_spec(spec, nn_artefact_root(pair))  # → …/specs/{spec_hash}/spec.yaml
     ```
     Record the returned path (and `spec.spec_hash`) in the description's footer.
  5. Self-check before handing off: re-load it — `NNModelSpec.from_yaml(str(path))`
     must succeed; `layers` non-empty with kinds ⊆ buildable set; `targets`
     non-empty with kinds ⊆ `{direction,label,regression}`; starting values set.

  ## Red flags — STOP

  - An indicator name you "remember" but did not find in `indicators_config.yaml`.
  - A layer kind outside `{dense,lstm,gru,conv1d}` without the recipe applied first.
  - Writing `spec.yaml` anywhere under `main/` (it goes on the volume, via
    `materialize_spec`).
  - Picking `units`/`lr`/`dropout` as "the answer" — those are Optuna's to tune; you
    fix only kinds, count, target, and the locked starting values.
  - A layer with no real-data-dependency sentence — remove it.
  ````
  Verify the file exists and the frontmatter is well-formed:
  ```bash
  cd /home/om/projects/simple_trader/main && \
    .venv/bin/python -c "import yaml,io,pathlib; t=pathlib.Path('.agents/skills/nn-investigate/SKILL.md').read_text(); fm=t.split('---')[1]; d=yaml.safe_load(fm); assert d['name']=='nn-investigate' and d['description'].lower().startswith('use when'); print('frontmatter ok')"
  ```
  Expected: `frontmatter ok`.

- [ ] **Step 2: Write the sample v1 fixture spec.**
  This is a representative v1 `spec.yaml` of the kind Tier-0b emits — a small
  `cnn_lstm` archetype (conv1d → lstm → dense), recurrent batch_size 64. Create
  `main/tests/nn/orchestration/fixtures/sample_v1_spec.yaml`:
  ```bash
  cd /home/om/projects/simple_trader/main && mkdir -p tests/nn/orchestration/fixtures
  ```
  Write `main/tests/nn/orchestration/fixtures/sample_v1_spec.yaml` with exactly:
  ```yaml
  # Representative Tier-0b v1 spec: cnn_lstm archetype (conv1d -> lstm -> dense).
  # Feature names are real indicators_config.yaml fields; target is a direction kind.
  # Locked starting values: recurrent => batch_size 64, epochs 50, patience 8.
  features:
    - logret
    - rsi_14
    - macd_12_26_9_slope
  layers:
    - kind: conv1d
      units: 32
      params:
        kernel_size: 3
    - kind: lstm
      units: 64
      params:
        num_layers: 1
    - kind: dense
      units: 32
      params: {}
  targets:
    - name: dir_60
      kind: direction
      params:
        horizon: 60
  batch_size: 64
  epochs: 50
  patience: 8
  learning_rate: 0.001
  dropout: 0.2
  seed: 42
  device: cpu
  ```
  > The exact key set (`features`/`layers`/`targets`/scalars) MUST match what
  > `NNModelSpec.from_yaml` consumes — confirm against `nn/nn_model_spec.py` while
  > writing. If `from_yaml` names a required key not present here (or rejects an
  > extra one), the contract test in Step 3 will FAIL on load; fix THIS fixture to
  > match the real schema (do not weaken the test). Adjust only key names/shape to
  > satisfy `from_yaml`; keep the kinds (conv1d/lstm/dense + direction) and the
  > locked values.

- [ ] **Step 3: RED — write the contract test, run it, watch it fail.**
  Create `main/tests/nn/orchestration/test_investigate_contract.py` with exactly:
  ```python
  """Contract test for the nn-investigate skill's documented output.

  Phase 17 Task 09. The skill's contract (README Layer C): any emitted spec.yaml
  MUST load via NNModelSpec.from_yaml and be well-formed. We pin that here against
  a representative Tier-0b v1 spec fixture — proving the documented output shape is
  actually loadable and buildable, not just plausible markdown.
  """

  from pathlib import Path

  from nn.nn_model_spec import NNModelSpec

  FIXTURE = Path(__file__).parent / "fixtures" / "sample_v1_spec.yaml"

  BUILDABLE_LAYER_KINDS = {"dense", "lstm", "gru", "conv1d"}
  TARGET_KINDS = {"direction", "label", "regression"}


  def _load():
      return NNModelSpec.from_yaml(str(FIXTURE))


  def test_sample_v1_spec_loads_via_from_yaml():
      spec = _load()  # must not raise
      assert spec is not None
      assert spec.spec_hash  # hashable => fully constructed


  def test_layers_are_nonempty_and_buildable():
      spec = _load()
      assert spec.layers, "v1 spec must declare at least one layer"
      for layer in spec.layers:
          assert layer.kind in BUILDABLE_LAYER_KINDS, (
              f"layer kind {layer.kind!r} not buildable by _SpecNet today; "
              f"needs the engine extension recipe first"
          )


  def test_targets_are_nonempty_and_well_formed():
      spec = _load()
      assert spec.targets, "v1 spec must declare at least one target"
      for target in spec.targets:
          assert target.kind in TARGET_KINDS, (
              f"target kind {target.kind!r} not in {sorted(TARGET_KINDS)}"
          )


  def test_locked_starting_values_are_set():
      spec = _load()
      # recurrent archetype => batch_size 64; others 128. Fixture is cnn_lstm => 64.
      assert spec.batch_size == 64
      assert spec.epochs == 50
      assert spec.patience == 8
  ```
  Run it RED (expected to fail until the fixture matches the real schema):
  ```bash
  cd /home/om/projects/simple_trader/main && \
    .venv/bin/pytest tests/nn/orchestration/test_investigate_contract.py -q
  ```
  Expected on first run: FAIL — likely an attribute/key mismatch (`from_yaml`
  rejects an unexpected key, or `spec.targets`/`spec.layers`/`spec.patience` is
  named differently). This is the RED signal that the fixture's shape does not yet
  match the contract.

- [ ] **Step 4: GREEN — align the fixture to the real schema, re-run.**
  Read `main/nn/nn_model_spec.py` for the exact field names/shape `from_yaml`
  consumes (`LayerSpec` fields, `TargetSpec` fields, the scalar attribute names
  like `batch_size`/`epochs`/`patience`). Edit ONLY
  `tests/nn/orchestration/fixtures/sample_v1_spec.yaml` so it loads — keep the
  conv1d/lstm/dense stack, the `direction` target, and the locked values
  (`batch_size 64`, `epochs 50`, `patience 8`). Do not edit the test to fit a
  broken fixture.
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && \
    .venv/bin/pytest tests/nn/orchestration/test_investigate_contract.py -q
  ```
  Expected: PASS — `4 passed`.

- [ ] **Step 5: GREEN gate — passes in the nn-train image too.**
  `from_yaml` pulls in the `nn` package; confirm it also passes in the GPU image:
  ```bash
  cd /home/om/projects/simple_trader && docker compose run --rm nn-train \
    python -m pytest tests/nn/orchestration/test_investigate_contract.py -q
  ```
  Expected: PASS — `4 passed`.

- [ ] **Step 6: GREEN gate — no regression in the nn suite.**
  ```bash
  cd /home/om/projects/simple_trader && docker compose run --rm nn-train \
    python -m pytest tests/nn/ -q
  ```
  Expected: PASS — existing nn tests (Tasks 04–08) stay green; this task only adds
  a skill, a fixture, and a new test module.

- [ ] **Step 7: Wire the runtime symlink (so `.claude/skills/` sees it).**
  The canonical copy lives in `.agents/skills/`; the runtime reads `.claude/skills/`.
  ```bash
  cd /home/om/projects/simple_trader/main
  mkdir -p .claude/skills
  [ -e .claude/skills/nn-investigate ] || \
    ln -s ../../.agents/skills/nn-investigate .claude/skills/nn-investigate
  ls -l .claude/skills/nn-investigate
  ```
  Expected: a symlink `nn-investigate -> ../../.agents/skills/nn-investigate`.
  (If sibling skills already use a different symlink convention, match theirs.)

- [ ] **Step 8: Commit.**
  ```bash
  cd /home/om/projects/simple_trader/main
  git add .agents/skills/nn-investigate/SKILL.md \
          .claude/skills/nn-investigate \
          tests/nn/orchestration/fixtures/sample_v1_spec.yaml \
          tests/nn/orchestration/test_investigate_contract.py
  git commit -m "feat(skill): nn-investigate Tier-0a/0b"
  ```
  Expected: clean commit; `git status` shows nothing pending under
  `.agents/skills/nn-investigate/` or `tests/nn/orchestration/`.
  (Drop `.claude/skills/nn-investigate` from `git add` if the repo ignores
  `.claude/` symlinks or already tracks it.)
