# Task 09: NNStrategist (LLM Search Steering)

**Phase:** 11 — NN Module  
**Depends on:** Task 07 (ExperimentTracker.summary)  
**Produces:** `nn/nn_strategist.py`

---

## Goal
Build the bounded LLM agent that **steers** the hybrid improvement loop: it reasons over experiment history and decides *which indicators, timeframes, and targets to explore* next, *what bounds Optuna should sample within*, and *when and why to stop*. It only emits structured, schema-validated proposals — it never trains, evaluates, or touches weights. Optuna owns numeric sampling and pruning; `NNStrategist` owns scope decisions.

## Context
Division of labour (from the `TrainingLoop` spec):

| Concern | Owner |
|---------|-------|
| Numeric hyperparameter/architecture sampling, pruning | Optuna |
| Which indicators / timeframes / targets to explore, when to stop, why | `NNStrategist` (LLM) |
| Train one concrete spec | `NNModel` via `NNOrchestrator` |
| Record trials, hold out, decide promotion | `ExperimentTracker` |

Optuna explores *within* a space; the strategist *moves* the space — it can drop a noisy indicator, switch to a longer horizon, or add a regression head, with the reasoning logged. The strategist is **optional**: when disabled, `TrainingLoop` degrades to a pure Optuna search over `base_spec`.

## Files
- Create: `nn/nn_strategist.py`

## Interface

### `propose(history: dict) -> Proposal`
- Input: `tracker.summary()` — incumbent/best metrics so far, per-indicator and per-target performance deltas, recent trial outcomes, trial/round counts. Already aggregated to fit an LLM prompt.
- Output (validated schema):
  ```python
  @dataclass
  class Proposal:
      indicators: list[str]
      timeframes: list[int]
      targets: list[TargetSpec]
      search_space: dict          # bounds for Optuna: lr range, depth range, units, dropout
      rationale: str              # why this scope — logged with the round
  ```
- **Investigation log (short form):** before returning, `propose` emits **one** concise, human-readable line via `logs.log()` summarising *what it investigated and what it decided* — for the user to follow the search at a glance, distinct from the verbose reproducibility record (prompt + full proposal). One line, no JSON dump. Shape (verbatim):
  ```
  [NNStrategist] round={r}: best={metric}={value:.4f} | signals: <top driver / weakest indicator from history> → propose {n_ind} ind, tf={timeframes}, targets=[…]; space lr={lo}-{hi}, depth={lo}-{hi} | why: {rationale[:120]}
  ```
  - Sourced only from inputs `propose` already has (the tracker `history` summary + the `Proposal` it is about to return) — no extra computation, no model/weight access.
  - Truncate `rationale` to keep the line readable; the full rationale stays in the `Proposal` and the reproducibility log.
  - On the fallback path (schema-rejected proposal → previous proposal reused), log instead (verbatim):
    ```
    [NNStrategist] round={r}: proposal rejected ({reason}); reusing previous scope
    ```
    so the user sees the search did not advance.

### `review(round_summary: dict) -> str`
- Input: `tracker.round_summary(round)` — best/median/failed counts for one round.
- Returns one of `continue | narrow | broaden | change_targets | stop`, plus a rationale. (If no trial beat the incumbent across the round, the strategist is told so it can `broaden`.)

## Key Constraints
- **Schema-validated proposals:** any field outside the allowed indicator/timeframe/target vocab is rejected; the round falls back to the **previous** proposal (and logs the rejection line above).
- **`review` verb is constrained** to the allowed vocab `continue | narrow | broaden | change_targets | stop`; out-of-vocab → fallback (treat as `continue`).
- **search_space bounds clamped** to `search_config` limits — the LLM cannot request unbounded LR / depth / units / dropout.
- **Optional:** when the strategist is disabled, `TrainingLoop` degrades to a pure Optuna search over `base_spec` (no calls made here).
- The strategist **never trains or touches weights** — it only emits structured proposals.

## Notes
- Model/provider for the strategist follows project LLM conventions — default to the latest Claude model; **do not hardcode a model id**. All calls are logged (prompt, proposal, rationale) for reproducibility, distinct from the one-line investigation log.

## Verification
```bash
docker compose run --rm nn-train python3 -c "
from nn.nn_strategist import NNStrategist, Proposal

# stub history shaped like ExperimentTracker.summary()
history = {
    'incumbent': {'holdout_score': 0.70},
    'per_indicator': {'rsi': 0.01, 'vol_regime': 0.04},
    'per_target': {'dir_h1': 0.71},
    'recent': [{'trial_id': 't1', 'holdout_score': 0.68, 'status': 'ok'}],
    'n_trials': 5, 'n_rounds': 1,
}
search_config = {'lr': (1e-5, 1e-2), 'depth': (1, 6), 'units': (16, 256), 'dropout': (0.0, 0.5)}

s = NNStrategist(search_config=search_config)  # provider/model per project LLM conventions

# propose() returns a schema-valid Proposal; bounds clamped into search_config
p = s.propose(history)
assert isinstance(p, Proposal)
assert isinstance(p.indicators, list) and isinstance(p.timeframes, list)
assert isinstance(p.targets, list) and isinstance(p.search_space, dict)
assert isinstance(p.rationale, str) and p.rationale
lo, hi = p.search_space['lr']
assert search_config['lr'][0] <= lo <= hi <= search_config['lr'][1]

# review() returns an allowed verb
verb = s.review({'round': 1, 'best': 0.70, 'median': 0.66, 'failed': 1})
assert verb in {'continue', 'narrow', 'broaden', 'change_targets', 'stop'}, verb
print('OK')
"
```

## Commit
`feat(nn): NNStrategist LLM search steering (propose/review) with guardrails`
