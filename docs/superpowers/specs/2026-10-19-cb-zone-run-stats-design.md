# CB zone run-length statistics (expected in-zone minutes per zone block) — design

**Date:** 2026-10-19
**Base branch:** `experimental_imp_2` (main/). Work branch: `cb-zone-run-stats` (main/, off `experimental_imp_2`).
**Status:** approved 2026-10-19 (user decisions §7); **measured 2026-10-19** — frozen values `15:2.0/2.0;60:3.0/3.0;240:4.0/4.0` in `experiment/results/cb_zone_run_stats_results.md`; code on branch `cb-zone-run-stats` @ `8c5f422`, merged into `experimental_imp_2` as `08c623e` (release_001, 2026-10-20).
**Consumer:** `trade_executor` — [`external/executor/specs/2026-10-19-cb-book-stop-design.md`](../../../executor/specs/2026-10-19-cb-book-stop-design.md) freezes the numbers this produces as `CB_STOP_EXPECTED_POINTS`.
**Related:** [2026-10-05-cb-markers-main-flow-design.md](2026-10-05-cb-markers-main-flow-design.md) (what `cb_inzone` is), [2026-10-17-cb-overshoot-main-flow-design.md](2026-10-17-cb-overshoot-main-flow-design.md) (the filter flags, frozen thresholds), `scripts/cb_export_overshoot.py` (the script this mirrors), `notebooks/zone_profitability/run_cb_overshoot.py` `stats()` (the lost per-candle statistic), `external/docs/superpowers/experiment/results/extdone_zone_filter_results.md` §3.1 (the only surviving per-candle numbers, oos2m).

## 1. Why

The executor's CB-zone stop (executor spec above) needs, per `(tf, side)`, one frozen number: how many consecutive 1-min rows a price typically stays inside a CB entry zone once it has entered it — "points in a row per zone". With that and the current streak it knows how many minutes the zone episode is expected to run, and sizes the stop from the order book over that horizon.

No such number exists. What exists:

- `run_cb_overshoot.py` `stats()` computed **in-zone minutes per touched candle** (mean, p50) per `(tf, side)` for the all / kept / dropped overshoot sets. The report (`cb_overshoot_report.{json,md}`) went to a session scratchpad and is gone; nothing copied it into a doc.
- `extdone_zone_filter_results.md` §3.1 gives markers and candles on **oos2m** after the sticky extdone veto (oos2m ladder), before the overshoot filter. Dividing gives ≈ 3.9 / 3.6 (15 long / short), 12.3 / 10.6 (60), 40.2 / 32.6 (240) minutes per touched candle.

Both count **every** in-zone minute of a candle, so several separate touches add up; neither is a consecutive run length, neither is on 2y, and neither uses the filter set the executor's entry check fires on. Nobody has measured how many separate zone blocks a candle usually has.

## 2. Definitions

All on the 1-min wide frame; `cid` = candle id from `{tf}_is_closed` (the experiment convention, `evlib.candle_id` / `kernel.candle_progress(by_rows=True)`'s grouping). A run never crosses a candle boundary: a new candle has a new zone value, and the executor's re-fire rule is per zone value. The executor's streak counter resets on the same event — a change of `{tf}_cb_zone_{side}` (stop spec §5) — so the two count the same thing.

Per `(tf, side)`, three marker masks `m` over rows:

| set | mask | why |
|---|---|---|
| A `raw` | `{tf}_cb_inzone_{side}` | what the executor's streak counter counts (it reads the raw flag) |
| B `extdone` | A ∧ `{tf}_cb_f_extdone_{side}` | matches the surviving oos2m table (non-sticky, 2y ladder — the main-flow flag, not the experiment's sticky veto) |
| C `overshoot` | A ∧ `{tf}_cb_f_overshoot_{side}` | **the frozen set** (user decision 2026-10-19: overshoot filter only, no `cb_f_trend`). Not the executor's firing set: the entry check also vetoes on `cb_f_trend`, needs its own trade-price MA class (no main/ column), and rule 2 fires on a minute that is not in zone; the results doc says so. |
| D `entry` | C ∧ `{tf}_cb_f_trend_{side}` | reported for comparison only (the entry check's full filter set) |

Per set:

- **block** = maximal run of consecutive rows with `m` True inside one `cid`. Its **length** `L` = row count (minutes; rows are dense 1-min, gaps in the frame are not bridged — a missing minute ends a block, same as live).
- **touched candle** = a `cid` with ≥ 1 True row. Per touched candle: `blocks` (number of blocks), `minutes` (= Σ L), `first_block_len` (L of the block holding the candle's first True row).
- **remaining given streak** `R[s]` = over every block with `L ≥ s`, the distribution of `L − s` (s = 1 … 12). This is the quantity the executor approximates with `E − streak`; reported so the one-number rule can be judged.

## 3. Script

`scripts/cb_zone_run_stats.py` (main/), one-off, mirrors `scripts/cb_export_overshoot.py`: runs in the `simple_trader` image, writes a report, writes no params.

```
docker compose -p cbtest run --rm ohlc_gen python3 scripts/cb_zone_run_stats.py \
    [--train-ind /trader_data_long/train/2y_az_link_usdt/df_with_indicators.pkl] \
    [--train-cb  /trader_data_long/train/2y_link_usdt/df_with_candle_bounds.pkl] \
    [--oos-dir   /trader_data_long/train/oos2m_link_usdt] \
    [--out <dir>]  [--recompute-cb]
```

Inputs. `pd.read_pickle` loads the whole frame (no column selection — `cb_export_overshoot.py` slices *after* loading, and its 2y run was never executed on this host: `cb_overshoot_main_flow_results.md` G1b). The script loads the 2y frame, immediately keeps the column list below and drops the rest, then loads the sidecar; peak memory ≈ the whole 2y frame + sidecar + kernel intermediates. G3 reports the peak RSS. If the host cannot hold it, the plan's first step is a one-time column-subset re-pickle written on the volume through docker (`2y_az_link_usdt/df_cb_run_stats_inputs.pkl`, the column list below), which every later run reads instead.

- 2y (`2y_az_link_usdt/df_with_indicators.pkl`): `1_high`, `1_low`, `1_close`, and per tf `{tf}_high`, `{tf}_low`, `{tf}_close`, `{tf}_ema_25`, `{tf}_is_closed`, plus `{tf}_ema_25_slope_class` / `{tf}_move_class` **if present** (believed absent: the materialize and move_class7 scripts were only run on oos2m). Absent `ema_25_slope_class` is backfilled the way `scripts/cb_markers_materialize._ema_slope_columns` does (from `{tf}_ema_25` / `{tf}_close`, talib in the image); absent `move_class` is a NaN column (`cb_f_mcx` is not used). **ATR**: `1_atr_14_ma_5` is not stored on the 2y frame; every 2y driver rebuilt it (`run_zone_ext.atr1_ma5`, pandas Wilder ewm on 1-min OHLC), and the frozen `EXTDONE_LADDER` was fit against that rebuilt series (`fit_extdone_ladder.py`). The script does the same and injects it under `params.ATR_COL` — provenance-consistent with the ladder, slightly different from prep's talib ATR that live uses (recorded as a caveat in the results doc; if the stored column turns out to exist, it is used and the choice logged). The closed-bounds sidecar `2y_link_usdt/df_with_candle_bounds.pkl`, reindexed onto the 2y index, supplies `{tf}_cb_{low,high}[,_std]` and `{tf}_cb_inzone_{side}`. Flags are computed with the main-flow kernel: `kernel.extdone(df, tf, EXTDONE_LADDER[tf])`, `kernel.overshoot(cb, df, tf)`, `kernel.filters(df, ext, over, tf)`. `--recompute-cb` runs `stage.compute_cb_columns` on the frame *after* the backfill/NaN columns are injected (it raises on a missing `required_columns()` entry) instead of reading the sidecar (slow; the oracle).
- oos2m (`oos2m_link_usdt/df_with_indicators.pkl`): already holds every main-flow CB column (phase 18/19 materialize, 884 columns) and the stored ATR — read the flags directly.

Outputs (`--out`, default `notebooks/zone_profitability/out/`):

- `cb_zone_run_stats.json` — per dataset ∈ {2y, oos2m}, per set, per `(tf, side)`: `n_blocks`, `n_candles`, `run_len` {mean, p50, p75, p90, max}, `blocks_per_candle` {mean, p50, p90}, `minutes_per_candle` {mean, p50}, `first_block_len` {mean, p50, p75}, `remaining_given_streak` {s: {p50, p75, n}} for s = 1…12.
- `cb_zone_run_stats.md` — the same as tables, plus one **freeze table**: set C (inzone ∧ overshoot), 2y, `run_len.p50` per `(tf, side)`, and the oos2m value beside it.
- stdout: the freeze table.

Pure functions, unit-tested on hand-built frames: `blocks(m: np.ndarray, cid: np.ndarray) -> np.ndarray` (lengths), `per_candle(m, cid) -> DataFrame[blocks, minutes, first_block_len]`, `remaining_given_streak(lengths, s_max) -> dict`.

## 4. What gets frozen, and where

- The executor's `CB_STOP_EXPECTED_POINTS` (executor spec §10) carries **set C (inzone ∧ overshoot pass), 2y, `run_len.p50` (median)** per `(tf, side)`, six numbers — both user decisions of 2026-10-19. **This task ends at the results doc**: the executor plan (stop spec) copies the six numbers into its `docker-compose.yml` default; nothing here touches `trade_executor`. Nothing in main/ reads them; no `params.py` change.
- The results doc records the full tables so a later switch (mean instead of p50, `first_block_len`, or the `remaining_given_streak` table as a lookup) is a config change, not a re-measurement.

Author's calls (not asked of the user; flagged):

| Question | Call |
|---|---|
| p50 or mean | **p50 (median)** — user decision 2026-10-19. Run lengths are right-skewed (one long block pulls the mean up); the stop should fit the typical episode, the buffer minute covers the rest. Mean is in the table. |
| Which set for the frozen value | **C = inzone ∧ overshoot pass** — user decision 2026-10-19 (not the trend flag). The executor's streak counter counts raw (A) minutes, so an overshoot flag that flips mid-block makes the live streak longer than C's block; the A/C difference in the table says how much that matters. If A and C differ by > 1 minute at p50 on any tf, say so in the results doc. |
| Blocks that touch the frame's edges / a tf's warm-up | Dropped (first and last candle of each dataset, candles where the bound is NaN) — matches `cb_markers_validate.py`'s edge rule. |

## 5. Acceptance gates

- **G1** unit: `blocks([1,1,0,1], cid=[0,0,0,0]) == [2,1]`; a run split by a candle boundary is two blocks; an empty mask gives no blocks; `per_candle` counts blocks/minutes/first_block_len on a 3-candle hand frame; `remaining_given_streak([3,5], 4)` → s=1: {2,4}, s=4: {1}.
- **G2** parity with the surviving numbers (markers only — no per-candle reference exists for the non-sticky set): set B on oos2m reproduces the minute counts of `cb_markers_main_flow_results.md`'s "∧ cb_f_extdone" column (10 056 / 8 134 / 10 587 / 7 178 / 9 474 / 6 553) within the edge rule's one candle per tf; set A reproduces the `cb_inzone` column likewise. `n_candles` and `minutes_per_candle` are reported, not gated.
- **G3** 2y run: the script completes on the host (report peak RSS and wall time; the subset re-pickle step if it was needed); set C freeze table printed; json + md written.
- **G4** oos2m vs 2y: the oos2m p50 per cell is reported beside 2y; a cell where oos2m p50 differs from 2y p50 by more than 50 % is called out (oos2m was the more volatile regime — `extdone_zone_filter_results.md` §3.3).
- **G5** results doc `external/docs/superpowers/experiment/results/cb_zone_run_stats_results.md` written with the tables, the run command, the commit hash, the ATR caveat, the A-vs-C p50 comparison, and the six frozen values in the exact `CB_STOP_EXPECTED_POINTS` syntax (`15:L/S;60:L/S;240:L/S`) for the executor plan to copy.

## 6. Non-goals

- No change to prep, live, broadcast or the viewer. No new column anywhere.
- No conditioning (progress bucket, move class, EMA slope class) — the `remaining_given_streak` table is the only refinement reported.
- Not a re-measurement of the overshoot thresholds or the extdone ladder.
- No replay of profitability; this measures zone geometry only.

## 7. User decisions (2026-10-19)

| Question | Answer |
|---|---|
| 2y memory | **Wait for the 2y results; retry on error** (the subset re-pickle step first). No oos2m-only freeze. |
| §3 ATR on 2y | Only `kernel.extdone` reads the ATR, so it only shapes set B (the reference set that matches the old table). The frozen set C (overshoot flag) does not use it. Rebuilt `atr1_ma5`, as every 2y driver and the ladder fit used, is the author's call; the results doc records it. |
| Frozen set | **inzone ∧ `cb_f_overshoot`** (set C), no trend flag. |
| Statistic | **Median** (p50) block length. |
