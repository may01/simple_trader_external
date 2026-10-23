# Plan: cci_entry_quality — 2y / oos2m test of "CCI at the fire predicts entry success"

Spec: [`../experiment/cci_entry_quality.md`](../experiment/cci_entry_quality.md). Base branch for the script:
none needed (host numpy/pandas/talib over the frames, like `2026-10-21-trend-ma-length-2y-oos2m.py`); if anything is
written into main/, branch `cci-entry-quality` off `experimental_imp_2`. Heavy step = task 2 (1.05 M rows × 6 cells).

## Task 1 — loader + CCI columns (gate: CCI reproduction)
- Extend the tier-B loader: read the 25 `df_with_indicators.part_XX.pkl` with the column subset, concat, join
  `df_with_candle_bounds.pkl` + `_nc.pkl` on the index; oos2m from its single frame. Assert index continuity.
- Gate: recompute `5_cci_14` / `15_cci_14` on 500 random rows with `cci_lib`'s convention from the frame's own
  `{tf}_high/low/close` + `is_closed`: |diff| < 1e-6 (paper run gave 5e-11). Add `adv5`, `adv15` and the shift-1
  (closed-candle) versions.

## Task 2 — entries + per-entry record (gate: stand-in reproduction)
- Run `simulate_all` for the e25+mom gate (the live stand-in) per tf × side; per entry store ts, tf, side, entry,
  stop, dist, target, reason, pnl, R, `adv*`, MAE15/stop, MAE-pre-stop, target-before-stop, fwd15, fwd60, month.
- Gate: entry counts, net and PF per cell match the trend_ma_length run's `e25`+`mom` row (same code path) to the
  trade; write `entries_2y.parquet`, `entries_oos2m.parquet`.

## Task 3 — descriptive + nulls (gate: numbers for every validity gate)
- Bins / deciles / Spearman / AUC per cell; permutation within tf × side × month (2 000 draws); base rates; closed vs
  forming CCI; truth ladder (candle stop → stop × 2 → fwd15 / fwd60).
- Output a table per cell with n, stop rate, mean R, null 90 % band, base rate. Reject the hypothesis here if no
  cell has |Spearman| above its null band on both the strict and the forward rung.

## Task 4 — actions on 2y (gate: degeneracy + controls)
- Grid X × δ × W × CCI-tf, skip and wait; paired month-block bootstrap vs plain (24 blocks); random-skip control
  (same counts, 200 draws); wait-all control; shuffled-adv control.
- Freeze `cci_entry_quality_params.json` {X, δ, W, tf, 2y Δ, CI, n affected, control values, git sha, date}.

## Task 5 — oos2m score + interaction (gate: provenance)
- Apply the frozen params once to oos2m; report Δnet / Δstop rate / fill rate / CI. Crosscheck the params file
  against the paper-run variant names. Rerun the winner on top of stop × 2.

## Task 6 — report + register
- `results/cci_entry_quality_results.md` with every gate number; REPORT.md verdict (`success` only under the spec's
  decision rule); if alive, a candidate executor toggle spec (`CB_CCI_GATE_TF/X/MODE`).
