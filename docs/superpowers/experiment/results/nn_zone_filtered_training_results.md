# NN on Zone-Filtered Points — Results

**Date:** 2026-07-24
**Plan:** `plans/2026-07-24-nn-zone-filtered-training.md`
**Branch:** `nn-zone-filtered-training` (from `next-candle-bounds-nc` @ 2788110)
**Data:** train `2y_link_usdt` zone-filtered rows, eval `oos2m_link_usdt` zone-filtered rows.
**Models:** 6 — tf ∈ {15, 60, 240} × {long, short}.

## Setup

- **Base**: `full-snapshot-dense-v5` architecture + full 102-indicator input over TFs
  1/5/15/60/240/1440, history 4 (its own 0.9422 "holdout" is the known broken-gate
  collapse on direction_binary — only the arch + feature set were reused).
- **Filter**: `{tf}_cbnc_inzone_{side}` (hybrid nc zones: SL = closed bound, target =
  nc bound −0.15 %, frac 0.05), computed for 2y by the extended `run_cbnc.py`
  (G1–G3 gates pass machine-exact on 2y as well). In-zone training mass:
  91k–125k rows per model; after NaN drop ≈ 100k–120k.
- **Target**: `{tf}_ps{long|short}_n2_*` strict labels (2-candle horizon of the same tf).
- **Infra added**: `filter_column` spec field → row mask in `NNDataset` (train/val/holdout
  all from the filtered population), hash-safe (unset ⇒ every pre-existing spec/dataset
  hash unchanged, verified); trainer joins the cb/cbnc sidecars; `_materialise`
  restructured two-pass (one float64 lookback block alive at a time — the old
  all-at-once path needs ~20GB on 2y for a 102-indicator spec and OOMs a 15GB host);
  regression byte-identical.
- **Training**: single-shot (`NN_TRAIN_MODE=single`), 50 epochs, GPU; ~5 min/model.
- **Eval**: checkpoint-normalised inference (`run_inference`, bundled train stats —
  leakage-free) on CPU (85k-row batch OOMs the 4GB GPU), scored ONLY on each model's
  own oos2m in-zone rows. Baseline = incumbent nn-features-only `nnfo_ps{tf}_n2_{side}`
  head (trained unfiltered) scored on the SAME rows.

## Results (oos2m, in-zone rows only)

| model | n | in-zone base | AUC zf / nnfo | p@5% zf / nnfo | lift@5 zf / nnfo | p@10% zf / nnfo |
|---|---|---|---|---|---|---|
| zf15 long | 13 669 | 0.207 | **0.621** / 0.572 | **0.385** / 0.258 | **1.86** / 1.25 | 0.364 / 0.252 |
| zf15 short | 11 135 | 0.218 | **0.601** / 0.543 | **0.312** / 0.257 | **1.43** / 1.18 | 0.300 / 0.236 |
| zf60 long | 11 931 | 0.120 | **0.652** / 0.627 | **0.268** / 0.209 | **2.24** / 1.75 | 0.230 / 0.208 |
| zf60 short | 9 605 | 0.114 | **0.666** / 0.664 | **0.169** / 0.146 | **1.48** / 1.28 | 0.172 / 0.157 |
| zf240 long | 10 262 | 0.074 | 0.605 / **0.630** | **0.125** / 0.086 | **1.69** / 1.16 | 0.135 / 0.104 |
| zf240 short | 6 853 | 0.084 | 0.578 / **0.585** | **0.090** / 0.044 | **1.07** / 0.52 | 0.109 / 0.089 |

## Findings

1. **The zone itself is the first-stage signal.** In-zone strict-label base rates are
   ~2× the population's (15 long: 0.207 in-zone vs 0.098 overall) — the nc entry zone
   already concentrates profitable points before any NN.
2. **Zone-filtered training beats unfiltered training on the zone population** —
   precision@5% higher on **6 of 6** models, AUC on 4 of 6. Stacked with the zone's own
   enrichment, zf15-long p@5 = 0.385 ≈ **3.9× the population base rate**; zf60-long
   lift@5 = 2.24 within the zone.
3. **tf240 is the weak spot** (thin: ~92k train rows from only 4.4k candles of label
   variation; short n=6.9k eval rows). AUC slightly below the incumbent, though top-k
   precision still ~1.5–2× it. Treat 240 numbers as indicative only.
4. Raw val accuracy at 0.5 threshold is uninformative (balanced class weights push
   probabilities off-centre); ranking metrics are the meaningful readout.

## Caveats

- Bounds models (hence the 2y zone filter) are fit on the same 2y window — the training
  filter is partially in-sample. oos2m evaluation is clean end-to-end (frozen bounds,
  frozen NN, bundled normalisation).
- One pair, one 2-month OOS window — the standing caveat of this whole line.
- Precision/lift ≠ P&L: no fee/realized-R accounting here. The natural next step is
  feeding zf top-k signals into the realized-R harness the bounds experiments already
  call for.

## Artifacts

- Checkpoints + tensor caches under `train/link_usdt/nn/{checkpoints,datasets}/{spec_hash}`
  (spec hashes: zf15L 6efbc615…, others per `configs/nn_specs/zone_filtered/*.yaml`).
- 2y sidecars: `train/2y_link_usdt/df_with_candle_bounds{,_nc}.pkl` + meta/metrics json.
- Eval: `zf_eval_oos2m.json` (scratchpad; numbers reproduced above).
- Code on branch: `configs/nn_specs/zone_filtered/*` (6 specs),
  `notebooks/candle_bounds_nc/{train_zf_all.sh,eval_zf.py}`, `run_cbnc.py` (generalised),
  `nn/nn_model_spec.py` + `nn/nn_dataset.py` (filter_column + two-pass memory fix),
  `training/trainer.py` (sidecar joins). Uncommitted — pending review.
