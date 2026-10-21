# rule2_removal — Results & Conclusion

**Date:** 2026-10-21 · **Run report (the full document):** [`executor/runs/2026-10-21-rule2-removal-replay.md`](../../../../executor/runs/2026-10-21-rule2-removal-replay.md) · **Script / outputs:** beside it · **Branch:** none (read-only replay over the `cbov-check` paper postgres; no code-repo change)
**Data:** Binance LINKUSDT paper stack, 2026-10-18 11:41Z → 2026-10-21 10:05Z (70.4 h, 527 892 trades, 42 CB indicator names with expiry, 188 recorded CbZoneEntry fires for the reproduction gate).
**Pipeline:** numpy port of `CbZoneEntryCheck` + `signals::trend` + `compute_candle_stop` + the orchestrator's open / skip / reversal + the trend-flip exit; every fire recomputed from the stored indicators and trades; today's candle stop held fixed for every variant.
**Configuration under test:** the entry's rule set — live (rule 1 in-zone + rule 2 zone-rejection), r1 (rule 1 only = the question), r2 (rule 2 only, ablation).

## Headline conclusion

**Negative — removing rule 2 does not change the profit measurably.** Full window: net +2 694 (live, 168 positions)
→ +3 073 (r1, 141 positions), Δ +378 with a paired 6-h-block 90 % CI [−788, +1 542], P(Δ<0) 0.29; PF 1.42 → 1.62,
win rate 51 → 59 %, 16 % fewer trades. On the three slices the sign flips: candle-stop era −167 (P 0.73), last 24 h
−258 (P 0.69), previous 24 h +50 (P 0.47). Rule 2 on its own (r2) is +2 094 on the full window but the best variant in
the candle-stop era (+817 vs +425). Mechanism: rule 2 opens almost no zone that rule 1 would not — 153 of the 183 live
fire keys fire in r1 too (117 in the same minute, 36 later, up to +12.6 min); the 30 rule-2-only zones are worth +289
together. Rule 2's content is "the same zone a few minutes earlier, before the MA class confirms", and those earlier
fills are neither systematically better nor worse on 70 h. Not proven: anything about fees (paper), other regimes, or
a "rule 2 only with class = direction" variant (9 positions here, not run).

## The progression

| variant | rules | trades | net | PF | win rate | stop-outs | net at 0.1 %/side | r1/r2 − live paired Δ (full) |
|---|---|---|---|---|---|---|---|---|
| live | 1 + 2 | 168 | +2 694 | 1.42 | 51 % | 79 | −13 023 | — |
| **r1** | 1 | 141 | +3 073 | 1.62 | 59 % | 56 | −9 808 | +378 [−788, +1 542] P 0.29 |
| r2 | 2 | 150 | +2 094 | 1.41 | 52 % | 62 | −11 160 | −600 [−1 405, +254] P 0.88 |

Slices (r1 − live): candle-stop era 10-20 20:25Z → (13.7 h) −167 [−797, +463]; last 24 h −258 [−1 040, +618];
previous 24 h +50 [−415, +617]. Per day r1 wins 10-18 (+771 vs +542), 10-19 (+651 vs +330), 10-21 (+291 vs +138),
loses 10-20 (+1 361 vs +1 684).

## Gates (numbers in the run report §2)

Reproduction 181/188 recorded fires re-fired (rule + class 180/181, `ma_slope` median rel. diff 3.1e-8; the 7 misses
sit at the three executor restarts), candle-stop port 36/37 within half a tick; null floor: live CI [+457, +4 946],
r1 [+1 083, +5 128], r2 [+134, +4 174], paired Δ CIs all contain zero; top-2 trades +691…+733 in every row (the same
two 240 trades); split halves disagree in sign (r1 +573 ahead first half, −194 behind second); no parameter fitted;
look-ahead by construction.

## Degeneracies found

None in the objective (nothing optimised). One reading trap: the live rule-2 positions are themselves profitable
(72, +1 199, PF 1.45) — removing them helps on the full window only through displacement (the same zones re-fire by
rule 1 later, 7 of them handed to the 60 zone's farther target), not because the rule-2 trades lose.

## Disposition

No branch, nothing to merge. Docs only: this file, the spec `rule2_removal.md`, the run report + script + four
outputs in `executor/runs/`, the REPORT.md row and entry. Keep rule 2 as it is. Re-run with `--t0=` once ≥ 2 weeks of
trades exist; the fee question (breakeven ≈ 0.017 %/side live, 0.024 % r1) outranks this toggle.
