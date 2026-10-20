# CB zone entry signal (replaces SAR flip as the open signal) — Design Spec

Date: 2026-10-18
Status: **implemented 2026-10-18 on branch `cb-zone-entry-signal` (committed `e493080`, in `layer-implementation` = `release_001` @ `1689dc5` since 2026-10-20) — host loop green (signals 73, orchestrator lib 87, state_store/visualizer DTO round-trips); Docker gate 1407 passed / 3 pre-existing timing flakes in untouched crates (plan step 6.3); the operator's live check pending**
Target project: `trade_executor` (worktree `layer-implementation`) — L2 `signals` crate (new check), L5 `state_store` DTO, orchestrator config/boot/dispatch, `visualizer_server` DTO, L9 compose. No `main/` change: every indicator this reads is already broadcast by `cb-overshoot-main-flow`.
Supersedes as the *open* signal: [2026-09-22-sar-flip-test-signal-design.md](2026-09-22-sar-flip-test-signal-design.md). `SarFlipCheck` stays in the code, disarmed by compose.
Related: [2026-10-16-cb-overlay-visualiser-design.md](2026-10-16-cb-overlay-visualiser-design.md) §3 (the indicator names and their meaning), main/ `external/docs/superpowers/specs/2026-10-05-cb-markers-main-flow-design.md` (zone formulas), [2026-09-16-trade-visualization-design.md](2026-09-16-trade-visualization-design.md) §5 (the 1-min price MA + trend class the visualiser already draws — this spec computes the same thing in Rust), [layers/L2-local-analysis.md](layers/L2-local-analysis.md).

## 1. Why

The executor's only live open signal is the SAR flip test signal: it exists to prove the indicator → decision → order path, not to trade. main/ now broadcasts the candle-bound (CB) entry zones, in-zone markers and their filters for tf 15/60/240 every 30 s, and the visualiser draws them. Nothing trades on them. This spec makes the executor open positions from the CB zones, gated by the direction of a short price moving average computed from its own trade feed.

## 2. Decisions taken by the user (2026-10-18)

| Question | Answer |
|---|---|
| Rule 2's "zone boundary" | The **zone level** `{tf}_cb_zone_{side}`, not the outer bound: the previous 1-min candle's wick reached the zone and the candle closed back outside it. |
| Rule 1's "candle is in open zone" | main/'s own flag `{tf}_cb_inzone_{side} == 1` — the same marker the chart draws; nothing re-derived. |
| Timeframes | All three: 15, 60, 240. One check per tf, any may fire; the decision carries that tf. |
| Filters | `{tf}_cb_f_overshoot_{side}` and `{tf}_cb_f_trend_{side}` must pass. **Not** extdone. |
| Exits | Unchanged placeholders (1 % stop, nearest-level target; `MIN_RR=0`). A separate task. |
| Re-fire control | At most once per (tf, side, zone value) plus a 60 s minimum gap per check. |

Calls made by the author after the builder check (not asked of the user; flagged for review):

| Question | Call |
|---|---|
| Which position-opening check families may coexist on a pair | Exactly one. Priority CB > SAR > Mock: `CB_ZONE_SIGNAL_TFS` set suppresses `MockVolumeCross` the way SAR does today; CB **and** SAR both set is a **config error** (two independent decision tasks with their own reversal logic on one pair is what the code's exclusion rule forbids). |
| Cross-timeframe conflicts | The three tfs are evaluated by **one** check instance (`CbZoneEntryCheck { tfs }`) that emits **at most one event per trade**: candidates on both sides across any tfs → contradiction, nothing fires; several same-side candidates → the **highest tf** is reported (its zone is the larger structure), the others' re-fire keys are marked too. A later fire on a lower tf may still reverse a position opened from a higher tf — accepted: the decision task's reversal rule already treats an opposite signal as evidence against the held position, and nothing today records a position's tf. |
| 60 s gap: consumed or deferred | **Deferred.** A candidate blocked only by the gap is not recorded as fired; it fires on the first trade after the gap if it still holds. The gap exists to stop rapid re-opens, not to burn a zone for a whole 4 h candle. Only the once-per-(tf, side, zone) rule consumes. |

## 3. Scope

In: a `CbZoneEntryCheck` in the `signals` crate (one instance per tf); a Rust port of the visualiser's 1-min price MA + slope + trend class; a `SignalEvent::CbZoneEntry` variant through persistence (`signal_log`) and the visualiser's signal DTO; orchestrator env knob, boot wiring, side dispatch, decision timeframe; compose defaults switched from SAR to CB.

Out: exits (placeholder stays), position sizing, `main/`, chart markers for the new signal (the Decisions it produces already draw as decision markers), replay-harness support for indicator-driven signals (same gap SAR has: expiry is wall-clock).

## 4. The data this reads

Per tf ∈ {15, 60, 240}, from `MarketDataWindow::indicators` (prefetched by `SignalPipeline` via `required_indicators`, expiry already applied — an expired or never-received name is simply absent):

| Name | Type | Used for |
|---|---|---|
| `{tf}_cb_zone_long`, `{tf}_cb_zone_short` | price | rule 2's line; the re-fire key |
| `{tf}_cb_inzone_long`, `{tf}_cb_inzone_short` | 0/1 | rule 1 |
| `{tf}_cb_f_overshoot_long/short`, `{tf}_cb_f_trend_long/short` | 0/1 | filters |

Eight names per tf, twenty-four in all. `cb_low`/`cb_high`/extdone are not read.

Meaning (main/ spec): `cb_zone_long = cb_low + 0.05·(cb_high − cb_low)`, `cb_zone_short = cb_high − 0.05·(cb_high − cb_low)`; `cb_inzone_long` is true for a minute whose 1-min low ≤ `cb_zone_long` (short: high ≥ `cb_zone_short`). A zone value changes only when its tf candle closes. A filter flag is `0` when main/ would veto that side.

From `MarketDataWindow::recent_trades` (oldest first, count-bounded at 6 000 by `SIGNAL_PIPELINE_WINDOW_CAPACITY`): the MA, and the previous 1-min candle for rule 2. `window.now` is the latest trade's exchange timestamp.

## 5. The MA and trend class (Rust port of `static/js/trades_ma.js`)

> **Superseded in part 2026-10-18** by [2026-10-18-cb-target-trend-exit-design.md](2026-10-18-cb-target-trend-exit-design.md) §6: the computation below now runs **once per trade in `SignalPipeline`** (`with_trend`), not inside `CbZoneEntryCheck`; the check reads `MarketDataWindow::trend`, the executor's exit reads the same reading off a `TrendSlot`. `SignalConfig::CbZoneEntry` lost its `trend` field. §4's name list gains `{tf}_cbnc_high`/`_low` (ten per tf) and the event carries `target`.

Same numbers as the visualiser so an operator can read the chart and the decision together:

1. Mean trade price per **10 s bucket**, on a dense grid from the first to the last bucket with a trade; a quiet bucket carries the previous mean forward.
2. Trailing mean over **6 buckets** (1 min), early buckets averaging what exists.
3. Slope = first difference per bucket.
4. σ = population standard deviation of the slopes over the buckets in the window, **bounded to the last 2 h** of buckets (the chart's window; the trade count bound usually cuts earlier).
5. Class of the **last** bucket (the one containing `now`): **up** if slope > +0.7·σ, **down** if < −0.7·σ, else **neutral**. σ = 0 → neutral.

Insufficient data: fewer than **30 buckets** (5 min of trades) → no class, the check does not fire (never a guessed class). Arithmetic in `f64`; `Decimal` → `f64` on the way in, the slope reported on the event as `Decimal` from `f64` (audit only, nothing downstream computes with it).

Module `signals::trend` (pure, no I/O): `bucket_mean_prices`, `trailing_means`, `slopes`, `std_dev`, `classify`, `trend_class(trades, now, params) -> Option<TrendReading { class, slope, sigma }>`. `TrendParams { bucket: Duration, ma_window: Duration, std_mult: f64, std_span: Duration, min_buckets: usize }`, defaults above. The unit tests reuse the JS tests' fixtures and expected values (`trades_ma.test.js`) so the two implementations are checked against the same numbers.

## 6. The check (`CbZoneEntryCheck`, one instance for all armed tfs)

`SignalConfig::CbZoneEntry { tfs: Vec<u32>, min_interval: Duration, trend: TrendParams }`; the check's own `id()` is `cb_zone_entry`, but every **event** carries the firing tf's id `cb_zone_{tf}` (`cb_zone_15` / `cb_zone_60` / `cb_zone_240`, static strings from a `CB_ZONE_ENTRY_IDS` table like `VOLUME_BOOK_DEPLETION_IDS`) — that is what lands in `signal_log.signal_id`, so a row says which zone fired.

Per trade (`check(window)`):

1. `trend = trend_class(...)`; `None` → return `None`.
2. Previous 1-min candle: minute `m = floor(now / 60 s) − 1`; low/high/close of the trades with `ts` in `[m, m+60 s)` (close = last trade by `ts`). No trade in that minute → rule 2 unavailable this tick (rule 1 still runs).
3. For each armed tf and each side `s ∈ {long→Buy, short→Sell}`:
   - **filters**: `{tf}_cb_f_overshoot_{s}` and `{tf}_cb_f_trend_{s}` must not be `0`. Absent = pass (the viewer's rule; a flag main/ never sent cannot veto). Vetoed → side skipped.
   - `zone = {tf}_cb_zone_{s}` must be present, else side skipped.
   - **rule 1 (in zone)**: `{tf}_cb_inzone_{s} == 1` **and** trend class = direction of `s` (up for long, down for short).
   - **rule 2 (zone rejection)**: previous candle available **and** (long: `low ≤ zone` and `close > zone`; short: `high ≥ zone` and `close < zone`) **and** trend class ∈ {neutral, direction of `s`}.
   - rule 1 or rule 2 → the side is a candidate, tagged with the rule that fired (rule 1 wins the tag when both hold).
4. Drop every candidate `(tf, s, zone)` already fired (once per zone value per tf and side — state in a `Mutex`, like `SarFlipCheck`).
5. Remaining candidates on **both** sides (possible only with a neutral trend and rule-2 rejections on different zones) → contradictory, `None`, nothing recorded.
6. `now − last_fired < min_interval` (60 s, exchange time) → `None`, nothing recorded: the candidate is **deferred** and fires on the next trade after the gap if it still holds.
7. Fire for the **highest** tf among the remaining same-side candidates: `SignalEvent::CbZoneEntry { pair, ts: now, signal_id: cb_zone_{tf}, side, tf_minutes, rule, zone, price (last trade), trend_class, ma_slope }`; record `last_fired = now` and every remaining candidate's `(tf, s, zone)` as fired (they describe the same open).

`required_indicators()` returns the eight names of §4 for every armed tf.

Equality on the zone value is on the `Decimal` as received; main/ re-publishes the same value every 30 s until the tf candle closes, so "same value" is "same candle" in practice.

## 7. Orchestrator

- **Env** `CB_ZONE_SIGNAL_TFS` — comma-separated minutes, e.g. `15,60,240`. Absent or blank = disabled. Any value other than 15/60/240 is a config error (the names main/ publishes exist for those three only); duplicates are deduped; order is irrelevant. Parsed into `OrchestratorConfig::cb_zone_signal_tfs: Vec<u32>` (sorted). Set together with `SAR_TEST_SIGNAL_INDICATOR` → config error (§2's call).
- **Boot**: when non-empty, one `SignalPipeline` per pair holding the one `CbZoneEntryCheck { tfs }`, over the same `StateStoreIndicators` source the SAR pipeline uses, driving its own `run_signal_decision_task` with task cooldown `Duration::ZERO` (the check paces itself) — the SAR block's shape, next to it. `trade_window_signal_configs` registers `MockVolumeCross` only when **neither** CB nor SAR is armed. Boot prints which tfs are armed, as it does for SAR.
- **Dispatch**: `SignalEvent::CbZoneEntry { side, .. } => Some(side)`.
- **Decision timeframe**: `TradeDecision.timeframe` becomes the event's tf (`15→M15`, `60→M60`, `240→M240`) for `CbZoneEntry`; every other event keeps the `M15` placeholder. Both the open and the reversal's close leg carry it.
- Everything after the decision (reversal, flat wait, fail-closed audit, sizing, placeholder exits) is unchanged.

## 8. Persistence and DTOs

- `state_store::dto::SignalEventDto` gains `CbZoneEntry { pair, ts, signal_id: String, side, tf_minutes, rule: String ("in_zone" | "zone_rejection"), zone, price, trend_class: String ("up"|"down"|"neutral"), ma_slope }` with `From`/`TryFrom` round-trip (a stored `signal_id` that is not one of the three → `Decode` error, same as depletion). `pg.rs`'s `ts` match gains the arm.
- `visualizer_server::dto::SignalEventDto` gains the mirror variant minus `ts` (wrapper supplies it). The SPA's `setSignalMarkers` already skips unknown kinds.

## 9. Compose (L9)

`docker-compose.yml` executor service: `CB_ZONE_SIGNAL_TFS=${CB_ZONE_SIGNAL_TFS:-15,60,240}`; `SAR_TEST_SIGNAL_INDICATOR=${SAR_TEST_SIGNAL_INDICATOR:-}` (default off; the comment says how to re-arm). The live executor is **not** recreated by this work ([feedback: never recreate the live executor from my shell]); the operator restarts it.

## 10. Error handling

A check never errors: missing indicator, missing candle, too few trades, σ = 0 all collapse to "did not fire". A config error (`CB_ZONE_SIGNAL_TFS=5`) fails boot with the other env errors. Decode of an unknown stored `signal_id` surfaces as `StoreError::Decode`, as for depletion.

## 11. Testing

**`signals::trend` unit** (host, no DB): bucket means on the JS fixture (`[10@10s, 12@12s, 20@30s]` → `[11, 11, 20]`); trailing means `[2,4,6,8]`,2 → `[2,3,5,7]`; slopes; σ of `[2,4,4,4,5,5,7,9]` = 2; classify band; too few buckets → `None`; σ = 0 → neutral; rising-then-flat series classes up then neutral; 2 h bound drops older buckets.

**`CbZoneEntryCheck` unit** (host, `MarketDataWindow` built by hand, indicators by name): rule 1 long fires with inzone=1 + trend up; rule 1 does not fire on neutral; rule 2 long fires on `low ≤ zone < close` with neutral and with up, not with down; rule 2 short mirrored; overshoot=0 vetoes; trend flag=0 vetoes; absent flag passes; absent zone → nothing; same zone value never fires twice, a new zone value fires again; 60 s gap defers (blocked at t+30 s, fires at t+61 s on the same still-true zone); both sides (two tfs) → `None` and nothing recorded; two same-side tfs → one event for the higher tf, both keys recorded; insufficient trades → `None`; `required_indicators` lists eight names per armed tf; event `signal_id` per tf.

**Orchestrator unit** (`tests.rs`, `FakeExecutorSpy` / scripted indicators, the SAR tests' shape): a `CbZoneEntry` event opens once with `timeframe: M60` for tf 60; against an opposite position it closes then opens the reverse; config: `CB_ZONE_SIGNAL_TFS` absent → empty, `15,240` → `[15,240]`, `240,15,15` → `[15,240]`, `5` → error, blank → empty, set with SAR → error; `trade_window_signal_configs` has no Mock when CB is armed.

**DTO round-trips** (`state_store::dto`, `visualizer_server::dto`): `CbZoneEntry` encodes and decodes; unknown stored id → `Decode`.

**Docker gate**: `docker compose -p cbz-test … run --build --rm test` on a fresh volume, isolated project ([project-executor-test-isolation]).

**Live check (operator, human-gated)**: restart the live executor with the new compose; within a tf candle close, the Decisions panel shows `Open Buy|Sell M15|M60|M240` rows from `cb_zone_*` only, the chart's decision markers sit on in-zone minutes, and `signal_log` carries `cb_zone_{tf}` rows with the rule and trend class.

## 12. Acceptance criteria

1. With `CB_ZONE_SIGNAL_TFS=15,60,240` and SAR unset, boot prints the three armed tfs, no SAR line and no Mock registration; every new *decision-bearing* `signal_log` row has `signal_id` ∈ {`cb_zone_15`, `cb_zone_60`, `cb_zone_240`} (the depletion/reversal checks still log decision-less rows as today).
2. Rule 1 and rule 2 fire exactly as §6 on hand-built windows, and never without a trend class.
3. One decision per (tf, side, zone value); ≥ 60 s between two from the same check.
4. The decision's `timeframe` equals the firing check's tf.
5. The Rust trend class equals the visualiser's on the shared fixtures.
6. Docker gate green; test count ≥ baseline + new tests.
