# Task 06: report frontmatter (ReportMeta + parse/render)

**Phase:** 17 — NN Training Orchestration
**Depends on:** —
**Produces:** nn/orchestration/report.py::ReportMeta, parse_report(md)->ReportMeta, render_report(meta,body)->str

## Goal

Give the Phase 17 loop driver a machine-readable version report. Each version a skill
trains produces a `report.md` that begins with a YAML frontmatter block (the
decision fields the loop reads programmatically — accuracy, loss, per-class, the
promote/revert decision, the strike count, the next hypothesis) followed by a free
prose body (the agent's written reasoning).

This task delivers the read/write codec for that file:

- `ReportMeta` — a dataclass holding exactly the machine-readable fields.
- `parse_report(md)` — read a report string, split off the leading `---`-fenced YAML
  frontmatter, build a `ReportMeta`; raise `ValueError` if the fences or any required
  key are missing.
- `render_report(meta, body)` — emit `---\n` + `yaml.safe_dump(asdict(meta))` + `---\n\n`
  + body, so a freshly rendered report round-trips back through `parse_report`.

This is Layer B (loop-driver code). It has no dependency on torch/optuna — it is pure
PyYAML + dataclasses — so its tests run both under `main/.venv` and inside the
`nn-train` image.

## Context

`nn/orchestration/` is a new package introduced in Layer B (see phase README, Task
Index T05–T08). This task creates the package (`__init__.py`) and its first module,
`report.py`. The phase README fixes the contract for this module verbatim (README
lines under "Layer B — loop-driver"):

```python
# nn/orchestration/report.py
@dataclass
class ReportMeta:
    archetype: str
    version: int
    parent: str | None           # parent version label e.g. "v2", or None for v1
    spec_hash: str
    hypothesis: str              # what structural change this version tests
    holdout_acc: float
    holdout_loss: float
    per_class: dict              # {"up": float, "neutral": float, "down": float}
    decision: str                # "promote" | "revert" | "pending"
    strike: int
    next_hypothesis: str | None
def parse_report(md: str) -> ReportMeta: ...     # reads YAML frontmatter; raises on missing keys
def render_report(meta: ReportMeta, body: str) -> str: ...  # frontmatter + "\n" + body
```

**Frontmatter format.** The file starts with a `---\n` fence, then a YAML mapping,
then a closing `\n---\n` fence, then the prose body. `parse_report` splits on the
first two `---` fences; the YAML between them is parsed with `yaml.safe_load` into a
dict, then validated. `render_report` is the inverse: `'---\n' + yaml.safe_dump(asdict(meta)) + '---\n\n' + body`.

**Validation.** Every dataclass field name is a required frontmatter key. If the input
has no `---` fences at all (plain markdown), or the YAML mapping is missing any
required key, `parse_report` raises `ValueError`. The missing-key message is
`f"missing report keys: {sorted(missing)}"`; the no-fence message is its own
`ValueError("report has no '---' frontmatter fences")`.

**`parent` / `next_hypothesis` may be null.** They are `str | None`. In YAML, `null`
(or `~`, or empty) loads as Python `None`, which is exactly what a v1 report carries
for `parent`. No coercion is needed — `yaml.safe_load` already yields `None`.

**Types come from YAML.** `yaml.safe_load` infers types from the literal: `version: 2`
loads as `int`, `holdout_acc: 0.63` loads as `float`, the `per_class:` block loads as a
`dict[str, float]`. The dataclass does no runtime type coercion (it is a plain
`@dataclass`), so the tests assert that the YAML literals carry the right types and the
hand-written example block uses unquoted numerics.

**Round-trip.** `render_report` uses `asdict(meta)`, so the dumped YAML contains every
field. `yaml.safe_dump` writes `parent: null` for `None` and a nested mapping for
`per_class`. Feeding that straight back into `parse_report` reconstructs an equal
`ReportMeta` (compare field-by-field via `asdict`). `safe_dump` sorts keys by default;
order does not matter because `parse_report` reads by key.

Full example of a rendered report (this is exactly the shape `render_report` emits and
`parse_report` consumes — note the leading fence, the closing fence, the blank line,
then prose):

```markdown
---
archetype: cnn_lstm
version: 3
parent: v2
spec_hash: 9f1c4ad2e7b0
hypothesis: add a second conv1d block before the lstm to widen the receptive field
holdout_acc: 0.6312
holdout_loss: 0.8741
per_class:
  up: 0.71
  neutral: 0.49
  down: 0.66
decision: promote
strike: 0
next_hypothesis: try a residual skip around the lstm
---

## v3 — second conv block

Hypothesis: a second `conv1d` block before the LSTM should widen the receptive
field and lift `neutral` recall, which lagged at 0.41 in v2.

Result: holdout accuracy rose 0.6051 -> 0.6312 (margin 0.0261 > 0.01), so this
version is promoted to incumbent. `neutral` recall improved to 0.49. Next we test a
residual skip around the LSTM to ease gradient flow.
```

A v1 report differs only in the nullable fields, which serialise as `null`:

```markdown
---
archetype: cnn_lstm
version: 1
parent: null
spec_hash: 1a2b3c4d5e6f
hypothesis: baseline declared cnn_lstm archetype
holdout_acc: 0.5503
holdout_loss: 1.0212
per_class:
  up: 0.58
  neutral: 0.41
  down: 0.61
decision: pending
strike: 0
next_hypothesis: null
---

## v1 — baseline

First declared architecture for this archetype; nothing to compare against yet.
```

## Files

### Create
- `main/nn/orchestration/__init__.py` — new package marker (empty file). This task
  introduces the `nn/orchestration/` package.
- `main/nn/orchestration/report.py` — the codec: `ReportMeta`, `parse_report`,
  `render_report`. Imports: `import yaml`, `from dataclasses import asdict, dataclass`.
- `main/tests/nn/orchestration/__init__.py` — new test-package marker (empty file).
- `main/tests/nn/orchestration/test_report.py` — new test module (5 tests, one per
  behaviour below).

### Modify
- None. (No existing code calls this module yet; T07/T10 wire it in.)

## Interface

```python
# main/nn/orchestration/report.py
import yaml
from dataclasses import asdict, dataclass


@dataclass
class ReportMeta:
    archetype: str
    version: int
    parent: str | None           # e.g. "v2", or None for v1
    spec_hash: str
    hypothesis: str
    holdout_acc: float
    holdout_loss: float
    per_class: dict              # {"up": float, "neutral": float, "down": float}
    decision: str               # "promote" | "revert" | "pending"
    strike: int
    next_hypothesis: str | None


def parse_report(md: str) -> ReportMeta: ...
    # split on first two '---' fences; yaml.safe_load the block;
    # validate all field names present -> else ValueError(f"missing report keys: {sorted(missing)}");
    # no fences -> ValueError("report has no '---' frontmatter fences")


def render_report(meta: ReportMeta, body: str) -> str: ...
    # '---\n' + yaml.safe_dump(asdict(meta)) + '---\n\n' + body
```

Round-trip contract:

```python
m = ReportMeta(...)
assert parse_report(render_report(m, "## body")) == m   # @dataclass gives field-wise __eq__
```

## TDD Steps

- [ ] **Step 0: Branch for the task.**
  ```bash
  cd /home/om/projects/simple_trader/main
  git checkout experimental_imp_2
  git pull --ff-only
  git checkout -b feat/nn-report-frontmatter
  ```
  Expected: `Switched to a new branch 'feat/nn-report-frontmatter'`.

- [ ] **Step 1: RED — `render_report` shape + round-trip of a full `ReportMeta`.**
  Create `main/tests/nn/orchestration/__init__.py` as an empty file, then create
  `main/tests/nn/orchestration/test_report.py` with exactly this content:
  ```python
  from dataclasses import asdict

  import pytest

  from nn.orchestration.report import ReportMeta, parse_report, render_report


  def _meta(**over):
      base = dict(
          archetype="cnn_lstm",
          version=3,
          parent="v2",
          spec_hash="9f1c4ad2e7b0",
          hypothesis="add a second conv1d block before the lstm",
          holdout_acc=0.6312,
          holdout_loss=0.8741,
          per_class={"up": 0.71, "neutral": 0.49, "down": 0.66},
          decision="promote",
          strike=0,
          next_hypothesis="try a residual skip around the lstm",
      )
      base.update(over)
      return ReportMeta(**base)


  def test_render_report_shape_and_roundtrip():
      m = _meta()
      out = render_report(m, "## body\n\nsome prose")

      assert out.startswith("---\n")
      assert "archetype:" in out
      assert out.endswith("## body\n\nsome prose")

      reparsed = parse_report(render_report(m, "hi"))
      assert asdict(reparsed) == asdict(m)
      assert reparsed == m
  ```
  Run (pure-python, no torch):
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_report.py -q
  ```
  Expected: FAIL — `ModuleNotFoundError: No module named 'nn.orchestration'`.

- [ ] **Step 2: GREEN — create the package + `ReportMeta` + `render_report` + a stub `parse_report`.**
  Create `main/nn/orchestration/__init__.py` as an empty file. Create
  `main/nn/orchestration/report.py` with exactly this content:
  ```python
  import yaml
  from dataclasses import asdict, dataclass


  @dataclass
  class ReportMeta:
      archetype: str
      version: int
      parent: str | None
      spec_hash: str
      hypothesis: str
      holdout_acc: float
      holdout_loss: float
      per_class: dict
      decision: str
      strike: int
      next_hypothesis: str | None


  def parse_report(md: str) -> ReportMeta:
      parts = md.split("---", 2)
      if len(parts) < 3:
          raise ValueError("report has no '---' frontmatter fences")
      front = yaml.safe_load(parts[1]) or {}
      required = set(ReportMeta.__dataclass_fields__)
      missing = required - set(front)
      if missing:
          raise ValueError(f"missing report keys: {sorted(missing)}")
      return ReportMeta(**{k: front[k] for k in required})


  def render_report(meta: ReportMeta, body: str) -> str:
      front = yaml.safe_dump(asdict(meta))
      return "---\n" + front + "---\n\n" + body
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_report.py -q
  ```
  Expected: PASS — `1 passed`. (The `---\n…---\n\n` framing means `split("---", 2)`
  yields `["", "<yaml>\n", "\n\n## body…"]`; `parts[1]` is the YAML, and the prose is
  recovered after the closing fence. The round-trip is exact because `asdict(meta)`
  dumps every field and `parse_report` reads every field back by key.)

- [ ] **Step 3: RED — `parse_report` reads a hand-written frontmatter block with correct types.**
  Append to `main/tests/nn/orchestration/test_report.py`:
  ```python
  HANDWRITTEN_V3 = """---
  archetype: cnn_lstm
  version: 3
  parent: v2
  spec_hash: 9f1c4ad2e7b0
  hypothesis: add a second conv1d block before the lstm
  holdout_acc: 0.6312
  holdout_loss: 0.8741
  per_class:
    up: 0.71
    neutral: 0.49
    down: 0.66
  decision: promote
  strike: 0
  next_hypothesis: try a residual skip around the lstm
  ---

  ## v3 — second conv block

  Result: holdout accuracy rose, so this version is promoted.
  """

  HANDWRITTEN_V1 = """---
  archetype: cnn_lstm
  version: 1
  parent: null
  spec_hash: 1a2b3c4d5e6f
  hypothesis: baseline declared cnn_lstm archetype
  holdout_acc: 0.5503
  holdout_loss: 1.0212
  per_class:
    up: 0.58
    neutral: 0.41
    down: 0.61
  decision: pending
  strike: 0
  next_hypothesis: null
  ---

  ## v1 — baseline

  First declared architecture; nothing to compare against yet.
  """


  def test_parse_handwritten_types():
      m = parse_report(HANDWRITTEN_V3)
      assert m.archetype == "cnn_lstm"
      assert m.version == 3 and isinstance(m.version, int)
      assert m.parent == "v2"
      assert m.spec_hash == "9f1c4ad2e7b0"
      assert m.holdout_acc == 0.6312 and isinstance(m.holdout_acc, float)
      assert m.holdout_loss == 0.8741 and isinstance(m.holdout_loss, float)
      assert isinstance(m.per_class, dict)
      assert m.decision == "promote"
      assert m.strike == 0 and isinstance(m.strike, int)
      assert m.next_hypothesis == "try a residual skip around the lstm"


  def test_parse_handwritten_nullable_parent():
      m = parse_report(HANDWRITTEN_V1)
      assert m.parent is None
      assert m.next_hypothesis is None
      assert m.version == 1
      assert m.decision == "pending"
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_report.py -q
  ```
  Expected: PASS — `3 passed`. `yaml.safe_load` infers `int`/`float` from the unquoted
  numerics and `null` -> `None` for the nullable fields, so the parser from Step 2
  already satisfies these. If `version`/`holdout_acc` come back as `str`, the
  frontmatter quoted the value — fix the example block, NOT the assertions.

- [ ] **Step 4: RED — `parse_report` raises `ValueError` on a missing required key.**
  Append to `main/tests/nn/orchestration/test_report.py`:
  ```python
  MISSING_SPEC_HASH = """---
  archetype: cnn_lstm
  version: 2
  parent: v1
  hypothesis: drop dropout to 0.1
  holdout_acc: 0.60
  holdout_loss: 0.95
  per_class:
    up: 0.62
    neutral: 0.45
    down: 0.63
  decision: revert
  strike: 1
  next_hypothesis: null
  ---

  ## v2

  no spec_hash in the frontmatter above.
  """


  def test_parse_missing_key_raises():
      with pytest.raises(ValueError) as exc:
          parse_report(MISSING_SPEC_HASH)
      assert "missing report keys" in str(exc.value)
      assert "spec_hash" in str(exc.value)
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_report.py -q
  ```
  Expected: PASS — `4 passed`. The `missing = required - set(front)` check from Step 2
  flags `spec_hash` and raises `ValueError(f"missing report keys: ['spec_hash']")`.

- [ ] **Step 5: RED — `parse_report` raises `ValueError` on plain markdown with no fences.**
  Append to `main/tests/nn/orchestration/test_report.py`:
  ```python
  def test_parse_no_fences_raises():
      plain = "# just a heading\n\nsome prose with no frontmatter at all.\n"
      with pytest.raises(ValueError) as exc:
          parse_report(plain)
      assert "frontmatter" in str(exc.value)
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_report.py -q
  ```
  Expected: PASS — `5 passed`. `"# just a heading…".split("---", 2)` yields a single
  element (no `---` present), so `len(parts) < 3` raises the no-fence `ValueError`.

- [ ] **Step 6: RED — `per_class` round-trips as a dict of `up`/`neutral`/`down` floats.**
  Append to `main/tests/nn/orchestration/test_report.py`:
  ```python
  def test_per_class_roundtrips_as_float_dict():
      m = _meta(per_class={"up": 0.71, "neutral": 0.49, "down": 0.66})
      reparsed = parse_report(render_report(m, "body"))

      assert set(reparsed.per_class) == {"up", "neutral", "down"}
      assert reparsed.per_class == {"up": 0.71, "neutral": 0.49, "down": 0.66}
      for v in reparsed.per_class.values():
          assert isinstance(v, float)
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_report.py -q
  ```
  Expected: PASS — `6 passed`. `asdict(meta)` keeps `per_class` as a nested dict;
  `safe_dump` writes it as a nested YAML mapping and `safe_load` reads the values back
  as `float`. No code change is needed — this test pins the nested-dict behaviour so a
  later refactor (e.g. flattening per-class into top-level keys) can't silently break it.

- [ ] **Step 7: GREEN gate — full module passes inside the image.**
  The module is pure-python, but it lives under the `nn` package, so confirm it also
  passes in the GPU image (no `.venv`):
  ```bash
  cd /home/om/projects/simple_trader && docker compose run --rm nn-train \
    python -m pytest tests/nn/orchestration/test_report.py -q
  ```
  Expected: PASS — `6 passed`.

- [ ] **Step 8: GREEN gate — no regression in the nn suite.**
  ```bash
  cd /home/om/projects/simple_trader && docker compose run --rm nn-train \
    python -m pytest tests/nn -q
  ```
  Expected: PASS — the existing nn tests stay green (this task only adds a new package
  and tests; it modifies no existing module).

- [ ] **Step 9: Commit.**
  ```bash
  cd /home/om/projects/simple_trader/main
  git add nn/orchestration/__init__.py nn/orchestration/report.py \
          tests/nn/orchestration/__init__.py tests/nn/orchestration/test_report.py
  git commit -m "feat(nn): version report frontmatter"
  ```
  Expected: clean commit; `git status` shows nothing pending under `nn/orchestration/`
  or `tests/nn/orchestration/`.
