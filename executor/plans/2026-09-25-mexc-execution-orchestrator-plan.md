# MEXC trading connector 4/5 — Execution + orchestrator (L3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Index: [2026-09-25-mexc-connector-index-plan.md](2026-09-25-mexc-connector-index-plan.md).

**Goal:** Make the executor act on what each venue can and cannot do. The boot gate refuses unsafe configurations. Execution refuses shorts it cannot place, sizes closes where `reduce_only` is not enforced, records a deliberate local-only stop honestly, keeps futures stops alive across expiry, and resolves unknown order outcomes while running, not only at restart.

**Spec:** D1, D4, §5.2 (whole), §5.3 (runtime recovery), §6.3, §7.3 (renewal, lost stop), §9 (env, waiver); review items R11, R16–R24, R26.

**Scope:** `crates/orchestrator`, `crates/execution`, `crates/state_store` (only if a read path needs `stop_leg`), `crates/visualizer_server` + `static/` (the "local only" label). **No** adapter code: everything here runs against scripted fakes whose `capabilities()` match spec §5.1, so this plan does not wait for 3/5 or 5/5.

**Depends on:** 2/5 merged (`Capabilities`, `PermissionProbe`, `get_order_by_client_id`, `PermissionDenied`). The position-management precondition (index).

**Branch:** `mexc-execution`, cut from `mexc-trading-connector`.

---

## Readiness review

Verified against `layer-implementation` @ 165afdb plus the uncommitted position-management work.

| Item | Today | Change | Size |
|---|---|---|---|
| Orchestrator keeps only `Arc<dyn MarketAccount>` | `orchestrator/src/main.rs:256-257`; adapter dropped | keep `Arc<dyn ExchangeAdapter>` beside the account | 🟡 |
| `KindAccount::resolve` | `.expect` panic on first use (`main.rs:38-46`) | resolve once at boot → config error | 🟢 |
| Hedge-mode boot guard (pos-mgmt D10) | **not built** | boot gate step 2 | 🟡 |
| Leverage / margin type at boot | never called | `FUTURES_LEVERAGE`, `FUTURES_MARGIN_TYPE` | 🟡 |
| `NotPlaced { pair, reason: String }` | `execution/src/types.rs:485`; mirrored in state_store / mq_gateway / visualizer dtos | reason **strings** `"short_unsupported"`, `"market_closed"`; no type change | 🟢 |
| `place_stop` on failure | writes `(Stop, OrderInfo{Rejected})` + Critical `OrderPlacementFailed` (`engine.rs:379-411`) | skip when `!native_stop`, set `stop_leg` | 🟡 |
| Exits / stops always `reduce_only: true` | `engine.rs:393,433` | unchanged; size capped when `!reduce_only_enforced` | 🟡 |
| `OpenPosition` persistence | full struct in `position_log.state jsonb` (`0009_position.sql:101`) | `stop_leg` rides in the JSON with a serde default; **no migration** | 🟢 |
| Runtime `submitted_unknown` resolution | boot only | fill-sync tick | 🟡 |
| Plan-order renewal / lost-stop re-place | none | new, in the fill-sync loop | 🟡 |
| Feed-loss grace | **not built** (pos-mgmt deliverable) | none here; M4 blocked on it | — |

---

## Global constraints

- **Capabilities decide, never exchange names.** No `if exchange == Mexc` in execution or orchestrator. Every branch reads `capabilities()`.
- **Binance behaviour changes only where spec says so:** Binance spot now refuses shorts (`can_short == false`). Everything else on Binance is unchanged; its test suite is the check.
- **Boot gate runs only for `EXECUTION_MODE=live`.** `no_trade` boots as today.
- **Nothing sent before a refusal.** A refused decision makes zero adapter calls (asserted with a counting fake).
- One commit per layer, green in Docker, after user confirmation.

---

## Docker Entry Points

```bash
docker compose run --build --rm test cargo test -p orchestrator
docker compose run --build --rm test cargo test -p execution
docker compose run --build --rm test                         # layer gate

# Boot-gate smoke (no credentials needed: each case must exit non-zero before any order)
docker compose run --rm -e EXECUTION_MODE=live -e EXCHANGE=mexc -e MARKET_KIND=margin executor
docker compose run --rm -e EXECUTION_MODE=live -e EXCHANGE=mexc -e MARKET_KIND=spot   executor   # no waiver
```

Verified: [ ] baseline green on `mexc-execution` at its cut point.

---

## Layer 1: orchestrator configuration

### Task 1.1: Config

**Files:** `orchestrator/src/config.rs`.

**Interface:**
```rust
pub struct VenueGateConfig {
    pub allow_local_only_stop: bool,                  // ALLOW_LOCAL_ONLY_STOP == "1" exactly
    pub local_only_max_notional: Option<Decimal>,     // LOCAL_ONLY_MAX_NOTIONAL, quote units
    pub futures_leverage: u32,                        // FUTURES_LEVERAGE, default 1
    pub futures_margin_type: MarginType,              // FUTURES_MARGIN_TYPE isolated|cross, default isolated
}
```

**Unit tests (RED first):** defaults; `ALLOW_LOCAL_ONLY_STOP=true` / `yes` → false (only `"1"` arms, same rule as `LIVE_TRADE_OPS`); negative or zero `LOCAL_ONLY_MAX_NOTIONAL` → config error; unknown margin type → config error; `FUTURES_LEVERAGE=0` → config error.

---

## Layer 2: boot gate

### Task 2.1: Keep the adapter; resolve the kind once

**Interface:**
```rust
pub struct Venue { pub adapter: Arc<dyn ExchangeAdapter>, pub account: Arc<dyn MarketAccount>, pub kind: MarketKind }
pub fn build_venue(cfg: &OrchestratorConfig) -> Result<Venue, ConfigError>;   // replaces build_market_account()
```
`KindAccount` either goes, or keeps the resolved `&dyn MarketAccount` and never panics.

**Unit tests (RED first):** MEXC + `margin` → `ConfigError` naming the kind (after 3/5 / 5/5, MEXC `margin()` is `None`; until then a fake adapter with `margin() == None` stands in); Binance + each kind → Ok; the process exits non-zero with that message, not a panic backtrace.

### Task 2.2: Gate steps (spec §5.2)

**Interface:**
```rust
pub enum GateRefusal { KindUnsupported(MarketKind), HedgeMode, NoOrderPermission,
                       LocalOnlyStopNotWaived, LocalOnlyCapMissing, SetupFailed(AdapterError) }
pub async fn run_boot_gate(venue: &Venue, cfg: &VenueGateConfig, pairs: &[Pair],
                           alerts: &dyn Alerts) -> Result<(), GateRefusal>;
```
Order: (1) kind resolved (Task 2.1); (2) futures: `futures_ops().is_hedge_mode()` true → `HedgeMode`; (3) `permission_probe()` present → `probe_order_permission(first pair)`; (4) `!capabilities().can_place_orders` → `NoOrderPermission`; (5) `!native_stop` → `LocalOnlyStopNotWaived` unless waived **and** capped (`LocalOnlyCapMissing` if waived without cap), then one `Severity::Critical` banner; (6) futures: per pair `set_margin_type` then `set_leverage`, any error → `SetupFailed`.

**Integration test → execution (RED):** `live_boot_on_mexc_futures_fake_reaches_execution`: a scripted MEXC-futures-shaped fake (one-way, permission ok) passes the gate, leverage/margin are set per pair, and the execution engine starts with the same account. The same fake in hedge mode never constructs the engine.

**Unit tests (RED first):** one per refusal; waived spot → exactly one Critical banner, no `OrderPlacementFailed`; `no_trade` mode skips the gate entirely; probe returns `Err` → `SetupFailed` (fail closed); `futures_ops()` `None` on a futures kind → `SetupFailed`; setup order is margin type then leverage (a counting fake records calls).

---

## Layer 3: execution behaviour

### Task 3.1: `StopLeg`

**Interface:**
```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum StopLeg { #[default] Exchange, LocalOnly, Unprotected }
// OpenPosition gains:  #[serde(default)] pub stop_leg: StopLeg,
```

**Unit tests (RED first):** an old `position_log.state` JSON without the field deserialises to `Exchange`; `place_stop` success → `Exchange`; failure → `Unprotected` (the existing Rejected entry + Critical alert stay); `!native_stop` → `LocalOnly`, **no** stop order sent, **no** `OrderPlacementFailed`; `run_stop_loss_watcher` still arms the local leg in all three states.

### Task 3.2: Short refusal and market-closed refusal

**Interface:** constants in `execution/src/types.rs`: `pub const REASON_SHORT_UNSUPPORTED: &str = "short_unsupported";` `pub const REASON_MARKET_CLOSED: &str = "market_closed";`

**Unit tests (RED first):** `side: short` with `can_short == false` → `NotPlaced { reason: "short_unsupported" }`, **zero** adapter calls (counting fake), one `WARN` per decision id; `get_market_info().trading_status == Halted` → `NotPlaced { reason: "market_closed" }` before placement; an exit on a `Halted` pair is **not** refused.

### Task 3.3: Close sizing without `reduce_only`

**Unit tests (RED first):** `!reduce_only_enforced`: exit qty = `min(net_size, free_base)` read from `get_account_state` just before placement; free base < net_size (fee taken in base) → capped; free base 0 → no order, `WARN`, position stays `Closing` for the next tick; `reduce_only_enforced` → uncapped (unchanged behaviour). `reduce_only: true` is still sent in every case.

### Task 3.4: Local-only notional cap

**Unit tests (RED first):** `!native_stop` with cap 50 and a sized entry worth 120 → entry clamped to 50 of quote; below min notional after clamping → `NotPlaced { reason: "below min notional after local-only cap" }`; `native_stop` → no clamp.

### Task 3.5: Runtime recovery of unknown outcomes

**Unit tests (RED first):** `place_order` returns `Network` → the journal row stays `submitted_unknown`; on the fill-sync tick after `recv_window + 10 s`, `get_order_by_client_id` → `Some` → tracked normally; `None` → marked rejected and the position resolves as not opened; before that age → no lookup; `client_id_lookup == false` → leave it for boot recovery, with a `WARN`.

### Task 3.6: Futures stop upkeep

**Unit tests (RED first), with a `native_stop` fake:** a stop placed 6 days ago is cancelled and re-placed (same trigger, new client id, `stop_leg` stays `Exchange`); a stop that turns `Cancelled` without execution having cancelled it → re-placed at once, one `WARN`; re-place fails → `stop_leg = Unprotected` and Critical `OrderPlacementFailed`; a stop that turns `Filled` → the normal stopped-out path.

### Task 3.7: Runtime permission loss

**Unit tests (RED first):** after `can_place_orders` flips false (fake), new entries → `NotPlaced { reason: "no order permission" }`; closes are still attempted; the alert fires once (from the adapter, asserted not duplicated by execution).

---

## Layer 4: visualiser label

### Task 4.1: Show `stop_leg`

**Files:** the position view DTO in `visualizer_server`, the position panel in `static/`.

**Unit / fixture tests (RED first):** DTO carries `stop_leg`; a committed route fixture with `LocalOnly`; the panel shows "stop: local only" (not "unprotected") for `LocalOnly`, and "UNPROTECTED" for `Unprotected`.

---

## Layer 5: docs

- [ ] Spec §5.2 / §11 L3 row ticked; drift amended in the spec and noted in §15.
- [ ] Deploy docs / env examples list `ALLOW_LOCAL_ONLY_STOP`, `LOCAL_ONLY_MAX_NOTIONAL`, `FUTURES_LEVERAGE`, `FUTURES_MARGIN_TYPE`.
- [ ] Layer gate green in Docker; commit after confirmation.
