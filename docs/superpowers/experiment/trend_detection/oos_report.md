# OOS validation report (frozen artifacts, zero refit)

- train_base: /trader_data_long/train/2y_link_usdt/trend_detection/
- best_iter: 2 (transform=prune_top40, horizon=n1)

## Crosscheck gate (cut-provenance drift check)

| tf | status | fraction |
|---|---|---|
| tf=15 | passed | 1.0000 |
| tf=60 | passed | 1.0000 |
| tf=240 | passed | 1.0000 |

## Per-combo metrics (test vs oos)

| combo | model | split | roc_auc | acc | base_rate | prec_top_decile | prec_bottom_decile | lift_long | lift_short | n |
|---|---|---|---|---|---|---|---|---|---|---|
| 15_dn | logistic | test | 0.9695 | 0.9702 | 0.8916 | 1.0000 | 0.8649 | 0.1084 | 0.7565 | 369 |
| 15_dn | logistic | oos | 0.9771 | 0.9535 | 0.9302 | 1.0000 | 0.5556 | 0.0698 | 0.4858 | 86 |
| 15_dn | gbc | test | 0.9706 | 0.9702 | 0.8916 | 1.0000 | 0.8919 | 0.1084 | 0.7835 | 369 |
| 15_dn | gbc | oos | 0.9896 | 0.9651 | 0.9302 | 1.0000 | 0.5556 | 0.0698 | 0.4858 | 86 |
| 15_up | logistic | test | 0.9540 | 0.9351 | 0.1324 | 0.8378 | 1.0000 | 0.7054 | 0.1324 | 370 |
| 15_up | logistic | oos | 0.9902 | 0.9495 | 0.1313 | 0.9000 | 1.0000 | 0.7687 | 0.1313 | 99 |
| 15_up | gbc | test | 0.9411 | 0.9216 | 0.1324 | 0.7568 | 1.0000 | 0.6243 | 0.1324 | 370 |
| 15_up | gbc | oos | 0.9785 | 0.8485 | 0.1313 | 0.9000 | 1.0000 | 0.7687 | 0.1313 | 99 |
| 60_dn | logistic | test | 0.9424 | 0.8636 | 0.6212 | 1.0000 | 1.0000 | 0.3788 | 0.6212 | 66 |
| 60_dn | logistic | oos | nan | nan | nan | nan | nan | nan | nan | 15 |
| 60_dn | gbc | test | 0.9385 | 0.9394 | 0.6212 | 1.0000 | 1.0000 | 0.3788 | 0.6212 | 66 |
| 60_dn | gbc | oos | nan | nan | nan | nan | nan | nan | nan | 15 |
| 60_up | logistic | test | 0.9793 | 0.8852 | 0.4426 | 1.0000 | 1.0000 | 0.5574 | 0.4426 | 61 |
| 60_up | logistic | oos | nan | nan | nan | nan | nan | nan | nan | 9 |
| 60_up | gbc | test | 0.9967 | 0.9672 | 0.4426 | 1.0000 | 1.0000 | 0.5574 | 0.4426 | 61 |
| 60_up | gbc | oos | nan | nan | nan | nan | nan | nan | nan | 9 |

## Robustness (oos, truth vs realized forward return)

| combo | long_fwd1 | long_fwd4 | short_fwd1 | short_fwd4 |
|---|---|---|---|---|
| 15_dn | 0.9000 | 0.7375 | 1.0000 | 0.8333 |
| 15_up | 0.9231 | 0.7692 | 0.8605 | 0.7442 |
| 60_dn | nan | nan | nan | nan |
| 60_up | nan | nan | nan | nan |

## Verdicts

Per combo, judged off the gbc model (this pipeline's own primary/higher-capacity model -- see tdlib.loop.IterResult.mean_test_auc, which is gbc-only): 'holds' iff oos roc_auc > 0.5 AND oos lift_long's sign matches the frozen iteration's own test-split lift_long sign AND oos lift_short's sign matches its own test-split lift_short sign -- BOTH signs, not lift_long alone (this is a two-sided experiment; a side=-2 'dn' combo is not 'short-native', so judging it on lift_short alone -- or either side alone -- would be arbitrary, not principled). Any NaN among those four signed quantities -> 'fails'. 'skipped' if the oos slim had too few marked points to score; 'fails' otherwise.

- 15_dn: holds (oos_auc=0.9896, oos_lift_long=0.0698, test_lift_long=0.1084, oos_lift_short=0.4858, test_lift_short=0.7835)
- 15_up: holds (oos_auc=0.9785, oos_lift_long=0.7687, test_lift_long=0.6243, oos_lift_short=0.1313, test_lift_short=0.1324)
- 60_dn: skipped (n=15 < 30)
- 60_up: skipped (n=9 < 30)
