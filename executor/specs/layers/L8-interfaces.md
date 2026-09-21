# L8 — interfaces (cli, visualizer_backend)

Part of [architecture index](../2026-09-04-architecture-design.md).

## Purpose

Human-facing surfaces. Two crates at this layer in-process with the
executor (`cli`), plus — **superseded 2026-09-11**, see
[postgres-market-data-store-design.md](../2026-09-09-postgres-market-data-store-design.md)
— a visualiser that is no longer an in-process consumer at all:
`visualizer_backend`/`visualizer_server` now run as a **separate
process**, reading only committed rows out of Postgres. What they
render (panels, order-book reconstruction, frontend choice) is
unchanged from the original design in
[executor-visualiser-design.md](../2026-09-07-executor-visualiser-design.md)
(see that file's own supersession note for the exact split of what
still stands vs. what changed) — only the process topology and
transport moved.

## Responsibilities

- **cli**: inspect the running process — status, positions, logs.
  Force actions are issued as queue messages (via `mq_gateway`), not a
  separate CLI-only command path; the CLI may publish onto the same
  queue for convenience. Unaffected by the visualiser's process split —
  `cli` stays in-process with the executor, talking to
  `ExecutionEngine`/`mq_gateway`/`StateStore` directly.
- **visualizer_backend** / **visualizer_server**: a separate binary
  (`visualizer`) rendering historical and live market/position data by
  reading **only committed database rows**, via `PgMarketDataReader`/
  `PgStateReader` — never a call into the executor's in-process state,
  because there is no such call available across a process boundary.
- **Indicators panel** (added 2026-09-21, built — see
  [indicator-visualisation-design.md](../2026-09-20-indicator-visualisation-design.md)):
  `VisualizerBackend::current_indicators(pair, as_of)`, a pass-through
  to `PgStateReader::read_current_indicators`, served as
  `GET /api/current_indicators?pair=&as_of=` (`as_of` optional,
  default the server's now; `CurrentIndicatorDto` adds `age_ms`/
  `expires_in_ms` computed against that same instant). The pair page's
  Indicators panel polls it on the existing status tick — Live with no
  `as_of`, History with the loaded window's end — mutes rows with under
  30 s left, and shows "No live indicators — `main/` may not be
  publishing." when empty. Read-only, like everything else here: no
  chart drawing of indicators, no history series.

## Depends on

`execution::ExecutionEngine::position_state` (cli status),
`mq_gateway::DecisionInbound`-compatible publish path (cli force
actions), `state_store::StateStore` (cli read-only inspection),
`market_data::MarketDataStore` via `PgMarketDataReader` (visualiser
historical + live — **not** `MarketDataFeed`, see below).

**No exchange dependency, asserted by test, not just convention.** The
visualiser crates depend on `exchange_adapter` for wire **types** only;
they do not depend on `exchange_adapter_binance` or
`exchange_adapter_mexc`, and the container receives no exchange
credentials or URLs at all. A test
(`the_visualizer_binary_has_no_exchange_adapter_dependency`, in
`visualizer_server/tests/passive.rs`) asserts this directly against
the real `cargo tree` output, so a later edit that quietly reintroduces
an exchange-adapter dependency fails the suite rather than going
unnoticed.

**`PgMarketDataReader` implements `MarketDataStore` only — deliberately
no `MarketDataFeed` impl.** `MarketDataFeed`'s live getters
(`order_book`, `candles`, `latest_trades`) are served from in-memory
caches that only `ingest` fills. A process that never ingests (this
one) would have permanently empty caches, so giving the reader
`MarketDataFeed` would let a caller compile a call to a getter that can
only ever return nothing — a silent-nonsense trap, not a working live
view. The live view instead comes from `MarketDataStore::tail`
(`ins_seq` cursor polling, see L1) plus the freshness signal below, not
from `MarketDataFeed` at all.

**`LiveModeFlag` is gone.** It was an in-process `AtomicBool`, set once
at boot and meaningless across the new process boundary (the visualiser
and the executor are no longer the same process to share a flag with).
It is replaced by **freshness derived from `max(recv_ts)` lag** per
pair: fresh below a threshold, "feed stale" above it, "executor
offline" above a longer one. This is strictly more informative than
the flag it replaces — `LiveModeFlag` never caught an executor that had
crashed or wedged after boot, since it was only ever set once; a lag
computed from the newest row the database actually has catches exactly
that case, because a dead or wedged executor simply stops advancing
`recv_ts`.

## Interface exposed upward

None — this is the top of the stack. Exposed to humans/operators, not
to another crate.

## Error handling

Read-only paths (status/history) degrade to "unavailable", never crash
the underlying engine. CLI-published force actions follow the same
error path as any other `mq_gateway` publish (see L4). The visualiser's
per-panel errors degrade to an error banner and keep serving whatever
is already loaded, retrying in the background — a database error is a
typed `Result`, not a caught panic, now that reads go through `sqlx`
rather than an in-process call that could panic across an abstraction
boundary.

## Testing

cli: integration test against a fake `ExecutionEngine` +
`mq_gateway`. visualizer_backend/visualizer_server: integration test
against a real (schema-isolated) Postgres fixture via `PgMarketDataReader`/
`PgStateReader` for historical rendering and the freshness computation,
plus the passivity suite (`visualizer_server/tests/passive.rs`): the
`dashboard` database role gets `permission denied` on `INSERT` while a
`SELECT` against the same table succeeds (proving the restriction is
real, not just "this role can't see the schema at all"), and the
dependency-tree test described above.
