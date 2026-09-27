# Phase 17 — Decisions Log

Resolved during the grill-with-docs session that produced the spec. Pointers, not re-derivations — see CONTEXT.md + ADRs for full reasoning.

## Design decisions (grilling)

| # | Decision | Source |
|---|---|---|
| D1 | Skill-set + loop driver sits ABOVE the existing code loop; reasoning/reports in agents, numeric search in code. | CONTEXT.md tiers |
| D2 | Architecture is AI-reasoned (Tier 0/2), Optuna numeric-only; `build_spec` respects declared layers. | ADR-0001 |
| D3 | Promotion gate = holdout accuracy + loss; P&L deferred; per-class + confusion recorded. | ADR-0002 |
| D4 | Per-archetype lineage; vocabulary Archetype / Version / Trial / Lineage. | CONTEXT.md |
| D5 | Gate per archetype (autonomous within a lineage, stop between archetypes). | CONTEXT.md |
| D6 | Failure → revert + try another way; K=2 strikes, bounded by max_versions + time budget. | CONTEXT.md "Strike" |
| D7 | Archetype list AI-generated (Tier 0a); new layer kinds built on demand via TDD. | README extension recipe |
| D8 | Iterate on 2y `link_usdt`; re-validate winner on 4y. | starting-values.md |
| D9 | Spec on artefact volume (`specs/{spec_hash}/spec.yaml`), docs external; trainer reads via `NN_SPEC_PATH`. | Global Constraints |
| D10 | Reports = machine frontmatter + prose; loop driver reads decisions from frontmatter. | report.py contract |

## Things already wired (no code needed — verified in source)

- `margin` is already read from `nn_search.yaml` and passed to `ExperimentTracker` ([trainer.py:343](../../../../../main/training/trainer.py)). → config-only change.
- In-loop `NNStrategist` is already OFF by default ([trainer.py:352](../../../../../main/training/trainer.py)); leave `NN_STRATEGIST` unset. → no code.
- `_SpecNet` already builds dense/lstm/gru/conv1d + mixed architectures ([nn_model.py:164](../../../../../main/nn/nn_model.py)). The dense-only restriction lives ONLY in `build_spec`. → T02 is the whole fix.
- `max_wall_clock_s`, `max_rounds`, `trials_per_round` already env/config-driven. → config-only.

## Engine extension recipe (adding a LayerSpec kind on demand)

When a Tier-0a/0b archetype needs a kind the engine can't build (e.g. `attention`):
1. Branch per task; write a failing unit test: build `_SpecNet` from a spec with `LayerSpec(kind="attention", units=..., params={...})`, assert forward produces `(B, n_heads_width)` and no error.
2. Add a builder block in `_add_layer` ([nn_model.py:219](../../../../../main/nn/nn_model.py)) for the new kind (e.g. wrap `nn.MultiheadAttention` in a block that collapses the time dim, returning `(out_dim, seq_collapsed=True)`).
3. If the kind is sequence-aware, ensure `sequence_mode` detection at [nn_model.py:180](../../../../../main/nn/nn_model.py) includes it.
4. Green the test in the `nn-train` image. Document the kind in `LayerSpec`'s docstring.
5. Only then may an archetype spec declare that kind.

VRAM note: attention/transformer kinds are tight on the 4 GB GPU — keep `units`/heads small; the OOM→CPU retry is the safety net.

## Open calibration items (after archetype #1)

- Re-time per-training wall-clock on real 2y data; adjust `max_wall_clock_s` / per-archetype budget if estimates were off.
- Reconsider `n_startup_trials` vs `trials_per_round` once TPE behaviour on the holdout is observed.
