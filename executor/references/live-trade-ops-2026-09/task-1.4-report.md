# Task 1.4 Report — Margin/futures ops traits

## What was implemented

New `crates/exchange_adapter/src/ops.rs`, re-exported from `lib.rs`:

- `MarginBalance { asset, free, locked, borrowed, interest, net_asset }`
- `MarginType { Cross, Isolated }`
- `MarginOps` (`#[async_trait]`, `Send + Sync`): `borrow`, `repay`,
  `max_borrowable`, `margin_balances` — signatures copied verbatim from the
  brief.
- `LeverageBracket { notional_floor, notional_cap, max_leverage, maint_margin_ratio, cum }`
- `FuturesPosition { pair, side, size, entry_price, mark_price, leverage, margin_type, isolated_margin, initial_margin, maint_margin, liquidation_price }`
- `FuturesMarginSummary { wallet_balance, available_balance, total_initial_margin, total_open_order_initial_margin, total_position_initial_margin }`
- `FuturesOps` (`#[async_trait]`, `Send + Sync`): `set_leverage`,
  `set_margin_type`, `leverage_brackets`, `position_risk`,
  `futures_margin_summary`, `is_hedge_mode` — signatures copied verbatim.

`ExchangeAdapter` (in `lib.rs`) gains two **default** methods:

```rust
fn margin_ops(&self) -> Option<&dyn MarginOps> { None }
fn futures_ops(&self) -> Option<&dyn FuturesOps> { None }
```

No liquidation/margin arithmetic anywhere in this crate — `ops.rs`'s doc
comment says explicitly that this belongs to `live_trade_ops` (Task 4.3)
and is out of scope here. No exchange-specific behaviour added.

### Integration test placeholders (Layer 2 RED)

Per the brief's "Integration test → Layer 2" section, added RED cases to
`crates/exchange_adapter_binance/tests/wiremock_tests.rs`:

- `margin_get_order_fills_parses_fee_bearing_trades` — mocks
  `GET /sapi/v1/margin/myTrades`, calls `get_order_fills` on `margin()`.
- `futures_get_order_fills_parses_realized_pnl` — mocks
  `GET /fapi/v1/userTrades`, asserts `realized_pnl` parses.
- `margin_ops_borrow_sends_borrow_repay_post_with_type_borrow` — mocks
  `POST /sapi/v1/margin/borrow-repay?type=BORROW`, calls
  `adapter.margin_ops().unwrap().borrow(...)`.
- `futures_ops_set_leverage_returns_the_applied_leverage` — mocks
  `POST /fapi/v1/leverage`, calls
  `adapter.futures_ops().unwrap().set_leverage(...)`.
- `minus_2010_body_classifies_to_insufficient_balance` — existing
  `POST /api/v3/order` rejection path, asserts
  `err.reason() == Some(RejectReason::InsufficientBalance)`.

All five fail today (RED) against the current, correct code: `margin_ops`/
`futures_ops` return `None` (trait default), `get_order_fills` returns
`Err(NotSupported)` (trait default, `BinanceMarketAccount` doesn't override
it — that's Task 2.3), and Binance's rejection path still tags everything
`RejectReason::Unknown` (`classify` is Task 2.2). They'll turn green as
Tasks 2.2–2.5 land, unmodified.

**Deviation from the brief, flagged explicitly:** the brief's fifth
integration case — `EXCHANGE_NETWORK=testnet` + margin →
`ConfigError::NoTestnet` — is **not** added. It depends on
`hosts(network, kind) -> Result<Hosts, ConfigError>`, which is Task 2.1's
own deliverable and doesn't exist anywhere in `exchange_adapter_binance`
yet (not even privately). Writing a test against it now would be a genuine
unresolved-name compile error. I confirmed by experiment that
`cargo test --workspace` (the `test` service's actual command in
`docker-compose.yml`) aborts the **entire** run — zero tests execute in
*any* crate — the instant any single test target fails to compile. Adding
that case now would have silently defeated this same task's "everything
else green" requirement rather than satisfying "Layer 2 tests RED". Left
for Task 2.1 to add alongside `hosts` itself. A comment in
`wiremock_tests.rs` documents this reasoning in place.

## TDD evidence

### `ops.rs` / `ExchangeAdapter::margin_ops`/`futures_ops` — RED

Temporarily removed the two new default methods from `ExchangeAdapter`
(kept `ops.rs` itself, since the new test in `lib.rs`'s `contract_tests`
is what exercises the trait surface) and ran:

```
docker compose run --build --rm test cargo test -p exchange_adapter
```

```
error[E0599]: no method named `margin_ops` found for struct `FakeAdapter` in the current scope
   --> crates/exchange_adapter/src/lib.rs:667:25
error[E0599]: no method named `futures_ops` found for struct `FakeAdapter` in the current scope
   --> crates/exchange_adapter/src/lib.rs:668:25
error: could not compile `exchange_adapter` (lib test) due to 2 previous errors
```

Expected: `FakeAdapter` (in `contract_tests`) never overrides
`margin_ops`/`futures_ops`, so the new test
`margin_and_futures_ops_default_to_none_when_unoverridden` can only compile
once the trait actually grows those default methods.

### GREEN

Restored the default methods, ran the same command:

```
docker compose run --build --rm test cargo test -p exchange_adapter
```

```
running 42 tests
...
test contract_tests::margin_and_futures_ops_default_to_none_when_unoverridden ... ok
test ops::tests::futures_margin_summary_constructs_with_the_exact_field_set ... ok
test ops::tests::leverage_bracket_constructs_with_the_exact_field_set ... ok
test ops::tests::margin_balance_constructs_with_the_exact_field_set ... ok
test ops::tests::futures_ops_is_object_safe_and_returns_canned_position ... ok
test ops::tests::margin_type_variants_are_distinguishable ... ok
test ops::tests::futures_position_constructs_with_the_exact_field_set ... ok
test ops::tests::position_risk_is_none_when_no_open_position_not_an_error ... ok
test ops::tests::margin_ops_is_object_safe_and_returns_canned_balances ... ok
...
test result: ok. 42 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s
```

(34 pre-existing + 8 new: 1 in `contract_tests`, 7 in `ops::tests` —
struct/enum field-set constructions and two object-safety tests proving
`&dyn MarginOps`/`&dyn FuturesOps` work as trait objects.)

### Full workspace gate

Ran the exact entry point first:

```
docker compose run --build --rm test
```

This failed at `exchange_adapter_binance`'s `wiremock_tests` target with
`error: could not compile ... cannot find function 'hosts'` from the
speculative fifth test I'd initially written — and, critically, **zero
tests ran anywhere in the workspace** because of it (confirmed no `test
result:` lines at all in that run's output). That's what led to removing
the `NoTestnet` case (see "Deviation" above).

After removing it, re-ran the exact entry point:

```
docker compose run --build --rm test
```

`exchange_adapter` (Layer 1, 42 tests) green, `exchange_adapter_binance`'s
own unit tests (53 tests) green, but the whole invocation still stops
after the first FAILED test *binary* — cargo's default fail-fast for
`cargo test --workspace` — so I also ran with `--no-fail-fast` to see the
rest of the workspace in the same pass:

```
docker compose run --build --rm test cargo test --workspace --no-fail-fast
```

Result: every crate `test result: ok` except
`exchange_adapter_binance`'s `wiremock_tests`, which reported exactly the
5 new RED cases failing and the pre-existing 26 tests in that same file
still passing:

```
test futures_get_order_fills_parses_realized_pnl ... FAILED
test futures_ops_set_leverage_returns_the_applied_leverage ... FAILED
test margin_get_order_fills_parses_fee_bearing_trades ... FAILED
test margin_ops_borrow_sends_borrow_repay_post_with_type_borrow ... FAILED
test minus_2010_body_classifies_to_insufficient_balance ... FAILED
test result: FAILED. 26 passed; 5 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.67s
...
error: 1 target failed:
    `-p exchange_adapter_binance --test wiremock_tests`
```

All other crates (cli, db_schema, migrations, exchange_adapter,
exchange_adapter_mexc + its 3 test binaries, execution, local_analysis,
market_data + read_path/write_path, mq_gateway, observability,
orchestrator, trade_executor, replay_harness, state_store + pg_store,
test_support, visualizer_backend, visualizer_server, cli's passive test)
reported `0 failed`.

Re-ran the known-flaky test in isolation per the task's environment note:

```
docker compose run --build --rm test cargo test -p market_data --test write_path shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database
```

```
test shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database ... ok
```

Did not flake this run — passed both in isolation and inside the full
`write_path` run (23 passed, 0 failed). No disk-space issue encountered
(`docker builder prune` not needed).

## Files changed

- `crates/exchange_adapter/src/ops.rs` (new) — `MarginOps`, `FuturesOps`,
  `MarginBalance`, `MarginType`, `LeverageBracket`, `FuturesPosition`,
  `FuturesMarginSummary`, in-file tests.
- `crates/exchange_adapter/src/lib.rs` — `mod ops;` + re-export;
  `ExchangeAdapter::margin_ops`/`futures_ops` default methods; one new
  test in `contract_tests`.
- `crates/exchange_adapter_binance/tests/wiremock_tests.rs` — `RejectReason`
  import; 5 new RED integration-test placeholders (see above) plus a
  comment explaining the omitted sixth case.

## Self-review findings

- Every method/field name in `ops.rs` matches the brief's interface block
  character-for-character; double-checked against the brief text again
  before committing.
- No `risk.rs`, no liquidation math, no test-only types added to
  `exchange_adapter` — confirmed by re-reading the diff; `ops.rs`'s own
  doc comment states the boundary explicitly.
- `exchange_adapter` still has zero new external dependencies and no
  workspace-member dependency (checked `Cargo.toml` — unchanged).
- Fixed a `fills[0].is_maker == false` idiom to `!fills[0].is_maker` on
  review (harmless either way, but the latter is the crate's own style
  elsewhere).
- Confirmed the two extension traits are genuinely object-safe by using
  them as `&dyn MarginOps`/`&dyn FuturesOps` in `ops::tests`, not just
  declaring them — this is the property the whole design depends on
  (`ExchangeAdapter::margin_ops`/`futures_ops` return `Option<&dyn _>`).
- Re-checked no other `ExchangeAdapter` implementor in the workspace
  (Binance, MEXC, `orchestrator`'s `KindAccount`/`NoTradeAccount`,
  `execution`'s fakes) needed any change — confirmed by grepping for
  `impl ExchangeAdapter for` across the workspace; all four sites compile
  untouched against the new defaults (verified by the full green run
  above covering every one of them).

## Concerns

- The one deliberate deviation from the brief (omitting the
  `EXCHANGE_NETWORK=testnet` + margin → `NoTestnet` RED case) is explained
  above and in a code comment. I believe this is the right call given the
  demonstrated cargo behavior, but flagging it explicitly since it's a
  literal instruction I did not follow.
- The `docker compose run --build --rm test` entry point as written in
  `global-constraints.md` cannot, on its own, demonstrate "everything else
  green" once *any* RED test exists in the workspace (cargo's fail-fast
  stops the run after the first failing binary, before later crates even
  get a chance to run their tests). I used `cargo test --workspace
  --no-fail-fast` to get full visibility in one pass instead; future tasks
  in this Layer 2/3 sequence that also carry RED-until-later tests will hit
  the same issue and may want to adopt `--no-fail-fast` for their own gate
  verification, or accept per-crate gate commands.
