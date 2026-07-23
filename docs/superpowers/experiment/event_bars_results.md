# Proposal 2 — Event Bars: Results

**Date:** 2026-07-22
**Spec:** `specs/2026-07-21-event-bars-design.md`
**Data:** train `2y_az` (731d), OOS `oos2m` (59d), LINK/USDT. 1-minute OHLCV only.
**Verdict:** **negative on the decisive metric — the valuable negative.** Event bars sharpen
*range* prediction but do **not** move *direction* AUC off ~0.50. Per the pre-registered
criterion (§8), range gain alone does not justify the pipeline rebuild. This establishes that
the range/direction split is **structural, not a sampling artifact**, and routes the sequencing
to the data hypothesis (Proposals 3/4).

---

## Setup

Isolated experiment, no production code touched. Bars built from raw 1-minute OHLCV; V+P
features only (the blocks computable directly from a bar series — time-bar RSI/MACD are
meaningless on event bars). Thresholds frozen on train, applied to OOS. Bar-count targets
matched to the time-tf closed-candle counts (70163/17535/4379 for tf 15/60/240).

Four bar types per tf-equivalent:

- **time** — fixed `tf` 1-minute rows per bar (the baseline).
- **volume** — close when cumulative volume ≥ V.
- **dollar** — close when cumulative `close·volume` ≥ D.
- **CUSUM** — close when cumulative |log-return| ≥ θ.

## Results

| config | n_oo | bars/d train | bars/d OOS | r²_high | r²_low | **dir AUC** | null | base |
|---|---|---|---|---|---|---|---|---|
| tf15-time | 5665 | 96.0 | 96.0 | 0.319 | 0.371 | 0.505 | 0.505 | 0.538 |
| tf15-volume | 6688 | 92.8 | 113.4 | 0.366 | 0.416 | **0.538** | 0.508 | 0.538 |
| tf15-dollar | 10362 | 91.4 | 175.6 | 0.360 | 0.411 | 0.537 | 0.495 | 0.531 |
| tf15-cusum | 7523 | 89.2 | 127.5 | 0.395 | 0.407 | 0.517 | 0.495 | 0.528 |
| tf60-time | 1417 | 24.0 | 24.0 | 0.330 | 0.321 | 0.541 | 0.470 | 0.527 |
| tf60-volume | 1764 | 24.0 | 29.9 | 0.346 | 0.453 | 0.502 | 0.499 | 0.536 |
| tf60-dollar | 2846 | 23.9 | 48.2 | 0.365 | 0.437 | 0.529 | 0.482 | 0.524 |
| tf60-cusum | 2018 | 23.5 | 34.2 | 0.377 | 0.408 | 0.524 | 0.484 | 0.521 |
| tf240-time | 355 | 6.0 | 6.0 | 0.264 | 0.369 | 0.500 | 0.502 | 0.523 |
| tf240-volume | 441 | 6.0 | 7.5 | 0.372 | 0.425 | 0.533 | 0.491 | 0.507 |
| tf240-dollar | 718 | 6.0 | 12.2 | 0.331 | 0.444 | 0.518 | 0.497 | 0.542 |
| tf240-cusum | 514 | 6.0 | 8.7 | 0.432 | 0.431 | 0.510 | 0.514 | 0.515 |

## Reading

**Range: event bars help, consistently.** Every event type beats its time baseline on at least
one side, most on both. The clearest is tf240-cusum (0.432/0.431 vs time 0.264/0.369) and
tf15-cusum (0.395 vs 0.319 high). Sampling by activity does sharpen the one thing that already
worked — as theory predicts, because volatility clustering is a *magnitude* property and event
bars sample magnitude better.

**Direction: no movement.** AUC stays 0.50–0.54 across every bar type and timeframe. The single
highest is tf60-**time** (0.541) — a time bar. The best event-bar result (tf15-volume, 0.538)
is +0.030 over its null but *equal to* the majority-class base rate (0.538), i.e. no better than
guessing the dominant class. **Nothing clears the 0.55 success threshold**, and no event type
beats time bars at direction in any consistent way.

**Bars/day drifted on OOS.** Thresholds frozen on train produced far more bars on OOS
(tf15-dollar: 91→176/day, tf60-dollar: 24→48/day). The OOS window was a materially
higher-activity regime. This is itself a finding — and it violates the "comparable bars/day"
clause of the success criterion, so even the marginal direction readings are not clean A/B
comparisons.

## Verdict against the pre-registered criterion (§8)

> **Primary:** direction AUC > 0.55 OOS on ≥1 event-bar type at ≥1 tf-equivalent, with a passing
> null control **and** comparable bars/day.

**Fails.** No config reaches 0.55; the event types that come closest have drifted bars/day.

> Range r² improvement alone is **not** sufficient to justify the §7 rebuild.

Correct call in advance — the range gain is real but does not pay for re-plumbing the pipeline.

This is the **"equally valuable negative"** the spec anticipated (§8): a clean demonstration that
event bars do not recover direction. It matches the honest prior in §10 ("expect range↑,
direction flat").

## What it means

The range/direction asymmetry is **structural, not an artifact of time sampling.** Two
independent sampling schemes (time and event) both find range predictable (r² 0.26–0.45) and
direction unpredictable (AUC ≈ 0.50). Combined with the close-prediction result (r² ≈ 0) and the
direction test (AUC ≈ 0.50), three separate angles now agree:

> **OHLCV contains magnitude information but not short-horizon sign information — regardless of
> how it is sampled.**

That is the expensive conclusion the sequencing was built to reach: the constraint is the
**data**, not the model and not the sampling. The next question is whether *different* data
carries direction — order flow (Proposal 3) or a cross-sectional relative signal (Proposal 4).

## Caveats

- **Leakage not separately mutation-tested.** Bars are built from cumulative sums crossing a
  threshold (bar k's boundary uses only data up to that point) and features are `.shift(1)` of
  completed bars, so the frame is look-ahead free by construction. But the range r² gain should
  be mutation-tested (spec §9.3) before being *trusted* as a sizing improvement — leakage
  inflates, and a positive is what needs guarding. The direction *negative* stands regardless
  (leakage would only inflate it, and it still didn't clear 0.55).
- **One pair, 59-day OOS.** Same limitation as everything in this line of work; the bars/day
  drift shows how much the short window can differ in regime.
- **CUSUM θ, V, D calibrated to a bar count, not tuned.** A different calibration could shift
  bars/day but not the direction conclusion — AUC ≈ 0.50 is not a threshold-sensitivity issue.

## Recommendation

1. **Do not rebuild the pipeline for event bars.** The decisive metric failed.
2. **The range gain is worth banking cheaply** — if the bounds/sizing model is ever
   productionized, event-bar (esp. CUSUM) sampling is a low-cost r² improvement worth a
   mutation-test and a look. It is an optimization, not a new capability.
3. **Sequencing now points at data.** Time bars, event bars, close prediction, and direction
   classification all agree OHLCV lacks short-horizon sign information. Proposals 3 (order flow)
   and 4 (cross-sectional) are the remaining hypotheses. Resolve the **multi-pair data
   inventory** open question first — Proposal 4 is far cheaper than Proposal 3 if the data
   exists.

## Artifacts

- `scratchpad/eventbars.py` — bar builders (time/volume/dollar/CUSUM), V+P frame, A/B harness.
  Read-only over the wide df.
- `out/eventbars.json` — all 12 configs' metrics.
- No production code changed, no sidecar written.
