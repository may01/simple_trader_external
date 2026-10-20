# CB Zone Stop From the 15-min Candle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline) — layer by layer, host tests green per task, Docker gate last. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A CB zone open's stop = the forming 15-min candle's low (long) / high (short) ∓ the trailing mean range of the last 60 closed 1-min bars, replacing the order-book stop as the default (`CB_STOP_MODE=candle`); the book stop stays selectable (`book`), `off` = placeholder.

**Architecture:** `signals::cb_stop` gains a trade-fed 1-min bar aggregator (`MinuteBars`, owned by the check's `State` like `Streaks`) and a pure `compute_candle_stop`. `CbZoneEntryCheck::with_candle_stop` arms it; step 0 feeds the bars, step 7 computes the stop and puts it on the event with two audit fields. The orchestrator parses `CB_STOP_MODE` + two knobs into `OrchestratorConfig.cb_candle_stop` and passes it through `SignalConfig::CbZoneEntry`. DTOs mirror the two fields. Nothing downstream of the event changes.

**Spec:** [`2026-10-20-cb-candle-stop-design.md`](../specs/2026-10-20-cb-candle-stop-design.md). Replay it comes from: [`runs/2026-10-20-sl-15m-anchor-replay.md`](../runs/2026-10-20-sl-15m-anchor-replay.md).

**Branch:** `cb-candle-stop` off `layer-implementation` @ `1689dc5`, worktree `trade_executor/.worktrees/cb-candle-stop`. Never commit without explicit user confirmation.

## Global constraints

- The stop never blocks a fire; every skip → `stop: None` + one `eprintln!` line; builder placeholder applies.
- `SignalPipeline::new`, `CbZoneEntryCheck::new`, `Executor::new` keep their signatures.
- Every new DTO field `Option` + `serde(default)`.
- `CB_STOP_MODE=book` must leave every existing test green and unchanged in meaning.
- Host loop: `CARGO_TARGET_DIR` may point at the `layer-implementation` worktree's target to reuse the cache.

## Docker entry points

```bash
cargo test -p signals --lib
cargo test -p local_analysis
cargo test -p orchestrator --lib
cargo test -p state_store --lib
cargo test -p visualizer_server --lib
docker compose -p ccs-test -f docker-compose.yml -f <scratch>/noports.yml run --build --rm test   # fresh volume, then down -v
```

## Task 1 — L2 `signals`: `cb_stop` candle rule (pure)

- [x] `CbCandleStopParams { anchor_minutes: u32, range_candles: usize }`, `MinuteBars` (§5), `CandleStopReading { stop, anchor, offset, bars_used }`, `CandleStopSkip { NoClosedBars, NotAdverse { stop, price } }` + `Display`, `compute_candle_stop` (§6).
- [x] Tests per spec §10 (`MinuteBars`, `compute_candle_stop`). `cargo test -p signals --lib` green.

## Task 2 — L2 `signals`: the check and the event

- [x] `SignalConfig::CbZoneEntry.candle_stop: Option<CbCandleStopParams>`; `SignalEvent::CbZoneEntry.stop_anchor`, `.stop_offset`.
- [x] `CbZoneEntryCheck::with_candle_stop`; `State.bars`; step 0 observe when armed; `stop_for` candle path first; factory wiring.
- [x] Tests per spec §10 (check). Every `SignalEvent::CbZoneEntry { … }` literal in the workspace gains the two fields.

## Task 3 — L5 DTOs

- [x] `state_store::dto` and `visualizer_server::dto` mirrors + round-trip tests with and without the keys.

## Task 4 — Orchestrator: env, config, boot, compose

- [x] `CB_STOP_MODE` (`candle` default / `book` / `off`), `CB_STOP_ANCHOR_MINUTES` (15), `CB_STOP_RANGE_CANDLES` (60) → `OrchestratorConfig.cb_candle_stop`; `cb_stop` only in `book` mode; errors per spec §9.
- [x] `cb_zone_signal_config` passes `candle_stop`; boot lines; `clear_all()` list in tests.
- [x] Compose: the three new vars with defaults; comment block updated.
- [x] Orchestrator tests per spec §10.

## Task 4b — L2 `local_analysis`: placeholder 0.2 % (user, 2026-10-20)

- [x] `PLACEHOLDER_STOP_LOSS_PCT` 1 % → 0.2 %; builder tests 99/101 → 99.8/100.2; boot line + compose comments.

## Task 5 — Gate, docs, hand-over

- [ ] Docker gate on a fresh volume (`-p ccs-test`).
- [x] UNFINISHED entry; spec status line; run report status; experiment `REPORT.md` row disposition.
- [ ] Describe the diff; wait for the user's commit decision; operator rebuild + restart is theirs.
