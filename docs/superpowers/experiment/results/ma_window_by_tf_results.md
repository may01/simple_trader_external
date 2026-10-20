# ma_window_by_tf_replay — Results & Conclusion

**Date:** 2026-10-20 · **Run report (the full document):** [`executor/runs/2026-10-20-ma-window-by-tf-replay.md`](../../../../executor/runs/2026-10-20-ma-window-by-tf-replay.md) · **Script / output:** beside it · **Branch:** none (read-only replay over the `cbov-check` paper postgres; no code-repo change)
**Data:** Binance LINKUSDT paper stack, 2026-10-18 11:41Z → 2026-10-20 21:24Z (57.7 h, 450 017 trades, 42 CB indicator names with expiry, 152 recorded CbZoneEntry fires for the reproduction gate).
**Pipeline:** numpy port of `CbZoneEntryCheck` + `signals::trend` + `compute_candle_stop` + the orchestrator's open / skip / reversal + the trend-flip exit; every fire recomputed from the stored indicators and trades; today's candle stop (0.2 % placeholder) held fixed for every variant.
**Final configuration under test:** trailing-mean window of the trend class per tf, in 10-s buckets — live 6 / 6 / 6 (tf 15 / 60 / 240); user's variants 6 / 18 / 18, 6 / 30 / 30 (3, 5 min for the 60 and 240 zones) and 6 / 6 / 60, 6 / 6 / 90 (10, 15 min for the 240 zone); exit-too and all-tf ablations.

## Headline conclusion

**Negative.** A slower trade-price MA as the activation class for the higher-tf zones does not raise the profit: net
+2 489 (live) → +2 482 (3 min) → +2 128 (5 min); 240 zone alone at 10 / 15 min → +2 226 / +1 861. On the tf 60 + 240
positions +772 → +572 → +242 (3 / 5 min), +542 / +311 (10 / 15 min). Every difference is inside the bootstrap 90 % CI
(the subset CIs all contain zero), but the mechanism is uniform and not noise: the slower class fires the **same**
(side, tf, zone) keys later (median +0.6 … +1.8 min, up to +43 min), the 15-min-anchored stop does not move, the
reversal / trend-flip exits land at the same price, so winners shrink and losers stay; 6–8 tf-60 trades are taken by
the 15-min zone first and inherit its nearer target. Not proven: anything about fees (paper), other regimes, or
whether a *different* higher-tf filter would help — only that a slower version of the same signal does not.

## The progression

| variant | entry window tf 15 / 60 / 240 | trades | net | PF | tf 60+240: n, net, PF |
|---|---|---|---|---|---|
| live | 6 / 6 / 6 | 135 | +2 489 | 1.48 | 35, +772, 1.49 |
| e3 | 6 / 18 / 18 | 134 | +2 482 | 1.52 | 28, +572, 1.54 |
| e5 | 6 / 30 / 30 | 133 | +2 128 | 1.45 | 27, +242, 1.24 |
| x3 / x5 (exit too) | as e3 / e5 | 134 / 133 | +2 381 / +2 097 | 1.50 / 1.45 | +471 / +211 |
| t10 | 6 / 6 / 60 | 136 | +2 226 | 1.44 | 35, +542, 1.38 |
| t15 | 6 / 6 / 90 | 135 | +1 861 | 1.36 | 35, +311, 1.19 |
| x10 / x15 (exit too) | as t10 / t15 | 136 / 135 | +2 152 / +1 826 | 1.42 / 1.35 | +468 / +275 |
| a3 / a5 (slow MA every tf) | 18 / 18 / 18, 30 / 30 / 30 | 125 / 114 | +1 723 / +1 042 | 1.43 / 1.27 | +277 / +83 |

## Gates (numbers in the run report §2)

Reproduction 145/152 recorded fires re-fired (rule + class 144/145, `ma_slope` median rel. diff 2.6e-8; the 7 misses sit at the three executor restarts); null floor: live CI [+431, +4 597], e3 [+537, +4 433], e5 [+203, +4 111], t15 [−113, +3 974]; top-2 trades +675…+733 in every row (the same two 240 trades); split halves agree; ablation a3 / a5 worse everywhere; no parameter fitted; look-ahead by construction (indicators by `received_at ≤ t`, bars closed before the minute).

## Degeneracies found

None in the objective (nothing optimised). One bookkeeping trap: the per-tf table shows "tf 60 worse, tf 15 better" under the slower class — mostly re-labelling (the 60 fire arrives seconds after the 15 fire and is skipped as same-side), so the totals and the matched-position transition tables (run report §4, §7) are the fair comparison, not the per-tf rows.

## Disposition

Keep the 1-min class on every tf. REPORT.md row closed `negative`. A fee of 0.1 %/side turns every variant to −8…−10 k — independent of this question, flagged for the live-run gate.
