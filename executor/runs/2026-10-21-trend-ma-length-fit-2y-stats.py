"""2y fit: mean/std of the closed-candle ema_N_diff_prc per tf, N in {7,14,25}, mirroring main/:
closed EMA_N at candle k = talib EMA over the INDICATOR_WINDOW_ROWS(=105) closed candles ending at k
(the window the indicator field sees); diff_prc[k] = (ema[k]-ema[k-1])/ema[k-1]*100 on consecutive closed
candles. Gate: N=25 must reproduce EMA_SLOPE_STATS (classification.py) and the stored {tf}_ema_25."""
import sys, json, numpy as np, pandas as pd, talib
W = 105
P = "/media/om/Alexandria/simple_trader/simple_trader_vol_long/train/2y_az_link_usdt/df_with_indicators.pkl"
FROZEN = {15: (0.0018696074433414492, 0.08854754765129406), 60: (0.007586181744923595, 0.17365581448454287),
          240: (0.03083283482398462, 0.3443346525283253)}
df = pd.read_pickle(P)
out = {}
for tf in (15, 60, 240):
    c = df.loc[df[f"{tf}_is_closed"] == True]
    closes = c[f"{tf}_close"].to_numpy(float)
    stored = c[f"{tf}_ema_25"].to_numpy(float)
    n = len(closes)
    for N in (7, 14, 25):
        ema = np.full(n, np.nan)
        for j in range(W - 1, n):
            ema[j] = talib.EMA(closes[j - W + 1:j + 1], timeperiod=N)[-1]
        # earlier candles: full-history EMA (the frame's own warm-up rows) -- as _ema_prev does with the stored value
        head = talib.EMA(closes[:W - 1], timeperiod=N)
        ema[:W - 1] = head
        d = (ema[1:] - ema[:-1]) / ema[:-1] * 100.0
        d = d[np.isfinite(d)]
        mu, sd = float(d.mean()), float(d.std())
        out[f"{tf}_{N}"] = {"mean": mu, "std": sd, "n": int(len(d))}
        extra = ""
        if N == 25:
            ok = np.isfinite(stored) & np.isfinite(ema)
            rel = np.abs(ema[ok] - stored[ok]) / stored[ok]
            fm, fs = FROZEN[tf]
            # also the frozen-stat reproduction using the STORED ema_25 (what the live stats were fit on)
            ds = (stored[1:] - stored[:-1]) / stored[:-1] * 100.0; ds = ds[np.isfinite(ds)]
            extra = (f" | stored-ema rel diff max {rel.max():.2e} median {np.median(rel):.2e} (n {ok.sum()})"
                     f" | frozen rel diff mean {abs(mu-fm)/abs(fm):.2e} std {abs(sd-fs)/fs:.2e}"
                     f" | from stored: mean {ds.mean():.16g} std {ds.std():.16g} n {len(ds)} -> rel {abs(ds.mean()-fm)/abs(fm):.1e} {abs(ds.std()-fs)/fs:.1e}")
        print(f"tf {tf:3d} N {N:2d}: n {len(d):6d} mean {mu:+.6f} std {sd:.6f}{extra}", flush=True)
json.dump(out, open(sys.argv[1], "w"), indent=1)
