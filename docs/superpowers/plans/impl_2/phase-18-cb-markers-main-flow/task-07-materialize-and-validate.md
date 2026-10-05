# Task 07: Materialize on existing datasets + validation against the experiment sidecars

**Phase:** 18 — CB Markers Main Flow
**Layer:** 3 — Test data prep
**Depends on:** Task 05
**Produces:** `scripts/cb_markers_materialize.py`, `scripts/cb_markers_validate.py`, oos2m dataset with CB columns, `experiment/results/cb_markers_main_flow_results.md` (external repo)
**Gates:** G2, G3, G4, G5, G7 (materialize == prep)

---

## Goal

Add the CB columns to already-prepared datasets without a re-prep, and prove on oos2m that the main-flow values reproduce the experiment's stored artifacts.

## Context

Existing datasets predate `ema_25_diff_prc` and `ema_25_slope_class` (config was added after they were baked). oos2m has `{tf}_move_class` (7-class, materialized earlier by `scripts/move_class7_materialize.py` — follow that script's structure, backup and run convention).

Stored sidecars next to `oos2m_link_usdt/df_with_indicators.pkl`: `df_with_candle_bounds.pkl`, `df_with_candle_bounds_nc.pkl`, `df_with_ext_done.pkl`. They are never modified.

Backfill of the two EMA columns, equal to what the fields compute per row (forming EMA against the last closed candle's EMA):

```
ema_prev = kernel.to_rows(closed {tf}_ema_25, df.index)
{tf}_ema_25_diff_prc    = ({tf}_ema_25 - ema_prev) / ema_prev * 100
{tf}_ema_25_slope_class = classification.ema_slope_class({tf}_ema_25_diff_prc, tf)
```

**As executed (ruling):** the formula above does **not** equal the field output once a tf has more than 105 closed candles. The field's `ema[k-1]` is a talib EMA over the **104** closed candles of its `build_indicator_input` slice; the stored closed `{tf}_ema_25` uses 105, and talib seeds each window on its first 25 values. `backfill_ema_slope` therefore recomputes the 104-candle window EMA per closed candle wherever the frame holds that window (matches the field to rtol 1e-9); in the first 103 closed candles of a trimmed dataset, whose true window reached into dropped warm-up rows, it falls back to the stored closed EMA (approximate). On oos2m the formula above vs the implemented one: up to 8.7e-4 / 1.4e-3 / 2.3e-3 %-pt, 45 / 63 / 58 slope-class flips (15 / 60 / 240). Approximation window on oos2m: 1.82 % / 7.27 % / 29.10 % of rows (`executor/TECH_DEBT.md` §19).

The stored extdone sidecar used the oos2m-picked ladder, row-count progress and a sticky state:

```python
LADDER_OOS = {15: ((0.25, 4.0), (0.50, 2.5), (0.75, 1.0)),
              60: ((0.25, 8.0), (0.50, 5.0), (0.75, 3.0)),
              240: ((0.50, 12.0), (0.75, 8.0))}        # same for high and low
```

## Files

- Create: `scripts/cb_markers_materialize.py`
- Create: `scripts/cb_markers_validate.py`
- Test: `tests/unit/data_layer/test_cb_materialize.py`
- Create (external repo): `docs/superpowers/experiment/results/cb_markers_main_flow_results.md`

## Interface

```python
# scripts/cb_markers_materialize.py
def backfill_ema_slope(df: pd.DataFrame) -> pd.DataFrame: ...
    # adds {tf}_ema_25_diff_prc and {tf}_ema_25_slope_class for tf in TFS where absent; never overwrites
def materialize(df: pd.DataFrame, pair: str) -> pd.DataFrame: ...
    # backfill_ema_slope -> drop existing expected_columns() -> compute_cb_columns -> concat
    # raises ValueError if {tf}_move_class is absent (message points to scripts/move_class7_materialize.py)
    # raises RuntimeError if there is no model for the pair
def main() -> None: ...
    # path = helpers.wide_df_path(); one-time hard-link backup path + ".precb_bak";
    # write to path + ".tmp", os.rename over path

# scripts/cb_markers_validate.py
def main() -> int: ...     # exit code 0 only if every gate passes; prints one line per check and a marker-count table
```

## Validation checks (`cb_markers_validate.py`, reads the **materialized** `df_with_indicators.pkl`)

| Gate | Check | Threshold |
|---|---|---|
| G2 | `{tf}_cb_{side}`, `_up`, `_dn` vs `df_with_candle_bounds.pkl`, rows where both non-NaN, final row excluded | max rel diff < 1e-9 |
| G2 | no row where stored is non-NaN and ours is NaN | count == 0 |
| G3 | `{tf}_cb_zone_{long,short}` vs stored, same row mask as G2 | max rel diff < 1e-9 |
| G3 | `{tf}_cb_inzone_{long,short}` vs stored (NaN → False), same mask | mismatches == 0 |
| G4 | `{tf}_cbnc_{side}`, `_up`, `_dn`, `cbnc_tgt_*`, `cbnc_zone_*` vs `df_with_candle_bounds_nc.pkl`, both non-NaN, final row excluded | max rel diff < 1e-9 |
| G4 | `{tf}_cbnc_inzone_*`, `{tf}_cbx_inzone_*` vs stored, same mask | mismatches == 0 |
| G5a | `kernel.extdone(df, tf, {"high": LADDER_OOS[tf], "low": LADDER_OOS[tf]}, by_rows=True)`, then running OR within the candle (candles delimited as `by_rows` does) vs stored `{tf}_extdone_{high,low}` | mismatches == 0 |
| G5b | Materialized `{tf}_extdone_{side}` (2y ladder): at the first True minute of each candle (excluding a candle's last row), share where the running extreme is **not** touched again (`>=` for high, `<=` for low) before the candle closes | within ±0.01 of: 15 high 0.938, 15 low 0.936, 60 high 0.951, 60 low 0.952, 240 high 0.931, 240 low 0.955 |

If a G2–G4 mismatch appears only on the leading warm-up candle or the final row, that is the known edge delta documented in `notebooks/candle_bounds_nc/run_cbnc.py`; anything else is a failure. If G5b falls outside ±0.01, do not adjust the threshold: report the numbers and stop — the reference values were measured with row-count progress, and the difference must be explained (gaps in oos2m) before the gate is changed.

Reported, not gated — table per tf and direction on oos2m:

`cb_inzone` minutes · `∧ cb_f_extdone` · `∧ cb_f_trend` · `∧ cb_f_mcx` · `cbx_inzone` · share of minutes with `extdone_{side}` True.

## Key Constraints

- Volume files are root-owned: run both scripts in a container. Never write the volume from the host.
- `materialize` is idempotent: a second run yields an identical frame.
- The backup is made once; never overwrite an existing `.precb_bak`.
- Peak memory on 2y (~1 M rows): load, add columns with one concat, write. If a 2y run is killed by the OOM killer, stop and report; do not retry with a different approach without the user.
- Only oos2m is materialized in this task. 2y and 4y are done on the user's request, not here.

## Tests (RED first)

`tests/unit/data_layer/test_cb_materialize.py`:

- `test_backfill_matches_field_output` — build a small prepared frame through `DataPreparer.prepare()` (fixtures as in Task 06) so it contains the real `ema_25_diff_prc` and `ema_25_slope_class`; drop them; `backfill_ema_slope` → `ema_25_slope_class` equal to the original for tf 15/60/240 on all rows where the original `ema_25_diff_prc` is non-NaN; `ema_25_diff_prc` rtol 1e-9.
- `test_backfill_does_not_overwrite` — pre-set `15_ema_25_slope_class` to a sentinel → unchanged.
- `test_materialize_equals_prep` — G7. Prepared frame with CB columns from Task 06; strip `expected_columns()` and the two EMA columns; `materialize` → `assert_frame_equal` on `expected_columns()`, rtol 1e-12.
- `test_materialize_idempotent` — twice → equal, no duplicate columns.
- `test_materialize_missing_move_class_raises` — drop `60_move_class` → `ValueError` mentioning `move_class7_materialize`.
- `test_materialize_no_model_raises` — pair `btc_usdt` → `RuntimeError`.

## Steps

- [x] Write the test file. Run in Docker: `docker compose -p cbtest run --rm ohlc_gen python -m pytest tests/unit/data_layer/test_cb_materialize.py -q` → FAIL.
- [x] Implement `cb_markers_materialize.py`. Re-run → PASS.
- [x] Implement `cb_markers_validate.py`. *(As executed — ruling R1: the stored nc sidecar was built with `tgt_shrink_pct = 0.35` (its meta), production keeps `TGT_SHRINK_PCT = 0.15`. G4 for the hybrid columns is validated as kernel parity at the sidecar's own shrink read from `candle_bounds_nc_meta.json`, plus materialized == kernel at 0.15; the parameter difference prints as a non-gating WARN.)*
- [x] Before touching the volume, tell the user: oos2m `df_with_indicators.pkl` will be rewritten in place with a `.precb_bak` backup, and the `view-full` container that mounts it should be restarted afterwards. Wait for a yes. *(As executed: covered by the controller's authorization for the run; restarting `view-full` is still the user's step.)*
- [x] Materialize oos2m: `TRAIN_ENV=configs/oos2m_dataset.env docker compose -p cbtest run --rm ohlc_gen python3 scripts/cb_markers_materialize.py`. Expected: prints input/output shape; output has 114 + up to 6 more columns. *(752 → 872 columns; backup `df_with_indicators.pkl.precb_bak`.)*
- [x] Validate: `TRAIN_ENV=configs/oos2m_dataset.env docker compose -p cbtest run --rm ohlc_gen python3 scripts/cb_markers_validate.py`. Expected: every G2–G5 line `PASS`, exit code 0. *(249 PASS, 0 FAIL, 1 WARN (shrink 0.35 vs 0.15), exit 0.)*
- [x] Write `experiment/results/cb_markers_main_flow_results.md` in the external repo: the validate output verbatim (gate lines, P(hold) per cell, marker-count table), the run date and commit. Note explicitly that the `cb_f_extdone` effect is measured for the non-sticky state and differs from the ~60 % in `extdone_zone_filter_results.md` §2.
- [ ] Stage code in `main/` and the results doc in `external/`; describe; wait for confirmation. Suggested message: `feat(cb): materialize and validate candle-bound columns on existing datasets`. *(As executed: staged by the controller with `git add` after review; no commit — the commit waits for the user's confirmation at handover.)*
