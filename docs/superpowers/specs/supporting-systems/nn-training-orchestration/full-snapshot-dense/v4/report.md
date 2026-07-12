---
archetype: full-snapshot-dense
decision: revert
holdout_acc: 0.7123947625748289
holdout_loss: null
hypothesis: 'Swap layer[0] conv1d->conv1d_seq: preserve the per-bar conv features
  over the 4-bar window (instead of mean-pooling them) so the head keeps where in
  the window the pattern occurred.'
next_hypothesis: 'Add the recurrent consumer: conv1d_seq -> gru -> dense (swap dense[1]->gru).
  conv1d_seq alone regressed because nothing consumes the preserved sequence; a gru
  models the ordered 4-bar conv features - the conv_seq->recurrent shape that won
  recurrent-temporal. batch->64 (recurrent convention).'
parent: v3
per_class: {}
spec_hash: b4fb8a780b41f4d1c18a79c17d76dc7ae853b584ce0757bac8208c838936b07b
strike: 1
version: 4
---

## v4 - preserve the window sequence (conv1d -> conv1d_seq)

**Hypothesis.** v3's conv1d mean-pools the 4-bar window away after extracting local
features, discarding order. Swap it for conv1d_seq, which keeps the per-bar conv
output (B,T,C), so the trailing dense layers (and a future recurrent) can use where in
the window a pattern sits. One structural change vs the v3 incumbent; h=4 and the two
dense layers unchanged; Optuna re-tuned units/lr/dropout.

**Result.**

| metric | value | vs incumbent (v3) |
|---|---|---|
| holdout_score | 0.7124 | -0.0143 |
| holdout_loss | not recorded | - |
| per-class recall | not recorded (binary long-vs-other) | - |

8-trial Optuna over conv1d_seq -> dense -> dense / h=4:

| conv filters | holdout_score |
|---|---|
| 51 | 0.7124 (best this version) |
| 59 | 0.6989 |
| 54 | 0.6964 |
| 36 | 0.6928 |
| 44 | 0.6748 |
| 26 | 0.6635 |
| 22 | 0.6378 |
| 42 | 0.6286 |

**What went good.** Nothing net-positive: the best trial (0.7124) is below the v3
incumbent (0.7267). The version did its job as a clean isolation - it tells us
preserving the sequence, on its own, is not useful.

**What went bad.** Preserving the per-bar sequence and then FLATTENING it through plain
dense layers is strictly worse than v3's pooled conv (-0.0143, under the 0.01 margin) -
the dense head cannot exploit temporal order, it just sees a wider flattened input with
more parameters to overfit. `decide(...)` reason: "revert: -0.0143 < margin (strike
1/2)". Incumbent stays v3.

**What to improve.** conv1d_seq only pays off if a sequence model consumes it. The next
change adds that consumer - a gru between the conv_seq front and the dense head - which
is the conv_seq -> recurrent -> dense structure that won the recurrent-temporal
archetype. This is now the make-or-break move: one more sub-margin result ends the
lineage (strike 2/2).

**Decision.** revert - "revert: -0.0143 < margin (strike 1/2)". Next hypothesis:
conv1d_seq -> gru -> dense (add the recurrent stage; batch->64 for the recurrent stack).
