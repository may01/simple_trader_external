# Step 9 — L8 interfaces (cli, visualizer_backend) (plan)

Part of the [layer implementation sequence](2026-09-05-layer-implementation-sequence.md).
Spec: [L8-interfaces](../specs/layers/L8-interfaces.md).

## What to implement

- **cli**: inspect the running process — status, positions, logs.
  Force actions go through the same message-queue path as any other
  force action; the CLI may publish onto that queue for convenience,
  not a separate command path.
- **visualizer_backend**: renders historical market data from local
  storage, switching to live updates while the executor is running
  live trading.
- Both are read-only against the running system except for the
  CLI's force-action publish path.

## Acceptance criteria (high level)

**Status:** implemented and committed on branch `layer-implementation`
(`crates/cli`, `crates/visualizer_backend`, commit `5daacfb`). 12 tests,
workspace total 211, clippy clean, Docker-verified. Both crates degrade
read-only paths to an `Unavailable`/`VisualizerError` on a panicking
fake dependency rather than crashing — `cli::logs` specifically needed
`tokio::spawn`+`JoinError` rather than `catch_unwind` (which only
guards a stream's `.next()` call construction, not a panic while it's
actually polled). `visualizer_backend`'s live/historical switch is
tested as two genuinely distinct behaviors (a live-mode test confirms a
newly-ingested event arrives, not pre-existing historical data).
`mq_gateway::encode_force_close` was added for `cli::force_close` (the
inverse of `decode_inbound`'s force-close arm, needed by nothing until
now).

**Update (2026-09-11, branch `postgres-market-data-store`):** the
visualiser half of this layer was pulled out of the executor process
entirely and rebuilt as a separate `visualizer_server` binary reading
only committed Postgres rows via `PgMarketDataReader`/`PgStateReader` —
`cli` is unaffected, still in-process. `LiveModeFlag` is deleted,
replaced by a `max(recv_ts)`-lag freshness signal per pair (catches a
crashed/wedged executor, which the boot-time flag never did).
`PgMarketDataReader` implements `MarketDataStore` only — no
`MarketDataFeed`, since a non-ingesting process's live caches are
permanently empty. No exchange-adapter dependency of any kind, asserted
directly against `cargo tree` by
`the_visualizer_binary_has_no_exchange_adapter_dependency`
(`visualizer_server/tests/passive.rs`), alongside a role-based
passivity test (`dashboard` role: `INSERT` denied, `SELECT` allowed).
Docker-verified end-to-end for three of four entry points (test suite;
`--migrate-only`; dashboard serving while the executor is stopped); the
fourth (executor boots, ingests, dashboard flips Offline→Fresh) reached
a real MEXC REST call rejected for invalid placeholder credentials
(`[10072] Api key info invalid`) and was not driven further — no funded
exchange account was available in this environment. See
[L8-interfaces.md](../specs/layers/L8-interfaces.md) and
[postgres-market-data-store-design.md](../specs/2026-09-09-postgres-market-data-store-design.md)
for the full design, and this plan's own Task 10 report in the code
worktree for the entry-point evidence.

- [ ] cli shows correct status/positions/logs against a fake
      execution engine and message queue, and a published force
      action follows the same path/error handling as any other
      mq_gateway publish.
- [ ] visualizer_backend renders historical data correctly from a
      fixture store, and correctly switches to a live feed when the
      executor is running live — verified as two distinct behaviors,
      not just one code path assumed to cover both.
- [ ] Read-only paths degrade to "unavailable" on failure — neither
      surface ever crashes the underlying engine it's inspecting.
