# Task 6.2 report: Harness components

Commit: `fbd4b60` — `feat(live_trade_ops): live harness components` on branch `live-trade-ops`.

## What was implemented

New module `crates/live_trade_ops/src/harness/` (mod.rs + 10 files), re-exported from `lib.rs`:

| File | Component | Notes |
|---|---|---|
| `mod.rs` | `HarnessError` | one flat error enum for every component below; `From<AdapterError>`/`From<JournalError>` so `?` works throughout |
| `book.rs` | `BookWatcher` | background task consuming `subscribe_market_data`, maintains bids/asks via `apply_deltas`; `best_bid`/`best_ask` enforce the 2s freshness rule (`tokio::time::Instant`); a `Gap` event marks the book gapped without refreshing its timestamp, so a later stale read reports `BookGap` instead of plain `BookStale` |
| `pricer.rs` | `Pricer` | reads `MarketInfo` once at construction, refuses empty `base_asset`/`quote_asset` there; `resting_buy`/`resting_sell`/`marketable_buy`/`marketable_sell` round by **order side** (BUY down, SELL up) regardless of resting vs. marketable, and panic (not `Result`) if the book isn't fresh — safe because every caller runs under `with_cleanup`'s `catch_unwind`; `qty_for_notional` rounds down, `min_order_qty` rounds up (the one deliberate up-rounding, so the result still clears `min_notional`); `check` refuses outside `[min_notional, LIVE_MAX_NOTIONAL]` |
| `countdown.rs` | `countdown`, `RestingOrder`, `Touched` | 1s-tick loop, `tokio::time::sleep`; touched sticky once observed; duration asserted on `tokio::time::Instant` |
| `capped.rs` | `CappedAccount<'a>` | wraps `&'a dyn MarketAccount` (matches spec's literal wording); refuses `qty×price > max_notional` or a priceless order with `AdapterError::InvalidRequest("notional cap ...")` before ever calling `inner` |
| `ids.rs` | `client_id`, `validate_client_id` | `livetest-{run8}-{step}`; panics (never truncates) on a malformed result |
| `config.rs` | `LiveConfig` | `LIVE_PAIR`/`LIVE_MAX_NOTIONAL`(15)/`LIVE_WAIT_SECS`(20)/`LIVE_RUN_ID`(fresh uuid v4)/`LIVE_REQUIRE_ALL`; `from_env_with(get)` for tests, `from_env()` the real loader |
| `poller.rs` | `await_filled` | polls `get_order` to `Filled` (caller's `timeout`), then `get_order_fills` until `Σ qty == filled_qty` (fixed 10s per spec §4.5) |
| `settlement_check.rs` | `check_settlement`, `check_journal`, `Balances` | balance-delta check against `Settlement::net_deltas` (exact, no tolerance) plus a fee-rate check; journal check compares `exchange_order_id`/`status`/`filled_qty`/`avg_fill_price`/`Σ fills.qty`/fee totals against the exchange's own `OrderInfo` |
| `cleanup.rs` | `with_cleanup`, `RunCtx`, `RunOutcome` | `catch_unwind`-wrapped body, always runs `ctx`'s cleanup closure afterward, combines both outcomes; a cleanup failure fails the run even if the body passed |
| `report.rs` | `RunReport`, `StepOutcome`, `FillReportLine`, `BalanceLine` | per-step outcomes, `record_unmapped` (`UNMAPPED <exchange> <code>: <message>`), `write_jsonl(base_dir)` appends one JSON line per fill to `{base_dir}/live-trade-ops/{run_id}.jsonl` |

Also touched:
- `crates/live_trade_ops/src/journal/mod.rs`: widened `from_order_status` from private to `pub(crate)` so `check_journal` can reuse the exact same `OrderStatus`→`JournalStatus` mapping instead of duplicating it. One-line visibility change only, no behaviour change.
- `crates/live_trade_ops/src/lib.rs`: `pub mod harness;` + re-exports.
- `crates/live_trade_ops/Cargo.toml`: added `uuid` (already resolved elsewhere in the workspace lockfile — Cargo.lock diff is exactly one line, `+ "uuid"` under `live_trade_ops`'s dependency list, no version bumps); moved `serde`/`serde_json` from `[dev-dependencies]` to `[dependencies]` (RunReport's JSONL writer is non-test code, unlike `risk`'s golden-file test which was their only prior caller).

### Design decisions not fully pinned by the brief

The brief gives one-line signatures; a few shapes needed a decision I made explicitly rather than improvising silently:

- **`CappedAccount<'a>` borrows `&'a dyn MarketAccount`** (matching spec §5.2's literal wording, "Wraps `&dyn MarketAccount`"), not `Arc` like `JournaledAccount`. This makes it trivial to test directly against `ScriptedExchange::margin()`'s borrow; how Task 6.3 bridges this borrow with `JournaledAccount`'s owned `Arc<dyn MarketAccount>` in the real `JournaledAccount(CappedAccount(inner), journal)` stack is that task's problem, not this one's.
- **`with_cleanup`'s cleanup routine is supplied via `RunCtx::new`'s closure**, not a second parameter to `with_cleanup` itself — the brief's signature only takes `ctx` and `body`. What cleanup actually *does* (cancel `livetest-` orders, repay margin, close futures positions) is exchange/kind-specific scenario logic and explicitly out of this task's scope (Task 6.3); this module only supplies the generic catch/always-run/combine plumbing spec §5.2 describes around it.
- **`Balances`** (a `Vec<(String, Decimal)>` newtype) didn't exist before this task; `check_settlement`'s brief signature names it as a parameter type without defining it. Kept intentionally source-agnostic — the caller (a Task 6.3 scenario) builds it from either `margin_balances()`'s `net_asset` or `futures_margin_summary()`'s `wallet_balance`, whichever its kind uses.
- **`check_journal`'s "settle(...) == the settlement the step checked" (spec §5.2)** couldn't be a literal re-derivation of `Settlement` inside `check_journal` — the function's signature (`journal, client_id, info, s`) carries no `MarketKind`/`PairAssets`/`Side`, which `settle()` needs for `net_deltas`/`avg_price`/`net_price`/`realized_pnl`. What *doesn't* need those three is `settle`'s fee arithmetic (`fees`, computed purely from `fill.fee`/`fee_asset`), so `check_journal` recomputes just the fee totals from the journaled fills and compares them to `s.fees` — a real, meaningful cross-check that fits the signature it was actually given, documented in the function's doc comment rather than silently narrowed.
- **`FEE_RATE_EPSILON` (0.0001) is a fixed constant**, not derived from `MarketInfo`'s precision — `check_settlement`'s signature carries no `MarketInfo`/precision either. Documented as a known simplification in `settlement_check.rs`'s doc comment.

## TDD evidence

### RED (before implementation existed)

Writing the harness files with their test modules and running `cargo check` first produced genuine compile-time RED (missing `use exchange_adapter::ExchangeAdapter;` in five test modules, plus `Pricer` needing `Debug` for `unwrap_err()`) — 20 compile errors, listed in full below (excerpt):

```
$ cargo check -p live_trade_ops --tests
error[E0599]: no method named `margin` found for struct `fake::ScriptedExchange` in the current scope
   --> crates/live_trade_ops/src/harness/countdown.rs:150:51
   ...
error[E0277]: `pricer::Pricer` doesn't implement `std::fmt::Debug`
    --> crates/live_trade_ops/src/harness/pricer.rs:208:58
   ...
error: could not compile `live_trade_ops` (lib test) due to 20 previous errors
```

Fixed by adding `ExchangeAdapter` to the five affected test modules' imports (`book.rs`, `capped.rs`, `countdown.rs`, `poller.rs`, `pricer.rs`) and `#[derive(Debug)]` on `Pricer`.

After that fix, the suite compiled and ran genuinely RED once more — a real behavioural bug, not a missing-symbol bug:

```
$ cargo test -p live_trade_ops --lib
...
test harness::cleanup::tests::a_panicking_body_still_runs_cleanup_and_fails ... FAILED
test result: FAILED. 145 passed; 1 failed; 0 ignored; 0 measured; finished in 1.00s
```

Root cause (isolated with a throwaway `/tmp/panictest` reproduction, deleted afterward): `Err(panic) => panic_message(&panic)` where `panic: Box<dyn Any + Send>` — `Box<dyn Any + Send>` itself satisfies the blanket `impl Any for T: 'static`, so `&panic` coerces to `&(dyn Any + Send)` by **unsizing the `Box` itself** into the trait object rather than deref'ing to the payload inside it. `downcast_ref::<&str>()`/`::<String>()` then silently (no compile error) report "neither" no matter what the real panic payload was. Confirmed the exact mechanism with a minimal `/tmp/panictest` crate before touching the real fix, isolating: sync `catch_unwind` (works), inline async `catch_unwind` in the same function (works), only breaks once the downcast crosses into a **separate function** taking `&(dyn Any + Send)` and is called as `f(&boxed)` instead of `f(&*boxed)`.

Fix: `panic_message(&*panic)` — explicit deref forces the coercion onto the payload. Documented at the call site (`cleanup.rs`) so the footgun doesn't get silently "fixed" back the wrong way later.

### GREEN

```
$ cargo test -p live_trade_ops --lib
test result: ok. 146 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.00s

$ cargo test -p live_trade_ops --test no_adapter_imports
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s
```

### Docker gate

```
$ docker compose run --build --rm test cargo test --workspace --no-fail-fast
```

Every target passed except one:
```
error: 1 target failed:
    `-p market_data --test write_path`
```
— specifically `shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database`, the flake named in TECH_DEBT §5 and called out in the task brief. Re-run in isolation:
```
$ docker compose run --build --rm test cargo test -p market_data --test write_path shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 22 filtered out; finished in 0.97s
```
Passes on its own, confirming the known flake and not a regression from this task. `live_trade_ops`'s own targets (lib: 146, `no_adapter_imports`: 1, `pg_journal`: 9) were all green in the same gate run.

Also ran, per the task's manifest-touching requirement:
```
$ docker compose build executor
...
 executor  Built
```
Green — the release image (which never compiles `live_trade_ops`, a test-only crate) is unaffected.

`Cargo.lock`'s diff is exactly one line (`+ "uuid"` under `live_trade_ops`'s dependency list) — no unrelated version bumps. It was regenerated by ordinary local `cargo check`/`cargo test` runs under my own host user (`om`, confirmed via `ls -la Cargo.lock` — not root), not inside Docker, so the bind-mount+`--user` procedure for avoiding root-owned files didn't apply here; the Docker gate and `docker compose build executor` both then confirmed the resulting lockfile builds and tests cleanly in the container.

## Files changed

- `crates/live_trade_ops/src/harness/{mod,book,pricer,countdown,capped,cleanup,poller,settlement_check,report,ids,config}.rs` (new)
- `crates/live_trade_ops/src/lib.rs` (added `pub mod harness;` + re-exports)
- `crates/live_trade_ops/src/journal/mod.rs` (`from_order_status`: private → `pub(crate)`)
- `crates/live_trade_ops/Cargo.toml` (added `uuid`; moved `serde`/`serde_json` dev → normal)
- `Cargo.lock` (one line: `uuid` added under `live_trade_ops`)

## Self-review findings

- Every test named in the brief's list is present and asserts real behaviour (verified by re-reading each against the brief/spec after writing, not just "it's green"): pricer rounding both directions + refusals (`pricer.rs`); countdown duration on the paused clock + touched flag (`countdown.rs`); cap blocking before the inner account is called, proven via an *empty* script so any real call would panic, not just via `calls().is_empty()` after the fact (`capped.rs`); client-id format/length, including the "must panic, never truncate" cases (`ids.rs`); poller waiting out fill lag across three scripted `get_order_fills` replies (`poller.rs`); settlement check passing on correct balances and failing with the asset named on a one-unit (0.0001) discrepancy (`settlement_check.rs`); journal check failing on a mismatched exchange id (`settlement_check.rs`); report's JSONL line shape, parsed back with `serde_json` and checked field-by-field (`report.rs`).
- No `f64` anywhere (`grep -rn "f64" src/harness/` — none). No `std::thread::sleep`/`std::time::Instant` (`tokio::time::{sleep, Instant}` throughout `book.rs`/`countdown.rs`/`poller.rs`). No adapter-crate import outside `registry.rs` (`no_adapter_imports.rs` still passes unchanged). No exchange-name comparison anywhere in `harness/`.
- Compiler output is warning-free for `cargo build -p live_trade_ops --tests` (checked explicitly, zero warnings).
- Per the task's carry-over note (`CallMatcher::{GetOrder, GetOrderFills, CancelOrder}` don't match on `OrderId`): `poller.rs`'s test `await_filled_queries_the_order_it_was_asked_about_not_a_different_one` asserts order identity through `exchange.calls()` rather than relying on the matcher, exactly as instructed.
- Left the fixed `FEE_RATE_EPSILON`/`Balances`/`with_cleanup`'s closure-based cleanup routine as documented, deliberate narrowings where the brief's one-line signature didn't fully constrain the shape (see "Design decisions" above) rather than guessing silently.

## Fix round 1/5

Two findings from review, both addressed:

### 1. Important — `CappedAccount` must own `Arc<dyn MarketAccount>`, not borrow

The reviewer's reasoning was correct and decisive: `MarketAccount: Send + Sync` carries no lifetime, so `Arc<dyn MarketAccount>` means `dyn MarketAccount + 'static`; coercing `Arc<CappedAccount<'a>>` into that requires `'a = 'static`, which a locally-built adapter account never satisfies without leaking it. Spec §5.2's own composition, `JournaledAccount(CappedAccount(adapter account), journal)`, therefore didn't compile as originally written.

Fixed:
- `crates/live_trade_ops/src/harness/capped.rs`: `CappedAccount` now owns `inner: Arc<dyn MarketAccount>` (dropped the `<'a>` lifetime parameter entirely), mirroring `JournaledAccount::new`'s shape. Doc comment rewritten to explain why, referencing this exact review finding so it isn't silently "fixed" back later.
- `crates/live_trade_ops/src/fake/mod.rs` (task 6.1's file — minimal, additive touch): `ScriptedExchange`'s internal `account` field changed from `ScriptedAccount` to `Arc<ScriptedAccount>`; added `pub fn account_arc(&self) -> Arc<dyn MarketAccount>` so tests (and, later, real scenario code) can get an owned handle to the same backing account `margin()`/`futures()` already borrow from. `margin()`/`futures()`/`margin_ops()`/`futures_ops()` now go through `self.account.as_ref()` instead of `&self.account` — same observable behaviour, just through the new `Arc` field.
- Existing `CappedAccount` tests updated from `exchange.margin().unwrap()` to `exchange.account_arc()`. Kept the empty-`Script` proof exactly as the reviewer asked ("stronger form — an unexpected call panics inside the fake rather than merely leaving `calls()` empty").
- **New tests, both in `capped.rs`**, building spec §5.2's actual full stack and placing an order through it (not just asserting the types compile):
  - `the_full_journaled_capped_stack_places_one_order` — `JournaledAccount::new(Arc::new(CappedAccount::new(exchange.account_arc(), cap)), journal, ctx)`, places an at-cap order, asserts the ack comes back through both decorators unchanged and the journal row exists with the right `exchange_order_id`.
  - `the_full_journaled_capped_stack_refuses_an_over_cap_order_before_the_exchange_or_the_journal_see_it` — same stack, an over-cap order; asserts the exchange is never called (empty script) and that `JournaledAccount`'s own fail-closed rule (spec §4.7) still records the local refusal as a terminal `Rejected` row rather than leaving it dangling as `Intent`.

### 2. Minor — journal fee cross-check was order-sensitive

`settlement_check.rs::check_journal` compared `journaled_fees` (built in `journal.fills(...)`'s own order) against `s.fees` (built in `settle()`'s `fills` argument order) with `Vec::ne` — a real exchange order whose fills carry more than one `fee_asset` (exactly the case `settle`'s own test list covers) could have the same fees as sets but in different order, since `PgOrderJournal::fills` orders by `(exchange_ts, trade_id)`, independent of whatever order the caller passed fills to `settle()` in.

Fixed: both sides are now cloned and sorted by asset name before comparing (each asset appears at most once per side already, since both the settle-fee loop and the journal-fee loop merge duplicates per asset, so a sort is sufficient to make the comparison order-independent — no need for a full set/map type).

New test `fee_cross_check_is_order_insensitive_across_multiple_fee_assets`: builds two fills with different fee assets (LINK, BNB), computes `s = settle(...)` from them in `[LINK, BNB]` order (asserted via a sanity check that `s.fees[0].0 == "LINK"`), then records the *same* two fills into a `MemoryJournal` via two separate `record_fills` calls in the *opposite* order, so `journal.fills(...)` returns `[BNB, LINK]` (asserted via a second sanity check). `check_journal` still passes — proving the fix, not just asserting it by inspection.

### Accepted without changes (per review)

- The `&*panic` deref fix in `cleanup.rs` — confirmed correct, left as-is.
- `BookWatcher`'s `Gap`/`BookGap` scoping — confirmed sufficient for this task; the bounded 10s resync loop is carried into Task 6.3 as a requirement there, not here.
- `FEE_RATE_EPSILON` as a fixed constant rather than derived from the fee asset's precision — recorded as debt, not fixed in this round.

### Answer to the open question: printed human-readable fill report

**Left for Task 6.3, not implemented here.** Spec §5.5 describes two outputs: the printed form (`[livetest-…] margin BUY …` / `ordered` / `executed` / `fee paid` / `resulting` / `balances`, shown with `--nocapture`) and the JSONL line. This task's brief (`report.rs`'s one-liner: "writes target/live-trade-ops/{run}.jsonl") only committed to the JSONL half, and that's the only half `RunReport` implements — there is no `println!`/`Display` rendering of a `FillReportLine` anywhere in this diff. `FillReportLine`'s fields carry everything the printed form needs (they were deliberately designed to map one-to-one onto `Settlement` plus ordered qty/price and before/after/expected/diff balances, per spec §5.5's own "Fields map one-to-one" line), so Task 6.3 — which is the layer that actually knows when an order filled during a live scenario and would call `--nocapture`-visible `println!` — can build the printed form directly from a `FillReportLine` it already has, rather than needing anything new from this module. Flagging explicitly, as asked, so the coordinator can require it there.

## Re-verification after fix round 1/5

```
$ cargo test -p live_trade_ops --lib
test result: ok. 149 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.00s

$ cargo test -p live_trade_ops --test no_adapter_imports
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s

$ cargo build -p live_trade_ops --tests   # zero warnings, checked explicitly
```

Full gate:
```
$ docker compose run --build --rm test cargo test --workspace --no-fail-fast
```
Every target passed, including `market_data --test write_path` (the previously-flagged flake passed cleanly this run too) and `live_trade_ops`'s own three targets (lib: 149/149, `no_adapter_imports`: 1/1, `pg_journal`: 9/9). No `error:` anywhere in the gate's output this run.

`Cargo.toml`/`Cargo.lock` were **not** touched in this fix round (no new dependencies), so `docker compose build executor` was not re-run — nothing in the manifest changed since the last verified-green build of it.

## Files changed (this fix round)

- `crates/live_trade_ops/src/harness/capped.rs` (`CappedAccount`: borrow → `Arc`; two new full-stack tests)
- `crates/live_trade_ops/src/harness/settlement_check.rs` (order-insensitive fee comparison; one new test)
- `crates/live_trade_ops/src/fake/mod.rs` (`ScriptedExchange`: `Arc`-backed account + `account_arc()` accessor)

## Concerns for the reviewer

1. **`BookWatcher`'s `Gap` handling is a simplification**, not spec §5.2's full "cannot resync within 10s" retry policy. Per `exchange_adapter::GapMarker`'s own doc comment, the *live* `subscribe_market_data` path never actually produces this variant in production (only `market_data`'s replayed stream does), so this is defence-in-depth for a case the scripted fake can still exercise, not something Binance/MEXC's real feeds are expected to hit. I distinguish `BookGap` from plain `BookStale` (so a caller can tell the two apart) but do not implement an active resubscribe-and-wait-up-to-10s loop; that felt like it belonged to the scenario layer (Task 6.3, explicitly out of scope here) rather than the low-level watcher. Flagging in case the reviewer reads spec §5.2 as requiring the retry loop itself in this component.
2. ~~**`CappedAccount` borrows (`&'a dyn MarketAccount`) rather than owning (`Arc<dyn MarketAccount>`)**...~~ — **resolved in fix round 1/5**: `CappedAccount` now owns `Arc<dyn MarketAccount>`, and the full `JournaledAccount(CappedAccount(inner), journal)` stack is built and exercised (one order placed through it, one refused) in `capped.rs`'s own tests. See "Fix round 1/5" above.
3. The Rust panic-payload footgun documented above (`&*panic`, not `&panic`) is subtle enough that I'd flag it for double-checking independently — it's exactly the kind of thing that silently "works" (compiles, never panics itself) while quietly returning the wrong string, so a reviewer skimming `cleanup.rs` might not notice why the explicit deref matters without reading the comment.
