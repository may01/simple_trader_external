# Replay: stop-out followed by a same-side re-entry from a better price

Date: 2026-10-21. Question (user): in live (paper) trading two CB zone trades often come close together — the first is
stopped out at the start of the zone, the second opens a few minutes later from a better price. How often does this
happen, what does it cost, and what would fix it (up to five proposals)?

Data: `cbov-check` paper stack (Binance LINKUSDT, paper balance 100 000, `RISK_PER_TRADE=100`,
`MAX_NOTIONAL_FRACTION=0.5`, `CB_STOP_MODE=candle` since 10-20 20:25Z, book stop before), read from its tables:
`trade` (753 117 rows, 10-16 22:29Z → 10-21 11:16Z), `indicators` (42 CB names, 470 989 readings with expiry),
`signal_log` CbZoneEntry rows (191), `position_log` (1 727 rows → 144 CB positions, 114 closed with a pnl, 30 lost
to executor restarts). Window = whole CB-armed history **10-18 11:41Z → 10-21 11:16Z (71.6 h, 532 852 trades)** and the
candle-stop era **10-20 20:25Z → 10-21 11:16Z (14.9 h)**. Exports archived at
`simple_trader_vol_long:/train/replays/stop-reentry-replay-data-2026-10-21.tgz`.

Scripts: [`2026-10-21-stop-reentry-recorded-pairs.py`](2026-10-21-stop-reentry-recorded-pairs.py) (recorded positions
only, output [`…-recorded-pairs-output.txt`](2026-10-21-stop-reentry-recorded-pairs-output.txt)) and
[`2026-10-21-stop-reentry-replay.py`](2026-10-21-stop-reentry-replay.py) (fire-re-deriving replay = the
`2026-10-21-rule2-removal-replay.py` harness, cb-candle-stop @ `a6a5bc6` port, plus per-variant knobs and a pair
detector). Outputs: [`…-output-full.txt`](2026-10-21-stop-reentry-replay-output-full.txt),
[`…-output-candle-era.txt`](2026-10-21-stop-reentry-replay-output-candle-era.txt),
[`…-output-sm-sweep.txt`](2026-10-21-stop-reentry-replay-output-sm-sweep.txt),
[`…-output-zone-stop-full.txt`](2026-10-21-stop-reentry-replay-output-zone-stop-full.txt),
[`…-output-zone-stop-era.txt`](2026-10-21-stop-reentry-replay-output-zone-stop-era.txt) (with per-trade tables).
Status: **answered — the pattern is the dominant loss channel (43 % of all stop-loss money); only a wider stop
(offset × 2–2.5) moves it in the right direction on both windows; cooldown, deeper entry, half size, candle-skip and
anchor changes are dead or no-ops.**

## 1. Definition

Pair = consecutive positions P1 → P2 with P1 closed by `stop`, P2 the same side, opened ≤ W min after P1's close, P2's
entry better than P1's entry (long: lower; short: higher). Windows W = 5 / 15 / 30 / 60 min; W = 15 is the headline.

## 2. How often, what it costs

Recorded paper positions (both stop eras, 114 closed, 71 stop-outs, net +650):

| W | pairs | of stop-outs | P1 loss | P2 pnl | pair net | P2 outcomes |
|---|---|---|---|---|---|---|
| 5 | 6 | 8 % | −274 | +153 | −120 | stop 3, target 2, main_close 1 |
| 15 | 13 | 18 % | −352 | +487 | +135 | stop 7, main_close 4, target 2 |
| 30 | 17 | 24 % | −508 | +537 | +29 | stop 10, main_close 5, target 2 |
| 60 | 19 | 27 % | −549 | +504 | −45 | stop 12, main_close 5, target 2 |

Candle-stop era only (recorded, 38 closed, 22 stop-outs, net +169): W 15 → 4 pairs (18 %), P1 −273, P2 +312; W 60 → 6
(27 %), P1 −403, P2 +243. P2 entry is a median 0.8–1.2 P1-stop-distances better; 0/19 pairs share P1's zone value.

Simulated live rule, uniform candle stop over the whole 71.6 h (171 positions, 82 stop-outs = −6 560, net +2 503):

| W | pairs | of stop-outs | P1 loss | P2 pnl | P2 outcomes | gap median | P2 beyond P1 stop | Δentry / P1 stop-dist |
|---|---|---|---|---|---|---|---|---|
| 5 | 28 | 34 % | −2 293 | +311 | stop 13, reversal 7, target 7 | 1.6 min | 17/28 | 1.06 |
| 15 | 35 | 43 % | −2 795 | +226 | stop 17, reversal 9, target 8 | 1.9 min | 23/35 | 1.19 |
| 30 | 45 | 55 % | −3 572 | +544 | stop 22, reversal 12, target 10 | 2.4 min | 31/45 | 1.35 |
| 60 | 49 | 60 % | −3 966 | +606 | stop 24, reversal 12, target 12 | 3.0 min | 33/49 | 1.35 |

So under the running stop rule roughly **every second stop-out is the first leg of such a pair**, the P1 legs carry
**43 % of all stop-loss money** (−2 795 of −6 560 at W 15), and the P2 legs only recover +226 because half of them are
stopped again (17/35). P1 is tf 15 in 30/35 pairs; P2 is a different tf in 18/35 (60: 16, 240: 2) and rule 2 in 13/35.
"P1 held to P2's exit" at P1's size is worse than the actual P1 (recorded: −1 067 vs −352 at W 15; candle era −77 vs
−273), i.e. the P1 would mostly have been stopped at P2's level too — this is not a "stop too tight by a tick" story.

## 3. Mechanism

- The fire lands on a fresh extreme (price entering the zone). The candle stop anchors on the forming 15-min
  extreme, which at that moment *is* the price: anchor distance 0.2–1.3 mean 1-min ranges, stop distance a median
  1.8–2.1 ranges (`anchor_dist/offset` table in the recorded-pairs output). In 41/42 candle-era fires the rolling
  15-min extreme equals the forming-candle extreme — any "anchor further back" variant is a no-op by construction.
- The zone keeps moving: `{tf}_cb_zone_*` is rebroadcast every minute (forming-candle bounds), so the once-per-(tf,
  side, zone) rule never blocks the second fire (0/19 recorded pairs share the zone value). P2 comes from the next
  zone value by rule 2, or from the 60/240 zone of the same side.
- Entry-side room is larger than the stop: median room from the fire price to the entry-side `cbnc` bound is 0.027
  (tf 15), 0.054 (tf 60), 0.108 (tf 240) vs a stop distance of ~0.015–0.025. The zone is 2–4 stops deep.
- Positions in the first 3 minutes of a 15-min candle stop out 62 % (n 8) vs 40 % after minute 7 (n 10), median
  stop/offset 1.76 vs 2.13 — small n, direction consistent with the anchor story.

## 4. Variants (same simulator, everything else identical)

| knob | variants | what it changes |
|---|---|---|
| cooldown | cd5 / cd15 / cd30 | same-side fires N min after a stop-out are rejected at the decision layer |
| stop_mult | sm15 / sm20 / sm25 / sm30 | candle-stop offset (trailing-60 mean 1-min range) × k |
| anchor | anc2 (previous closed 15-min candle + forming) / roll15 (last 15 closed 1-min bars + forming) | stop anchor window |
| depth | dp05 / dp10 | a candidate needs the price d × offset beyond the zone line |
| skip_min | skip3 / skip5 | no fire in the first K minutes of a 15-min candle (deferred) |
| half_first | half | first entry after flat × 0.5 size; a same-side re-entry within 60 min of a stop-out is full size |
| zone_stop | zs (entry-side `cbnc` bound ∓ offset) / zsw (wider of that and the candle stop) / zsw15 (zsw with offset × 1.5) | stop level |

## 5. Results — full window 71.6 h (171 live positions)

| variant | trades | net | net −0.1 %/side fee | PF | win rate | stop-outs / mean | pairs W15 (of stops) | P1 loss | P2 pnl | Δ vs live (paired 6-h blocks, 13) | 90 % CI | P(Δ<0) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| live | 171 | +2 503 | −13 522 | 1.38 | 51 % | 82 / −80 | 35 (43 %) | −2 795 | +226 | — | — | — |
| cd5 | 147 | +2 581 | −11 208 | 1.47 | 52 % | 69 / −79 | 9 (13 %) | −697 | +285 | +78 | [−645, +812] | 0.43 |
| cd15 | 139 | +2 426 | −10 688 | 1.46 | 52 % | 66 / −79 | 0 | 0 | 0 | −77 | [−1 117, +924] | 0.56 |
| cd30 | 127 | +1 766 | −10 138 | 1.37 | 52 % | 60 / −79 | 0 | 0 | 0 | −737 | [−2 189, +571] | 0.81 |
| sm15 | 166 | +3 051 | −11 443 | 1.51 | 59 % | 66 / −91 | 33 (50 %) | −3 022 | +591 | +548 | [−720, +1 955] | 0.26 |
| sm20 | 160 | +3 108 | −9 488 | 1.58 | 64 % | 54 / −98 | 30 (56 %) | −2 961 | +307 | +605 | [−582, +1 799] | 0.21 |
| sm25 | 155 | +3 139 | −7 619 | 1.71 | 69 % | 43 / −101 | 25 (58 %) | −2 538 | +565 | +636 | [−228, +1 518] | 0.11 |
| sm30 | 150 | +2 340 | −6 803 | 1.56 | 70 % | 40 / −101 | 23 (57 %) | −2 338 | +485 | −163 | [−1 125, +752] | 0.61 |
| anc2 | 167 | +2 326 | −12 565 | 1.37 | 53 % | 75 / −82 | 31 (41 %) | −2 448 | +372 | −177 | [−702, +396] | 0.72 |
| roll15 | 169 | +2 918 | −12 752 | 1.47 | 53 % | 77 / −81 | 33 (43 %) | −2 601 | +617 | +415 | [−41, +945] | 0.07 |
| dp05 | 71 | +2 169 | −4 467 | 1.92 | 54 % | 31 / −73 | 8 (26 %) | −607 | −167 | −334 | [−2 376, +1 680] | 0.59 |
| dp10 | 41 | +684 | −3 058 | 1.39 | 49 % | 21 / −83 | 4 (19 %) | −326 | −184 | −1 819 | [−4 142, +447] | 0.90 |
| skip3 | 164 | +1 889 | −13 235 | 1.30 | 51 % | 76 / −83 | 34 (45 %) | −2 778 | +231 | −614 | [−1 650, +285] | 0.85 |
| skip5 | 152 | +2 486 | −11 348 | 1.45 | 55 % | 65 / −84 | 30 (46 %) | −2 514 | +70 | −17 | [−1 535, +1 288] | 0.47 |
| half | 171 | +1 567 | −9 529 | 1.33 | 51 % | 82 / −57 | 35 (43 %) | −1 963 | +222 | −936 | [−1 623, −244] | 0.99 |
| zs | 149 | +2 654 | −6 578 | 1.71 | 67 % | 38 / −93 | 20 (53 %) | −1 840 | −320 | +151 | [−1 516, +1 675] | 0.45 |
| zsw | 149 | +2 709 | −6 513 | 1.73 | 68 % | 37 / −95 | 20 (54 %) | −1 894 | −366 | +206 | [−1 300, +1 690] | 0.42 |
| zsw15 | 147 | +2 451 | −5 720 | 1.71 | 71 % | 33 / −99 | 19 (58 %) | −1 907 | +18 | −52 | [−1 407, +1 300] | 0.53 |

Per day (live / sm20 / sm25): 10-18 +542 / +773 / +764; 10-19 +330 / +864 / +943; 10-20 +1 684 / +1 209 / +1 292;
10-21 −53 / +262 / +140 — the wider stop gives on the big day and takes on the other three.

## 6. Results — candle-stop era 14.9 h (38 live positions, 3 blocks)

| variant | trades | net | PF | stop-outs / mean | pairs W15 | P1 | P2 | Δ vs live | 90 % CI | P(Δ<0) |
|---|---|---|---|---|---|---|---|---|---|---|
| live | 38 | +237 | 1.17 | 21 / −68 | 8 (38 %) | −526 | +474 | — | — | — |
| cd5 | 31 | −111 | 0.91 | 19 / −67 | 1 | −49 | +126 | −348 | [−637, −59] | 0.97 |
| cd15 | 30 | −236 | 0.81 | 19 / −67 | 0 | | | −473 | [−762, −184] | 0.96 |
| cd30 | 28 | +76 | 1.07 | 16 / −68 | 0 | | | −162 | [−488, +164] | 0.71 |
| sm15 | 36 | +364 | 1.26 | 17 / −81 | 7 | −557 | +435 | +127 | [−343, +597] | 0.29 |
| sm20 | 34 | +600 | 1.50 | 13 / −92 | 6 | −539 | +140 | +363 | [+166, +559] | 0.00 |
| anc2 | 37 | +245 | 1.18 | 20 / −68 | 7 | −433 | +337 | +7 | [−0, +15] | 0.27 |
| roll15 | 38 | +237 | 1.17 | 21 / −68 | 8 | −526 | +474 | 0 (identical) | | |
| dp05 | 12 | +395 | 2.19 | 6 / −55 | 0 | | | +158 | [−565, +880] | 0.40 |
| dp10 | 11 | +365 | 1.95 | 5 / −77 | 0 | | | +128 | [−829, +1 085] | 0.29 |
| skip3 | 36 | +235 | 1.16 | 19 / −75 | 7 | −530 | +495 | −3 | [−9, +3] | 0.74 |
| skip5 | 33 | +151 | 1.11 | 17 / −80 | 6 | −508 | +291 | −86 | [−208, +35] | 0.85 |
| half | 38 | +244 | 1.25 | 21 / −46 | 8 | −348 | +474 | +7 | [−216, +229] | 0.40 |
| zs | 33 | +183 | 1.19 | 11 / −86 | 5 | −409 | −131 | −54 | [−254, +146] | 0.63 |
| zsw | 33 | +162 | 1.16 | 11 / −87 | 5 | −417 | −131 | −76 | [−255, +104] | 0.62 |
| zsw15 | 31 | +352 | 1.45 | 8 / −95 | 3 | −292 | +49 | +115 | [+54, +176] | 0.04 |

## 7. Gates

| gate | number |
|---|---|
| reproduction (fires) | 184/191 recorded CbZoneEntry fires matched (same side + tf within 60 s), 7 missed = executor restarts, 2 extra; era 40/42 |
| reproduction (stop) | 39/40 recorded candle stops reproduced within half a tick |
| recorded vs simulated, candle era | recorded 38 positions +169 / 4 pairs; sim-live 38 positions +237 / 8 pairs (paper positions lost on restarts, sim keeps them) |
| null floor / noise | every full-window Δ except `half` (−936, CI [−1 623, −244]) has a 90 % CI straddling 0; era CIs rest on 3 blocks |
| degeneracy | stop-multiplier sweep is a plateau 1.5–2.5 (+548 / +605 / +636) and falls at 3.0 (−163): not a boundary optimum |
| no-op check | roll15 ≡ live in the era (41/42 fires: rolling 15-min extreme = forming-candle extreme); anc2 Δ +7 |
| look-ahead | all inputs are trades ≤ t and indicator readings received ≤ t; the pair detector is descriptive only |
| provenance | nothing fitted; every knob a hand-picked grid; oos2m not touched (executor-DB only) |
| fees | paper = 0; the −0.1 %/side column is a sensitivity; at that fee every variant is deeply negative, wider stops least so |

## 8. Verdict and proposals

Pattern confirmed and costly (§2); mechanism = stop anchored on the fire's own extreme inside a zone 2–4 stops deep
(§3). Proposals, ranked by evidence:

1. **Widen the candle stop: offset × 2 (… 2.5).** Full +605 / +636 (P(Δ<0) 0.21 / 0.11), era +363 (P 0.00, 3
   blocks); stop-outs 82 → 54 / 43, PF 1.38 → 1.58 / 1.71, win rate 51 → 64 / 69 %, fee-adjusted net −13.5 k →
   −9.5 k / −7.6 k. Pairs do not disappear (30 / 25) but the P1 legs shrink to 39 % of the stop money at 2.5. One
   parameter in `cb_stop` (`CB_STOP_RANGE_MULT`, today implicitly 1.0). The only proposal with the right sign on
   both windows. Plateau 1.5–2.5; 3.0 gives it back.
2. **Stop beyond the entry-side `cbnc` bound (zone-depth stop)** — same family, not better: +151 / +206 full, −54 /
   −76 era; with offset × 1.5 (zsw15) era +115 (P 0.04) but full −52. Keep as the structural alternative to 1 if
   the multiplier is felt to be arbitrary; no evidence it beats × 2.
3. **Cooldown after a stop-out (5 / 15 / 30 min, same side)** — dead. It removes exactly the P2 legs, which are net
   positive (+226 … +606), and blocks the reversal re-entries: full +78 / −77 / −737, era −348 / −473 / −162
   (P 0.97 / 0.96). The second trade is the one that works; the problem is the first.
4. **Enter deeper (price 0.5 / 1.0 mean ranges beyond the zone line)** — unsupported. Halves to quarters the trade
   count (171 → 71 / 41); full −334 / −1 819, era +158 / +128 inside noise; tf 60 turns negative at 0.5.
5. **Size the first leg half, the re-entry full** — dead (full −936, P 0.99; era +7): most winners are first legs,
   so halving them costs more than the P1 losses it saves. Likewise **skip the first 3 / 5 minutes of the 15-min
   candle** (−614 / −17 full, −3 / −86 era) and **anchor on the previous candle / rolling 15 min** (no-op, §3).

Forward check: re-run `--t0=` after ≥ 2 weeks of candle-stop trades; if proposal 1 is deployed, replay the new era
against `sm20` for the reproduction gate. Fee breakeven (≈ 0.02 %/side) still dominates every toggle here.
