# Task 2.3 report: client order id, fills, market info assets (Binance)

## What was implemented

1. **`get_order_fills` on `BinanceMarketAccount`** (`crates/exchange_adapter_binance/src/market.rs`),
   for all three kinds, resolving the symbol via the existing `symbol_for`
   (`order_symbols`) cache — the same mechanism `get_order`/`cancel_order`
   already use, since `MarketAccount::get_order_fills` carries only an
   `OrderId` but Binance's fills endpoints require `symbol`:
   - spot: `GET /api/v3/myTrades?symbol&orderId`
   - margin: `GET /sapi/v1/margin/myTrades?symbol&orderId&isIsolated=FALSE`
   - futures: `GET /fapi/v1/userTrades?symbol&orderId`
2. **`Fill` parsing** (`crates/exchange_adapter_binance/src/parsing.rs`,
   new `parse_fill`/`parse_fills`): `trade_id` (`id`, stringified),
   `order_id`, `pair`, `price`, `qty`, `quote_qty`,
   `fee`/`fee_asset` (`commission`/`commissionAsset`), `ts` (`time`)
   shared verbatim across kinds; side/maker/realized_pnl diverge:
   - spot/margin: side from `isBuyer` (no `side` field on these
     endpoints), maker flag `isMaker`, `realized_pnl` always `None`.
   - futures: side from `side`, maker flag `maker`, `realized_pnl` from
     `realizedPnl` (`Some`).
   Marked `// from docs — replace with capture` (not yet captured from a
   real response — Layer 7's job).
3. **`OrderInfo.client_order_id`** parsed from `clientOrderId` in
   `parse_order_info` (feeds both `get_order` and open-orders responses,
   all three kinds); an empty string is treated as absent, same as no
   field at all.
4. **`MarketInfo.base_asset`/`quote_asset`** parsed from `exchangeInfo`'s
   `baseAsset`/`quoteAsset` as required fields (`req_str`, typed error if
   missing — no silent `String::new()` fallback), also marked
   `// from docs — replace with capture`.
5. **Endpoint paths** (`crates/exchange_adapter_binance/src/kind.rs`):
   added `Endpoints.fills` per kind (see above three paths).
6. **Carry-over fix**: deleted the stale "RED until Task 2.2" comment on
   `minus_2010_body_classifies_to_insufficient_balance` (Task 2.2 already
   landed; `classify` exists and the test was already green).

## A shape correction to the two pre-existing RED tests

`margin_get_order_fills_parses_fee_bearing_trades` and
`futures_get_order_fills_parses_realized_pnl` (written in Task 1.4 as
placeholders) called `get_order_fills(OrderId(n))` directly on a freshly
built adapter, with no prior `place_order`/`get_account_state` call. That
shape is incompatible with a correct implementation: Binance's fills
endpoints require `symbol`, and the only way this crate's
`MarketAccount` (whose `get_order_fills` signature carries only an
`OrderId`, per L0's fixed trait) can recover a symbol for an id is the
`order_symbols` cache populated by `place_order`/`get_account_state` —
exactly the same constraint `get_order`/`cancel_order` already document
in `symbol_for`'s error message. Sending no `symbol` at all, or an
empty/wrong one, to satisfy the test as originally written would not
match the endpoint table ("all with `symbol` + `orderId`") and would not
reflect real usage (where the harness always knows the order it just
placed).

I judged this a test-setup gap, not a design question worth blocking on:
the task instructions explicitly reserved "must stay RED and untouched"
for the *other* two placeholders (2.4/2.5) but did not say that for
these two, only that they "must now go GREEN" — leaving room to fix their
setup. I added a `place_order` call (with its own mock) before each
`get_order_fills` call to prime the cache, and added `query_param`
assertions on `symbol`/`orderId`/`isIsolated` to the mocks so the tests
now also verify request-building, not just response parsing. The
original assertions (fee_asset, is_maker, realized_pnl) are unchanged.

## New wiremock tests added (per the brief's list)

- `spot_get_order_fills_parses_multiple_fills_with_mixed_maker_flags` —
  the only fills coverage for spot; also covers a multi-fill response
  and a non-quote fee asset (BTC).
- `margin_place_order_never_sends_reduce_only_even_when_requested` — spec
  §4.4; uses `query_param_is_missing("reduceOnly")` so a regression would
  404 rather than silently pass.
- `spot_get_order_parses_client_order_id`,
  `margin_get_order_parses_client_order_id`,
  `futures_get_order_parses_client_order_id` — one per kind, per spec
  §5.4's "one wiremock parsing test per kind".
- `open_orders_parses_client_order_id` — the open-orders half of §5.4's
  requirement (order-create/query is covered by the three tests above).
- `get_market_info_computes_precision_from_filter_scale` extended with
  `baseAsset`/`quoteAsset` assertions.

`parsing.rs` unit tests added: `parses_spot_fill_from_is_buyer_and_is_maker_flags`,
`parses_futures_fill_from_side_and_maker_flag_with_realized_pnl`,
`parse_fills_rejects_a_non_array_response`,
`parse_order_info_reads_client_order_id_and_treats_empty_string_as_none`,
`market_info_missing_base_asset_is_a_typed_error_not_an_empty_string`
(also extended `parses_market_info_precision_from_filter_scale`).

## TDD evidence

**RED** (baseline before any change, full crate):

```
docker compose run --build --rm test cargo test -p exchange_adapter_binance --no-fail-fast
```
```
test margin_get_order_fills_parses_fee_bearing_trades ... FAILED
test futures_ops_set_leverage_returns_the_applied_leverage ... FAILED
test futures_get_order_fills_parses_realized_pnl ... FAILED
test margin_ops_borrow_sends_borrow_repay_post_with_type_borrow ... FAILED
...
---- margin_get_order_fills_parses_fee_bearing_trades stdout ----
thread '...' panicked at .../wiremock_tests.rs:1324:78:
called `Result::unwrap()` on an `Err` value: NotSupported
---- futures_get_order_fills_parses_realized_pnl stdout ----
thread '...' panicked at .../wiremock_tests.rs:1345:79:
called `Result::unwrap()` on an `Err` value: NotSupported
test result: FAILED. 28 passed; 4 failed; 0 ignored; 0 measured; 0 filtered out
```
Expected: `get_order_fills` had no Binance override yet, so both hit the
trait's `Err(NotSupported)` default. The two `_ops` failures are the
Task 2.4/2.5 placeholders, unrelated to this task.

**GREEN** (after implementation, full crate):

```
docker compose run --build --rm test cargo test -p exchange_adapter_binance --no-fail-fast
```
```
test result: ok. 106 passed; 0 failed; 0 ignored ...       (unit tests, incl. new parsing.rs cases)
test result: ok. 0 passed; 0 failed; 1 ignored ...          (testnet_integration.rs, #[ignore]'d)
test margin_get_order_fills_parses_fee_bearing_trades ... ok
test futures_get_order_fills_parses_realized_pnl ... ok
test spot_get_order_fills_parses_multiple_fills_with_mixed_maker_flags ... ok
test margin_place_order_never_sends_reduce_only_even_when_requested ... ok
test spot_get_order_parses_client_order_id ... ok
test margin_get_order_parses_client_order_id ... ok
test futures_get_order_parses_client_order_id ... ok
test open_orders_parses_client_order_id ... ok
test get_market_info_computes_precision_from_filter_scale ... ok
test futures_ops_set_leverage_returns_the_applied_leverage ... FAILED   (Task 2.5, untouched, expected)
test margin_ops_borrow_sends_borrow_repay_post_with_type_borrow ... FAILED  (Task 2.4, untouched, expected)
test result: FAILED. 36 passed; 2 failed; 0 ignored, 0 measured, 0 filtered out
```
The only failures are the two placeholders this task must not touch.

**Full workspace gate:**

```
docker compose run --build --rm test cargo test --workspace --no-fail-fast
```
```
error: 2 targets failed:
    `-p exchange_adapter_binance --test wiremock_tests`
    `-p market_data --test write_path`
```
`exchange_adapter_binance` failure = the same two expected 2.4/2.5 RED
cases. `market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database`
is the pre-existing flake named in TECH_DEBT §5; re-ran it isolated
(`cargo test -p market_data --test write_path
shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database --
--test-threads=1`) and it passed. Nothing in this diff touches
`market_data`.

No compiler warnings (`cargo build -p exchange_adapter_binance --tests`).

## Files changed

- `crates/exchange_adapter_binance/src/kind.rs` — `Endpoints.fills` per kind.
- `crates/exchange_adapter_binance/src/market.rs` — `get_order_fills` impl;
  updated `order_symbols`/`symbol_for` doc comments to mention the new caller.
- `crates/exchange_adapter_binance/src/parsing.rs` — `req_bool`,
  `parse_fill`/`parse_fills`, `client_order_id` in `parse_order_info`,
  `base_asset`/`quote_asset` in `parse_market_info`, plus unit tests.
- `crates/exchange_adapter_binance/tests/wiremock_tests.rs` — primed the
  two pre-existing fills RED tests, added the new tests listed above,
  fixed the stale Task 2.2 comment.

No changes outside `exchange_adapter_binance` — `orchestrator`,
`execution`, `market_data`, `mq_gateway` untouched (their `OrderInfo`
construction sites already set `client_order_id` from the prior task,
confirmed by grep before starting).

## Self-review findings

- All three kinds implemented and tested (spot/margin/futures fills;
  margin's `isIsolated=FALSE` asserted via `query_param`).
- Maker-flag spelling handled for both shapes (`isMaker` spot/margin vs
  `maker` futures) — each is a typed-error `req_bool`, not a fallback.
- `realized_pnl` is `None` on spot/margin (not parsed at all — no such
  field exists on those endpoints) and `Some` on futures, both asserted.
- Multi-fill response covered (spot test, 2 fills, mixed maker flags,
  non-quote fee asset).
- `clientOrderId` parsed on all three kinds, plus open-orders — 4 targeted
  wiremock tests, plus a parsing.rs unit test for the empty-string case.
- `base_asset`/`quote_asset` populated as required (typed-error) fields,
  not defaulted; a unit test proves a missing `baseAsset` is a typed
  error, not silently `""`.
- `// from docs — replace with capture` present on `parse_fill` and the
  `base_asset`/`quote_asset` extraction in `parse_market_info`, matching
  `errors.rs`'s established convention from Task 2.2.
- The two Task 2.4/2.5 RED tests (`margin_ops_borrow_sends_borrow_repay_post_with_type_borrow`,
  `futures_ops_set_leverage_returns_the_applied_leverage`) are byte-for-byte
  untouched — confirmed via the diff.
- No `cargo fmt` run on the crate; hand-formatted only the lines touched,
  matching surrounding style.
- No behaviour change in `orchestrator`/`execution`/`market_data`/`mq_gateway`.
- Did not implement margin ops (2.4) or futures ops (2.5) — confirmed by
  diff scope (only `kind.rs`, `market.rs`, `parsing.rs`, `wiremock_tests.rs`
  touched).

## Concerns

- The shape correction to the two pre-existing RED tests (adding a
  `place_order` priming call + request-param assertions) is a judgment
  call, flagged above rather than silently made. If the plan's author
  intended a different symbol-resolution path for `get_order_fills`
  (e.g. one that doesn't reuse `order_symbols`), that would need to be
  reconciled with `get_order`/`cancel_order`'s existing, documented
  constraint — I saw no such alternative in the spec or existing code.
- `base_asset`/`quote_asset`, the fills shapes, and `clientOrderId`'s
  parsing (all three now marked `// from docs — replace with capture`,
  see the fix-round note below) are unconfirmed against a real Binance
  response; Layer 7 is where that gets closed out, per the plan.

## Fix round 1/5 (review finding)

Review found the new `client_order_id` block in `parse_order_info`
(`crates/exchange_adapter_binance/src/parsing.rs`) was missing the
`// from docs — replace with capture` marker present on `parse_fill` and
the `base_asset`/`quote_asset` extraction — an equally new, equally
uncaptured doc-derived mapping that would otherwise silently survive
Layer 7's grep-for-marker capture-replacement pass.

**Fix**: added the marker immediately before the `.get("clientOrderId")`
call, in the same form/position as the other two (`parsing.rs`, in the
`parse_order_info` function, right after the existing explanatory
comment and before the field access). Re-audited the whole task diff
(`git diff 4420531 HEAD -- crates/exchange_adapter_binance/src/{kind,market,parsing}.rs`)
for any other new doc-derived response-field mapping lacking the marker:
none found. `kind.rs`'s new `fills` endpoint paths and `market.rs`'s new
`isIsolated=FALSE` request param are request-building, not response
parsing, and the marker convention (per `errors.rs`, Task 2.2) applies
to unconfirmed response-field mappings, not to request construction —
consistent with the existing (unmarked) `order`/`account`/`open_orders`
endpoint paths, which are equally unconfirmed but never carried the
marker either. Also corrected this report's Concerns section, which
previously listed only fills and base/quote assets as unconfirmed —
`client_order_id` belongs in that list too.

**Re-test** (`docker compose run --build --rm test cargo test -p exchange_adapter_binance --no-fail-fast`):
```
test result: ok. 106 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.21s   (unit tests)
test result: ok. 0 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out; finished in 0.00s      (testnet_integration.rs, #[ignore]'d)
test result: FAILED. 36 passed; 2 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.61s (wiremock_tests.rs)
test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s       (doc-tests)
```
The two wiremock failures are, unchanged, `futures_ops_set_leverage_returns_the_applied_leverage`
and `margin_ops_borrow_sends_borrow_repay_post_with_type_borrow` — the
Task 2.4/2.5 RED placeholders, still untouched. No new failures
introduced by the one-line fix.
