# Task 02: Warmup Rows as Input Only — Trim Before Save

**Phase:** 13 — Indicator Warmup
**Depends on:** Task 01 (warmup-extended grab range)
**Produces:** `DataPreparer.prepare(raw_data_path, data_start_ms)` — indicator passes restricted to ts ≥ DATA_START, warmup rows dropped before saving `df_with_indicators.pkl`
**Branch:** `warmup-trim` (off `experimental_imp_2`), worktree `worktrees/warmup-trim`.

---

## Goal

Warmup history (Task 01) must serve only as *input* for indicator computation.
No indicator is computed for any WideDataPoint timestamp before DATA_START, and
all rows before DATA_START are dropped before `df_with_indicators.pkl` is saved.

## Context

Task 01 extended the grab range ~105 days back. Without this task, DataPreparer's
per-row indicator pass would also iterate those ~151k warmup 1-min rows (wasted
compute) and the saved frame would contain pre-DATA_START rows the simulation
never requests. Warmup rows still must be present *during* the pass so
`build_indicator_input` slices see full lookback history at DATA_START.

Row independence holds: per-row results are collected in lists and written to the
frame only after the loop, so slices never read other rows' computed indicator
values — restricting the iteration range is safe.

## Files

- `training/data_preparer.py` — `prepare()` gains `data_start_ms`;
  `_compute_base_indicators` / `_compute_class_indicators` /
  `_run_indicator_pass` gain `start_ts`; trim after class indicators
  (before NN merge / NN stats / save).
- `training/trainer.py` — `_run_prepare_data` passes
  `data_start_ms=int(os.environ["DATA_START"])`.

## Interface

```python
class DataPreparer:
    def prepare(self, raw_data_path: str, data_start_ms: int | None = None) -> None: ...
    def _compute_base_indicators(self, df: pd.DataFrame, start_ts: pd.Timestamp | None = None) -> None: ...
    def _compute_class_indicators(self, df: pd.DataFrame, start_ts: pd.Timestamp | None = None) -> None: ...
    def _run_indicator_pass(self, df, groups, tfs, start_ts: pd.Timestamp | None = None) -> None: ...
```

`data_start_ms=None` keeps the old full-range behavior (compute everything,
trim nothing) — used by unit fixtures without warmup.

## Key Constraints

- Trim happens after the class-indicator pass and before NN merge / NN stats /
  save, so classification fields still see warmup lookback but saved frame and
  NN normalization stats cover only [DATA_START, DATA_END].
- Base attributes (step 4) run on the untrimmed frame; warmup rows carry NaN
  indicators there and quantile/stat computations ignore NaN.
- Targets (forward-looking) unaffected: they read future rows inside the range.

## Verification

- Unit: `_run_indicator_pass(start_ts=...)` iterates only ts ≥ start_ts; rows
  before start_ts keep NaN in indicator columns.
- Unit: `prepare(..., data_start_ms=...)` saves a frame whose index starts at
  the first ts ≥ DATA_START.
- Unit: trainer passes `data_start_ms` from env to `prepare()`.
- Integration: warmup fixture → non-NaN indicators at DATA_START, NaN/absent
  before it, saved frame trimmed.
- Full suite green in Docker.

## Commit

`feat: compute indicators only from DATA_START, drop warmup rows before save`
