# Position Management 2/9 — Persistence (`db_schema`, `state_store`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan layer-by-layer. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the one-row-per-pair `position_state` snapshot with an append-only `position_log` in which every row is evidence that something happened — closing the "a closed position leaves no record" gap and the "a failed write leaves the on-disk row confidently wrong" failure mode in the same change.

**Spec:** [`2026-09-22-position-management-design.md`](../specs/2026-09-22-position-management-design.md) §5 (whole), decision D12, audit rows C1/C2/C6, D8's `reconciliation_log`.

**Scope:** `migrations/0009_position.sql`, `crates/db_schema`, `crates/state_store`. **No** orchestrator call sites (plan 3/9), **no** read routes (plan 7/9).

**Depends on:** plan 1/9 (`position-core`) merged into `position-management` — the DTO mirrors need `OpenPosition`'s final shape. **The SQL half has no such dependency** and may be written and reviewed first; only the Rust half blocks.

**Blocks:** plans 3/9 and 7/9.

**Branch:** `position-persistence`, cut from `position-management`, merged back into it.

**Note on layer taxonomy:** see plan 1/9 — principles of `layer-first-planning` applied over the executor's real crate layers.

## Readiness review

Verified against the code on `layer-implementation` @ `ff2938d` and `live-trade-ops` @ `e45dc05` (2026-09-25).

🟢 **green** — exists in the system, small update · 🟡 **yellow** — in the spec, small code change · 🟠 **orange** — in the spec, large code change · 🔴 **red** — in neither code nor spec

### 🟢 Green

| Item | Where it is today | Change |
|---|---|---|
| `StateStore` trait, `StateStoreImpl`, `PgStateReader` | `state_store/src/{lib,pg}.rs` | trait surface changes; the sync-durability machinery is reused |
| `dto.rs` mirrors + round-trip tests | `state_store/src/dto.rs` | extended field-for-field |
| Migration runner, `SCHEMA_VERSION`, `migrations/0001`–`0008` | `db_schema` | one new migration; nothing edited |
| `global_ins_seq`, `side_enum` | `migrations/0001_init.sql` | reused by `position_log` |
| `reconcile`, `ReconciliationReport`, `ReconciliationOutcome` | `state_store/src/lib.rs` | unchanged; gains a durable sink |

### 🟡 Yellow

Migration `0009` DDL and the two views · `reconciliation_log` · `PositionLogEntry` · the `PersistFailed` alert-text rewrite and the `state_store` module-doc rewrite (both required by §5.2/§5.3 and both easy to forget precisely because they are prose).

### 🟠 Orange

| Item | Why it is large |
|---|---|
| `append_position` replacing `persist` + `log_event` | removed from the trait, not deprecated — deliberate compiler errors at every call site in `orchestrator`, `visualizer_backend` and the test suites |
| `load_all` reimplemented over `position_current` | boot recovery changes its source; the equivalence test against a restored dump is the gate |
| DTO extension to the whole new `OpenPosition` | `Vec<Fill>`, `Vec<(OrderRole, OrderInfo)>`, `pending_close`, the leverage group — one round-trip test per field |
| The backfill | must use each row's own timestamp, not `now()`; getting this wrong makes every recovered position look like it changed at migration time |

### 🔴 Red

| Item | Status |
|---|---|
| ~~Migration number for `exchange_order.position_id`~~ | **RESOLVED 2026-09-25.** Folded into `0009`, one bump, 8 → 9 — matching §5.1's budget and §11's layer row, which already read "Migration 0009 … **and** 0008's `position_id` column". `0010` was invented by this plan and is withdrawn. Renamed **`0009_position.sql`** because it now creates three objects *and* alters `exchange_order`. Nothing else in any spec or plan claims `0009` or `0010`; `0008` is the highest on disk. |
| `PositionLogEntryDto`, and the grep-for-`UPDATE`/`DELETE` check | implementation detail; no amendment needed |

---

## Global Constraints

- **Additive migrations only.** Never edit `0001`–`0008` (sqlx checksums; see `0002`'s header). `SCHEMA_VERSION` 8 → 9.
- **`position_state` and `event_log` are retired, not dropped** (§5.2). No new writes; rows left in place; no `DROP TABLE` anywhere in this plan. Dropping a table that holds the only record of a position this system may still be holding is data loss, not a migration.
- **A row means something changed** (§5.1). No heartbeat row. No `NoDiscrepancy` reconcile row. No periodic unrealized-P&L row.
- **`position_log` is append-only in practice, not just in intent.** No `UPDATE` or `DELETE` statement against it may exist in `state_store`; this is a grep-checkable acceptance criterion.
- **One commit per layer**, after green in Docker, **after explicit user confirmation**.

---

## Docker Entry Points

```bash
docker compose run --build --rm test
docker compose run --build --rm test cargo test -p db_schema
docker compose run --build --rm test cargo test -p state_store
docker compose run --rm executor --migrate-only        # reaches 0009 (the only bump in this plan)
docker compose exec -T postgres psql -U executor -d trader -c '\d position_log'
```

Verified: [ ] baseline `docker compose run --build --rm test` green on the branch before Layer 1.

---

## Layer 1: Schema

### Task 1.1: Migration `0009_position.sql`

**Files:** `migrations/0009_position.sql`, `crates/db_schema/src/lib.rs` (`SCHEMA_VERSION` 8 → 9).

Includes §5.4's `ALTER TABLE exchange_order ADD COLUMN position_id uuid` and its index — one migration, one bump. Task 3.1 below keeps only the Rust-side writer change.

**Interface:** exactly §5.1's DDL — `position_log` (append-only, hot columns denormalised out of a full `state` jsonb), views `position_current` and `position_history`, table `reconciliation_log`, and the three indexes.

**Integration test → Layer 2 (RED in Docker):** `crates/db_schema/tests/migrations.rs` — migrate a fresh database to 9; assert `position_log` exists with every column of §5.1 at the stated type; assert `position_current` returns one row per pair and that it is the **highest `seq`** for that pair (insert three rows for one pair out of timestamp order and check the view picks the right one — this is the test that catches ordering by `recorded_at` instead of `seq`); assert `position_history` returns one row per `position_id` with `created_at` = the minimum `recorded_at`.

**Unit tests (RED):**
- Migrating an **existing** database at version 8 reaches 9 without touching 0001–0008 checksums.
- The backfill (§5.2) turns every `position_state` row into exactly one `position_log` row with `event = 'reconciled'` and the row's own timestamp — **not** `now()`, which would make every recovered position look like it changed at migration time.
- A database with zero `position_state` rows migrates cleanly (fresh install).
- `dashboard` has `SELECT` on `position_log`, both views and `reconciliation_log` through the existing default privileges — asserted, not assumed, since §5.1 claims it.

**Constraints:** `global_ins_seq` is the sequence (§5.1) — `seq` must order against `trade`/`candle`/`signal_log` without a clock comparison. `position_id` is nullable (a `not_placed` with no position).

**Layer 1 gate:** `docker compose run --rm executor --migrate-only` reaches 9; migration tests green; Layer 2's store tests RED. Commit: `feat(db_schema): migration 0009 position_log, views, reconciliation log`.

---

## Layer 2: `state_store` write and read paths

### Task 2.1: DTO mirrors

**Files:** `crates/state_store/src/dto.rs`.

**Interface:** `PositionStateDto`/`OpenPositionDto` extended field-for-field with plan 1/9's `OpenPosition` — `entries`/`exits` as `Vec<FillDto>`, `orders` as `Vec<(OrderRoleDto, OrderInfoDto)>`, `pending_close`, `created_at`, the leverage group. New `PositionLogEntryDto`.

**Unit tests (RED):** a round-trip test **per new field** (§5.3 names this as the RED test for the task); an `OpenPosition` with empty `entries`/`exits`/`orders` round-trips; an unknown variant in stored jsonb reads back as a cache miss, not a panic — matching the existing "missing and corrupt both read as absent" contract.

### Task 2.2: `append_position` replaces `persist` + `log_event`

**Interface:**
```rust
pub struct PositionLogEntry { pub pair: Pair, pub position_id: Option<PositionId>,
                              pub event: PositionStateEvent, pub state: PositionState, pub recorded_at: Ts }

async fn append_position(&self, entry: &PositionLogEntry) -> Result<(), StoreError>;
async fn load_all(&self) -> Result<Vec<PositionState>, StoreError>;                 // over position_current
async fn read_position_log(&self, pair: Pair, from: Ts, to: Ts) -> Result<PositionLogStream, StoreError>;
async fn read_position_history(&self, pair: Pair, from: Ts, to: Ts) -> Result<PositionHistoryStream, StoreError>;
async fn read_position(&self, id: PositionId) -> Result<Option<PositionLogStream>, StoreError>;
async fn record_reconciliation(&self, report: &ReconciliationReport, at: Ts) -> Result<(), StoreError>;
```
`persist` and `log_event` are **removed from the trait**, not deprecated — a compiler error at every call site is the point.

**Integration test → plan 3/9 (RED in Docker):** `crates/state_store/tests/pg_store.rs` — append a full lifecycle (`opened`, `partially_filled`, `filled`, `closed`), then assert: `load_all` returns the terminal state; `read_position_log` returns all four rows in `seq` order with the event *and* the state on each; `read_position_history` returns one row; and — the durability property — a simulated failure of the third append leaves rows 1–2 intact and row 4 still appendable, with the current state correct after it.

**Unit tests (RED):**
- The event and the state land in **one row and one commit**; there is no interleaving in which one is written and the other is not (§5.3's whole reason).
- Committed before return, same contract as `log_decision`.
- `record_reconciliation` writes one `reconciliation_log` row per pair checked, **including** `NoDiscrepancy` — that table is the record of checks.
- `append_position` is **not** called for a `NoDiscrepancy` reconcile (§5.1) — assert zero `position_log` rows after a clean reconcile of a pair with an open position.
- `load_all` after the 0009 backfill returns exactly what the old `persist`-based reader returned on the same data (the acceptance criterion; run both against one restored fixture).
- No `UPDATE`/`DELETE` against `position_log` anywhere in the crate (`grep`, asserted in a test or a CI check).

### Task 2.3: Alert text and module doc

**Constraints (§5.3):** the `PersistFailed` alert text changes meaning and must be rewritten — on-disk state is no longer *stale*, it is *missing a step*, and the next successful append restores a correct current state on its own. `state_store`'s module doc, which currently explains why `position_state` is "not an append-only log", is rewritten to say why it now is one and where its predecessor went.

**Layer 2 gate:** `docker compose run --build --rm test` green; the plan-3/9 integration test above GREEN (it needs no orchestrator). Commit: `feat(state_store): append-only position log replacing the snapshot`.

---

## Layer 3: Additive change to 0008

### Task 3.1: `exchange_order.position_id` — writer side

**Files:** `crates/order_journal/src/pg.rs` writer (moved there by plan 1/9 Task 1.3). **No migration file** — the column and its index ship in `0009` (Task 1.1), folded there on 2026-09-25.

**Interface:** `OrderIntent` gains `position_id: Option<PositionId>`; `record_intent` persists it into the column `0009` created.

**Unit tests (RED):** a journalled order with a `position_id` round-trips; a `livetest` order with `NULL` still writes and reads; querying an order by `position_id` returns it without any `client_order_id LIKE` pattern — §5.4 is explicit that joining by string prefix "would work and would be the wrong thing to leave in a schema".

**Constraints:** no `SCHEMA_VERSION` change — Task 1.1 already took it to 9. The journal lives in `crates/order_journal` since 2026-09-25 (spec D5 + §5.5) — edit it there, never in `live_trade_ops`.

**Layer 3 gate:** full suite green; an order journalled by `orchestrator` carries its `position_id`. Commit: `feat(order_journal): link journalled orders to positions`.

---

## Done when

- [ ] Every layer gate green in Docker, in order.
- [ ] Spec acceptance criteria satisfied here: "`position_log` is append-only in practice"; "`load_all` after migration 0009 returns exactly what it returned before"; "a killed process between two appends leaves the last good row intact"; "a closed position leaves a terminal `position_log` row … and exactly one row in `position_history`".
- [ ] `position-persistence` merged into `position-management` (after user confirmation).
