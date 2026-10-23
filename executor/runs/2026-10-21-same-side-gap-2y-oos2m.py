#!/usr/bin/env python3
"""Tier B: a close HIGHER-tf zone on the SAME side as a lower-tf CB zone entry — veto the lower entry, or delay it to a
limit at the higher zone — over 2y (2023-01 -> 2024-12) and oos2m (2025-01 -> 2025-03) from the stored 1-min frames.
Flow = the higher_tf_bounds_geometry tier-B stand-in (set-C candidate minutes = inzone and overshoot pass; first passing
minute per tf candle; entry = 1_close; candle stop = 15-min running extreme -/+ trailing-60 mean 1-min range; cbnc
target; max hold H; size min(100/dist, 50000/entry); no fees); the veto per (tf, side) is ANDed into the own forming
EMA-25 flag (e25).

Quantities at a row for the higher tf H (long side shown; short mirrored):
  g      (close - H_cb_zone_long) / ATR1      signed gap to H's same-side zone line; > 0 = H's zone beyond the entry on the stop side
  gd     g * ATR1 / dist                      the same gap in units of the entry's candle-stop distance
  mr     (H_cb_zone_short - close) / ATR1     control: gap to H's OPPOSITE zone (room)
  sh     g read 1440 rows earlier             placebo
Variants (veto when): gz{k} 0 <= g < k; gzb{k} |g| < k; gzin g < 0; gd{m} 0 <= gd < m; mr{k} 0 <= mr < k; sh{k} 0 <= sh < k.
Delay: dl{k}N — when 0 <= g < k the e25 entry is NOT taken at the fire minute; a limit at H's zone line (frozen at the
fire) is live for N rows; fill at the line (1_low <= line), stop = min(prev 15-min extreme, line) - range, cbnc target
at the fill, hold H from the fill; unfilled = no entry. dlc{k}N additionally requires the 1-min forming class at the
fill not to be against the trade (class source: own-tf forming EMA-25 class, the stand-in's only class).
Thresholds are FROZEN on 2y (paired delta vs e25 on the 15<60 pair, entry retention >= 60 % for vetoes) and oos2m is
scored with them; the full grids are printed on both tiers for transparency only.
usage: python3 2026-10-21-same-side-gap-2y-oos2m.py [--hold=60] [--only=2y|oos2m] [--gz=k --gd=m --dl=k,N]
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
RISK = 100.0; CAP = 100_000 * 0.5; PLACEHOLDER = 0.002; RANGE_N = 60; SHIFT = 1440
ZONE_FRAC = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--zone-frac=")), "nan"))
HIGHER = {15: (60, 240), 60: (240,), 240: ()}
PAIRS = {"15<60": {15: (60,)}, "15<240": {15: (240,)}, "60<240": {60: (240,)}, "ladder": HIGHER}
KS = (0.5, 1.0, 2.0, 3.0, 5.0); MS = (0.5, 1.0, 1.5, 2.0, 3.0); DLN = (15, 60); DLK = (1.0, 2.0, 3.0, 5.0)
RETAIN = 0.6
GBINS = ((-99, -2), (-2, -1), (-1, 0), (0, 0.5), (0.5, 1), (1, 2), (2, 3), (3, 5), (5, 8), (8, 999))
DBINS = ((-99, 0), (0, 0.5), (0.5, 1), (1, 1.5), (1.5, 2), (2, 3), (3, 5), (5, 999))
REACH_ROWS = 60


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
        atr = pd.concat([pd.read_pickle(f"{V}/2y_link_usdt/df_with_indicators.part_{k:02d}.pkl")[["1_atr_14_ma_5"]] for k in range(25)])
        cbf = pd.read_pickle(f"{V}/2y_link_usdt/df_with_candle_bounds.pkl")
        zc = [f"{tf}_cb_zone_{s}" for tf in TFS for s in SIDES if f"{tf}_cb_zone_{s}" in cbf.columns]
        cb = cbf[CBC + zc].copy(); del cbf
        nc = pd.read_pickle(f"{V}/2y_link_usdt/df_with_candle_bounds_nc.pkl")[NCC].copy()
        df = pd.concat([df, atr.reindex(df.index), cb.reindex(df.index), nc.reindex(df.index)], axis=1)
    else:
        zc = [f"{tf}_cb_zone_{s}" for tf in TFS for s in SIDES]
        df = pd.read_pickle(f"{V}/oos2m_link_usdt/df_with_indicators.pkl")[BASE + ["1_atr_14_ma_5"] + CBC + NCC + zc].copy()
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


class Px:
    """price arrays + the candle-stop material shared by every simulation on a frame"""
    def __init__(self, df):
        self.hi, self.lo, self.cl = (df[c].to_numpy(float) for c in ("1_high", "1_low", "1_close"))
        self.n = len(self.cl)
        cid15 = candle_id((df["15_is_closed"] == True).to_numpy())  # noqa: E712
        self.ext = {"long": pd.Series(self.lo).groupby(cid15).cummin().to_numpy(),
                    "short": pd.Series(self.hi).groupby(cid15).cummax().to_numpy()}
        # the extreme known BEFORE row j (previous rows of the same 15-min candle; nan at the candle's first row)
        prev = {s: np.r_[np.nan, self.ext[s][:-1]] for s in SIDES}
        first = np.r_[True, cid15[1:] != cid15[:-1]]
        for s in SIDES:
            prev[s][first] = np.nan
        self.ext_prev = prev
        self.rng = pd.Series(self.hi - self.lo).shift(1).rolling(RANGE_N, min_periods=1).mean().to_numpy()


def sim_one(P, side, e, stop, t, a, b):
    """entry e at row a-1 (stop/target checked from row a to b-1); returns pnl, reason, size, dist, placeholder"""
    kind = 0
    if not np.isfinite(stop) or (side == "long" and stop >= e) or (side == "short" and stop <= e):
        stop = e * (1 - PLACEHOLDER) if side == "long" else e * (1 + PLACEHOLDER); kind = 1
    dist = abs(e - stop); size = min(RISK / dist, CAP / e)
    sgn = 1.0 if side == "long" else -1.0
    if side == "long":
        hs = P.lo[a:b] <= stop; ht = P.hi[a:b] >= t if np.isfinite(t) else np.zeros(b - a, dtype=bool)
    else:
        hs = P.hi[a:b] >= stop; ht = P.lo[a:b] <= t if np.isfinite(t) else np.zeros(b - a, dtype=bool)
    js = int(np.argmax(hs)) if hs.any() else 10 ** 9; jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
    if js <= jt and js < 10 ** 9:
        x, r = stop, 1
    elif jt < 10 ** 9:
        x, r = t, 2
    else:
        x, r = P.cl[b - 1], 3
    return (x - e) * size * sgn, r, size, dist, kind


def simulate_all(P, tgt, side, idx):
    pnl = np.zeros(len(idx)); reason = np.zeros(len(idx), dtype=np.int8); size = np.zeros(len(idx)); dist = np.zeros(len(idx)); kind = np.zeros(len(idx), dtype=np.int8)
    for k, i0 in enumerate(idx):
        e = P.cl[i0]
        stop = P.ext[side][i0] - P.rng[i0] if side == "long" else P.ext[side][i0] + P.rng[i0]
        pnl[k], reason[k], size[k], dist[k], kind[k] = sim_one(P, side, e, stop, tgt[i0], i0 + 1, min(i0 + 1 + H, P.n))
    return pnl, reason, size, dist, kind


def simulate_delayed(P, tgt, side, i0, line, nrows, cls=None):
    """limit at `line` live for rows i0+1 .. i0+nrows; fill at the line; stop from the extreme known at the fill"""
    a, b = i0 + 1, min(i0 + 1 + nrows, P.n)
    hit = P.lo[a:b] <= line if side == "long" else P.hi[a:b] >= line
    if cls is not None:
        hit &= cls[a:b] != (-1 if side == "long" else 1)
    if not hit.any():
        return 0.0, 4, 0.0, 0.0, 0, -1
    j = a + int(np.argmax(hit))
    if side == "long":
        anchor = np.nanmin([P.ext_prev["long"][j], line]); stop = anchor - P.rng[j]
    else:
        anchor = np.nanmax([P.ext_prev["short"][j], line]); stop = anchor + P.rng[j]
    pnl, r, size, dist, kind = sim_one(P, side, line, stop, tgt[j], j, min(j + 1 + H, P.n))
    return pnl, r, size, dist, kind, j


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


def first_per_candle(fl, cid_e):
    first = np.zeros(len(fl), dtype=bool); seen = set()
    for k in np.flatnonzero(fl):
        c = cid_e[k]
        if c not in seen:
            seen.add(c); first[k] = True
    return first


def pack(cids, pnl, reason, size, dist, months, extra=None):
    taken = reason != 4
    p = pnl[taken]
    d = dict(n=int(taken.sum()), net=float(p.sum()), pf=pf_of(p), wr=float(np.mean(p > 0)) if len(p) else float("nan"),
             stop=int((reason == 1).sum()), tgt=int((reason == 2).sum()), hold=int((reason == 3).sum()), unf=int((reason == 4).sum()),
             R=float((p / (size[taken] * dist[taken])).sum()) if taken.any() else 0.0, cids=cids, pnl=pnl, reason=reason, months=months)
    if extra:
        d.update(extra)
    return d


def run(name):
    df = load(name)
    n = len(df); P = Px(df)
    close = P.cl; atr = df["1_atr_14_ma_5"].to_numpy(float)
    ok_atr = np.isfinite(atr) & (atr > 0); satr = np.where(ok_atr, atr, np.nan)
    CLS = {}; CID = {}; OVA = {}; ZL = {}; ZS = {}; G = {}; MR = {}
    for tf in TFS:
        CLS[tf], CID[tf] = classes(df, tf)
        lo = df[f"{tf}_cb_low"].to_numpy(float); hi = df[f"{tf}_cb_high"].to_numpy(float)
        for side in SIDES:
            b = lo if side == "long" else hi
            w = df[f"{tf}_cb_low_std" if side == "long" else f"{tf}_cb_high_std"].to_numpy(float)
            x = df["1_low" if side == "long" else "1_high"].to_numpy(float)
            over = (b - x) / w if side == "long" else (x - b) / w
            OVA[(tf, side)] = over > THR[tf][side]
        ZL[tf] = df[f"{tf}_cb_zone_long"].to_numpy(float); ZS[tf] = df[f"{tf}_cb_zone_short"].to_numpy(float)
        with np.errstate(invalid="ignore"):
            G[(tf, "long")] = (close - ZL[tf]) / satr; G[(tf, "short")] = (ZS[tf] - close) / satr
            MR[(tf, "long")] = (ZS[tf] - close) / satr; MR[(tf, "short")] = (close - ZL[tf]) / satr
        print(f"[{name}] tf {tf:3d}: zone lines finite {np.isfinite(ZL[tf]).mean():.3f}; g long q {q(G[(tf, 'long')])} | g short q {q(G[(tf, 'short')])}; "
              f"e25 +1 {np.mean(CLS[tf] == 1):.3f} -1 {np.mean(CLS[tf] == -1):.3f}", flush=True)
    GSH = {k: np.r_[np.full(SHIFT, np.nan), v[:-SHIFT]] for k, v in G.items()}
    month = pd.DatetimeIndex(df.index).to_period("M").astype(str).to_numpy()
    out = {}
    for tf in TFS:
        cid = CID[tf]
        for side in SIDES:
            inz = df[f"{tf}_cb_inzone_{side}"].fillna(False).to_numpy(bool)
            cand = inz & ~OVA[(tf, side)]
            idx = np.flatnonzero(cand)
            tgt = df[f"{tf}_cbnc_high" if side == "long" else f"{tf}_cbnc_low"].to_numpy(float)
            pnl, reason, size, dist, kind = simulate_all(P, tgt, side, idx)
            bad = -1 if side == "long" else 1
            e25 = CLS[tf][idx] != bad
            cid_e = cid[idx]; mon = month[idx]
            # geometry at the candidates per higher tf
            GG = {}
            for Hh in TFS:
                g = G[(Hh, side)][idx]
                GG[Hh] = dict(g=g, gd=g * satr[idx] / dist, mr=MR[(Hh, side)][idx], sh=GSH[(Hh, side)][idx],
                              line=(ZL[Hh] if side == "long" else ZS[Hh])[idx])
            VETO = {}
            for Hh in TFS:
                gg = GG[Hh]
                with np.errstate(invalid="ignore"):
                    for kk in KS:
                        VETO[(f"gz{kk}", Hh)] = (gg["g"] >= 0) & (gg["g"] < kk)
                        VETO[(f"gzb{kk}", Hh)] = np.abs(gg["g"]) < kk
                        VETO[(f"mr{kk}", Hh)] = (gg["mr"] >= 0) & (gg["mr"] < kk)
                        VETO[(f"sh{kk}", Hh)] = (gg["sh"] >= 0) & (gg["sh"] < kk)
                    for mm in MS:
                        VETO[(f"gd{mm}", Hh)] = (gg["gd"] >= 0) & (gg["gd"] < mm)
                    VETO[("gzin", Hh)] = gg["g"] < 0
            fams = sorted({k[0] for k in VETO})
            flags = {"none": np.ones(len(idx), dtype=bool), "e25": e25}
            for fam in fams:
                for pk, rule in PAIRS.items():
                    fl = e25.copy()
                    for Hh in rule.get(tf, ()):
                        fl &= ~VETO[(fam, Hh)]
                    flags[f"{fam}|{pk}"] = fl
            res = {}
            for v, fl in flags.items():
                first = first_per_candle(fl, cid_e)
                res[v] = pack(cid_e[first], pnl[first], reason[first], size[first], dist[first], mon[first])
            # delay variants on the e25 first entries, per pair (the limit at the FIRST vetoing H of the pair; 15<60 primary)
            f25 = first_per_candle(e25, cid_e); fi = np.flatnonzero(f25)
            for pk, rule in PAIRS.items():
                hs = rule.get(tf, ())
                if not hs:
                    for kk in DLK:
                        for nn in DLN:
                            for lab in ("dl", "dlc"):
                                res[f"{lab}{kk}{nn}|{pk}"] = res["e25"]
                    continue
                for kk in DLK:
                    for nn in DLN:
                        for lab, cls in (("dl", None), ("dlc", CLS[tf])):
                            p = pnl[fi].copy(); r = reason[fi].copy(); sz = size[fi].copy(); ds = dist[fi].copy()
                            nrep = 0; fills = 0; fill_rows = []
                            for m, k in enumerate(fi):
                                hit = [Hh for Hh in hs if VETO[(f"gz{kk}", Hh)][k]]
                                if not hit:
                                    continue
                                nrep += 1
                                line = GG[hit[0]]["line"][k]
                                p[m], r[m], sz[m], ds[m], _, j = simulate_delayed(P, tgt, side, idx[k], line, nn, cls)
                                if r[m] != 4:
                                    fills += 1; fill_rows.append(j - idx[k])
                            res[f"{lab}{kk}{nn}|{pk}"] = pack(cid_e[fi], p, r, sz, ds, mon[fi],
                                                              extra=dict(replaced=nrep, fills=fills, fill_rows=np.array(fill_rows)))
            out[(tf, side)] = dict(res=res, idx=idx, pnl=pnl, reason=reason, size=size, dist=dist, cid=cid_e, G=GG, VETO=VETO, month=mon, e25=e25, f25=f25)
            r = res["e25"]
            print(f"[{name}] tf {tf:3d} {side:5s}: candidates {len(idx)} in {len(np.unique(cid_e))} candles; e25 entries {r['n']} net {r['net']:+.0f} "
                  f"PF {r['pf']:.2f} wr {r['wr']:.2f} stop/tgt/hold {r['stop']}/{r['tgt']}/{r['hold']} | placeholder stops {kind.mean():.1%} RSS {rss():.0f} MB", flush=True)
    out["_P"] = P; out["_ZL"] = ZL; out["_ZS"] = ZS
    del df
    return out


def paired(out, v, tfs=TFS, sides=SIDES, rng=None):
    """paired Δ vs e25 by candle: (sum, ci5, ci95, P(Δ<0), months+, months) over the given cells."""
    rng = rng or np.random.default_rng(0)
    all_d = []; mon_d = defaultdict(float)
    for tf in tfs:
        for side in sides:
            o = out[(tf, side)]; r = o["res"][v]; b = o["res"]["e25"]
            dv = defaultdict(float); db = defaultdict(float); cm = {}
            for c, p, m in zip(r["cids"], r["pnl"], r["months"]):
                dv[c] += p; cm[c] = m
            for c, p, m in zip(b["cids"], b["pnl"], b["months"]):
                db[c] += p; cm[c] = m
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
    print(f"\n=== {name}, {title}: hold {H} min: entries, net USDT, PF, win rate, stop/target/hold(/unfilled) | ALL; paired Δ vs e25 by candle (CI90, P(Δ<0)) months+/months ===")
    print(f"{'variant':>16s} | " + " | ".join(f"{'tf' + str(tf) + ' ' + side:>28s}" for tf in TFS for side in SIDES) + f" | {'ALL n':>6s} {'net':>8s} {'PF':>5s} | {'Δ':>8s} {'CI90':>18s} {'P':>4s} {'m+':>5s}")
    for v in variants:
        cells = []; tot_n = 0; tot = 0.0; w = 0.0; l = 0.0
        for tf in TFS:
            for side in SIDES:
                r = out[(tf, side)]["res"][v]
                u = f"/{r['unf']}" if r["unf"] else ""
                cells.append(f"{r['n']:5d} {r['net']:+7.0f} {r['pf']:4.2f} {r['wr']:.2f} {r['stop']}/{r['tgt']}/{r['hold']}{u}")
                tot_n += r["n"]; tot += r["net"]; p = r["pnl"]; w += p[p > 0].sum(); l += abs(p[p < 0].sum())
        if v == "e25":
            pd_ = ""
        else:
            s, a, b, pneg, mp, mn = paired(out, v)
            pd_ = f"{s:+8.0f} [{a:+7.0f},{b:+7.0f}] {pneg:.2f} {mp:2d}/{mn:2d}"
        print(f"{v:>16s} | " + " | ".join(f"{c:>28s}" for c in cells) + f" | {tot_n:6d} {tot:+8.0f} {w / l if l else float('inf'):5.2f} | {pd_}")


def splits(out, name):
    P = out["_P"]
    print(f"\n=== {name}: e25 entries (hold {H}) split by the signed gap to the higher tf's SAME-side zone line at the entry minute ===")
    for tf in (15, 60):
        for side in SIDES:
            o = out[(tf, side)]; r = o["res"]["e25"]; fi = np.flatnonzero(o["f25"]); p = o["pnl"][fi]; rs = o["reason"][fi]; idx = o["idx"][fi]
            for Hh in HIGHER[tf]:
                gg = o["G"][Hh]; g = gg["g"][fi]; gd = gg["gd"][fi]; line = gg["line"][fi]
                # does price reach H's line within REACH_ROWS rows after the entry ("drag")?
                reach = np.zeros(len(fi), dtype=bool)
                for m, i0 in enumerate(idx):
                    a, b = i0 + 1, min(i0 + 1 + REACH_ROWS, P.n)
                    reach[m] = (P.lo[a:b] <= line[m]).any() if side == "long" else (P.hi[a:b] >= line[m]).any()
                print(f"-- tf {tf} {side} by H {Hh}: g in ATR1 (> 0 = H zone beyond the entry on the stop side) — all {cell(p, rs)}; g finite {np.isfinite(g).mean():.3f}; g q {q(g)}; gd q {q(gd)}")
                for a, b in GBINS:
                    m = (g >= a) & (g < b)
                    if m.sum():
                        print(f"   g [{a},{b}): {cell(p[m], rs[m])} reach_H_line<= {REACH_ROWS}r {reach[m].mean():.2f}")
                for a, b in DBINS:
                    m = (gd >= a) & (gd < b)
                    if m.sum():
                        print(f"   gd [{a},{b}) stop-dist: {cell(p[m], rs[m])} reach {reach[m].mean():.2f}")
                sh = gg["sh"][fi]
                for kk in (1.0, 2.0):
                    m = (sh >= 0) & (sh < kk); print(f"   placebo sh [0,{kk}): {cell(p[m], rs[m])} | else {cell(p[~m], rs[~m])}")
                mr = gg["mr"][fi]
                for kk in (1.0, 2.0):
                    m = (mr >= 0) & (mr < kk); print(f"   control mr [0,{kk}) (H opposite zone ahead): {cell(p[m], rs[m])} | else {cell(p[~m], rs[~m])}")
                # delayed-entry detail at the frozen-ish cell
                for kk in (2.0,):
                    for nn in DLN:
                        rr = o["res"][f"dl{kk}{nn}|{'15<60' if (tf, Hh) == (15, 60) else '15<240' if (tf, Hh) == (15, 240) else '60<240'}"]
                        fr = rr.get("fill_rows", np.zeros(0))
                        print(f"   dl{kk}{nn}: replaced {rr.get('replaced', 0)}, filled {rr.get('fills', 0)} ({rr.get('fills', 0) / max(rr.get('replaced', 1), 1):.2f}), fill row q {q(fr.astype(float), (0.25, 0.5, 0.75)) if len(fr) else 'n/a'}; "
                              f"net {rr['net']:+.0f} vs e25 {r['net']:+.0f}")


def select(out):
    """freeze one parameter per family on 2y: best paired Δ on the 15<60 pair (tf 15 cells); vetoes need entry retention >= RETAIN."""
    base = sum(out[(15, s)]["res"]["e25"]["n"] for s in SIDES)
    frozen = {}
    print(f"\n=== 2y selection (pair 15<60, cells tf 15 long+short, retention >= {RETAIN:.0%} for vetoes) ===")
    for fam, grid in (("gz", KS), ("gzb", KS), ("gd", MS)):
        best = None
        for g in grid:
            v = f"{fam}{g}|15<60"
            n = sum(out[(15, s)]["res"][v]["n"] for s in SIDES)
            s, a, b, pneg, mp, mn = paired(out, v, tfs=(15,))
            keep = n / base
            print(f"   {v:>14s}: entries {n} ({keep:.2f} of e25) Δ {s:+8.0f} [{a:+7.0f},{b:+7.0f}] P {pneg:.2f} months+ {mp}/{mn}" + ("" if keep >= RETAIN else "  (below retention floor)"))
            if keep >= RETAIN and (best is None or s > best[1]):
                best = (g, s)
        frozen[fam] = best[0] if best else grid[0]
        print(f"   -> frozen {fam} = {frozen[fam]}")
    for lab in ("dl", "dlc"):
        best = None
        for kk in DLK:
            for nn in DLN:
                v = f"{lab}{kk}{nn}|15<60"
                s, a, b, pneg, mp, mn = paired(out, v, tfs=(15,))
                n = sum(out[(15, s_)]["res"][v]["n"] for s_ in SIDES)
                print(f"   {v:>14s}: entries {n} Δ {s:+8.0f} [{a:+7.0f},{b:+7.0f}] P {pneg:.2f} months+ {mp}/{mn}")
                if best is None or s > best[1]:
                    best = ((kk, nn), s)
        frozen[lab] = best[0]
        print(f"   -> frozen {lab} = {frozen[lab]}")
    return frozen


def frozen_variants(frozen):
    vs = ["none", "e25"]
    for pk in PAIRS:
        vs += [f"gz{frozen['gz']}|{pk}", f"gzb{frozen['gzb']}|{pk}", f"gzin|{pk}", f"gd{frozen['gd']}|{pk}",
               f"mr{frozen['gz']}|{pk}", f"sh{frozen['gz']}|{pk}",
               f"dl{frozen['dl'][0]}{frozen['dl'][1]}|{pk}", f"dlc{frozen['dlc'][0]}{frozen['dlc'][1]}|{pk}"]
    return vs


def grid_variants():
    vs = ["none", "e25"]
    for pk in ("15<60", "ladder"):
        vs += [f"gz{kk}|{pk}" for kk in KS] + [f"gzb{kk}|{pk}" for kk in KS] + [f"gzin|{pk}"] + [f"gd{mm}|{pk}" for mm in MS]
        vs += [f"mr{kk}|{pk}" for kk in KS] + [f"sh{kk}|{pk}" for kk in KS]
        vs += [f"{lab}{kk}{nn}|{pk}" for lab in ("dl", "dlc") for kk in DLK for nn in DLN]
    for pk in ("15<240", "60<240"):
        vs += [f"gz{kk}|{pk}" for kk in KS] + [f"gd{mm}|{pk}" for mm in MS] + [f"gzin|{pk}"] + [f"dl{kk}{nn}|{pk}" for kk in (2.0,) for nn in DLN]
    return vs


def parse_frozen():
    gz = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--gz=")), KS[1]))
    gd = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--gd=")), MS[1]))
    dl = next((a.split("=")[1] for a in sys.argv if a.startswith("--dl=")), "2.0,60").split(",")
    return {"gz": gz, "gzb": gz, "gd": gd, "dl": (float(dl[0]), int(dl[1])), "dlc": (float(dl[0]), int(dl[1]))}


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
            frozen = parse_frozen()
            print(f"frozen values passed on the command line: {frozen}")
        out = run("oos2m")
        splits(out, "oos2m")
        table(out, "oos2m", frozen_variants(frozen), f"FROZEN ON 2y {frozen} — the score")
        table(out, "oos2m", grid_variants(), "FULL GRID (post hoc, NOT for selection)")
    print(f"\ndone in {time.time() - t0:.0f}s, RSS {rss():.0f} MB")
