# Volume, 5-min buy−sell flow and book-depletion markers at the CB zone fire — paper-run alignment + entry-filter replay

Date: 2026-10-21. Question (user): align the volume, the 5-min buy/sell volume difference and the volume-depletion
markers with the position entries, look for a correlation, propose filters that stop the losing trades, measure the
profit impact.

Scripts: [`2026-10-21-volume-flow-replay.py`](2026-10-21-volume-flow-replay.py) (= the stop-re-entry harness + the
features + the `vol` skip gate; export SQL in its header), outputs
[`…-output-full.txt`](2026-10-21-volume-flow-replay-output-full.txt) (78.4 h, 15 six-hour blocks),
[`…-output-candle-era.txt`](2026-10-21-volume-flow-replay-output-candle-era.txt) (candle-stop era from 10-20 02:25,
5 blocks), [`…-output-union-full.txt`](2026-10-21-volume-flow-replay-output-union-full.txt) /
[`…-union-era.txt`](2026-10-21-volume-flow-replay-output-union-era.txt) (combined filters).
2y / oos2m stand-in: [`2026-10-21-volume-flow-2y-oos2m.py`](2026-10-21-volume-flow-2y-oos2m.py), output
[`…-2y-oos2m-output-h60.txt`](2026-10-21-volume-flow-2y-oos2m-output-h60.txt).
Status: **paper window: climax-volume and 60-min depletion-marker skips are a consistent-sign lead (+700…+900 on a
+2 679 base, P 0.06–0.20, both halves, 4/4 days); flow-direction filters dead; nothing reproduces on 2y / oos2m.**

## 0. Data, features, gates

Paper DB `cbov-check-postgres-1` (LINKUSDT): 832 623 trades with taker side + qty, 207 recorded `cb_zone_*` fires,
159 recorded positions (130 closed with pnl inside the window), `volume_book_depletion_{15,60,240}` rows
52 452 / 191 617 / 453 184 — one row per qualifying tick (duplicates per ts), active in 4 % / 17 % / 56 % of the
minutes. Replay window 10-18 11:41 → 10-21 18:04 (612 358 trades, feed gaps > 60 s: 5, the largest 2.6 h on 10-19).

Features at the fire tick (trailing, trades only): `vol{w}`, `net{w}` = Σbuy − Σsell (the executor's `net_qty`,
w = 5 is the live `avg_window`), `imb{w}` = net / vol, `adv{w}` = +imb for a long fire, −imb for a short fire
(> 0 = flow agrees with the trade), `rv{w}` = vol{w} / median w-min bucket volume over the trailing 2 h,
`dep{h}_on` = a depletion row within the last 60 s, `dep{h}_dir` = its direction vs the trade (+1 agree / −1 oppose),
`dep{h}_move` = |projected_move| / price in %, `dep{h}_dens` = rows in the last 5 min; `depany_*` across horizons.

Gates: reproduction — simulated live rule 202 fires vs 207 recorded, 200 matched (same side + tf within 60 s),
missed 7, extra 2; candle-stop port 54/55 recorded stops within half a tick. Fires vs 400 random ticks: adv5 median
−0.13 at fires vs +0.01 random (a fade fires with the flow against it, as designed), rv5 1.15 vs 1.23, dep rates equal.

## 1. Correlation at the fire (simulated live rule, 186 positions, net +2 679, stop-outs 47 %)

| feature | Spearman(x, pnl) (perm P) | Spearman(x, R) | AUC(x → stop-out) | worst quintile / level | best |
|---|---|---|---|---|---|
| rv5 (relative 5-min volume) | **−0.212 (0.00)** | −0.193 (0.01) | **0.597** | ≥ 2.27: n 37, stop 62 %, net −705 | < 0.79: 36 %, +1 764 |
| rv1 | −0.190 (0.01) | −0.187 (0.01) | 0.575 | ≥ 3.47: 59 %, −612 | 0.69–1.24: 33 %, +1 235 |
| vol5 (absolute) | −0.199 (0.01) | −0.168 (0.02) | 0.574 | ≥ 6 900: 55 %, −623 | < 1 940: 35 %, +1 973 |
| rv15 | −0.161 (0.03) | −0.171 (0.02) | 0.567 | ≥ 1.74: 59 %, −565 | 0.9–1.13: 35 %, +1 339 |
| adv1 (1-min flow with the trade) | +0.095 (0.20) | +0.193 (0.01) | 0.429 | < −0.35: 57 %, +264 | 0.35–0.67: 39 %, +1 076 |
| adv5 (= live net_qty, signed) | +0.047 (0.52) | +0.133 (0.07) | 0.425 | < −0.50: 62 %, −29 | −0.5…−0.25: 41 %, +945 |
| adv15 | +0.077 (0.29) | +0.136 (0.07) | 0.411 | < −0.34: 62 %, −233 | ≥ 0.24: 34 %, +1 077 |
| dep15_on | −0.082 (0.26) | −0.129 (0.08) | 0.521 | on: n 13, 62 %, −311 | off: 46 %, +2 991 |
| dep60_on | **−0.165 (0.02)** | −0.159 (0.03) | 0.558 | on: n 42, 60 %, −539 | off: 43 %, +3 218 |
| dep240_on | −0.118 (0.11) | −0.082 (0.27) | 0.558 | on: n 119, 51 %, +430 | off: 39 %, +2 249 |
| depany_move (largest projected move, %) | −0.153 (0.03) | −0.180 (0.01) | **0.599** | ≥ 8.7 %: 63 %, −716 | < 1.2 %: 39 %, +2 456 |
| dep{h}_dir (agree vs oppose) | +0.08…+0.12 (n.s.) | | 0.45–0.47 | oppose worse than off at every h; agree too thin (1 / 6 / 30) | |

Per cell: tf 15 short is the only cell where the flow direction matters (adv5 Spearman +0.26, P 0.02: lowest tercile
stop 58 % net −392, highest 31 % +1 405); tf 15 long none (−0.09); tf 60 long rv5 −0.75 on n 18 (top tercile 6/6
stopped). Recorded positions (130, net +919, stop 58 %): same directions, weaker — adv5 +0.09 (P 0.27), rv5 −0.09
(P 0.30), dep15_on −0.18 (P 0.05, 10 on: 70 % stop, −220), depany_move −0.18 (P 0.04, top quartile 69 % stop, −431),
adv15 lowest quintile 85 % stop −554.

Reading: volume *level* (climax) and the 60-min depletion marker carry the strongest in-sample relation (|ρ| ≈ 0.2,
AUC ≈ 0.6); flow *direction* is weak overall (|ρ| ≤ 0.1) with the sign "flow already with the trade = fewer
stop-outs"; a marker in the trade's direction is almost never on at a fire.

## 2. Filters replayed (Δ vs live, paired 6-h block bootstrap; full 78.4 h / candle era 30 h)

| variant (skip the fire when …) | skipped | full n / net | Δ full (P(Δ<0)) | era n / net | Δ era (P) | split-half Δ first / second | days + |
|---|---|---|---|---|---|---|---|
| live | — | 186 / +2 679 | — | 53 / +411 | — | — | — |
| rv5 > 3 | 26 | 160 / +3 443 | **+763 (0.06)** | 43 / +822 | +411 (0.01) | +315 / +448 | 4/4 |
| rv5 > 2 | 41 | 145 / +3 412 | +733 (0.20) | 36 / +817 | +406 (0.02) | +601 / +132 | |
| rv5 > 1.5 | 53 | 133 / +3 531 | +852 (0.22) | | +398 (0.16) | +628 / +223 | |
| rv15 > 3 | 15 | 171 / +3 379 | **+699 (0.00)** | 47 / +612 | +201 (0.05) | +293 / +406 | 4/4 |
| rv1 > 3 | 44 | 143 / +3 427 | +747 (0.17) | 37 / +806 | +394 (0.00) | +481 / +266 | 4/4 |
| rv5 < 0.7 (dead tape) | 27 | 160 / +315 | **−2 365 (1.00)** | 49 / +355 | −56 | | |
| rv1 < 0.7 | | | −2 397 (1.00) | | −371 | | |
| dep60_on | 43 | 145 / +3 560 | **+881 (0.07)** | 33 / +920 | +509 (0.13) | +277 / +604 | 3/4 |
| dep60_oppose | 37 | 151 / +3 511 | +831 (0.07) | 35 / +833 | +422 (0.12) | | |
| dep15_on | 13 | 173 / +3 025 | +346 (0.12) | 45 / +670 | +259 (0.07) | | 3/4 |
| dep240_on | 67 | | −582 (0.68) | | +108 | | |
| depany_on | 127 | | −200 (0.54) | | +139 | | |
| depany_move > 10 % | | | +649 (0.11) | | +409 (0.06) | | |
| adv5 < −0.2 (flow against) | 85 | 105 / +2 248 | −431 (0.62) | | +513 (0.19) | +152 / −583 | |
| adv5 < −0.5 | | | +308 (0.29) | | +345 (0.13) | +150 / +158 | |
| adv15 < −0.5 | 21 | 168 / +3 629 | +950 (0.00) | 39 / +1 236 | +825 (0.00) | +71 / +879 | 4/4 |
| adv5 > 0.1 (flow already with) | 62 | 132 / +1 175 | −1 505 (0.97) | 44 / +49 | −362 (0.93) | | |
| adv1 > 0.5 / adv15 > 0.1 | | | −2 295 / −1 509 (0.99 / 0.98) | | | | |
| random skip 10 % / 20 % (8 seeds) | | | mean −258 (−939…+176) / −479 (−1 195…0) | | | | |
| sh24 placebo rv5 > 1.5 / dep60_on / adv5 > 0.2 | | | −142 / −131 / +341 | | +193 / −37 / +596 | +718 / −378 (adv) | |

Split-half honesty: 32 variants are positive on the first half, 16 of them (50 %) stay positive on the second; the
variant with the best first half is the shifted placebo `sh24_adv5_gt0.2` (+718 → −378). The relative-volume family
(rv1/5/15 > 2–3) and `dep60_on` are the only ones positive in both halves, every day and in the era, and they beat
the random-skip band (−1 195…+176 at 20 %) and their own shifted controls. Per cell the gain is spread: rv5 > 3
lifts tf 15 short +1 388 → +1 596, tf 60 long −403 → −30, tf 60 short +451 → +589. Fee sensitivity unchanged
(−0.1 %/side still ≈ −10 000 … −14 500 for every variant — the fee problem dwarfs any filter).

Combined filters (`rv5 > 3 | dep60_on` etc.): see §2b.

## 2b. Combined filters

| union (skip when any holds) | skipped (of 202 fires) | full n / net | Δ full (P(Δ<0)) | era n | Δ era (P) |
|---|---|---|---|---|---|
| rv5 > 3 \| dep60_on | 47 | 141 / +3 619 | +940 (0.07) | 32 | +562 (0.08) |
| rv15 > 3 \| dep60_on | 47 | 141 / +3 655 | +976 (0.06) | 32 | +570 (0.08) |
| rv5 > 3 \| dep15_on | 30 | 156 / +3 447 | +768 (0.07) | 41 | +502 (0.00) |
| rv5 > 2 \| rv15 > 3 | 46 | 140 / +3 582 | +903 (0.16) | 34 | +540 (0.00) |
| rv5 > 3 \| rv15 > 3 \| dep60_on | 51 | 137 / +3 715 | +1 036 (0.06) | 31 | +623 (0.06) |
| sh24 rv5 > 1.5 / sh24 dep60_on (controls) | | | −142 / −131 | | +193 / −37 |

The unions add +100…+270 over the best single filter while skipping a quarter of the fires — the two families
overlap (climax volume and a 60-min marker fire together) rather than stack. Nothing above the single `dep60_on`
in P terms.

## 3. 2y / oos2m stand-in (flow features only — the book markers have no history)

Tier-B flow = the bounds-geometry stand-in (candidate = in-zone & overshoot pass, first passing minute per tf
candle, entry = 1-min close, candle stop, cbnc target, hold ≤ 60, e25 forming-EMA flag as the baseline). Flow from
the frame's `volume` / `taker_base_vol` (Binance klines): net = 2·taker − volume over the last w closed minutes;
rv = vol / rolling-120 median. Baseline e25: 2y 57 383 entries +166 435; oos2m 4 414 entries +15 827.

Correlation at the entry minute (tf 15, 2y, n ≈ 22 000 per side): Spearman(adv5, pnl) −0.05 / −0.06, AUC(adv → stop)
0.47; Spearman(rv5, pnl) −0.005 / −0.004, AUC 0.49; w 1 / 15 the same; oos2m |ρ| ≤ 0.03. The paper window's
|ρ| ≈ 0.2 for rv does not exist here.

Selection on 2y (tf 15 cells, retention ≥ 60 %) and the oos2m score with the frozen values:

| family | frozen on 2y | Δ 2y vs e25 (P(Δ<0), months +) | shifted placebo 2y | Δ oos2m (P) |
|---|---|---|---|---|
| veto flow against the trade (adv < −x) | adv15 < −0.5 (2 % of entries) | −1 315 (0.62, 11/24); every other x / w −16 309 … −79 738 (P ≥ 0.99, 2–8/24) | −2 769 | −94 (0.51) |
| veto flow already with the trade (adv > x) | adv1 > 0.2 | +12 390 (0.11, 13/24) [tf 15 only +15 754, P 0.02] | — | **−3 354 (0.85)** |
| veto climax volume (rv > k) | rv1 > 3 | +9 150 (0.25, 13/24); rv > 1.5 / 2 at any w −8 399 … −32 825 (P 0.86–1.00) | −16 389 | **−3 417 (0.81)**; every rv > k on oos2m −3 417 … −7 970 |
| veto dead tape (rv < k) | rv5 < 0.5 | +1 759 (0.41, 14/24); rv < 0.7 −17 533 … −22 899 | — | −3 457 (0.92) |
| adv5 < −0.2 & rv5 > 1.5 / adv5 < −0.2 \| rv5 > 2 | — | −26 355 / −66 894 (0.99 / 1.00) | | −5 513 / −10 468 |

Nothing survives: the climax and with-flow vetoes that are mildly positive on 2y flip on oos2m, the against-flow
vetoes lose heavily on both (the entries taken against the strongest inflow are the best cells on 2y: tf 15 short
adv5 < −0.5 PF 1.18 mean +6.2 vs +3.7 all — the same adverse-selection pattern the CCI experiment found).

## 4. Conclusion

- Alignment / correlation: on the paper run the fires taken on climax volume (rv5 ≥ 2.3, top quintile) and under
  an active 60-min depletion marker stop out 60–62 % vs 36–43 % and lose (−705 / −539 on a +2 679 total); the flow
  direction is weak (|ρ| ≤ 0.1), only tf 15 short shows "flow already short = better" (+0.26). The recorded
  positions show the same signs, weaker.
- Filters: `rv5 > 3` (skips 14 %, +763, P 0.06), `rv15 > 3` (8 %, +699, P 0.00), `dep60_on` (23 %, +881, P 0.07)
  are the candidates — positive on both halves, 4/4 or 3/4 days, above the placebo band. Everything built on the
  flow direction is noise or negative; skipping low-volume fires is strongly negative (they are the best).
- Not actionable yet: the 2y / oos2m stand-in shows zero correlation and the climax vetoes lose on oos2m; the paper
  effect rests on 15–43 skipped fires in 78 h. Next arbiter: keep `rv5 > 3` and `dep60_on` as *observation-only*
  decision-log fields in the executor for two weeks of paper, then re-score; or export Binance aggTrades for the
  2y span to recompute the executor's exact trailing features (the frame's klines taker volume is a different feed).
