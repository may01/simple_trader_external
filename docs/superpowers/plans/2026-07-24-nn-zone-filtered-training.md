# NN on Zone-Filtered Points — Plan

**Date:** 2026-07-24
**Branch:** `nn-zone-filtered-training` (from `next-candle-bounds-nc` @ 2788110, same worktree)
**Spec (user):** for tf ∈ {15, 60, 240}: filter 1-min candles by the zone markers, train the
NN on those points only. Base = best model with the full input-indicator set. Target =
buy/sell strict labels, 2-candle horizon of the corresponding tf.

## Mapping

- **Zone filter** = `{tf}_cbnc_inzone_long` (buy) / `{tf}_cbnc_inzone_short` (sell) from the
  next-candle-bounds-nc experiment — hybrid space (SL = closed bound, target = nc bound
  −0.15 %), frac 0.05. Long-zone rows feed the long model, short-zone rows the short model.
- **Target** = `{tf}_pslong_n2_*` / `{tf}_psshort_n2_*` strict labels (n = 2 candles of the
  same tf). Present in `2y_link_usdt` (train) and `oos2m_link_usdt` (validation).
  OOS base rates: 15: 9.8 %/9.1 %, 60: 6.3 %/5.9 %, 240: 5.3 %/5.8 % (long/short).
- **Base model**: best full-indicator-set spec — `configs/nn_specs/profit_strict/ps{tf}_n2_{side}.yaml`
  family (46-indicator input across TFs 1/5/15/60/240/1440, conv1d+lstm+dense backbone),
  pending confirmation against the volume lineage reports. → 6 models: {15,60,240} × {long,short}.

## Steps

1. **Zone markers for 2y** — the nc artifact exists only for oos2m. Extend the cbnc driver
   to also run on `2y_link_usdt`: fit on 2y_az closed candles (unchanged), infer closed +
   forming bounds over the 2y 1-min rows, hybrid zones, write
   `df_with_candle_bounds_nc.pkl` sidecar next to the 2y dataset.
   *Caveat (accepted, documented): the bounds models are fit on the same 2y window — the
   training-set filter is partially in-sample. The filter is a row-selector, not the target;
   oos2m evaluation stays clean end-to-end.*
2. **Row filtering in the NN dataset path** — mechanism TBD from pipeline investigation:
   either a native mask hook in `nn/nn_dataset.py` or a new spec/env knob
   (`filter_column`) that restricts training/holdout rows to marker==True. Must apply to
   train AND holdout so the model is scored on the population it will serve.
3. **Specs** — 6 new spec files (e.g. `configs/nn_specs/zone_filtered/zf{tf}_n2_{side}.yaml`),
   identical to the base ps*_n2 specs + the filter knob. New study/checkpoint names so
   nothing collides with existing lineages.
4. **Train** on `2y_link_usdt` (GPU compose override, NN_TRAIN_ENV=2y recipe), 6 runs.
5. **Evaluate** on oos2m zone-filtered rows: precision@k / lift vs the in-zone base rate,
   vs the unfiltered nnfo_ps*_n2 models scored on the same in-zone rows (does zone-filtered
   training beat zone-filtered *inference* of the existing models?).
6. **Results doc** + viewer surfacing if useful (existing nn head columns pattern).

## Risks

- In-zone sample counts 2y: must check after step 1 — tf240 zones may be thin for NN training.
- Known infra traps (memories): two scorers must both know the target kind; promotion gate
  metric; 2y OOM → chunked/memmap paths; GPU infer OOM at hp>8 → CPU infer.
