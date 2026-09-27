# Task 1.3 Report — Order info client id, fills

## Addendum — coordinator-authorized fix (post-review)

The coordinator authorized local commits on `live-trade-ops` (global-constraints.md
updated accordingly), accepted both judgment calls from the original report
(`serde_json` dev-dep on `exchange_adapter`; `get_order_fills` forward on
`orchestrator/src/main.rs`'s `KindAccount`), and asked for one more instance
of the same fix: `crates/orchestrator/src/no_trade.rs`'s `NoTradeAccount` also
re-implements `MarketAccount` method-by-method (refusing `place_order`/
`cancel_order`, forwarding every read to `inner`). It had the same gap —
`get_order_fills` would have inherited the trait default (`Err(NotSupported)`)
forever, even after Binance/MEXC implement it, silently under-capping this
wrapper versus what `inner` actually supports.

**RED** — extended `every_read_only_call_is_passed_through` to call
`account.get_order_fills(...)` and expect `"get_order_fills"` in the recorded
call list, and added a new dedicated test
`get_order_fills_is_passed_through_while_place_order_stays_refused` (calls
`get_order_fills` then `place_order`, asserting the read reached `inner` while
the mutation is still refused) — both *before* touching `NoTradeAccount`'s
impl, so they exercised the trait default. Ran:

```
cargo test -p orchestrator no_trade
```

```
test no_trade::tests::get_order_fills_is_passed_through_while_place_order_stays_refused ... FAILED
test no_trade::tests::every_read_only_call_is_passed_through ... FAILED
thread '...' panicked at crates/orchestrator/src/no_trade.rs:307:63:
called `Result::unwrap()` on an `Err` value: NotSupported
test result: FAILED. 3 passed; 2 failed; 0 ignored; 0 measured; 38 filtered out
```

Exactly the expected failure mode: the wrapper's default swallowed the call
instead of reaching `RecordingAccount`.

**GREEN** — added an explicit `get_order_fills` forward on `NoTradeAccount`
(placed next to `get_order`, in the "passed through" block) and a matching
override on the test double `RecordingAccount` (records the call, returns
`Ok(vec![])`). Ran the same command:

```
cargo test -p orchestrator no_trade
```

```
test no_trade::tests::the_refusal_explains_itself ... ok
test no_trade::tests::place_order_is_refused_and_never_reaches_the_wrapped_account ... ok
test no_trade::tests::cancel_order_is_refused_and_never_reaches_the_wrapped_account ... ok
test no_trade::tests::every_read_only_call_is_passed_through ... ok
test no_trade::tests::get_order_fills_is_passed_through_while_place_order_stays_refused ... ok
test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 38 filtered out; finished in 0.00s
```

Then confirmed the coordinator's exact requested command, in Docker:

```
docker compose run --build --rm test cargo test -p orchestrator -p exchange_adapter
```

```
test result: ok. 33 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s   [exchange_adapter]
test result: ok. 43 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.33s   [orchestrator]
test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s     [trade_executor main]
test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s     [doc-tests exchange_adapter]
test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s     [doc-tests orchestrator]
```

Zero failures, exit 0. `cargo build --workspace --tests` also re-checked clean
(no ripple elsewhere needed — `Fill`/`get_order_fills` are additive; no other
`impl MarketAccount for` block in the workspace re-implements every method
the way `KindAccount` and `NoTradeAccount` do, so no third site needed this).

### Files changed (this addendum)

- `crates/orchestrator/src/no_trade.rs` — `Fill` import; explicit
  `get_order_fills` forward on `NoTradeAccount`; `RecordingAccount` gains a
  `get_order_fills` override (records + `Ok(vec![])`); extended
  `every_read_only_call_is_passed_through`; added
  `get_order_fills_is_passed_through_while_place_order_stays_refused`. (The
  `client_order_id`/`base_asset`/`quote_asset` lines visible in this file's
  diff are from the original task pass, not this addendum — `RecordingAccount`
  was one of the ripple sites listed in the main report.)

### Concerns

None outstanding — both prior judgment calls are now coordinator-confirmed,
and this addendum closes the one remaining gap of the same shape. Full
workspace Docker gate was run earlier in this task's main pass and was green;
this addendum only reran the two affected crates per the coordinator's
instruction, which is sufficient since the change is additive and contained
to `no_trade.rs`.

## What was implemented

In `crates/exchange_adapter/src/lib.rs`:

- `OrderInfo` gains `client_order_id: Option<String>` — the id this process
  tagged the order with at `place_order` time, echoed back so a caller can
  find the order again by client id.
- New `Fill` type (`Debug, Clone, PartialEq, Serialize, Deserialize`, matching
  `OrderInfo`'s derive set): `trade_id: String, order_id: OrderId, pair: Pair,
  side: Side, price: Decimal, qty: Decimal, quote_qty: Decimal, fee: Decimal,
  fee_asset: String, is_maker: bool, realized_pnl: Option<Decimal>, ts: Ts` —
  exactly the shape given in the brief.
- `MarketAccount::get_order_fills(&self, id: OrderId) -> Result<Vec<Fill>,
  AdapterError>` added as a **default trait method** returning
  `Err(AdapterError::NotSupported)`, so no existing implementor needs to
  change.
- `MarketInfo` gains `base_asset: String, quote_asset: String`. Every
  constructor in this task sets both to `String::new()` to compile; no
  pair-splitting fallback was invented, per the brief.

## TDD evidence

**RED** — added the three new tests referencing `Fill`/`get_order_fills`/
`client_order_id` while temporarily leaving the production types unchanged
(reverted after capturing this, then reapplied), ran:

```
cargo test -p exchange_adapter
```

Failed to compile, exactly as expected — the new types/field/method didn't
exist yet:

```
error[E0422]: cannot find struct, variant or union type `Fill` in this scope
   --> crates/exchange_adapter/src/lib.rs:674:20
error[E0599]: no method named `get_order_fills` found for struct `FakeMarketAccount`
   --> crates/exchange_adapter/src/lib.rs:668:30
error[E0560]: struct `OrderInfo` has no field named `client_order_id`
   --> crates/exchange_adapter/src/lib.rs:723:13
(+ 4 more of the same shape)
error: could not compile `exchange_adapter` (lib test) due to 7 previous errors
```

**GREEN** — reapplied the `Fill`/`get_order_fills`/field additions, ran:

```
cargo test -p exchange_adapter
```

```
running 33 tests
...
test contract_tests::fill_realized_pnl_round_trips_as_none_on_spot ... ok
test contract_tests::fill_round_trips_through_serde_json ... ok
test contract_tests::get_order_fills_defaults_to_not_supported_when_unoverridden ... ok
test contract_tests::order_info_round_trips_through_serde_json_with_client_order_id ... ok
...
test result: ok. 33 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s
```

Then fixed the compile ripples one wave at a time (`cargo build --workspace
--tests` after each), and finally ran the full Docker gate:

```
docker compose run --build --rm test
```

Full workspace result: every crate's `test result: ok`, **zero failures**,
exit code 0. The known-flaky
`market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database`
test is part of `write_path.rs`'s 23-passed/0-failed result in this run — it
did not flake, so no isolated re-run was needed. Disk was not tight this run
(no "No space left on device"); `docker builder prune` was not needed.

## Files changed

- `crates/exchange_adapter/src/lib.rs` — `Fill`, `OrderInfo.client_order_id`,
  `MarketInfo.base_asset`/`quote_asset`, `get_order_fills` default method,
  ripple in `FakeMarketAccount`, 3 new tests.
- `crates/exchange_adapter/Cargo.toml` — added `serde_json` as a
  **dev-dependency** (see "Judgment call" below).
- `crates/exchange_adapter_binance/src/parsing.rs` — `client_order_id: None`
  in `parse_order_info`; `base_asset`/`quote_asset: String::new()` in
  `parse_market_info`.
- `crates/exchange_adapter_mexc/src/dto.rs` — `client_order_id: None` in
  `SpotOrderResponse::into_order_info`.
- `crates/exchange_adapter_mexc/src/account_diff.rs` — `client_order_id: None`
  in a test's `OrderInfo` literal.
- `crates/exchange_adapter_mexc/src/futures.rs` — `client_order_id: None` in
  `get_order`; `base_asset`/`quote_asset: String::new()` in `get_market_info`.
- `crates/exchange_adapter_mexc/src/spot.rs` — `base_asset`/`quote_asset:
  String::new()` in `get_market_info` (no `OrderInfo` literal in this file —
  it delegates to `dto.rs`'s `into_order_info`).
- `crates/execution/src/paper.rs` — `client_order_id: None` in
  `PaperMarketAccount::place_order`'s `OrderInfo`; `base_asset`/`quote_asset:
  String::new()` in `get_market_info`.
- `crates/execution/src/tests.rs` — `client_order_id: None` in a fake's
  `get_order`.
- `crates/market_data/src/pg/rows.rs` — `client_order_id: None` in
  `row_to_order_info` (production; `OrderEventRow` has no such column, so
  this is a real, documented information loss on the DB round trip, not a
  bug) and in 3 test literals.
- `crates/market_data/tests/common/mod.rs` — `client_order_id: None` in
  `order_event`.
- `crates/orchestrator/src/main.rs` — added an explicit
  `get_order_fills` forwarding method on `KindAccount` (see "Judgment call"
  below); this file has no `OrderInfo`/`MarketInfo` literal.
- `crates/orchestrator/src/no_trade.rs`, `crates/orchestrator/src/tests.rs` —
  `client_order_id: None` / `base_asset`/`quote_asset: String::new()` in fake
  `MarketAccount` impls (3 `OrderInfo` sites, 2 `MarketInfo` sites total).
- `crates/state_store/tests/pg_store.rs` — `client_order_id: None` in the
  `resting_stop` test helper.

## Self-review findings / judgment calls

1. **`serde_json` dev-dependency in `exchange_adapter/Cargo.toml`.** The
   brief's unit test ("Fill and OrderInfo round-trip through serde if they
   derive it") requires an actual data format to serialize through; `serde`
   alone has no format. I read the global constraint "exchange_adapter stays
   a leaf crate; no new workspace dependencies" as being about not depending
   on other *workspace member crates* (consistent with "leaf crate" and with
   how "workspace dependency" is used elsewhere in the same doc, e.g.
   `live_trade_ops`: "no workspace crate depends on it"), not as a ban on any
   new external crate. Tasks 1.1/1.2 added zero new Cargo.toml entries, so
   this is the first departure from that pattern — flagging it explicitly in
   case the intended reading is stricter. Used dev-dependency only, same
   version (`1.0.151`) other crates in the workspace already use.
2. **`KindAccount::get_order_fills` forwarding in `orchestrator/src/main.rs`.**
   Not in the brief's file list (it has no `OrderInfo`/`MarketInfo` literal,
   so it wasn't a compile ripple). `KindAccount` re-implements every
   `MarketAccount` method as an explicit forward to `self.resolve()` rather
   than relying on defaults. Leaving `get_order_fills` unforwarded would mean
   that once Binance/MEXC override it in Tasks 2.3/3.1, the *production*
   binary would still silently get `NotSupported` through this wrapper — a
   latent bug of exactly the kind this task's default-method design is
   trying to avoid elsewhere. Added a one-line forward, consistent with
   every other method in that impl. This is additive and low-risk, but
   flagging it as something added beyond the literal file list.
3. **`execution/src/paper.rs`'s `place_order`** could have set
   `client_order_id: order.client_order_id` (the field already exists on
   `OrderRequest` and is right there) instead of `None`. Chose `None`
   per the brief's explicit instruction that this file's ripple is
   mechanical — echoing the client id back is real behavior that belongs to
   a task that actually tests it, not a silent addition here. Left a comment
   explaining the choice so a future reader doesn't mistake it for an
   oversight.
4. **`market_data`'s DB round trip** (`row_to_order_info`) always returns
   `client_order_id: None` because `OrderEventRow`/the migration have no such
   column. This is a real (documented) capability gap, not a bug — no
   migration was added, per scope (Task 1.3 only touches the shared type).
   Commented in place.
5. Checked for any other `MarketAccount` implementor or `OrderInfo`/
   `MarketInfo` construction site across the whole workspace (`grep -rn` for
   both literals plus `impl MarketAccount for`) — the list above is
   exhaustive; nothing outside it needed touching.
6. Confirmed no test's *meaning* changed: every ripple only adds a field to
   an already-matching struct literal; no assertions were altered.

## Test summary

`docker compose run --build --rm test`: full workspace green, 0 failures,
exit 0. `exchange_adapter` alone: 33 passed (30 pre-existing + 3 new).

## Concerns

- Item 1 above (`serde_json` dev-dep) and item 2 (`KindAccount` forwarding)
  are judgment calls beyond the brief's literal instructions — please confirm
  they're the right call, or tell me to revert either.
- No other concerns; workspace is fully green, diff is minimal and matches
  the brief's file list plus the two additions above.
