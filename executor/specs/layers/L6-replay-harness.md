# L6 — replay_harness

Part of [architecture index](../2026-09-04-architecture-design.md).

## Purpose

Required gate: any change to `local_analysis` must replay against
captured market conditions before being enabled in live trading. Not
just a research tool.

## Responsibilities

- Orchestrate the gate: pick a dataset window, get a replay-mode feed
  from `market_data` (`MarketDataStore::replay`), wire it into the
  *same* `local_analysis` code path used live — this crate does not
  implement replay mechanics itself; that lives in `market_data` (L1)
  so any analysis task can reuse it, not just this gate.
- Produce a pass/fail report gating promotion to `execution`.

## Depends on

`market_data::MarketDataStore::replay` (returns a `MarketDataFeed`
backed by history — see L1's Storage design / Interface),
`local_analysis::{CriticalLevelAnalyzer, SimpleSignalFeed}` (the
implementation under test, unmodified from its live form).

## Interface exposed upward

```
trait ReplayRunner {
    fn run(
        &self,
        window: (Pair, Ts, Ts),
        analyzer: impl CriticalLevelAnalyzer + SimpleSignalFeed,
    ) -> ReplayReport;
    // internally: market_data.replay(pair, from, to, ReplaySpeed::AsFast)
    // wired straight into `analyzer` — no bespoke replay code here
}
```

Consumer: dev/CI workflow gating a `local_analysis` change before it
ships to `execution` — not another runtime layer at trading time.

## Error handling

A signal change that fails replay blocks promotion — this is a gate
outcome, not a runtime error to catch and recover from.

## Testing

Golden-replay tests: known dataset + known analyzer version → known
report, to catch regressions in the harness itself.
