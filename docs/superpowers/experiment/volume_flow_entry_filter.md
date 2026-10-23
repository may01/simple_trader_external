# Volume / 5-min buy–sell flow / book-depletion markers at the CB zone entry — entry filters

Date: 2026-10-21. Status: done 2026-10-21, verdict partial — see results/volume_flow_entry_filter_results.md (autonomous session; locked decisions below are the session's assumptions, user
asked only for the analysis — correct any row and the run is repeated).

# Goal
Align the 1-min/5-min trade volume, the 5-min buy−sell volume difference (the executor's own `net_qty` over the
trailing 5 min of trades) and the `volume_book_depletion_{15,60,240}` markers with every CB zone position entry of
the paper run, measure the correlation with the position outcome (pnl, R multiple, stop-out), propose entry filters
that remove losing trades, and replay each filter through the executor's rules to measure the profit impact with a
paired block test, placebos and a split-half check. Then the flow part (not the book markers, which have no history)
is re-measured on 2y / oos2m through the tier-B stand-in.

# Rationale and algorithm
CB zone entries fade a move into the zone. The hypothesis to test both ways: (a) strong taker flow still pushing into
the zone (net flow against the trade's side) means the move is not done → more stop-outs; (b) flow already turned (net
flow with the trade) means the reversal has started → fewer stop-outs; (c) volume climax / dead tape change the odds.
The depletion markers are the executor's projection "net rate × horizon walked against the live book moves price by
> P %" — a marker in the trade's direction at the fire would say the book is thin on the trade's side.

Quantities at a fire tick t (trailing, trades only, nothing after t):
- `vol{w}`   = Σ qty over (t − w min, t], w ∈ {1, 5, 15}; `rv{w}` = vol{w} / median of the per-w-minute volume over the
  trailing 2 h (relative volume)
- `net{w}`   = Σ buy qty − Σ sell qty over the same window (the executor's `net_qty`, w = 5 is the live one)
- `imb{w}`   = net{w} / vol{w} ∈ [−1, 1]; `adv_imb` = +imb for a long fire, −imb for a short fire (positive = flow
  agrees with the trade)
- `dep{h}`   = a `volume_book_depletion_{h}` row within the last 60 s of t; `dep{h}_dir` = its direction vs the
  trade's side (+1 agree, −1 oppose, 0 none); `dep{h}_move` = signed |projected_move| / price; `dep{h}_dens` = rows
  in the last 5 min
Outcome per position: pnl, R = pnl / (size × stop distance), stop-out flag, MAE / stop distance.

# Steps
1. Export the paper DB (trades with side+qty, cb indicators, cb_zone fires, position_log, depletion signal_log).
2. Replay harness = the stop-re-entry harness (rules unchanged) + the features above at every simulated fire.
3. Descriptive: per-position feature table, quantile bins vs stop-out / mean pnl, Spearman + permutation null,
   AUC(feature → stop-out), per tf / side.
4. Filters as harness variants: skip the fire when the feature is in a band (both tails of adv_imb, rv high / low,
   depletion marker present / agree / oppose per horizon, combinations); placebo = random skip at the same rate (8
   seeds) and the same feature read 24 h earlier; split-half = bands chosen on the first half of the window, scored
   on the second.
5. Profit impact: Δ net vs live, paired 6-h block bootstrap, P(Δ<0), per tf / side, candle-stop era, fee sensitivity.
6. 2y / oos2m stand-in for the flow features only (`taker_base_vol`, `volume` of the 1-min frame): veto grid frozen on
   2y with entry retention ≥ 60 %, oos2m scored with the frozen values, mirror + 1440-row shifted placebo.

# Results
`results/volume_flow_entry_filter_results.md`; run report + scripts + outputs in `executor/runs/2026-10-21-volume-flow-*`.

# Constraints
Read-only over the executor DB and the stored frames; no code repo change; nothing committed before approval;
oos2m scored once with frozen 2y parameters; the paper window is in-sample for any band chosen on it (split-half is
the only out-of-sample number there).

# Data
Paper: LINKUSDT, cb_zone era 2026-10-18 11:41 → 2026-10-21 18:02 UTC (~78 h), 832 623 trades, 207 recorded fires,
159 recorded positions, depletion rows 52 452 / 191 617 / 453 184 (h 15 / 60 / 240; active in 4 / 17 / 56 % of
minutes). 2y = `2y_az_link_usdt` + `2y_link_usdt` parts (2023-01 → 2024-12), oos2m = `oos2m_link_usdt` (2025-01 →
2025-03).

# Locked decisions (session, 2026-10-21)
| # | Decision | Choice |
|---|---|---|
| 1 | Entry = the fire tick (live rule); features trailing from the fire tick, trades only | yes |
| 2 | Live flow window | 5 min (= the executor's `avg_window`); 1 and 15 min as a ladder |
| 3 | Depletion marker "active" | a row within the last 60 s before the fire (markers fire every tick while the condition holds) |
| 4 | Outcome | pnl at the simulator's exit (stop / target+flip / reversal), no fees, fee sensitivity 0.1 %/side |
| 5 | Filter acceptance | Δ vs live > 0 on the full window AND the candle era, P(Δ<0) ≤ 0.10 on the paired 6-h block bootstrap, beats the random-skip placebo band, holds in the second half when chosen on the first |
| 6 | 2y freeze rule | best paired Δ vs e25 on the tf-15 cells with retention ≥ 60 %, one value per family |
| 7 | Isolation | read-only scripts in `external/executor/runs`; no worktree, no branch (parallel sessions share the external checkout) |

# Open questions
- Trade `side` in the executor's `trade` table is the taker side as the exchange reports it; the 2y `taker_base_vol`
  is Binance's taker-buy base volume — same convention, different exchange (paper feed = Binance WS).
- Book depletion markers have no history → paper only.
