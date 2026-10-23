# trend_ma_length — EMA-7 / EMA-14 slope class as the CB zone trend filter

Date: 2026-10-21. Status: **done — negative** (see [results](results/trend_ma_length_results.md)); EMA-14 noise, EMA-7 worse on every tier; side findings: weaker veto / no flag and the closed-candle class beat the forming EMA-25 on all tiers. Base: read-only replay over the paper executor's recorded data
(no code-repo branch for the replay; a main/ branch only if the 2y/oos2m tier needs a driver change).

# Goal

The CB zone entry's trend filter (`{tf}_cb_f_trend_{side}`) is today the forming-candle slope class of the
**EMA-25 of closes** (`ema_25_slope_class`: `ema_25_diff_prc` outside mean ± 0.5·std, stats frozen on the 2y
closed candles; long vetoed on *fall*, short on *rise*). Question (user): how does the profit change if the
slope of the **EMA-7** or the **EMA-14** is used for the trend filtering instead?

# Rationale and algorithm

A shorter EMA turns earlier: its slope class flips sooner at a reversal (fewer entries vetoed against a
dying trend, more entries vetoed when a fresh counter-move starts) and flickers more inside a range. The
live filter is a veto only — it never fires a trade — so the effect is confined to which zone minutes may
open a position; the open itself still needs the 1-min trade-MA class (rule 1 / rule 2) and the overshoot
flag. The rest of the flow (candle stop, cbnc target, trend-flip exit, reversal) is unchanged.

Same construction for every length N ∈ {7, 14, 25}, as `EmaDiffPrcField` + `ema_slope_class` do it live:

1. closed-candle EMA_N per tf (15 / 60 / 240) = talib EMA over the 105-row indicator window ending at the
   candle (main/'s `INDICATOR_WINDOW_ROWS`), i.e. what `{tf}_ema_N` holds on a closed row;
2. forming value per minute: `ema_f = α·close_now + (1−α)·ema_prev_closed`, α = 2/(N+1);
3. `diff_prc = (ema_f − ema_prev_closed) / ema_prev_closed · 100`;
4. class = −1 / 0 / +1 by `diff_prc` vs `mean ± X·std`, **mean/std frozen on the 2y closed candles of that N
   and tf** (the live EMA-25 numbers are `EMA_SLOPE_STATS`), X = `EMA_SLOPE_X` = 0.5;
5. flag: long passes unless class = −1, short passes unless class = +1; NaN passes.

# Steps

1. Export trade / indicators / signal_log from the `cbov-check` postgres; Binance LINKUSDT klines
   (1m for the forming close, 15m / 1h / 4h for the EMA warm-up).
2. **2y fit:** per tf, per N, mean/std of the closed-candle `diff_prc` on `2y_az_link_usdt`
   (2023-01-01 → 2024-12-31). Gate: N = 25 reproduces `EMA_SLOPE_STATS` (rel diff ~1e-15).
3. **Flag reconstruction:** per minute, per N, the forming class and flag from the klines. Gate: for N = 25,
   the reconstructed forming `{tf}_ema_25` vs the executor's stored snapshots, and the reconstructed flag vs
   the stored `{tf}_cb_f_trend_{side}` at every trade (agreement ≥ 99 %).
4. **Replay** with the trend-x-sweep harness (fires re-derived on every trade, today's candle stop, 0.7 σ
   1-min class), swapping only the trend flag source: `live` (stored flags) · `e25` (reconstructed, gate) ·
   `e14` · `e7` · `none` (flag always passes) · closed-candle variants `c25 / c14 / c7` (class of the last
   closed candle, shift + ffill, the `run_ema_class.py` default) · X = 1.0 sensitivity for each N.
5. Stability: bootstrap CI, paired vs live, split halves, per day, per tf / side / rule.
6. Report + register.

# Results

`external/docs/superpowers/experiment/results/trend_ma_length_results.md`; script + raw output in
`external/executor/runs/2026-10-21-trend-ma-length-replay*`; frozen 2y stats for N = 7 / 14 in the results.

# Constraints

Read-only: no change to the executor or to main/'s indicators. One stop rule for every variant. No fit on
the replay window: the only fitted numbers (mean/std per N) come from 2y closed candles, as the live ones do.
oos2m is not touched by the replay tier.

# Data

`cbov-check` paper stack postgres (Binance LINKUSDT): `trade` 2026-10-16 22:29Z → 2026-10-21 10:06Z,
`indicators` (CB names + `{tf}_ema_7/14/25` forming snapshots, 30 s cadence, 300 s validity), `signal_log`
CbZoneEntry rows. 2y: `/trader_data_long/train/2y_az_link_usdt/df_with_indicators.pkl` (47 cols,
`{tf}_close`, `{tf}_is_closed`, `{tf}_ema_25`). Binance klines fetched 2026-10-21 for the EMA warm-up.

# Locked decisions (author's assumptions — the user was not available; flagged in the report)

| # | Decision | Choice |
|---|---|---|
| 1 | "ma 21 or 25" | the live filter is the EMA-25 of closes (`ema_25_slope_class`); no 21 exists in the flow |
| 2 | What changes | only the `cb_f_trend` flag's EMA length; the 1-min trade-MA class (rule 1/2, trend-flip exit) stays |
| 3 | Thresholds for N = 7 / 14 | same recipe as N = 25: mean ± 0.5·std of the 2y closed-candle `diff_prc`, per tf |
| 4 | Forming vs closed | primary = forming (live convention); closed-candle class reported as an ablation |
| 5 | Stop / fill / fees / window | as trend_x_sweep: candle stop everywhere, fire-trade fill, paper fees 0 (+0.1 %/side row), window from 10-17 22:00Z |
| 6 | Selection | none; whole window reported, split halves as a stability check |

# Open questions

- Should the shorter EMA also replace the 1-min trade-MA class (the open's own trend gate)? Not in scope;
  yesterday's ma_window_by_tf replay showed any slower trade-MA class is worse.
