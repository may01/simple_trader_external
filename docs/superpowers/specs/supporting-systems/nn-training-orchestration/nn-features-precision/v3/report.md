---
archetype: nn-features-precision
version: 3
parent: v1
spec_hash: fecec1c8f27411715fb2c9bb0b718e05a952b86f5b1549bfdb124325c80b8fa5
hypothesis: Swap lstm->gru on the incumbent v1 backbone (history_points back to 4). v2's
  wider window overfit and regressed, so try a lighter recurrent kind whose simpler gating
  often generalises better on the short 4-step window and may sustain precision deeper
  into the ranking.
holdout_acc: 0.2727272727272727
holdout_loss: 0.0
per_class:
  base_rate: 0.0578
  p@1: 0.3848
  p@5: 0.2727
  p@10: 0.2223
  lift@1: 6.66
  lift@5: 4.72
  lift@10: 3.85
decision: revert
strike: 2
next_hypothesis: null
---

## v3 — swap lstm→gru

**Hypothesis.** v2 showed temporal context is not the bottleneck (widening the window
hurt). Swap the recurrent kind `lstm`→`gru` on the incumbent v1 backbone (history_points
back to 4) — gru's simpler gating often generalises better on short sequences and might
sustain precision deeper into the ranking. One structural change from incumbent v1.

**Result.** (gate scalar = precision@5%; binary strict long15, base rate 5.78%.)

| metric | v3 | incumbent v1 | Δ |
|---|---|---|---|
| precision@5% (gate) | 0.2727 | 0.2829 | **−0.0102** |
| precision@1% | 0.3848 | 0.4163 | −0.0315 |
| precision@10% | 0.2223 | 0.2268 | −0.0045 |
| lift@5% | 4.72× | 4.90× | −0.18× |

Winning trial spec_hash `fecec1c8…`: `gru` recurrent block, `history_points=4`, Optuna
units 31, `lr≈1.1e-4`.

**What went good.** gru recovered most of the ground v2 lost — p@5 0.2677→0.2727, and
p@10 (0.2223) came within 0.0045 of the incumbent. So the recurrent kind matters less
than expected; gru ≈ lstm at this window, marginally behind.

**What went bad.** Still below the incumbent at every cut, most at the top (p@1
0.4163→0.3848). gru did not beat the v1 lstm on the precision gate. `decide(...)` reason:
`stop: 2/2 strikes`. This is the **second consecutive revert** — the lineage stop
condition (K=2) fires.

**What to improve.** Two single-lever structural edits off v1 (wider window, lstm→gru)
both failed to beat v1's `conv1d_seq×2 → lstm → dense` at history 4. v1's architecture is
a local optimum under this feature set and gate; further gains likely need a different
lever than recurrent shape — e.g. the target labelling (`label_m`/`label_x`/`label_y`
clean-entry band) or an added indicator group — not explored within this lineage's budget.

**Decision.** revert — `stop: 2/2 strikes`. **Lineage stops** (K=2 consecutive reverts).
**Winner = v1** (p@5 0.2829, lift 4.90×; conv1d_seq×2 → lstm → dense, history_points 4).
