"""CCI-14 on the 5-/15-min candles built from the executor's trade feed, main/ convention:
input = the last 104 closed tf candles + the forming candle (high/low cummax/cummin, close = last trade <= t),
talib.CCI(timeperiod=14) on those 105 rows (indicators/framework.build_indicator_input, INDICATOR_WINDOW_ROWS=105).
Reproduced against the stored 2y frame to 1e-11 (2y_link_usdt part_00, 300 random rows per tf)."""
import numpy as np, talib

WINDOW = 105
PERIOD = 14

class CciFeed:
    def __init__(self, t_ts, t_px):
        self.ts = np.asarray(t_ts, dtype=np.int64); self.px = np.asarray(t_px, dtype=float)
        self._cache = {}
        self._tf = {}

    def _bars(self, tf):
        b = self._tf.get(tf)
        if b is None:
            cid = self.ts // (tf * 60_000)
            u, first = np.unique(cid, return_index=True)
            last = np.concatenate([first[1:], [len(self.ts)]]) - 1
            hi = np.maximum.reduceat(self.px, first); lo = np.minimum.reduceat(self.px, first)
            cl = self.px[last]
            b = self._tf[tf] = dict(u=u, first=first, last=last, hi=hi, lo=lo, cl=cl)
        return b

    def at(self, i, tf):
        """CCI at trade index i (inclusive) on the tf-minute candles."""
        key = (i, tf)
        v = self._cache.get(key)
        if v is not None:
            return v
        b = self._bars(tf)
        cid = self.ts[i] // (tf * 60_000)
        k = int(np.searchsorted(b["u"], cid))           # index of the forming candle
        if k >= len(b["u"]) or b["u"][k] != cid:
            return float("nan")
        k_lo = max(0, k - (WINDOW - 1))
        if k - k_lo < PERIOD:
            return float("nan")
        hi = b["hi"][k_lo:k].copy(); lo = b["lo"][k_lo:k].copy(); cl = b["cl"][k_lo:k].copy()
        seg = self.px[b["first"][k]:i + 1]
        hi = np.append(hi, seg.max()); lo = np.append(lo, seg.min()); cl = np.append(cl, seg[-1])
        v = float(talib.CCI(hi, lo, cl, timeperiod=PERIOD)[-1])
        self._cache[key] = v
        return v
