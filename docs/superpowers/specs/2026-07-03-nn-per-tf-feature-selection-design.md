# NN per-TF feature selection — design

**Date:** 2026-07-03
**Status:** approved (brainstorm), pending implementation plan
**Area:** `nn/` module (Phase-11 spec-driven NN)

## Problem

The impl-A NN config carried a top-level `nn: feature_cols:` block — an explicit
per-timeframe list of exact `{tf}_{field}` columns fed to the NN. That block was
deleted (DECISIONS-LOG **D13**) because it fed only the orphaned
`DataAttributes.compute_nn_stats` (Pipeline A, no consumer after `NNPredictor`
removal). The feature **columns** were not deleted — every underlying field still
lives in `indicators_config.yaml` and materialises into `df_with_indicators.pkl`.

Audit (2026-07-03) confirmed full coverage: all 73 underlying fields from the
impl-A `feature_cols` spec are present in the current config, with **zero**
TF-coverage gaps across all 411 `{tf}_{field}` columns.

However, the current spec-driven path cannot *select* two families the way impl-A
did. The current path builds features as a **uniform Cartesian product**:

```python
# nn/nn_dataset.py — NNDataset.build (current)
for tf in spec.timeframes:
    feature_cols_by_tf[str(tf)] = [f"{tf}_{ind}" for ind in spec.indicators]
# then: any {tf}_{ind} missing from df.columns → ValueError
```

impl-A `feature_cols` was a **per-TF hand-picked** list, so it could place a
column at one TF only. Two families are TF-restricted and break under uniform
expansion (`feature columns missing`, `nn_dataset.py:441`):

- **cross-TF align ladder** — `align_5`→`[1]`, `align_15`→`[5]`, `align_60`→`[15]`,
  `align_240`→`[60]`, `align_1440`→`[240]`. Listing `align_60` with
  `timeframes: [15, 60]` tries to build `60_align_60`, which does not exist → crash.
- **cyclical time** — `sin_tod`/`cos_tod` have no `1440_` variant (daily bars share
  one wall-clock open → constant intraday time). Any spec including `tf=1440` → crash.

The impl-A per-TF difference is **entirely** driven by each field's `applies_to`
restriction, which is already declared in `indicators_config.yaml`. Reproducing
impl-A therefore reduces to making feature selection honor `applies_to` instead of
blindly crossing every indicator with every timeframe.

## Goal

Make NN feature selection per-TF-aware (ragged), so TF-restricted `nn_features`
train without crashing, and feature width derives from the **resolved** selection.

Non-goals (YAGNI): no spec schema change, no per-TF strategist proposals, no
revived `nn:` block, no per-feature `_z` columns (deleted per phase-11 task-03).

## Approach — `applies_to`-aware ragged selection

Keep the spec flat (`indicators: list[str]` + `timeframes: list[int]`). At dataset
build, emit `{tf}_{ind}` only when that column actually exists in `df`. The network's
first-layer width is computed from the **resolved** `feature_cols_by_tf`, never from
`len(indicators) × len(timeframes)`.

Rationale: the entire impl-A per-TF difference is `applies_to`-driven, and the
registry/materialised frame already holds that truth. Honoring it reproduces impl-A
exactly with the least code and no strategist/LLM/schema disruption. It also
generalizes to any future TF-restricted feature.

### Why width stays correct despite "omitted" columns

The tensor is already built per-TF from `feature_cols_by_tf[tf]` and concatenated
along the feature axis (`nn_dataset.py` `_materialise` 513-517, `build_matrix`
840-847). So the real tensor width already equals `sum(len(cols))`. The fix makes
the layer read from the same resolved list, so layer width == tensor width by
construction. Two visibility guards separate *width correctness* (guaranteed) from
*intent* (was the drop meant?):

- an indicator resolving at **zero** spec timeframes → hard error (real typo);
- dropped `(tf, ind)` pairs (present at some TF, absent at this one) → logged, not silent.

## Component changes (2 files)

### `nn/nn_dataset.py` — `NNDataset.build` (~434-450)

Replace the uniform product + hard missing-column error with ragged,
existence-driven selection:

```python
feature_cols_by_tf: dict[str, list[str]] = {}
dropped: list[tuple[int, str]] = []
for tf in spec.timeframes:
    cols = [f"{tf}_{ind}" for ind in spec.indicators if f"{tf}_{ind}" in df.columns]
    dropped += [(tf, ind) for ind in spec.indicators if f"{tf}_{ind}" not in df.columns]
    feature_cols_by_tf[str(tf)] = cols

# typo guard: every indicator must resolve at >= 1 timeframe
unresolved = [i for i in spec.indicators
              if not any(f"{tf}_{i}" in df.columns for tf in spec.timeframes)]
if unresolved:
    raise ValueError(f"indicators not found at any timeframe: {unresolved}")

# a timeframe with zero features is a spec error
empty = [tf for tf, cols in feature_cols_by_tf.items() if not cols]
if empty:
    raise ValueError(f"timeframes with zero features: {empty}")

# visibility: intentional per-TF drops are logged, never silent
if dropped:
    logger.info("NN feature selection dropped per-TF pairs (applies_to): %s", dropped)
```

Column order preserves `spec.indicators` order → deterministic dataset hash.

### `nn/nn_model.py` — width from resolved list, not spec arithmetic

- `_n_features` / `input_size` become `sum(len(cols) for cols in feature_cols_by_tf.values())`.
- Source at **train**: the dataset (available inside `train()` before `build()` runs).
- Source at **load/inference**: bundled `manifest["feature_cols"]` (`nn_model.py:691`),
  so a reloaded net is sized to exactly the trained width.
- `_SpecNet` unchanged (already takes `n_features`).
- Retire the `len(indicators) × len(timeframes)` sites: 286-288, 306-308, 700-701.

`input_size` is computed in `__init__` today but only *consumed* in `build()`, which
runs inside `train(dataset)` — so deriving it at build time from the dataset
introduces no ordering problem.

## Data flow (unchanged downstream — already ragged-safe)

```
build → feature_cols_by_tf (ragged)
      → _materialise: per-TF blocks → concat on feature axis
      → normalize per column (robust clip→z→clamp, train split only)
      → manifest.feature_cols (per-TF dict)
      → checkpoint bundle (feature_cols + normalization)
      → inference build_matrix: iterates manifest feature_cols per TF
```

`_dataset_hash` already folds `feature_cols_by_tf` (`nn_dataset.py:453`), so ragged
variants key distinctly in the tensor cache. Normalization is per-column and
group-agnostic (`nn_dataset.py:569-601`), so ragged selection needs no change there.

## Edge cases

| case | behaviour |
|---|---|
| indicator resolves at 0 TFs | `ValueError` (typo) |
| a timeframe resolves to 0 columns | `ValueError` (misconfigured TF) |
| `align_60` with `timeframes: [15, 60]` | keep `15_align_60`, drop `60_align_60` (logged) |
| `sin_tod`/`cos_tod` with `tf=1440` in spec | drop `1440_sin_tod`/`1440_cos_tod` (logged) |
| checkpoint round-trip | reload width from bundled `feature_cols` == trained width |
| ordering / determinism | `spec.indicators` order preserved → stable hash |

## Testing (verify in Docker per layer-first)

- **unit** — ragged spec (align/cyclical across multiple TFs) → per-TF counts
  correct; `input_size == sum(per-TF counts) * history_points`; model builds and a
  forward pass produces the expected output shape.
- **unit** — typo indicator → `ValueError`; empty-TF spec → `ValueError`.
- **unit** — checkpoint round-trip preserves ragged `feature_cols` and rebuilds a
  same-width net (load path reads bundled `feature_cols`, not spec arithmetic).
- **integration (Docker)** — `nn_spec.yaml` listing an align rung + `sin_tod` with
  `timeframes` including `1440` → training runs end-to-end, no `feature columns
  missing` crash.

## Config follow-on (separate task, optional)

Once the mechanism lands, `nn_spec.yaml indicators:` can list the TF-restricted
names (align ladder, cyclical) and, if desired, the full impl-A feature set — the
selector now drops the non-applicable `(tf, ind)` pairs instead of crashing.

## References

- impl-A `feature_cols` full spec: `plans/impl_2/phase-11-nn-module/task-03-nn-features.md`
- D13 removal of the `nn:` block: `plans/impl_2/phase-11-nn-module/DECISIONS-LOG.md`,
  `plans/impl_2/phase-00-infrastructure/task-03-config-yaml-files.md`
- current selection + width coupling: `nn/nn_dataset.py` (434-450, 500-614, 804-847),
  `nn/nn_model.py` (283-323, 691-713)
