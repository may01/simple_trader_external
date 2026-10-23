# half_atr_stop — CB zone stop = forming 15-min high/low ∓ 0.5 × ATR(1 min)

Date: 2026-10-21. Status: **done — negative** (see [results](results/half_atr_stop_results.md)).

## Hypothesis

Reducing the CB zone stop from the live rule (forming 15-min extreme ∓ 1.0 × trailing-60 mean 1-min range) to
forming 15-min high/low ∓ 0.5 × ATR(1 min) (`1_atr_14_ma_5`) improves the paper run's net.

## Locked decisions (2026-10-21, assumptions — the user was not available for clarification)

| # | question | decision |
|---|---|---|
| 1 | "High/Low" = which candle | the forming 15-min candle's extreme, as in the live rule; the forming 1-min bar and the bare fire price run as ablations |
| 2 | ATR(1 min) source | `1_atr_14_ma_5` rebuilt from the trades (the executor DB stores no ATR); Wilder 14 on closed 1-min bars incl. the gap to the previous close, SMA-5, last closed bar |
| 3 | sizing | live rule (100 / stop distance, notional cap); a `size_live` ablation sizes with the live distance to isolate placement |
| 4 | data | paper `cbov-check` DB, CB-armed history 10-18 11:41Z → 10-21 17:20Z (77.6 h) + the candle-stop era (20.9 h); no 2y / oos2m stand-in |
| 5 | base branch / code | none — read-only replay, script in `executor/runs/`, nothing in the code repo |

## Method

Fire-re-deriving replay (`executor/runs/2026-10-21-half-atr-stop-replay.py`, the stop-reentry harness with the stop
offset as a knob); variants = offset sweep 0.25 … 2.5 × ATR1 and 0.5 / 0.75 × mean range, three anchors, three sizing
ablations; paired 6-h block bootstrap vs live, fee sensitivity 0.02 / 0.05 / 0.1 %/side.

## Validity gates

| gate | number |
|---|---|
| reproduction | 200/207 recorded fires matched, 54/55 candle-era stops within half a tick, era net +438 recorded vs +411 simulated |
| null floor | atr10 (live offset unit changed by 1.6 %) Δ +292 full / −26 era — one-tick stop moves flip ~300 of net |
| base rate / sizing | `size_live` ablation: atr05 +348 → +20 full, +266 → +186 era |
| degeneracy | sweep non-monotone around live (0.25 +593, 0.5 +348, 0.75 +875, 1.5 +523, 2.0 +590, 2.5 +349) |
| look-ahead | ATR1 and the mean range from closed bars only; the stop is fixed at the fire trade; the anchor uses trades ≤ the fire |
| provenance | no fitted parameters; all constants from the live executor (`a6a5bc6`) |
