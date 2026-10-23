# Validity gates — how to run each one

Every gate below has been failed at least once in this project. The example is the real case.

## 1. Null floor

Compare the statistic against the value it takes on noise at the same sample size.

- Mutual information on `K` classes with `N` rows has floor `(K−1)/(2·N·ln2)`. At TF240
  with 354 OOS rows the raw MI sat *below* its own floor and was reported as signal until
  `mi_null_floor` was emitted per block.
- No closed form? Permute the label 200× and report the 95th percentile of the shuffled
  metric next to the real one. Anything not clearing it is noise.

Report as a column in the same table as the metric, never as prose.

## 2. Base rate / class balance

Always print `base_rate` and `n` beside every score.

- Rare-positive targets collapse to always-negative. An NN promotion gate scored argmax
  accuracy on a 6% positive class; the collapsed model scored 0.94 and won promotion.
- For rare positives use precision@k, lift, or realized R — not accuracy, not plain EV.
- Expected value over rare strict labels is negative in every cell → argmax picks the cell
  with the fewest points. Use winrate with a minimum-points floor (30 was the used value),
  and report the point count next to the winrate.

## 3. Degeneracy of the objective

Ask where the argmax lands *before* believing it.

- Zone selection: `select_y` maximized coverage with a Y-invariant reward → Y slammed to
  ±2 and the zone covered everything. Fix: objective = `n_zoned × mean_R`, so widening is
  self-limiting.
- Target selection by marginal reach → degenerate near-target/far-stop corner with
  negative realized R. Fix: first-touch realized R, plus a reward:risk floor.
- Rule: an objective with no counterweight always returns a boundary value. If the winner
  is at the edge of the grid, the objective is broken, not the market.

## 4. Truth-decomposition ladder

Vary only the label definition, keeping points, features, models and split fixed:

| rung | truth | what it removes |
|---|---|---|
| strict | `profit_strict` (clean-entry gate) | nothing |
| plain | race + pessimistic fill, no clean-entry gate | the gate's own fingerprint |
| fwd | pure realized forward return | all label mechanics |

Report `label_share = strict − plain`, `entry_fill_share = plain − fwd`,
`future_share = fwd − 0.5`. In trend detection the ladder read 0.94 → 0.56 → 0.51:
the entire headline was label mechanics. `future_share` is the only number that means
"prediction".

## 5. Feature ablation

Drop the feature family that could encode the label and rerun the same loop.

- Excluding candle-k's own geometry (logret, body ratio, wicks, range/ATR) separated
  "recovering the label" from "predicting the future". The plain-truth run kept 0.55–0.58
  with shape and collapsed to 0.51 without it — the transfer was entry-fill mechanics.
- Keep the ablated run as a first-class artifact, not a footnote.

## 6. Look-ahead audit

For each feature, state which rows it can see. Broadcast values from a higher timeframe
must be shifted so no same-row information leaks. Forming-candle work (running
cummax/cummin) must be stored one row later, matching the closed-broadcast convention.
Write the audit into the report; the user has asked "does this look into the future?" on
every experiment.

## 7. Provenance / crosscheck

Cuts, models and shifts fitted on 2y and applied to oos2m must be verifiably the same
objects.

- 2y frames often predate columns baked into oos2m. Recomputing the class from frozen cuts
  reproduced the stored class 99.2% — good enough only because it was measured.
- Emit a crosscheck fraction per TF in the OOS report. 1.0000 or explain.
- Never re-derive frozen cuts from a stats json that may be a stale smoke artifact
  (`rsi_classification.json` diff_std was stale by ~0.5 std).

## 8. Reproduction gates

When replacing or re-implementing a pipeline, prove equivalence numerically before
trusting new outputs. The next-candle-bounds round used three gates: refit vs stored meta
(≤3e-16), inference vs stored artifact (≤1.6e-15), and first-row equivalence between the
forming and closed models (≤1.6e-15). Any accepted difference gets named and justified.

## 9. Sample-size rule

Cells with n < 30 on OOS are reported as `nan`, never scored. Small-n winners are the
default failure mode of grid search.
