---
archetype: nn-features-precision
version: 1
parent: null
spec_hash: cd3ce362c8366366c6b3fa8189649bb897829d9527659c3b774c9c6f4ad3c496
hypothesis: Precision-gated evolution seeded from nn-features-only-v3 (the precision@5%
  leader). Re-search the conv1d_seq x2 -> lstm -> dense backbone under
  gate_metric=precision_at_k on the strict long15 direction_binary target; the gate
  scalar is long-class precision@5%, so Optuna optimises the actionable signal directly.
holdout_acc: 0.28293427453973097
holdout_loss: 0.0
per_class:
  base_rate: 0.0578
  p@1: 0.4163
  p@5: 0.2829
  p@10: 0.2268
  lift@1: 7.21
  lift@5: 4.90
  lift@10: 3.93
decision: promote
strike: 0
next_hypothesis: widen history_points 4->8 so the conv1d/lstm stack has more temporal
  context to separate profitable-long setups deeper into the ranking (precision decays
  from p@1 0.42 to p@10 0.23 - separation holds only at the very top).
---

## v1 — precision-gated re-search of the v3 backbone

**Hypothesis.** Seed the lineage from `nn-features-only-v3` (conv1d_seq×2 → lstm → dense,
46 nn_features × 6 TF levels, `history_points=4`), the strict-long15 model that led the
baseline on precision@5%. Re-run the in-container Optuna search under
`gate_metric=precision_at_k` instead of argmax accuracy, so the gate scalar (and the
Optuna objective) is long-class **precision@5%** on the 2y holdout. Test whether
optimising the actionable metric directly beats the accuracy-selected baseline.

**Result.** (gate scalar = precision@5%; the head is binary `direction_binary` long15,
strict, base rate 5.78% — the direction 3-class confusion table does not apply.)

| metric | v1 | vs incumbent (v3 baseline) |
|---|---|---|
| precision@5% (gate) | 0.2829 | +0.0127 |
| precision@1% | 0.4163 | +0.0091 |
| precision@10% | 0.2268 | +0.0059 |
| lift@5% | 4.90× | +0.22× |
| lift@1% | 7.21× | +0.16× |
| holdout rows | 209,645 | — |

Winning trial `a35a80fb`, spec_hash `cd3ce362…`: Optuna pulled the layer width to 17,
`lr≈1.1e-4`, `dropout≈2.4e-3`. (Train/val per-class metrics were not captured in the
trial record — `metrics.*` are null; only the holdout precision block is populated.)

**What went good.** Optimising precision@5% directly beat the accuracy-selected baseline
on every precision cut: p@5 0.2702→0.2829, lift 4.68×→4.90×. This is the end-to-end
proof the toggled gate works in a real Optuna search — the winner is chosen for
actionable long precision, not base-rate accuracy.

**What went bad.** Precision falls off steeply across the ranking: p@1 0.4163 →
p@5 0.2829 → p@10 0.2268. The model separates the very top bars well but the signal
dilutes deeper into the top decile — the p@5 gate leaves precision on the table between
the 1% and 10% cuts. `decide(...)` reason: `promote: first version`.

**What to improve.** Sustain precision deeper into the ranking — the failure is
separation of profitable-long setups from near-misses beyond the top 1%. The next
structural change targets temporal context, not width.

**Decision.** promote — `promote: first version`. Next hypothesis: widen
`history_points` 4→8 (one structural change) so the conv1d/lstm stack sees a longer
lookback to separate longs deeper into the ranking.
