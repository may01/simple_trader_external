#!/usr/bin/env python3
"""Tier B: how the CB bounds of 15 / 60 / 240 connect, and the HIGHER tf's range position / executed opposite bound as
a veto on the lower tf's CB zone entries, over 2y (2023-01 -> 2024-12) and oos2m (2025-01 -> 2025-03) from the stored
1-min frames. Flow = the higher_tf_pullback_veto tier-B stand-in (set-C candidate minutes = inzone and overshoot pass;
first passing minute per tf candle; entry = 1_close; candle stop; cbnc target; max hold H; size min(100/dist,
50000/entry); no fees); the veto per (tf, side) is ANDed into the own forming EMA-25 flag (e25).

Quantities at a row for the higher tf H (short side shown; long mirrored):
  pos    (close - H_cb_low) / (H_cb_high - H_cb_low)          f = pos (short) / 1 - pos (long) = favourable room share
  room   (close - H_cb_low) / ATR1                             favourable room in ATR1 (1_atr_14_ma_5)
  nest   |T_cb_low - H_cb_low| <= delta * ATR1                 the lower tf's OPPOSITE bound sits on H's same-side bound
  exz    H long zone touched earlier in the current H candle, not now, close >= 1 ATR1 above H's long zone line
Variants (veto when): pos{q} f < q; room{k} room < k; nest{d}; exz; exzpos{q} exz & f < q; mirpos{q} f > 1 - q (control);
sh{q} f < q with pos read 1440 rows earlier (placebo). Pairs 15<60, 15<240, 60<240, ladder.
The thresholds are FROZEN on 2y (paired delta vs e25 on the 15<60 pair, entry retention >= 60 %) and oos2m is scored with
them; the full grids are printed on both tiers for transparency only.
usage: python3 2026-10-21-bounds-geometry-2y-oos2m.py [--hold=60] [--only=2y|oos2m]
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
QS = (0.15, 0.25, 0.35, 0.5); KS = (1.0, 2.0, 3.0, 5.0); DS = (0.5, 1.0, 2.0)
RETAIN = 0.6
FBINS = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])


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


def geometry(df, name):
    """descriptive block over all rows: how the bounds of the tfs sit relative to each other."""
    close = df["1_close"].to_numpy(float); atr = df["1_atr_14_ma_5"].to_numpy(float)
    ok_atr = np.isfinite(atr) & (atr > 0); satr = np.where(ok_atr, atr, np.nan)
    B = {tf: (df[f"{tf}_cb_low"].to_numpy(float), df[f"{tf}_cb_high"].to_numpy(float)) for tf in TFS}
    print(f"\n=== {name}: bound geometry over all rows (ATR1 = 1_atr_14_ma_5) ===")
    for tf in TFS:
        lo, hi = B[tf]; span = hi - lo; ok = np.isfinite(span) & (span > 0)
        pos = (close - lo) / np.where(ok, span, np.nan)
        print(f"tf {tf:3d}: bounds present {ok.mean():.3f}; span/ATR1 q05/25/50/75/95 {q(span / satr)}; "
              f"close pos in range q {q(pos)}; share close below low {np.nanmean(pos < 0):.3f} above high {np.nanmean(pos > 1):.3f}")
    for T, Hh in ((15, 60), (15, 240), (60, 240)):
        tl, th = B[T]; hl, hh = B[Hh]
        ok = np.isfinite(tl) & np.isfinite(th) & np.isfinite(hl) & np.isfinite(hh) & (th > tl) & (hh > hl) & ok_atr
        ratio = (hh - hl)[ok] / (th - tl)[ok]
        nested = ((tl >= hl) & (th <= hh))[ok]
        above = (th > hh)[ok]; below = (tl < hl)[ok]
        dlo = np.abs(tl - hl)[ok] / atr[ok]; dhi = np.abs(th - hh)[ok] / atr[ok]
        hspan = (hh - hl)[ok]
        posl = (tl - hl)[ok] / hspan; posh = (th - hl)[ok] / hspan
        print(f"pair {T}<{Hh}: rows {ok.sum()}; span ratio H/T q {q(ratio)}; T nested in H {nested.mean():.3f}; T high above H high {above.mean():.3f}; "
              f"T low below H low {below.mean():.3f}; both outside {(above & below).mean():.3f}")
        print(f"   |T_low - H_low|/ATR1 q {q(dlo)}: <=0.5 {np.mean(dlo <= 0.5):.3f} <=1 {np.mean(dlo <= 1):.3f} <=2 {np.mean(dlo <= 2):.3f} | "
              f"|T_high - H_high|/ATR1 q {q(dhi)}: <=0.5 {np.mean(dhi <= 0.5):.3f} <=1 {np.mean(dhi <= 1):.3f} <=2 {np.mean(dhi <= 2):.3f}")
        print(f"   T low's position in H range q {q(posl)}; T high's position q {q(posh)}; "
              f"T range in lower half of H (T high < H mid) {np.mean(posh < 0.5):.3f}, in upper half (T low > H mid) {np.mean(posl > 0.5):.3f}")


def run(name, frozen=None):
    df = load(name)
    n = len(df)
    close = df["1_close"].to_numpy(float); atr = df["1_atr_14_ma_5"].to_numpy(float)
    ok_atr = np.isfinite(atr) & (atr > 0); satr = np.where(ok_atr, atr, np.nan)
    geometry(df, name)
    CLS = {}; CID = {}; OVA = {}; POS = {}; ROOM = {}; EXZ = {}; ZL = {}
    for tf in TFS:
        CLS[tf], CID[tf] = classes(df, tf)
        lo = df[f"{tf}_cb_low"].to_numpy(float); hi = df[f"{tf}_cb_high"].to_numpy(float); span = hi - lo
        ok = np.isfinite(span) & (span > 0)
        POS[tf] = (close - lo) / np.where(ok, span, np.nan)
        ROOM[tf] = {"short": (close - lo) / satr, "long": (hi - close) / satr}
        for side in SIDES:
            b = lo if side == "long" else hi
            w = df[f"{tf}_cb_low_std" if side == "long" else f"{tf}_cb_high_std"].to_numpy(float)
            x = df["1_low" if side == "long" else "1_high"].to_numpy(float)
            over = (b - x) / w if side == "long" else (x - b) / w
            OVA[(tf, side)] = over > THR[tf][side]
        inzl = df[f"{tf}_cb_inzone_long"].fillna(False).to_numpy(bool); inzs = df[f"{tf}_cb_inzone_short"].fillna(False).to_numpy(bool)
        zl = df[f"{tf}_cb_zone_long"].to_numpy(float); zs = df[f"{tf}_cb_zone_short"].to_numpy(float)
        # exz for a SHORT entry: H's long zone touched earlier in this H candle, not now, close >= EXZ_ATR above the long zone line
        EXZ[(tf, "short")] = seg_cummax(inzl, CID[tf]) & ~inzl & ((close - zl) / satr >= EXZ_ATR)
        EXZ[(tf, "long")] = seg_cummax(inzs, CID[tf]) & ~inzs & ((zs - close) / satr >= EXZ_ATR)
        print(f"[{name}] tf {tf:3d}: pos finite {np.isfinite(POS[tf]).mean():.3f}; exz short {EXZ[(tf, 'short')].mean():.3f} long {EXZ[(tf, 'long')].mean():.3f}; "
              f"e25 +1 {np.mean(CLS[tf] == 1):.3f} -1 {np.mean(CLS[tf] == -1):.3f}", flush=True)
    POS_SH = {tf: np.r_[np.full(SHIFT, np.nan), POS[tf][:-SHIFT]] for tf in TFS}
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
            # geometry at the candidate minutes, per higher tf
            G = {}
            own_opp = df[f"{tf}_cb_low" if side == "short" else f"{tf}_cb_high"].to_numpy(float)[idx]
            for Hh in TFS:
                p = POS[Hh][idx]; f = p if side == "short" else 1.0 - p
                psh = POS_SH[Hh][idx]; fsh = psh if side == "short" else 1.0 - psh
                h_same = df[f"{Hh}_cb_low" if side == "short" else f"{Hh}_cb_high"].to_numpy(float)[idx]
                G[Hh] = dict(f=f, fsh=fsh, room=ROOM[Hh][side][idx], nest=np.abs(own_opp - h_same) / satr[idx], exz=EXZ[(Hh, side)][idx])
            # veto arrays per (fam, Hh): True = veto
            VETO = {}
            for Hh in TFS:
                g = G[Hh]
                with np.errstate(invalid="ignore"):
                    for qq in QS:
                        VETO[(f"pos{qq}", Hh)] = g["f"] < qq
                        VETO[(f"mirpos{qq}", Hh)] = g["f"] > 1 - qq
                        VETO[(f"sh{qq}", Hh)] = g["fsh"] < qq
                        VETO[(f"exzpos{qq}", Hh)] = g["exz"] & (g["f"] < qq)
                    for kk in KS:
                        VETO[(f"room{kk}", Hh)] = g["room"] < kk
                    for dd in DS:
                        VETO[(f"nest{dd}", Hh)] = g["nest"] <= dd
                    VETO[("exz", Hh)] = g["exz"]
            fams = sorted({k[0] for k in VETO})
            one = np.ones(len(idx), dtype=bool)
            flags = {"none": one, "e25": e25}
            for fam in fams:
                for pk, rule in PAIRS.items():
                    fl = e25.copy()
                    for Hh in rule.get(tf, ()):
                        fl &= ~VETO[(fam, Hh)]
                    flags[f"{fam}|{pk}"] = fl
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
            out[(tf, side)] = dict(res=res, idx=idx, pnl=pnl, reason=reason, cid=cid_e, flags=flags, G=G, VETO=VETO, month=month[idx], e25=e25)
            r = res["e25"]
            print(f"[{name}] tf {tf:3d} {side:5s}: candidates {len(idx)} in {len(np.unique(cid_e))} candles; e25 entries {r['n']} net {r['net']:+.0f} "
                  f"PF {r['pf']:.2f} wr {r['wr']:.2f} stop/tgt/hold {r['stop']}/{r['tgt']}/{r['hold']} | placeholder stops {kind.mean():.1%} RSS {rss():.0f} MB", flush=True)
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
    print(f"{'variant':>16s} | " + " | ".join(f"{'tf' + str(tf) + ' ' + side:>26s}" for tf in TFS for side in SIDES) + f" | {'ALL n':>6s} {'net':>8s} {'PF':>5s} | {'Δ':>8s} {'CI90':>18s} {'P':>4s} {'m+':>5s}")
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
        print(f"{v:>16s} | " + " | ".join(f"{c:>26s}" for c in cells) + f" | {tot_n:6d} {tot:+8.0f} {w / l if l else float('inf'):5.2f} | {pd_}")


def splits(out, name):
    print(f"\n=== {name}: e25 entries (hold {H}) split by the higher tf's geometry at the entry minute ===")
    for tf in (15, 60):
        for side in SIDES:
            o = out[(tf, side)]; r = o["res"]["e25"]; fi = r["first_idx"]; p = r["pnl"]; rs = o["reason"][fi]
            for Hh in HIGHER[tf]:
                g = o["G"][Hh]; f = g["f"][fi]
                print(f"-- tf {tf} {side} by H {Hh}: favourable room share f (0 = entry at the wrong end of H's range) — all {cell(p, rs)}; f finite {np.isfinite(f).mean():.3f}; f q {q(f)}")
                for a, b in zip(FBINS[:-1], FBINS[1:]):
                    m = (f >= a) & (f < b) if b < 1 else (f >= a) & (f <= b)
                    print(f"   f [{a:.1f},{b:.1f}{')' if b < 1 else ']'}: {cell(p[m], rs[m])}")
                m = f < 0; print(f"   f < 0 (beyond H's bound against the trade): {cell(p[m], rs[m])}")
                m = f > 1; print(f"   f > 1 (beyond H's bound in the trade's favour): {cell(p[m], rs[m])}")
                room = g["room"][fi]
                for a, b in ((-99, 0), (0, 1), (1, 2), (2, 3), (3, 5), (5, 10), (10, 999)):
                    m = (room >= a) & (room < b); print(f"   room [{a},{b}) ATR1: {cell(p[m], rs[m])}")
                nest = g["nest"][fi]
                for dd in DS:
                    m = nest <= dd; print(f"   nest <= {dd} ATR1 (own opposite bound on H's same-side bound): {cell(p[m], rs[m])} | else {cell(p[~m], rs[~m])}")
                ex = g["exz"][fi]
                print(f"   exz (H opposite zone executed this H candle, price moved >= {EXZ_ATR} ATR1 away): {cell(p[ex], rs[ex])} | else {cell(p[~ex], rs[~ex])}")
                m = ex & (nest <= 1.0); print(f"   USER CASE exz & nest<=1: {cell(p[m], rs[m])} | else {cell(p[~m], rs[~m])}")
                m = ex & (f < 0.35); print(f"   exz & f<0.35: {cell(p[m], rs[m])} | else {cell(p[~m], rs[~m])}")


def select(out):
    """freeze one parameter per family on 2y: best paired Δ on the 15<60 pair with entry retention >= RETAIN."""
    base = sum(out[(15, s)]["res"]["e25"]["n"] for s in SIDES)
    frozen = {}
    print(f"\n=== 2y selection (pair 15<60, cells tf 15 long+short, retention >= {RETAIN:.0%}) ===")
    for fam, grid in (("pos", QS), ("room", KS), ("nest", DS)):
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
    frozen["exz"] = None
    return frozen


def frozen_variants(frozen):
    vs = ["none", "e25"]
    for pk in PAIRS:
        vs += [f"pos{frozen['pos']}|{pk}", f"room{frozen['room']}|{pk}", f"nest{frozen['nest']}|{pk}", f"exz|{pk}",
               f"exzpos{frozen['pos']}|{pk}", f"mirpos{frozen['pos']}|{pk}", f"sh{frozen['pos']}|{pk}"]
    return vs


def grid_variants():
    vs = ["none", "e25"]
    for pk in ("15<60", "ladder"):
        vs += [f"pos{qq}|{pk}" for qq in QS] + [f"room{kk}|{pk}" for kk in KS] + [f"nest{dd}|{pk}" for dd in DS] + [f"exz|{pk}"]
        vs += [f"exzpos{qq}|{pk}" for qq in QS] + [f"mirpos{qq}|{pk}" for qq in QS] + [f"sh{qq}|{pk}" for qq in QS]
    for pk in ("15<240", "60<240"):
        vs += [f"pos{qq}|{pk}" for qq in QS] + [f"room{kk}|{pk}" for kk in KS] + [f"exz|{pk}"]
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
            frozen = {"pos": float(next((a.split("=")[1] for a in sys.argv if a.startswith("--pos=")), QS[1])),
                      "room": float(next((a.split("=")[1] for a in sys.argv if a.startswith("--room=")), KS[1])),
                      "nest": float(next((a.split("=")[1] for a in sys.argv if a.startswith("--nest=")), DS[1])), "exz": None}
            print(f"frozen values passed on the command line: {frozen}")
        out = run("oos2m")
        splits(out, "oos2m")
        table(out, "oos2m", frozen_variants(frozen), f"FROZEN ON 2y {frozen} — the score")
        table(out, "oos2m", grid_variants(), "FULL GRID (post hoc, NOT for selection)")
    print(f"\ndone in {time.time() - t0:.0f}s, RSS {rss():.0f} MB")
