#!/usr/bin/env python3
"""Replay: a HIGHER tf's PULL-BACK state vetoing the lower tf's in-trend CB zone entries.

Question (user, 2026-10-21): when the higher tf shows signals to reverse from the trend (or goes too deep) and moves
backward into range, discard the in-trend-direction zones on the lower timeframes — the higher-tf move will win.

Flow = 2026-10-21-higher-tf-trend-replay.py imported as a module (identical: fires re-derived on every trade, 1-min
class X 0.7, candle stop, cbnc target + trend-flip exit, reversal, paper = no fees). Only a veto per (tf, side) is
ANDed into the own forming EMA-25 flag (e25). Pull-back state PB_long of the higher tf H (short mirrored):

  xd     stored {H}_extdone_high == 1          (H's high is done: price pulled away >= d(progress) ATR; = AND {H}_cb_f_extdone_long)
  cf0    closed H class == +1 and forming class <= 0   (the slope just left the trend)       cf-  forming class == -1
  ovc    {H}_cb_f_overshoot_short was 0 earlier in the SAME forming H candle and passes now   ov30  within the last 30 min
  any    xd | cf0 | ovc            xdcf   xd & cf0
  mir    stored {H}_extdone_low == 1 (the opposite sign: veto long when H's LOW is done)      control
  sh+ / sh-   the xd state read 24 h earlier / later (pass-rate matched placebo)              control
pairs: 15<60, 15<240, 60<240, ladder (15: 60 & 240, 60: 240)

usage: python3 2026-10-21-higher-tf-pullback-replay.py <data_dir> <klines_dir> <stats.json> [--start=ISO] [--fee=0.001] [--only=a,b]
"""
import sys, os, json, importlib.util, datetime as dt
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("harness", os.path.join(HERE, "2026-10-21-higher-tf-trend-replay.py"))
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)

D = h.D; N = h.N; T_TS = h.T_TS; TFS = h.TFS; SIDES = h.SIDES; HIGHER = h.HIGHER; fmt_ts = h.fmt_ts
ONLY = h.arg("only", "")

# ---------------------------------------------------------------- extra stored indicators (same snapshot/expiry rule as the harness)
EXTRA = [f"{tf}_{n}" for tf in TFS for n in ("extdone_high", "extdone_low", "cb_f_extdone_long", "cb_f_extdone_short")]
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
print("\n=== STORED STATE GATE: extdone_high/low per trade in the window (mean), cb_f_extdone == NOT extdone (agreement) ===")
for tf in TFS:
    hi, lo = XI[f"{tf}_extdone_high"], XI[f"{tf}_extdone_low"]
    fl, fs = XI[f"{tf}_cb_f_extdone_long"], XI[f"{tf}_cb_f_extdone_short"]
    m = ~np.isnan(hi[I0:]) & ~np.isnan(fl[I0:])
    print(f"tf {tf:3d}: present {np.mean(~np.isnan(hi[I0:])):.3f} | extdone_high {np.nanmean(hi[I0:]):.3f} low {np.nanmean(lo[I0:]):.3f} | "
          f"f_long == !high {np.mean((fl[I0:][m] != 0) == (hi[I0:][m] == 0)):.4f}  f_short == !low {np.mean((fs[I0:][m] != 0) == (lo[I0:][m] == 0)):.4f}")


def d_of(s):
    return 1 if s == "Buy" else -1


# ---------------------------------------------------------------- pull-back states per H and side (True = PB on = veto)
def seg_cummax(active, seg_id):
    """cumulative OR of `active` within segments of equal seg_id (sorted)."""
    out = np.zeros(len(active), dtype=bool)
    starts = np.flatnonzero(np.r_[True, seg_id[1:] != seg_id[:-1]])
    ends = np.r_[starts[1:], len(active)]
    for a, b in zip(starts, ends):
        out[a:b] = np.maximum.accumulate(active[a:b])
    return out


def within_last(active, ms):
    """True where some `active` trade occurred within the last `ms` (strictly before or at t)."""
    last = np.where(active, T_TS, np.int64(-10 ** 15))
    last = np.maximum.accumulate(last)
    return (T_TS - last) <= ms


PB = {}   # (fam, H, side) -> bool array, True = veto that side's lower-tf fire
for H in TFS:
    cand_id = T_TS // (H * 60_000)
    for s in SIDES:
        d = d_of(s); ext_side = "high" if s == "Buy" else "low"; opp = "low" if s == "Buy" else "high"
        PB[("xd", H, s)] = XI[f"{H}_extdone_{ext_side}"] == 1
        PB[("mir", H, s)] = XI[f"{H}_extdone_{opp}"] == 1
        cf_ = h.CLS_C[(H, 25, 0.5)] == d
        PB[("cf0", H, s)] = cf_ & (h.CLS_F[(H, 25, 0.5)] != d)
        PB[("cf-", H, s)] = cf_ & (h.CLS_F[(H, 25, 0.5)] == -d)
        ov_name = f"{H}_cb_f_overshoot_{'short' if s == 'Buy' else 'long'}"   # price beyond H's bound in the trade's direction
        ov_active = h.IND[ov_name] == 0
        PB[("ovc", H, s)] = seg_cummax(ov_active, cand_id) & ~ov_active
        PB[("ov30", H, s)] = within_last(ov_active, 30 * 60_000) & ~ov_active
        PB[("any", H, s)] = PB[("xd", H, s)] | PB[("cf0", H, s)] | PB[("ovc", H, s)]
        PB[("xdcf", H, s)] = PB[("xd", H, s)] & PB[("cf0", H, s)]
        for lab, sh in (("sh+", 24 * 3600_000), ("sh-", -24 * 3600_000)):
            j = np.searchsorted(T_TS, T_TS - sh, "right") - 1
            okj = (j >= 0) & (j < N) & (np.abs(T_TS[np.clip(j, 0, N - 1)] - (T_TS - sh)) < 120_000)
            v = np.zeros(N, dtype=bool); v[okj] = PB[("xd", H, s)][np.clip(j, 0, N - 1)][okj]
            PB[(lab, H, s)] = v

FAMS = ("xd", "cf0", "cf-", "ovc", "ov30", "any", "xdcf", "mir", "sh+", "sh-")
print("\n=== PULL-BACK STATE RATES over the window's trades (share of trades with the veto on), per H and vetoed side ===")
print(f"{'fam':>5s} | " + " | ".join(f"{H:3d} {s[:1]}" for H in TFS for s in SIDES))
for fam in FAMS:
    print(f"{fam:>5s} | " + " | ".join(f"{PB[(fam, H, s)][I0:].mean():5.3f}" for H in TFS for s in SIDES))
print("overlap of the veto sets on the window's trades, tf-60 for long: static (class -1) vs xd / cf0 / ovc — Jaccard")
for H in (60, 240):
    for s in SIDES:
        st = h.CLS_F[(H, 25, 0.5)][I0:] == -d_of(s)
        for fam in ("xd", "cf0", "ovc", "any"):
            p = PB[(fam, H, s)][I0:]
            print(f"  H {H:3d} {s:4s} static {st.mean():.3f} {fam:4s} {p.mean():.3f} both {(st & p).mean():.3f} jaccard {(st & p).sum() / max(1, (st | p).sum()):.3f}")

# ---------------------------------------------------------------- variants
PAIRS = {"15<60": {15: (60,)}, "15<240": {15: (240,)}, "60<240": {60: (240,)}, "ladder": HIGHER}


def mk(fam, rule):
    out = {}
    for tf in TFS:
        for s in SIDES:
            f = h.F[tf][s].copy()
            for H in rule.get(tf, ()):
                f &= ~PB[(fam, H, s)]
            out[(tf, s)] = f
    return out


VARIANTS = {"live": h.VARIANTS["live"], "e25": h.VARIANTS["e25"], "none": h.VARIANTS["none"], "hx15<60": h.VARIANTS["hx15<60"]}
for fam in FAMS:
    for pk, rule in PAIRS.items():
        if fam in ("sh+", "sh-", "mir") and pk in ("15<240",):
            continue
        VARIANTS[f"{fam}{pk}"] = mk(fam, rule)
ORDER = [v for v in VARIANTS if not ONLY or v in ONLY.split(",") or v in ("live", "e25")]

results = {}
for v in ORDER:
    results[v] = h.simulate(VARIANTS[v], fee=h.FEE)
    print(f"simulated {v}: {len(results[v][0])} positions", flush=True)

# ---------------------------------------------------------------- reproduction gate (copied from the harness main)
rec = []
with open(f"{D}/events.jsonl") as f:
    for line in f:
        r = json.loads(line); e = r["ev"]
        rec.append(dict(ts=int(e["ts"]), side=e["side"], tf=int(e["tf_minutes"]), rule=e["rule"], cls=e["trend_class"]))
rec.sort(key=lambda e: e["ts"])
sim_after = [f for f in results["live"][1] if f["ts"] >= h.GATE_FROM]
by_ts = defaultdict(list)
for f in sim_after:
    by_ts[f["ts"]].append(f)
exact = near = 0; sim_ts = np.array([f["ts"] for f in sim_after])
for e in rec:
    if any(f["side"] == e["side"] and f["tf"] == e["tf"] for f in by_ts.get(e["ts"], [])):
        exact += 1; continue
    j = np.searchsorted(sim_ts, e["ts"])
    if any(abs(sim_after[k]["ts"] - e["ts"]) <= 120_000 and sim_after[k]["side"] == e["side"] and sim_after[k]["tf"] == e["tf"]
           for k in range(max(0, j - 3), min(len(sim_after), j + 3))):
        near += 1
print(f"\n=== REPRODUCTION GATE (live flags): recorded CbZoneEntry {len(rec)}, exact {exact}, within ±120 s {near}, unmatched {len(rec) - exact - near} ===")

# ---------------------------------------------------------------- tables
print(f"\n=== VARIANTS, window {fmt_ts(T_TS[I0])} -> {fmt_ts(T_TS[-1])}, paper (no fees); veto ANDed into e25, everything else live ===")
for v in ORDER:
    cl, fi, sk = results[v]
    print(h.row(v, h.stats(cl), f"| fires {len(fi)} ({'/'.join(str(sum(f['tf'] == tf for f in fi)) for tf in TFS)}) skip {sk}"))
print("\n--- by the opening fire's tf: n, net, PF ---")
for v in ORDER:
    print(f"{v:>9s} | {h.by_tf(results[v][0])}")
print("\n--- by side: n, net ---")
for v in ORDER:
    cl = results[v][0]
    print(f"{v:>9s} | " + " | ".join(f"{s}: {sum(p['side'] == s for p in cl)}, {sum(p['pnl'] for p in cl if p['side'] == s):+.0f}" for s in SIDES))

print("\n--- fees: net after f %/side ---")
for v in ORDER:
    cl = results[v][0]
    if not cl:
        continue
    turn = sum(p["size"] * (p["entry"] + p["exit"]) for p in cl); gross = sum(p["pnl"] for p in cl)
    print(f"{v:>9s} | gross {gross:+7.0f} | " + " | ".join(f"{f * 100:.2f}% {gross - f * turn:+7.0f}" for f in (0.0001, 0.0002, 0.0005)) + f" | breakeven {gross / turn * 100:.3f} %")

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
        print(f"{v:>9s} | shared {both:3d} | only-{v:>8s} {len(other) - both:3d} | only-{ref} {len(base) - both:3d} | Δnet {diffs.sum():+7.0f} | CI90 [{np.percentile(boot, 5):+6.0f}, {np.percentile(boot, 95):+6.0f}] | P(Δ<0) {np.mean(boot < 0):.2f}")

half = (T_TS[I0] + T_TS[-1]) // 2
days = sorted({int(p["open_ts"] // 86_400_000) for v in ORDER for p in results[v][0]})
print(f"\n--- stability: net by half (split {fmt_ts(half)}) and by UTC day ---")
print(f"{'variant':>9s} | {'H1':>7s} {'n':>3s} | {'H2':>7s} {'n':>3s} | " + " | ".join(f"{dt.datetime.fromtimestamp(d * 86400, dt.timezone.utc).strftime('%m-%d'):>6s} n" for d in days))
for v in ORDER:
    cl = results[v][0]
    h1 = [p for p in cl if p["open_ts"] < half]; h2 = [p for p in cl if p["open_ts"] >= half]
    per = [f"{sum(p['pnl'] for p in cl if int(p['open_ts'] // 86_400_000) == d):+6.0f} {sum(int(p['open_ts'] // 86_400_000) == d for p in cl):2d}" for d in days]
    print(f"{v:>9s} | {sum(p['pnl'] for p in h1):+7.0f} {len(h1):3d} | {sum(p['pnl'] for p in h2):+7.0f} {len(h2):3d} | " + " | ".join(per))

# ---------------------------------------------------------------- fire-level: what each variant removes / adds vs e25
print("\n--- fire-level vs e25: lost fires (veto True there), new fires; by tf ---")
f25 = {(f["ts"], f["side"], f["tf"]): f for f in results["e25"][1]}
for v in ORDER:
    if v in ("live", "e25"):
        continue
    fv = {(f["ts"], f["side"], f["tf"]): f for f in results[v][1]}
    lost = [f25[k] for k in f25 if k not in fv]; new = [fv[k] for k in fv if k not in f25]
    lost_flag = sum(not VARIANTS[v][(f["tf"], f["side"])][f["i"]] for f in lost)
    print(f"{v:>9s}: e25 fires {len(f25)}, shared {len(f25) - len(lost)}, lost {len(lost)} (veto at {lost_flag}), new {len(new)}; "
          f"lost by tf {dict((tf, sum(f['tf'] == tf for f in lost)) for tf in TFS)}, new by tf {dict((tf, sum(f['tf'] == tf for f in new)) for tf in TFS)}")

# ---------------------------------------------------------------- mechanism: e25 positions split by the PB state at the open
print("\n--- e25 POSITIONS by opening tf, split by the higher tf's pull-back state at the open (True = would be vetoed): n, net, PF, stop share, wr, mean ---")
for tf in (15, 60):
    for H in HIGHER[tf]:
        for fam in FAMS:
            for val in (True, False):
                c = [p for p in results["e25"][0] if p["tf"] == tf and bool(PB[(fam, H, p["side"])][p["open_i"]]) == val]
                if not c:
                    print(f"tf {tf:3d} by H {H:3d} {fam:4s} = {str(val):5s}: n 0"); continue
                pnl = np.array([p["pnl"] for p in c]); w = pnl[pnl > 0].sum(); l = abs(pnl[pnl < 0].sum())
                print(f"tf {tf:3d} by H {H:3d} {fam:4s} = {str(val):5s}: n {len(c):3d}, net {pnl.sum():+6.0f}, PF {w / l if l else float('inf'):4.2f}, "
                      f"stop {np.mean([p['reason'] == 'stop' for p in c]):.0%}, wr {np.mean(pnl > 0):.0%}, mean {pnl.mean():+5.0f}")
print("\n--- e25 tf-15 positions: cross-tab of the static tf-60 veto (class against) x xd / cf0 / ovc state at the open: n, net ---")
for H in (60, 240):
    for fam in ("xd", "cf0", "ovc", "any"):
        tab = defaultdict(lambda: [0, 0.0])
        for p in results["e25"][0]:
            if p["tf"] != 15:
                continue
            st = bool(h.CLS_F[(H, 25, 0.5)][p["open_i"]] == -d_of(p["side"])); pb = bool(PB[(fam, H, p["side"])][p["open_i"]])
            tab[(st, pb)][0] += 1; tab[(st, pb)][1] += p["pnl"]
        print(f"H {H:3d} {fam:4s}: " + "; ".join(f"static {st} PB {pb}: n {n} {net:+.0f}" for (st, pb), (n, net) in sorted(tab.items())))

# ---------------------------------------------------------------- the vetoed positions themselves: what happened after the open
print("\n--- e25 positions that xd15<60 / cf015<60 / ovc15<60 would veto: list (open, side, tf, reason, pnl, hold min) ---")
for fam in ("xd", "cf0", "ovc"):
    c = [p for p in results["e25"][0] if p["tf"] == 15 and PB[(fam, 60, p["side"])][p["open_i"]]]
    print(f"{fam}: n {len(c)} net {sum(p['pnl'] for p in c):+.0f}")
    for p in c:
        print(f"   {fmt_ts(p['open_ts'])} {p['side']:4s} {p['reason']:8s} {p['pnl']:+6.0f} hold {(p['close_ts'] - p['open_ts']) / 60000:5.1f} cls60 {int(h.CLS_F[(60, 25, 0.5)][p['open_i']]):+d}")
