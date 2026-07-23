# Beyond Direction Prediction — Design

**Date:** 2026-07-21
**Status:** proposal. Four independent tracks; each needs its own plan before implementation.
**Origin:** the candle-bounds experiments (`experiment/candle_bounds_estimation_results.md`,
`experiment/candle_bounds_algorithm.md`) established that range is predictable and direction
is not. This document proposes what to do about that.

---

## 1. Evidence base

Everything below is measured on LINK/USDT, train `2y_az` (2023-01→2025-01), OOS `oos2m`
(2025-01→2025-03), unless noted.

| finding | measurement |
|---|---|
| Candle **range** is predictable | r² 0.30–0.41 OOS on `high`/`low` extremes |
| Candle **close** is not | r² −0.001 / −0.001 / +0.016 at tf 15/60/240 |
| Candle **direction** is not | AUC 0.48–0.54; null-control AUC 0.47–0.51 — real results sit inside the null's spread |
| Adding 32 trained NN heads | changed nothing (AUC 0.458–0.538) |
| Accuracy vs majority-class | **negative in 13 of 24 cells** |
| Level placement cannot create edge | gross R +0.007 mean over 146 configurations, win rate 0.498 |
| Fees dominate | net R median −1.29R; `fee_R = 2·fee·entry/risk_dist` |
| `diff_prc_rm(6)` as a centre | r² −0.155 to −0.245 — worse than a constant |
| Volatility ≫ indicators | `only_V` r² 0.26–0.38 vs `only_R` 0.08–0.11 |

**The structural conclusion:** volatility clusters, so range forecasts work. Direction at the
candle level is close to a martingale. Predicting range gives *sizing accuracy*; it does not
give *return*. Return requires either a directional edge (absent here) or a favourable
asymmetry in the return distribution (untested — Proposal 1).

## 2. Shared validation protocol

Every track below MUST satisfy this. Each rule exists because violating it produced a false
positive during the candle-bounds work.

1. **Null control.** Fit on a shuffled target; report its score alongside. A result inside
   the null's spread is not a result. *(Caught: nothing — but it is what let us trust the
   r²≈0.35 range result.)*
2. **Honest baseline.** State what the model is beating. `diff_prc_rm(6)` scores −0.16 to
   −0.24, so beating it proves nothing. Use the train mean, floor 0. *(Caught: an apparent
   r² 0.42 that was 0.167 of free variance from the target's own construction.)*
3. **Target-construction audit.** If the target contains any quantity known at prediction
   time, that share of r² is free. Decompose before believing a number. *(Caught: `rm[k]`
   contains `d[k−1..k−5]`.)*
4. **Look-ahead mutation test.** Perturb candle k's own data; assert k's prediction is
   bit-identical, AND that k+1's changes. Without the second half the test passes vacuously.
   *(Caught: two false alarms in the test itself — feature-window overlap, and float residue
   from pandas' online `rolling()`.)*
5. **Alignment test.** Compare the broadcast value against `ext[j−1]`, `ext[j]`, `ext[j+1]`;
   the lowest MAE identifies which candle it actually forecasts. *(Caught: a real off-by-one
   that made the chart display a one-candle-stale forecast.)*
6. **Fee-aware realized R, not r².** Final acceptance is always net R after
   `2·fee·entry/risk_dist`, never a correlation or an r². *(Caught: a model with −27% MAE
   that produced zero realized edge.)*
7. **Sample-size honesty.** Report n alongside every rate. Lifts resting on <50 positive
   cases are noise. *(Caught: a 0.43x→1.06x "improvement" on 6 label hits.)*

## 3. Proposal 1 — Predict asymmetry, not direction

**Recommended first. Highest expected value, lowest new-dependency cost.**

### Problem

We have been asking "will price go up?" — measured at AUC 0.50. The tradeable question is
"is expected return positive?", which does not require P(up) > 0.5. A 40% win rate is
profitable at 2:1 reward:risk. The existing `profit_strict` labels already encode this, which
is why the NN heads target labels rather than sign.

### Design

- **Target:** per candle, the realized first-touch R of a trade opened at that candle's
  close with target/stop taken from the validated bounds model — reusing
  `_realized_rr_for_marking`'s walk (`validate.py:741`), which already implements
  first-touch with a pessimistic same-minute tie rule.
- **Framing:** regression on E[R], plus a classifier on `R > threshold` where threshold is
  set so the trade clears fees. The classifier is the operative one; the regression is
  diagnostic.
- **Features:** the 15 established blocks (R/M/A/V/P), plus the bounds model's own predicted
  range and band width — the range forecast is our one validated signal and should be an
  input, not just an output.
- **Selectivity is the deliverable.** Round 3 proved unconditional entry has zero
  expectation. Success is a *small* subset of candles with positive net R, not broad
  coverage. Report the full coverage/net-R curve, not a single operating point.
- **Validation:** protocol §2, acceptance on net R after fees at a stated coverage.

### Success criteria

Net R > 0 after fees on OOS at ≥2% coverage, holding on ≥4 of 6 (tf, side) combos, with
≥100 resolved trades per combo.

### Risks

The honest prior is that this fails too — if direction is unpredictable, asymmetry may be as
well. The difference is that it has not been tested, and it is the framing the rest of the
pipeline already assumes. Cheap to falsify.

**Effort:** small. Reuses existing frame, features, walk, and split.

## 4. Proposal 2 — Event bars instead of time bars

### Problem

Time bars sample at a constant clock rate regardless of activity, which is the worst case for
signal-to-noise: quiet periods contribute mostly noise, active periods are under-sampled.
Every result in §1 was measured on time bars.

### Design

- **Bar types:** volume bars, dollar bars, and a CUSUM event filter on returns. Standard
  AFML constructions.
- **Calibration:** set the threshold so average bars/day matches the current tf, making the
  comparison like-for-like rather than confounded by sample count.
- **Scope:** re-run the *existing, validated* range model on the new bars. This is a
  sampling change, not a model change — the point is to isolate the effect of sampling.
- **Read-out:** if range r² and direction AUC both move materially, sampling was a real
  constraint. If only range improves, it confirms the range/direction split is structural
  rather than an artifact of time bars.

### Success criteria

Direction AUC > 0.55 out of sample with a passing null control, **or** a clear negative that
retires the idea. Both outcomes are worth the cost.

### Risks

Bar construction sits upstream of the whole wide-df pipeline — indicators, labels and the
viewer all assume a 1-minute index. This is the main integration cost and the reason it is
not first.

**Effort:** medium. New bar builder, and every downstream consumer must be re-pointed.

## 5. Proposal 3 — Order-flow / microstructure data

### Problem

Short-horizon directional predictability lives in order flow — book imbalance, trade signing,
queue dynamics. This project has OHLCV only. §1's AUC ≈ 0.50 is partly a statement about the
*input*, not the model: no amount of indicator engineering recovers information that was
never in the data.

### Design

- **Acquisition:** exchange L2 book snapshots and/or the aggTrades stream. Both need a
  collector running forward — historical L2 is generally not free, and this is the gating
  constraint.
- **Features:** book imbalance at N levels, trade-signed volume (tick rule or Lee-Ready),
  order-flow imbalance, realized spread, queue depletion rate.
- **Horizon:** seconds to minutes. Microstructure signal decays fast; testing it at 240m
  would be a category error.
- **Validation:** protocol §2, and fee sensitivity is decisive here — microstructure edges
  are small per trade and only survive at low cost. Model maker/taker fees explicitly.

### Success criteria

Direction AUC > 0.55 at a horizon where net-of-fee R is positive.

### Risks

**Highest cost, most uncertain payoff.** Requires new infrastructure, forward data collection
(months before a usable sample exists), and the edges are the ones most exposed to latency
and fees. Realistically only worth starting if Proposals 1 and 2 both fail and there is
appetite for a much larger commitment.

**Effort:** large. New collector, new storage, new pipeline.

## 6. Proposal 4 — Cross-sectional prediction

### Problem

"Does this asset go up" is near-martingale. "Which of N assets outperforms" is a relative
question — much of the common market factor cancels, and the residual ranking is more
tractable and far better documented.

### Design

- **Universe:** the pairs the project already ingests. Requires ≥10–20 for a meaningful
  cross-section; below that the ranking is noise.
- **Target:** rank of forward return across the universe at each timestamp, or the
  top-quantile-vs-bottom-quantile binary.
- **Features:** the existing per-asset blocks, cross-sectionally standardized at each
  timestamp (z-score across assets, not across time). This standardization *is* the method —
  it removes the common factor.
- **Validation:** protocol §2, plus a long-short portfolio backtest with fees, since the
  natural expression is a market-neutral spread rather than a single-asset entry.

### Success criteria

Positive net-of-fee spread return OOS for a top-vs-bottom-quantile portfolio, with a passing
null control.

### Risks

Needs multi-pair data at the same quality as the current single-pair wide df — check what
exists before committing. Also a genuinely different execution model (simultaneous multi-leg)
that the current simulation layer does not support.

**Effort:** medium-large. Data availability is the unknown to resolve first.

## 7. Sequencing

```
Proposal 1  ──▶ cheap, reuses everything, tests the reframe the pipeline already assumes
     │
     ├── if it works ──▶ productionize; revisit 2 for sampling gains
     │
     └── if it fails ──▶ Proposal 2 (is the constraint sampling?)
                              │
                              ├── works ──▶ rebuild on event bars
                              └── fails ──▶ the constraint is the DATA
                                                │
                                                ├── Proposal 4 if multi-pair data exists (cheaper)
                                                └── Proposal 3 only with appetite for a large build
```

**Recommendation: do Proposal 1 next, and nothing else until it resolves.** It is days of
work against tracks that are weeks to months, it reuses the entire validated stack, and its
result determines whether the others are worth starting. Proposals 3 and 4 should not begin
until 1 and 2 have both been answered.

## 8. Open questions

1. **Multi-pair data inventory** — how many pairs exist at wide-df quality? Gates Proposal 4
   entirely; cheap to answer and should be answered before any commitment.
2. **Fee model** — everything above is evaluated at a flat `EXCHANGE_FEE=0.001`. Real
   maker/taker split and slippage would change the acceptance threshold, and Proposal 3 is
   especially sensitive.
3. **OOS length** — the 2-month window is too short for per-combo tuning; the zone-selection
   work already traced most overfitting symptoms to it. Any track that survives its first
   test should be re-validated on 6–12 months before being trusted.
4. **Where the code lives** — `azlib` is scoped to the zone-selection experiment and is
   read-only over the existing pipeline. Proposal 1 fits inside it; Proposals 2–4 do not and
   need their own home. Decide before writing Proposal 2's plan.
