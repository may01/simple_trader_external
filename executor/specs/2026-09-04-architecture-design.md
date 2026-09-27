# Trade Executor — Layered Architecture Design (index)

Expands `main_goal.md` into a concrete layered structure: Cargo
workspace, one crate per layer, dependency direction bottom-up.
Produced via brainstorming skill (architectural path). Approved
2026-09-04; split per-layer 2026-09-04.

Each layer has its own design doc under [layers/](layers/) — purpose,
responsibilities, depends-on, interface exposed upward, error
handling, testing. This index holds only what's shared across all of
them: the decisions from clarifying questions, the layer list with
one-line summaries, and the cross-layer data flow (how layers actually
talk to each other end-to-end — no single layer doc shows the full
picture on its own).

## Decisions carried in from questions

- **MQ transport**: abstracted behind a trait in `mq_gateway`; concrete
  transport is ZeroMQ, no broker, PUSH/PULL, executor binds — see
  [L4-mq-gateway-transport.md](layers/L4-mq-gateway-transport.md).
- **Build order**: data layer (`market_data` + `exchange_adapter`)
  first — everything else depends on live data existing.
- **Exchange scope** (superseded 2026-09-04, was "one exchange, one
  market kind first"): both `exchange_adapter_binance` and
  `exchange_adapter_mexc` implement spot, margin, and futures —
  including position support (open/close/modify via `MarketAccount`,
  margin/liquidation-proximity data via `get_extended_market_data`) —
  as L0's actual scope, not a narrowed first increment. Coding can
  still land in whatever order is convenient; the acceptance bar for
  "L0 done" (see L0's Acceptance Criteria, stage 1) is all of it.
- **Exchange adapter packaging**: `exchange_adapter` (trait) is one
  common crate. Every exchange gets its **own** crate
  (`exchange_adapter_binance`, `exchange_adapter_mexc`, future ones),
  each independently installable. An executor binary depends only on
  the adapter crates it actually needs — not one crate bundling every
  exchange. This is the pattern from day one, not something added
  later into a shared blob.

## Layers

Dependency direction is strictly bottom-up; a layer never depends on
anything above it. Full detail in each linked doc.

| Layer | Crate(s) | Depends on | One-line role |
|---|---|---|---|
| L0 | [exchange_adapter](layers/L0-exchange-adapter.md) + `_binance`/`_mexc`/... | — | trait: order placement, market-data subscription, account query; one crate per exchange |
| L1 | [market_data](layers/L1-market-data.md) | L0 | live order book + candles, local persistence for replay |
| L2 | [local_analysis](layers/L2-local-analysis.md) | L1 (+ decision context / open-position view as plain data, not a crate dep) | wall detection + combined_levels (main/↔local glue), volume signals, full signal build (open/close/SL prices + timing), pre-trade risk / best-price selection, ongoing stop-loss advisory — pure fns |
| L3 | [execution](layers/L3-execution.md) | L0(write path), L1(account-event push), L2, L4(in) | position lifecycle, risk/SL/TP/liquidation, dual stop-loss, paper-trading |
| L4 | [mq_gateway](layers/L4-mq-gateway.md) | L3(out) | main/ boundary: inbound decisions+force (dedup), outbound state |
| L5 | [state_store](layers/L5-state-store.md) | L0, L3 | crash recovery, boot-time reconcile vs exchange truth |
| L6 | [replay_harness](layers/L6-replay-harness.md) | L1(replay feed), L2 | required gate: local_analysis change must replay clean before live — replay mechanics live in L1, this crate just orchestrates the gate |
| L7 | [observability](layers/L7-observability.md) | none (leaf; all depend on it) | logs/metrics/alerts, own dead-man's-switch |
| L8 | [interfaces](layers/L8-interfaces.md) (`cli`, `visualizer_backend`) | L3, L4, L1, L5 | human-facing: status/logs/force-publish, historical+live viz |
| L9 | [orchestrator & deploy](layers/L9-deploy.md) — **is** a crate (the binary) | all | constructs + wires every layer, boot sequence, runtime loop, multi-pair, Docker/env config — the previously-missing "who runs this" answer |

## Cross-layer communication (data flow)

```
main/ (Python) ──MQ(decision+levels, id)──▶ mq_gateway ──▶ execution
                                                              │
exchange ws ──▶ exchange_adapter_X ──▶ market_data ──▶ local_analysis
                                          │                   │
                                          │(wall levels, signal ticks)
                                          ▼                   ▼
                                     replay_harness      execution (timing/SL/TP adjust)
                                                              │
                                                              ▼
                                                    exchange_adapter_X (place/cancel order)
                                                              │
                                                              ▼
                                                         state_store (persist)
                                                              │
                                                              ▼
                                                mq_gateway ──MQ(state: opened/closed/stopped/fill)──▶ main/
```

Key paths (each also detailed in the relevant layer doc's own
sections):

- **Decision path**: main/ → mq_gateway (dedup by id) → execution
  builds `local_analysis::DecisionContext` (kind, side, timeframe,
  main/'s levels — no size, no firing window, per L2's corrected doc)
  → local_analysis (`combined_levels` → `build_signal` → `validate`)
  → execution acts on the resulting risk-checked `SignalAction`
  (`Open`/`Close` open/close/stop-loss prices + timing), computing
  position size itself, or reports not-placed if L2 returned `NoOp` /
  a risk violation — a regular decision always goes through this
  local_analysis processing, never reaching the exchange unprocessed.
  Force signals ride the same mq_gateway channel/path but skip
  local_analysis entirely — the one case where a decision-shaped
  message is a direct pass-through to execution, still placed via the
  exchange-native-order-first safety path (per `main_goal.md`) — no
  shortcut on placement mechanics, just no L2 processing first.
- **Local safety path**: local_analysis (wall, live) + execution's own
  ongoing risk calc (SL/TP/margin-proximity) → exchange_adapter
  directly. No round-trip through mq_gateway or main/. This is the
  priority path, never blocked on MQ. Distinct from the decision path's
  one-time pre-trade `validate` above — this is what runs continuously
  once a position is already open. Alongside it, execution feeds
  local_analysis an `OpenPositionView` each iteration and applies any
  `position_advisor::advise` result (e.g. trailing the stop-loss up on
  favorable price movement) the same way — L2 proposes the adjustment,
  L3 applies it.
- **Reporting path**: execution state changes → state_store (persist)
  and mq_gateway (→ main/) — independent writes, both required, order
  between them doesn't matter.
- **Recovery path** (boot only): exchange_adapter queries
  account/positions/orders → reconciled against state_store → exchange
  wins conflicts.
- **Replay path** (offline, gate): market_data owns the replay
  mechanism itself — `MarketDataStore::replay` turns stored history
  into a feed identical in shape to the live one; replay_harness just
  requests that feed and wires it into local_analysis under test →
  pass/fail before enabling in execution.
- **Account-event path**: exchange_adapter's per-kind `MarketAccount`
  pushes own order/fill/balance/position changes (`AccountEvent`) into
  `market_data`, same ingestion pipeline as public book/trade data;
  `execution` and `state_store` subscribe there instead of each
  re-subscribing to `exchange_adapter` directly.
- **Observability**: every arrow above also emits to observability;
  omitted from the diagram as an ambient sink on all layers.

## Scope note

This spec covers structure, layer boundaries, and inter-layer
communication only. Deferred to their own specs: MQ transport choice,
exchange-adapter trait's exact method signatures (beyond the
conceptual shape in L0's doc), local_analysis signal definitions in
detail, state_store's on-disk format, and the visualizer's UI.
