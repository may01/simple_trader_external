# cci_zone_excursion — CCI at CB zone entry, at the strict marker, and the in-zone excursion in 1-min ATR

**Date:** 2026-10-21 · **Status:** done (partial — answered, no threshold found) · **Branch:** none (read-only over the 2y / oos2m frames)
**Results:** [`results/cci_zone_excursion_results.md`](results/cci_zone_excursion_results.md) · **Script:** [`executor/runs/2026-10-21-cci-zone-excursion-2y.py`](../../../executor/runs/2026-10-21-cci-zone-excursion-2y.py) · outputs `…-output-2y.txt`, `…-output-oos2m.txt`

## Questions (user)

1. At what CCI-14 (5- / 15-min candle) level does the price enter a CB zone, and at what level does the strict
   target marker (`{tf}_ps{long,short}_n{1,2}…`, the viewer's dark markers) fire inside the zone?
2. With the market in the zone and CCI > 100 | 140 | a stats-based value: how far beyond the current extreme does the
   price still go, in 1-min ATR — to place a delayed entry and its stop by CCI level.

## Locked decisions (author's calls)

| # | decision | choice | date |
|---|---|---|---|
| 1 | data | 2y = `2y_link_usdt/df_with_indicators.part_00…24.pkl` (subset) + `df_with_candle_bounds.pkl` (`{tf}_cb_inzone_{side}`); oos2m single frame; tf 15 / 60 / 240 × long / short | 2026-10-21 |
| 2 | CCI | stored `5_cci_14`, `15_cci_14` (forming-candle rows); `adv` = CCI for the short zone, −CCI for the long zone | 2026-10-21 |
| 3 | strict marker | recomputed with `indicators/labels.py` `profit_strict_{long,short}` and the oos2m parameters (tf15 m1 x0.3 l15 y0.2; tf60 m1 x0.2 l15 y0.1; tf240 m1 x0.1 l15 y0.1; n 1 / 2); gate = equality with the stored oos2m columns | 2026-10-21 |
| 4 | zone block | consecutive in-zone minutes inside one tf candle; "entry" = its first minute; one sample per block for excursions (first minute meeting the CCI condition) | 2026-10-21 |
| 5 | excursion | (future extreme − current 1-min high) / `1_atr_14` for the short zone (mirror for long), horizons = to the tf candle close and the next 60 min; q50 / q75 / q90 / q95, P(> 1), P(> 2) | 2026-10-21 |
| 6 | delayed-entry table | limit at current extreme + δ·ATR1 (δ 0.5 … 3), P(filled) and P(a further s·ATR1 beyond the fill, s 1 / 2 / 3), horizon candle close, conditions adv ≥ 100 / ≥ 140 | 2026-10-21 |
| 7 | no fitting | fixed bins, p80 / p90 of the in-zone adv reported as the "stats-based" candidates; nothing selected | 2026-10-21 |

## Outcome

See the results file. One line: the zone is entered at adv5 ≈ +66 (tf 15) / +120 (tf 60) / +110 (tf 240) median;
the strict marker fires *more* often the higher adv is (tf 15: P 0.12 base → 0.18–0.21 at ≥ 200, 0.24–0.33 at the
zone-entry minute; oos2m same); the excursion beyond the current extreme is set by the tf (q50 0.7 / 1.7 / 3.6 ATR1 to
the candle close), CCI adds 15–40 % at the top bins and nothing that separates 100 from 140 from p90; the
stop-after-fill probability is flat in δ (memoryless), so a deeper delayed entry only lowers the fill rate.
