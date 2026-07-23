# Iteration 04 -- horizon_n2

- transform: horizon_n2
- horizon: n2

## Counts

| combo | tf | side | n_long | n_short | both | neither | nan | skipped |
|---|---|---|---|---|---|---|---|---|
| 15_up | 15 | 2 | 198 | 1780 | 1 | 8710 | 0 | False |
| 15_dn | 15 | -2 | 1700 | 207 | 2 | 8816 | 0 | False |
| 60_up | 60 | 2 | 114 | 207 | 0 | 2271 | 0 | False |
| 60_dn | 60 | -2 | 218 | 119 | 0 | 2259 | 0 | False |
| 240_up | 240 | 2 | 36 | 32 | 0 | 597 | 0 | False |
| 240_dn | 240 | -2 | 29 | 31 | 0 | 612 | 0 | False |

## Robustness (truth vs realized forward return)

| combo | long_fwd1 | long_fwd4 | short_fwd1 | short_fwd4 |
|---|---|---|---|---|
| 15_up | 0.8939 | 0.7323 | 0.9185 | 0.7871 |
| 15_dn | 0.9206 | 0.7724 | 0.8889 | 0.7053 |
| 60_up | 0.9474 | 0.8070 | 0.9420 | 0.8019 |
| 60_dn | 0.9587 | 0.8257 | 0.9244 | 0.6639 |
| 240_up | 0.9444 | 0.8056 | 0.9375 | 0.8125 |
| 240_dn | 0.9310 | 0.7931 | 0.9032 | 0.7419 |

## Metrics

| combo | model | split | roc_auc | acc | base_rate | prec_top_decile | prec_bottom_decile | lift_long | lift_short | n |
|---|---|---|---|---|---|---|---|---|---|---|
| 15_up | logistic | train | 1.0000 | 1.0000 | 0.0925 | 0.9209 | 1.0000 | 0.8284 | 0.0925 | 1384 |
| 15_up | logistic | test | 0.9620 | 0.9343 | 0.1178 | 0.7833 | 1.0000 | 0.6655 | 0.1178 | 594 |
| 15_up | gbc | train | 1.0000 | 1.0000 | 0.0925 | 0.9209 | 1.0000 | 0.8284 | 0.0925 | 1384 |
| 15_up | gbc | test | 0.9139 | 0.9158 | 0.1178 | 0.7333 | 1.0000 | 0.6155 | 0.1178 | 594 |
| 15_dn | logistic | train | 1.0000 | 1.0000 | 0.8913 | 1.0000 | 1.0000 | 0.1087 | 0.8913 | 1334 |
| 15_dn | logistic | test | 0.9626 | 0.9546 | 0.8918 | 0.9828 | 0.8276 | 0.0910 | 0.7194 | 573 |
| 15_dn | gbc | train | 1.0000 | 1.0000 | 0.8913 | 1.0000 | 1.0000 | 0.1087 | 0.8913 | 1334 |
| 15_dn | gbc | test | 0.9626 | 0.9546 | 0.8918 | 1.0000 | 0.8103 | 0.1082 | 0.7021 | 573 |
| 60_up | logistic | train | 1.0000 | 1.0000 | 0.3214 | 1.0000 | 1.0000 | 0.6786 | 0.3214 | 224 |
| 60_up | logistic | test | 0.8918 | 0.7938 | 0.4330 | 0.9000 | 1.0000 | 0.4670 | 0.4330 | 97 |
| 60_up | gbc | train | 1.0000 | 1.0000 | 0.3214 | 1.0000 | 1.0000 | 0.6786 | 0.3214 | 224 |
| 60_up | gbc | test | 0.9610 | 0.8866 | 0.4330 | 1.0000 | 1.0000 | 0.5670 | 0.4330 | 97 |
| 60_dn | logistic | train | 1.0000 | 1.0000 | 0.6468 | 1.0000 | 1.0000 | 0.3532 | 0.6468 | 235 |
| 60_dn | logistic | test | 0.9853 | 0.9314 | 0.6471 | 1.0000 | 1.0000 | 0.3529 | 0.6471 | 102 |
| 60_dn | gbc | train | 1.0000 | 1.0000 | 0.6468 | 1.0000 | 1.0000 | 0.3532 | 0.6468 | 235 |
| 60_dn | gbc | test | 0.9600 | 0.9020 | 0.6471 | 1.0000 | 1.0000 | 0.3529 | 0.6471 | 102 |
| 240_up | logistic | train | 1.0000 | 1.0000 | 0.5532 | 1.0000 | 1.0000 | 0.4468 | 0.5532 | 47 |
| 240_up | logistic | test | 0.7636 | 0.7143 | 0.4762 | 1.0000 | 0.6667 | 0.5238 | 0.1429 | 21 |
| 240_up | gbc | train | 1.0000 | 1.0000 | 0.5532 | 1.0000 | 1.0000 | 0.4468 | 0.5532 | 47 |
| 240_up | gbc | test | 0.6091 | 0.6190 | 0.4762 | 1.0000 | 0.6667 | 0.5238 | 0.1429 | 21 |
| 240_dn | logistic | train | 1.0000 | 1.0000 | 0.4286 | 1.0000 | 1.0000 | 0.5714 | 0.4286 | 42 |
| 240_dn | logistic | test | 0.4805 | 0.5556 | 0.6111 | 1.0000 | 0.0000 | 0.3889 | -0.3889 | 18 |
| 240_dn | gbc | train | 1.0000 | 1.0000 | 0.4286 | 1.0000 | 1.0000 | 0.5714 | 0.4286 | 42 |
| 240_dn | gbc | test | 0.5584 | 0.5556 | 0.6111 | 0.5000 | 0.5000 | -0.1111 | 0.1111 | 18 |

## Top screened features

### 15_up

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 15_close_diff_prc | 0.0456 | 0.0346 | 0.7676 |
| 15_logret | 0.0456 | 0.0346 | 0.7676 |
| 15_body_ratio | 0.0600 | 0.0465 | 0.7735 |
| 5_rsi_ma8_diff | 0.0747 | 0.0590 | 0.6960 |
| 5_cci_14 | 0.1053 | 0.0851 | 0.6693 |
| 5_rsi_ma12_diff | 0.1082 | 0.0876 | 0.6013 |
| 15_wick_up | 0.8874 | 0.8494 | 0.6569 |
| 5_logret | 0.1152 | 0.0937 | 0.6301 |
| 5_close_diff_prc | 0.1152 | 0.0937 | 0.6301 |
| 5_body_ratio | 0.1175 | 0.0956 | 0.6458 |

### 15_dn

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 15_close_diff_prc | 0.0571 | 0.0306 | 0.7680 |
| 15_logret | 0.0571 | 0.0306 | 0.7680 |
| 5_rsi_ma8_diff | 0.0582 | 0.0314 | 0.7437 |
| 15_body_ratio | 0.0622 | 0.0347 | 0.7588 |
| 5_rsi_ma12_diff | 0.0979 | 0.0642 | 0.6293 |
| 5_logret | 0.0997 | 0.0657 | 0.6479 |
| 5_close_diff_prc | 0.0997 | 0.0657 | 0.6479 |
| 5_cci_14 | 0.1003 | 0.0663 | 0.6893 |
| 5_body_ratio | 0.1157 | 0.0796 | 0.6516 |
| 60_wick_dn | 0.1207 | 0.0839 | 0.6521 |

### 60_up

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 15_close_diff_prc | 0.0324 | 0.0112 | 0.8063 |
| 15_logret | 0.0324 | 0.0112 | 0.8063 |
| 15_body_ratio | 0.0427 | 0.0182 | 0.8107 |
| 5_rsi_ma8_diff | 0.0656 | 0.0346 | 0.7368 |
| 5_logret | 0.0779 | 0.0439 | 0.6952 |
| 5_close_diff_prc | 0.0779 | 0.0439 | 0.6952 |
| 5_body_ratio | 0.1004 | 0.0612 | 0.6923 |
| 5_ema_7_minus_close | 0.8977 | 0.8472 | 0.6659 |
| 5_rsi_ma12_diff | 0.1093 | 0.0682 | 0.6747 |
| 5_cci_14 | 0.1508 | 0.1018 | 0.5738 |

### 60_dn

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 15_body_ratio | 0.0348 | 0.0065 | 0.8345 |
| 15_close_diff_prc | 0.0384 | 0.0088 | 0.8104 |
| 15_logret | 0.0384 | 0.0088 | 0.8104 |
| 5_rsi_ma8_diff | 0.0600 | 0.0232 | 0.7270 |
| 5_rsi_ma12_diff | 0.0909 | 0.0461 | 0.6811 |
| 5_ema_7_minus_close | 0.9042 | 0.8667 | 0.6712 |
| 5_logret | 0.1076 | 0.0592 | 0.6646 |
| 5_close_diff_prc | 0.1076 | 0.0592 | 0.6646 |
| 5_body_ratio | 0.1223 | 0.0710 | 0.6493 |
| 5_cci_14 | 0.1254 | 0.0735 | 0.6448 |

### 240_up

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 15_body_ratio | 0.1538 | 0.0361 | 0.5769 |
| 15_close_diff_prc | 0.1740 | 0.0497 | 0.5769 |
| 15_logret | 0.1740 | 0.0497 | 0.5769 |
| 15_move_class | 0.2070 | 0.0732 | 0.4542 |
| 1440_body_ratio | 0.2161 | 0.0800 | 0.5495 |
| 15_rsi_ma8_diff | 0.2198 | 0.0828 | 0.4927 |
| 1440_logret | 0.2216 | 0.0841 | 0.4744 |
| 1440_close_diff_prc | 0.2216 | 0.0841 | 0.4744 |
| 60_wick_up | 0.7674 | 0.6329 | 0.5018 |
| 240_macd_signal_12_26_9_slope | 0.2344 | 0.0939 | 0.4945 |

### 240_dn

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 15_rsi_ma12_diff | 0.1343 | 0.0247 | 0.6389 |
| 15_rsi_ma8_diff | 0.1366 | 0.0261 | 0.7222 |
| 15_move_class | 0.1435 | 0.0303 | 0.5972 |
| 15_rsi_ma24_diff | 0.1505 | 0.0346 | 0.5833 |
| 15_ema_7_minus_close | 0.8426 | 0.7149 | 0.5972 |
| 15_ema_14_minus_close | 0.8403 | 0.7117 | 0.6111 |
| 240_wick_dn | 0.1713 | 0.0479 | 0.5694 |
| 1440_wick_up | 0.8125 | 0.6748 | 0.5417 |
| 60_body_ratio | 0.1898 | 0.0602 | 0.6250 |
| 60_adx_14_slope | 0.1944 | 0.0634 | 0.6389 |

## Top importance

### 15_up

| feature | imp_mean | imp_std |
|---|---|---|
| 15_wick_up | 0.0272 | 0.0008 |
| 15_logret | 0.0081 | 0.0013 |
| 60_macd_signal_12_26_9_slope | 0.0020 | 0.0000 |
| 15_rsi_ma8_diff | 0.0010 | 0.0000 |
| 5_nn_rsi_ma8_norm_mean_20 | 0.0007 | 0.0002 |
| 5_wick_dn | 0.0007 | 0.0003 |
| 15_wick_dn | 0.0006 | 0.0001 |
| 15_close_diff_prc | 0.0003 | 0.0000 |
| 1440_atr_14 | 0.0001 | 0.0000 |
| 15_range_atr | 0.0001 | 0.0000 |

### 15_dn

| feature | imp_mean | imp_std |
|---|---|---|
| 15_wick_dn | 0.0444 | 0.0023 |
| 15_range_atr | 0.0024 | 0.0005 |
| 15_logret | 0.0024 | 0.0003 |
| 5_wick_up | 0.0018 | 0.0002 |
| 15_cci_14 | 0.0007 | 0.0000 |
| 240_range_atr | 0.0004 | 0.0000 |
| 5_rsi_ma8_diff | 0.0002 | 0.0000 |
| 15_wick_up | 0.0000 | 0.0000 |
| 240_adx_14 | 0.0000 | 0.0000 |
| 15_close_diff_prc | 0.0000 | 0.0000 |

### 60_up

| feature | imp_mean | imp_std |
|---|---|---|
| 15_wick_up | 0.0108 | 0.0027 |
| 15_wick_dn | 0.0013 | 0.0006 |
| 15_range_atr | 0.0010 | 0.0001 |
| 1440_ema_100_slope | 0.0000 | 0.0000 |
| 15_adx_14 | 0.0000 | 0.0000 |
| 15_close_diff_prc | 0.0000 | 0.0000 |
| 15_cci_14 | 0.0000 | 0.0000 |
| 5_logret | 0.0000 | 0.0000 |
| 5_rsi_ma12_diff | 0.0000 | 0.0000 |
| 60_macd_5_13_9_slope | 0.0000 | 0.0000 |

### 60_dn

| feature | imp_mean | imp_std |
|---|---|---|
| 15_body_ratio | 0.1029 | 0.0066 |
| 15_wick_dn | 0.0169 | 0.0033 |
| 240_vol_ma_20_minus_volume | 0.0003 | 0.0001 |
| need_speed_dn_240 | 0.0001 | 0.0000 |
| 15_adx_14_slope | 0.0000 | 0.0000 |
| 240_ema_14_minus_ema_50 | 0.0000 | 0.0000 |
| 240_macd_12_26_9 | 0.0000 | 0.0000 |
| 240_ema_50_minus_close | 0.0000 | 0.0000 |
| 1440_ema_7_minus_close | 0.0000 | 0.0000 |
| 240_rsi_ma8_slope | 0.0000 | 0.0000 |

### 240_up

| feature | imp_mean | imp_std |
|---|---|---|
| 1440_body_ratio | 0.1560 | 0.0178 |
| 15_close_diff_prc | 0.0029 | 0.0027 |
| 240_rsi_ma24_diff | 0.0000 | 0.0000 |
| 1440_rsi_ma8 | 0.0000 | 0.0000 |
| 1440_rsi_14 | 0.0000 | 0.0000 |
| 240_ZS | 0.0000 | 0.0000 |
| 240_ZB | 0.0000 | 0.0000 |
| 240_low_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_low_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_high_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |

### 240_dn

| feature | imp_mean | imp_std |
|---|---|---|
| 15_rsi_ma8_diff | 0.3269 | 0.0847 |
| 60_high_diff_prc_rm_6_std_above | 0.0051 | 0.0072 |
| 1440_rsi_ma8_diff | 0.0000 | 0.0000 |
| 1440_rsi_ma8 | 0.0000 | 0.0000 |
| 1440_rsi_14 | 0.0000 | 0.0000 |
| 240_ZS | 0.0000 | 0.0000 |
| 240_ZB | 0.0000 | 0.0000 |
| 240_low_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_low_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_high_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |

## Charts

### 15_up
- 15_up/charts/15_close_diff_prc__hist.png
- 15_up/charts/15_close_diff_prc__decile.png
- 15_up/charts/15_logret__hist.png
- 15_up/charts/15_logret__decile.png
- 15_up/charts/15_body_ratio__hist.png
- 15_up/charts/15_body_ratio__decile.png
- 15_up/charts/5_rsi_ma8_diff__hist.png
- 15_up/charts/5_rsi_ma8_diff__decile.png
- 15_up/charts/5_cci_14__hist.png
- 15_up/charts/5_cci_14__decile.png
- 15_up/charts/5_rsi_ma12_diff__hist.png
- 15_up/charts/5_rsi_ma12_diff__decile.png
- 15_up/charts/15_wick_up__hist.png
- 15_up/charts/15_wick_up__decile.png
- 15_up/charts/5_logret__hist.png
- 15_up/charts/5_logret__decile.png
- 15_up/charts/5_close_diff_prc__hist.png
- 15_up/charts/5_close_diff_prc__decile.png
- 15_up/charts/5_body_ratio__hist.png
- 15_up/charts/5_body_ratio__decile.png
- 15_up/charts/60_wick_up__hist.png
- 15_up/charts/60_wick_up__decile.png
- 15_up/charts/5_bb_upper_20_2_minus_close__hist.png
- 15_up/charts/5_bb_upper_20_2_minus_close__decile.png
- 15_up/charts/5_rsi_ma24_diff__hist.png
- 15_up/charts/5_rsi_ma24_diff__decile.png
- 15_up/charts/5_ema_7_minus_close__hist.png
- 15_up/charts/5_ema_7_minus_close__decile.png
- 15_up/charts/240_wick_up__hist.png
- 15_up/charts/240_wick_up__decile.png

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
- 15_dn/charts/5_logret__hist.png
- 15_dn/charts/5_logret__decile.png
- 15_dn/charts/5_close_diff_prc__hist.png
- 15_dn/charts/5_close_diff_prc__decile.png
- 15_dn/charts/5_cci_14__hist.png
- 15_dn/charts/5_cci_14__decile.png
- 15_dn/charts/5_body_ratio__hist.png
- 15_dn/charts/5_body_ratio__decile.png
- 15_dn/charts/60_wick_dn__hist.png
- 15_dn/charts/60_wick_dn__decile.png
- 15_dn/charts/15_wick_dn__hist.png
- 15_dn/charts/15_wick_dn__decile.png
- 15_dn/charts/5_ema_7_minus_close__hist.png
- 15_dn/charts/5_ema_7_minus_close__decile.png
- 15_dn/charts/5_cci_diff__hist.png
- 15_dn/charts/5_cci_diff__decile.png
- 15_dn/charts/5_bb_lower_20_2_minus_close__hist.png
- 15_dn/charts/5_bb_lower_20_2_minus_close__decile.png
- 15_dn/charts/5_rsi_ma24_diff__hist.png
- 15_dn/charts/5_rsi_ma24_diff__decile.png

### 60_up
- 60_up/charts/15_close_diff_prc__hist.png
- 60_up/charts/15_close_diff_prc__decile.png
- 60_up/charts/15_logret__hist.png
- 60_up/charts/15_logret__decile.png
- 60_up/charts/15_body_ratio__hist.png
- 60_up/charts/15_body_ratio__decile.png
- 60_up/charts/5_rsi_ma8_diff__hist.png
- 60_up/charts/5_rsi_ma8_diff__decile.png
- 60_up/charts/5_logret__hist.png
- 60_up/charts/5_logret__decile.png
- 60_up/charts/5_close_diff_prc__hist.png
- 60_up/charts/5_close_diff_prc__decile.png
- 60_up/charts/5_body_ratio__hist.png
- 60_up/charts/5_body_ratio__decile.png
- 60_up/charts/5_ema_7_minus_close__hist.png
- 60_up/charts/5_ema_7_minus_close__decile.png
- 60_up/charts/5_rsi_ma12_diff__hist.png
- 60_up/charts/5_rsi_ma12_diff__decile.png
- 60_up/charts/5_cci_14__hist.png
- 60_up/charts/5_cci_14__decile.png
- 60_up/charts/60_wick_up__hist.png
- 60_up/charts/60_wick_up__decile.png
- 60_up/charts/5_rsi_ma24_diff__hist.png
- 60_up/charts/5_rsi_ma24_diff__decile.png
- 60_up/charts/5_cci_diff__hist.png
- 60_up/charts/5_cci_diff__decile.png
- 60_up/charts/5_bb_upper_20_2_minus_close__hist.png
- 60_up/charts/5_bb_upper_20_2_minus_close__decile.png
- 60_up/charts/5_ema_14_minus_close__hist.png
- 60_up/charts/5_ema_14_minus_close__decile.png

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
- 60_dn/charts/5_logret__hist.png
- 60_dn/charts/5_logret__decile.png
- 60_dn/charts/5_close_diff_prc__hist.png
- 60_dn/charts/5_close_diff_prc__decile.png
- 60_dn/charts/5_body_ratio__hist.png
- 60_dn/charts/5_body_ratio__decile.png
- 60_dn/charts/5_cci_14__hist.png
- 60_dn/charts/5_cci_14__decile.png
- 60_dn/charts/60_wick_dn__hist.png
- 60_dn/charts/60_wick_dn__decile.png
- 60_dn/charts/5_rsi_ma24_diff__hist.png
- 60_dn/charts/5_rsi_ma24_diff__decile.png
- 60_dn/charts/5_bb_lower_20_2_minus_close__hist.png
- 60_dn/charts/5_bb_lower_20_2_minus_close__decile.png
- 60_dn/charts/240_wick_dn__hist.png
- 60_dn/charts/240_wick_dn__decile.png
- 60_dn/charts/5_cci_diff__hist.png
- 60_dn/charts/5_cci_diff__decile.png

### 240_up
- 240_up/charts/15_body_ratio__hist.png
- 240_up/charts/15_body_ratio__decile.png
- 240_up/charts/15_close_diff_prc__hist.png
- 240_up/charts/15_close_diff_prc__decile.png
- 240_up/charts/15_logret__hist.png
- 240_up/charts/15_logret__decile.png
- 240_up/charts/15_move_class__hist.png
- 240_up/charts/15_move_class__decile.png
- 240_up/charts/1440_body_ratio__hist.png
- 240_up/charts/1440_body_ratio__decile.png
- 240_up/charts/15_rsi_ma8_diff__hist.png
- 240_up/charts/15_rsi_ma8_diff__decile.png
- 240_up/charts/1440_logret__hist.png
- 240_up/charts/1440_logret__decile.png
- 240_up/charts/1440_close_diff_prc__hist.png
- 240_up/charts/1440_close_diff_prc__decile.png
- 240_up/charts/60_wick_up__hist.png
- 240_up/charts/60_wick_up__decile.png
- 240_up/charts/240_macd_signal_12_26_9_slope__hist.png
- 240_up/charts/240_macd_signal_12_26_9_slope__decile.png
- 240_up/charts/240_macd_hist_12_26_9__hist.png
- 240_up/charts/240_macd_hist_12_26_9__decile.png
- 240_up/charts/1440_close_diff_prc_rm_6_std_above__hist.png
- 240_up/charts/1440_close_diff_prc_rm_6_std_above__decile.png
- 240_up/charts/240_close_diff_prc_rm_6__hist.png
- 240_up/charts/240_close_diff_prc_rm_6__decile.png
- 240_up/charts/60_body_ratio__hist.png
- 240_up/charts/60_body_ratio__decile.png
- 240_up/charts/1440_wick_up__hist.png
- 240_up/charts/1440_wick_up__decile.png

### 240_dn
- 240_dn/charts/15_rsi_ma12_diff__hist.png
- 240_dn/charts/15_rsi_ma12_diff__decile.png
- 240_dn/charts/15_rsi_ma8_diff__hist.png
- 240_dn/charts/15_rsi_ma8_diff__decile.png
- 240_dn/charts/15_move_class__hist.png
- 240_dn/charts/15_move_class__decile.png
- 240_dn/charts/15_rsi_ma24_diff__hist.png
- 240_dn/charts/15_rsi_ma24_diff__decile.png
- 240_dn/charts/15_ema_7_minus_close__hist.png
- 240_dn/charts/15_ema_7_minus_close__decile.png
- 240_dn/charts/15_ema_14_minus_close__hist.png
- 240_dn/charts/15_ema_14_minus_close__decile.png
- 240_dn/charts/240_wick_dn__hist.png
- 240_dn/charts/240_wick_dn__decile.png
- 240_dn/charts/1440_wick_up__hist.png
- 240_dn/charts/1440_wick_up__decile.png
- 240_dn/charts/60_body_ratio__hist.png
- 240_dn/charts/60_body_ratio__decile.png
- 240_dn/charts/60_adx_14_slope__hist.png
- 240_dn/charts/60_adx_14_slope__decile.png
- 240_dn/charts/15_body_ratio__hist.png
- 240_dn/charts/15_body_ratio__decile.png
- 240_dn/charts/15_logret__hist.png
- 240_dn/charts/15_logret__decile.png
- 240_dn/charts/15_close_diff_prc__hist.png
- 240_dn/charts/15_close_diff_prc__decile.png
- 240_dn/charts/15_cci_14__hist.png
- 240_dn/charts/15_cci_14__decile.png
- 240_dn/charts/240_body_ratio__hist.png
- 240_dn/charts/240_body_ratio__decile.png

## Verdict

REJECTED: mean_test_auc=0.8275, best_before=0.9617, delta=-0.1342 (eps_auc=0.0050)
