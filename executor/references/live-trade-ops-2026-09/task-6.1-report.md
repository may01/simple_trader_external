# Task 6.1 report — Scripted fake exchange

## What was implemented

`crates/live_trade_ops/src/fake/{mod.rs,script.rs,builders.rs}`, re-exported from `lib.rs`:

- `script.rs`: `CallMatcher` (one variant per `MarketAccount`/`MarginOps`/`FuturesOps` call the task brief names), `OrderMatcher` (optional `side`/`reduce_only`/`client_id_step` fields, `None` always matches; `client_id_step` matches by substring so a script survives a fresh `run` id per invocation), `ReplyValue` (one variant per call's return payload, with `From` impls so a script can write `Reply::ok(order_ack)` instead of naming the enum variant), `Reply` (`Ok`/`Err`/`Delay(Duration, Box<Reply>)`/`Panic(String)`), and `Script` (`new`, `expect`, `any_time`, `without_margin_ops`, `without_futures_ops`, `book`).
- `mod.rs`: `RecordedCall` (full-argument record of every call received, independent of any matcher), `ScriptedExchange` (implements `ExchangeAdapter`; `spot()` is always `None` — nothing in Layers 6/7 runs a spot scenario; `margin()`/`futures()` both return the same backing `ScriptedAccount`; `margin_ops()`/`futures_ops()` return `Some`/`None` per the script), `ScriptedAccount` (implements `MarketAccount`, `MarginOps`, `FuturesOps` — every method is a thin wrapper around `dispatch` (find the reply or panic) + `resolve` (honour `Delay`/`Panic`, unwrap to the method's own `Result` type)), `calls()`, `assert_script_consumed()`.
- `builders.rs`: `resting_order_cancelled`, `marketable_order_filled`, `margin_balances` — exactly the three signatures the brief gives.

Dispatch logic (`ScriptedAccount::dispatch`): records the call, then checks `any_time` steps (unordered, never consumed) before the strict queue's front (consumed only on a match). No match in either → panic naming the call received and the step expected next (or "script exhausted" if the queue is empty). `resolve` loops through `Delay`/`Panic` layers, awaiting `tokio::time::sleep` for each `Delay` (never `std::thread::sleep`) and panicking synchronously for `Panic`.

`subscribe_market_data` streams `Script::book`'s events via `async_stream::stream!`, sleeping (on `tokio::time`) for each event's own delay before yielding it — same idiom `exchange_adapter_binance`/`exchange_adapter_mexc`'s websocket streams already use. `subscribe_account_updates` is not part of the scripted call surface at all (see "Decisions and things I did not ask about" below) — it always returns an empty stream.

### Carry-over from task 5.3's review

`crates/live_trade_ops/src/journal/mod.rs`'s `OrderJournal` trait doc now has a paragraph cross-referencing `pg.rs`'s "Two fields the frozen schema does not carry" explanation (`Rejection::http_status`; `Fill::order_id`/`pair`/`side`), so a reader of the trait alone learns the caveat exists instead of only finding it in `pg.rs`'s own tests.

### Cargo.toml changes

- Added `async-stream = "0.3.6"` to `[dependencies]` (same version already used by the two adapter crates for their websocket streams) — needed by `book()`'s stream.
- Moved `futures-util = "0.3.34"` from `[dev-dependencies]` to `[dependencies]`: `ScriptedAccount::subscribe_account_updates` (non-test code) needs `futures_util::stream::empty()`.
- Added `tokio = { features = ["time"] }` to `[dependencies]` (non-test code needs `tokio::time::sleep`); added `"time"` and `"test-util"` to the existing `[dev-dependencies]` `tokio` entry (this module's own `#[tokio::test(start_paused = true)]` self-tests need `test-util`; `market_data`'s `Cargo.toml` already sets this same precedent).
- No `Cargo.lock` changes were needed — every added package/feature was already present in the resolved graph from other crates.

## TDD evidence

Given the task brief pins the exact types (`ScriptedExchange`, `Script`, `CallMatcher`, `Reply`, `OrderMatcher`, the two builders) down to their field sets, I wrote the module and its `#[cfg(test)]` suite together rather than writing tests against types that didn't exist yet (which would only have produced compiler-error RED, not behavioural RED). To get genuine behavioural RED evidence instead, once the full suite was green I deliberately broke the one line that is this task's actual contract — `dispatch`'s call-matcher check — and reran:

**RED** — `crates/live_trade_ops/src/fake/mod.rs`, temporarily changed:
```rust
let front_matches = state.steps.front().is_some(); // BUG INJECTED FOR RED DEMONSTRATION
```
(dropping the `.is_some_and(|(m, _)| m.matches(&call))` matcher check, so *any* pending step is treated as a match regardless of its shape).

```
docker compose run --build --rm test cargo test -p live_trade_ops fake::
```
```
test fake::tests::an_order_matcher_field_mismatch_is_also_an_unexpected_call - should panic ... FAILED
test fake::tests::calling_a_later_step_before_its_earlier_step_panics - should panic ... FAILED
test fake::tests::the_panic_message_names_the_call_it_actually_received_and_the_step_it_expected - should panic ... FAILED

failures:
---- fake::tests::an_order_matcher_field_mismatch_is_also_an_unexpected_call stdout ----
note: test did not panic as expected at crates/live_trade_ops/src/fake/mod.rs:564:14
---- fake::tests::calling_a_later_step_before_its_earlier_step_panics stdout ----
thread '...' panicked at crates/live_trade_ops/src/fake/mod.rs:232:5:
ScriptedExchange: `cancel_order` step scripted a reply of the wrong shape: OrderAck(OrderAck { id: OrderId(1), status: New })
note: panic did not contain expected string
 expected substring: "unexpected call"
---- fake::tests::the_panic_message_names_the_call_it_actually_received_and_the_step_it_expected stdout ----
 expected substring: "expected next: PlaceOrder"

test result: FAILED. 20 passed; 3 failed; 0 ignored; 0 measured; 65 filtered out; finished in 1.01s
```
This is exactly the failure mode the task exists to prevent surfacing: with the matcher disabled, a wrong-order or wrong-shaped call silently gets whatever reply happens to be at the front of the queue instead of panicking. The three failures are precisely the tests that assert "unexpected call panics" and "strict order is enforced" — confirming those tests are not vacuous.

I reverted the injected bug (`cp` from a pre-edit backup, diffed clean against the intended file) before proceeding.

**GREEN** — same command, unmodified source:
```
docker compose run --build --rm test cargo test -p live_trade_ops fake::
```
```
running 23 tests
test fake::tests::any_time_step_is_repeatable_and_does_not_disturb_strict_order ... ok
test fake::tests::assert_script_consumed_is_silent_when_every_step_was_used ... ok
test fake::tests::an_order_matcher_field_mismatch_is_also_an_unexpected_call - should panic ... ok
test fake::tests::a_call_with_no_matching_step_at_all_panics - should panic ... ok
test fake::tests::assert_script_consumed_panics_listing_every_unused_step - should panic ... ok
test fake::tests::calling_a_later_step_before_its_earlier_step_panics - should panic ... ok
test fake::tests::calls_records_every_call_in_order_with_its_arguments ... ok
test fake::tests::margin_ops_and_futures_ops_default_to_some ... ok
test fake::tests::delay_advances_the_tokio_clock_by_the_full_duration ... ok
test fake::tests::book_streams_events_in_order_after_their_own_delays ... ok
test fake::tests::futures_ops_calls_go_through_the_same_script ... ok
test fake::tests::margin_ops_calls_go_through_the_same_script ... ok
test fake::tests::marketable_order_filled_builder_composes_a_fill_sequence ... ok
test fake::tests::nested_delays_each_advance_the_clock ... ok
test fake::tests::spot_is_always_none ... ok
test fake::tests::panic_reply_panics_inside_the_caller - should panic ... ok
test fake::tests::resting_order_cancelled_builder_composes_a_full_cleanup_sequence ... ok
test fake::tests::strict_steps_must_be_called_in_the_order_they_were_scripted ... ok
test fake::tests::without_futures_ops_turns_the_accessor_to_none ... ok
test fake::tests::without_margin_ops_turns_the_accessor_to_none ... ok
test fake::tests::the_panic_message_names_the_call_it_actually_received_and_the_step_it_expected - should panic ... ok
test fake::tests::the_panic_message_says_the_script_is_exhausted_when_there_is_no_next_step - should panic ... ok
test fake::tests::panic_reply_still_panics_after_a_delay - should panic ... ok

test result: ok. 23 passed; 0 failed; 0 ignored; 0 measured; 65 filtered out; finished in 1.01s
```

## Gate run

```
docker compose run --build --rm test cargo test --workspace --no-fail-fast
```

`live_trade_ops`: **88/88 passed** (65 pre-existing + 23 new in `fake::`), no compiler warnings, `tests/no_adapter_imports.rs` (the exchange-agnosticism guard) still passes. Full workspace: every other crate's tests passed, including `market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database` (the documented pre-existing flake, TECH_DEBT §5) — it passed on this run.

**One failure, unrelated to this diff:** `db_schema::migrations::dashboard_role_can_select_but_not_insert_on_the_real_public_schema_order_journal_tables`:
```
thread '...' panicked at crates/db_schema/tests/migrations.rs:998:48:
called `Result::unwrap()` on an `Err` value: VersionMismatch(8)
```
Re-ran in isolation (`cargo test -p db_schema --test migrations dashboard_role_can_select_but_not_insert_on_the_real_public_schema_order_journal_tables`) — same, deterministic failure.

Root-caused, not guessed: this test runs `db_schema::MIGRATOR.run` against the real `public` schema of `TEST_DATABASE_URL`, which this worktree's `docker-compose.yml` backs with a **persistent named volume** (`trader_pgdata`) — the test's own comment says as much ("`public` is a real, persistent schema shared across runs of this suite against the same Postgres volume"). Migration `0008_order_journal.sql`'s content changed between two commits already on this branch:
```
git show f835720:migrations/0008_order_journal.sql | md5sum   # 38039fab... (original)
git show 151e54c:migrations/0008_order_journal.sql | md5sum   # 9b8d937f... (post-review-fix, == current file)
```
The persistent volume's `_sqlx_migrations` table still holds the checksum from the *original* commit (`f835720`, applied to this worktree's Postgres volume at some point before the review-round fix landed); sqlx's migrator sees today's file hash to a different checksum for the same version and refuses with `VersionMismatch(8)`. This is stale local Docker-volume state left over from earlier development on this branch, not a defect in the current migration file, and this task's diff touches neither `db_schema` nor `migrations/` at all. I did not attempt to repair it (would mean mutating a persistent Postgres volume's bookkeeping table, which is an operational/infrastructure action outside this task's scope and outside "local git commit" pre-authorization) — flagging it here per the report format's request for concerns, and leaving the fix (most simply, `docker compose down -v` on this worktree, or a manual `_sqlx_migrations` checksum repair) to the user.

## Self-review findings

- Strict ordering enforced (`strict_steps_...`, `calling_a_later_step_before_its_earlier_step_panics`).
- `any_time` repeatable and doesn't disturb strict order (`any_time_step_is_repeatable_and_does_not_disturb_strict_order` — called 3×, un-consumed, `assert_script_consumed` stays silent).
- Unexpected call panics naming both sides (`the_panic_message_names_the_call_it_actually_received_and_the_step_it_expected`, `an_order_matcher_field_mismatch_is_also_an_unexpected_call`, `the_panic_message_says_the_script_is_exhausted_when_there_is_no_next_step`).
- `assert_script_consumed` lists leftovers by count and content (`assert_script_consumed_panics_listing_every_unused_step` — `#[should_panic(expected = "2 unused step(s)")]`).
- `Delay` proven on `tokio::time` under a paused clock, including nested delays (`delay_advances_the_tokio_clock_by_the_full_duration`, `nested_delays_each_advance_the_clock` — asserts *virtual* elapsed ≥ scripted duration while *wall* elapsed stays under 5s, proving it's the paused clock auto-advancing, not a real sleep).
- `Panic` reply panics inside the caller, including through a `Delay` wrapper (`panic_reply_panics_inside_the_caller`, `panic_reply_still_panics_after_a_delay`).
- `without_margin_ops`/`without_futures_ops` turn only their own accessor to `None`, leaving the other untouched and both defaulting to `Some`.
- `calls()` records full arguments, asserted by equality against the exact `OrderRequest`/`OrderId` values placed (`calls_records_every_call_in_order_with_its_arguments`).
- Builders compose into working end-to-end scripts (`resting_order_cancelled_builder_...`, `marketable_order_filled_builder_...`) and `margin_balances`/`FuturesOps`/`MarginOps` are reachable through the same dispatch path as `MarketAccount`.
- Confirmed the matching logic (not just its presence) is load-bearing via the RED/GREEN bug-injection run above.
- `tests/no_adapter_imports.rs` needed no change — `fake/{mod,script,builders}.rs` mention neither `exchange_adapter_binance` nor `exchange_adapter_mexc`; the guard test still passes.
- Verified `Cargo.lock` has no diff (all added deps/features were already resolved elsewhere in the workspace).
- One deliberate scope decision I did not stop to ask about (see below), documented in code and here.

### Decisions and things I did not ask about

`MarketAccount::subscribe_account_updates` has no `CallMatcher` variant in the brief and isn't mentioned by any spec §5.2 harness component (`BookWatcher`, the fill poller, the settlement check — all poll `get_order`/read balances rather than subscribing to pushed account events). Rather than inventing a matcher for a call nothing in Layers 6/7 makes, `ScriptedAccount::subscribe_account_updates` always returns an empty stream, unconditionally, outside the script/panic machinery entirely — documented inline at the call site. This is a minor, judgment-call gap-filling rather than a redefinition of any type the brief pins down; flagging it here in case the reviewer disagrees with treating it as out-of-scope.

`ScriptedExchange::spot()` always returns `None` (undocumented by the brief either way) since nothing in Layers 6/7 runs a spot scenario — matches `margin()`/`futures()` both being required accessors while spot is absent from every part of §5–§6 of the spec.

## Files changed

- `crates/live_trade_ops/src/fake/mod.rs` (new)
- `crates/live_trade_ops/src/fake/script.rs` (new)
- `crates/live_trade_ops/src/fake/builders.rs` (new)
- `crates/live_trade_ops/src/lib.rs` (add `pub mod fake;` + re-exports)
- `crates/live_trade_ops/src/journal/mod.rs` (doc-only carry-over)
- `crates/live_trade_ops/Cargo.toml` (dependency additions, documented above)

Commit: `95170b1` — `feat(live_trade_ops): scripted fake exchange` (branch `live-trade-ops`, local only, not pushed).

## Fix round 1/5

Two problems, both raised by the coordinator; both confirmed and fixed.

### 1. `Cargo.lock` was out of sync with the new dependency (mine to fix)

`docker compose build executor` failed:
```
error: cannot update the lock file /app/Cargo.lock because --locked was passed to prevent this
```

**Why my earlier "no diff" checks missed it:** the `test` service in `docker-compose.yml` has no source bind mount — it's `build: {context: ., target: test}`, so `docker compose run --build --rm test cargo test --workspace` runs against a *copy* of the repo baked into that build's image layer. Any lock-file update `cargo test` makes inside the container is written to that ephemeral container's filesystem and discarded on `--rm`; it never reaches the host's `Cargo.lock`. So every earlier `git diff Cargo.lock` on the host correctly reported no changes — the container had already "fixed" its own copy and thrown the fix away. Root cause of the drift itself: `live_trade_ops`'s `[[package]].dependencies` list in `Cargo.lock` (line ~1339) was missing `"async-stream"`, which I added to `crates/live_trade_ops/Cargo.toml` in the original task but never propagated into `Cargo.lock` on the host.

**Fix, without bumping any other version:**
```
docker compose run --rm --user "$(id -u):$(id -g)" -v "$(pwd):/app" test cargo check --workspace
```
(`--user "$(id -u):$(id -g)"` so the bind-mounted write lands as the host user, not root — per this project's own "containers write root-owned files into mounted worktrees" lesson; `cargo check`, not `cargo generate-lockfile`, because the latter re-resolves the *entire* lock from scratch and picked newer compatible versions for eight unrelated packages the first time I tried it — reverted with `git checkout -- Cargo.lock` before retrying with `check`, which only adds the missing dependency edge conservatively.)

```
git diff --stat Cargo.lock
```
```
 Cargo.lock | 1 +
 1 file changed, 1 insertion(+)
```
```
git diff Cargo.lock
```
```diff
 name = "live_trade_ops"
 version = "0.1.0"
 dependencies = [
+ "async-stream",
  "async-trait",
  "db_schema",
  "exchange_adapter",
```
Confirmed no root-owned files: `target/` and `Cargo.lock` both remained owned by `om:om` after the bind-mounted run.

**Executor build, now green:**
```
docker compose build executor
```
```
...
#10 79.66     Finished `release` profile [optimized] target(s) in 1m 19s
...
 executor  Built
```

### 2. `db_schema::migrations` failure — coordinator's correction accepted

My earlier root-cause (stale `_sqlx_migrations` checksum from migration 0008's pre-review content) was right in shape but wrong in attribution: the coordinator traced it to their own `docker compose run --rm executor --migrate-only` (without `--build`) applying a stale executor image's copy of 0008, and had already cleared the version-8 row back to version 7 before this fix round. Re-ran with `--build` as instructed:
```
docker compose run --build --rm executor --migrate-only
```
```
migrations applied: latest migration version 8, db_schema::SCHEMA_VERSION 8
```

### Full gate re-run

```
docker compose run --build --rm test cargo test --workspace --no-fail-fast
```
Every `test result:` line in the run reports `0 failed`. In particular:
- `db_schema::migrations`: **24/24 passed**, including `dashboard_role_can_select_but_not_insert_on_the_real_public_schema_order_journal_tables` (the test that failed before).
- `live_trade_ops`: **88/88 passed** (unchanged from before this fix round).
- `market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database` (the documented flake, TECH_DEBT §5): passed.

No other failures anywhere in the workspace.

### Note for the future (asked for explicitly)

`docker compose run --rm executor --migrate-only` **without `--build`** runs whatever executor image Docker already has cached, which can be older than the current source tree — including an older copy of a migration file. If that stale image applies a migration whose *content* later changes before the version number does (exactly what happened to migration `0008` across the review-round fix), the persistent Postgres volume's `_sqlx_migrations` checksum row locks in the old content, and every subsequent correctly-built image's migrator then refuses with `VersionMismatch(N)` until the row is repaired. Layer 7's live runs use the same `--migrate-only` entry point against real exchange credentials; forgetting `--build` there would hit the identical foot-gun, on a database that matters. Always pass `--build` with `--migrate-only`, or confirm the image was just rebuilt some other way first.

