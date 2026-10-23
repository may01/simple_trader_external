# Volume-flow entry filter — out-of-sample re-score (task, due 2026-11-04)

**Origin:** experiment `volume_flow_entry_filter` (2026-10-21, verdict partial). User decision 2026-10-21: no executor
code change; the features are reconstructed from the DB after the fact.
**Goal:** score the three paper-run leads on data they never saw — the paper run from 2026-10-21 18:04:23 UTC
(ms 1792605863000, the last trade of the scored window) onward, ≥ 2 weeks.

## Preconditions
- The paper stack (`cbov-check`, worktree `trade_executor/.worktrees/cb-candle-stop` @ a6a5bc6) keeps running on
  LINKUSDT with the same rules (cb_zone fires, candle stop, trend-flip exit). A rule change inside the window
  invalidates the comparison — note the date and cut the window there.
- `trade` and `signal_log` are not pruned (checked 2026-10-21: no pruning path in the executor).

## Recipe
1. Export (psql -At -F, from `cbov-check-postgres-1`, db `trader`) into a scratch `data/` dir — SQL in the header of
   `external/executor/runs/2026-10-21-volume-flow-replay.py`: `trades.csv` (ord_ts, price, qty, side), `indicators.csv`,
   `events.jsonl`, `positions.jsonl`, `depletion.csv`.
2. Run, out-of-sample window only:
   ```
   python3 external/executor/runs/2026-10-21-volume-flow-replay.py data --t0=1792605863000 \
     --variants=live,rv5_gt3.0,rv15_gt3.0,dep60_on,rv5_gt3.0|rv15_gt3.0|dep60_on,sh24_rv5_gt1.5,sh24_dep60_on,rand20_s0,rand20_s1,rand20_s2,rand20_s3 \
     > external/executor/runs/2026-11-04-volume-flow-rescore-output.txt
   ```
   Check the reproduction gate line first (recorded vs simulated fires matched ≥ 95 %).
3. Read: the `PAIRED 6-H BLOCK BOOTSTRAP vs live` block (Δ, P(Δ<0)) for the three skips and the union, against the
   `rand20_*` and `sh24_*` controls; the per-day table for sign consistency.

## Decision rule (fixed now, before the data exists)
- Promote the climax-volume skip (`rv5 > 3`, no book dependency) to an executor spec if Δ > 0 on the new window
  with P(Δ<0) ≤ 0.10, positive on ≥ 70 % of days, and above the random-skip band.
- `dep60_on` the same way, only if `rv5 > 3` also passes (they overlap; one filter, not two).
- Otherwise close the experiment as negative in `experiment/REPORT.md` (new row referencing the 2026-10-21 row).
- No flow-direction filter under any outcome.

## Deliverables
`external/executor/runs/2026-11-04-volume-flow-rescore.md` (one table + verdict), `REPORT.md` row update, the
results file's "Next arbiter" section replaced by the number.
