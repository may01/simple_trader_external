# Replay: a 3- / 5-min trade-price MA as the entry's trend class for the 60- and 240-min zones

Date: 2026-10-20. Question (user): how does the profit change if, for the higher-tf zones (60 and 240 min), the
activation signal uses a longer MA of the recent trades — 3 min and 5 min — instead of the live 1 min?

Data: `cbov-check` paper stack (Binance LINKUSDT, paper balance 100 000, `RISK_PER_TRADE=100`,
`MAX_NOTIONAL_FRACTION=0.5`), read straight from its tables: `trade` (670 282 rows, 10-16 22:29Z → 10-20 21:24Z),
`indicators` (42 CB names, 406 646 readings with their expiry), `signal_log` CbZoneEntry rows (152) and
`position_log` (the last two for the reproduction gate only). Window = the whole CB-armed history,
**2026-10-18 11:41Z → 2026-10-20 21:24Z (57.7 h, 450 017 trades)**.
Script: [`2026-10-20-ma-window-by-tf-replay.py`](2026-10-20-ma-window-by-tf-replay.py) (numpy only; the export SQL is in
its header); full output incl. every per-trade table and the live → variant transition tables:
[`…-output.txt`](2026-10-20-ma-window-by-tf-replay-output.txt).
Status: **answered — the longer MA does not improve the higher-tf trades; no rule change recommended (§8).**

## 1. What was replayed

Unlike the stop replay, nothing recorded is reused: every fire is recomputed from the stored indicators and trades
with a port of `CbZoneEntryCheck` + `signals::trend` + `cb_stop::compute_candle_stop` + the orchestrator's open /
skip / reversal and the executor's stop watcher and trend-flip exit (cb-candle-stop @ `a6a5bc6`). Per trade `t`:

- indicators = the latest stored reading with `received_at ≤ t < expires_at` (the store's own query);
- trend class = 10 s bucket means over the last 6 000 trades, trailing mean over **W** buckets, slope = first
  difference, σ = population std of the slopes in the last 2 h, up/down if |slope| > 0.7 σ, ≥ 30 buckets;
  W = 6 (1 min, live), 18 (3 min), 30 (5 min) — all three computed from the same grid at every trade;
- rule 1 / rule 2, filters (0 vetoes, absent passes), once per (tf, side, zone) with the latest zone per (tf, side)
  remembered, both sides → nothing, 60 s gap deferred, highest tf fires, target = `{tf}_cbnc_{far}` at fire;
- stop = forming-15m extreme ∓ mean range of the last 60 closed 1-min bars (bars from the trades), 0.2 % placeholder
  when not adverse — today's live rule, held fixed for every variant; size `min(100 / dist, free × 0.5 / entry)`;
  entry at the fire trade's price; stop fills at the crossing trade; paper = no fees (fee column as sensitivity).

| variant | entry MA (buckets) tf 15 / 60 / 240 | exit MA for tf 60/240 positions | what it answers |
|---|---|---|---|
| **live** | 6 / 6 / 6 | 6 | reproduction |
| **e3** | 6 / **18** / **18** | 6 | the question, 3 min — activation only |
| **e5** | 6 / **30** / **30** | 6 | the question, 5 min |
| x3 / x5 | as e3 / e5 | **18 / 30** | the longer MA on both ends of the higher-tf trade |
| a3 / a5 | 18 / 18 / 18 and 30 / 30 / 30 | 6 | ablation: is the effect tf-specific or just "slower MA"? |
| t10 / t15 | 6 / 6 / **60** and 6 / 6 / **90** | 6 | user follow-up: 10 / 15 min MA for the 240 zone only (§7) |
| x10 / x15 | as t10 / t15 | **60 / 90** | the same window on the 240 position's exit |

Author's calls (user not available during the run; flag if you disagree): "longer MA" = the live class with the
trailing-mean window raised from 6 to 18 / 30 buckets, everything else (bucket, σ span, 0.7 σ, min buckets)
unchanged; the 15-min zone keeps the 1-min class; the exit keeps the 1-min class in the primary variants (x3/x5
report the alternative); one stop rule (today's) across the whole window, so the live run's earlier stop rules are
*not* reproduced — fires are, P&L is not.

## 2. Gates

| Gate | Result |
|---|---|
| Reproduction: fires | `live` re-fires **145 of the 152** recorded CbZoneEntry rows (same side + tf within 60 s; median \|dt\| 0.0 s, max 2.7 s); same rule 144/145, same class 144/145, same zone value 145/145; at the 141 exact-timestamp matches the logged `ma_slope` is reproduced to a median relative difference of 2.6 × 10⁻⁸ (one row at 4.7 × 10⁻², all others < 1 %). The 7 misses sit at the three executor (re)starts — 10-18 11:41Z (boot), 10-19 22:43Z (release_001), 10-20 20:25Z (candle stop) — where the live check had a short trade window / empty fired-state and the sim has neither; 2 extra sim fires are the same zones fired a few minutes later. |
| Reproduction: stop port | one recorded candle-stop fire in the window: anchor reproduced exactly (12.3200), offset 0.0093 vs logged 0.0086 — the live `MinuteBars` had ~35 closed bars 36 min after its restart, the sim uses the full 60. |
| Look-ahead | by construction: indicators by `received_at ≤ t`, trades ≤ t, bars closed before the current minute, the forming bar only up to the current trade. |
| Provenance | no parameter fitted: 0.7 σ, 2 h, 6 000 trades, 60 s gap, 15-min anchor, 60 bars, 0.2 % and the sizing are the live values; 3 / 5 min are the user's. |
| Null floor | 135 positions; bootstrap 90 % CI of the net: live [+431, +4 597], e3 [+537, +4 433], e5 [+203, +4 111]. The variant differences (−7 and −361 USDT) are far inside the CI widths. On the tf 60 + 240 subset (27–35 positions) every CI contains zero. |
| Concentration | top-2 trades +733 (live), +687 (e3), +688 (e5) — the same two 240-zone trades in every variant (10-20 06:16Z, 10-20 16:19Z). |
| Ablation | a3 / a5 (longer MA on every tf): net +1 723 / +1 042 vs +2 489 — the slower class is worse everywhere, not only on the higher tfs (§5). |
| Split halves | live +797 / +1 692; e3 +940 / +1 542; e5 +855 / +1 273 — no half where a longer MA wins by more than the noise. |
| Feed gaps | 3 gaps > 60 s in the window: 5 564 s (10-19 13:01Z), 9 432 s (10-19 20:01Z), 305 s (10-20 16:13Z). |

## 3. Results

Same simulator, same stop rule, same window for every row.

| variant | trades | net | net with 0.1 %/side fee | PF | win rate | stop-outs n / mean | targets | reversals | median hold | median risk | sum R | 90 % CI | P(net<0) | top-2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **live** | 135 | **+2 489** | −9 914 | 1.48 | 53 % | 62 / −83 | 53 | 20 | 7.1 min | 87 | +35.1 | [+431, +4 597] | 0.02 | +733 |
| **e3** | 134 | **+2 482** | −9 423 | 1.52 | 55 % | 56 / −83 | 56 | 22 | 7.2 min | 93 | +32.3 | [+537, +4 433] | 0.02 | +687 |
| **e5** | 133 | **+2 128** | −9 603 | 1.45 | 55 % | 55 / −83 | 56 | 22 | 7.0 min | 93 | +26.9 | [+203, +4 111] | 0.03 | +688 |
| x3 | 134 | +2 381 | −9 522 | 1.50 | 55 % | 56 / −83 | 55 | 23 | 7.2 min | 93 | +31.2 | [+455, +4 301] | 0.02 | +678 |
| x5 | 133 | +2 097 | −9 636 | 1.45 | 55 % | 55 / −83 | 54 | 24 | 7.0 min | 93 | +26.6 | [+190, +4 076] | 0.03 | +675 |
| a3 | 125 | +1 723 | −8 663 | 1.43 | 56 % | 43 / −87 | 65 | 17 | 6.8 min | 100 | +20.9 | [+37, +3 430] | 0.05 | +684 |
| a5 | 114 | +1 042 | −8 161 | 1.27 | 53 % | 43 / −86 | 56 | 15 | 7.5 min | 100 | +11.4 | [−667, +2 862] | 0.16 | +683 |
| t10 | 136 | +2 226 | −9 967 | 1.44 | 53 % | 60 / −83 | 53 | 23 | 7.0 min | 91 | +31.4 | [+193, +4 332] | 0.04 | +675 |
| t15 | 135 | +1 861 | −10 327 | 1.36 | 51 % | 61 / −83 | 52 | 22 | 6.9 min | 91 | +24.0 | [−113, +3 974] | 0.06 | +688 |
| x10 | 136 | +2 152 | −10 041 | 1.42 | 53 % | 60 / −83 | 53 | 23 | 7.0 min | 91 | +30.6 | [+131, +4 231] | 0.04 | +675 |
| x15 | 135 | +1 826 | −10 362 | 1.35 | 51 % | 61 / −83 | 52 | 22 | 6.9 min | 91 | +23.6 | [−137, +3 933] | 0.06 | +675 |

Positions by the tf of their opening fire (the rows the question is about are tf 60 and tf 240):

| variant | tf 15: n, net, PF | tf 60: n, net, PF | tf 240: n, net, PF | tf 60 + 240: n, net, PF, 90 % CI |
|---|---|---|---|---|
| **live** | 100, +1 717, 1.47 | 26, +106, 1.09 | 9, +667, 2.98 | **35, +772, 1.49, [−361, +2 015]** |
| **e3** | 106, +1 910, 1.52 | 19, −171, 0.81 | 9, +743, 5.76 | **28, +572, 1.54, [−407, +1 583]** |
| **e5** | 106, +1 886, 1.51 | 18, −292, 0.65 | 9, +534, 3.93 | **27, +242, 1.24, [−632, +1 167]** |
| x3 | 106, +1 910, 1.52 | 19, −221, 0.76 | 9, +692, 5.43 | 28, +471, 1.44 |
| x5 | 106, +1 886, 1.51 | 18, −249, 0.71 | 9, +460, 3.53 | 27, +211, 1.21 |
| a3 | 93, +1 446, 1.51 | 23, −61, 0.93 | 9, +338, 2.55 | 32, +277, 1.24 |
| a5 | 84, +959, 1.36 | 21, −163, 0.83 | 9, +246, 1.70 | 30, +83, 1.06 |
| t10 | 101, +1 684, 1.46 | 27, +1, 1.00 | 8, +541, 6.48 | 35, +542, 1.38, [−484, +1 600] |
| t15 | 100, +1 551, 1.43 | 27, +1, 1.00 | 8, +310, 2.14 | 35, +311, 1.19, [−752, +1 403] |
| x10 | 101, +1 684, 1.46 | 27, +1, 1.00 | 8, +467, 5.74 | 35, +468, 1.33 |
| x15 | 100, +1 550, 1.43 | 27, +1, 1.00 | 8, +274, 2.01 | 35, +275, 1.17 |

Fires: live 147 (15: 109, 60: 29, 240: 9); e3 147 (111 / 27 / 9); e5 145 (110 / 26 / 9). Class at the fire, live:
up 41, down 53, neutral 53 (rule 1 87, rule 2 60); e3 rule 1 83 / rule 2 64; e5 79 / 66.

## 4. Where the difference comes from

The longer MA does not select different zones — it fires the **same** (side, tf, zone) keys later. Of the 38 live
higher-tf fire keys, e3 fires 35 (3 never fire, 1 new), e5 34; the delay on the common keys is median +0.6 min (e3,
max +20.7) and +1.8 min (e5, max +33.6). Every live tf 60/240 position matched to the variant position opened on the
same side within −5…+40 min (full tables in the output):

| live → e3 | n | P&L live | P&L e3 | Δ |
|---|---|---|---|---|
| tf 60 → tf 60 (same trade, later entry) | 18 | −99 | −162 | −62 |
| tf 60 → **tf 15** (the 15-min zone fires first, the delayed 60 fire is skipped as same-side; the trade inherits the 15-min target) | 6 | +375 | +126 | **−249** |
| tf 60 → not opened | 1 | −103 | 0 | +103 |
| tf 60 → tf 240 | 1 | −68 | +19 | +86 |
| tf 240 → tf 240 | 8 | +755 | +725 | −31 |
| tf 240 → tf 60 | 1 | −89 | −10 | +79 |

| live → e5 | n | P&L live | P&L e5 | Δ |
|---|---|---|---|---|
| tf 60 → tf 60 | 16 | −144 | −295 | −152 |
| tf 60 → tf 15 | 8 | +420 | +77 | **−343** |
| tf 60 → not opened | 1 | −103 | 0 | +103 |
| tf 60 → tf 240 | 1 | −68 | +19 | +86 |
| tf 240 → tf 240 | 8 | +755 | +515 | **−240** |
| tf 240 → tf 60 | 1 | −89 | −10 | +79 |

Three effects, two of them against the idea:

1. **Later entry on the same zone, same outcome, worse price.** The stop-outs stay stop-outs (−87 → −87, −103 →
   −102 …: the stop is anchored on the 15-min extreme, so a later entry does not move it away) while the reversal
   and target exits shrink because the entry is 4–27 ticks further along the move: +108 → +39, +188 → +80
   (e5: +38), +341 → +287 (e5: +244), +133 → +96. This is what a slower MA has to cost: it confirms the direction
   after the price has already left the zone.
2. **Re-labelling to the 15-min zone.** 6–8 of the live tf-60 trades were simultaneous 15 + 60 candidates where the
   highest-tf rule gave the open to the 60 zone. With the 60 class lagging, the 15 zone fires first, the 60 fire
   comes seconds later and is skipped as same-side, and the position carries the 15-min `cbnc` target — nearer, so
   the trend-flip exit arms earlier and the same move pays +9 instead of +107, +16 instead of +104. The per-tf
   table's "tf 60 gets worse, tf 15 gets better" is mostly this bookkeeping, which is why the totals are the fair
   comparison.
3. **Dodging a shake-out.** In 3 (e3) / 3 (e5) cases the late entry misses a stop-out that the live fire took and
   rides to a reversal instead (−100 → +60, −104 → +34, −68 → +19): +270 in e3's favour. It is outweighed by 1 and 2.

Using the longer class for the exit too (x3 / x5) removes one more target exit on the higher tfs and loses another
~100 USDT: the slower class also confirms the turn later.

## 5. Ablation: the slower MA everywhere

a3 / a5 apply the same 18 / 30-bucket class to the 15-min zone as well. Rule-1 fires collapse (87 → 40 → 28) because a
3–5-min slope rarely clears ±0.7 σ while the price is still in the zone minute; the entries shift to rule 2 (60 → 96 →
100), the number of positions drops (135 → 125 → 114), and the net falls to +1 723 / +1 042. The slower class is not a
better activation signal on any tf in this sample — the higher tfs are simply where it hurts least because their
trades are fewer and longer.

## 6. Caveats

1. **57.7 h, one pair, one regime** (LINK 11.7–12.4). 35 higher-tf positions in the live variant, 9 of them on tf 240;
   two 240 trades are a third of the net in every row. The bootstrap CIs of the higher-tf subset all contain zero;
   this replay can say the longer MA is *not better here* and *why* (§4), not that it is worse by a known amount.
2. **Not a reproduction of the live P&L.** The live run went through three stop rules in this window; the replay
   applies today's candle stop to all 57.7 h for every variant. The recorded fires are reproduced (gate 1), the
   recorded P&L is not meant to be.
3. **Fill model.** Entry at the fire trade's price (the live book mid is not stored at scale); stop fills at the
   crossing trade (≈ 4–5 USDT per stop more pessimistic than the paper mid-fill, same for every variant).
4. **Restarts.** The live check forgets its fired zones and trims its trade window at every restart; the sim does
   not. 7 of 152 fires differ for that reason — none of them on a variant-specific path.
5. **Fees.** Paper charges none. With 0.1 % per side every variant is deeply negative (−8 to −10 k): at ~50 000
   notional a round trip costs ~100 USDT, i.e. the whole median risk per trade. Independent of the question, but
   the first thing a live run would meet.
6. The candle stop's 60-bar mean uses the full trade history; the live `MinuteBars` warms up from boot (one recorded
   offset 0.0086 vs 0.0093 here).

## 7. Follow-up (user, 2026-10-20): 10 / 15 min MA for the 240 zone only

Same script, windows 60 and 90 buckets on the 240 zone alone (t10 / t15; x10 / x15 also on the 240 exit); tf 15 and
60 keep the 1-min class. Fires: t10 148 (15: 109, 60: 30, 240: 9), t15 147 (109 / 30 / 8).

| 240-zone entry MA | net all | tf 240: n, net, PF | tf 60 + 240: n, net, PF | 240 keys fired vs live |
|---|---|---|---|---|
| 1 min (live) | +2 489 | 9, +667, 2.98 | 35, +772, 1.49 | — |
| 3 min (e3) | +2 482 | 9, +743, 5.76 | 28, +572, 1.54 | 8/9 same keys |
| 5 min (e5) | +2 128 | 9, +534, 3.93 | 27, +242, 1.24 | |
| **10 min (t10)** | **+2 226** | 8, +541, 6.48 | 35, +542, 1.38 | 38/38 same keys, delay median +0.0 min, max **+42.6** |
| **15 min (t15)** | **+1 861** | 8, +310, 2.14 | 35, +311, 1.19 | 37/38 same keys, max delay +20.7 |
| 10 min entry + exit (x10) | +2 152 | 8, +467, 5.74 | 35, +468, 1.33 | |
| 15 min entry + exit (x15) | +1 826 | 8, +274, 2.01 | 35, +275, 1.17 | |

Monotone in the window length: the longer the MA, the later the same 240 zone fires and the less the trade pays.
Every live tf-240 position matched to its t10 / t15 counterpart (same side, opened within −5…+40 min):

| live tf 240 position | live | t10 (delay, entry Δ) | t15 (delay, entry Δ) |
|---|---|---|---|
| 10-18 21:16Z Sell, stop | −91 | −69 as a tf-15 trade (+4.6 min) | −86 (−0.1 min) |
| 10-19 02:11Z Sell, reversal | +111 | not opened (a 60 fire took the slot) | not opened |
| 10-19 23:05Z Sell, reversal | +188 | **+21** (+7.9 min, 34 ticks worse) | **−103, stopped** (+12.5 min, 50 ticks worse) |
| 10-20 12:26Z Sell, reversal | +69 | +8 (+3.0 min, 17 ticks) | +8 (+3.0 min) |
| 10-20 21:01Z Sell, stop | −54 | −71 (+2.2 min) | −54 |
| 5 / 6 others (incl. the two +296 / +341 trades) | unchanged or ±10 | | |

Aggregate over the 9 live tf-240 positions: t10 −440 (+839 → +467 on the 5 that stay 240 trades, −111 for the one
not opened, +43 on the two re-labelled), t15 −519. The tf-60 column is identical in t10 / t15 (27 trades, +1): the
60 zone is untouched, its one extra fire is the 02:11Z slot the slower 240 class let go.

A 10–15-min MA of 10-s buckets needs 6–9 buckets of the same sign at ±0.7 σ to flip; on a 4-h zone the price has
usually left the zone minute by then (the 23:05Z trade: the move was 50 ticks along before the 15-min class said
"down"), and the 15-min-anchored stop then sits 50 ticks *further* from the entry in R terms while the reversal /
trend-flip exits land at the same price as before. Nothing here distinguishes 10 from 15 min beyond the noise, but
no window in 3…15 min beats 1 min on the 240 zone, and the direction of the curve is uniform (+667 → +743 → +534 →
+541 → +310 on the tf-240 rows, +772 → +572 → +242 → +542 → +311 on the higher-tf subset).

## 8. Verdict

**Negative.** With the 1-min class replaced by a 3-min (e3) or 5-min (e5) trade-price MA class for the 60- and 240-min
zones, the net over the 57.7 h goes +2 489 → +2 482 (e3) → +2 128 (e5); on the tf 60 + 240 positions +772 → +572 →
+242, PF 1.49 → 1.54 → 1.24. Every difference is inside the bootstrap noise, but the mechanism is not noise: the
slower MA fires the same zones 0.6–1.8 min later at a worse price, leaves the stop where it was, hands 6–8 trades to
the 15-min zone's nearer target, and gains back only three dodged shake-outs. Using it on the exit as well (x3 / x5)
costs another ~100. Applied to every tf (a3 / a5) it is clearly worse. The follow-up with 10 / 15 min on the 240 zone
alone (§7) sits on the same curve: +2 226 / +1 861 total, tf 240 +541 / +310 vs +667, the same zones fired up to 43 min
later. Keep the 1-min class; if the higher-tf zones are to be filtered, the lever is not a slower version of the same signal.
