# Task 1.1 Report: Common enums, config network, env loader

## Fix round 1/5 (review response)

Review verdict: spec PASS, one Important + one Minor finding.

**Important — `.expect()` panics replace an already-available typed error path.**
`crates/exchange_adapter_binance/src/adapter.rs` and `crates/exchange_adapter_mexc/src/lib.rs`
called `.expect("...")` on the now-optional `rest_base_url`/`ws_base_url` when resolving them
at construction time. Both `ExchangeAdapterBinance::new` and `ExchangeAdapterMexc::new` already
return `Result<Self, AdapterError>`, and `AdapterError::InvalidRequest` is the crates' existing
idiom for construction-time validation — so a missing override should surface as a typed error,
not panic the process.

Fix: replaced every `.expect(msg)` with `.ok_or_else(|| AdapterError::InvalidRequest(msg.into()))?`
in both files (3 sites in `exchange_adapter_mexc/src/lib.rs`: `spot_rest_base_url`,
`spot_ws_base_url`, `futures_rest_base_url`; 2 sites in `exchange_adapter_binance/src/adapter.rs`:
`rest_base_url`, `ws_base_url`). Behaviour for every current caller is unchanged — orchestrator and
every test fixture already always pass `Some(url)`, so the `Ok` path is identical; only the
previously-unreachable-in-practice `None` path changed from a panic to a normal `Err(AdapterError)`
returned from `new(..)`.

**Minor — clone-before-check ordering in `exchange_adapter_mexc/src/lib.rs`.**
The three sites above used `.clone().expect(...)` (clone the whole `Option<Url>`, then check).
Reworked to `.as_ref().ok_or_else(...)?.clone()` — check for `None` first via a borrow, then clone
only the `Url` once its presence is confirmed.

Not addressed (per reviewer's explicit ruling, no action needed): the `market_data` shutdown-timeout
flake — pre-existing, tracked in TECH_DEBT §5, outside this diff.

### Tests re-run after the fix

Command (the two adapter crates' suites, as the reviewer asked for):

```
docker compose run --build --rm test cargo test -p exchange_adapter_binance -p exchange_adapter_mexc
```

Output (test-result summary lines, in run order):

```
test result: ok. 53 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s   (exchange_adapter_binance unit tests)
test result: ok. 0 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out; finished in 0.00s     (testnet_integration.rs — gated, unchanged)
test result: ok. 26 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.67s    (wiremock_tests.rs)
test result: ok. 73 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.14s    (exchange_adapter_mexc unit tests)
test result: ok. 7 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.20s      (futures_wiremock_tests.rs)
test result: ok. 0 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out; finished in 0.00s     (live_credentials.rs — gated, unchanged)
test result: ok. 11 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.25s    (spot_wiremock_tests.rs)
test result: ok. 10 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.59s    (wiremock_tests.rs)
test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s     (Doc-tests exchange_adapter_binance)
test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s     (Doc-tests exchange_adapter_mexc)
```

All green, no new warnings. Also re-ran `docker compose run --build --rm test cargo build --workspace`
to confirm the ripple (orchestrator's construction call sites are unaffected — it never hits the
`None` branch since it always supplies `Some(url)`) still compiles clean: only the two pre-existing,
unrelated warnings (`local_analysis::PLACEHOLDER_STOP_LOSS_PCT` dead code, `mq_gateway::inbound_lagged_total`
dead code) appeared, same as before this task touched anything.

Commit: `f77da56` "fix(exchange_adapter): typed error instead of panic for missing host override" on branch `live-trade-ops`, local only.

---

## Summary

Implemented exactly the interface in the brief:
- `crates/exchange_adapter/src/config.rs` (new): `MarketKind`, `Exchange`, `Network`, `ResolvedNetwork`, `Hosts`, `ConfigError`, `AdapterConfig` (moved here from `lib.rs`, now with `network: Network` and `rest_base_url`/`ws_base_url` as `Option<Url>` overrides), `AdapterConfig::from_env`/`from_env_with`.
- `crates/exchange_adapter/src/lib.rs`: removed the old `AdapterConfig` struct + its `Debug` impl and duplicate test, added `mod config;` and `pub use config::{AdapterConfig, ConfigError, Exchange, Hosts, MarketKind, Network, ResolvedNetwork};`, dropped now-unused `HashMap`/`SecretString`/`Url` imports.
- Compile-only ripples (behaviour identical, per the plan's constraint): `exchange_adapter_binance/src/adapter.rs`, `exchange_adapter_binance/src/config.rs` (test fixture), `exchange_adapter_mexc/src/lib.rs` (construction + test fixture), `orchestrator/src/main.rs::adapter_config_from_env`, and all five test files that construct `AdapterConfig` literals directly (`exchange_adapter_binance/tests/{testnet_integration,wiremock_tests}.rs`, `exchange_adapter_mexc/tests/{live_credentials,spot_wiremock_tests,futures_wiremock_tests,wiremock_tests}.rs`).
- No new dependency added to `exchange_adapter/Cargo.toml` — it stays a leaf crate (confirmed via `git diff`, empty).
- No host table implemented anywhere (per the brief's explicit scope note); `Hosts`/`ConfigError::NoTestnet`/`ResolvedNetwork` are defined but unused until later tasks.

## Design notes / decisions

- `AdapterConfig` deliberately does **not** derive `PartialEq` (its `SecretString` fields don't, by design of the `secrecy` crate — comparing secrets is a footgun). Tests that need to assert on error variants use `matches!` instead of `assert_eq!` on the whole `Result`.
- `EXCHANGE_NETWORK`: unset → `Mainnet`; `"testnet"` → `Testnet`; `"mainnet"` → `Mainnet`; anything else, including `""` (present-but-empty is distinct from absent) → `ConfigError::Invalid { var: "EXCHANGE_NETWORK", .. }`. No other default was added.
- Every ripple site that used to consume `rest_base_url`/`ws_base_url` as bare `Url` now `.expect()`s the `Option` at the point of use, with a comment explaining why (no per-exchange host table exists yet — that's tasks 2.x/3.x) — this preserves today's behaviour exactly, since every current caller (orchestrator, and every test) already always supplies both.
- `orchestrator::adapter_config_from_env` still requires its own `{prefix}REST_BASE_URL`/`{prefix}WS_BASE_URL` env vars directly (does not call the new `AdapterConfig::from_env`) and passes them as `Some(url)` with `network: Network::Mainnet` — per the task's explicit instruction not to move behaviour into it yet.
- `exchange_adapter_binance/tests/testnet_integration.rs` and its `config.rs` test fixture now say `network: Network::Testnet` (cosmetic — the field is destructured as `_network` and ignored until task 2.1, but it matches the testnet hosts already in use there). All other test fixtures (mainnet/wiremock hosts) use `Network::Mainnet`.

## TDD evidence

**RED** — wrote all 14 unit tests in `config.rs` first, temporarily stubbed `from_env_with`'s body with `unimplemented!()`, added `mod config;` to `lib.rs`, ran:

```
docker compose run --build --rm test cargo test -p exchange_adapter config::
```

First pass caught two real test bugs (a missing lifetime on the `lookup` helper, and `assert_eq!` on `Result<AdapterConfig, _>` which doesn't compile since `AdapterConfig` intentionally has no `PartialEq`); fixed those, then re-ran to get genuine RED:

```
test config::tests::malformed_override_url_is_invalid ... FAILED
...
thread 'config::tests::malformed_override_url_is_invalid' panicked at crates/exchange_adapter/src/config.rs:167:9:
not implemented: TDD RED: from_env_with not yet implemented
...
test result: FAILED. 1 passed; 13 failed; 0 ignored; 0 measured; 11 filtered out; finished in 0.00s
```

(1 passed = `debug_never_prints_secrets`, which doesn't call `from_env_with`.)

**GREEN** — restored the real `from_env_with` body, re-ran the same command:

```
docker compose run --build --rm test cargo test -p exchange_adapter config::
...
running 14 tests
test config::tests::debug_never_prints_secrets ... ok
test config::tests::missing_api_key_reports_the_var_name ... ok
test config::tests::malformed_override_url_is_invalid ... ok
test config::tests::missing_api_secret_reports_the_var_name ... ok
test config::tests::network_mainnet_value_selects_mainnet ... ok
test config::tests::network_testnet_value_selects_testnet ... ok
test config::tests::network_unrecognized_word_is_invalid ... ok
test config::tests::network_unset_defaults_to_mainnet ... ok
test config::tests::network_uppercase_mainnet_is_invalid_not_a_fallback ... ok
test config::tests::no_override_url_present_is_none ... ok
test config::tests::network_empty_string_is_invalid_not_unset ... ok
test config::tests::prefix_is_honoured_for_missing_key ... ok
test config::tests::override_url_present_is_some_parsed_url ... ok
test config::tests::prefix_is_honoured_when_present ... ok

test result: ok. 14 passed; 0 failed; 0 ignored; 0 measured; 11 filtered out; finished in 0.00s
```

Then wired up the ripple sites (binance/mexc/orchestrator + their test fixtures) so the whole workspace compiles again.

## GREEN — full gate

```
docker compose run --build --rm test
```

Ran twice. First run had one failure (`market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database`), which I isolated and confirmed flaky/unrelated:

```
docker compose run --build --rm test cargo test -p market_data --test write_path shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database
...
test shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database ... ok
```

Passes in isolation both times it was checked; `market_data` is untouched by this diff and out of this task's scope. The global-constraints doc explicitly calls out that a concurrent baseline `docker compose run` may contend for resources during this branch's work, which is the most likely explanation.

Second full-gate run also showed this same single test flake (and nothing else) — every `exchange_adapter*`/`orchestrator` test binary was green in both runs:

- `exchange_adapter` unit tests: 24 passed (was 10 before this task; +14 new `config::tests`).
- `exchange_adapter_binance` unit tests: 53 passed; `testnet_integration.rs`: 0 passed/1 ignored (gated, unchanged); `wiremock_tests.rs`: 26 passed.
- `exchange_adapter_mexc` unit tests: 73 passed; `futures_wiremock_tests.rs`: 7 passed; `live_credentials.rs`: 0 passed/1 ignored (gated, unchanged); `spot_wiremock_tests.rs`: 11 passed; `wiremock_tests.rs`: 10 passed.
- `orchestrator` unit tests: 42 passed.

No new warnings from `cargo build --workspace` or `cargo build -p exchange_adapter` (checked both; the one `unused import: url::Url` warning I introduced mid-refactor was cleaned up before the final build).

## Files changed

- `crates/exchange_adapter/src/config.rs` (new)
- `crates/exchange_adapter/src/lib.rs`
- `crates/exchange_adapter_binance/src/adapter.rs`
- `crates/exchange_adapter_binance/src/config.rs`
- `crates/exchange_adapter_binance/tests/testnet_integration.rs`
- `crates/exchange_adapter_binance/tests/wiremock_tests.rs`
- `crates/exchange_adapter_mexc/src/lib.rs`
- `crates/exchange_adapter_mexc/tests/futures_wiremock_tests.rs`
- `crates/exchange_adapter_mexc/tests/live_credentials.rs`
- `crates/exchange_adapter_mexc/tests/spot_wiremock_tests.rs`
- `crates/exchange_adapter_mexc/tests/wiremock_tests.rs`
- `crates/orchestrator/src/main.rs`

Commit: `aab8116` "feat(exchange_adapter): common kinds, network selection, env config loader" on branch `live-trade-ops` (local only — not pushed, not merged).

## Self-review findings

- Checked `git diff crates/exchange_adapter/Cargo.toml` is empty — no new workspace dependency, leaf crate constraint honoured.
- Grepped for every remaining `AdapterConfig {` struct-literal site across `crates/` after the edits — all 12 sites accounted for and updated (2 in `config.rs` itself, 10 ripple sites).
- Confirmed `MarketKind`/`ResolvedNetwork`/`Hosts`/`ConfigError::NoTestnet` compile clean with zero dead-code warnings once re-exported at the crate root (they were warning as dead code while only `mod config;` — private — existed, during the RED phase; resolved once `pub use` was added).
- Binance's existing crate-private `kind::MarketKind` (`exchange_adapter_binance/src/kind.rs`) was left untouched, as instructed — task 2.1's job, not this one.
- Verified test quality: every new test in `config.rs` uses `from_env_with` with a `HashMap`-backed closure; grepped the whole new/changed test surface for `std::env::set_var`/`remove_var` — none found.
- `AdapterConfig` intentionally has no `Eq`/`PartialEq` (matches `secrecy::SecretString`'s own choice not to implement it); tests that assert on error paths use `matches!` rather than `assert_eq!` on the whole `Result`.

## Concerns

- The one test failure seen across two full-gate runs (`market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database`) is outside this task's crate boundary and reproducibly passes in isolation — flagging in case it recurs for a later task's baseline check, but it is not a regression introduced here.
- `rest_base_url`/`ws_base_url` are now `.expect()`-panicking at construction time in `exchange_adapter_binance`/`exchange_adapter_mexc` if absent. This is intentional (behaviour-preserving: every current caller already supplies both) but means a caller that adopts `AdapterConfig::from_env` without providing override URLs will panic at adapter construction, not get a `ConfigError` — that's expected to be fixed by the host-table tasks (2.1/3.x), not this one.
