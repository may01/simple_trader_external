# Replay: the higher tf's range position / executed opposite bound as a veto on the lower tf's CB zone entry

Date: 2026-10-21. Question (user): how are the candle bounds of the tfs connected, and can the lower-tf entries that
lose *because of the bigger tf's move* be filtered by the higher tf's bounds? Example: the 15-min low zone executes,
price runs to the 15-min high bound and a short opens there, but the 15-min low bound sits on the 60-min low bound and
the 60-min candle keeps rising, so the 15-min reversal fails.

Sibling of [higher-tf-trend-replay](2026-10-21-higher-tf-trend-replay.md) and
[higher-tf-pullback-replay](2026-10-21-higher-tf-pullback-replay.md) (same exports, same harness imported as a module,
same window **10-17 22:00Z → 10-21 10:07Z, 84 h**, same e25 reference +3 783 / 212 positions). Scripts:
[`2026-10-21-bounds-geometry-replay.py`](2026-10-21-bounds-geometry-replay.py) → [output](2026-10-21-bounds-geometry-replay-output.txt);
tier B [`2026-10-21-bounds-geometry-2y-oos2m.py`](2026-10-21-bounds-geometry-2y-oos2m.py) → [output h60](2026-10-21-bounds-geometry-2y-oos2m-output-h60.txt).
Status: **answered — negative, no rule change (§6).**

## 1. Quantities at a fire (tf T, side s, price p; higher tf H; short shown, long mirrored)

| key | definition | veto when |
|---|---|---|
| f | favourable room share = (p − H_cb_low)/(H_cb_high − H_cb_low) for a short (1 − that for a long): 0 = the entry sits at the wrong end of H's range, 1 = at the right end | pos{q}: f < q |
| room | favourable room in units of the candle stop's mean 1-min range (paper) / ATR1 (2y, oos2m) | room{k}: room < k |
| nest | \|T_cb_low − H_cb_low\| ≤ δ ranges (the lower tf's **opposite** bound on H's same-side bound — the example's "15 low ≈ 60 low") | nest{δ} |
| exz | H's **opposite** zone was touched earlier in the current H candle, is not touched now, price ≥ 1 range beyond its zone line ("60 low executed, continues up") | exz |
| controls | mirpos{q}: f > 1 − q (opposite sign); sh{q}: f read 24 h earlier (placebo) | |

Pairs 15<60, 15<240, 60<240, ladder (15: 60 ∧ 240; 60: 240). Thresholds frozen on 2y (paired Δ vs e25 on the 15<60
pair, entry retention ≥ 60 %): **pos 0.15, room 2, nest 1**; the grid is also run for display only.

## 2. Gates

| gate | number |
|---|---|
| fires reproduced (live flags) | 177 / 188 recorded exact, 4 within ±120 s, 7 unmatched (restarts) — the harness's own gate, unchanged |
| stored bounds | `{tf}_cb_high/low` present at 97.9 % of the window's trades; span > 0 on 100 %; stored zone lines = low + 0.0500·span / high − 0.0500·span on every tf (kernel `ZONE_FRAC` 0.05) |
| span / mean 1-min range (paper) | q50 5.2 (tf 15), 11.1 (60), 24.0 (240) — ratios 2.1 / 2.2, as the 2y frame (§5) |
| state rates at the trades | pos0.15 (H 60) 0.28 / 0.25 long / short; room2 0.24 / 0.21; exz 0.22 / 0.23; placebo sh0.15 0.17 / 0.17; mirpos 0.25 / 0.28 |
| tier B e25 baseline | 2y +166 435 / 57 383 entries, oos2m +15 827 / 4 414 — identical to the pullback / trend-filter runs |

## 3. Paper replay, 84 h, no fees (paired Δ vs e25 by (open trade, side), bootstrap CI90, P(Δ<0))

| variant | n | net | PF | Δ vs e25 (CI90, P) | fires lost / new | variant | n | net | PF | Δ vs e25 |
|---|---|---|---|---|---|---|---|---|---|---|
| e25 | 212 | +3 783 | 1.48 | 0 | | none | 262 | +4 751 | 1.49 | +968 (0.16) |
| **pos0.15\|15<60** | 201 | +3 863 | 1.52 | **+80** ([−578, +756], 0.42) | 14 / 3 | pos0.15\|ladder | 183 | +3 351 | 1.50 | −432 (0.72) |
| room2\|15<60 | 198 | +4 260 | 1.60 | +477 ([−290, +1 192], 0.15) | 16 / 2 | room2\|ladder | 189 | +3 490 | 1.51 | −293 (0.68) |
| nest1\|15<60 | 191 | +3 278 | 1.47 | −505 ([−1 604, +468], 0.79) | 23 / 0 | nest1\|ladder | 187 | +3 250 | 1.48 | −533 (0.78) |
| exz\|15<60 | 162 | +1 751 | 1.27 | **−2 032** ([−3 678, −492], 0.98) | 65 / 9 | exz\|ladder | 117 | +168 | 1.04 | −3 615 (0.99) |
| exzpos0.15\|15<60 | 212 | +3 791 | 1.48 | +9 (0.34) | 1 / 1 | exz\|60<240 | 208 | +3 805 | 1.51 | +23 (0.48) |
| mirpos0.15\|15<60 (control) | 202 | +2 878 | 1.38 | −904 (0.87) | 29 / 13 | mirpos0.15\|ladder | 188 | +2 206 | 1.32 | −1 577 (0.96) |
| **sh0.15\|15<60 (placebo)** | 192 | +4 138 | 1.60 | **+355** ([−695, +1 352], 0.30) | 26 / 6 | sh0.15\|ladder | 176 | +2 590 | 1.39 | −1 193 (0.91) |
| pos0.15\|15<240 | 189 | +3 049 | 1.43 | −734 (0.87) | | pos0.35\|15<60 | 183 | +3 738 | 1.55 | −45 (0.52) |
| room2\|15<240 | 197 | +2 920 | 1.40 | −862 (0.93) | | pos0.5\|15<60 | 161 | +2 462 | 1.40 | −1 321 (0.89) |

The best real variants (+80 / +477) touch 14–16 of 238 fires and sit inside the placebo's range (+355); every ladder
and every 15<240 variant is negative; the executed-opposite-zone veto (exz) is clearly negative (−2 032, P 0.98;
ladder −3 615, P 0.99). Halves: pos0.15|15<60 +1 431 / +2 432 vs e25 +1 822 / +1 961 — the gain is one day (10-20
+2 196 vs +1 702), the other days lose. Fee breakeven unchanged (0.018–0.020 %/side; exz|15<60 0.011 %).

## 4. Mechanism — the e25 positions split by the higher tf's geometry at the open (paper)

| opening tf 15 by H 60 | n | net | PF | stop | mean |
|---|---|---|---|---|---|
| f < 0 (beyond the 60 bound, against) | 10 | −64 | 0.88 | 60 % | −6 |
| f [0, 0.15) | 4 | −161 | 0.20 | 50 % | −40 |
| f [0.15, 0.35) | 18 | +40 | 1.03 | 61 % | +2 |
| f [0.35, 0.75) | 94 | +1 012 | 1.31 | 48 % | +11 |
| f [0.75, 1] and beyond | 35 | +1 267 | 2.11 | 37 % | +36 |
| **exz = True** (60's opposite zone executed this candle) | **58** | **+1 247** | **1.61** | 47 % | +21 |
| exz = False | 103 | +848 | 1.22 | 49 % | +8 |
| nest1 = True (15 opposite bound on the 60 bound) | 21 | +230 | 1.23 | 52 % | +11 |

On paper the four worst fires do sit at f < 0.15 of the 60-min range (the hypothesis's picture), but there are 14 of
them and the 60-min "executed opposite zone" state — the example's "60 keeps rising" — marks the *better* 15-min
entries (PF 1.61 vs 1.22). Against the 240: f [0, 0.25) n 21 −771 (PF 0.35), f [0.35, 0.5) n 33 +1 439 (PF 2.84).

## 5. 2y / oos2m stand-in (hold 60; paired Δ vs e25 by candle, P(Δ<0), months with Δ > 0)

Bound geometry (2y, all minutes; oos2m in brackets): span / ATR1 q50 4.75 (15), 10.1 (60), 21.4 (240) [4.1 / 8.4 /
16.9]; span ratio 60/15 q50 2.14, 240/60 2.13, 240/15 4.55; the 15 range is nested inside the 60 range 60 % of the
minutes [53 %], pokes above the 60 high 20 % and below the 60 low 20 % [22 / 25 %]; |15 low − 60 low| ≤ 0.5 / 1 / 2 ATR1
on 6.6 / 13.7 / 29 % of minutes [9 / 18 / 38 %]; |15 low − 240 low| ≤ 1 ATR1 on 4.9 % [6.8 %]; the 15 range sits in
the lower half of the 60 range 21 % and in the upper half 24 % [26 / 23 %].

| variant | 2y Δ (CI90, P, months+) | oos2m Δ (CI90, P) |
|---|---|---|
| pos0.15\|15<60 | **−32 488** ([−45 006, −19 609], 1.00, 2/24) | **−4 416** ([−8 959, +6], 0.95) |
| room2\|15<60 | −29 400 (1.00, 6/24) | −5 932 (0.97) |
| nest1\|15<60 | −1 765 ([−16 758, +12 706], 0.56, 11/24) | −1 224 (0.66) |
| exz\|15<60 | −11 015 (0.87, 8/24) | −1 803 (0.70) |
| exzpos0.15\|15<60 | −800 (0.98, 4/17) | −184 (0.96) |
| mirpos0.15\|15<60 (control) | −18 085 (0.97, 10/24) | −5 850 (0.96) |
| sh0.15\|15<60 (placebo) | −15 859 (0.97, 8/24) | −4 366 (0.93) |
| pos0.15\|15<240 / room2 / nest1 / exz | −25 073 / −26 422 / −5 568 / −22 314 (0.99–1.00 / 0.82 / 0.99) | −7 359 / −6 881 / −2 554 / −9 313 (0.98–1.00 / 0.86) |
| pos0.15\|60<240 / room2 / nest1 | −7 077 (0.92) / −9 113 (0.98) / −5 746 (0.91) | −501 / −698 / +188 (0.61 / 0.65 / 0.45) |
| **exz\|60<240** | **+4 000** ([−6 744, +14 502], 0.25, 11/24) | **+2 258** ([−701, +5 224], 0.10, 2/2) |
| pos0.15\|ladder / exz\|ladder | −51 400 / −32 487 (1.00 / 0.98) | −8 435 / −7 550 (0.97 / 0.94) |
| grid (2y, 15<60): pos 0.25 / 0.35 / 0.5 | −33 566 / −42 817 / −50 484 (1.00) | — |
| grid (2y, 15<60): nest 0.5 / 2 | −11 068 (0.95) / −28 460 (0.98) | — |

Where the entries sit (2y, e25 entries of tf 15 split by f against the 60; short / long):

| f bin (60) | short n / PF / mean | long n / PF / mean |
|---|---|---|
| < 0 (beyond the 60 bound, against the trade) | 1 188 / **1.27** / +12.7 | 1 360 / **1.15** / +7.1 |
| [0, 0.1) | 535 / **1.29** / +13.3 | 538 / 1.07 / +3.3 |
| [0.1, 0.2) | 669 / 1.20 / +9.2 | 808 / 1.09 / +3.9 |
| [0.2, 0.5) | 4 259 / 1.06 / +2.8 | 4 582 / 1.00 / −0.1 |
| [0.5, 0.9) | 11 981 / 1.07 / +2.6 | 10 956 / 1.07 / +2.9 |
| [0.9, 1] and beyond | 4 053 / 1.08 / +3.2 | 3 367 / 1.00 / +0.3 |
| nest ≤ 1 ATR1 | 3 448 / 1.00 / −0.1 (else 1.11 / +4.4) | 3 460 / 1.03 / +1.5 (else 1.05 / +2.3) |
| exz (60 opposite zone executed this candle) | 3 762 / 1.04 / +2.0 (else 1.10 / +4.1) | 3 601 / 1.03 / +1.2 (else 1.05 / +2.3) |
| **user case: exz ∧ nest ≤ 1** | 1 356 / 1.00 / −0.1 (else 1.09 / +4.0) | 1 372 / 1.07 / +3.3 (else 1.05 / +2.1) |

oos2m reverses the user-case cell: tf 15 long by 60 exz ∧ nest PF 0.83 (n 138, −1 444, stop 68 %) and short PF 1.09
(n 139, +697); by 240 long 1.16 / short 1.25. The f < 0.2 bins stay the best cells OOS for shorts (f [0, 0.1) PF 2.24,
n 55; [0.1, 0.2) 1.40) and are mixed for longs ([0.1, 0.2) 1.81, [0.2, 0.3) 0.98).

The only consistent-sign cell is **exz 60<240**: 60-min entries while the 240 executed its opposite zone this
candle are worse (2y short PF 0.92 n 1 054 vs 1.13; long 1.00 vs 1.06; oos2m short n 15 PF 0.66) and the veto is
+4 000 (P 0.25) / +2 258 (P 0.10) — 9–13 fires on paper (+23), not decision-grade.

## 6. Verdict

**Negative.** The entry's position inside the higher tf's range does not separate the lower-tf entries that lose
from those that win: on 2y the entries at the *wrong* end of the 60-min range (f < 0.2, or beyond the 60 bound) are
the best cells (short PF 1.20–1.29, mean +9…+13 vs +3.7), so every range-position veto loses (−29 k … −51 k, P 1.00)
and the placebo / mirror lose the same way; oos2m −4.4 k … −10 k; on paper the best variants (+80 / +477 on 14–16
fires) sit inside the placebo (+355). The example's own state — the 60's opposite zone executed in the current
candle, 15's opposite bound on the 60's bound — marks average entries on 2y (PF 1.00 / 1.07) and flips sign on
oos2m. A 15-min zone touched at or past the higher bound is a deeper excursion that bounces harder — the same
counter-trend finding as the trend-filter and pull-back replays. No toggle.

## 7. Caveats

- Bounds are the closed-candle `cb_high / cb_low` of each tf; the forming-candle `cbnc` bounds were not used as the
  higher reference (the stored stream and the 2y frame carry both; the question was posed on the zone bounds).
- Paper tier: 238 fires, 84 h; the affected sets are 14–65 fires. Tier B carries the sample size with the stand-in flow.
- Thresholds were frozen on 2y and scored once on oos2m; the oos2m grid is printed post hoc and was not used.
