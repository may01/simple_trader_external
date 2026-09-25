# Position Management 4/9 — Wire v2 (`mq_gateway`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan layer-by-layer. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the executor → main/ channel carry something worth reading: full position state on every event, a rejection reason that survives the wire boundary, the `filled` event kind the contract has always listed and nothing has ever produced, a way for a restarted main/ to ask what is held, and a heartbeat that distinguishes a dead queue from a quiet market.

**Spec:** [`2026-09-22-position-management-design.md`](../specs/2026-09-22-position-management-design.md) §6.1, §6.2, §6.3, decision D9.

**Scope:** `crates/mq_gateway` only — encoder, decoder, the two new inbound/outbound behaviours. **No** main/ code (plan 6/9), **no** position model changes (plan 1/9).

**Depends on:** plan 1/9 (`position-core`) merged — the encoder maps `PositionStateEvent`'s new variants. Independent of plans 2/9, 3/9, 7/9, 8/9; may run in parallel with all of them.

**Blocks:** plan 6/9 (main/'s consumer codes against this format).

**Branch:** `position-wire-v2`, cut from `position-management`, merged back into it.

## Readiness review

Verified against the code on `layer-implementation` @ `ff2938d` and `live-trade-ops` @ `e45dc05` (2026-09-25).

🟢 **green** — exists in the system, small update · 🟡 **yellow** — in the spec, small code change · 🟠 **orange** — in the spec, large code change · 🔴 **red** — in neither code nor spec

### 🟢 Green

| Item | Where it is today | Change |
|---|---|---|
| `wire.rs` — `OutboundEnvelope`, `encode_outbound`, `decode_inbound`, the DTO enums | `mq_gateway/src/wire.rs` | envelope grows; `flat_state()` goes |
| `MqGateway`, `StateOutbound::publish_state`, `MqGatewayConfig` validation | `mq_gateway/src/gateway.rs` | one signature change |
| `drive`'s three loops | `mq_gateway/src/drive.rs` | outbound loop reads state alongside the event |
| `ZmqTransport` PUSH/PULL, bind addresses, queue bound | `mq_gateway/src/zmq_transport.rs` | untouched |
| `InboundPayload` tagged-enum decoding | `wire.rs` | one variant added |

### 🟡 Yellow

The `schema: 2` field · the six added event kinds · `position_query` inbound · the heartbeat task and `POSITION_HEARTBEAT_SECS` · `publish_state`'s new `state` parameter.

### 🟠 Orange

| Item | Why it is large |
|---|---|
| Deleting `flat_state()` and threading real state to the encoder | `drive` must read the engine's current state at event time; "the state at the moment of the event, not a later one" is a concurrency property, not a field copy |
| Making the event→kind match total | removing the catch-all arm means every `PositionStateEvent` variant must be handled explicitly, and adding one later must fail to compile |

### 🔴 Red

| Item | Status |
|---|---|
| Golden wire fixtures as a committed cross-repo contract | this plan's own device for letting 6/9 proceed in another repo and language; no amendment needed, but it is load-bearing for the schedule |
| Interaction with [../TECH_DEBT.md](../TECH_DEBT.md) §3 | `drive` "drops every error", including a failed `publish_state`. This plan makes the outbound message matter much more, which makes §3 worse without changing it. Flagged, deliberately not fixed here — but §3 should be re-prioritised once this lands. |

---

## Global Constraints

- **Additive versioning** (D9). `schema: 2` on outbound. A reader ignores unknown fields; `schema` bumps only on a breaking change.
- **Aggregates only — no per-fill array, ever** (§6.1). main/ needs an average entry price and a set of levels, not a trade ledger.
- **`flat_state()` is deleted.** Every event carries the full current state; a consumer must be able to reconstruct the position from the last message it received without having seen the first.
- **The heartbeat publishes and appends nothing** (§6.3, §5.1). No database call in this crate.
- **The inbound nested-vs-flat `payload` drift stays unfixed** (D9, §9) — it is inbound, documented in `L4-mq-gateway.md`, and not this plan's business.
- **One commit per layer**, green in Docker, **after explicit user confirmation**.

---

## Docker Entry Points

```bash
docker compose run --build --rm test
docker compose run --build --rm test cargo test -p mq_gateway
# end-to-end against a fake main/: a PULL socket on the outbound topic
docker compose up -d --build postgres executor
```

Verified: [ ] baseline green on the branch before Layer 1.

---

## Layer 1: Outbound encoder

### Task 1.1: The v2 envelope

**Files:** `crates/mq_gateway/src/wire.rs`.

**Interface:**
```rust
pub fn encode_outbound(event: &PositionStateEvent, state: &PositionState) -> Result<Vec<u8>, WireError>;
```
Note the added `state` parameter: v1 could encode from the event alone precisely because it threw the state away for every variant but `Opened`. The signature change is the fix.

**Unit tests (RED) — one per bullet of §6.1:**
- `schema` is `2` on every message.
- **Every** event kind carries a populated `position_state` — a parametrised test over all variants asserting `status` is never `"flat_or_unchanged"` and that `net_size`/`avg_entry_price` are present whenever the position is not flat. This is the v1 regression, so it gets the most direct test.
- `not_placed` carries its `reason`; `decision_id` is present as a correlation field on every event that has one.
- `filled` and `partially_filled` are emitted by the variants that mean them — the contract has listed `"filled"` since L4 was written with no producer, and this test is what makes that no longer true.
- `target_hit`, `sl_moved`, `not_filled`, `already_closed` each map to their own kind, not to the `state_update` catch-all.
- **No `fills` key appears in any encoded message**, for any input (§6.1's "no per-fill array, ever" — a structural test over the serialised JSON, not over the DTO).
- Decimal fields serialise as JSON numbers with full precision, not as floats that round a price.

### Task 1.2: `PositionStateEvent` → event-kind mapping

**Unit tests (RED):** the mapping is total — a match over every variant with no catch-all arm, so adding a variant later fails to compile rather than silently becoming `state_update`. `Modified` does **not** exist as a kind (B8 is deferred, [../TECH_DEBT.md](../TECH_DEBT.md) §10) and an event kind with no producer is the trap `"filled"` was in.

**Integration test → Layer 2 (RED in Docker):** `crates/mq_gateway/tests/` — bind the transport, publish one event of every kind, receive them on a PULL socket, and assert each decodes as valid JSON with `schema: 2` and a complete `position_state`. RED until Layer 2's publisher exists.

**Layer 1 gate:** unit tests green, integration RED. Commit: `feat(mq_gateway): wire v2 outbound envelope with full state on every event`.

---

## Layer 2: Publisher behaviour

### Task 2.1: `publish_state` takes the state

**Interface:** `StateOutbound::publish_state(&self, event: PositionStateEvent, state: PositionState) -> Result<(), MqError>`; `drive`'s outbound loop reads the current state from the engine alongside the event.

**Unit tests (RED):** the published state is the state **at the moment of the event**, not a later one — drive two events in quick succession and assert each message carries its own snapshot; a publish failure is reported, not swallowed (this is [../TECH_DEBT.md](../TECH_DEBT.md) §3's "drops every error", so do not make it worse — if §3 is still open, leave a pointer, do not quietly fix it here).

### Task 2.2: Snapshot heartbeat (§6.3)

**Interface:** one task, `POSITION_HEARTBEAT_SECS` (default 30), publishing a `state_update` per live position.

**Unit tests (RED):** publishes once per live position per interval; publishes **nothing** when no position is live; **touches no database** (a `StateStore` spy asserting zero calls — §5.1's rule made executable); stops on shutdown.

**Layer 2 gate:** Layer 1's integration test GREEN. Commit: `feat(mq_gateway): publish full state, snapshot heartbeat`.

---

## Layer 3: Inbound `position_query` (§6.2)

### Task 3.1: Decode and answer

**Interface:** `InboundPayload::PositionQuery { pair: Option<String> }`; answered with one `state_update` per live position, or a single `status: flat` message for a queried pair holding nothing.

**Unit tests (RED):** a query naming a pair answers for that pair only; a query omitting `pair` answers for all; a pair with no position answers `flat` rather than staying silent (silence is indistinguishable from a dropped message — the whole reason this exists); an unknown `type` still errors as today.

**Integration test (RED in Docker):** a fake main/ that has never seen an event sends `position_query` and receives the live position — the acceptance criterion "`position_query` from a freshly started main/ returns the live position".

**Layer 3 gate:** full suite green. Commit: `feat(mq_gateway): position_query resynchronisation`.

---

## Layer 4: Contract fixtures for plan 6/9

### Task 4.1: Golden messages

**Files:** `crates/mq_gateway/tests/fixtures/*.json` (new), committed.

**Interface:** one canonical encoded message per event kind, generated by this crate's tests and asserted byte-stable.

**Constraints:** plan 6/9 (main/'s Python consumer) codes against **these files**, not against a hand-written reading of the spec. They are the contract in executable form, and they are what lets that plan proceed in parallel in another repository and another language without guessing. A change to the encoder that changes a fixture must be a deliberate, reviewed diff.

**Layer 4 gate:** fixtures generated, committed, and asserted stable by a test. Commit: `test(mq_gateway): golden wire v2 fixtures as the cross-repo contract`.

---

## Done when

- [ ] Every layer gate green in Docker, in order.
- [ ] Spec acceptance criteria satisfied here: "`position_query` from a freshly started main/ returns the live position"; the encoder half of "main/ receives and decodes every event kind".
- [ ] Fixtures handed to plan 6/9.
- [ ] `position-wire-v2` merged into `position-management` (after user confirmation).
