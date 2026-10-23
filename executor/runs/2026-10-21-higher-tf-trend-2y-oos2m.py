#!/usr/bin/env python3
"""Tier B: a HIGHER tf's trend flag as a filter on a lower tf's CB zone entries, over 2y (2023-01 -> 2024-12) and
oos2m (2025-01 -> 2025-03), from the stored 1-min frames. The trend-ma-length stand-in flow (set-C candidate minutes
= inzone and overshoot pass; first passing minute per tf candle; entry = 1_close; candle stop; cbnc target; max hold H;
size min(100/dist, 50000/entry); no fees), with the flag per (tf, side) built from the forming EMA-25 class of the OWN
tf and of the HIGHER tfs (same row): hx (own & higher veto), al (own & higher aligned), rp (higher replaces own),
cl (own & higher closed-candle class), nladder (higher only), none, e25, c25.
usage: python3 tier_b.py <stats.json> [--hold=60]
"""
import sys, json, time, resource
import numpy as np, pandas as pd, talib
from collections import defaultdict

V = "/media/om/Alexandria/simple_trader/simple_trader_vol_long/train"
STATS = json.load(open(sys.argv[1]))
H = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--hold=")), 60))
TFS = (15, 60, 240); SIDES = ("long", "short"); NS = (25,); W = 105; X = 0.5
FROZEN25 = {15: (0.0018696074433414492, 0.08854754765129406), 60: (0.007586181744923595, 0.17365581448454287),
            240: (0.03083283482398462, 0.3443346525283253)}
THR = {15: {"long": 0.3477, "short": 0.3808}, 60: {"long": 0.3756, "short": 0.3796}, 240: {"long": 0.4693, "short": 0.5178}}
RISK = 100.0; CAP = 100_000 * 0.5; PLACEHOLDER = 0.002; RANGE_N = 60


def rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def candle_id(closed):
    return np.concatenate(([0], np.cumsum(closed)[:-1]))


def load(name):
    t0 = time.time()
    if name == "2y":
        df = pd.read_pickle(f"{V}/2y_az_link_usdt/df_with_indicators.pkl")
        keep = ["1_high", "1_low", "1_close"] + [f"{tf}_{c}" for tf in TFS for c in ("close", "is_closed")]
        df = df[keep].copy()
        cb = pd.read_pickle(f"{V}/2y_link_usdt/df_with_candle_bounds.pkl")
        cb = cb[[f"{tf}_{c}" for tf in TFS for c in ("cb_low", "cb_high", "cb_low_std", "cb_high_std", "cb_inzone_long", "cb_inzone_short")]].copy()
        nc = pd.read_pickle(f"{V}/2y_link_usdt/df_with_candle_bounds_nc.pkl")
        nc = nc[[f"{tf}_{c}" for tf in TFS for c in ("cbnc_high", "cbnc_low")]].copy()
        df = pd.concat([df, cb.reindex(df.index), nc.reindex(df.index)], axis=1)
    else:
        df = pd.read_pickle(f"{V}/oos2m_link_usdt/df_with_indicators.pkl")
        keep = ["1_high", "1_low", "1_close"] + [f"{tf}_{c}" for tf in TFS for c in ("close", "is_closed", "cb_low", "cb_high", "cb_low_std", "cb_high_std",
                                                                               "cb_inzone_long", "cb_inzone_short", "cbnc_high", "cbnc_low")]
        df = df[keep].copy()
    print(f"[{name}] {df.shape} {df.index[0]} -> {df.index[-1]} loaded {time.time() - t0:.0f}s RSS {rss():.0f} MB", flush=True)
    return df


def ema_closed(closes, Nn):
    n = len(closes); ema = np.full(n, np.nan)
    for j in range(n):
        lo = max(0, j - W + 1)
        if j - lo + 1 >= Nn:
            ema[j] = talib.EMA(closes[lo:j + 1], timeperiod=Nn)[-1]
    return ema


def classes(df, tf):
    """per row: {(N, 'f'|'c'): class int8}"""
    closed = (df[f"{tf}_is_closed"] == True).to_numpy()  # noqa: E712
    cid = candle_id(closed)
    closes = df.loc[closed, f"{tf}_close"].to_numpy(float)
    c1 = df["1_close"].to_numpy(float)
    out = {}
    for Nn in NS:
        ema = ema_closed(closes, Nn)
        a = 2.0 / (Nn + 1)
        prev_i = cid - 1
        prev = np.where(prev_i >= 0, ema[np.maximum(prev_i, 0)], np.nan)
        d_f = (a * c1 + (1 - a) * prev - prev) / prev * 100.0
        dcl = np.full(len(ema), np.nan); dcl[1:] = (ema[1:] - ema[:-1]) / ema[:-1] * 100.0
        d_c = np.where(prev_i >= 0, dcl[np.maximum(prev_i, 0)], np.nan)
        mu, sd = FROZEN25[tf] if Nn == 25 else (STATS[f"{tf}_{Nn}"]["mean"], STATS[f"{tf}_{Nn}"]["std"])
        for key, d in ((f"e{Nn}", d_f), (f"c{Nn}", d_c)):
            cl = np.where(d < mu - X * sd, -1, np.where(d > mu + X * sd, 1, 0)).astype(np.int8); cl[~np.isfinite(d)] = 0
            out[key] = cl
    return out, cid


def simulate_all(df, tf, side, cand):
    """outcome of an entry at EVERY candidate minute: pnl (USDT), reason; vectorised per entry."""
    hi, lo, cl = (df[c].to_numpy(float) for c in ("1_high", "1_low", "1_close"))
    n = len(cl)
    cid15 = candle_id((df["15_is_closed"] == True).to_numpy())  # noqa: E712
    s = pd.Series(lo if side == "long" else hi)
    ext15 = (s.groupby(cid15).cummin() if side == "long" else s.groupby(cid15).cummax()).to_numpy()
    rng = pd.Series(hi - lo).shift(1).rolling(RANGE_N, min_periods=1).mean().to_numpy()  # closed bars before this minute
    tgt = df[f"{tf}_cbnc_high" if side == "long" else f"{tf}_cbnc_low"].to_numpy(float)
    idx = np.flatnonzero(cand)
    pnl = np.zeros(len(idx)); reason = np.zeros(len(idx), dtype=np.int8)  # 1 stop 2 target 3 hold
    size_arr = np.zeros(len(idx)); dist_arr = np.zeros(len(idx)); kind = np.zeros(len(idx), dtype=np.int8)
    sgn = 1.0 if side == "long" else -1.0
    for k, i0 in enumerate(idx):
        e = cl[i0]
        stop = ext15[i0] - rng[i0] if side == "long" else ext15[i0] + rng[i0]
        if not np.isfinite(stop) or (side == "long" and stop >= e) or (side == "short" and stop <= e):
            stop = e * (1 - PLACEHOLDER) if side == "long" else e * (1 + PLACEHOLDER); kind[k] = 1
        t = tgt[i0]
        dist = abs(e - stop); size = min(RISK / dist, CAP / e)
        a, b = i0 + 1, min(i0 + 1 + H, n)
        if side == "long":
            hs = lo[a:b] <= stop; ht = hi[a:b] >= t if np.isfinite(t) else np.zeros(b - a, dtype=bool)
        else:
            hs = hi[a:b] >= stop; ht = lo[a:b] <= t if np.isfinite(t) else np.zeros(b - a, dtype=bool)
        js = int(np.argmax(hs)) if hs.any() else 10 ** 9; jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
        if js <= jt and js < 10 ** 9:      # both in one minute -> stop
            x, r = stop, 1
        elif jt < 10 ** 9:
            x, r = t, 2
        else:
            x, r = cl[b - 1], 3
        pnl[k] = (x - e) * size * sgn; reason[k] = r; size_arr[k] = size; dist_arr[k] = dist
    return idx, pnl, reason, size_arr, dist_arr, kind


HIGHER = {15: (60, 240), 60: (240,), 240: ()}


def run(name):
    df = load(name)
    c1 = df["1_close"].to_numpy(float)
    mom_up = np.r_[False, c1[1:] > c1[:-1]]; mom_dn = np.r_[False, c1[1:] < c1[:-1]]
    CLS = {}; CID = {}
    for tf in TFS:
        CLS[tf], CID[tf] = classes(df, tf)
    out = {}
    for tf in TFS:
        cid = CID[tf]
        for side in SIDES:
            inz = df[f"{tf}_cb_inzone_{side}"].fillna(False).to_numpy(bool)
            b = df[f"{tf}_cb_low" if side == "long" else f"{tf}_cb_high"].to_numpy(float)
            w = df[f"{tf}_cb_low_std" if side == "long" else f"{tf}_cb_high_std"].to_numpy(float)
            x = df["1_low" if side == "long" else "1_high"].to_numpy(float)
            over = (b - x) / w if side == "long" else (x - b) / w
            over_pass = ~(over > THR[tf][side])
            cand = inz & over_pass
            idx, pnl, reason, size, dist, kind = simulate_all(df, tf, side, cand)
            bad = -1 if side == "long" else 1; good = -bad
            fv = {h: CLS[h]["e25"][idx] != bad for h in TFS}      # forming veto flag of tf h at the candidate minutes
            fa = {h: CLS[h]["e25"][idx] == good for h in TFS}     # forming aligned
            fc = {h: CLS[h]["c25"][idx] != bad for h in TFS}      # closed veto flag
            one = np.ones(len(idx), dtype=bool)
            def mk(own, hi, rule):
                f = (own if own is not None else one).copy()
                for h in rule:
                    f &= hi[h]
                return f
            flags = {"none": one, "e25": fv[tf], "c25": fc[tf]}
            flags["hx15<60"] = mk(fv[tf], fv, (60,) if tf == 15 else ())
            flags["hx15<240"] = mk(fv[tf], fv, (240,) if tf == 15 else ())
            flags["hx60<240"] = mk(fv[tf], fv, (240,) if tf == 60 else ())
            flags["ladder"] = mk(fv[tf], fv, HIGHER[tf])
            flags["all<240"] = mk(fv[tf], fv, (240,) if tf != 240 else ())
            flags["rp15=60"] = mk(None, fv, (60,) if tf == 15 else (tf,))
            flags["rp15=240"] = mk(None, fv, (240,) if tf == 15 else (tf,))
            flags["rp60=240"] = mk(None, fv, (240,) if tf == 60 else (tf,))
            flags["rpall=240"] = mk(None, fv, (240,))
            flags["al15<60"] = mk(fv[tf], fa, (60,) if tf == 15 else ())
            flags["al15<240"] = mk(fv[tf], fa, (240,) if tf == 15 else ())
            flags["al60<240"] = mk(fv[tf], fa, (240,) if tf == 60 else ())
            flags["alladder"] = mk(fv[tf], fa, HIGHER[tf])
            flags["cl15<60"] = mk(fv[tf], fc, (60,) if tf == 15 else ())
            flags["clladder"] = mk(fv[tf], fc, HIGHER[tf])
            flags["nladder"] = mk(None, fv, HIGHER[tf])
            flags["n15<60"] = mk(None, fv, (60,) if tf == 15 else (tf,))
            mom = (mom_up if side == "long" else mom_dn)[idx]
            cid_e = cid[idx]
            res = {}
            for gate in ("", "mom"):
                for v, fl in flags.items():
                    ok = fl & (mom if gate else True)
                    first = np.zeros(len(idx), dtype=bool)
                    seen = set()
                    for k in np.flatnonzero(ok):
                        c = cid_e[k]
                        if c not in seen:
                            seen.add(c); first[k] = True
                    p = pnl[first]
                    res[(gate, v)] = dict(n=int(first.sum()), net=float(p.sum()), pf=float(p[p > 0].sum() / abs(p[p < 0].sum())) if (p < 0).any() else float("inf"),
                                          wr=float(np.mean(p > 0)) if len(p) else float("nan"), stop=int((reason[first] == 1).sum()), tgt=int((reason[first] == 2).sum()),
                                          hold=int((reason[first] == 3).sum()), R=float((p / (size[first] * dist[first])).sum()),
                                          first_idx=np.flatnonzero(first), pnl=p, cands=int(ok.sum()))
            out[(tf, side)] = dict(res=res, n_cand=len(idx), n_candles=len(np.unique(cid_e)), idx=idx, pnl=pnl, reason=reason, cid=cid_e, flags=flags, mom=mom,
                                   fv=fv, fa=fa)
            r = res[("", "e25")]
            print(f"[{name}] tf {tf:3d} {side:5s}: candidates {len(idx)} in {len(np.unique(cid_e))} candles; e25 entries {r['n']} net {r['net']:+.0f} "
                  f"PF {r['pf']:.2f} wr {r['wr']:.2f} stop/tgt/hold {r['stop']}/{r['tgt']}/{r['hold']} | placeholder stops {kind.mean():.1%} RSS {rss():.0f} MB", flush=True)
    del df
    return out


def table(out, name, gate):
    order = ["none", "e25", "c25", "hx15<60", "hx15<240", "hx60<240", "ladder", "all<240", "rp15=60", "rp15=240", "rp60=240", "rpall=240",
             "al15<60", "al15<240", "al60<240", "alladder", "cl15<60", "clladder", "nladder", "n15<60"]
    print(f"\n=== {name}, gate '{gate or 'C'}', hold {H} min: entries, net USDT, PF, win rate, stop/target/hold exits, sum R ===")
    print(f"{'variant':>9s} | " + " | ".join(f"{'tf' + str(tf) + ' ' + side:>26s}" for tf in TFS for side in SIDES) + f" | {'ALL n':>7s} {'net':>8s} {'PF':>5s} {'R':>7s}")
    for v in order:
        cells = []; tot_n = 0; tot = 0.0; w = 0.0; l = 0.0; R = 0.0
        for tf in TFS:
            for side in SIDES:
                r = out[(tf, side)]["res"][(gate, v)]
                cells.append(f"{r['n']:5d} {r['net']:+7.0f} {r['pf']:4.2f} {r['wr']:.2f} {r['stop']}/{r['tgt']}/{r['hold']}")
                tot_n += r["n"]; tot += r["net"]; p = r["pnl"]; w += p[p > 0].sum(); l += abs(p[p < 0].sum()); R += r["R"]
        print(f"{v:>9s} | " + " | ".join(f"{c:>26s}" for c in cells) + f" | {tot_n:7d} {tot:+8.0f} {w / l if l else float('inf'):5.2f} {R:+7.1f}")
    # paired vs e25 per candle: the candle's entry pnl under v minus under e25 (0 when no entry)
    print(f"--- paired vs e25 by candle (Δnet, bootstrap CI90 over candles, P(Δ<0)); per tf+side and all ---")
    rng = np.random.default_rng(0)
    for v in order:
        parts = []; all_d = []
        for tf in TFS:
            for side in SIDES:
                o = out[(tf, side)]; r = o["res"][(gate, v)]; b = o["res"][(gate, "e25")]
                dv = defaultdict(float); db = defaultdict(float)
                for k, p in zip(r["first_idx"], r["pnl"]):
                    dv[o["cid"][k]] += p
                for k, p in zip(b["first_idx"], b["pnl"]):
                    db[o["cid"][k]] += p
                keys = set(dv) | set(db)
                d = np.array([dv.get(c, 0.0) - db.get(c, 0.0) for c in keys]) if keys else np.zeros(1)
                boot = np.array([rng.choice(d, len(d), replace=True).sum() for _ in range(2000)])
                parts.append(f"{d.sum():+6.0f} [{np.percentile(boot, 5):+6.0f},{np.percentile(boot, 95):+6.0f}] {np.mean(boot < 0):.2f}")
                all_d.append(d)
        d = np.concatenate(all_d); boot = np.array([rng.choice(d, len(d), replace=True).sum() for _ in range(2000)])
        print(f"{v:>9s} | " + " | ".join(f"{p:>26s}" for p in parts) + f" | {d.sum():+8.0f} [{np.percentile(boot, 5):+7.0f},{np.percentile(boot, 95):+7.0f}] {np.mean(boot < 0):.2f}")


if __name__ == "__main__":
    for name in ("2y", "oos2m"):
        out = run(name)
        for gate in ("", "mom"):
            table(out, name, gate)
        print(f"--- {name}: flag pass rate at the candidate minutes ---")
        for tf in TFS:
            for side in SIDES:
                o = out[(tf, side)]
                print(f"tf {tf:3d} {side:5s}: " + " ".join(f"{v} {o['flags'][v].mean():.3f}" for v in ("e25", "c25", "hx15<60", "hx15<240", "hx60<240", "ladder", "al15<60", "al60<240")) + f" | mom {o['mom'].mean():.3f}")
        print(f"--- {name}: e25 entries (gate C, hold {H}) split by the higher tf's veto flag / alignment at the entry minute: n, net, PF, stop share, mean ---")
        for tf in (15, 60):
            for side in SIDES:
                o = out[(tf, side)]; r = o["res"][("", "e25")]; fi = r["first_idx"]
                for h in HIGHER[tf]:
                    for lab, arr in (("veto pass", o["fv"][h]), ("aligned", o["fa"][h])):
                        for val in (True, False):
                            m = arr[fi] == val; p = r["pnl"][m]
                            if m.sum() == 0:
                                continue
                            w = p[p > 0].sum(); l = abs(p[p < 0].sum())
                            print(f"tf {tf:3d} {side:5s} by tf {h:3d} {lab:9s} = {str(val):5s}: n {m.sum():6d}, net {p.sum():+8.0f}, PF {w / l if l else float('inf'):4.2f}, "
                                  f"stop {np.mean(o['reason'][fi][m] == 1):.2f}, mean {p.mean():+6.2f}")
