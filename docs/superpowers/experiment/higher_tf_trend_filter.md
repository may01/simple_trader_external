# higher_tf_trend_filter — a higher-tf trend as a filter on lower-tf CB zone entries

Date: 2026-10-21. Status: **running**. Base: read-only replay over the paper executor's recorded data (no code-repo
branch, as trend_ma_length / trend_x_sweep); 2y / oos2m stand-in on the stored frames. Chains off
[trend_ma_length](trend_ma_length.md) (same harness, same flag reconstruction).

# Goal

Question (user, 2026-10-21): investigate how a **higher** trend impacts the signal's profit / loss — e.g. what is
the profit difference if the 15-min zones are filtered by the 60-min trend?

Today every tf's CB zone entry is vetoed only by its **own** tf's trend flag (`{tf}_cb_f_trend_{side}` = forming
EMA-25 slope class on that tf, long vetoed on −1, short on +1). The 60- and 240-min flags exist in the same
indicator stream but are never consulted for a 15-min fire.

# Hypothesis

A 15-min (60-min) zone entry taken against the 60-min (240-min) trend is a counter-trend bounce with a worse
stop-out rate; requiring the higher tf's flag to pass (or to point in the trade's direction) removes those entries
and raises the net. Null: the higher-tf flag removes entries at random with respect to their outcome (Δnet ≈ 0 or
negative because of the lost trades), as the own-tf flag did in trend_ma_length (no flag beat live on every tier).

# Variants (flag per (tf, side); everything else is the live flow)

| key | tf 15 flag | tf 60 flag | tf 240 flag |
|---|---|---|---|
| live / e25 / none | stored / reconstructed forming EMA-25 / always pass (references) | | |
| hx15<60 | own ∧ f60 | own | own |
| hx15<240 | own ∧ f240 | own | own |
| hx60<240 | own | own ∧ f240 | own |
| ladder | own ∧ f60 ∧ f240 | own ∧ f240 | own |
| all<240 | own ∧ f240 | own ∧ f240 | own |
| rp15=60 / rp15=240 / rp60=240 / rpall=240 | the higher flag **replaces** the own flag on that tf (own dropped) | | |
| al15<60 / al15<240 / al60<240 / alladder | own ∧ higher class **= direction** (aligned, stronger than the veto) | | |
| cl15<60 / clladder | own (forming) ∧ higher flag from the **closed**-candle class | | |
| nladder | no own flag; higher veto flags only (tf 15: f60 ∧ f240, tf 60: f240, tf 240: pass) | | |
| livex15<60 / livexladder | same as hx… but from the **stored** flags (reconstruction gate) | | |

f{tf} = the higher tf's forming EMA-25 flag for the trade's side (pass unless the class is against the trade).

# Steps

1. Data: the trend_ma_length exports (`trade`, `indicators`, `signal_log` of the `cbov-check` postgres, 10-16 22:29Z
   → 10-21 10:07Z; Binance klines 15m / 1h / 4h) reused as they are. Window 10-17 22:00Z → 10-21 10:07Z.
2. Paper replay: the trend-ma-length harness with the variants above. Gates: fires reproduced vs the recorded
   CbZoneEntry rows (live), reconstructed flag vs stored (e25), livex vs hx (cross-tf reconstruction).
3. 2y / oos2m stand-in (set-C entries, first passing minute per candle, candle stop, cbnc target, hold 30 / 60 / 240):
   the same variants with the per-row classes of every tf. Stats frozen on 2y (the live `EMA_SLOPE_STATS`); nothing
   selected on oos2m.
4. Stability: bootstrap CI, paired vs e25 / live, halves, days, per tf / side; fee sensitivity.
5. Report + register.

# Constraints

Read-only; no executor or main/ change. One stop rule. No fit on the replay window or oos2m.

# Locked decisions (author's assumptions — the user was not available; flagged in the report)

| # | Decision | Choice |
|---|---|---|
| 1 | "higher trend" | the higher tf's `cb_f_trend` flag (forming EMA-25 slope class), the signal the executor already has; the 1-min trade-MA class is untouched |
| 2 | filter semantics | primary = veto (higher flag must pass, as the own flag works); aligned (higher class = direction) as the stronger variant |
| 3 | which pairs | 15←60 (the user's example), 15←240, 60←240, the full ladder, 240 on all |
| 4 | own flag | kept ∧ higher (primary); replaced by the higher (rp…); dropped with higher only (nladder) — because trend_ma_length found no-flag > live |
| 5 | tiers | paper replay (all live rules) decides the sign on the live flow; 2y / oos2m stand-in carries the sample size |
| 6 | stop / fill / fees / window | as trend_ma_length: candle stop, fire-trade fill, paper fees 0 (+ fee rows), window from 10-17 22:00Z |
