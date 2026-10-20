# trend_x_sweep — results

Date: 2026-10-20. Spec: [trend_x_sweep.md](../trend_x_sweep.md). Script:
[`executor/runs/2026-10-20-trend-x-sweep-replay.py`](../../../../executor/runs/2026-10-20-trend-x-sweep-replay.py),
full output [`…-output.txt`](../../../../executor/runs/2026-10-20-trend-x-sweep-replay-output.txt).
Verdict: **partial** — the live value X = 0.7 sits on a plateau (0.6–0.85) that no other value beats on the
recorded 4 days; the plateau is real against the degenerate ends (X ≥ 1.5, X → ∞) but the differences
inside 0.4–1.2 are inside the paired noise. **Keep 0.7.** The number that actually decides this system's
profit is the fee, not X (§6).

## 1. What was replayed

Binance LINKUSDT paper stack `cbov-check`, window **2026-10-17 22:00Z → 2026-10-20 21:23Z** (first trade
with the overshoot flags → last stored trade; 521 959 trades), replayed event by event:

- `signals::trend` ported (10 s buckets, 1-min trailing MA, σ over the 6 000-trade window bounded to 2 h,
  30-bucket warm-up); (slope, σ) computed once per trade, the class per X on top;
- `CbZoneEntryCheck` ported and **re-run on every trade** against the indicator snapshots the executor
  stored (latest reading with `received_at ≤ trade ts < expires_at`): overshoot/trend-flag veto, rule 1
  (in zone ∧ class = direction), rule 2 (previous 1-min candle from the trades rejected at the zone ∧
  class ∈ {neutral, direction}), once per (tf, side, zone value), both-sides veto, 60 s gap, highest tf;
- orchestrator: flat → open at the firing trade's price, same side while open → skip, opposite → reversal;
- stop = today's live rule for every X: forming-15m extreme ∓ trailing-60 mean 1-min range, 0.2 %
  placeholder when not adverse (0 of 178 fell back); trips on the crossing trade;
- close = extreme past the frozen `cbnc` target, then the opposite class; size `min(100/dist, free·0.5/entry)`
  (→ ~50 k USDT notional, ~84 USDT median risk); paper = no fees.

X is swept jointly (open gate + exit) and separately (one gate at a time, the other held at 0.7).

## 2. Gates

| Gate | Number |
|---|---|
| Reproduction (X = 0.7 vs the 152 recorded `CbZoneEntry` rows from 10-18 11:41Z) | **141/152 exact** (same ms, side, tf), 4 within ±120 s, 7 unmatched; class agrees 140/141 at the exact matches; \|slope diff\| ≤ 3.9e-5 (median 5e-14). The 7 unmatched fires sit right after the live run's restarts / feed gaps (10-18 11:41 arming, 10-19 13:01Z 5 564 s and 20:01Z 9 432 s gaps, 10-20 20:21Z restart), where the live once-per-zone state and warm-up restarted and the continuous sim's did not. 2 sim fires have no live counterpart. |
| Null floor | 178 trades at X = 0.7; bootstrap 90 % CI of the net [+1 135, +5 923], P(net < 0) 0.01. **Paired** against 0.7 (trades matched by opening trade, unmatched ones counted in full): every alternative in 0.3–1.2 has a paired CI straddling zero (e.g. 0.5: Δ −664 [−3 020, +1 678]; 1.0: Δ −507 [−2 910, +1 932]). Only X ≥ 2 and X = ∞ are near-significantly worse (Δ −2 741…−2 914, P(Δ < 0) 0.92–0.95). |
| Base rate / references | X = ∞ (no trend gate anywhere: rule 2 fires on any class, no trend-flip exit): +749 on 126 trades. X = 0.01 (sign only): +2 224 on 188. The band at 0.7 adds ≈ +1 270 over sign-only and ≈ +2 740 over no-gate, inside the CIs above. |
| Degeneracy | The optimum is interior (plateau 0.6–0.85, both flanks fall monotonically). Caveat: the peak coincides with the value the live run used, and the candle stop's offset rule was chosen on 10-20 data produced by X = 0.7 fires — the stop is held fixed here, but it was not chosen blind to X. |
| Ablation (which gate carries X) | Entry-only sweep (exit at 0.7): flat +3 095…+3 495 for X ∈ 0.6–1.2, +2 293 at X = ∞ (rule 2 only); low X adds fires (212 vs 201) and stops (97 vs 82). Exit-only sweep (entry at 0.7): **flat +3 131…+3 492 for X ∈ 0.01–1.0** — exiting on the first adverse bucket is as good as waiting for 0.7σ; past 1.2 the exit stops firing and the net falls to +1 424 at X = ∞. |
| Look-ahead | Indicators by `received_at ≤ trade ts` and unexpired; trend over trades up to and including the current one; rule-2 candle is the previous closed minute; stop offset over closed bars before the fire's minute; target frozen at the fire. |
| Provenance | Nothing fitted: every X is reported on the whole window; halves/days are a stability check. |
| Concentration | top-2 trades +804 of +3 490 at 0.7 (23 %); similar at every X. |
| Feed gaps | 18 gaps > 60 s in the trade table (the executor writes it, so a gap = the executor down); three long ones (5 564 s, 9 432 s, 305 s). |

## 3. Joint sweep (open gate and exit use the same X), paper, no fees

| X | n | net USDT | PF | win rate | ΣR | median hold | stops n / Σ | targets n / Σ | reversals n / Σ | fires | class mix up/down/neutral | CI90 of net |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.01 (sign only) | 188 | +2 224 | 1.30 | 47 % | +45.9 | 7.5 min | 97 / −7 416 | 56 / +5 770 | 35 / +3 870 | 212 | 50/49/1 | [0, +4 557] |
| 0.2 | 186 | +2 205 | 1.30 | 49 % | +42.0 | 7.0 | 93 / −7 317 | 60 / +5 898 | 33 / +3 624 | 209 | 43/41/16 | [−46, +4 474] |
| 0.3 | 186 | +2 310 | 1.32 | 49 % | +45.5 | 7.1 | 92 / −7 272 | 60 / +5 843 | 34 / +3 738 | 209 | 39/38/23 | [+28, +4 565] |
| 0.4 | 181 | +2 562 | 1.36 | 50 % | +46.7 | 7.1 | 88 / −7 019 | 60 / +5 769 | 33 / +3 812 | 204 | 36/34/30 | [+313, +4 857] |
| 0.5 | 181 | +2 826 | 1.41 | 51 % | +45.2 | 7.2 | 86 / −6 841 | 63 / +5 973 | 32 / +3 695 | 205 | 32/31/37 | [+565, +5 117] |
| 0.6 | 180 | +3 259 | 1.48 | 52 % | +49.8 | 7.4 | 84 / −6 740 | 64 / +5 845 | 32 / +4 153 | 204 | 29/28/43 | [+873, +5 685] |
| 0.65 | 178 | +3 320 | 1.50 | 52 % | +48.7 | 7.2 | 82 / −6 603 | 66 / +6 264 | 30 / +3 659 | 201 | — | [+987, +5 697] |
| **0.7 (live)** | **178** | **+3 490** | **1.52** | **52 %** | **+52.5** | **7.2** | **82 / −6 622** | **66 / +6 494** | **30 / +3 619** | **201** | **26/25/49** | **[+1 135, +5 923]** |
| 0.75 | 178 | +3 513 | 1.52 | 52 % | +51.8 | 7.4 | 82 / −6 642 | 66 / +6 605 | 30 / +3 551 | 201 | — | [+1 118, +5 962] |
| 0.8 | 177 | +3 428 | 1.52 | 53 % | +51.3 | 7.5 | 81 / −6 570 | 66 / +6 487 | 30 / +3 511 | 198 | 23/22/55 | [+987, +5 893] |
| 0.85 | 176 | +3 304 | 1.50 | 53 % | +49.8 | 7.2 | 81 / −6 574 | 66 / +6 387 | 29 / +3 492 | 198 | — | [+918, +5 840] |
| 0.9 | 175 | +3 090 | 1.47 | 53 % | +47.0 | 7.1 | 80 / −6 508 | 65 / +5 989 | 30 / +3 609 | 197 | 21/20/60 | [+744, +5 533] |
| 1.0 | 172 | +2 983 | 1.47 | 52 % | +43.7 | 7.1 | 78 / −6 311 | 63 / +5 383 | 31 / +3 911 | 193 | 19/17/64 | [+737, +5 378] |
| 1.2 | 167 | +2 667 | 1.45 | 50 % | +36.2 | 7.9 | 74 / −5 845 | 60 / +4 520 | 33 / +3 992 | 186 | 15/14/72 | [+436, +4 917] |
| 1.5 | 161 | +1 914 | 1.32 | 47 % | +27.9 | 8.5 | 71 / −5 675 | 54 / +3 365 | 36 / +4 224 | 183 | 10/9/81 | [−244, +4 165] |
| 2.0 | 156 | +700 | 1.11 | 38 % | +11.8 | 10.0 | 72 / −5 643 | 44 / +2 393 | 40 / +3 950 | 178 | 5/5/89 | [−1 479, +3 044] |
| 3.0 | 137 | +576 | 1.09 | 38 % | +9.4 | 11.0 | 74 / −5 728 | 17 / +1 055 | 46 / +5 248 | 174 | 2/2/96 | [−1 597, +2 900] |
| ∞ (all neutral) | 126 | +749 | 1.12 | 37 % | +12.2 | 11.1 | 75 / −6 209 | — | 51 / +6 959 | 174 | 0/0/100 | [−1 795, +3 449] |

X = 0 as coded is identical to X = ∞ (band 0 → `classify` returns Neutral), hence 0.01 for "sign only".

### Paired against X = 0.7 (same opening trade ⇒ same position; unmatched positions count in full)

| X | shared opens | only at X | only at 0.7 | Δ net | paired CI90 | P(Δ < 0) |
|---|---|---|---|---|---|---|
| 0.3 | 68 | 118 | 110 | −1 180 | [−4 092, +1 748] | 0.75 |
| 0.5 | 103 | 78 | 75 | −664 | [−3 020, +1 678] | 0.68 |
| 0.6 | 127 | 53 | 51 | −231 | [−2 297, +1 731] | 0.59 |
| 0.75 | 141 | 37 | 37 | +23 | [−1 805, +1 778] | 0.49 |
| 0.8 | 131 | 46 | 47 | −62 | [−2 241, +2 025] | 0.51 |
| 1.0 | 97 | 75 | 81 | −507 | [−2 910, +1 932] | 0.63 |
| 1.2 | 80 | 87 | 98 | −823 | [−3 577, +1 805] | 0.70 |
| 1.5 | 66 | 95 | 112 | −1 576 | [−4 434, +1 361] | 0.81 |
| 2.0 | 57 | 99 | 121 | −2 791 | [−5 801, +250] | 0.94 |
| ∞ | 46 | 80 | 132 | −2 741 | [−5 972, +512] | 0.92 |

### Stability (net by half of the window and by UTC day, joint X)

| X | H1 (→ 10-19 09:41Z) | H2 | 10-18 | 10-19 | 10-20 |
|---|---|---|---|---|---|
| 0.3 | +1 018 (97) | +1 292 (89) | +629 | +197 | +1 405 |
| 0.5 | +1 603 (94) | +1 224 (87) | +1 345 | +104 | +1 309 |
| 0.6 | **+1 796** (93) | +1 463 (87) | **+1 595** | +14 | +1 577 |
| 0.7 | +1 618 (92) | **+1 872** (86) | +1 463 | +334 | +1 624 |
| 0.75 | +1 676 (92) | +1 838 (86) | +1 409 | +408 | **+1 627** |
| 1.0 | +1 471 (88) | +1 512 (84) | +1 257 | **+426** | +1 240 |
| 1.5 | +1 211 (82) | +703 (79) | +1 148 | +259 | +552 |
| ∞ | +415 (66) | +334 (60) | +429 | +10 | +245 |

The best X moves between 0.6 and 1.0 from day to day; 0.7–0.75 is never the worst of the plateau. The
10-17 column (5 trades) is omitted.

## 4. Which gate the multiplier acts through

| sweep | X = 0.01 | 0.3 | 0.5 | 0.7 | 1.0 | 1.2 | 1.5 | ∞ |
|---|---|---|---|---|---|---|---|---|
| entry gate only (exit at 0.7) | +2 447 (188) | +2 295 (186) | +2 993 (181) | +3 490 (178) | +3 095 (172) | +3 098 (167) | +2 714 (162) | +2 293 (159) |
| exit gate only (entry at 0.7) | +3 375 (178) | +3 366 (178) | +3 260 (178) | +3 490 (178) | +3 410 (178) | +2 996 (178) | +2 490 (177) | +1 424 (147) |

- **Entry.** A narrow band (X ≤ 0.3) lets rule 1 fire on noise slopes: +8–11 fires, +10–15 stop-outs
  (−7.3 k vs −6.6 k), the win rate 47–49 % vs 52 %. A wide band (X ≥ 1.5) starves rule 1 (in-zone fires
  fall from 120 to ~60) and leaves rule 2, whose 60-min long leg is the one consistently losing cell
  (−317…−374 at every X).
- **Exit.** Indifferent between 0.01 and 1.0: once the extreme has passed the target, the first adverse
  bucket and the first 0.7σ-adverse bucket close within the same move. Past 1.2 the flip rarely comes,
  positions ride to a reversal (reversal P&L rises +3.6 k → +8.7 k) or the stop (−6.6 k → −7.3 k), and the
  net halves.

## 5. Per rule / tf / side at X = 0.7 (n: net)

in-zone 15 long 35: +390 · 15 short 44: +1 007 · 60 long 10: +30 · 60 short 11: +345 · 240 long 3: +151 ·
240 short 5: +800 · rejection 15 long 25: +528 · 15 short 29: +101 · **60 long 7: −317** · 60 short 6: +305 ·
240 long 1: +296 · 240 short 2: −146. Shorts carry the window (+2 412 vs +1 078 long); LINK fell 12.34 → 12.2
over it.

## 6. Fees — the number that matters more than X

The paper account charges nothing. Gross edge per trade is **≈ +3.9 bp of notional** at the best X (median
notional 50.5 k USDT, +19.6 USDT per trade). Net after a per-side fee f:

| X | gross | bp/trade | f = 0.01 % | 0.02 % | 0.05 % | 0.10 % | breakeven f/side |
|---|---|---|---|---|---|---|---|
| 0.3 | +2 310 | +2.5 | +577 | −1 156 | −6 356 | −15 023 | 0.013 % |
| 0.5 | +2 826 | +3.1 | +1 133 | −560 | −5 640 | −14 107 | 0.017 % |
| **0.7** | **+3 490** | **+3.9** | **+1 830** | **+170** | **−4 810** | **−13 111** | **0.021 %** |
| 0.75 | +3 513 | +3.9 | +1 855 | +197 | −4 777 | −13 068 | 0.021 % |
| 1.0 | +2 983 | +3.4 | +1 391 | −201 | −4 977 | −12 937 | 0.019 % |
| 1.5 | +1 914 | +2.4 | +451 | −1 012 | −5 403 | −12 719 | 0.013 % |
| ∞ | +749 | +1.2 | −367 | −1 484 | −4 834 | −10 417 | 0.007 % |

At a 0.1 %/side taker fee (Binance spot/margin VIP 0) every X loses ~13 k USDT over the 4 days; at
0.05 %/side every X loses ~5 k. The strategy as sized only survives a venue/tier with ≤ 0.02 %/side
(maker or futures-tier rates), and then only at the plateau X. No X choice moves the breakeven fee by more
than 0.01 %. Fee checking against the intended venue (MEXC futures per the connector work) is the next
decision, ahead of any X tuning.

## 7. Caveats

1. **4 days, one pair, one regime** (LINK 11.9–12.4). 178 trades; day-to-day best X wanders 0.6–1.0.
2. **Continuous sim vs restarted live**: the sim never resets the once-per-zone state, the 1-min bars or
   the trend warm-up; the 7/152 unmatched fires are at exactly those moments.
3. **Entry at the firing trade, stop at the crossing trade** (the paper account fills at the mid, ≈ 1 tick
   better per stop); the same model on every X, so the comparison is unaffected.
4. **The stop rule was picked on 10-20 under X = 0.7 fires** and is held fixed here; a different X might
   prefer a different offset. Not re-tuned (that would be a fit on the same window).
5. **Sizing is not risk-constant**: every trade sits at the 50 % notional cap, so the net is ~50 k notional
   × bp; R-multiples (ΣR column) tell the same story (0.7: +52.5 R over 178 vs 1.5: +27.9 over 161).
6. Not modelled: the `TREND_READING_MAX_AGE` 30 s staleness rule (the sim uses the same trade), the
   flat-wait after a reversal's close leg, the live 1 % placeholder era, the book stop era.

## 8. Decision

- **Keep X = 0.7** (anything in 0.6–0.85 is indistinguishable from it; 0.75 is +23 USDT on 178 trades).
- Do not spend the next tuning step on X: the exit gate is insensitive below 1.0 and the entry gate's
  plateau is 0.6–1.2. If anything in the trend module is to be revisited, it is the rule-2 60-min long leg
  (−317 at every X) and the restart resets, not the multiplier.
- The fee gate (§6) decides whether this system makes money at all: confirm the live venue's per-side
  rate for the intended account before another paper day is spent.
- Re-run this script when the trade store holds ≥ 2 weeks (`--start=` to pick the window); the cache
  makes a full sweep ~2 min.
