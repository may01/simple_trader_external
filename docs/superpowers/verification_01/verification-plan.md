# Verification Plan — impl_2 Pipeline (with observed statuses and fixes)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement the FIX steps task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define the exact runtime verification procedure for the impl_2 pipeline (plan `external/docs/superpowers/plans/impl_2/`), record what each step showed when executed on branch `experimental_imp_2` (2026-06-10), and give concrete fix steps for every failing step.

**Architecture:** Verification is runtime observation at the Docker surfaces the plan defines — build the image, run each compose path in dependency order (build → graber → prepare → simulate → nn → live/frontend), capture output. Each step has: command, expected result, **observed status**, and (if failing) a fix task with exact files and code.

**Tech Stack:** Docker Compose, Python 3.12, pandas, TA-Lib (PyPI wheel), python-binance, pytest (for fix-verification only — the verification itself never substitutes tests for runtime).

**Working directory for all commands:** `main/` (the git repo root, branch `experimental_imp_2`).

---

## Verification Step 1 — Clean Docker build

- [ ] **Run:**

```bash
docker compose build graber
```

**Expected:** image `simple_trader` builds from a clean cache.

**Observed status: ❌ FAIL → ✅ FIXED 2026-06-10 (branch `fix-docker-build`, commit `501acab`)**

Original failure:

```
ERROR: Could not find a version that satisfies the requirement pandas-ta (from versions: none)
ERROR: No matching distribution found for pandas-ta
```

`pandas-ta` no longer publishes for python 3.11 (Dockerfile base `python:3.11-slim`); current releases require ≥ 3.12. Secondary fragility: the TA-Lib C source download from sourceforge failed intermittently during verification.

**Fix applied and verified:** Fix Task 1 below executed as written, plus one addition discovered at re-verification — compose services run entry scripts from subfolders (`python3 grabers/grab_binance.py`) which import top-level modules (`helpers`); without `PYTHONPATH=/code` they die with `ModuleNotFoundError: No module named 'helpers'`. Added `ENV PYTHONPATH=/code` to the Dockerfile (this also retro-corrects Verification Step 2: its original PASS relied on the harness exporting `PYTHONPATH` manually — through the real compose surface it failed until this fix). Verified post-fix: `docker compose build graber` → clean build (11.2 GB); `docker compose run --rm graber` → `No new data needed — existing range covers requested range`; `talib 0.6.8`, `tensorflow 2.21.0`, torch, pandas_ta, binance, dash all import inside the image.

### Fix Task 1: rebuild on python 3.12 with wheel-based TA-Lib and pinned requirements

**Files:**
- Modify: `Dockerfile`
- Modify: `requirements.txt`

- [x] **Step 1.1: Replace Dockerfile** — drop the C-library source build entirely; the `ta-lib` 0.6.x PyPI wheel bundles the C library (verified: `import talib` → `0.6.8` on bare `python:3.12-slim`). `ENV PYTHONPATH=/code` added at re-verification (see Observed status above).

```dockerfile
FROM python:3.12-slim

WORKDIR /code

# Entry scripts live in subfolders (grabers/...) but import top-level modules
# (helpers, constants) — make /code importable regardless of script location.
ENV PYTHONPATH=/code

# Install Python dependencies (rebuild only when requirements.txt changes).
# TA-Lib comes from the PyPI wheel (>=0.6 bundles the C library) — no source build.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Source code is mounted at /code via volume — NOT copied into image
# No CMD — every service defines its own command:
```

- [x] **Step 1.2: Pin requirements.txt** (exact versions resolved on python 3.12, 2026-06-10):

```
pandas==3.0.3
numpy==2.2.6
ta-lib==0.6.8
pandas-ta==0.4.71b0
python-binance==1.0.37
tensorflow[and-cuda]==2.21.0
keras==3.14.1
dash==4.2.0
plotly==6.8.0
kaleido==1.3.0
pyyaml==6.0.3
pytest==9.0.3
pytest-mock==3.15.1
torch==2.12.0
```

- [x] **Step 1.3: Re-run verification step**

```bash
docker compose build graber
BINANCE_API_KEY= BINANCE_API_SECRET= docker compose run --rm graber
```

Observed: clean build, full dependency set incl. tensorflow/torch (image 11.2 GB); graber service through real compose surface → `No new data needed — existing range covers requested range`.

- [x] **Step 1.4: Commit** — done: `501acab` on branch `fix-docker-build` in `main/`.

---

## Verification Step 2 — Path A: graber (phase 02)

- [ ] **Run** (volumes `simple_trader_vol`, `simple_trader_vol_long` must exist — `scripts/vol_creation.sh`):

```bash
BINANCE_API_KEY= BINANCE_API_SECRET= docker compose run --rm graber
```

**Expected:** `Saved 20161 rows to /trader_data/train/2w_link_usdt/graber_data.pkl` (env `configs/train_dataset.env`: link_usdt, 2024-01-01 → 2024-01-15) and dataset folder tree created.

**Observed status: ✅ PASS** (in workaround image; empty API keys sufficient — klines are public). Output:

```
Saved 20161 rows to /trader_data/train/2w_link_usdt/graber_data.pkl
```

Volume tree after run: `train/2w_link_usdt/{graber_data.pkl, data/, shared/nn_data/, shared/actions/}` — matches phase-02 task-00 spec.

No fix needed.

---

## Verification Step 3 — Path A probe: incremental rerun

- [ ] **Run** the same command again.

**Expected:** no re-download, idempotent.

**Observed status: ✅ PASS**

```
No new data needed — existing range covers requested range
```

No fix needed.

---

## Verification Step 4 — Entry-point wiring

- [ ] **Run:**

```bash
docker compose run --rm ohlc_gen     # → python3 trainer.py generate_full_ohlc
```

**Expected:** the real pipeline executes.

**Observed status: ❌ FAIL → ✅ FIXED 2026-06-10 for `trainer.py` (branch `fix-trainer-wiring`, commit `e3f095c`)** — `trader.py` / `view_*.py` remain stubs (Fix Task 8 scope).

Original failure — every entry point except the graber script was a phase-00 stub:

```
[stub] trainer mode=generate_full_ohlc
[stub] trader
[stub] /code/view_full.py args=['none']
```

The real orchestrator exists at `training/trainer.py` (class `Trainer`, dispatches on env var `RUN_TYPE`), but root `trainer.py` never calls it. Three vocabularies disagree: compose argv modes (`generate_full_ohlc`, `group_nn`, `nn_train`) vs `Trainer` RUN_TYPEs (`prepare_data`, `train_nn`) vs plan-README service `trainer` which does not exist in `docker-compose.yml`.

### Fix Task 4: wire root `trainer.py` to `training.Trainer`

**Files:**
- Modify: `trainer.py` (root, currently 3-line stub)

- [x] **Step 4.1: Replace root `trainer.py`** — translate compose argv modes to Trainer RUN_TYPEs:

```python
"""trainer.py — CLI entry point. Maps compose argv mode to training.Trainer RUN_TYPE."""

import os
import sys

# compose command argv → Trainer RUN_TYPE
_MODE_MAP = {
    "grab_data": "grab_data",
    "generate_full_ohlc": "prepare_data",
    "simulate": "simulate",
    "group_nn": "prepare_data",   # UNRESOLVED: no dedicated RUN_TYPE for NN grouping;
                                  # plan README "Unresolved" section — revisit with NN target labeling
    "nn_train": "train_nn",
    "simulate_nn": "simulate_nn",
    "full": "full",
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in _MODE_MAP:
        valid = ", ".join(sorted(_MODE_MAP))
        print(f"usage: trainer.py <{valid}>", file=sys.stderr)
        sys.exit(2)

    os.environ["RUN_TYPE"] = _MODE_MAP[sys.argv[1]]

    from training.trainer import Trainer
    Trainer(config_path="configs/").run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4.2: Decide `group_nn` mapping** — `Trainer` has no NN-grouping run type. Either add a `group_nn` RUN_TYPE to `training/trainer.py` or fold it into `prepare_data` (step 6 of `DataPreparer.prepare` already merges `df_with_nn.pkl`). Tracked as unresolved in plan README; do not silently guess — raise with plan owner.

- [x] **Step 4.3: Re-run verification step** — wiring itself verified 2026-06-10:

```bash
docker compose run --rm ohlc_gen
```

Observed: no `[stub]` line; real pipeline executes and stops at the known Fix-5a seam (`ValueError: graber_data.pkl is missing required columns: ['open_time']`) — exactly the expected gate state until Fix Task 5 lands. Probes: `python3 trainer.py bogus` and bare `python3 trainer.py` → usage line + exit 2.

- [x] **Step 4.4: Commit** — done: `e3f095c` on branch `fix-trainer-wiring` in `main/` (stacked on `fix-docker-build`).

**Also unresolved:** `trader.py` and `view_*.py` stubs (phases 10/12 surfaces). Real modules exist (`robots/robot.py`, `frontend/*.py`) but wiring is unspecified by any plan task — the plan never contains a "replace stub X" task. Needs new plan tasks; out of scope for this fix list.

---

## Verification Step 5 — Path B: prepare_data (phases 03–04 seam)

- [ ] **Run** (post Fix Task 4; until then, drive `training.Trainer` directly with `RUN_TYPE=prepare_data`):

```bash
docker compose run --rm ohlc_gen
```

**Expected:** `df_with_indicators.pkl` + `data_attributes.pkl` written to `/trader_data/train/2w_link_usdt/`.

**Observed status: ❌ FAIL — two independent bugs, confirmed live in order:**

**5a — graber→preparer contract mismatch:**

```
ValueError: graber_data.pkl is missing required columns: ['open_time'].
Available columns: ['o', 'h', 'l', 'c', 'v', 'close_time', 'taker_base_vol']
```

Graber writes `open_time` as the DataFrame **index** — phase-02 spec line "`open_time` | Timestamp | Candle open time (also the index)" — while `DataPreparer._load_raw_data` requires it in `raw.columns`. Graber follows spec; the preparer check is wrong.

**5b — indicator results discarded (hit after shimming 5a):**

```
KeyError: '1_vol_ma'   (in VolSellMAField.compute, indicators.py:703)
```

Root cause: `DataPreparer._run_indicator_pass` (`training/data_preparer.py:272-304`) loops over **every timestamp × tf**, wraps the wide df in `WideDataPoint`, and calls `Indicators.compute_group`. But `WideDataPoint.get_df(tf)` delegates to `build_indicator_input()` which returns a **fresh slice per call** — every computed indicator column is written into a throwaway copy. The wide DataFrame never receives any indicator column; the first field that reads a prior field's output (`vol_sell_ma` ← `vol_ma`) crashes. The loop is additionally O(n²) (20,161 timestamps × full-history slice each) — unusable at any scale even if writes landed.

### Fix Task 5a: accept spec-conformant graber output

**Files:**
- Modify: `training/data_preparer.py` (`_load_raw_data`, around line 137)
- Test: `tests/test_data_preparer.py`

- [ ] **Step 5a.1: Write the failing test**

```python
def test_load_raw_data_accepts_open_time_as_index(tmp_path):
    """Phase-02 spec: open_time is the index of graber_data.pkl."""
    idx = pd.date_range("2024-01-01", periods=3, freq="1min", tz="UTC")
    idx.name = "open_time"
    raw = pd.DataFrame(
        {"o": [1.0] * 3, "h": [1.0] * 3, "l": [1.0] * 3,
         "c": [1.0] * 3, "v": [1.0] * 3, "taker_base_vol": [0.5] * 3},
        index=idx,
    )
    path = str(tmp_path / "graber_data.pkl")
    raw.to_pickle(path)

    preparer = DataPreparer("configs/", "out.pkl", "attrs.pkl", nn_output_path="nn.pkl")
    df = preparer._load_raw_data(path)

    assert df.index.name == "open_time"
    assert list(df.columns[:4]) == ["open", "high", "low", "close"]
```

- [ ] **Step 5a.2: Run test, verify it fails** — `pytest tests/test_data_preparer.py::test_load_raw_data_accepts_open_time_as_index -v` → expected FAIL with the `ValueError` above.

- [ ] **Step 5a.3: Implement** — in `_load_raw_data`, before the column validation:

```python
        raw: pd.DataFrame = pd.read_pickle(path)

        # Phase-02 contract: open_time is the index. Normalize to a column
        # so the validation/rename below has one shape to handle.
        if "open_time" not in raw.columns and raw.index.name == "open_time":
            raw = raw.reset_index()
```

- [ ] **Step 5a.4: Run test, verify PASS.**

- [ ] **Step 5a.5: Commit** — `git commit -m "fix: accept open_time index from graber per phase-02 spec"`

### Fix Task 5b: make indicator pass write into the wide DataFrame, vectorized

**Files:**
- Modify: `training/data_preparer.py` (`_run_indicator_pass`)
- Test: `tests/test_data_preparer.py`

Design note: `Indicators.compute_group` already iterates fields in dependency order and writes `df[f"{tf}_{field.name}"] = series` into whatever `data_point.get_df(tf)` returns. The fix is to hand it a DataPoint whose `get_df` returns **the wide df itself** (mutable reference), once per tf — not a per-timestamp slice. Fields' `compute` methods are already vectorized (`.rolling(20).mean()` etc. over the whole frame).

- [ ] **Step 5b.1: Write the failing test**

```python
def test_indicator_pass_writes_columns_into_wide_df():
    idx = pd.date_range("2024-01-01", periods=120, freq="1min", tz="UTC")
    df = pd.DataFrame({
        "1_volume": np.random.rand(120) * 100,
        "1_buy_volume": np.random.rand(120) * 50,
        "1_close": np.linspace(10, 11, 120),
        # ... minimal columns required by the 'volume' group fields
    }, index=idx)

    preparer = DataPreparer("configs/", "out.pkl", "attrs.pkl", nn_output_path="nn.pkl")
    preparer._run_indicator_pass(df, groups=["volume"], tfs=[1])

    assert "1_vol_ma" in df.columns, "indicator results must land in the wide df"
    assert "1_vol_sell_ma" in df.columns, "dependent fields must see prior results"
```

- [ ] **Step 5b.2: Run test, verify it fails** — expected: `1_vol_ma` missing (current behavior) or `KeyError: '1_vol_ma'`.

- [ ] **Step 5b.3: Implement** — replace the per-timestamp loop:

```python
    def _run_indicator_pass(
        self,
        df: pd.DataFrame,
        groups: list[str],
        tfs: list[int],
    ) -> None:
        """Compute indicator groups for each tf, writing into df in place.

        Indicators.compute_group writes into data_point.get_df(tf); we hand it
        a DataPoint whose get_df returns *df itself*, so results land in the
        wide DataFrame and dependent fields see their dependencies. One call
        per tf — field.compute implementations are vectorized over the frame.
        """
        from indicators import Indicators  # lazy import

        class _WholeFrameDataPoint:
            """get_df returns the wide df itself (mutable reference)."""

            def __init__(self, frame: pd.DataFrame) -> None:
                self._frame = frame

            def get_df(self, tf: int) -> pd.DataFrame:
                return self._frame

            @property
            def timestamp(self) -> pd.Timestamp:
                return self._frame.index[-1]

        data_point = _WholeFrameDataPoint(df)
        for tf in tfs:
            Indicators.compute_group(data_point, tf, groups=groups)
```

**Caveat to validate during fix:** fields whose semantics are "closed candles + current partial row" (per plan design decision "indicators calculated at EVERY 1-min row … via build_indicator_input") may produce different values whole-frame vs per-row for non-closed rows. Cross-check a sample of `{tf}_rsi_14` values for tf=5 at non-boundary timestamps against a per-row computation before accepting this fix wholesale. If they differ, the per-row model itself needs a redesign for prep-time use — escalate to plan owner rather than ship silently different numbers.

- [ ] **Step 5b.4: Run test, verify PASS.**

- [ ] **Step 5b.5: Re-run verification step in Docker:**

```bash
docker compose run --rm ohlc_gen
```

Expected: completes; `df_with_indicators.pkl` exists and contains `{tf}_{field}` columns for all config registry fields.

- [ ] **Step 5b.6: Commit** — `git commit -m "fix: indicator pass writes into wide df; vectorized per tf"`

**Related cleanup (same task):** yaml `configs/indicators_config.yaml` declares `vol_sell_ma: depends_on: []` while the field class declares `dependencies = ["vol_ma", "vol_buy_ma"]`. Topological sort uses only the yaml. Sync the yaml (`depends_on: [vol_ma, vol_buy_ma]`) and audit all fields for the same drift — the class-level `dependencies` attribute is dead data today.

---

## Verification Step 6 — Path C: simulate (phase 08 seam)

- [ ] **Run** (post Fix Tasks 4–5):

```bash
docker compose run --rm simulate
```

**Expected:** simulation runs over `df_with_indicators.pkl`, writes `training_state.pkl` with metrics to the shared folder.

**Observed status: ❌ FAIL — three bugs in `training/trainer.py::_run_simulate`:**

1. **Confirmed live** (with planted minimal wide df): `TypeError: SimulationData.__init__() missing 3 required positional arguments: 'begin_ts', 'end_ts', and 'step_min'`. Actual signature (`data.py:340`): `SimulationData(pair, begin_ts, end_ts, step_min)` — it loads `df_with_indicators.pkl` itself; the Trainer's `pd.read_pickle` + `SimulationData(df)` is wrong on both ends.
2. **Confirmed by inspection:** `from strategy_manager import StrategyManager` → `ModuleNotFoundError`; module is `strategies/strategy_manager.py`.
3. **Confirmed by inspection:** `StrategyManager()` — actual signature (`strategies/strategy_manager.py:49`): `__init__(self, fee: float)`. Violates plan decision "fee always injected via constructor".

### Fix Task 6: rewrite `_run_simulate` against real signatures

**Files:**
- Modify: `training/trainer.py:129-165` (`_run_simulate`)
- Test: `tests/test_trainer.py`

- [ ] **Step 6.1: Write the failing test** (mock `SimulationData`/`SimulationOrchestrator`, assert construction args):

```python
def test_run_simulate_constructs_simulation_data_correctly(monkeypatch, tmp_path):
    captured = {}

    class FakeSimData:
        def __init__(self, pair, begin_ts, end_ts, step_min):
            captured["args"] = (pair, begin_ts, end_ts, step_min)

    monkeypatch.setenv("RUN_TYPE", "simulate")
    monkeypatch.setenv("PAIR", "link_usdt")
    monkeypatch.setenv("DATA_START", "1704067200000")   # ms
    monkeypatch.setenv("DATA_END", "1705276800000")     # ms
    monkeypatch.setenv("STEP_MIN", "1")
    monkeypatch.setattr("data.SimulationData", FakeSimData)
    # ... mock SimulationOrchestrator / PerformanceAnalyzer similarly

    Trainer(config_path="configs/")._run_simulate()

    assert captured["args"] == ("link_usdt", 1704067200, 1705276800, 1)  # seconds
```

- [ ] **Step 6.2: Run test, verify it fails.**

- [ ] **Step 6.3: Implement:**

```python
    def _run_simulate(self) -> None:
        """Run the backtesting simulation and analyze results."""
        from backtesting.performance_analyzer import PerformanceAnalyzer  # lazy
        from backtesting.simulation_orchestrator import SimulationOrchestrator  # lazy
        from data import SimulationData  # lazy
        from helpers import shared_folder  # lazy

        pair = os.environ["PAIR"]
        begin_ts = int(os.environ["DATA_START"]) // 1000   # env is epoch ms; SimulationData wants seconds
        end_ts = int(os.environ["DATA_END"]) // 1000
        step_min = int(os.environ.get("STEP_MIN", "1"))

        simulation_data = SimulationData(pair, begin_ts, end_ts, step_min)

        fee = float(os.environ.get("FEE", os.environ.get("EXCHANGE_FEE", "0.001")))

        def _default_strategy_factory():
            from strategies.strategy_manager import StrategyManager  # lazy
            return StrategyManager(fee)

        orch = SimulationOrchestrator(
            strategy_factory=_default_strategy_factory,
            fee=fee,
        )
        results = orch.run(simulation_data)

        analyzer = PerformanceAnalyzer(results)
        metrics = analyzer.analyze()

        shared = shared_folder()
        os.makedirs(shared, exist_ok=True)
        with open(shared + "training_state.pkl", "wb") as f:
            pickle.dump({"phase": "simulate", "metrics": metrics}, f)

        self.metadata["simulate"] = metrics
```

Notes for implementer: env files define `EXCHANGE_FEE` (`configs/train_dataset.env`), not `FEE` — hence the fallback chain; verify `SimulationOrchestrator.run(simulation_data)` signature before committing (not exercised in this verification — first surface to check when this step re-runs).

- [ ] **Step 6.4: Run test, verify PASS.**

- [ ] **Step 6.5: Re-run verification step in Docker** — `docker compose run --rm simulate` → expected: metrics dict printed/persisted, `training_state.pkl` in shared folder.

- [ ] **Step 6.6: Commit** — `git commit -m "fix: _run_simulate — real SimulationData/StrategyManager signatures, fee injection"`

---

## Verification Step 7 — Path D: NN pipeline (phase 11 seam)

- [ ] **Run** (post Fix Tasks 4–6):

```bash
docker compose run --rm prepare-nn-data && docker compose run --rm nn-train
```

**Expected:** NN data grouped, training runs, checkpoints written.

**Observed status: ❌ FAIL (by inspection; unreachable at runtime until steps 5–6 fixed):**

1. `training/trainer.py::_run_train_nn`: `from training.nn_orchestrator import NNOrchestrator` → `ModuleNotFoundError`; actual module `nn/nn_orchestrator.py`. The except-branch then **falsely** reports `"NNOrchestrator is not yet implemented (Phase 11)"` although it is implemented.
2. `NNOrchestrator(self.config_path)` — actual signature (`nn/nn_orchestrator.py:33`): `__init__(self, checkpoint_dir: str, feature_cols: list[str])`.
3. `load_nn_config(self.config_path)` in `DataPreparer` (line 261) — expects the YAML *file* path; Trainer passes a directory (and the default `"config/"` doesn't even exist — repo dir is `configs/`).

### Fix Task 7: correct NN imports, construction, and config path

**Files:**
- Modify: `training/trainer.py` (`_run_train_nn`, both import sites; `__init__` default)
- Modify: `training/data_preparer.py:261` call site or `Trainer._run_prepare_data` (pass file path)
- Test: `tests/test_trainer.py`

- [ ] **Step 7.1: Write the failing test** — assert `_run_train_nn` constructs `NNOrchestrator(checkpoint_dir, feature_cols)` from `load_nn_config("configs/indicators_config.yaml")` (mock the orchestrator, assert args).

- [ ] **Step 7.2: Run test, verify it fails** (current code raises the fake "not yet implemented" RuntimeError).

- [ ] **Step 7.3: Implement:**
  - Both imports → `from nn.nn_orchestrator import NNOrchestrator`.
  - `Trainer.__init__` default → `config_path: str = "configs/"`.
  - Construction:

```python
        from config_loader import load_nn_config  # lazy
        nn_cfg = load_nn_config(self.config_path + "indicators_config.yaml")
        orch = NNOrchestrator(
            checkpoint_dir=nn_cfg["checkpoint_dir"],
            feature_cols=nn_cfg["feature_cols"],
        )
```

  - `DataPreparer` line 261 similarly: `load_nn_config(self.config_path + "indicators_config.yaml")` — or change `DataPreparer.__init__` to take the file path explicitly and have Trainer pass it; pick one convention and apply it to **both** call sites.

- [ ] **Step 7.4: Run test, verify PASS.**

- [ ] **Step 7.5: Re-run verification step in Docker** — expected: reaches actual NN training. Note plan README "Unresolved" section: NN target labeling is undecided, so `train_nn` may legitimately stop at the missing `{tf}_target_direction` label — that is a *plan* gap, not a code bug; report it as such.

- [ ] **Step 7.6: Commit** — `git commit -m "fix: NN orchestrator import path, constructor args, config file path"`

---

## Verification Step 8 — Path E/F: live trading + viewers (phases 10/12)

- [ ] **Run:**

```bash
docker compose run --rm live        # → python3 trader.py
docker compose up view-full         # → python3 view_full.py none, port 8080
```

**Expected:** robot polling loop (paper mode) / Dash dashboard serving.

**Observed status: ❌ FAIL** — `[stub] trader`, `[stub] /code/view_full.py args=['none']`. Real modules exist (`robots/robot.py`, `robots/live_order_tracker.py`, `frontend/{chart_renderer,data_viewer,training_dashboard,live_dashboard}.py`) but no plan task ever specifies wiring them into the root entry scripts.

### Fix Task 8: write the missing wiring plan tasks first

No code fix proposed here — the wiring contract (which dashboard binds to which port/service, what `trader.py` startup sequence is, paper-mode flag) is **unspecified by the impl_2 plan**. Doing it ad hoc would repeat the seam-bug pattern this verification found.

- [ ] **Step 8.1:** Add plan tasks `phase-10-execution/task-05-trader-entry-wiring.md` and `phase-12-frontend/task-05-view-entry-wiring.md` to `external/docs/superpowers/plans/impl_2/`, each specifying: entry file, construction sequence with exact signatures (verified against code, not memory — see Steps 6–7 above for why), env vars consumed, port, and a Docker-run verification command.
- [ ] **Step 8.2:** Implement per those tasks (TDD, same step format as Fix Tasks 5–7).
- [ ] **Step 8.3:** Re-run this verification step; for `view-full` capture a screenshot of `http://localhost:8080`.

---

## Verification Step 9 — Probes (always run after fixes)

- [ ] `RUN_TYPE`/argv probes — **✅ already passing**, keep green:
  - `docker compose run --rm graber` twice → second run prints `No new data needed`.
  - bogus mode: `python3 trainer.py bogus` → must exit 2 with usage line (post Fix Task 4); raw `RUN_TYPE=bogus` → `ValueError: Unknown RUN_TYPE: 'bogus'. Expected one of: [...]` (observed working).
- [ ] Missing-data probe: run `simulate` with no `df_with_indicators.pkl` → must fail with a *clear* message naming the missing file and the producing step (current bare `FileNotFoundError` is acceptable but a `RuntimeError("run generate_full_ohlc first: ...")` wrapper is better — optional polish).
- [ ] Volume-hygiene check before any real run — delete verification artifacts:

```bash
docker run --rm -v simple_trader_vol:/td alpine \
  rm /td/train/2w_link_usdt/graber_data_fixed.pkl /td/train/2w_link_usdt/df_with_indicators.pkl
```

(`df_with_indicators.pkl` currently on the volume is a 10-row fake planted by probe; `graber_data.pkl` is real and can stay.)

---

## Execution order and gating

Fix Tasks must land in this order — each unlocks runtime observability of the next seam, mirroring the plan's own layer gates:

```
Fix 1 (build) → Fix 4 (entry wiring) → Fix 5a → Fix 5b (Path B green)
   → Fix 6 (Path C green) → Fix 7 (Path D reachable) → Fix 8 (live/view)
```

**Gate rule (restored from plan README):** after each Fix Task, re-run its Verification Step *in Docker* and do not proceed until observed output matches Expected. Unit tests in the fix steps verify the change locally; only the Docker run verifies the seam.

---

## Status summary

| Step | Surface | Status | Fix |
|------|---------|--------|-----|
| 1 | `docker compose build` | ✅ FIXED (`fix-docker-build` @ `501acab`) | Fix Task 1 — done |
| 2 | graber | ✅ PASS | — |
| 3 | graber incremental | ✅ PASS | — |
| 4 | entry-point wiring | ✅ FIXED for trainer.py (`fix-trainer-wiring` @ `e3f095c`); trader/view stubs → Fix 8 | Fix Task 4 — done (4.2 group_nn mapping still UNRESOLVED) |
| 5 | prepare_data (B) | ✅ GATE GREEN 2026-06-11: `compose run ohlc_gen` exit 0 in ~47 min; `df_with_indicators.pkl` 59 MB, 389 cols, values sane (99.7% non-NaN rsi) | Fix Tasks 5a, 5b — done |
| 6 | simulate (C) | ✅ GATE GREEN: completes over 2-week dataset, metrics → `training_state.pkl`. Required follow-up fix `3a59604` (picklable strategy factory — closure crashed all ProcessPool workers silently) | Fix Task 6 — done |
| 7 | NN pipeline (D) | ✅ wiring GREEN (CPU run): orchestrator constructed, df loaded, per-TF loop warns `Target column '{tf}_target_direction' not found — Skipping` — stops exactly at the plan's UNRESOLVED NN-labeling decision. Compose `nn-train` service itself needs an nvidia GPU (host has none) | Fix Task 7 — done |
| 8 | live + viewers (E/F) | ✅ wired + verified (`fix-entry-wiring` @ `023e35e`, `dc87094`): live paper loop polls cleanly; view-sim serves HTTP 200 via compose port map | Fix Task 8 — done (plan tasks task-05 added to phases 10/12) |
| 9 | probes | ✅ PASS | keep green |

### Fix round 2026-06-10 — additional bugs found while driving the fixes

- `_run_train_nn` epoch callback was 2-param; orchestrator contract is `(tf_str, epoch, metrics)` — would have raised TypeError on first epoch. Fixed with Fix 7.
- `Robot.do()` read nonexistent `live_data.data_point` (AttributeError swallowed every tick by the loop's crash guard) and never called `build_candles()` — live data would never refresh. Found by running the wired `live` service in paper mode; fixed per phase-03 task-05 contract (`dc87094`).
- Dash dashboards bound `127.0.0.1:8050` — unreachable through compose port maps. Now `0.0.0.0:$DASH_PORT` (default 8080).
- `view_online_point.py`/`view_training.py` were partially wired (module-level run with relative `shared/` state path that resolves nowhere in-container) — not pure stubs as originally reported.
- yaml↔class indicator dependency drift in 7 fields (`vol_sell_ma`, 4 classification fields, `trend_up/down`) — topological sort reads only the yaml. Synced; regression test added.
- Indicator pass runtime: ~30 min for the 2-week dataset (per-row designed algorithm, 44 fields × 6 TFs per 1-min row). Faster requires deciding whether EMA-family indicators may use full candle history instead of the designed 105-candle window — **plan-owner decision, unresolved**.
- `StrategyManager.__init__(fee, robot_actions_test)` per design decision vs `(fee)` implemented — drift flagged, unresolved.
- Paper mode: plan README's `IS_TRAIDER_TEST=1` does not exist; actual mechanism is `STOCK_TYPE=mock_binance`, now the trader.py default.

### Round 3 (2026-06-11) — gate results on real data

- Strategy factory closure unpicklable → all 4 ProcessPool simulation workers crashed, **silently absorbed into empty result dicts** by the orchestrator's crash guard. Fixed (`3a59604`); the silent-crash design itself is worth a plan review — a fully-crashed run is indistinguishable from a quiet market.
- `total_trades: 0` over the 2-week window — verified legitimate (single-worker probe, 2881 ticks, zero swallowed errors; manual `StrategyManager.check` returns NOTHING). Example strategies may need looser trigger conditions or a different window; strategy question, not integration.
- `nn-train`/`view-full` compose services point at datasets that were never grabbed (`3y_link_usdt`, `4m_link_usdt` on the long volume) — Path A for the long datasets is a prerequisite nobody ran; gates exercised against the 2-week dataset instead.
- `view_full.py` renders clean over the real 389-column frame; `view-sim` dashboard serves HTTP 200 via compose port map with absent state file.
- Frame-fragmentation perf pass (`f8a5e60`, `4926537`): wide-df build single-concat, write-back single setitem, intentional slice fragmentation silenced at the one loop that owns it. Pre-allocation tried and reverted — measured 17% slower under pandas CoW.
- Prep runtime measured: ~47 min for 2 weeks (pre-defrag code). The escalated 105-window question remains the real lever.
