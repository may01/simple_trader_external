# Task 4.1 report: crate, registry, `test` service

## What was implemented

New crate `crates/live_trade_ops` (workspace member added), containing:

- `Cargo.toml` -- depends on `exchange_adapter`, `exchange_adapter_binance`, `exchange_adapter_mexc`, `observability`. No dev-dependencies were needed (all tests are sync, no async/tokio, no DB).
- `src/lib.rs` -- crate doc explaining the two one-way-dependency rules (nothing depends on this crate; only `registry` may import the two adapter crates) and re-exports `pub mod registry;`.
- `src/registry.rs`:
  - `BuiltAdapter` enum (`Binance(Arc<ExchangeAdapterBinance>)` / `Mexc(Arc<ExchangeAdapterMexc>)`) with `adapter() -> Arc<dyn ExchangeAdapter>`, `exchange() -> Exchange`, `resolved_network(kind) -> ResolvedNetwork`.
  - `parse_market_kind(raw) -> Result<MarketKind, ConfigError>` (`spot`/`margin`/`futures`, else `Invalid`).
  - `build_adapter_from_env(kind, metrics, alerts) -> Result<BuiltAdapter, ConfigError>`, delegating to `build_adapter_from_env_with(..., get)` (the real, env-backed entry point uses `|k| std::env::var(k).ok()`; tests always use the `_with` form with a map closure -- no process-env mutation, matches Layer 1's convention).
  - Reads `EXCHANGE` (`binance`/`mexc`, else `ConfigError::Invalid`; unset -> `ConfigError::Missing("EXCHANGE")`).
  - Builds each exchange's config via `exchange_adapter::AdapterConfig::from_env_with` (prefix `""`; MEXC's futures leg also reads prefix `"FUTURES_"`, mirroring `orchestrator/src/main.rs::adapter_config_from_env`'s doc comment on why MEXC futures gets its own credential prefix).
  - `validate_supported(exchange, network, kind)`: a small, explicitly-documented mirror of just the two "no testnet" facts from spec §4.3 (Binance margin; MEXC, any kind) -- checked **before** any adapter is constructed. This exists because `exchange_adapter_binance::config::hosts`/`exchange_adapter_mexc::config::hosts` are both private to their crates (not re-exported), and Binance's own constructor resolves spot+margin+futures unconditionally in one call, so a construction failure there isn't necessarily about the `kind` the caller actually asked for. Pre-checking the two known combinations lets an unsupported request fail immediately, before any adapter object is built at all, with a precise typed `ConfigError::NoTestnet { exchange, kind }` -- not by pattern-matching the adapter's own error string.
  - `adapter_err_to_config_err`: any other adapter-construction failure (bad override URL, etc.) surfaces as `ConfigError::Invalid`, carrying the `AdapterError`'s `Display` text.
- `tests/no_adapter_imports.rs`: walks `src/` recursively, skips `registry.rs`, greps every other `.rs` file's raw text for `exchange_adapter_binance`/`exchange_adapter_mexc` (a literal substring match, not `use`-only -- catches even a doc-comment mention, per the brief's "mentions" wording).
- `docker-compose.yml`: `test` service's `environment` gained the 14 pass-through vars from the plan's Docker Entry Points section, each `${VAR:-}`: `LIVE_TRADE_OPS`, `LIVE_PAIR`, `LIVE_MAX_NOTIONAL`, `LIVE_WAIT_SECS`, `LIVE_RUN_ID`, `LIVE_REQUIRE_ALL`, `EXCHANGE`, `EXCHANGE_NETWORK`, `MARKET_KIND`, `API_KEY`, `API_SECRET`, `FUTURES_API_KEY`, `FUTURES_API_SECRET`, `DATABASE_URL`. `test`'s `command` is unchanged (`["cargo", "test", "--workspace"]`); `executor` was not touched.
- `Cargo.toml` (workspace) / `Cargo.lock`: `crates/live_trade_ops` added to `members`.

Not implemented (correctly out of scope for this task): `settle`, `risk`, `journal`, `harness`, `scenarios`, `fake`, `tests/live_trade_ops.rs`, migration 0008.

## A subtlety worth flagging (self-review finding, resolved, no code change needed)

`ExchangeAdapterBinance::new` resolves spot, margin *and* futures hosts unconditionally in one call (all three sub-accounts always get built). On `EXCHANGE_NETWORK=testnet` with no `REST_BASE_URL`/`WS_BASE_URL` override, that construction **always** fails on margin's `NoTestnet` -- regardless of which `kind` the caller actually wants -- because margin resolution happens before the requested kind is even considered. This means the brief's "same with Futures -> Ok, resolved_network(Futures) == Testnet" test case is only reachable by supplying a `REST_BASE_URL`/`WS_BASE_URL` override (which bypasses spot+margin's shared host resolution while leaving futures to resolve through its own table row) -- exactly the same workaround `exchange_adapter_binance`'s own `testnet_network_resolves_spot_and_futures_to_testnet` test already uses. My test `binance_futures_on_testnet_is_ok_and_resolves_to_testnet` does this and documents why in its own comment. This is an existing property of `exchange_adapter_binance` (Layer 2, not touched here), not something this task's code introduced or should paper over.

## TDD evidence

**RED** -- `parse_market_kind`/`build_adapter_from_env_with` bodies were temporarily stubbed to always return `Err(ConfigError::Missing("RED_STUB"))` (backed up first, restored after). Command: `cargo test -p live_trade_ops --no-fail-fast` (run locally; rustc/cargo 1.94, same as the `test` image's `rust:1.94-slim` base).

```
test registry::tests::binance_margin_on_testnet_is_no_testnet ... FAILED
  left: Some(Missing("RED_STUB"))  right: Some(NoTestnet { exchange: Binance, kind: Margin })
test registry::tests::exchange_unset_is_a_missing_config_error ... FAILED
test registry::tests::exchange_unknown_is_an_invalid_config_error ... FAILED
test registry::tests::mexc_testnet_is_no_testnet_for_any_kind ... FAILED
test registry::tests::mexc_defaults_resolve_to_mainnet_hosts_and_reads_futures_prefix ... FAILED
test registry::tests::mexc_missing_futures_credentials_is_a_missing_config_error ... FAILED
test registry::tests::binance_defaults_resolve_to_mainnet_hosts ... FAILED
test registry::tests::binance_futures_on_testnet_is_ok_and_resolves_to_testnet ... FAILED
test registry::tests::binance_adapter_is_usable_as_the_common_trait_object ... FAILED
test registry::tests::parse_market_kind_accepts_the_three_known_words ... FAILED
test registry::tests::parse_market_kind_rejects_anything_else ... FAILED
test result: FAILED. 0 passed; 11 failed; 0 ignored
```

All 11 failed for the expected reason (stub always returns the wrong/generic error instead of the real, specific one) -- no test passed vacuously.

While the stub was in place, `tests/no_adapter_imports.rs` **also** failed once, for a genuine reason: `lib.rs`'s own doc comment named `exchange_adapter_binance`/`exchange_adapter_mexc` in prose, which the (deliberately literal, per the brief's "mentions" wording) grep flagged. Fixed by rewording the doc comment to say "the two per-exchange adapter crates" instead of spelling the names out. Re-ran and it passed on its own, confirming the guard test's baseline is clean before any real registry code existed.

**GREEN** -- real implementation restored, same command:

```
$ cargo test -p live_trade_ops --no-fail-fast
running 11 tests
test registry::tests::binance_margin_on_testnet_is_no_testnet ... ok
test registry::tests::exchange_unknown_is_an_invalid_config_error ... ok
test registry::tests::exchange_unset_is_a_missing_config_error ... ok
test registry::tests::mexc_missing_futures_credentials_is_a_missing_config_error ... ok
test registry::tests::mexc_testnet_is_no_testnet_for_any_kind ... ok
test registry::tests::parse_market_kind_accepts_the_three_known_words ... ok
test registry::tests::parse_market_kind_rejects_anything_else ... ok
test registry::tests::binance_adapter_is_usable_as_the_common_trait_object ... ok
test registry::tests::mexc_defaults_resolve_to_mainnet_hosts_and_reads_futures_prefix ... ok
test registry::tests::binance_futures_on_testnet_is_ok_and_resolves_to_testnet ... ok
test registry::tests::binance_defaults_resolve_to_mainnet_hosts ... ok
test result: ok. 11 passed; 0 failed

     Running tests/no_adapter_imports.rs
test no_file_other_than_registry_rs_imports_an_adapter_crate ... ok
```

## Self-review checklist (per the task's instructions)

- Every listed registry test present: unset/unknown `EXCHANGE`; Binance testnet+margin -> `NoTestnet`; Binance testnet+futures -> `Ok` with `resolved_network(Futures) == Testnet`; MEXC+testnet -> `NoTestnet`; Binance defaults -> mainnet hosts. All present, all green. Two extra tests added beyond the minimum (`binance_adapter_is_usable_as_the_common_trait_object` -- proves the `Arc<dyn ExchangeAdapter>` coercion actually works and both ops traits are `Some`; `mexc_missing_futures_credentials_is_a_missing_config_error` -- proves the `FUTURES_` prefix is actually read, and that a testnet short-circuit happens before those credentials are even requested).
- Guard test proven to genuinely fire: temporarily added a one-line reference to `exchange_adapter_binance::ExchangeAdapterBinance::new` inside `lib.rs`, ran `cargo test -p live_trade_ops --test no_adapter_imports`, confirmed it failed naming `src/lib.rs`, then reverted the addition and reran clean.
- `cargo tree -i live_trade_ops` output: `live_trade_ops v0.1.0 (.../crates/live_trade_ops)` -- itself only, no workspace crate listed as a dependent.
- `docker compose config` before/after this change: `executor`, `postgres`, `visualizer` services byte-identical (compared as parsed YAML); `test`'s `command` unchanged; `test`'s `environment` gained exactly the 14 new keys, each resolving to empty string (unset on this host), nothing else changed.
- `cargo clippy -p live_trade_ops --all-targets`: zero warnings from this crate's own code (fixed one `match_like_matches_macro` lint in `validate_supported` during review, before the final gate run). Remaining clippy warnings in the workspace are pre-existing, in `exchange_adapter_binance`/`exchange_adapter_mexc`'s `ws.rs`, untouched by this task.
- Gate: `docker compose run --build --rm test cargo test --workspace --no-fail-fast` -- every target green except `market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database`, which failed once and then passed 3/3 in isolated re-runs (`docker compose run --rm test cargo test -p market_data --test write_path shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database -- --exact`), consistent with the known TECH_DEBT §5 flake named in the task instructions -- not something this change introduced.
- No `cargo fmt` run on any crate; only the lines this task wrote were manually formatted.
- No behaviour change to `orchestrator`, `execution`, `market_data`, `mq_gateway`, or either adapter crate -- none of their files were touched.

## Files changed

- `Cargo.toml` (workspace members)
- `Cargo.lock` (new crate entry)
- `docker-compose.yml` (`test` service environment only)
- `crates/live_trade_ops/Cargo.toml` (new)
- `crates/live_trade_ops/src/lib.rs` (new)
- `crates/live_trade_ops/src/registry.rs` (new)
- `crates/live_trade_ops/tests/no_adapter_imports.rs` (new)

## Concerns for the reviewer

1. `validate_supported`'s two-case table duplicates a fact that also lives (correctly, as the authoritative source) inside each adapter crate's own private `hosts()` table. This duplication is deliberate and scoped to exactly the two documented "no testnet" exceptions in spec §4.3 -- it is not a general host table, and it is the only way this registry can produce a precise `ConfigError::NoTestnet` before construction, given that `hosts()` is private in both adapter crates and Binance's constructor validates all three kinds unconditionally regardless of the requested one. If spec §4.3's table ever grows a new "no testnet" exception, this function needs a matching new arm -- there's no way around that without changing the (out-of-scope) adapter crates to expose their tables publicly.
2. `build_adapter_from_env_with`'s `Exchange::Local` match arm is unreachable in practice (this registry's own `parse_exchange` never produces it) but is there for exhaustiveness over the shared `exchange_adapter::Exchange` enum, whose third variant belongs to `NoTradeAccount`. Returns a typed error rather than `unreachable!()`, per the "typed errors, never panics" constraint.

---

## Fix round 1/5: Binance margin's NoTestnet must not block a Futures-only testnet build

### The defect

Concern 1 from the original report was load-bearing, not cosmetic: `ExchangeAdapterBinance::new` resolved spot, margin, and futures hosts unconditionally in one call. On `EXCHANGE_NETWORK=testnet` with no `REST_BASE_URL`/`WS_BASE_URL` override, margin's resolution *always* failed (`ConfigError::NoTestnet`, surfaced as `AdapterError::InvalidRequest`), aborting construction of the whole adapter -- even when the caller only wanted `Futures`. This meant Task 7.2's first live run (Binance futures testnet) could never build an adapter through this registry without a URL override that has nothing to do with futures. The coordinator ruled this must be fixed in the adapter, not worked around in the registry.

### What changed in the adapters

**`crates/exchange_adapter_binance/src/config.rs`:**
- Added `resolve_kind(network, kind, rest_override, ws_override) -> Result<Option<(Hosts, ResolvedNetwork)>, AdapterError>`: calls the existing `resolve_hosts`, turning exactly `ConfigError::NoTestnet` into `Ok(None)` and propagating every other error (a malformed override URL, etc.) as a hard `AdapterError` via the existing `config_err_to_adapter_err`.
- `BinanceAdapterConfig`'s `rest_base_url`/`ws_base_url`/`resolved_network` and the `futures_*` equivalents are replaced by three uniform fields: `pub spot: Option<(Hosts, ResolvedNetwork)>`, `pub margin: Option<(Hosts, ResolvedNetwork)>`, `pub futures: Option<(Hosts, ResolvedNetwork)>`. `BinanceAdapterConfig::new` now calls `resolve_kind` for all three kinds instead of `resolve_hosts` + discard-and-propagate-error-only for margin.

**`crates/exchange_adapter_binance/src/adapter.rs`:**
- `ExchangeAdapterBinance`'s `spot`/`margin`/`futures` fields become `Option<BinanceMarketAccount>`; `margin_ops`/`futures_ops` become `Option<BinanceMarginOps>`/`Option<BinanceFuturesOps>`; the two `resolved_network` fields split into three (`spot_resolved_network`, `margin_resolved_network`, `futures_resolved_network`), each `Option<ResolvedNetwork>`.
- `new()` builds each kind independently: `None` in `BinanceAdapterConfig` means the `BinanceRestClient`/account/ops for that kind are never constructed at all (no wasted HTTP client, no dial). A genuine failure building the client (e.g. `AdapterError::Network` from `reqwest::Client::builder().build()`) for a kind that *does* have a host still propagates via `?` and fails construction loudly -- only the "no host" case became soft.
- `resolved_network(&self, kind: MarketKind) -> Option<ResolvedNetwork>` (was `-> ResolvedNetwork`): `None` when that kind wasn't built, in lockstep with the account itself.
- `ExchangeAdapter::spot()`/`margin()`/`futures()`/`margin_ops()`/`futures_ops()` now return `self.<field>.as_ref().map(|x| x as &dyn Trait)` instead of always `Some(&self.<field>)`.

**`crates/exchange_adapter_mexc/src/lib.rs`** (MEXC has no testnet for *any* kind, so this is the same fix applied symmetrically):
- Added the same `resolve_kind` helper (mirroring Binance's, using `resolve_hosts` from `config.rs`).
- `ExchangeAdapterMexc`'s `spot`/`margin` fields become `Option<SpotStyleAccount>` (margin always mirrors spot's `Option` outcome exactly, since MEXC margin shares spot's host per `NOTES.md` §2 -- no separate resolution needed for margin), `futures` becomes `Option<FuturesAccount>`, and both `resolved_network` fields become `Option<ResolvedNetwork>`.
- `new()` now builds spot+margin as one unit (both present or both absent) and futures independently; `resolved_network(kind) -> Option<ResolvedNetwork>`; `spot()`/`margin()`/`futures()` follow the same `.as_ref().map(...)` pattern as Binance.
- Construction on `EXCHANGE_NETWORK=testnet` now succeeds with every accessor `None`, rather than failing outright -- this is the "MEXC unaffected in substance" case the coordinator's ruling anticipated.

### What the registry no longer duplicates

`crates/live_trade_ops/src/registry.rs`: removed `validate_supported`, the two-row table mirroring spec §4.3's "no testnet" facts (Binance margin; MEXC, any kind) that Concern 2 flagged. In its place, `ensure_kind_supported(exchange, adapter, kind)` builds the adapter first (`build_binance`/`build_mexc`, now with no pre-check at all), then asks the adapter itself -- via the same `spot()`/`margin()`/`futures()` accessors every other caller uses -- whether the requested `kind` came back `Some`. `None` becomes `ConfigError::NoTestnet { exchange, kind }`. Spec §4.3's facts now live in exactly one place: the adapters' own host tables.

`build_adapter_from_env_with`'s shape changed slightly: `build_binance`/`build_mexc` no longer take `kind` (they don't need it to build -- both adapters always attempt every kind they know about and let the missing ones come back absent); `kind` is only consulted once, by `ensure_kind_supported`, after the adapter exists.

### Covering tests

**`crates/exchange_adapter_binance/src/config.rs`** (`#[cfg(test)] mod tests`):
- `testnet_network_with_no_override_leaves_margin_absent` (new): `Network::Testnet`, no override -> `config.margin.is_none()`, `config.spot.is_some()`, `config.futures.is_some()`.
- `testnet_network_with_no_override_resolves_futures_to_testnet_host` (rewritten): no longer needs `REST_BASE_URL`/`WS_BASE_URL` at all.
- `rest_override_wins_over_testnet_table_even_for_margin` (updated wording/assertions): override still resolves margin to `Custom`, now framed against "absent" rather than "erroring" as the no-override case.
- Removed `testnet_network_without_override_fails_construction_with_no_testnet_for_margin` (asserted the old hard-fail; no longer true).
- Added a small `hosts_of`/`resolved_of` test helper for the new `Option<(Hosts, ResolvedNetwork)>` shape.

**`crates/exchange_adapter_binance/src/adapter.rs`** (`#[cfg(test)] mod tests`):
- `testnet_network_resolves_spot_and_futures_to_testnet_with_no_override_needed` (rewritten, dropped the override): proves spot/futures both resolve on testnet with zero configuration beyond `EXCHANGE_NETWORK=testnet`.
- `margin_on_testnet_without_override_is_absent_while_spot_and_futures_are_not` (replaces `margin_on_testnet_without_override_fails_construction`): construction succeeds; `margin()`/`margin_ops()` are `None`; `resolved_network(Margin)` is `None`; `spot()`/`futures()`/`futures_ops()` are `Some`. This is the test the ruling's point 4 asked for directly.
- `mainnet_default_resolves_every_kind_to_mainnet`, `explicit_override_resolves_to_custom_never_mainnet_or_testnet`: mechanically updated to `Some(...)`.

**`crates/exchange_adapter_binance/tests/wiremock_tests.rs`**: `margin_on_testnet_without_override_is_a_no_testnet_config_error` (asserted `BinanceAdapterConfig::new(...).expect_err(...)`) replaced by `margin_on_testnet_without_override_is_absent_while_spot_and_futures_are_not`, which builds the full `ExchangeAdapterBinance` and asserts `margin()`/`margin_ops()` are `None` while `spot()`/`futures()` are `Some`.

**`crates/exchange_adapter_mexc/src/lib.rs`** (`mod construction_tests`):
- `testnet_leaves_spot_and_margin_absent_but_construction_still_succeeds`, `testnet_leaves_futures_absent_too_but_construction_still_succeeds`, `testnet_on_every_kind_leaves_every_accessor_absent` (new) replace `exchange_network_testnet_fails_construction_with_no_testnet`/`..._for_futures_too`, which asserted the old hard-fail.
- `unset_network_resolves_every_kind_to_mainnet_hosts_without_any_override`, `explicit_override_resolves_to_custom_even_on_a_network_that_would_otherwise_be_no_testnet`: mechanically updated to `Option`.

**`crates/live_trade_ops/src/registry.rs`**:
- `binance_futures_on_testnet_is_ok_and_resolves_to_testnet_with_no_override_needed` (renamed from `..._and_resolves_to_testnet`, override lines dropped): this is the test that directly proves the defect is fixed -- `EXCHANGE=binance`, `EXCHANGE_NETWORK=testnet`, `MarketKind::Futures`, **no** `REST_BASE_URL`/`WS_BASE_URL`, and it now returns `Ok`.
- `binance_margin_on_testnet_is_no_testnet`, `mexc_testnet_is_no_testnet_for_any_kind`: unchanged in intent, still assert `ConfigError::NoTestnet`, now produced via `ensure_kind_supported` instead of `validate_supported`. `mexc_testnet_is_no_testnet_for_any_kind` now supplies `FUTURES_API_KEY`/`FUTURES_API_SECRET` too, since the registry no longer short-circuits before building the futures leg's `AdapterConfig` (both legs are always built now; the short-circuit was a side effect of the removed pre-check, not something the design should optimize for).
- All `resolved_network(...)` assertions updated to `Some(...)`.

### Gate command and output

```
$ docker compose run --build --rm test cargo test --workspace --no-fail-fast
```
Two full runs, both fully green (no failures at all, including `market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database`, which didn't flake either time). Also re-ran that one test in isolation twice more as a sanity check (`docker compose run --rm test cargo test -p market_data --test write_path shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database -- --exact`): passed both times.

Per-crate check, before the full gate:
```
$ cargo test -p exchange_adapter_binance --no-fail-fast   # 117 + 55 passed, 0 failed
$ cargo test -p exchange_adapter_mexc --no-fail-fast      # 101 + 9 + 13 + 10 passed, 0 failed
$ cargo test -p live_trade_ops --no-fail-fast             # 11 + 1 (guard) passed, 0 failed
$ cargo tree -i live_trade_ops                            # itself only, no workspace crate depends on it
$ cargo clippy -p live_trade_ops -p exchange_adapter_binance -p exchange_adapter_mexc --all-targets
  # zero new warnings from adapter.rs / config.rs / lib.rs / registry.rs -- all remaining
  # warnings (too_many_arguments, wrong_self_convention, useless_conversion) are pre-existing,
  # confined to ws.rs / futures.rs / wiremock test files this fix never touched
```

### Files changed (this fix round, in addition to Task 4.1's original diff)

- `crates/exchange_adapter_binance/src/config.rs`
- `crates/exchange_adapter_binance/src/adapter.rs`
- `crates/exchange_adapter_binance/tests/wiremock_tests.rs`
- `crates/exchange_adapter_mexc/src/lib.rs`
- `crates/live_trade_ops/src/registry.rs`

### Concerns / notes for the reviewer

1. **Orchestrator's `KindAccount::resolve()` panic path** (`crates/orchestrator/src/main.rs:37-45`, `.expect("configured MARKET_KIND is not supported by this exchange adapter")`): this fix makes it possible, in principle, for `ExchangeAdapterBinance`/`ExchangeAdapterMexc` to construct successfully while a specific `MARKET_KIND` is unsupported (e.g. `MARKET_KIND=margin` + Binance + `EXCHANGE_NETWORK=testnet`) -- a combination that used to fail at construction, before `KindAccount::resolve()` could ever be reached. **In practice this is not reachable today**: `orchestrator`'s own `adapter_config_from_env` hardcodes `network: Network::Mainnet` unconditionally (it doesn't read `EXCHANGE_NETWORK` at all yet -- that's the orchestrator follow-up spec §2 defers). So there is no live path to this panic under current orchestrator code, and per the global constraint ("no behaviour change in orchestrator"), `main.rs` was left untouched. Flagging it because it becomes a live concern the moment the orchestrator follow-up wires up `EXCHANGE_NETWORK`.
2. `ExchangeAdapterMexc`'s `margin` field is `Option<SpotStyleAccount>` that always mirrors `spot`'s `Option` outcome exactly (both built together from one `resolve_kind(spot_cfg.network, MarketKind::Spot, ...)` call) rather than being resolved separately for `MarketKind::Margin` -- correct per MEXC's own table (margin always shares spot's host, `NOTES.md` §2), but worth the reviewer double-checking that no future MEXC change gives margin an independent host without updating this coupling.
3. `BinanceAdapterConfig::spot`/`futures` are `Option<(Hosts, ResolvedNetwork)>` even though Binance's table never actually returns `None` for either today (only margin can) -- kept uniform across all three kinds per the ruling's literal wording ("make the three accounts per-kind optional"), for symmetry and so a future table change (e.g. a network with no futures host) needs no shape change here, only a new `hosts()` row.
