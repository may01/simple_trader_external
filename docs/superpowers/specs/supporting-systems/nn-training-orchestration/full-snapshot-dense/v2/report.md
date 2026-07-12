---
archetype: full-snapshot-dense
decision: promote
holdout_acc: 0.7100050084666937
holdout_loss: null
hypothesis: Widen the input window (history_points 1->N) so the dense stack sees recent
  trajectory, not a single instant. Planned N=8; the h=8 build OOM'd on 15GB RAM (474
  cols x 8 x 1.05M rows), so realized at N=4 (largest window that fits).
next_hypothesis: 'Swap layer[0] dense->conv1d (kernel 3) over the h=4 window: the
  window lifted score +0.032, so recent-trajectory signal is real; a conv front extracts
  local temporal PATTERN across the 4 bars directly instead of flattening the window
  into the dense input.'
parent: v1
per_class: {}
spec_hash: 1ea89ee93aba60492a8c780b658578218367788fff8307449f86073153b3ca70
strike: 0
version: 2
---

## v2 - short lookback window (history_points 1->4)

**Hypothesis.** v1's holdout plateaued at 0.667-0.683 across every Optuna width/lr/
dropout setting - the single-instant SHAPE was saturated. Widen the input window so
the dense stack can see recent trajectory. Planned history_points=8; that build was
SIGKILLed (OOM) - h=8 needs an ~6.8GB per-timeframe float64 block on top of the
~4.8GB resident df, over the 15GB host RAM. Retried at history_points=4 (the largest
window that fits), one structural change vs v1; layer kinds/count unchanged, Optuna
re-tuned units/lr/dropout.

**Result.**

| metric | value | vs incumbent (v1) |
|---|---|---|
| holdout_score | 0.7100 | +0.0319 |
| holdout_loss | not recorded | - |
| per-class recall | not recorded (binary long-vs-other) | - |

8-trial Optuna over the fixed conv-less dense x3 / h=4 shape:

| units (L1) | holdout_score |
|---|---|
| 36 | 0.7100 (incumbent) |
| 59 | 0.6929 |
| 16 | 0.6930 |
| 54 | 0.6902 |
| 31 | 0.6874 |
| 51 | 0.6828 |
| 38 | 0.6771 |
| 23 | 0.6334 |

**What went good.** The window broke the v1 plateau: +0.0319 over v1's 0.6781, clearing
the 0.01 promotion margin cleanly. The recent-trajectory signal that a single-instant
snapshot could not see is real - myopia was a genuine limiter, not just tuning noise.
h=4 also fits the 15GB RAM box, so the archetype stays runnable.

**What went bad.** The planned h=8 is infeasible here (OOM), so the window is capped at
4 by hardware - the fuller-window version of this hypothesis cannot be tested on this
box. Score spread across trials is wider than v1 (0.633-0.710) but still no per-class /
confusion data (binary target, metrics null), so the *nature* of the remaining errors
is unobserved.

**What to improve.** The window carries signal but is flattened into a plain dense
input; the model does not model the 4-bar temporal structure explicitly, and the
window cannot grow (RAM). Extract the window's local pattern more efficiently instead
of widening it.

**Decision.** promote - "promote: +0.0319 >= margin 0.0100". Next hypothesis: swap
layer[0] dense->conv1d (kernel 3) over the h=4 window (one structural change; conv
kinds are buildable; Optuna re-tunes units/lr/dropout).
