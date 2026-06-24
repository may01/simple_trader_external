# Task 07: ExperimentTracker (Trial Store + Holdout Promotion Gate)

**Phase:** 11 — NN Module  
**Depends on:** Task 02 (NNModelSpec)  
**Produces:** `nn/experiment_tracker.py`

---

## Goal
Build a dependency-free local trial store (JSON + SQLite, no MLflow) that:
1. Records every training trial (spec, metrics, holdout result, rationale) durably and queryably — the history the `NNStrategist` reads.
2. Gates promotion of new best models: a candidate becomes the incumbent only when it beats the current best on a time-ordered **holdout** by at least `margin`.

The tracker is the contract between numeric search (Optuna writes trials) and LLM reasoning (the strategist reads `summary()`); the gate decides truth.

## Context
This **replaces the legacy `ResultAggregator`**. Under the old design the unit of aggregation was a *worker shard* (parallel-result merging). Now the unit of aggregation is a **trial**. Three things change:
- **Holdout-based, margin-gated promotion** — improvement is judged on a time-ordered holdout split (untouched by training and Optuna pruning), not on validation; gains within `margin` are noise and do not promote.
- **Per-group incumbent** — each group (class / regime) has its own best, tracked independently; `best.json` maps `group_key → trial`.
- **Serverless storage** — SQLite index for fast queries + per-trial JSON manifests (JSON is the source of truth); no MLflow, no server.

## Files
- Create: `nn/experiment_tracker.py`

## Interface

```python
class ExperimentTracker:
    def __init__(
        self,
        tracking_dir: str,
        study_name: str,
        metric: str = "holdout_score",
        margin: float = 0.0,
        mode: str = "max",
    ) -> None: ...
    # study_name keys tracking/{study_name}/ (resolved/owned by Trainer._run_train_nn();
    #   reuse = resume). metric: promotion criterion (holdout direction-accuracy by default,
    #   configurable per target type). margin: min improvement over incumbent to promote
    #   (guards noise). mode: "max" or "min". Creates the study dir + SQLite schema if absent.

    def record(
        self,
        spec: "NNModelSpec",
        metrics: dict,
        holdout: dict,
        round: int,
        status: str = "ok",
        rationale: str = None,
    ) -> str: ...
    # Writes the trial JSON and inserts the SQLite row; returns trial_id.
    # status="failed"|"pruned" records non-completing trials so the strategist sees dead ends.

    def is_improvement(self, group_key: str, holdout: dict) -> bool: ...
    # Promotion gate: True only if holdout[metric] beats the incumbent for group_key by at
    #   least margin (respecting mode). No incumbent → True.

    def promote(self, group_key: str, trial_id: str) -> None: ...
    # Updates best.json for group_key, marks the trial promoted=true. Called by the loop after
    #   CheckpointManager.save(..., promote=True) so best stays in sync with saved weights.

    def summary(self) -> dict: ...
    # Compact history for the NNStrategist: incumbent metrics, per-indicator and per-target
    #   performance deltas, recent trial outcomes, count of trials/rounds. Sized to fit an LLM
    #   prompt (aggregated, NOT raw).

    def round_summary(self, round: int) -> dict: ...
    # Metrics for one round (best/median/failed counts) feeding NNStrategist.review().

    def best(self, group_key: str = None) -> dict: ...
    # Returns incumbent trial record(s).

    def export(self, format: str = "json") -> str: ...
    # Exports the full history (JSON or CSV) for offline analysis.
```

### Storage layout
```
tracking/{study_name}/
├── index.sqlite           # one row per trial (queryable)
├── trials/{trial_id}.json # full record: spec, metrics, rationale
└── best.json              # current incumbent per group (class/regime)
```

### SQLite `trials` columns (verbatim from spec)
```
trial_id, round, group_key, spec_hash, train_acc, val_acc, holdout_score, promoted (bool), status (ok|failed|pruned), created_at
```

### Trial JSON record (verbatim from spec)
```json
{
  "trial_id": "…", "round": 3, "group_key": "all",   // "all" for grouping=single; else class/regime key
  "spec_hash": "…", "spec": { …full NNModelSpec… },
  "metrics": {"loss":…, "accuracy":…, "val_loss":…, "val_accuracy":…, "per_target":{…}},
  "holdout": {"score":…, "per_target":{…}, "n_rows":…},
  "promoted": true,
  "strategist_rationale": "added vol_regime; dropped raw RSI level",
  "status": "ok"
}
```

## Key Constraints
- **Promotion judged on time-ordered HOLDOUT** (untouched by training/Optuna pruning), not validation — a model that overfit validation cannot be promoted.
- **Margin gate:** holdout gains within `margin` are treated as no improvement, preventing churn on noise.
- **Per-group incumbent:** `best.json` maps `group_key → trial`; promotion is independent across groups. (`group_key="all"` when grouping=single.)
- **Metric per target family:** classification uses holdout accuracy/F1; regression uses holdout MAE/Huber with `mode="min"`; multi-target uses a configured weighted combination from the study config.
- **`summary()` must fit an LLM prompt** — aggregated (incumbent metrics, deltas, recent outcomes, counts), not raw trial dumps.
- **Resilience:** corrupt `index.sqlite` → rebuilt from `trials/*.json` (JSON is source of truth); missing/empty holdout → trial recorded but cannot be promoted (loop warns); concurrent writers → SQLite WAL mode + per-trial JSON files, `best.json` updates serialised.

## Verification
```bash
docker compose run --rm nn-train python3 -c "
from nn.experiment_tracker import ExperimentTracker
from nn.model_spec import NNModelSpec
import tempfile, os, json

d = tempfile.mkdtemp()
t = ExperimentTracker(d, 'study_a', metric='holdout_score', margin=0.02, mode='max')

spec = NNModelSpec.default()  # or a minimal valid spec

# first trial: no incumbent → improvement, record + promote
h1 = {'holdout_score': 0.70, 'score': 0.70, 'per_target': {}, 'n_rows': 100}
assert t.is_improvement('all', h1) is True
id1 = t.record(spec, {'accuracy': 0.72, 'val_accuracy': 0.69}, h1, round=1)
t.promote('all', id1)

# within-margin gain (0.70 -> 0.715, margin 0.02) → NOT an improvement
h2 = {'holdout_score': 0.715, 'score': 0.715, 'per_target': {}, 'n_rows': 100}
assert t.is_improvement('all', h2) is False

# beyond-margin gain (0.70 -> 0.75) → improvement
h3 = {'holdout_score': 0.75, 'score': 0.75, 'per_target': {}, 'n_rows': 100}
assert t.is_improvement('all', h3) is True
id3 = t.record(spec, {'accuracy': 0.77, 'val_accuracy': 0.71}, h3, round=2)
t.promote('all', id3)

# promote updated best.json
best = json.load(open(os.path.join(d, 'study_a', 'best.json')))
assert best['all']['trial_id'] == id3, best

# storage artifacts exist
assert os.path.exists(os.path.join(d, 'study_a', 'index.sqlite'))
assert os.path.exists(os.path.join(d, 'study_a', 'trials', id3 + '.json'))

# summary() returns an LLM-sized dict
s = t.summary()
assert isinstance(s, dict)
print('OK')
"
```

## Commit
`feat(nn): ExperimentTracker trial store with holdout promotion gate`
