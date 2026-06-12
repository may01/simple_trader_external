# Task 03: cci_diff Field, Sided diff_prc Stats, indicator_stats.json

**Phase:** 13 — Indicator Warmup (continuation: indicator/attribute additions)
**Depends on:** Phase 03/04 (indicator framework + library), Task 02
**Produces:** `cci_diff` oscillator field; new semantics for `*_mean_above/_mean_below/_std_above/_std_below`; new `indicator_stats.json` attribute file
**Branch:** `indicator-additions` (off `experimental_imp_2`), worktree `worktrees/indicator-additions`.

---

## Goal

1. New indicator `cci_diff` = 1-step diff of `cci_14_ma_20` (oscillators, all TFs).
2. Re-define price_derivatives sided fields (per source close/high/low, window 20):
   - `{src}_diff_prc_rm_20_mean_above` — mean of the window's `diff_prc` values that
     are **above** the window mean (`rm_20`); `_mean_below` — mean of values below it.
   - `{src}_diff_prc_rm_20_std_above` / `_std_below` — std (ddof=1) of those same
     subsets. (Previously: one-signed mean of the rm series / rm ± std band.)
   - Empty subset → 0.0; single value → std 0.0. Column names unchanged.
3. New stats file `indicator_stats.json` in `stats_folder()` (idempotent, like the
   existing two), per TF [15, 60, 240, 1440] over closed candles:
   - `rsi_14_minus_rsi_ma8`: mean + std of `{tf}_rsi_14 − {tf}_rsi_ma8`
   - `cci_diff`: mean + std of `{tf}_cci_diff`
   - `vol_minus_vol_ma_20`: mean + std of `{tf}_volume − {tf}_vol_ma_20`
   - Loader `DataAttributes.load_indicator_stats()`.

## Files

- `indicators/library/oscillators.py` — `CCIDiffField`
- `indicators/library/price_derivatives.py` — rewrite `_DiffPrcRMMeanSideBase`,
  `_DiffPrcRMStdSideBase` compute()
- `indicators/registry.py` — `cci_diff` entry
- `configs/indicators_config.yaml` — `cci_diff` field; sided fields depend on
  `{src}_diff_prc` (not the rm column)
- `indicators/attributes.py` — `_compute_indicator_stats` + loader, called from `compute()`

## Interface

```python
class CCIDiffField(IndicatorField):       # name="cci_diff", deps=["cci_14_ma_20"]
    def compute(self, data_point, tf: int) -> pd.Series: ...

class DataAttributes:
    @classmethod
    def load_indicator_stats(cls) -> dict: ...
```

`indicator_stats.json` schema:
`{"15": {"rsi_14_minus_rsi_ma8": {"mean", "std"}, "cci_diff": {...}, "vol_minus_vol_ma_20": {...}}, ...}`

## Key Constraints

- `cci_diff` computed in the base oscillators pass → available when
  `_compute_base_attributes` (DataPreparer step 4) runs.
- DataAttributes.compute() runs on the untrimmed frame; warmup rows hold NaN
  indicators and are dropped via `.dropna()` before stats.
- Sided-field invariants change: `mean_above` ≥ rm value (not ≥ 0); existing
  sign-based tests must be replaced.

## Verification

- Unit: exact-value tests for sided mean/std on deterministic windows;
  cci_diff equals `cci_14_ma_20.diff()`; registry/config wiring (sorted fields
  include cci_diff); indicator_stats.json content, idempotence, loader,
  missing-file raise.
- Full suite green in Docker.

## Commit

`feat: cci_diff field, sided diff_prc mean/std semantics, indicator_stats.json`
