#!/usr/bin/env python3
"""Descriptive pass: stop-out followed by a same-side re-entry at a better price (recorded positions only)."""
import json, sys, datetime as dt
from collections import defaultdict, Counter
import numpy as np
D = sys.argv[1]
ERA = 1792527900000  # 10-20 20:25Z candle stop live
def fts(ms): return dt.datetime.fromtimestamp(ms/1000, dt.timezone.utc).strftime("%m-%d %H:%M:%S")
rows=[json.loads(l) for l in open(f"{D}/positions.jsonl")]
by=defaultdict(list)
for r in rows:
    if r["position_id"]: by[r["position_id"]].append(r)
P=[]
for pid,rs in by.items():
    rs.sort(key=lambda r:r["seq"]); f,l=rs[0],rs[-1]
    if not (f["signal_id"] or "").startswith("cb_zone") or not l["avg_entry_price"]: continue
    P.append(dict(pid=pid,side=f["side"],sig=f["signal_id"],tf=int(f["signal_id"].split("_")[-1]),open=f["recorded_at"],close=l["recorded_at"],
        entry=float(l["avg_entry_price"]),exit=float(l["avg_exit_price"]) if l["avg_exit_price"] else None,
        stop=next((float(r["stop_loss_price"]) for r in rs if r["stop_loss_price"]),None),
        tp=next((float(r["take_profit_price"]) for r in rs if r["take_profit_price"]),None),
        size=max((float(r["net_size"]) for r in rs if r["net_size"]),default=0.0),
        pnl=float(l["realized_pnl"]) if l["realized_pnl"] is not None else None,reason=l["close_reason"],status=l["status"],decision=f["decision_id"]))
P.sort(key=lambda p:p["open"])
ev={}
for l in open(f"{D}/events.jsonl"):
    r=json.loads(l); ev[r["decision_id"]]=r["ev"]
for p in P:
    e=ev.get(p["decision"]); p["zone"]=float(e["zone"]) if e else None; p["rule"]=e["rule"] if e else None
closed=[p for p in P if p["pnl"] is not None]
print(f"recorded cb positions {len(P)}, closed {len(closed)}, {fts(P[0]['open'])} -> {fts(P[-1]['close'])}, net {sum(p['pnl'] for p in closed):+.0f}")
c=Counter(p["reason"] for p in closed); print("close reasons", dict(c), "stop pnl", f"{sum(p['pnl'] for p in closed if p['reason']=='stop'):+.0f}")
sgn=lambda p: 1 if p["side"]=="Buy" else -1
def better(p1,p2): return (p2["entry"]-p1["entry"])*sgn(p1) < 0
def analyse(pos,label,W):
    stops=[k for k,p in enumerate(pos) if p["reason"]=="stop"]
    pairs=[]
    for k in stops:
        p1=pos[k]
        if k+1>=len(pos): continue
        p2=pos[k+1]
        gap=(p2["open"]-p1["close"])/60000
        if p2["side"]!=p1["side"] or gap>W: continue
        if not better(p1,p2): continue
        pairs.append((p1,p2,gap))
    n=len(stops); m=len(pairs)
    L1=sum(p1["pnl"] for p1,_,_ in pairs); L2=sum(p2["pnl"] for _,p2,_ in pairs)
    print(f"\n== {label} W<={W} min: positions {len(pos)}, stop-outs {n}, stop→same-side better re-entry pairs {m} ({m/max(n,1):.0%} of stop-outs)")
    if not m: return pairs
    print(f"   P1 loss sum {L1:+.0f} (mean {L1/m:+.0f}); P2 pnl sum {L2:+.0f} (mean {L2/m:+.0f}); pair net {L1+L2:+.0f}; P2 outcomes {dict(Counter(p2['reason'] for _,p2,_ in pairs))}")
    # counterfactual: P1 with P2's stop & exit (same size as P1) ~ P1 entry held to P2 exit
    cf=[ (p2["exit"]-p1["entry"])*sgn(p1)*p1["size"] for p1,p2,_ in pairs if p2["exit"]]
    print(f"   cf 'P1 held to P2 exit' (P1 size): {sum(cf):+.0f} vs actual P1 {L1:+.0f}; cf 'skip P1, keep P2': {L2:+.0f} -> Δ vs actual pair {-L1:+.0f}")
    d_ent=[abs(p2["entry"]-p1["entry"])/abs(p1["entry"]-p1["stop"]) for p1,p2,_ in pairs if p1["stop"]]
    beyond=sum(1 for p1,p2,_ in pairs if p1["stop"] and (p2["entry"]-p1["stop"])*sgn(p1)<0)
    print(f"   P2 entry improvement / P1 stop-dist: median {np.median(d_ent):.2f}, P2 entry beyond P1 stop: {beyond}/{m}; gap min median {np.median([g for *_,g in pairs]):.1f}")
    same_tf=sum(1 for p1,p2,_ in pairs if p1["tf"]==p2["tf"]); same_zone=sum(1 for p1,p2,_ in pairs if p1["zone"] is not None and p2["zone"] is not None and abs(p1["zone"]-p2["zone"])<1e-9)
    print(f"   same tf {same_tf}/{m}, same zone value {same_zone}/{m}; P2 tf {dict(Counter(p2['tf'] for _,p2,_ in pairs))}, P2 rule {dict(Counter(p2['rule'] for _,p2,_ in pairs))}; P1 tf {dict(Counter(p1['tf'] for p1,_,_ in pairs))}")
    # chains
    ch=0
    for p1,p2,_ in pairs:
        if p2["reason"]=="stop" and any(q1 is p2 for q1,_,_ in pairs): ch+=1
    print(f"   chains (P2 itself is a P1 of another pair): {ch}")
    print(f"   {'P1 open':15s} {'side':4s} {'tf':>3s} {'entry':>8s} {'stop':>8s} {'exit':>8s} {'pnl':>7s} | {'gap':>5s} {'P2 tf':>5s} {'rule':12s} {'entry':>8s} {'stop':>8s} {'reason':8s} {'exit':>8s} {'pnl':>7s} {'Δe/sd':>5s}")
    for p1,p2,g in pairs:
        sd=abs(p1["entry"]-p1["stop"]) if p1["stop"] else float('nan')
        print(f"   {fts(p1['open']):15s} {p1['side']:4s} {p1['tf']:3d} {p1['entry']:8.4f} {p1['stop'] or 0:8.4f} {p1['exit'] or 0:8.4f} {p1['pnl']:+7.0f} | {g:5.1f} {p2['tf']:5d} {str(p2['rule']):12s} {p2['entry']:8.4f} {p2['stop'] or 0:8.4f} {str(p2['reason']):8s} {p2['exit'] or 0:8.4f} {p2['pnl']:+7.0f} {abs(p2['entry']-p1['entry'])/sd:5.2f}")
    return pairs
for W in (5,15,30,60):
    analyse(closed,"all",W)
era=[p for p in closed if p["open"]>=ERA]
for W in (15,60):
    analyse(era,"candle-stop era",W)
# stop-outs not followed by re-entry: what happened — next same-side position within 60 min but worse price?
stops=[k for k,p in enumerate(closed) if p["reason"]=="stop"]
cat=Counter()
for k in stops:
    if k+1>=len(closed): cat["last"]+=1; continue
    p1,p2=closed[k],closed[k+1]; gap=(p2["open"]-p1["close"])/60000
    if p2["side"]!=p1["side"]: cat[f"next opposite side (gap {'<=60' if gap<=60 else '>60'})"]+=1
    elif gap>60: cat["same side gap >60"]+=1
    elif better(p1,p2): cat["same side <=60 better"]+=1
    else: cat["same side <=60 worse"]+=1
print("\nstop-out follow-up categories:", dict(cat))
