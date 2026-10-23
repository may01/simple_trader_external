# Volume / 5-min buy−sell flow / book-depletion markers at the CB zone entry — Results & Conclusion

**Date:** 2026-10-21 **Spec:** `experiment/volume_flow_entry_filter.md` **Branch:** none (read-only replay; scripts in
`executor/runs/`) **Run report:** `executor/runs/2026-10-21-volume-flow-replay.md` (all tables, per-cell, per-day).
**Data:** paper run LINKUSDT 2026-10-18 11:41 → 10-21 18:04 (78.4 h, 612 358 trades, 202 simulated / 207 recorded
fires, 186 / 130 positions; depletion rows 697 253); 2y `2y_az_link_usdt` + `2y_link_usdt` (2023-01 → 2024-12,
1 052 560 rows), oos2m `oos2m_link_usdt` (2025-01 → 2025-03, 84 961 rows).
**Pipeline:** `executor/runs/2026-10-21-volume-flow-replay.py` (stop-re-entry harness + features + `vol` gate),
`executor/runs/2026-10-21-volume-flow-2y-oos2m.py` (bounds-geometry tier-B stand-in + flow features).
**Final configuration:** features trailing from the fire tick, w ∈ {1, 5, 15} min, rv = vol / trailing-2 h median,
depletion "on" = a row within 60 s; filters = skip the fire; paired 6-h block bootstrap vs live; 2y freeze on the
tf-15 cells with ≥ 60 % retention, oos2m scored once.

## Headline conclusion
On the paper run the fires taken on climax volume (rv5 top quintile ≥ 2.3) or under an active 60-min depletion
marker stop out 60–62 % vs 36–43 % and account for the losses (−705 / −539 on +2 679); the 5-min buy−sell flow
direction is weak (|ρ| ≤ 0.1, AUC 0.43) with "flow already with the trade = fewer stop-outs" as the only sign.
Skipping `rv5 > 3` (+763, P 0.06), `rv15 > 3` (+699, P 0.00) or `dep60_on` (+881, P 0.07) is positive on both
halves, in the candle era and on 4/4 (3/4) days, above the random-skip band — a lead of +700…+900 on 15–43 skipped
fires. It is NOT proven: the 2y / oos2m stand-in shows zero correlation (|ρ| ≤ 0.06) and every climax / flow veto
is negative on oos2m (−3 354 … −7 970); flow-direction filters are negative everywhere; fees (−10 … −14 k at
0.1 %/side) dwarf any filter.

## The progression (Δ net vs live, paper; Δ vs e25, 2y / oos2m)

| filter (skip when) | paper full 78 h | paper era 30 h | split first / second | 2y (frozen) | oos2m (score) |
|---|---|---|---|---|---|
| live / e25 base | +2 679 (186) | +411 (53) | | +166 435 (57 383) | +15 827 (4 414) |
| rv5 > 3 (climax) | +763 (P 0.06) | +411 (0.01) | +315 / +448 | rv1 > 3: +9 150 (0.25) | −3 417 (0.81) |
| rv15 > 3 | +699 (0.00) | +201 (0.05) | +293 / +406 | −3 372 (0.75) | −5 952 (0.99) |
| dep60_on | +881 (0.07) | +509 (0.13) | +277 / +604 | n/a (no book history) | n/a |
| dep15_on | +346 (0.12) | +259 (0.07) | | n/a | n/a |
| dep240_on / depany_on | −582 / −200 | +108 / +139 | | n/a | n/a |
| adv5 < −0.2 (flow against) | −431 (0.62) | +513 (0.19) | +152 / −583 | −62 185 (1.00) | −11 569 (0.98) |
| adv15 < −0.5 | +950 (0.00) | +825 (0.00) | +71 / +879 | −1 315 (0.62) | −94 (0.51) |
| adv5 > 0.1 (flow already with) | −1 505 (0.97) | −362 (0.93) | | adv1 > 0.2: +12 390 (0.11) | −3 354 (0.85) |
| rv5 < 0.7 (dead tape) | −2 365 (1.00) | −56 | | −22 899 (0.99) | rv5 < 0.5: −3 457 (0.92) |
| random skip 10 / 20 % | −258 / −479 (8 seeds) | | | | |
| shifted-24 h placebo rv5 > 1.5 / dep60_on | −142 / −131 | +193 / −37 | | sh rv1 > 3: −16 389 | −238 |

## Degeneracies found
1. The best first-half variant is a placebo (`sh24_adv5_gt0.2` +718 → −378): single-window selection among ~60
   variants is noise; only family-level consistency (rv climax, dep60) was read as a lead.
2. `dep15_agree` / `adv15 > 0.5` show "P 0.00" on Δ +13 — one fire changed; the bootstrap P is meaningless when
   < 3 blocks change. Reported but discarded.
3. Fires happen with the flow against them by construction (adv5 median −0.13 vs +0.01 at random ticks); a
   "skip when flow is against" filter removes the normal fire, not a bad one — negative on 2y at every threshold.

## Validity gates
- Reproduction: 200/207 recorded fires matched within 60 s, 54/55 candle stops within half a tick; 2y zone lines
  = lo + 0.0500·span as stored; volume columns finite 100 %.
- Null floor / placebo: random skip 20 % mean −479 (−1 195 … 0); shifted-feature controls −142 / −131 (paper),
  −16 389 (2y rv); the candidates (+699 … +881) sit above both; the era's noise floor is ±600 (placebo +596).
- Base rate: stop-out 47 % (sim) / 58 % (recorded); the worst quintiles 60–63 %, the best 32–36 %.
- Split-half: 16 of 32 first-half-positive variants hold (50 %); the rv family and dep60 hold.
- Look-ahead: all features trailing from the fire tick (trades ≤ t, depletion rows ≤ t); 2y features from rows ≤ t
  with the entry at row t's close.
- Provenance: oos2m scored only with the 2y-frozen (advlt0.5_w15, advgt0.2_w1, rvgt3.0_w1, rvlt0.5_w5); the oos2m
  grid is printed post hoc and shows the same sign everywhere (all rv > k negative).
- Truth ladder: |ρ| 0.2 (paper, n 186) → 0.05 (2y, n 44 000) → 0.03 (oos2m) for the same quantities — the paper
  correlation is small-sample or feed-specific.

## What generalized vs what did not
- Held on the paper window only: climax-volume skip (rv1/5/15 > 2–3), 60-min depletion marker skip; "low volume
  fires are the best" (skipping them −2 365).
- Did not: flow direction as a filter (both tails negative or noise on paper, negative on 2y / oos2m); climax skip
  on 2y / oos2m (negative); the 240-min marker (on 56 % of minutes, no information); marker direction (agree
  almost never on at a fire).

## Config & artifacts
Scripts + outputs in `executor/runs/2026-10-21-volume-flow-*`; data export in the script header (scratchpad copy
not kept); nothing in the code repo; nothing committed.

## Next arbiter
User decision 2026-10-21: no executor change; re-score offline from the DB after two more paper weeks — task
`plans/2026-11-04-volume-flow-rescore.md` (recipe, out-of-sample boundary ms 1792605863000, decision rule fixed in advance).

Log `rv5`, `rv15`, `dep60_on` on every decision for two more weeks of paper and re-score the three skips on the new
window (out-of-sample by construction); the 2y question needs the executor's own feed (aggTrades) rather than
klines taker volume to settle whether the paper correlation is real or feed-specific.
