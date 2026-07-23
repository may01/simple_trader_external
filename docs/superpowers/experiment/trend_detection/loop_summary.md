# Improvement loop summary

## Iteration history

| iter | transform | horizon | mean_test_auc | status |
|---|---|---|---|---|
| 01 | baseline | n1 | 0.9544 | kept |
| 02 | prune_top40 | n1 | 0.9617 | kept |
| 03 | interact_time_left | n1 | 0.9387 | rejected |
| 04 | horizon_n2 | n2 | 0.8275 | rejected |

## Best iteration: 02 (prune_top40, horizon=n1)

| combo | model | roc_auc | acc | lift_long | lift_short | n |
|---|---|---|---|---|---|---|
| 15_up | logistic | 0.9540 | 0.9351 | 0.7054 | 0.1324 | 370 |
| 15_up | gbc | 0.9411 | 0.9216 | 0.6243 | 0.1324 | 370 |
| 15_dn | logistic | 0.9695 | 0.9702 | 0.1084 | 0.7565 | 369 |
| 15_dn | gbc | 0.9706 | 0.9702 | 0.1084 | 0.7835 | 369 |
| 60_up | logistic | 0.9793 | 0.8852 | 0.5574 | 0.4426 | 61 |
| 60_up | gbc | 0.9967 | 0.9672 | 0.5574 | 0.4426 | 61 |
| 60_dn | logistic | 0.9424 | 0.8636 | 0.3788 | 0.6212 | 66 |
| 60_dn | gbc | 0.9385 | 0.9394 | 0.3788 | 0.6212 | 66 |
