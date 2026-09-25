# Position Management 1/9 — Position core (`exchange_adapter`, `execution`, `local_analysis`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan layer-by-layer. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The position stops being a record of what was *submitted* and becomes a record of what the exchange *did* — fill-driven, settled with fees, resolved once per entry, with the target as a local trigger and the stop as the only resting leg.

**Spec:** [`external/executor/specs/2026-09-22-position-management-design.md`](../specs/2026-09-22-position-management-design.md) (approved 2026-09-24) — §3 (whole), §4, decisions D3–D7, D10, D11. Section refs (§) below point into it; read it alongside this plan.

**Scope:** `crates/exchange_adapter`, `crates/execution`, `crates/local_analysis`, and the new `crates/order_journal` (a move only, Task 1.3). Pure types, pure transitions and in-crate behaviour. **No** orchestrator wiring, **no** persistence, **no** wire, **no** visualiser — those are plans 2/9, 3/9, 4/9, 7/9, 8/9.

**Position in the set:** the foundation. Plans 2/9, 3/9 and 4/9 all compile against the types this plan defines. Nothing here depends on them.

**Depends on:** [`2026-09-22-live-trade-ops-plan.md`](2026-09-22-live-trade-ops-plan.md) merged into `layer-implementation` and green. As of 2026-09-25 that branch is substantially complete — journal, `settle`, scenarios, live runner, migration `0008`, and one real Binance margin run — but **not merged** (`git merge-base --is-ancestor live-trade-ops layer-implementation` → NO). This plan consumes as production API what that one built test-only: `Fill`, `MarketAccount::get_order_fills`, `settle`, `OrderRequest::client_order_id`, `RejectReason`, `MarginOps`/`FuturesOps`.

**Branch:** `position-core`, cut from the integration branch `position-management` (itself cut from `layer-implementation`). Merged back into `position-management`, never straight into `layer-implementation` — plan 9/9 owns that merge.

**Tech stack:** Rust workspace (`tokio`, `rust_decimal`, `uuid`, `wiremock`), Docker Compose. Workspace: `trade_executor/.worktrees/layer-implementation`.

**Note on layer taxonomy:** `layer-first-planning`'s layer table describes the Python trading pipeline, not the executor. Like [2026-09-21-indicator-panel-plan.md](2026-09-21-indicator-panel-plan.md) and [2026-09-22-live-trade-ops-plan.md](2026-09-22-live-trade-ops-plan.md), this plan applies that skill's *principles* — Docker first, interface before code, a RED integration test at each boundary, no layer started before the previous is green in Docker — over `trade_executor`'s real crate layers.

## Readiness review

Verified against the code on `layer-implementation` @ `ff2938d` and `live-trade-ops` @ `e45dc05` (2026-09-25).

🟢 **green** — exists in the system, small update · 🟡 **yellow** — in the spec, small code change · 🟠 **orange** — in the spec, large code change · 🔴 **red** — in neither code nor spec

### 🟢 Green

| Item | Where it is today | Change |
|---|---|---|
| `Executor`, `ExecutionEngine`, the `positions` map, `report()`/`state_tx` broadcast | `execution/src/engine.rs` | internals only; the trait keeps its shape |
| `run_stop_loss_watcher`, `run_advisor_loop` | `engine.rs` | each gains an arm; the shutdown-race shape is reused verbatim |
| `sizing::compute_size` | `execution/src/sizing.rs` | formula unchanged; only `within_account_limits` grows a leveraged branch |
| `PositionStateEvent` + `report()` | `execution/src/types.rs` | gains variants |
| `DefaultPositionAdvisor`, `PositionAdvisor` | `local_analysis/src/advisor.rs` | behaviour unchanged |
| `settle`, `PairAssets`, `Settlement` | **already written**, `live_trade_ops/src/settle.rs` | a crate move, not an implementation |
| `OrderJournal`, `JournaledAccount`, `JournalContext`, `MemoryJournal`, `PgOrderJournal` | **already written**, `live_trade_ops/src/journal/` (`mod.rs`, `memory.rs`, `pg.rs`) + `tests/pg_journal.rs` | a crate move to `crates/order_journal` (spec D5, amended 2026-09-25), not an implementation |
| `Fill`, `OrderInfo::client_order_id`, `get_order_fills`, `RejectReason`, `MarginOps`/`FuturesOps` | **already written** on `live-trade-ops` | consumed as-is |

**Dependency status corrected.** `live-trade-ops` is much further along than this plan first assumed — journal, `settle`, scenarios, live runner and migration `0008` all exist, and one real Binance margin run has happened (`dabc7a9`). It is **not merged**: `git merge-base --is-ancestor live-trade-ops layer-implementation` → NO. So none of it is reachable yet, but none of it needs writing either.

### 🟡 Yellow

`PositionId`, `OrderRole`, `CloseReason`, `pending_close` field · the `created_at` rename and `first_fill_at` removal · `OpenPositionView`'s three new fields · D5's client-order-id format · the five new constants (`ENTRY_FILL_TIMEOUT_SECS`, `EXIT_FILL_TIMEOUT_SECS`, `ORDER_POLL_INTERVAL_SECS`, `POSITION_RISK_POLL_SECS`, `LIQUIDATION_WARN_FRACTION`).

### 🟠 Orange

| Item | Why it is large |
|---|---|
| `PositionStatus` 2 → 4 variants; `OpenPosition` rewritten | every read site in `execution`, `state_store`, `mq_gateway`, `orchestrator`, `visualizer_server` — the renames are deliberately compiler-forced, so the blast radius *is* the design |
| `open_position` / `do_close` / `apply_stop_loss_move` rebuilt around resolution | the ordering of placement, cancellation and state writes all change |
| **`run_fill_sync`** | net-new task: poll authority, event-as-hint, the `get_order_fills` settle loop with its 10 s lag rule |
| Target trigger in `run_advisor_loop` | new `subscribe_signals` arm plus the price backstop |
| Liquidation proximity + `position_risk` polling | net-new, and the first producer `AlertKind::LiquidationNear` has ever had |
| Scale-in / partial close | entry and exit lists, weighted averages, net size — the reason A19's hazard disappears |

### 🔴 Red

| Item | Status |
|---|---|
| `Resolution` enum, `TerminalOrderInfo` newtype, `apply_fill`/`apply_settlement`/`net_size()`/`unrealized_pnl()`, `mint_client_order_id`/`parse_client_order_id` | implementation detail below the spec's altitude — no amendment needed |
| ~~`pos8` collision risk~~ | **RESOLVED 2026-09-25.** 32 bits gave ~1.2 % collision at 10 000 positions and 50 % at 77 000 — and because `exchange_order.client_order_id` is a global `PRIMARY KEY`, a collision is a fail-closed `record_intent` error, i.e. a position that silently will not open. D5 now specifies `pos16` (the **low** 64 bits, 62 effective after uuid v4's variant bits), and `JournalError::DuplicateClientOrderId` makes the impossible case loud rather than generic. Note the original flag overstated the impact: nothing *merges*, because §5.4's `position_id` column is the join key. |
| ~~Fill idempotency on `trade_id`~~ | **RESOLVED 2026-09-25.** Spec §3.5 now states it as a requirement with its reason — the fill-lag poll re-delivers every fill on every poll, so this is the ordinary path, not an edge case. Dedupe key aligned with `exchange_fill`'s `PRIMARY KEY (exchange, trade_id)`. |
| ~~`settle`'s real signature differs from spec §4.5~~ | **RESOLVED 2026-09-25.** live-trade-ops §4.5 amended: parameter is `assets`, and its "promote if `execution` needs it later" hedge replaced by a statement that D4 promotes it. `avg_price: Option<Decimal>` was already correct there. |

---

## Global Constraints

- **No implementation code in this plan.** Signatures and test descriptions only.
- **`cargo test` with no flags never touches the network.** Everything here is unit tests plus `wiremock`.
- **One commit per layer**, after that layer is green in Docker. **Commit only after explicit user confirmation** — stage, describe, wait.
- **Renames are compiler-forced, deliberately** (§3.2): `OpenPosition::size` → `net_size`, `open_price` → `intended_open_price`/`avg_entry_price`, `close_price` → `take_profit_price`. Every existing read site must be reviewed, not silently carried forward. Do not add aliases.
- **No new order or fill type** (§3.2). A fill is `exchange_adapter::Fill`; an order is `exchange_adapter::OrderInfo`. `OrderRole` is the only new type and it is an enum.
- **The account-event stream is a hint, never the authority** (§3.5). No code path may read a terminal status off an `AccountEvent`.
- **Nothing rests on the exchange for the target** (D7). `OrderRole` has no `TakeProfit` variant; assert this at review.

---

## Docker Entry Points

From `trade_executor/.worktrees/layer-implementation`:

```bash
# Every layer's gate. --build is mandatory (stale test image otherwise).
docker compose run --build --rm test

# One crate while iterating
docker compose run --build --rm test cargo test -p exchange_adapter
docker compose run --build --rm test cargo test -p execution
docker compose run --build --rm test cargo test -p local_analysis
```

Verified: [ ] `docker compose run --build --rm test` green on `position-core` at its cut point, before Layer 1 starts (baseline).

---

## Layer 1: `exchange_adapter` — shared primitives

Everything the later layers compile against. No new I/O.

### Task 1.1: Promote `settle` from `live_trade_ops`

**Files:** create `crates/exchange_adapter/src/settle.rs` (re-exported from `lib.rs`); delete `crates/live_trade_ops/src/settle.rs` and re-point its callers.

**Interface** (moved verbatim — this is a move, not a redesign; see spec §4.5 of the live-trade-ops design for the contract):
```rust
pub struct PairAssets { pub base: String, pub quote: String }
pub struct Settlement { pub filled_qty: Decimal, pub gross_quote: Decimal,
                        pub avg_price: Option<Decimal>, pub fees: Vec<(String, Decimal)>,
                        pub fee_in_quote: Option<Decimal>, pub effective_fee_rate: Option<Decimal>,
                        pub net_deltas: Vec<(String, Decimal)>, pub net_price: Option<Decimal>,
                        pub realized_pnl: Option<Decimal> }
pub fn settle(kind: MarketKind, assets: &PairAssets, side: Side, fills: &[Fill]) -> Settlement;
```
Transcribed from the **code** (`live_trade_ops/src/settle.rs`), not from spec §4.5,
which names the parameter `pair` and types `avg_price` as a bare `Decimal`. The
code is right — zero fills has no average price. See the red row above.

**Unit tests (RED first):** the existing `live_trade_ops` settle tests move with the function and must pass unchanged in meaning — each row of live-trade-ops §4.5's table, multi-fill orders, mixed maker/taker, a BNB fee (`fee_in_quote == None`), zero fills.

**Constraints:** `live_trade_ops` keeps working and now calls `exchange_adapter::settle`. `cargo tree -i live_trade_ops` must still show nothing depending on it.

### Task 1.3: Promote the order journal to `crates/order_journal`

**Why:** spec D5/§5.5 wrap the orchestrator's production account in `JournaledAccount`, and live-trade-ops §5.0 forbids any workspace crate depending on `live_trade_ops`. Decided 2026-09-25: the journal gets its own production crate, the same move Task 1.1 makes for `settle` (spec D4).

**Files:** create `crates/order_journal/` (`Cargo.toml`, `src/lib.rs` ← `live_trade_ops/src/journal/mod.rs`, `src/memory.rs`, `src/pg.rs`, `tests/pg_journal.rs`); add it to the workspace `members`; delete `crates/live_trade_ops/src/journal/` and `crates/live_trade_ops/tests/pg_journal.rs`; re-point `live_trade_ops`'s `lib.rs` re-export, `scenario_common.rs`, `margin_scenario.rs`, `futures_scenario.rs`, `harness/{mod,capped,settlement_check}.rs`, `tests.rs` and `tests/live_trade_ops.rs` at `order_journal::…`.

**Interface:** moved verbatim — same public items, same signatures, same behaviour; the module path changes from `live_trade_ops::journal::X` to `order_journal::X`. Dependencies: `exchange_adapter`, `observability`, `sqlx`, `async-trait`, `rust_decimal`, `uuid` (whatever the module uses today — no adapter crate, no `live_trade_ops`). Journal write failures keep raising `AlertKind::PersistFailed` with `component=order_journal` (live-trade-ops §4.7); no new `AlertKind` variant.

**Unit tests (RED first):** the journal's own unit tests and `pg_journal.rs` move with it and pass unchanged in meaning; `live_trade_ops`'s offline self-tests (cleanup-after-panic, touched rule, settlement, `record_intent` failure → nothing sent) still pass against the moved journal.

**Constraints:** no behaviour, schema or migration change — `0008` stays as is. `cargo tree -i live_trade_ops` lists no workspace crate; `cargo tree -i order_journal` lists `live_trade_ops` (and, once plan 3/9 lands, `orchestrator`); `cargo tree -p order_journal` contains no `exchange_adapter_binance`/`exchange_adapter_mexc`. `live_trade_ops/tests/no_adapter_imports.rs` still passes. Do it before plans 2/9 (Task 3.1 writes `position_id` in this crate) and 3/9 (Task 2.1 wraps the account with it).

### Task 1.2: `PositionId` and client-order-id minting

**Files:** `crates/exchange_adapter/src/lib.rs` (or `src/ids.rs`, re-exported).

**Interface:**
```rust
pub struct PositionId(pub uuid::Uuid);
pub enum OrderRole { Entry, Exit, Stop }   // no TakeProfit -- D7
pub fn mint_client_order_id(pos: PositionId, role: OrderRole, n: u32) -> String;
pub fn parse_client_order_id(s: &str) -> Option<(String, OrderRole, u32)>;  // for the journal/visualiser, never for position state
```

**Unit tests (RED):**
- Format is `x-{pos16}-{role}-{n}` with `role ∈ {e,x,s}` (D5), where `pos16` is the **last** 16 hex digits of the uuid with hyphens stripped — assert against a fixed uuid, and assert it is the low half, not the high half (the version nibble lives in the high half; taking it would cost 2 bits of entropy and would pass a careless test).
- Output is `[a-z0-9-]` only and ≤ 32 chars for `n` up to 11 digits. `n` beyond that is a programming error, not a runtime one — the counter is per position.
- **Collision volume**: 100k distinct `PositionId`s produce 100k distinct `pos16` values. At 62 bits this is expected to pass every time; the test exists so that shortening the prefix later fails loudly instead of quietly re-introducing the 32-bit birthday problem D5 was amended to remove.
- `parse_client_order_id` round-trips every minted id and returns `None` for a `livetest-…` id.

**Constraints:** `parse_client_order_id` exists for the journal and the visualiser only. §3.2 is explicit that position state must not recover `OrderRole` by parsing — enforce by review, and say so in the doc comment.

### Integration test → Layer 2 (RED in Docker)

In `crates/execution/tests/` (new file, RED until Layer 2 exists): construct an `OpenPosition` from two `Fill`s, call `settle` through `exchange_adapter`, and assert `avg_entry_price` equals `Settlement::avg_price` — the boundary being proved is that `execution` derives its averages from the adapter's settlement and never computes its own.

**Layer 1 gate:** `docker compose run --build --rm test` — Layer 1 unit tests green, the Layer 2 integration test RED (compiles, fails), everything else green. Commit (after user confirmation): `feat(exchange_adapter): promote settle and order journal, position id, client order ids`.

---

## Layer 2: `execution` types and pure transitions

No I/O whatsoever. This layer is a state machine and its tests are a truth table.

### Task 2.1: The types

**Files:** `crates/execution/src/types.rs`.

**Interface:** exactly §3.2's block — `PositionStatus { Flat, Opening, Open, Closing }`, `OpenPosition` with `entries`/`exits: Vec<Fill>`, `orders: Vec<(OrderRole, OrderInfo)>`, `pending_close: Option<CloseReason>`, `created_at`, `closed_at`, the leverage/margin group, and the intent/truth split. Plus:
```rust
pub enum CloseReason { Target, Stop, MainClose, Force, Reconcile, Timeout }
```

**Unit tests (RED):** every field of §3.2 exists with the stated type (compile-level); `OpenPosition` has no `size`/`open_price`/`close_price` field (a negative test that fails to compile is not a test — assert instead that `net_size`, `intended_open_price`, `avg_entry_price`, `take_profit_price` are all present and distinct); `OrderRole` has exactly three variants.

### Task 2.2: Resolution — the `Opening` exit

The heart of the plan. Pure function, no orders placed.

**Interface:**
```rust
pub enum Resolution { Flat { reason: String }, Open, Closing { reason: CloseReason } }
pub fn resolve_opening(entry: &OrderInfo, pending_close: Option<CloseReason>) -> Resolution;
```

**Unit tests (RED) — §3.1's table, exhaustively:**
- `Filled`, no pending close → `Open`; `Filled`, pending close → `Closing` carrying that reason.
- `Cancelled` with `filled_qty == 0` → `Flat`; `Cancelled` with `filled_qty > 0` → `Open` (**the timeout case — a partially filled cancelled entry is a position, not a non-event**).
- `Rejected` → `Flat`.
- `New`/`PartiallyFilled` → the function must not be callable, or must panic/return an error: resolution is only defined on a terminal status. Prefer a typed `TerminalOrderInfo` newtype over a runtime check, so "resolve a working order" cannot be written.
- Pending close of each `CloseReason` propagates unchanged.

### Task 2.3: Fill folding and averages

**Interface:**
```rust
impl OpenPosition {
    pub fn apply_fill(&mut self, role: OrderRole, fill: Fill);
    pub fn apply_settlement(&mut self, role: OrderRole, s: &Settlement);
    pub fn net_size(&self) -> Decimal;
    pub fn unrealized_pnl(&self, mark: Decimal) -> Option<Decimal>;
}
```

**Unit tests (RED):** entry fills grow `net_size` and set `avg_entry_price` as the quantity-weighted mean (not the arithmetic mean — a test with two fills of different sizes catches the difference); exit fills shrink it; `net_size` reaching exactly zero is representable and does not go negative; `apply_settlement` writes fees per asset and futures `realized_pnl`; `unrealized_pnl` is `None` with no entry fill and sign-correct for both sides; **applying the same fills repeatedly changes nothing** — `apply_fill` is idempotent on `(exchange, trade_id)`, per spec §3.5. This is not a defensive nicety: `get_order_fills` returns every fill on every poll and the fill-lag loop polls repeatedly by design, so re-delivery is the ordinary case, not the edge case. Test it by applying one `get_order_fills` response five times and asserting `net_size`, `avg_entry_price` and `fees` are identical to applying it once. Dedupe key matches `exchange_fill`'s `PRIMARY KEY (exchange, trade_id)` — `trade_id` is unique per exchange, not globally.

### Integration test → Layer 3 (RED in Docker)

`crates/execution/tests/lifecycle.rs`: drive a position through open → partial fill → terminal entry → resolution → close → flat against a fake `MarketAccount`, asserting the **status sequence** is exactly `Opening, Opening, Open, Closing, Flat` — i.e. that a partial fill did not move the status. RED until Layer 3.

**Layer 2 gate:** unit tests green, Layer 3 integration test RED. Commit: `feat(execution): fill-driven position types and Opening resolution`.

---

## Layer 3: `execution` behaviour

### Task 3.1: Order choreography (§3.4)

**Files:** `crates/execution/src/engine.rs`.

**Interface:** unchanged `ExecutionEngine` trait. Internals change: `open_position` places the entry and stops; `resolve_entry` places the stop (resolution `Open`) or the exit (resolution `Closing`) or nothing (`Flat`); `do_close` records `pending_close` when `Opening` and otherwise cancels the stop and places the exit.

**Unit tests (RED):** placing an entry sends exactly one order and no stop; resolution `Open` sends exactly one stop, sized to the final filled quantity; resolution `Closing` sends an exit and **no stop**; resolution `Flat` sends nothing; a close arriving while `Opening` sends nothing and sets `pending_close`; `do_close` on `Open` cancels exactly one order (there is no target order to cancel).

### Task 3.2: `run_fill_sync` (§3.5)

**Interface:**
```rust
pub async fn run_fill_sync(self: Arc<Self>, pair: Pair, shutdown: watch::Receiver<bool>);
```

**Unit tests (RED):**
- An `AccountEvent::OrderUpdate` matching a tracked `client_order_id` triggers a poll of *that* order.
- An event matching nothing, or carrying `client_order_id: None`, triggers a poll of **all** non-terminal tracked orders (the MEXC/Binance gap — §3.5).
- **With no account events at all**, the `ORDER_POLL_INTERVAL_SECS` poll alone carries a position from `Opening` to `Flat` through a full cycle. This is the Binance vanished-order case and is the single most important test in this plan.
- Terminal status is taken only from `get_order`; a fake feeding a stale `Filled` on the event stream while `get_order` says `New` must leave the position `Opening`.
- `get_order_fills` is polled until `Σ qty == filled_qty` or 10 s; on timeout, `settlement_complete` stays `false` and an alert fires.
- `NotSupported` from `get_order_fills` → `settlement_complete: false`, fees empty, no fabricated number.

### Task 3.3: Target trigger and timeouts (§3.4, D7)

**Unit tests (RED):** a designated exit `SignalEvent` closes an `Open` position and emits `TargetHit`; `take_profit_price` reached with no signal also closes it (backstop); both go through `do_close`; **no order is ever placed with role `Stop` at the target price** and no `t` role exists; `ENTRY_FILL_TIMEOUT_SECS` cancels a working entry and lets resolution decide (partial → `Open`); `EXIT_FILL_TIMEOUT_SECS` re-places the exit and alerts on the second escalation, never converting to market.

### Task 3.4: Unrealized P&L and liquidation proximity (§3.6)

**Unit tests (RED):** `run_advisor_loop` updates `unrealized_pnl` per tick; `position_risk` refresh honours `POSITION_RISK_POLL_SECS`; `LiquidationNear` fires once per crossing at `LIQUIDATION_WARN_FRACTION` and not again while still near; spot positions never fire it (no liquidation price).

**Layer 3 gate:** Layer 2's integration test GREEN, all unit tests green. Commit: `feat(execution): fill-driven lifecycle, poll-authoritative fill sync, local target`.

---

## Layer 4: `local_analysis`

### Task 4.1: `OpenPositionView` additions (§4)

**Interface:** `OpenPositionView` gains `avg_entry_price: Option<Price>`, `net_size: Decimal`, `unrealized_pnl: Option<Decimal>`.

**Unit tests (RED):** `DefaultPositionAdvisor`'s output is **unchanged** for every existing test input — the fields are supplied, not yet used, and a behaviour change here would be out of scope.

**Constraints:** B7/B8 are **not** in this plan. `DefaultSignalBuilder` is untouched; `PLACEHOLDER_STOP_LOSS_PCT` stays; `DecisionKind::Modify` still resolves to `NoOp`. See [../TECH_DEBT.md](../TECH_DEBT.md) §10.

**Layer 4 gate:** `docker compose run --build --rm test` fully green. Commit: `feat(local_analysis): realised-risk fields on OpenPositionView`.

---

## Done when

- [ ] Every layer gate green in Docker, in order.
- [ ] Spec acceptance criteria satisfied by this plan's tests: "no position state transition caused by a `place_order` return value"; "a position resolves with the account-event stream disabled entirely"; "a partially filled entry stays `Opening` … exactly one stop order"; "a close arriving while `Opening` is held as `pending_close`"; "an entry cancelled by timeout after a partial fill resolves to `Open`"; "no order is ever placed for the target"; "`settle`'s fee arithmetic exists in exactly one place".
- [ ] `position-core` merged into `position-management` (after user confirmation).
