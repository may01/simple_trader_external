# stop_reentry_pairs — results (2026-10-21)

Spec: [`../stop_reentry_pairs.md`](../stop_reentry_pairs.md). Run report with every table, variant definition and gate:
[`executor/runs/2026-10-21-stop-reentry-replay.md`](../../../../executor/runs/2026-10-21-stop-reentry-replay.md).
Verdict: **partial** — the pattern is real and is the main loss channel; one fix (wider candle stop) is supported in
direction on both windows, nothing is decision-grade on 71.6 h.

## How often, what it costs

| data | stop-outs | pairs W15 | share | P1 loss | P2 pnl | P2 stopped again |
|---|---|---|---|---|---|---|
| recorded paper, both stop eras (114 closed) | 71 | 13 | 18 % | −352 | +487 | 7/13 |
| recorded, candle-stop era (38 closed) | 22 | 4 | 18 % | −273 | +312 | 1/4 |
| simulated live rule, uniform candle stop, 71.6 h (171) | 82 | 35 | 43 % | −2 795 | +226 | 17/35 |
| same, W 60 | 82 | 49 | 60 % | −3 966 | +606 | 24/49 |

Under the running stop every second stop-out starts such a pair; the first legs are 43 % of all stop-loss money
(−6 560); the second legs open a median 1.9 min later, 1.2 P1-stop-distances better, 23/35 beyond P1's stop, and
recover little because half of them stop again.

## Mechanism

The fire lands on a fresh extreme, the candle stop anchors on that extreme (41/42 era fires: rolling 15-min extreme =
forming-candle extreme), so the stop is 1.8–2.1 mean 1-min ranges from the entry while the zone's entry-side `cbnc`
bound is 2–4 stops away. The zone value is rebroadcast every minute, so once-per-zone never blocks the second fire
(0/19 recorded pairs share the zone value); P2 arrives via rule 2 or the 60/240 zone.

## Fixes tested (Δ vs live, paired 6-h blocks; full 71.6 h / candle era 14.9 h)

| proposal | full Δ (P(Δ<0)) | era Δ (P) | verdict |
|---|---|---|---|
| 1. stop offset × 2 / × 2.5 | +605 (0.21) / +636 (0.11); stop-outs 82 → 54 / 43, PF 1.38 → 1.58 / 1.71 | +363 (0.00, 3 blocks) | supported in direction; plateau 1.5–2.5, × 3 −163 |
| 2. stop at entry-side `cbnc` bound ∓ offset (zs / zsw / zsw × 1.5) | +151 / +206 / −52 | −54 / −76 / +115 | neutral; not better than 1 |
| 3. cooldown 5 / 15 / 30 min | +78 / −77 / −737 | −348 (0.97) / −473 (0.96) / −162 | dead — removes the P2 legs, which are the positive ones |
| 4. enter 0.5 / 1.0 ranges deeper | −334 / −1 819 (0.90); trades 171 → 71 / 41 | +158 / +128 | unsupported |
| 5. half size first leg, full re-entry | −936 (0.99) | +7 | dead; skip first 3/5 min −614 / −17, anchor variants no-op |

Gates: 184/191 fires and 39/40 stops reproduced; sm sweep not a boundary optimum; no fitting; paper = no fees
(at 0.1 %/side everything is negative, wider stops least).

## Disposition

No branch. Scripts + outputs in `executor/runs/2026-10-21-stop-reentry-*`; DB exports archived on
`simple_trader_vol_long:/train/replays/stop-reentry-replay-data-2026-10-21.tgz`. Candidate executor change: a
`CB_STOP_RANGE_MULT` knob in `cb_stop` (default 1.0, try 2.0), then replay the next era against `sm20`.
