# candle_reach_sizing_stop — the volatility index (ATR1 level, candle reach) as a stop-width and position-size rule

Date: 2026-10-21. Status: **done — negative** (see [results](results/candle_reach_sizing_stop_results.md)). Chains off [candle_reach_gate](candle_reach_gate.md) (negative as an entry
gate; same features, same harnesses). Read-only replay, no code-repo branch; docs on external `cross-tf-veto-replay`.

# Goal

User (2026-10-21): "test sizing / stop use" of the index. Decide whether scaling the candle stop's offset or the
position size by the volatility index at the fire raises the net of the CB zone system (2y frozen → oos2m → paper)
against risk-matched controls. The entry set is unchanged (no skips): a sizing rule only re-weights the same trades,
a stop rule changes each trade's stop distance, size (100 / distance) and outcome.

# Quantities (as candle_reach_gate; closed information only)

ATR1 = `1_atr_14_ma_5`; atr1_rel = ATR1 / median ATR1 over 1440 rows; atr1_pct = ATR1 / close × 100; fc8c_T = median
reach (range / ATR1) of the last 8 closed T-candles; rel_T = fc8c_T / √T; rem = fc8c × (1 − progress)^0.5; D = target
distance / ATR1; ratio = rem / D. Live stop offset `off` = trailing-60 mean 1-min range (≈ ATR1), anchor = forming
15-min extreme (all tfs); live size = min(100 / stop distance, notional cap).

# Families

Stop (offset multiplier m on `off`; the anchor unchanged):

| key | m |
|---|---|
| st_rel_b{β} | rel_15^β, β ∈ {0.5, 1, 2} — wider when recent candles are wider than random walk |
| st_arel_b{β} | atr1_rel^β, β ∈ {−1, −0.5, 0.5, 1} — β < 0: the stop in 24-h-median-ATR units (tighter in high vol); β > 0: doubly scaled |
| st_fc_g{g} | offset = g × fc8c_15 × ATR1 (a fraction of the expected 15-min candle reach), g ∈ {0.15, 0.25, 0.4} |
| st_reg_{hi}_{lo} | m = hi if atr1_rel > 1.3, lo if atr1_rel < 0.8, else 1; (hi, lo) ∈ {(1.5, 0.75), (0.75, 1.5), (2, 1), (1, 2)} |
| controls | st_sh (frozen rule on 1440-row-shifted features), st_rand (frozen rule's multipliers shuffled, 3 seeds) |

Size (multiplier s on the live size, normalised to mean 1 over the 2y e25 entries; the normalising constant is
frozen and applied unchanged to oos2m / paper, so the total risk budget is matched):

| key | s ∝ |
|---|---|
| sz_arel_g{γ} | atr1_rel^γ, γ ∈ {−1, −0.5, 0.5, 1} (γ < 0 = smaller in high vol, the gate experiment's lead) |
| sz_apct_g{γ} | atr1_pct^γ, same γ |
| sz_rel_g{γ} | rel_15^γ, γ ∈ {−1, 1} |
| sz_ratio_g{γ} | ratio^γ, γ ∈ {−0.5, 0.5} (2y lead: low ratio better) |
| sz_reg_{lo}_{hi} | s = lo below atr1_rel 0.8, hi above 1.3, 1 between; (lo, hi) ∈ {(1.5, 0.5), (0.5, 1.5)} |
| controls | sz_sh (shifted features), sz_rand (multipliers shuffled, 3 seeds) |

# Steps

1. 2y: simulate the e25 entries (first passing minute per candle, as the gate stand-in) once per stop variant;
   sizing variants re-weight the live-stop run. Paired Δ vs live by candle, CI90, months+, net per unit risk
   (Σpnl / Σ size × distance). Freeze the best stop and the best size variant (one each), their placebos.
2. oos2m: score the frozen variants once (grid printed post hoc).
3. Paper replay (volume-flow harness + `stop_rule` / `size_rule` knobs at the fire): live, frozen, controls,
   random band; full window + candle era; fee sensitivity.
4. Results + register.

# Pass criterion

Frozen stop or size rule: Δ > 0 with CI90 excluding 0 on 2y, same sign on oos2m and paper, above its shifted and
shuffled controls on each tier; else partial / negative.

# Locked decisions (2026-10-21, author — the user asked for the test, details unasked)

| # | question | decision |
|---|---|---|
| 1 | hold-time / exit rules from the index | not in scope (sizing + stop only, as asked); noted as a follow-up |
| 2 | sizing normalisation | mean multiplier = 1 over the 2y entries, constant frozen per family |
| 3 | selection | best paired Δ over all cells on 2y, one per family, controls on the frozen only |
| 4 | stop anchor | unchanged (forming 15-min extreme); only the offset scales |
| 5 | fc for the stop | the 15-min reach for every tf (the anchor is the 15-min candle) |
