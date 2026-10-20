# Paper mode (`EXECUTION_MODE=paper`) — Design Spec

Date: 2026-10-18
Status: **implemented 2026-10-18 on branch `paper-mode` (squashed into `close-marker-pnl` `4f5ede3`, in `layer-implementation` = `release_001` @ `1689dc5` since 2026-10-20; running as the `cbov-check` paper stack) — host loop green (execution 123, orchestrator 98); Docker gate `cargo test --workspace --no-fail-fast` fresh volume 1463 / 0; review fix pass: paper + futures refused at config; operator restart pending**
Target project: `trade_executor` (worktree `layer-implementation`, on top of branch `cb-target-trend-exit`) — L4 `execution` (`PaperMarketAccount` fill model), orchestrator (`main.rs` mode, `config.rs`, `boot` wiring), L9 compose. No schema change, no `main/` change, no visualiser change.
Related: [2026-10-18-cb-target-trend-exit-design.md](2026-10-18-cb-target-trend-exit-design.md) (the close rule this exists to observe), [2026-09-22-position-management-design.md](2026-09-22-position-management-design.md) §13 (paper mode named as the only way to watch a full position lifecycle without money), [2026-09-22-sar-flip-test-signal-design.md](2026-09-22-sar-flip-test-signal-design.md) §13 (why `boot` could not wire it then), `UNFINISHED.md` "Paper mode is still not wired".

## 1. Why

With `EXECUTION_MODE=no_trade` every open dies before a position exists (`NoTradeAccount` refuses the order; before that, sizing refuses at `RISK_PER_TRADE=100`). The chart therefore shows only the *open* marker of each CB zone decision and never a close point — and the new close rule (extreme past target, then trend flip) only runs on an `Open` position. The user needs the positions that *would have opened* to actually open and close inside the executor, against the live feed, with no money: a paper account whose fills are simulated, so `position_log` gets real `Opened`/`TargetHit`/`StoppedOut`/`Closed` rows and the visualiser draws both ends of every trade.

## 2. Decisions

Taken by the user (2026-10-18): wire paper mode (option 1 of the assessment), not a "shadow position" log.

Calls made by the author (flagged for review):

| Question | Call |
|---|---|
| Where paper plugs in | A third `EXECUTION_MODE` value, `paper`. The real exchange adapter is still built (it is the **market-data source**: trades, book) and wrapped in `NoTradeAccount` as a belt-and-braces refusal; the **execution** account is a `PaperMarketAccount` over the executor's own `MarketDataService`, built inside `boot` after the feed exists. Same live stack, same compose, same DB; only the env value changes. |
| Fill model for a limit order | **Fills immediately at its limit price**, whatever the mid. Today's rule (fill only if the limit crosses the mid, else rest) would leave the executor's exit — a limit at the *trade* price — resting whenever that trade was on the far side of the mid, and the position stuck `Closing` until the exit timeout. Optimistic, documented: this is for observing where the rules open and close, not for measuring slippage. |
| Fill model for a market order | Unchanged: fills at the current mid (the stop watcher's close). No mid (empty book) → `Stale`, the watcher alerts and retries on the next trade. |
| Fill model for a stop order | Unchanged: accepted, rests `New` forever, never triggers. The executor's own stop watcher (`run_stop_loss_watcher`, every trade) is the stop in paper mode; the resting stop is cancelled by `do_close` as today. |
| Fills | `get_order_fills` **implemented**: one synthesised `Fill` per filled order (`trade_id = "paper-{order id}"`, the order's qty and price, fee 0 in the quote asset, `is_maker: true`, `realized_pnl: None`, `ts` = now). `capabilities().order_fills = true`. Without it `fetch_order_fills` returns `None`, `apply_to_position` records nothing, `net_size` stays 0 and the position never becomes `Open`. ~~**`realized_pnl` on a `Closed` row stays `NULL` for `margin`/`spot`**~~ — since 2026-10-19 (branch `close-marker-pnl`) `OpenPosition::recompute` works it out from the fills on every non-futures position (exits' notional vs the exited quantity at the average entry, gross of fees; `None` until an exit fills), so paper, spot and margin closes carry a number and the Closed Positions table totals it. Futures keep the venue's figure via `apply_settlement`. |
| Balances | Quote **and base** tracked: a buy fill debits quote by `price·qty` and credits base by `qty`; a sell fill the reverse (base may go negative for a short). `get_account_state` reports both (`free` = balance, `locked` 0). `close_qty` for a long's sell exit reads the free base — without it the exit is sized 0 and "retrying on the next tick" forever. |
| Fees, positions, market info | No fees (unchanged). `positions: []` (margin/spot semantics). `get_market_info` unchanged (tick/lot 1e-8, no min notional). `MARKET_KIND` stays whatever the env says (live: `margin`) **except `futures`, refused at config time**: `exchange_confirms_flat` is futures-only and would read the empty `positions` as "the venue confirms flat", closing a position locally on any failed exit instead of retrying (review finding, 2026-10-18). |
| `client_order_id` | Echoed from the request (today `None`, flagged as a TODO in the code). `client_id_lookup` stays false. |
| Starting balance | `PAPER_STARTING_BALANCE` (quote units), read only when `EXECUTION_MODE=paper`, **default 100 000**: `within_account_limits` needs `free·MAX_NOTIONAL_FRACTION ≥ notional` and the compose defaults (`RISK_PER_TRADE=100`, 1 % stop, fraction 0.5) ask for a 10 000 notional. Invalid value → config error at boot. |
| Account events / position sync | The paper account's `subscribe_account_updates` stays `NotSupported`, but nothing calls it: `spawn_account_ingestion` subscribes to the **handed-in real** account and `run_position_sync` reads `market_data`'s account events, so it keeps running and writes `position_log` as usual; a real-account `OrderUpdate` for a pair holding a paper position is a no-op (no state event). Fill sync is poll-driven. (Corrected after review, 2026-10-18.) |
| Reconciliation and restart | Boot reconciles against the paper account's truth (no positions, no open orders): a position persisted by a previous paper run is reconciled flat. **Paper positions do not survive a restart** — stated at boot. The **periodic reconcile loop is not spawned in paper mode**: with `positions: []` it would flatten every open paper position in the store every 60 s (`reconcile_pair`'s "extra locally" arm, a `position_log` correction row and a `PositionDrift` alert per tick) while the executor kept trading it. Boot logs "reconcile loop off (paper)". (Builder check, 2026-10-18. The same hole exists for live margin — MEXC spot/margin also reports no positions — and goes to `TECH_DEBT.md`, not fixed here.) |
| Order journal | `JournaledAccount` wraps the paper account as it wraps a real one (every simulated order gets its `exchange_order` row, so the panels show them), with `JournalContext.origin = "paper"` so the rows are distinguishable from `"execution"`. |
| Order ids across runs | `exchange_order` is `UNIQUE (exchange, market_kind, exchange_order_id)` and the journal refuses (`Rejected`, non-retryable) an ack whose id collides, so a counter restarting at 1 every boot would refuse every order of the second paper run. Paper order ids are therefore **run-unique**: `p{run_token}-{n}` with `run_token` = construction time in ms, `n` from 1; `trade_id = "paper-{order id}"` inherits it. (Builder check, 2026-10-18.) |
| Boot gate | Not run (it is `live`-only today; paper never reaches a venue). |
| Where the mode is parsed | `main.rs` keeps `parse_execution_mode` (now `no_trade|paper|live`) and `OrchestratorConfig` gains `paper: Option<PaperConfig>` filled by `from_env` from the same env (so `boot` and its tests can select the backend without `main.rs`). The two must agree; `main.rs` reads the mode once and passes the account it built. |

## 3. Scope

In: `PaperMarketAccount` fill/fills/balance/client-id changes + tests; `ExecutionMode::Paper` in `main.rs`; `OrchestratorConfig.paper`; `boot` building the paper account over `market_data` and using it for execution, the journal and reconciliation while the passed-in account keeps feeding ingestion; boot log lines; compose env pass-through; UNFINISHED/plan.

Out: slippage/latency/partial-fill simulation; a simulated stop trigger (the local watcher is the stop); fees; persistence of paper state across restarts; a separate compose project (the operator picks the project as today); `main/` or visualiser changes.

## 4. Interfaces

```rust
// orchestrator/src/config.rs
pub struct PaperConfig { pub starting_balance: Decimal }
pub struct OrchestratorConfig { /* … */ pub paper: Option<PaperConfig> }   // Some iff EXECUTION_MODE=paper

// orchestrator/src/main.rs
enum ExecutionMode { NoTrade, Paper, Live }
fn parse_execution_mode(raw: &str) -> ExecutionMode                        // "paper" accepted

// orchestrator/src/system.rs (boot, step 5)
/// The account orders go to: the one handed in, or a paper account over
/// the feed when `config.paper` is set.
fn execution_account(config: &OrchestratorConfig, handed_in: Arc<dyn MarketAccount>, feed: Arc<dyn MarketDataFeed>) -> Arc<dyn MarketAccount>

// execution/src/paper.rs (existing type, changed behaviour)
impl MarketAccount for PaperMarketAccount {
    async fn place_order(&self, order: OrderRequest) -> Result<OrderAck, AdapterError>;   // Limit: fills at limit price; Market: at mid; Stop: rests
    async fn get_order_fills(&self, id: OrderId) -> Result<Vec<Fill>, AdapterError>;      // one Fill per filled order, [] for a resting one
    async fn get_account_state(&self) -> Result<AccountState, AdapterError>;              // quote + base balances
    fn capabilities(&self) -> Capabilities;                                               // order_fills: true
}
```

`boot(config, market_account)` keeps its signature: `market_account` is what ingestion subscribes to; execution/journal/reconcile use `execution_account(..)`.

## 5. Boot (step 5, orchestrator)

1. After `MarketDataService::connect` and ingestion spawn (unchanged), `let execution = execution_account(&config, market_account.clone(), market_data.clone())`.
2. `JournaledAccount::new(execution, …, JournalContext { origin: if config.paper.is_some() { "paper" } else { "execution" }, .. })`.
3. Reconcile, `Executor::new`, position sync, unknown-order recovery: all over the journaled account as today (they already take `market_account` = journaled).
4. Log line: `EXECUTION_MODE=paper -- orders are simulated in-process against the live feed (starting balance {n} {quote}); none reach the exchange; paper positions do not survive a restart` (in `main.rs` next to the other two mode lines, plus boot's `paper account armed` line naming the balance).

## 6. Compose (L9)

`executor` service: `- PAPER_STARTING_BALANCE=${PAPER_STARTING_BALANCE:-}` (unset = default 100 000 in code); the `EXECUTION_MODE` comment lists `paper`. Default stays `no_trade`. The live executor is **not** recreated by this work; the operator restarts it with `EXECUTION_MODE=paper` in their shell.

## 7. Error handling

`EXECUTION_MODE=paper` with an unparsable `PAPER_STARTING_BALANCE` → config error at boot (with the other env errors). An empty book at a market fill → `AdapterError::Stale` → the stop watcher's existing Critical alert, retried on the next trade. `cancel_order` of an already-filled paper order → `InvalidRequest` (unchanged; `do_close` treats a failed stop cancel as "probably filled" and polls).

## 8. Testing

**`execution::paper` unit** (host): limit buy below mid fills at its own price; limit sell above mid fills at its own price; market fills at mid; stop rests `New` and can be cancelled; `get_order_fills` of a filled order = one fill with the order's qty/price/`trade_id = "paper-{id}"` and fee 0, of a resting order = `[]`; a buy debits quote and credits base, a sell the reverse, both visible in `get_account_state`; `client_order_id` echoed; `capabilities().order_fills`.

**`execution` lifecycle** (host, `tests.rs`, `Executor` over a real `PaperMarketAccount` + `FakeFeed`): an `Open` decision (canned `SignalAction::Open` at 100, target 110, stop 90) places the entry, `poll_orders` books the fill → `Opened` with `net_size` = sized qty; trades 112 (Up) then 111 (Down via a scripted `TrendSource`) → `TargetHit`, exit placed, `poll_orders` → `Closed` with `close_reason = target`, `avg_exit_price = 111`, paper base balance back to 0; the stop path: trade 89 → `StoppedOut` → `Closed` with `close_reason = stop`. Two paper accounts constructed one after the other never share an order id. This is the test the SAR spec §11.4 asked for and never had.

**Orchestrator unit**: `parse_execution_mode("paper")`; `from_env` with `EXECUTION_MODE=paper` → `paper.starting_balance` default 100 000 / parsed / invalid → error; `EXECUTION_MODE=no_trade` + `PAPER_STARTING_BALANCE` set → `paper: None` (ignored); `execution_account` returns the handed-in account when `paper` is `None` and a paper account (balance visible in `get_account_state`) when `Some`; `boot` with `paper: Some` (the existing DB-backed `boot_constructs_every_layer…` shape) journals with `origin = "paper"` and spawns no reconcile loop (no `reconcile[{pair}]` task name among the handles / no reconciliation report after the interval).

**Docker gate**: `docker compose -p cbx-test … run --build --rm test cargo test --workspace --no-fail-fast` on a fresh volume.

**Live check (operator, human-gated)**: restart with `EXECUTION_MODE=paper` (keys still needed for the market-data feed); first `cb_zone_*` fire → position panel shows `Open`, `take_profit_price` = `cbnc` bound; later `Closed` with `close_reason` `target` or `stop`; chart draws open + close points; `exchange_order` rows carry origin `paper`.

## 9. Acceptance criteria

1. `EXECUTION_MODE=paper` boots with the real feed and a paper account; no order reaches the exchange (the real account is wrapped in `NoTradeAccount`).
2. A CB zone decision opens a paper position (`Opened`, size from `RISK_PER_TRADE`) and the trend-flip rule closes it (`TargetHit` → `Closed`, reason `target`), or the stop watcher does (`StoppedOut` → `Closed`, reason `stop`), all visible in `position_log` and the visualiser.
3. `no_trade` and `live` behave exactly as before; `paper` is never a default.
4. Docker gate green; test count ≥ 1444 + new.

## 10. Follow-ups (not blocking)

- The `working_order` ack fix found by §8's lifecycle test is a **live** fix (I-19): Binance/MEXC spot acks carry the venue's status, and an entry or exit acked `FILLED` was never polled.

- Slippage / partial fills / stop-trigger simulation if paper P&L is ever to be trusted as a number.
- ~~`realized_pnl` for margin/spot closes (avg entry vs avg exit)~~ — done 2026-10-19 (`close-marker-pnl`): price-derived in `OpenPosition::recompute` for non-futures positions, live rows included; fees stay a separate column.
- Persisting paper state across restarts.
- TECH_DEBT: the periodic reconcile loop flattens any open position on a venue that reports `positions: []` (MEXC spot/margin) — never hit live because `no_trade` never opens.
