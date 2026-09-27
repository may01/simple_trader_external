# Trade Executor — Layer Implementation Sequence (high level)

**Status (2026-09-05): all ten layers (L0–L9) implemented, tested, and
Docker-verified** on branch `layer-implementation` in the
`trade_executor` repo — 223 tests, clippy clean workspace-wide. See
each layer's own numbered plan doc (`01-`…`10-`) for its specific
status note, real gaps, and commit hashes. The two open threads that
cut across multiple layers: (1) nothing has been verified against a
real exchange testnet/sandbox anywhere (L0's adapters are mock-server-
tested only — no credentials available in this environment), so every
"proven against live exchange" acceptance box in every layer's doc
stays unchecked regardless of how much else landed; (2) L9's `main.rs`
can construct a real Binance/MEXC-backed live-trading deployment, but
there is no zero-credential "paper trading against live public data"
path yet — `execution::PaperMarketAccount` has no market-data
subscription of its own, so it can't stand alone as the orchestrator's
market account; a delegating wrapper (real adapter for data, paper
account for orders) would close this, not built.

Order to implement the layer specs in `specs/layers/`. Sequencing only —
no interfaces, no test plans, no code. Those live in each layer's own
spec and in the per-layer implementation plan when that layer starts.

Source of dependency facts: `specs/2026-09-04-architecture-design.md`
layer table + "Build order" decision.

## Sequence

1. **L7 observability** — leaf, zero deps, but every other layer emits
   to it. Build a minimal skeleton first so L0+ don't bolt logging on
   after the fact. Full alerting/dead-man's-switch can mature in
   parallel with later stages.
2. **L0 exchange_adapter** (trait + `_binance`/`_mexc`) — foundation,
   no deps. Confirmed build-order decision: data layer first.
3. **L1 market_data** — depends on L0. Live book/candles + local
   persistence.
4. **L2 local_analysis** — depends on L1. Pure-fn signal/risk logic.
5. **L3 execution** — depends on L0 (write path), L1 (account events),
   L2. Position lifecycle, risk/SL/TP, dual stop-loss, paper-trading.
6. **L4 mq_gateway** and **L5 state_store** — both depend on L3 only,
   build in parallel. L4 = main/ boundary (dedup, out state). L5 =
   crash recovery / reconcile.
7. **L6 replay_harness** — depends on L1 + L2 only, so it's not
   strictly gated behind L3/L4/L5. Can be pulled earlier (right after
   step 4) if replay validation of local_analysis is needed before
   execution work starts. Required gate before any L2 change ships to
   live trading — don't skip it regardless of when it's built.
8. **L8 interfaces** (`cli`, `visualizer_backend`) — depends on L3, L4,
   L1, L5. Needs the full data+execution+reporting path present.
9. **L9 orchestrator & deploy** — depends on all layers. Wires
   everything, boot sequence, runtime loop, multi-pair, Docker/env
   config. Last, by definition — it constructs the rest.

## Notes

- Numbers above are build order, not the L0–L9 spec numbering (which
  is dependency-tier, not sequence) — they mostly coincide except for
  L7 (pulled to the front) and L6 (flagged as movable).
- L4/L5 parallelism and L6's earlier option are the only slack in an
  otherwise linear chain — everything else is a hard dependency per
  the architecture doc's table.
- Each stage still owes its own Docker entry point, interface
  signatures, and RED integration test before implementation starts,
  per `layer-first-planning` — this document only fixes the order
  stages happen in.
