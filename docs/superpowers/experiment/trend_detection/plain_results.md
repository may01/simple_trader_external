# Trend Detection — Plain-Truth (non-strict labels) Run

**Date:** 2026-07-23 · **Branch:** `trend-detection-experiment` (worktree, uncommitted)
**Truth:** plain n1 pair (`plong_n1`/`pshort_n1`) — race + pessimistic entry fill, **no clean-entry gate**. Long-class = `plong==1 & pshort==0`, short-class inverse; both/neither excluded.
**Pipeline:** same improvement loop as the strict run, `truth_kind="plain"` (new `tdlib.loop` parameter; schedule drops `horizon_n2` — plain pair is n1-only) + `feature_set="noshape"` variant (`diag_feature_cols`). Artifacts under `.../trend_detection/{plain,plain_noshape}/`, strict artifacts untouched. 229 tests GREEN in docker (6 new).
**Drivers:** `run_loop_plain.py` / `run_loop_plain_noshape.py` (2y) · `run_oos_plain.py` / `run_oos_plain_noshape.py` (oos2m, frozen bundles, zero refit; sym0 crosscheck 1.0000 on 15/60/240).

## Headline

**Removing the clean-entry gate removes ~all of the separation the strict run showed.** Strict 0.94–0.97 test AUC → plain 0.55–0.58 at tf15, ≤ chance at tf60. What remains at tf15 **does transfer OOS** (15_up 0.60, 15_dn 0.54, both verdict *holds* with positive both-side lifts) — but the diagnostic decomposition (alt_truth: plain_noshape ≈ 0.51) says most of this remainder is **entry-fill mechanics read off candle shape**, not future price information. Consistency check: iter_01 baseline AUCs reproduce alt_truth's plain_full cells exactly (0.5588/0.5809/0.4768/0.4774).

## Point counts (2y, usable long/short after both/neither exclusion)

| combo | n_long | n_short | note |
|---|---|---|---|
| 15_up | 1,894 | 1,718 | ~3.6k usable vs 236 under strict — gate was the binding constraint |
| 15_dn | 1,828 | 2,075 | |
| 60_up | 360 | 247 | |
| 60_dn | 261 | 340 | |
| 240_up | 52 | 37 | scoreable at last (strict n1 starved tf240 entirely) |
| 240_dn | 27 | 52 | |

## Improvement loop (2y)

| iter | transform | mean test AUC | status |
|---|---|---|---|
| 01 | baseline | 0.5577 | kept |
| 02 | prune_top40 | **0.5740** | **kept — best** |
| 03 | interact_time_left | 0.5565 | rejected |

Best-iteration gbc test AUC per combo: 15_up 0.5646 · 15_dn 0.5543 · 60_up 0.4812 · 60_dn 0.4688 · 240_up 0.5824 (n=27 test) · 240_dn 0.7926 (n=24 test — noise, dominates the 0.574 mean; ignore).

## OOS (oos2m, frozen, zero refit)

| combo | test gbc AUC | oos gbc AUC | oos n | verdict |
|---|---|---|---|---|
| 15_up | 0.5646 | **0.5997** | 309 | **holds** (lift_long +0.21, lift_short +0.18) |
| 15_dn | 0.5543 | 0.5416 | 301 | **holds** (lift_long +0.05, lift_short +0.08) |
| 60_up | 0.4812 | 0.4955 | 43 | fails (lift sign flips) |
| 60_dn | 0.4688 | 0.5890 | 54 | fails (lift sign flips) |
| 240_up/dn | — | — | 8/5 | skipped (< 30 points) |

## Top importance (best iter, tf15)

- **15_up:** `5_wick_up` (#1 — entry-fill fingerprint), `15_sin_tod`, `60_adx_14`, `1440_body_ratio`, `need_speed_dn_60`, `60_range_atr`, `15_cci_diff`.
- **15_dn:** `15_close_diff_prc_rm_6_std_above`, `60_natr_14`, `5_range_atr`, `60_rsi_ma8_diff`, `swing_dist_lo_15_50` (engineered levels proxy, #5), `5_wick_dn`.

Volatility/shape features dominate — consistent with the label's remaining mechanics (pessimistic fill inside candle k). Time-of-day (`15_sin_tod`) ranking #2 on 15_up is the one genuinely new signal candidate not present in the strict run's top ranks.

## Read

1. Plain truth is the honest ceiling for "which side wins the race from here": **~0.55–0.60 AUC at tf15, nothing at tf60, unresolved at tf240** (2y trainable now, OOS window too short).
2. The strict run's 0.94–0.97 was gate reconstruction (confirmed again, now with the full loop, not just the decomposition baseline).
3. 15_up OOS 0.60 with +0.21/+0.18 both-side lifts is the best plain cell, but n=309 (±~0.03–0.05 CI) and shape-feature-driven — treat as "mechanics + modest signal", not an edge until a noshape plain loop or second symbol confirms.

## Noshape run (follow-up #1 — EXECUTED 2026-07-23, same day)

Full plain loop + OOS rerun on the **shape-excluded** feature set (`feature_set="noshape"`, `diag_feature_cols`; engineered features kept). Artifacts under `.../trend_detection/plain_noshape/`. Iter 01 baseline reproduces alt_truth's plain_noshape cells exactly (0.5119/0.5075/0.4842/0.4740). Best = iter 01 (pruning did not help past eps).

| combo | test gbc AUC | oos gbc AUC | oos verdict |
|---|---|---|---|
| 15_up | 0.5119 | 0.5230 | **fails** (lift_short sign flips) |
| 15_dn | 0.5075 | 0.4969 | **fails** (AUC < 0.5) |
| 60_up/dn | 0.47–0.48 | 0.43/0.54 | fails |
| 240_up/dn | 0.59/0.79 (n=24–27) | — | skipped (n=5–8) |

**Verdict: once candle-shape columns are removed, plain-truth separation is gone — every combo fails OOS.** Top noshape importance (15_up: `5_rsi_ma8_diff`, `5_bb_upper_20_2_minus_close`, `240_adx_14`) carries no OOS-stable signal under plain truth. This closes the question the full-featured plain run left open: its tf15 OOS "holds" (0.60/0.54) was **entry-fill mechanics read off candle shape**, not future price information — consistent with, and now stronger than, the alt_truth decomposition (full loop + pruning + frozen OOS, not just a single baseline).

Combined ladder (15_up gbc test): strict 0.94 → plain full 0.56 → plain noshape 0.51 → fwd ~0.51. Every step of the strict AUC is now accounted for by label mechanics.

## Follow-ups

- ~~Plain loop on the noshape feature set~~ **DONE — see above. Non-mechanics remainder ≈ zero.**
- Longer OOS window to resolve tf240 plain (needs ≥30 usable points) — low priority given noshape verdict.
- `15_sin_tod` (time-of-day) — still in noshape top ranks (#6) but nothing OOS-stable behind it under plain truth; only worth revisiting inside the strict-gate framing.
- Remaining live signal from this whole experiment = the strict-side fwd-truth features (`bb_dist_up_{15,240}`, `swing_dist_hi_15_50`, deep 5m oversold on strong-down) — see `results.md` next-steps #2.

## Artifacts

- 2y: `/trader_data_long/train/2y_link_usdt/trend_detection/plain/{iter_01..03,summary.md,best.json}`
- oos2m: `/trader_data_long/train/oos2m_link_usdt/trend_detection/plain/{oos_report.md,oos_table.csv}`
- Code: `tdlib/loop.py` (`truth_kind`), `tdlib/oos.py` (`truth_kind`), `run_loop_plain.py`, `run_oos_plain.py` — branch `trend-detection-experiment`, uncommitted.
