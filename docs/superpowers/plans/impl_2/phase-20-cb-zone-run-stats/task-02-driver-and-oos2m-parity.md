# Task 02: Driver script and oos2m parity

**Phase:** 20 — CB zone run stats
**Depends on:** 01
**Produces:** `scripts/cb_zone_run_stats.py` (CLI, masks, loaders, json + md writer)
**Gates:** G2

---

## Goal

Turn a dataset into the four masks per `(tf, side)`, run Task 01's functions, write `cb_zone_run_stats.{json,md}`. Prove the masks are right by reproducing the phase-18/19 oos2m minute counts.

## Files

- Create: `scripts/cb_zone_run_stats.py`
- Test: `tests/unit/data_layer/test_cb_zone_run_stats_script.py` (mask building + integration on a synthetic frame)
- Modify (optional, if the test needs a shared fixture): `tests/unit/data_layer/cb_fixtures.py`

## Interface

```python
# scripts/cb_zone_run_stats.py
SETS: tuple[str, ...] = ("raw", "extdone", "overshoot", "entry")

def masks_from_columns(df: pd.DataFrame, tf: int, side: str) -> dict[str, np.ndarray]: ...
    # oos2m path: reads {tf}_cb_inzone_{side}, {tf}_cb_f_extdone_{side}, {tf}_cb_f_overshoot_{side}, {tf}_cb_f_trend_{side}
def masks_from_kernel(df: pd.DataFrame, cb: pd.DataFrame, tf: int, side: str) -> dict[str, np.ndarray]: ...
    # 2y path: inzone from cb; flags via kernel.extdone / kernel.overshoot / kernel.filters on df (+ cb)
def edge_mask(df: pd.DataFrame, cb: pd.DataFrame | None, tf: int, side: str) -> np.ndarray: ...
    # False on the first and last cid of the tf and on rows whose bound is NaN (spec §4 edge rule)
def load_train(ind_path: str, cb_path: str, recompute_cb: bool, pair: str) -> tuple[pd.DataFrame, pd.DataFrame]: ...
    # whole-frame load, trimmed to NEED columns; ema_25_slope_class backfill; move_class NaN if absent;
    # ATR: stored column if present else run_zone_ext.atr1_ma5 injected under params.ATR_COL (prints which)
def load_oos(oos_dir: str) -> pd.DataFrame: ...
def dataset_stats(df: pd.DataFrame, cb: pd.DataFrame | None, from_kernel: bool) -> dict: ...
    # {set: {"{tf}_{side}": summarize(..) | {"remaining_given_streak": ..}}}
def write_subset(ind_path: str, out_path: str) -> None: ...          # --make-subset (Task 03 retry path)
def render_md(report: dict) -> str: ...                              # tables + the freeze table
def main(argv: list[str] | None = None) -> int: ...
```

CLI: `--train-ind`, `--train-cb`, `--oos-dir`, `--out` (default `notebooks/zone_profitability/out`), `--skip-train`, `--recompute-cb`, `--pair` (default `PAIR` env or `link_usdt`), `--make-subset PATH` (writes the subset pickle from `--train-ind` and exits 0), `--s-max` (default 12).

`NEED` (2y trim list): `1_high`, `1_low`, `1_close`, per tf `{tf}_high`, `{tf}_low`, `{tf}_close`, `{tf}_open`, `{tf}_ema_25`, `{tf}_is_closed`, and `{tf}_ema_25_slope_class`, `{tf}_move_class`, `1_atr_14_ma_5` when present.

Freeze table in the md: rows `(tf, side)`, columns `2y C p50`, `oos2m C p50`, `2y A p50`, `2y C mean`, `2y D p50`; final line `CB_STOP_EXPECTED_POINTS=15:L/S;60:L/S;240:L/S` from `2y C p50` (one decimal).

## Steps

- [ ] **Step 1: RED — unit tests for the masks and the edge rule** (`test_cb_zone_run_stats_script.py`)

```python
def test_masks_from_columns_and_sets():
    # 6-row frame with the four flag columns: raw == inzone; extdone == inzone & f_extdone;
    # overshoot == inzone & f_overshoot; entry == overshoot & f_trend; NaN flag -> True (pass)
def test_masks_from_kernel_equals_masks_from_columns_on_fixture():
    # the phase-18 fixture frame (cb_fixtures) run through compute_cb gives flag columns;
    # masks_from_kernel(df, cb) == masks_from_columns(df_with_cb) for every set, tf 15 both sides
def test_edge_mask_drops_first_last_candle_and_nan_bound():
    # 3 candles, bound NaN on candle 1's rows -> only candle 1 rows True... (first/last dropped, NaN dropped => all False); 4 candles with finite bounds -> candles 1,2 True
def test_load_train_rebuilds_atr_when_absent(tmp_path, capsys):
    # pickle without 1_atr_14_ma_5 -> column present after load, equals run_zone_ext.atr1_ma5, stdout says "rebuilt"
def test_load_train_backfills_slope_class_and_nan_move_class(tmp_path):
    # pickle without {tf}_ema_25_slope_class / {tf}_move_class -> both present, move_class all NaN
```

- [ ] **Step 2: RED — integration test (driver → Task 01)**

```python
def test_driver_writes_json_matching_zone_runs_on_synthetic_oos(tmp_path):
    # write a small oos-shaped df_with_indicators.pkl (3 candles per tf, flags set by hand) into tmp_path/oos
    # run main(["--skip-train", "--oos-dir", str(tmp_path/"oos"), "--out", str(tmp_path/"out")]) -> 0
    # json["oos2m"]["raw"]["15_long"] == summarize(blocks(..), per_candle(..)) computed directly on the same mask
    # md contains the freeze table header and the CB_STOP_EXPECTED_POINTS line (with "n/a" for 2y cells when --skip-train)
```

- [ ] **Step 3: Run RED** — `… pytest … tests/unit/data_layer/test_cb_zone_run_stats_script.py -q` → ImportError / assertion failures.

- [ ] **Step 4: Implement `scripts/cb_zone_run_stats.py`** per the interface. Loaders mirror `scripts/cb_export_overshoot.py` (sys.path, defaults, `--recompute-cb` after injecting the backfill/NaN columns). The md writer mirrors `run_cb_overshoot.py`'s table loop.

- [ ] **Step 5: Run GREEN** — 6 passed.

- [ ] **Step 6: G2 — oos2m parity in Docker**

Run: the "oos2m only" entry point from the README. Compare the json's `oos2m.raw` and `oos2m.extdone` `n_blocks`-independent minute totals (`Σ minutes_per_candle.mean × n_candles`, printed by the script as `minutes_total`) with `cb_markers_main_flow_results.md`'s `cb_inzone` and "∧ cb_f_extdone" columns: 20936/18673/17291/14894/14352/10663 and 10056/8134/10587/7178/9474/6553. Expected: equal within one candle's rows per tf (the edge rule). Record the six pairs in the task log.

- [ ] **Step 7: Stage and describe** — message `feat(scripts): cb_zone_run_stats driver (masks, loaders, report)`. Wait for the user.
