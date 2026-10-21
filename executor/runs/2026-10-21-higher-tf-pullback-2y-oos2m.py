#!/usr/bin/env python3
"""Tier B: a HIGHER tf's PULL-BACK state vetoing the lower tf's in-trend CB zone entries, over 2y (2023-01 -> 2024-12)
and oos2m (2025-01 -> 2025-03), from the stored 1-min frames. The higher_tf_trend_filter tier-B flow (set-C candidate
minutes = inzone and overshoot pass; first passing minute per tf candle; entry = 1_close; candle stop; cbnc target;
max hold H; size min(100/dist, 50000/entry); no fees); the veto per (tf, side) is ANDed into the own forming EMA-25
flag (e25). Pull-back state PB_long of the higher tf H (short mirrored), per row:
  xd    kernel extdone_high of H (({H}_high - 1_close)/1_atr_14_ma_5 >= d(progress), EXTDONE_LADDER, wall-clock progress)
  cf0   closed H class == +1 and forming class <= 0          ovc   H short-side overshoot (> OVERSHOOT_THR) earlier in the
  ov30  ... within the last 30 rows, and not now                    same H candle, and not now
  any   xd | cf0 | ovc      mir  kernel extdone_low of H (opposite sign, control)      sh+  xd read 1440 rows earlier (placebo)
usage: python3 2026-10-21-higher-tf-pullback-2y-oos2m.py <stats.json> [--hold=60]
"""
import sys, json, time, resource
import numpy as np, pandas as pd, talib
from collections import defaultdict

V = "/media/om/Alexandria/simple_trader/simple_trader_vol_long/train"
STATS = json.load(open(sys.argv[1]))
H = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--hold=")), 60))
TFS = (15, 60, 240); SIDES = ("long", "short"); W = 105; X = 0.5
FROZEN25 = {15: (0.0018696074433414492, 0.08854754765129406), 60: (0.007586181744923595, 0.17365581448454287),
            240: (0.03083283482398462, 0.3443346525283253)}
THR = {15: {"long": 0.3477, "short": 0.3808}, 60: {"long": 0.3756, "short": 0.3796}, 240: {"long": 0.4693, "short": 0.5178}}
LADDER = {15: {"high": ((0.25, 5.0), (0.50, 2.5), (0.75, 1.5)), "low": ((0.25, 4.0), (0.50, 2.5), (0.75, 1.5))},
          60: {"high": ((0.25, 10.0), (0.50, 8.0), (0.75, 4.0)), "low": ((0.25, 10.0), (0.50, 6.0), (0.75, 4.0))},
          240: {"high": ((0.75, 8.0),), "low": ((0.75, 8.0),)}}
RISK = 100.0; CAP = 100_000 * 0.5; PLACEHOLDER = 0.002; RANGE_N = 60; OV_ROWS = 30; SHIFT = 1440
HIGHER = {15: (60, 240), 60: (240,), 240: ()}
PAIRS = {"15<60": {15: (60,)}, "15<240": {15: (240,)}, "60<240": {60: (240,)}, "ladder": HIGHER}
FAMS = ("xd", "cf0", "ovc", "ov30", "any", "xdcf", "mir", "sh+")


def rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def candle_id(closed):
    return np.concatenate(([0], np.cumsum(closed)[:-1]))


BASE = ["1_high", "1_low", "1_close"] + [f"{tf}_{c}" for tf in TFS for c in ("close", "is_closed", "high", "low")]
CBC = [f"{tf}_{c}" for tf in TFS for c in ("cb_low", "cb_high", "cb_low_std", "cb_high_std", "cb_inzone_long", "cb_inzone_short")]
NCC = [f"{tf}_{c}" for tf in TFS for c in ("cbnc_high", "cbnc_low")]


def load(name):
    t0 = time.time()
    if name == "2y":
        df = pd.read_pickle(f"{V}/2y_az_link_usdt/df_with_indicators.pkl")[BASE].copy()
        atr = pd.concat([pd.read_pickle(f"{V}/2y_link_usdt/df_with_indicators.part_{k:02d}.pkl")[["1_atr_14_ma_5"]] for k in range(25)])
        cb = pd.read_pickle(f"{V}/2y_link_usdt/df_with_candle_bounds.pkl")[CBC].copy()
        nc = pd.read_pickle(f"{V}/2y_link_usdt/df_with_candle_bounds_nc.pkl")[NCC].copy()
        df = pd.concat([df, atr.reindex(df.index), cb.reindex(df.index), nc.reindex(df.index)], axis=1)
    else:
        df = pd.read_pickle(f"{V}/oos2m_link_usdt/df_with_indicators.pkl")[BASE + ["1_atr_14_ma_5"] + CBC + NCC].copy()
    print(f"[{name}] {df.shape} {df.index[0]} -> {df.index[-1]} loaded {time.time() - t0:.0f}s RSS {rss():.0f} MB; atr finite {np.isfinite(df['1_atr_14_ma_5'].to_numpy(float)).mean():.3f}", flush=True)
    return df


def ema_closed(closes, Nn):
    n = len(closes); ema = np.full(n, np.nan)
    for j in range(n):
        lo = max(0, j - W + 1)
        if j - lo + 1 >= Nn:
            ema[j] = talib.EMA(closes[lo:j + 1], timeperiod=Nn)[-1]
    return ema


def classes(df, tf):
    closed = (df[f"{tf}_is_closed"] == True).to_numpy()  # noqa: E712
    cid = candle_id(closed)
    closes = df.loc[closed, f"{tf}_close"].to_numpy(float)
    c1 = df["1_close"].to_numpy(float)
    ema = ema_closed(closes, 25); a = 2.0 / 26
    prev_i = cid - 1
    prev = np.where(prev_i >= 0, ema[np.maximum(prev_i, 0)], np.nan)
    d_f = (a * c1 + (1 - a) * prev - prev) / prev * 100.0
    dcl = np.full(len(ema), np.nan); dcl[1:] = (ema[1:] - ema[:-1]) / ema[:-1] * 100.0
    d_c = np.where(prev_i >= 0, dcl[np.maximum(prev_i, 0)], np.nan)
    mu, sd = FROZEN25[tf]
    out = {}
    for key, d in (("e25", d_f), ("c25", d_c)):
        cl = np.where(d < mu - X * sd, -1, np.where(d > mu + X * sd, 1, 0)).astype(np.int8); cl[~np.isfinite(d)] = 0
        out[key] = cl
    return out, cid


def ladder_threshold(prog, ladder):
    thr = np.full(len(prog), np.inf)
    for p0, d in ladder:
        thr[prog >= p0] = d
    return thr


def extdone(df, tf):
    """kernel port, wall-clock progress, NOT sticky"""
    idx = pd.DatetimeIndex(df.index)
    prog = (np.asarray((idx - idx.floor(f"{tf}min")) / pd.Timedelta(minutes=1), dtype=float) + 1.0) / tf
    close = df["1_close"].to_numpy(float); atr = df["1_atr_14_ma_5"].to_numpy(float)
    ok = np.isfinite(atr) & (atr > 0); safe = np.where(ok, atr, 1.0)
    out = {}
    for side in ("high", "low"):
        run = df[f"{tf}_{side}"].to_numpy(float)
        pull = ((run - close) if side == "high" else (close - run)) / safe
        with np.errstate(invalid="ignore"):
            out[side] = ok & (pull >= ladder_threshold(prog, LADDER[tf][side]))
    return out


def seg_cummax(active, seg):
    return pd.Series(active).groupby(seg).cummax().to_numpy(bool)


def within_last(active, rows):
    return pd.Series(active.astype(float)).rolling(rows, min_periods=1).max().to_numpy() > 0


def simulate_all(df, tf, side, cand):
    hi, lo, cl = (df[c].to_numpy(float) for c in ("1_high", "1_low", "1_close"))
    n = len(cl)
    cid15 = candle_id((df["15_is_closed"] == True).to_numpy())  # noqa: E712
    s = pd.Series(lo if side == "long" else hi)
    ext15 = (s.groupby(cid15).cummin() if side == "long" else s.groupby(cid15).cummax()).to_numpy()
    rng = pd.Series(hi - lo).shift(1).rolling(RANGE_N, min_periods=1).mean().to_numpy()
    tgt = df[f"{tf}_cbnc_high" if side == "long" else f"{tf}_cbnc_low"].to_numpy(float)
    idx = np.flatnonzero(cand)
    pnl = np.zeros(len(idx)); reason = np.zeros(len(idx), dtype=np.int8)
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
        if js <= jt and js < 10 ** 9:
            x, r = stop, 1
        elif jt < 10 ** 9:
            x, r = t, 2
        else:
            x, r = cl[b - 1], 3
        pnl[k] = (x - e) * size * sgn; reason[k] = r; size_arr[k] = size; dist_arr[k] = dist
    return idx, pnl, reason, size_arr, dist_arr, kind


def run(name):
    df = load(name)
    n = len(df)
    CLS = {}; CID = {}; XD = {}; OVA = {}
    for tf in TFS:
        CLS[tf], CID[tf] = classes(df, tf)
        XD[tf] = extdone(df, tf)
        for side in SIDES:
            b = df[f"{tf}_cb_low" if side == "long" else f"{tf}_cb_high"].to_numpy(float)
            w = df[f"{tf}_cb_low_std" if side == "long" else f"{tf}_cb_high_std"].to_numpy(float)
            x = df["1_low" if side == "long" else "1_high"].to_numpy(float)
            over = (b - x) / w if side == "long" else (x - b) / w
            OVA[(tf, side)] = over > THR[tf][side]          # overshoot ACTIVE on that side's bound
        print(f"[{name}] tf {tf:3d}: extdone high {XD[tf]['high'].mean():.3f} low {XD[tf]['low'].mean():.3f} | overshoot active long {OVA[(tf, 'long')].mean():.3f} short {OVA[(tf, 'short')].mean():.3f} "
              f"| e25 class +1 {np.mean(CLS[tf]['e25'] == 1):.3f} -1 {np.mean(CLS[tf]['e25'] == -1):.3f}", flush=True)
    # PB per (fam, H, dir): True = veto a lower-tf entry of that direction
    PB = {}
    for Hh in TFS:
        for side in SIDES:
            d = 1 if side == "long" else -1
            ext_side = "high" if side == "long" else "low"; opp = "low" if side == "long" else "high"
            PB[("xd", Hh, side)] = XD[Hh][ext_side]
            PB[("mir", Hh, side)] = XD[Hh][opp]
            cf_ = CLS[Hh]["c25"] == d
            PB[("cf0", Hh, side)] = cf_ & (CLS[Hh]["e25"] != d)
            ova = OVA[(Hh, "short" if side == "long" else "long")]   # price beyond H's bound in the trade's direction
            PB[("ovc", Hh, side)] = seg_cummax(ova, CID[Hh]) & ~ova
            PB[("ov30", Hh, side)] = within_last(ova, OV_ROWS) & ~ova
            PB[("any", Hh, side)] = PB[("xd", Hh, side)] | PB[("cf0", Hh, side)] | PB[("ovc", Hh, side)]
            PB[("xdcf", Hh, side)] = PB[("xd", Hh, side)] & PB[("cf0", Hh, side)]
            v = np.zeros(n, dtype=bool); v[SHIFT:] = PB[("xd", Hh, side)][:-SHIFT]
            PB[("sh+", Hh, side)] = v
    print(f"[{name}] PB rates over all rows: " + "; ".join(f"{fam} " + "/".join(f"{PB[(fam, Hh, s)].mean():.3f}" for Hh in TFS for s in SIDES) for fam in FAMS), flush=True)
    month = pd.DatetimeIndex(df.index).to_period("M").astype(str).to_numpy()
    out = {}
    for tf in TFS:
        cid = CID[tf]
        for side in SIDES:
            inz = df[f"{tf}_cb_inzone_{side}"].fillna(False).to_numpy(bool)
            cand = inz & ~OVA[(tf, side)]
            idx, pnl, reason, size, dist, kind = simulate_all(df, tf, side, cand)
            bad = -1 if side == "long" else 1
            fv = {Hh: CLS[Hh]["e25"][idx] != bad for Hh in TFS}
            pb = {(fam, Hh): PB[(fam, Hh, side)][idx] for fam in FAMS for Hh in TFS}
            one = np.ones(len(idx), dtype=bool)
            flags = {"none": one, "e25": fv[tf], "hx15<60": fv[tf] & (fv[60] if tf == 15 else one)}
            for fam in FAMS:
                for pk, rule in PAIRS.items():
                    f = fv[tf].copy()
                    for Hh in rule.get(tf, ()):
                        f &= ~pb[(fam, Hh)]
                    flags[f"{fam}{pk}"] = f
            cid_e = cid[idx]
            res = {}
            for v, fl in flags.items():
                first = np.zeros(len(idx), dtype=bool); seen = set()
                for k in np.flatnonzero(fl):
                    c = cid_e[k]
                    if c not in seen:
                        seen.add(c); first[k] = True
                p = pnl[first]
                res[v] = dict(n=int(first.sum()), net=float(p.sum()), pf=float(p[p > 0].sum() / abs(p[p < 0].sum())) if (p < 0).any() else float("inf"),
                              wr=float(np.mean(p > 0)) if len(p) else float("nan"), stop=int((reason[first] == 1).sum()), tgt=int((reason[first] == 2).sum()),
                              hold=int((reason[first] == 3).sum()), R=float((p / (size[first] * dist[first])).sum()), first_idx=np.flatnonzero(first), pnl=p)
            out[(tf, side)] = dict(res=res, idx=idx, pnl=pnl, reason=reason, cid=cid_e, flags=flags, pb=pb, fv=fv, month=month[idx])
            r = res["e25"]
            print(f"[{name}] tf {tf:3d} {side:5s}: candidates {len(idx)} in {len(np.unique(cid_e))} candles; e25 entries {r['n']} net {r['net']:+.0f} "
                  f"PF {r['pf']:.2f} wr {r['wr']:.2f} stop/tgt/hold {r['stop']}/{r['tgt']}/{r['hold']} | placeholder stops {kind.mean():.1%} RSS {rss():.0f} MB", flush=True)
    del df
    return out


def table(out, name):
    order = ["none", "e25", "hx15<60"] + [f"{fam}{pk}" for fam in FAMS for pk in PAIRS]
    print(f"\n=== {name}, gate C, hold {H} min: entries, net USDT, PF, win rate, stop/target/hold exits, sum R ===")
    print(f"{'variant':>10s} | " + " | ".join(f"{'tf' + str(tf) + ' ' + side:>26s}" for tf in TFS for side in SIDES) + f" | {'ALL n':>7s} {'net':>8s} {'PF':>5s} {'R':>7s}")
    for v in order:
        cells = []; tot_n = 0; tot = 0.0; w = 0.0; l = 0.0; R = 0.0
        for tf in TFS:
            for side in SIDES:
                r = out[(tf, side)]["res"][v]
                cells.append(f"{r['n']:5d} {r['net']:+7.0f} {r['pf']:4.2f} {r['wr']:.2f} {r['stop']}/{r['tgt']}/{r['hold']}")
                tot_n += r["n"]; tot += r["net"]; p = r["pnl"]; w += p[p > 0].sum(); l += abs(p[p < 0].sum()); R += r["R"]
        print(f"{v:>10s} | " + " | ".join(f"{c:>26s}" for c in cells) + f" | {tot_n:7d} {tot:+8.0f} {w / l if l else float('inf'):5.2f} {R:+7.1f}")
    print(f"--- paired vs e25 by candle (Δnet, bootstrap CI90 over candles, P(Δ<0)); per tf+side, all; months with Δ>0 / months ---")
    rng = np.random.default_rng(0)
    for v in order:
        if v == "e25":
            continue
        parts = []; all_d = []; mon_d = defaultdict(float)
        for tf in TFS:
            for side in SIDES:
                o = out[(tf, side)]; r = o["res"][v]; b = o["res"]["e25"]
                dv = defaultdict(float); db = defaultdict(float); cm = {}
                for k, p in zip(r["first_idx"], r["pnl"]):
                    dv[o["cid"][k]] += p; cm[o["cid"][k]] = o["month"][k]
                for k, p in zip(b["first_idx"], b["pnl"]):
                    db[o["cid"][k]] += p; cm[o["cid"][k]] = o["month"][k]
                keys = set(dv) | set(db)
                d = np.array([dv.get(c, 0.0) - db.get(c, 0.0) for c in keys]) if keys else np.zeros(1)
                for c in keys:
                    mon_d[cm[c]] += dv.get(c, 0.0) - db.get(c, 0.0)
                boot = np.array([rng.choice(d, len(d), replace=True).sum() for _ in range(2000)])
                parts.append(f"{d.sum():+6.0f} [{np.percentile(boot, 5):+6.0f},{np.percentile(boot, 95):+6.0f}] {np.mean(boot < 0):.2f}")
                all_d.append(d)
        d = np.concatenate(all_d); boot = np.array([rng.choice(d, len(d), replace=True).sum() for _ in range(2000)])
        mp = sum(1 for m, x in mon_d.items() if x > 0); mn = sum(1 for m, x in mon_d.items() if x != 0)
        print(f"{v:>10s} | " + " | ".join(f"{p:>26s}" for p in parts) + f" | {d.sum():+8.0f} [{np.percentile(boot, 5):+7.0f},{np.percentile(boot, 95):+7.0f}] {np.mean(boot < 0):.2f} | {mp}/{mn}")


if __name__ == "__main__":
    for name in ("2y", "oos2m"):
        out = run(name)
        table(out, name)
        print(f"--- {name}: e25 entries (gate C, hold {H}) split by the higher tf's pull-back state at the entry minute: n, net, PF, stop share, mean ---")
        for tf in (15, 60):
            for side in SIDES:
                o = out[(tf, side)]; r = o["res"]["e25"]; fi = r["first_idx"]
                for Hh in HIGHER[tf]:
                    for fam in FAMS:
                        for val in (True, False):
                            m = o["pb"][(fam, Hh)][fi] == val; p = r["pnl"][m]
                            if m.sum() == 0:
                                continue
                            w = p[p > 0].sum(); l = abs(p[p < 0].sum())
                            print(f"tf {tf:3d} {side:5s} by H {Hh:3d} {fam:4s} = {str(val):5s}: n {m.sum():6d}, net {p.sum():+8.0f}, PF {w / l if l else float('inf'):4.2f}, "
                                  f"stop {np.mean(o['reason'][fi][m] == 1):.2f}, mean {p.mean():+6.2f}")
        print(f"--- {name}: e25 entries, static tf-60 veto (class against) x xd / cf0 / ovc at the entry minute (tf 15): n, net ---")
        for side in SIDES:
            o = out[(15, side)]; r = o["res"]["e25"]; fi = r["first_idx"]
            st = ~o["fv"][60][fi]
            for fam in ("xd", "cf0", "ovc", "any"):
                pb = o["pb"][(fam, 60)][fi]
                cells = []
                for a in (True, False):
                    for b in (True, False):
                        m = (st == a) & (pb == b); cells.append(f"static {a} PB {b}: n {m.sum()} {r['pnl'][m].sum():+.0f}")
                print(f"tf 15 {side:5s} {fam:4s}: " + "; ".join(cells))
