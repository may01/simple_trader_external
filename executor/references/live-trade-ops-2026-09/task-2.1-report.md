# Task 2.1 report: Host table, config, `resolved_network`

Branch: `live-trade-ops`, worktree `layer-implementation`. Base commit before this task: `44c0d9c` (Task 1.4, "margin and futures ops extension traits").

## What was implemented

1. `pub fn hosts(network: Network, kind: MarketKind) -> Result<Hosts, ConfigError>` in `crates/exchange_adapter_binance/src/config.rs` -- the Binance host table from spec §4.3:
   - spot: testnet `testnet.binance.vision` / mainnet `api.binance.com` + `stream.binance.com:9443`
   - margin: testnet → `ConfigError::NoTestnet { exchange: Binance, kind: Margin }` (Binance has no margin testnet); mainnet same host as spot
   - futures: testnet `testnet.binancefuture.com` + `stream.binancefuture.com` / mainnet `fapi.binance.com` + `fstream.binance.com`
2. A private `resolve_hosts(network, kind, rest_override, ws_override) -> Result<(Hosts, ResolvedNetwork), ConfigError>` helper implementing the precedence rule: an explicit override (REST/WS independently) wins outright and bypasses the host table entirely (so a hand-set margin-testnet host, e.g. a wiremock server, never hits `NoTestnet`); otherwise `hosts(network, kind)` applies, which can itself error.
3. `BinanceAdapterConfig::new` now resolves every kind's hosts through `resolve_hosts` instead of the old "override required, testnet-default fallback" scheme. It resolves spot, then margin (purely to surface `NoTestnet` when it applies -- spot and margin always share one physical host so their resolved values agree whenever both succeed), then futures (from `extra["futures_rest_base_url"]`/`extra["futures_ws_base_url"]`, now genuinely optional -- no more `DEFAULT_FUTURES_*` fallback). `BinanceAdapterConfig` carries the resolved concrete `rest_base_url`/`ws_base_url`/`futures_rest_base_url`/`futures_ws_base_url` plus `resolved_network`/`futures_resolved_network` (`ResolvedNetwork`).
4. `impl ExchangeAdapterBinance { pub fn resolved_network(&self, kind: MarketKind) -> ResolvedNetwork }` in `adapter.rs`, backed by two new fields (`resolved_network`, `futures_resolved_network`) populated from the resolved config at construction time. `ExchangeAdapterBinance::new` no longer has an "override required" error path (Task 1.1 carry-over, deliverable #7) -- every host is already concrete by the time it runs.
5. `kind.rs`'s crate-private `MarketKind` enum is gone; it now re-exports `exchange_adapter::MarketKind` (`pub use exchange_adapter::MarketKind;`). `.tag()`/`.endpoints()` moved to a local extension trait `MarketKindExt` (an inherent `impl MarketKind` isn't legal for a foreign type -- orphan rule), implemented for the common type. Call sites (`adapter.rs`, `market.rs`, `ws.rs`) import `MarketKindExt` alongside `MarketKind`; `parsing.rs` only pattern-matches the enum, so it needed no import change.
6. Removed `DEFAULT_FUTURES_REST_BASE_URL`/`DEFAULT_FUTURES_WS_BASE_URL` and the stale doc comments claiming "every base URL defaults to testnet" and that `futures_ws_base_url` is "not yet consumed" (it is -- `adapter.rs` passes it to the futures `BinanceMarketAccount`). `config.rs`'s module doc now states the real precedence and that unset `EXCHANGE_NETWORK` means mainnet.
7. Carry-over from Task 1.4: replaced the deferral comment block (previously at the end of `crates/exchange_adapter_binance/tests/wiremock_tests.rs`, ~lines 1418-1432) with the real integration test `margin_on_testnet_without_override_is_a_no_testnet_config_error`, which builds a raw `AdapterConfig { network: Network::Testnet, rest_base_url: None, ws_base_url: None, .. }` and asserts `BinanceAdapterConfig::new` fails with `AdapterError::InvalidRequest` naming margin/testnet.

## Files changed

- `crates/exchange_adapter_binance/src/config.rs` -- rewritten: `hosts`, `resolve_hosts`, `BinanceAdapterConfig` (new fields, new `new()`), `config_err_to_adapter_err`, `parse_optional_extra_url`; in-file unit tests for every host-table row and precedence.
- `crates/exchange_adapter_binance/src/adapter.rs` -- `ExchangeAdapterBinance` gained `resolved_network`/`futures_resolved_network` fields and the `resolved_network(kind)` method; `new()` no longer unwraps `Option<Url>` with an `InvalidRequest` fallback; new `#[cfg(test)]` module.
- `crates/exchange_adapter_binance/src/kind.rs` -- `MarketKind` replaced by a re-export of `exchange_adapter::MarketKind`; `.tag()`/`.endpoints()` moved to a new `MarketKindExt` trait.
- `crates/exchange_adapter_binance/src/market.rs`, `src/ws.rs` -- one-line import changes to bring `MarketKindExt` into scope where `.tag()`/`.endpoints()` are called.
- `crates/exchange_adapter_binance/tests/wiremock_tests.rs` -- replaced the Task 1.4 deferral comment with the real `NoTestnet` carry-over test; the four other RED placeholders (`margin_get_order_fills_parses_fee_bearing_trades`, `futures_get_order_fills_parses_realized_pnl`, `margin_ops_borrow_sends_borrow_repay_post_with_type_borrow`, `futures_ops_set_leverage_returns_the_applied_leverage`) and `minus_2010_body_classifies_to_insufficient_balance` were not touched.

No changes were needed in `orchestrator`, `execution`, `market_data`, or `mq_gateway`: `orchestrator::main.rs::adapter_config_from_env` always supplies both `rest_base_url`/`ws_base_url` as `Some(..)`, which is the full-override branch of `resolve_hosts` and behaves exactly as before.

## TDD evidence

RED (before implementing `hosts`/`resolve_hosts`/the new `BinanceAdapterConfig`/`resolved_network`, with the deferral comment still in place and the old testnet-default code): the crate did not compile against the new test file until `hosts`, `resolve_hosts`, and the `BinanceAdapterConfig`/`ExchangeAdapterBinance` field changes existed -- e.g. before the change, `cargo test -p exchange_adapter_binance` failed to build once the new tests referenced `exchange_adapter_binance::config::hosts` and `ExchangeAdapterBinance::resolved_network`, exactly as the removed comment in `wiremock_tests.rs` predicted (referencing `hosts` before Task 2.1 is a hard compile error). The pre-existing `defaults_futures_urls_to_testnet_when_no_override_given` test (removed) encoded the old, now-wrong assumption ("no override → testnet").

GREEN, this crate in isolation:
```
$ cargo test -p exchange_adapter_binance
...
test result: ok. 69 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.6s   (lib)
test result: ok. 0 passed; 0 failed; 1 ignored ...                                                (testnet_integration.rs)
test result: FAILED. 27 passed; 5 failed ...                                                       (wiremock_tests.rs)
```
The 5 failures in `wiremock_tests.rs` are exactly the known-RED set named in the task brief (`futures_get_order_fills_parses_realized_pnl`, `futures_ops_set_leverage_returns_the_applied_leverage`, `margin_get_order_fills_parses_fee_bearing_trades`, `margin_ops_borrow_sends_borrow_repay_post_with_type_borrow`, `minus_2010_body_classifies_to_insufficient_balance`) -- untouched, unmodified, belonging to Tasks 2.2-2.5. The new carry-over test `margin_on_testnet_without_override_is_a_no_testnet_config_error` is **not** among the failures -- it went GREEN.

GREEN, full workspace gate:
```
$ docker compose run --build --rm test cargo test --workspace --no-fail-fast
```
Every crate/target passed except `exchange_adapter_binance --test wiremock_tests`, which failed with exactly the same 5 known-RED tests above and nothing else. Ran twice; the second run also had `market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database` pass (it's the known pre-existing flake, TECH_DEBT §5 -- it failed once, in the very first run of this session, and passed both in isolation and in the second full-workspace run, consistent with a flake rather than a regression). Isolation re-run: `cargo test -p market_data --test write_path shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database -- --exact` → `ok`.

## Self-review

- Every row of spec §4.3's Binance table has a direct `hosts()` unit test (`spot_testnet_host_is_binance_vision`, `spot_mainnet_host_is_api_binance_com`, `margin_testnet_is_a_no_testnet_config_error`, `margin_mainnet_host_matches_spot`, `futures_testnet_host_is_binancefuture_com`, `futures_mainnet_host_is_fapi_binance_com`), plus the `NoTestnet` row is re-tested at the `BinanceAdapterConfig::new` level, the `ExchangeAdapterBinance::new` level, and as the wiremock integration carry-over.
- Precedence tested including `Custom`: `rest_override_wins_over_mainnet_default`, `rest_override_wins_over_testnet_table_even_for_margin`, `futures_extra_override_wins_over_mainnet_default` (config.rs), `explicit_override_resolves_to_custom_never_mainnet_or_testnet` (adapter.rs).
- Grepped the crate for `DEFAULT_FUTURES`, "not yet consumed", "default every base URL", "testnet-by-default" -- no hits; all removed/corrected.
- No duplicate `MarketKind`: `kind.rs` re-exports the common type; verified by `cargo check` (no orphan-rule or type-mismatch errors) and by the full test run.
- The four Task 2.2-2.5 RED placeholders in `wiremock_tests.rs` are byte-for-byte untouched (confirmed via `git diff`, which shows only the deferral-comment block replaced).
- Caught and fixed a mistake of my own during self-review: an initial pass of `cargo fmt -p exchange_adapter_binance` reformatted `rest.rs`, `signing.rs`, `parsing.rs`, `market.rs`, `ws.rs`, and `tests/wiremock_tests.rs` far beyond this task's scope (a rustfmt-version/style mismatch against what's already committed, unrelated to this task). Reverted all of those to their committed form and re-applied only the one- or two-line import edits each file actually needed, per the plan's "do not restructure code outside the task" constraint. Final diff for those five files is exactly the intended one-line/two-line changes.
- Test output is pristine: no stray `dbg!`/`println!`, no `#[ignore]` added, no test weakened to pass.

## Concerns

- None blocking. One judgment call worth flagging: `BinanceAdapterConfig::new` resolves margin's hosts even though the concrete `Hosts` value it produces is discarded (only used to surface `NoTestnet`) -- this is intentional (spot and margin always agree when both succeed, since they share one Binance host by construction) but means margin's `resolve_hosts` call is redundant work on the success path. Left as-is for clarity/symmetry with the three-kind structure; not a correctness issue.
