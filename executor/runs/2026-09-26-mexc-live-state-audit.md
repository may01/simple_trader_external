# Live state audit — MEXC futures LINK_USDT, 2026-09-26 11:40–15:17 UTC

Run: container `layer-implementation-executor-1`, trade_executor `mexc-live-m5` @ `5163899` (after the
I-1…I-6 fixes), `EXECUTION_MODE=live`, SAR test signal `1_sar_002_02`, leverage 1, isolated, one-way.
Window: boot 11:40:09 → snapshot 15:17:34. **18 round trips (9 long, 9 short), flat at the end.**

Sources:

| Side | Source |
|---|---|
| Exchange (what MEXC told us) | `position_event` (position stream), `order_event` (order stream + REST polls), `balance_event` (wallet) |
| System (what we stored) | `decision_log`, `signal_log`, `exchange_order` (order journal), `exchange_fill`, `position_log` / `position_current` / `position_history`, `reconciliation_log`, container log |

A direct read-only MEXC REST snapshot (history orders, deals, plan orders, history positions) was
**not taken**: the permission classifier refused it. "Exchange" below means the exchange's own
stream data as the executor received it. The script is ready if you want to run it yourself
(see *Not verified*).

## Verdict per question

| # | Question | Verdict |
|---|---|---|
| 1 | Orders executed correctly | 🟢 Entries, exits and stops filled at sane prices, on the lot/tick grid, with reduce-only on every stop and exit. 🔴 Two entries filled after the signal had flipped the other way (R1). |
| 2 | Decisions delivered to orders | 🟢 20 of 24 decisions became orders in 1.4–2.3 s. 🔴 4 decisions were silently dropped (R1). |
| 3 | Orders placed and stored correctly | 🟢 63 orders in the journal, ids match the exchange. 🔴 12 stop statuses wrong in the journal, `position_id` empty on every order (R4, R7). |
| 4 | Fills received and stored | 🟢 All 33 stored fills have the right price, fee and P&L. 🔴 4 more exit fills were received but never stored (R3). 🔴 One partial fill counted twice (R2). |
| 5 | Position updated on each action | 🟡 Fill, open, stop move and close are logged. Decision, order placement and stop cancel are not, and `Opening` is never persisted (R6). |
| 6 | State transitions | 🔴 Terminal rows lose `position_id`, so `position_history` shows all 18 closed positions as `open` or `closing` (R5). Reconciliation writes `Flat` over a working entry (R6). |
| 7 | Exchange vs DB drift | 🟢 Side, size and entry price agree for 18 of 18 positions, and the end state is flat on both sides. 🔴 Stored P&L is off by 0.0057 USDT. The stored state drops the live stop after every entry (R4). |
| 9 | Long vs short | 🟢 Both sides are symmetric: stop sides, P&L signs and prices are correct. Every defect below hits both sides equally (4 missing exits: 2 long, 2 short). |

---

## 🟢 Green — working correctly

- **Position size, side and entry agree with the exchange, 18 of 18.** Every `position_event` open
  (size, side, entry price) equals the local `avg_entry_price` / `net_size`. Final state: the exchange
  size is 0 at 15:16:53 and the local position is `Flat` at 15:16:54.
- **Wallet reconciles to the cent once the missing fills are added.** The wallet went from
  38.482926 (10:41, flat) to 38.198396 (15:16:53, flat), which is **−0.284530 USDT**. Stored fills
  net to −0.263311, and the 4 unstored exit fills from the order stream net to −0.021218. The sum is
  −0.284529. Every one of the 18 per-trade wallet deltas matches fills to within 1e-8. No funding
  charges fell in the window.
- **Fees are correct.** Taker is 0.0008 and maker 0.0006 of quote quantity, checked on every fill.
  `is_maker` agrees with the rate charged.
- **P&L signs are correct on both sides.** Examples: short 14.302 → 14.295 gives +0.0042, and long
  14.239 → 14.232 gives −0.0049. The local `realized_pnl` equals the exchange's per-fill
  `realized_pnl`.
- **Signal → decision → order is fast and deterministic.** Each of the 23 SAR flips produced a
  decision or a logged skip (11:51:06 same side, `position_already_open`). Decision to entry order
  took 1.7–2.3 s. Decision to exit order took 1.4–1.5 s.
- **Reversal sequencing is correct when the position is `Open`.** At 12:02:57 the flow was: Close,
  exit `x-3` filled at 12:02:59, then the new short entry at 12:03:02. There was never a net
  overlapping position.
- **Order hygiene.** Every stop and exit is `reduce_only=t`, and no entry is. Quantities are
  6 or 7 contracts (0.6/0.7 LINK, contractSize 0.1). Prices are on the 0.001 tick. There are no
  duplicate client ids and no duplicate fills: every fill arrives twice (websocket plus poll), and
  `exchange_fill` dedups it.
- **Initial stops are correctly placed.** The first stop is about 1 % away, above the market for
  shorts and below it for longs, on all 18.
- **Partial fills are handled in state.** The exit `x-3` at 14:55 filled 0.3 + 0.3.
  `PartiallyFilled` (net 0.3) came before `Filled` (net 0).
- **The I-1…I-6 fixes hold.** There were no stop re-place loops, no close-retry loops and no
  duplicate-client-id refusals. There was one stop move per trigger. I-2's position check closed
  4 positions cleanly, with no loop.
- **Leverage on the venue.** `position_event` shows leverage 1 on every position, and the
  liquidation price is far away (0.021 long, about 28.5 short).

## 🟡 Yellow — risks

- **Y1. The position is unprotected about 1.1 s after every entry and about 1.2 s on every stop
  move.** The stop is placed only after the entry fill. Every trailing move cancels first and places
  second. In total there were 103 s without an exchange stop over 1 646 s held (R8 accounts for 54 s
  of that).
- **Y2. Trailing stops are placed at or through the market.** Of 17 trailing moves, 8 had a trigger
  at or through the last trade (0 to −1.4 bps) and the rest were ≤ 13 bps away. The move usually
  comes 2–60 s after entry, so most trades end at about the entry price, and fees (about 0.14 %
  round trip) decide the result. **All 18 trades lost money net**, including the 7 with a positive
  gross P&L. The "breakeven" lock ignores fees. This is a strategy/config concern (`TRAILING_FRACTION`
  0.5 with the ≥ 0.1 % move gate), not a state bug. Profit is not locked.
- **Y3. SAR emits same-side flips.** 3 of 23 flips repeated the previous side (11:51:06, 14:56:59,
  15:10:39). At 14:56:59 this re-opened a short that had just been refused, which was an accidental
  retry.
- **Y4. A spot-spelling ghost pair is still loaded.** `position_current` still holds
  `LINKUSDT flat` from 09-25 (spot run), and a second reconcile loop reports `LINKUSDT
  no_discrepancy` every minute (192×) against nothing. The executor seeds it at boot. This is noise
  that looks like a clean check. `position_state` (the retired table) also holds a stale
  `LINKUSDT Flat`.
- **Y5. The local watcher sends event spam while `Closing`.** Position `d1b3105e` logged 38
  `StoppedOut` rows in 27 s while its exit rested, one per trade tick. Only one exit order was sent,
  so it is harmless on the venue, but it bloats `position_log` and hides real events.
- **Y6. Local futures metadata is empty.** Local `leverage`, `margin_type` and `liquidation_price`
  are `null` on every position, although the exchange reports them. Liquidation distance cannot be
  monitored from our state.
- **Y7. Metrics lose information.** `position_closed` and `position_realized_pnl` carry
  `side="none"`. `slippage_bps` is raw (fill − intended): favourable is + for sells and − for buys,
  so any cross-side average cancels. `position_realized_pnl` is gross and reports 0 for the 4
  drift-closed trades.
- **Y8. The account poll is flaky.** There were 6 `mexc_account_poll_error_count` warnings and REST
  errors on `open_positions` (12:22:16) and `account/assets` (14:54:12). None had a visible effect,
  but a failed position check during I-2's "is it gone?" path returns `false`, which keeps a ghost
  position.
- **Y9. `position_event.exchange_ts` is `NULL` on every row.** Exchange-to-receive latency cannot be
  measured, and event ordering relies on receive time only.
- **Y10. `take_profit_price` is stored but never placed.** For example, 14.629 on `fbe84c8c`. No TP
  order exists on the venue, so if TP is meant to be local-only, it does not survive a restart. Not
  reached in this window, not verified.

## 🔴 Red — misalignment / wrong behaviour

### R1. A stale entry fills after the signal flipped; the opposite decision is dropped

Seen twice, one hour apart, on both sides:

| Entry | Rested | Opposite decisions refused while it rested | Result |
|---|---|---|---|
| long `x-83c1…-e-1` 12:58:41 @14.186 | **13.7 min** | Sell 13:11:01 | filled 13:12:25 against SAR, stopped 54 s later |
| short `x-84a9…-e-1` 14:57:01 @14.376 | **19.8 min** | Buy 15:09:27, Buy 15:10:39 | filled 15:16:48 against SAR, stopped 5 s later (−0.0087 net) |

Also, 14:55:06 Open/Sell was refused while the long was `Closing`.

Cause, from the code:
- The signal guard (`orchestrator/src/system.rs:1063`) treats anything other than
  `PositionStatus::Open` as flat. With `Opening`, it emits a plain **Open** in the opposite
  direction instead of a reversal (Close + Open).
- The executor then refuses it with "a position is already open on this pair", and nothing cancels
  the resting entry.
- `SIGNAL_MAX_WAIT_SECS=300` is only carried on `SignalAction::Open.max_wait`. `execution` never
  reads it, so entries have **no time-to-live**.

4 of 24 decisions produced nothing. The refusal is logged only as a `not_placed` row on the *other*
position (the resting one), with no `decision_id`.

### R2. A partial exit fill is double-counted in P&L and fees

Position `fbe84c8c` (long 0.6 @14.428, exit `x-3` 14.385, filled 0.3 + 0.3):
- Exchange: pnl −0.0258, fees 0.012104. Wallet delta −0.037904 ✔.
- Stored `Closed`: pnl **−0.0387**, fees **0.014693**. The first 0.3 fill (−0.0129 pnl, 0.0025893
  fee) is counted twice.

### R3. Exchange-stop fills are received but not stored (4 trades, 2 long / 2 short)

When the exchange stop and the local watcher fire together (I-8), the plan order's child order
(`f:…`) fills. The order stream delivers it, but it never reaches `exchange_fill`, and the position
is closed by I-2's "exchange holds no position" path with pnl 0 and entry fees only.

| Position | Side | Exit seen in `order_event` | Missing pnl | Missing fee |
|---|---|---|---|---|
| 47104257 | long | 12:21:00 sell 0.7 @14.259 | −0.0007 | 0.007985 |
| b039962e | short | 12:25:41 buy 0.7 @14.243 | 0 | 0.007976 |
| d266ed16 | long | 13:13:18 sell 0.7 @14.199 | +0.0091 | 0.007951 |
| 88b07f51 | short | 14:36:04 buy 0.6 @14.388 | +0.0012 | 0.006906 |

In all 4 cases the local exit (`x-4`/`x-5`) was refused with `2009`. Its limit price equals the
stop's own fill print: the watcher fired on the trade the exchange stop created. The ledger misses
−0.021218 USDT, and together with R2 the stored session P&L is **−0.278800 vs −0.284530 on the
wallet**.

### R4. Reconciliation deletes the live stop from the stored state after every entry

`reconciliation_log` holds 11 `stale_order` entries, one per position, each about ≤ 60 s after the
stop was placed, with `truth_status: null`. The adapter says so itself (`futures.rs:648`): *"Plan
(stop) orders are not in this list"*. Yet `state_store` treats a stop's absence from `open_orders`
as proof that it is gone. The "correction" clears the stop from the stored state.

Example: at 14:43:17 the stored `fbe84c8c` became `Open` with `orders=[Entry]` only, while the
exchange stop `p:…858839902597564928` was live (last stream status `new`, until it was cancelled at
14:55:07). The running executor kept it in memory (I-7), so trading was unaffected. See the restart
dry-run for the impact.

### R5. Terminal position rows lose their identity; `position_history` is wrong

All 36 `filled`/`closed`/`stopped_out` rows with status `flat` have `position_id`, `side`, sizes,
prices and pnl `NULL` in their columns (the values are only inside `event_detail`).
`position_history` takes the last row *that has* a `position_id`, so it lists **14 closed positions
as `open` and 4 as `closing`**, with `realized_pnl=0` and no exit price. `decision_id` and
`signal_id` are `NULL` on every position row.

### R6. `Opening` is not persisted, and reconciliation flattens a working entry

- There is no `position_log` row between decision and entry fill. The first row appears either at
  the fill (`filled`, status `opening`) or when an opposite decision is refused. The visualiser and
  any restart see `Flat` while an entry rests (root cause of I-9, and the input to R1).
- At 13:11:17, 15:10:17 and 15:11:17, `extra_locally` wrote `Flat` over an `Opening` position
  whose entry order was resting on the venue. The entry then filled anyway, giving a stored
  `Flat → Filled(Entry)` sequence with no open.

### R7. The order journal disagrees with the exchange on stop orders

- 12 journal/stream status mismatches, all stops. The journal says `filled`, while the plan order's
  last stream status is `new` (MEXC never streams "executed" for plan orders; the fill arrives on
  the child `f:` order).
- 4 more stops are stuck at `new` in the journal forever (`b159…-s-3`, `9bda…-s-3`,
  `83c1…-s-4`, `9a95…-s-3`) although they executed. A "resting stops" query would count 4 phantoms.
- 12 exchange child orders (`f:…`) created by stop triggers do not exist in the journal at all.
- `exchange_order.position_id` is `NULL` for all 63 orders. The link to the position survives only
  inside the client-id suffix.

### R8. A local-watcher or signal close leaves the position without an exchange stop

When closing by limit order, the executor cancels the exchange stop before the exit fills:
- `d1b3105e` (long): stop cancelled at 13:20:37, and the exit limit at 14.232 rested **28.6 s**
  while trades printed down to 14.220.
- `fbe84c8c` (long, main close): stop cancelled at 14:55:07, and the exit rested **25.4 s** (partial
  at +21 s).

For those windows, nothing on the venue limited the loss.

---

## Extra checks (item 8)

| Check | Result |
|---|---|
| Wallet-ledger reconciliation | Done, see Green and R2/R3. Wallet = fills + 4 unstored fills, exact. |
| Stop coverage windows | 103 s unprotected over 18 positions. Entry→stop is about 1.1 s each, cancel→replace about 1.2 s per move, and the limit-close handoffs were 28.6 s and 25.4 s (Y1, R8). 8 of 17 trailing stops were at or through the market (Y2). |
| Journal vs exchange stream | 12 status mismatches, 12 orphan child orders, 4 phantom `new` stops, and `position_id` empty everywhere (R7). 4 rejected local exits have no stream entry, which is expected (refused at REST). |
| Signal → decision completeness | 23 flips produced 24 decisions and 1 logged skip, with none lost upstream. 4 decisions were dropped at the executor (R1). 3 same-side flips (Y3). |
| Restart seeding (code-read, not executed) | Boot runs `state_store::reconcile`, which deletes the stop as in R4, and then seeds `position_current`. A restart during an open position would seed `Open` with no stop. `upkeep_stop` re-places a stop only if one is `lost` (it tracks none) or older than `STOP_RENEW_AFTER` = 6 days. So the executor would run **unaware of the live exchange stop**: the next trailing move adds a second stop, and a trigger of the old one lands in R3. `LINKUSDT` (spot, flat) is seeded too (Y4). Right now both rows are `flat`, so a restart at 15:17 would be safe. |

## Not verified

- **Direct exchange snapshot.** Run it yourself:
  `/tmp/claude-1000/-home-om-projects-simple-trader/b7bfd340-5884-440a-9423-8bcb3136f1e3/scratchpad/mexc_ro.py`
  (GET only: open/history positions, open/history orders, deals, plan and stop orders, asset,
  position mode). It reads `K`/`S` from the environment and writes `mexc.json`. This would confirm
  that no stray plan orders are resting now and give the exchange-side realized P&L of the 4 missing
  exits.
- TP semantics (Y10).
- The 10:28–11:40 pre-fix session, covered by I-1…I-9.

## Suggested fix order (not implemented)

1. R4 + R6: reconciliation must read plan orders and must treat `Opening` with a live entry as
   legitimate. Until it does, it destroys the state a restart depends on.
2. R1: an opposite signal while `Opening` should cancel the entry (a reversal of a pending entry),
   and entries need a TTL (`max_wait` wired into execution).
3. R3/R7: map plan-order child orders (`f:`) back to their stop, and poll fills before I-2 closes
   locally (the fix proposed in I-8).
4. R2: make fill accounting idempotent per `trade_id`, not per order-update.
5. R8: keep the exchange stop until the exit fills, or exit with a marketable/IOC order.
6. R5: write `position_id` and the full columns on terminal rows, and link `decision_id` and
   `signal_id`.
