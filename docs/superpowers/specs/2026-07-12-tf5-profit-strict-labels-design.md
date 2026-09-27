# TF5 profit_strict NN labels — design

**Date:** 2026-07-12
**Base branch:** `nn-features-profit-strict-v4` (holds the existing 12 `ps{15,60,240}` specs + config)
**Status:** approved, ready for planning

## Goal

Add 4 new NN label heads mirroring the existing 15-minute strict targets, but on
the **5-minute** timeframe: `ps5` × horizon {n1, n2} × side {long, short},
**strict variant only**. Params copied verbatim from the TF15 strict targets.

## Context

The existing strict-target system (branch `nn-features-profit-strict-v4`):

- `configs/indicators_config.yaml` `labels:` block materializes
  `{tf}_pslong_...` / `{tf}_psshort_...` columns into the wide dataframe during
  data prep, via `indicators/labels.py::add_profit_strict_labels`.
- `nn_dataset.py` builds each label column **name** from the spec
  (`{label_tf}_{pslong|psshort}_n{n}_m{m}_x{x}_l{l}_y{y}`) and **reads the
  precomputed column** from the wide df at tensor-build time.
- `scripts/nn_pstrict_batch.py` globs `configs/nn_specs/profit_strict/*.yaml`
  (12 specs today) and single-trains one model per spec.

Param pattern across current TFs (`l=15`, `m=1` constant; only `x`/`y` vary):
TF15 → x0.3 y0.2 · TF60 → x0.2 y0.1 · TF240 → x0.1 y0.1.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| TF5 strict params | **mirror TF15**: m1, x0.3, l15, y0.2 | request was "similar to 15 min strict" |
| Materialization | **append-columns script** (not full re-prep) | full 2y re-prep OOMs 15GB host (memory); append is minutes, low risk |
| Scope / DoD | **specs + columns + tests only** | training/inference/frontend are separate manual runs |

## Column names (contract)

The materializer writes and the specs read the **same** names byte-for-byte
(`_fmt`: `1.0`→`1`, `0.3`→`0p3`, `0.2`→`0p2`):

```
5_pslong_n1_m1_x0p3_l15_y0p2    5_psshort_n1_m1_x0p3_l15_y0p2
5_pslong_n2_m1_x0p3_l15_y0p2    5_psshort_n2_m1_x0p3_l15_y0p2
```

## Changes (4 sites)

### 1. Specs — 4 new yamls `configs/nn_specs/profit_strict/ps5_n{1,2}_{long,short}.yaml`

Copy the matching `ps15_*` file. Change **only**:
- `name:` → `nnfo_ps5_n{1,2}_{long,short}`
- target `name:` → `ps5_n{1,2}_{long,short}`
- target `label_tf: 15` → `5`

Everything else (side, horizon, `label_m 1.0`, `label_x 0.3`, `label_l 15`,
`label_y 0.2`, backbone, feature list, timeframes) is already correct in the
respective TF15 source file — TF15 params **are** the target params.

### 2. `configs/indicators_config.yaml` — 2 new `profit_strict` entries

`tfs:[5]`, one `n:1` and one `n:2`, each `m:1  x:0.3  l:15  y:0.2`.
**No `profit` (non-strict) TF5 entries** — request is strict only.

### 3. NEW `scripts/nn_ps5_materialize.py` — append-columns materializer

- Loads the exact pickle `nn_dataset`/batch driver reads (`wide_df_path()` under
  the active env — implementer confirms this is the same file at build time).
- Calls `add_profit_strict_labels(df, 5, n=1, m=1, x=0.3, l=15, y=0.2)` and
  `n=2`, saves in place.
- **Idempotent**: skip when target columns already present.
- Run once per env: 2y train dataset, then oos2m. Runs inside nn-train container.

### 4. `scripts/nn_pstrict_batch.py` — docstring/comments only

"12 profit_strict models / TF 15/60/240 / 12-head" → "16 / TF 5/15/60/240 /
16-head". Glob logic unchanged (auto-picks the new specs).

## Tests

- **Spec→column contract**: each of the 4 new specs loads via
  `NNModelSpec.from_yaml` and resolves to the exact TF5 column name above.
- **Materializer**: adds the expected columns to a synthetic wide df; idempotent
  on re-run (no dup columns, no error).
- Label math for `tf=5` is already covered by
  `tests/test_phase13_task01_profit_labels.py` (existing `tf=5` case) — no new
  math test.

## Why safe

- New specs get **fresh per-spec-hash tensor datasets** — no stale tensor-cache
  risk for the 4 new heads.
- Appending columns to the wide df is sufficient because `nn_dataset` reads
  labels from the wide df at build time.
- **Two-scorer** concern (train `_accuracy_counts` vs holdout
  `_score_predictions`) does **not** apply: same target `kind: label`, not a new
  target kind.

## Out of scope

Training, inference, viewer/frontend wiring, and `profit` (non-strict) TF5
labels. Training + inference are a later manual run of the batch driver once
columns are materialized.
