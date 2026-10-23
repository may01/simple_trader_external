# Replay: release_001 stop rule vs the running candle stop, since the pivot (2026-10-20 20:21Z → 2026-10-21 19:40Z)

Date: 2026-10-21. Question (user): *take the release_001 implementation and compare it with the current run — how
much would the profit differ from the pivot point?*

**Pivot** = the live paper executor's restart on `cb-candle-stop` (`a6a5bc6`) at **2026-10-20 20:21:47Z**
(`docker inspect` StartedAt of `cbov-check-executor-1`). Before it the stack ran `release_001` (`1689dc5`):
order-book stop + 1 % placeholder. Since it: forming-15-min-candle stop ∓ trailing mean 1-min range + 0.2 %
placeholder. Everything else (zones, entry rules, target/trend-flip exit, reversal, sizing, env) is identical.

Data: `cbov-check` postgres (`localhost:5436`), 23.4 h of `trade` (180 995), `signal_log` CbZoneEntry (62 fires),
`position_log` (58 positions, all closed), `book_snapshot` (4) + `book_update` (80 041, no `book_gap` row).
Script: [`2026-10-21-rel001-vs-candle-stop-replay.py`](2026-10-21-rel001-vs-candle-stop-replay.py) (numpy only;
export SQL = the `COPY` statements in the run notes below). Outputs: [main](2026-10-21-rel001-vs-candle-stop-replay-output.txt),
[fill at the stop level](2026-10-21-rel001-vs-candle-stop-replay-output-fill-at-stop.txt),
[book lag 170 ms](2026-10-21-rel001-vs-candle-stop-replay-output-lag170.txt),
[book lag 1 000 ms](2026-10-21-rel001-vs-candle-stop-replay-output-lag1000.txt).

## 1. What the replay does

The 2026-10-20 sl-15m harness, run the other way round: the recorded fires drive an event-driven simulation
(flat → open at the recorded entry, same-side fire skipped, opposite fire = reversal at the fire price, stop
watcher on every trade, target exit = extreme past `target` then the opposite 10-s trend class, size =
`min(100 / dist, free × 0.5 / entry)`, no fees), and only the stop differs:

- **live** — the candle stop the executor recorded on the fire (`stop` on the CbZoneEntry event), 0.2 % fallback;
- **rel001** — the order-book stop **rebuilt** from the stored book: `book_snapshot` + `book_update` applied in
  `ins_seq` order (a `BookTracker` port, qty 0 removes a level), adverse-side volume per minute over the last
  300 s of trades (count-bounded 6 000-trade window), `minutes_left = max(E − streak, 0) + 1` with
  `E = 15:2 / 60:3 / 240:4` and the streak the event recorded (`inzone_streak`, same `Streaks` code in both
  builds), walked from the firing trade, strictly beyond the trade and the touch, else the **1 %** placeholder;
  also the builder's rule "stop not adverse to the actual entry → placeholder";
- two decompositions: **book_p02** (book stop, 0.2 % placeholder) and **candle_p1** (candle stop, 1 % placeholder).

## 2. Gates

| Gate | Result |
|---|---|
| Reproduction of the live run | sim-live opens the same 58 positions: **stop exact 58/58, size within 1 % 58/58, same close reason 57/58** (one reversal the sim closed 1 trade later as a stop) |
| Fill model | live actual **+240.37**, sim-live −18.51 (crossing-trade fill) / +34.30 (fill at the stop level). Gap = the paper mid-fill: the 30 live stop-outs filled a mean 2 ticks (≈ 8.4 USDT at ~4 050 LINK) better than the crossing trade (252 of the 259 USDT gap sits on the stops). Same model on both sides of every comparison below. |
| Book rebuild | at the 58 live opens the rebuilt mid is within 1 tick of the recorded entry (= the live book mid on the grid) for 51/58, median offset 0, max 6 ticks; rebuilt spread at the fire median 1 tick; the firing trade sits on the rebuilt best bid/ask in every row of the per-fire table |
| Book timing | updates applied at `exchange_ts` (main run); at +170 ms (the observed recv lag) and +1 000 ms (one diff-stream interval) as sensitivity, §3 |
| Shape check against the release era | rebuilt release stops: median **5 ticks**, 13/55 opens on the placeholder (24 %) — the pre-pivot live run had median 3 ticks and 16/68 placeholders (24 %) |
| Null floor | per-fire paired bootstrap of the difference, 5 000 draws, §3 |
| Trend-class port | unchanged from the 2026-10-20 harness (13/14 logged target exits reproduced there) |

## 3. Results (23.4 h, 62 fires; stop fills at the crossing trade unless stated)

| rule | trades | net | gross win (n) | gross loss (n) | win rate | PF | stop-outs n / mean | targets | reversals | median hold | median risk/trade | stop dist. median | 90 % CI | P(net<0) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **live** candle stop + 0.2 % | 58 | **−19** | +2 215 (27) | −2 234 (31) | 47 % | 0.99 | 30 / −74 | 17 | 11 | 7.3 min | 74.5 | 18 ticks (0.149 %) | [−1 061, +1 018] | 0.52 |
| **rel001** book stop + 1 % | 55 | **+422** | +1 150 (21) | −729 (34) | 38 % | 1.58 | 31 / −21 | 15 | 8 | 3.4 min | 22.3 | 5 ticks (0.045 %) | [−160, +1 042] | 0.12 |
| book stop + 0.2 % | 59 | +366 | +1 695 (19) | −1 329 (40) | 32 % | 1.28 | 40 / −33 | 13 | 6 | 3.0 min | 22.2 | 5 ticks | [−475, +1 240] | 0.24 |
| candle stop + 1 % | 58 | −19 | = live | | | | | | | | | | | |

Actual recorded live P&L over the window: **+240.37** (30 stops −1 973.91, 18 targets +1 056.46, 10 reversal
closes +1 157.82). With the same fill advantage the release rule would have recorded roughly **+240 + Δ**.

**Δ (release_001 − live), same fill model:**

| variant | Δ net | paired 90 % CI | P(Δ<0) | first / second half | tf 15 / 60 / 240 |
|---|---|---|---|---|---|
| main (book at exchange_ts, crossing-trade fill) | **+440** | [−442, +1 267] | 0.20 | +89 / +351 | +203 / +161 / +76 |
| fill at the stop level | +387 | [−489, +1 208] | 0.22 | +63 / +324 | +162 / +151 / +74 |
| book lag 170 ms | +269 | [−629, +1 124] | 0.30 | | |
| book lag 1 000 ms | +133 | [−762, +985] | 0.39 | | |
| stop rule alone (book + 0.2 % − live) | +385 | [−515, +1 274] | 0.24 | +136 / +249 | −95 / +404 / +76 |
| placeholder alone (candle + 1 % − live) | 0 | — | — | the candle stop never fell back in this window (58/58 candle) | |

Where it comes from (main run, same opening fire):

| transition live → rel001 | n | live | rel001 | Δ |
|---|---|---|---|---|
| stop → stop (still stopped, 5-tick instead of 18-tick loss) | 22 | −1 611 | −526 | **+1 085** |
| stop → reversal / target / not opened / open at end | 8 | −615 | −4 | +611 |
| reversal → **stop** (the tight stop hit before the reversal came) | 6 | +612 | −101 | **−713** |
| target → not opened (position still held, fire skipped) | 2 | +234 | 0 | −234 |
| target → target (same exit, 1 % placeholder size one-fifth on 4 of them) | 13 | +718 | +589 | −129 |
| reversal → reversal, target → stop, others | 8 | +494 | +464 | −30 |

The release rule gives back the same thing it gave on its own day: smaller stop-outs (−21 vs −74 mean, risk per
trade 22 vs 75 USDT) at the price of stopping six of the live run's eleven profitable reversals and two of its
targets. In R-multiples the two are far apart (live +0.8 R over 58, rel001 +50 R over 55) because the
5-tick stop makes every target exit a 10–20 R trade — the same risk-sizing artefact the 2026-10-20 report
warned about (its §5.2), now with the sign reversed.

## 4. Put next to the pre-pivot replay (2026-10-20, 21 h, 68–71 fires)

| window | book stop | candle stop (as implemented) | Δ candle − book |
|---|---|---|---|
| 2026-10-19 22:43Z → 10-20 19:18Z (book stop live) | +1 087 (0.2 % ph.) / +145 (1 % ph.) | +1 878 | **+791** |
| 2026-10-20 20:22Z → 10-21 19:40Z (candle stop live) | +366 (0.2 % ph.) / +422 (1 % ph.) | −19 | **−385 / −440** |

Two consecutive days, opposite sign, both 90 % CIs containing 0. The candle stop was adopted on a day where
wide stops survived the shake-outs; the next day the shake-outs ran through 18 ticks as readily as through 5,
and the only thing the wider stop changed was the size of the loss. Neither day distinguishes the rules.

## 5. Caveats

1. **Paper fill bias** (§2): live stop fills ≈ 2 ticks better than the crossing trade; the replay is sim-vs-sim.
2. **The rebuilt book is not the executor's book.** Updates are applied at `exchange_ts`; the executor applied
   them ~170 ms later and the check ran on the trade's arrival. 7/58 entries sit > 1 tick from the rebuilt mid.
   The Δ moves from +440 to +269 (170 ms) and +133 (1 000 ms) — the book stop walks 1–8 levels, so a 1-s-stale
   ladder lands on a different tick often enough to move the sum by ±300. The sign does not change.
3. **Streak** comes from the live event (`inzone_streak`); the release build counted it the same way from the
   same wire, and after the restart both counters started at 0 (first fire 5 min after boot).
4. **Risk per trade differs 3×** between the rules (22 vs 75 USDT median); net USDT is mostly a sizing statement.
5. 23 h, one pair, one regime (LINK 12.2 → 12.7, one 3 % up-move in the last 5 h where the live run's wide
   stops took −100 USDT hits at 18:53 and 19:17).

## 6. Verdict

**Not decidable; partial.** Over the 23.4 h since the pivot the release_001 rule (order-book stop, 1 % placeholder)
would have made **≈ +440 USDT more** than the running candle stop under the same fill model (+422 vs −19;
+387 at stop-level fills; +133 … +440 depending on the assumed book staleness), on a 100 000 USDT paper balance,
inside a paired 90 % CI of [−442, +1 267] (P(Δ<0) 0.20). The previous day's replay said the opposite by +791.
Nothing here justifies reverting; nothing here confirms the candle stop either. The fair arbiter stays what the
2026-10-20 report asked for: a second paper stack side by side (`CB_STOP_MODE=book` is still in the code) or a
week of replay once the trade/book store covers it.

## Run notes (export)

```sql
-- P = 1792527707000 (2026-10-20 20:21:47Z), psql -h localhost -p 5436 -U executor trader
COPY (select ord_ts, price, qty, case when side='buy' then 1 else -1 end, recv_ts from trade where ord_ts>=P order by ord_ts, trade_id) TO STDOUT WITH CSV;                      -- trades.csv
COPY (select row_to_json(r) from (select seq, decision_id, ts, record->'CbZoneEntry' as ev from signal_log where ts>=P and record ? 'CbZoneEntry' order by ts, seq) r) TO STDOUT;  -- events.jsonl
COPY (select row_to_json(r) from (select seq, position_id, event, status, side, target_size, net_size, intended_open_price, avg_entry_price, avg_exit_price, stop_loss_price, take_profit_price, realized_pnl, close_reason, decision_id, signal_id, recorded_at from position_log where recorded_at>=P order by seq) r) TO STDOUT;  -- positions.jsonl
COPY (select row_to_json(r) from (select ins_seq, seq, exchange_ts, recv_ts, bid_prices as bp, bid_qtys as bq, ask_prices as ap, ask_qtys as aq from book_snapshot where recv_ts>=P order by ins_seq) r) TO STDOUT;  -- book_snapshots.jsonl
COPY (select row_to_json(r) from (select ins_seq, seq, exchange_ts, recv_ts, bid_prices as bp, bid_qtys as bq, ask_prices as ap, ask_qtys as aq from book_update where recv_ts>=P order by ins_seq) r) TO STDOUT;    -- book_updates.jsonl
```

`book_update.seq` restarts at 1 after every snapshot (4 resyncs in the window); `ins_seq` is the global order.
Reversal opens ride a fresh decision id: the harness matches them to the last same-side fire within 5 s.
