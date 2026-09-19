# Standalone Indicator Broadcast (main/ → executor) — Design Spec

Date: 2026-09-19
Status: approved for planning
Target projects: `main/` (Python, sender — new) and `trade_executor` (Rust, receiver — extends L4/L2/L5)
Extends: [specs/layers/L4-mq-gateway.md](layers/L4-mq-gateway.md) (wire contract), `crates/local_analysis` (indicator consumption), `crates/state_store` (persistence)
Scope: first sub-project of the larger main/executor integration (per `main_goal.md`, "StrategyManager publishes trade decisions ... over a message queue"). This spec covers **only** standalone indicator broadcast — named values (support/resistance levels with volume, or arbitrary other indicators) independent of any trade decision. Publishing trade decisions themselves (open/close/modify) is a separate, later spec; that flow is still 100% unbuilt on the `main/` side and out of scope here.

## 1. Indicators are the core of this integration

This integration's message is a generic **indicator**: a named value main/ publishes independently of any trade decision, classified `support | resistance | none`. Price levels (main/'s existing support/resistance concept) are included as part of this — a level is one specific case of an indicator, `kind: support` or `kind: resistance`, carrying `volume`. Anything else main/ wants to expose (an RSI reading, or any other computed value) is the other case — `kind: none`, no `volume`. Both cases share one wire message (`indicator_update`), one storage path, and one lookup interface (`IndicatorStore`, §3) — the protocol is built around "indicator" as the primary concept, with "level" as one `kind` within it, not a separate thing bolted alongside.

Concretely, the agreed message structure (kept unchanged through this revision):
- `name` + `value` + `expires_at` on every indicator, always.
- `kind: support | resistance`, each additionally carrying `volume` — the price-level case.
- `kind: none`, carrying nothing else — every other indicator.

**Why this didn't already exist**: the wire protocol's only *prior* notion of a main/-supplied level was `TradeDecisionPayload.levels` (`crates/mq_gateway/src/wire.rs:63-69`) — a list riding *inside* a trade decision, ephemeral (exists only for that one decision), no `name`, no `volume`, no independent lifecycle, and no way to represent anything that isn't a price level at all. `crates/local_analysis::Level` (`crates/local_analysis/src/types.rs:38-45`) mirrors that narrower shape: `price` / `source` (`Wall(Side) | Main`) / `kind` (`Support | Resistance | Target | StopLoss`), with no storage — `combined_levels(main_levels, walls)` (`crates/local_analysis/src/levels.rs:132`) takes `main_levels` fresh on each call, nothing persists between calls. `main/`'s existing support/resistance computation (`main/levels.py`'s `Levels` class, backed by `shared/{pair}/levels.txt`, `LI_NAME`/`LI_TYPE`/interpolated `LI_VAL1`/`LI_VAL2`, `main/constants.py:32-48`) has no decision to attach to when it just wants to announce "here is where support/resistance currently sit" — and no vocabulary at all for a non-level value like RSI. `indicator_update` (§2) replaces that gap with one generic, standalone message type. Its first concrete producer (§4) is `main/`'s general `main/indicators/` framework (an allowlisted set of technical-indicator readings, `kind: "none"`) — support/resistance-classified indicators are a deliberately later, separate producer (§4.1, source undecided), not v1's defining case.

## 2. Wire schema — new inbound message type `indicator_update`

New variant on `InboundPayload` (`crates/mq_gateway/src/wire.rs:47-52`), alongside `Open | Close | Modify | ForceClose | ForceOverride`. Follows the wire crate's actual flattening convention (`#[serde(flatten)]` over an internally-tagged enum) rather than the L4 doc's stale nested-`payload` shape; that doc/code drift is pre-existing and orthogonal to this spec, but this new type is defined to match what the code actually does today so it doesn't add a second inconsistency.

**Support/resistance indicator** (carries `volume`):
```json
{
  "id": "<uuid>",
  "type": "indicator_update",
  "pair": "BTCUSDT",
  "name": "auto_support_3",
  "value": 12345.0,
  "kind": "support",
  "volume": 3.25,
  "expires_at": "<rfc3339>"
}
```

**Non-level indicator** (`kind: "none"`, no `volume` field at all — not merely null):
```json
{
  "id": "<uuid>",
  "type": "indicator_update",
  "pair": "BTCUSDT",
  "name": "rsi_14",
  "value": 63.4,
  "kind": "none",
  "expires_at": "<rfc3339>"
}
```

Fields:
- `id` — uuid, dedup key. Reuses the existing `SharedDedup` id-space shared with decisions/force (`crates/mq_gateway/src/gateway.rs:60-74`) — a fresh id per publish (see §4 cadence), not stable per `name`.
- `pair` — string, e.g. `"BTCUSDT"`.
- `name` — string, main/'s stable identifier for this indicator (`LI_NAME` from `levels.txt` for levels; any stable string for other indicators). This is the lookup key on the executor side (§3), not `id`.
- `value` — decimal, generic. A price for support/resistance kinds (`Levels.get_level_value`, `main/levels.py:83-93`); any other numeric reading for `kind: "none"` (e.g. an RSI value on a 0–100 scale). Deliberately not named `price` since it isn't always one.
- `kind` — `IndicatorKindDto::{Support, Resistance, None}`, modeled as an **internally-tagged enum where `Support`/`Resistance` carry `volume` as part of their own variant** rather than a separate optional top-level field:
  ```rust
  #[serde(tag = "kind", rename_all = "snake_case")]
  enum IndicatorKindDto {
      Support { volume: Decimal },
      Resistance { volume: Decimal },
      None,
  }
  ```
  This makes "volume present with kind none" or "volume missing with kind support" unrepresentable at parse time, rather than accepted-then-validated — consistent with this codebase's existing style (e.g. `LevelSource::Wall(Side)` carrying its side, `force_override`'s outright rejection rather than silent coercion). Main/'s 7 `LEVEL_TYPE_*` constants collapse onto `Support`/`Resistance` (long/short/auto support → `support`, long/short/auto resistance → `resistance`; `LEVEL_TYPE_TARGET` is excluded — target levels stay decision-only, unrelated to this message).
- `expires_at` — rfc3339 absolute timestamp. Chosen over a relative TTL to avoid clock-skew ambiguity about when a duration "starts" (matches the existing outbound `ts` field's rfc3339 convention, `wire.rs:269-291`).

### 2.1 `InboundMessage` / gateway plumbing
- `wire.rs`'s `InboundMessage` enum gains `Indicator(id: String, IndicatorUpdate)` next to `Decision`/`Force`.
- `MqGateway` (`crates/mq_gateway/src/gateway.rs`) gains `subscribe_indicators() -> IndicatorStream`, structurally identical to `subscribe_decisions()`/`subscribe_force()` (`gateway.rs:95-135`) — same dedup, same inbound topic, filter-mapping on `InboundMessage::Indicator`.

## 3. Executor-side handling

Two independent consumers of the same inbound stream (confirmed: both wanted, not either/or):

**(a) Persistence (state_store, Postgres)** — new `indicators` table: `id, pair, name, value, kind, volume (nullable), expires_at, received_at`. Every incoming `indicator_update` is appended (never updated/replaced) — an audit trail of all indicators ever seen, mirroring the existing `signal_log`/`record_signal` pattern (`crates/state_store/src/pg.rs:874-911`). Feeds the visualizer for display (a plotted RSI line just as much as a support/resistance line); no behavioral role.

**(b) Live consumption (local_analysis)** — new `IndicatorStore`: append-only in memory, keyed by `(pair, name)`. Exposes both a single-entry lookup and a bulk listing:
```rust
fn latest(&self, pair: Pair, name: &str, now: Ts) -> Option<IndicatorReading>
fn valid_indicators(&self, pair: Pair, now: Ts) -> Vec<IndicatorReading>
```
`latest` returns the most-recently-received entry for that `(pair, name)` where `now < expires_at`, or `None` if the newest entry has expired. `valid_indicators` is the **new structure** this spec delivers to `local_analysis`: the full list of currently-valid (non-expired) latest-per-name readings for a pair, across *every* `kind` — support, resistance, and none alike. Expired entries are never deleted from the store, just excluded from both queries (consistent with "store all, select latest non-expired").

This list is a **new, separate input to `local_analysis`** — threaded into the per-tick evaluation alongside (not merged into) the existing `combined_levels(main_levels, walls)` (`levels.rs:132`). The existing level machinery (`combined_levels`/wall-detection/risk) is **untouched by this spec**: it keeps working exactly as it does today, fed only by decision-attached `TradeDecisionPayload.levels`. `valid_indicators()`'s output — including `support`/`resistance`-kind readings — does not feed into `combined_levels`; indicators get their own path, checked by their own (future) logic.

**Checking logic that acts on `valid_indicators()`'s output is future work, out of scope here.** This spec's job stops at making the list available at the `local_analysis` boundary (store it, assemble it, pass it in); what a future signal does when it inspects a named indicator (support/resistance-based, RSI-based, or otherwise) is a separate, later spec.

## 4. Main-side sender (new)

**Source of data (v1)**: `main/indicators/` — the existing `IndicatorField`/`Indicators` framework (`main/indicators/framework.py`), configured via `main/configs/indicators_config.yaml`, output columns `{tf}_{name}` per field per timeframe (e.g. `"15_rsi_14"`). This is main/'s general-purpose indicator computation, unrelated to `levels.py`.

**v1 always publishes `kind: "none"`.** No support/resistance classification and no `volume` in this increment — every published indicator is a plain named value. Classifying specific indicators as `support`/`resistance` (with `volume`) is a **later, separate increment**, and it is `levels.py`'s concern when it lands (§4.1) — not something v1's generic sender does.

**Which fields get published is main/-operator-configured, not auto-selected.** `main/indicators/` computes dozens of fields across groups, several of them internal-only (`targets`, `nn_features` — training artifacts, not meaningful standalone readings). v1 introduces a new allowlist config (e.g. `main/configs/shared_indicators_config.yaml`) naming exactly which `(name, tf)` pairs to broadcast; the sender publishes only what's listed there, nothing is published by default.

**Initial v1 allowlist**: `ema_7`, `ema_14`, `ema_25` (existing `trend` group fields, `indicators_config.yaml`), each at timeframes 15/60/240 — nine `(name, tf)` combinations, wire `name` values `15_ema_7`, `60_ema_7`, `240_ema_7`, `15_ema_14`, `60_ema_14`, `240_ema_14`, `15_ema_25`, `60_ema_25`, `240_ema_25`.

**`expires_at` is sender-computed, not sourced from the indicator itself** — unlike `levels.py`'s `LI_TIME2`, `IndicatorField` values carry no inherent validity window. The sender sets `expires_at = now + TTL` (a small multiple of the tick interval) on every publish, functioning as a heartbeat: republishing every tick (not only on value change) means a crashed/disconnected main/ naturally ages its indicators out of `IndicatorStore`'s non-expired set once `TTL` elapses, with no explicit cancel/retract message needed. `TTL` must comfortably exceed one tick interval so a single missed tick doesn't flap an indicator in and out of "valid."

**New module**: `main/mq/` (or similar — main has zero messaging infra today, per prior audit; nothing to extend, this is new from scratch). Responsibilities:
- ZeroMQ PUSH client, connects to `tcp://<executor-host>:5555` (executor's bound inbound port, `docker-compose.yml` in the `layer-implementation` worktree), reusing the `decisions` topic (env `MQ_INBOUND_TOPIC`) — `indicator_update` shares the inbound channel with decisions/force, distinguished by `"type"`.
- New dependency: `pyzmq` (not currently in `main/requirements.txt`).
- On each tick, for every `(name, tf)` in the allowlist config, read the computed value (`{tf}_{name}` column) and PUSH an `indicator_update` (`kind: "none"`, `name: "{tf}_{name}"`, computed `expires_at`) with a **fresh uuid `id`**.
- No outbound/PULL handling is added by this spec — this is inbound-only (main/ → executor). The existing outbound `state` topic (position events) is unrelated and still unbuilt on main/'s side (separate, later spec).

### 4.1 Deferred: support/resistance classification (later increment, not v1)

Publishing any `kind: "support"`/`"resistance"` indicator (with `volume`) is **not part of this spec's v1 sender** — v1 publishes `kind: "none"` only (§4). Which main/ module eventually produces support/resistance readings, and how it derives `volume`/`expires_at`, is undecided and left to that later increment's own design — not assumed here. Whatever that source turns out to be, it reuses the same `main/mq/` publisher and `indicator_update` wire type built in this spec.

## 5. Out of scope (explicitly deferred)

- Publishing trade decisions (`open`/`close`/`modify`/`force_close`) from `StrategyManager` — the seam is `main/strategies/strategy_manager.py:75` `check()` / `main/robots/robot.py:131` `Robot.do()`, per prior audit, but building that sender is a separate spec.
- Consuming the outbound `state` topic on main/'s side.
- Publishing any `kind: "support"`/`"resistance"` indicator from main/ — schema supports it, v1's sender only emits `kind: "none"`; source for a future support/resistance producer is undecided (§4.1).
- Wiring `valid_indicators()`'s output into any signal check — this spec delivers the list to `local_analysis`'s boundary; checking logic against it (any `kind`, including `support`/`resistance`) is a separate, later spec.
- Any change to the existing `combined_levels`/wall-detection/risk machinery — it stays fed only by decision-attached `TradeDecisionPayload.levels`, exactly as today; indicators do not feed into it.
- Resolving the pre-existing L4 doc/code envelope mismatch (nested `payload` per doc vs. flat per code) for the *existing* `open`/`close`/`modify`/`force_close` types — noted in §2 as context, not fixed here.
- Any change to `run_signal_decision_task`'s Side-mapping or execution wiring — an `indicator_update` never produces a `TradeDecision`; it only lands in `IndicatorStore`/`valid_indicators()`, inert until a future spec's checking logic consumes it.

## 6. Testing notes for the implementation plan

- `wire.rs`: round-trip encode/decode test for `indicator_update`, both `kind: support/resistance` (with `volume`) and `kind: none` (no `volume` field, and a fixture proving a stray `volume` alongside `kind: none` fails to parse — the unrepresentable-state guarantee from §2).
- `IndicatorStore`: unit tests — latest-wins per `(pair, name)`, expired entries correctly excluded from both `latest()` and `valid_indicators()` while still retained (queryable) for the persistence audit trail, multiple names/pairs don't collide, `valid_indicators()` returns entries of every `kind` (confirming it stays independent of `combined_levels`, which this spec leaves untouched).
- `state_store`: `indicators` table insert + a query test mirroring `record_signal`'s pattern, including a `kind: none` row with `volume` null.
- `main/levels.py` + new `main/mq/` sender: unit test the `levels.txt` → wire-JSON mapping (column parsing, `LEVEL_TYPE_*` → `kind` collapse, `LI_TIME2` → `expires_at`), and an integration test against a fake PULL client (mirroring `zmq_transport.rs`'s existing `a_decision_posted_by_a_real_zmq_client_...` test pattern, from the sender's side this time).
