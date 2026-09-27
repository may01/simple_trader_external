# psh8 profit_strict NN labels — design

**Date:** 2026-07-12
**Base branch:** `nn-features-profit-strict-v4` (holds the 16 `ps{5,15,60,240}` profit_strict specs)
**Work branch:** `nn-psh8-labels` (off the above; ff-merge back)
**Status:** approved, in implementation

## Goal

A new NN set `psh8` = the existing 16-head `profit_strict` set with three changes,
to test whether a leaner feature set + deeper history helps the strict-label heads:

1. **Remove 10 ema-vs-ema diff features** (`ema_7_minus_ema_14` … `ema_50_minus_ema_100`) → 46 → 36 features.
2. **Remove the 1440-minute timeframe** → TFs 1/5/15/60/240 (was 1/5/15/60/240/1440).
3. **history_points 4 → 8** (deeper sequence window).

Train 2y, infer oos2m, coexist with the base 16 heads in the full viewer.

## Set definition

- New dir `configs/nn_specs/profit_strict_h8/`, **16 specs** = TF {5,15,60,240} × horizon {n1,n2} × side {long,short}.
- Each spec is a verbatim copy of the matching `profit_strict/ps{tf}_n{n}_{side}.yaml` with:
  - `timeframes:` — drop `- 1440`.
  - `indicators:` — drop the 10 `ema_*_minus_ema_*` lines (keep `ema_*_minus_close`).
  - `history_points: 4` → `8`.
  - `name:` `nnfo_ps{tf}_…` → `nnfo_psh8_{tf}_…`; target `name:` `ps{tf}_…` → `psh8_{tf}_…`.
  - Everything else unchanged (layers, activation, dropout, loss/optimizer/lr/weight_decay,
    batch/epochs/val/early-stop/class_weight/seed, and the profit_strict target label params).
- Output columns: `nn_res_psh8_{tf}_n{n}_{side}_prob` — distinct from base `nn_res_ps{tf}_…_prob`,
  so the two sets never collide.

## No data prep

Both removals are strict subtractions of columns already materialized in the 2y and oos2m
`df_with_indicators.pkl`. Changing timeframes/features/history yields a fresh `spec_hash`, so
the dataset + weights rebuild from scratch — but **zero new indicator materialization** is needed.

## Train

Runs inside the nn-train GPU container via the existing batch driver, glob pointed at the new dir:

```
NN_TRAIN_ENV=configs/nn_train_dataset_2y.env \
docker compose -f docker-compose.yml -f docker-compose.gpu.yml run --rm \
  -e PYTHONDONTWRITEBYTECODE=1 -e NUM_WORKERS=8 \
  -e NN_SPEC_GLOB=/code/configs/nn_specs/profit_strict_h8/*.yaml \
  nn-train python3 scripts/nn_pstrict_batch.py train
```

Resumable (skips any head whose `{spec_hash}/all_best.pt` exists). 16 sequential fresh dataset builds.

**Memory risk (hp=8):** 2y ≈ 1.05M rows; window matrix ≈ 6 GB float32. Base hp=4 (6 TF, 46 feat)
survived on the 15 GB host; hp=8 (5 TF, 36 feat) is comparable order. Budget = 35 GB (15 host + 20 swap).
Start `NUM_WORKERS=8`; **on OOM fall back to `NUM_WORKERS=4`**; last-resort fallback = df-free training
driver (see 2y-train-infer-OOM note).

## Infer + merge (coexist)

The base `nn_pstrict_batch.py infer` overwrites `{oos}/df_with_nn.pkl` and its canonical
`df_with_nn_heads.pkl` — running it for psh8 would clobber the base 16 heads. So a dedicated
`scripts/nn_psh8_infer_merge.py`:

1. Runs inference for the 16 psh8 specs on oos2m (~87k rows — low RAM).
2. Writes psh8 sidecar `df_with_nn_psh8_heads.pkl` (16 new heads).
3. Reads existing `{oos}/df_with_nn.pkl`, column-unions the 16 psh8 heads → writes back a
   **32-head** `df_with_nn.pkl`.
4. Leaves the base `df_with_nn_heads.pkl` untouched (base set stays canonical/re-derivable).

oos2m dir: `/media/om/Alexandria/simple_trader/simple_trader_vol_long/train/oos2m_link_usdt`
(in-container `/trader_data_long/train/oos2m_link_usdt`).

## Visualize

```
LONG_ENV=configs/oos2m_dataset.env docker compose up -d view-full   # → :8080
```

Viewer discovers all `nn_res_*` columns dynamically → both the 16 base and 16 psh8 heads show.

## Interpretation notes

- `val_acc` is misleading for rare-positive strict labels (near base rate). Honest signal =
  OOS prediction variance and long≠short separation.
- "Visualization" here = NN inference surfaced in the full view, not a PnL backtest.

## Integration

Branch `nn-psh8-labels` ff-merges back into `nn-features-profit-strict-v4`. Commit only on
explicit user confirmation.
