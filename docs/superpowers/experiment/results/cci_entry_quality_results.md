# cci_entry_quality — results (2026-10-21, paper-run mapping only)

Spec: [`../cci_entry_quality.md`](../cci_entry_quality.md) · run report
[`executor/runs/2026-10-21-cci-entry-quality.md`](../../../../executor/runs/2026-10-21-cci-entry-quality.md).
Verdict so far: **inconclusive on the paper run (71.6 h, 171 positions)**; the 2y / oos2m test is designed in the spec
and plan, not run.

| finding | number |
|---|---|
| CCI mapped onto the executor | recomputed from the trade feed with main/'s convention, reproduced vs the 2y frame to 5e-11 |
| shape of the relation | U: adv15 ∈ [0, 100) stop 40 %, net +1 908 (n 55); ≥ 140 stop 60–67 %, net −33 (n 18); [−140, −100) stop 62 %, −161 (n 16); ≤ −140 stop 67 %, −47 (n 6) |
| strength | AUC(adv → stop) 0.49 (15 m) / 0.51 (5 m); corr(adv, pnl) −0.01 / −0.02; permutation P 0.18 / 0.11 for the ≥ 140 lift |
| recorded positions (95) | same shape: ≥ 140 stop 80 % (n 10), [0, 100) 50 % (n 34) |
| skip at adv ≥ 140 | +133 (cci15) / +359 (cci5) full, P(Δ<0) 0.41 / 0.32; era +436 / +113 |
| wait for a better price (limit δ·range, 15 min) | −483 / −348 / +67 full at δ 0.5 / 1 / 2 (cci15 ≥ 140); every-fire control −2 448 (P 0.99), win rate 26 % |
| in-sample best-bin band | −874 full (selection breaks the reversal chain) |
| band adv ∈ [−140, 140) | cci5 +367 (P 0.32), cci15 +179 (0.40), both −53; PF 1.38 → 1.59 / 1.50; era +113 / +436 (0.04, 3 blocks); cci5 band helps longs (+467 → +897), cci15 band shorts (+2 036 → +2 165) |

| band grid 5 m × 15 m | solo beats combined: adv5 ±140 +367 full / +113 era, adv15 ±100 +285 / +604; adv15 ±140 ∧ adv5 ±100 −159 / −161; ±200 no-op |
| random-skip control | 15 % −324 ± 491, 30 % −686 ± 733 (full); solo bands ≈ 1.3–1.4 sd above random at equal counts, fee-adjusted too |
| delayed entry after the CCI reverses (hold until adv < 100 / 0, W 15 / 30) | ≈ skip: cci5 +301…+329 full (20–24 fills of 40, the fills net ≈ −30), cci15 0–3 fills ≡ skip; decision = enter inside ±140, decline beyond, never a price-limit delay ≤ 1 range |
| long run | not callable on 4 days / 171 trades; adv15 ±100's edge = last 1.5 days; candidate for the 2y plan |

Disposition: no branch; scripts + outputs in `executor/runs/2026-10-21-cci-entry-quality-*`, `cci_lib.py`, and the
`cci*` variants of `2026-10-21-stop-reentry-replay.py`. Next = the plan's task 1 (loader + CCI gate on 2y).
