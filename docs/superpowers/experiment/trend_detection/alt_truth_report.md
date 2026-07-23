# Truth decomposition report

Same points (move_class_sym0 +-2), same combos, same models/split -- only the TRUTH DEFINITION varies: 'strict' (profit_strict, existing mark_truth), 'plain' (race + pessimistic entry fill, no clean-entry gate), 'fwd' (pure realized forward direction, zero label mechanics). Each is shown against both the full feature set and the shape-excluded ('noshape', tdlib.diag) one.

## Headline: gbc test AUC (n) per combo x truth_kind x feature_set

| combo | strict_full | strict_noshape | plain_full | plain_noshape | fwd_full | fwd_noshape |
|---|---|---|---|---|---|---|
| 15_up | 0.9412 (n=370) | 0.9165 (n=370) | 0.5588 (n=1084) | 0.5119 (n=1084) | 0.5067 (n=3120) | 0.5040 (n=3120) |
| 15_dn | 0.9642 (n=369) | 0.9495 (n=369) | 0.5809 (n=1171) | 0.5075 (n=1171) | 0.5388 (n=3122) | 0.5407 (n=3122) |
| 60_up | 0.9401 (n=61) | 0.8802 (n=61) | 0.4768 (n=183) | 0.4842 (n=183) | 0.4979 (n=764) | 0.5201 (n=764) |
| 60_dn | 0.9722 (n=66) | 0.9463 (n=66) | 0.4774 (n=181) | 0.4740 (n=181) | 0.5377 (n=770) | 0.5359 (n=770) |

## Interpretation (full feature set)

label_share = strict_full - plain_full (clean-entry gate's own contribution); entry_fill_share = plain_full - fwd_full (race+fill mechanics, minus that gate); future_share = fwd_full - 0.5 (genuine forward-looking separation left over).

- 15_up: label_share=+0.3825, entry_fill_share=+0.0521, future_share=+0.0067
- 15_dn: label_share=+0.3833, entry_fill_share=+0.0420, future_share=+0.0388
- 60_up: label_share=+0.4633, entry_fill_share=-0.0211, future_share=-0.0021
- 60_dn: label_share=+0.4947, entry_fill_share=-0.0603, future_share=+0.0377

## 15_up

### plain

#### full

Top screened features (train-side):

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 5_wick_up | 0.4120 | 0.3899 | 0.1434 |
| 60_wick_up | 0.4151 | 0.3929 | 0.1310 |
| 15_wick_up | 0.4151 | 0.3929 | 0.1315 |
| 15_body_ratio | 0.5771 | 0.5550 | 0.1221 |
| 5_body_ratio | 0.5685 | 0.5462 | 0.1217 |
| 15_close_diff_prc | 0.5609 | 0.5386 | 0.0992 |
| 15_logret | 0.5609 | 0.5386 | 0.0992 |
| 240_wick_up | 0.4402 | 0.4178 | 0.0986 |
| 5_logret | 0.5548 | 0.5324 | 0.0935 |
| 5_close_diff_prc | 0.5548 | 0.5324 | 0.0935 |

Top importance (train-side):

| feature | imp_mean | imp_std |
|---|---|---|
| 5_wick_up | 0.0302 | 0.0035 |
| 240_adx_14 | 0.0112 | 0.0016 |
| 60_body_ratio | 0.0104 | 0.0008 |
| 15_sin_tod | 0.0082 | 0.0010 |
| 60_adx_14 | 0.0064 | 0.0008 |
| need_speed_up_60 | 0.0062 | 0.0006 |
| 5_bb_upper_20_2_minus_close | 0.0060 | 0.0008 |
| 5_rsi_ma8_diff | 0.0059 | 0.0005 |
| 5_vol_ma_20_minus_volume | 0.0057 | 0.0004 |
| 15_close_diff_prc_rm_6_std_below | 0.0056 | 0.0009 |

#### noshape

Top screened features (train-side):

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 5_rsi_ma8_diff | 0.5540 | 0.5317 | 0.0896 |
| time_in_candle_60 | 0.5497 | 0.5274 | 0.0845 |
| time_left_60 | 0.4503 | 0.4278 | 0.0845 |
| 5_rsi_ma12_diff | 0.5470 | 0.5246 | 0.0738 |
| 5_bb_upper_20_2_minus_close | 0.4554 | 0.4329 | 0.0763 |
| 5_cci_diff | 0.5420 | 0.5196 | 0.0773 |
| 240_low_diff_prc_rm_6 | 0.4645 | 0.4420 | 0.0638 |
| 5_rsi_ma24_diff | 0.5351 | 0.5127 | 0.0649 |
| 5_macd_signal_12_26_9_slope | 0.4654 | 0.4429 | 0.0702 |
| 5_cci_14 | 0.5308 | 0.5084 | 0.0646 |

Top importance (train-side):

| feature | imp_mean | imp_std |
|---|---|---|
| 5_rsi_ma8_diff | 0.0305 | 0.0014 |
| 5_bb_upper_20_2_minus_close | 0.0134 | 0.0023 |
| 240_adx_14 | 0.0108 | 0.0013 |
| 60_close_diff_prc_rm_6 | 0.0108 | 0.0016 |
| need_speed_up_60 | 0.0095 | 0.0007 |
| 15_sin_tod | 0.0089 | 0.0010 |
| need_speed_dn_60 | 0.0088 | 0.0012 |
| 60_close_diff_prc_rm_6_std_below | 0.0073 | 0.0010 |
| 5_cci_14_ma_5 | 0.0060 | 0.0006 |
| 5_rsi_ma12_diff | 0.0055 | 0.0011 |

### fwd

#### full

Top screened features (train-side):

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| swing_dist_lo_60_20 | 0.4759 | 0.4626 | 0.0437 |
| 240_rsi_ma8_slope | 0.4818 | 0.4686 | 0.0323 |
| 240_low_diff_prc_rm_6 | 0.4829 | 0.4697 | 0.0368 |
| bb_dist_dn_60 | 0.4830 | 0.4698 | 0.0411 |
| 240_macd_12_26_9_slope | 0.4833 | 0.4701 | 0.0346 |
| 240_macd_signal_5_13_9_slope | 0.4835 | 0.4703 | 0.0315 |
| 240_rsi_ma12_diff | 0.4838 | 0.4706 | 0.0329 |
| swing_dist_lo_60_50 | 0.4839 | 0.4706 | 0.0325 |
| htf_move_240 | 0.4840 | 0.4707 | 0.0288 |
| 240_macd_5_13_9_slope | 0.4844 | 0.4711 | 0.0329 |

Top importance (train-side):

| feature | imp_mean | imp_std |
|---|---|---|
| 5_ema_100_minus_close | 0.0400 | 0.0022 |
| 15_ema_25_minus_close | 0.0221 | 0.0020 |
| swing_dist_hi_15_50 | 0.0152 | 0.0007 |
| need_speed_up_60 | 0.0143 | 0.0012 |
| 5_vol_ma_20_minus_volume | 0.0136 | 0.0012 |
| need_speed_dn_60 | 0.0122 | 0.0010 |
| 240_close_diff_prc_rm_6_std_below | 0.0120 | 0.0007 |
| 60_ema_25_slope | 0.0113 | 0.0007 |
| 5_wick_up | 0.0111 | 0.0008 |
| 240_adx_14_slope | 0.0107 | 0.0008 |

#### noshape

Top screened features (train-side):

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| swing_dist_lo_60_20 | 0.4759 | 0.4626 | 0.0437 |
| 240_rsi_ma8_slope | 0.4818 | 0.4686 | 0.0323 |
| 240_low_diff_prc_rm_6 | 0.4829 | 0.4697 | 0.0368 |
| bb_dist_dn_60 | 0.4830 | 0.4698 | 0.0411 |
| 240_macd_12_26_9_slope | 0.4833 | 0.4701 | 0.0346 |
| 240_macd_signal_5_13_9_slope | 0.4835 | 0.4703 | 0.0315 |
| 240_rsi_ma12_diff | 0.4838 | 0.4706 | 0.0329 |
| swing_dist_lo_60_50 | 0.4839 | 0.4706 | 0.0325 |
| htf_move_240 | 0.4840 | 0.4707 | 0.0288 |
| 240_macd_5_13_9_slope | 0.4844 | 0.4711 | 0.0329 |

Top importance (train-side):

| feature | imp_mean | imp_std |
|---|---|---|
| swing_dist_hi_15_50 | 0.0266 | 0.0018 |
| 5_ema_100_minus_close | 0.0171 | 0.0011 |
| 5_vol_ma_20_minus_volume | 0.0156 | 0.0015 |
| need_speed_dn_60 | 0.0133 | 0.0017 |
| need_speed_up_60 | 0.0122 | 0.0010 |
| 5_cci_14_ma_5 | 0.0120 | 0.0012 |
| 15_macd_12_26_9_slope | 0.0111 | 0.0017 |
| 5_adx_14 | 0.0109 | 0.0006 |
| 240_adx_14_slope | 0.0108 | 0.0012 |
| 60_ema_25_slope | 0.0100 | 0.0014 |

## 15_dn

### plain

#### full

Top screened features (train-side):

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 5_range_atr | 0.5557 | 0.5341 | 0.1032 |
| 5_low_diff_prc_rm_6 | 0.4513 | 0.4298 | 0.0760 |
| 5_wick_dn | 0.5480 | 0.5264 | 0.0782 |
| 5_vol_ma_20_minus_volume | 0.4540 | 0.4325 | 0.0793 |
| 15_vol_ma_20_minus_volume | 0.4593 | 0.4377 | 0.0805 |
| 15_wick_dn | 0.5388 | 0.5172 | 0.0642 |
| 15_range_atr | 0.5379 | 0.5162 | 0.0659 |
| 5_close_diff_prc_rm_6 | 0.4624 | 0.4408 | 0.0757 |
| 5_wick_up | 0.4633 | 0.4417 | 0.0715 |
| 60_wick_dn | 0.5363 | 0.5146 | 0.0648 |

Top importance (train-side):

| feature | imp_mean | imp_std |
|---|---|---|
| 60_natr_14 | 0.0187 | 0.0020 |
| 15_close_diff_prc_rm_6_std_above | 0.0171 | 0.0017 |
| 5_range_atr | 0.0110 | 0.0015 |
| 5_wick_dn | 0.0091 | 0.0011 |
| 5_body_ratio | 0.0087 | 0.0007 |
| swing_dist_lo_15_50 | 0.0083 | 0.0006 |
| 1440_wick_dn | 0.0081 | 0.0010 |
| 240_vol_ma_20_minus_volume | 0.0067 | 0.0004 |
| 1440_wick_up | 0.0067 | 0.0008 |
| 1440_close_diff_prc_rm_6_std_above | 0.0061 | 0.0004 |

#### noshape

Top screened features (train-side):

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 5_low_diff_prc_rm_6 | 0.4513 | 0.4298 | 0.0760 |
| 5_vol_ma_20_minus_volume | 0.4540 | 0.4325 | 0.0793 |
| 15_vol_ma_20_minus_volume | 0.4593 | 0.4377 | 0.0805 |
| 5_close_diff_prc_rm_6 | 0.4624 | 0.4408 | 0.0757 |
| 15_bb_lower_20_2_minus_close | 0.5356 | 0.5139 | 0.0919 |
| 15_rsi_ma8_diff | 0.4683 | 0.4467 | 0.0797 |
| 60_macd_5_13_9_slope | 0.4699 | 0.4483 | 0.0576 |
| 1440_close_diff_prc_rm_6_std_above | 0.5292 | 0.5075 | 0.0598 |
| 15_rsi_ma12_diff | 0.4708 | 0.4492 | 0.0782 |
| 5_close_diff_prc_rm_6_std_above | 0.5288 | 0.5071 | 0.0600 |

Top importance (train-side):

| feature | imp_mean | imp_std |
|---|---|---|
| 15_close_diff_prc_rm_6_std_above | 0.0270 | 0.0026 |
| 60_natr_14 | 0.0176 | 0.0016 |
| swing_dist_lo_15_50 | 0.0126 | 0.0007 |
| 5_low_diff_prc_rm_6 | 0.0118 | 0.0009 |
| 1440_close_diff_prc_rm_6_std_above | 0.0091 | 0.0009 |
| 15_rsi_ma8_diff | 0.0086 | 0.0011 |
| 240_nn_rsi_ma8_norm_mean_20 | 0.0076 | 0.0005 |
| 15_rsi_ma12_diff | 0.0074 | 0.0013 |
| 15_macd_5_13_9_slope | 0.0072 | 0.0007 |
| 15_ema_50_minus_close | 0.0061 | 0.0004 |

### fwd

#### full

Top screened features (train-side):

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 5_rsi_14 | 0.4622 | 0.4488 | 0.0600 |
| swing_dist_hi_15_50 | 0.5335 | 0.5203 | 0.0596 |
| bb_dist_up_15 | 0.5334 | 0.5202 | 0.0595 |
| 240_cci_diff | 0.4666 | 0.4533 | 0.0628 |
| 60_rsi_ma24_diff | 0.4668 | 0.4535 | 0.0526 |
| 60_macd_hist_12_26_9 | 0.4677 | 0.4544 | 0.0538 |
| 60_rsi_ma12_diff | 0.4679 | 0.4546 | 0.0552 |
| 60_macd_12_26_9_slope | 0.4687 | 0.4554 | 0.0532 |
| 15_rsi_14 | 0.4688 | 0.4554 | 0.0572 |
| 5_bb_lower_20_2_minus_close | 0.5308 | 0.5176 | 0.0533 |

Top importance (train-side):

| feature | imp_mean | imp_std |
|---|---|---|
| 1440_atr_14_ma_5 | 0.0145 | 0.0016 |
| 5_macd_5_13_9_slope | 0.0142 | 0.0019 |
| 5_cci_14_ma_5 | 0.0125 | 0.0011 |
| 60_natr_14 | 0.0110 | 0.0016 |
| 240_atr_14_ma_5 | 0.0097 | 0.0012 |
| 1440_cci_diff | 0.0096 | 0.0009 |
| 5_rsi_ma12_diff | 0.0093 | 0.0006 |
| 15_close_diff_prc_rm_6_std_above | 0.0086 | 0.0006 |
| 240_wick_up | 0.0085 | 0.0007 |
| 5_adx_14_slope | 0.0078 | 0.0010 |

#### noshape

Top screened features (train-side):

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 5_rsi_14 | 0.4622 | 0.4488 | 0.0600 |
| swing_dist_hi_15_50 | 0.5335 | 0.5203 | 0.0596 |
| bb_dist_up_15 | 0.5334 | 0.5202 | 0.0595 |
| 240_cci_diff | 0.4666 | 0.4533 | 0.0628 |
| 60_rsi_ma24_diff | 0.4668 | 0.4535 | 0.0526 |
| 60_macd_hist_12_26_9 | 0.4677 | 0.4544 | 0.0538 |
| 60_rsi_ma12_diff | 0.4679 | 0.4546 | 0.0552 |
| 60_macd_12_26_9_slope | 0.4687 | 0.4554 | 0.0532 |
| 15_rsi_14 | 0.4688 | 0.4554 | 0.0572 |
| 5_bb_lower_20_2_minus_close | 0.5308 | 0.5176 | 0.0533 |

Top importance (train-side):

| feature | imp_mean | imp_std |
|---|---|---|
| 5_macd_5_13_9_slope | 0.0192 | 0.0021 |
| 60_natr_14_ma_5 | 0.0185 | 0.0024 |
| 60_natr_14 | 0.0155 | 0.0018 |
| 5_rsi_ma12_diff | 0.0130 | 0.0010 |
| 1440_cci_diff | 0.0123 | 0.0016 |
| 5_cci_14_ma_5 | 0.0116 | 0.0012 |
| 15_close_diff_prc_rm_6_std_above | 0.0105 | 0.0010 |
| need_speed_dn_60 | 0.0100 | 0.0007 |
| 5_macd_hist_12_26_9 | 0.0098 | 0.0006 |
| 1440_atr_14_ma_5 | 0.0093 | 0.0011 |

## 60_up

### plain

#### full

Top screened features (train-side):

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 1440_wick_dn | 0.5962 | 0.5422 | 0.1691 |
| time_in_candle_240 | 0.5884 | 0.5341 | 0.1664 |
| time_left_240 | 0.4116 | 0.3562 | 0.1664 |
| 240_wick_up | 0.4205 | 0.3649 | 0.1617 |
| 240_range_atr | 0.5761 | 0.5215 | 0.1670 |
| 60_atr_14_ma_5 | 0.4249 | 0.3693 | 0.1474 |
| 5_macd_5_13_9_slope | 0.5712 | 0.5165 | 0.1588 |
| 240_low_diff_prc_rm_6 | 0.4290 | 0.3733 | 0.1189 |
| 15_rsi_ma24_diff | 0.5699 | 0.5151 | 0.1627 |
| 1440_bb_lower_20_2_minus_close | 0.5694 | 0.5146 | 0.1794 |

Top importance (train-side):

| feature | imp_mean | imp_std |
|---|---|---|
| 240_low_diff_prc_rm_6 | 0.0000 | 0.0001 |
| 5_macd_12_26_9_slope | 0.0000 | 0.0000 |
| 1440_high_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 1440_close_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_high_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_close_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_close_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_high_diff_prc_rm_6 | 0.0000 | 0.0000 |
| 240_close_diff_prc_rm_6 | 0.0000 | 0.0000 |
| 240_close_diff_prc | 0.0000 | 0.0000 |

#### noshape

Top screened features (train-side):

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| time_in_candle_240 | 0.5884 | 0.5341 | 0.1664 |
| time_left_240 | 0.4116 | 0.3562 | 0.1664 |
| 60_atr_14_ma_5 | 0.4249 | 0.3693 | 0.1474 |
| 5_macd_5_13_9_slope | 0.5712 | 0.5165 | 0.1588 |
| 240_low_diff_prc_rm_6 | 0.4290 | 0.3733 | 0.1189 |
| 15_rsi_ma24_diff | 0.5699 | 0.5151 | 0.1627 |
| 1440_bb_lower_20_2_minus_close | 0.5694 | 0.5146 | 0.1794 |
| 60_atr_14 | 0.4309 | 0.3751 | 0.1385 |
| 1440_atr_14 | 0.4320 | 0.3763 | 0.1326 |
| 240_atr_14_ma_5 | 0.4323 | 0.3765 | 0.1229 |

Top importance (train-side):

| feature | imp_mean | imp_std |
|---|---|---|
| 240_low_diff_prc_rm_6 | 0.0000 | 0.0000 |
| 5_macd_5_13_9_slope | 0.0000 | 0.0000 |
| 1440_low_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 5_macd_12_26_9_slope | 0.0000 | 0.0000 |
| 60_high_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 60_low_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 1440_close_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_ZB | 0.0000 | 0.0000 |
| 240_low_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_high_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |

### fwd

#### full

Top screened features (train-side):

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 15_low_diff_prc_rm_6_std_above | 0.5383 | 0.5114 | 0.0817 |
| 15_low_diff_prc_rm_6_std_below | 0.5381 | 0.5112 | 0.0861 |
| 5_macd_signal_12_26_9_slope | 0.5375 | 0.5106 | 0.0751 |
| 60_adx_14_slope | 0.5373 | 0.5104 | 0.0613 |
| 15_macd_5_13_9_slope | 0.5362 | 0.5093 | 0.0670 |
| 15_high_diff_prc_rm_6_std_above | 0.5355 | 0.5086 | 0.0723 |
| 15_low_diff_prc_rm_6 | 0.5346 | 0.5078 | 0.0868 |
| 15_natr_14 | 0.5330 | 0.5061 | 0.0657 |
| 5_natr_14_ma_5 | 0.5330 | 0.5061 | 0.0702 |
| 5_ema_7_minus_ema_14 | 0.5329 | 0.5060 | 0.0606 |

Top importance (train-side):

| feature | imp_mean | imp_std |
|---|---|---|
| 15_high_diff_prc_rm_6_std_above | 0.0122 | 0.0015 |
| 5_high_diff_prc_rm_6_std_above | 0.0120 | 0.0015 |
| 15_body_ratio | 0.0098 | 0.0009 |
| 1440_close_diff_prc_rm_6_std_above | 0.0057 | 0.0007 |
| 15_low_diff_prc_rm_6 | 0.0054 | 0.0005 |
| 15_adx_14_slope | 0.0051 | 0.0008 |
| 240_close_diff_prc_rm_6_std_above | 0.0047 | 0.0008 |
| 5_rsi_ma24 | 0.0041 | 0.0002 |
| 5_low_diff_prc_rm_6_std_below | 0.0035 | 0.0010 |
| 240_wick_dn | 0.0034 | 0.0010 |

#### noshape

Top screened features (train-side):

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 15_low_diff_prc_rm_6_std_above | 0.5383 | 0.5114 | 0.0817 |
| 15_low_diff_prc_rm_6_std_below | 0.5381 | 0.5112 | 0.0861 |
| 5_macd_signal_12_26_9_slope | 0.5375 | 0.5106 | 0.0751 |
| 60_adx_14_slope | 0.5373 | 0.5104 | 0.0613 |
| 15_macd_5_13_9_slope | 0.5362 | 0.5093 | 0.0670 |
| 15_high_diff_prc_rm_6_std_above | 0.5355 | 0.5086 | 0.0723 |
| 15_low_diff_prc_rm_6 | 0.5346 | 0.5078 | 0.0868 |
| 15_natr_14 | 0.5330 | 0.5061 | 0.0657 |
| 5_natr_14_ma_5 | 0.5330 | 0.5061 | 0.0702 |
| 5_ema_7_minus_ema_14 | 0.5329 | 0.5060 | 0.0606 |

Top importance (train-side):

| feature | imp_mean | imp_std |
|---|---|---|
| 5_high_diff_prc_rm_6_std_above | 0.0105 | 0.0009 |
| 5_low_diff_prc_rm_6_std_below | 0.0099 | 0.0012 |
| 15_high_diff_prc_rm_6_std_above | 0.0082 | 0.0009 |
| 5_macd_signal_12_26_9_slope | 0.0061 | 0.0011 |
| 15_cci_diff | 0.0058 | 0.0007 |
| 15_low_diff_prc_rm_6_std_above | 0.0056 | 0.0009 |
| 5_rsi_ma24 | 0.0050 | 0.0005 |
| 5_ema_7_minus_close | 0.0044 | 0.0004 |
| 1440_close_diff_prc_rm_6_std_above | 0.0043 | 0.0009 |
| 240_high_diff_prc_rm_6_std_below | 0.0042 | 0.0006 |

## 60_dn

### plain

#### full

Top screened features (train-side):

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| swing_dist_lo_60_20 | 0.5660 | 0.5106 | 0.1385 |
| 1440_low_diff_prc_rm_6_std_above | 0.5659 | 0.5107 | 0.1361 |
| 5_high_diff_prc_rm_6_std_above | 0.4371 | 0.3823 | 0.1207 |
| 1440_cci_14_ma_5 | 0.4414 | 0.3865 | 0.1299 |
| 1440_high_diff_prc_rm_6_std_above | 0.4439 | 0.3889 | 0.1236 |
| 5_cci_diff | 0.4443 | 0.3893 | 0.1207 |
| 15_cci_14_ma_5 | 0.5542 | 0.4989 | 0.1005 |
| 60_cci_14 | 0.5531 | 0.4977 | 0.0962 |
| 5_low_diff_prc_rm_6_std_below | 0.4471 | 0.3921 | 0.1299 |
| 1440_macd_signal_12_26_9_slope | 0.4473 | 0.3923 | 0.1159 |

Top importance (train-side):

| feature | imp_mean | imp_std |
|---|---|---|
| 240_vol_ma_20_minus_volume | 0.0004 | 0.0001 |
| 60_cci_diff | 0.0003 | 0.0001 |
| 15_bb_middle_20_2_minus_close | 0.0001 | 0.0000 |
| 60_low_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 60_adx_14_slope | 0.0000 | 0.0000 |
| 15_adx_14 | 0.0000 | 0.0000 |
| 5_macd_signal_5_13_9_slope | 0.0000 | 0.0000 |
| 15_close_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |
| 240_ema_7_minus_ema_25 | 0.0000 | 0.0000 |
| 240_high_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |

#### noshape

Top screened features (train-side):

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| swing_dist_lo_60_20 | 0.5660 | 0.5106 | 0.1385 |
| 1440_low_diff_prc_rm_6_std_above | 0.5659 | 0.5107 | 0.1361 |
| 5_high_diff_prc_rm_6_std_above | 0.4371 | 0.3823 | 0.1207 |
| 1440_cci_14_ma_5 | 0.4414 | 0.3865 | 0.1299 |
| 1440_high_diff_prc_rm_6_std_above | 0.4439 | 0.3889 | 0.1236 |
| 5_cci_diff | 0.4443 | 0.3893 | 0.1207 |
| 15_cci_14_ma_5 | 0.5542 | 0.4989 | 0.1005 |
| 60_cci_14 | 0.5531 | 0.4977 | 0.0962 |
| 5_low_diff_prc_rm_6_std_below | 0.4471 | 0.3921 | 0.1299 |
| 1440_macd_signal_12_26_9_slope | 0.4473 | 0.3923 | 0.1159 |

Top importance (train-side):

| feature | imp_mean | imp_std |
|---|---|---|
| 60_cci_diff | 0.0019 | 0.0008 |
| 15_bb_middle_20_2_minus_close | 0.0002 | 0.0001 |
| 5_low_diff_prc_rm_6_std_below | 0.0001 | 0.0000 |
| 60_adx_14_slope | 0.0001 | 0.0001 |
| 240_vol_ma_20_minus_volume | 0.0000 | 0.0000 |
| 5_macd_signal_5_13_9_slope | 0.0000 | 0.0000 |
| 15_low_diff_prc_rm_6 | 0.0000 | 0.0000 |
| 60_close_diff_prc_rm_6_std_above | 0.0000 | 0.0000 |
| 240_ZB | 0.0000 | 0.0000 |
| 240_low_diff_prc_rm_6_std_below | 0.0000 | 0.0000 |

### fwd

#### full

Top screened features (train-side):

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 5_cci_14 | 0.4507 | 0.4235 | 0.0861 |
| bb_dist_up_240 | 0.5382 | 0.5112 | 0.0745 |
| 60_wick_dn | 0.4626 | 0.4354 | 0.0634 |
| 5_bb_lower_20_2_minus_close | 0.5373 | 0.5103 | 0.0902 |
| 5_rsi_ma12_diff | 0.4634 | 0.4362 | 0.0713 |
| 5_ema_14_minus_close | 0.5357 | 0.5088 | 0.0705 |
| 5_rsi_ma8_diff | 0.4644 | 0.4372 | 0.0751 |
| 5_ema_7_minus_close | 0.5355 | 0.5085 | 0.0763 |
| 5_close_diff_prc_rm_6 | 0.4650 | 0.4378 | 0.0663 |
| 5_high_diff_prc_rm_6 | 0.4651 | 0.4379 | 0.0787 |

Top importance (train-side):

| feature | imp_mean | imp_std |
|---|---|---|
| 60_low_diff_prc_rm_6_std_above | 0.0145 | 0.0010 |
| 5_macd_12_26_9_slope | 0.0097 | 0.0008 |
| 15_close_diff_prc_rm_6_std_above | 0.0096 | 0.0015 |
| 15_cci_diff | 0.0072 | 0.0015 |
| 60_close_diff_prc_rm_6_std_above | 0.0062 | 0.0020 |
| 5_body_ratio | 0.0057 | 0.0010 |
| 60_adx_14 | 0.0055 | 0.0007 |
| 240_close_diff_prc_rm_6_std_above | 0.0050 | 0.0006 |
| 5_high_diff_prc_rm_6_std_below | 0.0050 | 0.0005 |
| 1440_body_ratio | 0.0049 | 0.0012 |

#### noshape

Top screened features (train-side):

| feature | auc | auc_low95 | ks |
|---|---|---|---|
| 5_cci_14 | 0.4507 | 0.4235 | 0.0861 |
| bb_dist_up_240 | 0.5382 | 0.5112 | 0.0745 |
| 5_bb_lower_20_2_minus_close | 0.5373 | 0.5103 | 0.0902 |
| 5_rsi_ma12_diff | 0.4634 | 0.4362 | 0.0713 |
| 5_ema_14_minus_close | 0.5357 | 0.5088 | 0.0705 |
| 5_rsi_ma8_diff | 0.4644 | 0.4372 | 0.0751 |
| 5_ema_7_minus_close | 0.5355 | 0.5085 | 0.0763 |
| 5_close_diff_prc_rm_6 | 0.4650 | 0.4378 | 0.0663 |
| 5_high_diff_prc_rm_6 | 0.4651 | 0.4379 | 0.0787 |
| 15_ema_7_minus_close | 0.5344 | 0.5074 | 0.0712 |

Top importance (train-side):

| feature | imp_mean | imp_std |
|---|---|---|
| 60_low_diff_prc_rm_6_std_above | 0.0127 | 0.0014 |
| 5_macd_12_26_9_slope | 0.0118 | 0.0005 |
| 15_close_diff_prc_rm_6_std_above | 0.0097 | 0.0007 |
| 5_high_diff_prc_rm_6_std_below | 0.0076 | 0.0007 |
| 15_sin_tod | 0.0065 | 0.0011 |
| 5_close_diff_prc_rm_6_std_above | 0.0061 | 0.0004 |
| 240_low_diff_prc_rm_6_std_above | 0.0059 | 0.0005 |
| 60_adx_14 | 0.0055 | 0.0014 |
| 15_cci_diff | 0.0052 | 0.0010 |
| 60_close_diff_prc_rm_6_std_above | 0.0051 | 0.0016 |
