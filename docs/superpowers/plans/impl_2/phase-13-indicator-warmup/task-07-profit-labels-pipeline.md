# Task 07: Profit Labels → Data-Preparation Pipeline

**Phase:** 13 — Indicator Warmup (continuation)
**Depends on:** `indicators/labels.py` (commit `5e83bf2`, 37 unit tests green), Task 02 (warmup trim)
**Produces:** `{tf}_plong_*` / `{tf}_pshort_*` (and strict `{tf}_pslong_*` / `{tf}_psshort_*`) columns in `df_with_indicators.pkl`, driven by a new `labels:` config section
**Branch:** `profit-labels-pipeline` (off `experimental_imp_2`)

> **Update (2026-06-14, branch `labels-per-point-atr-ma`):** two semantics changes
> to `indicators/labels.py`:
> 1. **Labels on every wide row** (closed *and* forming), not only closed tf
>    candles. Each 1-min row is a candidate entry at that minute's close
>    (`{tf}_close`). The final `n*tf` rows stay NaN (no complete forward window).
> 2. **Sizing uses `atr_ma`, not raw `atr`.** Target/stop are sized from the
>    precomputed `{tf}_atr_{atr_period}_ma_{ma_length}` column (volatility
>    indicator group, per-row, forming-candle aware) read straight off the wide
>    frame — `labels.py` no longer computes ATR itself. The volatility pass must
>    run before labels (it does: `BASE_GROUPS` before `_compute_profit_labels`).
>    Missing column → clear `KeyError`. New `ma_length` config key (default 5);
>    default `atr_period=14`/`ma_length=5` matches the `atr_14_ma_5` indicator.
>
> **Update (2026-06-14, branch `swap-atr-ma5`):** replaced the `atr_14_ma_20` and
> `cci_14_ma_20` volatility/oscillator indicators with `atr_14_ma_5` / `cci_14_ma_5`
> (SMA window 5 instead of 20). Cascades: `cci_diff` now depends on `cci_14_ma_5`;
> the NN feature renamed `nn_close_diff_atr_14_ma_20` → `nn_close_diff_atr_14_ma_5`
> (and in `nn.feature_cols`); label `ma_length` default dropped 20 → 5 so labels
> read `atr_14_ma_5`. Requires dataset recompute + NN retrain (feature renamed).
>
> **Update (2026-06-15, branch `swap-atr-ma5`):** entry price is now a
> **pessimistic fill** instead of the 1-min close: a long enters at the row's
> **1-min low** (`1_low`), a short at the **1-min high** (`1_high`). Target/stop
> and the strict past-clean threshold are all measured from that entry. Side
> effect: a dip/spike on the *entry row itself* no longer dirties a strict label
> (the entry-row extreme *is* the entry), so only earlier in-window rows can.
> Changes label values → dataset recompute needed.

---

## Goal

`indicators/labels.py` is implemented and tested but has no caller — no dataset
gets labeled. Wire `add_profit_labels` / `add_profit_strict_labels` into
`DataPreparer.prepare()`, configured from `indicators_config.yaml`, so
backtest/NN datasets carry profit-label columns.

## Docker Entry Points (existing — unchanged)

```bash
TRAIN_ENV=configs/functional_dataset.env docker compose run --rm ohlc_gen   # prepare incl. labels
docker compose run --rm graber python3 -m pytest tests/                     # verification
```

## Design decisions

- **Config-driven specs.** New top-level `labels:` section in
  `indicators_config.yaml`; each entry one label family:

  ```yaml
  labels:
    - type: profit            # or profit_strict
      tfs: [15, 60]
      n: 12        # horizon in tf-candles
      m: 2.0       # target in atr_ma units
      x: 1.0       # stop in atr_ma units
      atr_period: 14   # selects the atr_{atr_period}_ma_{ma_length} column
      ma_length: 5     # SMA window of that atr_ma column (default 5)
      # strict adds: l (1-min lookback rows), y (clean-dip atr_ma units)
  ```

  Parameter values are a modeling choice — initial set goes in YAML where the
  user tunes it; the pipeline must not hardcode any.

  **Approved initial set (2026-06-13)** — each row ships as a `profit` entry
  plus a `profit_strict` entry (12 specs, 24 columns), `atr_period` default 14:

  | tf  | n | m | x   | strict l | strict y |
  |-----|---|---|-----|----------|----------|
  | 15  | 1 | 1 | 0.4 | 15       | 0.4      |
  | 15  | 2 | 1 | 0.4 | 15       | 0.4      |
  | 60  | 1 | 1 | 0.3 | 15       | 0.3      |
  | 60  | 2 | 1 | 0.3 | 15       | 0.3      |
  | 240 | 1 | 1 | 0.2 | 15       | 0.2      |
  | 240 | 2 | 1 | 0.2 | 15       | 0.2      |

- **Pipeline placement: after the warmup trim, before NN merge/stats**
  (new step between current steps 6 and 7 of `prepare()`):
  - labels are vectorized over the full frame (no per-row pass, no fork pool);
  - computing pre-trim would label ~151k warmup rows for nothing;
  - rows near DATA_END get NaN labels (insufficient future) — by design;
  - placing before `_compute_nn_attributes` lets label columns be NN targets.

- **Same frame, never features.** Columns live in `df_with_indicators.pkl`
  like the existing `targets` group, but stay out of the field registry and
  the `fields:` config section (labels.py header contract). Live path
  untouched — `LiveData` never sees labels.

## Layer 3: Test data prep (only layer touched)

### Interface

```python
# config_loader.py
@dataclass
class LabelSpecConfig:
    type: str            # "profit" | "profit_strict"
    tfs: list[int]
    n: int
    m: float
    x: float
    atr_period: int      # default 14
    ma_length: int       # default 5 — atr_{atr_period}_ma_{ma_length} column
    l: int | None        # strict only
    y: float | None      # strict only

def load_labels_config(path: str = "configs/indicators_config.yaml") -> list[LabelSpecConfig]: ...

# training/data_preparer.py
class DataPreparer:
    def _compute_profit_labels(self, df: pd.DataFrame) -> None: ...
```

### Integration test (RED in Docker, first)

`prepare()` on a small fixture with a `labels:` config containing one profit
spec → saved `df_with_indicators.pkl` contains `{tf}_plong_n…_m…_x…` and
`{tf}_pshort_…` columns whose values match calling `profit_long`/`profit_short`
directly on the same trimmed frame.

### Unit tests

- `load_labels_config`: happy path (both types), missing section → `[]`,
  strict entry without `l`/`y` → ValueError, unknown `type` → ValueError.
- `_compute_profit_labels`: one spec × multiple tfs → all columns appended;
  empty config → no-op; strict spec routes to `add_profit_strict_labels`.
- `prepare()` ordering: labels step runs after trim (label columns absent from
  any pre-trim state) and before `_compute_nn_attributes`.
- Guard: `labels.py` names never appear in `_FIELD_REGISTRY` or the config
  `fields:` section (contract test).

### Constraints / notes

- `_merge_nn_output` left-join must not collide with label columns (new-cols
  only — already the case).
- Stats files unaffected; no indicator_stats.json change.
- After merge: recalculate the 1-day dataset and verify label columns present,
  NaN only in the tail (no future) — not at DATA_START.

## Verification

- [ ] Integration + unit tests RED first, GREEN after
- [ ] Full suite green in Docker
- [ ] 1-day dataset recalculated with label columns

## Commit

`feat: config-driven profit labels in data preparation`
