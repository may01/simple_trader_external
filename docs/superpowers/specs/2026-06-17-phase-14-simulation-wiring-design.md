# Phase 14 — Simulation / Strategy / Signal Wiring (Design)

**Date:** 2026-06-17
**Status:** Approved
**Plan:** `plans/impl_2/phase-14-simulation-wiring/`

---

## Problem

Phases 04–12 built every layer (signals, strategies, position, robot, orchestrator, frontend) in isolation, validated only with `ExampleStrategy*` plumbing stubs. Nothing runs end-to-end with real entry/exit logic, nothing records *what happened* during a run, and the chart cannot show a simulation's trades.

This phase wires the existing layers into one working backtest path and makes a run observable: concrete test strategies, an **Action** record capturing every position change and signal firing, per-simulation on-disk storage keyed by a simulation id, a simulation report, and an action overlay on the `full_view` chart.

This phase **extends existing layers** — it does not introduce a new bottom layer. Task order stays bottom-up so each integration boundary is RED before the layer above it is touched.

---

## Requirements

| # | Requirement |
|---|-------------|
| 1 | Test strategies with simple open/close signals (EMA cross long; RSI zone_class long) |
| 2 | Mirror strategies for short |
| 3 | Position changes + signal firing produce Action records (opened / closed / stop-loss; signal fired; price provided from strategy to position) |
| 4 | Actions from the latest simulation shown on the `full_view` graph |
| 5 | Simulation runs the defined strategies over the dataset |
| 6 | Position tracks its changes and logs them |
| 7 | Simulation report |
| 8 | Each simulation carries an id number |
| 9 | Each set of actions stored in a folder keyed by the simulation id |

---

## Resolved design decisions

These were settled during brainstorming and override the first-draft task files where they differ:

1. **No new signal primitives.** EMA cross reuses `Cross_Up_Signal` / `Cross_Down_Signal`; RSI zone reuses `Cross_Up_Val_Signal` / `Cross_Down_Val_Signal` against `zone_class` (integer tier 0..4, 0 = oversold, 4 = overbought) at half-integer thresholds. Reuse over new code.
2. **Attribution = action type only.** The `Action` record carries `action_type` (a `STRATEGY_ACTION_*` constant) and prices, but **no** strategy-class name and **no** signal-chain name. This avoids widening the `StrategyManager`/`Strategy` `check()` 5-tuple and leaves Phase 07/08 callers + tests untouched.
3. **All 4 strategies run in one simulation.** One sim id, one folder. Accepted consequence: simultaneous competing OPENs from different strategies resolve to `NOTHING` (existing `StrategyManager._resolve` rule), so executed trades may be sparse. This is acceptable for test/inspection strategies.
4. **SIGNAL_FIRED captures pre-resolution firings.** Because (3) suppresses many firings, `StrategyManager` exposes the raw list of fired action **types** (no names — consistent with decision 2) so every strategy firing is recorded as a `SIGNAL_FIRED` action even when conflict-resolution discards it. This is per-tick scratch state, overwritten each tick — it does **not** violate the "no state between ticks" constraint.
5. **Action model lives in `backtesting/`**, not `position/`. Position is a lower layer than backtesting and must never import it — Position emits plain dicts; the robot maps them to `Action`s.
6. **`profit_factor = inf`** is serialised to JSON as the string `"inf"`, never raw `float('inf')` (strict parsers reject it).
7. **Frontend reads the newest simulation by id**, not by file mtime — id ordering is the source of truth.

---

## Architecture & data flow

```
TestStrategyFactory → StrategyManager(4 strategies)
                          │ check() → resolved 5-tuple
                          │ last_fired: list[str]  (pre-resolution action types, scratch)
                          ▼
TrainRobot.step(dp) ──► dispatch buy/sell/wait ──► Position (appends change_history dicts)
   │                                                     │
   │  drain_changes() ◄──────────────────────────────────┘
   ▼
   assembles Action records  →  ActionLog(sim_id)
                          ▼
SimulationOrchestrator: allocate sim_id once → thread to all workers →
   merge worker ActionLogs (crossing the process boundary as JSONL strings) →
   write sim_<id>/actions.jsonl + report.json
                          ▼
Frontend view_full → load newest sim_<id>/actions.jsonl → draw markers on price chart
```

---

## Components

### Strategies — `strategies/` (Task 01)

Four strategies on `tf=5`, each overriding only `register_signals()` and `check_conditions()` (price methods delegate to `Strategy` base defaults):

- `StrategyTest1Long` — entry `Cross_Up_Signal(5,"ema_7","ema_14")` → OPEN_LONG; exit `Cross_Down_Signal(...)` → CLOSE_LONG
- `StrategyTest1Short` — mirror (entry on cross-down → OPEN_SHORT; exit on cross-up → CLOSE_SHORT)
- `StrategyTest2Long` — entry `Cross_Up_Val_Signal(5,"zone_class",0.5)` (leaves oversold) → OPEN_LONG; exit `Cross_Up_Val_Signal(5,"zone_class",3.5)` (enters overbought) → CLOSE_LONG
- `StrategyTest2Short` — entry `Cross_Down_Val_Signal(5,"zone_class",3.5)` (leaves overbought) → OPEN_SHORT; exit `Cross_Down_Val_Signal(5,"zone_class",0.5)` (enters oversold) → CLOSE_SHORT

`TestStrategyFactory(fee)` — top-level picklable class (crosses `ProcessPoolExecutor`); `__call__` registers all four into a fresh `StrategyManager(fee)`.

### Action model — `backtesting/action.py` (Task 02)

`@dataclass Action`, concrete scalar fields only (JSONL round-trip lossless):

`sim_id, timestamp, tick_index, event, action_type, position_type, was_stop_loss, target_price, executed_price, stop_loss_price, revenue_pct, revenue_abs`

- `event` ∈ `OPEN | CLOSE | STOP_LOSS | MOVE_STOP_LOSS | SIGNAL_FIRED`
- `event` = lifecycle category (what happened to the position); `action_type` = the strategy intent constant
- `target_price` = price the strategy provided to the position; `executed_price` = simulated fill
- `revenue_*` set only on CLOSE / STOP_LOSS, else `0.0`

`ActionLog(sim_id)` — `record()` (asserts matching sim_id), `to_jsonl()`, `extend()`, `__len__`. No file I/O — persistence is the orchestrator's job.

### Position change log — `position/base_position.py` (Task 03)

- `change_history: list[dict]` (init `[]`); `_record_change(kind, target_price, executed_price, was_stop_loss=False, revenue_pct=0.0, revenue_abs=0.0)`; `drain_changes()` returns + clears.
- Wired into `open` (kind OPEN), `set_stop_loss` (MOVE_STOP_LOSS, only on actual update), `close` (CLOSE, `was_stop_loss` when `STRATEGY_ACTION_DO_STOP_LOSS`), `finalize` (settle realised P&L onto the trade's close event).
- **No import of `backtesting.action`.** `change_history` must survive `finalize()`'s state reset (added to the do-not-reset list); `to_dict`/`from_dict` need not serialise it.

### StrategyManager pre-resolution list — `strategies/strategy_manager.py` (Task 04)

- New attribute `last_fired: list[str]` set inside `check()` to the action types collected before `_resolve`. `check()` signature and 5-tuple return unchanged → live `robot.py` caller untouched. Overwritten each tick (scratch, not cross-tick state).

### TrainRobot Action assembly — `robots/train_robot.py` (Task 04)

- Owns `action_log: ActionLog`; `set_sim_context(sim_id)` (default `sim_id=0` for standalone); internal `tick_index` incremented per `step()`.
- After dispatch in `_do()`:
  - for each action type in `strategy_manager.last_fired`: record a `SIGNAL_FIRED` Action (carries `action_type`, strategy-provided `target_price`, `stop_loss_price`)
  - drain `position.drain_changes()` **after** `_finalize()` and map each `kind → event`, filling `executed_price` from the fill and `revenue_*` from the settle change
- `get_action_log()`. Recording wrapped in the existing `step()` try/except — never crashes the sim. `data_point` never stored as an attribute.

### Simulation id + storage — `helpers.py`, `backtesting/simulation_orchestrator.py` (Task 05)

- `helpers.simulation_folder(sim_id)` = `f"{action_folder()}sim_{sim_id}/"`; `helpers.next_simulation_id()` = `max(existing sim_<n>) + 1`, `1` when none.
- Orchestrator: allocate `sim_id` **once** per `run()`; pass to every worker → `robot.set_sim_context(sim_id)`. Workers return `action_log_jsonl` (strings cross the process boundary). `_persist_actions` concatenates in segment (chronological) order → `sim_<id>/actions.jsonl` (`os.makedirs(exist_ok=True)`). Worker crash → skip its (empty) log, don't abort. `run_single` mirrors id + persistence. `next_simulation_id` race acceptable (single backtest driver).

### Simulation report — `backtesting/simulation_report.py`, `training/trainer.py` (Task 06)

- `SimulationReport(sim_id, metrics, action_counts, context)` → `to_dict()`, `write(folder)` → `report.json` (pretty), `action_counts_from_jsonl(jsonl)` tallies events.
- `metrics` from `PerformanceAnalyzer.analyze()`; `context` = `{strategy_set, pair, begin_ts, end_ts, step_min, num_workers, fee}`.
- Writer asserts `metrics.total_trades == CLOSE + STOP_LOSS counts` (catches wiring drift). `inf` → `"inf"`. Report lives in the same folder as `actions.jsonl`.
- `trainer._run_simulate`: `factory = TestStrategyFactory(fee) if os.environ.get("STRATEGY_SET")=="test" else _DefaultStrategyFactory(fee)`; record `sim_id` + `report_path` in `metadata["simulate"]`.

### Frontend action overlay — `frontend/data_viewer.py`, `frontend/history_dashboard.py` (Task 07)

- `helpers.latest_simulation_folder()` → newest `sim_<id>` by id, or `None`.
- `FullData._load_latest_actions()` reads `actions.jsonl` (`[]` if absent); `_draw_action_markers` plots, on the price subplot only, events in the visible window: OPEN long = triangle-up below low (limegreen), OPEN short = triangle-down above high (orange), CLOSE = "x" (blue), STOP_LOSS = "x" (red), MOVE_STOP_LOSS = grey dot (optional). y from `executed_price` (fallback `target_price`), x from `timestamp` (Unix s, aligned to df index).
- `SIGNAL_FIRED` **not** plotted (too noisy). Overlay toggleable via `HistoryDashboard` controls, **off by default**. Skip-if-absent renders unchanged.

---

## On-disk layout

```
{action_folder()}/                 # = {shared_folder()}actions/
  sim_1/
    actions.jsonl                  # one Action per line, chronological
    report.json                    # metrics + action_counts + context
  sim_2/
    ...
```

---

## Error handling

- Action recording wrapped in `TrainRobot.step()` try/except → logged via `log_error`, never aborts the run.
- Missing/empty worker log → skipped in merge; empty simulation (zero trades) is valid, report still written.
- No simulation folder / no `actions.jsonl` → viewer renders the chart unchanged, no error.
- `report.json` is always strict-JSON-valid (no NaN, no raw `inf`).

---

## Acceptance criteria

End-to-end on the **functional dataset** (`df_with_indicators.pkl` carrying `5_ema_7`, `5_ema_14`, `5_zone_class`):

1. `docker compose run --rm -e STRATEGY_SET=test trainer python3 trainer.py simulate` **exits 0** — backtest of all four defined strategies runs to completion without crashing.
2. **All artifacts present** under one `sim_<id>/`:
   - `actions.jsonl` exists, non-empty; every line parses to an `Action`; every record's `sim_id` equals the folder id.
   - `report.json` exists and is valid JSON (no NaN, no raw `inf`).
3. **Report well-formed:** `report.json` contains `metrics` (`total_trades`, `win_rate`, `avg_revenue_pct`, `total_revenue_abs`, `max_drawdown`, `profit_factor`), `action_counts` per event, and `context` (`strategy_set=test`, `pair`, window, `fee`, `num_workers`).
4. **Consistency:** `metrics.total_trades == count(CLOSE) + count(STOP_LOSS)` from `actions.jsonl`, matching `action_counts`.
5. At least one `OPEN` action carries a strategy-provided `target_price`; at least one `SIGNAL_FIRED` action is recorded.
6. **Sim id unique + monotonic:** a second run creates a new `sim_<id+1>` folder and leaves the previous folder untouched.
7. `view_full.py` loads the newest simulation and renders its action markers without error; renders cleanly when no simulation exists.

These become the phase integration test (`tests/test_phase14_simulation_wiring.py`, written RED before Task 01) plus the two Docker entry-point checkboxes in the phase README.

---

## Testing strategy

- Each task ships unit tests written RED before implementation (happy path + edge + failure mode).
- Phase integration test wires every touched layer and asserts the acceptance criteria above; RED in Docker before Task 01, GREEN in Docker before the phase closes.
- All verification runs inside Docker (`simple_trader` image / `trainer` service) — never local-only.

---

## Out of scope

- Tuning strategy thresholds for profitability (these are test/validation strategies).
- Strategy/signal **name** attribution in Action records (decision 2 — action type only).
- Per-strategy or per-side simulation grouping (decision 3 — all four in one run).
- Live-trading action capture (`robots/robot.py`) — this phase is backtesting only.
- Concurrent-run locking for `next_simulation_id` (single backtest driver assumed).
