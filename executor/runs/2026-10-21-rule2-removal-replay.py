#!/usr/bin/env python3
"""Counterfactual replay: the CB zone entry without rule 2 (the wick / zone-rejection signal).

Question (user, 2026-10-21): the position opens on two conditions -- rule 1 = price in the zone and the 1-min
trade-price MA moving in the direction; rule 2 = the previous 1-min candle's wick crossed the zone and the candle
closed back outside it, open on the next candle. How does the profit change if rule 2 is removed?

Everything is recomputed from the paper stack's own tables (no recorded fire is reused):
  trade        -> the executor's trade feed (ord_ts, price)
  indicators   -> every {tf}_cb_zone/inzone/f_overshoot/f_trend/cbnc_* reading main/ broadcast (received_at, expires_at)
  signal_log   -> the recorded CbZoneEntry fires (reproduction gate only)
  position_log -> the recorded positions (reproduction gate only)

Exports (psql -At -F, from cbov-check-postgres-1, db trader):
  trades.csv      select ord_ts, price, qty, side from trade where pair='LINKUSDT' order by ord_ts, ins_seq
  indicators.csv  select name, value, received_at, expires_at from indicators where pair='LINKUSDT'
                    and (name like '%cb_%' or name like '%cbnc%') order by received_at, seq
  events.jsonl    row_to_json of (seq, signal_id, decision_id, ts, record->'CbZoneEntry' as ev) from signal_log
                    where signal_id like 'cb_zone_%' order by ts, seq
  positions.jsonl row_to_json of position_log (seq, position_id, event, status, side, net_size, avg_entry_price,
                    avg_exit_price, stop_loss_price, take_profit_price, realized_pnl, close_reason, decision_id,
                    signal_id, recorded_at) order by seq

Ports (same numbers as the Rust, cb-candle-stop @ a6a5bc6, the stack that is live):
  signals::trend         10 s buckets over the last 6 000 trades, trailing mean over 6 buckets (1 min), slope = first
                         difference, sigma = population std of the slopes in the last 2 h, class up/down if
                         |slope| > 0.7 sigma, >= 30 buckets else no class.
  CbZoneEntryCheck       indicators at t = latest row with received_at <= t < expires_at; filters (0 vetoes, absent
                         passes); rule 1 = inzone == 1 and class = direction; rule 2 = previous 1-min candle (from the
                         trades) wick reached the zone and closed back and class in {neutral, direction}; once per
                         (tf, side, zone) with the latest zone per (tf, side) remembered; both sides -> nothing;
                         60 s gap deferred; highest tf fires; the target = {tf}_cbnc_{far} at fire.
  cb_stop::compute_candle_stop  stop = forming-15m extreme (1-min bars from trades, incl. the forming bar) -/+ mean
                         range of the last 60 closed 1-min bars; not adverse to the fire price -> 0.2 % placeholder.
  orchestrator/executor  flat -> open at the fire trade's price; same side while open -> skip; opposite -> reversal
                         (close at the fire price, reopen); stop watcher trips on trade <= stop (long) / >= stop;
                         target exit = extreme past the target (strict) then the opposite class on a later trade;
                         size = min(100 / dist, free * 0.5 / entry); paper = no fees (fee sensitivity reported).

Variants (which rules may produce a candidate; everything else identical):
  live  rule 1 + rule 2      (reproduction)
  r1    rule 1 only          (the question: rule 2 removed)
  r2    rule 2 only          (ablation: what rule 2 is worth on its own)
Note the second-order effect: a rule-2 fire marks its (tf, side, zone) as fired, so in `live` rule 1 can no
longer fire on that zone; in `r1` the same zone may fire later by rule 1. The transition table reports this.
"""
import json, sys, datetime as dt
from collections import defaultdict
import numpy as np

D = sys.argv[1] if len(sys.argv) > 1 else "data"
def arg(name, default):
    return next((a.split("=", 1)[1] for a in sys.argv if a.startswith(f"--{name}=")), default)

RISK = 100.0
START_BAL = 100_000.0
MAX_NOTIONAL_FRAC = 0.5
PLACEHOLDER = float(arg("placeholder", 0.002))
WINDOW_CAP = 6000
BUCKET = 10
STD_MULT = float(arg("x", 0.7))
STD_SPAN = 2 * 3600
MIN_BUCKETS = 30
MIN_INTERVAL_MS = 60_000
ANCHOR_MS = 15 * 60_000
RANGE_CANDLES = 60
FEE = float(arg("fee", 0.001))          # per side, reported as a sensitivity only
TFS = (15, 60, 240)
SIDES = ("Buy", "Sell")
SUFFIX = {"Buy": "long", "Sell": "short"}
FAR = {"Buy": "high", "Sell": "low"}
WINDOWS = (6,)
MATCH_MS = int(arg("match-ms", 60_000))

VARIANTS = {
    "live": dict(rules=("in_zone", "zone_rejection")),
    "r1":   dict(rules=("in_zone",)),
    "r2":   dict(rules=("zone_rejection",)),
}
ONLY = arg("variants", "")
if ONLY:
    VARIANTS = {k: v for k, v in VARIANTS.items() if k in ONLY.split(",")}

def fmt_ts(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%m-%d %H:%M:%S")

# ---------------------------------------------------------------- trades
tr = np.loadtxt(f"{D}/trades.csv", delimiter=",", usecols=(0, 1), dtype=np.float64)
T_TS = tr[:, 0].astype(np.int64)
T_PX = tr[:, 1]
N = len(T_TS)
assert np.all(np.diff(T_TS) >= 0)
T_SEC = T_TS // 1000
T_BKT = T_SEC // BUCKET
CUM_PX = np.concatenate([[0.0], np.cumsum(T_PX)])
T_MIN = T_TS // 60_000

# 1-min bars from the trades (the executor's MinuteBars and rule 2's previous candle)
MIN_U, MIN_FIRST = np.unique(T_MIN, return_index=True)
MIN_LAST = np.concatenate([MIN_FIRST[1:], [N]]) - 1
MIN_LOW = np.minimum.reduceat(T_PX, MIN_FIRST)
MIN_HIGH = np.maximum.reduceat(T_PX, MIN_FIRST)
MIN_CLOSE = T_PX[MIN_LAST]
MIN_RANGE = MIN_HIGH - MIN_LOW

def minute_row(m):
    k = np.searchsorted(MIN_U, m)
    if k < len(MIN_U) and MIN_U[k] == m:
        return k
    return None

# ---------------------------------------------------------------- recorded events / positions
events = []
with open(f"{D}/events.jsonl") as f:
    for line in f:
        r = json.loads(line)
        e = r["ev"]
        events.append(dict(ts=int(e["ts"]), side=e["side"], tf=int(e["tf_minutes"]), rule=e["rule"], zone=float(e["zone"]),
                           price=float(e["price"]), cls=e.get("trend_class"), slope=float(e["ma_slope"]) if e.get("ma_slope") else None,
                           stop=float(e["stop"]) if e.get("stop") else None, target=float(e["target"]) if e.get("target") else None,
                           anchor=float(e["stop_anchor"]) if e.get("stop_anchor") else None,
                           offset=float(e["stop_offset"]) if e.get("stop_offset") else None,
                           decision_id=r["decision_id"], seq=r["seq"]))
events.sort(key=lambda e: (e["ts"], e["seq"]))
T0 = int(arg("t0", events[0]["ts"]))
T_END = int(arg("t-end", T_TS[-1]))
I0 = int(np.searchsorted(T_TS, T0, "left"))
I_END = int(np.searchsorted(T_TS, T_END, "right"))

actual = {}
with open(f"{D}/positions.jsonl") as f:
    rows = [json.loads(l) for l in f]
by_pid = defaultdict(list)
for r in rows:
    if r["position_id"]:
        by_pid[r["position_id"]].append(r)
for pid, rs in by_pid.items():
    rs.sort(key=lambda r: r["seq"])
    first, last = rs[0], rs[-1]
    if not (first["signal_id"] or "").startswith("cb_zone"):
        continue
    actual[pid] = dict(pid=pid, side=first["side"], decision_id=first["decision_id"], signal_id=first["signal_id"],
                       open_ts=first["recorded_at"], close_ts=last["recorded_at"],
                       entry=float(last["avg_entry_price"]) if last["avg_entry_price"] else None,
                       exit=float(last["avg_exit_price"]) if last["avg_exit_price"] else None,
                       stop=next((float(r["stop_loss_price"]) for r in rs if r["stop_loss_price"]), None),
                       tp=next((float(r["take_profit_price"]) for r in rs if r["take_profit_price"]), None),
                       size=max((float(r["net_size"]) for r in rs if r["net_size"]), default=0.0),
                       pnl=float(last["realized_pnl"]) if last["realized_pnl"] is not None else None,
                       reason=last["close_reason"])

# ---------------------------------------------------------------- indicators as step functions, evaluated at every trade
ind = defaultdict(lambda: ([], [], []))
with open(f"{D}/indicators.csv") as f:
    for line in f:
        name, value, recv, exp = line.rstrip("\n").split(",")
        a = ind[name]; a[0].append(int(recv)); a[1].append(float(value)); a[2].append(int(exp))
IND = {}
nonmono = 0
for name, (recv, val, exp) in ind.items():
    recv = np.array(recv, dtype=np.int64); val = np.array(val); exp = np.array(exp, dtype=np.int64)
    order = np.argsort(recv, kind="stable"); recv, val, exp = recv[order], val[order], exp[order]
    nonmono += int(np.sum(np.diff(exp) < 0))
    ts = T_TS[I0:I_END]
    idx = np.searchsorted(recv, ts, "right") - 1
    ok = idx >= 0
    v = np.full(len(ts), np.nan)
    sel = idx[ok]
    valid = exp[sel] > ts[ok]
    vv = np.where(valid, val[sel], np.nan)
    v[ok] = vv
    IND[name] = v   # indexed by i - I0
print(f"trades {N} ({fmt_ts(T_TS[0])} -> {fmt_ts(T_TS[-1])}); replay {fmt_ts(T0)} -> {fmt_ts(T_END)}: {I_END - I0} trades; "
      f"indicator names {len(IND)}, rows {sum(len(a[0]) for a in ind.values())}, expiry non-monotone steps {nonmono}")
_gaps = np.diff(T_TS[I0:I_END])
_big = np.where(_gaps > 60_000)[0]
print(f"trade feed gaps > 60 s in the replay window: {len(_big)}", [(fmt_ts(T_TS[I0 + i]), int(_gaps[i] // 1000)) for i in _big[:10]])

def ind_at(name, i):
    return IND[name][i - I0]

# pre-candidates, vectorised: filters pass, zone + target present, inzone or rule-2 rejection (class-free part)
PRE = {}
RULE1 = {}
RULE2 = {}
_ts = T_TS[I0:I_END]
_prev_min = (_ts // 60_000) - 1
_k = np.searchsorted(MIN_U, _prev_min)
_k = np.clip(_k, 0, len(MIN_U) - 1)
_has_prev = MIN_U[_k] == _prev_min
_plow = np.where(_has_prev, MIN_LOW[_k], np.nan); _phigh = np.where(_has_prev, MIN_HIGH[_k], np.nan); _pclose = np.where(_has_prev, MIN_CLOSE[_k], np.nan)
for tf in TFS:
    for side in SIDES:
        s = SUFFIX[side]
        f_over = IND[f"{tf}_cb_f_overshoot_{s}"]; f_trend = IND[f"{tf}_cb_f_trend_{s}"]
        veto = (f_over == 0) | (f_trend == 0)
        zone = IND[f"{tf}_cb_zone_{s}"]; target = IND[f"{tf}_cbnc_{FAR[side]}"]
        present = ~np.isnan(zone) & ~np.isnan(target)
        inzone = IND[f"{tf}_cb_inzone_{s}"] == 1
        if side == "Buy":
            rej = _has_prev & (_plow <= zone) & (_pclose > zone)
        else:
            rej = _has_prev & (_phigh >= zone) & (_pclose < zone)
        ok = ~veto & present
        RULE1[(tf, side)] = ok & inzone
        RULE2[(tf, side)] = ok & rej
        PRE[(tf, side)] = ok & (inzone | rej)
ANY_PRE = np.zeros(I_END - I0, dtype=bool)
for v in PRE.values():
    ANY_PRE |= v
print("pre-candidate trades (filters pass, zone+target present, inzone or rejection):",
      {f"{tf}_{SUFFIX[s]}": int(PRE[(tf, s)].sum()) for tf in TFS for s in SIDES}, "any:", int(ANY_PRE.sum()))

# ---------------------------------------------------------------- trend (port of signals::trend), all windows at once, memoised per trade
_trend_cache = {}
def trend_at(i):
    """-> dict window -> (class, slope, sigma) or None (fewer than MIN_BUCKETS buckets)."""
    r = _trend_cache.get(i)
    if r is not None:
        return r
    lo = max(0, i - WINDOW_CAP + 1)
    b_lo, b_hi = T_BKT[lo], T_BKT[i]
    n = int(b_hi - b_lo) + 1
    if n < MIN_BUCKETS:
        _trend_cache[i] = None
        return None
    ids = np.arange(b_lo, b_hi + 1)
    starts = np.searchsorted(T_BKT, ids, "left")
    ends = np.searchsorted(T_BKT, ids + 1, "left")
    starts = np.maximum(starts, lo); ends = np.minimum(ends, i + 1)
    cnt = ends - starts
    sums = CUM_PX[ends] - CUM_PX[starts]
    has = cnt > 0
    means = np.where(has, sums / np.where(has, cnt, 1), 0.0)
    carry = np.maximum.accumulate(np.where(has, np.arange(n), 0))
    prices = means[carry]
    cs = np.cumsum(prices)
    times = (b_lo + np.arange(n)) * BUCKET
    span_start = T_SEC[i] - STD_SPAN
    in_span = times[1:] >= span_start
    out = {}
    k = np.arange(n)
    for w in WINDOWS:
        ma = np.where(k < w, cs / (k + 1), (cs - np.concatenate([np.zeros(w), cs[:-w]])[:n]) / w) if n > w else cs / (k + 1)
        sl = np.diff(ma)
        xs = sl[in_span]
        sigma = float(np.sqrt(np.mean((xs - xs.mean()) ** 2))) if len(xs) >= 2 else 0.0
        s = float(sl[-1])
        band = STD_MULT * sigma
        cls = "up" if (band > 0 and s > band) else ("down" if (band > 0 and s < -band) else "neutral")
        out[w] = (cls, s, sigma)
    _trend_cache[i] = out
    return out

# ---------------------------------------------------------------- candle stop (port of cb_stop::compute_candle_stop)
def candle_stop(i, side, price):
    ts = T_TS[i]
    m_now = ts // 60_000
    m_anchor = (ts // ANCHOR_MS) * ANCHOR_MS // 60_000
    # closed bars in [m_anchor, m_now) and the forming bar's trades up to i
    k_lo = np.searchsorted(MIN_U, m_anchor, "left"); k_now = np.searchsorted(MIN_U, m_now, "left")
    anchor = price
    if k_now > k_lo:
        anchor = min(anchor, MIN_LOW[k_lo:k_now].min()) if side == "Buy" else max(anchor, MIN_HIGH[k_lo:k_now].max())
    j0 = MIN_FIRST[k_now] if (k_now < len(MIN_U) and MIN_U[k_now] == m_now) else i
    seg = T_PX[j0:i + 1]
    anchor = min(anchor, seg.min()) if side == "Buy" else max(anchor, seg.max())
    if k_now == 0:
        return None
    rng = MIN_RANGE[max(0, k_now - RANGE_CANDLES):k_now]
    offset = float(rng.mean())
    stop = anchor - offset if side == "Buy" else anchor + offset
    adverse = stop < price if side == "Buy" else stop > price
    if not adverse:
        return None
    return stop, anchor, offset

# ---------------------------------------------------------------- the check + the position layer
def simulate(name, rules, verbose=False):
    entry_win = {15: 6, 60: 6, 240: 6}; exit_win = entry_win
    fired = {}            # (tf, side) -> zone   (the Rust keeps the latest zone per (tf, side))
    last_fired = None
    bal = START_BAL
    pos = None
    closed = []
    fires = []
    skipped_same = 0
    contradictions = 0
    deferred = 0

    def open_pos(fire, i):
        nonlocal pos
        entry = fire["price"]
        cs = candle_stop(i, fire["side"], entry)
        if cs is None:
            stop = entry * (1 - PLACEHOLDER) if fire["side"] == "Buy" else entry * (1 + PLACEHOLDER)
            kind, anchor, offset = "placeholder", None, None
        else:
            stop, anchor, offset = cs; kind = "candle"
        dist = abs(entry - stop)
        size = min(RISK / dist, bal * MAX_NOTIONAL_FRAC / entry)
        pos = dict(side=fire["side"], entry=entry, stop=stop, stop_kind=kind, anchor=anchor, offset=offset, target=fire["target"],
                   size=size, open_ts=fire["ts"], extreme=None, tf=fire["tf"], rule=fire["rule"], cls=fire["cls"], armed=False, dist=dist,
                   zone=fire["zone"], fire_i=i)

    def close_pos(price, ts, reason):
        nonlocal pos, bal
        sgn = 1 if pos["side"] == "Buy" else -1
        pnl = (price - pos["entry"]) * pos["size"] * sgn
        bal += pnl
        pos.update(exit=price, close_ts=ts, reason=reason, pnl=pnl, fee=FEE * pos["size"] * (pos["entry"] + price))
        closed.append(pos)
        pos = None

    for i in range(I0, I_END):
        ts = int(T_TS[i]); px = T_PX[i]; j = i - I0
        # ---- CbZoneEntryCheck
        if ANY_PRE[j]:
            tr_ = trend_at(i)
            if tr_ is not None:
                cands = []
                for tf in TFS:
                    cls = tr_[entry_win[tf]][0]
                    for side in SIDES:
                        if not PRE[(tf, side)][j]:
                            continue
                        direction = "up" if side == "Buy" else "down"
                        r1 = "in_zone" in rules and RULE1[(tf, side)][j] and cls == direction
                        r2 = "zone_rejection" in rules and RULE2[(tf, side)][j] and cls in ("neutral", direction)
                        if not (r1 or r2):
                            continue
                        zone = float(ind_at(f"{tf}_cb_zone_{SUFFIX[side]}", i))
                        if fired.get((tf, side)) == zone:
                            continue
                        cands.append(dict(tf=tf, side=side, zone=zone, rule="in_zone" if r1 else "zone_rejection",
                                          target=float(ind_at(f"{tf}_cbnc_{FAR[side]}", i)), cls=cls))
                if cands:
                    has_buy = any(c["side"] == "Buy" for c in cands); has_sell = any(c["side"] == "Sell" for c in cands)
                    if has_buy and has_sell:
                        contradictions += 1
                    elif last_fired is not None and ts - last_fired < MIN_INTERVAL_MS:
                        deferred += 1
                    else:
                        best = max(cands, key=lambda c: c["tf"])
                        for c in cands:
                            fired[(c["tf"], c["side"])] = c["zone"]
                        last_fired = ts
                        fire = dict(ts=ts, i=i, side=best["side"], tf=best["tf"], rule=best["rule"], zone=best["zone"],
                                    target=best["target"], price=px, cls=best["cls"], slope=tr_[entry_win[best["tf"]]][1],
                                    sigma=tr_[entry_win[best["tf"]]][2], n_cands=len(cands))
                        # ---- decision task
                        if pos is None:
                            open_pos(fire, i); fire["outcome"] = "open"
                        elif pos["side"] == fire["side"]:
                            skipped_same += 1; fire["outcome"] = "skip_same"
                        else:
                            close_pos(px, ts, "reversal"); open_pos(fire, i); fire["outcome"] = "reversal"
                        fires.append(fire)
                        continue   # the executor's own open/close on this trade; the stop watcher sees the next trade
        if pos is None:
            continue
        # ---- stop watcher
        if (pos["side"] == "Buy" and px <= pos["stop"]) or (pos["side"] == "Sell" and px >= pos["stop"]):
            close_pos(px, ts, "stop")
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
            tr_ = trend_at(i)
            if tr_ is not None:
                cls = tr_[exit_win[pos["tf"]]][0]
                if (pos["side"] == "Buy" and cls == "down") or (pos["side"] == "Sell" and cls == "up"):
                    close_pos(px, ts, "target")
    if pos is not None:
        px = float(T_PX[I_END - 1]); sgn = 1 if pos["side"] == "Buy" else -1
        pos.update(exit=px, close_ts=int(T_TS[I_END - 1]), reason="open_at_end", pnl=(px - pos["entry"]) * pos["size"] * sgn,
                   fee=FEE * pos["size"] * (pos["entry"] + px))
        closed.append(pos)
    return dict(name=name, closed=closed, fires=fires, skipped_same=skipped_same, contradictions=contradictions, deferred=deferred)

# ---------------------------------------------------------------- reporting
def stats(closed):
    if not closed:
        return dict(n=0)
    pnl = np.array([p["pnl"] for p in closed]); fee = np.array([p["fee"] for p in closed])
    wins = pnl[pnl > 0]; losses = pnl[pnl < 0]
    hold = np.array([(p["close_ts"] - p["open_ts"]) / 60000 for p in closed])
    risk = np.array([p["size"] * p["dist"] for p in closed])
    R = pnl / risk
    rng = np.random.default_rng(0)
    boot = np.array([rng.choice(pnl, len(pnl), replace=True).sum() for _ in range(5000)])
    top = np.sort(pnl)[::-1][:2]
    reasons = defaultdict(lambda: [0, 0.0])
    for p in closed:
        reasons[p["reason"]][0] += 1; reasons[p["reason"]][1] += p["pnl"]
    return dict(n=len(closed), net=pnl.sum(), gw=wins.sum(), nw=len(wins), gl=losses.sum(), nl=len(losses),
                wr=len(wins) / len(closed), pf=(wins.sum() / abs(losses.sum())) if len(losses) else float("inf"),
                hold_med=float(np.median(hold)), risk_med=float(np.median(risk)), sumR=R.sum(), meanR=R.mean(),
                ci=(np.percentile(boot, 5), np.percentile(boot, 95)), pneg=float(np.mean(boot < 0)), top2=top.sum(),
                net_fee=(pnl - fee).sum(), reasons=dict(reasons))

def row(label, st):
    if st["n"] == 0:
        return f"| {label} | 0 | | | | | | | | | | | |"
    r = st["reasons"]
    def rr(k):
        return f"{r[k][0]}" if k in r else "0"
    return (f"| {label} | {st['n']} | {st['net']:+.0f} | {st['net_fee']:+.0f} | {st['pf']:.2f} | {st['wr']:.0%} | "
            f"{rr('stop')} / {r['stop'][1]/r['stop'][0] if 'stop' in r else 0:+.0f} | {rr('target')} | {rr('reversal')} | "
            f"{st['hold_med']:.1f} | {st['risk_med']:.0f} | {st['sumR']:+.1f} | [{st['ci'][0]:+.0f}, {st['ci'][1]:+.0f}] | {st['pneg']:.2f} | {st['top2']:+.0f} |")

HEADER = ("| variant | trades | net | net −0.1 %/side fee | PF | win rate | stop-outs n / mean | targets | reversals | "
          "median hold min | median risk | sum R | 90 % CI | P(net<0) | top-2 |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")

def per_tf(res):
    out = []
    for tf in TFS:
        cl = [p for p in res["closed"] if p["tf"] == tf]
        st = stats(cl)
        nf = sum(1 for f in res["fires"] if f["tf"] == tf)
        out.append((tf, nf, st))
    return out

def print_variant(res):
    st = stats(res["closed"])
    print(f"\n=== {res['name']} ===")
    print(f"fires {len(res['fires'])} (15: {sum(1 for f in res['fires'] if f['tf']==15)}, 60: {sum(1 for f in res['fires'] if f['tf']==60)}, "
          f"240: {sum(1 for f in res['fires'] if f['tf']==240)}); rule in_zone {sum(1 for f in res['fires'] if f['rule']=='in_zone')}, "
          f"rejection {sum(1 for f in res['fires'] if f['rule']=='zone_rejection')}; outcomes open {sum(1 for f in res['fires'] if f['outcome']=='open')}, "
          f"skip_same {res['skipped_same']}, reversal {sum(1 for f in res['fires'] if f['outcome']=='reversal')}; "
          f"contradiction ticks {res['contradictions']}, deferred ticks {res['deferred']}")
    print(HEADER); print(row(res["name"], st))
    for tf, nf, s in per_tf(res):
        print(row(f"  tf {tf} ({nf} fires)", s) if s["n"] else f"| tf {tf} ({nf} fires) | 0 |")
    # split halves
    mid = (T0 + T_END) // 2
    a = stats([p for p in res["closed"] if p["open_ts"] < mid]); b = stats([p for p in res["closed"] if p["open_ts"] >= mid])
    print(f"  halves: first {a.get('n',0)} trades net {a.get('net',0):+.0f}; second {b.get('n',0)} trades net {b.get('net',0):+.0f}")
    sk = defaultdict(int)
    for p in res["closed"]:
        sk[p["stop_kind"]] += 1
    print(f"  stop source: {dict(sk)}; class at fire: { {c: sum(1 for f in res['fires'] if f['cls']==c) for c in ('up','down','neutral')} }")
    return st

def per_trade_table(res):
    print(f"\nPER-TRADE {res['name']}")
    print(f"{'open':15s} {'side':4s} {'tf':>3s} {'rule':14s} {'cls':7s} {'entry':>8s} {'stop':>8s} {'kind':11s} {'target':>8s} {'reason':11s} {'exit':>8s} {'pnl':>8s} {'hold':>7s}")
    for p in res["closed"]:
        print(f"{fmt_ts(p['open_ts']):15s} {p['side']:4s} {p['tf']:3d} {p['rule']:14s} {p['cls']:7s} {p['entry']:8.4f} {p['stop']:8.4f} {p['stop_kind']:11s} "
              f"{p['target']:8.4f} {p['reason']:11s} {p['exit']:8.4f} {p['pnl']:+8.2f} {(p['close_ts']-p['open_ts'])/60000:7.1f}")

# ---------------------------------------------------------------- run
results = {}
for name, v in VARIANTS.items():
    results[name] = simulate(name, v["rules"])
    print(f"simulated {name}: {len(results[name]['fires'])} fires, {len(results[name]['closed'])} positions, trend evaluations cached {len(_trend_cache)}", flush=True)

# ---- reproduction gate: live-variant fires vs the recorded CbZoneEntry rows
if "live" in results:
    sim = results["live"]["fires"]
    rec = [e for e in events if T0 <= e["ts"] <= T_END]
    used = set(); matched = []
    for e in rec:
        best = None
        for k, f in enumerate(sim):
            if k in used or f["side"] != e["side"] or f["tf"] != e["tf"]:
                continue
            d = abs(f["ts"] - e["ts"])
            if d <= MATCH_MS and (best is None or d < best[0]):
                best = (d, k)
        if best:
            used.add(best[1]); matched.append((e, sim[best[1]]))
    missed = [e for e in rec if not any(m[0] is e for m in matched)]
    extra = [f for k, f in enumerate(sim) if k not in used]
    print(f"\nREPRODUCTION (live variant vs recorded fires, same side+tf within {MATCH_MS//1000} s): recorded {len(rec)}, simulated {len(sim)}, "
          f"matched {len(matched)}, missed {len(missed)}, extra {len(extra)}")
    if matched:
        dts = np.array([abs(f["ts"] - e["ts"]) / 1000 for e, f in matched])
        same_rule = sum(1 for e, f in matched if e["rule"] == f["rule"]); same_cls = sum(1 for e, f in matched if e["cls"] == f["cls"])
        same_zone = sum(1 for e, f in matched if abs(e["zone"] - f["zone"]) < 1e-9)
        sl = [(e["slope"], f["slope"]) for e, f in matched if e["slope"] is not None and abs(f["ts"] - e["ts"]) < 1]
        print(f"  |dt| median {np.median(dts):.1f} s, max {dts.max():.1f} s; same rule {same_rule}/{len(matched)}, same class {same_cls}/{len(matched)}, "
              f"same zone value {same_zone}/{len(matched)}; exact-ts matches {len(sl)}, slope rel diff median "
              f"{np.median([abs(a-b)/max(abs(a),1e-12) for a,b in sl]) if sl else float('nan'):.2e}, max "
              f"{max((abs(a-b)/max(abs(a),1e-12) for a,b in sl), default=float('nan')):.2e}, > 1 % in {sum(1 for a,b in sl if abs(a-b)/max(abs(a),1e-12) > 0.01)}")
        # stop port: recorded candle-stop fires (stop_anchor present) vs sim candle stop at the same trade
        cs = [(e, f) for e, f in matched if e["anchor"] is not None and abs(f["ts"] - e["ts"]) < 1]
        if cs:
            dd = []
            for e, f in cs:
                r = candle_stop(f["i"], e["side"], e["price"])
                dd.append((e["stop"], r[0] if r else None, e["anchor"], r[1] if r else None, e["offset"], r[2] if r else None))
            ok = sum(1 for a, b, *_ in dd if b is not None and abs(a - b) < 5e-4)
            print(f"  candle-stop port: {ok}/{len(dd)} recorded stops reproduced within half a tick; samples: " +
                  "; ".join(f"rec {a:.4f}/{c:.4f}/{e_:.4f} sim {b if b is None else round(b,4)}/{d if d is None else round(d,4)}/{f_ if f_ is None else round(f_,4)}" for a, b, c, d, e_, f_ in dd[:4]))
    for e in missed[:40]:
        j = int(np.searchsorted(T_TS, e["ts"], "left"))
        pre = {f"{tf}_{SUFFIX[s]}": bool(PRE[(tf, s)][j - I0]) for tf in TFS for s in SIDES if j - I0 < I_END - I0} if I0 <= j < I_END else {}
        trr = trend_at(j) if I0 <= j < I_END else None
        print(f"  missed {fmt_ts(e['ts'])} {e['side']} tf{e['tf']} {e['rule']} cls {e['cls']} zone {e['zone']:.4f} | sim pre {pre} sim class1m {trr[6][0] if trr else None}")
    for f in extra[:40]:
        print(f"  extra  {fmt_ts(f['ts'])} {f['side']} tf{f['tf']} {f['rule']} cls {f['cls']} zone {f['zone']:.4f} outcome {f['outcome']}")
    # recorded positions vs sim-live positions after the candle-stop restart (same stop rule era)
    ERA = 1792527900000  # 2026-10-20 20:25Z: cb-candle-stop went live
    act = sorted([a for a in actual.values() if a["open_ts"] >= ERA and a["entry"]], key=lambda a: a["open_ts"])
    simp = [p for p in results["live"]["closed"] if p["open_ts"] >= ERA]
    print(f"  candle-stop era (>= {fmt_ts(ERA)}): recorded positions {len(act)} net {sum(a['pnl'] or 0 for a in act):+.2f}; "
          f"sim-live positions {len(simp)} net {sum(p['pnl'] for p in simp):+.2f}")
    for a in act:
        print(f"    rec {fmt_ts(a['open_ts'])} {a['side']:4s} {a['signal_id']:11s} entry {a['entry']:.4f} stop {a['stop'] or 0:.4f} size {a['size']:.0f} {a['reason'] or '':9s} pnl {(a['pnl'] or 0):+.2f}")
    for p in simp:
        print(f"    sim {fmt_ts(p['open_ts'])} {p['side']:4s} tf{p['tf']:<8d} entry {p['entry']:.4f} stop {p['stop']:.4f} size {p['size']:.0f} {p['reason']:9s} pnl {p['pnl']:+.2f}")

# ---- summary table
print("\nSUMMARY (same simulator, same stop rule, same window for every variant)")
print(HEADER)
S = {}
for name, res in results.items():
    S[name] = stats(res["closed"])
    print(row(name, S[name]))
print("\nPER-TF (positions by the tf of their opening fire)")
print(HEADER)
for name, res in results.items():
    for tf, nf, s in per_tf(res):
        print(row(f"{name} tf{tf} ({nf} fires)", s) if s["n"] else f"| {name} tf{tf} ({nf} fires) | 0 |")
print("\nHIGHER-TF SUBSET (tf 60 + 240 positions only)")
print(HEADER)
for name, res in results.items():
    s = stats([p for p in res["closed"] if p["tf"] in (60, 240)])
    print(row(f"{name} tf60+240", s) if s["n"] else f"| {name} tf60+240 | 0 |")

for name, res in results.items():
    print_variant(res)
for name, res in results.items():
    per_trade_table(res)

# ---- per-rule attribution inside live (positions by the rule of their opening fire)
if "live" in results:
    print("\nLIVE BY OPENING RULE (and by rule x tf)")
    print(HEADER)
    for rule in ("in_zone", "zone_rejection"):
        s_ = stats([p for p in results["live"]["closed"] if p["rule"] == rule])
        print(row(f"live {rule}", s_) if s_["n"] else f"| live {rule} | 0 |")
        for tf in TFS:
            s_ = stats([p for p in results["live"]["closed"] if p["rule"] == rule and p["tf"] == tf])
            print(row(f"  live {rule} tf{tf}", s_) if s_["n"] else f"| live {rule} tf{tf} | 0 |")
    for side in SIDES:
        s_ = stats([p for p in results["live"]["closed"] if p["rule"] == "zone_rejection" and p["side"] == side])
        print(row(f"  live zone_rejection {side}", s_) if s_["n"] else f"| live zone_rejection {side} | 0 |")
    print("\nLIVE RULE-2 POSITIONS BY CLASS AT FIRE")
    for c in ("neutral", "up", "down"):
        s_ = stats([p for p in results["live"]["closed"] if p["rule"] == "zone_rejection" and p["cls"] == c])
        print(row(f"  live rule2 cls={c}", s_) if s_["n"] else f"| live rule2 cls={c} | 0 |")

# ---- what happens to each live rule-2 position under r1 (same side, r1 position opened within -5..+60 min, closest)
if "live" in results and "r1" in results:
    v = "r1"
    print(f"\nTRANSITIONS live -> {v}, every live position opened by rule 2 (variant position = same side, opened within -5..+60 min, closest)")
    print(f"{'live open':15s} {'side':4s} {'tf':>3s} {'cls':7s} {'reason':9s} {'pnl':>8s} | {'var open':15s} {'tf':>3s} {'rule':14s} {'reason':9s} {'pnl':>8s} {'delay':>6s} {'d_entry':>8s}")
    used = set(); agg = defaultdict(lambda: [0, 0.0, 0.0])
    for lp in [p for p in results["live"]["closed"] if p["rule"] == "zone_rejection"]:
        best = None
        for k, vp in enumerate(results[v]["closed"]):
            if k in used or vp["side"] != lp["side"]:
                continue
            d = vp["open_ts"] - lp["open_ts"]
            if -5 * 60000 <= d <= 60 * 60000 and (best is None or abs(d) < abs(best[0])):
                best = (d, k)
        if best is None:
            print(f"{fmt_ts(lp['open_ts']):15s} {lp['side']:4s} {lp['tf']:3d} {lp['cls']:7s} {lp['reason']:9s} {lp['pnl']:+8.2f} | (no position)")
            agg[(lp["tf"], "none")][0] += 1; agg[(lp["tf"], "none")][1] += lp["pnl"]
            continue
        used.add(best[1]); vp = results[v]["closed"][best[1]]
        sgn = 1 if lp["side"] == "Buy" else -1
        print(f"{fmt_ts(lp['open_ts']):15s} {lp['side']:4s} {lp['tf']:3d} {lp['cls']:7s} {lp['reason']:9s} {lp['pnl']:+8.2f} | {fmt_ts(vp['open_ts']):15s} {vp['tf']:3d} {vp['rule']:14s} {vp['reason']:9s} {vp['pnl']:+8.2f} {best[0]/60000:+6.1f} {sgn*(vp['entry']-lp['entry']):+8.4f}")
        key = (lp["tf"], f"tf{vp['tf']}")
        agg[key][0] += 1; agg[key][1] += lp["pnl"]; agg[key][2] += vp["pnl"]
    for (tf, to), (n, a, b) in sorted(agg.items()):
        print(f"  live tf{tf} -> {to:6s} n={n:2d} pnl live {a:+8.2f} {v} {b:+8.2f} delta {b-a:+8.2f}")

# ---- fire keys that differ between live and r1 / r2
if "live" in results:
    for v in ("r1", "r2"):
        if v not in results:
            continue
        L = [(f["ts"], f["side"], f["tf"], round(f["zone"], 6)) for f in results["live"]["fires"]]
        V = [(f["ts"], f["side"], f["tf"], round(f["zone"], 6)) for f in results[v]["fires"]]
        lz = {(s_, t, z) for _, s_, t, z in L}; vz = {(s_, t, z) for _, s_, t, z in V}
        print(f"\nFIRE KEYS live vs {v}: live {len(L)} fires on {len(lz)} (side, tf, zone) keys; {v} {len(V)} fires on {len(vz)} keys; "
              f"common keys {len(lz & vz)}, only live {len(lz - vz)}, only {v} {len(vz - lz)}")
        lt = {k: ts for ts, s_, t, z in L for k in [(s_, t, z)]}; vt = {k: ts for ts, s_, t, z in V for k in [(s_, t, z)]}
        lags = [(vt[k] - lt[k]) / 60000 for k in lz & vz]
        if lags:
            print(f"  fire delay {v} - live on common keys (min): median {np.median(lags):+.1f}, min {min(lags):+.1f}, max {max(lags):+.1f}; "
                  f"same minute {sum(1 for x in lags if abs(x) < 1)}, later by > 1 min {sum(1 for x in lags if x >= 1)}")

# ---- paired block bootstrap of the variant difference (positions binned by 6-h block of their open time; blocks resampled)
if "live" in results:
    BLOCK = 6 * 3600_000
    blocks = np.arange(T0 // BLOCK, T_END // BLOCK + 1)
    def block_net(res):
        out = np.zeros(len(blocks))
        for p in res["closed"]:
            out[int(p["open_ts"] // BLOCK - blocks[0])] += p["pnl"]
        return out
    rng = np.random.default_rng(1)
    nets = {name: block_net(res) for name, res in results.items()}
    print(f"\nPAIRED 6-H BLOCK BOOTSTRAP vs live ({len(blocks)} blocks, 5000 resamples)")
    for name in results:
        if name == "live":
            continue
        d = nets[name] - nets["live"]
        boot = np.array([d[rng.integers(0, len(d), len(d))].sum() for _ in range(5000)])
        print(f"  {name} - live: delta {d.sum():+.0f}, 90 % CI [{np.percentile(boot, 5):+.0f}, {np.percentile(boot, 95):+.0f}], "
              f"P(delta<0) {np.mean(boot < 0):.2f}; blocks where {name} > live {int(np.sum(d > 0))}, < live {int(np.sum(d < 0))}, equal {int(np.sum(d == 0))}")
    print("\nPER-DAY NET (UTC day of the opening fire)")
    days = sorted({int(p["open_ts"] // 86_400_000) for res in results.values() for p in res["closed"]})
    print("| day | " + " | ".join(f"{n} n / net" for n in results) + " |")
    print("|---|" + "---|" * len(results))
    for d in days:
        cells = []
        for n, res in results.items():
            ps = [p for p in res["closed"] if int(p["open_ts"] // 86_400_000) == d]
            cells.append(f"{len(ps)} / {sum(p['pnl'] for p in ps):+.0f}")
        print(f"| {dt.datetime.fromtimestamp(d * 86400, dt.timezone.utc).strftime('%m-%d')} | " + " | ".join(cells) + " |")
    # the 30 keys that only fire in live (rule-2-only zones): what did they earn as positions?
    if "r1" in results:
        r1keys = {(f["side"], f["tf"], round(f["zone"], 6)) for f in results["r1"]["fires"]}
        only = [p for p in results["live"]["closed"] if (p["side"], p["tf"], round(p["zone"], 6)) not in r1keys]
        s_ = stats(only)
        print("\nLIVE POSITIONS ON ZONES THAT NEVER FIRE IN r1 (rule-2-only zones)")
        print(HEADER); print(row("live rule2-only zones", s_) if s_["n"] else "| none | 0 |")
        for p in only:
            print(f"  {fmt_ts(p['open_ts'])} {p['side']:4s} tf{p['tf']:<3d} {p['rule']:14s} cls {p['cls']:7s} {p['reason']:9s} {p['pnl']:+8.2f}")
