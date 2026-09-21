# L5 — state_store

Part of [architecture index](../2026-09-04-architecture-design.md).

## Purpose

Crash recovery, plus an audit log of what main/ actually sent. Persist
position/order state so a restart doesn't lose track of open trades or
in-flight orders, and persist every inbound message from main/
(decisions with their levels, force actions) so it's inspectable later
— even after the decision is stale, acted on, or superseded.

## Storage backend

**Superseded 2026-09-11** — same backend change as L1, per
[postgres-market-data-store-design.md](../2026-09-09-postgres-market-data-store-design.md):
PostgreSQL, not the embedded KV store this spec originally assumed.
"Tree" below (`decision_log` tree, `event_log` tree, etc.) is leftover
terminology from that original design — read it as "table"; the
append-only/overwrite-on-persist semantics each one describes are
unchanged by the backend swap, only the storage mechanism is.

Write methods (`persist`, `log_decision`, and whatever else this
interface grows) are `async fn` and **synchronously durable**: they
commit to Postgres before returning, with no batching and no queue.
This is deliberately the opposite of L1's batched single-writer-task
design — L1's events arrive at book-tick rates and batching is what
makes that volume affordable, while L5's writes fire once per decision
and exist specifically to survive a crash, so trading away that
guarantee for throughput would defeat the only reason this layer
writes synchronously at all.

`last_reconciliation` stays exactly as specified below: an in-memory,
process-lifetime cache, never written to Postgres. That was already
true under the embedded-store design for "don't invent a second
persisted copy of derivable data," and nothing about moving the rest
of this layer to Postgres changes the reasoning — a since-last-boot
fact has no business surviving a restart.

**Implementation status, as of this branch:** `persist`, `load_all`,
`reconcile`, `log_decision` and `read_decision_log` exist in
`state_store`'s actual code (`crates/state_store/src/{lib,pg}.rs`) and
are async/Postgres-backed as described above. `log_event`/
`read_event_log` (the `event_log` additions described below, dated
2026-09-07) do **not** exist in this branch's code — they live on the
unmerged `state-store-expansion` branch. The `event_log` table itself
is already present in this branch's migration
(`migrations/0001_init.sql`), created but unused by any code path here
— so that future merge needs no new migration for it, only the Rust
methods. `current_levels`/`current_command`/`analysis_current`/
`analysis_log`/`read_wall_log` (described further below, dated
2026-09-08 and 2026-09-09) are likewise spec-only on this branch: no
backing tables exist yet in `migrations/0001_init.sql`, and no code in
`state_store` implements them. Treat everything below this point that
isn't `persist`/`load_all`/`reconcile`/`log_decision`/
`read_decision_log` as the target design for a future merge, not as
built.

## Responsibilities

- Persist every state change `execution` emits (position/order state,
  for crash recovery).
- **decision_log**: persist every inbound message from main/ as
  `execution` receives it — trade decisions (side, kind, timeframe,
  main/'s levels) and force actions alike, per L4's wire format. This
  is an append-only audit log, separate from position/order state:
  it's not read for reconciliation or crash recovery, it's for later
  answering "what did main/ actually send, and when" — including
  decisions that lapsed, were rejected (`NoOp`/`RiskViolation`), or
  were superseded before ever reaching the exchange.
- **event_log** (added 2026-09-07, for `visualizer_backend`'s
  historical event replay — see
  [executor-visualiser-design.md](../2026-09-07-executor-visualiser-design.md)):
  persist every `PositionStateEvent` `execution` emits on
  `subscribe_state_changes` — Opened/Closed/StoppedOut/
  StopLossMoved/NotPlaced/AlreadyClosed — append-only, keyed the same
  way as `decision_log` (`(pair, received_at, seq)`). This is a
  **second, distinct tree from the current-`PositionState` tree**
  described above: the current-state tree stays overwrite-on-persist
  by design (crash-recovery snapshot, not a log); `event_log` is the
  outcome history that tree deliberately doesn't keep. Not read for
  reconciliation or crash recovery — purely for later "what actually
  happened, and when," the outcome-side counterpart to `decision_log`'s
  intent-side record.
- On restart, reconcile persisted position/order state against the
  exchange's actual account/position/open-orders state — the exchange
  is always the source of truth, since fills or liquidations may have
  happened while the process was down. (Neither `decision_log` nor
  `event_log` is part of this reconciliation — both are records, not
  authoritative state.)
- **current_levels / current_command** (added 2026-09-08, see
  [state-store-expansion-design.md](../2026-09-08-state-store-expansion-design.md)):
  a derived read-cache, not a new persisted fact — `decision_log`
  already holds every level/command main/ ever sent, replayably.
  `log_decision` (unchanged signature) additionally upserts "latest
  per pair" into `current_levels` (only for `Decision` records, which
  carry levels) and `current_command` (every record, `Decision` or
  `Force`), so `execution` can read the current value in O(1) instead
  of scanning `decision_log` on every iteration.
- **indicators** (added 2026-09-20, **built** — see
  [level-broadcast-design.md](../2026-09-19-level-broadcast-design.md)):
  persist every `indicator_update` L4 receives from main/, append-only,
  one row per message, in a single `indicators` table
  (`migrations/0007_indicators.sql`, `SCHEMA_VERSION` 6 → 7). Columns:
  `seq` (from `global_ins_seq`), `pair`, `name`, `value`, `kind`,
  `volume` (nullable), `expires_at`, `received_at`, with a
  `volume_matches_kind` CHECK enforcing `volume IS NULL` exactly when
  `kind = 'none'` — the same invariant L4's parser enforces on the
  wire, asserted independently in the database because writer and
  readers must agree it always holds, not just at write time. Index
  `(pair, name, received_at DESC)` serves the read below as an index
  scan's first hit.

  Deliberately **not** paired with a current-value table the way
  `analysis_log` is with `analysis_current`: each row carries its own
  `expires_at`, so cheap repeated reads come from a read-through cache
  keyed by that expiry rather than from the write path maintaining a
  duplicate row. Whether `analysis_*` should converge on this shape is
  open, recorded in [TECH_DEBT.md](../../TECH_DEBT.md) §1 (and §2 for
  the cache's single `Mutex`), not settled here.
- **analysis_current / analysis_log** (added 2026-09-08, same doc as
  above): a cache for whatever `local_analysis` computes per pair
  (EMA, buy/sell zones, once those signals exist), so an iteration can
  reuse the last value instead of recomputing it from scratch.
  `analysis_current` is overwrite-per-`(pair, kind)` (the fast read);
  `analysis_log` is its append-only history, keyed like `decision_log`/
  `event_log`, for later replay/charting. One `persist_analysis` call
  writes both. Values are opaque `Vec<u8>` — `local_analysis` has no
  settled EMA/zone types yet, and `state_store` doesn't need to parse
  them to cache them.

## Depends on

`execution::ExecutionEngine::subscribe_state_changes` (what to persist
for crash recovery, and — as a second, independent subscription — what
`event_log` records), plus `execution` forwarding every inbound
message it receives from `mq_gateway` for `log_decision` (execution
stays the sole `mq_gateway` subscriber, per its own doc — `state_store`
never subscribes to `mq_gateway` directly). `exchange_adapter::
MarketAccount::get_account_state` — one call per market kind the
position uses — (truth to reconcile against, at boot only).

The `event_log` write path is a second broadcast subscriber on
`subscribe_state_changes` (the channel is `tokio::sync::broadcast`,
multi-consumer by design — `mq_gateway`'s relay is the first
subscriber, this is the second), not a tap on that relay. A slow or
lagging `event_log` writer never blocks or slows `mq_gateway`'s
delivery, and neither this nor `mq_gateway`'s subscription touches
`execution`'s own decision-making call path.

## Interface exposed upward

```
// Superseded 2026-09-11: persist/load_all/reconcile/log_decision/
// read_decision_log are `async fn` now (commit before returning, per
// Storage backend above) and carry Result<_, StoreError> where they
// didn't before -- this is what's actually implemented. log_event/
// read_event_log and everything from current_levels down are kept
// here as the still-current target shape, but see the implementation-
// status note above: none of them exist in this branch's code.
trait StateStore {
    async fn persist(&self, state: PositionState) -> Result<(), StoreError>;
    async fn load_all(&self) -> Result<Vec<PositionState>, StoreError>;
    async fn reconcile(&self, truth: AccountState) -> Result<ReconciliationReport, StoreError>;
    async fn log_decision(&self, id: DecisionId, record: DecisionRecord, received_at: Ts)
        -> Result<(), StoreError>;
    async fn read_decision_log(&self, from: Ts, to: Ts) -> Result<Stream<DecisionRecord>, StoreError>;
    fn log_event(&self, pair: Pair, event: PositionStateEvent, received_at: Ts)
        -> Result<(), StoreError>;
    fn read_event_log(&self, pair: Pair, from: Ts, to: Ts) -> Stream<PositionStateEvent>;
    fn last_reconciliation(&self) -> Option<ReconciliationReport>;

    // added 2026-09-08, see state-store-expansion-design.md
    fn current_levels(&self, pair: Pair) -> Option<(Vec<Level>, Ts)>;
    fn current_command(&self, pair: Pair) -> Option<(DecisionRecord, Ts)>;
    fn persist_analysis(&self, pair: Pair, kind: String, value: Vec<u8>, computed_at: Ts)
        -> Result<(), StoreError>;
    fn current_analysis(&self, pair: Pair, kind: String) -> Option<(Vec<u8>, Ts)>;
    fn read_analysis_log(&self, pair: Pair, kind: String, from: Ts, to: Ts)
        -> Stream<(Vec<u8>, Ts)>;

    // added 2026-09-09, see wall-visualisation-design.md
    fn read_wall_log(&self, pair: Pair, from: Ts, to: Ts) -> Stream<WallSnapshot>;
}

// added 2026-09-20, see level-broadcast-design.md -- BUILT.
//
// Write side is its own trait, same reasoning as WallSink/SignalSink: an
// indicator reading is a pure side-channel record with no bearing on
// crash recovery, so a caller that only writes readings has no reason to
// depend on the rest of StateStore's surface. Committed before it
// returns (same synchronous durability as `persist`); only after the
// INSERT commits is the in-process cache refreshed, so a failed write
// never leaves the cache asserting something unpersisted.
#[async_trait]
trait IndicatorSink {
    async fn record_indicator(&self, pair: Pair, reading: &IndicatorReading)
        -> Result<(), StoreError>;
}

struct IndicatorReading { name: String, value: Decimal, kind: IndicatorKind, expires_at: Ts }
enum IndicatorKind { Support { volume: Decimal }, Resistance { volume: Decimal }, None }

// Read side: an inherent method on StateStoreImpl (alongside
// current_analysis), not on the StateStore trait. Returns the newest
// non-expired row for (pair, name):
//   1. cached entry for (pair, name) with now < cached.expires_at -> served
//      without a DB round-trip;
//   2. otherwise SELECT ... WHERE pair = $1 AND name = $2 AND expires_at > $3
//      ORDER BY received_at DESC LIMIT 1;
//   3. whatever that returned is cached (None clears any stale entry).
// The cache is private to the store -- `Mutex<HashMap<(String, String),
// IndicatorReading>>`, plain not tokio, following last_reconciliation's
// precedent (held only across a synchronous clone/insert, never an .await).
// Per-process, never shared or coordinated between processes.
async fn current_indicator(&self, pair: Pair, name: &str, now: Ts)
    -> Result<Option<IndicatorReading>, StoreError>;

// added 2026-09-21, see indicator-visualisation-design.md -- BUILT.
// On PgStateReader (the visualiser's read-only, `dashboard`-role reader),
// not on StateStoreImpl. Every indicator current for `pair` at `as_of`:
// per name, the newest row with received_at <= as_of < expires_at, sorted
// by name; each tuple's Ts is the row's received_at. A plain query -- the
// visualiser is a separate process where current_indicator's cache would
// be permanently cold. Undecodable kind/volume -> StoreError::Decode
// (strict `decode_indicator_kind`, unlike current_indicator's coercion).
async fn read_current_indicators(&self, pair: Pair, as_of: Ts)
    -> Result<Vec<(Ts, IndicatorReading)>, StoreError>;

// Read side only. The write side is local_analysis::WallSink, which
// StateStoreImpl implements — deliberately not a method here, because it
// fires on execution's decision path and so must not hand back a Result
// the caller has no safe way to fail on. Backed by a `wall_log` tree
// keyed (pair, ts, seq), same append-only pattern as `event_log`.
//
// An empty `walls` is a meaningful row ("we looked, there were none"),
// distinct from no row at all ("we never looked").
struct WallSnapshot { ts: Ts, walls: Vec<WallObservation> }

// NOTE: this is a typed special case of analysis_log above. When both
// land, wall_log should collapse into analysis_log with kind = "walls",
// keeping WallSink/WallSnapshot as the typed facade.

enum DecisionRecord {
    Decision(TradeDecision),   // per L4's wire format
    Force(ForceAction),
}
```

`PositionStateEvent` is `execution`'s own type (Opened/Closed/
StoppedOut/StopLossMoved/NotPlaced/AlreadyClosed) — reused directly,
same "no parallel redefinition" convention `DecisionRecord` already
follows for `TradeDecision`/`ForceAction`.

Consumers: `execution` (load_all at boot before accepting new
decisions; log_decision on every inbound message, regardless of
whether it was acted on), `interfaces::cli`/`visualizer_backend`
(read-only inspection of position state, decision log, and event log —
e.g. showing why a position was opened, from main/'s original levels,
and what actually happened to it since; `last_reconciliation` lets a
read-only caller show "did the last boot-time reconciliation find a
discrepancy for this pair" without ever calling `reconcile` itself —
read-only callers have no `AccountState` truth to reconcile against).

`execution` also reads `current_levels`/`current_command` each
iteration instead of scanning `decision_log`, and reads/writes
`current_analysis`/`persist_analysis` around its calls into
`local_analysis` to avoid recomputing an unchanged value (added
2026-09-08 — see
[state-store-expansion-design.md](../2026-09-08-state-store-expansion-design.md)
for the full rationale). `visualizer_backend` is a future consumer of
`read_analysis_log`, for charting analysis values the same way it
already charts `decision_log`/`event_log` entries — not required by
this addition.

`IndicatorSink`'s only writer is `orchestrator`'s `indicator_ingest`
task (L9), which is also the only component that subscribes to L4's
`IndicatorInbound` — `state_store` still never subscribes to
`mq_gateway` itself. `current_indicator` has no production reader yet
by design (the visualiser reads through `PgStateReader::
read_current_indicators` instead, added 2026-09-21): `local_analysis` is untouched by this addition,
`combined_levels`/wall-detection keeps being fed only by
decision-attached `TradeDecisionPayload.levels`, and checking logic
against indicators is explicitly a later spec. The visualizer is the
expected first reader (history straight off `indicators`, latest value
via `current_indicator`).

`last_reconciliation` (added 2026-09-08, for
`visualizer_backend::pair_snapshot` — see
[executor-visualiser-design.md](../2026-09-07-executor-visualiser-design.md)):
caches the most recent `reconcile` call's report in memory, `None`
before the first boot-time reconciliation. Process-lifetime state
only, never written to disk — same posture as `event_log`'s "don't
invent a second persisted copy of derivable data," just applied here
to a report that's inherently a since-last-boot fact rather than
something needing durability across restarts.

## Error handling

Corrupt or missing local state on boot is never trusted alone —
`reconcile` against `get_account_state` always runs before `execution`
starts accepting decisions; on conflict, exchange wins.

Corrupt or missing rows in `current_levels`/`current_command`/
`analysis_current`/`analysis_log` (added 2026-09-08) are treated as
absent rather than panicking the read — a bad cache row is safety-
inert (the caller just recomputes, or treats "no cached value" as
"nothing known yet"), unlike position state or the audit logs, whose
existing stricter handling is unchanged.

## Testing

Reconciliation logic tested against fixture "exchange truth vs local
state" mismatches (missing position, extra position, quantity drift,
stale order still shown open locally but filled/cancelled on exchange).
`log_decision`/`read_decision_log` tested independently of
reconciliation: every `TradeDecision`/`ForceAction` variant logged and
read back unchanged, including ones that never resulted in a placed
order (`NoOp`, `RiskViolation`, a lapsed decision) — the log must not
silently drop anything just because nothing happened as a result.
`log_event`/`read_event_log` tested the same way: every
`PositionStateEvent` variant logged and read back unchanged, ordered
by `received_at` within a pair; a second broadcast subscriber
(simulating `mq_gateway`'s own relay running concurrently) receiving
the same events proves the two subscriptions don't interfere with
each other. `last_reconciliation` tested directly: `None` before any
`reconcile` call, `Some(report)` matching the most recent call's
return value after one or more calls, unaffected by `log_event`/
`log_decision`/`persist`.

`indicators` (added 2026-09-20 — **built and green**, 2026-09-20, via
`docker compose run --build --rm test`): `record_indicator` persists a
`support` reading with its volume and a `none` reading with `volume`
NULL; repeated writes for one `(pair, name)` append rather than
replace; `current_indicator` returns the newest non-expired row, `None`
when the only row is expired, and `None` when nothing was ever sent.
Cache behavior tested explicitly: a second call inside the validity
window serves the cached value without re-querying (proved by
inserting a row out-of-band, bypassing `record_indicator`, between the
two calls); `record_indicator` makes its reading visible to the next
`current_indicator` call immediately, without waiting for the previous
entry to expire; a call past the cached `expires_at` re-queries; and a
**failed** INSERT leaves the cache unpolluted.
`read_current_indicators` (added 2026-09-21, 11 DB tests, all as the
`dashboard` role): newest row per name; one row per name, name-sorted;
expired rows excluded but still stored; an expired newest row falls
back to an older live one; past `as_of` honoured; rows received after
`as_of` excluded; pair isolation; `support`/`resistance` volume
decoded; empty table → empty vec; `expires_at == as_of` excluded; a
same-millisecond tie resolved by `seq`.

`current_levels`/`current_command`/`analysis_current`/`analysis_log`
(added 2026-09-08) tested independently: `log_decision(Decision)`
populates both `current_levels` and `current_command`;
`log_decision(Force)` populates only `current_command`; a second call
for the same pair overwrites both without altering `decision_log`'s
own entries (read `read_decision_log` back afterward to confirm).
`persist_analysis` round-trips bytes unchanged through both
`current_analysis` and `read_analysis_log`; a second call for the same
`(pair, kind)` overwrites `current_analysis` but appends in
`analysis_log`; different `kind`s for one pair, and the same `kind`
across different pairs, never collide.
