# Archetype summary — recurrent-temporal (LINK, 2y, strict 15m long entry)

Lineage complete: 6 versions, stopped at max_versions. **Winner: v6** (conv1d_seq → lstm →
dense, 20 features, binary long-only, history 20, 8-trial Optuna).

## Lineage

| ver | change | long-precision | lift | decision |
|---|---|---|---|---|
| v1 | 3-class direction, epochs 12 | ≈ base rate | 1.0× | promote (baseline) |
| v2 | epochs 50 | ≈ base rate | 1.0× | revert — undertraining ruled out |
| v3 | binary long-only target | 0.081 @0.7 | 1.40× | promote — **signal found** |
| v4 | + conv1d_seq front | 0.109 @0.7 | 1.88× | promote — conv helps |
| v5 | + S/R & volume features (h32→20) | 0.115 @0.7 | 1.98× | promote (on lift) |
| **v6** | **8-trial search** | **0.145 @0.7** | **2.50×** | **promote — winner; stop (max_versions)** |

## What the archetype learned
1. **Target framing is decisive.** 3-class up/neutral/down (v1/v2) had ZERO signal even
   fully trained; a single binary long-only strict label (v3) immediately surfaced 1.40×.
2. **Local + temporal compound.** A sequence-preserving conv front before the LSTM (v4)
   captured entry micro-structure → 1.88×.
3. **Entry-context features help.** S/R levels + volume buy/sell (v5) added value even with
   shorter history → 1.98×.
4. **Search depth matters.** 8 trials vs 3 (v6) found a sharper operating point → 2.50× at
   high confidence (precision 14.5% vs 5.8% base), trading recall for purity.

## Best model (v6)
- spec_hash 90fdaa9a (best trial 7f94b476); checkpoint
  `train/link_usdt/nn/checkpoints/90fdaa9a…/all_best.pt`.
- conv1d_seq(32,k3) → lstm(64) → dense(32); 20 features × [15,60,240,1440]; history 20;
  binary strict 15m long label (m1/x0.3/l15/y0.2); class_weight balanced.
- Holdout (2y, 204,749 rows): @thr0.7 precision 0.1447 (2.50× base), recall 0.085;
  @thr0.6 precision 0.1235 (2.13×), recall 0.150.

## Caveats / open items
- **Trained on slim 2y data, history capped at 20, epochs 50 via batch 256** — laptop RAM
  (15 GB) + 4 GB GPU forced these. A bigger box could test history 32 + full feature set +
  deeper search (likely higher).
- **Promotion gate is holdout accuracy — too coarse** for this 5.8%-positive target
  (v5's real gain was sub-margin on accuracy; adjudicated on lift). Amend ADR-0002 to
  precision@k / lift before the next archetype.
- **No P&L yet** (ADR-0002 deferral). The 2.50× precision lift + favorable R:R
  (1 ATR target vs 0.3 ATR stop) is promising but unconfirmed as profit.
- **Long-only.** Short side (psshort) not modelled.

## Recommended next (archetype gate)
1. Re-validate v6 on the 4y dataset (regime-robustness check).
2. P&L backtest the v6 long filter — the true-north test now that a model is worth it.
3. Then gate to the next archetype (conv-local, mlp-snapshot, attention-crosstf) or pivot
   (short side, other pairs).

## Engine extensions committed during this archetype (branch phase-17-nn-orchestration)
- `label_l`/`label_y` on TargetSpec (strict targets).
- chunked holdout inference (`HOLDOUT_EVAL_CHUNK`) — GPU OOM on large holdouts.
- `conv1d_seq` sequence-preserving conv layer kind.
