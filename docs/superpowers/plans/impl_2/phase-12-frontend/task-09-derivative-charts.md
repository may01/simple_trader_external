# Task 09: Price-derivative charts — diff fields with rolling means

**Phase:** 12 — Frontend  
**Depends on:** Task 06 (timeframe selection)  
**Produces:** price-derivative (diff field) subplots with rolling-mean overlays in each TF chart group

---

## Goal

Under every timeframe's chart group, render the price-derivative fields: close/high/low percent-diff series, each on its own subplot together with its rolling mean and mean-above/mean-below bands. Same MA-on-same-subplot rule as the oscillators: each derivative's smoothed lines draw with their source series.

---

## Context

Price derivatives live in `indicators/library/price_derivatives.py` and are computed per TF into the wide df. They are the raw material for NN features and signal thresholds — researchers need to see the diff series against its rolling statistics to sanity-check signal levels.

Configured derivative fields, grouped per subplot:

- `close_diff` subplot: `close_diff_prc`, `close_diff_prc_rm_20`, `close_diff_prc_rm_20_mean_above`, `close_diff_prc_rm_20_mean_below`
- `high_diff` subplot: `high_diff_prc`, `high_diff_prc_rm_20`, `high_diff_prc_rm_20_mean_above`, `high_diff_prc_rm_20_mean_below`
- `low_diff` subplot: `low_diff_prc`, `low_diff_prc_rm_20`, `low_diff_prc_rm_20_mean_above`, `low_diff_prc_rm_20_mean_below`
- `rsi_diff` subplot: `rsi_ma8_diff`, `rsi_ma12_diff`, `rsi_ma24_diff`

---

## Files

- Modify: `frontend/data_viewer.py` — derivative field set and subplot routing

---

## Interface

**`DataViewer`**

- `_DERIVATIVES: dict[str, list[str]]` — subplot name → field list, exactly the grouping above
- Routing: members of `_DERIVATIVES` resolve to their group's subplot, bypassing the base-name-split heuristic in `_indicator_subplot()` (which would wrongly split `close_diff_prc` to subplot `close`)
- All derivative fields draw via `draw_line`; `mean_above`/`mean_below` get muted colours so the raw diff and `rm_20` stand out
- Derivative subplots render below the oscillator subplots (Task 08 order), in the order: `close_diff`, `high_diff`, `low_diff`, `rsi_diff`

---

## Key Constraints

- Diff series oscillate around 0 — each derivative subplot gets a zero reference line (`fig.add_hline(y=0, ...)` on that row)
- Skip-if-absent per column, same rule as Tasks 07/08; a group with no present columns produces no subplot
- Full per-TF chart group after Tasks 07–09: price (with overlays) + volume + 4 oscillator subplots + up to 4 derivative subplots — verify the figure stays readable; if plotly default height makes rows unusably short, set total figure height proportional to row count in `create_figure` (contract change, note it in the figure-factory docstring)

---

## Verification

```bash
LONG_ENV=configs/long_dataset.env docker compose up -d view-full
curl -sf http://localhost:8080 >/dev/null && echo "serving"
docker compose down view-full
```

Manual: 15m group shows close/high/low diff subplots each with 4 lines around a zero line, plus the rsi_diff subplot with 3 lines.

---

## Commit

`feat: add price-derivative subplots with rolling means per timeframe`
