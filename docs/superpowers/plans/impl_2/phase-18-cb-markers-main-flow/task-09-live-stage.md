# Task 09: Live stage — `LiveCbStage`

**Phase:** 18 — CB Markers Main Flow
**Layer:** live data layer
**Depends on:** Task 05 (`compute_cb`, `CbResult`, `required_columns`, `expected_columns`)
**Produces:** `indicators.candle_bounds.stage.LiveCbStage`, wiring in `data.LiveData`, `scripts/cb_live_parity.py`
**Gate:** G8

---

## Goal

Every live tick, compute the CB columns for the current minute with the same `compute_cb` function prep uses, and expose them through `LiveDataPoint.get(name, tf)`.

## Context

`data.LiveData.build_candles()` (line ~267) runs every tick (~1 s): fetches klines, builds one frame per tf (`self.ohlc[tf]`, up to 120 rows, index = candle open time, columns `{tf}_*`), and runs `Indicators.compute` on each. The last row of each frame is the **forming** candle with current indicator values, although live sets `{tf}_is_closed = True` on every row. Live has no wide frame: see `external/executor/TECH_DEBT.md` §15.

The stage adds **no indicator computation**. It assembles a sparse wide frame from the frames already computed:

- For each tf in `(15, 60, 240)`: one row per closed candle = `ohlc[tf].iloc[:-1]`, timestamp `candle_open + (tf − 1) min` (the candle's closing minute, as in prep), carrying that tf's columns, `{tf}_is_closed = True`.
- One row at the current minute `cur = ohlc[1].index[-1]`: for each tf the forming values from `ohlc[tf].iloc[-1]`; `{tf}_is_closed = (cur == candle_open + (tf − 1) min)`; plus `1_high`, `1_low`, `1_close`, `1_atr_14_ma_5` from `ohlc[1].iloc[-1]`.
- Rows of different tfs that share a timestamp are merged; cells with no source are NaN.

`compute_cb` on that frame gives correct last-row values for the closed bounds, zones, marker, extdone and filters. The forming bound is different: prep's `cbnc` on minute *t* is the prediction from minute *t − 1*, and live has no forming indicator values for *t − 1*. So the stage **holds** the previous minute's prediction:

```
state: minute (Timestamp | None), fresh (dict | None), held (dict | None)

update(ohlc):
    cur = ohlc[1].index[-1]
    if cur != minute:
        held  = fresh if (minute is not None and cur - minute == 1 min) else {}
        minute = cur
    result = compute_cb(build_wide(ohlc), models, nc_pred_prev=held)
    fresh  = result.nc_pred_last
    write result.columns.iloc[-1] into the last row of each ohlc[tf]
```

`held == {}` gives NaN `cbnc_*` (first minute after start, or after a gap).

**As implemented (ruling, fix round 1).** The pseudo-code above lets a `t − 2` prediction survive a failed minute and lets one tick with a stale tf frame blank the held value. Implemented instead: `fresh` is **reset at every minute change**; within a minute it is updated only for `(tf, side)` whose prediction is finite on that tick (a tf unusable on the last tick keeps the earlier same-minute prediction); at rollover `held = fresh`. Live does not call `compute_cb` on the whole sparse frame every tick: `closed_cb` and `kernel.forming_history` are cached per (tf, closed block) and each tick evaluates only the current row through `stage.tf_columns` (same kernel functions; `build_wide` stays as the reference input and the cached path is tested against `compute_cb(build_wide(...))`). A tf with fewer than `MIN_CLOSED_CANDLES = 13` closed candles (what `V_std12` needs) is also unusable (ruling; live normally holds 119).

## Files

- Modify: `indicators/candle_bounds/stage.py` — add `LiveCbStage`
- Modify: `data.py` — `LiveData.__init__` creates the stage; `build_candles` calls `update` after the indicator loop and before the `nn_res_*` join
- Create: `scripts/cb_live_parity.py`
- Test: `tests/unit/data_layer/test_cb_live_stage.py`

## Interface

```python
class LiveCbStage:
    def __init__(self, pair: str) -> None: ...          # load_models(pair); None -> stage disabled
    @property
    def enabled(self) -> bool: ...
    @staticmethod
    def build_wide(ohlc: dict[int, pd.DataFrame]) -> pd.DataFrame: ...
    def update(self, ohlc: dict[int, pd.DataFrame]) -> None: ...
```

`update` writes, for each tf in `(15, 60, 240)` and each of that tf's 38 names, column `{tf}_<name>` into `ohlc[tf]`: the last row gets the value (booleans as `1.0` / `0.0`), earlier rows NaN. `LiveDataPoint.get("cb_inzone_long", 15)` then returns `1.0` or `0.0`.

## Key Constraints

- `update` never raises into `build_candles`. In `LiveData`, wrap the call: on exception, log once per exception type with traceback and continue the tick with CB columns absent/NaN. A CB failure must not stop trading logic.
- Disabled stage (no model for the pair): `update` returns immediately, writes nothing.
- A tf whose frame is unusable gets NaN / `0.0` for all its columns while other tfs are still computed. Unusable means: missing from `ohlc`, empty, a required column absent, or its last row is not the candle containing `cur` (`ohlc[tf].index[-1] != cur.floor(f"{tf}min")` — a stale frame).
- Do not mutate or rely on live's `{tf}_is_closed` column; the stage sets its own flags in the wide frame.
- Do not change how `LiveData` fetches or computes anything else. Existing live indicator values must be unchanged.
- Per-tick cost target: under 50 ms for `update` on full frames. Measure it (see Steps); if it is higher, report the number before optimising. *(Measured 221 / 363 ms mean / p95 first; after the caching above 81 / 135 ms (max 249). Target NOT met; ruling: accepted without a second numpy implementation of the kernel maths — open decision for the user, `executor/TECH_DEBT.md` §16.)*

## Tests (RED first)

`tests/unit/data_layer/test_cb_live_stage.py`. Helper in the test file: `ohlc_from_wide(wide, t)` — from a `cb_fixtures.make_wide` frame, build the per-tf frames live would hold at minute `t`: for each tf, the closed rows up to `t` re-indexed to candle open time plus a last row with the forming values at `t` (tail 120); `ohlc[1]` = last 120 one-minute rows. Models: monkeypatch `load_models` → `make_models()`.

- `test_build_wide_rows_and_flags` — closed rows sit at `open + tf − 1 min` with `is_closed` True; last row is `cur`; `15_is_closed` on the last row is True only when `cur.minute % 15 == 14`.
- `test_build_wide_has_required_columns` — every `required_columns()` name present.
- `test_closed_bound_matches_prep` — for 30 sampled minutes `t`: `update(ohlc_from_wide(wide, t))` then `ohlc[15]["15_cb_high"].iloc[-1]` equals `compute_cb(wide, models).columns["15_cb_high"].loc[t]` (rtol 1e-9); same for `60_cb_low`, `240_cb_zone_long`.
- `test_marker_extdone_filters_match_prep` — same sampling: `cb_inzone_long`, `extdone_high`, `cb_f_extdone_long`, `cb_f_trend_short`, `cb_f_mcx_long` equal the prep row (as 1.0/0.0).
- `test_cbnc_first_minute_nan` — fresh stage, one `update` → `15_cbnc_high` NaN, `15_cbnc_inzone_long == 0.0`, `15_cbx_inzone_long == 0.0`.
- `test_cbnc_held_from_previous_minute_matches_prep` — `update` at `t − 1` then at `t` → `15_cbnc_high` at `t` equals prep's `15_cbnc_high.loc[t]` (rtol 1e-9); 20 consecutive minutes.
- `test_cbnc_stable_within_minute` — three `update` calls at the same `cur` with the forming close changed between calls → `15_cbnc_high` identical on all three (the held value does not move inside a minute).
- `test_gap_longer_than_one_minute_resets_held` — **Review Focus 2.** `update` at `t`, then at `t + 5 min` → `cbnc_*` NaN at `t + 5`; then at `t + 6` → non-NaN.
- `test_disabled_without_model` — **Review Focus 3.** `load_models` → `None`: `enabled` False; `update` adds no columns and does not raise.
- `test_short_history_tf_is_nan_others_ok` — **Review Focus 5.** `ohlc[240]` cut to 5 rows → all `240_*` CB values NaN / 0.0; `15_cb_high` still finite.
- `test_stale_tf_frame_is_nan` — `ohlc[60]` last row one candle behind `cur` → `60_*` NaN / 0.0, no exception.
- `test_missing_tf_frame` — `ohlc` without key 240 → no exception; 15 and 60 computed.
- `test_writes_only_last_row` — `ohlc[15]["15_cb_high"].iloc[:-1]` all NaN.
- `test_live_data_survives_stage_exception` — monkeypatch `LiveCbStage.update` to raise; `LiveData.build_candles()` (with the stock mocked as in `tests/unit/data_layer/test_live_data.py`) completes and `get_data_point()` works.
- `test_live_data_point_get_returns_cb_value` — with the stock mocked, after `build_candles()`, `get_data_point().get("cb_zone_long", 15)` is a float (finite once frames are long enough).

## Parity script (G8)

`scripts/cb_live_parity.py`, run on a prepared dataset that has CB columns (oos2m after Task 07):

```bash
TRAIN_ENV=configs/oos2m_dataset.env docker compose -p cbtest run --rm ohlc_gen \
    python3 scripts/cb_live_parity.py --minutes 600
```

For the last `--minutes` minutes of the dataset, one tick at the end of each minute:

1. Build the per-tf frames the way live does, from the dataset's raw 1-min OHLCV up to that minute: resample to each tf (same rule as `BinanceStock._resample_to_tf`), `tail(120)`, rename to `{tf}_*`, set `is_closed = True`, run `Indicators.compute(LiveDataPoint({tf: df}), tf)`.
2. `LiveCbStage.update(ohlc)`.
3. Compare each CB value with the prep row of that minute.

Output: per column family and tf — bool mismatch rate, float max and median relative difference — plus mean and p95 `update` time in ms.

Thresholds: the script has constants `MAX_BOOL_MISMATCH_RATE` and `MAX_FLOAT_REL_DIFF`, both `None` on first run (report only, exit 0). After the first measurement, show the numbers to the user, agree the thresholds, write them into the script and into the results doc; from then on the script exits non-zero when exceeded.

What this replay does **not** cover, state it in the results doc: live candles come from exchange klines at four base intervals, the replay resamples stored 1-min data; and live's last tick of a minute can precede the minute's final trade.

## Steps

- [x] Write the test file. Run in Docker: `docker compose -p cbtest run --rm ohlc_gen python -m pytest tests/unit/data_layer/test_cb_live_stage.py -q` → FAIL.
- [x] Implement `LiveCbStage`; wire into `LiveData`. Re-run → PASS.
- [x] Regression: `... python -m pytest tests/unit/data_layer/test_live_data.py tests/test_robot_orders.py -q` → PASS.
- [x] Write and run `cb_live_parity.py`. Record the full output in `experiment/results/cb_markers_main_flow_results.md` (external repo). *(600 ticks on oos2m: `cb_inzone_*` mismatch 0; worst bool 1/600 `15_cbnc_inzone_long` (boundary); float max rel ≤ 5.9e-5.)*
- [ ] Present the parity numbers and proposed thresholds to the user. If the bool mismatch rate on `cb_inzone_*` is not near zero, stop here: per the spec the fix belongs in live frame construction and is raised before widening this change. *(Not yet — user-gated, done by the controller at handover. Proposed: `MAX_BOOL_MISMATCH_RATE = 0.005`, `MAX_FLOAT_REL_DIFF = 2e-4`, **not agreed**.)*
- [ ] After agreement, set the two constants; re-run → exit 0. *(Not done: both constants are still `None` in `scripts/cb_live_parity.py` (report-only, exit 0).)*
- [x] Final-review fix wave (2026-10-06). *As executed (final review): an unusable tf (missing / empty / stale / short / input column absent) now writes NaN in all 38 of its columns, bools included (was 1.0/0.0 → 0.0, published as a change on every candle-boundary fetch skew); `_usable_tfs` warns once per (tf, cause) through `_warn_once`; `update` computes every tf before writing any (no partially written tick on an exception); module docstring corrected (live does not run `compute_cb`; `compute_cb(nc_pred_prev=)` / `build_wide` / `_wide` are the prep path and test/parity oracles); `LiveData` builds no stage when `PAIR` is empty/unset; golden test on the shipped `models_link_usdt.json`. Spec: unusable tf → all NaN; live `cbnc_*_std` is NaN wherever the live bound is NaN (prep may be finite in warm-up — known asymmetry). G8 replay re-run: per-column table identical (114/114 rows), worst bool 0.0017, worst float 5.899e-5.*
- [ ] Stage; describe; wait for confirmation. Suggested message: `feat(live): compute candle-bound columns every tick`. *(As executed: staged by the controller with `git add` after review; no commit — the commit waits for the user's confirmation at handover.)*
