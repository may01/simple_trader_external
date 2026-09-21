# Indicator Broadcast End-to-End Check (main/ → executor) — Design Spec

Date: 2026-09-20
Status: complete 2026-09-21 — scripted check green from cold start (6/6); Tier 2 observed on LINKUSDT
Target projects: `main/` (Python, sender) and `trade_executor` (Rust, receiver, worktree `layer-implementation`)
Extends: [2026-09-19-level-broadcast-design.md](2026-09-19-level-broadcast-design.md) — this spec adds no wire format, no storage and no behavior, only proof that what that spec describes actually works across the process boundary
Related: [layers/L4-mq-gateway.md](layers/L4-mq-gateway.md) §`indicator_update`, [layers/L5-state-store.md](layers/L5-state-store.md) §indicators, [layers/L9-deploy.md](layers/L9-deploy.md) step 7b, plan [2026-09-20-level-broadcast-plan.md](../plans/2026-09-20-level-broadcast-plan.md)

## 1. Why this exists

The indicator-broadcast feature is implemented and green on both sides, in isolation:

- executor: `docker compose run --build --rm test` passes — `mq_gateway` 39 tests (wire round-trip, `subscribe_indicators`, shared dedup), `state_store`/`pg_store` 65 (persist, `current_indicator`, cache, failed-insert cache non-pollution), `orchestrator` 42 (ingest task, shutdown, persist-failure alert). Verified 2026-09-20.
- main/: `docker compose run --rm live pytest tests/test_shared_indicators_config.py tests/test_indicator_publisher.py tests/test_robot.py -v` → 65 passed. Verified 2026-09-20.

**Every one of those tests stops at a boundary it controls.** The executor's tests feed `mq_gateway` through `InMemoryTransport` or a test-local `PushSocket`; main/'s publisher tests assert against a fake PULL socket inside the same container. Nothing anywhere has ever run the real `main/` process and the real executor process at once and observed a reading cross between them. The plan that built this feature has no task for it either — a gap in the plan, not a step that was skipped.

That gap is not theoretical. Preparing this spec turned up a configuration defect (§3) that every existing test is structurally incapable of catching, and that makes the feature **non-functional as currently deployed**.

## 2. What the check must prove

One claim, end to end, with no test doubles anywhere in the path:

> A `main/` process publishing an allowlisted indicator results in a row in the executor's `indicators` table, and `current_indicator` serves that reading back.

Decomposed into the assertions §5 lists. Anything that can be proven without both real processes running belongs in the existing unit suites, not here.

## 3. Blocking finding: the two processes cannot currently reach each other

Measured 2026-09-20, with the `layer-implementation` executor stack up:

| From | Target | Result |
|---|---|---|
| host | `127.0.0.1:5555` | connects |
| container with `extra_hosts: host.docker.internal:host-gateway` (i.e. `main/`'s `live` service) | `host.docker.internal` → `172.17.0.1:5555` | `ConnectionRefusedError [Errno 111]` |

Cause: `trade_executor/docker-compose.yml` publishes the inbound socket as `"127.0.0.1:5555:5555"` — deliberately host-loopback-only, because "mq_gateway's wire format carries no auth of its own" (its own comment). `main/`'s `live` service reaches the host through the docker bridge gateway, `172.17.0.1`. A port published on `127.0.0.1` is not published on `172.17.0.1`, so `MQ_EXECUTOR_ADDR=tcp://host.docker.internal:5555` (`main/configs/live.env`) connects to nothing.

It fails silently by design: `IndicatorPublisher.publish` is best-effort and never raises (zmq PUSH queues to an unconnected peer, then `zmq.Again` once the HWM fills), and the executor simply never receives anything. Nobody is alerted on either side. That silence is exactly why the unit suites are green and the feature is dead.

## 4. Decision: shared external docker network (A) — taken 2026-09-20

**Decided: (A).** Both compose projects attach to one external network, `trader_mq`, and `main/` addresses the executor by compose service name. Nothing is exposed beyond the two projects — strictly tighter than a host-published port. Concretely, as now written into both repos:

- created once, out-of-band, owned by neither project: `docker network create trader_mq`;
- `trade_executor/docker-compose.yml`: `executor` gains `networks: [default, trader_mq]` (`default` must be listed explicitly — naming any network disables compose's implicit default membership, and `postgres` lives there). Its `127.0.0.1:5555/5556` publishes are **kept**, now documented as host-side tooling only, not main/'s path;
- `main/docker-compose.yml`: `live` gains the same `networks: [default, trader_mq]`, plus the `networks: {trader_mq: {external: true}}` declaration; its `extra_hosts` host-gateway entry stays for other host-dialing uses;
- `main/configs/live.env`: `MQ_EXECUTOR_ADDR=tcp://executor:5555`.

**Verified 2026-09-20** (executor attached live via `docker network connect --alias executor trader_mq …`, no restart):

- name resolution and TCP: `executor` → `172.26.0.2`, `connect(('executor', 5555))` succeeds — §3's probe inverted;
- main/'s **real** `IndicatorPublisher`, run from the `simple_trader` image on `trader_mq`, published three readings with `dropped == 0`.

One gotcha the check's own setup must encode: the publisher sets `zmq.IMMEDIATE = 1`, so anything published in the first moments after construction, before libzmq finishes connecting, is dropped rather than queued (`dropped == 1`, logged as "no reachable executor" — indistinguishable from a genuinely wrong address). A Tier 1 script must settle the connection before its first assertion-bearing publish. The live tick loop is unaffected: it republishes every interval.

The options below are kept for the record.

Options considered, with the security posture each preserves or gives up:

- **(A) Shared external docker network — recommended.** Create one user-defined network (e.g. `docker network create trader_mq`), attach it in both compose files, and set `MQ_EXECUTOR_ADDR=tcp://executor:5555` so `main/` resolves the executor by service name. Nothing is exposed beyond the two projects — strictly *tighter* than today's host-published port, and the `127.0.0.1:5555` publish can stay for host-side tooling or be dropped entirely.
- **(B) Publish on the bridge gateway address**: `ports: - "172.17.0.1:5555:5555"`. Minimal change, but hardcodes an address docker is free to change and stops working the moment a custom bridge is in play.
- **(C) Publish on `0.0.0.0`.** Exposes an unauthenticated command socket to the LAN. Rejected — it contradicts the host-only posture the current binding was chosen for.
- **(D) `network_mode: host` on `main/`'s `live` service.** Works, but conflicts with its own published `8050:8050` and changes the networking of an unrelated live-trading service to serve a telemetry side channel.

The check runs entirely inside `trader_mq` and needs no host ports.

Until the check below passes, treat the feature as unproven end to end — wiring it is necessary, not sufficient.

## 5. The check itself

**Shape**: one scripted, on-demand check — not a unit test, not part of `cargo test --workspace` or `pytest tests/`. It needs two real processes, a real Postgres and a real network hop; wiring it into either default suite would make both suites depend on a running stack.

**Setup**
1. Executor stack up: `postgres` healthy, migrations applied (`SCHEMA_VERSION` 7), `executor` running with `indicator_ingest` spawned (L9 step 7b).
2. `main/` sender reachable to it per §4's decision, with a known allowlist — the shipped `configs/shared_indicators_config.yaml` (`ema_7`/`ema_14`/`ema_25` × 15/60/240) or a narrower one for the check.
3. A read connection to Postgres for assertions (the host-published `127.0.0.1:5436` read-only `dashboard` role already exists for exactly this).

**Two tiers.** The first is the one that must exist; the second is worth having but depends on live market data and so cannot be a gate.

**Tier 1 — synthetic sender, deterministic.** Drive `main/`'s *real* `IndicatorPublisher` (not a hand-rolled JSON PUSH — the point is to exercise main/'s own builder and socket code) from a small script in a `main/`-image container, publishing a handful of readings with a unique `name` prefix per run, then assert against Postgres.

**Tier 2 — real tick loop.** Run `main/`'s actual `live` service against the executor and confirm the allowlisted indicators appear in `indicators` within one tick interval, republished each tick. Depends on live market data and warm indicator state, so it is a manual/soak confirmation, not a gate.

## 6. Assertions (Tier 1)

1. **Arrival**: after publishing one `kind: "none"` reading, a row exists in `indicators` with the sent `pair`, `name`, `value`, `kind = 'none'`, `volume IS NULL`, and an `expires_at` matching the sender's TTL (300 s) within clock tolerance.
2. **Read-back**: `current_indicator(pair, name, now)` returns that reading — exercised through the executor process that ingested it (its cache is warm by construction), not only by direct SQL.
3. **Dedup across the shared id-space**: the same `id` published twice yields exactly one row. (Main/ mints a fresh uuid per publish, so this needs the script to resend a captured id deliberately.)
4. **Append-only**: a second reading for the same `(pair, name)` with a different `value` adds a row rather than replacing one, and `current_indicator` returns the newer one.
5. **Expiry**: a reading published with a short TTL stops being returned by `current_indicator` once `expires_at` passes, while its row remains in the table.
6. **Kind round-trip**: a `kind: "support"` reading with `volume` persists with `volume` non-NULL, satisfying the `volume_matches_kind` CHECK — this exercises wire→store `IndicatorKind` mapping that v1's sender never emits (it publishes `kind: "none"` only), and is the only place that mapping is proven outside Rust unit tests.
7. **Negative control — the failure that started this spec**: with the sender pointed at an address nothing is listening on, `publish` still returns without raising, the tick loop keeps running, `main/` increments its `dropped` counter, and **no** row appears. This pins the silent-failure behavior as intended, and makes §3's defect a test-visible condition rather than something only noticed by reading compose files.

## 6a. First run, by hand — 2026-09-20

Executor rebuilt from `layer-implementation` HEAD (`docker compose up -d --build executor`, migration 7 applied, `indicator_ingest` running, container on `layer-implementation_default` + `trader_mq`). Probe run from the `simple_trader` image on `trader_mq`, driving main/'s real `IndicatorPublisher`; assertions read back with `psql` against the executor's own Postgres. Run tag `fa51c75d`:

| # | Assertion | Result |
|---|---|---|
| 1 | Arrival | **pass** — `kind = 'none'`, `volume` NULL, `expires_at − received_at` = 300 000 ms, exactly the sender's TTL |
| 3 | Dedup on a resent `id` | **pass** — one row from two identical sends |
| 4 | Append-only | **pass** — two rows for one `(pair, name)`, both values kept |
| 6 | `support` + `volume` round trip | **pass** — `kind = 'support'`, `volume = 3.25`, `volume_matches_kind` satisfied |
| 7 | Negative control (dead address) | **pass** — no row, no raise, `dropped == 1`, warning logged; the live publisher's `dropped == 0` in the same run |
| 2 | Read-back via `current_indicator` | **not testable end to end** — see below |
| 5 | Expiry stops it being served | **pass at the row level (2026-09-21)** — the short-TTL row persists with `expires_at − received_at` = 3 000 ms, and since the indicator panel landed, `GET /api/current_indicators` stops listing a row once its `expires_at` passes (verified on the running visualiser). The executor-side *cache* half remains unobservable, as for 2 |

**`current_indicator` has no caller anywhere in the workspace** — no `visualizer_server` route, no orchestrator use, nothing outside `state_store`'s own tests. It is correct, unit-tested (cache hit, immediate write-through visibility, re-query past expiry, no cache pollution on failed insert) and currently dead. So assertions 2 and 5 cannot be proven from outside the process by any means, and this spec should not pretend otherwise.

**Update 2026-09-21:** decided and built — [indicator-visualisation-design.md](2026-09-20-indicator-visualisation-design.md) adds a read route over a plain `PgStateReader` query (not `current_indicator`, whose cache is always cold in the visualiser's process). That closes assertion 5 at the row level; assertion 2 stays unit-test-only, by choice. Original text follows.

Closing that needs a decision of its own, out of this spec's scope: either expose a read route (`/api/pair_indicators`, mirroring `pair_signals`) — which the visualizer will want anyway, per L5 — or accept that this half stays covered by Rust unit tests only. Until then, a scripted Tier 1 asserts 1, 3, 4, 6, 7 and the *row* half of 5.

## 6b. Scripted check — 2026-09-21

Lives in the **`main/` repo** — the sender side, whose image and code the probe needs — on branch `indicator-broadcast-sender`:

- `scripts/e2e_indicator_broadcast.py` — host-side driver, stdlib only. Brings the executor stack up (`--cold`: `docker compose down` — never `-v` — then `up -d --build postgres executor visualizer`, and rebuilds main/'s `simple_trader` image), waits for `/api/status` to report ready at `schema_version` 7, then **waits for a warm-up reading to land in `indicators`** — a healthy API says nothing about whether `indicator_ingest` is running, so the ingest path is its own readiness check. Asserts through both `psql` (inside the executor's `postgres` service) and `GET /api/current_indicators`. Exits non-zero on any failure.
- `scripts/e2e_indicator_broadcast_probe.py` — runs inside the `simple_trader` image on `trader_mq`, publishing through main/'s real `IndicatorPublisher`. The only hand-built messages are the two the real publisher can't produce: a resent `id` (A3) and a `kind: "support"` reading (A6).

Run from `main/`:
```bash
python3 scripts/e2e_indicator_broadcast.py --cold   # cold start of both sides
python3 scripts/e2e_indicator_broadcast.py          # against the stack as it is
```
Needs `docker network create trader_mq` once per machine; `EXECUTOR_DIR`/`--executor-dir` overrides the default `../trade_executor/.worktrees/layer-implementation`.

Results: the executor ran at `indicator-panel` HEAD (`layer-implementation` + the read route), after `docker compose run --build --rm test` passed on that same HEAD.

| Run | Mode | Result |
|---|---|---|
| `e2e_f88ee2ae` | `--cold` | 5/6. A1 "failed" on `expires_at − received_at` = 299 999 ms against an exact 300 000 check. That was a **bug in the check**: the two timestamps come from the sender's and the executor's clocks, so the gap is TTL minus transit/skew, never exact. §6 already said "within clock tolerance". Fixed to ±1 000 ms, for A5 as well. |
| `e2e_5b642c40` | warm | 6/6 |
| `e2e_bbe2146c` | `--cold` | **6/6** — A1 299 999 ms (in tolerance), A3 1 row, A4 rows `[111.5, 222.5]` and API `222.5`, A5 served → gone 16 s later with row kept, A6 `support`/`3.25` in row and API, A7 `dropped_dead=1` / `dropped_live=0`, no row |

A5 now runs end to end through the read route (`served_before` / `gone_after` / `row_kept`), using a 15 s short TTL so the API is checked while the reading is still live. Yesterday's 3 s TTL had already lapsed by the time the probe container exited.

Every run leaves `e2e_<run>_*` rows in the append-only `indicators` table. They show in the visualiser's Indicators panel until they expire (300 s).

## 7. Out of scope

- Any change to the wire format, the `indicators` table, `current_indicator`, or the ingest task — this spec proves what exists, it does not modify it.
- Wiring `current_indicator` into any signal check, and anything about `combined_levels` — still a later spec, unchanged by this one.
- Publishing `kind: "support"`/`"resistance"` from `main/` in production (assertion 6 drives that path from a check script only).
- Outbound (executor → main/) anything.
- Fixing `main/`'s 21 pre-existing unrelated test failures or the missing `optuna` in the `live` image (see the plan's Docker Entry Points).

## 8. Acceptance criteria

- [x] §4's networking decision is recorded, and both compose files reflect it. (2026-09-20 — `trade_executor/docker-compose.yml`, `main/docker-compose.yml`, `main/configs/live.env`; uncommitted at time of writing.)
- [x] A container running `main/`'s real `IndicatorPublisher` reaches the executor's inbound socket — the §3 probe inverts (connects instead of `ConnectionRefused`). (2026-09-20, `dropped == 0` after settling the connection.)
- [x] Stack rebuilt from current `layer-implementation` HEAD, migration 7 applied, `indicator_ingest` running (2026-09-20). Note the previously-running container predated the feature: its DB was at migration 6, so early probe readings were accepted by the socket and discarded by an old binary.
- [x] Assertions 1, 3, 4, 6, 7 pass against the real stack, run by hand (2026-09-20, §6a).
- [x] Assertion 5 — covered at the row level via `GET /api/current_indicators` (2026-09-21).
- [x] ~~Assertion 2 end to end~~ — **won't do, by decision**: `current_indicator`'s in-process cache is not observable from outside the executor. It is covered by `state_store`'s unit tests (cache hit, write-through visibility, re-query past expiry, failed-insert non-pollution).
- [x] The same assertions pass from a **scripted** run, from a cold start of both stacks (2026-09-21, run `e2e_bbe2146c`, 6/6, §6b).
- [x] The check is runnable with a single documented command, and its location is recorded in the L9 testing notes (`main/scripts/e2e_indicator_broadcast.py --cold`, 2026-09-21).
- [x] Tier 2 has been observed manually at least once, with the result and date noted here. **2026-09-21**: main/'s real `live` service (`STOCK_TYPE=binance_candles`, `STRATEGY_SET` empty) → executor on `PAIRS=LINKUSDT`. All 9 allowlisted names arrived under `LINKUSDT` every 30 s; values differed across timeframes (e.g. `15_ema_7` 13.1009, `60_ema_7` 13.0085, `240_ema_7` 12.8805) and moved between publishes; `GET /api/current_indicators?pair=LINKUSDT` served all 9.

  Getting there exposed two main/ defects that no test had caught, both fixed on main/ branch `stock-pair-and-readonly-candles`:
  - **Empty pair.** `Stock_MockBinance`, the code-default paper stock, had no `get_pair_name()`, so every paper-mode reading went out as `pair: ""`. The executor accepted it (see TECH_DEBT §6). Fixed with an override.
  - **Frozen values.** That same mock replays a pickled candle fixture, so paper-mode indicators were constants, identical across timeframes. Added `STOCK_TYPE=binance_candles`: real Binance public market data, no API keys read even when set, every order/account call refused. `configs/live.env` now uses it.
