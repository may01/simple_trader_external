# Step 10 — L9 orchestrator & deploy (plan)

Part of the [layer implementation sequence](2026-09-05-layer-implementation-sequence.md).
Spec: [L9-deploy](../specs/layers/L9-deploy.md).

## What to implement

- The binary crate that constructs every other layer from config,
  wires them together in the fixed construction order (observability
  → exchange adapters → market_data → local_analysis →
  state_store's load+reconcile → execution → mq_gateway →
  execution's runtime loop → interfaces), and owns the top-level
  error boundary. This is the only place depending on every layer at
  once.
- Env-based config loading into each layer's own config type,
  credentials never logged or sent over the queue.
- Multi-pair operation: one ingestion+iteration task per configured
  pair, with a per-pair panic isolated (logged as an alert) rather
  than taking down the process or other pairs.
- Graceful shutdown on SIGTERM: stop accepting new decisions, let
  in-flight placements resolve or fail cleanly, flush state, close
  connections — never a hard kill that could orphan a placed order.
- Docker packaging around running the binary.

## Acceptance criteria (high level)

**Status:** implemented and committed on branch `layer-implementation`
(`crates/orchestrator`, commit `3864f61`). This is the final layer —
L0 through L9 are all implemented, tested, and Docker-verified (223
tests total across the workspace). 9 tests in this crate specifically
(config validation, full boot sequence via a fake adapter, panic
isolation, shutdown). Docker now has a `release` target building the
real `trade_executor` binary (previously only a `test` target existed,
since no binary existed yet) — actually run in this environment to
confirm it fails fast with a complete, clear error list on missing
config, per the acceptance criterion below.

Building this surfaced and fixed a real bug in two already-committed
crates: `execution::Executor::run_stop_loss_watcher`/`run_advisor_loop`
and `mq_gateway::drive` all read from broadcast channels whose sender
the process itself holds alive, so "await every background task to
natural completion" (the obvious graceful-shutdown strategy) would
hang forever on all of them. Fixed with a shutdown signal raced only
against "wait for the next item," never a whole iteration's body, so
an in-flight order placement is never cut off — see those crates'
own commits for detail.

Known gaps, not silently assumed solved: `main.rs`'s exchange/
credential resolution is real code but untestable without real
credentials (same posture as every other layer's live-exchange gap).
`PaperMarketAccount` can't stand alone as `boot()`'s market account for
a zero-credential "paper trading against live data" deployment — it
has no market-data subscription capability of its own; that needs a
delegating wrapper, not built here. The docker-compose integration
test against a real exchange sandbox (this layer's own Testing
section) remains gated on testnet credentials, same as L0/L1/L3.

- [ ] Valid config boots through every construction step in order,
      reaching "ready" only after reconciliation completes — never
      before.
- [ ] Invalid config (missing/malformed values) fails fast at boot,
      non-zero exit, clear log — never a partial start.
- [ ] Two or more configured pairs run concurrently with no
      cross-pair interference; a simulated panic in one pair's task
      leaves the others running.
- [ ] SIGTERM during an in-flight order placement waits for it to
      resolve (or fail cleanly and get reported) before the process
      exits — never silently abandoned.
- [ ] Standing rule: once each dependency's real implementation
      exists, re-verify this layer's wiring against what was actually
      built — this layer is exposed to every other layer's changes,
      so it needs the most frequent re-checks.
