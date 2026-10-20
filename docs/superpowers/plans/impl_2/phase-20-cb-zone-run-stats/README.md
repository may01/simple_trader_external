# Phase 20 — CB Zone Run-Length Statistics (expected in-zone minutes per zone block)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One script, run once in Docker, that measures how many consecutive 1-min rows price stays inside a CB entry zone (per tf, per side, per filter set) on 2y and oos2m, and a results doc whose freeze table gives the executor its six `CB_STOP_EXPECTED_POINTS` numbers.

**Architecture:** Three pure numpy functions (`blocks`, `per_candle`, `remaining_given_streak`) over a boolean marker mask and a candle id; a driver that builds the masks with the main-flow kernel (2y: sidecar bounds + kernel flags; oos2m: stored columns) and writes json + md. Nothing in prep, live, broadcast or the viewer changes; no new column.

**Tech Stack:** Python 3.11, pandas, numpy, pytest, Docker Compose (`ohlc_gen` service, `simple_trader` image).

**Spec:** `specs/2026-10-19-cb-zone-run-stats-design.md` — approved 2026-10-19 with the user decisions in its §7 (frozen set C = `cb_inzone ∧ cb_f_overshoot`, statistic = median block length, wait for 2y and retry on error). Read it first.

**Branch:** main/ `cb-zone-run-stats` off `experimental_imp_2` (`aca3ef6`), worktree `simple_trader/worktrees/cb-zone-run-stats`.

---

## Global Constraints

- TFs `(15, 60, 240)`; sides `long` / `short`. Masks per spec §2: A `raw` = `{tf}_cb_inzone_{side}`; B `extdone` = A ∧ `{tf}_cb_f_extdone_{side}`; C `overshoot` = A ∧ `{tf}_cb_f_overshoot_{side}` (**frozen**); D `entry` = C ∧ `{tf}_cb_f_trend_{side}` (reported only).
- A block never crosses a candle boundary (`cid` from `{tf}_is_closed`, `evlib.candle_id` convention); a missing minute (index gap) ends a block.
- Edge rule: the first and last candle of each dataset per tf, and candles whose bound is NaN, are dropped from every statistic.
- 2y ATR: rebuilt with `run_zone_ext.atr1_ma5`, injected under `params.ATR_COL`; if the stored column exists it is used instead, and the choice is printed and recorded.
- 2y frame is loaded whole (`pd.read_pickle` cannot select columns), trimmed to the needed columns immediately; peak RSS and wall time are reported. If the full load fails, the one-time column-subset re-pickle (Task 03 step 2) is the retry path. **No oos2m-only freeze.**
- Frozen value = set C, 2y, `run_len.p50` per `(tf, side)`; the results doc prints it in `CB_STOP_EXPECTED_POINTS` syntax `15:L/S;60:L/S;240:L/S`. This phase does not touch `trade_executor`.
- All tests and runs in Docker under a separate compose project: `docker compose -p cbrun run --rm -e PYTHONDONTWRITEBYTECODE=1 ohlc_gen python -m pytest -p no:cacheprovider <path> -q`.
- Do not commit, push or open a PR without the user's explicit confirmation. Stage, describe, wait.
- Docs (this plan, the spec, results) live in the external repo only. Volume files are root-owned: write to them only from inside a container.

## Review Focus

1. **A block that straddles a candle close.** Expected: two blocks, one per candle, never one long block. → Task 01 (`blocks` test "split by boundary").
2. **An index gap inside a candle** (missing minute in the frame). Expected: the block ends at the gap, like live. → Task 01 (`blocks` with a `minute` argument) and Task 02 (driver passes the frame's own minute index, not the row number).
3. **A candle with no marker at all.** Expected: absent from `per_candle` (not a zero row), so `blocks_per_candle` is over touched candles only. → Task 01.
4. **`remaining_given_streak` at `s` larger than every block.** Expected: empty cell with `n = 0`, never a NaN that becomes 0 in the table. → Task 01.
5. **oos2m parity drift.** Set A/B minute counts must match the phase-18/19 tables within the edge rule; a mismatch means the mask or `cid` is wrong, not the data. → Task 02 (G2).

---

## Docker Entry Points

```bash
# Unit tests (Task 01)
docker compose -p cbrun run --rm -e PYTHONDONTWRITEBYTECODE=1 ohlc_gen \
    python -m pytest -p no:cacheprovider tests/unit/data_layer/test_cb_zone_runs.py -q

# oos2m only, parity check (Task 02, G2) — fast
docker compose -p cbrun run --rm ohlc_gen python3 scripts/cb_zone_run_stats.py \
    --oos-dir /trader_data_long/train/oos2m_link_usdt --skip-train --out notebooks/zone_profitability/out

# Full run: 2y + oos2m (Task 03, G3/G4)
docker compose -p cbrun run --rm ohlc_gen python3 scripts/cb_zone_run_stats.py \
    --train-ind /trader_data_long/train/2y_az_link_usdt/df_with_indicators.pkl \
    --train-cb  /trader_data_long/train/2y_link_usdt/df_with_candle_bounds.pkl \
    --oos-dir   /trader_data_long/train/oos2m_link_usdt --out notebooks/zone_profitability/out

# Retry path if the full load fails: one-time subset re-pickle on the volume, then run against it
docker compose -p cbrun run --rm ohlc_gen python3 scripts/cb_zone_run_stats.py \
    --make-subset /trader_data_long/train/2y_az_link_usdt/df_cb_run_stats_inputs.pkl
docker compose -p cbrun run --rm ohlc_gen python3 scripts/cb_zone_run_stats.py \
    --train-ind /trader_data_long/train/2y_az_link_usdt/df_cb_run_stats_inputs.pkl ...
```

Verified: [ ] `docker compose -p cbrun run --rm ohlc_gen python -c "import indicators.candle_bounds.kernel"` succeeds on the work branch.

---

## Layers

### Layer 4 — Indicators (pure statistics)

**Interface produced (consumed by the driver):**

```python
# notebooks/zone_profitability/zone_runs.py
def blocks(mask: np.ndarray, cid: np.ndarray, minute: np.ndarray) -> np.ndarray: ...
    # lengths (int64) of every maximal run of True rows sharing one cid with consecutive minutes
def per_candle(mask: np.ndarray, cid: np.ndarray, minute: np.ndarray) -> pd.DataFrame: ...
    # index = touched cid; columns blocks (int), minutes (int), first_block_len (int)
def remaining_given_streak(lengths: np.ndarray, s_max: int) -> dict[int, dict[str, float | int]]: ...
    # {s: {"p50": .., "p75": .., "n": ..}} over L - s for L >= s, s = 1..s_max; n = 0 -> p50/p75 absent
def summarize(lengths: np.ndarray, pc: pd.DataFrame) -> dict[str, object]: ...
    # the spec §3 json cell: n_blocks, n_candles, run_len{mean,p50,p75,p90,max}, blocks_per_candle{mean,p50,p90},
    # minutes_per_candle{mean,p50}, first_block_len{mean,p50,p75}
```

**Integration test → driver (RED first):** `scripts/cb_zone_run_stats.py --skip-train` on a 3-candle synthetic oos-shaped frame written by the test writes a json whose set A cell equals `summarize(blocks(..), per_candle(..))` on the same mask (Task 02).

### Layer 3 — Driver (masks, datasets, report)

Builds the four masks per `(tf, side)` from a frame, runs Layer 4, writes `cb_zone_run_stats.{json,md}`; G2 parity on oos2m; G3/G4 on 2y (Tasks 02, 03).

### Docs

Results doc, spec status, memory (Task 03).

---

## Task Index and Execution Order

| Task | File | Layer | Depends on | Gates |
|---|---|---|---|---|
| 01 | `task-01-zone-runs-functions.md` | 4 | — | G1 |
| 02 | `task-02-driver-and-oos2m-parity.md` | 3 | 01 | G2 |
| 03 | `task-03-2y-run-and-results.md` | 3 / docs | 02 | G3, G4, G5 |

## Requirements Covered

| Spec section | Task |
|---|---|
| §2 definitions, §3 pure functions + unit tests | 01 |
| §3 script, inputs, ATR rebuild, oos2m flags, outputs; G2 | 02 |
| §3 2y run, memory retry; §4 freeze table; G3–G5; results doc | 03 |
