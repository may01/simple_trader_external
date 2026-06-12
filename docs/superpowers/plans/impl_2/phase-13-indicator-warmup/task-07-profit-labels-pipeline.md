# Task 07: Profit Labels → Data-Preparation Pipeline

**Phase:** 13 — Indicator Warmup (continuation)
**Depends on:** `indicators/labels.py` (commit `5e83bf2`, 37 unit tests green), Task 02 (warmup trim)
**Produces:** `{tf}_plong_*` / `{tf}_pshort_*` (and strict `{tf}_pslong_*` / `{tf}_psshort_*`) columns in `df_with_indicators.pkl`, driven by a new `labels:` config section
**Branch:** `profit-labels-pipeline` (off `experimental_imp_2`)

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
      m: 2.0       # target in ATRs
      x: 1.0       # stop in ATRs
      atr_period: 14
      # strict adds: l (1-min lookback rows), y (clean-dip ATRs)
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
    atr_period: int
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
