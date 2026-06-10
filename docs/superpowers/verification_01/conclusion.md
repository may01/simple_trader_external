# Verification 01 — Conclusion

**Date:** 2026-06-10
**Branch verified:** `experimental_imp_2` (97 commits ahead of `main`, +30,301 / −57 lines, 143 files)
**Plan verified against:** `external/docs/superpowers/plans/impl_2/` (phases 00–12) and `external/docs/superpowers/specs/`
**Method:** Runtime observation at the Docker surfaces the plan defines. The project image does not build, so real scripts were driven inside a workaround image (`python:3.12-slim` + equivalent deps) with the project code mounted at `/code`, the real `simple_trader_vol` / `simple_trader_vol_long` volumes, and the real Binance API.

## Verdict: FAIL

The plan claims phases 00–12 complete with the gate "Integration boundary must be GREEN in Docker before proceeding to next phase." Runtime reality: exactly one path works end-to-end (Path A, graber). Every other path is behind an unbuildable image, stub entry points, and a chain of cross-layer seams that were never executed together.

## What was observed

| # | Surface | Result | Evidence |
|---|---------|--------|----------|
| 1 | `docker compose build` | ❌ FAIL | `ERROR: No matching distribution found for pandas-ta` — pandas-ta has no release for python 3.11 (Dockerfile base); current releases require ≥ 3.12 |
| 2 | Path A — `grabers/grab_binance.py` | ✅ PASS | `Saved 20161 rows to /trader_data/train/2w_link_usdt/graber_data.pkl`; folder tree per spec; empty API keys sufficient for public klines |
| 3 | Path A rerun (incremental probe) | ✅ PASS | `No new data needed — existing range covers requested range` |
| 4 | Entry points `trainer.py`, `trader.py`, `view_*.py` | ❌ FAIL | All print `[stub] ...` and exit. Phase-00 stubs were never replaced. Every compose service except `graber` runs a stub |
| 5 | Path B — `RUN_TYPE=prepare_data` via `training.Trainer` | ❌ FAIL | `ValueError: graber_data.pkl is missing required columns: ['open_time']` — graber writes `open_time` as index (per spec); `DataPreparer` demands a column |
| 6 | Path B with index→column shim | ❌ FAIL | `KeyError: '1_vol_ma'` in `vol_sell_ma` — `DataPreparer._run_indicator_pass` writes every indicator into a throwaway per-timestamp slice from `WideDataPoint.get_df`; the wide DataFrame never receives indicator columns. Loop is also O(n²) over 20k timestamps |
| 7 | Path C — `RUN_TYPE=simulate` | ❌ FAIL | `FileNotFoundError: df_with_indicators.pkl` (upstream Path B broken) |
| 8 | Path C with planted minimal wide df (probe) | ❌ FAIL | `TypeError: SimulationData.__init__() missing 3 required positional arguments: 'begin_ts', 'end_ts', and 'step_min'` — Trainer calls `SimulationData(df)`, constructor is `(pair, begin_ts, end_ts, step_min)` and loads the pickle itself |
| 9 | `RUN_TYPE=bogus` (probe) | ✅ PASS | Clean `ValueError: Unknown RUN_TYPE: 'bogus'. Expected one of: [...]` |

## Latent bugs confirmed by inspection (behind the crashes above)

- `training/trainer.py` `_run_simulate`: `from strategy_manager import StrategyManager` — module is `strategies/strategy_manager.py`; and `StrategyManager()` omits the required `fee` argument, violating the plan's "fee always injected via constructor" decision.
- `training/trainer.py` `_run_train_nn`: imports `training.nn_orchestrator` — NNOrchestrator lives in `nn/nn_orchestrator.py`. The except-branch would falsely report "NNOrchestrator is not yet implemented (Phase 11)" although it is implemented.
- `training/trainer.py` `_run_train_nn`: `NNOrchestrator(self.config_path)` — constructor is `NNOrchestrator(checkpoint_dir, feature_cols)`.
- `Trainer.__init__` default `config_path="config/"` — the repo directory is `configs/`, and `load_nn_config()` expects a YAML *file* path, not a directory.
- Vocabulary three-way mismatch: compose passes argv modes (`generate_full_ohlc`, `group_nn`, `nn_train`), `Trainer` reads env var `RUN_TYPE` with different names (`prepare_data`, `train_nn`), plan README references a `trainer` compose service that does not exist (actual services: `ohlc_gen`, `simulate`, `prepare-nn-data`, `nn-train`, …).
- `requirements.txt` fully unpinned — this is why the build rotted (pandas-ta drifted to py ≥ 3.12-only). TA-Lib sourceforge download in the Dockerfile also failed intermittently during verification — second fragile build dependency.

## What works well

Graber (phase 02) end-to-end against live Binance: chunked fetch, atomic writes, exact 1-min spacing validation, correct incremental no-op on rerun, dataset folder init per spec, public klines with empty API keys.

## Root cause pattern

Modules of phases 03–11 exist and look individually polished; unit tests pass with mocks. But every cross-layer handoff driven at runtime broke on first touch: graber→preparer (row 5), preparer→indicators (row 6), trainer→SimulationData (row 8), trainer→StrategyManager / trainer→NNOrchestrator (latent). The per-phase Docker integration gate mandated by the plan was not enforced.

## Test artifacts left on volumes

On `simple_trader_vol` under `train/2w_link_usdt/`:

- `graber_data.pkl` — real data, usable.
- `graber_data_fixed.pkl` — index-reset copy made during verification; safe to delete.
- `df_with_indicators.pkl` — **10-row fake planted by probe 8; must be deleted before any real run**:

```bash
docker run --rm -v simple_trader_vol:/td alpine \
  rm /td/train/2w_link_usdt/graber_data_fixed.pkl /td/train/2w_link_usdt/df_with_indicators.pkl
```

## Recommendation

Fix build + entry-point wiring first, then walk Path B → C inside Docker; each seam will surface its bug immediately. Detailed step-by-step procedure with observed statuses and fix proposals: [`verification-plan.md`](verification-plan.md).
