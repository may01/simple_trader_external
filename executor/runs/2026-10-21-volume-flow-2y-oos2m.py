#!/usr/bin/env python3
"""Tier B stand-in for the volume-flow entry filters: the 1-/5-/15-min taker-flow imbalance and the relative volume at the
CB zone candidate minute as a veto on the own entry, over 2y (2023-01 -> 2024-12) and oos2m (2025-01 -> 2025-03) from
the stored 1-min frames. Flow = the bounds-geometry stand-in unchanged (set-C candidate minutes = inzone and overshoot
pass; first passing minute per tf candle; entry = 1_close; candle stop; cbnc target; max hold H; size min(100/dist,
50000/entry); no fees); the veto per (tf, side) is ANDed into the own forming EMA-25 flag (e25).

Flow quantities at row t (closed 1-min rows t-w+1..t, nothing after t; the frame's `volume` = base volume, `taker_base_vol`
= taker-buy base volume, both per 1-min row):
  vol{w} = sum volume; buy{w} = sum taker_base_vol; net{w} = 2 buy{w} - vol{w} (buy - sell); imb{w} = net{w} / vol{w}
  adv{w} = +imb for a long entry, -imb for a short entry (> 0: flow agrees with the trade)
  rv{w}  = vol{w} / median over the trailing 120 rows of vol{w} (relative volume, the paper harness's definition up to
           bucket alignment)
Variants (veto when): advlt{x}_w{w} adv < -x (flow pushing into the zone); advgt{x}_w{w} adv > x (mirror / "reversal
started" tail); rvgt{k}_w{w} rv > k (climax); rvlt{k}_w{w} rv < k (dead tape); sh_* = the same read 1440 rows earlier
(placebo). Thresholds FROZEN on 2y (best paired Δ vs e25 on the tf-15 cells, entry retention >= 60 %), oos2m scored
with them; full grids printed on both tiers for transparency only.
usage: python3 2026-10-21-volume-flow-2y-oos2m.py [--hold=60] [--only=2y|oos2m]
"""
import sys, time, resource
import numpy as np, pandas as pd, talib
from collections import defaultdict

V = "/media/om/Alexandria/simple_trader/simple_trader_vol_long/train"
H = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--hold=")), 60))
ONLY = next((a.split("=")[1] for a in sys.argv if a.startswith("--only=")), "")
TFS = (15, 60, 240); SIDES = ("long", "short"); W = 105; X = 0.5
FROZEN25 = {15: (0.0018696074433414492, 0.08854754765129406), 60: (0.007586181744923595, 0.17365581448454287),
            240: (0.03083283482398462, 0.3443346525283253)}
THR = {15: {"long": 0.3477, "short": 0.3808}, 60: {"long": 0.3756, "short": 0.3796}, 240: {"long": 0.4693, "short": 0.5178}}
RISK = 100.0; CAP = 100_000 * 0.5; PLACEHOLDER = 0.002; RANGE_N = 60; SHIFT = 1440; EXZ_ATR = 1.0
ZONE_FRAC = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--zone-frac=")), "nan"))
HIGHER = {15: (60, 240), 60: (240,), 240: ()}
PAIRS = {"15<60": {15: (60,)}, "15<240": {15: (240,)}, "60<240": {60: (240,)}, "ladder": HIGHER}
WS = (1, 5, 15); XS = (0.1, 0.2, 0.3, 0.5); KHI = (1.5, 2.0, 3.0); KLO = (0.5, 0.7)
RETAIN = 0.6
ABINS = np.array([-1.0, -0.5, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.5, 1.0001]); RBINS = np.array([0.0, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 1e9])


def rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def candle_id(closed):
    return np.concatenate(([0], np.cumsum(closed)[:-1]))


BASE = ["1_high", "1_low", "1_close"] + [f"{tf}_{c}" for tf in TFS for c in ("close", "is_closed")]
CBC = [f"{tf}_{c}" for tf in TFS for c in ("cb_low", "cb_high", "cb_low_std", "cb_high_std", "cb_inzone_long", "cb_inzone_short")]
NCC = [f"{tf}_{c}" for tf in TFS for c in ("cbnc_high", "cbnc_low")]


def load(name):
    global ZONE_FRAC
    t0 = time.time()
    if name == "2y":
        df = pd.read_pickle(f"{V}/2y_az_link_usdt/df_with_indicators.pkl")[BASE].copy()
        atr = pd.concat([pd.read_pickle(f"{V}/2y_link_usdt/df_with_indicators.part_{k:02d}.pkl")[["1_atr_14_ma_5", "volume", "taker_base_vol"]] for k in range(25)])
        cbf = pd.read_pickle(f"{V}/2y_link_usdt/df_with_candle_bounds.pkl")
        zc = [f"{tf}_cb_zone_{s}" for tf in TFS for s in SIDES if f"{tf}_cb_zone_{s}" in cbf.columns]
        cb = cbf[CBC + zc].copy(); del cbf
        nc = pd.read_pickle(f"{V}/2y_link_usdt/df_with_candle_bounds_nc.pkl")[NCC].copy()
        df = pd.concat([df, atr.reindex(df.index), cb.reindex(df.index), nc.reindex(df.index)], axis=1)
    else:
        zc = [f"{tf}_cb_zone_{s}" for tf in TFS for s in SIDES]
        df = pd.read_pickle(f"{V}/oos2m_link_usdt/df_with_indicators.pkl")[BASE + ["1_atr_14_ma_5", "volume", "taker_base_vol"] + CBC + NCC + zc].copy()
    # zone lines: stored when present, else lo + ZONE_FRAC * span (ZONE_FRAC recovered from a stored frame)
    for tf in TFS:
        lo = df[f"{tf}_cb_low"].to_numpy(float); hi = df[f"{tf}_cb_high"].to_numpy(float); span = hi - lo
        if f"{tf}_cb_zone_long" in df.columns:
            zl = df[f"{tf}_cb_zone_long"].to_numpy(float)
            ok = np.isfinite(zl) & np.isfinite(span) & (span > 0)
            fr = np.median((zl[ok] - lo[ok]) / span[ok])
            if not np.isfinite(ZONE_FRAC):
                ZONE_FRAC = float(fr)
            print(f"[{name}] tf {tf:3d}: stored zone_long = lo + {fr:.4f} * span (ZONE_FRAC in use {ZONE_FRAC:.4f})")
        else:
            assert np.isfinite(ZONE_FRAC), "ZONE_FRAC unknown: pass --zone-frac or run oos2m first"
            df[f"{tf}_cb_zone_long"] = lo + ZONE_FRAC * span
            df[f"{tf}_cb_zone_short"] = hi - ZONE_FRAC * span
            print(f"[{name}] tf {tf:3d}: zone lines derived with ZONE_FRAC {ZONE_FRAC:.4f}")
    print(f"[{name}] {df.shape} {df.index[0]} -> {df.index[-1]} loaded {time.time() - t0:.0f}s RSS {rss():.0f} MB; "
          f"atr finite {np.isfinite(df['1_atr_14_ma_5'].to_numpy(float)).mean():.3f}", flush=True)
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
    mu, sd = FROZEN25[tf]
    cl = np.where(d_f < mu - X * sd, -1, np.where(d_f > mu + X * sd, 1, 0)).astype(np.int8); cl[~np.isfinite(d_f)] = 0
    return cl, cid


def seg_cummax(active, seg):
    return pd.Series(active).groupby(seg).cummax().to_numpy(bool)


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


def q(a, ps=(0.05, 0.25, 0.5, 0.75, 0.95)):
    a = a[np.isfinite(a)]
    return " ".join(f"{np.percentile(a, p * 100):+.2f}" for p in ps) if len(a) else "n/a"


def pf_of(p):
    w = p[p > 0].sum(); l = abs(p[p < 0].sum())
    return w / l if l else float("inf")


def cell(p, reason=None):
    if len(p) == 0:
        return "n 0"
    s = f"n {len(p):6d} net {p.sum():+8.0f} PF {pf_of(p):4.2f} mean {p.mean():+6.2f}"
    if reason is not None:
        s += f" stop {np.mean(reason == 1):.2f}"
    return s



def flow_features(df):
    vol = df["volume"].to_numpy(float); buy = df["taker_base_vol"].to_numpy(float)
    bad = ~np.isfinite(vol) | ~np.isfinite(buy)
    print(f"volume rows finite {1 - bad.mean():.4f}; taker/volume q {q(buy / np.where(vol > 0, vol, np.nan))}")
    F = {}
    sv = pd.Series(vol); sb = pd.Series(buy)
    for w in WS:
        v = sv.rolling(w, min_periods=w).sum(); b = sb.rolling(w, min_periods=w).sum()
        net = 2 * b - v
        imb = (net / v.where(v > 0)).to_numpy(float)
        med = v.rolling(120, min_periods=24).median()
        rv = (v / med.where(med > 0)).to_numpy(float)
        F[f"imb{w}"] = imb; F[f"rv{w}"] = rv
        F[f"imb{w}_sh"] = np.r_[np.full(SHIFT, np.nan), imb[:-SHIFT]]; F[f"rv{w}_sh"] = np.r_[np.full(SHIFT, np.nan), rv[:-SHIFT]]
        print(f"  w {w:2d}: imb q {q(imb)}; rv q {q(rv)}; finite {np.isfinite(imb).mean():.3f} / {np.isfinite(rv).mean():.3f}")
    return F


def run(name):
    df = load(name)
    F = flow_features(df)
    CLS = {}; CID = {}
    for tf in TFS:
        CLS[tf], CID[tf] = classes(df, tf)
    OVA = {}
    for tf in TFS:
        for side in SIDES:
            b = df[f"{tf}_cb_low" if side == "long" else f"{tf}_cb_high"].to_numpy(float)
            w = df[f"{tf}_cb_low_std" if side == "long" else f"{tf}_cb_high_std"].to_numpy(float)
            x = df["1_low" if side == "long" else "1_high"].to_numpy(float)
            over = (b - x) / w if side == "long" else (x - b) / w
            OVA[(tf, side)] = over > THR[tf][side]
    month = pd.DatetimeIndex(df.index).to_period("M").astype(str).to_numpy()
    out = {}
    for tf in TFS:
        cid = CID[tf]
        for side in SIDES:
            inz = df[f"{tf}_cb_inzone_{side}"].fillna(False).to_numpy(bool)
            cand = inz & ~OVA[(tf, side)]
            idx, pnl, reason, size, dist, kind = simulate_all(df, tf, side, cand)
            bad = -1 if side == "long" else 1
            e25 = CLS[tf][idx] != bad
            sgn = 1.0 if side == "long" else -1.0
            G = {}
            for w in WS:
                G[f"adv{w}"] = F[f"imb{w}"][idx] * sgn; G[f"rv{w}"] = F[f"rv{w}"][idx]
                G[f"adv{w}_sh"] = F[f"imb{w}_sh"][idx] * sgn; G[f"rv{w}_sh"] = F[f"rv{w}_sh"][idx]
            VETO = {}
            with np.errstate(invalid="ignore"):
                for w in WS:
                    for x in XS:
                        VETO[f"advlt{x}_w{w}"] = G[f"adv{w}"] < -x
                        VETO[f"advgt{x}_w{w}"] = G[f"adv{w}"] > x
                        VETO[f"sh_advlt{x}_w{w}"] = G[f"adv{w}_sh"] < -x
                    for k in KHI:
                        VETO[f"rvgt{k}_w{w}"] = G[f"rv{w}"] > k
                        VETO[f"sh_rvgt{k}_w{w}"] = G[f"rv{w}_sh"] > k
                    for k in KLO:
                        VETO[f"rvlt{k}_w{w}"] = G[f"rv{w}"] < k
                VETO["advlt0.2_w5&rvgt1.5_w5"] = (G["adv5"] < -0.2) & (G["rv5"] > 1.5)
                VETO["advlt0.2_w5|rvgt2.0_w5"] = (G["adv5"] < -0.2) | (G["rv5"] > 2.0)
            one = np.ones(len(idx), dtype=bool)
            flags = {"none": one, "e25": e25}
            for v, vt in VETO.items():
                flags[v] = e25 & ~vt
            cid_e = cid[idx]
            res = {}
            for v, fl in flags.items():
                first = np.zeros(len(idx), dtype=bool); seen = set()
                for k in np.flatnonzero(fl):
                    c = cid_e[k]
                    if c not in seen:
                        seen.add(c); first[k] = True
                p = pnl[first]
                res[v] = dict(n=int(first.sum()), net=float(p.sum()), pf=pf_of(p), wr=float(np.mean(p > 0)) if len(p) else float("nan"),
                              stop=int((reason[first] == 1).sum()), tgt=int((reason[first] == 2).sum()), hold=int((reason[first] == 3).sum()),
                              R=float((p / (size[first] * dist[first])).sum()), first_idx=np.flatnonzero(first), pnl=p)
            out[(tf, side)] = dict(res=res, idx=idx, pnl=pnl, reason=reason, cid=cid_e, flags=flags, G=G, VETO=VETO, month=month[idx], e25=e25,
                                   size=size, dist=dist)
            r = res["e25"]
            print(f"[{name}] tf {tf:3d} {side:5s}: candidates {len(idx)} in {len(np.unique(cid_e))} candles; e25 entries {r['n']} net {r['net']:+.0f} "
                  f"PF {r['pf']:.2f} wr {r['wr']:.2f} stop/tgt/hold {r['stop']}/{r['tgt']}/{r['hold']} | placeholder stops {kind.mean():.1%} RSS {rss():.0f} MB", flush=True)
    del df
    return out


def paired(out, v, tfs=TFS, sides=SIDES, rng=None):
    rng = rng or np.random.default_rng(0)
    all_d = []; mon_d = defaultdict(float)
    for tf in tfs:
        for side in sides:
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
            all_d.append(d)
    d = np.concatenate(all_d)
    boot = np.array([rng.choice(d, len(d), replace=True).sum() for _ in range(2000)])
    mp = sum(1 for x in mon_d.values() if x > 0); mn = sum(1 for x in mon_d.values() if x != 0)
    return float(d.sum()), float(np.percentile(boot, 5)), float(np.percentile(boot, 95)), float(np.mean(boot < 0)), mp, mn


def table(out, name, variants, title):
    print(f"\n=== {name}, {title}: hold {H} min: entries, net USDT, PF, win rate, stop/target/hold | ALL; paired Δ vs e25 by candle (CI90, P(Δ<0)) months+/months ===")
    print(f"{'variant':>24s} | " + " | ".join(f"{'tf' + str(tf) + ' ' + side:>26s}" for tf in TFS for side in SIDES) + f" | {'ALL n':>6s} {'net':>8s} {'PF':>5s} | {'Δ':>8s} {'CI90':>18s} {'P':>4s} {'m+':>5s}")
    for v in variants:
        cells = []; tot_n = 0; tot = 0.0; w = 0.0; l = 0.0
        for tf in TFS:
            for side in SIDES:
                r = out[(tf, side)]["res"][v]
                cells.append(f"{r['n']:5d} {r['net']:+7.0f} {r['pf']:4.2f} {r['wr']:.2f} {r['stop']}/{r['tgt']}/{r['hold']}")
                tot_n += r["n"]; tot += r["net"]; p = r["pnl"]; w += p[p > 0].sum(); l += abs(p[p < 0].sum())
        if v == "e25":
            pd_ = ""
        else:
            s, a, b, pneg, mp, mn = paired(out, v)
            pd_ = f"{s:+8.0f} [{a:+7.0f},{b:+7.0f}] {pneg:.2f} {mp:2d}/{mn:2d}"
        print(f"{v:>24s} | " + " | ".join(f"{c:>26s}" for c in cells) + f" | {tot_n:6d} {tot:+8.0f} {w / l if l else float('inf'):5.2f} | {pd_}")


def rank(a):
    o = np.argsort(a, kind="stable"); r = np.empty(len(a)); r[o] = np.arange(len(a)); return r


def spearman(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 10: return float("nan"), int(m.sum())
    return float(np.corrcoef(rank(x[m]), rank(y[m]))[0, 1]), int(m.sum())


def splits(out, name):
    print(f"\n=== {name}: e25 entries (hold {H}) split by the flow features at the entry minute (one row per bin: n, net, PF, mean, stop share) ===")
    for tf in TFS:
        for side in SIDES:
            o = out[(tf, side)]; r = o["res"]["e25"]; fi = r["first_idx"]; p = r["pnl"]; rs = o["reason"][fi]
            Rm = p / (o["size"][fi] * o["dist"][fi])
            print(f"-- tf {tf} {side}: all {cell(p, rs)}")
            for w in WS:
                a = o["G"][f"adv{w}"][fi]; rv = o["G"][f"rv{w}"][fi]
                rho, n = spearman(a, p); rhoR, _ = spearman(a, Rm); rho2, _ = spearman(rv, p); rho2R, _ = spearman(rv, Rm)
                st = (rs == 1).astype(float)
                def auc(x, y):
                    m = np.isfinite(x); x = x[m]; yb = y[m] > 0.5
                    if yb.sum() == 0 or (~yb).sum() == 0: return float("nan")
                    rk = rank(x); return float((rk[yb].sum() - yb.sum() * (yb.sum() - 1) / 2) / (yb.sum() * (~yb).sum()))
                print(f"   w {w:2d}: Spearman(adv, pnl) {rho:+.3f} (R {rhoR:+.3f}) AUC(adv->stop) {auc(a, st):.3f} | Spearman(rv, pnl) {rho2:+.3f} (R {rho2R:+.3f}) AUC(rv->stop) {auc(rv, st):.3f}; n {n}")
                for lo_, hi_ in zip(ABINS[:-1], ABINS[1:]):
                    m = (a >= lo_) & (a < hi_)
                    if m.sum(): print(f"      adv{w} [{lo_:+.1f},{hi_:+.1f}): {cell(p[m], rs[m])}")
                for lo_, hi_ in zip(RBINS[:-1], RBINS[1:]):
                    m = (rv >= lo_) & (rv < hi_)
                    if m.sum(): print(f"      rv{w} [{lo_:g},{hi_:g}): {cell(p[m], rs[m])}")


def select(out):
    base = sum(out[(15, s)]["res"]["e25"]["n"] for s in SIDES)
    frozen = {}
    print(f"\n=== 2y selection (cells tf 15 long+short, retention >= {RETAIN:.0%}): one (threshold, window) per family ===")
    fams = {"advlt": [f"advlt{x}_w{w}" for w in WS for x in XS], "advgt": [f"advgt{x}_w{w}" for w in WS for x in XS],
            "rvgt": [f"rvgt{k}_w{w}" for w in WS for k in KHI], "rvlt": [f"rvlt{k}_w{w}" for w in WS for k in KLO]}
    for fam, vs in fams.items():
        best = None
        for v in vs:
            n = sum(out[(15, s)]["res"][v]["n"] for s in SIDES)
            s, a, b, pneg, mp, mn = paired(out, v, tfs=(15,))
            keep = n / base
            print(f"   {v:>16s}: entries {n} ({keep:.2f} of e25) Δ {s:+8.0f} [{a:+7.0f},{b:+7.0f}] P {pneg:.2f} months+ {mp}/{mn}" + ("" if keep >= RETAIN else "  (below retention floor)"))
            if keep >= RETAIN and (best is None or s > best[1]):
                best = (v, s)
        frozen[fam] = best[0] if best else vs[0]
        print(f"   -> frozen {fam} = {frozen[fam]}")
    return frozen


def frozen_variants(frozen):
    vs = ["none", "e25"] + [frozen[f] for f in ("advlt", "advgt", "rvgt", "rvlt")]
    for f in ("advlt", "rvgt"):
        vs.append("sh_" + frozen[f])
    vs += ["advlt0.2_w5&rvgt1.5_w5", "advlt0.2_w5|rvgt2.0_w5"]
    return vs


def grid_variants():
    vs = ["none", "e25"]
    for w in WS:
        vs += [f"advlt{x}_w{w}" for x in XS] + [f"advgt{x}_w{w}" for x in XS] + [f"rvgt{k}_w{w}" for k in KHI] + [f"rvlt{k}_w{w}" for k in KLO]
        vs += [f"sh_advlt{x}_w{w}" for x in XS] + [f"sh_rvgt{k}_w{w}" for k in KHI]
    vs += ["advlt0.2_w5&rvgt1.5_w5", "advlt0.2_w5|rvgt2.0_w5"]
    return vs


if __name__ == "__main__":
    t0 = time.time()
    frozen = None
    if ONLY in ("", "2y"):
        out = run("2y")
        splits(out, "2y")
        table(out, "2y", grid_variants(), "FULL GRID (selection tier)")
        frozen = select(out)
        table(out, "2y", frozen_variants(frozen), f"FROZEN {frozen}")
        del out
    if ONLY in ("", "oos2m"):
        if frozen is None:
            fz = next((a.split("=")[1] for a in sys.argv if a.startswith("--frozen=")), "")
            assert fz, "pass --frozen=advlt:advlt0.2_w5,advgt:...,rvgt:...,rvlt:..."
            frozen = dict(kv.split(":") for kv in fz.split(","))
            print(f"frozen values passed on the command line: {frozen}")
        out = run("oos2m")
        splits(out, "oos2m")
        table(out, "oos2m", frozen_variants(frozen), f"FROZEN ON 2y {frozen} — the score")
        table(out, "oos2m", grid_variants(), "FULL GRID (post hoc, NOT for selection)")
    print(f"\ndone in {time.time() - t0:.0f}s, RSS {rss():.0f} MB")
