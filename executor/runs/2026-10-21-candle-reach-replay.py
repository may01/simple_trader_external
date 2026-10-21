#!/usr/bin/env python3
"""Candle-reach entry gate replayed through the paper executor's rules (2026-10-21; spec
docs/superpowers/experiment/candle_reach_gate.md).

Harness = 2026-10-21-volume-flow-replay.py (rules, ports, simulator, bootstrap, split-half, random-skip band unchanged;
the flow / depletion features replaced by the reach features). Reach quantities at a fire tick t (closed information
only; ATR1 = 1_atr_14_ma_5 rebuilt from the trades as in half_atr_stop: Wilder-14 on the closed 1-min bars, SMA-5, read at
the last closed minute):
  per tf T in 15/60/240, closed candles c (wall-clock keys minute // T, built from the 1-min bars):
    reach_c = (high_c - low_c) / ATR1 at the candle's last minute;  body_c = |close_c - open_c| / ATR1;  eff_c = body / reach
    fc{N}c_T = median reach of the last N closed candles;  fc{N}t_T = median range of the last N closed candles / ATR1 now
    eff_T = median eff of the last 8;  rel_T = fc8c_T / sqrt(T)
  own tf: prog = (minutes since the candle opened + 1) / T;  rem{N}{nm}_a{alpha} = fc x (1 - prog)^alpha;
          dtgt = |cbnc far-bound target - price| / ATR1;  ratio{N}{nm}_a{alpha} = rem / dtgt;  rel{N}{nm} = fc / sqrt(T)
  atr1_rel = ATR1 / median ATR1 over the trailing 1440 closed minutes;  atr1_pct = ATR1 / price x 100
  ladr{H} = rel_H / rel_15 for a tf-15 fire (nan otherwise)
  variant knob vol=dict(skip=[(feature, lo, hi), ...], shift_h=0): the fire is skipped when every listed feature lies in
  [lo, hi); shift_h = 24 reads the reach features 24 h earlier at the same clock time (placebo; dtgt stays the fire's own).
usage: python3 2026-10-21-candle-reach-replay.py <data dir> [--t0=ms] [--t-end=ms] [--variants=a,b] [--frozen=name,name]
"""
import json, sys, datetime as dt
from collections import defaultdict, Counter
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

BASE = dict(rules=("in_zone", "zone_rejection"), cooldown=0, stop_mult=1.0, anchor="forming", depth=0.0, skip_min=0, half_first=False, zone_stop=None, cci=None, vol=None)
def V(**kw):
    d = dict(BASE); d.update(kw); return d
def SK(*conds, shift_h=0):
    return V(vol=dict(skip=list(conds), shift_h=shift_h))
INF = 1e18
VARIANTS = {"live": V()}
NS_P = (4, 8, 16); NORMS_P = ("c", "t"); ALPHAS_P = (0.5, 1.0); KS_P = (0.5, 0.75, 1.0, 1.5)
# primary family: remaining forecast reach below k x the target distance
for _N in NS_P:
    for _nm in NORMS_P:
        for _a in ALPHAS_P:
            for _k in KS_P:
                VARIANTS[f"rem{_N}{_nm}_a{_a}_k{_k}"] = SK((f"ratio{_N}{_nm}_a{_a}", -INF, _k))
# reach threshold (fc below q x sqrt(tf)), chop, dead, eff, ladder
for _N in NS_P:
    for _nm in NORMS_P:
        for _q in (0.5, 0.75, 1.0):
            VARIANTS[f"thr{_N}{_nm}_q{_q}"] = SK((f"rel{_N}{_nm}", -INF, _q))
for _a in (1.3, 1.6):
    for _b in (0.8, 1.0):
        VARIANTS[f"chop_a{_a}_b{_b}"] = SK(("atr1_rel", _a, INF), ("rel8c", -INF, _b))
for _m in (1, 2, 3):
    VARIANTS[f"dead_m{_m}"] = SK(("atr1_pct", -INF, _m * 0.042))
for _e in (0.25, 0.35):
    VARIANTS[f"eff_e{_e}"] = SK(("eff", -INF, _e))
for _h in (60, 240):
    for _r in (1.25, 1.5, 2.0):
        VARIANTS[f"lad{_h}_r{_r}"] = SK((f"ladr{_h}", _r, INF))
# rw control: the primary with the reach forecast replaced by sqrt(tf) (progress x target distance only, no reach information)
for _a in ALPHAS_P:
    for _k in KS_P:
        VARIANTS[f"rw_a{_a}_k{_k}"] = SK((f"ratiorw_a{_a}", -INF, _k))
# mirrors of the N = 8 primary grid and of rw (skip when the candle CAN reach: must not win)
for _nm in NORMS_P:
    for _a in ALPHAS_P:
        for _k in KS_P:
            VARIANTS[f"mir_rem8{_nm}_a{_a}_k{_k}"] = SK((f"ratio8{_nm}_a{_a}", _k, INF))
for _a in ALPHAS_P:
    for _k in KS_P:
        VARIANTS[f"mir_rw_a{_a}_k{_k}"] = SK((f"ratiorw_a{_a}", _k, INF))
# 24-h shifted placebos (reach read a day earlier at the same clock time; own prog and dtgt) of the N = 8 grids + chop / eff / lad
for _nm_, _v in list(VARIANTS.items()):
    if _nm_.startswith(("rem8", "thr8", "chop", "eff", "lad")):
        VARIANTS[f"sh24_{_nm_}"] = V(vol=dict(skip=list(_v["vol"]["skip"]), shift_h=24))
# random-skip placebos
for _p in (0.1, 0.2, 0.3, 0.5):
    for _seed in range(8):
        VARIANTS[f"rand{int(_p*100)}_s{_seed}"] = V(cci=dict(mode="rand", p=_p, seed=_seed))
FROZEN = [x for x in arg("frozen", "").split(",") if x]
for _f in FROZEN:
    assert _f in VARIANTS, f"frozen variant {_f} not in the grid"
ONLY = arg("variants", "")
if ONLY:
    keep = {"live"} | set(ONLY.split(",")) | set(FROZEN) | {"mir_" + f for f in FROZEN} | {"sh24_" + f for f in FROZEN}
    VARIANTS = {k: v for k, v in VARIANTS.items() if k in keep or (k.startswith("rand") and "rand" in keep)}

def fmt_ts(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%m-%d %H:%M:%S")

# ---------------------------------------------------------------- trades
tr = np.loadtxt(f"{D}/trades.csv", delimiter=",", usecols=(0, 1, 2), dtype=np.float64)
T_TS = tr[:, 0].astype(np.int64)
T_PX = tr[:, 1]
T_QTY = tr[:, 2]
T_BUY = np.array([l.rstrip("\n").rsplit(",", 1)[1] == "buy" for l in open(f"{D}/trades.csv")])
assert len(T_BUY) == len(T_TS)
T_SGN = np.where(T_BUY, T_QTY, -T_QTY)
CUM_Q = np.concatenate([[0.0], np.cumsum(T_QTY)])
CUM_S = np.concatenate([[0.0], np.cumsum(T_SGN)])
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


# ---------------------------------------------------------------- reach features at a trade index
# ATR1 = 1_atr_14_ma_5 on the 1-min bars from the trades (same construction as 2026-10-21-half-atr-stop-replay.py)
_prev_close = np.concatenate([[MIN_CLOSE[0]], MIN_CLOSE[:-1]])
_tr = np.maximum(MIN_HIGH - MIN_LOW, np.maximum(np.abs(MIN_HIGH - _prev_close), np.abs(MIN_LOW - _prev_close)))
ATR_P = 14
_atr = np.full(len(_tr), np.nan)
_atr[ATR_P - 1] = _tr[:ATR_P].mean()
for k in range(ATR_P, len(_tr)):
    _atr[k] = (_atr[k - 1] * (ATR_P - 1) + _tr[k]) / ATR_P
ATR1 = np.full(len(_tr), np.nan)
for k in range(ATR_P + 3, len(_atr)):
    ATR1[k] = _atr[k - 4:k + 1].mean()
MIN_OPEN = T_PX[MIN_FIRST]
print(f"ATR1 (1_atr_14_ma_5 from trades): median {np.nanmedian(ATR1):.5f}, p10 {np.nanpercentile(ATR1, 10):.5f}, p90 {np.nanpercentile(ATR1, 90):.5f}; "
      f"ATR1 / price median {np.nanmedian(ATR1 / MIN_CLOSE) * 100:.4f} %; minutes {len(MIN_U)}")
# per-tf candles from the 1-min bars (wall-clock keys); a candle is closed once a later minute exists
CND = {}
for tf in TFS:
    key = MIN_U // tf
    uk, first, cnt = np.unique(key, return_index=True, return_counts=True)
    last = first + cnt - 1
    hi = np.maximum.reduceat(MIN_HIGH, first); lo = np.minimum.reduceat(MIN_LOW, first)
    op = MIN_OPEN[first]; cl = MIN_CLOSE[last]; atr_c = ATR1[last]
    rng_c = hi - lo
    reach = np.where(atr_c > 0, rng_c / atr_c, np.nan); body = np.where(atr_c > 0, np.abs(cl - op) / atr_c, np.nan)
    eff = np.where(reach > 0, body / reach, np.nan)
    CND[tf] = dict(key=uk, rng=rng_c, reach=reach, eff=eff, n=cnt, last=last)
    r = reach[:-1]; r = r[np.isfinite(r)]
    ac = np.corrcoef(r[:-1], r[1:])[0, 1] if len(r) > 10 else float("nan")
    print(f"  tf {tf:3d}: candles {len(uk)} (minutes per candle median {np.median(cnt):.0f}); reach q05/25/50/75/95 "
          + " ".join(f"{np.nanpercentile(reach[:-1], p):.2f}" for p in (5, 25, 50, 75, 95)) + f" (sqrt(tf) {np.sqrt(tf):.1f}); lag-1 autocorr {ac:+.3f}")
NSF = (4, 8, 16); ALPHAS_F = (0.5, 1.0); ATR_MED_MIN = 1440
_feat_cache = {}

def _med(a):
    a = a[np.isfinite(a)]
    return float(np.median(a)) if len(a) else np.nan

def features_at(i, side, tf, target):
    """reach features at trade index i (inclusive) for a fire of the given side / tf / target."""
    key_ = (i, side, tf, target)
    r = _feat_cache.get(key_)
    if r is not None:
        return r
    t = int(T_TS[i]); px = T_PX[i]
    m_now = t // 60_000
    k_now = int(np.searchsorted(MIN_U, m_now, "left"))   # closed minutes = MIN_U[:k_now]
    out = {}
    atr1 = ATR1[k_now - 1] if k_now >= 1 else np.nan
    out["atr1"] = atr1
    med = _med(ATR1[max(0, k_now - ATR_MED_MIN):k_now]) if k_now >= 240 else np.nan
    out["atr1_rel"] = atr1 / med if (med == med and med > 0) else np.nan
    out["atr1_pct"] = atr1 / px * 100.0 if atr1 == atr1 else np.nan
    for T in TFS:
        c = CND[T]; cur = m_now // T
        j = int(np.searchsorted(c["key"], cur, "left"))   # candles with key < cur are closed
        for N in NSF:
            rr = c["reach"][max(0, j - N):j]; rg = c["rng"][max(0, j - N):j]
            fc_c = _med(rr) if len(rr) == N else np.nan
            fc_t = (_med(rg) / atr1) if (len(rg) == N and atr1 == atr1 and atr1 > 0) else np.nan
            out[f"fc{N}c_{T}"] = fc_c; out[f"fc{N}t_{T}"] = fc_t
        ee = c["eff"][max(0, j - 8):j]
        out[f"eff_{T}"] = _med(ee) if len(ee) == 8 else np.nan
        out[f"rel_{T}"] = out[f"fc8c_{T}"] / np.sqrt(T)
    out["prog"] = (m_now - (m_now // tf) * tf + 1.0) / tf
    out["dtgt"] = abs(target - px) / atr1 if (atr1 == atr1 and atr1 > 0 and target == target) else np.nan
    for N in NSF:
        for nm in ("c", "t"):
            fc = out[f"fc{N}{nm}_{tf}"]
            out[f"fc{N}{nm}"] = fc; out[f"rel{N}{nm}"] = fc / np.sqrt(tf)
            for a in ALPHAS_F:
                rem = fc * (max(0.0, 1.0 - out["prog"]) ** a)
                out[f"rem{N}{nm}_a{a}"] = rem; out[f"ratio{N}{nm}_a{a}"] = rem / out["dtgt"] if out["dtgt"] == out["dtgt"] and out["dtgt"] > 0 else np.nan
    for a in ALPHAS_F:
        out[f"ratiorw_a{a}"] = np.sqrt(tf) * (max(0.0, 1.0 - out["prog"]) ** a) / out["dtgt"] if out["dtgt"] == out["dtgt"] and out["dtgt"] > 0 else np.nan
    out["eff"] = out[f"eff_{tf}"]; out["rel"] = out[f"rel_{tf}"]
    for hh in (60, 240):
        out[f"ladr{hh}"] = out[f"rel_{hh}"] / out["rel_15"] if (tf == 15 and out["rel_15"] == out["rel_15"] and out["rel_15"] > 0) else np.nan
    _feat_cache[key_] = out
    return out

def features_shifted(i, side, tf, target, hours):
    t = int(T_TS[i]) - hours * 3600_000
    j = int(np.searchsorted(T_TS, t, "right")) - 1
    if j < 1000:
        return None
    now = features_at(i, side, tf, target); old = features_at(j, side, tf, target)
    f = dict(old); f["dtgt"] = now["dtgt"]
    for N in NSF:
        for nm in ("c", "t"):
            for a in ALPHAS_F:
                f[f"ratio{N}{nm}_a{a}"] = old[f"rem{N}{nm}_a{a}"] / now["dtgt"] if now["dtgt"] == now["dtgt"] and now["dtgt"] > 0 else np.nan
    return f

def vol_gate(cfg, i, side, tf, target):
    f = features_shifted(i, side, tf, target, cfg["shift_h"]) if cfg.get("shift_h") else features_at(i, side, tf, target)
    if f is None:
        return False
    def hit(conds):
        for name, lo, hi in conds:
            v = f.get(name, np.nan)
            if not (v == v) or not (lo <= v < hi):
                return False
        return True
    if hit(cfg["skip"]):
        return True
    if cfg.get("skip_or") and hit(cfg["skip_or"]):
        return True
    if cfg.get("skip_or2") and hit(cfg["skip_or2"]):
        return True
    return False
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
                   zone=fire["zone"], fire_i=i, reentry=reentry, feat=fire.get("feat"))

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
                        fire["feat"] = features_at(i, best["side"], best["tf"], best["target"])
                        if prm["vol"] and vol_gate(prm["vol"], i, best["side"], best["tf"], best["target"]):
                            gate = "skip"
                        if gate is None and prm["cci"]:
                            cc = prm["cci"]; adv = np.nan   # CCI modes not used here (rand only)
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
                            cci_skip += 1; fire["outcome"] = "vol_skip" if prm["vol"] else "cci_skip"
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


# ================================================================ descriptive: features at the fire vs outcome
FEATS = ["atr1_pct", "atr1_rel", "prog", "dtgt", "ratiorw_a0.5", "ratiorw_a1.0"] + [f"fc{N}{nm}" for N in NSF for nm in ("c", "t")] + ["rel8c", "eff", "ladr60", "ladr240"] + \
        [f"ratio{N}{nm}_a{a}" for N in NSF for nm in ("c", "t") for a in ALPHAS_F]
def rank(a):
    o = np.argsort(a, kind="stable"); r = np.empty(len(a)); r[o] = np.arange(len(a))
    # average ties
    s = a[o]; i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and s[j + 1] == s[i]: j += 1
        if j > i: r[o[i:j + 1]] = (i + j) / 2.0
        i = j + 1
    return r
def spearman(x, y):
    m = ~np.isnan(x) & ~np.isnan(y)
    if m.sum() < 5: return float("nan"), float("nan"), int(m.sum())
    rx, ry = rank(x[m]), rank(y[m])
    c = np.corrcoef(rx, ry)[0, 1]
    rng_ = np.random.default_rng(7)
    null = np.array([np.corrcoef(rx, rng_.permutation(ry))[0, 1] for _ in range(2000)])
    return float(c), float(np.mean(np.abs(null) >= abs(c))), int(m.sum())
def auc(x, y):
    m = ~np.isnan(x); x = x[m]; y = y[m].astype(bool)
    if y.sum() == 0 or (~y).sum() == 0: return float("nan")
    r = rank(x); return float((r[y].sum() - y.sum() * (y.sum() - 1) / 2) / (y.sum() * (~y).sum()))
def bins_table(label, X, pnl, R, stop, edges=None, nb=5):
    m = ~np.isnan(X)
    if m.sum() < 10:
        print(f"  {label}: n {m.sum()} (too few)"); return
    x = X[m]; p = pnl[m]; r = R[m]; s = stop[m]
    if edges is None:
        if len(np.unique(x)) <= 3:
            edges = np.unique(x); cats = [(f"={v:g}", x == v) for v in edges]
        else:
            qs = np.quantile(x, np.linspace(0, 1, nb + 1)); qs[-1] += 1e-9
            cats = [(f"[{qs[k]:+.3g},{qs[k+1]:+.3g})", (x >= qs[k]) & (x < qs[k + 1])) for k in range(nb)]
    else:
        cats = [(f"[{a:+g},{b:+g})", (x >= a) & (x < b)) for a, b in zip(edges[:-1], edges[1:])]
    rho, pp, n = spearman(x, p); rhoR, ppR, _ = spearman(x, r); a_ = auc(x, s)
    print(f"  {label}: n {n}, Spearman(x, pnl) {rho:+.3f} (perm P {pp:.2f}), Spearman(x, R) {rhoR:+.3f} (P {ppR:.2f}), AUC(x -> stop-out) {a_:.3f}")
    print(f"    {'bin':>18s} | {'n':>4s} {'stop':>5s} {'net':>7s} {'mean':>6s} {'meanR':>6s} {'PF':>5s}")
    for name, mm in cats:
        if mm.sum() == 0: continue
        pm = p[mm]; w = pm[pm > 0].sum(); l = abs(pm[pm < 0].sum())
        print(f"    {name:>18s} | {mm.sum():4d} {s[mm].mean():5.0%} {pm.sum():+7.0f} {pm.mean():+6.0f} {r[mm].mean():+6.2f} {(w / l if l else float('inf')):5.2f}")

def outcome_arrays(closed):
    pnl = np.array([p["pnl"] for p in closed]); R = np.array([p["pnl"] / (p["size"] * p["dist"]) for p in closed])
    stop = np.array([p["reason"] == "stop" for p in closed]); return pnl, R, stop
if "live" in results:
    lv = [p for p in results["live"]["closed"] if p.get("feat")]
    pnl, R, stop = outcome_arrays(lv)
    print(f"\nFEATURES AT THE FIRE vs OUTCOME — simulated live rule, {len(lv)} positions (stop-outs {stop.mean():.0%}, net {pnl.sum():+.0f})")
    for fn in FEATS:
        X = np.array([p["feat"].get(fn, np.nan) for p in lv], dtype=float)
        bins_table(fn, X, pnl, R, stop)
    print("\n  per tf x side, ratio8c / rel8c / dtgt / prog / atr1_rel:")
    for tf in TFS:
        for side in SIDES:
            sub = [p for p in lv if p["tf"] == tf and p["side"] == side]
            if len(sub) < 10: continue
            p_, R_, s_ = outcome_arrays(sub)
            for fn in ("ratio8c_a0.5", "ratio8c_a1.0", "rel8c", "dtgt", "prog", "atr1_rel"):
                X = np.array([p["feat"].get(fn, np.nan) for p in sub], dtype=float)
                bins_table(f"tf{tf} {side} {fn}", X, p_, R_, s_, nb=3)
    # recorded positions: features at the trade index of the recorded open
    act = sorted([a for a in actual.values() if a["entry"] and a["pnl"] is not None and T0 <= a["open_ts"] <= T_END], key=lambda a: a["open_ts"])
    if act:
        rows_ = []
        for a in act:
            i = int(np.searchsorted(T_TS, a["open_ts"], "right")) - 1
            _tf = int(a["signal_id"].split("_")[2]) if a["signal_id"].count("_") >= 3 and a["signal_id"].split("_")[2].isdigit() else 15
            rows_.append(dict(feat=features_at(i, a["side"], _tf, a["tp"] if a["tp"] else np.nan), pnl=a["pnl"], size=a["size"] or 1.0, dist=abs(a["entry"] - a["stop"]) if a["stop"] else np.nan,
                              reason="stop" if (a["reason"] or "").lower().find("stop") >= 0 else (a["reason"] or "")))
        pnl_a = np.array([r["pnl"] for r in rows_]); R_a = np.array([r["pnl"] / (r["size"] * r["dist"]) if r["dist"] == r["dist"] and r["dist"] > 0 else np.nan for r in rows_])
        stop_a = np.array([r["reason"] == "stop" for r in rows_])
        print(f"\nFEATURES AT THE RECORDED OPEN vs RECORDED PNL — {len(rows_)} recorded positions (stop-outs {stop_a.mean():.0%}, net {pnl_a.sum():+.0f}; close reasons {dict(Counter(a['reason'] for a in act))})")
        for fn in ("ratio8c_a0.5", "ratio8c_a1.0", "rel8c", "dtgt", "prog", "atr1_rel", "atr1_pct", "eff"):
            X = np.array([r["feat"].get(fn, np.nan) for r in rows_], dtype=float)
            bins_table(fn, X, pnl_a, R_a, stop_a)
    # feature distribution at fires vs at random trades (is the fire special?)
    rng_ = np.random.default_rng(3)
    ri = rng_.integers(I0 + 20000, I_END, 400)
    print("\n  feature medians: at the live fires vs 400 random trade ticks (side assigned at random for adv):")
    for fn in ("fc8c", "rel8c", "eff", "atr1_rel", "atr1_pct", "prog"):
        xf = np.array([p["feat"][fn] for p in lv], dtype=float)
        xr = np.array([features_at(int(i), "Buy" if rng_.random() < 0.5 else "Sell", 15, np.nan)[fn] for i in ri], dtype=float)
        print(f"    {fn:>8s}: fires median {np.nanmedian(xf):+.3f} (q25 {np.nanpercentile(xf,25):+.3f}, q75 {np.nanpercentile(xf,75):+.3f}) | random {np.nanmedian(xr):+.3f} (q25 {np.nanpercentile(xr,25):+.3f}, q75 {np.nanpercentile(xr,75):+.3f})")

# ================================================================ split-half: choose on the first half, score on the second
half = blocks[0] + (blocks[-1] - blocks[0] + 1) // 2
first = blocks < half
print(f"\nSPLIT-HALF (blocks {int(first.sum())} first / {int((~first).sum())} second; Δ vs live per half; the variant with the best first-half Δ is the one 'chosen')")
rows_sh = []
for name in results:
    if name == "live" or name.startswith("rand"): continue
    d = nets[name] - nets["live"]
    rows_sh.append((name, d[first].sum(), d[~first].sum(), int(np.sum(d[first] != 0)), int(np.sum(d[~first] != 0))))
rows_sh.sort(key=lambda r: -r[1])
print(f"  {'variant':>24s} | {'Δ first':>8s} {'Δ second':>8s} | blocks changed first/second")
for r in rows_sh[:25]:
    print(f"  {r[0]:>24s} | {r[1]:+8.0f} {r[2]:+8.0f} | {r[3]}/{r[4]}")
pos_first = [r for r in rows_sh if r[1] > 0]
if pos_first:
    agree = sum(1 for r in pos_first if r[2] > 0)
    print(f"  variants with Δ first > 0: {len(pos_first)}, of which Δ second > 0: {agree} ({agree/len(pos_first):.0%}); chosen '{rows_sh[0][0]}' second-half Δ {rows_sh[0][2]:+.0f}")
# reverse direction too
rows_sh2 = sorted(rows_sh, key=lambda r: -r[2])
pos_second = [r for r in rows_sh2 if r[2] > 0]
if pos_second:
    agree = sum(1 for r in pos_second if r[1] > 0)
    print(f"  reverse: Δ second > 0: {len(pos_second)}, of which Δ first > 0: {agree} ({agree/len(pos_second):.0%}); chosen on the second '{rows_sh2[0][0]}' first-half Δ {rows_sh2[0][1]:+.0f}")
# placebo band
rp = {}
for name in results:
    if name.startswith("rand"):
        p_ = name.split("_")[0]; rp.setdefault(p_, []).append(nets[name].sum() - nets["live"].sum())
print("\nRANDOM-SKIP PLACEBO BAND (Δ vs live over 8 seeds): " + "; ".join(f"{k}: mean {np.mean(v):+.0f}, min {np.min(v):+.0f}, max {np.max(v):+.0f}" for k, v in sorted(rp.items())))
# per-variant skip counts + retention
print("\nSKIPS PER VARIANT (fires skipped by the volume gate / positions / Δ net vs live)")
for name, res in results.items():
    if name == "live": continue
    sk = sum(1 for f in res["fires"] if f["outcome"] in ("vol_skip", "cci_skip"))
    print(f"  {name:>24s}: skipped {sk:3d}, positions {len(res['closed']):3d} (live {len(results['live']['closed'])}), Δ {nets[name].sum() - nets['live'].sum():+7.0f}")

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
