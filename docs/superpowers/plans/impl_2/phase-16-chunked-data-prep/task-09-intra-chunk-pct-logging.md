# Task 09: Intra-chunk 1% progress logging

**Phase:** 16 — Chunked Data Prep
**Depends on:** Task 03/05 (`_compute_tf_rows` per-row loop), `logs.log`
**Produces:** `training.data_preparer._PctProgress`; progress wiring inside `_compute_tf_rows`

---

## Goal

Portion-boundary logging (`_ChunkProgress`) leaves the **inside** of a portion
silent: `_compute_tf_rows` (the expensive per-row loop) emits nothing until the
whole portion finishes — a multi-hour blackout on big spans. Log a line each time
the loop completes **1% of its rows** so progress is visible throughout.

Granularity is **per work unit** — one `(tf, row-slice)`. Serial mode → one
`0→100%` stream per timeframe; parallel mode → each fork worker reports its own
slice's 1% (worker stdout is the parent's). Logging only; output unchanged.

---

## Files

- Modify: `training/data_preparer.py` — add `_PctProgress`; tick it in `_compute_tf_rows`
- Test: `tests/unit/data_layer/test_chunk_pct_progress.py`

---

## Interface

```python
class _PctProgress:
    """Logs once each time an integer percent of a chunk's rows is reached."""
    def __init__(self, total: int, label: str,
                 *, log: "Callable[[str], None] | None" = None) -> None: ...
    def tick(self, done: int) -> None: ...
        # logs "<label> <pct>% (<done>/<total>)" when floor(done*100/total) increases
```

`_compute_tf_rows` builds `_PctProgress(len(rows), f"[prepare] indic tf={tf} n={len(rows)}")`
and calls `tick(i)` once per processed row.

---

## Tests (TDD — one behavior per cycle)

```python
# tests/unit/data_layer/test_chunk_pct_progress.py
def test_logs_once_per_percent_crossing():
    lines = []; p = _PctProgress(200, "x", log=lines.append)
    for d in range(1, 201): p.tick(d)
    assert len(lines) == 100

def test_log_line_format():
    lines = []; _PctProgress(100, "pass1 tf=15", log=lines.append).tick(1)
    assert lines == ["pass1 tf=15 1% (1/100)"]

def test_total_zero_is_noop(): ...            # total<=0 → no log, no div-by-zero
def test_done_zero_no_log(): ...
def test_small_total_logs_each_new_percent():  # total=4 → 25/50/75/100, in order
    ...
def test_no_duplicate_percent_logs(): ...      # same percent never logged twice

def test_compute_tf_rows_emits_pct_progress(monkeypatch):
    # mock indicators (mirror _run_indicator_pass tests); capture logs.log
    # 200 rows → 100 "tf=1 ...%" lines
    ...
```

RED first per cycle; B1 (percent-crossing) is the tracer, B7 (the
`_compute_tf_rows` integration) drives the wiring.

---

## Key constraints

- `tick` is O(1) integer math — negligible against ~0.13 s/row talib cost.
- Default log target is `logs.log` (resolved lazily so tests can inject a capture
  list). Workers inherit the parent's stdout via fork, so their lines reach docker
  logs without extra plumbing.
- Additive only: no change to `results` / output ordering — the bit-identical
  guarantee from tasks 04–08 holds.

---

## Verification

```bash
# real-talib smoke: 130 rows → 100 progress lines
docker compose run --rm ohlc_gen python3 -c "
import numpy as np, pandas as pd, training.data_preparer as dp, logs
n=130; idx=pd.date_range('2024-01-01', periods=n, freq='1min', tz='UTC')
df=pd.DataFrame({'1_volume':np.random.rand(n)*100,'1_buy_volume':np.random.rand(n)*50,
                 '1_close':np.linspace(10,11,n),'1_is_closed':[True]*n}, index=idx)
caps=[]; logs.log=caps.append
dp._compute_tf_rows(df,1,df.index,['volume'])
print('pct lines:', len([l for l in caps if 'indic tf=1' in l]))
"
```

---

## Commit

`feat(data-prep): intra-chunk 1% progress logging in the per-row pass`
