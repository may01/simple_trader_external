#!/usr/bin/env python3
"""2y / oos2m: CCI-14 (5 / 15 min) at CB zone entry and at the strict-label minutes; in-zone adverse excursion beyond
the current extreme in 1-min ATR by CCI level (delayed-entry / stop placement).

Data (host path): 2y = 2y_link_usdt/df_with_indicators.part_00..24.pkl (column subset) + df_with_candle_bounds.pkl
(cb zones); oos2m = oos2m_link_usdt/df_with_indicators.pkl (has zones and the stored strict labels -> gate).
Strict labels recomputed with main/'s indicators/labels.py (profit_strict_{long,short}) with the oos2m parameters:
tf15 m1 x0.3 l15 y0.2 | tf60 m1 x0.2 l15 y0.1 | tf240 m1 x0.1 l15 y0.1, n in {1, 2}.
adv = CCI for the short zone, -CCI for the long zone (momentum pushing into the zone).
usage: python3 cci_zone_2y.py 2y|oos2m
"""
import sys, time, resource
import numpy as np, pandas as pd
sys.path.insert(0, "/home/om/projects/simple_trader/main")
from indicators.labels import profit_strict_long, profit_strict_short

V = "/media/om/Alexandria/simple_trader/simple_trader_vol_long/train"
NAME = sys.argv[1]
TFS = (15, 60, 240); SIDES = ("long", "short")
LP = {15: dict(m=1.0, x=0.3, l=15, y=0.2), 60: dict(m=1.0, x=0.2, l=15, y=0.1), 240: dict(m=1.0, x=0.1, l=15, y=0.1)}
BINS = [-1e9, -200, -140, -100, 0, 100, 140, 200, 1e9]
BL = ["<-200", "-200..-140", "-140..-100", "-100..0", "0..100", "100..140", "140..200", ">=200"]
H60 = 60

def rss(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
def q(a, p): return np.nanpercentile(a, p) if len(a) else float("nan")

t0 = time.time()
base = ["1_high", "1_low", "1_close", "1_atr_14", "5_cci_14", "15_cci_14"] + [f"{tf}_{c}" for tf in TFS for c in ("is_closed", "atr_14_ma_5")]
zone = [f"{tf}_{c}" for tf in TFS for c in ("cb_inzone_long", "cb_inzone_short", "cb_high", "cb_low")]
if NAME == "2y":
    parts = [pd.read_pickle(f"{V}/2y_link_usdt/df_with_indicators.part_{k:02d}.pkl")[base] for k in range(25)]
    df = pd.concat(parts); del parts
    cb = pd.read_pickle(f"{V}/2y_link_usdt/df_with_candle_bounds.pkl")[zone]
    df = pd.concat([df, cb.reindex(df.index)], axis=1); del cb
    stored = None
else:
    full = pd.read_pickle(f"{V}/oos2m_link_usdt/df_with_indicators.pkl")
    df = full[base + zone].copy()
    stored = {(tf, s, n): full[f"{tf}_ps{s}_n{n}_m1_x{str(LP[tf]['x']).replace('.', 'p')}_l15_y{str(LP[tf]['y']).replace('.', 'p')}"].to_numpy(float)
              for tf in TFS for s in SIDES for n in (1, 2)}
    del full
assert df.index.is_monotonic_increasing
_g = (df.index[1:] - df.index[:-1]) != pd.Timedelta(minutes=1)
print(f"index gaps (step != 1 min): {int(_g.sum())}, largest {(df.index[1:] - df.index[:-1]).max()} — rows are treated positionally, as the stored labels do")
print(f"[{NAME}] {df.shape} {df.index[0]} -> {df.index[-1]} loaded {time.time()-t0:.0f}s RSS {rss():.0f} MB", flush=True)

# ---- strict labels (main/ code) + gate on oos2m
LAB = {}
for tf in TFS:
    p = LP[tf]
    for n in (1, 2):
        LAB[(tf, "long", n)] = profit_strict_long(df, tf, n, p["m"], p["x"], p["l"], p["y"]).to_numpy(float)
        LAB[(tf, "short", n)] = profit_strict_short(df, tf, n, p["m"], p["x"], p["l"], p["y"]).to_numpy(float)
if stored is not None:
    for k, v in LAB.items():
        s = stored[k]; ok = ~np.isnan(v) & ~np.isnan(s)
        print(f"  label gate {k}: recomputed vs stored equal {np.mean(v[ok] == s[ok]):.6f} on {ok.sum()} rows, nan mismatch {int((np.isnan(v) != np.isnan(s)).sum())}")
print(f"labels done {time.time()-t0:.0f}s RSS {rss():.0f} MB", flush=True)

hi = df["1_high"].to_numpy(float); lo = df["1_low"].to_numpy(float); atr1 = df["1_atr_14"].to_numpy(float)
cci = {5: df["5_cci_14"].to_numpy(float), 15: df["15_cci_14"].to_numpy(float)}
N = len(df)
# forward max/min over the next 60 min (rows t+1..t+60)
def fwd_extreme(a, fn, h):
    sw = np.lib.stride_tricks.sliding_window_view(a, h)
    out = np.full(N, np.nan); out[:N - h] = fn(sw[1:], axis=1)   # window starting at t+1
    return out
f60_hi = fwd_extreme(hi, np.max, H60); f60_lo = fwd_extreme(lo, np.min, H60)

for tf in TFS:
    closed = df[f"{tf}_is_closed"].to_numpy(bool)
    cid = np.concatenate(([0], np.cumsum(closed)[:-1]))            # candle id per row
    # suffix extreme within the candle (rows t+1 .. candle end)
    s_hi = pd.Series(hi[::-1]).groupby(cid[::-1]).cummax().to_numpy()[::-1]
    s_lo = pd.Series(lo[::-1]).groupby(cid[::-1]).cummin().to_numpy()[::-1]
    nxt_hi = np.append(s_hi[1:], np.nan); nxt_lo = np.append(s_lo[1:], np.nan)
    same_next = np.append(cid[1:] == cid[:-1], False)
    cand_hi = np.where(same_next, nxt_hi, np.nan); cand_lo = np.where(same_next, nxt_lo, np.nan)   # nan when t is the last row of the candle
    for side in SIDES:
        inz = df[f"{tf}_cb_inzone_{side}"].fillna(False).to_numpy(bool)
        sgn = 1.0 if side == "short" else -1.0
        adv = {k: v * sgn for k, v in cci.items()}
        # zone blocks: consecutive in-zone rows inside one candle
        start = inz & ~np.append(False, inz[:-1] & (cid[1:] == cid[:-1]))
        blk = np.cumsum(start) * inz                                 # 0 outside, block id inside
        first = np.flatnonzero(start)
        print(f"\n######## [{NAME}] tf {tf} {side}: in-zone minutes {inz.sum()}, zone blocks {len(first)}, candles {cid[-1]+1}")
        # ---------- 1. CCI at zone entry, CCI at strict-label minutes
        for ctf in (5, 15):
            a = adv[ctf]
            e = a[first]; e = e[~np.isnan(e)]
            print(f"  adv{ctf} at zone ENTRY (first in-zone minute, n {len(e)}): q10 {q(e,10):+.0f} q25 {q(e,25):+.0f} median {q(e,50):+.0f} q75 {q(e,75):+.0f} q90 {q(e,90):+.0f}; "
                  f"share >= 100: {np.mean(e >= 100):.0%}, >= 140: {np.mean(e >= 140):.0%}, < 0: {np.mean(e < 0):.0%}")
            for n in (1, 2):
                lab = LAB[(tf, side, n)]
                m = inz & ~np.isnan(lab) & ~np.isnan(a)
                pos = m & (lab == 1); neg = m & (lab == 0)
                print(f"  adv{ctf} at in-zone minutes, strict n{n}: label=1 n {pos.sum()} median {q(a[pos],50):+.0f} [q25 {q(a[pos],25):+.0f}, q75 {q(a[pos],75):+.0f}] | "
                      f"label=0 n {neg.sum()} median {q(a[neg],50):+.0f} [q25 {q(a[neg],25):+.0f}, q75 {q(a[neg],75):+.0f}]; base rate P(1) {pos.sum()/max(m.sum(),1):.3f}")
                # P(strict=1 | adv bin), in-zone minutes and zone-entry minutes
                rows = []
                for lo_, hi_, name in zip(BINS[:-1], BINS[1:], BL):
                    mm = m & (a >= lo_) & (a < hi_); me = mm & start
                    rows.append(f"{name}: {mm.sum()} / {lab[mm].mean() if mm.sum() else float('nan'):.3f} (entry {me.sum()} / {lab[me].mean() if me.sum() else float('nan'):.3f})")
                print(f"    P(strict n{n}=1 | adv{ctf} bin) in-zone minutes n / P (zone-entry minutes n / P): " + " | ".join(rows))
                # first strict=1 minute per block: CCI there and minutes after block start
                fb = {}
                for i in np.flatnonzero(pos):
                    b = blk[i]
                    if b not in fb: fb[b] = i
                if fb:
                    idx = np.array(list(fb.values())); st = first[np.array(list(fb.keys())) - 1]
                    print(f"    first strict n{n}=1 minute per block: {len(idx)} of {len(first)} blocks ({len(idx)/len(first):.0%}); adv{ctf} there median {q(a[idx],50):+.0f} [q25 {q(a[idx],25):+.0f}, q75 {q(a[idx],75):+.0f}]; "
                          f"minutes after zone entry median {np.median(idx-st):.0f} (q75 {np.percentile(idx-st,75):.0f})")
        # ---------- 2. adverse excursion beyond the current extreme, in 1-min ATR, by CCI level
        cur = hi if side == "short" else lo
        exc_c = (cand_hi - cur) / atr1 if side == "short" else (cur - cand_lo) / atr1      # to the candle close
        exc_60 = (f60_hi - cur) / atr1 if side == "short" else (cur - f60_lo) / atr1      # next 60 min
        for ctf in (5, 15):
            a = adv[ctf]
            print(f"  --- excursion beyond the current 1-min {'high' if side=='short' else 'low'} in 1-min ATR, by adv{ctf} (one sample per block = first in-zone minute meeting the condition; 'all' = every in-zone minute)")
            print(f"      {'condition':>12s} | {'blocks':>6s} {'to candle end: q50':>18s} {'q75':>5s} {'q90':>5s} {'q95':>5s} {'P>1':>4s} {'P>2':>4s} | {'next 60m: q50':>13s} {'q75':>5s} {'q90':>5s} {'q95':>5s} {'P>1':>4s} {'P>2':>4s} | {'all-min n':>9s} {'q50':>5s} {'q90':>5s}")
            conds = [("all in-zone", inz), ("adv < 0", inz & (a < 0)), ("0..100", inz & (a >= 0) & (a < 100)), ("adv >= 100", inz & (a >= 100)),
                     ("adv >= 140", inz & (a >= 140)), ("adv >= 200", inz & (a >= 200))]
            e_all = a[inz]; e_all = e_all[~np.isnan(e_all)]
            if len(e_all):
                p80 = float(np.percentile(e_all, 80)); p90 = float(np.percentile(e_all, 90))
                conds += [(f"adv >= p80={p80:.0f}", inz & (a >= p80)), (f"adv >= p90={p90:.0f}", inz & (a >= p90))]
            for name, m in conds:
                mm = m & ~np.isnan(exc_c) & ~np.isnan(atr1)
                # first row per block meeting the condition
                fb = {}
                for i in np.flatnonzero(mm):
                    b = blk[i]
                    if b not in fb: fb[b] = i
                idx = np.array(list(fb.values()), dtype=int)
                ec = exc_c[idx]; e6 = exc_60[idx]; ea = exc_c[mm]
                print(f"      {name:>12s} | {len(idx):6d} {q(ec,50):18.2f} {q(ec,75):5.2f} {q(ec,90):5.2f} {q(ec,95):5.2f} {np.mean(ec>1) if len(ec) else 0:4.0%} {np.mean(ec>2) if len(ec) else 0:4.0%} | "
                      f"{q(e6,50):13.2f} {q(e6,75):5.2f} {q(e6,90):5.2f} {q(e6,95):5.2f} {np.mean(e6>1) if len(e6) else 0:4.0%} {np.mean(e6>2) if len(e6) else 0:4.0%} | {mm.sum():9d} {q(ea,50):5.2f} {q(ea,90):5.2f}")
            # delayed entry / stop table for adv >= 100 and >= 140 (to candle end): P(fill at delta) and P(stop at delta+s | filled)
            for X in (100, 140):
                mm = inz & (a >= X) & ~np.isnan(exc_c)
                fb = {}
                for i in np.flatnonzero(mm):
                    b = blk[i]
                    if b not in fb: fb[b] = i
                idx = np.array(list(fb.values()), dtype=int); ec = exc_c[idx]
                if len(ec) < 30: continue
                print(f"      delayed entry at current extreme + δ·ATR1 for adv{ctf} >= {X} (n {len(ec)} blocks, horizon = candle end): P(filled) and P(price goes a further s·ATR1 beyond the fill | filled)")
                print(f"        {'δ':>4s} {'P(fill)':>8s} | " + " | ".join(f"s={s_}: P(stop)" for s_ in (1, 2, 3)))
                for d in (0.5, 1.0, 1.5, 2.0, 3.0):
                    filled = ec >= d
                    cells = [f"{np.mean(ec[filled] >= d + s_) if filled.any() else float('nan'):14.0%}" for s_ in (1, 2, 3)]
                    print(f"        {d:4.1f} {np.mean(filled):8.0%} | " + " | ".join(cells))
    print(f"[{NAME}] tf {tf} done {time.time()-t0:.0f}s RSS {rss():.0f} MB", flush=True)
