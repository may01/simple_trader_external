# MEXC trading connector 0/5 — Index, schedule, live runs, acceptance

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking. **Read this plan first**: it is the index for the other five, and it owns the live runs (M0–M5) and spec §13 end to end.

**Goal:** MEXC becomes a venue the executor can trade on. Futures comes first, with an exchange-side plan-order stop. Spot follows, behind the local-only-stop waiver. Every function in the spec's capability matrix is either real or refuses in a documented way.

**Spec:** [`2026-09-25-mexc-trading-connector-design.md`](../specs/2026-09-25-mexc-trading-connector-design.md), reviewed 2026-09-25 (its §15 lists R1–R29). § references below point into it; read the two side by side.

**Tech stack:** Rust workspace (`tokio`, `rust_decimal`, `serde`, `wiremock`, `sqlx`), Docker Compose. Workspace: `trade_executor/.worktrees/layer-implementation`.

**Note on layer taxonomy:** `layer-first-planning`'s layer table describes the Python pipeline. As in the position-management plans, these plans apply its *principles* over `trade_executor`'s real layers: Docker first, interface before code, a RED integration test at each boundary, and no layer started before the previous one is green in Docker.

---

## Precondition — blocks everything

The spec's consumers (`run_fill_sync`, `settle`, order-journal recovery, `OpenPosition`) are in the **uncommitted** position-management work in `.worktrees/layer-implementation`: 56 changed files at 2026-09-25, on branch `position-management`, whose HEAD equals `layer-implementation` @ 165afdb.

- [ ] Position-management work committed and merged into `layer-implementation` (its own finalisation plan, [2026-09-24-position-management-finalisation-plan.md](2026-09-24-position-management-finalisation-plan.md), owns that).
- [ ] `docker compose run --build --rm test` green on `layer-implementation` after that merge (baseline for every plan below).

Plan 1/5 (G0) is the **only** exception: it uses nothing position-management adds, so it may start now.

---

## The five plans

| # | Plan | Spec layers | Crates | Depends on | Branch |
|---|---|---|---|---|---|
| 1/5 | [G0 capability probe](2026-09-25-mexc-g0-probe-plan.md) | G0, run M0 | `live_trade_ops`, `exchange_adapter_mexc` (fixtures only) | operator keys (D2 checklist) | `mexc-g0-probe` |
| 2/5 | [Common layer](2026-09-25-mexc-common-layer-plan.md) | L0-a | `exchange_adapter`, `exchange_adapter_binance`, `order_journal`, `market_data`, `observability`, every `OrderId` user, `migrations/` | 1/5 verdict on F4, precondition | `mexc-common` |
| 3/5 | [MEXC futures trading](2026-09-25-mexc-futures-trading-plan.md) | L0-d, L0-e | `exchange_adapter_mexc`, `live_trade_ops` (M3 wiring) | 2/5, 1/5 step 7 green | `mexc-futures` |
| 4/5 | [Execution + orchestrator](2026-09-25-mexc-execution-orchestrator-plan.md) | L3 | `execution`, `orchestrator`, `state_store`, `visualizer_server` + `static/` (label) | 2/5 | `mexc-execution` |
| 5/5 | [MEXC spot trading](2026-09-25-mexc-spot-trading-plan.md) | L0-b, L0-c | `exchange_adapter_mexc`, `live_trade_ops` (spot scenario) | 2/5 | `mexc-spot` |

Integration branch: `mexc-trading-connector`, cut from `layer-implementation` once the precondition holds. Every plan branch is cut from it and merged back into it. Only this plan merges `mexc-trading-connector` into `layer-implementation`, and only after the acceptance table below is green.

### Contract artefacts between plans

- 1/5 → 3/5, 5/5: captured fixtures in `crates/exchange_adapter_mexc/tests/fixtures/captured/` plus the probe report `external/executor/runs/<date>-mexc-g0.md`. A fixture marked `// from docs` is replaced when a capture exists.
- 2/5 → 3/5, 4/5, 5/5: the Rust signatures in 2/5's Interface sections (`OrderId(String)`, `Capabilities`, `get_order_by_client_id`, `RejectReason::PermissionDenied`, `ServerClock`, `AlertKind::ClockSkew`).
- 3/5, 5/5 → 4/5: the capability values in spec §5.1, as a test in each adapter crate.

3/5, 4/5 and 5/5 are independent of one another once 2/5 is merged. 4/5 can be built against scripted fakes before either adapter lands.

### Schedule

```
Wave 0  1/5 G0 probe                 ← starts now; confirms the facts the rest rests on
Wave A  2/5 common layer             ← after precondition + G0 F4 verdict
Wave B  3/5 futures  ║ 4/5 execution  ║ 5/5 spot (L0-b)     (parallel)
Wave C  M3 (futures scenario) → M5 (executor on futures)   ← critical path ends here
Wave D  5/5 spot push (L0-c) → M1, M2 → M4 (needs D1 waiver + pos-mgmt feed-loss grace)
```

Critical path (spec §11): G0 → L0-a → L0-d → M3 → L0-e → L3 → M5.

---

## Global constraints (every plan)

- **No implementation code in plans.** Signatures and test descriptions only.
- **`cargo test` with no flags never touches the network.** Live tests are `#[ignore]` **and** check `LIVE_TRADE_OPS=1`.
- **The legacy docs (`mexcdevelop.github.io`) are not a source.** Every MEXC path, field and code comes from `mexc.com/api-docs` or a capture.
- **No silent rounding in adapters.** Off-step price / qty / vol → `InvalidRequest`.
- **The adapter never retries a POST that places or cancels.** Unknown outcome → `Network`; recovery goes through `get_order_by_client_id` (spec §5.3).
- **One commit per layer**, after it is green in Docker. **Commit only after explicit user confirmation**: stage, describe, wait.
- **Containers write root-owned files into the worktree.** Fix ownership (`docker compose run --rm test chown -R $(id -u):$(id -g) target tests/fixtures`) before any merge.
- **Every improvement updates the spec.** A plan that finds the spec wrong amends the spec in the same step and notes it in spec §15.

---

## Docker entry points

From `trade_executor/.worktrees/layer-implementation` (or the branch's own worktree):

```bash
# Every layer's gate. --build is mandatory (stale test image otherwise).
docker compose run --build --rm test

# One crate while iterating
docker compose run --build --rm test cargo test -p exchange_adapter_mexc
docker compose run --build --rm test cargo test -p exchange_adapter
docker compose run --build --rm test cargo test -p execution
docker compose run --build --rm test cargo test -p orchestrator

# Live runs (mainnet, operator-armed; env files are never committed)
docker compose run --build --rm --env-file configs/live-trade-ops/mexc.spot.mainnet.env    test \
  cargo test -p live_trade_ops --test live_trade_ops live_mexc_probe       -- --ignored --nocapture --test-threads=1
docker compose run --build --rm --env-file configs/live-trade-ops/mexc.futures.mainnet.env test \
  cargo test -p live_trade_ops --test live_trade_ops live_futures_trade_ops -- --ignored --nocapture --test-threads=1
docker compose run --build --rm --env-file configs/live-trade-ops/mexc.spot.mainnet.env    test \
  cargo test -p live_trade_ops --test live_trade_ops live_spot_trade_ops   -- --ignored --nocapture --test-threads=1

# Executor end to end (M4, M5): the executor service's usual deploy env, with
#   EXCHANGE=mexc MARKET_KIND=futures|spot EXECUTION_MODE=live PAIRS=<one pair>
#   FUTURES_REST_BASE_URL=https://api.mexc.com FUTURES_WS_BASE_URL=wss://contract.mexc.com/edge
docker compose up --build executor
```

Verified: [ ] `docker compose run --build --rm test` green on `mexc-trading-connector` at its cut point.

---

## Live runs (owned here)

Each run: operator sets `LIVE_TRADE_OPS=1`, `LIVE_PAIR`, `LIVE_MAX_NOTIONAL`, `LIVE_RUN_ID`. The report goes to `external/executor/runs/<date>-mexc-<run>.md`. Captures are committed to `exchange_adapter_mexc/tests/fixtures/captured/`. Every `UNMAPPED Mexc <code>` line becomes a `classify` row or an entry in the run report.

| # | Run | Needs | Proves | Status |
|---|---|---|---|---|
| M0 | G0 probe | 1/5 | F1–F8 verdicts, D2 (futures order permission), fixtures | [ ] |
| M3 | Futures scenario: open → plan-order stop → move stop (cancel-and-replace) → close reduce-only → flat; `position_risk` vs `LiqCalc` golden row | 2/5, 3/5 (L0-d) | spec §7 whole | [ ] |
| M5 | Executor, `EXCHANGE=mexc MARKET_KIND=futures EXECUTION_MODE=live`, one SAR-test-signal position at minimum notional, with `main/` | 3/5, 4/5 | boot gate, plan-order stop in production, position-management on MEXC futures | [ ] |
| M1 | Spot scenario: limit buy → `get_order_fills` → `settle` → limit sell (`reduce_only=true`) → flat; stop step `Skipped(native_stop=false)` | 2/5, 5/5 (L0-b) | C1, C2, C4–C11, MEXC fee assets, string ids through the journal | [ ] |
| M2 | M1 with the user-data stream up: every fill seen on push before the poll | 5/5 (L0-c) | spec §6.4 | [ ] |
| M4 | Executor, `EXCHANGE=mexc MARKET_KIND=spot EXECUTION_MODE=live`, `ALLOW_LOCAL_ONLY_STOP=1`, `LOCAL_ONLY_MAX_NOTIONAL` at minimum, one SAR-test-signal position | 4/5, 5/5, pos-mgmt feed-loss grace | position-management on MEXC spot | [ ] |

**Human gate:** every live run needs the operator's explicit go, in the conversation, for that run. Approval of one run does not extend to the next.

---

## Acceptance (spec §13) → where it is proven

| # | Criterion | Proven by | Status |
|---|---|---|---|
| 1 | D1–D5 recorded | spec §4 | ✅ 2026-09-25 |
| 2 | G0 report + fixtures committed; F-table has a confirmed / refuted column | 1/5 Task 1.4 | [ ] |
| 3 | `OrderId` string end to end; place, restart, cancel by stored id | 2/5 integration test + M1 | [ ] |
| 4 | Every MEXC-spot C-row implemented or refuses as documented, wiremock on captured fixtures | 5/5 | [ ] |
| 5 | `get_order_fills` real on spot; M1 ends `settlement_complete: true` | 5/5 + M1 | [ ] |
| 6 | Boot refuses MEXC spot live without waiver + cap; `MARKET_KIND=margin` on MEXC → config error, not panic | 4/5 Tasks 2.1, 2.2 | [ ] |
| 7 | Spot short → `NotPlaced { reason: "short_unsupported" }`, zero exchange calls | 4/5 Task 3.2 | [ ] |
| 8 | No `classify` row seen in M0–M5 still "from docs"; every `Unknown` listed | run reports | [ ] |
| 9 | M3 green on current REST (no REST to `contract.mexc.com`); MEXC `LiqCalc` golden row; no-permission key → `can_place_orders == false`, futures live boot refuses | 3/5 + 4/5 Task 2.1 + M3 | [ ] |
| 9a | Every MEXC-futures C-row implemented, wiremock on captured fixtures; M5 green | 3/5 + M5 | [ ] |
| 9b | Spot exit with `reduce_only=true` placed, sized `min(net_size, free_base)` | 5/5 Task 1.2 + 4/5 Task 3.3 | [ ] |
| 10 | `exchange_adapter_mexc/NOTES.md` describes only what is still true | end of 3/5 and 5/5 | [ ] |
| 11 | Plans exist per layer (this set); `TECH_DEBT.md` §7 closed; `amend_stop` follow-up recorded | 2/5 Task 1.6, this plan | [~] plans written 2026-09-25 |

## Finalisation

- [ ] Every row above green, with a link to the test or run report that proves it.
- [ ] Spec status → **implemented**, F-table verdict column filled, §15 "Still open" emptied or moved to TECH_DEBT.
- [ ] `external/executor/TECH_DEBT.md`: §7 closed; new numbered section for `amend_stop` / `planorder/change_price` (D5).
- [ ] Merge `mexc-trading-connector` → `layer-implementation` after user confirmation.
