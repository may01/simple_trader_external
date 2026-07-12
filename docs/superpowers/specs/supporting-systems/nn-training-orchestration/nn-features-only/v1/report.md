---
archetype: nn-features-only
decision: promote
holdout_acc: 0.707634
holdout_loss: null
hypothesis: "Archetype declaration: the 46 working nn_features (of 52; vol_regime\
  \ + align ladder are all-NaN in the prep path) across all 6 timeframe levels [1,5,15,60,240,1440]\
  \ as the SOLE input set \u2014 do engineered NN features alone carry directional\
  \ signal?"
next_hypothesis: 'swap recurrent kind gru -> lstm (conv1d_seq->lstm->dense) to test
  whether an LSTM cell models the multi-TF temporal structure better than GRU. RAM-neutral.
  Two earlier v2 attempts abandoned: history_points 4->16 OOM-kills the 15GB host
  (~14.7GB train tensor); conv1d_seq->gru->lstm is unbuildable (two stacked recurrents
  -> "too many indices for tensor of dimension 2").'
parent: null
per_class: {}
spec_hash: 52b4762cce6d8f4cc3f91df07b1bd1f3aecc66b85c2ad79a69f959cf73a20270
strike: 0
version: 1
---

## v1 — nn_features-only baseline (46 features x 6 levels)

**Hypothesis.** Archetype declaration: the 46 working nn_features (of 52; vol_regime + align ladder are all-NaN in the prep path) across all 6 timeframe levels [1,5,15,60,240,1440] as the SOLE input set — do engineered NN features alone carry directional signal?

**Result.**

| metric | value | vs incumbent |
|---|---|---|
| holdout accuracy (direction_binary argmax) | 0.7076 | first version |
| holdout loss | n/a (not recorded for direction_binary) | |
| trials completed | 5 (wall-clock cap 3600s hit before 8) | |
| trial spread | 0.6743 - 0.7155 | |

Per-class recall / confusion: NOT recorded by the pipeline for direction_binary
(metrics.per_target only stores aggregate holdout_score). Diagnose from the
aggregate + base rate instead.

**What went good.** Dataset builds cleanly on the 46-feature x 6-TF set (274 dense
cols, 70,170 usable holdout rows); search promoted a model; engineered nn_features
alone train to a stable ~0.71 across trials.

**What went bad.** 0.71 argmax-accuracy is BELOW the ~0.94 base rate (full-snapshot
v5 collapsed to always-negative at 0.9422 on the same target/holdout). Under the
broken direction_binary gate ([[project_nn_promotion_gate_broken]]) this reads as
'worse', but it means v1 actually predicts the minority long class rather than
collapsing — real predictions, penalised by argmax accuracy. decide: promote: first version.

**What to improve.** history_points=4 gives the conv1d_seq(kernel 3)+gru almost no
temporal context — too short to detect the directional momentum that separates
long from not-long. Widen the input window.

**Decision.** promote — promote: first version. Next hypothesis: swap recurrent kind gru -> lstm (conv1d_seq->lstm->dense) to test whether an LSTM cell models the multi-TF temporal structure better than GRU. RAM-neutral. Two earlier v2 attempts abandoned: history_points 4->16 OOM-kills the 15GB host (~14.7GB train tensor); conv1d_seq->gru->lstm is unbuildable (two stacked recurrents -> "too many indices for tensor of dimension 2"). (one structural change).
