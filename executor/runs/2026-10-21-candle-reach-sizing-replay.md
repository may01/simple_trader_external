# Volatility index as stop-offset and size multiplier — paper-run replay + 2y / oos2m stand-in

Date: 2026-10-21. Question (user): test the sizing / stop use of the candle-reach volatility index (after the entry
gate died). Spec `docs/superpowers/experiment/candle_reach_sizing_stop.md`, results
`docs/superpowers/experiment/results/candle_reach_sizing_stop_results.md`.

Scripts: [`2026-10-21-candle-reach-sizing-replay.py`](2026-10-21-candle-reach-sizing-replay.py) (= the candle-reach
harness + `stop_rule` / `size_rule` knobs at the fire; multipliers from atr1_rel / atr1_pct / rel_15 / fc8c_15 / ratio;
rand controls draw multipliers from the live fires' pool; `--norm` carries the 2y normalisation constants), outputs
[`…-output-full.txt`](2026-10-21-candle-reach-sizing-replay-output-full.txt) (78.4 h, 64 variants) and
[`…-output-candle-era.txt`](2026-10-21-candle-reach-sizing-replay-output-candle-era.txt). Stand-in:
[`2026-10-21-candle-reach-sizing-2y-oos2m.py`](2026-10-21-candle-reach-sizing-2y-oos2m.py) (imports the gate stand-in,
simulates the e25 entry set per stop variant, re-weights for size variants), output
[`…-2y-oos2m-output-h60.txt`](2026-10-21-candle-reach-sizing-2y-oos2m-output-h60.txt) (173 s).

Status: **negative** — frozen stop rule `st_reg_2.0_1.0` 2y +7 910 (P 0.21) / oos2m −2 858 / paper +1; frozen size rule
`sz_apct_g0.5` 2y +2 284 (P 0.38) / oos2m +7 545 (P 0.01, placebo +5 080) / paper +36 inside the shuffle band. Only
constant stop widening moves paper (+849, P 0.08), as the stop-reentry replay already showed.

Gates: reproduction 200/207 fires, 54/55 stops (era 56/58); shuffled-multiplier and constant-multiplier controls per
frozen rule; size multipliers risk-matched (mean 1 on 2y).
