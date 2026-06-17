# Memo: Validate indicators and strip outliers before computing mean/std

**Status:** open / not yet implemented
**Area:** indicator statistics pipeline (`indicator_stats.json` generation)
**Related plan:** `superpowers/plans/impl_2/phase-13-indicator-warmup/`

## Decision

Before `mean` and `std` (standard deviation) are computed for any indicator
series, the series must be:

1. **Validated** — drop or flag NaN / inf / non-finite values, and reject
   warmup-region values that are not yet stable.
2. **Outlier-filtered** — remove statistical outliers from the sample so they
   do not distort the `mean` and inflate the `std`.

The cleaned sample is what feeds the `mean` / `std` written to
`indicator_stats.json`. Outliers are removed *only* from the stats
computation — the raw indicator values themselves are not altered.

## Why

`mean` / `std` are used as normalization anchors (z-scores, sided
`diff_prc_std_*`, `over_low` / `over_high` thresholds, target/SL offsets). A few
extreme values — warmup artifacts, gaps, bad ticks — pull the mean and blow up
the std, which silently mis-scales every downstream signal and label.

## Suggested approach (to refine when implemented)

- Validation: require finite values; honor existing warmup margin/trim
  (see `task-01-warmup-margin`, `task-02-warmup-only-input-trim-before-save`).
- Outlier rule: pick one and apply consistently per indicator —
  - IQR fence (drop outside `Q1 - 1.5*IQR` .. `Q3 + 1.5*IQR`), or
  - robust z-score via median / MAD (drop `|x - median| / MAD > k`), or
  - percentile clip (e.g. drop below p1 / above p99).
  Prefer median/MAD or IQR — both are robust to the very outliers we are
  removing, unlike a mean/std-based cut.
- Record in `indicator_stats.json` which rule + params were used and how many
  samples were dropped, so stats are reproducible and auditable.

## Open questions

- Per-indicator outlier rule vs. one global rule?
- Should sided stats (`diff_prc_std_*`) filter each side independently?
- Keep a count of dropped samples per field for monitoring drift?
