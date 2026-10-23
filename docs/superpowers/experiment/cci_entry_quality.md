# cci_entry_quality — does the 5-/15-min CCI at a CB zone fire predict entry success?

**Date:** 2026-10-21 · **Status:** paper-run mapping done (weak / inconclusive); 2y test designed, not run · **Branch:** none yet
**Run report:** [`executor/runs/2026-10-21-cci-entry-quality.md`](../../../executor/runs/2026-10-21-cci-entry-quality.md) · **Results:** [`results/cci_entry_quality_results.md`](results/cci_entry_quality_results.md) · **2y plan:** [`../plans/2026-10-21-cci-entry-quality-2y-test.md`](../plans/2026-10-21-cci-entry-quality-2y-test.md)

## Hypothesis

User: "if CCI > 140 then we will need to enter on the better price". H1: the CCI-14 on the 5- and/or 15-min candle at
the moment of a CB zone fire, signed into the trade's direction (`adv` = CCI for shorts, −CCI for longs: momentum the
trade fades), predicts (a) the stop-out probability and (b) how much better an entry becomes available within the
next minutes, such that above a threshold X the executor should either wait (limit δ deeper) or skip. H0: `adv` is
unrelated to the outcome beyond the stop mechanics, or related non-monotonically so that no threshold action beats
the plain rule.

## Locked decisions (author's calls)

| # | decision | choice | date |
|---|---|---|---|
| 1 | CCI definition | main/'s `cci_14` on the tf candles: last 104 closed + forming candle, talib CCI 14 (`build_indicator_input`, INDICATOR_WINDOW_ROWS 105); recomputed from the executor trade feed for the paper run (`cci_lib.py`), reproduced vs the 2y frame to 1e-11 | 2026-10-21 |
| 2 | signed value | `adv` = CCI × (+1 short, −1 long) | 2026-10-21 |
| 3 | paper-run data | the stop-re-entry replay (live rule, uniform candle stop, 71.6 h) + recorded positions; actions = skip at X ∈ {100, 140}, wait = limit at price ∓ δ·mean 1-min range for 15 min, δ ∈ {0.5, 1, 2}; controls = in-sample band, wait-all | 2026-10-21 |
| 4 | 2y test | tier-B stand-in (trend_ma_length harness) over `2y_link_usdt` parts + `df_with_candle_bounds{,_nc}`; fit X / δ on 2y by month-block bootstrap, freeze, score oos2m | 2026-10-21 |

## Outcome of the paper-run mapping (details in the run report)

U-shaped, not monotone: stop-out 40 % / net +1 908 in adv15 ∈ [0, 100) (n 55) vs 60–67 % / ≈ 0 at ≥ 140 (n 18) and
64 % / −208 below −100 (n 22). AUC(adv → stop) 0.49 / 0.51, permutation P 0.18 / 0.11 for the ≥ 140 stop-rate lift.
Skip at ≥ 140: +133 (cci15) / +359 (cci5) full window (P 0.41 / 0.32), +436 / +113 candle era. Wait-for-better-price:
−483 … +67 full, the every-fire control −2 448 (P 0.99) — the limit fills on the trades that keep going. Verdict on
71.6 h: **inconclusive, no action**; the 2y plan below is the arbiter.

## 2y test strategy (what the plan file executes)

1. **Data** (host-readable `…/simple_trader_vol_long/train`): 2y = `2y_link_usdt/df_with_indicators.part_00…24.pkl`
   column subset `1_high/low/close`, `5_cci_14`, `15_cci_14`, `{15,60,240}_close/is_closed`, concat; zones from
   `2y_link_usdt/df_with_candle_bounds.pkl` (`{tf}_cb_inzone_{side}`, `cb_low/high(_std)`) and
   `df_with_candle_bounds_nc.pkl` (`{tf}_cbnc_high/low`). oos2m = `oos2m_link_usdt/df_with_indicators.pkl` (all
   columns present, 2025-01 → 2025-03). Verified 2026-10-21.
2. **Entry stand-in** = `2026-10-21-trend-ma-length-2y-oos2m.py` tier B: candidate minute = inzone ∧ overshoot pass
   ∧ e25 trend flag ∧ 1-min momentum; first candidate per tf candle; stop = forming-15m extreme ∓ mean range of 60
   closed 1-min bars (0.2 % placeholder); target = `cbnc` far bound, exit at the target price; hold cap 60 min; size
   min(100/dist, 50 000/entry); no fees. Per entry record: `adv5`, `adv15`, outcome, pnl, R, MAE within 15 min in
   stop-distances, MAE before the stop, "target before stop", forward return at 15 / 60 min.
3. **Descriptive (2y):** per tf × side: stop rate, mean R, mean pnl by `adv` decile and by fixed bins
   (< −100, −100…0, 0…100, 100…140, 140…200, ≥ 200); Spearman(adv, R); AUC(adv → stop). Minimum 200 entries per
   cell. **Null floor:** permutation of `adv` within tf × side × calendar month (regime-matched). **Base rate:** the
   cell's unconditional stop rate. Report both CCIs and their closed-candle (shift = 1) versions — if only the forming
   CCI "works", it is the entry minute's own candle shape, not information.
4. **Truth ladder:** (strict) stand-in outcome with the candle stop → (plain) same with stop × 2 → (forward) raw
   15- and 60-min forward return into the trade's direction, no stop. A relation that dies on the way down is the
   stop mechanics (already known from `stop_reentry_pairs`), not a CCI signal.
5. **Actions, fit on 2y only:** skip at `adv ≥ X`, X ∈ {80, 100, 120, 140, 160, 200}; wait = limit at price ∓ δ·range
   for W ∈ {5, 15} min, δ ∈ {0.5, 1, 2}; both per CCI tf and for `adv5 ∧ adv15`. Objective = Δnet vs plain with a
   paired month-block bootstrap (24 blocks); pick the (X, δ, W) with the best lower CI bound, require n ≥ 100 affected
   entries. **Controls:** (i) random skip of the same count (does any thinning help?); (ii) wait-all (adverse-selection
   floor); (iii) the same grid on the shuffled `adv`. **Degeneracy:** the chosen X / δ must not sit on the grid edge.
6. **Score on oos2m once:** the frozen (X, δ, W); report Δnet, Δstop rate, fill rate, CI; provenance = the frozen
   JSON (2y stats + chosen params) crosschecked against the paper-run replay's variant definitions.
7. **Interaction:** rerun step 5's winner on top of stop × 2 (the `stop_reentry_pairs` candidate) — does CCI add
   anything once the stop is wider? Also correlate `adv` with `cb_f_trend` / the EMA-25 class to show it is not a
   proxy of the existing veto.
8. **Decision rule:** promote only if (a) 2y lower CI > 0 for the chosen action, (b) oos2m Δ > 0, (c) survives the
   random-skip control, (d) the forward-return rung of the ladder keeps the sign. Otherwise record dead with the
   numbers.
