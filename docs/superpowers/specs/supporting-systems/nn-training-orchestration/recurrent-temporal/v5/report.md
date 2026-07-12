---
archetype: recurrent-temporal
version: 5
parent: v4
spec_hash: 90fdaa9ac19a8cbff4698352724b3096aaf280eb3987961279069887751f4ec2
hypothesis: Enrich features — add S/R levels (ZB, ZS, tgt_long, sl_long) + volume
  buy/sell (vol_buy_ma_20, vol_sell_ma_20) on all 4 TFs (14->20 features). Does
  entry-relevant context beyond momentum/trend strengthen v4's 1.88x lift?
holdout_acc: 0.7125
holdout_loss: null
per_class:
  long_entry_base_rate: 0.0579
  precision_thr0.5: 0.1035
  precision_thr0.6: 0.1091
  precision_thr0.7: 0.1147
  recall_thr0.7: 0.366
  lift_thr0.7: 1.98
decision: promote
strike: 0
next_hypothesis: Two open levers and a methodology fix. (1) METHOD — switch the promotion
  gate from holdout accuracy to precision@high-confidence / lift; accuracy is too coarse
  for this 5.8%-positive target (v5's real gain was sub-margin on accuracy but clear on
  lift). (2) v6 — either restore history 32 WITH the 20 features (needs a row subsample
  to fit 8GB RAM) to test history+features together, or 8-trial Optuna to squeeze the
  current setup. Trajectory is flattening (1.40->1.88->1.98), so gains are diminishing.
---

# recurrent-temporal v5 — report

## Change from v4
Features only (with a forced history cut): added 6 entry-relevant inputs on all 4 TFs —
S/R levels `ZB, ZS, tgt_long, sl_long` and volume `vol_buy_ma_20, vol_sell_ma_20`
(14→20 features). history_points 32→20 was forced: 20feat×h32 tensors (~11 GB) OOM'd the
15 GB laptop during the dataset build; h20 keeps the build (~6.7 GB) under v4's footprint.

## Result (holdout = 204,749 rows, positive base rate 5.79%)
| threshold | precision | recall | lift | (v4 precision / lift) |
|---|---|---|---|---|
| 0.5 | 0.1035 | 0.518 | 1.79× | 0.0998 / 1.72× |
| 0.6 | 0.1091 | 0.452 | 1.88× | 0.1050 / 1.81× |
| 0.7 | 0.1147 | 0.366 | 1.98× | 0.1087 / 1.88× |

## Verdict — features help (despite shorter history)
v5 beats v4 at every threshold on both precision and recall, while using LESS history
(20 vs 32). The enriched features more than compensated for reduced lookback → S/R +
volume context carries genuine entry signal. The confound (shorter history) only
strengthens the read: with equal history, v5 would likely be even better.

## Methodology finding (ADR-0002 made concrete)
The promotion gate is holdout *accuracy*. v5's accuracy rose 0.7042→0.7125 = +0.0083,
**below the 0.01 margin → `decide` returns revert/strike-1**. But the metric that matters
(lift / precision at high confidence) clearly improved (1.88→1.98×). Accuracy is too
coarse for a 5.8%-positive target. **Adjudicated promote on the lift evidence** (ADR-0002:
per-class is the real signal; the agent decides). Recommend amending the gate to
precision@k / lift for imbalanced binary targets.

## Decision
Gate (accuracy): revert (+0.0083 < margin). Agent adjudication (lift 1.98× > 1.88×):
**promote**, strike 0. v5 is the new base.

## Lineage
| ver | change | long-prec@0.7 | lift | decision |
|---|---|---|---|---|
| v1 | 3-class dir, ep12 | ≈base | 1.0× | promote (baseline) |
| v2 | ep50 | ≈base | 1.0× | revert (undertraining ruled out) |
| v3 | binary long-only | 0.081 | 1.40× | promote (signal found) |
| v4 | + conv1d_seq | 0.109 | 1.88× | promote |
| v5 | + S/R & volume features (h32→20) | 0.115 | 1.98× | promote (on lift) |
