#!/usr/bin/env python3
"""Counterfactual replay: in overshoot-vetoed CB zone minutes, take the side from a longer
trade-price MA class (3 min / 5 min) instead of skipping the side.

Question (user, 2026-10-20): what P&L would the system make if, in overshoot zones, instead of
filtering the trades out it relied on the signal from a higher MA of the recent trades (3-min
and 5-min MA)?

Data: the cbov-check paper stack's own tables, exported with
  PG="docker exec cbov-check-postgres-1 psql -U executor -d trader -At -F,"
  $PG -c "select ord_ts, price, qty, side from trade where pair='LINKUSDT' order by ord_ts, trade_id" > trades.csv
  $PG -c "select received_at, expires_at, name, value from indicators where pair='LINKUSDT'
          and (name like '%\\_cb\\_%' or name like '%\\_cbnc\\_%') order by seq" > indicators.csv
  psql -At -c "select json_build_object('seq',seq,'decision_id',decision_id,'ts',ts,'signal_id',signal_id,
          'ev',record->'CbZoneEntry') from signal_log where signal_id like 'cb_zone%' order by seq" > events.jsonl
  psql -At -c "select row_to_json(p) from (select seq, position_id, event, status, side, net_size, avg_entry_price,
          avg_exit_price, stop_loss_price, take_profit_price, realized_pnl, close_reason, decision_id, signal_id,
          recorded_at from position_log where position_id is not null) p order by seq" > positions.jsonl

The entry check is a port of trade_executor `checks/cb_zone_entry.rs` + `signals::trend` run on
every stored trade: indicators = latest reading received at or before the trade and not expired;
rule 1 (in zone + class = direction), rule 2 (previous 1-min candle wick reached the zone and
closed back + class in {neutral, direction}); `cb_f_trend` veto always; once per (tf, side, zone),
both-sides contradiction, 60 s deferred gap, highest tf. Modes differ only in what happens when
`{tf}_cb_f_overshoot_{side} == 0`:

  current  : the side is skipped (live)
  no_veto  : the side is evaluated with the 1-min class like any other minute (ablation)
  ma3/ma5  : the side is evaluated with the 3-min / 5-min class INSTEAD of the 1-min class
  ma3_and/ma5_and : the 1-min AND the longer class must both pass
  ma3_all/ma5_all : the longer class replaces the 1-min class in EVERY minute (reference)

The longer class = signals::trend with the trailing-mean window raised from 6 to 18 / 30 buckets
of 10 s; bucket, 2 h sigma span, 0.7 sigma band, 30-bucket minimum and the 6 000-trade window
unchanged.

Position layer = today's live rules in every mode: same-side fire while open = skip, opposite =
reversal (close at the event price, reopen); stop = forming-15m extreme -/+ trailing mean range of
the last 60 closed 1-min bars (bars from trades), placeholder 0.2 % when not adverse; target =
{tf}_cbnc_{far bound} at fire time; close when the extreme since open passed the target and the
1-min class flips (unchanged in every mode); stop trips on the crossing trade; size =
min(100 / dist, free * 0.5 / entry); entry = the fire trade's price; paper = no fees (a 0.05 %
per side fee sensitivity is reported).
"""
import json, sys, datetime as dt
from collections import defaultdict
import numpy as np

D = sys.argv[1] if len(sys.argv) > 1 else "data"
RISK = 100.0
START_BAL = 100_000.0
MAX_NOTIONAL_FRAC = 0.5
PLACEHOLDER = 0.002
WINDOW_CAP = 6000; BUCKET = 10; STD_MULT = 0.7; STD_SPAN = 2 * 3600; MIN_BUCKETS = 30
MA_WINS = {1: 6, 3: 18, 5: 30}          # minutes -> buckets
MIN_INTERVAL_MS = 60_000
ANCHOR_MS = 15 * 60_000
RANGE_CANDLES = 60
FEE_SIDE = 0.0005
TFS = (15, 60, 240)
SIDES = ("Buy", "Sell")
SUFFIX = {"Buy": "long", "Sell": "short"}
FAR = {"Buy": "high", "Sell": "low"}
DIR = {"Buy": "up", "Sell": "down"}
HOURS = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--hours=")), 0))
MODES = ("current", "no_veto", "ma3", "ma5", "ma3_and", "ma5_and", "ma3_all", "ma5_all")


def fmt_ts(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%m-%d %H:%M:%S")


# ---------------------------------------------------------------- data
tr = np.loadtxt(f"{D}/trades.csv", delimiter=",", usecols=(0, 1), dtype=np.float64)
T_TS = tr[:, 0].astype(np.int64); T_PX = tr[:, 1]
N = len(T_TS)

events = []
with open(f"{D}/events.jsonl") as f:
    for line in f:
        r = json.loads(line); e = r["ev"]
        events.append(dict(ts=int(e["ts"]), side=e["side"], price=float(e["price"]), tf=int(e["tf_minutes"]),
                           rule=e["rule"], zone=float(e["zone"]), cls=e["trend_class"],
                           target=float(e["target"]) if e.get("target") else None,
                           slope=float(e["ma_slope"]), decision_id=r["decision_id"], seq=int(r["seq"])))
events.sort(key=lambda e: (e["ts"], e["seq"]))

by_pid = defaultdict(list)
with open(f"{D}/positions.jsonl") as f:
    for line in f:
        r = json.loads(line)
        by_pid[r["position_id"]].append(r)
actual = []
for pid, rs in by_pid.items():
    rs.sort(key=lambda r: r["seq"])
    last = rs[-1]
    actual.append(dict(pid=pid, open_ts=rs[0]["recorded_at"], close_ts=last["recorded_at"], side=rs[0]["side"],
                       pnl=float(last["realized_pnl"]) if last["realized_pnl"] is not None else None,
                       reason=last["close_reason"], status=last["status"]))

ind = defaultdict(lambda: ([], [], []))
with open(f"{D}/indicators.csv") as f:
    for line in f:
        rcv, exp, name, val = line.rstrip("\n").split(",")
        a = ind[name]; a[0].append(int(rcv)); a[1].append(int(exp)); a[2].append(float(val))
ind = {k: (np.array(v[0]), np.array(v[1]), np.array(v[2])) for k, v in ind.items()}


def ind_series(name):
    """Value of `name` at every trade: latest reading received at or before the trade and not expired; NaN if absent."""
    a = ind.get(name)
    out = np.full(N, np.nan)
    if a is None:
        return out
    i = np.searchsorted(a[0], T_TS, "right") - 1
    ok = (i >= 0)
    ii = np.where(ok, i, 0)
    ok &= a[1][ii] > T_TS
    out[ok] = a[2][ii[ok]]
    return out


# ---------------------------------------------------------------- window
T0 = events[0]["ts"]
END_TS = int(T_TS[-1])
if HOURS > 0:
    T0 = max(T0, END_TS - int(HOURS * 3600 * 1000))
I0 = int(np.searchsorted(T_TS, T0, "left"))
print(f"window {fmt_ts(T0)} -> {fmt_ts(END_TS)} UTC ({(END_TS - T0) / 3.6e6:.1f} h): trades {N - I0} of {N} stored; "
      f"recorded CbZoneEntry events in window {sum(1 for e in events if e['ts'] >= T0)} of {len(events)}")
_g = np.diff(T_TS[I0:]); _b = np.where(_g > 60_000)[0]
print(f"trade feed gaps > 60 s: {len(_b)}", [(fmt_ts(int(T_TS[I0 + i])), int(_g[i] // 1000)) for i in _b[:10]])

# ---------------------------------------------------------------- per-trade precomputation
MIN = T_TS // 60_000
# 1-min bars from trades (the executor's MinuteBars): per minute low/high/close
bar_min, bar_first = np.unique(MIN, return_index=True)
bar_last = np.r_[bar_first[1:], N] - 1
bar_low = np.minimum.reduceat(T_PX, bar_first)
bar_high = np.maximum.reduceat(T_PX, bar_first)
bar_close = T_PX[bar_last]
bar_range = bar_high - bar_low
bar_cum = np.r_[0.0, np.cumsum(bar_range)]
# previous-minute candle per trade (NaN when that minute has no trade)
prev_idx = np.searchsorted(bar_min, MIN - 1)
prev_ok = (prev_idx < len(bar_min)) & (bar_min[np.minimum(prev_idx, len(bar_min) - 1)] == MIN - 1)
pi = np.where(prev_ok, prev_idx, 0)
PREV_LOW = np.where(prev_ok, bar_low[pi], np.nan)
PREV_HIGH = np.where(prev_ok, bar_high[pi], np.nan)
PREV_CLOSE = np.where(prev_ok, bar_close[pi], np.nan)
# trailing mean range of the last RANGE_CANDLES closed bars with minute < this trade's minute
k_hi = np.searchsorted(bar_min, MIN, "left")          # bars with minute < MIN
k_lo = np.maximum(k_hi - RANGE_CANDLES, 0)
OFFSET = np.where(k_hi > k_lo, (bar_cum[k_hi] - bar_cum[k_lo]) / np.maximum(k_hi - k_lo, 1), np.nan)
# forming-15m extreme per trade (incl. the trade itself)
A15 = T_TS // ANCHOR_MS
a_first = np.unique(A15, return_index=True)[1]
ANCHOR_LOW = np.empty(N); ANCHOR_HIGH = np.empty(N)
for s, e in zip(a_first, np.r_[a_first[1:], N]):
    ANCHOR_LOW[s:e] = np.minimum.accumulate(T_PX[s:e])
    ANCHOR_HIGH[s:e] = np.maximum.accumulate(T_PX[s:e])

IND = {}
for tf in TFS:
    for side in SIDES:
        s = SUFFIX[side]
        IND[(tf, side, "zone")] = ind_series(f"{tf}_cb_zone_{s}")
        IND[(tf, side, "inzone")] = ind_series(f"{tf}_cb_inzone_{s}") == 1.0
        IND[(tf, side, "over")] = ind_series(f"{tf}_cb_f_overshoot_{s}") == 0.0     # True = vetoed
        IND[(tf, side, "trendf")] = ind_series(f"{tf}_cb_f_trend_{s}") == 0.0
        IND[(tf, side, "target")] = ind_series(f"{tf}_cbnc_{FAR[side]}")
        z = IND[(tf, side, "zone")]
        if side == "Buy":
            rej = (PREV_LOW <= z) & (PREV_CLOSE > z)
        else:
            rej = (PREV_HIGH >= z) & (PREV_CLOSE < z)
        IND[(tf, side, "rej")] = np.nan_to_num(rej.astype(float)).astype(bool)
        IND[(tf, side, "base")] = (~IND[(tf, side, "trendf")] & ~np.isnan(z) & ~np.isnan(IND[(tf, side, "target")])
                                   & (IND[(tf, side, "inzone")] | IND[(tf, side, "rej")]))

# ---------------------------------------------------------------- trend (port of signals::trend), three MA windows at once
_cache = {}


def classes(i):
    """{1: (class, slope, sigma), 3: ..., 5: ...} at trade i over the last WINDOW_CAP trades, or None (< 30 buckets)."""
    if i in _cache:
        return _cache[i]
    lo = max(0, i - WINDOW_CAP + 1)
    sec = (T_TS[lo:i + 1] // 1000) // BUCKET * BUCKET
    first = sec[0]
    n = int((sec[-1] - first) // BUCKET) + 1
    if n < MIN_BUCKETS:
        _cache[i] = None
        return None
    idx = ((sec - first) // BUCKET).astype(np.int64)
    sums = np.bincount(idx, weights=T_PX[lo:i + 1], minlength=n)
    cnt = np.bincount(idx, minlength=n)
    has = cnt > 0
    pos = np.maximum.accumulate(np.where(has, np.arange(n), 0))
    prices = (sums / np.where(has, cnt, 1))[pos]
    cs = np.cumsum(prices)
    times = first + BUCKET * np.arange(1, n)
    span_mask = times >= (T_TS[i] // 1000) - STD_SPAN
    out = {}
    for mins, w in MA_WINS.items():
        ma = np.empty(n)
        head = min(w, n)
        ma[:head] = cs[:head] / np.arange(1, head + 1)
        if n > w:
            ma[w:] = (cs[w:] - cs[:-w]) / w
        sl = np.diff(ma)
        in_span = sl[span_mask]
        sigma = float(np.sqrt(np.mean((in_span - in_span.mean()) ** 2))) if len(in_span) >= 2 else 0.0
        s = float(sl[-1])
        band = STD_MULT * sigma
        cls = "up" if (band > 0 and s > band) else "down" if (band > 0 and s < -band) else "neutral"
        out[mins] = (cls, s, sigma)
    _cache[i] = out
    return out


# ---------------------------------------------------------------- the check, per mode
def run_check(mode):
    """Port of CbZoneEntryCheck::check over every trade from I0; returns the fired events."""
    long_ma = 3 if "ma3" in mode else 5 if "ma5" in mode else None
    # trades where any (tf, side) could be a candidate in this mode
    poss = np.zeros(N, dtype=bool)
    for tf in TFS:
        for side in SIDES:
            b = IND[(tf, side, "base")]
            if mode == "current":
                b = b & ~IND[(tf, side, "over")]
            poss |= b
    poss[:I0] = False
    fired = {}            # (tf, side) -> zone
    last_fired = None
    out = []
    n_eval = 0
    for i in np.flatnonzero(poss):
        ts = int(T_TS[i])
        cl = classes(i)
        if cl is None:
            continue
        n_eval += 1
        cands = []
        for tf in TFS:
            for side in SIDES:
                if not IND[(tf, side, "base")][i]:
                    continue
                vetoed = bool(IND[(tf, side, "over")][i])
                if mode == "current" and vetoed:
                    continue
                direction = DIR[side]
                if mode.endswith("_all"):
                    use = [cl[long_ma]]
                elif vetoed and mode.endswith("_and"):
                    use = [cl[1], cl[long_ma]]
                elif vetoed and mode in ("ma3", "ma5"):
                    use = [cl[long_ma]]
                else:
                    use = [cl[1]]
                rule_1 = bool(IND[(tf, side, "inzone")][i]) and all(c[0] == direction for c in use)
                rule_2 = bool(IND[(tf, side, "rej")][i]) and all(c[0] in ("neutral", direction) for c in use)
                if not (rule_1 or rule_2):
                    continue
                zone = float(IND[(tf, side, "zone")][i])
                if fired.get((tf, side)) == zone:
                    continue
                cands.append(dict(tf=tf, side=side, zone=zone, rule="in_zone" if rule_1 else "zone_rejection",
                                  target=float(IND[(tf, side, "target")][i]), vetoed=vetoed, cls=use[-1][0]))
        if not cands:
            continue
        if any(c["side"] == "Buy" for c in cands) and any(c["side"] == "Sell" for c in cands):
            continue
        if last_fired is not None and ts - last_fired < MIN_INTERVAL_MS:
            continue
        best = max(cands, key=lambda c: c["tf"])
        for c in cands:
            fired[(c["tf"], c["side"])] = c["zone"]
        last_fired = ts
        price = float(T_PX[i])
        # candle stop (today's live rule)
        anchor = float(ANCHOR_LOW[i] if best["side"] == "Buy" else ANCHOR_HIGH[i])
        off = float(OFFSET[i]) if not np.isnan(OFFSET[i]) else None
        stop = None
        if off is not None:
            stop = anchor - off if best["side"] == "Buy" else anchor + off
            if (best["side"] == "Buy" and stop >= price) or (best["side"] == "Sell" and stop <= price):
                stop = None
        out.append(dict(i=int(i), ts=ts, price=price, stop=stop, anchor=anchor, offset=off, **best,
                        cls1=cl[1][0], slope1=cl[1][1], sigma1=cl[1][2]))
    return out, n_eval


# ---------------------------------------------------------------- position layer
def simulate(evs):
    bal = START_BAL
    pos = None
    closed = []
    ev_i = 0
    skipped_same = 0

    def open_pos(e):
        nonlocal pos
        entry = e["price"]
        stop = e["stop"]
        kind = "candle"
        if stop is None:
            stop = entry * (1 - PLACEHOLDER) if e["side"] == "Buy" else entry * (1 + PLACEHOLDER)
            kind = "placeholder"
        dist = abs(entry - stop)
        size = min(RISK / dist, bal * MAX_NOTIONAL_FRAC / entry)
        pos = dict(side=e["side"], entry=entry, stop=stop, stop_kind=kind, target=e["target"], size=size,
                   open_ts=e["ts"], extreme=None, tf=e["tf"], rule=e["rule"], vetoed=e["vetoed"], cls=e["cls"],
                   key=(e["ts"], e["tf"], e["side"]), armed=False, dist=dist)

    def close_pos(price, ts, reason):
        nonlocal pos, bal
        sgn = 1 if pos["side"] == "Buy" else -1
        pnl = (price - pos["entry"]) * pos["size"] * sgn
        bal += pnl
        pos.update(exit=price, close_ts=ts, reason=reason, pnl=pnl,
                   fee=(pos["entry"] + price) * pos["size"] * FEE_SIDE)
        closed.append(pos)
        pos = None

    for i in range(I0, N):
        ts = int(T_TS[i]); px = T_PX[i]
        while ev_i < len(evs) and evs[ev_i]["ts"] <= ts:
            e = evs[ev_i]; ev_i += 1
            if pos is None:
                open_pos(e)
            elif pos["side"] == e["side"]:
                skipped_same += 1
            else:
                close_pos(e["price"], e["ts"], "reversal")
                open_pos(e)
        if pos is None:
            continue
        if (pos["side"] == "Buy" and px <= pos["stop"]) or (pos["side"] == "Sell" and px >= pos["stop"]):
            close_pos(px, ts, "stop")
            continue
        if pos["extreme"] is None:
            pos["extreme"] = px
        elif pos["side"] == "Buy":
            pos["extreme"] = max(pos["extreme"], px)
        else:
            pos["extreme"] = min(pos["extreme"], px)
        pos["armed"] = pos["extreme"] > pos["target"] if pos["side"] == "Buy" else pos["extreme"] < pos["target"]
        if pos["armed"]:
            cl = classes(i)
            if cl and ((pos["side"] == "Buy" and cl[1][0] == "down") or (pos["side"] == "Sell" and cl[1][0] == "up")):
                close_pos(px, ts, "target")
    if pos is not None:
        px = float(T_PX[-1]); sgn = 1 if pos["side"] == "Buy" else -1
        pos.update(exit=px, close_ts=END_TS, reason="open_at_end", pnl=(px - pos["entry"]) * pos["size"] * sgn,
                   fee=(pos["entry"] + px) * pos["size"] * FEE_SIDE)
        closed.append(pos)
    return closed, skipped_same


def stats(closed):
    pnl = np.array([p["pnl"] for p in closed]) if closed else np.zeros(0)
    if len(pnl) == 0:
        return dict(n=0, net=0.0, pf=0.0, wr=0.0, stops=0, targets=0, revs=0, hold=0.0, risk=0.0, ci=(0, 0), pneg=0.0,
                    top2=0.0, R=0.0, net_fee=0.0, stop_mean=0.0)
    wins = pnl[pnl > 0]; losses = pnl[pnl < 0]
    rng = np.random.default_rng(0)
    boot = np.array([rng.choice(pnl, len(pnl), replace=True).sum() for _ in range(5000)])
    hold = np.array([(p["close_ts"] - p["open_ts"]) / 60000 for p in closed])
    risk = np.array([p["size"] * p["dist"] for p in closed])
    R = np.array([p["pnl"] / (p["size"] * p["dist"]) for p in closed])
    st = [p["pnl"] for p in closed if p["reason"] == "stop"]
    return dict(n=len(pnl), net=pnl.sum(), pf=(wins.sum() / abs(losses.sum())) if len(losses) else float("inf"),
                wr=len(wins) / len(pnl), stops=len(st), targets=sum(1 for p in closed if p["reason"] == "target"),
                revs=sum(1 for p in closed if p["reason"] == "reversal"), hold=float(np.median(hold)),
                risk=float(np.median(risk)), ci=(np.percentile(boot, 5), np.percentile(boot, 95)),
                pneg=float(np.mean(boot < 0)), top2=float(np.sort(pnl)[::-1][:2].sum()), R=float(R.sum()),
                net_fee=float(pnl.sum() - sum(p["fee"] for p in closed)), stop_mean=float(np.mean(st)) if st else 0.0)


def row(name, s, extra=""):
    return (f"| {name:9s} | {s['n']:3d} | {s['net']:+8.0f} | {s['net_fee']:+8.0f} | {s['pf']:4.2f} | {s['wr']:4.0%} | "
            f"{s['stops']:3d} / {s['stop_mean']:+6.1f} | {s['targets']:3d} | {s['revs']:3d} | {s['hold']:5.1f} | {s['risk']:4.0f} | "
            f"[{s['ci'][0]:+5.0f}, {s['ci'][1]:+5.0f}] | {s['pneg']:.2f} | {s['top2']:+5.0f} | {s['R']:+6.1f} |{extra}")


HDR = ("| mode | trades | net | net −fee | PF | win | stop-outs n / mean | targets | reversals | med hold min | med risk | 90 % CI | P(net<0) | top-2 | ΣR |\n"
       "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")

if __name__ == "__main__":
    import time
    t_start = time.time()
    # ---- how often the veto bites
    print("\nOVERSHOOT VETO INCIDENCE (trades in window where the side is otherwise a candidate minute: base = trend-flag pass, zone+target present, in zone or rejected)")
    for tf in TFS:
        for side in SIDES:
            b = IND[(tf, side, "base")][I0:]; v = IND[(tf, side, "over")][I0:]
            inz = IND[(tf, side, "inzone")][I0:]
            print(f"  tf {tf:3d} {side:4s}: base trades {int(b.sum()):7d}, of which overshoot-vetoed {int((b & v).sum()):7d} ({(b & v).sum() / max(b.sum(), 1):.0%}); "
                  f"in-zone minutes {len(np.unique(MIN[I0:][inz]))}, vetoed in-zone minutes {len(np.unique(MIN[I0:][inz & v]))}")

    results = {}
    for mode in MODES:
        evs, n_eval = run_check(mode)
        closed, sk = simulate(evs)
        results[mode] = (evs, closed, sk)
        print(f"[{mode}] evaluated {n_eval} trades, fired {len(evs)} ({sum(1 for e in evs if e['vetoed'])} on an overshoot-vetoed side), "
              f"positions {len(closed)}, same-side skipped {sk}  ({time.time() - t_start:.0f} s)")

    # ---- reproduction gate: current-mode fires vs recorded
    print("\nREPRODUCTION GATE: current mode vs recorded CbZoneEntry events (match = same side, tf, zone within 1e-6, |ts| <= 120 s)")
    sim = results["current"][0]
    rec = [e for e in events if e["ts"] >= T0]
    used = set(); matched = []; missed = []
    for e in rec:
        best = None
        for j, s in enumerate(sim):
            if j in used or s["side"] != e["side"] or s["tf"] != e["tf"] or abs(s["zone"] - e["zone"]) > 1e-6 or abs(s["ts"] - e["ts"]) > 120_000:
                continue
            if best is None or abs(s["ts"] - e["ts"]) < abs(sim[best]["ts"] - e["ts"]):
                best = j
        if best is None:
            missed.append(e)
        else:
            used.add(best); matched.append((e, sim[best]))
    extra = [s for j, s in enumerate(sim) if j not in used]
    dts = np.array([abs(s["ts"] - e["ts"]) / 1000 for e, s in matched]) if matched else np.zeros(0)
    same_rule = sum(1 for e, s in matched if e["rule"] == s["rule"])
    same_cls = sum(1 for e, s in matched if e["cls"] == s["cls1"])
    print(f"  recorded {len(rec)}, matched {len(matched)} (|dt| median {np.median(dts) if len(dts) else 0:.1f} s, max {dts.max() if len(dts) else 0:.0f} s; "
          f"same rule {same_rule}, same 1-min class {same_cls}), missed {len(missed)}, extra sim fires {len(extra)}")
    # missed: was the zone key already fired in sim (restart duplicate)?
    sim_keys = defaultdict(list)
    for s in sim:
        sim_keys[(s["tf"], s["side"], round(s["zone"], 6))].append(s["ts"])
    dup = sum(1 for e in missed if any(t < e["ts"] for t in sim_keys[(e["tf"], e["side"], round(e["zone"], 6))]))
    print(f"  missed of which the same (tf, side, zone) had already fired earlier in sim (executor restart re-fire / gap timing): {dup}")
    for e in missed[:40]:
        i = int(np.searchsorted(T_TS, e["ts"], "right")) - 1
        cl = classes(i)
        print(f"    missed {fmt_ts(e['ts'])} {e['side']:4s} tf {e['tf']:3d} {e['rule']:14s} rec class {e['cls']:7s} zone {e['zone']:.4f} | "
              f"sim at that trade: class {cl[1][0] if cl else None}, inzone {bool(IND[(e['tf'], e['side'], 'inzone')][i])}, rej {bool(IND[(e['tf'], e['side'], 'rej')][i])}, "
              f"over_veto {bool(IND[(e['tf'], e['side'], 'over')][i])}, trend_veto {bool(IND[(e['tf'], e['side'], 'trendf')][i])}, zone {IND[(e['tf'], e['side'], 'zone')][i]:.4f}, "
              f"base {bool(IND[(e['tf'], e['side'], 'base')][i])}")
    for s in extra[:40]:
        print(f"    extra  {fmt_ts(s['ts'])} {s['side']:4s} tf {s['tf']:3d} {s['rule']:14s} class {s['cls1']:7s} zone {s['zone']:.4f}")
    # slope check at matched fires
    if matched:
        rel = np.array([abs(s["slope1"] - e["slope"]) / max(abs(e["slope"]), 1e-9) for e, s in matched if abs(s["ts"] - e["ts"]) < 1000])
        print(f"  1-min slope at fires matched within 1 s: n {len(rel)}, median rel diff {np.median(rel) if len(rel) else float('nan'):.3f}, "
              f"share within 10 % {np.mean(rel < 0.1) if len(rel) else float('nan'):.0%}")
    act_win = [a for a in actual if a["open_ts"] >= T0 and a["pnl"] is not None]
    print(f"  actual recorded positions in window: {len([a for a in actual if a['open_ts'] >= T0])}, with P&L {len(act_win)}, net {sum(a['pnl'] for a in act_win):+.2f} "
          f"(three stop rules over the window: 1 % placeholder -> book stop 10-20 01:44Z -> candle stop 10-20 20:25Z; the sim applies the candle stop throughout, so P&L is not a reproduction target)")

    # ---- main table
    print(f"\nRESULTS (every mode: candle stop, 0.2 % placeholder, 1-min exit class, entry at the fire trade, no fees; 'net −fee' = {FEE_SIDE:.2%} per side)")
    print(HDR)
    for mode in MODES:
        evs, closed, sk = results[mode]
        print(row(mode, stats(closed), f" fires {len(evs)}, same-side skipped {sk}"))

    # ---- marginal: positions opened on an overshoot-vetoed side
    print("\nMARGINAL: positions whose opening fire was on an overshoot-vetoed side (these exist only because the veto was relaxed)")
    print(HDR)
    for mode in MODES:
        if mode == "current":
            continue
        evs, closed, sk = results[mode]
        sub = [p for p in closed if p["vetoed"]]
        print(row(mode, stats(sub), f" of {len(closed)}"))
    print("\nNON-MARGINAL: the other positions of each mode (fires on non-vetoed sides — they shift because the marginal positions occupy the book and reverse)")
    print(HDR)
    for mode in MODES:
        evs, closed, sk = results[mode]
        sub = [p for p in closed if not p["vetoed"]]
        print(row(mode, stats(sub), f" of {len(closed)}"))

    # ---- by tf and by rule for the marginal positions
    for mode in ("ma3", "ma5", "no_veto"):
        closed = results[mode][1]
        sub = [p for p in closed if p["vetoed"]]
        by = defaultdict(lambda: [0, 0.0, 0, 0])
        for p in sub:
            k = (p["tf"], p["side"], p["rule"]); by[k][0] += 1; by[k][1] += p["pnl"]; by[k][2] += p["reason"] == "stop"; by[k][3] += p["reason"] == "target"
        print(f"\n  {mode} marginal by (tf, side, rule): " + "; ".join(f"{k[0]}/{k[1]}/{k[2]}: n {v[0]} pnl {v[1]:+.0f} stops {v[2]} targets {v[3]}" for k, v in sorted(by.items())))

    # ---- transitions current -> ma3 / ma5 by opening fire key
    for mode in ("ma3", "ma5", "no_veto"):
        cur = {p["key"]: p for p in results["current"][1]}
        new = {p["key"]: p for p in results[mode][1]}
        trans = defaultdict(lambda: [0, 0.0, 0.0])
        for k, c in cur.items():
            p = new.get(k)
            key = (c["reason"], p["reason"] if p else "not_opened")
            trans[key][0] += 1; trans[key][1] += c["pnl"]; trans[key][2] += p["pnl"] if p else 0.0
        added = [p for k, p in new.items() if k not in cur]
        print(f"\nTRANSITIONS current -> {mode} (same opening fire; keys are (ts, tf, side))")
        for k, (n, a, b) in sorted(trans.items()):
            print(f"  {k[0]:11s} -> {k[1]:11s} n={n:3d}  pnl current {a:+8.2f}  {mode} {b:+8.2f}  delta {b - a:+8.2f}")
        print(f"  positions only in {mode}: n={len(added)} pnl {sum(p['pnl'] for p in added):+.2f} "
              f"(on vetoed side {sum(1 for p in added if p['vetoed'])}, pnl {sum(p['pnl'] for p in added if p['vetoed']):+.2f}; "
              f"stops {sum(1 for p in added if p['reason'] == 'stop')}, targets {sum(1 for p in added if p['reason'] == 'target')}, reversals {sum(1 for p in added if p['reason'] == 'reversal')})")

    # ---- class agreement in vetoed candidate minutes: how often does the longer MA say the same as the 1-min one?
    print("\nCLASS AGREEMENT at overshoot-vetoed candidate trades (ma3/ma5 fires vs the 1-min class at the same trade)")
    for mode in ("ma3", "ma5"):
        evs = [e for e in results[mode][0] if e["vetoed"]]
        agree = sum(1 for e in evs if e["cls"] == e["cls1"])
        print(f"  {mode}: {len(evs)} vetoed-side fires; longer class == 1-min class at the fire in {agree}; 1-min class at those fires: "
              + ", ".join(f"{c} {sum(1 for e in evs if e['cls1'] == c)}" for c in ("up", "down", "neutral")))

    # ---- split halves
    print("\nSPLIT HALVES (net / trades per mode, first half vs second half of the window by open time)")
    mid = (T0 + END_TS) // 2
    print(f"  split at {fmt_ts(mid)}")
    for mode in MODES:
        closed = results[mode][1]
        a = [p["pnl"] for p in closed if p["open_ts"] < mid]; b = [p["pnl"] for p in closed if p["open_ts"] >= mid]
        print(f"  {mode:9s}: first {sum(a):+8.0f} ({len(a):3d})   second {sum(b):+8.0f} ({len(b):3d})")

    # ---- per-trade tables for current, ma3, ma5
    for mode in ("current", "ma3", "ma5"):
        closed = results[mode][1]
        print(f"\nPER-TRADE {mode}")
        print(f"{'open':15s} {'side':4s} {'tf':>3s} {'rule':14s} {'vet':3s} {'cls':7s} {'entry':>8s} {'stop':>8s} {'kind':11s} {'target':>8s} {'reason':11s} {'pnl':>8s} {'hold':>6s}")
        for p in closed:
            print(f"{fmt_ts(p['open_ts']):15s} {p['side']:4s} {p['tf']:3d} {p['rule']:14s} {'V' if p['vetoed'] else '-':3s} {p['cls']:7s} {p['entry']:8.4f} {p['stop']:8.4f} {p['stop_kind']:11s} "
                  f"{p['target']:8.4f} {p['reason']:11s} {p['pnl']:+8.2f} {(p['close_ts'] - p['open_ts']) / 60000:6.1f}")
    print(f"\nelapsed {time.time() - t_start:.0f} s")
