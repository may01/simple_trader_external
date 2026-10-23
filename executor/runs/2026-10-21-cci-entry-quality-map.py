#!/usr/bin/env python3
"""Map CCI-14 (5- and 15-min candles, main/ convention) onto the CB zone fires of the paper executor and relate it to
entry success. Inputs: data/trades.csv, data/events.jsonl, data/positions.jsonl, sim_live.json (replay dump)."""
import json, sys, datetime as dt
import numpy as np
from collections import defaultdict, Counter
from cci_lib import CciFeed
D = "data"
tr = np.loadtxt(f"{D}/trades.csv", delimiter=",", usecols=(0, 1)); T = tr[:, 0].astype(np.int64); P = tr[:, 1]
feed = CciFeed(T, P)
def fts(ms): return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%m-%d %H:%M")
sgn = lambda side: 1 if side == "Buy" else -1

def excursions(i, side, entry, stop, target, W=15):
    """next W min after trade i: max favourable / adverse move (price units), stop hit?, target reached?, time of best adverse price before stop."""
    t_end = T[i] + W * 60_000
    j = int(np.searchsorted(T, t_end, "right"))
    seg = P[i + 1:j]
    if len(seg) == 0:
        return dict(mfe=0, mae=0, stop_hit=False, tgt_hit=False, mae_pre_stop=0)
    s = sgn(side)
    adv = (entry - seg) * s      # positive = price moved against the entry (a better entry was available)
    fav = (seg - entry) * s
    hit = np.flatnonzero(adv >= (entry - stop) * s)
    k_stop = hit[0] if len(hit) else len(seg)
    tgt = np.flatnonzero(fav >= (target - entry) * s) if target else []
    return dict(mfe=float(fav.max()), mae=float(adv.max()), stop_hit=bool(len(hit)), tgt_hit=bool(len(tgt)),
                mae_pre_stop=float(adv[:k_stop].max()) if k_stop > 0 else 0.0,
                tgt_before_stop=bool(len(tgt) and (not len(hit) or tgt[0] < hit[0])))

# ---- simulated live positions (uniform candle stop, 71.6 h)
sim = json.load(open("sim_live.json"))["live"]["closed"]
rows = []
for k, p in enumerate(sim):
    i = p["fire_i"]
    c5 = feed.at(i, 5); c15 = feed.at(i, 15)
    pair_p1 = (p["reason"] == "stop" and k + 1 < len(sim) and sim[k + 1]["side"] == p["side"]
               and (sim[k + 1]["open_ts"] - p["close_ts"]) <= 15 * 60_000 and (sim[k + 1]["entry"] - p["entry"]) * sgn(p["side"]) < 0)
    ex = excursions(i, p["side"], p["entry"], p["stop"], p["target"])
    rows.append(dict(src="sim", ts=p["open_ts"], side=p["side"], tf=p["tf"], rule=p["rule"], cci5=c5, cci15=c15,
                     adv5=c5 * (1 if p["side"] == "Sell" else -1), adv15=c15 * (1 if p["side"] == "Sell" else -1),
                     reason=p["reason"], pnl=p["pnl"], stop=p["reason"] == "stop", pair_p1=pair_p1, dist=p["dist"],
                     mae_sd=ex["mae"] / p["dist"], mae_pre_stop_sd=ex["mae_pre_stop"] / p["dist"], mfe_sd=ex["mfe"] / p["dist"],
                     tgt_before_stop=ex.get("tgt_before_stop", False), reentry=p.get("reentry", False)))
# ---- recorded positions (both stop eras)
ev = {}
for l in open(f"{D}/events.jsonl"):
    r = json.loads(l); ev[r["decision_id"]] = r["ev"]
by = defaultdict(list)
for l in open(f"{D}/positions.jsonl"):
    r = json.loads(l)
    if r["position_id"]: by[r["position_id"]].append(r)
rec = []
for pid, rs in by.items():
    rs.sort(key=lambda r: r["seq"]); f, l = rs[0], rs[-1]
    if not (f["signal_id"] or "").startswith("cb_zone") or l["realized_pnl"] is None: continue
    e = ev.get(f["decision_id"])
    if not e: continue
    i = int(np.searchsorted(T, int(e["ts"]), "right")) - 1
    c5 = feed.at(i, 5); c15 = feed.at(i, 15)
    rec.append(dict(src="rec", ts=int(e["ts"]), side=e["side"], tf=int(e["tf_minutes"]), rule=e["rule"], cci5=c5, cci15=c15,
                    adv5=c5 * (1 if e["side"] == "Sell" else -1), adv15=c15 * (1 if e["side"] == "Sell" else -1),
                    reason=l["close_reason"], pnl=float(l["realized_pnl"]), stop=l["close_reason"] == "stop"))
print(f"sim positions {len(rows)} (CCI nan: 5m {sum(np.isnan(r['cci5']) for r in rows)}, 15m {sum(np.isnan(r['cci15']) for r in rows)}); recorded {len(rec)}")

def binned(rs, key, edges, label):
    print(f"\n== {label}: bins of {key} (CCI signed into the trade's direction: + = momentum pushing into the zone)")
    print(f"{'bin':>12s} {'n':>4s} {'stop%':>6s} {'tgt/rev%':>8s} {'pair-P1%':>8s} {'net':>7s} {'mean':>6s} {'med mae/sd':>10s} {'mae≥1sd%':>8s} {'tgt<stop%':>9s}")
    for a, b in zip(edges[:-1], edges[1:]):
        s = [r for r in rs if a <= r[key] < b]
        if not s: print(f"{f'[{a},{b})':>12s} {0:4d}"); continue
        n = len(s); st = np.mean([r["stop"] for r in s]); tg = np.mean([r["reason"] in ("target", "reversal", "main_close") for r in s])
        pp = np.mean([r.get("pair_p1", False) for r in s]); net = sum(r["pnl"] for r in s)
        mae = np.median([r["mae_sd"] for r in s]) if "mae_sd" in s[0] else float("nan")
        m1 = np.mean([r["mae_sd"] >= 1 for r in s]) if "mae_sd" in s[0] else float("nan")
        tb = np.mean([r.get("tgt_before_stop", False) for r in s])
        print(f"{f'[{a},{b})':>12s} {n:4d} {st:6.0%} {tg:8.0%} {pp:8.0%} {net:+7.0f} {net/n:+6.0f} {mae:10.2f} {m1:8.0%} {tb:9.0%}")

E = [-1e9, -200, -140, -100, 0, 100, 140, 200, 1e9]
for key in ("adv15", "adv5"):
    binned([r for r in rows if not np.isnan(r[key])], key, E, f"SIM live (171, uniform candle stop) — {key}")
    binned([r for r in rec if not np.isnan(r[key])], key, E, f"RECORDED paper (114) — {key}")
for key in ("adv15", "adv5"):
    for tf in (15, 60):
        binned([r for r in rows if not np.isnan(r[key]) and r["tf"] == tf], key, [-1e9, -140, 0, 100, 140, 1e9], f"SIM tf{tf} — {key}")
# threshold sweep: stop rate / net above vs below
print("\n== threshold sweep on SIM (adv ≥ X vs < X): n, stop rate, net, mean pnl; pair-P1 rate; AUC-ish = P(adv of stop > adv of non-stop)")
for key in ("adv15", "adv5"):
    a = np.array([r[key] for r in rows]); ok = ~np.isnan(a); st = np.array([r["stop"] for r in rows]); pn = np.array([r["pnl"] for r in rows]); pp = np.array([r["pair_p1"] for r in rows])
    a, st, pn, pp = a[ok], st[ok], pn[ok], pp[ok]
    x, y = a[st], a[~st]
    auc = np.mean([xi > yj for xi in x for yj in y])
    print(f"  {key}: AUC(stop vs not) {auc:.3f}; corr(adv, pnl) {np.corrcoef(a, pn)[0,1]:+.3f}; n {len(a)}")
    for X in (0, 50, 100, 140, 200):
        hi = a >= X
        print(f"    X={X:4d}: above n {hi.sum():3d} stop {st[hi].mean() if hi.any() else float('nan'):.0%} net {pn[hi].sum():+6.0f} mean {pn[hi].mean() if hi.any() else 0:+5.0f} pairP1 {pp[hi].mean() if hi.any() else 0:.0%} | "
              f"below n {(~hi).sum():3d} stop {st[~hi].mean() if (~hi).any() else float('nan'):.0%} net {pn[~hi].sum():+6.0f} mean {pn[~hi].mean() if (~hi).any() else 0:+5.0f} pairP1 {pp[~hi].mean() if (~hi).any() else 0:.0%}")
# permutation null for the stop-rate difference at X=140 (adv15)
rng = np.random.default_rng(0)
for key in ("adv15", "adv5"):
    a = np.array([r[key] for r in rows]); ok = ~np.isnan(a); st = np.array([r["stop"] for r in rows])[ok]; pn = np.array([r["pnl"] for r in rows])[ok]; a = a[ok]
    for X in (100, 140):
        hi = a >= X
        if hi.sum() < 3: continue
        obs = st[hi].mean() - st[~hi].mean(); obs_pnl = pn[hi].mean() - pn[~hi].mean()
        null = []; nullp = []
        for _ in range(5000):
            perm = rng.permutation(len(a)); h = hi[perm]
            null.append(st[h].mean() - st[~h].mean()); nullp.append(pn[h].mean() - pn[~h].mean())
        null = np.array(null); nullp = np.array(nullp)
        print(f"  permutation {key} X={X}: Δstop-rate {obs:+.2f} (null 90 % [{np.percentile(null,5):+.2f}, {np.percentile(null,95):+.2f}], P(null≥obs) {np.mean(null>=obs):.2f}); "
              f"Δmean pnl {obs_pnl:+.0f} (P(null≤obs) {np.mean(nullp<=obs_pnl):.2f})")
# per-position table for the extreme bins
print("\n== SIM positions with adv15 ≥ 140")
for r in sorted(rows, key=lambda r: -r["adv15"] if not np.isnan(r["adv15"]) else 0):
    if np.isnan(r["adv15"]) or r["adv15"] < 140: continue
    print(f"  {fts(r['ts'])} {r['side']:4s} tf{r['tf']:<3d} {r['rule']:14s} cci15 {r['cci15']:+6.0f} cci5 {r['cci5']:+6.0f} {r['reason']:11s} {r['pnl']:+6.0f} mae/sd {r['mae_sd']:.2f} pre-stop {r['mae_pre_stop_sd']:.2f} tgt<stop {r['tgt_before_stop']} pairP1 {r['pair_p1']}")
json.dump(dict(sim=rows, rec=rec), open("cci_map.json", "w"), default=lambda o: bool(o) if isinstance(o, np.bool_) else float(o))
