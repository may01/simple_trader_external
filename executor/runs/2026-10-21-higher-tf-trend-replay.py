#!/usr/bin/env python3
"""Replay: a HIGHER tf's trend flag as a filter on a lower tf's CB zone entry.

Question (user, 2026-10-21): how does a higher trend impact the signal's P&L — e.g. the profit difference when the
15-min zones are filtered by the 60-min trend?

Flow = the trend-ma-length harness (CbZoneEntryCheck re-run on every recorded trade against the stored indicator
snapshots, 1-min trade-MA class at X = 0.7 for rule 1 / rule 2 and the trend-flip exit, orchestrator same-side skip /
reversal, candle stop, size min(100/dist, free*0.5/entry), paper = no fees). Only the trend FLAG per (tf, side) changes:

  live      stored {tf}_cb_f_trend_{side}                      e25   reconstructed forming EMA-25 flag (own tf)
  none      always pass
  hxA<B     own flag of tf A  AND  the forming EMA-25 flag of tf B (veto: pass unless B's class is against the trade)
  ladder    15: own & f60 & f240; 60: own & f240; 240: own     all<240  every tf: own & f240
  rpA=B     tf A uses tf B's flag INSTEAD of its own            rpall=240  every tf uses the 240 flag
  alA<B     own & tf B's class == direction (aligned)           alladder   aligned on every higher tf
  clA<B     own (forming) & tf B's CLOSED-candle class flag     clladder   closed higher flags, ladder
  nladder   no own flag; higher veto flags only                 livexA<B / livexladder  hx from the STORED flags (gate)

usage: python3 2026-10-21-higher-tf-trend-replay.py <data_dir> <klines_dir> <stats.json> [--start=ISO] [--fee=0.001]
"""
import json, sys, datetime as dt
from collections import defaultdict
import numpy as np, talib

D = sys.argv[1]; K = sys.argv[2]; STATS = json.load(open(sys.argv[3]))
RISK = 100.0; START_BAL = 100_000.0; MAX_NOTIONAL_FRAC = 0.5; PLACEHOLDER = 0.002
WINDOW_CAP = 6000; BUCKET = 10; MA_WIN = 6; STD_SPAN = 2 * 3600; MIN_BUCKETS = 30
MIN_INTERVAL_MS = 60_000; ANCHOR_MS = 15 * 60_000; RANGE_CANDLES = 60
TFS = (15, 60, 240); SIDES = ("Buy", "Sell"); LIVE_X = 0.7
NS = (7, 14, 25); W = 105; EMA_X = 0.5
IV = {15: "15m", 60: "1h", 240: "4h"}
FROZEN25 = {15: (0.0018696074433414492, 0.08854754765129406), 60: (0.007586181744923595, 0.17365581448454287),
            240: (0.03083283482398462, 0.3443346525283253)}


def arg(name, default):
    return next((a.split("=", 1)[1] for a in sys.argv if a.startswith(f"--{name}=")), default)


START = arg("start", "2026-10-17T22:00:00Z")
START_MS = int(dt.datetime.fromisoformat(START.replace("Z", "+00:00")).timestamp() * 1000)
FEE = float(arg("fee", "0.001"))
GATE_FROM = int(dt.datetime(2026, 10, 18, 11, 41, tzinfo=dt.timezone.utc).timestamp() * 1000)


def fmt_ts(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%m-%d %H:%M:%S")


# ---------------------------------------------------------------- trades
tr = np.loadtxt(f"{D}/trades.csv", delimiter=",", usecols=(0, 1), dtype=np.float64)
T_TS = tr[:, 0].astype(np.int64); T_PX = tr[:, 1]
N = len(T_TS)
print(f"trades {N}  {fmt_ts(T_TS[0])} -> {fmt_ts(T_TS[-1])}")
gaps = np.diff(T_TS); big = np.where(gaps > 60_000)[0]
print(f"trade feed gaps > 60 s: {len(big)}", [(fmt_ts(T_TS[i]), int(gaps[i] // 1000)) for i in big])

# ---------------------------------------------------------------- indicators: value at each trade, expiry applied
NAMES = [f"{tf}_{n}" for tf in TFS for n in ("cb_zone_long", "cb_zone_short", "cb_inzone_long", "cb_inzone_short",
                                            "cb_f_overshoot_long", "cb_f_overshoot_short", "cb_f_trend_long",
                                            "cb_f_trend_short", "cbnc_high", "cbnc_low")]
rows = defaultdict(list)
with open(f"{D}/indicators.csv") as f:
    for line in f:
        recv, exp, name, val = line.rstrip("\n").split(",")
        if name in NAMES:
            rows[name].append((int(recv), int(exp), float(val)))
IND = {}
for name in NAMES:
    r = sorted(rows[name])
    recv = np.array([x[0] for x in r], dtype=np.int64); exp = np.array([x[1] for x in r], dtype=np.int64)
    val = np.array([x[2] for x in r])
    idx = np.searchsorted(recv, T_TS, "right") - 1
    v = np.full(N, np.nan); ok = idx >= 0
    ok[ok] &= T_TS[ok] < exp[idx[ok]]
    v[ok] = val[idx[ok]]
    IND[name] = v

# ---------------------------------------------------------------- EMA_N slope classes per trade, from the klines
def load_k(iv):
    a = np.loadtxt(f"{K}/klines_{iv}.csv", delimiter=",", usecols=(0, 4, 6))
    return a[:, 0].astype(np.int64), a[:, 1], a[:, 2].astype(np.int64)


CLS_F = {}; CLS_C = {}   # (tf, N, X) -> per-trade class (int8)
for tf in TFS:
    o, c, ct = load_k(IV[tf])
    closed = ct < T_TS[-1] - 60_000 * tf           # fully closed inside the data
    o, c = o[closed], c[closed]
    n = len(c)
    cid = np.searchsorted(o, T_TS, "right") - 1     # the trade's forming candle
    prev_i = cid - 1
    for Nn in NS:
        ema = np.full(n, np.nan)
        for j in range(n):
            lo = max(0, j - W + 1)
            if j - lo + 1 >= Nn:
                ema[j] = talib.EMA(c[lo:j + 1], timeperiod=Nn)[-1]
        a = 2.0 / (Nn + 1)
        prev = np.where(prev_i >= 0, ema[np.maximum(prev_i, 0)], np.nan)
        diff_f = (a * T_PX + (1 - a) * prev - prev) / prev * 100.0
        dcl = np.full(n, np.nan); dcl[1:] = (ema[1:] - ema[:-1]) / ema[:-1] * 100.0
        diff_c = np.where(prev_i >= 0, dcl[np.maximum(prev_i, 0)], np.nan)
        mu, sd = FROZEN25[tf] if Nn == 25 else (STATS[f"{tf}_{Nn}"]["mean"], STATS[f"{tf}_{Nn}"]["std"])
        for X in (0.01, 0.5, 1.0):
            for d, store in ((diff_f, CLS_F), (diff_c, CLS_C)):
                cl = np.where(d < mu - X * sd, -1, np.where(d > mu + X * sd, 1, 0)).astype(np.int8)
                cl[~np.isfinite(d)] = 0
                store[(tf, Nn, X)] = cl
    print(f"tf {tf:3d}: {n} closed klines {fmt_ts(o[0])} -> {fmt_ts(o[-1])}; stats " +
          ", ".join(f"N{Nn} {FROZEN25[tf][0] if Nn == 25 else STATS[f'{tf}_{Nn}']['mean']:+.5f}/{FROZEN25[tf][1] if Nn == 25 else STATS[f'{tf}_{Nn}']['std']:.5f}" for Nn in NS))


def flag_from_cls(cl, side):
    return cl != (-1 if side == "Buy" else 1)


# variant -> {(tf, side): pass array}
def d_of(s):
    return 1 if s == "Buy" else -1


F = {tf: {s: flag_from_cls(CLS_F[(tf, 25, 0.5)], s) for s in SIDES} for tf in TFS}          # forming veto flag
A = {tf: {s: CLS_F[(tf, 25, 0.5)] == d_of(s) for s in SIDES} for tf in TFS}                 # forming aligned
C = {tf: {s: flag_from_cls(CLS_C[(tf, 25, 0.5)], s) for s in SIDES} for tf in TFS}          # closed veto flag
L = {tf: {s: IND[f"{tf}_cb_f_trend_{'long' if s == 'Buy' else 'short'}"] != 0 for s in SIDES} for tf in TFS}  # stored
ONE = np.ones(N, dtype=bool)
HIGHER = {15: (60, 240), 60: (240,), 240: ()}


def mk(own, hi, rule):
    """own: dict tf->{side->flag} or None; hi: dict tf->{side->flag}; rule: tf -> tuple of higher tfs to AND in"""
    out = {}
    for tf in TFS:
        for s in SIDES:
            f = (own[tf][s] if own is not None else ONE).copy()
            for h in rule.get(tf, ()):
                f &= hi[h][s]
            out[(tf, s)] = f
    return out


VARIANTS = {}
VARIANTS["live"] = mk(L, L, {})
VARIANTS["e25"] = mk(F, F, {})
VARIANTS["none"] = mk(None, F, {})
VARIANTS["hx15<60"] = mk(F, F, {15: (60,)})
VARIANTS["hx15<240"] = mk(F, F, {15: (240,)})
VARIANTS["hx60<240"] = mk(F, F, {60: (240,)})
VARIANTS["ladder"] = mk(F, F, HIGHER)
VARIANTS["all<240"] = mk(F, F, {15: (240,), 60: (240,)})
VARIANTS["rp15=60"] = mk(None, F, {15: (60,), 60: (60,), 240: (240,)})
VARIANTS["rp15=240"] = mk(None, F, {15: (240,), 60: (60,), 240: (240,)})
VARIANTS["rp60=240"] = mk(None, F, {15: (15,), 60: (240,), 240: (240,)})
VARIANTS["rpall=240"] = mk(None, F, {15: (240,), 60: (240,), 240: (240,)})
VARIANTS["al15<60"] = mk(F, A, {15: (60,)})
VARIANTS["al15<240"] = mk(F, A, {15: (240,)})
VARIANTS["al60<240"] = mk(F, A, {60: (240,)})
VARIANTS["alladder"] = mk(F, A, HIGHER)
VARIANTS["cl15<60"] = mk(F, C, {15: (60,)})
VARIANTS["clladder"] = mk(F, C, HIGHER)
VARIANTS["nladder"] = mk(None, F, HIGHER)
VARIANTS["n15<60"] = mk(None, F, {15: (60,)})
VARIANTS["livex15<60"] = mk(L, L, {15: (60,)})
VARIANTS["livexladder"] = mk(L, L, HIGHER)
ORDER = list(VARIANTS)

# ---------------------------------------------------------------- flag reconstruction gate: e25 vs the stored flag at every trade
print("\n=== FLAG GATE: reconstructed forming EMA-25 flag vs the stored cb_f_trend at every trade (stored present) ===")
for tf in TFS:
    for s in SIDES:
        suf = "long" if s == "Buy" else "short"
        st = IND[f"{tf}_cb_f_trend_{suf}"]; has = ~np.isnan(st)
        mine = VARIANTS["e25"][(tf, s)]
        agree = np.mean(mine[has] == (st[has] != 0))
        print(f"tf {tf:3d} {suf:5s}: stored present {has.mean():.1%}, pass stored {np.mean(st[has] != 0):.3f} e25 {mine[has].mean():.3f} "
              f"| agreement e25 vs stored {agree:.4f}")

# ---------------------------------------------------------------- trend (port of signals::trend), per trade
def trend_all():
    slope = np.full(N, np.nan); sigma = np.full(N, np.nan)
    for i in range(N):
        lo = max(0, i - WINDOW_CAP + 1)
        ts = T_TS[lo:i + 1] // 1000; px = T_PX[lo:i + 1]
        sec = (ts // BUCKET) * BUCKET
        first, last = int(sec[0]), int(sec[-1])
        n = (last - first) // BUCKET + 1
        if n < MIN_BUCKETS:
            continue
        idx = (sec - first) // BUCKET
        sums = np.bincount(idx, weights=px, minlength=n); cnt = np.bincount(idx, minlength=n)
        has = cnt > 0
        fill = np.maximum.accumulate(np.where(has, np.arange(n), 0))
        prices = (sums / np.where(has, cnt, 1))[fill]
        cs = np.cumsum(prices)
        ma = cs / np.arange(1, n + 1)
        if n > MA_WIN:
            ma[MA_WIN:] = (cs[MA_WIN:] - cs[:-MA_WIN]) / MA_WIN
        sl = np.diff(ma)
        times = first + BUCKET * np.arange(1, n)
        in_span = sl[times >= int(ts[-1]) - STD_SPAN]
        sg = float(np.sqrt(np.mean((in_span - in_span.mean()) ** 2))) if len(in_span) >= 2 else 0.0
        slope[i] = sl[-1]; sigma[i] = sg
    return slope, sigma


try:
    z = np.load(f"{D}/trend_cache.npz")
    assert len(z["slope"]) == N
    SLOPE, SIGMA = z["slope"], z["sigma"]
    print("trend cache loaded")
except Exception:
    import time
    t0 = time.time()
    SLOPE, SIGMA = trend_all()
    np.savez(f"{D}/trend_cache.npz", slope=SLOPE, sigma=SIGMA)
    print(f"trend computed in {time.time() - t0:.0f} s")
HAS_TREND = ~np.isnan(SLOPE)
C07 = np.zeros(N, dtype=np.int8)
band = LIVE_X * SIGMA
C07[HAS_TREND & (band > 0) & (SLOPE > band)] = 1; C07[HAS_TREND & (band > 0) & (SLOPE < -band)] = -1

# ---------------------------------------------------------------- 1-min bars from the trades
T_MIN = T_TS // 60_000
MIN_KEYS, first_idx = np.unique(T_MIN, return_index=True)
last_idx = np.r_[first_idx[1:], N] - 1
M_LOW = np.minimum.reduceat(T_PX, first_idx); M_HIGH = np.maximum.reduceat(T_PX, first_idx); M_CLOSE = T_PX[last_idx]
M_CUM = np.r_[0.0, np.cumsum(M_HIGH - M_LOW)]


def mean_range(ts):
    hi = int(np.searchsorted(MIN_KEYS, ts // 60_000, "left")); lo = max(0, hi - RANGE_CANDLES)
    return None if hi <= lo else (M_CUM[hi] - M_CUM[lo]) / (hi - lo)


def candle_stop(side, i):
    ts = int(T_TS[i]); price = T_PX[i]
    start = (ts // ANCHOR_MS) * ANCHOR_MS
    lo = int(np.searchsorted(T_TS, start, "left"))
    seg = T_PX[lo:i + 1]
    anchor = float(seg.min()) if side == "Buy" else float(seg.max())
    off = mean_range(ts)
    if off is None:
        return None, anchor, None
    stop = anchor - off if side == "Buy" else anchor + off
    if (side == "Buy" and stop >= price) or (side == "Sell" and stop <= price):
        return None, anchor, off
    return stop, anchor, off


# ---------------------------------------------------------------- flag-independent candidate material
I_START = int(np.searchsorted(T_TS, START_MS, "left"))
OV_OK = {}; ZONE = {}; INZONE = {}; TARGET = {}; REJ = {}
PREV = np.full((N, 3), np.nan)
pm = T_MIN - 1; pos_ = np.searchsorted(MIN_KEYS, pm); posc = np.minimum(pos_, len(MIN_KEYS) - 1); hit = MIN_KEYS[posc] == pm
PREV[hit, 0] = M_LOW[posc[hit]]; PREV[hit, 1] = M_HIGH[posc[hit]]; PREV[hit, 2] = M_CLOSE[posc[hit]]
for tf in TFS:
    for s in SIDES:
        suf = "long" if s == "Buy" else "short"
        OV_OK[(tf, s)] = ~(IND[f"{tf}_cb_f_overshoot_{suf}"] == 0)
        ZONE[(tf, s)] = IND[f"{tf}_cb_zone_{suf}"]; INZONE[(tf, s)] = IND[f"{tf}_cb_inzone_{suf}"] == 1
        TARGET[(tf, s)] = IND[f"{tf}_cbnc_high" if s == "Buy" else f"{tf}_cbnc_low"]
        z = ZONE[(tf, s)]
        REJ[(tf, s)] = hit & ((PREV[:, 0] <= z) & (PREV[:, 2] > z) if s == "Buy" else (PREV[:, 1] >= z) & (PREV[:, 2] < z))
GEO_OK = {k: OV_OK[k] & ~np.isnan(ZONE[k]) & ~np.isnan(TARGET[k]) for k in OV_OK}
# a trade where some (tf, side) could fire under SOME flag source (rule 1 or 2 by the 1-min class)
POSSIBLE_ANY = np.zeros(N, dtype=bool)
for k in GEO_OK:
    d = 1 if k[1] == "Buy" else -1
    POSSIBLE_ANY |= GEO_OK[k] & ((INZONE[k] & (C07 == d)) | (REJ[k] & ((C07 == 0) | (C07 == d))))
POSSIBLE_ANY &= HAS_TREND; POSSIBLE_ANY[:I_START] = False
POSS_IDX = np.where(POSSIBLE_ANY)[0]
print(f"\ntrades from {fmt_ts(T_TS[I_START])}: {N - I_START}; trades where some (tf, side) passes geometry + 1-min class: {len(POSS_IDX)}")


# ---------------------------------------------------------------- the check + the flow
def simulate(flags, fee=0.0):
    base_ok = {k: GEO_OK[k] & flags[k] for k in GEO_OK}
    bal = START_BAL; pos = None; closed = []; fires = []; fired = {}; last_fired = None; skipped_same = 0
    poss = POSS_IDX; p = 0; np_ = len(poss)
    i = I_START
    # event loop: jump between candidate trades while flat; while in a position walk every trade (stop/advisor)
    while i < N:
        if pos is None:
            while p < np_ and poss[p] < i:
                p += 1
            if p >= np_:
                break
            i = int(poss[p])
        ts = int(T_TS[i]); px = T_PX[i]
        if POSSIBLE_ANY[i]:
            cls = int(C07[i]); cands = []
            for tf in TFS:
                for s in SIDES:
                    k = (tf, s)
                    if not base_ok[k][i]:
                        continue
                    d = 1 if s == "Buy" else -1
                    r1 = INZONE[k][i] and cls == d
                    r2 = REJ[k][i] and (cls == 0 or cls == d)
                    if r1 or r2:
                        cands.append((tf, s, ZONE[k][i], "in_zone" if r1 else "zone_rejection", TARGET[k][i]))
            if cands:
                cands = [c for c in cands if fired.get((c[0], c[1])) != c[2]]
                sides = {c[1] for c in cands}
                if cands and len(sides) == 1 and not (last_fired is not None and ts - last_fired < MIN_INTERVAL_MS):
                    best = max(cands, key=lambda c: c[0])
                    for c in cands:
                        fired[(c[0], c[1])] = c[2]
                    last_fired = ts
                    ev = dict(i=i, ts=ts, side=best[1], tf=best[0], zone=best[2], rule=best[3], target=best[4], price=px, cls=cls,
                              slope=float(SLOPE[i]))
                    fires.append(ev)
                    if pos is not None and pos["side"] == ev["side"]:
                        skipped_same += 1
                    else:
                        if pos is not None:
                            close_pos(pos, px, ts, "reversal", closed, fee); bal += closed[-1]["pnl"]; pos = None
                        stop, anchor, off = candle_stop(ev["side"], i); kind = "candle"
                        if stop is None:
                            stop = px * (1 - PLACEHOLDER) if ev["side"] == "Buy" else px * (1 + PLACEHOLDER); kind = "placeholder"
                        dist = abs(px - stop); size = min(RISK / dist, bal * MAX_NOTIONAL_FRAC / px)
                        pos = dict(side=ev["side"], entry=px, stop=stop, stop_kind=kind, target=ev["target"], size=size, open_ts=ts,
                                   open_i=i, extreme=None, tf=ev["tf"], rule=ev["rule"], dist=dist, armed=False, cls_open=cls)
                        i += 1
                        continue
        if pos is None:
            i += 1
            continue
        if (pos["side"] == "Buy" and px <= pos["stop"]) or (pos["side"] == "Sell" and px >= pos["stop"]):
            close_pos(pos, px, ts, "stop", closed, fee); bal += closed[-1]["pnl"]; pos = None; i += 1
            continue
        if pos["extreme"] is None:
            pos["extreme"] = px
        elif pos["side"] == "Buy":
            pos["extreme"] = max(pos["extreme"], px)
        else:
            pos["extreme"] = min(pos["extreme"], px)
        pos["armed"] = pos["extreme"] > pos["target"] if pos["side"] == "Buy" else pos["extreme"] < pos["target"]
        if pos["armed"]:
            co = int(C07[i])
            if (pos["side"] == "Buy" and co == -1) or (pos["side"] == "Sell" and co == 1):
                close_pos(pos, px, ts, "target", closed, fee); bal += closed[-1]["pnl"]; pos = None
        i += 1
    if pos is not None:
        close_pos(pos, float(T_PX[-1]), int(T_TS[-1]), "open_at_end", closed, fee)
    return closed, fires, skipped_same


def close_pos(pos, price, ts, reason, closed, fee):
    sgn = 1 if pos["side"] == "Buy" else -1
    gross = (price - pos["entry"]) * pos["size"] * sgn
    fees = fee * pos["size"] * (pos["entry"] + price)
    pos.update(exit=price, close_ts=ts, reason=reason, pnl=gross, fees=fees, pnl_net=gross - fees)
    closed.append(pos)


# ---------------------------------------------------------------- stats
def stats(closed, key="pnl"):
    pnl = np.array([p[key] for p in closed]) if closed else np.zeros(0)
    if len(pnl) == 0:
        return dict(n=0, net=0.0, pf=float("nan"), wr=float("nan"), ci=(0.0, 0.0), pneg=float("nan"), top2=0.0, by={},
                    hold=float("nan"), risk=float("nan"), R=0.0)
    wins = pnl[pnl > 0]; losses = pnl[pnl < 0]
    by = defaultdict(lambda: [0, 0.0])
    for p, v in zip(closed, pnl):
        by[p["reason"]][0] += 1; by[p["reason"]][1] += v
    hold = np.array([(p["close_ts"] - p["open_ts"]) / 60000 for p in closed]); risk = np.array([p["size"] * p["dist"] for p in closed])
    rng = np.random.default_rng(0)
    boot = np.array([rng.choice(pnl, len(pnl), replace=True).sum() for _ in range(4000)])
    return dict(n=len(pnl), net=float(pnl.sum()), pf=float(wins.sum() / abs(losses.sum())) if len(losses) else float("inf"),
                wr=len(wins) / len(pnl), ci=(float(np.percentile(boot, 5)), float(np.percentile(boot, 95))), pneg=float(np.mean(boot < 0)),
                top2=float(np.sort(pnl)[::-1][:2].sum()), by=dict(by), hold=float(np.median(hold)), risk=float(np.median(risk)),
                R=float((pnl / risk).sum()))


def row(label, st, extra=""):
    by = st["by"]
    b = " ".join(f"{k[:4]}={by[k][0]}/{by[k][1]:+.0f}" for k in ("stop", "target", "reversal", "open_at_end") if k in by)
    return (f"{label:>9s} | n {st['n']:3d} | net {st['net']:+7.0f} | PF {st['pf']:5.2f} | wr {st['wr']:4.0%} | R {st['R']:+6.1f} | hold {st['hold']:5.1f}m "
            f"| risk {st['risk']:4.0f} | CI90 [{st['ci'][0]:+6.0f},{st['ci'][1]:+6.0f}] P<0 {st['pneg']:.2f} | top2 {st['top2']:+5.0f} | {b} {extra}")


def by_tf(cl):
    out = []
    for tf in TFS:
        c = [p for p in cl if p["tf"] == tf]
        pnl = np.array([p["pnl"] for p in c]); w = pnl[pnl > 0].sum(); l = abs(pnl[pnl < 0].sum())
        out.append(f"tf{tf}: {len(c)}, {pnl.sum():+.0f}, PF {w / l if l else float('inf'):.2f}")
    return " | ".join(out)


if __name__ == "__main__":
    results = {}
    for v in ORDER:
        results[v] = simulate(VARIANTS[v], fee=FEE)

    # ---- reproduction gate: live-flag sim fires vs the recorded CbZoneEntry rows
    rec = []
    with open(f"{D}/events.jsonl") as f:
        for line in f:
            r = json.loads(line); e = r["ev"]
            rec.append(dict(ts=int(e["ts"]), side=e["side"], tf=int(e["tf_minutes"]), rule=e["rule"], cls=e["trend_class"],
                            slope=float(e["ma_slope"]), zone=float(e["zone"])))
    rec.sort(key=lambda e: e["ts"])
    fires_live = results["live"][1]
    sim_after = [f for f in fires_live if f["ts"] >= GATE_FROM]
    by_ts = defaultdict(list)
    for f in sim_after:
        by_ts[f["ts"]].append(f)
    exact = near = cls_ok = rule_ok = 0; unmatched = []; sim_ts = np.array([f["ts"] for f in sim_after])
    for e in rec:
        m = [f for f in by_ts.get(e["ts"], []) if f["side"] == e["side"] and f["tf"] == e["tf"]]
        if m:
            exact += 1; cls_ok += ({1: "up", -1: "down", 0: "neutral"}[m[0]["cls"]] == e["cls"]); rule_ok += (m[0]["rule"] == e["rule"]); continue
        j = np.searchsorted(sim_ts, e["ts"])
        if any(abs(sim_after[k]["ts"] - e["ts"]) <= 120_000 and sim_after[k]["side"] == e["side"] and sim_after[k]["tf"] == e["tf"]
               for k in range(max(0, j - 3), min(len(sim_after), j + 3))):
            near += 1
        else:
            unmatched.append(e)
    print("\n=== REPRODUCTION GATE (live flags, X = 0.7) ===")
    print(f"recorded CbZoneEntry fires: {len(rec)} ({fmt_ts(rec[0]['ts'])} -> {fmt_ts(rec[-1]['ts'])}); sim fires in the span: {len(sim_after)}")
    print(f"  exact (same ms, side, tf): {exact}/{len(rec)}; within ±120 s: {near}; unmatched: {len(unmatched)}; class agrees {cls_ok}/{exact}, rule agrees {rule_ok}/{exact}")
    for e in unmatched[:15]:
        print(f"    unmatched recorded: {fmt_ts(e['ts'])} {e['side']:4s} tf {e['tf']:3d} {e['rule']:14s} {e['cls']}")

    # ---- main table
    print(f"\n=== VARIANTS, window {fmt_ts(T_TS[I_START])} -> {fmt_ts(T_TS[-1])}, paper (no fees); flag source changes, everything else live ===")
    for v in ORDER:
        cl, fi, sk = results[v]
        print(row(v, stats(cl), f"| fires {len(fi)} ({'/'.join(str(sum(f['tf'] == tf for f in fi)) for tf in TFS)}) skip {sk} | r1 {sum(f['rule'] == 'in_zone' for f in fi)} r2 {sum(f['rule'] == 'zone_rejection' for f in fi)}"))
    print("\n--- by the opening fire's tf: n, net, PF ---")
    for v in ORDER:
        print(f"{v:>9s} | {by_tf(results[v][0])}")
    print("\n--- by side: n, net ---")
    for v in ORDER:
        cl = results[v][0]
        print(f"{v:>9s} | " + " | ".join(f"{s}: {sum(p['side'] == s for p in cl)}, {sum(p['pnl'] for p in cl if p['side'] == s):+.0f}" for s in SIDES)
              + " | " + " | ".join(f"{r[:3]}: {sum(p['rule'] == r for p in cl)}, {sum(p['pnl'] for p in cl if p['rule'] == r):+.0f}" for r in ("in_zone", "zone_rejection")))

    # ---- fees
    print("\n--- fees: net after f %/side; bp = gross per trade in bp of median notional ---")
    print(f"{'variant':>9s} | {'gross':>7s} | {'notional':>8s} | {'bp/trade':>8s} | {'0.01%':>7s} | {'0.02%':>7s} | {'0.05%':>7s} | {'0.10%':>7s} | breakeven")
    for v in ORDER:
        cl = results[v][0]
        if not cl:
            continue
        turn = sum(p["size"] * (p["entry"] + p["exit"]) for p in cl); gross = sum(p["pnl"] for p in cl)
        notional = np.median([p["size"] * p["entry"] for p in cl]); bp = gross / len(cl) / notional * 1e4
        print(f"{v:>9s} | {gross:+7.0f} | {notional:8.0f} | {bp:+8.1f} | " + " | ".join(f"{gross - f * turn:+7.0f}" for f in (0.0001, 0.0002, 0.0005, 0.001)) + f" | {gross / turn * 100:.3f} %")

    # ---- paired vs e25 (same construction) and vs live
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
            print(f"{v:>9s} | shared {both:3d} | only-{v:>7s} {len(other) - both:3d} | only-{ref} {len(base) - both:3d} | Δnet {diffs.sum():+7.0f} | CI90 [{np.percentile(boot, 5):+6.0f}, {np.percentile(boot, 95):+6.0f}] | P(Δ<0) {np.mean(boot < 0):.2f}")

    # ---- stability
    half = (T_TS[I_START] + T_TS[-1]) // 2
    days = sorted({int(p["open_ts"] // 86_400_000) for v in ORDER for p in results[v][0]})
    print(f"\n--- stability: net by half (split {fmt_ts(half)}) and by UTC day, no fees ---")
    print(f"{'variant':>9s} | {'H1':>7s} {'n':>3s} | {'H2':>7s} {'n':>3s} | " + " | ".join(f"{dt.datetime.fromtimestamp(d * 86400, dt.timezone.utc).strftime('%m-%d'):>6s} n" for d in days))
    for v in ORDER:
        cl = results[v][0]
        h1 = [p for p in cl if p["open_ts"] < half]; h2 = [p for p in cl if p["open_ts"] >= half]
        per = [f"{sum(p['pnl'] for p in cl if int(p['open_ts'] // 86_400_000) == d):+6.0f} {sum(int(p['open_ts'] // 86_400_000) == d for p in cl):2d}" for d in days]
        print(f"{v:>9s} | {sum(p['pnl'] for p in h1):+7.0f} {len(h1):3d} | {sum(p['pnl'] for p in h2):+7.0f} {len(h2):3d} | " + " | ".join(per))

    # ---- where the fires differ: e25 fires vetoed by eN (flag False at that trade) and eN fires that e25 vetoed
    print("\n--- fire-level mechanism vs e25: fires of e25 absent in the variant because its flag was False there, and the variant's own new fires ---")
    f25 = {(f["ts"], f["side"], f["tf"]): f for f in results["e25"][1]}
    for v in [x for x in ORDER if x not in ("live", "e25")]:
        fv = {(f["ts"], f["side"], f["tf"]): f for f in results[v][1]}
        lost = [f25[k] for k in f25 if k not in fv]; new = [fv[k] for k in fv if k not in f25]
        lost_flag = sum(not VARIANTS[v][(f["tf"], f["side"])][f["i"]] for f in lost)
        new_flag = sum(not VARIANTS["e25"][(f["tf"], f["side"])][f["i"]] for f in new)
        print(f"{v:>5s}: e25 fires {len(f25)}, shared {len(f25) - len(lost)}, lost {len(lost)} (flag False in {v} at {lost_flag}), new {len(new)} (flag False in e25 at {new_flag}); "
              f"lost by tf {dict((tf, sum(f['tf'] == tf for f in lost)) for tf in TFS)}, new by tf {dict((tf, sum(f['tf'] == tf for f in new)) for tf in TFS)}")

    # ---- position-level transitions e25 -> variant (same side, opened within -5..+40 min)
    print("\n--- positions of e25 -> their counterpart in the variant (same side, opened −5…+40 min): Δ pnl by outcome ---")
    for v in ("hx15<60", "ladder", "al15<60", "rp15=60", "none", "nladder"):
        other = results[v][0]; o_ts = np.array([p["open_ts"] for p in other])
        tab = defaultdict(lambda: [0, 0.0, 0.0]); used = set()
        for p in results["e25"][0]:
            j = None
            for k in np.where((o_ts >= p["open_ts"] - 5 * 60_000) & (o_ts <= p["open_ts"] + 40 * 60_000))[0]:
                if other[k]["side"] == p["side"] and k not in used:
                    j = int(k); break
            if j is None:
                key = (p["tf"], "not opened"); tab[key][0] += 1; tab[key][1] += p["pnl"]
            else:
                used.add(j); q = other[j]; key = (p["tf"], f"-> tf{q['tf']} {'same' if q['open_ts'] == p['open_ts'] else 'later' if q['open_ts'] > p['open_ts'] else 'earlier'}")
                tab[key][0] += 1; tab[key][1] += p["pnl"]; tab[key][2] += q["pnl"]
        extra = [other[k] for k in range(len(other)) if k not in used]
        print(f"{v}: " + "; ".join(f"tf{tf} {what}: n {n} {a:+.0f} -> {b:+.0f} (Δ {b - a:+.0f})" for (tf, what), (n, a, b) in sorted(tab.items()))
              + f"; variant-only positions {len(extra)}: {sum(p['pnl'] for p in extra):+.0f}")

    # ---- higher-tf class at the e25 fires (per fire's tf), and outcome of e25 positions split by the higher flag
    print("\n--- e25 fires: forming EMA-25 class of each tf at the fire (long: -1 = would be vetoed, +1 = aligned; short mirrored) ---")
    for tf in TFS:
        for h in TFS:
            cnt = defaultdict(int)
            for f in results["e25"][1]:
                if f["tf"] == tf:
                    cnt[(f["side"], int(CLS_F[(h, 25, 0.5)][f["i"]]))] += 1
            print(f"fire tf {tf:3d}, class of tf {h:3d}: " + ", ".join(f"{s} {c:+d}: {cnt[(s, c)]:3d}" for s in SIDES for c in (-1, 0, 1)))
    print("\n--- e25 POSITIONS by opening tf, split by the higher tf's flag / alignment at the open: n, net, PF, stop share ---")
    for tf in (15, 60):
        for h in HIGHER[tf]:
            for lab, arr in (("veto pass", F[h]), ("aligned", A[h])):
                for val in (True, False):
                    c = [p for p in results["e25"][0] if p["tf"] == tf and bool(arr[p["side"]][p["open_i"]]) == val]
                    if not c:
                        print(f"tf {tf:3d} by tf {h:3d} {lab:9s} = {str(val):5s}: n 0"); continue
                    pnl = np.array([p["pnl"] for p in c]); w = pnl[pnl > 0].sum(); l = abs(pnl[pnl < 0].sum())
                    print(f"tf {tf:3d} by tf {h:3d} {lab:9s} = {str(val):5s}: n {len(c):3d}, net {pnl.sum():+6.0f}, PF {w / l if l else float('inf'):4.2f}, "
                          f"stop {np.mean([p['reason'] == 'stop' for p in c]):.0%}, wr {np.mean(pnl > 0):.0%}, mean {pnl.mean():+5.0f}")
