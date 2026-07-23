# Task 03 — Classification fields (zone_class_q, move_class_sym0)

**Layer:** 4 indicators (`indicators/library/classification.py`)
**Depends on:** task-02 GREEN
**Produces:** two new IndicatorFields + `_apply_cuts` helper

## Interface (signatures only)
```python
def _apply_cuts(x: pd.Series, cuts: list[float], base: int) -> np.ndarray: ...  # np.digitize + base; NaN→middle

class ZoneClassQField(IndicatorField):      # name="zone_class_q", feature rsi_ma8, zone_cuts, base 0 → 0..4
    def compute(self, data_point, tf: int) -> pd.Series: ...
class MoveClassSym0Field(IndicatorField):   # name="move_class_sym0", feature rsi_ma8_diff, move_cuts, base -2 → -2..2
    def compute(self, data_point, tf: int) -> pd.Series: ...
```
`applies_to=[15,60,240,1440]`, `group="classification"`, `resource_dependencies=["rsi_classification.json"]`.

## Integration test → prep pipeline (RED, Docker)
`test_new_fields_compute_from_cuts`: with a stubbed `rsi_classification.json` (known cuts),
`ZoneClassQField().compute(dp, 60)` → integer Series in 0..4 aligned to df index;
`MoveClassSym0Field().compute(dp, 60)` → −2..2. (Wires cuts json → field output column.)

## Unit tests (RED)
- `_apply_cuts`: values below `cuts[0]`→base; above `cuts[3]`→base+4; NaN→base+2 (middle);
  boundary values land in the documented tier.
- `zone_class_q`: quantile-cut input → ~balanced 5 classes (each ~15–40%, none empty on real-ish data).
- `move_class_sym0`: symmetric input → neutral class brackets 0; `+σ`→base+3, `+2σ`→base+4.
- dtype int; index preserved; uses `_get_tf_classification(tf)` fallback when TF absent.
- Legacy `zone_class`/`move_class`/`_five_tiers` unchanged (regression assert).

## Implementation
- Add `_apply_cuts`; add both field classes reading `zone_cuts`/`move_cuts` from
  `_get_tf_classification(tf)`. Mirror legacy NaN-→-middle policy.

## Constraints
- Do NOT touch `_five_tiers` or legacy fields (coexist).
- Middle tier index: zone base 0 → middle=2; move base −2 → digitize gives 0..4, subtract 2 → middle=0.
