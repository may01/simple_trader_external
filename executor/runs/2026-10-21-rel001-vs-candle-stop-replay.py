#!/usr/bin/env python3
"""
Replay: release_001 stop rule vs the running candle stop, over the window since the
2026-10-20 20:21:47Z executor restart ("the pivot": cbov-check recreated on cb-candle-stop a6a5bc6).

  release_001 (1689dc5): stop = order-book walk (cb-book-stop design §6) -- adverse-side volume per minute over
                          the last 300 s of trades x minutes_left (max(E - streak, 0) + 1, E = 15:2 / 60:3 / 240:4),
                          walked against the position from the last trade; must be strictly beyond the trade and
                          the touch; else, or when not adverse to the actual entry, the 1 % placeholder.
  live (a6a5bc6):         stop = forming 15-min extreme -/+ trailing mean 1-min range (60 closed bars) -- taken
                          from the recorded CbZoneEntry event (`stop`); else the 0.2 % placeholder.

Both rules run through the same event-driven simulator (port of the 2026-10-20 sl-15m-anchor replay):
recorded CbZoneEntry fires (incl. the ones the live run skipped), reversal on an opposite-side fire, stop
watcher on every trade, target exit = extreme past `target` then the opposite 10-s trend class, size =
min(100 / dist, free_quote x 0.5 / entry). The order book at each fire is rebuilt from `book_snapshot` +
`book_update` (ins_seq order, qty 0 removes a level), exactly as `BookTracker` does.

Data dir layout (psql COPY exports, see the run report): trades.csv (ord_ts, price, qty, side +-1, recv_ts),
events.jsonl, positions.jsonl, book_snapshots.jsonl, book_updates.jsonl.

usage: python3 THIS.py DATA_DIR [--fill-at-stop] [--book-lag-ms=N]
"""
import json, sys
from collections import defaultdict
import numpy as np

D = sys.argv[1] if len(sys.argv) > 1 else "data"
RISK = 100.0
START_BAL = 100_000.0
MAX_NOTIONAL_FRAC = 0.5
PH_REL = 0.01        # release_001 placeholder
PH_LIVE = 0.002      # live placeholder since 2026-10-20
E_POINTS = {15: 2.0, 60: 3.0, 240: 4.0}
BUFFER_MIN = 1.0
VOL_WINDOW_MS = 300_000
WINDOW_CAP = 6000
BUCKET = 10
MA_WIN = 6
STD_MULT = 0.7
STD_SPAN = 2 * 3600
MIN_BUCKETS = 30
TICK = 0.001
FILL_AT_STOP = "--fill-at-stop" in sys.argv
BOOK_LAG_MS = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--book-lag-ms=")), 0))

# ---------------------------------------------------------------- data
tr = np.loadtxt(f"{D}/trades.csv", delimiter=",", usecols=(0, 1, 2, 3), dtype=np.float64)
T_TS = tr[:, 0].astype(np.int64); T_PX = tr[:, 1]; T_QTY = tr[:, 2]; T_SIDE = tr[:, 3].astype(np.int64)
T_SELL_CUM = np.concatenate([[0.0], np.cumsum(np.where(T_SIDE < 0, T_QTY, 0.0))])
T_BUY_CUM = np.concatenate([[0.0], np.cumsum(np.where(T_SIDE > 0, T_QTY, 0.0))])

events = []
for line in open(f"{D}/events.jsonl"):
    r = json.loads(line); e = r["ev"]
    events.append(dict(ts=int(e["ts"]), side=e["side"], price=float(e["price"]), stop=float(e["stop"]),
                       anchor=float(e.get("stop_anchor") or 0), offset=float(e.get("stop_offset") or 0),
                       target=float(e["target"]), tf=int(e["tf_minutes"]), rule=e["rule"],
                       streak=int(e.get("inzone_streak", 0)), decision_id=r["decision_id"], seq=r["seq"]))
events.sort(key=lambda e: (e["ts"], e["seq"]))

rows = [json.loads(l) for l in open(f"{D}/positions.jsonl")]
by_pid = defaultdict(list)
for r in rows:
    if r["position_id"]:
        by_pid[r["position_id"]].append(r)
actual_list = []
for pid, rs in by_pid.items():
    rs.sort(key=lambda r: r["seq"])
    first, last = rs[0], rs[-1]
    actual_list.append(dict(pid=pid, side="Buy" if first["side"] == "buy" else "Sell", decision_id=first["decision_id"],
                            open_ts=first["recorded_at"], close_ts=last["recorded_at"],
                            entry=float(last["avg_entry_price"]) if last["avg_entry_price"] else None,
                            exit=float(last["avg_exit_price"]) if last["avg_exit_price"] else None,
                            stop=next((float(r["stop_loss_price"]) for r in rs if r["stop_loss_price"]), 0.0),
                            tp=next((float(r["take_profit_price"]) for r in rs if r["take_profit_price"]), 0.0),
                            size=max((float(r["net_size"]) for r in rs if r["net_size"]), default=0.0),
                            pnl=float(last["realized_pnl"]) if last["realized_pnl"] is not None else None,
                            reason=last["close_reason"], status=last["status"]))
actual_list.sort(key=lambda a: a["open_ts"])
# match each live position to its opening fire: same decision id, else (reversal: the open rides a fresh
# decision) the last same-side event within 5 s before the position's first row
actual = {}
by_did = {e["decision_id"]: e for e in events}
for a in actual_list:
    e = by_did.get(a["decision_id"])
    if e is None:
        cands = [e for e in events if e["side"] == a["side"] and 0 <= a["open_ts"] - e["ts"] <= 5000]
        e = cands[-1] if cands else None
    if e is None:
        print("UNMATCHED live position", a["pid"], a["side"], a["open_ts"]); continue
    a["event_seq"] = e["seq"]
    actual[e["seq"]] = a

END_TS = int(T_TS[-1])
T0 = events[0]["ts"]
_gaps = np.diff(T_TS); _big = np.where(_gaps > 60_000)[0]
print(f"trades {len(T_TS)}  window {T_TS[0]} -> {END_TS} ({(END_TS - T_TS[0]) / 3.6e6:.1f} h); feed gaps > 60 s: {len(_big)}",
      [(int(T_TS[i]), int(_gaps[i] // 1000)) for i in _big[:10]])
print(f"events {len(events)}  live positions {len(actual_list)} matched {len(actual)}")

# ---------------------------------------------------------------- order book (BookTracker port)
book_rows = []
for fn, kind in (("book_snapshots.jsonl", "snap"), ("book_updates.jsonl", "upd")):
    for line in open(f"{D}/{fn}"):
        r = json.loads(line)
        ts = r["exchange_ts"] if r["exchange_ts"] is not None else r["recv_ts"]
        book_rows.append((r["ins_seq"], int(ts) + (BOOK_LAG_MS if kind == "upd" else 0), kind,
                          [float(x) for x in r["bp"]], [float(x) for x in r["bq"]],
                          [float(x) for x in r["ap"]], [float(x) for x in r["aq"]]))
book_rows.sort(key=lambda x: x[0])
print(f"book rows {len(book_rows)} (snapshots {sum(1 for b in book_rows if b[2] == 'snap')})")


class Book:
    def __init__(self):
        self.bids = {}; self.asks = {}; self.i = 0; self.ts = 0; self.n_applied = 0

    def advance(self, until_ts):
        """apply every row with ts <= until_ts, in ins_seq order (the executor applies on arrival)"""
        while self.i < len(book_rows) and book_rows[self.i][1] <= until_ts:
            _, ts, kind, bp, bq, ap, aq = book_rows[self.i]
            if kind == "snap":
                self.bids = dict(zip(bp, bq)); self.asks = dict(zip(ap, aq))
            else:
                for p, q in zip(bp, bq):
                    if q == 0: self.bids.pop(p, None)
                    else: self.bids[p] = q
                for p, q in zip(ap, aq):
                    if q == 0: self.asks.pop(p, None)
                    else: self.asks[p] = q
            self.ts = ts; self.i += 1; self.n_applied += 1

    def best(self):
        return (max(self.bids) if self.bids else None, min(self.asks) if self.asks else None)


def adverse_vol_rate(side, i_now):
    """signals::cb_stop::adverse_vol_rate on the count-bounded window ending at trade i_now"""
    now = int(T_TS[i_now]); cutoff = now - VOL_WINDOW_MS
    lo_cap = max(0, i_now - WINDOW_CAP + 1)
    lo = max(lo_cap, int(np.searchsorted(T_TS, cutoff, "left")))
    if lo > i_now:
        return None, "no_trades"
    qty = (T_SELL_CUM[i_now + 1] - T_SELL_CUM[lo]) if side == "Buy" else (T_BUY_CUM[i_now + 1] - T_BUY_CUM[lo])
    if qty <= 0:
        return None, "zero_rate"
    oldest = int(T_TS[lo])
    span = max(min(now - oldest, VOL_WINDOW_MS), 60_000)
    return qty / (span / 60_000), None


def book_stop(side, i_now, price, tf, streak, book):
    rate, why = adverse_vol_rate(side, i_now)
    if rate is None:
        return None, why, dict(rate=None)
    minutes_left = max(E_POINTS[tf] - streak, 0.0) + BUFFER_MIN
    target_qty = rate * minutes_left
    if side == "Buy":
        levels = sorted(((p, q) for p, q in book.bids.items() if p <= price), key=lambda x: -x[0])
    else:
        levels = sorted(((p, q) for p, q in book.asks.items() if p >= price), key=lambda x: x[0])
    cum = 0.0; level = None; walked = 0
    for p, q in levels:
        cum += q; walked += 1
        if cum >= target_qty - 1e-12:
            level = p; break
    info = dict(rate=rate, minutes_left=minutes_left, target_qty=target_qty, levels=len(levels), walked=walked)
    if level is None:
        return None, "depth_exhausted", info
    touch = levels[0][0]
    adverse = (level < price and level < touch) if side == "Buy" else (level > price and level > touch)
    if not adverse:
        return None, "not_adverse", info
    return level, "book", info


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
    slopes = np.diff(ma)
    times = first + BUCKET * np.arange(n)
    in_span = slopes[(times[1:] >= (T_TS[i_now] // 1000 - STD_SPAN))]
    sigma = float(np.sqrt(np.mean((in_span - in_span.mean()) ** 2))) if len(in_span) >= 2 else 0.0
    s = float(slopes[-1]) if n > 1 else None
    band = STD_MULT * sigma
    if s is not None and band > 0 and s > band: return "up", s, sigma
    if s is not None and band > 0 and s < -band: return "down", s, sigma
    return "neutral", s, sigma


# ---------------------------------------------------------------- simulation
def placeholder(side, entry, pct):
    return entry * (1 - pct) if side == "Buy" else entry * (1 + pct)


def adverse_to(side, stop, entry):
    return stop < entry if side == "Buy" else stop > entry


MODES = {
    # name: (stop rule, placeholder pct)
    "live":        ("candle", PH_LIVE),   # the running system (reproduction gate)
    "rel001":      ("book", PH_REL),      # release_001 as it ran before the pivot
    "book_p02":    ("book", PH_LIVE),     # release_001 stop, live placeholder (isolates the stop rule)
    "candle_p1":   ("candle", PH_REL),    # live stop, release placeholder (isolates the placeholder)
}


def simulate(mode, verbose=False):
    rule, ph = MODES[mode]
    bal = START_BAL; pos = None; closed = []; ev_i = 0; skipped_same = 0
    book = Book()
    i_start = int(np.searchsorted(T_TS, T0, "left"))
    i_at_ts = {}  # event ts -> trade index of the firing trade (last trade with ts <= event ts)

    def open_pos(e, at_ts, i_trade):
        nonlocal pos
        a = actual.get(e["seq"])
        entry = a["entry"] if (a and a["entry"]) else e["price"]
        book.advance(e["ts"])
        bb, ba = book.best()
        if rule == "candle":
            stop, kind, info = e["stop"], "candle", {}
        else:
            stop, kind, info = book_stop(e["side"], i_trade, e["price"], e["tf"], e["streak"], book)
        if stop is None or not adverse_to(e["side"], stop, entry):
            kind = "placeholder" if stop is None else f"placeholder({kind}:not_adverse_to_entry)"
            stop = placeholder(e["side"], entry, ph)
        dist = abs(entry - stop)
        size = min(RISK / dist, bal * MAX_NOTIONAL_FRAC / entry)
        pos = dict(side=e["side"], entry=entry, stop=stop, stop_kind=kind, info=info, bb=bb, ba=ba, book_ts=book.ts,
                   target=e["target"], size=size, open_ts=at_ts, extreme=None, tf=e["tf"], seq=e["seq"],
                   decision_id=e["decision_id"], rule=e["rule"], armed=False, dist=dist, streak=e["streak"])

    def close_pos(price, ts, reason):
        nonlocal pos, bal
        sgn = 1 if pos["side"] == "Buy" else -1
        pnl = (price - pos["entry"]) * pos["size"] * sgn
        bal += pnl
        pos.update(exit=price, close_ts=ts, reason=reason, pnl=pnl)
        closed.append(pos); pos = None

    for i in range(i_start, len(T_TS)):
        ts = int(T_TS[i]); px = T_PX[i]
        while ev_i < len(events) and events[ev_i]["ts"] <= ts:
            e = events[ev_i]; ev_i += 1
            # the firing trade: the last trade at or before the event ts
            i_fire = int(np.searchsorted(T_TS, e["ts"], "right")) - 1
            if pos is None:
                open_pos(e, e["ts"], i_fire)
            elif pos["side"] == e["side"]:
                skipped_same += 1
            else:
                close_pos(e["price"], e["ts"], "reversal"); open_pos(e, e["ts"], i_fire)
        if pos is None:
            continue
        if (pos["side"] == "Buy" and px <= pos["stop"]) or (pos["side"] == "Sell" and px >= pos["stop"]):
            close_pos(pos["stop"] if FILL_AT_STOP else px, ts, "stop"); continue
        if pos["extreme"] is None: pos["extreme"] = px
        elif pos["side"] == "Buy": pos["extreme"] = max(pos["extreme"], px)
        else: pos["extreme"] = min(pos["extreme"], px)
        pos["armed"] = pos["extreme"] > pos["target"] if pos["side"] == "Buy" else pos["extreme"] < pos["target"]
        if pos["armed"]:
            r = trend_reading(i)
            if r and ((pos["side"] == "Buy" and r[0] == "down") or (pos["side"] == "Sell" and r[0] == "up")):
                close_pos(px, ts, "target")
    if pos is not None:
        px = float(T_PX[-1]); sgn = 1 if pos["side"] == "Buy" else -1
        pos.update(exit=px, close_ts=END_TS, reason="open_at_end", pnl=(px - pos["entry"]) * pos["size"] * sgn)
        closed.append(pos)
    return closed, skipped_same


def fmt_ts(ms):
    import datetime as dt
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%m-%d %H:%M:%S")


def summarize(name, closed):
    pnl = np.array([p["pnl"] for p in closed]); wins = pnl[pnl > 0]; losses = pnl[pnl < 0]
    by_reason = defaultdict(lambda: [0, 0.0])
    for p in closed:
        by_reason[p["reason"]][0] += 1; by_reason[p["reason"]][1] += p["pnl"]
    hold = np.array([(p["close_ts"] - p["open_ts"]) / 60000 for p in closed])
    print(f"\n=== {name} ===")
    print(f"trades {len(closed)}  net {pnl.sum():+.2f}  gross profit {wins.sum():+.2f} ({len(wins)})  gross loss {losses.sum():+.2f} ({len(losses)})  "
          f"win rate {len(wins) / len(closed):.0%}  PF {wins.sum() / abs(losses.sum()) if len(losses) else float('inf'):.2f}  "
          f"avg hold {hold.mean():.1f} min  median {np.median(hold):.1f}")
    for k, (n, s) in sorted(by_reason.items()):
        print(f"  {k:12s} n={n:3d}  pnl={s:+.2f}")
    risk = np.array([p["size"] * p["dist"] for p in closed]); R = pnl / risk
    rng = np.random.default_rng(0)
    boot = np.array([rng.choice(pnl, len(pnl), replace=True).sum() for _ in range(5000)])
    top = np.sort(pnl)[::-1][:2]
    dist = np.array([p["dist"] for p in closed]); ent = np.array([p["entry"] for p in closed])
    print(f"  risk/trade median {np.median(risk):.1f} USDT (max {risk.max():.1f}); sum R {R.sum():+.1f}, mean R {R.mean():+.2f}; "
          f"net bootstrap 90% CI [{np.percentile(boot, 5):+.0f}, {np.percentile(boot, 95):+.0f}]; P(net<0) {np.mean(boot < 0):.2f}; top-2 trades {top.sum():+.0f}")
    print(f"  stop distance median {np.median(dist):.4f} ({np.median(dist / ent) * 100:.3f} %, {np.median(dist) / TICK:.0f} ticks) min {dist.min():.4f} max {dist.max():.4f}; "
          f"size median {np.median([p['size'] for p in closed]):.0f}; stop source {dict(sorted(((k, sum(1 for p in closed if p['stop_kind'] == k)) for k in set(p['stop_kind'] for p in closed))))}")
    st = [p["pnl"] for p in closed if p["reason"] == "stop"]
    if st:
        print(f"  stop-outs n={len(st)} mean {np.mean(st):+.2f} median {np.median(st):+.2f} worst {min(st):+.2f}")
    return pnl


def transitions(a_name, A, b_name, B):
    pa = {p["seq"]: p for p in A}; pb = {p["seq"]: p for p in B}
    trans = defaultdict(lambda: [0, 0.0, 0.0])
    for s in sorted(set(pa) | set(pb)):
        a = pa.get(s); b = pb.get(s)
        key = (a["reason"] if a else "not_opened", b["reason"] if b else "not_opened")
        trans[key][0] += 1; trans[key][1] += a["pnl"] if a else 0.0; trans[key][2] += b["pnl"] if b else 0.0
    print(f"\nTRANSITIONS {a_name} -> {b_name} (same opening fire)")
    for k, (n, x, y) in sorted(trans.items()):
        print(f"  {k[0]:11s} -> {k[1]:11s} n={n:2d}  pnl {a_name} {x:+8.2f}  {b_name} {y:+8.2f}  delta {y - x:+8.2f}")
    # paired bootstrap on the per-fire delta
    seqs = sorted(set(pa) | set(pb))
    d = np.array([(pb[s]["pnl"] if s in pb else 0.0) - (pa[s]["pnl"] if s in pa else 0.0) for s in seqs])
    rng = np.random.default_rng(1)
    boot = np.array([rng.choice(d, len(d), replace=True).sum() for _ in range(5000)])
    print(f"  paired delta sum {d.sum():+.2f} over {len(d)} fires; bootstrap 90% CI [{np.percentile(boot, 5):+.0f}, {np.percentile(boot, 95):+.0f}]; P(delta<0) {np.mean(boot < 0):.2f}")
    # by half / by tf / by side
    mid = seqs[len(seqs) // 2]
    for lab, sel in (("first half", [s for s in seqs if s < mid]), ("second half", [s for s in seqs if s >= mid])):
        dd = [(pb[s]["pnl"] if s in pb else 0.0) - (pa[s]["pnl"] if s in pa else 0.0) for s in sel]
        print(f"  {lab}: n={len(sel)} delta {sum(dd):+.2f}")
    for tf in (15, 60, 240):
        sel = [s for s in seqs if (pa.get(s) or pb.get(s))["tf"] == tf]
        if sel:
            dd = [(pb[s]["pnl"] if s in pb else 0.0) - (pa[s]["pnl"] if s in pa else 0.0) for s in sel]
            print(f"  tf {tf}: n={len(sel)} {a_name} {sum(pa[s]['pnl'] for s in sel if s in pa):+.2f} {b_name} {sum(pb[s]['pnl'] for s in sel if s in pb):+.2f} delta {sum(dd):+.2f}")


if __name__ == "__main__":
    act = [a for a in actual_list if a["entry"] is not None and a["status"] == "closed"]
    act_pnl = sum(a["pnl"] or 0 for a in act)
    print(f"\nACTUAL recorded (live candle stop): positions {len(act)}  net {act_pnl:+.2f}  "
          f"stop {sum(1 for a in act if a['reason'] == 'stop')} ({sum(a['pnl'] for a in act if a['reason'] == 'stop'):+.2f})  "
          f"target {sum(1 for a in act if a['reason'] == 'target')} ({sum(a['pnl'] for a in act if a['reason'] == 'target'):+.2f})  "
          f"main_close {sum(1 for a in act if a['reason'] == 'main_close')} ({sum(a['pnl'] for a in act if a['reason'] == 'main_close'):+.2f})  "
          f"open {sum(1 for a in actual_list if a['status'] != 'closed')}")
    res = {m: simulate(m) for m in MODES}
    print(f"\nplaceholder release {PH_REL * 100:.1f} % / live {PH_LIVE * 100:.1f} %; fill model: "
          f"{'stop fills AT the stop level' if FILL_AT_STOP else 'stop fills at the crossing trade price'}; book lag {BOOK_LAG_MS} ms")
    P = {}
    P["live"] = summarize("SIM live: candle stop (recorded) + 0.2 % placeholder  [reproduction of the running system]", res["live"][0])
    P["rel001"] = summarize("SIM release_001: order-book stop (rebuilt) + 1 % placeholder", res["rel001"][0])
    P["book_p02"] = summarize("SIM book stop + 0.2 % placeholder (stop rule only)", res["book_p02"][0])
    P["candle_p1"] = summarize("SIM candle stop + 1 % placeholder (placeholder only)", res["candle_p1"][0])
    print("\nsame-side fires skipped:", {m: res[m][1] for m in MODES})

    # ---- reproduction gate: sim live vs actual
    print("\nREPRODUCTION: actual vs sim-live per live position (stop, size, reason, pnl)")
    pl = {p["seq"]: p for p in res["live"][0]}
    n_stop_ok = n_size_ok = n_reason_ok = n = 0; sim_on_actual = 0.0
    for a in sorted(act, key=lambda a: a["open_ts"]):
        c = pl.get(a.get("event_seq"))
        if not c:
            print(f"  {fmt_ts(a['open_ts'])} {a['side']:4s} actual pnl {a['pnl']:+8.2f} {a['reason']:10s} | sim: NOT OPENED"); continue
        n += 1; sim_on_actual += c["pnl"]
        ok_stop = abs(a["stop"] - c["stop"]) < 1e-6; ok_size = abs(a["size"] - c["size"]) / max(a["size"], 1) < 0.01
        ok_reason = (a["reason"] == {"stop": "stop", "target": "target", "reversal": "main_close"}.get(c["reason"], c["reason"]))
        n_stop_ok += ok_stop; n_size_ok += ok_size; n_reason_ok += ok_reason
        flag = "" if ok_stop and ok_size and ok_reason else "  <-- differs"
        print(f"  {fmt_ts(a['open_ts'])} {a['side']:4s} tf{c['tf']:<3d} actual stop {a['stop']:.4f} size {a['size']:7.0f} exit {a['exit'] or 0:.4f} pnl {(a['pnl'] or 0):+8.2f} {a['reason'] or '':10s} "
              f"| sim stop {c['stop']:.4f} size {c['size']:7.0f} exit {c['exit']:.4f} pnl {c['pnl']:+8.2f} {c['reason']:10s}{flag}")
    print(f"  matched {n}/{len(act)}: stop exact {n_stop_ok}, size within 1 % {n_size_ok}, same close reason {n_reason_ok}; "
          f"actual net {act_pnl:+.2f} vs sim-live on the same positions {sim_on_actual:+.2f}; sim-live total {P['live'].sum():+.2f}")

    # ---- book reconstruction gate: rebuilt mid at the fire vs the recorded entry (= book mid on the tick grid)
    print("\nBOOK GATE: rebuilt best bid/ask at each live open vs the recorded entry (paper entry = mid rounded to the grid)")
    hits = 0; tot = 0; offs = []
    for p in res["rel001"][0] + [q for q in res["live"][0]]:
        pass
    for p in res["live"][0]:
        a = actual.get(p["seq"])
        if not a or a["entry"] is None or p["bb"] is None or p["ba"] is None:
            continue
        mid = (p["bb"] + p["ba"]) / 2
        off = (a["entry"] - mid) / TICK
        offs.append(off); tot += 1; hits += abs(off) <= 1.0001
    offs = np.array(offs)
    print(f"  {hits}/{tot} entries within 1 tick of the rebuilt mid; |offset| median {np.median(np.abs(offs)):.2f} ticks, max {np.abs(offs).max():.2f}; "
          f"rebuilt spread at fire: median {np.median([p['ba'] - p['bb'] for p in res['live'][0] if p['bb'] and p['ba']]) / TICK:.1f} ticks")

    # ---- the release_001 stop per fire
    print("\nRELEASE_001 STOP PER FIRE (rebuilt book walk)")
    print(f"{'fire':15s} {'side':4s} {'tf':>3s} {'strk':>4s} {'price':>8s} {'bb':>8s} {'ba':>8s} {'rate/min':>8s} {'m_left':>6s} {'tgt_qty':>8s} {'lvls':>4s} {'walk':>4s} {'stop':>8s} {'src':28s} {'dist_t':>6s} | {'live stop':>9s} {'dist_t':>6s}")
    pr = {p["seq"]: p for p in res["rel001"][0]}
    for e in events:
        p = pr.get(e["seq"]); c = pl.get(e["seq"])
        if not p:
            continue
        inf = p["info"]
        ls = f"{c['stop']:9.4f} {c['dist'] / TICK:6.0f}" if c else "   (not opened)"
        print(f"{fmt_ts(e['ts']):15s} {e['side']:4s} {e['tf']:3d} {e['streak']:4d} {e['price']:8.4f} {p['bb'] or 0:8.4f} {p['ba'] or 0:8.4f} "
              f"{(inf.get('rate') or 0):8.1f} {inf.get('minutes_left', 0):6.1f} {inf.get('target_qty', 0):8.0f} {inf.get('levels', 0):4d} {inf.get('walked', 0):4d} "
              f"{p['stop']:8.4f} {p['stop_kind']:28s} {p['dist'] / TICK:6.0f} | {ls}")

    transitions("live", res["live"][0], "rel001", res["rel001"][0])
    transitions("live", res["live"][0], "book_p02", res["book_p02"][0])
    transitions("live", res["live"][0], "candle_p1", res["candle_p1"][0])

    print("\nPER-FIRE (live sim | release_001 sim)")
    print(f"{'open':15s} {'side':4s} {'tf':>3s} {'entry':>8s} | {'stop_l':>8s} {'reason_l':10s} {'pnl_l':>8s} {'hold':>6s} | {'stop_r':>8s} {'src':12s} {'reason_r':10s} {'pnl_r':>8s} {'hold':>6s}")
    for e in events:
        c = pl.get(e["seq"]); p = pr.get(e["seq"])
        if not c and not p:
            continue
        o = c or p
        cs = f"{c['stop']:8.4f} {c['reason']:10s} {c['pnl']:+8.2f} {(c['close_ts'] - c['open_ts']) / 60000:6.1f}" if c else " " * 35 + "(skip)"
        ps = f"{p['stop']:8.4f} {p['stop_kind'][:12]:12s} {p['reason']:10s} {p['pnl']:+8.2f} {(p['close_ts'] - p['open_ts']) / 60000:6.1f}" if p else " " * 48 + "(skip)"
        print(f"{fmt_ts(o['open_ts']):15s} {o['side']:4s} {o['tf']:3d} {o['entry']:8.4f} | {cs} | {ps}")

    print("\nSUMMARY net USDT:", {m: f"{P[m].sum():+.0f}" for m in P},
          f"| release_001 - live = {P['rel001'].sum() - P['live'].sum():+.0f}; stop rule alone (book_p02 - live) = {P['book_p02'].sum() - P['live'].sum():+.0f}; "
          f"placeholder alone (candle_p1 - live) = {P['candle_p1'].sum() - P['live'].sum():+.0f}")
