# Diagnostic report -- per-candle geometry excluded

Candle-k's OWN shape/geometry (logret, close/high/low_diff_prc, body_ratio, wick_up/dn, range_atr -- see diag.SHAPE_SUFFIXES) is excluded from the feature set entirely; the _rm_6* backward-smoothed rolling family stays IN (see the module docstring's judgment call). Compares this run's gbc test AUC against the ORIGINAL loop's iter_01 (baseline, full feature set, horizon=n1) gbc test AUC, per combo -- how much residual separation survives once the profit_strict labels' candle-interior fingerprint is no longer directly observable.

## Headline: baseline (iter_01) vs diag, gbc test AUC

| combo | baseline_test_auc | diag_test_auc | delta | interpretation |
|---|---|---|---|---|
| 15_up | 0.9412 | 0.9165 | -0.0247 | strong |
| 15_dn | 0.9642 | 0.9495 | -0.0147 | strong |
| 60_up | 0.9401 | 0.8802 | -0.0599 | strong |
| 60_dn | 0.9722 | 0.9463 | -0.0259 | strong |

## 15_up

### Top screened features (diag, train-side)

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 5_rsi_ma8_diff | 0.0705 | 0.0517 | 0.7342 |
| 5_cci_14 | 0.0879 | 0.0660 | 0.7253 |
| 5_rsi_ma12_diff | 0.0985 | 0.0747 | 0.6438 |
| 5_bb_upper_20_2_minus_close | 0.8698 | 0.8206 | 0.5986 |
| 5_rsi_ma24_diff | 0.1622 | 0.1282 | 0.5485 |
| 5_ema_7_minus_close | 0.8153 | 0.7592 | 0.4852 |
| 5_cci_diff | 0.2003 | 0.1610 | 0.4982 |
| 15_rsi_ma8_slope | 0.7219 | 0.6588 | 0.3825 |
| swing_dist_hi_15_20 | 0.6941 | 0.6298 | 0.4684 |
| 15_rsi_ma8_diff | 0.3072 | 0.2556 | 0.3045 |

### Top importance (diag, train-side)

| feature | imp_mean | imp_std |
|---|---|---|
| 5_rsi_ma8_diff | 0.0762 | 0.0030 |
| 5_cci_14 | 0.0116 | 0.0019 |
| 1440_cci_14_ma_5 | 0.0025 | 0.0000 |
| 5_cci_14_ma_5 | 0.0017 | 0.0003 |
| 5_rsi_ma8_slope | 0.0011 | 0.0006 |
| 15_ema_25_minus_close | 0.0000 | 0.0000 |
| 1440_rsi_ma8_slope | 0.0000 | 0.0000 |
| 5_cci_diff | 0.0000 | 0.0000 |
| 60_macd_hist_12_26_9 | 0.0000 | 0.0000 |
| 5_ema_100_slope | 0.0000 | 0.0000 |

## 15_dn

### Top screened features (diag, train-side)

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 5_rsi_ma8_diff | 0.0468 | 0.0168 | 0.7900 |
| 5_rsi_ma12_diff | 0.0816 | 0.0429 | 0.6898 |
| 5_cci_14 | 0.0856 | 0.0461 | 0.7364 |
| 5_ema_7_minus_close | 0.8661 | 0.8373 | 0.5548 |
| 5_bb_lower_20_2_minus_close | 0.8515 | 0.8204 | 0.6435 |
| 5_cci_diff | 0.1542 | 0.1039 | 0.5799 |
| 5_rsi_ma24_diff | 0.1625 | 0.1112 | 0.5139 |
| 5_vol_ma_20_minus_volume | 0.2131 | 0.1568 | 0.4765 |
| 5_macd_5_13_9_slope | 0.2346 | 0.1767 | 0.4165 |
| 15_rsi_ma8_slope | 0.7618 | 0.7191 | 0.4438 |

### Top importance (diag, train-side)

| feature | imp_mean | imp_std |
|---|---|---|
| 5_rsi_ma8_diff | 0.1488 | 0.0121 |
| 5_ema_7_minus_close | 0.0027 | 0.0009 |
| 1440_cci_diff | 0.0007 | 0.0000 |
| 5_rsi_ma8_slope | 0.0005 | 0.0002 |
| 5_bb_lower_20_2_minus_close | 0.0001 | 0.0001 |
| 1440_close_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 1440_ema_7_minus_close | 0.0000 | 0.0000 |
| 1440_zone_class | 0.0000 | 0.0000 |
| 1440_nn_rsi_ma8_norm_mean_20 | 0.0000 | 0.0000 |
| 1440_rsi_ma24_diff | 0.0000 | 0.0000 |

## 60_up

### Top screened features (diag, train-side)

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 5_rsi_ma8_diff | 0.0763 | 0.0335 | 0.6759 |
| 5_ema_7_minus_close | 0.8989 | 0.8387 | 0.6328 |
| 5_rsi_ma12_diff | 0.1248 | 0.0691 | 0.6132 |
| 5_cci_diff | 0.1758 | 0.1092 | 0.5426 |
| 5_cci_14 | 0.1881 | 0.1191 | 0.5613 |
| 5_rsi_ma24_diff | 0.1965 | 0.1260 | 0.4956 |
| 5_ema_14_minus_close | 0.7931 | 0.7113 | 0.4618 |
| 5_bb_upper_20_2_minus_close | 0.7600 | 0.6735 | 0.4695 |
| 5_close_diff_prc_rm_6 | 0.2521 | 0.1726 | 0.3991 |
| 15_rsi_ma8_diff | 0.2633 | 0.1822 | 0.3521 |

### Top importance (diag, train-side)

| feature | imp_mean | imp_std |
|---|---|---|
| 5_rsi_ma8_diff | 0.2046 | 0.0438 |
| 240_ZS | 0.0000 | 0.0000 |
| 240_ZB | 0.0000 | 0.0000 |
| 240_low_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_low_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_high_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_high_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_close_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_close_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_low_diff_prc_rm_6 | 0.0000 | 0.0000 |

## 60_dn

### Top screened features (diag, train-side)

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 5_rsi_ma8_diff | 0.0491 | 0.0096 | 0.7663 |
| 5_rsi_ma12_diff | 0.0823 | 0.0316 | 0.7284 |
| 5_ema_7_minus_close | 0.9039 | 0.8570 | 0.7074 |
| 5_cci_14 | 0.1239 | 0.0626 | 0.6840 |
| 5_rsi_ma24_diff | 0.1461 | 0.0800 | 0.5901 |
| 5_bb_lower_20_2_minus_close | 0.8388 | 0.7775 | 0.6035 |
| 5_cci_diff | 0.1713 | 0.1005 | 0.5840 |
| 5_rsi_14 | 0.1961 | 0.1213 | 0.5035 |
| 5_macd_5_13_9_slope | 0.2096 | 0.1328 | 0.5128 |
| 15_rsi_ma8_diff | 0.2252 | 0.1462 | 0.4596 |

### Top importance (diag, train-side)

| feature | imp_mean | imp_std |
|---|---|---|
| 5_rsi_ma8_diff | 0.1858 | 0.0270 |
| 240_vol_ma_20_minus_volume | 0.0009 | 0.0005 |
| 240_rsi_ma8_slope | 0.0001 | 0.0001 |
| 240_ZS | 0.0000 | 0.0000 |
| 240_ZB | 0.0000 | 0.0000 |
| 240_low_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_low_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_high_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_high_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_close_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
