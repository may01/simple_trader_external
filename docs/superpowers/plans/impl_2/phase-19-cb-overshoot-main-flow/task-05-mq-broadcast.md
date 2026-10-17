# Task 05: MQ broadcast — two flags on the allowlist

**Phase:** 19 — CB Overshoot Main Flow
**Depends on:** Task 02
**Produces:** `configs/shared_indicators_config.yaml` +2 entries; broadcast tests pin them
**Gate:** G6

---

## Goal

`{tf}_cb_f_overshoot_{long,short}` travel as 1.0/0.0 with `on_change: true`; the float `cb_overshoot_*` does not travel (D3).

## Files

- Modify: `configs/shared_indicators_config.yaml`
- Modify: `tests/test_cb_broadcast.py`

## Interface

```yaml
  - name: cb_f_overshoot_long
    timeframes: [15, 60, 240]
    on_change: true
  - name: cb_f_overshoot_short
    timeframes: [15, 60, 240]
    on_change: true
```

## Tests (RED first)

`tests/test_cb_broadcast.py`:

- `ONCHG` += `cb_f_overshoot_long`, `cb_f_overshoot_short` (so `test_loader_default_file_contains_cb_entries` demands them with `on_change` True and TFS).
- The "not in allowlist" tuple += `cb_overshoot_long`, `cb_overshoot_short`.
- `test_overshoot_flag_published_as_float_on_change` — fake publisher: a flip from 1.0 → 0.0 on `cb_f_overshoot_long` publishes `15_cb_f_overshoot_long` = 0.0 immediately, inside the interval. (Reuse `_setup`.)
- `test_allowlist_cb_name_count` — 16 CB names (6 plain + 10 on_change) → 48 wire names. Pin.

## Steps

- [x] Edit the test file. Run → FAIL.
- [x] Add the two entries after `cb_f_trend_short`. Run → PASS (G6). Full `tests/test_cb_broadcast.py` green.
- [ ] Stage; describe; wait for confirmation. Suggested message: `feat(mq): broadcast cb_f_overshoot flags`.
