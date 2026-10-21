# higher_tf_pullback_veto — a higher-tf PULL-BACK state discarding the lower tf's in-trend CB zones

Date: 2026-10-21. Status: **done — negative, archived 2026-10-21** (see [results](results/higher_tf_pullback_veto_results.md)); no further work. Base: read-only replay over the paper executor's recorded data (no code-repo
branch, as [higher_tf_trend_filter](higher_tf_trend_filter.md) / trend_ma_length); 2y / oos2m stand-in on the stored
frames. Chains off higher_tf_trend_filter (same harness, same exports, same flag reconstruction).

# Goal

Question (user, 2026-10-21): "Investigate pull back: when the higher tf shows signals to reverse from the trend (or
goes too deep) and moves backward into range, it makes sense to discard the in-trend-direction zones on the lower
timeframes, because the higher-tf move will win."

Measurable: does vetoing a lower-tf (15 / 60) CB zone entry whose side equals the higher tf's (60 / 240) previous
trend direction, **while that higher tf is pulling back** (reversal signal fired, price retreating from its extreme
into the candle's range), raise the net / PF of the live flow — on the 84 h paper window and on the 2y / oos2m
stand-in?

# Hypothesis

A 15-min long zone touched while the 60-min candle has made a high and is pulling back from it (or the 60-min
slope just flipped from up, or price has overshot the 60-min upper bound and come back inside) is a "buy the dip in
the old trend" that gets run over by the higher-tf retreat; removing those entries (and their short mirrors) raises
the net. Null: the pull-back state removes entries at random with respect to outcome (Δ ≈ 0 minus the lost
trades), as the static higher-tf veto did in higher_tf_trend_filter (hx15<60 −1 051, P(Δ<0) 0.92; the entries
**against** the higher trend were the better cell, PF 2.43 vs 1.22).

Difference to higher_tf_trend_filter: that experiment vetoed on the higher tf's *standing* slope class (trend
against the trade). This one vetoes on a *transition* of the higher tf — trend **with** the trade that is reversing
right now — so the two veto sets are disjoint by construction (the static veto removes counter-trend entries, the
pull-back veto removes in-trend entries during the retreat).

# Pull-back state definitions (per higher tf H, per direction d; all from information the executor already has)

| key | PB_long on H (PB_short mirrored) | source |
|---|---|---|
| **xd** | `{H}_extdone_high` = the forming H candle's high is done: `(H_high − price)/ATR1 ≥ d(progress)` (frozen 2y ladder `EXTDONE_LADDER`) — the up-run reversed and price has pulled away from it | stored `{H}_cb_f_extdone_long` (= not extdone_high, main/ `kernel.filters`); tier B: kernel port |
| **cf0** / **cf−** | the last **closed** H candle's EMA-25 slope class was +1 (trend up) and the **forming** class is now ≤ 0 (cf0) / −1 (cf−) — "signal to reverse from the trend" | reconstructed forming / closed EMA-25 classes (higher_tf_trend_filter's `CLS_F` / `CLS_C`, frozen `EMA_SLOPE_STATS`) |
| **ovc** / **ov30** | the H short-side overshoot flag fired (price beyond H's `cb_high` by > `OVERSHOOT_THR`, "went too deep") earlier in the same forming H candle (ovc) / within the last 30 min (ov30) and price is now back inside (flag passes again) — "moves backward into range" | stored `{H}_cb_f_overshoot_short` history; tier B: `over > THR` from the frames |
| **any** | xd ∨ cf0 ∨ ovc | |
| **xdcf** | xd ∧ cf0 (both signals) | |

Veto rule per variant: a lower-tf fire of side s is vetoed when PB_s(H) is on; everything else (own-tf trend flag,
overshoot flag, 1-min class rules, candle stop, cbnc target, trend-flip exit, reversal, same-side skip) is the live
flow. Pairs: 15←60, 15←240, 60←240, ladder (15←60∧240, 60←240).

Controls: **mirror** (veto the lower-tf fire *against* the old trend during the pull-back, i.e. the opposite sign of
the hypothesis — `{H}_cb_f_extdone_{opposite}`), **shift** (the xd state shifted by ±24 h: a pass-rate-matched
placebo), **none** / **e25** / **live** references from higher_tf_trend_filter.

# Steps

1. Data: the higher_tf_trend_filter exports (`trade` 748 276 rows, `indicators`, `signal_log` 188 CbZoneEntry rows,
   Binance klines) reused as they are, copied to this session's scratchpad. Window 10-17 22:00Z → 10-21 10:07Z.
2. Paper replay: the higher_tf_trend_filter harness imported as a module (identical flow), the pull-back flags added
   per (tf, side). Gates: fires reproduced vs recorded (live), e25 vs stored own flag, the state pass rates vs the
   stored stream, the xd state's mean vs the stored `extdone_high/low` means.
3. Mechanism: the e25 positions split by each higher-tf pull-back state at the open (n, net, PF, stop share); the
   same split for the static class so the two veto sets are shown disjoint.
4. 2y / oos2m stand-in (higher_tf_trend_filter's tier B: set-C candidate minutes, first passing minute per candle,
   candle stop, cbnc target, hold 60): xd (kernel port, wall-clock progress), cf0 / cf−, ovc / ov30, any, mirror, per
   pair + ladder; month-matched shift placebo. Frozen ladders / thresholds / EMA stats from 2y; nothing selected on
   oos2m.
5. Stability: bootstrap CI, paired vs e25 / live, halves, days, per tf / side; fee sensitivity.
6. Report + register.

# Constraints

Read-only; no executor or main/ change. One stop rule. No fit on the replay window or oos2m. Frames loaded
column-subset, one at a time (host RAM 15 GB, ~2 GB free during the parallel sessions).

# Locked decisions (author's assumptions — the user was not available; flagged in the report)

| # | Decision | Choice |
|---|---|---|
| 1 | "signals to reverse from the trend" | (a) the forming H EMA-25 slope class leaving +1 after a closed +1 (cf0 / cf−); (b) the H candle's extreme done (`extdone`, the ev_line survivor) — both already in the indicator stream |
| 2 | "goes too deep and moves backward into range" | the H overshoot flag having fired earlier in the candle / last 30 min and passing again (ovc / ov30); also covered by xd (pull-away ≥ d ATR from the extreme) |
| 3 | "in-trend-direction zones" | lower-tf fires whose side equals the direction of the H move that is reversing (long when H's high is done / slope left +1 / price came back below cb_high) |
| 4 | which pairs | 15←60 (primary), 15←240, 60←240, ladder |
| 5 | own flag | kept (live flow) — the variants only add a veto; a no-own-flag variant is not part of this question |
| 6 | tiers / window / stop / fees | as higher_tf_trend_filter: paper replay 84 h from 10-17 22:00Z, candle stop, fire-trade fill, paper fees 0 (+ fee rows); tier B hold 60 |
| 7 | state source in the replay | stored executor stream for xd / ov (what the executor would actually read), reconstructed classes for cf (gated 99 % vs stored in higher_tf_trend_filter) |
