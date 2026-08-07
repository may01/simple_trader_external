# RSI Parameters Selection Experiment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `../../specs/2026-08-06-rsi-parameters-selection-design.md`
**Goal:** Measure which RSI ma window (8/12/24), classification technique (quantile/sym0/zscore) and class count (5/7) best separates profit labels by `rsi_maN_diff` class, on 2y (fit+score) and oos2m (score only).

**Architecture:** standalone host-side analysis package `experiments/rsi_params_selection/` inside a new worktree — reads volume pickles directly, computes 2y labels per part in memory, fits cuts on pooled 2y closed rows, scores both datasets, dumps JSON + md report to external docs. No production code touched, no Docker, nothing written into the volume.

**Tech stack:** python3 (host), pandas + numpy only (no scipy/sklearn — MI/η²/Spearman implemented inline), pytest for unit tests, repo modules `config_loader.load_labels_config` + `indicators.labels.add_profit_labels/add_profit_strict_labels`.

## Global constraints (from spec — every task inherits these)

- Feature: `{tf}_rsi_ma{W}_diff` only, W ∈ {8,12,24}; `_slope` out of scope.
- Same-TF grid: TF ∈ {15, 60, 240}; labels strict + non-strict, n ∈ {1,2}, long + short.
- 5-class cuts: quantile p[10,30,70,90]; sym0 0±{0.3,1.0}·std; zscore mean±{0.5,1.0}·std.
- 7-class cuts: quantile p[2,10,30,70,90,98]; sym0 0±{0.3,1.0,2.0}·std; zscore mean±{0.5,1.0,2.0}·std.
- Cuts fit on 2y closed rows ONLY; applied unchanged to oos2m (no OOS refit).
- Row basis: `{tf}_is_closed == True` rows; NaN feature/label rows dropped and counted.
- Data: 2y parts `df_with_indicators.part_{00..24}.pkl` (labels computed per part by the harness); oos2m `df_with_indicators.pkl` (labels already baked).
- **NO git commits in any task** — project rule: user confirms every commit; results stay uncommitted until report approved. Each task ends by reporting what changed, not by committing.
- Direction-agnostic flip test: which side is "continuation" is measured output (prior gate showed inversion: strong-up → short edge).

## Setup (before task-01)

```bash
cd /home/om/projects/simple_trader/main
git worktree add ../worktrees/rsi-params-selection -b rsi-params-selection experimental_imp_2
cd ../worktrees/rsi-params-selection
python3 -c "import pandas, numpy, pytest; print('env ok')"
ls /media/om/Alexandria/simple_trader/simple_trader_vol_long/train/2y_link_usdt/df_with_indicators.part_00.pkl
```
All commands in tasks run from the worktree root.

## Tasks

| task | deliverable | boundary |
|------|-------------|----------|
| task-01 | `config.py` + `data_loading.py` | closed-row per-TF frames with diffs + labels, from both datasets |
| task-02 | `classify.py` | fit_cuts / apply_cuts, all 3 techniques × {5,7} |
| task-03 | `metrics.py` | populations, rates+lift, separation+monotonicity, flip test, MI, η² |
| task-04 | `run_experiment.py` + JSON results | smoke run (2 parts) then full 2y+oos run |
| task-05 | `report.py` + results md | ranking tables + written analysis → user approval gate |

Rule: task N+1 does not start until task N's tests are green.

## Verification

- `python3 -m pytest tests/unit/experiments/ -q` green after each task.
- task-04 smoke: JSON has 54 cells × (train+oos) blocks, populations sum to row counts, no empty middle class.
- task-05: report answers every spec §7 question (best W strict/non-strict, 5 vs 7, technique, overall).
