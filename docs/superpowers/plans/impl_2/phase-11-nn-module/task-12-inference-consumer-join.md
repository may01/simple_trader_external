# Task 12: Inference Path — Remove NNPredictor, Consumer Left-Join

**Phase:** 11 — NN Module
**Depends on:** Task 08 (`run_inference` → `{dataset}/df_with_nn.pkl`), Task 11 (Trainer `infer_nn` wiring that writes it); and the `DataPoint.get(col, tf, shift=0, default=_MISSING)` absence-safe contract from `data-class.md` §2 (the `nn_res_*` access layer — owned by the data-module tasks, assumed present here).
**Produces:** deletion of `NNPredictor` + its live call site; a `join_nn_results()` left-join of `df_with_nn.pkl` applied in `SimulationData` / `FullData` / `LiveData` at construction.
**Replaces:** the old `task-02-nn-predictor.md` (NNPredictor is removed, not built).

---

## Goal

Retire the per-tick `NNPredictor` entirely and make every data consumer read NN outputs as
ordinary, precomputed indicator columns. NN results reach strategies through a single batch
artifact — `{dataset}/df_with_nn.pkl` (produced by `NNOrchestrator.run_inference` / `Trainer.infer_nn`,
Tasks 08/11) — left-joined onto the consumer's frame at construction time. After this task the
prediction/strategy stage imports no NN class, no checkpoint, and no PyTorch.

## Context

<MIGRATION: the per-tick `NNPredictor` is removed entirely; inference is batch-only.
`LiveData.build_candles()` no longer calls `predictor.compute(point, tf)`; `LiveData.__init__`
no longer takes/constructs an `nn_predictor`. Instead `SimulationData`, `FullData`, and `LiveData`
LEFT-JOIN `{dataset}/df_with_nn.pkl` (timeframe-agnostic `nn_res_*` columns) onto their frame on
the 1-min `DatetimeIndex`. Strategies read those columns via `data_point.get(col, tf, default=…)`
with no knowledge of models/checkpoints.>

Rationale (from `nnpredictor-class.md` §2 and `nn-module.md` §6):

1. **Live/backtest parity.** Per-tick inference risked normalisation-timing / warmup / feature-availability
   skew versus the batch path. Computing `nn_res_*` once in batch and consuming identical columns in
   both live and backtest makes parity *structural* — both read a `df_with_nn.pkl` produced by the same
   `run_inference`.
2. **Decoupling.** Strategies treat `nn_res_*` as just-another-indicator. The strategy stage loses its
   runtime dependency on `NNModel`/checkpoints/PyTorch and a whole class of live-only failures.
3. **Cost / latency.** Single-sample inference per tick per TF is wasteful and on the hot path; batch
   inference over the prepared frame is far cheaper and runs offline.

NN result columns carry **no `{tf}` prefix** (one set per row, shared across all timeframes); the join
is on the 1-min index, and the columns are determined by the model's `TargetSpec` list
(`nnmodel-class.md` §6) — adding a target adds columns without touching strategy code.

## Files

- **Delete:** `nn/nn_predictor.py` (the `NNPredictor` class + `NNPredictor.load` classmethod, the
  module-level `_warned_missing_columns` warning set, and the `DataPoint` Protocol stub it carries).
- **Delete:** `tests/unit/nn/test_nn_predictor.py` (all 14 tests — they exercise the removed class).
- **Modify:** `data.py`
  - `LiveData.__init__` (currently `def __init__(self, nn_predictor=None)`, `data.py:249`): drop the
    `nn_predictor` parameter and `self.nn_predictor = nn_predictor` (`data.py:255`).
  - `LiveData.build_candles` (`data.py:258`): remove the second-pass block at `data.py:300-303`
    (`if self.nn_predictor is not None: … self.nn_predictor.compute(point, tf)`) and the `points` /
    comment scaffolding (`data.py:265-267`, `:297-298`) that existed only to feed that pass.
  - Add the `join_nn_results()` helper (module-level in `data.py`) and call it in the three consumers
    (below). No new `NNModel`/`CheckpointManager` import is introduced into `data.py`.
- **Verify-only (callers, expect no edits):** `trader.py:74` (`live_data = LiveData()`) and
  `scripts/tail_live_actions.py:80` already construct `LiveData()` with no predictor arg, so dropping
  the parameter is backward-compatible. `FullData(df)` callers (`view_full.py:12`, viewer tests) pass a
  pre-built df — see the FullData note in **Interface**.

## Interface

### New helper — `join_nn_results`

```python
def join_nn_results(df: pd.DataFrame, dataset_dir: str) -> pd.DataFrame:
    """LEFT-JOIN {dataset_dir}/df_with_nn.pkl (timeframe-agnostic nn_res_* columns)
    onto df on the shared 1-min DatetimeIndex, and return the joined frame.

    Absence-safe: if df_with_nn.pkl does not exist, returns df unchanged (no-op);
    the nn_res_* columns simply do not appear. Only nn_res_* columns are taken
    from the pickle (it is NN-columns-only by construction, but the join must not
    overwrite existing df columns). Does NOT mutate df_with_indicators.pkl on disk.
    """
```

- Join is on the index (1-min `DatetimeIndex`), `how="left"`, keeping every original row.
- `nn_res_*` columns are timeframe-agnostic — joined once, read for any `tf`.
- Re-running `prepare()` never sees these columns (single-writer, below); re-running inference
  overwrites only `df_with_nn.pkl`.

### Consumer wiring (join at construction)

- **`SimulationData.__init__`** (`data.py:345`): after `self._df = pd.read_pickle(path)` (`data.py:360`),
  apply `self._df = join_nn_results(self._df, <dataset dir for pair>)`. The dataset dir is the directory
  containing `df_with_indicators.pkl` — derive it from `_wide_df_path_for_pair(pair)` (`data.py:325`)
  via `os.path.dirname(...)`. `WideDataPoint` then resolves `nn_res_*` against the bare column name.
- **`LiveData`** (`data.py:241`): in `build_candles`, after assembling/enriching `self.ohlc`, left-join
  the `nn_res_*` columns produced for the live dataset onto the per-tf frames (the live window is "just
  another dataset"; per `nnpredictor-class.md` §6 the live path MUST reuse the same `run_inference`
  batch artifact, never a per-tick predictor). If `df_with_nn.pkl` is absent, no-op. Cadence of when the
  live artifact is (re)produced is a LiveData concern, out of scope here; this task only adds the
  absence-safe consumer-side join and removes the per-tick path.
- **`FullData`** (`data.py:438`): `FullData.__init__(self, df)` takes a pre-built frame, so the join must
  be applied to the df *before* `FullData(df)` is constructed — at the call sites that build the viewer
  frame (`view_full.py` / `get_stock_data` path, `data.py:484`) — OR `FullData` is given the dataset dir
  and joins internally. Per `data-class.md` §8 `FullData.get(tf)` must return columns
  `c.startswith(f"{tf}_") or c.startswith("nn_res_")`; ensure the joined `nn_res_*` columns survive the
  per-tf column filter (the §8 reference shows the corrected filter). Pick one wiring and keep
  `FullData` itself a thin view.

### REMOVED surface (must not reappear in the prediction/strategy stage)

- `NNPredictor` class and `nn/nn_predictor.py` per-tick path.
- `NNPredictor.load(...)`, the `_warned_missing_columns` warning set.
- `LiveData(nn_predictor=…)` parameter and `self.nn_predictor`.
- The `predictor.compute(point, tf)` second-pass loop in `LiveData.build_candles` (`data.py:300-303`).
- Any live-path import of `NNModel` / `CheckpointManager` / checkpoints.
- (Also retired per spec §5: the legacy Gaussian price-level `Predictor`; price-level prediction, if
  revived, returns as a regression `TargetSpec` through this same batch indicator path.)

## Key Constraints

- `df_with_indicators.pkl` stays **single-writer** (DataPreparer). The NN merge is a **consumer-side
  join**, NOT a `prepare()` step — `df_with_nn.pkl` is an additive, disposable artifact.
- **Absence of `df_with_nn.pkl` is a no-op.** Construction must still succeed; the `nn_res_*` columns are
  simply absent and reads return the caller's default via `DataPoint.get(col, tf, default=…)` — identical
  to any other missing indicator. No checkpoint present ⇒ no pickle ⇒ no columns ⇒ no crash.
- **No live-path import of `NNModel`/checkpoints remains** anywhere reachable from the strategy stage.
- `nn_res_*` are **timeframe-agnostic** columns (no `{tf}` prefix), joined on the 1-min index, read like
  ordinary indicators for any `tf`.
- Live path reuses the batch `run_inference` artifact for parity — it MUST NOT reintroduce a divergent
  per-tick computation.

## Verification

```bash
# 1) After infer_nn produced df_with_nn.pkl, a consumer surfaces nn_res_* columns;
#    renaming the pkl away still lets construction succeed with the columns absent.
docker compose run --rm trainer python3 -c "
import os, glob, pandas as pd
from data import SimulationData, _wide_df_path_for_pair
pair = os.environ['PAIR']
d = os.path.dirname(_wide_df_path_for_pair(pair))
nn = os.path.join(d, 'df_with_nn.pkl')
assert os.path.exists(nn), 'run infer_nn first (Task 08/11)'
# present: nn_res_* columns appear after the consumer-side join
sim = SimulationData(pair, BEGIN_TS, END_TS, step_min=1)   # fill in window from env
assert any(c.startswith('nn_res_') for c in sim._df.columns), 'nn_res_* missing after join'
# absent: rename the pkl away, construction must still succeed, columns gone
os.rename(nn, nn + '.bak')
try:
    sim2 = SimulationData(pair, BEGIN_TS, END_TS, step_min=1)
    assert not any(c.startswith('nn_res_') for c in sim2._df.columns)
    print('OK: present-and-absent both handled')
finally:
    os.rename(nn + '.bak', nn)
"

# 2) No live/strategy reference to the removed predictor remains.
grep -rn "NNPredictor\|nn_predictor" main/ --include=*.py   # expect: no matches

# 3) Single-writer invariant: infer / consumer-join never rewrites df_with_indicators.pkl.
#    (df_with_indicators.pkl mtime unchanged after constructing a consumer.)
```

Additional checks:
- `test_nn_predictor.py` is deleted; the unit suite collects with no import error for `nn.nn_predictor`.
- `LiveData()` constructs with no arguments (existing callers `trader.py:74`,
  `scripts/tail_live_actions.py:80` unchanged).
- `FullData.get(tf)` returns `nn_res_*` columns when the joined df carries them (per `data-class.md` §8).

## Commit

`refactor(nn): remove per-tick NNPredictor; left-join df_with_nn.pkl in consumers`
