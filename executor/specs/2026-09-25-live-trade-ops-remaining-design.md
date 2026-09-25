# Live Trade-Ops — Remaining Work — Design Spec (draft)

Date: 2026-09-25
Status: **draft** — successor to [2026-09-22-live-trade-ops-l0-test-design.md](2026-09-22-live-trade-ops-l0-test-design.md), which is implemented and merged
Target project: `trade_executor` (Rust, worktree `layer-implementation`)
Scope: what the live trade-ops work did **not** finish. Nothing here is started.

## 1. Where the predecessor got to

Implemented over 7 layers on branch `live-trade-ops` (35 commits, merged 2026-09-25): common connector types and the `EXCHANGE_NETWORK` switch; Binance host table, error-code table, fills, `MarginOps`, `FuturesOps`; MEXC plumbing; the test-only `live_trade_ops` crate (registry, `settle`, `risk`, order journal on Postgres via migration 0008, scripted fake, harness, both scenarios, 190+ offline self-tests, runner, env templates).

Two live runs happened, both on the operator's **main** Binance account (not the dedicated sub-account the predecessor assumed):

| Run | Result |
|---|---|
| 2026-09-24, margin mainnet | Failed at the exchange (`-1021`, timestamp outside recvWindow). Cleanup then bought 0.42 LINK (~5.55 USDT) and repaid 0.085 LINK + 0.0000233 USDT of debt **that pre-dated the run**. Five defects found (L1–L5), all fixed and reviewed. |
| 2026-09-24, margin mainnet, post-fix | Clean abort: `step 0: Skipped("precondition not met: USDT free 5.22587092 is below 2x LIVE_MAX_NOTIONAL 15")`, nothing sent, exit 0. Proved the `-1021` fix, the `EXCHANGE_NETWORK` fix and the precondition gate against the real exchange. |

**Clock follow-up (2026-09-25):** the first `-1021` fix did not change how timestamps are made: Binance still signed with the raw local clock. Since MEXC connector L0-a (`mexc-trading-connector` branch) every Binance signed request is timestamped from a `ServerClock` (offset learned from `/api/v3/time` or `/fapi/v1/time`, refreshed every 10 min and right after a `-1021`). A skew beyond half the recvWindow raises `AlertKind::ClockSkew` once per excursion.

**Nothing beyond step 0 has ever run against a live exchange.**

## 2. The remaining live runs

Unchanged from the predecessor's §6 and §9; listed here because they are the whole point and none are done.

| # | Run | Needs | Proves |
|---|---|---|---|
| R1 | Binance futures, **testnet** | testnet keys, funded faucet wallet | every step end-to-end at zero cost; captures real responses to replace the `// from docs` fixtures; writes the first liquidation golden rows |
| R2 | Binance futures, mainnet | sub-account, futures enabled, ≥ 2 × cap in the futures wallet | mainnet brackets and liquidation numbers; `LiqCalc` accepted for production only once a mainnet golden row exists |
| R3 | Binance margin, mainnet | **≥ 30 USDT free in cross margin** (2 × `LIVE_MAX_NOTIONAL`; 5.23 at the time of writing) | steps 1–8, sell funding, borrow/repay postconditions, the cleanup ledger under a real failure |
| R4 | MEXC futures, mainnet | MEXC keys | capability skips reported rather than silently passed; cleanup leaves nothing behind |

R1 first: it is the only run that costs nothing, and every one of L1–L5 would have surfaced there.

Per-run obligations (predecessor §9, still open): replace each `// from docs — replace with capture` marker with a captured response; record F4's observed leverage behaviour and turn it into assertions; settle the `bracket_for` floor/cap boundary question; append golden rows; record the outcome of the borrow-repay endpoint check.

## 3. Defects and limitations carried forward

### 3.1 Cleanup cannot separate its own interest from a stranger's

`margin_cleanup` repays `min(ledger, live_debt)` and refuses to touch debt the run did not create (the L1 fix). Binance reports `interest` pooled per asset, not per loan, so on an account the run does not exclusively own, some of the run's **own** accrued interest can be left unpaid. The report now says the residue "may be this run's own accrued interest, a pre-existing loan, or both". A dedicated sub-account removes the ambiguity entirely — which is what the predecessor's §D4 assumed and the operator's runs did not use.

**Decide:** either require a sub-account for margin runs (and enforce it: refuse to start if the account shows debt or open orders the run did not create), or accept the residue permanently and document the bound.

### 3.2 Cleanup runs outside `catch_unwind`

`harness/cleanup.rs:86` runs the cleanup closure outside the `catch_unwind` that guards the body, so a panic **inside cleanup** aborts the process instead of degrading to `LIVE CLEANUP FAILED` with the leftovers named. The L4 fix makes the one known trigger (a malformed client order id) unreachable, but the shape is wrong: the code whose job is to run after a failure is the code least protected against one.

### 3.3 Known gaps in the offline safety net

- `CallMatcher::{GetOrder, GetOrderFills, CancelOrder}` do not match on `OrderId`, so the fake cannot catch a harness bug that queries the wrong order. Harmless while no scenario path has two orders open at once; a precondition for any scenario that does.
- `FEE_RATE_EPSILON` is a fixed `0.0001` rather than derived from the fee asset's precision (predecessor §5.2 asks for "one unit of the fee asset's precision").
- The settlement check inspects only assets named in `net_deltas`: an unexpected move in an unrelated asset is not caught.
- Cleanup's own buyback fill is reported but not settlement-checked (deliberate: a failed assertion there would turn a successful cleanup into a reported failure).
- `MarketKind::Spot` shares `Margin`'s `settle` arm and is never exercised by a test.

### 3.4 Infrastructure foot-guns found the hard way

- `docker compose run` on this host has **neither `--env-file` nor `--network`**. Use `set -a; . <file>; set +a` plus `-e NAME` pass-through, and `docker run --network none <image>` for the no-network proof.
- `docker compose run --rm executor --migrate-only` **without `--build`** applies a stale image's migrations and writes a stale checksum into the volume, which then blocks every later run with "migration 8 was previously applied but has been modified".
- The `test` compose service has no source bind mount, so a `Cargo.lock` fix made by cargo inside it never reaches the host. A green test gate does **not** imply `docker compose build executor` succeeds; check both after adding a dependency.

## 4. Follow-ups the predecessor deliberately deferred

- **Orchestrator adoption** (predecessor §2, "Not covered"): switch the orchestrator onto `AdapterConfig::from_env`, `exchange_registry` and `JournaledAccount`, so production orders are persisted. **Blocked on [TECH_DEBT.md](../TECH_DEBT.md) §9**: `KindAccount::resolve()`'s `.expect()` runs on every account call and is dead only because the orchestrator hardcodes mainnet and always supplies URL overrides. The moment it reads `EXCHANGE_NETWORK`, a misconfigured `MARKET_KIND` turns a boot-time typed exit into a panic mid-flight. Fix that first.
- **Borrow/repay and leverage persistence**: the journal covers orders only. Binance's `tranId` is currently discarded because `MarginOps` returns `Result<(), _>`.
- **MEXC's error table**: `classify` carries only the one evidenced row plus auth. Filling it is MEXC's own spec, done the same way — captured responses, then rows, then tests.
- **MEXC ops traits and fills**: `get_order_fills`, `MarginOps`, `FuturesOps` remain on their defaults.
- **`order_event.order_id` is `bigint`** and cannot hold a MEXC order id ([TECH_DEBT.md](../TECH_DEBT.md) §7).
- **The order journal's shape** ([TECH_DEBT.md](../TECH_DEBT.md) §8, reviewed 2026-09-23, "build as specified"): a state row plus append-only fills, with no action history and cancels not written before sending. Revisit if a live run makes a cancel or a crash hard to reconstruct.

## 5. Acceptance criteria for this spec's successor

- [ ] R1 green; fixtures replaced by captures; F4 observations encoded; golden rows written.
- [ ] R2 green; mainnet golden rows; leverage and margin type verified restored afterwards.
- [ ] R3 green; the report shows the 4a borrow and the 6b buy-back and repay; `borrowed == 0` afterwards, verified independently of the test.
- [ ] R4 runs end to end with skips reported and nothing left behind.
- [ ] §3.1 decided (sub-account required, or residue accepted and bounded in writing).
- [ ] §3.2 fixed: a panic inside cleanup degrades to a reported failure naming what is left.
- [ ] Predecessor §9's remaining boxes ticked, including the L0 Stage 1 checkboxes in [layers/L0-exchange-adapter.md](layers/L0-exchange-adapter.md).
