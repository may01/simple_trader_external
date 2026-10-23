# trend_x_sweep — the 1-min trade-MA slope band multiplier X

Date: 2026-10-20. Status: **done — partial** (see [results](results/trend_x_sweep_results.md)); keep X = 0.7. Base: read-only replay over the paper executor's recorded data
(no code-repo branch; the replay script lives beside the run report, as the sl-15m-anchor replay did).

# Goal

Decide which value of X in "MA slope outside ±X·σ is a trend" (`signals::trend::TrendParams::std_mult`,
today 0.7, same number in `static/js/trades_ma.js`) gives the paper executor the best P&L, and whether any
value is distinguishable from 0.7 at all on the data recorded so far.

# Rationale and algorithm

The class gates both ends of every CB zone trade (cb-zone-entry-signal §6, cb-target-trend-exit §7):

- open, rule 1: in zone ∧ class = direction of the side;
- open, rule 2: previous 1-min candle rejected at the zone ∧ class ∈ {neutral, direction};
- close: extreme past the frozen `cbnc` target ∧ class opposite to the side.

X moves the neutral band: X → 0 means every bucket is up or down (rule 1 fires on the slope's sign alone,
rule 2 needs the sign to agree, the trend-flip exit fires on the first adverse bucket after arming); X → ∞
means everything is neutral (rule 1 never fires, rule 2 fires regardless of the slope, the trend-flip exit
never fires — positions end on the stop or a reversal).

Replay: event-driven re-run of the recorded Binance LINKUSDT trades with the CB indicator snapshots the
executor stored (`indicators`, 30 s cadence, 300 s validity), the check ported from
`checks/cb_zone_entry.rs` (filters, rule 1/2, once-per-zone, both-sides veto, 60 s gap, highest tf), the
orchestrator's same-side skip / opposite-side reversal, the candle stop (forming-15m extreme ∓ trailing-60
mean 1-min range, 0.2 % placeholder — today's live rule, held fixed across X), sizing
`min(100/dist, free·0.5/entry)`, the trend port of `signals::trend`. (slope, σ) is computed once per
trade; only the class depends on X, so the sweep re-runs the simulation only.

# Steps

1. Export trade / indicators / signal_log / position_log / candle from the `cbov-check` postgres.
2. Port trend + check + stop + orchestrator + exits into one numpy script; cache (slope, σ) per trade.
3. Reproduction gate at X = 0.7: simulated fires vs the 152 recorded `CbZoneEntry` rows (ts, side, tf,
   rule, class) and slope at the recorded fires vs the logged `ma_slope`.
4. Sweep X ∈ {0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0}: trades, net, PF,
   win rate, exits by reason, R, bootstrap CI, class mix, with and without a 0.1 %/side fee.
5. Stability: split the window in two halves and per day; does the ranking of X hold?
6. Report.

# Results

`external/docs/superpowers/experiment/results/trend_x_sweep_results.md`, script + raw output in
`external/executor/runs/2026-10-20-trend-x-sweep-replay*`.

# Constraints

Read-only: no change to the executor or main/. One stop rule for every X. No fit/selection on a held-out
part — the data is ~4 days, the whole window is reported with a split-half check instead of a 2y/oos2m
split (there is no tick history to fit on).

# Data

`cbov-check` paper stack postgres: `trade` 2026-10-16 22:29Z → 2026-10-20 21:20Z (670 k trades),
`indicators` (CB names from 10-16 22:34Z, overshoot flags from 10-17 22:00Z), `signal_log` CbZoneEntry
152 rows from 10-18 11:41Z, `position_log`, `candle` 1m.

# Locked decisions (author's assumptions — the user was not available; flagged in the report)

| # | Decision | Choice |
|---|---|---|
| 1 | Stop rule across the sweep | today's live candle stop + 0.2 % placeholder, for every X |
| 2 | Entry fill | the firing trade's price (no mid) |
| 3 | Fees | paper = 0; a 0.1 %/side sensitivity row |
| 4 | Replay window | from the first trade with overshoot flags (10-17 22:00Z) to the last stored trade |
| 5 | Continuous run | no executor restarts modelled (bars, fired-state, warm-up never reset) |
| 6 | Selection | none: the whole window is reported; split halves are a stability check, not a fit |

# Open questions

- Should X differ between the open gate and the trend-flip exit? (One number today; the sweep also
  reports the exit-only and entry-only variants.)
