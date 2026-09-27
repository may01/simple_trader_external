# Task 07: lineage.decide (promote/revert/strike/stop)

**Phase:** 17 — NN Training Orchestration
**Depends on:** —
**Produces:** nn/orchestration/lineage.py::LineageDecision, decide(...)

## Goal

Implement the PURE decision function at the heart of the improve-loop. Given the
current best holdout score and a new version's score, `decide(...)` returns a
`LineageDecision` that says:

1. **promote vs revert** — does the candidate beat the running best by the margin?
2. **the updated strike count** AFTER this version (reset on promote, +1 on revert).
3. **whether the lineage stops** — strikes exhausted, version cap hit, or budget gone.
4. a short human-readable `reason` naming the dominant cause.

This is the gate that hill-climbs the lineage. It is the executable form of
**ADR-0002** (promote on holdout accuracy/loss, not P&L) together with the locked
operating values from the phase decisions: **K = 2** consecutive strikes,
**max_versions = 6**, **margin = 0.01**, and an **8-hour budget = 28800 s**.

`decide` is deliberately a single pure function: no torch, no filesystem, no clock.
The caller passes `elapsed_s`/`budget_s` and the current `best_score`; `decide` only
does arithmetic and string formatting. That makes every branch directly unit-testable
without spinning up a model.

## Context

ADR-0002 (`external/docs/superpowers/specs/supporting-systems/nn-training-orchestration/adr/0002-promotion-gate-accuracy.md`)
fixes the gate metric: a version is promoted or reverted on **holdout accuracy/loss**,
expressed here as a single scalar `score` (higher is better). This task does NOT
compute that score — it only compares two scores. The known "always-neutral" gaming
risk from ADR-0002 is handled elsewhere (per-class breakdown in the version report);
`decide` is intentionally agnostic to how `score` was produced.

The locked control values for the loop:

- **margin = 0.01** — minimum improvement that counts as real (not noise). The
  comparison is `>=` so a candidate that beats best by *exactly* the margin promotes.
- **K = 2** — number of *consecutive* non-improving versions (strikes) that ends a
  lineage. Strike count resets to 0 on every promote.
- **max_versions = 6** — hard cap on versions per lineage, independent of strikes.
- **budget_s = 28800** (8 h) — wall-clock cap; once elapsed reaches it the lineage
  stops regardless of the current version's outcome.

Strike semantics are about *the running streak of reverts*, so the count is updated
AFTER this version and returned in the decision. The caller threads the returned
`strike_count` into the next `decide` call.

Stop is the OR of three independent conditions, evaluated against the POST-update
strike count:

```
stop = (new_strike >= K) or (version_n >= max_versions) or (elapsed_s >= budget_s)
```

When more than one stop cause is true at once, the `reason` names them in priority
order **strikes > max_versions > budget** — but `stop` is just `True` either way; the
priority only affects which cause the human-readable message blames.

Pure-python: the module imports only `from dataclasses import dataclass`. No torch,
no IO, no clock. The test therefore runs under `main/.venv` directly — it does NOT
need the `nn-train` image:

```bash
cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_lineage.py -q
```

## Files

### Create
- `main/nn/orchestration/lineage.py` — the new module: `LineageDecision` dataclass
  and the `decide(...)` function. Pure-python; only `from dataclasses import dataclass`.
- `main/nn/orchestration/__init__.py` — package marker, created only if it does not
  already exist (so `nn.orchestration` is importable).
- `main/tests/nn/orchestration/test_lineage.py` — new test module (7 tests, one per
  behaviour below). Plain function calls, no fixtures.
- `main/tests/nn/orchestration/__init__.py` — package marker for the test dir, created
  only if it does not already exist.

## Interface

```python
# nn/orchestration/lineage.py
from dataclasses import dataclass


@dataclass
class LineageDecision:
    action: str        # "promote" | "revert"
    new_best: bool
    strike_count: int  # updated count AFTER this version
    stop: bool
    reason: str


def decide(
    *,
    best_score: float | None,
    candidate_score: float,
    margin: float,
    strike_count: int,
    K: int,
    version_n: int,
    max_versions: int,
    elapsed_s: float,
    budget_s: float,
) -> LineageDecision: ...
```

Exact semantics (the implementation must match these line for line):

```text
is_improvement = (best_score is None) or (candidate_score - best_score >= margin)
# >= so exactly-margin promotes; first version (best_score is None) always promotes

if is_improvement:
    action     = "promote"
    new_best   = True
    new_strike = 0
else:
    action     = "revert"
    new_best   = False
    new_strike = strike_count + 1

stop = (new_strike >= K) or (version_n >= max_versions) or (elapsed_s >= budget_s)

reason: short human string naming the DOMINANT cause.
  - stop by strikes        -> "stop: 2/2 strikes"            (strikes win over the rest)
  - else stop by versions  -> "stop: max_versions 6 reached"
  - else stop by budget    -> "stop: budget 28800s exceeded"
  - else promote (no stop) -> "promote: +0.0200 ≥ margin 0.0100"
  - else revert  (no stop) -> "revert: +0.0040 < margin (strike 1/2)"
```

Notes for the implementer:

- Compute `delta = candidate_score - best_score` only when `best_score is not None`;
  for the first version use a fixed promote message (e.g. `"promote: first version"`)
  since there is no prior to diff against.
- Number formatting in `reason` uses `f"{x:.4f}"` for score deltas and the margin so
  the strings read like `+0.0200`, `0.0100` (sign on the delta via `+`/`-`).
- Budget/version numbers render as plain ints in the message
  (`int(budget_s)`, `max_versions`).
- The priority chain for the message is: check strikes first, then max_versions, then
  budget; whichever fires first names the reason. `stop` itself is the plain OR — do
  not gate `stop` behind the message priority.

## TDD Steps

- [ ] **Step 0: Branch for the task.**
  ```bash
  cd /home/om/projects/simple_trader/main
  git checkout experimental_imp_2
  git pull --ff-only
  git checkout -b feat/nn-lineage-decide
  ```
  Expected: `Switched to a new branch 'feat/nn-lineage-decide'`.

- [ ] **Step 1: Create the package markers (no test yet).**
  Ensure both packages exist so the imports resolve. Create empty `__init__.py`
  files only if missing:
  ```bash
  cd /home/om/projects/simple_trader/main
  mkdir -p nn/orchestration tests/nn/orchestration
  [ -f nn/orchestration/__init__.py ] || : > nn/orchestration/__init__.py
  [ -f tests/nn/orchestration/__init__.py ] || : > tests/nn/orchestration/__init__.py
  ```
  Expected: both `__init__.py` files exist (`ls nn/orchestration tests/nn/orchestration`
  lists them). No behaviour yet.

- [ ] **Step 2: RED — first version (best_score=None) promotes.**
  Create `main/tests/nn/orchestration/test_lineage.py` with exactly this content:
  ```python
  from nn.orchestration.lineage import LineageDecision, decide


  def test_first_version_promotes():
      d = decide(
          best_score=None,
          candidate_score=0.40,
          margin=0.01,
          strike_count=0,
          K=2,
          version_n=1,
          max_versions=6,
          elapsed_s=0.0,
          budget_s=28800.0,
      )
      assert isinstance(d, LineageDecision)
      assert d.action == "promote"
      assert d.new_best is True
      assert d.strike_count == 0
      assert d.stop is False
  ```
  Run (pure-python, no torch):
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_lineage.py -q
  ```
  Expected: FAIL — `ModuleNotFoundError: No module named 'nn.orchestration.lineage'`.

- [ ] **Step 3: GREEN — create `lineage.py` with the full contract.**
  Create `main/nn/orchestration/lineage.py` with exactly this content:
  ```python
  from dataclasses import dataclass


  @dataclass
  class LineageDecision:
      action: str        # "promote" | "revert"
      new_best: bool
      strike_count: int  # updated count AFTER this version
      stop: bool
      reason: str


  def decide(
      *,
      best_score: float | None,
      candidate_score: float,
      margin: float,
      strike_count: int,
      K: int,
      version_n: int,
      max_versions: int,
      elapsed_s: float,
      budget_s: float,
  ) -> LineageDecision:
      # --- promote vs revert ------------------------------------------------
      if best_score is None:
          is_improvement = True
          delta = None
      else:
          delta = candidate_score - best_score
          is_improvement = delta >= margin

      if is_improvement:
          action = "promote"
          new_best = True
          new_strike = 0
      else:
          action = "revert"
          new_best = False
          new_strike = strike_count + 1

      # --- stop conditions (plain OR) ---------------------------------------
      stop_strikes = new_strike >= K
      stop_versions = version_n >= max_versions
      stop_budget = elapsed_s >= budget_s
      stop = stop_strikes or stop_versions or stop_budget

      # --- reason: dominant cause, priority strikes > versions > budget -----
      if stop_strikes:
          reason = f"stop: {new_strike}/{K} strikes"
      elif stop_versions:
          reason = f"stop: max_versions {max_versions} reached"
      elif stop_budget:
          reason = f"stop: budget {int(budget_s)}s exceeded"
      elif action == "promote":
          if delta is None:
              reason = "promote: first version"
          else:
              reason = f"promote: {delta:+.4f} ≥ margin {margin:.4f}"
      else:
          reason = f"revert: {delta:+.4f} < margin (strike {new_strike}/{K})"

      return LineageDecision(
          action=action,
          new_best=new_best,
          strike_count=new_strike,
          stop=stop,
          reason=reason,
      )
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_lineage.py -q
  ```
  Expected: PASS — `1 passed`.

- [ ] **Step 4: RED — a real improvement promotes and resets strikes.**
  Append to `main/tests/nn/orchestration/test_lineage.py`:
  ```python
  def test_real_improvement_promotes_and_resets_strikes():
      d = decide(
          best_score=0.40,
          candidate_score=0.42,
          margin=0.01,
          strike_count=1,          # there was a prior strike; promote must clear it
          K=2,
          version_n=3,
          max_versions=6,
          elapsed_s=1000.0,
          budget_s=28800.0,
      )
      assert d.action == "promote"
      assert d.new_best is True
      assert d.strike_count == 0   # reset on promote
      assert d.stop is False
      assert "promote" in d.reason
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_lineage.py -q
  ```
  Expected: PASS — `2 passed`. The `is_improvement` branch in Step 3 sets
  `new_strike = 0` on promote, so this goes green immediately. If it FAILS on
  `strike_count == 0`, the bug is in `lineage.py` (promote must reset, not carry the
  strike) — fix the module, not the assertion.

- [ ] **Step 5: RED — exactly-margin improvement promotes (boundary, `>=`).**
  Append:
  ```python
  def test_exactly_margin_promotes():
      # candidate - best == margin exactly -> must promote because comparison is >=
      d = decide(
          best_score=0.40,
          candidate_score=0.41,    # 0.41 - 0.40 == 0.01 == margin
          margin=0.01,
          strike_count=0,
          K=2,
          version_n=2,
          max_versions=6,
          elapsed_s=0.0,
          budget_s=28800.0,
      )
      assert d.action == "promote"
      assert d.new_best is True
      assert d.strike_count == 0
      assert d.stop is False
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_lineage.py -q
  ```
  Expected: PASS — `3 passed`. The `delta >= margin` test in Step 3 makes the
  boundary promote. NOTE: `0.41 - 0.40` is `0.009999999999999964` in IEEE-754, which
  is `< 0.01`, so a naive `>=` would WRONGLY revert here. If this test FAILS, do NOT
  relax it to `revert`: the fix is to compare with a tiny tolerance — change the
  improvement test in `lineage.py` to
  `is_improvement = delta >= margin - 1e-9` (an epsilon so exactly-margin promotes
  despite float noise). Re-run; all three pass.

- [ ] **Step 6: RED — noise below margin reverts, first strike, no stop.**
  Append:
  ```python
  def test_noise_below_margin_reverts_first_strike():
      d = decide(
          best_score=0.40,
          candidate_score=0.404,   # +0.004 < margin 0.01
          margin=0.01,
          strike_count=0,
          K=2,
          version_n=2,
          max_versions=6,
          elapsed_s=1000.0,
          budget_s=28800.0,
      )
      assert d.action == "revert"
      assert d.new_best is False
      assert d.strike_count == 1   # 0 -> 1
      assert d.stop is False        # one strike of two; lineage continues
      assert "strike 1/2" in d.reason
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_lineage.py -q
  ```
  Expected: PASS — `4 passed`.

- [ ] **Step 7: RED — second consecutive strike stops the lineage.**
  Append:
  ```python
  def test_second_strike_stops():
      d = decide(
          best_score=0.40,
          candidate_score=0.404,   # same sub-margin candidate as Step 6
          margin=0.01,
          strike_count=1,          # already one strike on the board
          K=2,
          version_n=3,
          max_versions=6,
          elapsed_s=1000.0,
          budget_s=28800.0,
      )
      assert d.action == "revert"
      assert d.strike_count == 2   # 1 -> 2 == K
      assert d.stop is True
      assert "strike" in d.reason  # strikes are the dominant stop cause
      assert "2/2" in d.reason
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_lineage.py -q
  ```
  Expected: PASS — `5 passed`. `new_strike` reaches `K`, so `stop_strikes` is true and
  the reason renders `"stop: 2/2 strikes"`.

- [ ] **Step 8: RED — max_versions backstop stops even on a promote.**
  Append:
  ```python
  def test_max_versions_backstop_stops_even_when_promoting():
      d = decide(
          best_score=0.40,
          candidate_score=0.50,    # a clear improvement -> promote
          margin=0.01,
          strike_count=0,
          K=2,
          version_n=6,             # already at the cap
          max_versions=6,
          elapsed_s=1000.0,
          budget_s=28800.0,
      )
      assert d.action == "promote"     # it still promoted the winner
      assert d.new_best is True
      assert d.strike_count == 0
      assert d.stop is True            # but the lineage ends here
      assert "max_versions" in d.reason
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_lineage.py -q
  ```
  Expected: PASS — `6 passed`. `version_n >= max_versions` forces `stop=True`
  independently of the promote, and with no strikes the reason names max_versions.

- [ ] **Step 9: RED — budget exceeded stops regardless of action.**
  Append:
  ```python
  def test_budget_exceeded_stops_regardless_of_action():
      d = decide(
          best_score=0.40,
          candidate_score=0.42,    # an improvement -> promote
          margin=0.01,
          strike_count=0,
          K=2,
          version_n=3,             # below the version cap
          max_versions=6,
          elapsed_s=28800.0,       # elapsed == budget -> exceeded (>=)
          budget_s=28800.0,
      )
      assert d.action == "promote"
      assert d.stop is True
      assert "budget" in d.reason
      assert "28800" in d.reason
  ```
  Run:
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_lineage.py -q
  ```
  Expected: PASS — `7 passed`. `elapsed_s >= budget_s` (boundary equal) sets
  `stop_budget`, and with no strikes and below the version cap the reason names budget.

- [ ] **Step 10: GREEN gate — full module green, pure-python.**
  ```bash
  cd /home/om/projects/simple_trader/main && .venv/bin/pytest tests/nn/orchestration/test_lineage.py -q
  ```
  Expected: PASS — `7 passed`.

- [ ] **Step 11: GREEN gate — no regression across the nn suite.**
  The module is pure-python and importing it pulls in `nn`, so confirm the rest of the
  nn tests still collect and pass (run inside the image since other nn tests need torch):
  ```bash
  cd /home/om/projects/simple_trader && docker compose run --rm nn-train \
    python -m pytest tests/nn/ -q
  ```
  Expected: PASS — the existing nn tests stay green; the only additions are a new
  leaf module plus two `__init__.py` markers.

- [ ] **Step 12: Commit.**
  ```bash
  cd /home/om/projects/simple_trader/main
  git add nn/orchestration/__init__.py nn/orchestration/lineage.py \
          tests/nn/orchestration/__init__.py tests/nn/orchestration/test_lineage.py
  git commit -m "feat(nn): lineage decide promote/revert/strike/stop"
  ```
  Expected: clean commit; `git status` shows nothing pending under `nn/orchestration/`
  or `tests/nn/orchestration/`.
