# Task 5.3 report: `PgOrderJournal`

## Status: DONE

## What was implemented

1. `crates/live_trade_ops/src/journal/pg.rs` (new) — `PgOrderJournal`,
   `sqlx` directly against `exchange_order`/`exchange_fill` (migration
   `0008_order_journal.sql`, task 5.2, untouched). Implements the
   `OrderJournal` trait from task 5.1's `journal/mod.rs`, reusing its
   `check_transition`/`rank`/`from_order_status` helpers rather than
   re-deriving the forward-only ladder in SQL.
   - `record_intent`: a single `INSERT` with no explicit transaction, so
     it auto-commits before `execute` returns `Ok` — the property
     `JournaledAccount::place_order` depends on. Duplicate
     `client_order_id` → `sqlx::Error::Database` with SQLSTATE `23505`
     (primary-key violation) → `JournalError::Write`.
   - `record_ack` / `record_submit_unknown` / `record_rejection` /
     `record_status`: each opens a transaction, `SELECT status ... FOR
     UPDATE` the row, runs `check_transition`, and only on success issues
     the `UPDATE` and commits. On refusal (`BackwardTransition` or no
     such row) the transaction is dropped uncommitted (`sqlx::Transaction`
     rolls back on drop), so the stored row is left exactly as it was.
     `PgOrderJournal::new`'s `alerts: Arc<dyn Alerts>` parameter (pinned
     by the brief) fires an alert on every refused backward transition,
     independent of whatever `JournaledAccount` layered on top also does.
   - `record_fills`: idempotent via the table's own `(exchange, trade_id)`
     primary key, `ON CONFLICT DO NOTHING`, whole batch in one
     transaction. `exchange` is read from the order's own row rather than
     threaded through the call, matching `MemoryJournal`'s `exchange_key`.
   - `get` / `unfinished`: decode every column through a typed
     `db_to_*`/`Result` path — no `unwrap`/`panic!` on what the database
     returns. `unfinished` filters on `status NOT IN ('filled',
     'cancelled', 'rejected')`, matching `MemoryJournal`'s `rank(status) <
     4`.
   - `fills`: joins back to `exchange_order` to recover `pair`/`side`
     exactly (the frozen `exchange_fill` schema has no columns of its
     own for them); `order_id` is parsed from the acked
     `exchange_order_id` text when numeric, else `OrderId(0)` — see the
     "Two fields the frozen schema does not carry" note below.
   - Every numeric column is `Decimal` end to end (`price`, `stop_price`,
     `qty`, `filled_qty`, `avg_fill_price`, and every `exchange_fill`
     money column) — never `f64`.
2. `crates/live_trade_ops/src/journal/mod.rs`: wired `pub mod pg;` +
   `pub use pg::PgOrderJournal;` alongside the existing `memory` wiring.
3. `crates/live_trade_ops/tests/pg_journal.rs` (new) — 9 integration
   tests against a real Docker Postgres (`TEST_DATABASE_URL`, per-test
   schema via `test_support::test_db()` + `db_schema::MIGRATOR`, same
   pattern as `state_store/tests/pg_store.rs`):
   - `every_trait_method_round_trips`
   - `record_intent_has_committed_before_it_returns_seen_from_a_second_connection`
     — reads the row from a **second, independent** `PgPool::connect`,
     never a clone of the journal's own pool.
   - `duplicate_client_order_id_on_record_intent_is_a_write_error`
   - `filled_to_new_is_refused_and_leaves_the_stored_row_untouched` — also
     asserts the alert fired exactly once.
   - `new_then_partially_filled_then_filled_is_accepted`
   - `record_fills_twice_with_the_same_trade_id_produces_one_row` — plus a
     direct `SELECT count(*)` against `exchange_fill`, independent of how
     `fills()` itself decodes rows.
   - `unfinished_filters_exchange_origin_and_terminal_status`
   - `parity_memory_and_pg_journals_agree_on_a_scripted_sequence` — one
     script (`run_script`) exercising every `OrderJournal` method
     (`record_intent`, `record_ack`, `record_submit_unknown`,
     `record_status`, `record_fills` incl. a replayed trade id,
     `record_rejection`) run against both `MemoryJournal` and
     `PgOrderJournal`, then `get`/`fills`/`unfinished` compared for exact
     equality.
   - `journaled_account_over_pg_journal_has_committed_the_intent_row_before_the_fake_is_entered`
     — a `MarketAccount` fake whose own `place_order` body queries the row
     (from a second connection) and asserts it is already there,
     `status = 'intent'`, before doing anything else.
4. `crates/live_trade_ops/Cargo.toml`: added `sqlx` (same feature set as
   `state_store`/`db_schema`, minus `migrate`) and `url` as regular
   dependencies; `db_schema` and `test_support` as dev-dependencies (for
   `tests/pg_journal.rs` only). `state_store` is not touched anywhere.
5. `Cargo.lock`: regenerated (`cargo metadata`, no `--locked`, on the
   host) so it lists `live_trade_ops`'s new dependency edges
   (`sqlx`/`url`/`db_schema`/`test_support`) — a 4-line diff, all
   pre-existing pinned versions elsewhere in the workspace, no version
   bumps. Same class of incidental fix task 5.2 called out: plain
   `cargo test --workspace` inside the Docker `test` image never notices
   a stale lockfile (no `--locked`), but leaving it stale would still be
   wrong to commit.

## Two fields the frozen schema does not carry (documented in pg.rs, not a bug)

Migration `0008` (frozen, matches spec §4.7's own table exactly) has no
column for `Rejection::http_status`, and `exchange_fill` has no
`pair`/`side`/`order_id` columns of its own:
- `get()`'s reconstructed `Rejection` always has `http_status: None`,
  even if the original had `Some(_)`. Every other field
  (`reason`/`code`/`message`) round-trips exactly.
- `fills()` recovers `pair`/`side` exactly via a join back to the parent
  `exchange_order` row (a fill always belongs to that order's own pair
  and side, so this is a join, not a guess). `order_id` has no natural
  source — `exchange_order_id` is `text` (MEXC ids are strings) where
  `Fill::order_id` is `u64` — so it's parsed from the acked id when
  numeric, else `OrderId(0)`. This never affects `settle`/the harness's
  settlement check, which never reads `Fill::order_id`.

The test fixtures avoid exercising these two lossy paths in ways that
would make the parity test fail for a reason unrelated to the code under
test: `rejection()`'s fixture uses `http_status: None`, and every scripted
`Fill`'s `order_id`/`pair`/`side` matches its order's own values (which
is also how any real fill actually looks). `ResolvedNetwork::Custom(Url)`
is similarly out of scope for these tests for the same reason (the schema
stores only the fixed tag `"custom"`, never the URL) — every fixture uses
`Mainnet`.

## TDD evidence

**RED** — `crates/live_trade_ops/src/journal/pg.rs` temporarily replaced
with a stub (`PgOrderJournal` struct/constructor unchanged, every trait
method body `todo!("RED stub")`), same file layout, tests untouched:

```
docker compose run --build --rm test cargo test -p live_trade_ops --test pg_journal --no-fail-fast
```
```
running 9 tests
test record_fills_twice_with_the_same_trade_id_produces_one_row ... FAILED
test new_then_partially_filled_then_filled_is_accepted ... FAILED
test record_intent_has_committed_before_it_returns_seen_from_a_second_connection ... FAILED
test parity_memory_and_pg_journals_agree_on_a_scripted_sequence ... FAILED
test unfinished_filters_exchange_origin_and_terminal_status ... FAILED
test duplicate_client_order_id_on_record_intent_is_a_write_error ... FAILED
test filled_to_new_is_refused_and_leaves_the_stored_row_untouched ... FAILED
test every_trait_method_round_trips ... FAILED
test journaled_account_over_pg_journal_has_committed_the_intent_row_before_the_fake_is_entered ... FAILED
...
thread '...' panicked at crates/live_trade_ops/src/journal/pg.rs:29:9:
not yet implemented: RED stub
test result: FAILED. 0 passed; 9 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.15s
```
All 9 failed for exactly the expected reason (the real implementation
doesn't exist yet), nothing else.

**GREEN** — real implementation restored:

```
docker compose run --build --rm test cargo test -p live_trade_ops --test pg_journal --no-fail-fast
```
```
running 9 tests
test filled_to_new_is_refused_and_leaves_the_stored_row_untouched ... ok
test every_trait_method_round_trips ... FAILED   <- see below
test unfinished_filters_exchange_origin_and_terminal_status ... ok
test record_fills_twice_with_the_same_trade_id_produces_one_row ... ok
test journaled_account_over_pg_journal_has_committed_the_intent_row_before_the_fake_is_entered ... ok
test parity_memory_and_pg_journals_agree_on_a_scripted_sequence ... FAILED   <- see below
test new_then_partially_filled_then_filled_is_accepted ... ok
test record_intent_has_committed_before_it_returns_seen_from_a_second_connection ... ok
test duplicate_client_order_id_on_record_intent_is_a_write_error ... ok
test result: FAILED. 7 passed; 2 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.17s
```

This GREEN attempt caught a real bug: `record_intent` bound a
freshly-computed `now_ms()` for **both** `created_at` and `updated_at`
(`$14` reused for both placeholders), instead of the caller's own
`OrderIntent::created_at`. Both failing assertions were exactly this —
`created_at` came back as "now" instead of the scripted fixed timestamp.
Fixed by binding `intent.created_at` to its own placeholder
(`ts_to_i64(intent.created_at)`) and `now_ms()` only to `updated_at`
(`$14`/`$15` instead of `$14`/`$14`). Re-ran:

```
docker compose run --build --rm test cargo test -p live_trade_ops --test pg_journal --no-fail-fast
```
```
running 9 tests
test new_then_partially_filled_then_filled_is_accepted ... ok
test parity_memory_and_pg_journals_agree_on_a_scripted_sequence ... ok
test record_intent_has_committed_before_it_returns_seen_from_a_second_connection ... ok
test filled_to_new_is_refused_and_leaves_the_stored_row_untouched ... ok
test journaled_account_over_pg_journal_has_committed_the_intent_row_before_the_fake_is_entered ... ok
test record_fills_twice_with_the_same_trade_id_produces_one_row ... ok
test every_trait_method_round_trips ... ok
test unfinished_filters_exchange_origin_and_terminal_status ... ok
test duplicate_client_order_id_on_record_intent_is_a_write_error ... ok
test result: ok. 9 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.22s
```

Self-review (see below) then found the parity script never called
`record_submit_unknown`; extended `run_script` with a fourth order (`c4`,
never acked, `record_submit_unknown` instead) and re-ran — still green
(shown in the workspace-gate section below).

## Workspace gate

```
docker compose run --build --rm test cargo test --workspace --no-fail-fast
```
Run twice (once before, once after the `run_script`/Cargo.lock fixes).
Final run: exit code 0; 49 `test result: ok` blocks; zero `FAILED`, zero
`panicked`, zero `error[` anywhere in the log.
`market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database`
(the known flake, TECH_DEBT §5) passed in this run.

## Files changed

- `crates/live_trade_ops/src/journal/pg.rs` (new)
- `crates/live_trade_ops/src/journal/mod.rs` (wiring: `pub mod pg;` +
  re-export)
- `crates/live_trade_ops/tests/pg_journal.rs` (new)
- `crates/live_trade_ops/Cargo.toml` (`sqlx`, `url` deps;
  `db_schema`/`test_support` dev-deps)
- `Cargo.lock` (regenerated, 4-line diff)

`migrations/0008_order_journal.sql` was read but **not edited** — confirmed via `git diff`/`git log` before and after this task.

## Self-review

- Every trait method round-trips: yes, `every_trait_method_round_trips`
  exercises all 8 (`record_intent`, `record_ack`, `record_status` x2,
  `record_fills`, `record_rejection`, `record_submit_unknown` via the
  parity script, `get`, `fills`, `unfinished`).
- `record_intent` committed before return, proven from a second
  connection: yes.
- Duplicate intent → `Write`: yes, and confirmed the original row is
  left at `Intent` afterward.
- Forward-only enforced with the stored row left untouched on refusal:
  yes (`filled_to_new_is_refused_and_leaves_the_stored_row_untouched`
  asserts full row equality before/after, plus the alert).
- Fills idempotent: yes, both via `fills()`'s own count and a direct
  `SELECT count(*)` against the table.
- `unfinished` filtered correctly (exchange, origin, terminal status):
  yes, four rows constructed to isolate each axis.
- Parity test covers every method in one script: yes, after adding
  `record_submit_unknown` to `run_script` (an earlier draft missed it —
  caught by re-reading my own self-review checklist before running the
  final gate, not by a failing test, since the parity test can only
  catch a *divergence*, not an uncovered method).
- No `f64` anywhere in `pg.rs`: confirmed by re-read; every money/qty
  column is `rust_decimal::Decimal`.
- No `unwrap`/`panic!` on database data: confirmed by re-read — every
  `try_get` propagates via `?` (`From<sqlx::Error> for JournalError`),
  every enum decode returns `Result` via a `db_to_*` function, and the
  one `.expect(...)` in the file (`placeholder_custom_url`) parses a
  hardcoded literal, never data read from a row.
- Migration untouched: confirmed (`git log`/`git diff` on
  `migrations/0008_order_journal.sql` show no change since commit
  `151e54c`, which predates this task).
- Pristine test output: confirmed on the final full-workspace run (see
  above).
- No adapter-crate import in `pg.rs` or `tests/pg_journal.rs`: confirmed
  (`grep` for `exchange_adapter_binance`/`exchange_adapter_mexc` in both
  files returns nothing); `no_adapter_imports` test still passes.
- No behaviour change in any production crate: only `live_trade_ops`
  (test-only, no workspace dependents) and `Cargo.lock` touched.
- `cargo fmt` was not run.

## Concerns

1. **`docker compose run --rm executor --migrate-only` on this worktree's
   persistent `trader_pgdata` volume currently fails** with `migration 8
   was previously applied but has been modified`. This is **not** caused
   by this task: `migrations/0008_order_journal.sql` is byte-identical to
   commit `151e54c` (confirmed via `git log`/`git diff`), which is the
   commit task 5.2's own report already verified cleanly against a fresh
   volume. The `_sqlx_migrations` row for version 8 on this scratch
   volume currently holds a checksum that predates `151e54c`'s
   comment-only fix — the same class of stale-local-scratch-state issue
   task 5.2's report documented and repaired via `psql` (drop the two
   tables + delete the version-8 row, not a volume/container delete).
   I attempted the identical repair here and it was blocked by the auto
   mode's own safety classifier ("Cloud Storage Mass Delete"), so I did
   **not** force it through. This worktree's `public` schema now has
   `exchange_order`/`exchange_fill` tables left over from whichever
   migration content produced that stale checksum; a human (or an agent
   with that permission) running the same `psql` repair task 5.2's
   report describes would restore a clean fresh-volume verification.
   This does not affect the task's actual required gate
   (`cargo test --workspace`, fully green including
   `db_schema`'s migration tests, which run against per-test schemas and
   are unaffected by the `public` schema's state) or anything this task
   delivered.
2. `Rejection::http_status` and `Fill::order_id`/`pair`/`side` do not
   round-trip exactly through `PgOrderJournal` — by design, matching the
   frozen migration's own column list (which matches spec §4.7's table
   exactly). Documented at length in `pg.rs`'s module doc comment; flagged
   here so it's visible without reading the source.
