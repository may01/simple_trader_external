# Proposal 2 — Event Bars Instead of Time Bars (Detailed Design)

**Date:** 2026-07-21
**Status:** detailed proposal. Expands §4 of `2026-07-21-direction-alternatives-design.md`.
Runs only if Proposal 1 fails. Needs its own implementation plan before code.
**Parent evidence:** every result in the candle-bounds work was measured on **time bars**
(direction AUC ≈ 0.50, range r² ≈ 0.35). This proposal asks whether the sampling itself is
the constraint.

---

## 1. The core idea, precisely

A **time bar** closes on a fixed clock: every 15, 60, 240 minutes regardless of what the
market is doing. This is the worst case for signal-to-noise:

- **Quiet periods** are over-sampled — many near-identical bars carrying almost no
  information, which the model must still fit.
- **Active periods** are under-sampled — a violent 3-minute move is one row, its internal
  structure collapsed.

Information does not arrive on a clock; it arrives with **activity**. An **event bar** closes
when a chosen activity measure crosses a threshold, so each bar carries roughly equal
information regardless of wall-clock duration. The claim under test: sampling by activity
recovers signal that time sampling smears out.

**This is a sampling change, not a model change.** The entire point is to hold the model
fixed and vary only how bars are formed, so any movement in the metrics is attributable to
sampling alone.

## 2. Current bar model (what we are replacing)

From `data.py:_build_wide_df` — the production wide df is built by:

- Base = a **1-minute DatetimeIndex**.
- For each `tf` in `[1, 5, 15, 60, 240, 1440]`, floor the index to `tf`-minute buckets
  (`index.floor("{tf}min")`).
- Within each bucket: `open`=first, `high`=cummax, `low`=cummin, `close`=raw 1-min close,
  `volume`=cumsum, `buy_volume`=cumsum of `taker_base_vol`.
- `{tf}_is_closed` = True at the last 1-minute row of each bucket (minute-modulo logic).

Every downstream consumer assumes this: the `{tf}_` column scheme, `is_closed`, the labels'
`n·tf`-minute forward window, the candle-bounds `frame()`, and the viewer's tf toggles. That
assumption is the integration cost (§7), and the reason this experiment is deliberately
**isolated** from the production pipeline (§4).

## 3. Bar constructions to test

Three standard event-bar types (López de Prado, *Advances in Financial ML*, ch. 2), each with
one threshold parameter:

| bar | closes when… | threshold | reads |
|---|---|---|---|
| **Volume** | cumulative base volume ≥ V | V | `volume` |
| **Dollar** | cumulative `close·volume` ≥ D | D | `close`, `volume` |
| **CUSUM** | cumulative absolute return since last bar ≥ θ | θ | `close` |

Dollar bars are usually the most stable of the three (they self-adjust as price level drifts,
unlike volume bars). CUSUM is the most directly tied to *price* activity rather than traded
size. All three are cheap to build from the raw 1-minute OHLCV the project already has —
`taker_base_vol` (buy volume) is present, so signed-volume variants are also possible later.

**Each event bar carries the same OHLC + volume fields as a time bar**, so it is a drop-in for
`frame()`'s inputs — `open`/`high`/`low`/`close`/`volume` per bar, plus a bar-close timestamp.

## 4. Isolation — do NOT rebuild the pipeline first

The cardinal mistake would be to re-plumb the production wide df for event bars before knowing
whether they help. Mirror how Proposal 1 reuses `frame()`: build event bars from raw 1-minute
OHLCV in a standalone script, compute features **on the event-bar series itself**, and run the
same range/direction tests. Nothing in `simple_trader/data.py` changes for the experiment.

Consequence for features: the production RSI/MACD/EMA columns are computed on **time bars** and
are meaningless on event bars. For the first test, use only the features that are computable
directly from the event-bar OHLCV series:

- **V block** — std/absmean of bar-to-bar returns, bar range %, bar body % (this was the
  *dominant* block for range anyway — `only_V` r² 0.26–0.38).
- **P block** — previous bar returns, rolling mean.

RSI/MACD on event bars would require recomputing those indicators on the new series — a second
step, only worth doing if V+P on event bars already shows movement. Do not front-load it.

## 5. Calibration — make the comparison fair

The confound to kill: event bars and time bars must produce a **comparable number of bars**,
or any metric difference is just sample-count, not sampling *quality*.

- Choose each threshold (V, D, θ) so the average bars/day ≈ the time-bar count at the tf being
  compared. E.g. to compare against 60-minute bars (24/day), tune D so dollar bars average
  ~24/day over the train window.
- Freeze the threshold on **train**, apply unchanged to OOS — same discipline as every frozen
  stat in this project. A threshold refit on OOS would leak.
- Report actual bars/day on both train and OOS; if OOS drifts far from train (regime change in
  activity), that is itself a finding.

## 6. The measurement — a direct A/B

Run the **identical** V+P range model and direction classifier (Proposal-1 machinery, or the
existing candle-bounds `frame()` restricted to V+P) on:

- **A:** time bars at tf ∈ {15, 60, 240} — the numbers we already have.
- **B:** each event-bar type, threshold-matched to each tf.

Then compare, with the parent doc's §2 protocol (null control, honest baseline, look-ahead
test) applying unchanged:

| metric | time bar (known) | event bar (new) | reading |
|---|---|---|---|
| range r² | 0.30–0.41 | ? | does better sampling sharpen the one thing that already works? |
| direction AUC | 0.48–0.54 | ? | **the decisive one** — does activity sampling move direction off 0.50? |
| null-control AUC | 0.47–0.51 | ? | the bar to clear |

**Two informative outcomes, both worth the cost:**

- **Direction AUC and range r² both move materially** → sampling was a real constraint;
  rebuilding on event bars is justified (→ §7).
- **Only range improves, direction stays ≈ 0.50** → the range/direction split is *structural*,
  not a time-bar artifact. That retires "sampling" as the explanation and points the sequencing
  at **data** (Proposals 3/4), which is a valuable narrowing.

## 7. Integration cost (only paid if §6 succeeds)

If event bars win the A/B, productionizing them touches the spine of the pipeline. Scoped here
so the cost is known before step 6, not discovered after:

1. **Bar builder** replaces `_build_wide_df`'s time-floor with a threshold-crossing scan.
   Irregular close times break the minute-modulo `is_closed` logic — `is_closed` becomes
   "threshold crossed," and there is no longer a single 1-minute base grid shared across tfs.
2. **`{tf}_` column scheme** no longer maps to minutes. Bars need a new identity (bar index, or
   the tf-equivalent bars/day the threshold was tuned to). Every `{tf}_`-keyed consumer is
   affected.
3. **Labels' forward window** (`n·tf` minutes, `_forward_labels`) must be redefined in *bars*,
   not minutes — "the next n bars," which is a different, non-constant time horizon.
4. **Viewer** tf toggles and the candle-bounds sidecar assume a time index; both need an
   event-bar-aware axis (bars are unevenly spaced in wall-clock time — the x-axis becomes bar
   index or a warped time axis).
5. **Multi-tf coexistence** — the current design derives all tfs from one 1-minute grid. Event
   bars at different thresholds do not share a grid; they are separate series. This is the
   deepest architectural change.

This is why Proposal 2 is *second*, not first: the experiment (§4–6) is cheap and isolated, but
acting on a positive result is a spine-level rebuild.

## 8. Success criteria

**Primary:** direction AUC > 0.55 out of sample on ≥1 event-bar type at ≥1 timeframe-equivalent,
with a passing null control **and** comparable bars/day to the time-bar baseline.

**Equally valuable negative:** a clean demonstration that event bars do **not** move direction
AUC above the null spread — this retires the sampling hypothesis and routes the sequencing to
the data hypothesis (Proposals 3/4), which is the point of running it.

Range r² improvement alone is **not** sufficient to justify the §7 rebuild — better sizing on
event bars does not pay for re-plumbing the pipeline; only a direction/edge gain does.

## 9. Concrete build order

1. **Bar builders** — volume, dollar, CUSUM, from raw 1-minute OHLCV. Standalone script. Unit
   test each against a tiny synthetic series (known threshold crossings).
2. **Calibration** — tune each threshold on train so bars/day ≈ the 15/60/240 time-bar counts;
   freeze; report train + OOS bars/day.
3. **Feature frame on event bars** — V+P blocks, computed on the event-bar series, k−1 aligned.
   Look-ahead mutation test (parent §2.4) — an event bar's own data must not enter its own
   features.
4. **A/B range model** — r² event vs time, null control, all three bar types.
5. **A/B direction classifier** — AUC event vs time, null control. **The decisive step.**
6. **Decision** against §8. If positive, open a separate spec for the §7 rebuild. If negative,
   route to Proposal 3/4 with "sampling is not the constraint" established.

## 10. Risks and honest priors

- **Prior leans negative.** Volatility clustering (why range is predictable) is a *magnitude*
  property; event bars sharpen magnitude sampling, so range r² may well improve. Direction is a
  *sign* property, and there is no strong theoretical reason activity sampling recovers sign
  from OHLCV alone. Expect range↑, direction flat — which is the "route to data" outcome, still
  worth having.
- **Look-ahead is subtler on event bars.** A bar's close time depends on future ticks crossing
  the threshold, so "when does this bar end" is itself forward-looking if used carelessly.
  Features must use only *completed* prior bars; the mutation test is non-negotiable here.
- **Threshold drift.** Activity regimes shift; a train-tuned threshold can produce very
  different bars/day on OOS. Report it — large drift confounds the A/B and is itself a finding.
- **Small OOS.** Two months of event bars at ~24/day is ~1,400 bars — thinner than the
  time-bar count once, and the direction test is already sample-hungry. Underpowered results
  must be flagged, not reported as conclusions.

## 11. Relationship to the other proposals

- Runs **only if Proposal 1 fails** — asymmetry is cheaper and reuses more.
- A **negative** result here is the gate to Proposals 3/4: it establishes that the constraint is
  the **data** (OHLCV lacks the information), not how the data is sampled — which is the
  expensive conclusion that justifies collecting order-flow (P3) or going cross-sectional (P4).
- A **positive** result makes P3/P4 lower priority: if better sampling of existing data yields
  an edge, spend there before acquiring new data.
