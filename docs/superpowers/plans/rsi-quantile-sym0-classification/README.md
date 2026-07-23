# Plan — RSI Quantile Zone + Sym0 Move Classification (Coexist A/B)

**Spec:** `../../specs/2026-07-22-rsi-classification-quantile-sym0-design.md`
**Style:** layer-first (Docker → stats → indicators → viewer → regen), interface-before-code,
RED integration test per boundary, Docker-verified.
**Branch:** dedicated worktree off `experimental_imp_2`, revertable.

## What ships
Two NEW coexisting fields beside the legacy `zone_class`/`move_class`:
- `zone_class_q` — `rsi_ma8` bucketed by quantile cuts `[p10,p30,p70,p90]` → 0..4.
- `move_class_sym0` — `rsi_ma8_diff` bucketed by `0 ± {0.3,1.0}·diff_std` → −2..2.
Plus additive stats (`zone_cuts`/`move_cuts`), a companion `rsi_side_stats.json`, viewer
markers + side-aware tooltip. Legacy fields untouched.

## Docker entry points (ground truth — Step 0)
```bash
# Unit + integration tests (image: simple_trader)
docker run --rm -v "$PWD":/code -w /code simple_trader \
  python3 -m pytest tests/unit/data_layer/test_rsi_class_separation.py -q

# Regen a dataset (prepare pipeline: indicators + stats bake into df_with_indicators)
#   env selects dataset/volume per the nn-orchestrator run recipe (ROOT_FOLDER=long, 2y/oos2m)
docker compose run --rm ohlc_gen          # trainer.py generate_full_ohlc

# Viewer (8080 = view-full = data_viewer)
docker compose up -d view-full            # → localhost:8080 ; restart to redeploy
```
Verified: [ ] test image builds & pytest runs · [ ] `ohlc_gen` runs · [ ] `view-full` serves 8080

## Layer order & execution
| task | layer | boundary |
|------|-------|----------|
| task-01 | gate pre-check | `gate.py` PASS before any field code (hard block) |
| task-02 | stats (test data prep, L3) | `rsi_classification.json` += cuts; `rsi_side_stats.json` |
| task-03 | indicators (L4) | `zone_class_q` / `move_class_sym0` consume the cuts |
| task-04 | wiring (L4) | registry + config expose the fields to the prep pipeline |
| task-05 | viewer (frontend) | markers + side-aware tooltip consume both jsons + columns |
| task-06 | regen + deploy | prep 2y + oos2m (OOS no-refit guard) → merge → restart 8080 |

Rule: task N+1 does not start until task N is GREEN in Docker. task-01 is a hard gate.

## Acceptance
- `gate.py` stays PASS (move directional 3/3; zone magnitude re-gate) on 2y-test + oos2m.
- New columns present, quantile classes ~balanced, both jsons non-NaN, legacy unchanged.
- 8080 shows legacy + new markers on the rsi_ma8 subplot; tooltip shows long/short win-rate.

## Revert
Delete the worktree/branch. Coexist = nothing overwritten; legacy path intact.
