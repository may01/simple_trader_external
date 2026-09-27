# Task 1.2 report: Rejection model

## What was implemented

Turned `AdapterError::Rejected(String)` into `AdapterError::Rejected(Rejection)` with an
exchange-agnostic `RejectReason`, per the brief's exact interface. New file
`crates/exchange_adapter/src/error.rs`, re-exported from `lib.rs`:

- `RejectReason` — exactly the 20 variants listed in the brief (no test-only variants; no
  `NotionalCapExceeded`).
- `Rejection { reason, exchange, code: Option<String>, http_status: Option<u16>, message: String }`.
- `impl Display for Rejection`: `rejected: {message} [{exchange} {code}]`, code bracket omitted
  when `None` (uses `{:?}` for `exchange` since `Exchange` only derives `Debug`, which prints
  bare variant names like `Binance`).
- `impl AdapterError { pub fn reason(&self) -> Option<RejectReason>; pub fn is_retryable(&self) -> bool; }`
  — `reason()` is `Some` only for `Rejected`; `is_retryable()` is true for `RateLimited`,
  `Network(_)`, and `Rejected` carrying `RejectReason::ClockSkew`, false otherwise.
- `AdapterError::Rejected`'s own `Display` arm now delegates to `Rejection`'s `Display`.
- Doc comment on `AdapterError` narrows `InvalidRequest`'s meaning: refused locally before
  anything was sent, or an unparseable response — never an exchange's own refusal.

No new dependencies added to `exchange_adapter` (still a leaf crate, uses only `std::fmt` and
`crate::config::Exchange`).

### Ripple edits (compile-only in meaning, per the task's scope)

- `crates/orchestrator/src/no_trade.rs`: `refusal()` now builds
  `Rejection { reason: Disarmed, exchange: Local, code: None, http_status: None, message: "execution disarmed: EXECUTION_MODE=no_trade" }`.
  Its three tests updated: `place_order_is_refused_...`/`cancel_order_is_refused_...` now assert
  `err.reason() == Some(RejectReason::Disarmed)` (brief's explicit requirement) instead of just
  `matches!(_, Rejected(_))`; `the_refusal_explains_itself` destructures the `Rejection` and checks
  `.message` plus (added) `.reason == Disarmed`.
- `crates/execution/src/tests.rs`: fake `place_order` failure path now returns
  `Rejection { reason: Unknown, exchange: Local, code: None, http_status: None, message: "forced test failure" }`.
- `crates/exchange_adapter_binance/src/rest.rs`: `classify_http_error` unchanged classification
  (429/418 → `RateLimited`, other 4xx → `Rejected`, else `Network`); the `Rejected` arm now builds
  `Rejection { reason: Unknown, exchange: Binance, code: None, http_status: Some(status), message: body }`.
  No JSON/code parsing existed here before and none was added — "code/message extracted as
  today" for this file means `code: None`, raw body preserved verbatim as `message`.
- `crates/exchange_adapter_mexc/src/http.rs`: `map_error_status`'s 401/403 branch (the only branch
  that was ever `Rejected`) now builds `Rejection { reason: Unknown, exchange: Mexc, code: None, http_status: Some(status), message: format!("auth error ({status}): {msg}") }`
  — the `msg` text (already embedding `[code] text` when a code was parsed) is preserved
  byte-for-byte; the other branches (`RateLimited`/`InvalidRequest`/`Network`) are untouched.
- `crates/exchange_adapter_mexc/src/dto_futures.rs`: `unwrap_envelope`'s `success: false` branch
  now builds `Rejection { reason: Unknown, exchange: Mexc, code: envelope.code.map(|c| c.to_string()), http_status: None, message: msg }`.
  `msg` computation is byte-for-byte unchanged (envelope's `message`, or the same fallback string
  built from `code`'s `Debug` form when absent). The one new thing: `envelope.code` — already
  extracted today but previously only consulted for the absent-message fallback — is now *also*
  carried structurally in `Rejection.code`, since the type now has a field for it. This doesn't
  change `message`/`Display` output for the case the existing test exercises.
  In-file test `unwrap_envelope_rejects_on_success_false_even_with_http_200` updated to match on
  `Rejected(ref r) if r.message.contains(...)`.
- `crates/exchange_adapter_mexc/tests/futures_wiremock_tests.rs`: same match-arm update,
  `Rejected(ref r) if r.message.contains("insufficient balance")`.
- `crates/exchange_adapter_binance/tests/wiremock_tests.rs` (not in the brief's file list, found
  by grep): two `matches!(result, Err(AdapterError::Rejected(_)))` sites — untouched, compile
  unchanged since the wildcard pattern doesn't care about the inner type.

## TDD evidence

**RED** — temporarily reverted `AdapterError::Rejected(Rejection)` back to `Rejected(String)`
(keeping the new `error.rs` test file in place) and ran:

```
docker compose run --build --rm test cargo test -p exchange_adapter
```

Failing output (compile error, as expected — the new tests construct `Rejected(Rejection {...})`
which doesn't fit the old `String` variant):

```
error[E0308]: mismatched types
   --> crates/exchange_adapter/src/error.rs:145:40
    |
145 |         assert!(AdapterError::Rejected(rejection(RejectReason::ClockSkew)).is_retryable());
    |                 ---------------------- ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ expected `String`, found `Rejection`
...
error: could not compile `exchange_adapter` (lib test) due to 7 previous errors
```

**GREEN** — reapplied the `Rejected(Rejection)` change and reran the same command:

```
docker compose run --build --rm test cargo test -p exchange_adapter
```

```
running 29 tests
...
test error::tests::adapter_error_rejected_display_delegates_to_rejection ... ok
test error::tests::display_includes_code_when_present ... ok
test error::tests::reason_is_some_only_for_rejected ... ok
test error::tests::is_retryable_true_exactly_for_rate_limited_network_and_clock_skew_rejection ... ok
test error::tests::display_omits_code_bracket_when_absent ... ok
...
test result: ok. 29 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s
```

Then applied the ripple edits and reran the affected crates together:

```
docker compose run --build --rm test cargo test -p exchange_adapter -p exchange_adapter_binance -p exchange_adapter_mexc -p orchestrator -p execution
```

All green — `exchange_adapter` 29, `exchange_adapter_binance` 73 (+26 wiremock +1 ignored live),
`exchange_adapter_mexc` 61 (unit) + 7 futures_wiremock + 11 spot_wiremock + 10 ws wiremock + 1
ignored live, `execution` 20, `orchestrator` 42. 0 failed anywhere.

## Full workspace gate

```
docker compose run --build --rm test
```

First full run: exit 0, every one of the 45 test binaries reported `ok` (including doc-tests),
covering the whole workspace.

A second full run hit 3 failures in `visualizer_server::passive` — but the panic was
`PgDatabaseError { code: "53100", message: "could not extend file ...: No space left on device" }`,
not a code issue. `df -h /` showed the host at 98% (4.5G free). Ran `docker builder prune -f` to
reclaim 2.6GB of build cache (safe: only Docker's reclaimable build-cache layers, not the repo,
not any container/volume with data), re-ran the previously-failing test file alone (52/52 passed)
and then the full suite once more end-to-end: exit 0, all 45 binaries `ok`, `FAILED` count 0.

The known pre-existing flake called out in the task
(`market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database`)
did not appear in any run — nothing to isolate/report there.

## Files changed

- `crates/exchange_adapter/src/error.rs` (new)
- `crates/exchange_adapter/src/lib.rs`
- `crates/orchestrator/src/no_trade.rs`
- `crates/execution/src/tests.rs`
- `crates/exchange_adapter_binance/src/rest.rs`
- `crates/exchange_adapter_mexc/src/http.rs`
- `crates/exchange_adapter_mexc/src/dto_futures.rs`
- `crates/exchange_adapter_mexc/tests/futures_wiremock_tests.rs`

Exactly the file list the brief named plus the required new `error.rs`.

## Self-review findings

- **Completeness**: `RejectReason` has exactly the 20 variants listed, in the same order, no
  additions. `Rejection`'s fields match the brief's struct verbatim. `reason()`/`is_retryable()`
  signatures match verbatim.
- **Naming**: no renames outside what the brief specified.
- **YAGNI**: did not write `classify` tables (explicitly deferred to 2.2/3.1); did not add
  `NotionalCapExceeded` or any other variant beyond the brief's list; did not touch
  `market_data`/`mq_gateway` (no `Rejected` usage there — verified by workspace-wide grep).
- **Ripple meaning preserved**: verified via full-suite green run plus reading every touched
  branch's control flow before and after — no branch that used to hit `RateLimited`/
  `InvalidRequest`/`Network` now hits `Rejected` or vice versa, in any of the five files.
- **One judgment call**: `dto_futures.rs`'s `envelope.code` is now also copied into
  `Rejection.code` (previously it was only consulted as a fallback-message ingredient, discarded
  when `message` was present). This doesn't change any presently-tested `message`/`Display`
  output, and directly serves the stated goal ("the exchange code/message preserved") using data
  that was already being extracted — flagging it here since it's the one place I did slightly
  more than the pure minimum type-wrap.
- Confirmed `exchange_adapter/Cargo.toml` has no diff (no new dependency).
- Confirmed no new compiler warnings in any of the seven touched crates (grepped the full-suite
  log; the only warnings present are pre-existing, in `local_analysis`/`mq_gateway`, unrelated to
  this change).
- Grepped the whole workspace for `AdapterError::Rejected`/`Rejected(` after finishing to confirm
  no call site was missed; found one extra file not in the brief's list
  (`crates/exchange_adapter_binance/tests/wiremock_tests.rs`) using a wildcard pattern that needed
  no edit.

## Concerns

- The host disk-space issue (98% full at the time) is environmental, not introduced by this
  change, and is now mitigated by the build-cache prune — but it's worth flagging since it could
  recur for later tasks/layers on this same host if the pattern continues (`--build` on every
  gate run growing the image/layer cache). Not something to fix as part of this task.
- Not a concern exactly, but worth surfacing for reviewer attention: the `dto_futures.rs`
  `Rejection.code` enrichment noted above under self-review.
