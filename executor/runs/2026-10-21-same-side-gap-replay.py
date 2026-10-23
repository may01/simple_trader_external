#!/usr/bin/env python3
"""Replay: a close HIGHER-tf zone on the SAME side as a lower-tf CB zone fire — veto the lower fire, or delay it to a
limit at the higher zone line.

Question (user, 2026-10-21): when a 15-min zone and a 60-min zone are close, the bigger one drags the price to itself,
so a 15-min fire with a nearby 60-min zone is more likely to stop out. Impact on profit of removing the lower-tf fire
or delaying the opening.

Flow = 2026-10-21-higher-tf-trend-replay.py imported as a module (fires re-derived on every trade, 1-min class X 0.7,
candle stop, cbnc target + trend-flip exit, reversal, paper = no fees). The veto per (tf, side) is ANDed into the own
forming EMA-25 flag (e25). Per trade and higher tf H (stored {H}_cb_zone_long/short, same snapshot/expiry rule as the
harness; long shown, short mirrored; u = mean 1-min range, the candle stop's unit):
  g      (price - H_zone_long) / u        signed gap to H's same-side zone line; > 0 = H's zone beyond the entry (stop side)
  gd     g * u / dist                      the same gap in units of this trade's candle-stop distance
  mr     (H_zone_short - price) / u        control: gap to H's OPPOSITE zone (room ahead)
  sh     g read 24 h earlier               placebo
Vetoes: gz{k} 0 <= g < k; gzb{k} |g| < k; gzin g < 0; gd{m} 0 <= gd < m; mr{k}; sh{k}.
Delay: dl{k}{N} — a fire that would open a NEW position (flat) with 0 <= g < k for some H of the pair does not open;
a limit at H's zone line (frozen at the fire) is live N min; filled at the line on the first trade at or beyond it,
candle stop + cbnc target taken at the fill; cancelled on expiry or when another fire opens / pends. dlc{k}{N} also
requires the 1-min class at the fill not to be against the trade. Reversal fires open immediately (no delay).
usage: python3 2026-10-21-same-side-gap-replay.py <data_dir> <klines_dir> <stats.json> [--start=ISO] [--fee=0.001] --gz=k --gd=m --dl=k,N
"""
import sys, os, importlib.util, datetime as dt
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("harness", os.path.join(HERE, "2026-10-21-higher-tf-trend-replay.py"))
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)

D = h.D; N = h.N; T_TS = h.T_TS; T_PX = h.T_PX; TFS = h.TFS; SIDES = h.SIDES; HIGHER = h.HIGHER; fmt_ts = h.fmt_ts
_dl = h.arg("dl", "2.0,60").split(",")
FZ = {"gz": float(h.arg("gz", "2.0")), "gd": float(h.arg("gd", "1.0")), "dl": (float(_dl[0]), int(_dl[1]))}
KS = (0.5, 1.0, 2.0, 3.0, 5.0); MS = (0.5, 1.0, 1.5, 2.0, 3.0); DLK = (1.0, 2.0, 3.0, 5.0); DLN = (15, 60)
SHIFT_MS = 24 * 3600 * 1000
PAIRS = {"15<60": {15: (60,)}, "15<240": {15: (240,)}, "60<240": {60: (240,)}, "ladder": HIGHER}
GBINS = ((-99, -2), (-2, -1), (-1, 0), (0, 0.5), (0.5, 1), (1, 2), (2, 3), (3, 5), (5, 8), (8, 999))
DBINS = ((-99, 0), (0, 0.5), (0.5, 1), (1, 1.5), (1.5, 2), (2, 3), (3, 5), (5, 999))
I0 = h.I_START

# ---------------------------------------------------------------- mean 1-min range per trade (the candle stop's unit)
RANGE = np.full(N, np.nan)
mk = T_TS // 60_000
_, first = np.unique(mk, return_index=True)
for a, b in zip(first, np.r_[first[1:], N]):
    r = h.mean_range(int(T_TS[a]))
    if r is not None:
        RANGE[a:b] = r

# ---------------------------------------------------------------- 15-min running extreme per trade (vectorised candle-stop anchor) -> stop distance
seg = (T_TS // h.ANCHOR_MS) * h.ANCHOR_MS
starts = np.flatnonzero(np.r_[True, seg[1:] != seg[:-1]]); ends = np.r_[starts[1:], N]
EXT_LO = np.empty(N); EXT_HI = np.empty(N)
for a, b in zip(starts, ends):
    EXT_LO[a:b] = np.minimum.accumulate(T_PX[a:b]); EXT_HI[a:b] = np.maximum.accumulate(T_PX[a:b])
DIST = {}
with np.errstate(invalid="ignore"):
    stop_b = EXT_LO - RANGE; stop_s = EXT_HI + RANGE
    DIST["Buy"] = np.where(np.isfinite(stop_b) & (stop_b < T_PX), T_PX - stop_b, T_PX * h.PLACEHOLDER)
    DIST["Sell"] = np.where(np.isfinite(stop_s) & (stop_s > T_PX), stop_s - T_PX, T_PX * h.PLACEHOLDER)

# gate: vectorised stop distance == harness candle_stop at the e25 fires (checked below after the sims)

# ---------------------------------------------------------------- gap quantities per trade and higher tf
G = {}; GD = {}; MR = {}; GSH = {}
j24 = np.searchsorted(T_TS, T_TS - SHIFT_MS, "right") - 1
for Hh in TFS:
    zl = h.ZONE[(Hh, "Buy")]; zs = h.ZONE[(Hh, "Sell")]
    with np.errstate(invalid="ignore", divide="ignore"):
        G[(Hh, "Buy")] = (T_PX - zl) / RANGE; G[(Hh, "Sell")] = (zs - T_PX) / RANGE
        MR[(Hh, "Buy")] = (zs - T_PX) / RANGE; MR[(Hh, "Sell")] = (T_PX - zl) / RANGE
        for s in SIDES:
            GD[(Hh, s)] = G[(Hh, s)] * RANGE / DIST[s]
            v = np.full(N, np.nan); ok = j24 >= 0; v[ok] = G[(Hh, s)][j24[ok]]; GSH[(Hh, s)] = v

print("\n=== STORED ZONE LINES GATE: present at the window's trades; g distribution ===")
for Hh in TFS:
    for s in SIDES:
        g = G[(Hh, s)][I0:]
        print(f"H {Hh:3d} {s:4s}: zone line present {np.isfinite(h.ZONE[(Hh, s)][I0:]).mean():.3f}; g q05/25/50/75/95 " +
              " ".join(f"{np.nanpercentile(g, x):+.1f}" for x in (5, 25, 50, 75, 95)) + f"; share 0<=g<2 {np.nanmean((g >= 0) & (g < 2)):.3f}, g<0 {np.nanmean(g < 0):.3f}")

VETO = {}
for Hh in TFS:
    for s in SIDES:
        g = G[(Hh, s)]; gd = GD[(Hh, s)]; mr = MR[(Hh, s)]; sh = GSH[(Hh, s)]
        with np.errstate(invalid="ignore"):
            for kk in KS:
                VETO[(f"gz{kk}", Hh, s)] = (g >= 0) & (g < kk)
                VETO[(f"gzb{kk}", Hh, s)] = np.abs(g) < kk
                VETO[(f"mr{kk}", Hh, s)] = (mr >= 0) & (mr < kk)
                VETO[(f"sh{kk}", Hh, s)] = (sh >= 0) & (sh < kk)
            for mm in MS:
                VETO[(f"gd{mm}", Hh, s)] = (gd >= 0) & (gd < mm)
            VETO[("gzin", Hh, s)] = g < 0

print("\n=== state rates at the window's trades (veto = True), per H and side ===")
for Hh in TFS:
    for s in SIDES:
        print(f"H {Hh:3d} {s:4s}: " + " ".join(f"{fam} {np.nanmean(VETO[(fam, Hh, s)][I0:]):.3f}" for fam in (f"gz{FZ['gz']}", f"gzb{FZ['gz']}", "gzin", f"gd{FZ['gd']}", f"mr{FZ['gz']}", f"sh{FZ['gz']}")))


def variant(fam, rule):
    out = {}
    for tf in TFS:
        for s in SIDES:
            fl = h.F[tf][s].copy()
            for Hh in rule.get(tf, ()):
                fl &= ~VETO[(fam, Hh, s)]
            out[(tf, s)] = fl
    return out


# ---------------------------------------------------------------- the flow with an optional pending limit (delay)
def simulate(flags, fee=0.0, delay=None):
    """delay = dict(k=, N=, rule=, cls=bool) or None (then identical to the harness's simulate)"""
    base_ok = {k: h.GEO_OK[k] & flags[k] for k in h.GEO_OK}
    bal = h.START_BAL; pos = None; closed = []; fires = []; fired = {}; last_fired = None; skipped_same = 0
    pend = None; pend_log = []
    poss = h.POSS_IDX; p = 0; np_ = len(poss)
    i = I0
    while i < N:
        if pos is None and pend is None:
            while p < np_ and poss[p] < i:
                p += 1
            if p >= np_:
                break
            i = int(poss[p])
        ts = int(T_TS[i]); px = T_PX[i]
        # pending limit: expiry, then fill (only while flat)
        if pend is not None:
            if ts > pend["expiry"]:
                pend["outcome"] = "expired"; pend_log.append(pend); pend = None
            elif pos is None and ((pend["side"] == "Buy" and px <= pend["limit"]) or (pend["side"] == "Sell" and px >= pend["limit"])) \
                    and (not delay["cls"] or int(h.C07[i]) != (-1 if pend["side"] == "Buy" else 1)):
                e = pend["limit"]; side = pend["side"]
                stop, anchor, off = h.candle_stop(side, i); kind = "candle"
                if stop is None or (side == "Buy" and stop >= e) or (side == "Sell" and stop <= e):
                    stop = e * (1 - h.PLACEHOLDER) if side == "Buy" else e * (1 + h.PLACEHOLDER); kind = "placeholder"
                dist = abs(e - stop); size = min(h.RISK / dist, bal * h.MAX_NOTIONAL_FRAC / e)
                tgt = h.TARGET[(pend["tf"], side)][i]
                if not np.isfinite(tgt):
                    tgt = pend["target"]
                pos = dict(side=side, entry=e, stop=stop, stop_kind=kind, target=tgt, size=size, open_ts=ts, open_i=i, extreme=None,
                           tf=pend["tf"], rule="delayed", dist=dist, armed=False, cls_open=int(h.C07[i]), fire_ts=pend["fire_ts"], delay_min=(ts - pend["fire_ts"]) / 60000)
                pend["outcome"] = "filled"; pend["fill_ts"] = ts; pend_log.append(pend); pend = None
                i += 1
                continue
        if h.POSSIBLE_ANY[i]:
            cls = int(h.C07[i]); cands = []
            for tf in TFS:
                for s in SIDES:
                    k = (tf, s)
                    if not base_ok[k][i]:
                        continue
                    d = 1 if s == "Buy" else -1
                    r1 = h.INZONE[k][i] and cls == d
                    r2 = h.REJ[k][i] and (cls == 0 or cls == d)
                    if r1 or r2:
                        cands.append((tf, s, h.ZONE[k][i], "in_zone" if r1 else "zone_rejection", h.TARGET[k][i]))
            if cands:
                cands = [c for c in cands if fired.get((c[0], c[1])) != c[2]]
                sides = {c[1] for c in cands}
                if cands and len(sides) == 1 and not (last_fired is not None and ts - last_fired < h.MIN_INTERVAL_MS):
                    best = max(cands, key=lambda c: c[0])
                    for c in cands:
                        fired[(c[0], c[1])] = c[2]
                    last_fired = ts
                    ev = dict(i=i, ts=ts, side=best[1], tf=best[0], zone=best[2], rule=best[3], target=best[4], price=px, cls=cls, slope=float(h.SLOPE[i]))
                    fires.append(ev)
                    if pos is not None and pos["side"] == ev["side"]:
                        skipped_same += 1
                    else:
                        if pos is not None:
                            h.close_pos(pos, px, ts, "reversal", closed, fee); bal += closed[-1]["pnl"]; pos = None
                            do_delay = False
                        else:
                            do_delay = delay is not None and any(VETO[(f"gz{delay['k']}", Hh, ev["side"])][i] for Hh in delay["rule"].get(ev["tf"], ()))
                        if pend is not None:
                            pend["outcome"] = "cancelled"; pend_log.append(pend); pend = None
                        if do_delay:
                            Hh = next(Hh for Hh in delay["rule"][ev["tf"]] if VETO[(f"gz{delay['k']}", Hh, ev["side"])][i])
                            pend = dict(side=ev["side"], limit=float(h.ZONE[(Hh, ev["side"])][i]), expiry=ts + delay["N"] * 60_000, tf=ev["tf"], H=Hh,
                                        fire_ts=ts, fire_i=i, fire_px=px, target=ev["target"], g=float(G[(Hh, ev["side"])][i]))
                            i += 1
                            continue
                        stop, anchor, off = h.candle_stop(ev["side"], i); kind = "candle"
                        if stop is None:
                            stop = px * (1 - h.PLACEHOLDER) if ev["side"] == "Buy" else px * (1 + h.PLACEHOLDER); kind = "placeholder"
                        dist = abs(px - stop); size = min(h.RISK / dist, bal * h.MAX_NOTIONAL_FRAC / px)
                        pos = dict(side=ev["side"], entry=px, stop=stop, stop_kind=kind, target=ev["target"], size=size, open_ts=ts,
                                   open_i=i, extreme=None, tf=ev["tf"], rule=ev["rule"], dist=dist, armed=False, cls_open=cls)
                        i += 1
                        continue
        if pos is None:
            i += 1
            continue
        if (pos["side"] == "Buy" and px <= pos["stop"]) or (pos["side"] == "Sell" and px >= pos["stop"]):
            h.close_pos(pos, px, ts, "stop", closed, fee); bal += closed[-1]["pnl"]; pos = None; i += 1
            continue
        if pos["extreme"] is None:
            pos["extreme"] = px
        elif pos["side"] == "Buy":
            pos["extreme"] = max(pos["extreme"], px)
        else:
            pos["extreme"] = min(pos["extreme"], px)
        pos["armed"] = pos["extreme"] > pos["target"] if pos["side"] == "Buy" else pos["extreme"] < pos["target"]
        if pos["armed"]:
            co = int(h.C07[i])
            if (pos["side"] == "Buy" and co == -1) or (pos["side"] == "Sell" and co == 1):
                h.close_pos(pos, px, ts, "target", closed, fee); bal += closed[-1]["pnl"]; pos = None
        i += 1
    if pos is not None:
        h.close_pos(pos, float(T_PX[-1]), int(T_TS[-1]), "open_at_end", closed, fee)
    if pend is not None:
        pend["outcome"] = "open_at_end"; pend_log.append(pend)
    return closed, fires, skipped_same, pend_log


VARIANTS = {"live": (h.VARIANTS["live"], None), "e25": (h.VARIANTS["e25"], None), "none": (h.VARIANTS["none"], None)}
FROZEN = [f"gz{FZ['gz']}", f"gzb{FZ['gz']}", "gzin", f"gd{FZ['gd']}", f"mr{FZ['gz']}", f"sh{FZ['gz']}"]
for fam in FROZEN:
    for pk, rule in PAIRS.items():
        VARIANTS[f"{fam}|{pk}"] = (variant(fam, rule), None)
for pk, rule in PAIRS.items():
    for lab, cr in (("dl", False), ("dlc", True)):
        VARIANTS[f"{lab}{FZ['dl'][0]}{FZ['dl'][1]}|{pk}"] = (h.VARIANTS["e25"], dict(k=FZ["dl"][0], N=FZ["dl"][1], rule=rule, cls=cr))
GRID = [f"gz{kk}" for kk in KS] + [f"gzb{kk}" for kk in KS] + [f"gd{mm}" for mm in MS] + [f"mr{kk}" for kk in KS] + [f"sh{kk}" for kk in KS]
for fam in GRID:
    for pk in ("15<60", "ladder"):
        VARIANTS.setdefault(f"{fam}|{pk}", (variant(fam, PAIRS[pk]), None))
for fam in [f"gz{kk}" for kk in KS] + [f"gd{mm}" for mm in MS]:
    for pk in ("15<240", "60<240"):
        VARIANTS.setdefault(f"{fam}|{pk}", (variant(fam, PAIRS[pk]), None))
for pk in ("15<60", "ladder"):
    for lab, cr in (("dl", False), ("dlc", True)):
        for kk in DLK:
            for nn in DLN:
                VARIANTS.setdefault(f"{lab}{kk}{nn}|{pk}", (h.VARIANTS["e25"], dict(k=kk, N=nn, rule=PAIRS[pk], cls=cr)))
ORDER = list(VARIANTS)
FEE = h.FEE

if __name__ == "__main__":
    import time
    t0 = time.time()
    results = {}
    for v in ORDER:
        fl, dl = VARIANTS[v]
        results[v] = simulate(fl, fee=FEE, delay=dl)
    print(f"\n{len(ORDER)} variants simulated in {time.time() - t0:.0f} s")
    # ---- reproduction gates
    ref = h.simulate(h.VARIANTS["e25"], fee=FEE)
    mine = results["e25"]
    same = len(ref[0]) == len(mine[0]) and all(a["open_ts"] == b["open_ts"] and a["pnl"] == b["pnl"] for a, b in zip(ref[0], mine[0]))
    print(f"=== GATE: this script's flow (no delay) vs the harness simulate on e25: positions {len(ref[0])} / {len(mine[0])}, identical {same}; "
          f"gz0 (k=0, nothing vetoed) == e25: {len(simulate(variant('gz0.5', {}), fee=FEE)[0]) == len(mine[0])}")
    e25 = mine[0]
    dd = np.array([abs(DIST[p['side']][p['open_i']] - p['dist']) / p['dist'] for p in e25])
    print(f"=== GATE: vectorised stop distance vs the harness candle_stop at the e25 opens: max rel diff {dd.max():.2e}, > 1e-9 on {np.mean(dd > 1e-9):.3f}")
    print(f"\n=== VARIANTS, window {fmt_ts(T_TS[I0])} -> {fmt_ts(T_TS[-1])}, paper (no fees); frozen 2y values {FZ} ===")
    for v in ORDER:
        cl, fi, sk, pl = results[v]
        extra = f"| fires {len(fi)} ({'/'.join(str(sum(f['tf'] == tf for f in fi)) for tf in TFS)}) skip {sk}"
        if pl:
            oc = defaultdict(int)
            for x in pl:
                oc[x["outcome"]] += 1
            dl_pos = [p for p in cl if p["rule"] == "delayed"]
            extra += f" | pend {len(pl)}: " + " ".join(f"{k} {n}" for k, n in sorted(oc.items())) + f"; delayed pos {len(dl_pos)} net {sum(p['pnl'] for p in dl_pos):+.0f}"
        print(h.row(v, h.stats(cl), extra))
    print("\n--- by the opening fire's tf: n, net, PF ---")
    for v in ORDER:
        print(f"{v:>16s} | {h.by_tf(results[v][0])}")
    print("\n--- by side: n, net ---")
    for v in ORDER:
        cl = results[v][0]
        print(f"{v:>16s} | " + " | ".join(f"{s}: {sum(p['side'] == s for p in cl)}, {sum(p['pnl'] for p in cl if p['side'] == s):+.0f}" for s in SIDES))
    for ref_ in ("e25", "live"):
        print(f"\n--- paired vs {ref_}: trades matched by (open trade, side); unmatched enter as (pnl − 0) ---")
        base = {(p["open_ts"], p["side"]): p for p in results[ref_][0]}
        rng = np.random.default_rng(1)
        for v in ORDER:
            other = {(p["open_ts"], p["side"]): p for p in results[v][0]}
            keys = set(base) | set(other)
            diffs = np.array([other[k]["pnl"] if k in other else 0.0 for k in keys]) - np.array([base[k]["pnl"] if k in base else 0.0 for k in keys])
            both = sum(1 for k in keys if k in base and k in other)
            boot = np.array([rng.choice(diffs, len(diffs), replace=True).sum() for _ in range(4000)])
            print(f"{v:>16s} | shared {both:3d} | only-var {len(other) - both:3d} | only-{ref_} {len(base) - both:3d} | Δnet {diffs.sum():+7.0f} | CI90 [{np.percentile(boot, 5):+6.0f}, {np.percentile(boot, 95):+6.0f}] | P(Δ<0) {np.mean(boot < 0):.2f}")
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
    # ---- mechanism: e25 positions split by the gap at the open
    print("\n--- e25 POSITIONS by opening tf, split by the signed gap g to the higher tf's SAME-side zone line at the open (u = mean 1-min range): n, net, PF, stop share, mean; reach = price touched H's line within 60 min ---")
    for tf in (15, 60):
        for Hh in HIGHER[tf]:
            c = [p for p in e25 if p["tf"] == tf]
            g = np.array([G[(Hh, p["side"])][p["open_i"]] for p in c]); gd = np.array([GD[(Hh, p["side"])][p["open_i"]] for p in c])
            pnl = np.array([p["pnl"] for p in c]); st = np.array([p["reason"] == "stop" for p in c])
            reach = np.zeros(len(c), dtype=bool)
            for m, p in enumerate(c):
                i = p["open_i"]; line = h.ZONE[(Hh, p["side"])][i]; j = int(np.searchsorted(T_TS, T_TS[i] + 3_600_000, "left"))
                if np.isfinite(line):
                    reach[m] = (T_PX[i + 1:j] <= line).any() if p["side"] == "Buy" else (T_PX[i + 1:j] >= line).any()
            print(f"tf {tf:3d} by H {Hh:3d}: n {len(c)}, g finite {np.isfinite(g).mean():.2f}, g q05/25/50/75/95 " + " ".join(f"{np.nanpercentile(g, x):+.1f}" for x in (5, 25, 50, 75, 95)))
            for a, b in GBINS:
                m = (g >= a) & (g < b)
                if m.sum():
                    p = pnl[m]; w = p[p > 0].sum(); l = abs(p[p < 0].sum())
                    print(f"   g [{a},{b}): n {m.sum():3d}, net {p.sum():+6.0f}, PF {w / l if l else float('inf'):4.2f}, stop {st[m].mean():.0%}, mean {p.mean():+5.0f}, reach {reach[m].mean():.2f}")
            for a, b in DBINS:
                m = (gd >= a) & (gd < b)
                if m.sum():
                    p = pnl[m]; w = p[p > 0].sum(); l = abs(p[p < 0].sum())
                    print(f"   gd [{a},{b}) stop-dist: n {m.sum():3d}, net {p.sum():+6.0f}, PF {w / l if l else float('inf'):4.2f}, stop {st[m].mean():.0%}, mean {p.mean():+5.0f}, reach {reach[m].mean():.2f}")
            for lab in (f"sh{FZ['gz']}", f"mr{FZ['gz']}"):
                for val in (True, False):
                    cc = [p for p in c if bool(VETO[(lab, Hh, p["side"])][p["open_i"]]) == val]
                    if cc:
                        p = np.array([x["pnl"] for x in cc]); w = p[p > 0].sum(); l = abs(p[p < 0].sum())
                        print(f"   {lab} = {str(val):5s}: n {len(cc):3d}, net {p.sum():+6.0f}, PF {w / l if l else float('inf'):4.2f}, stop {np.mean([x['reason'] == 'stop' for x in cc]):.0%}, mean {p.mean():+5.0f}")
    # ---- delay detail: pended fires and what became of them vs the e25 position opened at that fire
    print("\n--- delay variants: pended fires → outcome; the e25 position at the same fire (open_ts) for comparison ---")
    e25_by_ts = {p["open_ts"]: p for p in e25}
    for v in ORDER:
        fl, dl = VARIANTS[v]
        if dl is None:
            continue
        cl, fi, sk, pl = results[v]
        dpos = {p["fire_ts"]: p for p in cl if p["rule"] == "delayed"}
        rows = defaultdict(lambda: [0, 0.0, 0.0, 0])
        for x in pl:
            base = e25_by_ts.get(x["fire_ts"]); q = dpos.get(x["fire_ts"])
            key = x["outcome"]
            rows[key][0] += 1; rows[key][1] += base["pnl"] if base else 0.0; rows[key][2] += q["pnl"] if q else 0.0; rows[key][3] += (base is not None)
        dm = [p["delay_min"] for p in cl if p["rule"] == "delayed"]
        print(f"{v:>16s}: " + "; ".join(f"{k}: n {a} (e25 pos at fire {d}) e25 pnl {b:+.0f} → delayed pnl {c:+.0f}" for k, (a, b, c, d) in sorted(rows.items()))
              + (f"; fill delay min q25/50/75 {np.percentile(dm, 25):.1f}/{np.percentile(dm, 50):.1f}/{np.percentile(dm, 75):.1f}" if dm else ""))
    # ---- fire-level: which e25 fires each frozen veto removes
    print("\n--- fire-level vs e25: lost / new fires per frozen veto (pair 15<60 and ladder) ---")
    f25 = {(f["ts"], f["side"], f["tf"]): f for f in results["e25"][1]}
    for fam in FROZEN:
        for pk in ("15<60", "ladder"):
            v = f"{fam}|{pk}"; fv = {(f["ts"], f["side"], f["tf"]): f for f in results[v][1]}
            lost = [f25[k] for k in f25 if k not in fv]; new = [fv[k] for k in fv if k not in f25]
            print(f"{v:>16s}: e25 fires {len(f25)}, lost {len(lost)} (by tf {dict((tf, sum(f['tf'] == tf for f in lost)) for tf in TFS)}), new {len(new)}")
