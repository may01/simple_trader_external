---
archetype: recurrent-temporal
version: 2
parent: v1
spec_hash: 4faeeeb4a0ef4a886d2def16b301f2193d948fc435c83c9497096f3082902479
hypothesis: Rule out undertraining — same LSTM(64)->dense(32), epochs 50 / patience 8 /
  batch 256 (4x fewer steps so it finishes in v1 wall-time). Does proper training lift
  up/down precision above the base rate?
holdout_acc: 0.3857
holdout_loss: null
per_class:
  up: {precision: 0.060, recall: 0.322}
  neutral: {precision: 0.892, recall: 0.394}
  down: {precision: 0.062, recall: 0.327}
decision: revert
strike: 1
next_hypothesis: Undertraining is RULED OUT. The limitation is structural/representational.
  v3 — change the target framing to a single binary long-only strict label (predict
  "good long entry: yes/no"); if up-precision still equals the base rate, the strict
  entries are not predictable from this TA feature set and the investigation should
  pivot features/target rather than architecture.
---

# recurrent-temporal v2 — report

## Change from v1
Only training depth: epochs 12→50, patience 4→8, batch_size 64→256 (kept the
architecture, features, target, history identical). Sole purpose: settle whether v1's
"no signal" was undertraining.

## Result (holdout = 201,581 rows)
| class | true % | pred % | precision | recall | base rate |
|---|---|---|---|---|---|
| up | 5.8% | 31.0% | 0.060 | 0.322 | 0.058 |
| neutral | 88.5% | 39.1% | 0.892 | 0.394 | — |
| down | 5.7% | 29.9% | 0.062 | 0.327 | 0.057 |
Best trial: lr 0.00075, units 59, dropout 0.289, epochs 50. Holdout accuracy 0.3857.

## Verdict — undertraining ruled out
Full 50-epoch training moved up-precision 0.058→0.060 and down 0.059→0.062 — a hair,
within noise of the base rates (0.058 / 0.057). **Proper training does not produce a
predictive signal.** v1's null result was NOT an artefact of the 12-epoch cut.

## What this means
The recurrent-temporal LSTM over these 14 stationary/trend TA features **cannot
discriminate strict 15m best-entry points** above chance. The bottleneck is
representational, not optimisation. Two live hypotheses remain:
1. **Target framing too hard** — the 3-class up/neutral/down dilutes a weak directional
   signal; a single binary long-only strict label may be more learnable. → v3.
2. **Features carry no signal for this target** — best-entry timing may not be
   recoverable from these indicators at all. If v3 (binary) also sits at base rate, this
   is the conclusion, and the investigation should pivot the feature set or the target,
   not the architecture.

## Decision
`decide`: revert (−0.0642 < margin 0.01), strike 1/2, lineage continues. Best remains v1
(by the accuracy gate) — though neither version has real signal, so "best" here is
nominal.
