#!/usr/bin/env python3
"""Tier B stand-in for the candle-reach entry gate (spec: docs/superpowers/experiment/candle_reach_gate.md): the per-tf
"reach" of the candle (tf range in 1-min ATRs) forecast from the last N closed candles, as a veto on the own CB zone entry,
over 2y (2023-01 -> 2024-12) and oos2m (2025-01 -> 2025-03) from the stored 1-min frames. The entry / stop / target /
sizing / hold machinery is the volume-flow stand-in unchanged (set-C candidate minutes = inzone and overshoot pass; first
passing minute per tf candle; entry = 1_close; candle stop; cbnc target; max hold H; size min(100/dist, 50000/entry); no
fees); the veto per (tf, side) is ANDed into the own forming EMA-25 flag (e25).

Reach quantities (closed information only; ATR1 = 1_atr_14_ma_5 of the row):
  reach_c  = (high_c - low_c) / ATR1 at the close of closed tf candle c;  body_c = |close_c - open_c| / ATR1;  eff_c = body/reach
  reach_fc{N}{norm}[t] = median of the last N closed candles' reach (norm c: each candle's range over the ATR1 at its close;
             norm t: median range of the N candles over the ATR1 at row t)
  p[t]     = wall-clock progress of the forming tf candle ((minutes since open + 1) / tf, production form)
  rem      = reach_fc * (1 - p)^alpha;   D_tgt = |cbnc far-bound target - 1_close| / ATR1
  atr1_rel = ATR1 / rolling median(ATR1, 1440 rows);  atr1_pct = ATR1 / close * 100;  rel_tf = reach_fc / sqrt(tf)
Variants (veto when): rem{N}{norm}_a{alpha}_k{k} rem < k*D_tgt (primary, target reachability); thr{N}{norm}_q{q}
reach_fc < q*sqrt(tf); chop_a{a}_b{b} atr1_rel > a and rel_tf < b; dead_m{m} atr1_pct < m*0.042; eff_e{e} eff_fc < e;
lad{H}_r{r} (tf-15 fires only) rel_H > r*rel_15; mir_* the opposite inequality of the frozen primary; sh_* the frozen
variant's features read 1440 rows earlier (placebo). Secondary families use N = 8, norm c. Thresholds FROZEN on 2y (best
paired delta vs e25 on the tf-15 cells, entry retention >= 60 %), oos2m scored with them; full grids printed on both tiers
for transparency only.
rw_a{alpha}_k{k}: the primary with the reach forecast replaced by sqrt(tf) (random-walk reach) = a progress x target-distance gate
without any reach information (the decisive ablation: if rw == rem the reach index carries nothing).
usage: python3 2026-10-21-candle-reach-2y-oos2m.py [--hold=60] [--only=2y|oos2m] [--frozen=reach:...,rw:...,thr:...,chop:...,dead:...,eff:...,lad:...]
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
NS = (4, 8, 16); NORMS = ("c", "t"); ALPHAS = (0.5, 1.0); KS = (0.5, 0.75, 1.0, 1.5); QS = (0.5, 0.75, 1.0)
CHOP_A = (1.3, 1.6); CHOP_B = (0.8, 1.0); DEAD_M = (1, 2, 3); EFF_E = (0.25, 0.35); LAD_R = (1.25, 1.5, 2.0)
FEE_RT = 0.042; RETAIN = 0.6; SEC_N = 8; SEC_NORM = "c"
RATIO_BINS = np.array([0.0, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 1e9]); REL_BINS = np.array([0.0, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 1e9])
AREL_BINS = np.array([0.0, 0.7, 0.85, 1.0, 1.3, 1.6, 2.0, 1e9])


def rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def candle_id(closed):
    return np.concatenate(([0], np.cumsum(closed)[:-1]))


BASE = ["1_open", "1_high", "1_low", "1_close"] + [f"{tf}_{c}" for tf in TFS for c in ("close", "is_closed")]
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


def shift(a):
    return np.r_[np.full(SHIFT, np.nan), a[:-SHIFT]]


def reach_features(df, name):
    """Per tf: closed-candle reach/body/eff (per candle), the row-level forecasts, progress, rel; plus the ATR1 axes."""
    atr = df["1_atr_14_ma_5"].to_numpy(float); c1 = df["1_close"].to_numpy(float)
    hi = df["1_high"].to_numpy(float); lo = df["1_low"].to_numpy(float); op = df["1_open"].to_numpy(float)
    n = len(atr)
    F = {}
    med = pd.Series(atr).rolling(SHIFT, min_periods=240).median().to_numpy()
    F["atr1_rel"] = atr / np.where(med > 0, med, np.nan)
    F["atr1_pct"] = atr / c1 * 100.0
    F["atr1_rel_sh"] = shift(F["atr1_rel"]); F["atr1_pct_sh"] = shift(F["atr1_pct"])
    print(f"[{name}] ATR1 pct q {q(F['atr1_pct'])} (fee round trip {FEE_RT:.3f} %: share below 1x/2x/3x "
          f"{np.nanmean(F['atr1_pct'] < FEE_RT):.3f}/{np.nanmean(F['atr1_pct'] < 2 * FEE_RT):.3f}/{np.nanmean(F['atr1_pct'] < 3 * FEE_RT):.3f}); atr1_rel q {q(F['atr1_rel'])}")
    idx = pd.DatetimeIndex(df.index)
    for tf in TFS:
        closed = (df[f"{tf}_is_closed"] == True).to_numpy()  # noqa: E712
        cid = candle_id(closed)
        g = pd.Series(np.arange(n)).groupby(cid)
        first = g.min().to_numpy(); last = g.max().to_numpy()
        ncand = len(first)
        c_hi = pd.Series(hi).groupby(cid).max().to_numpy(); c_lo = pd.Series(lo).groupby(cid).min().to_numpy()
        c_op = op[first]; c_cl = c1[last]; c_atr = atr[last]
        c_closed = closed[last]                      # the last candle may be forming (never closed) -> excluded
        rng_c = c_hi - c_lo
        reach_c = np.where(c_closed & (c_atr > 0), rng_c / c_atr, np.nan)
        body_c = np.where(c_closed & (c_atr > 0), np.abs(c_cl - c_op) / c_atr, np.nan)
        eff_c = np.where(reach_c > 0, body_c / reach_c, np.nan)
        rng_cc = np.where(c_closed, rng_c, np.nan)
        ok = np.isfinite(reach_c)
        r = reach_c[ok]
        ac1 = np.corrcoef(r[:-1], r[1:])[0, 1] if len(r) > 10 else np.nan
        lr = np.log(r[r > 0]); acl = np.corrcoef(lr[:-1], lr[1:])[0, 1] if len(lr) > 10 else np.nan
        # autocorrelation of the median-8 forecast vs the realized next candle (what the gate actually uses)
        s_r = pd.Series(reach_c)
        fc8 = s_r.rolling(8, min_periods=8).median().shift(1).to_numpy()
        m = np.isfinite(fc8) & np.isfinite(reach_c)
        rho_fc = np.corrcoef(fc8[m], reach_c[m])[0, 1] if m.sum() > 10 else np.nan
        sp_fc = spearman(fc8[m], reach_c[m])[0]
        print(f"[{name}] tf {tf:3d}: closed candles {int(ok.sum())}; reach q {q(reach_c)} (sqrt(tf) {np.sqrt(tf):.1f}; median/sqrt {np.nanmedian(reach_c) / np.sqrt(tf):.2f}); "
              f"eff q {q(eff_c)}; lag-1 autocorr reach {ac1:+.3f} (log {acl:+.3f}); corr(median-8 forecast, next reach) pearson {rho_fc:+.3f} spearman {sp_fc:+.3f}")
        # row-level forecasts: candles strictly before the forming one
        prog = ((np.asarray((idx - idx.floor(f"{tf}min")) / pd.Timedelta(minutes=1), dtype=float)) + 1.0) / tf
        F[(tf, "prog")] = prog
        for N in NS:
            fc_c = s_r.rolling(N, min_periods=N).median().shift(1).to_numpy()          # per candle, closed ones before c
            fc_t = pd.Series(rng_cc).rolling(N, min_periods=N).median().shift(1).to_numpy()
            F[(tf, f"fc{N}c")] = fc_c[cid]
            F[(tf, f"fc{N}t")] = fc_t[cid] / np.where(atr > 0, atr, np.nan)
            F[(tf, f"fc{N}c_sh")] = shift(F[(tf, f"fc{N}c")]); F[(tf, f"fc{N}t_sh")] = shift(F[(tf, f"fc{N}t")])
        eff_fc = pd.Series(eff_c).rolling(SEC_N, min_periods=SEC_N).median().shift(1).to_numpy()
        F[(tf, "eff")] = eff_fc[cid]; F[(tf, "eff_sh")] = shift(F[(tf, "eff")])
        F[(tf, "rel")] = F[(tf, f"fc{SEC_N}{SEC_NORM}")] / np.sqrt(tf); F[(tf, "rel_sh")] = shift(F[(tf, "rel")])
        print(f"      fc8c q {q(F[(tf, 'fc8c')])}; fc8t q {q(F[(tf, 'fc8t')])}; rel q {q(F[(tf, 'rel')])}; finite {np.isfinite(F[(tf, 'fc8c')]).mean():.3f}")
    return F


def rank(a):
    o = np.argsort(a, kind="stable"); r = np.empty(len(a)); r[o] = np.arange(len(a)); return r


def spearman(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 10: return float("nan"), int(m.sum())
    return float(np.corrcoef(rank(x[m]), rank(y[m]))[0, 1]), int(m.sum())


def auc(x, y):
    m = np.isfinite(x); x = x[m]; yb = y[m] > 0.5
    if yb.sum() == 0 or (~yb).sum() == 0: return float("nan")
    rk = rank(x); return float((rk[yb].sum() - yb.sum() * (yb.sum() - 1) / 2) / (yb.sum() * (~yb).sum()))


def variant_names():
    V_ = {"reach": [f"rem{N}{nm}_a{a}_k{k}" for N in NS for nm in NORMS for a in ALPHAS for k in KS],
          "thr": [f"thr{N}{nm}_q{qq}" for N in NS for nm in NORMS for qq in QS],
          "chop": [f"chop_a{a}_b{b}" for a in CHOP_A for b in CHOP_B],
          "dead": [f"dead_m{m}" for m in DEAD_M],
          "eff": [f"eff_e{e}" for e in EFF_E],
          "lad": [f"lad{hh}_r{r}" for hh in (60, 240) for r in LAD_R],
          "rw": [f"rw_a{a}_k{k}" for a in ALPHAS for k in KS]}
    return V_


def veto_of(v, G, tf, mirror=False, sh=False):
    """boolean veto array over the cell's candidates from variant name v (G = per-candidate feature dict)."""
    s = "_sh" if sh else ""
    with np.errstate(invalid="ignore"):
        if v.startswith("rem"):
            head, a, k = v.split("_"); N_nm = head[3:]; a = float(a[1:]); k = float(k[1:])
            rem = G[f"fc{N_nm}{s}"] * np.power(np.clip(1.0 - G["prog"], 0.0, 1.0), a)
            out = rem < k * G["dtgt"]
        elif v.startswith("thr"):
            head, qq = v.split("_"); N_nm = head[3:]; qq = float(qq[1:])
            out = G[f"fc{N_nm}{s}"] < qq * np.sqrt(tf)
        elif v.startswith("chop"):
            _, a, b = v.split("_"); a = float(a[1:]); b = float(b[1:])
            out = (G[f"atr1_rel{s}"] > a) & (G[f"rel{s}"] < b)
        elif v.startswith("dead"):
            m = float(v.split("_m")[1])
            out = G[f"atr1_pct{s}"] < m * FEE_RT
        elif v.startswith("eff"):
            e = float(v.split("_e")[1])
            out = G[f"eff{s}"] < e
        elif v.startswith("rw"):
            _, a, k = v.split("_"); a = float(a[1:]); k = float(k[1:])
            rem = np.sqrt(tf) * np.power(np.clip(1.0 - G["prog"], 0.0, 1.0), a)
            out = rem < k * G["dtgt"]
        elif v.startswith("lad"):
            head, r = v.split("_"); hh = int(head[3:]); r = float(r[1:])
            if tf != 15:
                return np.zeros(len(G["prog"]), dtype=bool)
            out = G[f"rel{hh}{s}"] > r * G[f"rel{s}"]
        else:
            raise ValueError(v)
    out = np.where(np.isfinite(out.astype(float)), out, False).astype(bool)
    return ~out & np.isfinite(G["dtgt"]) if mirror else out


def run(name):
    df = load(name)
    F = reach_features(df, name)
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
    atr = df["1_atr_14_ma_5"].to_numpy(float); c1 = df["1_close"].to_numpy(float)
    VN = variant_names()
    out = {}
    for tf in TFS:
        cid = CID[tf]
        for side in SIDES:
            inz = df[f"{tf}_cb_inzone_{side}"].fillna(False).to_numpy(bool)
            cand = inz & ~OVA[(tf, side)]
            idx, pnl, reason, size, dist, kind = simulate_all(df, tf, side, cand)
            bad = -1 if side == "long" else 1
            e25 = CLS[tf][idx] != bad
            tgt = df[f"{tf}_cbnc_high" if side == "long" else f"{tf}_cbnc_low"].to_numpy(float)
            G = {"prog": F[(tf, "prog")][idx], "dtgt": np.abs(tgt[idx] - c1[idx]) / np.where(atr[idx] > 0, atr[idx], np.nan),
                 "atr1_rel": F["atr1_rel"][idx], "atr1_pct": F["atr1_pct"][idx], "atr1_rel_sh": F["atr1_rel_sh"][idx], "atr1_pct_sh": F["atr1_pct_sh"][idx],
                 "eff": F[(tf, "eff")][idx], "eff_sh": F[(tf, "eff_sh")][idx], "rel": F[(tf, "rel")][idx], "rel_sh": F[(tf, "rel_sh")][idx]}
            for N in NS:
                for nm in NORMS:
                    G[f"fc{N}{nm}"] = F[(tf, f"fc{N}{nm}")][idx]; G[f"fc{N}{nm}_sh"] = F[(tf, f"fc{N}{nm}_sh")][idx]
            for hh in (60, 240):
                G[f"rel{hh}"] = F[(hh, "rel")][idx]; G[f"rel{hh}_sh"] = F[(hh, "rel_sh")][idx]
            one = np.ones(len(idx), dtype=bool)
            flags = {"none": one, "e25": e25}
            VETO = {}
            for fam, vs in VN.items():
                for v in vs:
                    VETO[v] = veto_of(v, G, tf)
                    VETO["sh_" + v] = veto_of(v, G, tf, sh=True)
                    VETO["mir_" + v] = veto_of(v, G, tf, mirror=True)
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


def splits(out, name):
    print(f"\n=== {name}: e25 entries (hold {H}) split by the reach features at the entry minute (n, net, PF, mean, stop share) ===")
    for tf in TFS:
        for side in SIDES:
            o = out[(tf, side)]; r = o["res"]["e25"]; fi = r["first_idx"]; p = r["pnl"]; rs = o["reason"][fi]
            G = o["G"]; st = (rs == 1).astype(float)
            print(f"-- tf {tf} {side}: all {cell(p, rs)}; D_tgt q {q(G['dtgt'][fi])}; prog q {q(G['prog'][fi])}")
            for N in NS:
                for nm in NORMS:
                    fc = G[f"fc{N}{nm}"][fi]
                    for a in ALPHAS:
                        rem = fc * np.power(np.clip(1 - G["prog"][fi], 0, 1), a); ratio = rem / G["dtgt"][fi]
                        rho, n_ = spearman(ratio, p)
                        print(f"   rem{N}{nm} a{a}: Spearman(rem/D, pnl) {rho:+.3f} AUC(rem/D->stop) {auc(ratio, st):.3f} n {n_}; ratio q {q(ratio)}")
                        if N == SEC_N and nm == SEC_NORM:
                            for lo_, hi_ in zip(RATIO_BINS[:-1], RATIO_BINS[1:]):
                                m = (ratio >= lo_) & (ratio < hi_)
                                if m.sum(): print(f"      rem/D [{lo_:g},{hi_:g}): {cell(p[m], rs[m])}")
            for a in ALPHAS:
                ratio = np.sqrt(tf) * np.power(np.clip(1 - G["prog"][fi], 0, 1), a) / G["dtgt"][fi]
                print(f"   rw a{a} (sqrt tf, no reach): Spearman(rw/D, pnl) {spearman(ratio, p)[0]:+.3f} AUC(rw/D->stop) {auc(ratio, st):.3f}; ratio q {q(ratio)}")
                if a == 0.5:
                    for lo_, hi_ in zip(RATIO_BINS[:-1], RATIO_BINS[1:]):
                        m = (ratio >= lo_) & (ratio < hi_)
                        if m.sum(): print(f"      rw/D [{lo_:g},{hi_:g}): {cell(p[m], rs[m])}")
            rel = G["rel"][fi]; ar = G["atr1_rel"][fi]; ef = G["eff"][fi]; ap = G["atr1_pct"][fi]
            print(f"   rel (fc8c/sqrt tf): Spearman {spearman(rel, p)[0]:+.3f} AUC->stop {auc(rel, st):.3f} | atr1_rel: {spearman(ar, p)[0]:+.3f} / {auc(ar, st):.3f} | "
                  f"eff: {spearman(ef, p)[0]:+.3f} / {auc(ef, st):.3f} | atr1_pct: {spearman(ap, p)[0]:+.3f} / {auc(ap, st):.3f}")
            for lo_, hi_ in zip(REL_BINS[:-1], REL_BINS[1:]):
                m = (rel >= lo_) & (rel < hi_)
                if m.sum(): print(f"      rel [{lo_:g},{hi_:g}): {cell(p[m], rs[m])}")
            for lo_, hi_ in zip(AREL_BINS[:-1], AREL_BINS[1:]):
                m = (ar >= lo_) & (ar < hi_)
                if m.sum(): print(f"      atr1_rel [{lo_:g},{hi_:g}): {cell(p[m], rs[m])}")
            for lo_, hi_ in zip(np.array([0, 0.03, 0.042, 0.06, 0.084, 0.126, 0.2, 1e9]), np.array([0.03, 0.042, 0.06, 0.084, 0.126, 0.2, 1e9, 1e10])):
                m = (ap >= lo_) & (ap < hi_)
                if m.sum(): print(f"      atr1_pct [{lo_:g},{hi_:g}): {cell(p[m], rs[m])}")


def select(out):
    base = sum(out[(15, s)]["res"]["e25"]["n"] for s in SIDES)
    frozen = {}
    print(f"\n=== 2y selection (cells tf 15 long+short, retention >= {RETAIN:.0%}): one variant per family ===")
    for fam, vs in variant_names().items():
        best = None
        for v in vs:
            n = sum(out[(15, s)]["res"][v]["n"] for s in SIDES)
            s, a, b, pneg, mp, mn = paired(out, v, tfs=(15,))
            keep = n / base
            print(f"   {v:>20s}: entries {n} ({keep:.2f} of e25) Δ {s:+8.0f} [{a:+7.0f},{b:+7.0f}] P {pneg:.2f} months+ {mp}/{mn}" + ("" if keep >= RETAIN else "  (below retention floor)"))
            if keep >= RETAIN and (best is None or s > best[1]):
                best = (v, s)
        frozen[fam] = best[0] if best else vs[0]
        print(f"   -> frozen {fam} = {frozen[fam]}")
    return frozen


def frozen_variants(frozen):
    vs = ["none", "e25"]
    for fam in ("reach", "rw", "thr", "chop", "dead", "eff", "lad"):
        vs.append(frozen[fam])
    vs += ["mir_" + frozen["reach"], "sh_" + frozen["reach"], "mir_" + frozen["rw"], "sh_" + frozen["thr"], "sh_" + frozen["chop"], "sh_" + frozen["lad"]]
    return vs


def grid_variants():
    vs = ["none", "e25"]
    for fam, fv in variant_names().items():
        vs += fv
        vs += ["sh_" + v for v in fv]
    vs += ["mir_" + v for v in variant_names()["reach"]] + ["mir_" + v for v in variant_names()["rw"]]
    return vs


if __name__ == "__main__":
    t0 = time.time()
    frozen = None
    fz = next((a.split("=")[1] for a in sys.argv if a.startswith("--frozen=")), "")
    if fz:
        frozen = dict(kv.split(":") for kv in fz.split(","))
        print(f"frozen values passed on the command line: {frozen}")
    if ONLY in ("", "2y"):
        out = run("2y")
        splits(out, "2y")
        table(out, "2y", grid_variants(), "FULL GRID (selection tier)")
        frozen = select(out)
        table(out, "2y", frozen_variants(frozen), f"FROZEN {frozen}")
        del out
    if ONLY in ("", "oos2m"):
        assert frozen, "pass --frozen=reach:rem8c_a0.5_k1.0,thr:...,chop:...,dead:...,eff:...,lad:..."
        out = run("oos2m")
        splits(out, "oos2m")
        table(out, "oos2m", frozen_variants(frozen), f"FROZEN ON 2y {frozen} — the score")
        table(out, "oos2m", grid_variants(), "FULL GRID (post hoc, NOT for selection)")
    print(f"\ndone in {time.time() - t0:.0f}s, RSS {rss():.0f} MB")
