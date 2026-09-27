# Task 7.1 report — Runner and env templates

## Addendum — review round 1/2: single-threaded execution as a code guarantee

Review came back PASS with one Important finding: single-threaded execution
was documentation-only. An operator running `cargo test -p live_trade_ops
--test live_trade_ops -- --ignored` with no name filter — a plausible slip —
would get Rust's default multi-threaded test runner starting
`live_margin_trade_ops` and `live_futures_trade_ops` concurrently, on
separate OS threads, against the same sub-account/pair/`DATABASE_URL`, with
nothing but a comment to stop it.

**Fix.** Added `static LIVE_RUN_GUARD: std::sync::Mutex<()>` (module-level in
`tests/live_trade_ops.rs`) and `acquire_run_guard()`, which recovers from
poisoning (`unwrap_or_else(|poisoned| poisoned.into_inner())`) rather than
propagating it — one run panicking must not permanently wedge the guard for
a later run in the same process. `run(kind, golden_rows_path)` now acquires
this guard as its very first line, before even the `armed()` check, and
holds it (via an unused `_run_guard` binding) for the entire body — across
every `.await` the adapter build, DB connect and scenario run make. A plain
blocking `std::sync::Mutex`, not `tokio::sync::Mutex`, deliberately: it must
block the *OS thread* the second test's own dedicated `#[tokio::test]`
runtime is running on (each test gets its own runtime instance and, by
default, its own OS thread from the test harness), not merely yield within
one shared async runtime that the two tests don't actually share.

Two new tests prove it:
- `tests::live_run_guard_serializes_two_concurrent_holders_rather_than_interleaving`
  — two real OS threads (`std::thread::spawn`, not tokio tasks), thread A
  given a head start, holds the guard across a 150 ms sleep (standing in
  for a live run's many awaits) while logging `a-start`/`a-end`; thread B
  logs `b-start`/`b-end`. Asserts the log is exactly
  `["a-start","a-end","b-start","b-end"]` — if the guard failed to
  serialize them, `b-start` would land between `a-start` and `a-end`. Ran
  it 5x locally back to back with no flakiness (30 ms/150 ms margin).
- `tests::a_panic_while_holding_the_guard_does_not_poison_it_for_the_next_acquisition`
  — a thread panics while holding the guard; a subsequent
  `acquire_run_guard()` on another thread still succeeds rather than
  hanging or panicking on a `PoisonError`.

**Considered and rejected: a cross-process guard (e.g. a Postgres advisory
lock on `DATABASE_URL`).** The reviewer's finding was specifically about two
*threads in one process* (the concrete, plausible slip: one `cargo test`
invocation, no name filter). A `pg_try_advisory_lock`/`pg_advisory_unlock`
pair would additionally guard against two *separate* `docker compose run`
invocations racing against the same `DATABASE_URL`, but doing it correctly
requires pinning one dedicated Postgres connection for the whole run's
duration (advisory locks are session-scoped, and `PgPool` otherwise returns
connections to the pool between queries) — real added complexity and a
second code path to get right, for a scenario global constraints already
cover procedurally (every Layer 7 run is a separate human gate; a human
runs one at a time). Left as documented, in-code-guarantee scope: the
in-process mutex.

**`MARKET_KIND` (smaller finding).** It appeared in all four `.env.example`
files but `run()` never read it — an inert variable in a credentials file
invites someone to edit it and expect an effect. Fixed by reading it (if
present) and validating it against the hardcoded `kind` via
`registry::parse_market_kind`, panicking immediately (before the
adapter/DB are ever touched) on a mismatch — e.g. the futures.testnet file
accidentally passed to `live_margin_trade_ops`. Left the variable in the
templates now that it does something.

**Runbook note (smaller finding).** Added to `tests/live_trade_ops.rs`'s own
module doc comment: the plan's literal `docker compose run --rm --network
none …` does not work on this environment's Compose CLI (`docker compose run
--help` lists no `--network` flag); repeating the no-network proof means
using bare `docker run --network none <image> cargo test -p live_trade_ops`
against the already-built `test` image instead (exact commands already in
the "Evidence" section below).

**Re-ran the full gate after these changes:**
`docker compose run --build --rm test cargo test --workspace --no-fail-fast`
→ exit 0, zero failures. `live_trade_ops`: lib `184 passed`,
`tests/live_trade_ops.rs` `12 passed; 0 failed; 2 ignored` (10 banner/gate
tests + the 2 new guard tests; both live tests still correctly `ignored`),
`no_adapter_imports.rs` `1 passed`, `pg_journal.rs` `9 passed`. The known
`market_data` flake (`shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database`)
passed cleanly again.

---

## What was implemented

1. **`crates/live_trade_ops/tests/live_trade_ops.rs`** (new) — the runner.
   - `live_margin_trade_ops` and `live_futures_trade_ops`, both `#[tokio::test]` + `#[ignore]`.
   - Both call a shared `run(kind, golden_rows_path)` that:
     - returns immediately, printing why, unless `armed()` (`LIVE_TRADE_OPS` == exactly `"1"`) — spec §8's "opt-in twice";
     - builds the adapter via `live_trade_ops::registry::build_adapter_from_env(kind, metrics, alerts)`;
     - builds `PgOrderJournal` on `DATABASE_URL` (`PgPoolOptions::connect`);
     - prints the spec §5.1 banner (`EXCHANGE = … KIND = … NETWORK = … (<host>)`) before step 0;
     - runs `run_margin_scenario`/`run_futures_scenario`;
     - prints the report (steps, unmapped rejections, fill count, `passed()`), each line tagged `[exchange kind network]`;
     - `live_futures_trade_ops` additionally appends golden rows to `crates/live_trade_ops/tests/fixtures/futures_liq_golden.json` (the exact path `risk::risk_matches_live_golden_rows` already reads);
     - writes the JSONL fill report to `target/live-trade-ops/{run}.jsonl`;
     - `assert!(report.passed())`.
   - No adapter-crate import in this file at all — `registry::build_adapter_from_env` already hands back `Arc<dyn ExchangeAdapter>`, so `tests/no_adapter_imports.rs` (which only scans `src/`) needed no change and the file needed no listing there.
   - Pure, unit-tested helpers: `armed_with` (gating), `banner`/`known_host`/`network_label`/`exchange_label`/`kind_label` (the banner), `tag` (per-line network tag). 10 unit tests plus one integration-style test (`run_returns_immediately_without_touching_anything_when_not_armed`) that calls the real `run()` and proves it does nothing when unarmed, using the real (never-set-in-CI) `LIVE_TRADE_OPS`.

2. **The banner (spec §5.1).** `resolved_network()` (registry/adapter) reports which environment was dialed (`Testnet`/`Mainnet`/`Custom(url)`) but not the literal host string for `Testnet`/`Mainnet` — no accessor on `BuiltAdapter`/`ExchangeAdapterBinance`/`ExchangeAdapterMexc` exposes it. `known_host()` reproduces spec §4.3's own published host table purely for the banner's text (presentational only — the adapter has already independently resolved and is already dialing this exact host before the runner ever sees a `ResolvedNetwork`; a stale row here could make the banner's *text* wrong, never make the run dial the wrong host). `Custom` prints the real override URL verbatim, never a table lookup.

3. **The key/network mismatch case (spec §5.1).** Added `scenario_common::translate_auth_mismatch` + `network_word` (both `pub(crate)`, in the test-only `live_trade_ops` crate, not a production crate) and wired one call into each of `margin_scenario::run_margin_body` / `futures_scenario::run_futures_body`, right where step 0's result is first matched. It converts `Err(HarnessError::Adapter(AdapterError::Rejected(Rejection { reason: RejectReason::AuthFailed, .. })))` into `Err(HarnessError::Precondition("API key does not belong to {testnet|mainnet|custom}"))`, so the scenario's existing `Err(HarnessError::Precondition(msg)) => Skipped(...)` arm produces spec's exact wording without a duplicated match arm. Every other error passes through completely unchanged. Covered by 3 pure unit tests (`scenario_common::tests`) plus 2 full scripted-exchange integration tests (`tests::task_7_1_margin_auth_failed_...`, `tests::futures::task_7_1_futures_auth_failed_...`) proving the real scenario functions produce `Skipped("precondition not met: API key does not belong to mainnet")` and `report.passed() == true` (not a raw error, not a failure) when the very first signed call (`get_account_state`) is rejected this way.

4. **`RunReport::passed()`** (new, `harness/report.rs`) — the brief's own interface note (`assert!(report.passed())`) needed a method that didn't exist yet. `true` unless any recorded step is `StepOutcome::Failed`; `Skipped`/`Inconclusive` never fail a run on their own (D8, spec §5.3). 4 new unit tests.

5. **`configs/live-trade-ops/*.env.example`** (4 files) — one per run, listing every variable spec §5.1's table names (`LIVE_TRADE_OPS`, `EXCHANGE`, `EXCHANGE_NETWORK`, `API_KEY`/`API_SECRET` (+`FUTURES_API_KEY`/`FUTURES_API_SECRET` for MEXC), `REST_BASE_URL`/`WS_BASE_URL`, `LIVE_PAIR`, `DATABASE_URL`, `LIVE_REQUIRE_ALL`, `LIVE_MAX_NOTIONAL`, `LIVE_WAIT_SECS`, `LIVE_RUN_ID`), all placeholder values, no real keys (checked twice by hand and by `grep`, see below). `LIVE_REQUIRE_ALL=1` in the three Binance files; left commented-out/unset in the MEXC file per the task's explicit instruction (its ops traits are deliberately unimplemented).

6. **`.gitignore`** — added `configs/live-trade-ops/*.env`, scoped so it matches only the real files, never the committed `*.env.example` templates (verified with `git check-ignore -v`, see evidence).

7. **Deleted the two superseded tests** (only after the runner compiled and the full workspace gate was green):
   - `crates/exchange_adapter_binance/tests/testnet_integration.rs` — covered construction of `ExchangeAdapterBinance` against a hand-built `AdapterConfig` plus one `get_market_info` call against real Binance testnet; `#[ignore]`d, never run (no credentials/egress in its own build environment). That coverage now lives in `live_margin_trade_ops`/`live_futures_trade_ops`'s own step 0 (`build_adapter_from_env` + `get_account_state`/`get_market_info` against whichever real host `EXCHANGE_NETWORK` resolves to), which is strictly more — it also places, cancels and fills real orders, which the old test never attempted.
   - `crates/exchange_adapter_mexc/tests/live_credentials.rs` — same shape, MEXC spot mainnet, one `get_market_info` call. Same replacement: `live_futures_trade_ops` with `EXCHANGE=mexc` (Task 7.5) now exercises real MEXC calls end to end, with unimplemented capabilities reported `SKIPPED` per D8 rather than the old test's untested placeholder.

## Evidence

### `docker compose run --build --rm test cargo test --workspace --no-fail-fast`

Ran twice (once right before deleting the two superseded tests, once after, to prove nothing else broke): **exit 0 both times, zero failures across the whole workspace.** `market_data::write_path::shutdown_reports_a_timeout_instead_of_hanging_on_a_failing_database` (TECH_DEBT §5's known flake) passed cleanly both times — no isolation re-run was needed.

Confirmed post-delete: `exchange_adapter_binance` — `117 passed; 0 failed; 0 ignored` (was `0 passed; 0 failed; 1 ignored` before deleting `testnet_integration.rs`). `exchange_adapter_mexc` — `101 passed; 0 failed; 0 ignored` (was `1 ignored` before deleting `live_credentials.rs`).

`live_trade_ops` itself: lib `184 passed`, `tests/live_trade_ops.rs` `10 passed; 0 failed; 2 ignored` (the two live tests, correctly never run), `tests/no_adapter_imports.rs` `1 passed`, `tests/pg_journal.rs` `9 passed` (real Postgres via the compose network).

### `cargo tree -i live_trade_ops` (spec §5.0/acceptance criteria)

```
docker compose run --rm test cargo tree -i live_trade_ops
```
→ prints only `live_trade_ops v0.1.0 (/app/crates/live_trade_ops)` itself — no workspace crate depends on it.

### The no-network proof

The installed `docker compose` CLI in this environment has **no `--network` flag on `run`** (`docker compose run --help` lists none), and the `test` Dockerfile stage does no `RUN cargo …` at build time at all — it is a bare `COPY . .` plus a `CMD`, so *every* `cargo test` invocation, networked or not, does its dependency-index refresh and full compile inside that one container run. There is no cache volume for `~/.cargo`/`target` in `docker-compose.yml`, so a literal `docker run --network none <image> cargo test …` fails immediately trying to resolve `index.crates.io` — before a single line of this crate's own code ever runs. That failure is about Cargo's own package manager, not about anything `live_trade_ops` does, and is a pre-existing property of this repo's build setup, not something this task touches.

To prove the thing the brief actually cares about — that `cargo test -p live_trade_ops` itself never dials a live exchange — I warmed a throwaway `CARGO_HOME`/`target` cache with one networked run, then reran the identical command with `--network none` against the same caches (bare `docker run`, not compose, since compose's `run` has no such flag here):

```bash
docker volume create test_cargo_registry
docker volume create test_cargo_git
docker volume create test_target_cache

# warm run (network enabled) — populates the caches
docker run --rm \
  -v test_cargo_registry:/usr/local/cargo/registry \
  -v test_cargo_git:/usr/local/cargo/git \
  -v test_target_cache:/app/target \
  layer-implementation-test cargo test -p live_trade_ops --no-fail-fast

# the proof — identical command, --network none, same caches
docker run --rm --network none \
  -v test_cargo_registry:/usr/local/cargo/registry \
  -v test_cargo_git:/usr/local/cargo/git \
  -v test_target_cache:/app/target \
  layer-implementation-test cargo test -p live_trade_ops --no-fail-fast
```

Result (second command, `--network none`):
- lib: `184 passed; 0 failed`
- `tests/live_trade_ops.rs`: `10 passed; 0 failed; 2 ignored` — `live_margin_trade_ops` and `live_futures_trade_ops` both print `... ignored`
- `tests/no_adapter_imports.rs`: `1 passed`
- `tests/pg_journal.rs`: **9 failed**, every one with `TEST_DATABASE_URL must be set` / connection failure — because this bare `docker run` isn't on the compose network and can't reach the `postgres` service at all under `--network none`. This is expected and orthogonal to the proof: `pg_journal.rs` is a real-Postgres integration suite (task 5.3), not a live-exchange test, and it fails identically (same panic) even in the *networked* warm run once it's outside the compose project's own network — it needs `postgres` reachable, not "the internet". It never once attempts to reach `index.crates.io` or any exchange host.

I deleted the three temporary docker volumes afterward (`docker volume rm test_cargo_registry test_cargo_git test_target_cache`) — nothing about them is part of the tracked project.

**Conclusion:** everything this task added or touched — the lib, the runner file, the adapter-import guard — passes with zero network access once ordinary Rust dependency caching is in place; the only failures under `--network none` are the pre-existing Postgres-integration suite, which fails for the same reason (no route to `postgres`) whether or not internet egress is present, and is unrelated to whether a live exchange is ever dialed.

## Files changed

- `crates/live_trade_ops/tests/live_trade_ops.rs` (new) — the runner.
- `crates/live_trade_ops/src/scenario_common.rs` — `network_word`, `translate_auth_mismatch` + 3 unit tests.
- `crates/live_trade_ops/src/margin_scenario.rs` — one `translate_auth_mismatch` call in `run_margin_body`.
- `crates/live_trade_ops/src/futures_scenario.rs` — one `translate_auth_mismatch` call in `run_futures_body`.
- `crates/live_trade_ops/src/harness/report.rs` — `RunReport::passed()` + 4 unit tests.
- `crates/live_trade_ops/src/tests.rs` — 2 new self-tests (`task_7_1_margin_auth_failed_...`, `tests::futures::task_7_1_futures_auth_failed_...`).
- `configs/live-trade-ops/binance.margin.mainnet.env.example` (new)
- `configs/live-trade-ops/binance.futures.testnet.env.example` (new)
- `configs/live-trade-ops/binance.futures.mainnet.env.example` (new)
- `configs/live-trade-ops/mexc.futures.mainnet.env.example` (new)
- `.gitignore` — `configs/live-trade-ops/*.env`
- Deleted: `crates/exchange_adapter_binance/tests/testnet_integration.rs`, `crates/exchange_adapter_mexc/tests/live_credentials.rs`

## Self-review findings (and what I did about them)

- **Deviation from the brief's literal file list, disclosed:** the brief's own interface note ("print banner; run scenario; print report; `assert!(report.passed())`") and spec §5.1's mismatch requirement cannot be met from `tests/live_trade_ops.rs` alone — `RunReport` had no `passed()` method, and the `AuthFailed` translation has to happen where step 0's result is first inspected (inside the two scenario modules), not after the fact on an already-built `RunReport` (a post-hoc string match on the recorded step text would be far worse). I made the three small, targeted, unit-tested additions this required (`passed()`, `translate_auth_mismatch`, `network_word`) rather than working around the gap in the test file, per "if wiring the runner reveals that a scenario or the registry needs a change, say so." All three are additive: no existing behaviour, signature, or test changed meaning.
- **Found via a first failing run, then fixed:** my first draft of the margin auth-mismatch self-test only scripted the two `GetAccountState` calls (step 0's rejection + cleanup's own read) and the `MarginBalances` cleanup check — it missed that `margin_cleanup` also calls `get_market_info` (to learn the pair's base/quote assets) *before* its `MarginBalances` check. The scripted-exchange panicked with "expected next: MarginBalances, received: GetMarketInfo". Fixed by adding `.any_time(CallMatcher::GetMarketInfo, ...)`, matching the existing `step0_prefix()` convention elsewhere in the same file. Left this note in so a future reader of the test understands why it's there.
- **`known_host`'s host table is presentational duplication of spec §4.3, disclosed rather than hidden:** no adapter accessor exposes the literal dialed host for `Testnet`/`Mainnet` (only `resolved_network()`'s three-way enum). I judged reproducing spec's own already-published table for banner text only (never for any decision) to be the right scope for this task rather than adding a new accessor to the registry/adapter crates. Said so in the code's own doc comment and here.
- **"Every log line of the run carries the network" (spec §5.1) — only partially met, disclosed:** the runner's own summary lines (`print_report`) are tagged `[exchange kind network]`. The scenario modules' own inline `println!` calls (fill reports, the F4 leverage-observation line, sell-funding notes — all frozen, five-times-reviewed Task 6.3 code) do **not** individually carry this tag. Retrofitting every one of those call sites felt like real scope creep for a "runner + env templates" task and risked disturbing already-reviewed logic for a cosmetic requirement; I judged the banner (which does announce the network before anything else prints) plus the runner's own tagged summary to be the right line to hold in this task, and flagged the gap explicitly in the runner file's own doc comment.
- Checked `MARKET_KIND` isn't actually read by `registry::build_adapter_from_env` (kind is a parameter the two test functions supply directly) — included it in the env templates anyway since `docker-compose.yml`'s `test` service already whitelists it for pass-through and it does no harm, but it's not load-bearing.
- Double-checked every `.env.example` file by hand and with `grep -riE 'sk-|secret.*[a-z0-9]{20}|api.?key.?=.?[a-zA-Z0-9]{15}'` — every credential-shaped value is one of the four literal placeholder strings (`REPLACE_WITH_REAL_...`); no real key ever touched these files.

## Concerns for the reviewer

1. The `translate_auth_mismatch`/`network_word`/`passed()` additions touch three files (`scenario_common.rs`, `margin_scenario.rs`, `futures_scenario.rs`, `harness/report.rs`) that Task 6.2/6.3 had already closed out through five review rounds. They're additive and I ran the full pre-existing test suite before and after (both green, same counts plus my new tests) — but a reviewer should specifically re-check that `translate_auth_mismatch`'s placement (right after `step0`'s own result, before the existing `Precondition`/generic-`Err` match) can't ever mask a genuine non-auth failure; I believe the `if r.reason == RejectReason::AuthFailed` guard makes that impossible, but it's worth an independent look.
2. The banner's host table (`known_host` in the runner) is data, not logic — a typo there would only make a log line read wrong, never change which host is actually dialed (that's entirely the adapter's own, already-tested `resolved_network`/host-table resolution). Still worth a glance against spec §4.3's table.
3. Both live tests are wired through `registry::build_adapter_from_env`/`LiveConfig::from_env`/`PgOrderJournal` exactly as the brief specifies, but **have never been run against a real exchange** — that's Tasks 7.2–7.5, human-gated, out of this task's scope entirely. This task proves the runner compiles, gates correctly, and produces the right banner/mismatch text against a scripted fake; it does not and cannot prove the real Binance/MEXC calls behave as expected.

## Exact command per run (human operator, Tasks 7.2–7.5)

```bash
docker compose run --build --rm --env-file configs/live-trade-ops/binance.margin.mainnet.env test \
  cargo test -p live_trade_ops --test live_trade_ops live_margin -- --ignored --nocapture --test-threads=1

docker compose run --build --rm --env-file configs/live-trade-ops/binance.futures.testnet.env test \
  cargo test -p live_trade_ops --test live_trade_ops live_futures -- --ignored --nocapture --test-threads=1

docker compose run --build --rm --env-file configs/live-trade-ops/binance.futures.mainnet.env test \
  cargo test -p live_trade_ops --test live_trade_ops live_futures -- --ignored --nocapture --test-threads=1

docker compose run --build --rm --env-file configs/live-trade-ops/mexc.futures.mainnet.env test \
  cargo test -p live_trade_ops --test live_trade_ops live_futures -- --ignored --nocapture --test-threads=1
```

Each of these is a separate human gate (global constraints): stop, show the operator the env file with keys redacted and the printed banner, and wait for an explicit "go" before that specific run.
