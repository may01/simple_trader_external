# state_store expansion — iteration caches — design

Part of [architecture index](2026-09-04-architecture-design.md). Extends
[L5 — state_store](layers/L5-state-store.md).

## Purpose

`state_store` today persists position state (crash recovery,
reconciliation) and an audit trail of inbound decisions/outcomes
(`decision_log`, `event_log`). This adds three more things `execution`
needs on every iteration, so it isn't recomputing or rescanning history
for data it already has:

1. The **current** set of levels main/ last sent for a pair, without
   scanning `decision_log`.
2. The **current** command (decision or force action) main/ last sent
   for a pair, same reason.
3. A place to cache whatever `local_analysis` computes per pair (EMA,
   buy/sell zones, once those signals exist) so an iteration can reuse
   the last value instead of recomputing from scratch — **and** a
   replayable history of those values, so `visualizer_backend` can plot
   them at the point in time they were computed the same way it already
   plots `decision_log`/`event_log` entries.

## Decisions

**Levels/commands get no new history tree.** `decision_log` already
persists every inbound `TradeDecision` (levels included) and
`ForceAction`, in order, replayable via `read_decision_log` — that's
already how `visualizer_backend`'s History mode sources its event
panel (per the visualiser design's L5 addendum). Adding a second
history store for the same data would just be two copies of one fact
drifting apart. `current_levels`/`current_command` are a **derived
read-cache**: `log_decision` (unchanged signature) now also upserts a
small "latest per pair" tree as a side effect of the write it already
does. No new call sites in `execution` — it already calls
`log_decision` on every inbound message.

**Analysis snapshots get the position/event_log treatment: current +
log, two trees.** Unlike levels/commands, there is no existing history
for `local_analysis`'s output — it's pure functions today, nothing
persisted. So this follows the precedent the position/event split
already set: one overwrite tree for O(1) "latest value" reads
(`analysis_current`), one append-only tree keyed `(pair, kind, ts,
seq)` for replay (`analysis_log`), same convention as
`event_log`/`decision_log`. A single `persist_analysis` call writes
both — callers don't do double bookkeeping.

**Analysis values are opaque bytes, not a typed struct.** `local_analysis`
has no EMA/zone types yet, and won't be pinned down here — whatever it
eventually computes serializes to `Vec<u8>` on the way in, and comes
back the same way. `state_store` doesn't parse it. This matches
`dto.rs`'s own stated boundary: serde is an on-disk-format concern of
`state_store`, not something every upstream domain type should carry
— and here there isn't even a settled domain type yet to carry it.
Freshness/invalidation policy (when is a cached value stale enough to
recompute) is the caller's (`execution`'s) decision, not
`state_store`'s — this crate only stores and retrieves.

**Order book is explicitly out of scope.** Snapshot/update persistence
and a periodic (1-minute) exchange-snapshot re-fetch for fast recovery
both belong to `market_data` (L1), which already owns
`book_snapshot`/`book_update`/`BookTracker`. The 1-minute poller is a
separate, independent follow-up against L1 — not part of this change.

## Data model (new sled trees, `state_store`)

- `current_levels`: key = `pair_key(pair)` (reused from `keys.rs`),
  value = `(Vec<LevelDto>, Ts)`. Overwritten on every `log_decision`
  call carrying a `Decision` record.
- `current_command`: key = `pair_key(pair)`, value =
  `(DecisionRecordDto, Ts)`. Overwritten on every `log_decision` call,
  `Decision` or `Force` alike.
- `analysis_current`: key = `analysis_key(pair, kind)` (new key
  function: pair bytes, `0x00`, kind bytes), value = `(Vec<u8>, Ts)`.
  Overwritten on every `persist_analysis` call for that `(pair, kind)`.
- `analysis_log`: key = `pair_kind_ts_seq_key(pair, kind, ts, seq)`
  (new key function, same big-endian/`0x00`-separated convention as
  `keys.rs`'s existing `ts_seq_key`), value = raw `Vec<u8>`.
  Append-only; `seq` disambiguates same-millisecond writes for the
  same `(pair, kind)`, same role `decision_log`'s `seq` already plays.

## Interface exposed upward (additions to `StateStore`)

```rust
// Already specified 2026-09-08 in L5-state-store.md, not yet
// implemented in the crate — implemented as part of this change, no
// design change from what's already written there.
fn log_event(&self, pair: Pair, event: PositionStateEvent, received_at: Ts)
    -> Result<(), StoreError>;
fn read_event_log(&self, pair: Pair, from: Ts, to: Ts) -> Stream<PositionStateEvent>;
fn last_reconciliation(&self) -> Option<ReconciliationReport>;

// New in this change.
fn current_levels(&self, pair: Pair) -> Option<(Vec<Level>, Ts)>;
fn current_command(&self, pair: Pair) -> Option<(DecisionRecord, Ts)>;
fn persist_analysis(&self, pair: Pair, kind: String, value: Vec<u8>, computed_at: Ts)
    -> Result<(), StoreError>;
fn current_analysis(&self, pair: Pair, kind: String) -> Option<(Vec<u8>, Ts)>;
fn read_analysis_log(&self, pair: Pair, kind: String, from: Ts, to: Ts)
    -> Stream<(Vec<u8>, Ts)>;
```

`log_decision`'s own signature is unchanged — `current_levels`/
`current_command` are populated as an internal side effect of the
write it already does, keyed by the `pair` already present on both
`TradeDecision` and `ForceAction`.

## Wiring

- `log_decision` (called by `execution` on every inbound message,
  unchanged) — internally now also upserts `current_command[pair]`,
  and `current_levels[pair]` when the record is `Decision`.
- `event_log`/`last_reconciliation` — wiring already specified in
  L5-state-store.md (second broadcast subscriber on
  `subscribe_state_changes`, in-memory-only for `last_reconciliation`)
  — implemented here per that existing spec, no new decision.
- `persist_analysis`/`current_analysis` — new call sites in
  `execution`'s iteration loop: check `current_analysis(pair, kind)`,
  call into `local_analysis` only if absent/stale (policy lives in
  `execution`, not here), `persist_analysis` the result. That loop
  change is `execution`-side work and out of this crate's scope — this
  spec only adds the interface it calls.
- `read_analysis_log` — read-only, for `visualizer_backend` to overlay
  analysis values on the chart the same way it already overlays
  `event_log`/`decision_log` entries (future integration, not required
  by this change).

## Error handling

Corrupt or missing rows in `current_levels`/`current_command`/
`analysis_current`/`analysis_log` are treated as absent (skip-on-
decode-failure, same posture `load_all` already has for
`position_state`) rather than panicking the read — unlike position
state, a bad cache row is safety-inert: the caller just recomputes or
treats "no cached command" as "nothing known yet," it never feeds a
wrong value into a money-moving decision (positions and decision_log/
event_log — the safety- and audit-critical trees — keep their
existing, stricter handling, unchanged by this doc).

## Testing

- `log_decision(Decision)` populates both `current_levels` and
  `current_command`; `log_decision(Force)` populates only
  `current_command`. A second call for the same pair overwrites both
  (latest-only semantics) without touching `decision_log`'s own
  entries (proves the cache is a derived side-view, not a replacement
  — read `read_decision_log` back afterward and confirm both original
  entries are still there unchanged).
- `persist_analysis` round-trips bytes unchanged through both
  `current_analysis` and `read_analysis_log`; a second call for the
  same `(pair, kind)` overwrites `current_analysis` but appends (not
  overwrites) in `analysis_log`; different `kind`s for the same pair,
  and the same `kind` for different pairs, never collide.
- `log_event`/`read_event_log`/`last_reconciliation` tested exactly per
  the existing Testing section in L5-state-store.md (no change here).
