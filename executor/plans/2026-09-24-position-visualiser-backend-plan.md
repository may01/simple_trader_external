# Position Management 7/9 — Visualiser backend (`visualizer_backend`, `visualizer_server`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan layer-by-layer. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve everything the position now knows — its log, its closed history, the orders and fills behind it, and what is resting on the exchange right now — over routes the frontend can render without a second query.

**Spec:** [`2026-09-22-position-management-design.md`](../specs/2026-09-22-position-management-design.md) §8.1, audit rows D5, D6, D7, D8, D10.

**Scope:** `crates/visualizer_backend`, `crates/visualizer_server` (routes, DTOs, `/ws`). **No** frontend (plan 8/9).

**Depends on:** plan 2/9 (`position_log`, the two views, `reconciliation_log`, `exchange_order.position_id`) merged into `position-management`. Independent of plans 3/9, 4/9, 5/9, 6/9.

**Blocks:** plan 8/9.

**Branch:** `position-visualiser-backend`, cut from `position-management`, merged back into it.

## Readiness review

Verified against the code on `layer-implementation` @ `ff2938d` and `live-trade-ops` @ `e45dc05` (2026-09-25).

🟢 **green** — exists in the system, small update · 🟡 **yellow** — in the spec, small code change · 🟠 **orange** — in the spec, large code change · 🔴 **red** — in neither code nor spec

### 🟢 Green

| Item | Where it is today | Change |
|---|---|---|
| `VisualizerBackend` with `historical`, `tail`, `freshness`, `order_book_view`, `wall_snapshots`, `position_events`, `signals`, `current_indicators`, `decisions` | `visualizer_backend/src/lib.rs` | three read methods added in the same shape |
| Routes `/api/history`, `/api/pair_history`, `/api/pair_events`, `/api/pair_decisions`, `/api/pair_signals`, `/api/walls`, `/api/pairs`, `/api/freshness`, `/api/status`, `/ws` | `visualizer_server/src/routes.rs` | four routes added; two existing ones extended |
| `PositionStateDto`, `PositionEventEntryDto`, the `#[serde(flatten)]` entry-wrapper convention | `visualizer_server/src/dto.rs` | extended, plus `OpenOrderDto` |
| The degrade-not-panic standard and its named tests | `visualizer_backend/src/lib.rs` tests | new routes must meet it |
| `dashboard` role grants via default privileges | `docker/initdb.d/00-roles.sql` | already covers 0009's tables |

### 🟡 Yellow

`position_log` / `position_history` / `position` / `orders` / `fills` / `open_orders` read methods · the four routes · `OpenOrderDto` · `execution_mode` + `main_order_placement` on `/api/status` · `PairSummaryDto.position` carrying the full state.

### 🟠 Orange

| Item | Why it is large |
|---|---|
| `/api/pair_events` over the `position_log` ∪ legacy `event_log` union | the migration seam is visible in exactly one place and this is it; legacy rows carry no `state`, which the DTO must represent as *absent*, not as an empty position |
| Position updates over `/ws` | today the socket is candle/trade/book only; a new broadcast source, a slow-client policy, and the existing traffic must be provably unchanged |

### 🔴 Red

| Item | Status |
|---|---|
| **Visualiser port — now fixed** | This plan's Docker section used `127.0.0.1:8081`. The compose file publishes **`127.0.0.1:8090:8090`**. Corrected below. The plan already said "confirm the port rather than assuming"; the assumption slipped in anyway, which is why it is listed here rather than quietly edited. |
| Committed route-response fixtures | this plan's device for unblocking 8/9; no amendment needed |

---

## Global Constraints

- **Every handler reads; none writes.** The existing rule for this crate.
- **A read failure degrades to a typed error, never a panic and never a short history** — the existing `a_database_error_degrades_to_a_typed_error_not_a_panic` and `historical_reports_a_read_failure_rather_than_returning_a_short_history` tests define the standard; new routes meet it.
- **Same window conventions** as `/api/pair_events` — `from`/`to`, empty window returns an empty list, same `#[serde(flatten)]` entry-wrapper shape. One exception, deliberate: `/api/open_orders` has no window (§8.1).
- **One commit per layer**, green in Docker, **after explicit user confirmation**.

---

## Docker Entry Points

```bash
docker compose run --build --rm test
docker compose run --build --rm test cargo test -p visualizer_backend
docker compose run --build --rm test cargo test -p visualizer_server
docker compose up -d --build postgres executor visualizer
curl -s 'http://127.0.0.1:8090/api/open_orders?pair=LINKUSDT' | jq
```

Verified: [ ] baseline green on the branch before Layer 1.

**Which visualiser.** Everything in this plan and in 8/9 refers to the
**executor's** visualiser — the `visualizer` service in
`trade_executor/docker-compose.yml`, i.e. the Rust `visualizer_server` binary
serving `crates/visualizer_server/static/`, bound via
`VISUALIZER_BIND_ADDR=0.0.0.0:8090` and published on `127.0.0.1:8090:8090`.

It is **not** either of `main/`'s viewers, which are separate processes in a
separate compose project and are untouched by this work: `live`
(`trader.py`, port **8050**) and the `view-full` viewer (port **8080**). Three
dashboards on three ports is easy to mis-copy, so the plans name the service
and the env var rather than a bare number.

---

## Layer 1: Read paths

### Task 1.1: Position log and history

**Files:** `crates/visualizer_backend/src/lib.rs`.

**Interface:**
```rust
pub async fn position_log(&self, pair: Pair, from: Ts, to: Ts) -> Result<Vec<(Ts, PositionLogEntry)>, VisualizerError>;
pub async fn position_history(&self, pair: Pair, from: Ts, to: Ts) -> Result<Vec<PositionRecord>, VisualizerError>;
pub async fn position(&self, id: PositionId) -> Result<Vec<(Ts, PositionLogEntry)>, VisualizerError>;
```

**Unit tests (RED):** rows come back in `seq` order, not `recorded_at` order (the same ordering trap plan 2/9's view test covers, asserted again at the layer that serves it); an empty window returns an empty list, not an error; a database error is a typed error; `position_history` returns one row per `position_id` with `created_at` from the first row and everything else from the last.

### Task 1.2: Orders, fills, open orders

**Interface:**
```rust
pub async fn orders(&self, pair: Pair, from: Ts, to: Ts) -> Result<Vec<OrderRecord>, VisualizerError>;
pub async fn fills(&self, id: PositionId) -> Result<Vec<Fill>, VisualizerError>;
pub async fn open_orders(&self, pair: Pair) -> Result<Vec<OpenOrder>, VisualizerError>;
```

**Unit tests (RED):**
- `open_orders` returns exactly the non-terminal statuses (`intent`, `submitted_unknown`, `new`, `partially_filled`) and excludes `filled`/`cancelled`/`rejected`.
- **An order with no live position is still returned** — `open_orders` reads `exchange_order`, not the position (§8.1: an orphan is "the exact thing worth seeing on a chart"). Seed an `exchange_order` row whose `position_id` is closed and assert it appears.
- `origin = 'livetest'` rows are excluded from every route here.
- `fills` joins by `position_id`, never by a `client_order_id LIKE` pattern.

### Task 1.3: `/api/pair_events` over the union

**Constraints (§5.2):** for a window spanning migration 0009, this route reads `position_log` unioned with legacy `event_log` rows. That seam is visible in exactly one place and this is it.

**Unit tests (RED):** a window entirely after the migration returns only `position_log` rows; entirely before, only `event_log` rows; spanning it, both, correctly interleaved by time; the legacy rows carry no `state` and the DTO represents that as absent rather than as an empty position.

**Layer 1 gate:** `cargo test -p visualizer_backend` green; Layer 2's route tests RED. Commit: `feat(visualizer_backend): position log, history, orders, fills, open orders`.

---

## Layer 2: Routes and DTOs

### Task 2.1: The routes

**Files:** `crates/visualizer_server/src/{routes.rs,dto.rs}`.

**Interface:** `GET /api/positions`, `GET /api/orders`, `GET /api/fills`, `GET /api/open_orders?pair=`; `PairSummaryDto.position` carries the full `PositionStateDto`; `/api/status` gains `execution_mode` and `main_order_placement`.

```rust
pub struct OpenOrderDto { pub client_order_id: String, pub role: String, pub side: SideDto,
                          pub order_kind: String, pub price: Option<Decimal>, pub stop_price: Option<Decimal>,
                          pub qty: Decimal, pub filled_qty: Decimal, pub status: String }
```

**Integration test → plan 8/9 (RED in Docker):** `crates/visualizer_server/tests/` — seed a full position lifecycle into Postgres, then assert each route's JSON shape field-for-field. These are the contract plan 8/9 codes against; capture the responses as committed fixtures the same way plan 4/9 does for the wire.

**Unit tests (RED):**
- `/api/open_orders` takes no `from`/`to` and rejects them if sent, rather than ignoring them silently.
- A `Stop` order's drawable price is `stop_price`; a limit's is `price`; a market order is **omitted entirely** (§8.1 — it has no price to draw, and a line at `null` is worse than no line).
- Missing `pair` → the same empty-response convention the existing routes use.
- `/api/status` reports `no_trade` when the executor is disarmed.

### Task 2.2: `/ws` carries position updates

**Constraints (§8.2, D9):** the header comment in `pair.js` and in the server's `/ws` module declaring the socket candle/trade/book-only is **updated**, not worked around.

**Unit tests (RED):** a position state change reaches a connected `/ws` client; a client connected mid-position receives the next update without needing a poll; the existing candle/trade/book traffic is unchanged; a slow client is dropped rather than blocking the broadcast.

**Layer 2 gate:** `docker compose up -d visualizer` and each route returns real data for a seeded position. Commit: `feat(visualizer_server): position, order, fill and open-order routes; position over /ws`.

---

## Done when

- [ ] Both layer gates green in Docker.
- [ ] Route fixtures committed and handed to plan 8/9.
- [ ] Spec acceptance criterion satisfied in part here: "an orphaned order — open on the exchange with no live position — is still drawn" (the backend half: still **returned**).
- [ ] `position-visualiser-backend` merged into `position-management` (after user confirmation).
