# state_store expansion on Postgres — design

Part of [architecture index](2026-09-04-architecture-design.md). Supersedes
the data model of
[state_store expansion — iteration caches](2026-09-08-state-store-expansion-design.md)
and extends [L5 — state_store](layers/L5-state-store.md).

## Purpose

The `state-store-expansion` branch implemented eight methods against the
sled backend: `log_event`/`read_event_log`, `last_reconciliation`,
`current_levels`/`current_command`, and
`persist_analysis`/`current_analysis`/`read_analysis_log`. That branch
never merged. Meanwhile `postgres-market-data-store` replaced the sled
backend outright, deleting `crates/state_store/src/{keys,store}.rs` — the
exact files the expansion built on. Merging the branch as-is resurrects
the sled store, so the work has to be re-landed against `pg.rs` instead.

This document records the data model and interface for that re-landing,
plus two related changes it pulls in: the per-level `kind` and the
force-action `reason` that main/ already sends on the wire and L4
currently discards.

## What carries over unchanged from the 2026-09-08 design

Its decisions still hold and are not re-argued here:

- Levels and commands get **no new history store**. `decision_log`
  already persists every inbound `TradeDecision` and `ForceAction` in
  order. `current_levels`/`current_command` stay a derived read-cache
  that `log_decision` upserts as a side effect of the write it already
  does — no new call sites in `execution`.
- Analysis snapshots get the **current + log** treatment, two stores,
  written by one `persist_analysis` call.
- Analysis values stay **opaque bytes**. `state_store` does not parse
  them; freshness policy belongs to the caller.
- Order book persistence stays **out of scope** — that is L1's.

## Decisions specific to the Postgres backend

**`last_reconciliation` stays in memory.** A `Mutex<Option<Report>>` on
`StateStoreImpl`, process-lifetime, never persisted — as
[07-L5-state-store.md](../plans/07-L5-state-store.md)'s 2026-09-11 update
already settled. No table, no migration, lost on restart by design.

**`event_log` needs no migration.** `migrations/0001_init.sql` already
creates the table (`seq`, `pair`, `event` jsonb, `recorded_at`), created
but unused. Only the Rust methods are missing. It does need an index —
see below.

**Readers return `Result<Option<T>, StoreError>`, not bare `Option<T>`.**
The sled implementation wrote `self.tree.get(key).ok()??`, which collapses
"the stored row is corrupt" and "the database is unreachable" into the
same `None`. The spec asks only for the first: corrupt or missing rows
read as absent. An unreachable database reporting "no value" would be a
lie that callers cannot distinguish from a genuine cache miss. So decode
failure yields `Ok(None)`; connection or query failure yields `Err`.

**Every method is `async`.** The whole `StateStore` trait is
`#[async_trait]` on the Postgres backend; the sled originals were sync.

**Multi-table writes are one transaction.** `log_decision` writes
`decision_log`, `current_command` and (for `Decision` records)
`current_levels` in a single transaction; `persist_analysis` writes
`analysis_current` and `analysis_log` in another. Synchronous durability
is unchanged — commit before return, no batching, the deliberate opposite
of L1's batching writer.

**`current_levels` is row-per-level, not a jsonb blob.** The 2026-09-08
design stored `(Vec<LevelDto>, Ts)` as one sled value because sled cannot
query inside a value. Postgres can, and levels are the thing an operator
most wants to read directly, so each level gets its own row with its name
and value in real columns. The whole set for a pair is replaced on every
`Decision` — delete-then-insert inside `log_decision`'s transaction.

## The two dropped wire fields

L4 already decodes both of these from main/ and then throws them away,
because the domain types have nowhere to put them. `wire.rs`'s module doc
and a test named
`levels_kind_is_accepted_on_decode_but_dropped_mapping_into_level` both
document the loss. Storing levels by name requires un-dropping them.
Neither the wire format nor main/ changes.

```rust
// mq_gateway::wire — today
struct LevelDto { kind: LevelKindDto, price: Decimal }  // kind: #[allow(dead_code)]
enum LevelKindDto { Support, Resistance, Target, StopLoss }
struct ForceActionPayload { pair: String, reason: String }  // reason: #[allow(dead_code)]
```

**`LevelKind` moves into the domain, as an optional field on `Level`.**

```rust
// local_analysis::types
pub enum LevelKind { Support, Resistance, Target, StopLoss }
pub struct Level {
    pub price: Price,
    pub source: LevelSource,      // unchanged: Wall(Side) | Main
    pub kind: Option<LevelKind>,  // new
}
```

`LevelKind` is `Copy`, so `Level` stays `Copy`.

The obvious alternative — folding the kind into `LevelSource::Main(LevelKind)`
— is better-typed and was rejected anyway, because `LevelSourceDto::Main`
is a **unit variant already serialized into `decision_log.record` jsonb**.
Turning it into a tuple variant makes every row written before this change
undecodable, and `pg.rs`'s `CorruptRow` policy would then either skip those
rows silently (`read_decision_log`) or hard-error (`PgStateReader`). An
`Option` on `Level` decodes legacy rows cleanly as `None` and needs no
compat shim in the DTO.

The cost is explicit: the type now permits a `Wall` carrying a main/ kind,
an impossible state the compiler no longer rejects. `Level::wall(..)` is
the only constructor that builds walls and always sets `kind: None`, and
the field carries a doc comment saying so — convention, not enforcement.

Call-site impact is smaller than the alternative's: `Level::main(price)`
keeps working (12 sites unchanged, `kind: None`), and a new
`Level::main_with_kind(price, kind)` is what `wire.rs` uses.

**`ForceAction` gains the comment.**

```rust
// execution::types
pub struct ForceAction { pub id: DecisionId, pub pair: Pair, pub kind: ForceKind,
                         pub comment: String }
```

7 construction sites. `wire.rs` maps `reason` into it instead of
discarding it; `encode_force_close` already takes a `reason` argument.

## Data model

New migration `0003_state_store_caches.sql`; `db_schema::SCHEMA_VERSION`
goes 2 → 3 (`visualizer_server`'s `check_schema` asserts the two agree).

```sql
CREATE TABLE current_levels (
    seq         bigint PRIMARY KEY DEFAULT nextval('global_ins_seq'),
    pair        text    NOT NULL,
    name        text,               -- support | resistance | target | stop_loss;
                                    -- NULL when the level carried no kind
    value       numeric NOT NULL,   -- the price
    extra_text  text,               -- nullable; no producer yet, see below
    received_at bigint  NOT NULL
);
CREATE INDEX ON current_levels (pair);

CREATE TABLE current_command (
    pair        text PRIMARY KEY,
    record      jsonb  NOT NULL,
    comment     text,               -- ForceAction.comment; NULL for decisions
    received_at bigint NOT NULL
);

CREATE TABLE analysis_current (
    pair        text    NOT NULL,
    kind        text    NOT NULL,
    value       bytea   NOT NULL,
    computed_at bigint  NOT NULL,
    PRIMARY KEY (pair, kind)
);

CREATE TABLE analysis_log (
    seq         bigint PRIMARY KEY DEFAULT nextval('global_ins_seq'),
    pair        text    NOT NULL,
    kind        text    NOT NULL,
    value       bytea   NOT NULL,
    computed_at bigint  NOT NULL
);
CREATE INDEX ON analysis_log (pair, kind, computed_at, seq);

-- event_log exists since 0001 but has no index; read_event_log ranges
-- over (pair, recorded_at) and would seq-scan without one.
CREATE INDEX ON event_log (pair, recorded_at, seq);
```

`analysis_*.value` is `bytea`, not `jsonb`: "opaque bytes the store does
not parse" only survives as `bytea`. `jsonb` would force every caller to
produce valid JSON and would let Postgres reject a payload `state_store`
promised not to inspect.

`current_levels` uses `global_ins_seq` for its primary key so rows written
in one transaction keep their relative order under the same sequence every
other append-only table shares.

### Two columns with no producer today

Both are honest gaps, recorded here so nobody later reads them as an
oversight:

- **`current_command.comment` is populated only for `Force` records.**
  `TradeDecisionPayload` on the wire is `{pair, side, timeframe, levels}`
  — a decision carries no comment or reason. Decision rows write NULL
  until main/ sends one.
- **`current_levels.extra_text` has no producer at all.** `name` now
  carries the semantic label and the wire's `LevelDto` is `{kind, price}`
  — there is nothing else per level to store. The column exists for
  annotation main/ may send later; it is NULL until then.

## Interface

Added to the `StateStore` trait, all `async`:

```rust
async fn log_event(&self, pair: Pair, event: PositionStateEvent, received_at: Ts)
    -> Result<(), StoreError>;
async fn read_event_log(&self, pair: Pair, from: Ts, to: Ts)
    -> Result<EventLogStream, StoreError>;
fn last_reconciliation(&self) -> Option<ReconciliationReport>;   // in-memory, sync
async fn current_levels(&self, pair: Pair)
    -> Result<Option<(Vec<Level>, Ts)>, StoreError>;
async fn current_command(&self, pair: Pair)
    -> Result<Option<(DecisionRecord, Ts)>, StoreError>;
async fn persist_analysis(&self, pair: Pair, kind: String, value: Vec<u8>, computed_at: Ts)
    -> Result<(), StoreError>;
async fn current_analysis(&self, pair: Pair, kind: String)
    -> Result<Option<(Vec<u8>, Ts)>, StoreError>;
async fn read_analysis_log(&self, pair: Pair, kind: String, from: Ts, to: Ts)
    -> Result<AnalysisLogStream, StoreError>;
```

`read_event_log` and `read_analysis_log` return `Result<Stream>` for the
same reason `read_decision_log` already does: the `Result` reports a
failure to issue the query, the stream yields bare items.

`last_reconciliation` stays synchronous — it reads a `Mutex`, not the
database.

## Error handling

Unchanged from the spec: corrupt or missing rows in `current_levels`,
`current_command`, `analysis_current` and `analysis_log` are treated as
absent, never as a hard failure — a cache that cannot be decoded is a
cache miss, and the caller recomputes. Query and connection failures are
`Err`, per the reader-signature decision above.

## Testing

DB-backed, so every test runs under `docker compose run --rm test`. The
sled branch's 16 tests port across:

- events read back unchanged and ordered by `received_at`;
  `read_event_log` never returns another pair's events
- `last_reconciliation` is `None` before any `reconcile`, matches the most
  recent one, and is unaffected by `persist`/`log_decision`
- `log_decision(Decision)` populates both `current_levels` and
  `current_command`; `log_decision(Force)` populates `current_command`
  only, with its comment
- a second `log_decision` for a pair overwrites the cache without
  disturbing `decision_log`; caches never collide across pairs
- `persist_analysis` round-trips through `current_analysis`; a second call
  overwrites current but appends to the log; kinds and pairs never collide
- `read_analysis_log` filters by time range

New beyond the port:

- a level's `name` round-trips from the wire `kind` through
  `current_levels` and back — the case `wire.rs` currently has a test
  asserting is *lost*
- `db_schema`'s `l5_tables_exist_with_their_expected_columns` covers the
  four new tables, and `the_schema_version_constant_matches_the_highest_applied_migration`
  covers the bump to 3

## Out of scope

- **`read_wall_log`.** The L5 spec lists it alongside these additions, but
  the `state-store-expansion` branch never implemented it, and the spec
  itself notes wall_log should collapse into `analysis_log` with
  `kind = "walls"` once both land. Left for the wall-visualisation work.
- **A comment on `TradeDecision`.** Needs a wire-format field and a main/
  change; `current_command.comment` is ready for it.
- **Any consumer of these caches.** `execution` and `visualizer_backend`
  read them per the spec, but no call sites exist yet on any branch; this
  change lands the store side only.
