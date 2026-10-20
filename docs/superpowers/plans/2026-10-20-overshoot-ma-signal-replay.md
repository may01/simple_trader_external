# Overshoot-zone MA signal replay — plan

**Spec:** `experiment/overshoot_ma_signal.md`. **Goal:** P&L of `ma3` / `ma5` vs `current` on the paper run's stored 58 h, with the reproduction gate on fires. **Architecture:** one numpy script in `external/executor/runs/` (precedent `2026-10-20-sl-15m-anchor-replay.py`), reads CSV/JSONL exports of the `cbov-check` postgres, writes text outputs beside itself; touches no code repo. **Stack:** host python3, numpy only.

## Step 0 — entry points
```
PG="docker exec cbov-check-postgres-1 psql -U executor -d trader -At -F,"   # exports (SQL in the script header)
python3 external/executor/runs/2026-10-20-overshoot-ma-replay.py <data-dir> > …-output.txt
```

## Tasks
| task | deliverable | gate |
|---|---|---|
| 1 export | trades.csv, indicators.csv (CB names), events.jsonl, positions.jsonl | row counts printed |
| 2 check port | `current` mode re-fires the 152 recorded events | matched/missed/extra table |
| 3 modes | current, no_veto, ma3, ma5, ma3_and, ma5_and (+ ma3_all / ma5_all: longer MA everywhere) | standard + marginal tables |
| 4 gates | bootstrap CI, top-2, fee sensitivity, feed gaps | numbers in the report |
| 5 report | run report + results summary + REPORT.md verdict | user approval |
