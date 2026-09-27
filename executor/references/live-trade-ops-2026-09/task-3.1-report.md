# Task 3.1 report — MEXC plumbing (Layer 3)

Branch: `live-trade-ops` (worktree `trade_executor/.worktrees/layer-implementation`)
Commit: `abcc94e` — `feat(mexc): network hosts, rejection classification, client order id, assets`

## What was implemented

1. **`hosts(network, kind)` / `resolved_network`** (`crates/exchange_adapter_mexc/src/config.rs`)
   - `hosts(Network::Testnet, _)` → `ConfigError::NoTestnet { exchange: Exchange::Mexc, kind }` for every `MarketKind` (spot, margin, futures) — MEXC has no public testnet.
   - `hosts(Network::Mainnet, kind)` → today's hosts: spot/margin → `https://api.mexc.com` / `wss://wbs-api.mexc.com/ws` (the protobuf-capable ws host, per this crate's own `NOTES.md` §1, not the older `wss://wbs.mexc.com`); futures → `https://contract.mexc.com` / `wss://contract.mexc.com/ws` (the ws value is unused today — `FuturesAccount` is REST-poll-only — filled in only for `Hosts`' shape).
   - `resolve_hosts(network, kind, rest_override, ws_override)` mirrors `exchange_adapter_binance::config::resolve_hosts`'s precedence exactly (full override > partial override > table), copied verbatim since the precedence rule is exchange-agnostic.
   - `ExchangeAdapterMexc::new` (`lib.rs`) now calls `resolve_hosts` for spot/margin/futures instead of requiring an explicit `AdapterConfig.rest_base_url`/`ws_base_url` override (that requirement was only ever a placeholder until this table existed). Added `resolved_network: ResolvedNetwork` / `futures_resolved_network: ResolvedNetwork` fields and a `pub fn resolved_network(&self, kind: MarketKind) -> ResolvedNetwork` accessor, mirroring `ExchangeAdapterBinance`'s. `config_err_to_adapter_err` mirrors Binance's helper, surfacing `ConfigError` (notably `NoTestnet`) as `AdapterError::InvalidRequest` carrying `ConfigError`'s `Display` text.

2. **`errors::classify`** (new `crates/exchange_adapter_mexc/src/errors.rs`)
   - `classify(http_status, code, message) -> RejectReason`: `401`/`403` → `AuthFailed`; message containing "insufficient balance" (case-insensitive, `// from docs — replace with capture`) → `InsufficientBalance`; everything else → `Unknown`. `code` is accepted for interface parity with Binance's `classify` but not yet keyed on (no MEXC code number for "insufficient balance" is evidenced — the wiremock fixture's `1001`/`30004` are hand-built placeholders, not evidence). One test per row plus an unmapped-code/message case. No other rows invented, per the brief and spec §4.6's MEXC paragraph.

3. **`http::map_error_status`** now routes every 4xx (including 401/403, folded into the same branch) through `errors::classify`, returning `AdapterError::Rejected(Rejection{ reason, exchange: Mexc, code, http_status, message })` — never `AdapterError::InvalidRequest` for an exchange refusal (carry-over fix from Task 1.2's review, previously line 301). `RateLimited` (429/418) and `Network` (5xx) branches unchanged. Extracted `(code, message)` cleanly instead of the old formatted `"[code] msg"` string, since `message` must now be the exchange's verbatim text on `Rejection`.

4. **`dto_futures::unwrap_envelope`** now calls `errors::classify(0, code, &msg)` (`0` standing for "no HTTP-level signal" — MEXC's contract API sends `success:false` business rejections on an HTTP 200) instead of hardcoding `RejectReason::Unknown`, and the envelope's `code` is preserved on `Rejection.code` (previously dropped once a `message` was present, per Task 1.2's carry-over review note).

5. **`client_order_id` parsing**:
   - Spot: `SpotOrderResponse` gained `client_order_id: Option<String>` (`#[serde(rename = "clientOrderId")]`, `#[serde(default)]`); `into_order_info` now sets it instead of hardcoding `None`.
   - Futures: `ContractOrder` gained `external_oid: Option<String>` (`#[serde(rename = "externalOid")]`, `#[serde(default)]`); `futures.rs::get_order` sets `OrderInfo.client_order_id` from it.

6. **`MarketInfo.base_asset`/`quote_asset`**:
   - Spot: `SymbolInfo` gained required (no `#[serde(default)]`) `base_asset`/`quote_asset` fields (`baseAsset`/`quoteAsset`) — a missing field is now a typed parse error (`AdapterError::Network`), never a silent empty string, per the "typed errors, never silent defaults on exchange-supplied data" decision.
   - Futures: `ContractDetail` gained required `base_coin`/`quote_coin` fields (`baseCoin`/`quoteCoin`), same rationale.
   - `spot.rs`/`futures.rs::get_market_info` populate `MarketInfo.base_asset`/`quote_asset` from these instead of `String::new()`.

## Out of scope (confirmed untouched)

`get_order_fills`, `MarginOps`, `FuturesOps` are not implemented for MEXC — grepped the crate to confirm no `margin_ops`/`futures_ops`/`get_order_fills` symbol exists anywhere in `crates/exchange_adapter_mexc/src/`; they stay on the trait's defaults (`NotSupported`/`None`). `OrderId` is untouched (still `u64` in `exchange_adapter`).

## TDD evidence

Given the size of the task, I worked file-by-file (write the test alongside the minimal implementation it needs, run, watch RED where the assertion was wrong, fix, watch GREEN), rather than one giant RED pass across the whole crate — a bare RED commit across all six files would have failed to compile at several intermediate points (e.g. `SpotOrderResponse` struct-literal call sites needing the new field everywhere at once). Representative RED→GREEN cycles actually observed:

- **`errors::classify`**: first wrote `errors.rs` with the table and its tests; `cargo test -p exchange_adapter_mexc --lib errors` initially failed to compile (module not registered) until `mod errors;` was added to `lib.rs` — that's the RED I watched (compile error, not a wrong assertion, since the function and its tests were written together per the module's self-contained nature). After registering the module: `6 passed; 0 failed`.
- **`http::map_error_status`**: added tests asserting `Rejected`/`reason()` before rewriting the function; running `cargo test -p exchange_adapter_mexc --lib http::` against the *old* function (still mapping generic 4xx to `InvalidRequest`, 401/403 to `Rejected(Unknown)`) — I made the edit and test addition together and confirmed the old behavior would have failed `a_4xx_exchange_body_becomes_rejected_not_invalid_request_with_code_kept` and `insufficient_balance_4xx_maps_to_insufficient_balance_reason` by inspection (old code: `else if status.is_client_error() { AdapterError::InvalidRequest(msg) }` — not `Rejected`, no `reason()`). After the rewrite: `8 passed; 0 failed`.
- **`SymbolInfo`/`ContractDetail` required fields**: making `base_asset`/`quote_asset`/`base_coin`/`quote_coin` required (no `#[serde(default)]`) immediately broke `spot_get_market_info_parses_exchange_info` and `futures_get_market_info_parses_contract_detail` — genuine RED: `cargo test` failed those two with a `serde` "missing field" deserialize error surfaced as `AdapterError::Network`. Fixed by adding `"baseAsset"/"quoteAsset"`/`"baseCoin"/"quoteCoin"` to the mocked JSON fixtures and asserting the new fields. GREEN after.
- **Migrated "insufficient balance" tests**: `unwrap_envelope_rejects_on_success_false_even_with_http_200` (dto_futures.rs) and `futures_place_order_surfaces_success_false_as_rejected_even_with_http_200` (futures_wiremock_tests.rs) — before wiring `classify` into `unwrap_envelope`, `err.reason()` would have been `Some(RejectReason::Unknown)` (the old hardcoded value), so `assert_eq!(err.reason(), Some(RejectReason::InsufficientBalance))` is a real RED against the pre-change code; GREEN after `unwrap_envelope` was rewired.

**GREEN — full crate, local cargo (fast iteration):**
```
cargo test -p exchange_adapter_mexc
```
→ lib: `100 passed; 0 failed`; `futures_wiremock_tests`: `9 passed`; `live_credentials`: `1 ignored` (pre-existing, unrelated); `spot_wiremock_tests`: `13 passed`; `wiremock_tests`: `10 passed`; doc-tests: `0`.

**GREEN — mandated gate, Docker:**
```
docker compose run --build --rm test cargo test --workspace --no-fail-fast
```
First attempt hit `No space left on device` inside Postgres (host disk was at 98% full, `layer-implementation_trader_pgdata` volume alone had grown to 5.1 GB from repeated migration/test churn across prior sessions). `docker builder prune -f` only freed 3 MB (the bloat was the Postgres data volume, not the builder cache), so I additionally ran `docker compose down -v` for this worktree's own compose project (`layer-implementation`, scoped by project name — did not touch any other worktree's volumes) to drop and recreate that disposable test-only volume, freeing ~4.7 GB. Re-ran the gate: **fully green**, exit 0, no `FAILED`/`error` anywhere in the log, 45 `test result: ok` blocks across every crate. A second full run (after a trivial no-op cleanup — removed a redundant `.clone()` in `futures.rs`) hit the one **known pre-existing flake**, `market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database` (TECH_DEBT §5); re-ran it in isolation and it passed:
```
docker compose run --build --rm test cargo test -p market_data --test write_path shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database -- --nocapture
→ test result: ok. 1 passed; 0 failed
```

## Files changed

- `crates/exchange_adapter_mexc/src/config.rs` — `hosts`, `resolve_hosts`, tests.
- `crates/exchange_adapter_mexc/src/errors.rs` — new; `classify`, tests.
- `crates/exchange_adapter_mexc/src/lib.rs` — host resolution wired into `ExchangeAdapterMexc::new`, `resolved_network(kind)`, `config_err_to_adapter_err`, construction-level tests.
- `crates/exchange_adapter_mexc/src/http.rs` — `map_error_status` rewrite, tests.
- `crates/exchange_adapter_mexc/src/dto_futures.rs` — `unwrap_envelope` routed through `classify`; `ContractOrder.external_oid`; `ContractDetail.base_coin`/`quote_coin`; test migrated to `reason()`, new preserved-code test.
- `crates/exchange_adapter_mexc/src/dto.rs` — `SpotOrderResponse.client_order_id`; `SymbolInfo.base_asset`/`quote_asset`.
- `crates/exchange_adapter_mexc/src/spot.rs` — `get_market_info` populates `base_asset`/`quote_asset`.
- `crates/exchange_adapter_mexc/src/futures.rs` — `get_order` sets `client_order_id`; `get_market_info` populates `base_asset`/`quote_asset`.
- `crates/exchange_adapter_mexc/tests/futures_wiremock_tests.rs` — migrated insufficient-balance assertion; new `baseCoin`/`quoteCoin` fixture + assertions; new `client_order_id` present/absent tests.
- `crates/exchange_adapter_mexc/tests/spot_wiremock_tests.rs` — new `baseAsset`/`quoteAsset` fixture + assertions; new `client_order_id` present/absent tests.

## Self-review findings

- Both `NoTestnet` paths covered for every `MarketKind` (spot, margin, futures) — see `config::tests::{spot,margin,futures}_testnet_is_a_no_testnet_config_error` and `lib.rs::construction_tests::exchange_network_testnet_fails_construction_{with_no_testnet,for_futures_too}`.
- Mainnet hosts unchanged from today's literal values (`https://api.mexc.com`, `https://contract.mexc.com`) — same strings the crate hardcoded before this task, now behind the table instead of a required override.
- No path turns an exchange refusal into `InvalidRequest` — `map_error_status`'s `is_client_error()` branch and `unwrap_envelope`'s `!envelope.success` branch are the crate's only two `Rejected`-construction sites (grepped: no third `AdapterError::Rejected(` in `src/`), both go through `classify`.
- Envelope `code` preserved on both surfaces: `http.rs` (`code.map(|c| c.to_string())`) and `dto_futures.rs` (`code.map(|c| c.to_string())`, tested explicitly in `unwrap_envelope_preserves_code_on_rejection_even_when_unmapped`).
- Client order ids and base/quote assets parsed on both surfaces (spot `clientOrderId`/`baseAsset`/`quoteAsset`, futures `externalOid`/`baseCoin`/`quoteCoin`), each with a present-and-absent test.
- `get_order_fills`/`margin_ops`/`futures_ops` confirmed absent from the MEXC crate (grep, see above) — still on trait defaults.
- Markers present: `errors.rs`'s one message-keyed row and `http_401_maps_to_auth_failed`/`http_403_maps_to_auth_failed` are explicitly documented as evidenced-vs-not; the one `// from docs — replace with capture` marker sits on the insufficient-balance message check (the only doc-derived response-field row in this task's table).
- Message-string assertions migrated to `reason()`: both `dto_futures.rs`'s and `futures_wiremock_tests.rs`'s "insufficient balance" tests now assert `err.reason() == Some(RejectReason::InsufficientBalance)`.
- Pristine test output: no warnings on `cargo build -p exchange_adapter_mexc` after this task's changes (checked; the only warnings seen mid-task, an unused `RejectReason` import and dead-code on then-unused `hosts`/`resolve_hosts`, were resolved by moving the import into the test module and wiring the functions into `lib.rs`).
- `cargo fmt` was not run on the crate; only the lines I wrote were hand-formatted to match the surrounding style.

## Where MEXC's shape differs from Binance's (as asked)

- Binance keeps a separate `crates/exchange_adapter_binance/src/adapter.rs` distinct from `config.rs`; MEXC has no such split — `ExchangeAdapterMexc` construction has always lived directly in `lib.rs`, so `resolved_network(kind)` and `config_err_to_adapter_err` were added there instead of a new file, to avoid restructuring code outside this task's scope.
- MEXC's `MexcConfig` has no separate `margin: AdapterConfig` field (margin reuses spot's `AdapterConfig`/host, per `NOTES.md` §2, itself pre-existing and unchanged by this task) — mirrored Binance's "resolve margin purely to catch `NoTestnet`, discard its hosts" pattern rather than inventing a margin-specific `AdapterConfig`.
- MEXC's classify table is deliberately much thinner than Binance's (one message-keyed row vs. Binance's ~18 code-keyed rows) — per spec §4.6's explicit "MEXC" paragraph, filling the real table is a later spec's job; inventing rows from memory was explicitly ruled out both by the brief and by the "Before You Begin" guidance.

## Concerns

- None blocking. The futures ws host literal (`wss://contract.mexc.com/ws`) is a best-effort placeholder — nothing in the crate dials it today (`FuturesAccount` is REST-poll-only, unchanged by this task), so it has no observable effect; flagged in a code comment at its definition so a future ws implementation doesn't mistake it for confirmed.
- The disk-space incident during the Docker gate was a pre-existing environment issue (this worktree's own Postgres test volume bloated to 5.1 GB across many prior sessions' churn), not something this task's changes caused; resolved by recreating that one disposable volume (`docker compose down -v` scoped to this compose project only).
- One observation, no code change here: `tests/live_credentials.rs` still carries the outdated `wss://wbs.mexc.com` literal that `NOTES.md:68` itself calls out as stale (the correct value, used by this task's `config::hosts` table, is `wss://wbs-api.mexc.com/ws`). That test is `#[ignore]`d and only exercises a REST call, so the stale literal is never dialed — flagged for whoever next touches that file, not fixed here since it's outside this task's file list.

## Fix round 1 (review finding, Important)

**Finding.** Four new doc-derived response-field mappings were missing the `// from docs — replace with capture` marker (applied only to `errors.rs`'s message-keyed row, not to the newly-added struct fields): `dto.rs`'s `clientOrderId`, `baseAsset`/`quoteAsset`; `dto_futures.rs`'s `externalOid`, `baseCoin`/`quoteCoin`. All six are modelled on MEXC's published docs and never diffed against a live response, exactly like every other doc-derived mapping this crate already marks — Layer 7's capture work finds what to reconfirm by grepping that exact string, so an unmarked assumption is invisible to it.

**Fix.** Added `// from docs — replace with capture` immediately above each of the six `#[serde(rename = ...)]` field mappings:
- `crates/exchange_adapter_mexc/src/dto.rs`: `client_order_id` (`clientOrderId`), `base_asset` (`baseAsset`), `quote_asset` (`quoteAsset`).
- `crates/exchange_adapter_mexc/src/dto_futures.rs`: `external_oid` (`externalOid`), `base_coin` (`baseCoin`), `quote_coin` (`quoteCoin`).

Comment-only change, no behaviour touched.

**Re-checked for any other missed marker.** Diffed this task's whole commit (`git show abcc94e -- <the six touched src files>`) for every newly-added `#[serde(rename = ...)]` and every newly-added `pub(crate)` struct field: the only six new fields in the whole task are exactly the ones the reviewer flagged, and all are covered now. No other new response-field mapping was found unmarked.

**Test re-run** (Docker `test` service, as requested):
```
docker compose run --build --rm test cargo test -p exchange_adapter_mexc
```
→ lib: `100 passed; 0 failed`; `futures_wiremock_tests`: `9 passed`; `live_credentials`: `0 passed; 1 ignored` (pre-existing, unrelated); `spot_wiremock_tests`: `13 passed`; `wiremock_tests`: `10 passed`; doc-tests: `0 passed`. All green, no behaviour change expected or observed (comment-only diff).

**Commit:** `4be10a9` — `fix(mexc): mark the 4 new doc-derived response fields as unconfirmed`, on `live-trade-ops` (local only).
