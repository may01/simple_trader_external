---
archetype: nn-features-only
decision: promote
holdout_acc: 0.779465
holdout_loss: null
hypothesis: 'swap recurrent kind gru -> lstm (conv1d_seq->lstm->dense) to test whether
  an LSTM cell models the multi-TF temporal structure better than GRU. (history_points
  4->16 was abandoned: OOM on 15GB host; conv1d_seq->gru->lstm abandoned: two stacked
  recurrents unbuildable.)'
next_hypothesis: "add a second conv1d_seq feature-extraction stage before the lstm\
  \ (conv1d_seq->conv1d_seq->lstm->dense) \u2014 the lstm swap lifted holdout +0.072,\
  \ so temporal/local-pattern capacity is the productive, RAM-neutral lever; deeper\
  \ conv extraction over the 274-feature window is the next single edit."
parent: v1
per_class: {}
spec_hash: 621b031d74a0f0cb899d5e9cb753a353721a16d244dce84eefb1be666ff8d160
strike: 0
version: 2
---

## v2 — swap gru -> lstm (conv1d_seq -> lstm -> dense)

**Hypothesis.** swap recurrent kind gru -> lstm (conv1d_seq->lstm->dense) to test whether an LSTM cell models the multi-TF temporal structure better than GRU. (history_points 4->16 was abandoned: OOM on 15GB host; conv1d_seq->gru->lstm abandoned: two stacked recurrents unbuildable.)

**Result.**

| metric | value | vs incumbent (v1) |
|---|---|---|
| holdout accuracy (direction_binary argmax) | 0.7795 | +0.0718 |
| holdout loss | n/a (not recorded) | |
| trials completed | 5 (wall-clock cap 3600s) | |
| trial spread | 0.7005 - 0.7795 | |

Per-class recall / confusion: not recorded by the pipeline for direction_binary.

**What went good.** LSTM cleanly beat GRU: +0.0719 holdout over v1, best trial 0.7795 and
the whole trial spread (0.70-0.78) shifted up vs v1 (0.67-0.72). Buildable, RAM-neutral,
trains within the cap (5 trials).

**What went bad.** Still on the broken direction_binary argmax gate — 0.7795 is below the
~0.94 always-negative base rate, so absolute number is not promotion-grade signal
([[project_nn_promotion_gate_broken]]); the +0.072 DELTA is the meaningful comparative
result, not the level. Per-class detail still unavailable to localise the failure.

**What to improve.** Temporal/feature-extraction capacity is the productive lever (lstm
helped). history_points widening is RAM-blocked on this 15GB host; next reach for deeper
conv feature extraction instead.

**Decision.** promote — promote: +0.0718 ≥ margin 0.0100. Next hypothesis: add a second conv1d_seq feature-extraction stage before the lstm (conv1d_seq->conv1d_seq->lstm->dense) — the lstm swap lifted holdout +0.072, so temporal/local-pattern capacity is the productive, RAM-neutral lever; deeper conv extraction over the 274-feature window is the next single edit. (one structural change).
