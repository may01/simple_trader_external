# NN Training Orchestration

The skill-driven layer that designs candidate neural-network models for stock-price
prediction, drives their training, and evolves them version-by-version. It sits *above*
the existing in-code training machinery (`TrainingLoop`, Optuna, `NNStrategist`,
`ExperimentTracker`) and adds the reasoning, reporting, and lineage that the code loop
does not have.

## Language

### Model design

**Archetype**:
An architecture family defined by a single design thesis — e.g. `recurrent-temporal`
(LSTM/GRU over the history window), `conv-local` (Conv1d over the window),
`mlp-snapshot` (dense over a flattened snapshot), `attention-crosstf` (attention across
timeframes — needs new code). Each archetype gets exactly one Tier-0 investigation and
one description document.
_Avoid_: model type, model kind, network family.

**Version**:
A concrete `NNModelSpec` within one archetype's lineage, numbered v1 → v2 → v3. A new
version is born from the previous version's report. Previous versions are never mutated.
_Avoid_: iteration, revision, generation.

**Lineage**:
The ordered version chain for one archetype. Each archetype owns an independent lineage;
there is no global cross-archetype version line.
_Avoid_: history, branch, family tree.

**Trial**:
One Optuna sample inside a single version's hyperparameter search — the existing code
unit, recorded in `ExperimentTracker`. A version contains many trials.
_Avoid_: run, attempt, experiment.

**Spec**:
The `NNModelSpec` dataclass instance ([nn_model_spec.py](../../../../../../main/nn/nn_model_spec.py))
— the full declarative definition of a Version (indicators, timeframes, layers, targets,
learning params). Content-hashed to `spec_hash`, which keys checkpoints and tensor caches.
_Avoid_: config, model definition, params.

### The three tiers

**Tier 0a — Meta-investigation**:
The one-off reasoning stage that proposes the *list* of archetypes to pursue (with
rationale and a buildable-now flag), reading the allowed indicators / timeframes / targets
from the existing config as its vocabulary. Emits `meta-investigation.md`.
_Avoid_: survey, scoping.

**Tier 0b — Investigation**:
The offline, per-archetype reasoning stage. One agent reasons about which indicators and
targets to use and *why*, and what each layer represents in real-data terms, then emits a
v1 Spec plus a description document. No training, no Optuna.
_Avoid_: research, design phase, planning.

**Tier 1 — Hyperparameter search**:
The existing in-code `TrainingLoop`: Optuna samples numeric knobs (learning rate, layer
width, layer count, dropout) *within one Version's fixed architecture*, trains each Trial,
and gates promotion on the holdout. This is the **only** tier where Optuna operates.
_Avoid_: tuning, the loop, optimisation.

**Tier 2 — Architectural evolution**:
The outer skill loop. It reads a Version's report, reasons about a structural change (add
a layer, widen the history window, swap a target), writes the next Version's Spec, re-runs
Tier 1, and compares. Architecture is decided here by reasoning, never sampled by Optuna.
_Avoid_: the improve loop, the meta loop.

### Evaluation

**Promotion gate**:
The decision that makes a Version (or Trial) the new incumbent or reverts to the previous
one. Current metric: **holdout accuracy + loss**. Backtest P&L is deliberately deferred to
a later model-combination / signal-identification phase.
_Avoid_: selection, the gate, scoring.

**Holdout**:
The time-ordered tail split untouched by training and by Optuna pruning — the surface on
which the promotion gate is computed. Distinct from the validation split used for early
stopping.
_Avoid_: test set, validation, out-of-sample.

**Scope**:
The structural choices the in-code `NNStrategist` may nudge per round — which indicators,
timeframes, and targets are in play — as opposed to the numeric knobs Optuna samples.
_Avoid_: search space (that term is reserved for Optuna's numeric bounds).

**Strike**:
One failed Version — a v(n+1) that did not beat its lineage's current best on the
promotion gate. Tier-2 reverts to the best and tries a *different* structural change. The
lineage stops after K consecutive strikes (default K=2), a max-version ceiling, or a
per-archetype time budget — whichever comes first.
_Avoid_: miss, failure, regression.

## Flagged ambiguities

- **"Model"** alone is ambiguous: it may mean an Archetype, a Version, a Spec, or the
  trained `NNModel` weights. Always qualify.
- **"Better"** means *higher holdout accuracy / lower loss* for now — **not** more
  profitable. The per-class accuracy + confusion breakdown is recorded in every report so
  a degenerate "always-neutral" winner is visible even though the gate does not block it.

## Example dialogue

> **Dev:** The conv-local archetype's v2 beat v1, so I promoted it.
> **Expert:** Promoted on what — the holdout gate, or a single Optuna trial?
> **Dev:** The version's best trial holdout accuracy was higher.
> **Expert:** Good. But check the per-class breakdown in v2's report before you start the
> v3 investigation — if up/down recall is near zero it's just predicting neutral, and
> v3's Tier-2 reasoning should target that, not the layer width.
