# Task 4.3 report: Liquidation calculator (`risk`)

## What was implemented

`crates/live_trade_ops/src/risk.rs`, re-exported from `lib.rs` (`bracket_for`,
`initial_margin`, `isolated_liquidation_price`). The golden-file test lives
**in the same file**, inside the module's own `#[cfg(test)] mod tests` block,
alongside the other unit tests — following `settle.rs`'s shape exactly, per
the task's own instruction to do so. There was no reason to split it into
`tests/`: the golden test needs no fixtures beyond the JSON file itself and
no setup `settle.rs`'s in-file convention couldn't already give it.

Three functions, per the brief's exact signatures:

- `initial_margin(qty, entry, leverage) -> Decimal` — `qty * entry /
  Decimal::from(leverage)`, guarded: `leverage == 0` returns `Decimal::ZERO`
  instead of panicking.
- `isolated_liquidation_price(side, qty, entry, isolated_margin, bracket) ->
  Decimal` — spec §6.3's Binance long/short formula. `side` selects
  `Side::Buy` (long) vs `Side::Sell` (short), the same sign convention
  `exchange_adapter_binance`'s own position-risk parsing already uses for a
  raw `positionAmt` (positive → long, negative → short). Both denominators
  guarded against zero.
- `bracket_for(brackets, notional) -> Option<&LeverageBracket>` — the
  bracket whose `[notional_floor, notional_cap)` range contains `notional`
  (floor inclusive, cap exclusive, so a value sitting exactly on a shared
  boundary between two contiguous tiers belongs to the tier it is the floor
  of). `None` once `notional` reaches or passes the last bracket's cap.
- `risk_matches_live_golden_rows` — reads
  `crates/live_trade_ops/tests/fixtures/futures_liq_golden.json` if it
  exists, deserializes it into `Vec<GoldenRow>`, and asserts every row's
  computed liquidation price is within 0.5% of `exchange_liq_price`. Not
  `#[ignore]`d. Today the file does not exist, so the test prints a
  "no golden rows yet" line and passes vacuously.

## A decision the brief didn't spell out: no `side` column in the golden row

Spec §6.3's golden row shape is `(exchange, net, run_date, qty, entry,
leverage, isolated_margin, mmr, cum, exchange_liq_price)` — no `side` field.
`isolated_liquidation_price` needs a side, so something in the row has to
carry it. I used `qty`'s sign (positive = long, negative = short), because
that is the *only* place it can come from given the fixed shape, and it
matches the sign convention already used elsewhere in this workspace for a
raw exchange `positionAmt` (`exchange_adapter_binance::parsing::
parse_one_futures_position` / `parse_position_risk_row`, both `amt.abs()`
for the magnitude with side derived from `amt.is_sign_positive()`). This
wasn't explicitly stated in the brief or spec §6.3's row-shape line, so
flagging it explicitly for review: if Layer 7 ends up writing golden rows
with an unsigned `qty` and expects some other encoding of side, this
struct's `GoldenRow::qty` field and the `is_sign_negative()` dispatch in
`risk_matches_live_golden_rows` is the one place to change.

## The MEXC seam

Per the task's decision ("leave the seam ... do not invent MEXC's"), I did
not add a `LiqCalc` enum (the brief's interface only lists the three
functions above, no such type) — instead, `risk_matches_live_golden_rows`
dispatches on `row.exchange.as_str()` with only a `"binance"` arm calling
`isolated_liquidation_price`; any other value panics with a message naming
the missing exchange and pointing at spec §6.3, so a stray MEXC golden row
fails loudly and legibly rather than being silently skipped or silently
compared against the wrong formula.

## TDD evidence

**RED** — I temporarily replaced all three function bodies with
`unimplemented!("RED: ...")` (keeping the real signatures and all tests
intact), then ran:

```
docker compose run --build --rm test cargo test -p live_trade_ops risk:: --no-fail-fast
```

First attempt failed to *compile* — `exchange_adapter::ops::LeverageBracket`
doesn't exist as a public path (the `ops` module is private; `LeverageBracket`
is re-exported at the crate root). Fixed the import to
`use exchange_adapter::{LeverageBracket, Side};`, re-ran, and got a clean RED:

```
test risk::tests::bracket_for_at_the_last_caps_boundary_is_none ... FAILED
  panicked at crates/live_trade_ops/src/risk.rs:88:5: not implemented: RED: bracket_for not yet implemented
test risk::tests::initial_margin_is_qty_times_entry_over_leverage ... FAILED
  panicked at ...:38:5: not implemented: RED: initial_margin not yet implemented
... (12 failed total)
test risk::tests::risk_matches_live_golden_rows ... ok   <- vacuous pass, no fixture yet, doesn't touch the stubbed functions
test result: FAILED. 1 passed; 12 failed; 0 ignored; 0 measured; 20 filtered out
```

All 12 non-golden tests failed for the expected reason (calling an
unimplemented stub); the golden test passed vacuously as designed since it
never reaches the stubbed functions when the fixture is absent.

**GREEN** — restored the real implementation, re-ran:

```
docker compose run --build --rm test cargo test -p live_trade_ops --no-fail-fast
```

```
test result: ok. 33 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.17s
     Running tests/no_adapter_imports.rs ...
test no_file_other_than_registry_rs_imports_an_adapter_crate ... FAILED
  panicked: /app/crates/live_trade_ops/src/risk.rs: mentions `exchange_adapter_binance`
```

The guard test (`no_adapter_imports.rs`) is a **textual** grep, and my doc
comment on `isolated_liquidation_price` named
`exchange_adapter_binance::parsing::parse_position_risk_row` by its full
crate path. Reworded the doc comment to describe the convention without
naming the crate ("the same convention the Binance adapter's own
position-risk row parsing already uses ..."), re-ran:

```
test result: ok. 33 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
test no_file_other_than_registry_rs_imports_an_adapter_crate ... ok
```

Full workspace gate, twice (once before this report, once after a small
message-wording fix found in self-review):

```
docker compose run --build --rm test cargo test --workspace --no-fail-fast
```

Every crate's `test result: ok`, 0 failed, across the whole log both times.
`market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database`
(the known TECH_DEBT §5 flake) ran and passed both times — no re-isolation
needed.

## Golden-file enforcement, proven live (per the self-review instruction)

With no fixture present, `risk_matches_live_golden_rows` passes and prints:

```
risk_matches_live_golden_rows: no golden rows yet -- /app/crates/live_trade_ops/tests/fixtures/futures_liq_golden.json does not exist (written by Layer 7's live runs)
```

I then wrote a temporary one-row fixture at
`crates/live_trade_ops/tests/fixtures/futures_liq_golden.json` matching the
spec's worked example (`binance`, `qty "1"`, `entry "1"`, `leverage 10`,
`isolated_margin "0.1"`, `mmr "0.01"`, `cum "0"`, `exchange_liq_price
"0.90909"`) — it passed. I then mutated `exchange_liq_price` to `"0.95000"`
(well outside 0.5%) and re-ran; it failed loudly:

```
thread 'risk::tests::risk_matches_live_golden_rows' panicked at crates/live_trade_ops/src/risk.rs:376:13:
row GoldenRow { ... exchange_liq_price: 0.95000 }: computed liquidation price 0.9090909090909090909090909091 vs exchange-reported 0.95000 differs by 0.0409090909090909090909090909, exceeding the 0.5% tolerance (0.00475000)
```

I also verified the signed-`qty` short-side dispatch works with a
`qty: "-3"` row matching the short-side unit test's numbers — passed. I then
deleted the fixture and its now-empty `tests/fixtures/` directory and
confirmed the vacuous-pass message returns unchanged, and confirmed `git
status` shows no trace of the temporary fixture (only the three real files
changed).

## Files changed

- `crates/live_trade_ops/src/risk.rs` (new) — the three functions, doc
  comments, and the full test module (initial_margin ×2, isolated
  liquidation ×5 covering long/short/cum≠0/guards, bracket_for ×5 covering
  floor/shared-boundary/mid-range/last-cap/past-last-cap, and the golden
  test).
- `crates/live_trade_ops/src/lib.rs` — added `pub mod risk;` and the
  `pub use risk::{...}` re-export.
- `crates/live_trade_ops/Cargo.toml` — `rust_decimal` gained the
  `serde-with-str` feature (declared explicitly rather than relied on as
  incidental fallout from `exchange_adapter_binance`/`exchange_adapter_mexc`
  already requesting it); added `serde` (derive) and `serde_json` as
  `[dev-dependencies]`, used only by the golden-file test.

No changes to any other crate, no `cargo fmt` run (only the lines I wrote
are formatted by hand to match `settle.rs`'s style).

## Self-review findings (and fixes made before this report)

1. Doc comment on `isolated_liquidation_price` named
   `exchange_adapter_binance::parsing::parse_position_risk_row` by full
   path, which tripped the crate's own `no_adapter_imports.rs` textual
   guard (by design — it greps doc comments too). Reworded to describe the
   convention without the crate name. Fixed, verified green.
2. Import path `exchange_adapter::ops::LeverageBracket` doesn't compile —
   `ops` is a private module inside `exchange_adapter`; the type is
   re-exported at the crate root. Fixed to `exchange_adapter::LeverageBracket`.
3. Minor wording glitch in the golden test's panic message for an
   unimplemented exchange ("before golden rows for it can be enforced") —
   reworded to "before golden rows for that exchange can be enforced".
4. Confirmed no `f64` anywhere in the file (only in a doc comment, as
   prose) and no process-environment reads/writes in any test.
5. Confirmed `bracket_for`'s boundary semantics (floor inclusive / cap
   exclusive) are internally consistent and documented, and that the
   worked-example test's expected value (`0.90909`) matches spec §6.3's own
   stated figure exactly rather than an independently-rounded approximation.
6. `Cargo.lock` needed no update after adding the `serde-with-str` feature
   request — it was already resolved that way via
   `exchange_adapter_binance`/`exchange_adapter_mexc`'s existing feature
   request on the same `rust_decimal` version; `git status` shows it
   untouched.

## Concerns for the reviewer

- The `qty`-sign-encodes-side decision (see above) is an inference from the
  fixed row shape, not something spec §6.3 states outright. It is the only
  workable reading given the columns listed, and it reuses an existing
  in-workspace convention, but it's worth a second pair of eyes before
  Layer 7 starts writing real rows against it.
- `bracket_for`'s exact floor-inclusive/cap-exclusive boundary rule is my
  own choice (the brief only says "the bracket whose notional range
  contains the value"); it matches how Binance's own contiguous tiers are
  laid out (each tier's cap equals the next tier's floor) and is the only
  boundary rule that doesn't produce ambiguous double-matches, but it's
  worth confirming against Binance's own `leverageBracket` semantics once
  Layer 7 pulls real ladders.
