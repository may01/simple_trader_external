# Task 2.2 report — Error classification (Binance)

Branch: `live-trade-ops`. Commit: `4420531` `feat(binance): map exchange error codes to reject reasons`.

## What was implemented

- New `crates/exchange_adapter_binance/src/errors.rs`: `pub(crate) fn classify(http_status: u16, code: Option<i64>, message: &str) -> RejectReason`, built exactly from spec §4.6's Binance table. Every match arm and helper carries a `// from docs — replace with capture` marker (20 markers total: 17 on the main match's rows, 1 each in `classify_minus_2010`/`classify_minus_1013`/`classify_minus_1111`), plus prose in the module/function doc comments noting the same. No row is confirmed against a captured response yet, per the plan's fixture-capture rule.
  - `-2010`: "insufficient balance" (case-insensitive substring) → `InsufficientBalance`; anything else → `Unknown`.
  - `-2019` → `InsufficientMargin`.
  - `-1013`: message disambiguated by filter name — `PERCENT_PRICE…` → `PriceOutsideBand`, `PRICE_FILTER` → `InvalidPrice`, `LOT_SIZE`/`MARKET_LOT_SIZE` → `InvalidQuantity`, `MIN_NOTIONAL`/`NOTIONAL` → `BelowMinNotional`. `PERCENT_PRICE`/`PRICE_FILTER` are checked before the plain `LOT_SIZE`/`NOTIONAL` substring checks so none of the filter names can shadow another.
  - `-1111`: message mentions "price" → `InvalidPrice`; "quantity" → `InvalidQuantity`; neither → `Unknown` (the table only specifies these two disambiguations; a message matching neither falls through rather than guessing).
  - `-4131`/`-4016`/`-4024` → `PriceOutsideBand`; `-5022` → `PostOnlyWouldTake`; `-2022` → `ReduceOnlyRejected`; `-2013` → `OrderNotFound`; `-2011` → `OrderNotCancellable`; `-4028` → `LeverageNotAllowed`; `-4048`/`-4047` → `MarginModeChangeBlocked`; `-4046` → `AlreadySet`; `-3006` → `BorrowLimitExceeded`; `-3015` → `RepayExceedsDebt`; `-3045` → `AssetNotBorrowable`; `-2014`/`-2015`/`-1022` → `AuthFailed`; `-1021` → `ClockSkew`.
  - Any other code, or `code: None`, → `Unknown`.
  - `_http_status` is part of the signature per the brief's interface but unused by today's table (no row keys off HTTP status) — documented as such rather than silently dropped.
  - 24 unit tests, one per spec §4.6 row (message-disambiguated rows get one test covering both sides, e.g. `minus_1013_lot_size_and_market_lot_size_map_to_invalid_quantity` asserts both literal filter-name strings; `-4131`/`-4016`/`-4024` and `-2014`/`-2015`/`-1022` similarly assert all three codes in one row-test). Plus `unmapped_code_maps_to_unknown` and `missing_code_maps_to_unknown`.

- `crates/exchange_adapter_binance/src/rest.rs::classify_http_error`: now parses the Binance `{"code": i64, "msg": String}` error-body shape via a new private `extract_code_and_message`, routes `(code, message)` through `errors::classify`, and builds the `Rejection` with the real `reason`, `code` (stringified, verbatim), and `message` (the parsed `msg`, or — if the body isn't that shape at all — the whole raw body, so nothing is ever lost). 429/418 → `RateLimited` and 5xx → `Network` are untouched. Added 6 unit tests in a new `#[cfg(test)] mod tests` in `rest.rs` (this function is private, not exposed via `__test_support`): 429 and 418 → `RateLimited`, 5xx → `Network` (message preserved), a known code (`-2010`) mapping through `classify` with code/message/exchange/http_status all preserved, an unmapped code (`-9999`) still preserving code+message under `Unknown`, and a non-JSON body falling back to `(None, whole_body)`.

- `crates/exchange_adapter_binance/src/lib.rs`: added `mod errors;`.

## Carry-overs from Task 2.1's review (done)

1. `config.rs:63-65` — `host_url`'s doc comment named a nonexistent test `hosts_table_urls_parse`. Replaced with the actual test names that exercise every `hosts()` row (`spot_testnet_host_is_binance_vision`, `spot_mainnet_host_is_api_binance_com`, `margin_testnet_is_a_no_testnet_config_error`, `margin_mainnet_host_matches_spot`, `futures_testnet_host_is_binancefuture_com`, `futures_mainnet_host_is_fapi_binance_com`).
2. `resolve_hosts`'s two untested branches — added `rest_only_override_wins_for_rest_and_ws_falls_through_to_the_host_table` and `ws_only_override_wins_for_ws_and_rest_falls_through_to_the_host_table`, each calling `resolve_hosts` directly (it's private, tests live in the same file) and asserting the overridden half wins while the other half matches the host table's value.
3. `adapter.rs`'s `margin_on_testnet_without_override_fails_construction` — the `other` arm printed `other.is_ok()` (a bool) instead of the actual value. `ExchangeAdapterBinance` isn't `Debug`, so `Result<ExchangeAdapterBinance, AdapterError>` can't be `{:?}`-printed directly; fixed by matching on `other` and printing `"Ok(_)"` or `format!("{e:?}")` for the `Err` case, so a future failure shows which case actually happened.

## TDD evidence

**RED.** `errors.rs` was written with the full 24-test suite but a stubbed `classify` (`let _ = (code, message); RejectReason::Unknown`), wired into `lib.rs`, and run before any real mapping existed:

```
docker compose run --build --rm test cargo test -p exchange_adapter_binance errors:: --no-fail-fast
```
```
test result: FAILED. 3 passed; 21 failed; 0 ignored; 0 measured; 69 filtered out; finished in 0.00s
```
21 of 24 failed against the stub (3 passed "by accident" — the two tests that themselves expect `Unknown`, plus one row whose message happens not to match anything). Sample failure:
```
thread 'errors::tests::minus_3006_maps_to_borrow_limit_exceeded' (4532) panicked at crates/exchange_adapter_binance/src/errors.rs:218:9:
assertion `left == right` failed
  left: Unknown
 right: BorrowLimitExceeded
```
Expected: every row but the two `Unknown`-expecting ones must fail against a stub that always returns `Unknown` — confirms the tests are actually exercising the mapping logic, not vacuously true.

The pre-existing `minus_2010_body_classifies_to_insufficient_balance` in `wiremock_tests.rs` was already RED going into this task (per the task brief) — confirmed still RED before implementation (it was hitting `classify_http_error`'s old hard-coded `RejectReason::Unknown`).

**GREEN.** After filling in the real table:

```
docker compose run --build --rm test cargo test -p exchange_adapter_binance --no-fail-fast
```
- `--lib`: 101 passed, 0 failed (includes all 24 `errors::` tests, 6 new `rest::tests::*`, 2 new `config::tests::*` for the carry-over, and the fixed `margin_on_testnet_without_override_fails_construction`).
- `--test wiremock_tests`: 28 passed, 4 failed — the 4 failures are exactly `futures_get_order_fills_parses_realized_pnl`, `futures_ops_set_leverage_returns_the_applied_leverage`, `margin_get_order_fills_parses_fee_bearing_trades`, `margin_ops_borrow_sends_borrow_repay_post_with_type_borrow` (Tasks 2.3/2.4/2.5, untouched). `minus_2010_body_classifies_to_insufficient_balance` is now `ok`.

**Workspace gate:**
```
docker compose run --build --rm test cargo test --workspace --no-fail-fast
```
Only failing target: `exchange_adapter_binance --test wiremock_tests`, with exactly the same 4 known-RED failures (grepped the full log for `FAILED`/`failures:` — nothing else). `market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database` (the known TECH_DEBT §5 flake) passed (`ok`) on this run, so no isolation re-run was needed. No disk-space issues encountered.

## Files changed

- `crates/exchange_adapter_binance/src/errors.rs` (new)
- `crates/exchange_adapter_binance/src/rest.rs`
- `crates/exchange_adapter_binance/src/lib.rs`
- `crates/exchange_adapter_binance/src/config.rs`
- `crates/exchange_adapter_binance/src/adapter.rs`

## Self-review findings

- Verified every spec §4.6 row has both an implementation arm and a dedicated unit test; verified the message-disambiguated rows (`-1013` ×4, `-1111` ×2, `-2010` ×2) are genuinely distinguished, not just returning the same thing for both branches.
- Verified `-1013`'s substring checks are ordered so `PERCENT_PRICE…` and `PRICE_FILTER` are tested before the plainer `LOT_SIZE`/`NOTIONAL` checks — none of the six literal filter names can be misclassified by an unintended substring match.
- Verified unknown codes and unparseable bodies preserve `code`/`message` verbatim on `Rejection` (tested directly in `rest.rs`, since `classify` itself only returns a `RejectReason` and never sees `Rejection`).
- Verified 429/418 → `RateLimited` and 5xx → `Network` are byte-for-byte unchanged in behaviour (only reorganized which arm of the same `match` they fall in), and added regression tests pinning that.
- Verified `NotSupported` panics in the four Task 2.3/2.4/2.5 wiremock tests, and the `NoTestnet`-flavoured test, are untouched — diffed `wiremock_tests.rs` against HEAD before this task and confirmed zero changes there.
- Grepped the whole crate for other `Rejected(`/`Rejection {` construction sites — `rest.rs::classify_http_error` is the only one, so there's nowhere else in this crate silently bypassing `classify`.
- Confirmed `cargo tree` / dependency shape wasn't touched (only added `mod errors;`, no new crate dependencies — `serde`'s `derive` feature the new `BinanceErrorBody` struct needs was already enabled in `Cargo.toml`).
- Did not run `cargo fmt`; only new/edited lines follow the surrounding file's existing style.

## Concerns

- The exact Binance wire text for several rows (especially `-1111`'s price-vs-quantity disambiguation, whose real message may not literally contain the words "price"/"quantity") is genuinely unconfirmed — that's precisely what the `// from docs` markers flag for Layer 7 to correct. If a captured response contradicts a guess here (most likely `-1111`), Layer 7 should expect to adjust that one helper, not the overall table shape.
- None otherwise; scope was held to exactly this task (no fills/margin-ops/futures-ops touched, no behaviour change outside `exchange_adapter_binance`).
