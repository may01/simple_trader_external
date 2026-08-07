# RSI Parameters Selection — MA-Window / Slope-Class Separation Experiment — Design

**Date:** 2026-08-06
**Status:** approved design, ready for implementation plan.
**Source spec:** `../experiment/rsi_parameters_selection.md`
**Scope:** measurement-only experiment — no production indicator/classification code changes.
**Branch:** new worktree `rsi-params-selection` off `experimental_imp_2`.

---

## 1. Goal

Select the RSI ma window (8 / 12 / 24) and slope-classification scheme that best
separates profit labels by class. A class scheme is good when:

- stronger (non-neutral) classes show a growing gap between long-label and
  short-label probability (directional separation), and
- in the 7-class variant, the outermost ("extra") class flips: probability of the
  reverse-side label exceeds continuation-side probability, while the "strong"
  class below it still favors continuation. This captures the pre-reversal
  blow-off candle regime.

## 2. Locked decisions

| # | Decision | Choice |
|---|----------|--------|
| 1 | Slope feature | **`_diff` only** (`{tf}_rsi_ma{W}_diff`, 1-bar difference) — user-locked; `_slope` (OLS w5) out of scope |
| 2 | Grid | **Same-TF only, TF ∈ {15, 60, 240}**: TF-X diff classified against TF-X labels |
| 3 | 7-class cuts | **Defaults**: quantile p[2,10,30,70,90,98]; sym0 0±{0.3,1.0,2.0}·std; z ±{0.5,1.0,2.0} (extra class ≈ 2–2.5% of rows) |
| 4 | Approach | **A — host-side analysis harness** (reads volume pickles directly; no Docker; no prod code) |
| 5 | Fit protocol | Cuts fit on **2y only**, applied unchanged to oos2m (OOS-refit guard) |
| 6 | Commits | **Nothing committed** (code or external docs) until report approved |

## 3. Ground truth (verified 2026-08-06)

- `rsi_ma8/12/24`, `_diff`, `_slope` baked at all TFs in **both** datasets — no re-prep.
  - 2y: `/media/om/Alexandria/simple_trader/simple_trader_vol_long/train/2y_link_usdt/df_with_indicators.part_{00..24}.pkl` (43200 rows/part, 716 cols; part_24 = 15840 rows).
  - oos2m: `.../oos2m_link_usdt/df_with_indicators.pkl` (84961 rows, 752 cols).
- Label columns (`{tf}_plong_*`, `{tf}_pshort_*`, `{tf}_pslong_*`, `{tf}_psshort_*`):
  **present in oos2m, absent in 2y parts** → harness computes 2y labels per part via
  `indicators.labels.add_profit_labels` / `add_profit_strict_labels` (vectorized).
- Label specs come from `configs/indicators_config.yaml` `labels:` section
  (TF 15: x0.3 l15 y0.2; TF 60: x0.2 l15 y0.1; TF 240: x0.1 l15 y0.1; n ∈ {1,2}).
- Host python (pandas) reads the volume mountpoint fine — no root-owned-file risk.
- `rsi-quantile-sym0` worktree's uncommitted work is unrelated to this experiment
  (it productizes zone/move classes for the viewer); base is plain `experimental_imp_2`.

## 4. Measurement grid

- **Windows:** W ∈ {8, 12, 24} → feature `{tf}_rsi_ma{W}_diff`.
- **TFs:** {15, 60, 240}, same-TF labels.
- **Techniques** (cuts on the diff distribution, fit on 2y closed rows per TF):
  - `quantile` — percentile cuts.
  - `sym0` — symmetric around zero: 0 ± k·diff_std.
  - `zscore` — (x − diff_mean)/diff_std against fixed limits (equivalently
    diff_mean ± k·diff_std — the legacy `_five_tiers` family).
- **Class counts:**
  - 5-class: quantile p[10,30,70,90]; sym0 k∈{0.3,1.0}; zscore k∈{0.5,1.0}.
  - 7-class: quantile p[2,10,30,70,90,98]; sym0 k∈{0.3,1.0,2.0}; zscore k∈{0.5,1.0,2.0}.
- **Labels:** strict (`pslong/psshort`) and non-strict (`plong/pshort`), n ∈ {1,2},
  long + short, same TF as the feature.

Classifier configs: 3 W × 3 techniques × 2 class-counts × 3 TFs = 54; each scored
against 8 label columns (2 kinds × 2 n × 2 sides) on 2y and oos2m.

## 5. Method

1. **Row basis:** per-TF closed-candle rows only (dedupe 1-min forming duplicates —
   same basis as the 2026-07-22 RSI classification gate). Rows with NaN feature or
   NaN label dropped and counted.
2. **2y labels:** computed per part; per-part boundary tail (max n·tf + l minutes,
   ≈ 8h of a 30-day part) yields NaN labels and is dropped; dropped-row counts
   reported. No cross-part stitching (accepted, negligible loss).
3. **Fit:** per (W, TF, technique, class-count), cuts computed from the pooled 2y
   closed-row diff distribution. Same cuts applied to oos2m. No OOS refit.
4. **Score:** per class × label column, on 2y and oos2m separately.

## 6. Metrics (per grid cell)

1. **Class population** — count + share; degenerate/empty class detection.
2. **Label rate per class per side** — `P(label=1 | class)` for long and short
   columns + **lift** vs that side's base rate. (The spec's "amount of labels in
   each class".)
3. **Directional separation** — long-rate − short-rate spread per class; must grow
   with class strength; monotonicity checked across the ladder (Spearman of spread
   vs class index magnitude).
4. **Extra-class flip test (7-class only)** — per extreme tail, compare long vs
   short label rate in the *strong* class against the *extra* class of the same
   sign. PASS pattern: strong class → one side clearly dominant; extra class →
   dominance shrinks or flips to the opposite side. Direction-agnostic on purpose:
   the 2026-07-22 gate showed RSI move edge is inverted (strong-up → short), so
   which side is "continuation" is an empirical output, not an assumption.
5. **Aggregates for ranking** — mutual information (class vs label) and η²; used to
   rank W, technique, class-count per label kind. TF240 7-class tails are thin
   (~50–100 closed rows per tail on 2y, fewer oos) — flagged, not hidden.

## 7. Deliverables

- `external/docs/superpowers/experiment/results/rsi_parameters_selection_results.md`
  — analysis report: best W for strict and for non-strict; 5 vs 7 classes;
  technique comparison; per-measurement commentary; overall recommendation.
- Same directory: machine-readable `rsi_parameters_selection_results.json`
  (full per-cell metric tables the md summarizes).
- Harness in the worktree (`experiments/rsi_params_selection/` — driver script +
  config), reproducible end-to-end from the two dataset paths. Not registered in
  any pipeline; plain scripts.

## 8. Out of scope (YAGNI)

- `_slope` (OLS) feature variant; TF5/TF1440; cross-TF (higher-TF diff vs lower-TF
  labels) — revisit after this report if extra-class detection underwhelms.
- Productizing winning scheme as indicator fields / viewer markers (follow-up
  design like the 2026-07-22 quantile-sym0 one).
- NN wiring, multi-symbol, 4y.

## 9. Process

- New worktree `rsi-params-selection` off `experimental_imp_2` (git repo at
  `main/`, worktrees under `worktrees/`, absolute paths).
- Runs on host python against the volume mountpoint; nothing written into the
  volume; results land in external docs tree only.
- No commit/push of anything before the report is approved (then: harness commit
  in worktree needs explicit user confirmation as usual).
