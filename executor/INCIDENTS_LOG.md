is # Incidents log — trade executor

Bugs seen in live runs, with what was done about them. Position reconciliation and state drift
only; open design follow-ups live in [TECH_DEBT.md](TECH_DEBT.md). Newest first.

Commits refer to trade_executor branch `mexc-live-m5`.

**Deploy 2026-09-26 ~20:00 UTC:** `mexc-live-m5` @ `d326de5` (I-10–I-16 all merged) built and
started on a wiped DB (schema 11); pre-wipe dump in
[runs/2026-09-26-pre-wipe-trader.dump](runs/2026-09-26-pre-wipe-trader.dump). Came up in
`EXECUTION_MODE=no_trade` on the default compose env; the fixes are not yet verified live.

---

## 2026-09-26 — MEXC futures, LINK_USDT, live (SAR test signal, 0.6–0.7 LINK)

Two trades at 10:28–10:41 UTC, then 20 minutes of the executor holding a position MEXC had
already closed. Exchange stayed safe throughout: every extra order was reduce-only or refused.
After the fixes, eight round trips from 11:49 UTC ended flat.

### I-1. A close was undone by a concurrent stop move (lost update)

**Seen:** the local stop-loss watcher placed an exit (`x-8`) and marked the position `Closing`; a
trailing-stop move running at the same time stored its older `Open` copy over it. The exit filled on
MEXC, but the position no longer referenced it, so the executor kept the position open.
**Cause:** every task cloned the position, awaited the exchange, then stored its clone back — last
writer wins.
**Fix:** per-pair async lock around every read-modify-write that talks to the exchange
(`open_position`, `do_close`, `apply_stop_loss_move`, `poll_orders`). Regression test fails without
the lock. `5163899`. **Status:** fixed, verified live.

### I-2. Position outlived the exchange's: stop re-place and close-retry loops

**Seen:** with the stale local position, MEXC cancelled every reduce-only stop at once (no
position), the executor re-placed it ("stop disappeared without being cancelled here") about every
second; the local watcher retried the close and got `2009 Position is nonexistent or closed` on every
trade tick. ~70 stop orders in 15 minutes.
**Cause:** nothing asked the exchange whether the position still existed.
**Fix:** on futures, a refused close or a stop the venue dropped triggers a position check; if the
exchange holds none, the position is closed locally (`Closed` + `PositionDrift` alert, P&L marked
incomplete). `5163899`. **Status:** fixed, verified live (fired twice, no loop).

### I-3. Client order ids reused after a failed close

**Seen:** `duplicate client_order_id x-…-x-77` refused by the order journal on every retry.
**Cause:** a failed close did not store the position, so its order-id counter went back.
**Fix:** the position is stored on failure too (close and exit retry). `5163899`. **Status:** fixed.

### I-4. An exchange stop fill did not flatten an Open position

**Seen:** trade A's plan-order stop executed at 14.095; the executor kept the position open until
reconciliation happened to clear it.
**Cause:** `finish_close` only finished a `Closing` position; a stop fill on an `Open` one was
ignored.
**Fix:** a stop fill that takes an `Open` position to zero closes it (`Closed`, reason `Stop`).
`5163899`. **Status:** fixed, verified live.

### I-5. Journal recorded a triggered stop as Cancelled

**Seen:** `OrderJournalBackwardTransition … Cancelled -> Filled` for stop `s-7`.
**Cause:** MEXC answers a plan-order cancel with success even when the order has already
triggered.
**Fix:** the MEXC adapter reads the plan order back after cancelling; an executed one returns
`OrderNotCancellable`. `5163899`. **Status:** fixed.

### I-6. Trailing stop moved on every trade tick

**Seen:** one cancel-and-replace per second (+0.001 each), hitting the adapter's rate limit and
widening the window for I-1.
**Fix:** a move needs ≥ 0.1 % of price and ≥ 5 s since the last one. `5163899`. **Status:** fixed,
verified live (one move per trade).

### I-7. Continuous reconciliation corrects the store, not the running executor

**Seen:** `PositionDrift extra_locally … the correction is applied` every minute for 20 minutes while
the executor kept the position; after the fixes, one `stale_order` / `extra_locally` note per closed
trade.
**Cause:** `run_reconcile_loop` writes the exchange's truth to `state_store` only; the executor's
in-memory state is seeded from the store at boot and never again.
**Fix:** none yet — I-1/I-2 removed the cause of this incident. **Status:** open, TECH_DEBT §14.

### I-8. Local stop watcher and exchange stop fire together

**Seen (after the fixes):** 3 of 8 stop-outs — the exchange stop closed the position and the local
watcher's exit was refused with `2009`; I-2's check then closed the position locally with P&L and
fees marked incomplete, and the stop stays `new` in the journal.
**Cause:** both legs of the dual stop trigger at the same price; the one that loses the race never
sees the other's fill.
**Fix proposed:** give the exchange stop a short grace before the local watcher acts; poll tracked
orders (and collect their fills) before closing locally. On a venue with a native stop but no
enforced `reduce_only` the race could double-close. **Status:** open.

### I-9. Visualiser shows Flat while an entry is working

**Seen:** `/api/pairs` read `Flat` for 4 minutes while the entry limit order rested unfilled.
**Cause:** `Opening` is never written to `position_log`; the first row is the entry fill. See I-15.
**Status:** fixed with I-15 (`entry_placed` row, `5a932c6`), not deployed.

### I-10. Stale entry fills against a flipped signal; the opposite decision is dropped

**Seen (11:40–15:17 audit):** a long entry rested 13.7 min and a short entry rested 19.8 min. The
opposite SAR decisions (13:11:01; 15:09:27 and 15:10:39) were refused with "a position is already
open"; both entries then filled against the signal and were stopped out. 4 of 24 decisions produced
nothing.
**Cause:** the signal guard (`orchestrator/src/system.rs:1063`) treats `Opening` as flat, so it
sends a plain Open instead of a reversal. `max_wait` (`SIGNAL_MAX_WAIT_SECS`) never reaches
`execution`, so entries have no time-to-live.
**Fix:** (1) Guard: `Opening` counts as held on its side. A same-side flip is skipped
(`position_already_open`). An opposite flip reverses: the Close leg now *cancels* the working entry
(`pending_close` plus one cancel), and the Open waits until the pair is flat (`REVERSAL_FLAT_WAIT`
30 s). If the pair is not flat by then, it is skipped with `not_flat_after_close` plus a Warn alert.
A flip while `Closing` waits for flat before any decision is logged; otherwise it is skipped with
`position_closing`. (2) TTL: `max_wait` sets `entry_expires_at`. `poll_orders` cancels an expired
entry once, and an entry cancelled with nothing filled reports `NotFilled` "entry expired unfilled
after max_wait". (3) Logging: `NotPlaced` carries the refused `decision_id`. Its `position_log` row
has no `position_id` and uses the event's `decision_id`. Every position now records the decision
that opened it. The `main/` wire format is unchanged. `154bba9`, merged into
`mexc-live-m5` as `ee2e613` (conflicts with I-16 resolved; workspace tests 1332 passed). **Status:**
fixed, not yet deployed. Audit: [runs/2026-09-26-mexc-live-state-audit.md](runs/2026-09-26-mexc-live-state-audit.md) R1.

### I-11. A partial exit fill is double-counted

**Seen:** `fbe84c8c` exit filled 0.3 + 0.3. Stored pnl was −0.0387 against −0.0258 on the exchange,
and fees were 0.014693 against 0.012104.
**Cause:** `get_order_fills` returns every fill on the order each poll. `apply_fill` dedupes on
`trade_id`, but `apply_order_update` settled the whole list and `apply_settlement` adds, so poll 1
([A]) added A and poll 2 ([A, B]) added A + B again: 2A + B.
**Fix:** settle only the fills `apply_fill` accepted this poll; `settle_order` renamed
`fetch_order_fills` and no longer settles. Regression test fails without it (−150 vs −100). The
stored `fbe84c8c` row is not corrected. `35062fb`. **Status:** fixed, not yet deployed (running
executor predates it). Audit R2.

### I-12. Exchange-stop fills received but not stored

**Seen:** 4 trades (2 long, 2 short). The plan order's child `f:` order fill is in `order_event`
but not in `exchange_fill`. I-2 closed each position locally with pnl 0; the ledger is short by
−0.021218 USDT.
**Cause:** only the REST poll writes `exchange_fill`, and only for orders the position still tracks;
the plan-to-child link exists only on that path (`get_order_fills(p:)`). In all 4 cases the local
watcher took the pair lock first (I-8): `do_close` ignored the cancel's "already triggered", the
exit was refused (2009), and I-2's `close_as_gone` set `Flat` with pnl 0. The poll the child's push
woke then found nothing tracked. Contributing: a trigger-moment read of an executed plan with no
child id came back `New`, 0 filled; trailing stops moved through the market fired at once (Y2);
nothing revisited stops left working after `Flat` (R7's 4 phantom stops). `apply_stop_loss_move`
had the same hole: a refused cancel was ignored and the fired stop replaced.
**Fix:** (1) A refused stop cancel (`do_close`, trailing move, renewal) reads the stop and its fills
back and applies them; if that closes the position it is booked as a stop close and no exit is sent.
(2) `close_as_gone` settles every working order before closing locally, and alerts drift only if
size remains. (3) Orders still working at `Flat` go to an orphan sweep in `poll_orders`, read
through the journal until terminal (≤150 ticks), and late fills are alerted (the position row is
not corrected). (4) MEXC `get_order`/`get_order_fills` on an executed plan with no child id return
a retryable error, not `New`. (5) The advisor never moves a stop to or through the market (Y2).
Dedupe per `trade_id` already holds (`apply_fill`, `exchange_fill` `ON CONFLICT`). Not done: I-8
grace period; linking websocket `f:` pushes to their stop (the poll path covers it); the 4 stored
positions are not corrected. 6 regression tests, all fail without the fix. With I-16 the stop is kept beside the exit on
MEXC, so the refused-cancel path in `do_close` applies to cancel-first venues; on MEXC the race
lands in `close_as_gone`, which now books the stop. Commit `e7dad37`, merged into `mexc-live-m5` as `77ff876`
(rebased on `mexc-live-m5` `3f974e8`). Host tests: 1071 passed; the 250 failing need
`TEST_DATABASE_URL` (docker test run not done).
**Status:** merged (`77ff876`), not deployed. Audit R3, R7, Y2.

### I-13. Reconciliation removes the live stop from the stored state

**Seen:** 11 `stale_order` entries, each with `truth_status: null`, one per position about 60 s after
entry. The stored `Open` then holds no stop while the exchange stop is live.
**Cause:** `AccountState::open_orders` excludes plan orders (`futures.rs:648`), and `state_store`
reads that absence as "gone". A restart during a position would seed it without its stop
(`upkeep_stop` re-places one only if it is lost or 6 days old). Both correction paths
(`stale_order`, `quantity_drift`) also rewrote a `Closing` position as `Open`.
**Fix:** (1) Reconcile clears a tracked stop only when the exchange reports it `Cancelled` or
`Rejected`; absence keeps it, and a `Filled` stop is kept for the executor's poll to link (I-12).
`StaleOrderNoLongerOpen::truth_status` is now a plain `OrderStatus`, never null. (2) Corrections keep
the stored status (`Opening`/`Closing` stay put). (3) `upkeep_stop` places a stop for an `Open`
position that tracks none, so rows already stored without one heal on the next poll. Commit `e1e9cd7`
on `i13-reconcile-stop`, merged with `mexc-live-m5` as `0e05693`. 5 new tests, 1 inverted (absent stop
now kept). Workspace tests on the merged tree: 1345 passed. `market_data`
`shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database` failed 2 of 4 runs, unrelated
and timing-dependent. **Status:** fixed in `mexc-live-m5` (fast-forwarded to `0e05693`), not deployed. Related to I-7. Audit R4.

### I-14. Terminal position rows lose their identity

**Seen:** all 36 flat `filled`/`closed`/`stopped_out` rows have `position_id` and every column
`NULL`. `position_history` lists all 18 closed positions as `open` or `closing`. `decision_id` and
`signal_id` are `NULL` everywhere, and `exchange_order.position_id` is `NULL` on all 63 orders.
**Cause:** `run_position_sync` re-read the pair's state after each event. After a close that state
is `Flat`, which holds no position, so the terminal row got no id and no columns and never had
status `closed`. Nothing carried `signal_id` onto a decision, nothing set `decision_id` on the
position it opened, and `OrderRequest` had no field for the position.
**Fix:** (1) `ExecutionEngine::subscribe_position_changes` reports each event together with the
executor's own state snapshot and the position the event is about. For `Closed`/`NotFilled` that
is the finished position, the only copy left. (2) `PositionLogEntry::from_change` builds the row
from that change. The pg hot columns come from the position, and a terminal row's status is
`closed`, while `state` stays `Flat` for `load_all`. (3) `TradeDecision.signal_id` is new; the
opened position records `decision_id` and `signal_id`. (4) `OrderRequest.position_id` is new
(venues never see it); every order a position sends sets it, and the journal writes
`exchange_order.position_id`. Commit `0bf57f2` on `i14-position-identity`. 5 new tests, each seen
failing with its part of the fix removed. Rows written before the fix stay `NULL`; no backfill.
Merged with `mexc-live-m5` as `d326de5` (2026-09-26), `mexc-live-m5` fast-forwarded. Conflicts with
I-10/I-12/I-15/I-16: terminal paths (expired entry, `close_out` with the orphan sweep) go through
`flatten_and_report`; `from_change` drops the attached position for an event that names none, so
I-10's refused-decision row keeps no `position_id`; `position_id()` covers `EntryPlaced`. Docker
workspace run: 1349 passed, 1 failed (`market_data` `shutdown_reports_a_timeout_…`, crate
unchanged from base, known timing flake). **Status:** merged, not deployed. Audit R5, R7.

### I-15. `extra_locally` flattens a working entry

**Seen:** at 13:11:17, 15:10:17 and 15:11:17, reconciliation wrote `Flat` over an `Opening` position
whose entry was resting on MEXC; the entry filled later.
**Cause:** `open_position` set `Opening` in memory only and reported nothing, so the only `opening`
rows were I-10 refusal rows carrying the resting position's state. `reconcile_pair` counts any
non-flat status as held; with no exchange position, the `(Some, None)` arm wrote `Flat` without
looking at the entry order in `open_orders`. The correction reached the store only (I-7), so the
executor kept trading; a restart while an entry rested would have seeded `Flat` and orphaned it.
Trigger was R1, not the reverse (the guard reads memory, not the DB).
**Fix:** (1) New `PositionStateEvent::EntryPlaced { id, side, qty, price }` (`entry_placed`) is
reported when the entry goes out, so `Opening` is persisted (also fixes I-9). Migration `0011`
adds it to the `position_log.event` CHECK; `SCHEMA_VERSION` 11. (2) `reconcile_pair`: an `Opening`
whose entry is still `New`/`PartiallyFilled` in `open_orders` is `NoDiscrepancy`; an `Opening`
whose entry is gone still flattens. (3) Refusal rows naming no position: already done by I-10
(`NotPlaced.decision_id`). 3 new tests; the reconcile one fails without the guard (`ExtraLocally`).
Docker workspace run: 1340 passed, 1 failed (`market_data` `shutdown_reports_a_timeout_…`,
untouched crate, passes alone 3/3). `main/mq/position_consumer.py` does not know `entry_placed`
yet and skips it with one warning. Commit `4f81c31`, merged into `mexc-live-m5` as `5a932c6`.
Deploy needs executor and visualiser rebuilt together (schema 11). **Status:** merged, not
deployed. Audit R6.

### I-16. The exchange stop is cancelled before a limit close fills

**Seen:** 28.6 s (13:20, local stop) and 25.4 s (14:55, SAR close) with no stop on the venue while
the exit limit rested and the price moved through it.
**Cause:** `do_close` cancelled the exchange stop before it placed a passive reduce-only limit exit.
Nothing repriced that exit, and nothing acted while the position was `Closing`: `upkeep_stop` only
handles `Open`, and the watcher's `do_close` returned early.
**Fix:** (1) Where the venue holds a stop and enforces `reduce_only` (MEXC futures), the stop stays
in place while the exit works. Elsewhere it is still cancelled first. (2) When one of the two fills,
`finish_close` cancels the other. If the stop fills with its fills not booked (I-12), the position
closes only once the exchange reports no position. (3) If the venue refuses the exit while the stop
rests, `do_close` cancels the stop and places the exit again (the old order). (4) Stop-outs exit at
`Market`. (5) A stop crossing while a limit exit rests cancels that limit, books what filled, and
sends a reduce-only `Market` for the rest, once. No time limit on a main/target limit exit: the
kept stop bounds it. Commit `3f974e8` on `i16-close-keeps-stop`, fast-forwarded into `mexc-live-m5`. 8 new tests
and 1 updated; 7 of them fail without the fix. Workspace tests: 1315 passed. **Open:** whether MEXC accepts a reduce-only
limit beside a full-size reduce-only stop. Fallback (3) covers a refusal. **Status:** fixed in `mexc-live-m5`,
not deployed. Audit R8.

---

## 2026-09-26 — verification run 20:18–22:13 UTC (`d326de5` deployed)

Audit: [runs/2026-09-26-mexc-live-state-audit-2.md](runs/2026-09-26-mexc-live-state-audit-2.md).
6 round trips + 1 expired entry + 1 open short. The wallet equals the fills exactly (+0.002240 USDT),
and reconciliation found 0 discrepancies.

**Verified live:**
- I-9 / I-15: an `entry_placed` row on every entry, and no flattened entry.
- I-10: 2 reversals waited for flat; 1 entry expired at 300 s; 1 same-side skip.
- I-11: stored P&L = fills on 6 of 6 (no partial fill in the window).
- I-12: an exchange stop that won the race was booked with its fill.
- I-13: the stored open position keeps its stop.
- I-14: `position_id` is set on every order and fill.
- I-16: the stop is kept until the exit fills; 18.9 s unprotected over 2 191 s. MEXC accepts a
  reduce-only limit beside a full-size reduce-only stop, which answers I-16's open question.

I-8 still fires (2 of 3 stop-outs), safely: one refused order each.

### I-17. `StoppedOut` after `Closed` empties the position's history row

**Seen:** `286f684b` (I-12 race). Rows `closed` (20220, correct) and then `stopped_out` (20221,
status `flat`, id set, every column `NULL`). `position_history` shows the position as `flat` with
no side, exit or P&L. Stored fills and the `Closed` row are correct.
**Cause:** the local watcher's `StoppedOut` is reported after the booked stop close. `from_change`
then has only the `Flat` state (the I-14 remainder). The watcher's `do_close` found the exchange
flat and booked the stop through `close_as_gone` → `close_out` (`Closed`, reason `Stop`), returned
`Ok(true)`, and the watcher then called `report(StoppedOut)` on a `Flat` pair. `TargetHit` from the
advisor loop had the same race.
**Fix:** new `Executor::report_trigger`, used for `StoppedOut` and `TargetHit`: the event is
reported only while the pair still holds the position it names. When the close already finished
that position, `Closed` (which carries `close_reason: Stop`/`Target`) is its last change. Normal
stop-outs (exit placed, position `Closing`) still report `StoppedOut` with the position attached.
Stale doc comments in `types.rs` (`PositionChange.position`) and `state_store::from_change` updated.
2 new tests (`position_races`: stop-out and target-hit on a position already gone), both seen
failing before the fix with exactly the live row (`state: Flat, position: None`). Workspace run
against a throwaway postgres: 1353 passed, 0 failed. The stored `286f684b` row is not corrected; no
backfill. Commit `618255f` on `i17-late-stopped-out`, fast-forwarded into `mexc-live-m5`.
**Status:** merged (`618255f`), not deployed. Audit 2, N1.

### I-18. Spot base URLs default to Binance on a MEXC launch

**Seen:** `REST_BASE_URL=https://api.binance.com` and `WS_BASE_URL=wss://stream.binance.com:9443`
(compose defaults, `docker-compose.yml:186`) with `EXCHANGE=mexc`. There were 0 spot requests, but
a spot-surface call would sign with the MEXC key against Binance.
**Status:** open (config). Audit 2, Y5.
