# Paper Mode Implementation Plan

> **Status 2026-10-18: implemented on branch `paper-mode` (uncommitted, stacked). Tasks 1–5 done; host suites green (execution 123, orchestrator 98); Docker gate 1463 / 0 on a fresh volume (before the fix pass added the paper+futures config refusal, covered by `paper_mode_refuses_futures`). Review (fresh opus) → 1 Important fixed (paper + futures refused), minors deferred to UNFINISHED. Engine fix I-19 (`working_order` ack status) rides along. Commit awaits user confirmation.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) to implement this plan layer-by-layer. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `EXECUTION_MODE=paper` opens and closes positions inside the executor against the live feed with simulated fills, so every CB zone decision that would have opened gets its `Opened`/`TargetHit`/`StoppedOut`/`Closed` rows and both chart points — no money, no exchange order.

**Architecture:** `PaperMarketAccount` (exists, unwired) gets a fill model the executor's own flow can complete: limit fills at its price, market at mid, stop rests; synthesised `get_order_fills`; quote + base balances; run-unique ids. `main.rs` accepts `paper`, wraps the real adapter in `NoTradeAccount` (feed only); `OrchestratorConfig.paper` carries the starting balance; `boot` builds the paper account over `market_data`, journals it with origin `paper`, reconciles once at boot and skips the periodic reconcile loop. Compose passes `PAPER_STARTING_BALANCE` through.

**Tech stack:** Rust workspace (`tokio`, `rust_decimal`), Docker Compose. Executor worktree `trade_executor/.worktrees/layer-implementation`, branch `paper-mode` from `cb-target-trend-exit` (uncommitted stack).

**Spec:** [`external/executor/specs/2026-10-18-paper-mode-design.md`](../specs/2026-10-18-paper-mode-design.md).

**Layers:** L4 `execution::paper` → L4 `execution` lifecycle → orchestrator config/main → orchestrator boot → L9 compose/docs. Host suites green before the next layer; Docker gate last.

---

## Global Constraints

- **Branch:** `paper-mode` from the current `cb-target-trend-exit` head; this task's diff stays unstaged on top (index = earlier stacked work). Never commit without explicit user confirmation.
- **`no_trade` and `live` behave exactly as before; `paper` is never a default** (spec §9.3).
- **No schema change, no `main/` change, no visualiser change.**
- **The periodic reconcile loop is not spawned in paper mode; the boot-time reconcile is kept** (spec §2).
- **Paper order ids are run-unique** `p{run_token}-{n}`; `trade_id = "paper-{order id}"` (spec §2).
- **Live executor is not recreated by this work.**
- **Test DB isolation:** throw-away postgres `-p cbx-test` on 5437 for the host loop; the gate on a fresh volume.

## Review Focus

1. Second paper run after a restart: orders must not be refused by the journal's UNIQUE id (Task 1 run-token test; Task 4 boot test journals under origin `paper`).
2. A long whose sell exit is a limit on the far side of the mid must still fill (Task 1 "limit sell above mid fills at its price"; Task 2 lifecycle).
3. A short in paper: base balance goes negative, the buy exit sizes to `net_size` (Task 2 short lifecycle).
4. Empty book at a market (stop) fill → `Stale`, no panic, the watcher retries (Task 1 test).
5. `EXECUTION_MODE=paper` with keys missing: the feed still needs the adapter; the mode must not silently fall back to `no_trade` (Task 3: `parse_execution_mode` exact match; `from_env` reads the mode once).

---

## Docker Entry Points

```bash
cargo test -p execution --lib
cargo test -p orchestrator --lib                       # config/main-shaped tests (no DB)
docker compose -p cbx-test -f docker-compose.yml -f <scratch>/ports.yml up -d --wait postgres
TEST_DATABASE_URL=postgres://executor:executor@127.0.0.1:5437/trader cargo test -p orchestrator --lib
docker compose -p cbx-test -f docker-compose.yml down -v
# gate
docker compose -p cbx-test -f docker-compose.yml -f <scratch>/ports.yml run --build --rm test cargo test --workspace --no-fail-fast
# operator (their shell, env exported there):
EXECUTION_MODE=paper docker compose -p cbov-check up -d --no-build executor
```

Verified: [x] gate green — 1463 passed / 0 failed (2026-10-18).

---

## Task 1 — L4 `execution::paper`: a fill model the executor can complete

**Files:**
- Modify: `crates/execution/src/paper.rs`
- Test: its `#[cfg(test)]` module (existing `non_marketable_limit_rests_as_new` is replaced; `marketable_limit_fills_immediately` keeps passing)

**Interfaces (Produces):**
- `PaperMarketAccount::new(feed, quote_asset, starting_balance)` unchanged; `pub fn balances(&self) -> Vec<(String, Decimal)>` (quote and every base touched) for tests.
- `place_order`: `Limit` → `Filled` at `order.price` (a limit without a price → `InvalidRequest`); `Market` → `Filled` at mid, no mid → `AdapterError::Stale`; `Stop` → `New`. Every fill moves quote by `price·qty` and base (`pair` minus the quote suffix, `_` trimmed, as `Executor::pair_assets`) by `qty`. `OrderInfo.client_order_id` = the request's. Ids: `OrderId::from(format!("p{run_token}-{n}"))`, `run_token` = ms since epoch at construction.
- `get_order_fills(id)`: `Ok(vec![Fill { trade_id: format!("paper-{id}"), order_id, pair, side, price, qty, quote_qty: price·qty, fee: 0, fee_asset: quote, is_maker: true, realized_pnl: None, ts: now }])` for a filled order, `Ok(vec![])` for a resting/cancelled one, `InvalidRequest` for an unknown id.
- `capabilities()`: `order_fills: true` (rest unchanged).
- `get_account_state()`: one `BalanceDelta` per tracked asset (`locked: 0`), `positions: []`, open orders = resting.

- [ ] **Step 1: RED**

```rust
#[tokio::test] async fn a_limit_buy_below_mid_fills_at_its_own_price()      // mid 100, buy limit 99 → Filled, avg 99, quote −99·qty, base +qty
#[tokio::test] async fn a_limit_sell_above_mid_fills_at_its_own_price()     // mid 100, sell limit 101 → Filled at 101, base −qty
#[tokio::test] async fn a_market_order_without_a_book_is_stale()            // empty book → Err(Stale), nothing booked
#[tokio::test] async fn a_stop_rests_and_can_be_cancelled()                 // New, then cancel → Cancelled; get_order_fills → []
#[tokio::test] async fn fills_are_synthesised_for_a_filled_order()          // one Fill, trade_id "paper-{id}", qty/price, fee 0 in USDT
#[tokio::test] async fn the_client_order_id_is_echoed()
#[tokio::test] async fn order_ids_are_unique_across_two_accounts()          // ids of account A and B (constructed after a 2 ms sleep) never collide; both start n=1
#[tokio::test] async fn a_round_trip_returns_the_base_to_zero_and_books_the_quote_difference()  // buy 10@100, sell 10@111 → base 0, quote +110
#[test] fn capabilities_report_fills()
```

- [ ] **Step 2: `cargo test -p execution --lib paper` — RED**
- [ ] **Step 3: Implement** (`run_token: u64`, `balances: Mutex<HashMap<String, Decimal>>` replacing the single quote balance; `pnl()` = quote − starting)
- [ ] **Step 4: `cargo test -p execution --lib` — GREEN**

---

## Task 2 — L4 `execution`: the lifecycle the SAR spec §11.4 asked for

**Files:**
- Test only: `crates/execution/src/tests.rs` (new module `paper_lifecycle`; reuses `FakeFeed`, `CannedSignalBuilder`, `PassThroughRiskValidator`, `NoAdvice`, `trend_flip_exit::ScriptedTrend`-style source, `decision(..)`)

**Interfaces (Consumes):** Task 1's account; `Executor::new(Arc<PaperMarketAccount>, feed, ..).with_trend_source(..)`; `handle_decision`, `poll_orders(&pair)`, `run_stop_loss_watcher`, `run_advisor_loop`, `subscribe_position_changes`.

- [ ] **Step 1: RED**

```rust
#[tokio::test] async fn a_long_opens_on_paper_and_closes_on_the_trend_flip()
  // canned Open {open 100, close 110, stop 90}, RISK 100 → qty 10; handle_decision; poll_orders → Opened (net_size 10);
  // spawn advisor loop with ScriptedTrend(Up); trades 112; set Down; trade 111 → TargetHit{111};
  // poll_orders → Closed { close_reason: Target, avg_exit_price: 111 }; account base balance 0; position Flat
#[tokio::test] async fn a_long_opens_on_paper_and_is_stopped_out()
  // same open; spawn stop watcher; trade 89 → StoppedOut; poll_orders → Closed { close_reason: Stop }, avg_exit_price = mid (FakeFeed book) 
#[tokio::test] async fn a_short_opens_on_paper_and_closes_on_the_trend_flip()
  // Sell: open 100, close 90, stop 110; trade 88 (Down), set Up, trade 89 → TargetHit{89} → Closed; base balance back to 0
```

If `poll_orders` is not reachable from the test module as the SAR-era tests reach `resolve_entry`, use the same `pub(crate)` entry those tests use (`filled_entry`/`resolve_entry` for the entry, `poll_orders` for the exit) — the brief for the executor's fill path is `run_fill_sync`'s doc comment.

- [ ] **Step 2: RED** (the entry must actually fill through the paper account: a RED here that says "net_size 0" means Task 1's `get_order_fills` is wrong, not this test)
- [ ] **Step 3: fix whatever Task 1 missed** (no production change expected beyond Task 1)
- [ ] **Step 4: `cargo test -p execution --lib` — GREEN**

---

## Task 3 — Orchestrator config + `main.rs`: the `paper` mode

**Files:**
- Modify: `crates/orchestrator/src/config.rs` (`PaperConfig`, `OrchestratorConfig.paper`, `from_env`)
- Modify: `crates/orchestrator/src/main.rs` (`ExecutionMode::Paper`, `parse_execution_mode`, `build_market_account` arm)
- Test: `config.rs` tests (`from_env` env-var fixtures), `main.rs` has no test module today — `parse_execution_mode` becomes `pub(crate)` in a `mode.rs`? No: keep it in `main.rs` and test the config side; the match arm is one line.

**Interfaces (Produces):**
- `pub struct PaperConfig { pub starting_balance: Decimal }`; `OrchestratorConfig.paper: Option<PaperConfig>`; `from_env`: `EXECUTION_MODE=paper` → `Some(PaperConfig { starting_balance: PAPER_STARTING_BALANCE or 100_000 })`, invalid → error `PAPER_STARTING_BALANCE=… is not a valid decimal`; any other mode → `None` (`PAPER_STARTING_BALANCE` ignored). `EXECUTION_MODE` missing stays `main.rs`'s fatal (config does not add a second error for it).
- `main.rs`: `"paper" => ExecutionMode::Paper`; the fatal message lists `no_trade|paper|live`; `Paper` arm prints `EXECUTION_MODE=paper -- orders are simulated in-process against the live feed; none reach the exchange; paper positions do not survive a restart` and returns `NoTradeAccount::new(account)`; no boot gate.
- `valid_config` in `tests.rs` gains `paper: None`.

- [ ] **Step 1: RED (config.rs tests)**

```rust
#[test] fn paper_mode_reads_the_starting_balance_with_a_default()   // EXECUTION_MODE=paper, var unset → 100000; "2500.5" → 2500.5
#[test] fn an_invalid_paper_balance_is_a_config_error()
#[test] fn no_trade_ignores_the_paper_balance()                      // paper: None even with PAPER_STARTING_BALANCE set
```
- [ ] **Step 2: `cargo test -p orchestrator --lib config` — RED**
- [ ] **Step 3: Implement**
- [ ] **Step 4: `cargo test -p orchestrator --lib config` — GREEN; `cargo build -p orchestrator --bin trade_executor`**

---

## Task 4 — Orchestrator `boot`: the paper account over the feed

**Files:**
- Modify: `crates/orchestrator/src/system.rs` (`execution_account`, journal origin, reconcile-loop gate, boot log)
- Test: `crates/orchestrator/src/tests.rs`

**Interfaces (Produces):** `pub(crate) fn execution_account(config: &OrchestratorConfig, handed_in: Arc<dyn MarketAccount>, feed: Arc<dyn MarketDataFeed>) -> Arc<dyn MarketAccount>`; boot step 5 uses it for the `JournaledAccount`; `JournalContext.origin` = `"paper"` / `"execution"`; the reconcile block is skipped when `config.paper.is_some()` with the log line `reconcile loop off (paper): the paper account is this process, nothing to reconcile against`; boot prints `paper account armed: starting balance {n} {quote}`.

- [ ] **Step 1: RED**

```rust
#[tokio::test] async fn execution_account_is_the_handed_in_one_without_paper()      // same Arc (ptr_eq) 
#[tokio::test] async fn execution_account_is_a_paper_account_with_the_balance_when_paper()  // get_account_state free USDT == 2500
#[tokio::test] async fn boot_in_paper_mode_journals_as_paper_and_runs_no_reconcile_loop()
  // DB-backed, `boot_constructs_every_layer…` shape with paper: Some; after boot: the handed-in FakeMarketAccount saw no place_order ever;
  // `system.task_names()` (or the handles' labels — add `pub fn task_names(&self) -> Vec<String>` to RunningSystem if absent) has no "reconcile";
  // an exchange_order row written through system.executor (one Open decision → entry placed) has origin = "paper"
```
- [ ] **Step 2: `TEST_DATABASE_URL=… cargo test -p orchestrator --lib` — RED**
- [ ] **Step 3: Implement**
- [ ] **Step 4: GREEN; `cargo clippy --workspace --tests` no new warnings**

---

## Task 5 — Compose, Docker gate, docs

- [ ] **Step 1:** `docker-compose.yml` executor service: `- PAPER_STARTING_BALANCE=${PAPER_STARTING_BALANCE:-}`; `EXECUTION_MODE` comment mentions `paper`.
- [ ] **Step 2:** gate on a fresh volume — green, count ≥ 1444 + new.
- [ ] **Step 3:** External docs: spec status → implemented; `UNFINISHED.md` "Paper mode is still not wired" ticked in the SAR section, new section for this plan (commit gate, operator restart with `EXECUTION_MODE=paper`, no reconcile loop, no P&L on margin, ids run-unique); `TECH_DEBT.md` new numbered section: periodic reconcile loop vs venues reporting `positions: []` (MEXC spot/margin).
- [ ] **Step 4:** leave the diff unstaged; describe; wait for the user's commit confirmation.
