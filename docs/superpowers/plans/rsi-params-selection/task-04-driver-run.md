# task-04 — driver: fit on 2y, score 2y + oos, dump JSON

**Files:**
- Create: `experiments/rsi_params_selection/run_experiment.py`
- Test: `tests/unit/experiments/test_rps_driver.py`
- Output (not committed): `external/docs/superpowers/experiment/results/rsi_parameters_selection_results.json`

**Interfaces:**
- Consumes: `data_loading.load_2y/load_oos`, `classify.fit_cuts/apply_cuts`, `metrics.evaluate`, `config.*`.
- Produces:
  - `run_experiment.run_grid(train: dict[int, pd.DataFrame], oos: dict[int, pd.DataFrame]) -> dict` — pure, testable on synthetic frames.
  - CLI: `python3 -m experiments.rsi_params_selection.run_experiment [--limit N] [--out PATH]`.
  - JSON layout consumed by task-05:

```python
{
  "meta": {
    "spec": "2026-08-06-rsi-parameters-selection-design.md",
    "parts_used": int, "row_counts": {"train": {"15": int, ...}, "oos": {...}},
    "dropped_nan_feature": {"train": {"15": {"8": int, "12": int, "24": int}}, "oos": {...}},
  },
  "cells": [
    {"window": 8, "tf": 15, "technique": "sym0", "n_classes": 5,
     "cuts": [float, ...],
     "train": {<metrics.evaluate dict>},
     "oos":   {<metrics.evaluate dict>}},
    ...  # 3 windows x 3 tfs x 3 techniques x 2 class counts = 54 cells
  ],
}
```

- [ ] **Step 1: write failing test**

`tests/unit/experiments/test_rps_driver.py`:

```python
import numpy as np
import pandas as pd

from experiments.rsi_params_selection import config
from experiments.rsi_params_selection.run_experiment import run_grid


def _fake_tf_frame(n=6000, seed=0):
    rng = np.random.default_rng(seed)
    data = {f"diff{w}": rng.normal(0, 1, n) for w in config.WINDOWS}
    for kind in ("plain", "strict"):
        for hn in (1, 2):
            data[f"{kind}_n{hn}_long"] = (rng.random(n) < 0.3).astype(float)
            data[f"{kind}_n{hn}_short"] = (rng.random(n) < 0.3).astype(float)
    return pd.DataFrame(data)


def test_run_grid_full_cell_coverage_and_oos_uses_train_cuts():
    train = {tf: _fake_tf_frame(seed=tf) for tf in config.TFS}
    oos = {tf: _fake_tf_frame(n=800, seed=tf + 100) for tf in config.TFS}
    res = run_grid(train, oos)
    assert len(res["cells"]) == 54
    keys = {(c["window"], c["tf"], c["technique"], c["n_classes"])
            for c in res["cells"]}
    assert len(keys) == 54
    for c in res["cells"]:
        assert len(c["cuts"]) == c["n_classes"] - 1
        assert sum(c["train"]["population"].values()) == c["train"]["n_rows"]
        assert sum(c["oos"]["population"].values()) == c["oos"]["n_rows"]
    # oos scored with train cuts: same cell, same cuts list is the contract
    cell = res["cells"][0]
    assert cell["train"]["n_rows"] == 6000 and cell["oos"]["n_rows"] == 800


def test_run_grid_counts_nan_feature_drops():
    train = {tf: _fake_tf_frame(seed=tf) for tf in config.TFS}
    train[15].loc[train[15].index[:100], "diff8"] = np.nan
    oos = {tf: _fake_tf_frame(n=800, seed=tf + 100) for tf in config.TFS}
    res = run_grid(train, oos)
    assert res["meta"]["dropped_nan_feature"]["train"]["15"]["8"] == 100
    cell = next(c for c in res["cells"]
                if c["tf"] == 15 and c["window"] == 8)
    assert cell["train"]["n_rows"] == 5900
```

- [ ] **Step 2: run test, verify fail**

Run: `python3 -m pytest tests/unit/experiments/test_rps_driver.py -q`
Expected: FAIL — `ImportError: run_experiment`

- [ ] **Step 3: implement**

`experiments/rsi_params_selection/run_experiment.py`:

```python
"""Driver: fit cuts on 2y closed rows, score 2y + oos2m, dump one JSON.

Usage (from worktree root, host python):
    python3 -m experiments.rsi_params_selection.run_experiment --limit 2   # smoke
    python3 -m experiments.rsi_params_selection.run_experiment             # full
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

from . import config
from .classify import apply_cuts, fit_cuts
from .data_loading import load_2y, load_oos
from .metrics import evaluate

DEFAULT_OUT = os.path.join(
    "external", "docs", "superpowers", "experiment", "results",
    "rsi_parameters_selection_results.json")

LABEL_KEYS = [f"{kind}_n{n}_{side}" for kind, n in config.LABEL_PAIRS
              for side in ("long", "short")]


def _score(frame: pd.DataFrame, window: int, cuts) -> dict:
    """Drop NaN-feature rows, classify, evaluate against the 8 label columns."""
    x = frame[f"diff{window}"].to_numpy(dtype=float)
    ok = ~np.isnan(x)
    classes = apply_cuts(x[ok], cuts)
    return evaluate(classes, frame.loc[ok, LABEL_KEYS], len(cuts) + 1)


def run_grid(train: dict[int, pd.DataFrame], oos: dict[int, pd.DataFrame]) -> dict:
    dropped = {"train": {}, "oos": {}}
    for name, dsets in (("train", train), ("oos", oos)):
        for tf, frame in dsets.items():
            dropped[name][str(tf)] = {
                str(w): int(frame[f"diff{w}"].isna().sum())
                for w in config.WINDOWS}

    cells = []
    for tf in config.TFS:
        for window in config.WINDOWS:
            fit_x = train[tf][f"diff{window}"].dropna().to_numpy(dtype=float)
            for technique in config.TECHNIQUES:
                for n_classes in config.CLASS_COUNTS:
                    cuts = fit_cuts(fit_x, technique, n_classes)
                    cells.append({
                        "window": window, "tf": tf,
                        "technique": technique, "n_classes": n_classes,
                        "cuts": [float(c) for c in cuts],
                        "train": _score(train[tf], window, cuts),
                        "oos": _score(oos[tf], window, cuts),
                    })
    return {
        "meta": {
            "spec": "2026-08-06-rsi-parameters-selection-design.md",
            "row_counts": {
                name: {str(tf): int(len(f)) for tf, f in dsets.items()}
                for name, dsets in (("train", train), ("oos", oos))},
            "dropped_nan_feature": dropped,
        },
        "cells": cells,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="use only the first N 2y parts (smoke run)")
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    print("loading 2y parts…", flush=True)
    train = load_2y(limit=args.limit)
    print("loading oos2m…", flush=True)
    oos = load_oos()
    for tf in config.TFS:
        print(f"  tf {tf}: train {len(train[tf])} rows, oos {len(oos[tf])} rows")

    result = run_grid(train, oos)
    result["meta"]["parts_used"] = args.limit or 25

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(result, fh, indent=1)
    print(f"wrote {args.out} ({len(result['cells'])} cells)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: run test, verify pass**

Run: `python3 -m pytest tests/unit/experiments/test_rps_driver.py -q`
Expected: 2 passed. Then whole suite: `python3 -m pytest tests/unit/experiments/ -q` — all green.

- [ ] **Step 5: smoke run (2 parts)**

Run: `python3 -m experiments.rsi_params_selection.run_experiment --limit 2 --out /tmp/claude-1000/-home-om-projects-simple-trader/1deed332-6bb3-465d-8555-6e55901eed89/scratchpad/rps_smoke.json`

Check: 54 cells; per cell `train.n_rows` ≈ TF15 5760 / TF60 1440 / TF240 360 minus NaN drops; oos rows ≈ 5664/1416/354; quantile 5-class populations ≈ 10/20/40/20/10%.

- [ ] **Step 6: full run**

Run: `python3 -m experiments.rsi_params_selection.run_experiment`
Expected: ~25 parts × (read 300MB pickle + 12 label columns) — minutes-scale, watch memory stays bounded (one part in RAM at a time). Output JSON lands in `external/docs/superpowers/experiment/results/` (NOT committed).

- [ ] **Step 7: sanity checks on full JSON**

```bash
python3 - <<'EOF'
import json
r = json.load(open("external/docs/superpowers/experiment/results/rsi_parameters_selection_results.json"))
assert len(r["cells"]) == 54
tf15 = r["meta"]["row_counts"]["train"]["15"]
assert 65_000 < tf15 < 72_000, tf15   # ~2y of TF15 closed rows
for c in r["cells"]:
    pop = c["train"]["population"]
    assert all(v > 0 for k, v in pop.items() if k == "0"), (c["window"], c["tf"])
print("ok", tf15)
EOF
```

- [ ] **Step 8: checkpoint — report row counts + drop accounting (NO commit)**
