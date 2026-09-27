# Archetype summary — full-snapshot-dense (LINK, 2y, strict 15m long entry)

Lineage HALTED at v5 on a discovered **measurement-validity failure** — not on strikes,
max_versions, or budget. The promotion gate (argmax accuracy) is invalid for this
~5.8%-positive target and rewards the always-negative collapse. No trustworthy winner
until the gate is fixed (precision@k / lift). Iterated on **2y link_usdt**; **no 4y
confirm** (per operator).

## Lineage

| ver | structural change (ONE per version) | spec_hash | holdout_score | decision |
|---|---|---|---|---|
| v1 | kitchen-sink snapshot: 102 feat × 6 tf, h=1, dense×3 | `cef7e106` | 0.6781 | promote (baseline) |
| v2a | history_points 1→8 | — | **OOM** (137) | discarded (infra, not a strike) |
| v2 | history_points 1→4 (window) | `1ea89ee9` | 0.7100 | promote (+0.032) |
| v3 | dense[0]→conv1d(k3) (local pattern) | `1a7c5b97` | **0.7267** | promote (+0.017) |
| v4 | conv1d→conv1d_seq (preserve sequence) | `b4fb8a78` | 0.7124 | revert (−0.014, strike 1) |
| v5 | conv1d_seq→gru→dense (recurrent) | `a1175b4d` | 0.9422 → **rejected** | HALT (broken gate) |

## What the archetype learned (in the non-degenerate regime)

1. **Breadth is buildable but myopic at a single instant.** The full 102-feature × 6-tf
   snapshot (h=1) trains, but v1's score plateaus at 0.667–0.683 across the ENTIRE Optuna
   sweep — the shape, not the tuning, was the limit.
2. **A short window is the first real lift.** history_points 1→4 gave +0.032 (0.678→0.710).
   The intended h=8 is infeasible on this 15GB-RAM box (OOM: 474 cols × 8 × 1.05M float64).
3. **Local pattern compounds.** A conv1d(k3) front over the window added +0.017 (→0.727).
4. **Preserving the sequence needs a consumer.** conv1d_seq alone regressed (−0.014) — a
   flattening dense head can't use temporal order.
5. **The recurrent stage is the biggest lever.** conv1d_seq→gru reached a real
   (non-degenerate) 0.7694 — +0.043 over v3 — echoing recurrent-temporal's conv→recurrent
   win. But this is where the metric broke.

## The decisive finding — the promotion gate is invalid for this target

- `direction_binary` holdout_score = **plain argmax accuracy** (`training_loop._score_predictions`).
- Holdout positive (long) rate = 5.78%; negative base rate = **0.94224** (209,646 rows).
- v5 trial u23 scored **0.94224** — the always-predict-"other" degenerate model: 94.2%
  accuracy, **zero long recall**, worthless as a filter. `cli decide` mechanically returned
  "promote: +0.2155".
- The metric monotonically rewards predicting FEWER longs, so **every** version's score is
  suspect — v1→v3's 0.678→0.727 hill-climb partly rewards conservatism, not trading quality.
- This is the exact **ADR-0002** gap the recurrent-temporal SUMMARY flagged: "promotion gate
  is holdout accuracy — too coarse … amend to precision@k / lift before the next archetype."
  It was not amended before this archetype.

## Required next step (human gate)

1. **Fix the gate (engine TDD):** replace the `direction_binary` accuracy scorer with a
   precision@k / lift holdout score; update **both** scorers (train `_accuracy_counts` and
   holdout `_score_predictions`) per the two-scorer invariant; amend ADR-0002. Add tests
   that a degenerate always-negative predictor scores ~0, not ~0.94.
2. **Re-score / re-run** the lineage (at minimum v1, v3, v5) on the corrected metric — only
   then are the promote/revert decisions and any "winner" trustworthy.
3. The **architecture** finding stands independent of the gate: window → conv → recurrent
   each added signal in the non-degenerate regime; conv1d_seq→gru is the shape to carry
   forward once the metric is fixed.

## Data-reality notes (this 2y dataset)

- 6 of the 108 non-target fields are unusable and were dropped: `align_5`/`align_15`/
  `align_1440` (no column generated), `align_60`/`align_240` (columns exist but entirely
  NaN), `vol_regime` (entirely NaN at 15/60/240, absent at 1/5/1440). Net **102 features**,
  474 resolved `{tf}_{ind}` columns; full 2y series (1,052,560 one-minute rows) survives the
  NaN-drop. All cross-timeframe alignment flags being dead means the archetype's
  cross-timeframe-alignment thesis could not be exercised — regenerating those upstream is a
  separate improvement.

## Artefacts

- Specs on volume: `…/train/link_usdt/nn/specs/{cef7e106,1ea89ee9,1a7c5b97,b4fb8a78,a1175b4d}/spec.yaml`
- Studies: `…/nn/tracking/full_snapshot_dense_2y_v{1,2,3,4,5}` (host-readable at
  `/media/om/Alexandria/simple_trader/simple_trader_vol_long/…`).
- Reports: `full-snapshot-dense/v{1..5}/report.md` (each parseable by `parse_report`).
