# Task 11: Target / stop-loss price overlays — tgt_long, sl_long, tgt_short, sl_short

**Phase:** 12 — Frontend
**Depends on:** Task 07 (price overlays)
**Produces:** target/SL level lines on each TF's OHLC chart in `HistoryDashboard`

---

## Goal

Render the four target/stop-loss fields from the targets indicator group (`indicators/library/targets.py`) on the price axis of every timeframe's candlestick chart.

---

## Context

The fields are price-level series derived from close (`close × (1 ± mean_diff)` from `diff_stats.pkl`), so they belong on the price subplot, not an oscillator subplot. Computed per TF (15/60/240/1440) by the prepare stage; columns sit in the wide df as `{tf}_tgt_long` etc.

Fields:

- `tgt_long` — long target, `sl_long` — long stop-loss
- `tgt_short` — short target, `sl_short` — short stop-loss

---

## Files

- Modify: `frontend/data_viewer.py` — `_PRICE_AXIS_PREFIXES` gains `tgt_`/`sl_` routing; `_PRICE_OVERLAYS` and `_OVERLAY_COLORS` gain the four fields
- Add: `tests/test_phase12_task11_target_sl_overlays.py`

---

## Interface

- Routing: names starting with `tgt_` or `sl_` resolve to the price axis (`_indicator_subplot` returns `None`) — explicit indicator lists never create a stray subplot
- Default draw: `build_window_figure()` draws all four as lines on the price row, skip-if-absent
- Colours: targets greens / stop-losses reds; long darker, short lighter — `tgt_long` darkgreen, `sl_long` darkred, `tgt_short` mediumseagreen, `sl_short` indianred

---

## Key Constraints

- Skip-if-absent: datasets prepared without the targets group still render
- No new subplots — overlays join the existing price row
- Legend toggling is the on/off control (plotly default); no extra UI

---

## Verification

```bash
docker run --rm -v "$PWD":/code -w /code simple_trader \
  python3 -m pytest tests/test_phase12_task11_target_sl_overlays.py -q
```

Manual: on the 15m chart confirm the four lines track close at fixed percentage offsets — targets above (long) / below (short) close, SLs opposite.

---

## Commit

`feat: render tgt/sl target and stop-loss overlays on per-TF price charts`
