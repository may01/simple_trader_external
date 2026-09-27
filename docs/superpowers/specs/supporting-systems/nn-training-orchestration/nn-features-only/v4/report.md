---
archetype: nn-features-only
decision: revert
holdout_acc: 0.737914
holdout_loss: null
hypothesis: "revert to v2 (conv1d_seq->lstm->dense) and add a dense HEAD layer (conv1d_seq->lstm->dense->dense)\
  \ \u2014 probe back-end head capacity, a different depth location than v3 front-end\
  \ conv depth."
next_hypothesis: null
parent: v2
per_class: {}
spec_hash: 5cc35dc3b1b35195eea925774869e5d1fc9457858e3c2068423fadc4a10668ed
strike: 2
version: 4
---

## v4 — add dense head (conv1d_seq -> lstm -> dense -> dense)

**Hypothesis.** revert to v2 (conv1d_seq->lstm->dense) and add a dense HEAD layer (conv1d_seq->lstm->dense->dense) — probe back-end head capacity, a different depth location than v3 front-end conv depth.

**Result.**

| metric | value | vs incumbent (v2) |
|---|---|---|
| holdout accuracy (direction_binary argmax) | 0.7379 | -0.0416 |
| holdout loss | n/a (not recorded) | |
| trials completed | 5 (wall-clock cap 3600s) | |
| trial spread | 0.6805 - 0.7379 | |

Per-class recall / confusion: not recorded by the pipeline for direction_binary.

**What went good.** Best trial 0.7379 recovered above v3 (0.7160) — head depth is less harmful
than front-end conv depth. Builds/trains fine.

**What went bad.** Still regressed vs v2 (-0.0416); extra head capacity did not add
generalisable signal. Second consecutive sub-margin version. decide: stop: 2/2 strikes.

**What to improve.** Neither front-end (v3) nor back-end (v4) depth beats the plain
conv1d_seq->lstm->dense. Two strikes -> lineage stops. Beyond this archetype the productive
levers are OUTSIDE the RAM-neutral depth menu: widen history_points (needs >15GB RAM or fewer
features), fix the direction_binary promotion gate ([[project_nn_promotion_gate_broken]]) so
scores are trustworthy, or change the target head.

**Decision.** revert — stop: 2/2 strikes. Lineage stops: stop: 2/2 strikes; winner = v2 (holdout 0.7795,
conv1d_seq -> lstm -> dense).
