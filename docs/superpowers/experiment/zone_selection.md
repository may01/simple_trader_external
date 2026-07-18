# Porpoise:
Define on 1 min timeframe data zones that will identify the best 1 min candles to buy or sell asset based on bounds for higher timeframe candles.

# Rationale and algorithm description

The price always lands between high and low values of the candle. If we will estimate the high and low value of the next candle we can predict the range in which the price will most likely land. Defining the upper and lower bound of the candle. Based on this higher and lower bound a zone for buy and sell can be selected for this candle

## Bound selection

### 1. Defining basic values 
For high and low prices of the candle we can calculate the percentage change of the price relative to a previous candle (diff_prc). Then the moving average (diff_prc_ma) for the diff_prc provides us the average value of the price change during last N candles. 

### 2. Next value prediction 
Considering that the average price will not change a lot, we can interpolate the next diff_prc_ma value, and calculate what diff_prc should be to satisfy next next diff_prc_ma value.

### 3. Deviation 
The standard deviation (std) of diff_prc from diff_prc_ma can be calculated. This deviation will provide us probabilities of how likely the price will get to this level. It's important to remember that for high bound, diff_prc_ma - std is much more likely then high_diff_prc_ma+high_std. Because high_diff_prc_ma - high_std is much more closer to the center of the candle, The same logic is valid for lower bound with an opposite operation low_diff_prc_ma+low_std much more likely then low_diff_prc_ma-low_std

### 4. Action levels
Based on the deviation from mean value, 4 action levels are defined
1. target long =  tgt_long
2. stop loss long = sl_long
3. target short =  tgt_short
4. stop loss long = sl_short

Each level should be selected as level = diff_pc_ma +- X * std

Maximum value of X considered 2.0. 
So:
 - the lowest level we considering is low_diff_pc_ma - 2.0 * std
 - the highest level we considering is high_diff_pc_ma + 2.0 * std

The stretch between highest and lowest value will be called levels space. Level space will be defined as coeffitient between 0 (lowest level) and 1 (highest level). All values that are out of this spaced clamped to 0 or 1. 
 
Reference to goal 1

### 5. Risk / Reward
By selecting probabilities of SL (risk) and Target (reward). We can get risk reward ratio = R/R.
R/R ration should be aligned against candle size including operations fees. (fees should be parametrized during experiment)

R/R ration should be separate for long and short operations.

Reference to goal 2


### 6. Market condition challenge
diff_prc_ma and std are changing with market condition. For bull market long is more prefered and R/R should be in favor of long operation, and vise versa for bear market and short operation.

To resolve the challenge the proposal is to use trend indicators and labeled data to select correct values X for action levels from section 4.

Reference to goal 3

### 7. Trend indicators

For each indicator such values are specified:
 - position
 - slope
 - distance (optional)
 Each indicator value should be normalized by z-score principle and value clamped in range [-3, +3].

 Reference to goal 3: The experiment should search for correlation between indicator value and probability of profitable points

#### 7.1 RSI
- position = position of rsi_ma in rsi space [0; 100]
- slope = rsi_ma difference to previous value
- distance = distance of rsi value from rsi_ma 
#### 7.2 MACD
- position = position of macd 
- slope = macd difference to previous value
- distance = macd_hist 

#### 7.3 MA
- position = position of ema against price calculated in percentage of the price
- slope = ema difference to previous ema value 

### 8. Labels
Algorithms should use strict labels points as profitable points to calculate statistics.
The labels should parametrized at the start of experiment. To provide capability to find relation between 15 min profit labels with 240 tf candles and indicators.

For each strict point calculate coefficient of it's position in the action space (label_coeff).  

### 9. Indicators to labels classification

To find dependencies select all rows whitch are marked with lebles and 
plot indicator group  against the label_coeff and save the plot for further investigation.
#### Indicator group
There can be 1, 2 or 3 dimensional dependency.
##### 1 dimension
Search dependency for each trend indicator value against label_coeff.
Example: One dependency for
 - plot RSI(position) / label_coeff
 - plot RSI(slope) / label_coeff
 - plot RSI(distance) / label_coeff
 same for MACD and MA

##### 2 dimension
  Search dependency for pair of trend indicator value against label_coeff. trend indicator should be from one space RSI+RSI+label_coeff. No mixig (RSI+MACD+label_coeff)
Example: 
 - plot RSI(position) / RSI(slope) / label_coeff
 
##### 3 dimension
  Do not plot, but try to calculate regression and classification

#### 9.1 Regression
Propose a set of regressions get function that will provide the best mean value and std for label_coeff against indicator group. This can be linear and non linear regression separately for each indicators group. Run the regression. Plot the results on the chart and save it for each indicators group separately.

##### 9.1.2 Results
For each checked regression save all parameters and results values to separate report file to be capable to reproduce  results. Also make a chart with the regression function, and points of data with label=1 and points of data with label=0.
Propose the ways how the labeling can be performed based on regression function and what will be the error of such labeling.  


#### 9.2 Classification

Propose a set of classifications algorithms that will provide the best class select for label_coeff agains each indicators group. Classificatoin should include two classes. One defined by label=0 second by label=1. label=1 class is a target class as it defines the action levels. 
##### 9.2.1 Results
Run the Classification. Plot the results on the chart and save it for each indicators group separately. Calculate the classification error when label=0 was mistakenly marked as label=1. Save all required data and results in repor tto be able compare different classifications and reproduce the results

### 10. Human model validation
Iterate over step 9 with human interaction to select the best models
As a result select a set of models that will be used for action levels definition. ### 11. Regression inference


### 11.1 Basic inference

For selected on step 10 regression models perform inference of expected label_coeff for each point in dataset.
Save expected mean value and std

### 11.2 Kalman filter
Select results of Basic inference (11.1) from different indicators groups. That will provide mean/std for each basic inference. And apply calman filter on top of this distribution. 

### 11.3 Final lebele_coeff selection
Based on result from 11.2 select the expected value of label_coeff for certain point.
This value should be treated as mean+-Y*std.

### 11.4 Y inference
Iterate over Y value [-2.0; 2.0] with step 0.1 and define for what ratio of labeled point that are under (for long) / over (fro short) will be the best. Save results to report file with charts

### 11.5 Calculate zones
1. Take selected Y value. Based on it calculate the inferred_labeled_coeff = regression_mean + Y * regression_std 
2. calculate point in action levels that will correspond to: inferred_labeled_coeff
3. calculate for each candle the actual price that will correspond to the inferred_labeled_coeff = zone_limit
4. mark points with ZONE marker:  
   - low < zone_limit for long
   - high > zone_limit for short
5. Save dataset with zoned points

# Restrictions

The initial experiment should be held on train data set.

Train dataset should be used for regression and classification models selection and fine tuning.

Initial calculation should be done in jupiter notebook to reduce code change on the simple trader.

Jupiter notebooks should be stored in the separate folder of simple trader.

Training results and chart should be properly named and stored for further investigation as an artifacts under mounted volume

The investigation should be performed on 15, 60, 240 candles

The investigation should be performed on 15, 60, 240 labels.

The initial combination of indicators with labels should eb performed using strict labels. As this labels represent the best points to open position.

The validation of classification and regression can be performed on strict labels and non strict sibling labels ( as non strict positive labels are still profitable points)

The investigation should be performed with each separate indicators group, and with Kalman filter on the set of this indicators. The best performing should be selected.

The best performing result provides the maximum amount of strict labeled point to be in the zone, with the less amount of non strict labeled points in the zone

The experiment should be held separately for short and long directions.

The implementation should use data model from simple trader. But should not change existing code until all flow is validated by human and approved. 

Propose experiment file and artifact structure during planing

# Goals


1. The goal is to define action levels that will provide best levels fo actions. 
Meaning target should be reached most of the time. Stop loss should be hit recently.
Risk/reward ratio between hitting target and hitting stop loss should be profitable against candle size including operation fees.

2. 1 min candles that will satisfy R/R ratio will be considered as such that are in buy zone for long / sell zone for short. This means that statistically entering positions during this candles will be profitable. 


3. The goal is to adapt action level based on diff_prc_ma and std values based on the market conditions.

4. 


# Data
For each experiment calculated required columns for initial dataset and save them with specific names to be able later review results of the each separate experiment

Training and validation data should both be capable to attach each experiment results and draw Zone markers on the charts in full view.

Experiments should provide results file that will describe the parameters of the system and will allow to perform inference on new datasets.

## Training

Use 2 year dataset for training. 

## Validation

Use 2 month OOS data to validate the result

# Opened questions

- investigate if its possible to calculate different std mean value for diff_prc based on the indicators values