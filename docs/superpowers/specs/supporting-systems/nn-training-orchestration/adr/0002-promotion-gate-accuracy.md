# Promotion gate is holdout accuracy + loss, not P&L

A version (or trial) is promoted or reverted on **holdout accuracy and loss**, not on
backtested profit. Backtest P&L is the honest "better = makes more money" target, but it
requires model-combination and signal-identification work that does not exist yet, so it
is deliberately deferred to that later phase. Until then accuracy/loss is the interim
proxy that the whole improve-loop hill-climbs.

## Consequences

- **Known risk recorded:** raw accuracy on 3-class direction labels is gameable — a model
  that always predicts the dominant *neutral* class can score high and be promoted. A
  high-accuracy model is therefore NOT evidence of a profitable one.
- **Guard:** every version report records per-class accuracy + a confusion breakdown
  alongside the scalar, so the Tier-2 reasoning agent (and a human) can see a degenerate
  "always-neutral" winner even though the gate does not block it. `class_weight: balanced`
  already weights the training loss, but the *gate* metric is unchanged by that.
- When P&L is adopted later, prior cross-version comparisons become invalid (they were on
  a different objective) and lineages may need a re-baseline.
