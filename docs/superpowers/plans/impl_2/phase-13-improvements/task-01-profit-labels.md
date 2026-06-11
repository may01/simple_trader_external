# Task 01: Profit Labels (lookahead entry labels)

**Phase:** 13 — Improvements
**Depends on:** Phase 03 (data layer — wide DataFrame), Phase 09 Task 02 (DataPreparer, consumer)
**Produces:** `indicators/labels.py` — lookahead profit labels for training and backtest evaluation

---

## Goal

Implement binary lookahead labels marking profitable long/short entry points. A point is a
profitable long entry when, within the next `N * tf` minutes, price rises more than `M * tf_atr`
before dropping more than `X * tf_atr` below entry. Short is the exact mirror.

Labels look into the future by construction — they are training/backtest targets, never features.

---

## Context

The `IndicatorField` framework cannot host these labels: `build_indicator_input()` feeds
`compute()` a ≤105-row slice ending at "now", so future rows are physically absent. Labels
therefore live in a **standalone module** operating on the full wide DataFrame, called only by
the training data prep / backtest evaluation paths. This is also the leak barrier: the module is
not in `indicators_config.yaml`, not in the field registry, and must never be imported by the
live path (`pybtctr.py` / Robot).

Future scanning uses **1-minute candles** (`1_high` / `1_low` columns of the wide df), not tf
candles. This shrinks the intra-bar ambiguity window to one minute. Within a single 1-minute bar
where both target and stop are touched, the **stop wins** (pessimistic tie rule).

Partially resolves the README "Unresolved: NN target labeling" item: threshold is ATR-relative,
horizon is `N` tf-candles, encoding is binary per direction.

---

## Files

- Create: `indicators/labels.py`
- Create: `tests/test_phase13_task01_profit_labels.py`

---

## Docker Entry Point

No new compose service. Labels are computed inside Path B / Path D1 data prep (`trainer`
service). Ground-truth invocation:

```bash
docker compose run --rm trainer python3 -c "
from indicators.labels import add_profit_labels
print('labels importable')
"
```

---

## Interface

```python
# indicators/labels.py — lookahead labels. NEVER import from live path.

def profit_long(
    wide_df: pd.DataFrame, tf: int, n: int, m: float, x: float, atr_period: int = 14,
) -> pd.Series: ...

def profit_short(
    wide_df: pd.DataFrame, tf: int, n: int, m: float, x: float, atr_period: int = 14,
) -> pd.Series: ...

def add_profit_labels(
    wide_df: pd.DataFrame, tf: int, n: int, m: float, x: float, atr_period: int = 14,
) -> None: ...
```

- `wide_df` — full-history wide DataFrame (1-minute DatetimeIndex, `{tf}_*` columns).
- Returned Series aligned to the full 1-minute index: values only at rows where
  `{tf}_is_closed`, NaN elsewhere.
- `add_profit_labels` appends both columns in place:
  - `{tf}_plong_n{N}_m{M}_x{X}`
  - `{tf}_pshort_n{N}_m{M}_x{X}`
  - number formatting: ints verbatim; floats with dot→`p` (e.g. `x=1.5` → `x1p5`).

---

## Semantics (long; short is mirrored)

1. Entry rows: every row where `{tf}_is_closed`. Entry price = `{tf}_close` at that row.
2. `tf_atr` = ATR(`atr_period`) computed internally on tf closed candles
   (talib on `{tf}_high/low/close` at closed rows), value taken at the entry bar.
3. Window: the next `N * tf` 1-minute rows strictly after the entry row.
4. Target = `entry + m * atr`; stop = `entry − x * atr` (short: target below, stop above).
5. Label **1** iff the first minute where `1_high > target` comes strictly before the first
   minute where `1_low < stop`. Stop first, same minute, or neither touched → **0**.
   Strict `>` / `<` comparisons.
6. NaN when: window extends past end of data (incomplete future), or ATR is NaN (warmup).

---

## Implementation

Two implementations, identical semantics:

- **A (production, `indicators/labels.py`):** vectorized —
  `np.lib.stride_tricks.sliding_window_view` over the `1_high` / `1_low` arrays (zero-copy
  view), rows picked at entry positions, compared against per-entry target/stop, first-touch
  index via `argmax` along the window axis. Entry rows processed in chunks (~10k) to cap peak
  memory (tf=1440, N=10 → 14 400-wide windows).
- **B (reference, test file only):** naive per-entry Python loop walking 1-minute bars in
  order. Trivially auditable; used as the oracle.

---

## Integration test → data layer (RED in Docker)

Wire the real wide-df builder to the label module before implementing:

```python
def test_labels_on_wide_df():
    # _build_wide_df from data.py on synthetic 1-min OHLCV
    wide = _build_wide_df(synthetic_ohlcv_df)
    s = profit_long(wide, tf=15, n=4, m=2.0, x=1.0)
    assert s.index.equals(wide.index)
    assert s[~wide["15_is_closed"].astype(bool)].isna().all()
    assert s.dropna().isin([0, 1]).all()
```

---

## Unit tests

Hand-built 1-minute price paths (deterministic, small):

- Target touched, stop never → 1.
- Stop touched first, target later → 0.
- Both in same minute → 0 (pessimistic tie).
- Neither touched in window → 0.
- Window truncated by end of data → NaN.
- ATR warmup rows → NaN.
- Short mirror of each case above.
- Property test: A ≡ B exactly on random-walk data, long + short,
  several `(tf, n, m, x)` combos including `tf=15` and `tf=60`.
- Column naming: `add_profit_labels(..., x=1.5)` produces `15_plong_n4_m2_x1p5`.

All RED before implementation starts; GREEN in Docker before task completion.

---

## Key Constraints

- Module operates on the **full** wide df — never on `DataPoint.get_df()` slices.
- No registration in `indicators_config.yaml` or the field registry — labels must be
  unreachable from `Indicators.compute()` / the live path.
- Future scan on 1-minute candles only; tf candles used solely for entry close + ATR.
- Pessimistic tie rule is non-negotiable: same-minute target+stop → 0.
- NaN (not 0) for incomplete windows — training must be able to drop them.

---

## Verification

```bash
docker compose run --rm trainer python3 -m pytest tests/test_phase13_task01_profit_labels.py -v
```

---

## Commit

`feat: add lookahead profit labels (plong/pshort) for training targets`
