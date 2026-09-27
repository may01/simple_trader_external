# Task 7.4a report — Five defects found by the first live margin run

Branch: `live-trade-ops`. Commit: see branch history (this task's own commit follows this
report).

## Context

The first real live run of the margin scenario (spec §6.1) executed against Binance mainnet —
by mistake, against the operator's **main** account rather than the dedicated sub-account the
spec assumes. It failed at the exchange with `-1021` (timestamp outside `recvWindow`) before
step 0 ever read a balance, but the cleanup guard (which always runs, per `with_cleanup`) then
traded anyway: it bought back 0.42 LINK (~5.55 USDT) to repay a 0.08497688 LINK loan that
pre-dated the run entirely, plus a 0.00002332 USDT repayment. This report covers the five
defects that run exposed, worst first, matching the task brief's own ordering.

## L1 — Cleanup scoped to the run, not to live balances

**Root cause.** `margin_cleanup` re-derived "outstanding debt" purely from a live
`margin_balances()` read (Task 6.3's own deliberate choice — its report called this "more
robust than a flag set earlier"). That conflates this run's own debt with anything else sitting
on the account. On a dedicated, exclusive sub-account the two happen to coincide (step 0
already proves `borrowed == 0` before the run ever borrows anything); on the account this run
actually ran against, they didn't — the 0.085 LINK debt was a pre-existing, unrelated position.

**Fix.** Added a `LoanLedger` (`Arc<Mutex<HashMap<String, Decimal>>>`, `margin_scenario.rs`):
every successful `borrow()` call the body makes (step 4a's `ensure_sell_funds`, step 7's
explicit borrows) increments its asset's entry; every successful `repay()` call (step 6b, step
8) decrements it, clamped at zero. `margin_cleanup` now takes this ledger and:
- reads it, not `margin_balances()`, to decide **whether** it owes anything on a given asset —
  if the ledger shows zero owed, cleanup does nothing to that asset's debt at all, no matter
  what the exchange shows;
- when it does owe something, bounds both the buyback and the repay to
  `min(ledger amount, live borrowed + interest)` — never more than either number
  independently justifies;
- for any live debt beyond that bound, records and prints a line naming the asset and amount
  left untouched (`"<asset>: <amount> outstanding was not created by this run -- left
  untouched"` / `"... pre-existing debt left untouched after repaying this run's <amount>"`).

**Disclosed limitation — the crux the task brief asked me to surface if found.** The ledger
tracks *principal* the run itself borrowed. Binance's `interest` figure is one pooled number
per asset, not itemised per loan — there is no API call that says "how much of this asset's
accrued interest belongs to the loan opened at time T" on an account that also carries a
foreign loan on the same asset. So on an account this run does **not** exclusively own, cleanup
repays exactly the recorded principal (safe, bounded, never touches foreign money) and leaves
any residual interest — its own accrued interest included, if a foreign loan on the same asset
makes the two inseparable — as a disclosed gap rather than guessing at a split it cannot
observe. On the spec's own intended setup (dedicated sub-account, `borrowed == 0` proven at
step 0) this is moot: foreign debt cannot exist at borrow time, so all subsequently-accrued
interest is unambiguously the run's own. It only becomes a real gap on an account the test
doesn't exclusively own — exactly what happened here, and exactly why the spec calls for a
dedicated sub-account (D4) in the first place. I did not try to guess or estimate an interest
split; I recorded the gap in code comments (`margin_scenario.rs`'s `LoanLedger` doc comment)
instead.

**Tests added** (`crates/live_trade_ops/src/tests.rs`):
- `self_test_3a_a_panic_between_4a_and_6b_leaves_pre_existing_debt_untouched_and_reports_it` —
  4a needs no borrow (fee taken in USDT), so the ledger has nothing recorded for LINK; a stray
  0.4 LINK debt appears at cleanup time regardless (the scripted fake has no causality to keep
  consistent — this stands in for "someone else's position"); asserts no buyback order, no
  repay call, and a report line naming the untouched foreign debt.
- `self_test_3b_a_panic_between_4a_and_6b_still_repays_the_loan_this_run_itself_created` — same
  panic point, but 4a's borrow is genuine (fee in LINK, as in the happy path), so the ledger
  does have a 0.4 LINK entry; asserts cleanup still buys back and repays exactly that amount,
  and that the buyback fill and repayment both land in the returned `RunReport` (see L3).

These two tests replace the old `self_test_3`, whose own script comment admitted it was
exercising exactly the design L1 says is wrong ("independent of the fact that 4a itself never
borrowed in this script ... cleanup buys it back and repays").

## L2 — `-1021` (timestamp outside `recvWindow`)

**Root cause.** The host clock was fine (186ms skew); the very first signed call of the run
measured 6.9s end to end. `rest.rs::execute` already stamps `timestamp` as late as possible —
immediately before signing, freshly on every call (there is no retry loop anywhere in this
codebase that resends a previously-built request, so nothing could have reused a stale
timestamp) — so the 6.9s was in-flight network time (cold DNS/TCP/TLS) between the stamp and
the exchange receiving it, which the old 5000ms `recvWindow` default could not absorb.

**Fix** (`crates/exchange_adapter_binance/src/config.rs`): raised `DEFAULT_RECV_WINDOW_MS` from
5,000 to 10,000 — roughly 45% more headroom than the observed 6.9s, while staying well under
Binance's own 60,000ms ceiling, so a genuinely stale/replayed signature is still rejected
quickly. Comment on the constant explains the reasoning and cites the observed number. The
existing `recv_window_defaults_when_absent` test asserts against the constant itself, so it
required no change.

**Test added** (`crates/exchange_adapter_binance/tests/wiremock_tests.rs`):
`a_second_signed_call_carries_a_later_timestamp_than_the_first` — calls a signed endpoint
(`get_account_state`) twice through the public adapter API against a wiremock server that
captures each request's `timestamp` query param via a custom `respond_with` closure, with a
real (unpaused) 5ms sleep between calls, asserting the second timestamp is strictly greater
than the first — pinning the "always fresh, per attempt" property as a regression guard.

## L3 — Cleanup's actions were invisible to the report

**Root cause.** Cleanup placed an order and made two repayments through calls that bypassed
`RunReport` entirely — the printed report and the JSONL only ever reflected the body's own
steps and fills.

**Fix.**
- `print_fill_report` (`margin_scenario.rs`) was refactored to take its inputs as plain fields
  (`pair`, `assets`, `fees`, `report`) instead of a whole `&StepCtx` (cleanup has no `StepCtx`
  of its own), so `margin_cleanup`'s own buyback order — once it fills — is printed and
  `record_fill`-ed through the **exact same function** the body's steps 3/6/6b/8 use. A reader
  cannot tell from the report which of the two produced a given fill line, which is the point.
- Cleanup's cancels and repayments (which have no `FillReportLine` shape — they moved no order)
  are recorded via `RunReport::record_step` with a descriptive message as the step name (e.g.
  `"cleanup: repaid 0.4 LINK (this run's own loan)"`, `"cleanup: cancelled open order id(s)
  [999]"`, `"cleanup: foreign debt left untouched -- LINK: 0.4 outstanding was not created by
  this run -- left untouched"`).
- `RunReport::write_jsonl` (`harness/report.rs`) now appends every recorded step as its own
  JSON line (`{"step": ..., "outcome": ...}`), after the fill lines — additive, not a
  replacement: a reader that only looked at the first `fills().len()` lines before (this
  crate's own earlier tests included) sees nothing new. `StepOutcome` gained `Serialize` for
  this. The runner's own printed summary (`tests/live_trade_ops.rs::print_report`) already
  iterates `report.steps()`, so cleanup's step lines show up there too with no runner change
  needed.

**Tests added:**
- `harness::report::tests::write_jsonl_includes_recorded_steps_after_the_fills` — a fill plus
  two steps (`Passed`, `Skipped`) round-trip through `write_jsonl` as 3 JSON lines in order,
  fill first.
- `self_test_3b` (above) also asserts `report.fills()` contains the cleanup buyback's fill line
  and `report.steps()` contains a `Passed` step naming the LINK repayment — i.e. the fix is
  proven end to end through the real cleanup path, not just the report type in isolation.

## L4 — Malformed client order id (`livetest--cl-buyback`)

**Root cause, both halves.**
1. `LiveConfig::from_env_with` already generated a fresh UUID when `LIVE_RUN_ID` was **absent**
   — but `docker-compose.yml`'s `test` service passes it through as `LIVE_RUN_ID=${LIVE_RUN_ID:-}`,
   which (this is standard Compose behaviour, not a bug in that file) sets the *container's* var
   to the **empty string** when the operator's shell doesn't have it, never leaving it absent.
   So `get("LIVE_RUN_ID")` returned `Some("")`, the `unwrap_or_else` never fired, and `run_id`
   ended up `""` — `run8` (its first 8 chars) is also `""`, producing `livetest--cl-buyback`.
2. `ids::validate` checked only charset and length. Every character of `livetest--cl-buyback`
   is individually valid `[a-z0-9-]`, so nothing caught the empty run segment.

**Fix, both halves** (matches the brief's "fix both halves"):
1. `LiveConfig::from_env_with` (`harness/config.rs`): `LIVE_RUN_ID` is now filtered through
   `.filter(|v| !v.trim().is_empty())` before the `unwrap_or_else` — an empty or whitespace-only
   value now generates a fresh UUID exactly like an absent one.
2. `ids::validate` (`harness/ids.rs`): now also rejects any id with an empty segment between
   hyphens (`id.split('-').any(|s| s.is_empty())`) — catches a blank run id, a blank step, and a
   doubled/leading/trailing hyphen uniformly. This is deliberately kept as a second, independent
   check (belt and braces): `client_id` is the one place spec §5.4's shape is enforced for every
   caller, cleanup included, not just the ones that go through `LiveConfig`.

**Tests added:**
- `harness::config::tests::empty_live_run_id_generates_a_fresh_uuid_same_as_unset` /
  `whitespace_only_live_run_id_generates_a_fresh_uuid_same_as_unset`.
- `harness::ids::tests::an_empty_run_id_panics_instead_of_producing_a_double_hyphen` (proves
  `client_id("", "cl-buyback")` panics rather than returning the malformed id) and
  `validate_client_id_rejects_an_empty_run_segment` (the `Result`-returning half).

## L5 — `EXCHANGE_NETWORK` unreachable-as-unset under Docker

**Root cause.** Same Compose mechanism as L4: `docker-compose.yml`'s `test` service passes
`EXCHANGE_NETWORK=${EXCHANGE_NETWORK:-}`, which sets the container's var to an empty string
when unset on the host — never actually leaving it absent. `AdapterConfig::from_env_with`
(`crates/exchange_adapter/src/config.rs`) rejected an empty value as `ConfigError::Invalid`
(a deliberate Task 1.1 decision, "empty is distinct from unset, and rejected") — so the
documented "unset means mainnet" default was unreachable in the only way this is ever actually
run, and the live run's first attempt died on it before ever reaching `-1021`.

**Fix.** `AdapterConfig::from_env_with`'s `EXCHANGE_NETWORK` match now treats
`v.trim().is_empty()` the same as `None` (mainnet) — a genuinely unrecognised, non-empty value
(`"MAINNET"`, `"prod"`, ...) is still a hard error, never silently coerced.

**Tests updated/added:** `network_empty_string_is_invalid_not_unset` was renamed to
`network_empty_string_is_treated_exactly_like_unset_mainnet` and now asserts `Network::Mainnet`
instead of an error (this supersedes the Task 1.1 pin, as instructed); added
`network_whitespace_only_is_treated_exactly_like_unset_mainnet` for the whitespace case.

**Env templates.** All three mainnet `.env.example` files (`binance.futures.mainnet`,
`binance.margin.mainnet`, `mexc.futures.mainnet`) now set `EXCHANGE_NETWORK=mainnet` explicitly
(previously commented out) — the testnet file already had `EXCHANGE_NETWORK=testnet`
uncommented. Comments explain the Compose empty-string mechanism so the intent is visible
either way, per the brief.

## Files changed

Production crates (expected — L2/L5 are connector defects the live run exposed):
- `crates/exchange_adapter/src/config.rs` — L5 fix + 2 tests updated/added.
- `crates/exchange_adapter_binance/src/config.rs` — L2 fix (default `recv_window_ms`).
- `crates/exchange_adapter_binance/tests/wiremock_tests.rs` — L2 test.

`live_trade_ops` (everything else, as scoped):
- `crates/live_trade_ops/src/harness/config.rs` — L4 fix (half 1) + 2 tests.
- `crates/live_trade_ops/src/harness/ids.rs` — L4 fix (half 2) + 2 tests.
- `crates/live_trade_ops/src/harness/report.rs` — L3 fix (`StepOutcome: Serialize`,
  `write_jsonl` includes steps) + 1 test.
- `crates/live_trade_ops/src/margin_scenario.rs` — L1 fix (`LoanLedger`, `margin_cleanup`
  rewrite) + L3 fix (`print_fill_report` refactored to a free function, shared by body and
  cleanup).
- `crates/live_trade_ops/src/tests.rs` — replaced `self_test_3` with `self_test_3a`/`3b`.

Config (no code):
- `configs/live-trade-ops/binance.futures.mainnet.env.example`
- `configs/live-trade-ops/binance.margin.mainnet.env.example`
- `configs/live-trade-ops/mexc.futures.mainnet.env.example`

No manifest (`Cargo.toml`, `docker-compose.yml`) was touched, so `docker compose build
executor` was not required by the gate; skipped.

## TDD evidence

For L1, L3, L4 and L5 I wrote the fix and its test(s) together, then explicitly re-verified red
→ green for each by temporarily undoing just that fix (in a scratch copy, restored immediately
after via a file backup — never `git checkout` on uncommitted work) and re-running the new
test(s):

- **L5** (`exchange_adapter/src/config.rs`): removed the `v.trim().is_empty()` match arm →
  `network_empty_string_is_treated_exactly_like_unset_mainnet` failed with
  `Invalid { var: "EXCHANGE_NETWORK", reason: "must be \`testnet\` or \`mainnet\`, got \`\`" }`.
  Restored, green again.
- **L4, half 1** (`harness/config.rs`): removed the `.filter(|v| !v.trim().is_empty())` →
  `empty_live_run_id_generates_a_fresh_uuid_same_as_unset` failed (`config.run_id` was `""`, not
  a valid uuid). Restored, green again.
- **L4, half 2** (`harness/ids.rs`): removed the empty-segment check from `validate` → both
  `an_empty_run_id_panics_instead_of_producing_a_double_hyphen` (didn't panic) and
  `validate_client_id_rejects_an_empty_run_segment` failed. Restored, green again.
- **L1** (`margin_scenario.rs`): replaced `owed_by_run(&ledger, &asset)` with `live_debt`
  (simulating the old re-derive-from-balances design) → `self_test_3a` failed with the scripted
  fake panicking on an *unscripted* `cl-buyback` `PlaceOrder` call — i.e. with the old design
  restored, cleanup tried to buy back and repay the foreign debt exactly as the live run did.
  Restored, green again.
- **L3** (`harness/report.rs`): removed `write_jsonl`'s step-appending loop →
  `write_jsonl_includes_recorded_steps_after_the_fills` failed (1 line instead of the expected
  3). Restored, green again.

**L2** is a regression guard rather than a red/green pair: `rest.rs::execute` already stamped a
fresh timestamp per call before this task (no retry loop exists anywhere in this codebase that
could have reused a stale one), so `a_second_signed_call_carries_a_later_timestamp_than_the_first`
passes against the pre-existing code and continues to pass after the `recv_window_ms` bump — it
pins the property the brief asked to prove, per its own "wiremock test proving ..." wording.

After every one of the above restores, the full crate suite was re-run green (`cargo test -p
live_trade_ops --lib`: 190 passed / 0 failed each time; `cargo test -p exchange_adapter --lib`
and `-p exchange_adapter_binance` also rerun clean after their respective restores).

Final gate, run twice for confidence (once mid-way, once after all restores above):
```
docker compose run --build --rm test cargo test --workspace --no-fail-fast
```
Both runs: every reported `test result:` block read `... ok`, zero failures, exit code 0 (48
test-result blocks across the workspace). The `market_data` shutdown flake (TECH_DEBT §5) did
not reproduce in either run.

## Self-review / concerns

- **The interest-attribution gap (L1) is real, not just disclosed for form.** On an account
  that isn't exclusively this test's, cleanup can leave a small amount of this run's own accrued
  interest unpaid if a foreign loan on the same asset makes the two inseparable. This is
  strictly safer than the old behaviour (spending money on someone else's principal), but it
  means a loan this run created might not be *fully* closed out by cleanup alone on such an
  account — another reason D4's "dedicated sub-account" isn't optional in practice, only in the
  code's ability to enforce it.
- **`margin_cleanup`'s buyback fill is not settlement-checked.** The body's own fills go through
  `check_settlement` (asserts the observed balance delta matches `Settlement::net_deltas`
  exactly); cleanup's buyback deliberately does not, since a failed assertion there would turn a
  successful cleanup action into a reported cleanup failure over a rounding/timing difference
  that isn't actually a bug. It is still fully reported (printed + `record_fill` + JSONL), just
  not assertion-gated. Flagging this as a design choice worth a second look, not silently.
- **`owed_by_run`/`record_borrow`/`record_repay` are crate-private free functions, not methods
  on a type with invariants enforced by construction** (e.g. nothing stops a future call site
  from calling `record_repay` for an asset that was never borrowed — it's a harmless no-op today
  since the entry defaults to zero and clamps there, but it's worth noting this ledger trusts
  its callers rather than making misuse impossible).
- I did not add a `cleanup-cancel` JSONL-visible line distinction beyond the generic step
  mechanism now in place; a cancelled order's id is folded into one aggregate step message
  rather than one line per cancelled order. Chose this to keep cleanup's own report additions
  proportionate to what actually happened (usually 0 or 1 stray orders) rather than one line per
  order on principle.
- Did not touch `futures_scenario.rs` / futures cleanup at all — L1 is specific to margin loans;
  futures cleanup restores leverage/margin type, which the live run's findings didn't touch.

## Review round 1/5 — fixes

Coordinator's review: PASS on all five findings, no Critical. Two Important items, both fixed.

**1. The foreign-debt message was inaccurate in exactly the case the L1 write-up disclosed**
(`margin_scenario.rs`). `leftover_foreign` (now renamed `leftover`) is `live_debt - repay_amount`;
`live_debt = borrowed + interest`, but `LoanLedger` only ever tracks *principal* (what a
`borrow()` call actually moved). So even on a perfectly clean, exclusively-owned account with
zero foreign debt, `leftover` is routinely nonzero — it's this run's own accrued interest, which
Binance starts charging from the first hour regardless of whose loan it is, and which the ledger
never counted. The old message ("pre-existing debt left untouched") labelled that residue a
stranger's loan unconditionally, which is exactly backwards from the limitation the original
report called out. Fixed by:
- Reserving the definite wording ("was not created by this run") for the one case that actually
  is unambiguous: `owed_by_run() == 0`, i.e. the ledger has no record of this run ever
  successfully borrowing this asset at all.
- Rewording every `leftover > 0` message (the per-asset repay line, the aggregate summary, and
  the `margin_cleanup`/module-level doc comments) to say the residue "may be this run's own
  accrued interest, a pre-existing loan, or both (Binance's interest is pooled per asset, not
  separable by loan)" — honest about what the code can and cannot tell apart, rather than
  guessing.
- Renamed the internal `foreign_notes` vector to `unresolved_notes` to match (it now legitimately
  holds two different kinds of note, not just foreign-debt ones).

**Test added:** `self_test_3c_a_leftover_purely_from_this_runs_own_accrued_interest_is_not_mislabelled_foreign`
— same panic-before-6b shape as 3b, but at cleanup time `margin_balances` shows `borrowed = 0.4`
(matching the ledger's own recorded principal *exactly* — no foreign principal at all) and
`interest = 0.05` (nonzero, uncaptured by the ledger). Asserts cleanup still repays exactly 0.4
(the ledger-bounded amount, not the full 0.45), and that the report neither claims the 0.05
residue "was not created by this run" nor omits it — it must name the 0.05 and acknowledge it
may be this run's own accrued interest. Verified red against the pre-fix wording (reverted both
message sites via a file-backup round-trip, confirmed the assertion failed with the old
"pre-existing debt" phrasing present, restored) before confirming green against the fix.

**2. The module doc still described the design L1 replaced** (`margin_scenario.rs:6-16`, the
"Re-deriving state instead of threading flags" block). It said cleanup decides what to undo by
re-reading `margin_balances()` — the exact mechanism L1 removed — while `margin_cleanup`'s own
doc comment a few hundred lines below already said the opposite. Rewritten to describe both
designs accurately and why they differ: step 6b (in-body, never reached after a panic) still
legitimately re-derives from live balances, since at that point in a normal run nothing but this
run's own trading could have touched the account (step 0 already proved `borrowed == 0`);
`margin_cleanup` (the last line of defense, reached even when step 0 never got the chance to
check anything) consults `LoanLedger` instead, never live balances, to decide *whether* it owes
anything.

**Gate:** `docker compose run --build --rm test cargo test --workspace --no-fail-fast` — exit 0,
48/48 test-result blocks green, run after these fixes (in addition to the two runs already
recorded above). `live_trade_ops --lib` alone: 191 passed / 0 failed (190 + the new
`self_test_3c`).

**Follow-up noted, not fixed here (reviewer's own observation, pre-existing, out of this task's
scope):** `harness/cleanup.rs:86`'s `ctx.run_cleanup()` call is not itself inside
`catch_unwind` — only the scenario body is (see `with_cleanup`'s own structure: the body is
wrapped in `AssertUnwindSafe(body).catch_unwind()`, but `ctx.run_cleanup().await` right after it
is a plain, unwrapped call). A panic *inside* cleanup itself — as opposed to cleanup returning
`Err` — would therefore crash the whole test process instead of degrading to a reported `LIVE
CLEANUP FAILED`. This task's L4 fix (treating an empty `LIVE_RUN_ID` as absent, plus
`ids::validate`'s independent empty-segment check) makes the one panic path inside
`margin_cleanup` that existed before this task (`client_id`'s malformed-id panic, on a malformed
run id reaching cleanup) unreachable in practice, but the general gap in `with_cleanup` itself —
any *other* future panic inside a cleanup routine — remains. Worth a dedicated follow-up task to
wrap `ctx.run_cleanup()` in its own `catch_unwind`, symmetric with the body's.

## Report path

This file: `.superpowers/sdd/2026-09-22-live-trade-ops-plan/task-7.4a-report.md`.
