# Plan: higher_tf_trend_filter (2026-10-21)

Spec: `../experiment/higher_tf_trend_filter.md`. Read-only replay, no code-repo branch (precedent: trend_ma_length).

## Known facts (recon)

- Data: trend_ma_length session exports copied into this session's scratchpad `data/` (trades.csv 748 276 rows
  10-16 22:29Z → 10-21 10:07Z; indicators.csv with `{tf}_cb_zone/inzone/f_overshoot/f_trend_{side}`, `{tf}_cbnc_high/low`,
  received_at/expires_at; events.jsonl 188 CbZoneEntry rows; trend_cache.npz slope/sigma per trade) + `klines/`
  (Binance 15m/1h/4h/1m) + `ema_stats_2y.json` (N 7/14 stats; N 25 = live FROZEN25 in the script).
- Live flag = forming EMA-25 class, X 0.5, stats `EMA_SLOPE_STATS` (sample std); pass = stored flag != 0, absent passes.
- 2y frames: `/media/om/Alexandria/simple_trader/simple_trader_vol_long/train/2y_az_link_usdt/df_with_indicators.pkl`
  (`1_high/low/close`, `{tf}_close`, `{tf}_is_closed`), `2y_link_usdt/df_with_candle_bounds.pkl` (`{tf}_cb_low/high(_std)`,
  `{tf}_cb_inzone_{side}`), `2y_link_usdt/df_with_candle_bounds_nc.pkl` (`{tf}_cbnc_high/low`); oos2m all in
  `oos2m_link_usdt/df_with_indicators.pkl`. Tier-B RSS ~700 MB; host has ~1 GB free + cache (13/15 GB used by Chrome/VS Code).
- Executor postgres `cbov-check-postgres-1` on 5436 still up (re-export not needed; same window as trend_ma_length keeps
  the baselines comparable: e25 +3 783, live +3 732, none +4 751).

## Tasks

1. Paper replay script `executor/runs/2026-10-21-higher-tf-trend-replay.py` (from the trend-ma-length harness; N 25
   only; cross-tf variants). Gates: fires 177/188 exact (live), flag agreement ≥ 99 % (e25), livex vs hx.
2. 2y / oos2m script `…-2y-oos2m.py`: classes of every tf per row first, then flags per (tf, side) from the higher tf's
   class. Holds 30 / 60 / 240.
3. Run both; raw outputs beside the scripts.
4. Results `experiment/results/higher_tf_trend_filter_results.md`, run report `executor/runs/…-replay.md`, REPORT.md
   row closed. Nothing committed until the user approves.
