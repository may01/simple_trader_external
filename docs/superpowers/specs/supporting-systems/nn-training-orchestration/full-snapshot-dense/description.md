# Archetype: full-snapshot-dense

## Design thesis
Every indicator is pre-computed at every timeframe and stored as a `{tf}_{indicator}`
column, so a **single-instant snapshot row already encodes multi-resolution market
state** — 1-minute micro-structure through 1440-minute macro regime — side by side.
This archetype tests one hypothesis: *breadth beats curation*. Feed a wide dense MLP
the **entire** feature set across **all six** timeframes with **no manual selection and
no temporal modelling**, and let the network discover the cross-feature and
cross-timeframe interactions itself. It **wins** if the curated, hand-picked feature
subsets we normally use are leaving signal on the table — i.e. the network finds a
useful interaction (e.g. 240m trend alignment × 1m RSI exhaustion) that a curated model
never had the columns to see. It **loses** if the ~600-wide input is mostly noise and
collinearity (nine overlapping EMAs, three Bollinger bands, redundant RSI MAs), so the
MLP dilutes or overfits and underperforms the curated `recurrent-temporal` winner
(2.50× precision lift @thr0.7 on the same 2y LINK holdout). Either way it is the
**kitchen-sink baseline** that tells us whether feature curation is earning its keep, and
whether cross-timeframe interaction (captured here as a flat concatenation, not parallel
branches) carries signal at a single instant without any sequence history.

## Indicators (features) — rationale
All non-target fields from `indicators_config.yaml` that carry usable data in the 2y
dataset are included by design — **102 of the 108** non-target fields. The `targets`
group (`tgt_long`, `sl_long`, `tgt_short`, `sl_short`, `ZB`, `ZS`) and the
`classification` group (`move_class`, `zone_class`, `over_low`, `over_high`) are excluded
because they are prediction labels (forward-looking → leakage), not inputs. Six further
names are dropped because the 2y `link_usdt` `df_with_indicators` does not carry usable
values for them: all five alignment flags (`align_5`/`align_15`/`align_1440` have no
`{tf}_{ind}` column at all; `align_60`/`align_240` exist only as `15_align_60`/
`60_align_240` and are entirely NaN), and `vol_regime` (its `15/60/240_vol_regime`
columns are entirely NaN, and it is absent at 1/5/1440) — any all-NaN column forces the
row-wise NaN-drop to zero rows, so they cannot be included. With the remaining 102 the
full 2y series (1,052,560 one-minute rows) survives the NaN-drop intact. **Exhaustive
inclusion is the hypothesis**, so the per-feature dependency argument is made per group;
every listed name exists verbatim in `indicators_config.yaml`.

- **momentum (7):** `rsi_14`, `rsi_ma8`, `rsi_ma12`, `rsi_ma24`, `rsi_ma8_diff`,
  `rsi_ma12_diff`, `rsi_ma24_diff` — overbought/oversold state and its rate of change;
  the smoothed RSI MAs and their diffs carry momentum acceleration, the signal a
  next-bar long entry keys off.
- **trend (11):** `ema_7`, `ema_14`, `ema_25`, `ema_50`, `ema_100`, `macd_12_26_9`,
  `macd_signal_12_26_9`, `macd_hist_12_26_9`, `macd_5_13_9`, `macd_signal_5_13_9`,
  `adx_14` — the trend backbone: EMA ladder position, MACD impulse (two speeds), and
  ADX trend strength. Their *relative* geometry (see price_derivatives) is what a long
  entry needs; raw levels are kept so the net can form its own interactions.
- **volatility (11):** `atr_14`, `natr_14`, `natr_14_ma_5`, `atr_14_ma_5`,
  `bb_upper_20_2`, `bb_middle_20_2`, `bb_lower_20_2`, `bb_upper_10_15`, `bb_lower_10_15`,
  `bb_upper_20_3`, `bb_lower_20_3` — the strict target/stop are defined in ATR units, so
  the model must see the volatility regime to know whether a 0.3-ATR move is imminent;
  Bollinger envelopes give the squeeze/expansion context.
- **oscillators (4):** `cci_14`, `cci_14_ma_5`, `cci_diff`, `sar_002_02` — mean-reversion
  extremes (CCI) and the parabolic-SAR flip level; complementary to RSI for pinpointing
  exhaustion turns.
- **volume (3):** `vol_ma_20`, `vol_buy_ma_20`, `vol_sell_ma_20` — participation and the
  buy/sell split; conviction behind a candidate move, which `recurrent-temporal` v5 found
  additive.
- **price_derivatives (18):** `close_diff_prc`, `close_diff_prc_rm_6`,
  `close_diff_prc_rm_6_mean_above`, `close_diff_prc_rm_6_mean_below`, `high_diff_prc`,
  `high_diff_prc_rm_6`, `high_diff_prc_rm_6_mean_above`, `high_diff_prc_rm_6_mean_below`,
  `low_diff_prc`, `low_diff_prc_rm_6`, `low_diff_prc_rm_6_mean_above`,
  `low_diff_prc_rm_6_mean_below`, `close_diff_prc_rm_6_std_above`,
  `close_diff_prc_rm_6_std_below`, `high_diff_prc_rm_6_std_above`,
  `high_diff_prc_rm_6_std_below`, `low_diff_prc_rm_6_std_above`,
  `low_diff_prc_rm_6_std_below` — normalised bar-to-bar returns and their rolling
  mean/std bands; scale-free micro-structure the entry actually fires on.
- **trend_flags (2):** `trend_up_50`, `trend_down_50` — the binary 50-period regime
  gate; a long-only strict entry should behave differently inside an up-regime.
- **nn_features (52):** the engineered set built specifically for NN consumption —
  `nn_rsi_ma8_norm_mean_20`, `nn_close_diff_atr_14_ma_5`; the *relative-geometry*
  block `bb_*_minus_close`, `ema_*_minus_close`, `vol_ma_20_minus_volume`, and every
  `ema_i_minus_ema_j` pair (price position vs each MA and MA-vs-MA spread — the trend
  geometry, made explicit so a dense layer need not learn subtraction); the *slope*
  block `macd_*_slope`, `ema_*_slope`, `adx_14_slope`, `rsi_ma*_slope`,
  `cci_14_ma_5_slope` (first differences → local direction); the candle-shape block
  `logret`, `range_atr`, `body_ratio`, `wick_up`, `wick_dn`; and the cyclical time
  encodings `sin_tod`, `cos_tod`, `sin_dow`, `cos_dow` (session/day seasonality).
  (`vol_regime` and the multi-timeframe alignment flags `align_*` — which would have been
  the most direct test of the cross-timeframe thesis — are all entirely NaN or absent in
  this 2y dataset and so are omitted; regenerating them upstream is the obvious next
  improvement to actually exercise that thesis.)

**Timeframes used:** all of `[1, 5, 15, 60, 240, 1440]`. Each is a different horizon of
context pre-aligned into the snapshot row: 1m/5m carry execution-scale micro-structure,
15m is the target-label resolution, 60m/240m give swing context, 1440m fixes the daily
regime. Including all six *is* the "all timeframes" mandate; the dataset builder emits
`{tf}_{indicator}` only where the column exists (`applies_to`-aware), so ragged features
drop cleanly rather than fabricating columns.

## Layers — real-data dependency rationale
`history_points = 1` — a **pure snapshot**, no time axis. The multi-timeframe columns
already carry longer horizons (the 1440m indicators summarise ~a day into one value), so
temporal modelling is deliberately withheld to isolate the "breadth at one instant"
hypothesis; a history window would also multiply the already-~600-wide input by the
window length.

- `dense(256)` → **snapshot cross-feature interaction at a single instant** across the
  full ~600-wide multi-timeframe vector (no time). First projection: compresses the
  large, collinear input into a dense interaction basis.
- `dense(128)` → snapshot feature interaction over the learned basis; the funnel forces
  the network to combine, not memorise, the wide input.
- `dense(64)` → final snapshot interaction layer feeding the head; the narrow bottleneck
  is the regulariser against overfitting a 600-wide input.

Every layer maps to the same real-data dependency — cross-feature interaction at one
instant — which is exactly the archetype's claim. All three kinds are `dense`, all in
`{dense, lstm, gru, conv1d}` → **buildable-now**. No `conv1d`/recurrent layer is used:
this archetype asserts no local-pattern or temporal dependency, by design (that is what
`recurrent-temporal` already covers).

## Target — rationale
`direction_binary`, `side="long"`, `horizons=[1]`, strict 15-minute long label
(`label_tf=15`, `label_m=1.0`, `label_x=0.3`, `strict=True`, `label_l=15`,
`label_y=0.2`) — **the exact target of the `recurrent-temporal` v6 winner**. Reusing it
verbatim is deliberate: it lets the orchestrator compare this kitchen-sink MLP's lift
directly against v6's 2.50× @thr0.7 on the same 2y LINK holdout, so the experiment
isolates the single variable under test — *feature breadth (snapshot MLP) vs curation +
temporal modelling (recurrent)*. The strict clean-entry window (`l=15`, `y=0.2 ATR`)
keeps the positive class to the ~6% high-quality long entries, matching the imbalance the
`class_weight="balanced"` setting is tuned for.

## Initial hyperparameters — and why
- **batch_size = 128** — locked starting value for a non-recurrent stack (recurrent
  archetypes drop to 64); wide input, small model, so 128 keeps gradient estimates stable
  and the GPU busy.
- **epochs = 50** — locked; ample for a shallow MLP with early stopping to cut in.
- **early_stopping_patience = 8** — locked; halts once holdout stops improving, the main
  guard against overfitting the 600-wide input.
- **learning_rate = 1e-3** — locked Adam default; Optuna-tuned later.
- **dropout = 0.2** — locked; the primary regulariser given the wide, collinear input.
- **units = 256 / 128 / 64** — a funnel: compress the wide input, then bottleneck toward
  the head. Optuna-tuned later.

Per **ADR-0001**, only `units`, `learning_rate`, and `dropout` are Optuna-tuned
dimensions; the layer **kinds and count** (3× dense) and the target are **fixed here** and
must not move during the numeric search.

## VRAM note (4 GB GPU)
Input width = 102 features across the timeframes where each is materialised = **474
columns** (measured on the 2y df; tf 1/5/1440 carry 56 features each, tf 15/60/240 carry
~102), with `history_points=1` so no time-axis multiplier. Parameters ≈ 474·256 + 256·128
+ 128·64 + 64·2 ≈ **160 K** (~0.65 MB
FP32). At batch 128 the activation footprint is a few MB — the model itself uses well
under 1 % of the 4 GB ceiling. The real memory pressure of this archetype is the **wide
dataset tensor** on the host (≈650 float columns × ~200 K rows per timeframe-block),
not the GPU; `history_points=1` keeps the content-addressed tensor cache far smaller than
`recurrent-temporal`'s history-20 blocks. If a widened Optuna trial ever OOMs, the
**OOM→CPU retry** path is the safety net.

---
**Materialized spec:** `/trader_data_long/train/link_usdt/nn/specs/cef7e1064ab585decc8ff6e3ce1db73249dbc58124501c2389404da59880782e/spec.yaml`
**spec_hash:** `cef7e1064ab585decc8ff6e3ce1db73249dbc58124501c2389404da59880782e` (`cef7e106`)
**pair:** `link_usdt` · **buildable-now:** yes (layer kinds ⊆ {dense}) · **features:** 102 (of 108; 5 alignment flags + `vol_regime` unusable in the 2y dataset) · **timeframes:** [1,5,15,60,240,1440] · **history_points:** 1 · **study:** `full_snapshot_dense_2y_v1`
**Superseded during v1 bring-up (data reality, not design):**
- `77616518…` (108 feat) — all 8 trials failed: `indicators not found at any timeframe: [align_5, align_15, align_1440]` (no columns generated).
- `466423b1…` (105 feat) — all 8 trials failed: `no usable rows after dropping NaN` (`15/60/240_vol_regime`, `15_align_60`, `60_align_240` entirely NaN).
- `cef7e106…` (102 feat) — the buildable v1: zero all-NaN columns, 100% of rows survive.
