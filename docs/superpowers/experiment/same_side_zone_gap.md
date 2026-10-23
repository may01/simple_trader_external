# same_side_zone_gap — a close higher-tf zone on the SAME side as a lower-tf fire: veto or delay the lower entry

Date: 2026-10-21. Status: **running**. Base: read-only replay over the paper executor's recorded data (no code-repo
branch; precedent higher_tf_bounds_geometry / higher_tf_pullback_veto / higher_tf_trend_filter — same harnesses);
2y / oos2m stand-in on the stored frames. Docs on the external branch `cross-tf-veto-replay` (the cross-tf series).
Chains off [higher_tf_bounds_geometry](higher_tf_bounds_geometry.md).

# Goal

Question (user, 2026-10-21): when a 15-min zone and a 60-min zone are close to each other, the bigger one drags the
price to itself — so a 15-min fire with a nearby 60-min zone is more likely to be stopped out. Calculate the impact on
profit of (a) removing the lower-tf fire in that situation and (b) delaying the opening (entering at the higher zone
instead).

# What the predecessors already answered (not repeated)

- higher_tf_bounds_geometry measured the higher tf's **range position** (favourable room), the **ATR room** to the
  higher tf's opposite bound, and the coincidence of the lower tf's **opposite** bound with the higher tf's bound —
  all negative as vetoes; entries at the wrong end of the higher range are the best cells.
- cross_tf_veto_replay: higher tf in zone on the **opposite** side → dead; any_zone flat.
- stop_reentry_pairs: 43 % of stop-outs start a stop → better re-entry pair (first legs 43 % of the stop money);
  cooldown / deeper re-entry / half size dead.

Not measured yet: the signed **gap from the lower-tf entry to the higher tf's SAME-side zone line**, i.e. whether the
higher zone lies a little *beyond* the entry in the stop's direction, and a delayed entry at that higher zone.

# Hypothesis

At a lower-tf fire (tf T, side s, price p), the higher tf H has its same-side zone line z_H (long: `H_cb_zone_long`,
short: `H_cb_zone_short`). Gap g = (p − z_H) for a long, (z_H − p) for a short, in units of the stop's own unit (mean
1-min range on paper, ATR1 on 2y / oos2m) and in units of the entry's stop distance. H0 (user): for 0 ≤ g < k (the
higher zone just beyond the entry) the lower-tf entry is stopped more often and loses; removing it, or replacing it
with an entry at z_H, raises the net. Null: the outcome of the lower-tf entry does not depend on g; a veto removes
entries at random with respect to outcome (placebo = g read 24 h earlier), a delayed entry only lowers the fill rate
(cci_zone_excursion: P(+1 ATR1 | filled) is memoryless in the depth).

# Quantities (per trade / row; H ∈ {60, 240} for T = 15, H = 240 for T = 60)

| key | definition |
|---|---|
| g_z | signed gap to H's same-side zone line in stop units: long (p − z_H)/u, short (z_H − p)/u; u = mean 1-min range (paper) / ATR1 (2y, oos2m). g > 0: H's zone lies beyond the entry (stop side); g < 0: price is already inside / beyond H's zone |
| g_d | the same gap in units of the entry's candle-stop distance d (g_z·u / d); g_d < 1: H's zone sits inside the stop |
| mr | control: the gap to H's OPPOSITE zone in the trade's favour (long (z_H,short − p)/u) |
| sh | placebo: g_z read 24 h earlier |

# Variants (veto ANDed into the own forming EMA-25 flag e25; pairs 15<60, 15<240, 60<240, ladder)

| key | rule |
|---|---|
| gz{k} | veto when 0 ≤ g_z < k, k ∈ {0.5, 1, 2, 3, 5} — k frozen on 2y |
| gzb{k} | veto when \|g_z\| < k (either side of the entry) |
| gzin | veto when g_z < 0 (H's same-side zone already touched / passed) |
| gd{m} | veto when 0 ≤ g_d < m, m ∈ {0.5, 1, 1.5, 2, 3} |
| mr{k} | control: 0 ≤ mr < k (H's opposite zone just ahead — the room veto of the predecessor) |
| sh{k} | placebo: 0 ≤ sh < k |
| dl{k}N | delay: when 0 ≤ g_z < k do not open at the fire; a limit at z_H (frozen at the fire) is live for N min (N ∈ {15, 60}); fill at the line, candle stop and cbnc target taken at the fill; otherwise no entry |
| dlc{k}N | delay + the 1-min class at the fill must not be against the trade |

# Steps

1. Descriptive: distribution of g_z / g_d at the e25 entries (2y, oos2m, paper); outcome of the e25 entries by g bin
   (n, net, PF, stop share, mean) — the direct test of "more likely stopped".
2. Tier B (2y → freeze k / m / N per family by paired Δ vs e25 on the 15<60 pair, entry retention ≥ 60 % for vetoes;
   oos2m scored once with the frozen values; full grids printed for both tiers but labelled).
3. Paper replay (84 h, the trend-filter harness extended with a pending limit for the delay variants): frozen
   variants + controls; gates: fires reproduced, stored zone lines present at the trades.
4. Stability: bootstrap CI, months with Δ > 0, per tf / side, halves / days on paper; fee sensitivity.
5. Results + register.

# Constraints

Read-only; no executor or main/ change. Candle stop, cbnc target, set-C entries as the predecessors. Nothing fitted
on the replay window or on oos2m. Source frames read-only.

# Data

Paper: the trend_ma_length exports (trades 10-16 22:29Z → 10-21 10:07Z, indicators with `{tf}_cb_zone_*`,
`cb_inzone_*`, `cb_f_*`, `cbnc_*`; 188 CbZoneEntry rows), window 10-17 22:00Z → 10-21 10:07Z. 2y: `2y_az_link_usdt`
+ `2y_link_usdt` candle-bounds / cbnc sidecars + ATR parts; oos2m: `oos2m_link_usdt/df_with_indicators.pkl`.

# Locked decisions (author's assumptions — the user was not available; flagged in the report)

| # | Decision | Choice |
|---|---|---|
| 1 | "zone close" | the gap from the entry price to H's same-side ZONE LINE (where H itself would fire), signed so that positive = beyond the entry on the stop side; in stop units and in stop-distance units |
| 2 | "bigger zone" | H = 60 for a 15 fire (primary), 240 for 15 and 60 (secondary), ladder |
| 3 | "remove" | veto ANDed into e25 (the live flow); the 60 zone's own fire stays as it is |
| 4 | "delay" | a limit at H's zone line, frozen at the fire, live N min; fill at the line; stop / target at the fill; no entry if not filled |
| 5 | fit / score | k, m, N chosen on 2y only (paired Δ, retention ≥ 60 % for vetoes); oos2m scored once; paper decides the sign on the live flow |
| 6 | stop / fill / fees / window | as the predecessors: candle stop, fire-trade fill, paper fees 0 (+ fee rows), window 10-17 22:00Z → 10-21 10:07Z |

# Open questions

- Should the delayed entry inherit the 15-min fire's target (cbnc of the 15) or take the 60's? Assumed: the 15's
  target at the fill (the fire is still a 15-min fire, executed later).
