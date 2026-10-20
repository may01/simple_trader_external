#!/usr/bin/env python3
"""Sweep X in "1-min trade-MA slope outside ±X·σ is a trend" through the paper executor's flow.

X = `signals::trend::TrendParams::std_mult` (0.7 live, same number in static/js/trades_ma.js). The class
gates the CB zone open (rule 1: in zone ∧ class = direction; rule 2: previous 1-min candle rejected at
the zone ∧ class ∈ {neutral, direction}) and the trend-flip exit (extreme past the frozen cbnc target ∧
class opposite to the side).

Unlike the sl-15m-anchor / cross-tf-veto replays, the fires are NOT taken from signal_log: the check
(checks/cb_zone_entry.rs) is re-run on every recorded trade against the indicator snapshots the executor
stored, so a different X produces a different fire stream. Everything else is the live flow: orchestrator
same-side skip / opposite-side reversal, candle stop (forming-15m extreme ∓ trailing-60 mean 1-min range,
0.2 % placeholder) for every X, sizing min(RISK/dist, free·0.5/entry), stop trips on the crossing trade,
paper = no fees (a 0.1 %/side sensitivity is reported).

(slope, σ) per trade is X-independent and cached in <data>/trend_cache.npz; the sweep re-runs only the
simulation.

usage: python3 2026-10-20-trend-x-sweep-replay.py <data_dir> [--start=ISO] [--fee=0.001] [--xs=0.3,0.5,...]
"""
import json, sys, datetime as dt
from collections import defaultdict
import numpy as np

D = sys.argv[1] if len(sys.argv) > 1 else "data"
RISK = 100.0
START_BAL = 100_000.0
MAX_NOTIONAL_FRAC = 0.5
PLACEHOLDER = 0.002
WINDOW_CAP = 6000; BUCKET = 10; MA_WIN = 6; STD_SPAN = 2 * 3600; MIN_BUCKETS = 30
MIN_INTERVAL_MS = 60_000
ANCHOR_MS = 15 * 60_000
RANGE_CANDLES = 60
TFS = (15, 60, 240)
SIDES = ("Buy", "Sell")
LIVE_X = 0.7


def arg(name, default):
    return next((a.split("=", 1)[1] for a in sys.argv if a.startswith(f"--{name}=")), default)


START = arg("start", "2026-10-17T22:00:00Z")
START_MS = int(dt.datetime.fromisoformat(START.replace("Z", "+00:00")).timestamp() * 1000)
FEE = float(arg("fee", "0.001"))
XS = [float(x) for x in arg("xs", "0.01,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0,1.2,1.5,2.0,3.0,inf").split(",")]
GATE_FROM = int(dt.datetime(2026, 10, 18, 11, 41, tzinfo=dt.timezone.utc).timestamp() * 1000)  # first recorded CB fire


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
IND = {}  # name -> per-trade value (nan when absent/expired)
for name in NAMES:
    r = sorted(rows[name])
    recv = np.array([x[0] for x in r], dtype=np.int64); exp = np.array([x[1] for x in r], dtype=np.int64)
    val = np.array([x[2] for x in r])
    idx = np.searchsorted(recv, T_TS, "right") - 1
    v = np.full(N, np.nan)
    ok = idx >= 0
    ok[ok] &= T_TS[ok] < exp[idx[ok]]
    v[ok] = val[idx[ok]]
    IND[name] = v
    print(f"  {name:24s} rows {len(r):6d}  present at {ok.mean():.1%} of trades")

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


def classes(x):
    """Per-trade class for multiplier x: 1 up, -1 down, 0 neutral/none. x = inf -> all neutral."""
    c = np.zeros(N, dtype=np.int8)
    if not np.isfinite(x):
        return c
    band = x * SIGMA
    up = HAS_TREND & (band > 0) & (SLOPE > band)
    dn = HAS_TREND & (band > 0) & (SLOPE < -band)
    c[up] = 1; c[dn] = -1
    return c


# ---------------------------------------------------------------- 1-min bars from the trades (prev-minute candle, candle stop)
T_MIN = T_TS // 60_000
MIN_KEYS, first_idx = np.unique(T_MIN, return_index=True)
last_idx = np.r_[first_idx[1:], N] - 1
M_LOW = np.minimum.reduceat(T_PX, first_idx); M_HIGH = np.maximum.reduceat(T_PX, first_idx)
M_CLOSE = T_PX[last_idx]
M_RANGE = M_HIGH - M_LOW
M_CUM = np.r_[0.0, np.cumsum(M_RANGE)]
MIN_POS = {int(m): k for k, m in enumerate(MIN_KEYS)}


def prev_candle(ts):
    k = MIN_POS.get(int(ts // 60_000) - 1)
    return None if k is None else (M_LOW[k], M_HIGH[k], M_CLOSE[k])


def mean_range(ts):
    """mean (high-low) of the last RANGE_CANDLES closed 1-min bars with minute < ts's minute; None if none."""
    hi = int(np.searchsorted(MIN_KEYS, ts // 60_000, "left"))
    lo = max(0, hi - RANGE_CANDLES)
    return None if hi <= lo else (M_CUM[hi] - M_CUM[lo]) / (hi - lo)


def candle_stop(side, i):
    """forming-15m extreme ∓ trailing mean 1-min range, or None (skip -> placeholder)."""
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


# ---------------------------------------------------------------- X-independent per-trade candidate material
I_START = int(np.searchsorted(T_TS, START_MS, "left"))
FLAG_OK = {}; ZONE = {}; INZONE = {}; TARGET = {}; REJ = {}
for tf in TFS:
    for s in SIDES:
        suf = "long" if s == "Buy" else "short"
        ov = IND[f"{tf}_cb_f_overshoot_{suf}"]; tr_ = IND[f"{tf}_cb_f_trend_{suf}"]
        FLAG_OK[(tf, s)] = ~((ov == 0) | (tr_ == 0))
        ZONE[(tf, s)] = IND[f"{tf}_cb_zone_{suf}"]
        INZONE[(tf, s)] = IND[f"{tf}_cb_inzone_{suf}"] == 1
        TARGET[(tf, s)] = IND[f"{tf}_cbnc_high" if s == "Buy" else f"{tf}_cbnc_low"]
# rule-2 candle test per trade (needs the zone value at that trade)
PREV = np.full((N, 3), np.nan)
pm = T_MIN - 1
pos = np.searchsorted(MIN_KEYS, pm)
posc = np.minimum(pos, len(MIN_KEYS) - 1)
hit = MIN_KEYS[posc] == pm
PREV[hit, 0] = M_LOW[posc[hit]]; PREV[hit, 1] = M_HIGH[posc[hit]]; PREV[hit, 2] = M_CLOSE[posc[hit]]
for tf in TFS:
    for s in SIDES:
        z = ZONE[(tf, s)]
        if s == "Buy":
            REJ[(tf, s)] = hit & (PREV[:, 0] <= z) & (PREV[:, 2] > z)
        else:
            REJ[(tf, s)] = hit & (PREV[:, 1] >= z) & (PREV[:, 2] < z)
BASE_OK = {k: FLAG_OK[k] & ~np.isnan(ZONE[k]) & ~np.isnan(TARGET[k]) for k in FLAG_OK}
POSSIBLE = np.zeros(N, dtype=bool)
for k in BASE_OK:
    POSSIBLE |= BASE_OK[k] & (INZONE[k] | REJ[k])
POSSIBLE &= HAS_TREND
POSSIBLE[:I_START] = False
print(f"trades from {fmt_ts(T_TS[I_START])}: {N - I_START}; trades where some (tf, side) can be a candidate: {POSSIBLE.sum()}")


# ---------------------------------------------------------------- the check + the flow
def simulate(x_entry, x_exit, fee=0.0, collect_fires=False):
    c_in = classes(x_entry); c_out = classes(x_exit) if x_exit != x_entry else c_in
    bal = START_BAL; pos = None; closed = []; fires = []
    fired = {}; last_fired = None; skipped_same = 0
    poss_idx = np.where(POSSIBLE)[0]
    poss_set_ptr = 0
    # iterate every trade from I_START; the check only runs on POSSIBLE trades
    for i in range(I_START, N):
        ts = int(T_TS[i]); px = T_PX[i]
        # ---- signal check (per trade)
        if POSSIBLE[i]:
            cls = c_in[i]
            cands = []
            for tf in TFS:
                for s in SIDES:
                    k = (tf, s)
                    if not BASE_OK[k][i]:
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
                    ev = dict(i=i, ts=ts, side=best[1], tf=best[0], zone=best[2], rule=best[3], target=best[4],
                              price=px, cls=int(cls), slope=float(SLOPE[i]))
                    if collect_fires:
                        fires.append(ev)
                    # ---- orchestrator
                    if pos is not None and pos["side"] == ev["side"]:
                        skipped_same += 1
                    else:
                        if pos is not None:
                            close_pos(pos, px, ts, "reversal", closed, fee); bal += closed[-1]["pnl"]; pos = None
                        stop, anchor, off = candle_stop(ev["side"], i)
                        kind = "candle"
                        if stop is None:
                            stop = px * (1 - PLACEHOLDER) if ev["side"] == "Buy" else px * (1 + PLACEHOLDER); kind = "placeholder"
                        dist = abs(px - stop)
                        size = min(RISK / dist, bal * MAX_NOTIONAL_FRAC / px)
                        pos = dict(side=ev["side"], entry=px, stop=stop, stop_kind=kind, target=ev["target"], size=size,
                                   open_ts=ts, open_i=i, extreme=None, tf=ev["tf"], rule=ev["rule"], dist=dist, armed=False,
                                   cls_open=int(cls))
                        continue  # the executor treats the opening trade as the fill; stop/advisor run from the next trade
        if pos is None:
            continue
        # ---- stop watcher
        if (pos["side"] == "Buy" and px <= pos["stop"]) or (pos["side"] == "Sell" and px >= pos["stop"]):
            close_pos(pos, px, ts, "stop", closed, fee); bal += closed[-1]["pnl"]; pos = None
            continue
        # ---- advisor loop: extreme, arm, trend-flip exit
        if pos["extreme"] is None:
            pos["extreme"] = px
        elif pos["side"] == "Buy":
            pos["extreme"] = max(pos["extreme"], px)
        else:
            pos["extreme"] = min(pos["extreme"], px)
        pos["armed"] = pos["extreme"] > pos["target"] if pos["side"] == "Buy" else pos["extreme"] < pos["target"]
        if pos["armed"]:
            co = c_out[i]
            if (pos["side"] == "Buy" and co == -1) or (pos["side"] == "Sell" and co == 1):
                close_pos(pos, px, ts, "target", closed, fee); bal += closed[-1]["pnl"]; pos = None
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
        return dict(n=0, net=0.0, pf=float("nan"), wr=float("nan"), ci=(0.0, 0.0), pneg=float("nan"), top2=0.0,
                    by={}, hold=float("nan"), risk=float("nan"), R=0.0)
    wins = pnl[pnl > 0]; losses = pnl[pnl < 0]
    by = defaultdict(lambda: [0, 0.0])
    for p, v in zip(closed, pnl):
        by[p["reason"]][0] += 1; by[p["reason"]][1] += v
    hold = np.array([(p["close_ts"] - p["open_ts"]) / 60000 for p in closed])
    risk = np.array([p["size"] * p["dist"] for p in closed])
    R = float((pnl / risk).sum())
    rng = np.random.default_rng(0)
    boot = np.array([rng.choice(pnl, len(pnl), replace=True).sum() for _ in range(4000)])
    return dict(n=len(pnl), net=float(pnl.sum()), pf=float(wins.sum() / abs(losses.sum())) if len(losses) else float("inf"),
                wr=len(wins) / len(pnl), ci=(float(np.percentile(boot, 5)), float(np.percentile(boot, 95))),
                pneg=float(np.mean(boot < 0)), top2=float(np.sort(pnl)[::-1][:2].sum()), by=dict(by),
                hold=float(np.median(hold)), risk=float(np.median(risk)), R=R)


def row(label, st, extra=""):
    by = st["by"]
    b = " ".join(f"{k[:4]}={by[k][0]}/{by[k][1]:+.0f}" for k in ("stop", "target", "reversal", "open_at_end") if k in by)
    return (f"{label:>14s} | n {st['n']:3d} | net {st['net']:+8.0f} | PF {st['pf']:5.2f} | wr {st['wr']:4.0%} | R {st['R']:+6.1f} "
            f"| hold {st['hold']:5.1f}m | risk {st['risk']:4.0f} | CI90 [{st['ci'][0]:+6.0f},{st['ci'][1]:+6.0f}] P<0 {st['pneg']:.2f} "
            f"| top2 {st['top2']:+5.0f} | {b} {extra}")


def class_mix(x):
    c = classes(x)[I_START:]
    h = HAS_TREND[I_START:]
    return f"up {np.mean(c[h] == 1):4.0%} down {np.mean(c[h] == -1):4.0%} neutral {np.mean(c[h] == 0):4.0%}"


if __name__ == "__main__":
    # ---- reproduction gate at X = 0.7: sim fires vs the recorded CbZoneEntry rows
    rec = []
    with open(f"{D}/events.jsonl") as f:
        for line in f:
            r = json.loads(line); e = r["ev"]
            rec.append(dict(ts=int(e["ts"]), side=e["side"], tf=int(e["tf_minutes"]), rule=e["rule"], cls=e["trend_class"],
                            slope=float(e["ma_slope"]), zone=float(e["zone"])))
    rec.sort(key=lambda e: e["ts"])
    closed07, fires07, _ = simulate(LIVE_X, LIVE_X, collect_fires=True)
    sim_after = [f for f in fires07 if f["ts"] >= GATE_FROM]
    sim_by_ts = defaultdict(list)
    for f in sim_after:
        sim_by_ts[f["ts"]].append(f)
    exact = 0; near = 0; cls_ok = 0; slope_err = []; unmatched = []
    sim_ts = np.array([f["ts"] for f in sim_after])
    for e in rec:
        m = [f for f in sim_by_ts.get(e["ts"], []) if f["side"] == e["side"] and f["tf"] == e["tf"]]
        if m:
            exact += 1
            f = m[0]
            cls_ok += ({1: "up", -1: "down", 0: "neutral"}[f["cls"]] == e["cls"])
            slope_err.append(abs(f["slope"] - e["slope"]))
            continue
        j = np.searchsorted(sim_ts, e["ts"])
        cand = [sim_after[k] for k in range(max(0, j - 3), min(len(sim_after), j + 3))
                if abs(sim_after[k]["ts"] - e["ts"]) <= 120_000 and sim_after[k]["side"] == e["side"] and sim_after[k]["tf"] == e["tf"]]
        if cand:
            near += 1
        else:
            unmatched.append(e)
    # class/slope at the recorded fire's own trade, independent of whether the sim fired there
    cls_at = 0; sl_err_at = []
    c07 = classes(LIVE_X)
    for e in rec:
        j = int(np.searchsorted(T_TS, e["ts"], "right")) - 1
        if j >= 0 and T_TS[j] == e["ts"]:
            # several trades can share the ms; take the last one (the deque's last)
            cls_at += ({1: "up", -1: "down", 0: "neutral"}[int(c07[j])] == e["cls"]); sl_err_at.append(abs(SLOPE[j] - e["slope"]))
    print("\n=== REPRODUCTION GATE (X = 0.7) ===")
    print(f"recorded CbZoneEntry fires: {len(rec)}  (from {fmt_ts(rec[0]['ts'])});  sim fires in the same span: {len(sim_after)}")
    print(f"  exact match (same ms, side, tf): {exact}/{len(rec)}; within ±120 s (same side, tf): {near}; unmatched: {len(unmatched)}")
    print(f"  class agrees at exact matches: {cls_ok}/{exact}; |slope diff| max {max(slope_err) if slope_err else float('nan'):.2e}")
    print(f"  class at the recorded fire's trade (any sim state): {cls_at}/{len(rec)} agree; |slope diff| max {max(sl_err_at):.2e} median {np.median(sl_err_at):.2e}")
    extra_sim = len(sim_after) - exact - near
    print(f"  sim fires with no recorded counterpart: {extra_sim} (restart resets of the once-per-zone state, warm-ups and feed gaps explain live/sim differences)")
    for e in unmatched[:12]:
        print(f"    unmatched recorded: {fmt_ts(e['ts'])} {e['side']:4s} tf {e['tf']:3d} {e['rule']:14s} {e['cls']}")
    print(f"  sim-0.7 fire rules: in_zone {sum(f['rule']=='in_zone' for f in fires07)}, zone_rejection {sum(f['rule']=='zone_rejection' for f in fires07)}; "
          f"tf mix {dict((tf, sum(f['tf']==tf for f in fires07)) for tf in TFS)}")

    # ---- joint sweep
    print(f"\n=== JOINT SWEEP (X for open gate and trend-flip exit), window from {fmt_ts(T_TS[I_START])} to {fmt_ts(T_TS[-1])}, paper (no fees) ===")
    results = {}
    for x in XS:
        closed, fires, sk = simulate(x, x, fee=FEE, collect_fires=True)
        results[x] = (closed, fires, sk)
        st = stats(closed)
        print(row(f"X={x:g}", st, f"| fires {len(fires)} skip {sk} | {class_mix(x)}"))
    print("\n--- fees: net after f %/side (fee = f · size · (entry + exit)); breakeven f = gross / Σ size·(entry+exit); bp = gross per trade in bp of notional ---")
    print(f"{'X':>8s} | {'gross':>7s} | {'notional/trade':>14s} | {'bp/trade':>8s} | {'0.01%':>7s} | {'0.02%':>7s} | {'0.05%':>7s} | {'0.10%':>7s} | breakeven f/side")
    for x in XS:
        cl = results[x][0]
        turn = sum(p["size"] * (p["entry"] + p["exit"]) for p in cl)
        gross = sum(p["pnl"] for p in cl)
        notional = np.median([p["size"] * p["entry"] for p in cl])
        bp = gross / len(cl) / notional * 1e4
        fees = [gross - f * turn for f in (0.0001, 0.0002, 0.0005, 0.001)]
        print(f"{x:8g} | {gross:+7.0f} | {notional:14.0f} | {bp:+8.1f} | " + " | ".join(f"{v:+7.0f}" for v in fees) + f" | {gross / turn * 100:.3f} %")

    # ---- paired comparison vs the live X: trades matched by their opening fire (same ms, same side)
    print(f"\n--- paired vs X={LIVE_X:g}: trades matched by opening trade; unmatched trades enter as (pnl − 0) ---")
    base = {(p["open_ts"], p["side"]): p for p in results[LIVE_X][0]}
    rng = np.random.default_rng(1)
    for x in XS:
        other = {(p["open_ts"], p["side"]): p for p in results[x][0]}
        keys = set(base) | set(other)
        diffs = np.array([other[k]["pnl"] if k in other else 0.0 for k in keys]) - np.array([base[k]["pnl"] if k in base else 0.0 for k in keys])
        both = sum(1 for k in keys if k in base and k in other)
        boot = np.array([rng.choice(diffs, len(diffs), replace=True).sum() for _ in range(4000)])
        print(f"{x:8g} | shared opens {both:3d} | only-X {len(other) - both:3d} | only-0.7 {len(base) - both:3d} | Δnet {diffs.sum():+7.0f} | paired CI90 [{np.percentile(boot, 5):+6.0f}, {np.percentile(boot, 95):+6.0f}] | P(Δ<0) {np.mean(boot < 0):.2f}")

    # ---- split halves / per day (by open time), joint sweep
    half = (T_TS[I_START] + T_TS[-1]) // 2
    days = sorted({int(p["open_ts"] // 86_400_000) for x in XS for p in results[x][0]})
    print(f"\n--- stability: net by half (split at {fmt_ts(half)}) and by UTC day, joint X, no fees ---")
    hdr = f"{'X':>8s} | {'H1 net':>8s} {'n':>3s} | {'H2 net':>8s} {'n':>3s} | " + " | ".join(f"{dt.datetime.fromtimestamp(d*86400, dt.timezone.utc).strftime('%m-%d'):>6s} n" for d in days)
    print(hdr)
    for x in XS:
        cl = results[x][0]
        h1 = [p for p in cl if p["open_ts"] < half]; h2 = [p for p in cl if p["open_ts"] >= half]
        per = []
        for d in days:
            dd = [p for p in cl if int(p["open_ts"] // 86_400_000) == d]
            per.append(f"{sum(p['pnl'] for p in dd):+6.0f} {len(dd):2d}")
        print(f"{x:8g} | {sum(p['pnl'] for p in h1):+8.0f} {len(h1):3d} | {sum(p['pnl'] for p in h2):+8.0f} {len(h2):3d} | " + " | ".join(per))

    # ---- entry-only and exit-only sweeps (the other gate held at 0.7)
    print("\n=== ENTRY-GATE SWEEP (exit X fixed at 0.7), no fees ===")
    for x in XS:
        closed, fires, sk = simulate(x, LIVE_X, collect_fires=True)
        print(row(f"Xin={x:g}", stats(closed), f"| fires {len(fires)} skip {sk}"))
    print("\n=== EXIT-GATE SWEEP (entry X fixed at 0.7), no fees ===")
    for x in XS:
        closed, fires, sk = simulate(LIVE_X, x, collect_fires=True)
        print(row(f"Xout={x:g}", stats(closed), f"| fires {len(fires)} skip {sk}"))

    # ---- rule / tf / side breakdown at a few X
    print("\n=== BREAKDOWN by rule / tf / side (joint X), no fees ===")
    for x in (0.3, 0.5, LIVE_X, 1.0, 1.5):
        if x not in results:
            continue
        cl = results[x][0]
        g = defaultdict(lambda: [0, 0.0])
        for p in cl:
            g[(p["rule"], p["tf"], p["side"])][0] += 1; g[(p["rule"], p["tf"], p["side"])][1] += p["pnl"]
        print(f"X={x:g}: " + "; ".join(f"{r[:3]}/{tf}/{s[:1]} {n}:{v:+.0f}" for (r, tf, s), (n, v) in sorted(g.items())))

    # ---- stop-kind mix and class-at-open mix at live X
    cl = results[LIVE_X][0]
    print(f"\nX=0.7 stop source: candle {sum(p['stop_kind']=='candle' for p in cl)}, placeholder {sum(p['stop_kind']=='placeholder' for p in cl)}; "
          f"class at open: {dict((k, sum(p['cls_open']==k for p in cl)) for k in (1, 0, -1))}")
