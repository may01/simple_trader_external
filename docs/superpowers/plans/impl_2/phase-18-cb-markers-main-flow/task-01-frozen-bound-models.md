# Task 01: Frozen bound models (export + numpy predict)

**Phase:** 18 — CB Markers Main Flow
**Depends on:** `notebooks/candle_bounds_nc/cbnc.py` (`fit_side`, `FEATURES`), stored `candle_bounds_meta.json`
**Produces:** `indicators.candle_bounds.params`, `indicators.candle_bounds.models` (`BoundModel`, `ModelSet`, `models_path`, `load_models`), `indicators/candle_bounds/models_link_usdt.json`, `scripts/cb_export_models.py`
**Gate:** G1

---

## Goal

Freeze the six Ridge bound models (tf 15/60/240 × high/low) into a JSON file and predict from it with numpy, so nothing at runtime needs scikit-learn or refits.

## Context

`cbnc.fit_side` fits `make_pipeline(StandardScaler(), Ridge(alpha=1.0))` on the closed candles of `2y_az_link_usdt` every time it runs. Only `band_pct` was ever persisted (`candle_bounds_meta.json` next to the oos2m dataset). scikit-learn is not in the `simple_trader` image.

A fitted pipeline predicts `((x - scaler.mean_) / scaler.scale_) @ ridge.coef_ + ridge.intercept_`.

## Files

- Create: `indicators/candle_bounds/__init__.py` (empty)
- Create: `indicators/candle_bounds/params.py`
- Create: `indicators/candle_bounds/models.py`
- Create: `indicators/candle_bounds/models_link_usdt.json` (script output, committed)
- Create: `scripts/cb_export_models.py`
- Test: `tests/unit/data_layer/test_cb_models.py`

## Interface

```python
# indicators/candle_bounds/params.py
TFS: tuple[int, ...] = (15, 60, 240)
SIDES: tuple[str, ...] = ("high", "low")
DIRECTIONS: tuple[str, ...] = ("long", "short")
FEATURES: list[str] = [
    "R_position", "R_slope", "R_distance",
    "M_position", "M_slope", "M_distance",
    "A_position", "A_slope",
    "V_std12", "V_absmean12", "V_range", "V_body",
    "P_z1", "P_z2", "P_rm",
]
ZONE_FRAC: float = 0.05
TGT_SHRINK_PCT: float = 0.15
ATR_COL: str = "1_atr_14_ma_5"
EXTDONE_LADDER: dict[int, dict[str, tuple[tuple[float, float], ...]]] = {
    15:  {"high": ((0.25, 5.0), (0.50, 2.5), (0.75, 1.5)), "low": ((0.25, 4.0), (0.50, 2.5), (0.75, 1.5))},
    60:  {"high": ((0.25, 10.0), (0.50, 8.0), (0.75, 4.0)), "low": ((0.25, 10.0), (0.50, 6.0), (0.75, 4.0))},
    240: {"high": ((0.75, 8.0),), "low": ((0.75, 8.0),)},
}

# indicators/candle_bounds/models.py
@dataclass(frozen=True)
class BoundModel:
    tf: int
    side: str
    mean: np.ndarray
    scale: np.ndarray
    coef: np.ndarray
    intercept: float
    band_pct: float
    n_train: int
    def predict_pct(self, X: np.ndarray) -> np.ndarray: ...   # X shape (n, 15), FEATURES order

ModelSet = dict[tuple[int, str], BoundModel]

def models_path(pair: str) -> str: ...            # <package dir>/models_{pair}.json
def load_models(pair: str) -> ModelSet | None: ...  # None when the file does not exist; cached per pair
```

JSON layout (one object per `"{tf}_{side}"` key, plus a header):

```json
{
  "pair": "link_usdt", "train": "2y_az", "features": ["R_position", "..."],
  "models": {
    "15_high": {"mean": [15 floats], "scale": [15 floats], "coef": [15 floats],
                "intercept": 0.0, "band_pct": 0.308983, "n_train": 70150}
  }
}
```

`scripts/cb_export_models.py --train <pkl> --meta <json> --out <json>`: fits each `(tf, side)` with `cbnc.fit_side`, then **aborts with non-zero exit** unless, for every model:

- `abs(band_pct - meta[f"{tf}_{side}"]["band_pct"]) / stored < 1e-3`
- `max(abs(numpy_pred - pipe.predict(X_train))) < 1e-12`

It prints one line per model with both numbers, then writes the JSON.

## Key Constraints

- `models.py` imports only `json`, `os`, `functools`, `dataclasses`, `numpy`.
- `load_models` raises `ValueError` when the file's `features` list differs from `params.FEATURES`, or when any of the six `(tf, side)` keys is missing, or an array is not length 15. A file that exists but is wrong must not look like "no model".
- `predict_pct` returns NaN for a row containing NaN (plain arithmetic; do not fill).
- The ladder values above come from `fit_extdone_ladder.py` output and were re-checked against it on 2026-10-05. Do not edit them here; Task 07 re-verifies.

## Tests (RED first)

`tests/unit/data_layer/test_cb_models.py`:

- `test_predict_matches_manual_formula` — build a `BoundModel` with hand-picked `mean`, `scale`, `coef`, `intercept`; two input rows; assert against the formula computed by hand to 1e-12.
- `test_predict_nan_row_is_nan` — one feature NaN → output NaN for that row only.
- `test_load_models_missing_file_returns_none` — `load_models("no_such_pair") is None`.
- `test_load_models_link_usdt_complete` — returns exactly 6 keys `{(15|60|240, high|low)}`, each array shape `(15,)`, `scale > 0` everywhere, `band_pct > 0`.
- `test_load_models_feature_mismatch_raises` — write a temp JSON with reordered `features`; monkeypatch `models_path`; expect `ValueError`.
- `test_load_models_missing_key_raises` — temp JSON lacking `240_low`; expect `ValueError`.
- `test_band_pct_matches_stored_meta` — `load_models("link_usdt")[(15, "high")].band_pct == pytest.approx(0.30898300437354337, rel=1e-3)` and `(15, "low")` `0.382271504309902`, `(60, "high")` `0.6307165030404358`, `(60, "low")` `0.7659954524397203`.

## Steps

- [x] Create branch and worktree (`superpowers:using-git-worktrees`), base `experimental_imp_2`.
- [x] Write `params.py` and the test file. Run: `docker compose -p cbtest run --rm ohlc_gen python -m pytest tests/unit/data_layer/test_cb_models.py -q` → FAIL (module missing).
- [x] Write `models.py`. Re-run → the two `predict` tests and `missing_file` pass; the `link_usdt` tests still fail (no JSON yet).
- [x] Write `scripts/cb_export_models.py`.
- [x] Run the export. It needs scikit-learn and read access to the volume. No such environment is known to exist on the host (`python3 -c "import sklearn"` fails there); create a scratch venv (`python3 -m venv <scratchpad>/cbenv && <scratchpad>/cbenv/bin/pip install scikit-learn pandas numpy`) and run the command from the phase README. If the volume is unreadable or the install is not permitted, stop and hand the command to the user. *(As executed: no host venv — the export ran inside the `ohlc_gen` container with scikit-learn pip-installed into a throwaway `--target` directory under the worktree's `.superpowers/`, same pandas as the pickles.)*
- [x] Confirm the script printed 6 lines, all within both thresholds (G1). Record the printed numbers in the task report. *(G1 passed: `band_pct` rel ≤ 2.9e-16, max_pred_diff 0.0; n_train 70,157 / 17,529 / 4,373. Numbers also in `experiment/results/cb_markers_main_flow_results.md`.)*
- [x] Re-run the test file in Docker → all PASS.
- [ ] Stage `indicators/candle_bounds/`, `scripts/cb_export_models.py`, the test. Describe; wait for the user's confirmation before committing. Suggested message: `feat(cb): frozen candle-bound models with numpy predict`. *(As executed: staged by the controller with `git add` after review; no commit — the commit waits for the user's confirmation at handover.)*
