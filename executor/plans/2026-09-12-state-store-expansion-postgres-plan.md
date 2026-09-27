# state_store expansion — Postgres rebuild plan

Implements
[2026-09-12-state-store-expansion-postgres-design.md](../specs/2026-09-12-state-store-expansion-postgres-design.md).
Base: `layer-implementation` @ `c0c1607`. Target branch:
`state-store-expansion-postgres` (already created off that base, empty).

## Branch note

Worktree `.worktrees/state-store-expansion` sits on the OLD sled-backed
`state-store-expansion` branch — diverged from `layer-implementation` at a
common ancestor before the Postgres migration landed, unrelated history,
unsalvageable. Its one unstaged change (`crates/cli/src/lib.rs`, sync/
`Option`-returning stub methods) is against that stale sled trait, not this
design — left untouched. This plan's work happens in
`.worktrees/layer-implementation`, on branch `state-store-expansion-postgres`
(already checked out there, clean, 0 files ahead of `layer-implementation`
today).

## Step 0 — Docker entry point (unchanged)

`docker compose run --rm test` already runs `cargo test --workspace`. No new
entry point. Every step below is verified through it before moving to the
next step.

## Step 1 — Migration + schema version (RED first)

- `db_schema/tests/migrations.rs`: extend the L5 table list to the 4 new
  tables and extend `l5_tables_exist_with_their_expected_columns` to assert
  their columns and `analysis_*.value` is `bytea` — written first, RED
  against migration 0002 alone.
- `migrations/0003_state_store_caches.sql`: `current_levels`,
  `current_command`, `analysis_current`, `analysis_log` + the 3 indexes
  (including the missing `event_log (pair, recorded_at, seq)` index) —
  verbatim SQL is already in the design's "Data model" section.
- `db_schema::SCHEMA_VERSION` 2 → 3.
- `the_schema_version_constant_matches_the_highest_applied_migration` stays
  green as part of this same step.

## Step 2 — Domain types (interface first)

- `local_analysis::types`: `LevelKind` enum (`Support | Resistance | Target |
  StopLoss`, `Copy`), `Level.kind: Option<LevelKind>`, new
  `Level::main_with_kind(price, kind)`. `Level::wall`/`Level::main` keep
  `kind: None` (doc comment says so, not enforced).
- `execution::types::ForceAction`: add `comment: String`. Update all 5
  construction sites: `execution/src/tests.rs`, `mq_gateway/src/wire.rs`,
  `state_store/src/dto.rs` (×2: the `From` impl and its round-trip test),
  `state_store/tests/pg_store.rs`. (Design doc says 7 sites — verified by
  grep there are only 5 on this branch; use the real count.)
- Expected to break compilation everywhere until Step 3/4 finish threading
  the new fields through — mechanical, stays inside this one step.

## Step 3 — wire.rs stops dropping kind/reason

- `LevelKindDto -> LevelKind` conversion; `LevelDto -> Level` becomes
  `Level::main_with_kind(l.price, l.kind.into())`.
- `ForceActionPayload.reason` maps into `ForceAction.comment` in the
  `ForceClose` decode arm; drop both `#[allow(dead_code)]` markers.
- Rewrite `levels_kind_is_accepted_on_decode_but_dropped_mapping_into_level`
  as `..._is_carried_into_level` — asserts `Some(LevelKind::StopLoss)`, not a
  drop.

## Step 4 — state_store::dto

- `LevelDto` gains `kind: Option<LevelKindDto>`; `ForceActionDto` gains
  `comment: String`. Thread both directions of the `From` impls; existing
  round-trip tests keep passing once the fields are wired.
- New `PositionStateEventDto` (mirrors all 6 `PositionStateEvent` variants)
  for `event_log`'s payload — same pattern as the other DTOs in this file.

## Step 5 — StateStore trait

Add to `crates/state_store/src/lib.rs`, per the design's Interface section:
`log_event`, `read_event_log`, `last_reconciliation` (sync), `current_levels`,
`current_command`, `persist_analysis`, `current_analysis`,
`read_analysis_log`. New stream aliases `EventLogStream`,
`AnalysisLogStream` alongside the existing `DecisionLogStream`.

## Step 6 — pg.rs (RED pg_store test per method, then GREEN)

Port the sled branch's 16 tests (design's Testing section) into
`pg_store.rs`:

- `log_event`/`read_event_log`: insert/select against the already-migrated
  `event_log` table via `PositionStateEventDto`; corrupt/missing rows are
  skipped (no reader counterpart exists yet, so one policy, not a
  Skip/Surface split).
- `last_reconciliation`: `Mutex<Option<ReconciliationReport>>` field on
  `StateStoreImpl`, set at the end of `reconcile`, sync getter, never
  persisted.
- `current_levels`/`current_command`: `log_decision` becomes one transaction
  — insert `decision_log`, then (Decision only) delete+insert
  `current_levels` rows and upsert `current_command` (`comment` populated
  only for Force), commit. Readers return `Result<Option<(T, Ts)>,
  StoreError>` — corrupt or missing both decode to `Ok(None)`, a new, simpler
  helper shape distinct from the existing `CorruptRow` enum (design is
  explicit this reader signature is new).
- `persist_analysis`/`current_analysis`/`read_analysis_log`: one transaction
  writes `analysis_current` (upsert on `(pair, kind)`) and `analysis_log`
  (append); readers use the same `Ok(None)`-on-corrupt shape.
- New tests beyond the port: a level's `name` round-trips through
  `current_levels`; `db_schema`'s two Step-1 tests.

## Step 7 — cli::FakeStore mock

Add the 8 new async/`Result`-returning stub arms to `crates/cli/src/lib.rs`'s
test-only `impl StateStore for FakeStore` — mechanical, matches the trait.

## Step 8 — Full verification

`docker compose run --rm test` (whole workspace) green: `db_schema`,
`state_store` (dto unit tests + pg_store integration tests), `mq_gateway`
(wire tests), `execution`, `cli`.

## Explicitly out of scope (per design)

`read_wall_log`; a comment field on `TradeDecision`; any real consumer
(`execution`/`visualizer_backend`) of the new caches — store side only.
