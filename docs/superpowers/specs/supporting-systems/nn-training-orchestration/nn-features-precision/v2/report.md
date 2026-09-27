---
archetype: nn-features-precision
version: 2
parent: v1
spec_hash: 1b8ba79eba47b55a0527653c8359a98848e6481c405b1a2840afca852034c5dc
hypothesis: Widen history_points 4->8 so the conv1d/lstm stack has more temporal context
  to separate profitable-long setups deeper into the ranking (v1 precision decayed from
  p@1 0.42 to p@10 0.23).
holdout_acc: 0.2677218225419664
holdout_loss: 0.0
per_class:
  base_rate: 0.0578
  p@1: 0.3976
  p@5: 0.2677
  p@10: 0.2165
  lift@1: 6.87
  lift@5: 4.63
  lift@10: 3.74
decision: revert
strike: 1
next_hypothesis: swap lstm->gru; the wider window overfit (v2 regressed), so try a
  lighter recurrent kind whose simpler gating often generalises better on the short
  4-step window and may sustain precision deeper into the ranking.
---

## v2 — widen history_points 4→8

**Hypothesis.** v1 precision decayed steeply across the ranking (p@1 0.42 → p@10 0.23),
suggesting the model separated only the very top bars. Widen `history_points` 4→8 to give
the conv1d/lstm stack a longer lookback to distinguish profitable-long setups deeper into
the top decile. One structural change; everything else = incumbent v1.

**Result.** (gate scalar = precision@5%; binary strict long15, base rate 5.78%.)

| metric | v2 | incumbent v1 | Δ |
|---|---|---|---|
| precision@5% (gate) | 0.2677 | 0.2829 | **−0.0152** |
| precision@1% | 0.3976 | 0.4163 | −0.0187 |
| precision@10% | 0.2165 | 0.2268 | −0.0103 |
| lift@5% | 4.63× | 4.90× | −0.27× |
| holdout rows | 208,493 | 209,645 | — |

Winning trial spec_hash `1b8ba79e…`: `history_points=8`, Optuna widened units to 59,
`lr≈7.5e-4`.

**What went good.** Nothing on the gate — every precision cut regressed. The run
completed cleanly under the precision gate (full ~1h wall cap), confirming the toggled
pipeline is stable across structural variants.

**What went bad.** The longer window *lowered* precision at every cut (p@5 0.2829→0.2677).
Optuna compensated with much wider layers (22→59 units) yet still lost ground — the extra
temporal context did not help separation and likely added noise/overfit. `decide(...)`
reason: `revert: -0.0152 < margin (strike 1/2)`.

**What to improve.** Temporal context is NOT the bottleneck (widening it hurt). Target the
recurrent block's generalisation instead: at the short 4-step window a full LSTM may
overfit. The next structural change swaps the recurrent kind, not the window.

**Decision.** revert — `revert: -0.0152 < margin (strike 1/2)`. Incumbent remains v1
(p@5 0.2829). Next hypothesis: swap `lstm`→`gru` (one structural change) on the incumbent
v1 backbone (history_points back to 4).
