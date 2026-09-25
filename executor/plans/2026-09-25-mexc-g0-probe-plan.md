# MEXC trading connector 1/5 — G0 capability probe (`live_trade_ops`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Index: [2026-09-25-mexc-connector-index-plan.md](2026-09-25-mexc-connector-index-plan.md).

**Goal:** Before any refactor, confirm or refute every MEXC fact the spec rests on (F1–F8, D2's futures permission, the open field spellings) against live responses, and commit the responses as fixtures.

**Spec:** §2 (F-table), §10.1 (the probe's eight steps), §15 "Still open". R2 is why this runs first.

**Scope:** a new `mexc_probe` scenario in `crates/live_trade_ops`, built on **raw signed HTTP**: the existing `exchange_adapter_mexc` `signing.rs` / `http.rs`, reached through whatever `live_trade_ops` already uses to build a MEXC client. It does **not** use the adapter's order mapping, and it does not use or wait for `OrderId(String)`. No production crate changes except the new fixture directory.

**Depends on:** nothing in this set. Operator: MEXC spot key and futures key (IP-bound, trade permission, **no withdraw**), KYC done.

**Branch:** `mexc-g0-probe`, cut from `layer-implementation` (it does not need the position-management precondition).

---

## Readiness review

Verified against `layer-implementation` @ 165afdb.

| Item | State | Note |
|---|---|---|
| Live runner, double gate (`#[ignore]` + `LIVE_TRADE_OPS=1`), run guard, banner | 🟢 exists | `live_trade_ops/tests/live_trade_ops.rs` |
| `known_host` banner for MEXC futures | 🟡 says `contract.mexc.com` | must say `api.mexc.com` for REST (line ~175) |
| MEXC signing (spot query HMAC, futures `accessKey+timestamp+params`) | 🟢 exists | `exchange_adapter_mexc/src/signing.rs`, `http.rs` |
| Futures `Recv-Window` header | 🔴 sent in ms (5000) | docs: seconds, max 60. The probe sends `10` explicitly; the adapter fix is in 3/5 |
| Spot scenario / probe scenario | 🔴 none | only `run_margin_scenario`, `run_futures_scenario` exist |
| Env templates | 🟡 | `configs/live-trade-ops/mexc.futures.mainnet.env.example` exists; no spot template |
| `UNMAPPED` report line | 🟢 | prints `UNMAPPED Mexc <code>: <msg>` (`harness/report.rs:179`) |

---

## Global constraints

- **At most one order reaches the exchange**, and it is designed to be refused (`vol=0`). If any step returns an order id, the probe cancels it immediately and fails.
- **`order/test` only** on spot. No real spot order.
- **Futures REST goes to `https://api.mexc.com`**; futures ws to `wss://contract.mexc.com/edge`.
- **Every response body is saved**, success or refusal, before it is parsed. A parse failure is a finding, not a crash.
- Secrets are redacted from saved fixtures (`ApiKey`, `Signature`, `listenKey`, `signature` query param).
- Commit only after explicit user confirmation.

---

## Docker Entry Points

```bash
# Offline gate (fake transport; no network)
docker compose run --build --rm test cargo test -p live_trade_ops

# M0: the live probe (operator-armed)
docker compose run --build --rm --env-file configs/live-trade-ops/mexc.spot.mainnet.env test \
  cargo test -p live_trade_ops --test live_trade_ops live_mexc_probe -- --ignored --nocapture --test-threads=1
```

The probe reads both key pairs (`API_KEY`/`API_SECRET` and `FUTURES_API_KEY`/`FUTURES_API_SECRET`), so the spot env file carries both.

Verified: [ ] `docker compose run --build --rm test` green on `mexc-g0-probe` at its cut point.

---

## Layer 1: the probe scenario

### Task 1.1: Probe types and entry

**Files:** create `crates/live_trade_ops/src/mexc_probe.rs`; register in `lib.rs`; add `live_mexc_probe` (`#[ignore]`, `LIVE_TRADE_OPS=1`) to `tests/live_trade_ops.rs`; add `configs/live-trade-ops/mexc.spot.mainnet.env.example`.

**Interface:**
```rust
pub enum FactId { F1, F2, F3, F4, F5, F6, F7, F8, D2, ClientIdLimit, FieldSpelling(&'static str) }
pub enum Verdict { Confirmed, Refuted(String), Inconclusive(String) }
pub struct ProbeStep { pub name: &'static str, pub fact: FactId, pub verdict: Verdict,
                       pub fixture: Option<PathBuf> }
pub struct ProbeReport { pub run_id: String, pub steps: Vec<ProbeStep>,
                         pub spot_offset_ms: i64, pub futures_offset_ms: i64 }

/// Minimal transport the probe needs; the real one wraps exchange_adapter_mexc's http/signing.
#[async_trait]
pub trait ProbeTransport: Send + Sync {
    async fn spot_signed(&self, method: Method, path: &str, params: &[(&str, String)]) -> RawResponse;
    async fn spot_public(&self, path: &str, params: &[(&str, String)]) -> RawResponse;
    async fn futures_signed(&self, method: Method, path: &str, body_or_query: ProbeParams) -> RawResponse;
    async fn futures_public(&self, path: &str) -> RawResponse;
    async fn spot_user_stream(&self, listen_key: &str, channels: &[&str], secs: u64) -> Vec<String>;
    async fn futures_ws_login(&self, subscribe: bool) -> Vec<String>;
}
pub struct RawResponse { pub http_status: u16, pub body: String }

pub async fn run_mexc_probe(t: &dyn ProbeTransport, pair: &Pair, fixtures_dir: &Path,
                            run_id: &str) -> ProbeReport;
```

**Integration test → fixtures consumer (RED in Docker):** `probe_writes_fixtures_the_adapter_tests_can_load`: run `run_mexc_probe` against a `FakeProbeTransport` that returns the docs' example bodies. Assert that every fixture file it wrote parses with the fixture loader `exchange_adapter_mexc`'s wiremock tests use (`tests/fixtures/…`). This is the probe → adapter-tests boundary.

**Unit tests (RED first):**
- Happy path: the docs' bodies give `Confirmed` for F1–F8 and D2.
- F1 refuted: `order/test` with `type=STOP_MARKET_ORDER` returns 200 → `Refuted`, and the report flags "D1 re-open".
- F4 refuted: numeric `orderId` → `Refuted`, and the report flags "D3 re-open".
- F8: `openOrders` without `symbol` returns an error → `Refuted` (restores the per-pair design).
- D2: `vol=0` refusal with code 704 / 200005 / 200006 / 300000 / 300001 → `Refuted("permission")`; a validation code (e.g. 2011/2015) → `Confirmed`.
- **`vol=0` returns an order id** → the probe issues exactly one `order/cancel` for it and the step is `Refuted("order accepted")`; the run fails.
- Client-id limit: 32 accepted and 33 refused → `Confirmed(32)`; both accepted → `Inconclusive("> 33")`.
- Field spellings: `cumulativeQuoteQty` vs `cummulativeQuoteQty`, `isTaker` vs `taker`, `contract/detail` vs `contract/detail/country`: whichever is present is recorded.
- Redaction: no saved fixture contains the secret, the api key, or a listen key.
- Unparseable body → step `Inconclusive`, body still saved, run continues.

**Constraints:** the probe's step order is spec §10.1's. The `vol=0` step runs last among REST steps, so a surprise acceptance cannot contaminate earlier captures.

### Task 1.2: Real transport

**Files:** `crates/live_trade_ops/src/mexc_probe.rs` (real `ProbeTransport` impl) plus any `pub(crate)` → `pub` needed in `exchange_adapter_mexc::{http, signing}`. Keep that exposure minimal and `#[doc(hidden)]`.

**Unit tests (RED first), wiremock:**
- Spot signed GET puts `timestamp`, `recvWindow`, `signature` last in the query, with the `X-MEXC-APIKEY` header.
- Futures POST signs the raw JSON body; `Recv-Window: 10` (seconds).
- Futures GET signs sorted, `&`-joined params.
- Clock offset from `/api/v3/time` and `/api/v1/contract/ping` is applied to `timestamp` / `Request-Time`.

**Constraints:** `live_trade_ops/tests/no_adapter_imports.rs` must still pass. If exposing `http`/`signing` would break that rule, re-implement signing locally in the probe (≈30 lines) instead of loosening the rule.

### Task 1.3: Banner and env template

- [ ] `known_host(Mexc, Futures, false)` → `api.mexc.com`. Test: the banner for MEXC futures names `api.mexc.com`.
- [ ] `mexc.spot.mainnet.env.example`: `EXCHANGE=mexc`, `MARKET_KIND=spot`, `LIVE_PAIR`, `LIVE_MAX_NOTIONAL`, both key pairs, `FUTURES_REST_BASE_URL=https://api.mexc.com`, `FUTURES_WS_BASE_URL=wss://contract.mexc.com/edge`.
- [ ] `mexc.futures.mainnet.env.example`: REST base URL updated the same way.

---

## Layer 2: run M0 and record

### Task 1.4: Run and write back (human-gated)

- [ ] Ask the operator for go. Run the M0 command.
- [ ] Commit fixtures to `crates/exchange_adapter_mexc/tests/fixtures/captured/` (names: `<surface>_<endpoint>_<case>.json`).
- [ ] Write `external/executor/runs/<date>-mexc-g0.md`: one line per step, verdict, fixture path, offsets, every `UNMAPPED` line.
- [ ] Spec §2: add a **Verdict (G0)** column to the F-table and fill it. Any `Refuted` re-opens the named decision in spec §4 **before** plan 2/5 starts: stop and ask the user.
- [ ] Spec §15 "Still open": strike every item the capture settled.

**Exit criterion:** F4 verdict known (plan 2/5 is gated on it), D2 verdict known (plan 3/5 is gated on it).
