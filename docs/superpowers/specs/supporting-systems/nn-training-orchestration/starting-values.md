# Starting values (calibrate after archetype #1)

Locked defaults for the first real run. All are estimates grounded in the 4 GB RTX 3050 Ti
+ 2y `link_usdt` dataset + low-SNR financial data; revisit after the first lineage.

## Per-training (one model fit)

| Value | Setting | Why |
|---|---|---|
| `batch_size` | **128** dense/conv, **64** recurrent | 128 feeds the 4 GB GPU well for small dense/conv models with mild gradient-noise regularization; recurrent activations scale with `history × batch`, so drop to 64. OOM→CPU retry is the safety net. Per-spec, not Optuna-searched. |
| `epochs` | **50** (ceiling) | Generous cap early-stop rarely reaches; financial models overfit within tens of epochs. |
| `early_stopping_patience` | **8** (val_loss) | Room to find signal without wasting GPU on a dead trial; MedianPruner also kills weak trials mid-training, so patience needn't protect them. |

## Per-version (one Optuna search)

| Value | Setting | Why |
|---|---|---|
| `trials_per_round` | **8** | Numeric search over lr/depth/units/dropout. |
| `n_startup_trials` | **4** (new config) | TPESampler defaults to 10 random before TPE engages; lowering to 4 gives 4 random + 4 TPE-guided in an 8-trial round instead of pure random. **Requires exposing the sampler param.** |
| `max_rounds` | **1** | Scope + architecture are fixed per version by Tier-0/2, so re-scoping rounds would break Version immutability; one larger study beats several fresh small ones for numeric search. |
| in-loop `NNStrategist` | **OFF** | All reasoning lives in Tier-0/2 agents (see ADR-0001). |
| `max_wall_clock_s` | **3600** (1 h/version) | Existing 1800 s is too tight for 8 recurrent trials and would cut a search mid-way. |

→ **~8 trainings per version.**

## Per-lineage (one archetype)

| Value | Setting | Why |
|---|---|---|
| `K` (strikes) | **2** | A single failure is usually a bad hypothesis, not a dead archetype; a second independent attempt is cheap insurance; beyond 2 the yield drops. |
| `max_versions` | **6** (v1 + 5) | Backstop past the typical v2–v4 plateau; rarely reached given K + margin + time budget. |
| `margin` | **0.01** (1 pp holdout acc) | ~2× sampling-noise std on the 2y holdout (σ≈0.004); promotes only credible gains, not seed luck. Without it (margin=0) noise drifts a lineage to max_versions. |
| per-archetype time budget | **8 h** (checked at version boundaries) | Covers a full v1+5 lineage at recurrent speeds; releases the GPU within ~a workday if stuck. |

## Compute envelope (sanity check)

- Version ≈ 8 trainings ≈ 25 min (dense) – 60 min (recurrent).
- Lineage ≈ 3–6 h typical, ≤ 8 h capped.
- With ~4–5 archetypes from Tier-0a, sequential on one GPU → **~30–40 h total GPU**, i.e. a few days of unattended-per-archetype running with human gates between archetypes.

## Coupled code changes these imply

1. `build_spec` must respect declared layer kinds (ADR-0001).
2. `NN_SPEC_PATH` env override (read spec from artefact volume).
3. Expose `n_startup_trials` in `nn_search.yaml` → `TPESampler`.
4. Raise `max_wall_clock_s` default to 3600.
5. New `LayerSpec` kinds added on demand (TDD) for code-needing archetypes.
