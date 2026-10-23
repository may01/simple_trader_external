#!/usr/bin/env python3
"""Counterfactual replay: the stop-out -> same-side re-entry-at-a-better-price pattern and five candidate fixes.

Question (user, 2026-10-21): two CB zone trades close together -- the first is stopped out at the start of the zone,
the second opens a few minutes later from a better price. How often, what does it cost, how to fix it.

Data, ports and the simulator are the rule2-removal harness (2026-10-21-rule2-removal-replay.py, cb-candle-stop @
a6a5bc6), unchanged; this script adds per-variant knobs and a pair detector on the simulated positions:

  cooldown   after a stop-out, same-side fires for N min are rejected at the decision layer (fire consumed, no position)
  stop_mult  the candle stop's offset (trailing mean 1-min range) multiplied by k
  anchor     'forming' = live (forming 15-min extreme); 'two' = previous closed 15-min candle + forming;
             'roll15' = the last 15 closed 1-min bars + forming
  depth      a candidate needs the price d x offset beyond the zone line (long: price <= zone - d*off)
  skip_min   no fire in the first K minutes of a 15-min candle (deferred, the zone stays unfired)
  half_first the first entry after flat is sized x0.5; a same-side re-entry within 60 min of a stop-out is full size

Pair = consecutive simulated positions P1 (stop) -> P2 (same side, opened <= W min after P1's close, entry better
than P1's entry).
"""
import json, sys, datetime as dt
from collections import defaultdict, Counter
import numpy as np
from cci_lib import CciFeed

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

BASE = dict(rules=("in_zone", "zone_rejection"), cooldown=0, stop_mult=1.0, anchor="forming", depth=0.0, skip_min=0, half_first=False, zone_stop=None, cci=None)
def V(**kw):
    d = dict(BASE); d.update(kw); return d
VARIANTS = {
    "live":   V(),
    "cd5":    V(cooldown=5),
    "cd15":   V(cooldown=15),
    "cd30":   V(cooldown=30),
    "sm15":   V(stop_mult=1.5),
    "sm20":   V(stop_mult=2.0),
    "sm25":   V(stop_mult=2.5),
    "sm30":   V(stop_mult=3.0),
    "anc2":   V(anchor="two"),
    "roll15": V(anchor="roll15"),
    "dp05":   V(depth=0.5),
    "dp10":   V(depth=1.0),
    "skip3":  V(skip_min=3),
    "skip5":  V(skip_min=5),
    "half":   V(half_first=True),
    "zs":     V(zone_stop="bound"),
    "zsw":    V(zone_stop="wider"),
    "zsw15":  V(zone_stop="wider", stop_mult=1.5),
}
NEAR = {"Buy": "low", "Sell": "high"}
for _tfc in (5, 15):
    for _X in (100, 140):
        VARIANTS[f"cci{_tfc}_skip{_X}"] = V(cci=dict(tf=_tfc, X=_X, mode="skip"))
        for _d in (0.5, 1.0, 2.0):
            VARIANTS[f"cci{_tfc}_wait{_X}_d{_d}"] = V(cci=dict(tf=_tfc, X=_X, mode="wait", delta=_d, W=15))
VARIANTS["cci5_band"] = V(cci=dict(tf=5, mode="band", lo=0, hi=100))   # in-sample ablation only
VARIANTS["cci5_band140"] = V(cci=dict(tf=5, mode="band", lo=-140, hi=140))
VARIANTS["cci15_band140"] = V(cci=dict(tf=15, mode="band", lo=-140, hi=140))
VARIANTS["cci5+15_band140"] = V(cci=dict(tf=5, tf2=15, mode="band", lo=-140, hi=140))
VARIANTS["cci5_band100"] = V(cci=dict(tf=5, mode="band", lo=-100, hi=100))
for _b5 in (None, 100, 140, 200):
    for _b15 in (None, 100, 140, 200):
        if _b5 is None and _b15 is None: continue
        bands = {}
        if _b5: bands[5] = (-_b5, _b5)
        if _b15: bands[15] = (-_b15, _b15)
        VARIANTS[f"b5_{_b5 or 'x'}_b15_{_b15 or 'x'}"] = V(cci=dict(mode="bands", bands=bands))
for _tfc in (5, 15):
    for _W in (15, 30):
        VARIANTS[f"cciwait{_tfc}_140to100_W{_W}"] = V(cci=dict(tf=_tfc, X=140, mode="waitcci", X2=100, W=_W))
        VARIANTS[f"cciwait{_tfc}_140to0_W{_W}"] = V(cci=dict(tf=_tfc, X=140, mode="waitcci", X2=0, W=_W))
for _tfc in (5, 15):
    VARIANTS[f"cci{_tfc}_skip_lowtail"] = V(cci=dict(mode="skipband", tf=_tfc, lo=-140, hi=-100))
    VARIANTS[f"cci{_tfc}_skip_below140"] = V(cci=dict(mode="skipband", tf=_tfc, lo=-1e9, hi=-140))
for _p in (0.15, 0.3):
    for _seed in range(8):
        VARIANTS[f"rand{int(_p*100)}_s{_seed}"] = V(cci=dict(mode="rand", p=_p, seed=_seed))
VARIANTS["cci15_band100"] = V(cci=dict(tf=15, mode="band", lo=-100, hi=100))
VARIANTS["wait_all_d1.0"] = V(cci=dict(tf=5, X=-1e9, mode="wait", delta=1.0, W=15))   # every fire becomes a limit 1 range deeper
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
def candle_stop(i, side, price, mult=1.0, mode="forming"):
    ts = T_TS[i]
    m_now = ts // 60_000
    if mode == "forming":
        m_anchor = (ts // ANCHOR_MS) * ANCHOR_MS // 60_000
    elif mode == "two":
        m_anchor = (ts // ANCHOR_MS) * ANCHOR_MS // 60_000 - 15
    else:
        m_anchor = m_now - 15
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
    offset = float(rng.mean()) * mult
    stop = anchor - offset if side == "Buy" else anchor + offset
    adverse = stop < price if side == "Buy" else stop > price
    if not adverse:
        return None
    return stop, anchor, offset

def mean_range_at(i):
    k_now = np.searchsorted(MIN_U, T_TS[i] // 60_000, "left")
    if k_now == 0:
        return float("nan")
    return float(MIN_RANGE[max(0, k_now - RANGE_CANDLES):k_now].mean())

CCI = CciFeed(T_TS, T_PX)
RNG = {n: np.random.default_rng(v["cci"]["seed"]) for n, v in VARIANTS.items() if v.get("cci") and v["cci"].get("mode") == "rand"}

# ---------------------------------------------------------------- the check + the position layer
def simulate(name, prm, verbose=False):
    pending = None
    rules = prm["rules"]
    entry_win = {15: 6, 60: 6, 240: 6}; exit_win = entry_win
    fired = {}
    last_fired = None
    bal = START_BAL
    pos = None
    closed = []
    fires = []
    skipped_same = 0; contradictions = 0; deferred = 0; cooled = 0; depth_block = 0; skip_block = 0; cci_skip = 0; cci_wait = 0; cci_fill = 0; cci_expire = 0
    last_stop = {}   # side -> (close_ts, position)

    def open_pos(fire, i):
        nonlocal pos
        entry = fire["price"]
        cs = candle_stop(i, fire["side"], entry, prm["stop_mult"], prm["anchor"])
        if cs is None:
            stop = entry * (1 - PLACEHOLDER) if fire["side"] == "Buy" else entry * (1 + PLACEHOLDER)
            kind, anchor, offset = "placeholder", None, None
        else:
            stop, anchor, offset = cs; kind = "candle"
        if prm["zone_stop"]:
            near = float(ind_at(f"{fire['tf']}_cbnc_{NEAR[fire['side']]}", i))
            off = (offset if offset is not None else mean_range_at(i) * prm["stop_mult"])
            bstop = near - off if fire["side"] == "Buy" else near + off
            b_adv = bstop < entry if fire["side"] == "Buy" else bstop > entry
            if b_adv and (prm["zone_stop"] == "bound" or (fire["side"] == "Buy" and bstop < stop) or (fire["side"] == "Sell" and bstop > stop)):
                stop, kind, anchor = bstop, "bound", near
        dist = abs(entry - stop)
        size = min(RISK / dist, bal * MAX_NOTIONAL_FRAC / entry)
        reentry = False
        ls = last_stop.get(fire["side"])
        if ls is not None and fire["ts"] - ls[0] <= 60 * 60_000:
            sgn = 1 if fire["side"] == "Buy" else -1
            reentry = (entry - ls[1]["entry"]) * sgn < 0
        if prm["half_first"] and not reentry:
            size *= 0.5
        pos = dict(side=fire["side"], entry=entry, stop=stop, stop_kind=kind, anchor=anchor, offset=offset, target=fire["target"],
                   size=size, open_ts=fire["ts"], extreme=None, tf=fire["tf"], rule=fire["rule"], cls=fire["cls"], armed=False, dist=dist,
                   zone=fire["zone"], fire_i=i, reentry=reentry)

    def close_pos(price, ts, reason):
        nonlocal pos, bal
        sgn = 1 if pos["side"] == "Buy" else -1
        pnl = (price - pos["entry"]) * pos["size"] * sgn
        bal += pnl
        pos.update(exit=price, close_ts=ts, reason=reason, pnl=pnl, fee=FEE * pos["size"] * (pos["entry"] + price))
        closed.append(pos)
        if reason == "stop":
            last_stop[pos["side"]] = (ts, pos)
        pos = None

    for i in range(I0, I_END):
        ts = int(T_TS[i]); px = T_PX[i]; j = i - I0
        if ANY_PRE[j]:
            tr_ = trend_at(i)
            if tr_ is not None:
                cands = []
                off = mean_range_at(i) if prm["depth"] > 0 else 0.0
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
                        if prm["depth"] > 0 and off == off:
                            sgn = 1 if side == "Buy" else -1
                            if (zone - px) * sgn < prm["depth"] * off:
                                depth_block += 1
                                continue
                        cands.append(dict(tf=tf, side=side, zone=zone, rule="in_zone" if r1 else "zone_rejection",
                                          target=float(ind_at(f"{tf}_cbnc_{FAR[side]}", i)), cls=cls))
                if cands and prm["skip_min"] > 0 and (ts // 60_000) % 15 < prm["skip_min"]:
                    skip_block += 1
                    cands = []
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
                        ls = last_stop.get(best["side"])
                        gate = None
                        if prm["cci"]:
                            cc = prm["cci"]; adv = CCI.at(i, cc.get("tf", 15)) * (1 if best["side"] == "Sell" else -1)
                            fire["adv"] = adv
                            if cc["mode"] == "skipband":
                                gate = "skip" if (cc["lo"] <= adv < cc["hi"]) else None
                            elif cc["mode"] == "bands":
                                inb = True
                                for _tf, (_lo, _hi) in cc["bands"].items():
                                    _a = CCI.at(i, _tf) * (1 if best["side"] == "Sell" else -1)
                                    inb = inb and (_lo <= _a < _hi)
                                gate = None if inb else "skip"
                            elif cc["mode"] == "rand":
                                gate = "skip" if RNG[name].random() < cc["p"] else None
                            elif cc["mode"] == "band":
                                inb = cc["lo"] <= adv < cc["hi"]
                                if cc.get("tf2"):
                                    adv2 = CCI.at(i, cc["tf2"]) * (1 if best["side"] == "Sell" else -1)
                                    inb = inb and (cc["lo"] <= adv2 < cc["hi"])
                                gate = None if inb else "skip"
                            elif adv == adv and adv >= cc["X"]:
                                gate = cc["mode"]
                        pending = None   # a new decision supersedes a waiting limit
                        if gate == "skip":
                            cci_skip += 1; fire["outcome"] = "cci_skip"
                        elif gate == "waitcci":
                            pending = dict(fire=fire, limit=None, exp=ts + cc["W"] * 60_000, cci=cc)
                            cci_wait += 1; fire["outcome"] = "cci_wait"
                        elif gate == "wait":
                            off = mean_range_at(i)
                            lim = px - cc["delta"] * off if best["side"] == "Buy" else px + cc["delta"] * off
                            pending = dict(fire=fire, limit=lim, exp=ts + cc["W"] * 60_000)
                            cci_wait += 1; fire["outcome"] = "cci_wait"
                        elif prm["cooldown"] > 0 and ls is not None and ts - ls[0] < prm["cooldown"] * 60_000:
                            cooled += 1; fire["outcome"] = "cooldown"
                        elif pos is None:
                            open_pos(fire, i); fire["outcome"] = "open"
                        elif pos["side"] == fire["side"]:
                            skipped_same += 1; fire["outcome"] = "skip_same"
                        else:
                            close_pos(px, ts, "reversal"); open_pos(fire, i); fire["outcome"] = "reversal"
                        fires.append(fire)
                        continue
        if pending is not None:
            if ts > pending["exp"]:
                pending = None; cci_expire += 1
            else:
                f0 = pending["fire"]
                if pending.get("limit") is None:
                    _cc = pending["cci"]
                    _adv = CCI.at(i, _cc["tf"]) * (1 if f0["side"] == "Sell" else -1)
                    crossed = _adv == _adv and _adv < _cc["X2"]
                else:
                    crossed = (f0["side"] == "Buy" and px <= pending["limit"]) or (f0["side"] == "Sell" and px >= pending["limit"])
                if crossed:
                    fire = dict(f0, ts=ts, i=i, price=px, outcome="cci_fill")
                    pending = None; cci_fill += 1
                    if pos is None:
                        open_pos(fire, i)
                    elif pos["side"] == fire["side"]:
                        skipped_same += 1; fire["outcome"] = "cci_fill_skip_same"
                    else:
                        close_pos(px, ts, "reversal"); open_pos(fire, i); fire["outcome"] = "cci_fill_reversal"
                    fires.append(fire)
                    continue
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
    return dict(name=name, closed=closed, fires=fires, skipped_same=skipped_same, contradictions=contradictions, deferred=deferred,
                cooled=cooled, depth_block=depth_block, skip_block=skip_block, cci_skip=cci_skip, cci_wait=cci_wait, cci_fill=cci_fill, cci_expire=cci_expire)

# ---------------------------------------------------------------- reporting
def stats(closed):
    if not closed:
        return dict(n=0)
    pnl = np.array([p["pnl"] for p in closed]); fee = np.array([p["fee"] for p in closed])
    wins = pnl[pnl > 0]; losses = pnl[pnl < 0]
    hold = np.array([(p["close_ts"] - p["open_ts"]) / 60000 for p in closed])
    risk = np.array([p["size"] * p["dist"] for p in closed])
    rng = np.random.default_rng(0)
    boot = np.array([rng.choice(pnl, len(pnl), replace=True).sum() for _ in range(5000)])
    reasons = defaultdict(lambda: [0, 0.0])
    for p in closed:
        reasons[p["reason"]][0] += 1; reasons[p["reason"]][1] += p["pnl"]
    return dict(n=len(closed), net=pnl.sum(), gw=wins.sum(), nw=len(wins), gl=losses.sum(), nl=len(losses),
                wr=len(wins) / len(closed), pf=(wins.sum() / abs(losses.sum())) if len(losses) else float("inf"),
                hold_med=float(np.median(hold)), risk_med=float(np.median(risk)),
                ci=(np.percentile(boot, 5), np.percentile(boot, 95)), pneg=float(np.mean(boot < 0)),
                net_fee=(pnl - fee).sum(), reasons=dict(reasons))

def pairs_of(closed, W):
    out = []
    for k, p1 in enumerate(closed[:-1]):
        if p1["reason"] != "stop":
            continue
        p2 = closed[k + 1]
        sgn = 1 if p1["side"] == "Buy" else -1
        gap = (p2["open_ts"] - p1["close_ts"]) / 60000
        if p2["side"] == p1["side"] and gap <= W and (p2["entry"] - p1["entry"]) * sgn < 0:
            out.append((p1, p2, gap))
    return out

def row(label, st, pr=None):
    if st["n"] == 0:
        return f"| {label} | 0 |"
    r = st["reasons"]
    def rr(k):
        return f"{r[k][0]}" if k in r else "0"
    pc = ""
    if pr is not None:
        m = len(pr); l1 = sum(p1["pnl"] for p1, _, _ in pr); l2 = sum(p2["pnl"] for _, p2, _ in pr)
        pc = f" {m} ({m / max(r['stop'][0] if 'stop' in r else 1, 1):.0%}) | {l1:+.0f} | {l2:+.0f} |"
    return (f"| {label} | {st['n']} | {st['net']:+.0f} | {st['net_fee']:+.0f} | {st['pf']:.2f} | {st['wr']:.0%} | "
            f"{rr('stop')} / {r['stop'][1]/r['stop'][0] if 'stop' in r else 0:+.0f} | {rr('target')} | {rr('reversal')} | "
            f"{st['hold_med']:.1f} | {st['risk_med']:.0f} | [{st['ci'][0]:+.0f}, {st['ci'][1]:+.0f}] | {st['pneg']:.2f} |" + pc)

HEADER = ("| variant | trades | net | net −0.1 %/side fee | PF | win rate | stop-outs n / mean | targets | reversals | "
          "median hold min | median risk | 90 % CI | P(net<0) | pairs W15 (of stops) | P1 loss | P2 pnl |\n"
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")

# ---------------------------------------------------------------- run
results = {}
for name, v in VARIANTS.items():
    results[name] = simulate(name, v)
    r = results[name]
    print(f"simulated {name}: {len(r['fires'])} fires, {len(r['closed'])} positions, cooled {r['cooled']}, depth-blocked ticks {r['depth_block']}, "
          f"skip-blocked ticks {r['skip_block']}, cci skip/wait/fill/expire {r['cci_skip']}/{r['cci_wait']}/{r['cci_fill']}/{r['cci_expire']}, trend cache {len(_trend_cache)}", flush=True)

# ---- reproduction gate
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
    print(f"\nREPRODUCTION (live variant vs recorded fires, same side+tf within {MATCH_MS//1000} s): recorded {len(rec)}, simulated {len(sim)}, "
          f"matched {len(matched)}, missed {len(missed)}, extra {len(sim) - len(matched)}")
    cs = [(e, f) for e, f in matched if e["anchor"] is not None and abs(f["ts"] - e["ts"]) < 1]
    if cs:
        ok = 0
        for e, f in cs:
            r_ = candle_stop(f["i"], e["side"], e["price"])
            ok += int(r_ is not None and abs(e["stop"] - r_[0]) < 5e-4)
        print(f"  candle-stop port: {ok}/{len(cs)} recorded stops reproduced within half a tick")
    # recorded pairs vs sim-live pairs in the candle-stop era
    ERA = 1792527900000
    act = sorted([a for a in actual.values() if a["open_ts"] >= max(ERA, T0) and a["entry"] and a["pnl"] is not None], key=lambda a: a["open_ts"])
    for a in act:
        a["open_ts"] = a["open_ts"]; a.setdefault("reason", a["reason"])
    ap = pairs_of([dict(a, close_ts=a["close_ts"]) for a in act], 15)
    sp = pairs_of([p for p in results["live"]["closed"] if p["open_ts"] >= max(ERA, T0)], 15)
    print(f"  candle-stop era: recorded positions {len(act)} net {sum(a['pnl'] for a in act):+.0f}, pairs W15 {len(ap)} (P1 {sum(p1['pnl'] for p1,_,_ in ap):+.0f}, P2 {sum(p2['pnl'] for _,p2,_ in ap):+.0f}); "
          f"sim-live positions {sum(1 for p in results['live']['closed'] if p['open_ts'] >= max(ERA, T0))} net {sum(p['pnl'] for p in results['live']['closed'] if p['open_ts'] >= max(ERA, T0)):+.0f}, "
          f"pairs W15 {len(sp)} (P1 {sum(p1['pnl'] for p1,_,_ in sp):+.0f}, P2 {sum(p2['pnl'] for _,p2,_ in sp):+.0f})")

print("\nSUMMARY (same simulator, same window for every variant; pairs = stop -> same side better re-entry within 15 min)")
print(HEADER)
S = {}
for name, res in results.items():
    S[name] = stats(res["closed"])
    print(row(name, S[name], pairs_of(res["closed"], 15)))
print("\nPAIR STATS ON LIVE SIM BY WINDOW")
for W in (5, 15, 30, 60):
    pr = pairs_of(results["live"]["closed"], W)
    nst = sum(1 for p in results["live"]["closed"] if p["reason"] == "stop")
    if pr:
        l1 = sum(p1["pnl"] for p1, _, _ in pr); l2 = sum(p2["pnl"] for _, p2, _ in pr)
        imp = [abs(p2["entry"] - p1["entry"]) / p1["dist"] for p1, p2, _ in pr]
        beyond = sum(1 for p1, p2, _ in pr if (p2["entry"] - p1["stop"]) * (1 if p1["side"] == "Buy" else -1) < 0)
        print(f"  W<={W:2d}: pairs {len(pr)} of {nst} stop-outs ({len(pr)/nst:.0%}); P1 {l1:+.0f} (mean {l1/len(pr):+.0f}), P2 {l2:+.0f} (mean {l2/len(pr):+.0f}), "
              f"P2 outcomes {dict(Counter(p2['reason'] for _, p2, _ in pr))}; Δentry/P1 stop-dist median {np.median(imp):.2f}, P2 beyond P1 stop {beyond}/{len(pr)}; "
              f"gap median {np.median([g for *_, g in pr]):.1f} min; P2 rule {dict(Counter(p2['rule'] for _, p2, _ in pr))}, P2 tf {dict(Counter(p2['tf'] for _, p2, _ in pr))}")
# analytic half-size: live positions with reentry flag
lv = results["live"]["closed"]
re_pnl = sum(p["pnl"] for p in lv if p["reentry"]); n_re = sum(1 for p in lv if p["reentry"])
print(f"  live sim: re-entry-flagged positions {n_re}, pnl {re_pnl:+.0f}; others {len(lv)-n_re}, pnl {S['live']['net']-re_pnl:+.0f}")

# ---- what the cooldown removes / the stop variants change on the P1s
for v in ("cd5", "cd15", "cd30"):
    if v in results:
        lost = [f for f in results[v]["fires"] if f["outcome"] == "cooldown"]
        print(f"  {v}: fires rejected by cooldown {len(lost)}")

# ---- paired block bootstrap
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
    print(f"  {name:7s} - live: delta {d.sum():+6.0f}, 90 % CI [{np.percentile(boot, 5):+6.0f}, {np.percentile(boot, 95):+6.0f}], "
          f"P(delta<0) {np.mean(boot < 0):.2f}; blocks > {int(np.sum(d > 0))}, < {int(np.sum(d < 0))}, = {int(np.sum(d == 0))}")
print("\nPER-DAY NET (UTC day of the opening fire)")
days = sorted({int(p["open_ts"] // 86_400_000) for res in results.values() for p in res["closed"]})
print("| day | " + " | ".join(f"{n}" for n in results) + " |")
print("|---|" + "---|" * len(results))
for d in days:
    cells = []
    for n, res in results.items():
        ps = [p for p in res["closed"] if int(p["open_ts"] // 86_400_000) == d]
        cells.append(f"{len(ps)} / {sum(p['pnl'] for p in ps):+.0f}")
    print(f"| {dt.datetime.fromtimestamp(d * 86400, dt.timezone.utc).strftime('%m-%d')} | " + " | ".join(cells) + " |")

print("\nPER-TF")
print(HEADER)
for name, res in results.items():
    for tf in TFS:
        cl = [p for p in res["closed"] if p["tf"] == tf]
        s_ = stats(cl)
        print(row(f"{name} tf{tf}", s_, pairs_of(cl, 15)) if s_["n"] else f"| {name} tf{tf} | 0 |")

print("\nPER-SIDE (positions by side)")
print(HEADER)
for name, res in results.items():
    for side in SIDES:
        cl = [p for p in res["closed"] if p["side"] == side]
        s_ = stats(cl)
        print(row(f"{name} {side}", s_, pairs_of(cl, 15)) if s_["n"] else f"| {name} {side} | 0 |")
print("\nPER-SIDE x TF")
print(HEADER)
for name, res in results.items():
    for side in SIDES:
        for tf in TFS:
            cl = [p for p in res["closed"] if p["side"] == side and p["tf"] == tf]
            s_ = stats(cl)
            print(row(f"{name} {side} tf{tf}", s_) if s_["n"] else f"| {name} {side} tf{tf} | 0 |")

if arg("dump", ""):
    out = {}
    for name, res in results.items():
        out[name] = dict(closed=[{k: v for k, v in p.items() if k not in ("extreme", "armed")} for p in res["closed"]],
                         fires=[{k: v for k, v in f.items()} for f in res["fires"]])
    def _conv(o):
        if isinstance(o, (np.bool_, bool)): return bool(o)
        if isinstance(o, np.integer): return int(o)
        if isinstance(o, np.floating): return float(o)
        raise TypeError(type(o))
    json.dump(out, open(arg("dump", ""), "w"), default=_conv)
    print("dumped", arg("dump", ""))
if arg("trades", "") == "1":
    for name, res in results.items():
        print(f"\nTRADES {name}")
        for p in res["closed"]:
            print(f"  {fmt_ts(p['open_ts'])} {p['side']:4s} tf{p['tf']:<3d} {p['rule']:14s} e {p['entry']:.4f} s {p['stop']:.4f} {p['stop_kind']:11s} anchor {p['anchor'] if p['anchor'] is None else round(p['anchor'],4)} size {p['size']:.0f} {p['reason']:11s} x {p['exit']:.4f} {p['pnl']:+6.0f} hold {(p['close_ts']-p['open_ts'])/60000:.1f}")
if arg("pairs", "") == "1":
    for name, res in results.items():
        print(f"\nPAIRS {name} (W15)")
        for p1, p2, g in pairs_of(res["closed"], 15):
            print(f"  {fmt_ts(p1['open_ts'])} {p1['side']:4s} tf{p1['tf']:<3d} e {p1['entry']:.4f} s {p1['stop']:.4f} {p1['pnl']:+6.0f} | +{g:4.1f}m tf{p2['tf']:<3d} {p2['rule']:14s} e {p2['entry']:.4f} s {p2['stop']:.4f} {p2['reason']:8s} {p2['pnl']:+6.0f}")
