# candle_reach_gate — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:executing-plans (inline; read-only replay, two scripts).

**Spec:** external/docs/superpowers/experiment/candle_reach_gate.md
**Goal:** decide whether skipping CB zone fires whose forecast remaining candle reach (median reach of the last N
closed tf candles in ATR1 × (1 − progress)^α) is below k × the target distance raises the net on 2y-frozen /
oos2m-scored / paper-replayed tiers above placebo and the random-skip band.
**Architecture:** two scripts in `external/executor/runs/`, both copies of the volume-flow pair with the flow
features replaced by the reach features; they read the stored frames (2y / oos2m) and the paper export dir; nothing
in main/ or trade_executor changes; no frame is written.
**Tech stack:** host python3 + numpy / pandas / talib (as the predecessors ran).

## Locked decisions (user-confirmed 2026-10-21)
See the spec's table (1–5 user, 6–10 author).

## Global constraints
- Do not commit anything; stage nothing; the user approves the results first.
- Frames read-only, column subsets only (host ~1 GB free with the live stack up; precedent peak 873 MB).
- oos2m scored once with the 2y-frozen values; paper replay scored with the same values.
- Docs stay on external `cross-tf-veto-replay`; no code-repo branch.

## Known facts (recon 2026-10-21)
- ATR1 column `1_atr_14_ma_5` (2y: in `2y_link_usdt/df_with_indicators.part_{00..24}.pkl`; oos2m: in
  `oos2m_link_usdt/df_with_indicators.pkl`); `1_open`, `1_high`, `1_low`, `1_close`, `{tf}_close`, `{tf}_is_closed`
  in `2y_az_link_usdt/df_with_indicators.pkl`; cb bounds / zones / cbnc as the volume-flow stand-in loads them.
- 2y 1 052 560 rows 2023-01-01 → 2024-12-31; oos2m 84 961 rows 2025-01-01 → 2025-03-01; stand-in run ≈ 200 s.
- Candle id = cumsum of `{tf}_is_closed` shifted (predecessor `candle_id`); progress = production wall-clock form
  `(minutes since floor(tf) + 1) / tf`.
- Paper export dir (trades.csv with qty+side, events.jsonl, positions.jsonl, indicators.csv, depletion.csv) =
  the volume-flow run's scratchpad `data/` (located in recon; copied into this session's scratchpad).
- Paper ATR1 rebuild: half_atr_stop lines 97–108 (Wilder-14 on closed 1-min bars from trades, SMA-5).
- Paper harness knobs reused: `vol=dict(skip=[(feature, lo, hi)], shift_h)`, random-skip `cci=dict(mode="rand")`,
  6-h block bootstrap, reproduction gate (200/207 fires, 54/55 stops).

## Step 0 — entry points
```
cd external/executor/runs
python3 2026-10-21-candle-reach-2y-oos2m.py --hold=60            > 2026-10-21-candle-reach-2y-oos2m-output-h60.txt
python3 2026-10-21-candle-reach-replay.py <data dir>              > 2026-10-21-candle-reach-replay-output-full.txt
python3 2026-10-21-candle-reach-replay.py <data dir> --t0=1792527900000 > ...-output-candle-era.txt
```

## Tasks
| task | deliverable | gate |
|---|---|---|
| 1 | stand-in script: reach features (per tf: closed-candle reach / body / eff, median-N forecast, progress, rem, D_tgt, atr1_rel, atr1_pct, rel, 1440-row shift), descriptive section (quantiles, lag-1 autocorrelation of reach, Spearman / AUC / bins at e25 entries), variant grid per family, 2y selection with retention floor, frozen table, oos2m scoring | smoke on oos2m only (`--only=oos2m --frozen=...`) runs < 2 min, e25 cells reproduce the volume-flow stand-in's e25 numbers exactly |
| 2 | run 2y → oos2m (hold 60; hold 30 / 240 sensitivity if time) | outputs saved; frozen values recorded |
| 3 | paper harness: ATR1 rebuild, per-tf closed-candle reach from the 1-min bars, same features at the fire tick, variants = live + frozen + mirror + sh24 + rand band | reproduction gate unchanged (200/207, 54/55) |
| 4 | run paper full + candle era; fee sensitivity | outputs saved |
| 5 | results md, run report md, register row, memory | user approval |
