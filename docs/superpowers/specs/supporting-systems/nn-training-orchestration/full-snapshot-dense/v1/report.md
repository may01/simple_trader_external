---
archetype: full-snapshot-dense
decision: promote
holdout_acc: 0.6781184384293084
holdout_loss: null
hypothesis: 'Breadth beats curation: a wide 3-layer dense MLP over the full 102-feature
  x 6-timeframe snapshot (history_points=1, no temporal modelling) predicts the strict
  15m long entry as well as or better than a curated/temporal model.'
next_hypothesis: 'Widen history_points 1->8 (keep dense x3): the holdout score plateaus
  at 0.667-0.683 across every Optuna width/lr/dropout setting, so the snapshot SHAPE
  is saturated; a short lookback window tests whether a single instant is too myopic.'
parent: null
per_class: {}
spec_hash: cef7e1064ab585decc8ff6e3ce1db73249dbc58124501c2389404da59880782e
strike: 0
version: 1
---

## v1 - full multi-timeframe snapshot (kitchen-sink dense baseline)

**Hypothesis.** Breadth beats curation. Feed a wide dense MLP the entire usable
feature set (102 indicators x 6 timeframes = 474 input columns) at a single instant
(history_points=1, no temporal layer) and let it find the cross-feature /
cross-timeframe interactions, with no manual selection. Baselines the archetype: is
seeing everything competitive with the curated `recurrent-temporal` line?

**Result.**

| metric | value | vs incumbent |
|---|---|---|
| holdout_score | 0.6781 | baseline (first version) |
| holdout_loss | not recorded | - |
| per-class recall | not recorded (binary long-vs-other target) | - |

Target is `direction_binary` (side=long, strict 15m, m1/x0.3/l15/y0.2), so there is
no 3-class up/neutral/down confusion; the trainer recorded only the aggregate
`holdout_score` (0.6781 over 210,506 holdout rows) — `metrics.loss/accuracy` and
per-class were null in best.json, so no confusion table is available this version.

Optuna ran the locked 8-trial search (units/lr/dropout) over the fixed dense x3 /
h=1 shape. All 8 trials landed in a tight band:

| units (L1) | dropout/lr tuned | holdout_score | status |
|---|---|---|---|
| 51 | incumbent | 0.6781 | ok (promoted incumbent) |
| 38 | - | 0.6834 | ok (best raw, < margin over incumbent) |
| 36 | - | 0.6827 | ok |
| 16 | - | 0.6796 | ok |
| 54 | - | 0.6789 | ok |
| 31 | - | 0.6680 | ok |
| 59 | - | 0.6680 | ok |
| 23 | - | 0.6671 | ok |

**What went good.** The archetype is buildable and trains end-to-end on the full
474-column multi-timeframe snapshot; the whole 2y series (1,052,560 one-minute rows)
survives the NaN-drop after pruning the 6 dead features. A first, non-trivial signal
exists (0.6781) — the kitchen-sink snapshot is not noise.

**What went bad.** The score is flat (0.667-0.683, ~1.6% spread) across the entire
Optuna sweep of width, learning-rate, and dropout. Tuning the tunables barely moves
it, which says the bottleneck is the model SHAPE, not its numeric settings — the
pure single-instant snapshot has saturated. `decide(...)` reason: "promote: first
version".

**What to improve.** The saturated-shape plateau is the dominant failure mode. The
one structural dimension currently pinned at its floor is the input window
(history_points=1). Widen it so the dense stack can see recent trajectory; if the
score breaks the plateau, the snapshot was myopic, if not, the multi-timeframe
columns already carried the lookback.

**Decision.** promote - "promote: first version" (baseline incumbent). Next
hypothesis: widen history_points 1->8 (one structural change; layer kinds/count
unchanged, Optuna re-tunes units/lr/dropout).
