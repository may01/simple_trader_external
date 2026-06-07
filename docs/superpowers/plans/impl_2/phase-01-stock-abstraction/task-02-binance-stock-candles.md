# Task 02: BinanceStock — Candle Fetching

**Phase:** 01 — Stock Abstraction  
**Depends on:** Task 01 (BaseStock)  
**Produces:** `stocks/binance_stock.py` — `Stock_Binance.get_candles_history()` working end-to-end

---

## Goal

Implement `Stock_Binance.__init__()` and `get_candles_history()`. This is the candle-fetching half of the Binance adapter — the core of the live data path.

---

## Context

`get_candles_history()` is called every tick in live trading. It fetches 1-min, 15-min, 1-hour, and 12-hour klines from Binance, builds DataFrames, and returns `Dict[tf → DataFrame]` for all requested timeframes including resampled derivatives. Rate-limit weight is tracked per call and triggers a 60-second backoff when `overflow_weight` (5000) is exceeded.

---

## Files

- Create: `stocks/binance_stock.py`

---

## Interface

**Constructor:**
- `__init__()` — reads `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `PAIR`, `EXCHANGE_FEE` from env (exception if any absent); splits `PAIR` on `"_"` into `coin`/`coin_base` (e.g., `"link_usdt"` → `coin="link"`, `coin_base="usdt"`); calls `super().__init__(key, secret, coin, coin_base)`; initializes `BinanceClient`; sets `self.fee`; sets `was_init = True`

**Key methods:**
- `get_candles_history(time_list: list[int], coin: str, time_point: int = 0) -> dict[int, pd.DataFrame]`
- `get_candles_range(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame` — fetches 1-min klines from `start_ms` to `end_ms` (Unix ms) in 30-day chunks via `BinanceClient.get_historical_klines()`; returns DataFrame with columns `open_time, o, h, l, c, v, close_time, taker_base_vol`; same chunking and atomic-merge logic as `grab_binance.py`; `symbol` is Binance format (e.g. `"LINKUSDT"`)

**Internal helpers:**
- `_fetch_klines(interval: str, lookback: str) -> pd.DataFrame` — single Binance API call + DataFrame construction
- `_resample_to_tf` — inherited from `StockInterface`; do not re-implement

---

## Candle Fetching Logic

Four base Binance intervals fetched (hardcoded lookback periods):
| Interval | Lookback | Derived TFs |
|----------|----------|-------------|
| 1-min | 10 hours ago | `[1]` and any requested TF resampleable from 1-min |
| 15-min | 4 days ago | `[15]` and derived TFs |
| 1-hour | 43 days ago | `[60, 240]` |
| 12-hour | 121 days ago | `[1440]` |

**DataFrame columns after parsing:**
`open_time`, `open`, `high`, `low`, `close`, `volume`, `close_time`, `qav`, `num_trades`, `taker_base_vol`, `taker_quote_vol`, `ignore`

**Post-processing:**
- Convert Unix timestamps to datetime index
- Forward-fill missing rows (zero-volume candles)
- Resample base intervals to all requested TFs using `{'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}`
- Keep last 120 candles per TF

**Weight tracking:**
- +2 per `get_historical_klines()` call
- If `self.weight > self.overflow_weight`: sleep `overflow_weight_time` seconds, reset counter

---

## Key Constraints

- `fee` must be read from `EXCHANGE_FEE` env var — NO hardcoded fallback. Missing env var = constructor exception
- `PAIR` env var format is `coin_coinbase` (e.g., `"link_usdt"`, `"btc_busd"`) — split on `"_"` gives `coin` and `coin_base`; system supports any base currency
- `get_pair_name()` returns `(coin + coin_base).upper()` — e.g., `"LINKUSDT"`, `"BTCBUSD"`
- Returns dict keyed by integer minutes — `{1: df, 5: df, 15: df, 60: df, 240: df, 1440: df}`
- All price/volume columns must be `float64`

---

## Verification

```bash
# Requires BINANCE_API_KEY and BINANCE_API_SECRET in host env
docker compose run --rm live python3 -c "
from stocks_holder import do_stock_init, stock_holder as stock
do_stock_init('binance')
result = stock.item.get_candles_history([1, 5, 15], 'link')
assert set(result.keys()) >= {1, 5, 15}
assert len(result[1]) > 0
print('candle fetch ok, rows:', len(result[1]))
"
```

---

## Commit

`feat: implement Stock_Binance candle fetching`
