# task-05 — ranking tables + written report → approval gate

**Files:**
- Create: `experiments/rsi_params_selection/report.py`
- Test: `tests/unit/experiments/test_rps_report.py`
- Output (not committed): `external/docs/superpowers/experiment/results/rsi_parameters_selection_results.md`

**Interfaces:**
- Consumes: the task-04 JSON (`cells` list + `meta`).
- Produces: `report.render(result: dict) -> str` — markdown with the mechanical tables; the written analysis (spec §7) is authored by the executor on top of those tables, inside the same md file.

Ranking rule (mechanical part): rank cells per label kind by **oos MI averaged over
the kind's 4 label columns** (n1/n2 × long/short), tie-break by train MI. Flip
summary: per 7-class cell count `sign_flip == True` over pairs × sides (max 8).

- [ ] **Step 1: write failing test**

`tests/unit/experiments/test_rps_report.py`:

```python
import numpy as np
import pandas as pd

from experiments.rsi_params_selection import config
from experiments.rsi_params_selection.report import kind_mi, render
from experiments.rsi_params_selection.run_experiment import run_grid


def _result():
    rng = np.random.default_rng(7)

    def frame(n):
        d = {f"diff{w}": rng.normal(0, 1, n) for w in config.WINDOWS}
        for kind in ("plain", "strict"):
            for hn in (1, 2):
                d[f"{kind}_n{hn}_long"] = (rng.random(n) < 0.3).astype(float)
                d[f"{kind}_n{hn}_short"] = (rng.random(n) < 0.3).astype(float)
        return pd.DataFrame(d)

    train = {tf: frame(4000) for tf in config.TFS}
    oos = {tf: frame(700) for tf in config.TFS}
    return run_grid(train, oos)


def test_kind_mi_averages_four_columns():
    res = _result()
    cell = res["cells"][0]
    got = kind_mi(cell, "strict", "oos")
    cols = [f"strict_n{n}_{s}" for n in (1, 2) for s in ("long", "short")]
    want = sum(cell["oos"]["labels"][c]["mi"] for c in cols) / 4
    assert got == want


def test_render_contains_required_sections():
    md = render(_result())
    for heading in ("## Ranking — strict", "## Ranking — non-strict",
                    "## 5 vs 7 classes", "## Technique comparison",
                    "## Flip test (7-class)", "## Row counts & drops"):
        assert heading in md, heading
    assert "| window | tf | technique |" in md
```

- [ ] **Step 2: run test, verify fail**

Run: `python3 -m pytest tests/unit/experiments/test_rps_report.py -q`
Expected: FAIL — `ImportError: report`

- [ ] **Step 3: implement**

`experiments/rsi_params_selection/report.py`:

```python
"""Mechanical md tables from the results JSON. Written analysis goes on top."""
from . import config

KINDS = ("strict", "plain")


def kind_mi(cell: dict, kind: str, split: str) -> float:
    cols = [f"{kind}_n{n}_{s}" for n in (1, 2) for s in ("long", "short")]
    return sum(cell[split]["labels"][c]["mi"] for c in cols) / len(cols)


def _rank_table(cells, kind: str, top: int = 15) -> str:
    rows = sorted(cells, key=lambda c: (-kind_mi(c, kind, "oos"),
                                        -kind_mi(c, kind, "train")))
    lines = ["| window | tf | technique | classes | oos MI | train MI | mono ρ (oos) |",
             "|---|---|---|---|---|---|---|"]
    for c in rows[:top]:
        rho = c["oos"]["pairs"][f"{kind}_n1"]["monotonicity_rho"]
        lines.append(
            f"| {c['window']} | {c['tf']} | {c['technique']} | {c['n_classes']} "
            f"| {kind_mi(c, kind, 'oos'):.5f} | {kind_mi(c, kind, 'train'):.5f} "
            f"| {rho:.2f} |")
    return "\n".join(lines)


def _class_count_table(cells, kind: str) -> str:
    lines = ["| classes | mean oos MI | best cell |", "|---|---|---|"]
    for nc in config.CLASS_COUNTS:
        sub = [c for c in cells if c["n_classes"] == nc]
        mean = sum(kind_mi(c, kind, "oos") for c in sub) / len(sub)
        best = max(sub, key=lambda c: kind_mi(c, kind, "oos"))
        lines.append(f"| {nc} | {mean:.5f} | ma{best['window']} tf{best['tf']} "
                     f"{best['technique']} ({kind_mi(best, kind, 'oos'):.5f}) |")
    return "\n".join(lines)


def _technique_table(cells, kind: str) -> str:
    lines = ["| technique | mean oos MI | mean train MI |", "|---|---|---|"]
    for t in config.TECHNIQUES:
        sub = [c for c in cells if c["technique"] == t]
        lines.append(f"| {t} | "
                     f"{sum(kind_mi(c, kind, 'oos') for c in sub) / len(sub):.5f} | "
                     f"{sum(kind_mi(c, kind, 'train') for c in sub) / len(sub):.5f} |")
    return "\n".join(lines)


def _flip_table(cells) -> str:
    lines = ["| window | tf | technique | kind | split | flips (of 8) | extra pop − / + |",
             "|---|---|---|---|---|---|---|"]
    for c in cells:
        if c["n_classes"] != 7:
            continue
        for split in ("train", "oos"):
            pop = c[split]["population"]
            for kind in KINDS:
                flips = 0
                for n in (1, 2):
                    fl = c[split]["pairs"][f"{kind}_n{n}"]["flip"]
                    for side in ("neg", "pos"):
                        flips += bool(fl[side]["sign_flip"])
                lines.append(
                    f"| {c['window']} | {c['tf']} | {c['technique']} | {kind} "
                    f"| {split} | {flips} | {pop['-3']} / {pop['3']} |")
    return "\n".join(lines)


def _counts(meta: dict) -> str:
    lines = ["| split | tf | closed rows | NaN diffs (8/12/24) |", "|---|---|---|---|"]
    for split in ("train", "oos"):
        for tf, n in meta["row_counts"][split].items():
            d = meta["dropped_nan_feature"][split][tf]
            lines.append(f"| {split} | {tf} | {n} | {d['8']}/{d['12']}/{d['24']} |")
    return "\n".join(lines)


def render(result: dict) -> str:
    cells = result["cells"]
    parts = ["# RSI Parameters Selection — Results",
             "",
             f"Source: `rsi_parameters_selection_results.json` "
             f"({result['meta'].get('parts_used', '?')} parts).",
             "", "## Ranking — strict", "", _rank_table(cells, "strict"),
             "", "## Ranking — non-strict", "", _rank_table(cells, "plain"),
             "", "## 5 vs 7 classes", "",
             "strict:", _class_count_table(cells, "strict"), "",
             "non-strict:", _class_count_table(cells, "plain"),
             "", "## Technique comparison", "",
             "strict:", _technique_table(cells, "strict"), "",
             "non-strict:", _technique_table(cells, "plain"),
             "", "## Flip test (7-class)", "", _flip_table(cells),
             "", "## Row counts & drops", "", _counts(result["meta"]), ""]
    return "\n".join(parts)


if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else (
        "external/docs/superpowers/experiment/results/"
        "rsi_parameters_selection_results.json")
    md = render(json.load(open(path)))
    out = path.replace(".json", ".md")
    with open(out, "w") as fh:
        fh.write(md)
    print(f"wrote {out}")
```

- [ ] **Step 4: run tests, verify pass**

Run: `python3 -m pytest tests/unit/experiments/ -q`
Expected: all green.

- [ ] **Step 5: generate tables from the full-run JSON**

Run: `python3 -m experiments.rsi_params_selection.report`

- [ ] **Step 6: write the analysis (spec §7) into the md, above the tables**

Executor authors these sections at the top of `rsi_parameters_selection_results.md`, each backed by numbers from the tables (quote oos values, flag TF240 7-class tail thinness ~50–100 train rows / far fewer oos):

1. **Best ma window — strict labels** and **— non-strict labels** (may differ).
2. **5 vs 7 classes** — did the extra split add oos MI or only train MI (overfit tell)? Is the 7-class flip pattern present (strong keeps dominance, extra shrinks/flips)?
3. **Technique** — quantile vs sym0 vs zscore on oos MI + monotonicity + population sanity.
4. **Per-measurement commentary** — one short paragraph per TF: which cells look real (train AND oos agree) vs noise.
5. **Overall recommendation** — single (window, technique, classes) pick + runner-up, with the caveats.
6. Note which side dominated where (inversion check vs 2026-07-22 gate finding).

- [ ] **Step 7: approval gate**

Present report to user. **Nothing gets committed** — code, JSON, md — until the user approves the report and explicitly confirms commits (project rule). After approval: user decides what to commit (harness + report) and whether to update external specs/tasks per the tasks-as-plan-files convention.
