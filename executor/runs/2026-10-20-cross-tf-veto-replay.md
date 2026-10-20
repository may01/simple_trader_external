# Replay: higher-tf zone marker discards lower-tf fires (last 24 h of the paper run)

Date: 2026-10-20. Question (user): when markers point two ways — e.g. tf 15 in the buy zone while tf 60 is in
the sell zone — how does the P&L change if the higher tf's marker discards the lower tf's signal?

Data: `cbov-check` paper stack (Binance LINKUSDT, paper balance 100 000, `RISK_PER_TRADE=100`,
`MAX_NOTIONAL_FRACTION=0.5`), read straight from its tables: `trade`, `signal_log` CbZoneEntry rows,
`position_log`, and `indicators` (every `{tf}_cb_inzone_*` / `{tf}_cb_zone_*` reading main/ broadcast, with
its expiry). Headline window = the last 24 h of stored trades, **2026-10-19 21:17Z → 2026-10-20 21:17Z**
(82 fires, 75 positions). Two more windows for robustness: the 24 h before (10-18 21:17Z → 10-19 21:17Z,
43 fires) and the whole CB-fire history (10-18 11:41Z → 10-20 21:17Z, 152 fires).
Script: [`2026-10-20-cross-tf-veto-replay.py`](2026-10-20-cross-tf-veto-replay.py) (numpy only);
outputs: [24 h](2026-10-20-cross-tf-veto-replay-output-24h.txt), [previous 24 h](2026-10-20-cross-tf-veto-replay-output-prev24h.txt),
[full span](2026-10-20-cross-tf-veto-replay-output-full.txt). Status: **answered; no rule change recommended yet (§6).**

## 1. What "two directions" means here, and what the live check already does

A fire of tf T, side s, at time t is *contradicted* when a higher tf H > T is in-zone on the opposite side at t:
`{H}_cb_inzone_{opp(s)} == 1` on the latest non-expired reading (the executor's own `MarketDataWindow` rule).
The live `CbZoneEntryCheck` already refuses to fire when *candidates* exist on both sides in the same evaluation
(spec 2026-10-18 §2), but a higher tf that is merely in its zone — trend class not aligned, filter vetoed, or its
zone already consumed by an earlier fire — is not a candidate, so the lower tf fires against it. That is the
situation the question describes.

Variants replayed (a vetoed fire is removed from the event stream; the simulator then runs as live):

| variant | rule |
|---|---|
| **none** | as live (reproduction) |
| **opp_zone** | drop a tf-T fire when any higher tf is in-zone on the **opposite** side — the question as asked |
| any_zone | drop when any higher tf is in-zone on **either** side (higher structure owns the minute) |
| opp_price | drop when the trade price sits beyond a higher tf's opposite zone *line* (long with price ≥ `{H}_cb_zone_short`, short mirrored) |
| opp_fire | drop when a higher tf *fired* the opposite side on its current zone value (same tf candle) |
| no_lower_rev | a lower-tf opposite fire may not **reverse** a position opened by a higher tf (flat → opens as usual) |

Simulator = the 2026-10-20 stop replay's, unchanged: recorded fires in order; flat → open at the recorded entry
(book mid), same side while open → skip, opposite → reversal; stop = the event's stop when adverse to the entry
else the placeholder (1 % before the 20:25Z restart, 0.2 % after); stop trips on the crossing trade; target exit
= extreme past the target then the opposite 10-s trend class (port of `signals::trend`); size =
`min(100 / dist, free_quote × 0.5 / entry)`; no fees.

## 2. Gates

| Gate | Result |
|---|---|
| Reproduction (24 h) | sim `none` opens the same **75/75** positions as the live run (10 reversal opens matched by time: a reversal's open leg carries its own decision id), same stop 75/75, same close reason 75/75. Net: actual **+442.73**, sim **+205.27** — the gap is the paper mid-fill on 51 stop-outs (sim fills at the crossing trade, ≈ 4–5 USDT per stop more pessimistic; same model on every row, so the comparison between variants is unaffected). |
| Reproduction (previous 24 h) | opens 25/29, close reason 13/25 — that day ran older rules (trailing advisor on, no P&L number, placeholder stop only); the window is a **counterfactual under today's rules**, not a reproduction. |
| Null floor | 24 h: 75 trades, bootstrap 90 % CI of the net: none [−299, +744], opp_zone [−218, +867]. Every CI contains zero and every pair overlaps almost entirely. |
| Concentration | top-2 trades +265 in every variant (the veto never touches them); none without its top-2 = −52, opp_zone = +48. |
| Feed gaps | one gap > 60 s in the 24 h window (305 s at 10-20 16:13Z). |
| Base rate of the vetoed fires | 24 h: the 8 contradicted fires were 8/8 stop-outs against a 68 % stop-out base rate (P ≈ 0.05 under the base rate — not strong on 8 draws); previous day: 3/3 target exits. |

## 3. How often it happens

| window | fires | contradicted (opp_zone) | same-side higher zone | price beyond higher opposite line | higher tf fired opposite on its live zone |
|---|---|---|---|---|---|
| last 24 h | 82 (15: 56, 60: 19, 240: 7) | **8** (10 %) | 10 | 10 | 31 |
| previous 24 h | 43 | 3 | 5 | 3 | 10 |
| full span | 152 | 16 (11 %) | 16 | 18 | 43 |

All 16 contradicted fires on the full span are tf 15 or tf 60 against tf 60/240; 15 of 16 are tf 15.

## 4. Results

Last 24 h (headline; same fill model on every row):

| variant | trades | net USDT | PF | win % | stop-outs | targets | reversals | vetoed | 90 % CI | P(net<0) | ΣR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| none (as live) | 75 | **+205** | 1.25 | 29 | 51 | 14 | 10 | 0 | [−299, +744] | 0.28 | +1.8 |
| **opp_zone** | 65 | **+307** | 1.43 | 34 | 42 | 14 | 9 | 8 | [−218, +867] | 0.18 | +11.1 |
| any_zone | 58 | +396 | 1.64 | 38 | 35 | 14 | 9 | 17 | [−128, +931] | 0.11 | +18.1 |
| opp_price | 63 | +358 | 1.52 | 37 | 40 | 14 | 9 | 10 | [−158, +922] | 0.14 | +13.5 |
| opp_fire | 40 | −138 | 0.75 | 30 | 27 | 11 | 2 | 31 | [−496, +254] | 0.72 | −8.0 |
| no_lower_rev | 63 | −124 | 0.84 | 24 | 48 | 11 | 4 | 10 | [−504, +297] | 0.70 | −26.4 |

With stop fills at the stop level instead of the crossing trade: none +210, opp_zone +312, any_zone +401 (unchanged picture).

Where opp_zone's +101 comes from (same opening event, none → opp_zone): 10 stop-outs not opened (−170 → 0: the 8
vetoed fires, −140, plus 2 fires that are now same-side-skipped because the position they would have opened
after is still held, −30), one reversal that becomes a full stop-out because the lower-tf fire that would have reversed it was vetoed
(−26 → −100), everything else identical (9 reversals +570, 14 targets +435, 41 stop-outs −603).

The 8 vetoed fires under the live rule: every one stopped out, median hold 0.2 min, total −140 USDT
(23:17 L15 vs 240-short; 00:34 S15 vs 60-long; 01:20 S15 vs 60+240-long; 11:46 L15 vs 60-short; 12:31 L15 vs
60-short; 14:48 L15 vs 60+240-short — the 12.43 spike; 15:05 L60 vs 240-short; 15:46 L15 vs 240-short).

Previous 24 h (counterfactual under today's rules, §2):

| variant | trades | net | PF | vetoed | 90 % CI | P(net<0) |
|---|---|---|---|---|---|---|
| none | 30 | **+341** | 2.37 | 0 | [+22, +646] | 0.04 |
| **opp_zone** | 27 | **+198** | 1.65 | 3 | [−157, +541] | 0.17 |
| any_zone | 25 | +269 | 2.32 | 8 | [−24, +560] | 0.07 |
| opp_price | 27 | +198 | 1.65 | 3 | [−157, +541] | 0.17 |
| opp_fire | 23 | +233 | 1.87 | 10 | [−120, +572] | 0.14 |
| no_lower_rev | 8 | −36 | 0.86 | 17 | [−389, +323] | 0.56 |

The 3 vetoed fires that day were 3/3 target exits (+40, +34, +14 = +87); the veto also turned one reversal into
a −100 stop-out. **The sign of the effect flips between the two days.**

Full span (10-18 11:41Z → 10-20 21:17Z, 152 fires, mixed live rules):

| variant | trades | net | PF | vetoed | 90 % CI | P(net<0) |
|---|---|---|---|---|---|---|
| none | 117 | **+435** | 1.31 | 0 | [−305, +1175] | 0.17 |
| **opp_zone** | 103 | **+277** | 1.20 | 16 | [−472, +985] | 0.27 |
| any_zone | 94 | +439 | 1.37 | 31 | [−283, +1155] | 0.16 |
| opp_price | 101 | +329 | 1.24 | 18 | [−400, +1066] | 0.24 |
| opp_fire | 73 | −2 | 1.00 | 43 | [−679, +649] | 0.50 |
| no_lower_rev | 83 | −270 | 0.80 | 27 | [−924, +388] | 0.74 |

Over the full span the 16 contradicted fires split 11 stop-outs (−271), 4 target exits (+186), 1 reversal (+7);
removing them saves +271 and forgoes +193, and two reversals that the vetoed fires would have triggered become
full −100 stop-outs (−130) — net −158.

## 5. Reading

1. **On the day asked, the veto helps: +205 → +307 (PF 1.25 → 1.43), by skipping 8 fires that were all
   instant stop-outs.** Sizes are small (8 fires, −170 USDT); the CIs of the two rules overlap almost entirely.
2. **On the day before it hurts: +341 → +198**, because the three contradicted tf-15 fires were the ones that
   rode to the target. Over the full 2.5-day history it is −158 USDT. The hypothesis does not survive a second day.
3. A contradicted lower-tf fire is not systematically bad — it is a *counter-trend* entry against the larger
   structure, which on 10-20 (two 2–3 % moves) meant being run over, and on 10-18/19 (range) meant catching the
   turn. The veto is a regime bet, not an edge.
4. `any_zone` (skip any lower-tf fire while a higher tf is in *either* zone) is the only variant that is not
   negative anywhere (+396 / +269 / +439 vs +205 / +341 / +435): it removes 31/152 fires, mostly instant
   stop-outs on 10-20, and keeps the full-span net flat. Still inside every CI.
5. The two "marker" readings are clearly worse: skipping after a higher-tf *fire* (`opp_fire`, 43 fires removed,
   full span −2) and forbidding lower-tf reversals of higher-tf positions (`no_lower_rev`, −270): tf-15 fires
   reversing a higher-tf position made **+340 on 10-20 and +397 over the span** — the reversal is doing the work
   the stop should do. Do not remove it.
6. Mechanically the opp_zone veto is a few lines in `CbZoneEntryCheck` (the higher tfs' `cb_inzone_*` flags are
   already in `required_indicators`); nothing stops it from being a toggle. The numbers do not justify switching
   it on today.

## 6. Verdict

Not decidable on one day, and the second day points the other way. The user's rule (higher tf in the opposite
zone discards the lower tf's fire) is +101 USDT on 2026-10-20 (8 fires, 10 % of fires), −143 on 2026-10-19,
−158 over the full history, every CI straddling zero. If a cross-tf rule is wanted at all, `any_zone` is the
candidate to run forward as a toggle (`CB_ZONE_HIGHER_TF_VETO=any|opposite|off`) beside the live rule; the fair
test is a second paper stack side by side, or this replay once the trade store covers a week.

## 7. Caveats

- One pair, 2.5 days, two regimes; the 24 h headline has 8 affected fires.
- Previous-day and full-span rows apply today's rules to days that ran older ones (trailing advisor, placeholder
  stop only, no trend-exit before 10-18 evening); the positions are counterfactual there.
- Stop fills at the crossing trade (pessimistic vs paper's mid-fill; same for all rows).
- In-zone state is sampled from main/'s 30-s broadcast with its expiry; a zone minute shorter than the broadcast
  interval can be missed on both sides equally.
- Not P&L-validated on a non-contradicted sample of the same size: the comparison is within one day's 8 fires.
