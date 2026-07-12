---
archetype: full-snapshot-dense
decision: revert
holdout_acc: 0.9422356841327005
holdout_loss: null
hypothesis: 'Add the recurrent consumer: conv1d_seq -> gru -> dense. A gru models
  the ordered 4-bar conv features (the conv_seq->recurrent shape that won recurrent-temporal);
  batch->64 for the recurrent stack.'
next_hypothesis: null
parent: v3
per_class: {}
spec_hash: a1175b4d0e89316680d88b2c3c6268f826e8dc31e8c0e3be488a4fe36f9e0486
strike: 1
version: 5
---

## v5 - add gru on the conv sequence (conv1d_seq -> gru -> dense) + BROKEN-GATE HALT

**Hypothesis.** Complete the conv_seq->recurrent structure: a gru consumes the per-bar
conv features that conv1d_seq preserves, modelling the ordered 4-bar window. This is
the shape that won the recurrent-temporal archetype. batch_size 128->64 (recurrent
convention). Same dataset (h=4) as v2-v4, so no rebuild.

**Result (as recorded, then adjudicated).**

| metric | value | note |
|---|---|---|
| holdout_score (recorded winner, trial u23) | 0.9422 | **DEGENERATE - rejected** |
| holdout negative ("other") base rate | 0.94224 | matches u23 to 6 dp |
| real non-degenerate best (trial u36) | 0.7694 | actually predicts longs |
| trials completed | 5 / 8 | max_wall_clock_s cap hit (gru trials slow) |

Trials: u51 0.7616 | u54 0.6980 | u59 0.7290 | u36 0.7694 | u23 **0.9422**.

**What went good.** In the NON-degenerate regime the recurrent stage is the strongest
lever seen: real trials reach 0.7694 (u36) vs the v3 incumbent 0.7267 (+0.043) - the
conv_seq->gru shape does extract more signal, consistent with recurrent-temporal. The
architecture direction is validated.

**What went bad (the decisive finding).** The recorded "winner" trial u23 scored 0.9422,
which is EXACTLY the holdout negative base rate (0.94224 over 209,646 rows). u23 is the
degenerate always-predict-"other" classifier: 94.2% accuracy, ZERO long recall, useless
as a trading filter. It gamed the promotion gate, which for `direction_binary` is plain
argmax accuracy (`training_loop._score_predictions`). On a ~5.8%-positive target that
metric monotonically rewards predicting FEWER longs, so the majority-class collapse wins
and `cli decide` mechanically returns "promote: +0.2155". The gain is a measurement
artifact, not a model improvement. This is the exact ADR-0002 gap the recurrent-temporal
SUMMARY flagged ("promotion gate too coarse ... amend to precision@k / lift before the
next archetype") - which was not done before this archetype.

**What to improve.** Fix the promotion gate BEFORE trusting any winner in this archetype:
replace the accuracy scorer with a precision@k / lift-based holdout score for
`direction_binary` (and update BOTH scorers per the two-scorer invariant). Until then no
version's holdout_score is interpretable as trading quality - including v1-v3's apparent
0.678->0.727 hill-climb, which partly rewards conservatism, not signal.

**Decision.** revert (reject the degenerate u23 - not a real gain; incumbent of record
stays v3 0.7267 but is itself on the suspect metric). Lineage STOPS here - not on strikes
(1/2), max_versions (5/6), or budget - but on a discovered measurement-validity failure:
the promotion gate is invalid for this target. Handing to the human gate with the
recommendation to implement the precision@k/lift scorer (engine TDD) and re-score/re-run.
