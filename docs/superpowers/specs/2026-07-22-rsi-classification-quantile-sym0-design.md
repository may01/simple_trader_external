# RSI Classification — Quantile Zone + Sym0 Move (Coexist A/B) — Detailed Design

**Date:** 2026-07-22
**Status:** approved design, ready for implementation plan.
**Scope:** add two new *coexisting* viewer-marker classification fields, fit from better
thresholds, validated by a side-aware gate that ran BEFORE any code.
**Branch:** dedicated feature branch off `experimental_imp_2`, revertable (coexist = nondestructive).

---

## 1. Problem

`zone_class` (RSI level) and `move_class` (RSI momentum) both bucket their feature into 5
tiers via `mean ± {0.5,1}·std` (Gaussian z-score) in
`indicators/library/classification.py`. Two defects:

1. **Method is distribution-blind.** RSI is bounded [0,100], skewed, fat-tailed; std is
   inflated by spikes. Tier populations are uneven and the "neutral" band is arbitrary. For
   `move` (`rsi_ma8_diff`) the split centres on `diff_mean` (~0.27–0.75), so "neutral" is a
   drift band, not "flat slope".
2. **Stored stats are degenerate.** `stats/train/link_usdt/rsi_classification.json` carries
   TF240 `std=1.75` while the real 2y std is **10.57** (a smoke-set artifact) — production
   `zone_class` at 240 is currently broken.

### Evidence (LINK/USDT, 2y closed candles, fit train 70% → score test 30%, H=1 bar)

Full per-class forward-return curves + metrics + side-aware heatmaps:
artifact `970763e2-10fb-45f4-a419-2d9ee142d2ee`. Harness in the analysis scratchpad
(`bench.py`, `side.py`, `gate.py`).

- **Move sym0 (0 ± {0.3,1.0}·diff_std):** best class balance everywhere (entropy ~0.99),
  MI/η² 2–3× current at TF240/1440, neutral centred on 0.
- **Zone quantile (p10/30/70/90):** distribution-agnostic, non-degenerate by construction,
  best OOS MI where zone matters (TF240 MI .0107 vs current .0033), largest extreme
  separation.
- **Supervised tree binning: rejected** — overfits, collapses to 1–13-sample classes, wild
  OOS spikes; in-sample η² is a mirage.

---

## 2. Key findings that shape the design

1. **Zone is not directional — it's a U (mean-reversion / volatility).** Both very-low and
   very-high classes show *positive* forward return; the direction of the per-side edge
   **flips between test and oos** (e.g. TF60 zone: `High→long` test vs `V.high→short` oos).
   Zone must be judged on **move-size (|return|)**, not signed direction.
2. **Move is directional and inverted — stable.** strong-down → +return (long), strong-up →
   −return (short); holds across test AND oos. `sym0` sharpens it and centres neutral on 0.
3. Zone signal grows with timeframe (near-flat at 15m, ~100× at 1d); move carries the
   intraday signal.

---

## 3. Decisions (all locked with the user)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Deploy | **Coexist / A-B** — new fields beside legacy; viewer shows both; nondestructive |
| 2 | JSON schema | **Additive** — keep `mean/std/diff_*`, ADD `zone_cuts`/`move_cuts`; `over_low/over_high` unchanged |
| 3 | Train-only leak fix | **Deferred** — keep full-data fit (markers cosmetic today) |
| 4 | Regen scope | **2y + oos2m** |
| 5 | Side-aware | **Gate before coding + viewer tooltip** (long/short win-rate per class) |
| 6 | Zone acceptance | **Keep quantile, re-gate on balance + \|return\| magnitude + OOS MI** (per-side direction is the wrong yardstick for zone) |
| 7 | Isolation | **Dedicated branch, easy revert** |

---

## 4. Acceptance gate — ALREADY RUN (this is a record, re-run in CI/plan task-01)

`gate.py`: fit thresholds on 2y, score on 2y-test AND oos2m (fit-2y → score-OOS).

**Move — directional gate** (best per-side lift, TF 1h/4h/1d, recommended ≥ current − 0.3pp
on BOTH test & oos): **3/3 PASS**. Per-side class stable: S.Dn→long, S.Up→short.

**Zone — magnitude re-gate** (`η²(|fwd|)` + extreme-vs-neutral |return| separation):
quantile ≥ current at 1h/4h on both test & oos (e.g. TF240 magsep 40.6 vs 34.4 bps test,
64.6 vs 39.1 oos; η²|fwd| .0157 vs .0111 test). TF1440 noisy (59 oos bars). **PASS on the
correct metric.**

Gate is the go/no-go: **both fields GO.** Plan task-01 re-runs it as a hard pass/fail before
implementing fields.

---

## 5. Architecture — layer by layer

Ordered Docker-first, interface-before-code, integration-tested per layer.

### Layer A — stats (data attributes)
`indicators/attributes.py :: _compute_rsi_classification`
- **Add** per-TF, additively:
  - `zone_cuts = percentile(rsi_ma8_closed, [10,30,70,90])`
  - `move_cuts = [-1.0, -0.3, 0.3, 1.0] · diff_std`
- Keep `mean/std/diff_mean/diff_std`. Keep "<2 valid rows → skip TF, no NaN".
- Full-data fit (decision 3). Missing-TF fallback in `_get_tf_classification` already carries
  new keys (they ride the same entry).
- **Interface (JSON entry):** `{mean, std, diff_mean, diff_std, zone_cuts:[4], move_cuts:[4]}`.
- **Companion file** `rsi_side_stats.json` (for Layer D tooltip): per TF, per new-field class
  → `{long_winrate, short_winrate, long_lift, short_lift, base_long}`. Written absent-only,
  same guard as `rsi_classification.json`. Delete on regen.

### Layer B — classification fields
`indicators/library/classification.py`
- **Add** shared helper `_apply_cuts(x, cuts, base) -> np.ndarray` = `np.digitize(x, cuts)` +
  base offset; NaN → middle tier (matches `_five_tiers` NaN policy).
- **Add** `ZoneClassQField` (`name="zone_class_q"`, feature `rsi_ma8`, `zone_cuts`, base 0 →
  0..4) and `MoveClassSym0Field` (`name="move_class_sym0"`, feature `rsi_ma8_diff`,
  `move_cuts`, base −2 → −2..2). `applies_to [15,60,240,1440]`, group `classification`,
  resource `rsi_classification.json`.
- **Legacy `zone_class`/`move_class`/`_five_tiers` untouched.**
- **Interface:** each field `.compute(data_point, tf) -> pd.Series[int]`.

### Layer C — wiring
- `indicators/registry.py`: register `zone_class_q`, `move_class_sym0`.
- `configs/indicators_config.yaml`: add both (group classification, `depends_on`
  `[rsi_ma8]` / `[rsi_ma8, rsi_ma8_diff]`, resource `rsi_classification.json`).

### Layer D — viewer + side-aware tooltip
`frontend/data_viewer.py`
- Add marker specs for `zone_class_q` (diamond, distinct colormap) and `move_class_sym0`
  (circle), drawn on the `rsi_ma8` line, skip-if-absent. Legacy markers stay → **A/B on one
  chart**.
- **Side-aware tooltip (decision 5):** each new-class marker's hover shows the class's
  **long win-rate and short win-rate** (and lift vs base) for that TF, read from a small
  per-TF side-stats table baked at prepare time (see Layer A note below) or computed from the
  loaded window. Keep it read-only; no strategy wiring.
  - **Source (decided): precompute `rsi_side_stats.json`** alongside `rsi_classification.json`
    at prepare time — per TF, per new-field class: `{long_winrate, short_winrate, long_lift,
    short_lift, base_long}` over closed rows (forward return over 1 TF-bar, side-agnostic
    close-to-close). Fit on the SAME rows/stats as the cuts (2y for the 2y set; 2y-fit reused
    for oos2m). Viewer reads it read-only. Rejected: computing on the displayed window
    (unstable, window-dependent).

### Layer E — regen (2y + oos2m)
- Delete `rsi_classification.json` for 2y (`stats/train/link_usdt/`) and oos2m stats so new
  keys compute.
- Re-run prepare for 2y (25 parts) + oos2m (single `df_with_indicators.pkl`) so new class
  columns bake in. **OOS correctness:** oos2m must load the **2y-fit** cuts (no refit) — copy
  the 2y json into oos2m stats or point `stats_folder()` at 2y before prepare; stats
  regenerate only if absent, so guard against an accidental OOS refit.
- Deploy to 8080: merge branch → `experimental_imp_2`, `docker restart`. Watch container
  root-owned files blocking the merge.

---

## 6. Testing (interface-first, Docker-verified per layer)

- **Unit** (`tests/unit/data_layer/test_rsi_class_separation.py`, extend):
  - `zone_class_q` quantile boundaries → 0..4, ~balanced.
  - `move_class_sym0` symmetric-zero boundaries → −2..2, neutral brackets 0.
  - JSON additive keys present (`zone_cuts`, `move_cuts`), never NaN; missing-TF fallback
    carries them.
  - `_apply_cuts` NaN → middle tier.
- **Integration (Docker):** prepare a small dataset → new columns present, quantile classes
  ~20% each, JSON has both cut arrays, legacy fields unchanged.
- **Gate (CI/manual):** `gate.py` re-run must stay PASS before merge.

---

## 7. Out of scope (YAGNI)

- Train-only leak fix (decision 3, deferred).
- `zone_dist` distance-from-neutral encoding (flagged by the gate as the "principled" zone
  fix; revisit if quantile A/B underwhelms in the viewer).
- Replacing legacy fields; NN-input / strategy wiring; 4y regen; multi-symbol.

---

## 8. Process

- Dedicated branch off `experimental_imp_2`; coexist keeps it revertable.
- Task files → `external/docs/superpowers/plans/…` (task-NN). No GitHub issues.
- No commit/push without explicit confirmation.
