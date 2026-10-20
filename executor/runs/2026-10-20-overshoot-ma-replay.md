# Replay: in overshoot-vetoed zone minutes, trade on a 3-/5-min trade-price MA instead of skipping (the whole CB-armed paper history, 57.7 h)

Date: 2026-10-20. Question (user): what P&L would the system make if, in overshoot zones, instead of filtering
the trades out it relied on the signal from a higher MA of the recent trades — try a 3-min MA and a 5-min MA?

Data: `cbov-check` paper stack (Binance LINKUSDT, paper balance 100 000, `RISK_PER_TRADE=100`,
`MAX_NOTIONAL_FRACTION=0.5`), read from its own tables: `trade` (every stored trade), `indicators` (every CB
reading main/ broadcast, with its expiry), `signal_log` CbZoneEntry rows (152), `position_log` (108 positions).
Window = the whole CB-armed history, **2026-10-18 11:41Z → 2026-10-20 21:25Z (57.7 h, 450 031 trades)**.
Script: [`2026-10-20-overshoot-ma-replay.py`](2026-10-20-overshoot-ma-replay.py) (numpy only; export SQL in
its header); full output incl. the per-trade tables: [`…-output.txt`](2026-10-20-overshoot-ma-replay-output.txt).
Spec: `docs/superpowers/experiment/overshoot_ma_signal.md`; decision summary
`docs/superpowers/experiment/results/overshoot_ma_signal_results.md`.
Status: **answered — negative. The relaxed entries lose money or break even in every variant; the veto
removes almost no whole zone, only minutes, so the modes differ by 6–19 trades out of ~140.**

## 1. What was replayed

The entry check is a port of `checks/cb_zone_entry.rs` + `signals::trend` run on every stored trade (not on the
recorded fires — the question needs fires the live check never emitted): indicators at a trade = the latest
reading received at or before it and not expired; rule 1 (in zone ∧ class = direction), rule 2 (previous 1-min
candle's wick reached the zone and it closed back ∧ class ∈ {neutral, direction}); `cb_f_trend` veto always;
once per (tf, side, zone value), both-sides contradiction, 60 s deferred gap, highest tf. Modes differ only in what
happens when `{tf}_cb_f_overshoot_{side} == 0`:

| mode | in an overshoot-vetoed minute the side is … |
|---|---|
| **current** | skipped (live) |
| no_veto | evaluated with the 1-min class like any other minute (ablation: the veto's own worth) |
| **ma3 / ma5** | evaluated with the 3-min / 5-min class **instead of** the 1-min class — the question |
| ma3_and / ma5_and | evaluated with the 1-min **and** the longer class (ablation) |
| ma3_all / ma5_all | the longer class replaces the 1-min class in **every** minute (reference: is the slower MA a better entry class at all) |

The longer class = `signals::trend` with the trailing-mean window raised from 6 to 18 / 30 buckets of 10 s;
bucket, 2 h σ span, 0.7 σ band, 30-bucket minimum and the 6 000-trade window unchanged.

Position layer = today's live rules, the same in every mode: same-side fire while open = skip, opposite =
reversal; stop = forming-15m extreme ∓ trailing mean range of the last 60 closed 1-min bars (bars built from the
trades, as the executor does), 0.2 % placeholder when not adverse; target = `{tf}_cbnc_{far}` at fire time; close
when the extreme since open passed the target and the **1-min** class flips (the exit is not part of the question);
stop trips on the crossing trade; size `min(100 / dist, free × 0.5 / entry)`; entry at the fire trade's price (the
live book mid is not stored at scale); no fees (paper), with a 0.05 %/side sensitivity column.

## 2. Gates

| Gate | Result |
|---|---|
| Reproduction: fires | `current` re-fires **145 of the 152** recorded CbZoneEntry events (same side, tf, zone; \|Δt\| median 0 s, max 3 s; same rule 144/145, same 1-min class 144/145). 7 missed: 6 are the first fires after an executor restart (10-18 11:41, 10-19 22:43/22:50/23:52, 10-20 20:26/20:31 — the live check's 6 000-trade window was nearly empty, so its σ was tiny and a small slope classed up/down; the sim's window reaches back across the restart and classes neutral) and one (10-20 00:21) fires in sim 4 min later on the same zone (listed under "extra"). 2 extra sim fires = those re-fires. |
| Reproduction: trend port | 1-min slope at the 142 fires matched within 1 s: median relative difference 0.000, 99 % within 10 % of the logged `ma_slope`. |
| Reproduction: P&L | not a target: the live window ran three stop rules in succession (1 % placeholder → book stop 10-20 01:44Z → candle stop 10-20 20:25Z); the sim applies the candle stop throughout. Actual recorded net over the window +472.89 on 79 closed positions with a P&L number. |
| Null floor | marginal trades (the only ones the question adds): no_veto 19 trades, 90 % CI [−1 228, +30], P(net<0) 0.94; ma3 11 trades [−597, +473], 0.59; ma5 6 trades [−473, +220], 0.69. The whole-mode CIs overlap entirely (current [+431, +4 597] vs ma3 [+341, +4 688], ma5 [+365, +4 632]). |
| Concentration | top-2 trades +733 in current/ma3/ma5 (identical trades; the relaxation never touches them). |
| Ablation `_and` | ma3_and ≡ ma3 (same 11 marginal trades, same P&L to the cent); ma5_and differs from ma5 by one deferred fire (−6). The longer class agreed with the 1-min class at 11 of the 12 ma3 vetoed-side fires and 4 of 7 for ma5 — **in an in-zone minute the 3-min MA is not an independent signal, it is the same move seen slower.** |
| Look-ahead | by construction: every indicator read at a trade has `received_at ≤ trade ts`, bars and anchors include only trades at or before the fire, the class uses the window ending at the trade. |
| Feed gaps | 3 gaps > 60 s (10-19 13:01Z 5 564 s, 10-19 20:01Z 9 432 s, 10-20 16:13Z 305 s) — same for every mode. |
| Split halves | current +797 / +1 692, ma3 +731 / +1 720, ma5 +728 / +1 760 (first / second half) — no half favours the relaxation. |

## 3. How often the veto bites — and why it changes so little

Over the 57.7 h, per (tf, side), trades at which the side is otherwise a candidate (trend flag passes, zone and
target present, in zone or rejected) and the share of them the overshoot flag vetoes:

| tf | side | candidate trades | overshoot-vetoed | in-zone minutes | of which vetoed |
|---|---|---|---|---|---|
| 15 | long | 52 259 | 42 % | 658 | 273 |
| 15 | short | 53 101 | 30 % | 780 | 344 |
| 60 | long | 53 364 | 46 % | 409 | 164 |
| 60 | short | 40 675 | 57 % | 486 | 252 |
| 240 | long | 21 695 | 0 % | 373 | 122 |
| 240 | short | 88 894 | 81 % | 421 | 260 |

So the veto removes 30–81 % of the candidate *minutes* — but lifting it entirely (`no_veto`) adds only **19 fires
to 147** (ma3: 12, ma5: 7). The once-per-(tf, side, zone) rule is the reason: a zone that is vetoed on some
minutes is nearly always touched again on a minute where the flag passes (the flag follows the 1-min extreme,
which flips in and out of "deep"), and the live check fires there. The veto almost never removes a *trade*; it
moves the fire to a later minute of the same zone. The question's premise — "trades filtered out in overshoot
zones" — holds for 19 fires in 2.4 days.

(tf 240 long never vetoed; tf 240 short 81 % vetoed through one long short-zone period on 10-19/10-20 — none of
the relaxations fired there because the zone had already fired on a passing minute.)

## 4. Results (same fill model and stop rule on every row)

| mode | trades | net USDT | net −fee (0.05 %/side) | PF | win | stop-outs n / mean | targets | reversals | med hold | med risk | 90 % CI | P(net<0) | top-2 | ΣR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **current** (veto, live) | 135 | **+2 489** | −3 713 | 1.48 | 53 % | 62 / −83 | 53 | 20 | 7.1 min | 87 | [+431, +4 597] | 0.02 | +733 | +35.1 |
| no_veto | 142 | +1 986 | −4 539 | 1.35 | 52 % | 67 / −84 | 51 | 24 | 7.1 | 87 | [−47, +4 083] | 0.05 | +688 | +29.7 |
| **ma3** | 140 | **+2 451** | −3 931 | 1.46 | 54 % | 64 / −84 | 54 | 22 | 7.0 | 88 | [+341, +4 688] | 0.03 | +733 | +34.8 |
| **ma5** | 139 | **+2 488** | −3 850 | 1.46 | 53 % | 64 / −84 | 53 | 22 | 7.2 | 88 | [+365, +4 632] | 0.03 | +733 | +35.1 |
| ma3_and | 140 | +2 451 | −3 931 | 1.46 | 54 % | 64 / −84 | 54 | 22 | 7.0 | 88 | [+341, +4 688] | 0.03 | +733 | +34.8 |
| ma5_and | 139 | +2 482 | −3 855 | 1.46 | 53 % | 64 / −84 | 53 | 22 | 7.1 | 88 | [+357, +4 632] | 0.03 | +733 | +35.0 |
| ma3_all | 131 | +1 628 | −3 807 | 1.38 | 57 % | 46 / −88 | 68 | 17 | 6.8 | 100 | [−127, +3 445] | 0.07 | +683 | +19.9 |
| ma5_all | 118 | +1 053 | −3 687 | 1.26 | 53 % | 45 / −87 | 58 | 15 | 7.5 | 100 | [−676, +2 883] | 0.16 | +683 | +11.5 |

### 4.1 The marginal trades — positions that exist only because a vetoed side was taken

| mode | trades | net | PF | win | stop-outs | targets | reversals | 90 % CI | P(net<0) | ΣR | by (tf/side) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| no_veto | 19 | **−613** | 0.47 | 37 % | 12 | 6 | 1 | [−1 228, +30] | 0.94 | −6.3 | 15/long 8: −57; 15/short 9: −355; 60/short 2: −201 |
| **ma3** | 11 | **−74** | 0.85 | 55 % | 5 | 4 | 2 | [−597, +473] | 0.59 | −0.7 | 15/long 3: +247; 15/short 6: −120; 60/short 2: −201 |
| **ma5** | 6 | **−127** | 0.58 | 50 % | 3 | 1 | 2 | [−473, +220] | 0.69 | −1.3 | 15/long 3: +176; 15/short 2: −203; 60/short 1: −101 |
| ma3_all | 15 | +133 | 1.27 | 67 % | 5 | 10 | 0 | [−430, +709] | 0.34 | +1.3 | — |
| ma5_all | 8 | +20 | 1.06 | 50 % | 3 | 5 | 0 | [−386, +462] | 0.47 | +0.2 | — |

All marginal fires are rule 1 (in zone); none came through rule 2. Every marginal stop-out is a full −100 USDT
(the candle stop sits at the notional cap, 1 R): 12 of 19 under `no_veto`, 5 of 11 under `ma3`, 3 of 6 under `ma5`,
against a 46 % stop-out rate for the non-marginal positions.

### 4.2 Where the mode totals come from (same opening fire, current → mode)

| transition | ma3: n / Δ | ma5: n / Δ | no_veto: n / Δ |
|---|---|---|---|
| unchanged trades (stop→stop, target→target, reversal→reversal) | 129 / ≈ 0 | 133 / ≈ 0 | 120 / −235 (three reversals now close against a marginal fire) |
| current trade not opened (a marginal position was still held) | 6 / +36 (3 stops −297 avoided, 3 targets +261 lost) | 2 / +125 | 12 / +345 |
| **positions only in the mode (all on a vetoed side)** | **11 / −74** | **6 / −127** | **19 / −613** |
| net change vs current | **−38** | **−1** | **−503** |

## 5. Caveats

1. **2.4 days, one pair, one regime** (LINK 11.6–12.4). Six to nineteen marginal trades decide the comparison;
   their CIs include zero. The result is "no evidence the relaxed entries make money", not "they lose with
   certainty" — except for `no_veto`, whose P(net<0) is 0.94 on 19 trades.
2. **Stop rule held fixed** at today's candle stop for every mode, so the live window's actual P&L (+473, three
   stop rules) is not comparable with the rows; the comparison is mode-vs-mode under one rule.
3. **Entry at the fire trade's price** for every mode (live: book mid). Same bias on every row.
4. **Fees.** The paper account charges none. At 0.05 % per side on the ~50 000 USDT notional every mode is
   deeply negative (the "net −fee" column: ≈ −50 USDT per round trip against a median risk of 87). That is a
   property of the strategy's sizing, not of this question, and it applies to every row equally; it is reported
   because the user should see it next to any P&L number from this stack.
5. The first fire after each executor restart cannot be reproduced (the live σ is computed over an almost empty
   window); 6 of 152 fires. The sim is the more faithful of the two to the spec's intent.

## 6. Verdict

**Negative.** In overshoot-vetoed zone minutes the 3-min and 5-min trade-price MA classes admit 11 and 6
extra positions over 57.7 h, netting −74 and −127 USDT; the whole-system net is unchanged within noise
(+2 451 / +2 488 vs +2 489). Two mechanisms explain why nothing can be gained here:

- the veto removes minutes, not zones — with the once-per-zone rule the live check fires on the next passing
  minute of the same zone, so only 19 fires in 2.4 days are actually lost to it, and those 19 lose (−613 at the
  1-min class, P(net<0) 0.94): the veto is doing its job on this sample;
- a slower MA is not a different signal inside an in-zone minute: it agreed with the 1-min class at 11 of 12
  (ma3) fires, so `ma3_and ≡ ma3`. Used everywhere (`ma3_all`, `ma5_all`) the slower class is worse
  (+1 628 / +1 053 vs +2 489): it fires later and misses the targets the 1-min class catches.

No rule change recommended. If the idea is to be kept alive, the next arbiter is the same replay once the trade
store covers a few weeks (the marginal set grows ~8 trades/day) — or a different question: whether the
*overshoot depth* (the stored float `cb_overshoot_*`, not on the wire) sizes the stop better, which the frozen
p75 flag cannot answer.
