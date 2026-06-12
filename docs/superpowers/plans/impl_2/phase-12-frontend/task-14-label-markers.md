# Task 14: Profit-label markers on the OHLC chart

**Phase:** 12 — Frontend
**Depends on:** Task 13 (chart UX)
**Produces:** per-label marker traces on the price subplot

---

## Goal

Show where each configured profit label (`labels:` section of `indicators_config.yaml`) fires, directly on the candles.

---

## Context

`indicators/labels.py` writes binary columns `{tf}_plong_<suffix>`, `{tf}_pshort_<suffix>`, `{tf}_pslong_<suffix>`, `{tf}_psshort_<suffix>` (1 = profitable entry at that candle). They are training targets, never indicator fields — the viewer reads them straight off the wide df.

---

## Files

- Modify: `frontend/data_viewer.py` — `_draw_label_markers`, `_LABEL_PREFIXES`, `_LABEL_OFFSET_STEP`
- Add: `tests/test_phase12_task14_label_markers.py`

---

## Interface

- One marker trace per label column, drawn only on rows where the label is 1; legend label = column name without TF prefix
- Longs (`plong`/`pslong`): triangle-up below the candle low; shorts (`pshort`/`psshort`): triangle-down above the high
- Colours: `plong` limegreen, `pslong` green, `pshort` orange, `psshort` red
- Stacking: each variant on a side gets the next 0.2 %-of-price offset step, so several label sets never overlap

---

## Key Constraints

- Skip-if-absent: datasets without label columns render unchanged
- All-zero label columns produce no trace (no empty legend entries)
- Markers go on the price subplot only — never the range/navigator row

---

## Verification

```bash
docker run --rm -v "$PWD":/code -w /code simple_trader \
  python3 -m pytest tests/test_phase12_task14_label_markers.py -q
```

Manual: on the 15m chart, green triangles sit under lows where long labels fired, orange/red triangles above highs for shorts; legend toggles each label set.

---

## Commit

`feat: profit-label markers on the OHLC chart`
