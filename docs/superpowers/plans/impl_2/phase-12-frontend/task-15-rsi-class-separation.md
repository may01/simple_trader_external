# Task 15: RSI class separation, per-TF stats, cross-TF label visibility

**Phase:** 12 — Frontend (+ data-layer fix)
**Depends on:** Task 14 (label markers)
**Produces:** distinct move/zone classifications per spec §5.7, NaN-free rsi_classification.json with diff stats, profit labels visible on every TF chart

---

## Goal

1. Profit-label markers visible on all TF charts, not only the chart's own TF.
2. `rsi_classification.json` valid for all TFs (no NaN entries; classes always computable).
3. `move_class` ≠ `zone_class` — momentum vs level, per spec.

---

## Context

Bug: both class fields bucketed `rsi_ma8` with identical conditions, making `zone_class == move_class + 1` on every row. Spec (`indicators-class.md` §5.7) defines `move_class` over `rsi_ma8_diff` and `zone_class` over `rsi_ma8`, five tiers each. Additionally short datasets (1-day smoke) produced NaN mean/std for 1440 — invalid JSON, degenerate classes.

---

## Files

- Modify: `indicators/library/classification.py` — `_get_tf_classification` (TF fallback), `_five_tiers`, reworked Move/ZoneClassField
- Modify: `indicators/attributes.py` — `_compute_rsi_classification` writes `diff_mean`/`diff_std`, skips TFs with <2 valid rows
- Modify: `configs/indicators_config.yaml` — `move_class` depends_on gains `rsi_ma8_diff`
- Modify: `frontend/data_viewer.py` — 5-tier marker colormaps; `_draw_label_markers` scans all-TF label columns on the raw window
- Add: `tests/unit/data_layer/test_rsi_class_separation.py`

---

## Interface

- `move_class`: `rsi_ma8_diff` vs `diff_mean ± diff_std` → −2..2; `zone_class`: `rsi_ma8` vs `mean ± std` → 0..4; tier boundaries at ±0.5·std / ±std; NaN → middle tier
- `rsi_classification.json` entry: `{mean, std, diff_mean, diff_std}`; missing TF → field falls back to nearest lower, then higher TF entry
- Viewer label markers: every `{anytf}_p(s)long/short_*` column drawn on every chart, deduped to the label's own TF grid, trace name = full column name (TF prefix included)

---

## Key Constraints

- Stats file never contains NaN (strict JSON parsers must accept it)
- Dataset regeneration required: class columns are baked into `df_with_indicators.pkl` and the stats file gains keys — delete `rsi_classification.json` before re-running the prepare pipeline
- Marker colormaps: red/orange/silver/lightgreen/green low→high for both fields

---

## Verification

```bash
docker run --rm -v "$PWD":/code -w /code simple_trader \
  python3 -m pytest tests/unit/data_layer/test_rsi_class_separation.py -q
```

Manual: on the rsi subplot, dot colour (momentum) and diamond colour (zone) differ where RSI is e.g. low but rising; 4h/1d charts show 15m label triangles.

---

## Commit

`fix: separate move_class (momentum) from zone_class (level), labels on all TFs`
