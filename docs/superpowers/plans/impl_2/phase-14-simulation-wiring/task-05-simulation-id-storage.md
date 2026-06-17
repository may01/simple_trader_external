# Task 05: Simulation id + per-simulation action storage

**Phase:** 14 — Simulation Wiring
**Depends on:** Task 04 (TrainRobot.action_log), Phase 08 Task 02 (SimulationOrchestrator), helpers (`action_folder`)
**Produces:** simulation id allocation, `helpers.simulation_folder`, per-sim `actions.jsonl` persistence

---

## Goal

Requirements 8 & 9: every simulation carries an id number, and each set of actions is stored in its own folder keyed by that id. `SimulationOrchestrator` allocates the id once per `run()`, threads it to every worker so all workers record into the same `sim_<id>` `ActionLog`, merges the worker logs, and writes `actions.jsonl` into `{action_folder()}sim_<id>/`.

---

## Context

`SimulationOrchestrator.run()` splits the range across workers; each worker builds its own `TrainRobot`. Today worker results are just revenue dicts. Now each worker also returns its `ActionLog` (already stamped with the shared `sim_id` via `set_sim_context`). The orchestrator merges them and persists.

`action_folder()` already exists (`{shared_folder()}actions/`). Add id allocation + folder helpers there.

---

## Files

- Modify: `helpers.py` — `next_simulation_id`, `simulation_folder`
- Modify: `backtesting/simulation_orchestrator.py` — allocate id, thread to workers, collect + persist action logs

---

## Interface

**helpers.py:**
- `simulation_folder(sim_id: int) -> str` — returns `f"{action_folder()}sim_{sim_id}/"`
- `next_simulation_id() -> int` — scans `action_folder()` for existing `sim_<n>` dirs, returns `max(n) + 1`; returns `1` when none exist (creates `action_folder()` if absent)

**SimulationOrchestrator:**
- `run(simulation_data) -> dict` — return value gains `sim_id` and `action_count`; now also returns the path written. (Existing callers in `training/trainer.py` read `results`/metrics — keep backward-compatible by returning a dict that still carries the per-worker revenue results under a `results` key, or update the caller in Task 06.)
- New attribute `sim_id: int` — set at the start of `run()` via `next_simulation_id()`
- Worker (`_worker`): receives `sim_id`, calls `robot.set_sim_context(sim_id)`, after the loop returns `{"revenue_history": ..., "trade_count": ..., "action_log_jsonl": robot.get_action_log().to_jsonl()}`
- `_persist_actions(sim_id: int, worker_jsonl: list[str]) -> str` — concatenates worker JSONL into one `ActionLog`, writes `{simulation_folder(sim_id)}actions.jsonl`, returns the path
- `run_single(...)` — same id allocation + persistence, single worker

---

## Key Constraints

- `sim_id` allocated ONCE per `run()` and passed to every worker — all workers write into the **same** folder. Never allocate per worker.
- Worker processes cannot share an `ActionLog` object (separate memory) — each returns its log serialised as JSONL; the parent reassembles. `ActionLog`/`Action` cross the process boundary as strings, not objects.
- `next_simulation_id()` is racy under concurrent runs — acceptable for backtesting (single driver); document the assumption, do not add locking.
- Folder is created lazily by `_persist_actions` (`os.makedirs(..., exist_ok=True)`) — never assume it exists.
- Worker crash: its action log is empty/missing — skip it, do not abort the merge (mirrors existing empty-result handling).
- Preserve chronological order: concatenate worker JSONL in segment order so actions read top-to-bottom in time.

---

## Verification

```bash
docker run --rm -v "$PWD":/code -w /code simple_trader python3 -c "
import os
from helpers import next_simulation_id, simulation_folder, action_folder
a = next_simulation_id(); b = next_simulation_id()
assert b >= a >= 1
os.makedirs(simulation_folder(a), exist_ok=True)
assert simulation_folder(a).endswith(f'sim_{a}/')
assert next_simulation_id() == a + 1   # now that sim_<a> dir exists
print('sim id + folder ok:', a, simulation_folder(a))
"
```

Plus the phase integration test (README) asserts `sim_<id>/actions.jsonl` exists and every line's `sim_id` matches.

---

## Commit

`feat: allocate simulation id and persist per-sim actions.jsonl under action_folder`
