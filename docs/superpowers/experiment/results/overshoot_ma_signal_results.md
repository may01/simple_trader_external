# overshoot_ma_signal — Results & Conclusion

**Date:** 2026-10-20 · **Spec:** `experiment/overshoot_ma_signal.md` · **Plan:** `plans/2026-10-20-overshoot-ma-signal-replay.md` · **Branch:** none (read-only replay over the paper executor's postgres)
**Data:** `cbov-check` paper stack, Binance LINKUSDT, the whole CB-armed history 2026-10-18 11:41Z → 2026-10-20 21:25Z (57.7 h, 450 031 trades, 152 recorded CbZoneEntry fires, 108 positions).
**Pipeline:** `external/executor/runs/2026-10-20-overshoot-ma-replay.py` (port of `CbZoneEntryCheck` + `signals::trend` run on every trade; today's candle stop, trend-flip exit, sizing), output `…-output.txt`, full run report `…-replay.md`.
**Final configuration:** live parameters throughout; the only change is the class source in overshoot-vetoed minutes (3-min = 18 buckets, 5-min = 30 buckets of 10 s, same 0.7 σ band).

## Headline conclusion

Taking the vetoed side on a 3-min or 5-min trade-price MA class adds 11 / 6 positions in 57.7 h, netting
−74 / −127 USDT; the system's net is unchanged within noise (+2 451 / +2 488 vs +2 489 with the veto).
Lifting the veto outright adds 19 positions netting −613 (P(net<0) 0.94). **Negative**: the veto removes
minutes, not zones (the once-per-zone rule re-fires on the next passing minute), and a slower MA agrees with
the 1-min class at the fire 11 of 12 times — it is not a second signal. Not proven: anything beyond one pair
and 2.4 days; fees (paper = none; at 0.05 %/side every mode is negative at this sizing).

## The progression

| mode | trades | net | PF | marginal trades | marginal net |
|---|---|---|---|---|---|
| current (veto) | 135 | +2 489 | 1.48 | — | — |
| no_veto | 142 | +1 986 | 1.35 | 19 | −613 |
| ma3 | 140 | +2 451 | 1.46 | 11 | −74 |
| ma5 | 139 | +2 488 | 1.46 | 6 | −127 |
| ma3_and / ma5_and | 140 / 139 | +2 451 / +2 482 | 1.46 | 11 / 6 | −74 / −133 |
| ma3_all / ma5_all (slower class everywhere) | 131 / 118 | +1 628 / +1 053 | 1.38 / 1.26 | 15 / 8 | +133 / +20 |

## Degeneracies found

None in the objective (nothing was fitted). One mechanism finding: the relaxation changes only 6–19 of ~140
trades because the veto flag flips within a zone and the live check fires on a passing minute of the same zone.

## Validity gates

| gate | number |
|---|---|
| reproduction (fires) | 145 / 152 recorded fires re-fired at the same trade (Δt median 0 s); 6 of 7 misses are first-fire-after-restart artefacts; slope port 99 % within 10 % of `ma_slope` |
| null floor | marginal CIs: no_veto [−1 228, +30], ma3 [−597, +473], ma5 [−473, +220]; whole-mode CIs overlap entirely |
| base rate | marginal stop-out share 63 % (no_veto) / 45 % / 50 % vs 46 % non-marginal; every marginal stop is −1 R |
| ablation | ma3_and ≡ ma3 (longer class = 1-min class at 11/12 vetoed fires); ma5_and = ma5 − 1 fire |
| truth ladder | slower class everywhere: +1 628 / +1 053 vs +2 489 — the slower MA is a worse entry class, not a better one |
| look-ahead | by construction (indicator `received_at ≤ trade`, bars/anchors/classes end at the trade) |
| provenance | every parameter is the live one; the two MA windows are the user's; no selection on the window |
| reproduction of the arithmetic | current-mode stop/anchor/offset formulas = `cb_stop::compute_candle_stop`; split halves +797/+1 692 (current) vs +731/+1 720 (ma3) |

## What generalized vs what did not

- Held: the overshoot veto's incremental value is positive on this sample (+503 vs no veto); the once-per-zone rule makes the veto cheap (19 lost fires in 2.4 days).
- Did not: a slower trade-MA class as the entry signal — neither in vetoed minutes nor everywhere.

## Config & artifacts

Script, output and run report under `external/executor/runs/2026-10-20-overshoot-ma-replay*`; exports are
regenerated from the DB with the SQL in the script header (not stored in the repo). No code repo touched;
nothing to commit there. REPORT.md row: negative, no branch.

## Next arbiter

The same replay once the trade store covers several weeks (≈ 8 marginal trades per day accrue), or the
overshoot *depth* (`cb_overshoot_*` float, stored, not broadcast) as a stop/size conditioner instead of a
binary veto.
