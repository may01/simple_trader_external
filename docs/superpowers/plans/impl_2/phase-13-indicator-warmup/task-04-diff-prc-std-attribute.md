# Task 04: diff_prc_std_* Attribute

**Phase:** 13 — Indicator Warmup (continuation: indicator/attribute additions)
**Depends on:** Task 03 (indicator_stats.json)
**Produces:** `diff_prc_std_close` / `diff_prc_std_high` / `diff_prc_std_low` entries in `indicator_stats.json`
**Branch:** `diff-prc-std-attr` (off `experimental_imp_2`), worktree `worktrees/diff-prc-std-attr`.

## Goal

Per TF [15, 60, 240, 1440], over closed candles: mean/std of
`{tf}_{src}_diff_prc − {tf}_{src}_diff_prc_rm_20` for src in close/high/low,
stored under key `diff_prc_std_{src}` alongside the existing
`indicator_stats.json` entries.

## Files

- `indicators/attributes.py` — extend `_compute_indicator_stats` specs map.

## Key Constraints

- Same skip rule: TF missing either source column → key omitted.
- File is idempotent (written only when absent) — regenerating an existing
  dataset requires deleting the old `indicator_stats.json`.

## Verification

- Unit: content matches manual closed-row computation per src/TF; skip rule.
- Full suite green in Docker.

## Commit

`feat: diff_prc_std_* stats in indicator_stats.json`
