# Step 2 — L0 exchange_adapter (plan)

Part of the [layer implementation sequence](2026-09-05-layer-implementation-sequence.md).
Spec: [L0-exchange-adapter](../specs/layers/L0-exchange-adapter.md).

## What to implement

- One common, exchange-agnostic adapter trait covering order
  placement, market-data subscription, and account/balance query —
  split into three independent sub-models (spot, margin, futures)
  rather than one flat interface branching on market kind, since
  fees/margin rules/liquidation behavior/available data differ
  enough per kind to deserve their own model.
- Two concrete adapter crates, `_binance` and `_mexc`, each
  implementing all three sub-models, including position support
  (open/close/modify, margin/liquidation data) — this is the full
  scope for both, not a narrowed first pass. Order of coding within
  that scope (which exchange/kind first) is free.
- Per-adapter construction/config (own config type, sourced from
  env at process start, credentials never logged or sent over the
  queue).
- Internal transport handling (websocket by default, REST fallback
  where an exchange lacks a ws for a given data type) — invisible
  to callers, who only ever see the same stream/result interface.
- The shared wire types that cross into L1 (book snapshot/update,
  trade, candle, account event) — L1 consumes these directly rather
  than inventing its own.
- Error surfacing: retry-with-backoff internally on disconnect/API
  error, but staleness always surfaces up, never swallowed.

## Acceptance criteria (high level)

Staged — each stage gated on the next layer existing; re-verify
against what that layer actually builds, not the interface assumed
here.

**Status:** all three crates implemented and committed on branch
`layer-implementation` (`crates/exchange_adapter`,
`exchange_adapter_binance`, `exchange_adapter_mexc`; commits
`d318ac6`/`6ac6b07`/`6581762`). `cargo test --workspace` (83 tests) and
`cargo clippy --workspace --all-targets` both clean; Docker-verified
(`docker build . && docker run --network host ...`).

Known gaps, none of which block moving on to L1 but all real:
- **MEXC still has no websocket for book/trade.** Binance's `subscribe_market_data`
  now emits real `BookSnapshot`/`BookUpdate` via `@depth` diff stream and `Trade`
  via `@trade` stream (see `external/executor/specs/2026-09-05-binance-market-data-websocket-design.md`),
  but `subscribe_account_updates` still polls `get_account_state` and diffs snapshots
  into synthetic `AccountEvent`s (REST-fallback path, out of scope). MEXC is still
  REST-kline-polling only (emits `Candle` only — never `BookSnapshot`/`BookUpdate`/`Trade`),
  tracked as a separate follow-up once Binance validation is complete.
- **Never run against real exchange credentials/testnet on either
  side.** All tests are `wiremock`-backed (loopback only). Each crate
  has one `#[ignore]`d gated integration test
  (`BINANCE_TESTNET_API_KEY`/`SECRET`, `MEXC_API_KEY`/`SECRET`) that has
  never executed — Stage 1's live-exchange checkbox stays open
  regardless.
- **MEXC margin trading is real-world dead**: MEXC closed its margin
  API to new orders 2023-04-14 UTC and no longer documents
  `/api/v3/margin/*` at all. `exchange_adapter_mexc`'s margin
  `place_order`/`cancel_order`/`get_order` return
  `AdapterError::NotSupported`; only read-only methods best-effort
  reuse spot endpoints (unverified). This is a spec-vs-reality gap, not
  an implementation shortcut — `specs/layers/L0-exchange-adapter.md`'s
  "both exchanges implement all three kinds" should be revisited: MEXC
  margin may need to become a documented exception (`margin()` still
  returns `Some`, but order placement genuinely can't work), not
  something a future pass can just "finish".
- `OrderId`/`cancel_order`/`get_order` carry no `Pair`, but both
  exchanges' REST APIs require the symbol — both adapters work around
  this with a process-local `OrderId → symbol` cache populated by
  `place_order`/`get_account_state`, lost on restart. Worth reopening
  as a possible trait-signature gap once L3 (execution) is built and
  actually needs cross-restart order lookups.
- MEXC futures: fixed leverage per adapter instance (no per-order field
  on `OrderRequest`), `qty` assumed 1:1 with contract `vol`,
  `get_account_state`'s `open_orders` always empty (MEXC's
  contract-open-orders endpoint is per-symbol, this method is
  account-wide).

**Stage 1 — standalone, no other layer needed**
- [ ] Both exchanges, all three kinds, live: streaming market data,
      placing/cancelling/querying orders, opening/closing/modifying
      positions, querying account state and fees/market info, and
      extended data (funding/mark/open interest) on margin/futures.
      All proven against exchange testnet/sandbox, not mocks.

**Stage 2 — glue to L1 (market_data)**
- [ ] Every event type L0 emits is consumed end-to-end by L1 with no
      data loss, producing a correct live book/trade/candle view.

**Stage 3 — glue to L3 (execution)**
- [ ] Execution can open/close a position purely through L0's calls,
      and receives real (not stubbed) fill confirmation via the
      account-event path.

**Stage 4 — glue to L5 (state_store)**
- [ ] State-store reconciliation against L0's real account/order data
      recovers correctly from a simulated exchange/local mismatch.
