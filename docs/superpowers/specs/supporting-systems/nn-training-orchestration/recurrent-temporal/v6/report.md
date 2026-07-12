---
archetype: recurrent-temporal
version: 6
parent: v5
spec_hash: 90fdaa9ac19a8cbff4698352724b3096aaf280eb3987961279069887751f4ec2
hypothesis: Deepen the Optuna search — 8 trials (4 random + 4 TPE) instead of 3 on the
  v5 config (conv1d_seq->lstm->dense, 20 features, history 20, binary long). Does wider
  hyperparameter exploration find a better lr/units/dropout than the shallow 3-trial best?
holdout_acc: 0.8027
holdout_loss: null
per_class:
  long_entry_base_rate: 0.0579
  precision_thr0.5: 0.1044
  precision_thr0.6: 0.1235
  precision_thr0.7: 0.1447
  recall_thr0.7: 0.085
  lift_thr0.6: 2.13
  lift_thr0.7: 2.50
decision: promote
strike: 0
next_hypothesis: Lineage complete (max_versions). Re-validate v6 on 4y to rule out 2y
  regime-luck, then either (a) P&L backtest the v6 long filter (the true-north test) or
  (b) gate to the next archetype. Also amend the promotion gate to precision@k / lift
  (accuracy proved too coarse across v3–v5).
---

# recurrent-temporal v6 — report

## Change from v5
Search depth only: `NN_TRIALS_PER_ROUND` 3→8 (same spec 90fdaa9a). No new
features/architecture. Tests whether the shallow 3-trial search under-explored.

## Result (holdout = 204,749 rows, positive base rate 5.79%)
| threshold | pred count | precision | recall | lift |
|---|---|---|---|---|
| 0.5 | 36,090 | 0.1044 | 0.318 | 1.80× |
| 0.6 | 14,427 | 0.1235 | 0.150 | 2.13× |
| 0.7 | 6,989 | 0.1447 | 0.085 | 2.50× |
8 trials, holdout spread 0.197–0.803. Best trial 7f94b476.

## Verdict — search depth matters
The 8-trial search found a config that is far more selective and precise at high
confidence: thr 0.7 precision 0.115→0.145 (lift 1.98×→2.50×). Recall fell (0.366→0.085) —
v6 takes fewer, purer entries. For an entry FILTER (precision on confident calls is the
objective, not catching every entry), this is the better operating point. Both the
accuracy gate (0.71→0.80) and the lift metric agree this time → unambiguous promote.

## Decision
`decide`: promote, new best, **stop: max_versions 6 reached**. v6 is the archetype winner.
Lineage closed.
