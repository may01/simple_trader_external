# Task 01: Pure run-length functions

**Phase:** 20 — CB zone run stats
**Depends on:** —
**Produces:** `notebooks/zone_profitability/zone_runs.py` — `blocks`, `per_candle`, `remaining_given_streak`, `summarize`
**Gates:** G1

---

## Goal

The statistics of spec §2 as pure numpy/pandas functions over `(mask, cid, minute)`, unit-tested on hand-built arrays. No file I/O, no dataset knowledge.

## Files

- Create: `notebooks/zone_profitability/zone_runs.py`
- Test: `tests/unit/data_layer/test_cb_zone_runs.py`

## Interface

```python
def blocks(mask: np.ndarray, cid: np.ndarray, minute: np.ndarray) -> np.ndarray: ...
def per_candle(mask: np.ndarray, cid: np.ndarray, minute: np.ndarray) -> pd.DataFrame: ...
def remaining_given_streak(lengths: np.ndarray, s_max: int = 12) -> dict[int, dict[str, float | int]]: ...
def summarize(lengths: np.ndarray, pc: pd.DataFrame) -> dict[str, object]: ...
```

`mask`: bool, one per row. `cid`: int, candle id per row (`evlib.candle_id`). `minute`: int64 epoch minutes of the row's index (`index.asi8 // 60_000_000_000` on a `DatetimeIndex`), so a gap in the frame is visible. A block = maximal run of rows with `mask` True, same `cid`, and `minute[i+1] == minute[i] + 1`.

`per_candle` index = every `cid` with ≥ 1 True row; columns `blocks` (count), `minutes` (True rows), `first_block_len` (length of the block holding the candle's first True row).

`remaining_given_streak`: for `s` in `1..=s_max`, over `L - s` for every `L >= s`: `{"p50", "p75", "n"}`; when `n == 0` the dict holds only `{"n": 0}`.

`summarize`: the spec §3 json cell — `n_blocks`, `n_candles`, `run_len` `{mean, p50, p75, p90, max}`, `blocks_per_candle` `{mean, p50, p90}`, `minutes_per_candle` `{mean, p50}`, `first_block_len` `{mean, p50, p75}` — floats rounded to 3 decimals; empty input → counts 0 and the nested dicts empty.

## Steps

- [ ] **Step 1: RED — write `tests/unit/data_layer/test_cb_zone_runs.py`**

```python
def test_blocks_counts_runs_within_one_candle():
    # mask 1,1,0,1 one candle, consecutive minutes -> [2, 1]
def test_blocks_split_by_candle_boundary():
    # mask 1,1,1,1 with cid 0,0,1,1 -> [2, 2]
def test_blocks_split_by_minute_gap():
    # mask 1,1,1 cid all 0, minutes 0,1,5 -> [2, 1]
def test_blocks_empty_mask_gives_no_blocks():
    # all False -> len 0, dtype int64
def test_per_candle_three_candles():
    # candle 0: 1,0,1,1 ; candle 1: 0,0,0 ; candle 2: 1
    # -> index [0, 2]; blocks [2, 1]; minutes [3, 1]; first_block_len [1, 1]
def test_per_candle_untouched_candle_absent():
    # candle 1 above is not a row (no zero row)
def test_remaining_given_streak_small():
    # lengths [3, 5], s_max 4 -> s=1: {p50 3.0 over {2,4}, p75 3.5, n 2}; s=4: {p50 1.0, n 1}; s=3: n 2 over {0,2}
def test_remaining_given_streak_beyond_every_block():
    # lengths [3], s_max 5 -> s=4 and s=5 are {"n": 0} with no p50 key
def test_summarize_matches_hand_numbers():
    # lengths [2,1,1], pc from test_per_candle_three_candles -> n_blocks 3, n_candles 2, run_len p50 1.0, mean 1.333,
    # blocks_per_candle mean 1.5, minutes_per_candle mean 2.0, first_block_len p50 1.0
def test_summarize_empty():
    # lengths [] and empty pc -> n_blocks 0, n_candles 0, run_len == {}
```

- [ ] **Step 2: Run it RED**

Run: `docker compose -p cbrun run --rm -e PYTHONDONTWRITEBYTECODE=1 ohlc_gen python -m pytest -p no:cacheprovider tests/unit/data_layer/test_cb_zone_runs.py -q`
Expected: FAIL — `ModuleNotFoundError: zone_runs` (the test adds `notebooks/zone_profitability` to `sys.path` the way `test_cb_notebook_parity.py` does for `cbnc`).

- [ ] **Step 3: Implement the four functions in `zone_runs.py`**

`blocks`: a run starts where `mask` is True and (previous row is False, or `cid` changed, or `minute` is not previous + 1); lengths by `np.diff` of start/end indices — vectorised, no Python loop over rows (2y has ~1 M rows × 24 masks).

- [ ] **Step 4: Run it GREEN** (same command). Expected: 10 passed.

- [ ] **Step 5: Stage and describe** — `git add notebooks/zone_profitability/zone_runs.py tests/unit/data_layer/test_cb_zone_runs.py`; message `feat(zone_runs): block run-length statistics for CB zones`. Wait for the user before committing.
