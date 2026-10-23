# CCI-14 (5- / 15-min candles) at the CB zone fire vs entry success — paper-run mapping

Date: 2026-10-21. Question (user): map main/'s CCI onto the live executor data; is there a relation between the
5-/15-min CCI at the fire and entry success — e.g. "CCI > 140 → we should wait for a better price"?

**Mapping.** main/ has no live frame with CCI, so the CCI is recomputed from the executor's trade feed with main/'s own
convention (`indicators/library/oscillators.CCI14Field` over `build_indicator_input`: the last 104 closed tf candles +
the forming candle, talib CCI 14) — [`cci_lib.py`](cci_lib.py). Gate: recomputed vs the stored `5_cci_14` /
`15_cci_14` of the 2y frame (part_00, 300 random rows per tf) |diff| median 7e-13 / 1e-12, max 5e-11. Candles here
come from trades (the executor's `candle` table holds only ~670 closed 1-min rows), the fire is intra-minute (forming
candle up to the fire trade) — the only deviation from the frame's minute rows. Signed value `adv` = CCI for shorts,
−CCI for longs = momentum pushing into the zone the trade fades.

Scripts: [`2026-10-21-cci-entry-quality-map.py`](2026-10-21-cci-entry-quality-map.py) (descriptive, output
[`…-map-output.txt`](2026-10-21-cci-entry-quality-map-output.txt)); counterfactuals = the stop-re-entry harness
[`2026-10-21-stop-reentry-replay.py`](2026-10-21-stop-reentry-replay.py) variants `cci{5,15}_skip{100,140}`,
`cci{5,15}_wait{100,140}_d{0.5,1,2}`, `cci5_band`, `wait_all_d1.0`; outputs
[`…-replay-output-full.txt`](2026-10-21-cci-entry-quality-replay-output-full.txt),
[`…-replay-output-candle-era.txt`](2026-10-21-cci-entry-quality-replay-output-candle-era.txt).
Status: **weak / inconclusive on 71.6 h — extremes on both sides stop out more, no monotone relation, the "wait for a
better price" action is negative or noise; the 2y test is designed in the spec.**

## 1. CCI at the fire vs outcome (simulated live rule, 171 positions, uniform candle stop)

| adv15 bin | n | stop-out | pair-P1 | net | mean | median MAE / stop-dist | MAE ≥ 1 stop | target before stop |
|---|---|---|---|---|---|---|---|---|
| < −200 | 2 | 50 % | 0 % | −7 | −4 | 0.82 | 50 % | 0 % |
| [−200, −140) | 4 | 75 % | 0 % | −40 | −10 | 1.64 | 75 % | 0 % |
| [−140, −100) | 16 | 62 % | 25 % | −161 | −10 | 1.55 | 69 % | 31 % |
| [−100, 0) | 59 | 46 % | 27 % | +748 | +13 | 0.84 | 47 % | 44 % |
| [0, 100) | 55 | 40 % | 15 % | +1 908 | +35 | 0.78 | 42 % | 45 % |
| [100, 140) | 17 | 47 % | 12 % | +87 | +5 | 1.08 | 53 % | 41 % |
| [140, 200) | 15 | 60 % | 33 % | +90 | +6 | 1.19 | 67 % | 13 % |
| ≥ 200 | 3 | 67 % | 0 % | −123 | −41 | 0.49 | 33 % | 0 % |

| adv5 bin | n | stop-out | pair-P1 | net | mean | median MAE / stop-dist | MAE ≥ 1 stop | target before stop |
|---|---|---|---|---|---|---|---|---|
| < −200 | 0 | | | | | | | |
| [−200, −140) | 2 | 50 % | 0 % | −7 | −4 | 0.82 | 50 % | 0 % |
| [−140, −100) | 5 | 80 % | 20 % | −171 | −34 | 1.99 | 80 % | 20 % |
| [−100, 0) | 41 | 54 % | 22 % | +171 | +4 | 1.23 | 59 % | 37 % |
| [0, 100) | 53 | 34 % | 15 % | +2 317 | +44 | 0.41 | 36 % | 53 % |
| [100, 140) | 34 | 47 % | 26 % | +625 | +18 | 1.23 | 59 % | 41 % |
| [140, 200) | 27 | 59 % | 26 % | −457 | −17 | 1.19 | 56 % | 22 % |
| ≥ 200 | 9 | 56 % | 11 % | +25 | +3 | 0.75 | 33 % | 11 % |

Recorded paper positions (95 with a fire record): same shape — adv15 ≥ 140 stops 80 % (n 10, net −226), [0, 100)
50 % (n 34, +562), [−140, −100) 89 % (n 9, −221), [−200, −140) 1 position (stop).

Threshold sweep and nulls (simulated, 171): AUC(adv → stop-out) 0.489 (adv15) / 0.507 (adv5), corr(adv, pnl) −0.01 /
−0.02. adv15 ≥ 140: 18 positions, stop 61 % vs 46 % below, net −33 vs +2 535; permutation Δstop-rate +0.15, null
90 % [−0.23, +0.21], P 0.18. adv5 ≥ 140: 36 positions, stop 58 % vs 45 %, Δmean pnl −34 (P 0.04), Δstop-rate P 0.11.
The relation is U-shaped (mid-range best, both extremes worse: adv15 ≤ −140 stops 4/6 at median MAE 1.6 stops, ≥ 140 stops 11/18), not "high CCI → bad"; the best bin [0, 100) on adv5
holds +2 317 of the +2 503 total — 53 trades, in-sample.

## 2. Actions replayed (Δ vs live, paired 6-h blocks; full 71.6 h / candle era 14.9 h)

| variant | full n / net | Δ full (P(Δ<0)) | era n / net | Δ era (P) |
|---|---|---|---|---|
| live | 171 / +2 503 | — | 38 / +237 | — |
| cci15_skip140 | 153 / +2 636 | +133 (0.41) | 33 / +673 | +436 (0.04) |
| cci15_skip100 | 136 / +2 642 | +139 (0.40) | 30 / +608 | +371 (0.14) |
| cci5_skip140 | 137 / +2 862 | +359 (0.32) | 29 / +351 | +113 (0.30) |
| cci5_skip100 | 101 / +2 453 | −50 (0.51) | 22 / +76 | −161 (0.73) |
| cci15_wait140 d0.5 / d1 / d2 (limit at price ∓ δ·mean range, 15 min) | 168 / +2 020, 166 / +2 155, 162 / +2 570 | −483 (0.89), −348 (0.74), +67 (0.45) | 38 / +351, +608, 35 / +637 | +114, +371, +399 (0.04) |
| cci5_wait140 d0.5 / d1 / d2 | +2 502, +2 297, +2 751 | −0, −206, +248 | +110, +249, +281 | −127, +11, +44 |
| cci15_wait100 d1 / cci5_wait100 d1 | +2 025 / +2 044 | −478 (0.75) / −459 (0.73) | +555 / +359 | +318 / +122 |
| cci5_band (trade only 0 ≤ adv5 < 100; in-sample ablation) | 53 / +1 629 | −874 (0.76) | 12 / +441 | +203 |
| wait_all_d1.0 (every fire → limit 1 range deeper; adverse-selection control) | 116 / +55 | −2 448 (0.99) | 26 / +71 | −166 |

Reading: skipping fires at adv ≥ 140 is a mild plus on both windows (the only consistent sign), inside noise on the
full window; "wait for a better price" fills preferentially on the trades that keep going (the control `wait_all`
loses 2 448, win rate 26 %) and is negative or noise at δ ≤ 1 range, ≈ live at δ = 2. The candle-era `cci15_*` P 0.04
rests on 3 blocks and the day the era covers. The in-sample band is negative despite the best bin — selection breaks
the reversal chain.


## 2b. Band filter: enter only when adv ∈ [−140, 140) (asked 2026-10-21 after the mapping)

Outputs [`…-replay-output-band-full.txt`](2026-10-21-cci-entry-quality-replay-output-band-full.txt),
[`…-replay-output-band-era.txt`](2026-10-21-cci-entry-quality-replay-output-band-era.txt) (per-side and per-side × tf
tables inside). Δ = paired 6-h-block bootstrap vs live.

| variant | full n / net / PF / win | Δ full (P(Δ<0)) | stop-outs full | era n / net / PF | Δ era (P) |
|---|---|---|---|---|---|
| live | 171 / +2 503 / 1.38 / 51 % | — | 82 | 38 / +237 / 1.17 | — |
| cci5 ∈ [−140, 140) | 135 / +2 869 / 1.59 / 53 % | +367 (0.32) | 62 | 29 / +351 / 1.32 | +113 (0.30) |
| cci15 ∈ [−140, 140) | 147 / +2 682 / 1.50 / 54 % | +179 (0.40) | 67 | 33 / +673 / 1.61 | +436 (0.04) |
| both ∈ [−140, 140) | 125 / +2 450 / 1.55 / 54 % | −53 (0.52) | 57 | 28 / +404 / 1.38 | +166 (0.30) |
| cci5 ∈ [−100, 100) | 94 / +2 631 / 1.84 / 56 % | +128 (0.47) | 40 | 22 / +76 / 1.08 | −161 (0.74) |
| cci15 ∈ [−100, 100) | 114 / +2 788 / 1.73 / 56 % | +285 (0.39) | 49 | 26 / +841 / 2.08 | +604 (0.03) |

By side (full window; era in the output file):

| variant | Buy n / net / PF / stop-outs | Sell n / net / PF / stop-outs |
|---|---|---|
| live | 80 / +467 / 1.14 / 44 | 91 / +2 036 / 1.64 / 38 |
| cci5 ∈ [−140, 140) | 60 / +897 / 1.38 / 31 | 75 / +1 972 / 1.79 / 31 |
| cci15 ∈ [−140, 140) | 72 / +516 / 1.18 / 38 | 75 / +2 165 / 1.91 / 29 |
| both | 57 / +702 / 1.32 / 29 | 68 / +1 748 / 1.77 / 28 |
| cci5 ∈ [−100, 100) | 40 / +387 / 1.24 / 21 | 54 / +2 244 / 2.50 / 19 |
| cci15 ∈ [−100, 100) | 52 / +1 163 / 1.65 / 24 | 62 / +1 625 / 1.79 / 25 |

Reading: every band lifts PF (1.38 → 1.5–1.8) and win rate by 2–5 points and removes 15–50 % of the trades, but the
net Δ is +128 … +367 with 90 % CIs of ± 1 500 — thinning, not information (cf. the random-skip control in the 2y
plan). The 5-min band helps the long side (+467 → +897, stop-outs 44 → 31), the 15-min band the short side (+2 036
→ +2 165, 38 → 29); combining both loses the reversal chain (−53). Fee-adjusted the bands are far better
(−13.5 k → −6 … −10 k) because fewer trades. The era P 0.04 / 0.03 for the 15-min bands rests on 3 blocks and the
same day that made `cci15_skip140` look good.

## 2c. Band grid (5-min × 15-min), random-skip control, long-run assessment (asked 2026-10-21)

Outputs [`…-replay-output-grid-full.txt`](2026-10-21-cci-entry-quality-replay-output-grid-full.txt),
[`…-replay-output-grid-era.txt`](2026-10-21-cci-entry-quality-replay-output-grid-era.txt). Cell = Δnet vs live
(paired 6-h blocks) / P(Δ<0) / PF / n; rows = `adv5` band, columns = `adv15` band ("none" = no filter on that tf).

Full window 71.6 h (live +2 503, PF 1.38, n 171):

| adv5 \ adv15 | none | ±100 | ±140 | ±200 |
|---|---|---|---|---|
| none | — | +285 / 0.38 / 1.73 / 114 | +179 / 0.40 / 1.50 / 147 | +131 / 0.19 / 1.42 / 166 |
| ±100 | +128 / 0.47 / 1.84 / 94 | −27 / 0.51 / 2.04 / 75 | −159 / 0.57 / 1.78 / 90 | +128 / 0.45 / 1.84 / 94 |
| ±140 | +367 / 0.33 / 1.59 / 135 | +61 / 0.47 / 1.78 / 98 | −53 / 0.51 / 1.55 / 125 | +367 / 0.33 / 1.59 / 135 |
| ±200 | −24 / 0.53 / 1.40 / 162 | +166 / 0.43 / 1.72 / 110 | +31 / 0.48 / 1.50 / 141 | −17 / 0.52 / 1.41 / 160 |

Candle-stop era 14.9 h (live +237, PF 1.17, n 38, 3 blocks):

| adv5 \ adv15 | none | ±100 | ±140 | ±200 |
|---|---|---|---|---|
| none | — | +604 / 0.03 / 2.08 / 26 | +436 / 0.04 / 1.61 / 33 | +86 / 0.26 / 1.24 / 37 |
| ±100 | −161 / 0.74 / 1.08 / 22 | +70 / 0.40 / 1.43 / 18 | −161 / 0.76 / 1.08 / 22 | −161 / 0.75 / 1.08 / 22 |
| ±140 | +113 / 0.29 / 1.32 / 29 | +342 / 0.16 / 1.80 / 21 | +166 / 0.30 / 1.38 / 28 | +113 / 0.30 / 1.32 / 29 |
| ±200 | −61 / 0.60 / 1.13 / 36 | +456 / 0.14 / 1.89 / 25 | +288 / 0.29 / 1.48 / 32 | −61 / 0.59 / 1.13 / 36 |

**Random-skip control** (same simulator, each fire skipped with probability p, 8 seeds):

| window | p | n | Δ mean ± sd | Δ range | PF range | fee-adjusted mean ± sd |
|---|---|---|---|---|---|---|
| full | 15 % | 150 | −324 ± 491 | [−1 071, +323] | 1.24–1.52 | −11 787 ± 479 |
| full | 30 % | 125 | −686 ± 733 | [−1 559, +331] | 1.18–1.69 | −9 822 ± 745 |
| era | 15 % | 33 | +10 ± 203 | [−401, +276] | 0.87–1.44 | |
| era | 30 % | 28 | −89 ± 289 | [−624, +440] | 0.65–1.70 | |

Per day (full window, n / net): live 26/+542, 40/+330, 74/+1 684, 31/−53; adv15 ±100 19/+225, 24/+220, 49/+1 757,
22/+587; adv5 ±140 22/+517, 30/+564, 59/+1 631, 24/+157; adv15 ±140 24/+432, 32/+124, 64/+1 788, 27/+337.

Reading:
- **Solo beats combined.** The user's example adv15 ±140 ∧ adv5 ±100 = −159 full / −161 era; every combination of
  two bands is below the better of its two solo bands on the full window (the second band removes trades the first
  already handled plus reversal re-entries). Best solo: `adv5 ±140` (+367 full, +113 era, −21 % trades) and
  `adv15 ±100` (+285 full, +604 era, −33 % trades). ±200 is a no-op (removes 3–9 trades).
- **Against random thinning:** a random 21 % cut costs ≈ −480 ± 600, a random 33 % cut −686 ± 733; the two solo bands
  sit ≈ +850 … +970 above the random mean, i.e. 1.3–1.4 sd. Fee-adjusted the same: bands −9.7 k / −8.0 k vs random
  −11.8 k / −9.8 k at the same trade counts. Suggestive, not decision-grade (the band CIs still span ± 1 500).
- **Consistency:** adv5 ±140 is ≥ live on 3 of 4 days (10-20 −53); adv15 ±100 loses on 10-18 / 10-19 (−317, −110)
  and wins on 10-20 / 10-21 (+73, +640) — its whole edge is the last 1.5 days, the same days that drive the era P 0.03.
- **Side:** adv5 bands act on longs (live Buy +467 → +897 at ±140), adv15 bands on shorts (+2 036 → +2 165 at ±140,
  +1 625 at ±100 but Buy +1 163).

**Can it be used on the long run?** Not from this sample: 4 days, 171 trades, one coin, one volatility regime, and
the candidate thresholds were read off the same data (in-sample). Arguments for: the effect is one-sided per CCI tf
(not a random cell), the mechanism is plausible (both CCI tails = fires into a momentum burst, where the candle stop
anchored at the fire price is 1–2 ranges from a running market), CCI is self-normalised (mean-deviation scaled) so
±100/±140 do not drift with volatility, and the bands beat random thinning by ≈ 1.4 sd on both the raw and the
fee-adjusted net. Arguments against: adv15 ±100's edge lives in 1.5 days; no combination survives; the thinning
itself is worth most of the fee-adjusted gain; `trend_ma_length` and `rule2_removal` showed on the same data that
every entry veto looks good in some window. Verdict: candidate, to be decided by the 2y / oos2m plan (steps 3–6 of
the spec: regime-matched permutation null, the random-skip control at the same counts, threshold frozen on 2y,
scored once on oos2m). Minimum to call it: 2y lower CI > 0 for `adv5 ±140` or `adv15 ±100` solo, oos2m Δ > 0, and
the forward-return rung keeps the sign.

## 2d. Decision per CCI value: decline / delayed entry / immediate (asked 2026-10-21)

Third action tested: **delayed entry after the CCI reverses** — the fire is held until `adv` drops back below X2
(100 or 0) within W (15 / 30 min), then the position opens at that trade with the candle stop recomputed there
(`cciwait{tf}_140to{X2}_W{W}`). Outputs [`…-waitcci-full.txt`](2026-10-21-cci-entry-quality-replay-output-waitcci-full.txt),
[`…-waitcci-era.txt`](2026-10-21-cci-entry-quality-replay-output-waitcci-era.txt); lower-tail skips in [`…-lowtail-full.txt`](2026-10-21-cci-entry-quality-replay-output-lowtail-full.txt) / [`…-lowtail-era.txt`](2026-10-21-cci-entry-quality-replay-output-lowtail-era.txt).

| action at adv ≥ 140 | cci5: fills / Δ full (P) / Δ era | cci15: fills / Δ full (P) / Δ era |
|---|---|---|
| enter immediately (live) | — / 0 / 0 | — / 0 / 0 |
| decline (skip) | 40 skipped / +359 (0.33) / +113 | 18 skipped / +133 (0.41) / +436 |
| delayed until adv < 100, W 15 / 30 | 20 / +329 (0.34) / +96; 24 / +301 / +150 | 3 / +72 (0.45) / +436; 3 / +72 / +436 |
| delayed until adv < 0, W 15 / 30 | 5 / +306 / +79; 6 / +311 / +79 | 0 / +133 / +436 (≡ skip) |
| delayed to a better price (limit 2 ranges deeper, 15 min) | 19 / +248 (0.40) / +44 | 11 / +67 (0.47) / +399 |
| delayed to a better price (limit 0.5 / 1 range) | −0 / −206 full | −483 / −348 full |

The delayed entries themselves are worth ≈ 0: cci5 "wait until adv < 100" fills 20 of 40 held fires and ends 30 below
plain skipping (+2 832 vs +2 862); the 15-min CCI rarely comes back inside 15–30 min (0–3 fills of 18), so delaying
≡ declining. Price-limit delays are worse than declining at every δ ≤ 1 and ≈ declining at δ = 2.

Decision table (paper run, 171 simulated + 95 recorded positions; nothing decision-grade, see §3):

| adv (signed CCI, momentum into the zone) | evidence | best action |
|---|---|---|
| [0, 100) | stop 34–40 %, net +1 908 (15 m) / +2 317 (5 m) of +2 503 total | enter immediately |
| [−100, 0) | stop 46–54 %, net +748 / +171; long side on cci5 is the weak part (n 19, stop 68 %, −172) | enter immediately |
| [100, 140) | stop 47 %, +87 / +625; cci5 band ±140 beats ±100 (+367 vs +128) | enter immediately |
| ≥ 140 | stop 58–61 %, net −33 / −432; skip +359 (5 m) / +133 (15 m); every delay ≤ skip | decline; if a delay is wanted, "adv back below 100" ≈ decline, never a price limit ≤ 1 range |
| [−140, −100) (momentum away from the zone) | 15 m: n 16, stop 62 %, −161, pair-P1 25 %, MAE 1.55 stops (Buy n 8 stop 88 % −429, Sell n 8 stop 38 % +268); 5 m: n 5, stop 80 %, −171; recorded 15 m n 9 stop 89 % −221. Skip only this bin: cci5 +172 full (P 0.25, 5 fires) / 0 era; cci15 +101 (0.41, 16 fires) / +232 era (4 fires) | decline, longs first (cci15 Buy +467 → +1 040 when skipped; Sell +2 036 → +1 563) — inside the noise |
| ≤ −140 | n 6–8, stop 67–88 %, −47 / −178; skip only this bin: cci15 +68 (6 fires), cci5 +7 (2 fires), era 0 | decline (tiny sample; costs nothing inside the band) |

## 3. Gates

| gate | number |
|---|---|
| CCI reproduction | main/ convention recomputed from the 2y frame's own candles: |diff| max 5e-11 (5 m), 4e-11 (15 m), 300 rows each |
| null (permutation) | Δstop-rate at adv15 ≥ 140 P 0.18, adv5 ≥ 140 P 0.11; AUC 0.49 / 0.51 |
| base rate | unconditional stop rate 48 %; extreme bins 60–70 % on n 3–27 |
| degeneracy | best bin is the widest, central one; the ≥ 200 bins have n 3 / 9 |
| adverse-selection control | wait_all_d1.0 −2 448 (P 0.99) |
| look-ahead | CCI at the fire trade uses closed candles + the forming candle up to that trade |
| sample | 171 / 38 positions, 13 / 3 blocks — nothing here is decision-grade; the 2y design is the arbiter |
