Inputs:
high low bounds for 15, 60 240 tf are calculated providing the expected values of high low of the candle

Goal:
define the zone in this bound that statistically provides the most amount of profitable points. do it separately for long and short points.
This zones should be selected by defining shift on the bound that will move bound to more desired position. This coeffitien shoul dbe selected per rsi move class. So that points that fall into the open zone will have maximum amount of points that are marked by strict label. Keeping the overall amount of point amount as big as possible. The target bound should be at the level, that provides reaching probability according amount of profitable(label==1) and loose(label==0) points in the zone.     

Steps:
- for each time frame [15,60,240]
- for each rsi move class [-3,-2.-1, 0, 1, 2, 3]
- for long/short: select open bound
- move open bound by some amount == bound_shift_coeff (amount can be measured in tf atr, or the distance between low high bound, other measuring approaches can be considered if there are relevant proposes), move can be done in both directions up(positive shift) or down(negative shift)
- calculate amount of profitable and lose points in the bound
- select bound that provides biggest amount of points, with best ratio between profit and loss points (try both strict and non strict labels for profitable points
)
-based on the ratio of profit/loss points, select the target bound for closing position. It should be shifted in the same manner as the open bound. and provide probability of reaching the bound that corresponds risk/reward ratio
- perform this actions for both long and short bounds
- save thebounds
- save the calculated values, provide table of open bound shifts that were tested, 
- provide the probabilities of reaching the target bound for each class

Results:
- save best parameters for bounds shift as separate artifact file that can be later be reused for strategy
- calculate bound on 2y dataframe, mark 1min candles which entered the open/close zone
- calculate bounds on 2month oos dataframe, mark 1min candles which entered the open/close zone, same as cb_long/short_tf markers on full view
- update full view to show new zone markers

Constraints:
- perform experiment in separate branch
- select branch with bounds experiment as a base branch to run the experiment
- do not commit any results, before report will be approved. 
- use 2y dataset for training 
- use 2m oos dataset for validation
- analyze task and ask unclear questions before starting the experiment
