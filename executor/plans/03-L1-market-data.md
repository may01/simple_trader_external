# Step 3 — L1 market_data (plan)

Part of the [layer implementation sequence](2026-09-05-layer-implementation-sequence.md).
Spec: [L1-market-data](../specs/layers/L1-market-data.md).

## What to implement

- Live order book per pair, built by applying L0's incremental
  updates on top of periodic snapshots, plus latest candles and
  trade tape.
- Local persistence of everything L0 streams — book updates,
  trades, candles, and account events — as the single layer that
  touches storage directly; every other layer reads through this
  layer's interface only, never the store files themselves.
- Gaps in any stream are recorded explicitly (never silently
  interpolated), so a later replay sees the same gaps that happened
  live.
- Replay: turn a stored time range back into something that behaves
  exactly like the live feed, so any consumer (analysis, backtest)
  runs the same code path against live or historical data
  unmodified. This layer owns replay mechanics; L6 only orchestrates
  the gate on top of it.
- Feed-staleness detection and propagation once a source disconnects
  beyond grace period.

## Acceptance criteria (high level)

Staged — each stage gated on the next layer existing.

**Status:** implemented and committed on branch `layer-implementation`
(`crates/market_data`, commit `029fe43`): `BookTracker` (apply +
gap-detect), sled-backed `MarketDataService` (one tree per stream kind),
`read_range`/`read_account_events`, `ReplayFeed`. 14 tests green,
clippy clean, Docker-verified. Wired to L7: a detected gap calls both
`Metrics::record("market_data_gap_detected")` and
`Alerts::fire(AlertKind::FeedStale)` (Stage 4's requirement, done early
since observability already existed).

**Update (2026-09-09, branch `book-crossed-safety-check`):**
**Correction, 2026-09-11: this note was factually wrong and is now
fixed.** `apply_deltas` did **not** move out of `market_data::book` —
it is still defined there (`crates/market_data/src/book.rs:10`,
`pub fn apply_deltas`). The false claim below ("moved into
`exchange_adapter`, re-exported by `market_data`") was copied
verbatim into
[postgres-market-data-store-design.md](../specs/2026-09-09-postgres-market-data-store-design.md)
and the 2026-09-09 plan; both have been corrected alongside this note.
What L0 adapters actually maintain for the crossed-book safety check is
their own independent ladder-maintenance logic, not a shared call into
`market_data::apply_deltas` — L0 cannot depend on L1, so it could never
have called L1's function regardless of which crate it lived in; this
note conflated "L0 has its own deltas logic for the same problem" with
"the shared function moved," which is not what happened. `BookTracker`
in `market_data` is otherwise unchanged: a crossed book is detected and
repaired in L0, so one never reaches L1.

**Update (2026-09-11, branch `postgres-market-data-store`):**
`market_data` moved from sled to PostgreSQL — schema, write path, read
path and the visualiser's read-only `PgMarketDataReader` are implemented
and Docker-verified (408 tests passing, 45 suites, as of Task 10's
re-verification). See
[postgres-market-data-store-design.md](../specs/2026-09-09-postgres-market-data-store-design.md)
for the full design and
[L1-market-data.md](../specs/layers/L1-market-data.md) for the amended
spec. Two things this update does **not** close: (1) the feed-staleness
fallback to "exchange-native stop only" is a no-op on MEXC, which has no
exchange-native stop order on either market kind — see L1's spec's own
Error handling section, a pre-existing safety gap this migration did not
introduce but did not fix either; (2) the write-failure shutdown policy
this plan's Task 7 specified was **not implemented** — `write_failed()`
is exposed but nothing polls it — because the safety-gate check that
same task required turned up (1) above: shutting the executor down on a
sustained write failure would kill the in-process stop-loss watcher,
which on MEXC is the *only* thing protecting an open position, making
shutdown strictly worse than continuing to trade. See
`.superpowers/sdd/2026-09-09-postgres-market-data-store-plan/task-7-report.md`
in the code worktree for the full finding.

Not yet closed: Stage 1's "for a live pair" wording implies a live/
testnet adapter feed — what's actually verified is ingestion/replay
logic against synthetic `MarketDataEvent`s in unit tests, since L0's
concrete adapters (`exchange_adapter_binance`/`_mexc`) are themselves
only mock-tested (no real testnet credentials yet, see their own plan
doc). `read_range`'s cross-tree merge is a sort-after-collect, not the
spec's preferred k-way merge over already-sorted per-CF ranges — a
documented simplification in `store.rs`, revisit if replay-window sizes
grow large enough for it to matter. Stages 2-5 are gated on
local_analysis/execution/replay_harness, none built yet.

**Stage 1 — glue to L0**
- [ ] Every event L0 emits for a live pair is captured, persisted,
      and retrievable unchanged; a deliberately induced gap produces
      an explicit gap marker, never a silent skip; live book/candle/
      trade views reflect ingested data correctly.

**Stage 2 — glue to L2 (local_analysis)**
- [ ] Every input local_analysis actually reads is served correctly;
      any missing capability is treated as an L1 interface gap to
      fix, not an L2 workaround.

**Stage 3 — glue to L3 (execution)**
- [ ] Account events reach execution with no loss/reordering;
      feed-staleness propagation actually triggers execution's
      fallback path in a real test.

**Stage 4 — glue to L7 (observability)**
- [ ] Feed staleness/disconnect and gap markers generate real
      alert-class events once observability exists.

**Stage 5 — glue to L6 (replay_harness)**
- [ ] Replay reproduces the exact recorded sequence, gaps included;
      the same local_analysis build run live and via replay over the
      same window produces matching output.

**Standing rule**: whenever a new layer names `market_data` as a
dependency, add a stage here validating that specific consumption
before treating L1 as done with respect to it.
