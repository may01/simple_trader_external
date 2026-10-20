#!/usr/bin/env python3
"""Counterfactual replay: what if a higher-tf CB zone marker discards lower-tf fires?

Question (user, 2026-10-20): when markers point two ways -- e.g. tf 15 in the buy zone while
tf 60 is in the sell zone -- how does the P&L change if the higher tf's marker discards the
lower tf's signal?

Data: the cbov-check paper stack's own tables (trade, signal_log CbZoneEntry rows, position_log,
indicators = every `{tf}_cb_inzone_*` / `{tf}_cb_zone_*` / `{tf}_cb_f_*` reading main/ broadcast).

Simulator = the 2026-10-20 sl-15m-anchor replay's: recorded CbZoneEntry events in order; flat ->
open at the recorded entry (or the event price); same side while open -> skip; opposite side ->
reversal; stop = the event's stop when adverse to the entry, else the placeholder (1 % before the
2026-10-20 20:25Z restart, 0.2 % after); stop trips on the crossing trade; target exit = extreme
past the target then the opposite 10-s trend class (port of signals::trend); size =
min(RISK / dist, free_quote * 0.5 / entry); no fees.

Veto variants (a vetoed event is removed from the stream before the simulation):
  none          : as live
  opp_zone      : drop a tf-T fire when any higher tf is in-zone on the OPPOSITE side ({H}_cb_inzone_{opp} == 1)
  any_zone      : drop a tf-T fire when any higher tf is in-zone on EITHER side
  opp_price     : drop when the trade price sits beyond a higher tf's opposite zone line
                  (long fire with price >= {H}_cb_zone_short; short fire with price <= {H}_cb_zone_long)
  opp_fire      : drop when a higher tf fired the opposite side on its CURRENT zone value (same tf candle)
  no_lower_rev  : a lower-tf opposite fire cannot reverse a position opened by a higher tf (flat -> opens as usual)
"""
import csv, json, sys, datetime as dt
from collections import defaultdict
import numpy as np

D = sys.argv[1] if len(sys.argv) > 1 else "data"
RISK = 100.0
START_BAL = 100_000.0
MAX_NOTIONAL_FRAC = 0.5
RESTART_02 = int(dt.datetime(2026, 10, 20, 20, 25, tzinfo=dt.timezone.utc).timestamp() * 1000)  # placeholder 1 % -> 0.2 %
WINDOW_CAP = 6000; BUCKET = 10; MA_WIN = 6; STD_MULT = 0.7; STD_SPAN = 2 * 3600; MIN_BUCKETS = 30
FILL_AT_STOP = "--fill-at-stop" in sys.argv
HOURS = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--hours=")), 24))
TFS = (15, 60, 240)

def fmt_ts(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%m-%d %H:%M:%S")

# ---------------------------------------------------------------- data
tr = np.loadtxt(f"{D}/trades.csv", delimiter=",", dtype=np.float64)
T_TS = tr[:, 0].astype(np.int64); T_PX = tr[:, 1]

events = []
with open(f"{D}/events.csv") as f:
    for seq, ts, did, rec in csv.reader(f):
        e = json.loads(rec)["CbZoneEntry"]
        events.append(dict(ts=int(e["ts"]), side=e["side"], price=float(e["price"]),
                           stop=float(e["stop"]) if e.get("stop") else None,
                           target=float(e["target"]) if e.get("target") else None,
                           tf=int(e["tf_minutes"]), rule=e["rule"], zone=float(e["zone"]),
                           decision_id=did, seq=int(seq)))
events.sort(key=lambda e: (e["ts"], e["seq"]))

actual = {}
by_pid = defaultdict(list)
with open(f"{D}/positions.csv") as f:
    for r in csv.reader(f):
        seq, pid, event, status, side, net, ent, ex, sl, tp, pnl, reason, did, sid, rec = r
        if pid:
            by_pid[pid].append(dict(seq=int(seq), event=event, status=status, side=side, net=net, ent=ent, ex=ex,
                                    sl=sl, tp=tp, pnl=pnl, reason=reason, did=did, ts=int(rec)))
for pid, rs in by_pid.items():
    rs.sort(key=lambda r: r["seq"])
    first, last = rs[0], rs[-1]
    actual[pid] = dict(pid=pid, side=first["side"], decision_id=first["did"], open_ts=first["ts"], close_ts=last["ts"],
                                entry=float(last["ent"]) if last["ent"] else None, exit=float(last["ex"]) if last["ex"] else None,
                                stop=next((float(r["sl"]) for r in rs if r["sl"]), 0.0),
                                tp=next((float(r["tp"]) for r in rs if r["tp"]), 0.0),
                                size=max((float(r["net"]) for r in rs if r["net"]), default=0.0),
                                pnl=float(last["pnl"]) if last["pnl"] else None, reason=last["reason"], status=last["status"])

_ev_ts = np.array([e["ts"] for e in events])
_rekey = {}
for pid, a in actual.items():
    if a["decision_id"] in {e["decision_id"] for e in events}:
        _rekey[a["decision_id"]] = a; continue
    j = int(np.searchsorted(_ev_ts, a["open_ts"], "right")) - 1
    if j >= 0 and a["open_ts"] - _ev_ts[j] <= 10_000:
        a["matched_by"] = "time"; a["decision_id"] = events[j]["decision_id"]; _rekey[events[j]["decision_id"]] = a
    else:
        _rekey[a["decision_id"]] = a
actual = _rekey

# indicator history: name -> (received_at[], value[], expires_at[])
ind = defaultdict(lambda: ([], [], []))
with open(f"{D}/indicators.csv") as f:
    for seq, name, val, rcv, exp in csv.reader(f):
        a = ind[name]; a[0].append(int(rcv)); a[1].append(float(val)); a[2].append(int(exp))
ind = {k: (np.array(v[0]), np.array(v[1]), np.array(v[2])) for k, v in ind.items()}

def ind_at(name, t):
    """Latest reading received at or before t and not expired (the executor's MarketDataWindow rule); None if absent."""
    a = ind.get(name)
    if a is None:
        return None
    i = int(np.searchsorted(a[0], t, "right")) - 1
    if i < 0 or a[2][i] <= t:
        return None
    return float(a[1][i])

# ---------------------------------------------------------------- window
BEFORE = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--before=")), 0))
END_TS = int(T_TS[-1]) - int(BEFORE * 3600 * 1000)
START_TS = END_TS - int(HOURS * 3600 * 1000) if HOURS > 0 else events[0]["ts"]
win_events = [e for e in events if START_TS <= e["ts"] <= END_TS]
print(f"window {fmt_ts(START_TS)} -> {fmt_ts(END_TS)} UTC ({HOURS:g} h): {len(win_events)} CbZoneEntry events of {len(events)} stored; "
      f"trades in window {int(np.searchsorted(T_TS, END_TS, 'right') - np.searchsorted(T_TS, START_TS, 'left'))}")
_g = np.diff(T_TS[(T_TS >= START_TS)]); _b = np.where(_g > 60_000)[0]
print(f"trade feed gaps > 60 s in window: {len(_b)}", [(fmt_ts(int(T_TS[T_TS >= START_TS][i])), int(_g[i] // 1000)) for i in _b[:10]])

# ---------------------------------------------------------------- higher-tf context per event
OPP = {"Buy": "short", "Sell": "long"}
SAME = {"Buy": "long", "Sell": "short"}
for e in win_events:
    ctx = {}
    for H in TFS:
        ctx[H] = dict(inz_long=ind_at(f"{H}_cb_inzone_long", e["ts"]), inz_short=ind_at(f"{H}_cb_inzone_short", e["ts"]),
                      z_long=ind_at(f"{H}_cb_zone_long", e["ts"]), z_short=ind_at(f"{H}_cb_zone_short", e["ts"]))
    e["ctx"] = ctx
    higher = [H for H in TFS if H > e["tf"]]
    e["opp_zone"] = [H for H in higher if ctx[H][f"inz_{OPP[e['side']]}"] == 1]
    e["same_zone"] = [H for H in higher if ctx[H][f"inz_{SAME[e['side']]}"] == 1]
    e["opp_price"] = [H for H in higher if (ctx[H]["z_short"] is not None and e["side"] == "Buy" and e["price"] >= ctx[H]["z_short"])
                      or (ctx[H]["z_long"] is not None and e["side"] == "Sell" and e["price"] <= ctx[H]["z_long"])]
# opp_fire: a higher-tf opposite fire whose zone value is still the current one at this event's time
last_fire = {}  # (tf, side) -> zone value of its last fire
for e in events:  # over the full stream so a fire before the window counts
    if e["ts"] > END_TS:
        break
    if START_TS <= e["ts"]:
        opp_side = {"Buy": "Sell", "Sell": "Buy"}[e["side"]]
        e["opp_fire"] = [H for H in TFS if H > e["tf"] and (H, opp_side) in last_fire
                         and e["ctx"][H][f"z_{OPP[e['side']]}"] is not None
                         and abs(last_fire[(H, opp_side)] - e["ctx"][H][f"z_{OPP[e['side']]}"]) < 1e-9]
    last_fire[(e["tf"], e["side"])] = e["zone"]

# ---------------------------------------------------------------- trend (port of signals::trend)
def trend_reading(i_now):
    lo = max(0, i_now - WINDOW_CAP + 1)
    ts = T_TS[lo:i_now + 1] // 1000; px = T_PX[lo:i_now + 1]
    sec = (ts // BUCKET) * BUCKET
    first, last = sec[0], sec[-1]
    n = int((last - first) // BUCKET) + 1
    if n < MIN_BUCKETS:
        return None
    idx = ((sec - first) // BUCKET).astype(np.int64)
    sums = np.bincount(idx, weights=px, minlength=n); cnt = np.bincount(idx, minlength=n)
    prices = np.empty(n); carried = 0.0
    for k in range(n):
        if cnt[k]:
            carried = sums[k] / cnt[k]
        prices[k] = carried
    cs = np.cumsum(prices); ma = np.empty(n)
    for k in range(n):
        ma[k] = cs[k] / (k + 1) if k < MA_WIN else (cs[k] - cs[k - MA_WIN]) / MA_WIN
    slopes = np.diff(ma); times = first + BUCKET * np.arange(n)
    now_s = T_TS[i_now] // 1000
    in_span = slopes[(times[1:] >= now_s - STD_SPAN)]
    sigma = float(np.sqrt(np.mean((in_span - in_span.mean()) ** 2))) if len(in_span) >= 2 else 0.0
    s = float(slopes[-1]) if n > 1 else None
    band = STD_MULT * sigma
    if s is not None and band > 0 and s > band:
        return "up", s, sigma
    if s is not None and band > 0 and s < -band:
        return "down", s, sigma
    return "neutral", s, sigma

# ---------------------------------------------------------------- simulation
def placeholder_at(ts):
    return 0.002 if ts >= RESTART_02 else 0.01

def stop_for(side, entry, ev_stop, ts):
    if ev_stop is not None and ((side == "Buy" and ev_stop < entry) or (side == "Sell" and ev_stop > entry)):
        return ev_stop, "signal"
    p = placeholder_at(ts)
    return (entry * (1 - p) if side == "Buy" else entry * (1 + p)), "placeholder"

def simulate(variant, evs):
    bal = START_BAL; pos = None; closed = []; ev_i = 0
    skipped_same = 0; skipped_rev = 0; vetoed = []
    stream = []
    for e in evs:
        if variant == "opp_zone" and e["opp_zone"]: vetoed.append(e); continue
        if variant == "any_zone" and (e["opp_zone"] or e["same_zone"]): vetoed.append(e); continue
        if variant == "opp_price" and e["opp_price"]: vetoed.append(e); continue
        if variant == "opp_fire" and e["opp_fire"]: vetoed.append(e); continue
        stream.append(e)
    i_start = int(np.searchsorted(T_TS, START_TS, "left"))

    def open_pos(e):
        nonlocal pos
        a = actual.get(e["decision_id"])
        entry = a["entry"] if (a and a["entry"]) else e["price"]
        stop, kind = stop_for(e["side"], entry, e["stop"], e["ts"])
        dist = abs(entry - stop)
        size = min(RISK / dist, bal * MAX_NOTIONAL_FRAC / entry)
        target = e["target"] if e["target"] is not None else (entry * 1.01 if e["side"] == "Buy" else entry * 0.99)
        pos = dict(side=e["side"], entry=entry, stop=stop, stop_kind=kind, target=target, size=size, open_ts=e["ts"],
                   extreme=None, tf=e["tf"], decision_id=e["decision_id"], rule=e["rule"], armed=False, dist=dist)

    def close_pos(price, ts, reason, by=None):
        nonlocal pos, bal
        sgn = 1 if pos["side"] == "Buy" else -1
        pnl = (price - pos["entry"]) * pos["size"] * sgn
        bal += pnl
        pos.update(exit=price, close_ts=ts, reason=reason, pnl=pnl, closed_by=by)
        closed.append(pos); pos = None

    i_end = int(np.searchsorted(T_TS, END_TS, "right"))
    for i in range(i_start, i_end):
        ts = int(T_TS[i]); px = T_PX[i]
        while ev_i < len(stream) and stream[ev_i]["ts"] <= ts:
            e = stream[ev_i]; ev_i += 1
            if pos is None:
                open_pos(e)
            elif pos["side"] == e["side"]:
                skipped_same += 1
            elif variant == "no_lower_rev" and e["tf"] < pos["tf"]:
                skipped_rev += 1; vetoed.append(e)
            else:
                close_pos(e["price"], e["ts"], "reversal", by=e["tf"]); open_pos(e)
        if pos is None:
            continue
        if (pos["side"] == "Buy" and px <= pos["stop"]) or (pos["side"] == "Sell" and px >= pos["stop"]):
            close_pos(pos["stop"] if FILL_AT_STOP else px, ts, "stop"); continue
        if pos["extreme"] is None:
            pos["extreme"] = px
        elif pos["side"] == "Buy":
            pos["extreme"] = max(pos["extreme"], px)
        else:
            pos["extreme"] = min(pos["extreme"], px)
        pos["armed"] = pos["extreme"] > pos["target"] if pos["side"] == "Buy" else pos["extreme"] < pos["target"]
        if pos["armed"]:
            r = trend_reading(i)
            if r and ((pos["side"] == "Buy" and r[0] == "down") or (pos["side"] == "Sell" and r[0] == "up")):
                close_pos(px, ts, "target")
    if pos is not None:
        px = float(T_PX[i_end - 1]); sgn = 1 if pos["side"] == "Buy" else -1
        pos.update(exit=px, close_ts=END_TS, reason="open_at_end", pnl=(px - pos["entry"]) * pos["size"] * sgn, closed_by=None)
        closed.append(pos)
    return dict(closed=closed, vetoed=vetoed, skipped_same=skipped_same, skipped_rev=skipped_rev)

def summarize(name, res):
    closed = res["closed"]
    pnl = np.array([p["pnl"] for p in closed]) if closed else np.array([0.0])
    wins = pnl[pnl > 0]; losses = pnl[pnl < 0]
    by_reason = defaultdict(lambda: [0, 0.0])
    for p in closed:
        by_reason[p["reason"]][0] += 1; by_reason[p["reason"]][1] += p["pnl"]
    hold = np.array([(p["close_ts"] - p["open_ts"]) / 60000 for p in closed]) if closed else np.array([0.0])
    R = np.array([p["pnl"] / (p["size"] * p["dist"]) for p in closed]) if closed else np.array([0.0])
    rng = np.random.default_rng(0)
    boot = np.array([rng.choice(pnl, len(pnl), replace=True).sum() for _ in range(5000)])
    top = np.sort(pnl)[::-1][:2]
    pf = wins.sum() / abs(losses.sum()) if len(losses) else float("inf")
    print(f"\n=== {name} ===")
    print(f"trades {len(closed)}  net {pnl.sum():+.2f}  gross win {wins.sum():+.2f} ({len(wins)})  gross loss {losses.sum():+.2f} ({len(losses)})  "
          f"win rate {len(wins)/max(len(closed),1):.0%}  PF {pf:.2f}  median hold {np.median(hold):.1f} min  vetoed {len(res['vetoed'])}  "
          f"same-side skips {res['skipped_same']}  lower-rev skips {res['skipped_rev']}")
    for k, (n, s) in sorted(by_reason.items()):
        print(f"  {k:12s} n={n:3d}  pnl={s:+.2f}")
    print(f"  sum R {R.sum():+.1f}  mean R {R.mean():+.2f}  bootstrap 90% CI [{np.percentile(boot,5):+.0f}, {np.percentile(boot,95):+.0f}]  "
          f"P(net<0) {np.mean(boot<0):.2f}  top-2 {top.sum():+.0f}  net w/o top-2 {pnl.sum()-top.sum():+.0f}")
    return dict(name=name, n=len(closed), net=pnl.sum(), pf=pf, wr=len(wins)/max(len(closed),1), by=dict(by_reason),
                ci=(np.percentile(boot,5), np.percentile(boot,95)), pneg=np.mean(boot<0), top2=top.sum(), sumR=R.sum(), vetoed=len(res["vetoed"]))

VARIANTS = ("none", "opp_zone", "any_zone", "opp_price", "opp_fire", "no_lower_rev")

if __name__ == "__main__":
    # ---- how often does the two-way marker situation occur?
    print("\nEVENTS in window with higher-tf zone context (opp = higher tf in-zone on the opposite side; same = on the same side; "
          "oppP = price beyond higher tf's opposite zone line; oppF = higher tf fired opposite on its current zone)")
    print(f"{'ts':15s} {'side':4s} {'tf':>3s} {'rule':14s} {'price':>8s} | 15 L/S  60 L/S  240 L/S | opp     same    oppP    oppF   | actual")
    n_opp = n_same = n_oppP = n_oppF = 0
    for e in win_events:
        c = e["ctx"]
        def f(v): return "-" if v is None else str(int(v))
        a = actual.get(e["decision_id"])
        act = f"{a['reason'] or a['status']:10s} {a['pnl'] if a['pnl'] is not None else 0:+8.2f}" if a else "skipped/not placed"
        print(f"{fmt_ts(e['ts']):15s} {e['side']:4s} {e['tf']:3d} {e['rule']:14s} {e['price']:8.4f} | "
              f"{f(c[15]['inz_long'])}/{f(c[15]['inz_short'])}     {f(c[60]['inz_long'])}/{f(c[60]['inz_short'])}     {f(c[240]['inz_long'])}/{f(c[240]['inz_short'])}     | "
              f"{str(e['opp_zone']):7s} {str(e['same_zone']):7s} {str(e['opp_price']):7s} {str(e['opp_fire']):7s}| {act}")
        n_opp += bool(e["opp_zone"]); n_same += bool(e["same_zone"]); n_oppP += bool(e["opp_price"]); n_oppF += bool(e["opp_fire"])
    by_tf = defaultdict(int)
    for e in win_events: by_tf[e["tf"]] += 1
    print(f"\nfires by tf {dict(by_tf)}; with a higher tf in the OPPOSITE zone: {n_opp}; in the SAME zone: {n_same}; "
          f"price beyond a higher opposite zone line: {n_oppP}; higher tf fired opposite on its current zone: {n_oppF}")

    # ---- reproduction gate
    act = [a for a in actual.values() if a["entry"] is not None and START_TS <= a["open_ts"] <= END_TS and a["status"] == "closed"]
    print(f"\nACTUAL recorded in window: closed positions {len(act)}  net {sum(a['pnl'] or 0 for a in act):+.2f}  "
          f"stop {sum(1 for a in act if a['reason']=='stop')}  target {sum(1 for a in act if a['reason']=='target')}  "
          f"main_close(reversal) {sum(1 for a in act if a['reason']=='main_close')}")
    results = {v: simulate(v, win_events) for v in VARIANTS}
    cur = results["none"]["closed"]; pc = {p["decision_id"]: p for p in cur}
    mism = 0; stop_ok = 0; reason_ok = 0
    for a in act:
        c = pc.get(a["decision_id"])
        if not c:
            mism += 1; continue
        stop_ok += abs(a["stop"] - c["stop"]) < 1e-6
        reason_ok += (a["reason"] == "main_close" and c["reason"] == "reversal") or (a["reason"] == c["reason"])
    extra = [p for p in cur if p["decision_id"] not in actual]
    print(f"REPRODUCTION (sim 'none' vs actual): actual positions matched by opening decision {len(act)-mism}/{len(act)}; "
          f"same stop {stop_ok}/{len(act)-mism}; same close reason {reason_ok}/{len(act)-mism}; sim opens with no actual position {len(extra)}")
    for a in act:
        c = pc.get(a["decision_id"])
        if not c or abs(a["stop"] - c["stop"]) > 1e-6 or not ((a["reason"] == "main_close" and c["reason"] == "reversal") or a["reason"] == c["reason"]):
            print(f"  {fmt_ts(a['open_ts'])} {a['side']:4s} actual stop {a['stop']:.4f} {a['reason']:10s} pnl {(a['pnl'] or 0):+8.2f} | "
                  + (f"sim stop {c['stop']:.4f} {c['reason']:10s} pnl {c['pnl']:+8.2f}" if c else "sim: NOT OPENED"))
    for p in extra:
        print(f"  sim-only open {fmt_ts(p['open_ts'])} {p['side']:4s} tf {p['tf']} {p['reason']:10s} pnl {p['pnl']:+8.2f}")

    # ---- summaries
    labels = {"none": "none (as live)", "opp_zone": "veto: higher tf in-zone OPPOSITE side", "any_zone": "veto: higher tf in-zone EITHER side",
              "opp_price": "veto: price beyond higher tf's opposite zone line", "opp_fire": "veto: higher tf fired opposite on its current zone",
              "no_lower_rev": "lower tf cannot reverse a higher-tf position"}
    summ = {v: summarize(labels[v], results[v]) for v in VARIANTS}
    print(f"\nfill model: {'stop fills AT the stop level' if FILL_AT_STOP else 'stop fills at the crossing trade price'}; placeholder 1 % before {fmt_ts(RESTART_02)}, 0.2 % after")

    print("\nPER-TF (variant none): opening tf -> trades, net, by reason")
    for tf in TFS:
        sub = [p for p in cur if p["tf"] == tf]
        if not sub: continue
        br = defaultdict(lambda: [0, 0.0])
        for p in sub: br[p["reason"]][0] += 1; br[p["reason"]][1] += p["pnl"]
        print(f"  tf {tf:3d}: n={len(sub):3d} net {sum(p['pnl'] for p in sub):+8.2f}  " + "  ".join(f"{k} {n}/{v:+.0f}" for k, (n, v) in sorted(br.items())))
    print("  reversal closes by the tf that reversed:", {tf: sum(1 for p in cur if p["reason"] == "reversal" and p["closed_by"] == tf) for tf in TFS},
          " P&L of positions reversed by tf 15:", f"{sum(p['pnl'] for p in cur if p['reason']=='reversal' and p['closed_by']==15):+.2f}")
    print("\nSUMMARY")
    print(f"{'variant':52s} {'trades':>6s} {'net':>9s} {'PF':>5s} {'win%':>5s} {'stop':>5s} {'target':>6s} {'rev':>4s} {'vetoed':>6s} {'90% CI':>16s} {'P<0':>5s} {'top2':>6s} {'sumR':>6s}")
    for v in VARIANTS:
        s = summ[v]; by = s["by"]
        print(f"{labels[v]:52s} {s['n']:6d} {s['net']:+9.2f} {s['pf']:5.2f} {s['wr']*100:5.0f} {by.get('stop',[0])[0]:5d} {by.get('target',[0])[0]:6d} "
              f"{by.get('reversal',[0])[0]:4d} {s['vetoed']:6d} [{s['ci'][0]:+6.0f},{s['ci'][1]:+6.0f}] {s['pneg']:5.2f} {s['top2']:+6.0f} {s['sumR']:+6.1f}")

    # ---- per opening event: none vs each veto variant
    for v in VARIANTS[1:]:
        pv = {p["decision_id"]: p for p in results[v]["closed"]}
        print(f"\nTRANSITIONS none -> {v} (matched by opening event)")
        trans = defaultdict(lambda: [0, 0.0, 0.0])
        for did, c in pc.items():
            p = pv.get(did)
            key = (c["reason"], p["reason"] if p else "not_opened")
            trans[key][0] += 1; trans[key][1] += c["pnl"]; trans[key][2] += (p["pnl"] if p else 0.0)
        for did, p in pv.items():
            if did not in pc:
                trans[("not_opened", p["reason"])][0] += 1; trans[("not_opened", p["reason"])][2] += p["pnl"]
        for k, (n, a, b) in sorted(trans.items()):
            print(f"  {k[0]:11s} -> {k[1]:11s} n={n:2d}  pnl none {a:+8.2f}  {v} {b:+8.2f}  delta {b-a:+8.2f}")
        print(f"  vetoed events ({len(results[v]['vetoed'])}) and their fate under 'none':")
        for e in results[v]["vetoed"]:
            c = pc.get(e["decision_id"])
            fate = f"opened -> {c['reason']:10s} pnl {c['pnl']:+8.2f} hold {(c['close_ts']-c['open_ts'])/60000:6.1f} min" if c else "not opened (same-side skip)"
            why = e["opp_zone"] if v == "opp_zone" else (e["opp_zone"] + e["same_zone"]) if v == "any_zone" else e["opp_price"] if v == "opp_price" else e["opp_fire"] if v == "opp_fire" else "lower-tf reversal"
            print(f"    {fmt_ts(e['ts'])} {e['side']:4s} tf {e['tf']:3d} {e['rule']:14s} higher {str(why):10s} | none: {fate}")

    # ---- per-trade table none vs opp_zone
    pv = {p["decision_id"]: p for p in results["opp_zone"]["closed"]}
    print("\nPER-TRADE (none | opp_zone)")
    print(f"{'open':15s} {'side':4s} {'tf':>3s} {'entry':>8s} | {'stop':>8s} {'reason':10s} {'pnl':>8s} {'hold':>6s} | {'reason':10s} {'pnl':>8s} {'hold':>6s}")
    for e in win_events:
        c = pc.get(e["decision_id"]); p = pv.get(e["decision_id"])
        if not c and not p:
            continue
        o = c or p
        cs = f"{c['stop']:8.4f} {c['reason']:10s} {c['pnl']:+8.2f} {(c['close_ts']-c['open_ts'])/60000:6.1f}" if c else " " * 35 + "(not opened)"
        ps = f"{p['reason']:10s} {p['pnl']:+8.2f} {(p['close_ts']-p['open_ts'])/60000:6.1f}" if p else " " * 26 + "(not opened)"
        print(f"{fmt_ts(o['open_ts']):15s} {o['side']:4s} {o['tf']:3d} {o['entry']:8.4f} | {cs} | {ps}")
