# Position Management 3/9 — Orchestration (`orchestrator`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan layer-by-layer. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the fill-driven position into the running process — every production order journalled before it is sent, every state change appended, drift detected while running rather than only at boot, and the position's behaviour observable in metrics and alerts.

**Spec:** [`2026-09-22-position-management-design.md`](../specs/2026-09-22-position-management-design.md) §3.5 (task spawn), §5.5, §7.2, §7.3, decisions D5, D8, D11 (deleting the A20 guard).

**Scope:** `crates/orchestrator`, plus `JournalError::DuplicateClientOrderId` in `crates/order_journal` (red row below). **No** new types, **no** schema, **no** wire, **no** UI.

**Depends on:** plans 1/9 and 2/9 merged into `position-management`.

**Blocked on:** [../TECH_DEBT.md](../TECH_DEBT.md) §8 — the `JournaledAccount`/`OrderJournal` review (state row vs. append-only action log, cancels not write-before-send, naming). §5.5 wraps the **production** account in that decorator, so the review's outcome changes what is persisted for every real order. **Resolved:** design 2026-09-23 (build as specified); placement 2026-09-25 (own crate `order_journal`, spec D5, moved by plan 1/9 Task 1.3).

**Branch:** `position-orchestration`, cut from `position-management`, merged back into it.

## Readiness review

Verified against the code on `layer-implementation` @ `ff2938d` and `live-trade-ops` @ `e45dc05` (2026-09-25).

🟢 **green** — exists in the system, small update · 🟡 **yellow** — in the spec, small code change · 🟠 **orange** — in the spec, large code change · 🔴 **red** — in neither code nor spec

### 🟢 Green

| Item | Where it is today | Change |
|---|---|---|
| `run_position_sync`, `boot`, per-pair task spawning, the shutdown watch | `orchestrator/src/system.rs` | one call replaces two; one task added |
| `NoTradeAccount` + `EXECUTION_MODE` | `orchestrator/src/{no_trade.rs,main.rs}` | unchanged; the journal wraps outside it |
| `Metrics` / `MetricEvent::new().with_tag()` / `Alerts` / `AlertEvent` | `observability/src/lib.rs` | reused as-is |
| Boot-time `reconcile` (step 5) | `system.rs` | unchanged; gains a periodic sibling |
| The already-open guard and its long justification comment | `system.rs` `run_signal_decision_task` | **deleted** — D11 removed the hazard it guarded |

### 🟡 Yellow

The periodic reconcile task and `RECONCILE_INTERVAL_SECS` · `AlertKind::PositionDrift` (spec §7.3; today `AlertKind` has `FeedStale`, `BookCrossed`, `FeedDisconnected`, `OrderPlacementFailed`, `LiquidationNear`, `PersistFailed`, `AlertChannelDead` — verified) · the ten metric names of §7.2.

### 🟠 Orange

| Item | Why it is large |
|---|---|
| Wrapping the production account in `JournaledAccount` | see the red row below — this is not just a constructor line |
| `run_position_sync` collapsing to one append | its trigger semantics change: an account event for a pair with no live position must now produce **no** write, where today it re-persists an unchanged snapshot |

### 🔴 Red

| Item | Status |
|---|---|
| ~~**`orchestrator` cannot depend on `live_trade_ops`**~~ **RESOLVED 2026-09-25** | **Resolution:** the journal is promoted to a new production crate `crates/order_journal` (spec D5 + §5.5, live-trade-ops §5.0 amended); plan 1/9 Task 1.3 does the move; `orchestrator` depends on `order_journal`, never on `live_trade_ops`. Original finding: **Real conflict, and the biggest finding of this review.** §5.5 of the position spec says to wrap the production account in `JournaledAccount` with `origin = "execution"`. But `JournaledAccount`, `OrderJournal` and `PgOrderJournal` live in `crates/live_trade_ops`, whose own spec (live-trade-ops §3, §5.0) requires that **no workspace crate depends on it**, enforced by the acceptance criterion `cargo tree -i live_trade_ops` returning nothing. Verified: they are in `live_trade_ops/src/journal/`. Neither spec resolved it at review time. The extraction is mechanical — types move unchanged, their tests move with them, `live_trade_ops` keeps its no-dependents property, `orchestrator` gains the decorator — and lands before any production wrapping. TECH_DEBT §8's review still stands on the journal's *design*; this settles only where it lives. |
| ~~**`AlertKind::OrderJournalWriteFailed`**~~ **RESOLVED 2026-09-25** | Not a variant and not meant to be one: live-trade-ops §4.7 already specifies `AlertKind::PersistFailed` with `component=order_journal` and `OrderJournalWriteFailed:` in the message, and the code does exactly that (`journal/mod.rs`, `journal/pg.rs`). Kept after the move to `order_journal` — match it, add no variant. |
| **`JournalError::DuplicateClientOrderId`** | Added by D5's 2026-09-25 amendment. Today `JournalError` has exactly `Write(String)` and `BackwardTransition { .. }` (verified), so a primary-key violation on `client_order_id` arrives as an untyped `Write` — indistinguishable from a disk error. `PgOrderJournal::record_intent` must map Postgres SQLSTATE `23505` to the new variant and alert at `Severity::Critical`. Lands in `crates/order_journal` (see the row above) — the one edit this plan makes outside `crates/orchestrator`. |
| The journal's real surface is richer than either spec drew | `record_submit_unknown`, `JournalContext`, an internal `order_id_map`, an `Alerts` dependency, and `JournaledAccount` as a concrete struct rather than the spec's generic `<A, J>`. Not a gap — a note, so the wrapping task codes against the real type. |

---

## Global Constraints

- **Fail closed on the journal** (§5.5, live-trade-ops §4.7): no order is sent unless `record_intent` committed.
- **Isolate and report, keep running** — the posture every existing task in `system.rs` uses. A persist failure alerts and continues; only a journal failure blocks a send.
- **Deleting the already-open guard is part of this plan, not a side effect** (D11). It exists only because `open_position` used to overwrite `positions[pair]`; plan 1/9 removed that. The **cooldown guard stays** — signal pacing is a different concern.
- **One commit per layer**, green in Docker, **after explicit user confirmation**.

---

## Docker Entry Points

```bash
docker compose run --build --rm test
docker compose run --build --rm test cargo test -p orchestrator
docker compose up -d --build postgres executor
docker compose logs -f executor        # boot sequence, reconcile report, alerts
```

Verified: [ ] baseline green on the branch before Layer 1.

---

## Layer 1: Task wiring

### Task 1.1: `run_position_sync` collapses to one append

**Files:** `crates/orchestrator/src/system.rs`.

**Interface:** unchanged signature; body calls `state_store.append_position(&entry)` once per trigger in place of `persist` + `log_event`.

**Unit tests (RED):** one trigger produces exactly one append; an account-event trigger for a pair with no live position produces **none** (today it re-persists an unchanged snapshot — that is exactly the no-op write §5.1 forbids); an append failure alerts `PersistFailed` and the loop continues; shutdown never cuts off an append already in flight.

### Task 1.2: Spawn `run_fill_sync`

**Interface:** one task per pair, alongside `run_stop_loss_watcher` and `run_advisor_loop`, same `tokio::select!`-against-`shutdown` shape.

**Unit tests (RED):** the task is spawned once per configured pair; it stops on shutdown; a panic in one pair's task does not take down another's.

### Task 1.3: Delete the already-open guard (D11)

**Files:** `system.rs` `run_signal_decision_task`.

**Unit tests (RED):** a crossing on a pair with an open position now produces a **scale-in decision**, not a `mock_signal_crossing_skipped{reason=position_already_open}`; the cooldown guard still skips and still records; the long doc comment justifying the guard is removed rather than left to mislead.

**Layer 1 gate:** `cargo test -p orchestrator` green. Commit: `feat(orchestrator): single-append position sync, fill sync task, drop already-open guard`.

---

## Layer 2: Journalled production orders

### Task 2.1: Wrap the account

**Interface:** `orchestrator` gains a dependency on `order_journal` (never `live_trade_ops`); boot builds `order_journal::JournaledAccount::new(NoTradeAccount-or-real, order_journal::PgOrderJournal, origin: "execution")` — journal **outside** the disarm decorator, so a refused order is journalled as `rejected: Disarmed` (§5.5: an operator asking "did it try?" gets an answer).

**Integration test (RED in Docker):** with `EXECUTION_MODE=no_trade`, drive one decision and assert an `exchange_order` row exists with `status = 'rejected'`, `reject_reason = 'Disarmed'`, `origin = 'execution'` and a non-null `position_id`. Then with a wiremock exchange and `EXECUTION_MODE=live`, assert the intent row is committed **before** the HTTP request is observed.

**Unit tests (RED):** `record_intent` failure → no order sent, error returned; a `Network` send failure leaves `submitted_unknown`; `record_ack` failure raises `AlertKind::PersistFailed` (`component=order_journal`) and returns the error; every `client_order_id` written parses back to the position that minted it.

**Layer 2 gate:** integration test green in Docker; `cargo tree -i live_trade_ops` still lists no workspace crate. Commit: `feat(orchestrator): journal every production order before sending it`.

---

## Layer 3: Continuous reconciliation (D8)

### Task 3.1: Periodic reconcile

**Interface:** one task, `RECONCILE_INTERVAL_SECS` (default 60), calling the existing `StateStore::reconcile` against a fresh `get_account_state`, then `record_reconciliation`.

**Unit tests (RED):** runs on the interval and at boot; `NoDiscrepancy` writes a `reconciliation_log` row and **no** `position_log` row (§5.1); a real correction writes both; a failure to read local state alerts and does not abort the loop; `last_reconciliation()` still serves the in-memory read.

### Task 3.2: `PositionDrift` alert

**Interface:** new `observability::AlertKind::PositionDrift`.

**Unit tests (RED):** fires only on a non-`NoDiscrepancy` outcome found by the **periodic** run (a boot-time discrepancy is expected after a crash and already reported); carries the pair and the outcome; distinct from `PersistFailed`, whose operator response is "retry" where this one's is "stop and look" (§7.3).

**Layer 3 gate:** `docker compose up -d executor` with a hand-closed position on the exchange produces the alert and the corrected state. Commit: `feat(orchestrator): continuous reconciliation with a durable record`.

---

## Layer 4: Observability

### Task 4.1: Metrics (§7.2)

**Interface:** `position_opened`, `position_closed{close_reason}`, `position_realized_pnl`, `position_fees_quote`, `position_hold_secs`, `fill_latency_ms`, `slippage_bps`, `entry_unfilled`, `exit_escalated`, `reconcile_discrepancy{outcome}` — all through the existing `Metrics`/`MetricEvent` with `pair` + `side` tags.

**Unit tests (RED):** one metric per lifecycle transition, emitted exactly once; `slippage_bps` is `avg_entry_price` against `intended_open_price` and is signed (a favourable fill is negative slippage, not an absolute value); `position_hold_secs` derives from `created_at` → `closed_at`.

### Task 4.2: Alert producers (§7.3)

**Unit tests (RED):** `LiquidationNear` reaches the alert sink from `execution`'s loop (plan 1/9 raises it; this task proves it is wired); entry-unfilled and exit-unfilled escalations alert at the stated severities.

**Layer 4 gate:** full suite green; `docker compose logs executor` shows the new metric lines on a paper cycle. Commit: `feat(orchestrator): position metrics and alert producers`.

---

## Done when

- [ ] Every layer gate green in Docker, in order.
- [ ] Spec acceptance criteria satisfied here: "every order the orchestrator sends has a row in `exchange_order` with `origin = 'execution'` and a non-null `position_id`, committed before the send"; "boot reconcile and the periodic reconcile both write `reconciliation_log` rows"; "a scale-in against an `Open` position leaves the status `Open`".
- [ ] `position-orchestration` merged into `position-management` (after user confirmation).
