#!/usr/bin/env python3
"""Replay: the HIGHER tf's range position / executed opposite bound as a veto on the lower tf's CB zone entry.

Question (user, 2026-10-21): how are the bounds of the tfs connected, and can the lower-tf entries that lose because
of the bigger tf's move be filtered by the higher tf's bounds? Example: the 15-min low zone executes, price runs to
the 15-min high bound and a short opens, but the 15-min low bound sits on the 60-min low bound and the 60-min candle
keeps rising, so the 15-min reversal fails.

Flow = 2026-10-21-higher-tf-trend-replay.py imported as a module (fires re-derived on every trade, 1-min class X 0.7,
candle stop, cbnc target + trend-flip exit, reversal, paper = no fees). A veto per (tf, side) is ANDed into the own
forming EMA-25 flag (e25). Per trade and higher tf H (stored {H}_cb_low / cb_high / cb_zone_* / cb_inzone_*, same
snapshot/expiry rule as the harness; short side shown, long mirrored):
  pos    (price - H_cb_low) / (H_cb_high - H_cb_low);  f = pos (short) / 1 - pos (long)   favourable room share
  room   (price - H_cb_low) / mean 1-min range (the candle stop's own unit, trailing 60 closed minutes)
  nest   |T_cb_low - H_cb_low| <= delta * mean range                      the lower tf's opposite bound on H's bound
  exz    {H}_cb_inzone_long was 1 earlier in the CURRENT H candle (wall clock), is 0 now, price >= 1 range above H's long zone
Variants: pos{q}, room{k}, nest{d}, exz, exzpos{q}, mirpos{q} (control), sh{q} (pos read 24 h earlier, placebo);
pairs 15<60, 15<240, 60<240, ladder. The frozen 2y values are passed with --pos= --room= --nest=; the grid is also run.
usage: python3 2026-10-21-bounds-geometry-replay.py <data_dir> <klines_dir> <stats.json> [--start=ISO] [--fee=0.001] --pos=q --room=k --nest=d
"""
import sys, os, json, importlib.util, datetime as dt
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("harness", os.path.join(HERE, "2026-10-21-higher-tf-trend-replay.py"))
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)

D = h.D; N = h.N; T_TS = h.T_TS; T_PX = h.T_PX; TFS = h.TFS; SIDES = h.SIDES; HIGHER = h.HIGHER; fmt_ts = h.fmt_ts
FZ = {"pos": float(h.arg("pos", "0.25")), "room": float(h.arg("room", "2")), "nest": float(h.arg("nest", "1"))}
QS = (0.15, 0.25, 0.35, 0.5); KS = (1.0, 2.0, 3.0, 5.0); DS = (0.5, 1.0, 2.0); EXZ_R = 1.0; SHIFT_MS = 24 * 3600 * 1000
PAIRS = {"15<60": {15: (60,)}, "15<240": {15: (240,)}, "60<240": {60: (240,)}, "ladder": HIGHER}

# ---------------------------------------------------------------- extra stored indicators (same snapshot/expiry rule as the harness)
EXTRA = [f"{tf}_{n}" for tf in TFS for n in ("cb_high", "cb_low")]
rows = defaultdict(list)
with open(f"{D}/indicators.csv") as f:
    for line in f:
        recv, exp, name, val = line.rstrip("\n").split(",")
        if name in EXTRA:
            rows[name].append((int(recv), int(exp), float(val)))
XI = {}
for name in EXTRA:
    r = sorted(rows[name])
    recv = np.array([x[0] for x in r], dtype=np.int64); exp = np.array([x[1] for x in r], dtype=np.int64); val = np.array([x[2] for x in r])
    idx = np.searchsorted(recv, T_TS, "right") - 1
    v = np.full(N, np.nan); ok = idx >= 0
    ok[ok] &= T_TS[ok] < exp[idx[ok]]
    v[ok] = val[idx[ok]]
    XI[name] = v
I0 = h.I_START

# mean 1-min range per trade (the candle stop's unit) — same helper as the harness
RANGE = np.full(N, np.nan)
mk = T_TS // 60_000
_, first = np.unique(mk, return_index=True)
for a, b in zip(first, np.r_[first[1:], N]):
    r = h.mean_range(int(T_TS[a]))
    if r is not None:
        RANGE[a:b] = r

print("\n=== STORED BOUNDS GATE: cb_high / cb_low present at the trades in the window; zone lines consistent (zone_long = low + 0.05 span) ===")
for tf in TFS:
    lo, hi = XI[f"{tf}_cb_low"], XI[f"{tf}_cb_high"]; zl = h.ZONE[(tf, "Buy")]; zs = h.ZONE[(tf, "Sell")]
    m = ~np.isnan(lo[I0:]) & ~np.isnan(hi[I0:]) & ~np.isnan(zl[I0:])
    span = (hi - lo)[I0:][m]
    fr = (zl[I0:][m] - lo[I0:][m]) / span
    print(f"tf {tf:3d}: present {np.mean(~np.isnan(lo[I0:]) & ~np.isnan(hi[I0:])):.3f}; span > 0 {np.mean(span > 0):.3f}; zone_long frac median {np.median(fr):.4f} "
          f"(zone_short {np.median((hi[I0:][m] - zs[I0:][m]) / span):.4f}); span / mean range q50 {np.nanmedian(span / RANGE[I0:][m]):.1f}")

# ---------------------------------------------------------------- geometry per trade and higher tf
def candle_start(ts, tf):
    return (ts // (tf * 60_000)) * (tf * 60_000)


def seg_cummax_by_candle(active, tf):
    """cumulative OR of `active` within each wall-clock H candle (trades are time-sorted)."""
    seg = candle_start(T_TS, tf)
    out = np.zeros(N, dtype=bool)
    starts = np.flatnonzero(np.r_[True, seg[1:] != seg[:-1]]); ends = np.r_[starts[1:], N]
    for a, b in zip(starts, ends):
        out[a:b] = np.maximum.accumulate(active[a:b])
    return out


POS = {}; EXZ = {}; ROOM = {}
for tf in TFS:
    lo, hi = XI[f"{tf}_cb_low"], XI[f"{tf}_cb_high"]; span = hi - lo
    with np.errstate(invalid="ignore", divide="ignore"):
        POS[tf] = np.where(span > 0, (T_PX - lo) / span, np.nan)
        ROOM[(tf, "Sell")] = (T_PX - lo) / RANGE; ROOM[(tf, "Buy")] = (hi - T_PX) / RANGE
    inzl = h.INZONE[(tf, "Buy")]; inzs = h.INZONE[(tf, "Sell")]
    zl = h.ZONE[(tf, "Buy")]; zs = h.ZONE[(tf, "Sell")]
    with np.errstate(invalid="ignore"):
        EXZ[(tf, "Sell")] = seg_cummax_by_candle(inzl, tf) & ~inzl & ((T_PX - zl) / RANGE >= EXZ_R)
        EXZ[(tf, "Buy")] = seg_cummax_by_candle(inzs, tf) & ~inzs & ((zs - T_PX) / RANGE >= EXZ_R)
# placebo: pos read 24 h earlier
POS_SH = {}
j = np.searchsorted(T_TS, T_TS - SHIFT_MS, "right") - 1
for tf in TFS:
    v = np.full(N, np.nan); ok = j >= 0; v[ok] = POS[tf][j[ok]]; POS_SH[tf] = v


def f_of(tf, s, shifted=False):
    p = (POS_SH if shifted else POS)[tf]
    return p if s == "Sell" else 1.0 - p


VETO = {}   # (fam, H, side) -> True = veto
for Hh in TFS:
    for s in SIDES:
        f = f_of(Hh, s); fsh = f_of(Hh, s, True); room = ROOM[(Hh, s)]
        with np.errstate(invalid="ignore"):
            for qq in QS:
                VETO[(f"pos{qq}", Hh, s)] = f < qq
                VETO[(f"mirpos{qq}", Hh, s)] = f > 1 - qq
                VETO[(f"sh{qq}", Hh, s)] = fsh < qq
                VETO[(f"exzpos{qq}", Hh, s)] = EXZ[(Hh, s)] & (f < qq)
            for kk in KS:
                VETO[(f"room{kk}", Hh, s)] = room < kk
            VETO[("exz", Hh, s)] = EXZ[(Hh, s)]
# nest depends on the lower tf too
for T in (15, 60):
    for Hh in HIGHER[T]:
        for s in SIDES:
            own_opp = XI[f"{T}_cb_low" if s == "Sell" else f"{T}_cb_high"]; hs = XI[f"{Hh}_cb_low" if s == "Sell" else f"{Hh}_cb_high"]
            with np.errstate(invalid="ignore"):
                d = np.abs(own_opp - hs) / RANGE
            for dd in DS:
                VETO[(f"nest{dd}", Hh, s, T)] = d <= dd

print("\n=== state rates at the window's trades (veto = True), per H and side ===")
for Hh in TFS:
    for s in SIDES:
        print(f"H {Hh:3d} {s:4s}: " + " ".join(f"{fam} {np.nanmean(VETO[(fam, Hh, s)][I0:]):.3f}" for fam in (f"pos{FZ['pos']}", f"room{FZ['room']}", "exz", f"exzpos{FZ['pos']}", f"mirpos{FZ['pos']}", f"sh{FZ['pos']}"))
              + f" | f finite {np.isfinite(f_of(Hh, s)[I0:]).mean():.3f}")


def variant(fam, rule):
    out = {}
    for tf in TFS:
        for s in SIDES:
            fl = h.F[tf][s].copy()
            for Hh in rule.get(tf, ()):
                key = (fam, Hh, s, tf) if fam.startswith("nest") else (fam, Hh, s)
                fl &= ~VETO[key]
            out[(tf, s)] = fl
    return out


VARIANTS = {"live": h.VARIANTS["live"], "e25": h.VARIANTS["e25"], "none": h.VARIANTS["none"]}
FROZEN = [f"pos{FZ['pos']}", f"room{FZ['room']}", f"nest{FZ['nest']}", "exz", f"exzpos{FZ['pos']}", f"mirpos{FZ['pos']}", f"sh{FZ['pos']}"]
for fam in FROZEN:
    for pk, rule in PAIRS.items():
        VARIANTS[f"{fam}|{pk}"] = variant(fam, rule)
GRID = [f"pos{qq}" for qq in QS] + [f"room{kk}" for kk in KS] + [f"nest{dd}" for dd in DS] + [f"exzpos{qq}" for qq in QS]
for fam in GRID:
    for pk in ("15<60", "ladder"):
        VARIANTS.setdefault(f"{fam}|{pk}", variant(fam, PAIRS[pk]))
ORDER = list(VARIANTS)
FEE = h.FEE

if __name__ == "__main__":
    results = {v: h.simulate(VARIANTS[v], fee=FEE) for v in ORDER}
    print(f"\n=== VARIANTS, window {fmt_ts(T_TS[I0])} -> {fmt_ts(T_TS[-1])}, paper (no fees); frozen 2y values {FZ} ===")
    for v in ORDER:
        cl, fi, sk = results[v]
        print(h.row(v, h.stats(cl), f"| fires {len(fi)} ({'/'.join(str(sum(f['tf'] == tf for f in fi)) for tf in TFS)}) skip {sk}"))
    print("\n--- by the opening fire's tf: n, net, PF ---")
    for v in ORDER:
        print(f"{v:>16s} | {h.by_tf(results[v][0])}")
    print("\n--- by side: n, net ---")
    for v in ORDER:
        cl = results[v][0]
        print(f"{v:>16s} | " + " | ".join(f"{s}: {sum(p['side'] == s for p in cl)}, {sum(p['pnl'] for p in cl if p['side'] == s):+.0f}" for s in SIDES))
    for ref in ("e25", "live"):
        print(f"\n--- paired vs {ref}: trades matched by (open trade, side); unmatched enter as (pnl − 0) ---")
        base = {(p["open_ts"], p["side"]): p for p in results[ref][0]}
        rng = np.random.default_rng(1)
        for v in ORDER:
            other = {(p["open_ts"], p["side"]): p for p in results[v][0]}
            keys = set(base) | set(other)
            diffs = np.array([other[k]["pnl"] if k in other else 0.0 for k in keys]) - np.array([base[k]["pnl"] if k in base else 0.0 for k in keys])
            both = sum(1 for k in keys if k in base and k in other)
            boot = np.array([rng.choice(diffs, len(diffs), replace=True).sum() for _ in range(4000)])
            print(f"{v:>16s} | shared {both:3d} | only-var {len(other) - both:3d} | only-{ref} {len(base) - both:3d} | Δnet {diffs.sum():+7.0f} | CI90 [{np.percentile(boot, 5):+6.0f}, {np.percentile(boot, 95):+6.0f}] | P(Δ<0) {np.mean(boot < 0):.2f}")
    print("\n--- fees: net after f %/side ---")
    for v in ORDER:
        cl = results[v][0]
        if not cl:
            continue
        turn = sum(p["size"] * (p["entry"] + p["exit"]) for p in cl); gross = sum(p["pnl"] for p in cl)
        print(f"{v:>16s} | gross {gross:+7.0f} | " + " | ".join(f"{f * 100:.2f}% {gross - f * turn:+7.0f}" for f in (0.0001, 0.0002, 0.0005)) + f" | breakeven {gross / turn * 100:.3f} %")
    half = (T_TS[I0] + T_TS[-1]) // 2
    days = sorted({int(p["open_ts"] // 86_400_000) for v in ORDER for p in results[v][0]})
    print(f"\n--- stability: net by half (split {fmt_ts(half)}) and by UTC day, no fees ---")
    print(f"{'variant':>16s} | {'H1':>7s} {'n':>3s} | {'H2':>7s} {'n':>3s} | " + " | ".join(f"{dt.datetime.fromtimestamp(d * 86400, dt.timezone.utc).strftime('%m-%d'):>6s} n" for d in days))
    for v in ORDER:
        cl = results[v][0]
        h1 = [p for p in cl if p["open_ts"] < half]; h2 = [p for p in cl if p["open_ts"] >= half]
        per = [f"{sum(p['pnl'] for p in cl if int(p['open_ts'] // 86_400_000) == d):+6.0f} {sum(int(p['open_ts'] // 86_400_000) == d for p in cl):2d}" for d in days]
        print(f"{v:>16s} | {sum(p['pnl'] for p in h1):+7.0f} {len(h1):3d} | {sum(p['pnl'] for p in h2):+7.0f} {len(h2):3d} | " + " | ".join(per))
    # ---- mechanism: e25 positions split by the higher tf's geometry at the open
    print("\n--- e25 POSITIONS by opening tf, split by the higher tf's geometry at the open: n, net, PF, stop share, mean ---")
    e25 = results["e25"][0]
    for tf in (15, 60):
        for Hh in HIGHER[tf]:
            c = [p for p in e25 if p["tf"] == tf]
            f = np.array([f_of(Hh, p["side"])[p["open_i"]] for p in c]); pnl = np.array([p["pnl"] for p in c]); st = np.array([p["reason"] == "stop" for p in c])
            print(f"tf {tf:3d} by H {Hh:3d}: n {len(c)}, f finite {np.isfinite(f).mean():.2f}, f q05/25/50/75/95 " + " ".join(f"{np.nanpercentile(f, x):+.2f}" for x in (5, 25, 50, 75, 95)))
            for a, b in ((-9, 0), (0, 0.15), (0.15, 0.25), (0.25, 0.35), (0.35, 0.5), (0.5, 0.75), (0.75, 1.0), (1.0, 9)):
                m = (f >= a) & (f < b)
                if m.sum():
                    p = pnl[m]; w = p[p > 0].sum(); l = abs(p[p < 0].sum())
                    print(f"   f [{a},{b}): n {m.sum():3d}, net {p.sum():+6.0f}, PF {w / l if l else float('inf'):4.2f}, stop {st[m].mean():.0%}, mean {p.mean():+5.0f}")
            for lab, key in (("exz", ("exz", Hh)), (f"nest{FZ['nest']}", (f"nest{FZ['nest']}", Hh))):
                arr = {s: VETO[key + (s,)] if lab == "exz" else VETO[key + (s, tf)] for s in SIDES}
                for val in (True, False):
                    cc = [p for p in c if bool(arr[p["side"]][p["open_i"]]) == val]
                    if cc:
                        p = np.array([x["pnl"] for x in cc]); w = p[p > 0].sum(); l = abs(p[p < 0].sum())
                        print(f"   {lab} = {str(val):5s}: n {len(cc):3d}, net {p.sum():+6.0f}, PF {w / l if l else float('inf'):4.2f}, stop {np.mean([x['reason'] == 'stop' for x in cc]):.0%}, mean {p.mean():+5.0f}")
    # ---- fire-level: which e25 fires each frozen variant removes
    print("\n--- fire-level vs e25: lost / new fires per frozen variant (pair 15<60 and ladder) ---")
    f25 = {(f["ts"], f["side"], f["tf"]): f for f in results["e25"][1]}
    for fam in FROZEN:
        for pk in ("15<60", "ladder"):
            v = f"{fam}|{pk}"; fv = {(f["ts"], f["side"], f["tf"]): f for f in results[v][1]}
            lost = [f25[k] for k in f25 if k not in fv]; new = [fv[k] for k in fv if k not in f25]
            print(f"{v:>16s}: e25 fires {len(f25)}, lost {len(lost)} (by tf {dict((tf, sum(f['tf'] == tf for f in lost)) for tf in TFS)}), new {len(new)}")
