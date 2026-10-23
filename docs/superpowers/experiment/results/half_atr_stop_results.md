# half_atr_stop — results (2026-10-21)

Spec: [half_atr_stop.md](../half_atr_stop.md). Run report with every table:
[executor/runs/2026-10-21-half-atr-stop-replay.md](../../../../executor/runs/2026-10-21-half-atr-stop-replay.md).

**Verdict: negative.** Stop = forming 15-min high/low ∓ 0.5 × ATR1 instead of ∓ 1.0 × mean 1-min range:

| window | live net | 0.5 × ATR1 net | Δ (paired 6-h blocks) | 90 % CI | P(Δ<0) | placement only (live sizing) |
|---|---|---|---|---|---|---|
| 77.6 h, 186 positions | +2 679 | +3 027 | +348 | [−516, +1 193] | 0.25 | +20 |
| candle-stop era 20.9 h, 53 | +411 | +677 | +266 | [−93, +645] | 0.14 | +186 |

- ATR1 ≈ the live offset unit (ratio median 1.016), so the change is "live offset × 0.5": stop 16.7 → 12.4 bp,
  stop-outs 87 → 102 (mean −81 → −64), targets 70 → 63, position at the notional cap 67 → 81 %.
- The +300 is the risk-per-trade sizing making the position bigger, not the placement (`size_live` ablation).
- Noise floor on this sample ≈ ±300: swapping the offset unit alone (atr10) moves net +292.
- Offset sweep 0.25 … 2.5 × ATR1 non-monotone with live in a local minimum (+593 / +348 / +875 / live / +523 /
  +590 / +349) — an overfit sweep, not a better offset; the earlier ×2–2.5 proposal is now P 0.22 / 0.31.
- Anchor on the 1-min bar / the fire price (7.5 / 4.2 bp stops): +853 (P 0.06) / +143 full, +829 / +1 009 era
  (P 0.00 on 4 blocks), carried by 10-21; fire anchor loses on 10-18 / 10-19. In-sample lead, scalp regime,
  fee-heaviest. Needs 2y / oos2m + real fees before reading.
- At 0.02 %/side every 15-min-anchored variant is negative on both windows (live −767 / −577, 0.5 × ATR1 −654 / −350).

Disposition: keep the live offset; no branch, nothing in the code repo.
