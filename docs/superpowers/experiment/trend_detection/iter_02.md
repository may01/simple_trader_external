# Iteration 02 -- prune_top40

- transform: prune_top40
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
| 15_up | logistic | train | 0.9938 | 0.9826 | 0.0998 | 0.8966 | 1.0000 | 0.7968 | 0.0998 | 862 |
| 15_up | logistic | test | 0.9540 | 0.9351 | 0.1324 | 0.8378 | 1.0000 | 0.7054 | 0.1324 | 370 |
| 15_up | gbc | train | 1.0000 | 1.0000 | 0.0998 | 0.9885 | 1.0000 | 0.8887 | 0.0998 | 862 |
| 15_up | gbc | test | 0.9411 | 0.9216 | 0.1324 | 0.7568 | 1.0000 | 0.6243 | 0.1324 | 370 |
| 15_dn | logistic | train | 0.9876 | 0.9814 | 0.8906 | 1.0000 | 0.9651 | 0.1094 | 0.8557 | 859 |
| 15_dn | logistic | test | 0.9695 | 0.9702 | 0.8916 | 1.0000 | 0.8649 | 0.1084 | 0.7565 | 369 |
| 15_dn | gbc | train | 1.0000 | 1.0000 | 0.8906 | 1.0000 | 1.0000 | 0.1094 | 0.8906 | 859 |
| 15_dn | gbc | test | 0.9706 | 0.9702 | 0.8916 | 1.0000 | 0.8919 | 0.1084 | 0.7835 | 369 |
| 60_up | logistic | train | 0.9972 | 0.9718 | 0.3592 | 1.0000 | 1.0000 | 0.6408 | 0.3592 | 142 |
| 60_up | logistic | test | 0.9793 | 0.8852 | 0.4426 | 1.0000 | 1.0000 | 0.5574 | 0.4426 | 61 |
| 60_up | gbc | train | 1.0000 | 1.0000 | 0.3592 | 1.0000 | 1.0000 | 0.6408 | 0.3592 | 142 |
| 60_up | gbc | test | 0.9967 | 0.9672 | 0.4426 | 1.0000 | 1.0000 | 0.5574 | 0.4426 | 61 |
| 60_dn | logistic | train | 0.9966 | 0.9870 | 0.6104 | 1.0000 | 1.0000 | 0.3896 | 0.6104 | 154 |
| 60_dn | logistic | test | 0.9424 | 0.8636 | 0.6212 | 1.0000 | 1.0000 | 0.3788 | 0.6212 | 66 |
| 60_dn | gbc | train | 1.0000 | 1.0000 | 0.6104 | 1.0000 | 1.0000 | 0.3896 | 0.6104 | 154 |
| 60_dn | gbc | test | 0.9385 | 0.9394 | 0.6212 | 1.0000 | 1.0000 | 0.3788 | 0.6212 | 66 |

## Top screened features

### 15_up

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 15_logret | 0.0462 | 0.0322 | 0.7601 |
| 15_close_diff_prc | 0.0462 | 0.0322 | 0.7601 |
| 15_body_ratio | 0.0552 | 0.0394 | 0.7730 |
| 5_rsi_ma12_diff | 0.0985 | 0.0747 | 0.6438 |
| 15_wick_up | 0.8877 | 0.8413 | 0.6657 |
| 5_close_diff_prc | 0.1217 | 0.0940 | 0.6154 |
| 5_logret | 0.1217 | 0.0940 | 0.6154 |
| 240_wick_up | 0.8359 | 0.7822 | 0.5613 |
| 15_rsi_ma8_diff | 0.3072 | 0.2556 | 0.3045 |
| 5_wick_dn | 0.6629 | 0.5976 | 0.3022 |

### 15_dn

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 5_rsi_ma8_diff | 0.0468 | 0.0168 | 0.7900 |
| 15_body_ratio | 0.0487 | 0.0181 | 0.7817 |
| 15_wick_dn | 0.1450 | 0.0958 | 0.6112 |
| 5_bb_lower_20_2_minus_close | 0.8515 | 0.8204 | 0.6435 |
| 15_range_atr | 0.7443 | 0.6997 | 0.4084 |
| 240_high_diff_prc_rm_6 | 0.4035 | 0.3400 | 0.1912 |
| 240_low_diff_prc_rm_6 | 0.4296 | 0.3662 | 0.1418 |
| 1440_adx_14 | 0.5527 | 0.4930 | 0.1286 |
| 240_low_diff_prc_rm_6_std_above | 0.4516 | 0.3886 | 0.0949 |
| 1440_zone_class | 0.5320 | 0.4713 | 0.0868 |

### 60_up

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 15_logret | 0.0281 | 0.0029 | 0.8203 |
| 15_close_diff_prc | 0.0281 | 0.0029 | 0.8203 |
| 240_wick_up | 0.7561 | 0.6691 | 0.5072 |
| 240_range_atr | 0.6652 | 0.5696 | 0.3269 |
| 240_body_ratio | 0.3579 | 0.2661 | 0.2603 |
| 240_vol_ma_20_minus_volume | 0.3954 | 0.3007 | 0.2342 |
| 240_atr_14_ma_5 | 0.4081 | 0.3125 | 0.1950 |
| 1440_ema_100_minus_close | 0.5861 | 0.4870 | 0.1885 |
| 240_bb_lower_20_2_minus_close | 0.5844 | 0.4852 | 0.2474 |
| 240_natr_14_ma_5 | 0.4197 | 0.3235 | 0.2545 |

### 60_dn

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 15_logret | 0.0126 | -0.0076 | 0.8954 |
| 240_wick_dn | 0.1548 | 0.0870 | 0.5475 |
| 15_wick_dn | 0.2267 | 0.1475 | 0.5071 |
| 240_body_ratio | 0.3418 | 0.2518 | 0.2787 |
| 1440_range_atr | 0.3637 | 0.2723 | 0.2376 |
| 240_wick_up | 0.6128 | 0.5234 | 0.2078 |
| 240_natr_14 | 0.3887 | 0.2962 | 0.2358 |
| 240_natr_14_ma_5 | 0.3970 | 0.3042 | 0.2117 |
| 240_low_diff_prc_rm_6_std_below | 0.3972 | 0.3044 | 0.2301 |
| 240_close_diff_prc_rm_6_std_below | 0.4053 | 0.3123 | 0.2156 |

## Top importance

### 15_up

| feature | imp_mean | imp_std |
|---|---|---|
| 15_wick_up | 0.0272 | 0.0014 |
| 60_macd_signal_12_26_9_slope | 0.0051 | 0.0001 |
| 1440_cci_14_ma_5 | 0.0027 | 0.0000 |
| 15_wick_dn | 0.0019 | 0.0004 |
| 15_logret | 0.0007 | 0.0002 |
| 15_rsi_ma8_diff | 0.0006 | 0.0002 |
| 1440_cci_diff | 0.0006 | 0.0003 |
| 15_body_ratio | 0.0004 | 0.0002 |
| 5_wick_dn | 0.0003 | 0.0002 |
| 1440_macd_hist_12_26_9 | 0.0002 | 0.0000 |

### 15_dn

| feature | imp_mean | imp_std |
|---|---|---|
| 15_body_ratio | 0.0575 | 0.0013 |
| 15_wick_dn | 0.0226 | 0.0026 |
| 15_range_atr | 0.0167 | 0.0003 |
| 5_bb_lower_20_2_minus_close | 0.0014 | 0.0003 |
| 15_wick_up | 0.0010 | 0.0004 |
| 15_cci_14 | 0.0010 | 0.0000 |
| 5_rsi_ma8_diff | 0.0003 | 0.0001 |
| 1440_cci_diff | 0.0002 | 0.0000 |
| 240_low_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 1440_rsi_ma12 | 0.0000 | 0.0000 |

### 60_up

| feature | imp_mean | imp_std |
|---|---|---|
| 15_logret | 0.0659 | 0.0192 |
| 15_close_diff_prc | 0.0462 | 0.0137 |
| 15_wick_dn | 0.0327 | 0.0049 |
| 15_macd_signal_5_13_9 | 0.0022 | 0.0012 |
| 240_close_diff_prc | 0.0000 | 0.0000 |
| 240_logret | 0.0000 | 0.0000 |
| 240_high_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_vol_ma_20_minus_volume | 0.0000 | 0.0000 |
| 240_range_atr | 0.0000 | 0.0000 |
| 240_low_diff_prc_rm_6 | 0.0000 | 0.0000 |

### 60_dn

| feature | imp_mean | imp_std |
|---|---|---|
| 15_logret | 0.4106 | 0.0404 |
| need_speed_up_240 | 0.0447 | 0.0220 |
| 15_wick_dn | 0.0391 | 0.0045 |
| 240_logret | 0.0005 | 0.0004 |
| 1440_range_atr | 0.0005 | 0.0002 |
| 240_high_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_close_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_high_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_close_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_low_diff_prc_rm_6 | 0.0000 | 0.0000 |

## Charts

### 15_up
- 15_up/charts/15_logret__hist.png
- 15_up/charts/15_logret__decile.png
- 15_up/charts/15_close_diff_prc__hist.png
- 15_up/charts/15_close_diff_prc__decile.png
- 15_up/charts/15_body_ratio__hist.png
- 15_up/charts/15_body_ratio__decile.png
- 15_up/charts/5_rsi_ma12_diff__hist.png
- 15_up/charts/5_rsi_ma12_diff__decile.png
- 15_up/charts/15_wick_up__hist.png
- 15_up/charts/15_wick_up__decile.png
- 15_up/charts/5_close_diff_prc__hist.png
- 15_up/charts/5_close_diff_prc__decile.png
- 15_up/charts/5_logret__hist.png
- 15_up/charts/5_logret__decile.png
- 15_up/charts/240_wick_up__hist.png
- 15_up/charts/240_wick_up__decile.png
- 15_up/charts/15_rsi_ma8_diff__hist.png
- 15_up/charts/15_rsi_ma8_diff__decile.png
- 15_up/charts/5_wick_dn__hist.png
- 15_up/charts/5_wick_dn__decile.png
- 15_up/charts/5_close_diff_prc_rm_6__hist.png
- 15_up/charts/5_close_diff_prc_rm_6__decile.png
- 15_up/charts/15_macd_signal_12_26_9_slope__hist.png
- 15_up/charts/15_macd_signal_12_26_9_slope__decile.png
- 15_up/charts/5_adx_14_slope__hist.png
- 15_up/charts/5_adx_14_slope__decile.png
- 15_up/charts/5_rsi_ma8__hist.png
- 15_up/charts/5_rsi_ma8__decile.png
- 15_up/charts/60_cci_14_ma_5__hist.png
- 15_up/charts/60_cci_14_ma_5__decile.png

### 15_dn
- 15_dn/charts/5_rsi_ma8_diff__hist.png
- 15_dn/charts/5_rsi_ma8_diff__decile.png
- 15_dn/charts/15_body_ratio__hist.png
- 15_dn/charts/15_body_ratio__decile.png
- 15_dn/charts/15_wick_dn__hist.png
- 15_dn/charts/15_wick_dn__decile.png
- 15_dn/charts/5_bb_lower_20_2_minus_close__hist.png
- 15_dn/charts/5_bb_lower_20_2_minus_close__decile.png
- 15_dn/charts/15_range_atr__hist.png
- 15_dn/charts/15_range_atr__decile.png
- 15_dn/charts/240_high_diff_prc_rm_6__hist.png
- 15_dn/charts/240_high_diff_prc_rm_6__decile.png
- 15_dn/charts/240_low_diff_prc_rm_6__hist.png
- 15_dn/charts/240_low_diff_prc_rm_6__decile.png
- 15_dn/charts/1440_adx_14__hist.png
- 15_dn/charts/1440_adx_14__decile.png
- 15_dn/charts/240_low_diff_prc_rm_6_std_above__hist.png
- 15_dn/charts/240_low_diff_prc_rm_6_std_above__decile.png
- 15_dn/charts/1440_zone_class__hist.png
- 15_dn/charts/1440_zone_class__decile.png
- 15_dn/charts/1440_ema_14_slope__hist.png
- 15_dn/charts/1440_ema_14_slope__decile.png
- 15_dn/charts/1440_rsi_ma8_diff__hist.png
- 15_dn/charts/1440_rsi_ma8_diff__decile.png
- 15_dn/charts/1440_ema_100_slope__hist.png
- 15_dn/charts/1440_ema_100_slope__decile.png
- 15_dn/charts/1440_ema_25_slope__hist.png
- 15_dn/charts/1440_ema_25_slope__decile.png
- 15_dn/charts/1440_cci_diff__hist.png
- 15_dn/charts/1440_cci_diff__decile.png

### 60_up
- 60_up/charts/15_logret__hist.png
- 60_up/charts/15_logret__decile.png
- 60_up/charts/15_close_diff_prc__hist.png
- 60_up/charts/15_close_diff_prc__decile.png
- 60_up/charts/240_wick_up__hist.png
- 60_up/charts/240_wick_up__decile.png
- 60_up/charts/240_range_atr__hist.png
- 60_up/charts/240_range_atr__decile.png
- 60_up/charts/240_body_ratio__hist.png
- 60_up/charts/240_body_ratio__decile.png
- 60_up/charts/240_vol_ma_20_minus_volume__hist.png
- 60_up/charts/240_vol_ma_20_minus_volume__decile.png
- 60_up/charts/240_atr_14_ma_5__hist.png
- 60_up/charts/240_atr_14_ma_5__decile.png
- 60_up/charts/1440_ema_100_minus_close__hist.png
- 60_up/charts/1440_ema_100_minus_close__decile.png
- 60_up/charts/240_bb_lower_20_2_minus_close__hist.png
- 60_up/charts/240_bb_lower_20_2_minus_close__decile.png
- 60_up/charts/240_natr_14_ma_5__hist.png
- 60_up/charts/240_natr_14_ma_5__decile.png
- 60_up/charts/240_natr_14__hist.png
- 60_up/charts/240_natr_14__decile.png
- 60_up/charts/15_wick_dn__hist.png
- 60_up/charts/15_wick_dn__decile.png
- 60_up/charts/240_wick_dn__hist.png
- 60_up/charts/240_wick_dn__decile.png
- 60_up/charts/1440_rsi_ma24__hist.png
- 60_up/charts/1440_rsi_ma24__decile.png
- 60_up/charts/240_low_diff_prc_rm_6__hist.png
- 60_up/charts/240_low_diff_prc_rm_6__decile.png

### 60_dn
- 60_dn/charts/15_logret__hist.png
- 60_dn/charts/15_logret__decile.png
- 60_dn/charts/240_wick_dn__hist.png
- 60_dn/charts/240_wick_dn__decile.png
- 60_dn/charts/15_wick_dn__hist.png
- 60_dn/charts/15_wick_dn__decile.png
- 60_dn/charts/240_body_ratio__hist.png
- 60_dn/charts/240_body_ratio__decile.png
- 60_dn/charts/1440_range_atr__hist.png
- 60_dn/charts/1440_range_atr__decile.png
- 60_dn/charts/240_wick_up__hist.png
- 60_dn/charts/240_wick_up__decile.png
- 60_dn/charts/240_natr_14__hist.png
- 60_dn/charts/240_natr_14__decile.png
- 60_dn/charts/240_natr_14_ma_5__hist.png
- 60_dn/charts/240_natr_14_ma_5__decile.png
- 60_dn/charts/240_low_diff_prc_rm_6_std_below__hist.png
- 60_dn/charts/240_low_diff_prc_rm_6_std_below__decile.png
- 60_dn/charts/240_close_diff_prc_rm_6_std_below__hist.png
- 60_dn/charts/240_close_diff_prc_rm_6_std_below__decile.png
- 60_dn/charts/1440_ema_7_minus_ema_14__hist.png
- 60_dn/charts/1440_ema_7_minus_ema_14__decile.png
- 60_dn/charts/240_range_atr__hist.png
- 60_dn/charts/240_range_atr__decile.png
- 60_dn/charts/1440_ema_14_minus_close__hist.png
- 60_dn/charts/1440_ema_14_minus_close__decile.png
- 60_dn/charts/1440_ema_25_minus_close__hist.png
- 60_dn/charts/1440_ema_25_minus_close__decile.png
- 60_dn/charts/240_close_diff_prc_rm_6_std_above__hist.png
- 60_dn/charts/240_close_diff_prc_rm_6_std_above__decile.png

## Verdict

KEPT: mean_test_auc=0.9617, best_before=0.9544, delta=+0.0073 (eps_auc=0.0050)
