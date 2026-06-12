# Task 05: Raw RSI / CCI Value Stats

**Phase:** 13 — Indicator Warmup (continuation: indicator/attribute additions)
**Depends on:** Task 03 (indicator_stats.json)
**Produces:** `rsi_14` and `cci_14` entries (mean/std of raw values) in `indicator_stats.json`
**Branch:** `rsi-cci-stats` (off `experimental_imp_2`), worktree `worktrees/rsi-cci-stats`.

## Goal

Per TF [15, 60, 240, 1440], over closed candles: mean/std of raw `{tf}_rsi_14`
and `{tf}_cci_14`, stored under keys `rsi_14` and `cci_14` alongside the
existing `indicator_stats.json` entries. (Distinct from rsi_classification.json,
which holds `rsi_ma8` stats.)

## Files

- `indicators/attributes.py` — extend `_compute_indicator_stats` specs map.

## Verification

- Unit: content matches manual closed-row computation; missing-column skip.
- Full suite green in Docker.

## Commit

`feat: raw rsi_14/cci_14 value stats in indicator_stats.json`
