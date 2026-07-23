# Task 02 — Stats layer (additive cuts + side-stats companion)

**Layer:** 3 test data prep (`indicators/attributes.py`)
**Depends on:** task-01 GREEN
**Produces:** `rsi_classification.json` with `zone_cuts`/`move_cuts`; new `rsi_side_stats.json`

## Interface (signatures only)
```python
# indicators/attributes.py :: DataAttributes
def _compute_rsi_classification(self, df: pd.DataFrame) -> None: ...   # now also writes cuts
def _compute_rsi_side_stats(self, df: pd.DataFrame) -> None: ...       # NEW companion file
```
JSON contracts:
```
rsi_classification.json[tf] = {mean, std, diff_mean, diff_std,
                               zone_cuts:[c10,c30,c70,c90], move_cuts:[-1.0s,-0.3s,0.3s,1.0s]}
rsi_side_stats.json[tf][field][class] = {long_winrate, short_winrate,
                                         long_lift, short_lift, base_long}
   field in {"zone_class_q","move_class_sym0"}; class = "0".."4"
```

## Integration test → Layer 4 (RED, Docker)
`test_side_stats_feed_classification`: compute stats on a small df → load
`rsi_classification.json`, assert `zone_cuts`/`move_cuts` present & ascending; feed a cut
array into `_apply_cuts` (task-03) → 0..4 output. (Wires stats → field consumer.)

## Unit tests (RED)
- `zone_cuts` = ascending 4-vector = percentile(rsi_ma8_closed,[10,30,70,90]).
- `move_cuts` = `[-1,-0.3,0.3,1]·diff_std`, symmetric about 0.
- Additive: legacy `mean/std/diff_mean/diff_std` still present & unchanged.
- `<2 valid rows` TF → skipped, file never NaN (both jsons).
- `rsi_side_stats.json`: per class long+short winrate in [0,1], `long_lift=long_winrate−base_long`.
- Missing-TF fallback (`_get_tf_classification`) returns an entry carrying the new keys.

## Implementation
- In `_compute_rsi_classification`, after mean/std/diff_*: add `zone_cuts`, `move_cuts`.
- Add `_compute_rsi_side_stats` (called from `compute()` absent-only, same guard as the
  classification file). Forward return = close-to-close over 1 TF-bar on closed rows,
  side-agnostic; classify with the new cuts; tally per-class long/short winrate + lift.
- Full-data fit (decision 3). No change to `over_low/over_high`.

## Constraints
- Both json files: absent-only recompute; delete to regen ([[stale stats block recompute]]).
- Never emit NaN (strict parsers).
