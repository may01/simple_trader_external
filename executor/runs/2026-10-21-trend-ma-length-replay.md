# Replay: the CB zone trend filter from the EMA-7 / EMA-14 slope class instead of the EMA-25

Date: 2026-10-21. Question (user): the trend filter uses the slope of the EMA of closes (length 25 live — the user's
"ma 21 or 25"; no 21 exists in the flow); how does the profit change if the slope of the EMA-7 or the EMA-14 is used
for the trend filtering?

What "the trend filter" is: `{tf}_cb_f_trend_{side}` = main/'s `ema_25_slope_class` on the **forming** tf candle
(`ema_25_diff_prc` = (EMA-25 forming − EMA-25 of the previous closed candle) / previous · 100, class −1 / 0 / +1 by
mean ± 0.5·std frozen on the 2y closed candles, `EMA_SLOPE_STATS`); long is vetoed on −1, short on +1, NaN passes. The
executor's `CbZoneEntryCheck` reads it as a veto (0 vetoes, absent passes) beside the overshoot flag; the open itself
needs the 1-min trade-price MA class (rule 1 / rule 2), which is a different signal and is not touched here (its windows
were replayed on 2026-10-20: any slower trade-MA class is worse).

Data: `cbov-check` paper stack (Binance LINKUSDT, paper balance 100 000, `RISK_PER_TRADE=100`,
`MAX_NOTIONAL_FRACTION=0.5`): `trade` (748 276 rows, 10-16 22:29Z → 10-21 10:07Z), `indicators` (CB names + the
`{tf}_ema_7/14/25` forming snapshots, 30 s cadence / 300 s validity), `signal_log` CbZoneEntry (188 rows). Binance
LINKUSDT klines (1m / 15m / 1h / 4h, fetched 2026-10-21) for the EMA warm-up; 2y frame
`2y_az_link_usdt/df_with_indicators.pkl` for the N = 7 / 14 thresholds. Window = **10-17 22:00Z → 10-21 10:07Z
(84 h, 600 032 trades)**, as the trend-x-sweep replay.
Scripts: [`…-replay.py`](2026-10-21-trend-ma-length-replay.py) (the executor replay; full output
[`…-replay-output.txt`](2026-10-21-trend-ma-length-replay-output.txt)),
[`…-fit-2y-stats.py`](2026-10-21-trend-ma-length-fit-2y-stats.py) → [`…-ema-stats-2y.json`](2026-10-21-trend-ma-length-ema-stats-2y.json),
[`…-2y-oos2m.py`](2026-10-21-trend-ma-length-2y-oos2m.py) (the 2y / oos2m tier; outputs `…-2y-oos2m-output-h{30,60,240}.txt`).
Status: **answered — neither EMA-7 nor EMA-14 improves the trend filter; EMA-7 is worse on every tier; the
filter itself is the thing to question (§7).**

## 1. What was replayed

The trend-x-sweep harness (fires re-derived on every trade from the stored indicator snapshots, 1-min trade-MA class
at X = 0.7 for rule 1 / 2 and the trend-flip exit, orchestrator same-side skip / reversal, candle stop = forming-15m
extreme ∓ trailing-60 mean 1-min range with the 0.2 % placeholder, size `min(100/dist, free·0.5/entry)`, fire-trade
fill, paper = no fees) with **only the trend flag's source swapped**:

| variant | flag source |
|---|---|
| **live** | the stored `{tf}_cb_f_trend_{side}` readings (reproduction) |
| **e25 / e14 / e7** | forming class of the EMA-N, recomputed per trade: `ema_f = α·price + (1−α)·EMA_N(prev closed tf candle)`, `diff = (ema_f − prev)/prev·100`, class by mean ± 0.5·std; N = 25 with the live `EMA_SLOPE_STATS`, N = 7 / 14 with the same statistic fitted on the 2y closed candles (§2); closed EMA_N = talib EMA over the 105-candle window (main/'s `INDICATOR_WINDOW_ROWS`) |
| **c25 / c14 / c7** | class of the last **closed** candle's EMA-N change (shift + ffill; `run_ema_class.py`'s default) |
| **none** | the flag always passes |
| eNx1 / eNsign | X = 1.0 (wider neutral band, weaker veto) / X = 0.01 (sign only, strongest veto) |
| e14@tf / e7@tf | the shorter EMA on one tf only, the others keep e25 |

Author's calls (user not available; flag if you disagree): the flag's EMA length is the only change; thresholds for
N = 7 / 14 follow the N = 25 recipe (mean ± 0.5·std of the 2y closed-candle `diff_prc`, per tf), not a fit on the
replay window; the forming convention stays primary (it is what runs), the closed class is an ablation.

## 2. Frozen thresholds (2y closed candles, 2023-01-01 → 2024-12-31, `diff_prc` in %)

| tf | N = 7 mean / std (n) | N = 14 | N = 25 (fit) | N = 25 live `EMA_SLOPE_STATS` |
|---|---|---|---|---|
| 15 | +0.00198 / 0.17060 (70 163) | +0.00190 / 0.11939 (70 156) | +0.00188 / 0.08856 (70 145) | +0.00187 / 0.08855 |
| 60 | +0.00791 / 0.33308 (17 535) | +0.00767 / 0.23355 (17 528) | +0.00756 / 0.17377 (17 517) | +0.00759 / 0.17366 |
| 240 | +0.03173 / 0.65677 (4 379) | +0.03081 / 0.46243 (4 372) | +0.03076 / 0.34519 (4 361) | +0.03083 / 0.34433 |

Reproduction of the live numbers from the stored `{tf}_ema_25` on the same frame: mean relative diff 0 / 2.3e-16 / 0,
std 7.1e-6 / 2.9e-5 / 1.1e-4 = exactly `sqrt(n/(n−1))` — the live std is the sample std; the fitted 7 / 14 values use
the population std (a 1e-5 relative difference, irrelevant for a ±0.5σ band). The 105-window recomputation vs the
stored closed `{tf}_ema_25`: median relative diff 0, max 2e-4 / 1.9e-3 / 4.1e-3 (the frame's first candles).

## 3. Gates

| Gate | Result |
|---|---|
| Reproduction: fires | `live` re-fires **177 of the 188** recorded CbZoneEntry rows at the same ms / side / tf (+4 within ±120 s, 7 unmatched — all at the three executor (re)starts 10-18 11:41Z, 10-19 22:43Z, 10-20 20:25Z and one 10-20 00:21Z); class agrees 176/177, rule 176/177. |
| Reproduction: flag | the recomputed forming EMA-25 flag vs the stored `cb_f_trend` at every trade (stored present at 98.2 % of trades): agreement **99.35 / 99.11 / 99.59 / 99.16 / 99.71 / 99.92 %** (15 L / 15 S / 60 L / 60 S / 240 L / 240 S); pass rates identical to 3 decimals (0.732 / 0.779 / 0.718 / 0.768 / 0.505 / 0.994). The stored `{tf}_ema_N` snapshots vs the reconstruction: median relative diff 1.4–4.2e-5 (≈ ⅙ tick; the live value is computed from the forming 1-min price between snapshots). `e25` vs `live` in the simulation: +3 783 vs +3 732, paired Δ +51, CI90 [−606, +701]. |
| Look-ahead | by construction: prev-closed EMA from fully closed klines, the trade's own price as the forming close, indicators by `received_at ≤ t`, bars closed before the current minute. |
| Provenance | the only fitted numbers are the 2y closed-candle mean / std per (tf, N) (§2); the replay window selected nothing. |
| Null floor | 212 positions: bootstrap CI90 of the net ≈ ±2 600 around +3 800; every variant difference below is inside the paired CI unless stated. |
| Concentration | top-2 trades +740…+805 in every variant (the same two 240 trades). |
| Feed gaps | 3 gaps > 5 min (10-19 13:01Z 5 564 s, 10-19 20:01Z 9 432 s, 10-20 16:13Z 305 s). |

## 4. Results (paper, no fees, same flow for every row)

| variant | n | net | PF | win | R | stop n / net | target | reversal | fires (15/60/240) | paired Δ vs e25 | CI90 | P(Δ<0) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| live | 211 | **+3 732** | 1.47 | 52 % | +56.5 | 99 / −7 822 | 74 / +7 036 | 37 / +4 505 | 237 (179/46/12) | −51 | [−711, +600] | 0.55 |
| **e25** | 212 | **+3 783** | 1.48 | 51 % | +56.2 | 100 / −7 821 | 74 / +7 078 | 37 / +4 513 | 238 (180/46/12) | — | | |
| **e14** | 221 | **+3 951** | 1.49 | 52 % | +59.1 | 101 / −7 917 | 73 / +6 754 | 46 / +5 102 | 246 (186/47/13) | **+168** | [−825, +1 201] | 0.40 |
| **e7** | 223 | **+3 400** | 1.42 | 52 % | +51.5 | 102 / −8 052 | 71 / +6 011 | 49 / +5 428 | 247 (190/45/12) | **−383** | [−1 821, +1 058] | 0.67 |
| none | 262 | +4 751 | 1.49 | 53 % | +66.9 | 120 / −9 558 | 73 / +6 137 | 68 / +8 160 | 294 (220/58/16) | +968 | [−609, +2 601] | 0.17 |
| c25 | 212 | +3 784 | 1.48 | 52 % | +57.7 | 100 / −7 896 | 71 / +6 903 | 40 / +4 765 | 237 | +1 | [−692, +681] | 0.50 |
| c14 | 226 | +3 382 | 1.39 | 50 % | +52.3 | 109 / −8 587 | 70 / +6 337 | 46 / +5 619 | 250 | −401 | [−1 333, +553] | 0.76 |
| c7 | 230 | +3 833 | 1.45 | 52 % | +58.4 | 107 / −8 459 | 69 / +6 110 | 53 / +6 170 | 255 | +51 | [−1 063, +1 192] | 0.48 |
| e25x1 | 248 | +4 709 | 1.52 | 53 % | +66.7 | 113 / −8 954 | 73 / +6 176 | 61 / +7 474 | 279 | +926 | [−557, +2 394] | 0.15 |
| e14x1 | 248 | +4 848 | 1.54 | 53 % | +69.6 | 112 / −8 921 | 73 / +6 200 | 62 / +7 557 | 279 | +1 065 | [−391, +2 557] | 0.12 |
| e7x1 | 254 | +4 630 | 1.50 | 53 % | +66.6 | 115 / −9 125 | 73 / +5 973 | 65 / +7 769 | 285 | +847 | [−669, +2 344] | 0.18 |
| e25sign | 126 | +1 846 | 1.40 | 51 % | +23.9 | 59 / −4 516 | 55 / +5 450 | 11 / +900 | 147 | −1 937 | [−3 923, +128] | 0.94 |
| e14sign | 126 | +1 377 | 1.30 | 52 % | +16.0 | 58 / −4 488 | 57 / +5 051 | 10 / +801 | 140 | −2 406 | [−4 558, −411] | 0.98 |
| e7sign | 119 | +1 191 | 1.27 | 51 % | +15.8 | 52 / −4 256 | 54 / +4 802 | 12 / +650 | 131 | −2 592 | [−5 068, −186] | 0.96 |

By the opening fire's tf (n, net, PF) and by side:

| variant | tf 15 | tf 60 | tf 240 | long | short | rule 1 | rule 2 |
|---|---|---|---|---|---|---|---|
| e25 | 161, +2 095, 1.35 | 40, +587, 1.37 | 11, +1 101, 4.24 | 97, +1 048 | 115, +2 735 | 125, +2 886 | 87, +897 |
| e14 | 167, +2 242, 1.37 | 42, +664, 1.40 | 12, +1 045, 4.33 | 102, +1 223 | 119, +2 728 | 132, +2 948 | 89, +1 004 |
| e7 | 172, +2 066, 1.33 | 40, +564, 1.38 | 11, +770, 2.89 | 103, +753 | 120, +2 647 | 132, +2 838 | 91, +561 |
| none | 197, +2 374, 1.33 | 50, +1 656, 1.93 | 15, +720, 2.15 | 121, +1 681 | 141, +3 069 | 155, +4 488 | 107, +262 |
| c25 | 160, +2 127, 1.36 | 41, +556, 1.33 | 11, +1 101, 4.24 | 98, +1 219 | 114, +2 565 | 129, +2 944 | 83, +840 |

One tf at a time (the others keep e25): e14@15 +3 992 (Δ +209, P 0.35), e14@60 +3 690 (−93, 0.63), e14@240 +3 826
(+44, 0.27); e7@15 +3 725 (−58, 0.52), e7@60 +3 586 (−197, 0.66), e7@240 +3 600 (−183, 0.89). Nothing distinguishable;
the 240-zone cells have 11–12 trades.

Fees (0.1 %/side): every variant −16 k … −20 k; breakeven 0.016–0.021 %/side (e7 and c14 the lowest at 0.016 %).
Halves / days: e14 > e25 in H2 and on 10-19 / 10-20, < on 10-18 / 10-21; e7 < e25 in both halves; `none` > e25 on
every day but 10-18. Nothing flips with the split.

## 5. Mechanism

The flag is a veto on a small fraction of fires, and the shorter EMA mostly moves the veto rather than removing it.
Of the 238 e25 fires, e14 keeps 219 (loses 19 — 10 of them because its own flag was False there, the rest because the
fire sequence shifted — and adds 27, 21 of which e25 had vetoed); e7 keeps 202, loses 36 (24 by flag), adds 45 (34 by
flag). The classes at the e25 fires:

| N | long fires: class −1 (vetoed) / 0 / +1 | short fires: −1 / 0 / +1 (vetoed) |
|---|---|---|
| 25 | 0 / 94 / 12 | 22 / 110 / 0 |
| 14 | 6 / 89 / 11 | 19 / 108 / 5 |
| 7 | 11 / 90 / 5 | 9 / 110 / 13 |

So the EMA-7 class vetoes 11 of the longs and 13 of the shorts that the EMA-25 let through — fires taken at a zone
while the fast EMA still slopes against the trade — and lets through fires the EMA-25 vetoed. Position-level, e25 →
e7: the 139 tf-15 trades opened at the same trade gain +248 in aggregate (slightly different reversal timing because
the fire stream around them changed), 7 tf-15 trades open later and lose 197, 5 tf-15 trades not opened were worth
−128 (dodged), 5 tf-60 trades not opened were worth +258 and 2 tf-240 trades not opened +241 (the fast class said
"against" at zones that paid), and e7's 23 own positions net −346. The sum is −383: the EMA-7 removes a few good
higher-tf entries and adds a few bad 15-min ones. e14 sits between (its 13 own positions −196, its tf-60 re-labels +261).

The larger structure is the veto strength itself, visible in the sign / X = 1.0 / none rows: sign-only (every fire
needs the EMA slope's sign to agree) halves the trade count and loses 1.9–2.6 k (P 0.94–0.98); X = 1.0 and `none` add
36–50 trades and +0.8–1.1 k (P 0.12–0.18). On these 3.5 days (LINK 11.7–12.5, the 4-h EMA-25 sloping down 47 % of the
time so the 240 long flag is False half the time) the vetoed entries were, on balance, profitable mean-reversion
trades — tf 60 +587 → +1 656 without the flag.

## 6. The 2y / oos2m tier

The same question on the stored 1-min frames (2023-01 → 2024-12 and 2025-01 → 2025-03), with a stand-in flow:
candidates = `cb_inzone ∧ overshoot pass` (set C of the run-stats report), one entry per tf candle at the first
candidate minute whose flag passes (the once-per-zone rule), entry at the minute's close, the live candle stop
(forming-15m extreme ∓ mean range of the last 60 closed 1-min bars), target = `{tf}_cbnc_{far}` at the entry (exit *at*
the target price; the trend-flip exit is not reproducible without the trade feed), max hold 60 min, size
`min(100/dist, 50 000/entry)`, no fees. The 1-min trade-MA class does not exist there; a `mom` ablation requires the
last 1-min close change in the trade's direction (rule 1's spirit). Paired by candle (Δ = variant − e25, 2 000-sample
bootstrap CI90):

| tier | e25 n / net | e14 Δ (CI90, P<0) | e7 Δ | none Δ | c25 Δ |
|---|---|---|---|---|---|
| **2y, gate C** | 57 383 / +166 435 | −3 825 ([−19 820, +12 368], 0.66) | **−22 822 ([−47 079, +31], 0.95)** | **+71 644 ([+39 672, +105 641], 0.00)** | +22 442 ([+7 519, +36 750], 0.01) |
| **oos2m, gate C** | 4 414 / +15 827 | −1 854 ([−7 813, +4 102], 0.69) | **−10 512 ([−19 237, −1 853], 0.97)** | +10 602 ([−2 097, +23 365], 0.09) | +5 300 ([−184, +10 781], 0.06) |
| 2y, gate C + mom | 44 440 / −9 714 | +1 918 ([−9 399, +12 481], 0.39) | −14 119 ([−30 235, +1 769], 0.93) | +2 345 ([−18 274, +22 799], 0.42) | +9 406 ([−127, +19 404], 0.06) |
| oos2m, gate C + mom | 3 295 / −4 079 | −1 609 ([−5 439, +2 037], 0.76) | −3 894 ([−8 735, +1 202], 0.90) | −534 ([−7 786, +6 487], 0.54) | +1 125 ([−2 060, +4 095], 0.29) |

Per cell (2y, gate C): e7 loses on tf 15 both sides (−12.5 k / −12.3 k, P 0.94 / 0.95) and tf 60 long (−8.3 k, P 0.95),
gains on tf 60 short (+10.9 k, P 0.02); e14 is within noise in every cell (tf 15 short −7.6 k at P 0.93 the closest);
`none` gains in 4 of 6 cells (tf 15 both, tf 60 short at P ≤ 0.03). On oos2m e7 −9.7 k on tf 15 long (P 1.00), e14 −7.1 k
there (P 1.00) and +0.6…+1.4 k elsewhere. Flag pass rates at the candidate minutes: e25 0.64–0.76 (2y) / 0.52–0.72
(oos2m), e7 0.56–0.72 / 0.50–0.64, the closed classes 0.76–0.84 / 0.62–0.78.

Hold sensitivity (gate C, all cells, Δ vs e25 / CI90 / P<0): hold 30 — 2y e14 −3.0 k [−17.9 k, +11.8 k] 0.63, e7 −21.7 k [−43.4 k, −0.4 k] 0.95, none +73.6 k 0.00, c25 +23.2 k 0.01; oos2m e14 −2.6 k 0.78, e7 −11.9 k [−20.1 k, −3.6 k] 0.99, none +14.3 k 0.03, c25 +6.0 k 0.03. Hold 240 — 2y e14 −1.4 k 0.56, e7 −23.3 k 0.95, none +72.0 k 0.00, c25 +19.3 k 0.02; oos2m e14 −1.1 k 0.62, e7 −10.3 k [−19.2 k, −0.9 k] 0.96, none +10.6 k 0.09, c25 +5.7 k 0.05. The ranking does not move with the hold (`…-2y-oos2m-output-h30.txt`, `…-h240.txt`).

## 7. Verdict

**Negative for the question as asked.** Replacing the EMA-25 slope class by the EMA-14 changes the 84-h paper net by
+168 USDT (+3 783 → +3 951, CI90 [−825, +1 201]) and by −3.8 k / −1.9 k over 2y / oos2m (both inside noise); the EMA-7
changes it by −383 (P 0.67) and by **−22.8 k (P 0.95) / −10.5 k (P 0.97)** over 2y / oos2m — worse on every tier, worst
on the 15-min zones, where the fast class vetoes the bounce entries while the slope still points the other way.
A shorter EMA does not make the filter better; the length is not the lever.

What the sweep does show, as a side result, is that the veto's *strength* is: every weakening of the filter (X 0.5 →
1.0, or no flag at all) is better than live on the paper run (+0.8…+1.1 k, P 0.12–0.18) and on 2y (`none` +71.6 k, CI90
excludes zero) and oos2m (+10.6 k, P 0.09) under the set-C gate; under the mom gate the flag is a wash. The closed-candle
EMA-25 class (c25) beats the forming one on 2y (+22.4 k, P 0.01) and oos2m (+5.3 k, P 0.06) and is equal on the paper
run — the forming definition (the memory's "all tfs fire together on sharp moves") loses entries without buying
quality. Both are separate hypotheses, not the question asked; candidates for a follow-up: drop the trend flag, or
switch it to the closed-candle class.
