# Unfinished — executor

What is left open across the plans that have landed but are not closed out. Newest work on top. A line here means "known and deliberate", not "forgotten"; when a line is done, tick it in its own plan and delete it here.


## CB zone stop from the 15-min candle (spec [2026-10-20](specs/2026-10-20-cb-candle-stop-design.md), plan [2026-10-20](plans/2026-10-20-cb-candle-stop-plan.md))

Branch `cb-candle-stop` (worktree `trade_executor/.worktrees/cb-candle-stop`) off `layer-implementation` = `release_001` @ `1689dc5`, committed `a6a5bc6` (2026-10-20), not merged, not pushed. Replaces the order-book stop as the default for CB zone opens after the 2026-10-20 replay ([runs/2026-10-20-sl-15m-anchor-replay.md](runs/2026-10-20-sl-15m-anchor-replay.md)): the book stop sat a median 3 ticks from the entry and stopped 46/68 positions inside minutes; `stop = forming 15-min candle's low (long) / high (short) ∓ trailing mean range of the last 60 closed 1-min bars`, bars built by the check from the trades it sees (`signals::cb_stop::MinuteBars`, the feed's candle cache holds only ~15 min of kline updates). `CB_STOP_MODE=candle` (default) / `book` / `off`; `CB_STOP_ANCHOR_MINUTES=15`, `CB_STOP_RANGE_CANDLES=60`. Event + both DTOs carry `stop_anchor` / `stop_offset`. Placeholder fallback 1 % → 0.2 %. Host loop green: signals 131 (+20), local_analysis 40, execution 136, orchestrator 113 (+5), state_store 23+96, visualizer_server 17+58.

- [x] **Docker gate** on a fresh volume (`-p ccs-test`): 1549 passed / 0 failed on the tree before the last two DTO tests and the 0.2 % placeholder; rerun on the final tree stopped at the known flaky `market_data` `write_path` shutdown test (975 passed before it; no `--no-fail-fast` in the gate command), nothing else ran there -- the final tree is covered by the host loop.
- [x] **Commit** — `a6a5bc6` (2026-10-20). Merge into `layer-implementation` / `release_001` and push: open.
- [x] **Rebuild + restart** 2026-10-20 ~20:25Z (user instruction): image `cbov-check-executor` built from the `cb-candle-stop` worktree, `EXECUTION_MODE=paper docker compose -p cbov-check -f <cb-candle-stop>/docker-compose.yml up -d --no-build --no-deps executor` (env diff vs the running container was `EXECUTION_MODE` only; the API keys sit in the login shell env). Recreated while flat (previous position closed 20:21:26Z). Boot printed `cb stop armed: candle mode, anchor 15 min, offset = mean range of the last 60 closed 1-min bars (CB_STOP_MODE=candle)`. The first fire inside the first minute after boot carries no stop (no closed bar yet → placeholder, logged); the trailing mean is over fewer than 60 bars for the first hour.
- [ ] **Forward check** over a day: stop distance distribution, stop-out share (book-stop day: 68 %), `cb stop skipped` lines; then replay the day with the script's `proposed_anchor_c1_range_trail` mode against the live numbers (reproduction gate for the rule).
- [ ] Bars are in memory only (warm-up ≤ 60 min after a restart); rebuild from the `candle` table is a follow-up (spec §12).
- [x] **Placeholder 1 % → 0.2 %** (user decision 2026-10-20, `PLACEHOLDER_STOP_LOSS_PCT`): the fallback now sizes onto the notional cap like every signal stop (run report §7, spec §3). Boot/compose text updated.

---

## release_001 (2026-10-20)

Both repos have a `release_001` branch = the running paper system: trade_executor `layer-implementation` @ `1689dc5`, main/ `experimental_imp_2` (see `docs/releases/2026-10-20-release_001.md` for the rules in force, env, paper results and the branch inventory). Pushed to origin 2026-10-20; merged work branches and worktrees deleted locally.

---

## CB zone stop from the order book (spec [2026-10-19](specs/2026-10-19-cb-book-stop-design.md), plan [2026-10-19](plans/2026-10-19-cb-book-stop-plan.md))

Implemented 2026-10-19 on branch `cb-book-stop` (off `close-marker-pnl` @ `4f5ede3`), committed `88f92c4` (2026-10-20); not merged into `layer-implementation`, pushed 2026-10-20. A CB zone open's stop is the order-book level reached by `|buy − sell|` flow per minute × (frozen expected in-zone minutes − in-zone streak + 1 buffer), walked on the adverse side at fire time (`signals::cb_stop`, `CbZoneEntryCheck::with_stop`); the event carries `stop`/`inzone_streak`/`stop_minutes`/`stop_vol_rate`, the decision carries `stop`, the builder uses it only when strictly adverse to `open_price` (else the 1 % placeholder, logged). Sizing is notional-capped (`sizing::cap_to_account_limits`): a tight stop trades smaller, never `NotPlaced`. Env `CB_STOP_EXPECTED_POINTS` (compose default = main/'s frozen `15:2.0/2.0;60:3.0/3.0;240:4.0/4.0`, phase 20), `CB_STOP_VOL_WINDOW_SECS=300`, `CB_STOP_BUFFER_MINUTES=1`. Host loop green: signals 111, local_analysis 40, execution 136, orchestrator 108, state_store 22+96, visualizer_server 17+58.

- [x] **Docker gate** 2026-10-20: 1526 passed / 1 failed = the known flaky `market_data` `write_path` shutdown test (1524/0 on the pre-fix tree); baseline 1463.
- [x] **Fresh review** (opus): Critical — a stop on the walked side's touch equals the grid-rounded entry → stopped out at once (fixed: level must be strictly beyond the touch); Important — compose `:-` default defeated the blank kill switch (fixed: `${VAR-default}`, also for `CB_ZONE_SIGNAL_TFS`); Important — rate divided by the full window when the count-bounded trades cover less (fixed: per covered span, ≥ 1 min). All RED→GREEN.
- [x] **Commit** — `88f92c4` (2026-10-20).
- [x] **Rule change 2026-10-20 (user):** rate = adverse-side volume (sells for a long, buys for a short) per covered minute, not `|buy − sell|` — after the first paper run put both stops 2.5–3.5 ticks from entry (`inzone_streak` ≥ `E` → buffer minute only; net flow small). `signals::cb_stop::adverse_vol_rate`; `stop_vol_rate` on the event now means that volume. Committed `90461f7` on `cb-book-stop`; `cbov-check-executor` image rebuilt 2026-10-20 01:44 and the executor runs from it. The `streak ≥ E → buffer only` collapse itself is untouched (options: floor `minutes_left` at `E`, lookup table, min stop distance, bigger `CB_STOP_BUFFER_MINUTES`).
- [ ] Review minors, deferred: `get_account_state` now runs before the Halted check (an account-read error replaces `NotPlaced(market_closed)` on a halted market); duplicate tf entries in `CB_STOP_EXPECTED_POINTS` accepted silently (first wins); the `// 1. The MA trend…` comment in `cb_zone_entry.rs` sits above the step-0 streak block; `stop_for` is silent when `expected()` is `None` (unreachable after boot validation).
- [x] **Rebuild + operator restart** done 2026-10-20 01:44 (executor up on the rebuilt image). **Watch over a day (open):** was: `docker compose -p cbov-check build executor`, then `EXECUTION_MODE=paper … up -d --no-build executor` from the shell that holds the env. Boot prints `cb stop armed: expected points […], vol window 300 s, buffer 1 min`. Then, over a day: `cb stop skipped …` lines by reason, `cb stop fallback …` (builder re-check) lines, `size capped …` lines, and `current_stop_loss_price ≠ entry × 0.99` on CB opens in the position panel.
- [ ] **Streak after a restart** starts at 0 (wider stop until the next zone). In memory only.
- [ ] **`E` is one number per tf/side**; the results doc's `remaining_given_streak` table shows the remaining length *growing* with the streak at tf 240 — a lookup table instead of `E − streak` is a config-shape follow-up (spec §15).
- [ ] **Rule 2 walks from the last trade**, not from the zone level (spec §15).
- [ ] **Book depth** is the 1000-level REST snapshot + deltas; `DepthExhausted` expected rare, counted live.

---

## Open-time dots on the Recent Trades chart (2026-10-20)

Branch `trades-open-markers` on `cb-book-stop`, committed `1689dc5` and fast-forwarded into `layer-implementation` = `release_001` (2026-10-20). The Recent Trades price line draws entry / stop-loss / target dots from each `Opened` position event, on the trade at or before its `ts` (1–2 s after the `Open` decision arrow on the same bar). Mapping extracted to `static/js/trade_markers.js` (`TradeMarkers.build(events, points, kinds)`, `OPEN_KINDS`, host-tested, 7 tests); `chart.js` keeps only the series (`createTradeMarkerSeries(chart, kinds)`, `applyTradeMarkers` anchors on `decisionSeries` for either chart, re-run after every `setTradesChartData`); trades chart opts out of close dots/arrows (`positionCloses: false`) and lets the dots take part in autoscale (`{ autoscale: true }`, else a 1 % target sits below the pane); `pair.js` feeds the same `/api/pair_events` batch to both charts; legend extended; `pair.html` + `tests/passive.rs` list the new file. `node --test` 44/0. Verified by injecting into the live page over CDP (two sells in the 2 h window → entry 12.0345/12.0255, stop 12.037/12.029, target 11.914/11.994 on their trade points). Design 2026-09-16 §5 addendum.

- [x] **Commit** — `1689dc5` (2026-10-20, release_001).
- [ ] **Rebuild + recreate visualizer** (JS hot-copied into the running `cbov-check-visualizer-1` 2026-10-20 01:08; image rebuilt 01:12; container not recreated) (`docker compose -p cbov-check build visualizer`, then `up -d --no-build --no-deps visualizer`; its env is compose-only, no secrets).
- [ ] `tests/passive.rs::every_asset_the_spa_references_is_actually_served` not run on host (needs `TEST_DATABASE_URL`); Docker gate pending.

---

## Close marker on its candle + P&L on paper/margin closes (2026-10-19)

Branch `close-marker-pnl` on `no-trailing-advisor`, uncommitted (sixth in the stack). Two bugs seen on the paper run: (1) the chart's `Closed` dot (and every other trade marker) was placed at the event's own second, which on lightweight-charts' ordinal time scale opens a slot of its own after the candle — a close and the flip's open drew as one blob right of the 10:39 candle, where 10:40 should have been; `setTradeMarkers` now anchors each point to the candle at or before its `ts` (`DecisionMarkers.pointAtOrBefore`), keeps the batch on the chart state and re-applies it after `setChartHistory` (design 2026-09-16 §5 addendum). (2) `realized_pnl` was `NULL` on every margin/paper close (`Fill.realized_pnl` is futures-only, `settle` reports none), so the Closed Positions table showed `—`; `OpenPosition::recompute` now derives it from the fills for non-futures positions (gross of fees, `None` until an exit fills) — live margin rows get a number too (paper-mode design §4 fills row, §10). Tests: `execution::types::position_model_tests` (+5), `setup()` in `execution::tests` now stamps the executor's `market_kind` on the seeded position (the futures tests seeded margin positions). `cargo test -p execution` 128/0; JS `node --test` 33/0; marker placement verified by injecting the new `setTradeMarkers` into the live page over CDP (closed/opened points land on the 10:39 candle, no extra slots).

Also on this branch: the chart's price axis, crosshair and Entry/Stop/Target labels read at 3 decimals (`PRICE_FORMAT` in `chart.js`, every price-scale series on both charts; was lightweight-charts' 2-decimal default, which printed the 12.0645 close and 12.0675 open as one "12.06").

- [x] **Commit** — `4f5ede3` on `close-marker-pnl` (2026-10-19, squashed with trend-exit/paper/no-trailing).
- [x] **Rebuild + operator restart** (executor rebuilt 2026-10-20 01:44 carries this; visualizer image 01:12, container still the older one with hot-copied JS): `docker compose -p cbov-check build executor visualizer`, then `EXECUTION_MODE=paper … up -d --no-build executor visualizer` from the shell that holds the env. Until then the running visualizer draws the old markers and the running executor writes `NULL` P&L; rows written before the restart stay `NULL` (the number is computed at fill time, not by the view).
- [ ] The Closed Positions panel also lists the *open* position (the `position_history` view has no status filter; the row shows `Held 1s`) — not touched here.

---

## Trailing stop off (`TRAILING_FRACTION=0`, 2026-10-19)

Branch `no-trailing-advisor` on `paper-mode`, uncommitted. First paper position (`c9d1c4f6`, LINKUSDT long 11.9625, target 11.9885) was stopped out 0.00025 above entry: `DefaultPositionAdvisor` (`TRAILING_FRACTION=0.5`) moved the stop to entry + ½·(first favourable tick) and the next noise tick hit it. The throttle only bounds the *move size* (≥ 0.2 % of price, trivially true from a 1 % stop), not the profit. `TRAILING_FRACTION=0` did not mean off (candidate = entry). Now: non-positive fraction → `NoTrailingAdvisor` (stop stays where the open put it), compose default `0`; positive → trailing as before. Tests: `local_analysis::advisor` (2), `orchestrator::tests` (2). Image `cbov-check-executor:latest` rebuilt.

- [x] **Commit** — `4f5ede3` (2026-10-19).
- [ ] **Operator restart** with the rebuilt image (`EXECUTION_MODE=paper … up -d --no-build executor`); boot prints `position advisor: off (TRAILING_FRACTION=0)`.
- [ ] Option 2 (arm trailing only after the extreme passed the target) if wanted later.

---

## Paper mode (plan [2026-10-18](plans/2026-10-18-paper-mode-plan.md), spec [2026-10-18](specs/2026-10-18-paper-mode-design.md))

Implemented on branch `paper-mode` (stacked on `cb-target-trend-exit`, all uncommitted), host loop green, Docker gate 1463 / 0 (pre-fix-pass; the fix pass added one config test). `EXECUTION_MODE=paper` trades a `PaperMarketAccount` over the executor's own feed; the real adapter feeds market data only (wrapped in `NoTradeAccount`). Limit fills at its price, market at mid, stops rest (the local watcher is the stop); run-unique order ids; no fees; no P&L number on margin closes; paper positions do not survive a restart; the periodic reconcile loop is off in paper mode (TECH_DEBT §20); `MARKET_KIND=futures` refused.

- [x] **Commit** — `4f5ede3` (2026-10-19).
- [ ] **Operator restart (HUMAN GATE):** `EXECUTION_MODE=paper docker compose -p cbov-check up -d --no-build executor` from the shell that holds the keys (images must be rebuilt first: `docker compose -p cbov-check build executor visualizer`). Expect boot lines `EXECUTION_MODE=paper -- …`, `paper account armed: starting balance 100000 USDT`, `reconcile loop off (paper)`; then `Opened` → `TargetHit`/`StoppedOut` → `Closed` rows and both chart points per CB zone decision; `exchange_order.origin = 'paper'`.
- [ ] **I-19 (`working_order` ack status) is a live fix too** — carry it in the commit message; it ships with this branch.
- [ ] `PAPER_STARTING_BALANCE ≤ 0` is accepted (every open then refused at sizing); `main.rs` prints balance 0 if config and main ever disagree on the mode; a prior run's resting paper stop rows stay `New` in `exchange_order`; no engine-level empty-book retry test. Review minors, deferred.
- [ ] Real-account `OrderUpdate`s for a pair holding a paper position reach `run_position_sync` and are no-ops (spec §2 corrected).

---

## CB target + trend-flip exit (plan [2026-10-18](plans/2026-10-18-cb-target-trend-exit-plan.md), spec [2026-10-18](specs/2026-10-18-cb-target-trend-exit-design.md))

Implemented on branch `cb-target-trend-exit` (stacked on `cb-zone-entry-signal`, both uncommitted), host loop green. A CB zone open stores the firing tf's forming-candle far bound (`{tf}_cbnc_high`/`_low`) as `take_profit_price`; the position closes (`close_reason = target`) on the first opposite 1-min-MA class after its extreme traded through it. The price-only target backstop is gone. The trend class is computed once per trade in `SignalPipeline` and shared with the executor through `TrendSlot`.

- [x] Docker gate 2026-10-18: `cargo test --workspace --no-fail-fast` on a fresh volume, 1444 passed / 0 failed (baseline 1407).
- [x] **Commit** — `4f5ede3` (2026-10-19).
- [ ] **Live run (operator, HUMAN GATE).** A `cb_zone_*` open shows `take_profit_price` = that tf's `cbnc` bound; a position that traded through it closes with `close_reason = target` on the first down (long) / up (short) class; the log line `target exit …` names extreme, class, slope. Sizing still dies at `NotPlaced` until `RISK_PER_TRADE`/funding is settled.
- [ ] **`MIN_RR` in the live env** (spec §14): the "wrong-side target passes" claim assumes the compose default `0`. If the live shell sets `MIN_RR > 0`, a target near/behind the price is refused after the check consumed the zone key — add a check-side guard then.
- [ ] **Stop is still the 1 % placeholder.** `cb_low`/`cb_high` stops are the next exit spec.
- [ ] **`extreme_price` is in memory only**: a restart re-arms only from trades seen afterwards.
- [ ] **A deployment without the CB pipeline (SAR/Mock) never arms the trend-flip close**: positions ride to stop/reversal/main close. Boot prints which.

---

## CB zone entry signal (plan [2026-10-18](plans/2026-10-18-cb-zone-entry-signal-plan.md), spec [2026-10-18](specs/2026-10-18-cb-zone-entry-signal-design.md))

Implemented on branch `cb-zone-entry-signal` (uncommitted), host loop green. Supersedes the SAR flip as the open signal; compose arms `CB_ZONE_SIGNAL_TFS=15,60,240` and blanks `SAR_TEST_SIGNAL_INDICATOR`.

- [x] Docker gate on a fresh volume: 1407/3, the 3 are known timing flakes (plan 6.3).
- [x] **Commit** — `e493080` on `cb-zone-entry-signal` (2026-10-19, with decision-markers).
- [ ] **Live run (operator, HUMAN GATE).** Restart the live executor on the new compose; confirm `signal_log` rows are `cb_zone_{tf}` with rule/trend class, Decisions show `Open … M15|M60|M240`, decision markers sit on in-zone minutes. Sizing still dies at `NotPlaced (computed size exceeds account limits)` until `RISK_PER_TRADE`/funding is settled (same blocker as SAR below).
- [x] ~~Exits are still the placeholders~~ — target + trend-flip exit done (section above); the stop remains the 1 % placeholder.
- [ ] **Cross-tf reversals accepted by design** (spec §2 calls): a tf 15 fire may reverse a tf 240 position. Revisit if it churns.
- [ ] **No chart marker for `cb_zone_*` signal rows** — the decisions they produce draw as decision markers; the signal rows themselves are table/`signal_log` only.

---

## SAR flip test signal (plan [2026-09-23](plans/2026-09-23-sar-flip-test-signal-plan.md), spec [2026-09-22](specs/2026-09-22-sar-flip-test-signal-design.md))

> **Superseded as the open signal 2026-10-18** by the CB zone entry signal above; code kept, disarmed by compose default.

Layers 1–6 are implemented, merged and green: Docker gate **1037 passed / 0 failed** (baseline was 1007). Layer 7 is where it stops.

- [ ] **The last hop of the `no_trade` run is unproven.** Two flips were observed live on LINKUSDT — `Buy` (sar 13.28632 vs price 13.28700) and `Sell` on the way back — and each produced a `signal_log` row, a `decision_log` row, a `signal_firing` metric and reached `execution`. Both then died at **sizing**: `NotPlaced { "computed size exceeds account limits" }`, before `NoTradeAccount`'s refusal — which is the one thing `no_trade` exists to demonstrate. `within_account_limits` needs `free_quote × MAX_NOTIONAL_FRACTION ≥ notional`, so at `RISK_PER_TRADE=0.5` (notional $50, `MAX_NOTIONAL_FRACTION=0.5`) it needs **≥ $100 free USDT on cross margin**. Unblock by funding the sub-account, or accept the hop as covered by unit tests only.
- [ ] **Spec §11.4's acceptance criterion is not met.** It asks for one full `Open → flip → Close → Open(reverse)` cycle with position-state rows and the visualiser rendering it. No position ever opened, so close-then-reverse has only ever run against `FakeExecutorSpy`, never against a real fill.
- [ ] **Layer 7.2, the live run, has not started (HUMAN GATE).** Decide `RISK_PER_TRADE` deliberately first: `compute_size` is `RISK_PER_TRADE / |entry − stop|` against a flat 1% stop, so **notional = 100 × RISK_PER_TRADE** regardless of price. The committed default of `100` therefore asks for a $10,000 position from a signal whose exits are two placeholder constants.
- [ ] **`MIN_RR=0` is deployment-wide.** Committed to `docker-compose.yml` for this test (spec §9): it disables the R:R gate for *every* decision path in that deployment, including the depletion signals and anything `main/` sends over MQ. Any deployment doing more than this test needs its own value.
- [ ] **`main/`'s full suite has not been run against this change.** Its config tests pass on the host (7/7, RED before the YAML entry), but 21 modules cannot be collected there — no `optuna`, `plotly`, `zmq`. The `simple_trader` image now exists locally, so `docker compose run --rm live python3 -m pytest tests/ -q` is runnable.
- [x] ~~Paper mode is still not wired~~ — wired 2026-10-18 (section above): `boot` keeps the handed-in account for ingestion and builds the paper account for execution.
- [ ] **Replay of an indicator-driven signal is unsupported** (spec §13). Expiry is judged against wall-clock time, so `replay_harness` passes `NoIndicators` permanently: no reading, no flip. A replayable source (`as_of` driven by the replayed event's own time) is its own change.
- [ ] **Statuses.** Spec header still says `draft — awaiting user review`; the plan's layer checkboxes are unticked.

---

## Live trade-ops (plan [2026-09-22](plans/2026-09-22-live-trade-ops-plan.md), spec [2026-09-22](specs/2026-09-22-live-trade-ops-l0-test-design.md))

Carried over verbatim from that plan's Task 7.6. The branch itself is merged into `layer-implementation` (`125a7f3`); which of its Tasks 7.2–7.5 human-gated runs completed is not recorded — their boxes are unticked.

- [ ] Tick L0 Stage 1 checkboxes named in the spec header in [specs/layers/L0-exchange-adapter.md](specs/layers/L0-exchange-adapter.md), with run dates.
- [ ] Spec status → `implemented 2026-…`; that plan's status line.
- [ ] `TECH_DEBT.md` §7 (`order_event.order_id` bigint) stays open — not fixed there.
