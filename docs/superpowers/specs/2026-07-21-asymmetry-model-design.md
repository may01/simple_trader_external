# Proposal 1 — Predict Asymmetry, Not Direction (Detailed Design)

**Date:** 2026-07-21
**Status:** detailed proposal. Expands §3 of `2026-07-21-direction-alternatives-design.md`.
Needs its own implementation plan before code.
**Parent evidence:** `experiment/candle_bounds_estimation_results.md` (range predictable,
direction not), Round 3 (level placement ≠ edge), the label-overlap runs (best entry filter
so far ≈ 1.2× base at ~2% base rate).

---

## 1. The core idea, precisely

Direction is a bet on the **sign** of the next move: P(up) measured at AUC ≈ 0.50 — unbeatable
here. Asymmetry is a bet on the **shape** of the return distribution: is expected return
positive once you fix a target and a stop?

These are different questions. P(up) can be exactly 0.50 while E[R] is strongly positive or
negative, because E[R] depends on *how far* price travels each way, not just *which way*:

```
E[R] = P(target first) · (reward/risk)  −  P(stop first) · 1  −  fees
```

A 40 % win rate at 3:1 reward:risk gives E[R] = 0.40·3 − 0.60·1 = +0.60R before fees. The
edge lives in the ratio, not the hit rate. This is the quantity a trade actually pays out,
and it is what the existing `profit_strict` labels already approximate — which is why the NN
heads target labels, not sign. We are making that target explicit and continuous.

**We are NOT predicting where price goes. We are predicting whether a specific bet is
favourable.** That reframing is the entire proposal.

## 2. What already exists (reuse map)

Nothing here is built from scratch. The candle-bounds experiment produced every piece:

| need | exists as | file |
|---|---|---|
| closed-candle feature frame | `frame()` (R/M/A/V/P blocks, k−1 aligned) | scratchpad `gen_candle_bounds.py` |
| target/stop **prices** per candle | validated bounds model | `candle_bounds_algorithm.md` |
| realized first-touch R walk | `_realized_rr_for_marking` | `validate.py:741` |
| binary profit label (comparison) | `profit_long/short`, `profit_strict_*` | `indicators/labels.py` |
| frozen train→OOS split, leakage tests | protocol §2 of parent doc | — |
| NN head readings | `nn_res_*` (oos2m only) | `df_with_nn.pkl` |

The new work is a target definition, a model, and a thresholding rule. The data pipeline,
the walk, and the validation harness are done.

## 3. Target definition — the one design decision that matters

For every closed candle *k*, define a trade opened at that candle's close, with:

- **target** = the bounds model's predicted extreme on the profit side
  (`cb_high` for long, `cb_low` for short),
- **stop** = the bounds model's predicted extreme on the loss side
  (`cb_low` for long, `cb_high` for short).

Then walk forward `n·tf` minutes (`_realized_rr_for_marking`, first-touch, pessimistic
same-minute tie → stop wins) and record the **realized R multiple**:

```
R = +reward_dist / risk_dist   if target touched first
    −1.0                        if stop touched first
    (excluded)                  if neither within the window, or risk_dist ≤ 0
```

`reward_dist = |target − entry|`, `risk_dist = |entry − stop|`.

**Two model heads, from the same R:**

- **Regression head** — predict E[R] directly. Diagnostic: tells you the shape of the edge
  across the feature space.
- **Classification head** — predict `R > R_min`, where `R_min` is set so a won trade clears
  fees: `R_min = fee_R = 2·fee·entry / risk_dist`. This is the **operative** head — its
  positive class is "a trade worth taking."

Why both: the classifier is what you act on, but a regression on E[R] is far more informative
for debugging *why* a region is favourable, and its residual structure tells you whether the
edge is real or a few outliers.

**Critical:** target/stop distances come from the bounds model, which is look-ahead free
(features at k−1). The forward walk uses candle k's future 1-minute bars — that is the label,
never a feature. This is the exact structure `_realized_rr_for_marking` already enforces.

## 4. Feature vector

The 15 validated blocks, plus the bounds model's own outputs:

| block | features | status |
|---|---|---|
| R | RSI position/slope/distance | established |
| M | MACD position/slope/distance | established, > RSI for range |
| A | MA position/slope | weak but cheap |
| V | std12, absmean12, range, body | **dominant** for range |
| P | prev residual ×2, rm | modest |
| **B (new)** | predicted range width, predicted band std, reward/risk ratio of the proposed trade | our one validated signal, fed as input |

Block B is the novel part: the range forecast (r² ≈ 0.35) is the only thing we can predict
well, so it should be an *input* to the asymmetry model, not just the source of the levels.
A candle whose predicted range is wide relative to its band uncertainty is a different bet
from one whose range is narrow — and only the asymmetry model can say whether that difference
is tradeable.

NN heads (`nn_res_*`) are an **optional** block, testable only on the oos2m-internal split
(they don't exist on 2y_az). Kept separate so their contribution is measured, not assumed —
the direction test already showed they add nothing to *direction*; whether they add to
*asymmetry* is an open question worth one clean measurement.

## 5. Model

- **Regression:** Ridge, then GBR as a nonlinearity check. The range work showed GBR helps
  only where data is plentiful (tf15) and *hurts* at tf240 (4,379 candles). Expect the same;
  linear is the default at 60/240.
- **Classification:** LogisticRegression, then GBM check, same reasoning.
- **Standardization frozen on train**, applied to OOS — the established pattern.
- **Per (tf, side)** — six independent models, as everywhere else in this experiment.

No deep model. The bottleneck established repeatedly is features and sample size, not model
capacity.

## 6. The deliverable is a curve, not a number

Round 3 proved unconditional entry has zero expectation. So the output is **not** "trade every
candle" — it is a **coverage / net-R curve**:

- Sort candles by predicted E[R] (or classifier score) descending.
- For each coverage level (top 1 %, 2 %, 5 %, …), compute realized net-R after fees on OOS.
- The tradeable region, if any, is where net-R > 0 at coverage high enough to matter.

A model that is right about the *ranking* is useful even at AUC 0.55, because you only trade
the top slice. This is the whole point of the asymmetry framing: you do not need to be right
often, you need the trades you take to pay.

Report the full curve for all six combos. A single operating point hides whether the edge is a
real gradient or one lucky bucket.

## 7. Validation — inherits parent §2, with two additions

All seven rules from `2026-07-21-direction-alternatives-design.md` §2 apply. Two are
sharpened here:

1. **Fees are in the target, not just the report.** `R_min = fee_R` means the classifier's
   own labels already price fees. A "positive" prediction that ignored fees would be a
   different, useless model. Verify `R_min` varies per row with `risk_dist` — a fixed
   threshold reintroduces the tight-stop trap (a stop 0.1 % away needs a huge R just to clear
   costs).
2. **Sample-size floor on the operating point.** The top-2 % slice of oos2m is ~28 candles at
   tf240. Any positive-net-R claim needs ≥100 resolved trades in the reported bucket, or it is
   flagged as underpowered and only reported on the pooled/finer timeframes.

## 8. Success criteria

**Primary:** net R > 0 after fees on OOS, at ≥2 % coverage, holding on ≥4 of 6 (tf, side)
combos, each with ≥100 resolved trades.

**Secondary (diagnostic, not acceptance):** classifier OOS AUC > 0.55 with a passing null
control; E[R] regression r² > 0 vs the train-mean baseline.

**Honest failure:** if the coverage/net-R curve is ≤ 0 everywhere across all six combos, the
asymmetry framing is retired and the sequencing routes to Proposal 2 (is the constraint
sampling?). This is a real possible outcome — see §10.

## 9. Concrete build order

Each step is independently checkable; do not proceed on a failed step.

1. **Target generation.** For each (tf, side), build the realized-R series over 2y_az and
   oos2m using the frozen bounds model + `_realized_rr_for_marking`. Sanity: distribution of
   R, fraction resolved, fraction of −1.0 (all-stops) — the short/240 −1.00R pathology from
   the zone work must not silently recur.
2. **Baseline.** Net-R of trading *every* resolved candle (the Round-3 null). Must be ≤ 0;
   if it is > 0 something leaked.
3. **Regression head.** Fit E[R], report r² vs train mean + null control. Expect small.
4. **Classification head.** Fit `R > fee_R`, report AUC + null. This is the operative model.
5. **Coverage/net-R curve.** The deliverable of §6, all six combos, with n per bucket.
6. **NN-head ablation.** Repeat 4–5 with block B+NN on the oos2m-internal split; measure
   whether NN heads add anything to *asymmetry* specifically.
7. **Decision.** Against §8. Promote, iterate, or retire and route onward.

## 10. Risks and honest priors

- **It may simply fail.** If E[R] is as unpredictable as direction, the curve is flat-zero
  and this dies at step 5. The prior is genuinely uncertain — asymmetry is untested, unlike
  direction which we measured dead. Its virtue is cheapness, not likelihood.
- **The bounds model defines the trade, so its errors flow through.** If predicted levels are
  systematically wrong on one side (the class-adjust experiment showed how easily one side
  skews), the realized R inherits that skew. Mitigate by using the *raw* bounds (now the
  chart default) and checking the resolved-R distribution per side at step 1.
- **Fees may eat everything.** The −1.29R median net from Round 3 is the warning. If the only
  positive-E[R] candles have stops so tight that `fee_R` swamps the reward, there is no
  tradeable slice. The per-row `R_min` makes this visible rather than hidden.
- **Overfitting a 2-month OOS.** The zone work traced most overfitting to this window. A
  survivor at step 7 is a *candidate*, not a result, until re-run on 6–12 months.

## 11. Why this is first

- Reuses the entire validated stack — days, not weeks.
- Tests the reframe the pipeline already assumes (`profit_strict` = asymmetry, not direction).
- Its outcome decides whether Proposals 2–4 are worth starting.
- Cheap to falsify: a flat coverage curve is an unambiguous, fast "no."
