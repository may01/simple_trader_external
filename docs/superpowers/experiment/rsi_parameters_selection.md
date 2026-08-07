Goal:
Check different RSI ma windows parameters and select the one that will fit the best for classifying the market state. 
The goal is to increase amount of certain label in the specific class. 
The middle class can stay neutral but as stronger the class is the bigger separation between long and short position should be.

Experiment steps:
1. check different RSI ma windows=[8,12,24] 
2. get slope value for each ma
3. classify slope value spliting by percentiles, sym0, or by proposed z-score distance from the mean.
4. calculate amount of strict labels in each class
5. save statistics what ma window provides better separation for defining the label probability.  
6. try to increase amount of classes to 7 there will be neutral class, low/high, low/high strong and low/high extra, the rationale of this: often before reversing the candle gets very big, indicators enter rear extra state, that should be represented by slope values. The goal here is to detect classes for which strong signal will mean very low probability of getting signal in reverse direction, but in extra class, the probability in reverse direction is higher then the continuation of the trend. For detecting extra classes try both strict and non-strict labels on different ma windows.   


Results:
- provide measurements what ma is the best for classifying strict and non strict labels.
- provide measurements, for 5 and 7 classes, compare results form different measurements
- provide measurements, what class selection techniques(quantile, sym0, raw predefined z-score limits) provides better metrics for labels split in classes, for both strict and non strict labels 
- analyze each measurement, provide report with description what approach performed the best for each check and what approach is the best overall.  


Constraints:
- perform experiment in separate branch
- select what branch fits the best as a base branch to run the experiment
- do not commit any results, before report will be approved. 
- use 2y dataset for training 
- use 2m oos dataset for validation
- analyze task and ask unclear questions before starting the experiment
