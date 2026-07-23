# Iteration 01 -- baseline

- transform: baseline
- horizon: n1

## Counts

| combo | tf | side | n_long | n_short | both | neither | nan | skipped |
|---|---|---|---|---|---|---|---|---|
| 15_up | 15 | 2 | 135 | 1097 | 1 | 9456 | 0 | False |
| 15_dn | 15 | -2 | 1094 | 134 | 2 | 9495 | 0 | False |
| 60_up | 60 | 2 | 78 | 125 | 0 | 2389 | 0 | False |
| 60_dn | 60 | -2 | 135 | 85 | 0 | 2376 | 0 | False |
| 240_up | 240 | 2 | 26 | 21 | 0 | 618 | 0 | True |
| 240_dn | 240 | -2 | 17 | 25 | 0 | 630 | 0 | True |

## Robustness (truth vs realized forward return)

| combo | long_fwd1 | long_fwd4 | short_fwd1 | short_fwd4 |
|---|---|---|---|---|
| 15_up | 0.8963 | 0.6815 | 0.9152 | 0.7539 |
| 15_dn | 0.9168 | 0.7422 | 0.8657 | 0.6866 |
| 60_up | 0.9231 | 0.7821 | 0.9280 | 0.7840 |
| 60_dn | 0.9407 | 0.8074 | 0.9059 | 0.6235 |

## Metrics

| combo | model | split | roc_auc | acc | base_rate | prec_top_decile | prec_bottom_decile | lift_long | lift_short | n |
|---|---|---|---|---|---|---|---|---|---|---|
| 15_up | logistic | train | 1.0000 | 1.0000 | 0.0998 | 0.9885 | 1.0000 | 0.8887 | 0.0998 | 862 |
| 15_up | logistic | test | 0.9435 | 0.9378 | 0.1324 | 0.8378 | 1.0000 | 0.7054 | 0.1324 | 370 |
| 15_up | gbc | train | 1.0000 | 1.0000 | 0.0998 | 0.9885 | 1.0000 | 0.8887 | 0.0998 | 862 |
| 15_up | gbc | test | 0.9412 | 0.9216 | 0.1324 | 0.8108 | 1.0000 | 0.6784 | 0.1324 | 370 |
| 15_dn | logistic | train | 1.0000 | 1.0000 | 0.8906 | 1.0000 | 1.0000 | 0.1094 | 0.8906 | 859 |
| 15_dn | logistic | test | 0.9666 | 0.9648 | 0.8916 | 0.9730 | 0.8649 | 0.0814 | 0.7565 | 369 |
| 15_dn | gbc | train | 1.0000 | 1.0000 | 0.8906 | 1.0000 | 1.0000 | 0.1094 | 0.8906 | 859 |
| 15_dn | gbc | test | 0.9642 | 0.9675 | 0.8916 | 0.9730 | 0.8649 | 0.0814 | 0.7565 | 369 |
| 60_up | logistic | train | 1.0000 | 1.0000 | 0.3592 | 1.0000 | 1.0000 | 0.6408 | 0.3592 | 142 |
| 60_up | logistic | test | 0.9281 | 0.8689 | 0.4426 | 1.0000 | 1.0000 | 0.5574 | 0.4426 | 61 |
| 60_up | gbc | train | 1.0000 | 1.0000 | 0.3592 | 1.0000 | 1.0000 | 0.6408 | 0.3592 | 142 |
| 60_up | gbc | test | 0.9401 | 0.8525 | 0.4426 | 1.0000 | 0.8571 | 0.5574 | 0.2998 | 61 |
| 60_dn | logistic | train | 1.0000 | 1.0000 | 0.6104 | 1.0000 | 1.0000 | 0.3896 | 0.6104 | 154 |
| 60_dn | logistic | test | 0.9678 | 0.8788 | 0.6212 | 1.0000 | 1.0000 | 0.3788 | 0.6212 | 66 |
| 60_dn | gbc | train | 1.0000 | 1.0000 | 0.6104 | 1.0000 | 1.0000 | 0.3896 | 0.6104 | 154 |
| 60_dn | gbc | test | 0.9722 | 0.9242 | 0.6212 | 1.0000 | 1.0000 | 0.3788 | 0.6212 | 66 |

## Top screened features

### 15_up

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 15_logret | 0.0462 | 0.0322 | 0.7601 |
| 15_close_diff_prc | 0.0462 | 0.0322 | 0.7601 |
| 15_body_ratio | 0.0552 | 0.0394 | 0.7730 |
| 5_rsi_ma8_diff | 0.0705 | 0.0517 | 0.7342 |
| 5_cci_14 | 0.0879 | 0.0660 | 0.7253 |
| 5_rsi_ma12_diff | 0.0985 | 0.0747 | 0.6438 |
| 60_wick_up | 0.8940 | 0.8488 | 0.6697 |
| 15_wick_up | 0.8877 | 0.8413 | 0.6657 |
| 5_body_ratio | 0.1186 | 0.0914 | 0.6632 |
| 5_close_diff_prc | 0.1217 | 0.0940 | 0.6154 |

### 15_dn

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 15_close_diff_prc | 0.0419 | 0.0134 | 0.8172 |
| 15_logret | 0.0419 | 0.0134 | 0.8172 |
| 5_rsi_ma8_diff | 0.0468 | 0.0168 | 0.7900 |
| 15_body_ratio | 0.0487 | 0.0181 | 0.7817 |
| 5_rsi_ma12_diff | 0.0816 | 0.0429 | 0.6898 |
| 5_cci_14 | 0.0856 | 0.0461 | 0.7364 |
| 5_logret | 0.0951 | 0.0538 | 0.6599 |
| 5_close_diff_prc | 0.0951 | 0.0538 | 0.6599 |
| 5_body_ratio | 0.1187 | 0.0733 | 0.6483 |
| 60_wick_dn | 0.1292 | 0.0823 | 0.6466 |

### 60_up

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 15_close_diff_prc | 0.0281 | 0.0029 | 0.8203 |
| 15_logret | 0.0281 | 0.0029 | 0.8203 |
| 15_body_ratio | 0.0315 | 0.0047 | 0.8117 |
| 5_logret | 0.0609 | 0.0230 | 0.7410 |
| 5_close_diff_prc | 0.0609 | 0.0230 | 0.7410 |
| 5_rsi_ma8_diff | 0.0763 | 0.0335 | 0.6759 |
| 5_body_ratio | 0.0999 | 0.0504 | 0.6955 |
| 5_ema_7_minus_close | 0.8989 | 0.8387 | 0.6328 |
| 5_rsi_ma12_diff | 0.1248 | 0.0691 | 0.6132 |
| 60_wick_up | 0.8438 | 0.7707 | 0.6311 |

### 60_dn

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 15_body_ratio | 0.0096 | -0.0080 | 0.9074 |
| 15_close_diff_prc | 0.0126 | -0.0076 | 0.8954 |
| 15_logret | 0.0126 | -0.0076 | 0.8954 |
| 5_rsi_ma8_diff | 0.0491 | 0.0096 | 0.7663 |
| 5_rsi_ma12_diff | 0.0823 | 0.0316 | 0.7284 |
| 5_ema_7_minus_close | 0.9039 | 0.8570 | 0.7074 |
| 5_close_diff_prc | 0.1035 | 0.0470 | 0.6876 |
| 5_logret | 0.1035 | 0.0470 | 0.6876 |
| 60_wick_dn | 0.1137 | 0.0547 | 0.6567 |
| 5_body_ratio | 0.1142 | 0.0551 | 0.6543 |

## Top importance

### 15_up

| feature | imp_mean | imp_std |
|---|---|---|
| 15_wick_up | 0.0425 | 0.0024 |
| 15_logret | 0.0051 | 0.0011 |
| 1440_cci_14_ma_5 | 0.0008 | 0.0000 |
| 15_close_diff_prc | 0.0007 | 0.0006 |
| 60_macd_signal_12_26_9_slope | 0.0006 | 0.0000 |
| 15_wick_dn | 0.0004 | 0.0001 |
| 1440_cci_diff | 0.0003 | 0.0002 |
| 15_rsi_ma8_diff | 0.0003 | 0.0000 |
| 15_body_ratio | 0.0002 | 0.0001 |
| 240_wick_up | 0.0001 | 0.0001 |

### 15_dn

| feature | imp_mean | imp_std |
|---|---|---|
| 15_wick_dn | 0.0132 | 0.0014 |
| 15_body_ratio | 0.0077 | 0.0006 |
| 15_wick_up | 0.0007 | 0.0005 |
| 15_range_atr | 0.0004 | 0.0000 |
| 15_cci_14 | 0.0001 | 0.0000 |
| 5_bb_lower_20_2_minus_close | 0.0001 | 0.0002 |
| 5_rsi_ma8_diff | 0.0000 | 0.0000 |
| 1440_cci_diff | 0.0000 | 0.0000 |
| 1440_rsi_ma8 | 0.0000 | 0.0000 |
| 1440_rsi_ma8_diff | 0.0000 | 0.0000 |

### 60_up

| feature | imp_mean | imp_std |
|---|---|---|
| 15_logret | 0.0559 | 0.0106 |
| 15_wick_dn | 0.0272 | 0.0095 |
| 15_macd_signal_5_13_9 | 0.0000 | 0.0000 |
| 15_close_diff_prc | 0.0000 | 0.0000 |
| 240_low_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_high_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_high_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_close_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_close_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_low_diff_prc_rm_6 | 0.0000 | 0.0000 |

### 60_dn

| feature | imp_mean | imp_std |
|---|---|---|
| 15_logret | 0.0795 | 0.0218 |
| 15_wick_dn | 0.0297 | 0.0040 |
| need_speed_up_240 | 0.0004 | 0.0002 |
| 1440_range_atr | 0.0000 | 0.0000 |
| 240_high_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_high_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_close_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_close_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_low_diff_prc_rm_6 | 0.0000 | 0.0000 |
| 240_high_diff_prc_rm_6 | 0.0000 | 0.0000 |

## Charts

### 15_up
- 15_up/charts/15_logret__hist.png
- 15_up/charts/15_logret__decile.png
- 15_up/charts/15_close_diff_prc__hist.png
- 15_up/charts/15_close_diff_prc__decile.png
- 15_up/charts/15_body_ratio__hist.png
- 15_up/charts/15_body_ratio__decile.png
- 15_up/charts/5_rsi_ma8_diff__hist.png
- 15_up/charts/5_rsi_ma8_diff__decile.png
- 15_up/charts/5_cci_14__hist.png
- 15_up/charts/5_cci_14__decile.png
- 15_up/charts/5_rsi_ma12_diff__hist.png
- 15_up/charts/5_rsi_ma12_diff__decile.png
- 15_up/charts/60_wick_up__hist.png
- 15_up/charts/60_wick_up__decile.png
- 15_up/charts/15_wick_up__hist.png
- 15_up/charts/15_wick_up__decile.png
- 15_up/charts/5_body_ratio__hist.png
- 15_up/charts/5_body_ratio__decile.png
- 15_up/charts/5_close_diff_prc__hist.png
- 15_up/charts/5_close_diff_prc__decile.png
- 15_up/charts/5_logret__hist.png
- 15_up/charts/5_logret__decile.png
- 15_up/charts/5_bb_upper_20_2_minus_close__hist.png
- 15_up/charts/5_bb_upper_20_2_minus_close__decile.png
- 15_up/charts/5_rsi_ma24_diff__hist.png
- 15_up/charts/5_rsi_ma24_diff__decile.png
- 15_up/charts/240_wick_up__hist.png
- 15_up/charts/240_wick_up__decile.png
- 15_up/charts/5_ema_7_minus_close__hist.png
- 15_up/charts/5_ema_7_minus_close__decile.png

### 15_dn
- 15_dn/charts/15_close_diff_prc__hist.png
- 15_dn/charts/15_close_diff_prc__decile.png
- 15_dn/charts/15_logret__hist.png
- 15_dn/charts/15_logret__decile.png
- 15_dn/charts/5_rsi_ma8_diff__hist.png
- 15_dn/charts/5_rsi_ma8_diff__decile.png
- 15_dn/charts/15_body_ratio__hist.png
- 15_dn/charts/15_body_ratio__decile.png
- 15_dn/charts/5_rsi_ma12_diff__hist.png
- 15_dn/charts/5_rsi_ma12_diff__decile.png
- 15_dn/charts/5_cci_14__hist.png
- 15_dn/charts/5_cci_14__decile.png
- 15_dn/charts/5_logret__hist.png
- 15_dn/charts/5_logret__decile.png
- 15_dn/charts/5_close_diff_prc__hist.png
- 15_dn/charts/5_close_diff_prc__decile.png
- 15_dn/charts/5_body_ratio__hist.png
- 15_dn/charts/5_body_ratio__decile.png
- 15_dn/charts/60_wick_dn__hist.png
- 15_dn/charts/60_wick_dn__decile.png
- 15_dn/charts/5_ema_7_minus_close__hist.png
- 15_dn/charts/5_ema_7_minus_close__decile.png
- 15_dn/charts/15_wick_dn__hist.png
- 15_dn/charts/15_wick_dn__decile.png
- 15_dn/charts/5_bb_lower_20_2_minus_close__hist.png
- 15_dn/charts/5_bb_lower_20_2_minus_close__decile.png
- 15_dn/charts/5_cci_diff__hist.png
- 15_dn/charts/5_cci_diff__decile.png
- 15_dn/charts/5_rsi_ma24_diff__hist.png
- 15_dn/charts/5_rsi_ma24_diff__decile.png

### 60_up
- 60_up/charts/15_close_diff_prc__hist.png
- 60_up/charts/15_close_diff_prc__decile.png
- 60_up/charts/15_logret__hist.png
- 60_up/charts/15_logret__decile.png
- 60_up/charts/15_body_ratio__hist.png
- 60_up/charts/15_body_ratio__decile.png
- 60_up/charts/5_logret__hist.png
- 60_up/charts/5_logret__decile.png
- 60_up/charts/5_close_diff_prc__hist.png
- 60_up/charts/5_close_diff_prc__decile.png
- 60_up/charts/5_rsi_ma8_diff__hist.png
- 60_up/charts/5_rsi_ma8_diff__decile.png
- 60_up/charts/5_body_ratio__hist.png
- 60_up/charts/5_body_ratio__decile.png
- 60_up/charts/5_ema_7_minus_close__hist.png
- 60_up/charts/5_ema_7_minus_close__decile.png
- 60_up/charts/5_rsi_ma12_diff__hist.png
- 60_up/charts/5_rsi_ma12_diff__decile.png
- 60_up/charts/60_wick_up__hist.png
- 60_up/charts/60_wick_up__decile.png
- 60_up/charts/5_cci_diff__hist.png
- 60_up/charts/5_cci_diff__decile.png
- 60_up/charts/5_cci_14__hist.png
- 60_up/charts/5_cci_14__decile.png
- 60_up/charts/5_rsi_ma24_diff__hist.png
- 60_up/charts/5_rsi_ma24_diff__decile.png
- 60_up/charts/5_ema_14_minus_close__hist.png
- 60_up/charts/5_ema_14_minus_close__decile.png
- 60_up/charts/15_wick_up__hist.png
- 60_up/charts/15_wick_up__decile.png

### 60_dn
- 60_dn/charts/15_body_ratio__hist.png
- 60_dn/charts/15_body_ratio__decile.png
- 60_dn/charts/15_close_diff_prc__hist.png
- 60_dn/charts/15_close_diff_prc__decile.png
- 60_dn/charts/15_logret__hist.png
- 60_dn/charts/15_logret__decile.png
- 60_dn/charts/5_rsi_ma8_diff__hist.png
- 60_dn/charts/5_rsi_ma8_diff__decile.png
- 60_dn/charts/5_rsi_ma12_diff__hist.png
- 60_dn/charts/5_rsi_ma12_diff__decile.png
- 60_dn/charts/5_ema_7_minus_close__hist.png
- 60_dn/charts/5_ema_7_minus_close__decile.png
- 60_dn/charts/5_close_diff_prc__hist.png
- 60_dn/charts/5_close_diff_prc__decile.png
- 60_dn/charts/5_logret__hist.png
- 60_dn/charts/5_logret__decile.png
- 60_dn/charts/60_wick_dn__hist.png
- 60_dn/charts/60_wick_dn__decile.png
- 60_dn/charts/5_body_ratio__hist.png
- 60_dn/charts/5_body_ratio__decile.png
- 60_dn/charts/5_cci_14__hist.png
- 60_dn/charts/5_cci_14__decile.png
- 60_dn/charts/5_rsi_ma24_diff__hist.png
- 60_dn/charts/5_rsi_ma24_diff__decile.png
- 60_dn/charts/240_wick_dn__hist.png
- 60_dn/charts/240_wick_dn__decile.png
- 60_dn/charts/5_bb_lower_20_2_minus_close__hist.png
- 60_dn/charts/5_bb_lower_20_2_minus_close__decile.png
- 60_dn/charts/5_cci_diff__hist.png
- 60_dn/charts/5_cci_diff__decile.png

## Verdict

KEPT: mean_test_auc=0.9544, best_before=-inf, delta=+nan (eps_auc=0.0050)
