# Task 2.4 report: `MarginOps` for Binance

## What was implemented

- `crates/exchange_adapter_binance/src/margin_ops.rs` (new): `BinanceMarginOps`, a `MarginOps`
  implementor holding its own clone of the margin `BinanceRestClient`.
  - `borrow`/`repay` share a private `borrow_repay(asset, amount, side)` helper that sends
    `POST /sapi/v1/margin/borrow-repay` with `asset`, `amount`, `type=BORROW|REPAY`,
    `isIsolated=FALSE` (spec §4.2). No response parsing needed — a non-2xx already becomes a
    typed `AdapterError::Rejected` via `rest.rs`'s existing `classify_http_error` → `errors::classify`
    path; success just returns `Ok(())`.
  - `max_borrowable` sends `GET /sapi/v1/margin/maxBorrowable?asset=...` and parses the `amount`
    field as `Decimal` (marked `// from docs — replace with capture`, per the fixture-capture rule —
    this endpoint's shape is unconfirmed against a real response).
  - `margin_balances` sends `GET /sapi/v1/margin/account` (the same path
    `MarketKind::Margin.endpoints().account` that `get_account_state` already uses) and parses it
    with the new `parse_margin_balances`.
- `crates/exchange_adapter_binance/src/parsing.rs`:
  - Added `margin_user_assets(account) -> Result<&Vec<Value>, AdapterError>`, factored out of
    `parse_balances`'s `Margin` arm's inline `userAssets[]` extraction — now the one place that
    array is pulled out of the account payload.
  - Added `parse_margin_balances(account) -> Result<Vec<MarginBalance>, AdapterError>`, built on
    `margin_user_assets`, parsing `asset`/`free`/`locked`/`borrowed`/`interest`/`netAsset` into the
    full `MarginBalance` struct — the fields `parse_balances` parses away for plain `BalanceDelta`.
  - Reused the existing `req_str`/`parse_decimal` helpers; no new parsing primitives.
- `crates/exchange_adapter_binance/src/adapter.rs`: added a `margin_ops: BinanceMarginOps` field to
  `ExchangeAdapterBinance`, constructed from `margin_rest.clone()` *before* `margin_rest` is moved
  into the `margin: BinanceMarketAccount::new(...)` call, and overrode
  `ExchangeAdapter::margin_ops()` to return `Some(&self.margin_ops)`.
- `crates/exchange_adapter_binance/src/lib.rs`: registered `mod margin_ops;`.

No behaviour change to `orchestrator`, `execution`, `market_data`, `mq_gateway`. No futures-ops
work (Task 2.5, left as its default `None` / RED test, untouched).

## TDD evidence

**RED** — before any implementation, ran the pre-existing test that belongs to this task:

```
docker compose run --build --rm test cargo test -p exchange_adapter_binance margin_ops_borrow_sends_borrow_repay_post_with_type_borrow -- --nocapture
```

```
thread 'margin_ops_borrow_sends_borrow_repay_post_with_type_borrow' panicked at
crates/exchange_adapter_binance/tests/wiremock_tests.rs:1664:43:
margin_ops should be Some on a Binance adapter
test margin_ops_borrow_sends_borrow_repay_post_with_type_borrow ... FAILED
test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 37 filtered out
```

Expected: `ExchangeAdapter::margin_ops()`'s default (`None`) means `.expect(...)` panics — exactly
the documented RED state before Task 2.4 overrides it.

I also strengthened this test's mock before implementing (per the task instructions: "keep its
assertions strong... a wrong request 404s"). The original mock only asserted `path` +
`type=BORROW`; I added `query_param` assertions for `asset=USDT`, `amount=100`, and
`isIsolated=FALSE` so a request missing any of those 404s against wiremock and the test fails,
rather than silently matching a looser mock. I also added five sibling tests (all initially RED
for the same "`margin_ops` is `None`" reason, confirmed by inspection — same code path panics):
`margin_ops_repay_sends_borrow_repay_post_with_type_repay`,
`margin_ops_max_borrowable_parses_amount`,
`margin_ops_margin_balances_parses_borrowed_interest_and_net_asset`,
`margin_ops_borrow_over_limit_surfaces_borrow_limit_exceeded` (`-3006` → `BorrowLimitExceeded`),
`margin_ops_repay_over_debt_surfaces_repay_exceeds_debt` (`-3015` → `RepayExceedsDebt`), plus two
`parsing.rs` unit tests (`parses_margin_balances_keeping_borrowed_interest_and_net_asset`,
`parse_margin_balances_rejects_a_missing_user_assets_array`).

**GREEN** — after implementation:

```
docker compose run --build --rm test cargo test -p exchange_adapter_binance
```

```
test result: ok. 108 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out   (unit tests)
test result: ok. 0 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out     (testnet_integration.rs)
--- wiremock_tests.rs ---
running 43 tests
...
test margin_ops_borrow_sends_borrow_repay_post_with_type_borrow ... ok
test margin_ops_repay_sends_borrow_repay_post_with_type_repay ... ok
test margin_ops_max_borrowable_parses_amount ... ok
test margin_ops_margin_balances_parses_borrowed_interest_and_net_asset ... ok
test margin_ops_borrow_over_limit_surfaces_borrow_limit_exceeded ... ok
test margin_ops_repay_over_debt_surfaces_repay_exceeds_debt ... ok
...
test futures_ops_set_leverage_returns_the_applied_leverage ... FAILED   <- Task 2.5, expected RED
test result: FAILED. 42 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out
```

The only failure is `futures_ops_set_leverage_returns_the_applied_leverage`, Task 2.5's RED test,
untouched (verified byte-for-byte identical against the pre-task commit via `git show HEAD~1` diff
— see Self-review below).

**Full workspace gate**:

```
docker compose run --build --rm test cargo test --workspace --no-fail-fast
```

```
error: 2 targets failed:
    `-p exchange_adapter_binance --test wiremock_tests`
    `-p market_data --test write_path`
```

- `exchange_adapter_binance::wiremock_tests`: 42 passed, 1 failed — the same
  `futures_ops_set_leverage_returns_the_applied_leverage` (Task 2.5 RED). Expected.
- `market_data::write_path`: 22 passed, 1 failed —
  `shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database`. This is the documented
  pre-existing flake (TECH_DEBT §5). Re-ran it in isolation:
  ```
  docker compose run --build --rm test cargo test -p market_data --test write_path \
    shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database -- --exact
  ```
  ```
  test shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database ... ok
  test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 22 filtered out
  ```
  Confirmed flake, unrelated to this task's changes (I never touched `market_data`).

No other target failed. Every other crate's tests (including all doc-tests) passed.

## Files changed

- `crates/exchange_adapter_binance/src/margin_ops.rs` (new)
- `crates/exchange_adapter_binance/src/lib.rs`
- `crates/exchange_adapter_binance/src/adapter.rs`
- `crates/exchange_adapter_binance/src/parsing.rs`
- `crates/exchange_adapter_binance/tests/wiremock_tests.rs`

Commit: `87d073d feat(binance): margin borrow, repay, max borrowable, balances` on branch
`live-trade-ops` (local only, not pushed).

## Self-review findings

- All four `MarginOps` methods implemented and tested (`borrow`, `repay`, `max_borrowable`,
  `margin_balances`).
- `borrow`/`repay` both assert `type=BORROW`/`type=REPAY` and `isIsolated=FALSE` via wiremock
  `query_param` matchers — confirmed a wrong request would 404 (that's exactly the mechanism
  `margin_place_order_never_sends_reduce_only_even_when_requested` already relies on elsewhere in
  this file).
- `-3006`/`-3015` surface as `BorrowLimitExceeded`/`RepayExceedsDebt` through `errors::classify` —
  no second classification path added; both new tests assert `err.reason()`.
- `margin_balances` parses `borrowed`/`interest`/`netAsset` without duplicating the account
  fetch/parse: same endpoint constant (`MarketKind::Margin.endpoints().account`), and the
  `userAssets[]` extraction is now shared (`margin_user_assets`) between `parse_balances` and
  `parse_margin_balances` rather than re-implemented.
- `// from docs — replace with capture` marker present on `max_borrowable`'s `amount` field
  (its shape is not confirmed against a real Binance response yet). Borrow/repay's request-building
  (path, params) correctly carries no such marker — request-building never does, per the plan's
  rule; there's no response-field mapping to mark on that call at all since nothing is parsed from
  the response.
- Task 2.5's `futures_ops_set_leverage_returns_the_applied_leverage` verified byte-for-byte
  untouched (diffed against `HEAD~1`/pre-task content, only whitespace context from insertion
  before it, no line inside the function changed).
- `cargo fmt` was not run on the crate; only the lines I wrote were hand-formatted to match
  surrounding style (checked against `rustfmt`'s usual line-wrap conventions used elsewhere in the
  file, e.g. `parse_fill`'s single-expression `Ok(...)` blocks).
- One added git-hygiene note: my first commit was missing the required `Co-Authored-By` trailer;
  caught it before reporting and amended the (still-unpushed, local-only) commit to add it.

## Concerns

- `max_borrowable`'s response shape (`{"amount": ..., "borrowLimit": ...}`) is taken from Binance's
  published docs, not a captured response — flagged with the marker per the plan's rule; a Layer 7
  live run against `configs/live-trade-ops/binance.margin.mainnet.env` should confirm the field
  name and remove the marker.
- `borrow`/`repay` don't parse `tranId` out of the response at all (the trait returns `Result<(),
  AdapterError>`, not the transaction id) — this matches the `MarginOps` trait signature exactly as
  given in `ops.rs`/spec §4.1, so this is intentional, not an oversight, but noting it in case a
  later task wants the transaction id surfaced.
