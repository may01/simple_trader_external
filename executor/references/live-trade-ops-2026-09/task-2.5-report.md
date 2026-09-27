# Task 2.5 report: `FuturesOps` for Binance

Commit: `8e7e3da` — `feat(binance): futures leverage, margin type, brackets, position risk`

## What was implemented

New `crates/exchange_adapter_binance/src/futures_ops.rs`, `BinanceFuturesOps`, mirroring
`margin_ops.rs`'s pattern: holds its own cloned `BinanceRestClient` (futures host), reached
only through `ExchangeAdapterBinance::futures_ops()` (new override in `adapter.rs`), errors
surfacing through the existing shared `errors::classify` (no second classification path).

All six `FuturesOps` methods, spec §4.2 endpoints:

| Method | Endpoint |
|---|---|
| `set_leverage` | `POST /fapi/v1/leverage` |
| `set_margin_type` | `POST /fapi/v1/marginType` |
| `leverage_brackets` | `GET /fapi/v1/leverageBracket` |
| `position_risk` | `GET /fapi/v2/positionRisk` (+ `GET /fapi/v2/account`, see below) |
| `futures_margin_summary` | `GET /fapi/v2/account` (top-level fields) |
| `is_hedge_mode` | `GET /fapi/v1/positionSide/dual` |

### Decisions

- **`set_leverage`** parses the response's `leverage` field (a raw JSON integer per Binance's
  docs, e.g. `{"leverage": 21, "maxNotionalValue": "1000000", "symbol": "BTCUSDT"}`) and
  returns *that*, never the caller's argument — covered by a dedicated test
  (`futures_ops_set_leverage_returns_what_the_exchange_applied_not_the_request`) where the
  mock returns a different value (20) than requested (25) and the test asserts 20.
- **`set_margin_type`** sends `marginType=ISOLATED|CROSSED`; on `Err` it checks
  `e.reason() == Some(RejectReason::AlreadySet)` (Binance `-4046`, already mapped by
  `errors::classify`) and turns that into `Ok(())`. `-4028`/`-4048` are exercised end-to-end
  through the real HTTP → `classify_http_error` → `classify` path, asserting
  `LeverageNotAllowed`/`MarginModeChangeBlocked` come back on `.reason()`.
- **`position_risk` API version — v2, not v3.** I checked Binance's actual docs (via web
  fetch/search, not memory) for both versions before choosing. Both v2 and v3 payloads carry
  the four fields spec §4.2 names as the selection criterion (`leverage`, `marginType`,
  `isolatedMargin`, `liquidationPrice`); v3 additionally carries Multi-Assets/hedge-mode-only
  fields (`breakEvenPrice`, `isolated`, `adlQuantile`) that this codebase has no use for —
  hedge mode is explicitly out of scope (spec §3, one-way mode only). v2 is the simpler,
  longer-established shape and pairs naturally with `/fapi/v2/account` (already used below),
  so it's what I picked. Marked `// from docs — replace with capture` per the fixture-capture
  rule.
- **A real gap I found and had to design around:** neither `positionRisk` version (confirmed
  against Binance's docs) carries `initial_margin`/`maint_margin` — those two fields only
  exist in `/fapi/v2/account`'s `positions[]` array, which in turn lacks `marginType`,
  `isolatedMargin` and `liquidationPrice`. But the already-committed `FuturesPosition` struct
  (`ops.rs`, Task 2.1, not mine to change) requires all of these together. Per `ops.rs`'s own
  doc comment ("`liquidation_price` is reported by the exchange here... not computed by this
  crate"), I did not derive `initial_margin`/`maint_margin` from other returned fields (e.g.
  `notional / leverage`) — that would make the value trivially agree with itself and defeat
  the point of a field the exchange is supposed to report independently. Instead
  `position_risk` makes a **second call** to the account endpoint (same one
  `futures_margin_summary` uses) and merges the two symbol-matched rows. This is the one
  place I went beyond the brief's literal endpoint table, and I'm flagging it explicitly as a
  concern below.
- **`leverageBracket`'s numeric fields are raw JSON numbers**, not the quoted strings almost
  every other Binance endpoint uses (confirmed against the docs' example response) —
  `notionalCap`, `notionalFloor`, `maintMarginRatio`, `cum`. `decimal_from_number_or_string`
  in `parsing.rs` accepts either shape (so a captured response that turns out to quote them
  still parses) and goes straight from the JSON number's own text
  (`serde_json::Number::to_string`) to `Decimal` — for the integer fields (`notionalCap`,
  `notionalFloor`, `initialLeverage`) this never touches a float at all, since serde_json
  stores whole numbers as `u64`/`i64` internally. For the two ratio fields with decimal
  points (`maintMarginRatio`, `cum`), serde_json's default (non-`arbitrary_precision`) `Value`
  does parse them through `f64` internally before we ever see them — an inherent limitation
  of the `serde_json` crate's untyped `Value`, not something this file's code does itself (no
  `as_f64`/float arithmetic anywhere in it). I considered enabling `arbitrary_precision` on
  `serde_json` to close this gap fully, but that's a workspace-wide dependency-feature change
  (Cargo unifies features for a shared dependency across the whole build) for two
  risk-ratio fields, not order-execution money amounts — out of proportion to this task, so I
  left it and noted the limitation in the code comment. Layer 7's capture will confirm the
  real wire shape either way.
- **`req_u64`/`req_bool`** in `parsing.rs` were module-private; widened to `pub(crate)` since
  `futures_ops.rs` needs them (matches the existing `req_str`/`parse_decimal` pattern already
  `pub(crate)`).

## TDD evidence

**RED** (before any of this task's code): `docker compose run --build --rm test cargo test -p
exchange_adapter_binance --no-fail-fast`

```
test futures_ops_set_leverage_returns_the_applied_leverage ... FAILED
---- futures_ops_set_leverage_returns_the_applied_leverage stdout ----
thread 'futures_ops_set_leverage_returns_the_applied_leverage' panicked at
crates/exchange_adapter_binance/tests/wiremock_tests.rs:1791:45:
futures_ops should be Some on a Binance adapter
test result: FAILED. 42 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out
```
Expected: `ExchangeAdapterBinance` still returns `None` from the default `futures_ops()`
accessor (no override yet) — exactly the documented RED reason.

**GREEN** (after implementation): `docker compose run --build --rm test cargo test -p
exchange_adapter_binance --test wiremock_tests --no-fail-fast`

```
test result: ok. 55 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.96s
```
(43 pre-existing + the strengthened RED test + 11 new: set_leverage×3, set_margin_type×4,
leverage_brackets×1, position_risk×2, futures_margin_summary×1, is_hedge_mode×2.)

Also: `docker compose run --build --rm test cargo test -p exchange_adapter_binance --lib`
→ `117 passed; 0 failed` (12 new parsing-layer unit tests for `parse_leverage_brackets`,
`parse_position_risk_row`, `parse_account_position_margins`, `parse_futures_margin_summary`,
including the "flat via zero amt" / "flat via no row at all" / "symbol not found is an error"
edge cases).

## Gate: `docker compose run --build --rm test cargo test --workspace --no-fail-fast`

Full run: every target green except the one known pre-existing flake:

```
test shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database ... FAILED
test result: FAILED. 22 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out
```

Re-ran in isolation (`cargo test -p market_data shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database -- --test-threads=1`):

```
test shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 22 filtered out
```

Confirms the known flake (TECH_DEBT §5), unrelated to this task's changes — every other
target across the workspace passed on the full run. No RED placeholders remain in
`exchange_adapter_binance`; updated the stale Task-1.4 comment block in `wiremock_tests.rs`
that said margin_ops/futures_ops were still RED.

No new compiler warnings introduced (checked the full gate log's `warning:` lines — the only
two are pre-existing, in `local_analysis` and `mq_gateway`, untouched by this task).

## Files changed

- `crates/exchange_adapter_binance/src/futures_ops.rs` (new) — `BinanceFuturesOps`.
- `crates/exchange_adapter_binance/src/adapter.rs` — constructs `BinanceFuturesOps` from a
  cloned futures `BinanceRestClient`, overrides `ExchangeAdapter::futures_ops()`.
- `crates/exchange_adapter_binance/src/lib.rs` — `mod futures_ops;`.
- `crates/exchange_adapter_binance/src/parsing.rs` — `req_u64`/`req_bool` widened to
  `pub(crate)`; new `decimal_from_number_or_string`, `parse_leverage_brackets`,
  `PositionRiskRow`/`parse_position_risk_row`, `parse_account_position_margins`,
  `parse_futures_margin_summary`, plus their unit tests.
- `crates/exchange_adapter_binance/tests/wiremock_tests.rs` — strengthened the RED
  `set_leverage` test with query-param assertions; added 10 more wiremock tests covering
  every method, both `set_margin_type` variants, `-4028`/`-4046`/`-4048`, flat vs. open
  `position_risk` (including the two-call merge), and both `is_hedge_mode` values; updated
  the stale Task-1.4 "still RED" comment block.

## Self-review findings

- All six trait methods implemented and tested.
- `-4046` → `Ok(())` tested (`futures_ops_set_margin_type_already_set_maps_to_ok`).
- `-4028`/`-4048` tested surfacing `LeverageNotAllowed`/`MarginModeChangeBlocked` through the
  real HTTP→classify path, not just unit-level.
- `position_risk` flat (two ways: zero `positionAmt`, and no row at all for the symbol) and
  open (all fields, merged from two endpoints) both tested.
- `is_hedge_mode` both `true`/`false` tested.
- Every `FuturesPosition`/`LeverageBracket`/`FuturesMarginSummary` field is parsed from
  exchange data — none defaulted or derived.
- `// from docs — replace with capture` present on every response-field mapping introduced
  (`decimal_from_number_or_string`, `parse_leverage_brackets`, `parse_position_risk_row`,
  `parse_account_position_margins`, `parse_futures_margin_summary`, and `set_leverage`'s
  applied-leverage read); request-building code does not carry the marker, per the brief.
- No RED placeholders remain anywhere in this crate.
- Decimals stay `Decimal` end to end in this crate's own code; leverage is `u32` throughout
  (including the `u32::try_from` range checks on both `set_leverage`'s response and
  `leverageBracket`'s `initialLeverage`). The one caveat is `serde_json::Value`'s own internal
  parsing of non-integer JSON numbers through `f64` before this code ever touches them — noted
  above and in the code comment, not hidden.

## Concerns for the reviewer

1. **`position_risk` issues two HTTP calls, not the single endpoint the brief's table
   literally names.** This was a genuine, verified gap (checked against Binance's real docs,
   not assumed): no `positionRisk` version reports `initial_margin`/`maint_margin`. I merged
   in a second call to `/fapi/v2/account` rather than derive those fields or leave them at a
   silent default. I believe this is the correct engineering call given
   `FuturesPosition`'s committed field set and the "never derive what the exchange should
   report" precedent already in `ops.rs`'s own doc comment, but it's a design decision beyond
   what the brief spelled out, and worth a second look.
2. **`maintMarginRatio`/`cum` in `leverageBracket` pass through `serde_json`'s internal `f64`**
   (a crate limitation, not this code's own arithmetic) before landing in `Decimal`. Flagged
   with a code comment and covered by the `arbitrary_precision`-tradeoff note above; Layer 7's
   capture will settle whether the real wire values need more precision than `f64` round-trips
   safely.
3. The RED test (`futures_ops_set_leverage_returns_the_applied_leverage`) worked fine as
   originally written against a correct implementation — no adjustment to its premise was
   needed. I only strengthened its query-parameter assertions (method/path only before) to
   match this crate's established pattern (e.g. `margin_ops_borrow_sends_borrow_repay_post_with_type_borrow`),
   per the task's "keep its assertions strong" instruction.

## Fix round 1/5 (review feedback)

Two findings from the spec-PASS review, both addressed:

1. **Important — missing `// from docs — replace with capture` marker.**
   `futures_ops.rs`'s `is_hedge_mode` read `req_bool(&value, "dualSidePosition")` without the
   marker every other new doc-derived response read in this diff carries. Added it directly
   above the `req_bool` call, same form and position as the others (e.g. `set_leverage`'s
   `req_u64(&value, "leverage")`).
2. **Minor — three error-path wiremock tests only matched on `method`/`path`.**
   `futures_ops_set_leverage_over_bracket_max_surfaces_leverage_not_allowed`,
   `futures_ops_set_margin_type_already_set_maps_to_ok`, and
   `futures_ops_set_margin_type_blocked_by_open_position_surfaces_margin_mode_change_blocked`
   would have matched a request missing its required parameters. Added the same
   `query_param` assertions their happy-path siblings already use: `symbol`+`leverage` for
   the first, `symbol`+`marginType` (`ISOLATED`/`CROSSED` respectively, matching what each
   test actually requests) for the other two.

Not findings, confirmed accepted by the reviewer with no action needed: the two-call
`position_risk` merge (fails safely — typed error on a missing `positions[]` array or an
absent symbol row, unit-tested; only a narrow staleness window between the two calls if a
position closes in between, inherent to the design and exercised for real by Layer 7) and the
`serde_json` number-parsing-through-`f64` limitation noted above. The `positionRisk` v2
choice was also confirmed to fail safely — every field goes through `req_str(...)?`, so a
wrong version would error rather than silently default.

### Re-run after the fix

`docker compose run --build --rm test cargo test -p exchange_adapter_binance --no-fail-fast`

```
     Running unittests src/lib.rs (exchange_adapter_binance)
test result: ok. 117 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.29s

     Running tests/testnet_integration.rs
test result: ok. 0 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out; finished in 0.00s

     Running tests/wiremock_tests.rs
test result: ok. 55 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.95s
```

All three amended tests (`futures_ops_set_leverage_over_bracket_max_surfaces_leverage_not_allowed`,
`futures_ops_set_margin_type_already_set_maps_to_ok`,
`futures_ops_set_margin_type_blocked_by_open_position_surfaces_margin_mode_change_blocked`)
pass with the new `query_param` assertions in place, confirming the request-building was
already correct — only the tests' matchers were loosened before.

Commit: `a82758f` — "fix(binance): review round 1/5 for Task 2.5 futures ops", on `live-trade-ops`
(local only).
