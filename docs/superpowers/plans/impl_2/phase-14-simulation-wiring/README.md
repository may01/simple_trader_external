# Phase 14 — Simulation / Strategy / Signal Wiring

**Goal:** Wire the already-built layers (signals → strategies → position → TrainRobot → SimulationOrchestrator → frontend) into one working backtest path. Add concrete test strategies, an **Action** record that captures every position change + signal firing, per-simulation storage keyed by simulation id, a simulation report, and an action overlay on the `full_view` chart.

**Why this phase exists:** Phases 04–12 built every layer in isolation with `ExampleStrategy*` plumbing validators. Nothing yet runs end-to-end with real entry/exit logic, nothing records *what happened* during a run, and the chart cannot show a simulation's trades. This phase connects the pieces and makes a run observable.

This phase **extends existing layers** — it does not introduce a new bottom layer. Task order is still bottom-up so each integration boundary is RED before the layer above it is touched.

---

## Requirements covered

| # | Requirement | Task |
|---|-------------|------|
| 1 | Test strategies with simple open/close signals (EMA cross long; RSI zone_class long) | 01 |
| 2 | Mirror strategies for short | 01 |
| 3 | Position changes + signal firing produce **Action** records (opened/closed/stop-loss, signal fired, strategy-provided price) | 02, 03, 04 |
| 4 | Actions from latest simulation shown on `full_view` graph | 07 |
| 5 | Simulation runs the defined strategies over the dataset | 01 (factory), 05 |
| 6 | Position tracks its changes and logs them | 03 |
| 7 | Simulation report | 06 |
| 8 | Each simulation carries an id number | 05 |
| 9 | Each set of actions stored in a folder keyed by the simulation id | 05 |

---

## Docker Entry Points (ground truth — defined before any layer)

```bash
# Run a backtest with the Phase-14 test strategies over the prepared dataset.
# STRATEGY_SET selects which strategies the factory registers (default "test" here).
docker compose run --rm -e STRATEGY_SET=test trainer python3 trainer.py simulate

# View the latest simulation's actions overlaid on the historical chart (Docker path F).
docker compose -f docker-compose-view.yml run --rm viewer python3 view_full.py
```

These commands are the contract. Implementation must make them work. The simulate command writes a per-simulation folder under `action_folder()` and the viewer reads the newest one.

Verified: [ ] `docker compose run --rm -e STRATEGY_SET=test trainer python3 trainer.py simulate` produces `{action_folder()}sim_<id>/actions.jsonl` and `report.json`
Verified: [ ] `view_full.py` renders action markers from the newest `sim_<id>` folder

---

## Layer order for this phase

```
Signal library (Phase 04)        ← REUSED as-is (Cross_Up_Signal, Cross_Up_Val_Signal) — no new primitives
  ↓
Strategy (Phase 07)              ← Task 01: 4 test strategies + test factory
  ↓
Action model (new, backtesting)  ← Task 02: Action dataclass + ActionLog
  ↓
Position management (Phase 06)   ← Task 03: position.action_history change log
  ↓
Backtesting / TrainRobot (Ph 08) ← Task 04: assemble Action records per tick
  ↓
SimulationOrchestrator (Ph 08)   ← Task 05: simulation id + per-sim folder persistence
  ↓
PerformanceAnalyzer (Ph 08)      ← Task 06: report.json into the sim folder
  ↓
Frontend (Phase 12)              ← Task 07: action overlay on full_view
```

---

## Phase integration test (RED in Docker, written before Task 01)

Wires every layer the phase touches in one assertion. Must be RED before implementation starts and GREEN before the phase is done.

`tests/test_phase14_simulation_wiring.py`:

```
def test_test_strategy_simulation_writes_actions_and_report():
    # Arrange: small SimulationData slice over the prepared dataset
    # Act: SimulationOrchestrator(strategy_factory=test_factory(fee)).run(sim_data)
    # Assert:
    #   - a sim_<id> folder exists under action_folder()
    #   - actions.jsonl is non-empty and every line parses to an Action with sim_id == that id
    #   - at least one OPEN action carries a target_price provided by the strategy
    #   - report.json exists and its total_trades matches the count of CLOSE actions
```

```bash
docker run --rm -v "$PWD":/code -w /code simple_trader \
  python3 -m pytest tests/test_phase14_simulation_wiring.py -q
```

---

## Key design decisions

- **No new signal primitives.** EMA cross uses `Cross_Up_Signal(5, "ema_7", "ema_14")` / `Cross_Down_Signal`. RSI zone uses `Cross_Up_Val_Signal(5, "zone_class", 0.5)` etc. — `zone_class` is the integer tier 0..4 (0 = oversold, 4 = overbought), so half-integer thresholds express "leaves oversold" / "enters overbought" with existing primitives. Reuse over new code.
- **Action is the single record type** for both position changes and signal firings — one schema, one file per simulation.
- **Simulation id is owned by `SimulationOrchestrator`**, allocated once per `run()`, threaded down to every worker so all workers write into the same `sim_<id>` folder.
- **TrainRobot assembles Action records** because it is the only layer that sees both the strategy decision (action + prices it provided) and the resulting position transition. Position keeps its own raw change log; TrainRobot enriches it with strategy context.
- **Frontend reads the newest sim folder** — no coupling between the run and the viewer beyond the on-disk folder.

---

## Tasks

| Task | File | Produces |
|------|------|----------|
| 01 | `task-01-test-strategies.md` | 4 test strategies + `TestStrategyFactory` |
| 02 | `task-02-action-record.md` | `backtesting/action.py` — `Action` + `ActionLog` |
| 03 | `task-03-position-change-log.md` | `position.action_history` change tracking |
| 04 | `task-04-train-robot-actions.md` | TrainRobot emits enriched `Action` records |
| 05 | `task-05-simulation-id-storage.md` | sim id + per-sim folder persistence |
| 06 | `task-06-simulation-report.md` | `report.json` per simulation |
| 07 | `task-07-action-overlay.md` | action markers on `full_view` |
