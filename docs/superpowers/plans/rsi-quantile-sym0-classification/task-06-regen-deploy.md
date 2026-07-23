# Task 06 — Regen (2y + oos2m) + deploy

**Layer:** prepare pipeline invocation + deploy
**Depends on:** task-05 GREEN
**Produces:** baked new columns + both jsons in 2y & oos2m; live on 8080

## Steps
1. **2y:** delete `stats/train/link_usdt/rsi_classification.json` (+ `rsi_side_stats.json` once it exists)
   → run `docker compose run --rm ohlc_gen` with 2y env (nn-orchestrator run recipe:
   ROOT_FOLDER=long, 2y_link_usdt). New cuts + side-stats compute; class columns bake into the
   25-part `df_with_indicators`.
2. **oos2m — NO REFIT:** copy the freshly-computed **2y** `rsi_classification.json` +
   `rsi_side_stats.json` into the oos2m stats folder BEFORE prepare (or point `stats_folder()`
   at 2y). Then prepare oos2m (single `df_with_indicators.pkl`). Absent-only guard means the
   copied 2y jsons are reused, not refit — this is the real OOS test.
3. **Verify:** new columns present in both; quantile classes ~balanced; jsons non-NaN; legacy
   columns unchanged. Re-run `gate.py` → still PASS.
4. **Deploy:** merge branch → `experimental_imp_2`; `docker compose up -d view-full`; open
   localhost:8080 → legacy + new markers on rsi_ma8, tooltip shows long/short win-rate.

## Constraints
- Container writes root-owned files into mounted worktrees → can block merge; fix ownership
  before merging ([[container root files]]).
- Confirm before any commit/push ([[confirm before commit]]).
- 4y NOT regenerated (out of scope).

## Done when
8080 shows the A/B markers on 2y and oos2m; gate PASS on the regenerated data.
