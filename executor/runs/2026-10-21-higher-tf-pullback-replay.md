# Replay: a higher tf's PULL-BACK state vetoing the lower tf's in-trend CB zone entries

Date: 2026-10-21. Question (user): "when the higher tf shows signals to reverse from the trend (or goes too deep)
and moves backward into range, discard the in-trend-direction zones on the lower timeframes — the higher-tf move
will win."

Sibling of [higher-tf-trend-replay](2026-10-21-higher-tf-trend-replay.md) (same exports, same harness imported as a
module: `trade` 748 276 rows 10-16 22:29Z → 10-21 10:07Z, `indicators`, `signal_log` 188 CbZoneEntry rows, Binance
klines; window **10-17 22:00Z → 10-21 10:07Z (84 h)**; fires re-derived on every trade, 1-min class X 0.7, candle
stop, cbnc target + trend-flip exit, reversal, paper = no fees). That replay vetoed on the higher tf's *standing*
slope class (trend against the trade); this one vetoes on a *transition* — trend **with** the trade that is reversing
now — so the two veto sets are disjoint by construction (Jaccard static-vs-cf0 = 0.000, static-vs-xd 0.17 / 0.24).
Scripts: [`…-pullback-replay.py`](2026-10-21-higher-tf-pullback-replay.py) → [`…-replay-output.txt`](2026-10-21-higher-tf-pullback-replay-output.txt);
[`…-pullback-2y-oos2m.py`](2026-10-21-higher-tf-pullback-2y-oos2m.py) → [`…-2y-oos2m-output-h60.txt`](2026-10-21-higher-tf-pullback-2y-oos2m-output-h60.txt).
Status: **answered — negative on every tier; see §6.**

## 1. Pull-back states (PB_long of the higher tf H; short mirrored), ANDed as a veto into the own e25 flag

| key | PB_long on H | source |
|---|---|---|
| **xd** | H's forming candle **high is done**: `(H_high − price)/ATR1 ≥ d(progress)` (frozen `EXTDONE_LADDER`) — up-run reversed, price pulled away | stored `{H}_extdone_high` (= NOT `{H}_cb_f_extdone_long`, agreement 1.0000); tier B: kernel port |
| **cf0** / cf− | last **closed** H EMA-25 class +1 and forming class ≤ 0 / −1 ("signal to reverse") | reconstructed classes (gated 99 % in the sibling) |
| **ovc** / ov30 | H's upper-bound overshoot flag fired earlier in the same H candle / last 30 min, and passes now ("too deep, back into range") | stored `{H}_cb_f_overshoot_short` history |
| any / xdcf | xd ∨ cf0 ∨ ovc / xd ∧ cf0 | |
| mir | `{H}_extdone_low` (opposite sign: veto long when H's LOW is done) | control |
| sh+ / sh− | the xd state read 24 h earlier / later | pass-rate-matched placebo |

Pairs 15<60, 15<240, 60<240, ladder (15: 60 ∧ 240; 60: 240). State rates on the window's trades: xd 0.20 / 0.23 (H 15),
0.14 / 0.19 (60), 0.15 / 0.13 (240); cf0 0.05 / 0.03, 0.08 / 0.05, 0.00 / 0.03; ovc 0.16 / 0.13, 0.12 / 0.09, 0.13 / 0.10;
any 0.34, 0.28, 0.25. **cf− never occurs** (a closed +1 cannot become a forming −1 inside one candle at X 0.5) — those
rows equal e25.

## 2. Gates

| gate | number |
|---|---|
| fires reproduced (live flags) | 177 / 188 recorded, 4 within ±120 s, 7 unmatched (restarts) — identical to the sibling |
| stored state | present at 97.9 % of trades; `cb_f_extdone_long == !extdone_high` 1.0000 on every tf |
| kernel port (tier B) vs the stored stream | extdone high / low means 2y 0.230 / 0.243 (15), 0.147 / 0.188 (60), 0.127 / 0.140 (240) vs stored 84 h 0.207 / 0.234, 0.145 / 0.189, 0.153 / 0.133 — within ±0.03 |
| provenance | `EXTDONE_LADDER`, `OVERSHOOT_THR`, `EMA_SLOPE_STATS` = the live frozen 2y values; nothing fitted on the window or on oos2m |
| placebo | sh+ / sh− carry the same pass rate as xd |

## 3. Paper replay, 84 h, no fees (paired Δ vs e25 = +3 783 / 212 positions / PF 1.48)

| variant | n | net | PF | Δ vs e25 (CI90, P(Δ<0)) | variant | n | net | PF | Δ vs e25 |
|---|---|---|---|---|---|---|---|---|---|
| xd15<60 | 186 | +3 507 | 1.52 | −276 ([−1 251, +632], 0.69) | ovc15<60 | 193 | +3 473 | 1.48 | −310 (0.69) |
| xd15<240 | 193 | +2 838 | 1.39 | −945 ([−1 984, +37], 0.94) | ovc15<240 | 193 | +3 149 | 1.44 | −634 (0.81) |
| xd60<240 | 207 | +3 712 | 1.49 | −71 (0.56) | ovc60<240 | 211 | +3 758 | 1.48 | −25 (0.54) |
| xdladder | 167 | +2 658 | 1.44 | −1 125 ([−2 625, +391], 0.89) | ovcladder | 173 | +2 966 | 1.46 | −817 (0.84) |
| cf015<60 | 204 | +3 961 | 1.53 | **+178** ([−448, +795], 0.30) | ov3015<60 | 191 | +3 272 | 1.46 | −511 (0.74) |
| cf015<240 | 212 | +3 624 | 1.45 | −159 (0.99) | ov3060<240 | 211 | +3 846 | 1.49 | +63 (0.24) |
| cf060<240 | 212 | +3 783 | 1.48 | 0 (no 60-min fire in a 240 cf0 state) | any15<60 | 167 | +3 486 | 1.58 | −297 (0.62) |
| cf0ladder | 204 | +3 802 | 1.50 | +19 (0.47) | any15<240 | 177 | +2 368 | 1.35 | −1 415 ([−2 839, −73], 0.96) |
| xdcf15<60 | 209 | +3 831 | 1.50 | +48 (0.37) | anyladder | 136 | +2 028 | 1.40 | −1 755 ([−3 652, +159], 0.94) |
| mir15<60 | 199 | +3 447 | 1.46 | −336 (0.76) | mirladder | 176 | +2 647 | 1.39 | −1 136 (0.95) |
| sh+15<60 | 190 | +3 220 | 1.45 | −563 (0.87) | **sh−15<60** (placebo) | 198 | **+4 695** | 1.67 | **+912** ([+207, +1 668], 0.01) |
| sh+ladder | 175 | +2 822 | 1.43 | −961 (0.89) | sh−ladder (placebo) | 189 | +4 362 | 1.64 | +579 (0.22) |

References: live +3 732, none +4 751 (+968, P 0.16), hx15<60 +2 731 (−1 051, P 0.93). The best variant of the whole
table is the **shifted-state placebo** (+912, P 0.01): the 84 h noise floor is wider than any real effect. Fee
breakeven 0.019–0.025 %/side for all.

## 4. Mechanism on the paper window — e25 positions split by the higher tf's state at the open

| opening tf | H | state on | n | net | PF | stop | mean | state off | n | net | PF | stop | mean |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 | 60 | xd | 29 | +320 | 1.28 | 52 % | +11 | | 132 | +1 775 | 1.37 | 47 % | +13 |
| 15 | 60 | cf0 | 14 | −92 | 0.85 | 57 % | −7 | | 147 | +2 187 | 1.41 | 47 % | +15 |
| 15 | 60 | ovc | 22 | +1 | 1.00 | 59 % | 0 | | 139 | +2 094 | 1.42 | 46 % | +15 |
| 15 | 60 | **any** | 57 | +115 | 1.05 | 56 % | +2 | | 104 | +1 980 | 1.56 | 43 % | +19 |
| 15 | 240 | xd | 22 | **+1 050** | **2.80** | 36 % | +48 | | 139 | +1 045 | 1.19 | 50 % | +8 |
| 15 | 240 | any | 40 | +1 071 | 1.77 | 42 % | +27 | | 121 | +1 024 | 1.22 | 50 % | +8 |
| 60 | 240 | xd | 9 | +241 | 1.60 | 56 % | +27 | | 31 | +346 | 1.30 | 45 % | +11 |
| 60 | 240 | any | 12 | +505 | 2.25 | 42 % | +42 | | 28 | +82 | 1.07 | 50 % | +3 |

Against the 60-min pull-back the 15-min cell is weaker (PF 1.05, stop 56 %) but still net **positive** (+115), so the
veto loses it and the flow re-fires elsewhere (any15<60: 70 fires lost, 11 new, Δ −297). Against the **240-min**
pull-back the 15-min and 60-min entries are the **better** cell (PF 2.80 / 2.25) — the opposite of the hypothesis,
the same picture as the sibling's "counter-trend entries are the better ones". The 14 cf015<60 positions (the only
net-negative cell, −92) are 10 Buys in a 60-min class that just left +1; vetoing them gives +178 on 84 h, below the
placebo.

## 5. 2y / oos2m stand-in (hold 60; set-C candidates, first passing minute per candle, candle stop, cbnc target)

e25: 2y 57 383 entries net +166 435 (PF 1.05–1.09 per tf 15 / 60); oos2m 4 414 entries +15 827. Paired Δ vs e25 by
candle, all tf+side (CI90, P(Δ<0)); months with Δ > 0 (2y of 24, oos2m of 2):

| variant | 2y Δ | P | m+ | oos2m Δ | P | m+ | variant | 2y Δ | P | m+ | oos2m Δ | P | m+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| xd15<60 | −28 562 [−44 844, −12 661] | 1.00 | 6 | −4 639 [−9 034, −288] | 0.96 | 0 | ovc15<60 | −18 407 | 0.99 | 8 | −3 563 | 0.92 | 0 |
| xd15<240 | −23 825 | 1.00 | 4 | −2 838 | 0.92 | 0 | ovc15<240 | −15 478 | 0.98 | 10 | −5 560 | 0.99 | 0 |
| xd60<240 | +990 [−8 618, +9 932] | 0.43 | 11 | +2 097 [−388, +4 401] | 0.08 | 2 | ovc60<240 | −3 136 | 0.75 | 11 | −1 068 | 0.76 | 0 |
| xdladder | −43 424 | 1.00 | 6 | −4 028 | 0.88 | 0 | ovcladder | −31 487 | 1.00 | 6 | −8 944 | 0.99 | 0 |
| cf015<60 | −8 702 [−18 364, +752] | 0.94 | 11 | −961 | 0.69 | 0 | ov3015<60 | −25 932 | 0.99 | 6 | −7 866 | 0.97 | 0 |
| cf015<240 | −8 936 | 0.99 | 8 | +108 | 0.44 | 1 | ov3060<240 | −8 729 | 0.96 | 5 | −1 555 | 0.79 | 1 |
| cf060<240 | +3 860 [−1 399, +9 248] | 0.12 | 16 | −2 068 [−4 157, −72] | 0.96 | 0 | any15<60 | −49 832 | 1.00 | 5 | −7 806 | 0.98 | 0 |
| cf0ladder | −12 549 | 0.95 | 8 | −2 786 | 0.89 | 0 | anyladder | −79 598 | 1.00 | 3 | −11 455 | 0.99 | 0 |
| xdcf15<60 | −2 314 | 0.76 | 11 | −1 186 | 0.85 | 0 | any60<240 | +1 364 | 0.41 | 12 | −593 | 0.61 | 0 |
| mir15<60 | −28 887 | 1.00 | 4 | +84 | 0.47 | 2 | sh+15<60 (placebo) | −24 759 | 1.00 | 8 | −483 | 0.60 | 1 |
| mir60<240 | −12 854 | 1.00 | 9 | −697 | 0.70 | 1 | sh+60<240 (placebo) | +1 024 | 0.43 | 14 | +1 483 | 0.15 | 2 |
| hx15<60 (sibling) | −3 998 | 0.69 | 13 | +2 695 | 0.15 | 2 | none | +71 644 | 0.00 | 18 | +10 602 | 0.09 | 2 |

Every 15-min variant is negative on both tiers with P ≥ 0.92; **the placebo sh+15<60 loses as much as xd15<60 on 2y**
(−24 759 vs −28 562): the veto removes entries of average quality from a flow whose every entry is worth +2…+4 on
average, so any removal costs. The e25 entries split by the state at the entry minute (2y, tf 15 long by H 60): xd on
PF 1.05 mean +2.05 vs off 1.05 / +2.16; cf0 on 1.00 / −0.01 (n 1 323) vs 1.05 / +2.28; ovc on 1.05 / +2.67 vs +2.09;
any on 1.03 / +1.55 vs 1.05 / +2.38 — differences of one or two USDT per trade, and the short side goes the other way
(xd on 1.07 / +2.96 vs 1.09 / +3.97, cf0 on **1.14 / +6.26** vs 1.08, ovc on 1.14 / +7.18 vs 1.08). By H 240 the state-on
cell is better on both sides (xd long 1.11 / +4.25 vs 1.04 / +1.88; short 1.12 vs 1.08; any short 1.17 / +7.16 vs
1.07 / +2.82). oos2m flips the 15←60 cells again (xd on long PF 1.27 / +12.8 vs 1.04; cf0 on 0.95; ovc on 0.90 long but
**1.52 / +25.8 short**).

The one place with the hypothesis's sign on 2y is **tf 60 ← 240**: long entries with the 240 state on PF 0.94 / −3.55
(n 1 359, any) vs 1.09 / +4.65 off, cf0 on 0.80 / −11.8 (n 300); shorts flat (1.05 vs 1.09). It yields xd60<240 +990
(P 0.43) / cf060<240 +3 860 (P 0.12) on 2y and xd60<240 +2 097 (P 0.08) / cf060<240 **−2 068 (P 0.96)** on oos2m, where
the cf0-on cells turn PF 1.45 / 2.00 (n 22 / 25). Not decision-grade on either tier, and it touches 9 of 238 fires in
84 h (xd60<240 −71 on paper).

Side finding, not the question: the **mirror** cell — a lower-tf entry *against* the higher tf's done extreme (long
when H's low is done) — is the best cell on 2y everywhere (tf 15 by 60: long PF 1.17 / +7.4, short 1.34 / +13.5; tf 60
by 240 long 1.45 / +22.9), and mixed on oos2m (tf 15 by 60 long 1.12, short 0.87; by 240 1.21 / 1.31). That is a
positive filter candidate ("fade the higher-tf done extreme"), the same direction as the sibling's mechanism.

## 6. Verdict

**Negative.** A higher-tf pull-back state (extreme done, slope class leaving the trend, overshoot retreat, or any of
them) vetoing the lower tf's in-trend entries does not raise the net on the 84 h paper window (best real variant
+178, the placebo +912), and loses on 2y (−8 702 … −79 598, P 0.94–1.00) and on oos2m (−961 … −11 455) for every
15-min pair. The entries the rule would discard are of average quality (2y) or better (H 240, oos2m 15←60 long):
the higher-tf pull-back does not "win" against a 15-min zone at the same time. The only consistent-sign cell is
60-min longs during a 240-min pull-back (2y PF 0.94 vs 1.09), too thin and oos2m-contradicted (cf0) to act on. No
toggle. Candidate for a later question: the mirror as a positive filter.
