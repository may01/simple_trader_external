# rule2_removal — the CB zone entry without the wick / zone-rejection signal

**Date:** 2026-10-21 · **Status:** done (negative — no measurable change) · **Branch:** none (read-only replay over the `cbov-check` paper postgres)
**Run report:** [`executor/runs/2026-10-21-rule2-removal-replay.md`](../../../executor/runs/2026-10-21-rule2-removal-replay.md) · **Results:** [`results/rule2_removal_results.md`](results/rule2_removal_results.md)

## Hypothesis

The live CB zone entry (`CbZoneEntryCheck`) opens on either of two rules: rule 1 = price in the zone ∧ 1-min
trade-price MA class in the direction; rule 2 = the previous 1-min candle's wick crossed the zone and the candle closed
back outside it ∧ class neutral-or-direction. User question: how does the profit change if rule 2 is removed?
H0: no change beyond the bootstrap noise. H1: the rule-2 fires (neutral-class, earlier entries) are net negative and
their removal raises the net.

## Locked decisions (author's calls — user not available during the run)

| # | decision | choice | date |
|---|---|---|---|
| 1 | data | the `cbov-check` paper stack's own tables, whole CB-armed history 10-18 11:41Z → 10-21 10:05Z (70.4 h) | 2026-10-21 |
| 2 | method | fire-re-deriving numpy replay (copy of the `ma-window-by-tf` harness, cb-candle-stop @ a6a5bc6 port), variants = rule sets {live, r1, r2} | 2026-10-21 |
| 3 | stop / exit / sizing | today's candle stop, trend-flip exit and sizing, held fixed for every variant | 2026-10-21 |
| 4 | significance | paired 6-h-block bootstrap of the variant difference + per-variant bootstrap CI; slices: candle-stop era, last 24 h, previous 24 h | 2026-10-21 |
| 5 | no fitting | no parameter touched; nothing selected on any window | 2026-10-21 |

## Outcome

See the results file. Headline: full window +2 694 → +3 073 (Δ +378, P(Δ<0) 0.29, 16 % fewer trades, PF 1.42 → 1.62);
last 24 h −258, candle-stop era −167, previous 24 h +50. Sign flips by window; keep rule 2.
