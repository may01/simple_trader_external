# ExperimentTracker Specification

**File:** `nn/experiment_tracker.py`
**Purpose:** Record every training trial, validate model improvement against a held-out set, and gate promotion of new best models. Dependency-free local store (JSON manifests + SQLite index) — no MLflow.

---

## 1. Class Overview

`ExperimentTracker` is the memory and judge of the training loop. It answers two questions the loop depends on:

1. *What has been tried, and how did it do?* — a durable, queryable history of trials feeding the `NNStrategist`.
2. *Is this candidate actually better?* — a strict promotion gate so the best checkpoint only changes when a new model beats the incumbent on a holdout set by a margin (not on noise or validation overfit).

Storage is local and serverless: a SQLite index for fast queries plus per-trial JSON records under the tracking directory.

---

## 2. Storage Layout

```
tracking/{study_name}/
├── index.sqlite           # one row per trial (queryable)
├── trials/{trial_id}.json # full record: spec, metrics, rationale
└── best.json              # current incumbent per group (class/regime)
```

### SQLite `trials` columns
`trial_id, round, group_key, spec_hash, train_acc, val_acc, holdout_score, promoted (bool), status (ok|failed|pruned), created_at`.

### Trial JSON record
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

---

## 3. Constructor

### `__init__(tracking_dir, study_name, metric="holdout_score", margin=0.0, mode="max")`
- `study_name` — keys `tracking/{study_name}/`; resolved and owned by `Trainer._run_train_nn()`, reuse = resume (see `training-coordinator-class.md` §2 "Study identity").
- `metric` — the promotion criterion (holdout direction-accuracy by default; configurable per target type).
- `margin` — minimum improvement over incumbent required to promote (guards against noise).
- `mode` — `"max"` or `"min"`.
- Creates the study directory and SQLite schema if absent.

---

## 4. Key Methods

### `record(spec, metrics, holdout, round, status="ok", rationale=None) -> str`
- Writes the trial JSON and inserts the SQLite row; returns `trial_id`.
- `status="failed"|"pruned"` records non-completing trials so the strategist sees dead ends.

### `is_improvement(group_key, holdout) -> bool`
- The **promotion gate**: returns `True` only if `holdout[metric]` beats the incumbent for `group_key` by at least `margin` (respecting `mode`). No incumbent → `True`.

### `promote(group_key, trial_id) -> None`
- Updates `best.json` for `group_key`, marks the trial `promoted=true`. Called by the loop after `CheckpointManager.save(..., promote=True)` so the tracker's notion of best stays in sync with the saved weights.

### `summary() -> dict`
- Compact history for the `NNStrategist`: incumbent metrics, per-indicator and per-target performance deltas, recent trial outcomes, count of trials/rounds. Sized to fit an LLM prompt (aggregated, not raw).

### `round_summary(round) -> dict`
- Metrics for one round (best/median/failed counts) feeding `NNStrategist.review()`.

### `best(group_key=None) -> dict`
- Returns incumbent trial record(s).

### `export(format="json") -> str`
- Exports the full history (JSON or CSV) for offline analysis.

---

## 5. Improvement Validation

- **Holdout, not validation:** promotion is judged on the time-ordered holdout split (untouched by training and Optuna pruning), so a model that overfit the validation set cannot be promoted.
- **Margin gate:** small holdout gains within `margin` are treated as no improvement, preventing churn on noise.
- **Per-group:** each group (class/regime) has its own incumbent; promotion is independent across groups.
- **Metric per target family:** classification uses holdout accuracy/F1; regression uses holdout MAE/Huber (with `mode="min"`); multi-target uses a configured weighted combination declared in the study config.

---

## 6. Error Handling

- Corrupt `index.sqlite` → rebuilt from the `trials/*.json` records (JSON is the source of truth).
- Missing holdout (empty split) → trial recorded but cannot be promoted; loop warns.
- Concurrent writers (parallel trials) → SQLite WAL mode + per-trial JSON files avoid contention; `best.json` updates are serialised.

---

## 7. Notes

- Replaces the legacy parallel-result aggregation; the unit of aggregation is now a *trial*, not a worker shard.
- The tracker is the contract between numeric search and LLM reasoning: Optuna writes trials, the strategist reads `summary()`, the gate decides truth.
