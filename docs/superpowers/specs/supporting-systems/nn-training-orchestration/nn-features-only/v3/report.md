---
archetype: nn-features-only
decision: revert
holdout_acc: 0.716015
holdout_loss: null
hypothesis: "add a second conv1d_seq feature-extraction stage before the lstm (conv1d_seq->conv1d_seq->lstm->dense)\
  \ \u2014 deeper local-pattern extraction over the 274-feature window."
next_hypothesis: 'revert to v2 (conv1d_seq->lstm->dense); front-end conv depth regressed
  -0.064, so test BACK-END head depth instead: add a dense layer after the lstm (conv1d_seq->lstm->dense->dense).
  RAM-neutral, buildable, isolates head-capacity from feature-extraction depth.'
parent: v2
per_class: {}
spec_hash: b2cfcb0cb1b54690d89fff656667ed23c4bb679ff9a39794f3e28981c8530b94
strike: 1
version: 3
---

## v3 — add 2nd conv1d_seq (conv1d_seq -> conv1d_seq -> lstm -> dense)

**Hypothesis.** add a second conv1d_seq feature-extraction stage before the lstm (conv1d_seq->conv1d_seq->lstm->dense) — deeper local-pattern extraction over the 274-feature window.

**Result.**

| metric | value | vs incumbent (v2) |
|---|---|---|
| holdout accuracy (direction_binary argmax) | 0.7160 | -0.0635 |
| holdout loss | n/a (not recorded) | |
| trials completed | 5 (wall-clock cap 3600s) | |
| trial spread | 0.6829 - 0.7160 | |

Per-class recall / confusion: not recorded by the pipeline for direction_binary.

**What went good.** Builds and trains fine (stacked conv1d_seq -> lstm is a valid contract);
5 trials within the cap.

**What went bad.** Regressed: best trial 0.7160 vs v2 0.7795 (-0.0635); the whole trial
spread (0.68-0.72) sits below v2 (0.70-0.78). Adding front-end conv depth added
parameters/receptive field without separable signal — likely mild overfit / diluted the
lstm input. decide: revert: -0.0635 < margin (strike 1/2).

**What to improve.** Front-end feature-extraction depth is NOT the lever (v3 < v2). Keep v2's
conv1d_seq->lstm->dense; probe head capacity (a dense layer after the lstm) as a distinct
depth location before spending the second strike.

**Decision.** revert — revert: -0.0635 < margin (strike 1/2). Incumbent stays v2 (0.7795), strike 1/2.
Next hypothesis: revert to v2 (conv1d_seq->lstm->dense); front-end conv depth regressed -0.064, so test BACK-END head depth instead: add a dense layer after the lstm (conv1d_seq->lstm->dense->dense). RAM-neutral, buildable, isolates head-capacity from feature-extraction depth. (one structural change).
