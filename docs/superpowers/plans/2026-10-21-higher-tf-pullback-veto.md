# higher_tf_pullback_veto — Plan

> Read-only replay experiment (executing-plans, inline). No code-repo branch: scripts + outputs live in
> `external/executor/runs/`, as higher_tf_trend_filter / trend_ma_length.

**Spec:** external/docs/superpowers/experiment/higher_tf_pullback_veto.md
**Goal:** does a higher-tf pull-back state (extreme done / slope class left the trend / overshoot retreat) vetoing the
lower tf's in-trend CB zone entries raise the net on the 84 h paper window and on 2y / oos2m?
**Architecture:** `executor/runs/2026-10-21-higher-tf-pullback-replay.py` imports
`2026-10-21-higher-tf-trend-replay.py` as a module (identical flow: trades, indicator snapshots, EMA classes, trend
cache, `simulate`, `stats`, paired bootstrap) and adds the pull-back flags; tier B
`…-pullback-2y-oos2m.py` extends the higher_tf_trend_filter tier-B script (same candidate / outcome construction)
with the kernel-ported extdone state, class transitions and overshoot history. Nothing writes to the frames or the
executor DB.
**Tech stack:** host python3, numpy, pandas, talib (the parallel scripts ran on the host).

## Locked decisions — see the spec's table (author's assumptions, 2026-10-21; user not available)

## Global constraints
- Read-only over the exports and the 2y / oos2m frames; no commit (there is no code-repo change).
- Stats frozen on 2y (`EMA_SLOPE_STATS`, `EXTDONE_LADDER`, `OVERSHOOT_THR`); oos2m scored once, never selected on.
- Heavy frames column-subset, one at a time; host has ~2 GB free while sibling sessions run.

## Known facts (research, 2026-10-21)
- Exports (copied from the sibling session's scratchpad): `trades.csv` 748 276 rows 10-16 22:29Z → 10-21 10:07Z;
  `indicators.csv` (received_at, expires_at, name, value) with `{tf}_cb_zone/inzone/f_overshoot/f_trend/cbnc/cb_high/
  cb_low/extdone_high/extdone_low/cb_f_extdone_long/short/ema_7/14/25`; `events.jsonl` 188 CbZoneEntry rows;
  `klines_{1m,15m,1h,4h}.csv` (Binance, cols open_ts, o, h, l, c, v, close_ts); `trend_cache.npz`.
- Stored stream means over the export: `15_extdone_high/low` 0.267 / 0.265, `60_` 0.177 / 0.217, `240_` 0.139 / 0.144;
  `{tf}_cb_f_extdone_long` = NOT `{tf}_extdone_high` (main/ `kernel.filters`), short = NOT `extdone_low`.
- The executor's CbZoneEntryCheck reads the overshoot + trend flags only (the harness reproduces 177/188 fires without
  extdone); extdone is broadcast but unused by the executor today.
- Kernel (`main/indicators/candle_bounds/kernel.py::extdone`, NOT sticky): `extdone_high = ({tf}_high − 1_close)/
  1_atr_14_ma_5 ≥ d(progress)`, progress = wall-clock minutes since the candle's open + 1 over tf, ladder
  `params.EXTDONE_LADDER` (15 high (0.25,5)(0.5,2.5)(0.75,1.5), low (0.25,4)(0.5,2.5)(0.75,1.5); 60 high (0.25,10)
  (0.5,8)(0.75,4), low (0.25,10)(0.5,6)(0.75,4); 240 (0.75,8) both), +inf below the first step.
- Frames: 2y = `2y_az_link_usdt/df_with_indicators.pkl` (+ `2y_link_usdt/df_with_candle_bounds{,_nc}.pkl`), oos2m =
  `oos2m_link_usdt/df_with_indicators.pkl` (cb + cbnc merged), both under
  `/media/om/Alexandria/simple_trader/simple_trader_vol_long/train`; `{tf}_high/low` = running extreme of the forming
  candle, `1_atr_14_ma_5` present (ATR_COL). 2y has no `df_with_ext_done.pkl` → kernel port on both tiers.
- Precedents: higher_tf_trend_filter (static higher veto negative on tf 15, counter-trend entries the better cell),
  cross_tf_veto_replay (higher-tf opposite zone veto dead), extdone_stop_move (60/240 extdone states rarely on inside
  a position; stop move after entry-side extdone negative).

## Step 0 — entry points (host, no Docker: read-only numpy/pandas scripts, as the sibling replays)
```
cd external/executor/runs
python3 2026-10-21-higher-tf-pullback-replay.py <scratch>/data <scratch>/klines <scratch>/ema_stats_2y.json > …-replay-output.txt
python3 2026-10-21-higher-tf-pullback-2y-oos2m.py <scratch>/ema_stats_2y.json --hold=60 > …-2y-oos2m-output-h60.txt
```

## Tasks
| task | deliverable | gate |
|---|---|---|
| 1 | replay script: import harness, load extdone / overshoot history, build PB flags, variants, controls, mechanism split | live gate 177/188 reproduced; state means vs stored; mirror / shift controls present |
| 2 | run replay (full window + 24 h slices), raw outputs | every variant has n, net, PF, paired Δ vs e25 with CI90 |
| 3 | tier-B script + run h60 (h30 / h240 if RAM allows) | kernel-port gate: extdone mean per tf within ±0.03 of the stored stream's; provenance = frozen params |
| 4 | run report in executor/runs, results md, register row closed, memory note | validity gates each with a number |
