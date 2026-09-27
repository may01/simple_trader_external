# TF5 profit_strict NN labels — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 4 strict-only NN label heads (`ps5` × horizon {n1,n2} × side {long,short}) on the 5-minute timeframe, mirroring the existing TF15 strict targets, and materialize their label columns into the 2y train + oos2m datasets.

**Architecture:** Config-driven label pipeline. `configs/indicators_config.yaml` `labels:` block defines which `{tf}_pslong_.../{tf}_psshort_...` columns exist in `df_with_indicators.pkl`; NN spec YAMLs (`configs/nn_specs/profit_strict/*.yaml`) each read one such precomputed column by a name built from the spec. This change adds 2 config entries, 4 spec files, and a one-shot append-columns script (avoids an expensive full re-prep) to write the new columns into the existing datasets.

**Tech Stack:** Python 3, pandas, PyYAML, pytest, Docker Compose (nn-train service, CPU-only base compose).

## Global Constraints

- **Base branch:** `nn-features-profit-strict-v4` (holds the existing 12 `ps{15,60,240}` specs + config). Branch from it; do NOT branch from `experimental_imp_2` (the ps15 files to copy do not exist there).
- **Strict params (verbatim, mirror TF15):** `m=1`, `x=0.3`, `l=15`, `y=0.2`; `atr_period=14`, `ma_length=5` (defaults). Horizons `n ∈ {1,2}`.
- **Exact column names produced/consumed** (`_fmt`: `1.0`→`1`, `0.3`→`0p3`, `0.2`→`0p2`):
  - `5_pslong_n1_m1_x0p3_l15_y0p2`  ·  `5_psshort_n1_m1_x0p3_l15_y0p2`
  - `5_pslong_n2_m1_x0p3_l15_y0p2`  ·  `5_psshort_n2_m1_x0p3_l15_y0p2`
- **Spec naming:** file `ps5_n{1,2}_{long,short}.yaml`; `name: nnfo_ps5_n{1,2}_{long,short}`; target `name: ps5_n{1,2}_{long,short}`; `label_tf: 5`.
- **Strict only:** add NO `profit` (non-strict) TF5 entries.
- **This plan document lives in the external docs repo, never in the code repo.**
- Materialization runs inside the `nn-train` container (base compose, CPU — pure pandas, no GPU). Dataset selected via `NN_TRAIN_ENV`.

## Docker Entry Points

Ground-truth commands (implementation must make these work). Run from the code worktree root.

```bash
# Run the unit test suite for this change inside the container
NN_TRAIN_ENV=configs/nn_train_dataset_2y.env \
  docker compose run --rm nn-train \
  python3 -m pytest tests/unit/data_layer/test_labels_config.py \
                    tests/unit/nn/test_ps5_spec_columns.py \
                    tests/unit/data_layer/test_ps5_materialize.py -v

# Materialize the new columns into the 2y TRAIN dataset
NN_TRAIN_ENV=configs/nn_train_dataset_2y.env \
  docker compose run --rm nn-train python3 scripts/nn_ps5_materialize.py

# Materialize the new columns into the oos2m INFER dataset
NN_TRAIN_ENV=configs/oos2m_dataset.env \
  docker compose run --rm nn-train python3 scripts/nn_ps5_materialize.py
```

Verified: [ ] `docker compose run --rm nn-train python3 -c "import pandas"` succeeds

## File Structure

| Path | Responsibility | Task |
|---|---|---|
| `configs/indicators_config.yaml` | +2 `profit_strict` `tfs:[5]` entries (n1,n2) → declares the columns | 1 |
| `tests/unit/data_layer/test_labels_config.py` | assert the 2 new TF5 strict entries parse correctly | 1 |
| `configs/nn_specs/profit_strict/ps5_n{1,2}_{long,short}.yaml` | 4 new specs, each one strict TF5 head | 2 |
| `scripts/nn_pstrict_batch.py` | docstring/comment count 12→16, TF list 5/15/60/240 | 2 |
| `tests/unit/nn/test_ps5_spec_columns.py` | assert each spec resolves to its exact TF5 column | 2 |
| `scripts/nn_ps5_materialize.py` | one-shot append-columns materializer (`add_ps5_labels` + `main`) | 3 |
| `tests/unit/data_layer/test_ps5_materialize.py` | unit-test `add_ps5_labels` (columns + idempotent) | 3 |

---

### Task 1: TF5 profit_strict config entries

**Files:**
- Modify: `configs/indicators_config.yaml` (append to the `labels:` block)
- Test: `tests/unit/data_layer/test_labels_config.py`

**Interfaces:**
- Consumes: `config_loader.load_labels_config(path) -> list[LabelSpecConfig]`; `LabelSpecConfig` has fields `type, tfs, n, m, x, atr_period, ma_length, l, y`.
- Produces: two new `LabelSpecConfig(type="profit_strict", tfs=[5], n=1|2, m=1.0, x=0.3, l=15, y=0.2)` entries returned by `load_labels_config()`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/data_layer/test_labels_config.py`:

```python
def test_tf5_profit_strict_entries_present():
    specs = load_labels_config("configs/indicators_config.yaml")
    tf5_strict = [s for s in specs if s.type == "profit_strict" and s.tfs == [5]]
    assert len(tf5_strict) == 2, "expected exactly two profit_strict tfs:[5] entries (n1, n2)"
    by_n = {s.n: s for s in tf5_strict}
    assert set(by_n) == {1, 2}
    for s in tf5_strict:
        assert s.m == 1.0 and s.x == 0.3 and s.l == 15 and s.y == 0.2

def test_no_nonstrict_profit_tf5():
    specs = load_labels_config("configs/indicators_config.yaml")
    assert not [s for s in specs if s.type == "profit" and s.tfs == [5]], \
        "strict only — no non-strict profit tf5 entries"
```

(Confirm `load_labels_config` is imported at the top of the file; add the import if missing.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/data_layer/test_labels_config.py::test_tf5_profit_strict_entries_present -v`
Expected: FAIL — `assert 0 == 2`.

- [ ] **Step 3: Add the config entries**

Append to the `labels:` block in `configs/indicators_config.yaml` (place after the TF15 strict entries; strict only — no `profit` entries):

```yaml
  - type: profit_strict
    tfs: [5]
    n: 1
    m: 1
    x: 0.3
    l: 15
    y: 0.2

  - type: profit_strict
    tfs: [5]
    n: 2
    m: 1
    x: 0.3
    l: 15
    y: 0.2
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/unit/data_layer/test_labels_config.py -v`
Expected: PASS (both new tests + existing).

- [ ] **Step 5: Commit**

```bash
git add configs/indicators_config.yaml tests/unit/data_layer/test_labels_config.py
git commit -m "feat: declare TF5 profit_strict label entries (n1,n2)"
```

---

### Task 2: Four ps5 spec YAMLs + batch-driver count

**Files:**
- Create: `configs/nn_specs/profit_strict/ps5_n1_long.yaml`, `ps5_n1_short.yaml`, `ps5_n2_long.yaml`, `ps5_n2_short.yaml`
- Modify: `scripts/nn_pstrict_batch.py` (docstring/comments only)
- Test: `tests/unit/nn/test_ps5_spec_columns.py`

**Interfaces:**
- Consumes: `nn.nn_model_spec.NNModelSpec.from_yaml(path) -> NNModelSpec` (`.targets: list[TargetSpec]`; `TargetSpec` has `label_tf, label_m, label_x, label_l, label_y, strict, side, horizons`); `nn.nn_dataset._profit_long_col(target, horizon) -> str` and `_profit_short_col(target, horizon) -> str`.
- Produces: 4 spec files that resolve to the 4 exact column names in Global Constraints. `nn_pstrict_batch.py` auto-globs them (16 specs total).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/nn/test_ps5_spec_columns.py`:

```python
import pytest
from nn.nn_model_spec import NNModelSpec
from nn.nn_dataset import _profit_long_col, _profit_short_col

SPEC_DIR = "configs/nn_specs/profit_strict"

CASES = [
    ("ps5_n1_long",  "long",  1, "5_pslong_n1_m1_x0p3_l15_y0p2"),
    ("ps5_n1_short", "short", 1, "5_psshort_n1_m1_x0p3_l15_y0p2"),
    ("ps5_n2_long",  "long",  2, "5_pslong_n2_m1_x0p3_l15_y0p2"),
    ("ps5_n2_short", "short", 2, "5_psshort_n2_m1_x0p3_l15_y0p2"),
]

@pytest.mark.parametrize("stem,side,horizon,column", CASES)
def test_ps5_spec_resolves_to_tf5_column(stem, side, horizon, column):
    spec = NNModelSpec.from_yaml(f"{SPEC_DIR}/{stem}.yaml")
    assert spec.name == f"nnfo_{stem}"
    tgt = spec.targets[0]
    assert tgt.strict is True
    assert tgt.label_tf == 5
    assert tgt.side == side
    assert tgt.horizons[0] == horizon
    resolver = _profit_long_col if side == "long" else _profit_short_col
    assert resolver(tgt, horizon) == column
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/nn/test_ps5_spec_columns.py -v`
Expected: FAIL — `from_yaml` cannot open `ps5_n1_long.yaml` (file missing).

- [ ] **Step 3: Create the 4 spec files**

For each new file, copy the matching TF15 file and change exactly three things. Example — `configs/nn_specs/profit_strict/ps5_n1_long.yaml` is `ps15_n1_long.yaml` with:
- line 1: `name: nnfo_ps5_n1_long`
- target `name: ps5_n1_long`
- `label_tf: 5`

The full target block for `ps5_n1_long.yaml` must read:

```yaml
targets:
- name: ps5_n1_long
  kind: label
  side: long
  horizons:
  - 1
  label_tf: 5
  label_m: 1.0
  label_x: 0.3
  strict: true
  label_l: 15
  label_y: 0.2
```

Repeat for the other three, copying from the correspondingly-named `ps15_*` source so `side`/`horizons` are already correct:
- `ps5_n1_short.yaml` ← `ps15_n1_short.yaml`: `name: nnfo_ps5_n1_short`, target `name: ps5_n1_short`, `label_tf: 5` (side `short`, horizon `1`).
- `ps5_n2_long.yaml` ← `ps15_n2_long.yaml`: `name: nnfo_ps5_n2_long`, target `name: ps5_n2_long`, `label_tf: 5` (side `long`, horizon `2`).
- `ps5_n2_short.yaml` ← `ps15_n2_short.yaml`: `name: nnfo_ps5_n2_short`, target `name: ps5_n2_short`, `label_tf: 5` (side `short`, horizon `2`).

Everything else in each file (`grouping`, `timeframes`, `indicators`, `layers`, `history_points`, optimizer/training block) stays identical to its TF15 source.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/nn/test_ps5_spec_columns.py -v`
Expected: PASS (4 parametrized cases).

- [ ] **Step 5: Update the batch-driver docstring/comments**

In `scripts/nn_pstrict_batch.py`, update the module docstring and inline comments so counts/TFs are accurate (glob logic is unchanged):
- `"Batch driver for the 12 profit_strict nn-features-only models."` → `16`
- `"side long/short x TF 15/60/240 x horizon n1/n2"` → `"side long/short x TF 5/15/60/240 x horizon n1/n2"`
- Comments referencing `12-head` / `the 12 heads` / `canonical 12` → `16`

Verify no functional line changed:

Run: `git diff -U0 scripts/nn_pstrict_batch.py`
Expected: only docstring/comment lines in the diff.

- [ ] **Step 6: Commit**

```bash
git add configs/nn_specs/profit_strict/ps5_n1_long.yaml \
        configs/nn_specs/profit_strict/ps5_n1_short.yaml \
        configs/nn_specs/profit_strict/ps5_n2_long.yaml \
        configs/nn_specs/profit_strict/ps5_n2_short.yaml \
        scripts/nn_pstrict_batch.py \
        tests/unit/nn/test_ps5_spec_columns.py
git commit -m "feat: add 4 TF5 profit_strict NN specs (ps5 n1/n2 long/short)"
```

---

### Task 3: Append-columns materializer script

**Files:**
- Create: `scripts/nn_ps5_materialize.py`
- Test: `tests/unit/data_layer/test_ps5_materialize.py`

**Interfaces:**
- Consumes: `indicators.labels.add_profit_strict_labels(wide_df, tf, n, m, x, l, y, atr_period=14, ma_length=5) -> None` (appends `{tf}_pslong_...`/`{tf}_psshort_...` columns in place); `helpers.wide_df_path() -> str` (returns `{dataset_folder()}df_with_indicators.pkl`, env-selected).
- Produces: `add_ps5_labels(wide_df: pd.DataFrame) -> list[str]` — appends the 4 TF5 strict columns in place, idempotent (skips columns already present), returns the list of column names now guaranteed present. `main()` — loads `wide_df_path()`, calls `add_ps5_labels`, writes the pickle back only if columns were added.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/data_layer/test_ps5_materialize.py`. Build a small synthetic wide df with the TF5 OHLC columns the label math needs, then assert the 4 columns appear and re-running is a no-op:

```python
import numpy as np
import pandas as pd
from scripts.nn_ps5_materialize import add_ps5_labels

EXPECTED = [
    "5_pslong_n1_m1_x0p3_l15_y0p2", "5_psshort_n1_m1_x0p3_l15_y0p2",
    "5_pslong_n2_m1_x0p3_l15_y0p2", "5_psshort_n2_m1_x0p3_l15_y0p2",
]

def _synthetic_wide(rows=400):
    # add_profit_strict_labels reads {tf}_high/{tf}_low/{tf}_close for tf=5.
    idx = pd.date_range("2024-01-01", periods=rows, freq="1min")
    close = pd.Series(100 + np.cumsum(np.random.default_rng(0).normal(0, 0.1, rows)), index=idx)
    df = pd.DataFrame(index=idx)
    df["5_close"] = close
    df["5_high"] = close + 0.5
    df["5_low"] = close - 0.5
    return df

def test_add_ps5_labels_adds_four_columns():
    df = _synthetic_wide()
    added = add_ps5_labels(df)
    assert set(EXPECTED).issubset(df.columns)
    assert set(added) == set(EXPECTED)

def test_add_ps5_labels_idempotent():
    df = _synthetic_wide()
    add_ps5_labels(df)
    cols_before = list(df.columns)
    add_ps5_labels(df)  # second call must not duplicate or error
    assert list(df.columns) == cols_before
```

> Note for implementer: confirm the exact OHLC column names `add_profit_strict_labels` reads for a TF (inspect `indicators/labels.py::_entry_state` / `profit_strict_long`) and build the synthetic frame to match. If the real names differ from `5_high/5_low/5_close`, fix the fixture — the production column names in `EXPECTED` are fixed by Global Constraints and must not change.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/data_layer/test_ps5_materialize.py -v`
Expected: FAIL — `ModuleNotFoundError: scripts.nn_ps5_materialize`.

- [ ] **Step 3: Write the materializer**

Create `scripts/nn_ps5_materialize.py`. Core function calls `add_profit_strict_labels` for n=1 and n=2 (params from Global Constraints), guarded for idempotency; `main()` loads/saves via `wide_df_path()`:

```python
#!/usr/bin/env python3
"""One-shot: append the 4 TF5 profit_strict label columns to df_with_indicators.pkl.

Avoids a full data re-prep. Run once per dataset via NN_TRAIN_ENV:

    NN_TRAIN_ENV=configs/nn_train_dataset_2y.env docker compose run --rm nn-train \
        python3 scripts/nn_ps5_materialize.py
    NN_TRAIN_ENV=configs/oos2m_dataset.env      docker compose run --rm nn-train \
        python3 scripts/nn_ps5_materialize.py
"""
import pandas as pd

from helpers import wide_df_path
from indicators.labels import add_profit_strict_labels

_PARAMS = dict(m=1, x=0.3, l=15, y=0.2)  # mirror TF15; atr_period/ma_length defaults
_EXPECTED = [
    "5_pslong_n1_m1_x0p3_l15_y0p2", "5_psshort_n1_m1_x0p3_l15_y0p2",
    "5_pslong_n2_m1_x0p3_l15_y0p2", "5_psshort_n2_m1_x0p3_l15_y0p2",
]


def add_ps5_labels(wide_df: pd.DataFrame) -> list[str]:
    """Append the 4 TF5 strict columns in place; idempotent. Returns their names."""
    if not set(_EXPECTED).issubset(wide_df.columns):
        for n in (1, 2):
            add_profit_strict_labels(wide_df, 5, n=n, **_PARAMS)
    return list(_EXPECTED)


def main() -> None:
    path = wide_df_path()
    df = pd.read_pickle(path)
    before = set(df.columns)
    add_ps5_labels(df)
    if set(df.columns) != before:
        df.to_pickle(path)
        print(f"[ps5] wrote {len(set(df.columns) - before)} columns -> {path}", flush=True)
    else:
        print(f"[ps5] columns already present -> {path} (no-op)", flush=True)


if __name__ == "__main__":
    main()
```

> Implementer: verify `add_profit_strict_labels`'s call signature order matches (`wide_df, tf, n, m, x, l, y, atr_period=14, ma_length=5`). Ensure `scripts/` is importable as a package in the test env (it already hosts `scripts/nn_pstrict_batch.py`); if `tests` cannot import `scripts.*`, add an empty `scripts/__init__.py` or use the same import path the existing script tests use.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/unit/data_layer/test_ps5_materialize.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/nn_ps5_materialize.py tests/unit/data_layer/test_ps5_materialize.py
git commit -m "feat: add one-shot TF5 profit_strict column materializer"
```

---

### Task 4: Materialize columns into the real 2y + oos2m datasets (Docker)

**Files:** none created — this is the in-container integration run that satisfies the DoD ("columns present in 2y + oos2m").

**Interfaces:**
- Consumes: `scripts/nn_ps5_materialize.py::main` (Task 3); the `nn-train` compose service; datasets on the shared volume selected by `configs/nn_train_dataset_2y.env` and `configs/oos2m_dataset.env`.
- Produces: the 4 TF5 strict columns present in each dataset's `df_with_indicators.pkl`.

- [ ] **Step 1: Run the unit suite in the container (integration gate, GREEN)**

Run:
```bash
NN_TRAIN_ENV=configs/nn_train_dataset_2y.env docker compose run --rm nn-train \
  python3 -m pytest tests/unit/data_layer/test_labels_config.py \
                    tests/unit/nn/test_ps5_spec_columns.py \
                    tests/unit/data_layer/test_ps5_materialize.py -v
```
Expected: all PASS in-container (proves the code runs against the container's pandas/torch image, not just the host).

- [ ] **Step 2: Materialize into the 2y TRAIN dataset**

Run:
```bash
NN_TRAIN_ENV=configs/nn_train_dataset_2y.env docker compose run --rm nn-train \
  python3 scripts/nn_ps5_materialize.py
```
Expected: `[ps5] wrote 4 columns -> .../train/2y_link_usdt/df_with_indicators.pkl`.

- [ ] **Step 3: Verify the columns landed and are non-degenerate (2y)**

Run:
```bash
NN_TRAIN_ENV=configs/nn_train_dataset_2y.env docker compose run --rm nn-train python3 -c "
import pandas as pd
from helpers import wide_df_path
df = pd.read_pickle(wide_df_path())
cols = ['5_pslong_n1_m1_x0p3_l15_y0p2','5_psshort_n1_m1_x0p3_l15_y0p2','5_pslong_n2_m1_x0p3_l15_y0p2','5_psshort_n2_m1_x0p3_l15_y0p2']
assert all(c in df.columns for c in cols), [c for c in cols if c not in df.columns]
for c in cols:
    s = df[c].dropna()
    print(c, 'nonnull=', len(s), 'positives=', int((s==1).sum()))
    assert len(s) > 0 and 0 < (s==1).sum() < len(s), c
print('2y OK')
"
```
Expected: prints per-column counts, ends `2y OK`. (Guards against all-NaN or single-class collapse.)

- [ ] **Step 4: Materialize + verify the oos2m INFER dataset**

Run:
```bash
NN_TRAIN_ENV=configs/oos2m_dataset.env docker compose run --rm nn-train \
  python3 scripts/nn_ps5_materialize.py
NN_TRAIN_ENV=configs/oos2m_dataset.env docker compose run --rm nn-train python3 -c "
import pandas as pd
from helpers import wide_df_path
df = pd.read_pickle(wide_df_path())
cols = ['5_pslong_n1_m1_x0p3_l15_y0p2','5_psshort_n1_m1_x0p3_l15_y0p2','5_pslong_n2_m1_x0p3_l15_y0p2','5_psshort_n2_m1_x0p3_l15_y0p2']
assert all(c in df.columns for c in cols), [c for c in cols if c not in df.columns]
print('oos2m OK')
"
```
Expected: materialize prints `wrote 4 columns` (or `no-op` if re-run), verify ends `oos2m OK`.

- [ ] **Step 5: Record completion**

No commit (data artifacts live on the shared volume, not in git). Note in the progress ledger that both datasets were materialized, with the printed nonnull/positive counts from Step 3.

> **Root-owned-files caution (memory):** container writes into a mounted worktree can land root-owned and block later merges. After the container runs, check `git status` in the worktree for stray root-owned files and for an accidentally-modified `df_with_indicators.pkl` tracked in git (it should be volume-only, not committed). Clean up before finishing the branch.

---

## Self-Review

**Spec coverage:** spec §Changes 1 (specs) → Task 2; §2 (config) → Task 1; §3 (materializer) → Task 3; §4 (batch docstring) → Task 2 Step 5; §Tests (spec→column, materializer, idempotent) → Tasks 2 & 3; DoD "columns in 2y+oos2m" → Task 4. All covered.

**Placeholder scan:** none — every step has concrete content/commands. The two `> Implementer:` notes are verification instructions, not deferred work.

**Type consistency:** `add_ps5_labels`, `add_profit_strict_labels`, `_profit_long_col`/`_profit_short_col`, `wide_df_path`, `load_labels_config`, `NNModelSpec.from_yaml` used with consistent signatures across tasks. The 4 column strings are identical everywhere (Global Constraints, tests, materializer, verification).
