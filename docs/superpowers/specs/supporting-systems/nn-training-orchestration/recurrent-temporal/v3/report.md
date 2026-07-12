---
archetype: recurrent-temporal
version: 3
parent: v2
spec_hash: 821b70b2704dbfabba7a0156c8792a03b89c4fcccc7459059ededbd6803f1fb0
hypothesis: Reframe the target — single binary strict LONG label (good long entry yes/no)
  instead of 3-class up/neutral/down. Does a focused target surface signal the 3-class
  framing diluted? Same LSTM(64)->dense(32), 14 features, epochs 50 / batch 256.
holdout_acc: 0.6283
holdout_loss: null
per_class:
  long_entry_base_rate: 0.0579
  precision_thr0.5: 0.0748
  precision_thr0.6: 0.0778
  precision_thr0.7: 0.0813
  recall_thr0.5: 0.477
  recall_thr0.7: 0.224
  lift_thr0.7: 1.40
decision: promote
strike: 0
next_hypothesis: Strengthen the weak signal. Most promising structural moves — (a) add a
  conv1d front (conv->lstm) to capture local entry micro-structure before the LSTM models
  trend; (b) enrich features (price-action / support-resistance distance / volume
  imbalance); (c) focal loss for the rare positive. Pick ONE per version.
---

# recurrent-temporal v3 — report

## Change from v2
Target only: 3-class direction `dir15s` → binary `label` `long15s` on the strict 15m long
entry (`15_pslong_n1_m1_x0p3_l15_y0p2`). Architecture, features, history, epochs
unchanged. Sole purpose: test whether the 3-class framing was diluting a directional
signal.

## Result (holdout = 201,581 rows, positive base rate 5.79%)
| threshold | pred % | precision | recall | lift vs base |
|---|---|---|---|---|
| 0.5 | 36.9% | 0.0748 | 0.477 | 1.29× |
| 0.6 | 26.4% | 0.0778 | 0.354 | 1.34× |
| 0.7 | 16.0% | 0.0813 | 0.224 | 1.40× |

## Verdict — first real signal
v1/v2 (3-class) sat exactly at base rate (precision ≈ 0.058 = up base rate). v3 (binary
long) lifts long-entry precision to **1.3–1.4× base**, and **lift increases monotonically
with confidence threshold** — the model ranks entries better than chance. The signal is
weak but unmistakable and was hidden by the 3-class framing.

NOTE on the gate metric: v3's `holdout_score` (0.6283) is binary accuracy and is NOT
comparable to v1/v2's 3-class accuracy (0.45 / 0.386) — different metrics. The promotion
was adjudicated on the lift analysis (signal vs no signal), not the raw scalar; the
`decide` gate happens to agree (0.6283 ≥ 0.45 + margin → promote, strikes reset).

## Trading relevance
The strict label encodes a favorable R:R (target m=1 ATR vs stop x=0.3 ATR). An entry
filter that raises hit-rate from 5.8% to ~8.1% on its most-confident calls can be
economically meaningful even at this modest lift — but P&L confirmation is deferred to the
model-combination / signal-identification phase (ADR-0002).

## Decision
`decide`: promote (+0.1784 ≥ margin), new best, strikes reset to 0. v3 (binary long-only)
is the new archetype base. Lineage continues to v4 to strengthen the signal.
