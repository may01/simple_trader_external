# Standalone Indicator Broadcast (main/ -> executor) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `indicator_update` MQ message so `main/` can publish named indicator readings (support/resistance-with-volume, or plain `kind: none` values) to `trade_executor` independently of any trade decision, and have the executor store, persist, and expose them.

**Architecture:** Extends the existing L4 (`mq_gateway`) wire format with a fourth inbound message type alongside `open`/`close`/`modify`/`force_close`, reusing the same dedup/id-space and inbound topic. Postgres (L5, `state_store`) is the store: one new append-only `indicators` table holds every reading, fronted by a write-through/read-through cache keyed by `(pair, name)` — `record_indicator` refreshes the entry once its INSERT commits, and `current_indicator` serves the cached reading until that reading's own `expires_at` passes, falling back to a query otherwise. So repeated reads inside a validity window cost nothing, a freshly written reading is visible at once, and there's no duplicate current-value table to maintain. That cache is private to the store; `local_analysis` is untouched by this plan, and `combined_levels`/wall-detection keeps working exactly as today. On `main/`'s side, a new `main/mq/` module reads an operator-configured allowlist of `main/indicators/` framework fields and PUSHes them every tick as `kind: "none"` readings (v1 scope — support/resistance classification is a later, separate increment with an undecided source).

**Note on plan organization:** this feature spans `trade_executor`'s own existing layer taxonomy (its specs live at `external/executor/specs/layers/L0`-`L9`) plus one new `main/` module. `simple_trader`'s `layer-first-planning` skill's specific layer table (data acquisition / training pipeline / indicators / backtesting / ...) is scoped to `main/`'s own pipeline and doesn't fit a cross-repo wire-protocol extension — this plan instead applies that skill's *principles* (Docker-first entry point, interface-before-code, RED integration test at each boundary, no layer started before the previous one is green in Docker) using `trade_executor`'s real layers (L4 -> L5 -> L9/orchestrator) and then the one `main/` layer this feature actually touches (its indicator-computation layer).

**Tech Stack:** Rust (`trade_executor`, workspace at `trade_executor/.worktrees/layer-implementation`, branch `layer-implementation`): `serde`/`serde_json`, `sqlx` (Postgres), `tokio`, `chrono`, `zeromq`. Python (`main/`, separate repo, base branch `experimental_imp_2`): `pyzmq` (new dependency), `pyyaml`, `pytest`.

**Spec:** `external/executor/specs/2026-09-19-level-broadcast-design.md`

## Global Constraints

- Work on the executor side happens in the `layer-implementation` worktree (`trade_executor/.worktrees/layer-implementation`), branch `layer-implementation`. One commit per task, after its tests are green.
- Work on the `main/` side (Tasks 6-9) happens in the separate `main/` repo, branched off **`experimental_imp_2`** — note the spelling, no "l", not `experimental_impl_1` and not `main`. That is the base branch for this development stage: cut a dedicated task branch from it (e.g. `indicator-broadcast-sender`) before the first `main/` change, and merge back into it when the sender is green. One commit per task there too.
- Migrations are append-only (`db_schema/src/lib.rs`'s own doc comment) — the new `indicators` table is a new numbered file, `migrations/0007_indicators.sql`, never an edit to an existing one. `db_schema::SCHEMA_VERSION` must bump from `6` to `7` in the same commit, or `visualizer_server`'s `check_schema` refuses to serve.
- `indicator_update` is inbound-only (main/ -> executor) — no outbound/PULL handling for indicators in this plan (per spec §4, last bullet).
- The only indicator cache is the private write-through/read-through one inside `state_store` (Task 3) — no other component holds indicator state, and `local_analysis` is untouched by this plan. `current_indicator`'s output is **not** wired into `combined_levels` or any signal check — that machinery stays exactly as it is today, fed only by decision-attached `TradeDecisionPayload.levels`. Checking logic against indicators is explicitly future work (spec §3/§5).
- v1's `main/` sender publishes `kind: "none"` only. No `volume`, no `support`/`resistance` classification, no `levels.py` involvement anywhere in this plan (spec §4/§4.1 — that source is undecided and out of scope here).
- The `kind` field's wire shape is an internally-tagged enum where `Support`/`Resistance` carry `volume` as part of their own variant and `None` carries nothing else — "volume present with kind none" must be a parse error, not a validated-then-rejected value (spec §2).
- `main/`'s allowlist of published `(name, tf)` pairs is operator-configured (`main/configs/shared_indicators_config.yaml`), never auto-selected from all of `main/indicators/`'s fields. Initial concrete allowlist: `ema_7`, `ema_14`, `ema_25` at timeframes `15`, `60`, `240` (spec §4).

---

## Docker Entry Points

**Executor side** (from `trade_executor/.worktrees/layer-implementation`):
```bash
docker compose run --rm test
```
**Pass `--build`: `docker compose run --build --rm test`.** Without it, compose reuses a stale cached image and silently runs the previous test binary — during Task 3 this produced a green run whose output contained none of the new tests. This builds the `test` target and runs `cargo test --workspace` (`docker-compose.yml`'s `test` service, `command: ["cargo", "test", "--workspace"]`). Every Rust task below (Tasks 1-6) must pass this before being considered done — running `cargo test` on the host is a faster inner loop while iterating, but the task isn't complete until this Docker command is green.

**Main/ side** (from `main/`, on a branch off `experimental_imp_2`):
```bash
docker compose run --rm live pytest tests/ -v --ignore=tests/nn
```
**`--ignore=tests/nn` is mandatory, confirmed 2026-09-20** — without it the run never reaches a single test: `tests/nn/test_tpe_startup.py` and `tests/nn/test_build_spec_layers.py` both `import optuna`, which the `live` image does not install, so pytest aborts with `Interrupted: 2 errors during collection` (`ModuleNotFoundError: No module named 'optuna'`). This is pre-existing and unrelated to this plan — do not "fix" it here.

**Known-red baseline, confirmed 2026-09-20**: with `--ignore=tests/nn`, the suite is **2081 passed, 21 failed, 2 skipped** on this feature's branch (the base branch itself was not re-run; the 21 are attributed as pre-existing because the branch's diff is additions-only and touches none of the failing modules). The 21 failures are `tests/test_phase09_task03_trainer.py` (9), `tests/test_phase12_task01_chart_renderer.py` (6), `tests/test_phase12_task14_label_markers.py` (6) — none of which this plan's branch touches (its diff vs `experimental_imp_2` is additions-only across `config_loader.py`, `configs/`, `mq/`, `robots/robot.py`, `trader.py`, `tests/`). So "full suite green" is **not** an achievable exit condition for any main/ task below; the real condition is **no new failures beyond those 21, and every test this plan adds passing**.

No dedicated `test` service exists in `main/docker-compose.yml` today — `live` is the leanest service built from the base `simple_trader` image, which already bakes in `pytest`/`pytest-mock` via `requirements.txt`, and mounts `.:/code`. This command was originally inferred (no README/CI references `pytest` at all) and has since been **confirmed to work as written above**, with the two caveats stated above it.

Verified: [ ] `docker compose run --rm test` succeeds on the current `layer-implementation` worktree HEAD (run this before Task 1, to confirm the baseline is green before adding anything).

---

## Task 1: Wire schema — `indicator_update` (L4, `mq_gateway`)

**Files:**
- Modify: `crates/mq_gateway/src/wire.rs`

**Interfaces:**
- Produces: `pub enum InboundMessage { Decision(...), Force(...), Indicator(DecisionId, IndicatorUpdate) }` (extends the existing enum, `wire.rs:150-153`) and a new public `IndicatorUpdate` struct:
  ```rust
  pub struct IndicatorUpdate {
      pub pair: execution::Pair,
      pub name: String,
      pub value: rust_decimal::Decimal,
      pub kind: IndicatorKind,
      pub expires_at: chrono::DateTime<chrono::Utc>,
  }
  pub enum IndicatorKind {
      Support { volume: rust_decimal::Decimal },
      Resistance { volume: rust_decimal::Decimal },
      None,
  }
  ```
  `decode_inbound(bytes: &[u8]) -> Result<InboundMessage, WireError>` gains the new match arm; existing signature unchanged.

- [ ] **Step 1: Write the failing round-trip tests**

Add to `crates/mq_gateway/src/wire.rs`'s existing `#[cfg(test)] mod tests` block:

```rust
#[test]
fn decode_inbound_accepts_a_support_indicator_with_volume() {
    let bytes = br#"{"id":"i1","type":"indicator_update","pair":"BTCUSDT","name":"15_ema_7","value":12345.0,"kind":"support","volume":3.25,"expires_at":"2026-09-20T00:00:00Z"}"#;
    let msg = decode_inbound(bytes).unwrap();
    match msg {
        InboundMessage::Indicator(id, upd) => {
            assert_eq!(id, DecisionId("i1".into()));
            assert_eq!(upd.pair, execution::Pair("BTCUSDT".into()));
            assert_eq!(upd.name, "15_ema_7");
            assert_eq!(upd.value, Decimal::new(123450, 1));
            match upd.kind {
                IndicatorKind::Support { volume } => assert_eq!(volume, Decimal::new(325, 2)),
                other => panic!("expected Support, got {other:?}"),
            }
        }
        other => panic!("expected Indicator, got {other:?}"),
    }
}

#[test]
fn decode_inbound_accepts_a_none_kind_indicator_with_no_volume_field() {
    let bytes = br#"{"id":"i2","type":"indicator_update","pair":"BTCUSDT","name":"15_rsi_14","value":63.4,"kind":"none","expires_at":"2026-09-20T00:00:00Z"}"#;
    let msg = decode_inbound(bytes).unwrap();
    match msg {
        InboundMessage::Indicator(_, upd) => assert!(matches!(upd.kind, IndicatorKind::None)),
        other => panic!("expected Indicator, got {other:?}"),
    }
}

#[test]
fn decode_inbound_rejects_a_none_kind_indicator_with_a_stray_volume_field() {
    let bytes = br#"{"id":"i3","type":"indicator_update","pair":"BTCUSDT","name":"x","value":1.0,"kind":"none","volume":9.9,"expires_at":"2026-09-20T00:00:00Z"}"#;
    assert!(decode_inbound(bytes).is_err(), "kind:none with a volume field must not parse");
}

#[test]
fn decode_inbound_rejects_a_support_indicator_missing_volume() {
    let bytes = br#"{"id":"i4","type":"indicator_update","pair":"BTCUSDT","name":"x","value":1.0,"kind":"support","expires_at":"2026-09-20T00:00:00Z"}"#;
    assert!(decode_inbound(bytes).is_err(), "kind:support without volume must not parse");
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cargo test -p mq_gateway wire:: -- --nocapture` (from `trade_executor/.worktrees/layer-implementation`)
Expected: FAIL to compile — `InboundMessage::Indicator`, `IndicatorKind`, `IndicatorUpdate` don't exist yet.

- [ ] **Step 3: Implement the wire types and decode arm**

In `crates/mq_gateway/src/wire.rs`, alongside the existing `InboundPayload` enum (`wire.rs:47-52`):

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum InboundPayload {
    Open(TradeDecisionPayload),
    Close(TradeDecisionPayload),
    Modify(TradeDecisionPayload),
    ForceClose(ForceActionPayload),
    ForceOverride(ForceActionPayload),
    IndicatorUpdate(IndicatorUpdatePayload),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct IndicatorUpdatePayload {
    pair: String,
    name: String,
    value: Decimal,
    #[serde(flatten)]
    kind: IndicatorKindDto,
    expires_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum IndicatorKindDto {
    Support { volume: Decimal },
    Resistance { volume: Decimal },
    None,
}

impl From<IndicatorKindDto> for IndicatorKind {
    fn from(k: IndicatorKindDto) -> Self {
        match k {
            IndicatorKindDto::Support { volume } => IndicatorKind::Support { volume },
            IndicatorKindDto::Resistance { volume } => IndicatorKind::Resistance { volume },
            IndicatorKindDto::None => IndicatorKind::None,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum IndicatorKind {
    Support { volume: Decimal },
    Resistance { volume: Decimal },
    None,
}

#[derive(Debug, Clone, PartialEq)]
pub struct IndicatorUpdate {
    pub pair: execution::Pair,
    pub name: String,
    pub value: Decimal,
    pub kind: IndicatorKind,
    pub expires_at: chrono::DateTime<chrono::Utc>,
}
```

Extend `InboundMessage` (`wire.rs:150-153`):
```rust
#[derive(Debug, Clone, PartialEq)]
pub enum InboundMessage {
    Decision(DecisionId, TradeDecision),
    Force(DecisionId, ForceAction),
    Indicator(DecisionId, IndicatorUpdate),
}
```

Add the match arm in `decode_inbound` (`wire.rs:159-179`), alongside the existing `InboundPayload::ForceOverride(_) => Err(...)` arm:
```rust
        InboundPayload::IndicatorUpdate(p) => {
            let expires_at = chrono::DateTime::parse_from_rfc3339(&p.expires_at)
                .map_err(|e| WireError::Json(format!("invalid expires_at: {e}")))?
                .with_timezone(&chrono::Utc);
            Ok(InboundMessage::Indicator(
                id,
                IndicatorUpdate {
                    pair: execution::Pair(p.pair),
                    name: p.name,
                    value: p.value,
                    kind: p.kind.into(),
                    expires_at,
                },
            ))
        }
```
Note `decode_inbound`'s existing `let id = DecisionId(envelope.id);` line is reused as-is (`wire.rs:158`) — this new arm doesn't need its own `id` handling, same as every other arm.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cargo test -p mq_gateway wire:: -- --nocapture`
Expected: PASS, all 4 new tests.

- [ ] **Step 5: Commit**

```bash
cd trade_executor/.worktrees/layer-implementation
git add crates/mq_gateway/src/wire.rs
git commit -m "feat(mq_gateway): add indicator_update inbound message type"
```

---

## Task 2: Gateway plumbing — `subscribe_indicators` (L4, `mq_gateway`)

**Files:**
- Modify: `crates/mq_gateway/src/gateway.rs`
- Modify: `crates/mq_gateway/src/lib.rs` (re-export new public types)

**Interfaces:**
- Consumes: `InboundMessage::Indicator`, `wire::IndicatorUpdate`, `wire::decode_inbound` (Task 1).
- Produces:
  ```rust
  pub type IndicatorStream = Pin<Box<dyn Stream<Item = (DecisionId, wire::IndicatorUpdate)> + Send>>;
  pub trait IndicatorInbound: Send + Sync {
      fn subscribe_indicators(&self) -> IndicatorStream;
  }
  ```
  implemented by `MqGateway`, reusing the same `SharedDedup` instance as `subscribe_decisions`/`subscribe_force` (per spec §2: "same channel/path, not a side channel").

- [ ] **Step 1: Write the failing tests**

Add to `crates/mq_gateway/src/gateway.rs`'s `#[cfg(test)] mod tests`:

```rust
#[tokio::test]
async fn subscribe_indicators_yields_indicator_update_only() {
    let (gateway, transport) = gateway();
    let mut indicators = gateway.subscribe_indicators();
    transport
        .send(
            "in",
            br#"{"id":"x1","type":"indicator_update","pair":"BTCUSDT","name":"15_ema_7","value":1.0,"kind":"none","expires_at":"2026-09-20T00:00:00Z"}"#.to_vec(),
        )
        .unwrap();
    let (id, upd) = indicators.next().await.unwrap();
    assert_eq!(id, DecisionId("x1".into()));
    assert_eq!(upd.name, "15_ema_7");
}

#[tokio::test]
async fn subscribe_indicators_ignores_decision_messages_on_the_same_topic() {
    let (gateway, transport) = gateway();
    let mut indicators = gateway.subscribe_indicators();
    transport
        .send(
            "in",
            br#"{"id":"d1","type":"open","pair":"BTCUSDT","side":"long","timeframe":"m1","levels":[]}"#.to_vec(),
        )
        .unwrap();
    transport
        .send(
            "in",
            br#"{"id":"x1","type":"indicator_update","pair":"BTCUSDT","name":"n","value":1.0,"kind":"none","expires_at":"2026-09-20T00:00:00Z"}"#.to_vec(),
        )
        .unwrap();
    let (id, _) = indicators.next().await.unwrap();
    assert_eq!(id, DecisionId("x1".into()), "the decision message must not appear on the indicator stream");
}

#[tokio::test]
async fn subscribe_indicators_dedups_by_id_shared_with_decisions() {
    let (gateway, transport) = gateway();
    let mut decisions = gateway.subscribe_decisions();
    let mut indicators = gateway.subscribe_indicators();
    // Same id space: consuming a decision with id "dup" first, then an
    // indicator_update reusing "dup", must still be dedup-checked against
    // the same SharedDedup set.
    transport
        .send("in", br#"{"id":"dup","type":"open","pair":"BTCUSDT","side":"long","timeframe":"m1","levels":[]}"#.to_vec())
        .unwrap();
    assert!(decisions.next().await.is_some());
    transport
        .send(
            "in",
            br#"{"id":"dup","type":"indicator_update","pair":"BTCUSDT","name":"n","value":1.0,"kind":"none","expires_at":"2026-09-20T00:00:00Z"}"#.to_vec(),
        )
        .unwrap();
    let result = tokio::time::timeout(std::time::Duration::from_millis(200), indicators.next()).await;
    assert!(result.is_err(), "a reused id must be dropped by dedup even across message types");
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cargo test -p mq_gateway gateway:: -- --nocapture`
Expected: FAIL to compile — `subscribe_indicators` doesn't exist.

- [ ] **Step 3: Implement**

In `crates/mq_gateway/src/gateway.rs`, add near `DecisionInbound`/`StateOutbound` (`gateway.rs:20-27`):
```rust
pub type IndicatorStream = Pin<Box<dyn Stream<Item = (DecisionId, crate::wire::IndicatorUpdate)> + Send>>;

pub trait IndicatorInbound: Send + Sync {
    fn subscribe_indicators(&self) -> IndicatorStream;
}
```
Update the `use crate::wire::{decode_inbound, encode_outbound, InboundMessage};` import to also bring in whatever's needed, then implement alongside `impl DecisionInbound for MqGateway` (`gateway.rs:94-134`):
```rust
impl IndicatorInbound for MqGateway {
    fn subscribe_indicators(&self) -> IndicatorStream {
        let raw = self.transport.recv(&self.inbound_topic);
        let dedup = self.seen_ids.clone();
        Box::pin(raw.filter_map(move |bytes| {
            let dedup = dedup.clone();
            async move {
                match decode_inbound(&bytes) {
                    Ok(InboundMessage::Indicator(id, upd)) => {
                        if dedup.first_time_seeing(&id) {
                            Some((id, upd))
                        } else {
                            None
                        }
                    }
                    Ok(InboundMessage::Decision(_, _)) | Ok(InboundMessage::Force(_, _)) | Err(_) => None,
                }
            }
        }))
    }
}
```
Update `crates/mq_gateway/src/lib.rs`'s two relevant `pub use` lines (confirmed present, `lib.rs:10-13`):
```rust
pub use gateway::{DecisionInbound, DecisionStream, ForceStream, IndicatorInbound, IndicatorStream, MqGateway, MqGatewayConfig, StateOutbound};
pub use wire::{decode_inbound, encode_force_close, encode_outbound, IndicatorKind, IndicatorUpdate, InboundMessage, WireError};
```
(the `IndicatorKind`/`IndicatorUpdate` addition to the `wire::` line covers Task 1's new public types too, which Task 1 itself didn't yet export — Task 4 needs both from outside this crate.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cargo test -p mq_gateway gateway:: -- --nocapture`
Expected: PASS, all 3 new tests plus every pre-existing `gateway::tests` test still green.

- [ ] **Step 5: Commit**

```bash
git add crates/mq_gateway/src/gateway.rs crates/mq_gateway/src/lib.rs
git commit -m "feat(mq_gateway): add subscribe_indicators sharing the decision/force dedup space"
```

---

## Task 3: Persistence + cached query — `indicators` table (L5, `state_store` + `db_schema`)

`IndicatorReading`/`IndicatorKind` are owned by `state_store` itself in this design — there is no `local_analysis::IndicatorStore` (removed per the pivot to "Postgres is the store"; `local_analysis` is untouched by this plan). `mq_gateway`'s orchestrator glue (Task 4) builds this same type directly from `wire::IndicatorUpdate`.

**One table only — deliberately not the two-table `analysis_current`/`analysis_log` shape.** A reading carries its own `expires_at`, so cheap repeated reads come from an in-process cache, not from maintaining a duplicate current-value row on every write. `record_indicator` is a single `INSERT` (mirroring `record_signal`, `pg.rs:882-910`) followed by a cache update; `current_indicator` serves that cache when the entry is still inside its validity window, falling back to an `ORDER BY received_at DESC LIMIT 1` query otherwise. Write-through plus read-through means the ingesting process never serves a stale reading, and a read-only process (visualizer, fresh restart) still works off the query path.

**Files:**
- Create: `migrations/0007_indicators.sql`
- Modify: `crates/db_schema/src/lib.rs` (`SCHEMA_VERSION` 6 -> 7, doc comment)
- Modify: `crates/state_store/src/lib.rs` (new `IndicatorReading`/`IndicatorKind` types, `IndicatorSink` trait, re-exports)
- Modify: `crates/state_store/src/dto.rs` (new `IndicatorReadingDto`)
- Modify: `crates/state_store/src/pg.rs` (new `indicator_cache` field on `StateStoreImpl`, `IndicatorSink` impl with `record_indicator`, and cached `current_indicator`)

**Interfaces:**
- Consumes: `market_data::Pair`, `exchange_adapter::Ts` (both already used throughout this crate).
- Produces:
  ```rust
  // in crates/state_store/src/lib.rs
  pub enum IndicatorKind {
      Support { volume: rust_decimal::Decimal },
      Resistance { volume: rust_decimal::Decimal },
      None,
  }
  pub struct IndicatorReading {
      pub name: String,
      pub value: rust_decimal::Decimal,
      pub kind: IndicatorKind,
      pub expires_at: Ts,
  }
  #[async_trait]
  pub trait IndicatorSink: Send + Sync {
      async fn record_indicator(&self, pair: Pair, reading: &IndicatorReading) -> Result<(), StoreError>;
  }
  // on the same struct read_signal_log/current_analysis live on
  pub async fn current_indicator(&self, pair: Pair, name: &str, now: Ts) -> Result<Option<IndicatorReading>, StoreError>;
  ```
  `IndicatorSink` is implemented by `StateStoreImpl`, mirroring `SignalSink::record_signal`'s shape, and additionally updates the cache with what it wrote once the `INSERT` commits. `current_indicator` serves a cached entry while `now < cached.expires_at`, otherwise queries the newest non-expired row and re-caches it.

- [ ] **Step 1: Write the migration**

Create `migrations/0007_indicators.sql`:
```sql
-- `indicators`: every `indicator_update` main/ has sent, per
-- specs/2026-09-19-level-broadcast-design.md. Append-only, one row per
-- message, same call as `signal_log`. Deliberately NOT paired with a
-- current-value table the way `analysis_log` is with `analysis_current`:
-- each row carries its own `expires_at`, so `current_indicator` caches
-- the row it fetched until that timestamp instead of the write path
-- maintaining a duplicate row. `kind`/`volume` mirror the wire format's
-- IndicatorKindDto: `volume` is NULL exactly when `kind = 'none'`,
-- non-NULL otherwise -- enforced by a CHECK rather than trusted to the
-- application, since writer and readers must agree the invariant always
-- holds, not just at write time.
CREATE TABLE indicators (
    seq         bigint PRIMARY KEY DEFAULT nextval('global_ins_seq'),
    pair        text   NOT NULL,
    name        text   NOT NULL,
    value       numeric NOT NULL,
    kind        text   NOT NULL CHECK (kind IN ('support', 'resistance', 'none')),
    volume      numeric,
    expires_at  bigint NOT NULL,
    received_at bigint NOT NULL,
    CONSTRAINT volume_matches_kind CHECK (
        (kind = 'none' AND volume IS NULL) OR (kind IN ('support', 'resistance') AND volume IS NOT NULL)
    )
);
-- Serves current_indicator's lookup: (pair, name) equality plus a
-- received_at DESC ordering, so the newest row per name is an index
-- scan's first hit rather than a sort over the pair's whole history.
CREATE INDEX indicators_pair_name_received ON indicators (pair, name, received_at DESC);
```

- [ ] **Step 2: Bump `SCHEMA_VERSION` and doc comment**

In `crates/db_schema/src/lib.rs`, update the module doc comment to mention `0007_indicators.sql` (mirroring the existing list style) and change:
```rust
pub const SCHEMA_VERSION: i64 = 6;
```
to
```rust
pub const SCHEMA_VERSION: i64 = 7;
```

- [ ] **Step 3: Run the migration test to verify it applies cleanly**

Run: `cargo test -p db_schema -- --nocapture` (exercises `crates/db_schema/tests/migrations.rs`, which runs every migration against a real Postgres — requires the `postgres` service; use `docker compose run --rm test` if no local Postgres is reachable).
Expected: PASS — migration applies with no SQL errors.

- [ ] **Step 4: Write the domain types, DTO, sink, and reader (RED first)**

Add to `crates/state_store/src/lib.rs`, alongside `DecisionRecord` (`lib.rs:31-...`):
```rust
#[derive(Debug, Clone, PartialEq)]
pub enum IndicatorKind {
    Support { volume: rust_decimal::Decimal },
    Resistance { volume: rust_decimal::Decimal },
    None,
}

#[derive(Debug, Clone, PartialEq)]
pub struct IndicatorReading {
    pub name: String,
    pub value: rust_decimal::Decimal,
    pub kind: IndicatorKind,
    pub expires_at: Ts,
}

#[async_trait]
pub trait IndicatorSink: Send + Sync {
    async fn record_indicator(&self, pair: Pair, reading: &IndicatorReading) -> Result<(), StoreError>;
}
```

Add to `crates/state_store/src/dto.rs`, mirroring `SignalEventDto`'s section:
```rust
#[derive(Debug, Clone, Serialize)]
pub(crate) struct IndicatorReadingDto {
    pub name: String,
    pub value: Decimal,
    pub kind: &'static str,
    pub volume: Option<Decimal>,
}

impl From<&crate::IndicatorReading> for IndicatorReadingDto {
    fn from(r: &crate::IndicatorReading) -> Self {
        let (kind, volume) = match r.kind {
            crate::IndicatorKind::Support { volume } => ("support", Some(volume)),
            crate::IndicatorKind::Resistance { volume } => ("resistance", Some(volume)),
            crate::IndicatorKind::None => ("none", None),
        };
        Self { name: r.name.clone(), value: r.value, kind, volume }
    }
}
```

Add failing tests to `crates/state_store/src/pg.rs`'s test module (find it via the existing `signal_log`-round-trip test for the exact fixture/pool-setup pattern to copy):
```rust
#[tokio::test]
async fn record_indicator_persists_a_support_reading_with_volume() {
    let store = test_store().await; // reuse whatever helper record_signal's own test uses to get a StateStoreImpl against test_db()
    let pair = Pair("BTCUSDT".into());
    let reading = IndicatorReading {
        name: "15_ema_7".into(),
        value: Decimal::new(123450, 1),
        kind: IndicatorKind::Support { volume: Decimal::new(325, 2) },
        expires_at: Ts(2_000_000_000_000),
    };
    store.record_indicator(pair.clone(), &reading).await.unwrap();

    let row: (String, String, Decimal, Option<Decimal>) =
        sqlx::query_as("SELECT pair, kind, value, volume FROM indicators WHERE pair = $1")
            .bind(&pair.0)
            .fetch_one(&store.pool)
            .await
            .unwrap();
    assert_eq!(row.0, "BTCUSDT");
    assert_eq!(row.1, "support");
    assert_eq!(row.3, Some(Decimal::new(325, 2)));
}

#[tokio::test]
async fn record_indicator_persists_a_none_kind_reading_with_null_volume() {
    let store = test_store().await;
    let pair = Pair("BTCUSDT".into());
    let reading = IndicatorReading {
        name: "15_rsi_14".into(),
        value: Decimal::new(634, 1),
        kind: IndicatorKind::None,
        expires_at: Ts(2_000_000_000_000),
    };
    store.record_indicator(pair.clone(), &reading).await.unwrap();

    let row: (String, Option<Decimal>) =
        sqlx::query_as("SELECT kind, volume FROM indicators WHERE pair = $1 AND name = $2")
            .bind(&pair.0)
            .bind("15_rsi_14")
            .fetch_one(&store.pool)
            .await
            .unwrap();
    assert_eq!(row.0, "none");
    assert_eq!(row.1, None);
}

#[tokio::test]
async fn record_indicator_appends_rather_than_replacing() {
    let store = test_store().await;
    let pair = Pair("BTCUSDT".into());
    store.record_indicator(pair.clone(), &IndicatorReading {
        name: "15_ema_7".into(), value: Decimal::new(1, 0), kind: IndicatorKind::None, expires_at: Ts(1000),
    }).await.unwrap();
    store.record_indicator(pair.clone(), &IndicatorReading {
        name: "15_ema_7".into(), value: Decimal::new(2, 0), kind: IndicatorKind::None, expires_at: Ts(2000),
    }).await.unwrap();

    let log_count: (i64,) = sqlx::query_as("SELECT count(*) FROM indicators WHERE pair = $1 AND name = $2")
        .bind(&pair.0).bind("15_ema_7").fetch_one(&store.pool).await.unwrap();
    assert_eq!(log_count.0, 2, "indicators must keep both rows");
}

#[tokio::test]
async fn current_indicator_returns_the_newest_non_expired_row() {
    let store = test_store().await;
    let pair = Pair("BTCUSDT".into());
    store.record_indicator(pair.clone(), &IndicatorReading {
        name: "15_ema_7".into(), value: Decimal::new(1, 0), kind: IndicatorKind::None, expires_at: Ts(1000),
    }).await.unwrap();
    store.record_indicator(pair.clone(), &IndicatorReading {
        name: "15_ema_7".into(), value: Decimal::new(2, 0), kind: IndicatorKind::None, expires_at: Ts(2000),
    }).await.unwrap();

    let got = store.current_indicator(pair, "15_ema_7", Ts(1500)).await.unwrap().unwrap();
    assert_eq!(got.value, Decimal::new(2, 0), "must return the newest row by received_at, not the first");
}

#[tokio::test]
async fn current_indicator_returns_none_when_the_only_row_is_expired() {
    let store = test_store().await;
    let pair = Pair("BTCUSDT".into());
    store.record_indicator(pair.clone(), &IndicatorReading {
        name: "x".into(), value: Decimal::new(1, 0), kind: IndicatorKind::None, expires_at: Ts(1000),
    }).await.unwrap();

    assert!(store.current_indicator(pair, "x", Ts(1000)).await.unwrap().is_none(), "now == expires_at must count as expired");
}

#[tokio::test]
async fn current_indicator_returns_none_when_never_sent() {
    let store = test_store().await;
    assert!(store.current_indicator(Pair("BTCUSDT".into()), "nonexistent", Ts(0)).await.unwrap().is_none());
}

#[tokio::test]
async fn record_indicator_refreshes_the_cache_immediately() {
    let store = test_store().await;
    let pair = Pair("BTCUSDT".into());
    store.record_indicator(pair.clone(), &IndicatorReading {
        name: "15_ema_7".into(), value: Decimal::new(1, 0), kind: IndicatorKind::None, expires_at: Ts(1000),
    }).await.unwrap();
    // Populates the cache from the write path.
    assert_eq!(store.current_indicator(pair.clone(), "15_ema_7", Ts(100)).await.unwrap().unwrap().value, Decimal::new(1, 0));

    // A newer reading is written well inside the previous entry's window:
    // write-through must make it visible at once, not one window later.
    store.record_indicator(pair.clone(), &IndicatorReading {
        name: "15_ema_7".into(), value: Decimal::new(9, 0), kind: IndicatorKind::None, expires_at: Ts(5000),
    }).await.unwrap();
    let got = store.current_indicator(pair, "15_ema_7", Ts(200)).await.unwrap().unwrap();
    assert_eq!(got.value, Decimal::new(9, 0), "a write must refresh the cache entry immediately");
}

#[tokio::test]
async fn current_indicator_serves_the_cached_value_without_requerying_until_its_expiry() {
    let store = test_store().await;
    let pair = Pair("BTCUSDT".into());
    store.record_indicator(pair.clone(), &IndicatorReading {
        name: "15_ema_7".into(), value: Decimal::new(1, 0), kind: IndicatorKind::None, expires_at: Ts(1000),
    }).await.unwrap();
    assert_eq!(store.current_indicator(pair.clone(), "15_ema_7", Ts(100)).await.unwrap().unwrap().value, Decimal::new(1, 0));

    // Insert out-of-band (raw SQL, bypassing record_indicator, so the
    // cache is NOT refreshed) -- proves reads inside the window don't
    // re-query.
    sqlx::query(
        "INSERT INTO indicators (pair, name, value, kind, volume, expires_at, received_at) \
         VALUES ($1, $2, $3, 'none', NULL, $4, $5)",
    )
    .bind(&pair.0).bind("15_ema_7").bind(Decimal::new(9, 0)).bind(5000_i64).bind(9999_i64)
    .execute(&store.pool).await.unwrap();

    let cached = store.current_indicator(pair.clone(), "15_ema_7", Ts(200)).await.unwrap().unwrap();
    assert_eq!(cached.value, Decimal::new(1, 0), "inside the cached entry's window, no re-query happens");

    // Past the cached entry's expires_at, the next call re-queries and
    // picks up the out-of-band row.
    let refreshed = store.current_indicator(pair, "15_ema_7", Ts(1500)).await.unwrap().unwrap();
    assert_eq!(refreshed.value, Decimal::new(9, 0), "once the cached entry expires, the table is queried again");
}
```
(Adjust the pool-access/test-fixture calls — `test_store()`/`store.pool` — to whatever the actual existing `record_signal` test in this same file uses; that test is the ground truth for this crate's exact Postgres-test-harness idiom, copy it rather than the sketch above verbatim. `current_indicator` in these tests is called directly on `store` — if reads and writes are genuinely separate types in this crate rather than the same struct wearing two trait hats, adjust the calls to go through whichever one the existing `current_analysis`-style tests actually construct, and put the cache field on that same type.)

- [ ] **Step 5: Run tests to verify they fail**

Run: `cargo test -p state_store -- --nocapture`
Expected: FAIL to compile — `record_indicator`/`IndicatorSink`/`current_indicator` don't exist yet.

- [ ] **Step 6: Add the cache field, then implement `record_indicator` and `current_indicator`**

Add the cache field to `StateStoreImpl` (`pg.rs:344-352`), directly mirroring `last_reconciliation`'s existing shape and doc-comment rationale:
```rust
pub struct StateStoreImpl {
    pool: PgPool,
    metrics: Arc<dyn Metrics>,
    last_reconciliation: Mutex<Option<ReconciliationReport>>,
    /// `current_indicator`'s cache, keyed by `(pair, name)`,
    /// process-lifetime only. Write-through (`record_indicator` refreshes
    /// the entry once its INSERT commits, so the ingesting process never
    /// serves a reading older than the last one it wrote) and
    /// read-through (a miss, or an entry past its own `expires_at`,
    /// falls back to the query). Entries also age out on their own
    /// `expires_at`, so a value is never served past the validity window
    /// its row declared even in a process that only reads. A plain
    /// `Mutex`, not `tokio::sync::Mutex`, for the same reason as
    /// `last_reconciliation`: the lock is only ever held across a
    /// synchronous get/clone/insert, never across an `.await`.
    indicator_cache: Mutex<HashMap<(String, String), IndicatorReading>>,
}
```
and initialize it as `indicator_cache: Mutex::new(HashMap::new())` in `StateStoreImpl::connect`'s `Ok(Self { ... })` (`pg.rs:381+`). `HashMap` is already imported at the top of this file (`pg.rs:40`).

Alongside `impl SignalSink for StateStoreImpl`, mirroring `record_signal`'s single-statement shape (`pg.rs:882-910`):
```rust
#[async_trait]
impl IndicatorSink for StateStoreImpl {
    async fn record_indicator(&self, pair: Pair, reading: &IndicatorReading) -> Result<(), StoreError> {
        let dto = IndicatorReadingDto::from(reading);
        sqlx::query(
            "INSERT INTO indicators (pair, name, value, kind, volume, expires_at, received_at) \
             VALUES ($1, $2, $3, $4, $5, $6, $7)",
        )
        .bind(&pair.0)
        .bind(&dto.name)
        .bind(dto.value)
        .bind(dto.kind)
        .bind(dto.volume)
        .bind(ts_to_i64(reading.expires_at))
        .bind(ts_to_i64(exchange_adapter::Ts(exchange_adapter::now_ms())))
        .execute(&self.pool)
        .await?;

        // Write-through: only after the INSERT commits, so a failed write
        // never leaves the cache asserting something that isn't persisted.
        self.indicator_cache
            .lock()
            .unwrap()
            .insert((pair.0, reading.name.clone()), reading.clone());
        Ok(())
    }
}
```
Alongside `current_analysis` (`pg.rs:675`), on the same struct/impl block (same `&self.pool` access, same row-mapping style):
```rust
pub async fn current_indicator(&self, pair: Pair, name: &str, now: Ts) -> Result<Option<IndicatorReading>, StoreError> {
    let key = (pair.0.clone(), name.to_string());

    // Cache hit, still inside the cached row's own validity window.
    if let Some(cached) = self.indicator_cache.lock().unwrap().get(&key) {
        if now.0 < cached.expires_at.0 {
            return Ok(Some(cached.clone()));
        }
    }

    let row: Option<(Decimal, String, Option<Decimal>, i64)> = sqlx::query_as(
        "SELECT value, kind, volume, expires_at FROM indicators \
         WHERE pair = $1 AND name = $2 AND expires_at > $3 \
         ORDER BY received_at DESC LIMIT 1",
    )
    .bind(&pair.0)
    .bind(name)
    .bind(ts_to_i64(now))
    .fetch_optional(&self.pool)
    .await?;

    let reading = row.map(|(value, kind, volume, expires_at)| {
        let kind = match (kind.as_str(), volume) {
            ("support", Some(v)) => IndicatorKind::Support { volume: v },
            ("resistance", Some(v)) => IndicatorKind::Resistance { volume: v },
            _ => IndicatorKind::None,
        };
        IndicatorReading { name: name.to_string(), value, kind, expires_at: Ts(expires_at as u64) }
    });

    let mut cache = self.indicator_cache.lock().unwrap();
    match &reading {
        Some(r) => { cache.insert(key, r.clone()); }
        None => { cache.remove(&key); }
    }
    Ok(reading)
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cargo test -p state_store -- --nocapture`
Expected: PASS, all 8 new tests plus every pre-existing `state_store` test still green.

- [ ] **Step 8: Docker-verify the whole L5 slice**

Run: `docker compose run --rm test` (from `trade_executor/.worktrees/layer-implementation`)
Expected: full `cargo test --workspace` green, including the new migration and all 8 new `state_store` tests.

- [ ] **Step 9: Commit**

```bash
git add migrations/0007_indicators.sql crates/db_schema/src/lib.rs crates/state_store/src/lib.rs crates/state_store/src/dto.rs crates/state_store/src/pg.rs
git commit -m "feat(state_store): persist indicator_update readings + current_indicator query, SCHEMA_VERSION 7"
```

---

## Task 4: Orchestrator wiring — ingest `indicator_update` into `state_store` (L9)

`mq_gateway::drive()` is deliberately **not** touched by this task — `drive()` only wires `DecisionInbound`/`StateOutbound`/`ExecutionEngine` together (per its own doc comment: "the 'Consumers' relationship L4's spec describes"), and the existing precedent for persisting something L4 delivers (signals, wall observations) is a *separate* task spawned directly in `orchestrator/src/system.rs`, not a fourth arm inside `drive()` — see `run_wall_snapshot_task`/`record_signal_without_decision`, neither of which lives in `drive.rs` either. Indicator ingestion follows that same precedent.

**Files:**
- Create: `crates/orchestrator/src/indicators.rs`
- Modify: `crates/orchestrator/src/system.rs` (spawn the new task; add `mod indicators;`)

**Interfaces:**
- Consumes: `mq_gateway::{IndicatorInbound, IndicatorKind, IndicatorUpdate}` (Tasks 1-2), `state_store::{IndicatorSink, IndicatorReading, IndicatorKind as StoreIndicatorKind}` (Task 3).
- Produces:
  ```rust
  pub async fn run_indicator_ingest_task(
      inbound: Arc<dyn mq_gateway::IndicatorInbound>,
      sink: Arc<dyn state_store::IndicatorSink + Send + Sync>,
      alerts: Arc<dyn Alerts>,
      shutdown: tokio::sync::watch::Receiver<bool>,
  );
  ```
  Spawned once per process (mirroring `mq_gateway::drive`'s own single spawn at `system.rs:356` — indicators aren't per-pair-loop scoped, each message already carries its own `pair`), not per-pair like `run_wall_snapshot_task`.

- [ ] **Step 1: Write the failing test**

Create `crates/orchestrator/src/indicators.rs`:
```rust
//! Ingests `indicator_update` off `mq_gateway`'s inbound stream straight
//! into `state_store` -- per specs/2026-09-19-level-broadcast-design.md
//! §3, Postgres is the only store; this task has no cache of its own and
//! performs no mapping beyond translating mq_gateway's wire-level
//! IndicatorKind into state_store's own.

use std::sync::Arc;

use futures_util::StreamExt;
use mq_gateway::{IndicatorInbound, IndicatorKind as WireIndicatorKind};
use state_store::{IndicatorKind, IndicatorReading, IndicatorSink};

pub async fn run_indicator_ingest_task(
    inbound: Arc<dyn IndicatorInbound>,
    sink: Arc<dyn IndicatorSink + Send + Sync>,
    mut shutdown: tokio::sync::watch::Receiver<bool>,
) {
    let mut indicators = inbound.subscribe_indicators();
    loop {
        let next = tokio::select! {
            next = indicators.next() => next,
            result = shutdown.changed() => {
                if result.is_err() || *shutdown.borrow() { break; }
                continue;
            }
        };
        let Some((_id, upd)) = next else { break };
        let reading = IndicatorReading {
            name: upd.name.clone(),
            value: upd.value,
            kind: match upd.kind {
                WireIndicatorKind::Support { volume } => IndicatorKind::Support { volume },
                WireIndicatorKind::Resistance { volume } => IndicatorKind::Resistance { volume },
                WireIndicatorKind::None => IndicatorKind::None,
            },
            expires_at: exchange_adapter::Ts(upd.expires_at.timestamp_millis() as u64),
        };
        // Persist failures are alerted, never swallowed -- matching
        // run_wall_snapshot_task (system.rs:684) and
        // record_signal_without_decision (system.rs:709), the two closest
        // sibling tasks in this crate. `mq_gateway::drive`'s `let _ =` is
        // recorded tech debt, not a pattern to copy.
        if let Err(e) = sink.record_indicator(pair.clone(), &reading).await {
            alerts.fire(AlertEvent::new(
                AlertKind::PersistFailed,
                Severity::Warn,
                format!("indicator persist for {pair}/{name} failed: {e}"),
            ));
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Mutex;

    use async_trait::async_trait;
    use execution::Pair;
    use mq_gateway::{InMemoryTransport, MqGateway, MqGatewayConfig, Transport};

    use super::*;

    struct FakeIndicatorSink {
        recorded: Mutex<Vec<(Pair, IndicatorReading)>>,
    }
    impl FakeIndicatorSink {
        fn new() -> Arc<Self> {
            Arc::new(Self { recorded: Mutex::new(vec![]) })
        }
    }
    #[async_trait]
    impl IndicatorSink for FakeIndicatorSink {
        async fn record_indicator(&self, pair: Pair, reading: &IndicatorReading) -> Result<(), state_store::StoreError> {
            self.recorded.lock().unwrap().push((pair, reading.clone()));
            Ok(())
        }
    }

    #[tokio::test]
    async fn a_posted_indicator_reaches_the_sink() {
        let transport = Arc::new(InMemoryTransport::new());
        let gateway = Arc::new(
            MqGateway::new(MqGatewayConfig { inbound_topic: "in".into(), outbound_topic: "out".into() }, transport.clone()).unwrap(),
        );
        let sink = FakeIndicatorSink::new();
        let (_shutdown_tx, shutdown_rx) = tokio::sync::watch::channel(false);
        let _task = tokio::spawn(run_indicator_ingest_task(gateway.clone(), sink.clone(), shutdown_rx));
        tokio::task::yield_now().await;

        transport.send(
            "in",
            br#"{"id":"i1","type":"indicator_update","pair":"BTCUSDT","name":"15_ema_7","value":1.0,"kind":"none","expires_at":"2099-01-01T00:00:00Z"}"#.to_vec(),
        ).unwrap();

        tokio::time::sleep(std::time::Duration::from_millis(50)).await;
        let recorded = sink.recorded.lock().unwrap();
        assert_eq!(recorded.len(), 1, "sink must receive the indicator");
        assert_eq!(recorded[0].1.name, "15_ema_7");
    }

    #[tokio::test]
    async fn shutdown_signal_stops_the_task_promptly() {
        let transport = Arc::new(InMemoryTransport::new());
        let gateway = Arc::new(
            MqGateway::new(MqGatewayConfig { inbound_topic: "in".into(), outbound_topic: "out".into() }, transport).unwrap(),
        );
        let sink = FakeIndicatorSink::new();
        let (shutdown_tx, shutdown_rx) = tokio::sync::watch::channel(false);
        let task = tokio::spawn(run_indicator_ingest_task(gateway, sink, shutdown_rx));

        tokio::task::yield_now().await;
        shutdown_tx.send(true).unwrap();

        let result = tokio::time::timeout(std::time::Duration::from_secs(2), task).await;
        assert!(result.is_ok(), "task must exit promptly once shutdown is signaled");
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cargo test -p orchestrator indicators:: -- --nocapture`
Expected: FAIL to compile — `mod indicators;` not wired into `orchestrator`'s `lib.rs`/`main.rs` yet.

- [ ] **Step 3: Wire the module and spawn the task**

Add `mod indicators;` (with `pub use indicators::run_indicator_ingest_task;` if this crate re-exports its internal task functions the way it does elsewhere — check an existing one like `run_wall_snapshot_task`'s own visibility for the pattern to match) to wherever `crates/orchestrator/src/system.rs`'s sibling modules are declared.

In `crates/orchestrator/src/system.rs`, alongside the existing `drive(...)` spawn (`system.rs:350-357`), add one more `task_handles.push(...)`:
```rust
    {
        let mq_gateway_c: Arc<dyn mq_gateway::IndicatorInbound> = mq_gateway.clone();
        let indicator_sink: Arc<dyn state_store::IndicatorSink + Send + Sync> = state_store.clone();
        let shutdown_d = shutdown_rx.clone();
        task_handles.push(spawn_supervised(
            alerts.clone(),
            "indicator_ingest".to_string(),
            async move { indicators::run_indicator_ingest_task(mq_gateway_c, indicator_sink, shutdown_d).await },
        ));
    }
```
(placed once, not inside the per-pair `for pair in &pairs` loop, since indicator messages already carry their own `pair` field — same reasoning as `drive()`'s own single spawn just above it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cargo test -p orchestrator indicators:: -- --nocapture`
Expected: PASS, both tests.

- [ ] **Step 5: Docker-verify**

Run: `docker compose run --rm test`
Expected: full workspace green.

- [ ] **Step 6: Commit**

```bash
git add crates/orchestrator/src/indicators.rs crates/orchestrator/src/system.rs
git commit -m "feat(orchestrator): ingest indicator_update into state_store, no in-process cache"
```

---

## Task 5: Final executor-side Docker verification

- [ ] **Step 1:** From `trade_executor/.worktrees/layer-implementation`, run `docker compose run --rm test`.
- [ ] **Step 2:** Confirm output shows `cargo test --workspace` passing for every crate touched: `mq_gateway`, `local_analysis`, `state_store`, `db_schema`, `orchestrator`.
- [ ] **Step 3:** If `visualizer_server`'s `check_schema` has its own test asserting `SCHEMA_VERSION`, confirm it's still green (it should be, since Task 3 bumped the constant in the same commit as the migration).

No commit for this task — it's a verification checkpoint only. If anything is red, return to the relevant task above; do not proceed to Task 6 until this is fully green.

---

## Task 6: `main/` allowlist config

**Files:**
- Create: `main/configs/shared_indicators_config.yaml`
- Modify: `main/config_loader.py`
- Test: `main/tests/test_shared_indicators_config.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class SharedIndicatorConfig:
      name: str
      timeframes: list[int]

  def load_shared_indicators_config(path: str = "configs/shared_indicators_config.yaml") -> list[SharedIndicatorConfig]: ...
  ```

- [ ] **Step 0: Confirm the Docker test command**

Run: `docker compose run --rm live pytest tests/ -v --ignore=tests/nn` (from `main/`)
Expected (confirmed 2026-09-20): the suite runs and reports **2081 passed, 21 failed, 2 skipped**. Those 21 failures are the pre-existing baseline documented under Docker Entry Points (trainer + chart-renderer + label-marker tests) and are not this plan's concern. Dropping `--ignore=tests/nn` instead produces `Interrupted: 2 errors during collection` (missing `optuna`) and runs nothing at all — that is a broken command, not a broken branch.

- [ ] **Step 1: Write the failing test**

Create `main/tests/test_shared_indicators_config.py`:
```python
from config_loader import load_shared_indicators_config


def test_loads_the_configured_allowlist(tmp_path):
    config_file = tmp_path / "shared_indicators_config.yaml"
    config_file.write_text(
        "indicators:\n"
        "  - name: ema_7\n"
        "    timeframes: [15, 60, 240]\n"
        "  - name: ema_14\n"
        "    timeframes: [15, 60, 240]\n"
    )
    result = load_shared_indicators_config(path=str(config_file))
    assert len(result) == 2
    assert result[0].name == "ema_7"
    assert result[0].timeframes == [15, 60, 240]


def test_empty_indicators_list_returns_empty(tmp_path):
    config_file = tmp_path / "empty.yaml"
    config_file.write_text("indicators: []\n")
    assert load_shared_indicators_config(path=str(config_file)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm live pytest tests/test_shared_indicators_config.py -v` (or the fallback command from Step 0)
Expected: FAIL — `load_shared_indicators_config` doesn't exist yet.

- [ ] **Step 3: Implement**

In `main/config_loader.py`, add alongside `load_indicators_config` (following its exact `open()`/`yaml.safe_load()` idiom):
```python
from dataclasses import dataclass


@dataclass
class SharedIndicatorConfig:
    name: str
    timeframes: list[int]


def load_shared_indicators_config(path: str = "configs/shared_indicators_config.yaml") -> list[SharedIndicatorConfig]:
    """Returns the operator-configured allowlist of (name, timeframes) to publish to trade_executor.

    Unlike load_indicators_config, this is not topologically sorted or
    merged with any computation config — it's a pure allowlist naming
    which already-computed fields get broadcast.
    """
    with open(path, "r") as fh:
        data = yaml.safe_load(fh)
    raw = data.get("indicators", [])
    return [SharedIndicatorConfig(name=entry["name"], timeframes=list(entry["timeframes"])) for entry in raw]
```
(`yaml` is already imported at the top of `config_loader.py` for the other loaders — no new import needed.)

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm live pytest tests/test_shared_indicators_config.py -v`
Expected: PASS, both tests.

- [ ] **Step 5: Create the real config file**

Create `main/configs/shared_indicators_config.yaml`:
```yaml
indicators:
  - name: ema_7
    timeframes: [15, 60, 240]
  - name: ema_14
    timeframes: [15, 60, 240]
  - name: ema_25
    timeframes: [15, 60, 240]
```

- [ ] **Step 6: Commit**

```bash
cd main
git add config_loader.py configs/shared_indicators_config.yaml tests/test_shared_indicators_config.py
git commit -m "feat(config): add shared_indicators_config allowlist for indicator broadcast"
```

---

## Task 7: `main/mq/` — indicator wire-JSON builder (pure, unit-testable)

**Files:**
- Create: `main/mq/__init__.py`
- Create: `main/mq/indicator_publisher.py`
- Test: `main/tests/test_indicator_publisher.py`

**Interfaces:**
- Consumes: `SharedIndicatorConfig` (Task 6).
- Produces:
  ```python
  def build_indicator_update(
      pair: str, name: str, value: float, now: datetime, ttl_seconds: float
  ) -> dict: ...

  class IndicatorPublisher:
      def __init__(self, connect_addr: str, ttl_seconds: float = 300.0) -> None: ...
      def publish(self, pair: str, name: str, value: float) -> None: ...
      def close(self) -> None: ...
  ```
  `build_indicator_update` is the pure, fully unit-testable piece (JSON shape, fresh uuid, `expires_at` heartbeat math) — `IndicatorPublisher` wraps it with the actual zmq PUSH socket, exercised separately in Task 8's integration test.

- [ ] **Step 1: Write the failing tests for the pure JSON builder**

Create `main/tests/test_indicator_publisher.py`:
```python
import uuid
from datetime import datetime, timezone, timedelta

from mq.indicator_publisher import build_indicator_update


def test_builds_a_none_kind_indicator_update():
    now = datetime(2026, 9, 20, 0, 0, 0, tzinfo=timezone.utc)
    msg = build_indicator_update(pair="BTCUSDT", name="15_ema_7", value=12345.0, now=now, ttl_seconds=30.0)

    assert msg["type"] == "indicator_update"
    assert msg["pair"] == "BTCUSDT"
    assert msg["name"] == "15_ema_7"
    assert msg["value"] == 12345.0
    assert msg["kind"] == "none"
    assert "volume" not in msg
    assert msg["expires_at"] == "2026-09-20T00:00:30+00:00"
    uuid.UUID(msg["id"])  # raises ValueError if not a valid uuid


def test_each_call_gets_a_fresh_id():
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    a = build_indicator_update(pair="BTCUSDT", name="x", value=1.0, now=now, ttl_seconds=30.0)
    b = build_indicator_update(pair="BTCUSDT", name="x", value=1.0, now=now, ttl_seconds=30.0)
    assert a["id"] != b["id"]
    # "differ in id ONLY" is the actual contract -- pin the rest too.
    assert {k: v for k, v in a.items() if k != "id"} == {k: v for k, v in b.items() if k != "id"}


def test_expires_at_is_now_plus_ttl():
    now = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
    msg = build_indicator_update(pair="BTCUSDT", name="x", value=1.0, now=now, ttl_seconds=120.0)
    # A pinned literal, NOT `(now + timedelta(...)).isoformat()` -- recomputing the
    # implementation's own expression only proves the code matches itself.
    assert msg["expires_at"] == "2026-09-20T12:02:00+00:00"


def test_a_naive_now_is_rejected():
    """`.isoformat()` on a naive datetime omits the UTC offset, and the executor
    parses expires_at with chrono's parse_from_rfc3339, which requires one --
    so every message would be rejected across the repo boundary."""
    with pytest.raises(ValueError):
        build_indicator_update(
            pair="BTCUSDT", name="x", value=1.0,
            now=datetime(2026, 9, 20, 12, 0, 0), ttl_seconds=120.0,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm live pytest tests/test_indicator_publisher.py -v`
Expected: FAIL — `mq` module doesn't exist yet.

- [ ] **Step 3: Implement**

Create `main/mq/__init__.py` (empty — marks the package).

Create `main/mq/indicator_publisher.py`:
```python
# indicator_publisher.py — builds indicator_update wire JSON and PUSHes it to trade_executor.

from __future__ import annotations

import uuid
from datetime import datetime, timedelta


def build_indicator_update(pair: str, name: str, value: float, now: datetime, ttl_seconds: float) -> dict:
    """Build one indicator_update wire message, kind: none (v1 scope — no support/resistance/volume yet).

    Args:
        pair: e.g. "BTCUSDT".
        name: stable indicator identifier, e.g. "15_ema_7" (matches main/indicators/'s own {tf}_{name} column naming).
        value: the indicator's current reading.
        now: current time; expires_at is computed from this, not read from any indicator metadata.
        ttl_seconds: how far past `now` this reading stays valid — must comfortably exceed one tick interval.

    Raises:
        ValueError: if `now` is naive. A naive datetime serializes without a
            UTC offset, which the executor's RFC3339 parser rejects.

    Returns:
        dict ready for json.dumps and PUSH — kind is always "none" in this v1 builder.
    """
    return {
        "id": str(uuid.uuid4()),
        "type": "indicator_update",
        "pair": pair,
        "name": name,
        "value": value,
        "kind": "none",
        "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm live pytest tests/test_indicator_publisher.py -v`
Expected: PASS, all 3 tests.

- [ ] **Step 5: Commit**

```bash
git add mq/__init__.py mq/indicator_publisher.py tests/test_indicator_publisher.py
git commit -m "feat(mq): add build_indicator_update, the pure indicator_update wire builder"
```

---

## Task 8: `main/mq/` — zmq PUSH client + requirements

**Files:**
- Modify: `main/mq/indicator_publisher.py`
- Modify: `main/requirements.txt`
- Test: `main/tests/test_indicator_publisher.py` (extend)

**Interfaces:**
- Consumes: `build_indicator_update` (Task 7), `pyzmq`.
- Produces:
  ```python
  class IndicatorPublisher:
      def __init__(self, connect_addr: str, ttl_seconds: float = 300.0) -> None: ...
      def publish(self, pair: str, name: str, value: float) -> None: ...   # best-effort: never blocks, never raises
      def close(self) -> None: ...

      dropped: int   # publishes discarded because no peer was reachable
  ```

**`publish` must never block and never raise — the task's load-bearing constraint, not a nicety.** It is called inline from `Robot.do()`'s tick loop (Task 9), so a stall inside it stalls strategy evaluation, order placement and stop-loss checks. A ZMQ PUSH socket with *no connected peer* enters mute state, where a default blocking `send` waits **forever** rather than erroring — so a `trade_executor` that is down, restarting, or not deployed yet would freeze live trading through a pure-telemetry path. `connect()` gives no warning of this: it is asynchronous and succeeds immediately against an address nothing is listening on. Hence Step 4's socket options — `SNDTIMEO=0` plus `NOBLOCK` (drop rather than wait), `IMMEDIATE=1` (never queue for a peer that has never connected), `LINGER=0` (never block process exit on an unsent backlog), and a bounded `SNDHWM` so a long outage cannot grow memory without limit.

**Reconnection is libzmq's job, not the caller's.** A PUSH socket whose peer is absent or has died keeps retrying the TCP connect from libzmq's own IO thread, indefinitely — so `IndicatorPublisher` must *not* call `connect()` again on failure (a second `connect()` adds a second endpoint to the same socket, it does not repair the first, and leaves the socket round-robining onto a phantom peer). What the class does own is the retry cadence: `RECONNECT_IVL=100` ms for a fast recovery from a brief executor restart, capped by `RECONNECT_IVL_MAX=5` s so libzmq backs off exponentially instead of hammering a host that is down for hours. Recovery is therefore automatic and silent: publishes are counted as `dropped` for as long as no peer is reachable, and the first tick after the executor returns delivers normally with no intervention and no publisher rebuild.

Dropping is safe *because* of the heartbeat design (spec §107): every reading is republished each tick with a fresh 300 s `expires_at`, so a dropped message costs at most one tick of freshness, and a prolonged outage correctly ages indicators out of `current_indicator` rather than feeding the executor stale values.

- [ ] **Step 1: Add the dependency**

In `main/requirements.txt`, add a new line (matching the file's existing `name==version` style):
```
pyzmq==26.4.0
```

- [ ] **Step 2: Write the failing integration test (real PULL socket, mirrors `zmq_transport.rs`'s own test precedent)**

Add to `main/tests/test_indicator_publisher.py`:
```python
import json
import time

import zmq

from mq.indicator_publisher import IndicatorPublisher


def test_publish_reaches_a_real_pull_socket():
    ctx = zmq.Context.instance()
    pull = ctx.socket(zmq.PULL)
    port = pull.bind_to_random_port("tcp://127.0.0.1")
    try:
        publisher = IndicatorPublisher(connect_addr=f"tcp://127.0.0.1:{port}", ttl_seconds=30.0)
        try:
            # connect() is asynchronous and the socket drops rather than queues
            # (IMMEDIATE=1), so the first publish can legitimately land before
            # the pipe is up. Retry the way the real per-tick heartbeat does,
            # instead of asserting on a single shot.
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                publisher.publish(pair="BTCUSDT", name="15_ema_7", value=42.0)
                if pull.poll(timeout=200):
                    break
            else:
                raise AssertionError("no message arrived within 5s of repeated publishes")
            raw = pull.recv()
            msg = json.loads(raw)
            assert msg["pair"] == "BTCUSDT"
            assert msg["name"] == "15_ema_7"
            assert msg["value"] == 42.0
            assert msg["kind"] == "none"
        finally:
            publisher.close()
    finally:
        pull.close()


def test_publish_to_a_dead_address_returns_promptly_and_counts_the_drop():
    """The executor being down must never stall main/'s tick loop.

    Port 1 has nothing listening; connect() still succeeds (it is
    asynchronous), so this is exactly the "executor not running" case.
    A blocking PUSH send would hang here forever.
    """
    publisher = IndicatorPublisher(connect_addr="tcp://127.0.0.1:1", ttl_seconds=30.0)
    try:
        started = time.monotonic()
        for _ in range(100):
            publisher.publish(pair="BTCUSDT", name="15_ema_7", value=42.0)
        elapsed = time.monotonic() - started
        assert elapsed < 1.0, f"100 publishes to a dead peer took {elapsed:.2f}s -- publish is blocking"
        assert publisher.dropped == 100
    finally:
        publisher.close()


def test_publishing_resumes_after_the_executor_comes_back():
    """An executor restart must heal itself -- no publisher rebuild, no manual reconnect.

    libzmq retries the connect from its own IO thread; this test pins that
    behaviour so a future "add a reconnect loop" change can't quietly replace
    it with something worse.
    """
    ctx = zmq.Context.instance()
    pull = ctx.socket(zmq.PULL)
    port = pull.bind_to_random_port("tcp://127.0.0.1")
    publisher = IndicatorPublisher(connect_addr=f"tcp://127.0.0.1:{port}", ttl_seconds=30.0)

    def publish_until_delivered(sock, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            publisher.publish(pair="BTCUSDT", name="15_ema_7", value=42.0)
            if sock.poll(timeout=200):
                return sock.recv()
        raise AssertionError("nothing delivered within the timeout")

    try:
        publish_until_delivered(pull)

        # Executor goes away. Publishing must stay fast and lossy, not block.
        pull.close()
        started = time.monotonic()
        for _ in range(50):
            publisher.publish(pair="BTCUSDT", name="15_ema_7", value=42.0)
        assert time.monotonic() - started < 1.0, "publish blocked while the peer was gone"

        # Executor comes back on the same address; delivery resumes by itself.
        pull = ctx.socket(zmq.PULL)
        pull.bind(f"tcp://127.0.0.1:{port}")
        raw = publish_until_delivered(pull)
        assert json.loads(raw)["name"] == "15_ema_7"
    finally:
        publisher.close()
        pull.close()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `docker compose run --rm live pytest tests/test_indicator_publisher.py::test_publish_reaches_a_real_pull_socket -v`
Expected: FAIL — `IndicatorPublisher` doesn't exist yet. (If `pyzmq` isn't installed in the running container yet because the image wasn't rebuilt, rebuild first: `docker compose build live`.)

- [ ] **Step 4: Implement `IndicatorPublisher`**

Extend `main/mq/indicator_publisher.py`:
```python
import logging

import zmq
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class IndicatorPublisher:
    """PUSH client onto trade_executor's inbound MQ socket, publishing indicator_update messages only (v1 scope)."""

    def __init__(self, connect_addr: str, ttl_seconds: float = 300.0) -> None:
        self._ttl_seconds = ttl_seconds
        self.dropped = 0
        self._ctx = zmq.Context.instance()
        self._socket = self._ctx.socket(zmq.PUSH)
        # A PUSH socket with no peer blocks forever on send by default, and
        # connect() succeeds even when nothing is listening -- these four
        # options are what keep a down executor from freezing the tick loop.
        self._socket.setsockopt(zmq.SNDTIMEO, 0)   # never wait for a peer
        self._socket.setsockopt(zmq.IMMEDIATE, 1)  # never queue for a peer that never connected
        self._socket.setsockopt(zmq.LINGER, 0)     # never block process exit on unsent messages
        self._socket.setsockopt(zmq.SNDHWM, 100)   # bounded backlog; drop past it
        # libzmq reconnects on its own, forever -- these only set the cadence.
        # Never call connect() a second time to "retry": it adds an endpoint
        # rather than repairing the existing one.
        self._socket.setsockopt(zmq.RECONNECT_IVL, 100)       # first retry after 100ms
        self._socket.setsockopt(zmq.RECONNECT_IVL_MAX, 5000)  # exponential backoff, capped at 5s
        self._socket.connect(connect_addr)

    def publish(self, pair: str, name: str, value: float) -> None:
        """Best-effort. Never blocks, never raises: an unreachable executor
        costs one tick of freshness, and the next tick republishes anyway."""
        msg = build_indicator_update(pair=pair, name=name, value=value, now=datetime.now(timezone.utc), ttl_seconds=self._ttl_seconds)
        try:
            self._socket.send_json(msg, flags=zmq.NOBLOCK)
        except zmq.Again:
            self.dropped += 1
        except zmq.ZMQError as e:
            self.dropped += 1
            logger.warning("indicator publish failed: %s", e)

    def close(self) -> None:
        self._socket.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose run --rm live pytest tests/test_indicator_publisher.py -v`
Expected: PASS, all 6 tests (3 from Task 7 + the three above). The dead-address test is the one that matters most: if `publish` is ever made blocking again it hangs rather than fails, so treat a timeout there as a real regression, not a slow test.

- [ ] **Step 6: Commit**

```bash
git add mq/indicator_publisher.py requirements.txt tests/test_indicator_publisher.py
git commit -m "feat(mq): add IndicatorPublisher zmq PUSH client"
```

---

## Task 9: Wire the publisher into the live tick loop

**Files:**
- Modify: `main/robots/robot.py`
- Test: `main/tests/test_robot.py` (extend — check this file's existing fixtures/mocking style for `Robot` before writing new tests, since it already has precedent for testing `Robot.do()`'s per-tick behavior)

**Interfaces:**
- Consumes: `IndicatorPublisher.publish` (Task 8), `SharedIndicatorConfig`/`load_shared_indicators_config` (Task 6), `DataPoint.get(name, tf)` (existing, `data.py:22-29`/`77-92`).

- [ ] **Step 1: Write the failing test**

Add to `main/tests/test_robot.py` (match whatever fixture the file already uses to construct a `Robot` with a fake `data_point`/`strategy_manager` — read the file first to copy the exact pattern; the sketch below assumes a `data_point` test double with a `.get(name, tf)` method, matching `DataPoint`'s real contract):
```python
def test_do_publishes_configured_indicators_every_tick(robot_with_fake_data_point, fake_indicator_publisher):
    # robot_with_fake_data_point's data_point.get("ema_7", 15) already returns a known value via the fixture.
    robot_with_fake_data_point.do()
    published = fake_indicator_publisher.published  # list of (pair, name, value) tuples the fake recorded
    assert ("BTCUSDT", "15_ema_7", pytest_approx_value) in published
```
(Adjust fixture names/assertion to whatever `test_robot.py`'s actual `Robot` construction fixture is called — this step's real deliverable is: one test proving that after `Robot.do()` runs, every `(name, tf)` pair in the allowlist has been published with the value read from `data_point.get(f"{name}", tf)`. Write it against the real fixture names once Step 0 of reading the file is done.)

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm live pytest tests/test_robot.py -k publishes_configured_indicators -v`
Expected: FAIL — `Robot.do()` doesn't publish anything yet.

- [ ] **Step 3: Implement**

In `main/robots/robot.py`, `Robot.__init__` gains an `indicator_publisher: IndicatorPublisher | None = None` constructor parameter (defaulting to `None` so existing callers/tests that don't care about this feature don't break) and loads `self._shared_indicators = load_shared_indicators_config()` once at construction. In `Robot.do()`, immediately after `data_point = self.live_data.get_data_point()` (`robot.py:127`), add:
```python
        if self.indicator_publisher is not None:
            for cfg in self._shared_indicators:
                for tf in cfg.timeframes:
                    value = data_point.get(cfg.name, tf)
                    self.indicator_publisher.publish(pair=self.pair, name=f"{tf}_{cfg.name}", value=value)
```
(`self.pair` — confirm the exact existing attribute name `Robot` already uses for its trading pair string; match it rather than inventing a new one.)

The publish call itself is already safe to make inline — Task 8's `publish` never blocks and never raises even with no executor listening. What is *not* yet guarded here is `data_point.get(cfg.name, tf)`: confirm what it does for an allowlisted indicator that is missing or not yet warmed up, and if it can raise, wrap this loop so a telemetry read can never abort `Robot.do()` before the trading logic below it runs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm live pytest tests/test_robot.py -v`
Expected: PASS — the new test, and every pre-existing `test_robot.py` test still green (since `indicator_publisher` defaults to `None` and is a no-op when absent).

- [ ] **Step 5: Wire construction in `trader.py`/wherever `Robot` is actually instantiated for live trading**

Find the real construction call site (likely `main/trader.py`, per the earlier audit's `main/trader.py:69-84` `main()`) and pass a real `IndicatorPublisher(connect_addr=<executor host:5555 from config/env>, ttl_seconds=300.0)`. Read that call site first to match its existing config/env-var conventions for where the executor host/port would come from (a new env var, e.g. `MQ_EXECUTOR_ADDR`, following whatever pattern `configs/live.env` already uses for other addresses/credentials) before hardcoding anything.

- [ ] **Step 6: Docker-verify**

Run: `docker compose run --rm live pytest tests/ -v --ignore=tests/nn`
Expected: **no new failures beyond the 21-failure baseline** from Docker Entry Points, and every test this plan added passing. "Full suite green" is unreachable on this repo and is not the bar — compare against the baseline instead. To check this plan's own tests in isolation: `docker compose run --rm live pytest tests/test_shared_indicators_config.py tests/test_indicator_publisher.py tests/test_robot.py -v` (65 tests, all passing as of 2026-09-20).

- [ ] **Step 7: Commit**

```bash
git add robots/robot.py trader.py  # plus whatever env/config file Step 5 touched
git commit -m "feat(robot): publish allowlisted indicators to trade_executor every tick"
```

---

## Self-Review Notes (already applied above)

- **Spec coverage:** §2 wire schema -> Task 1. §2.1 gateway plumbing -> Task 2. §3 persistence + `current_indicator` query (single `indicators` table, write-through/read-through cache keyed by each reading's own `expires_at`) -> Task 3, ingestion wired end-to-end in Task 4. §4 main/ sender (allowlist, `kind: none` only, heartbeat `expires_at`) -> Tasks 6-9. §4.1 (support/resistance deferred) -> deliberately no task here, matching the spec's explicit deferral. §5 out-of-scope items -> confirmed absent from every task above (no `combined_levels` change, no decision-publishing, no `levels.py`, no in-process `IndicatorStore`). §6 testing notes -> covered by Tasks 1, 3, 7-9's test steps.
- **Placeholder scan:** every step above has runnable code, not a description of code; `docker compose run --rm live pytest ...` was flagged as an inferred command needing Task 6 Step 0 confirmation; that confirmation has since happened (2026-09-20) and the command, its mandatory `--ignore=tests/nn`, and the 21-failure pre-existing baseline are now recorded under Docker Entry Points.
- **Type consistency:** `IndicatorKind` (wire.rs, Task 1) -> `state_store::IndicatorKind` (Task 3) is a two-name chain by design (each crate's own vocabulary, per the workspace's existing `LevelKindDto`/`execution::LevelKind` precedent) — Task 4's `crates/orchestrator/src/indicators.rs` is where that mapping actually happens, spelled out in full rather than left implicit. No third name/layer exists — `local_analysis` never sees this data at all, per the pivot away from an in-process store.
