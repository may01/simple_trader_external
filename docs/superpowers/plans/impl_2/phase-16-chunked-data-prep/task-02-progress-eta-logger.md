# Task 02: Per-portion progress + ETA logger

**Phase:** 16 — Chunked Data Prep
**Depends on:** `logs.log`
**Produces:** `training.data_preparer._ChunkProgress`

---

## Goal

A small, injectable-clock progress reporter that logs per-portion completion with
elapsed time and a linear ETA. Injectable clock makes ETA math unit-testable
without sleeping (and sidesteps non-deterministic wall-clock in tests).

---

## Files

- Modify: `training/data_preparer.py` — add `_ChunkProgress`
- Test: `tests/training/test_chunk_progress.py`

---

## Interface

```python
import time
from typing import Callable

class _ChunkProgress:
    """Logs '<pass> portion d/total  pct%  elapsed ...  ETA ...  rows=...' lines.

    now: monotonic-seconds source, injected for testability.
    """
    def __init__(self, pass_name: str, total: int,
                 *, now: Callable[[], float] = time.monotonic) -> None: ...

    def tick(self, done: int, rows: int) -> str:
        """Record that `done` of `total` portions are complete (cumulative
        `rows` processed). Log and RETURN the formatted line. ETA is
        elapsed / done * (total - done); '—' while done == 0."""
```

Format (single line, via `logs.log`):

```
pass1 base-ind  portion 12/49  24%  elapsed 8m12s  ETA 25m40s  rows=518400
```

`elapsed`/`ETA` formatted `<h>h<m>m<s>s` dropping leading zero units (e.g.
`8m12s`, `1h03m`, `45s`).

---

## Tests (RED first)

```python
# tests/training/test_chunk_progress.py
from training.data_preparer import _ChunkProgress

class _Clock:
    def __init__(self, seconds): self._s = list(seconds)
    def __call__(self): return self._s.pop(0)

def test_eta_linear_midway():
    # start t=0; after 4 portions of 49, 100s elapsed → ETA = 100/4*45 = 1125s
    clock = _Clock([0.0, 100.0])
    p = _ChunkProgress("pass1 base-ind", total=49, now=clock)
    line = p.tick(done=4, rows=4000)
    assert "portion 4/49" in line
    assert "8%" in line              # 4/49 → 8%
    assert "elapsed 1m40s" in line   # 100s
    assert "ETA 18m45s" in line      # 1125s

def test_first_tick_no_div_by_zero():
    clock = _Clock([0.0, 0.0])
    p = _ChunkProgress("pass2 class-ind", total=10, now=clock)
    line = p.tick(done=0, rows=0)
    assert "ETA —" in line

def test_rows_reported():
    clock = _Clock([0.0, 10.0])
    p = _ChunkProgress("pass1 base-ind", total=2, now=clock)
    assert "rows=129600" in p.tick(done=1, rows=129600)
```

Run RED: `pytest tests/training/test_chunk_progress.py -v` → FAIL.

---

## Key constraints

- Inject the clock via `now=`; never call `time.monotonic()` directly inside
  `tick` (tests stub it, and it keeps ETA math pure).
- ETA is intentionally linear (`elapsed/done × remaining`) — portions are roughly
  equal-sized, so this is honest. Do not over-model.
- Emit through `logs.log` (stdout + timestamp) so docker logs capture it.
- `total == 0` is a caller error (no portions); guard by logging nothing and
  returning "" rather than dividing.

---

## Verification

```bash
docker compose run --rm ohlc_gen python3 -c "
from training.data_preparer import _ChunkProgress
clk=iter([0.0,100.0]); p=_ChunkProgress('pass1 base-ind',49,now=lambda:next(clk))
print(p.tick(4,4000))
"
```

---

## Commit

`feat(data-prep): injectable-clock chunk progress + ETA logger`
