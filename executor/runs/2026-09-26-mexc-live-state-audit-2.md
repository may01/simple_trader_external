# Live state audit 2 — MEXC futures LINK_USDT, 2026-09-26 20:18–22:13 UTC

Follow-up to [audit 1](2026-09-26-mexc-live-state-audit.md) (11:40–15:17). Same method and checks.

Run: image built 19:39 UTC from `mexc-live-m5` @ `d326de5`. It contains I-10…I-16 (fixes for R1–R8
of audit 1); `ab6a51d` is visualiser-only. The executor started 20:18:41, the DB was wiped before it
(`runs/2026-09-26-pre-wipe-trader.dump`), and the schema is 11. Config is unchanged from audit 1
(SAR test signal, leverage 1, isolated, `SIGNAL_MAX_WAIT_SECS=300`, `TRAILING_FRACTION=0.5`).
Window: 20:18:41 → snapshot 22:13.
**7 positions: 6 round trips (3 long, 3 short), 1 entry expired unfilled, 1 short still open**
(0.7 @ 14.041, stop 14.18).

Sources are the same as in audit 1. "Exchange" means MEXC's own stream and poll data as stored
by the executor (`position_event`, `order_event`, `balance_event`). A direct REST snapshot was
again not taken, because the permission classifier refused it in audit 1.

## Verdict per question

| # | Question | Verdict |
|---|---|---|
| 1 | Orders executed correctly | 🟢 All 17 orders were on the grid and reduce-only where required. Stop-outs exit at market, and the TP limit filled. |
| 2 | Decisions delivered to orders | 🟢 10 of 10 decisions became orders. The reversal Open waits for flat; one entry expired by TTL, as designed. |
| 3 | Orders placed and stored correctly | 🟢 17 orders, every one with `position_id`. 🟡 2 plan-stop statuses differ from the stream, explained below. |
| 4 | Fills received and stored | 🟢 13 of 13 fills stored, including an exchange-stop fill that won the race. The fill ledger matches the wallet exactly. |
| 5 | Position updated on each action | 🟢 `entry_placed`, fill, open, stop move, target/stop, fill and closed are all logged. 🟡 A stray event is logged after close (N1). |
| 6 | State transitions | 🟢 `Opening→Open→Closing→Closed` holds on every position, and expiry gives `Opening→Closed(NotFilled)`. 🔴 One position ends as `flat` with no data in `position_history` (N1). |
| 7 | Exchange vs DB drift | 🟢 None. 0 reconciliation discrepancies in 104 runs. P&L and fees match to 1e-8, and the stored open state includes its live stop. |
| 9 | Long vs short | 🟢 Symmetric. The open, exit, P&L and fee values match on all 3 longs and 3 shorts. |

---

## 🟢 Green

- **No drift at all.** Side, size and entry match the exchange on 7 of 7 positions. Exchange-flat
  to local-closed takes 1–4 s. `reconciliation_log`: `LINK_USDT` gave 104 `no_discrepancy` and
  no `stale_order` or `extra_locally` (audit 1 had 11 + 5).
- **The wallet reconciles exactly.** 37.904178 (20:29, flat) → 37.906418 (22:02, flat) is
  **+0.002240 USDT**. Stored fills net +0.0847 pnl − 0.08246 fees, which is +0.002240. For each
  position, stored `Closed` pnl and fees equal the sum of its fills (difference 0.0000 on all 6).
  This is the first positive session: the TP trade `8bbb4a5a` made +0.105.
- **I-10 is verified** (stale entry / reversal):
  - Reversals at 20:37:39 and 21:15:12 went Close decision → exit order +0.5 s → exit fill →
    Open decision (logged only after flat) → new entry at +12.9 s and +19.4 s.
  - No entry filled against the signal.
  - TTL: the Buy entry `x-a04f…-e-1` (21:15:31) was cancelled at 21:20:32, exactly 300 s later,
    and logged as `not_filled` → `closed`.
  - Same-side flip at 22:11:20 → `signal_firing_skipped position_already_open`.
  - Every position row carries `decision_id` and `signal_id`.
- **I-11 is verified:** P&L and fees are equal per fill; no double counting. The window had no
  partial fills, so the partial-fill path specifically was not exercised.
- **I-12 is verified.** At 20:54:58 on `286f684b` (long) the exchange stop won the race and the
  local market exit was refused with `2009`. The stop's child fill (13.949) was stored under `s-3`
  with pnl +0.0007 and fee 0.00781144, the position closed as `stop`, and the P&L is complete. There
  was no `PositionDrift` alert.
- **I-13 is verified.** The stored `Open` for the current short holds its stop
  `p:…858950655673522176` (status New, `stop_leg=exchange`). A restart now would seed the stop.
- **I-14 is verified** (mostly). `exchange_order.position_id` is set on 17 of 17 orders and every
  fill joins to its position. `position_history` shows 6 `closed` with side, exit price and P&L.
  The exception is N1.
- **I-15 is verified.** Every entry writes `entry_placed` (status `opening`). No reconciliation
  flattened a resting entry, including one that rested 5 min.
- **I-16 is verified.** The exchange stop stays until the exit fills: stop cancelled 1–2 s after the
  main-close fill (20:37, 21:15), 1 s after the TP fill (20:47) and 1 s after the market
  stop-out (21:34). At 22:02 the stop itself triggered, and its child was refused (Y1). No close-handoff gap. Total unprotected time was **18.9 s over 2 191 s held**,
  down from 103 s over 1 646 s: only entry → first stop (about 1.1 s) and cancel → replace per move
  (about 1.2 s). This also answers I-16's open question: **MEXC accepts a reduce-only limit exit
  beside a full-size reduce-only stop** (`x-3` at 20:37:40 and 21:15:12 and the TP `x-8` at 20:47:21
  were all placed and filled with the stop resting).
- **TP works.** `8bbb4a5a`: 6 trailing moves in profit, then `target_hit` at 13.927, and the limit
  13.925 filled at 13.923.
- **Behaviour during the outage.** MEXC 504s and websocket TLS failures ran 22:07:07–22:09:54,
  with REST stale up to 49 s. Alerts fired (`FeedStale`, `FeedDisconnected`,
  `OrderPlacementFailed … retrying`). The open short stayed protected by its exchange stop. The
  websockets re-logged in and trades flowed again (last trade 22:12:57). There were no false
  closes and no drift after recovery.
- **Metrics now carry the side** (`position_closed`, `position_realized_pnl`), and the new
  `position_hold_secs` is present.

## 🟡 Yellow

- **Y1. The I-8 race still happens,** safely. 2 of 3 stop-outs had both legs fire:
  - `286f684b`: the exchange won and the local `x-4` market exit was refused (`2009`).
  - `b68bd446`: the local market exit `x-5` won, and the exchange's child order
    `f:…858950457048058368` was **rejected**.

  Reduce-only prevented a double close both times, and accounting is correct. Each costs one
  refused order.
- **Y2. The journal and the stream disagree on 2 plan stops,** by design. MEXC never streams
  "executed" for a plan order: `286f…-s-3` shows journal `filled` against stream `new`, and
  `b68b…-s-4` shows journal `rejected` against stream `new`. The journal is the correct side. Note
  that `rejected` on `s-4` means "triggered, child refused", not "never accepted". 2 child `f:`
  orders are not journalled as their own rows (their fills are, under the stop).
- **Y3. Trailing stops are still tight.** 2 of 10 moves were set at the last trade price (0 bps):
  `1f1d…-s-3` and `b68b…-s-3`. Four more were within 0.7 bps. They did not fire instantly (b68b's
  lasted 4 min 41 s; MEXC likely triggers on a different price), so this is not a defect, but
  breakeven stops still ignore fees. The 3 stop-outs made +0.0007, +0.0007 and +0.0098 gross but
  were net negative.
- **Y4. The spot ghost pair is still there.** `position_current` holds `LINKUSDT flat` (seq 4253,
  20:06:02). A `LINKUSDT` reconcile loop ran 114× against nothing. A `LINKUSDT` Open/Buy decision at
  20:06:01 (a boot before this one, logs gone) was refused with "computed size exceeds account
  limits". Something still sends or builds decisions under the spot spelling.
- **Y5. The spot base URLs point at Binance.** `REST_BASE_URL=https://api.binance.com` and
  `WS_BASE_URL=wss://stream.binance.com:9443` come from the compose defaults
  (`docker-compose.yml:186`), because `EXCHANGE_REST_BASE_URL` was not set for this launch (audit 1
  had MEXC). 0 spot requests were made (all 12 113 are `futures`). But any spot-surface call would
  send the MEXC API key and signature to Binance. Set the MEXC values, or fail boot on an
  exchange/URL mismatch.
- **Y6. Local futures metadata is still empty.** `leverage`, `margin_type` and `liquidation_price`
  are `null` on every position. The exchange reports leverage 1 and liquidation 0.02 (long) or
  about 28 (short).
- **Y7. Duplicate `StoppedOut` events.** `b68bd446` logged 2 rows 1 ms apart (stop 14.053, 14.052).
  Only one exit was sent.
- **Y8. `position_event.exchange_ts` is still `NULL`** on all 15 rows.
- **Y9. Reversal re-entry gives up after the TTL.** At 21:15:29 the Buy entry (limit 14.000,
  intended price) never filled and expired. The SAR said Buy for 18 min, but the pair stayed flat
  until the next flip. This is as designed; it is a strategy note, not a defect.

## 🔴 Red

### N1. A `StoppedOut` logged after `Closed` overwrites the position's last row with an empty one

`286f684b` (the I-12 race where the exchange stop won):

```
20219  20:55:02.386  filled       open    (Stop fill booked)
20220  20:55:02.388  closed       closed  pnl 0.0007, fees 0.01562232, exit 13.949   ✔
20221  20:55:02.389  stopped_out  flat    position_id set, side/size/prices/pnl NULL
```

`position_history` takes the last row per `position_id`, so it shows this position as **`flat`
with no side, exit or P&L**. `decision_id` is empty on that row too. The local watcher's
`StoppedOut` is reported after the booked stop close. I-14's `from_change` attaches the id but, with
the pair already `Flat`, no columns. Only the history view is wrong: the `Closed` row, fills and
wallet are correct. Fix direction: don't report `StoppedOut` once the position is closed, or build
the row from the finished position, as for `Closed`.

---

## Extra checks (same four as audit 1)

| Check | Result |
|---|---|
| Wallet ledger | Exact: +0.002240 wallet = +0.002240 fills. Per position, stored = fills on 6 of 6. |
| Stop coverage | 18.9 s unprotected over 2 191 s (0.9 %); no gap longer than 1.3 s. 1 % initial stops on 7 of 7. 2 of 10 trailing moves at 0 bps (Y3). |
| Journal vs exchange stream | 2 plan-status differences (Y2), 1 rejected local exit with no stream entry (expected), 2 un-journalled child orders (fills booked). 0 fills missing. |
| Signal → decision completeness | 9 SAR flips in this run: 8 produced 10 decisions (2 reversals), 1 same-side skip. 10 of 10 decisions produced orders in 0.5–1.8 s (reversal Open +12.9 s and +19.4 s after the flip, because it waits for flat). 0 dropped. |
| Restart seeding (code-read) | `position_current`: `LINK_USDT open` with its stop tracked (I-13 fix), plus the ghost `LINKUSDT flat` (Y4). A restart would now resume the short with its live stop. |

## Not verified

- A direct MEXC REST snapshot (script `mexc_ro.py` from audit 1, for you to run).
- Partial fills (none in this window).
- The 20:06 boot (its container logs are gone).

## Proposed next checks (item 8)

1. **Controlled restart** with the short open: confirm it seeds the stop and places no duplicate.
2. **Race rate for I-8**: over a longer run, count double-fired stops and the cost of refused
   orders.
3. **Fee-aware breakeven**: replay the trailing advisor on this window's trades with the stop at
   entry ± round-trip fees.
4. **Outage replay**: check that no decision arrived and no stop moved while REST was down
   (22:07–22:09), and measure how long the local watcher was blind.
