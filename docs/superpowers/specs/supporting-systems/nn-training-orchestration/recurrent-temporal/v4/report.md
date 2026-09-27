---
archetype: recurrent-temporal
version: 4
parent: v3
spec_hash: dc8bb242de29e1d9de8ad1f16af1e689aa581144cdf2fc79cd6849fbfad5bc90
hypothesis: Add a sequence-preserving conv1d front (conv1d_seq -> lstm -> dense) to
  capture local entry micro-structure before the LSTM models trend across history. Does
  it strengthen the v3 binary long-entry signal (1.40x lift)?
holdout_acc: 0.7042
holdout_loss: null
per_class:
  long_entry_base_rate: 0.0579
  precision_thr0.5: 0.0998
  precision_thr0.6: 0.1050
  precision_thr0.7: 0.1087
  recall_thr0.5: 0.512
  recall_thr0.7: 0.354
  lift_thr0.7: 1.88
decision: promote
strike: 0
next_hypothesis: Architecture now confirmed to carry signal. The next lever is FEATURES
  (v5) — add entry-relevant inputs the current 14 stationary indicators lack: support/
  resistance distance (ZB/ZS/tgt_long/sl_long exist in the df), volume imbalance
  (buy vs sell vol), and optionally 1m/5m microstructure for entry timing. Keep the
  conv1d_seq->lstm->dense architecture + binary long target fixed; change only the
  feature set so the comparison is clean.
---

# recurrent-temporal v4 — report

## Change from v3
Architecture only: prepended a `conv1d_seq(32, kernel 3)` (new engine kind — conv over
time that PRESERVES the sequence) before the LSTM → `conv1d_seq(32) -> lstm(64) ->
dense(32)`. Same 14 features, binary long target, epochs 50 / batch 256. Tests whether
local pattern extraction helps.

## Result (holdout = 201,581 rows, positive base rate 5.79%)
| threshold | precision | recall | lift vs base | (v3 precision / lift) |
|---|---|---|---|---|
| 0.5 | 0.0998 | 0.512 | 1.72× | 0.0748 / 1.29× |
| 0.6 | 0.1050 | 0.445 | 1.81× | 0.0778 / 1.34× |
| 0.7 | 0.1087 | 0.354 | 1.88× | 0.0813 / 1.40× |
Best trial: holdout binary accuracy 0.7042 (vs v3 0.6283).

## Verdict — clear improvement
The conv front lifts BOTH precision and recall at every threshold. At thr 0.7, precision
0.081→0.109 (lift 1.40×→1.88×) and recall 0.224→0.354. The model now flags ~11% true
long entries among its confident calls vs the 5.8% base — a near-doubling of edge.
Local entry micro-structure (conv) + trend context (LSTM) compound.

## Decision
`decide`: promote (+0.0759 ≥ margin, same binary metric as v3 so directly comparable),
new best, strike 0. v4 is the new archetype base. Lineage continues to v5.

## Lineage so far
| ver | change | long-precision @0.7 | lift | decision |
|---|---|---|---|---|
| v1 | 3-class dir, epochs 12 | ≈ base | 1.0× | promote (baseline) |
| v2 | epochs 50 | ≈ base | 1.0× | revert (undertraining ruled out) |
| v3 | binary long-only | 0.081 | 1.40× | promote (signal found) |
| v4 | + conv1d_seq front | 0.109 | 1.88× | promote (signal strengthened) |
