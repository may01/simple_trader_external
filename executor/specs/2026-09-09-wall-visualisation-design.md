# Wall visualisation — design

Replaces the candle chart's exchange-trade markers with a persisted,
drawable record of detected order-book walls.

Amends [L2-local-analysis.md](layers/L2-local-analysis.md) (a `WallSink`
port and a side/qty-carrying wall observation) and
[L5-state-store.md](layers/L5-state-store.md) (a `wall_log` tree).

## Motivation

The pair chart drew a green/red arrow per large exchange trade
(top-30 by qty). Two problems: the arrows say nothing the operator acts
on, and they consume the one visual vocabulary that should mean "the
system itself traded here". Walls — resting orders materially larger
than the book's own average — are the thing worth seeing on the price
axis, and nothing persisted them.

Arrows are therefore retired from the chart entirely and reserved for a
later system-trade overlay.

## What is recorded

`WallDetector` already finds walls but returns `Level`, which carries
only a price and a source tag. Drawing needs two more facts:

- **side** — a bid wall sits below price (support), an ask wall above.
- **qty** — the resting size, used to rank walls when a snapshot holds
  more than the chart draws.

Rather than widen `Level` (which would ripple through `execution`,
`mq_gateway` and `state_store`'s DTOs), `local_analysis` gains a
parallel, visualisation-only type:

```
struct WallObservation { price: Price, side: Side, qty: Decimal }

impl WallDetector {
    fn wall_observations(&self, book: &OrderBookSnapshot) -> Vec<WallObservation>;
    fn walls(&self, book: &OrderBookSnapshot) -> Vec<Level>;  // defined in terms of the above
}
```

`walls` is implemented on top of `wall_observations`, so there is one
threshold implementation, not two that can drift.

## Where it is written

`state_store` already depends on `local_analysis`, so
`local_analysis -> state_store` would be a dependency cycle. The write
is inverted into a port owned by the lower crate:

```
trait WallSink: Send + Sync {
    fn record(&self, pair: &Pair, ts: Ts, walls: &[WallObservation]);
}
```

`StateStoreImpl` implements it; the orchestrator injects it into
`LiveCriticalLevelAnalyzer`. `record` returns nothing on purpose: it
fires on the path `execution` uses to size a trade, so a full disk must
never become a failed decision. Errors are metered
(`state_store_wall_snapshot_write_failed`) and dropped — the same
posture `persist_correction` already takes.

## Cadence

Snapshots are periodic, aligned to the candle interval
(`WALL_SNAPSHOT_INTERVAL_SECS`, `0` = recording off), so one row lands
per bar and the chart's overlay has the same time grid as the candles.

Two callers reach `walls`:

- `execution`, whenever it evaluates a decision — an irregular clock.
- A dedicated orchestrator task, ticking once per interval — so the
  series has no gaps in the stretches when nothing is being decided,
  which is exactly when the operator most wants to look.

`LiveCriticalLevelAnalyzer` buckets by `book.ts / interval` per pair, so
those two callers can never double-write one interval. Bucketing on the
*book's* timestamp rather than a wall clock means replay reproduces the
same series as live. A book older than the last recorded bucket is
skipped, never rewound.

## Storage

A `wall_log` sled tree keyed `(pair, ts, seq)` via the existing
`keys::pair_ts_seq_key` — the same append-only, pair-isolated pattern as
`event_log`, including the `0x00` separator that keeps `BTC` and
`BTCUSDT` from overlapping. One row per snapshot, holding the whole wall
set:

```
struct WallSnapshot { ts: Ts, walls: Vec<WallObservation> }

trait StateStore {
    fn read_wall_log(&self, pair: Pair, from: Ts, to: Ts) -> Stream<WallSnapshot>;
}
```

An empty `walls` vector is a meaningful row — "we looked at this
interval and there were none" — and is deliberately distinct from no row
at all ("we never looked"). The trait exposes only the read side; the
write side is `WallSink`, for the infallibility reason above.

## Read path

`visualizer_backend::wall_snapshots(pair, from, to)` is always
historical and never mode-aware — the wall log is a persisted series, so
"what walls were there" is answered from the store whether or not the
executor is live. Wrapped in `catch_unwind`, same degrade-not-crash
contract as `historical_position_events`.

`GET /pairs/:pair/history` gains `walls: Vec<WallSnapshotDto>`. Unlike
`book` (collapsed to its final snapshot to avoid an OOM on hundreds of
thousands of deltas), the whole wall series is returned: it is one row
per candle interval, and the overlay draws the series rather than a
latest state.

Live connections **poll**: `state_store` has no change subscription, and
at one row per candle there is little to gain from inventing one. The WS
task seeds a high-water mark from what is already on disk (the client
got that from `GET /history`), then every `WALL_POLL_INTERVAL` reads
only rows newer than the mark and pushes them as `LiveMessage::Walls`.
Seeding up front rather than treating "first poll that finds rows" as
the seed is what makes an empty store behave: with nothing recorded yet
the mark stays at 0, so the first snapshot ever written is sent instead
of being swallowed.

## Drawing

The vendored lightweight-charts is v4.1.3, whose `SeriesMarker` has no
`price` field — positions are only `aboveBar`/`belowBar`/`inBar`, so a
marker physically cannot sit at a wall's price. (`atPriceMiddle` is v5.)

Walls are therefore drawn as a line series with `lineVisible: false` and
`pointMarkersVisible: true`, which renders as pure scatter at exact
prices. Circles, not arrows — arrows stay reserved for system trades.

A line series holds one value per time, so each side gets `WALL_SLOTS`
(4) parallel series: within a snapshot, the largest wall by qty goes to
slot 0, the next to slot 1, and so on; anything beyond the slot count is
dropped rather than overplotted. Slots rank per snapshot rather than
tracking a wall through time, so a slot's price can jump between
snapshots — invisible precisely because the connecting line is off. A
slot with no wall in a given snapshot gets a whitespace point (`time`,
no `value`), keeping every slot on one time grid.

Colours: bid walls `#8250df`, ask walls `#bf3989` — deliberately not the
candle green/red nor the blue position lines.

## Known overlap

The `state-store-expansion` branch adds a generic analysis log
(`persist_analysis(pair, kind, bytes, computed_at)` /
`read_analysis_log`). `wall_log` is a typed special case of it. When
that branch merges, `wall_log` should collapse into `analysis_log` with
`kind = "walls"`, keeping `WallSink`/`WallSnapshot` as the typed façade
so nothing above `state_store` changes.
