# candle_reach_gate — a per-tf "candle reach" volatility index (tf-candle range in 1-min ATRs) as an entry gate on the CB zone fires

Date: 2026-10-21. Status: **done — negative** (see [results](results/candle_reach_gate_results.md)). Base: read-only replay over the paper executor's recorded data (no code-repo
branch, precedent volume_flow_entry_filter / higher_tf_bounds_geometry) + 2y / oos2m stand-in on the stored frames.
Docs on the external branch `cross-tf-veto-replay` (user's choice 2026-10-21, no branch switch — sibling sessions share
the checkout).

# Goal

User question (2026-10-21): define a volatility index that says how much price will move *inside the candle*, in
1-min ATRs, per tf (15 / 60 / 240), so that we know when the volatility is good enough to trade that tf. Intuition:
in a trend the 1-min ATR is low and the 15-min candle is fifteen small same-colour 1-min candles that add up; in a
volatile period the 1-min ATR is big and the 15-min candle is five big mixed candles. High volatility widens the stop
and asks for a faster decision; low volatility means longer waits. First use (user's choice 2026-10-21): an **entry
gate** on the existing paper system — skip the CB zone fire when the forecast reach of the candle cannot cover the
distance to the target. Sizing / stop rules from the same index are a later experiment.

Decision to make: does the gate raise the net of the recorded paper run and of the 2y / oos2m stand-in, with the
thresholds frozen on 2y, above the placebo and the random-skip band? If yes → candidate indicator (`{tf}_reach_*`
columns + executor gate spec); if no → dead, with the number.

# Rationale and algorithm

All quantities at 1-min row t use closed information only (ATR1 of the last closed 1-min bar, reach of *closed*
tf candles, the forming candle's wall-clock progress).

| key | definition |
|---|---|
| ATR1 | `1_atr_14_ma_5` (frames); on paper rebuilt from the trades as in half_atr_stop (Wilder-14 on closed 1-min bars, SMA-5) |
| reach_tf(c) | (high_c − low_c) / ATR1 at the close of closed tf candle c — the candle's range in 1-min ATRs |
| body_tf(c) | \|close_c − open_c\| / ATR1; eff_tf(c) = body / reach (Kaufman-style efficiency, 0..1) |
| base_tf | √tf — the random-walk reach for tf 1-min steps of one ATR1 (3.9 / 7.7 / 15.5) |
| reach_fc_tf(t) | median of reach_tf over the last N closed candles (N ∈ {4, 8, 16}) — the forecast at the fire |
| eff_fc_tf(t) | median of eff_tf over the same N candles |
| p(t) | wall-clock progress of the forming tf candle, (minutes since open + 1) / tf (`candle_progress`, production form) |
| rem_fc_tf(t) | reach_fc_tf × (1 − p)^α, α ∈ {0.5 (random walk), 1 (linear)} — forecast reach left in the forming candle |
| D_tgt(t) | \|cbnc far-bound target − entry\| / ATR1 — what the trade needs the candle to travel |
| atr1_rel(t) | ATR1 / rolling median of ATR1 over the trailing 1440 rows (24 h) — the scale axis |
| atr1_pct(t) | ATR1 / close × 100 — the fee-floor axis (round trip 0.042 % at 0.021 %/side) |
| rel_tf(t) | reach_fc_tf / base_tf — persistence: > 1 trending, < 1 mean-reverting |

Hypothesis H1 (primary, user's pick): a fire whose **remaining forecast reach is below the target distance**
(rem_fc < k · D_tgt) ends in a stop-out or a hold-expiry more often; skipping it raises the net. Null: the outcome
of a fire does not depend on rem_fc / D_tgt (the zone and the candle stop already price the local range), so the
gate removes fires at random with respect to their outcome, as every cross-tf veto so far did.

Secondary families (printed on all tiers, each with its own freeze on 2y):

| family | skip when | parameters |
|---|---|---|
| reach (primary) | rem_fc_tf < k · D_tgt | N, α, k ∈ {0.5, 0.75, 1, 1.5} |
| thr | reach_fc_tf < q · base_tf | N, q ∈ {0.5, 0.75, 1.0} |
| chop | atr1_rel > a ∧ rel_tf < b | a ∈ {1.3, 1.6}, b ∈ {0.8, 1.0} |
| dead | atr1_pct < m · 0.042 | m ∈ {1, 2, 3} |
| eff | eff_fc_tf < e | e ∈ {0.25, 0.35} |
| ladder (tf-15 fires only, user's choice) | rel_60 > r · rel_15 (or rel_240) | r ∈ {1.25, 1.5, 2} |
| mirror | the opposite inequality of the frozen primary (control; must not win) | — |
| sh | the frozen variant read 1440 rows (24 h) earlier at the same clock time (placebo) | — |
| rand | skip a random p of the fires, p = the frozen variant's skip rate, 3 seeds (paper tier) | — |

# Steps

1. Descriptive: distribution of reach_tf, eff_tf, rel_tf per tf on 2y / oos2m / paper (quantiles, autocorrelation
   of reach across consecutive candles — if reach is not persistent the forecast is noise and the gate is dead
   before any replay); Spearman(reach_fc, pnl), AUC(reach_fc → stop-out), outcome by rem_fc / D_tgt bins at the
   e25 entries.
2. Tier B — 2y: full grid of every family; freeze one variant per family by paired Δ vs e25 on the tf-15 cells
   with a ≥ 60 % entry-retention floor (predecessor rule); print the frozen table. oos2m: scored once with the
   frozen values; full grid printed post hoc, labelled, never used for selection.
3. Tier A — paper replay (cbov-check DB, CB-armed window from 10-18 11:41Z, the volume-flow harness + the reach
   features + the same skip knob): live, frozen variants, mirror, placebo, random-skip band; full window and the
   candle-stop era; fee sensitivity 0.02 / 0.05 / 0.1 %/side.
4. Stability: block bootstrap CI90 and P(Δ < 0), months with Δ > 0 (2y / oos2m), halves / days (paper), per tf /
   side.
5. Results md + register row; if positive, a candidate-indicator section with the frozen parameters and the
   executor gate's pseudocode.

# Results

`results/candle_reach_gate_results.md`; run report `executor/runs/2026-10-21-candle-reach-replay.md`; scripts and
outputs in `executor/runs/` (`2026-10-21-candle-reach-2y-oos2m.py`, `2026-10-21-candle-reach-replay.py`).

# Constraints

Read-only: no executor or main/ change, no column written back to any frame. Candle stop, cbnc target, set-C
entries, hold 60 primary (30 / 240 as sensitivity) as the predecessors. Nothing fitted on oos2m or on the paper
window. Host has ~1 GB free RAM while the live stack runs; the stand-in loads column subsets only (precedent peak
873 MB).

# Data

Train 2y `2y_az_link_usdt` + `2y_link_usdt` parts (ATR1), 2023-01 → 2024-12, 1 052 560 rows; OOS `oos2m_link_usdt`
2025-01 → 2025-03, 84 961 rows. Paper: `cbov-check-postgres-1` trades / indicators / events export as the volume-flow
run (its data dir reused if still present). Column naming for a promoted indicator: `{tf}_reach_fc_{N}`,
`{tf}_eff_fc_{N}`, `1_atr1_rel_1440`.

# Locked decisions (2026-10-21)

| # | question | decision | by |
|---|---|---|---|
| 1 | ladder | per tf 15 / 60 / 240, one reach per tf | user |
| 2 | first use | entry gate (not sizing / stop) | user |
| 3 | primary gate rule | target reachability: skip when rem_fc_tf < k · D_tgt | user |
| 4 | ladder selector family | included as a secondary family, not the primary freeze | user |
| 5 | docs branch | stay on external `cross-tf-veto-replay` | user |
| 6 | forecast form | median of the last N closed candles' reach (N frozen on 2y); the tf-ATR ratio `{tf}_atr_14 / ATR1` is not used (EMA lag on both sides) | author |
| 7 | remaining-reach scaling | (1 − p)^α, α frozen on 2y from {0.5, 1} | author |
| 8 | selection rule | paired Δ vs e25 on tf-15 cells, retention ≥ 60 %, as volume_flow / bounds_geometry | author |
| 9 | base branch / code | none — read-only replay, scripts in `executor/runs/` | author |
| 10 | pass criterion | frozen primary Δ > 0 with CI90 excluding 0 on 2y, same sign on oos2m and paper, placebo and random band ≈ 0, mirror ≤ 0; anything less = partial / negative | author |

# Open questions

- Does reach persist candle to candle (autocorrelation)? If lag-1 ρ < 0.2 the forecast carries nothing and the
  experiment ends at step 1 with that number.
- 2y / oos2m use `1_atr_14_ma_5` (Wilder on frame bars incl. gaps); the paper rebuild from trades differs at the
  bar edges — reported as a reproduction gate (half_atr_stop matched its stops within half a tick).
