# Task 03: search config migration + n_startup_trials

**Phase:** 17 — NN Training Orchestration
**Depends on:** —
**Produces:** nn_search.yaml locked values ; TrainingLoop.run reads search_config["n_startup_trials"] into TPESampler

---

## Goal

Migrate `configs/nn_search.yaml` to the locked Phase-17 starting values and thread
a new `n_startup_trials` key from that config into the Optuna `TPESampler` used by
`TrainingLoop.run`. Today the sampler is built with `TPESampler(seed=seed)` — its
startup-trial count is the optuna library default (10). Phase 17 locks it to 4
(half of `trials_per_round: 8`) so TPE switches from random sampling to its
model sooner within a single short round.

This task is two separate, independent TDD cycles:

1. **Config-only (pure-python):** the YAML carries the locked values, and `depth`
   is removed from the search space per ADR-0001 (architecture is reasoned, not
   searched). `margin` and `max_wall_clock_s` are already read by existing code
   (`trainer.py` reads `margin` at ~line 343 and passes it to `ExperimentTracker`;
   `_load_nn_search_config()` applies env overrides), so changing their values is
   pure config — no code change for those.
2. **Code (Docker):** extract the sampler construction into a thin private helper
   `TrainingLoop._make_sampler(seed)` that reads `n_startup_trials` from
   `search_config` and returns a configured `TPESampler`. `run()` calls the helper.
   This keeps the heavy `run()` path untouched while making the one config-driven
   line directly testable.

---

## Context

- `configs/nn_search.yaml` is loaded by `Trainer._load_nn_search_config()` via
  `yaml.safe_load` with env overrides (`NN_MAX_ROUNDS`, etc.). Adding a new key
  to the YAML does not require touching the loader for the value to reach
  `search_config` (it is the parsed dict). The loader does not strip unknown keys.
- `nn/training_loop.py` `run()` builds the sampler **inside** the per-round loop
  at lines 165–166 (verbatim):
  ```python
                  sampler = optuna.samplers.TPESampler(seed=seed)
                  pruner = optuna.pruners.MedianPruner()
  ```
  `seed = self.search_config.get("seed", 0)` is read at line 151. The natural
  seam is to replace line 165 with `sampler = self._make_sampler(seed)` and move
  the `n_startup_trials` read into the new helper. The `MedianPruner()` line is
  unchanged.
- Locked values (from phase README "Locked starting values" + ADR-0001/0002):
  `max_rounds 1`, `trials_per_round 8`, `n_startup_trials 4`,
  `max_wall_clock_s 3600`, `margin 0.01`. `sampler: tpe`, `pruner: median`,
  `max_compute: null`, `seed: 0` are kept. Search space keeps `lr`, `units`,
  `dropout`; `depth` is removed.
- Anything importing optuna runs in the `nn-train` Docker image. The YAML-values
  test imports only PyYAML, so it runs in the base venv (and also passes in the
  image).

---

## Files

- Modify: `main/configs/nn_search.yaml` — locked values; add `n_startup_trials: 4`;
  remove `depth` from `search_space` with a comment citing ADR-0001.
- Modify: `main/nn/training_loop.py` — add private `_make_sampler(self, seed)`;
  `run()` calls it in place of the inline `TPESampler(seed=seed)` at line 165.
  **Refactor note:** the sampler construction moves out of `run()` into
  `_make_sampler` so the config-driven `n_startup_trials` read is testable without
  invoking the heavy `run()` training path. `pruner = MedianPruner()` stays inline.
- Test: `main/tests/nn/test_search_config_values.py` (pure-python, base venv).
- Test: `main/tests/nn/test_tpe_startup.py` (Docker, imports optuna).

---

## Interface

```python
# nn/training_loop.py  (new private method on TrainingLoop)
def _make_sampler(self, seed: int) -> "optuna.samplers.TPESampler": ...
    # n_startup = int(self.search_config.get("n_startup_trials", 10))
    # return optuna.samplers.TPESampler(seed=seed, n_startup_trials=n_startup)
```

```yaml
# configs/nn_search.yaml  (target shape)
max_rounds: 1
trials_per_round: 8
n_startup_trials: 4
sampler: tpe
pruner: median
max_wall_clock_s: 3600
max_compute: null
margin: 0.01
seed: 0
search_space:
  # depth removed: architecture is reasoned, not searched (ADR-0001)
  lr: [1.0e-4, 1.0e-2]
  units: [16, 64]
  dropout: [0.0, 0.3]
```

---

## TDD steps

### Cycle 1 — config locked values (pure-python)

- [ ] **RED — write the values test.** Create
      `main/tests/nn/test_search_config_values.py`:
  ```python
  from pathlib import Path
  import yaml

  CONFIG = Path(__file__).resolve().parents[2] / "configs" / "nn_search.yaml"

  def _load():
      with CONFIG.open() as fh:
          return yaml.safe_load(fh)

  def test_locked_scalar_values():
      cfg = _load()
      assert cfg["max_rounds"] == 1
      assert cfg["trials_per_round"] == 8
      assert cfg["n_startup_trials"] == 4
      assert cfg["max_wall_clock_s"] == 3600
      assert cfg["margin"] == 0.01

  def test_kept_scalar_values_unchanged():
      cfg = _load()
      assert cfg["sampler"] == "tpe"
      assert cfg["pruner"] == "median"
      assert cfg["max_compute"] is None
      assert cfg["seed"] == 0

  def test_depth_removed_from_search_space():
      space = _load()["search_space"]
      assert "depth" not in space          # ADR-0001: architecture not searched

  def test_searched_params_present():
      space = _load()["search_space"]
      assert "lr" in space
      assert "units" in space
      assert "dropout" in space
      assert space["units"] == [16, 64]
      assert space["dropout"] == [0.0, 0.3]
  ```

- [ ] **Run RED:**
  ```bash
  cd main && .venv/bin/pytest tests/nn/test_search_config_values.py -q
  ```
  Expected: FAIL — e.g. `KeyError: 'n_startup_trials'` (key absent) and
  `assert 2 == 1` for `max_rounds`. (Pre-migration YAML has `max_rounds: 2`,
  `trials_per_round: 3`, no `n_startup_trials`, `max_wall_clock_s: 1800`,
  `margin: 0.0`, and `depth` present.)

- [ ] **GREEN — migrate the YAML.** Overwrite `main/configs/nn_search.yaml` to the
      target shape shown in **Interface** above: set `max_rounds: 1`,
      `trials_per_round: 8`, add `n_startup_trials: 4`, set
      `max_wall_clock_s: 3600` and `margin: 0.01`; keep `sampler: tpe`,
      `pruner: median`, `max_compute: null`, `seed: 0`; in `search_space` delete
      the `depth` line and add the comment
      `# depth removed: architecture is reasoned, not searched (ADR-0001)`; keep
      `lr: [1.0e-4, 1.0e-2]`, `units: [16, 64]`, `dropout: [0.0, 0.3]`.

- [ ] **Run GREEN:**
  ```bash
  cd main && .venv/bin/pytest tests/nn/test_search_config_values.py -q
  ```
  Expected: `4 passed`.

### Cycle 2 — thread n_startup_trials into the sampler (Docker)

- [ ] **RED — write the sampler test.** Create
      `main/tests/nn/test_tpe_startup.py`:
  ```python
  import optuna

  from nn.training_loop import TrainingLoop


  def _loop(search_config):
      # Construct TrainingLoop without running it; only _make_sampler is exercised.
      loop = TrainingLoop.__new__(TrainingLoop)
      loop.search_config = search_config
      return loop


  def test_optuna_param_name_is_real():
      # Guards the kwarg name against an optuna API drift.
      sampler = optuna.samplers.TPESampler(seed=0, n_startup_trials=4)
      assert sampler._n_startup_trials == 4


  def test_make_sampler_reads_config():
      loop = _loop({"n_startup_trials": 4})
      sampler = loop._make_sampler(seed=0)
      assert isinstance(sampler, optuna.samplers.TPESampler)
      assert sampler._n_startup_trials == 4


  def test_make_sampler_default_when_absent():
      loop = _loop({})  # no n_startup_trials key
      sampler = loop._make_sampler(seed=0)
      assert sampler._n_startup_trials == 10


  def test_make_sampler_captures_kwargs(monkeypatch):
      captured = {}

      class FakeSampler:
          def __init__(self, **kwargs):
              captured.update(kwargs)

      monkeypatch.setattr(optuna.samplers, "TPESampler", FakeSampler)
      loop = _loop({"n_startup_trials": 4})
      loop._make_sampler(seed=7)
      assert captured == {"seed": 7, "n_startup_trials": 4}
  ```

- [ ] **Run RED:**
  ```bash
  docker compose run --rm nn-train python -m pytest tests/nn/test_tpe_startup.py -q
  ```
  Expected: FAIL — `AttributeError: 'TrainingLoop' object has no attribute
  '_make_sampler'` for the three `_make_sampler` tests
  (`test_optuna_param_name_is_real` passes already, proving the kwarg name).

- [ ] **GREEN — add the helper.** In `main/nn/training_loop.py`, add the private
      method to `TrainingLoop`:
  ```python
      def _make_sampler(self, seed):
          n_startup = int(self.search_config.get("n_startup_trials", 10))
          return optuna.samplers.TPESampler(seed=seed, n_startup_trials=n_startup)
  ```
  Then in `run()` replace the inline construction (line 165):
  ```python
                  sampler = optuna.samplers.TPESampler(seed=seed)
  ```
  with:
  ```python
                  sampler = self._make_sampler(seed)
  ```
  Leave `pruner = optuna.pruners.MedianPruner()` (line 166) unchanged.

- [ ] **Run GREEN:**
  ```bash
  docker compose run --rm nn-train python -m pytest tests/nn/test_tpe_startup.py -q
  ```
  Expected: `4 passed`.

- [ ] **Regression — both files together in the image:**
  ```bash
  docker compose run --rm nn-train python -m pytest \
    tests/nn/test_tpe_startup.py tests/nn/test_search_config_values.py -q
  ```
  Expected: `8 passed`.

---

## Verification

```bash
# Config reaches the loop with the locked value, end to end, in the image:
docker compose run --rm nn-train python -c "
import yaml
from nn.training_loop import TrainingLoop
cfg = yaml.safe_load(open('configs/nn_search.yaml'))
loop = TrainingLoop.__new__(TrainingLoop); loop.search_config = cfg
s = loop._make_sampler(seed=cfg['seed'])
assert s._n_startup_trials == 4, s._n_startup_trials
assert 'depth' not in cfg['search_space']
print('n_startup_trials =', s._n_startup_trials, '| search_space =', sorted(cfg['search_space']))
"
```
Expected: `n_startup_trials = 4 | search_space = ['dropout', 'lr', 'units']`.

---

## Key constraints

- `_make_sampler` is the single place the `n_startup_trials` config flows into
  optuna; `run()` must not reconstruct a `TPESampler` directly. Keep its default
  (`10`) equal to optuna's library default so an absent key is a no-op.
- Do not add `depth` handling anywhere — it is removed deliberately (ADR-0001).
  `build_spec` (Task 02) tunes `units`/`lr`/`dropout` only; this config is the
  source of those bounds.
- `margin` and `max_wall_clock_s` are config-only changes here; no code reads them
  in this task (already wired in `trainer.py`/`ExperimentTracker`).

---

## Branch + Commit

Branch first, then commit only after both cycles are GREEN and the user confirms:

```bash
git checkout -b phase17-task03-search-config experimental_imp_2
# ... implement, run tests GREEN ...
git commit -m "chore(nn): migrate nn_search.yaml + expose n_startup_trials"
```
