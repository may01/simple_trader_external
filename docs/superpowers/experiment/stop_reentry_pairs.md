# stop_reentry_pairs — stop-out at the zone's start, re-entry minutes later from a better price

**Date:** 2026-10-21 · **Status:** done (partial — pattern confirmed, one supported fix) · **Branch:** none (read-only over the `cbov-check` paper postgres)
**Run report:** [`executor/runs/2026-10-21-stop-reentry-replay.md`](../../../executor/runs/2026-10-21-stop-reentry-replay.md) · **Results:** [`results/stop_reentry_pairs_results.md`](results/stop_reentry_pairs_results.md)

## Hypothesis

User observation: two CB zone trades close together — the first stopped out at the beginning of the zone, the second
opened soon after from a better price. H1: this is a frequent, loss-bearing pattern caused by the entry/stop rule
(not by noise), and at least one rule change removes the loss without removing the second trade's profit.

## Locked decisions (author's calls — user not available during the run)

| # | decision | choice | date |
|---|---|---|---|
| 1 | pair definition | P1 closed by stop → next position P2 same side, opened ≤ W min after P1's close, P2 entry better than P1 entry; W = 5/15/30/60, headline 15 | 2026-10-21 |
| 2 | data | recorded `position_log` (both stop eras) for the descriptive count; fire-re-deriving replay (rule2-removal harness, cb-candle-stop @ a6a5bc6) for the counterfactuals, whole CB-armed history 10-18 11:41Z → 10-21 11:16Z (71.6 h) + candle-stop era (14.9 h) | 2026-10-21 |
| 3 | candidate fixes | cooldown 5/15/30; stop offset × 1.5/2/2.5/3; anchor two-candles / rolling-15; entry depth 0.5/1.0 ranges; skip first 3/5 min of the 15-min candle; half size first leg; stop at the entry-side `cbnc` bound (± offset, wider-of, × 1.5) | 2026-10-21 |
| 4 | significance | paired 6-h-block bootstrap vs live; per-variant bootstrap CI; two windows | 2026-10-21 |
| 5 | no fitting | hand grids only; nothing selected on any window; oos2m untouched | 2026-10-21 |

## Outcome

See the results file. Headline: 43 % of simulated stop-outs are the first leg of a pair, those legs carry 43 % of all
stop-loss money (−2 795 of −6 560 in 71.6 h), the second legs recover +226 (half are stopped again). Only the wider
stop (offset × 2–2.5: +605 / +636 full, +363 era, stop-outs 82 → 54 / 43) has the right sign on both windows.
Cooldown, deeper entry, half size, candle-minute skip: dead; anchor changes: no-op (the fire is the extreme).
