# Candle-reach entry gate — paper-run replay + 2y / oos2m stand-in

Date: 2026-10-21. Question (user): a per-tf volatility index = how much price moves inside the candle in 1-min ATRs,
used first as an entry gate (skip the CB zone fire when the forecast remaining reach of the candle cannot cover the
target distance). Spec `docs/superpowers/experiment/candle_reach_gate.md`, results
`docs/superpowers/experiment/results/candle_reach_gate_results.md`.

Scripts: [`2026-10-21-candle-reach-replay.py`](2026-10-21-candle-reach-replay.py) (= the volume-flow harness with the
reach features and the same skip knob; data export as the volume-flow run, `data/` with trades.csv (qty + side),
events.jsonl, positions.jsonl, indicators.csv), outputs [`…-output-full.txt`](2026-10-21-candle-reach-replay-output-full.txt)
(78.4 h, 15 blocks, 180 variants) and [`…-output-candle-era.txt`](2026-10-21-candle-reach-replay-output-candle-era.txt)
(`--t0=1792527900000`, 5 blocks). Stand-in: [`2026-10-21-candle-reach-2y-oos2m.py`](2026-10-21-candle-reach-2y-oos2m.py),
output [`…-2y-oos2m-output-h60.txt`](2026-10-21-candle-reach-2y-oos2m-output-h60.txt) (606 s, RSS 1.5 GB).

Status: **negative on all tiers** — see the results md for the tables. One-line: the ATR1-normalised candle range is
white noise around √tf (lag-1 autocorrelation ≤ 0.2), the gate collapses to progress × target distance (the `rw`
control reproduces it), and that gate skips the better entries on 2y (−14 709 frozen, P 0.95), is noise on oos2m
(+761) and inside the random-skip band on paper (+270 vs rand10 max +176; placebo +180; rw +517).

Gates: reproduction 200/207 fires, 54/55 candle stops; ATR1 rebuilt from trades median 0.0095 (0.078 % of price);
paper candles 450 / 116 / 30 (tf 15 / 60 / 240), reach median / √tf 1.15 / 1.27 / 1.37, lag-1 autocorr +0.11 / +0.22 / +0.12.
