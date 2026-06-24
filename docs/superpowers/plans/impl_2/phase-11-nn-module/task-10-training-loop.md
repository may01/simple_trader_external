# Task 10: TrainingLoop (Hybrid Optuna + LLM Loop)

**Phase:** 11 — NN Module  
**Depends on:** Task 07 (ExperimentTracker), Task 08 (NNOrchestrator), Task 09 (NNStrategist)  
**Produces:** `nn/training_loop.py`

---

## Goal
Turn NN training from a single run into a **search for a better model**. `TrainingLoop` runs the hybrid agentic improvement loop: an `NNStrategist` (LLM) decides *which* indicators / timeframes / targets to explore and *when to stop*; Optuna samples and prunes the numeric hyperparameters *within* that scope; `NNOrchestrator` trains each concrete spec; `ExperimentTracker` records every trial and gates promotion on a time-ordered holdout. The terminal artefact is the promoted best checkpoint per group plus the tracker's full history.

The strategist *moves* the search space; Optuna explores *within* it. This keeps numeric search efficient while letting structural decisions (drop a noisy indicator, switch to a longer horizon, add a regression head) be reasoned about explicitly and logged.

## Context
This replaces single-shot training (`NNOrchestrator.train()` standalone) with a **round-based agentic loop**:
- **Round-based, not one-shot** — each round is `propose → Optuna study → train+evaluate trials → record → review`; the strategist's review decides whether the loop continues, re-scopes, or stops.
- **Three-way separation of concerns** — numeric sampling/pruning (Optuna), scope + stop reasoning (NNStrategist), train-one-spec (NNOrchestrator/NNModel), record/holdout/promotion (ExperimentTracker). The loop only orchestrates; it owns no model weights, no metric definitions, no LLM prompt.
- **Holdout promotion gate** — a trial becomes the incumbent only when `tracker.is_improvement(group_key, holdout)` is True, then `CheckpointManager.save(..., promote=True)` and `tracker.promote(...)` keep saved weights and `best.json` in sync.
- **Bounded + reproducible** — per-run caps (rounds/trials/wall-clock/compute) stop the loop at the first cap regardless of strategist output; all randomness is seeded (`spec.seed`, Optuna seed) so rounds replay identically.
- **Strategist optional** — with the strategist disabled the loop degrades to a pure Optuna search over `base_spec` (no propose/review, one open-ended study constrained only by caps).

## Files
- Create: `nn/training_loop.py`

## Interface

```python
class TrainingLoop:
    def __init__(
        self,
        orchestrator: "NNOrchestrator",
        tracker: "ExperimentTracker",
        strategist: "NNStrategist | None",
        search_config: dict,
    ) -> None: ...
    # orchestrator: trains one concrete spec per trial (Task 08).
    # tracker: trial store + holdout promotion gate, already constructed and NAMED by
    #   Trainer._run_train_nn() (Task 07); the loop never derives or mutates study_name.
    # strategist: LLM steering (Task 09); None → pure-Optuna degrade mode.
    # search_config keys (read here, not invented):
    #   max_rounds, trials_per_round, sampler ("tpe"), pruner ("median"),
    #   search_space bounds + clamps (lr/depth/units/dropout caps the strategist cannot exceed),
    #   max_wall_clock_s, max_compute (caps), seed.

    def run(self, df, data_attributes) -> "RunResult": ...
    # The round loop (ordered steps below). Returns tracker.best() wrapped as RunResult.
```

### `run(df, data_attributes)` — ordered steps (description, not code)

For each `round` in `range(search_config["max_rounds"])`:

1. **Propose scope.** If a strategist is present, `proposal = strategist.propose(history=tracker.summary())` → indicator set, timeframe set, target set, search-space bounds, rationale. The proposal's bounds are clamped to `search_config` limits (the strategist cannot request unbounded LR/depth — clamping is enforced here before the bounds reach Optuna). In pure-Optuna mode (no strategist), `proposal` is `base_spec`'s scope unchanged and only the `search_config` bounds apply.
2. **Create the Optuna study.** `optuna.create_study(direction=...)` (`"maximize"`, or `"minimize"` when the tracker metric uses `mode="min"`), `sampler=TPESampler(seed=search_config["seed"])`, `pruner=MedianPruner`. The study is *per round* (Optuna explores within this round's scope); the cross-round incumbent lives in the tracker, not in Optuna.
3. **Run trials.** For each `trial` in `range(search_config["trials_per_round"])`:
   1. `spec = build_spec(base_spec, proposal, optuna_suggestions(trial))` — proposal sets the *structural* scope (indicators/timeframes/targets), Optuna suggests the *numeric* knobs (lr, depth, units, dropout) within the clamped bounds; `spec.seed` is set for reproducibility.
   2. `metrics = orchestrator.train(df, data_attributes, spec, epoch_callback=optuna_prune_cb)` — the prune callback reports intermediate epoch metrics to Optuna so weak trials are pruned early.
   3. `holdout = evaluate_on_holdout(spec, df, data_attributes)` — score on the time-ordered holdout split (untouched by training and Optuna pruning).
   4. `tracker.record(spec, metrics, holdout, round)` — durable trial record (status `"ok"`).
   5. **Promotion gate (per group):** for each group_key, if `tracker.is_improvement(group_key, holdout)` → `checkpoint_manager.save(model, holdout, promote=True)` then `tracker.promote(group_key, trial_id)` so saved weights and `best.json` stay in sync.
   6. **Caps check:** after each trial, if any per-run cap (rounds/trials/wall-clock/compute) is reached, stop the loop immediately (return — see step 5).
4. **Review.** If a strategist is present, `decision = strategist.review(tracker.round_summary(round))` → one of `continue | narrow | broaden | change_targets | stop`. If no trial in the round beat the incumbent, the incumbent is retained and the strategist is told so (via `round_summary`) so it can broaden. `decision == "stop"` breaks the loop. In pure-Optuna mode there is no review — the loop continues until a cap is hit.
5. **Return.** On `stop`, any cap, or exhausting `max_rounds`, return `tracker.best()` wrapped as `RunResult` (promoted best per group + history pointer).

### `study_name` ownership / resume semantics
- **Owner:** `Trainer._run_train_nn()` resolves `study_name`, constructs the `ExperimentTracker` with it, and passes the tracker into `TrainingLoop`. The loop receives an already-named tracker and **never derives or mutates** `study_name`.
- **Source / default:** training config / CLI (`--study <name>`); when omitted, default `"{PAIR}_{base_spec.spec_hash[:8]}"` — pair-scoped, stable across restarts of the same base spec.
- **Resume:** reusing an existing `study_name` **resumes** that study — the loop reads the existing SQLite index + `best.json` as starting history/incumbent. A **fresh** search requires a **new name**; this is the only resume/fresh switch, a deliberate caller decision, never auto-generated per process (auto-timestamping would silently fork history each run).
- **Validation:** filesystem-safe slug (no path separators), rejected early by `Trainer` before the tracker touches disk.

### Division of labour

| Concern | Owner |
|---------|-------|
| Numeric hyperparameter/architecture sampling, pruning | Optuna (TPE sampler, MedianPruner) |
| Which indicators / timeframes / targets to explore, when to stop, why | `NNStrategist` (LLM) |
| Train one concrete spec | `NNModel` via `NNOrchestrator` |
| Record trials, hold out, decide promotion | `ExperimentTracker` |

## Key Constraints
- **Promotion via the tracker, on a time-ordered holdout.** A trial promotes only when `tracker.is_improvement(group_key, holdout)` is True; then `CheckpointManager.save(..., promote=True)` and `tracker.promote(...)` are called together so weights and `best.json` never diverge. The loop never re-implements the gate.
- **Per-run caps stop at the first cap.** `max_rounds`, `trials_per_round`, wall-clock and compute budgets all bound the loop; whichever is hit first stops it, regardless of strategist output. Caps override the strategist.
- **Trial failure is isolated.** A trial that raises (bad spec, OOM, training error) is recorded as `status="failed"` (and pruned in Optuna); the loop continues to the next trial — one bad spec never aborts the round. **GPU OOM → retry the trial once on CPU** (per `nn-infrastructure.md` device policy) before marking it failed. Recorded failures are visible to the strategist as dead ends.
- **Seeded reproducibility.** `spec.seed` and the Optuna sampler seed are set from `search_config["seed"]`; rounds replay identically.
- **Bounds are clamped before Optuna sees them.** Strategist-proposed search-space bounds are clamped to `search_config` limits in the loop so the LLM cannot request unbounded LR/depth.
- **Strategist optional → pure-Optuna degrade.** With `strategist=None`, the loop skips `propose`/`review`, runs an Optuna search over `base_spec`'s scope, and terminates only on caps; everything else (record, holdout gate, promotion, seeding) is unchanged.
- **The loop owns orchestration only.** It owns no weights, no metric definitions, no LLM prompt — those belong to NNOrchestrator/CheckpointManager, ExperimentTracker, and NNStrategist respectively.

## Verification
```bash
docker compose run --rm nn-train python3 -c "
from nn.training_loop import TrainingLoop
from nn.nn_orchestrator import NNOrchestrator
from nn.experiment_tracker import ExperimentTracker
from nn.model_spec import NNModelSpec
import tempfile, os, pandas as pd, numpy as np

# tiny dataset
np.random.seed(0)
n = 200
df = pd.DataFrame({
    'open': np.random.rand(n), 'high': np.random.rand(n),
    'low': np.random.rand(n), 'close': np.random.rand(n),
    'volume': np.random.rand(n),
}, index=pd.date_range('2020-01-01', periods=n, freq='1h'))
data_attributes = {}  # minimal

ckpt = tempfile.mkdtemp(); dsdir = tempfile.mkdtemp(); track = tempfile.mkdtemp()
base = NNModelSpec.default()  # or a minimal valid spec

orch = NNOrchestrator(checkpoint_dir=ckpt, dataset_dir=dsdir, base_spec=base)
tracker = ExperimentTracker(track, 'study_smoke', metric='holdout_score', mode='max')

# strategist disabled -> pure-Optuna degrade
loop = TrainingLoop(
    orchestrator=orch,
    tracker=tracker,
    strategist=None,
    search_config={
        'max_rounds': 1, 'trials_per_round': 2,
        'sampler': 'tpe', 'pruner': 'median',
        'max_wall_clock_s': 120, 'seed': 0,
        'search_space': {'lr': [1e-4, 1e-2], 'depth': [1, 2]},
    },
)

result = loop.run(df, data_attributes)
assert result is not None, 'run() returned no RunResult'

best = tracker.best('all')
assert best is not None, 'no incumbent recorded'

# tracking dir populated
assert os.path.exists(os.path.join(track, 'study_smoke', 'index.sqlite'))
assert os.path.isdir(os.path.join(track, 'study_smoke', 'trials'))
print('OK')
"
```

## Commit
`feat(nn): TrainingLoop hybrid Optuna + NNStrategist round loop`
