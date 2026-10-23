# CB zone stop from the order book (replaces the 1 % placeholder stop) — Design Spec

Date: 2026-10-19
Status: **ARCHIVED 2026-10-21.** Superseded as the default by the 15-min candle stop ([2026-10-20-cb-candle-stop-design.md](2026-10-20-cb-candle-stop-design.md)): the forming extreme ± trailing mean 1-min range, chosen by the user as the better option; no further work on this rule. The code is on `layer-implementation` (`88f92c4`, `90461f7` adverse-side volume rate; pushed) behind `CB_STOP_MODE=book`; branch `cb-book-stop` folded in and deleted. Original status: implemented 2026-10-19 on branch `cb-book-stop` (off `close-marker-pnl` @ `4f5ede3`), commits `88f92c4` + `90461f7` (adverse-volume rate) 2026-10-20, fast-forwarded into `layer-implementation` = `release_001` @ `1689dc5` — host loop green (signals 111, local_analysis 40, execution 136, orchestrator 108, state_store 22+96, visualizer_server 17+58, mq_gateway 42, visualizer_backend 23, cli 7); Docker gate 1526 passed / 1 known-flaky (`write_path` shutdown timing) on a fresh volume, 1524/0 pre-fix; fresh review (opus) → 1 Critical + 2 Important fixed RED→GREEN (stop on the touch = rounded entry price; compose `${VAR-default}` kill switch; rate per covered span), 4 minors deferred to UNFINISHED; compose default carries the frozen `15:2.0/2.0;60:3.0/3.0;240:4.0/4.0`; operator restart pending**
Target project: `trade_executor` (worktree `layer-implementation`; the branch chain `decision-markers` → `cb-zone-entry-signal` → `cb-target-trend-exit` → `paper-mode` → `no-trailing-advisor` → `close-marker-pnl` is committed first (§14), new branch `cb-book-stop` on top of `close-marker-pnl`) — L2 `signals` (`CbZoneEntryCheck` computes the stop at fire time, event carries it), L2 `local_analysis` (`DecisionContext`/`SignalBuilder` take an explicit stop), L4 `execution` (`TradeDecision.stop`), L5 `state_store` / `visualizer_server` DTOs, orchestrator config/boot/dispatch, L9 compose. One `main/` prerequisite: the frozen numbers from [`external/docs/superpowers/specs/2026-10-19-cb-zone-run-stats-design.md`](../../docs/superpowers/specs/2026-10-19-cb-zone-run-stats-design.md).
Supersedes: `PLACEHOLDER_STOP_LOSS_PCT` (1 %) as the *stop* for positions opened by the CB zone entry. The placeholder stays as the fallback and for every other open path.
Related: [2026-10-18-cb-zone-entry-signal-design.md](2026-10-18-cb-zone-entry-signal-design.md) (the open signal; this follows its shape), [2026-10-18-cb-target-trend-exit-design.md](2026-10-18-cb-target-trend-exit-design.md) (the target travels on the event the same way the stop will), [2026-09-17-volume-book-depletion-signal-design.md](2026-09-17-volume-book-depletion-signal-design.md) §4.1 (the order-book walk this reuses: `signals::depletion::project_target_price`), [2026-09-22-position-management-design.md](2026-09-22-position-management-design.md) (stop watcher, `compute_size`).

## 1. Why

A CB zone open today gets a stop 1 % from the entry — a number that lets a decision reach the exchange, not a risk rule (`builder.rs` says so). The zone itself tells how long the episode should last: main/ measured how many consecutive minutes price typically stays inside a zone per tf and side. The executor knows how many of those minutes have already passed (its in-zone streak), how much net volume is hitting the market right now, and what the live order book will absorb. Put together: the stop sits where the book says price would be pushed to if the current net flow kept going for the minutes the zone has left, plus one minute of safety.

## 2. The rule, as the user stated it (2026-10-19)

1. **tf**: the firing zone's tf. When several tfs fire together the biggest wins — the entry check already reports the highest tf (entry spec §2 calls), so the stop uses that one.
2. **expected points** `E[tf, side]`: main/'s statistic of in-zone minutes per zone block, frozen (user decision 2026-10-19: frozen, not broadcast).
3. **vol_diff** (superseded 2026-10-20, user decision): the **adverse-side volume** over a trailing window — sell qty for a long, buy qty for a short. Was `|Σ buy qty − Σ sell qty|` (the first paper run showed stops 2–4 ticks away; the net difference understates the flow pushing against the position).
4. **streak**: how many in-zone minutes in a row the pair has now.
5. **minutes_left** = `max(E − streak, 0) + 1` (one minute safety buffer).
6. **stop** = the price the order book gives when `vol_diff` per minute × `minutes_left` is walked against the position's adverse side (long: bids downward; short: asks upward).

Calls made by the author (not asked of the user; flagged for review):

| Question | Call |
|---|---|
| vol_diff window | Trailing **5 min** of `recent_trades` (`CB_STOP_VOL_WINDOW_SECS`, default 300) — the depletion signal's `avg_window`. Rate = adverse-side qty / minutes covered, per minute, so the walk's `rate × minutes_left` is in trade qty. |
| Which number of main/'s is `E` | **Median (p50) block run length over `cb_inzone ∧ cb_f_overshoot` minutes, 2y** — user decisions 2026-10-19, run-stats spec §2 set C / §4. Mean, the raw set, the entry-filter set and first-block length are in that results doc for a later switch; the executor only ever sees six numbers. |
| Where the stop is computed | **In `CbZoneEntryCheck` at fire time**, on the event, exactly as the target is (`target` on the event → `TradeDecision.target` → `DecisionContext.target` → builder). The check has the trade window (vol_diff), the indicator readings (streak), and — via `SignalFactory::create(config, feed)` — the feed for `order_book`, which `VolumeBookDepletionCheck` already takes the same way. `DefaultSignalBuilder` stays I/O-free. |
| Streak source | **The check's own state**, not the `indicators` table: per `(tf, side)` it remembers the first and last exchange-time minute of the current run of `{tf}_cb_inzone_{side} == 1` readings, and the zone value the run belongs to (§5). After a restart the streak restarts from the first reading seen — the stop is then wider than it should be (more minutes left), which is the safe direction. |
| Stop vs the actual entry price | The check judges "adverse" against the last trade; the executor prices the entry at the book mid, after DB writes and, on a reversal, a close leg plus the flat wait. **The builder re-checks** `ctx.stop` against `open_price` (long: `stop < open`, short: `stop > open`) and falls back to the placeholder with a log line when it fails (§8.3). A reversal keeps the fire-time stop; the re-check is what protects it. |
| Rule 2 (zone rejection) fires | The previous minute touched the zone; the current one may not be in it. streak = the run that ended in the previous minute if there is one, else 0 → `minutes_left = E + 1` at most. |
| Book depth exhausted / rate zero / stop not strictly adverse | **No stop on the event** (`None`); the builder uses the 1 % placeholder; one log line says which of the three happened. Never an extrapolated stop (depletion spec §4.1's rule). |
| Stop tighter than the placeholder | Used as computed. A tight stop makes `compute_size = RISK_PER_TRADE / |entry − stop|` large (§10). |
| Stop wider than the placeholder | Used as computed. No cap in this spec; `MAX_NOTIONAL_FRACTION` / account limits still bound the notional. |
| Stop on the touch (review, 2026-10-20) | The walked side's **touch** (best bid for a long, best ask for a short) is never a stop: the entry limit is the mid rounded onto the grid, which on a one-tick spread *is* the touch, so a stop there is a stop on the fill price. `compute_stop` requires the level strictly beyond both the last trade and the touch; otherwise `NotAdverse` → placeholder. |
| Vol rate on a count-truncated window (review, 2026-10-20) | The 6 000-trade window may not reach back the full `vol_window` in a burst; the rate is per minute of the span the trades actually cover (floored at one minute), not per full window. |
| `E` missing for an armed tf | Config error at boot (half-configured). `CB_STOP_EXPECTED_POINTS` absent entirely = feature off: the event carries no stop, nothing else changes. |
| Trailing stop / stop watcher | Unchanged. `TRAILING_FRACTION=0` is the live default (`NoTrailingAdvisor`); with a positive fraction the advisor trails from this stop as it trailed from the placeholder. |

## 3. Scope

In: `CbStopParams` + stop computation in `signals` (`CbZoneEntryCheck`, a small pure module `cb_stop`), `SignalEvent::CbZoneEntry` gains `stop` + audit fields; `TradeDecision.stop`, `DecisionContext.stop`, `DefaultSignalBuilder` uses it (with the adverse re-check); notional-capped `compute_size` in `execution` (§10); orchestrator env, config, boot, dispatch; `state_store` and `visualizer_server` DTO mirrors; compose defaults; tests; UNFINISHED/plan updates.

Out: `main/` code (the measurement is its own spec); moving the stop after open (advisor unchanged); any cap or floor on the stop distance; sizing (§10 flags it); persistence of the streak; a chart line for the stop (the position panel shows `current_stop_loss_price` already); SAR/Mock opens (they keep the placeholder); replay-harness support (same gap as the entry signal).

## 4. The data this reads

- `MarketDataWindow::indicators`: `{tf}_cb_inzone_{side}` (already in `names_for(tf)`; nothing new is fetched).
- `MarketDataWindow::recent_trades` (oldest first, 6 000-bounded): `TradeTick { price, qty, side, ts }` for vol_diff; `window.now` for the minute.
- `MarketDataFeed::order_book(pair) -> OrderBookSnapshot { bids, asks, sequence, ts }` — the live book, read once at fire time, after every other rule has passed (one snapshot per fire, not per trade).
- Config: `CbStopParams { expected_points: HashMap<(u32, Side), Decimal>, vol_window: Duration, buffer_minutes: Decimal }` (`Side` derives no `Ord`; a `HashMap` or a `(u32, bool)` key, builder's choice).

## 5. The streak (`cb_stop::Streaks`, owned by the check's `State`)

Per `(tf, side)`: `Option<Run { zone: Decimal, start_minute: u64, last_minute: u64 }>`, minutes = `floor(window.now / 60 s)` in exchange time (same clock as `previous_minute_candle`).

On every `check()` call (once per trade, not per minute), for every armed `(tf, side)`, before the entry rules, with `m = now_minute`, `zone = {tf}_cb_zone_{side}` and `in_zone = {tf}_cb_inzone_{side} == 1`:

- `in_zone` and (no run, or `run.zone ≠ zone`, or `last_minute < m − 1`) → new run `{zone, start: m, last: m}`.
- `in_zone` and `run.zone == zone` and `last_minute ∈ {m − 1, m}` → `last_minute = m`.
- not `in_zone` → the run is left as it is (it ends by itself when the next in-zone minute is not adjacent, or when the zone value changes).

`streak_at(m)` = `last − start + 1` if `last ≥ m − 1`, else `0`. A run never spans two zone values — a new tf candle has a new zone — which is the same boundary main/'s measurement uses (run-stats spec §2, blocks bounded by the candle), so the live streak and the frozen `E` count the same thing. A reading that is absent (expired, never sent) counts as not in zone. One minute of granularity: main/ computes `cb_inzone` on the forming 1-min candle and publishes a flip within the minute (`on_change`), the 30 s heartbeat repeats it; a flag that flips to 1 late in a minute still counts that minute. Because the counter only advances on trades, a minute with no trade at all ends the run (LINKUSDT trades every minute; a quieter pair would under-count the streak, which widens the stop — the safe direction). The streak is therefore within ±1 minute of main/'s own row count; the buffer minute covers it.

## 6. The stop (`cb_stop::compute_stop`, pure)

```
compute_stop(side, streak, expected, buffer, vol_rate_abs, book, price) -> Result<StopReading, StopSkip>

minutes_left = max(expected − streak, 0) + buffer            // Decimal, may be fractional
signed_rate  = long: −vol_rate_abs, short: +vol_rate_abs      // walk bids for a long, asks for a short
(level, _)   = project_target_price(signed_rate, minutes_left, book, price)?   // returns Option<(price, Side)>
```

- `vol_rate = Σ adverse-side qty / covered minutes` over trades with `ts ∈ [now − vol_window, now]` (`adverse_vol_rate(side, ..)`: sells for a long, buys for a short; user decision 2026-10-20, was `|Σ_buy − Σ_sell|`); no trade in the window → `StopSkip::NoTrades`; no adverse-side volume → `StopSkip::ZeroRate`.
- `project_target_price` returns `None` (visible depth exhausted) → `StopSkip::DepthExhausted { cumulative_target, levels }`.
- `Some((level, _))` with `level ≥ price` for a long or `level ≤ price` for a short (the top of book sat on the last-trade price and held the whole target) → `StopSkip::NotAdverse`. `price` here is the **last trade**, not the entry: the executor prices the entry at the book mid later (§8.3 re-checks against the real `open_price`; `DefaultRiskValidator` reads the side off the stop, so a stop on the wrong side of the entry would flip the side).
- Otherwise `StopReading { stop: level, streak, minutes_left, vol_rate: vol_rate_abs, book_ts: book.ts, levels_walked }`.

`project_target_price` is reused as is: it already sorts defensively, filters each side to the levels beyond `price`, and stops at the level whose cumulative qty reaches the target (no interpolation). The stop is that level's own price — a stop-market trigger at the price the book says would be reached.

## 7. The check (`CbZoneEntryCheck`, changes to entry spec §6)

- `CbZoneEntryCheck::new(tfs, min_interval)` keeps its signature; `with_stop(params: CbStopParams, feed: Arc<dyn MarketDataFeed>) -> Self` arms the stop (`None` by default — the factory calls it when the config carries params). `SignalConfig::CbZoneEntry { tfs, min_interval, stop: Option<CbStopParams> }`.
- Per `check()`: step 0 (new) updates the streaks from this trade's readings for every armed `(tf, side)`. Steps 1–6 unchanged. Step 7, after `best` is chosen and **before** the fire is recorded: if the stop is armed, `expected = params.expected_points[(best.tf, best.side)]`, `streak = streaks.streak_at(now_minute)`, `vol_rate` from the window, `book = feed.order_book(pair)`, `compute_stop(...)`. `Ok` → the event carries `stop: Some(level)` and the reading's audit fields; `Err(skip)` → `stop: None`, one `eprintln!` line `cb stop skipped {pair} cb_zone_{tf} {side}: {skip}` (the workspace's logging convention — `volume_book_depletion.rs` explains why). The fire itself is never blocked by the stop: an open without a book stop gets the placeholder, as today.
- `SignalEvent::CbZoneEntry` gains `stop: Option<Decimal>`, `inzone_streak: u32`, `stop_minutes: Option<Decimal>`, `stop_vol_rate: Option<Decimal>` — `Option`/`default` so rows stored before this build decode (§9). `inzone_streak` is always set (0 when the stop is not armed).
- Boot log line: `cb stop armed: E=15:L/S 60:L/S 240:L/S, vol window 300 s, buffer 1 min` or `cb stop off`.

## 8. Decision → builder (mirrors the target path, trend-exit spec §5)

1. `run_signal_decision_task` builds the open `TradeDecision` with `stop: event.stop` for `CbZoneEntry`, `None` for every other event; the reversal's close leg carries `None`.
2. `execution::TradeDecision` and `local_analysis::DecisionContext` gain `stop: Option<Price>`; `handle_decision` copies it into the context. `TradeDecisionDto` gains `#[serde(default)] stop: Option<Decimal>`.
3. `DefaultSignalBuilder::build_signal`, `DecisionKind::Open`: `stop_loss_price = ctx.stop` **if it is strictly adverse to `open_price`** (long: `stop < open_price`; short: `stop > open_price`), else the placeholder, with one log line naming the decision, the stop and the open price when it falls back. The entry is priced at the book mid after the fire (DB writes, and on a reversal the close leg plus the flat wait), so a stop one level from the last trade can have crossed the entry by then; the placeholder is derived from `open_price` and never could. The target logic is unchanged.
4. Risk validation (`DefaultRiskValidator`): unchanged. Stage 1's R:R uses the new stop; with the compose default `MIN_RR=0` every stop passes. Stage 2 (level-supported stop search) only runs when stage 1 fails, as today.
5. Sizing, `open_position`, `OpenPosition::new(.., stop_loss_price, ..)`, the stop watcher, persistence: unchanged — the stop lands in `stop_loss_price` / `current_stop_loss_price`, which `position_state`/`position_log` persist and the visualiser shows.

## 9. Persistence and DTOs

- `state_store::dto::SignalEventDto::CbZoneEntry` and the `visualizer_server` mirror gain `stop`, `inzone_streak`, `stop_minutes`, `stop_vol_rate`, all `serde(default)` (`inzone_streak` defaults to 0). Round-tripped.
- `state_store::dto::TradeDecisionDto.stop: Option<Decimal>` (`serde(default)`), round-tripped.
- No schema change (`signal_log` / `decision_log` payloads are `jsonb`).

## 10. Orchestrator, config, compose (L9)

Env (all optional; the first one gates the feature):

| Var | Meaning | Default |
|---|---|---|
| `CB_STOP_EXPECTED_POINTS` | `15:L/S;60:L/S;240:L/S` — `E` per tf, long/short, decimals, e.g. `15:4/3.5;60:12/10;240:40/32` | blank = **off** until the run-stats results doc lands; then the six frozen values become the compose default |
| `CB_STOP_VOL_WINDOW_SECS` | vol_diff trailing window | `300` |
| `CB_STOP_BUFFER_MINUTES` | the safety buffer | `1` |

Parse into `OrchestratorConfig::cb_stop: Option<CbStopParams>`. Errors: a tf other than 15/60/240; a tf listed in `CB_ZONE_SIGNAL_TFS` missing from the map (half-configured); non-positive `E`; a window < 60 s. Set while `CB_ZONE_SIGNAL_TFS` is blank → accepted and ignored with a boot line (nothing fires). Boot passes `cb_stop` into `SignalConfig::CbZoneEntry` for the CB pipeline; the factory hands the feed to the check.

**Sizing (flagged — the user's decision, §14):** `compute_size = RISK_PER_TRADE / |entry − stop|` and `within_account_limits` compares the notional `size × open_price` with `free_quote × MAX_NOTIONAL_FRACTION`, so the open is refused `NotPlaced` when `|entry − stop| < open_price × RISK_PER_TRADE / (free_quote × MAX_NOTIONAL_FRACTION)` — on paper (`100 000 × 0.5`, `RISK_PER_TRADE=100`, LINK ≈ $12) below ≈ 0.024, i.e. ~24 ticks. A book level reached by one or two minutes of net flow is typically a few ticks away, and a refusal comes *after* the check has consumed the zone key (same failure mode the trend-exit spec §14 flags for `MIN_RR > 0`), so that candle never re-fires. With `DepthExhausted` → placeholder on the long horizons (E ≈ 40 min at tf 240), the likely live picture without a guard is "tight stops refused, wide stops placeholder". **User decision (2026-10-19): notional-capped size.** `compute_size` becomes `size = min(RISK_PER_TRADE / dist, free_quote × MAX_NOTIONAL_FRACTION / open_price)` (quantised to the venue's lot step as today); `within_account_limits` then holds by construction and an open is never refused for a tight stop. The risk actually taken is `size × dist ≤ RISK_PER_TRADE`; the open's log line prints both the uncapped and the capped size when the cap bit. Applies to every open (SAR/Mock too): the cap is a property of the account, not of the signal. Tests in `execution::sizing`: a stop 2 ticks away on paper gives the capped size, not `NotPlaced`; a wide stop gives the uncapped size unchanged; the cap at exactly the limit places.

The live executor is **not** recreated by this work ([feedback: never recreate the live executor from my shell]); the operator restarts it.

## 11. Error handling

The stop never blocks a fire and never panics: every skip reason (§6) collapses to "no stop on the event, placeholder in the builder" with one log line. A config error fails boot with the other env errors. Decode of old rows yields `None` / 0. The book snapshot is read once per fire; an empty book (feed without depth — the test `ChannelFeed`) is `DepthExhausted`.

## 12. Testing

**`cb_stop` unit** (host, hand-built books, no I/O): long with bids `[99.9×5, 99.8×5, 99.7×10]`, rate 2/min, E=4, streak=1, buffer 1 → target 8 → stop 99.8; short mirrored on asks; streak ≥ E → `minutes_left = buffer` only; fractional E; depth exhausted → `DepthExhausted`; zero rate → `ZeroRate`; no trade in window → `NoTrades`; bid at the trade price holding everything → `NotAdverse`; unsorted book gives the same answer (the walk sorts).

**`Streaks` unit**: three consecutive in-zone minutes → 3; a gap of one minute restarts; a 0 reading leaves the run, next adjacent 1 extends it; absent reading = not in zone; `streak_at` is 0 when the run ended two minutes ago; per `(tf, side)` independence.

**`CbZoneEntryCheck` unit** (existing window-by-hand tests + feed stub with a scripted book): armed stop → event carries `stop`, `inzone_streak`, `stop_minutes`; not armed → `stop: None`, `inzone_streak` still counted; stop skip (empty book) → fires with `stop: None`; the streak is read for the *firing* tf/side; rule 2 fire uses the previous minute's run; the book is read once per fire (spy counts `order_book` calls).

**`local_analysis` unit**: `build_signal` Open with `ctx.stop = Some(s)` strictly adverse → `stop_loss_price == s`; `Some(s)` on or beyond `open_price` (long `s ≥ open`, short `s ≤ open`) → placeholder; `None` → placeholder (existing tests unchanged).

**Orchestrator unit**: config parse (`15:4/3.5;60:12/10;240:40/32` → map; missing armed tf → error; `5:…` → error; blank → `None`; window 30 → error); a `CbZoneEntry` event with `stop` opens with `TradeDecision.stop == Some(stop)`; the reversal close leg and SAR/Mock paths carry `None`; boot prints the armed line.

**DTO round-trips** (`state_store`, `visualizer_server`): `TradeDecisionDto` and `SignalEventDto::CbZoneEntry` with and without the new fields (a JSON blob lacking them decodes).

**Docker gate**: `docker compose -p cbs-test … run --build --rm test` on a fresh volume, isolated project ([project-executor-test-isolation]).

**Live check (operator, human-gated, paper mode):** after a restart with the frozen `CB_STOP_EXPECTED_POINTS`, a `cb_zone_*` open shows `current_stop_loss_price` ≠ entry × 0.99 in the position panel, the `signal_log` row carries `stop`, `inzone_streak`, `stop_minutes`, and the boot line names the six values. Over a day: count of `cb stop skipped` lines by reason, and of `NotPlaced` opens caused by size (§10).

## 13. Acceptance criteria

1. With the stop armed, every position opened from `cb_zone_{tf}` whose event carries `stop` has `stop_loss_price == stop`; one whose event carries `None` has the placeholder, and the log says why.
2. `compute_stop` on hand-built books gives §6's numbers exactly; no skip reason ever becomes a stop.
3. The streak equals the number of adjacent in-zone minutes ending at or before the fire's minute, per `(tf, side)`, within one minute of main/'s row count.
4. Target, trend-flip exit, trailing advisor, stop watcher, reversal, paper fills: behaviour and tests unchanged.
5. Rows stored before this build decode.
6. Docker gate green; test count ≥ baseline + new tests.

## 14. User decisions (2026-10-19)

| Question | Answer |
|---|---|
| §10 sizing guard | **(a) notional-capped size.** Written into §10. |
| Branch base | **Commit the chain first**: `decision-markers` → `cb-zone-entry-signal` → `cb-target-trend-exit` → `paper-mode` → `no-trailing-advisor` → `close-marker-pnl`, one commit per branch, each described to the user before it is made; `cb-book-stop` then branches from `close-marker-pnl`'s commit and has a diff and a test baseline of its own. |
| Frozen `E` | The run-stats results doc is awaited; nothing ships with oos2m-only numbers. If the 2y run fails, it is retried (memory step, §3 of the run-stats spec), not replaced. |

**Book depth (recorded 2026-10-19):** both adapters seed the book from a REST snapshot with `limit=1000` levels per side (`exchange_adapter_mexc/src/ws.rs` `fetch_depth_snapshot`, `exchange_adapter_binance/src/ws.rs`) and apply WS deltas on top (MEXC `spot@public.aggre.depth.v3.api.pb@100ms`), so the visible depth is up to 1000 levels, not a 20-level partial book. With the frozen `E` (2–4 minutes) the walked qty is a few minutes of net flow; `DepthExhausted` should be rare. The live check (§12) counts it.

## 15. Follow-ups (not blocking)
- Whether `E` should instead be the `remaining_given_streak` lookup the run-stats script reports (a table per `(tf, side)` instead of one number) — config shape change only.
- Whether the book walk should start at the zone level rather than the last trade price for a rule-2 fire (price has already left the zone).
- Streak persistence across restarts (today: restarts at 0, stop wider).
