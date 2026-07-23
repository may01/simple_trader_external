For 2. Target levels. Perform experiment. where
For TF indicator-group will adjust the target value.
Preparation;

Update action space:
for level prc calculation (high_lvl_prc) use ma of rolling(window=6). but std should be calculated not from window=6 but for full range of data (call it full_std). So full_std = std of diff_prc from diff_prc_rm(6)
For each 1 min calculate z_scored_diff_prc = how big diff_prc_rm - diff_prc measured in full_std and clamped by [-3; 3]

For training and calculating experiment resulting parameters use 2y dataset.
To validate parameters use 2 month OOS dataset.

Experiment ( will utilise same steps for low and hihg)
1. Take closed candles.
2. for each closed candle : plot ingicator group RSI(position, slope, distance) agains z_scored_diff_prc
3. Plot should be 3D and interactive, the axis should be RSI values, z_scored_diff_prc should be replresented with the color of the dots. dots should be smal. Plot should be big
4. Perform regression to find multidimensional plane thta will the best represent dependency between previous candle RSI-group and current candle z_scored_diff_prc, 
5. calculate standart deviation for z_scored_diff_prc from the plane - z_scored_diff_prc_std.
6. Start of inference.
7. For each closed candle at the moment of close. Calculate RSI-group. and infere expected value of  z_scored_diff_prc_infered.
8. z_scored_diff_prc_infered calculate the expected diff_prc_infered value.
9. Calculate expeced candle bounds (low/high) value based on the diff_prc_infered (low/high

Results:
1. 3D Plot the ingicator group RSI vs z_scored_diff_prc dependency
2. calculate how much diff_prc values will lend diff_prc_ma + diff_prc_infered +- z_scored_diff_prc_std
3. Use OOS 2 month data with statistical calculate expected candle bounds (high/low) and plot them on the full view