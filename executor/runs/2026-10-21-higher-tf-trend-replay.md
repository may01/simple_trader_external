# Replay: a higher tf's trend flag as a filter on a lower tf's CB zone entry

Date: 2026-10-21. Question (user): how does a higher trend impact the signal's P&L — e.g. what is the profit
difference if the 15-min zones are filtered by the 60-min trend?

Today each tf's CB zone entry is vetoed only by its own tf's trend flag (`{tf}_cb_f_trend_{side}` = forming EMA-25
slope class, long vetoed on −1, short on +1, X 0.5, stats frozen on 2y). The 60- and 240-min flags are in the same
indicator stream but never consulted for a 15-min fire. This replay adds them.

Data / harness: the trend_ma_length exports (`cbov-check` postgres: `trade` 748 276 rows 10-16 22:29Z → 10-21 10:07Z,
`indicators`, `signal_log` 188 CbZoneEntry rows; Binance klines for the EMA-25 warm-up), window **10-17 22:00Z →
10-21 10:07Z (84 h)**; the fire-re-deriving harness (CbZoneEntryCheck on every trade, 1-min class X 0.7, candle stop,
cbnc target + trend-flip exit, reversals, paper = no fees). Only the flag per (tf, side) changes.
Scripts: [`…-replay.py`](2026-10-21-higher-tf-trend-replay.py) → [`…-replay-output.txt`](2026-10-21-higher-tf-trend-replay-output.txt);
[`…-2y-oos2m.py`](2026-10-21-higher-tf-trend-2y-oos2m.py) → `…-2y-oos2m-output-h{30,60,240}.txt`.

## 1. Variants

f{tf} = that tf's forming EMA-25 veto flag for the trade's side (pass unless the class is against the trade);
a{tf} = class equals the trade's direction (aligned); c{tf} = the closed-candle class's veto flag.

| key | tf 15 | tf 60 | tf 240 |
|---|---|---|---|
| live / e25 / none | stored flags / reconstructed own flags / always pass | | |
| hx15<60, hx15<240, hx60<240 | own ∧ f60 / own ∧ f240 / own | own / own / own ∧ f240 | own |
| ladder | own ∧ f60 ∧ f240 | own ∧ f240 | own |
| all<240 | own ∧ f240 | own ∧ f240 | own |
| rp15=60, rp15=240, rp60=240, rpall=240 | f60 / f240 / own / f240 | own / own / f240 / f240 | own / own / own / f240 |
| al15<60, al15<240, al60<240, alladder | own ∧ a60 / own ∧ a240 / own / own ∧ a60 ∧ a240 | own / own / own ∧ a240 / own ∧ a240 | own |
| cl15<60, clladder | own ∧ c60 / own ∧ c60 ∧ c240 | own / own ∧ c240 | own |
| nladder, n15<60 | f60 ∧ f240 / f60 | f240 / own | pass / own |
| livex15<60, livexladder | hx15<60 / ladder from the **stored** flags (reconstruction gate) | | |

## 2. Gates

| gate | number |
|---|---|
| fires reproduced (live flags) | 177 / 188 recorded CbZoneEntry rows at the same ms / side / tf, 4 within ±120 s, 7 unmatched (executor restarts); class 176/177, rule 176/177 |
| own flag reconstructed | e25 vs stored agreement 99.11–99.92 % per (tf, side), pass rates equal to 3 decimals; e25 net +3 783 vs live +3 732 (paired Δ +51) |
| cross flag reconstructed | livex15<60 +2 725 / hx15<60 +2 731 (paired Δ vs e25 −1 058 / −1 051); livexladder +3 479 / ladder +3 458 (−304 / −325) |
| provenance | all thresholds = the live `EMA_SLOPE_STATS`; nothing fitted on the window |

## 3. Paper replay, 84 h, no fees (full table in the output §VARIANTS)

| variant | n | net | PF | wr | stop / target / reversal | paired Δ vs e25 (CI90, P(Δ<0)) | H1 / H2 |
|---|---|---|---|---|---|---|---|
| live | 211 | +3 732 | 1.47 | 52 % | 99 / 74 / 37 | −51 | +1 733 / +1 999 |
| e25 | 212 | +3 783 | 1.48 | 51 % | 100 / 74 / 37 | 0 | +1 822 / +1 961 |
| none | 262 | +4 751 | 1.49 | 53 % | 120 / 73 / 68 | +968 ([−628, +2 582], 0.15) | +1 919 / +2 832 |
| **hx15<60** (the question) | 186 | **+2 731** | 1.39 | 51 % | 90 / 69 / 26 | **−1 051** ([−2 396, +149], **0.92**) | +691 / +2 041 |
| hx15<240 | 190 | +2 944 | 1.40 | 51 % | 92 / 68 / 29 | −839 ([−2 075, +244], 0.89) | +992 / +1 952 |
| hx60<240 | 209 | +3 895 | 1.51 | 52 % | 98 / 74 / 36 | +112 ([−328, +553], 0.34) | +1 838 / +2 057 |
| ladder | 161 | +3 458 | 1.57 | 52 % | 76 / 66 / 18 | −325 ([−1 930, +1 242], 0.62) | +1 314 / +2 143 |
| all<240 | 177 | +3 494 | 1.52 | 51 % | 84 / 67 / 25 | −289 ([−1 708, +1 080], 0.61) | +1 441 / +2 053 |
| rp15=60 | 194 | +2 820 | 1.38 | 51 % | 93 / 69 / 31 | −963 ([−2 436, +333], 0.87) | +660 / +2 160 |
| rp15=240 | 211 | +3 059 | 1.38 | 51 % | 102 / 67 / 41 | −724 ([−2 264, +788], 0.77) | +954 / +2 105 |
| rp60=240 | 217 | +4 479 | 1.55 | 52 % | 103 / 72 / 41 | +696 ([−217, +1 769], 0.12) | +2 059 / +2 420 |
| rpall=240 | 204 | +4 281 | 1.55 | 52 % | 97 / 65 / 41 | +498 ([−1 385, +2 448], 0.33) | +1 546 / +2 734 |
| al15<60 | 88 | +747 | 1.17 | 40 % | 53 / 28 / 6 | −3 036 ([−5 424, −801], 0.99) | +930 / −183 |
| al15<240 | 91 | +373 | 1.08 | 38 % | 56 / 28 / 6 | −3 410 ([−5 745, −1 261], 0.99) | +691 / −319 |
| al60<240 | 190 | +4 140 | 1.63 | 53 % | 85 / 79 / 26 | +357 ([−598, +1 298], 0.27) | +1 901 / +2 239 |
| alladder | 36 | +994 | 1.53 | 42 % | 20 / 15 / 0 | −2 789 ([−5 304, −324], 0.97) | +858 / +136 |
| cl15<60 | 182 | +2 534 | 1.36 | 49 % | 90 / 67 / 24 | −1 249 ([−2 523, −40], 0.96) | +649 / +1 885 |
| clladder | 155 | +2 892 | 1.48 | 50 % | 76 / 62 / 16 | −891 ([−2 601, +738], 0.81) | +1 265 / +1 627 |
| nladder | 180 | +3 716 | 1.53 | 51 % | 87 / 62 / 30 | −66 ([−2 023, +1 870], 0.52) | +1 338 / +2 378 |
| n15<60 | 212 | +3 548 | 1.43 | 50 % | 103 / 68 / 40 | −235 ([−1 676, +1 317], 0.61) | +1 051 / +2 497 |

Paired vs live gives the same picture (hx15<60 −1 000, P 0.92; rp60=240 +747, P 0.15; al15<60 −2 985, P 0.99).
Fee breakeven stays 0.016–0.023 %/side for every variant (alladder 0.033 % on 36 trades).

## 4. Mechanism — the e25 positions split by the higher tf's flag at the open

| opening tf | split | n | net | PF | stop share | mean |
|---|---|---|---|---|---|---|
| 15 | tf-60 veto **passes** | 137 | +1 189 | 1.22 | 50 % | +9 |
| 15 | tf-60 veto **fails** (would be removed by hx15<60) | **24** | **+906** | **2.43** | 33 % | +38 |
| 15 | tf-60 aligned | 32 | +218 | 1.15 | 59 % | +7 |
| 15 | tf-60 not aligned (removed by al15<60) | 129 | +1 877 | 1.42 | 45 % | +15 |
| 15 | tf-240 veto passes / fails | 142 / 19 | +1 691 / +404 | 1.31 / 1.68 | 49 % / 42 % | +12 / +21 |
| 15 | tf-240 aligned / not | 39 / 122 | +153 / +1 942 | 1.08 / 1.48 | 59 % / 44 % | +4 / +16 |
| 60 | tf-240 veto passes / fails | 33 / 7 | +995 / −408 | 1.91 / 0.16 | 39 % / 86 % | +30 / −58 |
| 60 | tf-240 aligned / not | 8 / 32 | +642 / −55 | 7.30 / 0.96 | 12 % / 56 % | +80 / −2 |

On the 15-min zones the sign is the opposite of the hypothesis: the entries taken **against** the 60-min (240-min)
trend are the better ones (PF 2.43 vs 1.22, stop share 33 % vs 50 %), and the entries **aligned** with the higher
trend are the worst cell (PF 1.15 / 1.08, stop 59 %). A 15-min zone touched while the higher EMA slopes the other way is
a pull-back into the zone that bounces; a zone touched with the higher trend behind it is a break-out through it.
Fire-level: hx15<60 removes 24 e25 fires (all tf 15) and adds 3; of the 24 removed positions 5 re-fire later from a
worse price (+366 → +187) and 3 hand the trade to a 60-min fire (−70 → +361); the other 24 "not opened" cost +466.
On the 60-min zones the 7 positions against the 240-min trend lose −408 (6 of 7 stopped) and the 8 aligned earn +642 —
the hypothesis's sign, but 7 and 8 trades on 84 h: hx60<240 +112 / rp60=240 +696 / al60<240 +357, none with P(Δ<0)
below 0.12.

Class mix at the e25 fires (per fire tf, long −1 = against): 15-min fires: tf-60 class against 28 / 160, tf-240
against 70 / 160, aligned 32 / 0 (the 240 class was never "up" and never "down for a short" in the window: 240 long
flag false 94 % of the window, see the 2026-10-17 memory); 60-min fires: tf-240 against 19 / 46.

## 5. 2y / oos2m stand-in

(filled from the tier-B outputs below)
