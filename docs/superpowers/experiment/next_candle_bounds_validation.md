> **Status 2026-07-24: DONE.** Results: `results/next_candle_bounds_nc_results.md`.
> Branch `next-candle-bounds-nc`; producer `notebooks/candle_bounds_nc/run_cbnc.py`;
> artifact `df_with_candle_bounds_nc.pkl` on oos2m; viewer groups `cbnc_*` + markers
> `cbzone_nc_*`/`cbx_*`.

Goal: 

Add additional metrics that will calculate next candle bounds (low and high) based on current not closed candle.

Steps:
For each 1 min point. take current not closed candle, and predict next candle bounds based on it. Store this bounds. 
And validate entry points for long and short position based on this bounds.

Use the same algorithms that used for predicting next bounds on the closed candles.

Results:
- Save for each 1 min candle the next bound on non close data
- update full view to visualise the new non closed bounds along side with exisitng closed bounds
- calculate metics of how good this bounds wokrs
- add markers cbzone non closed for long and short draw this markers along side with existing
- add markers that will represent intersection of zone markers on closed and non closed bounds