# Task 4.2 report — Fee settlement (`settle`)

## What was implemented

`crates/live_trade_ops/src/settle.rs`: `PairAssets`, `Settlement`, and the pure
function `settle(kind: MarketKind, assets: &PairAssets, side: Side, fills: &[Fill]) -> Settlement`,
per the brief and spec §4.5's rules table + worked example. Re-exported from
`crates/live_trade_ops/src/lib.rs` (`pub use settle::{settle, PairAssets, Settlement};`).

Design: every row of §4.5's table (spot/margin BUY, spot/margin SELL, futures
either side) falls out of one merge — a raw per-asset delta seeded by
kind/side (base/quote for spot/margin, quote-only via `realized_pnl` for
futures), then every fill's fee subtracted from whichever asset actually paid
it (`add_delta`, a small ordered `Vec<(String, Decimal)>` merge, first-seen
order). This is why a spot/margin fee taken from base and a futures fee taken
from quote/BNB need no kind/side special-casing per fee.

- `fee_in_quote`: sums fees converted at `avg_price` when the fee asset is
  base or quote; `None` the instant one fee asset is neither (BNB case) —
  short-circuits rather than partially summing.
- `effective_fee_rate`: `fee_in_quote / gross_quote`, `None` if either side
  is unavailable (no fee-in-quote, or `gross_quote == 0`).
- `realized_pnl`: `Some(Σ fill.realized_pnl)` for `MarketKind::Futures`
  (missing per-fill value treated as `0`, not `unwrap`ped); always `None`
  for spot/margin, regardless of what any individual fill carries — matches
  the struct doc ("futures only").
- `net_price`: `None` for futures (no base balance ever moves, so nothing to
  divide by); for spot/margin, `|quote net delta| / |base net delta|` read
  back out of `net_deltas` after fees are applied.
- Zero fills: short-circuits before any division. `avg_price`, `net_price`,
  `effective_fee_rate` → `None`. `fee_in_quote` → `Some(Decimal::ZERO)` (no
  fee asset was ever charged, so nothing is "unconvertible" — zero, not
  unknown). `realized_pnl` still follows the kind rule (`Some(0)` futures,
  `None` spot/margin) via the same `realized_pnl_for` helper, not a special
  case.

No `f64` anywhere; `Decimal` end to end. No `unwrap()` on caller data (only
`.unwrap_or(Decimal::ZERO)` on our own already-computed values, and
`.expect()` in test-only literal parsing). `Fill`/`MarketKind`/`Side` are the
only `exchange_adapter` types imported — no adapter crate import, confirmed
by the existing `tests/no_adapter_imports.rs` guard (still passes).

## TDD evidence

**RED.** Wrote the full test module first (9 tests: the spec's worked
example with exact numbers, SELL fee-in-quote, futures BUY open, futures
SELL close, multi-fill average, mixed maker/taker, BNB fee, and two zero-fill
variants), then temporarily replaced `settle`'s body with a stub returning
all-zero/`None` regardless of input (kept compiling, per global-constraints'
"a RED test must still compile" rule) and ran:

```
docker compose run --build --rm test cargo test -p live_trade_ops --no-fail-fast
```

Result: `11 passed; 9 failed` — the 9 new `settle::tests::*` failed (e.g.
`left: [] right: [("LINK", 0.80), ("USDT", -12.0000), ("BNB", -0.0050)]`,
`left: None right: Some(0.5000)`), all pre-existing `registry::tests::*`
still green, and `no_adapter_imports` still passed (stub used no adapter
types either). This confirmed the tests fail for the intended reason (wrong
arithmetic, not a setup bug) before any real logic existed.

**GREEN.** Restored the real implementation (diffed byte-identical against
the pre-stub version to confirm no accidental drift) and re-ran the same
command: `20 passed; 0 failed` in `live_trade_ops` (11 registry + 9 settle).

**Full gate**, twice — once right after GREEN, once again after a
line-length cleanup and the MEXC doc fix:

```
docker compose run --build --rm test cargo test --workspace --no-fail-fast
```

Both runs: every crate green, including
`market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database`
(the documented pre-existing flake, TECH_DEBT §5) — it passed both times, no
re-run-in-isolation needed. No warnings from any file this task touched (the
only warnings in the log are pre-existing, unrelated: `local_analysis`'s
`PLACEHOLDER_STOP_LOSS_PCT` and `mq_gateway`'s `inbound_lagged_total`).

## Files changed

- `crates/live_trade_ops/src/settle.rs` — new; `settle`, `PairAssets`,
  `Settlement`, private helpers `realized_pnl_for`/`fee_in_quote_for`/
  `add_delta`/`find_delta`, and the 9 `#[cfg(test)]` unit tests.
- `crates/live_trade_ops/src/lib.rs` — `pub mod settle;` +
  `pub use settle::{settle, PairAssets, Settlement};`; updated the module
  doc comment's "added in later tasks" list now that `settle` exists.
- `crates/live_trade_ops/tests/no_adapter_imports.rs` — same doc-comment
  update (mirrors `lib.rs`'s list), no test-body change.
- `crates/live_trade_ops/Cargo.toml` — added `rust_decimal = "1.43.0"`
  (same version `exchange_adapter` pins), needed because `Fill`'s and
  `Settlement`'s `Decimal` fields must be the same concrete type without
  relying on a re-export from `exchange_adapter` (it doesn't re-export
  `rust_decimal::Decimal`).
- `crates/exchange_adapter_mexc/src/lib.rs` — carry-over doc fix from Task
  4.1's review: `ExchangeAdapterMexc`'s struct doc no longer claims
  `spot()`/`margin()`/`futures()` are unconditionally `Some`; now says
  `Some` on mainnet, `None` on testnet (MEXC has no public testnet, spec
  §4.3). Doc-only; re-ran `cargo test -p exchange_adapter_mexc` after this
  change (23 + 13 + 10 = all green) before the full-workspace re-run.

## Self-review findings

- Confirmed every brief-listed test is present, including the worked
  example's exact decimals (`net_deltas` LINK `+0.79920` / USDT `-12.0000`,
  `net_price` rounds to `15.0150` — the true value is the repeating decimal
  `12.0000/0.79920`, asserted via `round_dp(4)` since the spec itself states
  it to 4dp).
- Found and fixed a real bug during self-review before the first full-gate
  run: the empty-fills branch originally hardcoded `realized_pnl: None`,
  which is wrong for `MarketKind::Futures` (would have failed my own
  `zero_fills_on_futures_has_realized_pnl_zero_not_none` test — caught
  because I ran that test, not from reading alone). Fixed to call
  `realized_pnl_for(kind, fills)` uniformly (sums an empty slice to `0` for
  futures, stays `None` for spot/margin) so the empty-fills path uses the
  exact same kind-based rule as the non-empty path rather than a special
  case.
- Found 3 lines over the project's 100-char default rustfmt width in the
  test module (long `vec![fill(...)]` one-liners); manually wrapped them
  (did not run `cargo fmt`, per the task's constraint) and re-ran the full
  gate to confirm the wrap didn't change behaviour.
- Grepped for `f64`/`.unwrap()` in the new file: none (the only `f64`
  occurrence is the word inside a doc comment). `rust_decimal_macros`/`dec!`
  is not used anywhere else in this workspace, so test fixtures build
  `Decimal` via `Decimal::from_str` through a small `dec()` test helper,
  matching the codebase's existing `Decimal::new(...)`-based convention in
  spirit (parse-from-string was chosen over `Decimal::new(mantissa, scale)`
  purely for readability with 5-decimal-place fee amounts; both are
  equally exact).
- Verified `cargo tree -i live_trade_ops` is unaffected in spirit (no new
  workspace crate references `live_trade_ops`; only `live_trade_ops`'s own
  `Cargo.toml` gained the `rust_decimal` dependency edge).
- Noted, not fixed (out of scope): `docker compose run --build --rm test`
  builds an image-COPY-based `test` service (no bind mount, confirmed by
  reading `docker-compose.yml`), so the container's own `Cargo.lock` update
  for the new `rust_decimal` dependency edge never reaches the host
  `Cargo.lock` — host `Cargo.lock` is unchanged by `git diff`. Not a defect
  introduced by this task; the dependency resolves fine every time the
  gate runs (same `rust_decimal = "1.43.0"` version already used elsewhere
  in the workspace, so no version-resolution ambiguity is possible either
  way).

## Concerns

None blocking. One judgment call worth flagging for review: the top-level
task brief for this task specifies `avg_price: Option<Decimal>` while spec
§4.5's struct pseudocode shows `avg_price: Decimal` (non-`Option`) — I
followed the task's explicit instruction (`Option<Decimal>`, `None` on zero
fills) since it states the exact shape and the zero-fills-must-not-divide
requirement outright; this is consistent with the brief's own unit-test list
("zero fills → all zero, `avg_price None`"). Flagging in case a downstream
task (harness/report, §5.5) assumed the spec's literal `Decimal` type.
