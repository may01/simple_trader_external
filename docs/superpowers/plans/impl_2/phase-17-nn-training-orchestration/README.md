# Phase 17 — NN Training Orchestration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. This phase is governed by **layer-first-planning** (Docker-first, layer-ordered, interface-before-code, Docker-verified integration tests) and **TDD** (vertical tracer bullets: one test → one implementation).

**Goal:** Add a skill-driven orchestration layer that designs candidate NN archetypes for stock-price prediction, drives their training through the existing in-code search, and evolves them version-by-version with written reasoning and reports — while migrating the engine so architecture is declared (not dense-only) and externally specifiable.

**Architecture:** Three tiers above the existing `TrainingLoop`/Optuna/`ExperimentTracker`. **Tier 0** (agents) reasons archetypes + emits specs; **Tier 1** (existing code, Optuna) tunes numerics within a fixed declared architecture; **Tier 2** (agents) evolves versions, comparing on a holdout gate. The phase delivers it bottom-up across three layers: (A) training-pipeline engine migration, (B) orchestration loop-driver code, (C) the skill-set + runbook.

**Tech Stack:** Python 3, PyTorch + Optuna (in the `nn-train` Docker image), PyYAML, pytest. Skills are markdown under `.agents/skills/`. Reasoning/reports are agent-authored markdown (external repo).

**Spec:** [CONTEXT.md](../../specs/supporting-systems/nn-training-orchestration/CONTEXT.md) · [ADR-0001 architecture](../../specs/supporting-systems/nn-training-orchestration/adr/0001-ai-reasoned-architecture.md) · [ADR-0002 promotion gate](../../specs/supporting-systems/nn-training-orchestration/adr/0002-promotion-gate-accuracy.md) · [starting-values.md](../../specs/supporting-systems/nn-training-orchestration/starting-values.md)

---

## Global Constraints

- **Naming:** the project is `simple_trader` (never `pybtctr2`); volume names (`simple_trader_vol_long` etc.) are exempt.
- **Docs are external:** all reasoning docs, reports, specs-of-record, ADRs live under `external/docs/superpowers/`. Only runtime code + config live in `main/`. Never commit docs to the code repo.
- **Specs on the artefact volume:** a version's `spec.yaml` is written to `{nn_artefact_root(pair)}/specs/{spec_hash}/spec.yaml` (read-write root = `/trader_data_long`). The trainer reads it via `NN_SPEC_PATH`. Never overwrite `main/configs/nn_spec.yaml` from the loop (root-owned-file/merge hazard in mounted worktrees).
- **Promotion metric (ADR-0002):** "better" = holdout accuracy + loss only. No backtest P&L this phase. Every report records per-class accuracy + confusion.
- **Architecture is reasoned, not searched (ADR-0001):** Optuna tunes `units` (width), `learning_rate`, `dropout` only — never layer kind or count.
- **Tests run in Docker:** any test importing torch/optuna runs in the `nn-train` image (`docker compose run --rm nn-train python -m pytest <path>`). Pure-python tests (no torch) may run in the base venv but must also pass in the image.
- **Locked starting values:** batch_size 128 (64 recurrent), epochs 50 / patience 8, trials_per_round 8, n_startup_trials 4, max_rounds 1, max_wall_clock_s 3600, K=2, max_versions 6, margin 0.01, per-archetype budget 8 h. Iterate on 2y `link_usdt`; re-validate winners on 4y.
- **Workflow:** branch per task; TDD red→green per task; never commit/push without explicit user confirmation.

---

## Layer Order (this phase)

| Layer | Maps to pipeline | Tasks |
|---|---|---|
| **0 Docker** | entry points | Docker Entry Points section below |
| **A — Engine migration** | Layer 2 Training pipeline | T01–T04 |
| **B — Loop-driver code** | new, above Layer 2 | T05–T08 |
| **C — Skill-set** | agent-facing | T09–T11 |

Layer N is not started until layer N-1's integration test is RED in Docker; not completed until its unit + integration tests are GREEN in Docker.

---

## Docker Entry Points (ground truth — implementation must make these work)

```bash
# Build the training image (torch + optuna)
docker compose build nn-train

# Train ONE version: read its spec from the artefact volume via NN_SPEC_PATH,
# scope the Optuna study to this version, write trials/best.json under tracking/{study}.
docker compose run --rm \
  -e NN_SPEC_PATH=/trader_data_long/train/link_usdt/nn/specs/<spec_hash>/spec.yaml \
  -e NN_STUDY=<archetype>_v<n> \
  -e NN_TRAIN_MODE=search \
  nn-train

# Poll progress / read result (host side):
#   {shared_folder}/training_state.pkl            → {"phase","study","best"}
#   {nn_artefact_root}/tracking/<study>/best.json → {group_key: incumbent record (holdout_score)}

# Run the phase test suites inside the image:
docker compose run --rm nn-train python -m pytest tests/nn -q
```

Verified: [ ] `docker compose build nn-train` succeeds · [ ] `docker compose run --rm nn-train python -m pytest tests/nn -q` runs.

---

## Canonical Interface Contracts (every task MUST match these names/types verbatim)

**Layer A — engine (modify existing):**
```python
# nn/device.py  (new helper)
def nn_spec_path() -> str: ...
    # returns os.environ.get("NN_SPEC_PATH", "configs/nn_spec.yaml")

# nn/nn_orchestrator.py  NNOrchestrator.from_trainer — change ONLY the spec load:
#   base_spec = NNModelSpec.from_yaml(nn_spec_path())

# nn/nn_model_spec.py  NNModelSpec  (new methods)
def to_dict(self) -> dict: ...          # full asdict incl device/seed, nested plain dicts
def to_yaml(self, path: str) -> None: ...  # yaml.safe_dump(self.to_dict()) → path

# nn/training_loop.py  TrainingLoop.build_spec — keep declared layers; tune width/lr/dropout only:
#   units = trial.suggest_int("units", units_lo, units_hi)
#   lr    = trial.suggest_float("lr", lr_lo, lr_hi, log=True)
#   dropout = trial.suggest_float("dropout", drop_lo, drop_hi)
#   spec.layers = [dataclasses.replace(l, units=units) for l in base_spec.layers]
#   spec.learning_rate, spec.dropout, spec.seed set; NO depth suggestion, NO kind change.

# nn/training_loop.py  run() — TPESampler reads n_startup_trials from search_config:
#   n_startup = int(self.search_config.get("n_startup_trials", 10))
#   sampler = optuna.samplers.TPESampler(seed=seed, n_startup_trials=n_startup)
```

**Layer B — loop-driver (new package `nn/orchestration/`):**
```python
# nn/orchestration/spec_store.py
def materialize_spec(spec: NNModelSpec, artefact_root: Path) -> Path: ...
    # writes {artefact_root}/specs/{spec.spec_hash}/spec.yaml ; returns that Path; idempotent

# nn/orchestration/report.py
@dataclass
class ReportMeta:
    archetype: str
    version: int
    parent: str | None           # parent version label e.g. "v2", or None for v1
    spec_hash: str
    hypothesis: str              # what structural change this version tests
    holdout_acc: float
    holdout_loss: float
    per_class: dict              # {"up": float, "neutral": float, "down": float}
    decision: str                # "promote" | "revert" | "pending"
    strike: int
    next_hypothesis: str | None
def parse_report(md: str) -> ReportMeta: ...     # reads YAML frontmatter; raises on missing keys
def render_report(meta: ReportMeta, body: str) -> str: ...  # frontmatter + "\n" + body

# nn/orchestration/lineage.py
@dataclass
class LineageDecision:
    action: str        # "promote" | "revert"
    new_best: bool
    strike_count: int  # updated count after this version
    stop: bool
    reason: str        # human-readable why (for the report + log)
def decide(*, best_score: float | None, candidate_score: float, margin: float,
           strike_count: int, K: int, version_n: int, max_versions: int,
           elapsed_s: float, budget_s: float) -> LineageDecision: ...

# nn/orchestration/runner.py
@dataclass
class VersionResult:
    study: str
    holdout_score: float
    best: dict
def run_version_training(spec_path: str, study: str, *, pair: str,
                         timeout_s: float, extra_env: dict | None = None) -> VersionResult: ...
    # launches `docker compose run nn-train` with NN_SPEC_PATH/NN_STUDY, polls
    # tracking/{study}/best.json until present or timeout; parses holdout_score.
```

**Layer C — skills (new, committed in-repo under `.claude/skills/<name>/`):** `nn-investigate` (Tier 0a + 0b), `nn-evolve` (Tier 2), `nn-train-orchestrator` (walk archetypes, gate per archetype). They are git-tracked on the branch (reviewed with the `nn/orchestration` code they drive); a post-merge deploy step symlinks them into the project-root discovery path (`/home/om/projects/simple_trader/.agents/skills/`) — see RUNBOOK.md. Contracts: any emitted `spec.yaml` MUST load via `NNModelSpec.from_yaml`; any emitted `report.md` MUST parse via `parse_report`.

---

## Task Index

| Task | Layer | Deliverable | Test surface |
|---|---|---|---|
| T01 | A | `nn_spec_path()` + `NN_SPEC_PATH` override in `from_trainer` | unit + Docker integration |
| T02 | A | `build_spec` respects declared layers (ADR-0001); drop `depth` | unit |
| T03 | A | config migration (`nn_search.yaml` locked values) + thread `n_startup_trials` | unit |
| T04 | A | `NNModelSpec.to_dict`/`to_yaml` round-trip | unit |
| T05 | B | `spec_store.materialize_spec` | unit |
| T06 | B | `report.py` — `ReportMeta` + `parse_report`/`render_report` | unit |
| T07 | B | `lineage.decide` — promote/revert/strike/stop (ADR-0002 + locked values) | unit |
| T08 | B | `runner.run_version_training` — launch + poll | Docker integration |
| T09 | C | `nn-investigate` skill (Tier 0a meta + 0b per-archetype) + spec-validates test | contract |
| T10 | C | `nn-evolve` skill (Tier 2) — report → next version via `decide` | contract |
| T11 | C | `nn-train-orchestrator` skill + runbook + end-to-end lineage smoke in Docker | Docker e2e |

Engine extension recipe (adding a new `LayerSpec` kind on demand, e.g. attention) is documented in [DECISIONS-LOG.md](./DECISIONS-LOG.md); new kinds are added during the loop via TDD against `_add_layer`, not pre-built.
