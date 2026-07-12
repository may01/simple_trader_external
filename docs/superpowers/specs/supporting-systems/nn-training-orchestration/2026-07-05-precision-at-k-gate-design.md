# Precision@k promotion/search gate for direction_binary — design

**Date:** 2026-07-05
**Status:** approved (design), pending implementation plan
**Context:** [[project_nn_promotion_gate_broken]] — the `direction_binary` gate is
argmax accuracy, which a rare-positive target games via always-negative collapse
(~0.94 base rate). The `nn-features-only` lineage winner (v2, conv1d_seq→lstm→dense)
scored 0.7795 accuracy but only **0.138 long precision / 0.536 recall** (long base
rate 5.78%, ≈2.4× lift). We want the search + promotion to optimise the actionable
signal — long-class precision — not accuracy.

## Goal

Make Optuna search **and** lineage promotion optimise **precision@k for the long
class** (k = top 5% of bars by long-probability), then iterate the v2 architecture
under the new gate.

Non-goals: adding a new target kind; changing the long label definition; a general
metric-config registry; per-epoch precision@k early-stopping.

## Metric

`precision_at_k(p_long, y_long, k_frac=0.05) -> float`

- `p_long` = per-row long score = `preds[:, 0] - preds[:, 1]` (index 0 = long, per
  `_target_block` encoding `{side:0, other:1}`; monotonic under softmax so the raw
  logit margin ranks identically).
- Rank rows by `p_long` descending; take the top `k = ceil(k_frac * N)`.
- Return `TP / k` = fraction of the top-k that are truly long (`y_long == 1`).
- `lift = precision_at_k / base_rate`, `base_rate = mean(y_long)`.
- Edge cases: `N == 0` → `0.0`; stable sort for ties; `k >= N` → all rows;
  `base_rate == 0` → lift `0.0` (avoid div-by-zero).

Pure helper, no torch — unit-testable in isolation.

`PRECISION_AT_K_FRAC = 0.05` (module constant; single edit point to retune k).

## Wiring — three sites, one metric

1. **`training_loop._score_predictions`** (holdout → Optuna objective + `decide`
   gate). For `direction_binary`, the head score becomes **precision@5%** (was
   argmax accuracy). Additionally record precision@{1%,5%,10%} and lift@each in the
   returned `per_target` for the version reports; the **gate scalar is precision@5%**.
   `overall`/`holdout_score` = mean of head scores as today (single head here).

2. **Checkpoint gate metric** (`checkpoint_manager`, currently `metric="val_accuracy"`)
   → **`val_loss`, mode=min**, so the persisted/scored `_best.pt` is the min-val-loss
   epoch (CE loss ranks probabilities → precision-aligned), not the accuracy-collapse
   epoch. Early stopping already minimises `val_loss`, so this only aligns *which
   epoch is persisted*. This closes the two-scorer gap ([[project_nn_two_scorers]])
   without adding a noisy per-epoch precision@k pass.
   **Implementation note:** `checkpoint_manager._is_improvement` currently assumes
   higher-is-better; `val_loss` needs min-mode — add a `mode="min"|"max"` param (or
   gate on `-val_loss`). Verify before edit.

3. **`decide` margin** stays 0.01 (precision ∈ [0,1]; 1pp is a meaningful step).
   Revisit after the v1 baseline shows precision@5% variance across trials.

## Iterate

New lineage **`nn-features-precision`** (2y link_usdt), seeded from the v2 arch
(conv1d_seq→lstm→dense, 46 nn_features × 6 TF levels — the `nn-features-only`
winner). Same locked orchestration values (trials 8, K=2, max_versions 6, margin
0.01, budget 28800s). v1 = baseline (v2 arch re-scored/searched under precision@5%);
then evolve one structural change per version, hill-climbing precision@5% instead of
accuracy. Reports carry precision@{1,5,10%}+lift; the winner is judged on precision@5%.

## Testing

- Unit: `precision_at_k` — known arrays (perfect ranking → 1.0), all-negative → 0.0,
  ties, k rounding (`ceil`), `k >= N`, `base_rate == 0`.
- Regression: update existing `_score_predictions` tests that assert argmax-accuracy
  semantics for `direction_binary`.
- Docker-verified: one holdout scoring run reproduces precision@5% on the existing v2
  checkpoint (cross-check vs the ad-hoc recompute: long precision 0.138 was top-of-
  ranking global; precision@5% is a distinct, higher number — record the baseline).

## Risks / notes

- Optuna variance: precision@k on a 5% slice is noisier than accuracy; 8 trials may
  under-explore. Mitigation: keep val_loss selection (stable) + revisit margin.
- `_score_predictions` semantics change is global to `direction_binary` — any other
  consumer reading `holdout_score` as "accuracy" must be checked (grep before edit).
- Scope: `main/` pipeline change → dedicated branch, TDD, Docker integration test
  before iterating; spec + version reports to the external docs repo only.
