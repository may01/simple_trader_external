# higher_tf_bounds_geometry — how the CB bounds of the tfs connect, and the higher tf's range position as a filter on lower-tf entries

Date: 2026-10-21. Status: **negative** (results in [results/higher_tf_bounds_geometry_results.md](results/higher_tf_bounds_geometry_results.md)). Base: read-only replay over the paper executor's recorded data (no code-repo
branch, precedent trend_ma_length / higher_tf_trend_filter / higher_tf_pullback_veto); 2y / oos2m stand-in on the
stored frames. Docs on the external branch `cross-tf-veto-replay` (the cross-tf series). Chains off
[higher_tf_pullback_veto](higher_tf_pullback_veto.md) (same harnesses).

# Goal

Question (user, 2026-10-21): investigate how the candle bounds of the tfs are connected to each other, and whether
a lower-tf entry that loses *because of the bigger tf's move* can be filtered by the higher tf's bounds. Example: the
15-min low zone executes, price runs to the 15-min high bound and a short opens there — but the 15-min low bound sits
near the 60-min low bound and the 60-min candle keeps moving up, so the 15-min reversal from its high bound fails.

Two deliverables: (a) a description of the bound geometry across tfs (spans, nesting, bound coincidence, where in the
higher range the lower-tf fires happen, and how the outcome depends on that); (b) a veto on the lower-tf entry from
the higher tf's range position / executed opposite bound, fitted on 2y, scored once on oos2m, replayed on paper.

# What the predecessors already answered (not repeated)

- cross_tf_veto_replay (10-20): higher tf **in-zone on the opposite side** discarding the lower fire — dead
  (sign flips by day); `any_zone` flat.
- higher_tf_trend_filter (10-21): higher tf's **EMA-25 slope flag** — negative on paper (hx15<60 −1 051, P 0.92);
  counter-trend 15-min entries are the *better* cell (PF 2.43 vs 1.22).
- higher_tf_pullback_veto (10-21): higher tf **extreme done / class flip / overshoot retreat** vetoing in-trend
  lower entries — negative on all tiers; the removed entries are of average quality.

The present question differs in the quantity: the **position of the entry inside the higher tf's predicted range**
(how much of the higher range lies in the trade's favour) and the **coincidence of the lower tf's opposite bound with
the higher tf's same-side bound** (the "connected bounds" of the example), neither of which was measured.

# Hypothesis

At a lower-tf fire (tf T, side s, price p), let the higher tf H have bounds `H_cb_low < H_cb_high` and define the
**favourable room** f = share of H's range on the trade's side: f = (p − H_cb_low)/(H_cb_high − H_cb_low) for a
short, 1 − that for a long. H0 (user): entries with small f (a short near the bottom of the 60-min range, a long near
its top) lose more often — the higher tf still has to travel against them — so vetoing f < q raises the net. Null:
the outcome of the lower-tf entry does not depend on f (the lower tf's own zone already encodes the local
reversal); any veto removes entries at random with respect to their outcome, as every cross-tf veto so far did.

# Quantities (per row / per trade, higher tf H ∈ {60, 240} for T = 15, H = 240 for T = 60)

| key | definition |
|---|---|
| pos_H | (close − H_cb_low)/(H_cb_high − H_cb_low) |
| f | favourable room share: pos_H (short) / 1 − pos_H (long) |
| room_H | favourable room in ATR1 (`1_atr_14_ma_5`): (close − H_cb_low)/ATR1 for a short, (H_cb_high − close)/ATR1 for a long |
| nest_δ | the lower tf's **opposite** bound within δ·ATR1 of H's same-side bound (short: \|T_cb_low − H_cb_low\| ≤ δ·ATR1) — the example's "15 low bound near the 60 low bound" |
| exz | H's **opposite** zone was touched earlier in the *current* H candle (short: `H_cb_inzone_long` seen since the H candle opened), is not touched now, and close is ≥ 1 ATR1 above H's long zone line — "60 low executed, continues up" |
| span ratio | (H_cb_high − H_cb_low)/(T_cb_high − T_cb_low); nesting = T's range inside H's range |

# Variants (veto ANDed into the own forming EMA-25 flag e25; pairs 15<60, 15<240, 60<240, ladder)

| key | veto when |
|---|---|
| pos{q} | f < q, q ∈ {0.15, 0.25, 0.35, 0.5} — q frozen on 2y |
| room{k} | room_H < k ATR1, k ∈ {1, 2, 3, 5} |
| nest{δ} | nest_δ true, δ ∈ {0.5, 1, 2} |
| exz | exz true |
| exzpos | exz ∧ f < q* |
| mirpos | f > 1 − q* (opposite sign, control) |
| sh+ | pos_H read 1440 rows (24 h) earlier (placebo, same pass rate) |

# Steps

1. Descriptive geometry over 2y and oos2m (all rows and the e25 entry minutes): span ratios, nesting share, bound
   coincidence rates per pair, distribution of f at the fires, outcome of the e25 entries by f-decile / nest / exz.
2. Tier B (2y → fit q, k, δ per family by paired Δ vs e25 with a ≥ 60 % entry-retention floor; oos2m scored once
   with the frozen values; the full grids printed for both tiers but labelled). Hold 60 primary.
3. Paper replay (84 h, the trend-filter harness) with the frozen variants + mirror + placebo; gates: fires
   reproduced vs the recorded CbZoneEntry rows, stored cb_high/low present at the trades.
4. Stability: bootstrap CI, months with Δ > 0, per tf / side, halves / days on paper; fee sensitivity.
5. Results + register.

# Constraints

Read-only; no executor or main/ change. Candle stop, cbnc target, set-C entries as the predecessors. Nothing fitted
on the replay window or on oos2m.

# Locked decisions (author's assumptions — the user was not available; flagged in the report)

| # | Decision | Choice |
|---|---|---|
| 1 | "bounds" | the closed-candle CB bounds `{tf}_cb_low / cb_high` (the zone lines are lo + f·span / hi − f·span, so position in the bound range and in the zone range are affine) |
| 2 | "near the lower bound of 60" | nest_δ in ATR1 units (δ 0.5 / 1 / 2) and the range-share f; both reported |
| 3 | "60 continues moving up" | exz (opposite zone executed this H candle, price now ≥ 1 ATR1 away from it), plus f as the continuous version |
| 4 | filter semantics | veto ANDed into e25 (the live flow); no replacement of the own flag |
| 5 | fit / score | thresholds chosen on 2y only (paired Δ, retention ≥ 60 %), oos2m scored once; paper replay decides the sign on the live flow |
| 6 | stop / fill / fees / window | as the predecessors: candle stop, fire-trade fill, paper fees 0 (+ fee rows), window 10-17 22:00Z → 10-21 10:07Z |
