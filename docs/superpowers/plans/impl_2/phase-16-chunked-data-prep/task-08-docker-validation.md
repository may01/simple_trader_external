# Task 08: Docker validation — equivalence + crash-resume (acceptance gate)

**Phase:** 16 — Chunked Data Prep
**Depends on:** Tasks 01–07
**Produces:** `tests/training/test_chunked_equivalence_docker.py`; a validated 2-week run

---

## Goal

Prove the two acceptance properties on a real dataset in Docker:
1. **Equivalence** — chunked output equals single-pass output within float tolerance.
2. **Resume** — deleting one mid part and rerunning recomputes only that portion
   and yields the same final frame.

This is the gate the user named: "validate against a 2-week dataset."

---

## Files

- Create: `tests/training/test_chunked_equivalence_docker.py` (marker: `docker`)
- Test target dataset: `configs/train_dataset.env` (the 2-week `2w` set)

---

## Procedure (each step a Docker invocation)

```bash
E=configs/train_dataset.env

# 0. ensure raw data present (incremental; safe to re-run)
TRAIN_ENV=$E docker compose up graber

# 1. SINGLE-CHUNK baseline (default thresholds → 2 weeks is below CHUNK_MIN_ROWS)
TRAIN_ENV=$E docker compose up ohlc_gen
docker compose run --rm ohlc_gen python3 -c "
import shutil; from helpers import wide_df_path
shutil.copy(wide_df_path(), wide_df_path()+'.single')
print('baseline saved')
"

# 2. FORCED MULTI-CHUNK
TRAIN_ENV=$E CHUNK_SPAN_DAYS=3 CHUNK_MIN_ROWS=0 docker compose up ohlc_gen

# 3. EQUIVALENCE assertion
docker compose run --rm ohlc_gen python3 -c "
import pandas as pd
from helpers import wide_df_path
a = pd.read_pickle(wide_df_path()+'.single')
b = pd.read_pickle(wide_df_path())
pd.testing.assert_frame_equal(a, b, check_exact=False, rtol=1e-6, atol=1e-8)
print('EQUIVALENCE OK: chunked == single within tolerance')
"
```

### Crash-resume

```bash
E=configs/train_dataset.env

# 4. start forced multi-chunk, then simulate a crash by removing one mid part.
#    Easiest deterministic form: run, delete a middle FINAL part + the merged
#    output, rerun, and assert only that portion's part mtime changes.
TRAIN_ENV=$E CHUNK_SPAN_DAYS=3 CHUNK_MIN_ROWS=0 docker compose up ohlc_gen   # full run (parts cleaned)

# Re-run leaving parts in place for the resume check: temporarily disable cleanup
# via a test hook, OR run the pytest docker test below which orchestrates it.
docker compose run --rm -e PYTEST_DOCKER=1 ohlc_gen \
    python3 -m pytest tests/training/test_chunked_equivalence_docker.py -v -m docker
```

---

## Test (pytest, docker marker)

```python
# tests/training/test_chunked_equivalence_docker.py
import os, glob, shutil
import pandas as pd
import pytest

pytestmark = pytest.mark.docker

DAY = 86_400_000

def _prepare(monkeypatch, span_days, min_rows):
    monkeypatch.setenv("CHUNK_SPAN_DAYS", str(span_days))
    monkeypatch.setenv("CHUNK_MIN_ROWS", str(min_rows))
    from training.data_preparer import DataPreparer
    from helpers import graber_data_path, wide_df_path, data_attributes_path
    prep = DataPreparer(config_path=os.environ["INDICATORS_CONFIG"],
                        output_path=wide_df_path(),
                        attributes_output_path=data_attributes_path())
    prep.prepare_chunked(graber_data_path(),
                         int(os.environ["DATA_START"]), int(os.environ["DATA_END"]))

def test_chunked_equals_single(monkeypatch):
    from helpers import wide_df_path
    _prepare(monkeypatch, span_days=30, min_rows=10**12)     # single
    single = pd.read_pickle(wide_df_path()).copy()
    _prepare(monkeypatch, span_days=3, min_rows=0)           # multi
    multi = pd.read_pickle(wide_df_path())
    pd.testing.assert_frame_equal(single, multi, check_exact=False, rtol=1e-6, atol=1e-8)

def test_resume_recomputes_only_missing(monkeypatch):
    from helpers import wide_df_path, data_folder
    # run with cleanup disabled so parts survive for inspection
    monkeypatch.setenv("CHUNK_KEEP_PARTS", "1")              # honoured by _merge_parts cleanup guard
    _prepare(monkeypatch, span_days=3, min_rows=0)
    finals = sorted(glob.glob(os.path.join(data_folder(), "df_with_indicators.part_*.pkl")))
    mtimes = {p: os.path.getmtime(p) for p in finals}
    victim = finals[len(finals)//2]
    os.remove(victim); os.remove(wide_df_path())
    _prepare(monkeypatch, span_days=3, min_rows=0)           # resume
    for p in finals:
        if p == victim: assert os.path.exists(p)             # recomputed
        else: assert os.path.getmtime(p) == mtimes[p]        # untouched
```

> The resume test needs `_merge_parts` to honour a `CHUNK_KEEP_PARTS` env flag
> (skip cleanup) so parts survive for the assertion. Add that one-line guard to
> Task 06's cleanup when implementing this task; note it in the Phase README
> TECH_DEBT if it should later become test-only.

---

## Key constraints

- Tolerance: `rtol=1e-6, atol=1e-8`. Indicator math is deterministic, but
  concat/copy can perturb float dtype ordering; exact equality is not required by
  the spec (within float tolerance).
- The `2w` dataset is below the default `CHUNK_MIN_ROWS`, so step 1 exercises the
  single-chunk path naturally — no env override needed for the baseline.
- Run everything in Docker (`ohlc_gen` service) — never assert local-only, per
  layer-first rule (tests pass in Docker before the phase is done).

---

## Verification

```bash
TRAIN_ENV=configs/train_dataset.env docker compose run --rm ohlc_gen \
    python3 -m pytest tests/training/test_chunked_equivalence_docker.py -v -m docker
# expect: 2 passed (equivalence + resume)
```

---

## Commit

`test(data-prep): docker equivalence + crash-resume on 2-week dataset`
