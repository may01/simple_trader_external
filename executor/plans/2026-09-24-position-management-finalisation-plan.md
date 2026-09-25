# Position Management 9/9 — Finalisation: integration, spec validation, live acceptance

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking. **This plan is also the index for the other eight** — read this first.

**Goal:** Turn eight independently-built branches into one shipped system: integrate them, prove every acceptance criterion in [`2026-09-22-position-management-design.md`](../specs/2026-09-22-position-management-design.md) §10 is actually met by a test that ran (not by a plan that claimed it), catch the drift that only shows up where two plans meet, and take it live under a human gate.

**Spec:** the whole of [`2026-09-22-position-management-design.md`](../specs/2026-09-22-position-management-design.md). This plan owns §10 end to end.

---

## The eight plans

| # | Plan | Repo / crates | Depends on | Branch |
|---|---|---|---|---|
| 1/9 | [Position core](2026-09-24-position-core-plan.md) | `exchange_adapter`, `execution`, `local_analysis` | live-trade-ops merged | `position-core` |
| 2/9 | [Persistence](2026-09-24-position-persistence-plan.md) | `db_schema`, `state_store`, migrations | 1/9 (Rust half only) | `position-persistence` |
| 3/9 | [Orchestration](2026-09-24-position-orchestration-plan.md) | `orchestrator` | 1/9, 2/9, TECH_DEBT §8 | `position-orchestration` |
| 4/9 | [Wire v2](2026-09-24-position-wire-v2-plan.md) | `mq_gateway` | 1/9 | `position-wire-v2` |
| 5/9 | [main/ order disarm](2026-09-24-main-order-disarm-plan.md) | **`main/`** | — | `main-order-disarm` |
| 6/9 | [main/ position consumer](2026-09-24-main-position-consumer-plan.md) | **`main/`** | 5/9, 4/9's fixtures | `main-position-consumer` |
| 7/9 | [Visualiser backend](2026-09-24-position-visualiser-backend-plan.md) | `visualizer_backend`, `visualizer_server` | 2/9 | `position-visualiser-backend` |
| 8/9 | [Visualiser frontend](2026-09-24-position-visualiser-frontend-plan.md) | `static/` | 7/9's fixtures | `position-visualiser-frontend` |

Two repositories. Plans 1–4, 7, 8 land on the integration branch `position-management`, cut from `layer-implementation` in `trade_executor/.worktrees/layer-implementation`. Plans 5 and 6 land on `experimental_imp_2` in `main/`.

### What makes them independent

Each plan owns a disjoint set of files, and every cross-plan boundary is a **committed contract artefact**, not a conversation:

- 4/9 → 6/9: golden wire fixtures (`crates/mq_gateway/tests/fixtures/*.json`).
- 7/9 → 8/9: committed route-response fixtures.
- 1/9 → 2/9, 3/9, 4/9: the Rust type signatures in spec §3.2.
- 2/9 → 3/9, 7/9: the `StateStore` trait in spec §5.3 and the DDL in §5.1.

A plan may be implemented against its contract artefact without its dependency being merged, and often should be.

### Schedule

```
Wave A (start together, no dependencies between them)
  ├─ 5/9  main/ order disarm        ← start FIRST; until it lands, two processes can place orders
  └─ 1/9  Position core              ← blocked only by live-trade-ops merging

Wave B (after 1/9)
  ├─ 2/9  Persistence                (SQL half can start in Wave A)
  └─ 4/9  Wire v2

Wave C
  ├─ 3/9  Orchestration              (after 2/9; also needs TECH_DEBT §8 resolved)
  ├─ 7/9  Visualiser backend         (after 2/9)
  └─ 6/9  main/ consumer             (after 5/9 + 4/9's fixtures)

Wave D
  └─ 8/9  Visualiser frontend        (after 7/9)

Wave E
  └─ 9/9  this plan
```

**5/9 first, before anything else.** It is the only plan with no dependencies, and it is the only one that removes a live hazard rather than adding capability.

## Readiness review

Verified against the code on `layer-implementation` @ `ff2938d` and `live-trade-ops` @ `e45dc05` (2026-09-25).

🟢 **green** — exists in the system, small update · 🟡 **yellow** — in the spec, small code change · 🟠 **orange** — in the spec, large code change · 🔴 **red** — in neither code nor spec

### 🟢 Green

The integration machinery all exists: `docker compose run --build --rm test`, `--migrate-only`, the compose stack, the live-run env-file pattern and the human-gate posture (`configs/live-trade-ops/*.env`, live-trade-ops Layer 7), and `scripts/e2e_indicator_broadcast.py` as the model for cross-project end-to-end checks.

### 🟡 Yellow

The §10 evidence table · the drift-audit greps · the merge sequence.

### 🟠 Orange

| Item | Why it is large |
|---|---|
| The full-cycle cross-layer test | the only test in the set that spans every plan at once, asserting `position_log`, `exchange_order`/`exchange_fill`, the wire message and `/api/positions` at each step — **with the account-event stream disabled** |
| The four live runs | real money, four distinct failure surfaces, one human gate each |
| The four-way `OpenPosition` mirror diff | `execution`, `state_store` DTO, `visualizer_server` DTO, wire `position_state` — written by four plans; a field present in three is silent data loss |

### 🔴 Red

| Item | Status |
|---|---|
| **Two blocking resolutions this plan inherits and cannot itself decide** | (1) plan 3/9's `orchestrator` → `live_trade_ops` dependency conflict — **resolved 2026-09-25**: journal promoted to `crates/order_journal` (spec D5, plan 1/9 Task 1.3); (2) plan 2/9's migration number for `exchange_order.position_id`. Both are **spec amendments**, both must land before their owning plan starts, and neither is discoverable from the finalisation layer — which is the point of having done this review before any code. |
| **Deployment-compatibility check has no test** | Layer 5 asks for confirmation that the two repositories' deployed versions are compatible — an armed `main/` against a live executor, or 6/9's consumer against an executor without wire v2. Nothing can assert this from inside either repo. It stays a human checklist item, and it is the residual risk of shipping across two deployments. |
| Spec amendments surfaced by this review | `pos8` collision bound, `apply_fill` idempotency, `settle`'s real signature, migration numbering, the journal's home (done 2026-09-25 — `order_journal`), the sync point in main/'s tick. Fold them into the spec **before** Wave A, not during Layer 5. |

---

## Global Constraints

- **This plan writes no feature code.** If a criterion fails here, the fix goes back to the owning plan's branch and that plan's gate is re-run. Patching it in the integration branch hides which plan is wrong.
- **A criterion is met when a test ran and passed**, not when a plan claimed it. Every row of §10 below records *where the evidence is*.
- **Live runs spend real money.** Every run in Layer 4 is a separate human gate: stop, show the env file (keys redacted) and the banner, wait for an explicit "go" for *that* run.
- **Merges to `layer-implementation` and `experimental_imp_2` require explicit user confirmation**, as does every push.

---

## Docker Entry Points

```bash
# executor workspace
docker compose run --build --rm test                      # full Rust suite
docker compose run --rm executor --migrate-only           # reaches 0009
docker compose up -d --build postgres executor visualizer

# main/
docker compose run --rm --no-deps live python3 -m pytest tests/ -q
python3 scripts/e2e_position_round_trip.py --cold

# live (Layer 4, human-gated, one at a time)
docker compose --env-file configs/position/binance.margin.mainnet.env up -d executor
```

---

## Layer 1: Integration

### Task 1.1: Assemble `position-management`

- [ ] Merge 1/9, 2/9, 4/9, 3/9, 7/9, 8/9 into `position-management` in that order, running `docker compose run --build --rm test` after **each** merge, not once at the end. A conflict between two plans is cheap to find after one merge and expensive after five.
- [ ] `docker compose run --rm executor --migrate-only` reaches schema 10 on a database restored from a pre-migration dump.
- [ ] `main/`: 5/9 then 6/9 merged to `experimental_imp_2`, `pytest tests/ -q` green after each.

### Task 1.2: Cross-plan drift audit

Things no single plan's tests can catch, because each side looks correct alone:

- [ ] **Wire fixtures still match the encoder.** Re-run 4/9's byte-stability test after all merges; then re-run 6/9's decoder tests against the *current* fixtures, not the copied ones. A field renamed in 1/9 after 4/9 branched shows up here and nowhere else.
- [ ] **Route fixtures still match the routes.** Same, for 7/9 → 8/9.
- [ ] **`OpenPosition`'s field set is identical** across `execution`, `state_store`'s DTO, `visualizer_server`'s DTO and the wire's `position_state`. Four mirrors of one shape, written by four plans. A field present in three of them is a silent data loss; enumerate and diff them.
- [ ] **No `persist` / `log_event` call site survives** anywhere (`grep`) — 2/9 removed them from the trait, but a plan that branched earlier may have added one.
- [ ] **No `TakeProfit` order role, no `-t-` client order id, no `Modified` wire event** (`grep`). Three things the spec deliberately does not have, each easy to reintroduce by analogy.
- [ ] **`position_log` has no `UPDATE`/`DELETE`** anywhere in the workspace, not just in `state_store`.
- [ ] **Metric and alert names** emitted by `orchestrator` match those the visualiser and any dashboard read.

### Task 1.3: Full-cycle integration test

- [ ] One test, in the executor workspace, driving a complete position against a wiremock exchange **with the account-event stream disabled**: decision → entry → partial fill → terminal → resolution → stop placed → target trigger → exit → settled → closed. Asserts at each step: the `position_log` row, the `exchange_order`/`exchange_fill` rows, the emitted wire message, and the `/api/positions` response. This is the only test in the whole set that spans every plan at once.

**Layer 1 gate:** both suites green; the full-cycle test green. Commit: `test: full position lifecycle across every layer`.

---

## Layer 2: Acceptance-criteria validation

Walk spec §10 in order. Each row: the criterion, the plan that owns it, and **where the passing evidence is** (test path, or the command whose output was checked). A row is not tickable on an assurance.

| # | Criterion (§10, abbreviated) | Owner | Evidence |
|---|---|---|---|
| 1 | No state transition from a `place_order` return value | 1/9 | |
| 2 | Entry never fills → `Flat` after `ENTRY_FILL_TIMEOUT_SECS`, `not_filled` | 1/9 | |
| 3 | Close never fills → stays `Closing`, escalation fires and alerts | 1/9 | |
| 4 | Partial entry stays `Opening`; exactly **one** stop, final qty; none mid-fill | 1/9 | |
| 5 | Close while `Opening` held as `pending_close`, applied at resolution, no stop | 1/9 | |
| 6 | Entry cancelled after a partial fill resolves to `Open`, not `Flat` | 1/9 | |
| 7 | Scale-in leaves status `Open` throughout; stays closable | 1/9 + 3/9 | |
| 8 | **No order is ever placed for the target** (wiremock log + `exchange_order`) | 1/9 | |
| 9 | Target closes on price backstop *and* on signal; both via `do_close` | 1/9 | |
| 10 | Position resolves with the account-event stream **disabled entirely** | 1/9 | |
| 11 | `settle`'s fee arithmetic exists in exactly one place | 1/9 | |
| 12 | Every sent order has an `exchange_order` row, `origin='execution'`, non-null `position_id`, committed **before** the send | 3/9 | |
| 13 | Closed position → terminal `position_log` row, one `position_history` row, `settlement_complete` | 2/9 + 4 (live) | |
| 14 | `position_log` append-only in practice (`grep`, and history survives restart) | 2/9 | |
| 15 | `load_all()` after 0009 == before, on one restored dump | 2/9 | |
| 16 | Kill between two appends → last good row intact, next append restores | 2/9 | |
| 17 | Boot **and** periodic reconcile write `reconciliation_log`; hand-closed position corrected, alerted, visible | 3/9 | |
| 18 | main/ decodes every event kind; its `Position` matches `/api/positions` | 6/9 | |
| 19 | **main/ places no orders**; `MAIN_ORDER_PLACEMENT=enabled` restores all | 5/9 | |
| 20 | A refused order is not logged at `ERROR` | 5/9 | |
| 21 | Leftover `live_order_tracker` JSON → startup `WARNING`, not acted on | 5/9 | |
| 22 | `position_query` from a freshly started main/ returns the live position | 4/9 + 6/9 | |
| 23 | Position panel fields + unprotected banner; Orders/Fills/Closed panels; footer totals | 8/9 | |
| 24 | Open orders drawn on both charts; gone within a refresh; dashed while unacked | 8/9 | |
| 25 | Orphaned order still returned **and** still drawn | 7/9 + 8/9 | |
| 26 | No historical chart layer added (`grep` over `chart.js`) | 8/9 | |
| 27 | `docker compose run --build --rm test` green at every layer boundary | all | |
| 28 | Live acceptance on Binance margin mainnet, human-gated | 9/9 L4 | |

- [ ] Every row has evidence recorded.
- [ ] Any row that cannot be ticked is written up — as a spec amendment, or as a numbered section in [../TECH_DEBT.md](../TECH_DEBT.md), never as a silent omission. A criterion quietly dropped is the one failure mode this layer exists to prevent.

**Layer 2 gate:** the table is complete. No commit — this layer produces a record, not code.

---

## Layer 3: Paper and disarmed soak

Before any real money.

- [ ] Run the full stack with `EXECUTION_MODE=no_trade` against live Binance market data for **24 h**: positions never open, every decision is journalled as `rejected: Disarmed`, no alert storm, no unbounded growth in `position_log` (the §5.1 write-volume claim, measured rather than asserted).
- [ ] Run with the paper account for **24 h**: positions open, fill, settle and close; `position_log` rows are one-per-change; the visualiser renders a full cycle; main/'s `Position` tracks the executor's throughout.
- [ ] Confirm main/ placed nothing across both soaks: zero rows in its own order path's logs, and no order on the account that the executor did not journal.
- [ ] Review the metric series: `slippage_bps` sign and magnitude are plausible, `fill_latency_ms` reflects `ORDER_POLL_INTERVAL_SECS` rather than something worse, `position_hold_secs` matches wall clock.

**Layer 3 gate:** both soaks clean, findings written up. Any surprise goes back to its owning plan.

---

## Layer 4: Live acceptance (human-gated, one run at a time)

Same posture as live-trade-ops Layer 7. **Each run: stop, show the env file with keys redacted and the startup banner, wait for an explicit "go" for that run.**

- [ ] **Run 1 — Binance margin mainnet, minimum notional, manual close.** Open one position at `LIVE_MAX_NOTIONAL` scale; verify the stop rests on the exchange and **nothing rests for the target**; close it by hand from the exchange UI; verify the periodic reconcile detects it, corrects local state, alerts `PositionDrift` and writes `reconciliation_log`.
- [ ] **Run 2 — full cycle, target exit.** Open, let the local target trigger fire, verify the exit is placed at that moment, the fills settle with real fees, `realized_pnl` matches the account's own change, and `settlement_complete` is true.
- [ ] **Run 3 — stop exit.** Open with a stop close to price; verify which leg fired (local watcher or resting order), that the other did not double-close, and that `close_reason` records it correctly.
- [ ] **Run 4 — process death mid-position.** Kill the executor with a position open; verify the resting stop is still on the exchange; restart; verify `load_all` + reconcile recover the position and re-establish anything missing.
- [ ] After each run: capture the real exchange responses and replace the remaining hand-written wiremock fixtures marked `// from docs`.
- [ ] After each run: main/ saw every event, and its `Position` ended consistent with the exchange.

**Layer 4 gate:** all four runs green, fixtures replaced, no unexplained discrepancy.

---

## Layer 5: Ship

- [ ] Update [../TECH_DEBT.md](../TECH_DEBT.md): close §8 if the journal review landed; add anything Layers 2–4 surfaced; leave §10 (B7/B8) open with a note that the position model is now built to receive its fix.
- [ ] Update the spec in place with any decision that changed during implementation — a spec that no longer describes the code is worse than no spec.
- [ ] Mark all eight plans done, with the commit range each landed in.
- [ ] Merge `position-management` → `layer-implementation` (**after user confirmation**). Push (**after user confirmation**).
- [ ] Confirm `experimental_imp_2` carries 5/9 and 6/9 and that the two repositories' deployed versions are compatible — main/ running the consumer against an executor without wire v2, or an armed main/ against a live executor, are both deployment hazards no test can catch.

---

## Done when

- [ ] Every row of the §10 table has evidence.
- [ ] Four live runs green.
- [ ] Both repositories merged and pushed with confirmation.
- [ ] The executor is the only process that places orders, and it records every position it holds.
