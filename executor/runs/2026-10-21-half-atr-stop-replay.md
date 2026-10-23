# Replay: CB zone stop = forming 15-min high/low ∓ 0.5 × ATR(1 min)

Date: 2026-10-21. Question (user): replay the live (paper) data and check how the profit changes if the stop loss is
reduced to High/Low + 0.5 × 1_min_atr.

Data: `cbov-check` paper stack (Binance LINKUSDT, paper balance 100 000, `RISK_PER_TRADE=100`,
`MAX_NOTIONAL_FRACTION=0.5`, `CB_STOP_MODE=candle` since 10-20 20:25Z, book stop before), fresh export 2026-10-21
17:20Z of `trade` (828 397 rows, 10-16 22:29Z → 10-21 17:20Z), `indicators` (42 CB names, 499 250 readings with
expiry; **the DB stores no ATR**), `signal_log` CbZoneEntry rows (207), `position_log` (1 879 rows). Window = whole
CB-armed history **10-18 11:41Z → 10-21 17:20Z (77.6 h, 608 132 trades)** and the candle-stop era **10-20 20:25Z →
10-21 17:20Z (20.9 h)**. Exports in the session scratchpad only (same SQL as the rule2 / stop-reentry harness).

Script: [`2026-10-21-half-atr-stop-replay.py`](2026-10-21-half-atr-stop-replay.py) = the
[`2026-10-21-stop-reentry-replay.py`](2026-10-21-stop-reentry-replay.py) harness (fire-re-deriving port of
cb-candle-stop @ `a6a5bc6`) with the stop offset made a knob (`offset` range / atr, `atr_mult`, anchors `forming` /
`min1` / `fire`, `size_live` sizing ablation). Outputs:
[`…-output-full.txt`](2026-10-21-half-atr-stop-replay-output-full.txt) (with per-trade tables),
[`…-output-candle-era.txt`](2026-10-21-half-atr-stop-replay-output-candle-era.txt).
Status: **answered — the asked stop (0.5 × ATR1 off the forming 15-min extreme) changes net by +348 on 77.6 h (P 0.25)
and +266 on the era (P 0.14), i.e. nothing distinguishable from live; the placement effect alone is +20 / +186, the rest
is risk sizing. The whole offset sweep 0.25 … 2.5 is non-monotone around live = noise on 186 positions.**

## 1. Rules compared

Live: stop = forming 15-min low (long) / high (short), including the current price, ∓ mean (high − low) of the last 60
closed 1-min bars (bars from the trades); 0.2 % placeholder when the candle stop is not adverse; size = min(100 / stop
distance, free × 0.5 / price) — a tighter stop is a bigger position until the notional cap.

ATR1 = `1_atr_14_ma_5` rebuilt from the trades (Wilder ATR-14 on closed 1-min bars with the gap to the previous close,
SMA-5, last closed bar at the fire) — the executor DB does not store it. Over the window ATR1 median 0.00946 vs
trailing-60 mean range 0.00923, ratio median 1.016 (p10 0.86, p90 1.22): **ATR1 ≈ the live offset unit**, so
`atr10` is the live rule with a slightly different offset and `atr05` ≈ `sm05` (live offset × 0.5).

| variant | anchor | offset | sizing |
|---|---|---|---|
| live | forming 15-min extreme | 1.0 × mean range 60 | 100 / dist |
| sm05 / sm075 | forming 15-min | 0.5 / 0.75 × mean range 60 | 100 / dist |
| atr025 … atr25 | forming 15-min | k × ATR1, k ∈ {0.25, 0.5, 0.75, 1, 1.5, 2, 2.5} | 100 / dist |
| **atr05** | forming 15-min | **0.5 × ATR1 — the user's rule** | 100 / dist |
| atr05_m1 | forming **1-min** bar extreme | 0.5 × ATR1 | 100 / dist |
| atr05_fire | the fire price (no anchor) | 0.5 × ATR1 | 100 / dist |
| atr05_sz / sm05_sz / atr10_sz | as atr05 / sm05 / atr10 | as atr05 / sm05 / atr10 | 100 / **live** dist (placement only) |

## 2. Reproduction gate

Live variant vs recorded fires (same side + tf within 60 s): recorded 207, simulated 202, matched 200, missed 7
(executor restarts), extra 2. Candle-stop port: 54/55 recorded candle-era stops reproduced within half a tick. Era:
recorded 54 positions net +438, sim-live 53 net +411.

## 3. Results — full window 77.6 h (186 live positions, 14 paired 6-h blocks)

| variant | trades | net | PF | win | stop-outs / mean | targets | median stop bp | size at cap | Δ vs live | 90 % CI | P(Δ<0) | blocks >/< | net @ 0.02 %/side |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| live | 186 | +2 679 | 1.38 | 52 % | 87 / −81 | 70 | 16.7 | 67 % | — | — | — | — | −767 |
| sm05 | 189 | +2 849 | 1.44 | 45 % | 101 / −64 | 63 | 12.5 | 82 % | +170 | [−596, +962] | 0.37 | 8 / 6 | −812 |
| sm075 | 187 | +3 357 | 1.51 | 50 % | 90 / −73 | 69 | 14.6 | 75 % | +677 | [+126, +1 151] | 0.02 | 11 / 3 | −206 |
| atr025 | 191 | +3 272 | 1.55 | 42 % | 108 / −55 | 59 | 10.3 | 89 % | +593 | [−201, +1 429] | 0.12 | 8 / 6 | −487 |
| **atr05** | 190 | **+3 027** | 1.46 | 45 % | 102 / −64 | 63 | 12.4 | 81 % | **+348** | **[−516, +1 193]** | **0.25** | 8 / 6 | −654 |
| atr075 | 187 | +3 554 | 1.54 | 51 % | 89 / −73 | 70 | 14.7 | 75 % | +875 | [+262, +1 459] | 0.01 | 12 / 2 | −5 |
| atr10 | 185 | +2 972 | 1.43 | 52 % | 85 / −81 | 71 | 16.8 | 68 % | +292 | [−54, +769] | 0.11 | 6 / 8 | −455 |
| atr15 | 180 | +3 203 | 1.50 | 60 % | 69 / −92 | 73 | 20.9 | 45 % | +523 | [−546, +1 765] | 0.24 | 5 / 9 | +114 |
| atr20 | 174 | +3 270 | 1.58 | 64 % | 56 / −98 | 76 | 24.5 | 24 % | +590 | [−547, +1 844] | 0.22 | 7 / 7 | +581 |
| atr25 | 169 | +3 028 | 1.61 | 68 % | 48 / −101 | 76 | 28.9 | 7 % | +349 | [−822, +1 484] | 0.31 | 8 / 6 | +731 |
| atr05_m1 | 192 | +3 533 | 1.70 | 37 % | 118 / −42 | 53 | 7.5 | 93 % | +853 | [−39, +1 728] | 0.06 | 11 / 3 | −308 |
| atr05_fire | 193 | +2 822 | 1.78 | 28 % | 139 / −26 | 38 | 4.2 | 98 % | +143 | [−1 318, +1 625] | 0.45 | 7 / 7 | −1 077 |
| atr05_sz | 190 | +2 700 | 1.44 | 45 % | 102 / −60 | 63 | 12.4 | 67 % | +20 | [−771, +754] | 0.48 | 9 / 5 | −816 |
| sm05_sz | 189 | +2 618 | 1.43 | 45 % | 101 / −60 | 63 | 12.5 | 67 % | −62 | [−846, +685] | 0.55 | 8 / 6 | −879 |
| atr10_sz | 185 | +2 903 | 1.41 | 52 % | 85 / −82 | 71 | 16.8 | 66 % | +223 | [−137, +755] | 0.26 | 6 / 8 | −529 |

Per day (live / atr05 / atr075 / atr05_m1): 10-18 +542 / +884 / +932 / +781; 10-19 +330 / +235 / +304 / +174;
10-20 +1 684 / +1 579 / +1 986 / +1 750; 10-21 +123 / +329 / +331 / +828.

Per tf (live → atr05): tf 15 +2 065 → +2 142 (stop-outs 63 → 74), tf 60 +49 → +110 (19 → 23), tf 240 +566 → +775
(5 → 5). Per side: long +718 → +747, short +1 961 → +2 280.

## 4. Results — candle-stop era 20.9 h (53 live positions, 4 blocks)

| variant | trades | net | PF | win | stop-outs / mean | targets | Δ vs live | 90 % CI | P(Δ<0) | net @ 0.02 %/side |
|---|---|---|---|---|---|---|---|---|---|---|
| live | 53 | +411 | 1.22 | 49 % | 26 / −73 | 18 | — | — | — | −577 |
| sm05 | 54 | +678 | 1.39 | 43 % | 30 / −57 | 16 | +266 | [−100, +668] | 0.13 | −350 |
| sm075 | 53 | +674 | 1.40 | 49 % | 26 / −65 | 18 | +263 | [+173, +318] | 0.00 | −328 |
| atr025 | 55 | +815 | 1.52 | 40 % | 32 / −48 | 15 | +404 | [−49, +938] | 0.06 | −243 |
| **atr05** | 54 | **+677** | 1.39 | 43 % | 30 / −57 | 16 | **+266** | **[−93, +645]** | **0.14** | −350 |
| atr075 | 53 | +648 | 1.38 | 49 % | 26 / −65 | 18 | +237 | [+162, +313] | 0.00 | −350 |
| atr10 | 53 | +385 | 1.20 | 49 % | 26 / −73 | 18 | −26 | [−88, +31] | 0.78 | −598 |
| atr15 | 50 | +560 | 1.34 | 58 % | 20 / −83 | 17 | +149 | [−345, +795] | 0.37 | −328 |
| atr20 | 49 | +521 | 1.31 | 61 % | 18 / −94 | 17 | +109 | [−285, +576] | 0.36 | −286 |
| atr25 | 48 | +461 | 1.29 | 65 % | 16 / −100 | 17 | +50 | [−240, +340] | 0.43 | −251 |
| atr05_m1 | 55 | +1 241 | 2.06 | 40 % | 32 / −36 | 15 | +829 | [+552, +1 132] | 0.00 | +164 |
| atr05_fire | 55 | +1 420 | 2.80 | 35 % | 36 / −22 | 12 | +1 009 | [+551, +1 514] | 0.00 | +312 |
| atr05_sz | 54 | +597 | 1.36 | 43 % | 30 / −55 | 16 | +186 | [−139, +467] | 0.15 | −404 |
| sm05_sz | 54 | +595 | 1.36 | 43 % | 30 / −55 | 16 | +183 | [−113, +471] | 0.14 | −406 |
| atr10_sz | 53 | +407 | 1.21 | 49 % | 26 / −73 | 18 | −4 | [−41, +33] | 0.57 | −581 |

## 5. Reading

1. **The asked rule is indistinguishable from live.** atr05 (= sm05 in live's units) Δ +348 / +266, both CIs straddle
   zero, 8 of 14 blocks up. It halves the stop (16.7 → 12.4 bp), turns 15 targets / reversals into stop-outs
   (87 → 102 stop-outs, mean loss −81 → −64) and makes the position bigger (size at the notional cap 67 → 81 %).
2. **The gain is sizing, not placement.** With the live stop distance sizing the position and the half-ATR stop only
   setting the exit (atr05_sz) Δ is +20 full / +186 era; sm05_sz −62 / +183. The risk-per-trade rule turns any
   tighter stop into a bigger bet, and the bigger bet is what adds the +300.
3. **Noise floor.** atr10 is the live rule with the offset unit changed by ≈ 1.6 % (ATR1 vs mean range) and still
   moves net by +292 on the full window (−26 on the era) — a few trades flip at a one-tick change of the stop. Any
   |Δ| ≲ 300 on this sample is that.
4. **The offset sweep is non-monotone.** 0.25 +593, 0.5 +348, 0.75 +875, 1.0 live, 1.5 +523, 2.0 +590, 2.5 +349:
   both tighter and wider "help", the live value sits in a local minimum — the signature of an overfit sweep on
   186 positions, not of a better offset. 0.75 is the sweep's best on both windows (P 0.01–0.02 / 0.00) and is the
   only cell to keep its sign on 10-18 … 10-21, but it is one of 15 variants read after the fact. The stop-reentry
   replay's ×2–2.5 (+605 / +636 on 71.6 h) is now +590 / +349 on 77.6 h with P 0.22 / 0.31 — six more hours
   moved it inside the noise.
5. **Anchor on the 1-min bar / the fire price** (atr05_m1, atr05_fire: 7.5 / 4.2 bp stops, 118 / 139 stop-outs at
   −42 / −26, win rate 37 / 28 %) looks strong on the era (+829 / +1 009, P 0.00 on 4 blocks) and on 10-21 alone
   (+828 / +1 103 vs +123) but the fire anchor loses on 10-18 and 10-19 (+346 / +1 vs +542 / +330) and the 1-min
   anchor's full-window P is 0.06 with its 10-21 day carrying half of the Δ. In-sample lead at best; it is the
   "scalp stop" regime (median hold 3.4 / 2.0 min) that pays the most fee per unit of net.
6. **Fees.** Paper = no fees. At 0.02 %/side (Binance futures maker tier) every variant with the 15-min anchor is
   negative on both windows (live −767 / −577; atr05 −654 / −350); only the 2–2.5 offsets are positive on the
   full window (+581 / +731) because they trade less and lose less to churn. A tighter stop does not change the
   fee verdict of [[project-trend-x-sweep]] (breakeven ≈ 0.021 %/side).

## 6. Verdict

Negative for the asked change: stop = forming 15-min high/low ∓ 0.5 × ATR1 is live + sizing noise. Keep the live
offset (× 1.0 mean range). The one thing worth carrying forward is the ablation pattern: any stop-offset proposal
must be scored with `size_live` to separate placement from risk sizing, and must clear the ≈ ±300 one-tick noise
floor on this sample. The 1-min-anchor lead needs a 2y / oos2m stand-in (and real fees) before anyone reads it.
