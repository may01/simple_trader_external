# Task 01 — Side-aware gate pre-check (hard block)

**Layer:** validation (before any field code)
**Depends on:** nothing
**Blocks:** task-02..06

## Goal
Re-run the acceptance gate and confirm PASS before writing field code. If it fails, STOP and
revisit the spec — do not implement.

## Interface
`gate.py` (analysis harness) → prints per-(TF,field) `current → recommended` best-side-lift
and a PASS/FAIL line. Inputs: 2y `closed.pkl` (fit), oos2m `df_with_indicators.pkl` (score).

## Check (RED→GREEN is "gate passes")
```bash
python3 gate.py         # move directional 3/3 PASS ; zone magnitude re-gate PASS
```
Record the numbers into the spec §4 if they drift from the recorded run.

## Pass criteria
- Move: recommended (sym0) best per-side lift ≥ current − 0.3pp at TF{60,240,1440}, on BOTH
  2y-test and oos2m.
- Zone: quantile `η²(|fwd|)` and extreme-vs-neutral |return| separation ≥ current at
  TF{60,240} on both sets (1d noisy, informational).

## Notes
- Gate is directional for move, magnitude for zone (zone is volatility, not signed).
- Fit-on-2y / score-on-oos2m mirrors production stat propagation (no OOS refit).
