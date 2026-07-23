# Task 04 — Wiring (registry + config)

**Layer:** 4 indicators (`indicators/registry.py`, `configs/indicators_config.yaml`)
**Depends on:** task-03 GREEN
**Produces:** fields visible to the prepare pipeline

## Interface
```python
# indicators/registry.py — add entries
"zone_class_q":    lambda cfg: ZoneClassQField(),
"move_class_sym0": lambda cfg: MoveClassSym0Field(),
```
```yaml
# configs/indicators_config.yaml — add under classification group
- name: zone_class_q
  group: classification
  applies_to: [15, 60, 240, 1440]
  depends_on: [rsi_ma8]
  params: {}
- name: move_class_sym0
  group: classification
  applies_to: [15, 60, 240, 1440]
  depends_on: [rsi_ma8, rsi_ma8_diff]
  params: {}
```

## Integration test → prep (RED, Docker)
`test_config_registers_new_fields`: build the indicator set from config → both field names
resolve to their classes; a prepare run on a small df yields `{tf}_zone_class_q` and
`{tf}_move_class_sym0` columns for each applies_to TF.

## Unit tests (RED)
- registry keys resolve to correct classes.
- config entries parse; `depends_on` satisfied by existing `rsi_ma8`/`rsi_ma8_diff`.

## Constraints
- Column naming follows existing `{tf}_{name}` convention.
- No dependency cycles; both depend only on already-computed rsi fields.
