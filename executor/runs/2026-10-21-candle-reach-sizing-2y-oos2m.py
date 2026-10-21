#!/usr/bin/env python3
"""Tier B stand-in for the volatility index as a STOP-OFFSET and POSITION-SIZE rule (spec
docs/superpowers/experiment/candle_reach_sizing_stop.md). Entry set = the candle_reach_gate stand-in's e25 entries (set-C
candidate minutes, first passing minute per tf candle, forming EMA-25 flag), unchanged by every variant; the live stop =
forming 15-min extreme -/+ trailing-60 mean 1-min range (off); live size = min(100 / stop distance, 50000 / entry); cbnc target;
hold H; no fees. Features at the entry row from the gate stand-in (imported): atr1_rel, atr1_pct, rel_15 (= fc8c_15 / sqrt 15),
fc8c_15, progress, D (target distance / ATR1), ratio = fc8c_tf (1 - p)^0.5 / D, and their 1440-row-shifted placebos.
Stop variants (offset multiplier m on off, anchor unchanged): st_rel_b{B} m = rel_15^B; st_arel_b{B} m = atr1_rel^B; st_fc_g{g}
offset = g * fc8c_15 * ATR1; st_reg_{hi}_{lo} m = hi above atr1_rel 1.3, lo below 0.8, else 1; controls st_sh_* (shifted
features), st_rand_* (the frozen rule's multipliers shuffled, 3 seeds).
Size variants (multiplier s on the live size, normalised to mean 1 over the 2y entries, constant frozen): sz_arel_g{G}
s ~ atr1_rel^G; sz_apct_g{G} ~ atr1_pct^G; sz_rel_g{G} ~ rel_15^G; sz_ratio_g{G} ~ ratio^G; sz_reg_{lo}_{hi}; controls sz_sh_*,
sz_rand_* (shuffled). Selection on 2y = best paired delta vs live over all cells, one per family; oos2m scored once.
usage: python3 2026-10-21-candle-reach-sizing-2y-oos2m.py [--hold=60] [--only=2y|oos2m] [--frozen=st:NAME,sz:NAME] [--norm=NAME:value,...]
"""
import sys, time, importlib.util
import numpy as np, pandas as pd
from collections import defaultdict

_spec = importlib.util.spec_from_file_location("gate", "2026-10-21-candle-reach-2y-oos2m.py")
gate = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(gate)
load, reach_features, classes, candle_id, pf_of, q, rss, spearman = (gate.load, gate.reach_features, gate.classes, gate.candle_id,
                                                                      gate.pf_of, gate.q, gate.rss, gate.spearman)
TFS, SIDES, THR, RISK, CAP, PLACEHOLDER, RANGE_N, SHIFT = gate.TFS, gate.SIDES, gate.THR, gate.RISK, gate.CAP, gate.PLACEHOLDER, gate.RANGE_N, gate.SHIFT
H = gate.H; ONLY = gate.ONLY
ST_REL_B = (0.5, 1.0, 2.0); ST_AREL_B = (-1.0, -0.5, 0.5, 1.0); ST_FC_G = (0.15, 0.25, 0.4); ST_REG = ((1.5, 0.75), (0.75, 1.5), (2.0, 1.0), (1.0, 2.0))
SZ_G = (-1.0, -0.5, 0.5, 1.0); SZ_REL_G = (-1.0, 1.0); SZ_RATIO_G = (-0.5, 0.5); SZ_REG = ((1.5, 0.5), (0.5, 1.5))
A_HI, A_LO = 1.3, 0.8; SEEDS = (0, 1, 2)


def simulate_entries(df, tf, side, idx, off):
    """one trade per entry row in idx with the absolute stop offset off[k] (nan / non-adverse -> placeholder)."""
    hi, lo, cl = (df[c].to_numpy(float) for c in ("1_high", "1_low", "1_close"))
    n = len(cl)
    cid15 = candle_id((df["15_is_closed"] == True).to_numpy())  # noqa: E712
    s = pd.Series(lo if side == "long" else hi)
    ext15 = (s.groupby(cid15).cummin() if side == "long" else s.groupby(cid15).cummax()).to_numpy()
    tgt = df[f"{tf}_cbnc_high" if side == "long" else f"{tf}_cbnc_low"].to_numpy(float)
    pnl = np.zeros(len(idx)); reason = np.zeros(len(idx), dtype=np.int8)
    size_arr = np.zeros(len(idx)); dist_arr = np.zeros(len(idx)); kind = np.zeros(len(idx), dtype=np.int8)
    sgn = 1.0 if side == "long" else -1.0
    for k, i0 in enumerate(idx):
        e = cl[i0]; o = off[k]
        stop = (ext15[i0] - o if side == "long" else ext15[i0] + o) if (o == o and o > 0) else np.nan
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
    return pnl, reason, size_arr, dist_arr, kind


def stop_variants():
    v = {}
    for b in ST_REL_B: v[f"st_rel_b{b}"] = ("rel", b)
    for b in ST_AREL_B: v[f"st_arel_b{b}"] = ("arel", b)
    for g in ST_FC_G: v[f"st_fc_g{g}"] = ("fc", g)
    for hi_, lo_ in ST_REG: v[f"st_reg_{hi_}_{lo_}"] = ("reg", (hi_, lo_))
    return v


def size_variants():
    v = {}
    for g in SZ_G: v[f"sz_arel_g{g}"] = ("arel", g); v[f"sz_apct_g{g}"] = ("apct", g)
    for g in SZ_REL_G: v[f"sz_rel_g{g}"] = ("rel", g)
    for g in SZ_RATIO_G: v[f"sz_ratio_g{g}"] = ("ratio", g)
    for lo_, hi_ in SZ_REG: v[f"sz_reg_{lo_}_{hi_}"] = ("reg", (lo_, hi_))
    return v


def stop_mult(kind, prm, G, sh=False):
    s = "_sh" if sh else ""
    with np.errstate(invalid="ignore", divide="ignore"):
        if kind == "rel": return np.power(G["rel15" + s], prm)
        if kind == "arel": return np.power(G["atr1_rel" + s], prm)
        if kind == "fc": return prm * G["fc8c_15" + s] * G["atr1"] / G["off"]       # offset = g fc ATR1  ->  multiplier on off
        if kind == "reg":
            hi_, lo_ = prm; a = G["atr1_rel" + s]
            return np.where(a > A_HI, hi_, np.where(a < A_LO, lo_, 1.0))
    raise ValueError(kind)


def size_raw(kind, prm, G, sh=False):
    s = "_sh" if sh else ""
    with np.errstate(invalid="ignore", divide="ignore"):
        if kind == "arel": return np.power(G["atr1_rel" + s], prm)
        if kind == "apct": return np.power(G["atr1_pct" + s], prm)
        if kind == "rel": return np.power(G["rel15" + s], prm)
        if kind == "ratio": return np.power(G["ratio" + s], prm)
        if kind == "reg":
            lo_, hi_ = prm; a = G["atr1_rel" + s]
            return np.where(a > A_HI, hi_, np.where(a < A_LO, lo_, 1.0))
    raise ValueError(kind)


def resize(pnl0, size0, dist0, entry, s):
    s = np.where(np.isfinite(s) & (s > 0), s, 1.0)
    size1 = np.minimum(s * RISK / dist0, CAP / entry)
    return pnl0 * size1 / size0, size1


def entries_and_features(df, name):
    F = reach_features(df, name)
    CLS = {}; CID = {}
    for tf in TFS:
        CLS[tf], CID[tf] = classes(df, tf)
    atr = df["1_atr_14_ma_5"].to_numpy(float); c1 = df["1_close"].to_numpy(float)
    hi1 = df["1_high"].to_numpy(float); lo1 = df["1_low"].to_numpy(float)
    off_all = pd.Series(hi1 - lo1).shift(1).rolling(RANGE_N, min_periods=1).mean().to_numpy()
    month = pd.DatetimeIndex(df.index).to_period("M").astype(str).to_numpy()
    cells = {}
    for tf in TFS:
        for side in SIDES:
            b = df[f"{tf}_cb_low" if side == "long" else f"{tf}_cb_high"].to_numpy(float)
            w = df[f"{tf}_cb_low_std" if side == "long" else f"{tf}_cb_high_std"].to_numpy(float)
            x = df["1_low" if side == "long" else "1_high"].to_numpy(float)
            over = (b - x) / w if side == "long" else (x - b) / w
            inz = df[f"{tf}_cb_inzone_{side}"].fillna(False).to_numpy(bool)
            cand = inz & ~(over > THR[tf][side])
            idx = np.flatnonzero(cand)
            bad = -1 if side == "long" else 1
            e25 = CLS[tf][idx] != bad
            cid_e = CID[tf][idx]
            first = np.zeros(len(idx), dtype=bool); seen = set()
            for k in np.flatnonzero(e25):
                c = cid_e[k]
                if c not in seen:
                    seen.add(c); first[k] = True
            E = idx[first]
            tgt = df[f"{tf}_cbnc_high" if side == "long" else f"{tf}_cbnc_low"].to_numpy(float)
            dtgt = np.abs(tgt[E] - c1[E]) / np.where(atr[E] > 0, atr[E], np.nan)
            prog = F[(tf, "prog")][E]
            G = dict(atr1=atr[E], off=off_all[E], entry=c1[E], dtgt=dtgt, prog=prog,
                     atr1_rel=F["atr1_rel"][E], atr1_pct=F["atr1_pct"][E], atr1_rel_sh=F["atr1_rel_sh"][E], atr1_pct_sh=F["atr1_pct_sh"][E],
                     rel15=F[(15, "rel")][E], rel15_sh=F[(15, "rel_sh")][E], fc8c_15=F[(15, "fc8c")][E], fc8c_15_sh=F[(15, "fc8c_sh")][E])
            with np.errstate(invalid="ignore", divide="ignore"):
                G["ratio"] = F[(tf, "fc8c")][E] * np.sqrt(np.clip(1 - prog, 0, 1)) / dtgt
                G["ratio_sh"] = F[(tf, "fc8c_sh")][E] * np.sqrt(np.clip(1 - prog, 0, 1)) / dtgt
            cells[(tf, side)] = dict(E=E, cid=cid_e[first], month=month[E], G=G)
            print(f"[{name}] tf {tf:3d} {side:5s}: e25 entries {len(E)}; off/ATR1 q {q(G['off'] / G['atr1'])}; atr1_rel q {q(G['atr1_rel'])}; rel15 q {q(G['rel15'])}", flush=True)
    return cells


def run(name, frozen=None, norms=None):
    df = load(name)
    cells = entries_and_features(df, name)
    SV = stop_variants(); ZV = size_variants()
    # ---- live + stop variants (re-simulated)
    t0 = time.time()
    for key, c in cells.items():
        tf, side = key; G = c["G"]
        pnl0, r0, sz0, d0, k0 = simulate_entries(df, tf, side, c["E"], G["off"])
        c["res"] = {"e25": dict(pnl=pnl0, reason=r0, size=sz0, dist=d0, kind=k0, first_idx=np.arange(len(pnl0)))}
        c["live"] = (pnl0, r0, sz0, d0)
    print(f"[{name}] live simulated {time.time() - t0:.0f}s RSS {rss():.0f} MB", flush=True)
    todo = dict(SV)
    norms = dict(norms or {})
    if frozen:   # controls of the frozen stop: shifted features, shuffled multipliers, constant = the frozen mean multiplier
        kind, prm = SV[frozen["st"]]
        todo[f"st_sh_{frozen['st']}"] = ("sh", (kind, prm))
        for sd in SEEDS: todo[f"st_rand{sd}_{frozen['st']}"] = ("rand", (kind, prm, sd))
        ck = f"stc_{frozen['st']}"
        if ck not in norms:
            allm = np.concatenate([stop_mult(kind, prm, c["G"]) for c in cells.values()])
            norms[ck] = float(np.mean(allm[np.isfinite(allm) & (allm > 0)]))
        todo[f"st_const_{frozen['st']}"] = ("const", norms[ck])
    for v, (kind, prm) in todo.items():
        t0 = time.time()
        for key, c in cells.items():
            tf, side = key; G = c["G"]
            if kind == "sh": m = stop_mult(prm[0], prm[1], G, sh=True)
            elif kind == "const": m = np.full(len(c["E"]), prm)
            elif kind == "rand":
                m = stop_mult(prm[0], prm[1], G); m = np.random.default_rng(prm[2]).permutation(m)
            else: m = stop_mult(kind, prm, G)
            pnl, r, sz, d, kd = simulate_entries(df, tf, side, c["E"], G["off"] * m)
            c["res"][v] = dict(pnl=pnl, reason=r, size=sz, dist=d, kind=kd, first_idx=np.arange(len(pnl)), mult=m)
        print(f"[{name}] {v:>24s} simulated {time.time() - t0:.0f}s", flush=True)
    # ---- size variants (re-weighted live run); normalisation = mean raw multiplier over all 2y entries (frozen)
    ztodo = dict(ZV)
    if frozen:
        kind, prm = ZV[frozen["sz"]]
        ztodo[f"sz_sh_{frozen['sz']}"] = ("sh", (kind, prm))
        for sd in SEEDS: ztodo[f"sz_rand{sd}_{frozen['sz']}"] = ("rand", (kind, prm, sd))
    for v, (kind, prm) in ztodo.items():
        raws = {}
        for key, c in cells.items():
            G = c["G"]
            if kind == "sh": s = size_raw(prm[0], prm[1], G, sh=True)
            elif kind == "rand": s = size_raw(prm[0], prm[1], G)
            else: s = size_raw(kind, prm, G)
            raws[key] = s
        base_v = v if not v.startswith(("sz_sh_", "sz_rand")) else v.split("_", 2)[2]
        if base_v not in norms:
            allr = np.concatenate([r_[np.isfinite(r_) & (r_ > 0)] for r_ in raws.values()])
            norms[base_v] = float(np.mean(allr)) if len(allr) else 1.0
        for key, c in cells.items():
            s = raws[key] / norms[base_v]
            if kind == "rand": s = np.random.default_rng(prm[2]).permutation(s)
            pnl0, r0, sz0, d0 = c["live"]
            pnl, sz = resize(pnl0, sz0, d0, c["G"]["entry"], s)
            c["res"][v] = dict(pnl=pnl, reason=r0, size=sz, dist=d0, kind=np.zeros(len(pnl), dtype=np.int8), first_idx=np.arange(len(pnl)), mult=s)
    out = {key: dict(res=c["res"], cid=c["cid"], month=c["month"], G=c["G"]) for key, c in cells.items()}
    del df
    return out, norms


def table(out, name, variants, title):
    print(f"\n=== {name}, {title}: hold {H} min: per cell n, net, PF, stop share | ALL n, net, PF, net per $ risked (x100), placeholder stops | paired Δ vs live by candle (CI90, P(Δ<0)) months+/months ===")
    print(f"{'variant':>26s} | " + " | ".join(f"{'tf' + str(tf) + ' ' + side:>20s}" for tf in TFS for side in SIDES) + f" | {'n':>6s} {'net':>8s} {'PF':>5s} {'R%':>6s} {'ph':>5s} | {'Δ':>8s} {'CI90':>18s} {'P':>4s} {'m+':>5s}")
    for v in variants:
        cellsf = []; tot_n = 0; tot = 0.0; w = 0.0; l = 0.0; risk = 0.0; ph = 0
        for tf in TFS:
            for side in SIDES:
                r = out[(tf, side)]["res"][v]; p = r["pnl"]
                cellsf.append(f"{len(p):5d} {p.sum():+7.0f} {pf_of(p):4.2f} {np.mean(r['reason'] == 1):.2f}")
                tot_n += len(p); tot += p.sum(); w += p[p > 0].sum(); l += abs(p[p < 0].sum()); risk += float((r["size"] * r["dist"]).sum()); ph += int(r["kind"].sum())
        if v == "e25":
            pd_ = ""
        else:
            s, a, b, pneg, mp, mn = gate.paired(out, v)
            pd_ = f"{s:+8.0f} [{a:+7.0f},{b:+7.0f}] {pneg:.2f} {mp:2d}/{mn:2d}"
        print(f"{v:>26s} | " + " | ".join(f"{c:>20s}" for c in cellsf) + f" | {tot_n:6d} {tot:+8.0f} {w / l if l else float('inf'):5.2f} {100 * tot / risk if risk else 0:+6.2f} {ph:5d} | {pd_}")


def select(out):
    frozen = {}
    for fam, vs in (("st", list(stop_variants())), ("sz", list(size_variants()))):
        best = None
        print(f"\n=== 2y selection ({fam}): paired Δ vs live over all cells ===")
        for v in vs:
            s, a, b, pneg, mp, mn = gate.paired(out, v)
            print(f"   {v:>20s}: Δ {s:+8.0f} [{a:+7.0f},{b:+7.0f}] P {pneg:.2f} months+ {mp}/{mn}")
            if best is None or s > best[1]: best = (v, s)
        frozen[fam] = best[0]
        print(f"   -> frozen {fam} = {frozen[fam]}")
    return frozen


def frozen_list(frozen):
    vs = ["e25", frozen["st"], f"st_sh_{frozen['st']}", f"st_const_{frozen['st']}"] + [f"st_rand{sd}_{frozen['st']}" for sd in SEEDS]
    vs += [frozen["sz"], f"sz_sh_{frozen['sz']}"] + [f"sz_rand{sd}_{frozen['sz']}" for sd in SEEDS]
    return vs


def correlations(out, name):
    print(f"\n=== {name}: live entries — Spearman(feature, pnl) / (feature, R = pnl / risk) per cell ===")
    for key, o in out.items():
        r = o["res"]["e25"]; p = r["pnl"]; R = p / (r["size"] * r["dist"]); G = o["G"]
        parts = []
        for f in ("atr1_rel", "atr1_pct", "rel15", "ratio"):
            parts.append(f"{f} {spearman(G[f], p)[0]:+.3f}/{spearman(G[f], R)[0]:+.3f}")
        print(f"   tf {key[0]:3d} {key[1]:5s} n {len(p):6d}: " + "; ".join(parts))


if __name__ == "__main__":
    t0 = time.time()
    frozen = None; norms = None
    fz = next((a.split("=")[1] for a in sys.argv if a.startswith("--frozen=")), "")
    if fz: frozen = dict(kv.split(":") for kv in fz.split(","))
    nm = next((a.split("=")[1] for a in sys.argv if a.startswith("--norm=")), "")
    if nm: norms = {k: float(v) for k, v in (kv.split(":") for kv in nm.split(","))}
    if ONLY in ("", "2y"):
        out, norms = run("2y")
        correlations(out, "2y")
        table(out, "2y", ["e25"] + list(stop_variants()) + list(size_variants()), "FULL GRID (selection tier)")
        frozen = select(out)
        out, norms = run("2y", frozen, norms)      # re-run with the controls of the frozen pair
        print(f"\nnormalisation constants (size: mean raw multiplier over the 2y entries; stc_: the frozen stop rule's mean multiplier): --norm=" + ",".join(f"{k}:{v:.6f}" for k, v in norms.items()))
        table(out, "2y", frozen_list(frozen), f"FROZEN {frozen} + controls")
        del out
    if ONLY in ("", "oos2m"):
        assert frozen and norms, "pass --frozen=st:NAME,sz:NAME and --norm=NAME:value,..."
        out, _ = run("oos2m", frozen, norms)
        correlations(out, "oos2m")
        table(out, "oos2m", frozen_list(frozen), f"FROZEN ON 2y {frozen} — the score")
        table(out, "oos2m", ["e25"] + list(stop_variants()) + list(size_variants()), "FULL GRID (post hoc, NOT for selection)")
    print(f"\ndone in {time.time() - t0:.0f}s, RSS {rss():.0f} MB")
