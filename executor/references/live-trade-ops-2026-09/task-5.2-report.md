# Task 5.2 report: Migration 0008 — order journal tables

## Fix round 1/5 (2026-09-24)

**Finding (Important):** the migration header comment
(`migrations/0008_order_journal.sql`) and the test
`dashboard_role_can_select_but_not_insert_on_the_order_journal_tables`
both claimed to prove `docker/initdb.d/00-roles.sql`'s `public`-schema
`ALTER DEFAULT PRIVILEGES` covers the new tables. That test actually runs
through `test_support::test_db()`, which scopes every test to its own
private `t_<uuid>` schema and issues its **own**
`ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT ON TABLES TO
dashboard` there (`crates/test_support/src/lib.rs`), precisely because
the compose init script only grants in `public`. The test would have
kept passing unchanged even if `00-roles.sql`'s grant were narrowed,
broken, or deleted outright — only the manual one-off container check
from the original report touched the real mechanism, and CI never
repeats it.

**Chose:** the reviewer's preferred option — add a check that exercises
the real `public`-schema path, since it didn't require contorting
`test_support` at all.

**Fix:**

- Added `dashboard_role_can_select_but_not_insert_on_the_real_public_schema_order_journal_tables`
  (`crates/db_schema/tests/migrations.rs`), which deliberately bypasses
  `test_support::test_db()`:
  - reads `TEST_DATABASE_URL` directly and runs `db_schema::MIGRATOR`
    against it with **no** `search_path` override — the real `public`
    schema, connected as the same `executor` role
    `docker compose run --rm executor --migrate-only` uses, so
    `00-roles.sql`'s `FOR ROLE executor` grant actually applies to the
    tables created;
  - connects as `dashboard` with Postgres's own default search_path (a
    small local `dashboard_url_on_public_schema` helper does the
    credential swap; `test_support`'s own equivalent helpers are private
    to that crate) and proves SELECT succeeds, INSERT is denied;
  - the insert is `ON CONFLICT (client_order_id) DO NOTHING` so
    re-running this test against the same persistent `public` schema
    (the `postgres` service's volume, unlike every other test's private
    schema) never collides with an earlier run's row.
- Reworded the existing schema-scoped test's comment and the migration's
  header comment to say precisely what each does and does not prove, so
  neither overclaims regardless of which test a future reader looks at
  first.
- Reset this worktree's own `trader_pgdata` volume state before
  re-verifying: the original task-5.2 verification had already run
  `docker compose run --rm executor --migrate-only` against this
  scratch volume's `public` schema with the *pre-fix* file content, so
  `_sqlx_migrations` held the old checksum for version 8. Editing the
  file's comments (no SQL statement changed) would otherwise make sqlx
  refuse to reapply it ("migration 8 was previously applied but has been
  modified"). Dropped `exchange_order`/`exchange_fill` and deleted the
  version-8 row from `_sqlx_migrations` via `psql` — this is my own
  local, not-yet-shared scratch state from this task's own prior
  verification step, not a shared/production database, and no volume,
  container or branch was deleted to do it.

**Verification:**

```
docker compose run --build --rm test cargo test -p db_schema --no-fail-fast
```
→ `test result: ok. 24 passed; 0 failed; ...` (was 23; the new test
brings it to 24).

Ran the new test alone a second time immediately after, to prove the
idempotency claim in its own comment:
```
docker compose run --rm test cargo test -p db_schema --no-fail-fast \
  dashboard_role_can_select_but_not_insert_on_the_real_public_schema
```
→ `test result: ok. 1 passed; 0 failed; ...` both times.

Then the full workspace gate:
```
docker compose run --build --rm test cargo test --workspace --no-fail-fast
```
→ exit code 0; no `FAILED` line and no `error[` anywhere in the log; 48
`test result: ok` blocks, zero `test result: FAILED`.

**Files touched:** `migrations/0008_order_journal.sql` (comment only —
no `CREATE TABLE`/index/constraint text changed),
`crates/db_schema/tests/migrations.rs`.

**Commit:** `151e54c fix(db): prove the dashboard grant against the real
public schema (review round 1/5)`.

---

## Status: DONE

## What was implemented

1. `migrations/0008_order_journal.sql` — new, additive migration creating
   `exchange_order` and `exchange_fill`, column-for-column against spec §4.7
   (`external/executor/specs/2026-09-22-live-trade-ops-l0-test-design.md`),
   plus the two indexes (`exchange_order (origin, status)`,
   `exchange_order (run_id)`) and the `CHECK` on `exchange_order.status`.
2. `crates/db_schema/src/lib.rs`: `SCHEMA_VERSION` 7 → 8, plus a doc-comment
   entry for the new migration file (matching the existing style that lists
   every migration and what it's for).
3. `crates/db_schema/tests/migrations.rs`: 8 new tests covering columns/types,
   both primary keys, the status `CHECK`'s accept/reject set, the compound
   `UNIQUE` key's NULL-tolerant-vs-duplicate-rejecting behaviour, the
   `exchange_fill → exchange_order` foreign key (+ its own `(exchange,
   trade_id)` primary key), the two required indexes (asserted by
   definition, not just by name), and the `dashboard` role's
   SELECT-yes/INSERT-no split. No production crate touched; `state_store`
   untouched.
4. Incidental fix: `Cargo.lock` was out of sync with
   `crates/live_trade_ops/Cargo.toml` (task 5.1, commit `0ff3fa4`, added
   `async-trait`/`futures-util`/`rust_decimal`/`serde`/`serde_json`/`tokio`
   as deps but never regenerated the lockfile's own dependency list for that
   crate). Plain `cargo test --workspace` never notices (no `--locked`), but
   the release Dockerfile's `cargo build --release --locked` does, and it
   blocked this task's own required "migrates against a fresh database"
   Docker gate. Fixed as a separate commit — no version bumps, purely
   recording resolved dependencies already in use.

## Pre-task check: spec vs `JournalStatus` (per "Before You Begin")

Compared spec §4.7's `status` column comment (`intent |
submitted_unknown | new | partially_filled | filled | cancelled |
rejected`) against `crates/live_trade_ops/src/journal/mod.rs`'s
`JournalStatus` enum (`Intent, SubmittedUnknown, New, PartiallyFilled,
Filled, Cancelled, Rejected`). Both lists have exactly the same seven
values in the same order once snake-cased. No disagreement — proceeded
without stopping to ask.

## TDD evidence

**RED** — `docker compose run --build --rm test cargo test -p db_schema
--no-fail-fast` run with the 8 new tests added to `migrations.rs` but
`SCHEMA_VERSION` already bumped to 8 and **no** `migrations/0008_order_journal.sql`
file yet:

```
test exchange_order_status_check_constraint_accepts_exactly_the_seven_journal_statuses ... FAILED
test exchange_order_and_exchange_fill_columns_match_spec_4_7 ... FAILED
test exchange_fill_references_exchange_order_and_is_keyed_by_exchange_and_trade_id ... FAILED
test exchange_order_unique_key_is_exchange_market_kind_exchange_order_id ... FAILED
test dashboard_role_can_select_but_not_insert_on_the_order_journal_tables ... FAILED
test exchange_order_has_the_origin_status_and_run_id_indexes_unfinished_needs ... FAILED
test exchange_order_and_exchange_fill_have_primary_keys ... FAILED
test the_schema_version_constant_matches_the_highest_applied_migration ... FAILED
...
test result: FAILED. 15 passed; 8 failed; 0 ignored; 0 measured; 0 filtered out; finished in 3.72s
```

Representative failure — `relation "exchange_order" does not exist`
(`code: "42P01"`) for every test that touches the new tables, and
`left: 7, right: 8` for the version-constant test. Exactly the expected RED:
every failure traces to "the migration doesn't exist yet", nothing else.

**GREEN** — after adding `migrations/0008_order_journal.sql`:

```
docker compose run --build --rm test cargo test -p db_schema --no-fail-fast
...
test result: ok. 23 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 2.72s
```

All 23 `db_schema` tests (15 pre-existing + 8 new) pass.

## Workspace gate

```
docker compose run --build --rm test cargo test --workspace --no-fail-fast
```

Exit code 0. Every `test result:` line across the whole run reports `0
failed` (grepped the full log: no `FAILED` anywhere, no `error[`). The
known flake, `market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database`,
passed in this run; re-ran it in isolation (`cargo test -p market_data
--test write_path shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database
-- --test-threads=1`) and it passed there too.

## Fresh-database migration check

Confirmed the database was genuinely fresh before running the gate:

```
$ docker compose up -d postgres
$ docker compose exec -T postgres psql -U executor -d trader -c "\dt"
Did not find any relations.
$ docker compose exec -T postgres psql -U executor -d trader -c "SELECT ... FROM _sqlx_migrations ..."
ERROR:  relation "_sqlx_migrations" does not exist
```

The `public` schema of this worktree's `trader_pgdata` volume had never
been touched by `db_schema::MIGRATOR` before (all test-suite migrations run
in per-test schemas via `test_support`, never `public`). Then:

```
$ docker compose run --build --rm executor --migrate-only
...
migrations applied: latest migration version 8, db_schema::SCHEMA_VERSION 8
```

(exit 0). Verified directly against the container afterward:

- `\d exchange_order` / `\d exchange_fill` — every column, type, the
  status `CHECK`, the compound `UNIQUE`, both indexes, the PKs and the FK
  are exactly as specified.
- `SELECT version FROM _sqlx_migrations ORDER BY version;` → `1..8`, all
  eight applied, none skipped.
- `psql -U dashboard -d trader -c "SELECT count(*) FROM exchange_order;"`
  → `0` (succeeds).
- `psql -U dashboard -d trader -c "INSERT INTO exchange_order (...) VALUES (...)"`
  → `ERROR: permission denied for table exchange_order`.

This proves the `dashboard` role's access on the *real* roles/grants setup
(`docker/initdb.d/00-roles.sql`), not just the test harness's per-schema
grant — the migration adds no `GRANT` statement and none was needed.

`docker compose down` (no `-v`) afterward to release the containers; the
`trader_pgdata` volume itself was left alone (not a destructive command,
no prune/volume removal).

## Files changed

- `migrations/0008_order_journal.sql` (new)
- `crates/db_schema/src/lib.rs`
- `crates/db_schema/tests/migrations.rs`
- `Cargo.lock` (separate commit, incidental fix — see above)

## Self-review findings

- Column list, types, order: matches spec §4.7 exactly for both tables,
  including `stop_price`, `reject_reason`/`reject_code`/`reject_message`,
  `run_id`, and the `filled_qty NOT NULL DEFAULT 0`.
- `status` `CHECK` lists exactly `JournalStatus`'s seven variants,
  snake-cased, comment cites the source of truth (journal/mod.rs) the same
  way 0002 cites `order_status_to_db`/`db_to_order_status`.
- `exchange_order_id` is `text`; `UNIQUE (exchange, market_kind,
  exchange_order_id)` present and proven to tolerate multiple NULLs
  (un-acked intents) while rejecting a genuine duplicate triple, and to
  distinguish by `market_kind` (not just `exchange_order_id` alone).
- `exchange_fill` FK to `exchange_order(client_order_id)` and its own
  `(exchange, trade_id)` primary key both proven by test (orphan fill
  rejected; duplicate `(exchange, trade_id)` rejected).
- Both required indexes present, asserted by index *definition*
  (`pg_indexes.indexdef`), not just by name — same rigor as the existing
  `read_path_indexes_cover_the_queries_the_readers_actually_run` test.
- `SCHEMA_VERSION` bumped and its existing test (unchanged) still passes.
- `dashboard` SELECT/no-INSERT proven both in the automated test suite
  (schema-scoped harness) and manually against the real running container
  with the real `docker/initdb.d/00-roles.sql` roles — belt and suspenders.
- No migration 0001–0007 touched; `state_store` untouched; no production
  crate behaviour changed; `cargo fmt` not run.
- Did not implement `PgOrderJournal` (task 5.3, out of scope here).
- One thing worth flagging rather than silently fixing further: the
  `Cargo.lock` drift (see above) was pre-existing from task 5.1 and unrelated
  to this task's schema work, but blocked this task's own required Docker
  verification step, so it's fixed as its own commit rather than folded
  silently into the schema commit or left for a later task to trip over
  again.

## Concerns

None blocking. The `Cargo.lock` fix is the only change outside this
task's literal file list (`migrations/0008_order_journal.sql`,
`db_schema/src/lib.rs`, `db_schema/tests/migrations.rs`); it's mechanical,
zero-version-change, and was necessary to actually run the migration gate
this task itself requires — flagging it here rather than hiding it.
