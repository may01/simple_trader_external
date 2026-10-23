# higher_tf_bounds_geometry — Results & Conclusion

**Date:** 2026-10-21 · **Spec:** [higher_tf_bounds_geometry.md](../higher_tf_bounds_geometry.md) · **Plan:**
[plans/2026-10-21-higher-tf-bounds-geometry.md](../../plans/2026-10-21-higher-tf-bounds-geometry.md) · **Branch:**
none in the code repo (read-only replay); docs on external `cross-tf-veto-replay` · **Run report:**
[executor/runs/2026-10-21-bounds-geometry-replay.md](../../../../executor/runs/2026-10-21-bounds-geometry-replay.md)
**Data:** paper exports of the `cbov-check` executor (window 10-17 22:00Z → 10-21 10:07Z, 84 h, 188 recorded CbZoneEntry
fires, stored `{tf}_cb_high/low/zone/inzone`); 2y (2023-01 → 2024-12, 1 052 560 rows) and oos2m (2025-01 → 2025-03,
84 961 rows) 1-min frames with the candle-bounds / cbnc sidecars and `1_atr_14_ma_5`.
**Pipeline:** `executor/runs/2026-10-21-bounds-geometry-replay.py` (imports the higher-tf-trend harness) and
`…-bounds-geometry-2y-oos2m.py` (pullback stand-in flow + geometry); hold 60.
**Final configuration:** veto per (tf, side) = own forming EMA-25 flag ∧ ¬state(H); states pos (favourable room share
f < 0.15), room (< 2 ATR1 / mean range), nest (lower tf's opposite bound within 1 ATR1 of H's bound), exz (H's opposite
zone executed in the current H candle, price ≥ 1 range beyond it); pairs 15←60, 15←240, 60←240, ladder; controls
mirror (f > 0.85) and 24-h-shifted placebo. Thresholds frozen on 2y; oos2m scored once.

## Headline conclusion

The hypothesis died. Where a 15-min (60-min) entry sits inside the 60-min (240-min) range, and whether the higher tf
has just executed its opposite bound, does not separate losing lower-tf entries from winning ones. On 2y the entries at
the *wrong* end of the higher range are the best cells (tf 15 short, f < 0.2 of the 60 range: PF 1.20–1.29, mean +9…+13
per entry vs +3.7 overall; beyond the 60 bound PF 1.27), so every range-position veto loses: pos0.15|15<60 −32 488
(P 1.00, 2 of 24 months positive), room2 −29 400, ladder −51 400; oos2m −4 416 / −5 932 / −8 435. The placebo loses
the same way (−15 859 / −4 366). On paper the best real variants (+80 / +477 on 14–16 of 238 fires) sit inside the
placebo (+355). The example's exact state (60 opposite zone executed this candle ∧ 15 opposite bound on the 60 bound)
marks average entries on 2y (PF 1.00 short / 1.07 long) and flips sign on oos2m (0.83 long / 1.09 short). Not proven:
nothing — no toggle.

## How the bounds connect (the descriptive deliverable; 2y, oos2m in brackets)

- Span in ATR1 (q50): 15-min 4.75, 60-min 10.1, 240-min 21.4 [4.1 / 8.4 / 16.9]; ratios 60/15 2.14, 240/60 2.13,
  240/15 4.55 — each step up roughly doubles the predicted range.
- The 15 range lies inside the 60 range on 60 % of minutes [53 %], pokes above the 60 high on 20 % and below the 60 low
  on 20 % [22 / 25 %]; never both. 60 inside 240: 62 % [57 %].
- Bound coincidence: |15 low − 60 low| ≤ 0.5 / 1 / 2 ATR1 on 6.6 / 13.7 / 29 % of minutes [9 / 18 / 38 %]; 15 vs 240
  ≤ 1 ATR1 4.9 % [6.8 %]; 60 vs 240 6.5 % [9 %]. The 15 range sits wholly in the lower half of the 60 range 21 % and in
  the upper half 24 % of the time [26 / 23 %].
- At the 15-min e25 entries the favourable room share against the 60 is q25 / q50 / q75 = 0.41 / 0.63 / 0.80 (long),
  0.45 / 0.66 / 0.83 (short): the lower-tf zone usually fires with the higher range on its side already; only ~10 % of
  entries have f < 0.2.

## The progression (paired Δ vs e25; paper 84 h / 2y 24 months / oos2m 2 months)

| variant | paper Δ (P) | 2y Δ (P, months+) | oos2m Δ (P) |
|---|---|---|---|
| pos0.15\|15<60 | +80 (0.42) | −32 488 (1.00, 2/24) | −4 416 (0.95) |
| room2\|15<60 | +477 (0.15) | −29 400 (1.00, 6/24) | −5 932 (0.97) |
| nest1\|15<60 | −505 (0.79) | −1 765 (0.56, 11/24) | −1 224 (0.66) |
| exz\|15<60 | −2 032 (0.98) | −11 015 (0.87, 8/24) | −1 803 (0.70) |
| exzpos0.15\|15<60 | +9 (0.34) | −800 (0.98) | −184 (0.96) |
| pos0.15\|15<240 | −734 (0.87) | −25 073 (0.99) | −7 359 (0.98) |
| exz\|60<240 | +23 (0.48) | +4 000 (0.25, 11/24) | +2 258 (0.10) |
| pos0.15\|ladder | −432 (0.72) | −51 400 (1.00, 7/24) | −8 435 (0.97) |
| exz\|ladder | −3 615 (0.99) | −32 487 (0.98) | −7 550 (0.94) |
| mirpos0.15\|15<60 (control) | −904 (0.87) | −18 085 (0.97) | −5 850 (0.96) |
| sh0.15\|15<60 (placebo) | +355 (0.30) | −15 859 (0.97) | −4 366 (0.93) |

## Degeneracies found

1. **The sign of f is the opposite of the hypothesis** — small f (entry at the wrong end of the higher range, or beyond
   its bound) is the best cell on 2y for shorts and longs alike and stays best OOS for shorts (f [0, 0.1) PF 2.24, n 55).
   A 15-min zone touched past the 60 bound is a deeper excursion that bounces harder: the counter-trend mechanism of
   the trend-filter run, seen through the bounds.
2. **Placebo ≈ real** — the 24-h-shifted f loses as much as the real f on 2y and oos2m and beats it on paper; the veto
   removes entries at random with respect to their outcome.
3. **User-case cell flips by tier and side** — 2y PF 1.00 short / 1.07 long, oos2m 0.83 long / 1.09 short on 138–1 400
   entries per cell.
4. exzpos (exz ∧ f < 0.15) is almost empty (1 of 238 paper fires, 0.2 % of 2y entries): the example's two conditions
   rarely coincide, because an executed opposite bound already puts the price ≥ 1 range into the higher range.

## Validity gates

| gate | number |
|---|---|
| Null floor / placebo | sh0.15\|15<60 −15 859 (2y) vs pos0.15 −32 488; paper +355 vs +80 / +477; oos2m −4 366 vs −4 416 |
| Base rate | e25 2y PF 1.05–1.09, mean +2…+4; every removed cell has mean ≥ +1.2 except nest ≤ 1 short (−0.1), exz∧nest short (−0.1) |
| Degeneracy | exzpos 0.2 % of entries; 2y ladder removes 17 % of entries and loses 31 % of the net |
| Truth ladder | paper (live flow) → 2y stand-in → oos2m: pos / room negative on all three in sign (paper inside the placebo) |
| Feature ablation | three independent quantities (range share, ATR room, bound coincidence) + executed-zone state: same sign |
| Look-ahead | stored bounds by received_at ≤ t with expiry (paper); closed-candle bounds reindexed to the row, exz from the cumulative in-zone flag within the H candle up to the row (2y); the shifted placebo reads the past |
| Provenance | `ZONE_FRAC` 0.05 reproduced from the stored zone lines on both tiers (median 0.0500); e25 / THR / FROZEN25 = the live frozen values; e25 baselines equal the sibling runs to the USDT |
| Reproduction | 177 / 188 recorded fires exact (harness gate); bounds present at 97.9 % of trades; thresholds frozen on 2y before oos2m was scored |

## What generalized vs what did not

- Did not: any veto on the lower tf from the higher tf's range position, room, bound coincidence or executed
  opposite bound (15←60, 15←240, ladder) — negative on 2y, oos2m and inside the placebo on paper.
- Did (descriptive): the bound ladder is a clean ×2 per step; the lower range nests in the higher one ~60 % of the
  time; bound coincidence within 1 ATR1 happens ~14 % of minutes (15 vs 60).
- Lead only: exz 60←240 (60-min entries while the 240 just executed its opposite zone) +4 000 / +2 258, P 0.25 / 0.10,
  9–13 paper fires; and, again, the small-f cell as a *positive* filter (same direction as the trend-filter's
  counter-trend cell and the pull-back run's mirror cell).

## Config & artifacts

Scripts and raw outputs in `external/executor/runs/2026-10-21-bounds-geometry-*`; no code-repo change; nothing
committed (docs on external `cross-tf-veto-replay`, uncommitted until approved). Paper exports reused from the
trend_ma_length session (copied into this session's scratchpad).

## Next arbiter

A positive filter built from the three sibling leads (counter-trend 15-min entries, entries against the higher tf's
done extreme, entries at the wrong end of the higher range) fitted on 2y and scored once on oos2m — not another veto.
