# Architecture is reasoned, not searched

Layer architecture (which layer kinds, in what order, what each layer represents in
real-data terms) is decided by reasoning agents — Tier-0 investigation for v1, Tier-2
evolution for later versions — and never sampled by Optuna. Optuna tunes only numeric
knobs (learning rate, layer width, layer count, dropout) *within* the already-chosen,
declared architecture. New layer kinds (e.g. attention) are added to the engine on demand
via TDD before an archetype that needs them is trained.

## Considered options

- **Let Optuna sample architecture too (NAS-style).** Rejected: stock data is extreme
  low signal-to-noise; sampling many architectures and picking the best holdout score
  reliably selects a model that fits holdout *noise*, not signal. Architecture search pays
  off on high-SNR data (vision), not here. It also produces models with no recorded "why",
  defeating the investigation/report requirement.
- **Extend the in-loop NNStrategist to also emit layers.** Rejected as the primary
  mechanism: keeps reasoning as throwaway JSON strings, no per-layer real-data
  justification, no version lineage or reports.

## Consequences

- `build_spec` in [training_loop.py](../../../../../../main/nn/training_loop.py) must stop
  overwriting `spec.layers` with a dense-only stack (line ~391). It must keep the declared
  layers' **kinds, count, and params**, and let Optuna tune only **width (units, applied to
  the declared layers), learning_rate, and dropout**. Layer *count* is architecture (a
  Tier-2 structural change → new version), so `depth` is removed from the Optuna search
  space.
- The orchestration skill-set is allowed to modify engine code (add `LayerSpec` kinds +
  builder branches in `nn_model.py`), gated by tests, following layer-first-planning + tdd.
