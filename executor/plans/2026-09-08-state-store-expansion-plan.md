# state_store Expansion (Iteration Caches) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `state_store` (L5) four missing pieces: `event_log`/`last_reconciliation` (already specified in `L5-state-store.md`, never coded), a derived `current_levels`/`current_command` read-cache over the existing `decision_log`, and a new `analysis_current`/`analysis_log` cache for whatever `local_analysis` computes per pair.

**Architecture:** All additions live in the existing `state_store` crate (`dto.rs`, `keys.rs`, `lib.rs`, `store.rs`) — one sled tree per new record kind, following the crate's own established pattern (JSON encoding via `serde_json`, byte keys via `keys.rs`, DTO mirrors of upstream domain types in `dto.rs`, corrupt-row-tolerant reads). No other crate changes; `execution`'s call sites for the new `persist_analysis`/`current_analysis` methods are explicitly out of scope (see Global Constraints).

**Tech Stack:** Rust, `sled`, `serde`/`serde_json`, `futures-util`/`futures-core`, `tokio` (dev-dep, for `#[tokio::test]`).

**Spec:** `external/executor/specs/2026-09-08-state-store-expansion-design.md` (and the sections it added to `external/executor/specs/layers/L5-state-store.md`).

## Global Constraints

- JSON encoding (`serde_json`) for every new tree's stored value, same as the crate's existing trees — `rust_decimal::Decimal`'s `Deserialize` impl needs a self-describing format (see `store.rs`'s and `dto.rs`'s existing comments on this).
- A corrupt or missing row in `current_levels`, `current_command`, `analysis_current`, or `analysis_log` must be treated as absent (`None`, or skipped from a stream) — never a panic. This is a *looser* rule than `position_state`/`decision_log`/`event_log`, which stay exactly as strict as they are today; do not change their error handling.
- `decision_log` itself, its `LoggedDecisionDto` encoding, and `read_decision_log`'s behavior are unchanged by this plan — `current_levels`/`current_command` are a side effect added inside `log_decision`'s existing body, not a replacement for anything it already does.
- `analysis_current`/`analysis_log` values are opaque `Vec<u8>` — this crate never parses them. Do not add any dependency on `local_analysis`'s EMA/zone types (they don't exist yet).
- Order book persistence (`market_data`'s `book_snapshot`/`book_update`) is untouched — out of scope for this plan entirely.
- `execution`'s iteration-loop wiring for `persist_analysis`/`current_analysis` (deciding when a cached analysis value is stale enough to recompute) is **not** part of this plan — this plan only adds the `state_store` interface. Do not touch any file under `crates/execution/`.
- Every new/changed public method on `StateStoreImpl` must satisfy the existing `StateStore` trait signature exactly as written in `L5-state-store.md` — do not invent a different shape for convenience.

---

## Task 1: `event_log` (`log_event` / `read_event_log`)

**Files:**
- Modify: `crates/state_store/src/dto.rs` (add `PositionStateEventDto` mirror + conversions)
- Modify: `crates/state_store/src/keys.rs` (add `pair_ts_seq_key`)
- Modify: `crates/state_store/src/lib.rs` (add `EventLogStream` type alias, `log_event`/`read_event_log` to the `StateStore` trait, import `PositionStateEvent`)
- Modify: `crates/state_store/src/store.rs` (add `event_log` tree + `event_seq` counter, implement both methods)
- Test: inline `#[cfg(test)] mod tests` at the bottom of `store.rs` (existing module)

**Interfaces:**
- Consumes: `execution::PositionStateEvent` (existing, `crates/execution/src/types.rs:95-113`, six variants: `NotPlaced{pair,reason}`, `Opened{pair,side,size,open_price,stop_loss_price,close_price}`, `Closed{pair,close_price}`, `StoppedOut{pair,stop_price}`, `AlreadyClosed{pair}`, `StopLossMoved{pair,new_stop_loss_price}`); `keys::seq_from_ts_seq_key` (existing, `keys.rs:32-38`, extracts trailing 8 bytes of any key as a `u64` — reused here even though `pair_ts_seq_key`'s layout differs from `ts_seq_key`'s, because both put `seq` in the trailing 8 bytes); existing test helper `store()` (`store.rs`, in `#[cfg(test)] mod tests`, returns `(StateStoreImpl, TempDir)`).
- Produces (used by Task 2, which touches the same `open()`/struct): `event_log: sled::Tree` and `event_seq: AtomicU64` fields on `StateStoreImpl`; a private `recover_max_trailing_seq(tree: &sled::Tree) -> Result<u64, StoreError>` function in `store.rs` (Task 4 reuses this for `analysis_seq` — same recovery logic, since neither tree's `tree.last()` gives the true max `seq` across all pairs the way `decision_log`'s single-counter `recover_seq` does).

- [ ] **Step 1: Add `PositionStateEventDto` to `dto.rs`**

Add near the bottom of `crates/state_store/src/dto.rs` (before the `#[cfg(test)]` module), and add `PositionStateEvent` to the `use execution::{...}` import at the top of the file:

```rust
use execution::{
    DecisionId, DecisionKind, ForceAction, ForceKind, OpenPosition, PositionState,
    PositionStateEvent, PositionStatus, TradeDecision,
};
```

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) enum PositionStateEventDto {
    NotPlaced {
        pair: Pair,
        reason: String,
    },
    Opened {
        pair: Pair,
        side: Side,
        size: Decimal,
        open_price: Decimal,
        stop_loss_price: Decimal,
        close_price: Decimal,
    },
    Closed {
        pair: Pair,
        close_price: Decimal,
    },
    StoppedOut {
        pair: Pair,
        stop_price: Decimal,
    },
    AlreadyClosed {
        pair: Pair,
    },
    StopLossMoved {
        pair: Pair,
        new_stop_loss_price: Decimal,
    },
}

impl From<&PositionStateEvent> for PositionStateEventDto {
    fn from(e: &PositionStateEvent) -> Self {
        match e {
            PositionStateEvent::NotPlaced { pair, reason } => PositionStateEventDto::NotPlaced {
                pair: pair.clone(),
                reason: reason.clone(),
            },
            PositionStateEvent::Opened {
                pair,
                side,
                size,
                open_price,
                stop_loss_price,
                close_price,
            } => PositionStateEventDto::Opened {
                pair: pair.clone(),
                side: *side,
                size: *size,
                open_price: *open_price,
                stop_loss_price: *stop_loss_price,
                close_price: *close_price,
            },
            PositionStateEvent::Closed { pair, close_price } => PositionStateEventDto::Closed {
                pair: pair.clone(),
                close_price: *close_price,
            },
            PositionStateEvent::StoppedOut { pair, stop_price } => PositionStateEventDto::StoppedOut {
                pair: pair.clone(),
                stop_price: *stop_price,
            },
            PositionStateEvent::AlreadyClosed { pair } => PositionStateEventDto::AlreadyClosed { pair: pair.clone() },
            PositionStateEvent::StopLossMoved { pair, new_stop_loss_price } => PositionStateEventDto::StopLossMoved {
                pair: pair.clone(),
                new_stop_loss_price: *new_stop_loss_price,
            },
        }
    }
}

impl From<PositionStateEventDto> for PositionStateEvent {
    fn from(d: PositionStateEventDto) -> Self {
        match d {
            PositionStateEventDto::NotPlaced { pair, reason } => PositionStateEvent::NotPlaced { pair, reason },
            PositionStateEventDto::Opened {
                pair,
                side,
                size,
                open_price,
                stop_loss_price,
                close_price,
            } => PositionStateEvent::Opened {
                pair,
                side,
                size,
                open_price,
                stop_loss_price,
                close_price,
            },
            PositionStateEventDto::Closed { pair, close_price } => PositionStateEvent::Closed { pair, close_price },
            PositionStateEventDto::StoppedOut { pair, stop_price } => PositionStateEvent::StoppedOut { pair, stop_price },
            PositionStateEventDto::AlreadyClosed { pair } => PositionStateEvent::AlreadyClosed { pair },
            PositionStateEventDto::StopLossMoved { pair, new_stop_loss_price } => {
                PositionStateEvent::StopLossMoved { pair, new_stop_loss_price }
            }
        }
    }
}
```

This step has no independent test of its own (it's a pure data-shape addition, exercised by Step 4's test) — proceed straight to Step 2.

- [ ] **Step 2: Add `pair_ts_seq_key` to `keys.rs`**

Add to `crates/state_store/src/keys.rs`, after `ts_seq_key`:

```rust
/// Key for the `event_log` tree: `(pair, received_at, seq)`, per
/// L5-state-store.md's `event_log` section — unlike `decision_log`
/// (global ordering, no pair component), `read_event_log` takes a
/// `pair` argument, so the pair is part of the key prefix (same
/// convention `market_data::keys::pair_seq_key` already uses) rather
/// than requiring a full-tree scan filtered in memory.
pub fn pair_ts_seq_key(pair: &Pair, ts: Ts, seq: u64) -> Vec<u8> {
    let mut key = pair.0.as_bytes().to_vec();
    key.push(0);
    key.extend_from_slice(&ts.0.to_be_bytes());
    key.extend_from_slice(&seq.to_be_bytes());
    key
}
```

Add this test to `keys.rs`'s existing `#[cfg(test)] mod tests`:

```rust
#[test]
fn pair_ts_seq_keys_sort_by_ts_then_seq_within_one_pair() {
    let pair = Pair("BTCUSDT".into());
    let mut keys = vec![
        pair_ts_seq_key(&pair, Ts(5), 0),
        pair_ts_seq_key(&pair, Ts(1), 9),
        pair_ts_seq_key(&pair, Ts(1), 2),
    ];
    keys.sort();
    assert_eq!(
        keys,
        vec![
            pair_ts_seq_key(&pair, Ts(1), 2),
            pair_ts_seq_key(&pair, Ts(1), 9),
            pair_ts_seq_key(&pair, Ts(5), 0),
        ]
    );
}

#[test]
fn pair_ts_seq_key_different_pairs_never_collide_even_at_same_ts_seq() {
    let a = pair_ts_seq_key(&Pair("BTC".into()), Ts(1), 0);
    let b = pair_ts_seq_key(&Pair("BTCUSDT".into()), Ts(1), 0);
    assert_ne!(a, b);
}
```

- [ ] **Step 3: Run the new `keys.rs` tests to verify they pass**

Run: `cargo test -p state_store pair_ts_seq_key`
Expected: both new tests PASS (this is a pure function, no RED phase needed — the function doesn't exist yet until Step 2 above, so writing test+impl together here is fine; every other step in this plan keeps the usual RED-first order).

- [ ] **Step 4: Write the failing test for `log_event`/`read_event_log`**

Add to `store.rs`'s existing `#[cfg(test)] mod tests` module (near the other `log_decision`/`read_decision_log` tests):

```rust
#[tokio::test]
async fn logged_events_read_back_unchanged_and_ordered_by_received_at() {
    use futures_util::StreamExt;

    let (store, _dir) = store();
    let pair = Pair("BTCUSDT".into());
    let opened = execution::PositionStateEvent::Opened {
        pair: pair.clone(),
        side: Side::Buy,
        size: Decimal::new(1, 0),
        open_price: Decimal::new(100, 0),
        stop_loss_price: Decimal::new(90, 0),
        close_price: Decimal::new(110, 0),
    };
    let closed = execution::PositionStateEvent::Closed { pair: pair.clone(), close_price: Decimal::new(110, 0) };

    store.log_event(pair.clone(), opened.clone(), exchange_adapter::Ts(100)).unwrap();
    store.log_event(pair.clone(), closed.clone(), exchange_adapter::Ts(200)).unwrap();

    let stream = store.read_event_log(pair, exchange_adapter::Ts(0), exchange_adapter::Ts(1000));
    let events: Vec<_> = stream.collect().await;
    assert_eq!(events, vec![opened, closed]);
}

#[tokio::test]
async fn read_event_log_never_returns_another_pairs_events() {
    use futures_util::StreamExt;

    let (store, _dir) = store();
    let btc = Pair("BTCUSDT".into());
    let eth = Pair("ETHUSDT".into());
    store
        .log_event(btc.clone(), execution::PositionStateEvent::AlreadyClosed { pair: btc.clone() }, exchange_adapter::Ts(1))
        .unwrap();
    store
        .log_event(eth.clone(), execution::PositionStateEvent::AlreadyClosed { pair: eth.clone() }, exchange_adapter::Ts(1))
        .unwrap();

    let stream = store.read_event_log(btc.clone(), exchange_adapter::Ts(0), exchange_adapter::Ts(10));
    let events: Vec<_> = stream.collect().await;
    assert_eq!(events, vec![execution::PositionStateEvent::AlreadyClosed { pair: btc }]);
}
```

- [ ] **Step 5: Run tests to verify they fail to compile**

Run: `cargo test -p state_store logged_events_read_back_unchanged`
Expected: compile error — `log_event`/`read_event_log` not found on `StateStoreImpl`/`StateStore`.

- [ ] **Step 6: Add `EventLogStream` and trait methods to `lib.rs`**

In `crates/state_store/src/lib.rs`, change the import to include `PositionStateEvent`:

```rust
use execution::{ForceAction, PositionState, PositionStateEvent, TradeDecision};
```

Add near `DecisionLogStream`'s definition:

```rust
/// `Stream<Item = PositionStateEvent>` per the spec's `event_log`
/// interface — same boxed/pinned shape as `DecisionLogStream`.
pub type EventLogStream = Pin<Box<dyn Stream<Item = PositionStateEvent> + Send>>;
```

Add to the `StateStore` trait, after `read_decision_log`:

```rust
    fn log_event(&self, pair: Pair, event: PositionStateEvent, received_at: Ts) -> Result<(), StoreError>;
    fn read_event_log(&self, pair: Pair, from: Ts, to: Ts) -> EventLogStream;
```

- [ ] **Step 7: Implement `log_event`/`read_event_log` in `store.rs`**

Update the `use` lines at the top of `store.rs`:

```rust
use crate::dto::{DecisionRecordDto, PositionStateDto, PositionStateEventDto};
use crate::keys;
use crate::{
    DecisionLogStream, DecisionRecord, EventLogStream, PairReconciliation, ReconciliationOutcome,
    ReconciliationReport, StateStore,
};
```

Add fields to `StateStoreImpl`:

```rust
pub struct StateStoreImpl {
    _db: sled::Db,
    position_state: sled::Tree,
    decision_log: sled::Tree,
    decision_seq: AtomicU64,
    event_log: sled::Tree,
    event_seq: AtomicU64,
    metrics: Arc<dyn Metrics>,
}
```

Update `open`:

```rust
pub fn open(path: &Path, metrics: Arc<dyn Metrics>) -> Result<Self, StoreError> {
    let db = sled::open(path)?;
    let decision_log = db.open_tree("decision_log")?;
    let decision_seq = AtomicU64::new(recover_seq(&decision_log)?);
    let event_log = db.open_tree("event_log")?;
    let event_seq = AtomicU64::new(recover_max_trailing_seq(&event_log)?);
    Ok(Self {
        position_state: db.open_tree("position_state")?,
        decision_log,
        decision_seq,
        event_log,
        event_seq,
        _db: db,
        metrics,
    })
}
```

Add the recovery helper next to the existing `recover_seq` function:

```rust
/// Resumes a `(..., seq)`-suffixed tree's seq counter past whatever was
/// last written, for keys where `tree.last()` does **not** give the true
/// max `seq` across the whole tree — `event_log` and `analysis_log` both
/// prefix their keys with `pair`/`(pair, kind)`, so the lexicographically
/// last key is the last pair/kind alphabetically, not necessarily the one
/// with the highest `seq`. `decision_log`'s `recover_seq` (above) has no
/// such prefix and keeps its cheaper `tree.last()`-only approach —
/// deliberately not generalized away from, since it's already correct
/// for that tree's key shape.
fn recover_max_trailing_seq(tree: &sled::Tree) -> Result<u64, StoreError> {
    let mut max_seq: Option<u64> = None;
    for entry in tree.iter() {
        let (key, _) = entry?;
        if let Some(seq) = keys::seq_from_ts_seq_key(&key) {
            max_seq = Some(max_seq.map_or(seq, |m| m.max(seq)));
        }
    }
    Ok(max_seq.map(|s| s + 1).unwrap_or(0))
}
```

Add to `impl StateStore for StateStoreImpl`, after `read_decision_log`:

```rust
    fn log_event(&self, pair: Pair, event: PositionStateEvent, received_at: exchange_adapter::Ts) -> Result<(), StoreError> {
        let seq = self.event_seq.fetch_add(1, Ordering::SeqCst);
        let dto = PositionStateEventDto::from(&event);
        self.event_log.insert(keys::pair_ts_seq_key(&pair, received_at, seq), encode(&dto)?)?;
        Ok(())
    }

    fn read_event_log(&self, pair: Pair, from: exchange_adapter::Ts, to: exchange_adapter::Ts) -> EventLogStream {
        let range = keys::pair_ts_seq_key(&pair, from, 0)..=keys::pair_ts_seq_key(&pair, to, u64::MAX);
        let events: Vec<PositionStateEvent> = self
            .event_log
            .range(range)
            .flatten()
            .filter_map(|(_, v)| decode::<PositionStateEventDto>(&v).ok())
            .map(PositionStateEvent::from)
            .collect();
        Box::pin(futures_util::stream::iter(events))
    }
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cargo test -p state_store logged_events_read_back_unchanged read_event_log_never_returns`
Expected: both PASS.

- [ ] **Step 9: Run the full existing test suite to confirm nothing broke**

Run: `cargo test -p state_store`
Expected: all tests PASS, including every pre-existing `persist`/`reconcile`/`log_decision` test.

- [ ] **Step 10: Commit**

```bash
git add crates/state_store/src/dto.rs crates/state_store/src/keys.rs crates/state_store/src/lib.rs crates/state_store/src/store.rs
git commit -m "feat(state_store): implement event_log (log_event/read_event_log)"
```

---

## Task 2: `last_reconciliation`

**Files:**
- Modify: `crates/state_store/src/lib.rs` (add `last_reconciliation` to the trait)
- Modify: `crates/state_store/src/store.rs` (add in-memory field, populate at the end of `reconcile`, implement the read)
- Test: `store.rs`'s existing `#[cfg(test)] mod tests`

**Interfaces:**
- Consumes: `ReconciliationReport` (existing, `lib.rs`, already derives `Clone`).
- Produces: `last_reconciliation: Mutex<Option<ReconciliationReport>>` field on `StateStoreImpl`, read by nothing else in this plan (future `visualizer_backend` consumer, per the spec — not part of this plan).

- [ ] **Step 1: Write the failing test**

Add to `store.rs`'s tests:

```rust
#[test]
fn last_reconciliation_is_none_before_any_reconcile_call() {
    let (store, _dir) = store();
    assert_eq!(store.last_reconciliation(), None);
}

#[test]
fn last_reconciliation_matches_the_most_recent_reconcile_call() {
    let (store, _dir) = store();
    let pair = Pair("BTCUSDT".into());

    let first = store.reconcile(account_with(vec![], vec![]));
    assert_eq!(store.last_reconciliation(), Some(first));

    let truth = account_with(vec![position_info(&pair, Side::Buy, 1, 100)], vec![]);
    let second = store.reconcile(truth);
    assert_eq!(store.last_reconciliation(), Some(second));
}

#[test]
fn last_reconciliation_is_unaffected_by_persist_or_log_decision() {
    let (store, _dir) = store();
    let pair = Pair("BTCUSDT".into());
    let report = store.reconcile(account_with(vec![], vec![]));

    store.persist(PositionState { pair: pair.clone(), status: PositionStatus::Flat }).unwrap();
    store
        .log_decision(DecisionId("d1".into()), DecisionRecord::Decision(TradeDecisionFixture::open()), exchange_adapter::Ts(1))
        .unwrap();

    assert_eq!(store.last_reconciliation(), Some(report));
}
```

- [ ] **Step 2: Run tests to verify they fail to compile**

Run: `cargo test -p state_store last_reconciliation`
Expected: compile error — `last_reconciliation` not found.

- [ ] **Step 3: Add the trait method to `lib.rs`**

Add to the `StateStore` trait, after `read_event_log`:

```rust
    fn last_reconciliation(&self) -> Option<ReconciliationReport>;
```

- [ ] **Step 4: Implement in `store.rs`**

Update the `use std::sync` line at the top of the file (this is the first task that needs `Mutex`):

```rust
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
```

Add the field to `StateStoreImpl`:

```rust
pub struct StateStoreImpl {
    _db: sled::Db,
    position_state: sled::Tree,
    decision_log: sled::Tree,
    decision_seq: AtomicU64,
    event_log: sled::Tree,
    event_seq: AtomicU64,
    last_reconciliation: Mutex<Option<ReconciliationReport>>,
    metrics: Arc<dyn Metrics>,
}
```

Initialize it in `open`:

```rust
        Ok(Self {
            position_state: db.open_tree("position_state")?,
            decision_log,
            decision_seq,
            event_log,
            event_seq,
            last_reconciliation: Mutex::new(None),
            _db: db,
            metrics,
        })
```

At the end of `reconcile`'s body (replacing its final line), store a clone of the report before returning it:

```rust
        let report = ReconciliationReport { entries };
        *self.last_reconciliation.lock().unwrap() = Some(report.clone());
        report
```

Add the trait method implementation, after `read_event_log`:

```rust
    fn last_reconciliation(&self) -> Option<ReconciliationReport> {
        self.last_reconciliation.lock().unwrap().clone()
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cargo test -p state_store last_reconciliation`
Expected: all three PASS.

- [ ] **Step 6: Run the full test suite**

Run: `cargo test -p state_store`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add crates/state_store/src/lib.rs crates/state_store/src/store.rs
git commit -m "feat(state_store): implement last_reconciliation"
```

---

## Task 3: `current_levels` / `current_command`

**Files:**
- Modify: `crates/state_store/src/dto.rs` (bump `LevelDto`/`LevelSourceDto` visibility to `pub(crate)`, add `CurrentLevelsDto`/`CurrentCommandDto`)
- Modify: `crates/state_store/src/lib.rs` (add trait methods, import `local_analysis::Level`)
- Modify: `crates/state_store/src/store.rs` (two new trees, `log_decision` gains a side effect, two new read methods)
- Test: `store.rs`'s existing `#[cfg(test)] mod tests`

**Interfaces:**
- Consumes: `keys::pair_key` (existing, `keys.rs:12-14`); `DecisionRecordDto`, its existing `From<&DecisionRecord>`/`From<DecisionRecordDto> for DecisionRecord` conversions, and `LevelDto`'s existing `From<&Level>`/`From<LevelDto> for Level` conversions (all in `dto.rs`, unchanged logic, only `LevelDto`/`LevelSourceDto`'s visibility changes from private to `pub(crate)` so `store.rs` can name the type directly).
- Produces: `current_levels(&self, pair: Pair) -> Option<(Vec<Level>, Ts)>` and `current_command(&self, pair: Pair) -> Option<(DecisionRecord, Ts)>` on `StateStoreImpl` — not consumed by any later task in this plan (future `execution` call sites, out of scope per Global Constraints).

- [ ] **Step 1: Write the failing tests**

Add to `store.rs`'s tests:

```rust
#[test]
fn log_decision_with_a_decision_populates_current_levels_and_current_command() {
    let (store, _dir) = store();
    let pair = Pair("BTCUSDT".into());
    let decision = execution::TradeDecision {
        id: DecisionId("d1".into()),
        pair: pair.clone(),
        kind: execution::DecisionKind::Open,
        side: Side::Buy,
        timeframe: execution::Timeframe::M15,
        main_levels: vec![local_analysis::Level::main(Decimal::new(100, 0))],
    };
    store
        .log_decision(DecisionId("d1".into()), DecisionRecord::Decision(decision.clone()), exchange_adapter::Ts(50))
        .unwrap();

    let (levels, ts) = store.current_levels(pair.clone()).expect("levels should be cached");
    assert_eq!(levels, vec![local_analysis::Level::main(Decimal::new(100, 0))]);
    assert_eq!(ts, exchange_adapter::Ts(50));

    let (command, ts) = store.current_command(pair).expect("command should be cached");
    assert_eq!(command, DecisionRecord::Decision(decision));
    assert_eq!(ts, exchange_adapter::Ts(50));
}

#[test]
fn log_decision_with_a_force_action_populates_current_command_only() {
    let (store, _dir) = store();
    let pair = Pair("BTCUSDT".into());
    let force = ForceAction { id: DecisionId("f1".into()), pair: pair.clone(), kind: ForceKind::CloseNow };
    store
        .log_decision(DecisionId("f1".into()), DecisionRecord::Force(force.clone()), exchange_adapter::Ts(60))
        .unwrap();

    assert_eq!(store.current_levels(pair.clone()), None, "a force action carries no levels");
    let (command, ts) = store.current_command(pair).expect("command should be cached");
    assert_eq!(command, DecisionRecord::Force(force));
    assert_eq!(ts, exchange_adapter::Ts(60));
}

#[tokio::test]
async fn a_second_log_decision_for_the_same_pair_overwrites_the_cache_not_the_decision_log() {
    use futures_util::StreamExt;

    let (store, _dir) = store();
    let pair = Pair("BTCUSDT".into());
    let first = TradeDecisionFixture::open();
    let second = execution::TradeDecision {
        id: DecisionId("d2".into()),
        pair: pair.clone(),
        kind: execution::DecisionKind::Close,
        side: Side::Sell,
        timeframe: execution::Timeframe::M60,
        main_levels: vec![local_analysis::Level::main(Decimal::new(200, 0))],
    };
    store.log_decision(DecisionId("d1".into()), DecisionRecord::Decision(first.clone()), exchange_adapter::Ts(1)).unwrap();
    store.log_decision(DecisionId("d2".into()), DecisionRecord::Decision(second.clone()), exchange_adapter::Ts(2)).unwrap();

    let (command, _) = store.current_command(pair.clone()).unwrap();
    assert_eq!(command, DecisionRecord::Decision(second.clone()));

    let stream = store.read_decision_log(exchange_adapter::Ts(0), exchange_adapter::Ts(10));
    let records: Vec<_> = stream.collect().await;
    assert_eq!(
        records,
        vec![DecisionRecord::Decision(first), DecisionRecord::Decision(second)],
        "both original decision_log entries must survive, unchanged, even though the cache now reflects only the latest"
    );
}

#[test]
fn current_levels_and_current_command_never_collide_across_pairs() {
    let (store, _dir) = store();
    let btc = Pair("BTCUSDT".into());
    let eth = Pair("ETHUSDT".into());
    let btc_decision = execution::TradeDecision {
        id: DecisionId("d1".into()),
        pair: btc.clone(),
        kind: execution::DecisionKind::Open,
        side: Side::Buy,
        timeframe: execution::Timeframe::M15,
        main_levels: vec![local_analysis::Level::main(Decimal::new(100, 0))],
    };
    let eth_decision = execution::TradeDecision {
        id: DecisionId("d2".into()),
        pair: eth.clone(),
        kind: execution::DecisionKind::Open,
        side: Side::Sell,
        timeframe: execution::Timeframe::M5,
        main_levels: vec![local_analysis::Level::main(Decimal::new(200, 0))],
    };
    store.log_decision(DecisionId("d1".into()), DecisionRecord::Decision(btc_decision.clone()), exchange_adapter::Ts(1)).unwrap();
    store.log_decision(DecisionId("d2".into()), DecisionRecord::Decision(eth_decision.clone()), exchange_adapter::Ts(2)).unwrap();

    assert_eq!(store.current_levels(btc).unwrap().0, btc_decision.main_levels);
    assert_eq!(store.current_levels(eth).unwrap().0, eth_decision.main_levels);
}
```

- [ ] **Step 2: Run tests to verify they fail to compile**

Run: `cargo test -p state_store current_levels current_command a_second_log_decision`
Expected: compile error — `current_levels`/`current_command` not found on `StateStoreImpl`/`StateStore`.

- [ ] **Step 3: Bump `LevelDto`/`LevelSourceDto` visibility and add the two cache DTOs in `dto.rs`**

Change:
```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
enum LevelSourceDto {
```
to:
```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) enum LevelSourceDto {
```

Change:
```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
struct LevelDto {
```
to:
```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) struct LevelDto {
```

Add near the bottom of `dto.rs` (before `#[cfg(test)]`):

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) struct CurrentLevelsDto {
    pub(crate) levels: Vec<LevelDto>,
    pub(crate) received_at: exchange_adapter::Ts,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) struct CurrentCommandDto {
    pub(crate) record: DecisionRecordDto,
    pub(crate) received_at: exchange_adapter::Ts,
}
```

- [ ] **Step 4: Add trait methods to `lib.rs`**

Add `local_analysis::Level` to the imports:

```rust
use local_analysis::Level;
```

Add to the `StateStore` trait, after `last_reconciliation`:

```rust
    fn current_levels(&self, pair: Pair) -> Option<(Vec<Level>, Ts)>;
    fn current_command(&self, pair: Pair) -> Option<(DecisionRecord, Ts)>;
```

- [ ] **Step 5: Implement in `store.rs`**

Add `local_analysis::Level` to the top-of-file imports (this is the first task that names it directly in `store.rs` — it's already a dependency of the crate, just not yet imported here):

```rust
use local_analysis::Level;
```

Update the `dto` import:

```rust
use crate::dto::{CurrentCommandDto, CurrentLevelsDto, DecisionRecordDto, PositionStateDto, PositionStateEventDto};
```

Add fields to `StateStoreImpl`:

```rust
pub struct StateStoreImpl {
    _db: sled::Db,
    position_state: sled::Tree,
    decision_log: sled::Tree,
    decision_seq: AtomicU64,
    event_log: sled::Tree,
    event_seq: AtomicU64,
    current_levels: sled::Tree,
    current_command: sled::Tree,
    last_reconciliation: Mutex<Option<ReconciliationReport>>,
    metrics: Arc<dyn Metrics>,
}
```

Update `open`:

```rust
        Ok(Self {
            position_state: db.open_tree("position_state")?,
            decision_log,
            decision_seq,
            event_log,
            event_seq,
            current_levels: db.open_tree("current_levels")?,
            current_command: db.open_tree("current_command")?,
            last_reconciliation: Mutex::new(None),
            _db: db,
            metrics,
        })
```

Change `log_decision`'s body to add the cache side effect:

```rust
    fn log_decision(
        &self,
        id: DecisionId,
        record: DecisionRecord,
        received_at: exchange_adapter::Ts,
    ) -> Result<(), StoreError> {
        let seq = self.decision_seq.fetch_add(1, Ordering::SeqCst);
        let record_dto: DecisionRecordDto = (&record).into();
        let dto = LoggedDecisionDto { id: id.0, record: record_dto.clone() };
        self.decision_log
            .insert(keys::ts_seq_key(received_at, seq), encode(&dto)?)?;

        let pair = match &record {
            DecisionRecord::Decision(d) => d.pair.clone(),
            DecisionRecord::Force(f) => f.pair.clone(),
        };
        let command_dto = CurrentCommandDto { record: record_dto, received_at };
        self.current_command
            .insert(keys::pair_key(&pair), encode(&command_dto)?)?;

        if let DecisionRecord::Decision(d) = &record {
            let levels_dto = CurrentLevelsDto {
                levels: d.main_levels.iter().map(crate::dto::LevelDto::from).collect(),
                received_at,
            };
            self.current_levels
                .insert(keys::pair_key(&pair), encode(&levels_dto)?)?;
        }
        Ok(())
    }
```

Add the two read methods, after `last_reconciliation`:

```rust
    fn current_levels(&self, pair: Pair) -> Option<(Vec<Level>, exchange_adapter::Ts)> {
        let bytes = self.current_levels.get(keys::pair_key(&pair)).ok()??;
        let dto: CurrentLevelsDto = decode(&bytes).ok()?;
        Some((dto.levels.into_iter().map(Level::from).collect(), dto.received_at))
    }

    fn current_command(&self, pair: Pair) -> Option<(DecisionRecord, exchange_adapter::Ts)> {
        let bytes = self.current_command.get(keys::pair_key(&pair)).ok()??;
        let dto: CurrentCommandDto = decode(&bytes).ok()?;
        Some((dto.record.into(), dto.received_at))
    }
```

`LevelDto::from` here needs `use crate::dto::LevelDto` in scope, or the fully-qualified `crate::dto::LevelDto::from` as written above — either is fine, keep whichever matches the file's existing import style once you're editing it.

Note `LoggedDecisionDto`'s `record` field is `DecisionRecordDto` (not `&DecisionRecordDto`) — the change above computes `record_dto` once and reuses it for both `LoggedDecisionDto` (via `.clone()`) and `CurrentCommandDto` (moved), instead of converting `&record` into a `DecisionRecordDto` twice.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cargo test -p state_store current_levels current_command a_second_log_decision`
Expected: all PASS.

- [ ] **Step 7: Run the full test suite**

Run: `cargo test -p state_store`
Expected: all PASS, including every pre-existing `log_decision`/`read_decision_log` test (proves the cache is a side-view, not a behavior change to the log itself).

- [ ] **Step 8: Commit**

```bash
git add crates/state_store/src/dto.rs crates/state_store/src/lib.rs crates/state_store/src/store.rs
git commit -m "feat(state_store): add current_levels/current_command derived cache"
```

---

## Task 4: `analysis_current` / `analysis_log`

**Files:**
- Modify: `crates/state_store/src/dto.rs` (add `AnalysisCurrentDto`)
- Modify: `crates/state_store/src/keys.rs` (add `analysis_key`, `pair_kind_ts_seq_key`)
- Modify: `crates/state_store/src/lib.rs` (add `AnalysisLogStream`, three trait methods)
- Modify: `crates/state_store/src/store.rs` (two new trees + seq counter, three new methods)
- Test: `keys.rs`'s and `store.rs`'s existing `#[cfg(test)] mod tests`

**Interfaces:**
- Consumes: `recover_max_trailing_seq` (added in Task 1, Step 7); `keys::seq_from_ts_seq_key` (existing).
- Produces: `persist_analysis`, `current_analysis`, `read_analysis_log` on `StateStoreImpl` — terminal task, nothing later in this plan consumes these (future `execution`/`visualizer_backend` call sites, out of scope per Global Constraints).

- [ ] **Step 1: Add key functions to `keys.rs`**

```rust
/// Key for the `analysis_current` tree: `(pair, kind)`, `0x00`-separated
/// (`kind` is a caller-chosen label like `"ema_5m"` or `"buy_zone"` —
/// ASCII, no embedded `0x00` byte assumed, same convention every other
/// string-keyed prefix in this file already relies on).
pub fn analysis_key(pair: &Pair, kind: &str) -> Vec<u8> {
    let mut key = pair.0.as_bytes().to_vec();
    key.push(0);
    key.extend_from_slice(kind.as_bytes());
    key
}

/// Key for the `analysis_log` tree: `(pair, kind, computed_at, seq)` —
/// `analysis_key`'s prefix plus a second `0x00` separator before the
/// same big-endian `ts`+`seq` suffix `ts_seq_key`/`pair_ts_seq_key` use.
pub fn pair_kind_ts_seq_key(pair: &Pair, kind: &str, ts: Ts, seq: u64) -> Vec<u8> {
    let mut key = analysis_key(pair, kind);
    key.push(0);
    key.extend_from_slice(&ts.0.to_be_bytes());
    key.extend_from_slice(&seq.to_be_bytes());
    key
}

/// Extracts the `ts` component from a [`pair_kind_ts_seq_key`] (the 8
/// bytes immediately before the trailing `seq`) — `analysis_log`'s
/// stored value is the caller's opaque bytes with no room for a
/// repeated `ts`, so `read_analysis_log` recovers it from the key,
/// same reasoning `seq_from_ts_seq_key` already documents for `seq`.
pub fn ts_from_pair_kind_ts_seq_key(key: &[u8]) -> Option<Ts> {
    if key.len() < 16 {
        return None;
    }
    let ts_bytes = &key[key.len() - 16..key.len() - 8];
    Some(Ts(u64::from_be_bytes(ts_bytes.try_into().ok()?)))
}
```

Add tests to `keys.rs`:

```rust
#[test]
fn analysis_key_different_kinds_for_the_same_pair_never_collide() {
    let pair = Pair("BTCUSDT".into());
    let a = analysis_key(&pair, "ema_5m");
    let b = analysis_key(&pair, "buy_zone");
    assert_ne!(a, b);
}

#[test]
fn pair_kind_ts_seq_keys_sort_by_ts_then_seq_within_one_pair_and_kind() {
    let pair = Pair("BTCUSDT".into());
    let mut keys = vec![
        pair_kind_ts_seq_key(&pair, "ema_5m", Ts(5), 0),
        pair_kind_ts_seq_key(&pair, "ema_5m", Ts(1), 9),
        pair_kind_ts_seq_key(&pair, "ema_5m", Ts(1), 2),
    ];
    keys.sort();
    assert_eq!(
        keys,
        vec![
            pair_kind_ts_seq_key(&pair, "ema_5m", Ts(1), 2),
            pair_kind_ts_seq_key(&pair, "ema_5m", Ts(1), 9),
            pair_kind_ts_seq_key(&pair, "ema_5m", Ts(5), 0),
        ]
    );
}

#[test]
fn ts_from_pair_kind_ts_seq_key_round_trips() {
    let key = pair_kind_ts_seq_key(&Pair("BTCUSDT".into()), "ema_5m", Ts(42), 7);
    assert_eq!(ts_from_pair_kind_ts_seq_key(&key), Some(Ts(42)));
}
```

- [ ] **Step 2: Run the new `keys.rs` tests**

Run: `cargo test -p state_store analysis_key pair_kind_ts_seq_key ts_from_pair_kind_ts_seq_key`
Expected: all PASS (same reasoning as Task 1 Step 3 — pure functions, test+impl together is fine here).

- [ ] **Step 3: Write the failing `store.rs` tests**

Add to `store.rs`'s tests:

```rust
#[test]
fn persist_analysis_round_trips_through_current_analysis() {
    let (store, _dir) = store();
    let pair = Pair("BTCUSDT".into());
    store.persist_analysis(pair.clone(), "ema_5m".into(), vec![1, 2, 3], exchange_adapter::Ts(100)).unwrap();

    let (value, ts) = store.current_analysis(pair, "ema_5m".into()).expect("value should be cached");
    assert_eq!(value, vec![1, 2, 3]);
    assert_eq!(ts, exchange_adapter::Ts(100));
}

#[test]
fn a_second_persist_analysis_overwrites_current_but_appends_to_the_log() {
    use futures_util::StreamExt;

    let (store, _dir) = store();
    let pair = Pair("BTCUSDT".into());
    store.persist_analysis(pair.clone(), "ema_5m".into(), vec![1], exchange_adapter::Ts(100)).unwrap();
    store.persist_analysis(pair.clone(), "ema_5m".into(), vec![2], exchange_adapter::Ts(200)).unwrap();

    let (value, ts) = store.current_analysis(pair.clone(), "ema_5m".into()).unwrap();
    assert_eq!(value, vec![2]);
    assert_eq!(ts, exchange_adapter::Ts(200));

    let stream = store.read_analysis_log(pair, "ema_5m".into(), exchange_adapter::Ts(0), exchange_adapter::Ts(1000));
    let entries: Vec<_> = stream.collect().await;
    assert_eq!(entries, vec![(vec![1], exchange_adapter::Ts(100)), (vec![2], exchange_adapter::Ts(200))]);
}

#[test]
fn analysis_cache_never_collides_across_kinds_or_pairs() {
    let (store, _dir) = store();
    let btc = Pair("BTCUSDT".into());
    let eth = Pair("ETHUSDT".into());
    store.persist_analysis(btc.clone(), "ema_5m".into(), vec![1], exchange_adapter::Ts(1)).unwrap();
    store.persist_analysis(btc.clone(), "buy_zone".into(), vec![2], exchange_adapter::Ts(1)).unwrap();
    store.persist_analysis(eth.clone(), "ema_5m".into(), vec![3], exchange_adapter::Ts(1)).unwrap();

    assert_eq!(store.current_analysis(btc.clone(), "ema_5m".into()).unwrap().0, vec![1]);
    assert_eq!(store.current_analysis(btc, "buy_zone".into()).unwrap().0, vec![2]);
    assert_eq!(store.current_analysis(eth, "ema_5m".into()).unwrap().0, vec![3]);
}

#[test]
fn read_analysis_log_filters_by_time_range() {
    use futures_util::StreamExt;

    let (store, _dir) = store();
    let pair = Pair("BTCUSDT".into());
    store.persist_analysis(pair.clone(), "ema_5m".into(), vec![1], exchange_adapter::Ts(100)).unwrap();
    store.persist_analysis(pair.clone(), "ema_5m".into(), vec![2], exchange_adapter::Ts(500)).unwrap();

    let stream = store.read_analysis_log(pair, "ema_5m".into(), exchange_adapter::Ts(0), exchange_adapter::Ts(200));
    let entries: Vec<_> = stream.collect().await;
    assert_eq!(entries, vec![(vec![1], exchange_adapter::Ts(100))], "only the ts=100 entry falls in [0,200]");
}
```

> **Note for the implementer:** `a_second_persist_analysis_overwrites_current_but_appends_to_the_log` and `read_analysis_log_filters_by_time_range` both use `.await` — mark both `#[tokio::test] async fn`, not `#[test] fn`.

- [ ] **Step 4: Run tests to verify they fail to compile**

Run: `cargo test -p state_store persist_analysis analysis_cache_never_collides read_analysis_log_filters`
Expected: compile error — `persist_analysis`/`current_analysis`/`read_analysis_log` not found.

- [ ] **Step 5: Add `AnalysisCurrentDto` to `dto.rs`**

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) struct AnalysisCurrentDto {
    pub(crate) value: Vec<u8>,
    pub(crate) computed_at: exchange_adapter::Ts,
}
```

- [ ] **Step 6: Add `AnalysisLogStream` and trait methods to `lib.rs`**

```rust
/// `Stream<Item = (Vec<u8>, Ts)>` for `analysis_log` — the opaque value
/// plus the `computed_at` recovered from the key (the stored value has
/// no room to repeat it, per `keys::ts_from_pair_kind_ts_seq_key`'s doc).
pub type AnalysisLogStream = Pin<Box<dyn Stream<Item = (Vec<u8>, Ts)> + Send>>;
```

Add to the `StateStore` trait, after `current_command`:

```rust
    fn persist_analysis(&self, pair: Pair, kind: String, value: Vec<u8>, computed_at: Ts) -> Result<(), StoreError>;
    fn current_analysis(&self, pair: Pair, kind: String) -> Option<(Vec<u8>, Ts)>;
    fn read_analysis_log(&self, pair: Pair, kind: String, from: Ts, to: Ts) -> AnalysisLogStream;
```

- [ ] **Step 7: Implement in `store.rs`**

Update the `dto` import:

```rust
use crate::dto::{AnalysisCurrentDto, CurrentCommandDto, CurrentLevelsDto, DecisionRecordDto, PositionStateDto, PositionStateEventDto};
```

Update the `crate::{...}` import:

```rust
use crate::{
    AnalysisLogStream, DecisionLogStream, DecisionRecord, EventLogStream, PairReconciliation,
    ReconciliationOutcome, ReconciliationReport, StateStore,
};
```

Add fields to `StateStoreImpl`:

```rust
pub struct StateStoreImpl {
    _db: sled::Db,
    position_state: sled::Tree,
    decision_log: sled::Tree,
    decision_seq: AtomicU64,
    event_log: sled::Tree,
    event_seq: AtomicU64,
    current_levels: sled::Tree,
    current_command: sled::Tree,
    analysis_current: sled::Tree,
    analysis_log: sled::Tree,
    analysis_seq: AtomicU64,
    last_reconciliation: Mutex<Option<ReconciliationReport>>,
    metrics: Arc<dyn Metrics>,
}
```

Update `open`:

```rust
    pub fn open(path: &Path, metrics: Arc<dyn Metrics>) -> Result<Self, StoreError> {
        let db = sled::open(path)?;
        let decision_log = db.open_tree("decision_log")?;
        let decision_seq = AtomicU64::new(recover_seq(&decision_log)?);
        let event_log = db.open_tree("event_log")?;
        let event_seq = AtomicU64::new(recover_max_trailing_seq(&event_log)?);
        let analysis_log = db.open_tree("analysis_log")?;
        let analysis_seq = AtomicU64::new(recover_max_trailing_seq(&analysis_log)?);
        Ok(Self {
            position_state: db.open_tree("position_state")?,
            decision_log,
            decision_seq,
            event_log,
            event_seq,
            current_levels: db.open_tree("current_levels")?,
            current_command: db.open_tree("current_command")?,
            analysis_current: db.open_tree("analysis_current")?,
            analysis_log,
            analysis_seq,
            last_reconciliation: Mutex::new(None),
            _db: db,
            metrics,
        })
    }
```

Add the three trait methods, after `current_command`:

```rust
    fn persist_analysis(&self, pair: Pair, kind: String, value: Vec<u8>, computed_at: exchange_adapter::Ts) -> Result<(), StoreError> {
        let current = AnalysisCurrentDto { value: value.clone(), computed_at };
        self.analysis_current
            .insert(keys::analysis_key(&pair, &kind), encode(&current)?)?;
        let seq = self.analysis_seq.fetch_add(1, Ordering::SeqCst);
        self.analysis_log
            .insert(keys::pair_kind_ts_seq_key(&pair, &kind, computed_at, seq), value)?;
        Ok(())
    }

    fn current_analysis(&self, pair: Pair, kind: String) -> Option<(Vec<u8>, exchange_adapter::Ts)> {
        let bytes = self.analysis_current.get(keys::analysis_key(&pair, &kind)).ok()??;
        let dto: AnalysisCurrentDto = decode(&bytes).ok()?;
        Some((dto.value, dto.computed_at))
    }

    fn read_analysis_log(&self, pair: Pair, kind: String, from: exchange_adapter::Ts, to: exchange_adapter::Ts) -> AnalysisLogStream {
        let range = keys::pair_kind_ts_seq_key(&pair, &kind, from, 0)..=keys::pair_kind_ts_seq_key(&pair, &kind, to, u64::MAX);
        let entries: Vec<(Vec<u8>, exchange_adapter::Ts)> = self
            .analysis_log
            .range(range)
            .flatten()
            .map(|(k, v)| {
                let ts = keys::ts_from_pair_kind_ts_seq_key(&k).unwrap_or(exchange_adapter::Ts(0));
                (v.to_vec(), ts)
            })
            .collect();
        Box::pin(futures_util::stream::iter(entries))
    }
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cargo test -p state_store persist_analysis analysis_cache_never_collides read_analysis_log_filters`
Expected: all PASS.

- [ ] **Step 9: Run the full test suite**

Run: `cargo test -p state_store`
Expected: all PASS — every test from Tasks 1-4 plus every pre-existing test in the crate.

- [ ] **Step 10: Commit**

```bash
git add crates/state_store/src/dto.rs crates/state_store/src/keys.rs crates/state_store/src/lib.rs crates/state_store/src/store.rs
git commit -m "feat(state_store): add analysis_current/analysis_log cache"
```

---

## Final check

- [ ] **Step 1: Run `cargo test -p state_store` one more time end to end**

Expected: every test in the crate PASSES — this plan touches only `state_store`, so no other crate's tests are affected.

- [ ] **Step 2: Run `cargo clippy -p state_store --all-targets`**

Expected: no new warnings introduced by this plan's code (pre-existing warnings, if any, are not this plan's concern to fix).
