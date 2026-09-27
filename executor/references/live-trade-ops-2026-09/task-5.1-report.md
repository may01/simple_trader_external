# Task 5.1 report: `OrderJournal`, `JournaledAccount`, in-memory journal

## Status

DONE. (Fix round 1/5 applied -- see the addendum at the bottom of this file.)

## Design-review gate

The brief's leading note gates this task on TECH_DEBT.md §8's review. Per the dispatching
message, that review is closed (user decision, 2026-09-23): build exactly as specified (a state
row per order, updated in place, plus append-only fills). Confirmed by reading
`external/executor/TECH_DEBT.md` §8 directly — its `Status:` line reads "reviewed 2026-09-23 —
user decided to build as specified... The `exchange_order_event` action-log option below was
considered and not adopted." No action-log table was added; §8 is left open as its own text says
(revisit only if Layer 7's live runs show a cancel/crash is hard to reconstruct).

## What was implemented

- `crates/live_trade_ops/src/journal/mod.rs` — `OrderIntent`, `JournalStatus`, `JournaledOrder`,
  `JournalError`, the `OrderJournal` trait, `JournalContext`, and `JournaledAccount` (a
  `MarketAccount` decorator).
- `crates/live_trade_ops/src/journal/memory.rs` — `MemoryJournal`, the in-memory `OrderJournal`
  implementation.
- `crates/live_trade_ops/src/lib.rs` — added `pub mod journal;` and re-exports.
- `crates/live_trade_ops/Cargo.toml` — added `async-trait` (runtime dep, matching
  `exchange_adapter`'s version) and `futures-util`/`tokio` (dev-deps, for the `#[tokio::test]`
  self-tests and the recording fake's stream returns). Neither existed in this crate before this
  task.

### Interface note: brief vs. spec §4.7 on `record_fills`

Spec §4.7's trait signature shows `record_fills(&self, client_id, fills, s: &Settlement)`, but
the task brief (this task's binding, more specific text) drops the `Settlement` parameter and
says explicitly: "`record_fills` stores fills only; settlement is always recomputed with `settle`
(Task 4.2), never stored." Implemented per the brief — `record_fills` takes only `fills`. The
brief also drops the spec's generic `JournaledAccount<A: MarketAccount, J: OrderJournal>` in favor
of `Arc<dyn MarketAccount>`/`Arc<dyn OrderJournal>`, which is what's implemented.

### Judgment calls (nothing in the brief pinned these down)

1. **Alert kind reused, not added.** Spec/brief name the alert `OrderJournalWriteFailed`, but
   `observability::AlertKind` is a closed, production-crate enum and the task explicitly forbids
   production-crate behaviour change. `AlertKind::PersistFailed` ("a write to the store of record
   failed", per its own doc comment) is the closest existing fit and is reused for every journal
   write failure a caller doesn't already see as their own returned error (`record_ack`,
   `record_rejection`, `record_submit_unknown`, `record_status` including the
   `BackwardTransition` case, `record_fills`). The message always starts with
   `OrderJournalWriteFailed:` so the semantic name from the spec is preserved in the alert text,
   and tags carry `component=order_journal` + `client_order_id`.
2. **`new()`'s signature vs. an `alerts` field.** The brief's struct comment lists `alerts` as a
   field, but `new(inner, journal, ctx)` only takes three arguments. Resolved by defaulting
   `alerts` to `observability::StdoutAlerts` inside `new` (the same default used elsewhere in the
   workspace) and adding a separate `with_alerts(self, Arc<dyn Alerts>) -> Self` builder for
   tests/real wiring — `new`'s pinned signature is untouched.
3. **Forward-only rank model.** `JournalStatus` ranks: `Intent`(0) < `SubmittedUnknown`(1) <
   `New`(2) < `PartiallyFilled`(3) < `{Filled,Cancelled,Rejected}`(4, tied). A transition is
   allowed iff the new rank is strictly higher, or equal rank with the *same* status (a repeated
   poll updating `filled_qty`, not a real transition). Same rank + different status (a lateral
   flip, e.g. `Filled → Cancelled`, or `New → SubmittedUnknown`) is refused as backward. This
   covers every case in the brief/spec: the terminal states never re-flip to each other, and
   `SubmittedUnknown` only ever resolves forward into a known status, never the reverse.
   `MemoryJournal`'s tests also cover the "two different terminal statuses" case beyond the
   brief's one named example (`Filled` then `New`).
4. **`get_order`/`cancel_order` → `record_status`.** `cancel_order` returns `Result<(), _>` with
   no `OrderInfo` to record. Rather than have the decorator call `inner.get_order` again after a
   successful cancel (an extra, unasked-for exchange round trip), `record_cancelled` builds the
   `OrderInfo` from the journal's own last-known row (pair/side never change; `filled_qty`/
   `avg_fill_price` are whatever was last observed) plus the new `Cancelled` status. Tested
   explicitly (`cancel_order_records_a_cancelled_status_from_the_journals_own_last_known_row`
   asserts `inner.calls()` is exactly `[place_order, cancel_order]` — no extra `get_order`).
5. **`OrderId → client_order_id` backfill.** Per the brief's explicit instruction: consults the
   in-memory map first, then falls back to `journal.unfinished(exchange, origin)` and matches on
   `exchange_order_id` — never `inner.get_order_fills`, which the brief calls out as unable to
   resolve a leftover order from a crashed run. Implemented in `resolve_client_id`, tested by
   `order_id_map_is_backfilled_from_the_journal_on_a_miss` (constructs a fresh `JournaledAccount`
   against a journal pre-seeded as if by a dead earlier process, with an empty map).

## TDD evidence

Implementation and tests were written together (the fail-closed/forward-only rules are
interdependent enough that writing the trait, the decorator and its tests in lockstep was more
tractable than a literal first-write RED). To get honest RED evidence anyway, three real guard
rails were surgically disabled after the full implementation compiled, the suite was run to
confirm the *exact* expected tests fail (and nothing else), then the guards were restored and the
suite re-run to confirm GREEN. Diffs were done via scripted `python3` string replacement so the
before/after is exact and reviewable; both files were restored byte-for-byte from a
`cp`-taken backup afterward (`grep -c RED-TEST-STUB` = 0 in both files post-restore).

**RED — three faults injected simultaneously:**
1. `mod.rs::place_order`'s `client_order_id` gate replaced with an unconditional
   `unwrap_or_else(|| "RED-TEST-STUB".to_string())` (never refuses).
2. `mod.rs::check_transition` replaced with `Ok(())` unconditionally (forward-only rule
   disabled).
3. `memory.rs::record_fills`'s dedup (`HashSet::insert` gate) replaced with an unconditional
   push (idempotency disabled).

Command: `docker compose run --build --rm test cargo test -p live_trade_ops --no-fail-fast`

Result: exactly the 6 tests that exercise these three rules failed, all others (51) passed:

```
test journal::memory::tests::a_terminal_status_cannot_flip_to_a_different_terminal_status ... FAILED
test journal::memory::tests::record_fills_is_idempotent_on_exchange_and_trade_id ... FAILED
test journal::tests::backward_transition_is_refused_and_alerted_but_the_caller_still_gets_the_exchanges_answer ... FAILED
test journal::tests::get_order_fills_twice_stores_the_fill_once ... FAILED
test journal::tests::place_order_without_client_order_id_also_refuses_an_empty_one ... FAILED
test journal::tests::place_order_without_client_order_id_is_refused_and_inner_is_never_called ... FAILED

test result: FAILED. 51 passed; 6 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.18s
```

Sample failure detail (forward-only, guard disabled):
```
---- journal::tests::backward_transition_is_refused_and_alerted_but_the_caller_still_gets_the_exchanges_answer stdout ----
thread '...' panicked at crates/live_trade_ops/src/journal/mod.rs:1022:9:
assertion `left == right` failed
  left: New
 right: Filled
```
This is exactly the expected failure mode: without the guard, the journal's own row silently
regresses to `New` instead of staying at `Filled`, so the row-state assertion fails — proving the
test really exercises `check_transition`, not something incidental.

**GREEN — guards restored (files `cp`'d back from the pre-fault backup):**

Command: `docker compose run --build --rm test cargo test -p live_trade_ops --no-fail-fast`

```
running 57 tests
... (all 57 ok, including the 6 that failed above)
test result: ok. 57 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.17s
     Running tests/no_adapter_imports.rs ...
test no_file_other_than_registry_rs_imports_an_adapter_crate ... ok
   Doc-tests live_trade_ops
test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s
```

## Full workspace gate

Command: `docker compose run --build --rm test cargo test --workspace --no-fail-fast`

First run: one failure, `market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database`
— exactly the known pre-existing flake named in the task brief (TECH_DEBT §5). Re-ran it in
isolation:

```
docker compose run --build --rm test cargo test -p market_data --test write_path \
  shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database -- --nocapture
...
test shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 22 filtered out; finished in 1.12s
```

Passes in isolation, confirming it's the documented flake and unrelated to this task's changes.
Every other crate, including `live_trade_ops` (57 passed), was green in both full-workspace runs.

## Files changed

- `crates/live_trade_ops/src/journal/mod.rs` (new, 1273 lines incl. tests)
- `crates/live_trade_ops/src/journal/memory.rs` (new, 343 lines incl. tests)
- `crates/live_trade_ops/src/lib.rs` (added `pub mod journal;` + re-exports)
- `crates/live_trade_ops/Cargo.toml` (added `async-trait` dep; `futures-util`/`tokio` dev-deps)

## Self-review findings (fixed before this report)

- A genuine borrow-checker catch in `memory.rs::record_fills`'s first draft (overlapping mutable
  borrows of `state.fills` and `state.seen_trade_ids` through one `MutexGuard`) — fixed by
  collecting new fills into a local `Vec` while `state.seen_trade_ids` is borrowed, then
  extending `state.fills` afterward, so the two borrows never overlap.
- Two `#[warn(unused_must_use)]` warnings on unpolled test streams (`subscribe_market_data`,
  `subscribe_account_updates` results dropped without use) — fixed by binding to `_stream`/
  `_events` in the passthrough test.
- A handful of lines over the repo's ~100-col convention, hand-wrapped (no `rustfmt` binary is
  installed in the test image, so this was manual, not `cargo fmt`, and touched only lines this
  task wrote).
- A rustdoc cross-repo link (`external/executor/TECH_DEBT.md`) used a relative path that was
  wrong by three directory levels and would never resolve (`external/` isn't inside this git
  worktree at all — it lives at a sibling path per this project's own "docs live externally"
  convention). Replaced with plain-text prose instead of a link.

## Checklist against the brief's test list

All present, each against `MemoryJournal` + `RecordingAccount` (the fake account) unless noted:

- missing/empty `client_order_id` → `InvalidRequest`, inner never called (2 tests)
- `record_intent` failure (via a `FaultyJournal` wrapper) → inner `place_order` never called
- intent → send → ack ordering, proven two ways: call-log order, and a journal that asserts
  `inner`'s real call log is empty at the moment `record_intent` runs
- `Rejected` → `record_rejection`, row status `Rejected`, error passed through unchanged
- `Network` → row `SubmittedUnknown`, error passed through unchanged
- `record_ack` failure after inner succeeds → `AlertKind::PersistFailed` alert
  (`OrderJournalWriteFailed` in the message) + error returned to caller
- forward-only: `Filled` then `New` → caller still gets both exchange answers unchanged, journal
  row stays `Filled`, one alert fired (decorator-level); a second, lower-level test in
  `memory.rs` covers `Filled` then a *different* terminal (`Cancelled`) directly against
  `MemoryJournal`
- `get_order_fills` twice with the same `trade_id` → stored once (decorator-level); a lower-level
  `MemoryJournal` test covers the same idempotency directly, plus one new + one duplicate in the
  same call
- `unfinished` filtered by exchange + origin, excluding terminal rows (both a decorator-level and
  a `MemoryJournal`-level test)
- passthrough methods (`subscribe_market_data`, `get_account_state`, `get_fees`,
  `get_market_info`, `get_extended_market_data`, `subscribe_account_updates`) reach `inner`
  untouched
- `OrderId → client_order_id` map backfilled from the journal on a miss (simulated crashed-run
  leftover: journal pre-seeded, fresh `JournaledAccount`, empty map)
- `cancel_order` records nothing when the inner cancel itself fails (extra test beyond the
  brief's list, added because `record_cancelled`'s "only after success" gate is itself a
  fail-closed-adjacent rule worth pinning down)

No `f64` anywhere in the new code (`Decimal` throughout, matching `settle`/`risk`). No `unwrap()`
in production code paths — every `.unwrap()` in the new files is in test fixtures/assertions or
on `Mutex::lock()` (lock-poisoning, not caller data).

## Concerns

- The `AlertKind::PersistFailed` reuse (judgment call 1 above) means a log/alert consumer
  filtering on `AlertKind` alone cannot distinguish an order-journal write failure from any other
  persistence failure in the workspace by kind — only by the message's
  `OrderJournalWriteFailed:` prefix and the `component=order_journal` tag. If a future task wants
  journal failures to be independently filterable/metriced, that would need either a new
  `AlertKind` variant (a production-crate change, out of this task's scope) or a tag-based
  convention agreed on explicitly.
- `record_rejection`/`record_submit_unknown`/`record_fills` write failures are alerted but the
  original `AdapterError` (Rejected/Network) is still returned to the caller unchanged, per the
  brief's "error passed through unchanged" requirement for those paths — this means a
  `record_rejection` failure is only visible via the alert, never via the returned error. This
  mirrors the brief's own explicit design for the forward-only case (alert-only) but the brief
  doesn't explicitly say whether `record_rejection`/`record_submit_unknown` failures should be
  alert-only too; treated them the same way for consistency (see judgment call 1) since no test
  says otherwise.

---

## Fix round 1/5 addendum

Spec review came back PASS on every named rule, with four Important findings, all fixed. Summary
of each, the fix, and the adversarial verification done for each (temporarily reverting the fix,
confirming exactly the new test(s) fail, restoring, reconfirming green -- same method as the
original RED/GREEN evidence above).

### Finding 1 -- four alert-firing branches had no test that could make them fail

`FaultyJournal` only had `fail_record_intent`/`fail_record_ack`. Extended it with independent
knobs for every other `OrderJournal` write method `JournaledAccount` calls:
`fail_record_rejection`, `fail_record_submit_unknown`, `fail_record_fills`, `fail_record_status`,
plus `fail_get`/`force_get_none` for finding 2. Added one test per previously-untested branch:

- `record_rejection_write_failure_after_a_real_rejection_alerts` (`place_order`'s `Rejected` arm)
- `record_submit_unknown_write_failure_after_a_network_error_alerts` (`place_order`'s `Network` arm)
- `get_order_fills_write_failure_alerts_but_still_returns_the_fills_to_the_caller`
- `cancel_order_record_status_write_failure_alerts_but_cancel_order_still_succeeds`

**Adversarial check:** neutered all four `fire_persist_failed` calls simultaneously (turned each
into a bare `let _ = journal.<call>(...).await;`), ran `cargo test -p live_trade_ops
--no-fail-fast` -- exactly `record_rejection_write_failure_...`,
`record_submit_unknown_write_failure_...`, and `get_order_fills_write_failure_...` failed (3 of
the 4; the fourth, `record_status` inside `record_cancelled`, was deliberately left un-neutered in
this pass since finding 2's fix touches the same function -- see finding 2's own check for that
one), 60 others unaffected. Restored, reconfirmed 65/65 green.

### Finding 2 -- silent, un-alerted swallow in `record_cancelled`

The single `let Ok(Some(existing)) = self.journal.get(&client_id).await else { return };` bundled
two distinct failure modes (`Err`, and an inconsistent `Ok(None)`) into one silent bail. Split into
an explicit `match` with its own alert for each: `Err` (a real `PgOrderJournal` failure) and
`Ok(None)` (the resolved `client_id` has no journal row at all -- an inconsistency, not "nothing
to do"). The other `let Some(client_id) = self.resolve_client_id(id).await else { return };` line
above it stays a silent, undocumented-no-longer return -- it is the genuinely benign case (nothing
was ever journaled for this `OrderId`, so nothing can vanish), now with a doc comment explaining
why, matching `record_observed_status`'s existing precedent.

New tests: `cancel_order_alerts_when_reading_the_existing_row_back_fails` (`fail_get`),
`cancel_order_alerts_when_the_resolved_client_id_has_no_journal_row` (`force_get_none`).

**Adversarial check:** reverted the `match` back to the original single `let ... else { return }`
(combining both `Err` and `Ok(None)` into one silent bail again) while simultaneously neutering
the other three finding-1 alert calls (record_rejection/record_submit_unknown/record_fills, see
above). Ran the suite: exactly 5 failures --both finding-2 tests plus the three finding-1 ones
neutered in the same pass (`cancel_order_record_status_write_failure_...`, which exercises the
*surviving* `record_status` call further down in the same function, correctly did not fail,
confirming that test is independent of the reverted block). Restored, reconfirmed 65/65 green.

### Finding 3 -- an `Intent` row orphaned forever on a non-`Rejected`/non-`Network` local refusal

`place_order`'s `match` ended `Err(other) => Err(other)`, silently leaving the row at `Intent`
when `inner.place_order` refuses locally with anything else (e.g. `InvalidRequest` from a wrapping
`CappedAccount`, spec §5.2's real stack). Fixed by recording a synthetic, local `Rejection`
(`reason: Unknown, exchange: Local`) via `record_rejection` in that arm before returning `other`
unchanged -- moves the row `Intent -> Rejected` (forward, terminal), so it stops appearing in
`unfinished()`.

New test: `a_local_refusal_from_inner_terminates_the_row_so_unfinished_no_longer_lists_it` -- a
fake whose `place_order` returns `InvalidRequest`, asserting the row ends `JournalStatus::Rejected`
and `unfinished()` no longer lists it.

**Adversarial check:** reverted the arm to `Err(other) => Err(other)`. The new test failed exactly
as expected (`left: Intent, right: Rejected` -- the row never left `Intent`). Restored, reconfirmed
green.

### Finding 4 -- `record_ack` failure returned a retryable error for an order the exchange already accepted

Previously returned `AdapterError::Network(...)`, and `Network.is_retryable() == true` (spec
§4.6) -- a caller honouring that contract could retry `place_order` and double-submit a live
order. Changed to `AdapterError::Rejected(Rejection { reason: Unknown, exchange: Local, ... })`,
which is non-retryable, with the choice (over `InvalidRequest`, the other non-retryable candidate)
explained in the doc comment: `Rejected` keeps the structured, inspectable `Rejection` shape and
matches the existing `Local`-origin convention (`NoTradeAccount`'s `Disarmed`), whereas
`InvalidRequest` documents itself as "before anything was sent" -- the opposite of what actually
happened.

New test: `ack_write_failure_after_inner_succeeds_returns_a_non_retryable_error`, asserting
`!err.is_retryable()` and `matches!(err, AdapterError::Rejected(_))`. The pre-existing
`ack_write_failure_after_inner_succeeds_alerts_and_returns_an_error` test (asserting only
`result.is_err()`) still passes unchanged -- it never depended on which variant was returned.

**Adversarial check:** reverted the arm to the original `Err(AdapterError::Network(...))`. The new
test failed exactly as expected (`an already-accepted order must never look retryable:
Network("...")`). Restored, reconfirmed green.

### Not re-litigated

Per the coordinator's message, the four items the reviewer flagged as "not findings, no action"
(the `record_fills`/`Settlement` signature, the `PersistFailed` reuse, the three-arg constructor,
and the `OrderId` backfill's test coverage) were left exactly as they were -- no changes made.

### Re-run commands and output (post-fix)

```
docker compose run --build --rm test cargo test -p live_trade_ops --no-fail-fast
```
```
running 65 tests
... (all ok)
test result: ok. 65 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.21s
     Running tests/no_adapter_imports.rs ...
test no_file_other_than_registry_rs_imports_an_adapter_crate ... ok
   Doc-tests live_trade_ops
test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s
```

Workspace gate (required by finding 4 touching the shared `AdapterError`/`is_retryable` contract,
even though the change is confined to `live_trade_ops` -- no other crate constructs or matches on
this specific error path):
```
docker compose run --build --rm test cargo test --workspace --no-fail-fast
```
Result: every crate green; `live_trade_ops`: `65 passed; 0 failed`. One failure,
`market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database` --
the same known pre-existing flake (TECH_DEBT §5) noted in the original report. Re-ran in
isolation:
```
docker compose run --build --rm test cargo test -p market_data --test write_path \
  shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database -- --nocapture
...
test shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 22 filtered out; finished in 0.93s
```
Passes in isolation, confirming it is the documented flake, unrelated to this change.

### Files changed (this round)

- `crates/live_trade_ops/src/journal/mod.rs` only (364 insertions, 12 deletions: the four
  production-code fixes plus 12 new tests and `FaultyJournal`'s expanded fault-injection surface).
