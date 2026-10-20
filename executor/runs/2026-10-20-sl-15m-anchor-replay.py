#!/usr/bin/env python3
"""Counterfactual replay of the paper executor's last 21 h with a different stop rule.

Modes:
  current  : stop as the executor placed it (book stop if adverse to entry, else 1 % placeholder)
  proposed : long  stop = low  of the current (forming) 15-min candle at open time  - d
             short stop = high of the current (forming) 15-min candle at open time + d
             where d = |entry - current stop|  ("existing sl value")
  proposed_closed15 : same, but the extreme of the LAST CLOSED 15-min candle

Everything else mirrors the executor: CbZoneEntry events as recorded in signal_log (skipped and
accepted alike), same-side event while open = skip, opposite side = reversal (close at event
price, reopen), stop watcher trips on trade price <= stop (long) / >= stop (short), target exit =
extreme past take-profit then opposite 10 s-bucket trend class (port of signals::trend), sizing =
min(RISK/d, free_quote*0.5/entry), paper = no fees.
"""
import csv, json, math, sys
from collections import defaultdict
import numpy as np

D = sys.argv[1] if len(sys.argv) > 1 else "data"
RISK = 100.0
START_BAL = 100_000.0
MAX_NOTIONAL_FRAC = 0.5
PLACEHOLDER = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--placeholder=")), 0.01))
WINDOW_CAP = 6000
BUCKET = 10
MA_WIN = 6
STD_MULT = 0.7
STD_SPAN = 2 * 3600
MIN_BUCKETS = 30
HORIZON_MS = 21 * 3600 * 1000
ANCHOR_PCT = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--anchor-pct=")), 0.001))  # for mode proposed_anchor_pct
# 1-min candle size (high-low) and body (|close-open|): global means over the replay window and trailing means
C = np.loadtxt(f"{D}/candles1m.csv", delimiter=",", usecols=(0, 1, 2, 3, 4), dtype=np.float64)
C_TS = C[:, 0].astype(np.int64); C_RANGE = C[:, 2] - C[:, 3]; C_BODY = np.abs(C[:, 4] - C[:, 1])
TRAIL_N = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--trail=")), 60))
def c1_stat(open_ts, which, trailing):
    """mean 1-min range/body: trailing = last TRAIL_N closed 1-min candles before open_ts, else global over the window."""
    arr = C_RANGE if which == "range" else C_BODY
    if trailing:
        hi = np.searchsorted(C_TS, (open_ts // 60_000) * 60_000, "left")  # candles that closed before the open's minute
        lo = max(0, hi - TRAIL_N)
        return float(arr[lo:hi].mean()) if hi > lo else float(arr.mean())
    return float(arr[C_TS >= C_WIN_START].mean())
FILL_AT_STOP = "--fill-at-stop" in sys.argv  # stop fills at the stop level instead of the crossing trade price

# ---------------------------------------------------------------- data
tr = np.loadtxt(f"{D}/trades.csv", delimiter=",", usecols=(0, 1), dtype=np.float64)
T_TS = tr[:, 0].astype(np.int64)
T_PX = tr[:, 1]

events = []
with open(f"{D}/events.jsonl") as f:
    for line in f:
        r = json.loads(line)
        e = r["ev"]
        events.append(dict(
            ts=int(e["ts"]), side=e["side"], price=float(e["price"]),
            stop=float(e["stop"]) if e.get("stop") else None,
            target=float(e["target"]), tf=e["tf_minutes"], rule=e["rule"],
            decision_id=r["decision_id"], seq=r["seq"]))
events.sort(key=lambda e: (e["ts"], e["seq"]))

# actual positions, keyed by decision_id
actual = {}
with open(f"{D}/positions.jsonl") as f:
    rows = [json.loads(l) for l in f]
by_pid = defaultdict(list)
for r in rows:
    if r["position_id"]:
        by_pid[r["position_id"]].append(r)
for pid, rs in by_pid.items():
    rs.sort(key=lambda r: r["seq"])
    last = rs[-1]
    first = rs[0]
    a = dict(pid=pid, side=first["side"], decision_id=first["decision_id"],
             open_ts=first["recorded_at"], close_ts=last["recorded_at"],
             entry=float(last["avg_entry_price"]) if last["avg_entry_price"] else None,
             exit=float(last["avg_exit_price"]) if last["avg_exit_price"] else None,
             stop=next((float(r["stop_loss_price"]) for r in rs if r["stop_loss_price"]), 0.0),
             tp=next((float(r["take_profit_price"]) for r in rs if r["take_profit_price"]), 0.0),
             size=max((float(r["net_size"]) for r in rs if r["net_size"]), default=0.0),
             pnl=float(last["realized_pnl"]) if last["realized_pnl"] is not None else None,
             reason=last["close_reason"])
    actual[a["decision_id"]] = a

END_TS = int(T_TS[-1])
_gaps = np.diff(T_TS)
_big = np.where(_gaps > 60_000)[0]
print(f"trade feed gaps > 60 s: {len(_big)}", [(int(T_TS[i]), int(_gaps[i]//1000)) for i in _big[:10]])
T0 = events[0]["ts"]
C_WIN_START = (T0 // 60_000) * 60_000

# ---------------------------------------------------------------- trend (port of signals::trend)
def trend_reading(i_now):
    """Class at trade index i_now using the last WINDOW_CAP trades up to and including it."""
    lo = max(0, i_now - WINDOW_CAP + 1)
    ts = T_TS[lo:i_now + 1] // 1000
    px = T_PX[lo:i_now + 1]
    sec = (ts // BUCKET) * BUCKET
    first, last = sec[0], sec[-1]
    n = int((last - first) // BUCKET) + 1
    if n < MIN_BUCKETS:
        return None
    idx = ((sec - first) // BUCKET).astype(np.int64)
    sums = np.bincount(idx, weights=px, minlength=n)
    cnt = np.bincount(idx, minlength=n)
    prices = np.empty(n)
    carried = 0.0
    for k in range(n):
        if cnt[k]:
            carried = sums[k] / cnt[k]
        prices[k] = carried
    # trailing means over MA_WIN incl. current; early entries average what exists
    cs = np.cumsum(prices)
    ma = np.empty(n)
    for k in range(n):
        if k < MA_WIN:
            ma[k] = cs[k] / (k + 1)
        else:
            ma[k] = (cs[k] - cs[k - MA_WIN]) / MA_WIN
    slopes = np.diff(ma)  # slope[k] for bucket k+1
    times = first + BUCKET * np.arange(n)
    now_s = T_TS[i_now] // 1000
    span_start = now_s - STD_SPAN
    in_span = slopes[(times[1:] >= span_start)]
    if len(in_span) < 2:
        sigma = 0.0
    else:
        sigma = float(np.sqrt(np.mean((in_span - in_span.mean()) ** 2)))
    s = float(slopes[-1]) if n > 1 else None
    band = STD_MULT * sigma
    if s is not None and band > 0 and s > band:
        cls = "up"
    elif s is not None and band > 0 and s < -band:
        cls = "down"
    else:
        cls = "neutral"
    return cls, s, sigma

# ---------------------------------------------------------------- 15-min extremes
def extreme_15m(open_ts, side, closed_prev=False):
    start = (open_ts // 900_000) * 900_000
    if closed_prev:
        end = start
        start = start - 900_000
    else:
        end = open_ts
    lo = np.searchsorted(T_TS, start, "left")
    hi = np.searchsorted(T_TS, end, "right")
    seg = T_PX[lo:hi]
    if len(seg) == 0:
        if closed_prev:
            return extreme_15m(open_ts, side, closed_prev=False)
        return None
    return float(seg.min()) if side == "Buy" else float(seg.max())

# ---------------------------------------------------------------- simulation
def current_stop(side, entry, ev_stop):
    if ev_stop is not None and ((side == "Buy" and ev_stop < entry) or (side == "Sell" and ev_stop > entry)):
        return ev_stop, "book"
    return (entry * (1 - PLACEHOLDER) if side == "Buy" else entry * (1 + PLACEHOLDER)), "placeholder"

def simulate(mode, use_actual_entry=True, verbose=False):
    bal = START_BAL
    pos = None
    closed = []
    ev_i = 0
    i_start = int(np.searchsorted(T_TS, T0, "left"))
    skipped_same = 0

    def open_pos(e, at_ts):
        nonlocal pos
        a = actual.get(e["decision_id"])
        entry = a["entry"] if (use_actual_entry and a and a["entry"]) else e["price"]
        stop_cur, kind = current_stop(e["side"], entry, e["stop"])
        d = abs(entry - stop_cur)
        if mode == "current":
            stop = stop_cur
            anchor = None
        else:
            anchor = extreme_15m(e["ts"], e["side"], closed_prev=(mode == "proposed_closed15"))
            if mode.startswith("proposed_anchor_only"):
                dd = 0.0
            elif mode == "proposed_anchor_pct":
                dd = anchor * ANCHOR_PCT
            elif mode.startswith("proposed_anchor_c1_"):      # proposed_anchor_c1_{range|body}_{global|trail}
                _, _, _, which, how = mode.split("_")
                dd = c1_stat(e["ts"], which, how == "trail")
            else:
                dd = d
            stop = anchor - dd if e["side"] == "Buy" else anchor + dd
            if (e["side"] == "Buy" and stop >= entry) or (e["side"] == "Sell" and stop <= entry):
                # anchor at/through the entry: one tick (anchor_only) or the placeholder fallback (anchor_only_fb)
                if mode == "proposed_anchor_only_fb":
                    stop = entry * (1 - PLACEHOLDER) if e["side"] == "Buy" else entry * (1 + PLACEHOLDER); kind = "placeholder"
                else:
                    stop = entry - 0.001 if e["side"] == "Buy" else entry + 0.001; kind = "one_tick"
            else:
                kind = mode.replace("proposed_", "") if mode.startswith("proposed_anchor") else kind
        dist = abs(entry - stop)
        size = min(RISK / dist, bal * MAX_NOTIONAL_FRAC / entry)
        pos = dict(side=e["side"], entry=entry, stop=stop, stop_kind=kind, d=d, anchor=anchor,
                   target=e["target"], size=size, open_ts=at_ts, extreme=None, tf=e["tf"],
                   decision_id=e["decision_id"], rule=e["rule"], armed=False, dist=dist)

    def close_pos(price, ts, reason):
        nonlocal pos, bal
        sgn = 1 if pos["side"] == "Buy" else -1
        pnl = (price - pos["entry"]) * pos["size"] * sgn
        bal += pnl
        pos.update(exit=price, close_ts=ts, reason=reason, pnl=pnl)
        closed.append(pos)
        pos = None

    for i in range(i_start, len(T_TS)):
        ts = int(T_TS[i]); px = T_PX[i]
        # events at or before this trade
        while ev_i < len(events) and events[ev_i]["ts"] <= ts:
            e = events[ev_i]; ev_i += 1
            if pos is None:
                open_pos(e, e["ts"])
            elif pos["side"] == e["side"]:
                skipped_same += 1
            else:
                close_pos(e["price"], e["ts"], "reversal")
                open_pos(e, e["ts"])
        if pos is None:
            continue
        # stop watcher
        if (pos["side"] == "Buy" and px <= pos["stop"]) or (pos["side"] == "Sell" and px >= pos["stop"]):
            close_pos(pos["stop"] if FILL_AT_STOP else px, ts, "stop")
            continue
        # advisor loop: extreme, arm, trend-flip exit
        if pos["extreme"] is None:
            pos["extreme"] = px
        elif pos["side"] == "Buy":
            pos["extreme"] = max(pos["extreme"], px)
        else:
            pos["extreme"] = min(pos["extreme"], px)
        if pos["side"] == "Buy":
            pos["armed"] = pos["extreme"] > pos["target"]
        else:
            pos["armed"] = pos["extreme"] < pos["target"]
        if pos["armed"]:
            r = trend_reading(i)
            if r and ((pos["side"] == "Buy" and r[0] == "down") or (pos["side"] == "Sell" and r[0] == "up")):
                close_pos(px, ts, "target")
    open_mtm = None
    if pos is not None:
        px = float(T_PX[-1])
        sgn = 1 if pos["side"] == "Buy" else -1
        pos.update(exit=px, close_ts=END_TS, reason="open_at_end", pnl=(px - pos["entry"]) * pos["size"] * sgn)
        open_mtm = pos
        closed.append(pos)
    return closed, skipped_same

def fmt_ts(ms):
    import datetime as dt
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%m-%d %H:%M:%S")

def summarize(name, closed):
    pnl = np.array([p["pnl"] for p in closed])
    wins = pnl[pnl > 0]; losses = pnl[pnl < 0]
    by_reason = defaultdict(lambda: [0, 0.0])
    for p in closed:
        by_reason[p["reason"]][0] += 1
        by_reason[p["reason"]][1] += p["pnl"]
    hold = np.array([(p["close_ts"] - p["open_ts"]) / 60000 for p in closed])
    print(f"\n=== {name} ===")
    print(f"trades {len(closed)}  net {pnl.sum():+.2f}  gross profit {wins.sum():+.2f} ({len(wins)})  gross loss {losses.sum():+.2f} ({len(losses)})  "
          f"flat {int((pnl == 0).sum())}  win rate {len(wins)/len(closed):.0%}  PF {wins.sum()/abs(losses.sum()) if len(losses) else float('inf'):.2f}  "
          f"avg hold {hold.mean():.1f} min  median {np.median(hold):.1f}")
    for k, (n, s) in sorted(by_reason.items()):
        print(f"  {k:12s} n={n:3d}  pnl={s:+.2f}")
    R = np.array([p["pnl"] / (p["size"] * p["dist"]) for p in closed])
    risk = np.array([p["size"] * p["dist"] for p in closed])
    rng = np.random.default_rng(0)
    boot = np.array([rng.choice(pnl, len(pnl), replace=True).sum() for _ in range(5000)])
    top = np.sort(pnl)[::-1][:2]
    print(f"  risk/trade median {np.median(risk):.1f} USDT (max {risk.max():.1f}); sum R {R.sum():+.1f}, mean R {R.mean():+.2f}; "
          f"net bootstrap 90% CI [{np.percentile(boot,5):+.0f}, {np.percentile(boot,95):+.0f}]; P(net<0) {np.mean(boot<0):.2f}; top-2 trades {top.sum():+.0f}")
    return pnl

if __name__ == "__main__":
    # ---- reproduction gate: actual recorded P&L vs simulator in 'current' mode
    act = [a for a in actual.values() if a["entry"] is not None]
    act_pnl = sum(a["pnl"] or 0 for a in act)
    act_stop = sum(a["pnl"] or 0 for a in act if a["reason"] == "stop")
    print(f"ACTUAL stop-outs sum {act_stop:+.2f}")
    print(f"ACTUAL recorded: positions {len(act)}  net {act_pnl:+.2f}  "
          f"stop {sum(1 for a in act if a['reason']=='stop')}  target {sum(1 for a in act if a['reason']=='target')}  "
          f"main_close(reversal) {sum(1 for a in act if a['reason']=='main_close')}")
    cur, sk_c = simulate("current")
    prop, sk_p = simulate("proposed")
    prop2, sk_p2 = simulate("proposed_closed15")
    prop3, _ = simulate("proposed_anchor_only")
    prop4, _ = simulate("proposed_anchor_only_fb")
    prop5, _ = simulate("proposed_anchor_pct")
    c1 = {m: simulate(m)[0] for m in ("proposed_anchor_c1_range_global", "proposed_anchor_c1_body_global", "proposed_anchor_c1_range_trail", "proposed_anchor_c1_body_trail")}
    p_cur = summarize("SIM current stop (reproduction of live rule)", cur)
    p_prop = summarize("SIM proposed: forming-15m extreme ± d", prop)
    p_prop2 = summarize("SIM variant: last CLOSED 15m extreme ± d", prop2)
    p_prop3 = summarize("SIM variant: forming-15m extreme only (d = 0), anchor at entry -> 1 tick", prop3)
    p_prop4 = summarize("SIM variant: forming-15m extreme only (d = 0), anchor at entry -> placeholder fallback", prop4)
    p_prop5 = summarize(f"SIM variant: forming-15m extreme ± {ANCHOR_PCT*100:.2f} % of the extreme", prop5)
    gr, gb = c1_stat(T0, "range", False), c1_stat(T0, "body", False)
    print(f"\n1-MIN CANDLE STATS over the window ({int((C_TS >= C_WIN_START).sum())} closed 1-min candles): mean range {gr:.4f} ({gr/0.001:.0f} ticks, {gr/np.mean(C[C_TS>=C_WIN_START,4])*100:.3f} %), "
          f"mean body {gb:.4f} ({gb/0.001:.0f} ticks, {gb/np.mean(C[C_TS>=C_WIN_START,4])*100:.3f} %); median range {np.median(C_RANGE[C_TS>=C_WIN_START]):.4f}, median body {np.median(C_BODY[C_TS>=C_WIN_START]):.4f}")
    for m, cl in c1.items():
        summarize(f"SIM variant: forming-15m extreme ± mean 1-min {m.split('_')[3]} ({m.split('_')[4]}{'-'+str(TRAIL_N) if m.endswith('trail') else ''})", cl)
        dd = np.array([abs(p['stop'] - p['anchor']) for p in cl])
        print(f"  offset used: median {np.median(dd):.4f} min {dd.min():.4f} max {dd.max():.4f}")
    print("  anchor-only stop source:", {k: sum(1 for p in prop3 if p["stop_kind"] == k) for k in ("anchor_only", "one_tick")},
          "| with fallback:", {k: sum(1 for p in prop4 if p["stop_kind"] == k) for k in ("anchor_only_fb", "placeholder")})
    print(f"placeholder {PLACEHOLDER*100:.2f} %; fill model: {'stop fills AT the stop level' if FILL_AT_STOP else 'stop fills at the crossing trade price'}")
    print(f"\nsame-side events skipped: current {sk_c}, proposed {sk_p}, closed15 {sk_p2}")

    # stop-distance stats
    for name, cl in (("current", cur), ("proposed", prop)):
        dist = np.array([p["dist"] for p in cl]); ent = np.array([p["entry"] for p in cl])
        print(f"{name}: stop distance median {np.median(dist):.4f} ({np.median(dist/ent)*100:.3f} %), "
              f"min {dist.min():.4f}, max {dist.max():.4f}; size median {np.median([p['size'] for p in cl]):.0f}")

    # per-trade table: current vs proposed (matched by decision id of the opening event)
    print("\nPER-TRADE (current sim | proposed sim)")
    print(f"{'open':15s} {'side':4s} {'tf':>3s} {'entry':>8s} | {'stop_c':>8s} {'reason_c':10s} {'pnl_c':>8s} {'hold_c':>7s} | {'anchor15':>8s} {'stop_p':>8s} {'reason_p':10s} {'pnl_p':>8s} {'hold_p':>7s}")
    pc = {p["decision_id"]: p for p in cur}
    pp = {p["decision_id"]: p for p in prop}
    for did in [e["decision_id"] for e in events]:
        c = pc.get(did); p = pp.get(did)
        if not c and not p:
            continue
        o = c or p
        cs = f"{c['stop']:8.4f} {c['reason']:10s} {c['pnl']:+8.2f} {(c['close_ts']-c['open_ts'])/60000:7.1f}" if c else " " * 37 + "(not opened)"
        ps = f"{p['anchor']:8.4f} {p['stop']:8.4f} {p['reason']:10s} {p['pnl']:+8.2f} {(p['close_ts']-p['open_ts'])/60000:7.1f}" if p else " " * 46 + "(not opened)"
        print(f"{fmt_ts(o['open_ts']):15s} {o['side']:4s} {o['tf']:3d} {o['entry']:8.4f} | {cs} | {ps}")

    # ---- reproduction detail: sim current vs actual per position
    print("\nREPRODUCTION: actual vs sim-current per actual position (entry, stop, size, pnl)")
    mism = 0
    for did, a in sorted(actual.items(), key=lambda kv: kv[1]["open_ts"]):
        c = pc.get(did)
        if not c:
            print(f"  {fmt_ts(a['open_ts'])} {a['side']:4s} actual pnl {a['pnl']:+8.2f} {a['reason']:10s} | sim: NOT OPENED"); mism += 1; continue
        flag = "" if abs((a["stop"] or 0) - c["stop"]) < 1e-6 and abs((a["size"] or 0) - c["size"]) / max(a["size"] or 1, 1) < 0.01 else "  <-- stop/size differ"
        print(f"  {fmt_ts(a['open_ts'])} {a['side']:4s} actual stop {a['stop']:.4f} size {a['size']:7.0f} exit {a['exit'] or 0:.4f} pnl {(a['pnl'] or 0):+8.2f} {a['reason'] or '':10s} | sim stop {c['stop']:.4f} size {c['size']:7.0f} exit {c['exit']:.4f} pnl {c['pnl']:+8.2f} {c['reason']:10s}{flag}")
    sim_total_on_actual = sum(pc[d]["pnl"] for d in actual if d in pc)
    print(f"  actual net {act_pnl:+.2f} vs sim-current net on same positions {sim_total_on_actual:+.2f}; sim-current total {p_cur.sum():+.2f}")

    # ---- trend port check against logged target exits
    print("\nTREND PORT CHECK (sim class/slope/sigma at the actual target-exit trade)")
    for did, a in sorted(actual.items(), key=lambda kv: kv[1]["open_ts"]):
        if a["reason"] != "target":
            continue
        # the exit trade: last trade with price == exit at/before close_ts (paper exit is a limit at the trade price)
        hi = np.searchsorted(T_TS, a["close_ts"] + 2000, "right")
        lo = np.searchsorted(T_TS, a["close_ts"] - 15000, "left")
        cand = [i for i in range(lo, hi) if abs(T_PX[i] - a["exit"]) < 1e-9]
        if not cand:
            print(f"  {fmt_ts(a['close_ts'])} exit {a['exit']} no matching trade"); continue
        i = cand[-1]
        r = trend_reading(i)
        print(f"  {fmt_ts(T_TS[i])} {a['side']:4s} exit {a['exit']:.4f} -> sim class {r[0]:7s} slope {r[1]:+.6f} sigma {r[2]:.6f}")

    # ---- transition matrix current -> proposed (matched by opening event)
    print("\nTRANSITIONS current -> proposed (same opening event)")
    trans = defaultdict(lambda: [0, 0.0, 0.0])
    for did, c in pc.items():
        p = pp.get(did)
        key = (c["reason"], p["reason"] if p else "not_opened")
        trans[key][0] += 1; trans[key][1] += c["pnl"]; trans[key][2] += (p["pnl"] if p else 0.0)
    for k, (n, a, b) in sorted(trans.items()):
        print(f"  {k[0]:9s} -> {k[1]:10s} n={n:2d}  pnl current {a:+8.2f}  proposed {b:+8.2f}  delta {b-a:+8.2f}")
    for name, cl in (("current", cur), ("proposed", prop)):
        st = [p["pnl"] for p in cl if p["reason"] == "stop"]
        print(f"  {name}: stop-outs n={len(st)} mean {np.mean(st):+.2f} median {np.median(st):+.2f} worst {min(st):+.2f}; "
              f"stop dist ticks median {np.median([p['dist'] for p in cl if p['reason']=='stop'])/0.001:.0f}")
    # d breakdown: how many proposed stops used a placeholder-derived d
    print("  proposed d source:", {k: sum(1 for p in prop if p["stop_kind"] == k) for k in ("book", "placeholder")})
