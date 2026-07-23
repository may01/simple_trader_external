# Proposal 1 — Asymmetry Model: Results

**Date:** 2026-07-22
**Spec:** `specs/2026-07-21-asymmetry-model-design.md`
**Data:** train `2y_az` (2023-01→2025-01), OOS `oos2m` (2025-01→2025-03), LINK/USDT.
**Verdict:** **partial signal, does not pass.** Asymmetry is more predictable than direction
(classifier AUC 0.57–0.75 vs null 0.50–0.56), but it does not convert into robust net-positive
R on this OOS under a fixed, non-tuned config with adequate sample sizes. Retire as a
standalone edge; the signal is real enough to revisit on a longer OOS.

---

## Headline

Three things, in order of confidence:

1. **There is asymmetry signal.** The `R > fee_R` classifier beats its shuffled-target null on
   every good config — AUC up to 0.68 (entry-at-close) and 0.75 (wide-stop). Direction never
   cleared 0.54. Predicting *whether a bet is favourable* is genuinely easier than predicting
   *which way price goes*.
2. **It does not clear fees at face value.** Fee drag is `2·fee·entry/risk_dist`. With
   entry-at-close and predicted-bound stops, the stop is ~0.3 % away at tf15, so fees eat
   **~0.67R per trade**. Net-R of every variant at the natural stop distance is negative.
3. **Making it positive requires exactly the profile that already overfit.** Widening the stop
   to cut fee drag flips many configs net-positive — but produces high-win-rate (88–95 %),
   small-reward, far-stop trades: the near-target/far-stop degeneracy the zone-selection work
   (`zone_selection_2y_results.md`) already identified and **reverted** for overfitting a
   2-month OOS. And the positive combos rest on <100 trades at coarse tf.

## The three trade variants tested

| variant | entry | target / stop | result |
|---|---|---|---|
| **A: entry-at-close, natural stop** | close[k−1] | pred high / pred low (rr≈1) | AUC 0.57–0.68 > null; **net-R negative** (fee drag) |
| **B: zone-limit entry** | zone (10 % from SL) | pred opposite / pred bound (rr≈9) | win rate 3–6 %; **net-R −1.3 to −3.2**; AUC ≈ null |
| **C: entry-at-close, widened stop** | close[k−1] | pred bound / pred bound − W·band | 30/54 (W,n) configs top-5 % net > 0, but far-stop profile |

Variant B fails because a 9:1 target is rarely reached within one candle while the tight stop
triggers constantly — the horizon is too short for the favourable rr to pay. Variant A has the
cleanest signal but rr≈1 collapses asymmetry back toward direction, and fees finish it.
Variant C is where positive numbers appear, and where the overfitting caveat bites.

## Step-by-step (the spec's build order)

1. **Target generation.** Realized first-touch R per candle, entry at close[k−1], levels from
   the frozen bounds model, walk over candle k's own tf minutes. Resolved fraction 73–82 %.
2. **Baseline (unconditional).** Net-R of trading every resolved candle: **−0.07 to −0.68**,
   negative everywhere. Confirms Round 3 — nothing leaked, and unconditional entry loses to
   fees. ✓
3. **E[R] regression.** r² small and positive on the good combos, near-zero on tf15. Diagnostic
   only.
4. **Classifier `R > fee_R`.** AUC 0.57–0.68 (variant A), 0.55–0.75 (variant C) vs null
   0.50–0.56. **The one clear positive: asymmetry ranks better than chance.**
5. **Coverage/net-R curve + stop-width/horizon sweep.** Variant A curves negative (fee drag).
   Variant C: 30 of 54 (tf, dir, W, n) configs have top-5 % net-R > 0 — all at W∈{2,3}
   (wide stops).

## The honest success-criterion test

The criterion (net-R > 0 at 5 % coverage, ≥4 of 6 combos, ≥100 resolved trades each) applied to
a **single fixed global (W, n)** — no per-combo tuning, because per-combo tuning is the exact
overfitting the parent docs warn against:

| config | combos passing |
|---|---|
| W=2, n=1 | **0 / 6** |
| W=3, n=1 | **1 / 6** |
| W=2, n=2 | **0 / 6** |

Every coarse-tf combo (60/240) shows *positive* top-5 % net-R but on **8–35 trades** —
underpowered, flagged not counted. Every fine-tf combo (15) with ≥100 trades sits at or below
zero. The apparent 30/54 win rate from the sweep dissolves once you (a) fix one config instead
of picking the best per combo, and (b) enforce the ≥100-trade floor.

**No configuration passes.**

## Why this is the expected outcome, not a bug

The spec (§10) called this: *"It may simply fail. If E[R] is as unpredictable as direction, the
curve is flat-zero."* It is not flat-zero — there is measurable ranking signal — but it is not
tradeable under honest constraints. Two forces cap it:

- **Fees scale inversely with stop distance.** Any edge from a tight, informative stop is eaten
  by `2·fee/risk`. Loosening the stop to escape fees reintroduces the far-stop profile whose
  rare large losses a 2-month OOS cannot sample reliably.
- **rr≈1 is direction in disguise.** The only entry that keeps rr≈1 (entry-at-close, full
  bounds) reduces "is this bet favourable" back to "does price go up," which we measured dead.

## What survives

- **The classifier's AUC edge is real and reproducible** — asymmetry > direction. That is worth
  keeping as a finding even though it did not clear fees.
- **The bounds model as a sizing tool** is unaffected and still validated (r² ≈ 0.35, band
  25–28 % tighter than the old action space).

## Recommendation

Per the parent doc's sequencing:

1. **Do not productionize.** No fixed config clears the criterion.
2. **Re-test on a 6–12 month OOS before any further work.** Every positive signal here is either
   underpowered (coarse tf) or the fragile far-stop profile. The parent docs trace most
   overfitting symptoms to the 2-month window; this result is consistent with that and cannot be
   trusted until the window is longer. This is the single highest-value next step and it is cheap
   (more data, same code).
3. **Then route to Proposal 2 (event bars).** The fee-drag ceiling is partly a sampling artifact
   — time bars force a fixed horizon, and the stop-distance/fee tradeoff is horizon-dependent.
   Event bars change the horizon structure and are the natural next question if the longer-OOS
   re-test still fails.

## Artifacts

- `scratchpad/asym.py` (variant A), `asym2.py` (B, zone entry), `asym3.py` (C, stop-width sweep +
  criterion test). Read-only over the wide df; nothing written to the repo.
- `out/asym.json`, `out/asym_zone.json`, `out/asym3.json` — per-combo metrics.
- No production code changed. No sidecar written (this was a validation experiment, not a
  deliverable).
