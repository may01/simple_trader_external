---
archetype: full-snapshot-dense
decision: promote
holdout_acc: 0.7267094373822414
holdout_loss: null
hypothesis: 'Swap layer[0] dense->conv1d (kernel 3) over the h=4 window: extract local
  temporal pattern across the 4 bars directly rather than flattening the window into
  the dense input.'
next_hypothesis: 'Swap layer[0] conv1d->conv1d_seq: conv1d mean-pools the 4-bar window
  away after extracting features; conv1d_seq preserves the per-bar sequence so the
  head keeps WHERE in the window the pattern occurred - and sets up a recurrent (gru)
  stage next.'
parent: v2
per_class: {}
spec_hash: 1a7c5b97a920acbd5e103a4cdd060ac684f93ff95a1cdaef1231925664aedc16
strike: 0
version: 3
---

## v3 - conv1d local-pattern front (dense[0] -> conv1d)

**Hypothesis.** v2 showed a 4-bar window lifts score (+0.032) but flattens the window
into a plain dense input. Replace the first dense with a conv1d (kernel 3) so the
model extracts local candle/pattern structure across the 4 bars directly (shape, not
flattened values). One structural change vs v2; h=4 and the two trailing dense layers
unchanged; Optuna re-tuned units/lr/dropout.

**Result.**

| metric | value | vs incumbent (v2) |
|---|---|---|
| holdout_score | 0.7267 | +0.0167 |
| holdout_loss | not recorded | - |
| per-class recall | not recorded (binary long-vs-other) | - |

8-trial Optuna over conv1d(k3) -> dense -> dense / h=4 (conv filters = L1 units):

| conv filters | holdout_score |
|---|---|
| 51 | 0.7267 (incumbent) |
| 54 | 0.7301 (raw best, < margin over incumbent) |
| 22 | 0.7293 |
| 36 | 0.7056 |
| 59 | 0.6900 |
| 63 | 0.6885 |
| 44 | 0.6502 |
| 32 | 0.5954 |

**What went good.** The conv front cleared the margin again: +0.0167 over v2's 0.7100.
Modelling the window's local pattern beats flattening it - the archetype is now at
0.7267, up +0.0486 over the v1 snapshot baseline across two structural moves
(window, then conv).

**What went bad.** conv1d mean-pools the time axis away after the conv, discarding
where in the 4-bar window a pattern sits; the ordered structure of the window is only
partially used. Trial variance is high (0.595-0.730) - some conv-filter settings
collapse - but Optuna owns that (units), not Tier 2. Still no per-class/confusion
(binary target, metrics null).

**What to improve.** Stop throwing away the window's temporal order. Preserve the
per-bar conv features so a sequence model can use them; this is the setup for adding a
recurrent stage (the conv_seq -> recurrent structure that won the recurrent-temporal
archetype).

**Decision.** promote - "promote: +0.0167 >= margin 0.0100". Next hypothesis: swap
layer[0] conv1d->conv1d_seq (one structural change; preserves the sequence for a gru
in the next version).
